"""Offline dictionary payloads preserve the existing Anki import contract."""
import copy
import html
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from anki_pipeline.packaging import _fields, build_package, render_preview
from anki_pipeline.web_preview import build_web_preview
from anki_pipeline.web_bundle import build_web_bundle


def card():
    return {"id": "stable-id", "sheet": "Unit 1", "lesson": "1", "position": "1",
            "word": "ambition", "phonetic": "/æmˈbɪʃən/", "definition": "旧核心",
            "simple_definition": "旧简明", "level": "考研", "word_forms": "旧词形",
            "audio_filename": "absent-legacy.mp3", "examples": [],
            "local_dictionary": {
                "senses": [{"pos": "n.", "text": "追求的目标；夙愿"}],
                "forms": [{"label": "复数", "form": "ambitions"}],
                "derived": [{"label": "形容词", "word": "ambitious"}],
                "audio": {"oxford": [{"filename": "oxford.mp3", "accent": "us"}],
                          "webster": [{"filename": "webster.mp3", "accent": "us"}]}}}


def ecdict_data():
    return {"translation": "v. 伸出；突出", "forms": [
                {"kind": "plural", "label": "复数", "form": "ambitions", "source": "ecdict"}],
            "derived": [], "tags": ["zk", "cet4"], "tag_labels": ["中考", "CET4"],
            "provenance": {"source": "ecdict", "word": "ambition", "license_text":
                "MIT License\nCopyright (c) 2017 skywind3000\n"
                "Permission is hereby granted, free of charge, to any person obtaining a copy "
                "of this software and associated documentation files (the Software), to deal "
                "in the Software without restriction, including without limitation the rights "
                "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell "
                "copies of the Software, and to permit persons to whom the Software is "
                "furnished to do so, subject to the following conditions:\n"
                "The above copyright notice and this permission notice shall be included in "
                "all copies or substantial portions of the Software.\n"
                "THE SOFTWARE IS PROVIDED AS IS, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR "
                "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, "
                "FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE "
                "AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER "
                "LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING "
                "FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER "
                "DEALINGS IN THE SOFTWARE."}}


class DictionaryPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.audio = self.root / "audio"
        self.audio.mkdir()
        for name in ("oxford.mp3", "webster.mp3"):
            (self.audio / name).write_bytes(b"ID3" + name.encode())

    def test_package_bundles_both_sources_in_existing_ten_fields(self):
        source = card()
        before = copy.deepcopy(source)
        target = self.root / "new.apkg"
        report = build_package([source], self.audio, target)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(set(json.loads(archive.read("media")).values()),
                             {"oxford.mp3", "webster.mp3"})
            database = self.root / "collection.anki2"
            database.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(database) as connection:
            fields = connection.execute("SELECT flds FROM notes").fetchone()[0].split("\x1f")
            model = next(iter(json.loads(connection.execute("SELECT models FROM col").fetchone()[0]).values()))
        self.assertEqual(len(fields), 10)
        self.assertEqual(int(model["id"]), 1552983369)
        self.assertIn("dictionary-definition", fields[2])
        self.assertEqual(fields[3], "")
        self.assertIn("ambitious", fields[5])
        self.assertIn('class="dictionary-inflections"', fields[5])
        self.assertIn('class="dictionary-derived"', fields[5])
        self.assertIn('派生词与词族', fields[5])
        self.assertNotIn("旧词形", fields[5])
        self.assertIn('src="oxford.mp3"', fields[6])
        self.assertIn('src="webster.mp3"', fields[6])
        self.assertNotIn("[sound:", fields[6])
        self.assertNotIn("localhost:8770", "".join(fields))
        self.assertEqual(report["audio_count"], 2)
        self.assertEqual(source, before)

    def test_web_manifest_contains_both_audio_sets_and_oxford_search_text(self):
        report = build_web_preview([card()], self.audio, self.root / "preview.html", deck_name="考研英语")
        version = Path(report["version_directory"])
        manifest = json.loads((version / "manifest.json").read_text())
        self.assertEqual(manifest["media_count"], 2)
        self.assertIn("cards/oxford.mp3", manifest["files"])
        self.assertIn("cards/webster.mp3", manifest["files"])
        catalog = json.loads((version / "catalog.json").read_text())
        self.assertEqual(catalog["cards"][0]["definition"], "n. 追求的目标；夙愿")
        page = (self.root / catalog["cards"][0]["previewUrl"]).read_text()
        self.assertIn('src="oxford.mp3"', page)
        self.assertIn('src="webster.mp3"', page)
        self.assertNotIn("旧核心", page)
        self.assertNotIn("data:audio", page)

    def test_missing_selected_source_is_explicit_and_no_legacy_substitution(self):
        source = card()
        source["local_dictionary"]["audio"]["oxford"] = []
        source["local_dictionary"]["senses"] = []
        page = render_preview(source, self.audio)
        self.assertIn("牛津原包未收录", page)
        self.assertNotIn('data-dictionary-source="oxford"', page)
        self.assertIn('data-dictionary-source="webster"', page)
        self.assertNotIn("absent-legacy.mp3", page)

    def test_missing_other_source_fails_before_replacing_existing_package(self):
        target = self.root / "new.apkg"
        target.write_bytes(b"previous")
        (self.audio / "webster.mp3").unlink()
        with self.assertRaises(FileNotFoundError):
            build_package([card()], self.audio, target)
        self.assertEqual(target.read_bytes(), b"previous")

    def test_untrusted_dictionary_content_is_escaped(self):
        source = card()
        source["local_dictionary"]["senses"][0]["text"] = '<img src=x onerror="bad">'
        source["local_dictionary"]["forms"][0]["form"] = "<script>bad</script>"
        page = render_preview(source)
        self.assertIn("&lt;img", page)
        self.assertNotIn('<img src=x', page)
        self.assertNotIn('<script>bad', page)

    def test_ecdict_tags_replace_only_display_levels_and_keep_oxford_webster_content(self):
        source = card()
        baseline, _, _ = _fields(source, None, 0)
        source["ecdict"] = ecdict_data()
        source["local_dictionary"].update(forms_source="webster", derived_source="webster")
        before = copy.deepcopy(source)
        fields, _, identity = _fields(source, None, 0)
        self.assertIn('<li>中考</li>', fields["Level"])
        self.assertIn('<li>CET4</li>', fields["Level"])
        self.assertNotIn('考研', fields["Level"])
        self.assertEqual(fields["Definition"], baseline["Definition"])
        self.assertEqual(fields["WordForms"], baseline["WordForms"])
        self.assertEqual(fields["Audio"], baseline["Audio"])
        self.assertEqual(identity, "stable-id")
        self.assertEqual(len(fields), 10)
        self.assertEqual(source, before)

    def test_ecdict_empty_tags_never_inherit_the_old_level(self):
        source = card()
        source["ecdict"] = ecdict_data()
        source["ecdict"].update(tags=[], tag_labels=[])
        fields, _, _ = _fields(source, None, 0)
        self.assertNotIn("考研", fields["Level"])
        self.assertIn("ECDICT 未标注考试标签", fields["Level"])

    def test_ecdict_complete_license_is_hidden_and_preserved_in_both_exports(self):
        source = card()
        source["ecdict"] = ecdict_data()
        source["ecdict"].update(tags=[], tag_labels=[])
        # Treat the whole supplied notice as data; markup cannot execute even
        # when a source-specific copyright attribution includes angle brackets.
        license_text = source["ecdict"]["provenance"]["license_text"] + '\nCopyright <owner> & "co"'
        source["ecdict"]["provenance"]["license_text"] = license_text
        escaped = html.escape(license_text, quote=True)
        fields, _, _ = _fields(source, None, 0)
        expected = '<div class="ecdict-license-notice" hidden aria-hidden="true">' + escaped + '</div>'
        self.assertIn(expected, fields["Level"])
        self.assertEqual(''.join(fields.values()).count('class="ecdict-license-notice"'), 1)
        self.assertNotIn('<owner>', fields["Level"])
        page = render_preview(source, self.audio)
        self.assertEqual(page.count(expected), 1)
        target = self.root / "ecdict.apkg"
        build_package([source], self.audio, target)
        with zipfile.ZipFile(target) as archive:
            database = self.root / "ecdict.anki2"
            database.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(database) as connection:
            exported = connection.execute("SELECT flds FROM notes").fetchone()[0].split("\x1f")
        self.assertEqual(len(exported), 10)
        self.assertEqual(exported[4], fields["Level"])
        self.assertEqual(''.join(exported).count(expected), 1)

    def test_example_highlights_only_the_selected_explicit_inflections(self):
        source = card()
        source["word_forms"] = "复数 ambitions; 现在分词 ambitioning"
        source["local_dictionary"].update(
            forms=[{"kind": "plural", "label": "复数", "form": "ambitions"}],
            forms_source="webster")
        source["examples"] = [{"text": "Ambition ambitions ambitious ambitioning.",
                               "translation": "对应句子译文", "source": "2020 年"}]
        before = copy.deepcopy(source)
        fields, _, _ = _fields(source, None, 0)
        expected = ('<mark class="target-word">Ambition</mark> '
                    '<mark class="target-word">ambitions</mark> ambitious ambitioning.')
        self.assertIn(expected, fields["Examples"])
        self.assertEqual(source, before)
        source["ecdict"] = ecdict_data()
        source["local_dictionary"].update(forms=copy.deepcopy(source["ecdict"]["forms"]), forms_source="ecdict")
        fallback_fields, _, _ = _fields(source, None, 0)
        self.assertEqual(fallback_fields["Examples"], fields["Examples"])

    def test_no_explicit_dictionary_forms_does_not_infer_or_use_the_legacy_forms(self):
        source = card()
        source["word_forms"] = "复数 ambitions; 现在分词 ambitioning"
        source["local_dictionary"].update(forms=[], forms_source="")
        source["examples"] = [{"text": "Ambition ambitions ambitious ambitioning.",
                               "translation": "对应句子译文", "source": "2020 年"}]
        fields, _, _ = _fields(source, None, 0)
        self.assertIn('<mark class="target-word">Ambition</mark> ambitions ambitious ambitioning.', fields["Examples"])
        self.assertEqual(fields["Examples"].count('<mark'), 1)

    def test_declared_ecdict_definition_fallback_is_escaped_and_has_no_duplicate_definition(self):
        source = card()
        source["ecdict"] = ecdict_data()
        source["ecdict"]["translation"] = 'v. <img src=x onerror="bad">；突出'
        source["local_dictionary"].update(senses=[], definition_source="ecdict",
            definition_fallback=source["ecdict"]["translation"])
        fields, _, _ = _fields(source, None, 0)
        self.assertIn('data-dictionary="ecdict"', fields["Definition"])
        self.assertIn('&lt;img', fields["Definition"])
        self.assertNotIn('<img', fields["Definition"])
        self.assertNotIn("旧核心", fields["Definition"])
        self.assertEqual(fields["SimpleDefinition"], "")

    def test_only_explicit_ecdict_forms_fill_the_empty_inflection_block(self):
        source = card()
        source["ecdict"] = ecdict_data()
        payload = source["local_dictionary"]
        payload.update(forms=copy.deepcopy(source["ecdict"]["forms"]), forms_source="ecdict", derived_source="webster")
        fields, _, _ = _fields(source, None, 0)
        markup = fields["WordForms"]
        self.assertIn('class="dictionary-inflections"', markup)
        self.assertIn('class="dictionary-derived"', markup)
        self.assertIn('派生词与词族', markup)
        self.assertIn("ambitious", markup)
        self.assertEqual(markup.count("ECDICT 补充"), 1)
        self.assertIn('data-dictionary="ecdict"', markup)
        self.assertNotIn("旧词形", markup)

    def test_explicit_ecdict_derived_words_have_their_own_block_and_are_escaped(self):
        source = card()
        source["ecdict"] = ecdict_data()
        rows = [{"label": "形容词", "word": '<script>bad</script>', "source": "ecdict"}]
        source["ecdict"]["derived"] = rows
        source["local_dictionary"].update(derived=copy.deepcopy(rows), forms_source="webster", derived_source="ecdict")
        fields, _, _ = _fields(source, None, 0)
        markup = fields["WordForms"]
        self.assertIn('class="dictionary-derived"', markup)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", markup)
        self.assertNotIn("<script>", markup)
        self.assertEqual(markup.count("ECDICT 补充"), 1)

    def test_ecdict_tag_labels_are_escaped_as_individual_labels(self):
        source = card()
        source["ecdict"] = ecdict_data()
        source["ecdict"]["tag_labels"] = ['<img src=x>', 'A | B']
        fields, _, _ = _fields(source, None, 0)
        self.assertIn('&lt;img src=x&gt;', fields["Level"])
        self.assertIn('<li>A | B</li>', fields["Level"])
        self.assertEqual(fields["Level"].count('<li>'), 2)
        self.assertNotIn('<img', fields["Level"])

    def test_invalid_ecdict_payloads_and_fallback_metadata_are_rejected(self):
        mutations = [
            lambda value: value.update(ecdict=None),
            lambda value: value["ecdict"].update(tag_labels="考研"),
            lambda value: value["ecdict"].update(tags=[True]),
            lambda value: value["ecdict"].update(provenance=[]),
            lambda value: value["ecdict"]["provenance"].update(license_text=None),
            lambda value: value["local_dictionary"].update(forms_source="guessed"),
            lambda value: value["local_dictionary"].update(forms_source=[]),
            lambda value: value["local_dictionary"].update(derived_source="guessed"),
            lambda value: value["local_dictionary"].update(definition_source=[]),
            lambda value: value["local_dictionary"].update(definition_source="ecdict", definition_fallback="v. 伸出"),
            lambda value: value["local_dictionary"].update(forms_source="", forms=[{"label": "复数", "form": "ambitions"}]),
            lambda value: value["local_dictionary"].update(forms_source="ecdict", forms=[{"label": "现在分词", "form": "ambitioning", "source": "ecdict"}]),
            lambda value: value["local_dictionary"].update(forms_source="ecdict", forms=[{"label": [], "form": "ambitions", "source": "ecdict"}]),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                source = card()
                source["ecdict"] = ecdict_data()
                mutate(source)
                with self.assertRaises(ValueError):
                    _fields(source, None, 0)
        source = card()
        source["local_dictionary"].update(senses=[], definition_source="ecdict", definition_fallback="v. 伸出")
        with self.assertRaises(ValueError):
            _fields(source, None, 0)

    def test_declared_fallback_preserves_real_audio_and_wordbook_catalog(self):
        source = card()
        payload = source["local_dictionary"]
        payload.update(senses=[], definition_source="wordbook",
                       definition_fallback="v. 伸出；突出", fallback_audio={"oxford": "webster"})
        payload["audio"]["oxford"] = []
        report = build_web_preview([source], self.audio, self.root / "preview.html", deck_name="考研英语")
        version = Path(report["version_directory"])
        catalog = json.loads((version / "catalog.json").read_text())
        self.assertEqual(catalog["cards"][0]["definition"], "v. 伸出；突出")
        page = (self.root / catalog["cards"][0]["previewUrl"]).read_text()
        self.assertIn('data-dictionary="wordbook"', page)
        self.assertIn('data-fallback-oxford="webster"', page)
        self.assertIn('data-dictionary-source="webster"', page)
        self.assertNotIn('data-dictionary-source="oxford"', page)
        self.assertNotIn('src="oxford.mp3"', page)

    def test_publish_callback_failure_preserves_existing_package(self):
        target = self.root / "new.apkg"
        target.write_bytes(b"previous")
        def fail():
            raise ValueError("source changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            build_package([card()], self.audio, target, before_publish=fail)
        self.assertEqual(target.read_bytes(), b"previous")

    def test_portable_bundle_contains_all_versioned_media_and_executable_launcher(self):
        report = build_web_preview([card()], self.audio, self.root / "preview.html", deck_name="考研英语")
        output = self.root / "complete.zip"
        build_web_bundle(report, output)
        with zipfile.ZipFile(output) as archive:
            base = "Anki-完整网页预览/"
            prefix = base + "web-preview/" + report["input_digest"] + "/"
            self.assertEqual(archive.read(prefix + "cards/oxford.mp3"), (self.audio / "oxford.mp3").read_bytes())
            self.assertEqual(archive.read(prefix + "cards/webster.mp3"), (self.audio / "webster.mp3").read_bytes())
            self.assertIn("ThreadingHTTPServer", archive.read(base + "serve_preview.py").decode())
            self.assertEqual(archive.getinfo(base + "启动网页预览.command").external_attr >> 16 & 0o777, 0o755)
            self.assertIsNone(archive.testzip())
        previous = output.read_bytes()
        (Path(report["version_directory"]) / "cards/webster.mp3").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            build_web_bundle(report, output)
        self.assertEqual(output.read_bytes(), previous)


if __name__ == "__main__":
    unittest.main()
