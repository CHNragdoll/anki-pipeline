"""Repack pinned ZIP/APKG transport without recompressing unchanged members.

This module knows no collection, media-manifest or card semantics. It copies
whole unchanged local records (including optional data descriptors), and asks
the standard library to compress replacements and rebuild the central index.
Source and replacement paths are read only. A newly created partial destination
is deliberately retained on failure; no path is ever unlinked or overwritten.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import zipfile


_CHUNK = 1024 * 1024
_SHA256 = re.compile(r'[a-f0-9]{64}')


def _stamp(info):
    # Reading may change atime; content/identity checks must exclude it.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _assert_unchanged(stream, path, before, label):
    try:
        named = path.stat(follow_symlinks=False)
        current = os.fstat(stream.fileno())
    except OSError as error:
        raise ValueError(label + ' changed while repacking') from error
    if _stamp(current) != before or _stamp(named) != before:
        raise ValueError(label + ' changed while repacking')


@contextmanager
def _regular_file(path, label):
    named = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(named.st_mode):
        raise ValueError(label + ' must be a regular file, not a symlink')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    # Prevent a concurrent FIFO substitution from blocking open on POSIX.
    flags |= getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        before = _stamp(os.fstat(stream.fileno()))
        _assert_unchanged(stream, path, before, label)
        if before != _stamp(named) or not stat.S_ISREG(before[2]):
            raise ValueError(label + ' changed while opening')
        yield stream, before


def _copy_range(source, destination, start, size):
    source.seek(start)
    remaining = size
    while remaining:
        block = source.read(min(_CHUNK, remaining))
        if not block:
            raise ValueError('source record was truncated while repacking')
        destination.write(block)
        remaining -= len(block)


def _check_filename_roundtrip(archive, entries):
    """Use the 3.11/3.13 stdlib's encoder/header layout without serializing ZIP.

    3.11 changes CP437 non-ASCII names to UTF-8; 3.13 clears UTF-8 on ASCII
    names. Exclude both from the portable input contract. Also compare the
    actual encoder result and source local header before any output is created.
    """
    for entry in entries:
        utf8 = bool(entry.flag_bits & 0x800)
        if (entry.filename.isascii() and utf8) or (not entry.filename.isascii() and not utf8):
            raise ValueError('source ZIP filename encoding unsupported: require ASCII without UTF-8 flag '
                             'or non-ASCII with UTF-8 flag')
        source_name = entry.orig_filename.encode('utf-8' if utf8 else 'cp437')
        encoded, flags = entry._encodeFilenameFlags()
        if encoded != source_name or flags != entry.flag_bits:
            raise ValueError('source ZIP filename encoding unsupported: name or flags cannot roundtrip')
        archive.fp.seek(entry.header_offset)
        raw = archive.fp.read(zipfile.sizeFileHeader)
        if len(raw) != zipfile.sizeFileHeader:
            raise ValueError('source ZIP local filename header is truncated')
        header = struct.unpack(zipfile.structFileHeader, raw)
        if (header[zipfile._FH_SIGNATURE] != zipfile.stringFileHeader or
                header[zipfile._FH_GENERAL_PURPOSE_FLAG_BITS] != entry.flag_bits or
                archive.fp.read(header[zipfile._FH_FILENAME_LENGTH]) != source_name):
            raise ValueError('source ZIP local filename or flags differ from its central directory')


def _layout(archive, source_size):
    entries = archive.infolist()
    if len({entry.filename for entry in entries}) != len(entries):
        raise ValueError('source ZIP member names must be unique; duplicate member found')
    physical = sorted(entries, key=lambda entry: entry.header_offset)
    offsets = [entry.header_offset for entry in physical] + [archive.start_dir]
    if (not 0 <= archive.start_dir <= source_size or
            any(start < 0 or end - start < 30 for start, end in zip(offsets, offsets[1:]))):
        raise ValueError('source ZIP local record boundaries are invalid')
    _check_filename_roundtrip(archive, physical)
    return physical, offsets


def _append_raw_record(archive, source, entry, end):
    """Minimal ZipFile write-state bridge, exercised on CPython 3.11 and 3.13.

    ZipFile has no public API for already compressed records. Its standard
    close() uses filelist/NameToInfo and start_dir to emit all central offsets
    and ZIP64 end records. No compression or ZIP serialization is copied here.
    The private fp/_didModify wiring is confined to this function (and prefix
    positioning below); replacements use ZipFile.open's normal writer.
    """
    target = copy.copy(entry)
    archive.fp.seek(archive.start_dir)
    target.header_offset = archive.fp.tell()
    _copy_range(source, archive.fp, entry.header_offset, end - entry.header_offset)
    archive.filelist.append(target)
    archive.NameToInfo[target.filename] = target
    archive.start_dir = archive.fp.tell()
    archive._didModify = True


def _replacement_info(entry, size):
    target = copy.copy(entry)
    target.compress_type = zipfile.ZIP_DEFLATED
    target.file_size = size
    # _compresslevel remains the 3.11-compatible alias in 3.13. Remove stale
    # size/offset extra fields; ZipFile creates any needed new ZIP64 metadata.
    target._compresslevel = 9
    strip_extra = zipfile._Extra.strip if hasattr(zipfile, '_Extra') else zipfile._strip_extra
    target.extra = strip_extra(target.extra, (1,))
    return target


def _write_replacement(archive, entry, value):
    if isinstance(value, bytes):
        archive.writestr(_replacement_info(entry, len(value)), value,
                         compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        return
    with _regular_file(value, 'replacement') as (source, before):
        with archive.open(_replacement_info(entry, before[3]), 'w') as target:
            _copy_range(source, target, 0, before[3])
        _assert_unchanged(source, value, before, 'replacement')


def repack_apkg(source, destination, replacements: dict[str, bytes | Path], *, expected_source_sha256):
    """Create a new ZIP, preserving every unselected local record byte for byte.

    The caller supplies an independently obtained SHA-256 for a regular source
    file that remains unchanged during the operation. Each replacement names an
    existing unique member and supplies immutable bytes or a read-only Path.
    Member names must be ASCII without the UTF-8 flag, or non-ASCII with it;
    the stdlib encoder and source local headers must preserve name bytes/flags.
    Replacements are standard deflate level 9. The destination must not exist.
    Once exclusive creation succeeds, a failure retains that incomplete file;
    callers must treat only a returned receipt as successful completion.
    """
    if not isinstance(expected_source_sha256, str) or not _SHA256.fullmatch(expected_source_sha256):
        raise ValueError('an explicit lowercase source sha256 pin is required')
    if (not isinstance(replacements, dict) or
            any(not isinstance(name, str) or not isinstance(value, (bytes, Path))
                for name, value in replacements.items())):
        raise ValueError('replacements must map existing member names to bytes or Path values')
    replacements = dict(replacements)
    source, destination = Path(source), Path(destination)
    copied_bytes = 0
    with _regular_file(source, 'source') as (original, before):
        digest = hashlib.sha256()
        while block := original.read(_CHUNK):
            digest.update(block)
        source_sha256 = digest.hexdigest()
        _assert_unchanged(original, source, before, 'source')
        if source_sha256 != expected_source_sha256:
            raise ValueError('source SHA-256 differs from the external pin')
        with zipfile.ZipFile(original) as incoming:
            physical, offsets = _layout(incoming, before[3])
            if not replacements.keys() <= incoming.NameToInfo.keys():
                raise ValueError('replacements may only name existing source members')
            _assert_unchanged(original, source, before, 'source')
            with destination.open('xb') as output:
                owned = os.fstat(output.fileno())
                with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                                     compresslevel=9, allowZip64=True) as outgoing:
                    prefix_size = offsets[0]
                    if prefix_size:
                        _copy_range(original, output, 0, prefix_size)
                        outgoing.start_dir = output.tell()
                    outgoing.comment = incoming.comment
                    for entry, end in zip(physical, offsets[1:]):
                        if entry.filename in replacements:
                            _write_replacement(outgoing, entry, replacements[entry.filename])
                        else:
                            _append_raw_record(outgoing, original, entry, end)
                            copied_bytes += end - entry.header_offset
                    # Preserve central-directory order even if it differs from
                    # physical local-record order in the input archive.
                    outgoing.filelist[:] = [outgoing.NameToInfo[entry.filename] for entry in incoming.infolist()]
                output.flush()
                os.fsync(output.fileno())
                _assert_unchanged(original, source, before, 'source')
                named = destination.stat(follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (owned.st_dev, owned.st_ino):
                    raise ValueError('destination path changed while repacking')
                destination_size = os.fstat(output.fileno()).st_size
    return {'schema': 'study-apkg-repack-receipt.v1', 'source_sha256': source_sha256,
            'source_bytes': before[3], 'destination_bytes': destination_size,
            'copied_members': len(physical) - len(replacements), 'replaced_members': len(replacements),
            'copied_record_bytes': copied_bytes, 'preserved_prefix_bytes': prefix_size}
