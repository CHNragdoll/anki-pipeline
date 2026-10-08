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

from anki_pipeline.packaging import _dictionary_markup, _fields, build_package, render_preview


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
    def test_reviewed_definition_shows_actual_source_and_escapes_its_notice(self):
        source = card(word="framer")
        source["local_dictionary"] = {
            "senses": [{"pos": "n.", "text": "制定者"}], "forms": [], "derived": [],
            "definition_source": "reviewed",
            "definition_source_notice": {"source_name": "Collins", "source_headword": "framer",
                "source_excerpt": "a person or thing that frames", "text": "核对 <script> 原文",
                "heading": "Collins 释义（校译）"}}
        definition, _ = _dictionary_markup(source)
        self.assertIn('data-dictionary="reviewed"', definition)
        self.assertIn('definition-source-notice', definition)
        self.assertIn('Collins；framer；a person or thing that frames', definition)
        self.assertIn('&lt;script&gt;', definition)
        self.assertNotIn('<script>', definition)
        source["local_dictionary"]["definition_source_notice"] = {}
        with self.assertRaisesRegex(ValueError, "visible source notice"):
            _dictionary_markup(source)

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
        for face in ("qfmt", "afmt"):
            self.assertIn("window.AnkiAudioLoudness =", model["tmpls"][0][face])
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

    def test_renaming_display_root_preserves_deck_ids_with_explicit_identity(self):
        original_name = "考研英语 · 精选真题"
        renamed = "27刘晓艳考研英语你还在背单词吗艾宾浩斯曲线版"
        second = card(2, word="theme", audio="theme.mp3")
        second["lesson"] = "2"
        with patch("genanki.package.time.time", return_value=1_700_000_000):
            previous = build_package([card(), second], self.audio, self.output,
                                     deck_name=original_name)
        media_before, notes_before, decks_before, models_before = collection(self.output)
        updated_path = self.root / "renamed.apkg"
        with patch("genanki.package.time.time", return_value=1_700_000_002):
            updated = build_package([second, card()], self.audio, updated_path,
                                    deck_name=renamed, deck_identity_name=original_name)
        media_after, notes_after, decks_after, models_after = collection(updated_path)
        expected = {renamed + name[len(original_name):]: identity
                    for name, identity in previous["deck_ids"].items()}
        self.assertEqual(updated["deck_ids"], expected)
        self.assertEqual(set(decks_before), set(decks_after))
        for name, identity in expected.items():
            self.assertEqual(decks_after[str(identity)]["name"], name)
        self.assertEqual(notes_before, notes_after)
        self.assertEqual(set(media_before.values()), set(media_after.values()))
        self.assertEqual(set(models_before), set(models_after))
        for identity in models_before:
            before = dict(models_before[identity])
            after = dict(models_after[identity])
            # genanki records the export time; all model content must stay identical.
            self.assertEqual(after.pop("mod") - before.pop("mod"), 2)
            self.assertEqual(before, after)

    def test_blank_explicit_deck_identity_does_not_replace_existing_package(self):
        self.output.write_bytes(b"existing")
        for identity in ("", "  ", False, "broken\x00identity"):
            with self.subTest(identity=identity), self.assertRaisesRegex(ValueError, "deck_identity_name"):
                build_package([card()], self.audio, self.output,
                              deck_identity_name=identity)
            self.assertEqual(self.output.read_bytes(), b"existing")

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
        self.assertIn("window.AnkiAudioLoudness =", preview)
        self.assertIn('The <mark class="target-word">rate</mark> rose.', preview)
        self.assertIn("data:audio/mpeg;base64,", preview)
        self.assertNotIn("file://", preview)
        self.assertNotIn("{{", preview)

    def test_library_sentence_has_safe_jump_and_only_its_sentence_translation(self):
        item = card()
        item['examples'][0].update({
            'latex_url': 'http://localhost:8765/reflow.htm?anki-sentence=0&paper=2026',
            'full_paper_url': 'http://localhost:8765/full-paper.htm?anki-sentence=0',
            'reader': 'full-paper', 'translation_scope': 'sentence',
        })
        build_package([item], self.audio, self.output)
        _, notes, _, _ = collection(self.output)
        fields = notes[0][1].split('\x1f')
        self.assertEqual(fields[6], '[sound:rate.mp3]')
        self.assertIn('<a class="sentence-jump"', fields[7])
        self.assertIn('href="http://localhost:8765/full-paper.htm?anki-sentence=0"', fields[7])
        self.assertIn('anki-sentence=0&amp;paper=2026', fields[7])
        self.assertIn('比率上升了。', fields[7])
        self.assertNotIn('段落译文', fields[7])
        self.assertNotIn('sentence-play', fields[7])
        preview = render_preview(item, self.audio)
        self.assertIn('class="preview-word-play replay-button"', preview)
        self.assertIn('<audio preload="none" hidden', preview)
        self.assertNotIn('<audio controls', preview)

    def test_unsafe_sentence_jump_url_does_not_replace_package(self):
        item = card()
        self.output.write_bytes(b'previous')
        for unsafe in ['javascript:alert(1)', 'http://user:secret@localhost/paper']:
            item['examples'][0].update({'latex_url': unsafe, 'full_paper_url': 'http://localhost/paper'})
            with self.assertRaisesRegex(ValueError, 'unsafe sentence source URL'):
                build_package([item], self.audio, self.output)
            self.assertEqual(self.output.read_bytes(), b'previous')

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
    def test_library_highlighting_uses_declared_forms_and_preserves_legacy_inference(self):
        item = card(word="forth", audio="")
        item["word_forms"] = ""
        example = item["examples"][0]
        example["text"] = "forth forthing forthcoming forthed"
        legacy = _fields(item, None, 5)[0]["Examples"]
        self.assertIn('<mark class="target-word">forth</mark>', legacy)
        self.assertIn('<mark class="target-word">forthing</mark>', legacy)
        example.update(latex_url="http://localhost:8765/latex.htm?anki_word=forth",
                       full_paper_url="http://localhost:8765/full-paper.htm?anki_word=forth")
        declared = _fields(item, None, 5)[0]["Examples"]
        self.assertIn('<mark class="target-word">forth</mark>', declared)
        self.assertNotIn('<mark class="target-word">forthing</mark>', declared)
        self.assertNotIn('<mark class="target-word">forthcoming</mark>', declared)
        self.assertNotIn('<mark class="target-word">forthed</mark>', declared)
        self.assertIn('<a class="sentence-jump"', declared)
        item["word_forms"] = "过去式: forthed"
        explicit = _fields(item, None, 5)[0]["Examples"]
        self.assertIn('<mark class="target-word">forthed</mark>', explicit)
        self.assertNotIn('<mark class="target-word">forthing</mark>', explicit)

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


class ClozeExampleRenderingTests(unittest.TestCase):
    def render(self, text, answers, *, word="rate", forms="rates, rated"):
        item = card(audio="")
        item["word"] = word
        item["word_forms"] = forms
        item["examples"][0].update(text=text, cloze_answers=answers)
        return _fields(item, None, 5)[0]["Examples"]

    def answer(self, text, word, number=1, *, last=False):
        start = text.rindex(word) if last else text.index(word)
        return {"start": start, "end": start + len(word), "word": word, "number": number}

    def test_only_the_actual_blank_occurrence_is_underlined(self):
        text = "The rate rose, but another rate fell."
        rendered = self.render(text, [self.answer(text, "rate", last=True)])
        self.assertIn('The <mark class="target-word">rate</mark> rose', rendered)
        self.assertIn('another <u class="cloze-answer" data-blank-number="1"><mark class="target-word">rate</mark></u> fell.', rendered)
        self.assertEqual(rendered.count('<u class="cloze-answer"'), 1)

    def test_multiple_answers_and_phrases_use_source_order(self):
        text = "A rate may rise in spite of limits."
        answers = [self.answer(text, "in spite of", 8), self.answer(text, "rate", 2)]
        rendered = self.render(text, answers)
        self.assertIn('<u class="cloze-answer" data-blank-number="8">in spite of</u>', rendered)
        self.assertLess(rendered.index('data-blank-number="2"'), rendered.index('data-blank-number="8"'))

    def test_target_word_highlighting_can_cross_a_blank_boundary(self):
        text = "Rates rise"
        rendered = self.render(text, [self.answer(text, "tes")])
        self.assertIn('<mark class="target-word">Ra</mark>', rendered)
        self.assertIn('<u class="cloze-answer" data-blank-number="1"><mark class="target-word">tes</mark></u>', rendered)

    def test_unicode_codepoint_offsets_and_html_are_preserved(self):
        text = "😀 rate <rate> & rate\nrate."
        rendered = self.render(text, [self.answer(text, "<rate>")])
        self.assertIn('😀 <mark class="target-word">rate</mark>', rendered)
        self.assertIn('<u class="cloze-answer" data-blank-number="1">&lt;<mark class="target-word">rate</mark>&gt;</u>', rendered)
        self.assertIn('&amp; <mark class="target-word">rate</mark><br>', rendered)
        self.assertNotIn('<rate>', rendered)

    def test_offsets_are_relative_to_the_supplied_text_before_edge_whitespace_trim(self):
        text = "  😀 rate. \n"
        rendered = self.render(text, [self.answer(text, "rate")])
        self.assertIn('😀 <u class="cloze-answer" data-blank-number="1"><mark class="target-word">rate</mark></u>.', rendered)

    def test_noncloze_rendering_is_unchanged_and_audio_jumps_ids_remain(self):
        item = card()
        before = _fields(item, None, 5)
        item["examples"][0]["cloze_answers"] = []
        self.assertEqual(_fields(item, None, 5), before)
        example = item["examples"][0]
        example.update(cloze_answers=[self.answer(example["text"], "rate")],
                       latex_url="http://localhost:8765/latex.htm?anki_word=rate#block-1",
                       full_paper_url="http://localhost:8765/full-paper.htm?anki_word=rate#block-1")
        fields, _, card_id = _fields(item, None, 5)
        self.assertEqual(card_id, before[2])
        self.assertEqual(fields["Audio"], "[sound:rate.mp3]")
        self.assertIn('<a class="sentence-jump"', fields["Examples"])
        self.assertIn('<u class="cloze-answer"', fields["Examples"])
        self.assertIn('<mark class="target-word">rate</mark>', fields["Examples"])

    def test_invalid_metadata_is_rejected(self):
        text = "rate rate"
        valid = self.answer(text, "rate")
        invalid = [None, {}, (), "rate", [None], [{}],
                   [{**valid, "start": True}], [{**valid, "end": 4.0}],
                   [{**valid, "number": True}], [{**valid, "number": "1"}],
                   [{**valid, "number": 0}], [{**valid, "start": -1}],
                   [{**valid, "end": len(text) + 1}], [{**valid, "end": 0}],
                   [{**valid, "word": "rates"}], [{**valid, "word": ""}],
                   [valid, valid], [valid, self.answer(text, "rate", last=True)],
                   [valid, {"start": 2, "end": 6, "word": text[2:6], "number": 2}]]
        for answers in invalid:
            with self.subTest(answers=answers), self.assertRaisesRegex(ValueError, "cloze"):
                self.render(text, answers)

    def test_zero_limit_renders_all_examples_in_fields_and_preview(self):
        item = card(audio="")
        item["examples"] = [{"text": f"The rate rose in sample {index}.", "source": "2020", "translation": "比率上升。"}
                            for index in range(8)]
        self.assertEqual(_fields(item, None, 0)[0]["Examples"].count('<li class="example-card">'), 8)
        preview = render_preview(item, max_examples=0)
        self.assertEqual(preview.count('<li class="example-card">'), 8)
        self.assertIn("sample 7.", preview)
        self.assertEqual(render_preview(item).count('<li class="example-card">'), 5)
        self.assertEqual(render_preview(item, max_examples=2).count('<li class="example-card">'), 2)

    def test_invalid_preview_example_limits_are_rejected(self):
        for maximum in (-1, True, 1.5, "0"):
            with self.subTest(maximum=maximum), self.assertRaisesRegex(ValueError, "max_examples"):
                render_preview(card(audio=""), max_examples=maximum)


if __name__ == "__main__":
    unittest.main()
