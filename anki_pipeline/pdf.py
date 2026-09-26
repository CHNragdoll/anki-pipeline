"""Read-only extraction of word examples from exam PDFs.

This module keeps the useful year/section/part/text provenance of the V2.0
extractor, but uses exact forms and returns plain sentences rather than HTML.
PyMuPDF is imported only when a PDF is actually opened.
"""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path
import re

from .text import matches_word, strip_markup, word_variants


_YEAR = re.compile(r"(?P<year>\d{4})\s*年")
_PAPER = re.compile(r"英语\s*[（(]?\s*(?P<paper>[一二12ⅠⅡ])\s*[)）]?", re.I)
_HEADING = re.compile(
    r"(?P<top>\d{4}\s*年\s*全国硕士研究生招生考试\s*英语(?:\s*[（(]?\s*[一二12ⅠⅡ]\s*[)）]?)?(?:\s*试题)?)"
    r"|(?P<section>\bSection\s+[IVXLC]+\b)"
    r"|(?P<part>\bPart\s+[A-Z]\b)"
    r"|(?P<passage>\bText\s+\d+\b)",
    re.I,
)
_DIRECTIONS = re.compile(
    r"^\s*(?:Directions\s*[:：]|Write an essay\b|Read the following\b|"
    r"Translate the following\b|Translate the text\b|Your translation\b|"
    r"Write your translation\b|In this section\b)",
    re.I,
)
_DIRECTIONS_BLOCK = re.compile(
    r"(?:^|\n)\s*(?:\d+\.\s*)?Directions\s*[:：]"
    r"[\s\S]{0,1500}?(?:\(\s*\d+\s*(?:points?|marks?)\s*\)|"
    r"（\s*\d+\s*(?:points?|marks?)\s*）)",
    re.I,
)
_HEADING_TAIL = re.compile(
    r"^(?:Reading Comprehension|Use of English|Cloze Test|Translation|Writing|试题)\b",
    re.I,
)
_SCORE = re.compile(r"^\s*(?:\(\s*\d+\s*(?:points?|marks?)\s*\)|\(\s*\d+\s*\))\s*", re.I)


def _normalize_title(raw: str) -> str:
    match = _YEAR.search(raw)
    if not match:
        return ""
    year = int(match.group("year"))
    if year <= 2009:
        return f"{year}年"
    paper = _PAPER.search(raw)
    if not paper:
        return f"{year}年英语"
    canonical = {"1": "一", "2": "二", "Ⅰ": "一", "Ⅱ": "二"}.get(paper.group("paper"), paper.group("paper"))
    return f"{year}年英语（{canonical}）"


def _source(state: dict[str, str], page: int) -> str:
    path = [state[key] for key in ("top", "section", "part", "passage") if state[key]]
    path.append(f"第{page}页")
    return " ➫ ".join(path)


def _is_boundary(text: str, index: int) -> bool:
    char = text[index]
    if char not in ".?!。！？":
        return False
    if char != ".":
        return True
    before = text[index - 1] if index else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if before.isdigit() and after.isdigit():
        return False
    # Internal and final periods of common dotted abbreviations (U.S., e.g.).
    if before.isalpha() and after.isalpha():
        return False
    if index >= 2 and text[index - 2] == "." and before.isalpha():
        return False
    return True


def _sentence_at(text: str, start: int, end: int) -> str:
    left = start - 1
    while left >= 0:
        if _is_boundary(text, left):
            left += 1
            break
        if left and text[left - 1 : left + 1] == "\n\n":
            left += 1
            break
        left -= 1
    left = max(left, 0)

    right = end
    while right < len(text):
        if _is_boundary(text, right):
            right += 1
            break
        if text[right : right + 2] == "\n\n":
            break
        right += 1
    return strip_markup(_SCORE.sub("", text[left:right])).strip(" \n\t-—")


def _page_lines(pages: list[str], filename: str) -> tuple[str, list[int], list[tuple[str, int]]]:
    state = {"top": "", "section": "", "part": "", "passage": ""}
    state["top"] = _normalize_title(filename)
    chunks: list[str] = []
    starts: list[int] = []
    locations: list[tuple[str, int]] = []
    offset = 0
    heading_before_next = False

    for page_no, page_text in enumerate(pages, start=1):
        page_text = _DIRECTIONS_BLOCK.sub("\n", page_text)
        for raw in page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line:
                continue
            if _DIRECTIONS.match(line):
                heading_before_next = True
                continue
            headings = list(_HEADING.finditer(line))
            if headings:
                heading_before_next = True
                for heading in headings:
                    kind = heading.lastgroup
                    label = " ".join(heading.group().split())
                    if kind == "top":
                        state.update(top=_normalize_title(label), section="", part="", passage="")
                    elif kind == "section":
                        state.update(section=label, part="", passage="")
                    elif kind == "part":
                        state.update(part=label, passage="")
                    elif kind == "passage":
                        state["passage"] = label
                line = line[headings[-1].end() :].strip(" :-—")
                if not line or _HEADING_TAIL.match(line):
                    continue
                if _DIRECTIONS.match(line):
                    continue

            if not state["top"]:
                year = _YEAR.search(line)
                if year and "英语" in line:
                    state["top"] = _normalize_title(line)

            separator = "\n\n" if heading_before_next else "\n"
            if chunks:
                chunks.append(separator)
                offset += len(separator)
            starts.append(offset)
            chunks.append(line)
            locations.append((_source(state, page_no), page_no))
            offset += len(line)
            heading_before_next = False

    return "".join(chunks), starts, locations


def extract_examples(pdf_path: str | Path, words: list[str], *, extra_forms: dict[str, set[str]] | None = None) -> dict[str, list[dict[str, str]]]:
    """Extract whole-word examples once per PDF, keyed by supplied word.

    Source contains the nearest title hierarchy and one-based PDF page.  A
    missing PyMuPDF installation raises an actionable ImportError.  This
    function performs no database or network writes.
    """
    try:
        import fitz  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("PDF extraction requires PyMuPDF (pip install pymupdf)") from exc

    with fitz.open(str(pdf_path)) as document:
        pages = [page.get_text() for page in document]
    full_text, starts, locations = _page_lines(pages, Path(pdf_path).name)
    results: dict[str, list[dict[str, str]]] = {}
    for word in words:
        supplied = (extra_forms or {}).get(word, ())
        forms = word_variants(word, supplied)
        examples: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        if forms:
            pattern = re.compile(
                r"(?<!\w)(?:" + "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True)) + r")(?!\w)",
                re.I,
            )
            for match in pattern.finditer(full_text):
                index = bisect_right(starts, match.start()) - 1
                if index < 0:
                    continue
                sentence = _sentence_at(full_text, match.start(), match.end())
                if len(sentence.split()) < 4 or not matches_word(word, sentence, supplied):
                    continue
                source, _ = locations[index]
                key = (sentence.casefold(), source)
                if key in seen:
                    continue
                seen.add(key)
                examples.append({"text": sentence, "source": source})
        results[word] = examples
    return results
