"""One sentence per CSV row; immutable IDs and content hashes prevent row drift."""
import csv
from pathlib import Path
from .store import backup_database, connect, event, identity, transaction
from .text import assess_translation

FIELDS = ("sentence_id", "word", "text", "source", "content_hash", "translation_revision", "translation")


def content_hash(row) -> str:
    return identity(row["id"], row["word"], row["text"], row["source"])


def translation_revision(row) -> str:
    return identity(row["translation"], row["review_reason"])


def export_translations(database: Path, target: Path, *, pending_only: bool = True) -> int:
    with connect(database, readonly=True) as conn:
        sql = "SELECT s.*, c.word FROM sentences s JOIN cards c ON c.id=s.card_id WHERE s.accepted=1"
        if pending_only:
            sql += " AND (s.translation='' OR s.review_reason<>'')"
        rows = conn.execute(sql + " ORDER BY c.sheet,c.lesson,c.position,s.original_number,s.id").fetchall()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive output: don't overwrite the user's in-progress translations.
    with target.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"sentence_id": row["id"], "word": row["word"], "text": row["text"],
                             "source": row["source"], "content_hash": content_hash(row),
                             "translation_revision": translation_revision(row), "translation": row["translation"]})
    return len(rows)


def import_translations(database: Path, source: Path, backups: Path) -> dict:
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("翻译文件超过 64 MiB 限制")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if set(reader.fieldnames or []) != set(FIELDS):
            raise ValueError("翻译文件列名不匹配；请使用 export-translations 生成模板")
        imported = list(reader)
    with connect(database, readonly=True) as conn:
        current = {r["id"]: dict(r) for r in conn.execute("SELECT s.*,c.word FROM sentences s JOIN cards c ON c.id=s.card_id")}
    updates, seen = [], set()
    for line, row in enumerate(imported, 2):
        sid = row["sentence_id"]
        if sid in seen or sid not in current:
            raise ValueError(f"第 {line} 行的句子 ID 重复或不存在")
        seen.add(sid)
        existing = current[sid]
        if row["content_hash"] != content_hash(existing) or any(row[k] != existing[k] for k in ("word", "text", "source")):
            raise ValueError(f"第 {line} 行原文或来源被修改；不能继续对齐译文")
        if not existing["accepted"]:
            raise ValueError(f"第 {line} 行是已隔离的误匹配句子")
        value = (row.get("translation") or "").strip()
        if not value:  # Blank means no change, never erase completed human work.
            continue
        if row["translation_revision"] != translation_revision(existing):
            if value == existing["translation"]:
                continue  # A replay must not clear a newer review flag.
            raise ValueError(f"第 {line} 行译文已被其他导入修改；请重新导出，避免覆盖较新的人工编辑")
        if len(value) > 32767 or assess_translation(value):
            raise ValueError(f"第 {line} 行译文过长或明显不完整，请校对")
        if value != existing["translation"] or existing["review_reason"]:
            updates.append((value, "", sid))
    if not updates:
        return {"rows": len(imported), "updated": 0}
    backup = backup_database(database, backups)
    with connect(database) as conn, transaction(conn):
        # Validate again under the write lock so concurrent edits can't be lost.
        for _, _, sid in updates:
            fresh = conn.execute("SELECT s.*,c.word FROM sentences s JOIN cards c ON c.id=s.card_id WHERE s.id=?", (sid,)).fetchone()
            if not fresh or dict(fresh) != current[sid]:
                raise ValueError("校验后数据库被其他操作修改，请重新导出")
        conn.executemany("UPDATE sentences SET translation=?,review_reason=? WHERE id=?", updates)
        event(conn, "import-translations", {"rows": len(imported), "updated": len(updates)})
    return {"rows": len(imported), "updated": len(updates), "backup": str(backup)}
