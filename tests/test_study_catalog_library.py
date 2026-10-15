import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
import uuid
import zipfile

import genanki
import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_library import classify,library


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires isolated PostgreSQL test connection')
class GeneralLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        model=genanki.Model(8123,'数学双向卡',fields=[{'name':'Question'},{'name':'Answer'}],templates=[
            {'name':'正向','qfmt':'问题：{{Question}}','afmt':'答案：{{Answer}}'},
            {'name':'反向','qfmt':'反向问题：{{Answer}}','afmt':'反向答案：{{Question}}'}])
        deck=genanki.Deck(8124,'数学::极限')
        deck.add_note(genanki.Note(model=model,fields=[r'\(\lim_{x\to0}\frac{\sin x}{x}\)', '1']))
        path=self.root/'math.apkg';genanki.Package(deck).write_to_file(str(path))
        import_package(self.target,path,book_id='math',title='数学',edition=2027);path.unlink()

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def test_general_mapping_has_no_word_requirement_and_preserves_both_templates(self):
        with c.connect(self.target,readonly=True) as db:
            nid=db.execute("select note_id from notes where book_id='math'").fetchone()[0]
            component=db.execute("select component_id from note_fields where book_id='math' and name='Answer'").fetchone()[0]
        scope={'subject':'数学','exam':'考研','topics':['极限'],'kind':'题目'}
        mapped=create_book(self.target,{'schema':'study-book-map.v1','id':'math-review','title':'数学复习',
            'edition':2028,'scope':scope,'units':[{'name':'高数::极限','items':[{'from_book':'math','from_note':nid}]}]})
        self.assertEqual(mapped['notes'],1)
        c.edit_component(self.target,component,'1，利用基本极限',expected='1',reason='补充推导',backups=self.root/'backups')
        apkg=self.root/'math-review.apkg';export_book(self.target,'math-review',apkg)
        with zipfile.ZipFile(apkg) as archive:
            native=sqlite3.connect(':memory:')
            try:
                native.deserialize(archive.read('collection.anki2'))
                self.assertEqual(native.execute('select count(*) from cards').fetchone()[0],2)
                ids=[r[0] for r in native.execute('select id from notes union all select id from cards')]
                self.assertEqual(len(set(ids)),3)
                for identifier in ids:self.assertLess(abs(identifier/1000-time.time()),60)
                self.assertIn('基本极限',native.execute('select flds from notes').fetchone()[0])
            finally:native.close()
        web=self.root/'web';report=export_book(self.target,'math-review',web,format='web')
        self.assertEqual((report['notes'],report['cards']),(1,2))
        data=json.loads((web/'catalog.json').read_text());self.assertEqual(data['scope'],scope)
        self.assertEqual([x['template_ordinal'] for x in data['cards']],[0,1])
        self.assertEqual(len({x['id'] for x in data['cards']}),2)
        self.assertIn('反向问题',(web/data['cards'][1]['url']).read_text())
        self.assertIn('基本极限',(web/data['cards'][0]['url']).read_text())
        self.assertEqual(library(self.target,subject='数学',exam='考研')['books'][0]['id'],'math-review')

    def test_scope_does_not_imply_a_new_database_or_an_english_word(self):
        classify(self.target,'math',{'subject':'数学','exam':'考研'},backups=self.root/'backups')
        with c.connect(self.target,readonly=True) as db:
            self.assertEqual(db.execute('select count(*) from words').fetchone()[0],0)
        self.assertEqual(library(self.target,exam='IELTS')['books'],[])
        self.assertEqual(library(self.target,subject='数学')['books'][0]['title'],'数学')
