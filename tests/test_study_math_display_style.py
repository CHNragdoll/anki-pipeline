import unittest
from anki_pipeline.study_catalog_math import displaystyle_markup
from anki_pipeline.study_exam_package import CSS

class StyleTests(unittest.TestCase):
    def test_visible_math_only_and_idempotent(self):
        source = r'<p>\(x\) \[y\] \(  \displaystyle z\)</p><script>"\\("</script><b title="\(a\)">A</b>'
        result=displaystyle_markup(source)
        self.assertEqual(result.count('displaystyle'),3)
        self.assertEqual(result,displaystyle_markup(result))
        self.assertIn(r'title="\(a\)"',result)
        self.assertIn(r'<script>"\\("</script>',result)
    def test_choice_center_rule(self):
        self.assertIn('.exam-body .choice{align-items:center}',CSS)
        self.assertIn('.exam-body .choice>b{align-self:center}',CSS)

    def test_quoted_greater_than_attribute_is_unchanged(self):
        source=r'<span data-source="a > \(x\)">\(y\)</span><style>.a:after{content:"\(z\)"}</style>'
        result=displaystyle_markup(source)
        self.assertIn(r'data-source="a > \(x\)"',result)
        self.assertIn(r'\(\displaystyle y\)',result)
        self.assertIn(r'content:"\(z\)"',result)

    def test_matrix_row_before_parenthesis_is_not_a_delimiter(self):
        source=r'\(x=\begin{cases}a\\(1-b)\end{cases}\)'
        result=displaystyle_markup(source)
        self.assertEqual(result.count('displaystyle'),1)
        self.assertIn(r'\\(1-b)',result)
