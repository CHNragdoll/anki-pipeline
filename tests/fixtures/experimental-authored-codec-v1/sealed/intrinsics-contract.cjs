'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const B=require('./build.cjs'),A=require('./adapter.cjs');
const {prepared,close}=require('./contracts.cjs');
const v5={};vm.runInNewContext(fs.readFileSync(__dirname+'/compact-candidates-v5.js','utf8')+';adapt=adaptAuthoredCompactCandidates',v5);
function first(x,candidate){return x.cap.withCapture(enabled=>x.w.eval(v5.adapt(candidate&&enabled?A.adapt(B.FIRST,B.PIN):B.FIRST,B.PIN)))}
async function forEachRepro(){const original=await prepared(),candidate=await prepared();const error=Error('changed NodeList.forEach');try{
 for(const x of [original,candidate])x.w.NodeList.prototype.forEach=function(){throw error};
 assert.throws(()=>first(original,false),e=>e===error);assert.equal(original.scans(),1);assert.equal(original.cap.status(original.w.document).accepted,0);
 assert.throws(()=>first(candidate,true),e=>e===error,'candidate must retain original NodeList.forEach exception');
 assert.equal(candidate.scans(),1);assert.equal(candidate.cap.status(candidate.w.document).accepted,0);
 console.log('PASS real9014+v5 changed NodeList.forEach: sameError/scans1/accepted0');
}finally{close(original.w);close(candidate.w)}}
module.exports={forEachRepro};
if(require.main===module)forEachRepro().catch(e=>{console.error(e.stack);process.exitCode=1});
