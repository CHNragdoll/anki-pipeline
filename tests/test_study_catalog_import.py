import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import genanki
import psycopg
from psycopg import sql
from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_import import import_package,import_sqlite_history


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class CatalogImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex);c.initialize(self.target)

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def package(self,book):
        names=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']
        model=genanki.Model(1234,'Shared test model',fields=[{'name':n} for n in names],templates=[{'name':'Card','qfmt':'{{Word}}','afmt':'{{Definition}} {{SimpleDefinition}} {{Examples}}'}])
        deck=genanki.Deck(2000 if book=='one' else 2001,book+'::词汇::Unit 01')
        for index,word in enumerate(['train','training']):
            fields=[word,'','完整释义','训练','','','[sound:recording.mp3]','original examples','词汇 Unit 01 ➫ '+str(index+1),'']
            deck.add_note(genanki.Note(model=model,fields=fields,guid=genanki.guid_for(book,word)))
        audio=self.root/'recording.mp3';audio.write_bytes(b'original immutable media bytes')
        package=genanki.Package(deck);package.media_files=[str(audio)];path=self.root/f'{book}.apkg';package.write_to_file(str(path));return path

    def test_two_books_share_content_keep_identities_and_idempotent_import(self):
        first=self.package('one');second=self.package('two')
        before=hashlib.sha256(first.read_bytes()).hexdigest()
        for book,path in [('one',first),('two',second)]:
            import_package(self.target,path,book_id=book,title=book,edition=2027)
        self.assertTrue(import_package(self.target,first,book_id='one',title='one',edition=2027)['already_imported'])
        for title,edition in [('different',2027),('one',2028)]:
            with self.assertRaisesRegex(ValueError,'another edition/title'):
                import_package(self.target,first,book_id='one',title=title,edition=edition)
        self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),before)
        with c.connect(self.target,readonly=True) as db:
            self.assertEqual(db.execute('select count(*) from words').fetchone()[0],2)
            self.assertEqual(db.execute('select count(*) from notes').fetchone()[0],4)
            self.assertEqual(db.execute('select count(distinct object_id) from resource_aliases').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from resource_aliases').fetchone()[0],2)
            self.assertEqual(db.execute("select count(*) from components where name='SimpleDefinition'").fetchone()[0],2)
            for book,path in [('one',first),('two',second)]:
                with zipfile.ZipFile(path) as z:
                    original=sqlite3.connect(':memory:');original.deserialize(z.read('collection.anki2'))
                    for nid,guid,fields in original.execute('select id,guid,flds from notes'):
                        self.assertEqual(c.note_fields(db,book,nid),fields.split('\x1f'))
                        self.assertEqual(db.execute('select guid from notes where book_id=%s and note_id=%s',(book,nid)).fetchone()[0],guid)
                    original.close()

    def test_archive_retains_all_rows_including_binary_and_repeat_is_noop(self):
        path=self.root/'legacy.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('create table original(id integer primary key,text text,binary blob)')
            db.executemany('insert into original values(?,?,?)',[(1,'旧审核',b'\0\xff'),(2,'未确定',b'exact')])
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        result=import_sqlite_history(self.target,path,kind='legacy')
        self.assertEqual(result['tables'],{'original':2})
        self.assertTrue(import_sqlite_history(self.target,path,kind='legacy')['already_imported'])
        with c.connect(self.target,readonly=True) as db:
            rows=[c.get_json(db,r[0]) for r in db.execute('select payload_id from archive_rows order by ordinal')]
            self.assertEqual(c._unpack_cell(rows[0][2]),b'\0\xff')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_bad_seal_and_ambiguous_mapping_write_no_book(self):
        path=self.package('one')
        with self.assertRaises(ValueError):import_package(self.target,path,book_id='bad',title='bad',edition=2027,expected_sha='0'*64)
        with c.connect(self.target,readonly=True) as db:self.assertEqual(db.execute('select count(*) from books').fetchone()[0],0)

    def test_modern_package_uses_real_collection_and_retains_compatibility_stub(self):
        original=self.package('one');modern=self.root/'modern.apkg'
        with zipfile.ZipFile(original) as src,zipfile.ZipFile(modern,'w') as dst:
            for name in src.namelist():
                if name!='collection.anki2':dst.writestr(name,src.read(name))
            raw=src.read('collection.anki2');db=sqlite3.connect(':memory:');db.deserialize(raw)
            db.execute('delete from cards where nid=(select max(id) from notes)');db.execute('delete from notes where id=(select max(id) from notes)');db.commit()
            dst.writestr('collection.anki2',db.serialize());dst.writestr('collection.anki21',raw);dst.writestr('meta',b'\x08\x02');db.close()
        result=import_package(self.target,modern,book_id='modern',title='modern',edition=2027)
        self.assertEqual(result['notes'],2)
        with c.connect(self.target,readonly=True) as db:
            source=c.get_json(db,db.execute('select manifest_id from sources').fetchone()[0])
            self.assertEqual(source['collection_entry'],'collection.anki21')
            self.assertEqual(c.get_object(db,source['extra_members']['meta']['object_id']),b'\x08\x02')
            self.assertIn('collection.anki2',source['extra_members'])

    def test_low_storage_retains_explicit_incomplete_source_and_can_resume(self):
        path=self.root/'guarded.sqlite3';db=sqlite3.connect(path)
        try:
            db.execute('create table original(id integer,text text)');db.execute("insert into original values(1,'完整内容')");db.commit()
        finally:db.close()
        before=hashlib.sha256(path.read_bytes()).hexdigest()
        with patch('anki_pipeline.study_catalog_import.shutil.disk_usage',return_value=SimpleNamespace(free=1)),patch('anki_pipeline.study_catalog_import.important_capacity',return_value=None):
            with self.assertRaises(OSError):import_sqlite_history(self.target,path,kind='legacy',space_guard=self.root)
        with c.connect(self.target,readonly=True) as db:
            self.assertEqual(db.execute('select count(*) from archive_rows').fetchone()[0],0)
            self.assertEqual(db.execute('select status from sources').fetchone()[0],'building')
        result=import_sqlite_history(self.target,path,kind='legacy',space_guard=self.root,min_free_bytes=1)
        self.assertEqual(result['tables'],{'original':1})
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_macos_reclaimable_capacity_is_used_by_the_storage_guard(self):
        from anki_pipeline.study_catalog_import import capacity_guard
        with patch('anki_pipeline.study_catalog_import.shutil.disk_usage',return_value=SimpleNamespace(free=1)),patch('anki_pipeline.study_catalog_import.important_capacity',return_value=90_000_000_000):
            capacity_guard(self.root,2*1024**3)


if __name__=='__main__':unittest.main()
