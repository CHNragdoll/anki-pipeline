"""Lossless legacy APKG -> standard VERSION3 container, without an Anki app.

The collection and media are opaque bytes. Only the container/index changes;
legacy clients receive a separately generated upgrade notice. No source/user
file is removed, and failed operations retain their private partials.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unicodedata
import zipfile

from .study_modern_recompress import (
    CHUNK_BYTES, RecompressionLimits, _BoundedOutput, _Budget, _PinnedSource,
    _copy_encoded, _decode, _identity, _need, _scan_frame, _temp_evidence,
    _verify_owned_temp, _zip_info,
)

_INDEX_BYTES = 64 * 1024**2
_MAX_ENTRIES = 250000


def _fallback_collection():
    """New, private SQLite containing one notice; never opens a user database."""
    import itertools
    import sqlite3
    import genanki
    model = genanki.Model(1792401001, 'Study modern container upgrade notice',
        fields=[{'name':'Notice'}], templates=[{'name':'Upgrade',
            'qfmt':'{{Notice}}', 'afmt':'{{Notice}}'}])
    deck = genanki.Deck(1792401002, 'Anki client upgrade required')
    deck.add_note(genanki.Note(model=model, guid=genanki.guid_for('study-modern-container-upgrade.v1'),
        fields=['请升级 Anki 客户端以导入此牌组。<br>Please update Anki to import this deck.']))
    db = sqlite3.connect(':memory:')
    try:
        genanki.Package(deck).write_to_db(db.cursor(), 1700000000.0, itertools.count(1700000000000))
        db.commit()
        return db.serialize()
    finally:
        db.close()


def _varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128); value >>= 7
    result.append(value)
    return bytes(result)


def _media_entry(name, size, sha1):
    # Official MediaEntries.entries=1; MediaEntry name=1,size=2,sha1=3.
    name = name.encode('utf-8')
    entry = b'\x0a'+_varint(len(name))+name+b'\x10'+_varint(size)+b'\x1a\x14'+sha1
    return b'\x0a'+_varint(len(entry))+entry


def _safe_alias(name):
    _need(type(name) is str and bool(name), 'media aliases must be nonempty strings')
    _need(len(name.encode('utf-8')) <= 255 and unicodedata.normalize('NFC', name) == name and
          not any(ord(c) < 32 or c in '\\/:<>"|?*' for c in name) and not name.endswith((' ', '.')) and
          name not in ('.', '..') and not re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', name),
          'canonical safe media aliases required; aliases cannot be renamed')


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, 'duplicate media map key'); result[key] = value
    return result


def _mapped_media(incoming, budget):
    info = incoming.getinfo('media')
    _need(info.file_size <= min(_INDEX_BYTES, budget.limits.member_raw_bytes), 'media map budget exceeded')
    data = bytearray()
    with incoming.open(info) as stream:
        while block := stream.read(CHUNK_BYTES):
            budget.check(); data.extend(block)
            _need(len(data) <= info.file_size, 'media map exceeds ZIP size')
    _need(len(data) == info.file_size, 'media map ZIP size differs')
    mapping = json.loads(data, object_pairs_hook=_unique_pairs)
    _need(type(mapping) is dict and len(mapping) <= _MAX_ENTRIES and
          all(re.fullmatch(r'0|[1-9][0-9]*', key) for key in mapping), 'invalid media map')
    for name in mapping.values(): _safe_alias(name)
    _need(len(set(mapping.values())) == len(mapping), 'duplicate media aliases')
    budget.check()
    return sorted(mapping.items(), key=lambda pair:int(pair[0]))


def _info(name, size, original=None):
    result = _zip_info(original or zipfile.ZipInfo(name), size)
    result.filename = result.orig_filename = name
    return result


def _emit_frame(reader, size, name, original, outgoing, work, budget, zstd):
    _need(size <= budget.limits.member_raw_bytes, 'member raw budget exceeded')
    fd, path = tempfile.mkstemp(prefix='member-', suffix='.zstd', dir=work)
    path = Path(path); temp = os.fdopen(fd, 'w+b')
    before = _identity(os.fstat(fd))
    try:
        params = zstd.ZstdCompressionParameters.from_level(9, source_size=size,
            window_log=27, threads=0, write_content_size=1, write_checksum=1)
        compressor = zstd.ZstdCompressor(compression_params=params).compressobj(size=size)
        raw_sha, raw_sha1, count = hashlib.sha256(), hashlib.sha1(), 0
        def encoded(data):
            for offset in range(0, len(data), CHUNK_BYTES):
                budget.check(); block = data[offset:offset+CHUNK_BYTES]
                _need(temp.tell()+len(block) <= budget.limits.member_encoded_bytes, 'member encoded budget exceeded')
                _need(temp.write(block) == len(block), 'short compressed member write')
        while raw := reader.read(CHUNK_BYTES):
            budget.check(); count += len(raw)
            _need(count <= size, 'source member exceeds ZIP size')
            raw_sha.update(raw); raw_sha1.update(raw); encoded(compressor.compress(raw))
        _need(count == size, 'source member ZIP size differs')
        encoded(compressor.flush()); del compressor
        temp.flush(); before = _identity(os.fstat(fd)); encoded_size = before[3]
        temp.seek(0); header, encoded_sha = _scan_frame(temp, encoded_size, zstd, budget)
        _need(header.has_checksum and header.content_size == size, 'new frame parameters differ')
        temp.seek(0); restored = _decode(temp, zstd, budget, size, lambda raw:None)
        _need(restored == raw_sha.hexdigest(), 'compressed raw SHA differs')
        temp.seek(0)
        with outgoing.open(_info(name, encoded_size, original), 'w') as target:
            _copy_encoded(temp, target, encoded_sha, encoded_size, budget)
        evidence = _verify_owned_temp(temp, path, before, encoded_sha, budget)
        path.unlink()  # Only this newly created member, while its proven FD remains held.
        result = {'modern_member':name, 'raw_bytes':count, 'raw_sha256':raw_sha.hexdigest(),
            'raw_sha1':raw_sha1.hexdigest(), 'encoded_bytes':encoded_size, 'encoded_sha256':encoded_sha}
        if evidence is not None: result['temp_identity_change'] = evidence
        return result
    except BaseException as error:
        error.add_note('owned member temp identities: '+repr(_temp_evidence(temp, path, before)))
        raise
    finally:
        temp.close()


def convert_legacy_apkg(source, destination, *, expected_source_sha256,
        expected_source_bytes=None, limits=None, callback=None, fallback_collection=None):
    """Convert only the container using level9/window27/one-thread zstd frames.

    Source SHA and six-part file identity are checked before/after. Publication
    is no-clobber; the new partial is retained as the same inode on success.
    Limits/callback guards run between 128KiB IO/codec calls. A guard cannot
    interrupt a native call already running. The fallback is a new upgrade
    notice unless the caller supplies explicit, small SQLite bytes.
    """
    _need(type(expected_source_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_source_sha256),
          'expected_source_sha256 is mandatory')
    _need(expected_source_bytes is None or type(expected_source_bytes) is int and expected_source_bytes >= 0,
          'invalid expected_source_bytes')
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink(): raise FileExistsError(destination)
    _need(source != destination and destination.parent.is_dir(), 'new destination parent required')
    budget = _Budget(limits if limits is not None else RecompressionLimits(), destination.parent)
    budget.check(); work = None
    try:
        with _PinnedSource(source, expected_source_sha256, budget) as pinned:
            if expected_source_bytes is not None:
                _need(pinned.before[3] == expected_source_bytes, 'source byte count differs')
            import zstandard as zstd
            with zipfile.ZipFile(pinned.stream) as incoming:
                infos = incoming.infolist(); names = [item.filename for item in infos]
                _need(len(names) <= _MAX_ENTRIES and len(names) == len(set(names)), 'duplicate/too many ZIP member names')
                _need(not any(item.flag_bits & 1 for item in infos), 'encrypted ZIP members are unsupported')
                _need({'collection.anki2', 'media'}.issubset(names) and
                      not {'meta', 'collection.anki21', 'collection.anki21b'}.intersection(names),
                      'legacy-v4 collection.anki2 input required')
                mapping = _mapped_media(incoming, budget)
                _need(set(key for key, alias in mapping).issubset(names), 'mapped media member missing')
                reserved = {'collection.anki2', 'media'} | {key for key, alias in mapping}
                extras = [item for item in infos if item.filename not in reserved]
                _need(not any(re.fullmatch('[0-9]+', item.filename) for item in extras), 'unmapped numeric ZIP member')
                _need(all(incoming.getinfo(key).file_size <= 0xffffffff for key, alias in mapping), 'media exceeds protobuf uint32 size')
                fallback = _fallback_collection() if fallback_collection is None else fallback_collection
                _need(type(fallback) is bytes and 16 <= len(fallback) <= min(1024**2,
                      budget.limits.member_raw_bytes, budget.limits.member_encoded_bytes) and
                      fallback.startswith(b'SQLite format 3\x00'), 'small SQLite fallback bytes required')
                work = Path(tempfile.mkdtemp(prefix=destination.name+'.convert-', dir=destination.parent))
                partial = work/'package.partial'; frame_count = 0; ledger = hashlib.sha256()
                def record(value, kind, old):
                    nonlocal frame_count
                    frame_count += 1
                    value.update(kind=kind, source_member=old)
                    ledger.update(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()+b'\n')
                    if callback: callback({'phase':'frame', **value})
                with partial.open('x+b') as physical:
                    owned = _identity(os.fstat(physical.fileno()))
                    with zipfile.ZipFile(_BoundedOutput(physical, budget), 'w', compression=zipfile.ZIP_STORED,
                                         allowZip64=True) as outgoing:
                        outgoing.comment = incoming.comment
                        outgoing.writestr(_info('meta', 2), b'\x08\x03')  # PackageMetadata.VERSION_LATEST=3.
                        original = incoming.getinfo('collection.anki2')
                        with incoming.open(original) as reader:
                            collection = _emit_frame(reader, original.file_size, 'collection.anki21b', original, outgoing, work, budget, zstd)
                        record(collection, 'collection', 'collection.anki2')
                        with outgoing.open(_info('collection.anki2', len(fallback)), 'w') as target:
                            _copy_encoded(io.BytesIO(fallback), target, hashlib.sha256(fallback).hexdigest(), len(fallback), budget)
                        index = bytearray()
                        for number, (old, alias) in enumerate(mapping):
                            original = incoming.getinfo(old)
                            with incoming.open(original) as reader:
                                value = _emit_frame(reader, original.file_size, str(number), original, outgoing, work, budget, zstd)
                            entry = _media_entry(alias, value['raw_bytes'], bytes.fromhex(value['raw_sha1']))
                            _need(len(index)+len(entry) <= _INDEX_BYTES, 'modern media index budget exceeded')
                            index.extend(entry); value['alias'] = alias; record(value, 'media', old)
                        media_index = _emit_frame(io.BytesIO(index), len(index), 'media', None, outgoing, work, budget, zstd)
                        record(media_index, 'media-index', 'media')
                        for original in extras:
                            _need(original.file_size <= min(budget.limits.member_raw_bytes,
                                  budget.limits.member_encoded_bytes), 'extra member budget exceeded')
                            with incoming.open(original) as reader, outgoing.open(_info(original.filename, original.file_size, original), 'w') as target:
                                _copy_encoded(reader, target, None, original.file_size, budget)
                    physical.flush(); os.fsync(physical.fileno())
                    complete = _identity(os.fstat(physical.fileno()))
                    _need(owned[:2] == complete[:2] and complete == _identity(partial.lstat()), 'owned partial identity changed')
                    physical.seek(0); output_sha = _copy_encoded(physical, None, None, complete[3], budget)
                    if callback: callback({'phase':'ready_to_publish', 'frame_count':frame_count, 'output_bytes':complete[3]})
                    pinned.verify(rehash=True); budget.check()
                    _need(complete == _identity(os.fstat(physical.fileno())) == _identity(partial.lstat()), 'completed partial changed')
                    os.link(partial, destination, follow_symlinks=False)
                    _need(complete[:5] == _identity(os.fstat(physical.fileno()))[:5] ==
                          _identity(partial.lstat())[:5] == _identity(destination.lstat())[:5], 'published partial identity changed')
                    directory = os.open(destination.parent, os.O_RDONLY)
                    try: os.fsync(directory)
                    finally: os.close(directory)
            return {'schema':'study-modern-conversion.v1', 'status':'COMPLETE', 'source':str(source),
                'source_sha256':expected_source_sha256, 'source_bytes':pinned.before[3],
                'source_identity_before':list(pinned.before), 'source_identity_after':list(pinned.before),
                'source_identity_sha256_unchanged':True, 'destination':str(destination),
                'output_bytes':complete[3], 'output_sha256':output_sha, 'work_directory':str(work),
                'retained_partial':str(partial), 'retained_partial_same_inode':True,
                'media_count':len(mapping), 'extra_count':len(extras), 'frame_count':frame_count,
                'collection':collection, 'media_index':media_index, 'member_checks_sha256':ledger.hexdigest(),
                'fallback_bytes':len(fallback), 'fallback_sha256':hashlib.sha256(fallback).hexdigest(),
                'level':9, 'window_log':27, 'threads':0, 'write_checksum':True, 'write_content_size':True,
                'zstandard_version':zstd.__version__, 'zstd_version':list(zstd.ZSTD_VERSION),
                'peak_rss_bytes':budget.peak_rss, 'elapsed_seconds':time.monotonic()-budget.started}
    except BaseException as error:
        if work is not None: error.add_note('Conversion partials retained in '+str(work))
        raise
