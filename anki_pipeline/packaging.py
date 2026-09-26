"""Build a local Anki package from validated vocabulary card dictionaries.

The model name/ID, field order, and GUID namespace are an import contract. A
new model version or a change to source card IDs may create duplicate notes on
re-import; migrate an existing Anki collection deliberately before changing
them. ``Note`` is an editable user field. Anki's import update settings decide
whether a later import overwrites edits to that field.
"""

from __future__ import annotations

import hashlib
import base64
import html
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import genanki


_TEMPLATE_DIR = Path(__file__).with_name("templates")
_MODEL_NAME = "考研英语词汇 v1"
_FIELD_NAMES = (
    "Word", "Phonetic", "Definition", "SimpleDefinition", "Level",
    "WordForms", "Audio", "Examples", "Meta", "Note",
)
_REQUIRED_CARD_KEYS = {
    "id", "sheet", "lesson", "position", "word", "phonetic", "definition",
    "simple_definition", "level", "word_forms", "audio_filename", "examples",
}
_CONDITION = re.compile(r"{{#([A-Za-z]+)}}(.*?){{/\1}}", re.DOTALL)
_PLACEHOLDER = re.compile(r"{{([A-Za-z]+)}}")
_NATURAL_PART = re.compile(r"(\d+)")


def _template(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _stable_numeric_id(namespace: str, name: str) -> int:
    digest = hashlib.sha256(f"anki-rebuild/{namespace}/{name}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 2_147_483_646 + 1


def _plain(value: Any, label: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{label} must be text or an integer")
    result = str(value)
    if "\x00" in result:
        raise ValueError(f"{label} contains a null character")
    return result.strip()


def _escaped(value: Any, label: str) -> str:
    return html.escape(_plain(value, label), quote=True).replace("\n", "<br>")


def _natural_key(value: str) -> tuple[tuple[int, Any], ...]:
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in _NATURAL_PART.split(value))


def _audio_file(filename: str, audio_dir: Path | None) -> Path | None:
    if not filename:
        return None
    if (filename in {".", ".."} or Path(filename).name != filename
            or "\\" in filename or any(ch in filename for ch in "[]<>&")
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in filename)):
        raise ValueError(f"unsafe audio filename: {filename!r}")
    if Path(filename).suffix.lower() != ".mp3":
        raise ValueError(f"audio file must be an .mp3: {filename!r}")
    if audio_dir is None:
        return None
    root = Path(audio_dir).resolve(strict=True)
    candidate = root / filename
    if not candidate.exists():
        raise FileNotFoundError(f"audio file is missing: {candidate}")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError(f"audio file escapes its directory or is not a file: {filename!r}")
    if resolved.stat().st_size == 0:
        raise ValueError(f"audio file is empty: {filename!r}")
    if resolved.stat().st_size > 5 * 1024 * 1024:
        raise ValueError(f"audio file exceeds 5 MiB limit: {filename!r}")
    return resolved


def _fields(card: dict[str, Any], audio_dir: Path | None, max_examples: int,
            *, preview: bool = False) -> tuple[dict[str, str], Path | None, str]:
    if not isinstance(card, dict):
        raise ValueError("each card must be a dictionary")
    missing = _REQUIRED_CARD_KEYS - card.keys()
    if missing:
        raise ValueError(f"card is missing fields: {', '.join(sorted(missing))}")
    card_id = _plain(card["id"], "id")
    if not card_id:
        raise ValueError("card id must not be blank")
    word = _plain(card["word"], "word")
    if not word:
        raise ValueError(f"card {card_id}: word must not be blank")
    examples = card["examples"]
    if not isinstance(examples, list):
        raise ValueError(f"card {card_id}: examples must be a list")
    filename = _plain(card["audio_filename"], "audio_filename")
    audio_path = _audio_file(filename, audio_dir)
    audio_field = ""
    if filename:
        if preview:
            reference = ("data:audio/mpeg;base64," + base64.b64encode(audio_path.read_bytes()).decode("ascii")) if audio_path else filename
            audio_field = (f'<audio controls preload="none" '
                           f'src="{html.escape(reference, quote=True)}"></audio>')
        else:
            audio_field = f"[sound:{filename}]"
    rendered_examples = []
    for index, example in enumerate(examples[:max_examples], start=1):
        if not isinstance(example, dict) or not {"text", "source", "translation"} <= example.keys():
            raise ValueError(f"card {card_id}: example {index} needs text, source, translation")
        text = _escaped(example["text"], "example text")
        source = _escaped(example["source"], "example source")
        translation = _escaped(example["translation"], "example translation")
        rendered_examples.append(
            '<li><span class="example-text">' + text + '</span>'
            + (f'<span class="example-translation">{translation}</span>' if translation else "")
            + (f'<span class="example-source">{source}</span>' if source else "")
            + '</li>'
        )
    meta = " · ".join(_escaped(card[key], key) for key in ("sheet", "lesson", "position")
                      if _plain(card[key], key))
    fields = {
        "Word": _escaped(word, "word"),
        "Phonetic": _escaped(card["phonetic"], "phonetic"),
        "Definition": _escaped(card["definition"], "definition"),
        "SimpleDefinition": _escaped(card["simple_definition"], "simple_definition"),
        "Level": _escaped(card["level"], "level"),
        "WordForms": _escaped(card["word_forms"], "word_forms"),
        "Audio": audio_field,
        "Examples": "".join(rendered_examples),
        "Meta": meta,
        "Note": _escaped(card.get("note", ""), "note"),
    }
    return fields, audio_path, card_id


def _sort_key(card: dict[str, Any]) -> tuple[Any, ...]:
    return (*(_natural_key(_plain(card[key], key)) for key in ("sheet", "lesson", "position")),
            _natural_key(_plain(card["id"], "id")), _natural_key(_plain(card["word"], "word")))


def _lesson_deck_name(root_name: str, card: dict[str, Any]) -> str:
    sheet = _plain(card["sheet"], "sheet")
    lesson = _plain(card["lesson"], "lesson")
    if not sheet or not lesson:
        raise ValueError("sheet and lesson must not be blank")
    if "::" in sheet or "::" in lesson:
        raise ValueError("sheet and lesson must not contain the Anki deck separator '::'")
    # Preserve source wording while making numbered units/lessons sort naturally
    # in Anki's alphabetical deck list.
    sheet = re.sub(r"\d+", lambda match: f"{int(match.group()):02d}", sheet, count=1)
    lesson_number = re.fullmatch(r"(?i)(?:lesson\s*)?(\d+)", lesson)
    if lesson_number:
        lesson = f"Lesson {int(lesson_number.group(1)):02d}"
    return f"{root_name}::{sheet}::{lesson}"


def _render_template(source: str, fields: dict[str, str]) -> str:
    rendered = _CONDITION.sub(lambda match: match.group(2) if fields.get(match.group(1)) else "", source)
    return _PLACEHOLDER.sub(lambda match: fields.get(match.group(1), ""), rendered)


def build_package(cards: list[dict], audio_dir: Path, output_path: Path, *,
                  deck_name: str = "考研英语", max_examples: int = 5) -> dict:
    """Write one .apkg atomically and return export counts and stable IDs.

    A blank audio filename means the source has no recording: export the card
    without a sound tag and count it in ``cards_without_audio``. A nonblank
    filename must name an existing regular file directly inside ``audio_dir``.
    """
    if not isinstance(cards, list) or not cards:
        raise ValueError("cards must be a nonempty list")
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or max_examples < 0:
        raise ValueError("max_examples must be a nonnegative integer")
    deck_name = _plain(deck_name, "deck_name")
    if not deck_name:
        raise ValueError("deck_name must not be blank")
    output_path = Path(output_path)
    if output_path.suffix.lower() != ".apkg":
        raise ValueError("output_path must end with .apkg")
    audio_dir = Path(audio_dir)

    prepared = []
    seen_ids = set()
    media = {}
    for card in cards:
        fields, audio_path, card_id = _fields(card, audio_dir, max_examples)
        if card_id in seen_ids:
            raise ValueError(f"duplicate card id: {card_id}")
        seen_ids.add(card_id)
        if audio_path is not None:
            media[audio_path.name] = audio_path
        prepared.append((card, fields, card_id))

    model_id = _stable_numeric_id("model", _MODEL_NAME)
    script = f"<script>\n{_template('script.js')}\n</script>"
    model = genanki.Model(
        model_id, _MODEL_NAME,
        fields=[{"name": name} for name in _FIELD_NAMES],
        templates=[{"name": "Vocabulary", "qfmt": _template("front.html") + script,
                    "afmt": _template("back.html") + script}],
        css=_template("style.css"),
    )
    decks: dict[str, genanki.Deck] = {}
    for due, (source_card, fields, card_id) in enumerate(
            sorted(prepared, key=lambda item: _sort_key(item[0])), start=1):
        full_deck_name = _lesson_deck_name(deck_name, source_card)
        if full_deck_name not in decks:
            decks[full_deck_name] = genanki.Deck(_stable_numeric_id("deck", full_deck_name),
                                                full_deck_name)
        note = genanki.Note(model=model, fields=[fields[name] for name in _FIELD_NAMES],
                            guid=genanki.guid_for("anki-rebuild-card-v1", card_id), due=due)
        decks[full_deck_name].add_note(note)
    package = genanki.Package([decks[name] for name in sorted(decks, key=_natural_key)])
    package.media_files = [str(path) for _, path in sorted(media.items())]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{output_path.stem}-", suffix=".tmp.apkg",
                                         dir=output_path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        package.write_to_file(str(temp_path))
        os.replace(temp_path, output_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {
        "output_path": str(output_path),
        "deck_count": len(decks),
        "deck_ids": {name: decks[name].deck_id for name in sorted(decks, key=_natural_key)},
        "model_id": model_id,
        "card_count": len(prepared),
        "audio_count": len(media),
        "cards_without_audio": sum(not fields["Audio"] for _, fields, _ in prepared),
    }


def render_preview(card: dict, audio_dir: Path | None = None) -> str:
    """Return a self-contained browser preview of both sides of one card."""
    fields, _, _ = _fields(card, Path(audio_dir) if audio_dir is not None else None,
                            max_examples=5, preview=True)
    front = _render_template(_template("front.html"), fields)
    back = _render_template(_template("back.html"), {**fields, "FrontSide": front})
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Anki 卡片预览</title><style>' + _template("style.css") + '</style></head>'
        '<body><section aria-label="正面预览">' + front + '</section>'
        '<section aria-label="背面预览">' + back + '</section>'
        '<script>' + _template("script.js") + '</script></body></html>'
    )
