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
  const roots=new Set(profile.nodeBindings.map(spec=>get(spec.rootKey))),baselines=new Map(),edits=new Map(),observed=new Map(),archivedMembers=new Map();
  for(const panel of panels.values())baselines.set(panel.status,{nodes:[...panel.status.childNodes],text:panel.status.textContent});
  for(const member of memberSet){baselines.set(member,{hidden:member.getAttribute('hidden')});observed.set(member,member.getAttribute('hidden'))}for(const panel of panels.values())observed.set(panel.status,{text:panel.status.textContent,nodes:[...panel.status.childNodes]});
  // An externally authenticated profile names exact original excluded slices.
  // No selector category alone grants permission to load or edit a history.
  const historySlots=profile.historySlots===undefined?[]:profile.historySlots;
  if(!Array.isArray(historySlots))fail('history slot table');
  const histories=new Map(),historyNodes=new Map(),insertedHistory=new Set(),historyTops=new Set(),historyPre=new Map(),initialHistories=new Map();
  const historyAttrs=node=>Array.from(node.attributes,attr=>[attr.name,attr.value]);
  const forbiddenHistory='li.example-card,li._r28,.sf-panel,.sf-sense,.source-reader,.sentence-jump,[data-rb-j],script,style,link,iframe,audio,video,source,button,input,select,textarea,[data-reviewed-chunk-projection="residual"]';
  const historyClasses=(node,wanted)=>node&&node.classList.length===wanted.length&&wanted.every(name=>node.classList.contains(name));
  function inlineHistoryOwner(owner){return owner?.namespaceURI==='http://www.w3.org/1999/xhtml'&&owner.matches('details')&&historyClasses(owner,['sf-inline-history'])&&owner.parentElement?.matches('.sf-report')&&!owner.closest('li.example-card,li._r28')}
  function supplementalHistoryOwner(owner){
   const content=owner?.parentElement,region=content?.parentElement,html='http://www.w3.org/1999/xhtml';
   return owner?.namespaceURI===html&&owner.matches('details')&&historyClasses(owner,['sf-supplemental-lexeme'])&&
    content?.namespaceURI===html&&content.matches('div')&&historyClasses(content,['field-content'])&&
    region?.namespaceURI===html&&region.matches('section')&&historyClasses(region,['field-callout','primary-definition'])&&
    !owner.closest('li.example-card,li._r28,.sf-report,.examples-section');
  }
  function residualHistoryOwner(owner,row){const container=owner?.parentElement,html='http://www.w3.org/1999/xhtml';return owner?.namespaceURI===html&&owner.tagName==='DETAILS'&&historyClasses(owner,['residual-owner-history'])&&container?.namespaceURI===html&&container.tagName==='DIV'&&historyClasses(container,['sf-native-ownership-history'])&&container.getAttribute('data-native-ownership-history')==='residual-v1'&&container.parentNode===row&&row?.namespaceURI===html&&row.tagName==='LI'&&row.matches('.example-card');}
  // Keep the archived DIV exceptions as exact graphs, never a general grant
  // for native LI rows, live semantic containers, or unknown history owners.
  function archivedHistoryPair(node,fragment,state){
   const archive=node.parentElement;
   if(node.namespaceURI!=='http://www.w3.org/1999/xhtml'||!node.matches('div')||!historyClasses(node,['sf-sentence-pair','example-card'])||archive?.namespaceURI!=='http://www.w3.org/1999/xhtml')return false;
   if(state.residualArchive&&archive.tagName==='DETAILS'&&historyClasses(archive,['sf-archived-example'])&&!archive.open&&archive.parentNode===fragment)return true;
   if(!archive.matches('article'))return false;
   if(state.inlineArchive)return historyClasses(archive,['sf-example','sf-archived-example'])&&archive.parentNode===fragment;
   const detail=archive.parentElement;
   return state.ownershipArchive&&historyClasses(archive,['sf-example'])&&detail?.namespaceURI==='http://www.w3.org/1999/xhtml'&&
    detail.matches('details')&&historyClasses(detail,['sf-inline-history'])&&!detail.open&&detail.parentNode===fragment;
  }
  function graph(node,spec,parent,slot,inserted=false){
   if(!spec||node.nodeType!==spec.type)fail('history node type');
   if(node.nodeType===1){if(node.tagName!==spec.name||node.namespaceURI!==spec.namespace||JSON.stringify(historyAttrs(node))!==JSON.stringify(spec.attrs)||node.childNodes.length!==spec.children.length)fail('history node graph');}
   else if(node.data!==spec.text)fail('history text graph');
   const record={node,parent,slot,attrs:node.nodeType===1?spec.attrs:null,text:node.nodeType===1?null:spec.text,children:[...node.childNodes]};historyNodes.set(node,record);if(inserted)insertedHistory.add(node);
   if(node.nodeType===1)record.children.forEach((child,n)=>graph(child,spec.children[n],node,slot,inserted));
  }
  function historyOwner(spec){const found=[...doc.querySelectorAll(spec.region.selector)];if(found.length!==spec.region.total)fail('history semantic region');return at(found[spec.region.ordinal],spec.region.ownerPath)}
  for(const spec of historySlots){
   if(!spec||spec.schema!=='study-compiled-excluded-history-slot.v1'||spec.sourceArtifactSha256!==profile.bindings.sourceArtifactSha256||!['.examples-section','.sf-report','.primary-definition'].includes(spec.region?.selector)||!Number.isSafeInteger(spec.region.ordinal)||!Number.isSafeInteger(spec.region.total)||!Array.isArray(spec.region.ownerPath)||!Array.isArray(spec.parts)||!spec.parts.length)fail('history capability shape');
   const owner=historyOwner(spec),anchor=owner&&at(owner,spec.anchorPath),manifest=owner&&at(owner,spec.manifestPath),row=owner?.closest('li.example-card'),jump=row?.querySelector('.sentence-jump');
   const inlineArchive=spec.region.selector==='.sf-report'&&inlineHistoryOwner(owner),supplementalArchive=spec.region.selector==='.primary-definition'&&supplementalHistoryOwner(owner);
   const confirmation=owner?.namespaceURI==='http://www.w3.org/1999/xhtml'&&owner.matches('details')&&(historyClasses(owner,['sf-source-confirmation-history'])||historyClasses(owner,['sf-source-confirmation-history','sf-final-history']))&&owner.parentNode===row&&jump;
   const residualArchive=spec.region.selector==='.examples-section'&&residualHistoryOwner(owner,row)&&!!jump&&owner.closest('.examples-section')===[...doc.querySelectorAll('.examples-section')][spec.region.ordinal];
   const ownerAllowed=inlineArchive||supplementalArchive||(spec.region.selector==='.examples-section'&&(owner?.matches('details.sf-ownership-history')||confirmation||residualArchive));
   if(!ownerAllowed||!owner.matches('details')||owner.open||!anchor?.matches('.as-lazy[data-as-kind="detail"]')||anchor.parentNode!==owner||!manifest?.matches('script.as-manifest[type="application/json"]')||manifest.parentNode!==anchor||manifest.textContent!==spec.manifestText||histories.has(manifest)||JSON.stringify(historyAttrs(owner))!==JSON.stringify(spec.ownerAttrs)||JSON.stringify(jump?[jump.getAttribute('data-rb-j'),jump.getAttribute('data-latex-url'),jump.getAttribute('data-full-paper-url')]:null)!==JSON.stringify(spec.nativeSource))fail('history owner/manifest');
   const value=JSON.parse(spec.manifestText);if(value.schema!=='anki-slim-segments.v1'||value.parts.length!==spec.parts.length||value.total!==spec.parts.reduce((n,p)=>n+p.count,0))fail('history manifest count');
   for(let n=0;n<spec.parts.length;n++){const part=spec.parts[n],declared=value.parts[n],e=part.consumerEvidence;if(!Number.isSafeInteger(part.count)||part.count<0||part.src!=='_as_'+part.sha256?.slice(0,24)+'.js'||!/^[a-f0-9]{64}$/.test(part.sha256)||JSON.stringify(declared)!==JSON.stringify({src:part.src,sha256:part.sha256,count:part.count})||!Array.isArray(part.tree)||!Array.isArray(part.evidence)||!e||['fine_example_roots','bank_containers','group_panels','group_physical_native_rows','residual_key_targets'].some(key=>!Array.isArray(e[key])||e[key].length)||!Array.isArray(e.projection_pair_roots)||e.projection_pair_roots.some(pair=>pair.excluded!==true))fail('history part/consumer evidence');}
   const residualBinding=residualArchive?{row,jump,container:owner.parentNode,containerAttrs:historyAttrs(owner.parentNode),rowAttrs:historyAttrs(row),region:owner.closest('.examples-section'),rowParent:row.parentNode,rowPosition:[...row.parentNode.childNodes].indexOf(row),jumpParent:jump.parentNode,jumpPosition:[...jump.parentNode.childNodes].indexOf(jump)}:null;
   const state={spec,owner,anchor,manifest,loaded:0,inlineArchive,residualArchive,residualBinding,ownershipArchive:spec.region.selector==='.examples-section'&&owner.matches('details.sf-ownership-history')};histories.set(manifest,state);roots.add(owner);graph(owner,spec.ownerTree,owner.parentNode,state);
  }
  // Initial closed AF evidence keeps its original placeholder in the delivery.
  // Only an authenticated, exact-bound PRE receives this write capability; the
  // shared bank stores one complete source text per logical SHA, not per PRE.
  const hasInitialSlots=Object.prototype.hasOwnProperty.call(profile,'initialHistorySlots'),hasInitialText=Object.prototype.hasOwnProperty.call(profile,'initialHistoryText');
  const initialText=profile.initialHistoryText,initialSlots=profile.initialHistorySlots,usedHistoryText=new Set();
  const validPath=value=>Array.isArray(value)&&value.every(n=>Number.isSafeInteger(n)&&n>=0);
  const validAttrs=value=>Array.isArray(value)&&value.every(pair=>Array.isArray(pair)&&pair.length===2&&pair.every(v=>typeof v==='string'))&&new Set(value.map(pair=>pair[0])).size===value.length;
  if(hasInitialSlots!==hasInitialText||hasInitialSlots&&(!Array.isArray(initialSlots)||!initialText||typeof initialText!=='object'||Array.isArray(initialText)||Object.entries(initialText).some(([pin,text])=>!/^[a-f0-9]{64}$/.test(pin)||typeof text!=='string')))fail('initial history table');
  if(hasInitialSlots)for(const spec of initialSlots){
   if(!spec||Object.keys(spec).sort().join('|')!=='media|ownerAttrs|ownerPath|placeholder|relativePath|requiredAttrs|resourceSha256|rootKey|sha256'||typeof spec.rootKey!=='string'||!validPath(spec.relativePath)||!validPath(spec.ownerPath)||!validAttrs(spec.requiredAttrs)||!validAttrs(spec.ownerAttrs)||typeof spec.placeholder!=='string'||!/^_af_[a-f0-9]{24}\.js$/.test(spec.media)||!/^[a-f0-9]{64}$/.test(spec.sha256)||!/^[a-f0-9]{64}$/.test(spec.resourceSha256)||!Object.prototype.hasOwnProperty.call(initialText,spec.sha256))fail('initial history capability shape');
   const rootSpec=specs.get(spec.rootKey),logical=get(spec.rootKey),pre=at(logical,spec.relativePath),owner=at(logical,spec.ownerPath),html='http://www.w3.org/1999/xhtml';
   if(rootSpec.rootKey!==spec.rootKey||rootSpec.relativePath.length||!roots.has(logical)||!pre||pre.namespaceURI!==html||pre.tagName!=='PRE'||pre.hasAttribute('is')||!owner||owner.namespaceURI!==html||owner.tagName!=='DETAILS'||owner.hasAttribute('is')||owner.hasAttribute('class')||owner.open||pre.parentNode!==owner||initialHistories.has(pre)||pre.getAttribute('data-native-history-media')!==spec.media||pre.getAttribute('data-native-history-sha')!==spec.sha256||pre.getAttribute('data-native-history-ready')!==null&&pre.getAttribute('data-native-history-ready')!=='false'||JSON.stringify(historyAttrs(pre))!==JSON.stringify(spec.requiredAttrs)||JSON.stringify(historyAttrs(owner))!==JSON.stringify(spec.ownerAttrs)||pre.textContent!==spec.placeholder||[...pre.childNodes].some(node=>node.nodeType!==3))fail('initial history binding');
   const state={spec,logical,owner,pre,ownerChildren:[...owner.childNodes]};initialHistories.set(pre,state);roots.add(owner);usedHistoryText.add(spec.sha256);
   historyPre.set(pre,{text:spec.placeholder,ready:pre.getAttribute('data-native-history-ready'),expectedText:initialText[spec.sha256]});
  }
  function historyEvidenceText(item){
   if(!item||!validPath(item.path)||!/^_af_[a-f0-9]{24}\.js$/.test(item.media)||!/^[a-f0-9]{64}$/.test(item.sha256))fail('history evidence binding');
   const hasText=Object.prototype.hasOwnProperty.call(item,'text'),hasKey=Object.prototype.hasOwnProperty.call(item,'textKey');
   if(hasText===hasKey)fail('history evidence text capability');
   if(hasText){if(typeof item.text!=='string')fail('history evidence text capability');return item.text;}
   if(Object.keys(item).sort().join('|')!=='media|path|resourceSha256|sha256|textKey'||item.textKey!==item.sha256||!/^[a-f0-9]{64}$/.test(item.resourceSha256)||!hasInitialText||!Object.prototype.hasOwnProperty.call(initialText,item.textKey))fail('history evidence text key');
   usedHistoryText.add(item.textKey);return initialText[item.textKey];
  }
  for(const state of histories.values())for(const part of state.spec.parts){const paths=new Set();for(const item of part.evidence){historyEvidenceText(item);const key=JSON.stringify(item.path);if(paths.has(key))fail('duplicate history evidence path');paths.add(key);}}
  if(hasInitialSlots&&Object.keys(initialText).some(pin=>!usedHistoryText.has(pin)))fail('unused initial history text');
  function checkInitialHistory(){for(const {spec,logical,owner,pre,ownerChildren}of initialHistories.values()){
   const known=historyPre.get(pre);
   if(get(spec.rootKey)!==logical||at(logical,spec.relativePath)!==pre||at(logical,spec.ownerPath)!==owner||pre.parentNode!==owner||!pre.isConnected||pre.ownerDocument!==doc||owner.ownerDocument!==doc||!same([...owner.childNodes],ownerChildren))fail('initial history node moved/replaced');
   if(JSON.stringify(historyAttrs(owner).filter(([name])=>name!=='open'))!==JSON.stringify(spec.ownerAttrs)||JSON.stringify(historyAttrs(pre).filter(([name])=>name!=='data-native-history-ready'))!==JSON.stringify(spec.requiredAttrs.filter(([name])=>name!=='data-native-history-ready'))||pre.getAttribute('data-native-history-ready')!==known.ready)fail('initial history attribute changed');
   if(pre.textContent!==known.text||[...pre.childNodes].some(node=>node.nodeType!==3))fail('initial history evidence text changed');
  }}
  function checkResidualHistory(state){const b=state.residualBinding;if(!b)return;if(!residualHistoryOwner(state.owner,b.row)||state.owner.parentNode!==b.container||state.owner.closest('.examples-section')!==b.region||b.row.parentNode!==b.rowParent||b.rowParent.childNodes[b.rowPosition]!==b.row||JSON.stringify(historyAttrs(b.container))!==JSON.stringify(b.containerAttrs)||JSON.stringify(historyAttrs(b.row))!==JSON.stringify(b.rowAttrs)||b.row.querySelector('.sentence-jump')!==b.jump||b.jump.parentNode!==b.jumpParent||b.jumpParent.childNodes[b.jumpPosition]!==b.jump||JSON.stringify([b.jump.getAttribute('data-rb-j'),b.jump.getAttribute('data-latex-url'),b.jump.getAttribute('data-full-paper-url')])!==JSON.stringify(state.spec.nativeSource))fail('residual history source changed');}
  function assertHistorySlots(){checkInitialHistory();const all=[...doc.querySelectorAll('script.as-manifest')];if(all.length!==histories.size||all.some(n=>!histories.has(n)))fail('uncovered history slot');for(const state of histories.values()){if(historyOwner(state.spec)!==state.owner||state.anchor.parentNode!==state.owner||state.manifest.parentNode!==state.anchor||state.manifest.textContent!==state.spec.manifestText)fail('history owner moved/replaced');checkResidualHistory(state);}return true}
  function historyState(slot){const state=histories.get(slot?.manifest);if(!state||slot.anchor!==state.anchor||slot.holder!==state.owner||slot.detail!==state.owner||slot.kind!=='disclosure'||slot.panel!==null||JSON.stringify(slot.value)!==state.spec.manifestText||slot.at!==state.loaded)fail('uncovered or changed history request');return state}
  function checkHistory(authoredPanel=null){assertHistorySlots();checkArchivedMembers(authoredPanel);for(const record of historyNodes.values()){
   const {node,parent,slot}=record;if(node.parentNode!==parent||!node.isConnected||node.ownerDocument!==doc)fail('history node moved/replaced');
   if(node.nodeType!==1){if(node.data!==record.text)fail('history text changed');continue;}
   const expected=new Map(record.attrs);if(expected.has('class'))expected.set('class',cleanClass(expected.get('class')));const archived=archivedMembers.get(node);if(archived)expected.delete('hidden');
   const dynamic=historyPre.get(node);if(dynamic){if(node.textContent!==dynamic.text||[...node.childNodes].some(n=>n.nodeType!==3))fail('history evidence text changed');expected.delete('data-native-history-ready');}
   for(const attr of node.attributes){if(archived&&attr.name==='hidden')continue;if(attr.name==='open'&&node.tagName==='DETAILS')continue;if(node===slot.owner&&attr.name==='aria-busy'){if(attr.value!=='true')fail('history busy state');continue;}if(node===slot.manifest&&attr.name==='data-as-state'){if(!['loading','partial','ready','failed'].includes(attr.value)||attr.value==='ready'&&slot.loaded!==slot.spec.parts.length)fail('history loader state');continue;}if(node===slot.manifest&&attr.name==='data-as-loaded-parts'){if(attr.value!==String(slot.loaded))fail('history loaded count');continue;}if(dynamic&&attr.name==='data-native-history-ready'){if(attr.value!==dynamic.ready)fail('history evidence ready state');continue;}if(!expected.has(attr.name)||(attr.name==='class'?cleanClass(attr.value):attr.value)!==expected.get(attr.name))fail('history attribute changed');expected.delete(attr.name);}
   if(expected.size)fail('history attribute removed');if(dynamic){if(node.getAttribute('data-native-history-ready')!==dynamic.ready)fail('history evidence ready removed');}else if(!same([...node.childNodes],record.children))fail('history child graph changed');
  }}
  function authorizeHistoryPart(slot,part,fragment){
   if(disposed||!isCurrent())return false;assertCurrent();checkHistory();const state=historyState(slot),wanted=state.spec.parts[state.loaded];
   if(!wanted||part.src!==wanted.src||part.sha256!==wanted.sha256||part.count!==wanted.count||fragment.nodeType!==11||fragment.querySelector(forbiddenHistory)||fragment.querySelector('.as-lazy,.as-manifest')||[...fragment.querySelectorAll('.example-card')].some(node=>!archivedHistoryPair(node,fragment,state)))fail('history part scope');
   const top=[...fragment.childNodes],preTextJoins=[];if(top.length!==wanted.tree.length)fail('history part root graph');
   // WebKit parses long archived PRE text into adjacent Text nodes. Accept only
   // an exact, all-Text partition of the one pinned Text, then canonicalize it
   // after the entire graph and its source capabilities have been checked.
   function equal(node,spec){
    if(node.nodeType!==spec.type)fail('history part graph type');
    if(node.nodeType===1){
     if(node.tagName!==spec.name||node.namespaceURI!==spec.namespace||JSON.stringify(historyAttrs(node))!==JSON.stringify(spec.attrs))fail('history part graph attributes');
     const children=[...node.childNodes];
     if(children.length!==spec.children.length){
      if(node.tagName!=='PRE'||node.namespaceURI!=='http://www.w3.org/1999/xhtml'||spec.children.length!==1||spec.children[0].type!==3||children.length<2||children.some(child=>child.nodeType!==3)||children.map(child=>child.data).join('')!==spec.children[0].text)fail('history part graph attributes');
      preTextJoins.push({node,text:spec.children[0].text});return;
     }
     children.forEach((child,index)=>equal(child,spec.children[index]));
    }else if(node.data!==spec.text)fail('history part graph text');
   }
   top.forEach((node,n)=>equal(node,wanted.tree[n]));
   const pairs=[...fragment.querySelectorAll('.sf-sentence-pair')];if(pairs.length!==wanted.consumerEvidence.projection_pair_roots.length||pairs.some(n=>!n.closest('.sf-archived-native-example,.sf-archived-example,.sf-original-history-panel,.sf-ownership-authority')&&!archivedHistoryPair(n,fragment,state)))fail('history producer exclusion drift');
   const evidence=wanted.evidence.map(item=>{const expectedText=historyEvidenceText(item),pre=at(fragment,item.path);if(!pre?.matches('pre[data-native-history-media]')||pre.dataset.nativeHistoryMedia!==item.media||pre.dataset.nativeHistorySha!==item.sha256)fail('history evidence binding');return{pre,item,expectedText};});
   const ownerRecord=historyNodes.get(state.owner),index=ownerRecord.children.indexOf(state.anchor);if(index<0)fail('history anchor changed');
   for(const {node,text}of preTextJoins){const first=node.firstChild;first.data=text;node.replaceChildren(first);}
   ownerRecord.children.splice(index,0,...top);top.forEach((node,n)=>{historyTops.add(node);graph(node,wanted.tree[n],state.owner,state,true)});for(const {pre,item,expectedText}of evidence)historyPre.set(pre,{...item,text:pre.textContent,ready:pre.getAttribute('data-native-history-ready'),expectedText});const panel=[...panels.values()].find(value=>value.panel===state.owner.closest('.sf-panel'));if(panel)registerArchivedMembers(panel,[...fragment.querySelectorAll('.sf-example')],true);state.loaded++;return true;
  }
  function authorizeHistoryText(pre,text,result){
   if(disposed||!isCurrent())return false;assertCurrent();checkHistory();const known=historyPre.get(pre);if(!known||typeof text!=='string'||!result||typeof result.ready!=='boolean'||typeof result.failed!=='boolean'||result.ready===result.failed||result.ready&&text!==known.expectedText||result.failed&&!text.startsWith('证据载入失败：'))fail('uncovered history evidence write');
   function forget(node){for(const child of node.childNodes)forget(child);historyNodes.delete(node)}for(const child of pre.childNodes)forget(child);
   known.text=text;known.ready=result.ready?'true':pre.getAttribute('data-native-history-ready');return true;
  }
  function protectedText(node){if(!historyTops.size&&!initialHistories.size)return node.textContent;let text='';function walk(n){if(historyTops.has(n))return;const initial=initialHistories.get(n);if(initial){text+=initial.spec.placeholder;return;}if(n.nodeType===3||n.nodeType===4){text+=n.data;return;}for(const child of n.childNodes)walk(child)}walk(node);return text;}

  // The original year handler visits every descendant, including archived
  // rows. Only these exact source nodes may participate in its transaction;
  // grouping and the final displayed count still concern direct members.
  function registerArchivedMembers(panel,rows,fromHistory=false){for(const node of rows){
   if(panel.members.includes(node)||archivedMembers.has(node))continue;
   const record=historyNodes.get(node),parent=fromHistory?record?.parent:node.parentNode;
   if(node.namespaceURI!=='http://www.w3.org/1999/xhtml'||node.tagName!=='ARTICLE'||!node.matches('.sf-example')||!parent)continue;
   if(fromHistory){if(!record||!insertedHistory.has(node))fail('unbound archived history member');}
   else if(node.closest('.sf-panel')!==panel.panel||parent.namespaceURI!=='http://www.w3.org/1999/xhtml'||!parent.matches('details.sf-inline-history'))continue;
   const children=fromHistory?historyNodes.get(parent)?.children:[...parent.childNodes],position=children?.indexOf(node);
   if(position===undefined||position<0)fail('archived filter position');
   archivedMembers.set(node,{node,panel,parent,position,year:node.getAttribute('data-sf-year'),attrs:historyAttrs(node).filter(([name])=>name!=='hidden'),hidden:node.getAttribute('hidden')});
  }}
  function activeFilterPanel(requested=null){
   const tx=filterTransaction;if(!tx||disposed||!isCurrent()||requested&&requested!==tx.panel)return null;
   const {panel,button}=tx;if(!button.isConnected||button.ownerDocument!==doc||button.closest('.sf-panel')!==panel.panel||!same([...panel.panel.querySelectorAll('[data-sf-filter]')].filter(n=>n.closest('.sf-panel')===panel.panel),panel.controls)||panel.controls.some(n=>n.getAttribute('aria-pressed')!==String(n===button)))return null;
   const year=button.getAttribute('data-sf-filter'),rows=[...panel.panel.querySelectorAll('.sf-example')];
   if(rows.some(n=>!panel.members.includes(n)&&archivedMembers.get(n)?.panel!==panel)||rows.some(n=>n.hidden!==(year!=='all'&&n.dataset.sfYear!==year))||panel.status.textContent!=='显示 '+rows.filter(n=>!n.hidden).length+' 处原文')return null;
   return panel;
  }
  function checkArchivedMembers(authoredPanel=null){const permitted=activeFilterPanel(authoredPanel);for(const entry of archivedMembers.values()){
   const {node,panel,parent,position}=entry;
   if(!node.isConnected||node.ownerDocument!==doc||node.parentNode!==parent||parent.childNodes[position]!==node||node.closest('.sf-panel')!==panel.panel||node.getAttribute('data-sf-year')!==entry.year||JSON.stringify(historyAttrs(node).filter(([name])=>name!=='hidden'))!==JSON.stringify(entry.attrs))fail('archived filter member changed');
   const selected=permitted===panel?panel.controls.find(n=>n.getAttribute('aria-pressed')==='true'):null,year=selected?.getAttribute('data-sf-filter')||'all',expected=permitted===panel?(year!=='all'&&node.dataset.sfYear!==year?'':null):entry.hidden;
   if(node.getAttribute('hidden')!==expected)fail('external archived visibility change');
  }}
  for(const panel of panels.values())registerArchivedMembers(panel,[...panel.panel.querySelectorAll('.sf-example')]);

  const semanticSelector='.sf-report,.examples-section,ol.examples,.example-card,li._r28,.sf-sentence-pair,.sf-panel,.sf-example';
  const lazySelector='.as-lazy,script.as-manifest',boundarySelector=semanticSelector+','+lazySelector;
  const semanticNodes=[...doc.querySelectorAll(semanticSelector)],semanticParents=semanticNodes.map(node=>node.parentNode),semanticKeys=semanticNodes.map(node=>node.getAttribute(KEY)),lazyNodes=[...doc.querySelectorAll(lazySelector)];
  function checkSemanticBoundary(){const current=[...doc.querySelectorAll(semanticSelector)].filter(node=>!insertedHistory.has(node));if(!same(current,semanticNodes)||current.some((node,n)=>node.parentNode!==semanticParents[n]||node.getAttribute(KEY)!==semanticKeys[n]))fail('semantic row/root membership changed');if(!same([...doc.querySelectorAll(lazySelector)],lazyNodes))fail('new or changed lazy semantic slot not covered')}
  function boundaryChanged(records){return records.some(record=>{if(record.type==='childList')return [...record.addedNodes,...record.removedNodes].some(node=>node.nodeType===1&&(node.matches(boundarySelector)||node.querySelector(boundarySelector)));if(record.type!=='attributes')return false;if(record.attributeName===KEY)return true;if(record.attributeName!=='class')return false;const roles=value=>(value||'').split(/\s+/).filter(name=>['sf-report','examples-section','examples','example-card','_r28','sf-sentence-pair','sf-panel','sf-example','as-lazy','as-manifest'].includes(name)).sort().join(' ');return roles(record.oldValue)!==roles(record.target.getAttribute('class'))})}
  let disposed=false,invalid=null,observer=null,filterTransaction=null;
  function clearFilterTransaction(){const tx=filterTransaction;filterTransaction=null;if(tx)doc.defaultView.clearTimeout(tx.timer);}
  function invalidate(error){if(!invalid){invalid=error;clearFilterTransaction();observer?.disconnect();doc.defaultView.removeEventListener('click',beginFilterTransaction,true);doc.removeEventListener('keydown',keyboard,true);options.onInvalid?.(error)}return error}
  function recordCheck(records,authoredPanel=null){if(historySlots.length||initialHistories.size)checkHistory(authoredPanel);else checkArchivedMembers(authoredPanel);if(boundaryChanged(records))checkSemanticBoundary();for(const record of records){if(historyNodes.has(record.target)||historyPre.has(record.target)||record.target.nodeType===3&&initialHistories.has(record.target.parentNode))continue;const target=record.target.nodeType===1?record.target:record.target.parentElement;if(!target)continue;let contained=false;for(let node=target;node;node=node.parentNode){if(roots.has(node)){contained=true;break}}if(!contained)continue;
   if(record.type==='attributes'){
    if(readerLinks.has(target)&&['href','title','aria-disabled'].includes(record.attributeName)){validateReader(target,readerLinks.get(target));continue}
    if(record.attributeName==='class'&&cleanClass(record.oldValue)===cleanClass(target.getAttribute('class')))continue;
    if(record.attributeName==='hidden'&&memberSet.has(target))continue;
    if(record.attributeName==='hidden'&&archivedMembers.has(target))continue;
    if(record.attributeName==='aria-pressed'&&filters.has(target))continue;
    if(record.attributeName==='open'&&target.tagName==='DETAILS')continue;
   }
   if(statusSet.has(target)||statusSet.has(target.parentElement))continue;
   fail('semantic DOM mutation requires original-path fallback');
  }}
  function assertCurrent(authoredPanel=null){if(disposed)fail('disposed');if(invalid)throw invalid;if(!isCurrent())fail('cancelled');if(observer)recordCheck(observer.takeRecords(),authoredPanel)}
  function validateNode(spec){const node=get(spec.key),logical=get(spec.rootKey);if(node.ownerDocument!==doc||!node.isConnected||at(regions.get(spec.region.selector+':'+spec.region.ordinal).node,spec.region.rootPath)!==logical||at(logical,spec.relativePath)!==node||node.tagName!==spec.tag||node.namespaceURI!==spec.namespace)fail('node position '+spec.key);
   if(spec.logicalRoot.kind==='occurrence'&&logical.getAttribute('data-sf-occurrence-id')!==spec.logicalRoot.id)fail('occurrence owner');
   if(spec.logicalRoot.kind==='native-source'){const jump=logical.querySelector('.sentence-jump,[data-rb-j]');if((jump?JSON.stringify([jump.getAttribute('data-rb-j'),jump.getAttribute('data-latex-url'),jump.getAttribute('data-full-paper-url')]):null)!==spec.logicalRoot.id)fail('native source owner')}
   const wanted=new Map(spec.requiredAttrs);for(const [name,value]of wanted){if(name==='hidden'&&memberSet.has(node))continue;const actual=node.getAttribute(name);if(name==='class'?cleanClass(actual)!==cleanClass(value):actual!==value)fail('role attribute '+spec.key+':'+name)}
   for(const attr of node.attributes)if(!wanted.has(attr.name)&&!(attr.name==='hidden'&&memberSet.has(node)))fail('extra semantic attribute '+spec.key);
   if(!spec.roles.some(r=>['sense-panel','group-panel','group-status'].includes(r))&&protectedText(node)!==spec.exactText)fail('text '+spec.key);
  }
  function validate(authoredPanel=null){authoredPanel=authoredPanel||activeFilterPanel();assertCurrent(authoredPanel);checkHistory(authoredPanel);checkSemanticBoundary();for(const [node,spec]of readerLinks)validateReader(node,spec);for(const {spec,node}of regions.values()){const current=[...doc.querySelectorAll(spec.selector)];if(current.length!==spec.total||current[spec.ordinal]!==node)fail('semantic region moved/replaced')}for(const spec of specs.values())validateNode(spec);for(const panel of panels.values()){
   if(!same([...panel.panel.children].filter(n=>n.matches('.sf-example')),panel.members))fail('panel semantic membership');
   if(!same([...panel.panel.querySelectorAll('[data-sf-filter]')].filter(n=>n.closest('.sf-panel')===panel.panel),panel.controls))fail('panel controls');
   if(authoredPanel!==panel){for(const member of panel.members){const expected=observed.get(member);if(member.getAttribute('hidden')!==expected)fail('external visibility change')}
    const state=observed.get(panel.status);if(panel.status.textContent!==state.text||!same([...panel.status.childNodes],state.nodes))fail('external status change');
   }else{const selected=panel.controls.find(n=>n.getAttribute('aria-pressed')==='true'),year=selected?.getAttribute('data-sf-filter')||'all',rows=[...panel.panel.querySelectorAll('.sf-example')];if(rows.some(n=>!panel.members.includes(n)&&archivedMembers.get(n)?.panel!==panel))fail('uncovered authored filter member');if(rows.some(n=>n.hidden!==(year!=='all'&&n.dataset.sfYear!==year)))fail('authored filter visibility');const count=rows.filter(n=>!n.hidden).length;if(panel.status.textContent!=='显示 '+count+' 处原文')fail('authored filter status')}
  }}
  function writeHidden(node,value){if(node.hidden===value)return;let edit=edits.get(node);if(!edit){edit={...baselines.get(node)};edits.set(node,edit)}node.hidden=value;edit.lastHidden=node.getAttribute('hidden')}
  function writeStatus(node,text){if(node.textContent===text)return;let edit=edits.get(node);if(!edit){edit={...baselines.get(node)};edits.set(node,edit)}node.textContent=text;edit.lastText=text;edit.lastNodes=[...node.childNodes]}
  function apply(panel,authored){try{validate(authored?panel:null);const selected=panel.controls.find(n=>n.getAttribute('aria-pressed')==='true'),year=selected?.dataset.sfFilter||'all';for(const members of panel.groups)members.forEach((node,n)=>writeHidden(node,n>0||(year!=='all'&&node.dataset.sfYear!==year)));writeStatus(panel.status,'显示 '+panel.members.filter(n=>!n.hidden).length+' 条原文');for(const member of panel.members)observed.set(member,member.getAttribute('hidden'));for(const entry of archivedMembers.values())if(entry.panel===panel)entry.hidden=entry.node.getAttribute('hidden');observed.set(panel.status,{text:panel.status.textContent,nodes:[...panel.status.childNodes]});if(observer)recordCheck(observer.takeRecords());return true}finally{if(filterTransaction?.panel===panel)clearFilterTransaction();}}
  function beginFilterTransaction(event){
   if(disposed||invalid||!isCurrent())return;const button=event.target?.closest?.('[data-sf-filter]'),panel=button&&[...panels.values()].find(value=>value.panel===button.closest('.sf-panel'));
   if(!panel||!filters.has(button)||button.ownerDocument!==doc||!button.closest('.sf-report')||![...archivedMembers.values()].some(value=>value.panel===panel))return;
   try{clearFilterTransaction();validate();const tx={event,panel,button,timer:null};filterTransaction=tx;tx.timer=doc.defaultView.setTimeout(()=>{if(filterTransaction!==tx)return;clearFilterTransaction();if(disposed||invalid||!isCurrent())return;try{validate();}catch(error){invalidate(error);}},0);}catch(error){invalidate(error);}
  }
  function keyboard(event){if(disposed||invalid||event.defaultPrevented||event.repeat||event.ctrlKey||event.altKey||event.metaKey||(event.key!=='Enter'&&event.key!==' '))return;const el=event.target;if(!wrappers.has(el)&&!residual.has(el))return;if(el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable]'))return;
   try{assertCurrent();validateNode(specs.get(el.getAttribute(KEY)));if(residual.has(el)){if(!el.matches('.card-chunk[data-reviewed-chunk-projection="residual"]')||!/^\d+( \d+)*$/.test(el.getAttribute('data-chunk-ids')||'')||el.closest('.sf-archived-example,.sf-inline-history'))return;const whole=(el.getAttribute('data-chunk-sentence-ids')||'').split(' ');if(el.getAttribute('data-chunk-ids').split(' ').every(id=>whole.includes(id)))return}event.preventDefault();el.dispatchEvent(new doc.defaultView.MouseEvent('click',{bubbles:true,cancelable:true}))}catch(error){invalidate(error)}
  }

  validate(); // All input validation precedes listeners, observers and DOM writes.
  observer=new doc.defaultView.MutationObserver(records=>{try{recordCheck(records)}catch(error){invalidate(error)}});const observationRoots=new Set([...regions.values()].map(value=>value.node).concat([...histories.values()].map(value=>value.owner.closest(value.spec.region.selector)))),boundaryAncestors=new Set();for(const node of observationRoots){let covered=false;for(let parent=node.parentNode;parent;parent=parent.parentNode){boundaryAncestors.add(parent);if(observationRoots.has(parent))covered=true}if(!covered)observer.observe(node,{subtree:true,childList:true,characterData:true,attributes:true,attributeOldValue:true})}for(const node of boundaryAncestors){let covered=false;for(let parent=node;parent;parent=parent.parentNode){if(observationRoots.has(parent)){covered=true;break}}if(!covered)observer.observe(node,{childList:true})}
  doc.defaultView.addEventListener('click',beginFilterTransaction,true);
  if(wrappers.size||residual.size)doc.addEventListener('keydown',keyboard,true);
  const handle={ready:Promise.resolve(true),assertHistorySlots(){try{assertCurrent();return assertHistorySlots()}catch(error){throw invalidate(error)}},authorizeHistoryPart(slot,part,fragment){try{return authorizeHistoryPart(slot,part,fragment)}catch(error){error.studyCompiledHistoryFailure=true;throw invalidate(error)}},authorizeHistoryText(pre,text,result){try{return authorizeHistoryText(pre,text,result)}catch(error){error.studyCompiledHistoryFailure=true;throw invalidate(error)}},refresh(slot){try{if(slot!==undefined&&slot!==null)historyState(slot);validate();return true}catch(error){throw invalidate(error)}},applyGrouping(panel){try{const found=typeof panel==='string'?panels.get(panel):[...panels.values()].find(p=>p.panel===panel);if(!found)fail('uncovered panel');return apply(found,true)}catch(error){throw invalidate(error)}},stats(){return{schema:SCHEMA,version:1,projectionWrappers:wrappers.size,residualWrappers:residual.size,panels:panels.size,groups:profile.groups.length,groupedOccurrences:profile.groups.reduce((n,g)=>n+g.memberKeys.length,0),bankRecords:profile.bankRecords.length,invalid:invalid?.message||null,disposed}},dispose(){if(disposed)return;disposed=true;clearFilterTransaction();observer.disconnect();doc.defaultView.removeEventListener('click',beginFilterTransaction,true);doc.removeEventListener('keydown',keyboard,true);if(isCurrent())for(const [node,edit]of edits){if(!node.isConnected||node.ownerDocument!==doc)continue;if('lastHidden'in edit&&node.getAttribute('hidden')===edit.lastHidden){if(edit.hidden===null)node.removeAttribute('hidden');else node.setAttribute('hidden',edit.hidden)}if('lastText'in edit&&node.textContent===edit.lastText&&same([...node.childNodes],edit.lastNodes))node.replaceChildren(...edit.nodes)}installed.delete(doc)}};
  installed.set(doc,{input,handle});return handle;
 }
 root.AnkiCompiledCardRuntime=Object.freeze({install,schema:SCHEMA,version:1});
})(typeof window==='object'?window:globalThis);
