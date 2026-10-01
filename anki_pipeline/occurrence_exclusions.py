"""Source-pinned homograph corrections; never remove a dictionary form globally."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def printed_text_map(value: str):
    """Normalize print spacing, retaining each code point's original range."""
    tokens = []
    for match in re.finditer(r'\s+|\S', value):
        char = ' ' if match[0].isspace() else match[0]
        if char in '.,;:!?' and tokens and tokens[-1][0] == ' ':
            tokens.pop()
        tokens.append((char, (match.start(), match.end())))
    while tokens and tokens[0][0] == ' ':
        tokens.pop(0)
    while tokens and tokens[-1][0] == ' ':
        tokens.pop()
    return ''.join(char for char, _ in tokens), [span for _, span in tokens]


def canonical_owner_key(pin, alias, sentences):
    owner_pin = pin.get('canonicalOwner')
    if owner_pin is None:
        return None
    if not isinstance(owner_pin, dict) or owner_pin.get('sentenceId') not in sentences:
        raise ValueError('Occurrence exclusion canonical owner is missing')
    owner = sentences[owner_pin['sentenceId']]
    span = owner_pin.get('en')
    context = alias.get('context', {})
    if (context.get('coverageStatus') != 'covered_by_paragraph' or
            context.get('translationRef') != owner.get('paragraphId') or
            owner['paperId'] != alias['paperId'] or
            not alias.get('sourceBlockIds') or
            set(alias['sourceBlockIds']) != set(owner.get('sourceBlockIds', [])) or
            owner_pin.get('englishHash') != hashlib.sha256(owner['english'].encode()).hexdigest() or
            owner_pin.get('sourceHash') != owner.get('sourceHash') or
            not isinstance(span, list) or len(span) != 2 or
            any(type(n) is not int for n in span) or
            not 0 <= span[0] < span[1] <= len(owner['english']) or
            owner['english'][span[0]:span[1]] != pin['form'] or
            (span[0] and re.match(r'\w', owner['english'][span[0]-1])) or
            (span[1] < len(owner['english']) and re.match(r'\w', owner['english'][span[1]]))):
        raise ValueError('Occurrence exclusion canonical owner has stale identity or range')
    alias_text, alias_map = printed_text_map(alias['filledEnglish'])
    owner_text, owner_map = printed_text_map(owner['filledEnglish'])
    if not alias_text or owner_text.count(alias_text) != 1:
        raise ValueError('Occurrence exclusion alias is not one exact physical paragraph')
    absolute = [alias['start'] + pin['en'][0], alias['start'] + pin['en'][1]]
    indices = [n for n, (start, end) in enumerate(alias_map)
               if absolute[0] <= start and end <= absolute[1]]
    if (not indices or indices != list(range(indices[0], indices[-1] + 1)) or
            alias_map[indices[0]][0] != absolute[0] or
            alias_map[indices[-1]][1] != absolute[1]):
        raise ValueError('Occurrence exclusion alias range cannot be mapped exactly')
    shift = owner_text.index(alias_text)
    expected = [owner_map[shift + indices[0]][0] - owner['start'],
                owner_map[shift + indices[-1]][1] - owner['start']]
    if span != expected:
        raise ValueError('Occurrence exclusion canonical owner points at another occurrence')
    return (owner['id'], pin['cardId'], *span)


def load_occurrence_exclusions(path: Path, sentences: list[dict], cards: list[dict]):
    if not path.exists():
        return {}, {}, None
    raw = path.read_bytes()
    payload = json.loads(raw)
    if (payload.get('schema') != 'codex-anki-occurrence-exclusions.v1' or
            payload.get('rangeUnit') != 'sentence-codepoints' or
            not isinstance(payload.get('exclusions'), list)):
        raise ValueError('Invalid occurrence exclusion schema')
    by_sentence = {row['id']: row for row in sentences}
    by_card = {row['id']: row for row in cards}
    result, aliases = {}, {}
    for row in payload['exclusions']:
        if not isinstance(row, dict):
            raise ValueError('Invalid occurrence exclusion row')
        sid, cid, span = row.get('sentenceId'), row.get('cardId'), row.get('en')
        if (not isinstance(sid, str) or sid not in by_sentence or
                not isinstance(cid, str) or cid not in by_card or
                not isinstance(span, list) or len(span) != 2 or
                any(type(offset) is not int for offset in span)):
            raise ValueError('Occurrence exclusion has a missing identity or invalid range')
        sentence = by_sentence[sid]
        english = sentence['english']
        start, end = span
        if (row.get('paperId') != sentence['paperId'] or
                row.get('englishHash') != hashlib.sha256(english.encode()).hexdigest() or
                row.get('sourceHash') != sentence.get('sourceHash') or
                not isinstance(row.get('sourceHash'), str) or
                not re.fullmatch(r'[0-9a-f]{64}', row['sourceHash']) or
                not 0 <= start < end <= len(english) or
                not isinstance(row.get('form'), str) or english[start:end] != row['form'] or
                row.get('word') != by_card[cid]['word'] or
                not isinstance(row.get('reason'), str) or not row['reason'].strip() or
                (start and re.match(r'\w', english[start-1])) or
                (end < len(english) and re.match(r'\w', english[end]))):
            raise ValueError(f'Occurrence exclusion no longer matches reviewed source: {sid}')
        key = (sid, cid, start, end)
        if key in result:
            raise ValueError('Duplicate occurrence exclusion')
        result[key] = row['reason']
        owner_key = canonical_owner_key(row, sentence, by_sentence)
        if owner_key is not None:
            aliases.setdefault(owner_key, set()).add(key)
    return result, aliases, hashlib.sha256(raw).hexdigest()
