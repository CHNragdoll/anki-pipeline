"""Lossless, streaming frame recompression of VERSION3 modern APKG containers.

Only zstd representations change. SQLite and media protobuf bytes are opaque.
The optional zstandard dependency is imported only when recompression is called.
Failure retains this operation's private work directory; existing paths are never
removed. Successful publication retains its own partial as the same inode.
"""
from __future__ import annotations

import copy
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile

CHUNK_BYTES = 128 * 1024


@dataclass(frozen=True)
class RecompressionLimits:
    wall_seconds: float = 7200
    rss_bytes: int = 512 * 1024**2
    free_bytes: int = 1024**3
    output_bytes: int = 8 * 1024**3
    member_encoded_bytes: int = 2 * 1024**3
    member_raw_bytes: int = 8 * 1024**3


def _need(value, message):
    if not value:
        raise ValueError(message)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


class _Budget:
    def __init__(self, limits, directory):
        _need(isinstance(limits, RecompressionLimits), 'explicit RecompressionLimits required')
        _need(type(limits.wall_seconds) in (int, float) and math.isfinite(limits.wall_seconds)
              and limits.wall_seconds > 0, 'positive finite wall budget required')
        for name in ('rss_bytes', 'free_bytes', 'output_bytes', 'member_encoded_bytes', 'member_raw_bytes'):
            value = getattr(limits, name)
            _need(type(value) is int and value >= (0 if name == 'free_bytes' else 1), 'invalid '+name+' budget')
        self.limits, self.directory, self.started = limits, directory, time.monotonic()
        self.peak_rss = 0

    def check(self):
        import resource
        elapsed = time.monotonic() - self.started
        if elapsed > self.limits.wall_seconds:
            raise TimeoutError('modern recompression wall budget exceeded')
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss *= 1 if sys.platform == 'darwin' else 1024
        self.peak_rss = max(self.peak_rss, rss)
        _need(rss <= self.limits.rss_bytes, 'modern recompression RSS budget exceeded')
        _need(shutil.disk_usage(self.directory).free >= self.limits.free_bytes,
              'modern recompression free-space floor reached')


class _PinnedSource:
    def __init__(self, path, expected, budget):
        self.path, self.expected, self.budget = path, expected, budget

    def __enter__(self):
        named = self.path.lstat()
        _need(stat.S_ISREG(named.st_mode), 'source must be a regular nonsymlink file')
        self.stream = os.fdopen(os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb')
        try:
            self.before = _identity(os.fstat(self.stream.fileno()))
            _need(self.before == _identity(named), 'source changed while opening')
            self.verify(rehash=True)
            return self
        except BaseException:
            self.stream.close()
            raise

    def verify(self, *, rehash=False):
        _need(_identity(self.path.lstat()) == self.before == _identity(os.fstat(self.stream.fileno())),
              'source identity changed')
        if rehash:
            self.stream.seek(0); digest = hashlib.sha256()
            while block := self.stream.read(CHUNK_BYTES):
                self.budget.check(); digest.update(block)
            _need(digest.hexdigest() == self.expected, 'source SHA256 differs')
            self.verify()

    def __exit__(self, *args):
        self.stream.close()


def _version3(raw):
    """Read only PackageMetadata's version tag; preserve all original bytes."""
    cursor, versions = 0, []
    def varint():
        nonlocal cursor
        value = 0
        for shift in range(0, 70, 7):
            _need(cursor < len(raw), 'truncated modern metadata')
            byte = raw[cursor]; cursor += 1; value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError('invalid modern metadata varint')
    while cursor < len(raw):
        tag = varint(); field, wire = tag >> 3, tag & 7
        _need(field > 0, 'invalid modern metadata field')
        if wire == 0:
            value = varint()
            if field == 1: versions.append(value)
        elif wire in (1, 5):
            cursor += 8 if wire == 1 else 4
        elif wire == 2:
            size = varint(); cursor += size
        else:
            raise ValueError('unsupported modern metadata wire type')
        _need(cursor <= len(raw), 'truncated modern metadata field')
    _need(versions == [3], 'modern APKG VERSION3 metadata required')


def _scan_frame(stream, encoded_size, zstd, budget):
    """Check one complete standard frame, including its checksum's presence.

    stream_reader alone silently accepts some truncated checksums. This small
    framing scan skips opaque blocks; all decoding/checksum validation remains
    with zstandard. It also rejects concatenated frames and trailing bytes.
    """
    digest, count = hashlib.sha256(), 0
    def exact(size):
        nonlocal count
        parts = bytearray()
        while size:
            budget.check(); block = stream.read(min(CHUNK_BYTES, size))
            _need(block, 'truncated zstd frame')
            digest.update(block); count += len(block); parts.extend(block); size -= len(block)
        return bytes(parts)
    first = exact(5)
    header = first + exact(zstd.frame_header_size(first) - 5)
    params = zstd.get_frame_parameters(header)
    _need(params.content_size not in (zstd.CONTENTSIZE_UNKNOWN, zstd.CONTENTSIZE_ERROR),
          'zstd frame must declare its content size')
    _need(params.content_size <= budget.limits.member_raw_bytes, 'member raw budget exceeded')
    _need(encoded_size <= budget.limits.member_encoded_bytes, 'member encoded budget exceeded')
    _need(params.dict_id == 0 and params.window_size <= 1 << 27, 'unsupported zstd dictionary/window')
    while True:
        block = int.from_bytes(exact(3), 'little'); kind, size = (block >> 1) & 3, block >> 3
        _need(kind != 3, 'reserved zstd block type')
        remaining = 1 if kind == 1 else size
        while remaining:
            take = min(CHUNK_BYTES, remaining); exact(take); remaining -= take
        if block & 1: break
    if params.has_checksum: exact(4)
    _need(not stream.read(1) and count == encoded_size, 'zstd member must contain exactly one complete frame')
    return params, digest.hexdigest()


def _decode(stream, zstd, budget, expected, consume):
    digest, count = hashlib.sha256(), 0
    with zstd.ZstdDecompressor(max_window_size=1 << 27).stream_reader(
            stream, read_size=CHUNK_BYTES, closefd=False) as reader:
        while raw := reader.read(CHUNK_BYTES):
            budget.check(); count += len(raw)
            _need(count <= expected, 'decoded member exceeds declared content size')
            digest.update(raw); consume(raw)
    _need(count == expected, 'decoded member differs from declared content size')
    budget.check()
    return digest.hexdigest()


def _zip_info(info, size):
    result = copy.copy(info); result.compress_type = zipfile.ZIP_STORED; result.file_size = size
    # ZIP64 sizes belong to the new member; stdlib writes the correct new ones.
    extra, kept, cursor = info.extra, bytearray(), 0
    while cursor < len(extra):
        _need(cursor + 4 <= len(extra), 'malformed ZIP extra field')
        tag = int.from_bytes(extra[cursor:cursor+2], 'little')
        length = int.from_bytes(extra[cursor+2:cursor+4], 'little'); end = cursor + 4 + length
        _need(end <= len(extra), 'malformed ZIP extra field length')
        if tag != 1: kept.extend(extra[cursor:end])
        cursor = end
    result.extra = bytes(kept)
    return result


class _BoundedOutput:
    def __init__(self, stream, budget): self.stream, self.budget = stream, budget
    def write(self, raw):
        self.budget.check()
        _need(self.stream.tell() + len(raw) <= self.budget.limits.output_bytes, 'output byte budget exceeded')
        return self.stream.write(raw)
    def __getattr__(self, key): return getattr(self.stream, key)


def _copy_encoded(stream, target, expected_sha, size, budget):
    digest, count = hashlib.sha256(), 0
    while block := stream.read(CHUNK_BYTES):
        budget.check(); count += len(block)
        _need(count <= size, 'encoded copy length differs')
        digest.update(block)
        if target is not None:
            _need(target.write(block) == len(block), 'short encoded member copy')
    _need(count == size, 'encoded copy length differs')
    actual = digest.hexdigest()
    _need(expected_sha is None or actual == expected_sha, 'encoded copy SHA differs')
    return actual


def _temp_evidence(stream, path, before):
    try: named = list(_identity(path.lstat()))
    except OSError: named = None
    return {'before':list(before), 'fd_after':list(_identity(os.fstat(stream.fileno()))),
            'path_after':named}


def _verify_owned_temp(stream, path, before, encoded_sha, budget):
    """Only a newly owned, still-open temp may requalify ctime-only drift.

    Both the copied representation and, on metadata drift, its current held-FD
    bytes are verified. This does not relax any pinned input/output identity.
    """
    evidence = _temp_evidence(stream, path, before)
    def same_owned_file():
        return (evidence['path_after'] is not None and
                list(before[:5]) == evidence['fd_after'][:5] == evidence['path_after'][:5])
    _need(same_owned_file(), 'owned frame temp identity changed')
    changed = not (list(before) == evidence['fd_after'] == evidence['path_after'])
    if changed:
        proof_before = _identity(os.fstat(stream.fileno()))
        stream.seek(0); _copy_encoded(stream, None, encoded_sha, before[3], budget)
        evidence = _temp_evidence(stream, path, before)
        _need(same_owned_file(), 'owned frame temp identity changed')
        _need(list(proof_before) == evidence['fd_after'] == evidence['path_after'],
              'owned frame temp changed during SHA requalification')
        evidence['encoded_sha256_verified'] = True
        evidence['encoded_sha256'] = encoded_sha
        return evidence
    return None


def recompress_modern_apkg(source, destination, *, expected_source_sha256,
        level=19, window_log=27, limits=None, callback=None,
        prefix=None, expected_prefix_sha256=None):
    """Recompress only modern zstd payloads; retain an original frame unless smaller.

    Limits default to 512MiB process peak RSS and a 1GiB live free-space floor.
    Guards run between bounded IO/codec calls, not inside a running native call.
    A callback receives per-frame records and a ready-to-publish summary before
    final source revalidation. No original/user path is ever removed. On failure
    the new work directory is retained. Failures before linking leave the
    destination absent; a failed post-link check retains paths and never
    reports success. An optional existing prefix ZIP is read-only and requires
    its full SHA pin. Every prefix payload is authenticated against the source;
    only strictly smaller, matching frames bypass compression. The prefix and
    original source retain their strict six-part identity/full-SHA protection.
    """
    _need(type(expected_source_sha256) is str and re.fullmatch('[a-f0-9]{64}', expected_source_sha256),
          'expected_source_sha256 is mandatory')
    _need(type(level) is int and 1 <= level <= 22 and type(window_log) is int and 10 <= window_log <= 27,
          'invalid zstd level/window')
    _need((prefix is None and expected_prefix_sha256 is None) or
          (prefix is not None and type(expected_prefix_sha256) is str and
           re.fullmatch('[a-f0-9]{64}', expected_prefix_sha256)),
          'prefix requires expected_prefix_sha256')
    source, destination = Path(source).absolute(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink(): raise FileExistsError(destination)
    _need(destination.parent.is_dir() and source != destination, 'new destination parent required')
    budget = _Budget(limits if limits is not None else RecompressionLimits(), destination.parent)
    budget.check(); work = None
    try:
        with _PinnedSource(source, expected_source_sha256, budget) as pinned, ExitStack() as resources:
            import zstandard as zstd
            with zipfile.ZipFile(pinned.stream) as incoming:
                entries = incoming.infolist(); names = [info.filename for info in entries]
                budget.check()
                _need(len(names) == len(set(names)), 'duplicate ZIP member names')
                _need(not any(info.flag_bits & 1 for info in entries), 'encrypted ZIP members are unsupported')
                _need('meta' in names and 'collection.anki21b' in names and 'media' in names, 'incomplete modern APKG')
                _need(incoming.getinfo('meta').file_size <= 64*1024, 'modern metadata budget exceeded')
                _version3(incoming.read('meta'))
                prefix_pinned, prefix_zip, prefix_infos = None, None, {}
                if prefix is not None:
                    prefix = Path(prefix).absolute()
                    prefix_pinned = resources.enter_context(_PinnedSource(prefix, expected_prefix_sha256, budget))
                    prefix_zip = resources.enter_context(zipfile.ZipFile(prefix_pinned.stream))
                    previous = prefix_zip.infolist(); previous_names = [item.filename for item in previous]
                    _need(len(previous_names) == len(set(previous_names)), 'duplicate prefix ZIP member names')
                    _need(not any(item.flag_bits & 1 for item in previous), 'encrypted prefix ZIP members are unsupported')
                    _need(previous_names == names[:len(previous_names)], 'prefix ZIP names differ from source prefix')
                    prefix_infos = {item.filename:item for item in previous}
                work = Path(tempfile.mkdtemp(prefix=destination.name+'.recompress-', dir=destination.parent))
                partial = work/'package.partial'; frames = []
                with partial.open('xb') as physical:
                    owned_output = os.fstat(physical.fileno())
                    with zipfile.ZipFile(_BoundedOutput(physical, budget), 'w', compression=zipfile.ZIP_STORED,
                                         allowZip64=True) as outgoing:
                        outgoing.comment = incoming.comment
                        for info in entries:
                            budget.check()
                            _need(info.file_size <= budget.limits.member_encoded_bytes, 'member encoded budget exceeded')
                            framed = info.filename in ('collection.anki21b', 'media') or re.fullmatch('[0-9]+', info.filename)
                            temp = None
                            if framed:
                                with incoming.open(info) as stream:
                                    header, encoded_sha = _scan_frame(stream, info.file_size, zstd, budget)
                                if info.filename in prefix_infos:
                                    candidate = prefix_infos[info.filename]
                                    with incoming.open(info) as stream:
                                        raw_sha = _decode(stream, zstd, budget, header.content_size, lambda raw:None)
                                    with prefix_zip.open(candidate) as stream:
                                        previous_header, previous_sha = _scan_frame(stream, candidate.file_size, zstd, budget)
                                    _need(previous_header.content_size == header.content_size, 'prefix content size differs')
                                    with prefix_zip.open(candidate) as stream:
                                        previous_raw = _decode(stream, zstd, budget, header.content_size, lambda raw:None)
                                    _need(previous_raw == raw_sha, 'prefix raw SHA differs')
                                    if candidate.file_size < info.file_size:
                                        _need(previous_header.has_checksum and previous_header.window_size <= 1 << window_log,
                                              'prefix frame parameters differ')
                                        with prefix_zip.open(candidate) as stream, outgoing.open(_zip_info(info, candidate.file_size), 'w') as target:
                                            _copy_encoded(stream, target, previous_sha, candidate.file_size, budget)
                                        record = {'name':info.filename, 'raw_bytes':header.content_size, 'raw_sha256':raw_sha,
                                            'original_encoded_bytes':info.file_size, 'original_encoded_sha256':encoded_sha,
                                            'trial_encoded_bytes':candidate.file_size, 'output_encoded_bytes':candidate.file_size,
                                            'output_encoded_sha256':previous_sha, 'retained_original':False, 'reused_prefix':True}
                                        frames.append(record)
                                        if callback: callback({'phase':'frame', **record})
                                        continue
                                fd, name = tempfile.mkstemp(prefix='frame-', suffix='.zstd', dir=work); temp_path = Path(name)
                                temp = os.fdopen(fd, 'w+b')
                                temp_identity = _identity(os.fstat(temp.fileno()))
                                try:
                                    params = zstd.ZstdCompressionParameters.from_level(level, source_size=header.content_size,
                                        window_log=window_log, threads=0, write_content_size=1, write_checksum=1)
                                    compressor = zstd.ZstdCompressor(compression_params=params).compressobj(size=header.content_size)
                                    def encoded(raw):
                                        for offset in range(0, len(raw), CHUNK_BYTES):
                                            budget.check(); block = raw[offset:offset+CHUNK_BYTES]
                                            _need(temp.tell()+len(block) <= budget.limits.member_encoded_bytes, 'member encoded budget exceeded')
                                            _need(temp.write(block) == len(block), 'short compressed member write')
                                    with incoming.open(info) as stream:
                                        raw_sha = _decode(stream, zstd, budget, header.content_size,
                                                          lambda raw: encoded(compressor.compress(raw)))
                                    encoded(compressor.flush()); temp.flush()
                                    temp_identity = _identity(os.fstat(temp.fileno())); new_size = temp_identity[3]
                                    temp.seek(0); new_header, new_sha = _scan_frame(temp, new_size, zstd, budget)
                                    _need(new_header.has_checksum and new_header.content_size == header.content_size,
                                          'new zstd frame parameters differ')
                                    temp.seek(0); restored_sha = _decode(temp, zstd, budget, header.content_size, lambda raw: None)
                                    _need(restored_sha == raw_sha, 'recompressed raw SHA differs')
                                    retain = new_size >= info.file_size
                                    size = info.file_size if retain else new_size
                                    with outgoing.open(_zip_info(info, size), 'w') as target:
                                        if retain:
                                            with incoming.open(info) as stream:
                                                _copy_encoded(stream, target, encoded_sha, size, budget)
                                        else:
                                            temp.seek(0)
                                            _copy_encoded(temp, target, new_sha, size, budget)
                                    metadata_change = _verify_owned_temp(temp, temp_path, temp_identity, new_sha, budget)
                                    temp_path.unlink()  # Only this completed member's exclusively created temp.
                                    temp.close(); temp = None
                                    record = {'name':info.filename, 'raw_bytes':header.content_size, 'raw_sha256':raw_sha,
                                        'original_encoded_bytes':info.file_size, 'original_encoded_sha256':encoded_sha,
                                        'trial_encoded_bytes':new_size, 'output_encoded_bytes':size,
                                        'output_encoded_sha256':encoded_sha if retain else new_sha, 'retained_original':retain}
                                    if metadata_change is not None: record['temp_identity_change'] = metadata_change
                                    frames.append(record)
                                    if callback: callback({'phase':'frame', **record})
                                except BaseException as error:
                                    if temp is not None:
                                        error.add_note('owned frame temp identities: '+repr(_temp_evidence(temp, temp_path, temp_identity)))
                                    raise
                                finally:
                                    if temp is not None: temp.close()  # Failure retains its owned temp path.
                            else:
                                with incoming.open(info) as stream, outgoing.open(_zip_info(info, info.file_size), 'w') as target:
                                    opaque_sha = _copy_encoded(stream, target, None, info.file_size, budget)
                                if info.filename in prefix_infos:
                                    candidate = prefix_infos[info.filename]
                                    _need(candidate.file_size == info.file_size, 'prefix opaque member size differs')
                                    with prefix_zip.open(candidate) as stream:
                                        _copy_encoded(stream, None, opaque_sha, info.file_size, budget)
                    physical.flush(); os.fsync(physical.fileno())
                    output_identity = _identity(os.fstat(physical.fileno()))
                    _need((owned_output.st_dev, owned_output.st_ino) ==
                          output_identity[:2] and output_identity == _identity(partial.lstat()),
                          'owned partial identity changed')
            with os.fdopen(os.open(partial, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as completed:
                _need(output_identity == _identity(os.fstat(completed.fileno())),
                      'completed partial differs from owned output')
                output_digest = hashlib.sha256()
                while block := completed.read(CHUNK_BYTES):
                    budget.check(); output_digest.update(block)
                _need(output_identity == _identity(os.fstat(completed.fileno())) == _identity(partial.lstat()),
                      'completed partial changed during SHA verification')
            report = {'schema':'study-modern-recompression.v1', 'source':str(source), 'destination':str(destination),
                'source_sha256':expected_source_sha256, 'source_bytes':pinned.before[3],
                'source_identity_before':list(pinned.before), 'frame_count':len(frames),
                'replaced_frames':sum(not item['retained_original'] for item in frames), 'frames':frames,
                'opaque_members_copied':len(entries)-len(frames),
                'saved_frame_bytes':sum(item['original_encoded_bytes']-item['output_encoded_bytes'] for item in frames),
                'level':level, 'window_log':window_log, 'threads':0, 'write_checksum':True, 'write_content_size':True,
                'zstandard_version':zstd.__version__, 'zstd_version':list(zstd.ZSTD_VERSION),
                'output_bytes':output_identity[3], 'output_sha256':output_digest.hexdigest(),
                'work_directory':str(work), 'retained_partial':str(partial),
                'peak_rss_bytes':budget.peak_rss, 'source_identity_sha256_unchanged':True,
                'elapsed_seconds':time.monotonic()-budget.started}
            if prefix_pinned is not None:
                report.update(prefix=str(prefix), prefix_sha256=expected_prefix_sha256,
                    prefix_identity_before=list(prefix_pinned.before), prefix_authenticated_members=len(prefix_infos),
                    reused_prefix_frames=sum(item.get('reused_prefix', False) for item in frames))
            if callback: callback({'phase':'ready_to_publish', 'frame_count':len(frames),
                                   'replaced_frames':report['replaced_frames'], 'output_bytes':report['output_bytes']})
            budget.check(); pinned.verify(rehash=True)
            if prefix_pinned is not None:
                prefix_pinned.verify(rehash=True)
                pinned.verify()  # The other input's full read must not hide a source change.
                report['prefix_identity_after'] = list(prefix_pinned.before)
            _need(output_identity == _identity(partial.lstat()), 'completed partial changed before publication')
            # Portable atomic no-clobber publication: only our own complete output is linked.
            # The original input is never hardlinked or modified.
            os.link(partial, destination, follow_symlinks=False)
            # Creating the hardlink changes ctime; the verified inode, mode,
            # size and mtime must still be those of our completed output.
            _need(output_identity[:5] == _identity(partial.lstat())[:5] == _identity(destination.lstat())[:5],
                  'published partial identity changed')
            directory = os.open(destination.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
            report.update(source_identity_after=list(pinned.before), peak_rss_bytes=budget.peak_rss,
                          elapsed_seconds=time.monotonic()-budget.started, retained_partial_same_inode=True)
            return report
    except BaseException as error:
        if work is not None: error.add_note('Recompression partials retained in '+str(work))
        raise
