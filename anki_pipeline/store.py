"""Versioned SQLite state with atomic transactions and verified online backups."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

SCHEMA_VERSION = 1
CARD_FIELDS = ("id", "sheet", "lesson", "position", "word", "phonetic", "definition",
               "simple_definition", "level", "word_forms", "audio_filename")
SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE cards (
 id TEXT PRIMARY KEY, sheet TEXT NOT NULL, lesson TEXT NOT NULL, position TEXT NOT NULL,
 word TEXT NOT NULL CHECK(length(trim(word))>0), phonetic TEXT NOT NULL DEFAULT '',
 definition TEXT NOT NULL DEFAULT '', simple_definition TEXT NOT NULL DEFAULT '',
 level TEXT NOT NULL DEFAULT '', word_forms TEXT NOT NULL DEFAULT '', audio_filename TEXT NOT NULL DEFAULT '',
 UNIQUE(sheet,lesson,word));
CREATE TABLE sentences (
 id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(id), text TEXT NOT NULL,
 source TEXT NOT NULL, translation TEXT NOT NULL DEFAULT '', original_number INTEGER NOT NULL,
 accepted INTEGER NOT NULL CHECK(accepted IN (0,1)), review_reason TEXT NOT NULL DEFAULT '');
CREATE INDEX sentences_card ON sentences(card_id,accepted,original_number);
CREATE TABLE legacy_rows (card_id TEXT PRIMARY KEY REFERENCES cards(id), payload TEXT NOT NULL);
CREATE TABLE events (id INTEGER PRIMARY KEY, happened_at TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def identity(*values: str) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def card_id(card: dict) -> str:
    return identity(str(card["sheet"]).strip(), str(card["lesson"]).strip(), str(card["word"]).strip())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def connect(path: Path, *, readonly: bool = False):
    path = Path(path).resolve()
    mode = "ro" if readonly else "rw"
    conn = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    try:
        yield conn
    finally:
        conn.close()


def initialize(path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        with connect(path, readonly=True) as conn:
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("未知数据库版本；请使用独立的新数据库路径")
        return
    # Exclusive creation prevents silently replacing an existing user file.
    with path.open("xb"):
        pass
    try:
        conn = sqlite3.connect(path)
        try:
            conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;")
        finally:
            conn.close()
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def event(conn, action: str, details: dict):
    conn.execute("INSERT INTO events(happened_at,action,details) VALUES(?,?,?)",
                 (utc_now(), action, json.dumps(details, ensure_ascii=False, sort_keys=True)))


def backup_database(path: Path, directory: Path, *, label: str = "before-write") -> Path:
    path = Path(path).resolve(strict=True)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{label}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.sqlite3"
    with connect(path, readonly=True) as src:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            result = dst.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise ValueError(f"备份完整性失败: {result}")
        finally:
            dst.close()
    return dest


def restore_database(backup: Path, destination: Path):
    """Restore only to a new file. The active database is never overwritten."""
    backup = Path(backup).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("恢复目标必须是新文件；保留当前库以便对账")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb"):
        pass
    try:
        with connect(backup, readonly=True) as src:
            dst = sqlite3.connect(destination)
            try:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("恢复完整性校验失败")
            finally:
                dst.close()
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def logical_digest(path: Path) -> str:
    """Ignore event history; compare owned learning content deterministically."""
    with connect(path, readonly=True) as conn:
        content = {t: [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY 1')]
                   for t in ("cards", "sentences", "legacy_rows", "metadata")}
    return identity(json.dumps(content, sort_keys=True, ensure_ascii=False))


def upsert_cards(path: Path, cards: list[dict], backups: Path) -> int:
    normalized = []
    seen = set()
    for item in cards:
        row = {key: str(item.get(key, "")).strip() for key in CARD_FIELDS if key != "id"}
        if not row["word"] or not row["sheet"] or not row["lesson"]:
            raise ValueError("词条缺少 word/sheet/lesson")
        row["id"] = card_id(row)
        if row["id"] in seen:
            raise ValueError(f"重复词条: {row['word']}")
        seen.add(row["id"])
        normalized.append(row)
    initialize(path)
    backup_database(path, backups)
    columns = ",".join(CARD_FIELDS)
    update = ",".join(f'{f}=CASE WHEN excluded.{f}<>\'\' THEN excluded.{f} ELSE cards.{f} END'
                       for f in CARD_FIELDS if f != "id")
    with connect(path) as conn, transaction(conn):
        conn.executemany(f"INSERT INTO cards({columns}) VALUES({','.join('?' for _ in CARD_FIELDS)}) "
                         f"ON CONFLICT(id) DO UPDATE SET {update}",
                         [tuple(r[k] for k in CARD_FIELDS) for r in normalized])
        event(conn, "import-wordbook", {"rows": len(normalized)})
    return len(normalized)
