'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const D=__dirname,BASE=__dirname+'/baseline-frame.js',before=fs.readFileSync(BASE,'utf8'),code=fs.readFileSync(D+'/candidate-frame.js','utf8'),helper=fs.readFileSync(D+'/phase-helper.js','utf8'),transform=require('./transform.cjs');
const CARD='ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576',P='a'.repeat(64),H='b'.repeat(64),R='c'.repeat(64);
let count=0;function pass(name){count++;console.log('PASS '+name)}
function fixture({throwSend=false}={}){let tick=0,alive=true;const rows=[],performance={timeOrigin:100000,now(){return++tick}},parent={postMessage(row){if(throwSend)throw Error('observer send failed');rows.push(row)}},assets={entries:{[CARD]:{html:{sha256:H},profile:{sha256:P}}},runtime:{sha256:R}},begin=new Function('performance','parent','compiledAssets',helper+';return qaCompiledPhase;')(performance,parent,assets),packet={id:CARD,token:7},ctx=begin(packet,1,22,()=>alive);return{ctx,rows,performance,begin,packet,setAlive(v){alive=v}}}
(async()=>{
assert.equal(transform.adapt(before),code);assert.equal(transform.undo(code),before);new Function(code);new Function(helper);
for(const name of ['waitPrepared','currentPreparation','show']){const find=(s)=>{const at=s.indexOf((name==='show'?'async ':'')+'function '+name+'(');assert.ok(at>=0);const end=s.indexOf('\n',at);return s.slice(at,end)};assert.equal(find(code),find(before),name+' control gate unchanged')}
assert.equal((code.match(/\bawait\b/g)||[]).length,(before.match(/\bawait\b/g)||[]).length);pass('exact full inverse; original gate and await count unchanged');
{
 const f=fixture();assert.equal(f.rows.length,1);assert.equal(f.rows[0].label,'prepare-start');f.ctx.point('profile-json-parsed');f.ctx.point('profile-json-parsed');f.ctx.point('unknown');assert.equal(f.rows.length,2);assert.equal(f.begin(f.packet,1,23,()=>true),null);f.setAlive(false);f.ctx.point('profile-frozen');assert.equal(f.rows.length,2);
 const g=fixture();for(let i=0;i<100;i++)g.ctx.span('author-execute',g.ctx.now(),P);assert.equal(g.rows.length,64);for(const row of g.rows){assert.equal(row.id,CARD);assert.equal(row.token,7);assert.equal(row.sequence,22);assert.equal(row.side,1);assert.equal(row.timeOrigin,100000)}
 const h=fixture({throwSend:true});assert.doesNotThrow(()=>h.ctx.point('profile-frozen'));assert.doesNotThrow(()=>h.ctx.span('author-execute',h.ctx.now(),P));pass('once/cap/owner/observer-failure isolation');
}
{
 const f=fixture(),original=Error('SHA failed'),calls=[],scriptCache=new Map();let mode='good';
 const a=code.indexOf('async function resource('),b=code.indexOf('\nasync function collectAuthoredScripts',a);assert.ok(a>=0&&b>a);const source=code.slice(a,b);
 const resource=new Function('scriptCache','document','URL','fetch','TextEncoder','knownPinMatches',source+'\nreturn resource;')(scriptCache,{baseURI:'http://local/qa.html'},URL,async(url,options)=>{calls.push(options);return{ok:true,status:200,headers:{get(){return null}},async text(){return 'plain'}}},TextEncoder,async(text,pin)=>{assert.equal(text,'plain');assert.equal(pin,H);if(mode==='throw')throw original;return mode==='good'});
 assert.equal(await resource('http://local/body.html',H,f.ctx),'plain');assert.equal(await resource('http://local/body.html',H,f.ctx),'plain');assert.equal(calls.length,1);assert.deepEqual(calls[0],{headers:{Range:'bytes=0-'}});const row=f.rows.find(r=>r.kind==='resource');assert.ok(row);assert.equal(row.resource,'derived-html');assert.equal(row.text_utf16,5);assert.ok(row.request_start<row.headers_at&&row.headers_at<row.text_at&&row.text_at<row.verified_at);assert.equal(row.elapsed,row.verified_at-row.request_start);
 mode='throw';await assert.rejects(resource('http://local/fail.html',H,f.ctx),e=>e===original);mode='good';assert.equal(await resource('http://local/fail.html',H,f.ctx),'plain');assert.equal(calls.length,3);pass('actual resource boundaries/cache/error/retry and original fetch options');
}
{
 const f=fixture(),start=code.indexOf('function makeCompiledProfileSupport('),end=code.indexOf('\n// Experimental explicit compiled profile',start);assert.ok(start>=0&&end>start);const pins={sourceWrapperSha256:P},entry={decoded:true,html:{src:'_qa_compiled_body.html',sha256:H},profile:{src:'_qa_compiled_profile.json',sha256:P},source:{wrapper_sha256:P,payload_sha256:P,side_sha256:P,expanded_sha256:P,registry_pins:[]},module:{original_sha256:P,sha256:H},anchors:{schema:'study-compiled-card-interactions.v1',version:1,bindings:{...pins,originalModuleSha256:P,nativeModuleSha256:H,derivedHTMLSha256:H}}};
 const assets={entries:{[CARD]:entry},runtime:{src:'_qa_compiled_runtime.js',sha256:R}},profile={schema:entry.anchors.schema,version:1,bindings:entry.anchors.bindings,nested:{values:[1]}};
 const make=new Function('document',code.slice(start,end)+'\nreturn makeCompiledProfileSupport;')({baseURI:'http://local/qa.html'});const values=new Map([[H,'html'],[P,JSON.stringify(profile)],[R,'runtime']]);let calls=0;const support=make(assets,async(url,pin,phase)=>{calls++;assert.equal(phase,f.ctx);return values.get(pin)},async()=>true,JSON.stringify,()=>true);
 const packet={id:CARD,prepared:{source_wrapper_sha256:P,source_payload_sha256:P,modules:{[P]:{original_sha256:P,sha256:H}}}},side={proof:{source_sha256:P,expanded_sha256:P,registry_pins:[]}};const result=await support.load(packet,1,side,()=>true,f.ctx);assert.equal(calls,3);assert.equal(result.html,'html');assert.ok(Object.isFrozen(result.profile.nested.values));assert.deepEqual(f.rows.filter(x=>x.kind==='point').map(x=>x.label),['prepare-start','compiled-assets-requested','compiled-assets-verified','compiled-recheck-verified','profile-json-parsed','profile-frozen']);pass('actual compiled load preserves checks/JSON/freeze ordering');
}
{
 const m=code.match(/ function batch\(action,qaClock\)\{[^\n]+/);assert.ok(m);let reads=0;const make=()=>new Function('refresh','let batchDepth=0,dirty=false;'+m[0]+';return batch;')(()=>{reads++});
 const f=fixture(),batch=make(),events=[];const returned=batch(()=>{events.push('author1','author2');return 77},f.ctx);assert.equal(returned,77);assert.deepEqual(events,['author1','author2']);assert.equal(reads,2);assert.equal(f.rows.filter(x=>x.label==='batch-finally-refresh').length,1);
 const original=Error('author failed');assert.throws(()=>batch(()=>{throw original},f.ctx),e=>e===original);assert.equal(reads,4);
 const q=fixture({throwSend:true});assert.equal(batch(()=>9,q.ctx),9);
 const problem=Error('layout failed');const broken=new Function('refresh','let batchDepth=0,dirty=false;'+m[0]+';return batch;')(()=>{throw problem});assert.throws(()=>broken(()=>{},f.ctx),e=>e===problem);pass('actual synchronous batch finally retains return/error/order and observes final refresh only');
}
{
 const start=code.indexOf('const authoredComplete=win.__ankiCigenFrames.batch('),end=code.indexOf('\n // Media adopted',start);assert.ok(start>=0&&end>start);const loop=code.slice(start,end)+';return authoredComplete;';const original=Error('original execute failure');
 function run(cancel=false,throws=false){const f=fixture(),events=[];let valid=true;const scripts=[{pin:P,node:{remove(){events.push('remove1')}}},{pin:H,node:{remove(){events.push('removeModule')}}},{pin:R,node:{remove(){events.push('remove2')}}}],packet={prepared:{modules:{[H]:{}}}},win={__ankiCigenFrames:{batch(action,phase){assert.equal(phase,f.ctx);return action()}}};const work=new Function('win','scripts','packet','valid','execute','doc','phase',loop);const call=()=>work(win,scripts,packet,()=>valid,(_doc,_code,pin)=>{events.push(pin);if(throws)throw original;if(cancel)valid=false},{},f.ctx);return{call,events,rows:f.rows}}
 const f=run();assert.equal(f.call(),true);assert.deepEqual(f.events,[P,'remove1','removeModule',R,'remove2']);assert.equal(f.rows.filter(r=>r.kind==='span').length,2);
 const c=run(true);assert.equal(c.call(),null);assert.deepEqual(c.events,[P,'remove1']);const e=run(false,true);assert.throws(e.call,x=>x===original);assert.equal(e.rows.filter(r=>r.kind==='span').length,1);pass('actual author loop keeps source order/module skip/cancel/error with synchronous clock only');
}
console.log(JSON.stringify({passed:count,no_large_DOM:true,no_browser:true,no_installer:true}));
})().catch(error=>{console.error(error.stack);process.exitCode=1});
