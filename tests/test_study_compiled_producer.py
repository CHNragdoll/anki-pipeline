"""Small producer boundary checks; never run a maximum-card fixture."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PRODUCER = ROOT / 'anki_pipeline/compiled/semantic-producer.cjs'
SERIALIZER = ROOT / 'anki_pipeline/compiled/stream-serializer.mjs'
ORIGINAL = 'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'
PREPARED = '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'


def digest(raw):
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()


def artifact():
    html = '<html><head><base href="../media/"></head><body>中文 🌕 e\u0301\n</body></html>'
    proof = {'source_sha256': digest(html), 'expanded_sha256': digest(html),
             'source_bytes': len(html.encode()), 'expanded_bytes': len(html.encode()),
             'registry_pins': [], 'original_source_unmodified': True}
    side = {'html': html, 'registry': {}, 'children': [], 'proof': proof}
    return {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': digest('wrapper'),
            'source_payload_sha256': digest('payload'), 'sides': [side, side],
            'modules': {ORIGINAL: {'src': 'evidence/native.js', 'sha256': PREPARED,
                                   'original_sha256': ORIGINAL}}}


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledProducerTests(unittest.TestCase):
    def node(self, source, value=None):
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=ROOT,
                                input=json.dumps(value), text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_prepared_back_source_registry_and_module_binding_are_checked(self):
        self.node(r"""
const assert=require('node:assert/strict'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
const a=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
const source={wrapper_sha256:a.source_wrapper_sha256,payload_sha256:a.source_payload_sha256};
const module={original_sha256:Object.keys(a.modules)[0],sha256:Object.values(a.modules)[0].sha256};
assert.equal(p.validateArtifact(a,source,module).side.html,a.sides[1].html);
for(const edit of [x=>x.schema='other',x=>x.source_payload_sha256='0'.repeat(64),x=>x.sides[1].html+='x',
 x=>x.sides[1].proof.expanded_bytes++,x=>x.sides[1].registry['f'.repeat(64)]='wrong',
 x=>x.sides[1].proof.registry_pins=['f'.repeat(64)],x=>x.modules[module.original_sha256].sha256='0'.repeat(64)]){
 const copy=structuredClone(a);edit(copy);assert.throws(()=>p.validateArtifact(copy,source,module));
}
""", artifact())

    def test_local_resource_manifest_is_closed_and_uses_authenticated_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            resource = root / 'data.js'
            resource.write_text('原文\n', encoding='utf-8')
            self.node(r"""
(async()=>{const assert=require('node:assert/strict'),fs=require('node:fs'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
const input=JSON.parse(fs.readFileSync(0,'utf8')),url='https://example.test/book/media/data.js';
const read=p.createResourceResolver({[url]:input},'https://example.test/book/');
assert.equal(await read(url,input.sha256),'原文\n');fs.writeFileSync(input.path,'changed after snapshot');
assert.equal(await read(url,input.sha256),'原文\n');
await assert.rejects(read(url,'0'.repeat(64)),/pin|SHA/);
await assert.rejects(read('https://example.test/book/media/unknown.js',input.sha256),/Unknown/);
await assert.rejects(read('https://elsewhere.test/book/media/data.js',input.sha256));
await assert.rejects(read(url+'?secret=x',input.sha256));
assert.throws(()=>p.createResourceResolver({'https://example.test/other/a.js':input},'https://example.test/book/'));
})().catch(e=>{console.error(e);process.exitCode=1});
""", {'path': str(resource), 'sha256': digest(resource.read_bytes())})

    def test_capture_hooks_are_four_unique_reversible_read_only_exports(self):
        self.node(r"""
const assert=require('node:assert/strict'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
const source=p.CAPTURE_EDITS.map(x=>x[0]).join('\n');const result=p.instrument(source);
assert.equal(result.edits.length,4);assert.equal(result.inverse,source);
assert.equal((result.code.match(/__canonicalProducerCapture\(/g)||[]).length,4);
assert.throws(()=>p.instrument(source+source),/boundary/);
assert.throws(()=>p.instrument(source.replace(p.CAPTURE_EDITS[0][0],'drift')),/boundary/);
assert.ok(!result.code.includes('records:Array.from(records)'));
""")

    def test_streaming_serializer_matches_parse5_without_coalescing_source(self):
        self.node(r"""
(async()=>{const assert=require('node:assert/strict'),{pathToFileURL}=require('node:url');
const p=await import('parse5'),{serializeToSink}=await import(pathToFileURL(process.cwd()+'/anki_pipeline/compiled/stream-serializer.mjs'));
for(const html of ['<!doctype html><p>中文 🌕 é &amp; <b a="&quot;">X</b></p>',
 '<template><p>nested</p><template>x</template></template><script>if(a<2){b="&"}</script>',
 '<svg><use xlink:href="#a"></use><foreignObject><div>html</div></foreignObject></svg>',
 '<!--audit--><input value="x"><noscript><b>raw</b></noscript>']){
 const doc=p.parse(html),chunks=[];serializeToSink(doc,{},x=>chunks.push(x));assert.equal(chunks.join(''),p.serialize(doc));
}
const {JSDOM}=require('jsdom'),utils=require('jsdom/lib/generated/idl/utils'),adapter=require('jsdom/lib/jsdom/living/domparsing/parse5-adapter-serialization');
const dom=new JSDOM('<!doctype html><p>中文 &amp; x</p><script type="application/json">{"x":"<x>"}</script>');
const chunks=[];serializeToSink(utils.implForWrapper(dom.window.document),{treeAdapter:adapter,scriptingEnabled:true},x=>chunks.push(x));
assert.equal(chunks.join(''),dom.serialize());dom.window.close();
})().catch(e=>{console.error(e);process.exitCode=1});
""")

    def test_bad_input_pin_and_existing_output_fail_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_path = root / 'artifact.json'
            artifact_path.write_text(json.dumps(artifact()), encoding='utf-8')
            module_path = root / 'module.js'
            module_path.write_text('not a verified prepared module', encoding='utf-8')
            helpers_path = root / 'helpers.js'
            helpers_path.write_text('throw Error("must never execute");', encoding='utf-8')
            request = {'schema': 'study-compiled-semantic-request.v1',
                       'artifact': {'path': str(artifact_path), 'sha256': '0' * 64},
                       'module': {'path': str(module_path), 'sha256': PREPARED, 'original_sha256': ORIGINAL},
                       'source': {'wrapper_sha256': digest('wrapper'), 'payload_sha256': digest('payload')},
                       'helpers': {'path': str(helpers_path), 'sha256': digest(helpers_path.read_bytes())},
                       'base_url': 'https://example.test/book/media/',
                       'source_url': 'https://example.test/book/index.html', 'resources': {},
                       'policy': {'external': {}, 'inline': []}}
            request_path = root / 'request.json'
            request_path.write_text(json.dumps(request), encoding='utf-8')
            output = root / 'new-output'
            command = [shutil.which('node'), str(PRODUCER), str(request_path), str(output)]
            failed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=15)
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('SHA', failed.stderr)
            self.assertFalse(output.exists(), 'authentication must precede output creation')
            output.mkdir()
            kept = output / 'user.txt'
            kept.write_text('keep me', encoding='utf-8')
            failed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=15)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(kept.read_text(), 'keep me')
            self.assertEqual(sorted(p.name for p in output.iterdir()), ['user.txt'])

    def test_utf8_sink_preserves_split_surrogates_and_hashes_written_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(r"""
(async()=>{const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),{pathToFileURL}=require('node:url');
const directory=JSON.parse(fs.readFileSync(0,'utf8'));
const {parse,serialize}=await import('parse5');
const {serializeToSink,createUtf8Sink}=await import(pathToFileURL(process.cwd()+'/anki_pipeline/compiled/stream-serializer.mjs'));
const cases=[['\ud83d','\ude00'],['\ud83d','','','\ude00'],['\ud83d'],['\ude00'],
 ['a\ud83d',''],['\ud83d','x'],['\ud83d','\ud83d','\ude00'],['\ude00','\ud83d',''],
 ['中文 ','\ud83d','\ude00',' é\n'],['','']];
for(const [index,chunks] of cases.entries()){
 const filename=directory+'/'+index+'.bin',fd=fs.openSync(filename,'wx'),sha=crypto.createHash('sha256');let bytes=0;
 const sink=createUtf8Sink(buffer=>{assert.ok(Buffer.isBuffer(buffer));fs.writeSync(fd,buffer);sha.update(buffer);bytes+=buffer.length});
 try{for(const chunk of chunks)sink.write(chunk);sink.end()}finally{fs.closeSync(fd)}
 const expected=Buffer.from(chunks.join(''),'utf8'),actual=fs.readFileSync(filename);
 assert.deepEqual(actual,expected);assert.equal(bytes,expected.length);
 assert.equal(sha.digest('hex'),crypto.createHash('sha256').update(expected).digest('hex'));
 assert.throws(()=>sink.write('late'),/closed/);assert.throws(()=>sink.end(),/closed/);
}
// The exact review reproduction: adjacent parse5 Text nodes, not one input string.
const ast=parse('<p></p>'),paragraph=ast.childNodes[0].childNodes[1].childNodes[0];
paragraph.childNodes=[{nodeName:'#text',value:'\ud83d',parentNode:paragraph},{nodeName:'#text',value:'\ude00',parentNode:paragraph}];
const chunks=[],sink=createUtf8Sink(buffer=>chunks.push(buffer));serializeToSink(ast,{},sink.write);sink.end();
assert.deepEqual(Buffer.concat(chunks),Buffer.from(serialize(ast),'utf8'));
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_unknown_module_cohort_is_rejected_before_output(self):
        self.node(r"""
const assert=require('node:assert/strict'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
assert.throws(()=>p.validateModule({original_sha256:'f'.repeat(64),sha256:'e'.repeat(64)}),/Unsupported/);
assert.throws(()=>p.validateModule({original_sha256:'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',sha256:'e'.repeat(64)}),/prepared|SHA/);
""")

    def test_actual_output_writer_retries_short_writes_and_rejects_no_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(r"""
(async()=>{const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),{pathToFileURL}=require('node:url');
const {writeAll}=require('./anki_pipeline/compiled/semantic-producer.cjs'),directory=JSON.parse(fs.readFileSync(0,'utf8'));
const {createUtf8Sink}=await import(pathToFileURL(process.cwd()+'/anki_pipeline/compiled/stream-serializer.mjs'));
const fd=fs.openSync(directory+'/short.bin','wx'),hash=crypto.createHash('sha256');let writes=0,bytes=0;
const sink=createUtf8Sink(buffer=>{bytes+=writeAll(fd,buffer,(actualFd,value,offset,length)=>{
 writes++;return fs.writeSync(actualFd,value,offset,Math.min(1,length));});hash.update(buffer)});
try{sink.write('中文 ');sink.write('\ud83d');sink.write('');sink.write('\ude00\n');sink.end()}finally{fs.closeSync(fd)}
const expected=Buffer.from('中文 😀\n');assert.deepEqual(fs.readFileSync(directory+'/short.bin'),expected);
assert.equal(bytes,expected.length);assert.equal(writes,expected.length);
assert.equal(hash.digest('hex'),crypto.createHash('sha256').update(expected).digest('hex'));
for(const result of [0,-1,NaN,0.5,2])assert.throws(()=>writeAll(0,Buffer.from('x'),()=>result),/Incomplete/);
const failure=Error('disk failed');assert.throws(()=>writeAll(0,Buffer.from('x'),()=>{throw failure}),e=>e===failure);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_actual_output_publish_never_overwrites_a_competing_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
const directory=JSON.parse(fs.readFileSync(0,'utf8')),partial=directory+'/output.partial',final=directory+'/output.html';
const text='our complete bytes',fd=fs.openSync(partial,'wx+');p.writeAll(fd,Buffer.from(text));
const expected={bytes:Buffer.byteLength(text),sha256:crypto.createHash('sha256').update(text).digest('hex')};
try{
// A competing writer appears after our partial was opened and completed.
fs.writeFileSync(final,'foreign final',{flag:'wx'});
assert.throws(()=>p.publishNoReplace(partial,final,fd,expected),e=>e.code==='EEXIST');
assert.equal(fs.readFileSync(final,'utf8'),'foreign final');assert.equal(fs.readFileSync(partial,'utf8'),'our complete bytes');
const next=directory+'/new.html';p.publishNoReplace(partial,next,fd,expected);
assert.equal(fs.readFileSync(next,'utf8'),'our complete bytes');assert.equal(fs.existsSync(partial),false);
assert.equal(fs.readFileSync(final,'utf8'),'foreign final');
}finally{fs.closeSync(fd)}
""", tmp)

    def test_actual_publish_binds_open_inode_and_preserves_replaced_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
const directory=JSON.parse(fs.readFileSync(0,'utf8')),text='our complete bytes';
const expected={bytes:Buffer.byteLength(text),sha256:crypto.createHash('sha256').update(text).digest('hex')};
const originalLink=fs.linkSync;
for(const when of ['before-call','before-link','after-link','content-change']){
 const partial=directory+'/'+when+'.partial',final=directory+'/'+when+'.html',fd=fs.openSync(partial,'wx+');
 p.writeAll(fd,Buffer.from(text));
 const replace=()=>{fs.unlinkSync(partial);fs.writeFileSync(partial,'foreign replacement',{flag:'wx'})};
 try{
  if(when==='before-call')replace();
  else if(when==='content-change')fs.writeSync(fd,Buffer.from('X'),0,1,0);
  else fs.linkSync=function(from,to){if(when==='before-link')replace();originalLink(from,to);if(when==='after-link')replace()};
  if(when==='after-link'){
   p.publishNoReplace(partial,final,fd,expected);
   assert.equal(fs.readFileSync(final,'utf8'),text,'published inode must be this open writer');
  }else{
   assert.throws(()=>p.publishNoReplace(partial,final,fd,expected),/ownership|content/);
   if(when==='before-link')assert.equal(fs.readFileSync(final,'utf8'),'foreign replacement','failed publication must not delete foreign final');
   else assert.equal(fs.existsSync(final),false);
  }
  if(when!=='content-change')assert.equal(fs.readFileSync(partial,'utf8'),'foreign replacement','foreign partial must remain');
 }finally{fs.linkSync=originalLink;fs.closeSync(fd)}
}
""", tmp)

    def test_complete_answer_may_reference_one_verified_module_twice(self):
        self.node(r"""
const assert=require('node:assert/strict'),p=require('./anki_pipeline/compiled/semantic-producer.cjs');
assert.equal(p.nativeScriptReferences([{pin:'native'},{pin:'visual'},{pin:'native'}],'native'),2);
assert.throws(()=>p.nativeScriptReferences([{pin:'visual'}],'native'),/census/);
""")


if __name__ == '__main__':
    unittest.main()
