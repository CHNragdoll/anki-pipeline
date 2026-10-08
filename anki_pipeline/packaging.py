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
from urllib.parse import urlsplit
from typing import Any

import genanki

from .forms import explicit_forms
from .text import word_variants
from .presentation import render_forms, render_levels, render_senses


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


def _cloze_ranges(source_text: Any, text: str, answers: Any, *,
                  preserve_source: bool = False) -> list[tuple[int, int, int]]:
    """Validate half-open Unicode character ranges against the supplied text."""
    if not isinstance(answers, list):
        raise ValueError("cloze_answers must be a list")
    if not answers:
        return []
    if not isinstance(source_text, str):
        raise ValueError("cloze answer ranges require example text to be a string")
    trim_start = 0 if preserve_source else len(source_text) - len(source_text.lstrip())
    trim_end = trim_start + len(text)
    ranges = []
    numbers = set()
    for answer in answers:
        if not isinstance(answer, dict) or not {"start", "end", "word", "number"} <= answer.keys():
            raise ValueError("cloze answer needs start, end, word and number")
        start, end, number = answer["start"], answer["end"], answer["number"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (start, end, number)):
            raise ValueError("cloze answer offsets and number must be integers")
        if number <= 0 or number in numbers:
            raise ValueError("cloze answer number must be positive and unique")
        if not 0 <= start < end <= len(source_text):
            raise ValueError("cloze answer range is outside example text")
        value = answer["word"]
        if not isinstance(value, str) or not value.strip() or "\x00" in value or source_text[start:end] != value:
            raise ValueError("cloze answer word does not match its text range")
        if start < trim_start or end > trim_end:
            raise ValueError("cloze answer range includes trimmed edge whitespace")
        numbers.add(number)
        ranges.append((start - trim_start, end - trim_start, number))
    ranges.sort()
    if any(current[0] < previous[1] for previous, current in zip(ranges, ranges[1:])):
        raise ValueError("cloze answer ranges overlap")
    return ranges


def _example_target_ranges(text: str, word: str, forms: str, *, declared_only: bool,
                           declared_forms: set[str] | None) -> list[tuple[int, int]]:
    """Locate complete English target words and explicitly selected forms."""
    variants = word_variants(word, explicit_forms(forms) if declared_forms is None else declared_forms,
                             infer=not declared_only and declared_forms is None)
    if not variants:
        return []
    pattern = re.compile(r"(?<!\w)(?:" + "|".join(
        re.escape(form) for form in sorted(variants, key=lambda value: (-len(value), value))
    ) + r")(?!\w)", re.IGNORECASE)
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def _highlight_example(source_text: Any, word: str, forms: str, cloze_answers: Any,
                       *, declared_only: bool = False,
                       declared_forms: set[str] | None = None,
                       target_ranges: list[tuple[int, int]] | None = None,
                       chunk_ranges: list[tuple[int, int, int]] | None = None,
                       preserve_source: bool = False) -> str:
    """Safely combine exact target highlighting with actual blank underlines."""
    text = _plain(source_text, "example text")
    if preserve_source:
        text = source_text
    cloze_ranges = _cloze_ranges(source_text, text, cloze_answers, preserve_source=preserve_source)
    if target_ranges is not None:
        if not isinstance(source_text, str) or (not preserve_source and source_text.strip() != text):
            raise ValueError('Pinned example ranges require plain source text')
        trim_start = 0 if preserve_source else len(source_text) - len(source_text.lstrip())
        target_ranges = [(start - trim_start, end - trim_start) for start, end in target_ranges]
        if any(not 0 <= start < end <= len(text) for start, end in target_ranges):
            raise ValueError('Pinned example target range includes trimmed edge whitespace')
    if target_ranges is None:
        target_ranges = _example_target_ranges(text, word, forms, declared_only=declared_only,
                                               declared_forms=declared_forms)
    boundaries = {0, len(text)}
    for start, end in target_ranges:
        boundaries.update((start, end))
    for start, end, _ in cloze_ranges:
        boundaries.update((start, end))
    for start, end, _ in chunk_ranges or []:
        boundaries.update((start, end))
    offsets = sorted(boundaries)
    parts = []
    active: list[tuple[str, int]] = []
    target_index = cloze_index = 0
    for start, end in zip(offsets, offsets[1:]):
        while target_index < len(target_ranges) and target_ranges[target_index][1] <= start:
            target_index += 1
        while cloze_index < len(cloze_ranges) and cloze_ranges[cloze_index][1] <= start:
            cloze_index += 1
        desired = []
        if cloze_index < len(cloze_ranges) and cloze_ranges[cloze_index][0] <= start:
            desired.append(("u", cloze_ranges[cloze_index][2]))
        if target_index < len(target_ranges) and target_ranges[target_index][0] <= start:
            desired.append(("mark", target_index))
        common = 0
        while common < min(len(active), len(desired)) and active[common] == desired[common]:
            common += 1
        parts.extend(f"</{tag}>" for tag, _ in reversed(active[common:]))
        for tag, identity in desired[common:]:
            parts.append(f'<u class="cloze-answer" data-blank-number="{identity}">' if tag == "u"
                         else '<mark class="target-word">')
        parts.append(_chunk_segment(text[start:end], "en", start, end, chunk_ranges or []))
        active = desired
    parts.extend(f"</{tag}>" for tag, _ in reversed(active))
    return "".join(parts).replace("\n", "<br>")


def _example_chunk_ranges(example: dict) -> tuple[list[tuple[int, int, int]],
                                                 list[tuple[int, int, int]], bool]:
    """Reject stale reviewed Codex data; optional generic chunks may degrade."""
    if "translation_alignment" not in example:
        return [], [], False
    from .translation_alignment import TranslationAlignmentError, validate_translation_alignment
    try:
        validate_translation_alignment(example["text"], example["translation"],
                                       example["translation_alignment"])
    except TranslationAlignmentError:
        if example.get("translation_source") == "codex":
            raise
        return [], [], False
    english, chinese = [], []
    for identity, entry in enumerate(example["translation_alignment"]["alignments"]):
        if entry["relation"] != "equivalent":
            continue
        english.append((*entry["en"], identity))
        chinese.extend((*span, identity) for span in entry["zh"])
    # A point in overlapping English chunks selects the finest authored range.
    # Chinese reverse activation is enabled only for an unambiguous membership.
    english.sort(key=lambda span: (span[1] - span[0], span[2]))
    return english, chinese, True


def _chunk_segment(text: str, side: str, start: int, end: int,
                   ranges: list[tuple[int, int, int]]) -> str:
    identities = list(dict.fromkeys(identity for left, right, identity in ranges
                                   if left <= start and end <= right))
    escaped = html.escape(text, quote=True)
    if not identities:
        return escaped
    ids = " ".join(str(identity) for identity in identities)
    return f'<span class="card-chunk" data-chunk-side="{side}" data-chunk-ids="{ids}">{escaped}</span>'


def _chunk_translation(text: str, ranges: list[tuple[int, int, int]]) -> str:
    boundaries = sorted({0, len(text)} | {offset for start, end, _ in ranges for offset in (start, end)})
    return "".join(_chunk_segment(text[start:end], "zh", start, end, ranges)
                   for start, end in zip(boundaries, boundaries[1:])).replace("\n", "<br>")


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


def _dictionary_audio_choices(card: dict) -> dict[str, str]:
    """Select one actual headword recording per dictionary, preferring US."""
    data = card.get("local_dictionary")
    if data is None:
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("audio"), dict):
        raise ValueError("local_dictionary needs a structured audio mapping")
    choices = {}
    for source in ("oxford", "webster"):
        recordings = data["audio"].get(source, [])
        if not isinstance(recordings, list):
            raise ValueError("dictionary recordings must be a list")
        for recording in recordings:
            if not isinstance(recording, dict) or not isinstance(recording.get("filename"), str):
                raise ValueError("dictionary recording needs a filename")
            _audio_file(recording["filename"], None)
        ordered = sorted(recordings, key=lambda item: item.get("accent") != "us")
        if ordered:
            choices[source] = ordered[0]["filename"]
    fallbacks = data.get("fallback_audio", {})
    if not isinstance(fallbacks, dict):
        raise ValueError("dictionary audio fallback must be a source mapping")
    for requested, actual in fallbacks.items():
        if requested not in {"oxford", "webster"} or actual not in {"oxford", "webster"} or requested == actual:
            raise ValueError("invalid dictionary audio fallback source")
        if requested in choices or actual not in choices:
            raise ValueError("dictionary fallback must fill an absent source with an available source")
    return choices


def _card_audio_files(card: dict, audio_dir: Path | None) -> dict[str, Path | None]:
    if "local_dictionary" in card:
        _dictionary_audio_choices(card)
        names = [row["filename"] for rows in card["local_dictionary"]["audio"].values()
                 for row in rows]
        names.extend(row["filename"] for _, _, row in _accent_recordings(card))
    else:
        names = [_plain(card["audio_filename"], "audio_filename")]
    return {name: _audio_file(name, audio_dir) for name in names if name}


def _accent_recordings(card: dict) -> list[tuple[str, str, dict]]:
    """Opt in only with explicit per-headword, per-accent source metadata."""
    data = card.get("local_dictionary", {})
    if "accent_audio" not in data:
        return []
    mapping = data["accent_audio"]
    selectors = {"uk": {"cambridge", "oxford"}, "us": {"oxford", "webster"}}
    supplements = {"collins", "wiktionary", "forvo"}
    allowed = {"uk": selectors["uk"] | supplements,
               "us": selectors["us"] | supplements | {"cambridge"}}
    if not isinstance(mapping, dict) or set(mapping) != set(allowed):
        raise ValueError("accent_audio must separate uk and us")
    result = []
    available = {accent: set() for accent in allowed}
    for accent, sources in mapping.items():
        if not isinstance(sources, dict) or set(sources) - allowed[accent]:
            raise ValueError("invalid accent dictionary source")
        for source, rows in sources.items():
            if not isinstance(rows, list):
                raise ValueError("accent recordings must be a list")
            for row in rows:
                if not isinstance(row, dict) or row.get("accent") != accent or not isinstance(row.get("filename"), str) or not row["filename"]:
                    raise ValueError("recording must declare its actual accent and filename")
                _audio_file(row["filename"], None)
                result.append((accent, source, row))
                available[accent].add(source)
    fallbacks = data.get("accent_audio_fallback", {})
    if not isinstance(fallbacks, dict) or set(fallbacks) - allowed.keys():
        raise ValueError("invalid accent fallback mapping")
    for accent, choices in fallbacks.items():
        if not isinstance(choices, dict):
            raise ValueError("accent fallbacks must be a source mapping")
        for requested, actual in choices.items():
            if requested not in selectors[accent] or actual not in allowed[accent] or requested == actual \
                    or requested in available[accent] or actual not in available[accent]:
                raise ValueError("accent fallback must fill an absent source with the same accent")
    return result


def _ecdict_data(card: dict) -> dict | None:
    """Validate display metadata without filling gaps or deriving new forms."""
    if "ecdict" not in card:
        return None
    data = card["ecdict"]
    if not isinstance(data, dict):
        raise ValueError("ecdict must contain structured dictionary metadata")
    if not isinstance(data.get("translation"), str):
        raise ValueError("ecdict translation must be text")
    _plain(data["translation"], "ECDICT translation")
    for key in ("tags", "tag_labels"):
        values = data.get(key)
        if not isinstance(values, list) or any(not isinstance(value, str) or not _plain(value, key)
                                              for value in values):
            raise ValueError(f"ecdict {key} must be a list of nonempty text labels")
    for key, field in (("forms", "form"), ("derived", "word")):
        values = data.get(key)
        if not isinstance(values, list):
            raise ValueError(f"ecdict {key} must be a list of explicit rows")
        for row in values:
            if (not isinstance(row, dict) or row.get("source") != "ecdict"
                    or any(not isinstance(row.get(name), str) or not _plain(row[name], name)
                           for name in ("label", field))):
                raise ValueError(f"ecdict {key} needs explicit labels, {field} and source")
    if not isinstance(data.get("provenance"), dict):
        raise ValueError("ecdict provenance must be structured metadata")
    license_text = data["provenance"].get("license_text")
    if not isinstance(license_text, str) or not _plain(license_text, "ECDICT license"):
        raise ValueError("ecdict provenance needs the complete plain-text license")
    return data


def _dictionary_rows_source(data: dict, key: str, rows: list, ecdict: dict | None) -> str:
    source = data.get(key + "_source", "webster" if rows else "")
    if not isinstance(source, str) or source not in {"webster", "ecdict", ""} or (rows and not source):
        raise ValueError(f"invalid dictionary {key} source")
    if source == "ecdict":
        if ecdict is None or not rows:
            raise ValueError(f"ECDICT {key} fallback needs explicit ECDICT rows")
        field = "form" if key == "forms" else "word"
        declared = {(row["label"], row[field]) for row in ecdict[key]}
        for row in rows:
            if (not isinstance(row, dict) or row.get("source") != "ecdict"
                    or any(not isinstance(row.get(name), str) for name in ("label", field))
                    or (row["label"], row[field]) not in declared):
                raise ValueError(f"dictionary {key} fallback must match declared ECDICT rows")
    return source


def _dictionary_markup(card: dict) -> tuple[str, str]:
    data = card["local_dictionary"]
    ecdict = _ecdict_data(card)
    senses, forms, derived = (data.get(key, []) for key in ("senses", "forms", "derived"))
    if any(not isinstance(value, list) for value in (senses, forms, derived)):
        raise ValueError("dictionary senses, forms and derived words must be lists")
    rows = []
    for sense in senses:
        if not isinstance(sense, dict) or not {"pos", "text"} <= sense.keys():
            raise ValueError("Oxford sense needs pos and text")
        rows.append('<div class="sense-row"><span class="sense-pos">'
                    + _escaped(sense["pos"], "dictionary part of speech") + '</span>'
                    + '<span class="sense-text">' + _escaped(sense["text"], "Oxford sense") + '</span></div>')
    definition_source = data.get("definition_source", "oxford")
    if not isinstance(definition_source, str) or definition_source not in {"oxford", "wordbook", "ecdict", "reviewed"}:
        raise ValueError("unknown definition source")
    if definition_source in {"wordbook", "ecdict"}:
        if rows:
            raise ValueError("definition fallback must only fill absent Oxford senses")
        fallback = _plain(data.get("definition_fallback", ""), definition_source + " definition")
        if definition_source == "ecdict" and (ecdict is None or not fallback
                or fallback != _plain(ecdict["translation"], "ECDICT translation")):
            raise ValueError("ECDICT definition fallback must match a nonempty declared translation")
        content = render_senses(fallback)
    else:
        content = ''.join(rows)
    definition = f'<div class="dictionary-definition" data-dictionary="{definition_source}">' + (
        content or '<span class="dictionary-missing">牛津原包未收录此词的中文释义</span>') + '</div>'
    if definition_source == "reviewed":
        notice = data.get("definition_source_notice")
        keys = ("source_name", "source_headword", "source_excerpt", "text", "heading")
        if not rows or not isinstance(notice, dict) or any(
                not isinstance(notice.get(key), str) or not notice[key].strip() for key in keys):
            raise ValueError("Reviewed definition needs senses and a visible source notice")
        definition = ('<div class="dictionary-definition" data-dictionary="reviewed" '
                      'data-definition-heading="' + html.escape(notice["heading"], quote=True)
                      + '">' + content + '</div>')
        definition += ('<details class="definition-source-notice" style="font-size:.8em;color:var(--muted,#63718a);margin:.4em 0;overflow-wrap:anywhere">'
                       '<summary>释义来源（已核对）</summary><p>'
                       + html.escape('；'.join(notice[key] for key in keys[:4]), quote=True)
                       + '</p></details>')
    forms_source = _dictionary_rows_source(data, "forms", forms, ecdict)
    derived_source = _dictionary_rows_source(data, "derived", derived, ecdict)
    form_rows = []
    for form in forms:
        if not isinstance(form, dict) or not {"label", "form"} <= form.keys():
            raise ValueError("Webster form needs label and form")
        note = _plain(form.get("note", ""), "dictionary form note")
        form_rows.append('<dl class="form-row"><dt>' + _escaped(form["label"], "form label")
                         + '</dt><dd>' + _escaped(form["form"], "form")
                         + (f' <small>{html.escape(note)}</small>' if note else '') + '</dd></dl>')
    derived_rows = []
    for item in derived:
        if not isinstance(item, dict) or not {"label", "word"} <= item.keys():
            raise ValueError("Webster derived word needs label and word")
        derived_rows.append('<dl class="form-row derived-word"><dt>'
                         + _escaped(item["label"], "derived label") + '</dt><dd>'
                         + _escaped(item["word"], "derived word") + '</dd></dl>')
    source_hint = '<small class="dictionary-source">ECDICT 补充</small>'
    sources = {source for source in (forms_source, derived_source) if source}
    group_source = next(iter(sources)) if len(sources) == 1 else "mixed" if sources else "webster"
    forms_attrs = ' data-dictionary="ecdict"' if forms_source == "ecdict" else ''
    derived_attrs = ' data-dictionary="ecdict"' if derived_source == "ecdict" else ''
    forms_html = (f'<div class="dictionary-form-groups dictionary-forms" data-dictionary="{group_source}">'
                  f'<section class="dictionary-inflections"{forms_attrs}><h3 class="field-title">词形变化'
                  + (' ' + source_hint if forms_source == "ecdict" else '') + '</h3>'
                  '<div class="forms-list">' + (''.join(form_rows) if form_rows else
                  '<span class="dictionary-missing">韦氏原包未列出词形变化</span>') + '</div></section>')
    if derived_rows:
        forms_html += (f'<section class="dictionary-derived"{derived_attrs}><h3 class="field-title">派生词与词族'
                       + (' ' + source_hint if derived_source == "ecdict" else '') + '</h3>'
                       '<div class="forms-list">' + ''.join(derived_rows) + '</div></section>')
    forms_html += '</div>'
    return definition, forms_html


def _ecdict_levels(data: dict) -> str:
    labels = data["tag_labels"]
    notice = ('<div class="ecdict-license-notice" hidden aria-hidden="true">'
              + html.escape(data["provenance"]["license_text"], quote=True) + '</div>')
    if not labels:
        return '<small class="dictionary-missing" data-dictionary="ecdict">ECDICT 未标注考试标签</small>' + notice
    return ('<ul class="level-list" data-dictionary="ecdict" aria-label="ECDICT 考试标签">'
            + ''.join('<li>' + html.escape(label, quote=True) + '</li>' for label in labels) + '</ul>' + notice)


def _exam_frequency_markup(card: dict) -> str:
    """Carry counts and self-contained styling without changing Anki identity.

    Legacy APKG updates can retain installed model CSS even when note fields
    update. These fixed inline styles keep the new component usable there.
    """
    if "exam_frequency" not in card:
        return ""
    from .exam_frequency import frequency_stars
    data = card["exam_frequency"]
    if not isinstance(data, dict) or data.get("schema") != "kaoyan-frequency.v1" or data.get("rule") != "occurrence-bands.v1":
        raise ValueError("unknown exam frequency schema or rating rule")
    keys = ("occurrences", "matched_sentences", "paper_count", "corpus_papers")
    if any(type(data.get(key)) is not int or data[key] < 0 for key in keys):
        raise ValueError("exam frequency counts must be nonnegative integers")
    count, sentences, papers, corpus = (data[key] for key in keys)
    if not 0 <= papers <= sentences <= count or papers > corpus or bool(count) != bool(papers):
        raise ValueError("inconsistent exam frequency counts")
    stars = data.get("stars")
    if (type(stars) not in (int, float) or stars != frequency_stars(count)):
        raise ValueError("exam frequency rating does not match its count")
    score = f"{stars:g}"
    star_path = "M12 2l3.09 6.26L22 9.54l-5 4.87 1.18 6.88L12 18.04l-6.18 3.25L7 14.41 2 9.54l6.91-1.01z"
    shapes = []
    for index in range(5):
        fraction = min(1, max(0, stars - index))
        fill = (f'<svg class="frequency-star-fill" width="{fraction * 100:g}%" height="100%" '
                f'viewBox="0 0 {fraction * 24:g} 24" preserveAspectRatio="xMinYMid meet" style="overflow:hidden">'
                f'<path style="fill:#ad7918" d="{star_path}"/></svg>') if fraction else ""
        shapes.append('<svg class="frequency-star" viewBox="0 0 24 24" aria-hidden="true" '
                      'style="display:block;flex:none;width:1.1rem;height:1.1rem">'
                      f'<path class="frequency-star-track" style="fill:var(--line,#dce4ef)" d="{star_path}"/>' + fill + '</svg>')
    return (f'<section class="exam-frequency" aria-label="考研真题词频" data-occurrences="{count}" '
            f'data-stars="{score}" data-paper-count="{papers}" data-corpus-papers="{corpus}" '
            f'data-matched-sentences="{sentences}" data-schema="kaoyan-frequency.v1" data-rule="occurrence-bands.v1" '
            'style="margin:0 0 .55rem;padding:0 0 .55rem;border-bottom:1px solid var(--line,#dce4ef);font-size:.9rem;font-weight:400;line-height:1.6">'
            '<h3 class="field-title" style="color:var(--secondary,#47566c)">真题词频</h3>'
            '<div class="frequency-summary" style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:.55rem 1rem">'
            '<span class="frequency-count" style="display:inline-flex;flex-wrap:wrap;align-items:baseline;gap:.3rem .65rem;min-width:0">'
            f'<strong style="color:var(--ink,#202b3c);font-size:1rem;font-weight:600;font-variant-numeric:tabular-nums">{count} 次</strong>'
            f'<span class="frequency-coverage" style="color:var(--muted,#63718a);font-size:.8rem">覆盖 {papers} / {corpus} 套</span></span>'
            f'<span class="frequency-rating" role="img" aria-label="{score} / 5 星" '
            'style="display:inline-flex;align-items:center;gap:.15rem;max-width:100%" '
            'title="按本库真题原文的出现次数分档；含原词和词典明确列出的词形，不含派生词。">'
            + ''.join(shapes) + '<span class="frequency-score" '
            f'style="margin-left:.4rem;color:var(--muted,#63718a);font-size:.8rem;font-variant-numeric:tabular-nums;white-space:nowrap">{score} / 5</span></span>'
            '</div></section>')


def _dictionary_audio_markup(card: dict, audio_dir: Path | None, *, preview: bool) -> str:
    _dictionary_audio_choices(card)
    if "accent_audio" in card["local_dictionary"]:
        audio = []
        for accent, source, recording in _accent_recordings(card):
            filename = recording["filename"]
            path = _audio_file(filename, audio_dir)
            reference = ('data:audio/mpeg;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
                         if preview and path else filename)
            audio.append(f'<audio preload="none" hidden data-dictionary-source="{source}" '
                         f'data-dictionary-accent="{accent}" src="{html.escape(reference, quote=True)}"></audio>')
        fallback_attrs = ''.join(f' data-fallback-{accent}-{requested}="{actual}"'
                                for accent, choices in card["local_dictionary"].get("accent_audio_fallback", {}).items()
                                for requested, actual in choices.items())
        return ('<div class="dictionary-word-audio" data-accent-playback="v1"' + fallback_attrs + '>'
                + ''.join(audio) + '<span class="word-audio-status" role="status"></span></div>')
    audio = []
    for source in ("oxford", "webster"):
        recordings = sorted(card["local_dictionary"]["audio"].get(source, []),
                            key=lambda item: item.get("accent") != "us")
        for recording in recordings:
            filename = recording["filename"]
            path = _audio_file(filename, audio_dir)
            reference = ('data:audio/mpeg;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
                         if preview and path else filename)
            audio.append(f'<audio preload="none" hidden data-dictionary-source="{source}" '
                         f'src="{html.escape(reference, quote=True)}"></audio>')
    fallback_attrs = ''.join(f' data-fallback-{requested}="{actual}"'
                             for requested, actual in card["local_dictionary"].get("fallback_audio", {}).items())
    return ('<div class="dictionary-word-audio" data-default-source="oxford"' + fallback_attrs + '>'
            '<label class="dictionary-audio-setting">发音 <select class="dictionary-audio-source" '
            'aria-label="选择全局发音来源"><option value="oxford">牛津</option>'
            '<option value="webster">韦氏</option></select></label>'
            '<button type="button" class="preview-word-play replay-button" '
            'aria-label="播放单词发音" title="播放单词发音">'
            '<svg viewBox="0 0 64 64" aria-hidden="true">'
            '<circle cx="32" cy="32" r="29" fill="none" stroke="currentColor" stroke-width="1"/>'
            '<path d="M20 13L56 32L20 51Z" fill="currentColor"/></svg></button>'
            + ''.join(audio) + '<span class="word-audio-status" role="status"></span></div>')


def _source_jump(example: dict) -> str:
    if not example.get("latex_url") or not example.get("full_paper_url"):
        return ""
    links = []
    for key in ("latex_url", "full_paper_url"):
        value = _plain(example[key], key)
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("unsafe sentence source URL")
        links.append(html.escape(value, quote=True))
    reader = example.get("reader", "latex")
    if reader not in {"latex", "full-paper"}:
        raise ValueError("unknown sentence reader")
    target = links[0 if reader == "latex" else 1]
    return (f'<a class="sentence-jump" href="{target}" data-latex-url="{links[0]}" '
            f'data-full-paper-url="{links[1]}" data-reader="{reader}" target="_blank" rel="noopener" '
            'aria-label="跳转到真题原句" title="跳转到真题原句">'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" '
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
            'd="M14 4h6v6M20 4L10 14M10 4H4v16h16v-6"/></svg></a>')


def _fields(card: dict[str, Any], audio_dir: Path | None, max_examples: int,
            *, preview: bool = False) -> tuple[dict[str, str], Path | None, str]:
    if not isinstance(card, dict):
        raise ValueError("each card must be a dictionary")
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or max_examples < 0:
        raise ValueError("max_examples must be a nonnegative integer")
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
    ecdict = _ecdict_data(card)
    declared_forms = None
    if "local_dictionary" in card and examples:
        from .match_forms import card_match_forms
        declared_forms = card_match_forms(card)
    choices = _dictionary_audio_choices(card)
    filename = (next(iter(choices.values()), "") if "local_dictionary" in card
                else _plain(card["audio_filename"], "audio_filename"))
    audio_path = _audio_file(filename, audio_dir)
    audio_field = ""
    if "local_dictionary" in card:
        audio_field = _dictionary_audio_markup(card, audio_dir, preview=preview)
    elif filename:
        if preview:
            reference = ("data:audio/mpeg;base64," + base64.b64encode(audio_path.read_bytes()).decode("ascii")) if audio_path else filename
            audio_field = ('<button type="button" class="preview-word-play replay-button" '
                           'aria-label="播放单词发音" title="播放单词发音">'
                           '<svg viewBox="0 0 64 64" aria-hidden="true">'
                           '<circle cx="32" cy="32" r="29" fill="none" stroke="currentColor" stroke-width="1"/>'
                           '<path d="M20 13L56 32L20 51Z" fill="currentColor"/></svg></button>'
                           f'<audio preload="none" hidden src="{html.escape(reference, quote=True)}"></audio>'
                           '<span class="word-audio-status" role="status"></span>')
        else:
            audio_field = f"[sound:{filename}]"
    rendered_examples = []
    selected_examples = examples if max_examples == 0 else examples[:max_examples]
    for index, example in enumerate(selected_examples, start=1):
        if not isinstance(example, dict) or not {"text", "source", "translation"} <= example.keys():
            raise ValueError(f"card {card_id}: example {index} needs text, source, translation")
        source_jump = _source_jump(example)
        aligned = "translation_alignment" in example
        if example.get("translation_source") == "codex" and not aligned:
            raise ValueError(f"card {card_id}: Codex example {index} is missing its alignment")
        declared_only = bool(source_jump) or "local_dictionary" in card or aligned
        forms = _plain(card["word_forms"], "word_forms")
        ranges = _example_target_ranges(example["text"], word, forms,
                                         declared_only=declared_only, declared_forms=declared_forms)
        if "matched_english_ranges" in example:
            selected = example["matched_english_ranges"]
            if (not isinstance(selected, list) or not selected or
                    any(not isinstance(span, list) or len(span) != 2 or
                        any(type(offset) is not int for offset in span) for span in selected)):
                raise ValueError(f"card {card_id}: invalid matched English ranges")
            chosen = [tuple(span) for span in selected]
            if len(set(chosen)) != len(chosen) or any(span not in ranges for span in chosen):
                raise ValueError(f"card {card_id}: matched ranges are not explicit whole-word forms")
            # A contextual option includes a restored question. Mark the card
            # word throughout that display, while source occurrence counts and
            # jump coordinates continue to use the pinned original selection.
            # Ordinary examples retain their deliberately selective ranges.
            if not example.get("option_context"):
                ranges = sorted(chosen)
        english_chunks, chinese_chunks, valid_alignment = _example_chunk_ranges(example)
        text = _highlight_example(example["text"], word, _plain(card["word_forms"], "word_forms"),
                                  example.get("cloze_answers", []),
                                  declared_only=declared_only,
                                  declared_forms=declared_forms, target_ranges=ranges,
                                  chunk_ranges=english_chunks, preserve_source=valid_alignment)
        if example.get("option_context") and not example["option_context"].get("hasQuestionBlank"):
            # Compact only the generated question/option separator in the HTML.
            # Keep source text, hashes and indexed code-point ranges unchanged.
            text = text.replace('<br><br><u class="cloze-answer"',
                                '<br><u class="cloze-answer"', 1)
        source = _escaped(example["source"], "example source")
        if aligned:
            # Validate text with the normal field contract, but do not trim or
            # normalize the strings whose exact codepoint offsets are hashed.
            # Plain data spans acquire visible emphasis only during interaction.
            _plain(example["translation"], "example translation")
            translation_text = (example["translation"] if isinstance(example["translation"], str)
                                else _plain(example["translation"], "example translation"))
            translation = _chunk_translation(translation_text, chinese_chunks)
        else:
            translation = _escaped(example["translation"], "example translation")
        rendered_examples.append(
            f'<li class="example-card"><div class="example-heading"><span class="index-tag">{index}</span>'
            + '<span class="example-text">' + text + '</span>'
            + source_jump + '</div>'
            + (f'<span class="example-translation"' + (' data-translation-source="codex"' if aligned else '')
               + f'><span class="translate-tag">{"段落译文" if example.get("translation_scope") == "paragraph" else "翻译"}</span> {translation}</span>' if translation else "")
            + (f'<span class="example-source">{source}</span>' if source else "")
            + '<span class="sentence-status" role="status"></span>'
            + '</li>'
        )
    meta = " ➫ ".join(_escaped(card[key], key) for key in ("sheet", "lesson", "position")
                      if _plain(card[key], key))
    fields = {
        "Word": _escaped(word, "word"),
        "Phonetic": _escaped(card["phonetic"], "phonetic"),
        "Definition": render_senses(_plain(card["definition"], "definition")),
        "SimpleDefinition": render_senses(_plain(card["simple_definition"], "simple_definition")),
        "Level": render_levels(_plain(card["level"], "level")),
        "WordForms": render_forms(_plain(card["word_forms"], "word_forms")),
        "Audio": audio_field,
        "Examples": "".join(rendered_examples),
        "Meta": meta,
        "Note": _escaped(card.get("note", ""), "note"),
    }
    if "local_dictionary" in card:
        fields["Definition"], fields["WordForms"] = _dictionary_markup(card)
        fields["SimpleDefinition"] = ""
    if ecdict is not None:
        fields["Level"] = _ecdict_levels(ecdict)
    frequency = _exam_frequency_markup(card)
    etymology = _etymology_markup(card)
    if frequency:
        # Legacy APKG imports can retain the installed note-type script/CSS.
        # Carry the fixed footer helper in a field shown on both card faces.
        fields["Meta"] += '<script>' + _template("countdown.js") + '</script>'
        # Put the statistics before the meaning heading, including in an
        # installed legacy note type whose CSS/template is retained on import.
        title = "核心释义"
        if "local_dictionary" in card:
            source = card["local_dictionary"].get("definition_source", "oxford")
            title = {"ecdict": "ECDICT 释义（牛津未收录）",
                     "wordbook": "词表释义（牛津未收录）"}.get(source, "牛津释义")
            if source == "reviewed":
                title = card["local_dictionary"]["definition_source_notice"]["heading"]
        fields["Definition"] = (
            '<style>.primary-definition>.field-title{display:none}'
            '.meaning-section>.field-callout{padding:.55rem 0}'
            '.meaning-section>.primary-definition{padding-bottom:.25rem}'
            '.meaning-section>.level-section{padding:.5rem 0}'
            '.primary-definition .sense-row{grid-template-columns:max-content minmax(0,1fr);column-gap:.5rem}'
            '</style>' + frequency
            + '<h3 class="field-title frequency-definition-title" style="color:var(--blue,#215fbb)">'
            + html.escape(title, quote=True) + '</h3>' + fields["Definition"] + etymology)
    elif etymology:
        fields["Definition"] = fields["Definition"] + etymology
    return fields, audio_path, card_id


def _etymology_markup(card: dict) -> str:
    """Keep original cigen DOM and entry controls in an offline sandbox.

    Field-carried styles and the audited size bridge preserve source resources
    while fitting legacy Anki note types, card typography and available width.
    """
    data = card.get("etymology")
    if data is None:
        return ""
    if not isinstance(data, dict) or data.get("schema") != "cigen-etymology.v1":
        raise ValueError("unknown etymology schema")
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValueError("etymology entries must be a list")
    if any(isinstance(entry, dict) and "source_html" in entry for entry in entries):
        from .etymology import original_viewer_document, _PARENT_FRAME_BRIDGE
        if data.get("has_content") is False:
            return ""
        bundle = data.get("original_viewer")
        originals = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("headword"), str):
                raise ValueError("Invalid original cigen entry identity")
            document = original_viewer_document(entry, bundle)
            name = html.escape(entry["headword"], quote=True)
            identifier = html.escape(str(entry.get("id", "")), quote=True)
            digest = html.escape(entry["html_sha256"], quote=True)
            originals.append('<div class="etymology-entry" data-entry-id="' + identifier
                + '" data-headword="' + name + '" data-html-sha256="' + digest + '">'
                '<iframe class="etymology-source-frame" title="' + name + ' 原词根资源" '
                'sandbox="allow-scripts allow-top-navigation-by-user-activation allow-top-navigation-to-custom-protocols" '
                'scrolling="no" style="display:block;width:100%;min-width:0;height:1px;border:0;overflow:hidden;font:inherit;color:inherit" srcdoc="'
                + html.escape(document, quote=True) + '"></iframe></div>')
        return ('<section class="etymology-section" aria-label="词根词缀与词源" '
                'data-schema="cigen-etymology.v1" data-source="cigen" '
                'data-renderer="cigen-original-viewer.v1" style="margin:.55rem 0 0;min-width:0">'
                + ''.join(originals) + '<script data-cigen-frame-bridge="v1">'
                + _PARENT_FRAME_BRIDGE + '</script></section>')
    def source_text(value, label):
        if not isinstance(value, str):
            raise ValueError(f"{label} must be source text")
        return html.escape(value, quote=True)
    def resource_markup(entry):
        from .etymology import _CLASSES, _STATIC_TAGS
        sections = entry.get("resource_sections")
        if entry.get("resource_schema") != "cigen-resource-sections.v1" or not isinstance(sections, list):
            raise ValueError("unknown etymology resource schema")
        allowed_classes = set(_CLASSES.values()) | {"etymology-exam-tag"}
        # Essential presentation travels in Definition for installed legacy
        # note types retained by Anki's default APKG update behavior.
        styles = {
            "etymology-source-section": "margin:.6rem 0 .8rem;min-width:0",
            "etymology-source-heading": "color:var(--blue,#215fbb);font-size:.9rem;font-weight:600;margin:.45rem 0 .3rem",
            "etymology-source-content": "min-width:0;overflow-wrap:anywhere",
            "etymology-tree-parts": "padding:.15rem .4rem",
            "etymology-combination": "margin:.1rem 0;overflow-wrap:anywhere",
            "etymology-root-word": "color:var(--blue,#215fbb);font-weight:600",
            "etymology-affix-word": "color:var(--blue,#215fbb);font-weight:600",
            "etymology-add": "font-style:normal;margin:0 .35rem;color:var(--muted,#63718a)",
            "etymology-affix-list": "list-style:none;padding:0;margin:.3rem 0",
            "etymology-affix": "display:block;margin:.35rem 0;overflow-wrap:anywhere",
            "etymology-affix-label": "color:var(--muted,#63718a);font-size:.8rem;margin-right:.5rem",
            "etymology-related-entry": "margin:.5rem 0;padding:.35rem 0;border-top:1px solid var(--line,#dce4ef)",
            "etymology-related-word": "margin:.2rem 0;font-size:1rem;font-weight:600;color:var(--blue,#215fbb)",
            "etymology-related-translation": "margin:.25rem 0;font-size:.9rem;line-height:1.65",
            "etymology-exam-tag": "display:inline-block;margin-right:.45rem;color:var(--muted,#63718a);font-size:.78rem",
            "etymology-example": "margin:.4rem 0;padding:.25rem .55rem;border-left:2px solid var(--line,#dce4ef)",
            "etymology-example-english": "margin:.15rem 0;font-size:.92rem;line-height:1.65",
            "etymology-example-chinese": "margin:.15rem 0;color:var(--secondary,#47566c);font-size:.85rem;line-height:1.65",
            "etymology-key": "background:var(--purple-soft,#f0e7fa);color:var(--purple,#664197);padding:0 .08em;border-radius:2px;font-weight:600",
        }
        def render_node(node, depth=0):
            if isinstance(node, str):
                return source_text(node, "etymology resource text")
            if depth > 64 or not isinstance(node, dict) or set(node) - {"tag", "classes", "children", "level"}:
                raise ValueError("invalid etymology static node")
            tag, classes, children = node.get("tag"), node.get("classes"), node.get("children")
            if tag not in _STATIC_TAGS or not isinstance(classes, list) \
                    or any(not isinstance(name, str) or name not in allowed_classes for name in classes) \
                    or not isinstance(children, list):
                raise ValueError("invalid etymology static tag/classes/children")
            attributes = ' class="' + ' '.join(classes) + '"' if classes else ''
            presentation = [styles[name] for name in classes if name in styles]
            if "level" in node:
                level = node["level"]
                if "etymology-tree-node" not in classes or (level is not None and (type(level) is not int or level < 0)):
                    raise ValueError("invalid etymology source tree level")
                attributes += f' data-level="{level if level is not None else ""}"'
                presentation.append(f'margin-left:{(level or 0) * .85:g}rem;padding-left:.4rem;'
                                    'border-left:2px solid var(--line,#dce4ef)')
            if presentation:
                attributes += ' style="' + ';'.join(presentation) + '"'
            if tag == "br":
                if children:
                    raise ValueError("etymology line break must have no children")
                return '<br>'
            return '<' + tag + attributes + '>' + ''.join(render_node(child, depth + 1) for child in children) + '</' + tag + '>'
        rendered_sections = []
        for section in sections:
            if not isinstance(section, dict) or set(section) != {"kind", "title", "node"} \
                    or section["kind"] not in {"tree", "affixes", "memory", "derived", "same_root", "other"} \
                    or not isinstance(section["title"], str):
                raise ValueError("invalid etymology source section")
            rendered_sections.append('<div class="etymology-resource" data-kind="' + section["kind"] + '">'
                                     + render_node(section["node"]) + '</div>')
        return ''.join(rendered_sections)
    rendered = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("etymology entry must be structured source data")
        name = source_text(entry.get("headword"), "etymology headword")
        tree, affixes, memory = (entry.get(key) for key in
                                ("etymology_tree", "root_affixes", "root_memory"))
        if any(not isinstance(value, list) for value in (tree, affixes, memory)):
            raise ValueError("etymology tree, affixes and memory must be lists")
        branches = []
        has_structure = False
        for node in tree:
            if not isinstance(node, dict):
                raise ValueError("etymology tree item must be structured")
            level, parts = node.get("level"), node.get("parts")
            if (level is not None and (type(level) is not int or level < 0)) or \
                    not isinstance(parts, list) or any(not isinstance(part, str) for part in parts):
                raise ValueError("invalid etymology tree level or parts")
            text = source_text(node.get("text"), "etymology tree text")
            if (level and text) or len(parts) > 1:
                has_structure = True
            if text:
                indent = (level or 0) * .65
                branches.append(f'<div class="etymology-branch" data-level="{level if level is not None else ""}" '
                    f'style="margin-left:{indent:g}rem;padding:.12rem 0;overflow-wrap:anywhere">{text}</div>')
        descriptions = []
        for affix in affixes:
            if not isinstance(affix, dict):
                raise ValueError("etymology affix item must be structured")
            label = source_text(affix.get("type"), "etymology affix type")
            text = source_text(affix.get("description"), "etymology affix description")
            if text:
                descriptions.append('<div class="etymology-affix" style="margin:.35rem 0;overflow-wrap:anywhere">'
                    f'<span style="color:var(--muted,#63718a);font-size:.8rem;margin-right:.5rem">{label}</span>{text}</div>')
        memories = [source_text(text, "etymology root memory") for text in memory]
        memories = [text for text in memories if text]
        full_resources = "resource_sections" in entry
        if full_resources:
            body = resource_markup(entry)
            if data.get("has_content") is False:
                continue
        elif not (has_structure or descriptions or memories):
            continue
        else:
            body = ''.join(branches) if has_structure else ''
            if body:
                body = ('<div class="etymology-tree" style="margin:.25rem 0 .4rem;'
                        'padding:.35rem .6rem;border-left:2px solid var(--line,#dce4ef)">'
                        '<h4 style="margin:.2rem 0">词源树</h4>' + body + '</div>')
            body += ''.join(descriptions)
            body += ''.join('<p class="etymology-memory" style="margin:.35rem 0;overflow-wrap:anywhere">'
                            + text + '</p>' for text in memories)
        identifier = _escaped(str(entry.get("id", "")), "etymology entry ID")
        digest = source_text(entry.get("html_sha256", ""), "etymology entry hash")
        rendered.append(f'<div class="etymology-entry" data-entry-id="{identifier}" '
            f'data-headword="{name}" data-html-sha256="{digest}">'
            + (f'<h4 style="margin:.4rem 0;font-size:.9rem">{name}</h4>' if len(entries) > 1 else '')
            + body + '</div>')
    if not rendered:
        return ""
    return ('<section class="etymology-section" aria-label="词根词缀" '
            'data-schema="cigen-etymology.v1" data-source="cigen" '
            'style="margin:0 0 .55rem;padding:0 0 .55rem;border-bottom:1px solid var(--line,#dce4ef);'
            'font-size:.9rem;font-weight:400;line-height:1.7;min-width:0">'
            '<h3 class="field-title" style="color:var(--blue,#215fbb)">词根词缀</h3>'
            + ''.join(rendered) + '</section>')


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
                  deck_name: str = "考研英语", deck_identity_name: str | None = None,
                  max_examples: int = 5,
                  before_publish=None) -> dict:
    """Write one .apkg atomically and return export counts and stable IDs.

    A blank audio filename means the source has no recording: export the card
    without a sound tag and count it in ``cards_without_audio``. A nonblank
    filename must name an existing regular file directly inside ``audio_dir``.
    ``max_examples=0`` includes every supplied example.
    ``deck_identity_name`` can preserve deck IDs when changing the displayed
    root name. When omitted, the displayed name remains the ID source.
    """
    if not isinstance(cards, list) or not cards:
        raise ValueError("cards must be a nonempty list")
    if isinstance(max_examples, bool) or not isinstance(max_examples, int) or max_examples < 0:
        raise ValueError("max_examples must be a nonnegative integer")
    deck_name = _plain(deck_name, "deck_name")
    if not deck_name:
        raise ValueError("deck_name must not be blank")
    identity_name = (deck_name if deck_identity_name is None
                     else _plain(deck_identity_name, "deck_identity_name"))
    if not identity_name:
        raise ValueError("deck_identity_name must not be blank")
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
        for name, path in _card_audio_files(card, audio_dir).items():
            if path is not None:
                media[name] = path
        prepared.append((card, fields, card_id))

    model_id = _stable_numeric_id("model", _MODEL_NAME)
    script = f"<script>\n{_template('script.js')}\n{_template('countdown.js')}\n{_template('card-chunks.js')}\n{_template('phonetic-labels.js')}\n{_template('audio-loudness.js')}\n</script>"
    model = genanki.Model(
        model_id, _MODEL_NAME,
        fields=[{"name": name} for name in _FIELD_NAMES],
        templates=[{"name": "Vocabulary", "qfmt": _template("front.html") + script,
                    "afmt": _template("back.html") + script}],
        css=_template("style.css") + "\n" + _template("card-chunks.css") + "\n" + _template("phonetic-labels.css"),
    )
    decks: dict[str, genanki.Deck] = {}
    for due, (source_card, fields, card_id) in enumerate(
            sorted(prepared, key=lambda item: _sort_key(item[0])), start=1):
        full_deck_name = _lesson_deck_name(deck_name, source_card)
        if full_deck_name not in decks:
            full_deck_identity = _lesson_deck_name(identity_name, source_card)
            decks[full_deck_name] = genanki.Deck(_stable_numeric_id("deck", full_deck_identity),
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
        if before_publish is not None:
            before_publish()
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
        "cards_without_audio": sum(not _card_audio_files(card, None) for card, _, _ in prepared),
    }


def render_preview(card: dict, audio_dir: Path | None = None, *, max_examples: int = 5) -> str:
    """Preview both card sides; a zero example limit includes all examples."""
    fields, _, _ = _fields(card, Path(audio_dir) if audio_dir is not None else None,
                            max_examples=max_examples, preview=True)
    front = _render_template(_template("front.html"), fields)
    back = _render_template(_template("back.html"), {**fields, "FrontSide": front})
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Anki 卡片预览</title><style>' + _template("style.css") + '\n' + _template("card-chunks.css") + '\n' + _template("phonetic-labels.css") + '</style></head>'
        '<body><div class="preview-controls"><button id="preview-flip" type="button" '
        'aria-pressed="false" aria-controls="preview-front preview-back">显示答案</button></div>'
        '<section id="preview-front" aria-label="正面预览">' + front + '</section>'
        '<section id="preview-back" aria-label="背面预览" hidden>' + back + '</section>'
        '<script>' + _template("script.js") + '\n' + _template("countdown.js") + '\n' + _template("card-chunks.js") + '\n' + _template("phonetic-labels.js") + '\n' + _template("audio-loudness.js") + '</script></body></html>'
    )
