"""Read-only migration inputs use the real legacy nine-table SQLite shape."""
import hashlib
import json
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_progress_snapshot as snapshot


# This is the legacy backend's schema, not a fixture built from inspector constants.
SCHEMA = '''
CREATE TABLE card_controls (
 book TEXT NOT NULL, card_id TEXT NOT NULL, flag INTEGER NOT NULL DEFAULT 0,
 suspended INTEGER NOT NULL DEFAULT 0, buried_until TEXT, note TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(book,card_id), FOREIGN KEY(book,card_id) REFERENCES cards(book,card_id));
CREATE TABLE card_actions (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL);
CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE settings (book TEXT PRIMARY KEY, new_per_day INTEGER NOT NULL,
 review_per_day INTEGER NOT NULL, desired_retention REAL NOT NULL);
CREATE TABLE cards (book TEXT NOT NULL, card_id TEXT NOT NULL, revision INTEGER NOT NULL,
 scheduler_json TEXT, introduced_at TEXT, PRIMARY KEY(book, card_id));
CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT NOT NULL, card_id TEXT NOT NULL,
 answered_at TEXT NOT NULL, day TEXT NOT NULL, rating INTEGER NOT NULL,
 duration_ms INTEGER NOT NULL, phase TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0,
 before_json TEXT, after_json TEXT NOT NULL, before_introduced_at TEXT,
 revision_after INTEGER NOT NULL, FOREIGN KEY(book, card_id) REFERENCES cards(book, card_id));
CREATE INDEX reviews_book_day ON reviews(book, day, undone);
CREATE TABLE undo (book TEXT PRIMARY KEY, review_id INTEGER);
CREATE TABLE requests (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, review_id INTEGER NOT NULL,
 FOREIGN KEY(review_id) REFERENCES reviews(id));
PRAGMA user_version=1;
'''


def scheduler(book, card):
    numeric = int.from_bytes(hashlib.sha256(f'{book}\0{card}'.encode()).digest()[:8], 'big') & (2**53 - 1)
    # Whitespace, escaped Unicode and floating-point spelling must survive untouched.
    return ('{ "card_id" : ' + str(numeric) + ', "state": 2, "step": null, '
            '"stability": 2.5000, "difficulty": 4.0, '
            '"due": "2026-10-19T00:00:00+00:00", '
            '"last_review": "2026-10-17T00:00:00+00:00" }')


def make_database(path, *, reverse=False):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    db.execute("insert into metadata values('revision',12)")
    books = ['liu', '旧书-非活动🧪']
    for book in reversed(books) if reverse else books:
        db.execute('insert into settings values(?,20,200,.9)', (book,))
        db.execute('insert into undo values(?,null)', (book,))
    cards = [('liu', '卡-α', 11, scheduler('liu', '卡-α'), '2026-10-17T00:00:00+00:00'),
             ('旧书-非活动🧪', 'never learned', 12, None, None)]
    for card in reversed(cards) if reverse else cards:
        db.execute('insert into cards values(?,?,?,?,?)', card)
    db.execute('insert into reviews values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
               (7, 'liu', '卡-α', '2026-10-17T00:00:00+00:00', '2026-10-17', 3, 123,
                'new', 0, None, cards[0][3], None, 11))
    db.execute('update undo set review_id=7 where book=?', ('liu',))
    db.execute('insert into requests values(?,?,?)', ('review-retry', 'a' * 64, 7))
    db.execute('insert into card_actions values(?,?)', ('control-retry', 'b' * 64))
    db.execute('insert into card_controls values(?,?,?,?,?,?)',
               ('liu', '卡-α', 6, 1, '2026-10-18', '备注 e\u0301 与 é\n原文 🧪'))
    db.execute('insert into preferences values(1,?)', ('{ "theme":"dark", "extra":"\\u4e2d" }',))
    db.execute("update sqlite_sequence set seq=99 where name='reviews'")
    db.commit()
    db.close()


def evidence(path):
    found = {}
    for candidate in (path, Path(str(path) + '-wal')):
        if candidate.exists():
            raw = candidate.read_bytes()
            found[candidate.name] = (len(raw), candidate.stat().st_mtime_ns, hashlib.sha256(raw).hexdigest())
    return found


def directory_evidence(directory):
    """Include absent/new sidecars and directory mutations, not access times."""
    before = directory.stat()
    entries = {}
    for candidate in directory.iterdir():
        info = candidate.lstat()
        entries[candidate.name] = (info.st_dev, info.st_ino, info.st_mode,
                                   info.st_size, info.st_mtime_ns, info.st_ctime_ns,
                                   hashlib.sha256(candidate.read_bytes()).hexdigest())
    return before.st_mtime_ns, before.st_ctime_ns, entries


@contextmanager
def private_directories():
    original = tempfile.TemporaryDirectory
    created = []

    def track(*args, **kwargs):
        temporary = original(*args, **kwargs)
        created.append(Path(temporary.name))
        return temporary

    with patch.object(snapshot.tempfile, 'TemporaryDirectory', side_effect=track):
        yield created


class ProgressSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'progress.sqlite3'
        make_database(self.path)

    def mutate(self, statement, values=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(statement, values)

    def codes(self, report):
        return {item['code'] for item in report['blockers']}

    def offline_wal_without_shm(self):
        # Copy a committed live pair into an offline directory; never remove a
        # live writer's SHM to manufacture this case.
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal')
        writer.execute('pragma wal_autocheckpoint=0')
        writer.execute("insert into card_actions values('offline-wal',?)", ('c' * 64,))
        writer.commit()
        directory = Path(self.temp.name) / 'offline'
        directory.mkdir()
        path = directory / 'progress.sqlite3'
        path.write_bytes(self.path.read_bytes())
        Path(str(path) + '-wal').write_bytes(Path(str(self.path) + '-wal').read_bytes())
        self.assertFalse(Path(str(path) + '-shm').exists())
        return path

    def test_exact_rows_types_unicode_all_tables_and_source_unchanged(self):
        before = evidence(self.path)
        report = snapshot.inspect_snapshot(self.path)
        rows = [json.loads(line) for line in snapshot.canonical_rows(self.path)]
        self.assertTrue(report['snapshot_valid'])
        self.assertEqual(report['sqlite_schema_version'], 1)
        self.assertEqual(set(report['tables']), {
            'metadata', 'settings', 'cards', 'reviews', 'undo', 'requests',
            'card_controls', 'card_actions', 'preferences', 'sqlite_sequence'})
        self.assertEqual(report['tables']['cards']['rows'], 2)
        self.assertEqual(report['revisions'], {'global': 12, 'card_max': 12, 'review_max': 11})
        self.assertEqual(report['review_sequence'], {'present': True, 'high_watermark': 99, 'maximum_id': 7})
        card = next(value for table, value in rows if table == 'cards' and value[0] == ['text', 'liu'])
        self.assertEqual(card[3], ['text', scheduler('liu', '卡-α')])
        untouched = next(value for table, value in rows if table == 'cards' and value[0] != ['text', 'liu'])
        self.assertEqual(untouched[3:], [['null'], ['null']])
        setting = next(value for table, value in rows if table == 'settings')
        self.assertEqual(setting[1], ['integer', '20'])
        self.assertEqual(setting[3], ['real', float(.9).hex()])
        note = next(value[-1] for table, value in rows if table == 'card_controls')
        self.assertEqual(note, ['text', '备注 e\u0301 与 é\n原文 🧪'])
        self.assertIn('旧书-非活动🧪', report['books'])
        self.assertEqual({table for table, _ in rows}, set(report['tables']))
        self.assertEqual(before, evidence(self.path), 'inspection changed the source main/WAL bytes or mtime')

    def test_canonical_order_and_digest_ignore_insertion_order_not_text_bytes(self):
        other = Path(self.temp.name) / 'other.sqlite3'
        make_database(other, reverse=True)
        first = list(snapshot.canonical_rows(self.path))
        self.assertEqual(first, list(snapshot.canonical_rows(other)))
        self.assertEqual(snapshot.inspect_snapshot(self.path)['rows_sha256'],
                         snapshot.inspect_snapshot(other)['rows_sha256'])
        self.mutate('update cards set scheduler_json=? where book=?',
                    (json.dumps(json.loads(scheduler('liu', '卡-α')), ensure_ascii=False), 'liu'))
        self.assertNotEqual(first, list(snapshot.canonical_rows(self.path)), 'raw JSON was normalized away')

    def test_undone_history_for_inactive_book_is_not_filtered_out(self):
        raw = scheduler('旧书-非活动🧪', 'never learned')
        self.mutate('insert into reviews values(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (5, '旧书-非活动🧪', 'never learned', '2026-10-17T00:00:00+00:00',
                     '2026-10-17', 2, 4321, 'new', 1, None, raw, None, 10))
        report = snapshot.inspect_snapshot(self.path)
        self.assertTrue(report['snapshot_valid'])
        self.assertEqual(report['tables']['reviews']['rows'], 2)
        rows = [json.loads(line)[1] for line in snapshot.canonical_rows(self.path, table='reviews')]
        archived = next(row for row in rows if row[0] == ['integer', '5'])
        self.assertEqual(archived[8], ['integer', '1'])
        self.assertEqual(archived[10], ['text', raw])

    def test_source_connection_rejects_writes_inside_real_read_transaction(self):
        original = snapshot._structure
        observed = []

        def probe(db):
            observed.append((db.execute('pragma query_only').fetchone()[0], db.in_transaction))
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("insert into card_actions values('must-not-write',?)", ('c' * 64,))
            return original(db)

        before = evidence(self.path)
        with patch.object(snapshot, '_structure', side_effect=probe):
            self.assertTrue(snapshot.inspect_snapshot(self.path)['snapshot_valid'])
        self.assertEqual(observed, [(1, True)])
        self.assertEqual(before, evidence(self.path))

    def test_table_selection_is_exact_and_unknown_table_rejected(self):
        selected = list(snapshot.canonical_rows(self.path, table='requests'))
        self.assertEqual(len(selected), 1)
        self.assertEqual(json.loads(selected[0])[0], 'requests')
        with self.assertRaises(snapshot.SnapshotError):
            list(snapshot.canonical_rows(self.path, table='cards;drop table cards'))

    def test_dry_run_never_claims_switch_without_full_target_proof(self):
        before = evidence(self.path)
        missing = snapshot.dry_run(self.path)
        self.assertFalse(missing['ready_to_switch'])
        self.assertIn('aliases_missing', self.codes(missing))
        aliases = {'schema': 'study-progress-aliases.v1', 'books': {
            'liu': {'catalog_book': 'liuxiaoyan2027', 'cards': {'卡-α': 'source-one'}}}}
        incomplete = snapshot.dry_run(self.path, aliases=aliases)
        self.assertFalse(incomplete['alias_coverage_complete'])
        self.assertIn('aliases_incomplete', self.codes(incomplete))
        aliases['books']['旧书-非活动🧪'] = {'catalog_book': 'archived-source', 'cards': {'never learned': 'source-two'}}
        ready_source = snapshot.dry_run(self.path, aliases=aliases)
        self.assertTrue(ready_source['alias_coverage_complete'])
        self.assertFalse(ready_source['ready_to_switch'])
        self.assertIn('catalog_bindings_unverified', self.codes(ready_source))
        self.assertIn('pg_import_and_full_reconciliation', ready_source['unverified_scope'])
        self.assertEqual(ready_source, snapshot.dry_run(self.path, aliases=aliases))
        self.assertEqual(before, evidence(self.path))

    def test_alias_shape_extras_and_duplicate_destination_do_not_pass(self):
        cases = [[], {'schema': 'unknown', 'books': {}},
                 {'schema': 'study-progress-aliases.v1', 'books': {'liu': {'catalog_book': 'x', 'cards': {}}}},
                 {'schema': 'study-progress-aliases.v1', 'books': {
                     'liu': {'catalog_book': 'same', 'cards': {'卡-α': 'same'}},
                     '旧书-非活动🧪': {'catalog_book': 'same', 'cards': {'never learned': 'same'}}}}]
        for aliases in cases:
            with self.subTest(aliases=aliases):
                report = snapshot.dry_run(self.path, aliases=aliases)
                self.assertFalse(report['alias_coverage_complete'])
                self.assertFalse(report['ready_to_switch'])

    def test_real_wal_commits_are_seen_without_immutable_or_source_change(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal')
        writer.execute('pragma wal_autocheckpoint=0')
        writer.execute("insert into card_actions values('committed-in-wal',?)", ('c' * 64,))
        writer.commit()
        self.assertTrue(Path(str(self.path) + '-wal').exists())
        before = evidence(self.path)
        report = snapshot.inspect_snapshot(self.path)
        self.assertEqual(report['tables']['card_actions']['rows'], 2)
        self.assertEqual(before, evidence(self.path))
        self.assertTrue(any(row['role'] == 'wal' for row in report['source']['files']))

    def test_offline_wal_without_shm_never_creates_source_directory_entries(self):
        path = self.offline_wal_without_shm()
        before = directory_evidence(path.parent)
        report = snapshot.inspect_snapshot(path)
        self.assertTrue(report['snapshot_valid'])
        self.assertEqual(report['tables']['card_actions']['rows'], 2)
        self.assertEqual(before, directory_evidence(path.parent),
                         'read inspection created or changed a source-side SQLite sidecar')
        rows = [json.loads(row) for row in snapshot.canonical_rows(path, table='card_actions')]
        self.assertEqual(len(rows), 2)
        self.assertEqual(before, directory_evidence(path.parent))

    def test_private_wal_connection_and_sidecars_close_on_exhaustion_close_or_cancel(self):
        path = self.offline_wal_without_shm()
        before = directory_evidence(path.parent)
        original = snapshot._structure
        observed = []

        def probe(db):
            actual = Path(db.execute('pragma database_list').fetchone()[2])
            observed.append((db, actual))
            structure = original(db)
            self.assertNotEqual(actual, path)
            self.assertEqual(actual.parent.stat().st_mode & 0o777, 0o700)
            self.assertTrue(Path(str(actual) + '-wal').is_file())
            self.assertTrue(Path(str(actual) + '-shm').is_file())
            return structure

        for finish in ('exhaust', 'close', 'cancel'):
            with self.subTest(finish=finish), private_directories() as directories:
                with patch.object(snapshot, '_structure', side_effect=probe):
                    rows = snapshot.canonical_rows(path)
                    next(rows)
                    db, actual = observed[-1]
                    self.assertTrue(actual.parent.exists())
                    if finish == 'exhaust':
                        list(rows)
                    elif finish == 'close':
                        rows.close()
                    else:
                        with self.assertRaises(KeyboardInterrupt):
                            rows.throw(KeyboardInterrupt)
                self.assertEqual(len(directories), 1)
                self.assertFalse(directories[0].exists(), 'private sidecars leaked after reader cleanup')
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute('select 1')
                self.assertEqual(before, directory_evidence(path.parent))

    def test_private_copy_actual_bytes_and_length_must_match_sealed_source(self):
        original = snapshot._file_record
        before = directory_evidence(self.path.parent)

        for corruption in ('bytes', 'length'):
            def corrupt(candidate, role):
                if role == 'copy':
                    with candidate.open('r+b') as copied:
                        if corruption == 'length':
                            copied.seek(0, 2)
                            copied.write(b'!')
                        else:
                            value = copied.read(1)
                            copied.seek(0)
                            copied.write(bytes([value[0] ^ 1]))
                return original(candidate, role)

            with self.subTest(corruption=corruption), private_directories() as directories:
                with patch.object(snapshot, '_file_record', side_effect=corrupt), \
                     patch.object(snapshot.sqlite3, 'connect', side_effect=AssertionError('unsealed copy opened')):
                    with self.assertRaisesRegex(snapshot.SnapshotError, 'private copy does not match'):
                        snapshot.inspect_snapshot(self.path)
                self.assertEqual(len(directories), 1)
                self.assertFalse(directories[0].exists())
                self.assertEqual(before, directory_evidence(self.path.parent))

    def test_source_changed_or_replaced_while_staging_is_rejected_before_sqlite(self):
        original_copy = snapshot._copy_source_file
        original_open = Path.open
        for change in ('write', 'replace'):
            path = Path(self.temp.name) / f'drift-{change}.sqlite3'
            make_database(path)
            before = evidence(path)
            payload = path.read_bytes()
            state = {'copying': False, 'changed': False}

            def drift():
                state['changed'] = True
                if change == 'write':
                    with original_open(path, 'r+b') as stream:
                        value = stream.read(1)
                        stream.seek(0)
                        stream.write(bytes([value[0] ^ 1]))
                else:
                    replacement = path.with_name('replacement.sqlite3')
                    replacement.write_bytes(payload)
                    replacement.replace(path)

            class ChangingReader:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return self.stream.__exit__(*args)

                def fileno(self):
                    return self.stream.fileno()

                def read(self, size):
                    chunk = self.stream.read(size)
                    if chunk and not state['changed']:
                        drift()
                    return chunk

            def opening(candidate, mode='r', *args, **kwargs):
                stream = original_open(candidate, mode, *args, **kwargs)
                if candidate == path and mode == 'rb' and state['copying']:
                    return ChangingReader(stream)
                return stream

            def copy(source, target, sealed):
                state['copying'] = True
                try:
                    return original_copy(source, target, sealed)
                finally:
                    state['copying'] = False

            with self.subTest(change=change), private_directories() as directories:
                with patch.object(snapshot, '_copy_source_file', side_effect=copy), \
                     patch.object(Path, 'open', new=opening), \
                     patch.object(snapshot.sqlite3, 'connect', side_effect=AssertionError('moving source opened')):
                    with self.assertRaisesRegex(snapshot.SnapshotError, 'changed'):
                        snapshot.inspect_snapshot(path)
                self.assertTrue(state['changed'], 'source drift was not injected during the real read')
                self.assertFalse(directories[0].exists())
                if change == 'write':
                    self.assertNotEqual(before, evidence(path))
                else:
                    self.assertEqual(before[path.name][-1], evidence(path)[path.name][-1])

    def test_cancel_during_staging_removes_only_owned_private_files(self):
        original = snapshot._copy_source_file
        before = directory_evidence(self.path.parent)

        def cancel(source, target, sealed):
            original(source, target, sealed)
            raise KeyboardInterrupt

        with private_directories() as directories:
            with patch.object(snapshot, '_copy_source_file', side_effect=cancel), \
                 patch.object(snapshot.sqlite3, 'connect', side_effect=AssertionError('cancelled copy opened')):
                with self.assertRaises(KeyboardInterrupt):
                    snapshot.inspect_snapshot(self.path)
            self.assertEqual(len(directories), 1)
            self.assertFalse(directories[0].exists())
        self.assertEqual(before, directory_evidence(self.path.parent))

    def test_invalid_schema_and_sqlite_error_clean_private_files_and_connection(self):
        self.mutate('pragma user_version=2')
        before = directory_evidence(self.path.parent)
        with private_directories() as directories:
            with self.assertRaisesRegex(snapshot.SnapshotError, 'unsupported'):
                snapshot.inspect_snapshot(self.path)
            self.assertFalse(directories[0].exists())
        self.assertEqual(before, directory_evidence(self.path.parent))

        original = snapshot._structure
        connections = []

        def fail(db):
            connections.append(db)
            db.execute('select no_such_column')
            return original(db)

        with private_directories() as directories:
            with patch.object(snapshot, '_structure', side_effect=fail):
                with self.assertRaisesRegex(snapshot.SnapshotError, 'SQLite read failed: OperationalError'):
                    snapshot.inspect_snapshot(self.path)
            self.assertFalse(directories[0].exists())
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute('select 1')
        self.assertEqual(before, directory_evidence(self.path.parent))

    def test_canonical_generator_holds_one_consistent_read_transaction(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute('pragma journal_mode=wal')
        writer.execute('pragma wal_autocheckpoint=0')
        rows = snapshot.canonical_rows(self.path)
        first = next(rows)
        writer.execute("insert into card_actions values('concurrent',?)", ('c' * 64,))
        writer.commit()
        # A stable view must not silently seal a moving source file as an offline snapshot.
        with self.assertRaisesRegex(snapshot.SnapshotError, 'changed'):
            list(rows)
        self.assertEqual(json.loads(first)[0], 'metadata')

    def test_unknown_version_table_column_constraint_trigger_and_index_rejected(self):
        cases = ["pragma user_version=2", 'create table surprise(x text)',
                 'alter table cards add column future text',
                 'create trigger surprise after insert on cards begin select 1; end',
                 'create index surprise on cards(revision)']
        for index, statement in enumerate(cases):
            with self.subTest(statement=statement):
                path = Path(self.temp.name) / f'bad-{index}.sqlite3'
                make_database(path)
                with closing(sqlite3.connect(path)) as db, db:
                    db.execute(statement)
                before = evidence(path)
                with self.assertRaises(snapshot.SnapshotError):
                    snapshot.inspect_snapshot(path)
                self.assertEqual(before, evidence(path))

    def test_missing_autoincrement_or_foreign_key_is_not_known_schema(self):
        for replacement in (SCHEMA.replace('AUTOINCREMENT', ''),
                            SCHEMA.replace('FOREIGN KEY(review_id) REFERENCES reviews(id)', 'CHECK(review_id>0)')):
            path = Path(self.temp.name) / ('shape-' + str(len(replacement)) + '.sqlite3')
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript(replacement)
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.inspect_snapshot(path)

    def test_unrecognized_column_spelling_is_an_explicit_schema_rejection(self):
        path = Path(self.temp.name) / 'renamed-columns.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(SCHEMA.replace('metadata (key TEXT', 'metadata (KEY TEXT'))
            db.execute("insert into metadata values('revision',0)")
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.inspect_snapshot(path)

    def test_foreign_keys_and_undo_book_ownership_checked_without_writes(self):
        self.mutate("insert into requests values('orphan',?,999)", ('a' * 64,))
        self.mutate('update undo set review_id=7 where book=?', ('旧书-非活动🧪',))
        before = evidence(self.path)
        report = snapshot.inspect_snapshot(self.path)
        self.assertFalse(report['snapshot_valid'])
        self.assertIn('foreign_key_violation', self.codes(report))
        self.assertIn('undo_reference_invalid', self.codes(report))
        self.assertEqual(before, evidence(self.path))

    def test_revision_and_sequence_high_watermark_are_not_recomputed_or_fixed(self):
        self.mutate("update metadata set value=1 where key='revision'")
        self.mutate("update sqlite_sequence set seq=3 where name='reviews'")
        report = snapshot.inspect_snapshot(self.path)
        self.assertIn('global_revision_behind', self.codes(report))
        self.assertIn('review_sequence_behind', self.codes(report))
        self.assertEqual(report['review_sequence']['high_watermark'], 3)
        self.assertEqual(report['revisions']['global'], 1)

    def test_duplicate_or_unknown_sequence_rows_are_not_silently_dropped(self):
        self.mutate("insert into sqlite_sequence values('reviews',100)")
        report = snapshot.inspect_snapshot(self.path)
        self.assertIn('review_sequence_invalid', self.codes(report))
        self.assertEqual(report['tables']['sqlite_sequence']['rows'], 2)
        self.assertEqual(len(list(snapshot.canonical_rows(self.path, table='sqlite_sequence'))), 2)

    def test_safe_integer_and_actual_storage_types_checked(self):
        self.mutate("update cards set revision=? where book='liu'", (2**53,))
        self.mutate("update settings set new_per_day='not a number' where book='liu'")
        report = snapshot.inspect_snapshot(self.path)
        self.assertIn('unsafe_integer', self.codes(report))
        self.assertIn('storage_type_invalid', self.codes(report))

    def test_malformed_or_duplicate_json_and_wrong_scheduler_identity_block(self):
        for raw in ('{"card_id":1,"card_id":2}', '{bad', '{"number":NaN}',
                    scheduler('different-book', '卡-α')):
            with self.subTest(raw=raw):
                self.mutate("update cards set scheduler_json=? where book='liu'", (raw,))
                report = snapshot.inspect_snapshot(self.path)
                self.assertFalse(report['snapshot_valid'])
                self.assertTrue(self.codes(report) & {'json_invalid', 'scheduler_identity_invalid'})

    def test_schema_version_one_empty_database_has_no_invented_rows_or_sequence(self):
        path = Path(self.temp.name) / 'empty.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript(SCHEMA)
            db.execute("insert into metadata values('revision',0)")
        before = evidence(path)
        report = snapshot.inspect_snapshot(path)
        self.assertTrue(report['snapshot_valid'])
        self.assertEqual(report['tables']['cards']['rows'], 0)
        self.assertEqual(report['review_sequence'], {'present': False, 'high_watermark': None, 'maximum_id': 0})
        self.assertEqual(before, evidence(path))

    def test_missing_nonregular_and_symlink_inputs_rejected(self):
        missing = Path(self.temp.name) / 'not-created.sqlite3'
        for path in (missing, Path(self.temp.name)):
            with self.subTest(path=path), self.assertRaises(snapshot.SnapshotError):
                snapshot.inspect_snapshot(path)
        self.assertFalse(missing.exists())
        alias = Path(self.temp.name) / 'alias.sqlite3'
        alias.symlink_to(self.path)
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.inspect_snapshot(alias)


if __name__ == '__main__':
    unittest.main()
