/* Compiled authored baseline. Caller MUST authenticate profile and final HTML
 * against external anchors before install. This module does not self-attest SHA. */
(function(root){
 'use strict';
 const KEY='data-study-compiled-key',SCHEMA='study-compiled-card-interactions.v1',installed=new WeakMap();
 const cleanClass=value=>(value||'').split(/\s+/).filter(v=>v&&v!=='card-chunk-active').join(' ');
 const same=(a,b)=>a.length===b.length&&a.every((v,n)=>v===b[n]);
 function fail(message){throw Error('Compiled card invalid: '+message)}
 function at(node,path){for(const n of path){if(!Number.isSafeInteger(n)||n<0)return null;node=node?.childNodes[n]}return node}
 function install(doc,input,options={}){
  const isCurrent=options.isCurrent||(()=>true);if(!isCurrent())fail('cancelled');
  if(!input||input.schema!==SCHEMA||input.version!==1||input.filter_mode!=='host-after-authored-filter'||input.residual_mode!=='original-listener'||input.residualWrappers?.length)fail('schema/version');
  if(installed.has(doc)){const prior=installed.get(doc);if(prior.input!==input)fail('different profile already installed');return prior.handle}
  const profile=JSON.parse(JSON.stringify(input));
  const requiredPins=['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'];if(!profile.bindings||requiredPins.some(name=>!profile.bindings[name])||Object.values(profile.bindings).some(pin=>typeof pin!=='string'||!/^[a-f0-9]{64}$/.test(pin)))fail('binding pins');
  for(const name of ['nodeBindings','projectionWrappers','residualWrappers','panels','groups','bankRecords','readerLinks'])if(!Array.isArray(profile[name]))fail('missing table '+name);
  const nodes=new Map(),specs=new Map(),regions=new Map();
  for(const node of doc.querySelectorAll('['+KEY+']')){const key=node.getAttribute(KEY);if(nodes.has(key))fail('duplicate DOM key '+key);nodes.set(key,node)}
  for(const spec of profile.nodeBindings){if(!spec||typeof spec.key!=='string'||specs.has(spec.key)||!spec.region||!['.sf-report','.examples-section'].includes(spec.region.selector)||!Number.isSafeInteger(spec.region.ordinal)||!Number.isSafeInteger(spec.region.total)||!Array.isArray(spec.region.rootPath)||!Array.isArray(spec.relativePath)||!Array.isArray(spec.requiredAttrs)||!Array.isArray(spec.roles)||!spec.logicalRoot)fail('node binding shape');specs.set(spec.key,spec);const regionId=spec.region.selector+':'+spec.region.ordinal;if(!regions.has(regionId)){const found=[...doc.querySelectorAll(spec.region.selector)];if(found.length!==spec.region.total||!found[spec.region.ordinal])fail('semantic region');regions.set(regionId,{spec:spec.region,node:found[spec.region.ordinal]})}}
  const get=key=>{if(!specs.has(key)||!nodes.has(key))fail('unbound key '+key);return nodes.get(key)};
  const wrappers=new Set(profile.projectionWrappers.map(get)),residual=new Set(profile.residualWrappers.map(get)),panels=new Map(),memberSet=new Set(),statusSet=new Set(),filters=new Set();
  if(wrappers.size!==profile.projectionWrappers.length||residual.size!==profile.residualWrappers.length)fail('duplicate wrapper');
  for(const key of profile.projectionWrappers)if(!specs.get(key).roles.includes('projection-keyboard-wrapper'))fail('wrapper role');
  for(const entry of profile.panels){if(panels.has(entry.panelKey)||!Array.isArray(entry.memberKeys))fail('panel table');const panel=get(entry.panelKey),status=get(entry.statusKey),members=entry.memberKeys.map(get);if(status.parentElement!==panel||!status.matches('.sf-preview-count')||!panel.matches('.sf-panel')||new Set(members).size!==members.length||members.some(n=>n.parentElement!==panel||!n.matches('.sf-example')))fail('panel members/status');const controls=[...panel.querySelectorAll('[data-sf-filter]')].filter(n=>n.closest('.sf-panel')===panel);controls.forEach(n=>filters.add(n));members.forEach(n=>memberSet.add(n));statusSet.add(status);panels.set(entry.panelKey,{panel,status,members,groups:[],controls})}
  const grouped=new Set();
  for(const entry of profile.groups){const panel=panels.get(entry.panelKey),members=entry.memberKeys.map(get);if(!panel||members.length<2||members.some(n=>!panel.members.includes(n)||grouped.has(n)))fail('group membership');members.forEach(n=>grouped.add(n));panel.groups.push(members)}
  for(const entry of profile.bankRecords){const label=get(entry.labelKey),container=get(entry.containerKey);if(!container.contains(label)||label.getAttribute('data-shared-reading-bank-evidence')!==entry.evidence||Object.entries(entry.compiledAttributes||{}).some(([k,v])=>label.getAttribute(k)!==v))fail('bank binding')}
  const readerLinks=new Map();for(const spec of profile.readerLinks){const node=at(get(spec.rootKey),spec.relativePath);if(!node||!node.matches('.sentence-jump')||readerLinks.has(node))fail('reader binding');readerLinks.set(node,spec)}
  function validateReader(node,spec){if(at(get(spec.rootKey),spec.relativePath)!==node||spec.immutableAttrs.some(([name,value])=>node.getAttribute(name)!==value))fail('reader source identity');const current={href:node.getAttribute('href'),title:node.getAttribute('title'),disabled:node.getAttribute('aria-disabled')};if(JSON.stringify(current)===JSON.stringify(spec.baseline))return;for(const [kind,attribute]of [['latex','data-latex-url'],['full-paper','data-full-paper-url']]){const address=node.getAttribute(attribute);let valid=false;try{const url=new URL(address);valid=/^https?:$/.test(url.protocol)&&!!url.hostname&&!url.username&&!url.password&&!/[\u0000-\u0020\u007f]/.test(address)}catch(_){}const expected={href:valid?address:null,title:'在'+(kind==='latex'?' LaTeX 重排版':'整卷版')+'定位原句',disabled:valid?null:'true'};if(JSON.stringify(current)===JSON.stringify(expected))return}fail('reader state outside authenticated choices')}
  const roots=new Set(profile.nodeBindings.map(spec=>get(spec.rootKey))),baselines=new Map(),edits=new Map(),observed=new Map();
  for(const panel of panels.values())baselines.set(panel.status,{nodes:[...panel.status.childNodes],text:panel.status.textContent});
  for(const member of memberSet){baselines.set(member,{hidden:member.getAttribute('hidden')});observed.set(member,member.getAttribute('hidden'))}for(const panel of panels.values())observed.set(panel.status,{text:panel.status.textContent,nodes:[...panel.status.childNodes]});
  let disposed=false,invalid=null,observer=null;
  function invalidate(error){if(!invalid){invalid=error;observer?.disconnect();doc.removeEventListener('keydown',keyboard,true);options.onInvalid?.(error)}return error}
  function recordCheck(records){for(const record of records){const target=record.target.nodeType===1?record.target:record.target.parentElement;if(!target)continue;let contained=false;for(let node=target;node;node=node.parentNode){if(roots.has(node)){contained=true;break}}if(!contained)continue;
   if(record.type==='attributes'){
    if(readerLinks.has(target)&&['href','title','aria-disabled'].includes(record.attributeName)){validateReader(target,readerLinks.get(target));continue}
    if(record.attributeName==='class'&&cleanClass(record.oldValue)===cleanClass(target.getAttribute('class')))continue;
    if(record.attributeName==='hidden'&&memberSet.has(target))continue;
    if(record.attributeName==='aria-pressed'&&filters.has(target))continue;
    if(record.attributeName==='open'&&target.tagName==='DETAILS')continue;
   }
   if(statusSet.has(target)||statusSet.has(target.parentElement))continue;
   fail('semantic DOM mutation requires original-path fallback');
  }}
  function assertCurrent(){if(disposed)fail('disposed');if(invalid)throw invalid;if(!isCurrent())fail('cancelled');if(observer)recordCheck(observer.takeRecords())}
  function validateNode(spec){const node=get(spec.key),logical=get(spec.rootKey);if(node.ownerDocument!==doc||!node.isConnected||at(regions.get(spec.region.selector+':'+spec.region.ordinal).node,spec.region.rootPath)!==logical||at(logical,spec.relativePath)!==node||node.tagName!==spec.tag||node.namespaceURI!==spec.namespace)fail('node position '+spec.key);
   if(spec.logicalRoot.kind==='occurrence'&&logical.getAttribute('data-sf-occurrence-id')!==spec.logicalRoot.id)fail('occurrence owner');
   if(spec.logicalRoot.kind==='native-source'){const jump=logical.querySelector('.sentence-jump,[data-rb-j]');if((jump?JSON.stringify([jump.getAttribute('data-rb-j'),jump.getAttribute('data-latex-url'),jump.getAttribute('data-full-paper-url')]):null)!==spec.logicalRoot.id)fail('native source owner')}
   const wanted=new Map(spec.requiredAttrs);for(const [name,value]of wanted){if(name==='hidden'&&memberSet.has(node))continue;const actual=node.getAttribute(name);if(name==='class'?cleanClass(actual)!==cleanClass(value):actual!==value)fail('role attribute '+spec.key+':'+name)}
   for(const attr of node.attributes)if(!wanted.has(attr.name)&&!(attr.name==='hidden'&&memberSet.has(node)))fail('extra semantic attribute '+spec.key);
   if(!spec.roles.some(r=>['sense-panel','group-panel','group-status'].includes(r))&&node.textContent!==spec.exactText)fail('text '+spec.key);
  }
  function validate(authoredPanel=null){assertCurrent();for(const [node,spec]of readerLinks)validateReader(node,spec);for(const {spec,node}of regions.values()){const current=[...doc.querySelectorAll(spec.selector)];if(current.length!==spec.total||current[spec.ordinal]!==node)fail('semantic region moved/replaced')}for(const spec of specs.values())validateNode(spec);for(const panel of panels.values()){
   if(!same([...panel.panel.children].filter(n=>n.matches('.sf-example')),panel.members))fail('panel semantic membership');
   if(!same([...panel.panel.querySelectorAll('[data-sf-filter]')].filter(n=>n.closest('.sf-panel')===panel.panel),panel.controls))fail('panel controls');
   if(authoredPanel!==panel){for(const member of panel.members){const expected=observed.get(member);if(member.getAttribute('hidden')!==expected)fail('external visibility change')}
    const state=observed.get(panel.status);if(panel.status.textContent!==state.text||!same([...panel.status.childNodes],state.nodes))fail('external status change');
   }else{const selected=panel.controls.find(n=>n.getAttribute('aria-pressed')==='true'),year=selected?.getAttribute('data-sf-filter')||'all';if(panel.members.some(n=>n.hidden!==(year!=='all'&&n.dataset.sfYear!==year)))fail('authored filter visibility');const count=panel.members.filter(n=>!n.hidden).length;if(panel.status.textContent!=='显示 '+count+' 处原文')fail('authored filter status')}
  }}
  function writeHidden(node,value){if(node.hidden===value)return;let edit=edits.get(node);if(!edit){edit={...baselines.get(node)};edits.set(node,edit)}node.hidden=value;edit.lastHidden=node.getAttribute('hidden')}
  function writeStatus(node,text){if(node.textContent===text)return;let edit=edits.get(node);if(!edit){edit={...baselines.get(node)};edits.set(node,edit)}node.textContent=text;edit.lastText=text;edit.lastNodes=[...node.childNodes]}
  function apply(panel,authored){validate(authored?panel:null);const selected=panel.controls.find(n=>n.getAttribute('aria-pressed')==='true'),year=selected?.dataset.sfFilter||'all';for(const members of panel.groups)members.forEach((node,n)=>writeHidden(node,n>0||(year!=='all'&&node.dataset.sfYear!==year)));writeStatus(panel.status,'显示 '+panel.members.filter(n=>!n.hidden).length+' 条原文');for(const member of panel.members)observed.set(member,member.getAttribute('hidden'));observed.set(panel.status,{text:panel.status.textContent,nodes:[...panel.status.childNodes]});if(observer)recordCheck(observer.takeRecords());return true}
  function keyboard(event){if(disposed||invalid||event.defaultPrevented||event.repeat||event.ctrlKey||event.altKey||event.metaKey||(event.key!=='Enter'&&event.key!==' '))return;const el=event.target;if(!wrappers.has(el)&&!residual.has(el))return;if(el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable]'))return;
   try{assertCurrent();validateNode(specs.get(el.getAttribute(KEY)));if(residual.has(el)){if(!el.matches('.card-chunk[data-reviewed-chunk-projection="residual"]')||!/^\d+( \d+)*$/.test(el.getAttribute('data-chunk-ids')||'')||el.closest('.sf-archived-example,.sf-inline-history'))return;const whole=(el.getAttribute('data-chunk-sentence-ids')||'').split(' ');if(el.getAttribute('data-chunk-ids').split(' ').every(id=>whole.includes(id)))return}event.preventDefault();el.dispatchEvent(new doc.defaultView.MouseEvent('click',{bubbles:true,cancelable:true}))}catch(error){invalidate(error)}
  }

  validate(); // All input validation precedes listeners, observers and DOM writes.
  observer=new doc.defaultView.MutationObserver(records=>{try{recordCheck(records)}catch(error){invalidate(error)}});for(const node of roots){let covered=false;for(let parent=node.parentNode;parent;parent=parent.parentNode){if(roots.has(parent)){covered=true;break}}if(!covered)observer.observe(node,{subtree:true,childList:true,characterData:true,attributes:true,attributeOldValue:true})}
  if(wrappers.size||residual.size)doc.addEventListener('keydown',keyboard,true);
  const handle={ready:Promise.resolve(true),refresh(slot){try{if(slot!==undefined&&slot!==null)fail('lazy semantic slot not covered');validate();return true}catch(error){throw invalidate(error)}},applyGrouping(panel){try{const found=typeof panel==='string'?panels.get(panel):[...panels.values()].find(p=>p.panel===panel);if(!found)fail('uncovered panel');return apply(found,true)}catch(error){throw invalidate(error)}},stats(){return{schema:SCHEMA,version:1,projectionWrappers:wrappers.size,residualWrappers:residual.size,panels:panels.size,groups:profile.groups.length,groupedOccurrences:profile.groups.reduce((n,g)=>n+g.memberKeys.length,0),bankRecords:profile.bankRecords.length,invalid:invalid?.message||null,disposed}},dispose(){if(disposed)return;disposed=true;observer.disconnect();doc.removeEventListener('keydown',keyboard,true);if(isCurrent())for(const [node,edit]of edits){if(!node.isConnected||node.ownerDocument!==doc)continue;if('lastHidden'in edit&&node.getAttribute('hidden')===edit.lastHidden){if(edit.hidden===null)node.removeAttribute('hidden');else node.setAttribute('hidden',edit.hidden)}if('lastText'in edit&&node.textContent===edit.lastText&&same([...node.childNodes],edit.lastNodes))node.replaceChildren(...edit.nodes)}installed.delete(doc)}};
  installed.set(doc,{input,handle});return handle;
 }
 root.AnkiCompiledCardRuntime=Object.freeze({install,schema:SCHEMA,version:1});
})(typeof window==='object'?window:globalThis);
