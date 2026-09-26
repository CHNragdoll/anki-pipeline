"""Behavior checks for the standalone, local Anki export."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from anki_pipeline.packaging import build_package, render_preview


def card(card_id=1, *, word="rate", audio="rate.mp3"):
    return {
        "id": card_id,
        "sheet": "Unit 2",
        "lesson": "Lesson 10",
        "position": card_id,
        "word": word,
        "phonetic": "/reɪt/",
        "definition": "n. 比率\nv. 评价",
        "simple_definition": "比率",
        "level": "CET-4",
        "word_forms": "rates, rated",
        "audio_filename": audio,
        "examples": [{"text": "The rate rose.", "source": "2019 考研", "translation": "比率上升了。"}],
    }


def collection(package_path):
    with zipfile.ZipFile(package_path) as archive:
        media = json.loads(archive.read("media"))
        with tempfile.NamedTemporaryFile(suffix=".anki2") as database_file:
            database_file.write(archive.read("collection.anki2"))
            database_file.flush()
            with sqlite3.connect(database_file.name) as connection:
                notes = connection.execute("SELECT guid, flds FROM notes ORDER BY guid").fetchall()
                decks = json.loads(connection.execute("SELECT decks FROM col").fetchone()[0])
                models = json.loads(connection.execute("SELECT models FROM col").fetchone()[0])
    return media, notes, decks, models


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "audio"
        self.audio.mkdir()
        (self.audio / "rate.mp3").write_bytes(b"ID3\0")
        (self.audio / "theme.mp3").write_bytes(b"ID3\0")
        self.output = self.root / "deck.apkg"

    def test_two_notes_one_lesson_deck_media_and_escaped_content(self):
        first = card()
        first["definition"] = '<script>alert("x")</script> & 比率'
        first["examples"][0]["translation"] = "翻译 <img src=x onerror=alert(1)>"
        second = card(2, word="theme", audio="theme.mp3")
        stats = build_package([second, first], self.audio, self.output)
        media, notes, decks, models = collection(self.output)
        self.assertEqual(stats["card_count"], 2)
        self.assertEqual(stats["audio_count"], 2)
        self.assertEqual(stats["deck_count"], 1)
        self.assertEqual(set(media.values()), {"rate.mp3", "theme.mp3"})
        self.assertEqual(len(notes), 2)
        deck_name = "考研英语::Unit 02::Lesson 10"
        self.assertEqual(len([deck for deck in decks.values() if deck["name"] == deck_name]), 1)
        self.assertIn(deck_name, stats["deck_ids"])
        self.assertEqual(len(models), 1)
        joined = "\n".join(fields for _, fields in notes)
        self.assertIn("[sound:rate.mp3]", joined)
        self.assertIn("&lt;script&gt;", joined)
        self.assertIn("&lt;img", joined)
        self.assertNotIn("<script>alert", joined)
        self.assertNotIn("<img src=x", joined)
        model = next(iter(models.values()))
        self.assertNotIn("<script", model["css"].lower())
        self.assertNotIn('class="speak-button"', model["tmpls"][0]["qfmt"])
        self.assertIn("2026-12-19T08:30:00+08:00", model["tmpls"][0]["qfmt"])

    def test_different_lesson_has_separate_stable_deck(self):
        second = card(2, word="theme", audio="theme.mp3")
        second["lesson"] = "2"
        stats = build_package([card(), second], self.audio, self.output)
        _, _, decks, _ = collection(self.output)
        names = {deck["name"] for deck in decks.values() if deck["name"].startswith("考研英语::")}
        self.assertEqual(names, {"考研英语::Unit 02::Lesson 02", "考研英语::Unit 02::Lesson 10"})
        self.assertEqual(stats["deck_count"], 2)
        self.assertEqual(len(set(stats["deck_ids"].values())), 2)

    def test_numeric_positions_determine_due_order(self):
        first = card(10)
        first["position"] = "10"
        later_input = card(2, word="theme", audio="theme.mp3")
        later_input["position"] = "2"
        build_package([first, later_input], self.audio, self.output)
        with zipfile.ZipFile(self.output) as archive:
            with tempfile.NamedTemporaryFile(suffix=".anki2") as database_file:
                database_file.write(archive.read("collection.anki2"))
                database_file.flush()
                with sqlite3.connect(database_file.name) as connection:
                    words = [row[0].split("\x1f")[0] for row in connection.execute(
                        "SELECT notes.flds FROM cards JOIN notes ON cards.nid=notes.id ORDER BY cards.due"
                    )]
        self.assertEqual(words, ["theme", "rate"])

    def test_ids_stable_across_processes_and_reordering(self):
        other_lesson = card(2, word="theme", audio="theme.mp3")
        other_lesson["lesson"] = "2"
        stats_a = build_package([other_lesson, card()], self.audio, self.output)
        _, notes_a, decks_a, models_a = collection(self.output)
        script = (
            "from pathlib import Path; from anki_pipeline.packaging import build_package; "
            "import json, sys; build_package(json.loads(sys.argv[3]), "
            "Path(sys.argv[1]), Path(sys.argv[2]))"
        )
        other = self.root / "other.apkg"
        input_cards = [card(), other_lesson]
        subprocess.run([sys.executable, "-c", script, str(self.audio), str(other),
                        json.dumps(input_cards, ensure_ascii=False)], check=True)
        _, notes_b, decks_b, models_b = collection(other)
        self.assertEqual(notes_a, notes_b)
        self.assertEqual(set(decks_a), set(decks_b))
        self.assertEqual(set(models_a), set(models_b))
        self.assertEqual(stats_a["deck_ids"], {
            deck["name"]: int(deck_id) for deck_id, deck in decks_b.items()
            if deck["name"].startswith("考研英语::")
        })

    def test_missing_audio_and_symlink_escape_leave_existing_package_untouched(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(FileNotFoundError):
            build_package([card(audio="missing.mp3")], self.audio, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"ID3\0")
        (self.audio / "escape.mp3").symlink_to(outside)
        with self.assertRaises(ValueError):
            build_package([card(audio="escape.mp3")], self.audio, self.output)
        self.assertEqual(self.output.read_bytes(), b"existing")
        self.assertEqual(list(self.root.glob("*.tmp.apkg")), [])

    def test_package_write_failure_is_atomic(self):
        self.output.write_bytes(b"previous package")

        def fail_after_partial_write(_package, path):
            Path(path).write_bytes(b"partial")
            raise OSError("disk full")

        with patch("anki_pipeline.packaging.genanki.Package.write_to_file",
                   autospec=True, side_effect=fail_after_partial_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                build_package([card()], self.audio, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous package")
        self.assertEqual(list(self.root.glob(".*.tmp.apkg")), [])

    def test_blank_audio_policy_and_preview(self):
        no_audio = card(audio="")
        stats = build_package([no_audio], self.audio, self.output)
        self.assertEqual(stats["cards_without_audio"], 1)
        self.assertEqual(stats["audio_count"], 0)
        preview = render_preview(card(), self.audio)
        self.assertIn("<audio", preview)
        self.assertIn('The <mark class="target-word">rate</mark> rose.', preview)
        self.assertIn("data:audio/mpeg;base64,", preview)
        self.assertNotIn("file://", preview)
        self.assertNotIn("{{", preview)

    def test_duplicate_ids_and_unsafe_media_names_rejected(self):
        with self.assertRaises(ValueError):
            build_package([card(), card()], self.audio, self.output)
        with self.assertRaises(ValueError):
            build_package([card(audio="../outside.mp3")], self.audio, self.output)
        (self.audio / "empty.mp3").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            build_package([card(audio="empty.mp3")], self.audio, self.output)
        (self.audio / "wrong.wav").write_bytes(b"RIFF")
        with self.assertRaisesRegex(ValueError, "\\.mp3"):
            build_package([card(audio="wrong.wav")], self.audio, self.output)
        self.assertFalse(self.output.exists())

class TemplateParityTests(unittest.TestCase):
    def test_exact_example_highlighting_with_escaping_and_explicit_forms(self):
        item = card(audio='')
        item['word_forms'] = '过去式: rated | 第三人称单数: rates'
        item['examples'] = [{'text': 'Rates were rated rather highly; rate <script>rate</script> & rat.', 'source': '2020', 'translation': '示例'}]
        preview = render_preview(item)
        self.assertIn('<mark class="target-word">Rates</mark>', preview)
        self.assertIn('<mark class="target-word">rated</mark>', preview)
        self.assertIn('<mark class="target-word">rate</mark>', preview)
        self.assertNotIn('<mark class="target-word">rather', preview)
        self.assertNotIn('<mark class="target-word">rat</mark>', preview)
        self.assertIn('&lt;script&gt;', preview)
        self.assertNotIn('<script>rate</script>', preview)

    def test_preview_has_separate_initial_question_and_hidden_answer(self):
        from html.parser import HTMLParser
        class Sections(HTMLParser):
            def __init__(self):
                super().__init__(); self.attrs = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if attrs.get('id') in ['preview-front','preview-back','preview-flip']:
                    self.attrs[attrs['id']] = attrs
        view = render_preview(card(audio=''))
        parser = Sections(); parser.feed(view)
        self.assertNotIn('hidden', parser.attrs['preview-front'])
        self.assertIn('hidden', parser.attrs['preview-back'])
        self.assertEqual(parser.attrs['preview-flip']['aria-pressed'], 'false')
        self.assertIn('dictionary-link', view)


if __name__ == "__main__":
    unittest.main()
