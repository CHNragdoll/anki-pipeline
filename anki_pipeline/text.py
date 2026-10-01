"""Pure text normalization, exact word matching, and numbered entry parsing.

The legacy PDF script matched an open-ended stem.  These functions deliberately
only match a lemma, a conservative inflection, or an explicitly supplied form.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from typing import Iterable


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template"}:
            self.hidden += 1
        elif not self.hidden and tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "tr"} and not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template"} and self.hidden:
            self.hidden -= 1
        elif not self.hidden and tag in {"p", "div", "li", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def strip_markup(text: str) -> str:
    """Return plain, whitespace-normalized text; discard active HTML content."""
    parser = _PlainText()
    parser.feed(str(text or ""))
    parser.close()
    return " ".join("".join(parser.parts).split())


_WORD = re.compile(r"[a-z]+(?:[-'][a-z]+)*\Z")
_HEADING_US_VARIANT = re.compile(r"[^\n]+\n\s*\(美\s*([a-z]+(?:[-'][a-z]+)*)\s*\)\s*\Z", re.I)


def _lookup_word(word: str) -> str:
    # Historical word cells can carry a pronunciation/variant on later lines.
    first = str(word or "").replace("\r", "\n").split("\n", 1)[0]
    return unicodedata.normalize("NFKC", first).strip().casefold()


_IRREGULAR: dict[str, set[str]] = {
    "be": {"am", "is", "are", "was", "were", "been", "being"},
    "do": {"does", "did", "done", "doing"},
    "go": {"goes", "went", "gone", "going"},
    "have": {"has", "had", "having"},
    "make": {"makes", "made", "making"},
    "run": {"runs", "ran", "running"},
    "fly": {"flies", "flew", "flown", "flying"},
    "buy": {"buys", "bought", "buying"},
    "sit": {"sits", "sat", "sitting"},
    "stop": {"stops", "stopped", "stopping"},
    "plan": {"plans", "planned", "planning"},
    "write": {"writes", "wrote", "written", "writing"},
    "eat": {"eats", "ate", "eaten", "eating"},
    "child": {"children"},
    "man": {"men"},
    "woman": {"women"},
    "mouse": {"mice"},
    "person": {"people"},
}


def word_variants(word: str, extra: Iterable[str] = (), *, infer: bool = True) -> set[str]:
    """Return whole-word forms; exact mode also accepts a declared US title spelling."""
    lemma = _lookup_word(word)
    if not _WORD.fullmatch(lemma):
        return set()
    forms = {lemma}
    if not infer:
        heading = unicodedata.normalize("NFKC", str(word or "").replace("\r", "\n"))
        variant = _HEADING_US_VARIANT.fullmatch(heading)
        if variant:
            forms.add(variant.group(1).casefold())
    if infer and lemma in _IRREGULAR:
        forms.update(_IRREGULAR[lemma])
    elif infer:
        if lemma.endswith("y") and len(lemma) > 1 and lemma[-2] not in "aeiou":
            forms.update({lemma[:-1] + "ies", lemma[:-1] + "ied"})
        elif lemma.endswith(("s", "x", "z", "ch", "sh")):
            forms.update({lemma + "es", lemma + "ed"})
        elif lemma.endswith("e"):
            forms.update({lemma + "s", lemma + "d"})
        else:
            forms.update({lemma + "s", lemma + "ed"})

        if lemma.endswith("ie"):
            forms.add(lemma[:-2] + "ying")
        elif lemma.endswith("e") and not lemma.endswith(("ee", "ye", "oe")):
            forms.add(lemma[:-1] + "ing")
        else:
            forms.add(lemma + "ing")

    supplied = (extra,) if isinstance(extra, str) else extra
    for form in supplied:
        normalized = _lookup_word(form)
        if _WORD.fullmatch(normalized):
            forms.add(normalized)
    return forms


def matches_word(word: str, text: str, extra: Iterable[str] = ()) -> bool:
    """Match complete tokens, case insensitively, with no stem wildcard."""
    forms = word_variants(word, extra)
    if not forms:
        return False
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True)) + r")(?!\w)"
    return re.search(pattern, strip_markup(text), flags=re.IGNORECASE) is not None


def _normalized_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", strip_markup(value)).casefold()


def stable_sentence_id(word: str, text: str, source: str) -> str:
    """SHA-256 of normalized word, sentence and source, independent of numbering."""
    values = [_lookup_word(word), _normalized_identity(text), _normalized_identity(source)]
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_NUMBERED = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
_SOURCE = re.compile(r"^(?:\d{4}\s*年|Section\s+[IVXLC]+\b|Part\s+[A-Z]\b|Text\s+\d+\b|Page\s+\d+\b)", re.I)
_CJK = re.compile(r"[\u3400-\u9fff]")


def _numbered_blocks(blob: str) -> list[tuple[int, list[str]]]:
    blocks: list[tuple[int, list[str]]] = []
    number: int | None = None
    lines: list[str] = []
    for line in str(blob or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _NUMBERED.match(line)
        if match:
            if number is not None:
                blocks.append((number, lines))
            number, lines = int(match.group(1)), [match.group(2)]
        elif number is not None:
            lines.append(line)
    if number is not None:
        blocks.append((number, lines))
    return blocks


def parse_numbered_entries(blob: str) -> list[dict[str, int | str]]:
    """Parse legacy or merged example blobs into one English entry per number.

    A repeated Chinese ``[n]`` line is a translation, not another example.
    Conflicting English entries with the same number are rejected for review.
    """
    entries: dict[int, dict[str, int | str]] = {}
    for number, lines in _numbered_blocks(blob):
        content: list[str] = []
        source_lines: list[str] = []
        in_source = False
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if _SOURCE.match(line) or "➫" in line:
                in_source = True
            (source_lines if in_source else content).append(line)
        plain = strip_markup(" ".join(content))
        source = " ".join(source_lines)
        if not plain:
            continue
        is_translation = bool(_CJK.search(plain)) and not bool(re.search(r"[A-Za-z]", plain))
        if is_translation:
            if number in entries and source and not entries[number]["source"]:
                entries[number]["source"] = source
            continue
        if number in entries:
            existing = entries[number]
            if _normalized_identity(str(existing["text"])) != _normalized_identity(plain):
                raise ValueError(f"conflicting example number [{number}]")
            if source:
                if existing["source"] and existing["source"] != source:
                    raise ValueError(f"conflicting source for example [{number}]")
                existing["source"] = source
        else:
            entries[number] = {"number": number, "text": plain, "source": source}
    return list(entries.values())


def parse_translations(blob: str) -> dict[int, str]:
    """Parse numbered translations, preserving continuation lines and order."""
    result: dict[int, str] = {}
    for number, lines in _numbered_blocks(blob):
        translation = "\n".join(line.strip() for line in lines).strip()
        if number in result and result[number] != translation:
            raise ValueError(f"conflicting translation number [{number}]")
        result[number] = translation
    return result


def assess_translation(text: str) -> str:
    """Flag only missing, placeholder or visibly unfinished translations."""
    value = str(text or "").strip()
    if not value:
        return "missing translation"
    if re.fullmatch(r"(?:待翻译|未翻译|暂无翻译|TODO|TBD|N/A|\[翻译\])\s*[.!。！]?", value, re.I):
        return "placeholder translation"
    if re.search(r"(?:\.{3,}|…+|，|、|,|：|:)\s*$", value):
        return "translation appears incomplete"
    return ""
