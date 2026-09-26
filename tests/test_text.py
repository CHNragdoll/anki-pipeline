import unittest

from anki_pipeline.text import (
    assess_translation,
    matches_word,
    parse_numbered_entries,
    parse_translations,
    stable_sentence_id,
    strip_markup,
    word_variants,
)


class TextTests(unittest.TestCase):
    def test_legacy_prefix_false_positives_are_excluded(self):
        # The V2.0 prefix regex reduced rate -> rat, theme -> them, fee -> fe.
        for word, false_hit in (("rate", "rather rat"), ("theme", "them"), ("fee", "feel")):
            with self.subTest(word=word):
                self.assertFalse(matches_word(word, false_hit))

    def test_regular_and_explicit_forms(self):
        self.assertTrue({"rate", "rates", "rated", "rating"} <= word_variants("rate"))
        self.assertTrue(matches_word("rate", "She rated it highly."))
        self.assertTrue(matches_word("child", "The children read.", extra=("children",)))
        self.assertFalse(matches_word("rate", "A ratio system."))
        self.assertFalse(matches_word("fee", "fees_extra"))
        self.assertFalse(matches_word("fee", "123fees"))
        self.assertTrue(matches_word("catalogue\n(美catalog)", "The catalogues were filed."))
        self.assertFalse(matches_word("catalogue\n(美catalog)", "The catalog was filed."))
        self.assertFalse(matches_word("rate", "ratified", extra=("rat*",)))

    def test_markup_is_plain_text(self):
        self.assertEqual(strip_markup("<p>A &amp; <b>B</b><script>bad()</script></p>"), "A & B")
        self.assertTrue(matches_word("theme", "<b>themes</b> matter"))

    def test_sentence_id_ignores_markup_and_whitespace(self):
        first = stable_sentence_id("Rate", "A <b>rate</b> rises.\n", "2020年  ➫ Text 1")
        second = stable_sentence_id("rate", "A rate rises.", "2020年 ➫ Text 1")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertNotEqual(first, stable_sentence_id("rate", "A rate rises.", "2021年 ➫ Text 1"))

    def test_parse_legacy_and_merged_without_duplicate_sentence(self):
        blob = (
            "[1] A <b>rate</b> rises.\n"
            "2020年 ➫ Section II ➫ Text 1\n\n"
            "[2] A theme matters.\n"
            "2021年 ➫ Text 2"
        )
        self.assertEqual(parse_numbered_entries(blob), [
            {"number": 1, "text": "A rate rises.", "source": "2020年 ➫ Section II ➫ Text 1"},
            {"number": 2, "text": "A theme matters.", "source": "2021年 ➫ Text 2"},
        ])
        merged = "[1] A rate rises.\n[1] 比率上涨。\n2020年 ➫ Text 1\n[1] A rate rises."
        self.assertEqual(parse_numbered_entries(merged), [
            {"number": 1, "text": "A rate rises.", "source": "2020年 ➫ Text 1"}
        ])

    def test_conflicting_numbered_english_raises(self):
        with self.assertRaises(ValueError):
            parse_numbered_entries("[1] First sentence.\n[1] Different sentence.")

    def test_parse_multiline_translations_and_conflicts(self):
        self.assertEqual(parse_translations("[1] 第一行\n第二行\n\n[2] 第二句"),
                         {1: "第一行\n第二行", 2: "第二句"})
        self.assertEqual(parse_translations("[1] 相同\n[1] 相同"), {1: "相同"})
        with self.assertRaises(ValueError):
            parse_translations("[1] 第一版\n[1] 第二版")

    def test_translation_assessment_is_conservative(self):
        self.assertEqual(assess_translation("正常的完整译文。"), "")
        self.assertEqual(assess_translation("诗意未尽，"), "translation appears incomplete")
        self.assertEqual(assess_translation("  "), "missing translation")
        self.assertEqual(assess_translation("待翻译"), "placeholder translation")


if __name__ == "__main__":
    unittest.main()
