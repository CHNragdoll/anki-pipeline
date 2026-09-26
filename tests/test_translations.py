"""CSV translation import must align by immutable IDs, not row order."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from anki_pipeline.store import card_id, connect, initialize, logical_digest, transaction
from anki_pipeline.translations import (FIELDS, content_hash, export_translations,
                                        import_translations)


class TranslationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "anki.sqlite3"
        self.backups = self.root / "backups"
        initialize(self.database)
        card = {"sheet": "Unit 1", "lesson": "Lesson 1", "word": "rate"}
        with connect(self.database) as conn, transaction(conn):
            conn.execute("INSERT INTO cards(id,sheet,lesson,position,word,phonetic,definition,audio_filename) VALUES(?,?,?,?,?,?,?,?)",
                         (card_id(card), "Unit 1", "Lesson 1", "1", "rate", "/reɪt/", "n. 比率", "rate.mp3"))
            conn.executemany("INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?)", [
                ("sentence-1", card_id(card), "The rate rose.", "2020 年", "旧译文。", 1, 1, ""),
                ("sentence-2", card_id(card), "Rates may vary.", "2021 年", "", 2, 1, "missing_translation"),
                ("sentence-3", card_id(card), "Rather than wait.", "2022 年", "", 3, 0, "word_mismatch"),
            ])
        self.template = self.root / "export.csv"
        self.assertEqual(export_translations(self.database, self.template, pending_only=False), 2)
        with self.template.open(encoding="utf-8-sig", newline="") as stream:
            self.rows = list(csv.DictReader(stream))

    def write_csv(self, name: str, rows: list[dict]) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def translations(self) -> dict[str, str]:
        with connect(self.database, readonly=True) as conn:
            return dict(conn.execute("SELECT id,translation FROM sentences"))

    def test_reordered_rows_import_by_id_and_repeat_is_noop(self):
        rows = {row["sentence_id"]: dict(row) for row in self.rows}
        rows["sentence-1"]["translation"] = "更新译文一。"
        rows["sentence-2"]["translation"] = "更新译文二。"
        source = self.write_csv("reordered.csv", [rows["sentence-2"], rows["sentence-1"]])
        self.assertEqual(import_translations(self.database, source, self.backups)["updated"], 2)
        self.assertEqual(self.translations(), {
            "sentence-1": "更新译文一。", "sentence-2": "更新译文二。", "sentence-3": "",
        })
        digest = logical_digest(self.database)
        self.assertEqual(import_translations(self.database, source, self.backups), {"rows": 2, "updated": 0})
        self.assertEqual(logical_digest(self.database), digest)

    def test_empty_cells_do_not_clear_existing_translation(self):
        row = next(dict(item) for item in self.rows if item["sentence_id"] == "sentence-1")
        row["translation"] = ""
        source = self.write_csv("empty.csv", [row])
        self.assertEqual(import_translations(self.database, source, self.backups)["updated"], 0)
        self.assertEqual(self.translations()["sentence-1"], "旧译文。")

    def test_stale_template_cannot_overwrite_newer_translation_but_replay_is_safe(self):
        original = next(dict(item) for item in self.rows if item["sentence_id"] == "sentence-2")
        version_a = {**original, "translation": "译文 A。"}
        version_b = {**original, "translation": "译文 B。"}
        source_a = self.write_csv("version-a.csv", [version_a])
        source_b = self.write_csv("version-b.csv", [version_b])
        self.assertEqual(import_translations(self.database, source_a, self.backups)["updated"], 1)
        after_a = logical_digest(self.database)
        with self.assertRaisesRegex(ValueError, "重新导出"):
            import_translations(self.database, source_b, self.backups)
        self.assertEqual(logical_digest(self.database), after_a)
        self.assertEqual(import_translations(self.database, source_a, self.backups)["updated"], 0)
        self.assertEqual(logical_digest(self.database), after_a)

    def test_wrong_id_text_hash_and_conflicting_rows_fail_atomically(self):
        rows = {row["sentence_id"]: dict(row) for row in self.rows}
        first = dict(rows["sentence-2"])
        first["translation"] = "可用的新译文。"
        baseline = logical_digest(self.database)
        cases = {
            "wrong-id": {**rows["sentence-1"], "sentence_id": "nonexistent"},
            "wrong-text": {**rows["sentence-1"], "text": "The rates rose."},
            "wrong-hash": {**rows["sentence-1"], "content_hash": "0" * 64},
            "duplicate-id": {**first, "translation": "冲突译文。"},
        }
        for name, invalid in cases.items():
            with self.subTest(name=name):
                source = self.write_csv(name + ".csv", [first, invalid])
                with self.assertRaises(ValueError):
                    import_translations(self.database, source, self.backups)
                self.assertEqual(logical_digest(self.database), baseline)

    def test_quarantined_sentence_cannot_be_imported(self):
        with connect(self.database, readonly=True) as conn:
            row = conn.execute("SELECT s.*,c.word FROM sentences s JOIN cards c ON c.id=s.card_id WHERE s.id='sentence-3'").fetchone()
            rejected = {"sentence_id": row["id"], "word": row["word"], "text": row["text"],
                        "source": row["source"], "content_hash": content_hash(row),
                        "translation": "错误匹配译文。"}
        source = self.write_csv("rejected.csv", [rejected])
        baseline = logical_digest(self.database)
        with self.assertRaisesRegex(ValueError, "隔离"):
            import_translations(self.database, source, self.backups)
        self.assertEqual(logical_digest(self.database), baseline)


if __name__ == "__main__":
    unittest.main()
