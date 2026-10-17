'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const data=require('./data.cjs'),B=require('./build.cjs'),codec=require('./codec-adapter.cjs'),{buildSmall}=require('./generate.cjs'),{adapt}=require('./frame.cjs');
function undo(value,edits){for(const[a,b]of edits.slice().reverse()){assert.equal(value.split(b).length,2);value=value.replace(b,()=>a)}return value}
const small=buildSmall(),baseline=data.raw('baseline-candidate-frame.js'),frame=adapt(baseline,small.assets);
assert.equal(undo(frame.output,frame.edits),baseline);
assert.equal(data.raw('candidate-frame.js'),frame.output);assert.equal(data.raw('candidate-frame.html'),data.raw('baseline-candidate-frame.html').replace(baseline,()=>frame.output));assert.equal(data.raw('candidate-profile.json'),small.rawProfile);assert.equal(data.raw('candidate-body.html'),small.built.html);assert.deepEqual(JSON.parse(fs.readFileSync(__dirname+'/frame-edits.json')),frame.edits);
assert.equal(undo(fs.readFileSync(__dirname+'/capability.js','utf8'),JSON.parse(fs.readFileSync(__dirname+'/capability-edits.json'))),fs.readFileSync(__dirname+'/../experimental-authored-codec-v1/sealed/capability.cjs','utf8'));
assert.equal(undo(fs.readFileSync(__dirname+'/project.cjs','utf8'),JSON.parse(fs.readFileSync(__dirname+'/project-edits.json'))),data.raw('project-source.cjs'));
assert.equal(B.patch(small.built.html,small.built.inverse),data.raw('export-replay-input-derived.html'));
assert.equal(codec.inverse(codec.adapt(B.SOURCE,B.PIN)),B.SOURCE);
const tail=B.SOURCE.slice(B.FIRST.length);assert.equal(B.hash(tail),'59185820030764bb5dd171f3796dda4ecc02f092de14da87bdae60d2a6a39335');
assert.ok(codec.adapt(B.SOURCE,B.PIN).endsWith(tail));
function scripts(raw){const d=new JSDOM(raw,{includeNodeLocations:true});try{return Array.from(d.window.document.scripts,n=>{const loc=d.nodeLocation(n);return raw.slice(loc.startOffset,loc.endOffset)})}finally{d.window.close()}}
assert.deepEqual(scripts(small.built.html),scripts(small.input.artifact.sides[1].html));
assert.equal(scripts(small.built.html).length,15);
const capture=JSON.parse(data.raw('capture-parity.json'));assert.equal(capture.capture_vs_uninstrumented_panel_dom_exact,true);assert.equal(capture.capture_vs_uninstrumented_stats_exact,true);
const exportProof=JSON.parse(data.raw('export-report.json'));for(const field of ['region_inverse_exact','source_script_bytes_and_order_exact','original_payload_and_manifest_markup_exact','source_iframe_attributes_srcdoc_sandbox_exact'])assert.equal(exportProof[field],true);
const caps=frame.edits.map(([before,after],index)=>({index,before_sha256:B.hash(before),after_sha256:B.hash(after),before_bytes:Buffer.byteLength(before),after_bytes:Buffer.byteLength(after)}));
console.log(JSON.stringify({schema:'study-authored-codec-frame-inverse.v1',baselineFrameSha256:B.hash(baseline),candidateFrameSha256:B.hash(frame.output),candidateFrameBytes:Buffer.byteLength(frame.output),frameEdits:frame.edits.length,frameInverseExact:true,capabilityInverseExact:true,projectInverseExact:true,authoredGuardInverseExact:true,remainingFourIIFEsSha256:B.hash(tail),originalScriptLexemesAndOrder:15,htmlSha256:B.hash(small.built.html),profileSha256:B.hash(small.rawProfile),profileBindings:small.profile.nodeBindings.length,noNewProfileParseHashFreeze:true,sourceWrapperSha256:small.input.artifact.source_wrapper_sha256,sourcePayloadSha256:small.input.artifact.source_payload_sha256,sourceArtifactSha256:small.input.artifact_sha256,editPins:caps}));
