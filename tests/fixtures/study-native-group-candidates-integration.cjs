'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const BE='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',V26='5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e';
const actualAdapt=new Function(input.adapter+';return adaptNativeGroupCoarseBuckets;')();
const actualWarm=new Function(input.warmAdapter+';return adaptSharedReadingBankWarm;')();
const actualFine=new Function(input.fineAdapter+';return adaptNativeFineWholeProbe;')();
// Execute the real module-loop slice. Prior algorithms are identity spies here;
// their real composed algorithms/DOM behavior are covered in the 14 Group cases.
const run=new Function('scripts','packet','active','resource','document','valid','execute','doc',
 'adaptNativeProjectionLookup','adaptNativeProjectionTask','adaptNativeGroupTranslationText','adaptNativeGroupRanges','adaptNativeGroupCoarseBuckets','adaptSharedReadingBankWarm','adaptNativeFineWholeProbe',
 'return (async()=>{const win=doc.defaultView||{},withSlimLoadChecker=(realm,run)=>run(false);'+input.call+'})();');
async function scenario(pin,code=input.source,options={}){
 const events=[],executed=[],digest=hash(code),active={modules:new Set()},doc={};
 const packet={prepared:{modules:{[pin]:{src:'evidence/_study_prepared_module_'+digest+'.js',sha256:digest,original_sha256:pin}}}};
 const resource=async(url,expected)=>{events.push('verify');assert.equal(url,'https://example.test/book/evidence/_study_prepared_module_'+digest+'.js');assert.equal(hash(options.corrupt?code+'changed':code),expected,'original resource SHA must verify before adaptation');return code};
 const prior=name=>(raw,original)=>{assert.equal(original,pin);assert.equal(events[0],'verify');events.push(name);return raw};
 const adapt=(raw,original)=>{events.push('coarse');return actualAdapt(raw,original)};
 const warm=(raw,original)=>{events.push('warm');return actualWarm(raw,original)};
 const fine=(raw,original)=>{events.push('fine');return actualFine(raw,original)};
 const execute=(node,raw,proof)=>{assert.equal(node,doc);assert.equal(proof,pin+'-prepared-'+digest);events.push('execute');executed.push(raw)};
 const invoke=()=>run([{pin}],packet,active,resource,{baseURI:'https://example.test/book/index.html'},()=>!options.cancelled,execute,doc,prior('lookup'),prior('task'),prior('translation'),prior('ranges'),adapt,warm,fine);
 if(options.reject){await assert.rejects(invoke(),options.reject);assert.deepEqual(executed,[]);return;}
 await invoke();return{events,executed,invoke};
}
(async()=>{
 for(const pin of [BE,V26]){const result=await scenario(pin);assert.deepEqual(result.events,['verify','lookup','task','translation','ranges','coarse','warm','fine','execute']);assert.equal(result.executed.length,1);assert.ok(result.executed[0].includes('coarseCounts.get(candidate.coarse) < 2'));}
 const retained=await scenario(BE);await retained.invoke();assert.equal(retained.executed.length,1,'same realm must not reexecute verified module');
 const cancelled=await scenario(BE,input.source,{cancelled:true});assert.deepEqual(cancelled.events,['verify']);assert.deepEqual(cancelled.executed,[]);
 await scenario(BE,input.source,{corrupt:true,reject:/original resource SHA/});
 const unknown=await scenario('f'.repeat(64),'unknown module');assert.deepEqual(unknown.executed,['unknown module']);
 await scenario(V26,input.source.replace('var buckets = new Map();','var buckets = new Set();'),{reject:/Audited native group coarse boundary differs/});
 const cohort=new Function(input.history+';return {table:staticHistoryCohorts,accept:staticHistoryCohort};')();
 const old='d34134c8918205c51c842963c7354f090e6041dcecd00480e695d4e874b8e21d',now='ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042',legacy='9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1';
 for(const sequence of cohort.table.sequences){const pin=sequence.find(value=>cohort.table.modules[value]),sha=cohort.table.modules[pin],packet={prepared:{modules:{[pin]:{original_sha256:pin,sha256:sha,src:'evidence/_study_prepared_module_'+sha+'.js'}}}},parsed={querySelectorAll:()=>[{}]},accept=seq=>cohort.accept(parsed,packet,seq.map(pin=>({pin})));
 assert.equal(accept(sequence),true);for(const replacement of [old,now])assert.equal(accept(sequence.map(value=>value===legacy?replacement:value)),true,'known numbering pin must normalize only at original numbering position');
 assert.equal(accept(sequence.map(value=>value===legacy?'f'.repeat(64):value)),false);const wrong=sequence.slice();wrong[0]=now;assert.equal(accept(wrong),false);}
 process.stdout.write(JSON.stringify({contracts:8,passed:true}));
})().catch(error=>{console.error(error);process.exit(1)});
