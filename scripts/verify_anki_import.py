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

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
DEFAULT_ANKI_PACKAGES = Path("/Applications/Anki.app/Contents/Resources/app_packages")


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


class CardMarkup(HTMLParser):
    """Record actual HTML elements, ignoring selector names inside CSS or JS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tag_classes: set[tuple[str, str]] = set()
        self.tag_ids: set[tuple[str, str]] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for name in (attributes.get("class") or "").split():
            self.tag_classes.add((tag, name))
        if element_id := attributes.get("id"):
            self.tag_ids.add((tag, element_id))


def card_markup(content: str) -> CardMarkup:
    markup = CardMarkup()
    markup.feed(content)
    markup.close()
    return markup


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
            and ("mark", "target-word") not in front.tag_classes
            and ("hr", "answer") in back.tag_ids
            and ("section", "primary-definition") in back.tag_classes
            and ("mark", "target-word") in back.tag_classes
            and ("button", "sentence-play") in back.tag_classes
        ):
            return card_id
    raise RuntimeError("no card renders the expected front/back lookup, answer, play control and highlighting markup")


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
            require(mp3_count(collection) == 1960, "old package did not import 1960 MP3 files")
            note_guids = {note_id: collection.get_note(note_id).guid for note_id in note_ids}

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
            progress_card = collection.get_card(progress_card_id)
            require(
                (
                    progress_card.type, progress_card.queue, progress_card.ivl,
                    progress_card.due, progress_card.reps,
                ) == schedule,
                "sample review progress changed",
            )
            require(mp3_count(collection) == 1960, "updated package media count differs from 1960")
            feature_card_id = card_rendering_sample(collection, card_ids)
            result = {
                "anki_backend_version": backend_version,
                "old_package": str(old_package),
                "old_package_sha256": file_sha256(old_package),
                "package": str(package),
                "package_sha256": file_sha256(package),
                "notes": collection.note_count(),
                "cards": collection.card_count(),
                "mp3": mp3_count(collection),
                "stable_note_card_ids_and_guids": True,
                "sample_review_schedule_preserved": True,
                "rendered_feature_card_id": feature_card_id,
                "word_and_eudic_link_script": True,
                "question_excludes_answer_markup": True,
                "answer_has_definition_play_control_and_target_highlight_markup": True,
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
