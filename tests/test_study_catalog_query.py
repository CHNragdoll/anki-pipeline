import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_import import import_package,import_analysis
from anki_pipeline.study_catalog_normalize import import_analysis as batch_import_analysis
from anki_pipeline.study_catalog_query import frequency_report,word_report
from tests import test_study_catalog_import as fixtures


def record(book):
    english='train train trains';translation='火车、火车、火车'
    rows=[]
    for i,(start,end) in enumerate([(0,5),(6,11),(12,18)]):
        rows.append({'english':english,'translation':translation,'target_range':[start,end],
                     'english_hash':hashlib.sha256(english.encode()).hexdigest(),
                     'physical_source':{'paragraph':'one','paper':'2026-02'},'occurrence_id':'position-'+str(i),
                     'paper_id':'kaoyan:2026-02','sentence_id':'paragraph-one','sense_id':'train-n-1',
                     'status':'confirmed','reason':'此处指火车','method':'fixture','alignment':None})
    return {'book_id':book,'card_id':book+'-train','word':'train','snapshot_id':'fixture-'+book,
            'definition_source':'Oxford','definition_provenance':{'fixture':'exact'},'expected_occurrences':3,
            'senses':[{'ordinal':0,'sense_id':'train-n-1','pos':'n.','text':'火车'}],'occurrences':rows}


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class CatalogQueryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        for book in ('one','two'):
            path=fixtures.CatalogImportTests.package(self,book)
            import_package(self.target,path,book_id=book,title=book,edition=2027)
            path.unlink()

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def test_same_paragraph_counts_three_positions_and_other_book_does_not_double_global_total(self):
        with c.connect(self.target) as db,c.transaction(db):
            for book in ('one','two'):
                batch_import_analysis(db,record(book))
                db.execute('update notes set source_card_id=%s where book_id=%s and word_id=%s',
                           (book+'-train',book,c.identity('word','en','train')))
        result=frequency_report(self.target,word='train')
        self.assertEqual(result['physical_occurrences'],3)
        self.assertEqual([x['physical_occurrences'] for x in result['books']],[3,3])
        self.assertEqual(len(word_report(self.target,'train')['dictionary_senses']),1)
        create_book(self.target,{'schema':'study-book-map.v1','id':'future','title':'Future','edition':2028,
                                'units':[{'name':'Unit 01','words':[{'word':'train','from_book':'one'}]}]})
        self.assertEqual(frequency_report(self.target,word='train',book_id='future')['physical_occurrences'],3)
        self.assertEqual(frequency_report(self.target,word='train')['physical_occurrences'],3)

    def test_missing_analysis_is_not_reported_as_zero_occurrences(self):
        result=frequency_report(self.target,word='training')
        self.assertEqual(result['data_status'],'not_normalized')
        self.assertIsNone(result['physical_occurrences'])

    def test_copy_normalization_matches_original_adapter_exactly(self):
        before=c.logical_digest(self.target)
        with c.connect(self.target) as db:
            with db.transaction(force_rollback=True):
                import_analysis(db,record('one'))
                original={table:list(c._rows(db,table)) for table in c.TABLES}
        self.assertEqual(c.logical_digest(self.target),before)
        with c.connect(self.target) as db,c.transaction(db):
            batch_import_analysis(db,record('one'))
            actual={table:list(c._rows(db,table)) for table in c.TABLES}
        self.assertEqual(actual,original)
