'use strict';
// Isolated prototype. This extracts authored facts; it runs no semantic producer.
const fs=require('node:fs'),crypto=require('node:crypto');
const parse5=require('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/node_modules/parse5');
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
 const byKey=new Map(),reports=[],examples=[],links=[],payloads=[],manifests=[],stack=[doc];let nodes=0,elements=0;
 while(stack.length){const node=stack.pop();if(++nodes>limits.nodes)fail('AST node limit');if(node.tagName){elements++;const id=get(node,KEY);if(id!==null){if(!id||byKey.has(id))fail('empty or duplicate producer key '+id);byKey.set(id,node)}if(hasClass(node,'sf-report'))reports.push(node);if(hasClass(node,'examples-section'))examples.push(node);if(hasClass(node,'sentence-jump'))links.push(node);if(matches(node,'script.anki-final-reviewed-data'))payloads.push(node);if(matches(node,'script.as-manifest'))manifests.push(node)}const children=node.childNodes||[];for(let n=children.length-1;n>=0;n--){children[n].__studyChildIndex=n;stack.push(children[n])}}
 return{doc,byKey,reports,examples,links,payloads,manifests,diagnostics:{nodes,elements,parseErrors,templateContentsExcludedFromDOMQueries:true}};
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
 return{fields:{nodeBindings,readerLinks,projectionWrappers:draft.projectionWrappers,residual_mode:'original-listener',residualWrappers:[],panels:draft.panels,groups:draft.groups,bankRecords:draft.bankRecords},index,diagnostics:{...index.diagnostics,logicalRoots:rootFacts.size,bindings:nodeBindings.length,readerLinks:readerLinks.length,exactTextBytes,manifests:index.manifests.length,keyInsertions:0}};
}
function makeSlotlessProfile({html,draft,draftRaw,bindings,limits=LIMITS}){
 if(typeof draftRaw!=='string'||Buffer.byteLength(draftRaw)>limits.draftBytes||JSON.stringify(JSON.parse(draftRaw))!==JSON.stringify(draft))fail('draft bytes/object differ');
 const required=['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'];
 if(!bindings||required.some(name=>!HASH.test(bindings[name]||''))||Object.values(bindings).some(pin=>typeof pin!=='string'||!HASH.test(pin)))fail('external binding pins');
 if(bindings.derivedHTMLSha256!==sha(html)||bindings.producerInputSha256!==sha(draftRaw)||bindings.sourceArtifactSha256!==draft.source_artifact_sha256)fail('delivery/draft/source SHA differs');
 const projected=projectFields({html,draft,limits});if(projected.index.manifests.length)fail('slotless emitter rejects unknown or nonempty manifest capability');
 const payload=projected.index.payloads;if(payload.length!==1||get(payload[0],'data-as-sha')!==bindings.rawSideSha256||get(payload[0],'data-as-index-sha')!==bindings.rawIndexSha256)fail('raw/index payload pins differ');
 const profile={schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',bindings:{...bindings},...projected.fields},raw=JSON.stringify(profile);if(Buffer.byteLength(raw)>limits.profileBytes)fail('profile output byte limit');
 return{profile,raw,anchors:{schema:profile.schema,version:1,profileSha256:sha(raw),htmlSha256:sha(html),bindings:profile.bindings},diagnostics:projected.diagnostics};
}
function readPinnedUTF8(file,pin,limit){if(!HASH.test(pin||'')||fs.statSync(file).size>limit)fail('pinned input descriptor/byte limit');const bytes=fs.readFileSync(file);if(sha(bytes)!==pin)fail('input SHA differs');return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes)}
module.exports={LIMITS,sha,attrs,get,hasClass,matches,closest,firstDescendant,textContent,nodePath,indexHTML,projectFields,makeSlotlessProfile,readPinnedUTF8};
