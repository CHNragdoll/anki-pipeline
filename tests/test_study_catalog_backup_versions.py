"""Frozen legacy backups and complete PG learning-extension recovery contracts."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_recovery as recovery
from anki_pipeline import study_progress_pg as progress


V1_FIXTURE = Path(__file__).parent / 'fixtures/study-catalog-backup-v1-minimal.jsonl'
V1_SHA256 = '8603a0dd4a09928b643c8998bcf15eb448c214d7b871ba08f59af5ccae679ad1'


class BackupHeaderVersionTests(unittest.TestCase):
    def test_frozen_pre_extension_v1_header_remains_supported(self):
        original = V1_FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(original).hexdigest(), V1_SHA256)
        with tempfile.TemporaryDirectory(dir='/tmp') as work:
            path = Path(work) / 'legacy.gz'
            path.write_bytes(gzip.compress(original))
            header = c.read_backup_header(path)
        self.assertEqual(header['schema'], 'study-catalog-postgresql-backup.v1')
        self.assertEqual(set(header['tables']), set(c.TABLES))
        self.assertEqual(len(header['tables']), 24)

    def test_unknown_version_extra_columns_and_unregistered_extensions_are_rejected(self):
        header = json.loads(V1_FIXTURE.read_bytes().splitlines()[0])
        variants = [{**header, 'schema': 'study-catalog-postgresql-backup.v999'},
                    {**header, 'extensions': {'unknown': {}}},
                    {**header, 'tables': {**header['tables'], 'unexpected': ['value']}},
                    {**header, 'tables': {**header['tables'], 'books': ['id', 'title', 'edition', 'extra']}}]
        with tempfile.TemporaryDirectory(dir='/tmp') as work:
            path = Path(work) / 'invalid.gz'
            for invalid in variants:
                with self.subTest(invalid=invalid):
                    path.write_bytes(gzip.compress(c.canonical(invalid).encode() + b'\n'))
                    with self.assertRaises(ValueError):
                        c.read_backup_header(path)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class LearningBackupVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.schemas = []
        self.addCleanup(self.cleanup_schemas)
        self.source = self.new_target()
        c.initialize(self.source)
        with c.connect(self.source) as db, db.transaction():
            progress.initialize_connection(db)
            c.event(db, 'backup fixture', {'exact': '原始审核说明'})
            db.execute('insert into metadata values(%s,%s)',
                       ('study.progress.aliases.v1', ' { "old-liu" : "liuxiaoyan2027" }\n'))
            db.execute('insert into metadata values(%s,%s)',
                       ('study.progress.migration.seal.v1', '{"source_sha256":"fixture-only"}'))
            fixtures = {
                'metadata': [('revision', 17)],
                'settings': [('redbook2027', 12, 77, .875)],
                'cards': [('redbook2027', 'card-b', 17, ' { "due" : 1.0, "text":"中" }\n', '2026-10-17T01:02:03+08:00'),
                          ('redbook2027', 'card-a', 0, None, None)],
                'reviews': [(7, 'redbook2027', 'card-a', '2026-10-17T01:02:04+08:00', '2026-10-17', 3,
                             1234, 'new', 1, None, ' { "elapsed_days":0.10 }\n', None, 1),
                            (19, 'redbook2027', 'card-b', '2026-10-17T01:04:04+08:00', '2026-10-17', 4,
                             4321, 'review', 0, '{"before":true}', '{"after":null}', '', 18)],
                'undo': [('redbook2027', 19)],
                'requests': [('review-request-一', 'original-request-hash', 19)],
                'card_controls': [('redbook2027', 'card-b', 2, 1, None, '笔记\n完整保留  ')],
                'card_actions': [('control-request-一', 'original-control-hash')],
                'preferences': [(1, ' { "theme": "night", "volume": 0.0 }\n')],
                'sequences': [('reviews', 103)],
            }
            for table in progress.TABLES:
                rows = fixtures[table.removeprefix('study_progress_')]
                query = sql.SQL('insert into {} values({})').format(sql.Identifier(table),
                    sql.SQL(',').join(sql.Placeholder() for _ in progress.COLUMNS[table]))
                for row in rows:
                    db.execute(query, row)
        self.backup = None

    def cleanup_schemas(self):
        with psycopg.connect(os.environ['ANKI_STUDY_TEST_DSN'], autocommit=True) as db:
            for schema in self.schemas:
                if not schema.startswith('testcatalog_backup_'):
                    raise AssertionError('Never clean up a non-test schema')
                db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))

    def new_target(self):
        selected = c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_backup_' + uuid.uuid4().hex)
        self.schemas.append(selected.schema)
        return selected

    def save(self):
        self.backup = c.backup(self.source, self.root / 'backups')
        return self.backup

    def read_records(self):
        return [json.loads(line) for line in gzip.decompress(self.backup.read_bytes()).splitlines()]

    def rewrite(self, records):
        rows = b''.join((c.canonical(record) + '\n').encode() for record in records[1:-1])
        counts = {table: 0 for table in records[0]['tables']}
        for table, _ in records[1:-1]:
            counts[table] += 1
        records[-1] = {'counts': counts, 'rows_sha256': hashlib.sha256(rows).hexdigest()}
        raw = (c.canonical(records[0]) + '\n').encode() + rows + (c.canonical(records[-1]) + '\n').encode()
        self.backup.write_bytes(gzip.compress(raw))

    def assert_missing_schema(self, selected):
        with psycopg.connect(selected.dsn, autocommit=True) as db:
            self.assertIsNone(db.execute('select 1 from pg_namespace where nspname=%s', (selected.schema,)).fetchone())

    def test_v2_backup_restore_and_independent_verifier_cover_all_34_tables(self):
        saved = self.save()
        records = self.read_records()
        self.assertEqual(records[0]['schema'], 'study-catalog-postgresql-backup.v2')
        self.assertEqual(set(records[0]['tables']), set(c.TABLES) | set(progress.TABLES))
        self.assertEqual(records[0]['extensions'], {progress.METADATA_KEY: progress.DESCRIPTOR})
        self.assertTrue(all(records[-1]['counts'][table] for table in progress.TABLES))
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        restored = self.new_target()
        c.restore(saved, restored)
        self.assertEqual(c.logical_digest(self.source), c.logical_digest(restored))
        report = recovery.verify_restore(saved, restored, chunk_hashes=2, merge_files=2)
        self.assertTrue(report['complete'])
        self.assertEqual(report['schema'], 'study-catalog-restore-verification.v2')
        self.assertEqual(set(report['tables']), set(c.TABLES) | set(progress.TABLES))
        self.assertEqual(report['tables']['study_progress_sequences']['rows'], 1)
        with c.connect(restored, readonly=True) as db:
            self.assertEqual(db.execute('select seq from study_progress_sequences').fetchone()[0], 103)
            self.assertEqual(db.execute('select value from metadata where key=%s',
                                       ('study.progress.aliases.v1',)).fetchone()[0], ' { "old-liu" : "liuxiaoyan2027" }\n')

    def test_legacy_frozen_v1_restores_only_its_original_24_table_scope(self):
        saved = self.root / 'frozen-v1.gz'
        saved.write_bytes(gzip.compress(V1_FIXTURE.read_bytes()))
        restored = self.new_target()
        c.restore(saved, restored)
        report = recovery.verify_restore(saved, restored, chunk_hashes=2, merge_files=2)
        self.assertEqual(report['schema'], 'study-catalog-restore-verification.v1')
        self.assertEqual(len(report['tables']), 24)
        with self.assertRaises(FileExistsError):
            c.restore(saved, self.source)
        with self.assertRaisesRegex(ValueError, 'tables|scope|format'):
            recovery.verify_restore(saved, self.source)

    def test_unknown_tables_partial_learning_and_extra_columns_cannot_be_silently_omitted(self):
        self.save()
        for change in ('create table future_aliases(value text)',
                       'alter table study_progress_cards add column unregistered text',
                       'drop table study_progress_sequences'):
            selected = self.new_target()
            c.restore(self.backup, selected)
            with c.connect(selected) as db:
                db.execute(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                c.backup(selected, self.root / 'invalid-backups')
            self.assertEqual(list((self.root / 'invalid-backups').glob('*')), [])

    def test_incorrect_or_absent_learning_marker_refuses_backup(self):
        self.save()
        for value in (None, '{}', c.canonical({**progress.DESCRIPTOR, 'version': True})):
            selected = self.new_target()
            c.restore(self.backup, selected)
            with c.connect(selected) as db:
                if value is None:
                    db.execute('delete from metadata where key=%s', (progress.METADATA_KEY,))
                else:
                    db.execute('update metadata set value=%s where key=%s', (value, progress.METADATA_KEY))
            with self.subTest(value=value), self.assertRaises(ValueError):
                c.backup(selected, self.root / 'invalid-marker-backups')

    def test_missing_watermark_row_is_preserved_instead_of_inventing_zero(self):
        with c.connect(self.source) as db:
            db.execute('delete from study_progress_sequences')
        restored = self.new_target()
        c.restore(self.save(), restored)
        report = recovery.verify_restore(self.backup, restored, chunk_hashes=2, merge_files=2)
        self.assertEqual(report['tables']['study_progress_sequences']['rows'], 0)
        with c.connect(restored, readonly=True) as db:
            self.assertIsNone(db.execute('select seq from study_progress_sequences').fetchone())

    def test_each_learning_table_change_is_seen_by_verification_and_logical_digest(self):
        self.save()
        original = c.logical_digest(self.source)
        mutations = {'metadata': "update study_progress_metadata set value=value+1",
            'settings': "update study_progress_settings set desired_retention=.87500001",
            'cards': "update study_progress_cards set scheduler_json='{}' where card_id='card-b'",
            'reviews': "update study_progress_reviews set before_introduced_at=NULL where id=19",
            'undo': "update study_progress_undo set review_id=NULL",
            'requests': "update study_progress_requests set payload_hash='changed'",
            'card_controls': "update study_progress_card_controls set note='changed'",
            'card_actions': "update study_progress_card_actions set payload_hash='changed'",
            'preferences': "update study_progress_preferences set value='{}'",
            'sequences': "update study_progress_sequences set seq=104"}
        for table in progress.TABLES:
            restored = self.new_target()
            c.restore(self.backup, restored)
            with c.connect(restored) as db:
                db.execute(mutations[table.removeprefix('study_progress_')])
            with self.subTest(table=table):
                self.assertNotEqual(c.logical_digest(restored), original)
                with self.assertRaisesRegex(ValueError, 'table ' + table):
                    recovery.verify_restore(self.backup, restored, chunk_hashes=2, merge_files=2)

    def test_corrupt_v2_header_and_metadata_roll_back_the_entire_new_schema(self):
        self.save()
        original = self.backup.read_bytes()
        for change in ('extra-table', 'extra-column', 'missing-sequence-table', 'wrong-marker'):
            self.backup.write_bytes(original)
            records = self.read_records()
            if change == 'extra-table':
                records[0]['tables']['future_aliases'] = ['value']
            elif change == 'extra-column':
                records[0]['tables']['study_progress_cards'].append('unregistered')
            elif change == 'missing-sequence-table':
                records[0]['tables'].pop('study_progress_sequences')
            else:
                for row in records[1:-1]:
                    if row[0] == 'metadata' and row[1][0] == progress.METADATA_KEY:
                        row[1][1] = '{}'
            if change == 'wrong-marker':
                self.rewrite(records)
            else:
                self.backup.write_bytes(gzip.compress(b''.join((c.canonical(row) + '\n').encode() for row in records)))
            selected = self.new_target()
            with self.subTest(change=change), self.assertRaises(ValueError):
                c.restore(self.backup, selected)
            self.assert_missing_schema(selected)

    def test_backup_name_collision_never_deletes_the_existing_file(self):
        directory = self.root / 'collision'
        directory.mkdir()
        existing = directory / 'catalog-20261017T000000-12345678.pg.jsonl.gz'
        existing.write_bytes(b'pre-existing unrelated backup')
        with patch.object(c, 'datetime') as clock, \
                patch.object(c.uuid, 'uuid4', return_value=SimpleNamespace(hex='12345678')):
            clock.now.return_value = datetime(2026, 10, 17, tzinfo=timezone.utc)
            with self.assertRaises(FileExistsError):
                c.backup(self.source, directory)
        self.assertEqual(existing.read_bytes(), b'pre-existing unrelated backup')

    def test_failed_backup_removes_only_its_own_inode(self):
        original_rows = c._rows
        for replace in (False, True):
            directory = self.root / ('replacement' if replace else 'incomplete')

            def failing_rows(db, name, *, ordered=True):
                for row in original_rows(db, name, ordered=ordered):
                    yield row
                    if replace:
                        owned, = directory.iterdir()
                        owned.unlink()
                        owned.write_bytes(b'independent later writer')
                    raise OSError('injected backup row failure')

            with self.subTest(replace=replace), patch.object(c, '_rows', side_effect=failing_rows):
                with self.assertRaisesRegex(OSError, 'injected backup row failure'):
                    c.backup(self.source, directory)
            remaining = list(directory.iterdir())
            if replace:
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining[0].read_bytes(), b'independent later writer')
            else:
                self.assertEqual(remaining, [])

    def test_existing_public_directory_creates_private_backup_atomically(self):
        directory = self.root / 'existing-directory'
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
        original_open = io.open
        observed_modes = []

        def observed_open(file, mode='r', *args, **kwargs):
            stream = original_open(file, mode, *args, **kwargs)
            if 'x' in mode and Path(file).parent.resolve() == directory.resolve():
                # This runs immediately after creation, before backup code can
                # chmod, write, or enter the file's context manager.
                observed_modes.append(os.fstat(stream.fileno()).st_mode & 0o777)
            return stream

        previous_umask = os.umask(0o022)
        try:
            with patch('io.open', side_effect=observed_open), patch('builtins.open', side_effect=observed_open):
                saved = c.backup(self.source, directory)
        finally:
            os.umask(previous_umask)
        self.assertEqual(observed_modes, [0o600])
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o755)

    def test_successful_row_stream_cannot_report_a_foreign_pathname_as_backup(self):
        original_rows = c._rows
        for symlink in (False, True):
            directory = self.root / ('success-symlink' if symlink else 'success-replacement')
            foreign = self.root / ('foreign-symlink-target' if symlink else 'foreign-target')
            foreign.write_bytes(b'independent later writer')
            injected = False

            def replaced_rows(db, name, *, ordered=True):
                nonlocal injected
                for row in original_rows(db, name, ordered=ordered):
                    yield row
                    if not injected:
                        owned, = directory.iterdir()
                        owned.unlink()
                        if symlink:
                            owned.symlink_to(foreign)
                        else:
                            owned.write_bytes(foreign.read_bytes())
                        injected = True

            with self.subTest(symlink=symlink), patch.object(c, '_rows', side_effect=replaced_rows):
                with self.assertRaisesRegex(ValueError, 'backup output was replaced'):
                    c.backup(self.source, directory)
            remaining, = directory.iterdir()
            self.assertEqual(remaining.read_bytes(), b'independent later writer')
            self.assertEqual(foreign.read_bytes(), b'independent later writer')


if __name__ == '__main__':
    unittest.main()
