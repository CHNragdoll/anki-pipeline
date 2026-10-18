"""Lossless native carrier transport; dictionary wire format v1.

Only the static JavaScript representation changes. Its synchronous register()
call receives the original text, so the host retains its original asset SHA and
all semantic validation. This module neither authenticates semantic inputs nor
changes their JSON serialization. It is deliberately separate from projection.
"""
from __future__ import annotations

import hashlib
import json
import re
import zlib


PACK_PREFIX = '(function(v){var d=v[1];window.StudyCompiledNative.register(v[0],v[2].map(function(p){return typeof p==="string"?p:d[p];}).join(""));})('
PACK_END = ');'
_LITERAL_PREFIX = 'window.StudyCompiledNative.register('
_MIN_LEAF_CHARS = 1024
_MAX_JSON_BYTES = 256 * 1024 * 1024
_MAX_VISITED_VALUES = 1_000_000
_MAX_LEAF_VALUES = 16_384
_MAX_LEAF_CHARS = 256 * 1024 * 1024
_MAX_CANDIDATES = 512
_MAX_DICTIONARY = 256
_MAX_PARTS = 20_000
_MIN_DEFLATE_SAVING = 128


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')


def _leaf_candidates(value):
    """Return a bounded, deterministic pool, or None to leave transport alone."""
    stack, candidates = [value], set()
    visited = leaves = chars = 0
    while stack:
        item = stack.pop()
        visited += 1
        if visited > _MAX_VISITED_VALUES:
            return None
        if isinstance(item, str) and len(item) >= _MIN_LEAF_CHARS:
            # These are exact candidate substrings of the original JSON text;
            # alternate source escape spelling is never normalized or rewritten.
            candidate = json.dumps(item, ensure_ascii=False, separators=(',', ':'))[1:-1]
            leaves += 1
            chars += len(candidate)
            if leaves > _MAX_LEAF_VALUES or chars > _MAX_LEAF_CHARS:
                return None
            candidates.add(candidate)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return sorted(candidates, key=lambda item: (-len(item), item))[:_MAX_CANDIDATES]


def _dictionary_parts(text, candidates):
    dictionary, parts = [], [text]
    for candidate in candidates:
        matches = sum(part.count(candidate) for part in parts if isinstance(part, str))
        if matches < 2:
            continue
        if len(dictionary) >= _MAX_DICTIONARY:
            break
        # Bound allocations before split(), including adversarial repetition.
        # This conservative upper bound may decline a useful optimization; it
        # always preserves the exact literal carrier as the fallback.
        if len(parts) + 2 * matches > _MAX_PARTS:
            return None
        index, replaced = len(dictionary), []
        for part in parts:
            if not isinstance(part, str) or candidate not in part:
                replaced.append(part)
                continue
            for offset, segment in enumerate(part.split(candidate)):
                if offset:
                    replaced.append(index)
                if segment:
                    replaced.append(segment)
        dictionary.append(candidate)
        parts = replaced
    if not dictionary:
        return None
    restored = ''.join(part if isinstance(part, str) else dictionary[part] for part in parts)
    if restored != text:
        return None
    return dictionary, parts


def _deflate_size(raw):
    """The raw DEFLATE9 stream used for ZIP members, without retaining it."""
    encoder = zlib.compressobj(9, zlib.DEFLATED, -15)
    view, total = memoryview(raw), 0
    for at in range(0, len(view), 1024 * 1024):
        total += len(encoder.compress(view[at:at + 1024 * 1024]))
    return total + len(encoder.flush())


def build_native_carrier(pin: str, text: str) -> bytes:
    """Carry exact UTF-8 text; use a local dictionary only for proven ZIP gain.

    Non-JSON, exhausted analysis budgets, absent repetition and savings below
    128 raw DEFLATE9 bytes all retain the byte-identical old literal format.
    The packed payload is exactly [pin, dictionary, parts]; parts contain only
    literal strings or zero-based dictionary indices. No client branch, codec,
    new dependency load or additional runtime content hash is introduced.
    """
    if (not isinstance(pin, str) or re.fullmatch(r'[a-f0-9]{64}', pin) is None or
            not isinstance(text, str)):
        raise ValueError('native carrier requires the exact UTF-8 SHA-256')
    source = text.encode('utf-8')
    if hashlib.sha256(source).hexdigest() != pin:
        raise ValueError('native carrier requires the exact UTF-8 SHA-256')
    literal = (_LITERAL_PREFIX + _encoded(pin) + ',' + _encoded(text) + ');').encode('utf-8')
    if len(source) > _MAX_JSON_BYTES:
        return literal
    del source
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return literal
    candidates = _leaf_candidates(value)
    del value
    if not candidates:
        return literal
    result = _dictionary_parts(text, candidates)
    if result is None:
        return literal
    dictionary, parts = result
    packed = (PACK_PREFIX + _encoded([pin, dictionary, parts]) + PACK_END).encode('utf-8')
    if _deflate_size(literal) - _deflate_size(packed) < _MIN_DEFLATE_SAVING:
        return literal
    return packed
