import copy
import html
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import zipfile

import psycopg
from psycopg import sql
from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_catalog_presentation import install
from anki_pipeline.study_exam_package import source_package
from anki_pipeline.study_exam_refresh import refresh, _identity


def snapshot(rows):
    result=[]
    for year, number, status in rows:
        key=f'politics:{year}-questions:q-{number}'
        record={'paper':{'id':f'politics:{year}-questions','year':year},
                'question':{'id':f'q-{number}','number':str(number),'questionType':'single_choice','options':[]}}
        result.append({'key':key,'year':year,'type':'single_choice','title':f'{year} · 单选题 · 第 {number} 题',
                       'source_label':key,'question':f'<p>题目{number}</p>',
                       'answer':'<p>答案A</p>' if status=='available' else '<p>未提供</p>',
                       'status':status,'source_record':record})
    return {'questions':result,'resources':{},'source_sha256':'0'*64}


class SourceIdentityTests(unittest.TestCase):
    def test_wrong_guid_and_question_binding_are_rejected(self):
        fields=['','','','','available',html.escape(json.dumps(snapshot([(2023,1,'available')])['questions'][0]['source_record']))]
        with self.assertRaisesRegex(ValueError,'GUID'): _identity(fields,'wrong','fixture')


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'explicit isolated PostgreSQL connection required')
class ExamRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testexamrefresh_'+uuid.uuid4().hex)
        c.initialize(self.target)
        self.bid='exam-refresh-fixture'
        old=self.root/'old.apkg'
        source_package(snapshot([(2023,1,'missing'),(2023,2,'available')]),old,book_id=self.bid,title='Old')
        self.imported=import_package(self.target,old,book_id=self.bid,title='Old',edition=2023)
        other=self.root/'other.apkg';source_package(snapshot([(2022,1,'available')]),other,book_id='other',title='Other')
        import_package(self.target,other,book_id='other',title='Other',edition=2022)
        install(self.target)
        self.new=self.root/'new.apkg'
        source_package(snapshot([(2023,1,'available'),(2023,2,'available'),(2024,1,'available')]),self.new,book_id=self.bid,title='New')
        with c.connect(self.target) as db,c.transaction(db):
            # A reviewed native card must not be reset by a source refresh.
            cid,pid=db.execute('SELECT native_id,payload_id FROM native_cards WHERE book_id=%s ORDER BY native_id DESC LIMIT 1',(self.bid,)).fetchone()
            value=c.get_json(db,pid);value.update(type=2,queue=2,due=17,reps=6,ivl=13)
            db.execute('UPDATE native_cards SET payload_id=%s WHERE book_id=%s AND native_id=%s',(c.put_json(db,value),self.bid,cid))

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def apply(self,db):
        return refresh(db,self.new,book_id=self.bid,title='New',edition=2024,
                       expected_source=self.imported['source_id'],backup_dir=self.root/'backup')

    def test_full_refresh_preserves_old_ids_templates_other_book_and_exports(self):
        with c.connect(self.target) as db:
            before=list(db.execute('SELECT note_id,guid FROM notes WHERE book_id=%s ORDER BY note_id',(self.bid,)))
            cards=list(db.execute('SELECT native_id,payload_id FROM native_cards WHERE book_id=%s ORDER BY native_id',(self.bid,)))
            payloads={cid:c.get_json(db,pid) for cid,pid in cards}
            other=list(db.execute("SELECT n::text FROM notes n WHERE book_id='other'"))
            from anki_pipeline.study_catalog_presentation import registry
            presentation=registry(db)
        with c.connect(self.target) as db,c.transaction(db): receipt=self.apply(db)
        self.assertEqual(receipt['notes'],3);self.assertEqual(receipt['created_notes'],1)
        self.assertEqual(len(receipt['source_default_unsuspended_cards']),1)
        self.assertTrue(Path(receipt['backup']).is_file())
        with c.connect(self.target) as db:
            self.assertTrue(set(before).issubset(set(db.execute('SELECT note_id,guid FROM notes WHERE book_id=%s',(self.bid,)))))
            self.assertEqual(other,list(db.execute("SELECT n::text FROM notes n WHERE book_id='other'")))
            self.assertEqual(presentation,registry(db))
            for cid,pid in db.execute('SELECT native_id,payload_id FROM native_cards WHERE book_id=%s',(self.bid,)):
                if cid not in payloads:continue
                expected=copy.deepcopy(payloads[cid])
                if expected['queue']==-1:expected['queue']=0
                self.assertEqual(expected,c.get_json(db,pid))
            book=project_book(db,self.bid)
            self.assertEqual(book['title'],'New')
            self.assertEqual(len(book['unit_overlay']['cards']),3)
            self.assertTrue(all(d['name']=='Default' or d['name'].startswith('New::') for d in book['units'].values()))
            self.assertEqual(book['units']['1']['name'],'Default')
            for nid,_ in before:
                self.assertIn('答案A',project_note(db,book,nid)['fields'][2])
        apkg=self.root/'out.apkg';export_book(self.target,self.bid,apkg)
        with zipfile.ZipFile(apkg) as archive:
            native=sqlite3.connect(':memory:');native.deserialize(archive.read('collection.anki2'))
            self.assertEqual(native.execute('SELECT count(*) FROM notes').fetchone()[0],3)
            self.assertEqual(native.execute('SELECT count(*) FROM cards').fetchone()[0],3)
            self.assertEqual(native.execute('PRAGMA integrity_check').fetchone()[0],'ok');native.close()

    def test_existing_overlay_ids_survive_expansion(self):
        import genanki
        from anki_pipeline import study_catalog_units as units
        with c.connect(self.target) as db,c.transaction(db):
            ids=[r[0] for r in db.execute('SELECT native_id FROM native_cards WHERE book_id=%s',(self.bid,))]
            decks={'1':genanki.Deck(1,'Default').to_json(),
                   '501':genanki.Deck(501,'Old::2023 年').to_json(),
                   '502':genanki.Deck(502,'Old::2023 年::单选题').to_json()}
            units.install(db,self.bid,decks,{str(cid):502 for cid in ids},expected=None)
        with c.connect(self.target) as db,c.transaction(db): self.apply(db)
        with c.connect(self.target) as db:
            overlay=units.registry(db)[self.bid]
            self.assertEqual(overlay['units']['501']['name'],'New::2023 年')
            self.assertEqual(overlay['units']['502']['name'],'New::2023 年::单选题')
            self.assertTrue(all(overlay['cards'][str(cid)]==502 for cid in ids))
            self.assertEqual(len(overlay['cards']),3)

    def test_stale_source_and_removed_question_leave_catalog_unchanged(self):
        with c.connect(self.target) as db,c.transaction(db):
            with self.assertRaisesRegex(ValueError,'stale'):
                refresh(db,self.new,book_id=self.bid,title='New',edition=2024,expected_source='stale',backup_dir=self.root/'backup')
        removed=self.root/'removed.apkg';source_package(snapshot([(2024,1,'available')]),removed,book_id=self.bid,title='New')
        with c.connect(self.target) as db,c.transaction(db):
            with self.assertRaisesRegex(ValueError,'remove'):
                refresh(db,removed,book_id=self.bid,title='New',edition=2024,expected_source=self.imported['source_id'],backup_dir=self.root/'backup')
        with c.connect(self.target) as db:
            self.assertEqual(db.execute('SELECT source_id FROM book_sources WHERE book_id=%s',(self.bid,)).fetchone()[0],self.imported['source_id'])
            self.assertEqual(db.execute('SELECT count(*) FROM notes WHERE book_id=%s',(self.bid,)).fetchone()[0],2)

    def test_caller_rollback_restores_all_mutable_rows(self):
        with c.connect(self.target) as db:
            prior=list(db.execute('SELECT n::text FROM notes n ORDER BY book_id,note_id'))
            meta=dict(db.execute('SELECT key,value FROM metadata'))
        with self.assertRaisesRegex(RuntimeError,'cancel'):
            with c.connect(self.target) as db,c.transaction(db):
                self.apply(db);raise RuntimeError('cancel')
        with c.connect(self.target) as db:
            self.assertEqual(prior,list(db.execute('SELECT n::text FROM notes n ORDER BY book_id,note_id')))
            self.assertEqual(meta,dict(db.execute('SELECT key,value FROM metadata')))
            self.assertEqual(db.execute('SELECT source_id FROM book_sources WHERE book_id=%s',(self.bid,)).fetchone()[0],self.imported['source_id'])
