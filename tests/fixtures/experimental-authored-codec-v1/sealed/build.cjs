'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');
const {JSDOM}=require('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/node_modules/jsdom');
const SOURCE=fs.readFileSync(__dirname+'/source-9014.js','utf8'),FIRST=fs.readFileSync(__dirname+'/first-iife.js','utf8');
const PIN='9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba',COHORT=JSON.parse(fs.readFileSync(__dirname+'/cohort.json'));
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
function config(){return JSON.parse(FIRST.slice(FIRST.indexOf('var config=')+11,FIRST.indexOf(';\ndocument.querySelectorAll')))}
function scriptLexemes(html){return [...html.matchAll(/<script\b(?:[^"'<>]|"[^"]*"|'[^']*')*>[\s\S]*?<\/script\s*>/gi)].map(m=>m[0])}
function openingTag(html){let quote=null;for(let n=0;n<html.length;n++){const c=html[n];if(quote){if(c===quote)quote=null}else if(c==='\"'||c==="'")quote=c;else if(c==='>')return html.slice(0,n+1)}throw Error('Unterminated serialized opening tag')}
function sourceCohort(doc){return [...doc.scripts].filter(n=>!n.type||['application/javascript','text/javascript'].includes(n.type)).map(n=>{const src=n.getAttribute('src');if(!src)return hash(n.textContent);const full=/_study_([a-f0-9]{64})\.js$/.exec(src);if(full)return full[1];const native=/_as_runtime_([a-f0-9]{24})\.js$/.exec(src);if(native)return COHORT.find(p=>p.startsWith(native[1]))||'unknown:'+src;return 'unknown:'+src})}
function patch(html,edits){let at=0,out=[];for(const e of edits){if(e.start<at||html.slice(e.start,e.end)!==e.before)throw Error('Nonexclusive source patch');out.push(html.slice(at,e.start),e.after);at=e.end}out.push(html.slice(at));return out.join('')}
function build(html,baseProfile,cohort=COHORT){
 if(baseProfile?.bindings?.derivedHTMLSha256!==hash(html))throw Error('Input HTML differs from external parent profile binding');
 if(hash(SOURCE)!==PIN||!SOURCE.startsWith(FIRST))throw Error('Original codec pin');
 const dom=new JSDOM(html,{runScripts:'outside-only',includeNodeLocations:true,url:'http://fixture.invalid/book/index.html'}),w=dom.window,d=w.document;
 try{
  const before=[...d.querySelectorAll('*')].map(n=>({n,parent:n.parentNode,attrs:JSON.stringify([...n.attributes].map(a=>[a.name,a.value])),children:[...n.childNodes],loc:dom.nodeLocation(n)}));
  const actualCohort=sourceCohort(d),cohortApproved=JSON.stringify(actualCohort)===JSON.stringify(COHORT)&&JSON.stringify(cohort)===JSON.stringify(COHORT);
  const scripts=[...d.scripts].map(n=>({n,html:n.outerHTML}));if(cohortApproved)w.eval(FIRST);
  if(scripts.some(v=>!d.contains(v.n)||v.n.outerHTML!==v.html))throw Error('Codec changed authored script');
  const parents=new Map(before.map(b=>[b.n,b.parent]));
  const replaced=new Set(before.filter(b=>b.children.length!==b.n.childNodes.length||b.children.some((n,i)=>n!==b.n.childNodes[i])).map(b=>b.n));
  const edits=[];
  for(const b of before){const n=b.n,l=b.loc;let covered=false;for(let p=b.parent;p;p=parents.get(p))if(replaced.has(p)){covered=true;break}if(covered)continue;if(!l?.startTag)continue;
   if(b.attrs!==JSON.stringify([...n.attributes].map(a=>[a.name,a.value]))){const after=openingTag(n.outerHTML);edits.push({start:l.startTag.startOffset,end:l.startTag.endOffset,before:html.slice(l.startTag.startOffset,l.startTag.endOffset),after,kind:'start-tag'})}
   if(b.children.length!==n.childNodes.length||b.children.some((x,i)=>x!==n.childNodes[i])){if(!l.endTag)throw Error('Unsupported codec child mutation');edits.push({start:l.startTag.endOffset,end:l.endTag.startOffset,before:html.slice(l.startTag.endOffset,l.endTag.startOffset),after:n.innerHTML,kind:'children'})}
  }
  edits.sort((a,b)=>a.start-b.start);const derived=patch(html,edits),c=config();
  const actionTokens=new Set(Object.keys(c.classes).concat(Object.getOwnPropertyNames(w.Object.prototype)));
  const residual=[...d.querySelectorAll('*')].some(n=>n.localName.includes('-')||n.hasAttribute('is')||[...n.classList].some(x=>actionTokens.has(x))||n.matches('span[_c],a[data-rb-j]'));
  if(JSON.stringify(scriptLexemes(html))!==JSON.stringify(scriptLexemes(derived)))throw Error('Raw script lexemes changed');
  const profile=JSON.parse(JSON.stringify(baseProfile));profile.bindings={...profile.bindings,derivedHTMLSha256:hash(derived)};
  profile.authoredCodec={schema:'study-compiled-authored-codec.v1',sourceSha256:PIN,firstIifeSha256:hash(FIRST),config:c,cohort:actualCohort,inputHTMLSha256:hash(html),derivedHTMLSha256:hash(derived),eligible:cohortApproved&&!residual};
  const rawProfile=JSON.stringify(profile);let shift=0;const inverse=edits.map(e=>{const start=e.start+shift;shift+=e.after.length-e.before.length;return{start,end:start+e.after.length,before:e.after,after:e.before,kind:e.kind}});
  if(patch(derived,inverse)!==html)throw Error('Source inverse differs');
  return{html:derived,profile,rawProfile,anchors:{htmlSha256:hash(derived),profileSha256:hash(rawProfile),sourceSha256:PIN,firstIifeSha256:hash(FIRST)},edits,inverse,sourceHTMLSha256:hash(html),scriptLexemes:scriptLexemes(html).map(hash)};
 }finally{w.close()}
}
module.exports={build,patch,hash,SOURCE,FIRST,PIN,COHORT,config,scriptLexemes,sourceCohort};
