'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const pins=['5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e','be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'];
const adapt=new Function(input.adapter+';return typeof adaptNativeFineWholeProbe==="function"?adaptNativeFineWholeProbe:(code=>code);')();
// Other algorithms are identity spies in this Fine-specific callsite test.
// The shared algorithm integration separately executes their real composition.
const run=new Function('scripts','packet','active','resource','document','valid','execute','doc',
 'adaptNativeProjectionLookup','adaptNativeProjectionTask','adaptNativeGroupTranslationText','adaptNativeGroupRanges','adaptNativeGroupCoarseBuckets','adaptSharedReadingBankWarm','adaptNativeFineWholeProbe',
 'return (async()=>{const win=doc.defaultView||{},withSlimLoadChecker=(realm,run)=>run(false);'+input.call+'})();');
async function scenario(pin,source=input.source,options={}){
 const events=[],executed=[],sha=hash(source),active={modules:new Set()},doc={};
 const packet={prepared:{modules:{[pin]:{src:'evidence/native.js',sha256:sha,original_sha256:pin}}}};
 const resource=async(url,expected)=>{events.push('resource');assert.equal(url,'https://fixture.test/book/evidence/native.js');assert.equal(hash(options.corrupt?source+'changed':source),expected,'original resource SHA differs');return source;};
 const prior=name=>(code,original)=>{assert.equal(original,pin);assert.equal(events[0],'resource');events.push(name);return code;};
 const fine=(code,original)=>{assert.equal(original,pin);events.push('fine');return adapt(code,original);};
 const execute=(actual,code,proof)=>{assert.equal(actual,doc);assert.equal(proof,pin+'-prepared-'+sha);events.push('execute');executed.push(code);};
 const invoke=()=>run([{pin}],packet,active,resource,{baseURI:'https://fixture.test/book/index.html'},()=>!options.cancelled,execute,doc,prior('lookup'),prior('task'),prior('translation'),prior('ranges'),prior('coarse'),prior('warm'),fine);
 if(options.reject){await assert.rejects(invoke(),options.reject);assert.deepEqual(executed,[]);assert.equal(active.modules.size,0);return;}
 await invoke();return {events,executed,invoke};
}
(async()=>{
 if(input.mode==='prepare'){const result=await scenario(pins[0]);process.stdout.write(JSON.stringify({candidate:result.executed[0]}));return;}
 const passed=[],expected='3e94e0fdbb11f646fdad3642b432a5a624e23102c51cb918758a12a75b71f363';
 const edits=JSON.parse(input.adapter.match(/  var edits = (\[\[.*\]\]);/)[1]);
 // These two real IIFE inputs were byte-identical in both approved originals.
 // Full-module inverse evidence remains separately sealed with the candidate.
 for(const pin of pins){const result=adapt(input.source,pin);assert.equal(hash(result),expected);let inverse=result;for(const [before,after]of edits){assert.equal(inverse.split(after).length,2);inverse=inverse.replace(after,before);}assert.equal(inverse,input.source);const tail='      stats.rootsWithWhole++;';assert.equal(result.slice(result.indexOf(tail)),input.source.slice(input.source.indexOf(tail)));passed.push('exact_two_boundary_iife_inverse_'+pin.slice(0,8));}
 for(const pin of ['',pins[0].toUpperCase(),'0'.repeat(64)])assert.equal(adapt('unrelated source',pin),'unrelated source');passed.push('unknown_pins_keep_original_bytes');
 for(const pin of pins){for(const [before]of edits)assert.throws(()=>adapt(input.source.replace(before,'changed exact boundary'),pin),/Audited Fine whole probe boundary differs/);assert.throws(()=>adapt(input.source+input.source,pin),/Audited Fine whole probe boundary differs/);assert.throws(()=>adapt(adapt(input.source,pin),pin),/Audited Fine whole probe boundary differs/);}passed.push('both_pins_reject_drift_duplicate_and_repeat');
 for(const pin of pins){const result=await scenario(pin);assert.equal(result.executed[0],adapt(input.source,pin));assert.deepEqual(result.events,['resource','lookup','task','translation','ranges','coarse','warm','fine','execute']);await result.invoke();assert.equal(result.executed.length,1);}passed.push('both_pins_use_outermost_fine_after_previous_adapters_once');
 const cancelled=await scenario(pins[0],input.source,{cancelled:true});assert.deepEqual(cancelled.events,['resource']);assert.deepEqual(cancelled.executed,[]);passed.push('cancel_before_adaptation_and_execution');
 await scenario(pins[0],input.source,{corrupt:true,reject:/original resource SHA differs/});passed.push('resource_verifies_before_adaptation');
 const unknown=await scenario('f'.repeat(64),'unrelated source');assert.deepEqual(unknown.executed,['unrelated source']);for(const [before]of edits)await scenario(pins[1],input.source.replace(before,'changed exact boundary'),{reject:/Audited Fine whole probe boundary differs/});passed.push('actual_loop_keeps_unknown_bytes_and_rejects_known_drift');
 process.stdout.write(JSON.stringify({passed:true,contracts:passed,originalFineSha256:hash(input.source),candidateFineSha256:expected}));
})().catch(error=>{console.error(error);process.exit(1)});
