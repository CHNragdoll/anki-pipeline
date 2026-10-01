"""Temporary-config command tests exercise the offline local trial flow."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import zipfile

from anki_pipeline.cli import main, _guard_output
from anki_pipeline.config import load_config
from anki_pipeline.exam_library import digest
from anki_pipeline.store import upsert_cards


MP3 = b"\xff\xfb\x90\x64" + b"\x00" * 252


class ConfigAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config_path = self.root / "cfg" / "config.toml"
        self.config_path.parent.mkdir()
        self.write_config()

    def write_config(self, *, database: str = "../data/anki.sqlite3",
                     audio: str = "../data/audio") -> None:
        self.config_path.write_text(
            '[project]\nroot = ".."\n'
            '[paths]\n'
            f'database = "{database}"\n'
            'legacy_database = "../legacy/old.sqlite3"\n'
            'wordbook = "../legacy/book.xlsx"\n'
            f'audio = "{audio}"\n'
            'legacy_audio = "../legacy/audio"\n'
            'output = "../output"\n'
            'backups = "../backups"\n'
            '[deck]\nname = "Trial deck"\nmax_examples = 2\n',
            encoding="utf-8",
        )

    def test_config_paths_are_relative_to_config_file_and_old_targets_forbidden(self):
        config = load_config(self.config_path)
        self.assertEqual(config.database, self.root / "data" / "anki.sqlite3")
        self.assertEqual(config.audio, self.root / "data" / "audio")
        self.assertEqual(config.legacy_database, self.root / "legacy" / "old.sqlite3")
        self.write_config(database="../legacy/old.sqlite3")
        with self.assertRaisesRegex(ValueError, "原始"):
            load_config(self.config_path)
        self.write_config(audio="../legacy/audio")
        with self.assertRaisesRegex(ValueError, "原始"):
            load_config(self.config_path)

    def test_dictionary_sources_inside_project_cannot_be_output_targets(self):
        with self.config_path.open("a", encoding="utf-8") as stream:
            stream.write('[local_dictionary]\nroot = "../dictionary-unpacked"\n')
        config = load_config(self.config_path)
        for name in ("oald10/entries/source.html", "mw-now/resources/audio.mp3", "mw-now/original.apkg"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "受保护"):
                _guard_output(config.dictionary_root / name, config, self.config_path)
        _guard_output(config.output / "dictionary-media", config, self.config_path)

    def test_codex_source_is_explicit_and_its_index_root_is_config_relative(self):
        with self.config_path.open('a', encoding='utf-8') as stream:
            stream.write('[exam_library]\nroot="../exams"\nsentence_source="codex"\n'
                         'codex_index_root="../staging"\n')
        config = load_config(self.config_path)
        self.assertEqual(config.exam_sentence_source, 'codex')
        self.assertEqual(config.codex_index_root, self.root / 'staging')
        for source in ('legacy', 'unknown'):
            self.write_config()
            with self.config_path.open('a', encoding='utf-8') as stream:
                stream.write('[exam_library]\nsentence_source="' + source + '"\n'
                             'codex_index_root="../staging"\n')
            with self.assertRaisesRegex(ValueError, 'codex|sentence_source'):
                load_config(self.config_path)

    def test_codex_completion_inputs_follow_configured_project_or_config_file(self):
        with self.config_path.open('a', encoding='utf-8') as stream:
            stream.write('[exam_library]\nroot="../exams"\nsentence_source="codex"\n')
        config = load_config(self.config_path)
        self.assertEqual(config.reading_completion_path,
                         self.root / 'data/reading-completions-v1.json')
        with self.config_path.open('a', encoding='utf-8') as stream:
            stream.write('reading_completion_path="../approved/completions.json"\n')
        config = load_config(self.config_path)
        self.assertEqual(config.reading_completion_path,
                         self.root / 'approved/completions.json')
        joined = config.reading_completion_path.with_name('reading-option-translations-v1.json')
        for source_input in (config.reading_completion_path,
                             config.reading_completion_path.with_suffix('.review.json'),
                             joined, joined.with_suffix('.review.json'),
                             self.root / 'output/reading-option-translation-review/author.json'):
            with self.subTest(source_input=source_input), self.assertRaisesRegex(ValueError, '受保护'):
                _guard_output(source_input, config, self.config_path)
        for source in ('legacy', 'unknown'):
            self.write_config()
            with self.config_path.open('a', encoding='utf-8') as stream:
                stream.write('[exam_library]\nsentence_source="' + source + '"\n'
                             'reading_completion_path="../approved/completions.json"\n')
            with self.assertRaisesRegex(ValueError, 'codex|sentence_source'):
                load_config(self.config_path)

    def test_deck_display_name_can_change_without_replacing_its_identity(self):
        self.assertIsNone(load_config(self.config_path).deck_identity_name)
        with self.config_path.open('a', encoding='utf-8') as stream:
            stream.write('identity_name="Original deck identity"\n')
        config = load_config(self.config_path)
        self.assertEqual(config.deck_name, 'Trial deck')
        self.assertEqual(config.deck_identity_name, 'Original deck identity')
        for value in ('""', '"   "', 'false', '123'):
            with self.subTest(value=value):
                self.write_config()
                with self.config_path.open('a', encoding='utf-8') as stream:
                    stream.write('identity_name=' + value + '\n')
                with self.assertRaisesRegex(ValueError, 'deck.identity_name'):
                    load_config(self.config_path)

    def test_build_and_web_preview_use_the_configured_codex_completion_inputs(self):
        with self.config_path.open('a', encoding='utf-8') as stream:
            stream.write('[exam_library]\nroot="../exams"\nsentence_source="codex"\n'
                         'reading_completion_path="../approved/completions.json"\n')
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / 'rate.mp3').write_bytes(MP3)
        upsert_cards(config.database, [{
            'sheet': 'Unit 1', 'lesson': 'Lesson 1', 'position': '1', 'word': 'rate',
            'phonetic': '/reɪt/', 'definition': 'n. 比率', 'audio_filename': 'rate.mp3',
        }], config.backups)

        def external_library(root, cards, base_url, reader, maximum, **inputs):
            self.assertEqual(root, config.exam_library)
            self.assertEqual(inputs['reading_completion_path'],
                             self.root / 'approved/completions.json')
            return cards, {'examples': 0, 'database_modified': False}

        for command in ('build', 'web-preview'):
            with self.subTest(command=command), \
                    patch('anki_pipeline.exam_library.library_examples', side_effect=external_library) as library, \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--config', str(self.config_path), command]), 0)
                library.assert_called_once()

    def test_etymology_config_and_source_output_guard(self):
        with self.config_path.open("a", encoding="utf-8") as stream:
            stream.write('[etymology]\nroot = "../dictionary-unpacked/cigen-en-new"\n')
        config = load_config(self.config_path)
        self.assertEqual(config.cigen_root, self.root / "dictionary-unpacked/cigen-en-new")
        for name in ('dictionary.sqlite3', 'entries/source.html', 'lookup.py'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "受保护"):
                _guard_output(config.cigen_root / name, config, self.config_path)

    def test_offline_bundle_enriches_once_and_delivers_web_apkg_zip_without_database_writes(self):
        with self.config_path.open("a", encoding="utf-8") as stream:
            stream.write('[local_dictionary]\nroot = "../dictionary-unpacked"\n')
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        upsert_cards(config.database, [{
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }], config.backups)
        original = config.database.read_bytes()
        def enrich(cards, dictionary_root, media):
            media.mkdir(parents=True)
            for name in ("oxford.mp3", "webster.mp3"):
                (media / name).write_bytes(MP3)
            for source in cards:
                source["local_dictionary"] = {
                    "senses": [{"pos": "n.", "text": "比率"}], "forms": [], "derived": [],
                    "audio": {"oxford": [{"filename": "oxford.mp3", "accent": "us"}],
                              "webster": [{"filename": "webster.mp3", "accent": "us"}]}}
            return cards, {"counts": {"cards": len(cards)}, "missing": []}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("anki_pipeline.local_dictionary.enrich_dictionary_cards", side_effect=enrich) as adapter:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["--config", str(self.config_path), "offline-bundle"])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(adapter.call_count, 1)
        self.assertEqual(config.database.read_bytes(), original)
        for name in ("Anki-本地双词典版.apkg", "Anki-完整网页预览.zip", "preview-library.html",
                     "preview-library-cloze.html", "dictionary-delivery-report.json"):
            self.assertTrue((config.output / name).is_file(), name)
        delivery = json.loads((config.output / "dictionary-delivery-report.json").read_text())
        self.assertEqual(delivery["package"]["audio_count"], 2)
        self.assertEqual(delivery["web"]["counts"]["cards"], 1)

    def test_check_and_build_write_report_package_and_preview(self):
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        upsert_cards(config.database, [{
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }], config.backups)
        report = self.root / "reports" / "quality.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            check_code = main(["--config", str(self.config_path), "check", "--report", str(report)])
        self.assertEqual(check_code, 0, stderr.getvalue())
        self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["ok"])
        output = config.output / "trial.apkg"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            build_code = main(["--config", str(self.config_path), "build", "--file", str(output)])
        self.assertEqual(build_code, 0, stderr.getvalue())
        self.assertTrue(output.is_file())
        with zipfile.ZipFile(output) as archive:
            self.assertIn("collection.anki2", archive.namelist())
            self.assertIn("media", archive.namelist())
        self.assertTrue((config.output / "preview.html").is_file())
        build_report = json.loads((config.output / "build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(build_report["quality"]["cards"], 1)

    def test_exam_library_build_and_preview_include_all_years_without_database_writes(self):
        with self.config_path.open("a", encoding="utf-8") as stream:
            stream.write('[exam_library]\nroot = "../exam-library"\n'
                         'base_url = "http://localhost:8765"\nmax_examples = 0\n')
        config = load_config(self.config_path)
        self.assertEqual(config.max_examples, 2)
        self.assertEqual(config.exam_max_examples, 0)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        upsert_cards(config.database, [{
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }], config.backups)
        database_before = config.database.read_bytes()

        index = config.exam_library / "data/sources/exam-library/structured/anki-sentences"
        (index / "kaoyan").mkdir(parents=True)
        entries = []
        for year in range(2000, 2007):
            paper_id = f"kaoyan:{year}-01"
            text = "The rate rose."
            translation = "比率上升了。"
            row = {"id": paper_id + ":p:b-1-5", "paperId": paper_id,
                   "title": f"{year}年考研英语", "kind": "reading",
                   "sourcePath": f"{year}年考研英语 ➫ Section II ➫ Part A ➫ Text 5",
                   "sourceText": text, "sourceHash": digest(text),
                   "text": text, "textHash": digest(text), "sentences": [text],
                   "sentenceTranslations": [translation],
                   "sentenceTranslationHashes": [digest(translation)]}
            data = {"schema": "anki-sentence-index.v1", "paperId": paper_id,
                    "paragraphs": [row], "excluded": []}
            path = index / "kaoyan" / f"{year}-01.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            entries.append({"paperId": paper_id, "path": "kaoyan/" + path.name,
                            "digest": digest(json.dumps(data, sort_keys=True,
                                                        ensure_ascii=False))})
        catalog = {"schema": "anki-sentence-catalog.v1", "category": "kaoyan",
                   "papers": entries}
        (index / "index.json").write_text(json.dumps(catalog), encoding="utf-8")

        output = config.output / "all-years.apkg"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config_path), "build", "--file", str(output)])
        self.assertEqual(code, 0, stderr.getvalue())
        report = json.loads((config.output / "build-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["exam_library"]["examples"], 7)
        self.assertEqual(config.database.read_bytes(), database_before)
        self.assertEqual((config.output / "preview.html").read_text().count(
            '<li class="example-card">'), 7)
        with zipfile.ZipFile(output) as archive:
            collection = self.root / "built-collection.anki2"
            collection.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(collection) as connection:
            fields = connection.execute("SELECT flds FROM notes").fetchone()[0]
        self.assertEqual(fields.count('<li class="example-card">'), 7)

        package_before = output.read_bytes()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config_path), "web-preview"])
        self.assertEqual(code, 0, stderr.getvalue())
        web_report = json.loads((config.output / "web-preview-report.json").read_text())
        catalog = json.loads((config.output / web_report["catalog_url"]).read_text())
        self.assertEqual(web_report["exam_library"]["examples"], 7)
        self.assertEqual(catalog["cards"][0]["exampleCount"], 7)
        self.assertEqual((config.output / catalog["cards"][0]["previewUrl"]).read_text().count(
            '<li class="example-card">'), 7)
        self.assertEqual(config.database.read_bytes(), database_before)
        self.assertEqual(output.read_bytes(), package_before)

    def test_exam_example_limit_must_be_nonnegative_integer(self):
        for value in ("-1", "true", "1.5"):
            with self.subTest(value=value):
                self.write_config()
                with self.config_path.open("a", encoding="utf-8") as stream:
                    stream.write(f"[exam_library]\nmax_examples = {value}\n")
                with self.assertRaisesRegex(ValueError, "exam_library.max_examples"):
                    load_config(self.config_path)

    def test_web_preview_includes_every_deck_without_rebuilding_package_or_database(self):
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        upsert_cards(config.database, [{
            "sheet": f"Unit {unit}", "lesson": "Lesson 1", "position": "1",
            "word": word, "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        } for unit, word in ((1, "rate"), (2, "speed"))], config.backups)
        database_before = config.database.read_bytes()
        config.output.mkdir()
        old_package = config.output / "old.apkg"
        old_package.write_bytes(b"existing card package")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config_path), "web-preview"])
        self.assertEqual(code, 0, stderr.getvalue())
        report = json.loads((config.output / "web-preview-report.json").read_text())
        catalog = json.loads((config.output / report["catalog_url"]).read_text())
        self.assertEqual(catalog["counts"]["cards"], 2)
        self.assertEqual(catalog["counts"]["decks"], 2)
        self.assertEqual(config.database.read_bytes(), database_before)
        self.assertEqual(old_package.read_bytes(), b"existing card package")
        self.assertEqual(list(config.output.glob("*.apkg")), [old_package])
        self.assertTrue((config.output / "preview-library.html").is_file())
        for card in catalog["cards"]:
            self.assertTrue((config.output / card["previewUrl"]).is_file())

    def test_web_preview_rejects_source_path_before_reading_database(self):
        config = load_config(self.config_path)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config_path), "web-preview", "--file",
                         str(config.database)])
        self.assertEqual(code, 2)
        self.assertIn("受保护", stderr.getvalue())
        self.assertFalse(config.database.exists())

    def test_web_preview_source_change_preserves_previous_entry_and_report(self):
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        upsert_cards(config.database, [{
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }], config.backups)
        config.output.mkdir()
        entry = config.output / "preview-library.html"
        report = config.output / "web-preview-report.json"
        entry.write_bytes(b"previous working entry")
        report.write_bytes(b"previous working report")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("anki_pipeline.cli.logical_digest", side_effect=["before", "after"]), \
                redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["--config", str(self.config_path), "web-preview"])
        self.assertEqual(code, 2)
        self.assertIn("数据库内容发生变化", stderr.getvalue())
        self.assertEqual(entry.read_bytes(), b"previous working entry")
        self.assertEqual(report.read_bytes(), b"previous working report")


if __name__ == "__main__":
    unittest.main()
