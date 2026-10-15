import hashlib
import os
import unittest
import uuid

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_archive import write_batch


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class CatalogArchiveTests(unittest.TestCase):
    def setUp(self):
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex);c.initialize(self.target)
        with c.connect(self.target) as db,c.transaction(db):
            key=c.put_json(db,{'sealed':'test'})
            db.execute("insert into sources values('fixture','legacy','fixture',%s,'building')",(key,))
            db.execute("insert into archive_tables values('fixture','original',%s,%s,0,null)",(key,key))

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))

    def test_copy_batches_preserve_original_rows_hashes_and_resume_order(self):
        rows=[(i,'完整原记录\n'*600,b'\x00\xff',None,1.25) for i in range(70)]
        digest=hashlib.sha256();expected=hashlib.sha256()
        with c.connect(self.target) as db:
            for start in (0,35):
                with c.transaction(db):
                    end=write_batch(db,'fixture','original',start,rows[start:start+35],digest)
                self.assertEqual(end,start+35)
            actual=db.execute("select payload_id from archive_rows where source_id='fixture' order by ordinal").fetchall()
            for source,(key,) in zip(rows,actual):
                raw=c.canonical([c._pack_cell(v) for v in source]).encode()
                expected.update(raw+b'\n')
                self.assertEqual(key,hashlib.sha256(raw).hexdigest())
                self.assertEqual(c.get_object(db,key),raw)
        self.assertEqual(digest.hexdigest(),expected.hexdigest())

    def test_failed_batch_rolls_back_objects_and_resume_rows_together(self):
        with c.connect(self.target) as db:
            before=db.execute('select count(*) from objects').fetchone()[0]
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                with c.transaction(db):write_batch(db,'missing','original',0,[(1,'new data')],hashlib.sha256())
            self.assertEqual(db.execute('select count(*) from objects').fetchone()[0],before)
            self.assertEqual(db.execute('select count(*) from archive_rows').fetchone()[0],0)
