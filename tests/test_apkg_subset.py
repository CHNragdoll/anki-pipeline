"""Subset export must preserve identities/history and reject unsafe inputs."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

import genanki

from anki_pipeline.apkg_subset import export_subset


def snapshot(path, root):
    with zipfile.ZipFile(path) as archive:
        db = root / (path.stem + ".anki2")
        db.write_bytes(archive.read("collection.anki2"))
        with closing(sqlite3.connect(db)) as connection:
            return {"notes": connection.execute("select * from notes order by id").fetchall(),
                    "cards": connection.execute("select * from cards order by id").fetchall(),
                    "revlog": connection.execute("select * from revlog order by id").fetchall(),
                    "decks": json.loads(connection.execute("select decks from col").fetchone()[0]),
                    "media": {name: archive.read(key) for key, name in json.loads(archive.read("media")).items()}}


class SubsetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.target = self.root / "full.apkg", self.root / "subset.apkg"
        model = genanki.Model(9001, "Words", fields=[{"name": "Word"}, {"name": "Audio"}],
                             templates=[{"name": "Word", "qfmt": "{{Word}}", "afmt": "{{Audio}}"}])
        guide = genanki.Model(9002, "Guide", fields=[{"name": name} for name in ("Title", "Overview", "Guide")],
                             templates=[{"name": "Guide", "qfmt": "{{Overview}}", "afmt": "{{Guide}}"}])
        decks = [genanki.Deck(1001, "Book::01 Required::Unit 01"),
                 genanki.Deck(1002, "Book::02 Basic::Unit 01"), genanki.Deck(1003, "Book::00 Guide")]
        decks[0].add_note(genanki.Note(model, ["remote", '[sound:remote audio.mp3]<audio src="odd&amp;audio.mp3?cache=1#t=0.2"></audio><audio src="./remote%20audio.mp3"></audio>']))
        decks[1].add_note(genanki.Note(model, ["tie", "[sound:tie.mp3]"]))
        decks[2].add_note(genanki.Note(guide, ["Guide", "Full", "Sources"]))
        media = []
        for name in ("remote audio.mp3", "odd&audio.mp3", "tie.mp3", "shared.css", "tree.png"):
            file = self.root / name
            file.write_bytes(b"original-media")
            media.append(str(file))
        package = genanki.Package(decks)
        package.media_files = media
        package.write_to_file(self.source)
        # Include a real review row and scheduling values in the fixture.
        with zipfile.ZipFile(self.source) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        db = self.root / "fixture.anki2"
        db.write_bytes(members["collection.anki2"])
        with closing(sqlite3.connect(db)) as connection, connection:
            cid = connection.execute("select id from cards where did=1001").fetchone()[0]
            connection.execute("update cards set queue=2, type=2, ivl=7, reps=3, due=101 where id=?", (cid,))
            connection.execute("insert into revlog values (?, ?, ?, ?, ?, ?, ?, ?, ?)", (777, cid, -1, 3, 7, 1, 2500, 1234, 1))
            connection.execute("insert into graves values (-1, 888, 0)")
        members["collection.anki2"] = db.read_bytes()
        self.repack(members)

    def repack(self, members):
        with zipfile.ZipFile(self.source, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)

    def test_subtrees_preserve_rows_history_media_and_source(self):
        before_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        before = snapshot(self.source, self.root)
        result = export_subset(self.source, self.target, ["Book::00 Guide", "Book::01 Required"])
        after = snapshot(self.target, self.root)
        kept = [row for row in before["cards"] if row[2] in {1001, 1003}]
        self.assertEqual(after["cards"], kept)
        self.assertEqual(after["notes"], [row for row in before["notes"] if row[0] in {card[1] for card in kept}])
        self.assertEqual(after["revlog"], before["revlog"])
        self.assertFalse(any("02 Basic" in deck["name"] for deck in after["decks"].values()))
        self.assertEqual(set(after["media"]), {"remote audio.mp3", "odd&audio.mp3", "shared.css", "tree.png"})
        self.assertTrue(all(before["media"][name] == value for name, value in after["media"].items()))
        self.assertEqual(result["audio_files"], 2)
        self.assertEqual(result["notes"], 2)
        self.assertEqual(result["source_sha256"], before_hash)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), before_hash)
        with closing(sqlite3.connect(self.root / "subset.anki2")) as connection:
            self.assertEqual(connection.execute("select count(*) from graves").fetchone()[0], 0)

    def test_guide_override_cannot_rewrite_vocabulary(self):
        original = snapshot(self.source, self.root)
        guide = next(row for row in original["notes"] if row[2] == 9002)
        overrides = {str(guide[0]): ["Guide", "Required only", "Same sources; full edition on GitHub"]}
        export_subset(self.source, self.target, ["Book::00 Guide", "Book::01 Required"], guide_fields=overrides)
        updated = snapshot(self.target, self.root)
        changed = next(row for row in updated["notes"] if row[0] == guide[0])
        self.assertEqual(changed[6].split("\x1f"), overrides[str(guide[0])])
        self.assertEqual(changed[:3], guide[:3])
        word = next(row for row in original["notes"] if row[2] == 9001)
        with self.assertRaisesRegex(ValueError, "Overrides are only"):
            export_subset(self.source, self.root / "bad.apkg", ["Book"], guide_fields={str(word[0]): ["x", "y", "z"]})
        self.assertFalse((self.root / "bad.apkg").exists())

    def test_missing_deck_or_audio_never_publishes_an_output(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            export_subset(self.source, self.target, ["Book::typo"])
        self.assertFalse(self.target.exists())
        with zipfile.ZipFile(self.source) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        mapping = json.loads(members["media"])
        mapping = {key: name for key, name in mapping.items() if name != "remote audio.mp3"}
        members["media"] = json.dumps(mapping).encode()
        self.repack(members)
        with self.assertRaisesRegex(ValueError, "Missing referenced audio"):
            export_subset(self.source, self.target, ["Book::01 Required"])
        self.assertFalse(self.target.exists())

    def test_existing_source_and_destination_are_never_overwritten(self):
        with self.assertRaisesRegex(ValueError, "new file"):
            export_subset(self.source, self.source, ["Book"])
        self.target.write_bytes(b"user-file")
        with self.assertRaisesRegex(ValueError, "new file"):
            export_subset(self.source, self.target, ["Book"])
        self.assertEqual(self.target.read_bytes(), b"user-file")

    def test_modern_format_and_unsafe_media_are_rejected(self):
        with zipfile.ZipFile(self.source) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        members["collection.anki21b"] = b"modern"
        self.repack(members)
        with self.assertRaisesRegex(ValueError, "legacy"):
            export_subset(self.source, self.target, ["Book"])
        del members["collection.anki21b"]
        mapping = json.loads(members["media"])
        mapping[next(iter(mapping))] = "../private.mp3"
        members["media"] = json.dumps(mapping).encode()
        self.repack(members)
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            export_subset(self.source, self.target, ["Book"])
