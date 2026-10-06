"""Export named deck subtrees without importing or rewriting the source APKG.

Supports the legacy collection.anki2 format emitted by this project. Shared
non-audio resources are retained conservatively; unused audio is omitted.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import unquote, urlsplit
import zipfile

_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".flac"}
_RESOURCE = re.compile(r"(?<![\w.#/-])([\w.-]+\.(?:mp3|ogg|wav|m4a|flac))(?![\w.-])", re.I)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _references(text: str) -> set[str]:
    """Read literal sound/src names, including names with spaces and entities."""
    text = html.unescape(text)
    names = set()
    def explicit(match):
        names.add(match[1])
        return ""
    # Do not tokenize a suffix of a structured name containing spaces or '&'.
    text = re.sub(r"\[sound:([^\]]+)\]", explicit, text)
    def src_reference(match):
        url = urlsplit(match[1])
        if url.scheme or url.netloc:
            return ""  # Remote/data media are not local ZIP references.
        name = unquote(url.path).removeprefix("./")
        if Path(name).suffix.lower() in _AUDIO_EXTENSIONS and ("/" in name or "\\" in name):
            raise ValueError("Audio src must reference a flat local media filename")
        names.add(name)
        return ""
    text = re.sub(r'''\bsrc\s*=\s*["']([^"']+)["']''', src_reference, text)
    names.update(_RESOURCE.findall(text))
    return names


def export_subset(source: Path, destination: Path, deck_names: list[str], *,
                  guide_fields: dict[str, list[str]] | None = None) -> dict:
    """Keep whole notes, their cards/history and stable identifiers.

    Optional field replacements are restricted to guide notes with the exact
    Title/Overview/Guide schema. Vocabulary fields are never rewritten.
    Destination publication is exclusive and occurs only after validation.
    """
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError("Destination must be a new file, separate from the source")
    if not deck_names or any(not isinstance(name, str) or not name.strip() for name in deck_names):
        raise ValueError("At least one explicit, non-empty deck name is required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = _sha(source)
    with tempfile.TemporaryDirectory(prefix="apkg-subset-", dir=destination.parent) as tmp:
        db = Path(tmp) / "collection.anki2"
        candidate = Path(tmp) / "subset.apkg"
        with zipfile.ZipFile(source) as archive:
            members = archive.namelist()
            if len(members) != len(set(members)):
                raise ValueError("Duplicate ZIP members")
            if "collection.anki2" not in members or any(
                    name in members for name in ("collection.anki21", "collection.anki21b")):
                raise ValueError("Only legacy collection.anki2 APKGs are supported; re-export first")
            media = json.loads(archive.read("media"))
            if not isinstance(media, dict) or any(
                    not isinstance(key, str) or not key.isdecimal() or key not in members
                    or not isinstance(name, str) or not name or Path(name).name != name
                    or "/" in name or "\\" in name or name in {".", ".."}
                    for key, name in media.items()) or len(set(media.values())) != len(media):
                raise ValueError("Unsafe, missing or duplicate media mappings")
            with archive.open("collection.anki2") as incoming, db.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing)
            connection = sqlite3.connect(db)
            try:
                if connection.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid source database")
                col = connection.execute("select decks, models, conf from col").fetchone()
                decks, models, conf = map(json.loads, col)
                selected = set()
                for requested in deck_names:
                    found = {int(key) for key, deck in decks.items()
                             if deck["name"] == requested or deck["name"].startswith(requested + "::")}
                    if not found:
                        raise ValueError(f"Deck subtree not found: {requested}")
                    selected.update(found)
                cards = connection.execute("select * from cards order by id").fetchall()
                kept_cards = [row for row in cards if row[2] in selected]
                note_ids = {row[1] for row in kept_cards}
                if not kept_cards:
                    raise ValueError("Selected subtrees contain no cards")
                if any(row[1] in note_ids and row[2] not in selected for row in cards):
                    raise ValueError("A selected note has sibling cards outside the selected subtrees")
                notes = [row for row in connection.execute("select * from notes order by id")
                         if row[0] in note_ids]
                if len(notes) != len(note_ids):
                    raise ValueError("Selected cards have missing notes")
                used_models = {str(row[2]) for row in notes}
                models = {key: model for key, model in models.items() if key in used_models}
                if set(models) != used_models:
                    raise ValueError("Selected notes have missing models")
                overrides = {} if guide_fields is None else guide_fields
                if not isinstance(overrides, dict) or set(overrides) - {str(nid) for nid in note_ids}:
                    raise ValueError("Guide overrides must address selected notes")
                for row in notes:
                    if str(row[0]) not in overrides:
                        continue
                    fields = overrides[str(row[0])]
                    schema = [field["name"] for field in models[str(row[2])]["flds"]]
                    if schema != ["Title", "Overview", "Guide"] or not isinstance(fields, list) \
                            or len(fields) != 3 or any(not isinstance(field, str) or "\x1f" in field for field in fields):
                        raise ValueError("Overrides are only allowed for Title/Overview/Guide notes")
                    # The title/sort field remains stable. Guides changed for the
                    # subset update normally while vocabulary rows stay exact.
                    if fields[0] != row[6].split("\x1f")[0]:
                        raise ValueError("Guide title must remain unchanged")
                    connection.execute("update notes set flds=?, mod=mod+1, usn=-1 where id=?",
                                       ("\x1f".join(fields), row[0]))
                connection.execute("create temp table kept_notes (id integer primary key)")
                connection.executemany("insert into kept_notes values (?)", [(nid,) for nid in note_ids])
                connection.execute("delete from cards where nid not in (select id from kept_notes)")
                connection.execute("delete from notes where id not in (select id from kept_notes)")
                connection.execute("delete from revlog where cid not in (select id from cards)")
                # A partial export must never distribute deletion tombstones.
                connection.execute("delete from graves")
                ancestors = set()
                for did in selected:
                    parts = decks[str(did)]["name"].split("::")
                    ancestors.update("::".join(parts[:i]) for i in range(1, len(parts) + 1))
                decks = {key: deck for key, deck in decks.items()
                         if int(key) in selected or deck["name"] in ancestors or key == "1"}
                conf["curDeck"] = min(selected)
                conf["activeDecks"] = sorted(selected)
                conf["curModel"] = sorted(used_models)[0]
                connection.execute("update col set decks=?, models=?, conf=?",
                                   tuple(json.dumps(value, ensure_ascii=False) for value in (decks, models, conf)))
                current_notes = connection.execute("select * from notes order by id").fetchall()
                if connection.execute("select * from cards order by id").fetchall() != kept_cards:
                    raise ValueError("Selected card scheduling changed")
                if [row for row in current_notes if str(row[0]) not in overrides] != [
                        row for row in notes if str(row[0]) not in overrides]:
                    raise ValueError("Vocabulary note contents changed")
                references = set()
                for model in models.values():
                    references.update(_references(model.get("css", "")))
                    for template in model["tmpls"]:
                        for face in ("qfmt", "afmt"):
                            references.update(_references(template[face]))
                for row in current_notes:
                    references.update(_references(row[6]))
                # Do not prune shared scripts/images or resources with dynamic
                # references. Scan them too, retaining any audio they name.
                for key, name in media.items():
                    if Path(name).suffix.lower() in {".js", ".css", ".html"}:
                        references.update(_references(archive.read(key).decode("utf-8")))
                retained = {key: name for key, name in media.items()
                            if Path(name).suffix.lower() not in _AUDIO_EXTENSIONS or name in references}
                missing = {name for name in references if Path(name).suffix.lower() in _AUDIO_EXTENSIONS
                           and not name.startswith(("http:", "https:", "data:")) and name not in media.values()}
                if missing:
                    raise ValueError(f"Missing referenced audio: {sorted(missing)[:5]}")
                connection.commit()
                connection.execute("vacuum")
                if connection.execute("pragma integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Invalid subset database")
            finally:
                connection.close()
            with zipfile.ZipFile(candidate, "x", compression=zipfile.ZIP_DEFLATED) as out:
                out.write(db, "collection.anki2")
                out.writestr("media", json.dumps(retained, ensure_ascii=False))
                for key in retained:
                    with archive.open(key) as incoming, out.open(key, "w") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
            with zipfile.ZipFile(candidate) as result:
                if result.testzip() is not None:
                    raise ValueError("Corrupt output archive")
                for key in retained:
                    with archive.open(key) as original, result.open(key) as exported:
                        if hashlib.file_digest(original, "sha256").digest() != hashlib.file_digest(exported, "sha256").digest():
                            raise ValueError("Exported media changed")
        if _sha(source) != before:
            raise ValueError("Source package changed during export")
        report = {"source_sha256": before, "package_sha256": _sha(candidate),
                  "package_bytes": candidate.stat().st_size, "database_bytes": db.stat().st_size,
                  "notes": len(notes), "cards": len(kept_cards),
                  "nonempty_decks": len({row[2] for row in kept_cards}),
                  "audio_files": sum(Path(name).suffix.lower() in _AUDIO_EXTENSIONS for name in retained.values()),
                  "media_files": len(retained), "guide_overrides": sorted(overrides),
                  "vocabulary_rows_and_scheduling_preserved": True,
                  "source_unchanged": True, "live_collection_changed": False}
        try:
            with destination.open("xb") as outgoing, candidate.open("rb") as incoming:
                shutil.copyfileobj(incoming, outgoing)
        except FileExistsError:
            raise ValueError("Destination appeared during export; not overwritten") from None
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return report
