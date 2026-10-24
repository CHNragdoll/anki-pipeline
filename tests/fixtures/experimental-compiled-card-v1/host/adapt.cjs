'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const FRAME='c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02';
function adapt(source,assets,nativeAdapterSource){
 if(sha(source)!==FRAME)throw Error('Compiled FRAME source SHA differs');
 const support=fs.readFileSync(__dirname+'/host-support.js','utf8');
 const edits=[];let output=source;
 function edit(before,after){if(output.split(before).length!==2)throw Error('Compiled FRAME anchor differs: '+before.slice(0,90));output=output.replace(before,after);edits.push({before,after})}
 const start='async function prepareView(packet,index,requestedAt){';
 const helper=support+'\n'+nativeAdapterSource+'\nconst compiledAssets='+JSON.stringify(assets)+';\nconst compiledProfiles=makeCompiledProfileSupport(compiledAssets,resource,knownPinMatches,canonicalJSON,()=>!!current);\n';
 edit(start,helper+start);
 const proof="if(!verified.every(Boolean))throw Error('Prepared body differs from its source proof');if(!valid())return null;";
 edit(proof,proof+'\n const compiled=await compiledProfiles.load(packet,index,prepared,valid);if(!valid())return null;const authoredHTML=compiled?compiled.html:prepared.html;');
 edit("const parsed=new DOMParser().parseFromString(prepared.html,'text/html');","const parsed=new DOMParser().parseFromString(authoredHTML,'text/html');");
 edit('if(/<noscript\\b/i.test(prepared.html))','if(/<noscript\\b/i.test(authoredHTML))');
 const pipeline='adaptNativeFineWholeProbe(adaptSharedReadingBankWarm(adaptNativeGroupCoarseBuckets(adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask(adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin)';
 edit(pipeline,'adaptActiveSlimCompiledProfile('+pipeline+',item.pin)');
 edit('win.AnkiSlimDecode?.(parsed);const history=','if(!compiled)win.AnkiSlimDecode?.(parsed);const history=');
 edit("for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){","if(!compiled)for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){");
 const clean="for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;\n const head=";
 edit(clean,"for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;compiledProfiles.clear(doc);if(compiled){if(!win.AnkiCompiledCardRuntime)execute(doc,compiled.runtimeCode,'compiled-card-'+compiled.runtimeSha256);if(win.AnkiCompiledCardRuntime?.schema!==compiled.profile.schema||win.AnkiCompiledCardRuntime?.version!==compiled.profile.version)throw Error('Compiled runtime version differs')}\n const head=");
 const connected='doc.head.replaceChildren(head);doc.body.replaceChildren(body);win.scrollTo(0,0);history?.bind';
 edit(connected,'doc.head.replaceChildren(head);doc.body.replaceChildren(body);compiledProfiles.bind(win,doc,compiled,()=>packet===current&&active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.isConnected&&active.node.contentDocument===doc);win.scrollTo(0,0);history?.bind');
 const clear="for(const audio of doc.querySelectorAll('audio'))audio.pause();doc.body.replaceChildren();";
 edit(clear,"for(const audio of doc.querySelectorAll('audio'))audio.pause();compiledProfiles.clear(doc);doc.body.replaceChildren();");
 let inverse=output;for(const e of [...edits].reverse()){if(inverse.split(e.after).length!==2)throw Error('Compiled inverse ambiguous');inverse=inverse.replace(e.after,e.before)}if(inverse!==source)throw Error('Compiled inverse differs');
 return {output,edits,supportSha256:sha(support),sourceSha256:FRAME,outputSha256:sha(output),inverseExact:true};
}
module.exports={adapt,sha,FRAME};
