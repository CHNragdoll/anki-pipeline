import unittest
from anki_pipeline.study_catalog_presentation import _dynamic_reference, rewrite_field_references

class RuntimeReferenceTests(unittest.TestCase):
    def test_source_metadata_comparison_is_not_resource_assignment(self):
        for text in ('o.image.src===options[0].image.src', 'a.src == b.src', 'a.href===b.href'):
            with self.subTest(text=text):
                self.assertFalse(_dynamic_reference(text))
                self.assertEqual(rewrite_field_references('<script>'+text+'</script>',{'figure.svg':'../media/figure.svg'}),'<script>'+text+'</script>')

    def test_dynamic_resource_assignments_remain_guarded(self):
        for text in ('image.src=source', 'link.href = value', 'image.src=base+name'):
            with self.subTest(text=text):
                self.assertTrue(_dynamic_reference(text))
                with self.assertRaisesRegex(ValueError,'explicit dependency'):
                    rewrite_field_references('<script>'+text+'</script>',{'figure.svg':'../media/figure.svg'})
