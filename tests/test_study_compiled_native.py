"""Native delivery adapters: source fields and host identity stay separate."""
import copy
import base64
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
    def bundle(self, original=ORIGINAL, with_history=False, shared_history=False, initial_history=False):
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
        if initial_history:
            text = '初始完整审核中文😀\n原字段 e\u0301 <source>'
            pin = sha(text); name = '_af_' + pin[:24] + '.js'
            extra[name] = ('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};window.AnkiFinalHistoryEvidence[' + json.dumps(pin) + ']=' + json.dumps(text, ensure_ascii=False) + ';').encode()
            initial = '<section class="sf-report"><article class="sf-example" data-study-compiled-key="initial"><details><summary>初始审核</summary><pre data-native-history-media="' + name + '" data-native-history-sha="' + pin + '">原占位</pre></details></article></section>'
            back = back.replace(payload, initial + payload)
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
            # The current AST emits one shared AF table. Legacy fixture bundles
            # deliberately reconstruct their old inline evidence representation.
            history_back = back.replace(initial, '') if initial_history else back
            completed = subprocess.run(['node', '-e', "const fs=require('fs'),a=require('./anki_pipeline/compiled/profile-ast.cjs'),v=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(a.buildHistorySlots({...v,index:a.indexHTML(v.html)})));"],
                cwd=ROOT, input=json.dumps({'html': history_back, 'moduleCode': module.decode(),
                    'module': {'sha256': prepared_pin, 'original_sha256': original},
                    'sourceArtifactSha256': bindings['sourceArtifactSha256'], 'parts': parts, 'evidence': evidence}),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            history = json.loads(completed.stdout)
            profile['historySlots'] = history['slots']
            if shared_history:
                profile.update(initialHistorySlots=[], initialHistoryText=history['initialHistoryText'])
            else:
                for slot in profile['historySlots']:
                    for part in slot['parts']:
                        for item in part['evidence']:
                            item['text'] = history['initialHistoryText'][item.pop('textKey')]
        if initial_history:
            profile.setdefault('initialHistorySlots', [])
            profile.setdefault('initialHistoryText', {})[pin] = text
            profile['nodeBindings'].append(dict(key='initial', rootKey='initial',
                region=dict(selector='.sf-report', ordinal=0, total=1, rootPath=[0]),
                relativePath=[], requiredAttrs=[['class', 'sf-example'], ['data-study-compiled-key', 'initial']],
                roles=['original-example'], tag='ARTICLE', namespace='http://www.w3.org/1999/xhtml',
                logicalRoot=dict(kind='occurrence', id=None), exactText='初始审核原占位'))
            profile['initialHistorySlots'].append(dict(rootKey='initial', relativePath=[0, 1], ownerPath=[0],
                requiredAttrs=[['data-native-history-media', name], ['data-native-history-sha', pin]],
                ownerAttrs=[], placeholder='原占位', media=name, sha256=pin, resourceSha256=sha(extra[name])))
        if shared_history or initial_history:
            runtime = (ROOT/'anki_pipeline/compiled/card-runtime.js').read_bytes()
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

    def test_dictionary_carrier_restores_the_original_profile_in_the_unchanged_native_host(self):
        from anki_pipeline.study_compiled_native import split_native_delivery_meta
        bundle=self.bundle();profile=json.loads(bundle['resources']['_profile.json'])
        audit='原审核😀 e\u0301 '+''.join(sha(str(index)) for index in range(1024))
        profile['transportFixture']=[audit,'中间',audit]
        raw=json.dumps(profile,ensure_ascii=False,separators=(',',':')).encode()
        bundle['resources']['_profile.json']=raw
        bundle['entry']['profile']['sha256']=sha(raw)
        bundle['entry']['anchors']['profileSha256']=sha(raw)
        result=self.native(bundle)
        descriptor=split_native_delivery_meta(result['note']['fields'][8])[1]
        alias=descriptor['transport']['_profile.json']['src']
        self.assertTrue(result['media'][alias].startswith(b'(function(v){'))
        self.run_native('''
const f=await boot();const snap=f.w.StudyCompiledNative.snapshot();
assert.equal(snap.ready,true);assert.equal(f.w.nativeEvents.length,1);
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
f.close();
''',bundle=bundle,result=result)

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
        self.assertEqual(actual['field_names'], note['field_names'])
        self.assertEqual(len(actual['fields']), len(note['fields']))
        from anki_pipeline.study_compiled_native import restore_native_source_fields
        self.assertEqual(restore_native_source_fields(actual), note['fields'])
        for name in ['id', 'note_id', 'guid', 'model_id']:
            self.assertEqual(actual[name], note[name])
        self.assertEqual(actual['model']['id'], note['model']['id'])
        self.assertEqual(actual['model']['flds'], note['model']['flds'])
        self.assertEqual((note, bundle), before)
        self.assertEqual(actual['content_mod'], 23)
        front, back = _render_note(actual)
        self.assertIn('data-answer="false"', front)
        self.assertIn('data-answer="true"', back)
        self.assertNotIn('{{FrontSide}}', actual['model']['tmpls'][0]['afmt'])
        self.assertFalse(back.startswith(front))
        self.assertNotIn('完整中文', actual['fields'][8], 'no second semantic DOM in descriptor')

    def test_meta_footer_keeps_the_exact_source_prefix_and_all_ten_fields_reversible(self):
        from anki_pipeline.study_compiled_native import project_native_note
        note = sample_note()
        note['fields'][8] = ' {"source":"中文😀 e\u0301 > \\\""}\r\n\t '
        before = copy.deepcopy(note)
        result = project_native_note(note, **self.bundle())['note']
        marker = '[[study-native-delivery:v3:'
        self.assertTrue(result['fields'][8].startswith(note['fields'][8] + marker))
        self.assertRegex(result['fields'][8][len(note['fields'][8]):], r'^\[\[study-native-delivery:v3:[A-Za-z0-9_-]+\]\]$')
        from anki_pipeline.study_compiled_native import split_native_delivery_meta, restore_native_source_fields
        original, descriptor = split_native_delivery_meta(result['fields'][8])
        self.assertEqual(original.encode(), note['fields'][8].encode())
        self.assertEqual(descriptor['id'], note['id'])
        self.assertEqual(restore_native_source_fields(result), note['fields'])
        self.assertEqual(result['fields'][:8] + result['fields'][9:], note['fields'][:8] + note['fields'][9:])
        self.assertEqual(result['payload'], {**note['payload'], 'mod': 23})
        self.assertEqual(note, before)

    def test_default_compatible_shell_keeps_descriptor_inert_until_native_mount(self):
        self.run_native(r"""
const parsed=new JSDOM(input.back,{runScripts:'dangerously'}).window.document;
assert.equal(parsed.querySelector('[data-study-native-delivery]'),null,'no live delivery script');
const source=parsed.querySelector('template[data-study-native-source-field]');
assert.ok(source,'existing Meta field is the only native transport container');
assert.equal(source.content.querySelectorAll('script').length,0);
assert.ok([...source.content.childNodes].every(node=>node.nodeType===3));
assert.ok(source.content.textContent.endsWith(']]'));
const f=await boot();
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('template[data-study-native-source-field]'),null,'source transport is retired with the shell');
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
assert.equal(f.d.getElementById('native-rating').textContent,'native rating');
f.close();
""")

    def test_editor_script_cleanup_keeps_meta_text_and_mounts_both_sides(self):
        from anki_pipeline.study_compiled_native import project_native_note, restore_native_source_fields
        note=sample_note();note['fields'][8]='必考词 Unit04 中文😀 e\u0301'
        result=project_native_note(note,**self.bundle())
        self.run_native(r"""
const editor=new JSDOM('<div id="editor">'+input.meta+'</div>').window.document.getElementById('editor');
for(const script of editor.querySelectorAll('script'))script.remove();
assert.equal(editor.textContent,input.meta,'editor HTML cleanup must preserve the complete text transport');
assert.ok(editor.textContent.includes('[[study-native-delivery:v3:'));
for(const side of ['front','back']){
 const document=new JSDOM(input[side]).window.document,source=document.querySelector('template[data-study-native-source-field]');
 source.innerHTML=editor.innerHTML;
 assert.equal(source.content.textContent,input.meta);
 assert.ok([...source.content.childNodes].every(node=>node.nodeType===3));
 input[side]=document.body.innerHTML;
}
const f=await boot('back');assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
await f.switchSide('front');assert.equal(f.w.StudyCompiledNative.snapshot().answer,false);
assert.deepEqual([...f.w.nativeEvents],[true,false]);f.close();
""",result=result)
        self.assertEqual(restore_native_source_fields(result['note']),note['fields'])

    def test_shared_transport_binder_is_pure_and_escapes_template_breakouts(self):
        from anki_pipeline.study_compiled_native import bind_native_delivery, split_native_delivery_meta
        projected = self.native()['note']
        _, descriptor = split_native_delivery_meta(projected['fields'][8])
        note = sample_note(); note['fields'][8] = 'original Meta 中文😀 >\r\n'
        descriptor['audit'] = '</template><script>window.nativeEscape=true</script> & 中文😀'
        before = copy.deepcopy((note, descriptor))
        bootstrap = next(name for name in self.native()['media'] if name.startswith('_study_native_bootstrap_'))
        result = bind_native_delivery(note, descriptor, bootstrap_name=bootstrap, model_mod=22, note_mod=23)
        self.assertEqual((note, descriptor), before)
        self.assertEqual(split_native_delivery_meta(result['fields'][8]), (note['fields'][8], descriptor))
        self.assertNotIn('</template>', result['fields'][8])
        self.assertEqual(result['field_names'], note['field_names'])
        self.assertEqual(result['model']['flds'], note['model']['flds'])
        runtime = self.native(); runtime['note'] = result
        self.run_native(r"""
const f=await boot();
assert.equal(f.w.nativeEscape,undefined);
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.body.textContent.includes('original Meta'),false);
f.close();
""", result=runtime)

    def test_numeric_resource_names_roundtrip_with_the_same_meta_canonical_order(self):
        for html_name,profile_name in [('2','1'),('10','2')]:
            bundle=self.bundle()
            bundle['resources'][html_name]=bundle['resources'].pop('_html.html')
            bundle['resources'][profile_name]=bundle['resources'].pop('_profile.json')
            bundle['entry']['html']['src']=html_name;bundle['entry']['profile']['src']=profile_name
            with self.subTest(names=(html_name,profile_name)):
                self.run_native(r"""
const f=await boot();
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
await f.switchSide('front');assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);f.close();
""",bundle=bundle)

    def test_meta_only_canonical_serializer_orders_nested_utf16_keys_without_changing_assets(self):
        from anki_pipeline.study_compiled_native import (bind_native_delivery,
            split_native_delivery_meta,native_delivery_json,_json)
        values={'2':'two','10':'ten','\ue000':'private','😀':'astral'}
        self.assertEqual(native_delivery_json(values),'{"10":"ten","2":"two","😀":"astral","\ue000":"private"}')
        self.assertEqual(_json({'2':'two','1':'one'}),'{"2":"two","1":"one"}',
                         'semantic asset JSON keeps its existing insertion order')
        result=self.native();_,descriptor=split_native_delivery_meta(result['note']['fields'][8])
        descriptor['audit']=[values,{'2':'two','1':'one'},[None,True,False,9007199254740991,-9007199254740991]]
        bootstrap=next(name for name in result['media'] if name.startswith('_study_native_bootstrap_'))
        result['note']=bind_native_delivery(sample_note(),descriptor,bootstrap_name=bootstrap,model_mod=22,note_mod=23)
        self.assertEqual(split_native_delivery_meta(result['note']['fields'][8])[1],descriptor)
        self.run_native(r"""
const f=await boot();assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');f.close();
""",result=result)

    def test_meta_serializer_rejects_unsupported_numbers_before_binding(self):
        from anki_pipeline.study_compiled_native import bind_native_delivery,split_native_delivery_meta
        result=self.native();_,descriptor=split_native_delivery_meta(result['note']['fields'][8])
        bootstrap=next(name for name in result['media'] if name.startswith('_study_native_bootstrap_'))
        for value in [9007199254740992,-9007199254740992,1.0,1.5,float('inf'),float('nan')]:
            changed=copy.deepcopy(descriptor);changed['unsupported']=[value]
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'safe integers'):
                bind_native_delivery(sample_note(),changed,bootstrap_name=bootstrap,model_mod=22,note_mod=23)

    def test_meta_transport_rejects_unsafe_source_duplicates_and_invalid_recovery(self):
        from anki_pipeline.study_compiled_native import (bind_native_delivery,
            split_native_delivery_meta, restore_native_source_fields)
        projected = self.native()['note']
        source, descriptor = split_native_delivery_meta(projected['fields'][8])
        bootstrap = next(name for name in self.native()['media'] if name.startswith('_study_native_bootstrap_'))
        for meta in ['unsafe <source>', 'unsafe &amp;', projected['fields'][8],
                     'reserved [[study-native-delivery:v4:anything]]']:
            note = sample_note(); note['fields'][8] = meta
            with self.subTest(meta=meta), self.assertRaisesRegex(ValueError, 'Meta|footer'):
                bind_native_delivery(note, descriptor, bootstrap_name=bootstrap, model_mod=22, note_mod=23)
        for meta in [source, projected['fields'][8] + ' ', projected['fields'][8] * 2,
                     projected['fields'][8].replace(':v3:', ':v4:'),
                     projected['fields'][8][:-2]+'=]]']:
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                split_native_delivery_meta(meta)
        wrong = copy.deepcopy(projected); wrong['field_names'][8] = 'Other'
        with self.assertRaisesRegex(ValueError, 'Meta'):
            restore_native_source_fields(wrong)
        for change in [lambda n: n['field_names'].append('StudyCompiledDelivery'),
                       lambda n: n['model']['flds'][8].update(name='Other')]:
            wrong = sample_note(); change(wrong)
            with self.assertRaisesRegex(ValueError, 'field|Meta'):
                bind_native_delivery(wrong, descriptor, bootstrap_name=bootstrap, model_mod=22, note_mod=23)
        with self.assertRaisesRegex(ValueError, 'version'):
            bind_native_delivery(sample_note(), descriptor, bootstrap_name=bootstrap, model_mod=19, note_mod=23)

    def test_native_template_delivery_rejects_multiple_footers_and_legacy_ambiguity(self):
        for duplicate in ['footer', 'template', 'legacy', 'version']:
            result = self.native()
            if duplicate == 'footer':
                result['note']['fields'][8] *= 2
            elif duplicate == 'version':
                result['note']['fields'][8] = result['note']['fields'][8].replace(':v3:', ':v4:')
            else:
                for template in result['note']['model']['tmpls']:
                    for side in ['qfmt', 'afmt']:
                        extra = ('<template data-study-native-source-field>{{Meta}}</template>' if duplicate == 'template'
                                 else '<script type="application/json" data-study-native-delivery>{}</script>')
                        template[side] = template[side].replace('<p role="status"', extra + '<p role="status"')
            with self.subTest(duplicate=duplicate):
                self.run_native(r"""
const f=await boot('back',{allowFailure:true});
assert.equal(f.w.StudyCompiledNative.snapshot().state,'failed');
assert.equal(f.d.querySelector('.vocab-back'),null);
assert.ok(f.d.querySelector('[role="alert"]'));
assert.ok(f.d.getElementById('native-rating'));
f.close();
""", result=result)

    def invalid_text_deliveries(self,result):
        from anki_pipeline.study_compiled_native import split_native_delivery_meta
        meta=result['note']['fields'][8];source,descriptor=split_native_delivery_meta(meta)
        raw=json.dumps(descriptor,ensure_ascii=False,separators=(',',':')).encode()
        def token(value):
            return source+'[[study-native-delivery:v3:'+base64.urlsafe_b64encode(value).decode().rstrip('=')+']]'
        old_script=source+'<script type="application/json" data-study-native-delivery="v2">'+raw.decode().replace('<','\\u003c')+'</script>'
        return {
            'missing':source,'suffix':meta+' ','duplicate':meta+meta,
            'reserved-prefix':'[[study-native-delivery:v9:other]]'+meta,
            'version':meta.replace(':v3:',':v4:'),'padding':meta[:-2]+'=]]',
            'invalid-alphabet':meta[:-2]+'!]]','invalid-length':source+'[[study-native-delivery:v3:A]]',
            'noncanonical-base64':source+'[[study-native-delivery:v3:e31]]',
            'invalid-utf8':token(b'\xff'),'overlong-utf8':token(b'\xc0\xaf'),
            'truncated-utf8':token(b'\xe2\x82'),'bom':token(b'\xef\xbb\xbf'+raw),
            'noncanonical-json':token(b' '+raw),'duplicate-json-key':token(b'{"id":"duplicate",'+raw[1:]),
            'not-object':token(b'[]'),'script-footer':old_script,
            'unsafe-positive-number':token(raw[:-1]+b',"zz_unsupported":9007199254740992}'),
            'unsafe-negative-number':token(raw[:-1]+b',"zz_unsupported":-9007199254740992}'),
            'unsupported-fraction':token(raw[:-1]+b',"zz_unsupported":1.5}'),
            'unsupported-float-format':token(raw[:-1]+b',"zz_unsupported":1.0}'),
            'lone-surrogate':token(b'{"bad":"\\ud800",'+raw[1:]),
            'comment':meta+'<!-- editor -->','element':source+'<span>text</span>'+meta,
        }

    def test_text_delivery_recovery_rejects_invalid_ambiguous_and_noncanonical_tokens(self):
        from anki_pipeline.study_compiled_native import split_native_delivery_meta
        result=self.native()
        for label,meta in self.invalid_text_deliveries(result).items():
            with self.subTest(label=label),self.assertRaises(ValueError):
                split_native_delivery_meta(meta)

    def test_text_delivery_runtime_rejects_invalid_ambiguous_and_noncanonical_tokens(self):
        result=self.native();variants=[]
        for meta in self.invalid_text_deliveries(result).values():
            variant=copy.deepcopy(result);variant['note']['fields'][8]=meta;variants.append(variant)
        self.run_native(r"""
const candidates=[input.back,...input.variants.map(value=>value.back)];
for(const back of candidates){
 input.back=back;const f=await boot('back',{allowFailure:true});
 assert.equal(f.w.StudyCompiledNative.snapshot().state,'failed');
 assert.equal(f.requests.length,0,'invalid text transport cannot load semantic assets');
 assert.equal(f.d.querySelector('.vocab-back'),null);assert.ok(f.d.querySelector('[role="alert"]'));
 assert.ok(f.d.getElementById('native-rating'));f.close();
}
""",result=variants[0],variants=variants[1:])

    def test_legacy_delivery_script_still_mounts_with_the_current_bootstrap(self):
        from anki_pipeline.study_compiled_native import split_native_delivery_meta
        result = self.native(); note = result['note']
        note['fields'][8], descriptor = split_native_delivery_meta(note['fields'][8])
        note['field_names'].append('StudyCompiledDelivery')
        note['fields'].append(json.dumps(descriptor, ensure_ascii=False).replace('<', '\\u003c'))
        for template in note['model']['tmpls']:
            for side in ['qfmt', 'afmt']:
                template[side] = template[side].replace('<template data-study-native-source-field>{{Meta}}</template>',
                    '<script type="application/json" data-study-native-delivery>{{StudyCompiledDelivery}}</script>')
        self.run_native(r"""
const f=await boot();
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('.vocab-back').textContent,'完整中文😀');
f.close();
""", result=result)

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

    def test_current_binder_uses_unchanged_legacy_profile_in_native_host(self):
        bundle = self.bundle(with_history=True)
        previous_profile = bundle['resources']['_profile.json']
        current = (ROOT / 'anki_pipeline/compiled/card-runtime.js').read_bytes()
        bundle['resources']['_runtime.js'] = current
        bundle['runtime']['sha256'] = sha(current)
        self.run_native(r"""
const f=await boot();
assert.equal(f.w.StudyCompiledNative.snapshot().ready,true);
assert.equal(f.d.querySelector('.anki-final-reviewed-data').dataset.nativeState,'ready');
assert.equal(f.d.getElementById('native-rating').textContent,'native rating');
f.close();
""", bundle=bundle)
        self.assertEqual(bundle['resources']['_profile.json'], previous_profile)

    def test_standalone_front_does_not_load_back_html_profile_or_binder(self):
        self.run_native(r"""
const f=await boot('front');
assert.equal(f.w.StudyCompiledNative.snapshot().answer,false);
assert.deepEqual([...f.w.nativeEvents],[false]);
assert.equal(f.w.AnkiCompiledCardRuntime,undefined);
const text=new JSDOM(input.front).window.document.querySelector('template[data-study-native-source-field]').content.textContent;
const descriptor=JSON.parse(Buffer.from(text.split('[[study-native-delivery:v3:')[1].slice(0,-2),'base64url').toString('utf8'));
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

    def test_shared_as_evidence_and_initial_closed_af_use_the_same_native_carriers(self):
        bundle = self.bundle(with_history=True, shared_history=True, initial_history=True)
        self.run_native(r"""
const f=await boot('back');
const initial=f.d.querySelector('[data-study-compiled-key="initial"] pre');
assert.equal(initial.textContent,'原占位','closed original placeholder is retained');
initial.parentElement.open=true;initial.parentElement.dispatchEvent(new f.w.Event('toggle'));
await wait(()=>initial.dataset.nativeHistoryReady==='true');
assert.equal(initial.textContent,'初始完整审核中文😀\n原字段 e\u0301 <source>');
for(const detail of f.d.querySelectorAll('details.sf-ownership-history')){
 detail.open=true;detail.dispatchEvent(new f.w.Event('toggle'));
 await wait(()=>detail.querySelector('script.as-manifest').dataset.asState==='ready');
 const pre=detail.querySelector('pre');pre.parentElement.open=true;pre.parentElement.dispatchEvent(new f.w.Event('toggle'));
 await wait(()=>pre.dataset.nativeHistoryReady==='true');assert.ok(pre.textContent.startsWith('审核完整中文😀'));
}
const handle=f.w.AnkiCompiledCardRuntime.install(f.d,f.w.StudyCompiledProfileBridge.get(f.d));
assert.equal(handle.stats().invalid,null);assert.equal(handle.refresh(),true);
assert.equal(f.d.querySelectorAll('pre[data-native-history-ready="true"]').length,3);
assert.ok(f.requests.every(n=>n.startsWith('_study_native_')));
f.close();
""", bundle=bundle)

    def test_shared_native_history_rejects_missing_conflicting_or_changed_sources(self):
        for change in [
            lambda p: p.pop('initialHistoryText'),
            lambda p: p.pop('initialHistorySlots'),
            lambda p: p.update(initialHistoryText=[]),
            lambda p: p['initialHistoryText'].update({next(iter(p['initialHistoryText'])): 'wrong'}),
            lambda p: p['initialHistoryText'].update({sha('unused'): 'unused'}),
            lambda p: p['historySlots'][0]['parts'][0]['evidence'][0].update(text='conflicting'),
            lambda p: p['historySlots'][0]['parts'][0]['evidence'][0].update(textKey='0'*64),
            lambda p: p['initialHistorySlots'][0].update(textKey='0'*64),
            lambda p: p['initialHistorySlots'][0].update(resourceSha256='0'*64),
        ]:
            with self.subTest(change=change):
                bundle=self.bundle(with_history=True, shared_history=True, initial_history=True)
                profile=json.loads(bundle['resources']['_profile.json']);change(profile)
                raw=json.dumps(profile,separators=(',', ':')).encode();bundle['resources']['_profile.json']=raw
                bundle['entry']['profile']['sha256']=sha(raw);bundle['entry']['anchors']['profileSha256']=sha(raw)
                with self.assertRaisesRegex(ValueError, 'history'):
                    self.native(bundle)

    def test_initial_closed_af_is_packaged_without_any_as_disclosure(self):
        self.run_native(r"""
const f=await boot('back'),pre=f.d.querySelector('pre[data-native-history-media]');
assert.equal(f.d.querySelectorAll('script.as-manifest').length,0);
assert.equal(pre.textContent,'原占位');
pre.parentElement.open=true;pre.parentElement.dispatchEvent(new f.w.Event('toggle'));
await wait(()=>pre.dataset.nativeHistoryReady==='true');
assert.equal(pre.textContent,'初始完整审核中文😀\n原字段 e\u0301 <source>');
assert.equal(f.w.AnkiCompiledCardRuntime.install(f.d,f.w.StudyCompiledProfileBridge.get(f.d)).stats().invalid,null);
f.close();
""", bundle=self.bundle(initial_history=True))

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
        from anki_pipeline.study_compiled_native import split_native_delivery_meta
        _, descriptor = split_native_delivery_meta(result['note']['fields'][8])
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
                   'meta': result['note']['fields'][result['note']['field_names'].index('Meta')],
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
