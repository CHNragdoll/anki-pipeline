"""Native delivery adapters: source fields and host identity stay separate."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from anki_pipeline.study_catalog_export import _render_note

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e'
PREPARED = '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4'
SECOND_ORIGINAL = 'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'
SECOND_PREPARED = '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'
sha = lambda raw: hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def sample_note():
    names = ['Word', 'Phonetic', 'Definition', 'SimpleDefinition', 'Level',
             'WordForms', 'Audio', 'Examples', 'Meta', 'Note']
    model = {'id': 17, 'mod': 20, 'sortf': 0,
             'flds': [{'name': name, 'ord': i} for i, name in enumerate(names)],
             'css': '.word{color:blue}', 'tmpls': [{'name': 'Card', 'ord': 0,
             'qfmt': '<main class="vocab-front">{{Word}}</main>',
             'afmt': '{{FrontSide}}<hr id="answer"><main>{{Definition}}</main>'}]}
    return {'id': 'opaque-source', 'note_id': 31, 'guid': 'unchanged-guid',
            'model_id': 17, 'model': model, 'field_names': names,
            'fields': ['word', '', '<p>complete 中文😀</p>', '', '', '', '', '', '', ''],
            'payload': {'id': 31, 'mid': 17, 'guid': 'unchanged-guid', 'mod': 19},
            'content_mod': 21}


class NativeCompiledTests(unittest.TestCase):
    def bundle(self, original=ORIGINAL, with_history=False):
        prepared_pin = PREPARED if original == ORIGINAL else SECOND_PREPARED
        module_path = ('tests/fixtures/experimental-authored-codec-frame-v1/resource-00.gz'
                       if original == ORIGINAL else 'tests/fixtures/study-compiled-native/prepared-module-6a2b0f26.js.gz')
        module = gzip.decompress((ROOT/module_path).read_bytes())
        self.assertEqual(sha(module), prepared_pin)
        runtime = (ROOT/'tests/fixtures/experimental-compiled-card-v1/history-slots-v1/runtime.js').read_bytes()
        init = 'window.nativeEvents=(window.nativeEvents||[]);window.nativeEvents.push(!!window.StudyCompiledProfileBridge.get(document));window.AnkiSlimApkgHydrate();'
        source = '<!doctype html><html><head></head><body><main class="vocab-card vocab-front"><h1 class="word">word</h1></main>{}<script src="_as_runtime.js"></script><script>'+init+'</script></body></html>'
        front = source.format('')
        raw_side, raw_index = '{}', '{"bindings":[]}'
        payload = '<script class="anki-final-reviewed-data" type="application/json" data-as-sha="' + sha(raw_side) + '" data-as-index-sha="' + sha(raw_index) + '">{}</script>'
        back = source.format('<hr id="answer"><div class="vocab-card vocab-back"><p>完整中文😀</p></div>' + payload)
        histories, parts, evidence, extra = [], {}, {}, {}
        if with_history:
            for index in range(2):
                text = '审核完整中文😀 ' + str(index); pin = sha(text); name = '_af_' + pin[:24] + '.js'
                raw = ('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};window.AnkiFinalHistoryEvidence[' + json.dumps(pin) + ']=' + json.dumps(text, ensure_ascii=False) + ';').encode()
                evidence[name] = {'raw': raw.decode(), 'sha256': sha(raw)}; extra[name] = raw
                part = '<div class="sf-archived-native-example"><div class="sf-sentence-pair"><span _c="e0">old</span><span _c="z0">旧</span></div><details><summary>audit</summary><pre data-native-history-media="' + name + '" data-native-history-sha="' + pin + '">pending</pre></details></div>'
                part_pin = sha(part); part_name = '_as_' + part_pin[:24] + '.js'; parts[part_pin] = part
                extra[part_name] = ('window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets[' + json.dumps(part_pin) + ']=' + json.dumps(part, ensure_ascii=False) + ';').encode()
                manifest = json.dumps({'schema': 'anki-slim-segments.v1', 'parts': [{'src': part_name, 'sha256': part_pin, 'count': 1}], 'total': 1}, separators=(',', ':'))
                histories.append('<details class="sf-ownership-history"><summary>history</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json">' + manifest + '</script></div></details>')
            historical = '<section class="examples-section"><ol><li class="example-card"><a class="sentence-jump" data-latex-url="https://example.test/latex" data-full-paper-url="https://example.test/full"></a>' + ''.join(histories) + '</li></ol></section>'
            back = source.format('<hr id="answer">' + historical + payload)
        bindings = {key: sha(key) for key in ['producerInputSha256', 'sourceArtifactSha256',
          'derivedHTMLSha256', 'sourceWrapperSha256', 'sourcePayloadSha256', 'sourceSideSha256',
          'expandedSideSha256', 'materializerSha256', 'frameRuntimeSha256', 'frameHTMLSha256',
          'adapterSha256', 'nativeModuleSha256', 'originalModuleSha256', 'rawSideSha256',
          'rawIndexSha256', 'residualListenerSha256', 'readerDelegateSha256']}
        bindings.update(derivedHTMLSha256=sha(back), originalModuleSha256=original, nativeModuleSha256=prepared_pin,
                        sourceWrapperSha256=sha('wrapper'), sourcePayloadSha256=sha('payload'),
                        sourceSideSha256=sha(back), expandedSideSha256=sha(back),
                        rawSideSha256=sha(raw_side), rawIndexSha256=sha(raw_index))
        profile = {'schema': 'study-compiled-card-interactions.v1', 'version': 1,
                   'filter_mode': 'host-after-authored-filter', 'residual_mode': 'original-listener',
                   'bindings': bindings, **{key: [] for key in ['nodeBindings', 'readerLinks', 'projectionWrappers',
                   'projectionComparisons', 'residualWrappers', 'panels', 'groups', 'bankRecords', 'historySlots']}}
        if with_history:
            completed = subprocess.run(['node', '-e', "const fs=require('fs'),a=require('./anki_pipeline/compiled/profile-ast.cjs'),v=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(a.buildHistorySlots({...v,index:a.indexHTML(v.html)}).slots));"],
                cwd=ROOT, input=json.dumps({'html': back, 'moduleCode': module.decode(),
                    'module': {'sha256': prepared_pin, 'original_sha256': original},
                    'sourceArtifactSha256': bindings['sourceArtifactSha256'], 'parts': parts, 'evidence': evidence}),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            profile['historySlots'] = json.loads(completed.stdout)
        raw = json.dumps(profile, separators=(',', ':')).encode()
        resources = {'_module.js': module, '_html.html': back.encode(), '_profile.json': raw, '_runtime.js': runtime, **extra}
        sides = [{'html': text, 'children': [], 'registry': {}, 'proof': {'source_sha256': sha(text),
                  'expanded_sha256': sha(text), 'registry_pins': []}} for text in [front, back]]
        sides[1]['registry'] = {sha(raw_side): raw_side, sha(raw_index): raw_index}
        sides[1]['proof']['registry_pins'] = sorted(sides[1]['registry'])
        prepared = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': sha('wrapper'),
                    'source_payload_sha256': sha('payload'), 'sides': sides,
                    'modules': {original: {'src': 'evidence/_module.js', 'original_sha256': original, 'sha256': prepared_pin}}}
        entry = {'decoded': True, 'source': {'wrapper_sha256': sha('wrapper'), 'payload_sha256': sha('payload'),
                 'side_sha256': sha(back), 'expanded_sha256': sha(back), 'registry_pins': sorted(sides[1]['registry'])},
                 'module': {'original_sha256': original, 'sha256': prepared_pin},
                 'html': {'src': '_html.html', 'sha256': sha(back)},
                 'profile': {'src': '_profile.json', 'sha256': sha(raw)},
                 'anchors': {'schema': profile['schema'], 'version': 1, 'bindings': bindings,
                             'profileSha256': sha(raw), 'htmlSha256': sha(back)}}
        return {'entry': entry, 'runtime': {'src': '_runtime.js', 'sha256': sha(runtime)}, 'prepared': prepared,
                'policy': {'external': {'_as_runtime.js': original}, 'inline': [{'source': init, 'sha256': sha(init)}]},
                'resources': resources, 'model_mod': 22, 'note_mod': 23}

    def native(self, bundle=None):
        from anki_pipeline.study_compiled_native import project_native_note
        return project_native_note(sample_note(), **(bundle or self.bundle()))

    def test_plain_note_is_an_exact_copy_without_added_fields_or_version_changes(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note(); before = copy.deepcopy(note)
        result = project_native_note(note, None, None)
        self.assertEqual(result['note'], before)
        self.assertEqual(result['media'], {})
        self.assertEqual(result['capability'], 'original-native')
        self.assertEqual(note, before)

    def test_baseline_render_has_no_independent_transport_or_owner_gate(self):
        # Characterizes the real pre-adapter path, rather than a missing import.
        front, back = _render_note(sample_note())
        self.assertNotIn('data-study-native-owner', back)
        self.assertTrue(back.startswith(front))

    def test_source_fields_identities_and_input_objects_are_unchanged(self):
        note = sample_note(); bundle = self.bundle(); before = copy.deepcopy((note, bundle))
        from anki_pipeline.study_compiled_native import project_native_note
        result = project_native_note(note, **bundle)
        actual = result['note']
        self.assertEqual(actual['fields'][:-1], note['fields'])
        self.assertEqual(actual['field_names'][:-1], note['field_names'])
        for name in ['id', 'note_id', 'guid', 'model_id']:
            self.assertEqual(actual[name], note[name])
        self.assertEqual(actual['model']['id'], note['model']['id'])
        self.assertEqual(actual['model']['flds'][:-1], note['model']['flds'])
        self.assertEqual((note, bundle), before)
        self.assertEqual(actual['content_mod'], 23)
        front, back = _render_note(actual)
        self.assertIn('data-answer="false"', front)
        self.assertIn('data-answer="true"', back)
        self.assertNotIn('{{FrontSide}}', actual['model']['tmpls'][0]['afmt'])
        self.assertFalse(back.startswith(front))
        self.assertNotIn('完整中文', actual['fields'][-1], 'no second semantic DOM in descriptor')

    def test_versions_source_bindings_and_resource_sha_fail_closed(self):
        for change, message in [(lambda b: b.update(note_mod=None), 'committed'),
                                (lambda b: b.update(model_mod=20), 'committed'),
                                (lambda b: b['entry']['source'].update(side_sha256='0'*64), 'source'),
                                (lambda b: b['entry']['anchors'].update(profileSha256='0'*64), 'bindings'),
                                (lambda b: b['entry']['anchors'].update(htmlSha256='0'*64), 'bindings')]:
            bundle = self.bundle(); change(bundle)
            with self.assertRaisesRegex(ValueError, message):
                self.native(bundle)
        bundle = self.bundle(); bundle['resources']['_runtime.js'] += b'wrong'
        with self.assertRaisesRegex(ValueError, 'bytes differ'):
            self.native(bundle)

    def test_projected_committed_versions_use_explicit_sealed_baselines(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note(); note['model']['mod'] = 22
        bundle = self.bundle(); bundle.update(model_mod=22, note_mod=21)
        result = project_native_note(note, **bundle, original_model_mod=20, original_note_mod=19)
        self.assertEqual(result['note']['model']['mod'], 22)
        self.assertEqual(result['note']['content_mod'], 21)
        with self.assertRaisesRegex(ValueError, 'committed'):
            project_native_note(note, **bundle)

    def test_resealed_profile_cannot_change_its_source_or_native_registry_binding(self):
        for key in ['sourceWrapperSha256', 'sourcePayloadSha256', 'sourceSideSha256',
                    'expandedSideSha256', 'rawSideSha256', 'rawIndexSha256']:
            with self.subTest(key=key):
                bundle = self.bundle()
                profile = json.loads(bundle['resources']['_profile.json'])
                profile['bindings'][key] = '0' * 64
                raw = json.dumps(profile, separators=(',', ':')).encode()
                bundle['resources']['_profile.json'] = raw
                bundle['entry']['profile']['sha256'] = sha(raw)
                bundle['entry']['anchors']['profileSha256'] = sha(raw)
                bundle['entry']['anchors']['bindings'] = profile['bindings']
                with self.assertRaisesRegex(ValueError, 'source|registry'):
                    self.native(bundle)

    def test_native_sound_markup_is_rejected_instead_of_becoming_web_audio(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note(); note['fields'][6] = '[sound:original.mp3]'
        with self.assertRaisesRegex(ValueError, 'original Anki replay'):
            project_native_note(note, **self.bundle())

    def test_actual_native_loader_back_boots_without_front_and_preserves_anki_shell(self):
        self.run_native(r"""
const f=await boot();
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.w.StudyCompiledNative.snapshot().answer,true);
assert.deepEqual([...f.w.nativeEvents],[true],'profile bound before original hydrate startup');
assert.equal(f.d.getElementById('native-rating').textContent,'native rating');
assert.equal(f.d.head.querySelector('#anki-bridge').textContent,'bridge');
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
assert.equal(f.d.querySelector('.anki-final-reviewed-data').dataset.nativeState,'ready');
assert.equal(f.w.AnkiFineChunkRuntime,undefined,'no original four-semantics definition or install');
assert.equal(f.requests.filter(s=>s.includes('_html.html')).length,0,'only generated local carriers');
f.close();
""")

    def test_standalone_front_does_not_load_back_html_profile_or_binder(self):
        self.run_native(r"""
const f=await boot('front');
assert.equal(f.w.StudyCompiledNative.snapshot().answer,false);
assert.deepEqual([...f.w.nativeEvents],[false]);
assert.equal(f.w.AnkiCompiledCardRuntime,undefined);
const descriptor=JSON.parse(new JSDOM(input.front).window.document.querySelector('[data-study-native-delivery]').textContent);
for(const asset of [descriptor.entry.html,descriptor.entry.profile,descriptor.runtime])assert.ok(!f.requests.includes(descriptor.transport[asset.src].src));
f.close();
""")

    def test_same_document_front_back_retirement_and_pagehide_revoke_old_profile(self):
        self.run_native(r"""
const f=await boot('back'),first=f.w.StudyCompiledNative.snapshot(),old=f.w.StudyCompiledProfileBridge.get(f.d);
assert.equal(f.w.StudyCompiledProfileBridge.isCurrent(f.d,old),true);
await f.switchSide('front');const second=f.w.StudyCompiledNative.snapshot();
assert.ok(second.generation>first.generation);assert.equal(second.answer,false);
assert.equal(f.w.StudyCompiledProfileBridge.isCurrent(f.d,old),false);
await f.switchSide('back');assert.ok(f.w.StudyCompiledNative.snapshot().generation>second.generation);
assert.deepEqual([...f.w.nativeEvents],[true,false,true]);
f.w.dispatchEvent(new f.w.Event('pagehide'));assert.equal(f.w.StudyCompiledNative.snapshot(),null);
assert.equal(f.w.StudyCompiledProfileBridge.get(f.d),null);
assert.ok(f.d.getElementById('native-rating'));
f.close();
""")

    def test_new_bootstrap_content_retires_only_its_old_same_document_host(self):
        from anki_pipeline import study_compiled_native as native
        factory, _ = native._bootstrap_parts()
        revised = factory.replace('/* Native host only.', '/* Revised native host only.', 1)
        self.assertNotEqual(factory, revised)
        with patch.object(native, '_bootstrap_parts', return_value=(revised, sha(revised))):
            second = self.native()
        self.run_native(r"""
const f=await boot(),old=f.w.StudyCompiledNative,oldBridge=f.w.StudyCompiledProfileBridge;
const oldProfile=oldBridge.get(f.d),oldState=old.snapshot();
f.d.getElementById('qa').innerHTML=input.variants[0].back;
const next=f.d.querySelector('[data-study-native-owner]');
const name=f.d.querySelector('#qa>script[src]').getAttribute('src');
f.w.eval(input.media[name]);
await wait(()=>f.w.StudyCompiledNative?.snapshot()?.state==='ready');
assert.notEqual(f.w.StudyCompiledNative,old,'new delivered source cannot silently reuse old host');
assert.notEqual(f.w.StudyCompiledProfileBridge,oldBridge);
assert.equal(old.snapshot(),null);assert.equal(oldBridge.isCurrent(f.d,oldProfile),false);
assert.equal(await old.mount(next),null,'retired API cannot reclaim new card');
assert.ok(f.w.StudyCompiledNative.snapshot().generation>oldState.generation);
const current=f.w.StudyCompiledNative.snapshot(),bridge=f.w.StudyCompiledProfileBridge;
old.shutdown();assert.equal(f.w.StudyCompiledProfileBridge,bridge);
assert.deepEqual(f.w.StudyCompiledNative.snapshot(),current);
const oldName=new JSDOM(input.back).window.document.querySelector('script[src]').getAttribute('src');
f.w.eval(input.media[oldName]);
assert.equal(f.w.StudyCompiledProfileBridge,bridge,'late old bootstrap cannot downgrade current host');
assert.deepEqual(f.w.StudyCompiledNative.snapshot(),current);
assert.equal(f.d.head.querySelector('#anki-bridge').textContent,'bridge');
assert.equal(f.d.getElementById('native-rating').textContent,'native rating');f.close();
const pending=await boot('back',{hold:true,allowLoading:true}),retired=pending.w.StudyCompiledNative;
pending.d.getElementById('qa').innerHTML=input.variants[0].front;pending.unhold();
const updated=pending.d.querySelector('#qa>script[src]').getAttribute('src');
pending.w.eval(input.media[updated]);
await wait(()=>pending.w.StudyCompiledNative?.snapshot()?.state==='ready');
const fresh=pending.w.StudyCompiledNative.snapshot();
pending.release();await new Promise(r=>setTimeout(r,10));
assert.equal(retired.snapshot(),null);assert.deepEqual(pending.w.StudyCompiledNative.snapshot(),fresh);
assert.equal(fresh.answer,false);assert.equal(pending.d.querySelector('[role="alert"]'),null);pending.close();
""", variants=[second])

    def test_two_actual_module_cohorts_reuse_document_but_not_owner_or_profile(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note(); note['id'] = 'second-source'; note['note_id'] = 32; note['guid'] = 'second-guid'
        second = project_native_note(note, **self.bundle(SECOND_ORIGINAL))
        self.run_native(r"""
const f=await boot('back'),a=f.w.StudyCompiledNative.snapshot(),old=f.w.StudyCompiledProfileBridge.get(f.d);
await f.switchSide('back',0);const b=f.w.StudyCompiledNative.snapshot(),p=f.w.StudyCompiledProfileBridge.get(f.d);
assert.equal(b.id,'second-source');assert.ok(b.generation>a.generation);
assert.equal(p.bindings.originalModuleSha256,'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93');
assert.equal(f.w.StudyCompiledProfileBridge.isCurrent(f.d,old),false);
assert.equal(f.w.AnkiFineChunkRuntime,undefined);
assert.equal(f.w.AnkiCompiledCardRuntime.install(f.d,p).stats().invalid,null);
await f.switchSide('back');const c=f.w.StudyCompiledNative.snapshot();
assert.equal(c.id,a.id);assert.ok(c.generation>b.generation);
assert.equal(f.w.StudyCompiledProfileBridge.isCurrent(f.d,p),false);
assert.equal(f.w.AnkiCompiledCardRuntime.install(f.d,f.w.StudyCompiledProfileBridge.get(f.d)).stats().invalid,null);
f.close();
""", variants=[second])

    def test_late_local_registration_after_selection_retirement_cannot_commit_or_fail_new_card(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note(); note['id'] = 'new-owner'; note['note_id'] = 32
        second = project_native_note(note, **self.bundle())
        self.run_native(r"""
const f=await boot('back',{hold:true,allowLoading:true});
const first=f.w.StudyCompiledNative.snapshot(),oldReady=f.w.StudyCompiledNative.mount(f.d.querySelector('[data-study-native-owner]'));
assert.equal(first.state,'loading');assert.ok(f.requests.length>0);
f.unhold();await f.switchSide('back',0);const next=f.w.StudyCompiledNative.snapshot();
assert.equal(next.id,'new-owner');assert.equal(next.ready,true);assert.ok(next.generation>first.generation);
assert.equal(await oldReady,null);
f.release();await new Promise(r=>setTimeout(r,10));
assert.deepEqual(f.w.StudyCompiledNative.snapshot(),next);
assert.equal(f.d.querySelector('[role="alert"]'),null);assert.ok(f.d.getElementById('native-rating'));
f.close();
""", variants=[second])

    def test_compiled_plain_compiled_preserves_later_authored_loader_and_shared_registry(self):
        bundle = self.bundle()
        module = bundle['resources']['_module.js'].decode()
        marker = '/* Offline shared literals only. The outer loader verifies the dictionary and\n'
        result = self.native(bundle)
        result['media']['_test_unmodified_authored_loader.js'] = module[module.index(marker):].encode()
        self.run_native(r"""
const f=await boot(),compiledHydrate=f.w.AnkiSlimApkgHydrate;
const plain='<main id="plain-author">ordinary native author</main>';
f.d.getElementById('qa').innerHTML=plain;
// Anki can execute the new author's scripts before MutationObserver delivery.
f.w.eval(input.media['_test_unmodified_authored_loader.js']);
assert.notEqual(f.w.AnkiSlimApkgHydrate,compiledHydrate,'original shared-v2 must install its own plain loader');
const plainHydrate=f.w.AnkiSlimApkgHydrate,plainDispose=f.w.AnkiSlimApkgDispose;
let newDisposeCalls=0;const observedPlainDispose=()=>{newDisposeCalls++;return plainDispose();};
f.w.AnkiSlimApkgDispose=observedPlainDispose;
f.w.AnkiSlimAssets.authoredNewEntry='preserve newer registry content';
await new Promise(r=>setTimeout(r,5));
assert.equal(newDisposeCalls,0,'retired compiled MO cannot call the new ordinary disposer');
assert.equal(f.w.AnkiSlimApkgHydrate,plainHydrate);
assert.equal(f.w.AnkiSlimApkgDispose,observedPlainDispose);
assert.equal(f.w.AnkiSlimAssets.authoredNewEntry,'preserve newer registry content');
assert.equal(f.w.StudyCompiledNative.snapshot(),null);
await f.switchSide('back');assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.notEqual(f.w.AnkiSlimApkgHydrate,plainHydrate);
f.d.getElementById('qa').innerHTML=plain;
await new Promise(r=>setTimeout(r,5));
assert.equal(f.w.AnkiSlimApkgHydrate,plainHydrate,'no later author: restore sealed original loader');
assert.equal(f.w.AnkiSlimApkgDispose,observedPlainDispose);
assert.equal(f.w.__AnkiSlimStorageVersion,'shared-v2');
assert.equal(f.w.AnkiSlimAssets.authoredNewEntry,'preserve newer registry content');
assert.equal(f.d.getElementById('plain-author').textContent,'ordinary native author');
assert.equal(f.d.getElementById('native-rating').textContent,'native rating');f.close();
""", result=result)

    def test_original_two_closed_parts_and_af_use_only_pinned_owner_bound_carriers(self):
        self.run_native(r"""
const f=await boot('back');
for(const detail of f.d.querySelectorAll('details.sf-ownership-history')){
 detail.open=true;detail.dispatchEvent(new f.w.Event('toggle'));await wait(()=>detail.querySelector('script.as-manifest').dataset.asState==='ready');
 const chunk=detail.querySelector('.card-chunk');assert.ok(chunk,'original fragment decoder retained');
 assert.equal(chunk.getAttribute('data-chunk-ids'),'0');
 const pre=detail.querySelector('pre[data-native-history-media]');pre.parentElement.open=true;pre.parentElement.dispatchEvent(new f.w.Event('toggle'));
 await wait(()=>pre.dataset.nativeHistoryReady==='true');assert.ok(pre.textContent.startsWith('审核完整中文😀'));
}
const p=f.w.StudyCompiledProfileBridge.get(f.d),h=f.w.AnkiCompiledCardRuntime.install(f.d,p);
assert.equal(h.stats().invalid,null);assert.equal(f.d.querySelectorAll('pre[data-native-history-ready="true"]').length,2);
assert.ok(f.requests.every(n=>n.startsWith('_study_native_')),'no unverified original script src loads');
f.close();
""", bundle=self.bundle(with_history=True))

    def test_late_original_as_and_af_cannot_write_after_owner_retirement(self):
        self.run_native(r"""
for(const phase of ['AS','AF']){
 const f=await boot('back'),detail=f.d.querySelector('details.sf-ownership-history');
 if(phase==='AF'){detail.open=true;detail.dispatchEvent(new f.w.Event('toggle'));await wait(()=>detail.querySelector('script.as-manifest').dataset.asState==='ready');}
 f.hold();const previous=f.requests.length;
 if(phase==='AS'){detail.open=true;detail.dispatchEvent(new f.w.Event('toggle'));}
 else{const pre=detail.querySelector('pre');pre.parentElement.open=true;pre.parentElement.dispatchEvent(new f.w.Event('toggle'));}
 await wait(()=>f.requests.length>previous);
 f.unhold();await f.switchSide('front');const stable=detail.outerHTML,snapshot=f.w.StudyCompiledNative.snapshot();
 f.release();await new Promise(r=>setTimeout(r,15));
 assert.equal(detail.outerHTML,stable,phase+' did not mutate detached owner');
 assert.deepEqual(f.w.StudyCompiledNative.snapshot(),snapshot);assert.equal(snapshot.ready,true);
 assert.equal(f.d.querySelector('[role="alert"]'),null);f.close();
}
""", bundle=self.bundle(with_history=True))

    def test_failed_carrier_never_reveals_another_card_or_removes_anki_controls(self):
        result = self.native()
        descriptor = json.loads(result['note']['fields'][-1])
        name = descriptor['transport'][descriptor['entry']['profile']['src']]['src']
        result['media'][name] = result['media'][name].replace(b'"study-compiled-card-interactions.v1"', b'"tampered"')
        # Carriers serialize the profile as an escaped string; alter a harmless
        # UTF-8 byte if the particular registration has no unescaped schema.
        if b'"tampered"' not in result['media'][name]:
            result['media'][name] = result['media'][name].replace(b'bindings', b'BindIngs', 1)
        self.run_native(r"""
const f=await boot('back',{allowFailure:true});
assert.equal(f.w.StudyCompiledNative.snapshot().ready,false);
assert.equal(f.w.StudyCompiledNative.snapshot().state,'failed');
assert.equal(f.d.querySelector('.vocab-back'),null);
assert.ok(f.d.querySelector('[role="alert"]').textContent.includes('SHA'));
assert.ok(f.d.getElementById('native-rating'));
f.close();
""", result=result)

    def run_native(self, code, bundle=None, *, result=None, variants=()):
        result = result or self.native(bundle)
        front, back = _render_note(result['note'])
        media = dict(result['media']); rendered = []
        for variant in variants:
            q, a = _render_note(variant['note']); rendered.append({'front': q, 'back': a})
            for name, raw in variant['media'].items():
                self.assertTrue(name not in media or media[name] == raw)
                media[name] = raw
        payload = {'front': front, 'back': back, 'variants': rendered,
                   'media': {k: v.decode() for k, v in media.items()}}
        script = r"""
const assert=require('node:assert/strict'),fs=require('fs'),crypto=require('crypto');
const {JSDOM,VirtualConsole}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const liveDoms=new Set();
const wait=async fn=>{const end=Date.now()+3000;while(!fn()){if(Date.now()>end)throw Error('timeout');await new Promise(r=>setTimeout(r,2));}};
async function boot(side='back',options={}){
 const requests=[],errors=[],held=[];let holding=!!options.hold;
 const v=new VirtualConsole();v.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM('<!doctype html><html><head><style id="anki-bridge">bridge</style></head><body class="card"><div id="qa">'+input[side]+'</div><button id="native-rating">native rating</button></body></html>',{url:'file:///anki/media/card.html',runScripts:'dangerously',virtualConsole:v,beforeParse(w){w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w.crypto,'subtle',{value:crypto.webcrypto.subtle});w.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};}});
 liveDoms.add(dom);const w=dom.window,d=w.document,append=w.Element.prototype.append;
 w.Element.prototype.append=function(...nodes){const value=Reflect.apply(append,this,nodes);for(const node of nodes)if(this===d.head&&node.tagName==='SCRIPT'&&node.src){const name=new URL(node.src).pathname.split('/').pop();requests.push(name);const run=()=>{if(!(name in input.media)){node.dispatchEvent(new w.Event('error'));return;}w.eval(input.media[name]);node.dispatchEvent(new w.Event('load'));};if(holding)held.push(run);else queueMicrotask(run);}return value;};
 const bootstrap=d.querySelector('script[src]').getAttribute('src');w.eval(input.media[bootstrap]);
 if(!options.allowLoading)await wait(()=>w.StudyCompiledNative?.snapshot()?.state==='ready'||w.StudyCompiledNative?.snapshot()?.state==='failed');
 if(!options.allowFailure&&!options.allowLoading)assert.equal(w.StudyCompiledNative.snapshot().state,'ready',d.body.textContent+' '+errors.join('\n'));
 return{w,d,requests,errors,hold(){holding=true;},unhold(){holding=false;},release(){for(const run of held.splice(0))run();},async switchSide(next,variant=null){d.getElementById('qa').innerHTML=(variant===null?input:input.variants[variant])[next];await w.StudyCompiledNative.mount(d.querySelector('[data-study-native-owner]'));},close(){w.StudyCompiledNative.dispose();w.close();}};
}
(async()=>{CODE})().catch(e=>{console.error(e);process.exitCode=1}).finally(()=>{for(const dom of liveDoms){dom.window.StudyCompiledNative?.dispose();dom.window.close();}});
""".replace('CODE', code)
        completed = subprocess.run(['node', '-e', script], cwd=ROOT, input=json.dumps(payload),
                                   text=True, capture_output=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        return completed.stdout


if __name__ == '__main__':
    unittest.main()
