import unittest
from anki_pipeline.study_exam_display import without_total_score
from anki_pipeline.study_catalog_navigation import note_navigation_metadata

class ScoreDisplayTests(unittest.TestCase):
    def test_remove_leading_total_preserve_number_and_question(self):
        for source in ['41. （本题13分）设有数组','41. ( 13 分 ) 设有数组','41．（本小题 13 分）设有数组']:
            with self.subTest(source=source):self.assertIn(without_total_score(source),['41. 设有数组','41．设有数组'])
        self.assertEqual(without_total_score('（本题13分）设有数组'),'设有数组')
    def test_retain_math_and_subquestion_marks(self):
        for source in ['(n ≥ 0) 求阶乘','设有数组。（1）说明思路（4分）','41. 求时间（13分）','41. （本题考查数组）设有数组']:
            self.assertEqual(without_total_score(source),source)
    def test_web_excerpt_clean_search_source_retained(self):
        raw='<p>41. （本题13分）设有数组；（1）说明思路（4分）。</p>'
        result=note_navigation_metadata({'field_names':['Question'],'fields':[raw]},question_mode=True)
        self.assertEqual(result['summary'],'41. 设有数组；（1）说明思路（4分）。')
        self.assertIn('本题13分',result['search_text'])
