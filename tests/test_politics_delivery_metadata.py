"""Metadata-only political-deck updates preserve existing study rows and media."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from scripts.add_politics_guide import build, ROOT, GUID, NOTE_ID, CARD_ID
from scripts.rename_apkg_root import rename_root


class PoliticsDeliveryMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        db = self.root / 'source.sqlite'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE col(models text, decks text)')
            c.execute('CREATE TABLE notes(id integer primary key,guid text,mid integer,mod integer,usn integer,tags text,flds text,sfld text,csum integer,flags integer,data text)')
            c.execute('CREATE TABLE cards(id integer primary key,nid integer,did integer,ord integer,mod integer,usn integer,type integer,queue integer,due integer,ivl integer,factor integer,reps integer,lapses integer,left integer,odue integer,odid integer,flags integer,data text)')
            c.execute('CREATE TABLE revlog(id integer primary key,cid integer)')
            c.execute('CREATE TABLE graves(usn integer,oid integer,type integer)')
            model = {'id':1,'name':'question','flds':[{'name':'Question','ord':0}],
                     'tmpls':[{'name':'Card','ord':0,'qfmt':'{{Question}}','afmt':'{{Question}}'}]}
            decks = {'1':{'id':1,'name':ROOT+'::2024 年::单选题','conf':1}}
            c.execute('INSERT INTO col VALUES (?,?)',(json.dumps({'1':model}),json.dumps(decks)))
            c.executemany('INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                          [(i,'question-'+str(i),1,10,-1,' flag ','Question '+str(i),'Question',0,0,'') for i in range(1,833)])
            c.executemany('INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          [(i,i,1,0,10,-1,2,-1,i,32,2500,5,1,0,0,0,3,'') for i in range(1,833)])
            c.execute('INSERT INTO revlog VALUES (9,1)')
            c.execute('INSERT INTO graves VALUES (-1,999,0)')
        self.source = self.root/'source.apkg'
        with zipfile.ZipFile(self.source,'w',compression=zipfile.ZIP_DEFLATED) as z:
            z.write(db,'collection.anki2');z.writestr('media','{"0":"fixture.svg"}');z.writestr('0','<svg/>')
        self.source_bytes=self.source.read_bytes()

    def read(self,path):
        with zipfile.ZipFile(path) as z:
            db=self.root/'inspect.sqlite';db.write_bytes(z.read('collection.anki2'))
        return sqlite3.connect(db)

    def test_guide_adds_only_one_stable_card_and_its_own_deck(self):
        destination=self.root/'guide.apkg'
        result=build(self.source,destination)
        self.assertEqual(result['cards'],833)
        with self.read(destination) as c:
            self.assertEqual(c.execute('SELECT guid FROM notes WHERE id=?',(NOTE_ID,)).fetchone()[0],GUID)
            self.assertEqual(c.execute('SELECT count(*) FROM cards WHERE id=?',(CARD_ID,)).fetchone()[0],1)
            names=[d['name'] for d in json.loads(c.execute('SELECT decks FROM col').fetchone()[0]).values()]
            self.assertIn(ROOT+'::00 使用说明',names)
            self.assertEqual(c.execute('SELECT * FROM revlog').fetchall(),[(9,1)])
            self.assertEqual(c.execute('SELECT queue,reps,flags FROM cards WHERE id=1').fetchone(),(-1,5,3))
        self.assertEqual(self.source.read_bytes(),self.source_bytes)
        with self.assertRaises(ValueError):build(self.source,destination)
        with self.assertRaises(AssertionError):build(destination,self.root/'duplicate.apkg')
        self.assertFalse((self.root/'duplicate.apkg').exists())

    def test_rename_preserves_existing_rows_and_handles_missing_root(self):
        destination=self.root/'renamed.apkg'
        result=rename_root(self.source,destination,ROOT,'考研政治测试')
        self.assertEqual(result['renamed_decks'],1)
        with self.read(destination) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM cards').fetchone()[0],832)
            self.assertEqual(json.loads(c.execute('SELECT decks FROM col').fetchone()[0])['1']['name'],'考研政治测试::2024 年::单选题')
        self.assertEqual(self.source.read_bytes(),self.source_bytes)
        with self.assertRaises(ValueError):rename_root(self.source,self.root/'missing.apkg','不存在','new')
        self.assertFalse((self.root/'missing.apkg').exists())
        with self.assertRaises(ValueError):rename_root(self.source,self.source,ROOT,'new')


if __name__=='__main__': unittest.main()
