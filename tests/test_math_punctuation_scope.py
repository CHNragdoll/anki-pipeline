import unittest
from anki_pipeline.study_exam_source import _halfwidth_display_text
class PunctuationScope(unittest.TestCase):
 def test_only_requested_prose_punctuation_changes(self):
  self.assertEqual(_halfwidth_display_text('<p>条件，成立：对；“保留”（括号）【答案】。</p>'),'<p>条件, 成立：对；“保留”（括号）【答案】.</p>')
 def test_protected_source_survives(self):
  for text in [r'<p>\(\text{a,b}\)</p>',r'<p>\[a,b\]</p>','<p>$$a,b$$</p>','<p>$a,b$</p>','<pre>printf("a,b");</pre>','<div class="code">a,b</div>','<span hidden>{"x":"a,b"}</span>']:
   with self.subTest(text=text):self.assertEqual(_halfwidth_display_text(text),text)

 def test_source_choice_labels_normalize_both_parentheses(self):
  from anki_pipeline.study_exam_reflow import markup
  for label in ['(A)', '（A）']:
   source = '<div class="math-option"><span class="math-option-label">'+label+'</span><span>题文，保留。</span></div>'
   self.assertIn('<b>A.</b>', _halfwidth_display_text(markup(source)))
