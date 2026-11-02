import unittest
from anki_pipeline.study_politics_types import projected_question_type
from anki_pipeline.study_exam_source import question_type_labels

class PoliticsTypeTests(unittest.TestCase):
    def test_exact_nine_source_evidenced_questions(self):
        for year in (2003, 2004, 2005):
            for number in ('31', '32', '33'):
                self.assertEqual(projected_question_type('politics', year, {'number': number, 'sectionTitle': '三、辨析题'}, 'free_response'), 'discrimination')
        self.assertEqual(question_type_labels()['discrimination'], '辨析题')

    def test_neighbors_subjects_and_later_years_unchanged(self):
        for category, year, number, original in [('politics', 2003, '34', 'free_response'), ('politics', 2006, '31', 'multiple_choice'), ('math3', 2003, '31', 'free_response'), ('politics', 2004, '30', 'multiple_choice')]:
            self.assertEqual(projected_question_type(category, year, {'number': number, 'sectionTitle': '分析题'}, original), original)

    def test_missing_printed_evidence_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'section evidence'):
            projected_question_type('politics', 2003, {'number': '31', 'sectionTitle': '分析题'}, 'free_response')

class PoliticsPackageGroupingTests(unittest.TestCase):
    def test_source_package_has_separate_discrimination_group_without_new_guid(self):
        import copy, json, sqlite3, tempfile, zipfile
        from pathlib import Path
        from anki_pipeline.study_exam_package import source_package
        from tests.test_study_exam_refresh import snapshot
        value = snapshot([(2003, 31, 'available'), (2003, 34, 'available')])
        for row in value['questions']:
            row['type'] = 'free_response'
            row['source_record']['question']['questionType'] = 'free_response'
        original = copy.deepcopy(value)
        value['questions'][0].update(type='discrimination', type_label='辨析题', title='2003 · 辨析题 · 第 31 题')
        value['questions'][0]['source_record']['question_type_label'] = '辨析题'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_package(original, root/'old.apkg', book_id='politics-test', title='政治')
            source_package(value, root/'new.apkg', book_id='politics-test', title='政治')
            def read(path):
                with zipfile.ZipFile(path) as z:
                    db = sqlite3.connect(':memory:'); db.deserialize(z.read('collection.anki2'))
                return db
            before, after = read(root/'old.apkg'), read(root/'new.apkg')
            try:
                self.assertEqual(set(before.execute('SELECT guid FROM notes')), set(after.execute('SELECT guid FROM notes')))
                decks=json.loads(after.execute('SELECT decks FROM col').fetchone()[0])
                self.assertIn('政治::2003 年::辨析题', [d['name'] for d in decks.values()])
                self.assertIn('政治::2003 年::材料分析题', [d['name'] for d in decks.values()])
            finally: before.close(); after.close()
