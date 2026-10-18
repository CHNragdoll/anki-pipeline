"""Lossless native carriers: dictionary v1 and exact streaming bundles.

Only the static JavaScript representation changes. Its synchronous register()
call receives the original text, so the host retains its original asset SHA and
all semantic validation. This module neither authenticates semantic inputs nor
changes their JSON serialization. It is deliberately separate from projection.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import re
import stat
from typing import AbstractSet, Hashable, Iterator, Mapping, TypedDict
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
_CARRIER_ALIAS = re.compile(r'_study_native_([a-f0-9]{64})\.js')
_BUNDLE_SIZE_LIMIT = 8 * 1024 * 1024
_BUNDLE_COUNT_LIMIT = 256
_STREAM_CHUNK_SIZE = 1024 * 1024


def _file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class _NativeCarrierSource:
    alias: str
    path: Path
    size: int
    sha256: str
    identity: tuple[int, ...] = field(repr=False)


def _check_source(member: _NativeCarrierSource) -> None:
    try:
        info = member.path.lstat()
    except OSError as exc:
        raise ValueError(f'native carrier source unavailable: {member.alias}') from exc
    if not stat.S_ISREG(info.st_mode) or _file_identity(info) != member.identity:
        raise ValueError(f'native carrier source changed or is not regular: {member.alias}')


def _iter_source_chunks(member: _NativeCarrierSource, chunk_size: int) -> Iterator[bytes]:
    """Read one pinned regular file; complete validation requires exhaustion."""
    _check_source(member)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    try:
        descriptor = os.open(member.path, flags)
    except OSError as exc:
        raise ValueError(f'native carrier source could not be opened: {member.alias}') from exc
    digest, size = hashlib.sha256(), 0
    with os.fdopen(descriptor, 'rb') as source:
        if _file_identity(os.fstat(source.fileno())) != member.identity:
            raise ValueError(f'native carrier source changed while opening: {member.alias}')
        while chunk := source.read(chunk_size):
            size += len(chunk)
            if size > member.size:
                raise ValueError(f'native carrier source size changed: {member.alias}')
            digest.update(chunk)
            yield chunk
        if (_file_identity(os.fstat(source.fileno())) != member.identity or
                size != member.size or digest.hexdigest() != member.sha256):
            raise ValueError(f'native carrier source changed or SHA-256 mismatch: {member.alias}')
    _check_source(member)


@dataclass(frozen=True)
class NativeCarrierBundle:
    """An immutable plan for exact concatenation, without creating a new file.

    iter_chunks() authenticates every source again. Consumers must exhaust it
    and handle failures transactionally: an invalid source can be detected after
    a prefix has been yielded. This class never writes or deletes any source.
    The caller supplies canonical, independently executable register programs;
    this physical transport helper does not parse or authenticate JavaScript.
    """
    members: tuple[_NativeCarrierSource, ...]
    size: int
    sha256: str

    @property
    def alias(self) -> str:
        return '_study_native_' + self.sha256 + '.js'

    def iter_chunks(self, chunk_size: int = _STREAM_CHUNK_SIZE) -> Iterator[bytes]:
        if type(chunk_size) is not int or chunk_size <= 0:
            raise ValueError('native carrier chunk_size must be a positive integer')
        digest, size = hashlib.sha256(), 0
        for member in self.members:
            for chunk in _iter_source_chunks(member, chunk_size):
                digest.update(chunk)
                size += len(chunk)
                yield chunk
        if size != self.size or digest.hexdigest() != self.sha256:
            raise ValueError('native carrier bundle size or SHA-256 mismatch')
        for member in self.members:
            _check_source(member)


class _NativeCarrierPlan(TypedDict):
    media: dict[str, Path | NativeCarrierBundle]
    media_pins: dict[str, str]
    replacements: dict[str, str]


def plan_native_carrier_bundles(media: dict[str, Path], pins: dict[str, str], *,
        consumers: Mapping[str, AbstractSet[Hashable] | None] | None = None) -> _NativeCarrierPlan:
    """Pin inputs and group carriers with identical nonempty consumer sets.

    Only _study_native_<raw SHA-256>.js files at most 8 MiB are eligible;
    each group is at most 8 MiB and 256 members. Consumers are opaque stable
    identities (including loading stages), supplied from all logical uses before
    readdressing or media deduplication. Thus a profile already needs every
    member of each bundle it references; no unrelated profile payload is added.
    The caller must merge every use and mark any unknown physical usage as None.
    Unknown/missing/empty usage, oversized singletons and other media retain their Path.
    Alias order determines groups within each cohort, independently of consumer
    map/set order. No aggregate payload or physical bundle is staged. Output
    pins remain alias -> raw SHA-256, including bundle hashes.
    All source identities and complete member hashes are checked during this
    call; bundle streaming repeats those checks immediately before packaging.
    """
    if set(media) != set(pins):
        raise ValueError('native carrier media and SHA-256 pins must have identical keys')
    sources = []
    for alias in sorted(media):
        path, pin = media[alias], pins[alias]
        if (not isinstance(path, Path) or not isinstance(pin, str) or
                re.fullmatch(r'[a-f0-9]{64}', pin) is None):
            raise ValueError(f'native carrier requires a Path and raw SHA-256: {alias}')
        match = _CARRIER_ALIAS.fullmatch(alias)
        if match is not None and match[1] != pin:
            raise ValueError(f'native carrier filename and raw SHA-256 disagree: {alias}')
        try:
            info = path.lstat()
        except OSError as exc:
            raise ValueError(f'native carrier source unavailable: {alias}') from exc
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f'native carrier source must be regular without symlinks: {alias}')
        sources.append(_NativeCarrierSource(alias, path, info.st_size, pin, _file_identity(info)))

    usage = {alias: frozenset(users or ()) for alias, users in (consumers or {}).items()}
    output, output_pins, replacements = {}, {}, {}
    cohorts = {}

    def finish(members: list[_NativeCarrierSource]) -> None:
        digest = hashlib.sha256()
        for member in members:
            for chunk in _iter_source_chunks(member, _STREAM_CHUNK_SIZE):
                digest.update(chunk)
        if len(members) == 1:
            member = members[0]
            output[member.alias], output_pins[member.alias] = member.path, member.sha256
            return
        bundle = NativeCarrierBundle(tuple(members), sum(m.size for m in members), digest.hexdigest())
        if bundle.alias in media or bundle.alias in output:
            raise ValueError(f'native carrier bundle alias collision: {bundle.alias}')
        output[bundle.alias], output_pins[bundle.alias] = bundle, bundle.sha256
        replacements.update((member.alias, bundle.alias) for member in members)

    for member in sources:
        users = usage.get(member.alias)
        if (not users or _CARRIER_ALIAS.fullmatch(member.alias) is None or
                member.size > _BUNDLE_SIZE_LIMIT):
            finish([member])
            continue
        cohorts.setdefault(users, []).append(member)
    for members in cohorts.values():
        pending, pending_size = [], 0
        for member in members:
            if pending and (pending_size + member.size > _BUNDLE_SIZE_LIMIT or
                            len(pending) >= _BUNDLE_COUNT_LIMIT):
                finish(pending)
                pending, pending_size = [], 0
            pending.append(member)
            pending_size += member.size
        if pending:
            finish(pending)
    for member in sources:
        _check_source(member)
    return {'media': dict(sorted(output.items())), 'media_pins': dict(sorted(output_pins.items())),
            'replacements': dict(sorted(replacements.items()))}


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
