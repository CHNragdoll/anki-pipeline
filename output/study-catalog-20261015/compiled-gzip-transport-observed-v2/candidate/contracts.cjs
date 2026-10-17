"use strict";
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),zlib=require('node:zlib'),vm=require('node:vm');
const root=__dirname,read=name=>fs.readFileSync(root+'/'+name,'utf8'),sha=text=>crypto.createHash('sha256').update(text).digest('hex');
const baseline=read('baseline-candidate-frame.js'),candidate=read('candidate-frame.js'),helper=read('transport.js'),doc={baseURI:'http://example.test/book/index.html'};
const body='<article>完整原文 α 🧪 &amp; unchanged</article>\n'.repeat(20);
function asset(text,kind='body.html'){return{src:'_qa_compiled_test_'+kind,sha256:sha(text),gzipSrc:'_qa_compiled_test_'+kind+'.gz'}}
function response(text,{gzip=false,status=200,headers={}}={}){return new Response(gzip?zlib.gzipSync(Buffer.from(text)):text,{status,headers})}
function setup(fetcher,{old=false,decompress=DecompressionStream,controller=new AbortController(),hashCheck=null,assets=null}={}){
 const calls=[],hashes=[],table=assets||{runtime:asset('runtime','runtime.js'),entries:{card:{html:asset(body),profile:asset('{}','profile.json')}}};
 const fetch=async(url,options)=>{calls.push({url,options});return fetcher(url,options,calls.length)};
 const matches=async(text,pin)=>{hashes.push([text,pin]);return hashCheck?hashCheck(text,pin):sha(text)===pin};
 const source=old?baseline:candidate,line=source.split('\n').find(x=>x.startsWith('async function resource('));
 const proofAt=source.indexOf('function verifiedResourceString('),proofSource=source.slice(proofAt,source.indexOf('\n}',proofAt)+2);assert.ok(proofAt>=0);
 const code='const scriptCache=new Map(),resourceProofs=new WeakMap();'+helper+'\n'+line+'\n'+proofSource+'\nconst compiledArtifactTransport=createCompiledArtifactTransport(compiledAssets,document,fetch,knownPinMatches,globalThis);return {resource,transport:compiledArtifactTransport,proof:(url,pin,text)=>verifiedResourceString(resource,url,pin,text),cache:scriptCache};';
 const api=new Function('fetch','knownPinMatches','document','URL','TextEncoder','frameAbort','compiledAssets','globalThis',code)(fetch,matches,doc,URL,TextEncoder,controller,table,{Response,TextDecoder,TextEncoder,DecompressionStream:decompress,DOMException});
 const rule=table.entries.card.html,url=new URL(rule.src,doc.baseURI).href;
 return{...api,calls,hashes,rule,url,controller,assets:table};
}
function load(x,rule=x.rule){return x.resource(new URL(rule.src,doc.baseURI).href,rule.sha256,null,rule)}
let count=0;async function check(name,fn){await fn();console.log('PASS',++count,name)}
async function red(){const x=setup(async()=>response(body),{old:true});assert.equal(await load(x),body);assert.ok(x.calls[0].url.endsWith('.gz'),'approved compiled asset must use explicit gzip representation instead of Range plain');}
async function main(){
 await check('real old resource is RED for explicit gzip, new resource preserves private proof and cache',async()=>{
  const x=setup(async()=>response(body,{gzip:true}));assert.equal(await load(x),body);assert.ok(x.calls[0].url.endsWith('.gz'));assert.equal(x.calls[0].options.headers,undefined);assert.equal(x.hashes.length,1);assert.equal(x.proof(x.url,x.rule.sha256,body),true);assert.equal(x.proof(x.url,x.rule.sha256,body+'!'),false);assert.equal(await x.resource(x.url,x.rule.sha256),body);assert.equal(x.calls.length,1);
 });
 await check('LAN HTML injection is avoided; missing gzip uses only original Range representation',async()=>{
  const injected=body.replace('<article>','<article><script>injected</script>');
  for(const missing of [false,true]){const x=setup(async(url,options)=>url.endsWith('.gz')?(missing?response('missing',{status:404}):response(body,{gzip:true})):response(options.headers?.Range==='bytes=0-'?body:injected));assert.equal(await load(x),body);assert.equal(x.calls.length,missing?2:1);if(missing)assert.equal(x.calls[1].options.headers.Range,'bytes=0-');}
 });
 await check('decoded wrong SHA rejects without plain retry; failed cache is retriable',async()=>{
  let bad=true;const x=setup(async()=>response(bad?body+'changed':body,{gzip:true}));await assert.rejects(load(x),/SHA differs/);assert.equal(x.calls.length,1);assert.equal(x.cache.size,0);assert.equal(x.proof(x.url,x.rule.sha256,body),false);bad=false;assert.equal(await load(x),body);assert.equal(x.calls.length,2);assert.equal(x.proof(x.url,x.rule.sha256,body),true);
 });
 await check('malformed gzip and absent DecompressionStream use raw Range with full206 check',async()=>{
  for(const decompress of [DecompressionStream,null]){const x=setup(async(url,options)=>url.endsWith('.gz')?response('malformed gzip'):response(body,{status:206,headers:{'Content-Range':'bytes 0-'+(Buffer.byteLength(body)-1)+'/'+Buffer.byteLength(body)}}),{decompress});assert.equal(await load(x),body);assert.equal(x.calls.at(-1).options.headers.Range,'bytes=0-');assert.equal(x.hashes.length,1);}
 });
 await check('all malformed partial206 representations still reject and leave no cache proof',async()=>{
  const n=Buffer.byteLength(body),ranges=[null,'bytes 1-'+(n-1)+'/'+n,'bytes 0-'+(n-2)+'/'+n,'bytes 0-'+(n+2)+'/'+(n+3),'bytes 0-9007199254740992/9007199254740993'];
  for(const range of ranges){const x=setup(async url=>url.endsWith('.gz')?response('missing',{status:404}):response(body,{status:206,headers:range?{'Content-Range':range}:{}}));await assert.rejects(load(x),/range|byte length/);assert.equal(x.cache.size,0);assert.equal(x.proof(x.url,x.rule.sha256,body),false);}
 });
 await check('Content-Encoding browser-decoded gzip is never decompressed twice',async()=>{const x=setup(async()=>response(body,{headers:{'Content-Encoding':'gzip'}}));assert.equal(await load(x),body);assert.equal(x.calls.length,1);assert.equal(x.hashes.length,1)});
 await check('abort before/during fetch and after read never falls back, hashes or publishes proof',async()=>{
  const first=setup(async()=>{throw Error('should not fetch')});first.controller.abort();await assert.rejects(load(first),e=>e.name==='AbortError');assert.equal(first.calls.length,0);
  const x=setup((url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('old','AbortError')),{once:true})));const pending=load(x);x.controller.abort();await assert.rejects(pending,e=>e.name==='AbortError');assert.equal(x.calls.length,1);assert.equal(x.hashes.length,0);assert.equal(x.cache.size,0);
  let y;y=setup(async()=>({ok:true,status:200,headers:new Headers({'Content-Encoding':'gzip'}),text:async()=>{y.controller.abort();return body}}));await assert.rejects(load(y),e=>e.name==='AbortError');assert.equal(y.hashes.length,0);assert.equal(y.calls.length,1);
 });
 await check('decoded streaming budget rejects before hash and never raw-retries',async()=>{const x=setup(async()=>response(body,{gzip:true}));await assert.rejects(x.transport.read(x.rule,x.url,x.rule.sha256,null,x.controller.signal,8),e=>e.name==='StudyPrefetchLimit');assert.equal(x.calls.length,1);assert.equal(x.hashes.length,0)});
 await check('descriptor identity, URL, pin, own-data shape and mutation are validated before cache use',async()=>{
  const x=setup(async()=>response(body,{gzip:true}));assert.equal(await load(x),body);const n=x.calls.length;
  await assert.rejects(load(x,{...x.rule}),/descriptor/);await assert.rejects(x.resource(x.url,'f'.repeat(64),null,x.rule),/descriptor/);assert.equal(x.calls.length,n);
  const saved=x.rule.gzipSrc;x.rule.gzipSrc='../foreign.gz';await assert.rejects(load(x),/descriptor/);x.rule.gzipSrc=saved;
  let accessed=0;Object.defineProperty(x.rule,'gzipSrc',{configurable:true,get(){accessed++;return saved}});await assert.rejects(load(x),/descriptor/);assert.equal(accessed,0);assert.equal(x.calls.length,n);
 });
 await check('held descriptor mutation rejects even after authentic bytes; no cross-identity success',async()=>{
  let release;const held=new Promise(r=>release=r),x=setup(async()=>{await held;return response(body,{gzip:true})});const pending=load(x);x.rule.sha256='f'.repeat(64);release();await assert.rejects(pending,/descriptor/);assert.equal(x.cache.size,0);assert.equal(x.proof(x.url,sha(body),body),false);
 });
 await check('source media remains exact original Range, bad200 SHA rejects, cache24/proof expiry retained',async()=>{
  const x=setup(async()=>response(body));const media='http://example.test/book/media/_as_runtime_123456789012345678901234.js';assert.equal(await x.resource(media,sha(body)),body);assert.equal(x.calls[0].options.headers.Range,'bytes=0-');for(let n=0;n<25;n++)await x.resource('http://example.test/book/media/file'+n+'.js',sha(body));assert.equal(x.cache.size,24);assert.equal(x.proof(media,sha(body),body),false);
  const y=setup(async()=>response('wrong'));await assert.rejects(y.resource(media,sha(body)),/SHA differs/);assert.equal(y.cache.size,0);
 });
 await check('source/parse/bind/fullgate preserved by six exact reversible edits and canonical HOST bytes',async()=>{
  let undo=candidate;const edits=JSON.parse(read('edits.json'));assert.equal(edits.length,6);for(const [a,b]of edits.toReversed()){assert.equal(undo.split(b).length,2);undo=undo.replace(b,a)}assert.equal(undo,baseline);
  const html=read('candidate-frame.html'),oldhtml=read('baseline-candidate-frame.html');assert.equal(html.replace(candidate,baseline),oldhtml);
  const exact=read('canonical-artifact-functions.js');assert.ok(helper.includes(exact));assert.equal(helper.split(exact).length,2);
  const begin=s=>s.slice(s.indexOf('async function prepareView('));assert.equal(begin(candidate),begin(baseline));
  const bind=s=>s.slice(s.indexOf(' function bind(win,doc,value,valid)'),s.indexOf('// Experimental explicit compiled profile;'));assert.equal(bind(candidate),bind(baseline));
  new vm.Script(candidate);new vm.Script(helper);
 });
 console.log(JSON.stringify({passed:true,contracts:count,noDOM:true,noBrowser:true,cpuStopped:true}));
}
module.exports={setup,load,response,body,asset,sha,baseline,candidate,read};
if(require.main===module){if(process.argv.includes('--red'))red().catch(e=>{console.error(e.stack);process.exitCode=1});else main().catch(e=>{console.error(e.stack);process.exitCode=1});}
