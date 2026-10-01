"""File, catalog and failure contracts for the complete static vocabulary library."""

from functools import partial
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urljoin
from urllib.request import urlopen

from anki_pipeline import web_preview
from anki_pipeline.packaging import _lesson_deck_name, _stable_numeric_id, render_preview


def card(card_id="1", *, unit="Unit 2", lesson="Lesson 10", position="1",
         word="rate", audio="rate.mp3", examples=1):
    return {
        "id": card_id, "sheet": unit, "lesson": lesson, "position": position,
        "word": word, "phonetic": "/reɪt/", "definition": "n. 比率\nv. 评价",
        "simple_definition": "比率", "level": "CET-4", "word_forms": "rates, rated",
        "audio_filename": audio,
        "examples": [{"text": f"The rate rose in sample {index}.", "source": "2020 考研",
                      "translation": f"比率上升了 {index}。"} for index in range(examples)],
    }


class AudioSources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "audio":
            self.sources.append(dict(attrs)["src"])


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class WebPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "audio"
        self.audio.mkdir()
        (self.audio / "rate.mp3").write_bytes(b"ID3\0recording")
        self.output = self.root / "preview-library.html"
        self.templates = self.root / "templates"
        self.templates.mkdir()
        (self.templates / "library-preview.html").write_text(
            '<!doctype html><html><head><link rel="stylesheet" '
            'href="__ASSET_BASE__library-preview.css"></head>'
            '<body data-catalog-url="__CATALOG_URL__"><main id="library"></main>'
            '<script src="__ASSET_BASE__library-preview.js"></script></body></html>',
            encoding="utf-8")
        (self.templates / "library-preview.css").write_text("body { color: #123; }", encoding="utf-8")
        (self.templates / "library-preview.js").write_text("'use strict';", encoding="utf-8")
        self.template_patch = patch.object(web_preview, "_UI_TEMPLATE_DIR", self.templates)
        self.template_patch.start()
        self.addCleanup(self.template_patch.stop)

    def build(self, cards=None, **kwargs):
        return web_preview.build_web_preview(
            cards if cards is not None else [card()], self.audio, self.output,
            deck_name="考研英语", **kwargs)

    def catalog(self, report):
        return json.loads((self.root / report["catalog_url"]).read_text(encoding="utf-8"))

    def versions(self):
        base = self.root / "web-preview"
        return sorted(path.name for path in base.iterdir() if not path.name.startswith(".")) if base.exists() else []

    def test_alignment_renderer_change_creates_a_new_immutable_version(self):
        checksum = web_preview._file_checksum
        revision = ["a" * 64]
        def changed_helper(path):
            return revision[0] if path.name == "translation_alignment.py" else checksum(path)
        with patch.object(web_preview, "_file_checksum", side_effect=changed_helper):
            first = self.build()
            revision[0] = "b" * 64
            second = self.build()
        self.assertNotEqual(first["input_digest"], second["input_digest"])
        self.assertEqual(len(self.versions()), 2)

    def test_natural_source_order_empty_card_counts_and_package_deck_ids(self):
        cards = [card("later", unit="Unit 10", lesson="2", position="1"),
                 card("position10", lesson="2", position="10", examples=2),
                 card("position2", lesson="2", position="2", examples=0, audio=""),
                 card("lesson10", lesson="10", position="1"),
                 card("unknown", unit="Unit 999 未分类", lesson="待分配", examples=0)]
        report = self.build(cards)
        catalog = self.catalog(report)
        self.assertEqual(catalog["schema"], "anki-web-catalog.v1")
        self.assertEqual(catalog["deckName"], "考研英语")
        self.assertEqual(catalog["defaultReader"], "latex")
        self.assertEqual(catalog["counts"], {"cards": 5, "decks": 4, "examples": 4})
        self.assertEqual([row["id"] for row in catalog["cards"]],
                         ["position2", "position10", "lesson10", "later", "unknown"])
        self.assertEqual(catalog["decks"][0]["cardIds"], ["position2", "position10"])
        for source in cards:
            name = _lesson_deck_name("考研英语", source)
            row = next(row for row in catalog["cards"] if row["id"] == source["id"])
            self.assertEqual(row["deckName"], name)
            self.assertEqual(row["deckId"], str(_stable_numeric_id("deck", name)))
            self.assertEqual(row["unit"], source["sheet"])
            self.assertEqual(row["lesson"], source["lesson"])
            self.assertEqual(row["position"], str(source["position"]))
            self.assertTrue((self.root / row["previewUrl"]).is_file())
        self.assertEqual(catalog["cards"][-1]["unit"], "Unit 999 未分类")
        self.assertEqual(report["card_count"], 5)
        self.assertEqual(report["audio_count"], 1)
        manifest = json.loads(Path(report["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"], catalog["counts"])
        self.assertEqual(manifest["media_count"], 1)
        self.assertEqual(manifest["input_digest"], report["input_digest"])
        self.assertEqual(len(manifest["files"]), 9)  # catalog, five cards, one MP3, two UI assets
        self.assertNotIn("__CATALOG_URL__", self.output.read_text(encoding="utf-8"))
        self.assertIn(report["catalog_url"], self.output.read_text(encoding="utf-8"))

    def test_all_examples_and_same_card_renderer_without_embedded_audio(self):
        source = card("../../source ID", word="rate\nrating", examples=9)
        report = self.build([source])
        catalog = self.catalog(report)
        row = catalog["cards"][0]
        page = (self.root / row["previewUrl"]).read_text(encoding="utf-8")
        self.assertEqual(page, render_preview(source, audio_dir=None, max_examples=0))
        self.assertEqual(page.count('<li class="example-card">'), 9)
        self.assertIn("sample 8.", page)
        self.assertEqual(row["exampleCount"], 9)
        self.assertEqual(row["word"], "rate\nrating")
        self.assertRegex(Path(row["previewUrl"]).name, r"^[0-9a-f]{64}\.html$")
        self.assertNotIn("data:audio", page)
        self.assertNotIn("file://", page)
        self.assertEqual((self.root / row["previewUrl"]).with_name("rate.mp3").read_bytes(),
                         b"ID3\0recording")

    def test_non_ascii_and_url_sensitive_audio_filename_resolves_over_http(self):
        filename = '录音 #?% "音色".mp3'
        (self.audio / filename).write_bytes(b"ID3\0unicode")
        report = self.build([card(audio=filename)])
        row = self.catalog(report)["cards"][0]
        parser = AudioSources()
        parser.feed((self.root / row["previewUrl"]).read_text(encoding="utf-8"))
        self.assertTrue(parser.sources)
        self.assertEqual(unquote(parser.sources[0]), filename)
        self.assertNotIn("#", parser.sources[0])
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(self.root)))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            page_url = f"http://127.0.0.1:{server.server_port}/{row['previewUrl']}"
            with urlopen(urljoin(page_url, parser.sources[0]), timeout=3) as response:
                self.assertEqual(response.read(), b"ID3\0unicode")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_malicious_content_stays_escaped_and_catalog_is_external_json(self):
        source = card(word='<img src=x onerror=alert(1)>\nrate', audio="")
        source["definition"] = '<script>alert("definition")</script>'
        source["examples"][0]["translation"] = '<svg onload=alert(2)>'
        report = self.build([source])
        row = self.catalog(report)["cards"][0]
        page = (self.root / row["previewUrl"]).read_text(encoding="utf-8")
        self.assertNotIn('<img src=x onerror=alert(1)>', page)
        self.assertNotIn('<script>alert("definition")</script>', page)
        self.assertNotIn('<svg onload=alert(2)>', page)
        self.assertIn('&lt;svg onload=alert(2)&gt;', page)
        self.assertEqual(row["word"], source["word"])
        self.assertNotIn("alert(1)", self.output.read_text(encoding="utf-8"))

    def test_bad_cards_media_duplicates_and_hash_collisions_preserve_entry(self):
        self.output.write_bytes(b"old entry")
        invalid = [[card(), card()], [card(audio="../outside.mp3")],
                   [card(audio="missing.mp3")], [card(audio="empty.mp3")],
                   [card(examples=0), {**card("late"), "examples": [None]}]]
        (self.audio / "empty.mp3").write_bytes(b"")
        for inputs in invalid:
            with self.subTest(inputs=inputs), self.assertRaises((ValueError, FileNotFoundError)):
                self.build(inputs)
            self.assertEqual(self.output.read_bytes(), b"old entry")
            self.assertFalse((self.root / "web-preview").exists())
        with patch.object(web_preview, "_card_filename", return_value="same.html"):
            with self.assertRaisesRegex(ValueError, "collision"):
                self.build([card("one"), card("two")])
        self.assertEqual(self.output.read_bytes(), b"old entry")
        outside = self.root / "outside.mp3"
        outside.write_bytes(b"ID3\0")
        (self.audio / "escape.mp3").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.build([card(audio="escape.mp3")])

    def test_repeat_build_reuses_valid_version_and_changed_inputs_keep_old_assets(self):
        first = self.build()
        catalog = self.catalog(first)
        old_page = self.root / catalog["cards"][0]["previewUrl"]
        old_bytes = old_page.read_bytes()
        old_mtime = old_page.stat().st_mtime_ns
        second = self.build()
        self.assertEqual(second["input_digest"], first["input_digest"])
        self.assertTrue(second["reused_version"])
        self.assertEqual(old_page.stat().st_mtime_ns, old_mtime)
        changed = self.build([card(word="rates")])
        self.assertNotEqual(changed["input_digest"], first["input_digest"])
        self.assertEqual(old_page.read_bytes(), old_bytes)
        self.assertEqual(len(self.versions()), 2)
        (self.audio / "rate.mp3").write_bytes(b"ID3\0new recording")
        audio_changed = self.build([card(word="rates")])
        self.assertNotEqual(audio_changed["input_digest"], changed["input_digest"])
        (self.templates / "library-preview.js").write_text("'changed';", encoding="utf-8")
        ui_changed = self.build([card(word="rates")])
        self.assertNotEqual(ui_changed["input_digest"], audio_changed["input_digest"])
        self.assertEqual(len(self.versions()), 4)

    def test_renderer_template_changes_create_a_new_version_and_input_reordering_reuses(self):
        renderer = self.root / "renderer"
        shutil.copytree(web_preview.packaging._TEMPLATE_DIR, renderer)
        inputs = [card("one", position="1"), card("two", position="2")]
        with patch.object(web_preview.packaging, "_TEMPLATE_DIR", renderer):
            first = self.build(inputs)
            reordered = self.build(list(reversed(inputs)))
            self.assertEqual(first["input_digest"], reordered["input_digest"])
            self.assertTrue(reordered["reused_version"])
            style = renderer / "style.css"
            style.write_bytes(style.read_bytes() + b"\n/* renderer change */\n")
            second = self.build(inputs)
            self.assertNotEqual(first["input_digest"], second["input_digest"])
            self.assertTrue(Path(first["version_directory"]).is_dir())
            self.assertEqual(len(self.versions()), 2)

    def test_tampered_or_unowned_existing_version_is_never_overwritten(self):
        report = self.build()
        original_entry = self.output.read_bytes()
        row = self.catalog(report)["cards"][0]
        page = self.root / row["previewUrl"]
        page.write_bytes(b"user changed this file")
        with self.assertRaisesRegex(ValueError, "checksum|version"):
            self.build()
        self.assertEqual(page.read_bytes(), b"user changed this file")
        self.assertEqual(self.output.read_bytes(), original_entry)
        page.unlink()
        page.symlink_to(self.audio / "rate.mp3")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()
        page.unlink()
        page.write_bytes(b"user changed this file")
        Path(report["manifest_path"]).unlink()
        with self.assertRaisesRegex(ValueError, "manifest|version"):
            self.build()

    def test_target_symlinks_rejected_without_touching_destination(self):
        outside = self.root / "other.html"
        outside.write_bytes(b"user document")
        self.output.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()
        self.assertEqual(outside.read_bytes(), b"user document")
        self.output.unlink()
        foreign = self.root / "foreign"
        foreign.mkdir()
        (self.root / "web-preview").symlink_to(foreign, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.build()
        self.assertEqual(list(foreign.iterdir()), [])

    def test_parent_symlink_is_rejected_even_when_hidden_by_dot_dot(self):
        foreign = self.root / "foreign"
        foreign.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(foreign, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            web_preview.build_web_preview([card()], self.audio,
                                          alias / ".." / "preview.html", deck_name="考研英语")
        self.assertFalse((self.root / "preview.html").exists())

    def test_media_change_during_copy_discards_staging_and_preserves_entry(self):
        self.output.write_bytes(b"old entry")
        copyfile = web_preview.shutil.copyfile

        def changed(source, destination):
            copyfile(source, destination)
            Path(destination).write_bytes(b"changed while copying")

        with patch.object(web_preview.shutil, "copyfile", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "audio changed"):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"old entry")
        self.assertEqual(list((self.root / "web-preview").iterdir()), [])

    def test_missing_template_and_partial_write_do_not_replace_entry_or_leave_staging(self):
        self.output.write_bytes(b"old entry")
        html = self.templates / "library-preview.html"
        original = html.read_bytes()
        html.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertEqual(self.output.read_bytes(), b"old entry")
        self.assertFalse((self.root / "web-preview").exists())
        html.write_bytes(original)
        writer = web_preview._write_file

        def fail(path, content):
            if path.name.endswith(".html"):
                path.write_bytes(b"partial")
                raise OSError("disk full")
            return writer(path, content)

        with patch.object(web_preview, "_write_file", side_effect=fail):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"old entry")
        self.assertEqual(list((self.root / "web-preview").iterdir()), [])

    def test_outer_atomic_replace_failure_preserves_entry_and_complete_version(self):
        self.output.write_bytes(b"old entry")
        replace = web_preview.os.replace

        def fail(source, destination):
            if Path(destination) == self.output:
                raise OSError("entry is busy")
            return replace(source, destination)

        with patch.object(web_preview.os, "replace", side_effect=fail):
            with self.assertRaisesRegex(OSError, "entry is busy"):
                self.build()
        self.assertEqual(self.output.read_bytes(), b"old entry")
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(list(self.root.glob(".preview-library-*.tmp")), [])
        report = self.build()
        self.assertTrue(report["reused_version"])

    def test_before_publish_failure_preserves_entry_for_new_and_reused_versions(self):
        self.output.write_bytes(b"old entry")
        calls = []

        def reject_changed_source():
            calls.append("checked")
            self.assertEqual(self.output.read_bytes(), b"old entry")
            self.assertEqual(len(self.versions()), 1)
            version = self.root / "web-preview" / self.versions()[0]
            manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
            web_preview._validate_version(version, manifest)
            raise ValueError("source changed before publication")

        for attempt in ("new version", "reused version"):
            with self.subTest(attempt=attempt), self.assertRaisesRegex(ValueError, "source changed"):
                self.build(before_publish=reject_changed_source)
            self.assertEqual(self.output.read_bytes(), b"old entry")
            self.assertEqual(list(self.root.glob(".preview-library-*.tmp")), [])
            self.assertEqual(len(self.versions()), 1)
            self.assertFalse(any(path.name.startswith(".") for path in
                                 (self.root / "web-preview").iterdir()))
        self.assertEqual(calls, ["checked", "checked"])
        page = next((self.root / "web-preview" / self.versions()[0] / "cards").glob("*.html"))
        original_mtime = page.stat().st_mtime_ns

        def accept_unchanged_source():
            calls.append("accepted")
            self.assertEqual(self.output.read_bytes(), b"old entry")

        report = self.build(before_publish=accept_unchanged_source)
        self.assertTrue(report["reused_version"])
        self.assertEqual(page.stat().st_mtime_ns, original_mtime)
        self.assertEqual(calls, ["checked", "checked", "accepted"])
        self.assertIn(report["catalog_url"], self.output.read_text(encoding="utf-8"))

    def test_output_cannot_overwrite_or_add_files_inside_owned_immutable_version(self):
        report = self.build()
        original_entry = self.output.read_bytes()
        old_page = self.root / self.catalog(report)["cards"][0]["previewUrl"]
        original_page = old_page.read_bytes()
        manifest = Path(report["manifest_path"])
        original_manifest = manifest.read_bytes()
        asset_target = Path(report["version_directory"]) / "assets" / "new-entry.html"
        for target in (old_page, asset_target):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "immutable"):
                web_preview.build_web_preview([card(word="changed")], self.audio,
                                              target, deck_name="考研英语")
            self.assertEqual(self.output.read_bytes(), original_entry)
            self.assertEqual(old_page.read_bytes(), original_page)
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertFalse(asset_target.exists())
            self.assertFalse((target.parent / "web-preview").exists())

    def test_generic_same_named_web_preview_directory_remains_a_legal_target(self):
        generic = self.root / "web-preview" / "generic" / "cards"
        generic.mkdir(parents=True)
        target = generic / "entry.html"
        report = web_preview.build_web_preview([card()], self.audio, target, deck_name="考研英语")
        self.assertTrue(target.is_file())
        self.assertTrue((target.parent / report["catalog_url"]).is_file())

    def test_explicit_example_limit_counts_match_rendered_files(self):
        report = self.build([card(examples=8)], max_examples=2)
        catalog = self.catalog(report)
        row = catalog["cards"][0]
        self.assertEqual(catalog["counts"]["examples"], 2)
        self.assertEqual(row["exampleCount"], 2)
        self.assertEqual((self.root / row["previewUrl"]).read_text(encoding="utf-8").count(
            '<li class="example-card">'), 2)
        for maximum in (True, -1, 1.5):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                self.build(max_examples=maximum)


if __name__ == "__main__":
    unittest.main()
