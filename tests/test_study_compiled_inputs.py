import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled as compiler
from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materializer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CompiledInputTests(unittest.TestCase):
    def test_derived_html_has_separate_bound_without_widening_other_inputs(self):
        path = self.root / 'derived.html'
        raw = b'0123456789abcdef'
        path.write_bytes(raw)
        value = {'path': path.name, 'sha256': sha(raw), 'bytes': len(raw)}
        with patch.object(compiler, '_LIMIT', 8), patch.object(compiler, '_DERIVED_HTML_LIMIT', 32):
            self.assertEqual(compiler._semantic_child(self.root, {'final_html': value}, 'final_html'), raw)
            with self.assertRaisesRegex(ValueError, 'invalid semantic result descriptor'):
                compiler._semantic_child(self.root, {'metadata': value}, 'metadata')
            with self.assertRaisesRegex(ValueError, 'byte count differs'):
                compiler._semantic_child(self.root, {'final_html': {**value, 'bytes': 15}}, 'final_html')
            path.write_bytes(raw + b'x')
            with self.assertRaisesRegex(ValueError, 'source bytes differ'):
                compiler._semantic_child(self.root, {'final_html': value}, 'final_html')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('cards', 'media', 'evidence'):
            (self.root / name).mkdir()
        original = b'window.fixtureNative = true;'
        self.native_pin = sha(original)
        self.prepared = original + b'\n// prepared test capability\n'
        (self.root / 'media/native.js').write_bytes(original)
        (self.root / 'evidence/prepared.js').write_bytes(self.prepared)
        self.policy = {'external': {'native.js': self.native_pin}, 'inline': []}
        front = '<!doctype html><html><head></head><body>front</body></html>'
        back = ('<!doctype html><html><head><base href="../media/"></head>'
                '<body><div>完整原文 中文</div><script src="native.js"></script></body></html>')
        payload = json.dumps([front, back], ensure_ascii=False).replace('<', '\\u003c')
        raw = web.card_shell(payload, '../media/').encode()
        self.wrapper = self.root / 'cards/source.html'
        self.wrapper.write_bytes(raw)
        media = materializer.ReadOnlyMedia(self.root / 'media')
        self.value = {'schema': 'study-prepared-card.v1',
                      'source_wrapper_sha256': sha(raw),
                      'source_payload_sha256': sha(payload.encode()),
                      'sides': [materializer.materialize_side(side, media) for side in (front, back)],
                      'modules': {self.native_pin: {'original_sha256': self.native_pin,
                                  'src': 'evidence/prepared.js', 'sha256': sha(self.prepared)}}}
        self.artifact = self.root / 'evidence/card.json'
        self.save_artifact()
        self.output = self.root / 'new-inputs'
        self.addCleanup(patch.stopall)
        patch.object(materializer, 'AUDITED_NATIVE_MODULES', frozenset({self.native_pin})).start()
        patch.object(materializer, 'prepare_native_module', return_value=self.prepared.decode()).start()

    def save_artifact(self):
        self.artifact.write_text(json.dumps(self.value, ensure_ascii=False))

    def build(self):
        return compiler.build_semantic_request(
            self.root,
            {'path': 'cards/source.html', 'sha256': sha(self.wrapper.read_bytes())},
            {'path': 'evidence/card.json', 'sha256': sha(self.artifact.read_bytes())},
            self.output, policy=self.policy, source_url='https://study.invalid/book/index.html')

    def test_frozen_request_preserves_source_and_copies_only_referenced_resources(self):
        (self.root / 'media/unrelated.mp3').write_bytes(b'untouched audio')
        before = self.wrapper.read_bytes(), self.artifact.read_bytes()
        result = self.build()
        request = json.loads((self.output / 'request.json').read_text())
        self.assertEqual(request['schema'], 'study-compiled-semantic-request.v1')
        self.assertEqual(request['source']['wrapper_sha256'], self.value['source_wrapper_sha256'])
        self.assertEqual(set(request['resources']), {'https://study.invalid/book/media/native.js',
                                                   'https://study.invalid/book/evidence/prepared.js'})
        for row in [request['artifact'], request['module'], request['helpers'], *request['resources'].values()]:
            self.assertEqual(sha(Path(row['path']).read_bytes()), row['sha256'])
        self.assertEqual(before, (self.wrapper.read_bytes(), self.artifact.read_bytes()))
        self.assertNotIn(b'untouched audio', [p.read_bytes() for p in self.output.iterdir() if p.is_file()])
        self.assertTrue(result['raw_wrapper_and_payload_verified'])

    def test_changed_source_payload_or_registry_is_rejected_before_output(self):
        for mutate in ('payload', 'expanded', 'registry'):
            with self.subTest(mutate=mutate):
                original = json.loads(json.dumps(self.value))
                if mutate == 'payload': self.value['source_payload_sha256'] = '0' * 64
                elif mutate == 'expanded': self.value['sides'][1]['html'] += '<p>other</p>'
                else: self.value['sides'][1]['registry']['0' * 64] = 'changed source'
                self.save_artifact()
                with self.assertRaises(ValueError): self.build()
                self.assertFalse(self.output.exists())
                self.value = original
                self.save_artifact()

    def test_prepared_module_must_be_exact_derivative_of_approved_original(self):
        (self.root / 'media/native.js').write_text('window.changedOriginal=true;')
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())

    def test_original_initial_AF_is_in_the_explicit_semantic_resource_snapshot(self):
        evidence = '用户保留的完整原始审核依据'
        pin = sha(evidence.encode())
        name = '_af_' + pin[:24] + '.js'
        raw = ('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};'
               'window.AnkiFinalHistoryEvidence["' + pin + '"]=' + json.dumps(evidence, ensure_ascii=False) + ';').encode()
        (self.root / 'media' / name).write_bytes(raw)
        sides = json.loads(web.card_payload(self.wrapper.read_bytes()))
        sides[1] = sides[1].replace('<body>', '<body><pre data-native-history-media="' + name + '" data-native-history-sha="' + pin + '">点击加载依据</pre>')
        payload = json.dumps(sides, ensure_ascii=False).replace('<', '\\u003c')
        self.wrapper.write_bytes(web.card_shell(payload, '../media/').encode())
        self.value.update(source_wrapper_sha256=sha(self.wrapper.read_bytes()), source_payload_sha256=sha(payload.encode()),
                          sides=[materializer.materialize_side(side, materializer.ReadOnlyMedia(self.root / 'media')) for side in sides])
        self.save_artifact()
        self.build()
        request = json.loads((self.output / 'request.json').read_bytes())
        descriptor = request['resources']['https://study.invalid/book/media/' + name]
        self.assertEqual(Path(descriptor['path']).read_bytes(), raw)
        self.assertEqual(descriptor['sha256'], sha(raw))

    def style_source(self, css=b'ol.examples > li.example-card { color: #123; }', name=None):
        name = name or '_study_' + sha(css) + '.css'
        (self.root / 'media' / name).write_bytes(css)
        sides = json.loads(web.card_payload(self.wrapper.read_bytes()))
        sides[1] = sides[1].replace('<head>', '<head><link rel="stylesheet" href="' + name + '">')
        payload = json.dumps(sides, ensure_ascii=False).replace('<', '\\u003c')
        self.wrapper.write_bytes(web.card_shell(payload, '../media/').encode())
        self.value.update(source_wrapper_sha256=sha(self.wrapper.read_bytes()), source_payload_sha256=sha(payload.encode()),
                          sides=[materializer.materialize_side(side, materializer.ReadOnlyMedia(self.root / 'media')) for side in sides])
        self.save_artifact()
        return name

    def test_source_stylesheet_is_frozen_under_its_original_content_address(self):
        css = b'ol.examples > li.example-card { color: #123; }'
        name = self.style_source(css)
        self.build()
        request = json.loads((self.output / 'request.json').read_bytes())
        descriptor = request['resources']['https://study.invalid/book/media/' + name]
        self.assertEqual(Path(descriptor['path']).read_bytes(), css)
        self.assertEqual(descriptor['sha256'], sha(css))

    def test_mismatched_or_unaddressed_stylesheet_is_rejected_before_output(self):
        self.style_source(name='_study_' + '0' * 64 + '.css')
        with self.assertRaisesRegex(ValueError, 'pin|bytes'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_duplicate_source_attribute_is_rejected_before_DOM_discards_it(self):
        sides = json.loads(web.card_payload(self.wrapper.read_bytes()))
        sides[1] = sides[1].replace('<div>', '<div class="index-tag" class="other">')
        payload = json.dumps(sides, ensure_ascii=False).replace('<', '\\u003c')
        self.wrapper.write_bytes(web.card_shell(payload, '../media/').encode())
        self.value.update(source_wrapper_sha256=sha(self.wrapper.read_bytes()), source_payload_sha256=sha(payload.encode()),
                          sides=[materializer.materialize_side(side, materializer.ReadOnlyMedia(self.root / 'media')) for side in sides])
        self.save_artifact()
        with self.assertRaisesRegex(ValueError, 'duplicate source HTML'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'owner.txt'
        sentinel.write_text('external change')
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(sentinel.read_text(), 'external change')

    def profile_source(self, *, history=False):
        raw_side, raw_index = '{"source":"完整原文"}', '{"source":"原索引"}'
        registry = {sha(text.encode()): text for text in (raw_side, raw_index)}
        side = self.value['sides'][1]
        side['registry'] = registry
        side['proof']['registry_pins'] = sorted(registry)
        self.save_artifact()
        receipt = self.build()
        request = json.loads(Path(receipt['request']['path']).read_bytes())
        self.profile_output = self.root / 'profile-inputs'
        result = self.root / 'semantic-result'
        result.mkdir()
        def record(name, raw):
            (result / name).write_bytes(raw)
            return {'path': name, 'sha256': sha(raw), 'bytes': len(raw)}
        def item(name, value):
            return record(name, json.dumps(value, ensure_ascii=False).encode())
        history_text = ''
        self.history_raw = None
        if history:
            evidence = '完整原审核依据\n原始版本'
            evidence_pin = sha(evidence.encode())
            evidence_name = '_af_' + evidence_pin[:24] + '.js'
            self.history_raw = ('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};'
                'window.AnkiFinalHistoryEvidence["' + evidence_pin + '"]=' + json.dumps(evidence, ensure_ascii=False) + ';').encode()
            (self.root / 'media' / evidence_name).write_bytes(self.history_raw)
            part = '<pre data-native-history-media="' + evidence_name + '" data-native-history-sha="' + evidence_pin + '"></pre>'
            self.part_pin = sha(part.encode())
            part_name = '_as_' + self.part_pin[:24] + '.js'
            (self.root / 'media' / part_name).write_text('window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets["' + self.part_pin + '"]=' + json.dumps(part) + ';')
            manifest = {'schema': 'anki-slim-segments.v1', 'parts': [{'src': part_name, 'sha256': self.part_pin, 'count': 1}], 'total': 1}
            history_text = '<script class="as-manifest" type="application/json">' + json.dumps(manifest) + '</script>'
        body = ('<script class="anki-final-reviewed-data" type="application/json" data-as-sha="' + sha(raw_side.encode())
                + '" data-as-index-sha="' + sha(raw_index.encode()) + '"></script>' + history_text)
        metadata = item('metadata.json', {'schema': 'fixture-metadata'})
        proof = {'schema': 'study-compiled-semantic-source.v1', 'request_sha256': receipt['request']['sha256'],
                 'artifact_sha256': request['artifact']['sha256'], 'helpers_sha256': request['helpers']['sha256'],
                 'source_wrapper_sha256': self.value['source_wrapper_sha256'], 'source_payload_sha256': self.value['source_payload_sha256'],
                 'source_side_sha256': side['proof']['source_sha256'], 'expanded_side_sha256': side['proof']['expanded_sha256'],
                 'source_side_utf8_bytes': side['proof']['source_bytes'], 'expanded_side_utf8_bytes': side['proof']['expanded_bytes'],
                 'original_module_sha256': self.native_pin, 'prepared_module_sha256': sha(self.prepared),
                 'registry_pins': sorted(registry), 'metadata_sha256': metadata['sha256']}
        report = {'schema': 'study-compiled-semantic-result.v1', 'real_native_ready': True, 'pure_semantic_only': True,
                  'authored_startup_executed': False, 'final_html': record('delivery.html', body.encode()),
                  'bindings': item('draft.json', {'schema': 'study-canonical-interaction-bindings.draft.v1', 'source_artifact_sha256': request['artifact']['sha256']}),
                  'source_proof': item('source-proof.json', proof), 'metadata': metadata,
                  'reconciliation': item('reconciliation.json', {'closed_history_manifests_preserved': int(history)}),
                  'capture_inverse': item('inverse.json', {})}
        self.report_path = result / 'report.json'
        self.report_path.write_text(json.dumps(report))
        self.semantic_request = receipt['request']
        self.report_descriptor = {'path': str(self.report_path), 'sha256': sha(self.report_path.read_bytes())}
        # Synthetic source is scoped to this unit test. Real reader and residual
        # source capability bytes are exercised by the actual-card integration.
        patch.object(compiler, '_DELEGATES', {'readerDelegateSha256': (b'window.fixtureNative', len(b'window.fixtureNative = true;'), self.native_pin),
                                           'residualListenerSha256': (b'window.fixtureNative', len(b'window.fixtureNative = true;'), self.native_pin)}, create=True).start()
        return report

    def profile_build(self, *, media=None):
        return compiler.build_profile_request(self.semantic_request, self.report_descriptor, self.profile_output, media=media)

    def test_profile_rejects_original_numbering_without_preparation_proof(self):
        report = self.profile_source()
        request_path = Path(self.semantic_request['path'])
        request = json.loads(request_path.read_bytes())
        request['policy']['external']['numbering.js'] = '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1'
        request_path.write_text(json.dumps(request))
        self.semantic_request['sha256'] = sha(request_path.read_bytes())
        proof_path = self.report_path.parent / report['source_proof']['path']
        proof = json.loads(proof_path.read_bytes())
        proof['request_sha256'] = self.semantic_request['sha256']
        proof_path.write_text(json.dumps(proof))
        report['source_proof'].update(sha256=sha(proof_path.read_bytes()), bytes=proof_path.stat().st_size)
        self.report_path.write_text(json.dumps(report))
        self.report_descriptor['sha256'] = sha(self.report_path.read_bytes())
        with self.assertRaisesRegex(ValueError, 'numbering requires its initial'):
            self.profile_build()
        self.assertFalse(self.profile_output.exists())

    def test_profile_request_binds_actual_producer_and_shared_runtime(self):
        report = self.profile_source()
        receipt = self.profile_build()
        request = json.loads(Path(receipt['request']['path']).read_bytes())
        header = json.loads(Path(request['bindings']['path']).read_bytes())
        self.assertEqual(header['producerInputSha256'], report['bindings']['sha256'])
        self.assertEqual(header['derivedHTMLSha256'], report['final_html']['sha256'])
        self.assertEqual(header['originalModuleSha256'], self.native_pin)
        self.assertEqual(header['frameRuntimeSha256'], materializer.digest(materializer.PREPARED_FRAME_RUNTIME))
        self.assertEqual(header['frameHTMLSha256'], materializer.digest(materializer.prepared_frame_html()))
        self.assertEqual(len(header), 17)
        self.assertNotIn('history', request)

    def test_profile_rejects_rebound_or_changed_outputs_before_publication(self):
        self.profile_source()
        report = json.loads(self.report_path.read_bytes())
        target = self.report_path.parent / report['source_proof']['path']
        original = target.read_bytes()
        proof = json.loads(original)
        proof['request_sha256'] = '0' * 64
        target.write_text(json.dumps(proof))
        report['source_proof'].update(sha256=sha(target.read_bytes()), bytes=target.stat().st_size)
        self.report_path.write_text(json.dumps(report))
        self.report_descriptor['sha256'] = sha(self.report_path.read_bytes())
        with self.assertRaises(ValueError): self.profile_build()
        self.assertFalse(self.profile_output.exists())

    def test_profile_rejects_byte_corruption_and_keeps_existing_output(self):
        report = self.profile_source()
        delivery = self.report_path.parent / report['final_html']['path']
        original = delivery.read_bytes()
        delivery.write_bytes(original + b'changed after semantic generation')
        with self.assertRaises(ValueError): self.profile_build()
        self.assertFalse(self.profile_output.exists())
        delivery.write_bytes(original)
        self.profile_output.mkdir()
        sentinel = self.profile_output / 'owner.txt'
        sentinel.write_text('existing output must survive')
        with self.assertRaises(FileExistsError): self.profile_build()
        self.assertEqual(sentinel.read_text(), 'existing output must survive')

    def test_profile_freezes_exact_closed_history_and_rejects_absent_media(self):
        self.profile_source(history=True)
        with self.assertRaises(ValueError): self.profile_build()
        self.assertFalse(self.profile_output.exists())
        self.profile_build(media=materializer.ReadOnlyMedia(self.root / 'media'))
        request = json.loads((self.profile_output / 'request.json').read_bytes())
        history = request['history']
        self.assertEqual(history['source_request'], self.semantic_request)
        part = history['parts'][self.part_pin]
        self.assertEqual(sha(Path(part['path']).read_bytes()), self.part_pin)
        self.assertEqual(len(history['evidence']), 1)
        entry = next(iter(history['evidence'].values()))
        self.assertEqual(Path(entry['path']).read_bytes(), self.history_raw)
        self.assertEqual(entry['sha256'], sha(self.history_raw))

    def test_profile_rejects_changed_original_history_before_output(self):
        self.profile_source(history=True)
        name = next((self.root / 'media').glob('_af_*.js'))
        name.write_bytes(self.history_raw.replace('完整'.encode(), '变更'.encode()))
        with self.assertRaises(ValueError): self.profile_build(media=self.root / 'media')
        self.assertFalse(self.profile_output.exists())

    def test_profile_rejects_uncovered_initial_AF_before_success(self):
        report = self.profile_source()
        delivery = self.report_path.parent / report['final_html']['path']
        original = delivery.read_bytes()
        for index, attrs in enumerate(('data-native-history-media="_af_123.js"',
                      'data-native-history-sha="' + '0' * 64 + '"',
                      'data-native-history-media="_af_123.js" data-native-history-sha="' + '0' * 64 + '"')):
            with self.subTest(attrs=attrs):
                self.profile_output = self.root / ('profile-inputs-' + str(index))
                delivery.write_bytes(original + ('<details><pre ' + attrs + '></pre></details>').encode())
                report['final_html'].update(sha256=sha(delivery.read_bytes()), bytes=delivery.stat().st_size)
                self.report_path.write_text(json.dumps(report))
                self.report_descriptor['sha256'] = sha(self.report_path.read_bytes())
                with self.assertRaisesRegex(ValueError, 'initial history evidence'):
                    self.profile_build()
                self.assertFalse(self.profile_output.exists())

    def test_profile_accepts_prepared_initial_and_part_owned_same_AF_source(self):
        report = self.profile_source(history=True)
        evidence_name = next((self.root / 'media').glob('_af_*.js')).name
        evidence_pin, text_json = materializer._HISTORY.fullmatch(self.history_raw.decode()).groups()
        text = json.loads(text_json)
        import html
        delivery = self.report_path.parent / report['final_html']['path']
        delivery.write_bytes(delivery.read_bytes() + ('<details><pre data-native-history-media="' + evidence_name + '" data-native-history-sha="' + evidence_pin + '" data-native-history-ready="true">' + html.escape(text) + '</pre></details>').encode())
        proof_path = self.report_path.parent / report['source_proof']['path']
        proof = json.loads(proof_path.read_bytes())
        proof['initial_history_evidence'] = [{'media': evidence_name, 'sha256': evidence_pin,
            'complete_text_sha256': sha(text.encode()), 'inverse_exact': True}]
        proof_path.write_text(json.dumps(proof))
        reconciliation_path = self.report_path.parent / report['reconciliation']['path']
        reconciliation_path.write_text(json.dumps({'closed_history_manifests_preserved': 1, 'initial_history_evidence': 1}))
        for key in ('final_html', 'source_proof', 'reconciliation'):
            path = self.report_path.parent / report[key]['path']
            report[key].update(sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
        self.report_path.write_text(json.dumps(report))
        self.report_descriptor['sha256'] = sha(self.report_path.read_bytes())
        receipt = self.profile_build(media=self.root / 'media')
        self.assertEqual(receipt['initial_history_evidence'], 1)
        self.assertEqual(receipt['closed_history_manifests'], 1)
        self.assertEqual(receipt['history_evidence'], 1)

    def test_profile_preserves_proven_closed_initial_AF_and_authenticates_full_resource(self):
        report = self.profile_source(history=True)
        name = next((self.root / 'media').glob('_af_*.js')).name
        pin, encoded = materializer._HISTORY.fullmatch(self.history_raw.decode()).groups()
        attrs = [['data-native-history-media', name], ['data-native-history-sha', pin], ['data-native-history-ready', 'false']]
        placeholder = '点击后保留原始完整审核😀'
        pre = '<pre' + ''.join(' ' + key + '="' + value + '"' for key, value in attrs) + '>' + placeholder + '</pre>'
        delivery = self.report_path.parent / report['final_html']['path']
        delivery.write_bytes(delivery.read_bytes() + ('<details>' + pre + '</details>').encode())
        proof_file = self.report_path.parent / report['source_proof']['path']
        proof = json.loads(proof_file.read_bytes())
        proof['initial_history_evidence'] = [{'ordinal': 0, 'preparation': 'deferred-closed', 'media': name,
            'sha256': pin, 'complete_text_sha256': pin, 'inverse_exact': True, 'original_text': placeholder,
            'original_text_sha256': sha(placeholder.encode()), 'original_attributes': attrs,
            'resource_sha256': sha(self.history_raw), 'original_pre_dom_sha256': sha(pre.encode()),
            'prepared_pre_dom_sha256': sha(pre.encode())}]
        proof_file.write_text(json.dumps(proof))
        reconciliation_file = self.report_path.parent / report['reconciliation']['path']
        reconciliation_file.write_text(json.dumps({'closed_history_manifests_preserved': 1, 'initial_history_evidence': 1}))
        for key in ('final_html', 'source_proof', 'reconciliation'):
            file = self.report_path.parent / report[key]['path']
            report[key].update(sha256=sha(file.read_bytes()), bytes=file.stat().st_size)
        self.report_path.write_text(json.dumps(report))
        self.report_descriptor['sha256'] = sha(self.report_path.read_bytes())
        receipt = self.profile_build(media=self.root / 'media')
        self.assertEqual(receipt['initial_history_evidence'], 1)
        self.assertEqual(receipt['history_evidence'], 1)
        self.assertIn(placeholder, delivery.read_text())
        self.assertNotIn(json.loads(encoded), delivery.read_text())


class InitialHistoryCompactionProofTests(unittest.TestCase):
    def snapshot(self, directory):
        from html import escape
        from anki_pipeline.study_compiled_history_compact import compact_semantic_result
        root = Path(directory)
        def store(name, value):
            raw = value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()
            file = root / name
            file.write_bytes(raw)
            return {'path': name, 'sha256': sha(raw), 'bytes': len(raw)}
        text, placeholder = '保留😀完整 & 审核原文', '原始占位😀'
        pin = sha(text.encode())
        attrs = [['data-native-history-media', '_af_' + pin[:24] + '.js'], ['data-native-history-sha', pin]]
        start = '<pre' + ''.join(' ' + key + '="' + value + '"' for key, value in attrs)
        original = start + '>' + placeholder + '</pre>'
        expanded = start + ' data-native-history-ready="true">' + escape(text, quote=False) + '</pre>'
        html = '<!DOCTYPE html><html><body>前😀<details>' + expanded + '</details></body></html>'
        request = store('request.json', {'schema': 'study-compiled-semantic-request.v1', 'artifact': {'sha256': 'c' * 64}})
        request = {key: value for key, value in {**request, 'path': str(root / request['path'])}.items() if key != 'bytes'}
        proof = {'request_sha256': request['sha256'], 'artifact_sha256': 'c' * 64, 'initial_history_evidence': [{
            'ordinal': 0, 'media': attrs[0][1], 'sha256': pin, 'resource_sha256': 'b' * 64,
            'original_text': placeholder, 'original_attributes': attrs, 'original_pre_dom_sha256': sha(original.encode()),
            'prepared_pre_dom_sha256': sha(expanded.encode()), 'original_text_sha256': sha(placeholder.encode()),
            'complete_text_sha256': pin, 'inverse_exact': True}]}
        report = {'schema': 'study-compiled-semantic-result.v1', 'real_native_ready': True, 'pure_semantic_only': True,
            'authored_startup_executed': False, 'final_html': store('body.html', html), 'source_proof': store('source.json', proof),
            'bindings': store('bindings.json', {}), 'reconciliation': store('reconciliation.json', {'initial_history_evidence': 1}),
            'capture_inverse': store('inverse.json', {}), 'metadata': store('metadata.json', {})}
        parent = store('report.json', report)
        parent = {'path': str(root / parent['path']), 'sha256': parent['sha256']}
        result = compact_semantic_result(request, parent, root / 'derived')
        return request, {key: result[key] for key in ('path', 'sha256')}

    def check_both(self, request, result, *, reject=False):
        import shutil
        import subprocess
        if reject:
            with self.assertRaises((ValueError, FileNotFoundError)):
                compiler.validate_initial_history_compaction(request, result)
        else:
            self.assertEqual(compiler.validate_initial_history_compaction(request, result)['schema'], 'study-initial-history-compaction.v1')
        if not shutil.which('node'):
            return
        source = r'''
const fs=require('node:fs'),path=require('node:path'),emitter=require('./anki_pipeline/compiled/profile-emitter.cjs');
const arg=JSON.parse(fs.readFileSync(0,'utf8')),report=JSON.parse(fs.readFileSync(arg.result.path)),directory=path.dirname(arg.result.path);
const input={report,directory,sourceProof:JSON.parse(fs.readFileSync(path.join(directory,report.source_proof.path))),request:{history:{source_request:arg.request}}};
let failed=false;try{emitter.validateInitialHistoryCompaction(input)}catch(error){failed=true;process.stderr.write(error.message)}
if(failed!==arg.reject)process.exitCode=1;
'''
        process = subprocess.run([shutil.which('node'), '-e', source], cwd=Path(__file__).resolve().parents[1],
            input=json.dumps({'request': request, 'result': result, 'reject': reject}), text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_immutable_parent_compaction_is_accepted_in_both_consumers(self):
        with tempfile.TemporaryDirectory() as directory:
            request, result = self.snapshot(directory)
            self.check_both(request, result)

    def test_resealed_bad_provenance_edits_and_counters_are_rejected(self):
        for failure in ('range', 'duplicate', 'original-pin', 'rerun', 'source-pin', 'counter', 'descriptor', 'outside', 'expanded-edit', 'byte-offset'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                request, result = self.snapshot(directory)
                root = Path(result['path']).parent
                report = json.loads(Path(result['path']).read_bytes())
                def rewrite(name, value):
                    file = root / report[name]['path']
                    raw = json.dumps(value, ensure_ascii=False).encode()
                    file.write_bytes(raw)
                    report[name].update(sha256=sha(raw), bytes=len(raw))
                proof = json.loads((root / report['initial_history_compaction']['path']).read_bytes())
                if failure == 'range': proof['edits'][0]['end'] = 10 ** 9
                elif failure == 'duplicate': proof['edits'].append(proof['edits'][0])
                elif failure == 'original-pin': proof['edits'][0]['original_prepared_pre_dom_sha256'] = '0' * 64
                elif failure == 'rerun': proof['semantic_preparation_rerun'] = True
                elif failure == 'source-pin': proof['source_html_sha256'] = '0' * 64
                elif failure == 'outside':
                    file = root / report['final_html']['path']
                    file.write_bytes(file.read_bytes().replace('前😀'.encode(), '未经许可修改正文'.encode()))
                    report['final_html'].update(sha256=sha(file.read_bytes()), bytes=file.stat().st_size)
                    proof['derived_html_sha256'] = report['final_html']['sha256']
                elif failure == 'expanded-edit':
                    parent = json.loads(Path(proof['parent_report']['path']).read_bytes())
                    before = (Path(proof['parent_report']['path']).parent / parent['final_html']['path']).read_bytes()
                    after = (root / report['final_html']['path']).read_bytes()
                    edit = proof['edits'][0]
                    after_end = edit['start_byte'] + edit['after_bytes']
                    edit.update(start=0, start_byte=0, before_sha256=sha(before[:edit['end_byte']]),
                                after_bytes=after_end, after_sha256=sha(after[:after_end]))
                elif failure == 'byte-offset': proof['edits'][0]['start_byte'] += 1
                rewrite('initial_history_compaction', proof)
                for name in ('source_proof', 'reconciliation'):
                    value = json.loads((root / report[name]['path']).read_bytes())
                    value['initial_history_compaction'] = dict(report['initial_history_compaction'])
                    if failure == 'counter' and name == 'reconciliation': value['initial_history_evidence'] = 2
                    if failure == 'descriptor' and name == 'source_proof': value['initial_history_compaction']['sha256'] = '0' * 64
                    rewrite(name, value)
                Path(result['path']).write_text(json.dumps(report))
                result['sha256'] = sha(Path(result['path']).read_bytes())
                self.check_both(request, result, reject=True)


if __name__ == '__main__':
    unittest.main()
