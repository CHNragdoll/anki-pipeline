import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_catalog_import import import_package
from tests import test_study_catalog_import as fixtures


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class MappedBookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        for book in ('one','two'):
            path=fixtures.CatalogImportTests.package(self,book)
            import_package(self.target,path,book_id=book,title=book,edition=2027)
            path.unlink()
        self.mapping={'schema':'study-book-map.v1','id':'future','title':'下一本书','edition':2028,
                      'units':[{'name':'核心词::Unit 01','words':[{'word':'train','from_book':'one'},
                                                                 {'word':'training','from_book':'one'}]}]}

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def test_new_edition_needs_only_mapping_and_shared_revision_reaches_it(self):
        with c.connect(self.target,readonly=True) as db:
            original_media=db.execute('select count(distinct object_id) from resource_aliases').fetchone()[0]
        result=create_book(self.target,self.mapping)
        self.assertEqual(result['notes'],2);self.assertEqual(result['new_media_bytes'],0)
        self.assertTrue(create_book(self.target,self.mapping)['already_created'])
        with c.connect(self.target,readonly=True) as db:
            self.assertEqual(db.execute('select count(distinct object_id) from resource_aliases').fetchone()[0],original_media)
            collection_id=db.execute("select collection_id from book_sources where book_id='future'").fetchone()[0]
            skeleton=sqlite3.connect(':memory:')
            try:
                skeleton.deserialize(c.get_object(db,collection_id))
                self.assertEqual(skeleton.execute('select count(*) from notes').fetchone()[0],0)
                self.assertEqual(skeleton.execute('select count(*) from cards').fetchone()[0],0)
            finally:skeleton.close()
            component=db.execute("select c.id from components c join words w on w.id=c.word_id where w.surface='train' and c.name='SimpleDefinition'").fetchone()[0]
        c.edit_component(self.target,component,'一次修订，三书共用',expected='训练',reason='新书共用验证',backups=self.root/'backups')
        path=self.root/'future.apkg';export_book(self.target,'future',path)
        with zipfile.ZipFile(path) as z:
            native=sqlite3.connect(':memory:')
            try:
                native.deserialize(z.read('collection.anki2'))
                row=native.execute("select flds from notes where sfld='train'").fetchone()[0]
                self.assertIn('一次修订，三书共用',row)
                self.assertIn('核心词 Unit 01 ➫ 1',row)
                self.assertEqual(native.execute('select count(*) from cards').fetchone()[0],2)
                self.assertEqual(native.execute('select sum(reps) from cards').fetchone()[0],0)
                self.assertEqual(z.read('0'),b'original immutable media bytes')
            finally:native.close()
        folder=self.root/'future-web';export_book(self.target,'future',folder,format='web')
        catalog=json.loads((folder/'catalog.json').read_text())
        self.assertEqual([x['word'] for x in catalog['cards']],['train','training'])
        self.assertIn('一次修订，三书共用',(folder/catalog['cards'][0]['url']).read_text())

    def test_ambiguous_or_invalid_mapping_rolls_back_without_new_book(self):
        self.mapping['units'][0]['words'][0].pop('from_book')
        before=c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError,'explicit source bundle'):create_book(self.target,self.mapping)
        self.assertEqual(c.logical_digest(self.target),before)

    def test_existing_edition_mapping_cannot_be_silently_replaced(self):
        create_book(self.target,self.mapping)
        self.mapping['edition']=2029
        with self.assertRaisesRegex(ValueError,'reviewed mapping revision'):create_book(self.target,self.mapping)

    def test_same_second_revisions_and_revert_advance_existing_and_mapped_note_mods(self):
        create_book(self.target,self.mapping)
        with c.connect(self.target,readonly=True) as db:
            component=db.execute("select c.id from components c join words w on w.id=c.word_id where w.surface='train' and c.name='SimpleDefinition'").fetchone()[0]
        mods=[];expected='训练'
        with patch('anki_pipeline.study_catalog_anki.time.time',return_value=1_800_000_000):
            for index,text in enumerate(('修订一','修订二','训练')):
                c.edit_component(self.target,component,text,expected=expected,reason='同秒修订验证',backups=self.root/'backups')
                this={}
                for book in ('one','future'):
                    path=self.root/f'{book}-same-second-{index}.apkg';export_book(self.target,book,path)
                    with zipfile.ZipFile(path) as archive:
                        native=sqlite3.connect(':memory:')
                        try:
                            native.deserialize(archive.read('collection.anki2'))
                            mod,fields=native.execute("select mod,flds from notes where sfld='train'").fetchone()
                            self.assertIn(text,fields);this[book]=mod
                        finally:native.close()
                mods.append(this);expected=text
        for book in ('one','future'):
            self.assertGreater(mods[1][book],mods[0][book])
            self.assertGreater(mods[2][book],mods[1][book])
