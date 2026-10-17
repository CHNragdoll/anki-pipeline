"""Explicit version registration against a new, disposable PostgreSQL schema.

No test connects to the production schema or imports into an Anki collection.
The tiny source APKG is used only to exercise the real catalog projections.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_anki as versions
from anki_pipeline import study_catalog_native_delivery as delivery
from anki_pipeline.study_catalog_export import compiled_source_sha256, project_book, project_note
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_compiled_runtime import CURRENT_RUNTIME_SHA256
from tests import test_study_catalog_import as fixtures


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class NativeDeliveryInputTests(unittest.TestCase):
    def test_explicit_target_and_strict_input_types_are_required_before_connecting(self):
        row = {'note_id': 1, 'id': 'opaque', 'source_sha256': 'a'*64,
               'record_sha256': 'b'*64, 'runtime_sha256': CURRENT_RUNTIME_SHA256}
        with patch.object(c, 'connect', side_effect=AssertionError('must not connect')):
            for target in (None, True, {}, Path('/tmp/not-a-connection'), '', c.Target('', 'testcatalog_unused')):
                with self.subTest(target=type(target)), self.assertRaisesRegex(ValueError, 'explicit catalog'):
                    delivery.plan_native_delivery(target, {'book': [row]})
            for value in ('1', True, 0, -1, 2**63):
                with self.subTest(note_id=value), self.assertRaises(ValueError):
                    delivery.plan_native_delivery(c.Target('unused', 'testcatalog_unused'),
                                                  {'book': [{**row, 'note_id': value}]})
            for rows in ([], [row, row], [{**row, 'extra': 1}], [{**row, 'runtime_sha256': 'c'*64}]):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    delivery.plan_native_delivery(c.Target('unused', 'testcatalog_unused'), {'book': rows})

    def test_journal_directory_replacement_never_writes_into_foreign_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, kept, foreign = root/'journal', root/'kept', root/'foreign'
            foreign.mkdir()
            before = {'metadata': {key: None for key in delivery.WRITE_KEYS}}
            after = {'metadata': {key: 'after' for key in delivery.WRITE_KEYS}}
            with delivery._journal(path, {'test_only': True}, 'a'*64, before) as owned:
                path.rename(kept)
                path.symlink_to(foreign, target_is_directory=True)
                with self.assertRaisesRegex(ValueError, 'directory ownership'):
                    delivery._post_journal(owned, before, after)
            self.assertEqual(list(foreign.iterdir()), [])
            self.assertFalse((kept/'after.json').exists())

    def test_original_before_bytes_and_inode_must_survive_until_sealing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            before = {'metadata': {key: None for key in delivery.WRITE_KEYS}}
            after = {'metadata': {key: 'after' for key in delivery.WRITE_KEYS}}
            for mode in ('bytes', 'inode'):
                path = root/mode
                with self.subTest(mode=mode), delivery._journal(path, {'test_only': True}, 'a'*64, before) as owned:
                    file = path/'before.json'
                    if mode == 'bytes':
                        file.write_text(c.canonical({'metadata': {key: 'foreign' for key in delivery.WRITE_KEYS}}))
                    else:
                        original = file.read_bytes()
                        file.rename(path/'before-kept.json')
                        file.write_bytes(original)
                    with self.assertRaisesRegex(ValueError, 'journal (bytes|file ownership) changed'):
                        delivery._post_journal(owned, before, after)
                    self.assertFalse((path/'SEAL.json').exists())

    def test_postcommit_directory_loss_is_explicit_committed_error_without_foreign_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, kept, foreign = root/'journal', root/'kept', root/'foreign'
            foreign.mkdir()
            before = {'metadata': {key: None for key in delivery.WRITE_KEYS}}
            after = {'metadata': {key: 'after' for key in delivery.WRITE_KEYS}}
            with delivery._journal(path, {'test_only': True}, 'a'*64, before) as owned:
                delivery._post_journal(owned, before, after)
                path.rename(kept)
                path.symlink_to(foreign, target_is_directory=True)
                with self.assertRaises(delivery.NativeDeliveryCommittedError) as caught:
                    delivery._committed(owned, {'test_receipt': True})
                self.assertTrue(caught.exception.committed)
            self.assertEqual(list(foreign.iterdir()), [])
            self.assertFalse((kept/'COMMITTED.json').exists())

    def test_foreign_fifo_is_rejected_without_blocking_on_read_open(self):
        def timeout(*_):
            raise TimeoutError('journal verifier blocked on a foreign FIFO')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'journal'
            before = {'metadata': {key: None for key in delivery.WRITE_KEYS}}
            with delivery._journal(path, {'test_only': True}, 'a'*64, before) as owned:
                (path/'before.json').unlink()
                os.mkfifo(path/'before.json', 0o600)
                handler = signal.signal(signal.SIGALRM, timeout)
                timer = signal.setitimer(signal.ITIMER_REAL, 0.5)
                try:
                    with self.assertRaisesRegex(ValueError, 'file ownership changed'):
                        owned.verify()
                finally:
                    signal.setitimer(signal.ITIMER_REAL, *timer)
                    signal.signal(signal.SIGALRM, handler)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class NativeDeliveryRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_'+uuid.uuid4().hex)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.drop_schema)
        for book in ('one', 'two'):
            package = fixtures.CatalogImportTests.package(self, book)
            import_package(self.target, package, book_id=book, title=book, edition=2027)
        self.books = self.inputs()

    def drop_schema(self):
        self.assertTrue(self.target.schema.startswith('testcatalog_'))
        with psycopg.connect(self.target.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(self.target.schema)))

    def inputs(self):
        result = {}
        with c.connect(self.target, readonly=True) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            for bid in ('one', 'two'):
                book = project_book(db, bid)
                result[bid] = []
                for nid, in db.execute('select note_id from notes where book_id=%s order by note_id', (bid,)):
                    note = project_note(db, book, nid)
                    result[bid].append({'note_id': nid, 'id': note['id'],
                        'source_sha256': compiled_source_sha256(note),
                        'record_sha256': digest('common record:'+bid+':'+note['id']),
                        'runtime_sha256': CURRENT_RUNTIME_SHA256})
        return result

    def metadata(self):
        with c.connect(self.target, readonly=True) as db:
            return delivery._metadata(db)

    def protected_rows(self):
        with c.connect(self.target, readonly=True) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            result = {table: list(c._rows(db, table)) for table in c.TABLES if table != 'metadata'}
            result['metadata'] = list(db.execute('select key,value from metadata where not (key=any(%s)) order by key',
                                                  (list(delivery.WRITE_KEYS),)))
            return result

    def put_metadata(self, key, value):
        with c.connect(self.target) as db, db.transaction():
            c.write_lock(db)
            db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
                       (key, value))

    def apply(self, plan=None, name='journal'):
        return delivery.register_native_delivery(self.target,
            plan if plan is not None else delivery.plan_native_delivery(self.target, self.books),
            journal=self.root/name)

    def test_plan_is_readonly_and_registration_only_changes_three_metadata_rows(self):
        original = c.logical_digest(self.target)
        protected = self.protected_rows()
        plan = delivery.plan_native_delivery(self.target, self.books)
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertEqual(plan['write_keys'], list(delivery.WRITE_KEYS))
        with patch.object(versions.time, 'time', return_value=1):
            result = self.apply(plan)
        self.assertFalse(result['idempotent'])
        self.assertEqual(result['changed_books'], ['one', 'two'])
        self.assertEqual(self.protected_rows(), protected)
        after = delivery.plan_native_delivery(self.target, self.books)
        self.assertEqual(after['expected']['revision'], plan['expected']['revision'])
        for bid, old in plan['expected']['books'].items():
            new = after['expected']['books'][bid]
            self.assertEqual(result['native_versions'][bid], delivery._native_versions(after['expected'])[bid])
            for mid, model in old['models'].items():
                self.assertGreater(new['models'][mid]['mod'], max(model['mod'], model['original_mod']))
            for previous, current in zip(old['notes'], new['notes']):
                self.assertGreater(current['content_mod'], previous['original_note_mod'])
                self.assertEqual(current['source_sha256'], previous['source_sha256'])
        journal = Path(result['journal'])
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o700)
        for file in journal.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        before = json.loads((journal/'before.json').read_bytes())
        final = json.loads((journal/'after.json').read_bytes())
        self.assertEqual(before['metadata'], plan['metadata'])
        self.assertEqual(final['metadata'], self.metadata())
        self.assertEqual(hashlib.sha256((journal/'SEAL.json').read_bytes()).hexdigest(), result['journal_sha256'])

    def test_literal_and_fresh_plan_replays_are_idempotent_but_changed_record_advances(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        with patch.object(versions.time, 'time', return_value=1):
            first = self.apply(plan, 'first')
            state = c.logical_digest(self.target)
            replay = self.apply(plan, 'replay')
            self.assertTrue(replay['idempotent'])
            self.assertEqual(replay['native_versions'], first['native_versions'])
            self.assertEqual(c.logical_digest(self.target), state)
            fresh = self.apply(name='fresh')
            self.assertTrue(fresh['idempotent'])
            self.assertEqual(c.logical_digest(self.target), state)
            changed = copy.deepcopy(self.books)
            changed['one'][0]['record_sha256'] = digest('next common record')
            revised = self.apply(delivery.plan_native_delivery(self.target, changed), 'revised')
        self.assertEqual(revised['changed_books'], ['one'])
        self.assertEqual(revised['native_versions']['two'], first['native_versions']['two'])
        for nid, mod in first['native_versions']['one']['notes'].items():
            self.assertGreater(revised['native_versions']['one']['notes'][nid], mod)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.apply(plan, 'old-replay')
        self.assertFalse((self.root/'old-replay').exists())

    def test_runtime_effective_versions_are_reprojected_not_copied_from_stored_mods(self):
        self.put_metadata(versions.RUNTIME_REVISIONS, c.canonical({'one': {'floor': 0, 'revision': 7}}))
        plan = delivery.plan_native_delivery(self.target, self.books)
        with patch.object(versions.time, 'time', return_value=1):
            result = self.apply(plan)
        stored = json.loads(self.metadata()[versions.MODS])
        for row in plan['expected']['books']['one']['notes']:
            self.assertEqual(result['native_versions']['one']['notes'][row['note_id']],
                             stored[c.identity('one', row['note_id'])]+7)
            self.assertGreater(result['native_versions']['one']['notes'][row['note_id']], row['content_mod'])
        self.assertEqual(self.protected_rows()['metadata'],
            [('native.runtime-revisions.v1', '{"one":{"floor":0,"revision":7}}'), ('schema', 'unified-study-catalog.pg.v1')])

    def test_literal_replay_cas_checks_the_exact_registration_row_too(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        self.apply(plan)
        self.put_metadata(delivery.KEY, self.metadata()[delivery.KEY]+' ')
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.apply(plan, 'foreign-receipt')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertFalse((self.root/'foreign-receipt').exists())

    def test_partial_models_unknown_notes_identity_and_source_mismatch_are_rejected(self):
        variants = []
        partial = copy.deepcopy(self.books); partial['one'].pop(); variants.append(partial)
        for key, value in (('note_id', 1), ('id', 'foreign source'), ('source_sha256', 'f'*64)):
            changed = copy.deepcopy(self.books); changed['one'][0][key] = value; variants.append(changed)
        original = c.logical_digest(self.target)
        for values in variants:
            with self.subTest(values=values), self.assertRaises(ValueError):
                delivery.plan_native_delivery(self.target, values)
        self.assertEqual(c.logical_digest(self.target), original)

    def test_stale_source_revision_or_metadata_cas_writes_nothing_and_keeps_foreign_output(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        foreign = self.root/'foreign'; foreign.mkdir(); (foreign/'user.txt').write_text('retain me')
        with self.assertRaisesRegex(ValueError, 'new path'):
            self.apply(plan, 'foreign')
        self.assertEqual((foreign/'user.txt').read_text(), 'retain me')
        self.put_metadata(versions.MODS, '{} ')
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.apply(plan, 'stale-metadata')
        self.assertEqual(c.logical_digest(self.target), original)
        fresh = delivery.plan_native_delivery(self.target, self.books)
        with c.connect(self.target) as db, db.transaction():
            c.write_lock(db)
            c.event(db, 'isolated-test-revision', {'test_only': True})
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.apply(fresh, 'stale-revision')
        self.assertEqual(c.logical_digest(self.target), original)
        fresh = delivery.plan_native_delivery(self.target, self.books)
        with c.connect(self.target) as db, db.transaction():
            c.write_lock(db)
            component = db.execute("select component_id from note_fields where book_id='one' and name='SimpleDefinition' limit 1").fetchone()[0]
            changed = c.put_object(db, 'different semantic source'.encode())
            db.execute('update components set current_id=%s where id=%s', (changed, component))
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'source identity/hash changed'):
            self.apply(fresh, 'stale-source')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertFalse((self.root/'stale-source').exists())

    def test_io_or_version_failure_after_first_mutation_rolls_back_entire_transaction(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        original = c.logical_digest(self.target)
        writer = delivery._write_json
        def fail_after(path, value, **kwargs):
            if path.name == 'after.json':
                raise OSError('injected journal disk failure')
            return writer(path, value, **kwargs)
        with patch.object(delivery, '_write_json', side_effect=fail_after):
            with self.assertRaisesRegex(OSError, 'journal disk failure'):
                self.apply(plan, 'io-failure')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertTrue((self.root/'io-failure'/'before.json').is_file())
        self.assertFalse((self.root/'io-failure'/'COMMITTED.json').exists())
        with patch.object(versions, 'bump_content_mods', side_effect=RuntimeError('injected second mutation failure')):
            with self.assertRaisesRegex(RuntimeError, 'second mutation failure'):
                self.apply(plan, 'version-failure')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertFalse((self.root/'version-failure'/'COMMITTED.json').exists())

    def test_after_commit_receipt_failure_is_explicit_and_safe_literal_retry_is_idempotent(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        writer = delivery._write_json
        def fail_marker(path, value, **kwargs):
            if path.name == 'COMMITTED.json':
                raise OSError('injected receipt failure')
            return writer(path, value, **kwargs)
        with patch.object(delivery, '_write_json', side_effect=fail_marker):
            with self.assertRaises(delivery.NativeDeliveryCommittedError) as caught:
                self.apply(plan, 'receipt-failure')
        self.assertTrue(caught.exception.committed)
        self.assertTrue((self.root/'receipt-failure'/'SEAL.json').exists())
        self.assertFalse((self.root/'receipt-failure'/'COMMITTED.json').exists())
        committed = c.logical_digest(self.target)
        replay = self.apply(plan, 'confirmed-retry')
        self.assertTrue(replay['idempotent'])
        self.assertEqual(c.logical_digest(self.target), committed)

    def test_common_lock_serializes_two_concurrent_replays_without_second_bump(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.apply, plan, 'concurrent-a')
            second = pool.submit(self.apply, plan, 'concurrent-b')
            results = [first.result(timeout=30), second.result(timeout=30)]
        self.assertEqual(sorted(item['idempotent'] for item in results), [False, True])
        self.assertEqual(results[0]['native_versions'], results[1]['native_versions'])

    def test_register_and_rollback_explicitly_select_read_committed_before_locking(self):
        target = c.Target(psycopg.conninfo.make_conninfo(self.target.dsn,
            options='-c default_transaction_isolation=serializable'), self.target.schema)
        plan = delivery.plan_native_delivery(target, self.books)
        observed = []
        lock = c.write_lock
        def observe(db):
            observed.append(db.execute('show transaction_isolation').fetchone()[0])
            return lock(db)
        with patch.object(c, 'write_lock', side_effect=observe):
            result = delivery.register_native_delivery(target, plan, journal=self.root/'serializable-default')
            delivery.rollback_native_delivery(target, result['journal'], expected_seal_sha256=result['journal_sha256'],
                unpublished=True, recovery_journal=self.root/'serializable-recovery')
        self.assertEqual(observed, ['read committed', 'read committed'])

    def test_journal_replacement_or_tampering_before_seal_rolls_back_database(self):
        plan = delivery.plan_native_delivery(self.target, self.books)
        original = c.logical_digest(self.target)
        post = delivery._post_journal
        for mode in ('directory', 'bytes'):
            foreign = self.root/('foreign-'+mode)
            foreign.mkdir()
            def tamper(owned, before, after):
                if mode == 'directory':
                    owned.path.rename(self.root/'kept-directory')
                    owned.path.symlink_to(foreign, target_is_directory=True)
                else:
                    (owned.path/'before.json').write_text('foreign byte replacement')
                return post(owned, before, after)
            with self.subTest(mode=mode), patch.object(delivery, '_post_journal', side_effect=tamper):
                with self.assertRaisesRegex(ValueError, 'journal (directory ownership|bytes) changed'):
                    self.apply(plan, 'tampered-'+mode)
            self.assertEqual(c.logical_digest(self.target), original)
            self.assertEqual(list(foreign.iterdir()), [])

    def test_unpublished_rollback_restores_exact_missing_and_noncanonical_metadata(self):
        self.put_metadata(versions.MODEL_MODS, '{  }\n')
        original = c.logical_digest(self.target)
        plan = delivery.plan_native_delivery(self.target, self.books)
        result = self.apply(plan)
        with self.assertRaisesRegex(ValueError, 'unpublished=True'):
            delivery.rollback_native_delivery(self.target, result['journal'],
                expected_seal_sha256=result['journal_sha256'], recovery_journal=self.root/'disallowed')
        registered = c.logical_digest(self.target)
        writer = delivery._write_json
        def fail_after(path, value, **kwargs):
            if path.name == 'after.json':
                raise OSError('injected recovery journal failure')
            return writer(path, value, **kwargs)
        with patch.object(delivery, '_write_json', side_effect=fail_after):
            with self.assertRaisesRegex(OSError, 'recovery journal failure'):
                delivery.rollback_native_delivery(self.target, result['journal'],
                    expected_seal_sha256=result['journal_sha256'], unpublished=True,
                    recovery_journal=self.root/'failed-recovery')
        self.assertEqual(c.logical_digest(self.target), registered)
        self.assertFalse((self.root/'failed-recovery'/'COMMITTED.json').exists())
        recovered = delivery.rollback_native_delivery(self.target, result['journal'],
            expected_seal_sha256=result['journal_sha256'], unpublished=True, recovery_journal=self.root/'recovery')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertEqual(self.metadata()[versions.MODEL_MODS], '{  }\n')
        self.assertIsNone(self.metadata()[versions.MODS])
        self.assertIsNone(self.metadata()[delivery.KEY])
        self.assertTrue((Path(recovered['journal'])/'COMMITTED.json').is_file())

    def test_rollback_rejects_tampering_and_any_later_metadata_write_or_source_change(self):
        result = self.apply()
        journal = Path(result['journal'])
        after = (journal/'after.json').read_bytes()
        (journal/'after.json').write_bytes(after+b' ')
        with self.assertRaisesRegex(ValueError, 'bytes changed'):
            delivery.rollback_native_delivery(self.target, journal,
                expected_seal_sha256=result['journal_sha256'], unpublished=True, recovery_journal=self.root/'tamper')
        (journal/'after.json').write_bytes(after)
        self.put_metadata(versions.MODS, self.metadata()[versions.MODS]+' ')
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'changed after registration'):
            delivery.rollback_native_delivery(self.target, journal,
                expected_seal_sha256=result['journal_sha256'], unpublished=True, recovery_journal=self.root/'stale-undo')
        self.assertEqual(c.logical_digest(self.target), original)
        self.assertFalse((self.root/'stale-undo').exists())


if __name__ == '__main__':
    unittest.main()
