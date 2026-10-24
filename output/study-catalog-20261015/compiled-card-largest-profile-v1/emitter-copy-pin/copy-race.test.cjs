"use strict";
const fs=require("node:fs"),path=require("node:path"),assert=require("node:assert/strict"),{test}=require("node:test"),{assemble}=require("./assemble-profile.cjs"),{sha}=require("/tmp/study-parse5-compiled-profile-20261017-jfnwtv1v/ast-profile.cjs");
const reference=JSON.parse(fs.readFileSync("/tmp/study-compiled-card-binder-v2-20261017-gjmnnl5m/replay/abolish/profile.json","utf8"));
test("actual input replacement after preflight hash is rejected before anchors/report publication",async()=>{
 const dir=fs.mkdtempSync("/tmp/study-copy-pin-race-"),fieldsFile=path.join(dir,"fields.json"),output=path.join(dir,"output"),keys=["nodeBindings","readerLinks","projectionWrappers","residual_mode","residualWrappers","panels","groups","bankRecords"],raw=JSON.stringify(Object.fromEntries(keys.map(k=>[k,reference[k]]))),mutated=raw.replace('"original-listener"','"tampered-listener"'),fieldsSha256=sha(raw),bindings=reference.bindings;
 assert.notEqual(mutated,raw);assert.equal(Buffer.byteLength(raw),Buffer.byteLength(mutated));fs.writeFileSync(fieldsFile,raw);
 const extraction={status:"FIELDS_EXTRACTED_NOT_PROFILE",fields:{bytes:Buffer.byteLength(raw),sha256:fieldsSha256},inputs:{html:{sha256:bindings.derivedHTMLSha256},draft:{sha256:bindings.producerInputSha256}},draftSourceArtifactSha256:bindings.sourceArtifactSha256,payloads:[{rawSideSha256:bindings.rawSideSha256,rawIndexSha256:bindings.rawIndexSha256}],diagnostics:{manifests:0,exactTextBytes:1981},tables:{}};
 const original=fs.createReadStream;let injected=0;
 fs.createReadStream=function(file,options){if(file===fieldsFile&&options?.start===1){injected++;fs.writeFileSync(fieldsFile,mutated)}return Reflect.apply(original,this,arguments)};
 try{await assert.rejects(assemble({fieldsFile,fieldsSha256,bindings,extraction},output),/Copied fields SHA differs/);assert.equal(injected,1);assert.equal(fs.existsSync(path.join(output,"anchors.json")),false);assert.equal(fs.existsSync(path.join(output,"report.json")),false);assert.equal(fs.readFileSync(fieldsFile,"utf8"),mutated);}finally{fs.createReadStream=original;fs.rmSync(dir,{recursive:true,force:true})}
});
