'use strict';
const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),crypto=require('node:crypto'),fs=require('node:fs');
// The production module-loop slice is supplied by the Python test. Other
// adapters are identity stubs in this narrow warm contract; their actual full
// composition is also executed by study-native-algorithm-integration.cjs.
const input=JSON.parse(fs.readFileSync(0,'utf8')),hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const source=input.source,adapter=input.adapter;
const adapt=new Function(adapter+';return typeof adaptSharedReadingBankWarm==="function"?adaptSharedReadingBankWarm:(code=>code);')();
const moduleRun=new Function('scripts','packet','active','resource','document','valid','execute','doc',
 'adaptNativeProjectionLookup','adaptNativeProjectionTask','adaptNativeGroupTranslationText','adaptNativeGroupRanges','adaptNativeGroupCoarseBuckets','adaptNativeFineWholeProbe',
 adapter+';return (async()=>{const win=doc.defaultView||{},withSlimLoadChecker=(realm,run)=>run(false);'+input.module+'})();');
async function moduleScenario(code,pin,options={}){
 const executed=[],events=[],active={modules:new Set()},doc={},sha=hash(code);
 const packet={prepared:{modules:{[pin]:{src:'evidence/native.js',sha256:sha,original_sha256:pin}}}};
 const resource=async(url,expected)=>{events.push('resource');assert.equal(url,'https://fixture.test/book/evidence/native.js');assert.equal(hash(options.corrupt?code+'changed':code),expected,'original resource SHA differs');return code;};
 const prior=name=>(value,original)=>{assert.equal(original,pin);assert.equal(events[0],'resource');events.push(name);return value;};
 const execute=(actual,value,proof)=>{assert.equal(actual,doc);assert.equal(proof,pin+'-prepared-'+sha);events.push('execute');executed.push(value);};
 const invoke=()=>moduleRun([{pin}],packet,active,resource,{baseURI:'https://fixture.test/book/index.html'},()=>!options.cancelled,execute,doc,prior('lookup'),prior('task'),prior('translation'),prior('ranges'),prior('coarse'),code=>code);
 if(options.reject){await assert.rejects(invoke(),options.reject);assert.deepEqual(executed,[]);assert.equal(active.modules.size,0);return;}
 await invoke();return {executed,events,invoke};
}
const prepared=source.replace('warmHashes.size>256||warmHashBytes>1048576','warmHashes.size>2048||warmHashBytes>1048576');
assert.notEqual(prepared,source);
const pin='5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e';
let optimized;const SIDE='af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5';
const BOUND='Verified bank sentence 😀',UNKNOWN='Unbound original sentence',META=metadata();
function metadata(text=BOUND,expected=hash(text)){
 return {schema:'exam-usage-shared-reading-bank.v5',summary:{verified_groups:1},groups:[{group_id:'bank-1',paper_id:'kaoyan:2026-01',status:'verified',question_range:[41,45],questions:[{question_id:'q41',number:41}],bank:[{source_option_id:'option-A',label:'A',correctness:'correct',matched_question_ids:['q41']}],group_evidence_sha256:'c'.repeat(64)}],sentence_bindings:[{sentence_id:'kaoyan:2026-01:bound',group_id:'bank-1',paper_id:'kaoyan:2026-01',source_option_id:'option-A',english:text,english_hash:expected,reviewed_content_hash:'b'.repeat(64),binding_sha256:'a'.repeat(64)}]};
}
function url(binding,id=binding.sentence_id){const q=new URLSearchParams({paper:binding.paper_id,'anki-codex-sentence':id,'anki-codex-hash':binding.english_hash,'anki-codex-review':binding.reviewed_content_hash,'anki-codex-en':JSON.stringify([[0,1]])});return 'https://fixture.test/exam-library/practice/full-paper.htm?'+q;}
function markup(meta,{id,text,extra='',sf=false}={}){const b=meta.sentence_bindings[0],doc=new JSDOM('').window.document,root=doc.createElement(sf?'section':'article');root.className=sf?'sf-example':'example-card';root.id='case';const en=doc.createElement('p');en.className=sf?'sf-en':'example-text';en.textContent=text??b.english;root.append(en);const zh=doc.createElement('p');zh.className=sf?'sf-zh':'example-translation';zh.textContent='原译文保持完整';root.append(zh);const a=doc.createElement('a');a.className='sentence-jump';a.href=url(b,id);a.textContent='原卷';root.append(a);const loc=doc.createElement('p');loc.className=sf?'sf-source':'example-source';loc.textContent='2026 原题';root.append(loc);const html=root.outerHTML+extra;doc.defaultView.close();return html;}
function fixture(code,meta,html=''){
 const dom=new JSDOM(html,{url:'https://fixture.test/book/',runScripts:'outside-only'}),w=dom.window;w.__ankiSlimManualRefresh=true;w.TextEncoder=TextEncoder;
 const trusted=new Set([JSON.stringify(meta,null,2)+'\n']),calls=[];let hold=null,failure=null;
 const digest=async(algorithm,bytes)=>{assert.equal(algorithm,'SHA-256');const text=Buffer.from(bytes).toString('utf8');calls.push(text);if(failure&&failure(text)){failure=null;throw Error('fixture SHA unavailable');}if(hold&&hold.predicate(text)){const state=hold;hold=null;state.entered=true;await new Promise(r=>state.release=r);}const hex=trusted.has(text)?SIDE:hash(text),b=Buffer.from(hex,'hex');return b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength);};
 Object.defineProperty(w.crypto,'subtle',{value:{digest},configurable:true});w.eval(code);
 return {w,dom,api:w.AnkiSharedReadingBankRuntime,calls,failNext:predicate=>{failure=predicate;},trust:m=>trusted.add(JSON.stringify(m,null,2)+'\n'),pause:predicate=>{const state={predicate,entered:false,release:null};hold=state;return state;},close:()=>w.close()};
}
const plain=value=>JSON.parse(JSON.stringify(value));
async function settleHold(state){for(let i=0;i<30&&!state.entered;i++)await Promise.resolve();assert.equal(state.entered,true,'actual process did not await its digest');}
function capture(f,h){return {html:f.w.document.body.innerHTML,stats:plain(h.stats()),diagnostics:plain(h.diagnostics())};}
async function scenario(code,{meta=META,opts={},warm=[],action}={}){
 const f=fixture(code,meta,markup(meta,opts));try{await f.api.warm(meta,warm);const h=f.api.install(f.w.document,meta);await h.ready;if(action)await action(f,h);const ready=capture(f,h);h.dispose();return {ready,disposedHtml:f.w.document.body.innerHTML};}finally{f.close();}
}
(async()=>{
 const results=[];
 const first=await moduleScenario(prepared,pin);optimized=first.executed[0];
 // RED is the unchanged real IIFE at the current 2048-entry policy.
 const red=process.argv.includes('--red'),f=fixture(red?prepared:optimized,META),long='x'.repeat(65537);
 await f.api.warm(META,[BOUND,UNKNOWN,UNKNOWN,'unbound 2',long,long,BOUND]);
 const prewarmCount=f.calls.length,unboundCalls=f.calls.filter(x=>x===UNKNOWN||x==='unbound 2'||x===long).length;
 assert.equal(unboundCalls,0,'unbound strings still trigger redundant digest work');assert.equal(prewarmCount,2,'only original metadata pin and one bound unique digest should run');f.close();results.push('only_bound_unique_texts_are_prewarmed');
 const before='warm:async function(metadata,texts){await buildIndex(metadata);await Promise.all(texts.map(digest));}';
 assert.equal(adapt(prepared,'unknown-source'),prepared);
 for(const known of [pin,'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93']){
  assert.throws(()=>adapt(prepared.replace(before,'changed'),known),/boundary differs/);
  assert.throws(()=>adapt(prepared+before,known),/boundary differs/);
  assert.throws(()=>adapt(adapt(prepared,known),known),/boundary differs/);
 }
 results.push('both_original_pin_guards_unknown_missing_duplicate_and_double_apply');
 for(const [name,mutate,error] of [
  ['wrong sidecar pin',m=>{m.summary.verified_groups=7;},/byte SHA mismatch/],
  ['invalid schema',m=>{m.schema='changed';},/invalid shared bank sidecar/],
  ['duplicate binding',m=>{m.sentence_bindings.push({...m.sentence_bindings[0]});},/duplicate shared bank sentence identity/],
  ['missing group',m=>{m.sentence_bindings[0].group_id='missing';},/binding group missing/],
  ['ambiguous option',m=>{m.groups[0].bank.push({...m.groups[0].bank[0]});},/option identity ambiguous/]
 ]){
  for(const code of [prepared,optimized]){const meta=structuredClone(META),f=fixture(code,meta);mutate(meta);if(name!=='wrong sidecar pin')f.trust(meta);await assert.rejects(f.api.warm(meta,[]),error);f.close();}
  results.push(name+'_still_rejected');
 }
 for(const [name,meta,opts,warm] of [
  ['native_bound',META,{},[BOUND,UNKNOWN]],
  ['sf_bound',META,{sf:true},[BOUND]],
  ['unknown_identity',META,{id:'kaoyan:2026-01:unknown',text:UNKNOWN},[UNKNOWN]],
  ['changed_english',META,{text:'Changed DOM English'},['Changed DOM English']],
  ['wrong_bound_hash',metadata(BOUND,'0'.repeat(64)),{},[BOUND]]
 ]){
  const old=await scenario(prepared,{meta,opts,warm}),next=await scenario(optimized,{meta,opts,warm});assert.deepEqual(next,old,name+' DOM/stats/ready/diagnostics/dispose changed');
  if(name==='wrong_bound_hash'){assert.equal(next.ready.stats.rejected,1);assert.equal(next.ready.stats.rejectionReasons['shared bank actual English SHA differs'],1);}
  if(name==='native_bound')assert.equal(next.ready.stats.projectedNative,1);
  if(name==='sf_bound')assert.equal(next.ready.stats.projectedSf,1);
  if(name==='unknown_identity')assert.equal(next.ready.stats.unbound,1);
  results.push(name+'_process_dom_stats_ready_dispose_parity');
 }
 for(const action of ['text','anchor','remove','dispose']){
  const all=[];
  for(const code of [prepared,optimized]){const meta=metadata(),f=fixture(code,meta,markup(meta));await f.api.warm(meta,[]);const hold=f.pause(t=>t===BOUND),h=f.api.install(f.w.document,meta);await settleHold(hold);if(action==='text')f.w.document.querySelector('.example-text').textContent='Changed during digest';if(action==='anchor')f.w.document.querySelector('a').href=url(meta.sentence_bindings[0],'kaoyan:2026-01:changed');if(action==='remove')f.w.document.querySelector('#case').remove();if(action==='dispose')h.dispose();hold.release();await h.ready;const v=capture(f,h);if(action==='text'||action==='anchor'){assert.equal(v.stats.rejected,1);assert.equal(v.stats.rejectionReasons['shared bank source changed during async verification'],1);}assert.equal(f.w.document.querySelector('[data-shared-reading-bank-group-id]'),null);all.push(v);f.close();}
  assert.deepEqual(all[0],all[1],action+' during async changed behavior');results.push(action+'_during_await_parity');
 }
 for(const code of [prepared,optimized]){const meta=metadata(),f=fixture(code,meta,markup(meta));await f.api.warm(meta,[BOUND]);meta.sentence_bindings[0].english='mutated metadata after snapshot';const h=f.api.install(f.w.document,meta);await h.ready;assert.equal(h.stats().projectedNative,1,'cached verified metadata snapshot was not retained');h.dispose();f.close();}
 results.push('verified_metadata_snapshot_survives_later_mutation');
 // Unsupported input shapes retain the original map/digest path and failures.
 for(const bad of [null,{},[null]]){const messages=[];for(const code of [prepared,optimized]){const f=fixture(code,META);await assert.rejects(f.api.warm(META,bad),e=>{messages.push(e.name+':'+e.message);return true});f.close();}assert.deepEqual(messages[0],messages[1]);}
 results.push('unsupported_input_shapes_preserve_original_rejection');
 // Warm itself performs no expected English-hash comparison, in both versions.
 const wrong=metadata(BOUND,'0'.repeat(64));for(const code of [prepared,optimized]){const f=fixture(code,wrong);await f.api.warm(wrong,[BOUND]);f.close();}results.push('warm_is_prewarm_not_per_text_expected_hash_validation');
 // Failed bound SHA jobs must remain evicted so actual process can retry.
 for(const code of [prepared,optimized]){const meta=metadata(),f=fixture(code,meta,markup(meta));f.failNext(t=>t===BOUND);await assert.rejects(f.api.warm(meta,[BOUND]),/fixture SHA unavailable/);const h=f.api.install(f.w.document,meta);await h.ready;assert.equal(h.stats().projectedNative,1);assert.equal(f.calls.filter(t=>t===BOUND).length,2);h.dispose();f.close();}
 results.push('failed_bound_prewarm_is_evicted_and_actual_process_retries');
 for(const known of [pin,'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93']){const result=await moduleScenario(prepared,known);assert.equal(result.executed[0],adapt(prepared,known),'actual production callsite did not use the exact warm adapter');assert.deepEqual(result.events,['resource','lookup','task','translation','ranges','coarse','execute']);await result.invoke();assert.equal(result.executed.length,1,'same realm reran an original module');}
 results.push('both_source_pins_use_real_module_callsite_after_prior_adapters_once');
 const cancelled=await moduleScenario(prepared,pin,{cancelled:true});assert.deepEqual(cancelled.events,['resource']);assert.deepEqual(cancelled.executed,[]);
 await moduleScenario(prepared,pin,{corrupt:true,reject:/original resource SHA differs/});
 results.push('real_callsite_keeps_verified_resource_and_cancellation_guards');
 const unknown=await moduleScenario('unknown source body','f'.repeat(64));assert.deepEqual(unknown.executed,['unknown source body']);
 await moduleScenario(prepared.replace(before,'changed warm boundary'),pin,{reject:/Audited shared reading bank warm boundary differs/});
 results.push('real_callsite_keeps_unknown_bytes_and_rejects_known_boundary_drift');
 console.log(JSON.stringify({passed:results.length,contracts:results,realReadingBankSha256:hash(source),candidateReadingBankSha256:hash(optimized),prewarmCalls:prewarmCount,unboundDigestCalls:unboundCalls,originalCachePolicy2048:true,fixedSidecarSha256:SIDE,stubCryptoScope:'Small synthetic sidecar bytes are explicitly mapped to the unchanged fixed production SIDECAR_SHA; all English hashes use real SHA256. This tests original control-flow/refusal behavior, not a cryptographic claim about synthetic metadata.'}));
})().catch(e=>{console.error(e);process.exit(1)});
