"""Fallback exports use only temporary files and random owned PG schemas."""
from contextlib import closing
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
from psycopg.pq import TransactionStatus

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_progress_pg as pg
from anki_pipeline import study_progress_snapshot as snapshot


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires explicit isolated PostgreSQL test connection')
class ProgressSQLiteExportTests(unittest.TestCase):
    def setUp(self):
        from anki_pipeline import study_progress as progress
        from tests.test_study_progress import Clock, catalog as books
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'current.sqlite3'
        self.target=catalog.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        self.addCleanup(self.drop_target)
        catalog.initialize(self.target)
        self.storage=pg.PgStudyStorage(self.target,backups=self.root/'backups');self.storage.initialize()
        self.clock=Clock();self.books=books()
        self.store=progress.StudyStore(None,self.books,now=self.clock,storage=self.storage)
        self.store.initialize_catalog()

    def drop_target(self):
        assert self.target.schema.startswith('testcatalog_')
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('drop schema if exists {} cascade').format(sql.Identifier(self.target.schema)))

    def exporter(self):
        from anki_pipeline import study_progress_sqlite_export
        return study_progress_sqlite_export

    def rows(self):
        with catalog.connect(self.target,readonly=True) as db,db.transaction():
            db.execute('set transaction isolation level repeatable read read only')
            return list(pg.canonical_rows(db))

    def answer(self,request_id='current-score'):
        card=self.store.dispatch('GET','/api/study/session',{'book':'redbook'},None)['card']
        return {'book':'redbook','deck':'all','cardId':card['id'],'revision':card['revision'],
                'rating':3,'durationMs':1234,'requestId':request_id}

    def test_real_http_score_undo_retry_and_all_typed_tables_roundtrip(self):
        from anki_pipeline import study_progress as progress
        from tests.test_study_progress_http import FIXTURE,serve,request
        fixture=json.loads(FIXTURE.read_text())
        with serve(self.store) as port:
            for step in fixture['requests']:
                self.clock.value=self.clock.value.fromisoformat(step['at'])
                status,headers,payload=request(port,step['method'],step['path'],step['body'])
                self.assertEqual(status,step['status']);self.assertEqual(headers,step['headers'])
                self.assertEqual(payload.decode(),step['response_text'])
                self.assertEqual(hashlib.sha256(b''.join(self.rows())).hexdigest(),step['state_sha256'])
                if step['name']=='checkpoint after undo':break
        wanted=self.rows();m=self.exporter()
        with patch.object(progress,'StudyStore',side_effect=AssertionError('export must not seed')):
            proof=m.export_sqlite(self.target,self.output)
        self.assertEqual(list(snapshot.canonical_rows(self.output)),wanted)
        self.assertFalse(proof['ready_to_switch']);self.assertFalse(proof['writer_quiescence_verified'])
        self.assertEqual(proof['consistency'],'observed-repeatable-read')
        self.assertEqual(set(proof['tables']),set(snapshot.TABLES))
        self.assertEqual(self.rows(),wanted)
        fallback=progress.StudyStore(self.output,self.books,now=self.clock)
        retry=next(row['body'] for row in fixture['requests'] if row['name']=='first rating')
        with serve(self.store) as original_port,serve(fallback) as fallback_port:
            for method,path,body in [('POST','/api/study/answer',retry),
                                     ('GET','/api/study/stats?book=redbook',None),
                                     ('GET','/api/study/card?book=redbook&cardId=redbook-1',None)]:
                self.assertEqual(request(original_port,method,path,body),request(fallback_port,method,path,body))
        self.assertEqual(list(snapshot.canonical_rows(self.output)),self.rows())

    def test_sequence_absence_and_high_watermark_99_are_not_recomputed(self):
        m=self.exporter();proof=m.export_sqlite(self.target,self.output)
        self.assertEqual(proof['review_sequence'],{'present':False,'high_watermark':None,'maximum_id':0})
        with closing(sqlite3.connect(self.output)) as db:self.assertEqual(db.execute('select * from sqlite_sequence').fetchall(),[])
        self.store.dispatch('POST','/api/study/answer',{},self.answer())
        with catalog.connect(self.target) as db:db.execute("update study_progress_sequences set seq=99 where name='reviews'")
        second=self.root/'after-score.sqlite3';proof=m.export_sqlite(self.target,second)
        self.assertEqual(proof['review_sequence']['high_watermark'],99)
        self.assertEqual(list(snapshot.canonical_rows(second)),self.rows())

    def test_inactive_namespace_raw_unicode_json_float_and_null_are_preserved(self):
        raw=' { "message" : "原文 e\u0301 / \\u4e2d", "nested" : {"n": 1.25} }\n'
        note='原始笔记\r\n<p>e\u0301 & 中文</p>\\path'
        retention=float.fromhex('0x1.c0ca458901e65p-1')
        with catalog.connect(self.target) as db,db.transaction():
            db.execute('insert into study_progress_settings values(%s,%s,%s,%s)',('inactive-book',0,17,retention))
            db.execute('insert into study_progress_cards values(%s,%s,%s,%s,%s)',
                       ('inactive-book','原卡 e\u0301',1,None,None))
            db.execute('insert into study_progress_card_controls values(%s,%s,%s,%s,%s,%s)',
                       ('inactive-book','原卡 e\u0301',7,1,None,note))
            db.execute('insert into study_progress_preferences values(1,%s) on conflict(id) do update set value=excluded.value',(raw,))
        wanted=self.rows();proof=self.exporter().export_sqlite(self.target,self.output)
        self.assertEqual(list(snapshot.canonical_rows(self.output)),wanted)
        self.assertIn('inactive-book',proof['snapshot_inspection']['books'])
        with closing(sqlite3.connect(self.output)) as db:
            self.assertEqual(db.execute('select value from preferences').fetchone()[0],raw)
            self.assertEqual(db.execute('select note from card_controls where book=?',('inactive-book',)).fetchone()[0],note)
            self.assertEqual(db.execute('select desired_retention from settings where book=?',('inactive-book',)).fetchone()[0].hex(),retention.hex())
            self.assertEqual(db.execute('select scheduler_json,introduced_at from cards where book=?',('inactive-book',)).fetchone(),(None,None))

    def test_caller_transaction_must_be_readonly_repeatable_and_is_not_committed(self):
        m=self.exporter()
        with catalog.connect(self.target) as db:
            with self.assertRaises(m.SQLiteExportError):m.export_sqlite(db,self.output)
            for mode in ['read committed read only','repeatable read read write']:
                with db.transaction():
                    db.execute('set transaction isolation level '+mode)
                    with self.assertRaises(m.SQLiteExportError):m.export_sqlite(db,self.output)
            with db.transaction():
                db.execute('set transaction isolation level repeatable read read only')
                before=db.execute('select pg_current_snapshot()::text').fetchone()[0]
                m.export_sqlite(db,self.output)
                self.assertEqual(db.info.transaction_status,TransactionStatus.INTRANS)
                self.assertEqual(db.execute('select pg_current_snapshot()::text').fetchone()[0],before)

    def test_writer_can_commit_but_same_rr_export_remains_observed_not_cutover_ready(self):
        m=self.exporter();wanted=self.rows();original=m.pg.canonical_rows;body=self.answer()
        def concurrent(db):
            for index,line in enumerate(original(db)):
                yield line
                if index==0:self.store.dispatch('POST','/api/study/answer',{},body)
        with patch.object(m.pg,'canonical_rows',side_effect=concurrent):proof=m.export_sqlite(self.target,self.output)
        self.assertEqual(list(snapshot.canonical_rows(self.output)),wanted)
        self.assertNotEqual(self.rows(),wanted)
        self.assertFalse(proof['ready_to_switch'])

    def test_existing_or_racing_paths_and_cancel_clean_only_owned_files(self):
        m=self.exporter();self.output.write_bytes(b'original')
        with self.assertRaises(FileExistsError):m.export_sqlite(self.target,self.output)
        self.assertEqual(self.output.read_bytes(),b'original');self.output.unlink()
        original=m.pg.canonical_rows
        def cancelled(db):
            yield next(original(db));raise KeyboardInterrupt
        with patch.object(m.pg,'canonical_rows',side_effect=cancelled),self.assertRaises(KeyboardInterrupt):
            m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(any(p.name.startswith('.study-progress-sqlite-') for p in self.root.iterdir()))
        link=m.os.link
        def race(source,target,**kwargs):
            Path(target).write_bytes(b'racer');return link(source,target,**kwargs)
        with patch.object(m.os,'link',side_effect=race),self.assertRaises(FileExistsError):m.export_sqlite(self.target,self.output)
        self.assertEqual(self.output.read_bytes(),b'racer')

    def test_published_bytes_proof_permissions_and_post_link_cancel(self):
        m=self.exporter();proof=m.export_sqlite(self.target,self.output)
        proof_path=self.output.with_name(self.output.name+'.proof.json')
        self.assertEqual(json.loads(proof_path.read_bytes()),proof)
        self.assertEqual(self.output.stat().st_mode&0o777,0o600)
        self.assertEqual(proof_path.stat().st_mode&0o777,0o600)
        self.assertEqual(hashlib.sha256(self.output.read_bytes()).hexdigest(),proof['sqlite']['sha256'])
        self.output.unlink();proof_path.unlink();link=m.os.link
        def interrupted(source,target,**kwargs):link(source,target,**kwargs);raise KeyboardInterrupt
        with patch.object(m.os,'link',side_effect=interrupted),self.assertRaises(KeyboardInterrupt):m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists());self.assertFalse(proof_path.exists())

    def test_post_link_tamper_and_proof_race_do_not_publish_unverified_pair(self):
        m=self.exporter();link=m.os.link
        proof_path=self.output.with_name(self.output.name+'.proof.json')
        def tamper(source,target,**kwargs):
            link(source,target,**kwargs)
            with Path(target).open('r+b') as stream:stream.write(b'not sqlite')
        with patch.object(m.os,'link',side_effect=tamper),self.assertRaises(m.SQLiteExportError):
            m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists());self.assertFalse(proof_path.exists())
        def proof_race(source,target,**kwargs):
            if Path(target).name==proof_path.name:proof_path.write_bytes(b'foreign proof')
            link(source,target,**kwargs)
        with patch.object(m.os,'link',side_effect=proof_race),self.assertRaises(FileExistsError):
            m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists());self.assertEqual(proof_path.read_bytes(),b'foreign proof')

    def test_verified_snapshot_bytes_cannot_change_before_publication_seal(self):
        m=self.exporter();reconcile=m._reconcile
        def tamper(path,*args):
            report=reconcile(path,*args)
            with path.open('r+b') as stream:stream.write(b'!')
            return report
        with patch.object(m,'_reconcile',side_effect=tamper),self.assertRaises(m.SQLiteExportError):
            m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_name(self.output.name+'.proof.json').exists())

    def test_second_link_cannot_change_already_linked_sqlite_unnoticed(self):
        m=self.exporter();link=m.os.link;proof_path=self.output.with_name(self.output.name+'.proof.json')
        def tamper_first_link(source,target,**kwargs):
            link(source,target,**kwargs)
            if Path(target).name==proof_path.name:
                with self.output.open('r+b') as stream:stream.write(b'!')
        with patch.object(m.os,'link',side_effect=tamper_first_link),self.assertRaises(m.SQLiteExportError):
            m.export_sqlite(self.target,self.output)
        self.assertFalse(self.output.exists());self.assertFalse(proof_path.exists())

    def test_invalid_current_source_is_rejected_without_repair_or_publish(self):
        m=self.exporter()
        with catalog.connect(self.target) as db:db.execute("update study_progress_metadata set value=-1 where key='revision'")
        wanted=self.rows()
        with self.assertRaises(m.SQLiteExportError):m.export_sqlite(self.target,self.output)
        self.assertEqual(self.rows(),wanted)
        self.assertFalse(self.output.exists())
        self.assertFalse(any(p.name.startswith('.study-progress-sqlite-') for p in self.root.iterdir()))


if __name__=='__main__':unittest.main()
