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

    def test_failure_quarantines_only_private_stage_with_nonreusable_journal_and_preserves_existing_sources(self):
        plan, _ = tool.prepare(self.request_pin)
        checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
        with patch.object(tool, 'render_card', side_effect=RuntimeError('injected bounded failure')):
            with self.assertRaisesRegex(RuntimeError, 'bounded failure'):
                tool.execute(self.request_pin, checksum, _parallel=False)
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.output.parent.glob('.residual-preview-*')), [])
        failed = list(self.output.parent.glob('.FAILED-residual-preview-*'))
        self.assertEqual(len(failed), 1)
        journal = json.loads((failed[0] / 'failed-journal.json').read_text())
        self.assertEqual(journal['status'], 'FAILED_DO_NOT_PUBLISH')
        self.assertFalse(journal['published'])
        self.assertFalse(journal['reusable'])
        self.assertEqual(journal['completed_cards'], 0)
        self.assertEqual(journal['plan_sha256'], checksum)
        self.assertEqual(journal['error_type'], 'RuntimeError')
        self.assertFalse((failed[0] / 'preview-manifest.json').exists())
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

    def test_actual_both_book_mixed_dictionary_caption_is_structural_and_exactly_invertible(self):
        checked = 0
        root = tool.ROOT / 'output'
        for item in self.plan['affected']:
            if not item['card_id'].startswith(('b9577ffe6b4f', '4cece5f54bb2', '3da8812fb92c', '425f9a85a493')):
                continue
            ledger = tool.read_json(item['ledger_file'])
            catalog = json.loads((root / 'exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay' / item['book_id'] / 'catalog.json').read_text())
            row = next(row for row in catalog['cards'] if row['id'] == item['card_id'])
            source = tool.local_url(row['previewUrl'], root)
            original = source.read_text()
            aliases = tool.class_aliases(source.parent.parent)
            rendered, inverse = tool.dictionary_caption(original, ledger, aliases=aliases)
            mixed = item['card_id'].startswith(('b9577ffe6b4f', '4cece5f54bb2'))
            self.assertEqual(len(inverse), int(mixed))
            self.assertEqual(tool.preview.restore_edits(rendered, inverse), original)
            if mixed:
                self.assertEqual(inverse[0]['original'], '牛津释义')
                self.assertEqual(rendered[inverse[0]['range'][0]:inverse[0]['range'][1]], '释义')
                self.assertIn('剑桥高阶英汉双解词典', rendered)
                self.assertEqual(rendered, original[:inverse[0]['range'][0]] + '释义' + original[inverse[0]['range'][0] + len('牛津释义'):])
            else:
                self.assertEqual(rendered, original)
            self.assertEqual(source.read_text(), original)
            checked += 1
        self.assertEqual(checked, 4)

    def test_actual_both_book_render_composes_dictionary_caption_inverse_with_all_original_layers(self):
        checked = 0
        root = tool.ROOT / 'output'
        for item in self.plan['affected']:
            if not item['card_id'].startswith(('b9577ffe6b4f', '4cece5f54bb2')):
                continue
            before, after, ledger = (tool.read_json(item[key]) for key in ('before_payload_file', 'payload_file', 'ledger_file'))
            catalog = json.loads((root / 'exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay' / item['book_id'] / 'catalog.json').read_text())
            row = next(row for row in catalog['cards'] if row['id'] == item['card_id'])
            source = tool.local_url(row['previewUrl'], root)
            original = source.read_text()
            rendered, _, _, proof, _ = tool.render_card(original, before, after, ledger,
                source_url=row['previewUrl'], target_url='/candidate/' + item['book_id'] + '/web-preview/fixture/cards/' + item['card_id'] + '.html',
                target_urls={entry['id']: entry['previewUrl'] for entry in catalog['cards']},
                aliases=tool.class_aliases(source.parent.parent), exam_base_url='http://localhost:8765')
            self.assertEqual(len(proof['dictionary_caption_inverse']), 1)
            restored = rendered
            for key in ('dictionary_caption_inverse', 'phrase_owner_history_inverse', 'auxiliary_source_inverse',
                        'display_projection_inverse', 'report_inverse'):
                restored = tool.preview.restore_edits(restored, proof[key])
            restored = tool.restore_original(restored, proof['native_inverse'])
            self.assertEqual(tool.preview.restore_edits(restored, proof['base_inverse']), original)
            self.assertEqual(source.read_text(), original)
            checked += 1
        self.assertEqual(checked, 2)

    def test_actual_multiline_completed_sf_pair_preserves_br_binding_new_fine_translation_and_exact_inverse(self):
        diagnosis = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/preview-own/sf-binding-diagnostic-v4.json'),
            'sha256': 'aebc8a335bd7143d70af6b405c78e1f90ecc7c80869295d9be49774facd997a7'})
        item = diagnosis['input_item']
        before, after, ledger = (tool.read_json(item[key]) for key in ('before_payload_file', 'payload_file', 'ledger_file'))
        adapter = tool.load_adapter({'file': str(tool.ROOT / 'anki_pipeline/residual_optimization.py'),
            'sha256': 'fd94049ae02339d090d67be602f0f5749776356ad643d4a15d59e9d4b823b77f'})
        source = tool.checked(diagnosis['source'])
        original = source.read_text()
        catalog = json.loads((tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay/redbook/catalog.json').read_text())
        row = next(row for row in catalog['cards'] if row['id'] == item['card_id'])
        aliases = tool.class_aliases(source.parent.parent)
        rendered, _, _, proof, _ = tool.render_card(original, before, after, ledger,
            source_url=row['previewUrl'], target_url='/candidate/redbook/web-preview/fixture/cards/' + item['card_id'] + '.html',
            target_urls={entry['id']: entry['previewUrl'] for entry in catalog['cards']}, aliases=aliases,
            exam_base_url='http://localhost:8765', adapter=adapter)
        shown = tool.presentation(after, adapter, display_updates=ledger['residual_display_updates'])
        mismatch = diagnosis['mismatches'][0]
        identity = mismatch['occurrence_id']
        expected = next(value['display'] for value in shown['occurrences'] if value['occurrence_id'] == identity)
        parsed = tool.native_api._Offsets(rendered, aliases)
        article = next(node for node in parsed.root.walk() if 'sf-example' in node.classes and
            node.attrs.get('data-sf-occurrence-id') == identity and not tool._inside_history(node))
        pair = next(node for node in article.children if 'sf-sentence-pair' in node.classes)
        tree = tool.sd._Tree(rendered[pair.start:pair.end]).root
        self.assertEqual(tool.sd._text_and_ranges(tool.sd._descendant(tree, 'sf-en'))[0], expected['english'])
        self.assertEqual(tool.sd._text_and_ranges(tool.sd._descendant(tree, 'sf-zh'))[0], expected['translation'])
        self.assertIn('because\nthey', expected['english'])
        self.assertIn('因为', expected['translation'])
        self.assertIn('data-reviewed-chunk-projection="residual"', rendered[pair.start:pair.end])
        self.assertIn('<u class="cloze-answer"', rendered[pair.start:pair.end])
        restored = rendered
        for key in ('dictionary_caption_inverse', 'phrase_owner_history_inverse', 'auxiliary_source_inverse',
                    'display_projection_inverse', 'report_inverse'):
            restored = tool.preview.restore_edits(restored, proof[key])
        restored = tool.restore_original(restored, proof['native_inverse'])
        self.assertEqual(tool.preview.restore_edits(restored, proof['base_inverse']), original)
        self.assertEqual(source.read_text(), original)
        old_pair = '<article class="sf-example" data-sf-occurrence-id="' + identity + '">' + mismatch['pair_html'] + '</article>'
        for tampered in (old_pair.replace('<br>', '', 1), old_pair.replace('<br>', ' ', 1),
                         old_pair.replace('脸书用户', '篡改用户', 1)):
            with self.assertRaisesRegex(ValueError, 'current SF display text binding differs'):
                tool.project_displays(tampered, after, shown)

    def test_actual_common_source_reports_render_change_and_book_with_complete_original_inverse(self):
        receipt = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/preview-own/source-report-preflight-v5.json'),
            'sha256': 'aa1cc8b28c7cbaa4fa536919e76f3a8d53e76429b3a1a4ec494926566c5c0162'})
        request = receipt['request']
        checkpoint = tool.read_json(request['checkpoint'])
        adapter = tool.load_adapter(request['presentation_adapter'])
        catalog = tool.read_json(request['books'][0]['catalog'])
        urls = {row['id']: row['previewUrl'] for row in catalog['cards']}
        selected = [issue for issue in receipt['issues'] if issue['book_id'] == 'redbook' and issue['word'] in {'change', 'book'}]
        self.assertEqual(len(selected), 2)
        with closing(tool.owned_readonly(checkpoint['parent_database']['file'])) as parent, \
                closing(tool.owned_readonly(checkpoint['database']['file'])) as candidate:
            for issue in selected:
                before, after, ledger, documents = tool.load_card_payloads(parent, candidate, issue['input_item'])
                original_before = tool.digest(before)
                source = tool.checked(issue['source'])
                original = source.read_text()
                row = next(row for row in catalog['cards'] if row['id'] == issue['card_id'])
                rendered, _, _, proof, _ = tool.render_card(original, before, after, ledger,
                    source_url=row['previewUrl'], target_url='/candidate/redbook/web-preview/common/cards/' + row['id'] + '.html',
                    target_urls=urls, aliases=tool.class_aliases(source.parent.parent), documents=documents,
                    exam_base_url=request['exam_base_url'], adapter=adapter)
                self.assertTrue(proof['source_report_bridge_certification']['adapted'])
                self.assertEqual(proof['source_report_bridge_certification']['physical_occurrences'], len(before['occurrences']))
                self.assertNotIn('data-residual-source-report-scaffold=', rendered)
                self.assertEqual(tool.digest(before), original_before)
                restored = rendered
                for key in ('dictionary_caption_inverse', 'phrase_owner_history_inverse', 'auxiliary_source_inverse',
                            'display_projection_inverse', 'report_inverse'):
                    restored = tool.preview.restore_edits(restored, proof[key])
                restored = tool.restore_original(restored, proof['native_inverse'])
                restored = tool.preview.restore_edits(restored, proof['source_report_bridge_inverse'])
                self.assertEqual(tool.preview.restore_edits(restored, proof['base_inverse']), original)
                self.assertEqual(source.read_text(), original)

    def test_actual_common_source_bridge_rejects_pos_text_order_snapshot_group_scope_counts_oid_and_bilingual_tampering(self):
        receipt = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/preview-own/source-report-preflight-v5.json'),
            'sha256': 'aa1cc8b28c7cbaa4fa536919e76f3a8d53e76429b3a1a4ec494926566c5c0162'})
        issue = next(issue for issue in receipt['issues'] if issue['book_id'] == 'redbook' and issue['word'] == 'change')
        before = tool.read_json(issue['input_item']['before_payload_file'])
        source = tool.checked(issue['source'])
        original = source.read_text()
        aliases = tool.class_aliases(source.parent.parent)
        parsed = tool.native_api._Offsets(original, aliases)
        meanings = [n for n in parsed.root.walk() if 'sf-meaning' in n.classes and not tool._inside_history(n)]
        pos = meanings[0].descendant('sf-pos')
        count = next(n for n in parsed.root.walk() if 'sf-count' in n.classes and not tool._inside_history(n))
        article = next(n for n in parsed.root.walk() if 'sf-example' in n.classes and not tool._inside_history(n))
        pair = next(n for n in article.children if 'sf-sentence-pair' in n.classes)
        english, chinese = pair.descendant('sf-en'), pair.descendant('sf-zh')
        variants = [
            tool.preview.apply_edits(original, [(pos.opened, pos.closed, 'wrong-pos')])[0],
            tool.preview.apply_edits(original, [(meanings[0].opened, meanings[0].closed, '篡改义项')])[0],
            tool.preview.apply_edits(original, [(meanings[0].opened, meanings[0].closed, original[meanings[1].opened:meanings[1].closed]),
                (meanings[1].opened, meanings[1].closed, original[meanings[0].opened:meanings[0].closed])])[0],
            original.replace('data-snapshot="' + before['snapshot_id'] + '"', 'data-snapshot="' + '0' * 64 + '"', 1),
            tool.preview.apply_edits(original, [(count.opened, count.closed, '999999 次')])[0],
            original.replace('data-sf-occurrence-id="' + article.attrs['data-sf-occurrence-id'] + '"',
                'data-sf-occurrence-id="' + '0' * 64 + '"', 1),
            tool.preview.apply_edits(original, [(english.opened, english.opened, '篡改')])[0],
            tool.preview.apply_edits(original, [(chinese.opened, chinese.opened, '篡改')])[0],
        ]
        for page in variants:
            with self.subTest(case=tool.sf._sha(page)):
                with self.assertRaises(ValueError):
                    tool.source_report_bridge(page, before, aliases=aliases)
        for kind in ('group', 'scope'):
            broken = deepcopy(before)
            if kind == 'group':
                broken['sense_group_equivalences'][0]['member_sense_ids'] = ['0' * 64]
            else:
                broken['definition_provenance']['components'][0]['sense_count'] -= 1
            with self.assertRaises(ValueError):
                tool.source_report_bridge(original, broken, aliases=aliases)

    def test_actual_common_source_bridge_rejects_swapped_members_with_unchanged_component_labels_counts_and_oids(self):
        receipt = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/preview-own/source-report-preflight-v5.json'),
            'sha256': 'aa1cc8b28c7cbaa4fa536919e76f3a8d53e76429b3a1a4ec494926566c5c0162'})
        issue = next(issue for issue in receipt['issues'] if issue['book_id'] == 'redbook' and issue['word'] == 'change')
        before = tool.read_json(issue['input_item']['before_payload_file'])
        source = tool.checked(issue['source'])
        original = source.read_text()
        aliases = tool.class_aliases(source.parent.parent)
        parsed = tool.native_api._Offsets(original, aliases)
        report = next(n for n in parsed.root.walk() if 'sf-report' in n.classes)
        groups = [n for n in report.children if 'sf-sense' in n.classes]
        left, right = [next(n for n in group.walk() if 'sf-example' in n.classes and not tool._inside_history(n))
                       for group in groups[:2]]
        swapped = tool.preview.apply_edits(original, [(left.start, left.end, original[right.start:right.end]),
            (right.start, right.end, original[left.start:left.end])])[0]
        with self.assertRaisesRegex(ValueError, 'source report common group membership differs'):
            tool.source_report_bridge(swapped, before, aliases=aliases)

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


class ActualNativeGuardBridgeTests(unittest.TestCase):
    BASE = tool.ROOT / 'output/residual-optimization-20261013/engineering/preview-own'

    def issues(self):
        return [item for name, sha in (
            ('native-context-target-preflight-v7.json', '37e8be727764a86f8dc682de2a9e0847a287c04d5eb83a6be203cbccb2a08318'),
            ('native-context-target-preflight-2027-v7.json', '7bc43840c2bc14c854cd0cd87482d26d0e6ba0ec8befdaca8b55d2c71d8dc0f6'))
            for item in tool.read_json({'file': str(self.BASE / name), 'sha256': sha})['issues']]

    def catalog(self, book):
        return json.loads((tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/owner-source-display-v5/final-overlay' /
            book / 'catalog.json').read_text())

    def documents(self, after, ledger):
        checkpoint = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/integration/root-full-apply-result-v3.json'),
            'sha256': '237ada59116cb63160102206a05b1a6e118fc0da7f400f7582d381c942342377'})
        with closing(tool.owned_readonly(checkpoint['database']['file'])) as db:
            documents = tool.history_documents(db, after)
        documents.update(ledger.get('render_context', {}).get('ownership_history_documents', {}))
        return documents

    def restore(self, page, proof):
        for key in ('dictionary_caption_inverse', 'phrase_owner_history_inverse', 'auxiliary_source_inverse',
                    'display_projection_inverse', 'report_inverse', 'residual_native_rebind_inverse'):
            page = tool.preview.restore_edits(page, proof[key])
        page = tool.restore_original(page, proof['native_inverse'])
        for key in ('native_missing_mark_inverse', 'source_report_bridge_inverse', 'base_inverse'):
            page = tool.preview.restore_edits(page, proof[key])
        return page

    def test_actual_all_twelve_missing_guard_cases_render_six_cards_with_final_marks_counts_and_full_inverse(self):
        seen, checked = set(), 0
        issues = self.issues()
        adapter = tool.load_adapter({'file': str(tool.ROOT / 'anki_pipeline/residual_optimization.py'),
            'sha256': 'fd94049ae02339d090d67be602f0f5749776356ad643d4a15d59e9d4b823b77f'})
        self.assertEqual(len(issues), 12)
        for issue in issues:
            if issue['card_id'] in seen:
                continue
            seen.add(issue['card_id'])
            item = issue['input_item']
            before, after, ledger = (tool.read_json(item[key]) for key in ('before_payload_file', 'payload_file', 'ledger_file'))
            saved = (tool.digest(before), tool.digest(after))
            source = tool.checked(issue['source']); original = source.read_text()
            aliases = tool.source_class_aliases(original, tool.class_aliases(source.parent.parent))
            catalog = self.catalog(issue['book_id']); row = next(r for r in catalog['cards'] if r['id'] == item['card_id'])
            rendered, frequency, _, proof, _ = tool.render_card(original, before, after, ledger,
                source_url=row['previewUrl'], target_url='/candidate/' + issue['book_id'] + '/web-preview/native/cards/' + row['id'] + '.html',
                target_urls={r['id']: r['previewUrl'] for r in catalog['cards']}, aliases=aliases,
                exam_base_url='http://localhost:8765', adapter=adapter, documents=self.documents(after, ledger))
            expected = 1 if issue['word'] in {'new', 'much'} else 4 if issue['book_id'] == 'redbook2027' else 3
            self.assertEqual(proof['native_missing_mark_certification']['temporary_marks'], expected)
            self.assertGreater(proof['native_stats']['native_examples'], 0)
            self.assertEqual(frequency['occurrences'], len(after['occurrences']))
            final = list(tool._native_nodes(rendered, aliases))
            for failure in (f for f in issues if f['card_id'] == issue['card_id']):
                expected_native = failure['native']
                matches = [native for _, native in final if native['jump'] == expected_native['jump'] and
                    native['english'] == expected_native['english'] and native['translation'] == expected_native['translation']]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]['target_ranges'], expected_native['target_ranges'])
            self.assertEqual(self.restore(rendered, proof), original)
            self.assertEqual((tool.digest(before), tool.digest(after)), saved)
            self.assertEqual(source.read_text(), original)
            checked += 1
        self.assertEqual(checked, 6)

    def test_actual_missing_mark_unknown_reviewed_authority_and_exact_source_tampering_still_reject(self):
        issue = self.issues()[0]; item = issue['input_item']
        before, after = (tool.read_json(item[k]) for k in ('before_payload_file', 'payload_file'))
        source = tool.checked(issue['source'])
        aliases = tool.source_class_aliases(source.read_text(), tool.class_aliases(source.parent.parent))
        fragment = issue['native_markup']
        projected, inverse, proof = tool.native_missing_mark_bridge(fragment, before, after, aliases=aliases)
        self.assertEqual(proof['temporary_marks'], 1)
        self.assertEqual(tool.preview.restore_edits(projected, inverse), fragment)
        identity = proof['bindings'][0]['occurrence_id']
        for kind in ('unknown', 'authority', 'reviewed'):
            old, new = deepcopy(before), deepcopy(after)
            for prepared in (old, new):
                entry = next(x for x in prepared['exam_usage_policy']['excluded'] if x['occurrence']['occurrence_id'] == identity)
                if kind == 'unknown':
                    entry['authority'].pop('legacy_projection_proof')
                elif kind == 'authority':
                    entry['authority']['decision_sha256'] = '0' * 64
                else:
                    entry['occurrence']['status'] = 'reviewed'
                prepared.pop('snapshot_id'); prepared['snapshot_id'] = tool.digest(prepared)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                shaped, _, _ = tool.native_missing_mark_bridge(fragment, old, new, aliases=aliases)
                tool.update_native_examples(shaped, old, new, aliases=aliases)
        for bad in (fragment.replace('New England', 'Nex England'), fragment.replace('新英格兰', '旧英格兰')):
            shaped, _, rejected = tool.native_missing_mark_bridge(bad, before, after, aliases=aliases)
            self.assertEqual(rejected['bindings'], [])  # A different pair is never projected.
            self.assertEqual(shaped, bad)
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'altered.html'; path.write_text(bad)
                with self.assertRaises(ValueError):
                    tool.checked({'file': str(path), 'sha256': tool.sf._sha(fragment)})

    def companions(self):
        return tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/engineering/writer-own/go-at-native-companion-display-handoff-v1.json'),
            'sha256': '9847609ab1019153b0528ffe9a9237ae41341bc7ffdf39772094b20a60dfe33d'})['cases']

    def test_actual_both_book_companion_native_and_sf_keep_two_full_histories_fine_jump_and_199_plus_one(self):
        for case in self.companions():
            before, after, ledger = (tool.read_json(case[k]) for k in ('before_pin', 'after_pin', 'ledger_pin'))
            saved = (tool.digest(before), tool.digest(after))
            catalog = self.catalog(case['book_id']); row = next(r for r in catalog['cards'] if r['id'] == case['card_id'])
            source = tool.local_url(row['previewUrl'], tool.ROOT / 'output'); original = source.read_text()
            aliases = tool.source_class_aliases(original, tool.class_aliases(source.parent.parent))
            rendered, frequency, _, proof, _ = tool.render_card(original, before, after, ledger,
                source_url=row['previewUrl'], target_url='/candidate/' + case['book_id'] + '/web-preview/native/cards/' + row['id'] + '.html',
                target_urls={r['id']: r['previewUrl'] for r in catalog['cards']}, aliases=aliases,
                exam_base_url='http://localhost:8765')
            self.assertEqual((proof['ordinary_native_occurrences'], proof['residual_native_occurrences'],
                proof['authoritative_sf_occurrences'], frequency['occurrences']), (199, 1, 200, 200))
            binding = proof['residual_native_rebind'][0]
            self.assertEqual(binding['target_range'], [71, 79])
            self.assertEqual(binding['translation_ranges'], [[51, 53]])
            natives = [(n, data) for n, data in tool._native_nodes(rendered, aliases)
                if data['jump'] == binding['preserved_native_jump']]
            self.assertEqual(len(natives), 1)
            node, native = natives[0]
            self.assertEqual(native['target_ranges'], [[71, 79]])
            self.assertEqual(native['jump']['target_ranges'], [[71, 76]])
            en_fragment = rendered[node.descendant('example-text').opened:node.descendant('example-text').closed]
            zh_fragment = rendered[node.descendant('example-translation').opened:node.descendant('example-translation').closed]
            self.assertIn('data-chunk-ids="4"', en_fragment)
            self.assertIn('data-chunk-ids="4"', zh_fragment)
            self.assertIn(' at', en_fragment)
            self.assertIn('deserts', en_fragment)
            original_row = ledger['companion_replacements'][0]['companion_parent_row']
            chunk = next(x for x in original_row['display']['alignment']['alignments'] if x['en'] == [71, 87])
            self.assertEqual(chunk['zh'], [[51, 55]])
            self.assertEqual(binding['preserved_fine_alignment_sha256'], tool.digest(original_row['display']['alignment']))
            for fragment, expected_chunk in ((en_fragment, native['english'][71:87]),
                                             (zh_fragment, native['translation'][51:55])):
                fine_text = ''.join(n.text() for n in tool.sd._Tree(fragment).root.walk()
                    if n.has_class('card-chunk') and n.attrs.get('data-chunk-ids') == '4')
                self.assertEqual(fine_text, expected_chunk)
            tree = tool.native_api._Offsets(rendered, aliases)
            sf = next(n for n in tree.root.walk() if 'sf-example' in n.classes and
                n.attrs.get('data-sf-occurrence-id') == binding['canonical_occurrence_id'] and not tool._inside_history(n))
            for container in (node, sf):
                body = rendered[container.start:container.end]
                self.assertIn('本句完整词组转归依据', body)
                self.assertEqual(len([n for n in container.walk() if 'sf-archived-example' in n.classes]), 2)
                for key in ('source_parent_row', 'companion_parent_row'):
                    self.assertIn(tool.html.escape(tool.canonical(ledger['companion_replacements'][0][key])), body)
            self.assertEqual(self.restore(rendered, proof), original)
            self.assertEqual((tool.digest(before), tool.digest(after)), saved)

    def test_companion_missing_duplicate_mark_history_range_sense_and_unlicensed_new_owner_reject(self):
        case = self.companions()[0]
        before, after, ledger = (tool.read_json(case[k]) for k in ('before_pin', 'after_pin', 'ledger_pin'))
        catalog = self.catalog(case['book_id']); source = tool.local_url(next(r['previewUrl'] for r in catalog['cards'] if r['id'] == case['card_id']), tool.ROOT / 'output')
        page = source.read_text(); aliases = tool.source_class_aliases(page, tool.class_aliases(source.parent.parent))
        old, new, bindings = tool.residual_native_companions(page, before, after, ledger, aliases=aliases)
        self.assertEqual((len(old['occurrences']), len(new['occurrences'])), (199, 199))
        node, _ = next((n, data) for n, data in tool._native_nodes(page, aliases)
            if data['jump'] == bindings[0]['native']['jump'])
        fragment = page[node.start:node.end]
        for bad in (page[:node.start] + page[node.end:], page[:node.end] + fragment + page[node.end:],
                    page[:node.start] + fragment.replace('target-word', 'removed-target-word', 1) + page[node.end:]):
            with self.assertRaises(ValueError):
                tool.residual_native_companions(bad, before, after, ledger, aliases=aliases)
        for kind in ('history', 'range', 'sense'):
            broken = deepcopy(after)
            row = next(r for r in broken['occurrences'] if r['occurrence_id'] == case['canonical_occurrence_id'])
            if kind == 'history':
                row['semantic_review']['residual_owner_history']['history_sha256'] = '0' * 64
            elif kind == 'range':
                row['translation_ranges'] = [[51, 55]]
            else:
                row['sense_id'] = row['reviewed_sense_id'] = broken['senses'][0]['sense_id']
            broken.pop('snapshot_id'); broken['snapshot_id'] = tool.digest(broken)
            with self.assertRaises(ValueError):
                tool.residual_native_companions(page, before, broken, ledger, aliases=aliases)
        unknown = deepcopy(new)
        incoming = deepcopy(after['occurrences'][76]); incoming.pop('semantic_review'); unknown['occurrences'].append(incoming)
        unknown['expected_occurrences'] += 1; unknown.pop('snapshot_id'); unknown['snapshot_id'] = tool.digest(unknown)
        with self.assertRaisesRegex(ValueError, 'complete validated sentence history'):
            tool.owner._native_owner_projection(old, unknown, {}, {})

    def test_inline_native_class_map_is_literal_bounded_conflict_checked_and_retains_original_script(self):
        issue = next(f for f in self.issues() if f['book_id'] == 'redbook2027')
        original = tool.checked(issue['source']).read_text()
        aliases = tool.source_class_aliases(original)
        self.assertEqual(len(aliases), 45)
        self.assertGreater(len(list(tool._native_nodes(original, aliases))), 0)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            tool.source_class_aliases(original, {'_r28': 'wrong-class'})
        with self.assertRaisesRegex(ValueError, 'malformed'):
            tool.source_class_aliases('<script>var x={"classes":{"_r0":"<script>"}};</script>')
        self.assertEqual(tool.source_class_aliases('<div data-json=\'{"classes":{"_r1":"example-card"}}\'></div>'), {})


class SpawnPreviewTests(ResidualPreviewTests):
    """Real spawn, tiny two-book sources; no production/page/database copies."""
    # Inherit fixtures, not the old suite's methods.
    def test_same_final_urls_serial_and_real_spawn_have_identical_all_output_bytes(self):
        plan, _ = tool.prepare(self.request_pin)
        checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
        tool.execute(self.request_pin, checksum, _parallel=False)
        serial = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        shutil.rmtree(self.output)  # Only this temporary test fixture, identical final URLs.
        tool.execute(self.request_pin, checksum)
        parallel = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        self.assertEqual(parallel, serial)
        rows = [json.loads(raw) for raw in parallel['card-proofs.jsonl'].splitlines()]
        self.assertEqual([row['book_id'] for row in rows], ['redbook', 'redbook2027'])

    def test_real_spawn_second_worker_failure_joins_children_and_quarantines_without_publication(self):
        path, original = self.pages['redbook2027']
        path.write_text(original.replace('</head>', '<base href="/extra.html"></head>'))
        plan, _ = tool.prepare(self.request_pin)
        checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
        with self.assertRaisesRegex(RuntimeError, 'redbook2027.*multiple base'):
            tool.execute(self.request_pin, checksum)
        self.assertFalse(self.output.exists())
        failed = list(self.output.parent.glob('.FAILED-residual-preview-*'))
        self.assertEqual(len(failed), 1)
        self.assertFalse(json.loads((failed[0] / 'failed-journal.json').read_text())['reusable'])
        self.assertEqual(json.loads((failed[0] / 'redbook2027/.worker-failure.json').read_text())['status'], 'FAILED')
        self.assertFalse(any(p.name.startswith('residual-preview-') for p in tool.multiprocessing.active_children()))
        self.assertEqual(self.pages['redbook'][0].read_text(), self.pages['redbook'][1])

    def test_completion_order_is_ignored_and_exact_proof_order_and_file_namespace_are_guarded(self):
        plan, _ = tool.prepare(self.request_pin)
        stage = self.root / 'private-stage'; stage.mkdir()
        results = tool.run_book_workers(self.request_pin, ['redbook', 'redbook2027'], stage, plan)
        reversed_results = {book: results[book] for book in ('redbook2027', 'redbook')}
        self.assertEqual(list(reversed_results), ['redbook2027', 'redbook'])
        files = {}
        count, _, _ = tool.merge_book_worker_proofs(stage, ['redbook', 'redbook2027'], reversed_results, plan, files)
        self.assertEqual(count, 2)
        self.assertEqual([json.loads(raw)['book_id'] for raw in (stage / 'card-proofs.jsonl').read_text().splitlines()],
            ['redbook', 'redbook2027'])
        self.assertFalse(any(p.name.startswith('residual-preview-') for p in tool.multiprocessing.active_children()))

    def test_post_worker_source_code_or_database_sidecar_drift_rejects_before_any_publish(self):
        real = tool.run_book_workers
        for kind in ('source', 'code', 'sidecar'):
            with self.subTest(kind=kind):
                path, original = self.pages['redbook']
                def drift(*args, **kwargs):
                    result = real(*args, **kwargs)
                    if kind == 'source':
                        path.write_text(original + '<!-- changed -->')
                    elif kind == 'sidecar':
                        Path(str(self.candidate) + '-wal').write_text('external writer')
                    else:
                        # A temporary watched asset tests code-byte drift. No
                        # real source/module is modified by this test.
                        self.runtime.write_bytes(self.runtime.read_bytes() + b'\n// changed')
                    return result
                plan, _ = tool.prepare(self.request_pin)
                checksum = hashlib.sha256((tool.canonical(plan) + '\n').encode()).hexdigest()
                raw_runtime = self.runtime.read_bytes()
                with patch.object(tool, 'run_book_workers', side_effect=drift), self.assertRaises(ValueError):
                    tool.execute(self.request_pin, checksum)
                self.assertFalse(self.output.exists())
                self.assertFalse(any(p.name.startswith('residual-preview-') for p in tool.multiprocessing.active_children()))
                path.write_text(original); self.runtime.write_bytes(raw_runtime)
                wal = Path(str(self.candidate) + '-wal')
                if wal.exists(): wal.unlink()

    def test_tiny_actual_metadata_cache_hit_and_input_stat_or_helper_drift_reject(self):
        for index, item in enumerate(self.affected):
            item['before_payload_file'] = save(self.root / item['book_id'] / 'before.json', self.before[index])
        self.refresh_request()
        witness_request = save(self.root / 'metadata-request.json', self.request)
        stats = {'checked_cards': 2, 'checked_sides': 4, 'history_rows': 0, 'histories': 0, 'verified_history_rows': 0}
        with closing(tool.owned_readonly(self.parent)) as old, closing(tool.owned_readonly(self.candidate)) as new:
            for index in range(2):
                for prepared, db in ((self.before[index], old), (self.after[index], new)):
                    self.assertEqual(tool.native_history_metadata(prepared, db, {})['failures'], [])
        database_stats = [tool.database_stat(path) for path in (self.parent, self.candidate)]
        evidence = save(self.root / 'native-preflight.json', {'schema': 'native-ownership-history-metadata-preflight.v1',
            'status': 'PASS', 'failures': [], 'request': witness_request, 'stats': stats,
            'database_stat_before': database_stats, 'database_stat_after': database_stats, 'watched_pins': []})
        cache = {'schema': 'native-history-preflight-cache.v1', 'evidence': evidence,
            'context': tool.native_history_context(self.request), 'helper_binding': tool.native_history_helper_binding(),
            'database_stats': database_stats,
            'payload_pins': [item[field] for item in self.affected for field in ('before_payload_file', 'payload_file', 'ledger_file')]}
        self.request['native_history_preflight'] = save(self.root / 'native-cache.json', cache)
        self.request_pin = save(self.root / 'request.json', self.request)
        hit = tool.reuse_native_history_preflight(self.request, self.checkpoint, {})
        self.assertEqual(hit['verified_history_rows'], 0)
        plan, _ = tool.prepare(self.request_pin); tool.check_guards(plan)
        self.assertIn('reused_evidence', plan['native_history_preflight'])
        with patch.object(tool, 'native_history_helper_binding', return_value={'helper_sha256': '0' * 64}):
            with self.assertRaisesRegex(ValueError, 'helper'):
                tool.reuse_native_history_preflight(self.request, self.checkpoint, {})
        bad = deepcopy(self.request); bad['native_history_preflight']['sha256'] = '0' * 64
        with self.assertRaises(ValueError): tool.reuse_native_history_preflight(bad, self.checkpoint, {})
        changed = deepcopy(self.checkpoint); changed['cards'][0]['payload_file']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'inventory'):
            tool.reuse_native_history_preflight(self.request, changed, {})
        with patch.object(tool, 'database_stat', return_value={**database_stats[0], 'mtime_ns': 0}):
            with self.assertRaises(ValueError): tool.reuse_native_history_preflight(self.request, self.checkpoint, {})


class NativeVariantTransportTests(unittest.TestCase):
    PIN = {'file': str(tool.ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/edge-own/native-variant-addendum.json'),
        'sha256': '019d20c84e973eb4f48dd303b4a313d212846e8c7e2de20f8deb259733763aa0'}

    def test_actual_variant_transport_preserves_exact_pin_watches_dependencies_and_never_hydrates_dataless_reference(self):
        watched, observation = {}, {}
        value = tool.native_variant_transport({'native_variant_addendum': self.PIN}, watched, observation)
        self.assertEqual(value, self.PIN)
        self.assertEqual(watched[self.PIN['file']], self.PIN['sha256'])
        body = tool.read_json(self.PIN)
        self.assertEqual(watched[body['frozen_primary_decisions_pin']['file']], body['frozen_primary_decisions_pin']['sha256'])
        for skipped in observation['unread_dataless_references']:
            self.assertNotIn(skipped['reference']['file'], watched)
            self.assertFalse(skipped['file_bytes_read'])
            self.assertEqual(skipped['pin_basis'], 'indexed_native_entry_utf8_sha256')
        with self.assertRaises(ValueError):
            tool.native_variant_transport({'native_variant_addendum': {**self.PIN, 'sha256': '0' * 64}})
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'addendum.json'
            body['affected_decisions'][0]['target_range'] = [0, 1]
            broken.write_text(tool.canonical(body))
            aliases = tool.owner.load_native_variant_addendum(tool.pin(broken))
            decision = next(iter(aliases.values()))['frozen_decisions'][body['affected_decisions'][0]['input_id']]
            self.assertNotEqual(body['affected_decisions'][0]['target_range'], decision['target']['target_range'])
            # The existing licensed-span replay, not a permissive transport,
            # remains responsible for rejecting this changed authorization.

    def fixture(self):
        request = tool.read_json({'file': str(tool.ROOT / 'output/residual-optimization-20261013/integration/root-preview-request-v3.json'),
            'sha256': '57dfcc676900fc024ce1c01e90397ad3f65bb3694f80d9b5d5fc1f1c9cff4734'})
        checkpoint = tool.read_json(request['checkpoint'])
        return request, checkpoint

    def test_actual_offline_both_books_missing_transport_rejects_and_exact_transport_replays_full_native_history_and_inverse(self):
        request, checkpoint = self.fixture()
        with closing(tool.owned_readonly(checkpoint['database']['file'])) as db:
            for item in (x for x in checkpoint['cards'] if x['word'] == 'offline'):
                before, after, ledger = (tool.read_json(item[k]) for k in ('before_payload_file', 'payload_file', 'ledger_file'))
                docs = tool.history_documents(db, after)
                rejected = tool.native_history_metadata(after, db, ledger, documents=docs)
                self.assertTrue(rejected['failures'])
                self.assertIn('hyphen variant addendum', rejected['failures'][0]['error'])
                variant = tool.native_variant_transport({'native_variant_addendum': self.PIN})
                accepted = tool.native_history_metadata(after, db, ledger, variant_pin=variant, documents=docs)
                self.assertEqual(accepted['failures'], [])
                docs['__owner_recovery_native_variant_addendum__'] = variant
                book = next(b for b in request['books'] if b['book_id'] == item['book_id'])
                catalog = tool.read_json(book['catalog'])
                row = next(r for r in catalog['cards'] if r['id'] == item['card_id'])
                source = tool.local_url(row['previewUrl'], Path(request['web_root'])); original = source.read_text()
                rendered, frequency, _, proof, _ = tool.render_card(original, before, after, ledger,
                    source_url=row['previewUrl'], target_url='/candidate/' + item['book_id'] + '/web-preview/variant/cards/' + row['id'] + '.html',
                    target_urls={r['id']:r['previewUrl'] for r in catalog['cards']}, documents=docs,
                    aliases=tool.class_aliases(source.parent.parent), exam_base_url=request['exam_base_url'])
                self.assertEqual(frequency['occurrences'], 1)
                self.assertEqual(ActualNativeGuardBridgeTests().restore(rendered, proof), original)

    def test_changed_addendum_scope_still_fails_actual_current_native_history_guard(self):
        _, checkpoint = self.fixture()
        item = next(x for x in checkpoint['cards'] if x['word'] == 'offline')
        after, ledger = (tool.read_json(item[k]) for k in ('payload_file', 'ledger_file'))
        body = tool.read_json(self.PIN)
        for scope in body['affected_decisions']:
            if scope['canonical_headword'] == 'offline' and scope['book_id'] == item['book_id']:
                scope['target_range'] = [0, 1]
        with tempfile.TemporaryDirectory() as tmp, closing(tool.owned_readonly(self.fixture()[1]['database']['file'])) as db:
            altered = Path(tmp) / 'addendum.json'; altered.write_text(tool.canonical(body))
            result = tool.native_history_metadata(after, db, ledger, variant_pin=tool.pin(altered))
            self.assertTrue(result['failures'])
            self.assertIn('authorization differs', result['failures'][0]['error'])


if __name__ == '__main__':
    unittest.main()
