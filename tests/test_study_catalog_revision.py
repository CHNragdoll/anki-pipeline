from copy import deepcopy
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

from anki_pipeline import study_catalog as c,sense_frequency as sf
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_normalize import import_analysis
from anki_pipeline.study_catalog_query import frequency_report
from anki_pipeline.study_catalog_revision import amend_decision
from tests.test_sense_frequency import aligned_record,reseal


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires isolated PostgreSQL test connection')
class SharedFactRevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        self.before={};self.definitions={}
        for index,book in enumerate(('one','two')):
            raw=aligned_record();raw['book_id']=book;raw['card_id']=book+'-novel';record=sf.prepare_record(reseal(raw))
            definition='<header data-original-dictionary="yes">完整词典详细解释</header>'+sf.render_report(sf.report_from_record(record))+'<footer>原来源与补充释义</footer>'
            definition=definition.replace('</article>','<details class="sf-source-confirmation-history"><summary>完整原审核</summary><p>全部内容、旧版本说明都保留</p></details></article>',1)
            model=genanki.Model(7211,'shared semantics',fields=[{'name':'Word'},{'name':'Definition'},{'name':'Examples'}],
                templates=[{'name':'Card','qfmt':'{{Word}}','afmt':'{{Definition}} {{Examples}}'}])
            deck=genanki.Deck(7212+index,book)
            deck.add_note(genanki.Note(model=model,fields=['novel',definition,'原例句、跳转和音频标签']))
            path=self.root/(book+'.apkg');genanki.Package(deck).write_to_file(str(path))
            import_package(self.target,path,book_id=book,title=book,edition=2027);path.unlink()
            with c.connect(self.target) as db,c.transaction(db):
                import_analysis(db,record);db.execute('update notes set source_card_id=%s where book_id=%s',(record['card_id'],book))
            self.before[book]=record;self.definitions[book]=definition
        create_book(self.target,{'schema':'study-book-map.v1','id':'future','title':'Future','edition':2028,
            'scope':{'subject':'英语','exam':'IELTS'},'units':[{'name':'Unit 01','items':[{'word':'novel','from_book':'one'}]}]})

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def request(self):
        with c.connect(self.target,readonly=True) as db:
            expected={b+'/'+card:rid for b,card,rid in db.execute('select book_id,source_card_id,record_id from analyses')}
            sense=db.execute("select sense_id from analysis_senses where book_id='one' and ordinal=0").fetchone()[0]
        physical=next(r['occurrence_id'] for r in self.before['one']['occurrences'] if r['sense_id']==self.before['one']['senses'][1]['sense_id'])
        return dict(word='novel',physical_id=physical,sense_id=sense,reason='一次公共审核，所有引用同步',expected=expected,backups=self.root/'backups')

    def test_one_fact_revision_updates_queries_apkg_and_web_and_keeps_complete_source_articles(self):
        self.assertEqual(frequency_report(self.target,word='novel')['physical_occurrences'],2)
        result=amend_decision(self.target,**self.request());self.assertEqual(len(result['changes']),2)
        report=frequency_report(self.target,word='novel')
        self.assertEqual(report['physical_occurrences'],2)
        self.assertEqual([x['physical_occurrences'] for x in report['books']],[2,2,2])
        self.assertTrue(all(x['physical_occurrences']==2 for x in report['senses_by_book']))
        for book in ('one','two','future'):
            apkg=self.root/(book+'-revised.apkg');export_book(self.target,book,apkg)
            with zipfile.ZipFile(apkg) as z:
                db=sqlite3.connect(':memory:')
                try:
                    db.deserialize(z.read('collection.anki2'));fields=db.execute('select flds from notes').fetchone()[0]
                finally:db.close()
            for marker in ('一次公共审核','完整词典详细解释','旧版本说明都保留','原例句、跳转和音频标签','sf-catalog-revision','card-chunk'):
                self.assertIn(marker,fields)
            folder=self.root/(book+'-web');export_book(self.target,book,folder,format='web')
            card=json.loads((folder/'catalog.json').read_text())['cards'][0]
            self.assertIn('一次公共审核',(folder/card['url']).read_text())

    def test_stale_scope_and_direct_html_edits_cannot_diverge_facts_from_body(self):
        request=self.request();request['expected'].pop('two/two-novel');before=c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError,'incomplete cross-book'):amend_decision(self.target,**request)
        self.assertEqual(c.logical_digest(self.target),before)
        with c.connect(self.target,readonly=True) as db:
            component=db.execute("select component_id from note_fields where book_id='one' and name='Definition'").fetchone()[0]
        with self.assertRaisesRegex(ValueError,'shared fact revision'):
            c.edit_component(self.target,component,'随意修改数字',expected=self.definitions['one'],reason='必须拒绝',backups=self.root/'backups')
        self.assertEqual(c.logical_digest(self.target),before)

    def test_late_compile_failure_rolls_back_every_book(self):
        with c.connect(self.target) as db:
            key=db.execute("select component_id from note_fields where book_id='two' and name='Definition'").fetchone()[0]
            db.execute('update components set current_id=%s where id=%s',(c.put_object(db,b'broken source'),key))
        before=c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError,'complete live physical articles'):amend_decision(self.target,**self.request())
        self.assertEqual(c.logical_digest(self.target),before)
