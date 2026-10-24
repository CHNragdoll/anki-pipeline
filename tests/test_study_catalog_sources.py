import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import zipfile

import genanki
import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_import import import_package,import_sqlite_history
from anki_pipeline.study_catalog_sources import archive_records,bind_legacy,retain_catalogs
from tests import test_study_catalog_import as fixtures


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class SourceBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def test_catalog_extra_metadata_is_retained_as_exact_bytes(self):
        path=fixtures.CatalogImportTests.package(self,'one')
        data={'cards':[{'id':'card-'+w,'word':w,'position':i,'deckName':'one::词汇::Unit 01'}
                       for i,w in enumerate(('train','training'),1)],'extra_metadata':{'完整保留':['目录','备注']}}
        raw=(json.dumps(data,ensure_ascii=False,indent=3)+'\n').encode();catalog=self.root/'catalog.json';catalog.write_bytes(raw)
        import_package(self.target,path,book_id='one',title='one',edition=2027,catalog=catalog)
        manifest={'books':[{'id':'one','catalog':str(catalog)}]}
        retain_catalogs(self.target,manifest)
        with c.connect(self.target,readonly=True) as db:
            key=db.execute("select value from metadata where key='source.catalog.one'").fetchone()[0]
            self.assertEqual(key,hashlib.sha256(raw).hexdigest());self.assertEqual(c.get_object(db,key),raw)
        before=c.logical_digest(self.target);retain_catalogs(self.target,manifest)
        self.assertEqual(c.logical_digest(self.target),before)
        catalog.write_text('{}')
        with self.assertRaisesRegex(ValueError,'catalog changed'):retain_catalogs(self.target,manifest)

    def test_archived_real_is_readable_after_source_is_removed(self):
        source=self.root/'real.sqlite3'
        with sqlite3.connect(source) as native:
            native.execute('create table samples(value real)');native.execute('insert into samples values(1.25)')
        result=import_sqlite_history(self.target,source,kind='legacy');source.unlink()
        with c.connect(self.target,readonly=True) as db,db.transaction():
            self.assertEqual(list(archive_records(db,result['source_id'],'samples')),[{'value':1.25}])

    def test_legacy_binding_uses_exact_guid_and_retains_original_annotations(self):
        original=fixtures.CatalogImportTests.package(self,'one');path=self.root/'legacy-guid.apkg'
        with zipfile.ZipFile(original) as src,zipfile.ZipFile(path,'w') as dst:
            for name in src.namelist():
                raw=src.read(name)
                if name=='collection.anki2':
                    native=sqlite3.connect(':memory:')
                    try:
                        native.deserialize(raw)
                        native.execute("update notes set guid=? where sfld='train'",(genanki.guid_for('anki-rebuild-card-v1','stable-train'),))
                        native.commit();raw=native.serialize()
                    finally:native.close()
                dst.writestr(name,raw)
        import_package(self.target,path,book_id='one',title='one',edition=2027)
        source=self.root/'legacy.sqlite3';native=sqlite3.connect(source)
        try:
            native.executescript('create table cards(id text primary key,word text);create table sentences(id text,card_id text,annotation text);create table legacy_rows(card_id text,payload text);')
            native.execute("insert into cards values('stable-train','train')")
            native.execute("insert into sentences values('s1','stable-train','原审核完整说明')")
            native.commit()
        finally:native.close()
        result=import_sqlite_history(self.target,source,kind='legacy');source.unlink();path.unlink();original.unlink()
        self.assertEqual(bind_legacy(self.target)['bindings'],1)
        with c.connect(self.target,readonly=True) as db,db.transaction():
            self.assertEqual(db.execute('select source_card_id from notes where guid=%s',(genanki.guid_for('anki-rebuild-card-v1','stable-train'),)).fetchone()[0],'stable-train')
            self.assertEqual(list(archive_records(db,result['source_id'],'sentences'))[0]['annotation'],'原审核完整说明')
        before=c.logical_digest(self.target);bind_legacy(self.target)
        self.assertEqual(c.logical_digest(self.target),before)
