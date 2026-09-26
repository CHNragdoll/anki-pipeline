"""Temporary-config command tests exercise the offline local trial flow."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path
import zipfile

from anki_pipeline.cli import main
from anki_pipeline.config import load_config
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


if __name__ == "__main__":
    unittest.main()
