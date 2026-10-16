"""Lossless legacy snapshot seals; no import, aliasing or backend cutover.

Only trusted constants create the private validation schema. SQL and DDL from
an artifact are never executed. A self-consistent footer is not a provenance
anchor: row consumption requires an independently supplied SHA AND byte count.
"""
from __future__ import annotations

import base64
from contextlib import closing
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from . import study_progress_snapshot as snapshot
from .study_catalog import canonical

SCHEMA = 'study-progress-seal.v1'
_HEX = re.compile('[a-f0-9]{64}\\Z')
_INTEGER = re.compile('(?:0|-[1-9][0-9]*|[1-9][0-9]*)\\Z')


class SealError(snapshot.SnapshotError):
    """The package is malformed, changed, unauthenticated, or already closed."""


def _json_line(value):
    return (canonical(value) + '\n').encode('utf-8')


def _write(stream, value):
    if stream.write(value) != len(value):
        raise SealError('short seal write')


def _private_file(path, mode='w+b'):
    return os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), mode)


def _digest(stream):
    stream.seek(0)
    digest, size = hashlib.sha256(), 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _verify_published(path, identity, digest, size):
    """Bind the actually linked inode/bytes, including a pre-link mutation."""
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        before = snapshot._file_identity(os.fstat(stream.fileno()))
        if (not stat.S_ISREG(before['mode']) or stat.S_IMODE(before['mode']) != 0o600 or
                any(before[key] != identity[key] for key in ('device', 'inode')) or
                _digest(stream) != (digest, size) or
                snapshot._file_identity(os.fstat(stream.fileno())) != before or
                snapshot._file_identity(path.lstat()) != before):
            raise SealError('published artifact identity/bytes differ')


def _parse(line):
    if not line.endswith(b'\n'):
        raise SealError('seal line missing terminal newline')
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise SealError('duplicate JSON key')
            value[key] = item
        return value
    try:
        value = json.loads(line.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(SealError('nonfinite JSON')))
        if _json_line(value) != line:
            raise SealError('noncanonical seal bytes')
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        raise SealError('invalid seal JSON') from error


def _decode(cell):
    if type(cell) is not list or not cell:
        raise SealError('invalid typed cell')
    if cell == ['null']:
        return None
    if len(cell) != 2 or type(cell[1]) is not str:
        raise SealError('invalid typed cell payload')
    kind, value = cell
    try:
        if kind == 'integer' and _INTEGER.fullmatch(value):
            result = int(value)
            if not -(2**63) <= result < 2**63:
                raise SealError('SQLite integer overflow')
            return result
        if kind == 'real':
            result = float.fromhex(value)
            if not math.isfinite(result) or result.hex() != value:
                raise SealError('noncanonical real cell')
            return result
        if kind == 'text':
            return value
        if kind == 'blob':
            result = base64.b64decode(value, validate=True)
            if base64.b64encode(result).decode('ascii') != value:
                raise SealError('noncanonical blob cell')
            return result
    except (ValueError, OverflowError) as error:
        raise SealError('invalid typed cell value') from error
    raise SealError('unknown typed cell')


def _source(source):
    if (type(source) is not dict or set(source) != {'path', 'files', 'read_isolation', 'private_temporary_writes'} or
            type(source['path']) is not str or not Path(source['path']).is_absolute() or
            source['read_isolation'] != 'verified-private-copy' or source['private_temporary_writes'] is not True or
            type(source['files']) is not list or [r.get('role') for r in source['files'] if type(r) is dict] not in
            (['main'], ['main', 'wal'])):
        raise SealError('invalid source seal')
    fields = {'role', 'sha256', 'device', 'inode', 'mode', 'bytes', 'mtime_ns', 'ctime_ns'}
    for record in source['files']:
        if (type(record) is not dict or set(record) != fields or not isinstance(record['sha256'], str) or
                not _HEX.fullmatch(record['sha256']) or any(type(record[k]) is not int or record[k] < 0
                for k in fields - {'role', 'sha256'}) or not stat.S_ISREG(record['mode'])):
            raise SealError('invalid source main/WAL identity')


def _validate(stream, directory, *, expected_sha256=None, expected_bytes=None):
    before = snapshot._file_identity(os.fstat(stream.fileno()))
    stream.seek(0)
    first = stream.readline()
    header = _parse(first)
    if type(header) is not dict or set(header) != {'schema', 'kind', 'snapshot'} or header['schema'] != SCHEMA or header['kind'] != 'header':
        raise SealError('invalid seal header/schema')
    report = header['snapshot']
    if type(report) is not dict or not isinstance(report.get('schema_sha256'), str) or not _HEX.fullmatch(report['schema_sha256']):
        raise SealError('invalid snapshot report')
    _source(report.get('source'))
    db_path = directory / 'validate.sqlite3'
    with _private_file(db_path):
        pass
    prefix, whole = hashlib.sha256(first), hashlib.sha256(first)
    payload_bytes, size, last_table, previous_key = len(first), len(first), -1, None
    row_total, sequence_cleared, footer = 0, False, None
    try:
        with closing(sqlite3.connect(db_path)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA journal_mode=MEMORY')
            db.execute('PRAGMA temp_store=MEMORY')
            for name in snapshot.TABLES:
                if name != 'sqlite_sequence':
                    db.execute(snapshot._DDL[name])
            db.execute(snapshot._INDEX)
            db.execute('PRAGMA user_version=1')
            structure = snapshot._structure(db)
            for line in stream:
                whole.update(line); size += len(line)
                value = _parse(line)
                if type(value) is dict:
                    footer = value
                    break
                if (type(value) is not list or len(value) != 2 or value[0] not in snapshot.TABLES or
                        type(value[1]) is not list):
                    raise SealError('invalid canonical row')
                name, cells = value
                index = snapshot.TABLES.index(name)
                if index < last_table:
                    raise SealError('table order differs')
                if not sequence_cleared and index > snapshot.TABLES.index('reviews'):
                    db.execute('DELETE FROM sqlite_sequence'); sequence_cleared = True
                columns = structure[name]['columns']
                if len(cells) != len(columns):
                    raise SealError('row column count differs')
                row = tuple(_decode(cell) for cell in cells)
                issues = []
                snapshot._validate_row(name, row, columns, issues, row_total)
                if issues or snapshot._line(name, row) != line:
                    raise SealError('invalid row storage/type/value')
                keys = [c[0] for c in sorted(columns, key=lambda c: c[5]) if c[5]]
                if name == 'sqlite_sequence':
                    if len(row) != 2 or type(row[0]) is not str or type(row[1]) is not int:
                        raise SealError('invalid sequence cell types')
                    keys = [0, 1]
                key = tuple(row[k] for k in keys)
                if index == last_table and key <= previous_key:
                    raise SealError('duplicate or unsorted primary key')
                last_table, previous_key = index, key
                db.execute('INSERT INTO "' + name + '" VALUES(' + ','.join('?' for _ in row) + ')', row)
                prefix.update(line); payload_bytes += len(line); row_total += 1
            if not sequence_cleared:
                db.execute('DELETE FROM sqlite_sequence')
            if stream.read(1):
                raise SealError('bytes after seal footer')
            fields = {'schema', 'kind', 'payload_bytes', 'payload_sha256', 'rows', 'rows_sha256', 'tables'}
            if (type(footer) is not dict or set(footer) != fields or footer['schema'] != SCHEMA or
                    footer['kind'] != 'footer' or type(footer['payload_bytes']) is not int or
                    footer['payload_bytes'] != payload_bytes or footer['payload_sha256'] != prefix.hexdigest() or
                    type(footer['rows']) is not int or footer['rows'] != row_total):
                raise SealError('invalid seal footer/digest/count')
            actual, _ = snapshot._inspect(db, report['source'])
            if not actual['snapshot_valid']:
                raise SealError('sealed rows fail snapshot validation')
            # The source schema SHA records original spelling/formatting. Never
            # execute it; the known logical contract/columns are checked below.
            actual['schema_sha256'] = report['schema_sha256']
            if canonical(actual) != canonical(report):
                raise SealError('snapshot report differs from sealed rows')
            tables = {name: {'rows': actual['tables'][name]['rows'], 'rows_sha256': actual['tables'][name]['rows_sha256']}
                      for name in snapshot.TABLES}
            if footer['rows_sha256'] != actual['rows_sha256'] or canonical(footer['tables']) != canonical(tables):
                raise SealError('table/combined row digest differs')
    except (sqlite3.Error, TypeError, KeyError, ValueError, RecursionError) as error:
        if isinstance(error, SealError):
            raise
        raise SealError('invalid sealed snapshot: ' + type(error).__name__) from error
    finally:
        db_path.unlink(missing_ok=True)
    if snapshot._file_identity(os.fstat(stream.fileno())) != before:
        raise SealError('seal changed during validation')
    if expected_sha256 is not None and (whole.hexdigest() != expected_sha256 or size != expected_bytes):
        raise SealError('external artifact SHA/bytes differ')
    return header, whole.hexdigest(), size


class SealedSource:
    """Owned, fixed verified artifact. Use as a context manager or close it."""
    def __init__(self, temporary, stream, header, digest, size, authenticated):
        self._temporary, self._stream, self._header = temporary, stream, header
        self._sha256, self._bytes, self._authenticated = digest, size, authenticated
        self._iterating = False

    @property
    def authenticated(self):
        return self._authenticated

    @property
    def sha256(self):
        return self._sha256

    @property
    def bytes(self):
        return self._bytes

    @property
    def report(self):
        return copy.deepcopy(self._header['snapshot'])

    def close(self):
        if self._stream is not None:
            self._stream.close(); self._stream = None
            self._temporary.cleanup()

    def __enter__(self):
        if self._stream is None:
            raise SealError('sealed source is closed')
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def read_seal(path, *, expected_sha256=None, expected_bytes=None):
    """Validate ALL bytes before returning. No external anchor means inspect-only."""
    anchored = expected_sha256 is not None or expected_bytes is not None
    if anchored and (type(expected_sha256) is not str or not _HEX.fullmatch(expected_sha256) or
                     type(expected_bytes) is not int or expected_bytes <= 0):
        raise SealError('both external artifact SHA and byte count are required')
    path = Path(path).expanduser().absolute()
    temporary, stream = tempfile.TemporaryDirectory(prefix='study-progress-seal-read-'), None
    try:
        sealed = snapshot._file_record(path, 'artifact')
        if anchored and (sealed['sha256'] != expected_sha256 or sealed['bytes'] != expected_bytes):
            raise SealError('external artifact SHA/bytes differ')
        private = Path(temporary.name) / 'artifact.jsonl'
        snapshot._copy_source_file(path, private, sealed)
        stream = private.open('rb')
        header, digest, size = _validate(stream, Path(temporary.name),
                                         expected_sha256=sealed['sha256'], expected_bytes=sealed['bytes'])
        if snapshot._file_record(path, 'artifact') != sealed:
            raise SealError('artifact changed during private validation')
        return SealedSource(temporary, stream, header, digest, size, anchored)
    except BaseException as error:
        if stream is not None:
            stream.close()
        temporary.cleanup()
        if isinstance(error, (OSError, snapshot.SnapshotError)) and not isinstance(error, SealError):
            raise SealError('seal read failed: ' + type(error).__name__) from error
        raise


def iter_sealed_rows(seal, *, table=None):
    """Yield canonical bytes only from the authenticated fixed private handle.

    Never reopens the original artifact path. Exhaust or close generators; a
    future importer must retain its transaction until exhaustion/reconciliation.
    """
    if not isinstance(seal, SealedSource) or seal._stream is None:
        raise SealError('sealed source is closed or invalid')
    if not seal.authenticated:
        raise SealError('external artifact SHA/bytes required for migration rows')
    if table is not None and table not in snapshot.TABLES:
        raise SealError('unknown canonical table')
    if seal._iterating:
        raise SealError('concurrent row iteration is not supported')
    seal._iterating = True
    try:
        stream = seal._stream
        _validate(stream, Path(seal._temporary.name), expected_sha256=seal.sha256, expected_bytes=seal.bytes)
        stream.seek(0)
        identity = snapshot._file_identity(os.fstat(stream.fileno()))
        first = stream.readline()
        combined, length, footer_seen = hashlib.sha256(first), len(first), False
        for line in stream:
            if seal._stream is None:
                raise SealError('sealed source closed during iteration')
            value = _parse(line)
            combined.update(line); length += len(line)
            if type(value) is dict:
                footer_seen = True
                break
            if table is None or value[0] == table:
                yield line
        if (not footer_seen or stream.read(1) or combined.hexdigest() != seal.sha256 or length != seal.bytes or
                snapshot._file_identity(os.fstat(stream.fileno())) != identity):
            raise SealError('sealed artifact changed during iteration')
    except ValueError as error:
        if seal._stream is None:
            raise SealError('sealed source closed during iteration') from error
        raise
    finally:
        seal._iterating = False


def seal_source(path, destination):
    """Check and seal one private source transaction; publish without replacing."""
    destination = Path(destination).expanduser().absolute()
    if os.path.lexists(destination):
        raise FileExistsError(destination)
    parent = destination.parent
    parent_identity = snapshot._file_identity(parent.stat())
    owned_identity = None
    try:
        with tempfile.TemporaryDirectory(prefix='.study-progress-seal-', dir=parent) as directory:
            directory = Path(directory)
            rows_path, artifact = directory / 'rows.jsonl', directory / 'artifact.jsonl'
            with _private_file(rows_path) as rows:
                report = snapshot.inspect_snapshot(path, row_sink=lambda line: _write(rows, line))
                if not report['snapshot_valid']:
                    raise SealError('source snapshot has validation blockers')
                rows.flush(); os.fsync(rows.fileno())
            with _private_file(artifact) as outgoing:
                _write(outgoing, _json_line({'schema': SCHEMA, 'kind': 'header', 'snapshot': report}))
                with rows_path.open('rb') as rows:
                    for chunk in iter(lambda: rows.read(1024 * 1024), b''):
                        _write(outgoing, chunk)
                outgoing.flush(); os.fsync(outgoing.fileno())
                prefix_sha, prefix_bytes = _digest(outgoing)
                outgoing.seek(0, 2)
                tables = {name: {key: report['tables'][name][key] for key in ('rows', 'rows_sha256')}
                          for name in snapshot.TABLES}
                _write(outgoing, _json_line({'schema': SCHEMA, 'kind': 'footer', 'payload_sha256': prefix_sha,
                       'payload_bytes': prefix_bytes, 'rows': sum(v['rows'] for v in tables.values()),
                       'rows_sha256': report['rows_sha256'], 'tables': tables}))
                outgoing.flush(); os.fsync(outgoing.fileno())
                digest, size = _digest(outgoing)
            # Read the actual finished bytes, not a pre-write intended hash.
            with read_seal(artifact, expected_sha256=digest, expected_bytes=size):
                pass
            now_parent = snapshot._file_identity(parent.stat())
            if any(now_parent[k] != parent_identity[k] for k in ('device', 'inode', 'mode')):
                raise SealError('destination directory changed before publication')
            owned_identity = snapshot._file_identity(artifact.stat())
            os.link(artifact, destination, follow_symlinks=False)
            _verify_published(destination, owned_identity, digest, size)
            folder = os.open(parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
            return {'schema': 'study-progress-seal-receipt.v1', 'path': str(destination),
                    'sha256': digest, 'bytes': size, 'rows_sha256': report['rows_sha256'],
                    'tables': tables, 'revisions': report['revisions'], 'review_sequence': report['review_sequence']}
    except BaseException:
        if owned_identity is not None:
            try:
                actual = snapshot._file_identity(destination.lstat())
                if all(actual[k] == owned_identity[k] for k in ('device', 'inode')):
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise
