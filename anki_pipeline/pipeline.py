"""Explicit application operations; no work runs at import time."""
from pathlib import Path
import shutil
import os
import tempfile
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from .store import backup_database, connect, event, identity, transaction
from .text import matches_word, stable_sentence_id, strip_markup
from .forms import explicit_forms


def copy_legacy_audio(database: Path, source: Path, target: Path, *, package: Path | None = None) -> dict:
    source = source.resolve()
    target = target.resolve()
    if source == target or source in target.parents:
        raise ValueError("新版音频必须位于原始音频目录之外")
    with connect(database, readonly=True) as conn:
        filenames = sorted({r[0] for r in conn.execute("SELECT audio_filename FROM cards") if r[0]})
    if package is not None:
        return _copy_package_audio(package, filenames, target)
    source = source.resolve(strict=True)
    planned = []
    for filename in filenames:
        if Path(filename).name != filename or "\\" in filename:
            raise ValueError(f"非法音频名: {filename}")
        src = (source / filename).resolve(strict=True)
        if not src.is_relative_to(source) or not src.is_file() or src.stat().st_size == 0:
            raise ValueError(f"音频不存在或越界: {filename}")
        planned.append((src, target / filename))
    target.mkdir(parents=True, exist_ok=True)
    def copy_one(pair):
        from .inputs import _valid_mp3
        src, dst = pair
        if dst.is_symlink():
            raise ValueError("音频目标不能为符号链接")
        if dst.exists():
            # Existing target may contain corrected audio; never overwrite it.
            if not dst.is_file() or dst.stat().st_size > 5 * 1024 * 1024 or not _valid_mp3(dst.read_bytes()):
                raise ValueError(f"已存在的音频无效，已保留供修复: {dst.name}")
            return 0
        fd, temp = tempfile.mkstemp(prefix=".media-", dir=target)
        os.close(fd)
        try:
            shutil.copyfile(src, temp)
            os.link(temp, dst)
            return 1
        finally:
            Path(temp).unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        copied = sum(pool.map(copy_one, planned))
    return {"files": len(filenames), "copied": copied}


def _copy_package_audio(package: Path, filenames: list[str], target: Path) -> dict:
    """Recover known MP3 names from a bounded Anki archive; never extract paths."""
    from .inputs import _valid_mp3
    from .store import sha256_file
    def unique_mapping(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("卡包媒体索引包含重复键")
            result[key] = value
        return result
    with zipfile.ZipFile(package) as archive:
        try:
            index_info = archive.getinfo("media")
        except KeyError as exc:
            raise ValueError("卡包缺少媒体索引") from exc
        if index_info.file_size > 2 * 1024 * 1024:
            raise ValueError("卡包媒体索引过大")
        mapping = json.loads(archive.read("media"), object_pairs_hook=unique_mapping)
        if not isinstance(mapping, dict):
            raise ValueError("卡包媒体索引无效")
        lookup = {}
        for entry, name in mapping.items():
            if not isinstance(entry, str) or not entry.isdigit() or not isinstance(name, str):
                raise ValueError("卡包媒体映射无效")
            if name in lookup:
                raise ValueError("卡包含重复媒体名称")
            lookup[name] = entry
        prepared = []
        if len(filenames) > 20000:
            raise ValueError("媒体文件数量超过 20000 限制")
        try:
            aggregate = sum(archive.getinfo(lookup[name]).file_size for name in filenames if name in lookup)
        except KeyError as exc:
            raise ValueError("卡包索引指向不存在的媒体成员") from exc
        if aggregate > 256 * 1024 * 1024:
            raise ValueError("媒体解压总量超过 256 MiB 限制")
        for filename in filenames:
            if (Path(filename).name != filename or "\\" in filename or not filename.lower().endswith(".mp3")
                    or any(c in filename for c in "[]<>&") or any(ord(c) < 32 or ord(c) == 127 for c in filename)):
                raise ValueError(f"非法音频名: {filename}")
            if filename not in lookup:
                raise ValueError(f"旧卡包缺少音频: {filename}")
            info = archive.getinfo(lookup[filename])
            if not 128 <= info.file_size <= 5 * 1024 * 1024:
                raise ValueError(f"媒体大小异常: {filename}")
            data = archive.read(info)  # ZipFile validates CRC while reading.
            if not _valid_mp3(data):
                raise ValueError(f"无效 MP3: {filename}")
            prepared.append((filename, data))
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for filename, data in prepared:
        dst = target / filename
        if dst.is_symlink():
            raise ValueError("音频目标不能为符号链接")
        if dst.exists():
            if not dst.is_file() or dst.stat().st_size > 5 * 1024 * 1024 or not _valid_mp3(dst.read_bytes()):
                raise ValueError(f"已存在的音频无效，已保留供修复: {filename}")
            continue
        fd, temporary = tempfile.mkstemp(prefix=".media-", dir=target)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.link(temporary, dst)
            copied += 1
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"files": len(filenames), "copied": copied, "archive": str(package), "archive_sha256": sha256_file(package)}


def add_examples(database: Path, found: dict[str, list[dict]], backups: Path) -> dict:
    with connect(database, readonly=True) as conn:
        cards = [dict(r) for r in conn.execute("SELECT * FROM cards")]
    planned = []
    for card in cards:
        for number, example in enumerate(found.get(card["word"], []), 1):
            text = strip_markup(example["text"])
            source = str(example["source"])
            if not text or not matches_word(card["word"], text, explicit_forms(card["word_forms"])):
                raise ValueError(f"PDF 检索返回了不匹配的例句: {card['word']}")
            sid = identity(card["id"], stable_sentence_id(card["word"], text, source))
            planned.append((sid, card["id"], text, source, "", number, 1, "missing_translation"))
    backup = backup_database(database, backups)
    with connect(database) as conn, transaction(conn):
        before = conn.total_changes
        conn.executemany("INSERT INTO sentences VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING", planned)
        inserted = conn.total_changes - before
        event(conn, "extract-pdf", {"candidate_sentences": len(planned), "inserted": inserted})
    return {"candidate_sentences": len(planned), "inserted": inserted, "backup": str(backup)}


def reclassify_examples(database: Path, backups: Path) -> dict:
    """Recheck only lexical acceptance; never replace source text or translations."""
    backup = backup_database(database, backups)
    with connect(database) as conn, transaction(conn):
        rows = conn.execute("SELECT s.*,c.word,c.word_forms FROM sentences s JOIN cards c ON c.id=s.card_id").fetchall()
        updates = []
        for row in rows:
            accepted = int(matches_word(row["word"], row["text"], explicit_forms(row["word_forms"])))
            reasons = [r for r in row["review_reason"].split(";") if r and r != "word_mismatch"]
            if not accepted:
                reasons.insert(0, "word_mismatch")
            reason = ";".join(reasons)
            if accepted != row["accepted"] or reason != row["review_reason"]:
                updates.append((accepted, reason, row["id"]))
        conn.executemany("UPDATE sentences SET accepted=?,review_reason=? WHERE id=?", updates)
        if updates:
            event(conn, "reclassify-examples", {"updated": len(updates)})
    return {"updated": len(updates), "backup": str(backup)}
