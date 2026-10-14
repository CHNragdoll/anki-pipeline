"""Lossless shared-string factoring for the offline APKG media transport.

Tokens are complete original HTML tags/text nodes or JSON quoted literals.
The tokenizer never normalizes whitespace, escapes, Unicode or source markup.
Production callers retain the original full-string SHA and validate restoration.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
import json
import re
from types import MappingProxyType

DICTIONARY_SCHEMA = 'anki-slim-shared-dictionary.v1'
PACKED_SCHEMA = 'anki-slim-shared-strings.v1'
DEFAULT_DICTIONARY_BYTES = 4 * 1024 * 1024
MAX_SAFE_INTEGER = (1 << 53) - 1
_HTML = re.compile(r'<[^>]*>|[^<]+|<', re.S)
_JSON = re.compile(r'"(?:\\.|[^"\\])*"|[^"\\]+|["\\]', re.S)


class SharedDictionary(tuple):
    """Immutable validated strings and a reusable token-to-index mapping.

    It is a tuple subclass so json.dumps serializes it as a regular JSON array.
    Duplicate entries are rejected to keep factoring deterministic.
    """

    def __new__(cls, strings: Iterable[str]):
        values = tuple(strings)
        if any(not isinstance(value, str) for value in values):
            raise ValueError('shared dictionary entries must be strings')
        if len(set(values)) != len(values):
            raise ValueError('shared dictionary entries must be unique')
        instance = super().__new__(cls, values)
        object.__setattr__(instance, '_indices', MappingProxyType({value: n for n, value in enumerate(values)}))
        return instance

    @property
    def indices(self) -> Mapping[str, int]:
        return self._indices

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError('shared dictionary is immutable')

    def __reduce__(self):
        # Rebuild the validated index once when a spawn-based worker receives
        # the immutable strings; MappingProxyType itself is not picklable.
        return type(self), (tuple(self),)


def prepare_dictionary(strings: Sequence[str]) -> SharedDictionary:
    if isinstance(strings, SharedDictionary):
        return strings
    if isinstance(strings, (str, bytes)) or not isinstance(strings, Sequence):
        raise ValueError('shared dictionary must be an array of strings')
    return SharedDictionary(strings)


def tokenize(raw: str) -> tuple[str, ...]:
    if not isinstance(raw, str):
        raise ValueError('source literal must be a string')
    expression = _HTML if raw.lstrip().startswith('<') else _JSON
    tokens = tuple(expression.findall(raw))
    if ''.join(tokens) != raw:
        raise ValueError('tokenizer did not preserve the exact original string')
    return tokens


def dictionary_json(strings: Sequence[str]) -> str:
    dictionary = prepare_dictionary(strings)
    return json.dumps({'schema': DICTIONARY_SCHEMA, 'strings': dictionary},
                      ensure_ascii=False, separators=(',', ':'))


def fit(
    sources: Iterable[str] | Callable[[], Iterable[str]],
    max_dictionary_bytes: int = DEFAULT_DICTIONARY_BYTES,
    *, strategy: str = 'frequency', max_token_bytes: int | None = None,
) -> SharedDictionary:
    """Fit a deterministic shared dictionary without retaining source strings.

    A factory can reopen the stream for the caller's later factoring pass.
    Budget includes the exact UTF-8 JSON envelope, quoted strings and commas.
    The conservative reference cost is six bytes, matching the agreed probe.
    Frequency prioritizes repeated tags, JSON keys and small structural tokens.
    Optional density/score strategies and token caps support bounded comparison
    experiments without changing the exact factoring/restoration contract.
    """
    if isinstance(max_dictionary_bytes, bool) or not isinstance(max_dictionary_bytes, int) or max_dictionary_bytes < 0:
        raise ValueError('dictionary byte budget must be a nonnegative integer')
    if strategy == 'freq':
        strategy = 'frequency'
    if strategy not in ('density', 'frequency', 'score'):
        raise ValueError('dictionary strategy must be density, frequency or score')
    if max_token_bytes is not None and (isinstance(max_token_bytes, bool) or not isinstance(max_token_bytes, int) or max_token_bytes <= 0):
        raise ValueError('maximum token bytes must be a positive integer or None')
    overhead = len(dictionary_json(()).encode('utf-8'))
    if max_dictionary_bytes < overhead:
        raise ValueError('dictionary byte budget cannot fit its JSON envelope')
    frequency: Counter[str] = Counter()
    stream = sources() if callable(sources) else sources
    if isinstance(stream, (str, bytes)):
        raise ValueError('source stream must contain complete literal strings')
    for raw in stream:
        tokens = tokenize(raw)
        frequency.update(token for token in tokens if max_token_bytes is None or len(token) <= max_token_bytes)
    candidates = []
    for token, count in frequency.items():
        if count < 2:
            continue
        raw_bytes = len(token.encode('utf-8'))
        if max_token_bytes is not None and raw_bytes > max_token_bytes:
            continue
        score = (raw_bytes - 6) * (count - 1)
        # Even very short JSON structure/end tags are worth sharing in the
        # measured frequency route. Score filtering would drop those tokens.
        if score > 0 or strategy == 'frequency':
            wire_bytes = len(json.dumps(token, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
            candidates.append((token, count, score, wire_bytes))
    if strategy == 'density':
        candidates.sort(key=lambda row: (-row[2] / (row[3] + 1), -row[1], row[0]))
    elif strategy == 'frequency':
        candidates.sort(key=lambda row: (-row[1], row[0]))
    else:
        candidates.sort(key=lambda row: (-row[2], -row[1], row[0]))
    selected = []
    used = overhead
    for token, _count, _score, wire_bytes in candidates:
        cost = wire_bytes + bool(selected)
        if used + cost > max_dictionary_bytes:
            continue
        selected.append(token)
        used += cost
    result = SharedDictionary(selected)
    if len(dictionary_json(result).encode('utf-8')) != used or used > max_dictionary_bytes:
        raise ValueError('shared dictionary exceeded its exact byte budget')
    return result


def factor(raw: str, dictionary: Sequence[str], index: Mapping[str, int] | None = None) -> list[int | str]:
    """Replace dictionary tokens with integers, joining adjacent raw literals."""
    strings = prepare_dictionary(dictionary)
    lookup = strings.indices if index is None else index
    if not isinstance(lookup, Mapping):
        raise ValueError('prepared dictionary index must be a mapping')
    pieces: list[int | str] = []
    literals: list[str] = []

    def flush() -> None:
        if literals:
            pieces.append(''.join(literals))
            literals.clear()

    for token in tokenize(raw):
        value = lookup.get(token)
        if value is None:
            literals.append(token)
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > MAX_SAFE_INTEGER or value >= len(strings) or strings[value] != token:
            raise ValueError('prepared dictionary index conflicts with its strings')
        flush()
        pieces.append(value)
    flush()
    return pieces


def expand(pieces: Sequence[int | str], dictionary: Sequence[str]) -> str:
    """Restore exact source bytes after strict types and reference bounds checks."""
    strings = prepare_dictionary(dictionary)
    if isinstance(pieces, (str, bytes)) or not isinstance(pieces, Sequence):
        raise ValueError('shared pieces must be an array')
    restored = []
    for piece in pieces:
        if isinstance(piece, str):
            restored.append(piece)
        elif not isinstance(piece, bool) and isinstance(piece, int) and 0 <= piece <= MAX_SAFE_INTEGER and piece < len(strings):
            restored.append(strings[piece])
        else:
            raise ValueError('shared pieces contain an invalid dictionary reference or type')
    return ''.join(restored)
