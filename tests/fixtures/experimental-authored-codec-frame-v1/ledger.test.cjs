'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm'),{JSDOM}=require('jsdom');
const data=require('./data.cjs'),B=require('./build.cjs'),{sourceCohort}=require('./ledger.cjs');
const original=fs.readFileSync(__dirname+'/../experimental-authored-codec-v1/sealed/build.cjs','utf8');
function oldCohort(doc){const fn=original.slice(original.indexOf('function sourceCohort('),original.indexOf('\nfunction patch('));return vm.runInNewContext('('+fn+')',{hash:B.hash,COHORT:B.COHORT})(doc)}
const input=JSON.parse(data.raw('input.json')),html=data.raw('export-replay-input-derived.html'),policy=input.policy,resources=new Map(Object.entries(policy.external).map(([src,pin])=>[src,data.byPin(pin)]));
function withDoc(text,action){const d=new JSDOM(text);try{return action(d.window.document)}finally{d.window.close()}}
function build(text,p=policy,r=resources,declared=B.COHORT){return B.build(text,{bindings:{derivedHTMLSha256:B.hash(text)}},declared,p,r)}
if(process.argv.includes('--red')){withDoc(html,d=>assert.deepEqual(Array.from(oldCohort(d)),B.COHORT,'filename-only eligibility rejected the real approved numbering resource'));process.exit(0)}
assert.deepEqual(withDoc(html,d=>sourceCohort(d,policy,resources)),B.COHORT);
// Different spelling, same verified byte identity is valid; no filename parsing.
const from=Object.keys(policy.external).find(s=>s.startsWith('_as_numbering_')),renamed='verified-numbering-resource.js',renamedHTML=html.split(from).join(renamed),renamedPolicy=structuredClone(policy),renamedResources=new Map(resources);renamedPolicy.external[renamed]=renamedPolicy.external[from];delete renamedPolicy.external[from];renamedResources.set(renamed,renamedResources.get(from));renamedResources.delete(from);
assert.equal(build(renamedHTML,renamedPolicy,renamedResources).profile.authoredCodec.eligible,true);
let checked=0;
const reject=(text,p=policy,r=resources,declared=B.COHORT)=>{const out=build(text,p,r,declared);assert.equal(out.profile.authoredCodec.eligible,false);assert.equal(out.html,text,'unqualified generation must preserve original byte string');assert.deepEqual(out.edits,[]);checked++};
const wrongResource=new Map(resources);wrongResource.set(from,resources.get(from)+' ');reject(html,policy,wrongResource);
const wrongResourcePolicy=structuredClone(policy);wrongResourcePolicy.external[from]='0'.repeat(64);reject(html,wrongResourcePolicy);
const inlineBad=structuredClone(policy);inlineBad.inline[0].sha256='0'.repeat(64);reject(html,inlineBad);
const inlineSourceBad=structuredClone(policy);inlineSourceBad.inline[0].source+=' ';reject(html,inlineSourceBad);
const scripts=B.scriptLexemes(html),first=scripts.find(s=>s.includes(B.PIN));assert.ok(first);reject(html.replace(first,''));reject(html.replace(first,()=>first+first));
const second=scripts.find(s=>s.includes('171b1a'));reject(html.replace(first,'<!--slot-->').replace(second,()=>first).replace('<!--slot-->',()=>second));
reject(html,policy,resources,[B.PIN]);
// Eligibility is checked BEFORE FIRST executes: extra executable observers must
// see exactly the unchanged original source rather than prematurely decoded DOM.
const observer='<script>window.observedCodecMarker=!!document.querySelector("._r11")</script>',marked=html.slice(0,html.lastIndexOf('</body>'))+'<p class="_r11">test</p>'+observer+html.slice(html.lastIndexOf('</body>'));reject(marked);
assert.equal(build(html).profile.authoredCodec.eligible,true);
const edits=JSON.parse(fs.readFileSync(__dirname+'/build-edits.json'));let inverse=fs.readFileSync(__dirname+'/build.cjs','utf8');for(const [a,b]of edits.slice().reverse()){assert.equal(inverse.split(b).length,2);inverse=inverse.replace(b,()=>a)}assert.equal(inverse,original);
console.log(JSON.stringify({schema:'study-authored-codec-resource-ledger-contract.v1',approvedRealCohort:true,filenameIndependentIdentity:true,rejectedUnchangedCases:checked,oldBuilderInverseExact:true}));
