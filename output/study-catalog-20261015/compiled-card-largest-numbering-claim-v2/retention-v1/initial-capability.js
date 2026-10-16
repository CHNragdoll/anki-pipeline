/* Private compiled capability. Caller authenticates certificate/bindings and
 * every source byte before this factory. No public receipt/row seed is used. */
function makeCompiledInitialNumbering(doc,certificate,bindings,scripts,isCurrent){
 'use strict';
 const HISTORY='.sf-inline-history,.sf-ownership-history,.sf-ownership-authority,.sf-native-ownership-history,.sf-original-history-panel,.residual-owner-history,.sf-source-confirmation-history,.sf-semantic-resolution-history,.sf-final-history,.sf-archived-example,.sf-archived-native-example,.sf-pending,[data-native-ownership-history],[data-reviewed-source-comparison]';
 const NAME='__studyCompiledInitialNumberingCapture',attrs=node=>JSON.stringify(Array.from(node.attributes,a=>[a.name,a.value]));
 let ownedDoc=doc,list=null,rows=[],initial=[],styles=[],ancestors=[],afterAncestors=[],captured=false,consumed=false,dead=false;
 const resultStatus={schema:'study-compiled-initial-numbering-status.v1',qualified:false,readerCaptured:false,attempted:false,accepted:false,rows:certificate?.rows||0,reason:'not-consumed'};
 const owns=()=>{try{return !dead&&ownedDoc===doc&&doc.defaultView&&isCurrent()===true}catch(_){return false}};
 function ancestry(){const out=[];for(let n=list;n&&n.nodeType===1;n=n.parentElement)out.push({node:n,parent:n.parentNode,attrs:attrs(n)});return out}
 function sameRows(){if(!list||!doc.contains(list)||list.closest(HISTORY))return false;const current=Array.from(list.children);if(current.length!==rows.length)return false;for(let i=0;i<rows.length;i++){const s=rows[i],row=current[i],badge=row.querySelector('.index-tag');if(row!==s.row||attrs(row)!==s.attrs||row.hidden||row.hasAttribute('style')||row.closest(HISTORY)||badge!==s.badge||badge.closest('li.example-card')!==row||badge.closest(HISTORY)||attrs(badge)!==s.badgeAttrs||badge.childNodes.length!==1||badge.firstChild!==s.textNode||badge.firstChild.nodeType!==3||badge.textContent!==String(i+1))return false}return true}
 function sameAncestors(){const current=ancestry();return current.length===afterAncestors.length&&current.every((s,i)=>s.node===afterAncestors[i].node&&s.parent===afterAncestors[i].parent&&s.attrs===afterAncestors[i].attrs)}
 function clear(){rows=[];initial=[];styles=[];ancestors=[];afterAncestors=[];list=null}
 function disable(){resultStatus.qualified=false;resultStatus.reason='reader-capture-mismatch';consumed=true;captured=false;clear()}
 function stop(){dead=true;clear();ownedDoc=null}
 try{
  if(!owns()||!certificate?.bindings||Object.keys(certificate.bindings).length!==7||Object.values(certificate.bindings).some(value=>typeof value!=='string'||!/^[a-f0-9]{64}$/.test(value))||certificate?.schema!=='study-compiled-initial-numbering.v1'||certificate.countdownHost!=='body'||!Number.isSafeInteger(certificate.rows)||certificate.rows<1||certificate.rows>8192||JSON.stringify(scripts.map(s=>s.pin))!==JSON.stringify(certificate.cohort)||Object.entries(certificate.bindings||{}).some(([key,value])=>bindings[key]!==value))return null;
  const lists=Array.from(doc.querySelectorAll('ol.examples'));if(lists.length!==1||lists[0].closest(HISTORY)||!lists[0].parentElement?.matches('.examples-section'))return null;list=lists[0];
  const children=Array.from(list.children);if(children.length!==certificate.rows)return null;
  for(let i=0;i<children.length;i++){const row=children[i],badge=row.querySelector('.index-tag');if(row.tagName!=='LI'||row.namespaceURI!=='http://www.w3.org/1999/xhtml'||row.getAttribute('class')!=='example-card'||row.hasAttribute('is')||row.hidden||row.hasAttribute('style')||row.closest(HISTORY)||!badge||badge.closest('li.example-card')!==row||badge.closest(HISTORY)||badge.childNodes.length!==1||badge.firstChild.nodeType!==3||badge.textContent!==String(i+1))return null;rows.push({row,attrs:attrs(row),badge,badgeAttrs:attrs(badge),textNode:badge.firstChild})}
  ancestors=ancestry();const approved=certificate.approvedCss.slice();
  for(const sheet of Array.from(doc.styleSheets)){const node=sheet.ownerNode,index=approved.findIndex(text=>text===node?.textContent);if(index<0||node.tagName!=='STYLE'||!doc.contains(node))return null;initial.push({node,rawCss:approved[index],attrs:Array.from(node.attributes,a=>[a.name,a.value])});approved.splice(index,1)}
  if(approved.length||initial.length!==certificate.approvedCss.length)return null;
 }catch(_){return null}
 resultStatus.qualified=true;
 function after(pin){
  if(captured||consumed||!owns()||pin!==certificate.readerPin)return;
  try{
   if(!sameRows())return disable();const current=ancestry(),oldSet=new Set(ancestors.map(s=>s.node)),old=current.filter(s=>oldSet.has(s.node)),added=current.filter(s=>!oldSet.has(s.node));
   if(old.length!==ancestors.length||old.some((s,i)=>s.node!==ancestors[i].node)||added.length!==1)return disable();
   const wrapper=added[0].node;if(wrapper.tagName!=='DIV'||wrapper.parentNode!==doc.body||attrs(wrapper)!==JSON.stringify([['class','anki-countdown-content']]))return disable();
   for(let i=0;i<old.length;i++){const before=ancestors[i],node=old[i].node;if(before.attrs===attrs(node))continue;const original=JSON.parse(before.attrs),next=Array.from(node.attributes,a=>[a.name,a.value]),oldClass=original.find(a=>a[0]==='class');if(!oldClass||!oldClass[1].split(/\s+/).includes('vocab-card'))return disable();const wanted=original.map(a=>a[0]==='class'?[a[0],a[1].split(/\s+/).includes('rb-compact-note')?a[1]:a[1]+' rb-compact-note']:a);if(JSON.stringify(wanted)!==JSON.stringify(next))return disable()}
   const sheets=Array.from(doc.styleSheets),known=new Map(initial.map(s=>[s.node,s])),extra=sheets.filter(s=>!known.has(s.ownerNode));if(extra.length!==1)return disable();const node=extra[0].ownerNode;if(node.tagName!=='STYLE'||node.id!==certificate.countdownStyleId||node.parentNode!==doc.head||doc.getElementById(node.id)!==node||node.textContent!==certificate.countdownCss||attrs(node)!==JSON.stringify([['id',certificate.countdownStyleId]]))return disable();
   const dynamic={node,rawCss:certificate.countdownCss,attrs:[['id',certificate.countdownStyleId]]},expected=initial.filter(s=>doc.head.contains(s.node)).concat(dynamic,initial.filter(s=>!doc.head.contains(s.node)));
   if(sheets.length!==expected.length||sheets.some((s,i)=>s.ownerNode!==expected[i].node))return disable();styles=expected;afterAncestors=current;captured=true;resultStatus.readerCaptured=true;
  }catch(_){disable()}
 }
 function claim(root){if(consumed)return false;consumed=true;resultStatus.attempted=true;try{resultStatus.accepted=root===ownedDoc&&owns()&&captured&&sameRows()&&sameAncestors()&&compiledNumberingCSSMatches(doc,styles,owns)===true;resultStatus.reason=resultStatus.accepted?'accepted':'claim-mismatch';return resultStatus.accepted}catch(_){resultStatus.reason='claim-mismatch';return false}finally{rows=[];initial=[];styles=[];ancestors=[];afterAncestors=[]}}
 function run(action){if(!owns())return false;if(!captured||consumed)return action(false);const win=doc.defaultView;try{if(NAME in win)return action(false)}catch(_){return action(false)}const capture=()=>claim;let installed=false;try{try{Object.defineProperty(win,NAME,{configurable:true,writable:false,value:capture});installed=true}catch(_){return action(false)}return action(true)}finally{if(installed){try{const property=Object.getOwnPropertyDescriptor(win,NAME);if(property?.value===capture)delete win[NAME]}catch(_){}}}}
 return Object.freeze({after,run,dispose:stop,status(){return Object.freeze({...resultStatus})}});
}
