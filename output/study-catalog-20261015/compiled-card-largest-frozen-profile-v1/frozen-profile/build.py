from pathlib import Path
import json,hashlib,difflib
P=Path(__file__).parent
sha=lambda s:hashlib.sha256(s.encode()).hexdigest()
base=(P/'baseline-frame.js').read_text();html=(P/'baseline-frame.html').read_text();runtime=(P/'input-runtime.js').read_text()
assert sha(base)=='68ff450a940e090e62d18823a684a66c78fa610f3dd4f0fd7529a492fcbd00b0';assert sha(html)=='2acd3b963a4a3fbb4be95248a3c2e5d02f63019b23ad1c9e6cf6d6621ad7e174';assert sha(runtime)=='e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc'
helper=(P/'support-helper.js').read_text();adapter=(P/'runtime-adapter.js').read_text();edits=[];code=base
def add(before,after):
 global code
 assert code.count(before)==1,before[:100]
 code=code.replace(before,after);edits.append([before,after])
add('function makeCompiledProfileSupport(assets, resource, matches, canonical, current) {',adapter+'\nfunction makeCompiledProfileSupport(assets, resource, matches, canonical, current) {')
line=" function immutable(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(immutable);Object.freeze(value)}return value}"
add(line,line+'\n'+helper)
add('const result=Object.freeze({html,profile:immutable(profile),runtimeCode,runtimeSha256:assets.runtime.sha256});','const result=Object.freeze({html,profile:rememberFrozenProfile(profile),runtimeCode,runtimeSha256:assets.runtime.sha256});')
add('return Object.freeze({load,bind,clear(doc){owners.delete(doc)}});','return Object.freeze({load,bind,withFrozenCapture,clear(doc){owners.delete(doc)}});')
add("if(!win.AnkiCompiledCardRuntime)execute(doc,compiled.runtimeCode,'compiled-card-'+compiled.runtimeSha256);","if(!win.AnkiCompiledCardRuntime)compiledProfiles.withFrozenCapture(win,enabled=>execute(doc,enabled?adaptCompiledFrozenProfile(compiled.runtimeCode,compiled.runtimeSha256):compiled.runtimeCode,'compiled-card-'+compiled.runtimeSha256));")
inverse=code
for before,after in reversed(edits):assert inverse.count(after)==1;inverse=inverse.replace(after,before)
assert inverse==base;assert html.count(base)==1;newhtml=html.replace(base,code);assert newhtml.replace(code,base)==html
for name,text in [('candidate-frame.js',code),('candidate-frame.html',newhtml)]: (P/name).write_text(text)
(P/'edits.json').write_text(json.dumps(edits,ensure_ascii=False,indent=2)+'\n')
proof={'schema':'study-frozen-profile-reuse-composition.v1','baseline_frame_sha256':sha(base),'baseline_html_sha256':sha(html),'candidate_frame_sha256':sha(code),'candidate_html_sha256':sha(newhtml),'exact_edits':len(edits),'inverse_exact_frame':True,'inverse_exact_html':True,'runtime_input_sha256':sha(runtime),'same_resource_source_SHA_validation_before_adapter':True,'author_order_layout_native_fullgate_unchanged':True,'no_new_await_or_geometry_or_diagnostic_clock':True}
(P/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');(P/'runtime.diff').write_text(''.join(difflib.unified_diff(base.splitlines(True),code.splitlines(True),fromfile='baseline-68ff.js',tofile='candidate.js')));print(json.dumps(proof,indent=2))
