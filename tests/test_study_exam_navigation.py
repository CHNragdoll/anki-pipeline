import unittest
from anki_pipeline.study_catalog_navigation import note_navigation_metadata
from anki_pipeline.study_catalog_web import navigation_index

class ExamNavigationTests(unittest.TestCase):
    def test_question_summary_does_not_reveal_answer(self):
        note={'field_names':['Title','Question','Answer'],'fields':['第一题','<p>题目材料</p>','<p>秘密答案</p>']}
        row=note_navigation_metadata(note,question_mode=True);self.assertIn('题目材料',row['summary']);self.assertNotIn('秘密答案',row['summary'])

    def test_exam_kind_is_explicit_navigation_metadata(self):
        cat={'scope':{'kind':'exam-questions'},'cards':[{'id':'one','word':'第一题','unit':'真题::2023','url':'cards/one.html'}]}
        self.assertEqual(navigation_index(cat)['content_kind'],'exam-questions')

    def test_long_material_can_be_searched_without_indexing_the_answer(self):
        note={'field_names':['Title','Question','Answer'],'fields':['材料题','<p>'+('材料文字'*160)+'末尾检索词</p>','秘密答案']}
        row=note_navigation_metadata(note,question_mode=True)
        self.assertNotIn('末尾检索词',row['summary'])
        self.assertIn('末尾检索词',row['search_text'])
        self.assertNotIn('秘密答案',row['search_text'])
        cat={'scope':{'kind':'exam-questions'},'cards':[{'id':'q','word':'材料题','unit':'真题::2023','url':'cards/q.html'}]}
        self.assertIn('末尾检索词',navigation_index(cat,{'cards':{'q':row}})['search_text']['q'])
