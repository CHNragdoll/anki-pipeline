"""Exact, read-only ECDICT enrichment without lemma or derivation guesses."""
from __future__ import annotations

import copy
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import ecdict


FIELDS = ["word", "phonetic", "definition", "translation", "pos", "collins", "oxford",
          "tag", "bnc", "frq", "exchange", "detail", "audio"]
ROOT = Path(__file__).resolve().parents[2] / "ECDICT"


class EcdictTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "ecdict.csv"
        self.license = self.root / "LICENSE"
        self.license.write_text("MIT License\n\nCopyright (c) test\nPermission notice.\n", encoding="utf-8")

    def write(self, *rows):
        with self.source.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)

    def enrich(self, *cards):
        return ecdict.enrich_ecdict_cards(cards, self.root)

    def test_exact_normalized_lookup_preserves_all_existing_fields_and_source(self):
        self.write({"word": "study", "translation": "n. 学习", "tag": "cet4 ky",
                    "exchange": "s:studies"})
        original = {"id": "stable", "word": "ＳＴＵＤＹ", "definition": "old definition",
                    "examples": [{"text": "keep", "translation": "原译"}],
                    "local_dictionary": {"senses": [{"text": "原词典"}]}}
        untouched = copy.deepcopy(original)
        raw = self.source.read_bytes()
        cards, report = self.enrich(original)
        self.assertEqual(original, untouched)
        self.assertEqual({key: cards[0][key] for key in original}, original)
        self.assertEqual(self.source.read_bytes(), raw)
        local = cards[0]["ecdict"]
        self.assertEqual(local["word"], "study")
        self.assertEqual(local["translation"], "n. 学习")
        self.assertEqual(local["provenance"], {"file_sha256": hashlib.sha256(raw).hexdigest(),
                                             "row": 2, "headword": "study",
                                             "license_text": self.license.read_text()})
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report["source"]["row_count"], 1)
        self.assertEqual(report["source"]["license_sha256"], hashlib.sha256(self.license.read_bytes()).hexdigest())
        self.assertEqual(report["counts"]["matches"], 1)
        cards[0]["examples"][0]["text"] = "changed copy"
        self.assertEqual(original, untouched)

    def test_first_line_heading_keeps_display_and_does_not_use_american_alias(self):
        self.write({"word": "catalogue", "translation": "原目录"},
                   {"word": "catalog", "translation": "美国目录"})
        title = "catalogue\n(美catalog)"
        cards, report = self.enrich({"id": "keep", "word": title})
        self.assertEqual(cards[0]["word"], title)
        self.assertEqual(cards[0]["ecdict"]["word"], "catalogue")
        self.assertEqual(cards[0]["ecdict"]["translation"], "原目录")
        self.assertEqual(report["counts"]["matches"], 1)

    def test_missing_word_never_follows_roots_or_fuzzy_punctuation(self):
        self.write({"word": "study", "translation": "学习", "exchange": "p:studied"},
                   {"word": "long-time", "translation": "长期"})
        cards, report = self.enrich({"id": "one", "word": "studied"},
                                   {"id": "two", "word": "longtime"})
        for card in cards:
            self.assertEqual(card["ecdict"]["translation"], "")
            self.assertEqual(card["ecdict"]["forms"], [])
            self.assertEqual(card["ecdict"]["provenance"]["row"], None)
        self.assertEqual(report["missing"]["entries"], [{"id": "one", "word": "studied"},
                                                        {"id": "two", "word": "longtime"}])

    def test_literal_newline_is_decoded_without_unicode_or_html_interpretation(self):
        text = r'vt. 使伸出\na. 突出的 <script>alert("x")</script> \u4e2d'
        self.write({"word": "exsert", "translation": text})
        cards, _ = self.enrich({"id": "one", "word": "exsert"})
        self.assertEqual(cards[0]["ecdict"]["translation"], text.replace(r"\n", "\n"))
        self.assertIn(r"\u4e2d", cards[0]["ecdict"]["translation"])
        self.assertEqual(cards[0]["ecdict"]["derived"], [])

    def test_exchange_only_seven_explicit_inflections_no_lemma_or_inferred_derivatives(self):
        self.write({"word": "exact", "pos": "n:100", "translation": "n. 名词\nv. 动词\nadj. 形容词", "exchange":
                    "p:exacted/d:exacted/i:exacting/3:exacts/s:exacts/r:exacter/t:exactest/0:root/1:p"})
        cards, report = self.enrich({"id": "one", "word": "exact"})
        self.assertEqual(cards[0]["ecdict"]["forms"], [
            {"kind": "past", "label": "过去式", "form": "exacted", "source": "ecdict"},
            {"kind": "past_participle", "label": "过去分词", "form": "exacted", "source": "ecdict"},
            {"kind": "present_participle", "label": "现在分词", "form": "exacting", "source": "ecdict"},
            {"kind": "third_person_singular", "label": "第三人称单数", "form": "exacts", "source": "ecdict"},
            {"kind": "plural", "label": "复数", "form": "exacts", "source": "ecdict"},
            {"kind": "comparative", "label": "比较级", "form": "exacter", "source": "ecdict"},
            {"kind": "superlative", "label": "最高级", "form": "exactest", "source": "ecdict"}])
        self.assertEqual(cards[0]["ecdict"]["derived"], [])
        self.assertEqual(report["counts"]["derived"], 0)

    def test_duplicate_inflections_deduplicate_but_keep_distinct_types(self):
        self.write({"word": "study", "translation": "vt. 学习", "exchange": "p:studied/p:studied/d:studied/0:study/1:p"})
        cards, _ = self.enrich({"id": "one", "word": "study"})
        self.assertEqual([(form["kind"], form["form"]) for form in cards[0]["ecdict"]["forms"]],
                         [("past", "studied"), ("past_participle", "studied")])

    def test_unknown_tags_and_exchange_types_are_explicit_and_do_not_invent_features(self):
        self.write({"word": "study", "tag": "zk gk cet4 cet6 ky toefl ielts gre alien cet4",
                    "exchange": "x:studious/0:study/1:s/broken/p:",
                    "collins": "0", "oxford": "0", "bnc": "0", "frq": "-1"})
        cards, report = self.enrich({"id": "one", "word": "study"})
        local = cards[0]["ecdict"]
        self.assertEqual(local["tags"], ["zk", "gk", "cet4", "cet6", "ky", "toefl", "ielts", "gre", "alien"])
        self.assertEqual(local["tag_labels"], ["中考", "高中", "CET4", "CET6", "考研", "TOEFL", "IELTS", "GRE"])
        self.assertEqual(local["forms"], [])
        self.assertEqual(local["derived"], [])
        self.assertEqual(set(local), {"word", "translation", "forms", "derived", "tags", "tag_labels", "provenance"})
        self.assertEqual(report["unknown_tags"], [{"id": "one", "word": "study", "row": 2, "tags": ["alien"]}])
        self.assertTrue(report["warnings"])

    def test_same_lookup_with_two_card_ids_remains_two_independent_cards(self):
        self.write({"word": "study", "translation": "学习", "tag": "ky"})
        cards, report = self.enrich({"id": "one", "word": "study"}, {"id": "two", "word": "STUDY"})
        self.assertEqual(report["counts"]["matches"], 2)
        self.assertEqual(report["unique_words"], 1)
        cards[0]["ecdict"]["tags"].clear()
        self.assertEqual(cards[1]["ecdict"]["tags"], ["ky"])

    def test_unsupported_adjective_plural_and_uncertain_pos_are_skipped_and_reported(self):
        self.write({"word": "dramatic", "translation": "a. 戏剧的", "exchange": "s:dramatics"},
                   {"word": "uncertain", "translation": "没有明确词性", "pos": "v:100", "exchange": "p:uncertained"})
        cards, report = self.enrich({"id": "one", "word": "dramatic"}, {"id": "two", "word": "uncertain"})
        self.assertTrue(all(card["ecdict"]["forms"] == [] for card in cards))
        self.assertEqual([warning["type"] for warning in report["warnings"]],
                         ["unsupported_exchange_pos", "unsupported_exchange_pos"])
        self.assertEqual(report["warnings"][0]["explicit_pos"], ["adjective"])
        self.assertEqual(report["warnings"][1]["explicit_pos"], [])

    def test_exact_oxford_pos_can_support_forms_but_stale_other_word_cannot(self):
        self.write({"word": "study", "translation": "学习", "exchange": "p:studied"})
        good = {"id": "one", "word": "study", "local_dictionary": {"lookup_word": "study", "senses": [{"pos": "v."}]}}
        stale = {"id": "two", "word": "study", "local_dictionary": {"lookup_word": "other", "senses": [{"pos": "v."}]}}
        cards, report = self.enrich(good, stale)
        self.assertEqual(cards[0]["ecdict"]["forms"][0]["form"], "studied")
        self.assertEqual(cards[1]["ecdict"]["forms"], [])
        self.assertEqual(report["counts"]["forms"], 1)

    def test_invalid_optional_oxford_pos_is_not_treated_as_evidence(self):
        self.write({"word": "study", "translation": "学习", "exchange": "p:studied"})
        cards, report = self.enrich(
            {"id": "one", "word": "study", "local_dictionary": {"lookup_word": None, "senses": [{"pos": "v."}]}},
            {"id": "two", "word": "study", "local_dictionary": {"lookup_word": "study", "senses": None}})
        self.assertTrue(all(card["ecdict"]["forms"] == [] for card in cards))
        self.assertEqual(report["counts"]["forms"], 0)

    def test_definition_pos_and_mixed_self_inflections_preserve_real_past_participle(self):
        self.write({"word": "cut", "definition": "v. sever with a knife", "exchange": "p:cut/d:cut/i:cutting"})
        cards, report = self.enrich({"id": "one", "word": "cut"})
        self.assertEqual([(form["kind"], form["form"]) for form in cards[0]["ecdict"]["forms"]],
                         [("past", "cut"), ("past_participle", "cut"), ("present_participle", "cutting")])
        self.assertEqual(report["warnings"], [])

    def test_self_only_exchange_is_not_used_as_missing_dictionary_fallback(self):
        self.write({"word": "foremost", "translation": "a. 最重要的", "exchange": "t:foremost/0:foremost/1:t"})
        cards, report = self.enrich({"id": "one", "word": "foremost"})
        self.assertEqual(cards[0]["ecdict"]["forms"], [])
        self.assertEqual(report["warnings"][0]["type"], "self_only_exchange")

    def test_form_values_remain_plain_text_with_no_html_interpretation(self):
        text = '<img src="x" onerror="alert(1)">'
        self.write({"word": "study", "translation": "v. 学习", "exchange": f"p:{text}"})
        cards, _ = self.enrich({"id": "one", "word": "study"})
        self.assertEqual(cards[0]["ecdict"]["forms"][0]["form"], text)

    def test_matched_normalized_duplicate_rows_are_rejected_without_mutation(self):
        self.write({"word": "study", "translation": "one"}, {"word": "ＳＴＵＤＹ", "translation": "two"})
        raw = self.source.read_bytes()
        original = {"id": "one", "word": "study"}
        with self.assertRaisesRegex(ValueError, "[Dd]uplicate"):
            self.enrich(original)
        self.assertEqual(original, {"id": "one", "word": "study"})
        self.assertEqual(self.source.read_bytes(), raw)

    def test_invalid_cards_and_duplicate_ids_are_rejected(self):
        self.write({"word": "study"})
        for cards in ([{"id": "same", "word": "study"}, {"id": "same", "word": "other"}],
                      [{"id": "", "word": "study"}], [{"id": "one", "word": 3}],
                      [{"id": "  ", "word": "study"}], [{"id": "one", "word": "  "}], ["invalid"]):
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                ecdict.enrich_ecdict_cards(cards, self.root)

    def test_malformed_header_and_csv_row_are_rejected(self):
        self.source.write_text("word,translation\nstudy,学习\n")
        with self.assertRaisesRegex(ValueError, "header"):
            self.enrich({"id": "one", "word": "study"})
        self.source.write_text("word,translation,definition,tag,exchange\nstudy,学习,,ky,,extra\n")
        with self.assertRaisesRegex(ValueError, "row"):
            self.enrich({"id": "one", "word": "study"})

    def test_source_change_during_scan_is_rejected(self):
        self.write({"word": "study", "translation": "学习"})
        original = ecdict._iter_lines

        def changed(stream, digest):
            for index, line in enumerate(original(stream, digest)):
                yield line
                if index == 0:
                    with self.source.open("ab") as writer:
                        writer.write(b"other,,,,,,,,,,,,\r\n")

        with patch("anki_pipeline.ecdict._iter_lines", changed):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.enrich({"id": "one", "word": "study"})

    def test_real_csv_newline_row_has_logical_record_provenance(self):
        self.write({"word": "study", "translation": "第一行\n第二行"}, {"word": "next", "translation": "下一条"})
        cards, report = self.enrich({"id": "two", "word": "next"})
        self.assertEqual(cards[0]["ecdict"]["provenance"]["row"], 3)
        self.assertEqual(report["source"]["row_count"], 2)


@unittest.skipUnless((ROOT / "ecdict.csv").is_file(), "Local ECDICT source is not installed")
class ActualEcdictTest(unittest.TestCase):
    def test_actual_exsert_definition_forms_and_catalogue_heading(self):
        cards, report = ecdict.enrich_ecdict_cards(
            [{"id": "exsert", "word": "exsert"}, {"id": "catalogue", "word": "catalogue\n(美catalog)"},
             *({"id": word, "word": word} for word in ["dramatic", "energetic", "vital", "limited", "foremost", "cut", "run"])], ROOT)
        self.assertEqual(report["missing"]["entries"], [])
        self.assertEqual(cards[0]["ecdict"]["translation"], "vt. 使突出, 使伸出\na. 突出的")
        self.assertEqual({form["kind"] for form in cards[0]["ecdict"]["forms"]},
                         {"past", "past_participle", "present_participle", "third_person_singular"})
        self.assertEqual(cards[0]["ecdict"]["derived"], [])
        self.assertEqual(cards[1]["word"], "catalogue\n(美catalog)")
        self.assertEqual(cards[1]["ecdict"]["tag_labels"], ["高中", "CET6", "IELTS"])
        self.assertEqual(len(report["source"]["sha256"]), 64)
        self.assertGreater(report["source"]["row_count"], 700000)
        self.assertTrue(all(card["ecdict"]["forms"] == [] for card in cards[2:7]))
        self.assertIn({"kind": "past_participle", "label": "过去分词", "form": "cut", "source": "ecdict"},
                      cards[7]["ecdict"]["forms"])
        self.assertIn({"kind": "past_participle", "label": "过去分词", "form": "run", "source": "ecdict"},
                      cards[8]["ecdict"]["forms"])
        self.assertTrue(cards[0]["ecdict"]["provenance"]["license_text"].startswith("MIT License"))


if __name__ == "__main__":
    unittest.main()
