'use strict';
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const data=require('./data.cjs'),B=require('./build.cjs'),{project}=require('./project.cjs');
function buildSmall(){
 const input=JSON.parse(data.raw('input.json')),resources=new Map(Object.entries(input.policy.external).map(([src,pin])=>[src,data.byPin(pin)]));
 const html=data.raw('export-replay-input-derived.html'),built=B.build(html,{bindings:{derivedHTMLSha256:B.hash(html)}},B.COHORT,input.policy,resources);
 const stage=fs.mkdtempSync(path.join(os.tmpdir(),'study-codec-frame-profile-'));
 try{
  const capture=path.join(stage,'capture');fs.mkdirSync(capture);
  fs.writeFileSync(path.join(stage,'input.json'),JSON.stringify(input));
  fs.writeFileSync(path.join(stage,'native-adapters.js'),data.raw('native-adapters.js'));
  fs.writeFileSync(path.join(capture,'runtime-bindings-minimal-draft.json'),data.raw('capture-runtime-bindings-minimal-draft.json'));
  const body=path.join(stage,'body.html');fs.writeFileSync(body,built.html);
  project('real2026',capture,body,path.join(stage,'output'));
  const profile=JSON.parse(fs.readFileSync(path.join(stage,'output/profile.json')));
  profile.authoredCodec=built.profile.authoredCodec;
  assert.equal(profile.bindings.derivedHTMLSha256,B.hash(built.html));
  // Projecting the final post-codec DOM is read-only; all bindings must already
  // be supplied by the original canonical producer/export ledger.
  assert.equal(fs.readFileSync(path.join(stage,'output/final.html'),'utf8'),built.html);
  const rawProfile=JSON.stringify(profile);
  const module=Object.values(input.artifact.modules)[0],original=Object.keys(input.artifact.modules)[0],side=input.artifact.sides[1];
  const runtime=data.raw('compiled-input-runtime.js');
  const assets={runtime:{src:'_qa_compiled_runtime_small.js',sha256:B.hash(runtime)},entries:{[input.card_id]:{decoded:true,html:{src:'_qa_compiled_body_small.html',sha256:B.hash(built.html)},profile:{src:'_qa_compiled_profile_small.json',sha256:B.hash(rawProfile)},anchors:{schema:profile.schema,version:1,bindings:profile.bindings},source:{wrapper_sha256:input.artifact.source_wrapper_sha256,payload_sha256:input.artifact.source_payload_sha256,side_sha256:side.proof.source_sha256,expanded_sha256:side.proof.expanded_sha256,registry_pins:side.proof.registry_pins},module:{original_sha256:original,sha256:module.sha256}}}};
  return{input,built,profile,rawProfile,runtime,assets,resources};
 }finally{fs.rmSync(stage,{recursive:true,force:true})}
}
module.exports={buildSmall};
if(require.main===module){const x=buildSmall();console.log(JSON.stringify({eligible:x.profile.authoredCodec.eligible,html:B.hash(x.built.html),profile:B.hash(x.rawProfile),edits:x.built.edits.length,bindings:x.profile.nodeBindings.length,cohort:x.profile.authoredCodec.cohort}));}
