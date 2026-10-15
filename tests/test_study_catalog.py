import json
import os
import uuid
import psycopg
from psycopg import sql
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog as catalog


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class StudyCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = catalog.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_'+uuid.uuid4().hex)
        self.schemas=[self.db.schema]
        catalog.initialize(self.db)

    def tearDown(self):
        with psycopg.connect(self.db.dsn,autocommit=True) as db:
            for schema in self.schemas:db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
        self.temp.cleanup()

    def test_same_exact_word_shared_but_case_and_inflections_remain_distinct(self):
        with catalog.connect(self.db) as db, catalog.transaction(db):
            words = [catalog.ensure_word(db, text) for text in ['train', 'training', 'US', 'us', 'May', 'may']]
            self.assertEqual(catalog.ensure_word(db, 'train'), words[0])
            self.assertEqual(len(set(words)), 6)

    def test_compressed_content_is_deduplicated_and_verifies_exact_bytes(self):
        raw = ('中文\n' + 'same context ' * 1000).encode()
        with catalog.connect(self.db) as db, catalog.transaction(db):
            key = catalog.put_object(db, raw)
            self.assertEqual(catalog.put_object(db, raw), key)
            self.assertEqual(catalog.get_object(db, key), raw)
            self.assertEqual(db.execute('select count(*) from objects').fetchone()[0], 1)
            self.assertLess(db.execute('select length(data) from objects').fetchone()[0], len(raw))
        with catalog.connect(self.db) as db:
            db.execute('update objects set data=%s where id=%s', (b'corrupt', key)); db.commit()
            with self.assertRaises(ValueError): catalog.get_object(db, key)

    def test_shared_edit_changes_both_book_projections_and_retains_history(self):
        with catalog.connect(self.db) as db, catalog.transaction(db):
            word = catalog.ensure_word(db, 'support')
            key = catalog.ensure_component(db, word, 'SimpleDefinition', '支持')
            for book, note in [('2026', 1), ('2027', 2)]:
                catalog.ensure_book(db, book, book, 2026 if book == '2026' else 2027)
                db.execute('insert into notes(book_id,note_id,guid,word_id,kind,ordinal,model_id,payload_id) values(%s,%s,%s,%s,%s,%s,%s,%s)',
                           (book,note,'guid'+book,word,'word',0,1,catalog.put_json(db, {'id':note,'mod':0})))
                db.execute('insert into note_fields values(%s,%s,%s,%s,%s)', (book,note,0,'SimpleDefinition',key))
        result = catalog.edit_component(self.db, key, '支持；协助', expected='支持', reason='核对词典', backups=self.root/'backup')
        self.assertEqual(result['affected_notes'], 2)
        self.assertTrue(Path(result['backup']).is_file())
        with catalog.connect(self.db, readonly=True) as db:
            for book,note in [('2026',1),('2027',2)]:
                self.assertEqual(catalog.note_fields(db,book,note), ['支持；协助'])
            self.assertEqual(db.execute('select count(*) from component_revisions').fetchone()[0], 1)
        with self.assertRaises(ValueError):
            catalog.edit_component(self.db,key,'stale',expected='支持',reason='bad',backups=self.root/'backup')

    def test_edit_rechecks_migration_state_after_backup_before_writing(self):
        with catalog.connect(self.db) as db,catalog.transaction(db):
            key=catalog.ensure_component(db,None,'template:css','before',scope='presentation')
            db.execute('insert into sources values(%s,%s,%s,%s,%s)',('source','legacy','fixture',catalog.put_json(db,{}),'complete'))
        original_backup=catalog.backup
        def starts_migration(*args):
            saved=original_backup(*args)
            with catalog.connect(self.db) as db:db.execute("update sources set status='building'")
            return saved
        with patch.object(catalog,'backup',side_effect=starts_migration):
            with self.assertRaisesRegex(ValueError,'migration is incomplete'):
                catalog.edit_component(self.db,key,'after',expected='before',reason='reject concurrent import',backups=self.root/'backups')
        with catalog.connect(self.db,readonly=True) as db:
            self.assertEqual(catalog.get_object(db,db.execute('select current_id from components where id=%s',(key,)).fetchone()[0]),b'before')
            self.assertEqual(db.execute('select count(*) from component_revisions').fetchone()[0],0)

    def test_transaction_failure_does_not_leave_partial_content(self):
        with catalog.connect(self.db) as db:
            with self.assertRaises(RuntimeError):
                with catalog.transaction(db):
                    catalog.ensure_word(db,'temporary')
                    raise RuntimeError('injected failure')
            self.assertEqual(db.execute('select count(*) from words').fetchone()[0],0)

    def test_restore_to_new_path_preserves_logical_content_and_refuses_overwrite(self):
        with catalog.connect(self.db) as db, catalog.transaction(db): catalog.ensure_word(db,'train')
        backup=catalog.backup(self.db,self.root/'backups')
        dest=catalog.Target(self.db.dsn,'testcatalog_'+uuid.uuid4().hex);self.schemas.append(dest.schema);catalog.restore(backup,dest)
        self.assertEqual(catalog.logical_digest(self.db),catalog.logical_digest(dest))
        with self.assertRaises(FileExistsError): catalog.restore(backup,self.db)

    def test_initialization_refuses_unrelated_schema_and_output_files(self):
        name='testcatalog_'+uuid.uuid4().hex;self.schemas.append(name)
        with psycopg.connect(self.db.dsn,autocommit=True) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
            db.execute(sql.SQL('CREATE TABLE {}.original(value text)').format(sql.Identifier(name)))
        with self.assertRaises((ValueError,psycopg.Error)):catalog.initialize(catalog.Target(self.db.dsn,name))
        with psycopg.connect(self.db.dsn,autocommit=True) as db:
            self.assertIsNotNone(db.execute('select to_regclass(%s)',(name+'.original',)).fetchone()[0])
        original=self.root/'original.apkg';original.write_bytes(b'source')
        with self.assertRaises(ValueError):catalog.guard_new_output(original,[original])
        self.assertEqual(original.read_bytes(),b'source')

    def test_read_only_connection_cannot_change_state(self):
        with catalog.connect(self.db,readonly=True) as db:
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):catalog.ensure_word(db,'invalid')

    def test_failed_restore_rolls_back_new_schema_atomically(self):
        import gzip
        saved=catalog.backup(self.db,self.root/'backup')
        raw=gzip.decompress(saved.read_bytes()).replace(b'rows_sha256',b'wrong_digest')
        saved.write_bytes(gzip.compress(raw))
        dest=catalog.Target(self.db.dsn,'testcatalog_'+uuid.uuid4().hex)
        with self.assertRaises(ValueError):catalog.restore(saved,dest)
        with psycopg.connect(self.db.dsn,autocommit=True) as db:
            self.assertIsNone(db.execute('select 1 from pg_namespace where nspname=%s',(dest.schema,)).fetchone())

    def test_book_id_cannot_be_reused_for_another_year(self):
        with catalog.connect(self.db) as db,catalog.transaction(db):
            catalog.ensure_book(db,'redbook2027','红宝书',2027)
            with self.assertRaises(ValueError):catalog.ensure_book(db,'redbook2027','红宝书',2026)

    def test_schema_name_is_not_executable_sql(self):
        with self.assertRaises(ValueError):catalog.Target(self.db.dsn,'bad; DROP SCHEMA public')



if __name__ == '__main__': unittest.main()
