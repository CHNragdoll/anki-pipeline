"""Bounded real SQLite/native/SF overlay tests; all writes stay in temp fixtures."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from anki_pipeline.packaging import _exam_frequency_markup
from scripts import build_residual_optimization_preview as tool
from tests.test_sense_frequency import aligned_record, reseal
from tests.test_sense_display import source, native_example


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tool.canonical(value) + '\n')
    return tool.pin(path)


def database(path, records):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE snapshots(id TEXT,book_id TEXT,card_id TEXT,payload TEXT)')
        db.execute('CREATE TABLE active_snapshots(book_id TEXT,card_id TEXT,snapshot_id TEXT)')
        for value in records:
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?)', (value['snapshot_id'], value['book_id'],
                value['card_id'], tool.canonical(value)))
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', (value['book_id'], value['card_id'], value['snapshot_id']))
        db.commit()


def actual_owner_fixture_request(directory):
    """Retain a six-card CLI fixture under the assigned preview evidence folder.

    Its tiny detached SQLite files contain the writer's exact prepared exports,
    not an applied clone or a new production authority. Existing files stay read-only.
    """
    directory = Path(directory).resolve()
    owned = tool.ROOT / 'output' / tool.ARTIFACT
    tool.require(directory.is_relative_to(owned) and not directory.exists(), 'fresh owned fixture directory required')
    directory.mkdir(parents=True)
    try:
        plan_pin = {'file': str(ActualOwnershipPreviewTests.FIXTURE), 'sha256': ActualOwnershipPreviewTests.PIN}
        plan = tool.read_json(plan_pin)
        selected = []
        parent = directory / 'parent-fixture.sqlite3'
        candidate = directory / 'child-fixture.sqlite3'
        with closing(sqlite3.connect(parent)) as old, closing(sqlite3.connect(candidate)) as new:
            for db in (old, new):
                db.execute('CREATE TABLE snapshots(id TEXT,book_id TEXT,card_id TEXT,payload TEXT)')
                db.execute('CREATE TABLE active_snapshots(book_id TEXT,card_id TEXT,snapshot_id TEXT)')
            for item in plan['affected']:
                after = tool.read_json(item['payload_file'])
                if not after.get('exam_usage_policy', {}).get('residual_auxiliary_usages'):
                    continue
                before = tool.read_json(item['before_payload_file'])
                for db, value in ((old, before), (new, after)):
                    db.execute('INSERT INTO snapshots VALUES(?,?,?,?)', (value['snapshot_id'], value['book_id'], value['card_id'], tool.canonical(value)))
                    db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', (value['book_id'], value['card_id'], value['snapshot_id']))
                selected.append(item)
            old.commit()
            new.commit()
        tool.require(len(selected) == 6, 'actual ownership fixture must cover three lexical entities in both books')
        checkpoint = {'schema': 'residual-optimization-checkpoint.v1', 'run_id': 'owner-fixture-v1',
            'parent_database': {'file': str(parent), 'stat': tool.database_stat(parent)},
            'database': {'file': str(candidate), 'stat': tool.database_stat(candidate)}, 'cards': selected,
            'entities_file': plan['entities_file'], 'entity_usages_file': plan['entity_usages_file'],
            'fixture_only': True, 'actual_writer_prepare': plan_pin}
        checkpoint_pin = save(directory / 'checkpoint.json', checkpoint)
        web = tool.ROOT / 'output'
        source = web / 'exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/runtime-candidate-overlay-v4'
        books = []
        for book, count in [('redbook', 6679), ('redbook2027', 6529)]:
            entry = source / book / 'preview-library.html'
            catalog = tool.local_url(tool.Shell(entry.read_text()).catalogs[0], web)
            books.append({'book_id': book, 'entry': tool.pin(entry), 'catalog': tool.pin(catalog), 'expected_cards': count})
        runtime = tool.local_url(tool.Shell((source / 'redbook/preview-library.html').read_text()).scripts[0], web)
        request = {'schema': tool.SCHEMA, 'checkpoint': checkpoint_pin, 'web_root': str(web), 'output': str(directory / 'preview'),
            'runtime': tool.pin(runtime), 'books': books, 'exam_base_url': 'http://localhost:8765',
            'fixture_only': True, 'actual_writer_prepare': plan_pin}
        return save(directory / 'request.json', request)
    except BaseException:
        shutil.rmtree(directory)
        raise


class ResidualPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.web = self.root / 'web'
        self.accepted = self.web / 'accepted'
        self.accepted.mkdir(parents=True)
        self.runtime = self.web / 'shared/library-preview.js'
        self.runtime.parent.mkdir()
        # Exact existing production asset, copied only into the detached fixture.
        runtime = tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/library-preview-owned-runtime-v4.js'
        self.runtime.write_bytes(runtime.read_bytes())
        self.before, self.after, self.books, self.affected, self.pages = [], [], [], [], {}
        for book_id in ['redbook', 'redbook2027']:
            original = aligned_record()
            original.update(book_id=book_id, card_id='a' * 64)
            item = source(original['occurrences'][0]['sentence_id'], original['occurrences'][0]['english'],
                original['occurrences'][0]['translation'], original['occurrences'][0]['alignment']['alignments'])
            for row in original['occurrences']:
                row['source_provenance']['reviewedContentHash'] = item['reviewedContentHash']
            original = reseal(original)
            before = sf.prepare_record(original)
            changed = deepcopy(original)
            changed['occurrences'][0]['reason'] = '新增充分上下文证据：这里是新颖含义。'
            after = sf.prepare_record(reseal(changed))
            self.before.append(before)
            self.after.append(after)
            path = self.accepted / book_id / 'web-preview/old/cards' / (before['card_id'] + '.html')
            path.parent.mkdir(parents=True)
            url = '/' + str(path.relative_to(self.web))
            css = tool.ROOT / 'anki_pipeline/templates/sense-frequency.css'
            frequency = tool.preview._frequency(before['occurrences'])
            body = ('<!doctype html><html><head><base href="' + url + '">'
                '<style data-supplement-preview="style">' + css.read_text() + '</style></head><body>'
                '<button id="preview-flip" aria-pressed="false"></button><section id="preview-front">front</section>'
                '<section id="preview-back"><audio src="../../assets/uk.mp3"></audio><iframe class="etymology-source-frame" srcdoc="legacy"></iframe>'
                '<a class="original-source" href="../../sources/entry.html">原词典</a>'
                '<ul>' + native_example(item, item['english'], item['translationZh'], [[2, 7], [19, 24]]) + '</ul>'
                + _exam_frequency_markup({'exam_frequency': frequency}) + sf.render_report(sf.report_from_record(before))
                + '<script>const preserveLegacyFlipAudio=true;</script></section></body></html>')
            path.write_text(body)
            self.pages[book_id] = (path, body)
            unchanged = {**{'id': 'b' * 64, 'word': 'unchanged', 'previewUrl': '/accepted/' + book_id + '/untouched.html'},
                'deckId': 'deck', 'deckName': '词卡', 'unit': '1', 'lesson': '1', 'position': '2', 'definition': '不改', 'exampleCount': 3}
            row = {**unchanged, 'id': before['card_id'], 'word': before['word'], 'previewUrl': url,
                'position': '1', 'definition': 'n. 小说；adj. 新颖的', 'exampleCount': 1}
            (self.accepted / book_id / 'untouched.html').write_text('untouched original bytes')
            catalog = {'schema': 'anki-web-catalog.v1', 'deckName': '词卡', 'defaultReader': 'latex',
                'counts': {'cards': 2, 'decks': 1, 'examples': 4}, 'cards': [row, unchanged],
                'decks': [{'id': 'deck', 'name': '词卡', 'unit': '1', 'lesson': '1', 'count': 2, 'cardIds': [row['id'], unchanged['id']]}]}
            catalog_path = self.accepted / book_id / 'catalog.json'
            catalog_pin = save(catalog_path, catalog)
            entry = self.accepted / book_id / 'preview-library.html'
            entry.write_text('<html><head><base href="/original-shell.html"></head><body data-catalog-url="/' +
                str(catalog_path.relative_to(self.web)) + '"><script src="/shared/library-preview.js"></script></body></html>')
            self.books.append({'book_id': book_id, 'entry': tool.pin(entry), 'catalog': catalog_pin, 'expected_cards': 2})
            payload_pin = save(self.root / book_id / 'payload.json', after)
            ledger_pin = save(self.root / book_id / 'ledger.json', {'new_definitions': [], 'excluded': [], 'prior_wrong_lemma_ids': [], 'render_context': {}})
            self.affected.append({'book_id': book_id, 'card_id': before['card_id'], 'word': before['word'],
                'parent_snapshot_id': before['snapshot_id'], 'parent_payload_sha256': tool.digest(before),
                'child_snapshot_id': after['snapshot_id'], 'child_payload_sha256': tool.digest(after),
                'payload_file': payload_pin, 'ledger_file': ledger_pin, 'original_count': 2, 'new_count': 2})
        self.parent = self.root / 'parent.sqlite3'
        self.candidate = self.root / 'candidate.sqlite3'
        database(self.parent, self.before)
        database(self.candidate, self.after)
        self.checkpoint = {'schema': 'residual-optimization-checkpoint.v1', 'run_id': 'c' * 64,
            'parent_database': {'file': str(self.parent), 'certified_sha256': hashlib.sha256(self.parent.read_bytes()).hexdigest(), 'stat': tool.database_stat(self.parent)},
            'database': {'file': str(self.candidate), 'stat': tool.database_stat(self.candidate)}, 'cards': self.affected}
        self.checkpoint_pin = save(self.root / 'checkpoint.json', self.checkpoint)
        self.output = self.web / tool.ARTIFACT / 'candidate-v1'
        self.request = {'schema': tool.SCHEMA, 'checkpoint': self.checkpoint_pin, 'web_root': str(self.web),
            'output': str(self.output), 'runtime': tool.pin(self.runtime), 'books': self.books}
        self.request_pin = save(self.root / 'request.json', self.request)

    def refresh_request(self):
        self.checkpoint_pin = save(self.root / 'checkpoint.json', self.checkpoint)
        self.request['checkpoint'] = self.checkpoint_pin
        self.request_pin = save(self.root / 'request.json', self.request)

    def build(self):
        plan, _ = tool.prepare(self.request_pin)
        checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
        return tool.execute(self.request_pin, checksum)

    def test_dry_run_reads_only_affected_snapshots_and_writes_nothing(self):
        before = (self.parent.read_bytes(), self.candidate.read_bytes())
        with patch.object(tool.preview, 'file_sha', wraps=tool.preview.file_sha) as hashing:
            plan, _ = tool.prepare(self.request_pin)
        self.assertEqual(len(plan['affected']), 2)
        self.assertEqual([item['changed_cards'] for item in plan['books']], [1, 1])
        self.assertFalse(self.output.exists())
        self.assertTrue(all(Path(call.args[0]).suffix != '.sqlite3' for call in hashing.call_args_list))
        self.assertEqual((self.parent.read_bytes(), self.candidate.read_bytes()), before)

    def test_prepare_retains_only_file_references_and_display_only_snapshot_stays_exact(self):
        self.candidate.unlink()
        database(self.candidate, self.before)
        for item, before in zip(self.affected, self.before):
            item.update(child_snapshot_id=before['snapshot_id'], child_payload_sha256=tool.digest(before), physical_updated=False)
            item['payload_file'] = save(Path(item['payload_file']['file']), before)
            item['ledger_file'] = save(Path(item['ledger_file']['file']), {'new_definitions': [], 'excluded': [],
                'residual_display_updates': [], 'render_context': {'residual_display_updates': []}})
        self.checkpoint['database']['stat'] = tool.database_stat(self.candidate)
        self.refresh_request()
        plan, state = tool.prepare(self.request_pin)
        self.assertTrue(all(not value['physical_updated'] and value['snapshot_id'] == value['parent_snapshot_id'] for value in plan['affected']))
        self.assertEqual(state[3], {(item['book_id'], item['card_id']): item for item in self.affected})
        self.assertTrue(all('occurrences' not in item and 'before_payload' not in item for item in state[3].values()))
        original = self.candidate.read_bytes()
        self.build()
        self.assertEqual(self.candidate.read_bytes(), original)

    def test_two_book_overlay_changes_only_affected_pages_and_inherits_shared_runtime(self):
        old_db = (self.parent.read_bytes(), self.candidate.read_bytes())
        result = self.build()
        self.assertEqual(result['rendered_cards'], 2)
        self.assertFalse(result['production_applied'])
        manifest = json.loads((self.output / 'preview-manifest.json').read_text())
        self.assertEqual(len([name for name in manifest['files'] if '/cards/' in name]), 2)
        self.assertEqual([name for name in manifest['files'] if name.endswith('.js')], ['assets/library-preview.js'])
        for book in self.books:
            bid = book['book_id']
            old = json.loads(Path(book['catalog']['file']).read_text())
            new = json.loads((self.output / bid / 'catalog.json').read_text())
            self.assertEqual(new['cards'][1], old['cards'][1])
            self.assertEqual(new['decks'], old['decks'])
            self.assertEqual(new['counts'], old['counts'])
            self.assertNotEqual(new['cards'][0]['previewUrl'], old['cards'][0]['previewUrl'])
            generated = self.web / new['cards'][0]['previewUrl'].lstrip('/')
            page = generated.read_text()
            self.assertIn('新增充分上下文证据', page)
            self.assertIn('<base href="' + old['cards'][0]['previewUrl'] + '">', page)
            self.assertIn('<audio src="../../assets/uk.mp3"></audio>', page)
            self.assertIn('<iframe class="etymology-source-frame" srcdoc="legacy"></iframe>', page)
            self.assertIn('<script>const preserveLegacyFlipAudio=true;</script>', page)
            shell = (self.output / bid / 'preview-library.html').read_text()
            self.assertIn('/assets/library-preview.js"></script>', shell)
            self.assertIn('<base href="/original-shell.html">', shell)
            self.assertEqual(self.pages[bid][0].read_text(), self.pages[bid][1])
        self.assertEqual((self.parent.read_bytes(), self.candidate.read_bytes()), old_db)

    def test_wrong_child_export_active_pointer_or_duplicate_identity_fails_before_output(self):
        original = deepcopy(self.checkpoint)
        self.checkpoint['cards'][0]['child_payload_sha256'] = 'd' * 64
        self.refresh_request()
        with self.assertRaisesRegex(ValueError, 'payload binding'):
            tool.prepare(self.request_pin)
        self.checkpoint = original
        self.checkpoint['cards'].append(deepcopy(self.checkpoint['cards'][0]))
        self.refresh_request()
        with self.assertRaisesRegex(ValueError, 'unique hashes'):
            tool.prepare(self.request_pin)
        self.assertFalse(self.output.exists())

    def test_source_drift_and_wrong_reviewed_plan_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reviewed plan'):
            tool.execute(self.request_pin, 'e' * 64)
        plan, _ = tool.prepare(self.request_pin)
        self.pages['redbook'][0].write_text('changed source')
        with self.assertRaisesRegex(ValueError, 'pinned input changed'):
            tool.check_guards(plan)
        self.assertFalse(self.output.exists())

    def test_database_drift_or_wal_and_output_escape_are_rejected(self):
        Path(str(self.candidate) + '-wal').write_bytes(b'active')
        with self.assertRaisesRegex(ValueError, 'standalone'):
            tool.prepare(self.request_pin)
        Path(str(self.candidate) + '-wal').unlink()
        self.request['output'] = str(self.accepted / 'must-not-write')
        self.request_pin = save(self.root / 'request.json', self.request)
        with self.assertRaisesRegex(ValueError, 'fresh owned'):
            tool.prepare(self.request_pin)

    def test_certified_closed_wal_header_uses_immutable_reader_without_sidecar_or_stat_writes(self):
        for path in (self.parent, self.candidate):
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone(), ('wal',))
                db.commit()
            self.assertFalse(any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')))
        old = (self.parent.read_bytes(), self.candidate.read_bytes())
        stats = (tool.database_stat(self.parent), tool.database_stat(self.candidate))
        self.checkpoint['parent_database']['stat'], self.checkpoint['database']['stat'] = stats
        self.refresh_request()
        self.build()
        self.assertEqual((self.parent.read_bytes(), self.candidate.read_bytes()), old)
        self.assertEqual((tool.database_stat(self.parent), tool.database_stat(self.candidate)), stats)
        self.assertFalse(any(Path(str(path) + suffix).exists() for path in (self.parent, self.candidate) for suffix in ('-wal', '-shm', '-journal')))

    def test_legacy_mode_ro_creates_wal_sidecars_but_new_owned_reader_does_not(self):
        for path in (self.parent, self.candidate):
            with closing(sqlite3.connect(path)) as db:
                db.execute('PRAGMA journal_mode=WAL')
            self.assertFalse(Path(str(path) + '-shm').exists())
        with closing(tool.preview._ro(self.parent)) as old:
            old.execute('SELECT count(*) FROM snapshots').fetchone()
            self.assertTrue(Path(str(self.parent) + '-wal').exists())
            self.assertTrue(Path(str(self.parent) + '-shm').exists())
        original = self.candidate.read_bytes()
        stat = tool.database_stat(self.candidate)
        with closing(tool.owned_readonly(self.candidate)) as new:
            self.assertEqual(new.execute('SELECT count(*) FROM snapshots').fetchone(), (2,))
            self.assertFalse(Path(str(self.candidate) + '-wal').exists())
            self.assertFalse(Path(str(self.candidate) + '-shm').exists())
            with self.assertRaises(sqlite3.OperationalError):
                new.execute('DELETE FROM snapshots')
        self.assertEqual(self.candidate.read_bytes(), original)
        self.assertEqual(tool.database_stat(self.candidate), stat)

    def test_new_sidecar_is_rejected_at_end_guard_even_if_main_bytes_and_stat_are_unchanged(self):
        plan, _ = tool.prepare(self.request_pin)
        Path(str(self.candidate) + '-wal').write_bytes(b'external writer')
        with self.assertRaisesRegex(ValueError, 'standalone'):
            tool.check_guards(plan)

    def test_failure_discards_only_private_stage_and_preserves_existing_sources(self):
        plan, _ = tool.prepare(self.request_pin)
        checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
        with patch.object(tool, 'render_card', side_effect=RuntimeError('injected bounded failure')):
            with self.assertRaisesRegex(RuntimeError, 'bounded failure'):
                tool.execute(self.request_pin, checksum)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob('.residual-preview-*')), [])
        self.assertEqual(self.pages['redbook'][0].read_text(), self.pages['redbook'][1])

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir(parents=True)
        (self.output / 'keep').write_text('old bytes')
        with self.assertRaisesRegex(ValueError, 'fresh owned'):
            tool.prepare(self.request_pin)
        self.assertEqual((self.output / 'keep').read_text(), 'old bytes')

    def test_actual_cli_plan_and_execute_are_bound_to_exact_stdout_bytes(self):
        command = [str(tool.ROOT / '.venv/bin/python'), '-B', str(Path(tool.__file__)),
            '--request', self.request_pin['file'], '--sha256', self.request_pin['sha256']]
        plan = subprocess.run(command + ['--dry-run'], cwd=tool.ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertFalse(self.output.exists())
        result = subprocess.run(command + ['--execute', '--plan-sha256', hashlib.sha256(plan.stdout.encode()).hexdigest()],
            cwd=tool.ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['rendered_cards'], 2)
        self.assertFalse(json.loads(result.stdout)['production_applied'])

    def test_presentation_adapter_cannot_change_source_meaning_count_or_snapshot(self):
        data = deepcopy(self.after[0])
        data.setdefault('exam_usage_policy', {})['residual_display_updates'] = [{'reviewed': True}]
        with self.assertRaisesRegex(ValueError, 'pinned writer'):
            tool.presentation(data)
        def bad(value):
            value['occurrences'][0]['english'] = 'invented'
            return value
        with self.assertRaisesRegex(ValueError, 'certified'):
            tool.presentation(data, bad)
        self.assertEqual(tool.presentation(data, lambda value: value), data)

    def test_separate_signed_display_ledger_uses_writer_keyword_api_without_resealing_source(self):
        from anki_pipeline.residual_optimization import presentation_record
        certified, shown, _, _ = self.presentation_fixture()
        entry = deepcopy(shown['occurrences'][0]['display']['residual_optimization'])
        entry.update(book_id=certified['book_id'], card_id=certified['card_id'], child_snapshot_id=certified['snapshot_id'])
        result = tool.presentation(certified, presentation_record, display_updates=[entry])
        self.assertEqual(result['snapshot_id'], certified['snapshot_id'])
        self.assertEqual(result['occurrences'][0]['english'], certified['occurrences'][0]['english'])
        self.assertEqual(result['occurrences'][0]['display']['translation'], entry['after']['translation'])
        self.assertNotIn('residual_display_updates', certified.get('exam_usage_policy', {}))
        entry['child_snapshot_id'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'physical child'):
            tool.presentation(certified, presentation_record, display_updates=[entry])

    def test_multiple_base_or_unsafe_base_and_shell_runtime_drift_fail_closed(self):
        before, after = self.before[0], self.after[0]
        kwargs = {'source_url': '/old.html', 'target_url': '/new.html', 'target_urls': {}}
        with self.assertRaisesRegex(ValueError, 'multiple base'):
            tool.render_card('<head><base href="/one"><base href="/two"></head>', before, after, {}, **kwargs)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            tool.render_card('<head><base href="https://evil.test"></head>', before, after, {}, **kwargs)
        self.runtime.write_text('runtime drift')
        with self.assertRaisesRegex(ValueError, 'pinned input changed'):
            tool.prepare(self.request_pin)

    def presentation_fixture(self):
        certified = deepcopy(self.after[0])
        row = certified['occurrences'][0]
        item = source(row['sentence_id'], row['english'], row['translation'], row['alignment']['alignments'])
        native = native_example(item, item['english'], item['translationZh'], [[2, 7], [19, 24]])
        jump = tool.sd._native_examples(native, {})[0]['jump']
        old = {'schema': 'sense-display.v2', 'english': row['english'], 'translation': row['translation'],
            'english_hash': sf._sha(row['english']), 'translation_hash': sf._sha(row['translation']),
            'target_range': row['target_range'], 'alignment': row['alignment'], 'cloze_answers': [],
            'provenance': {'native_jump': jump, 'derivation': 'original'}}
        old['display_hash'] = tool.digest(old)
        row['display'] = old
        previous = {'english': old['english'], 'translation': old['translation'],
            'english_hash': sf._sha(old['english']), 'translation_hash': sf._sha(old['translation']),
            'alignment': old['alignment'], 'source_comparisons': []}
        updated = deepcopy(previous)
        updated['translation'] += '而且完整译意。'
        updated['translation_hash'] = sf._sha(updated['translation'])
        updated['alignment']['translationHash'] = updated['translation_hash']
        comparison = {'english': previous['english'], 'translation': previous['translation'],
            'english_hash': previous['english_hash'], 'translation_hash': previous['translation_hash'],
            'target_range': old['target_range'], 'reason': '保留完整原译与细块；<script>只作文本</script>',
            'chunks': [{'en': [2, 7], 'zh': [[6, 8]], 'relation': 'equivalent'}]}
        updated['source_comparisons'] = [comparison]
        authority = {'before': previous, 'after': updated, 'before_sha256': tool.digest(previous),
            'after_sha256': tool.digest(updated), 'occurrence_ids': [row['occurrence_id']],
            'decision': {'original_source_pins': [tool.pin(self.pages['redbook'][0])]}}
        view = {**deepcopy(old), 'translation': updated['translation'], 'translation_hash': updated['translation_hash'], 'alignment': updated['alignment'],
            'residual_optimization': authority}
        view.pop('display_hash')
        view['display_hash'] = tool.digest(view)
        shown = deepcopy(certified)
        shown['occurrences'][0]['display'] = view
        pair = tool.render_sentence_pair({key: value for key, value in old.items() if key != 'display'})
        historical = '<details class="sf-ownership-history"><article class="sf-example" data-sf-occurrence-id="' + row['occurrence_id'] + '">' + pair + '</article></details>'
        page = '<html><head></head><body><ul>' + native + '</ul><article class="sf-example" data-sf-occurrence-id="' + row['occurrence_id'] + '">' + pair + historical + '</article></body></html>'
        return certified, shown, page, historical

    def test_reviewed_display_projection_changes_exact_native_and_sf_pairs_keeps_raw_jump_marks_history_and_original_comparison(self):
        certified, shown, page, historical = self.presentation_fixture()
        raw_jump = tool.sd._native_examples(page, {})[0]['jump']
        updated, inverse, stats = tool.project_displays(page, certified, shown)
        self.assertEqual(stats, {'changed_occurrences': 1, 'native_pairs': 1, 'sf_pairs': 1})
        self.assertEqual(tool.preview.restore_edits(updated, inverse), page)
        self.assertIn(historical, updated)
        native = tool.sd._native_examples(updated, {})[0]
        self.assertEqual(native['jump'], raw_jump)
        self.assertEqual(native['target_ranges'], [[2, 7], [19, 24]])
        self.assertEqual(native['translation'], shown['occurrences'][0]['display']['translation'])
        self.assertEqual(updated.count('data-reviewed-source-comparison="residual"'), 2)
        self.assertIn('&lt;script&gt;只作文本&lt;/script&gt;', updated)
        self.assertNotIn('<script>只作文本</script>', updated)
        self.assertIn('原译分块对照', updated)
        self.assertIn('data-chunk-ids="2"', updated, 'original comparison uses IDs above current fine chunks')
        self.assertEqual(certified['occurrences'][0]['english'], shown['occurrences'][0]['english'])

    def test_reviewed_projection_rejects_wrong_ledger_hash_occurrence_or_old_pair(self):
        certified, shown, page, _ = self.presentation_fixture()
        broken = deepcopy(shown)
        broken['occurrences'][0]['display']['translation'] += '篡改'
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            tool.project_displays(page, certified, broken)
        broken = deepcopy(shown)
        view = broken['occurrences'][0]['display']
        view['residual_optimization']['occurrence_ids'] = ['wrong']
        view.pop('display_hash')
        view['display_hash'] = tool.digest(view)
        with self.assertRaisesRegex(ValueError, 'occurrence binding'):
            tool.project_displays(page, certified, broken)
        with self.assertRaisesRegex(ValueError, 'text binding'):
            tool.project_displays(page.replace('<p class="sf-zh">', '<p class="sf-zh">changed', 1), certified, shown)

    def test_unsafe_run_or_book_paths_are_rejected_before_output(self):
        self.checkpoint['run_id'] = '../escape'
        self.refresh_request()
        with self.assertRaisesRegex(ValueError, 'safe immutable'):
            tool.prepare(self.request_pin)
        self.checkpoint['run_id'] = 'c' * 64
        self.request['books'][0]['book_id'] = '../escape'
        self.refresh_request()
        with self.assertRaisesRegex(ValueError, 'unsupported book'):
            tool.prepare(self.request_pin)

    def test_candidate_runtime_adds_only_exact_owned_history_route_and_is_reversible(self):
        original = self.runtime.read_bytes()
        candidate, proof = tool.runtime_overlay(original, '/residual-optimization-20261013/engineering/preview-own/candidate-v1')
        inverse = candidate.decode()[len(tool.RESIDUAL_KEYBOARD):]
        for before, after in reversed(proof['lifecycle_edits']):
            inverse = inverse.replace(after, before, 1)
        self.assertEqual(inverse.replace(proof['new_guard'], proof['original_guard'], 1).encode(), original)
        self.assertIn('(redbook|redbook2027)', proof['new_guard'])
        self.assertIn('[a-f0-9]{64}', proof['new_guard'])
        self.assertIn('url.origin === window.location.origin', candidate.decode())
        with self.assertRaisesRegex(ValueError, 'not unique'):
            tool.runtime_overlay(b'no approved guard', '/candidate')

    def test_new_reviewed_fine_spans_use_existing_sf_capture_keyboard_and_bilingual_delegate_once(self):
        certified, shown, page, _ = self.presentation_fixture()
        page, _, _ = tool.project_displays(page, certified, shown)
        page = page.replace('<body>', '<body><section class="sf-report">', 1).replace('</body>', '</section></body>', 1)
        fine = tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/fine-display-projection-runtime-v3.js'
        paths = [tool.ROOT / 'anki_pipeline/templates/card-chunks.js', tool.ROOT / 'anki_pipeline/templates/sense-frequency.js', fine]
        javascript = r'''
const {JSDOM}=require('jsdom'),fs=require('fs'),crypto=require('crypto'),assert=require('assert/strict');
const dom=new JSDOM(fs.readFileSync(0,'utf8'),{runScripts:'outside-only',url:'http://localhost:8771/candidate.html'}),w=dom.window,d=w.document;
Object.defineProperty(w,'crypto',{value:crypto.webcrypto});w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;
for(const file of PATHS)w.eval(fs.readFileSync(file,'utf8'));
w.eval(RESIDUAL_HELPER);
(async()=>{const token=await w.AnkiReviewedChunkProjection.prepare({schema:'derived-chunk-display-projection.v1',records:[],pins:{}}),handle=w.AnkiReviewedChunkProjection.install(d,token);
const residual=w.AnkiResidualReviewedChunkRuntime.install(d);assert.equal(w.AnkiResidualReviewedChunkRuntime.install(d),residual);
let clicks=0,flips=0;d.addEventListener('click',()=>clicks++,true);d.addEventListener('keydown',e=>{if(e.key===' '&&!e.defaultPrevented)flips++;});
const pair=d.querySelector('article.sf-example > .sf-sentence-pair'),en=pair.querySelector('.sf-en [data-reviewed-chunk-projection][data-chunk-ids="0"]'),zh=pair.querySelector('.sf-zh [data-reviewed-chunk-projection][data-chunk-ids="0"]');assert.ok(en&&zh);en.focus();
en.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));assert.equal(clicks,1);assert.ok(zh.classList.contains('card-chunk-active'));
en.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true}));assert.equal(clicks,2);assert.equal(pair.querySelector('.card-chunk-active'),null);assert.equal(flips,0);
zh.dispatchEvent(new w.MouseEvent('click',{bubbles:true,cancelable:true}));assert.ok(en.classList.contains('card-chunk-active'));zh.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert.equal(pair.querySelector('.card-chunk-active'),null);
residual.dispose();residual.dispose();handle.dispose();dom.window.close();process.stdout.write('actual SF capture and existing fine bridge PASS\n');})().catch(e=>{dom.window.close();console.error(e);process.exitCode=1;});
'''.replace('PATHS', json.dumps([str(path) for path in paths])).replace('RESIDUAL_HELPER', json.dumps(tool.RESIDUAL_KEYBOARD))
        result = subprocess.run([shutil.which('node'), '-e', javascript], input=page, text=True,
            cwd=tool.ROOT, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('existing fine bridge PASS', result.stdout)

    def test_contextual_definition_is_explicitly_non_native_and_keeps_complete_evidence(self):
        addition = {'kind': 'contextual_usage', 'is_dictionary_native': False, 'native_base_evidence': {'source': 'original'},
            'context_evidence': [{'english': 'actual context'}], 'source_pins': [tool.pin(self.pages['redbook'][0])],
            'contextual_key': 'c' * 64, 'source_headword': 'novel',
            'contextual_sense': {'kind': 'contextual_usage', 'is_dictionary_native': False, 'pos': 'adj.', 'text': '语境释义', 'english': 'reviewed contextual meaning'}}
        rendered = tool.definition_evidence(addition)
        self.assertIn('语境用法（非词典原义）', rendered)
        self.assertIn('actual context', rendered)
        self.assertIn('reviewed contextual meaning', rendered)
        addition['is_dictionary_native'] = True
        with self.assertRaisesRegex(ValueError, 'non-native'):
            tool.definition_evidence(addition)

    def test_sealed_phrase_source_and_companion_histories_are_inside_only_the_canonical_sentence_and_reversible(self):
        original = self.before[0]
        source, companion = deepcopy(original['occurrences'][0]), deepcopy(original['occurrences'][1])
        canonical = deepcopy(source)
        canonical['target_range'] = [source['target_range'][0], companion['target_range'][1]]
        canonical['occurrence_id'] = tool.digest([source['paper_id'], source['physical_source'], canonical['target_range']])
        history = {'schema': 'residual-native-phrase-history.v1', 'source_book_id': original['book_id'],
            'source_card_id': 'c' * 64, 'source_parent_snapshot_id': original['snapshot_id'], 'source_parent_row': source,
            'source_parent_row_sha256': tool.digest(source), 'companion_card_id': original['card_id'],
            'companion_parent_snapshot_id': original['snapshot_id'], 'companion_parent_row': companion,
            'companion_parent_row_sha256': tool.digest(companion), 'canonical_owner_card_id': original['card_id'],
            'canonical_occurrence_id': canonical['occurrence_id'], 'native_scope': {'whole_phrase_range': canonical['target_range']},
            'decision': {'reason': '完整词组转归审核依据'}, 'book_decision': {'physical_count': 1}}
        history['history_sha256'] = tool.digest(history)
        canonical['semantic_review'] = {'residual_owner_history': history}
        after = {**original, 'occurrences': [canonical], 'exam_usage_policy': {'residual_native_phrase_owners': [history]}}
        ledger = {'companion_replacements': [history]}
        article = '<article class="sf-example" data-sf-occurrence-id="' + canonical['occurrence_id'] + '">' + tool.render_sentence_pair(canonical) + '</article>'
        page = '<section class="sf-report">' + article + '</section>'
        rendered, inverse = tool.phrase_owner_histories(page, after, ledger)
        self.assertEqual(tool.preview.restore_edits(rendered, inverse), page)
        parser = tool.native_api._Offsets(rendered, {})
        owner = next(node for node in parser.root.walk() if 'sf-example' in node.classes)
        history_node = next(node for node in parser.root.walk() if 'residual-owner-history' in node.classes)
        self.assertIs(history_node.parent, owner)
        self.assertEqual(len([node for node in history_node.walk() if 'sf-archived-example' in node.classes]), 2)
        for old in (source, companion):
            self.assertIn(tool.html.escape(old['reason']), rendered)
            self.assertIn(tool.html.escape(tool.canonical(old)), rendered)
        broken = deepcopy(after)
        broken['occurrences'][0]['semantic_review']['residual_owner_history']['source_parent_row_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'differ'):
            tool.phrase_owner_histories(page, broken, ledger)
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            tool.phrase_owner_histories(page + article, after, ledger)


class ActualOwnershipPreviewTests(unittest.TestCase):
    """Source-pinned writer prepare fixture: no candidate/production DB mutation."""
    FIXTURE = tool.ROOT / 'output/residual-optimization-20261013/engineering/writer-own/ownership-readonly-prepared-v2/plan.json'
    PIN = '8382c3d5a8ada6ba21e1a67d778c0aedbc0fea327ccfa2f114d281f3ec2cf50d'

    def setUp(self):
        self.plan = tool.read_json({'file': str(self.FIXTURE), 'sha256': self.PIN})
        self.entities = tool.read_json(self.plan['entities_file'])
        self.usages = tool.read_json(self.plan['entity_usages_file'])

    def test_actual_three_auxiliary_lexemes_keep_physical_once_fine_marks_and_sentence_local_history(self):
        self.assertEqual({entity['lemma'] for entity in self.entities}, {'ruling', 'mistaken', 'vice versa'})
        for entity in self.entities:
            usages = [usage for usage in self.usages if usage['entity_id'] == entity['entity_id']]
            rendered, proof = tool.render_auxiliary(entity, usages, runtime_url='/candidate/assets/auxiliary-chunks.js', exam_base_url='http://localhost:8765')
            self.assertEqual(proof, {'entity_id': entity['entity_id'], 'physical_occurrences': 1, 'book_references': 2, 'visible_sentences': 1, 'learning_card': False})
            self.assertIn('<p>关联词条补充</p>', rendered)
            self.assertIn('真题词频 · 1次 / ', rendered)
            self.assertIn('本句完整原转归依据 · 2026红宝书', rendered)
            self.assertIn('本句完整原转归依据 · 2027红宝书', rendered)
            self.assertIn('data-book-id="redbook"', rendered)
            source_label = tool.auxiliary_source_label(entity)[0]
            self.assertIn('牛津高阶英汉双解词典', source_label)
            self.assertIn('剑桥高级学习词典', source_label)
            self.assertTrue(source_label.endswith('原译'))
            parser = tool.native_api._Offsets(rendered, {})
            articles = [node for node in parser.root.walk() if 'sf-example' in node.classes]
            self.assertEqual(len(articles), 1)
            histories = [node for node in articles[0].walk() if 'residual-auxiliary-history' in node.classes]
            self.assertEqual(len(histories), 2)
            row = usages[0]['row']
            en = next(node for node in articles[0].walk() if 'sf-en' in node.classes)
            zh = next(node for node in articles[0].walk() if 'sf-zh' in node.classes)
            self.assertEqual(tool.sd._Tree(rendered[en.start:en.end]).root.text(), row['english'])
            self.assertEqual(tool.sd._Tree(rendered[zh.start:zh.end]).root.text(), row['translation'])
            self.assertIn('<mark', rendered)
            self.assertIn('data-reviewed-chunk-projection="residual"', rendered)
            for usage in usages:
                for origin in usage['origins']:
                    self.assertIn(tool.html.escape(origin['source_parent_row']['reason']), rendered)
                    self.assertIn(tool.html.escape(origin['decision']['reason']), rendered)
            self.assertIn('原卷 · 完整图文', rendered)
            bad = deepcopy(usages)
            bad[0]['row']['target_range'] = [0, 1]
            with self.assertRaisesRegex(ValueError, 'seal'):
                tool.render_auxiliary(entity, bad, runtime_url='/same.js')
            with self.assertRaisesRegex(ValueError, 'duplicate auxiliary'):
                tool.render_auxiliary(entity, usages + [usages[0]], runtime_url='/same.js')

    def test_auxiliary_contextual_source_is_visible_and_cannot_look_native(self):
        entity = deepcopy(self.entities[0])
        entity.update(kind='contextual_usage', is_dictionary_native=False)
        usage = next(usage for usage in self.usages if usage['entity_id'] == entity['entity_id'])
        page, _ = tool.render_auxiliary(entity, [usage], runtime_url='/candidate.js')
        self.assertIn('语境用法（非词典原义）</p>', page)
        self.assertIn('牛津高阶英汉双解词典', page)
        self.assertIn('剑桥高级学习词典', page)
        self.assertIn('<summary>完整释义来源与语境审核依据</summary>', page)

    def test_auxiliary_reviewed_chinese_source_is_visibly_supplemental(self):
        entity = deepcopy(self.entities[0])
        entity['native_definition']['translation_kind'] = 'reviewed_translation'
        usage = deepcopy(next(usage for usage in self.usages if usage['entity_id'] == entity['entity_id']))
        usage['sense_id'] = tool.digest([entity['entity_id'], entity['native_definition']])
        usage['review_seal'] = tool.digest({key: value for key, value in usage.items() if key != 'review_seal'})
        page, _ = tool.render_auxiliary(entity, [usage], runtime_url='/candidate.js')
        self.assertIn('中文补译（原英文词典依据保留）</p>', page)
        self.assertIn('<summary>原英文词典、双语检索与补译依据</summary>', page)

    def test_actual_both_books_remove_wrong_default_pair_and_link_real_auxiliary_entry_keep_original_bytes(self):
        checked = 0
        root = tool.ROOT / 'output'
        urls = {entity['entity_id']: '/candidate/auxiliary/' + entity['entity_id'] + '.html' for entity in self.entities}
        for item in self.plan['affected']:
            after = tool.read_json(item['payload_file'])
            usages = after.get('exam_usage_policy', {}).get('residual_auxiliary_usages', [])
            if not usages:
                continue
            before = tool.read_json(item['before_payload_file'])
            ledger = tool.read_json(item['ledger_file'])
            catalog = json.loads((root / 'exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay' / item['book_id'] / 'catalog.json').read_text())
            source_row = next(row for row in catalog['cards'] if row['id'] == item['card_id'])
            source = tool.local_url(source_row['previewUrl'], root)
            original = source.read_text()
            aliases = tool.class_aliases(source.parent.parent)
            result, _, _, proof, _ = tool.render_card(original, before, after, ledger,
                source_url=source_row['previewUrl'], target_url='/candidate/' + item['book_id'] + '/web-preview/fixture/cards/' + item['card_id'] + '.html',
                target_urls={row['id']: row['previewUrl'] for row in catalog['cards']}, aliases=aliases, exam_base_url='http://localhost:8765')
            result, inverse = tool.auxiliary_links(result, after, urls)
            self.assertIn('（辅助词条）</a>', result)
            self.assertIn('target="_blank" rel="noopener"', result)
            self.assertEqual(tool.preview.restore_edits(result, inverse).count('residual-entity-links'), 0)
            native = tool.native_api._Offsets(result, aliases)
            for usage in usages:
                for origin in usage['origins']:
                    old = origin['source_parent_row']
                    for node in native.root.walk():
                        if node.tag != 'li' or 'example-card' not in node.classes or tool._inside_history(node):
                            continue
                        example = tool.sd._native_examples(result[node.start:node.end], aliases)[0]
                        self.assertIsNone(tool.native_api._view(old, example, old.get('display')), 'wrong full source sentence remains in default native examples')
            self.assertEqual(source.read_text(), original)
            self.assertEqual(proof['source_sha256'], sf._sha(original))
            self.assertEqual(len(catalog['cards']), 6679 if item['book_id'] == 'redbook' else 6529)
            checked += 1
        self.assertEqual(checked, 6)

    def test_auxiliary_reviewed_completed_presentation_uses_new_cn_fine_ranges_keeps_canonical_raw_and_history(self):
        entity = next(entity for entity in self.entities if entity['lemma'] == 'vice versa')
        usage = deepcopy(next(usage for usage in self.usages if usage['entity_id'] == entity['entity_id']))
        raw = deepcopy(usage['row'])
        origin = usage['origins'][0]
        approved = origin['source_parent_row'].get('display') or origin['source_parent_row']
        before = {field: deepcopy(approved[field]) for field in ('english', 'translation', 'english_hash', 'translation_hash', 'alignment')}
        after = deepcopy(before)
        after['translation'] += '（完整原义保持）'
        after['translation_hash'] = sf._sha(after['translation'])
        after['alignment']['translationHash'] = after['translation_hash']
        after['source_comparisons'] = [{**deepcopy(raw), 'reason': '保留原译完整对照'}]
        entry = {'before': before, 'after': after, 'before_sha256': tool.digest(before), 'after_sha256': tool.digest(after),
            'book_refs': [{'book_id': usage['book_id'], 'card_id': origin['source_card_id'], 'occurrence_id': origin['source_parent_row']['occurrence_id']}],
            'decision': {'original_source_pins': [{'file': str(self.FIXTURE), 'sha256': self.PIN}]}}
        usage['presentation'] = {**after, 'target_range': raw['target_range'], 'physical_occurrence_id': usage['occurrence_id'], 'residual_display_update': entry}
        usage['review_seal'] = tool.digest({key: value for key, value in usage.items() if key != 'review_seal'})
        rendered, proof = tool.render_auxiliary(entity, [usage], runtime_url='/candidate/chunks.js')
        self.assertEqual(proof['physical_occurrences'], 1)
        self.assertIn('（完整原义保持）', rendered)
        self.assertIn('原译分块对照', rendered)
        self.assertIn('data-reviewed-chunk-projection="residual"', rendered)
        self.assertEqual(usage['row'], raw)
        self.assertIn(tool.html.escape(origin['source_parent_row']['reason']), rendered)
        broken = deepcopy(usage)
        broken['presentation']['physical_occurrence_id'] = 'wrong'
        broken['review_seal'] = tool.digest({key: value for key, value in broken.items() if key != 'review_seal'})
        with self.assertRaisesRegex(ValueError, 'binding'):
            tool.render_auxiliary(entity, [broken], runtime_url='/candidate/chunks.js')
        broken = deepcopy(usage)
        broken['presentation']['target_range'] = [0, 3]
        broken['review_seal'] = tool.digest({key: value for key, value in broken.items() if key != 'review_seal'})
        with self.assertRaisesRegex(ValueError, 'full-lexeme range'):
            tool.render_auxiliary(entity, [broken], runtime_url='/candidate/chunks.js')

    def test_actual_frozen_chunk_completed_display_changes_native_and_sf_without_physical_or_frequency_change(self):
        from anki_pipeline.residual_optimization import presentation_record
        base = tool.ROOT / 'output/residual-optimization-20261013/chunks/merge-own'
        update = tool.read_json({'file': str(base / 'display-updates.json'), 'sha256': '2fc3084635cfa2cd63030bb6fef791f265ad96698788c24de1bb99b436143c1d'})[0]
        refs = tool.read_json({'file': str(base / 'display-bindings.json'), 'sha256': 'f40a8e4c4623fa0ca948c56a6c8851774d1cef97b4035b3622dea0eb54c42ba1'})[update['display_id']]
        ref = refs[0]
        database, before_stat = tool.checked_database(self.plan['baseline'])
        with closing(tool.owned_readonly(database)) as db:
            saved = db.execute('SELECT payload FROM snapshots WHERE id=? AND book_id=? AND card_id=?',
                (ref['snapshot_id'], ref['book_id'], ref['card_id'])).fetchone()[0]
            before = json.loads(saved)
            self.assertEqual(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',
                (ref['book_id'], ref['card_id'])).fetchone(), (ref['snapshot_id'],))
            documents = tool.history_documents(db, before)
        entry = {**update, 'book_refs': refs, 'book_id': ref['book_id'], 'card_id': ref['card_id'],
            'child_snapshot_id': ref['snapshot_id'], 'occurrence_ids': [row['occurrence_id'] for row in refs
                if (row['book_id'], row['card_id']) == (ref['book_id'], ref['card_id'])]}
        ledger = {'new_definitions': [], 'excluded': [], 'residual_display_updates': [entry], 'render_context': {'residual_display_updates': [entry]}}
        catalog = json.loads((tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay' / ref['book_id'] / 'catalog.json').read_text())
        row = next(row for row in catalog['cards'] if row['id'] == ref['card_id'])
        source = tool.local_url(row['previewUrl'], tool.ROOT / 'output')
        original = source.read_text()
        aliases = tool.class_aliases(source.parent.parent)
        rendered, frequency, _, proof, _ = tool.render_card(original, before, before, ledger, source_url=row['previewUrl'],
            target_url='/candidate/redbook/web-preview/fixture/cards/' + ref['card_id'] + '.html',
            target_urls={row['id']: row['previewUrl'] for row in catalog['cards']}, aliases=aliases, documents=documents,
            adapter=presentation_record, exam_base_url='http://localhost:8765')
        self.assertEqual(proof['display_projection_stats'], {'changed_occurrences': 1, 'native_pairs': 1, 'sf_pairs': 1})
        self.assertEqual(frequency, tool.preview._frequency(before['occurrences']))
        self.assertEqual(before['word'], 'difficult')  # Fixture identity, not a production rule.
        parsed = tool.native_api._Offsets(rendered, aliases)
        article = next(node for node in parsed.root.walk() if node.attrs.get('data-sf-occurrence-id') == ref['occurrence_id'] and not tool._inside_history(node))
        pair = next(node for node in article.children if 'sf-sentence-pair' in node.classes)
        cn = next(node for node in pair.children if 'sf-zh' in node.classes)
        self.assertEqual(tool.sd._Tree(rendered[cn.start:cn.end]).root.text(), update['after']['translation'])
        self.assertIn('data-reviewed-chunk-projection="residual"', rendered[pair.start:pair.end])
        self.assertIn('sf-target-chunk', rendered[pair.start:pair.end])
        self.assertIn('原译分块对照', rendered[pair.start:pair.end])
        self.assertEqual(source.read_text(), original)
        self.assertEqual(tool.database_stat(database), before_stat)

    def test_actual_modern_auxiliary_contract_has_selected_definition_and_exact_real_native_sources(self):
        pin = {'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/writer-own/auxiliary-render-contract-fixture-v2.json'),
            'sha256': '4dc8402f04d106dd4101a69d4bf90e70b369e767e88d2266565018f30676d0d4'}
        fixture = tool.read_json(pin)
        for entity in fixture['entities']:
            usages = [usage for usage in fixture['entity_usages'] if usage['entity_id'] == entity['entity_id']]
            page, proof = tool.render_auxiliary(entity, usages, runtime_url='/actual/chunks.js')
            self.assertEqual(proof['physical_occurrences'], 1)
            self.assertEqual(proof['book_references'], 2)
            for usage in usages:
                selected = tool.auxiliary_definition(entity, usage)
                self.assertEqual(selected['definition_id'], usage['selected_definition_id'])
                self.assertIn(tool.html.escape(selected['meaning_zh']), page)
            self.assertIn('牛津高阶英汉双解词典', page)
            self.assertIn('剑桥高级学习词典', page)
            broken = deepcopy(usages)
            broken[0]['selected_definition_id'] = 'wrong'
            broken[0]['review_seal'] = tool.digest({key: value for key, value in broken[0].items() if key != 'review_seal'})
            with self.assertRaisesRegex(ValueError, 'selected meaning'):
                tool.render_auxiliary(entity, broken, runtime_url='/actual/chunks.js')

    def test_auxiliary_selected_secondary_variant_never_defaults_to_entity_first_native_meaning(self):
        fixture = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/writer-own/auxiliary-render-contract-fixture-v2.json'),
            'sha256': '4dc8402f04d106dd4101a69d4bf90e70b369e767e88d2266565018f30676d0d4'})
        entity = deepcopy(next(entity for entity in fixture['entities'] if entity['lemma'] == 'vice versa'))
        native = entity['dictionary_evidence']['selected']['secondary_bilingual']
        evidence = {'dictionary': native['dictionary'], 'kind': 'native_bilingual_capture', 'capture': native['html_cache']}
        variant = {'definition_id': tool.digest([native, evidence]), 'native_definition': native, 'validated_source_evidence': evidence,
            'meaning_zh': native['original_chinese'], 'meaning_en': native['original_english'], 'contextual_gloss': 'exact secondary bilingual source'}
        entity['definition_variants'].append(variant)
        usage = deepcopy(next(usage for usage in fixture['entity_usages'] if usage['entity_id'] == entity['entity_id']))
        usage.update(selected_definition_id=variant['definition_id'], definition_variants=[variant],
            sense_id=tool.digest([entity['entity_id'], variant['definition_id']]), meaning_zh=variant['meaning_zh'], meaning_en=variant['meaning_en'])
        usage['review_seal'] = tool.digest({key: value for key, value in usage.items() if key != 'review_seal'})
        page, _ = tool.render_auxiliary(entity, [usage], runtime_url='/actual/chunks.js')
        parser = tool.native_api._Offsets(page, {})
        article = next(node for node in parser.root.walk() if 'sf-example' in node.classes)
        label = next(node for node in article.children if 'residual-meaning-source' in node.classes)
        text = tool.sd._Tree(page[label.start:label.end]).root.text()
        self.assertIn('剑桥高级学习词典', text)
        self.assertNotIn('牛津', text)
        self.assertIn(tool.html.escape(variant['meaning_zh']), page[article.start:article.end])

    def test_actual_mixed_native_context_variants_share_lexical_identity_and_select_actual_native_meaning(self):
        fixture = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/writer-own/auxiliary-render-contract-fixture-v3.json'),
            'sha256': '8d76b4ca294786be0c471749474a6c934dd861f9583ea6e5a8dd5b1da0d28e9d'})
        self.assertEqual(len(fixture['entities']), 1)
        entity = fixture['entities'][0]
        self.assertEqual(entity['canonical_identity_kind'], 'lexical_owner')
        self.assertEqual({definition['kind'] for definition in entity['definition_variants']}, {'dictionary_sense', 'contextual_usage'})
        page, proof = tool.render_auxiliary(entity, fixture['entity_usages'], runtime_url='/actual/chunks.js')
        self.assertEqual(proof['physical_occurrences'], 1)
        self.assertEqual(proof['book_references'], 2)
        selected = tool.auxiliary_definition(entity, fixture['entity_usages'][0])
        self.assertEqual(selected['kind'], 'dictionary_sense')
        self.assertIs(selected['is_dictionary_native'], True)
        parser = tool.native_api._Offsets(page, {})
        article = next(node for node in parser.root.walk() if 'sf-example' in node.classes)
        label = next(node for node in article.children if 'residual-meaning-source' in node.classes)
        self.assertNotIn('非词典原义', tool.sd._Tree(page[label.start:label.end]).root.text())
        changed = deepcopy(entity)
        changed['kind'] = 'contextual_usage'
        for usage in fixture['entity_usages']:
            tool.validate_auxiliary(changed, usage)  # Native/context is never the entity identity.
        changed['canonical_identity_kind'] = 'dictionary_sense'
        with self.assertRaisesRegex(ValueError, 'identity kind'):
            tool.render_auxiliary(changed, fixture['entity_usages'], runtime_url='/actual/chunks.js')


if __name__ == '__main__':
    unittest.main()
