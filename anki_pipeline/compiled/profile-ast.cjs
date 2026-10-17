'use strict';
// Shared v1 profile projection. This extracts authored facts; no semantic renderer runs.
const fs=require('node:fs'),crypto=require('node:crypto');
const {canonicalBankRecords}=require('./normalize-bank.cjs');
const parse5=require('parse5');
const KEY='data-study-compiled-key',HTML='http://www.w3.org/1999/xhtml';
const HASH=/^[a-f0-9]{64}$/;
const SELECTORS=new Set(['.sf-example','li.example-card,li._r28','.sf-panel','.sf-report','.examples-section','.sentence-jump','.sentence-jump,[data-rb-j]','['+KEY+']','script.anki-final-reviewed-data','script.as-manifest']);
const LIMITS=Object.freeze({htmlBytes:64*1024*1024,draftBytes:32*1024*1024,nodes:1000000,bindings:100000,exactTextBytes:128*1024*1024,profileBytes:256*1024*1024});
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
function fail(message){throw Error('AST compiled profile: '+message)}
const attrName=a=>a.prefix?a.prefix+':'+a.name:a.name;
function attrs(node){if(!node?.tagName)fail('attributes need an element');return node.attrs.map(a=>[attrName(a),a.value])}
function get(node,name){return node?.attrs?.find(a=>attrName(a)===name)?.value??null}
function hasClass(node,name){if(!node?.tagName)return false;const value=get(node,'class')||'';return value.split(/[\t\n\f\r ]+/).includes(name)}
function matches(node,selector){
 if(!SELECTORS.has(selector))fail('unsupported selector '+selector);
 if(!node?.tagName)return false;
 switch(selector){
  case '.sf-example':return hasClass(node,'sf-example');
  case 'li.example-card,li._r28':return node.tagName==='li'&&(hasClass(node,'example-card')||hasClass(node,'_r28'));
  case '.sf-panel':return hasClass(node,'sf-panel');
  case '.sf-report':return hasClass(node,'sf-report');
  case '.examples-section':return hasClass(node,'examples-section');
  case '.sentence-jump':return hasClass(node,'sentence-jump');
  case '.sentence-jump,[data-rb-j]':return hasClass(node,'sentence-jump')||get(node,'data-rb-j')!==null;
  case '['+KEY+']':return get(node,KEY)!==null;
  case 'script.anki-final-reviewed-data':return node.tagName==='script'&&hasClass(node,'anki-final-reviewed-data');
  case 'script.as-manifest':return node.tagName==='script'&&hasClass(node,'as-manifest');
  default:fail('unsupported selector '+selector);
 }
}
function closest(node,selector){if(!SELECTORS.has(selector))fail('unsupported selector '+selector);for(let current=node;current;current=current.parentNode)if(matches(current,selector))return current;return null}
function firstDescendant(root,selector){if(!SELECTORS.has(selector))fail('unsupported selector '+selector);const stack=[...(root.childNodes||[])].reverse();while(stack.length){const node=stack.pop();if(matches(node,selector))return node;const children=node.childNodes||[];for(let n=children.length-1;n>=0;n--)stack.push(children[n])}return null}
function textContent(element){if(!element?.tagName)fail('textContent needs an element');const out=[],stack=[element];while(stack.length){const node=stack.pop();if(node.nodeName==='#text')out.push(node.value);else{const children=node.childNodes||[];for(let n=children.length-1;n>=0;n--)stack.push(children[n])}}return out.join('')}
function tagName(node){return node.namespaceURI===HTML?node.tagName.toUpperCase():node.tagName}
function nodePath(node,root){const result=[];while(node!==root){if(!node?.parentNode||!Number.isSafeInteger(node.__studyChildIndex)||node.parentNode.childNodes[node.__studyChildIndex]!==node)fail('detached or changed path');result.push(node.__studyChildIndex);node=node.parentNode}return result.reverse()}
function indexHTML(html,limits=LIMITS){
 if(typeof html!=='string'||Buffer.byteLength(html)>limits.htmlBytes)fail('HTML input byte limit');
 const parseErrors=[],doc=parse5.parse(html,{scriptingEnabled:false,sourceCodeLocationInfo:true,onParseError:error=>{if(parseErrors.length<16)parseErrors.push({code:error.code,startOffset:error.startOffset})}});
 if(doc.mode==='quirks')fail('requires CSS1Compat input');
 const byKey=new Map(),reports=[],examples=[],links=[],payloads=[],manifests=[],initialEvidence=[],stack=[doc];let nodes=0,elements=0;
 while(stack.length){const node=stack.pop();if(++nodes>limits.nodes)fail('AST node limit');if(node.tagName){elements++;if(node.tagName==='pre'&&(get(node,'data-native-history-media')!==null||get(node,'data-native-history-sha')!==null)){if(!/^_af_[a-f0-9]{24}\.js$/.test(get(node,'data-native-history-media')||'')||!HASH.test(get(node,'data-native-history-sha')||'')||get(node,'data-native-history-ready')!=='true'||(node.childNodes||[]).some(child=>child.nodeName!=='#text'))fail('uncovered direct native-history evidence: not ready or text-only');initialEvidence.push(node);}const id=get(node,KEY);if(id!==null){if(!id||byKey.has(id))fail('empty or duplicate producer key '+id);byKey.set(id,node)}if(hasClass(node,'sf-report'))reports.push(node);if(hasClass(node,'examples-section'))examples.push(node);if(hasClass(node,'sentence-jump'))links.push(node);if(matches(node,'script.anki-final-reviewed-data'))payloads.push(node);if(matches(node,'script.as-manifest'))manifests.push(node)}const children=node.childNodes||[];for(let n=children.length-1;n>=0;n--){children[n].__studyChildIndex=n;stack.push(children[n])}}
 return{doc,byKey,reports,examples,links,payloads,manifests,initialEvidence,diagnostics:{nodes,elements,parseErrors,templateContentsExcludedFromDOMQueries:true}};
}
function insertion(node,key,html){const loc=node.sourceCodeLocation?.startTag;if(!loc||!Number.isSafeInteger(loc.startOffset)||!Number.isSafeInteger(loc.endOffset))fail('logical root has no explicit start tag for delivery key');const raw=html.slice(loc.startOffset,loc.endOffset);if(!raw.endsWith('>'))fail('logical root start-tag boundary');return{key,startTagStart:loc.startOffset,startTagEnd:loc.endOffset,insertOffset:loc.endOffset-(raw.endsWith('/>')?2:1),insertText:' '+KEY+'="'+key+'"',startTagSha256:sha(raw)}}
function projectFields({html,draft,limits=LIMITS}){
 if(!draft||draft.schema!=='study-canonical-interaction-bindings.draft.v1'||!HASH.test(draft.source_artifact_sha256||'')||!Array.isArray(draft.nodeBindings)||draft.nodeBindings.length>limits.bindings)fail('producer draft schema/binding limit');
 for(const name of ['projectionWrappers','panels','groups','bankRecords'])if(!Array.isArray(draft[name]))fail('producer table '+name);
 const index=indexHTML(html,limits),byKey=new Map(),keyPlans=[];let ordinal=0;
 for(const binding of draft.nodeBindings){if(!binding||typeof binding.key!=='string'||byKey.has(binding.key)||!Array.isArray(binding.roles))fail('producer binding shape');if(!index.byKey.has(binding.key))fail('missing producer key '+binding.key);byKey.set(binding.key,binding)}
 function key(node){let value=get(node,KEY);if(value===null){value='anchor-'+String(++ordinal).padStart(5,'0');if(index.byKey.has(value))fail('new logical root key collision');keyPlans.push(insertion(node,value,html));node.attrs.push({name:KEY,value});index.byKey.set(value,node)}return value}
 const roots=new Map();function logicalNode(node){if(roots.has(node))return roots.get(node);const root=closest(node,'.sf-example')||closest(node,'li.example-card,li._r28')||closest(node,'.sf-panel')||node;roots.set(node,root);return root}
 for(const binding of draft.nodeBindings){const root=logicalNode(index.byKey.get(binding.key)),id=key(root);if(!byKey.has(id))byKey.set(id,{key:id,roles:['logical-root']})}
 if(keyPlans.length){const error=Error('AST compiled profile: delivery HTML needs explicit logical-root keys');error.code='NEEDS_DELIVERY_ANCHOR_KEYS';error.keyInsertions=keyPlans;throw error}
 const rootFacts=new Map(),texts=new Map(),nodeBindings=[];let exactTextBytes=0;
 function facts(root){if(rootFacts.has(root))return rootFacts.get(root);let logicalRoot;if(matches(root,'.sf-example')){const id=get(root,'data-sf-occurrence-id');if(!id)fail('occurrence owner absent');logicalRoot={kind:'occurrence',id};}else if(matches(root,'li.example-card,li._r28')){const jump=firstDescendant(root,'.sentence-jump,[data-rb-j]');if(!jump)fail('native root source identity absent');logicalRoot={kind:'native-source',id:JSON.stringify([get(jump,'data-rb-j'),get(jump,'data-latex-url'),get(jump,'data-full-paper-url')])};}else logicalRoot={kind:'panel',id:key(root)};
  const region=closest(root,'.sf-report')||closest(root,'.examples-section');if(!region)fail('uncovered semantic region');const selector=matches(region,'.sf-report')?'.sf-report':'.examples-section',regions=selector==='.sf-report'?index.reports:index.examples,result={rootKey:key(root),logicalRoot,region:{selector,ordinal:regions.indexOf(region),total:regions.length,rootPath:nodePath(root,region)}};rootFacts.set(root,result);return result;
 }
 for(const[id,binding]of byKey){const node=index.byKey.get(id),root=logicalNode(node),rootInfo=facts(root),record={key:id,region:rootInfo.region,tag:tagName(node),namespace:node.namespaceURI,roles:binding.roles,rootKey:rootInfo.rootKey,logicalRoot:rootInfo.logicalRoot,relativePath:nodePath(node,root),requiredAttrs:attrs(node)};
  if(!binding.roles.some(role=>['sense-panel','group-panel','group-status'].includes(role))){if(!texts.has(node))texts.set(node,textContent(node));record.exactText=texts.get(node);exactTextBytes+=Buffer.byteLength(record.exactText);if(exactTextBytes>limits.exactTextBytes)fail('exactText byte limit')}
  nodeBindings.push(record);
 }
 const readerLinks=[];for(const link of index.links){const root=closest(link,'.sf-example')||closest(link,'li.example-card,li._r28')||closest(link,'.sf-panel');if(!root||!byKey.has(get(root,KEY)))continue;readerLinks.push({rootKey:get(root,KEY),relativePath:nodePath(link,root),immutableAttrs:['data-rb-j','data-latex-url','data-full-paper-url','data-reader','class','target','rel','aria-label'].map(name=>[name,get(link,name)]),baseline:{href:get(link,'href'),title:get(link,'title'),disabled:get(link,'aria-disabled')}})}
 return{fields:{nodeBindings,readerLinks,projectionWrappers:draft.projectionWrappers,residual_mode:'original-listener',residualWrappers:[],panels:draft.panels,groups:draft.groups,bankRecords:canonicalBankRecords(draft.bankRecords,nodeBindings)},index,diagnostics:{...index.diagnostics,logicalRoots:rootFacts.size,bindings:nodeBindings.length,readerLinks:readerLinks.length,exactTextBytes,manifests:index.manifests.length,keyInsertions:0}};
}
function makeSlotlessProfile({html,draft,draftRaw,bindings,limits=LIMITS}){
 if(typeof draftRaw!=='string'||Buffer.byteLength(draftRaw)>limits.draftBytes||JSON.stringify(JSON.parse(draftRaw))!==JSON.stringify(draft))fail('draft bytes/object differ');
 const required=['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'];
 if(!bindings||required.some(name=>!HASH.test(bindings[name]||''))||Object.values(bindings).some(pin=>typeof pin!=='string'||!HASH.test(pin)))fail('external binding pins');
 if(bindings.derivedHTMLSha256!==sha(html)||bindings.producerInputSha256!==sha(draftRaw)||bindings.sourceArtifactSha256!==draft.source_artifact_sha256)fail('delivery/draft/source SHA differs');
 const projected=projectFields({html,draft,limits});if(projected.index.manifests.length||projected.index.initialEvidence.length)fail('slotless emitter requires explicit history capability');
 const payload=projected.index.payloads;if(payload.length!==1||get(payload[0],'data-as-sha')!==bindings.rawSideSha256||get(payload[0],'data-as-index-sha')!==bindings.rawIndexSha256)fail('raw/index payload pins differ');
 const profile={schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',bindings:{...bindings},...projected.fields},raw=JSON.stringify(profile);if(Buffer.byteLength(raw)>limits.profileBytes)fail('profile output byte limit');
 return{profile,raw,anchors:{schema:profile.schema,version:1,profileSha256:sha(raw),htmlSha256:sha(html),bindings:profile.bindings},diagnostics:projected.diagnostics};
}
function readPinnedBytes(file,pin,limit){
 if(typeof file!=='string'||!HASH.test(pin||'')||!Number.isSafeInteger(limit)||limit<0)fail('pinned input descriptor/byte limit');
 const fd=fs.openSync(file,'r');
 try{
  const stat=fs.fstatSync(fd);if(!stat.isFile()||stat.size>limit)fail('pinned input byte limit');
  const buffer=Buffer.allocUnsafe(stat.size+1);let at=0;
  while(at<buffer.length){const count=fs.readSync(fd,buffer,at,buffer.length-at,at);if(count===0)break;at+=count;}
  if(at>stat.size||at>limit)fail('pinned input grew beyond byte limit');
  const bytes=buffer.subarray(0,at);if(sha(bytes)!==pin)fail('input SHA differs');return bytes;
 }finally{fs.closeSync(fd)}
}
function readPinnedUTF8(file,pin,limit){return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(readPinnedBytes(file,pin,limit))}
module.exports={LIMITS,sha,attrs,get,hasClass,matches,closest,firstDescendant,textContent,nodePath,indexHTML,projectFields,makeSlotlessProfile,readPinnedBytes,readPinnedUTF8};

// History capabilities use the existing e56 slot protocol. These routines read
// the audited source's literal selectors and decoder data; they do not execute
// its IIFEs or grant an arbitrary lazy-content capability.
function descendants(root){const top=root.childNodes||[];for(let n=0;n<top.length;n++)top[n].__studyChildIndex=n;const out=[],stack=[...top].reverse();while(stack.length){const node=stack.pop();out.push(node);const children=node.childNodes||[];for(let n=children.length-1;n>=0;n--){children[n].__studyChildIndex=n;stack.push(children[n])}}return out}
function setAttr(node,name,value){const old=node.attrs.find(a=>attrName(a)===name);if(old)old.value=value;else node.attrs.push({name,value})}
function removeAttr(node,name){node.attrs=node.attrs.filter(a=>attrName(a)!==name)}
function classTokens(node){return [...new Set((get(node,'class')||'').split(/[\t\n\f\r ]+/).filter(Boolean))]}
function addClass(node,name){const values=classTokens(node);if(!values.includes(name))values.push(name);setAttr(node,'class',values.join(' '))}
function ancestor(node,predicate,stop=null){for(let current=node;current&&current!==stop;current=current.parentNode)if(current.tagName&&predicate(current))return current;return null}
function unionMatch(node,selector){return selector.split(',').some(part=>{if(/^\.[a-zA-Z0-9_-]+$/.test(part))return hasClass(node,part.slice(1));const match=part.match(/^\[([a-zA-Z0-9_-]+)\]$/);if(match)return get(node,match[1])!==null;fail('unsupported audited history selector')})}
function sourceLiteral(source,marker){const start=source.indexOf(marker);if(start<0||source.indexOf(marker,start+marker.length)>=0)fail('audited history selector boundary');const end=source.indexOf(';',start),raw=source.slice(start+marker.length,end);if(!/^\s*'[^'\\]*'(?:\s*\+\s*'[^'\\]*')*\s*$/.test(raw))fail('audited selector literal');return [...raw.matchAll(/'([^'\\]*)'/g)].map(x=>x[1]).join('')}
function historySource(moduleCode,module){
 const {validateModule}=require('./semantic-producer.cjs');validateModule(module);
 if(sha(moduleCode)!==module.sha256)fail('history module SHA differs');
 const prefix="window.AnkiSlimDecode=function(root){'use strict';var config=",begin=moduleCode.indexOf(prefix),end=moduleCode.indexOf(";\nroot.querySelectorAll('[class]')",begin);
 if(begin<0||end<begin||moduleCode.indexOf(prefix,begin+prefix.length)>=0)fail('audited decoder boundary');
 const config=JSON.parse(moduleCode.slice(begin+prefix.length,end)),decoderEnd=moduleCode.indexOf(';window.AnkiSlimDecode(document);',end);
 if(decoderEnd<end||!config.classes||Object.entries(config.classes).some(([name,value])=>!/^_r\d+$/.test(name)||typeof value!=='string'||!/^[a-z][a-z0-9-]*$/.test(value)))fail('audited decoder config');
 const selectors={fine_history_exclusion:sourceLiteral(moduleCode,'var historySelector = '),projection_exclusion:sourceLiteral(moduleCode,'var excluded = '),bank_histories:sourceLiteral(moduleCode,'var histories = '),bank_sf_roots:sourceLiteral(moduleCode,'var sfRoots = '),group_rows:'li.example-card,li._r28',group_panels:'.sf-sense > .sf-panel'};
 if(!moduleCode.includes("doc.querySelectorAll('li.example-card,li._r28')")||!moduleCode.includes("doc.querySelectorAll('.sf-sense > .sf-panel')"))fail('audited Group selectors');
 return{classes:config.classes,selectors,moduleSha256:module.sha256,originalModuleSha256:module.original_sha256,decoderSha256:sha(moduleCode.slice(begin,decoderEnd+1))};
}
function decodeHistory(fragment,source){
 const nodes=descendants(fragment);
 if(nodes.some(node=>node.tagName==='a'&&get(node,'data-rb-j')!==null))fail('history source-reader decoder scope unsupported');
 for(const node of nodes.filter(node=>node.tagName&&get(node,'class')!==null)){
  for(const name of classTokens(node)){
   if(!Object.hasOwn(source.classes,name)){if(source.classes[name])fail('inherited decoder class unsupported');continue;}
   const card=ancestor(node,n=>hasClass(n,'vocab-card'),fragment);if(card)addClass(card,'rb-compact-note');
   setAttr(node,'class',classTokens(node).filter(value=>value!==name).join(' '));addClass(node,source.classes[name]);
  }
 }
 for(const node of nodes.filter(node=>node.tagName==='span'&&get(node,'_c')!==null)){
  const value=get(node,'_c');if(!/^[ez]\d+(,\d+)*$/.test(value))continue;
  addClass(node,'card-chunk');setAttr(node,'data-chunk-side',value[0]==='e'?'en':'zh');setAttr(node,'data-chunk-ids',value.slice(1).replace(/,/g,' '));removeAttr(node,'_c');
 }
 return nodes;
}
function nodeGraph(node){if(node.tagName)return{type:1,name:tagName(node),namespace:node.namespaceURI,attrs:attrs(node),children:(node.childNodes||[]).map(nodeGraph)};if(node.nodeName==='#text')return{type:3,text:node.value};if(node.nodeName==='#comment')return{type:8,text:node.data};fail('unsupported history graph node')}
function exactHistoryClasses(node,wanted){const names=classTokens(node);return names.length===wanted.length&&wanted.every(name=>names.includes(name))}
function inlineHistoryOwner(owner){return owner?.namespaceURI===HTML&&owner.tagName==='details'&&exactHistoryClasses(owner,['sf-inline-history'])&&hasClass(owner.parentNode,'sf-report')&&!closest(owner,'li.example-card,li._r28')}
// Only these original archived bilingual graphs may carry example-card on a
// DIV. The separately verified consumer census must still exclude every one.
function archivedHistoryPair(node,fragment,owner){
 const archive=node.parentNode;
 if(node.namespaceURI!==HTML||node.tagName!=='div'||!exactHistoryClasses(node,['sf-sentence-pair','example-card'])||archive?.namespaceURI!==HTML||archive.tagName!=='article')return false;
 if(inlineHistoryOwner(owner))return exactHistoryClasses(archive,['sf-example','sf-archived-example'])&&archive.parentNode===fragment;
 const detail=archive.parentNode;
 return owner?.namespaceURI===HTML&&owner.tagName==='details'&&hasClass(owner,'sf-ownership-history')&&
  exactHistoryClasses(archive,['sf-example'])&&detail?.namespaceURI===HTML&&detail.tagName==='details'&&
  exactHistoryClasses(detail,['sf-inline-history'])&&get(detail,'open')===null&&detail.parentNode===fragment;
}
function forbiddenHistory(node,fragment,owner){return !!node.tagName&&(
 ['script','style','link','iframe','audio','video','source','button','input','select','textarea'].includes(node.tagName)||
 (hasClass(node,'example-card')&&!archivedHistoryPair(node,fragment,owner))||
 ['_r28','sf-panel','sf-sense','source-reader','sentence-jump','as-lazy','as-manifest'].some(name=>hasClass(node,name))||
 get(node,'data-rb-j')!==null||get(node,'data-reviewed-chunk-projection')==='residual');}
function consumerFacts(nodes,fragment,owner,source){
 const selectors=source.selectors,fact=node=>({path:nodePath(node,fragment),tag:tagName(node),class:get(node,'class')});
 // Match the real insertion context without adding any new children to owner.
 fragment.parentNode=owner;
 try{
  const excluded=(node,selector)=>!!ancestor(node,n=>unionMatch(n,selector));
  const fine=nodes.filter(node=>hasClass(node,'example-card')&&!excluded(node,selectors.fine_history_exclusion));
  const bank=nodes.filter(node=>(unionMatch(node,selectors.bank_sf_roots)||hasClass(node,'example-card'))&&!excluded(node,selectors.bank_histories));
  const panels=nodes.filter(node=>hasClass(node,'sf-panel')&&hasClass(node.parentNode,'sf-sense'));
  const physical=nodes.filter(node=>matches(node,'li.example-card,li._r28'));
  const residual=nodes.filter(node=>hasClass(node,'card-chunk')&&get(node,'data-reviewed-chunk-projection')==='residual');
  const pairs=nodes.filter(node=>hasClass(node,'sf-sentence-pair')).map(node=>{
   const isExcluded=excluded(node,selectors.projection_exclusion);
   const ownArchive=ancestor(node,n=>['sf-archived-native-example','sf-archived-example','sf-original-history-panel','sf-ownership-authority'].some(name=>hasClass(n,name)),fragment);
   if(!isExcluded||(!ownArchive&&!archivedHistoryPair(node,fragment,owner)))fail('history Projection exclusion drift');
   return{...fact(node),excluded:true};
  });
  const result={fine_example_roots:fine.map(fact),projection_pair_roots:pairs,bank_containers:bank.map(fact),group_panels:panels.map(fact),group_physical_native_rows:physical.map(fact),residual_key_targets:residual.map(fact)};
  if([fine,bank,panels,physical,residual].some(values=>values.length))fail('history has live semantic consumer');
  return result;
 }finally{delete fragment.parentNode}
}
function historyEvidence(name,pin,evidence){
 const registration=evidence[name];
 if(!/^_af_[a-f0-9]{24}\.js$/.test(name||'')||!HASH.test(pin||'')||!registration||typeof registration.raw!=='string'||sha(registration.raw)!==registration.sha256)fail('history evidence resource');
 const match=registration.raw.match(/^window\.AnkiFinalHistoryEvidence=window\.AnkiFinalHistoryEvidence\|\|\{\};window\.AnkiFinalHistoryEvidence\["([a-f0-9]{64})"\]=([\s\S]*);$/);
 if(!match||match[1]!==pin)fail('history evidence registration');
 const text=JSON.parse(match[2]);if(typeof text!=='string'||sha(text)!==pin)fail('history evidence text SHA differs');
 return{text,resourceSha256:registration.sha256};
}
function buildHistorySlots({index,sourceArtifactSha256,moduleCode,module,parts,evidence,initialProof=[],initialResources={},nodeBindings=[],limits=LIMITS}){
 if(!HASH.test(sourceArtifactSha256||'')||!parts||typeof parts!=='object'||Array.isArray(parts)||!evidence||typeof evidence!=='object'||Array.isArray(evidence))fail('history input shape');
 const source=historySource(moduleCode,module),slots=[],scopeParts=[],initial=[],usedParts=new Set(),usedEvidence=new Set();
 let bytes=0,totalParts=0;
 const initialNodes=index.initialEvidence||[];
 if(!Array.isArray(initialProof)||initialProof.length!==initialNodes.length)fail('initial history source proof census');
 const boundRoots=new Map(nodeBindings.filter(spec=>spec.key===spec.rootKey&&typeof spec.exactText==='string').map(spec=>[spec.key,spec]));
 for(const [ordinal,pre]of initialNodes.entries()){
  const media=get(pre,'data-native-history-media'),pin=get(pre,'data-native-history-sha'),value=historyEvidence(media,pin,evidence),proof=initialProof[ordinal];
  if(get(pre,'data-native-history-ready')!=='true'||(pre.childNodes||[]).some(child=>child.nodeName!=='#text')||textContent(pre)!==value.text)fail('initial history ready/text/graph differs');
  if(initialResources[media]!==value.resourceSha256||!proof||proof.ordinal!==ordinal||proof.media!==media||proof.sha256!==pin||proof.complete_text_sha256!==pin||proof.resource_sha256!==value.resourceSha256||proof.inverse_exact!==true||typeof proof.original_text!=='string'||sha(proof.original_text)!==proof.original_text_sha256||!Array.isArray(proof.original_attributes))fail('initial history source proof differs');
  const names=new Set();for(const pair of proof.original_attributes)if(!Array.isArray(pair)||pair.length!==2||typeof pair[0]!=='string'||typeof pair[1]!=='string'||names.has(pair[0]))fail('initial history original attributes');else names.add(pair[0]);
  const original={...pre,attrs:proof.original_attributes.map(([name,value])=>({name,value})),childNodes:[]};
  original.childNodes.push({nodeName:'#text',value:proof.original_text,parentNode:original});
  const prepared={...pre,attrs:pre.attrs.filter(attr=>attrName(attr)!==KEY||names.has(KEY))};
  if(sha(parse5.serializeOuter(original))!==proof.original_pre_dom_sha256||sha(parse5.serializeOuter(prepared))!==proof.prepared_pre_dom_sha256)fail('initial history DOM inverse/source proof differs');
  const root=ancestor(pre,node=>boundRoots.has(get(node,KEY)));
  if(!root)fail('initial history is outside an exact bound root');
  // Initial pre content is already complete. Existing v1 exactText/attribute
  // ownership protects it; no new runtime mutation permission is created.
  bytes+=Buffer.byteLength(value.text);if(bytes>limits.exactTextBytes)fail('initial history byte limit');
  usedEvidence.add(media);initial.push({ordinal,media,sha256:pin,resourceSha256:value.resourceSha256,textSha256:sha(value.text),textBytes:Buffer.byteLength(value.text),ready:true,textOnly:true,rootKey:get(root,KEY),relativePath:nodePath(pre,root),requiredAttrs:attrs(pre),originalPreDOMSha256:proof.original_pre_dom_sha256,preparedPreDOMSha256:proof.prepared_pre_dom_sha256,inverseExact:true});
 }
 for(const [slotIndex,manifest]of index.manifests.entries()){
  const anchor=manifest.parentNode,owner=anchor?.parentNode,row=closest(owner,'li.example-card,li._r28'),jump=row&&firstDescendant(row,'.sentence-jump');
  const inline=inlineHistoryOwner(owner),confirmation=owner?.namespaceURI===HTML&&exactHistoryClasses(owner,['sf-source-confirmation-history','sf-final-history'])&&owner.parentNode===row;
  const region=closest(owner,inline?'.sf-report':'.examples-section'),selector=inline?'.sf-report':'.examples-section',regions=inline?index.reports:index.examples;
  if(!owner||owner.tagName!=='details'||(!inline&&!hasClass(owner,'sf-ownership-history')&&!confirmation)||get(owner,'open')!==null||anchor.tagName!=='div'||!hasClass(anchor,'as-lazy')||get(anchor,'data-as-kind')!=='detail'||get(manifest,'type')!=='application/json'||!region||(!inline&&!jump))fail('unsupported history owner/manifest');
  const manifestText=textContent(manifest),declared=JSON.parse(manifestText);
  if(declared.schema!=='anki-slim-segments.v1'||!Array.isArray(declared.parts)||!declared.parts.length||!Number.isSafeInteger(declared.total)||declared.total<0)fail('history manifest shape');
  const slot={schema:'study-compiled-excluded-history-slot.v1',sourceArtifactSha256,region:{selector,ordinal:regions.indexOf(region),total:regions.length,ownerPath:nodePath(owner,region)},ownerAttrs:attrs(owner),ownerTree:nodeGraph(owner),nativeSource:jump?[get(jump,'data-rb-j'),get(jump,'data-latex-url'),get(jump,'data-full-paper-url')]:null,anchorPath:nodePath(anchor,owner),manifestPath:nodePath(manifest,owner),manifestText,parts:[]};
  let count=0;
  for(const [partIndex,part]of declared.parts.entries()){
   if(!part||!HASH.test(part.sha256||'')||part.src!=='_as_'+part.sha256.slice(0,24)+'.js'||!Number.isSafeInteger(part.count)||part.count<0||JSON.stringify(part)!==JSON.stringify({src:part.src,sha256:part.sha256,count:part.count})||++totalParts>1024)fail('history part declaration');
   const raw=parts[part.sha256];if(typeof raw!=='string'||sha(raw)!==part.sha256)fail('history part source SHA differs');
   bytes+=Buffer.byteLength(raw);if(bytes>limits.exactTextBytes)fail('history input byte limit');
   usedParts.add(part.sha256);count+=part.count;if(!Number.isSafeInteger(count))fail('history count overflow');
   const fragment=parse5.parseFragment(raw,{scriptingEnabled:false}),nodes=decodeHistory(fragment,source);
   if(nodes.some(node=>forbiddenHistory(node,fragment,owner)))fail('history part forbidden scope');
   const consumers=consumerFacts(nodes,fragment,owner,source),af=[];
   for(const pre of nodes.filter(node=>node.tagName==='pre'&&get(node,'data-native-history-media')!==null)){
    const name=get(pre,'data-native-history-media'),pin=get(pre,'data-native-history-sha'),value=historyEvidence(name,pin,evidence),text=value.text;
    bytes+=Buffer.byteLength(text);if(bytes>limits.exactTextBytes)fail('history evidence byte limit');
    usedEvidence.add(name);af.push({path:nodePath(pre,fragment),media:name,sha256:pin,text,resourceSha256:value.resourceSha256});
   }
   slot.parts.push({...part,tree:(fragment.childNodes||[]).map(nodeGraph),evidence:af,consumerSelectors:source.selectors,consumerEvidence:consumers});
   scopeParts.push({slot:slotIndex,part:partIndex,src:part.src,sha256:part.sha256,count:part.count,raw_bytes:Buffer.byteLength(raw),nodes:nodes.length,consumerEvidence:consumers,evidence:af.map(value=>({path:value.path,media:value.media,sha256:value.sha256,resourceSha256:value.resourceSha256}))});
  }
  if(count!==declared.total)fail('history manifest count');slots.push(slot);
 }
 if(Object.keys(parts).some(pin=>!usedParts.has(pin))||Object.keys(evidence).some(name=>!usedEvidence.has(name)))fail('unused history source capability');
 return{slots,scope:{schema:'study-source-closed-detail-scope-inspection.v1',native_module_sha256:source.moduleSha256,decoder_sha256:source.decoderSha256,decoder_scope:'audited classes and _c; source-reader links rejected',source_artifact_sha256:sourceArtifactSha256,exact_native_selectors:source.selectors,parts:scopeParts,initial},diagnostics:{slots:slots.length,parts:totalParts,initial:initial.length,evidence:usedEvidence.size,inputBytes:bytes}};
}
Object.assign(module.exports,{historySource,decodeHistory,nodeGraph,buildHistorySlots});
