"""Read the legacy database without changing it; preserve originals and decisions."""
from pathlib import Path
import json
import os
import re
import sqlite3
import tempfile
from .store import (CARD_FIELDS, backup_database, card_id, connect, event, identity,
                    initialize, sha256_file, transaction)
from .text import (assess_translation, matches_word, parse_numbered_entries,
                   parse_translations, stable_sentence_id, strip_markup)
from .forms import explicit_forms

FIELD_MAP = {"sheet": "sheet", "lesson": "Lesson", "position": "序号", "word": "单词",
             "phonetic": "音标", "definition": "词义", "simple_definition": "简明词义",
             "level": "考试等级", "word_forms": "词形变化"}


def migrate_legacy(source: Path, destination: Path, backups: Path) -> dict:
    source, destination = source.resolve(strict=True), destination.resolve()
    if source == destination:
        raise ValueError("不允许覆盖原始数据库")
    source_hash = sha256_file(source)
    if destination.exists():
        with connect(destination, readonly=True) as existing:
            row = existing.execute("SELECT value FROM metadata WHERE key='legacy_sha256'").fetchone()
            if row and row[0] == source_hash:
                return {"status": "unchanged", "cards": existing.execute("SELECT count(*) FROM cards").fetchone()[0],
                        "source_sha256": source_hash}
        raise ValueError("目标库已存在且不是同一迁移；请选择新库，避免覆盖后续编辑")
    with connect(source, readonly=True) as legacy:
        if legacy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("原始数据库完整性检查失败")
        words = [dict(r) for r in legacy.execute('SELECT * FROM "最终数据"')]
        originals = {r["单词"]: dict(r) for r in legacy.execute('SELECT * FROM "Translate-tmp-1"')}
    snapshot = backup_database(source, backups, label="legacy-original")
    if sha256_file(source) != source_hash:
        raise ValueError("迁移期间原始数据库发生变化，已停止；请暂停旧流水线再试")
    cards, sentences, raw_rows = [], [], []
    seen_cards, seen_sentences = set(), set()
    missing_translation = rejected = needs_review = duplicate_sentences = 0
    for old in words:
        card = {key: str(old.get(column) or "").strip() for key, column in FIELD_MAP.items()}
        if not card["word"] or not card["lesson"] or not card["sheet"]:
            raise ValueError("原始词条缺少单词、单元或课程信息")
        card["audio_filename"] = card["word"].splitlines()[0].strip() + ".mp3"
        card["id"] = card_id(card)
        if card["id"] in seen_cards:
            raise ValueError(f"原始词条身份重复: {card['word']}")
        seen_cards.add(card["id"])
        cards.append(card)
        if card["word"] not in originals:
            raise ValueError(f"原始翻译快照缺少词条: {card['word']}；不能安全对齐例句")
        original = originals[card["word"]]
        # The snapshot is the only source of the numbered translation mapping.
        blob = original.get("句子出处") or ""
        translations = parse_translations(original.get("Translate") or "")
        entries = parse_numbered_entries(blob)
        numbers = {e["number"] for e in entries}
        extras = set(translations) - numbers
        if extras:
            raise ValueError(f"{card['word']} 译文包含无原文编号: {sorted(extras)}")
        raw_rows.append((card["id"], json.dumps({"final": old, "snapshot": original}, ensure_ascii=False)))
        for entry in entries:
            plain = strip_markup(entry["text"])
            source_text = str(entry["source"])
            sid = identity(card["id"], stable_sentence_id(card["word"], plain, source_text))
            if sid in seen_sentences:
                duplicate_sentences += 1
                continue
            seen_sentences.add(sid)
            translation = translations.get(entry["number"], "")
            accepted = matches_word(card["word"], plain, explicit_forms(card["word_forms"]))
            reason = "" if accepted else "word_mismatch"
            trans_reason = assess_translation(translation)
            if (translation and translations and entry["number"] == max(translations)
                    and numbers and max(translations) < max(numbers)
                    and not re.search(r'[。！？.!?][”\"\u2019)]?$', translation.strip())):
                trans_reason = "possibly_truncated_translation_tail"
            if not translation:
                missing_translation += 1
                trans_reason = "missing_translation"
            if trans_reason:
                reason = ";".join(filter(None, (reason, trans_reason)))
                needs_review += bool(translation)
            rejected += not accepted
            sentences.append((sid, card["id"], plain, source_text, translation,
                              entry["number"], int(accepted), reason))
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".migration-", suffix=".sqlite3", dir=destination.parent)
    os.close(fd)
    temp = Path(tmp)
    temp.unlink()
    try:
        initialize(temp)
        with connect(temp) as conn, transaction(conn):
            conn.executemany(f"INSERT INTO cards({','.join(CARD_FIELDS)}) VALUES({','.join('?' for _ in CARD_FIELDS)})",
                             [tuple(c[k] for k in CARD_FIELDS) for c in cards])
            conn.executemany("INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?)", sentences)
            conn.executemany("INSERT INTO legacy_rows VALUES(?,?)", raw_rows)
            conn.executemany("INSERT INTO metadata VALUES(?,?)", [("legacy_sha256", source_hash), ("legacy_snapshot", str(snapshot)), ("schema", "1")])
            summary = {"status": "migrated", "cards": len(cards), "sentences": len(sentences),
                       "rejected_word_matches": rejected, "missing_translations": missing_translation,
                       "review_translations": needs_review, "duplicate_sentences": duplicate_sentences,
                       "source_sha256": source_hash, "snapshot": str(snapshot)}
            event(conn, "migrate-legacy", summary)
        with connect(temp, readonly=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("新数据库完整性校验失败")
        # Hard-link promotion fails rather than replacing a concurrent destination.
        os.link(temp, destination)
        return summary
    finally:
        temp.unlink(missing_ok=True)
