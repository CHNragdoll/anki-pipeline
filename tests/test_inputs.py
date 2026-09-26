"""Fixture and mocked-network checks for source and enrichment inputs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from openpyxl import Workbook

from anki_pipeline.inputs import (
    InputError,
    audio_filename,
    download_audio,
    lookup_oxford,
    lookup_youdao,
    read_wordbook,
)


OXFORD_MP3 = "https://www.oxfordlearnersdictionaries.com/media/english/us_pron/a/amb/ambit/ambition__us_2.mp3"
MP3 = b"\xff\xfb\x90\x64" + b"\x00" * 252


class FakeResponse:
    def __init__(self, content=b"", *, url="", content_type="audio/mpeg", status_code=200):
        self.content = content
        self.url = url
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code
        self.closed = False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("HTTP error")

    def iter_content(self, chunk_size):
        yield self.content

    def close(self):
        self.closed = True


class WordbookTests(unittest.TestCase):
    def make_workbook(self, directory, rows):
        workbook = Workbook()
        first = workbook.active
        first.title = "Unit 1"
        first.append(["Lesson", "序号", "单词", "词义", "音标"])
        for row in rows:
            first.append(row)
        second = workbook.create_sheet("Unit 2")
        second.append(["Lesson", "序号", "单词", "词义"])
        second.append(["Lesson 1", 1, "present", "n. 礼物"])
        path = Path(directory) / "book.xlsx"
        workbook.save(path)
        workbook.close()
        return path

    def test_preserves_full_word_and_continuation_and_distinct_lessons(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_workbook(directory, [
                ["Lesson 1", 1, "present", "adj. 在场", "/ˈpreznt/"],
                ["Lesson 1", None, None, "v. 赠送"],
                ["Lesson 2", 1, "catalogue\n(美catalog)", "n. 目录"],
            ])
            cards = read_wordbook(path)
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0]["definition"], "adj. 在场\nv. 赠送")
        self.assertEqual(cards[0]["position"], "1")
        self.assertEqual(cards[0]["phonetic"], "/ˈpreznt/")
        self.assertEqual(cards[1]["word"], "catalogue\n(美catalog)")
        self.assertEqual(cards[1]["audio_filename"], "catalogue.mp3")
        self.assertEqual(cards[2]["sheet"], "Unit 2")
        self.assertEqual(set(cards[0]), {
            "sheet", "lesson", "position", "word", "phonetic", "definition",
            "simple_definition", "level", "word_forms", "audio_filename",
        })

    def test_rejects_duplicate_word_even_with_different_position(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.make_workbook(directory, [
                ["Lesson 1", 1, "rate", "n. 比率"],
                ["Lesson 1", 2, "Rate", "v. 评价"],
            ])
            with self.assertRaisesRegex(InputError, "duplicate word"):
                read_wordbook(path)

    def test_rejects_duplicate_position_and_orphan_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            duplicate = self.make_workbook(directory, [
                ["Lesson 1", 1, "rate", "n. 比率"],
                ["Lesson 1", 1, "theme", "n. 主题"],
            ])
            with self.assertRaisesRegex(InputError, "duplicate position"):
                read_wordbook(duplicate)
            orphan = self.make_workbook(directory, [["Lesson 1", None, None, "v. 继续"]])
            with self.assertRaisesRegex(InputError, "continuation"):
                read_wordbook(orphan)

    def test_filename_is_safe_and_does_not_collapse_distinct_words(self):
        self.assertEqual(audio_filename("rate"), "rate.mp3")
        self.assertEqual(audio_filename("rate\n(美rated)"), "rate.mp3")
        self.assertNotEqual(audio_filename("a/b"), audio_filename("a?b"))
        self.assertNotIn("/", audio_filename("../../secret"))


class LookupTests(unittest.TestCase):
    @patch("anki_pipeline.inputs.requests.get")
    def test_oxford_parses_entry_and_allows_missing_optional_fields(self, get):
        get.return_value = FakeResponse(
            b'<div class="entry"><div class="phons_n_am"><span class="phon">/test/</span></div>'
            b'<div class="audio_play_button pron-us" data-src-mp3="' + OXFORD_MP3.encode() + b'"></div></div>',
            url="https://www.oxfordlearnersdictionaries.com/definition/english/test",
        )
        self.assertEqual(lookup_oxford("test"), {"phonetic": "/test/", "audio_url": OXFORD_MP3})
        get.return_value = FakeResponse(
            b'<div class="entry">definition only</div>',
            url="https://www.oxfordlearnersdictionaries.com/definition/english/test",
        )
        self.assertEqual(lookup_oxford("test"), {"phonetic": "", "audio_url": ""})

    @patch("anki_pipeline.inputs.requests.get")
    def test_oxford_rejects_search_page(self, get):
        get.return_value = FakeResponse(b"<html>suggestion</html>", url="https://www.oxfordlearnersdictionaries.com/search/english/?q=teat")
        with self.assertRaisesRegex(InputError, "no exact entry"):
            lookup_oxford("teat")
        get.return_value = FakeResponse(
            b'<div class="entry"><h1 class="headword">productive</h1></div>',
            url="https://www.oxfordlearnersdictionaries.com/definition/english/productive",
        )
        with self.assertRaisesRegex(InputError, "different headword"):
            lookup_oxford("productve")

    @patch("anki_pipeline.inputs.requests.get")
    def test_youdao_parses_static_markup_and_rejects_dynamic_page(self, get):
        get.return_value = FakeResponse(
            b'<li class="word-exp"><span class="pos">n.</span><span class="trans">meaning</span></li>'
            b'<span class="exam_type-value">CET4</span>'
            b'<div class="word-wfs-cell-less"><span class="wfs-name">plural</span>'
            b'<span class="transformation">tests</span></div>',
        )
        self.assertEqual(lookup_youdao("test"), {
            "simple_definition": "n. meaning", "level": "CET4", "word_forms": "plural：tests"
        })
        get.return_value = FakeResponse(b"<html><script>hydrate()</script></html>")
        with self.assertRaisesRegex(InputError, "dynamic page is unsupported"):
            lookup_youdao("test")

    @patch("anki_pipeline.inputs.requests.get")
    def test_lookup_keeps_network_failure_distinct_from_empty_fields(self, get):
        get.side_effect = requests.Timeout("timed out")
        with self.assertRaises(requests.Timeout):
            lookup_oxford("test")


class AudioTests(unittest.TestCase):
    @patch("anki_pipeline.inputs.requests.get")
    def test_download_is_atomic_and_skips_valid_existing_file(self, get):
        response = FakeResponse(MP3)
        get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            filename = download_audio(OXFORD_MP3, "ambition", Path(directory))
            self.assertEqual(filename, "ambition.mp3")
            self.assertEqual((Path(directory) / filename).read_bytes(), MP3)
            self.assertTrue(response.closed)
            get.reset_mock()
            self.assertEqual(download_audio(OXFORD_MP3, "ambition", Path(directory)), filename)
            get.assert_not_called()

    @patch("anki_pipeline.inputs.requests.get")
    def test_audio_rejects_other_hosts_and_invalid_media(self, get):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(InputError, "Oxford US"):
                download_audio("https://evil.example/media/english/us_pron/a.mp3", "a", Path(directory))
            get.assert_not_called()
            get.return_value = FakeResponse(b"<html>blocked</html>", content_type="text/html")
            with self.assertRaisesRegex(InputError, "content type"):
                download_audio(OXFORD_MP3, "ambition", Path(directory))
            self.assertFalse((Path(directory) / "ambition.mp3").exists())

    @patch("anki_pipeline.inputs.requests.get")
    def test_audio_rejects_large_content(self, get):
        response = FakeResponse(MP3)
        response.headers["Content-Length"] = str(5 * 1024 * 1024 + 1)
        get.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(InputError, "size limit"):
                download_audio(OXFORD_MP3, "ambition", Path(directory))
            self.assertEqual(list(Path(directory).iterdir()), [])

    @patch("anki_pipeline.inputs.requests.get")
    def test_audio_replaces_invalid_existing_file_only_after_validation(self, get):
        get.return_value = FakeResponse(b"not MP3")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ambition.mp3"
            target.write_bytes(b"old invalid media")
            with self.assertRaisesRegex(InputError, "valid MP3"):
                download_audio(OXFORD_MP3, "ambition", Path(directory))
            self.assertEqual(target.read_bytes(), b"old invalid media")
            get.return_value = FakeResponse(MP3)
            download_audio(OXFORD_MP3, "ambition", Path(directory))
            self.assertEqual(target.read_bytes(), MP3)


if __name__ == "__main__":
    unittest.main()
