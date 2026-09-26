"""Verify real local inputs, recovery, and a generated APKG without Anki GUI."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_pipeline import __version__
from anki_pipeline.config import load_config
from anki_pipeline.migration import migrate_legacy
from anki_pipeline.quality import quality_report
from anki_pipeline.store import (
    backup_database, logical_digest, restore_database, sha256_file, utc_now,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def write_report(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".local-trial-",
            suffix=".tmp", dir=path.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package", help="APKG to verify; defaults to output/anki-rebuilt-<current version>.apkg"
    )
    parser.add_argument(
        "--report", help="JSON result under configured output/; defaults to local-trial-verification.json"
    )
    args = parser.parse_args()

    cfg = load_config(ROOT / "config.toml")
    package = project_path(args.package) if args.package else cfg.output / f"anki-rebuilt-{__version__}.apkg"
    report_path = project_path(args.report) if args.report else cfg.output / "local-trial-verification.json"
    require(package.is_file() and package.suffix.lower() == ".apkg", f"APKG not found: {package}")
    require(
        report_path.is_relative_to(cfg.output) and report_path.suffix.lower() == ".json",
        f"report must be a JSON file under {cfg.output}",
    )

    baseline = json.loads((ROOT / "docs/legacy-input-sha256.json").read_text(encoding="utf-8"))
    require(len(baseline["files"]) == 12, "expected 12 original input hashes")
    for source, expected in baseline["files"].items():
        require(sha256_file(Path(source)) == expected, f"Original input changed: {source}")

    before = logical_digest(cfg.database)
    repeat = migrate_legacy(cfg.legacy_database, cfg.database, cfg.backups)
    require(
        repeat["status"] == "unchanged" and logical_digest(cfg.database) == before,
        "migration was not idempotent",
    )
    backup = backup_database(cfg.database, cfg.backups, label="verified-recovery")
    with tempfile.TemporaryDirectory(prefix="anki-restore-") as folder:
        restored = Path(folder) / "restored.sqlite3"
        restore_database(backup, restored)
        require(logical_digest(restored) == before, "restored content digest differs")

    quality = quality_report(cfg.database, cfg.audio)
    require(quality["ok"] and quality["counts"]["cards"] == 1960, "local quality/card count failed")

    with zipfile.ZipFile(package) as archive:
        require(archive.testzip() is None, "APKG ZIP CRC failed")
        conn = sqlite3.connect(":memory:")
        try:
            conn.deserialize(archive.read("collection.anki2"))
            require(conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "APKG SQLite integrity failed")
            note_count = conn.execute("SELECT count(*) FROM notes").fetchone()[0]
            card_count = conn.execute("SELECT count(*) FROM cards").fetchone()[0]
            require(note_count == card_count == 1960, "APKG note/card count differs from 1960")
            require(
                conn.execute("SELECT count(*)-count(DISTINCT guid) FROM notes").fetchone()[0] == 0,
                "APKG contains duplicate note GUIDs",
            )
            models, decks = conn.execute("SELECT models,decks FROM col").fetchone()
            require(
                all("<script" not in model["css"].lower() for model in json.loads(models).values()),
                "APKG CSS contains script",
            )
            media = json.loads(archive.read("media"))
            require(len(media) == 1960 and len(set(media.values())) == 1960, "APKG media mapping is incomplete")
            references = {
                name
                for (fields,) in conn.execute("SELECT flds FROM notes")
                for name in re.findall(r"\[sound:([^\]]+)\]", fields)
            }
            require(references == set(media.values()), "APKG sound references differ from media mapping")
            for member, filename in media.items():
                archive_hash = hashlib.sha256(archive.read(member)).hexdigest()
                require(archive_hash == sha256_file(cfg.audio / filename), f"APKG media mismatch: {filename}")

            result = {
                "subject": __version__,
                "executed_at": utc_now(),
                "original_input_hashes_verified": len(baseline["files"]),
                "idempotent_migration": True,
                "backup_restore_digest_equal": True,
                "content_digest": before,
                "package": str(package),
                "package_sha256": sha256_file(package),
                "package_notes": note_count,
                "package_cards": card_count,
                "package_lesson_decks": sum(
                    deck["name"] != "Default" for deck in json.loads(decks).values()
                ),
                "media_verified": len(media),
                "quality": quality["counts"],
                "anki_client_import": "NOT_RUN",
                "full_translation_semantic_review": "NOT_RUN",
            }
        finally:
            conn.close()

    write_report(report_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
