import unittest
from anki_pipeline.study_exam_source import _halfwidth_display_text as normalize, _omit_standalone_question_number as omit
class CleanupTests(unittest.TestCase):
 def test_punctuation_and_labels(self):
  self.assertEqual(normalize('<p>（ ）。，：【解】</p><b>（A）</b>'),'<p>( ).,:[解]</p><b>A.</b>')
 def test_attributes_and_script_preserved(self):
  s='<p title="（原文）">，。</p><script>"（A）"</script>'
  self.assertEqual(normalize(s),'<p title="（原文）">,.</p><script>"（A）"</script>')
 def test_standalone_current_number_only(self):
  self.assertEqual(omit('<p>6.</p><table>数据</table>',6),'<table>数据</table>')
  for s in ['<p>6. 题干</p>','<p>7.</p>','<table><tr><td>6.</td></tr></table>']:
   self.assertEqual(omit(s,6),s)

 def test_label_lookalikes_protected(self):
  for s in ['<script>const x="<b>(A)</b>";</script>', '<style>.x:after{content:"<b>(B)</b>"}</style>', '<span data-source="<b>(C)</b>">x</span>']:
   self.assertEqual(normalize(s),s)
 def test_number_lookalike_in_attribute(self):
  s='<div title="><p>1.</p>">正文</div>'
  self.assertEqual(omit(s,1),s)
