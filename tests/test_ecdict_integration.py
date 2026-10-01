"""ECDICT fills missing dictionary sections, preserving source identities."""
import copy
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.cli import _guard_output
from anki_pipeline.config import load_config
from anki_pipeline.local_dictionary import apply_ecdict_fallbacks


def fixture():
    return {"id": "stable", "word": "study", "level": "old exam tags",
            "word_forms": "legacy spelling", "examples": [{"text": "Study it.", "translation": "研究它。"}],
            "local_dictionary": {"senses": [], "forms": [], "derived": [],
                "definition_source": "wordbook", "definition_fallback": "old meaning",
                "audio": {"oxford": [], "webster": []}},
            "ecdict": {"translation": "n. 研究\nv. 学习",
                "forms": [{"kind": "plural", "label": "复数", "form": "studies", "source": "ecdict"}],
                "derived": [], "tag_labels": ["考研"]}}


class EcdictIntegrationTests(unittest.TestCase):
    def test_fills_whole_missing_sections_and_preserves_actual_coverage(self):
        card = fixture()
        report = {"counts": {"oxford_senses": 0, "webster_forms": 0, "webster_derived": 0},
                  "missing": {"oxford_senses": [{"id": "stable", "word": "study"}]},
                  "fallbacks": {"definitions": [{"id": "stable", "word": "study", "source": "wordbook"}],
                                "audio": []}}
        before = copy.deepcopy((card, report))
        cards, audit = apply_ecdict_fallbacks([card], report)
        self.assertEqual((card, report), before)
        local = cards[0]["local_dictionary"]
        self.assertEqual(local["definition_source"], "ecdict")
        self.assertEqual(local["definition_fallback"], card["ecdict"]["translation"])
        self.assertEqual(local["forms_source"], "ecdict")
        self.assertEqual(local["webster_forms"], [])
        self.assertEqual(local["derived"], [])
        self.assertEqual(local["derived_source"], "")
        self.assertEqual(audit["counts"]["webster_forms"], 0)
        self.assertEqual(audit["counts"]["ecdict_forms"], 1)
        self.assertEqual(audit["missing"], report["missing"])
        self.assertEqual(audit["fallbacks"]["definitions"][0]["source"], "ecdict")
        for field in ("id", "word", "level", "word_forms", "examples"):
            self.assertEqual(cards[0][field], card[field])

    def test_present_oxford_and_webster_sections_are_not_merged_or_replaced(self):
        card = fixture()
        local = card["local_dictionary"]
        local.update(senses=[{"pos": "n.", "text": "牛津原义"}], definition_source="oxford",
                     forms=[{"kind": "plural", "label": "复数", "form": "original-studies"}],
                     derived=[{"label": "形容词", "word": "studious"}])
        card["ecdict"]["derived"] = [{"label": "形容词", "word": "different", "source": "ecdict"}]
        cards, audit = apply_ecdict_fallbacks([card], {})
        for field in ("senses", "forms", "derived", "definition_source"):
            self.assertEqual(cards[0]["local_dictionary"][field], local[field])
        self.assertEqual(cards[0]["local_dictionary"]["forms_source"], "webster")
        self.assertEqual(audit["fallback_counts"]["forms"], 0)

    def test_empty_ecdict_keeps_missing_sections_and_explicit_last_resort(self):
        card = fixture()
        card["ecdict"].update(translation="", forms=[], derived=[], tag_labels=[])
        cards, audit = apply_ecdict_fallbacks([card], {})
        self.assertEqual(cards[0]["local_dictionary"]["definition_source"], "wordbook")
        self.assertFalse(cards[0]["local_dictionary"]["forms"])
        self.assertFalse(cards[0]["local_dictionary"]["derived"])
        self.assertEqual(audit["counts"]["ecdict_definitions"], 0)

    def test_untracked_morphology_is_rejected(self):
        card = fixture()
        del card["ecdict"]["forms"][0]["source"]
        with self.assertRaisesRegex(ValueError, "source-tracked"):
            apply_ecdict_fallbacks([card], {})

    def test_ecdict_path_is_config_relative_and_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.toml"
            config_path.write_text('[paths]\ndatabase="data/cards.sqlite3"\n'
                'legacy_database="legacy/cards.sqlite3"\nwordbook="legacy/book.xlsx"\n'
                'audio="data/audio"\nlegacy_audio="legacy/audio"\noutput="output"\nbackups="backups"\n'
                '[ecdict]\nroot="ECDICT"\n')
            config = load_config(config_path)
            self.assertEqual(config.ecdict_root, (root / "ECDICT").resolve())
            with self.assertRaisesRegex(ValueError, "受保护"):
                _guard_output(config.ecdict_root / "ecdict.csv", config, config_path)


if __name__ == "__main__":
    unittest.main()
