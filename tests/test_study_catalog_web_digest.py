"""Browser delivery SHA worker transport preserves the original digest contract."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from tests import test_lan_sha256 as original_contract

HARNESS = original_contract.HARNESS
SOURCE_SENTENCE = original_contract.SOURCE_SENTENCE
SOURCE_SHA256 = original_contract.SOURCE_SHA256

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'anki_pipeline/templates/lan-sha256.js'
NODE = shutil.which('node')

WORKERS = r'''
const blobs=new Map(),stats={created:0,active:0,peak:0,posted:[],terminated:0};let nextURL=0;
function workerContext(options={}){
 const context=sandbox();
 context.Blob=class{constructor(parts){this.source=parts.join('')}};
 context.URL={createObjectURL(blob){const id='blob:test/'+(++nextURL);blobs.set(id,blob.source);return id},revokeObjectURL(id){blobs.delete(id)}};
 context.setTimeout=(fn,ms)=>setTimeout(fn,options.fastTimeout&&ms>=1000?20:ms);context.clearTimeout=clearTimeout;
 context.Worker=class{
  constructor(url){if(options.constructorFail)throw Error('worker blocked');this.source=blobs.get(url);this.closed=false;stats.created++}
  terminate(){this.closed=true;stats.terminated++}
  postMessage(message,transfer){
   if(options.postFail)throw Error('transfer blocked');
   stats.posted.push({id:message.id,bytes:message.bytes.byteLength,transfer:transfer?.length});
   const copied=structuredClone(message,{transfer});stats.active++;stats.peak=Math.max(stats.peak,stats.active);
   if(options.never)return;
   setTimeout(()=>{if(this.closed){stats.active--;return}
    if(options.error){stats.active--;this.onerror?.({message:'worker failed',preventDefault(){}});return}
    if(options.messageError){stats.active--;this.onmessageerror?.({});return}
    if(options.badResult){stats.active--;this.onmessage?.({data:{id:copied.id,result:new ArrayBuffer(31)}});return}
    const worker={Uint8Array,Uint32Array,ArrayBuffer,DataView,self:{postMessage:(answer,transfers)=>{
      if(options.wrongFirst)this.onmessage?.({data:{...answer,id:answer.id+999}});
      const result=structuredClone(answer,{transfer:transfers});stats.active--;this.onmessage?.({data:result});
    }}};
    try{vm.runInNewContext(this.source,worker);worker.self.onmessage({data:copied})}catch(error){stats.active--;this.onerror?.({message:error.message,preventDefault(){}})}
   },copied.id%2?12:1);
  }
 };
 return context;
}
'''


class StudyDeliveryDigestTests(original_contract.LanSha256Tests):
    def run_node(self, body):
        self.assertIsNotNone(NODE)
        result = subprocess.run([NODE, '-e', HARNESS.replace('__TEST_BODY__', body)],
            input=json.dumps({'script': str(SCRIPT), 'sentence': SOURCE_SENTENCE,
                              'sentenceHash': SOURCE_SHA256}),
            capture_output=True, text=True, cwd='/tmp', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_fips_compression_and_buffer_copy_code_are_unchanged(self):
        original = (ROOT / 'scripts/lan_sha256.js').read_text()
        current = SCRIPT.read_text()
        for name in ('copyBufferSource', 'sha256'):
            pattern = r'  function ' + name + r'\([^\n]*\) \{[\s\S]*?\n  \}'
            self.assertEqual(re.search(pattern, current)[0], re.search(pattern, original)[0])
        constants = r'const ROUND_CONSTANTS = new Uint32Array\(\[[\s\S]*?\]\);'
        self.assertEqual(re.search(constants, current)[0], re.search(constants, original)[0])

    def test_large_digests_use_at_most_two_workers_and_match_exact_snapshots(self):
        self.run_node(WORKERS + r'''
const context=install(workerContext({wrongFirst:true})),arrays=Array.from({length:6},(_,n)=>Uint8Array.from({length:300000+n*13},(_,i)=>(i+n*19)&255));
const hashes=arrays.map(expected),jobs=arrays.map(value=>digest(context,'SHA-256',value));
assert.equal(stats.created,2,'large concurrent hashes must use a bounded worker pool');
for(const bytes of arrays){assert.ok(bytes.buffer.byteLength>0,'caller buffer was detached');bytes.fill(0)}
assert.deepEqual(await Promise.all(jobs.map(p=>p.then(hex))),hashes);
assert.equal(stats.peak,2);assert.ok(stats.posted.every(p=>p.transfer===1));
assert.equal(new Set(stats.posted.map(p=>p.id)).size,arrays.length);
''')

    def test_old_lan_polyfill_does_not_prevent_the_worker_upgrade(self):
        original = json.dumps((ROOT / 'scripts/lan_sha256.js').read_text())
        self.run_node(WORKERS + '\nconst original=' + original + r''';
const context=workerContext();vm.runInNewContext(original,context);const previous=context.crypto.subtle.digest;install(context);
assert.notEqual(context.crypto.subtle.digest,previous);const bytes=new Uint8Array(300000).fill(71);
assert.equal(hex(await digest(context,'SHA-256',bytes)),expected(bytes));assert.equal(stats.created,1);
''')

    def test_worker_failures_and_saturation_fall_back_without_changing_the_hash(self):
        self.run_node(WORKERS + r'''
for(const options of [{constructorFail:true},{postFail:true},{error:true},{messageError:true},{badResult:true},{never:true,fastTimeout:true}]){
 const context=install(workerContext(options)),bytes=Uint8Array.from({length:300001},(_,i)=>i&255),want=expected(bytes),job=digest(context,'SHA-256',bytes);bytes.fill(0);assert.equal(hex(await job),want);
 // Recovery disables workers for the page. Subsequent local calls must keep
 // padding boundaries, byte-view offsets and immediate snapshot semantics.
 const posted=stats.posted.length;
 for(const length of [0,55,56,63,64,65,119,120,127,128,129,300003]){
  const backing=Uint8Array.from({length:length+8},(_,i)=>(i*73+191)&255),view=new DataView(backing.buffer,3,length),reference=expected(backing.subarray(3,3+length)),pending=digest(context,'SHA-256',view);
  backing.fill(0);assert.equal(hex(await pending),reference);
 }
 assert.equal(stats.posted.length,posted,'recovery unexpectedly retried a failed worker');
}
const context=install(workerContext()),bytes=new Uint8Array(300002).fill(89),wanted=expected(bytes),postedBefore=stats.posted.length,createdBefore=stats.created;
const all=Array.from({length:20},()=>digest(context,'SHA-256',bytes).then(hex));assert.equal(stats.posted.length-postedBefore,2);
assert.deepEqual(await Promise.all(all),Array(20).fill(wanted));assert.equal(stats.created-createdBefore,2);
assert.equal(stats.posted.length-postedBefore,8,'overflow requests must not accumulate in an unbounded worker queue');
''')

    def test_actual_threads_compute_without_blocking_the_calling_event_loop(self):
        self.run_node(r'''
const {Worker}=require('node:worker_threads'),blobs=new Map();let made=0;
const context=sandbox();context.setTimeout=setTimeout;context.clearTimeout=clearTimeout;
context.Blob=class{constructor(parts){this.source=parts.join('')}};
context.URL={createObjectURL(blob){blobs.set('blob:hash',blob.source);return 'blob:hash'},revokeObjectURL(){}};
context.Worker=class{
 constructor(url){made++;this.worker=new Worker("const {parentPort}=require('node:worker_threads');global.self={postMessage:(value,transfer)=>parentPort.postMessage(value,transfer)};parentPort.on('message',value=>self.onmessage({data:value}));"+blobs.get(url),{eval:true});this.worker.unref();this.worker.on('message',data=>this.onmessage?.({data}));this.worker.on('error',error=>this.onerror?.({message:error.message,preventDefault(){}}));this.worker.unref()}
 postMessage(value,transfer){this.worker.postMessage(value,transfer)}terminate(){this.worker.terminate()}
};
install(context);const bytes=require('node:crypto').randomFillSync(new Uint8Array(8*1024*1024)),reference=expected(bytes);
let ticked=false;const tick=new Promise(resolve=>setTimeout(()=>{ticked=true;resolve()},0));
const work=Promise.all([digest(context,'SHA-256',bytes),digest(context,'SHA-256',bytes)]);
assert.equal(made,2);await tick;assert.ok(ticked);assert.deepEqual((await work).map(hex),[reference,reference]);
''')

    def test_worker_fast_core_matches_native_vectors_padding_and_offsets(self):
        self.run_node(WORKERS + r'''
const context=workerContext();vm.runInNewContext(source.replace('const WORKER_THRESHOLD = 256 * 1024;', 'const WORKER_THRESHOLD = 0;'),context);
for(const text of ['', 'abc', 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq', 'a'.repeat(1000000), input.sentence, '中文😀']){
 const bytes=new TextEncoder().encode(text);assert.equal(hex(await digest(context,'SHA-256',bytes)),expected(bytes));
}
for(const length of [1,...Array.from({length:11},(_,i)=>55+i),119,120,127,128,129]){
 const backing=Uint8Array.from({length:length+8},(_,i)=>(i*73+191)&255),view=new DataView(backing.buffer,3,length);
 assert.equal(hex(await digest(context,'SHA-256',view)),expected(backing.subarray(3,3+length)));
}
assert.ok(stats.posted.length>=20,'small boundary cases must exercise the worker-only core');
''')
