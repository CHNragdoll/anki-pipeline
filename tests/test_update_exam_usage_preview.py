"""Bounded real SQLite and reversible-page checks for the new update tool."""
from copy import deepcopy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import exam_usage_policy as policy, sense_frequency as sf
from anki_pipeline.packaging import _exam_frequency_markup
from scripts import update_exam_usage_preview as tool
from tests.test_sense_frequency import record


def write_json(path, value):
    path.write_text(tool.canonical(value) + '\n')
    return {'file': str(path), 'sha256': tool.file_sha(path)}


def page_for(value):
    data = sf.prepare_record(value)
    frequency = tool._frequency(data['occurrences'])
    css = Path(sf.__file__).with_name('templates').joinpath('sense-frequency.css').read_text()
    return ('<!doctype html><html><head><style data-supplement-preview="style">' + css +
            '</style></head><body><h4 data-source="original">牛津原释义</h4>' +
            _exam_frequency_markup({'exam_frequency': frequency}) + sf.render_report(sf.report_from_record(data)) +
            '<img src="../assets/pinned.svg"><a href="../sources/entry.html">原条目</a></body></html>')


class UsageUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.web = self.root / 'web'
        self.accepted = self.web / 'accepted'
        (self.accepted / 'cards').mkdir(parents=True)
        self.before = record()
        for row in self.before['occurrences']:
            row['source_provenance']['sourcePathEvidence'] = {'kind': 'reading'}
        self.before['occurrences'] = [sf.seal_reviewed_assignment(self.before, row) for row in self.before['occurrences']]
        self.old_db = self.root / 'accepted.sqlite3'
        sf.save_records(self.old_db, [self.before], self.root / 'backups')
        self.old_bytes = self.old_db.read_bytes()
        self.card = {'id': self.before['card_id'], 'word': 'novel', 'deckId': 'deck',
                     'deckName': '词卡', 'definition': 'n. 小说 adj. 新颖的', 'exampleCount': 2,
                     'previewUrl': '/accepted/cards/novel.html'}
        self.source_page = self.accepted / 'cards/novel.html'
        self.source_page.write_text(page_for(self.before))
        self.catalog = {'cards': [self.card], 'decks': [{'id': 'deck', 'name': '词卡', 'cardIds': [self.card['id']], 'count': 1}],
                        'counts': {'cards': 1, 'decks': 1, 'examples': 2}, 'schema': 'fixture', 'deckName': '词卡'}
        self.catalog_pin = write_json(self.accepted / 'catalog.json', self.catalog)
        self.entry = self.accepted / 'preview-library.html'
        self.entry.write_text('<html><head></head><body><div data-catalog-url="catalog.json"></div></body></html>')
        self.policy_pin = write_json(self.root / 'policy.json', {'cards': []})
        self.request = {'schema': tool.SCHEMA, 'source_database': {'file': str(self.old_db), 'sha256': tool.file_sha(self.old_db)},
                        'web_root': str(self.web), 'new_database': str(self.root / 'new.sqlite3'),
                        'trial_output': str(self.web / 'trial'), 'policies': self.policy_pin,
                        'books': [{'book_id': self.before['book_id'], 'entry': {'file': str(self.entry), 'sha256': tool.file_sha(self.entry)},
                                   'catalog': self.catalog_pin, 'expected_cards': 1, 'output': str(self.web / 'full')}]}

    def invoke(self, **kwargs):
        pin = write_json(self.root / 'request.json', self.request)
        return tool.update(pin['file'], pin['sha256'], **kwargs)

    def test_repeated_report_hint_removal_preserves_complete_nested_history_bytes(self):
        history = ('<details class="sf-ownership-history"><summary>本句归属说明</summary>'
                   '<details class="sf-original-history-panel"><p class="sf-hint">'
                   '原匹配位置 299 处；已核实错归 6 处，完整原审核依据。</p></details></details>')
        global_hint = '<p class="sf-hint">当前报告重复的全局说明</p>'
        before = sf.prepare_record(self.before)
        report = sf.report_from_record(before)
        reports = [sf.render_report({**report, 'senses': [sense]}) for sense in report['senses']]
        page = page_for(self.before).replace(sf.render_report(report), ''.join(reports))
        changed = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        fake = '<section class="sf-report">' + global_hint + '<article>' + history + '</article></section>'
        with patch.object(sf, 'render_report', return_value=fake):
            rendered, inverse, _, _ = tool.render_page(page, before, sf.prepare_record(changed['record']),
                changed['scope_ledger'], source_url='/accepted/novel.html', target_url='/new/novel.html')
        self.assertEqual(rendered.count(history), 2)
        self.assertEqual(rendered.count(global_hint), 1)
        self.assertEqual(tool.restore_edits(rendered, inverse), page)

    def test_global_hint_removal_never_enters_archived_nested_sf_report(self):
        hint = '<p class="sf-hint">当前重复说明</p>'
        archived = ('<details class="sf-ownership-history"><summary>本句归属说明</summary>'
                    '<details class="sf-original-history-panel"><section class="sf-report">'
                    '<p class="sf-hint">旧报告的完整原审核依据。</p></section></details></details>')
        page = '<section class="sf-report">' + hint + archived + '</section>'
        with patch.object(sf, 'render_report', return_value=page):
            rendered = tool._render_without_global_hint({})
        self.assertEqual(rendered, '<section class="sf-report">' + archived + '</section>')

    def test_original_paper_link_is_added_only_to_current_owner_sentence(self):
        archived = ('<details class="sf-ownership-history"><article class="sf-example" '
                    'data-sf-occurrence-id="same"><p class="sf-source">旧完整出处</p></article></details>')
        page = ('<section class="sf-report"><article class="sf-example" data-sf-occurrence-id="same">'
                '<p class="sf-source">当前原出处</p>' + archived + '</article></section>')
        jump = {'reader': 'full-paper', 'latex_url': 'http://localhost:8765/paper.htm?source=raw',
                'full_paper_url': 'http://localhost:8765/full-paper.htm?source=raw'}
        with patch.object(sf, 'render_report', return_value=page):
            rendered = tool._render_with_source_jumps({}, {'same': jump})
        self.assertEqual(rendered.count('class="sentence-jump"'), 1)
        self.assertIn(archived, rendered)
        self.assertIn('http://localhost:8765/full-paper.htm?source=raw', rendered)
        with patch.object(sf, 'render_report', return_value=page):
            with self.assertRaises(ValueError):
                tool._render_with_source_jumps({}, {'same': {**jump, 'full_paper_url': 'javascript:alert(1)'}})

    def test_restored_owner_history_keeps_old_failed_audit_without_stale_current_note(self):
        from tests.test_ownership_history import fixture
        from anki_pipeline.ownership_history import bind_incoming_history
        before=sf.prepare_record(self.before); _,transfer=fixture(before)
        failed={'reason':'旧未绑定提示token','transfer':deepcopy(transfer)}
        bound=bind_incoming_history(before,[transfer]);bound['ownership_history_unresolved']=[failed]
        after=sf.prepare_record(policy.producer_record(bound,preserve_scope=False)); original=deepcopy(after)
        page,proof,_,_=tool.render_page(self.source_page.read_text(),before,after,{'excluded':[]},
            source_url=self.card['previewUrl'],target_url='/new/novel.html')
        self.assertNotIn('旧未绑定提示token',page)
        self.assertIn('完整旧错归解释',page)
        self.assertEqual(after,original)
        self.assertEqual(after['ownership_history_unresolved'],[failed])
        self.assertEqual(tool.restore_edits(page,proof),self.source_page.read_text())
        different=deepcopy(after);different['ownership_history_unresolved'][0]['transfer']['source_card_id']='different-source'
        other,_,_,_=tool.render_page(self.source_page.read_text(),before,different,{'excluded':[]},
            source_url=self.card['previewUrl'],target_url='/new/novel.html')
        self.assertIn('旧未绑定提示token',other)

    def _render_continuation_fixture(self):
        code = self.root / 'writer-code.py'
        code.write_bytes(b'accepted original writer bytes\n')
        old_pin = {'file': str(code), 'sha256': tool.file_sha(code)}
        self.request.setdefault('code_pins', {})['writer'] = old_pin
        checkpoint = self._fail_after_committed_database()
        payload = json.loads(checkpoint.read_text())
        backup = self.root / 'accepted-writer-backup.py'
        backup.write_bytes(code.read_bytes())
        code.write_bytes(b'approved presentation-only writer bytes\n')
        proof = write_json(self.root / 'independent-follow-proof.json', {'valid': True, 'scope': 'follow exact history'})
        approval = {'schema': 'exam-usage-render-code-continuation.v1',
            'scope': 'writer_report_hint_presentation_only',
            'request': payload['request'], 'prepared_checkpoint': {'file': str(checkpoint.resolve()), 'sha256': tool.file_sha(checkpoint)},
            'run_id': payload['run_id'], 'database': payload['database'],
            'original_code_pins': payload['code_pins'],
            'writer_change': {'old': old_pin, 'new': {'file': str(code), 'sha256': tool.file_sha(code)},
                              'backup': {'file': str(backup), 'sha256': old_pin['sha256']}},
            'proof_pins': [proof]}
        pin = write_json(self.root / 'render-continuation.json', approval)
        return checkpoint, code, approval, pin

    def test_explicit_render_code_continuation_reuses_exact_database_and_original_run(self):
        checkpoint, code, approval, pin = self._render_continuation_fixture()
        db = self.root / 'new.sqlite3'
        before = db.read_bytes(), checkpoint.read_bytes()
        with patch.object(tool, '__file__', str(code)), \
             patch.object(policy, 'transform_record', side_effect=AssertionError('no reprepare')), \
             patch.object(tool, 'insert_prepared', side_effect=AssertionError('no insert')), \
             patch.object(sqlite3, 'connect', wraps=sqlite3.connect) as connect:
            result = tool.resume_render(checkpoint, tool.file_sha(checkpoint),
                continuation_path=pin['file'], continuation_sha256=pin['sha256'])
        self.assertTrue(all('mode=ro' in str(call.args[0]) and call.kwargs.get('uri') for call in connect.call_args_list))
        self.assertEqual((db.read_bytes(), checkpoint.read_bytes()), before)
        self.assertEqual(result['run_id'], approval['run_id'])
        self.assertEqual(result['render_code_continuation']['approval'],
                         {**pin, 'file': str(Path(pin['file']).resolve())})
        self.assertEqual(result['render_code_continuation']['writer_change'], approval['writer_change'])
        verification = json.loads((self.web / 'full/verification.json').read_text())
        self.assertEqual(verification['render_code_continuation'], result['render_code_continuation'])

    def test_continuation_is_not_an_implicit_code_override_or_new_execution_authority(self):
        checkpoint, code, approval, pin = self._render_continuation_fixture()
        with patch.object(tool, '__file__', str(code)):
            with self.assertRaisesRegex(ValueError, 'SHA|pin|checksum'):
                tool.resume_render(checkpoint, tool.file_sha(checkpoint))
            with self.assertRaisesRegex(ValueError, 'resume|checkpoint'):
                tool.update(approval['request']['file'], approval['request']['sha256'],
                    _render_code_continuation={'pin': pin, 'payload': approval})
        self.assertTrue((self.root / 'new.sqlite3').exists())
        self.assertFalse((self.web / 'full').exists())

    def test_continuation_rejects_changed_scope_backup_database_run_and_other_code_pins(self):
        checkpoint, code, approval, _ = self._render_continuation_fixture()
        changes = [lambda d: d.update(scope='arbitrary migration'),
                   lambda d: d.update(run_id='wrong-run'),
                   lambda d: d['database']['stat'].update(bytes=1),
                   lambda d: d['original_code_pins'].update(other={'file': str(code), 'sha256': tool.file_sha(code)}),
                   lambda d: d['writer_change']['backup'].update(sha256='0' * 64),
                   lambda d: d['writer_change']['new'].update(file=str(self.root / 'foreign-code.py'))]
        before = (self.root / 'new.sqlite3').read_bytes(), checkpoint.read_bytes()
        for change in changes:
            candidate = deepcopy(approval); change(candidate)
            pin = write_json(self.root / 'invalid-continuation.json', candidate)
            with self.subTest(candidate=candidate), patch.object(tool, '__file__', str(code)):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    tool.resume_render(checkpoint, tool.file_sha(checkpoint),
                        continuation_path=pin['file'], continuation_sha256=pin['sha256'])
        self.assertEqual(((self.root / 'new.sqlite3').read_bytes(), checkpoint.read_bytes()), before)
        self.assertFalse((self.web / 'full').exists())

    def test_late_continuation_proof_tamper_blocks_publication_and_retains_database(self):
        checkpoint, code, approval, pin = self._render_continuation_fixture()
        original = tool.render_page
        def tamper_proof(*args, **kwargs):
            value = original(*args, **kwargs)
            Path(approval['proof_pins'][0]['file']).write_bytes(b'late proof replacement')
            return value
        with patch.object(tool, '__file__', str(code)), patch.object(tool, 'render_page', side_effect=tamper_proof):
            with self.assertRaisesRegex(ValueError, 'SHA|pin|checksum'):
                tool.resume_render(checkpoint, tool.file_sha(checkpoint),
                    continuation_path=pin['file'], continuation_sha256=pin['sha256'])
        self.assertTrue((self.root / 'new.sqlite3').is_file())
        self.assertTrue(checkpoint.is_file())
        self.assertFalse((self.web / 'full').exists())

    def test_continuation_still_rejects_other_code_drift_before_readonly_rendering(self):
        other = self.root / 'other-core.py'; other.write_bytes(b'exact accepted core\n')
        self.request['code_pins'] = {'other': {'file': str(other), 'sha256': tool.file_sha(other)}}
        # The fixture deliberately retains a second exact code pin in the
        # accepted request, rather than approving a broad replacement map.
        checkpoint, code, approval, pin = self._render_continuation_fixture()
        other.write_bytes(b'unaccepted semantic change\n')
        with patch.object(tool, '__file__', str(code)), patch.object(tool, 'render_page', side_effect=AssertionError('no render')):
            with self.assertRaisesRegex(ValueError, 'SHA|pin|checksum'):
                tool.resume_render(checkpoint, tool.file_sha(checkpoint),
                    continuation_path=pin['file'], continuation_sha256=pin['sha256'])
        self.assertTrue(checkpoint.exists())
        self.assertFalse((self.web / 'full').exists())

    def test_prepared_record_reproduction_preserves_original_sense_and_review_seals(self):
        before = sf.prepare_record(self.before)
        self.assertEqual(sf.prepare_record(tool.record_from_prepared(before)), before)
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        after = sf.prepare_record(result['record'])
        tool.validate_delta(before, after, result['scope_ledger'])
        self.assertEqual(before['senses'], after['senses'])
        self.assertEqual([r['assignment_context_hash'] for r in before['occurrences']],
                         [r['assignment_context_hash'] for r in after['occurrences']])

    def test_trial_real_sqlite_preserves_original_and_bound_parent_payload(self):
        with patch.object(sf, 'save_records', side_effect=AssertionError('no batch backups')):
            result = self.invoke(trial_words=['novel'])
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)
        self.assertEqual(result['word_cards'], 1)
        with closing(sqlite3.connect(result['new_database'])) as db:
            parent, child, payload, ledger = db.execute('SELECT parent_snapshot_id,child_snapshot_id,parent_payload,scope_ledger FROM exam_usage_parent_snapshots').fetchone()
            self.assertEqual(json.loads(payload)['snapshot_id'], parent)
            self.assertEqual(json.loads(ledger)['new_snapshot_id'], child)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        page = next((self.web / 'trial/redbook2027/web-preview').glob('*/cards/*.html')).read_text()
        self.assertIn('牛津原释义', page)
        self.assertIn('<base href="/accepted/cards/novel.html">', page)
        self.assertIn('../sources/entry.html', page)
        self.assertIn('阅读正文', page)
        proof = json.loads((self.web / 'trial/redbook2027/verification.json').read_text())['cards'][0]
        self.assertEqual(tool.restore_edits(page, proof['inverse']), self.source_page.read_text())

    def test_full_clone_keeps_old_immutable_rows_and_appends_once(self):
        result = self.invoke()
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)
        with closing(sqlite3.connect(result['new_database'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
            sid = sf.prepare_record(self.before)['snapshot_id']
            self.assertIsNotNone(db.execute('SELECT 1 FROM snapshots WHERE id=?', (sid,)).fetchone())
            self.assertEqual(db.execute('SELECT parent_payload FROM exam_usage_parent_snapshots').fetchone()[0], '')
        verification = json.loads((self.web / 'full/verification.json').read_bytes())
        self.assertNotIn('cards', verification)
        self.assertEqual(verification['card_proofs']['records'], 1)
        self.assertEqual(tool.file_sha(verification['card_proofs']['file']), verification['card_proofs']['sha256'])

    def test_failed_transform_discards_only_new_private_outputs(self):
        def invalid(record, **kwargs):
            result = policy.transform_record(record, **kwargs)
            result['record']['senses'][0]['text'] = '篡改原词义'
            return result
        with self.assertRaises(ValueError):
            self.invoke(transform=invalid)
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertFalse((self.web / 'full').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def _fail_after_committed_database(self):
        with patch.object(tool, 'render_page', side_effect=ValueError('controlled render failure')):
            with self.assertRaisesRegex(ValueError, 'controlled render failure'):
                self.invoke()
        checkpoint = Path(str(self.root / 'new.sqlite3') + '.prepared.json')
        return checkpoint

    def test_render_failure_preserves_committed_private_database_and_checkpoint(self):
        checkpoint = self._fail_after_committed_database()
        self.assertTrue((self.root / 'new.sqlite3').is_file())
        self.assertTrue(checkpoint.is_file())
        self.assertFalse((self.web / 'full').exists())
        self.assertEqual(list(self.web.glob('.usage-preview-*')), [])
        receipts = list(self.root.glob('new.sqlite3.render-failure-*.json'))
        self.assertEqual(len(receipts), 1)
        failure = json.loads(receipts[0].read_bytes())
        self.assertEqual(failure['exception_type'], 'ValueError')
        self.assertIn('controlled render failure', failure['message'])
        self.assertTrue(failure['database_retained'])
        self.assertIsNone(failure['terminal_exit_code'])
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)
        payload = json.loads(checkpoint.read_bytes())
        self.assertEqual(payload['database']['sha256'], tool.file_sha(self.root / 'new.sqlite3'))
        with closing(sqlite3.connect('file:' + str(self.root / 'new.sqlite3') + '?mode=ro', uri=True)) as db:
            self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT count(*) FROM exam_usage_parent_snapshots').fetchone()[0], 1)

    def test_exact_checkpoint_resume_only_renders_without_database_writes_or_reprepare(self):
        checkpoint = self._fail_after_committed_database()
        database = self.root / 'new.sqlite3'
        before = tool.file_sha(database)
        connections = []
        original_connect = sqlite3.connect
        def only_readonly_connection(path, *args, **kwargs):
            self.assertIn('?mode=ro', str(path))
            self.assertTrue(kwargs.get('uri'))
            connections.append(str(path))
            return original_connect(path, *args, **kwargs)
        with patch.object(policy, 'transform_record', side_effect=AssertionError('resume must not transform')):
            with patch.object(tool, 'insert_prepared', side_effect=AssertionError('resume must not insert')):
                with patch.object(sqlite3, 'connect', side_effect=only_readonly_connection):
                    result = tool.resume_render(checkpoint, tool.file_sha(checkpoint))
        self.assertTrue(connections)
        self.assertEqual(result['word_cards'], 1)
        self.assertEqual(result['database_sha256'], before)
        self.assertEqual(tool.file_sha(database), before)
        self.assertTrue((self.web / 'full/preview-library.html').is_file())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_checkpoint_resume_rejects_exact_pin_or_database_drift_and_preserves_private_database(self):
        code = self.root / 'renderer.py'
        code.write_text('# fixed renderer\n')
        self.request['code_pins'] = {'fixture': {'file': str(code), 'sha256': tool.file_sha(code)}}
        checkpoint = self._fail_after_committed_database()
        checkpoint_sha = tool.file_sha(checkpoint)
        database = self.root / 'new.sqlite3'
        for path in (self.root / 'request.json', self.root / 'policy.json', code, database):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                try:
                    with self.assertRaisesRegex(ValueError, 'pin|checkpoint|database'):
                        tool.resume_render(checkpoint, checkpoint_sha)
                    self.assertTrue(database.is_file())
                    self.assertTrue(checkpoint.is_file())
                    self.assertFalse((self.web / 'full').exists())
                finally:
                    path.write_bytes(original)

    def test_integrity_failure_before_checkpoint_discards_uncertified_database(self):
        with patch.object(tool, '_check_private_integrity', side_effect=ValueError('integrity rejected')):
            with self.assertRaisesRegex(ValueError, 'integrity rejected'):
                self.invoke()
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertFalse(Path(str(self.root / 'new.sqlite3') + '.prepared.json').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_checkpoint_from_wal_source_is_standalone_delete_database(self):
        with closing(sqlite3.connect(self.old_db)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
        self.old_bytes = self.old_db.read_bytes()
        self.request['source_database']['sha256'] = tool.file_sha(self.old_db)
        checkpoint = self._fail_after_committed_database()
        self.assertTrue(checkpoint.is_file())
        with closing(sqlite3.connect('file:' + str(self.root / 'new.sqlite3') + '?mode=ro', uri=True)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0], 'delete')

    def test_resume_rejects_unaccepted_sidecar_even_when_main_database_pin_is_unchanged(self):
        checkpoint = self._fail_after_committed_database()
        database = self.root / 'new.sqlite3'
        before = database.read_bytes()
        for suffix in ('-wal', '-journal'):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(database) + suffix)
                sidecar.write_bytes(b'unaccepted logical database state')
                try:
                    with self.assertRaisesRegex(ValueError, 'standalone|sidecar|journal'):
                        tool.resume_render(checkpoint, tool.file_sha(checkpoint))
                    self.assertEqual(database.read_bytes(), before)
                    self.assertFalse((self.web / 'full').exists())
                finally:
                    sidecar.unlink()

    def test_checkpoint_pin_failure_removes_only_its_owned_unready_checkpoint(self):
        original = tool.file_sha
        def fail_checkpoint_pin(path):
            if str(path).endswith('.prepared.json'):
                raise OSError('controlled durable checkpoint pin failure')
            return original(path)
        with patch.object(tool, 'file_sha', side_effect=fail_checkpoint_pin):
            with self.assertRaisesRegex(OSError, 'durable checkpoint pin failure'):
                self.invoke()
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertFalse(Path(str(self.root / 'new.sqlite3') + '.prepared.json').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_late_nonempty_journal_blocks_publication_and_retains_checkpoint_database(self):
        original = tool.render_page
        def add_unaccepted_journal(*args, **kwargs):
            rendered = original(*args, **kwargs)
            Path(str(self.root / 'new.sqlite3') + '-journal').write_bytes(b'unaccepted later write')
            return rendered
        with patch.object(tool, 'render_page', side_effect=add_unaccepted_journal):
            with self.assertRaisesRegex(ValueError, 'nonempty sidecar'):
                self.invoke()
        self.assertFalse((self.web / 'full').exists())
        self.assertTrue((self.root / 'new.sqlite3').is_file())
        self.assertTrue(Path(str(self.root / 'new.sqlite3') + '.prepared.json').is_file())

    def test_unready_checkpoint_cleanup_preserves_an_external_replacement(self):
        original = tool.file_sha
        replacement = self.root / 'externally-created-checkpoint.json'
        replacement.write_bytes(b'foreign checkpoint evidence')
        def replace_before_pin(path):
            if str(path).endswith('.prepared.json'):
                replacement.replace(path)
                raise OSError('controlled checkpoint replacement')
            return original(path)
        with patch.object(tool, 'file_sha', side_effect=replace_before_pin):
            with self.assertRaisesRegex(OSError, 'checkpoint replacement'):
                self.invoke()
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertEqual(Path(str(self.root / 'new.sqlite3') + '.prepared.json').read_bytes(),
                         b'foreign checkpoint evidence')

    def test_late_policy_tamper_rejects_before_publication_and_rolls_back_clone(self):
        def mutate(record, **kwargs):
            result = policy.transform_record(record, **kwargs)
            (self.root / 'policy.json').write_text('{"cards":[],"late":true}')
            return result
        with self.assertRaisesRegex(ValueError, 'pinned input changed'):
            self.invoke(transform=mutate)
        self.assertFalse((self.web / 'full').exists())
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def projection_sidecar(self, projected=None, blocked=None):
        stat = self.old_db.stat()
        document = {'schema': 'reading-option-display-projection.v1',
            'source_database': {**self.request['source_database'], 'stat': {
                key: getattr(stat, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}},
            'source_files': {}, 'projected': projected or [], 'blocked': blocked or [], 'books': {}}
        for item in document['projected'] + document['blocked']:
            counts = document['books'].setdefault(item['book_id'],
                {'projected': 0, 'blocked_original_retained': 0, 'original': 0})
            counts['original'] += 1
            counts['projected' if item in document['projected'] else 'blocked_original_retained'] += 1
        document['projection_sha256'] = tool.digest(document)
        self.request['reading_display_projection'] = write_json(self.root / 'reading-projection.json', document)
        self.request['reading_display_replay'] = {'exam_root': str(self.root),
            'staging': str(self.root), 'completion_path': str(self.root / 'completion.json')}
        return document

    def test_reading_sidecar_binds_source_database_and_indexes_only_projected_entries(self):
        before = sf.prepare_record(self.before)
        key = before['book_id'], before['card_id']
        items = [{'book_id': key[0], 'card_id': key[1], 'occurrence_id': row['occurrence_id'],
                  'snapshot_id': before['snapshot_id'], 'source_files': {}} for row in before['occurrences']]
        self.projection_sidecar(items[:1], items[1:])
        sidecars = tool.load_validated_policy_sidecars(self.request)
        projection = sidecars['reading_display_projection'][key]
        self.assertEqual(projection['entries'], {items[0]['occurrence_id']: items[0]})
        self.assertEqual(projection['authority'], {'sidecar': self.request['reading_display_projection'],
                                                 'replay': self.request['reading_display_replay']})
        document = json.loads(Path(self.request['reading_display_projection']['file']).read_bytes())
        document['source_database']['sha256'] = 'f' * 64
        document.pop('projection_sha256')
        document['projection_sha256'] = tool.digest(document)
        self.request['reading_display_projection'] = write_json(self.root / 'reading-projection.json', document)
        with self.assertRaisesRegex(ValueError, 'source database'):
            tool.load_validated_policy_sidecars(self.request)

    def test_reading_projection_delta_replays_exact_item_and_rejects_detached_ledger_or_display(self):
        from anki_pipeline import reading_display_projection as reading
        from tests.test_sense_frequency import completed_record
        before = sf.prepare_record(completed_record())
        old = before['occurrences'][0]
        view = deepcopy(old['display'])
        view['source'] += ' · 已核实题干显示'
        view.pop('display_hash')
        view['display_hash'] = sf._sha(sf._json(view))
        item = {'book_id': before['book_id'], 'card_id': before['card_id'],
            'snapshot_id': before['snapshot_id'], 'occurrence_id': old['occurrence_id'],
            'new_display': view, 'source_files': {}}
        projected = {'authority': {'sidecar': {'file': '/fixture.json', 'sha256': '1' * 64},
                     'replay': {'exam_root': '/fixture', 'staging': '/fixture', 'completion_path': '/fixture.json'}},
                     'entries': {old['occurrence_id']: item}}
        with patch.object(reading, 'replay_projection', return_value=view) as replay:
            result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before,
                                             policy={'reading_display_projection': projected})
            after = sf.prepare_record(result['record'])
            ledger = result['scope_ledger']
            with patch.object(reading, 'get_projection', return_value=item):
                tool.validate_delta(before, after, ledger, reading_display_projection=projected)
                for mutate in (lambda x: x['reading_display_projections'].clear(),
                               lambda x: x['reading_display_projections'][0].update(parent_snapshot_id='wrong'),
                               lambda x: x['reading_display_projections'][0].update(target_display_sha256='wrong')):
                    invalid = deepcopy(ledger); mutate(invalid)
                    with self.assertRaisesRegex(ValueError, 'projection'):
                        tool.validate_delta(before, after, invalid, reading_display_projection=projected)
                invalid = deepcopy(after)
                invalid['occurrences'][0]['display']['source'] = '替换真实显示'
                with self.assertRaisesRegex(ValueError, 'projection'):
                    tool.validate_delta(before, invalid, ledger, reading_display_projection=projected)
        self.assertEqual(replay.call_args.args[2], old)

    def test_reading_projection_actual_sqlite_preserves_raw_parent_and_persists_complete_authority(self):
        from anki_pipeline import reading_display_projection as reading
        from tests.test_sense_frequency import completed_record
        self.before = completed_record()
        sf.save_records(self.old_db, [self.before], self.root / 'backups')
        self.old_bytes = self.old_db.read_bytes()
        self.request['source_database']['sha256'] = tool.file_sha(self.old_db)
        self.source_page.write_text(page_for(self.before))
        before = sf.prepare_record(self.before)
        old = before['occurrences'][0]
        item = {'book_id': before['book_id'], 'card_id': before['card_id'],
            'snapshot_id': before['snapshot_id'], 'occurrence_id': old['occurrence_id'],
            'new_display': deepcopy(old['display']), 'source_files': {}}
        self.projection_sidecar([item])
        # Source reconstruction itself is tested by the dedicated replay module;
        # this fixture isolates the writer's validated callback/SQL boundary.
        with patch.object(reading, 'replay_projection', return_value=item['new_display']):
            result = self.invoke()
        with closing(tool._ro(result['new_database'])) as db:
            run = json.loads(db.execute('SELECT payload FROM exam_usage_update_runs').fetchone()[0])
            ledger, child = db.execute('SELECT p.scope_ledger,s.payload FROM exam_usage_parent_snapshots p '
                'JOIN snapshots s ON s.id=p.child_snapshot_id').fetchone()
        ledger, child = json.loads(ledger), json.loads(child)
        entry = ledger['reading_display_projections'][0]
        self.assertEqual(entry['projection'], item)
        self.assertEqual(entry['authority']['sidecar'], self.request['reading_display_projection'])
        self.assertEqual(entry['parent_snapshot_id'], before['snapshot_id'])
        self.assertEqual(child['exam_usage_policy']['reading_display_projections'], [entry])
        self.assertEqual(run['input_pins']['reading_display_replay'], self.request['reading_display_replay'])
        self.assertEqual(run['input_pins']['reading_display_projection'], self.request['reading_display_projection'])
        self.assertEqual(child['occurrences'][0]['english'], old['english'])
        self.assertEqual(child['occurrences'][0]['target_range'], old['target_range'])
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_late_reading_sidecar_tamper_rejects_before_checkpoint_or_page_publication(self):
        self.projection_sidecar()
        def tamper(record, **kwargs):
            result = policy.transform_record(record, **kwargs)
            Path(self.request['reading_display_projection']['file']).write_bytes(b'changed authorized projection')
            return result
        with self.assertRaisesRegex(ValueError, 'pinned input changed'):
            self.invoke(transform=tamper)
        self.assertFalse((self.root / 'new.sqlite3').exists())
        self.assertFalse((self.web / 'full').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_unprojected_display_requires_exact_deterministic_chunk_refresh(self):
        from tests.test_sense_frequency import completed_record
        before = sf.prepare_record(completed_record())
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        after = sf.prepare_record(result['record'])
        tool.validate_delta(before, after, result['scope_ledger'])
        forged = deepcopy(after)
        view = forged['occurrences'][0]['display']
        view['translation'] = '自行封存的替换译文'
        view['translation_hash'] = sf._sha(view['translation'])
        view['alignment']['translationHash'] = view['translation_hash']
        view.pop('display_hash')
        view['display_hash'] = sf._sha(sf._json(view))
        with self.assertRaisesRegex(ValueError, 'unprojected.*display|deterministic'):
            tool.validate_delta(before, forged, result['scope_ledger'])
        ordinary = sf.prepare_record(self.before)
        result = policy.transform_record(tool.record_from_prepared(ordinary), baseline_prepared=ordinary)
        forged = sf.prepare_record(result['record'])
        forged['occurrences'][0]['display'] = deepcopy(view)
        with self.assertRaisesRegex(ValueError, 'unprojected.*display|deterministic'):
            tool.validate_delta(ordinary, forged, result['scope_ledger'])

    def test_source_page_inverse_refuses_tampered_replacement(self):
        before = sf.prepare_record(self.before)
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        page, proof, _, _ = tool.render_page(self.source_page.read_text(), before,
            sf.prepare_record(result['record']), result['scope_ledger'], source_url=self.card['previewUrl'], target_url='/new/card.html')
        self.assertEqual(tool.restore_edits(page, proof), self.source_page.read_text())
        with self.assertRaisesRegex(ValueError, 'inverse'):
            tool.restore_edits(page.replace('阅读正文', '假造正文', 1), proof)

    def test_source_diagnostic_selection_protects_full_nested_incoming_history(self):
        raw = ('<details class="sf-wrong-bindings"><summary>源卡旧区</summary></details>'
               '<div class="sf-native-ownership-history"><details class="sf-ownership-history">'
               '<summary>本句归属说明</summary><details class="sf-original-history-panel">'
               '<details class="sf-wrong-bindings"><summary>完整旧解释</summary></details>'
               '<div class="sf-report"><span class="sf-meaning">历史释义</span></div>'
               '<section class="exam-frequency">历史频次</section></details></details></div>')
        nodes = tool._Spans(raw).nodes
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]['kind'], 'diagnostic')
        self.assertEqual(raw[nodes[0]['start']:nodes[0]['end']],
                         '<details class="sf-wrong-bindings"><summary>源卡旧区</summary></details>')

    def test_original_reviewed_binding_cannot_change_without_explicit_review(self):
        before = sf.prepare_record(self.before)
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        changed = deepcopy(sf.prepare_record(result['record']))
        changed['occurrences'][0]['reason'] = '静默改写'
        with self.assertRaisesRegex(ValueError, 'semantic assignment changed'):
            tool.validate_delta(before, changed, result['scope_ledger'])

    def test_cloze_filter_keeps_parent_and_seals_and_reconciles_exact_child_count(self):
        value = deepcopy(self.before)
        value['occurrences'][1]['source_provenance']['sourcePathEvidence'] = {
            'kind': 'answer_option', 'questionId': 'kaoyan:2022-01:q-1-1'}
        value['occurrences'] = [sf.seal_reviewed_assignment(value, r) for r in value['occurrences']]
        before = sf.prepare_record(value)
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        after = sf.prepare_record(result['record'])
        tool.validate_delta(before, after, result['scope_ledger'])
        self.assertEqual(after['expected_occurrences'], 1)
        self.assertEqual(result['scope_ledger']['excluded'][0]['exclusion_kind'], 'cloze_option')
        self.assertEqual(result['scope_ledger']['excluded'][0]['occurrence'],
                         next(r for r in before['occurrences'] if r['occurrence_id'] not in {x['occurrence_id'] for x in after['occurrences']}))

    def test_wrong_exclusion_cannot_replace_original_row_or_drop_authority(self):
        before = sf.prepare_record(self.before)
        # A reviewed row is never a legacy X, regardless of an injected label.
        wrong = {'occurrence_id': before['occurrences'][0]['occurrence_id'],
                 'occurrence': before['occurrences'][0], 'exclusion_kind': 'wrong_lemma',
                 'authority': {'parent_snapshot_id': before['snapshot_id']}}
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before,
                                         excluded_occurrences=[wrong])
        with self.assertRaisesRegex(ValueError, 'original non-R authority'):
            tool.validate_delta(before, sf.prepare_record(result['record']), result['scope_ledger'])

    def test_shipped_class_alias_frequency_span_has_complete_reversible_render(self):
        before = sf.prepare_record(self.before)
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before)
        page = self.source_page.read_text().replace('class="exam-frequency"', 'class="_r0"')
        revised, proof, _, _ = tool.render_page(page, before, sf.prepare_record(result['record']),
            result['scope_ledger'], source_url=self.card['previewUrl'], target_url='/new/card.html',
            aliases={'_r0': 'exam-frequency'})
        self.assertEqual(tool.restore_edits(revised, proof), page)
        self.assertEqual(len([n for n in tool._Spans(page, {'_r0': 'exam-frequency'}).nodes
                              if n['kind'] == 'frequency']), 1)

    def test_actual_accepted_change_frequency_uses_shipped_alias_map(self):
        from scripts.prepare_sense_frequency_records import class_aliases
        path = tool.ROOT / ('output/sense-frequency-20261011/context-supplement-v1/changed-native-2027-v1/'
            'web-preview/34f43048fcb316e399fd59da6467f7dc84de5bab7769e235f346d43717830d7e/cards/'
            'fcef7978c1d070a19edf39a1282274aa3456887d2f83212f00480108e42ea54d.html')
        if not path.exists():
            self.skipTest('the accepted actual sample is not available in this checkout')
        page = path.read_bytes().decode()
        aliases = class_aliases(path.parent.parent)
        self.assertEqual(aliases['_r0'], 'exam-frequency')
        panels = [n for n in tool._Spans(page, aliases).nodes if n['kind'] == 'frequency']
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]['attrs']['data-occurrences'], '289')
        self.assertTrue(page[panels[0]['start']:panels[0]['end']].endswith('</section>'))

    def test_source_entry_requires_actual_bound_history_and_keeps_failed_full_record(self):
        row = sf.prepare_record(self.before)['occurrences'][0]
        old = '<details class="sf-wrong-bindings"><summary>原说明</summary><p>所有原证据</p></details>'
        item = {'occurrence': row, 'exclusion_kind': 'wrong_lemma', 'authority': {'run_id': 'accepted'},
                'ownership': {'targets': [{'word': 'train', 'card_id': 'train-card', 'status': 'reviewed',
                    'occurrence_id': 'target-oid', 'verified_physical_match': True, 'matched_sense': {'pos': 'v.', 'text': '进行训练',
                    'dictionary_source': 'oxford'}, 'target_reason': '健身训练'}]}}
        markup = tool.render_exclusions([item], target_urls={'train-card': '/new/train.html'}, historical_html=old)
        self.assertNotIn(old, markup)
        self.assertIn('本次尚未完成转归', markup)
        self.assertIn('原审核解释：' + row['reason'], markup)
        self.assertIn(row['translation'], markup)
        moved = tool.render_exclusions([item], target_urls={'train-card': '/new/train.html'},
            actual_bound_targets={(row['occurrence_id'], 'train-card', 'target-oid')})
        self.assertIn('href="/new/train.html"', moved)
        self.assertIn('v. 进行训练 · oxford', moved)
        self.assertIn('健身训练', moved)
        self.assertNotIn('原审核解释：', moved)
        self.assertNotIn('sf-example', moved)

    def test_actual_found_parent_mask_keeps_legacy_x_that_is_now_cloze(self):
        legacy_path = tool.ROOT / 'output/exam-usage-policy-20261012/trial-inputs-v2/legacy-wrong-bindings.json'
        dbpath = tool.ROOT / 'data/sense-frequency-supplement-20261011.sqlite3'
        if not legacy_path.exists() or not dbpath.exists():
            self.skipTest('the source-bound actual found fixture is unavailable')
        key = ('redbook2027', '65f0d165a043bb32f8c2934e0c6b1b00f6aa2f656f3656196ed934fe681683e0')
        legacy = json.loads(legacy_path.read_bytes())
        wrong = next(c['excluded'] for c in legacy['cards'] if (c['book_id'], c['card_id']) == key)
        with closing(sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            before = json.loads(db.execute('SELECT s.payload FROM active_snapshots a JOIN snapshots s '
                'ON s.id=a.snapshot_id WHERE a.book_id=? AND a.card_id=?', key).fetchone()[0])
        result = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before,
                                         excluded_occurrences=wrong)
        ledger = result['scope_ledger']
        self.assertEqual(len(ledger['prior_wrong_lemma_ids']), 97)
        self.assertEqual(sum(x['exclusion_kind'] == 'wrong_lemma' for x in ledger['excluded']), 96)
        rows = [r for r in before['occurrences'] if r['occurrence_id'] not in set(ledger['prior_wrong_lemma_ids'])]
        self.assertEqual(tool._frequency(rows)['occurrences'], 9)
        self.assertEqual(tool._frequency(rows)['paper_count'], 5)
        cloze_prior = [x for x in ledger['excluded'] if x['exclusion_kind'] == 'cloze_option' and x.get('prior_exclusion')]
        self.assertEqual(len(cloze_prior), 1)
        self.assertIn('legacy_projection_proof', cloze_prior[0]['prior_exclusion']['authority'])

    def test_absolute_content_addressed_runtime_keeps_other_bundle_code_and_full_inverse(self):
        from anki_pipeline.native_example_usage import restore_original
        template = Path(sf.__file__).with_name('templates').joinpath('card-chunks.js').read_text()
        content = 'window.keptEtymology = true;\n' + template
        digest = hashlib.sha256(content.encode()).hexdigest()
        assets = self.web / 'immutable-assets'
        assets.mkdir()
        (assets / (digest + '.js')).write_text(content)
        page = '<html><head></head><body><script src="/immutable-assets/' + digest + '.js"></script></body></html>'
        runtime, references = tool.install_native_runtime(page, {'_r28': 'example-card'},
            source_path=self.source_page, web_root=self.web)
        self.assertIn('window.keptEtymology = true;', runtime['page'])
        self.assertIn('.example-card,.sf-example,._r28', runtime['page'])
        self.assertEqual(tool.restore_edits(restore_original(runtime['page'], runtime['inverse']), references), page)

    def append_fixture(self):
        value = deepcopy(self.before)
        raw = value['occurrences'][1]
        raw.update(status='unmatched', sense_index=None, reviewed_sense_id=None,
                   assignment_context_hash=None, reason='原有词典范围未明确')
        before = sf.prepare_record(value)
        pending = next(r for r in before['occurrences'] if r['status'] == 'unmatched')
        pin = {'provider': 'oxford', 'source_entry_id': 42, 'raw_sha256': hashlib.sha256(b'exact native').hexdigest(),
            'sense_id': 'novel-new-1', 'source_headword': 'novel', 'dictionary': 'oald10',
            'dictionary_version': 'OALD10'}
        english, chinese = 'a short fictional story', '短篇小说'
        registry = [{'source_ref': pin, 'sense_ref': hashlib.sha256(b'new sense').hexdigest(),
            'english': english, 'chinese': chinese, 'native_definition_valid': True, 'raw_entry_valid': True}]
        source_pin = {**pin, 'sense_ref': registry[0]['sense_ref']}
        decision = {'book_id': before['book_id'], 'card_id': before['card_id'], 'snapshot_id': before['snapshot_id'],
            'occurrence_id': pending['occurrence_id'], 'english_hash': pending['english_hash'],
            'target_range': pending['target_range'], 'old_assignment_sha256': policy.assignment_pin(before, pending),
            'status': 'reviewed', 'sense_id': None, 'reason': '实际短篇小说范围经整句与原词典核对',
            'evidence_ids': ['native:42'], 'dictionary_source_pins': [source_pin],
            'dictionary_explanation': {'source': 'oxford', 'name': '牛津高阶英汉双解词典', 'version': 'OALD10',
                'exact_entry': 'novel', 'sense': 'novel-new-1', 'source_ref_pin': source_pin,
                'english_definition': english, 'original_chinese': chinese},
            'new_sense': {'pos': 'n.', 'text': chinese, 'original_english': english,
                'original_chinese': chinese, 'translation_kind': 'original'}}
        transformed = policy.transform_record(tool.record_from_prepared(before), baseline_prepared=before,
            policy={'verified_dictionary_sources': registry}, residual_decisions=[decision])
        return before, transformed, registry, decision

    def test_source_pinned_append_and_exact_original_r_ordinal_reseal_pass(self):
        before, changed, registry, _ = self.append_fixture()
        after = sf.prepare_record(changed['record'])
        tool.validate_delta(before, after, changed['scope_ledger'], verified_dictionary_sources=registry)
        self.assertEqual([(s['pos'], s['text']) for s in before['senses']],
                         [(s['pos'], s['text']) for s in after['senses'][:len(before['senses'])]])
        self.assertEqual(len(changed['scope_ledger']['technical_semantic_rebindings']), 1)
        for mutate, message in [
                (lambda d: d['record']['senses'][0].update(text='原译被改写'), 'prefix'),
                (lambda d: d['scope_ledger']['technical_semantic_rebindings'].clear(), 'reseal'),
                (lambda d: d['scope_ledger']['new_definitions'][0]['validated_source_evidence'].update(text='假译文'), 'provenance')]:
            bad = deepcopy(changed); mutate(bad)
            if 'record' in bad:
                # Use the normalized untouched after for detached ledger tests;
                # stale changed definitions are rejected directly by prefix.
                candidate = deepcopy(after)
                if bad['record']['senses'][0]['text'] != changed['record']['senses'][0]['text']:
                    candidate['senses'][0]['text'] = bad['record']['senses'][0]['text']
            with self.assertRaisesRegex(ValueError, message):
                tool.validate_delta(before, candidate, bad['scope_ledger'], verified_dictionary_sources=registry)

    def test_actual_sqlite_append_source_label_and_inverse_are_complete(self):
        before, _, registry, decision = self.append_fixture()
        value = policy.producer_record(before)
        # Only temporary fixture inputs are replaced.
        self.old_db.unlink()
        sf.save_records(self.old_db, [value], self.root / 'append-backups')
        self.old_bytes = self.old_db.read_bytes()
        self.request['source_database']['sha256'] = tool.file_sha(self.old_db)
        self.source_page.write_text(page_for(value))
        decision_path = self.root / 'decisions.jsonl'
        decision_path.write_text(tool.canonical(decision) + '\n')
        registry_path = self.root / 'registry.jsonl'
        registry_path.write_text(''.join(tool.canonical(r) + '\n' for r in registry))
        self.request['residual_decisions'] = {'file': str(decision_path), 'sha256': tool.file_sha(decision_path)}
        self.request['dictionary_sources'] = {'file': str(registry_path), 'sha256': tool.file_sha(registry_path)}
        result = self.invoke(trial_words=['novel'])
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)
        page = next((self.web / 'trial/redbook2027/web-preview').glob('*/cards/*.html')).read_text()
        self.assertIn('牛津高阶英汉双解词典 · OALD10', page)
        self.assertIn('短篇小说', page)
        evidence = next((self.web / 'trial/redbook2027/sources').glob('*.html')).read_text()
        self.assertIn('a short fictional story', evidence)
        self.assertIn('主词典原中文', evidence)
        proof = json.loads((self.web / 'trial/redbook2027/verification.json').read_bytes())['cards'][0]
        self.assertEqual(tool.restore_edits(page, proof['inverse']), self.source_page.read_text())
        with closing(sqlite3.connect(result['new_database'])) as db:
            data = tool._active_prepared(db, before['book_id'], before['card_id'])
            self.assertEqual(len(data['senses']), 3)
            self.assertEqual(data['definition_provenance']['supplemental_definitions']['appended'][0]['source_name_zh'],
                             '牛津高阶英汉双解词典')

    def _appended_pending_diagnostic_fixture(self, *, target_current):
        before, transformed, _, _ = self.append_fixture()
        removed = before['occurrences'][0]
        transformed['record']['occurrences'] = [row for row in transformed['record']['occurrences']
                                                if row['occurrence_id'] != removed['occurrence_id']]
        transformed['record']['expected_occurrences'] = 1
        after = sf.prepare_record(transformed['record'])
        transformed['scope_ledger']['prior_wrong_lemma_ids'] = [removed['occurrence_id']]
        transformed['scope_ledger']['excluded'] = [{'occurrence_id': removed['occurrence_id'],
            'occurrence': removed, 'exclusion_kind': 'wrong_lemma', 'authority': {'fixture': True}}]
        if target_current:
            # The renderer deduplicates failed and resolved transfers by their
            # complete source/destination identity, as emitted by the producer.
            after['ownership_history_unresolved'] = [{'reason': '归属待核：实际新义句', 'transfer': {
                'book_id': before['book_id'], 'source_card_id': 'incoming-source-card',
                'source_parent_snapshot_id': before['snapshot_id'], 'source_parent_row': removed,
                'target_card_id': after['card_id'],
                'target_occurrence_id': after['occurrences'][0]['occurrence_id']}}]
            # The removed row's own unbound diagnostic is unnecessary for this
            # target-note fixture, which models an incoming transfer.
            transformed['scope_ledger']['excluded'] = []
        page = page_for(policy.producer_record(before))
        parsed = tool._Spans(page)
        panel = next(node for node in parsed.nodes if node['kind'] == 'frequency')
        frequency = _exam_frequency_markup({'exam_frequency': tool._frequency(after['occurrences'])})
        page = page[:panel['start']] + frequency + page[panel['end']:]
        addition = transformed['scope_ledger']['new_definitions'][0]
        revised, inverse, _, _ = tool.render_page(page, before, after, transformed['scope_ledger'],
            source_url=self.card['previewUrl'], target_url='/new/novel.html',
            appended_source_urls={addition['ordinal']: '/new/source.html'})
        self.assertEqual(tool.restore_edits(revised, inverse), page)
        return revised

    def test_unbound_diagnostic_is_archived_once_across_original_and_appended_reports(self):
        page = self._appended_pending_diagnostic_fixture(target_current=False)
        self.assertEqual(page.count('待核对例句（不计本词频）'), 1)
        self.assertEqual(page.count('class="sf-ownership-pending-note"'), 1)

    def test_appended_report_keeps_plain_text_hints_inside_complete_history(self):
        before, transformed, _, _ = self.append_fixture()
        after = sf.prepare_record(transformed['record'])
        page = page_for(policy.producer_record(before))
        history = ('<details class="sf-ownership-history"><summary>本句归属说明</summary>'
                   '<details class="sf-original-history-panel"><p class="sf-hint">'
                   '补充义项中的完整原审核依据。</p></details></details>')
        global_hint = '<p class="sf-hint">当前重复全局说明</p>'
        fake = '<section class="sf-report">' + global_hint + '<article>' + history + '</article></section>'
        addition = transformed['scope_ledger']['new_definitions'][0]
        with patch.object(sf, 'render_report', return_value=fake):
            rendered, inverse, _, _ = tool.render_page(page, before, after, transformed['scope_ledger'],
                source_url='/accepted/novel.html', target_url='/new/novel.html',
                appended_source_urls={addition['ordinal']: '/new/exact-source.html'})
        self.assertEqual(rendered.count(history), 2)
        self.assertEqual(rendered.count(global_hint), 1)
        self.assertEqual(tool.restore_edits(rendered, inverse), page)

    def test_pending_ownership_note_follows_its_actual_appended_sense_sentence(self):
        from anki_pipeline.native_example_usage import _Offsets
        page = self._appended_pending_diagnostic_fixture(target_current=True)
        self.assertNotIn('待核对例句（不计本词频）', page)
        self.assertEqual(page.count('class="sf-ownership-pending-note"'), 1)
        appended = page[page.index('<section class="supplement-definition">'):]
        self.assertIn('归属待核：实际新义句', appended)
        before, *_ = self.append_fixture()
        expected = next(row['occurrence_id'] for row in before['occurrences'] if row['status'] == 'unmatched')
        notes = [node for node in _Offsets(appended, {}).root.walk()
                 if 'sf-ownership-pending-note' in node.classes]
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].parent.tag, 'article')
        self.assertIn('sf-example', notes[0].parent.classes)
        self.assertEqual(notes[0].parent.attrs['data-sf-occurrence-id'], expected)

    def test_catalog_card_paths_follow_unchanged_runtime_allowlist(self):
        import re
        self.invoke(trial_words=['novel'])
        catalog = json.loads((self.web / 'trial/redbook2027/catalog.json').read_bytes())
        self.assertIn('试览 1 词', catalog['deckName'])
        for card in catalog['cards']:
            self.assertRegex(card['previewUrl'], r'/web-preview/[a-z0-9_-]+/cards/[a-f0-9]+\.html$')
        self.assertEqual(catalog['cards'][0]['id'], self.card['id'])

    def test_frozen_group_certificate_shape_is_normalized_without_status_and_keeps_original_authority(self):
        before = sf.prepare_record(self.before)
        ids = [s['sense_id'] for s in before['senses']]
        raw = {'book_id': before['book_id'], 'card_id': before['card_id'], 'record_key': 'reviewed-group-1',
            'candidate_sense_ids': ids, 'candidate_explanations': [{'sense_id': s} for s in ids],
            'common_meaning': '已核对的共同范围', 'usage_scope': {'exact': 'reviewed construction'},
            'context_reason': '上下文精确证据', 'grammar_reason': '语法精确证据'}
        pin = write_json(self.root / 'group-certificates.json', [raw])
        indexed, _ = tool._index_sidecar(pin, collection='equivalences')
        certificate = indexed[(before['book_id'], before['card_id'])]['equivalences'][0]
        self.assertEqual(certificate['member_sense_ids'], ids)
        self.assertEqual(certificate['evidence'], raw['candidate_explanations'])
        self.assertEqual(certificate['meaning'], raw['common_meaning'])
        self.assertIn(raw['context_reason'], certificate['reason'])
        self.assertIn(raw['grammar_reason'], certificate['reason'])
        self.assertEqual(certificate['original_certificate'], raw)
        self.assertEqual(certificate['certificate_source_pin'], pin)
        for change in (lambda x: x.pop('context_reason'),
                       lambda x: x.update(candidate_sense_ids=[ids[0], ids[0]]),
                       lambda x: x.update(candidate_explanations=[]),
                       lambda x: x.update(candidate_explanations=[{'sense_id': 'unrelated-evidence'}])):
            invalid = deepcopy(raw); change(invalid)
            badpin = write_json(self.root / 'invalid-group-certificates.json', [invalid])
            with self.assertRaises(ValueError):
                tool._index_sidecar(badpin, collection='equivalences')

    def ownership_fixture(self):
        from tests.test_sense_display import native_example
        for r in self.before['occurrences']:
            r['source_provenance']['reviewedContentHash'] = hashlib.sha256(b'exact reviewed fixture source').hexdigest()
        self.before['occurrences'] = [sf.seal_reviewed_assignment(self.before, r) for r in self.before['occurrences']]
        target = sf.prepare_record(self.before)
        source = deepcopy(self.before)
        source.update(card_id='wrong-card', word='novelty', definition_provenance={'entry': 'novelty'})
        source['occurrences'][0].update(status='unmatched', sense_index=None, reviewed_sense_id=None,
            assignment_context_hash=None, reason='完整旧错归说明\n该位置实际属于 novel，不能借名词义重复统计。')
        source['occurrences'] = [sf.seal_reviewed_assignment(source, r) if r['status'] == 'reviewed' else r
                                 for r in source['occurrences']]
        parent = sf.prepare_record(source)
        row = next(r for r in parent['occurrences'] if r['status'] == 'unmatched')
        destination = next(r for r in target['occurrences'] if r['occurrence_id'] == row['occurrence_id'])
        sense = next(s for s in target['senses'] if s['sense_id'] == destination['sense_id'])
        ownership = {'source_identity': {k: deepcopy(row[k]) for k in ('paper_id', 'physical_source',
            'sentence_id', 'english_hash', 'target_range')}, 'targets': [{
            'word': target['word'], 'card_id': target['card_id'], 'occurrence_id': destination['occurrence_id'],
            'status': 'reviewed', 'verified_physical_match': True, 'match_kind': 'exact_span',
            'target_range': destination['target_range'], 'matched_sense': {**sense, 'dictionary_source': 'oxford',
                'source_provenance': {'snapshot_id': target['snapshot_id']}}, 'target_reason': destination['reason']}]}
        decision = {'book_id': parent['book_id'], 'card_id': parent['card_id'],
            'after_snapshot_id': parent['snapshot_id'], 'occurrence_id': row['occurrence_id'],
            'decision_after': {'status': 'unmatched', 'reason': row['reason']}}
        exclusion = {'occurrence_id': row['occurrence_id'], 'occurrence': row, 'exclusion_kind': 'wrong_lemma',
            'ownership': ownership, 'authority': {'parent_snapshot_id': parent['snapshot_id'],
            'decision_sha256': tool.digest(decision), 'legacy_projection_proof': {'decision': decision, 'occurrence': row}}}
        self.old_db.unlink()
        sf.save_records(self.old_db, [self.before, source], self.root / 'history-backups')
        self.old_bytes = self.old_db.read_bytes()
        self.request['source_database']['sha256'] = tool.file_sha(self.old_db)
        old_panel = '<details class="sf-wrong-bindings"><summary>原完整核对块</summary><p>原完整块额外证据</p></details>'
        source_page = page_for(source).replace(_exam_frequency_markup({'exam_frequency': tool._frequency(parent['occurrences'])}),
            _exam_frequency_markup({'exam_frequency': tool._frequency([r for r in parent['occurrences'] if r['occurrence_id'] != row['occurrence_id']])}))
        source_page = source_page.replace('</body>', old_panel + '</body>')
        jump = {'id': target['occurrences'][0]['sentence_id'], 'englishHash': target['occurrences'][0]['english_hash'],
            'reviewedContentHash': target['occurrences'][0]['source_provenance']['reviewedContentHash']}
        native = native_example(jump, target['occurrences'][0]['english'], target['occurrences'][0]['translation'],
            [r['target_range'] for r in target['occurrences']])
        source_page = source_page.replace('</body>', '<ul>' + native + '</ul></body>')
        self.source_page.write_text(page_for(self.before).replace('</body>', '<ul>' + native + '</ul></body>'))
        self.catalog['cards'][0]['exampleCount'] = 1
        (self.accepted / 'cards/novelty.html').write_text(source_page)
        self.catalog['cards'].append({**self.card, 'id': source['card_id'], 'word': source['word'],
            'previewUrl': '/accepted/cards/novelty.html'})
        self.catalog['decks'][0]['cardIds'].append(source['card_id']); self.catalog['decks'][0]['count'] = 2
        self.catalog['counts']['cards'] = 2
        self.request['books'][0]['expected_cards'] = 2
        self.request['books'][0]['catalog'] = write_json(self.accepted / 'catalog.json', self.catalog)
        self.request['legacy_wrong_bindings'] = write_json(self.root / 'wrong-bindings.json', {'cards': [{
            'book_id': parent['book_id'], 'card_id': parent['card_id'], 'excluded': [exclusion]}]})
        return parent, row, target, old_panel

    def test_sqlite_reverse_history_moves_complete_evidence_only_after_actual_binding(self):
        parent, original, target, panel = self.ownership_fixture()
        result = self.invoke(trial_words=['novel', 'novelty'])
        self.assertEqual(result['ownership_history']['bound'], 1)
        self.assertEqual(result['ownership_history']['unresolved'], 0)
        self.assertEqual(result['ownership_history']['absent_targets'], 0)
        self.assertEqual(result['ownership_history']['pending_source_records'], 0)
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)
        with closing(sqlite3.connect(result['new_database'])) as db:
            child = tool._active_prepared(db, target['book_id'], target['card_id'])
            self.assertEqual(child['expected_occurrences'], target['expected_occurrences'])
            history = next(r for r in child['occurrences'] if r.get('ownership_history'))['ownership_history'][0]
            self.assertEqual(history['source_parent_row'], original)
            self.assertEqual(history['target_reason'], next(r for r in target['occurrences']
                if r['occurrence_id'] == history['target_occurrence_id'])['reason'])
            self.assertEqual(db.execute('SELECT count(*) FROM exam_usage_history_documents').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            overlay = db.execute('SELECT semantic_snapshot_id,final_snapshot_id FROM exam_usage_ownership_overlays').fetchone()
            self.assertNotEqual(*overlay)
            self.assertEqual(overlay[1], child['snapshot_id'])
        catalog = json.loads((self.web / 'trial/redbook2027/catalog.json').read_bytes())
        pages = {c['word']: tool._local_url(c['previewUrl'], self.web).read_text() for c in catalog['cards']}
        self.assertIn('完整旧错归说明', pages['novel'])
        self.assertIn('原完整块额外证据', pages['novel'])
        self.assertIn('sf-ownership-history', pages['novel'])
        self.assertNotIn('完整旧错归说明', pages['novelty'])
        self.assertNotIn('exam-usage-exclusions', pages['novelty'])
        self.assertTrue(Path(history['source_history_ref']['file']).exists())
        self.assertEqual(tool.file_sha(history['source_history_ref']['file']), history['source_history_ref']['sha256'])
        for proof in json.loads((self.web / 'trial/redbook2027/verification.json').read_bytes())['cards']:
            from anki_pipeline.native_example_usage import restore_original
            word = next(c['word'] for c in catalog['cards'] if c['id'] == proof['card_id'])
            restored = restore_original(tool.restore_edits(pages[word], proof['inverse']), proof['runtime_inverse'])
            restored = tool.restore_edits(restored, proof['runtime_reference_inverse'])
            self.assertEqual(restore_original(restored, proof['native_inverse']),
                tool._local_url(proof['source_url'], self.web).read_text())

    def test_absent_trial_target_retains_complete_diagnostic_and_never_claims_moved(self):
        _, original, _, _ = self.ownership_fixture()
        result = self.invoke(trial_words=['novelty'])
        self.assertEqual(result['ownership_history']['bound'], 0)
        self.assertEqual(result['ownership_history']['absent_targets'], 1)
        page = next((self.web / 'trial/redbook2027/web-preview').glob('*/cards/*.html')).read_text()
        self.assertIn('完整原记录尚未转归', page)
        self.assertIn(original['translation'], page)
        self.assertIn('完整旧错归说明', page)
        self.assertNotIn('完整原句、译文、标记、出处与原核对依据已随记录保存在目标词卡', page)

    def _sf_only_history_fixture(self):
        fixture = self.ownership_fixture()
        # An existing SF physical row does not imply a native <li>. This is
        # intentional source coverage, not permission to manufacture an example.
        self.source_page.write_text(page_for(self.before))
        self.catalog['cards'][0]['exampleCount'] = 0
        self.request['books'][0]['catalog'] = write_json(self.accepted / 'catalog.json', self.catalog)
        return fixture

    def test_sf_only_history_deferral_requires_complete_actual_sf_sentence_coverage(self):
        self._sf_only_history_fixture()
        result = self.invoke(trial_words=['novel', 'novelty'])
        verification = json.loads((self.web / 'trial/redbook2027/verification.json').read_bytes())
        proof = next(p for p in verification['cards'] if p['card_id'] == self.before['card_id'])
        self.assertEqual(proof['ownership_coverage']['expected_histories'], 1)
        self.assertEqual(proof['ownership_coverage']['sf_histories'], 1)
        self.assertEqual(proof['ownership_coverage']['native_histories'], 0)
        self.assertEqual(proof['ownership_coverage']['sf_only_histories'], 1)
        self.assertEqual(result['ownership_history']['bound'], 1)
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_sf_only_history_cannot_succeed_when_its_actual_inline_explanation_is_removed(self):
        self._sf_only_history_fixture()
        original_render = tool.render_page
        def remove_current_history(*args, **kwargs):
            page, inverse, frequency, breakdown = original_render(*args, **kwargs)
            from anki_pipeline.native_example_usage import _Offsets
            target = next((node for node in _Offsets(page, {}).root.walk()
                if node.attrs.get('data-ownership-history-id') and node.parent.tag == 'article'), None)
            if target is not None:
                page = page[:target.start] + page[target.end:]
            return page, inverse, frequency, breakdown
        with patch.object(tool, 'render_page', side_effect=remove_current_history):
            with self.assertRaisesRegex(ValueError, 'ownership SF history coverage is missing'):
                self.invoke(trial_words=['novel', 'novelty'])
        self.assertTrue((self.web / 'trial/usage-trial.sqlite3').exists())
        self.assertFalse((self.web / 'trial/redbook2027').exists())
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def _overlapping_rehome_fixture(self):
        parent, row, target, _ = self.ownership_fixture()
        old = json.loads(Path(self.request['legacy_wrong_bindings']['file']).read_bytes())['cards'][0]['excluded'][0]['ownership']
        old.update(book_id=parent['book_id'], card_id=parent['card_id'], word=parent['word'],
            occurrence_id=row['occurrence_id'], previous_status=row['status'], previous_sense_id=row['sense_id'],
            english=row['english'], exclusion_verified=True, ownership_status='rehome_verified',
            decision_status='keep_exclusion', reason='原政策完整核对理由',
            source_checks={'english_hash_valid': True, 'exact_target_match': True,
                           'frozen_context_sentence_contained': True})
        newer = deepcopy(old)
        newer.update(reason='残余复核补强的完整理由', origin={'original_audit': {'precise': 'new full context'},
            'original_audit_sha256': tool.digest({'precise': 'new full context'})})
        newer['source_identity']['context_entity_id'] = 'context:additional-immutable-proof'
        pin = write_json(self.root / 'overlap-original-policy.json', {'audit': old})
        return parent, row, target, old, newer, pin

    def test_overlapping_verified_rehomes_are_one_exclusion_with_both_full_authorities(self):
        parent, row, target, old, newer, pin = self._overlapping_rehome_fixture()
        with closing(tool._ro(self.old_db)) as db:
            merged = tool.merge_confirmed_rehomes(parent, [old], [newer], policy_pin=pin,
                parent_lookup=lambda b, c: tool._active_prepared(db, b, c))
            changed = policy.transform_record(tool.record_from_prepared(parent), baseline_prepared=parent,
                policy={'confirmed_new_exclusions': merged})
            after = sf.prepare_record(changed['record'])
            tool.validate_delta(parent, after, changed['scope_ledger'],
                parent_lookup=lambda b, c: tool._active_prepared(db, b, c))
        self.assertEqual(len(changed['scope_ledger']['excluded']), 1)
        audit = changed['scope_ledger']['excluded'][0]['authority']['audit']
        self.assertEqual(audit['reason'], newer['reason'])
        self.assertEqual(audit['origin'], newer['origin'])
        self.assertEqual(audit['additional_authorities'][0]['audit'], old)
        self.assertEqual(audit['additional_authorities'][0]['audit_sha256'], tool.digest(old))
        self.assertEqual(audit['additional_authorities'][0]['source_pin'], pin)
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)

    def test_overlapping_rehomes_reject_conflicting_or_unverified_actual_destinations(self):
        parent, _, _, old, newer, pin = self._overlapping_rehome_fixture()
        for mutate in (lambda a: a['targets'][0].update(target_reason='假核对说明'),
                       lambda a: a['targets'][0]['matched_sense'].update(text='不同实际义项'),
                       lambda a: a.update(previous_status='ambiguous'),
                       lambda a: a['source_checks'].update(english_hash_valid=False)):
            changed = deepcopy(newer); mutate(changed)
            with closing(tool._ro(self.old_db)) as db, self.assertRaises(ValueError):
                tool.merge_confirmed_rehomes(parent, [old], [changed], policy_pin=pin,
                    parent_lookup=lambda b, c: tool._active_prepared(db, b, c))

    def test_overlapping_rehomes_reject_duplicate_sources_and_stale_authority_pin(self):
        parent, _, _, old, newer, pin = self._overlapping_rehome_fixture()
        with closing(tool._ro(self.old_db)) as db:
            lookup = lambda b, c: tool._active_prepared(db, b, c)
            for previous, residual in (([old, old], [newer]), ([old], [newer, newer])):
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    tool.merge_confirmed_rehomes(parent, previous, residual, policy_pin=pin, parent_lookup=lookup)
            Path(pin['file']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'pinned input changed'):
                tool.merge_confirmed_rehomes(parent, [old], [newer], policy_pin=pin, parent_lookup=lookup)

    def test_residual_adapter_checks_actual_context_and_rejects_self_reported_flags(self):
        parent, row, target, _ = self.ownership_fixture()
        payload = {'paper_id': row['paper_id'], 'blocks': [{'id': 'block-1', 'text': row['english']}]}
        cache = {'kind': 'full-paper-context', 'entity_id': 'context:fixture', 'run_id': 'accepted-fixture-run',
            'payload': payload, 'payload_sha256': tool.digest(payload)}
        cache_pin = write_json(self.root / 'context.json', cache)
        with closing(sqlite3.connect(self.old_db)) as db:
            db.execute('CREATE TABLE supplemental_review_entities(run_id TEXT,entity_id TEXT,kind TEXT,payload_sha256 TEXT,payload TEXT)')
            db.execute('INSERT INTO supplemental_review_entities VALUES(?,?,?,?,?)', (cache['run_id'], cache['entity_id'],
                cache['kind'], cache['payload_sha256'], tool.canonical(payload)))
            db.commit()
        self.old_bytes = self.old_db.read_bytes()
        audit = {'book_id': parent['book_id'], 'card_id': parent['card_id'], 'word': parent['word'],
            'snapshot_id': parent['snapshot_id'], 'occurrence_id': row['occurrence_id'], 'apply_policy_change': True,
            'exclusion_verified': True, 'old_assignment_sha256': policy.assignment_pin(parent, row),
            'physical_target': row['english'][slice(*row['target_range'])],
            'source_identity': {k: deepcopy(row[k]) for k in ('paper_id', 'physical_source', 'sentence_id', 'english_hash', 'target_range')},
            'context_pin': {'run_id': cache['run_id'], 'entity_id': cache['entity_id'], 'payload_sha256': cache['payload_sha256'],
                'cache_file': cache_pin['file'], 'cache_file_sha256': cache_pin['sha256']}, 'targets': []}
        audit['source_identity']['physical_source'] = tool.canonical(audit['source_identity']['physical_source'])
        pin = write_json(self.root / 'residual-ownership.json', {'confirmed_targets': [audit]})
        with closing(tool._ro(self.old_db)) as db:
            indexed, pins = tool.normalized_residual_rehomes(pin, db)
            normalized = indexed[(parent['book_id'], parent['card_id'])][0]
            self.assertTrue(normalized['source_checks']['frozen_context_sentence_contained'])
            self.assertEqual(normalized['source_identity']['physical_source'], row['physical_source'])
            self.assertEqual(normalized['origin']['original_audit'], audit)
            self.assertEqual(pins, [cache_pin])
        bad = deepcopy(audit); bad['physical_target'] = 'invented target'
        bad_pin = write_json(self.root / 'bad-residual.json', {'confirmed_targets': [bad]})
        with closing(tool._ro(self.old_db)) as db, self.assertRaisesRegex(ValueError, 'actual English hash or target'):
            tool.normalized_residual_rehomes(bad_pin, db)
        cache['payload']['blocks'][0]['text'] = 'unrelated source'
        altered_cache = write_json(self.root / 'context.json', cache)
        bad = deepcopy(audit); bad['context_pin']['cache_file_sha256'] = altered_cache['sha256']
        bad['source_checks'] = {'frozen_context_sentence_contained': True}
        bad_pin = write_json(self.root / 'bad-residual.json', {'confirmed_targets': [bad]})
        with closing(tool._ro(self.old_db)) as db, self.assertRaisesRegex(ValueError, 'exact accepted paper entity'):
            tool.normalized_residual_rehomes(bad_pin, db)
        self.assertEqual(self.old_db.read_bytes(), self.old_bytes)


if __name__ == '__main__':
    unittest.main()
