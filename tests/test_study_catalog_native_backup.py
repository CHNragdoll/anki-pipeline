"""Real PG17 dump/restore in a Unix-only, private disposable instance.

No connection to the normal catalog or any existing learning store is made.
"""
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import psycopg

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_native_backup as native
from anki_pipeline import study_progress_pg as progress


class NativeConnectionTests(unittest.TestCase):
    def test_libpq_environment_defaults_are_not_discarded(self):
        with patch.dict(os.environ, {'PGPORT': '65431', 'PGHOST': '/fixture/private/socket',
                                    'PGPASSWORD': 'env-password', 'PGSERVICE': 'fixture-service'}):
            connection, environment = native._connection(c.Target('dbname=fixture user=fixture'))
        self.assertEqual(environment['PGPORT'], '65431')
        self.assertEqual(environment['PGHOST'], '/fixture/private/socket')
        self.assertEqual(environment['PGSERVICE'], 'fixture-service')
        self.assertEqual(environment['PGPASSWORD'], 'env-password')
        self.assertNotIn('env-password', connection)

    def test_sslpassword_is_rejected_without_echoing_its_value(self):
        secret = 'ssl-secret-canary'
        with self.assertRaises(native.NativeBackupError) as error:
            native._connection(c.Target('dbname=fixture sslpassword=' + secret))
        self.assertNotIn(secret, str(error.exception))

    def test_service_resolved_sslpassword_also_cannot_enter_arguments(self):
        secret = 'service-ssl-secret-canary'
        info = SimpleNamespace(get_parameters=lambda: {'sslpassword': secret}, host='/private/socket',
                               port=5432, dbname='fixture', user='fixture', password='unused')
        with self.assertRaises(native.NativeBackupError) as error:
            native._connection(c.Target('dbname=fixture'), SimpleNamespace(info=info))
        self.assertNotIn(secret, str(error.exception))

    def test_current_hostaddr_replaces_multi_host_service_values(self):
        for hostaddr, host in (('192.0.2.22', 'host-b'), ('', '/private/socket')):
            info = SimpleNamespace(get_parameters=lambda: {'host': 'host-a,host-b',
                                   'hostaddr': '192.0.2.11,192.0.2.22', 'service': 'mutable-service'},
                                   host=host, hostaddr=hostaddr, port=65432, dbname='fixture',
                                   user='fixture', password='private-effective-password')
            with patch.dict(os.environ, {'PGSERVICE': 'mutable-service', 'PGSERVICEFILE': '/mutable-service.conf',
                                        'PGHOSTADDR': '192.0.2.11,192.0.2.22'}):
                connection, environment = native._connection(c.Target('dbname=fixture'), SimpleNamespace(info=info))
            actual = psycopg.conninfo.conninfo_to_dict(connection)
            self.assertEqual(actual['host'], host)
            self.assertEqual(actual['port'], '65432')
            self.assertEqual(actual.get('hostaddr', ''), hostaddr)
            self.assertNotIn('service', actual)
            self.assertNotIn('PGSERVICE', environment)
            self.assertNotIn('PGSERVICEFILE', environment)
            if not hostaddr:
                self.assertNotIn('PGHOSTADDR', environment)
            self.assertNotIn('private-effective-password', connection)


@unittest.skipUnless((native.DEFAULT_BIN / 'pg_dump').is_file(), 'requires local PostgreSQL 17 tools')
class NativeBackupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='study-native-tests-', dir='/tmp')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        cls.cluster = native.PrivateRestoreCluster(cls.root / 'instance')
        cls.addClassCleanup(cls.cluster.stop)
        cls.cluster.start()

    def setUp(self):
        self.source = self.cluster.create_database()
        c.initialize(self.source)
        self.raw = bytes(range(256)) + b'\x00\xff\x00' + '完整字节\n'.encode()
        with c.connect(self.source) as db, db.transaction():
            progress.initialize_connection(db)
            self.object_id = c.put_object(db, self.raw)
            db.execute('insert into metadata values(%s,%s)', ('unicode-fixture', ' 原文\n"中"\\😀 '))
            db.execute("insert into words values('word-a','en','Alpha'),('word-b','en','Beta')")
            db.execute("insert into study_progress_cards values('book','card',17,%s,NULL)", (' { "原始": true }\n',))
            db.execute("insert into study_progress_sequences values('reviews',103)")
            db.execute("select setval('events_id_seq',501,true)")
        self.destination = self.root / ('bundle-' + self.source.dsn.split('dbname=')[1].split()[0])

    def save(self, **options):
        return native.backup(self.source, self.destination, **options)

    def test_real_custom_and_directory_archives_restore_every_column(self):
        for format in ('custom', 'directory'):
            with self.subTest(format=format):
                saved = native.backup(self.source, self.destination.with_name(self.destination.name + format),
                                      format=format, jobs=2 if format == 'directory' else 1)
                manifest = native.read_manifest(saved)
                self.assertEqual(manifest['descriptor']['schema'], c._BACKUP_V2)
                self.assertEqual(len(manifest['proof']['tables']), 34)
                self.assertEqual(manifest['proof']['algorithm'], native.ALGORITHM)
                restored, report = native.restore_and_verify(saved, self.cluster)
                self.assertTrue(report['complete'])
                self.assertEqual(report['identity_sequences']['events']['last_value'], 501)
                self.assertEqual(report['identity_sequences']['events']['next_id'], 502)
                with c.connect(restored, readonly=True) as db:
                    self.assertEqual(c.get_object(db, self.object_id), self.raw)
                    self.assertEqual(db.execute('select seq from study_progress_sequences').fetchone(), (103,))
                    self.assertEqual(db.execute('select value from metadata where key=%s', ('unicode-fixture',)).fetchone(),
                                     (' 原文\n"中"\\😀 ',))
                self.assertTrue(all(v['bytes'] > 0 for v in manifest['proof']['tables'].values()))
                self.assertTrue(all(type(v['rows']) is int for v in manifest['proof']['tables'].values()))

    def test_v1_catalog_without_learning_tables_remains_supported(self):
        selected = self.cluster.create_database()
        c.initialize(selected)
        saved = native.backup(selected, self.destination)
        manifest = native.read_manifest(saved)
        self.assertEqual(manifest['descriptor']['schema'], c._BACKUP_V1)
        self.assertEqual(len(manifest['proof']['tables']), 24)
        _, report = native.restore_and_verify(saved, self.cluster)
        self.assertTrue(report['complete'])

    def test_source_change_missing_row_and_bytea_change_are_not_confirmed(self):
        saved = self.save()
        with c.connect(self.source) as db:
            db.execute('update study_progress_sequences set seq=104')
        with self.assertRaisesRegex(native.VerificationUnconfirmed, 'study_progress_sequences'):
            native.verify_restored(saved, self.source)
        restored, _ = native.restore_and_verify(saved, self.cluster)
        with c.connect(restored) as db:
            db.execute("delete from words where id='word-a'")
        with self.assertRaisesRegex(native.VerificationUnconfirmed, 'words'):
            native.verify_restored(saved, restored)
        restored, _ = native.restore_and_verify(saved, self.cluster)
        with c.connect(restored) as db:
            db.execute('update objects set data=%s where id=%s', (b'changed\x00bytes', self.object_id))
        with self.assertRaisesRegex(native.VerificationUnconfirmed, 'objects'):
            native.verify_restored(saved, restored)

    def test_equal_rows_in_different_scan_order_are_only_unconfirmed(self):
        saved = self.save()
        restored, _ = native.restore_and_verify(saved, self.cluster)
        with c.connect(restored) as db:
            rows = db.execute('select * from words order by id desc').fetchall()
            db.execute('delete from words')
            for row in rows:
                db.execute('insert into words values(%s,%s,%s)', row)
        with c.connect(self.source, readonly=True) as source, c.connect(restored, readonly=True) as actual:
            self.assertEqual(source.execute('select * from words order by id').fetchall(),
                             actual.execute('select * from words order by id').fetchall())
        with self.assertRaisesRegex(native.VerificationUnconfirmed, 'scan-order'):
            native.verify_restored(saved, restored)

    def test_tampered_archive_and_manifest_are_rejected_before_restore(self):
        saved = self.save()
        data = saved.path / 'archive.dump'
        with data.open('ab') as output:
            output.write(b'foreign mutation')
        with self.assertRaisesRegex(native.NativeBackupError, 'sealed manifest'):
            native.restore_and_verify(saved, self.cluster)
        with self.assertRaisesRegex(native.NativeBackupError, 'external pin'):
            native.read_manifest(native.NativeBackup(saved.path, '0' * 64))

    def test_existing_output_and_arbitrary_restore_dsn_are_never_modified(self):
        self.destination.mkdir()
        existing = self.destination / 'existing'
        existing.write_bytes(b'unrelated')
        with self.assertRaises(FileExistsError):
            self.save()
        self.assertEqual(existing.read_bytes(), b'unrelated')
        with self.assertRaises(ValueError):
            native.restore_and_verify(None, c.DEFAULT_DSN)

    def test_unknown_table_is_rejected_without_publishing_output(self):
        with c.connect(self.source) as db:
            db.execute('create table future_unknown(value text)')
        with self.assertRaisesRegex(ValueError, 'unexpected tables'):
            self.save()
        self.assertFalse(self.destination.exists())

    def test_private_creation_with_public_parent_and_permissive_umask(self):
        parent = self.root / 'public'
        parent.mkdir(mode=0o755)
        os.chmod(parent, 0o755)
        before = os.umask(0o022)
        try:
            saved = native.backup(self.source, parent / 'private-bundle')
        finally:
            os.umask(before)
        self.assertEqual(saved.path.stat().st_mode & 0o777, 0o700)
        for path in saved.path.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)

    def test_dump_failure_cleans_only_its_recorded_files(self):
        with patch.object(native, '_run', side_effect=native.NativeBackupError('fixture failure')):
            with self.assertRaisesRegex(native.NativeBackupError, 'fixture failure'):
                self.save()
        self.assertFalse(self.destination.exists())

    def test_concurrent_foreign_archive_is_preserved_and_not_published(self):
        original = native._fingerprints
        def replace(db, descriptor):
            selected = self.destination / 'archive.dump'
            selected.unlink()
            selected.write_bytes(b'independent foreign file')
            return original(db, descriptor)
        with patch.object(native, '_fingerprints', side_effect=replace):
            with self.assertRaisesRegex(native.NativeBackupError, 'replaced'):
                self.save()
        self.assertEqual((self.destination / 'archive.dump').read_bytes(), b'independent foreign file')
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_instance_is_unix_only_and_reports_a_scoped_stop_command(self):
        with c.connect(self.source, readonly=True) as db:
            self.assertEqual(db.execute('show listen_addresses').fetchone(), ('',))
            self.assertEqual(native._server(db)['system_identifier'], self.cluster.system_identifier)
        self.assertEqual(self.cluster.stop_command[-4:], ['-m', 'fast', '-w', 'stop'])
        self.assertIn(str(self.cluster.data), self.cluster.stop_command)

    def test_password_is_never_in_tool_arguments_or_manifest(self):
        secret = 'fixture-canary-password-no-output'
        selected = c.Target(self.source.dsn + ' password=' + secret, self.source.schema)
        original = native._run
        calls = []
        def inspect(arguments, **options):
            self.assertNotIn(secret, repr(arguments))
            calls.append(arguments[0])
            return original(arguments, **options)
        with patch.object(native, '_run', side_effect=inspect):
            saved = native.backup(selected, self.destination)
        self.assertTrue(calls)
        self.assertNotIn(secret, (saved.path / 'manifest.json').read_text())

    def test_effective_target_can_inherit_its_private_socket_from_libpq_environment(self):
        options = psycopg.conninfo.conninfo_to_dict(self.source.dsn)
        selected = c.Target(psycopg.conninfo.make_conninfo(dbname=options['dbname'], user=options['user']))
        with patch.dict(os.environ, {'PGHOST': str(self.cluster.socket), 'PGPORT': '5432',
                                    'PGPASSWORD': 'fixture-env-password'}):
            saved = native.backup(selected, self.destination)
        _, report = native.restore_and_verify(saved, self.cluster)
        self.assertTrue(report['complete'])

    def test_dump_and_source_proof_share_one_snapshot_despite_concurrent_update(self):
        original = native._fingerprints
        def changed_after_dump(db, descriptor):
            with c.connect(self.source) as writer:
                writer.execute('update metadata set value=%s where key=%s', ('new later value', 'unicode-fixture'))
            return original(db, descriptor)
        with patch.object(native, '_fingerprints', side_effect=changed_after_dump):
            saved = self.save()
        restored, report = native.restore_and_verify(saved, self.cluster)
        self.assertTrue(report['complete'])
        with c.connect(restored, readonly=True) as db:
            self.assertEqual(db.execute('select value from metadata where key=%s', ('unicode-fixture',)).fetchone(),
                             (' 原文\n"中"\\😀 ',))
        with self.assertRaisesRegex(native.VerificationUnconfirmed, 'metadata'):
            native.verify_restored(saved, self.source)

    def test_operator_pg_ctl_stop_command_stops_only_the_private_child(self):
        with native.PrivateRestoreCluster(self.destination) as instance:
            result = subprocess.run(instance.stop_command, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0)
            instance.process.wait(timeout=5)
            self.assertIsNotNone(instance.process.poll())
        self.assertIsNone(self.cluster.process.poll())

    def test_symlinked_media_or_extra_file_cannot_enter_the_archive(self):
        saved = self.save()
        outside = self.root / 'foreign-file'
        outside.write_bytes(b'not part of the archive')
        (saved.path / 'unexpected').symlink_to(outside)
        with self.assertRaises((native.NativeBackupError, OSError)):
            native.read_manifest(saved)


if __name__ == '__main__':
    unittest.main()
