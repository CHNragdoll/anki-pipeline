"""The shared artifact transport authenticates text before optional JSON parsing."""
import json
import shutil
import subprocess
import unittest

from anki_pipeline import study_catalog_web as web


CONTRACT = r'''
const assert=require('node:assert/strict'),fs=require('node:fs');
const {createHash}=require('node:crypto'),{gzipSync}=require('node:zlib');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const hash=text=>createHash('sha256').update(text).digest('hex');
const origin=new URL('http://example.test/book/index.html');
function stream(bytes,onCancel=()=>{}){
 let at=0;
 return new ReadableStream({pull(controller){
  // Single bytes exercise UTF-8 sequences split over real stream reads.
  if(at===bytes.length)controller.close();else controller.enqueue(bytes.subarray(at,++at));
 },cancel:onCancel});
}
function response(text,options={}){
 const bytes=options.gzip?gzipSync(Buffer.from(text)):Buffer.from(text);
 return new Response(stream(bytes,options.cancel),{headers:options.headers||{}});
}
function setup(fetcher,{decompress=DecompressionStream,onHash=()=>{}}={}){
 const calls=[],events=[];
 const fetch=async(url,options)=>{calls.push(url);return fetcher(url,options)};
 const matches=async(text,pin)=>{events.push('hash');onHash();return hash(text)===pin};
 const parsed={parse(text){events.push('parse');return JSON.parse(text)}};
 const api=new Function('fetch','knownPinMatches','DecompressionStream','Response',
  'TextDecoder','URL','location','DOMException','JSON',input.helpers+'\n'+input.safeURL+
  ';return {text:typeof verifiedArtifactText==="function"?verifiedArtifactText:null,json:deliveryArtifact};'
 )(fetch,matches,decompress,Response,TextDecoder,URL,origin,DOMException,parsed);
 return {api,calls,events};
}
const rule=(text,gzip=false)=>({src:'plain.txt',...(gzip?{gzipSrc:'packed.gz'}:{}),sha256:hash(text)});
const path=url=>new URL(url).pathname;
let contracts=0;
(async()=>{
 {
  const text='<article>原句 α 🧪 &amp; unchanged</article>\n';
  const f=setup(async()=>response(text));
  assert.equal(typeof f.api.text,'function','a reusable authenticated text API must exist');
  assert.equal(await f.api.text(rule(text),undefined,1024),text);
  assert.deepEqual(f.calls,['http://example.test/book/plain.txt']);
  assert.deepEqual(f.events,['hash'],'text transport must not parse HTML as JSON');contracts++;
 }
 {
  const text='原生 gzip HTML 🧪';const f=setup(async()=>response(text,{gzip:true}));
  assert.equal(await f.api.text(rule(text,true),undefined,1024),text);
  assert.deepEqual(f.calls,['http://example.test/book/packed.gz']);
  assert.deepEqual(f.events,['hash']);contracts++;
 }
 {
  const text='browser already decoded gzip α';
  const f=setup(async()=>response(text,{headers:{'Content-Encoding':'gzip'}}));
  assert.equal(await f.api.text(rule(text,true)),text);
  assert.equal(f.calls.length,1,'Content-Encoding gzip must not be decoded twice');contracts++;
 }
 {
  const expected='original text',f=setup(async()=>response('changed text',{gzip:true}));
  await assert.rejects(f.api.text(rule(expected,true)),/Prepared artifact SHA differs/);
  assert.deepEqual(f.calls,['http://example.test/book/packed.gz'],
   'decoded content SHA failure must not retry as plain content');
  assert.deepEqual(f.events,['hash']);contracts++;
 }
 {
  const text='plain fallback when gzip API unavailable';
  const unavailable=setup(async()=>response(text),{decompress:null});
  assert.equal(await unavailable.api.text(rule(text,true)),text);
  assert.deepEqual(unavailable.calls,['http://example.test/book/plain.txt']);contracts++;
 }
 {
  const text='fallback only after gzip HTTP failure';
  const f=setup(async url=>path(url).endsWith('.gz')?new Response('missing',{status:404}):response(text));
  assert.equal(await f.api.text(rule(text,true)),text);
  assert.deepEqual(f.calls,['http://example.test/book/packed.gz','http://example.test/book/plain.txt']);
  assert.deepEqual(f.events,['hash']);contracts++;
 }
 {
  const text='fallback after unavailable gzip representation';
  const f=setup(async url=>path(url).endsWith('.gz')?response('not gzip'):response(text));
  assert.equal(await f.api.text(rule(text,true)),text);
  assert.equal(f.calls.length,2);assert.deepEqual(f.events,['hash']);contracts++;
 }
 {
  const controller=new AbortController();let began=false;
  const f=setup((url,options)=>{
   began=true;assert.equal(options.signal,controller.signal);
   return new Promise((resolve,reject)=>options.signal.addEventListener('abort',
    ()=>reject(new DOMException('superseded','AbortError')),{once:true}));
  });
  const pending=f.api.text(rule('unused',true),controller.signal);assert.equal(began,true);
  controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');
  assert.deepEqual(f.calls,['http://example.test/book/packed.gz']);
  assert.deepEqual(f.events,[]);contracts++;
 }
 {
  const text='decoded budget α 🧪',f=setup(async()=>response(text,{gzip:true}));
  await assert.rejects(f.api.text(rule(text,true),undefined,1),error=>error.name==='StudyPrefetchLimit');
  assert.deepEqual(f.calls,['http://example.test/book/packed.gz'],
   'decoded budget failure must not trigger an unbounded fallback');
  assert.deepEqual(f.events,[]);contracts++;
 }
 {
  let cancelled=false;const text='plain streaming budget';
  const f=setup(async()=>response(text,{cancel(){cancelled=true}}));
  await assert.rejects(f.api.text(rule(text),undefined,1),error=>error.name==='StudyPrefetchLimit');
  assert.equal(cancelled,true,'budget failure must cancel the unread stream');
  assert.deepEqual(f.events,[]);contracts++;
 }
 {
  const text='not JSON: 释义 🧪',f=setup(async()=>response(text));
  assert.equal(await f.api.text(rule(text)),text);
  assert.deepEqual(f.events,['hash']);
  await assert.rejects(f.api.json(rule(text)),SyntaxError);
  assert.deepEqual(f.events,['hash','hash','parse']);
  const good='{"source":"原文 🧪","count":3}',g=setup(async()=>response(good,{gzip:true}));
  assert.deepEqual(await g.api.json(rule(good,true),undefined,1024),JSON.parse(good));
  assert.deepEqual(g.events,['hash','parse']);contracts++;
 }
 {
  const f=setup(async()=>response('{"changed":true}'));
  await assert.rejects(f.api.json(rule('{"original":true}')),/SHA differs/);
  assert.deepEqual(f.events,['hash'],'JSON parsing must not precede complete decoded SHA');contracts++;
 }
 {
  const f=setup(async()=>{throw Error('unsafe URL reached fetch')});
  await assert.rejects(f.api.text({...rule('unused'),src:'https://other.test/content'}),/地址无效/);
  assert.deepEqual(f.calls,[]);contracts++;
 }
 {
  const controller=new AbortController(),f=setup(async()=>({ok:true,text:async()=>{
   controller.abort();return 'obsolete decoded content';
  }}));
  await assert.rejects(f.api.text(rule('obsolete decoded content'),controller.signal),
   error=>error.name==='AbortError');
  assert.deepEqual(f.events,[],'obsolete read must not hash or parse');contracts++;
 }
 {
  const controller=new AbortController(),text='{"obsolete":true}';
  const f=setup(async()=>response(text),{onHash(){
   // The extracted async text layer adds a continuation before JSON parsing.
   queueMicrotask(()=>queueMicrotask(()=>controller.abort()));
  }});
  await assert.rejects(f.api.json(rule(text),controller.signal),error=>error.name==='AbortError');
  assert.deepEqual(f.events,['hash'],'the new text/JSON await boundary must recheck its owner');contracts++;
 }
 console.log(JSON.stringify({passed:true,contracts}));
})().catch(error=>{console.error(error);process.exit(1)});
'''


@unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
class VerifiedArtifactTextTests(unittest.TestCase):
    def test_authenticated_text_and_legacy_json_share_stream_transport(self):
        begin = web.HOST_RUNTIME.index('function deliveryAborted(')
        end = web.HOST_RUNTIME.index('async function preparedRule(', begin)
        safe_begin = web.HOST_RUNTIME.index('function safeURL(')
        safe_end = web.HOST_RUNTIME.index('\n', safe_begin)
        result = subprocess.run(
            [shutil.which('node'), '-e', CONTRACT],
            input=json.dumps({'helpers': web.HOST_RUNTIME[begin:end],
                              'safeURL': web.HOST_RUNTIME[safe_begin:safe_end]}),
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True, 'contracts': 15})


if __name__ == '__main__':
    unittest.main()
