"""Integration checks for SQLite transactions and recoverable backups."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anki_pipeline import store


def sample_card(word: str = "rate") -> dict:
    return {
        "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1",
        "word": word, "phonetic": "/reɪt/", "definition": "n. 比率",
        "simple_definition": "rate", "level": "CET4", "word_forms": "rates",
        "audio_filename": word + ".mp3",
    }


class StoreIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "data" / "anki.sqlite3"
        self.backups = self.root / "backups"

    def test_backup_restore_preserves_logical_digest_and_refuses_overwrite(self):
        store.upsert_cards(self.database, [sample_card()], self.backups)
        expected = store.logical_digest(self.database)
        snapshot = store.backup_database(self.database, self.backups)
        restored = self.root / "restore" / "anki.sqlite3"
        store.restore_database(snapshot, restored)
        self.assertEqual(store.logical_digest(restored), expected)
        with self.assertRaises(FileExistsError):
            store.restore_database(snapshot, self.database)
        self.assertEqual(store.logical_digest(self.database), expected)

    def test_transaction_rolls_back_content_and_schema_change(self):
        store.upsert_cards(self.database, [sample_card()], self.backups)
        expected = store.logical_digest(self.database)
        with store.connect(self.database) as conn:
            with self.assertRaisesRegex(RuntimeError, "abort"):
                with store.transaction(conn):
                    conn.execute("UPDATE cards SET definition='wrong'")
                    conn.execute("CREATE TABLE transient (value TEXT)")
                    raise RuntimeError("abort")
        self.assertEqual(store.logical_digest(self.database), expected)
        with store.connect(self.database, readonly=True) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='transient'").fetchone())

    def test_schema_failure_does_not_leave_partial_database(self):
        with patch.object(store, "SCHEMA", "CREATE TABLE incomplete (id TEXT); INVALID SQL;"):
            with self.assertRaises(Exception):
                store.initialize(self.database)
        self.assertFalse(self.database.exists())


if __name__ == "__main__":
    unittest.main()
