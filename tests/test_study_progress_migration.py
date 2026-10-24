"""Sealed migration inputs use only owned temporary legacy SQLite fixtures."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

from anki_pipeline import study_progress_snapshot as snapshot
from tests.test_study_progress_snapshot import make_database, evidence


class ProgressMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.sqlite3'
        make_database(self.source)
        self.target = self.root / 'sealed.jsonl'

    def migration(self):
        from anki_pipeline import study_progress_migration
        return study_progress_migration

    def test_report_and_rows_are_produced_by_one_private_transaction(self):
        m = self.migration()
        original = snapshot._view
        calls = []
        def track(path):
            calls.append(path)
            return original(path)
        before = evidence(self.source)
        with patch.object(snapshot, '_view', side_effect=track), \
             patch.object(snapshot, 'canonical_rows', side_effect=AssertionError('source reopened')):
            receipt = m.seal_source(self.source, self.target)
        self.assertEqual(len(calls), 1)
        self.assertEqual(before, evidence(self.source))
        with m.read_seal(self.target, expected_sha256=receipt['sha256'], expected_bytes=receipt['bytes']) as seal:
            self.assertTrue(seal.authenticated)
            self.assertEqual(list(m.iter_sealed_rows(seal)), list(snapshot.canonical_rows(self.source)))
            self.assertEqual(seal.report['revisions'], {'global': 12, 'card_max': 12, 'review_max': 11})
            self.assertEqual(seal.report['review_sequence']['high_watermark'], 99)

    def test_row_sink_baseline_is_a_real_behavior_requirement(self):
        rows = []
        report = snapshot.inspect_snapshot(self.source, row_sink=rows.append)
        self.assertTrue(report['snapshot_valid'])
        self.assertEqual(rows, list(snapshot.canonical_rows(self.source)))

    def test_external_anchor_required_for_migration_rows_and_wrong_anchor_fails(self):
        m = self.migration(); receipt = m.seal_source(self.source, self.target)
        with m.read_seal(self.target) as seal:
            self.assertFalse(seal.authenticated)
            with self.assertRaises(m.SealError):
                list(m.iter_sealed_rows(seal))
        for kw in ({'expected_sha256': '0' * 64, 'expected_bytes': receipt['bytes']},
                   {'expected_sha256': receipt['sha256'], 'expected_bytes': receipt['bytes'] + 1},
                   {'expected_sha256': receipt['sha256']}):
            with self.subTest(kw=kw), self.assertRaises(m.SealError):
                m.read_seal(self.target, **kw)

    def test_destination_never_overwrites_existing_or_racing_file(self):
        m = self.migration(); self.target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):m.seal_source(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'keep')

    def test_fixed_private_copy_survives_source_artifact_replacement(self):
        m = self.migration(); receipt = m.seal_source(self.source, self.target)
        with m.read_seal(self.target, expected_sha256=receipt['sha256'], expected_bytes=receipt['bytes']) as seal:
            wanted = list(m.iter_sealed_rows(seal))
            self.target.unlink(); self.target.write_bytes(b'not the sealed package')
            self.assertEqual(list(m.iter_sealed_rows(seal)), wanted)
            gen = m.iter_sealed_rows(seal); next(gen); gen.close()
            self.assertEqual(list(m.iter_sealed_rows(seal)), wanted)
        with self.assertRaises(m.SealError):list(m.iter_sealed_rows(seal))

    def test_publish_permissions_receipt_actual_bytes_and_strict_tail(self):
        m = self.migration(); receipt = m.seal_source(self.source, self.target)
        raw = self.target.read_bytes()
        self.assertEqual(receipt['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(receipt['bytes'], len(raw))
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        for bad in (raw[:-1], raw + b'\n', raw + b'{}\n', raw.replace(b'"revision"', b'"revisioN"', 1)):
            path = self.root / 'bad.jsonl'; path.write_bytes(bad)
            with self.subTest(tail=bad[-20:]), self.assertRaises(m.SealError):m.read_seal(path)

    def test_unknown_header_fields_and_duplicate_json_keys_rejected(self):
        m = self.migration(); m.seal_source(self.source, self.target)
        raw = self.target.read_bytes(); header, rest = raw.split(b'\n', 1)
        for first in (header[:-1] + b',"ddl":"DROP TABLE cards"}',
                      header[:-1] + b',"schema":"study-progress-seal.v1"}'):
            path = self.root / 'bad.jsonl'; path.write_bytes(first+b'\n'+rest)
            with self.assertRaises(m.SealError):m.read_seal(path)

    def test_callback_error_or_cancel_cleans_only_owned_staging(self):
        m = self.migration(); before = evidence(self.source)
        for exception in (RuntimeError('write failure'), KeyboardInterrupt()):
            with self.subTest(exception=type(exception).__name__):
                with patch.object(m, '_write', side_effect=exception):
                    with self.assertRaises(type(exception)):m.seal_source(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assertFalse(any(p.name.startswith('.study-progress-seal-') for p in self.root.iterdir()))
                self.assertEqual(before, evidence(self.source))

    def test_recomputed_footer_does_not_hide_pk_type_order_count_or_report_changes(self):
        m = self.migration(); m.seal_source(self.source, self.target)
        original = [json.loads(line) for line in self.target.read_bytes().splitlines()]
        def attempt(change, message):
            values = json.loads(json.dumps(original))
            change(values)
            prefix = b''.join(m._json_line(value) for value in values[:-1])
            values[-1]['payload_bytes'] = len(prefix)
            values[-1]['payload_sha256'] = hashlib.sha256(prefix).hexdigest()
            path = self.root / 'tampered.jsonl'
            raw = prefix + m._json_line(values[-1]); path.write_bytes(raw)
            with self.assertRaisesRegex(m.SealError, message):
                m.read_seal(path, expected_sha256=hashlib.sha256(raw).hexdigest(), expected_bytes=len(raw))
        def duplicate(values):
            cards = [row for row in values if isinstance(row, list) and row[0] == 'cards']
            cards[1][1][0:2] = cards[0][1][0:2]
        def wrong_type(values):
            next(row for row in values if isinstance(row, list) and row[0] == 'settings')[1][1] = ['text', '20']
        def wrong_order(values):
            at = next(i for i,row in enumerate(values) if isinstance(row,list) and row[0] == 'reviews')
            values[at],values[at-1] = values[at-1],values[at]
        for change, message in ((duplicate, 'primary key'), (wrong_type, 'storage/type'),
                                (wrong_order, 'table order'),
                                (lambda x: x[-1].update(rows=999), 'digest/count'),
                                (lambda x: x[-1].update(rows_sha256='0'*64), 'row digest'),
                                (lambda x: x[0]['snapshot']['revisions'].update(global_=999), 'report differs')):
            with self.subTest(message=message):attempt(change, message)

    def test_actual_offline_wal_and_absent_sequence_survive_without_source_sidecars(self):
        m = self.migration()
        with closing(sqlite3.connect(self.source)) as writer, writer:
            writer.execute('pragma journal_mode=wal'); writer.execute('pragma wal_autocheckpoint=0')
            writer.execute("insert into card_actions values('wal-only',?)", ('c'*64,)); writer.commit()
            offline = self.root / 'offline'; offline.mkdir()
            path = offline / 'progress.sqlite3'
            path.write_bytes(self.source.read_bytes())
            Path(str(path)+'-wal').write_bytes(Path(str(self.source)+'-wal').read_bytes())
            before = evidence(path)
            receipt = m.seal_source(path, self.target)
        self.assertEqual(before, evidence(path)); self.assertFalse(Path(str(path)+'-shm').exists())
        with m.read_seal(self.target, expected_sha256=receipt['sha256'], expected_bytes=receipt['bytes']) as seal:
            self.assertEqual([r['role'] for r in seal.report['source']['files']], ['main','wal'])
            self.assertEqual(len(list(m.iter_sealed_rows(seal, table='card_actions'))),2)
        empty = self.root / 'empty.sqlite3'
        from tests.test_study_progress_snapshot import SCHEMA
        with closing(sqlite3.connect(empty)) as db, db:
            db.executescript(SCHEMA); db.execute("insert into metadata values('revision',0)")
        receipt = m.seal_source(empty, self.root/'empty.jsonl')
        with m.read_seal(self.root/'empty.jsonl', expected_sha256=receipt['sha256'], expected_bytes=receipt['bytes']) as seal:
            self.assertEqual(seal.report['review_sequence'], {'present':False,'high_watermark':None,'maximum_id':0})
            self.assertEqual(list(m.iter_sealed_rows(seal, table='sqlite_sequence')),[])

    def test_source_drift_from_same_transaction_callback_prevents_publication(self):
        m = self.migration(); original = m._write; changed = False
        def changing(stream, line):
            nonlocal changed
            original(stream,line)
            if not changed:
                changed = True
                with closing(sqlite3.connect(self.source)) as db, db:db.execute("update metadata set value=13 where key='revision'")
        with patch.object(m,'_write',side_effect=changing), self.assertRaises(snapshot.SnapshotError):
            m.seal_source(self.source,self.target)
        self.assertTrue(changed); self.assertFalse(self.target.exists())

    def test_destination_race_and_directory_fsync_failure_do_not_overwrite_or_leak(self):
        m = self.migration(); link = m.os.link
        def race(source,target,**kwargs):
            Path(target).write_bytes(b'racer')
            return link(source,target,**kwargs)
        with patch.object(m.os,'link',side_effect=race), self.assertRaises(FileExistsError):
            m.seal_source(self.source,self.target)
        self.assertEqual(self.target.read_bytes(),b'racer'); self.target.unlink()
        fsync = m.os.fsync
        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('directory fsync failed')
            return fsync(fd)
        with patch.object(m.os,'fsync',side_effect=fail_directory),self.assertRaises(OSError):
            m.seal_source(self.source,self.target)
        self.assertFalse(self.target.exists())
        self.assertFalse(any(p.name.startswith('.study-progress-seal-') for p in self.root.iterdir()))

    def test_private_file_modes_and_artifact_copy_swap_cleanup(self):
        m = self.migration(); modes=[]; structure=snapshot._structure
        def inspect(db):
            path=Path(db.execute('pragma database_list').fetchone()[2])
            modes.append((path.stat().st_mode&0o777,path.parent.stat().st_mode&0o777))
            return structure(db)
        with patch.object(snapshot,'_structure',side_effect=inspect):receipt=m.seal_source(self.source,self.target)
        self.assertTrue(modes); self.assertEqual(set(modes),{(0o600,0o700)})
        copied=snapshot._copy_source_file
        def swap(source,target,sealed):
            copied(source,target,sealed)
            if source==self.target:
                replacement=self.root/'replacement';replacement.write_bytes(self.target.read_bytes());replacement.replace(self.target)
        with patch.object(snapshot,'_copy_source_file',side_effect=swap),self.assertRaises(m.SealError):
            m.read_seal(self.target,expected_sha256=receipt['sha256'],expected_bytes=receipt['bytes'])

    def test_private_mutation_between_iterator_yields_is_not_accepted_at_exhaustion(self):
        m=self.migration();receipt=m.seal_source(self.source,self.target)
        with m.read_seal(self.target,expected_sha256=receipt['sha256'],expected_bytes=receipt['bytes']) as seal:
            generator=m.iter_sealed_rows(seal);next(generator)
            private=Path(seal._temporary.name)/'artifact.jsonl'
            with private.open('r+b') as raw:
                raw.seek(-2,2);raw.write(b' ')
            with self.assertRaises(m.SealError):list(generator)

    def test_publish_interruption_and_after_validation_tamper_are_rejected_and_cleaned(self):
        m=self.migration();link=m.os.link
        def interrupted(source,target,**kwargs):
            link(source,target,**kwargs)
            raise KeyboardInterrupt
        with patch.object(m.os,'link',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
            m.seal_source(self.source,self.target)
        self.assertFalse(self.target.exists())
        def tamper(source,target,**kwargs):
            with Path(source).open('r+b') as stream:stream.write(b'!')
            return link(source,target,**kwargs)
        with patch.object(m.os,'link',side_effect=tamper),self.assertRaisesRegex(m.SealError,'published artifact'):
            m.seal_source(self.source,self.target)
        self.assertFalse(self.target.exists())

    def test_early_close_cancel_concurrency_and_closed_owner_release(self):
        m=self.migration();receipt=m.seal_source(self.source,self.target)
        with m.read_seal(self.target,expected_sha256=receipt['sha256'],expected_bytes=receipt['bytes']) as seal:
            private=Path(seal._temporary.name)
            rows=m.iter_sealed_rows(seal);next(rows)
            with self.assertRaises(m.SealError):next(m.iter_sealed_rows(seal))
            rows.close()
            rows=m.iter_sealed_rows(seal);next(rows)
            with self.assertRaises(KeyboardInterrupt):rows.throw(KeyboardInterrupt)
            rows=m.iter_sealed_rows(seal);next(rows)
            seal.close()
            with self.assertRaises(m.SealError):next(rows)
        self.assertFalse(private.exists())


if __name__ == '__main__':unittest.main()
