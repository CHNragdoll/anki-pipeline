"""One explicit inflection set for sentence selection and target highlighting.

Dictionary builds consume their already selected Webster or ECDICT forms.
Raw ECDICT exchange/lemma relations and derived words are never match aliases.
The caller still supplies the card's own lemma to ``word_variants``.
"""
from __future__ import annotations

import re
import unicodedata

from .forms import explicit_forms
from .text import word_variants


_INFLECTION_KINDS = frozenset({
    "plural", "third_person_singular", "present_participle", "past",
    "past_participle", "comparative", "superlative",
})
_SINGLE_TOKEN = re.compile(r"[a-z]+(?:[-'][a-z]+)*\Z")


def _token(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def card_match_forms(card: dict) -> set[str]:
    """Return validated, single-token inflections without changing the card.

    When ``local_dictionary`` exists, its nonempty forms array is authoritative;
    there is no union with old wordbook forms or a second provider. An earlier
    fallback step may set ``forms_source='ecdict'`` only when Webster has none.
    A row with an explicit ``base`` must belong to this card's own lemma or
    declared title spelling. A parent entry cannot turn ``means`` into matches
    for ``mean``, ``meaning`` or ``meant``. Missing ownership metadata remains
    valid for explicit ECDICT forms; empty or malformed ownership is excluded.
    """
    if "local_dictionary" not in card:
        return {_token(value) for value in explicit_forms(card.get("word_forms", ""))}
    local = card["local_dictionary"]
    if not isinstance(local, dict):
        raise ValueError("local_dictionary must be a dictionary for matching")
    source = local.get("forms_source", "webster")
    rows = local.get("forms", [])
    if not isinstance(rows, list):
        raise ValueError("dictionary match forms must be a list")
    if source == "" and not rows:
        return set()
    if source not in {"webster", "ecdict"}:
        raise ValueError("unknown dictionary forms source for matching")
    owners = word_variants(card.get("word", ""), infer=False)
    forms = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("dictionary match form must be a dictionary")
        kind, raw = row.get("kind"), row.get("form")
        if not isinstance(raw, str):
            raise ValueError("dictionary match form must contain text")
        if "base" in row:
            base = row["base"]
            if not isinstance(base, str) or _token(base) not in owners:
                continue
        form = _token(raw)
        if not isinstance(kind, str) or not _SINGLE_TOKEN.fullmatch(form):
            continue
        if kind in _INFLECTION_KINDS or kind == "base" and form in owners:
            forms.add(form)
    return forms
