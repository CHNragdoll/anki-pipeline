"""Recovering audio from a legacy Anki package must never extract ZIP paths."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from anki_pipeline.pipeline import _copy_package_audio, copy_legacy_audio
from anki_pipeline.store import sha256_file, upsert_cards


MP3 = b"\xff\xfb\x90\x64" + b"\x00" * 252
OTHER_MP3 = b"\xff\xfb\xa0\xc4" + b"\x00" * 252


class PackageAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "source.apkg"
        self.target = self.root / "new-audio"

    def make_package(self, mapping: dict, files: dict[str, bytes] | None = None) -> Path:
        files = files if files is not None else {"0": MP3, "1": OTHER_MP3}
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("media", json.dumps(mapping, ensure_ascii=False))
            for name, data in files.items():
                archive.writestr(name, data)
        return self.package

    def test_recovers_numeric_entries_preserves_valid_files_and_never_extracts_paths(self):
        package = self.make_package(
            {"0": "rate.mp3", "1": "theme.mp3"},
            {"0": MP3, "1": OTHER_MP3, "../../outside.txt": b"unsafe archive member"},
        )
        self.target.mkdir()
        (self.target / "rate.mp3").write_bytes(OTHER_MP3)
        result = _copy_package_audio(package, ["rate.mp3", "theme.mp3"], self.target)
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["copied"], 1)
        self.assertEqual(result["archive_sha256"], sha256_file(package))
        self.assertEqual((self.target / "rate.mp3").read_bytes(), OTHER_MP3)
        self.assertEqual((self.target / "theme.mp3").read_bytes(), OTHER_MP3)
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertEqual(_copy_package_audio(package, ["rate.mp3", "theme.mp3"], self.target)["copied"], 0)

    def test_rejects_unsafe_names_duplicate_map_and_missing_media(self):
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3})
        for name in ("../escape.mp3", "nested/rate.mp3", "nested\\rate.mp3", "rate.ogg",
                     "rate[hidden].mp3", "rate\n.mp3", "rate<bad>.mp3"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "非法音频名"):
                _copy_package_audio(package, [name], self.target)
        with self.assertRaisesRegex(ValueError, "缺少音频"):
            _copy_package_audio(package, ["theme.mp3"], self.target)
        self.make_package({"0": "rate.mp3", "1": "rate.mp3"})
        with self.assertRaisesRegex(ValueError, "重复媒体名称"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertFalse(self.target.exists())

    def test_rejects_invalid_map_and_missing_numeric_archive_entry(self):
        package = self.make_package({"../../evil": "rate.mp3"}, {"../../evil": MP3})
        with self.assertRaisesRegex(ValueError, "媒体映射无效"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.make_package({"2": "rate.mp3"}, {"0": MP3})
        with self.assertRaisesRegex(ValueError, "缺少|不存在"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertFalse(self.target.exists())

    def test_rejects_duplicate_numeric_keys_in_media_json(self):
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("media", '{"0":"rate.mp3","0":"theme.mp3"}')
            archive.writestr("0", MP3)
        with self.assertRaisesRegex(ValueError, "重复|映射无效"):
            _copy_package_audio(self.package, ["theme.mp3"], self.target)

    def test_missing_media_index_reports_invalid_archive(self):
        with zipfile.ZipFile(self.package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("0", MP3)
        with self.assertRaisesRegex(ValueError, "媒体索引|卡包"):
            _copy_package_audio(self.package, ["rate.mp3"], self.target)

    def test_rejects_oversize_media_and_invalid_mp3_before_writing(self):
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3 + b"\0" * (5 * 1024 * 1024)})
        with self.assertRaisesRegex(ValueError, "媒体大小异常"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.make_package({"0": "rate.mp3"}, {"0": b"<html>not an MP3</html>"})
        with self.assertRaisesRegex(ValueError, "媒体大小异常|无效 MP3"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertFalse(self.target.exists())

    def test_rejects_existing_symlink_even_if_dangling(self):
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3})
        self.target.mkdir()
        outside = self.root / "outside.mp3"
        outside.write_bytes(OTHER_MP3)
        link = self.target / "rate.mp3"
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertEqual(outside.read_bytes(), OTHER_MP3)
        link.unlink()
        link.symlink_to(self.root / "not-present.mp3")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            _copy_package_audio(package, ["rate.mp3"], self.target)

    def test_existing_invalid_media_is_rejected_without_overwrite(self):
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3})
        self.target.mkdir()
        existing = self.target / "rate.mp3"
        existing.write_bytes(b"invalid existing media")
        with self.assertRaisesRegex(ValueError, "无效|损坏"):
            _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertEqual(existing.read_bytes(), b"invalid existing media")

    def test_copy_legacy_audio_can_use_package_without_reading_old_audio_files(self):
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3})
        database = self.root / "data" / "anki.sqlite3"
        old_audio = self.root / "legacy-audio"
        old_audio.mkdir()
        upsert_cards(database, [{
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/reɪt/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }], self.root / "backups")
        result = copy_legacy_audio(database, old_audio, self.target, package=package)
        self.assertEqual(result["files"], 1)
        self.assertEqual(result["copied"], 1)
        self.assertEqual((self.target / "rate.mp3").read_bytes(), MP3)

    def test_package_file_inside_target_directory_is_left_intact(self):
        self.target.mkdir()
        self.package = self.target / "source.apkg"
        package = self.make_package({"0": "rate.mp3"}, {"0": MP3})
        package_hash = sha256_file(package)
        result = _copy_package_audio(package, ["rate.mp3"], self.target)
        self.assertEqual(result["copied"], 1)
        self.assertEqual(sha256_file(package), package_hash)


if __name__ == "__main__":
    unittest.main()
