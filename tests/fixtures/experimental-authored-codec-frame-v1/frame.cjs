'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict');
const data=require('./data.cjs'),B=require('./build.cjs'),codec=require('./codec-adapter.cjs');
const PIN=B.PIN;
function adapt(source,assets){
 assert.equal(data.hash(source),'052ccc54d5f0c799a890d504fe48b695a6c547f5d96b96943d4f8ab472afa59d');
 let output=source;const edits=[];
 function edit(before,after){assert.equal(output.split(before).length,2,before.slice(0,90));output=output.replace(before,()=>after);edits.push([before,after])}
 const oldAssets=source.slice(source.indexOf('const compiledAssets=')+21).split(';\n')[0];
 edit('const compiledAssets='+oldAssets+';','const compiledAssets='+JSON.stringify(assets)+';');
 const approved={sourceSha256:PIN,firstIifeSha256:B.hash(B.FIRST),cohort:B.COHORT,configJSON:JSON.stringify(B.config())};
 const factory=fs.readFileSync(__dirname+'/capability.js','utf8');
 const adapter="function adaptCompiledCodecSource(code,pin){if(pin!=="+JSON.stringify(PIN)+")return code;const before="+JSON.stringify(B.FIRST)+",after="+JSON.stringify(codec.adapted)+";if(!code.startsWith(before)||code.split(before).length!==2)throw Error('Audited compiled codec source differs');return after+code.slice(before.length)}\n";
 edit('function makeCompiledProfileSupport(assets, resource, matches, canonical, current) {',factory+'\n'+adapter+'\nconst compiledCodecApproved='+JSON.stringify(approved)+';\nfunction makeCompiledProfileSupport(assets, resource, matches, canonical, current) {');
 edit("const owners=new WeakMap(), hash=/^[a-f0-9]{64}$/;","const owners=new WeakMap(), successfulResults=new WeakMap(), hash=/^[a-f0-9]{64}$/;");
 edit("phase?.point('profile-frozen');return result;","successfulResults.set(result,{packet,index,side,valid,htmlSha256:entry.html.sha256,profileSha256:entry.profile.sha256});phase?.point('profile-frozen');return result;");
 edit('return Object.freeze({load,bind,withFrozenCapture,clear(doc){owners.delete(doc)}});',"return Object.freeze({load,bind,withFrozenCapture,certifies(value,packet,index,side){const proof=successfulResults.get(value);return proof&&proof.packet===packet&&proof.index===index&&proof.side===side&&proof.valid()===true&&current()===true?proof:null},clear(doc){owners.delete(doc)}});");
 edit('if(item.code!==null)item.code=adaptAuthoredCompactClassScan(item.code,item.pin);',"if(item.code!==null){if(item.pin==="+JSON.stringify(PIN)+")item.compiledCodecCode=adaptAuthoredCompactClassScan(adaptCompiledCodecSource(item.code,item.pin),item.pin);item.code=adaptAuthoredCompactClassScan(item.code,item.pin);}");
 // The authenticated profile and the existing parsed DOM are reused verbatim.
 // Registration happens after source styles/children are finalized, immediately
 // before synchronous original adoption; no digest, parse, or freeze is added.
 edit("phase?.point('body-adoption-start');", "active.codec?.dispose(doc);active.codec=compiled?createCompiledCodecCapability(win,value=>compiledProfiles.certifies(value,packet,index,prepared),compiledCodecApproved):null;const codecRegistered=!!active.codec?.register(parsed,compiled,()=>valid()&&active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.isConnected&&active.node.contentDocument===doc,scripts.map(item=>item.pin));const adoptBody=()=>{phase?.point('body-adoption-start');");
 edit("phase?.point('body-connected');initialNumbering=", "phase?.point('body-connected');return doc;};if(codecRegistered)active.codec.attach(parsed,adoptBody);else adoptBody();initialNumbering=");
 const call='execute(doc,item.code,item.pin,initialNumbering)';
 const wrapped="(active.codec&&item.compiledCodecCode?active.codec.withCapture(current?.metricsAsset?item.compiledCodecCode+'\\n//# sourceURL=study-source-'+item.pin+'.js':item.compiledCodecCode,enabled=>execute(doc,enabled?item.compiledCodecCode:item.code,item.pin,initialNumbering)):execute(doc,item.code,item.pin,initialNumbering))";
 edit(call,wrapped);
 edit('compiledProfiles.clear(doc);qaLayoutCostClear(doc);doc.body.replaceChildren();', 'activeCodecDispose(entry);compiledProfiles.clear(doc);qaLayoutCostClear(doc);doc.body.replaceChildren();');
 edit('entry.key=cohortKey;entry.modules=new Set();entry.doc=null;', 'entry.key=cohortKey;activeCodecDispose(entry);entry.modules=new Set();entry.doc=null;');
 edit('function clearOld(entry){', 'function activeCodecDispose(entry){entry.codec?.dispose(entry.doc);entry.codec=null}\nfunction clearOld(entry){');
 let inverse=output;for(const [before,after]of [...edits].reverse()){assert.equal(inverse.split(after).length,2);inverse=inverse.replace(after,()=>before)}assert.equal(inverse,source);
 return{output,edits,inverseExact:true};
}
module.exports={adapt};
