"""Regression checks for protected paths and owner-edited enrichment state."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.cli import main
from anki_pipeline.config import load_config
from anki_pipeline.store import card_id, connect, sha256_file, transaction, upsert_cards
from anki_pipeline.text import stable_sentence_id
from anki_pipeline.translations import export_translations, import_translations


MP3 = b"\xff\xfb\x90\x64" + b"\x00" * 252


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config_path = self.root / "config.toml"
        self.legacy = self.root / "legacy" / "old.sqlite3"
        self.legacy.parent.mkdir()
        self.legacy.write_bytes(b"legacy input: must stay unchanged")
        self._write_config()

    def _write_config(self, *, output: str = "output", project_root: str | None = None,
                      new_prefix: str = "") -> None:
        project = f'[project]\nroot = "{project_root}"\n' if project_root is not None else ""
        self.config_path.write_text(
            project + "[paths]\n"
            f'database = "{new_prefix}data/anki.sqlite3"\n'
            'legacy_database = "legacy/old.sqlite3"\n'
            'wordbook = "legacy/book.xlsx"\n'
            f'audio = "{new_prefix}data/audio"\n'
            'legacy_audio = "legacy/audio"\n'
            f'output = "{output}"\n'
            f'backups = "{new_prefix}backups"\n',
            encoding="utf-8",
        )

    def _card(self, **changes: str) -> dict[str, str]:
        card = {
            "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1", "word": "rate",
            "phonetic": "/manual/", "definition": "n. 比率", "audio_filename": "rate.mp3",
        }
        card.update(changes)
        return card

    def _seed_card(self, **changes: str) -> tuple[Path, str]:
        config = load_config(self.config_path)
        card = self._card(**changes)
        upsert_cards(config.database, [card], config.backups)
        return config.database, card_id(card)

    def _cli(self, *args: str) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["--config", str(self.config_path), *args])
        return result, stdout.getvalue(), stderr.getvalue()

    def test_report_aliases_cannot_overwrite_active_or_legacy_database(self) -> None:
        database, _ = self._seed_card()
        before = {path: sha256_file(path) for path in (database, self.legacy)}
        alias = self.root / "output" / "report-link.json"
        alias.parent.mkdir()
        alias.symlink_to(self.legacy)

        for report in (database, self.legacy, alias):
            with self.subTest(report=report):
                code, _, error = self._cli("check", "--report", str(report))
                self.assertEqual(code, 2, error)
                self.assertIn("输出", error)
                self.assertEqual({path: sha256_file(path) for path in before}, before)
        self.assertTrue(alias.is_symlink())

    def test_build_replaces_hardlinked_preview_without_modifying_database(self) -> None:
        database, _ = self._seed_card()
        config = load_config(self.config_path)
        config.audio.mkdir(parents=True)
        (config.audio / "rate.mp3").write_bytes(MP3)
        config.output.mkdir()
        preview = config.output / "preview.html"
        preview.hardlink_to(database)
        database_hash = sha256_file(database)
        original_inode = database.stat().st_ino
        self.assertEqual(preview.stat().st_ino, original_inode)

        code, _, error = self._cli("build", "--file", str(config.output / "trial.apkg"))

        self.assertEqual(code, 0, error)
        self.assertEqual(sha256_file(database), database_hash)
        self.assertEqual(database.stat().st_ino, original_inode)
        self.assertNotEqual(preview.stat().st_ino, original_inode)
        self.assertIn("<html", preview.read_text(encoding="utf-8"))

    def test_output_directory_cannot_alias_legacy_input_directory(self) -> None:
        before = sha256_file(self.legacy)
        for output in ("legacy", "legacy/audio"):
            with self.subTest(output=output):
                self._write_config(output=output)
                with self.assertRaises(ValueError):
                    load_config(self.config_path)

        alias = self.root / "output-link"
        alias.symlink_to(self.legacy.parent, target_is_directory=True)
        self._write_config(output="output-link")
        with self.assertRaises(ValueError):
            load_config(self.config_path)
        self.assertEqual(sha256_file(self.legacy), before)

    def test_project_root_defaults_to_config_parent_or_declared_parent(self) -> None:
        self.assertEqual(load_config(self.config_path).project_root, self.root)
        nested = self.root / "nested"
        nested.mkdir()
        self.config_path = nested / "config.toml"
        self.config_path.write_text(
            '[project]\nroot = ".."\n[paths]\n'
            'database = "../data/anki.sqlite3"\n'
            'legacy_database = "../legacy/old.sqlite3"\n'
            'wordbook = "../legacy/book.xlsx"\n'
            'audio = "../data/audio"\n'
            'legacy_audio = "../legacy/audio"\n'
            'output = "../output"\n'
            'backups = "../backups"\n', encoding="utf-8",
        )
        config = load_config(self.config_path)
        self.assertEqual(config.project_root, self.root)
        self.assertEqual(config.database, self.root / "data" / "anki.sqlite3")

    def test_replaying_same_translation_does_not_clear_new_review_reason(self) -> None:
        database, cid = self._seed_card()
        text, source = "The rate was fair.", "2020年 ➫ Text 1"
        sid = stable_sentence_id("rate", text, source)
        with connect(database) as conn, transaction(conn):
            conn.execute(
                "INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?)",
                (sid, cid, text, source, "旧译文。", 1, 1, "needs_review"),
            )
        csv_path = self.root / "translations.csv"
        self.assertEqual(export_translations(database, csv_path), 1)
        with connect(database) as conn, transaction(conn):
            conn.execute("UPDATE sentences SET review_reason=? WHERE id=?", ("newer_manual_review", sid))
        before = sha256_file(database)

        result = import_translations(database, csv_path, self.root / "backups")

        self.assertEqual(result["updated"], 0)
        with connect(database, readonly=True) as conn:
            row = conn.execute("SELECT translation,review_reason FROM sentences WHERE id=?", (sid,)).fetchone()
        self.assertEqual(tuple(row), ("旧译文。", "newer_manual_review"))
        self.assertEqual(sha256_file(database), before)

    def test_oxford_enrich_repairs_missing_audio_without_replacing_phonetic(self) -> None:
        database, cid = self._seed_card()
        audio_path = load_config(self.config_path).audio / "rate.mp3"
        self.assertFalse(audio_path.exists())

        def fake_download(url: str, word: str, directory: Path) -> str:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "rate.mp3").write_bytes(MP3)
            return "rate.mp3"

        with patch("anki_pipeline.inputs.lookup_oxford", return_value={
            "phonetic": "/provider/", "audio_url": "https://example.invalid/rate.mp3"
        }) as lookup, patch("anki_pipeline.inputs.download_audio", side_effect=fake_download) as download:
            code, _, error = self._cli("enrich", "--provider", "oxford", "--limit", "1")

        self.assertEqual(code, 0, error)
        lookup.assert_called_once_with("rate")
        download.assert_called_once()
        self.assertTrue(audio_path.is_file())
        with connect(database, readonly=True) as conn:
            row = conn.execute("SELECT phonetic,audio_filename FROM cards WHERE id=?", (cid,)).fetchone()
        self.assertEqual(tuple(row), ("/manual/", "rate.mp3"))

    def test_youdao_enrich_keeps_nonblank_manual_level_and_forms(self) -> None:
        database, cid = self._seed_card(level="CET4", word_forms="复数：rates")
        with patch("anki_pipeline.inputs.lookup_youdao", return_value={
            "simple_definition": "n. 速度", "level": "IELTS", "word_forms": "过去式：rated"
        }) as lookup:
            code, _, error = self._cli("enrich", "--provider", "youdao", "--limit", "1")

        self.assertEqual(code, 0, error)
        lookup.assert_called_once_with("rate")
        with connect(database, readonly=True) as conn:
            row = conn.execute("SELECT simple_definition,level,word_forms FROM cards WHERE id=?", (cid,)).fetchone()
        self.assertEqual(tuple(row), ("n. 速度", "CET4", "复数：rates"))


if __name__ == "__main__":
    unittest.main()
