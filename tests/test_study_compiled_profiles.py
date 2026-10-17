"""Bounded shared-profile AST/emitter contracts; no real producer or browser."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


FIXTURE_JS = r"""
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),zlib=require('node:zlib');
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
const emitter=require('./anki_pipeline/compiled/profile-emitter.cjs');
function fixture(directory,withHistory=false,directAttributes='',initialMode=null){
 const base=path.join(directory,'source');fs.mkdirSync(base);const producer=path.join(base,'producer');fs.mkdirSync(producer);
 function save(name,value){const raw=typeof value==='string'?value:JSON.stringify(value),file=path.join(base,name);fs.writeFileSync(file,raw,{flag:'wx'});return{path:file,sha256:sha(raw)}}
 const module={original_sha256:'5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',sha256:'7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4'};
 if(withHistory||initialMode){const raw=zlib.gunzipSync(fs.readFileSync('tests/fixtures/experimental-authored-codec-frame-v1/resource-00.gz'));if(sha(raw)!==module.sha256)throw Error('Existing module fixture pin differs');module.path=path.join(base,'module.js');fs.writeFileSync(module.path,raw)}
 const parts={},evidence={};let disclosure='';
 if(withHistory)for(let n=0;n<2;n++){
  const text='完整审核😀\\n'+n,pin=sha(text),name='_af_'+pin.slice(0,24)+'.js';
  const registration='window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};window.AnkiFinalHistoryEvidence['+JSON.stringify(pin)+']='+JSON.stringify(text)+';';
  evidence[name]=save('evidence'+n+'.js',registration);
  const raw='<!--history--><div class="sf-archived-native-example"><div class="sf-sentence-pair"><p class="sf-en">old '+n+'<span class="_r32 keep" _c="e0">word</span></p><p class="sf-zh">旧<span _c="z0">译</span></p></div><pre data-native-history-media="'+name+'" data-native-history-sha="'+pin+'">placeholder</pre></div>';
  const part={src:'_as_'+sha(raw).slice(0,24)+'.js',sha256:sha(raw),count:1};parts[part.sha256]=save('part'+n+'.html',raw);
  const manifest=JSON.stringify({schema:'anki-slim-segments.v1',parts:[part],total:1});
  disclosure+='<details class="sf-ownership-history" data-owner="'+n+'"><summary>old</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json">'+manifest+'</script></div></details>';
 }
 const sideRaw='{}',indexRaw='[]',sidePin=sha(sideRaw),indexPin=sha(indexRaw);
 let direct=directAttributes?'<details class="sf-ownership-history"><summary>direct</summary><pre '+directAttributes+'>original pending evidence</pre></details>':'';
 const initialProof=[],initialResources={};let sourceDirect=direct;
 if(initialMode){
  let name=Object.keys(evidence)[0];
  if(!name){const text='初始完整审核😀',pin=sha(text);name='_af_'+pin.slice(0,24)+'.js';evidence[name]=save('initial-evidence.js','window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};window.AnkiFinalHistoryEvidence['+JSON.stringify(pin)+']='+JSON.stringify(text)+';')}
  const registration=fs.readFileSync(evidence[name].path,'utf8'),match=registration.match(/\["([a-f0-9]{64})"\]=([\s\S]*);$/),pin=match[1],text=JSON.parse(match[2]);
  const attrs=[['data-native-history-media',name],['data-native-history-sha',pin]],attributes=attrs.map(([n,v])=>n+'="'+v+'"').join(' ');
  const before='<pre '+attributes+'>original pending evidence</pre>',body=initialMode==='wrong-text'?'wrong complete text':initialMode==='graph'?'<span>'+text+'</span>':text;
  const prepared='<pre '+attributes+' data-native-history-ready="true">'+body+'</pre>';
  sourceDirect='<details class="sf-ownership-history"><summary>direct</summary>'+before+'</details>';
  direct='<details class="sf-ownership-history"><summary>direct</summary>'+prepared+'</details>';
  initialResources['https://example.test/book/media/'+name]=evidence[name];
  initialProof.push({ordinal:0,media:name,sha256:pin,resource_sha256:evidence[name].sha256,original_text:'original pending evidence',original_attributes:attrs,original_pre_dom_sha256:sha(before),prepared_pre_dom_sha256:sha(prepared),original_text_sha256:sha('original pending evidence'),complete_text_sha256:pin,inverse_exact:true});
 }
 const html='<!doctype html><html><head></head><body><section class="examples-section"><ol><li class="example-card"><a class="sentence-jump" data-latex-url="https://example.test/latex" data-full-paper-url="https://example.test/full"></a><span data-study-compiled-key="w">word</span>'+disclosure+direct+'</li></ol></section><script class="anki-final-reviewed-data" type="application/json" data-as-sha="'+sidePin+'" data-as-index-sha="'+indexPin+'">{}</script></body></html>';
 const sourceHTML=initialMode?html.replace(direct,sourceDirect):html;
 const wrapper=sha('wrapper'),payload=sha('payload'),registry={[sidePin]:sideRaw,[indexPin]:indexRaw};
 const side={html:sourceHTML,children:[],registry,proof:{source_sha256:sha(sourceHTML),expanded_sha256:sha(sourceHTML),source_bytes:Buffer.byteLength(sourceHTML),expanded_bytes:Buffer.byteLength(sourceHTML),registry_pins:Object.keys(registry).sort(),original_source_unmodified:true}};
 const artifact=save('artifact.json',{schema:'study-prepared-card.v1',source_wrapper_sha256:wrapper,source_payload_sha256:payload,sides:[side,side],modules:{[module.original_sha256]:{src:'evidence/module.js',sha256:module.sha256,original_sha256:module.original_sha256}}});
 const helper=save('helper.js','/* no execution */');
 const sourceRequest=save('source-request.json',{schema:'study-compiled-semantic-request.v1',artifact,module,source:{wrapper_sha256:wrapper,payload_sha256:payload},helpers:helper,base_url:'https://example.test/book/media/',resources:initialResources});
 const draft={schema:'study-canonical-interaction-bindings.draft.v1',source_artifact_sha256:artifact.sha256,nodeBindings:[{key:'w',roles:['projection-keyboard-wrapper']}],projectionWrappers:['w'],projectionComparisons:[],panels:[],groups:[],bankRecords:[]};
 function product(name,value){const raw=typeof value==='string'?value:JSON.stringify(value);fs.writeFileSync(path.join(producer,name),raw,{flag:'wx'});return{path:name,sha256:sha(raw),bytes:Buffer.byteLength(raw)}}
 const metadata=product('metadata.json','{}');
 const proof={schema:'study-compiled-semantic-source.v1',artifact_sha256:artifact.sha256,request_sha256:sourceRequest.sha256,helpers_sha256:helper.sha256,source_wrapper_sha256:wrapper,source_payload_sha256:payload,source_side_sha256:sha(sourceHTML),expanded_side_sha256:sha(sourceHTML),prepared_module_sha256:module.sha256,original_module_sha256:module.original_sha256,registry_pins:Object.keys(registry).sort(),metadata_sha256:metadata.sha256,initial_history_evidence:initialProof};
 const report={schema:'study-compiled-semantic-result.v1',pure_semantic_only:true,real_native_ready:true,authored_startup_executed:false,final_html:product('input.html',html),bindings:product('draft.json',draft),source_proof:product('source-proof.json',proof),metadata};
 const reportDescriptor=product('report.json',report);reportDescriptor.path=path.join(producer,reportDescriptor.path);
 const bindings=Object.fromEntries(emitter.REQUIRED_BINDINGS.map(name=>[name,sha(name)]));
 Object.assign(bindings,{producerInputSha256:report.bindings.sha256,sourceArtifactSha256:artifact.sha256,derivedHTMLSha256:sha(html),sourceWrapperSha256:wrapper,sourcePayloadSha256:payload,sourceSideSha256:sha(sourceHTML),expandedSideSha256:sha(sourceHTML),adapterSha256:helper.sha256,nativeModuleSha256:module.sha256,originalModuleSha256:module.original_sha256,rawSideSha256:sidePin,rawIndexSha256:indexPin});
 const request={schema:emitter.REQUEST_SCHEMA,producer_report:reportDescriptor,bindings:save('bindings.json',bindings)};
 if(withHistory||initialMode)request.history={parts,evidence,source_request:sourceRequest};
 const requestFile=path.join(base,'request.json');fs.writeFileSync(requestFile,JSON.stringify(request));
 return{base,producer,request,requestFile,bindings,html,draft,sourceRequest,saveRequest(){fs.writeFileSync(requestFile,JSON.stringify(request))}};
}
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledProfileTests(unittest.TestCase):
    def node(self, source, value=None):
        result = subprocess.run([shutil.which('node'), '-e', source], cwd=ROOT,
                                input=json.dumps(value), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_ast_preserves_css1_mode_unique_keys_and_semantic_regions(self):
        self.node(r"""
const assert=require('node:assert/strict'),a=require('./anki_pipeline/compiled/profile-ast.cjs');
const K='data-study-compiled-key',html='<!doctype html><section class="sf-report"><article class="sf-example" data-sf-occurrence-id="one" '+K+'="r">A<!--offset--><span '+K+'="w">word</span></article></section>';
const draft={schema:'study-canonical-interaction-bindings.draft.v1',source_artifact_sha256:'1'.repeat(64),nodeBindings:[{key:'w',roles:['projection-keyboard-wrapper']}],projectionWrappers:['w'],projectionComparisons:[],panels:[],groups:[],bankRecords:[]};
const x=a.projectFields({html,draft});assert.equal(x.fields.nodeBindings.length,2);
const w=x.fields.nodeBindings.find(n=>n.key==='w');assert.equal(w.rootKey,'r');assert.deepEqual(w.relativePath,[2]);
assert.deepEqual(w.region,{selector:'.sf-report',ordinal:0,total:1,rootPath:[0]});assert.equal(w.exactText,'word');
assert.throws(()=>a.projectFields({html:html.replace('<!doctype html>',''),draft}),/CSS1/);
assert.throws(()=>a.projectFields({html:html+'<p '+K+'="w"></p>',draft}),/duplicate/);
assert.throws(()=>a.projectFields({html:html.replace('class="sf-report"','class="uncovered"'),draft}),/uncovered/);
const withTemplate=html+'<template><section class="sf-report"><i '+K+'="w"></i></section></template>';
assert.equal(a.projectFields({html:withTemplate,draft}).index.reports.length,1);
""")

    def test_bank_canonical_projection_preserves_all_source_attributes_and_evidence(self):
        self.node(r"""
const assert=require('node:assert/strict'),{canonicalBankRecords,normalizeAttributes}=require('./anki_pipeline/compiled/normalize-bank.cjs');
const attrs=[['class','source-reader'],['data-shared-reading-bank-evidence','evidence'],['data-study-compiled-key','label']];
const record={labelKey:'label',containerKey:'root',evidence:'evidence',compiledAttributes:attrs};
const before=JSON.stringify(record),[normalized]=canonicalBankRecords([record],[{key:'label',requiredAttrs:attrs}]);
assert.deepEqual(Object.entries(normalized.compiledAttributes),attrs);assert.equal(JSON.stringify(record),before);
assert.equal(canonicalBankRecords([normalized],[{key:'label',requiredAttrs:attrs}])[0],normalized);
for(const value of [[['x','1'],['x','2']],[['x',1]],[['x','1','extra']],null,{x:1}])assert.throws(()=>normalizeAttributes(value));
assert.throws(()=>canonicalBankRecords([{...record,evidence:'other'}],[{key:'label',requiredAttrs:attrs}]),/evidence/);
assert.throws(()=>canonicalBankRecords([{...record,compiledAttributes:[...attrs,['foreign','x']]}],[{key:'label',requiredAttrs:attrs}]),/source label/);
""")

    def test_anchor_insertion_is_single_exact_and_reversible(self):
        self.node(r"""
const assert=require('node:assert/strict'),a=require('./anki_pipeline/compiled/profile-ast.cjs'),e=require('./anki_pipeline/compiled/profile-emitter.cjs');
const html='<!doctype html><section class="examples-section"><ol><li class="example-card"><a class="sentence-jump" data-rb-j="x"></a><span data-study-compiled-key="w">word</span></li></ol></section>';
const draft={schema:'study-canonical-interaction-bindings.draft.v1',source_artifact_sha256:'1'.repeat(64),nodeBindings:[{key:'w',roles:['projection-keyboard-wrapper']}],projectionWrappers:['w'],projectionComparisons:[],panels:[],groups:[],bankRecords:[]};
let error;try{a.projectFields({html,draft})}catch(x){error=x}assert.equal(error.code,'NEEDS_DELIVERY_ANCHOR_KEYS');
const x=e.insertAnchorKeys(html,error.keyInsertions);assert.equal(x.inverse,html);assert.equal(x.insertions.length,1);
assert.equal(a.projectFields({html:x.html,draft}).fields.nodeBindings.length,2);
assert.throws(()=>e.insertAnchorKeys(html,[{...error.keyInsertions[0],startTagSha256:'0'.repeat(64)}]),/anchor|SHA/);
assert.throws(()=>e.insertAnchorKeys(html,[error.keyInsertions[0],error.keyInsertions[0]]),/anchor|overlap/);
""")

    def test_closed_history_is_rejected_without_explicit_inputs(self):
        self.node(r"""
const assert=require('node:assert/strict'),e=require('./anki_pipeline/compiled/profile-emitter.cjs');
assert.throws(()=>e.validateHistoryInputs(undefined,1),/history|manifest/);
assert.doesNotThrow(()=>e.validateHistoryInputs(undefined,0));
""")

    def test_complete_emitter_preserves_header_and_anchors_and_copied_fields_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory);
const output=path.join(directory,'output'),report=await emitter.emitProfile(f.requestFile,output);
const profile=JSON.parse(fs.readFileSync(path.join(output,'profile.json'))),anchors=JSON.parse(fs.readFileSync(path.join(output,'anchors.json')));
assert.equal(profile.schema,'study-compiled-card-interactions.v1');assert.equal(profile.filter_mode,'host-after-authored-filter');
assert.equal(report.anchor_inverse.count,1);assert.equal(report.anchor_inverse.inverse_exact,true);
assert.equal(profile.nodeBindings.length,2);assert.equal(profile.nodeBindings[0].exactText,'word');
const header={...profile.bindings,derivedHTMLSha256:f.bindings.derivedHTMLSha256};assert.deepEqual(header,f.bindings);
for(const name of ['profile','anchors','delivery_html','fields']){const d=report[name],raw=fs.readFileSync(path.join(output,d.path));assert.equal(sha(raw),d.sha256);assert.equal(raw.length,d.bytes)}
assert.equal(anchors.profileSha256,report.profile.sha256);assert.equal(anchors.htmlSha256,report.delivery_html.sha256);
assert.equal(report.copied_fields_sha256,report.fields.sha256);assert.equal(report.copied_fields_exact,true);
await assert.rejects(emitter.emitProfile(f.requestFile,output),/new directory/);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_bad_source_header_or_input_pin_creates_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory),output=path.join(directory,'output');
const bad={...f.bindings,sourcePayloadSha256:'0'.repeat(64)},raw=JSON.stringify(bad);fs.writeFileSync(f.request.bindings.path,raw);f.request.bindings.sha256=sha(raw);f.saveRequest();
await assert.rejects(emitter.emitProfile(f.requestFile,output),/source\/header/);assert.equal(fs.existsSync(output),false);
f.request.producer_report.sha256='0'.repeat(64);f.saveRequest();await assert.rejects(emitter.emitProfile(f.requestFile,output),/SHA/);assert.equal(fs.existsSync(output),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_two_closed_history_slots_use_original_decoder_graphs_and_af_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory,true),output=path.join(directory,'output');
const report=await emitter.emitProfile(f.requestFile,output),profile=JSON.parse(fs.readFileSync(path.join(output,'profile.json')));
assert.equal(profile.historySlots.length,2);assert.equal(report.history.slots,2);assert.equal(report.history.parts,2);assert.equal(report.history.evidence,2);
assert.equal(profile.bindings.historyScopeEvidenceSha256,sha(fs.readFileSync(path.join(output,'history-scope.json'))));
assert.equal(profile.bindings.historyProducerSourceSha256,sha(fs.readFileSync('./anki_pipeline/compiled/profile-ast.cjs')));
for(const slot of profile.historySlots){
 assert.equal(slot.schema,'study-compiled-excluded-history-slot.v1');assert.equal(slot.sourceArtifactSha256,profile.bindings.sourceArtifactSha256);
 assert.equal(slot.ownerTree.name,'DETAILS');assert.equal(slot.ownerTree.attrs[0][1],'sf-ownership-history');
 const part=slot.parts[0],graph=JSON.stringify(part.tree);assert.ok(graph.includes('card-chunk'));assert.ok(graph.includes('target-word'));assert.ok(!graph.includes('"_c"'));
 assert.equal(part.consumerEvidence.projection_pair_roots.length,1);assert.equal(part.consumerEvidence.projection_pair_roots[0].excluded,true);
 for(const key of ['fine_example_roots','bank_containers','group_panels','group_physical_native_rows','residual_key_targets'])assert.deepEqual(part.consumerEvidence[key],[]);
 assert.equal(part.evidence.length,1);assert.equal(sha(part.evidence[0].text),part.evidence[0].sha256);
}
const restored={...profile.bindings,derivedHTMLSha256:f.bindings.derivedHTMLSha256};delete restored.historyScopeEvidenceSha256;delete restored.historyProducerSourceSha256;assert.deepEqual(restored,f.bindings);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_history_wrong_scope_pin_or_extra_capability_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory,true),output=path.join(directory,'output');
const evidence=Object.values(f.request.history.evidence)[0];evidence.sha256='0'.repeat(64);f.saveRequest();
await assert.rejects(emitter.emitProfile(f.requestFile,output),/SHA/);assert.equal(fs.existsSync(output),false);
evidence.sha256=sha(fs.readFileSync(evidence.path));f.request.history.parts['1'.repeat(64)]={path:evidence.path,sha256:'1'.repeat(64)};f.saveRequest();
await assert.rejects(emitter.emitProfile(f.requestFile,output),/SHA|history/);assert.equal(fs.existsSync(output),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_history_rejects_new_consumers_reader_decode_and_unexcluded_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
const assert=require('node:assert/strict'),a=require('./anki_pipeline/compiled/profile-ast.cjs');
const directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory,true),original=JSON.parse(fs.readFileSync(f.sourceRequest.path));
const moduleCode=fs.readFileSync(original.module.path,'utf8'),entries=Object.entries(f.request.history.parts),oldPin=entries[0][0];
const otherRaw=fs.readFileSync(entries[1][1].path,'utf8'),evidenceName=Object.keys(f.request.history.evidence)[1],evidenceDescriptor=f.request.history.evidence[evidenceName];
const evidence={[evidenceName]:{raw:fs.readFileSync(evidenceDescriptor.path,'utf8'),sha256:evidenceDescriptor.sha256}};
for(const [raw,reason]of [['<p class="sf-panel">live</p>',/forbidden scope/],['<a data-rb-j="unknown">link</a>',/source-reader decoder scope/],['<div class="sf-sentence-pair">unexcluded</div>',/Projection exclusion drift/]]){
 const pin=sha(raw),html=f.html.replaceAll(oldPin,pin).replaceAll(oldPin.slice(0,24),pin.slice(0,24)),index=a.indexHTML(html);
 const parts={[pin]:raw,[entries[1][0]]:otherRaw};
 assert.throws(()=>a.buildHistorySlots({index,sourceArtifactSha256:f.draft.source_artifact_sha256,moduleCode,module:original.module,parts,evidence}),reason);
}
""", tmp)

    def test_af_registration_hash_does_not_replace_logical_text_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8')),f=fixture(directory,true),output=path.join(directory,'output');
const d=Object.values(f.request.history.evidence)[0],raw=fs.readFileSync(d.path,'utf8').replace('完整审核','篡改审核');fs.writeFileSync(d.path,raw);d.sha256=sha(raw);f.saveRequest();
await assert.rejects(emitter.emitProfile(f.requestFile,output),/evidence text SHA/);assert.equal(fs.existsSync(output),false);
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def direct_af_is_rejected_before_output(self, with_history):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),[directory,history]=JSON.parse(fs.readFileSync(0,'utf8'));
const media='data-native-history-media="_af_'+('1'.repeat(24))+'.js"',pin='data-native-history-sha="'+('1'.repeat(64))+'"';
for(const [index,attrs] of [media+' '+pin,media,pin].entries()){
 const cell=path.join(directory,String(index));fs.mkdirSync(cell);const f=fixture(cell,history,attrs),output=path.join(cell,'output');
 await assert.rejects(emitter.emitProfile(f.requestFile,output),/uncovered direct native-history evidence/);
 assert.equal(fs.existsSync(output),false,'unsupported initial evidence must reject before output directory creation');
}
})().catch(e=>{console.error(e);process.exitCode=1});
""", [tmp, with_history])

    def test_direct_af_without_manifest_is_rejected_before_output(self):
        self.direct_af_is_rejected_before_output(False)

    def test_direct_af_mixed_with_manifest_is_rejected_before_output(self):
        self.direct_af_is_rejected_before_output(True)

    def test_authenticated_ready_initial_af_uses_existing_exact_text_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8'));
for(const mixed of [false,true]){
 const cell=path.join(directory,String(mixed));fs.mkdirSync(cell);const f=fixture(cell,mixed,'','ready'),output=path.join(cell,'output');
 const report=await emitter.emitProfile(f.requestFile,output),profile=JSON.parse(fs.readFileSync(path.join(output,'profile.json'))),scope=JSON.parse(fs.readFileSync(path.join(output,'history-scope.json')));
 assert.equal(report.history.initial,1);assert.equal(report.history.slots,mixed?2:0);assert.equal(profile.historySlots.length,mixed?2:0);
 assert.equal(scope.initial.length,1);const initial=scope.initial[0];assert.equal(initial.ready,true);assert.equal(initial.textOnly,true);assert.equal(initial.inverseExact,true);
 const root=profile.nodeBindings.find(spec=>spec.key===initial.rootKey);assert.equal(typeof root.exactText,'string');
 assert.ok(root.exactText.includes(mixed?'完整审核😀':'初始完整审核😀'));
 assert.equal(report.history.evidence,mixed?2:1,'initial and parts consume the same AF resource only once');
 assert.equal(Object.keys(profile).some(name=>/initial/i.test(name)),false,'v1 profile gains no initial-pre permission table');
 assert.equal(initial.resourceSha256,Object.values(f.request.history.evidence)[0].sha256);
}
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_ready_label_with_wrong_text_or_element_children_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8'));
for(const mode of ['wrong-text','graph']){
 const cell=path.join(directory,mode);fs.mkdirSync(cell);const f=fixture(cell,false,'',mode),output=path.join(cell,'output');
 await assert.rejects(emitter.emitProfile(f.requestFile,output),/initial history ready\/text\/graph|uncovered direct native-history evidence/);
 assert.equal(fs.existsSync(output),false);
}
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)

    def test_ready_initial_af_requires_resource_and_producer_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.node(FIXTURE_JS + r"""
(async()=>{const assert=require('node:assert/strict'),directory=JSON.parse(fs.readFileSync(0,'utf8'));
for(const missing of ['evidence','proof']){
 const cell=path.join(directory,missing);fs.mkdirSync(cell);const f=fixture(cell,false,'','ready'),output=path.join(cell,'output');
 if(missing==='evidence')f.request.history.evidence={};
 else{
  const report=JSON.parse(fs.readFileSync(f.request.producer_report.path)),proofFile=path.join(f.producer,report.source_proof.path),proof=JSON.parse(fs.readFileSync(proofFile));
  proof.initial_history_evidence=[];const raw=JSON.stringify(proof);fs.writeFileSync(proofFile,raw);report.source_proof.sha256=sha(raw);report.source_proof.bytes=Buffer.byteLength(raw);
  const body=JSON.stringify(report);fs.writeFileSync(f.request.producer_report.path,body);f.request.producer_report.sha256=sha(body);
 }
 f.saveRequest();await assert.rejects(emitter.emitProfile(f.requestFile,output),/initial history source/);assert.equal(fs.existsSync(output),false);
}
})().catch(e=>{console.error(e);process.exitCode=1});
""", tmp)


if __name__ == '__main__':
    unittest.main()
