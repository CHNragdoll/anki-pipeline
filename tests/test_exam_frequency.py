"""Source-based frequency and half-star rating regression checks."""

import unittest

from anki_pipeline.exam_frequency import frequency_for_matches, frequency_stars


class ExamFrequencyTests(unittest.TestCase):
    def test_all_half_star_thresholds_and_their_lower_boundaries(self):
        self.assertEqual(frequency_stars(0), 0.0)
        previous_stars = 0.0
        for index, minimum in enumerate((1, 2, 3, 5, 8, 13, 20, 30, 50, 80), 1):
            with self.subTest(minimum=minimum):
                self.assertEqual(frequency_stars(minimum - 1), previous_stars)
                self.assertEqual(frequency_stars(minimum), index / 2)
            previous_stars = index / 2
        self.assertEqual(frequency_stars(10000), 5.0)

    def test_occurrence_input_is_a_nonnegative_integer_not_a_bool_or_float(self):
        for value in (-1, True, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                frequency_stars(value)

    def test_repeated_source_identity_is_deduplicated_but_distinct_positions_count(self):
        source_matches = [
            ("kaoyan:2026-01", "p:first", 0, 2),
            ("kaoyan:2026-01", "p:first", 0, 2),
            ("kaoyan:2026-01", "p:first", 1, 2),
            ("kaoyan:2026-01", "p:second", 0, 1),
            ("kaoyan:2000-01", "p:third", 0, 1)]
        self.assertEqual(frequency_for_matches(source_matches, corpus_papers=44), {
            "schema": "kaoyan-frequency.v1", "occurrences": 6,
            "matched_sentences": 4, "paper_count": 2, "corpus_papers": 44,
            "stars": 2.0, "rule": "occurrence-bands.v1"})
        self.assertEqual(len(source_matches), 5)

    def test_conflicting_counts_for_one_source_identity_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "source identity"):
            frequency_for_matches([("paper", "paragraph", 0, 1),
                                   ("paper", "paragraph", 0, 2)], 1)

    def test_zero_matches_and_zero_count_rows_do_not_create_matched_sentences(self):
        expected = {"schema": "kaoyan-frequency.v1", "occurrences": 0,
                    "matched_sentences": 0, "paper_count": 0, "corpus_papers": 44,
                    "stars": 0.0, "rule": "occurrence-bands.v1"}
        self.assertEqual(frequency_for_matches([], 44), expected)
        self.assertEqual(frequency_for_matches([("paper", "paragraph", 0, 0)], 44), expected)

    def test_invalid_source_count_and_corpus_relationship_are_rejected(self):
        for corpus_papers in (-1, True, 1.0):
            with self.subTest(corpus_papers=corpus_papers), self.assertRaises(ValueError):
                frequency_for_matches([], corpus_papers)
        for source in (("paper", "paragraph", 0, -1),
                       ("paper", "paragraph", True, 1),
                       ("paper", "paragraph", -1, 1),
                       ("paper", "paragraph", 0, True),
                       ("paper", "paragraph", 0, 1.0),
                       ("", "paragraph", 0, 1),
                       ("paper", None, 0, 1)):
            with self.subTest(source=source), self.assertRaises(ValueError):
                frequency_for_matches([source], 44)
        with self.assertRaisesRegex(ValueError, "corpus"):
            frequency_for_matches([("paper-one", "paragraph", 0, 1),
                                   ("paper-two", "paragraph", 0, 1)], 1)


if __name__ == "__main__":
    unittest.main()
