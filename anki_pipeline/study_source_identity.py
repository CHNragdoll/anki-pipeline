"""Explicit source identities for the shared semantic record pipeline.

The historical ``kaoyan:YYYY-NN`` identity is intentionally kept unchanged.
Other corpora use an authored namespace and source proof; display labels never
decide which exam, book, article or year a physical occurrence belongs to.
"""
from __future__ import annotations

import re
from collections.abc import Mapping


_KAOYAN = re.compile(r'kaoyan:(\d{4})-(\d{2})')
_STUDY = re.compile(r'study:([a-z][a-z0-9_-]{0,63}):([A-Za-z0-9][A-Za-z0-9._-]{0,255})')
_KINDS = frozenset({'exam', 'book', 'article', 'lesson', 'other'})


def validate_source_identity(paper_id: str, sentence_id: str,
                             source_provenance: Mapping | None) -> int:
    """Validate source membership and return its explicit year, or internal 0.

    ``0`` represents an explicitly undated new source and must be presented with
    :func:`year_label`. This function does not mutate a record or add fields to
    a legacy payload, so its existing snapshot and review hashes remain valid.
    It validates declared identity, not the truth of a reviewer's source claim.
    """
    if not isinstance(paper_id, str) or not isinstance(sentence_id, str):
        raise ValueError('source and sentence identities must be text')
    legacy = _KAOYAN.fullmatch(paper_id)
    if legacy:
        if not sentence_id.startswith(paper_id + ':'):
            raise ValueError('sentence must belong to its declared kaoyan paper')
        return int(legacy[1])

    identity = _STUDY.fullmatch(paper_id)
    if identity is None or identity[1] == 'kaoyan':
        raise ValueError('source must use a declared study namespace or canonical kaoyan paper')
    prefix = paper_id + ':'
    if not sentence_id.startswith(prefix) or not sentence_id[len(prefix):].strip():
        raise ValueError('sentence must belong to its declared study source')
    proof = source_provenance.get('study_source') if isinstance(source_provenance, Mapping) else None
    if not isinstance(proof, Mapping) or proof.get('schema') != 'study-source.v1':
        raise ValueError('study source identity requires explicit study-source.v1 provenance')
    if proof.get('id') != paper_id or proof.get('namespace') != identity[1]:
        raise ValueError('study source provenance differs from its declared identity or namespace')
    if not isinstance(proof.get('kind'), str) or proof['kind'] not in _KINDS:
        raise ValueError('study source kind must be exam, book, article, lesson or other')
    for key in ('label', 'locator'):
        if not isinstance(proof.get(key), str) or not proof[key].strip():
            raise ValueError(f'study source {key} must be nonempty text')
    if 'year' not in proof:
        raise ValueError('study source year must be explicitly supplied or null')
    year = proof['year']
    if year is not None and (type(year) is not int or not 1 <= year <= 9999):
        raise ValueError('study source year must be an integer from 1 to 9999 or null')
    return year if year is not None else 0


def year_label(year: int) -> str:
    """Keep the internal undated sentinel out of user-facing year labels."""
    if type(year) is not int:
        raise ValueError('normalized source year must be an integer')
    return '未注明年份' if year == 0 else str(year)
