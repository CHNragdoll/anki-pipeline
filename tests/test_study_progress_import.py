"""Lossless migration contracts in owned fixtures and random PostgreSQL schemas."""
from contextlib import closing, contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_progress_migration as migration
from anki_pipeline import study_progress_pg as pg
from anki_pipeline import study_progress_snapshot as snapshot
from tests.test_study_progress_snapshot import make_database


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class ProgressImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target = catalog.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_'+uuid.uuid4().hex)
        self.addCleanup(self.drop_target)
        catalog.initialize(self.target)
        self.source = self.root/'source.sqlite3'
        make_database(self.source)
        self.sealed_path = self.root/'source.jsonl'
        self.seal_receipt = migration.seal_source(self.source, self.sealed_path)
        self.seal = migration.read_seal(self.sealed_path, expected_sha256=self.seal_receipt['sha256'],
                                       expected_bytes=self.seal_receipt['bytes'])
        self.addCleanup(self.seal.close)
        self.catalog_path = self.root/'catalog.json'
        self.legacy_catalog = {'schema':'anki-web-catalog.v1',
            'cards':[{'id':'卡-α','deckId':'legacy-deck'}],
            'decks':[{'id':'legacy-deck','cardIds':['卡-α'],'count':1}]}
        raw = catalog.canonical(self.legacy_catalog).encode()
        self.catalog_path.write_bytes(raw)
        target = {'book_id':'canonical-book','source_id':'source-a','note_id':101,'guid':'original-guid',
                  'native_id':201,'model_id':301,'template_ordinal':0,'unit_id':401}
        self.binding = {'evidence':'exact-source-card-id',
                        'legacy':{'book':'liu','card_id':'卡-α','deck_id':'legacy-deck'},'target':target}
        self.aliases = {'schema':'study-progress-current-bindings-readonly.v1','catalog_revision':0,
            'ready_to_switch':False,'captured_at':'fixture','scope':'fixture',
            'books':[{'book_id':'canonical-book','legacy_book':'liu','source_id':'source-a',
                      'cards':1,'native_cards':1,'catalog':{'path':str(self.catalog_path),
                      'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}}],
            'bindings':[self.binding],'excluded_from_legacy_learning_catalog':[],'guide_proofs':{}}
        self.alias_path = self.root/'aliases.json.gz'
        self.write_aliases()
        with catalog.connect(self.target) as db, db.transaction():
            pg.initialize_connection(db)
            payload = catalog.put_json(db, {})
            col = catalog.put_json(db, {'models':json.dumps({'301':{'tmpls':[{'ord':0}]}})})
            db.execute("insert into books values('canonical-book','Any subject',2032)")
            db.execute("insert into sources values('source-a','native','source',%s,'complete')",(payload,))
            db.execute("insert into book_sources values('canonical-book','source-a',%s,%s)",(payload,col))
            db.execute("insert into units values('canonical-book',401,'unit',null,%s)",(payload,))
            db.execute("insert into notes values('canonical-book',101,'original-guid',null,'word',0,301,%s,'卡-α')",(payload,))
            db.execute("insert into native_cards values('canonical-book',201,101,401,0,%s)",(payload,))

    def drop_target(self):
        assert self.target.schema.startswith('testcatalog_')
        with psycopg.connect(self.target.dsn, autocommit=True) as db:
            db.execute(sql.SQL('drop schema if exists {} cascade').format(sql.Identifier(self.target.schema)))

    def write_aliases(self):
        raw = gzip.compress(catalog.canonical(self.aliases).encode(),mtime=0)
        self.alias_path.write_bytes(raw)
        self.alias_kw = {'expected_alias_sha256':hashlib.sha256(raw).hexdigest(),'expected_alias_bytes':len(raw)}

    @contextmanager
    def transaction(self, *, locked=True, isolation='read committed'):
        with catalog.connect(self.target) as db, db.transaction():
            db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
            if locked:
                pg.write_lock(db)
            yield db

    def plan(self, db):
        return migration.plan_import(db,self.seal,self.alias_path,**self.alias_kw)

    def run_import(self, db):
        plan=self.plan(db)
        return migration.import_snapshot(db,self.seal,self.alias_path,
            expected_plan_sha256=plan['plan_sha256'],**self.alias_kw)

    def state(self):
        with self.transaction() as db:
            return list(pg.canonical_rows(db))

    def test_lossless_all_rows_inactive_aliases_and_same_seal_idempotence(self):
        before = self.source.read_bytes()
        with self.transaction() as db:
            plan = self.plan(db)
            self.assertFalse(plan['ready_to_switch'])
            self.assertEqual(plan['target_state'],'empty')
            result=self.run_import(db)
            self.assertTrue(result['reconciliation']['equal'])
            self.assertEqual(result['status'],'imported')
            self.assertEqual(list(pg.canonical_rows(db)),list(migration.iter_sealed_rows(self.seal)))
            alias_text=db.execute('select value from metadata where key=%s',(migration.ALIASES_KEY,)).fetchone()[0]
            aliases=json.loads(alias_text)
            self.assertEqual(aliases['inactive_cards'],[{'book':'旧书-非活动🧪','card_id':'never learned'}])
            self.assertEqual(aliases['approved_report'],self.aliases)
            second=self.run_import(db)
            self.assertEqual(second['status'],'reused')
            self.assertEqual(self.plan(db)['plan_sha256'],plan['plan_sha256'])
            self.assertEqual(db.execute("select seq from study_progress_sequences where name='reviews'").fetchone()[0],99)
        self.assertEqual(self.source.read_bytes(),before)

    def test_no_implicit_transactions_locks_initialization_or_user_restore(self):
        with catalog.connect(self.target) as db:
            with self.assertRaises(migration.MigrationError):self.plan(db)
        with self.transaction(locked=False) as db:
            with self.assertRaisesRegex(migration.MigrationError,'learning lock'):
                self.plan(db)
            with self.assertRaisesRegex(migration.MigrationError,'learning lock'):
                migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256='0'*64,**self.alias_kw)
        self.assertEqual(self.state(),[])

    def test_tampered_anchor_catalog_bytes_and_deck_membership_rejected(self):
        with self.transaction() as db:
            with self.assertRaises(migration.MigrationError):
                migration.plan_import(db,self.seal,self.alias_path,expected_alias_sha256='0'*64,
                                      expected_alias_bytes=self.alias_kw['expected_alias_bytes'])
            self.catalog_path.write_bytes(b'{}')
            with self.assertRaises(migration.MigrationError):self.plan(db)
        raw=catalog.canonical({**self.legacy_catalog,'decks':[{'id':'legacy-deck','cardIds':[]}]}).encode()
        self.catalog_path.write_bytes(raw)
        self.aliases['books'][0]['catalog'].update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        self.write_aliases()
        with self.transaction() as db,self.assertRaisesRegex(migration.MigrationError,'deck'):self.plan(db)
        self.assertEqual(self.state(),[])

    def test_each_target_identity_and_source_completion_rechecked(self):
        changes={'book_id':'wrong','source_id':'wrong','note_id':102,'guid':'wrong','native_id':202,
                 'model_id':302,'template_ordinal':1,'unit_id':402}
        for key,value in changes.items():
            with self.subTest(key=key):
                saved=self.binding['target'][key];self.binding['target'][key]=value;self.write_aliases()
                with self.transaction() as db,self.assertRaises(migration.MigrationError):self.plan(db)
                self.binding['target'][key]=saved
        self.write_aliases()
        with self.transaction() as db:
            db.execute("update sources set status='building'")
            with self.assertRaises(migration.MigrationError):self.plan(db)
        self.assertEqual(self.state(),[])

    def test_same_receipt_requires_every_row_and_alias_text_unchanged(self):
        with self.transaction() as db:self.run_import(db)
        original=self.state()
        for statement in ("update study_progress_cards set revision=10 where book='liu'",
                          "update study_progress_sequences set seq=100",
                          "delete from study_progress_card_actions"):
            with self.subTest(statement=statement),self.assertRaises(RuntimeError):
                with self.transaction() as db:
                    db.execute(statement)
                    with self.assertRaisesRegex(migration.MigrationError,'differ'):self.run_import(db)
                    raise RuntimeError('undo fixture mutation')
        with self.assertRaises(RuntimeError):
            with self.transaction() as db:
                db.execute('update metadata set value=%s where key=%s',('{}',migration.ALIASES_KEY))
                with self.assertRaises(migration.MigrationError):self.run_import(db)
                raise RuntimeError('undo fixture mutation')
        self.assertEqual(self.state(),original)

    def test_nonempty_target_and_stale_plan_cannot_be_overwritten(self):
        with self.transaction() as db:
            plan=self.plan(db)
            db.execute("insert into study_progress_metadata values('revision',0)")
            with self.assertRaises(migration.MigrationError):
                migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256=plan['plan_sha256'],**self.alias_kw)
            db.execute('delete from study_progress_metadata')
            with self.assertRaises(migration.MigrationError):
                migration.import_snapshot(db,self.seal,self.alias_path,expected_plan_sha256='0'*64,**self.alias_kw)
        self.assertEqual(self.state(),[])

    def test_failure_mid_import_rolls_back_even_when_caller_catches_exception(self):
        with self.transaction() as db:
            db.execute("create function fail_migration() returns trigger language plpgsql as $$ begin raise exception 'fixture failure'; end $$")
            db.execute('create trigger fail_migration before insert on study_progress_requests for each row execute function fail_migration()')
            with self.assertRaises(psycopg.Error):self.run_import(db)
            self.assertEqual(list(pg.canonical_rows(db)),[])
            self.assertIsNone(db.execute('select value from metadata where key=%s',(migration.RECEIPT_KEY,)).fetchone())
        self.assertEqual(self.state(),[])

    def test_missing_sequence_and_nulls_remain_missing_without_seed(self):
        self.seal.close()
        with closing(sqlite3.connect(self.source)) as db,db:
            db.execute('delete from requests');db.execute('update undo set review_id=null');db.execute('delete from reviews')
            db.execute('delete from sqlite_sequence')
        self.sealed_path.unlink();r=migration.seal_source(self.source,self.sealed_path)
        self.seal=migration.read_seal(self.sealed_path,expected_sha256=r['sha256'],expected_bytes=r['bytes'])
        self.addCleanup(self.seal.close)
        with self.transaction() as db:
            self.run_import(db)
            self.assertEqual(db.execute('select count(*) from study_progress_sequences').fetchone()[0],0)
            self.assertEqual(list(pg.canonical_rows(db)),list(migration.iter_sealed_rows(self.seal)))

    def test_explicit_exception_proof_has_no_book_or_deck_heuristic(self):
        for kind in ('exact-native-and-web-identity-derivation',
                     'every-original-field-exact-in-legacy-page-and-native-GUID'):
            with self.subTest(kind=kind):
                self.binding['evidence']='exact-guide-proof'
                self.aliases['guide_proofs']={'liu':{'id':'卡-α','guid':'original-guid','native_id':201,
                    'note_id':101,'template_ordinal':0,'evidence':{'kind':kind,'approved_external_evidence':'fixture'}}}
                self.write_aliases()
                with self.assertRaises(RuntimeError):
                    with self.transaction() as db:
                        db.execute("update notes set source_card_id=null,kind='guide'")
                        self.assertTrue(self.plan(db)['ready_to_import'])
                        self.run_import(db)
                        self.assertEqual(db.execute("select card_id from study_progress_cards where book='liu'").fetchone()[0],'卡-α')
                        raise RuntimeError('rollback fixture')
                self.aliases['guide_proofs']['liu']['guid']='incorrect-proof'
                self.write_aliases()
                with self.transaction() as db:
                    db.execute("update notes set source_card_id=null,kind='guide'")
                    with self.assertRaisesRegex(migration.MigrationError,'proof'):self.plan(db)

    def test_missing_active_duplicate_binding_and_unreviewed_supplement_rejected(self):
        for mutate in ('missing','duplicate','supplement'):
            with self.subTest(mutate=mutate):
                if mutate=='missing':self.aliases['bindings']=[]
                if mutate=='duplicate':self.aliases['bindings']=[self.binding,self.binding]
                self.write_aliases()
                with self.assertRaises(RuntimeError):
                    with self.transaction() as db:
                        if mutate=='supplement':
                            payload=catalog.put_json(db,{})
                            db.execute("insert into notes values('canonical-book',102,'supp',null,'supplemental',1,301,%s,'supp')",(payload,))
                            db.execute("insert into native_cards values('canonical-book',202,102,401,0,%s)",(payload,))
                        with self.assertRaises(migration.MigrationError):self.plan(db)
                        raise RuntimeError('rollback fixture')
                self.aliases['bindings']=[self.binding]
        self.assertEqual(self.state(),[])

    def test_catalog_read_and_hash_use_one_fd_and_retarget_is_rejected(self):
        original=migration.os.fdopen
        pin=self.aliases['books'][0]['catalog']
        class MutatingRead:
            def __init__(inner,stream):inner.stream=stream
            def __enter__(inner):return inner
            def __exit__(inner,*args):return inner.stream.__exit__(*args)
            def __getattr__(inner,name):return getattr(inner.stream,name)
            def read(inner,size):
                raw=inner.stream.read(size)
                changed=self.root/'changed-catalog';changed.write_bytes(raw)
                changed.replace(self.catalog_path)
                return raw
        with patch.object(migration.os,'fdopen',side_effect=lambda *a,**kw:MutatingRead(original(*a,**kw))), \
             self.assertRaisesRegex(migration.MigrationError,'identity changed'):
            migration._load_pinned_json(self.catalog_path,pin['sha256'],pin['bytes'])
        alias=self.root/'catalog-alias.json';alias.symlink_to(self.catalog_path)
        self.assertEqual(migration._load_pinned_json(alias,pin['sha256'],pin['bytes']),self.legacy_catalog)

    def test_cancel_mid_rows_and_receipt_write_failure_roll_back_all_ten_tables(self):
        original=migration._seal_rows
        calls=0
        def interrupted(seal):
            nonlocal calls
            calls+=1
            with closing(original(seal)) as rows:
                for name,row in rows:
                    if calls==3 and name=='reviews':raise KeyboardInterrupt
                    yield name,row
        with self.transaction() as db:
            with patch.object(migration,'_seal_rows',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):
                self.run_import(db)
            self.assertFalse(self.seal._iterating)
            self.assertEqual(list(pg.canonical_rows(db)),[])
            db.execute("create function fail_receipt() returns trigger language plpgsql as $$ begin "
                       "if new.key='study.progress.migration.v1' then raise exception 'receipt failure'; end if; return new; end $$")
            db.execute('create trigger fail_receipt before insert on metadata for each row execute function fail_receipt()')
            with self.assertRaises(psycopg.Error):self.run_import(db)
            self.assertEqual(list(pg.canonical_rows(db)),[])
            self.assertEqual(db.execute('select count(*) from metadata where key=any(%s)',
                ([migration.RECEIPT_KEY,migration.ALIASES_KEY],)).fetchone()[0],0)
        self.assertEqual(self.state(),[])

    def test_unauthenticated_closed_and_modified_private_seal_never_imports(self):
        with migration.read_seal(self.sealed_path) as untrusted,self.transaction() as db:
            with self.assertRaises(migration.SealError):
                migration.plan_import(db,untrusted,self.alias_path,**self.alias_kw)
        with self.transaction() as db,self.assertRaises(migration.SealError):
            migration.plan_import(db,untrusted,self.alias_path,**self.alias_kw)
        private=Path(self.seal._temporary.name)/'artifact.jsonl'
        with private.open('r+b') as stream:stream.write(b'!')
        with self.transaction() as db,self.assertRaises(migration.SealError):self.plan(db)
        self.assertEqual(self.state(),[])

    def test_outer_rollback_undoes_successful_import_and_reconcile_reports_drift(self):
        with self.assertRaises(RuntimeError):
            with self.transaction() as db:
                self.run_import(db)
                db.execute("update study_progress_sequences set seq=100")
                result=migration.reconcile(db,self.seal)
                self.assertFalse(result['equal'])
                self.assertFalse(result['tables']['sqlite_sequence']['equal'])
                self.assertFalse(result['ready_to_switch'])
                raise RuntimeError('caller rollback')
        self.assertEqual(self.state(),[])

    def test_migrated_state_continues_shared_http_business_like_sqlite(self):
        from datetime import datetime,timezone
        from urllib.parse import urlencode
        from anki_pipeline import study_progress as progress
        from tests.test_study_progress_http import serve,request
        with self.transaction() as db:self.run_import(db)
        books={'liu':{'id':'liu','name':'Any subject','previewPath':'/fixture/index.html',
            'cards':[{'id':'卡-α','word':'label','meta':'unit','deckId':'legacy-deck','previewUrl':'/fixture/card.html'}],
            'decks':[{'id':'legacy-deck','name':'old identity','cardIds':['卡-α']}]}}
        clock=lambda:datetime(2026,10,20,tzinfo=timezone.utc)
        legacy=progress.StudyStore(self.source,books,now=clock)
        current=progress.StudyStore(None,books,now=clock,storage=pg.PgStudyStorage(self.target,backups=self.root/'backups'))
        base={'book':'liu','deck':'all'}
        unsuspend={**base,'cardId':'卡-α','revision':11,'action':'unsuspend','requestId':'after-migration-unsuspend'}
        answer={**base,'cardId':'卡-α','revision':13,'rating':3,'durationMs':500,'requestId':'after-migration-answer'}
        calls=[('GET','overview',None),('GET','browse?book=liu',None),
               ('GET','card?'+urlencode({'book':'liu','cardId':'卡-α'}),None),
               ('POST','card-action',unsuspend),('POST','answer',answer),('POST','answer',answer),
               ('POST','undo',base),('GET','stats?book=liu',None)]
        with serve(legacy) as old_port,serve(current) as new_port:
            for index,(method,path,body) in enumerate(calls):
                with self.subTest(path=path,index=index):
                    old=request(old_port,method,'/api/study/'+path,body)
                    new=request(new_port,method,'/api/study/'+path,body)
                    self.assertEqual(new,old)
                    self.assertEqual(new[0],200)
                    self.assertEqual(self.state(),list(snapshot.canonical_rows(self.source)))
                    if path=='answer':
                        with self.transaction() as db:
                            self.assertEqual(db.execute('select max(id) from study_progress_reviews').fetchone()[0],100)
                            self.assertEqual(db.execute("select seq from study_progress_sequences where name='reviews'").fetchone()[0],100)

    def test_reapproved_alias_change_requires_new_plan_cas(self):
        with self.transaction() as db:
            old=self.plan(db)
            self.aliases['captured_at']='new explicitly approved report'
            self.write_aliases()
            with self.assertRaisesRegex(migration.MigrationError,'plan CAS'):
                migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256=old['plan_sha256'],**self.alias_kw)
            self.assertEqual(list(pg.canonical_rows(db)),[])

    def test_unrepresentable_postgres_text_is_blocked_without_rewriting_it(self):
        self.seal.close()
        with closing(sqlite3.connect(self.source)) as db,db:
            db.execute('update card_controls set note=?',('original\x00text',))
        self.sealed_path.unlink();r=migration.seal_source(self.source,self.sealed_path)
        self.seal=migration.read_seal(self.sealed_path,expected_sha256=r['sha256'],expected_bytes=r['bytes'])
        self.addCleanup(self.seal.close)
        with self.transaction() as db,self.assertRaisesRegex(migration.MigrationError,r'U\+0000'):
            self.plan(db)
        self.assertFalse(self.seal._iterating)
        self.assertEqual(self.state(),[])

    def test_metadata_trigger_cannot_silently_change_the_published_receipt(self):
        with self.transaction() as db:
            db.execute("create function change_receipt() returns trigger language plpgsql as $$ begin "
                       "if new.key='study.progress.migration.v1' then new.value='{}'; end if; return new; end $$")
            db.execute('create trigger change_receipt before insert on metadata for each row execute function change_receipt()')
            with self.assertRaisesRegex(migration.MigrationError,'published migration'):
                self.run_import(db)
            self.assertEqual(list(pg.canonical_rows(db)),[])
            self.assertEqual(db.execute('select count(*) from metadata where key=any(%s)',
                ([migration.RECEIPT_KEY,migration.ALIASES_KEY],)).fetchone()[0],0)

    def test_metadata_publish_side_write_cannot_change_learning_rows(self):
        with self.transaction() as db:
            db.execute("create function side_write_receipt() returns trigger language plpgsql as $$ begin "
                       "if new.key='study.progress.migration.v1' then "
                       "update study_progress_cards set revision=10 where book='liu'; "
                       "end if; return new; end $$")
            db.execute('create trigger side_write_receipt after insert on metadata for each row execute function side_write_receipt()')
            with self.assertRaisesRegex(migration.MigrationError,'published.*rows differ'):
                self.run_import(db)
            self.assertEqual(list(pg.canonical_rows(db)),[])
            self.assertEqual(db.execute('select count(*) from metadata where key=any(%s)',
                ([migration.RECEIPT_KEY,migration.ALIASES_KEY],)).fetchone()[0],0)

    def test_repeatable_read_old_catalog_view_cannot_import_stale_bindings(self):
        with self.transaction() as db:old_plan=self.plan(db)
        with self.transaction(isolation='repeatable read') as db:
            self.assertEqual(db.execute('select guid from notes').fetchone()[0],'original-guid')
            with catalog.connect(self.target) as writer,writer.transaction():
                catalog.write_lock(writer)
                writer.execute("update notes set guid='new-guid'")
                catalog.event(writer,'fixture-canonical-identity-change',{})
            # The RR view demonstrably remains old. Repeating this SELECT or
            # taking the advisory lock late cannot refresh it.
            self.assertEqual(db.execute('select guid from notes').fetchone()[0],'original-guid')
            with self.assertRaisesRegex(migration.MigrationError,'READ COMMITTED'):
                migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256=old_plan['plan_sha256'],**self.alias_kw)
        self.assertEqual(self.state(),[])

    def test_catalog_writer_lock_wait_refreshes_read_committed_identity_reads(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time
        with self.transaction() as db:old_plan=self.plan(db)
        observed,proceed=threading.Event(),threading.Event()
        reader={}
        def attempt():
            with self.transaction() as db:
                reader['pid']=db.info.backend_pid
                reader['old_guid']=db.execute('select guid from notes').fetchone()[0]
                observed.set()
                if not proceed.wait(3):raise AssertionError('test writer did not release import gate')
                return migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256=old_plan['plan_sha256'],**self.alias_kw)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(attempt)
            self.assertTrue(observed.wait(3))
            self.assertEqual(reader['old_guid'],'original-guid')
            with catalog.connect(self.target) as writer,writer.transaction():
                catalog.write_lock(writer)
                writer.execute("update notes set guid='new-guid'")
                catalog.event(writer,'fixture-canonical-identity-change',{})
                proceed.set()
                deadline=time.monotonic()+3
                waited=False
                while time.monotonic()<deadline:
                    row=writer.execute("select 1 from pg_locks where pid=%s and locktype='advisory' and not granted",
                                       (reader['pid'],)).fetchone()
                    if row:
                        waited=True
                        break
                    if future.done():break
                    time.sleep(.01)
                self.assertTrue(waited,'import did not wait on the actual catalog writer fence')
                self.assertFalse(future.done())
            with self.assertRaisesRegex(migration.MigrationError,'catalog revision differs'):
                future.result(timeout=3)
        self.assertEqual(self.state(),[])
        # A new externally approved mapping can be used after the stale one is
        # rejected; this is not a permanent lock or an unconditional rejection.
        self.aliases['catalog_revision']=1
        self.binding['target']['guid']='new-guid'
        self.write_aliases()
        with self.transaction() as db:self.assertEqual(self.run_import(db)['status'],'imported')

    def test_fixed_snapshot_plan_import_rejected_but_readonly_reconcile_supported(self):
        for isolation in ('repeatable read','serializable'):
            with self.subTest(isolation=isolation),self.transaction(isolation=isolation) as db:
                with self.assertRaisesRegex(migration.MigrationError,'READ COMMITTED'):self.plan(db)
                with self.assertRaisesRegex(migration.MigrationError,'READ COMMITTED'):
                    migration.import_snapshot(db,self.seal,self.alias_path,
                        expected_plan_sha256='0'*64,**self.alias_kw)
            with self.subTest(readonly=isolation),catalog.connect(self.target,readonly=True) as db,db.transaction():
                db.execute(sql.SQL('set transaction isolation level {}').format(sql.SQL(isolation)))
                self.assertFalse(migration.reconcile(db,self.seal)['equal'])
        with self.transaction(locked=False) as db,self.assertRaisesRegex(migration.MigrationError,'learning lock'):
            migration.reconcile(db,self.seal)

    def test_catalog_and_learning_fences_survive_failed_import_savepoint_until_outer_exit(self):
        learning_key=int(catalog.identity(pg.VERSION,self.target.schema)[:15],16)
        content_key=int(catalog.identity('catalog-content-writes.v1')[:15],16)
        with self.transaction() as db:
            plan=self.plan(db)
            with self.assertRaisesRegex(migration.MigrationError,'plan CAS'):
                migration.import_snapshot(db,self.seal,self.alias_path,
                    expected_plan_sha256='0'*64,**self.alias_kw)
            self.assertEqual(plan['target_state'],'empty')
            with catalog.connect(self.target) as contender,contender.transaction():
                self.assertFalse(contender.execute('select pg_try_advisory_xact_lock(%s)',(learning_key,)).fetchone()[0])
                self.assertFalse(contender.execute('select pg_try_advisory_xact_lock(%s)',(content_key,)).fetchone()[0])
        with catalog.connect(self.target) as contender,contender.transaction():
            self.assertTrue(contender.execute('select pg_try_advisory_xact_lock(%s)',(learning_key,)).fetchone()[0])
            self.assertTrue(contender.execute('select pg_try_advisory_xact_lock(%s)',(content_key,)).fetchone()[0])
