"""Validate reviewed sentence alignments and render safe Chinese highlights.

Offsets are half-open Unicode codepoint ranges into the *exact* supplied strings,
not UTF-16 code units, grapheme indices, normalized text, or escaped HTML. Payloads
use this JSON shape::

    {"schema": "codex-sentence-alignment.v1",
     "englishHash": "<lowercase SHA256 of UTF-8 English>",
     "translationHash": "<lowercase SHA256 of UTF-8 translation>",
     "alignments": [{"en": [4, 8], "zh": [[0, 2]],
                     "relation": "equivalent", "note": "optional explanation"}]}

An English range appears only once; its Chinese ranges may overlap or be reordered.
``implicit`` and ``untranslated`` entries have no Chinese ranges and require a
nonblank explanatory ``note``. Validation checks integrity and shape, not whether
the reviewed translation or semantic correspondence is linguistically correct.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import escape


__all__ = ["TranslationAlignmentError", "validate_translation_alignment",
           "render_aligned_translation"]

_SCHEMA = "codex-sentence-alignment.v1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PAYLOAD_FIELDS = frozenset({"schema", "englishHash", "translationHash", "alignments"})
_ENTRY_FIELDS = frozenset({"en", "zh", "relation"})
_RELATIONS = frozenset({"equivalent", "implicit", "untranslated"})
_Range = tuple[int, int]


class TranslationAlignmentError(ValueError):
    """An alignment cannot safely be applied to its current sentence strings."""


@dataclass(frozen=True)
class _Alignment:
    en: _Range
    zh: tuple[_Range, ...]
    relation: str


def _text_hash(text: str, field: str) -> str:
    if not isinstance(text, str):
        raise TranslationAlignmentError(f"{field} must be a string")
    if not text.strip():
        raise TranslationAlignmentError(f"{field} must not be blank")
    try:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise TranslationAlignmentError(f"{field} must contain valid UTF-8 Unicode") from exc


def _range(value: object, length: int, field: str, *, json_array: bool = True) -> _Range:
    allowed = isinstance(value, list) if json_array else isinstance(value, (list, tuple))
    if not allowed or len(value) != 2:
        raise TranslationAlignmentError(f"{field} must be a two-integer range")
    start, end = value
    # bool is an int subclass, but cannot be an offset in the JSON schema.
    if type(start) is not int or type(end) is not int:
        raise TranslationAlignmentError(f"{field} offsets must be integers")
    if not 0 <= start < end <= length:
        raise TranslationAlignmentError(f"{field} must satisfy 0 <= start < end <= text length")
    return start, end


def _validated_alignments(english: str, translation: str,
                          alignment_payload: Mapping[str, object]) -> tuple[_Alignment, ...]:
    hashes = {"englishHash": _text_hash(english, "english"),
              "translationHash": _text_hash(translation, "translation")}
    if not isinstance(alignment_payload, Mapping):
        raise TranslationAlignmentError("alignment_payload must be an object")
    if alignment_payload.keys() != _PAYLOAD_FIELDS:
        raise TranslationAlignmentError("alignment_payload must contain exactly schema, englishHash, "
                                        "translationHash and alignments")
    if alignment_payload["schema"] != _SCHEMA:
        raise TranslationAlignmentError(f"schema must be {_SCHEMA}")
    for field, actual in hashes.items():
        recorded = alignment_payload[field]
        if not isinstance(recorded, str) or not _HASH.fullmatch(recorded):
            raise TranslationAlignmentError(f"{field} must be a lowercase SHA256 hex string")
        if recorded != actual:
            raise TranslationAlignmentError(f"{field} is stale for the exact current text")

    items = alignment_payload["alignments"]
    if not isinstance(items, list):
        raise TranslationAlignmentError("alignments must be an array")
    validated: list[_Alignment] = []
    seen: set[_Range] = set()
    for index, item in enumerate(items):
        field = f"alignments[{index}]"
        if not isinstance(item, Mapping):
            raise TranslationAlignmentError(f"{field} must be an object")
        keys = item.keys()
        if not _ENTRY_FIELDS <= keys or not keys <= _ENTRY_FIELDS | {"note"}:
            raise TranslationAlignmentError(f"{field} must contain en, zh, relation and optional note")
        relation = item["relation"]
        if not isinstance(relation, str) or relation not in _RELATIONS:
            raise TranslationAlignmentError(f"{field}.relation is not supported")
        if "note" in item and not isinstance(item["note"], str):
            raise TranslationAlignmentError(f"{field}.note must be a string")
        en = _range(item["en"], len(english), f"{field}.en")
        if en in seen:
            raise TranslationAlignmentError(f"{field}.en is a duplicate English range")
        seen.add(en)
        chinese = item["zh"]
        if not isinstance(chinese, list):
            raise TranslationAlignmentError(f"{field}.zh must be an array of ranges")
        zh = tuple(_range(span, len(translation), f"{field}.zh[{position}]")
                   for position, span in enumerate(chinese))
        if relation == "equivalent":
            if not zh:
                raise TranslationAlignmentError(f"{field}.zh must not be empty for equivalent")
        else:
            if zh:
                raise TranslationAlignmentError(f"{field}.zh must be empty for {relation}")
            if not item.get("note", "").strip():
                raise TranslationAlignmentError(f"{field}.note must explain {relation}")
        validated.append(_Alignment(en, zh, relation))
    return tuple(validated)


def validate_translation_alignment(english: str, translation: str,
                                   alignment_payload: Mapping[str, object]) -> None:
    """Raise ``TranslationAlignmentError`` on malformed, stale, or unsafe data.

    The payload and supplied strings are never normalized or modified. Unknown
    fields and schemas are rejected so a future producer cannot silently change
    the interpretation of an offset. Successful validation returns ``None``.
    """
    _validated_alignments(english, translation, alignment_payload)


def _body_range(english: str) -> _Range:
    """Locate lexical content so sentence punctuation cannot evade the fallback rule."""
    start, end = len(english), 0
    for index, char in enumerate(english):
        if char.isalnum() or unicodedata.category(char).startswith("M"):
            start = min(start, index)
            end = index + 1
    return (start, end) if end else (0, len(english))


def _select_alignment(alignments: tuple[_Alignment, ...], matched: _Range,
                      body: _Range) -> _Alignment | None:
    exact = next((item for item in alignments if item.en == matched), None)
    if exact is not None:
        return exact
    candidates = [item for item in alignments
                  if item.en[0] <= matched[0] and matched[1] <= item.en[1]
                  and not (item.en[0] <= body[0] and body[1] <= item.en[1])]
    if not candidates:
        return None
    shortest = min(item.en[1] - item.en[0] for item in candidates)
    smallest = [item for item in candidates if item.en[1] - item.en[0] == shortest]
    if len(smallest) != 1:
        raise TranslationAlignmentError("ambiguous shortest alignment for matched_english_ranges")
    return smallest[0]


def _merge_ranges(ranges: Iterable[_Range]) -> list[_Range]:
    merged: list[_Range] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def render_aligned_translation(english: str, translation: str,
                               alignment_payload: Mapping[str, object],
                               matched_english_ranges: Iterable[_Range]) -> str:
    """Return escaped Chinese HTML with only its finest aligned spans highlighted.

    The caller must supply complete current target-word or target-phrase ranges
    from its English matcher; word/form and language-boundary decisions belong to
    that matcher. This function validates their offsets and the *entire* payload
    before rendering, including entries that are not selected.

    An exact English range wins over any containing phrase. Otherwise the unique
    shortest containing phrase wins, excluding whole-sentence fallback ranges.
    Implicit/untranslated or unmatched words have no forced Chinese highlight.
    Overlapping and adjacent Chinese spans are merged without repeating text.
    """
    alignments = _validated_alignments(english, translation, alignment_payload)
    if (not isinstance(matched_english_ranges, Iterable)
            or isinstance(matched_english_ranges, (str, bytes, Mapping))):
        raise TranslationAlignmentError("matched_english_ranges must be an iterable of ranges")
    matched = tuple(_range(span, len(english), f"matched_english_ranges[{index}]", json_array=False)
                    for index, span in enumerate(matched_english_ranges))
    body = _body_range(english)
    chinese: list[_Range] = []
    for span in matched:
        selected = _select_alignment(alignments, span, body)
        if selected is not None:
            chinese.extend(selected.zh)

    parts: list[str] = []
    position = 0
    for start, end in _merge_ranges(chinese):
        parts.append(escape(translation[position:start]))
        parts.append('<span class="term-highlight">')
        parts.append(escape(translation[start:end]))
        parts.append("</span>")
        position = end
    parts.append(escape(translation[position:]))
    return "".join(parts)
