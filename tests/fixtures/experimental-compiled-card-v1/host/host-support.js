/* Called only from the externally pinned compiled-capability FRAME. */
function makeCompiledProfileSupport(assets, resource, matches, canonical, current) {
 'use strict';
 const owners=new WeakMap(), hash=/^[a-f0-9]{64}$/;
 const schema='study-compiled-card-interactions.v1';
 function fail(message){throw Error('Compiled profile: '+message)}
 function immutable(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(immutable);Object.freeze(value)}return value}
 function asset(value){if(!value||typeof value.src!=='string'||!/^_qa_compiled_[a-z0-9_]+\.(?:js|json|html)$/.test(value.src)||!hash.test(value.sha256||''))fail('asset descriptor');return value}
 async function load(packet,index,side,valid){
  if(index!==1)return null;
  const entry=Object.prototype.hasOwnProperty.call(assets.entries,packet.id)?assets.entries[packet.id]:null;if(!entry)return null;
  if(!valid())return null;
  const source=entry.source,module=entry.module,anchors=entry.anchors;
  if(!source||!module||!anchors||anchors.schema!==schema||anchors.version!==1||entry.decoded!==true)fail('capability/schema');
  if(packet.prepared.source_wrapper_sha256!==source.wrapper_sha256||packet.prepared.source_payload_sha256!==source.payload_sha256||side.proof.source_sha256!==source.side_sha256||side.proof.expanded_sha256!==source.expanded_sha256||canonical(side.proof.registry_pins)!==canonical(source.registry_pins))fail('original side binding');
  const preparedModule=packet.prepared.modules?.[module.original_sha256];
  if(!preparedModule||preparedModule.original_sha256!==module.original_sha256||preparedModule.sha256!==module.sha256)fail('original module binding');
  if(anchors.bindings?.originalModuleSha256!==module.original_sha256||anchors.bindings?.nativeModuleSha256!==module.sha256||anchors.bindings?.derivedHTMLSha256!==entry.html.sha256)fail('external producer binding');
  const values=await Promise.all([entry.html,entry.profile,assets.runtime].map(value=>{asset(value);return resource(new URL(value.src,document.baseURI).href,value.sha256)}));
  if(!valid())return null;
  const [html,raw,runtimeCode]=values;
  if(!(await Promise.all([[html,entry.html.sha256],[raw,entry.profile.sha256],[runtimeCode,assets.runtime.sha256]].map(([text,pin])=>matches(text,pin)))).every(Boolean))fail('external resource SHA');
  if(!valid())return null;
  const profile=JSON.parse(raw);
  if(profile.schema!==schema||profile.version!==1||canonical(profile.bindings)!==canonical(anchors.bindings))fail('external metadata binding');
  return Object.freeze({html,profile:immutable(profile),runtimeCode,runtimeSha256:assets.runtime.sha256});
 }
 function bind(win,doc,value,valid){
  owners.delete(doc);
  if(!Object.prototype.hasOwnProperty.call(win,'StudyCompiledProfileBridge'))Object.defineProperty(win,'StudyCompiledProfileBridge',{configurable:false,writable:false,value:Object.freeze({get(target){const owner=owners.get(target);if(!owner)return null;if(target!==doc||!owner.valid()||!current())fail('expired document owner');return owner.profile},isCurrent(target,profile){const owner=owners.get(target);return!!owner&&target===doc&&owner.profile===profile&&owner.valid()&&current()}})});
  if(value)owners.set(doc,{profile:value.profile,valid});
 }
 return Object.freeze({load,bind,clear(doc){owners.delete(doc)}});
}
