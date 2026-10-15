"""A failed preview must not activate data or remove original definitions."""
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from anki_pipeline import sense_frequency as sf
from anki_pipeline import sense_display as sd
from anki_pipeline import sense_components as sc
from anki_pipeline.exam_frequency import frequency_for_matches
from anki_pipeline.packaging import _exam_frequency_markup
from scripts import build_sense_frequency_preview as builder
from scripts.prepare_sense_frequency_records import parse_card_page


class SensePreviewBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.web = self.root / 'web'
        self.source = self.web / 'original'
        self.version = self.source / 'web-preview' / 'source-version'
        (self.version / 'cards').mkdir(parents=True)
        (self.version / 'assets').mkdir()
        self.entry = self.source / 'preview-library.html'
        self.output = self.web / 'new-preview'
        self.database = self.root / 'sense.sqlite3'
        self.records_path = self.root / 'records.json'
        self.backups = self.root / 'backups'
        self.aliases = {'_d': 'dictionary-definition', '_r': 'sense-row',
                        '_p': 'sense-pos', '_t': 'sense-text'}
        (self.version / 'assets' / 'source.js').write_text(
            json.dumps({'classes': self.aliases}), encoding='utf-8')
        (self.version / 'assets' / 'source.css').write_text('body { color: black; }', encoding='utf-8')
        (self.version / 'cards' / 'voice one.mp3').write_bytes(b'original-audio')
        self.senses = [{'pos': 'n.', 'text': '小说'}, {'pos': 'adj.', 'text': '新颖的'}]
        self.configure()

    def configure(self, *, mixed=False, gap=''):
        def block(source, senses):
            return ('<div class="_d" data-dictionary="' + source + '">' + ''.join(
                '<div class="_r"><span class="_p">' + sense['pos'] + '</span>'
                '<span class="_t">' + sense['text'] + '</span></div>' for sense in senses) + '</div>')
        self.definition = (block('oxford', self.senses[:1]) + gap + block('cambridge', self.senses[1:])
                           if mixed else block('oxford', self.senses))
        self.page = ('<html><head><link rel="stylesheet" href="../assets/source.css"></head><body>'
            '<div id="preview-front">novel</div><div id="preview-back">'
            '<h3>novel</h3><div data-occurrences="1">frequency</div>' + self.definition +
            '<audio src="voice%20one.mp3"></audio><script src="../assets/source.js"></script>'
            '<p id="retained">etymology and original examples</p></div></body></html>')
        self.page_path = self.version / 'cards' / 'novel-card.html'
        self.page_path.write_text(self.page, encoding='utf-8')
        url = '/' + str(self.page_path.relative_to(self.web))
        self.card = {'id': 'novel-card', 'word': 'novel', 'deckId': 'unit-1',
                     'deckName': '2027红宝书::Unit 01', 'previewUrl': url, 'exampleCount': 1}
        self.catalog = {'schema': 'anki-web-catalog.v1', 'deckName': '2027红宝书',
            'cards': [self.card], 'decks': [{'id': 'unit-1', 'name': 'Unit 01',
                                         'cardIds': ['novel-card'], 'count': 1}],
            'counts': {'cards': 1, 'decks': 1, 'examples': 1}}
        (self.version / 'catalog.json').write_text(json.dumps(self.catalog, ensure_ascii=False), encoding='utf-8')
        self.entry.write_text('<body data-catalog-url="web-preview/source-version/catalog.json"></body>', encoding='utf-8')
        parsed = parse_card_page(self.page, self.aliases)
        english = 'A novel idea.'
        self.record = {'book_id': 'redbook2027', 'card_id': 'novel-card', 'word': 'novel',
            'definition_source': 'mixed' if mixed else 'oxford',
            'definition_provenance': {'headword': 'novel', 'web_source': url,
                'page_sha256': hashlib.sha256(self.page.encode()).hexdigest(), 'components': parsed['definitions']},
            'expected_occurrences': 1, 'senses': deepcopy(self.senses), 'occurrences': [
                {'physical_source': ['original-location'], 'paper_id': 'kaoyan:2022-01',
                 'sentence_id': 'kaoyan:2022-01:p:original-location:0', 'english': english,
                 'english_hash': hashlib.sha256(english.encode()).hexdigest(),
                 'translation': '一个新颖的想法。', 'source': '2022年考研英语一 ➫ Text 1',
                 'target_range': [2, 7], 'translation_ranges': [],
                 'source_provenance': {'reviewedContentHash': 'source-review-1'},
                 'status': 'reviewed', 'sense_index': 1, 'reason': '修饰 idea，表示新颖',
                 'method': 'context-review', 'review_version': '20261011'}]}
        self.write_record()

    def write_record(self):
        self.record['occurrences'] = [sf.seal_reviewed_assignment(self.record, row)
            if row['status'] == 'reviewed' else row for row in self.record['occurrences']]
        self.records_path.write_text(json.dumps([self.record], ensure_ascii=False), encoding='utf-8')

    def baseline(self):
        value = deepcopy(self.record)
        value.update(card_id='existing-card', word='existing', expected_occurrences=0, occurrences=[])
        sf.save_records(self.database, [value], self.backups)
        return builder._database_digest(self.database)

    def build(self, **options):
        return builder.build(self.entry, self.records_path, self.database, self.output, self.backups, self.web,
                             **options)

    def assert_failed_unchanged(self, error=ValueError):
        before = self.baseline()
        with self.assertRaises(error):
            self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.web.glob('.sense-preview-*')))

    def test_success_keeps_other_cards_and_resources_and_uses_catalog_title(self):
        self.baseline()
        result = self.build()
        verification = json.loads((self.output / 'verification.json').read_text())
        report = sf.read_card(self.database, 'redbook2027', 'novel-card')
        self.assertEqual(result['save']['snapshots'], verification['snapshot_ids'])
        self.assertEqual(report['snapshot_id'], verification['cards']['novel-card.html']['snapshot_id'])
        self.assertIsNotNone(sf.read_card(self.database, 'redbook2027', 'existing-card'))
        updated_page = self.output / 'web-preview' / result['version'] / 'cards' / 'novel-card.html'
        plan = sc.plan_components(self.page, self.record['definition_provenance']['components'], self.aliases)
        self.assertEqual(sc.remove_component_report(updated_page.read_text(), plan), self.page)
        self.assertEqual((updated_page.parent / 'voice one.mp3').read_bytes(), b'original-audio')
        catalog = json.loads((updated_page.parent.parent / 'catalog.json').read_text())
        self.assertEqual(catalog['deckName'], '2027红宝书 · 义项频次预览（1词）')
        self.assertIn('sense_chunks.py', verification['renderer_sha256'])
        self.assertEqual(self.page_path.read_text(), self.page)

    def test_missing_audio_cannot_activate_database_or_create_output(self):
        (self.version / 'cards' / 'voice one.mp3').unlink()
        self.assert_failed_unchanged(FileNotFoundError)

    def recovery_case(self):
        def asset(content, suffix):
            return '_rb_' + hashlib.sha256(content).hexdigest()[:24] + suffix, content
        marker = asset(b'original marker PNG bytes', '.png')
        state = asset(b'original collapsed marker PNG bytes', '.png')
        unrelated = asset(b'unreferenced image PNG bytes', '.png')
        script = asset(('const assets={"closed":"' + state[0] + '#grey-close.png"};').encode(), '.js')
        style = asset(b'.etymology .expandIcon { width: 16px; }', '.css')
        self.recovery_assets = dict((marker, state, script, style, unrelated))
        self.recovery_script, self.recovery_state = script[0], state[0]
        self.recovery_unrelated = unrelated[0]
        embedded = ('<link rel="stylesheet" href="' + style[0] + '"><div class="etymology">'
            '<img class="expandIcon" src="' + marker[0] + '#yellow-open.png"></div>'
            '<script src="' + script[0] + '"></script>')
        self.page = self.page.replace('</body>', '<iframe data-web-etymology-srcdoc="' +
                                      html.escape(embedded, quote=True) + '"></iframe></body>')
        self.page_path.write_text(self.page)
        self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
        self.write_record()
        archive = self.root / 'approved.apkg'
        with zipfile.ZipFile(archive, 'w') as package:
            mapping = {}
            for index, (name, content) in enumerate(self.recovery_assets.items()):
                mapping[str(index)] = name
                package.writestr(str(index), content)
            package.writestr('media', json.dumps(mapping))
        return {'recovery_package': archive,
                'recovery_package_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}

    def test_pinned_package_restores_original_embedded_assets_and_state_dependencies_only_in_copy(self):
        options = self.recovery_case()
        result = self.build(**options)
        page = self.output / 'web-preview' / result['version'] / 'cards' / self.page_path.name
        definition = sc.plan_components(self.page, self.record['definition_provenance']['components'], self.aliases)
        self.assertEqual(sc.remove_component_report(page.read_text(), definition), self.page)
        self.assertEqual(self.page_path.read_text(), self.page)
        self.assertFalse((self.version / 'cards' / self.recovery_state).exists())
        self.assertEqual((page.parent / self.recovery_state).read_bytes(), self.recovery_assets[self.recovery_state])
        self.assertFalse((page.parent / self.recovery_unrelated).exists())
        verification = json.loads((self.output / 'verification.json').read_text())
        proofs = verification['recovered_source_resources'][self.card['id']]
        state = proofs[self.recovery_state + '#grey-close.png']
        self.assertEqual(state['reference_chain'], [self.recovery_script,
                                                   self.recovery_state + '#grey-close.png'])
        self.assertEqual([step['media_name'] for step in state['dependency_chain']],
                         [self.recovery_script, self.recovery_state])
        for step in state['dependency_chain']:
            self.assertEqual(step['sha256'], hashlib.sha256(self.recovery_assets[step['media_name']]).hexdigest())
        self.assertEqual(state['source_page_sha256'], hashlib.sha256(self.page.encode()).hexdigest())
        self.assertEqual(state['sha256'], hashlib.sha256(self.recovery_assets[self.recovery_state]).hexdigest())
        self.assertEqual(verification['recovery_package']['sha256'], options['recovery_package_sha256'])

    def test_missing_legacy_resource_without_explicit_package_still_rejects(self):
        self.recovery_case()
        self.assert_failed_unchanged(FileNotFoundError)

    def test_pinned_package_does_not_authorize_missing_real_image(self):
        options = self.recovery_case()
        self.page = self.page.replace('</body>', '<img src="missing-diagram.png"></body>')
        self.page_path.write_text(self.page)
        self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
        self.write_record()
        before = self.baseline()
        with self.assertRaisesRegex(FileNotFoundError, 'missing-diagram'):
            self.build(**options)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_recovery_package_pin_and_content_address_must_both_match(self):
        options = self.recovery_case()
        before = self.baseline()
        with self.assertRaisesRegex(ValueError, 'package.*hash'):
            self.build(**{**options, 'recovery_package_sha256': '0' * 64})
        archive = options['recovery_package']
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('media', json.dumps({'0': self.recovery_script}))
            package.writestr('0', 'different bytes under a claimed content address')
        options['recovery_package_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'content address'):
            self.build(**options)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_recovery_package_duplicate_media_names_are_rejected(self):
        options = self.recovery_case()
        archive = options['recovery_package']
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr('media', json.dumps({'0': self.recovery_script, '1': self.recovery_script}))
            package.writestr('0', self.recovery_assets[self.recovery_script])
            package.writestr('1', self.recovery_assets[self.recovery_script])
        options['recovery_package_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.build(**options)
        self.assertFalse(self.database.exists())
        self.assertFalse(self.output.exists())

    def test_injected_package_resource_is_not_an_original_card_reference(self):
        options = self.recovery_case()
        render = sf.render_report
        def inject(report):
            return render(report).replace('<div class="sf-report"', '<img src="' +
                self.recovery_unrelated + '"><div class="sf-report"', 1)
        before = self.baseline()
        with patch.object(builder.sf, 'render_report', side_effect=inject):
            with self.assertRaisesRegex(ValueError, 'original card'):
                self.build(**options)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_encoded_or_relative_alias_cannot_borrow_a_recovered_dependency(self):
        options = self.recovery_case()
        render = sf.render_report
        before = self.baseline()
        for reference in (self.recovery_state, './' + self.recovery_state,
                          self.recovery_state.replace('_rb_', '%5frb_', 1),
                          '../cards/' + self.recovery_state + '#extra-marker.png'):
            def inject(report):
                return render(report).replace('<div class="sf-report"', '<img src="' +
                    reference + '"><div class="sf-report"', 1)
            with self.subTest(reference=reference), patch.object(builder.sf, 'render_report', side_effect=inject):
                with self.assertRaisesRegex(ValueError, 'original card'):
                    self.build(**options)
            self.assertEqual(builder._database_digest(self.database), before)
            self.assertFalse(self.output.exists())

    def test_original_recovery_reference_with_traversal_or_encoding_is_not_eligible(self):
        options = self.recovery_case()
        original = self.page
        for reference in ('../cards/' + self.recovery_script,
                          self.recovery_script.replace('_rb_', '%5frb_', 1)):
            self.page = original.replace(self.recovery_script, reference)
            self.page_path.write_text(self.page)
            self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
            self.write_record()
            with self.subTest(reference=reference), self.assertRaises(FileNotFoundError):
                self.build(**options)
            self.assertFalse(self.database.exists())
            self.assertFalse(self.output.exists())

    def test_pinned_viewer_literal_dependency_missing_from_package_cannot_be_skipped(self):
        options = self.recovery_case()
        archive = options['recovery_package']
        with zipfile.ZipFile(archive, 'w') as package:
            mapping = {}
            for index, (name, content) in enumerate(self.recovery_assets.items()):
                if name == self.recovery_state:
                    continue
                mapping[str(index)] = name
                package.writestr(str(index), content)
            package.writestr('media', json.dumps(mapping))
        options['recovery_package_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with self.assertRaisesRegex(FileNotFoundError, 'unapproved viewer dependency'):
            self.build(**options)
        self.assertFalse(self.database.exists())
        self.assertFalse(self.output.exists())

    def test_recovery_package_or_recovered_bytes_changed_before_activation_roll_back(self):
        options = self.recovery_case()
        before = self.baseline()
        rename = builder.os.rename
        for change in ('archive', 'resource'):
            def change_after_rename(stage, destination):
                result = rename(stage, destination)
                if change == 'archive':
                    options['recovery_package'].write_bytes(b'changed archive')
                else:
                    recovered = next((destination / 'web-preview').glob('*/cards/' + self.recovery_state))
                    recovered.write_bytes(b'changed recovered resource')
                return result
            with self.subTest(change=change), patch.object(builder.os, 'rename', side_effect=change_after_rename):
                with self.assertRaisesRegex(ValueError, 'recover.*changed'):
                    self.build(**options)
            self.assertEqual(builder._database_digest(self.database), before)
            self.assertFalse(self.output.exists())
            if change == 'archive':
                # Recreate the exact fixture archive for the independent second case.
                with zipfile.ZipFile(options['recovery_package'], 'w') as package:
                    mapping = {}
                    for index, (name, content) in enumerate(self.recovery_assets.items()):
                        mapping[str(index)] = name
                        package.writestr(str(index), content)
                    package.writestr('media', json.dumps(mapping))
                options['recovery_package_sha256'] = hashlib.sha256(options['recovery_package'].read_bytes()).hexdigest()

    def test_existing_authorizing_viewer_script_changed_before_activation_is_rejected(self):
        options = self.recovery_case()
        source_script = self.version / 'cards' / self.recovery_script
        source_script.write_bytes(self.recovery_assets[self.recovery_script])
        before = self.baseline()
        rename = builder.os.rename
        def change_after_rename(stage, destination):
            result = rename(stage, destination)
            source_script.write_bytes(b'changed original authorizing viewer script')
            return result
        with patch.object(builder.os, 'rename', side_effect=change_after_rename):
            with self.assertRaisesRegex(ValueError, 'authorizing dependency changed'):
                self.build(**options)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def shared_resource_case(self, *, add_to_page=True):
        version = self.web / 'accent-supplement-online-20261005' / 'web-preview' / ('a' * 64)
        assets = version / 'assets'
        assets.mkdir(parents=True, exist_ok=True)
        path = assets / 'phonetic-labels.css'
        path.write_text('.phonetic-label { font-size: 1rem; }', encoding='utf-8')
        url = '/' + str(path.relative_to(self.web))
        if add_to_page:
            self.page = self.page.replace('</head>', '<link rel="stylesheet" href="' + url + '"></head>')
            self.page_path.write_text(self.page, encoding='utf-8')
            self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
            self.write_record()
        return url, path

    def test_existing_absolute_cross_version_asset_keeps_original_url_and_inverse_and_records_hash(self):
        url, path = self.shared_resource_case()
        original = path.read_bytes()
        result = self.build()
        page = self.output / 'web-preview' / result['version'] / 'cards' / self.page_path.name
        rendered = page.read_text()
        self.assertIn('href="' + url + '"', rendered)
        plan = sc.plan_components(self.page, self.record['definition_provenance']['components'], self.aliases)
        self.assertEqual(sc.remove_component_report(rendered, plan), self.page)
        proof = json.loads((self.output / 'verification.json').read_text())['shared_source_resources']
        self.assertEqual(proof[self.record['card_id']][url]['path'], str(path.resolve()))
        self.assertEqual(proof[self.record['card_id']][url]['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.page_path.read_text(), self.page)

    def test_missing_absolute_shared_asset_does_not_activate(self):
        _, path = self.shared_resource_case()
        path.unlink()
        self.assert_failed_unchanged(FileNotFoundError)

    def test_absolute_shared_asset_traversal_and_wrong_version_shape_do_not_activate(self):
        _, path = self.shared_resource_case(add_to_page=False)
        urls = ('/../outside.css', '/accent-supplement-online-20261005/web-preview/not-a-hash/assets/phonetic-labels.css',
            '/accent-supplement-online-20261005/web-preview/' + 'a' * 64 + '/assets/../assets/phonetic-labels.css',
            '/accent-supplement-online-20261005/web-preview/' + 'a' * 64 + '/assets/%2e%2e/assets/phonetic-labels.css',
            '/accent-supplement-online-20261005/web-preview/' + 'a' * 64 + '/cards/phonetic-labels.css')
        for url in urls:
            self.configure()
            self.page = self.page.replace('</head>', '<link rel="stylesheet" href="' + url + '"></head>')
            self.page_path.write_text(self.page)
            self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
            self.write_record()
            with self.subTest(url=url): self.assert_failed_unchanged()

    def test_absolute_asset_symlink_escape_does_not_activate(self):
        _, path = self.shared_resource_case()
        outside = self.root / 'outside.css'
        outside.write_text('unapproved outside root')
        path.unlink()
        path.symlink_to(outside)
        self.assert_failed_unchanged()

    def test_shared_asset_changed_after_publish_rename_cannot_activate_and_output_is_removed(self):
        _, path = self.shared_resource_case()
        before = self.baseline()
        rename = builder.os.rename
        def change_after_rename(stage, destination):
            result = rename(stage, destination)
            path.write_text('changed before live activation')
            return result
        with patch.object(builder.os, 'rename', side_effect=change_after_rename):
            with self.assertRaisesRegex(ValueError, 'shared.*changed'):
                self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.web.glob('.sense-preview-*')))

    def test_newly_injected_absolute_resource_cannot_expand_original_card_authorization(self):
        self.shared_resource_case()
        injected = self.web / 'different-book' / 'web-preview' / ('b' * 64) / 'assets' / 'new.js'
        injected.parent.mkdir(parents=True)
        injected.write_text('new unauthorized script')
        url = '/' + str(injected.relative_to(self.web))
        render = sf.render_report
        def extra_resource(report):
            value = render(report)
            return value.replace('<div class="sf-report"', '<script src="' + url + '"></script><div class="sf-report"', 1)
        before = self.baseline()
        with patch.object(builder.sf, 'render_report', side_effect=extra_resource):
            with self.assertRaisesRegex(ValueError, 'not.*original card'):
                self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_another_cards_shared_resource_does_not_authorize_a_new_reference_here(self):
        self.shared_resource_case()
        other_resource = self.web / 'other-shared' / 'web-preview' / ('b' * 64) / 'assets' / 'other.js'
        other_resource.parent.mkdir(parents=True)
        other_resource.write_text('original resource for the second card')
        other_url = '/' + str(other_resource.relative_to(self.web))
        other_page = self.page.replace('</head>', '<script src="' + other_url + '"></script></head>')
        other_path = self.version / 'cards' / 'second-card.html'
        other_path.write_text(other_page)
        other_card = {**self.card, 'id': 'second-card', 'previewUrl': '/' + str(other_path.relative_to(self.web))}
        other_record = deepcopy(self.record)
        other_record['card_id'] = other_card['id']
        other_record['definition_provenance'].update(web_source=other_card['previewUrl'],
            page_sha256=hashlib.sha256(other_page.encode()).hexdigest())
        other_record['occurrences'] = [sf.seal_reviewed_assignment(other_record, row)
                                       for row in other_record['occurrences']]
        self.catalog['cards'].append(other_card)
        self.catalog['decks'][0]['cardIds'].append(other_card['id'])
        self.catalog['decks'][0]['count'] = 2
        (self.version / 'catalog.json').write_text(json.dumps(self.catalog, ensure_ascii=False))
        self.records_path.write_text(json.dumps([self.record, other_record], ensure_ascii=False))
        render = sf.render_report
        def extra_resource(report):
            value = render(report)
            if report['card_id'] == self.record['card_id']:
                value = value.replace('<div class="sf-report"',
                    '<script src="' + other_url + '"></script><div class="sf-report"', 1)
            return value
        before = self.baseline()
        with patch.object(builder.sf, 'render_report', side_effect=extra_resource):
            with self.assertRaisesRegex(ValueError, 'not.*original card'):
                self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_candidate_scope_requires_live_sources_and_explicit_audit_pin(self):
        before = self.baseline()
        audit = self.root / 'audit.json'
        audit.write_text('{}', encoding='utf-8')
        for options in (
                {'candidate_scope_audit': audit},
                {'source_displays': True, 'candidate_scope_audit': audit},
                {'source_displays': True, 'candidate_scope_supplement': audit},
                {'candidate_scope_audit': audit, 'candidate_scope_audit_sha256': 'a' * 64}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'candidate scope'):
                builder.build(self.entry, self.records_path, self.database, self.output,
                              self.backups, self.web, **options)
            self.assertEqual(builder._database_digest(self.database), before)
            self.assertFalse(self.output.exists())

    def candidate_scope_case(self):
        from tests.test_sense_candidate_scope import candidate_fixture
        directory = self.root / 'candidate-fixture'
        directory.mkdir()
        value, page, sources, audit_path, _ = candidate_fixture(directory)
        page = (page.replace('<html><body>', '<html><head></head><body>'
                            '<div id="preview-front">a/an</div><div id="preview-back">')
                    .replace('</body>', '</div></body>')
                    .replace('definition-row', 'sense-row').replace('part-of-speech', 'sense-pos')
                    .replace('definition-text', 'sense-text'))
        self.card.update(id=value['card_id'], word=value['word'], exampleCount=5)
        self.catalog['decks'][0]['cardIds'] = [value['card_id']]
        self.page_path.write_text(page, encoding='utf-8')
        provenance = {**value['definition_provenance'], 'web_source': self.card['previewUrl'],
                      'page_sha256': hashlib.sha256(page.encode()).hexdigest(),
                      'components': parse_card_page(page, self.aliases)['definitions']}
        value['definition_provenance'] = provenance
        raw_path = directory / 'full-inventory-v2' / 'records.jsonl'
        raw = json.loads(raw_path.read_text())
        raw['definition_provenance'] = deepcopy(provenance)
        raw_data = json.dumps(raw, ensure_ascii=False, sort_keys=True) + '\n'
        raw_path.write_text(raw_data, encoding='utf-8')
        audit = json.loads(audit_path.read_text())
        snapshot = audit['source_snapshot']
        snapshot['inventory_record_byte_locator']['byte_length'] = len(raw_data.encode())
        snapshot['inventory_record_sha256'] = hashlib.sha256(raw_data.encode()).hexdigest()
        snapshot['official_page_sha256'] = provenance['page_sha256']
        Path(snapshot['official_page']).write_text(page, encoding='utf-8')
        audit['original_book_intent']['definition_provenance'] = deepcopy(provenance)
        forms = audit['word_form_origin']['formal_page_forms_raw']
        audit['word_form_origin']['formal_page_form_raw_character_range'] = [page.index(forms), page.index(forms) + len(forms)]
        audit_data = json.dumps(audit, ensure_ascii=False, sort_keys=True) + '\n'
        audit_path.write_text(audit_data, encoding='utf-8')
        self.record = value
        self.write_record()
        (self.version / 'catalog.json').write_text(json.dumps(self.catalog, ensure_ascii=False), encoding='utf-8')
        return page, sources, {'source_displays': True, 'candidate_scope_audit': audit_path,
                              'candidate_scope_audit_sha256': hashlib.sha256(audit_data.encode()).hexdigest()}

    def test_live_candidate_overlay_reconciles_components_before_database_activation(self):
        page, sources, options = self.candidate_scope_case()
        with patch.object(sd, '_load_sources', return_value=sources):
            result = builder.build(self.entry, self.records_path, self.database, self.output,
                                   self.backups, self.web, **options)
        report = sf.read_card(self.database, 'redbook2027', self.record['card_id'])
        self.assertEqual((report['total'], report['pending_count']), (3, 1))
        self.assertEqual(report['candidate_scope']['excluded_total'], 2)
        verification = json.loads((self.output / 'verification.json').read_text())
        self.assertEqual(verification['candidate_scopes'][self.record['card_id']], report['candidate_scope'])
        self.assertIn(self.record['card_id'], verification['frequency_reconciliations'])
        target = self.output / 'web-preview' / result['version'] / 'cards' / self.page_path.name
        rendered = target.read_text()
        self.assertIn('剩余3次为候选', rendered)
        self.assertEqual(self.page_path.read_text(), page)

    def test_reviewed_other_lemma_conflict_cannot_be_silently_excluded(self):
        _, sources, options = self.candidate_scope_case()
        before = self.baseline()
        self.record['occurrences'][1].update(status='reviewed', sense_index=0, reason='错误地把 as 当冠词')
        self.write_record()
        with patch.object(sd, '_load_sources', return_value=sources), self.assertRaisesRegex(ValueError, 'conflicts'):
            builder.build(self.entry, self.records_path, self.database, self.output,
                          self.backups, self.web, **options)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_serialized_candidate_overlay_needs_original_source_replay(self):
        from anki_pipeline.sense_candidate_scope import apply_candidate_scope
        page, sources, options = self.candidate_scope_case()
        before = self.baseline()
        with patch.object(sd, '_load_sources', return_value=sources):
            checked, authority = builder.sr.reread_source_displays(
                [self.record], {self.record['card_id']: page}, self.aliases)
            filtered, scopes = apply_candidate_scope(checked, {self.record['card_id']: page},
                self.aliases, verified_sources=authority,
                audit_path=options['candidate_scope_audit'],
                expected_audit_sha256=options['candidate_scope_audit_sha256'])
        self.record = filtered[0]
        self.record['candidate_scope'] = scopes.for_record(self.record).verification()
        self.write_record()
        with patch.object(sd, '_load_sources', return_value=sources), self.assertRaisesRegex(ValueError, 'original source replay'):
            builder.build(self.entry, self.records_path, self.database, self.output,
                          self.backups, self.web, source_displays=True)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_explicit_mixed_inventory_selects_only_catalog_book_and_records_input_hash(self):
        other = deepcopy(self.record)
        other.update(book_id='redbook', card_id='2026-card')
        self.records_path = self.root / 'inventory.jsonl'
        self.records_path.write_text('\n'.join(json.dumps(row, ensure_ascii=False)
            for row in (other, self.record)) + '\n')
        result = builder.build(self.entry, self.records_path, self.database, self.output,
                               self.backups, self.web, inventory_records=True)
        self.assertEqual(len(result['words']), 1)
        self.assertIsNone(sf.read_card(self.database, 'redbook', '2026-card'))
        evidence = json.loads((self.output / 'verification.json').read_text())['record_input']
        self.assertEqual(evidence['source_records'], 2)
        self.assertEqual(evidence['selected_records'], 1)
        self.assertEqual(evidence['sha256'], hashlib.sha256(self.records_path.read_bytes()).hexdigest())

    def test_mixed_inventory_rejects_unknown_books_before_any_write(self):
        self.records_path = self.root / 'inventory.jsonl'
        self.records_path.write_text(json.dumps({**self.record, 'book_id':'unknown-book'}))
        before = self.baseline()
        with self.assertRaises(ValueError):
            builder.build(self.entry, self.records_path, self.database, self.output,
                          self.backups, self.web, inventory_records=True)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_input_changed_during_construction_cannot_activate_database(self):
        with patch.object(builder, '_file_sha', return_value='changed-input'):
            self.assert_failed_unchanged()

    def test_source_display_is_persisted_and_included_in_renderer_fingerprint(self):
        row = self.record['occurrences'][0]
        sources = {'sentences': {row['sentence_id']: {
            'id': row['sentence_id'], 'english': row['english'],
            'translationZh': row['translation'], 'englishHash': row['english_hash'],
            'reviewedContentHash': row['source_provenance']['reviewedContentHash']}},
            'completions': {}, 'options': {}, 'watched': {}}
        with patch.object(sd, '_load_sources', return_value=sources):
            builder.build(self.entry, self.records_path, self.database, self.output,
                          self.backups, self.web, source_displays=True)
        report = sf.read_card(self.database, 'redbook2027', 'novel-card')
        display = report['senses'][1]['occurrences'][0]['display']
        self.assertEqual(display['english'], row['english'])
        self.assertEqual(display['translation'], row['translation'])
        self.assertEqual(report['senses'][1]['count'], 1)
        verification = json.loads((self.output / 'verification.json').read_text())
        self.assertIn('sense_display.py', verification['renderer_sha256'])

    def test_source_display_failure_cannot_activate_database_or_publish_preview(self):
        before = self.baseline()
        with patch.object(sd, 'attach_source_displays', side_effect=ValueError('stale native source')):
            with self.assertRaisesRegex(ValueError, 'stale native source'):
                builder.build(self.entry, self.records_path, self.database, self.output,
                              self.backups, self.web, source_displays=True)
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_source_bound_frequency_repair_is_visible_reversible_and_preserves_original(self):
        panel = _exam_frequency_markup({'exam_frequency': frequency_for_matches([], 44)})
        self.page = self.page.replace('<div data-occurrences="1">frequency</div>', panel)
        self.page = self.page.replace('<h3>novel</h3>', '<h1 class="word">novel</h1>')
        self.page_path.write_text(self.page)
        self.record['definition_provenance']['page_sha256'] = hashlib.sha256(self.page.encode()).hexdigest()
        row = self.record['occurrences'][0]
        row['physical_source'] = [row['sentence_id']]
        self.write_record()
        source = {'id': row['sentence_id'], 'english': row['english'],
            'englishHash': row['english_hash'], 'translationZh': row['translation'],
            'reviewedContentHash': row['source_provenance']['reviewedContentHash'],
            'paperId': row['paper_id'], 'paragraphId': row['sentence_id'].rsplit(':', 1)[0],
            'sourceHash': row['english_hash'], 'start': 0, 'end': len(row['english']),
            'sourceEnglish': row['english'], 'sourceBlockIds': [row['paper_id'] + ':b-first'],
            'sourceFragments': [], 'sourceSentenceRefs': [], 'kind': 'reading', 'context': {}}
        sources = {'sentences': {row['sentence_id']: source},
                   'completions': {}, 'options': {}, 'watched': {}}
        before = self.baseline()
        with self.assertRaisesRegex(ValueError, 'physical occurrences'):
            self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())
        with patch.object(sd, '_load_sources', return_value=sources):
            result = builder.build(self.entry, self.records_path, self.database, self.output,
                                   self.backups, self.web, source_displays=True)
        verification = json.loads((self.output / 'verification.json').read_text())
        audit = verification['frequency_reconciliations'][self.record['card_id']]
        revised = (self.output / 'web-preview' / result['version'] / 'cards' / 'novel-card.html').read_text()
        self.assertEqual(audit['old_frequency']['occurrences'], 0)
        self.assertEqual(audit['new_frequency']['occurrences'], 1)
        self.assertIn('原网页0次，按明确词形和原文位置核对为1次', revised)
        self.assertIn('data-occurrences="1"', revised)
        self.assertEqual(self.page_path.read_text(), self.page)
        self.assertEqual(sf.read_card(self.database, 'redbook2027', 'novel-card')['total'], 1)

    def test_bad_definitions_are_rejected_before_any_database_write(self):
        for mutation in ('reverse', 'text', 'pos', 'source', 'components'):
            with self.subTest(mutation=mutation):
                self.configure()
                if mutation == 'reverse': self.record['senses'].reverse()
                if mutation == 'text': self.record['senses'][0]['text'] = '另一个释义'
                if mutation == 'pos': self.record['senses'][0]['pos'] = 'v.'
                if mutation == 'source': self.record['definition_source'] = 'webster'
                if mutation == 'components': self.record['definition_provenance']['components'][0]['source'] = 'webster'
                self.write_record()
                self.assert_failed_unchanged()

    def test_crossword_crosscard_crossbook_and_stale_page_are_rejected(self):
        for mutation in ('word', 'card', 'book', 'page', 'web_source', 'headword'):
            with self.subTest(mutation=mutation):
                self.configure()
                if mutation == 'word': self.record['word'] = 'ambition'
                if mutation == 'card': self.record['card_id'] = 'other-card'
                if mutation == 'book': self.record['book_id'] = 'redbook'
                if mutation == 'page': self.record['definition_provenance']['page_sha256'] = '0' * 64
                if mutation in ('web_source', 'headword'):
                    self.record['definition_provenance'][mutation] = 'other'
                self.write_record()
                self.assert_failed_unchanged()

    def test_contiguous_mixed_definitions_preserve_each_original_sense(self):
        self.configure(mixed=True, gap='\n ')
        result = self.build()
        page = self.output / 'web-preview' / result['version'] / 'cards' / 'novel-card.html'
        revised = page.read_text()
        plan = sc.plan_components(self.page, self.record['definition_provenance']['components'], self.aliases)
        self.assertEqual(sc.remove_component_report(revised, plan), self.page)
        report = sf.read_card(self.database, 'redbook2027', 'novel-card')
        self.assertEqual(report['definition_source'], 'mixed')
        self.assertEqual([sense['text'] for sense in report['senses']], ['小说', '新颖的'])

    def test_separated_components_keep_headwords_frequency_and_global_counts(self):
        gap = '<h3>an</h3><aside id="component-source">original component source</aside>'
        self.configure(mixed=True, gap=gap)
        self.baseline()
        result = self.build()
        revised = (self.output / 'web-preview' / result['version'] / 'cards' / 'novel-card.html').read_text()
        plan = sc.plan_components(self.page, self.record['definition_provenance']['components'], self.aliases)
        self.assertEqual(sc.remove_component_report(revised, plan), self.page)
        self.assertIn(gap, revised)
        self.assertEqual(revised.count('data-snapshot='), 2)
        report = sf.read_card(self.database, 'redbook2027', 'novel-card')
        self.assertEqual(report['total'], 1)
        self.assertEqual([sense['count'] for sense in report['senses']], [0, 1])
        self.assertIn('sense_components.py', json.loads((self.output / 'verification.json').read_text())['renderer_sha256'])
        self.assertIsNotNone(sf.read_card(self.database, 'redbook2027', 'existing-card'))
        self.assertEqual(self.page_path.read_text(), self.page)

    def test_construction_failure_after_staging_snapshot_does_not_touch_live_database(self):
        before = self.baseline()
        with patch.object(builder, '_copy_resource', side_effect=OSError('simulated resource copy failure')):
            with self.assertRaises(OSError): self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_stage_publication_failure_does_not_touch_live_database(self):
        before = self.baseline()
        with patch.object(builder.os, 'rename', side_effect=OSError('simulated output publication failure')):
            with self.assertRaises(OSError): self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())

    def test_post_commit_activation_failure_restores_existing_database_and_removes_output(self):
        before = self.baseline()
        save = sf.save_records
        def fail_after_commit(path, records, backups):
            result = save(path, records, backups)
            if Path(path).resolve() == self.database.resolve():
                raise RuntimeError('simulated post-commit error')
            return result
        with patch.object(builder.sf, 'save_records', side_effect=fail_after_commit):
            with self.assertRaises(RuntimeError): self.build()
        self.assertEqual(builder._database_digest(self.database), before)
        self.assertFalse(self.output.exists())
        self.assertIsNone(sf.read_card(self.database, 'redbook2027', 'novel-card'))

    def test_post_commit_activation_failure_removes_new_database_and_output(self):
        save = sf.save_records
        def fail_after_commit(path, records, backups):
            result = save(path, records, backups)
            if Path(path).resolve() == self.database.resolve():
                raise RuntimeError('simulated post-commit error')
            return result
        with patch.object(builder.sf, 'save_records', side_effect=fail_after_commit):
            with self.assertRaises(RuntimeError): self.build()
        self.assertFalse(self.database.exists())
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_removed_or_modified(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('user-owned output')
        before = self.baseline()
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(sentinel.read_text(), 'user-owned output')
        self.assertEqual(builder._database_digest(self.database), before)


if __name__ == '__main__':
    unittest.main()
