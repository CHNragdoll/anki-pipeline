"""Provider precedence and safe explicit forms shared by both consumers."""
import copy
import unittest

from anki_pipeline.match_forms import card_match_forms
from anki_pipeline.text import word_variants


class MatchFormsTests(unittest.TestCase):
    def card(self, word="ambition", *, source="webster", forms=None):
        return {"word": word, "word_forms": "复数：ambitious", "ecdict": {
            "exchange": "s:ambitionless/i:ambitioning", "lemma": "ambit"},
            "local_dictionary": {"forms_source": source,
                "forms": forms or [], "derived": [{"word": "ambitious"}]}}

    def test_webster_is_authoritative_without_ecdict_legacy_or_derived_union(self):
        card = self.card(forms=[{"kind": "plural", "form": "ambitions"},
                                {"kind": "past", "form": "ambitioned"}])
        original = copy.deepcopy(card)
        self.assertEqual(card_match_forms(card), {"ambitions", "ambitioned"})
        self.assertEqual(card, original)

    def test_empty_webster_never_implicitly_reads_raw_ecdict_or_old_forms(self):
        self.assertEqual(card_match_forms(self.card()), set())

    def test_selected_ecdict_fallback_has_irregular_inflections(self):
        card = self.card("take", source="ecdict", forms=[
            {"kind": "past", "form": "took"},
            {"kind": "past_participle", "form": "taken"}])
        self.assertEqual(card_match_forms(card), {"took", "taken"})
        self.assertEqual(word_variants("take", card_match_forms(card), infer=False),
                         {"take", "took", "taken"})

    def test_parent_lemma_and_derived_relations_are_not_inflections(self):
        for word, parent in (("means", "mean"), ("customs", "custom")):
            with self.subTest(word=word):
                card = self.card(word, source="ecdict", forms=[
                    {"kind": "base", "form": parent},
                    {"kind": "lemma", "form": parent},
                    {"kind": "derived", "form": parent}])
                self.assertEqual(card_match_forms(card), set())

    def test_base_row_only_allows_own_lemma(self):
        self.assertEqual(card_match_forms(self.card("run", forms=[
            {"kind": "base", "form": "run", "base": "run"},
            {"kind": "past", "form": "ran", "base": "run"}])), {"run", "ran"})

    def test_explicit_parent_owned_inflections_are_not_own_forms(self):
        card = self.card("means", forms=[
            {"kind": "plural", "form": "means", "base": "mean"},
            {"kind": "base", "form": "mean", "base": "mean"},
            {"kind": "present_participle", "form": "meaning", "base": "mean"},
            {"kind": "past", "form": "meant", "base": "mean"}])
        self.assertEqual(card_match_forms(card), set())
        self.assertEqual(word_variants("means", card_match_forms(card), infer=False),
                         {"means"})
        customs = self.card("customs", forms=[
            {"kind": "plural", "form": "customs", "base": "custom"}])
        self.assertEqual(word_variants("customs", card_match_forms(customs), infer=False),
                         {"customs"})

    def test_explicit_owner_may_be_the_declared_title_spelling(self):
        card = self.card("armour\n(美armor)", forms=[
            {"kind": "plural", "form": "armors", "base": " ARMOR "},
            {"kind": "plural", "form": "armours", "base": "armour"},
            {"kind": "base", "form": "armor", "base": "armor"},
            {"kind": "plural", "form": "arms", "base": "arm"}])
        self.assertEqual(card_match_forms(card), {"armors", "armours", "armor"})
        self.assertEqual(card_match_forms(self.card("armour", forms=[
            {"kind": "plural", "form": "armors", "base": "armor"}])), set())

    def test_missing_owner_is_allowed_but_empty_or_malformed_owner_is_excluded(self):
        self.assertEqual(card_match_forms(self.card("rate", forms=[
            {"kind": "plural", "form": "rates"},
            {"kind": "past", "form": "rated", "base": ""},
            {"kind": "present_participle", "form": "rating", "base": "  "},
            {"kind": "past", "form": "rated", "base": None},
            {"kind": "past", "form": "rated", "base": ["rate"]}])),
                         {"rates"})

    def test_multiword_analytic_unknown_and_markup_forms_are_excluded(self):
        card = self.card("direct", forms=[
            {"kind": "comparative", "form": "more direct"},
            {"kind": "superlative", "form": "most direct"},
            {"kind": "other", "form": "direction"},
            {"kind": ["plural"], "form": "directs"},
            {"kind": "plural", "form": "<b>directs</b>"},
            {"kind": "plural", "form": "directs/directives"}])
        self.assertEqual(card_match_forms(card), set())

    def test_all_valid_inflection_kinds_are_normalized_and_deduplicated(self):
        forms = [{"kind": kind, "form": " RATES "} for kind in (
            "plural", "third_person_singular", "present_participle", "past",
            "past_participle", "comparative", "superlative")]
        self.assertEqual(card_match_forms(self.card("rate", forms=forms)), {"rates"})

    def test_existing_dictionary_records_default_to_webster(self):
        card = self.card(forms=[{"kind": "plural", "form": "ambitions"}])
        del card["local_dictionary"]["forms_source"]
        self.assertEqual(card_match_forms(card), {"ambitions"})

    def test_empty_source_is_only_valid_for_an_empty_forms_array(self):
        self.assertEqual(card_match_forms(self.card(source="")), set())
        with self.assertRaisesRegex(ValueError, "forms source"):
            card_match_forms(self.card(source="", forms=[
                {"kind": "plural", "form": "ambitions"}]))

    def test_non_dictionary_build_preserves_only_explicit_legacy_inflections(self):
        card = {"word": "even", "word_forms":
                "比较级：evener或more even | 最高级：evenest或most even | 派生词：evenly"}
        self.assertEqual(card_match_forms(card), {"evener", "evenest"})

    def test_malformed_provider_data_fails_before_matching(self):
        invalid = [None, {"forms_source": "unknown", "forms": []},
                   {"forms": {}}, {"forms": ["ran"]},
                   {"forms": [{"kind": "past", "form": None}]}]
        for local in invalid:
            with self.subTest(local=local):
                with self.assertRaises(ValueError):
                    card_match_forms({"word": "run", "local_dictionary": local})


if __name__ == "__main__":
    unittest.main()
