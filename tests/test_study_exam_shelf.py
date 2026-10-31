import unittest
from anki_pipeline.study_exam_shelf import append_entry

class ShelfTests(unittest.TestCase):
    def entry(self, source, **changes):
        data=dict(identity='exam-one',title='真题 <测试>',subtitle='每题一卡',subject='政治',stats='794 张卡',browse='/exam/index.html',papers='/exam/papers/index.html',package='/exam/complete.apkg');data.update(changes);return append_entry(source,**data)

    def test_idempotent_preserves_existing_english_cards_and_scripts(self):
        original='<article data-study-book="redbook">原书</article><script src="old.js"></script><details id="home-help">帮助</details>'
        first=self.entry(original);self.assertEqual(self.entry(first),first);self.assertIn(original.split('<details')[0],first)
        self.assertEqual(first.count('data-study-book="redbook"'),1);self.assertNotIn('data-study-book="exam-one"',first);self.assertIn('真题 &lt;测试&gt;',first)

    def test_external_and_parent_traversal_urls_rejected(self):
        for url in ['https://example.com/a','//example.com/a','/exam/../private','/exam/%2e%2e/private']:
            with self.subTest(url=url),self.assertRaises(ValueError):self.entry('<details id="home-help">',browse=url)
