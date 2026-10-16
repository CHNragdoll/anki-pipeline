'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto'),{JSDOM}=require('jsdom');
const path=require('node:path'),read=n=>fs.readFileSync(path.join(process.env.SLIM_LOAD_TEMPLATES,n),'utf8'),hash=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const PIN='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',OTHER='5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e';
const baseline=fs.readFileSync(process.env.SLIM_LOAD_SOURCE,'utf8'),adapterSource=read('native-slim-load-checker-adapter.js'),adapt=vm.runInNewContext(adapterSource+'\nadaptNativeSlimLoadChecker;');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject};};
async function until(fn){for(let i=0;i<100;i++){if(fn())return;await new Promise(resolve=>setTimeout(resolve,0));}assert.fail('condition was not reached');}
function fixture(t,options={}){
 const dom=new JSDOM('<!doctype html><head></head><body></body>',{runScripts:'outside-only',url:'https://example.test/book/'});t.after(()=>dom.window.close());const w=dom.window,doc=w.document;
 const calls={digest:0,match:[],network:[]},assets=new Map();w.TextEncoder=TextEncoder;w.AnkiSlimAssets=Object.create(null);
 Object.defineProperty(w.crypto,'subtle',{value:{digest(...args){calls.digest++;return options.digest?options.digest(...args):crypto.webcrypto.subtle.digest(...args);}}});
 const checker=(raw,pin)=>{calls.match.push({raw,pin});return options.match?options.match(raw,pin):Promise.resolve(hash(raw)===pin);};
 const bridge=new Function('knownPinMatches',read('native-slim-load-checker-bridge.js')+';return withSlimLoadChecker;')(options.noHelper?undefined:checker);
 if(options.conflict)Object.defineProperty(w,'__studySlimLoadCheckerCapture',{value:options.conflict,configurable:true});
 const script=options.source||baseline;
 if(!options.deferModule)bridge(w,enabled=>w.eval(enabled?adapt(script,options.original||PIN):script));
 const append=doc.head.append.bind(doc.head);doc.head.append=function(...nodes){append(...nodes);for(const node of nodes){if(node.tagName!=='SCRIPT'||!node.src)continue;const name=node.getAttribute('src');calls.network.push(name);w.setTimeout(()=>{const item=assets.get(name)||assets.get(name.replace(/^_ac_/,'_as_'));if(!item){node.onerror?.();return;}w.AnkiSlimAssets[item.pin]=item.raw;node.onload?.();},0);}};
 function part(raw,extra={}){const pin=hash(raw),descriptor={src:'_as_'+pin.slice(0,24)+'.js',sha256:pin,...extra};assets.set(descriptor.src,{pin,raw});return descriptor;}
 function register(raw,extra={}){const descriptor=part(raw,extra);w.AnkiSlimAssets[descriptor.sha256]=raw;return descriptor;}
 return{w,doc,calls,assets,part,register,load:descriptor=>w.StudySlimWarm.load(descriptor),bridge};
}

test('real prepared loader uses the known-pin matcher rather than old digest on first miss',async t=>{
 const f=fixture(t),part=f.register('原始 UTF8 😀');assert.equal(await f.load(part),'原始 UTF8 😀');assert.equal(f.calls.digest,0,'old digest must not run when the verified private checker is available');assert.equal(f.calls.match.length,1);assert.equal(Object.hasOwn(f.w,'__studySlimLoadCheckerCapture'),false);
});
test('bad SHA and missing registry content fail without verification cache and can retry',async t=>{
 const f=fixture(t),bad='0'.repeat(64),part={src:'_as_'+bad.slice(0,24)+'.js',sha256:bad};f.w.AnkiSlimAssets[bad]='wrong';await assert.rejects(f.load(part),/本地片段校验失败/);assert.equal(f.w.AnkiSlimAssets[bad],undefined);
 const valid=f.part('missing-body');f.w.AnkiSlimAssets[valid.sha256]=42;await assert.rejects(f.load(valid),/本地片段内容缺失/);f.w.AnkiSlimAssets[valid.sha256]='missing-body';assert.equal(await f.load(valid),'missing-body');
});
test('literal validation, all original src/pin guards and actual missing-media retry remain',async t=>{
 const f=fixture(t),part=f.part('dictionary',{literal:true});f.w.AnkiSlimAssets[part.sha256]={bad:true};assert.throws(()=>f.load(part),/共享字典必须是原始文本/);
 for(const bad of [null,{}, {...part,src:'https://example.test/x.js'},{...part,src:'../'+part.src},{...part,sha256:'A'.repeat(64)},{...part,src:'_as_'+'0'.repeat(24)+'.js'}])assert.throws(()=>f.load(bad),/本地片段标识无效/);
 const absent=f.part('not-on-disk');f.assets.delete(absent.src);await assert.rejects(f.load(absent),/本地片段媒体无法载入/);assert.deepEqual(f.calls.network,[absent.src.replace('_as_','_ac_'),absent.src]);
});
test('packed decode retains its literal dictionary load and verifies final exact raw',async t=>{
 const f=fixture(t),dict=f.register('dictionary text',{literal:true}),raw='expanded exact 中文',part=f.part(raw);f.w.AnkiSlimAssets[part.sha256]={packed:true};
 f.w.AnkiSlimPackedDecode=async(value,load)=>{assert.equal(value.packed,true);assert.equal(await load(dict),'dictionary text');return raw;};
 assert.equal(await f.load(part),raw);assert.deepEqual(f.calls.match.map(item=>item.pin),[dict.sha256,part.sha256]);assert.equal(f.calls.digest,0);
});
test('matcher rejection and synchronous throw leave pending retryable without caching failures',async t=>{
 const failure=new Error('helper failure');let mode='throw';const f=fixture(t,{match:(raw,pin)=>{if(mode==='throw')throw failure;if(mode==='reject')return Promise.reject(failure);return hash(raw)===pin;}}),part=f.register('retry raw');
 for(const next of ['throw','reject']){mode=next;await assert.rejects(f.load(part),error=>error===failure);}mode='ok';assert.equal(await f.load(part),'retry raw');assert.equal(f.calls.match.length,3);await f.load(part);assert.equal(f.calls.match.length,3);
});
test('same pin concurrent loads share the actual pending promise and cache survives card dispose',async t=>{
 const hold=deferred(),f=fixture(t,{match:()=>hold.promise}),part=f.register('shared raw'),first=f.load(part),second=f.load({...part});assert.equal(first,second);await until(()=>f.calls.match.length===1);f.w.AnkiSlimApkgDispose();hold.resolve(true);assert.equal(await first,'shared raw');assert.equal(await f.load(part),'shared raw');assert.equal(f.calls.match.length,1);
});
test('32MiB verified LRU remains unchanged and evicted registry rows reverify on reuse',async t=>{
 const f=fixture(t),length=12*1024*1024,parts=[];for(const letter of ['A','B','C']){const raw=letter.repeat(length),part=f.register(raw);parts.push(part);assert.equal((await f.load(part)).length,length);}assert.equal(f.w.AnkiSlimAssets[parts[0].sha256],undefined);assert.equal(f.calls.match.length,3);
 await f.load(parts[1]);assert.equal(f.calls.match.length,3);await f.load(parts[0]);assert.equal(f.calls.match.length,4);assert.equal(f.calls.network.length,1);
});
test('descriptor and raw are stable snapshots even when the caller or registry changes while hashing',async t=>{
 const hold=deferred(),f=fixture(t,{match:(raw,pin)=>hold.promise.then(()=>hash(raw)===pin)}),part=f.register('captured correct'),originalPin=part.sha256,pending=f.load(part);await until(()=>f.calls.match.length===1);part.src='_as_'+'f'.repeat(24)+'.js';part.sha256='f'.repeat(64);part.literal=true;f.w.AnkiSlimAssets[originalPin]='tampered later';hold.resolve();assert.equal(await pending,'captured correct');assert.equal(f.calls.match[0].pin,originalPin);assert.equal(f.calls.match[0].raw,'captured correct');assert.equal(await f.load({src:'_as_'+originalPin.slice(0,24)+'.js',sha256:originalPin}),'captured correct');
});
test('bad expected pin changed to a good pin during await cannot become a verified cache entry',async t=>{
 const hold=deferred(),f=fixture(t,{match:(raw,pin)=>hold.promise.then(()=>hash(raw)===pin)}),bad='0'.repeat(64),good=hash('valid'),part={src:'_as_'+bad.slice(0,24)+'.js',sha256:bad};f.w.AnkiSlimAssets[bad]='valid';const pending=f.load(part);await until(()=>f.calls.match.length===1);part.sha256=good;part.src='_as_'+good.slice(0,24)+'.js';hold.resolve();await assert.rejects(pending,/本地片段校验失败/);assert.equal(f.w.AnkiSlimAssets[bad],undefined);assert.equal(f.w.AnkiSlimAssets[good],undefined);
});
test('in-flight hydration disposed by the next card never writes old verified slice into new DOM',async t=>{
 const hold=deferred(),html='<li class="example-card"><p class="example-text">OLD SLICE</p></li>',f=fixture(t,{match:(raw,pin)=>raw===html?hold.promise:hash(raw)===pin}),part=f.register(html),handle=()=>({refresh:()=>Promise.resolve(),dispose(){},stats:()=>({errors:[]})});
 f.w.AnkiFinalReadingMetadata={};f.w.AnkiFineChunkRuntime={install:handle};f.w.AnkiReviewedChunkProjection={prepare:async()=>0,install:handle};f.w.AnkiSharedReadingBankRuntime={install:()=>({...handle(),ready:Promise.resolve()})};f.w.AnkiSameSenseGroupRuntime={install:handle};f.w.AnkiResidualReviewedChunkRuntime={install:handle};
 f.doc.body.innerHTML='<script class="anki-final-reviewed-data" type="application/json">{}</script><ol class="examples"><li class="as-lazy" data-as-kind="examples"><script class="as-manifest" type="application/json">'+JSON.stringify({schema:'anki-slim-segments.v1',parts:[{...part,count:1}],total:1})+'</script></li></ol>';
 const old=f.w.AnkiSlimApkgHydrate();await until(()=>f.calls.match.some(item=>item.raw===html));f.w.AnkiSlimApkgDispose();f.doc.body.innerHTML='<p id="new-card">NEW CARD</p>';hold.resolve(true);await old;assert.equal(f.doc.body.innerHTML,'<p id="new-card">NEW CARD</p>');
});
test('bridge collision leaves original bytes and digest; synchronous module errors clean only owned property',async t=>{
 const marker=()=>()=>true,w={},bridge=new Function('knownPinMatches',read('native-slim-load-checker-bridge.js')+';return withSlimLoadChecker;')(()=>true);Object.defineProperty(w,'__studySlimLoadCheckerCapture',{value:marker,configurable:true});assert.equal(bridge(w,enabled=>enabled),false);assert.equal(w.__studySlimLoadCheckerCapture,marker);
 const failure=new Error('execution error'),clean={};assert.throws(()=>bridge(clean,()=>{throw failure;}),error=>error===failure);assert.equal(Object.hasOwn(clean,'__studySlimLoadCheckerCapture'),false);
 const foreign=()=>false;bridge(clean,()=>Object.defineProperty(clean,'__studySlimLoadCheckerCapture',{value:foreign,configurable:true}));assert.equal(clean.__studySlimLoadCheckerCapture,foreign);
 const locked=Object.preventExtensions({});assert.equal(bridge(locked,enabled=>enabled),false);
 const actual=fixture(t,{conflict:marker}),part=actual.register('real collision fallback');assert.equal(await actual.load(part),'real collision fallback');assert.equal(actual.calls.digest,1);assert.equal(actual.calls.match.length,0);assert.equal(actual.w.__studySlimLoadCheckerCapture,marker);
});
test('missing helper retains original digest and unknown native pins do not adapt',async t=>{
 const f=fixture(t,{noHelper:true}),part=f.register('fallback');assert.equal(await f.load(part),'fallback');assert.equal(f.calls.digest,1);assert.equal(f.calls.match.length,0);
 for(const unknown of ['',PIN.toUpperCase(),'f'.repeat(64),'6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'])assert.equal(adapt('unrelated module',unknown),'unrelated module');
 const standalone=fixture(t,{noHelper:true,source:adapt(baseline,PIN)}),q=standalone.register('no capture');assert.equal(await standalone.load(q),'no capture');assert.equal(standalone.calls.digest,1);
});
test('both audited Slim shapes invert exactly and drift/duplicate/repeated boundaries reject',()=>{
 const edits=vm.runInNewContext(adapterSource.split('  const edits = ')[1].split(';\n  if (edits.some')[0]);
 assert.equal(hash(baseline),'bb8cb1ae357a17245a3829edd1523a8677c29fe8b3d0cd1118beeb5e4e6c0a59');
 for(const original of [PIN,OTHER])for(const source of [baseline,baseline.replace('\n  window.StudySlimWarm = Object.freeze({load:load});','')]){const result=adapt(source,original);let inverse=result;for(const [before,after]of edits){assert.equal(source.split(before).length,2);assert.equal(inverse.split(after).length,2);inverse=inverse.replace(after,before);}assert.equal(inverse,source);}
 assert.throws(()=>adapt(baseline.replace('cache(part.sha256, raw); return raw;','changed cache return;'),PIN),/Audited native Slim load checker boundary differs/);assert.throws(()=>adapt(baseline+baseline,PIN),/boundary differs/);assert.throws(()=>adapt(adapt(baseline,PIN),PIN),/boundary differs/);
});

test('original loader accepts a mutated bad expected pin after await; snapshot candidate above rejects the same race',async t=>{
 const hold=deferred(),f=fixture(t,{noHelper:true,source:baseline,digest:(...args)=>hold.promise.then(()=>crypto.webcrypto.subtle.digest(...args))}),bad='0'.repeat(64),part={src:'_as_'+bad.slice(0,24)+'.js',sha256:bad};
 f.w.AnkiSlimAssets[bad]='valid';const pending=f.load(part);await until(()=>f.calls.digest===1);part.sha256=hash('valid');part.src='_as_'+part.sha256.slice(0,24)+'.js';hold.resolve();assert.equal(await pending,'valid','characterize original mutable-descriptor hole rather than claim strict original snapshot semantics');
});

test('the actual candidate FRAME module loop verifies first, captures once, cleans, and keeps realm-only matcher across cards',async t=>{
 const line=process.env.SLIM_LOAD_MODULE_LOOP,f=fixture(t,{deferModule:true}),events=[],sha=hash(baseline),packet={prepared:{modules:{[PIN]:{sha256:sha,src:'evidence/_study_prepared_module_'+sha+'.js',original_sha256:PIN}}}},active={modules:new Set()};
 const names=['adaptNativeProjectionLookup','adaptNativeProjectionTask','adaptNativeGroupTranslationText','adaptNativeGroupRanges','adaptNativeGroupCoarseBuckets','adaptSharedReadingBankWarm','adaptNativeFineWholeProbe'];
 const run=new Function('scripts','packet','active','resource','document','valid','execute','doc','win',...names,'withSlimLoadChecker','adaptNativeSlimLoadChecker','return (async()=>{'+line+'})();');
 const resource=async(url,pin)=>{events.push('resource');assert.equal(Object.hasOwn(f.w,'__studySlimLoadCheckerCapture'),false);assert.equal(url,'https://example.test/book/evidence/_study_prepared_module_'+sha+'.js');assert.equal(hash(baseline),pin);return baseline;};
 const execute=(doc,code,proof)=>{events.push('execute');assert.equal(doc,f.doc);assert.equal(proof,PIN+'-prepared-'+sha);assert.equal(typeof f.w.__studySlimLoadCheckerCapture,'function');f.w.eval(code);};
 const invoke=(valid=()=>true)=>run([{pin:PIN}],packet,active,resource,{baseURI:'https://example.test/book/index.html'},valid,execute,f.doc,f.w,...names.map(name=>(code,pin)=>{events.push(name);assert.equal(pin,PIN);return code;}),f.bridge,adapt);
 await invoke();assert.deepEqual(events,['resource',...names,'execute']);assert.equal(Object.hasOwn(f.w,'__studySlimLoadCheckerCapture'),false);const a=f.register('card A');assert.equal(await f.load(a),'card A');f.w.AnkiSlimApkgDispose();const b=f.register('card B');assert.equal(await f.load(b),'card B');assert.equal(f.calls.match.length,2);assert.equal(f.calls.digest,0);await invoke();assert.equal(events.filter(x=>x==='execute').length,1);
 active.modules.clear();events.length=0;await invoke(()=>false);assert.deepEqual(events,['resource']);assert.equal(Object.hasOwn(f.w,'__studySlimLoadCheckerCapture'),false);
});
