"""Verify real local inputs, idempotency, backup recovery and the generated APKG."""
from pathlib import Path
import json
import re
import sqlite3
import tempfile
import zipfile
from anki_pipeline.config import load_config
from anki_pipeline.migration import migrate_legacy
from anki_pipeline.quality import quality_report
from anki_pipeline.store import (backup_database, logical_digest, restore_database,
                                 sha256_file, utc_now)

ROOT = Path(__file__).resolve().parents[1]
cfg = load_config(ROOT / "config.toml")
baseline = json.loads((ROOT / "docs/legacy-input-sha256.json").read_text())
for path, expected in baseline["files"].items():
    assert sha256_file(Path(path)) == expected, f"Original input changed: {path}"
before = logical_digest(cfg.database)
repeat = migrate_legacy(cfg.legacy_database, cfg.database, cfg.backups)
assert repeat["status"] == "unchanged" and logical_digest(cfg.database) == before
backup = backup_database(cfg.database, cfg.backups, label="verified-recovery")
with tempfile.TemporaryDirectory() as folder:
    restored = Path(folder) / "restored.sqlite3"
    restore_database(backup, restored)
    assert logical_digest(restored) == before
report = quality_report(cfg.database, cfg.audio)
assert report["ok"] and report["counts"]["cards"] == 1960
package = cfg.output / "anki-rebuilt-3.0.0rc1.apkg"
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(archive.read("collection.anki2"))
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        note_count = conn.execute("SELECT count(*) FROM notes").fetchone()[0]
        card_count = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
        assert note_count == card_count == 1960
        assert conn.execute("SELECT count(*)-count(DISTINCT guid) FROM notes").fetchone()[0] == 0
        models, decks = conn.execute("SELECT models,decks FROM col").fetchone()
        assert all("<script" not in m["css"].lower() for m in json.loads(models).values())
        media = json.loads(archive.read("media"))
        assert len(media) == 1960 and len(set(media.values())) == 1960
        references = {name for fields, in conn.execute("SELECT flds FROM notes") for name in re.findall(r"\[sound:([^\]]+)\]", fields)}
        assert references == set(media.values())
        for member, filename in media.items():
            import hashlib
            assert hashlib.sha256(archive.read(member)).hexdigest() == sha256_file(cfg.audio / filename)
        result = {
            "subject": "3.0.0-rc.1", "executed_at": utc_now(), "original_input_hashes_verified": len(baseline["files"]),
            "idempotent_migration": True, "backup_restore_digest_equal": True,
            "content_digest": before, "package_sha256": sha256_file(package),
            "package_notes": note_count, "package_cards": card_count,
            "package_lesson_decks": sum(name["name"] != "Default" for name in json.loads(decks).values()),
            "media_verified": len(media), "quality": report["counts"],
            "anki_client_import": "NOT_RUN", "full_translation_semantic_review": "NOT_RUN",
        }
    finally:
        conn.close()
(ROOT / "docs/local-trial-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
