import html,json,unittest
from anki_pipeline.study_catalog_presentation import rewrite_field_references

class FieldRuntimeReferences(unittest.TestCase):
 def test_escaped_json_audit_is_byte_exact(self):
  data=html.escape(json.dumps({'source':'s.src=value; document.currentScript; "old.js"'}))
  source='<script src="old.js"></script><pre style="white-space:pre-wrap">'+data+'</pre>'
  self.assertEqual(rewrite_field_references(source,{'old.js':'new.js'}),source.replace('src="old.js"','src="new.js"'))
 def test_live_dynamic_script_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<script>s.src=value;</script>',{'old.js':'new.js'})
 def test_dynamic_after_data_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<pre>{&quot;data&quot;:1}</pre><script>s.src=value;</script>',{'old.js':'new.js'})
 def test_dynamic_pre_attribute_still_rejected(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<pre onclick="s.src=value;">{}</pre>',{'old.js':'new.js'})
 def test_markup_inside_pre_not_admitted(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<pre><script>s.src=value;</script></pre>',{'old.js':'new.js'})
 def test_non_json_pre_not_admitted(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<pre>s.src=value;</pre>',{'old.js':'new.js'})
 def test_script_string_cannot_hide_dynamic(self):
  with self.assertRaisesRegex(ValueError,'dynamic note'):
   rewrite_field_references('<script>var x=\'<pre>{}</pre>\';s.src=value;</script>',{'old.js':'new.js'})
 def test_unchanged_without_aliases(self):
  source='<script>s.src=value;</script>'
  self.assertEqual(rewrite_field_references(source,{}),source)
 def test_live_literal_reference_rewritten(self):
  self.assertEqual(rewrite_field_references('<script src="old.js"></script>',{'old.js':'new.js'}),'<script src="new.js"></script>')

if __name__=='__main__':unittest.main()
