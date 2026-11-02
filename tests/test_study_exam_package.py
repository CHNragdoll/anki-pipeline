import json
from contextlib import closing
import sqlite3
import zipfile
from tests import test_study_exam_source as fixtures
from anki_pipeline.study_exam_package import source_package

class ExamPackageTests(fixtures.ExamSourceTests):
    def package(self, name='source.apkg'):
        out=self.root/name;report=source_package(self.read(),out,book_id='exam-fixture',title='真题测试')
        with zipfile.ZipFile(out) as archive:
            db=sqlite3.connect(':memory:');db.deserialize(archive.read('collection.anki2'));media=json.loads(archive.read('media'));raw_media={name:archive.read(key) for key,name in media.items()}
        return report,db,raw_media

    def test_fields_native_identity_and_resources_remain_complete(self):
        report,db,media=self.package();fields=db.execute('select flds from notes').fetchone()[0].split('\x1f');models=json.loads(db.execute('select models from col').fetchone()[0]);model=next(iter(models.values()))
        self.assertIn('完整答案要点',fields[2]);self.assertNotIn('完整答案要点',fields[1]);self.assertEqual(len(media),1)
        self.assertTrue(model['tmpls'][0]['afmt'].startswith('{{FrontSide}}'));self.assertNotIn('回看本题',model['tmpls'][0]['afmt']);self.assertNotIn('真题练习',model['tmpls'][0]['qfmt']);self.assertIn('exam-location',model['tmpls'][0]['qfmt']);self.assertIn('exam-choice-interactive',model['tmpls'][0]['qfmt']);self.assertIn('查看答案',model['tmpls'][0]['qfmt']);self.assertNotIn('清除选择',model['tmpls'][0]['qfmt']);self.assertNotIn('已选：',model['tmpls'][0]['qfmt']);self.assertNotIn('{{Answer}}',model['tmpls'][0]['qfmt']);self.assertIn('{{Answer}}',model['tmpls'][0]['afmt']);self.assertEqual(report['cards'],1)
        _,second,_=self.package('second.apkg');self.assertEqual(db.execute('select guid from notes').fetchone(),second.execute('select guid from notes').fetchone());db.close();second.close()

    def test_math_fill_blank_uses_shared_package_and_retains_math(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE questions SET question_type='fill_blank'")
            db.execute("UPDATE source_blocks SET content_html=? WHERE id='stem'", (r'<p>计算 \(\int_0^1 x\,dx\) = ____。</p>',))
        snapshot=self.read(type_labels={'free_response':'解答题'})
        self.assertEqual(snapshot['questions'][0]['type_label'],'填空题')
        path=self.root/'math.apkg'
        source_package(snapshot,path,book_id='math3-exams',title='考研数学三历年真题')
        with zipfile.ZipFile(path) as archive:
            with closing(sqlite3.connect(':memory:')) as db:
                db.deserialize(archive.read('collection.anki2'))
                decks=json.loads(db.execute('select decks from col').fetchone()[0])
                self.assertIn('考研数学三历年真题::2023 年::填空题',{v['name'] for v in decks.values()})
                fields=db.execute('select flds from notes').fetchone()[0].split('\x1f')
                self.assertIn(r'\int_0^1',fields[1])
                self.assertIn('完整答案要点',fields[2])

    def test_missing_answer_is_retained_and_default_suspended(self):
        with closing(sqlite3.connect(self.db)) as source, source:source.execute('delete from answers')
        report,db,_=self.package();self.assertEqual(report['missing_answer_suspended'],1);self.assertEqual(db.execute('select count(*) from cards').fetchone()[0],1);self.assertEqual(db.execute('select queue from cards').fetchone()[0],-1);db.close()

    def test_custom_type_label_controls_title_deck_and_refresh_metadata(self):
        snapshot=self.read(type_labels={'free_response':'综合应用题'})
        path=self.root/'custom.apkg'
        source_package(snapshot,path,book_id='exam-fixture',title='408')
        with zipfile.ZipFile(path) as archive:
            db=sqlite3.connect(':memory:');db.deserialize(archive.read('collection.anki2'))
        try:
            names=[r['name'] for r in json.loads(db.execute('SELECT decks FROM col').fetchone()[0]).values()]
            self.assertIn('408::2023 年::综合应用题',names)
            self.assertFalse(any('材料分析题' in name for name in names))
            fields=db.execute('SELECT flds FROM notes').fetchone()[0].split('\x1f')
            import html
            self.assertIn('综合应用题',fields[0])
            self.assertEqual(json.loads(html.unescape(fields[-1]))['question_type_label'],'综合应用题')
            _,default,_=self.package('default-label.apkg')
            try:self.assertEqual(db.execute('SELECT guid FROM notes').fetchone(),default.execute('SELECT guid FROM notes').fetchone())
            finally:default.close()
        finally:db.close()

    def test_conflicting_type_labels_cannot_change_refresh_grouping(self):
        snapshot=self.read(type_labels={'free_response':'综合应用题'})
        snapshot['questions'][0]['source_record']['question_type_label']='材料分析题'
        with self.assertRaisesRegex(ValueError,'source record and type label'):
            source_package(snapshot,self.root/'conflicting.apkg',book_id='exam-fixture',title='408')
        self.assertFalse((self.root/'conflicting.apkg').exists())
