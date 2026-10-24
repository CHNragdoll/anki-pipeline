import gzip
import base64
import hashlib
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_recovery as recovery


class RowFingerprintTests(unittest.TestCase):
    def fingerprint(self, values, *, name='objects', columns=None):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            rows = recovery._Rows(Path(directory), name, columns or ['id', 'data'], chunk_hashes=2, merge_files=2)
            try:
                for value in values:
                    rows.add(value)
                return rows.fingerprint()
            finally:
                rows.close()

    def test_order_is_ignored_but_duplicates_bytes_types_and_boundaries_are_not(self):
        rows = [(1, b'\x00\xffsame'), (2, '中文'), (3, None), (4, 1.25), (5, True)]
        expected = self.fingerprint(rows)
        self.assertEqual(expected, self.fingerprint(reversed(rows)))
        self.assertNotEqual(expected, self.fingerprint(rows + [rows[0]]))
        self.assertNotEqual(expected, self.fingerprint([(1, b'\x00\xfesame')] + rows[1:]))
        self.assertNotEqual(expected, self.fingerprint(rows, name='tokens'))
        self.assertNotEqual(expected, self.fingerprint(rows, columns=['data', 'id']))
        for left, right in [(1, 1.0), (0.0, -0.0), (True, 1), (None, 'null')]:
            self.assertNotEqual(recovery._row_hash([left]), recovery._row_hash([right]))
        self.assertEqual(recovery._row_hash([b'\x00\xff', 1.25]),
                         hashlib.sha256(c.canonical([{'$bytes': 'AP8='}, 1.25]).encode()).digest())

    def test_large_byte_cells_are_canonically_hashed_in_bounded_base64_blocks(self):
        raw = bytes(range(256)) * 1001
        expected = hashlib.sha256(c.canonical([c._pack_cell(raw), '完整内容']).encode()).digest()
        original_encode = base64.b64encode
        sizes = []
        def bounded_encode(value):
            sizes.append(len(value))
            if len(value) > 49152:
                raise AssertionError('encoded a whole large payload at once')
            return original_encode(value)
        packed = [c._pack_cell(raw), '完整内容']
        with patch.object(recovery.base64, 'b64encode', side_effect=bounded_encode):
            self.assertEqual(recovery._row_hash([raw, '完整内容']), expected)
            self.assertEqual(recovery._row_hash(packed, packed=True), expected)
        self.assertGreater(len(sizes), 8)
        # Backup v1's decoder accepts equivalent noncanonical pad bits; the
        # verifier compares actual decoded bytes rather than encoding spelling.
        self.assertEqual(recovery._row_hash([{'$bytes': 'Zh=='}], packed=True), recovery._row_hash([b'f']))
        for value in ['A', 'AA==AAAA', 'AA==\u4e2d', '!!!!']:
            with self.assertRaises(ValueError): recovery._row_hash([{'$bytes': value}], packed=True)

    def test_external_sort_uses_bounded_reads_and_multiple_merge_generations(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            directory = Path(directory)
            bucket = directory / 'bucket'
            values = [hashlib.sha256(str(i).encode()).digest() for i in range(73)]
            values += [values[0]] * 7
            bucket.write_bytes(b''.join(reversed(values)))
            work = directory / 'runs'
            work.mkdir()
            original_open = Path.open
            reads = []

            class GuardedReader:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): return self.stream.__exit__(*args)
                def read(self, size=-1):
                    self_limit = 2 * recovery._HASH_BYTES
                    if not 0 <= size <= self_limit:
                        raise AssertionError('external sort read an unbounded bucket')
                    reads.append(size)
                    return self.stream.read(size)

            def guarded(path, *args, **kwargs):
                stream = original_open(path, *args, **kwargs)
                return GuardedReader(stream) if path == bucket and args[0] == 'rb' else stream

            with patch.object(Path, 'open', guarded):
                result = recovery._sort_bucket(bucket, work, chunk_hashes=2, merge_files=2)
            self.assertGreater(len(reads), 20)
            self.assertTrue(result.name.startswith('merge-5-'))
            self.assertEqual(result.read_bytes(), b''.join(sorted(values)))

    def test_truncated_hash_files_and_nonfinite_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            path = Path(directory) / 'bucket'
            path.write_bytes(b'x' * 33)
            with self.assertRaisesRegex(ValueError, 'truncated'):
                recovery._sort_bucket(path, Path(directory), chunk_hashes=2, merge_files=2)
        for value in [math.inf, -math.inf, math.nan]:
            with self.assertRaises(ValueError): recovery._row_hash([value])


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class RestoreVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp')
        self.root = Path(self.temp.name)
        self.source = self.new_target()
        self.schemas = [self.source.schema]
        c.initialize(self.source)
        with c.connect(self.source) as db, c.transaction(db):
            self.object_id = c.put_object(db, b'\x00\xffpayload\x01' * 1000)
            c.ensure_word(db, 'training')
            c.ensure_word(db, 'train')
            c.ensure_book(db, 'book', '完整书籍', 2027)
            component = c.ensure_component(db, None, 'Answer', 'before')
            db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) '
                       'values(%s,%s,%s,%s,%s)',
                       (component, self.object_id, self.object_id, '完整记录', c.now()))
            c.event(db, 'fixture', {'number': 1.25, 'bytes': 'independent payload'})
        self.backup = c.backup(self.source, self.root / 'backups')
        self.restored = self.new_target()
        self.schemas.append(self.restored.schema)
        c.restore(self.backup, self.restored)

    def new_target(self):
        return c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_' + uuid.uuid4().hex)

    def tearDown(self):
        with psycopg.connect(self.source.dsn, autocommit=True) as db:
            for schema in self.schemas:
                db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
        self.temp.cleanup()

    def verify(self):
        return recovery.verify_restore(self.backup, self.restored, chunk_hashes=2, merge_files=2)

    def mutate_backup(self, transform):
        self.backup.write_bytes(gzip.compress(transform(gzip.decompress(self.backup.read_bytes()))))

    def test_every_table_and_sequence_checked_without_mutation_or_order_dependency(self):
        before = c.logical_digest(self.restored)
        with c.connect(self.restored) as db:
            # Rewrite physical word order without changing any row's value.
            db.execute('create temporary table saved_words as select * from words order by surface desc')
            db.execute('delete from words')
            db.execute('insert into words select * from saved_words')
        result = self.verify()
        self.assertTrue(result['complete'])
        self.assertEqual(set(result['tables']), set(c.TABLES))
        self.assertTrue(all(len(value['sha256']) == 64 for value in result['tables'].values()))
        self.assertEqual(result['tables']['words']['rows'], 2)
        self.assertEqual(result['sequences']['events']['next_id'], 2)
        self.assertIn('not stored', result['sequence_scope'])
        self.assertEqual(before, c.logical_digest(self.restored))
        with c.connect(self.restored) as db:
            c.event(db, 'continued', {})
            self.assertEqual(db.execute('select max(id) from events').fetchone()[0], 2)

    def test_missing_and_extra_rows_are_rejected(self):
        with c.connect(self.restored) as db:
            db.execute("delete from words where surface='train'")
        with self.assertRaisesRegex(ValueError, 'table words'): self.verify()
        with c.connect(self.restored) as db:
            c.ensure_word(db, 'train')
            c.ensure_word(db, 'surplus')
        with self.assertRaisesRegex(ValueError, 'table words'): self.verify()

    def test_same_primary_key_with_changed_bytea_is_rejected(self):
        with c.connect(self.restored) as db:
            old = db.execute('select data from objects where id=%s', (self.object_id,)).fetchone()[0]
            changed = bytes([old[0] ^ 1]) + old[1:]
            db.execute('update objects set data=%s where id=%s', (changed, self.object_id))
        with self.assertRaisesRegex(ValueError, 'table objects'): self.verify()

    def test_column_order_and_names_must_match(self):
        with c.connect(self.restored) as db:
            db.execute('alter table books rename column title to renamed_title')
        with self.assertRaisesRegex(ValueError, 'columns'): self.verify()

    def test_unexpected_table_is_not_silently_omitted(self):
        with c.connect(self.restored) as db:
            db.execute('create table unexpected(value text)')
        with self.assertRaisesRegex(ValueError, 'unexpected tables'): self.verify()

    def test_backup_footer_rows_digest_and_trailing_data_are_verified(self):
        original = self.backup.read_bytes()
        for transform in [lambda raw: raw.replace(b'rows_sha256', b'wrong_digest'),
                          lambda raw: raw.replace(b'training', b'traininx'),
                          lambda raw: raw + b'\n']:
            self.backup.write_bytes(original)
            self.mutate_backup(transform)
            with self.assertRaisesRegex(ValueError, 'footer|rows_sha256'): self.verify()

    def test_truncated_backup_is_rejected_and_temporary_files_removed(self):
        self.backup.write_bytes(self.backup.read_bytes()[:-9])
        original_temporary = tempfile.TemporaryDirectory
        allocated = []
        def tracked_temporary(*args, **kwargs):
            temp = original_temporary(*args, **kwargs)
            allocated.append(Path(temp.name))
            return temp
        with patch.object(recovery.tempfile, 'TemporaryDirectory', side_effect=tracked_temporary):
            with self.assertRaisesRegex(ValueError, 'invalid|incomplete'): self.verify()
        self.assertTrue(allocated)
        self.assertTrue(all(not path.exists() for path in allocated))
        self.assertEqual(allocated[0].parent, Path('/tmp'))

    def test_float_payloads_are_complete_typed_rows_and_nonfinite_is_rejected(self):
        # A read-only verifier is independent of business column types. A
        # future schema's REAL values must be hashed rather than rounded away.
        for selected in [self.source, self.restored]:
            with c.connect(selected) as db:
                db.execute('alter table books alter column edition type double precision')
                db.execute('update books set edition=1.25')
        self.backup = c.backup(self.source, self.root / 'float-backups')
        self.assertTrue(self.verify()['complete'])
        with c.connect(self.restored) as db: db.execute('update books set edition=1.25000001')
        with self.assertRaisesRegex(ValueError, 'table books'): self.verify()
        with c.connect(self.restored) as db: db.execute("update books set edition='Infinity'::double precision")
        with self.assertRaises(ValueError): self.verify()

    def test_sequence_collision_detected_and_rolled_back_inserts_do_not_cause_false_mismatch(self):
        with c.connect(self.restored) as db:
            with self.assertRaises(RuntimeError):
                with c.transaction(db):
                    c.event(db, 'rolled-back', {})
                    raise RuntimeError('rollback fixture')
        result = self.verify()
        self.assertEqual(result['sequences']['events']['max_id'], 1)
        self.assertEqual(result['sequences']['events']['next_id'], 3)
        with c.connect(self.restored) as db:
            sequence = db.execute("select pg_get_serial_sequence('events','id')").fetchone()[0]
            db.execute('select setval(%s,1,false)', (sequence,))
        with self.assertRaisesRegex(ValueError, 'collide'): self.verify()

    def test_all_rows_are_streamed_with_unordered_server_cursor(self):
        original_rows = c._rows
        calls = []
        def tracked_rows(db, name, *, ordered=True):
            calls.append((name, ordered))
            yield from original_rows(db, name, ordered=ordered)
        with patch.object(c, '_rows', side_effect=tracked_rows):
            self.verify()
        self.assertEqual(calls, [(name, False) for name in c.TABLES])

    def test_verification_does_not_retain_all_object_payloads(self):
        original_rows = c._rows
        live = 0
        peak = 0
        seen = 0
        class TrackedPayload(bytes):
            def __new__(cls, raw):
                nonlocal live, peak
                value = bytes.__new__(cls, raw)
                live += 1
                peak = max(peak, live)
                if live > 2:
                    raise AssertionError('verification retained a whole object result set')
                return value
            def __del__(self):
                nonlocal live
                live -= 1
        def tracked_rows(db, name, *, ordered=True):
            nonlocal seen
            for row in original_rows(db, name, ordered=ordered):
                if name == 'objects':
                    seen += 1
                    yield (*row[:3], TrackedPayload(row[3]))
                else:
                    yield row
        with patch.object(c, '_rows', side_effect=tracked_rows):
            self.assertTrue(self.verify()['complete'])
        self.assertGreater(seen, 2)
        self.assertLessEqual(peak, 2)
        self.assertEqual(live, 0)

    def test_target_scan_uses_one_repeatable_read_snapshot(self):
        original_rows = c._rows
        injected = False
        def concurrent_write(db, name, *, ordered=True):
            nonlocal injected
            if not injected:
                with c.connect(self.restored) as writer:
                    c.ensure_word(writer, 'committed-after-verification-snapshot')
                injected = True
            yield from original_rows(db, name, ordered=ordered)
        with patch.object(c, '_rows', side_effect=concurrent_write):
            self.assertTrue(self.verify()['complete'])
        self.assertTrue(injected)
        with self.assertRaisesRegex(ValueError, 'table words'): self.verify()


if __name__ == '__main__': unittest.main()
