"""Render sense previews with the card renderer's existing bilingual chunks.

Only the complete, hash-pinned source alignment can create interactive spans.
The complete authored target chunk and its translations keep a default accent;
the target token retains its own mark. No word-matching rule guesses Chinese
correspondences. The existing ``card-chunks.js`` handles hover/tap emphasis.
"""
from __future__ import annotations

import re

from .packaging import _chunk_translation, _example_chunk_ranges, _highlight_example, _annotate_sentence_chunks


def _target_chunk_ids(chunks: list[tuple[int, int, int]], target: tuple[int, int]) -> set[int]:
    """Pick authored ranges, never shorten a chunk to the target word."""
    exact = [span for span in chunks if span[:2] == target]
    containing = [span for span in chunks if span[0] <= target[0] and target[1] <= span[1]]
    candidates = exact or containing
    if candidates:
        shortest = min(right - left for left, right, _ in candidates)
        return {identity for left, right, identity in candidates if right - left == shortest}
    # A target crossing an authored boundary keeps both complete original
    # chunks. Implicit/untranslated entries are absent from ``chunks``.
    return {identity for left, right, identity in chunks
            if left < target[1] and target[0] < right}


def _accent_chunks(fragment: str, chosen: set[int]) -> str:
    # Match only markup emitted by the shared renderer. Source text is escaped
    # before this step; it can neither inject tags nor change chunk IDs.
    pattern = r'(<span class=")card-chunk(" data-chunk-side="(?:en|zh)" data-chunk-ids="([0-9 ]+)">)'

    def accent(match: re.Match[str]) -> str:
        active = chosen.intersection(int(identity) for identity in match[3].split())
        return match[1] + ('card-chunk sf-target-chunk' if active else 'card-chunk') + match[2]

    return re.sub(pattern, accent, fragment)


def render_sentence_pair(row: dict) -> str:
    """Return exact English/Chinese paragraphs with validated authored chunk IDs.

    ``alignment`` uses ``codex-sentence-alignment.v1`` with the complete existing
    ``alignments`` array and both original text hashes. Missing legacy alignment
    yields readable plain text, rather than invented bilingual correspondences.
    A supplied stale or malformed alignment fails instead of silently drifting.
    Default bilingual emphasis covers complete existing chunks, with the target
    word marked separately inside its English chunk.
    All offsets use Unicode codepoints into the exact source strings.
    """
    display = row.get("display")
    if display is not None:
        from .sense_display import validate_display
        view = validate_display(display, row)
    else:
        view = row
    english, translation = view.get("english"), view.get("translation")
    if not isinstance(english, str) or not isinstance(translation, str):
        raise ValueError("sense preview English and translation must be strings")
    if "\x00" in english or "\x00" in translation:
        raise ValueError("sense preview strings must not contain null characters")
    target = view.get("target_range")
    if (not isinstance(target, (list, tuple)) or len(target) != 2 or
            any(type(offset) is not int for offset in target) or
            not 0 <= target[0] < target[1] <= len(english)):
        raise ValueError("sense preview target must be an exact Unicode codepoint range")

    example = {"text": english, "translation": translation}
    if view.get("alignment") is not None:
        example.update(translation_source="codex", translation_alignment=view["alignment"])
    en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
    selected = _target_chunk_ids(en_chunks, tuple(target))
    en_html = _highlight_example(
        english, "", "", view.get("cloze_answers", []), target_ranges=[tuple(target)],
        chunk_ranges=en_chunks, preserve_source=True,
    )
    zh_html = _chunk_translation(translation, zh_chunks)
    en_html, zh_html = _accent_chunks(en_html, selected), _accent_chunks(zh_html, selected)
    en_html = _annotate_sentence_chunks(en_html, view.get('alignment'))
    zh_html = _annotate_sentence_chunks(zh_html, view.get('alignment'))
    # The existing delegated runtime scopes activation to its nearest example.
    # This wrapper prevents identical chunk IDs in other occurrences interacting.
    return ('<div class="sf-sentence-pair example-card">'
            f'<p class="sf-en">{en_html}</p>'
            f'<p class="sf-zh">{zh_html}</p></div>')
