"""Small legacy SQLite fixtures exercise migration without touching V2.0."""

from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anki_pipeline.migration import migrate_legacy
from anki_pipeline.store import (connect, initialize, logical_digest, sha256_file,
                                 upsert_cards)


def create_legacy(path: Path, *, bad_translation: bool = False) -> None:
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript('''
            CREATE TABLE "最终数据" (
                sheet TEXT, "Lesson" TEXT, "序号" TEXT, "单词" TEXT,
                "音标" TEXT, "词义" TEXT, "简明词义" TEXT,
                "考试等级" TEXT, "词形变化" TEXT, "句子出处" TEXT);
            CREATE TABLE "Translate-tmp-1" (
                "单词" TEXT PRIMARY KEY, "句子出处" TEXT, "Translate" TEXT);
        ''')
        conn.executemany('INSERT INTO "最终数据" VALUES(?,?,?,?,?,?,?,?,?,?)', [
            ("Unit 1", "Lesson 1", "1", "rate", "/reɪt/", "n. 比率", "比率", "CET4", "rates", "original rate blob"),
            ("Unit 1", "Lesson 2", "1", "theme", "/θiːm/", "n. 主题", "主题", "CET4", "themes", "original theme blob"),
        ])
        rate_examples = (
            "[1] The rate rose.\n2020 年考研英语\n"
            "[1] 比率上升了。\n"
            "[2] Rather than wait, she left.\n2021 年考研英语"
        )
        theme_examples = (
            "[1] The theme changed.\n2022 年考研英语\n"
            "[2] They saw them.\n2023 年考研英语"
        )
        rate_translation = "[1] 比率上升了。\n[2] 她没有等待就离开了。"
        theme_translation = "[1] 主题改变了。\n[2] 他们看见了他们。"
        if bad_translation:
            rate_translation += "\n[99] 没有对应原文。"
        conn.executemany('INSERT INTO "Translate-tmp-1" VALUES(?,?,?)', [
            ("rate", rate_examples, rate_translation),
            ("theme", theme_examples, theme_translation),
        ])


class MigrationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "legacy.sqlite3"
        self.target = self.root / "new" / "anki.sqlite3"
        self.backups = self.root / "backups"
        create_legacy(self.source)

    def test_migrates_all_cards_and_raw_rows_quarantines_false_matches(self):
        source_hash = sha256_file(self.source)
        result = migrate_legacy(self.source, self.target, self.backups)
        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["cards"], 2)
        self.assertEqual(result["sentences"], 4)
        self.assertEqual(result["rejected_word_matches"], 2)
        self.assertEqual(source_hash, sha256_file(self.source))
        with closing(sqlite3.connect(self.source)) as original, closing(sqlite3.connect(result["snapshot"])) as snapshot:
            for table in ("最终数据", "Translate-tmp-1"):
                self.assertEqual(original.execute(f'SELECT * FROM "{table}" ORDER BY 1,2').fetchall(),
                                 snapshot.execute(f'SELECT * FROM "{table}" ORDER BY 1,2').fetchall())
        with connect(self.target, readonly=True) as conn:
            cards = [dict(row) for row in conn.execute("SELECT * FROM cards ORDER BY word")]
            self.assertEqual([card["word"] for card in cards], ["rate", "theme"])
            self.assertEqual(conn.execute("SELECT count(*) FROM legacy_rows").fetchone()[0], 2)
            sentences = [dict(row) for row in conn.execute("SELECT * FROM sentences ORDER BY text")]
            self.assertEqual({row["text"] for row in sentences if row["accepted"]},
                             {"The rate rose.", "The theme changed."})
            self.assertEqual({row["text"] for row in sentences if not row["accepted"]},
                             {"Rather than wait, she left.", "They saw them."})
            self.assertTrue(all("word_mismatch" in row["review_reason"] for row in sentences if not row["accepted"]))
            payload = json.loads(conn.execute("SELECT payload FROM legacy_rows WHERE card_id=?", (cards[0]["id"],)).fetchone()[0])
            self.assertIn("original rate blob", payload["final"]["句子出处"])
            self.assertIn("[1] 比率上升了。", payload["snapshot"]["句子出处"])

    def test_repeat_migration_keeps_manual_edits_and_content_digest(self):
        migrate_legacy(self.source, self.target, self.backups)
        with connect(self.target) as conn:
            conn.execute("UPDATE cards SET definition=? WHERE word='rate'", ("manual correction",))
            conn.commit()
        expected = logical_digest(self.target)
        result = migrate_legacy(self.source, self.target, self.backups)
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(logical_digest(self.target), expected)
        with connect(self.target, readonly=True) as conn:
            self.assertEqual(conn.execute("SELECT definition FROM cards WHERE word='rate'").fetchone()[0], "manual correction")

    def test_existing_unrelated_destination_is_protected(self):
        initialize(self.target)
        upsert_cards(self.target, [{
            "sheet": "Unit X", "lesson": "Lesson 1", "position": "1", "word": "manual",
            "phonetic": "/m/", "definition": "手动", "audio_filename": "manual.mp3",
        }], self.backups)
        expected = logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, "目标库已存在"):
            migrate_legacy(self.source, self.target, self.backups)
        self.assertEqual(logical_digest(self.target), expected)

    def test_invalid_translation_mapping_does_not_publish_target(self):
        self.source.unlink()
        create_legacy(self.source, bad_translation=True)
        before = sha256_file(self.source)
        with self.assertRaisesRegex(ValueError, "无原文编号"):
            migrate_legacy(self.source, self.target, self.backups)
        self.assertFalse(self.target.exists())
        self.assertEqual(sha256_file(self.source), before)


if __name__ == "__main__":
    unittest.main()
