"""Verify an APKG update with Anki's installed backend in a disposable collection.

This does not launch Anki's GUI, access Anki2 profiles, or sync.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
from importlib import metadata
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
DEFAULT_ANKI_PACKAGES = Path("/Applications/Anki.app/Contents/Resources/app_packages")
DEFAULT_ECDICT_LICENSE = ROOT.parent / "ECDICT" / "LICENSE"
FIELD_NAMES = (
    "Word", "Phonetic", "Definition", "SimpleDefinition", "Level",
    "WordForms", "Audio", "Examples", "Meta", "Note",
)
MIT_BODY = '''Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mp3_count(collection) -> int:
    media_dir = Path(collection.media.dir())
    return sum(path.is_file() for path in media_dir.glob("*.mp3"))


def safe_media_name(value: object) -> bool:
    return bool(
        isinstance(value, str) and value not in {"", ".", ".."}
        and not any(character in value for character in "/\\:")
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def package_media_hashes(package: Path) -> dict[str, str]:
    """Read exact filename/content identities without extracting the APKG."""
    result: dict[str, str] = {}
    with zipfile.ZipFile(package) as archive:
        mapping = json.loads(archive.read("media"))
        require(isinstance(mapping, dict), f"invalid media mapping: {package}")
        members = set(archive.namelist())
        for member, name in mapping.items():
            require(isinstance(member, str) and member.isascii() and member.isdecimal(),
                    f"invalid numbered media member: {member!r}")
            require(safe_media_name(name), f"unsafe media filename: {name!r}")
            require(name not in result, f"duplicate media filename: {name!r}")
            require(member in members, f"missing media member: {member!r}")
            digest = hashlib.sha256()
            with archive.open(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result[name] = digest.hexdigest()
    return result


def merge_package_media(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    conflicts = {name for name in old.keys() & new.keys() if old[name] != new[name]}
    require(not conflicts, f"conflicting media contents for unchanged names: {sorted(conflicts)[:5]}")
    return old | new


def verify_imported_media(media_dir: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = media_dir / name
        require(path.is_file(), f"imported media missing: {name}")
        require(file_sha256(path) == digest, f"imported media hash differs: {name}")


class CardMarkup(HTMLParser):
    """Record actual HTML elements, ignoring selector names inside CSS or JS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tag_classes: set[tuple[str, str]] = set()
        self.tag_ids: set[tuple[str, str]] = set()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.source_reader_choices: list[set[str | None]] = []
        self.dictionary_source_choices: list[set[str | None]] = []
        self._reader_choices: set[str | None] | None = None
        self._dictionary_choices: set[str | None] | None = None
        self.ecdict_license_notices: list[dict] = []
        self._license_notice: dict | None = None
        self._license_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._license_notice is not None:
            self._license_notice["nested_markup"] = True
            self._license_depth += 1
        if tag == "div" and "ecdict-license-notice" in (attributes.get("class") or "").split():
            notice = {"attributes": attributes, "text": [], "nested_markup": False}
            self.ecdict_license_notices.append(notice)
            if self._license_notice is None:
                self._license_notice = notice
                self._license_depth = 1
        self.elements.append((tag, attributes))
        for name in (attributes.get("class") or "").split():
            self.tag_classes.add((tag, name))
        if element_id := attributes.get("id"):
            self.tag_ids.add((tag, element_id))
        if tag == "select":
            self._reader_choices = None
            self._dictionary_choices = None
            if "source-reader" in (attributes.get("class") or "").split():
                self._reader_choices = set()
                self.source_reader_choices.append(self._reader_choices)
            if "dictionary-audio-source" in (attributes.get("class") or "").split():
                self._dictionary_choices = set()
                self.dictionary_source_choices.append(self._dictionary_choices)
        elif tag == "option":
            if self._reader_choices is not None:
                self._reader_choices.add(attributes.get("value"))
            if self._dictionary_choices is not None:
                self._dictionary_choices.add(attributes.get("value"))

    def handle_endtag(self, tag: str) -> None:
        if self._license_notice is not None:
            self._license_depth -= 1
            if self._license_depth == 0:
                self._license_notice = None
        if tag == "select":
            self._reader_choices = None
            self._dictionary_choices = None

    def handle_data(self, data: str) -> None:
        if self._license_notice is not None:
            self._license_notice["text"].append(data)


def card_markup(content: str) -> CardMarkup:
    markup = CardMarkup()
    markup.feed(content)
    markup.close()
    return markup


def safe_source_url(value: str | None) -> bool:
    if not value or any(ord(character) <= 32 or ord(character) == 127 for character in value):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port also validates its numeric value and range.
        parsed.port
        return bool(
            parsed.scheme in {"http", "https"} and parsed.hostname
            and not parsed.username and not parsed.password
        )
    except ValueError:
        return False


def source_jump_controls(markup: CardMarkup) -> bool:
    jumps = [attributes for tag, attributes in markup.elements
             if tag == "a" and "sentence-jump" in (attributes.get("class") or "").split()]
    if not jumps or ("select", "source-reader") not in markup.tag_classes:
        return False
    if not markup.source_reader_choices or not all(
        {"latex", "full-paper"} <= choices for choices in markup.source_reader_choices
    ):
        return False
    for attributes in jumps:
        reader = attributes.get("data-reader")
        latex_url = attributes.get("data-latex-url")
        full_paper_url = attributes.get("data-full-paper-url")
        if reader not in {"latex", "full-paper"}:
            return False
        if not safe_source_url(latex_url) or not safe_source_url(full_paper_url):
            return False
        if attributes.get("href") != (latex_url if reader == "latex" else full_paper_url):
            return False
        if attributes.get("target") != "_blank" or "noopener" not in (attributes.get("rel") or "").split():
            return False
    return True


def dictionary_audio_references(markup: CardMarkup) -> dict[str, set[str]]:
    references: dict[str, set[str]] = {}
    for tag, attributes in markup.elements:
        source = attributes.get("data-dictionary-source")
        if tag != "audio" or source is None:
            continue
        require(source in {"oxford", "webster"}, f"unknown dictionary audio source: {source}")
        name = attributes.get("src")
        require(safe_media_name(name), f"dictionary audio must reference packaged local media: {name!r}")
        references.setdefault(source, set()).add(name)
    return references


def dictionary_card_controls(front: CardMarkup, back: CardMarkup, *,
                             allow_wordbook_fallback: bool = False,
                             allow_ecdict_fallback: bool = False) -> bool:
    if not (front.dictionary_source_choices or dictionary_audio_references(front)):
        return True  # Legacy packages retain their existing acceptance criteria.
    definition_sources = {"oxford"}
    if allow_wordbook_fallback:
        definition_sources.add("wordbook")
    if allow_ecdict_fallback:
        definition_sources.add("ecdict")
    return bool(
        front.dictionary_source_choices
        and all({"oxford", "webster"} <= choices for choices in front.dictionary_source_choices)
        and any(tag == "div" and attributes.get("data-dictionary") in definition_sources
                and "dictionary-definition" in (attributes.get("class") or "").split()
                for tag, attributes in back.elements)
        and ("section", "secondary-definition") not in back.tag_classes
    )


def card_rendering_sample(collection, card_ids: set[int]) -> int:
    """Find one card with distinct front/answer markup and lookup script."""
    for card_id in sorted(card_ids):
        card = collection.get_card(card_id)
        question = card.question()
        answer = card.answer()
        front = card_markup(question)
        back = card_markup(answer)
        if (
            ("h1", "word") in front.tag_classes
            and ("a", "dictionary-link") in front.tag_classes
            and "eudic://x-callback-url/searchword?word=" in question
            and ("hr", "answer") not in front.tag_ids
            and ("section", "primary-definition") not in front.tag_classes
            and ("button", "sentence-play") not in front.tag_classes
            and ("a", "sentence-jump") not in front.tag_classes
            and ("select", "source-reader") not in front.tag_classes
            and ("mark", "target-word") not in front.tag_classes
            and ("hr", "answer") in back.tag_ids
            and ("section", "primary-definition") in back.tag_classes
            and ("mark", "target-word") in back.tag_classes
            and ("button", "sentence-play") not in back.tag_classes
            and source_jump_controls(back)
            and dictionary_card_controls(front, back)
        ):
            return card_id
    raise RuntimeError("no card renders the expected front/back lookup, answer, source jump, reader control, dictionary controls and highlighting markup")


def verify_ecdict_metadata(fields: list[str], expected_license: str | None) -> bool:
    """Require source-marked tags and the exact full hidden source MIT notice."""
    markups = [card_markup(field) for field in fields]
    if not any(markup.ecdict_license_notices or any(
        attributes.get("data-dictionary") == "ecdict" for _, attributes in markup.elements)
        for markup in markups
    ):
        return False
    require(expected_license is not None, "ECDICT metadata requires its source LICENSE")
    normalized_license = " ".join(expected_license.split())
    require(normalized_license.startswith("MIT License") and "Copyright" in normalized_license
            and " ".join(MIT_BODY.split()) in normalized_license,
            "ECDICT source license must contain the complete MIT terms")
    require(len(fields) == len(FIELD_NAMES), "ECDICT metadata requires the ten-field note contract")
    levels = markups[FIELD_NAMES.index("Level")]
    tag_markers = [attributes for tag, attributes in levels.elements
                   if (tag == "ul" and "level-list" in (attributes.get("class") or "").split())
                   or (tag == "small" and "dictionary-missing" in (attributes.get("class") or "").split())]
    require(len(tag_markers) == 1 and tag_markers[0].get("data-dictionary") == "ecdict",
            "ECDICT exam tag source must be explicit and must not inherit old tag lists")
    require(len(levels.ecdict_license_notices) == 1, "ECDICT license notice is missing or duplicated")
    notice = levels.ecdict_license_notices[0]
    attrs = notice["attributes"]
    require("hidden" in attrs and attrs.get("aria-hidden") == "true" and not notice["nested_markup"],
            "ECDICT license notice must be hidden plain text")
    require(" ".join("".join(notice["text"]).split()) == normalized_license,
            "ECDICT license notice differs from the complete source license")
    return True


def note_field_changes(old: dict[int, tuple[str, ...]], new: dict[int, tuple[str, ...]]) -> dict:
    """Describe content changes separately from stable identity/schema checks."""
    require(old.keys() == new.keys(), "cannot compare fields for different note identities")
    changed = {name: [] for name in FIELD_NAMES}
    for note_id in sorted(old):
        require(len(old[note_id]) == len(new[note_id]) == len(FIELD_NAMES), "note field count changed")
        for index, name in enumerate(FIELD_NAMES):
            if old[note_id][index] != new[note_id][index]:
                changed[name].append(new[note_id][0])
    return {
        "note_fields_changed": {name: {"notes": len(words), "sample_words": words[:10]}
                                for name, words in changed.items() if words},
        "note_fields_unchanged": [name for name, words in changed.items() if not words],
    }


def verify_dictionary_media(collection, note_ids: set[int], card_ids: set[int],
                            packaged_media: set[str], *, expected_ecdict_license: str | None = None) -> dict:
    """Use Anki's real media scanner on the literal imported field contents."""
    references: dict[str, set[str]] = {}
    scanned_all: set[str] = set()
    notes_with_dictionary_audio: set[int] = set()
    wordbook_fallbacks: dict[int, str] = {}
    ecdict_fallbacks: dict[int, str] = {}
    ecdict_metadata_notes: set[int] = set()
    for note_id in sorted(note_ids):
        note = collection.get_note(note_id)
        note_type = note.note_type()
        require(note_type is not None, f"note has no model: {note_id}")
        if verify_ecdict_metadata(note.fields, expected_ecdict_license):
            ecdict_metadata_notes.add(note_id)
        for field in note.fields:
            scanned = set(collection.media.files_in_str(note_type["id"], field))
            scanned_all.update(scanned)
            markup = card_markup(field)
            if any(tag == "div" and attributes.get("data-dictionary") == "wordbook"
                   and "dictionary-definition" in (attributes.get("class") or "").split()
                   for tag, attributes in markup.elements):
                wordbook_fallbacks[note_id] = note.fields[0]
            if any(tag == "div" and attributes.get("data-dictionary") == "ecdict"
                   and "dictionary-definition" in (attributes.get("class") or "").split()
                   for tag, attributes in markup.elements):
                require(note_id in ecdict_metadata_notes, "ECDICT definition fallback lacks verified metadata")
                ecdict_fallbacks[note_id] = note.fields[0]
            source_refs = dictionary_audio_references(markup)
            if not source_refs:
                continue
            notes_with_dictionary_audio.add(note_id)
            for source, names in source_refs.items():
                require(names <= scanned,
                        f"Anki scanner misses {source} audio on note {note_id}: {sorted(names - scanned)}")
                require(names <= packaged_media,
                        f"dictionary audio is absent from new APKG: {sorted(names - packaged_media)}")
                references.setdefault(source, set()).update(names)
        if any(source in field for field in note.fields
               for source in ('data-dictionary-source=', 'class="dictionary-audio-source"')):
            require(not any(endpoint in field for field in note.fields
                            for endpoint in ("localhost:8770", "127.0.0.1:8770")),
                    f"dictionary note depends on the localhost API: {note_id}")
    if references:
        require(set(references) == {"oxford", "webster"}, "both dictionary audio sets must be present")
        for card_id in sorted(card_ids):
            card = collection.get_card(card_id)
            require(dictionary_card_controls(
                card_markup(card.question()), card_markup(card.answer()),
                allow_wordbook_fallback=getattr(card, "nid", None) in wordbook_fallbacks,
                allow_ecdict_fallback=getattr(card, "nid", None) in ecdict_fallbacks),
                    f"dictionary controls or exact Oxford definition marker missing: card {card_id}")
    require(packaged_media <= scanned_all,
            f"new APKG media not referenced in Anki fields: {sorted(packaged_media - scanned_all)[:10]}")
    media_check = collection.media.check()
    require(not media_check.missing, f"Anki reports missing media: {list(media_check.missing)[:10]}")
    unused_new = set(media_check.unused) & packaged_media
    require(not unused_new, f"new APKG media unused by Anki: {sorted(unused_new)[:10]}")
    return {
        "dictionary_audio_note_count": len(notes_with_dictionary_audio),
        "dictionary_wordbook_definition_fallback_words": sorted(wordbook_fallbacks.values()),
        "dictionary_ecdict_definition_fallback_words": sorted(ecdict_fallbacks.values()),
        "ecdict_exam_tag_source_note_count": len(ecdict_metadata_notes),
        "ecdict_hidden_complete_mit_notice_count": len(ecdict_metadata_notes),
        "dictionary_audio_references_by_source": {source: len(names) for source, names in references.items()},
        "anki_media_scanner_recognizes_dictionary_audio": bool(references),
        "all_new_package_media_referenced_in_anki_fields": True,
        "anki_media_missing": [],
        "new_package_unused_media": [],
        "unused_old_media_count": len(media_check.unused),
    }


def write_report(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".anki-import-",
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
    parser.add_argument("--old-package", required=True, help="previous APKG to import first")
    parser.add_argument("--package", required=True, help="updated APKG to import second")
    parser.add_argument(
        "--report", help="JSON result under project output/; defaults to output/anki-import-verification.json"
    )
    parser.add_argument(
        "--anki-packages", default=str(DEFAULT_ANKI_PACKAGES),
        help="installed Anki app_packages directory containing anki and its native backend",
    )
    parser.add_argument(
        "--ecdict-license", default=str(DEFAULT_ECDICT_LICENSE),
        help="read-only original ECDICT LICENSE used when imported fields declare ECDICT",
    )
    args = parser.parse_args()

    old_package = project_path(args.old_package)
    package = project_path(args.package)
    report_path = project_path(args.report) if args.report else OUTPUT / "anki-import-verification.json"
    anki_packages = Path(args.anki_packages).expanduser().resolve(strict=True)
    for path in (old_package, package):
        require(path.is_file() and path.suffix.lower() == ".apkg", f"APKG not found: {path}")
    require(old_package != package, "old and updated packages must be different files")
    require(
        report_path.is_relative_to(OUTPUT) and report_path.suffix.lower() == ".json",
        f"report must be a JSON file under {OUTPUT}",
    )
    require((anki_packages / "anki" / "_rsbridge.so").is_file(), "installed Anki native backend not found")
    old_package_digest = file_sha256(old_package)
    package_digest = file_sha256(package)
    old_media = package_media_hashes(old_package)
    new_media = package_media_hashes(package)
    expected_media = merge_package_media(old_media, new_media)
    ecdict_license_path = project_path(args.ecdict_license)
    expected_ecdict_license = (ecdict_license_path.read_text(encoding="utf-8")
                              if ecdict_license_path.is_file() else None)
    ecdict_license_digest = (file_sha256(ecdict_license_path) if expected_ecdict_license is not None else None)

    sys.path.insert(0, str(anki_packages))
    import anki
    from anki.collection import Collection
    from anki.import_export_pb2 import ImportAnkiPackageRequest

    require(Path(next(iter(anki.__path__))).resolve() == anki_packages / "anki", "wrong Anki package imported")
    backend_version = metadata.version("anki")
    OUTPUT.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="anki-import-verify-", dir=OUTPUT) as folder:
        collection_path = Path(folder) / "collection.anki2"
        collection = Collection(str(collection_path))
        try:
            require(collection.note_count() == collection.card_count() == 0, "temporary collection is not empty")
            collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(old_package)))
            note_ids = set(collection.find_notes(""))
            card_ids = set(collection.find_cards(""))
            require(len(note_ids) == len(card_ids) == 1960, "old package did not import 1960 notes/cards")
            require(mp3_count(collection) == sum(name.endswith(".mp3") for name in old_media),
                    "old package MP3 count differs from its media manifest")
            verify_imported_media(Path(collection.media.dir()), old_media)
            note_guids = {note_id: collection.get_note(note_id).guid for note_id in note_ids}
            old_note_fields = {note_id: tuple(collection.get_note(note_id).fields) for note_id in note_ids}
            note_type_ids = {note_id: collection.get_note(note_id).note_type()["id"] for note_id in note_ids}
            model_shapes = {
                model_id: (model["name"], tuple(field["name"] for field in model["flds"]))
                for model_id in set(note_type_ids.values())
                if (model := collection.models.get(model_id)) is not None
            }
            require(all(fields == FIELD_NAMES for _, fields in model_shapes.values()),
                    "old package model field names/order differ from the ten-field contract")
            card_deck_ids = {card_id: collection.get_card(card_id).did for card_id in card_ids}
            deck_names = {deck_id: collection.decks.get(deck_id)["name"]
                          for deck_id in set(card_deck_ids.values())}

            progress_card_id = min(card_ids)
            progress_card = collection.get_card(progress_card_id)
            progress_card.type = 2
            progress_card.queue = 2
            progress_card.ivl = 7
            progress_card.due = collection.sched.today + 7
            progress_card.reps = 4
            collection.update_card(progress_card)
            schedule = (
                progress_card.type, progress_card.queue, progress_card.ivl,
                progress_card.due, progress_card.reps,
            )

            collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(package)))
            require(set(collection.find_notes("")) == note_ids, "note IDs changed or duplicated")
            require(set(collection.find_cards("")) == card_ids, "card IDs changed or duplicated")
            require(
                all(collection.get_note(note_id).guid == guid for note_id, guid in note_guids.items()),
                "note GUIDs changed",
            )
            require(all(collection.get_note(note_id).note_type()["id"] == model_id
                        for note_id, model_id in note_type_ids.items()), "note model IDs changed")
            require(all(
                (model["name"], tuple(field["name"] for field in model["flds"])) == shape
                for model_id, shape in model_shapes.items()
                if (model := collection.models.get(model_id)) is not None
            ), "model name or ten-field order changed")
            require(all(collection.get_card(card_id).did == deck_id
                        for card_id, deck_id in card_deck_ids.items()), "card deck memberships changed")
            require(all(collection.decks.get(deck_id)["name"] == name
                        for deck_id, name in deck_names.items()), "deck names changed")
            progress_card = collection.get_card(progress_card_id)
            require(
                (
                    progress_card.type, progress_card.queue, progress_card.ivl,
                    progress_card.due, progress_card.reps,
                ) == schedule,
                "sample review progress changed",
            )
            require(mp3_count(collection) == sum(name.endswith(".mp3") for name in expected_media),
                    "updated MP3 count differs from the union of old/new package media manifests")
            verify_imported_media(Path(collection.media.dir()), expected_media)
            media_verification = verify_dictionary_media(
                collection, note_ids, card_ids, set(new_media), expected_ecdict_license=expected_ecdict_license)
            field_verification = note_field_changes(
                old_note_fields, {note_id: tuple(collection.get_note(note_id).fields) for note_id in note_ids})
            feature_card_id = card_rendering_sample(collection, card_ids)
            require(file_sha256(old_package) == old_package_digest, "old APKG changed during verification")
            require(file_sha256(package) == package_digest, "updated APKG changed during verification")
            license_verification = {}
            if media_verification["ecdict_hidden_complete_mit_notice_count"]:
                require(file_sha256(ecdict_license_path) == ecdict_license_digest,
                        "ECDICT source LICENSE changed during verification")
                license_verification = {"ecdict_source_license_path": str(ecdict_license_path),
                                        "ecdict_source_license_sha256": ecdict_license_digest}
            result = {
                "anki_backend_version": backend_version,
                "old_package": str(old_package),
                "old_package_sha256": old_package_digest,
                "package": str(package),
                "package_sha256": package_digest,
                "notes": collection.note_count(),
                "cards": collection.card_count(),
                "mp3": mp3_count(collection),
                "old_package_media": len(old_media),
                "new_package_media": len(new_media),
                "expected_imported_media_union": len(expected_media),
                "all_packaged_media_hashes_match_imported": True,
                "stable_note_card_ids_and_guids": True,
                "stable_model_id_name_and_ten_field_order": True,
                "stable_deck_names_and_card_memberships": True,
                "sample_review_schedule_preserved": True,
                "rendered_feature_card_id": feature_card_id,
                "word_and_eudic_link_script": True,
                "question_excludes_answer_markup": True,
                "answer_has_definition_source_jump_reader_and_target_highlight_markup": True,
                "rendered_feature_card_has_safe_source_links_and_reader_choices": True,
                **media_verification,
                **field_verification,
                **license_verification,
                "collection_scope": "temporary directory under project output",
                "anki_gui_rendering": "NOT_RUN",
                "anki_user_profile_import": "NOT_RUN",
            }
        finally:
            collection.close()

    write_report(report_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
