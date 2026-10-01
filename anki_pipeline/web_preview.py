"""Build a complete, versioned static vocabulary library without database writes.

The outer HTML entry is replaced only after an immutable version is complete.
Previous versions remain available to readers that already loaded their catalog.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from urllib.parse import quote

from . import packaging


_UI_TEMPLATE_DIR = Path(__file__).with_name("templates")
_UI_FILES = ("library-preview.html", "library-preview.css", "library-preview.js")
_RENDERER_TEMPLATES = ("front.html", "back.html", "style.css", "script.js", "countdown.js", "etymology-card.css", "etymology-card.js", "card-chunks.js", "card-chunks.css")
_CATALOG_SCHEMA = "anki-web-catalog.v1"
_MANIFEST_SCHEMA = "anki-web-preview-manifest.v1"
_GENERATOR = "anki_pipeline.web_preview"


@dataclass(frozen=True)
class _PreparedCard:
    source: dict[str, Any]
    card_id: str
    filename: str
    audio_filename: str
    example_count: int
    rendered: dict[str, Any]


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def _checksum(content: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def _file_checksum(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return {"sha256": digest.hexdigest(), "bytes": size}


def _card_filename(card_id: str) -> str:
    return hashlib.sha256(card_id.encode("utf-8")).hexdigest() + ".html"


def _reject_symlinks(path: Path) -> None:
    # Inspect the original path rather than resolve() and silently follow links.
    for component in (path, *path.parents):
        if component.is_symlink():
            # macOS exposes its standard temporary directories through these
            # operating-system aliases. They are not library target links.
            if (sys.platform == "darwin" and component in {Path("/var"), Path("/tmp")}
                    and component.resolve() == Path("/private") / component.name):
                continue
            raise ValueError(f"web preview target must not contain a symlink: {component}")


def _validate_target(output_path: Path) -> None:
    _reject_symlinks(output_path)
    _reject_symlinks(output_path.parent / "web-preview")
    for ancestor in output_path.parents:
        marker = ancestor / "manifest.json"
        if marker.is_symlink() or not marker.is_file():
            continue
        try:
            manifest = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if (isinstance(manifest, dict) and manifest.get("schema") == _MANIFEST_SCHEMA
                and manifest.get("generator") == _GENERATOR):
            raise ValueError("output_path must not be inside an immutable web preview version")
    if output_path.exists() and not output_path.is_file():
        raise ValueError("web preview entry already exists and is not a regular file")
    for directory in (output_path.parent, output_path.parent / "web-preview"):
        if directory.exists() and not directory.is_dir():
            raise ValueError(f"web preview directory is not a directory: {directory}")


def _source_checksums() -> dict[str, dict[str, Any]]:
    """Fingerprint renderer code as well as every template that it consumes."""
    package_dir = Path(__file__).parent
    sources = {f"python/{name}": package_dir / name for name in
               ("web_preview.py", "packaging.py", "presentation.py", "forms.py", "text.py", "exam_frequency.py", "etymology.py", "translation_alignment.py", "occurrence_exclusions.py", "reading_completion.py", "sentence_insertion.py", "option_context.py", "option_translation.py", "source_paths.py", "exam_library.py")}
    sources.update({f"renderer/{name}": packaging._TEMPLATE_DIR / name
                    for name in _RENDERER_TEMPLATES})
    return {label: _file_checksum(path) for label, path in sorted(sources.items())}


def _render_card(card: dict[str, Any], max_examples: int) -> bytes:
    page = packaging.render_preview(card, audio_dir=None, max_examples=max_examples)
    if "local_dictionary" in card:
        for source, recordings in card["local_dictionary"]["audio"].items():
            for recording in recordings:
                filename = recording["filename"]
                literal = (f'<audio preload="none" hidden data-dictionary-source="{source}" '
                           f'src="{html.escape(filename, quote=True)}">')
                encoded = (f'<audio preload="none" hidden data-dictionary-source="{source}" '
                           f'src="{quote(filename, safe="")}">')
                if literal not in page:
                    raise ValueError("dictionary renderer no longer exposes the expected audio reference")
                page = page.replace(literal, encoded)
        return page.encode("utf-8")
    filename = packaging._plain(card["audio_filename"], "audio_filename")
    if filename:
        # A valid filesystem basename may still contain a URL fragment, query,
        # percent sign, space or non-ASCII text. Encode only the media reference;
        # preserve every other byte of the existing card renderer.
        literal = f'<audio preload="none" hidden src="{html.escape(filename, quote=True)}">'
        encoded = f'<audio preload="none" hidden src="{quote(filename, safe="")}">'
        if literal not in page:
            raise ValueError("card renderer no longer exposes the expected audio reference")
        page = page.replace(literal, encoded)
    return page.encode("utf-8")


def _write_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _validate_version(directory: Path, manifest: dict[str, Any]) -> None:
    _reject_symlinks(directory)
    if not directory.is_dir():
        raise ValueError("existing web preview version is not a directory")
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("web preview manifest must not be a symlink")
    if not manifest_path.is_file():
        raise ValueError("existing web preview version has no owned manifest")
    try:
        actual = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError("existing web preview version has an invalid manifest") from error
    if actual != manifest or actual.get("schema") != _MANIFEST_SCHEMA:
        raise ValueError("existing web preview version manifest does not match its inputs")
    expected_files = {*manifest["files"], "manifest.json"}
    actual_files = set()
    for path in directory.rglob("*"):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise ValueError(f"web preview version contains a symlink: {relative}")
        if path.is_dir():
            if relative not in {"cards", "assets"}:
                raise ValueError(f"web preview version contains an unexpected directory: {relative}")
        elif path.is_file():
            actual_files.add(relative)
        else:
            raise ValueError(f"web preview version contains a nonregular file: {relative}")
    if actual_files != expected_files:
        raise ValueError("web preview version file inventory does not match its manifest")
    for relative, checksum in manifest["files"].items():
        if _file_checksum(directory / relative) != checksum:
            raise ValueError(f"web preview version checksum mismatch: {relative}")


def _replace_entry(output_path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{output_path.stem}-", suffix=".tmp",
                                         dir=output_path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_target(output_path)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_web_preview(cards: list[dict], audio_dir: Path, output_path: Path, *,
                      deck_name: str, max_examples: int = 0,
                      before_publish: Callable[[], None] | None = None) -> dict:
    """Publish a complete local static library and return its reconciled counts.

    All supplied examples are included by default. A positive explicit limit is
    reflected in both catalog counts and card pages. Audio remains in external
    MP3 files adjacent to the pages, and every version is preserved. No Anki
    package, source card, database, or previous version is modified.

    ``catalog_url`` and ``assets_directory`` are relative to ``output_path``;
    the latter includes a trailing slash. ``counts`` contains cards, decks and
    examples, with scalar ``card_count``, ``deck_count`` and ``example_count``
    aliases for command-line reports.

    ``before_publish``, when supplied, runs after a complete new or reused
    version has been validated and before replacing the outer HTML entry.
    An exception preserves the old entry and leaves the complete version
    available for a later retry. Entries cannot be written inside an existing
    version identified by this generator's manifest.
    """
    if not isinstance(cards, list) or not cards:
        raise ValueError("cards must be a nonempty list")
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or max_examples < 0:
        raise ValueError("max_examples must be a nonnegative integer")
    if before_publish is not None and not callable(before_publish):
        raise ValueError("before_publish must be callable or None")
    deck_name = packaging._plain(deck_name, "deck_name")
    if not deck_name:
        raise ValueError("deck_name must not be blank")
    requested_path = Path(output_path)
    if not requested_path.is_absolute():
        requested_path = Path.cwd() / requested_path
    _reject_symlinks(requested_path)
    output_path = Path(os.path.abspath(requested_path))
    if output_path.suffix.lower() not in {".html", ".htm"}:
        raise ValueError("output_path must end with .html or .htm")
    _validate_target(output_path)
    audio_dir = Path(audio_dir)

    # Snapshot caller data so the digest and all rendered files describe the
    # same source. Hashes and media validation precede any output directory.
    try:
        source_cards = json.loads(_json_bytes(cards))
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("cards must contain JSON-compatible source data") from error
    dependencies = _source_checksums()
    ui = {name: (_UI_TEMPLATE_DIR / name).read_bytes() for name in _UI_FILES}
    shell_template = ui["library-preview.html"].decode("utf-8")
    if "__CATALOG_URL__" not in shell_template or "__ASSET_BASE__" not in shell_template:
        raise ValueError("library preview HTML is missing its catalog or asset placeholder")
    for name in _UI_FILES:
        ui[name].decode("utf-8")

    prepared = []
    seen_ids = set()
    seen_filenames = set()
    media: dict[str, tuple[Path, dict[str, Any]]] = {}
    for source in source_cards:
        # Reuse the original validator, including fields beyond a requested
        # example limit. Avoid embedding or loading audio into the card HTML.
        full_page = _render_card(source, 0)
        card_id = packaging._plain(source["id"], "id")
        if card_id in seen_ids:
            raise ValueError(f"duplicate card id: {card_id}")
        seen_ids.add(card_id)
        filename = _card_filename(card_id)
        if filename in seen_filenames:
            raise ValueError(f"card filename hash collision: {card_id}")
        seen_filenames.add(filename)
        audio_files = packaging._card_audio_files(source, audio_dir)
        audio_filename = next(iter(audio_files), "")
        for name, audio_path in audio_files.items():
            if audio_path is not None and name not in media:
                media[name] = (audio_path, _file_checksum(audio_path))
        packaging._lesson_deck_name(deck_name, source)
        selected_count = len(source["examples"]) if max_examples == 0 else min(
            len(source["examples"]), max_examples)
        page = full_page if max_examples == 0 else _render_card(source, max_examples)
        prepared.append(_PreparedCard(source, card_id, filename, audio_filename,
                                      selected_count, _checksum(page)))
    prepared.sort(key=lambda item: packaging._sort_key(item.source))
    if _source_checksums() != dependencies:
        raise ValueError("card renderer changed during web preview validation; retry the build")

    input_digest = hashlib.sha256(_json_bytes({
        "schema": _MANIFEST_SCHEMA, "cards": [item.source for item in prepared],
        "deck_name": deck_name, "max_examples": max_examples,
        "renderer": dependencies, "ui": {name: _checksum(ui[name]) for name in _UI_FILES},
        "media": {name: checksum for name, (_, checksum) in sorted(media.items())},
    })).hexdigest()
    relative_base = f"web-preview/{input_digest}"
    catalog_url = f"{relative_base}/catalog.json"
    assets_directory = f"{relative_base}/assets/"
    decks: dict[str, dict[str, Any]] = {}
    catalog_cards = []
    for item in prepared:
        source = item.source
        name = packaging._lesson_deck_name(deck_name, source)
        deck_id = str(packaging._stable_numeric_id("deck", name))
        unit = packaging._plain(source["sheet"], "sheet")
        lesson = packaging._plain(source["lesson"], "lesson")
        if name not in decks:
            decks[name] = {"id": deck_id, "name": name, "unit": unit, "lesson": lesson,
                           "count": 0, "cardIds": []}
        decks[name]["count"] += 1
        decks[name]["cardIds"].append(item.card_id)
        definitions = dict.fromkeys(packaging._plain(source[key], key) for key in
                                    ("definition", "simple_definition"))
        if "local_dictionary" in source:
            definitions = dict.fromkeys(
                packaging._plain(sense["pos"], "sense pos") + " "
                + packaging._plain(sense["text"], "sense text")
                for sense in source["local_dictionary"]["senses"])
            if source["local_dictionary"].get("definition_source") in {"wordbook", "ecdict"}:
                definitions = {packaging._plain(
                    source["local_dictionary"]["definition_fallback"], "fallback definition"): None}
        catalog_cards.append({
            "id": item.card_id, "word": packaging._plain(source["word"], "word"),
            "deckId": deck_id, "deckName": name, "unit": unit, "lesson": lesson,
            "position": packaging._plain(source["position"], "position"),
            "definition": "\n".join(value for value in definitions if value),
            "exampleCount": item.example_count,
            "previewUrl": f"{relative_base}/cards/{item.filename}",
        })
    counts = {"cards": len(prepared), "decks": len(decks),
              "examples": sum(item.example_count for item in prepared)}
    catalog = {"schema": _CATALOG_SCHEMA, "deckName": deck_name, "defaultReader": "latex",
               "counts": counts, "decks": list(decks.values()), "cards": catalog_cards}
    catalog_bytes = _json_bytes(catalog)
    files = {"catalog.json": _checksum(catalog_bytes)}
    files.update({f"assets/{name}": _checksum(ui[name])
                  for name in ("library-preview.css", "library-preview.js")})
    files.update({f"cards/{item.filename}": item.rendered for item in prepared})
    files.update({f"cards/{name}": checksum for name, (_, checksum) in media.items()})
    manifest = {"schema": _MANIFEST_SCHEMA, "generator": _GENERATOR,
                "input_digest": input_digest, "counts": counts, "media_count": len(media),
                "files": files}
    shell = shell_template.replace("__CATALOG_URL__", catalog_url).replace(
        "__ASSET_BASE__", assets_directory).encode("utf-8")
    version_root = output_path.parent / "web-preview"
    version = version_root / input_digest
    _reject_symlinks(version)
    reused_version = version.exists()
    staging = None
    try:
        if reused_version:
            _validate_version(version, manifest)
        else:
            _validate_target(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            version_root.mkdir(exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".web-preview-", dir=version_root))
            (staging / "cards").mkdir()
            (staging / "assets").mkdir()
            _write_file(staging / "catalog.json", catalog_bytes)
            for name in ("library-preview.css", "library-preview.js"):
                _write_file(staging / "assets" / name, ui[name])
            for item in prepared:
                page = _render_card(item.source, max_examples)
                if _checksum(page) != item.rendered:
                    raise ValueError("card renderer changed during web preview build; retry the build")
                _write_file(staging / "cards" / item.filename, page)
            for name, (audio_path, expected) in media.items():
                destination = staging / "cards" / name
                shutil.copyfile(audio_path, destination)
                if _file_checksum(destination) != expected:
                    raise ValueError(f"audio changed during web preview build: {name}")
            if _source_checksums() != dependencies:
                raise ValueError("card renderer changed during web preview build; retry the build")
            _write_file(staging / "manifest.json", _json_bytes(manifest))
            _validate_version(staging, manifest)
            _validate_target(output_path)
            _reject_symlinks(version)
            if version.exists():
                # Another identical build may have completed in the meantime.
                _validate_version(version, manifest)
                reused_version = True
            else:
                try:
                    os.rename(staging, version)
                except OSError:
                    if not version.exists():
                        raise
                    _validate_version(version, manifest)
                    reused_version = True
                else:
                    staging = None
        if before_publish is not None:
            before_publish()
        _replace_entry(output_path, shell)
    finally:
        if staging is not None:
            shutil.rmtree(staging)
    return {
        "output_path": str(output_path), "counts": counts,
        "card_count": counts["cards"], "deck_count": counts["decks"],
        "example_count": counts["examples"], "audio_count": len(media),
        "cards_without_audio": sum(not item.audio_filename for item in prepared),
        "deck_ids": {name: int(deck["id"]) for name, deck in decks.items()},
        "catalog_url": catalog_url, "assets_directory": assets_directory,
        "input_digest": input_digest, "version_directory": str(version),
        "manifest_path": str(version / "manifest.json"), "reused_version": reused_version,
    }
