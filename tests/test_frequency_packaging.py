"""Exam counts and half stars survive web/APKG export without changing note IDs."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from anki_pipeline.packaging import _fields, build_package, render_preview
from anki_pipeline.web_preview import build_web_preview


def card():
    return {"id": "frequency-note", "sheet": "Unit 1", "lesson": "1", "position": "1",
            "word": "rate", "phonetic": "/reɪt/", "definition": "n. 比率",
            "simple_definition": "", "level": "考研", "word_forms": "",
            "audio_filename": "", "examples": [],
            "exam_frequency": {"schema": "kaoyan-frequency.v1", "occurrences": 8,
                "matched_sentences": 6, "paper_count": 4, "corpus_papers": 44,
                "stars": 2.5, "rule": "occurrence-bands.v1"}}


class FrequencyPackagingTests(unittest.TestCase):
    def test_half_rating_has_exactly_five_star_shapes_and_one_half(self):
        fields, _, _ = _fields(card(), None, 0)
        markup = fields["Definition"]
        self.assertIn('class="exam-frequency"', markup)
        self.assertIn('data-occurrences="8"', markup)
        self.assertIn('data-stars="2.5"', markup)
        self.assertEqual(markup.count('class="frequency-star"'), 5)
        self.assertEqual(markup.count('class="frequency-star-fill" width="50%"'), 1)
        self.assertEqual(markup.count('class="frequency-star-fill" width="100%"'), 2)
        self.assertIn("8 次", markup)
        self.assertIn("4 / 44 套", markup)
        self.assertIn('aria-label="2.5 / 5 星"', markup)
        self.assertIn("2.5 / 5", markup)
        self.assertNotIn("exam-frequency", fields["Word"])
        self.assertLess(markup.index('class="exam-frequency"'), markup.index('frequency-definition-title'))
        self.assertLess(markup.index('frequency-definition-title'), markup.index('class="sense-row"'))

    def test_no_frequency_is_not_fabricated_for_legacy_card(self):
        source = card()
        del source["exam_frequency"]
        fields, _, _ = _fields(source, None, 0)
        self.assertNotIn("exam-frequency", fields["Definition"])

    def test_full_rating_is_capped_at_five_stars(self):
        source = card()
        source["exam_frequency"].update(occurrences=250, stars=5.0)
        fields, _, _ = _fields(source, None, 0)
        self.assertEqual(fields["Definition"].count('class="frequency-star"'), 5)
        self.assertEqual(fields["Definition"].count('class="frequency-star-fill" width="100%"'), 5)
        self.assertIn("5 / 5", fields["Definition"])

    def test_zero_rating_is_explicit_and_has_five_empty_stars(self):
        source = card()
        source["exam_frequency"].update(occurrences=0, matched_sentences=0, paper_count=0, stars=0.0)
        fields, _, _ = _fields(source, None, 0)
        self.assertIn("0 次", fields["Definition"])
        self.assertIn("0 / 5", fields["Definition"])
        self.assertEqual(fields["Definition"].count('class="frequency-star"'), 5)
        self.assertNotIn('class="frequency-star-fill"', fields["Definition"])

    def test_invalid_or_inconsistent_statistics_fail_closed(self):
        for key, value in [("occurrences", True), ("occurrences", -1),
                           ("stars", 2.25), ("stars", 5), ("stars", float("nan")),
                           ("paper_count", 45), ("matched_sentences", 9),
                           ("corpus_papers", "<script>"), ("schema", "unknown"),
                           ("rule", "unknown")]:
            with self.subTest(key=key, value=value):
                source = card()
                source["exam_frequency"][key] = value
                with self.assertRaises(ValueError):
                    _fields(source, None, 0)

    def test_web_and_apkg_use_identical_statistics_in_existing_ten_fields(self):
        source = card()
        before = copy.deepcopy(source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "audio"
            audio.mkdir()
            package = root / "frequency.apkg"
            build_package([source], audio, package)
            with zipfile.ZipFile(package) as archive:
                database = root / "collection.anki2"
                database.write_bytes(archive.read("collection.anki2"))
            with sqlite3.connect(database) as connection:
                fields = connection.execute("SELECT flds FROM notes").fetchone()[0].split("\x1f")
                model = next(iter(json.loads(connection.execute("SELECT models FROM col").fetchone()[0]).values()))
            web = build_web_preview([source], audio, root / "preview.html", deck_name="考研英语")
            catalog = json.loads((Path(web["version_directory"]) / "catalog.json").read_text())
            page = (root / catalog["cards"][0]["previewUrl"]).read_text()
            self.assertEqual(len(fields), 10)
            self.assertEqual(int(model["id"]), 1552983369)
            self.assertIn(fields[2], page)
            self.assertIn(fields[2], render_preview(source, audio))
            self.assertIn(fields[8], page)
            self.assertTrue(fields[8].startswith('Unit 1 ➫ 1 ➫ 1<script>'))
            # Legacy APKG updates may keep the installed note-type CSS. The
            # component must carry its own sizing, layout and colours.
            self.assertNotIn(".exam-frequency", model["css"])
            self.assertIn('style="display:block;flex:none;width:1.1rem;height:1.1rem"', fields[2])
            self.assertIn('style="fill:#ad7918"', fields[2])
            self.assertIn('style="overflow:hidden"', fields[2])
            self.assertIn('data-stars="2.5"', fields[2])
        self.assertEqual(source, before)


if __name__ == "__main__":
    unittest.main()
