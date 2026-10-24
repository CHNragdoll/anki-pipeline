function createCompiledCodecCapability(scope,matches,approved){
 approved=JSON.parse(JSON.stringify(approved));
 const records=new WeakMap(),name='__studyCompiledCodecCapture',schema='study-compiled-authored-codec.v1';
 const O=scope.Object,F=scope.Function,A=scope.Array,E=scope.Element,N=scope.Node,D=scope.Document;
 const refs=[[O,'getOwnPropertyDescriptor'],[O,'getOwnPropertyNames'],[O,'getPrototypeOf'],[F.prototype,'toString'],[E.prototype,'getAttribute'],[E.prototype,'hasAttribute'],[E.prototype,'querySelectorAll'],[D.prototype,'querySelectorAll'],[N.prototype,'appendChild'],[scope.NodeList.prototype,'forEach']].map(([root,key])=>[root,key,O.getOwnPropertyDescriptor(root,key)]);
 const stockNames=['constructor','__defineGetter__','__defineSetter__','hasOwnProperty','__lookupGetter__','__lookupSetter__','isPrototypeOf','propertyIsEnumerable','toString','valueOf','__proto__','toLocaleString'].sort();
 const native=(value,name)=>typeof value==='function'&&(/^function .+\(\) \{\s*\[native code\]\s*\}$/.test(F.prototype.toString.call(value)))&&F.prototype.toString.call(value).includes(name);
 function environment(){try{
  if(refs.some(([root,key,was])=>{const now=O.getOwnPropertyDescriptor(root,key);return !now||now.value!==was.value||now.get!==was.get||now.set!==was.set}))return false;
  if(JSON.stringify(O.getOwnPropertyNames(O.prototype).sort())!==JSON.stringify(stockNames)||O.getOwnPropertySymbols(O.prototype).length)return false;
  for(const key of stockNames){const d=O.getOwnPropertyDescriptor(O.prototype,key);if(key==='__proto__'){if(!native(d.get,'get __proto__')||!native(d.set,'set __proto__'))return false}else if(!native(d.value,key==='constructor'?'Object':key))return false}
  return true;
 }catch(_){return false}}
 function deepFreeze(x){if(x&&typeof x==='object'){O.values(x).forEach(deepFreeze);O.freeze(x)}return x}
 function attrs(n){return JSON.stringify([...n.attributes].map(a=>[a.name,a.value]))}
 let executionCode=null;
 function observe(doc,r){r.observer=new scope.MutationObserver(changes=>{try{if(!alive(r)||!processChanges(r,changes))retire(r)}catch(_){retire(r)}});r.observer.observe(doc,{subtree:true,childList:true,attributes:true,attributeFilter:['class','_c','data-rb-j','is']})}
 function processChanges(r,changes){
  for(const c of changes){
   if(c.type!=='childList'||c.target!==r.head)return false;
   for(const n of c.addedNodes){if(n!==r.doc.currentScript||n.nodeName!=='SCRIPT'||typeof executionCode!=='string'||n.textContent!==executionCode)return false;r.executionScripts.add(n)}
   for(const n of c.removedNodes)if(!r.executionScripts.has(n))return false;
  }
  return true;
 }
 function retire(r,failed=true){if(!r)return;r.bad=failed;r.observer?.disconnect();r.observer=null;r.valid=null;r.doc=null;r.root=null;r.head=null;r.body=null;r.parsed=null;r.topHead=null;r.topBody=null}
 function alive(r){if(!r||typeof r.valid!=='function')return false;try{if(r.valid()===true&&environment())return true}catch(_){}retire(r);return false}
 function check(doc,config,pin){const r=records.get(doc);if(!r||!r.attached||r.bad||!alive(r)||pin!==approved.sourceSha256)return false;
  if(doc!==scope.document||r.doc!==doc||doc.documentElement!==r.root||doc.body!==r.body||doc.head!==r.head||JSON.stringify(config)!==r.configJSON){retire(r);return false}
  try{if(!processChanges(r,r.observer.takeRecords())){retire(r);return false}}catch(_){retire(r);return false}r.accepted++;retire(r,false);return true;
 }
 async function load(html,profileText,expected,valid,cohort){
  if(typeof html!=='string'||typeof profileText!=='string'||typeof matches!=='function'||typeof valid!=='function')throw TypeError('Compiled codec input');
  const pins={htmlSha256:expected?.htmlSha256,profileSha256:expected?.profileSha256,sourceSha256:expected?.sourceSha256,firstIifeSha256:expected?.firstIifeSha256};
  if(O.values(pins).some(x=>typeof x!=='string'||!/^[a-f0-9]{64}$/.test(x))||pins.sourceSha256!==approved.sourceSha256||pins.firstIifeSha256!==approved.firstIifeSha256)throw Error('Compiled codec external anchors');
  const scripts=JSON.stringify(cohort);if(valid()!==true)return null;
  if(!(await Promise.all([[html,pins.htmlSha256],[profileText,pins.profileSha256]].map(([raw,pin])=>matches(raw,pin)))).every(x=>x===true))throw Error('Compiled codec artifact SHA');
  if(valid()!==true)return null;
  const p=JSON.parse(profileText),c=p.authoredCodec;
  if(p.bindings?.derivedHTMLSha256!==pins.htmlSha256)throw Error('Compiled codec producer binding');
  const compatible=!!c&&c.schema===schema&&c.sourceSha256===pins.sourceSha256&&c.firstIifeSha256===pins.firstIifeSha256&&c.derivedHTMLSha256===pins.htmlSha256;
  const qualified=compatible&&c.eligible===true&&JSON.stringify(c.cohort)===JSON.stringify(approved.cohort)&&scripts===JSON.stringify(approved.cohort)&&JSON.stringify(c.config)===approved.configJSON&&environment();
  const parsed=new scope.DOMParser().parseFromString(html,'text/html');
  const r={qualified,bad:false,accepted:0,valid,doc:null,root:null,head:null,body:null,observer:null,configJSON:approved.configJSON,executionScripts:new WeakSet(),topHead:[...parsed.head.childNodes],topBody:[...parsed.body.childNodes],htmlAttrs:attrs(parsed.documentElement),bodyAttrs:attrs(parsed.body),parsed};
  records.set(parsed,r);return Object.freeze({document:parsed,profile:deepFreeze(p)});
 }
 function attach(parsed,transfer){const r=records.get(parsed);if(!r||!alive(r))return false;
  // Observe before the synchronous caller-owned adoption. The only allowed
  // records here are removal of the already-captured original top-level nodes.
  observe(parsed,r);let doc;try{doc=transfer(parsed);if(doc&&typeof doc.then==='function')throw Error('Compiled codec adoption must be synchronous');const expected=new Set(r.topHead.concat(r.topBody));for(const c of r.observer.takeRecords())if(c.type!=='childList'||c.addedNodes.length||[...c.removedNodes].some(n=>!expected.has(n)))r.bad=true;
   if(doc!==scope.document||JSON.stringify([...doc.head.childNodes].map((n,i)=>n===r.topHead[i]))!==JSON.stringify(r.topHead.map(()=>true))||doc.head.childNodes.length!==r.topHead.length||doc.body.childNodes.length!==r.topBody.length||[...doc.body.childNodes].some((n,i)=>n!==r.topBody[i])||attrs(doc.documentElement)!==r.htmlAttrs||attrs(doc.body)!==r.bodyAttrs)r.bad=true;
  }catch(error){r.observer.disconnect();r.valid=null;records.delete(parsed);throw error}
  r.observer.disconnect();records.delete(parsed);r.parsed=null;r.topHead=null;r.topBody=null;r.htmlAttrs=null;r.bodyAttrs=null;r.doc=doc;r.root=doc.documentElement;r.head=doc.head;r.body=doc.body;r.attached=true;r.bad=r.bad||!r.qualified;records.set(doc,r);if(r.bad){retire(r);return false}observe(doc,r);return true;
 }
 function withCapture(code,action){if(typeof code==='function'){action=code;code=null}let conflict;try{conflict=name in scope}catch(_){return action(false)}if(conflict)return action(false);let installed=false;const capture=()=>check,previous=executionCode;executionCode=typeof code==='string'?code:null;try{try{O.defineProperty(scope,name,{configurable:true,writable:false,value:capture});installed=true}catch(_){return action(false)}return action(true)}finally{executionCode=previous;if(installed)try{if(O.getOwnPropertyDescriptor(scope,name)?.value===capture)delete scope[name]}catch(_){}}}
 function dispose(doc){const r=records.get(doc);if(!r)return;r.observer?.disconnect();r.valid=null;r.doc=null;r.root=null;r.head=null;r.body=null;r.parsed=null;r.executionScripts=null;records.delete(doc)}
 return O.freeze({load,attach,withCapture,dispose,status(doc){const r=records.get(doc);return O.freeze({qualified:!!r?.qualified,accepted:r?.accepted||0,current:alive(r),bad:!!r?.bad})}});
}
