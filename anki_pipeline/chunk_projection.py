"""Reuse reviewed bilingual chunks in a derived display without guessing pairs.

Source offsets address exact Unicode code points. A changed display accepts a
chunk only when its existing English fragment and every Chinese fragment occur
uniquely and unchanged. A separately reviewed complete bilingual context may
also expose an explicitly labelled sentence-level correspondence.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
import hashlib
import re

from .translation_alignment import validate_translation_alignment


SENTENCE_FALLBACK_NOTE = '整句对应：沿用已审校双语全文，不表示新增词语级对齐。'


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _project_range(source: str, span: list[int], display: str) -> list[int] | None:
    if source == display:
        return list(span)
    fragment = source[slice(*span)]
    positions = [match.start() for match in re.finditer('(?=' + re.escape(fragment) + ')', display)]
    if len(positions) != 1:
        return None
    return [positions[0], positions[0] + len(fragment)]


def project_reviewed_chunks(english: str, translation: str, sources: Iterable[Mapping], *,
                            sentence_fallback: bool = False) -> dict:
    """Return current exact hashes and confirmed source chunks, without mutation.

    Each source has ``english``, ``translation`` and an optional complete
    ``alignment`` payload. Supplied payloads always undergo full validation;
    stale or malformed ranges cannot quietly become a sentence fallback.

    Set ``sentence_fallback`` only when the complete displayed bilingual text
    is already reviewed or assembled from reviewed question/candidate texts.
    This creates one explicitly noted whole-context pair. It does not claim
    newly authored word-level alignment, and finer existing chunks take
    priority in the shared card renderer.
    """
    if not isinstance(sources, Iterable) or isinstance(sources, (str, bytes, Mapping)):
        raise ValueError('Chunk sources must be an iterable of bilingual source mappings')
    entries, conflicts = {}, set()
    for source in sources:
        if not isinstance(source, Mapping):
            raise ValueError('A chunk source must be a bilingual source mapping')
        alignment = source.get('alignment')
        if alignment is None:
            continue
        original_en, original_zh = source.get('english'), source.get('translation')
        validate_translation_alignment(original_en, original_zh, alignment)
        for entry in alignment['alignments']:
            if entry['relation'] != 'equivalent':
                continue
            en = _project_range(original_en, entry['en'], english)
            zh = [_project_range(original_zh, span, translation) for span in entry['zh']]
            if en is None or any(span is None for span in zh):
                continue
            projected = {**deepcopy(entry), 'en': en, 'zh': zh}
            key = tuple(en)
            if key in entries and entries[key] != projected:
                conflicts.add(key)
            else:
                entries[key] = projected
    projected = [entry for key, entry in sorted(entries.items()) if key not in conflicts]
    whole = [0, len(english)]
    if sentence_fallback and not any(entry['en'] == whole for entry in projected):
        projected.append({'en': whole, 'zh': [[0, len(translation)]], 'relation': 'equivalent',
                          'note': SENTENCE_FALLBACK_NOTE})
    payload = {'schema': 'codex-sentence-alignment.v1', 'englishHash': _sha(english),
               'translationHash': _sha(translation), 'alignments': projected}
    validate_translation_alignment(english, translation, payload)
    return payload
