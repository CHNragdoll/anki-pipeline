"""Reviewed sentence alignments must never apply stale or imprecise offsets."""

from __future__ import annotations

import copy
import hashlib
import unittest
from html import escape

from anki_pipeline.translation_alignment import (
    TranslationAlignmentError,
    render_aligned_translation,
    validate_translation_alignment,
)


def payload(english, translation, alignments=()):
    return {
        "schema": "codex-sentence-alignment.v1",
        "englishHash": hashlib.sha256(english.encode("utf-8")).hexdigest(),
        "translationHash": hashlib.sha256(translation.encode("utf-8")).hexdigest(),
        "alignments": list(alignments),
    }


def equivalent(en, *zh):
    return {"en": list(en), "zh": [list(span) for span in zh],
            "relation": "equivalent"}


class TranslationAlignmentTests(unittest.TestCase):
    def test_valid_payload_is_not_modified(self):
        english, translation = "The rate rose.", "比率上升了。"
        alignment = payload(english, translation, [
            {"en": [0, 3], "zh": [], "relation": "implicit",
             "note": "The definite article has no separate Chinese token."},
            equivalent((4, 8), (0, 2)), equivalent((9, 13), (2, 5)),
        ])
        original = copy.deepcopy(alignment)
        self.assertIsNone(validate_translation_alignment(english, translation, alignment))
        self.assertEqual(alignment, original)

    def test_exact_word_highlights_only_its_translation(self):
        english, translation = "The rate rose.", "比率上升了。"
        alignment = payload(english, translation, [equivalent((4, 8), (0, 2))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(4, 8)]),
                         '<span class="term-highlight">比率</span>上升了。')

    def test_repeated_word_uses_selected_occurrence_offsets(self):
        english, translation = "The bank faces the river bank.", "银行面对河岸。"
        alignment = payload(english, translation, [
            equivalent((4, 8), (0, 2)), equivalent((25, 29), (4, 6)),
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(25, 29)]),
                         '银行面对<span class="term-highlight">河岸</span>。')
        self.assertEqual(render_aligned_translation(english, translation, alignment,
                                                  [(4, 8), (25, 29)]),
                         '<span class="term-highlight">银行</span>面对'
                         '<span class="term-highlight">河岸</span>。')

    def test_exact_pair_wins_over_smaller_and_larger_containing_phrases(self):
        english, translation = "They take off quickly.", "他们迅速起飞。"
        alignment = payload(english, translation, [
            equivalent((0, len(english)), (0, len(translation))),
            equivalent((5, 13), (2, 6)), equivalent((5, 9), (4, 6)),
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(5, 9)]),
                         '他们迅速<span class="term-highlight">起飞</span>。')

    def test_shortest_containing_phrase_supports_many_to_many(self):
        english, translation = "They take off quickly.", "他们迅速起飞。"
        alignment = payload(english, translation, [
            equivalent((0, len(english)), (0, len(translation))),
            equivalent((5, 13), (4, 6)), equivalent((5, 21), (2, 6)),
        ])
        for matched in ([(5, 9)], [(10, 13)], [(5, 9), (10, 13)], [(5, 13)]):
            with self.subTest(matched=matched):
                self.assertEqual(render_aligned_translation(english, translation, alignment, matched),
                                 '他们迅速<span class="term-highlight">起飞</span>。')

    def test_one_english_span_can_highlight_reordered_separate_chinese_spans(self):
        english, translation = "We firmly disagree.", "我们明确表示不同意，态度坚定。"
        alignment = payload(english, translation, [equivalent((3, 9), (12, 14), (2, 4))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(3, 9)]),
                         '我们<span class="term-highlight">明确</span>表示不同意，态度'
                         '<span class="term-highlight">坚定</span>。')

    def test_disjoint_chinese_spans_preserve_the_intervening_text(self):
        english, translation = "He never came.", "他既没来，也从未联络。"
        alignment = payload(english, translation, [equivalent((3, 8), (2, 3), (6, 8))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(3, 8)]),
                         '他既<span class="term-highlight">没</span>来，也'
                         '<span class="term-highlight">从未</span>联络。')

    def test_overlapping_and_duplicate_chinese_spans_do_not_repeat_text(self):
        english, translation = "The weather is good.", "今天的天气很好。"
        alignment = payload(english, translation, [
            equivalent((4, 11), (3, 5), (4, 6), (3, 5)),
            equivalent((15, 19), (5, 7)),
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment,
                                                  [(4, 11), (15, 19), (4, 11)]),
                         '今天的<span class="term-highlight">天气很好</span>。')

    def test_adjacent_chinese_spans_are_merged(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation, [equivalent((3, 8), (2, 3), (3, 4))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(3, 8)]),
                         '我们<span class="term-highlight">同意</span>。')

    def test_implicit_exact_pair_blocks_a_broader_equivalent_pair(self):
        english, translation = "They will depart tomorrow.", "他们明天出发。"
        alignment = payload(english, translation, [
            equivalent((5, 16), (2, 6)),
            {"en": [5, 9], "zh": [], "relation": "implicit",
             "note": "Future time is carried by the time adverb."},
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(5, 9)]),
                         translation)

    def test_untranslated_pair_does_not_force_a_highlight(self):
        english, translation = "Well, we agree.", "我们同意。"
        alignment = payload(english, translation, [
            {"en": [0, 4], "zh": [], "relation": "untranslated",
             "note": "The discourse marker is intentionally omitted."},
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(0, 4)]),
                         translation)

    def test_no_match_and_no_selected_ranges_only_escape_translation(self):
        english, translation = "We agree.", '<img src="x" onerror="alert(1)"> & 同意'
        alignment = payload(english, translation, [equivalent((0, 2), (0, 1))])
        for matches in ([], [(3, 8)]):
            with self.subTest(matches=matches):
                self.assertEqual(render_aligned_translation(english, translation, alignment, matches),
                                 escape(translation))

    def test_full_sentence_is_never_a_containing_fallback(self):
        english, translation = ' "We agree." ', "我们同意。"
        for en in ((0, len(english)), (2, 10)):
            with self.subTest(en=en):
                alignment = payload(english, translation, [equivalent(en, (0, len(translation)))])
                self.assertEqual(render_aligned_translation(english, translation, alignment, [(5, 10)]),
                                 translation)

    def test_exact_single_word_sentence_is_allowed(self):
        english, translation = "Run!", "跑！"
        alignment = payload(english, translation, [equivalent((0, 3), (0, 1))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(0, 3)]),
                         '<span class="term-highlight">跑</span>！')

    def test_equal_shortest_containing_spans_fail_instead_of_guessing(self):
        english, translation = "one two three four", "一二三四"
        alignment = payload(english, translation, [
            equivalent((0, 7), (0, 2)), equivalent((4, 11), (1, 3)),
        ])
        with self.assertRaisesRegex(TranslationAlignmentError, "ambiguous"):
            render_aligned_translation(english, translation, alignment, [(4, 7)])

    def test_non_english_neighbors_are_not_treated_as_english_word_boundaries(self):
        english, translation = "中文rate中文", "中文比率中文"
        alignment = payload(english, translation, [equivalent((2, 6), (2, 4))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(2, 6)]),
                         '中文<span class="term-highlight">比率</span>中文')

    def test_offsets_are_unicode_codepoints_not_utf16_or_grapheme_indices(self):
        english, translation = "😀 A cafe\u0301 blooms.", "👨‍👩‍👧‍👦在咖啡馆喝cafe\u0301。"
        en_start = english.index("cafe")
        zh_start = translation.index("cafe")
        alignment = payload(english, translation, [
            equivalent((en_start, en_start + 5), (zh_start, zh_start + 5)),
        ])
        self.assertEqual(render_aligned_translation(english, translation, alignment,
                                                  [(en_start, en_start + 5)]),
                         '👨‍👩‍👧‍👦在咖啡馆喝<span class="term-highlight">café</span>。')

    def test_html_and_js_like_source_is_always_escaped(self):
        english = "We said alert."
        translation = '<script>alert("x")</script> & \'测试\''
        start = translation.index("alert")
        alignment = payload(english, translation, [equivalent((8, 13), (start, start + 5))])
        self.assertEqual(render_aligned_translation(english, translation, alignment, [(8, 13)]),
                         '&lt;script&gt;<span class="term-highlight">alert</span>'
                         '(&quot;x&quot;)&lt;/script&gt; &amp; &#x27;测试&#x27;')

    def test_selected_iterable_is_consumed_once(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation, [equivalent((3, 8), (2, 4))])
        matches = (span for span in [(3, 8)])
        self.assertEqual(render_aligned_translation(english, translation, alignment, matches),
                         '我们<span class="term-highlight">同意</span>。')

    def test_english_and_translation_hashes_are_independently_checked(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation, [equivalent((3, 8), (2, 4))])
        for en, zh, expected in (("We Agree.", translation, "englishHash"),
                                 (english, "我们同意！", "translationHash")):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(TranslationAlignmentError, expected):
                    render_aligned_translation(en, zh, alignment, [(3, 8)])

    def test_hash_is_exact_without_unicode_or_whitespace_normalization(self):
        english, translation = "A cafe\u0301.", "一家咖啡馆。"
        alignment = payload(english, translation)
        for changed in ("A café.", english + " "):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(TranslationAlignmentError, "englishHash"):
                    validate_translation_alignment(changed, translation, alignment)

    def test_unknown_schema_and_top_level_fields_are_rejected(self):
        english, translation = "We agree.", "我们同意。"
        valid = payload(english, translation)
        cases = [None, [], {**valid, "schema": "future.v2"},
                 {**valid, "extra": True}, {k: v for k, v in valid.items() if k != "translationHash"}]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(TranslationAlignmentError):
                    validate_translation_alignment(english, translation, invalid)

    def test_malformed_hashes_are_rejected(self):
        english, translation = "We agree.", "我们同意。"
        for field in ("englishHash", "translationHash"):
            for value in (None, 5, "0" * 63, "g" * 64, "A" * 64, "0" * 64):
                with self.subTest(field=field, value=value):
                    invalid = {**payload(english, translation), field: value}
                    with self.assertRaisesRegex(TranslationAlignmentError, field):
                        validate_translation_alignment(english, translation, invalid)

    def test_non_string_text_and_unpaired_surrogates_are_rejected(self):
        valid = payload("We agree.", "我们同意。")
        for english, translation in ((None, "我们同意。"), ("We agree.", b"translation"),
                                     ("\ud800", "我们同意。"), ("We agree.", "\ud800")):
            with self.subTest(english=repr(english), translation=repr(translation)):
                with self.assertRaises(TranslationAlignmentError):
                    validate_translation_alignment(english, translation, valid)

    def test_blank_source_or_translation_is_rejected(self):
        for english, translation in (("", "译文"), (" \n", "译文"), ("English", ""),
                                     ("English", "\t ")):
            with self.subTest(english=english, translation=translation):
                with self.assertRaisesRegex(TranslationAlignmentError, "blank"):
                    validate_translation_alignment(english, translation, payload(english, translation))

    def test_alignment_container_and_item_fields_are_strict(self):
        english, translation = "We agree.", "我们同意。"
        good = equivalent((3, 8), (2, 4))
        invalid_items = [None, [], {**good, "extra": "data"},
                         {k: v for k, v in good.items() if k != "en"},
                         {**good, "relation": "unknown"}, {**good, "note": 3},
                         {**good, "en": (3, 8)}, {**good, "zh": ((2, 4),)},
                         {**good, "zh": [(2, 4)]}]
        for items in (None, {}, tuple([good])):
            with self.subTest(items=items):
                with self.assertRaises(TranslationAlignmentError):
                    validate_translation_alignment(english, translation,
                                                   {**payload(english, translation), "alignments": items})
        for item in invalid_items:
            with self.subTest(item=item):
                with self.assertRaises(TranslationAlignmentError):
                    validate_translation_alignment(english, translation,
                                                   payload(english, translation, [item]))

    def test_invalid_english_and_chinese_ranges_are_rejected(self):
        english, translation = "We agree.", "我们同意。"
        invalid_ranges = [[3], [0, 1, 2], [-1, 3], [8, 3], [3, 3],
                          [0, 99], [True, 3], [0, False], [0.0, 3], [0, "3"]]
        for field in ("en", "zh"):
            for invalid_range in invalid_ranges:
                item = equivalent((3, 8), (2, 4))
                item[field] = invalid_range if field == "en" else [invalid_range]
                with self.subTest(field=field, range=invalid_range):
                    with self.assertRaisesRegex(TranslationAlignmentError, field):
                        validate_translation_alignment(english, translation,
                                                       payload(english, translation, [item]))

    def test_relation_constraints_and_explanations_are_enforced(self):
        english, translation = "We agree.", "我们同意。"
        invalid_items = [{"en": [3, 8], "zh": [], "relation": "equivalent"}]
        for relation in ("implicit", "untranslated"):
            invalid_items.extend([
                {"en": [3, 8], "zh": [[2, 4]], "relation": relation, "note": "Explanation"},
                {"en": [3, 8], "zh": [], "relation": relation},
                {"en": [3, 8], "zh": [], "relation": relation, "note": " \n "},
            ])
        for item in invalid_items:
            with self.subTest(item=item):
                with self.assertRaises(TranslationAlignmentError):
                    validate_translation_alignment(english, translation,
                                                   payload(english, translation, [item]))

    def test_duplicate_english_pairs_are_rejected(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation, [
            equivalent((3, 8), (2, 3)), equivalent((3, 8), (3, 4)),
        ])
        with self.assertRaisesRegex(TranslationAlignmentError, "duplicate"):
            validate_translation_alignment(english, translation, alignment)

    def test_invalid_unselected_alignment_still_fails_before_rendering(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation, [
            equivalent((3, 8), (2, 4)), equivalent((0, 2), (10, 12)),
        ])
        with self.assertRaisesRegex(TranslationAlignmentError, "zh"):
            render_aligned_translation(english, translation, alignment, [(3, 8)])

    def test_invalid_matched_ranges_are_rejected_even_when_no_alignment_matches(self):
        english, translation = "We agree.", "我们同意。"
        alignment = payload(english, translation)
        cases = [None, "agree", [(8, 3)], [(3, 3)], [(-1, 2)], [(3, 99)],
                 [(True, 3)], [(0.0, 2)], [(3,)], ["38"]]
        for matches in cases:
            with self.subTest(matches=matches):
                with self.assertRaisesRegex(TranslationAlignmentError, "matched_english_ranges"):
                    render_aligned_translation(english, translation, alignment, matches)


if __name__ == "__main__":
    unittest.main()
