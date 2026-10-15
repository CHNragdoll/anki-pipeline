"""Physical token counts, durable reviewed assignments and safe web previews."""
import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from anki_pipeline import sense_display as sd


def record():
    english = 'A novel idea for a novel.'
    value = {'book_id': 'redbook2027', 'card_id': 'novel-card', 'word': 'novel',
            'definition_source': 'oxford', 'definition_provenance': {'entry': 'novel'},
            'expected_occurrences': 2,
            'senses': [{'pos': 'n.', 'text': '小说'}, {'pos': 'adj.', 'text': '新颖的'}],
            'occurrences': [
                {'physical_source': ['paper', 'block-1'], 'paper_id': 'kaoyan:2022-01',
                 'sentence_id': 'kaoyan:2022-01:p:block-1:0', 'english': english,
                 'english_hash': hashlib.sha256(english.encode()).hexdigest(),
                 'translation': '一部小说中的新颖想法。', 'source': '2022年考研英语一 ➫ Text 1',
                 'target_range': span, 'translation_ranges': [],
                 'source_provenance': {'reviewedContentHash': 'source-review-1'},
                 'status': 'reviewed', 'sense_index': sense, 'reason': reason,
                 'method': 'context-review', 'review_version': '20261011'}
                for span, sense, reason in [([2, 7], 1, '修饰 idea，表示新颖'),
                                            ([19, 24], 0, '名词，指小说')]]}
    return reseal(value)


def reseal(value):
    value['occurrences'] = [sf.seal_reviewed_assignment(value, row)
                            if row['status'] == 'reviewed' else row
                            for row in value['occurrences']]
    return value


def aligned_record():
    value = record()
    alignment = {'schema': 'codex-sentence-alignment.v1',
                 'englishHash': value['occurrences'][0]['english_hash'],
                 'translationHash': hashlib.sha256(value['occurrences'][0]['translation'].encode()).hexdigest(),
                 'alignments': [{'en': [2, 7], 'zh': [[6, 8]], 'relation': 'equivalent'},
                                {'en': [19, 24], 'zh': [[2, 4]], 'relation': 'equivalent'}]}
    for row, ranges in zip(value['occurrences'], ([[6, 8]], [[2, 4]])):
        row['alignment'] = copy.deepcopy(alignment)
        row['translation_ranges'] = ranges
    return reseal(value)


def completed_record():
    """Two physical tokens share one approved completed-question display."""
    value = aligned_record()
    page = '<html><head></head><body></body></html>'
    value['definition_provenance']['headword'] = value['word']
    value['definition_provenance']['page_sha256'] = hashlib.sha256(page.encode()).hexdigest()
    for row in value['occurrences']:
        row['english'] += ' ______'
        row['english_hash'] = hashlib.sha256(row['english'].encode()).hexdigest()
        row['translation'] += '______'
        row['alignment']['englishHash'] = row['english_hash']
        row['alignment']['translationHash'] = hashlib.sha256(row['translation'].encode()).hexdigest()
        row['alignment']['alignments'] = [
            {'en': [0, 12], 'zh': [[6, 10]], 'relation': 'equivalent'},
            {'en': [13, 25], 'zh': [[0, 6]], 'relation': 'equivalent'}]
    value = reseal(value)
    raw = value['occurrences'][0]
    source = {'id': raw['sentence_id'], 'english': raw['english'],
              'translationZh': raw['translation'], 'englishHash': raw['english_hash'],
              'reviewedContentHash': raw['source_provenance']['reviewedContentHash'],
              'translation_alignment': raw['alignment']}
    left = raw['english'].index('______')
    completed = raw['english'][:left] + 'succeeds.'
    derived = {'sentenceId': raw['sentence_id'], 'originalEnglish': raw['english'],
               'completedEnglish': completed, 'translationZh': '一部小说中的新颖想法。获得成功。',
               'blankRange': [left, left + 6], 'insertedRange': [left, left + 8],
               'answerNumber': '31', 'questionId': 'kaoyan:2022-01:q31'}
    sources = {'sentences': {raw['sentence_id']: source},
               'completions': {raw['sentence_id']: derived}, 'options': {}, 'watched': {}}
    with patch.object(sd, '_load_sources', return_value=sources):
        return sd.attach_source_displays([value], {value['card_id']: page}, {})[0]


class CandidateScopePersistenceTests(unittest.TestCase):
    def test_scope_and_exact_retained_source_survive_normalized_database_rows(self):
        from tests.test_sense_candidate_scope import scope_fixture
        from anki_pipeline.sense_candidate_scope import validate_stored_scope
        with tempfile.TemporaryDirectory() as directory:
            value, ledger = scope_fixture(directory)
            original = copy.deepcopy(value)
            value['candidate_scope'] = ledger
            database = Path(directory) / 'scope.sqlite3'
            sf.save_records(database, [value], Path(directory) / 'backups')
            report = sf.read_card(database, value['book_id'], value['card_id'])
            self.assertEqual(report['total'], 3)
            self.assertEqual(report['pending_count'], 1)
            self.assertEqual(report['candidate_scope'], ledger)
            with closing(sqlite3.connect(database)) as connection:
                payload = json.loads(connection.execute('SELECT payload FROM snapshots').fetchone()[0])
            self.assertEqual(payload['candidate_source_record'], original)
            self.assertEqual(validate_stored_scope(payload['candidate_source_record'], ledger), ledger)
            self.assertEqual(value['occurrences'], original['occurrences'])
            ordinary = sf.prepare_record(original)
            self.assertEqual(payload['definition_snapshot_id'], ordinary['definition_snapshot_id'])
            self.assertEqual(payload['occurrences'], ordinary['occurrences'])
            self.assertNotEqual(payload['snapshot_id'], ordinary['snapshot_id'])

    def test_changed_excluded_evidence_cannot_activate_a_new_scope(self):
        from tests.test_sense_candidate_scope import scope_fixture
        with tempfile.TemporaryDirectory() as directory:
            value, ledger = scope_fixture(directory)
            value['candidate_scope'] = ledger
            database = Path(directory) / 'scope.sqlite3'
            sf.save_records(database, [value], Path(directory) / 'backups')
            before = sf.read_card(database, value['book_id'], value['card_id'])['snapshot_id']
            bad = copy.deepcopy(value)
            bad['candidate_scope']['excluded'][0]['occurrence']['english'] += ' changed'
            with self.assertRaises(ValueError):
                sf.save_records(database, [bad], Path(directory) / 'backups')
            self.assertEqual(sf.read_card(database, value['book_id'], value['card_id'])['snapshot_id'], before)


# Exact original column layout, before review bindings and full chunk storage.
LEGACY_SCHEMA = '''
CREATE TABLE snapshots (
 id TEXT PRIMARY KEY, book_id TEXT NOT NULL, card_id TEXT NOT NULL, word TEXT NOT NULL,
 definition_source TEXT NOT NULL, definition_provenance TEXT NOT NULL,
 expected_occurrences INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(id,book_id,card_id));
CREATE TABLE active_snapshots (
 book_id TEXT NOT NULL, card_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 PRIMARY KEY(book_id,card_id),
 FOREIGN KEY(snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id));
CREATE TABLE senses (
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id), sense_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL, pos TEXT NOT NULL, text TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,sense_id), UNIQUE(snapshot_id,ordinal));
CREATE TABLE occurrences (
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id), occurrence_id TEXT NOT NULL,
 physical_source TEXT NOT NULL, paper_id TEXT NOT NULL, year INTEGER NOT NULL,
 sentence_id TEXT NOT NULL, english TEXT NOT NULL, english_hash TEXT NOT NULL,
 translation TEXT NOT NULL, translation_hash TEXT NOT NULL,
 target_start INTEGER NOT NULL, target_end INTEGER NOT NULL,
 translation_ranges TEXT NOT NULL, source TEXT NOT NULL, source_provenance TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,occurrence_id));
CREATE TABLE assignments (
 snapshot_id TEXT NOT NULL, occurrence_id TEXT NOT NULL, sense_id TEXT,
 status TEXT NOT NULL, reason TEXT NOT NULL, method TEXT NOT NULL, review_version TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,occurrence_id),
 FOREIGN KEY(snapshot_id,occurrence_id) REFERENCES occurrences(snapshot_id,occurrence_id),
 FOREIGN KEY(snapshot_id,sense_id) REFERENCES senses(snapshot_id,sense_id));
CREATE INDEX assignment_senses ON assignments(snapshot_id,sense_id);
PRAGMA user_version=1;
'''


class SenseFrequencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'sense-frequency.sqlite3'

    def put(self, value):
        return sf.save_records(self.db, [value], self.root / 'backups')

    def get(self):
        return sf.read_card(self.db, 'redbook2027', 'novel-card')

    def test_completed_display_roundtrip_keeps_raw_counts_and_review_binding(self):
        value = completed_record()
        raw_only = copy.deepcopy(value)
        for row in raw_only['occurrences']:
            row.pop('display')
        old = sf.prepare_record(raw_only)
        new = sf.prepare_record(value)
        self.assertNotEqual(old['snapshot_id'], new['snapshot_id'])
        self.assertEqual([row['assignment_context_hash'] for row in old['occurrences']],
                         [row['assignment_context_hash'] for row in new['occurrences']])
        self.put(value)
        report = self.get()
        self.assertEqual(report['total'], 2)
        self.assertEqual([sense['count'] for sense in report['senses']], [1, 1])
        for sense in report['senses']:
            row = sense['occurrences'][0]
            self.assertIn('______', row['english'])
            self.assertNotIn('______', row['display']['english'])
        rendered = sf.render_report(report)
        self.assertNotIn('______', rendered)
        self.assertIn('cloze-answer', rendered)
        self.assertIn('。获得成功。', rendered)
        self.assertEqual(report['senses'][0]['occurrences'][0]['display']['translation'],
                         '一部小说中的新颖想法。获得成功。')
        self.assertIn('sf-target-chunk', rendered)
        self.assertEqual(sf.save_records(self.db, [value], self.root / 'backups')['snapshots'],
                         [new['snapshot_id']])

    def test_stale_completed_display_fails_before_database_write(self):
        value = completed_record()
        value['occurrences'][0]['display']['translation'] += '错误'
        with self.assertRaisesRegex(ValueError, 'display translation hash'):
            self.put(value)
        self.assertFalse(self.db.exists())

    def test_same_physical_token_is_counted_once_but_two_ranges_count_twice(self):
        value = record()
        duplicate = copy.deepcopy(value['occurrences'][0])
        duplicate['sentence_id'] = 'kaoyan:2022-01:completion-copy'
        value['occurrences'].append(duplicate)
        self.put(value)
        result = self.get()
        self.assertEqual(result['total'], 2)
        self.assertEqual([s['count'] for s in result['senses']], [1, 1])
        self.assertEqual(sum(sum(y['count'] for y in s['years']) for s in result['senses']), 2)
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM occurrences').fetchone()[0], 2)

    def test_identical_text_in_two_different_original_locations_stays_distinct(self):
        value = record()
        other = copy.deepcopy(value['occurrences'][0])
        other['physical_source'] = ['paper', 'block-2']
        other['sentence_id'] = 'kaoyan:2022-01:p:block-2:0'
        value['occurrences'].append(other)
        value['expected_occurrences'] = 3
        reseal(value)
        self.put(value)
        self.assertEqual(self.get()['senses'][1]['count'], 2)

    def test_unresolved_does_not_inflate_any_sense(self):
        value = record()
        value['occurrences'][1].update(status='ambiguous', sense_index=None, reason='两个义项均可能',
                                       reviewed_sense_id=None, assignment_context_hash=None)
        self.put(value)
        result = self.get()
        self.assertEqual([s['count'] for s in result['senses']], [0, 1])
        self.assertEqual(result['pending_count'], 1)
        markup = sf.render_report(result)
        self.assertIn('待核对 1 次', markup)
        self.assertIn('已核对次数', markup)

    def test_invalid_or_conflicting_mapping_cannot_change_active_data(self):
        self.put(record())
        before = self.get()
        for change in ('unknown-sense', 'stale-hash', 'conflicting-duplicate', 'count-mismatch'):
            with self.subTest(change=change):
                value = record()
                if change == 'unknown-sense': value['occurrences'][0]['sense_index'] = 10
                if change == 'stale-hash': value['occurrences'][0]['english_hash'] = '0' * 64
                if change == 'conflicting-duplicate':
                    value['occurrences'].append({**value['occurrences'][0], 'sense_index': 0})
                if change == 'count-mismatch': value['expected_occurrences'] = 9
                with self.assertRaises(ValueError): self.put(value)
                self.assertEqual(self.get(), before)

    def test_reordered_definition_or_changed_context_invalidates_review(self):
        value = record()
        for change in ('reordered-senses', 'changed-gloss', 'changed-english',
                       'changed-translation', 'changed-location'):
            with self.subTest(change=change):
                stale = copy.deepcopy(value)
                if change == 'reordered-senses': stale['senses'].reverse()
                if change == 'changed-gloss': stale['senses'][0]['text'] = '（长篇）小说'
                if change == 'changed-english':
                    row = stale['occurrences'][0]
                    row['english'] += ' Elsewhere.'
                    row['english_hash'] = hashlib.sha256(row['english'].encode()).hexdigest()
                if change == 'changed-translation': stale['occurrences'][0]['translation'] += '另一处。'
                if change == 'changed-location': stale['occurrences'][0]['physical_source'][-1] = 'other'
                with self.assertRaises(ValueError): sf.prepare_record(stale)

    def test_sealing_requires_review_and_does_not_mutate_input(self):
        value = record()
        row = copy.deepcopy(value['occurrences'][0])
        row.pop('reviewed_sense_id'); row.pop('assignment_context_hash')
        before = copy.deepcopy(row)
        sealed = sf.seal_reviewed_assignment(value, row)
        self.assertEqual(row, before)
        self.assertEqual(sealed['sense_index'], 1)
        self.assertNotEqual(sealed['reviewed_sense_id'], sealed['assignment_context_hash'])
        with self.assertRaises(ValueError): sf.prepare_record({**value, 'occurrences': [row, value['occurrences'][1]]})
        row.update(status='unmatched', sense_index=None)
        with self.assertRaises(ValueError): sf.seal_reviewed_assignment(value, row)

    def test_full_alignment_is_validated_stored_and_bound_to_review(self):
        value = aligned_record()
        self.put(value)
        report = self.get()
        for sense in report['senses']:
            self.assertEqual(sense['occurrences'][0]['alignment'], value['occurrences'][0]['alignment'])
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            alignment = json.loads(db.execute('SELECT alignment_json FROM occurrences LIMIT 1').fetchone()[0])
            self.assertEqual(alignment, value['occurrences'][0]['alignment'])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('UPDATE assignments SET reviewed_sense_id=NULL')
        stale = copy.deepcopy(value)
        stale['occurrences'][0]['alignment']['alignments'][0]['zh'] = [[5, 8]]
        with self.assertRaises(ValueError): sf.prepare_record(stale)
        reseal(stale)  # Only an explicit new review may authorize changed correspondence.
        sf.prepare_record(stale)
        invalid = copy.deepcopy(value)
        invalid['occurrences'][0]['alignment']['translationHash'] = '0' * 64
        with self.assertRaises(ValueError): sf.seal_reviewed_assignment(invalid, invalid['occurrences'][0])

    def test_implicit_alignment_is_retained_without_inventing_chinese_ranges(self):
        value = aligned_record()
        row = value['occurrences'][0]
        row['alignment']['alignments'][0] = {'en': [2, 7], 'zh': [],
                                             'relation': 'implicit', 'note': '原译未明译目标词'}
        row['alignment_evidence'] = [{'english_range': [2, 7], 'translation_ranges': [],
                                       'relation': 'implicit'}]
        row['translation_ranges'] = []
        reseal(value)
        self.put(value)
        stored = self.get()['senses'][1]['occurrences'][0]
        self.assertEqual(stored['alignment']['alignments'][0]['zh'], [])
        self.assertEqual(stored['alignment_evidence'], row['alignment_evidence'])

    def test_proposal_finest_scope_can_differ_from_display_chunk_union(self):
        from anki_pipeline.sense_matching import propose_match
        value = aligned_record()
        row = value['occurrences'][0]
        row['alignment']['alignments'].append({'en': [0, len(row['english'])],
                                               'zh': [[0, len(row['translation'])]],
                                               'relation': 'equivalent'})
        row['translation_ranges'].append([0, len(row['translation'])])
        reseal(value)
        row = value['occurrences'][0]
        proposal = sf.seal_matching_proposal(value, row, propose_match(value['senses'], row))
        self.assertEqual(proposal['alignment_scope']['translation_ranges'], [[6, 8]])
        row['matching_proposal'] = proposal
        self.put(value)
        self.assertEqual(self.get()['senses'][1]['count'], 1)

    def test_suggestion_is_bound_persisted_and_never_becomes_a_count(self):
        value = aligned_record()
        row = value['occurrences'][0]
        row.update(status='unmatched', sense_index=None, reviewed_sense_id=None,
                   assignment_context_hash=None, reason='尚未核对')
        proposal = {'schema': 'exam-sense-proposal.v1', 'method': 'target-aligned-gloss-candidates.v1',
                    'status': 'suggested', 'automatic_confirmation': False,
                    'reason_code': 'aligned_gloss_candidate', 'reason': '仅供核对',
                    'candidate_sense_indices': [1],
                    'candidates': [{'sense_index': 1, 'pos': 'adj.', 'sense_text': '新颖的',
                                    'evidence': [{'gloss_atom': '新颖', 'source_gloss': '新颖的',
                                                  'english_range': [2, 7], 'translation_range': [6, 8],
                                                  'translation_text': '新颖'}]}],
                    'alignment_scope': {'english_range': [2, 7], 'translation_ranges': [[6, 8]]}}
        row['matching_proposal'] = sf.seal_matching_proposal(value, row, proposal)
        self.put(value)
        report = self.get()
        self.assertEqual([sense['count'] for sense in report['senses']], [1, 0])
        self.assertEqual(report['pending_count'], 1)
        self.assertEqual(report['pending'][0]['matching_proposal']['automatic_confirmation'], False)
        with closing(sqlite3.connect(self.db)) as db, db:
            stored = json.loads(db.execute('SELECT matching_proposal_json FROM assignments '
                                          'WHERE matching_proposal_json IS NOT NULL').fetchone()[0])
            self.assertEqual(stored, row['matching_proposal'])
        for change in ('definition', 'evidence', 'scope', 'confirmation', 'sense-id'):
            with self.subTest(change=change):
                invalid = copy.deepcopy(value)
                candidate = invalid['occurrences'][0]['matching_proposal']
                if change == 'definition': invalid['senses'][1]['text'] = '新奇的'
                if change == 'evidence': candidate['candidates'][0]['evidence'][0]['translation_text'] = '其他'
                if change == 'scope': candidate['alignment_scope']['english_range'] = [1, 8]
                if change == 'confirmation': candidate['automatic_confirmation'] = True
                if change == 'sense-id': candidate['candidate_sense_ids'] = ['0' * 64]
                with self.assertRaises(ValueError): sf.prepare_record(invalid)
        self.assertEqual(self.get(), report)

    def test_schema_migration_and_activations_roll_back_together(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript(LEGACY_SCHEMA)
            db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)",
                       ('legacy', 'other', 'legacy-card', 'legacy', 'oxford', '{}', 0, 'old', '{}'))
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', ('other', 'legacy-card', 'legacy'))
            db.execute("CREATE TRIGGER force_failure BEFORE INSERT ON assignments "
                       "BEGIN SELECT RAISE(ABORT, 'fixture late assignment failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.put(record())
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT id FROM snapshots').fetchall(), [('legacy',)])
            self.assertEqual(db.execute('SELECT snapshot_id FROM active_snapshots').fetchall(), [('legacy',)])
            self.assertNotIn('alignment_json', {row[1] for row in db.execute('PRAGMA table_info(occurrences)')})
            db.execute('DROP TRIGGER force_failure')
        self.put(record())
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
            self.assertEqual(db.execute("SELECT snapshot_id FROM active_snapshots WHERE book_id='other'").fetchone()[0], 'legacy')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(self.get()['total'], 2)
        backup = list((self.root / 'backups').glob('*.sqlite3'))[-1]
        with closing(sqlite3.connect(backup)) as db, db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT id FROM snapshots').fetchall(), [('legacy',)])

    def test_every_owned_connection_closes_on_success_early_return_and_failure(self):
        original_connect = sqlite3.connect
        opened = []

        def tracked_connect(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            opened.append(db)
            return db

        with patch.object(sf.sqlite3, 'connect', side_effect=tracked_connect):
            failed = self.root / 'failed-init.sqlite3'
            with patch.object(sf, '_SQL', 'CREATE TABLE partial_init (id INTEGER); INVALID SQL;'):
                with self.assertRaises(sqlite3.OperationalError):
                    sf.save_records(failed, [record()], self.root / 'backups')
            self.assertFalse(failed.exists())
            self.put(record())  # Includes fresh-schema initialization.
            self.get()
            self.assertIsNone(sf.read_card(self.db, 'absent', 'absent'))
            self.put(record())  # Includes read-only validation and backup handles.
            invalid = self.root / 'invalid.sqlite3'
            with closing(sqlite3.connect(invalid)) as db, db:
                db.execute('PRAGMA user_version=100')
            with self.assertRaises(ValueError): sf.read_card(invalid, 'absent', 'absent')
            corrupt = self.root / 'corrupt.sqlite3'
            corrupt.write_bytes(b'not a sqlite database')
            with self.assertRaises(sqlite3.DatabaseError): sf.read_card(corrupt, 'absent', 'absent')
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute("CREATE TRIGGER force_failure BEFORE INSERT ON assignments "
                           "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
            changed = record(); changed['senses'][0]['text'] = '（长篇）小说'; reseal(changed)
            with self.assertRaises(sqlite3.IntegrityError): self.put(changed)
        self.assertGreater(len(opened), 8)
        for index, db in enumerate(opened):
            with self.subTest(connection=index), self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')

    def test_idempotence_and_definition_change_keep_old_snapshot_and_backup(self):
        self.put(record()); first = self.get()
        self.put(record())
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 1)
        changed = record(); changed['senses'][0]['text'] = '（长篇）小说'
        with self.assertRaises(ValueError): self.put(changed)
        reseal(changed)
        self.put(changed)
        self.assertNotEqual(self.get()['snapshot_id'], first['snapshot_id'])
        with closing(sqlite3.connect(self.db)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        backups = list((self.root / 'backups').glob('*.sqlite3'))
        self.assertTrue(backups)
        with closing(sqlite3.connect(backups[-1])) as db, db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_whole_batch_validates_before_database_creation(self):
        bad = record(); bad['card_id'] = 'bad'; bad['occurrences'][0]['status'] = 'guess'
        with self.assertRaises(ValueError): sf.save_records(self.db, [record(), bad], self.root / 'backups')
        self.assertFalse(self.db.exists())

    def test_count_zero_is_static_and_preview_is_escaped_and_highlights_exact_token(self):
        value = record(); value['senses'].append({'pos': 'n.', 'text': '<script>unused</script>'})
        reseal(value)
        self.put(value)
        markup = sf.render_report(self.get())
        self.assertIn('0 次', markup)
        self.assertIn('sf-empty', markup)
        self.assertNotIn('<script>unused</script>', markup)
        self.assertIn('&lt;script&gt;unused&lt;/script&gt;', markup)
        self.assertIn('A <mark class="target-word">novel</mark> idea for a novel.', markup)
        self.assertIn('sf-year-chip', markup)
        self.assertIn('data-sf-year="2022"', markup)

    def test_injection_preserves_every_other_byte_and_native_renderer(self):
        self.put(record())
        definition = '<div class="dictionary-definition">old</div>'
        page = '<html><head></head><body>' + definition + '<audio src="original.mp3"></audio></body></html>'
        updated = sf.inject_report(page, definition, self.get())
        self.assertIn('original.mp3', updated)
        self.assertIn('data-sense-frequency="v1"', updated)
        self.assertEqual(sf.remove_report(updated, definition), page)
        with self.assertRaises(ValueError): sf.inject_report(page + definition, definition, self.get())


if __name__ == '__main__': unittest.main()
