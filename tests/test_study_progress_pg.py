"""Real PostgreSQL storage contracts, exclusively in random testcatalog schemas."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
from itertools import permutations
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_progress as progress
from anki_pipeline import study_progress_pg as pg
from anki_pipeline.study_progress_storage import StorageError
from anki_pipeline.study_progress_snapshot import canonical_rows as sqlite_rows
from tests.test_study_progress import Clock, catalog as book_catalog
from tests.test_study_progress_snapshot import scheduler
from tests.test_study_progress_http import FIXTURE, request, serve


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class ProgressPostgresTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.targets = []
        self.target = self.new_target()
        self.storage = pg.PgStudyStorage(self.target, backups=self.root/'backups')
        self.storage.initialize()
        self.clock = Clock()
        self.books = book_catalog()
        self.store = progress.StudyStore(None, self.books, now=self.clock, storage=self.storage)
        self.store.initialize_catalog()

    def new_target(self):
        target = catalog.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_'+uuid.uuid4().hex)
        self.targets.append(target)
        self.addCleanup(self.drop_target, target)
        catalog.initialize(target)
        return target

    @staticmethod
    def drop_target(target):
        if not target.schema.startswith('testcatalog_'):
            raise AssertionError('not an isolated test schema')
        with psycopg.connect(target.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(target.schema)))

    def state(self):
        with catalog.connect(self.target, readonly=True) as db, db.transaction():
            return list(pg.canonical_rows(db))

    def call(self, method, path, body=None, **query):
        return self.store.dispatch(method, '/api/study/'+path, query, body)

    def answer_body(self, request_id='answer', rating=3):
        card = self.call('GET','session',book='redbook')['card']
        return {'book':'redbook','deck':'all','cardId':card['id'],'revision':card['revision'],
                'rating':rating,'requestId':request_id,'durationMs':1234}

    def backup_digest(self, path):
        with gzip.open(path, 'rb') as stream:
            header = json.loads(stream.readline())
            self.assertEqual(header['schema'], 'study-progress-postgresql-snapshot.v1')
            self.assertEqual(header['storage'], pg.DESCRIPTOR)
            self.assertEqual(header['columns'], {name:list(columns) for name,columns in pg.COLUMNS.items()})
            self.assertEqual(header['source_schema'], self.target.schema)
            lines = list(stream)
        footer = json.loads(lines.pop())
        digest = hashlib.sha256(b''.join(lines)).hexdigest()
        self.assertEqual(footer['rows_sha256'], digest)
        self.assertEqual(sum(footer['counts'].values()),len(lines))
        return digest

    def test_constructor_does_not_create_schema_or_seed_rows(self):
        target = self.new_target()
        storage = pg.PgStudyStorage(target, backups=self.root/'other-backups')
        with self.assertRaises(StorageError):
            progress.StudyStore(None,self.books,now=self.clock,storage=storage)
        with catalog.connect(target, readonly=True) as db:
            self.assertIsNone(db.execute('select value from metadata where key=%s',(pg.METADATA_KEY,)).fetchone())
        storage.initialize()
        store = progress.StudyStore(None,self.books,now=self.clock,storage=storage)
        with catalog.connect(target, readonly=True) as db:
            self.assertEqual(db.execute('select count(*) from study_progress_cards').fetchone()[0],0)
        store.initialize_catalog()
        self.assertEqual(len(store.dispatch('GET','/api/study/backup',{},None)['books']),2)
        before = self.state()
        self.store.initialize_catalog()
        self.assertEqual(before,self.state())

    def test_initializer_obeys_outer_transaction_and_rejects_partial_tables(self):
        target = self.new_target()
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with catalog.connect(target) as db, db.transaction():
                pg.initialize_connection(db)
                raise RuntimeError('rollback')
        with catalog.connect(target) as db:
            self.assertIsNone(db.execute('select value from metadata where key=%s',(pg.METADATA_KEY,)).fetchone())
            with self.assertRaises(StorageError):
                pg.initialize_connection(db)
            db.execute('create table study_progress_cards(bogus text)')
        storage = pg.PgStudyStorage(target, backups=self.root/'unused')
        with self.assertRaises(StorageError):
            storage.initialize()
        with catalog.connect(target) as db:
            self.assertIsNone(db.execute('select value from metadata where key=%s',(pg.METADATA_KEY,)).fetchone())

    def test_schema_extra_column_type_or_foreign_key_drift_is_rejected(self):
        statements = (
            'alter table study_progress_cards add column unexpected text',
            'alter table study_progress_cards alter column revision type text',
            'alter table study_progress_requests drop constraint study_progress_requests_review_id_fkey',
            'alter table study_progress_sequences drop constraint study_progress_sequences_seq_check',
        )
        for statement in statements:
            with self.subTest(statement=statement), catalog.connect(self.target) as db:
                with self.assertRaises(RuntimeError):
                    with db.transaction():
                        db.execute(statement)
                        with self.assertRaises(StorageError):
                            pg.validate_connection(db)
                        raise RuntimeError('rollback fixture drift')
        self.storage.validate()

    def test_unknown_sql_and_read_transaction_writes_fail_closed(self):
        before = self.state()
        connection = self.storage.connect()
        try:
            connection.execute('BEGIN')
            with self.assertRaises(StorageError):
                connection.execute('SELECT 42')
            with self.assertRaises(StorageError):
                connection.execute('UPDATE cards SET revision=?',(99,))
            connection.rollback()
        finally:
            connection.close()
        self.assertEqual(before,self.state())

    def test_all_legacy_http_responses_and_rows_match_with_pg_backup_format(self):
        fixture = json.loads(FIXTURE.read_text())
        self.assertEqual(hashlib.sha256(b''.join(self.state())).hexdigest(),fixture['initial_state_sha256'])
        with patch.object(progress.uuid,'uuid4',return_value=uuid.UUID(fixture['uuid4'])), serve(self.store) as port:
            for step in fixture['requests']:
                with self.subTest(request=step['name']):
                    self.clock.value = self.clock.value.fromisoformat(step['at'])
                    status, headers, payload = request(port,step['method'],step['path'],step['body'])
                    expected = json.loads(step['response_text'])
                    expected_text = step['response_text']
                    expected_headers = dict(step['headers'])
                    if step['backup_before_sha256'] is not None:
                        old_name = expected['automaticBackup']
                        expected['automaticBackup'] = old_name.removesuffix('.sqlite3')+'.pg.jsonl.gz'
                        self.assertEqual(expected_text.count(old_name),1)
                        expected_text = expected_text.replace(old_name,expected['automaticBackup'],1)
                    expected_headers['Content-Length'] = str(len(expected_text.encode()))
                    self.assertEqual(status,step['status'])
                    self.assertEqual(headers,expected_headers)
                    self.assertEqual(payload.decode(),expected_text)
                    self.assertEqual(hashlib.sha256(b''.join(self.state())).hexdigest(),step['state_sha256'])
                    if step['backup_before_sha256'] is not None:
                        self.assertEqual(self.backup_digest(self.storage.backups/expected['automaticBackup']),
                                         step['backup_before_sha256'])
        self.assertEqual([json.loads(line) for line in self.state()],fixture['final_state'])

    def test_parallel_retries_and_distinct_clicks_serialize_before_queue_read(self):
        body = self.answer_body()
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _:self.call('POST','answer',body),range(4)))
        self.assertTrue(all(value==results[0] for value in results))
        self.assertEqual(self.call('GET','stats',book='redbook')['summary']['totalReviews'],1)
        body = self.answer_body('distinct')

        def click(number):
            try:
                self.call('POST','answer',dict(body,requestId=f'click-{number}'))
                return 200
            except progress.StudyError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=4) as workers:
            statuses = list(workers.map(click,range(4)))
        self.assertEqual(sorted(statuses),[200,409,409,409])
        self.assertEqual(self.call('GET','stats',book='redbook')['summary']['totalReviews'],2)

    def test_answer_failure_rolls_back_card_history_dedupe_revision_and_sequence(self):
        before = self.state()
        body = self.answer_body()
        with catalog.connect(self.target) as db:
            db.execute("create function fail_request() returns trigger language plpgsql as $$ "
                       "begin raise exception 'fixture failure'; end $$")
            db.execute('create trigger fail_request before insert on study_progress_requests '
                       'for each row execute function fail_request()')
        with self.assertRaises(progress.StudyError) as caught:
            self.call('POST','answer',body)
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(self.state(),before)
        with catalog.connect(self.target) as db:
            db.execute('drop trigger fail_request on study_progress_requests')
        self.call('POST','answer',body)
        with catalog.connect(self.target,readonly=True) as db:
            self.assertEqual(db.execute('select id from study_progress_reviews').fetchall(),[(1,)])
            self.assertEqual(db.execute('select seq from study_progress_sequences').fetchall(),[(1,)])

    def test_restore_failure_preserves_pg_snapshot_and_all_original_rows(self):
        self.call('POST','answer',self.answer_body())
        snapshot = self.call('GET','backup')
        before = self.state()
        with catalog.connect(self.target) as db:
            db.execute("create function fail_card() returns trigger language plpgsql as $$ "
                       "begin raise exception 'fixture restore failure'; end $$")
            db.execute('create trigger fail_card before insert on study_progress_cards '
                       'for each row execute function fail_card()')
        with self.assertRaises(progress.StudyError) as caught:
            self.call('POST','restore',{'backup':snapshot})
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(self.state(),before)
        backups = list(self.storage.backups.iterdir())
        self.assertEqual(len(backups),1)
        self.assertEqual(self.backup_digest(backups[0]),hashlib.sha256(b''.join(before)).hexdigest())

    def test_sequence_high_watermark_survives_delete_and_exhaustion_rolls_back(self):
        self.call('POST','answer',self.answer_body())
        with catalog.connect(self.target) as db:
            db.execute("update study_progress_sequences set seq=99 where name='reviews'")
            db.execute('delete from study_progress_requests')
            db.execute('delete from study_progress_reviews')
            db.execute('update study_progress_undo set review_id=null')
        self.call('POST','answer',self.answer_body('second'))
        with catalog.connect(self.target) as db:
            self.assertEqual(db.execute('select id from study_progress_reviews order by id').fetchall(),[(100,)])
            db.execute("update study_progress_sequences set seq=%s where name='reviews'",(2**53-1,))
        before = self.state()
        with self.assertRaises(progress.StudyError) as caught:
            self.call('POST','answer',self.answer_body('ceiling'))
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(before,self.state())
        with catalog.connect(self.target) as db:
            db.execute("update study_progress_sequences set seq=100 where name='reviews'")
            db.execute("update study_progress_metadata set value=%s where key='revision'",(2**53-1,))
        before = self.state()
        with self.assertRaises(progress.StudyError) as caught:
            self.call('POST','answer',self.answer_body('global-ceiling'))
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(before,self.state())

    def test_connection_failure_keeps_the_same_business_error_and_no_state_change(self):
        before = self.state()
        with patch.object(catalog,'_open_connection',side_effect=psycopg.OperationalError('fixture unavailable')):
            with self.assertRaises(progress.StudyError) as caught:
                self.call('GET','session',book='redbook')
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(caught.exception.message,'学习数据库操作失败；本次变更已回滚')
        self.assertEqual(before,self.state())

    def test_inactive_raw_rows_nulls_unicode_and_json_text_survive_initialization(self):
        raw = scheduler('旧书🧪','old-card')
        preferences = json.dumps(progress.DEFAULT_PREFERENCES,ensure_ascii=False,indent=2)
        with catalog.connect(self.target) as db, db.transaction():
            pg.write_lock(db)
            db.execute('insert into study_progress_settings values(%s,20,200,.9)',('旧书🧪',))
            db.execute('insert into study_progress_cards values(%s,%s,23,%s,null)',('旧书🧪','old-card',raw))
            db.execute('insert into study_progress_reviews values(7,%s,%s,%s,%s,3,0,%s,1,null,%s,null,22)',
                       ('旧书🧪','old-card','2026-10-04T02:00:00+00:00','2026-10-04','new',raw))
            db.execute('insert into study_progress_undo values(%s,null)',('旧书🧪',))
            db.execute('insert into study_progress_requests values(%s,%s,7)',('旧请求','a'*64))
            db.execute('insert into study_progress_card_actions values(%s,%s)',('旧控制','b'*64))
            db.execute('insert into study_progress_card_controls values(%s,%s,6,1,null,%s)',
                       ('旧书🧪','old-card','原文 e\u0301 与 é\n🧪'))
            db.execute('insert into study_progress_preferences values(1,%s)',(preferences,))
            db.execute("insert into study_progress_sequences values('reviews',99)")
            db.execute("update study_progress_metadata set value=23 where key='revision'")
        before = self.state()
        self.store.initialize_catalog()
        self.assertEqual(before,self.state())
        decoded = [json.loads(line) for line in before]
        card = next(values for name,values in decoded if name=='cards' and values[0]==['text','旧书🧪'])
        self.assertEqual(card[3:], [['text',raw],['null']])
        preference = next(values for name,values in decoded if name=='preferences')
        self.assertEqual(preference[1],['text',preferences])
        self.assertEqual([book['id'] for book in self.call('GET','backup')['books']],['liu','redbook'])

    def test_read_view_is_repeatable_and_database_enforces_read_only(self):
        reader = self.storage.connect()
        try:
            reader.execute('BEGIN')
            before = reader.execute('SELECT revision FROM cards WHERE book=? AND card_id=?',
                                    ('redbook','redbook-1')).fetchone()[0]
            self.call('POST','answer',self.answer_body())
            self.assertEqual(reader.execute('SELECT revision FROM cards WHERE book=? AND card_id=?',
                                           ('redbook','redbook-1')).fetchone()[0],before)
            self.assertEqual(reader.raw.execute('show transaction_isolation').fetchone()[0],'repeatable read')
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                reader.raw.execute('update study_progress_metadata set value=value+1')
            reader.rollback()
        finally:
            reader.close()

    def test_preferences_and_two_books_match_a_valid_sqlite_serial_order(self):
        actions = []
        for book in ('liu','redbook'):
            card = self.call('GET','session',book=book)['card']
            actions.append(('answer',{'book':book,'deck':'all','cardId':card['id'],
                'revision':card['revision'],'rating':3,'requestId':'score-'+book,'durationMs':1234}))
        actions.append(('preferences',{'preferences':dict(progress.DEFAULT_PREFERENCES,learningSteps='2,20')}))

        def perform(store, index):
            endpoint, body = actions[index]
            try:
                store.dispatch('POST','/api/study/'+endpoint,{},body)
                return 200
            except progress.StudyError as error:
                return error.status

        expected = []
        for number, order in enumerate(permutations(range(3))):
            path = self.root/f'serial-{number}.sqlite3'
            store = progress.StudyStore(path,self.books,now=self.clock)
            statuses = [None]*3
            for index in order:
                statuses[index] = perform(store,index)
            expected.append((statuses,list(sqlite_rows(path))))
        barrier = threading.Barrier(3)

        def concurrent(index):
            barrier.wait(timeout=5)
            return perform(self.store,index)

        with ThreadPoolExecutor(max_workers=3) as workers:
            statuses = list(workers.map(concurrent,range(3)))
        self.assertIn((statuses,self.state()),expected)

    def test_bulk_unbury_revision_order_matches_sqlite_for_reverse_inserted_controls(self):
        path = self.root/'unbury.sqlite3'
        sqlite_store = progress.StudyStore(path,self.books,now=self.clock)

        def perform(store):
            for card_id in ('redbook-2','redbook-1'):
                card = store.dispatch('GET','/api/study/card',{'book':'redbook','cardId':card_id},None)
                store.dispatch('POST','/api/study/card-action',{},
                    {'book':'redbook','deck':'all','cardId':card_id,'revision':card['revision'],
                     'action':'bury','requestId':'bury-'+card_id})
            return store.dispatch('POST','/api/study/card-action',{},
                                  {'book':'redbook','deck':'all','action':'unburyAll','requestId':'all'})

        self.assertEqual(perform(self.store),perform(sqlite_store))
        self.assertEqual(self.state(),list(sqlite_rows(path)))

    def test_pg_backup_failure_prevents_restore_without_using_sqlite(self):
        self.call('POST','answer',self.answer_body())
        snapshot = self.call('GET','backup')
        before = self.state()
        with patch.object(progress.sqlite3,'connect',side_effect=AssertionError('PG used SQLite backup')), \
             patch.object(pg.os,'fsync',side_effect=OSError('private backup write failure')):
            with self.assertRaises(progress.StudyError) as caught:
                self.call('POST','restore',{'backup':snapshot})
        self.assertEqual(caught.exception.status,500)
        self.assertEqual(before,self.state())
        self.assertEqual(list(self.storage.backups.iterdir()),[])

    def backup_paths(self):
        fixed = uuid.UUID('12345678-1234-4234-8234-123456789012')
        basename = f"progress-before-restore-{self.clock().strftime('%Y%m%dT%H%M%S%fZ')}-12345678.pg.jsonl.gz"
        return fixed, self.storage.backups/('.'+basename+'.tmp'), self.storage.backups/basename

    def test_backup_is_private_at_creation_in_existing_shared_directory(self):
        self.storage.backups.mkdir(mode=0o755)
        self.storage.backups.chmod(0o755)
        observed = []
        original = os.fchmod

        def record(descriptor, mode):
            observed.append(os.fstat(descriptor).st_mode & 0o777)
            return original(descriptor,mode)

        previous_umask = os.umask(0o022)
        try:
            with patch.object(pg.os,'fchmod',side_effect=record):
                result = self.call('POST','restore',{'backup':self.call('GET','backup')})
        finally:
            os.umask(previous_umask)
        self.assertTrue(observed)
        self.assertEqual(observed,[0o600])
        self.assertEqual((self.storage.backups/result['automaticBackup']).stat().st_mode & 0o777,0o600)

    def test_preexisting_backup_temporary_is_never_removed(self):
        fixed, temporary, destination = self.backup_paths()
        self.storage.backups.mkdir()
        temporary.write_bytes(b'foreign preexisting file')
        before_file = temporary.stat()
        before = self.state()
        with patch.object(pg.uuid,'uuid4',return_value=fixed):
            with self.assertRaises(progress.StudyError) as caught:
                self.call('POST','restore',{'backup':self.call('GET','backup')})
        self.assertEqual(caught.exception.status,500)
        self.assertIsInstance(caught.exception.__cause__,FileExistsError)
        self.assertTrue(temporary.exists(),'foreign temporary was deleted after exclusive create failed')
        self.assertEqual(temporary.read_bytes(),b'foreign preexisting file')
        fields = ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
        self.assertEqual(tuple(getattr(temporary.stat(),name) for name in fields),
                         tuple(getattr(before_file,name) for name in fields))
        self.assertFalse(destination.exists())
        self.assertEqual(before,self.state())

    def test_backup_link_substitution_or_mode_drift_aborts_restore(self):
        fixed, temporary, destination = self.backup_paths()
        self.storage.backups.mkdir()
        original = os.link
        for change in ('temporary','destination','symlink','mode'):
            with self.subTest(change=change):
                for path in self.storage.backups.iterdir():
                    path.unlink()
                foreign = self.root/'foreign-backup'
                foreign.write_bytes(b'foreign replacement')
                foreign.chmod(0o600)
                before = self.state()

                def replace(source, target, *args, **kwargs):
                    if change == 'temporary':
                        os.replace(foreign,source)
                    elif change == 'symlink':
                        Path(source).unlink()
                        Path(source).symlink_to(foreign)
                    result = original(source,target,*args,**kwargs)
                    if change == 'destination':
                        os.replace(foreign,target)
                    elif change == 'mode':
                        Path(target).chmod(0o644)
                    return result

                with patch.object(pg.uuid,'uuid4',return_value=fixed), patch.object(pg.os,'link',side_effect=replace):
                    with self.assertRaises(progress.StudyError) as caught:
                        self.call('POST','restore',{'backup':self.call('GET','backup')})
                self.assertEqual(caught.exception.status,500)
                self.assertEqual(before,self.state())
                if change in ('temporary','destination'):
                    self.assertEqual(destination.read_bytes(),b'foreign replacement')
                if change == 'temporary':
                    self.assertEqual(temporary.read_bytes(),b'foreign replacement')
                if change == 'symlink':
                    self.assertTrue(temporary.is_symlink())
                    self.assertEqual(foreign.read_bytes(),b'foreign replacement')
                if change == 'mode':
                    self.assertEqual(destination.stat().st_mode & 0o777,0o644)

    def test_directory_fsync_error_preserves_foreign_tmp_and_completed_backup(self):
        fixed, temporary, destination = self.backup_paths()
        original = os.fsync
        failure = OSError('injected directory fsync failure')
        calls = []
        before = self.state()

        def fsync(descriptor):
            calls.append(descriptor)
            if len(calls) == 2:
                temporary.write_bytes(b'foreign after publish')
                raise failure
            return original(descriptor)

        with patch.object(pg.uuid,'uuid4',return_value=fixed), patch.object(pg.os,'fsync',side_effect=fsync):
            with self.assertRaises(progress.StudyError) as caught:
                self.call('POST','restore',{'backup':self.call('GET','backup')})
        self.assertIs(caught.exception.__cause__,failure)
        self.assertEqual(before,self.state())
        self.assertEqual(temporary.read_bytes(),b'foreign after publish')
        self.assertEqual(self.backup_digest(destination),hashlib.sha256(b''.join(before)).hexdigest())


if __name__ == '__main__':
    unittest.main()
