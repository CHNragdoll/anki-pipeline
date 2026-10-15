"""Read-only, complete backup-to-restoration reconciliation.

Table fingerprints are SHA-256 over every sorted row hash, retaining duplicate
rows. Only physical row order is ignored. Payloads are processed one row at a
time and fixed-size row hashes are sorted with bounded external merge runs in
``/tmp``. This check does not replace source reconciliation or decompressed
content-address verification by the catalog's deep verifier.
"""
from __future__ import annotations

from contextlib import ExitStack
import base64
import binascii
import gzip
import hashlib
import heapq
import json
from pathlib import Path
import tempfile

from psycopg import sql

from . import study_catalog as c


_BUCKETS = 64
_HASH_BYTES = 32
_CHUNK_HASHES = 32768
_MERGE_FILES = 32
_ALGORITHM = 'sha256-canonical-packed-row-multiset-64-bucket.v1'


def _hashes(stream):
    while raw := stream.read(_HASH_BYTES):
        if len(raw) != _HASH_BYTES:
            raise ValueError('truncated restore-verification hash run')
        yield raw


def _merge(paths, output):
    with ExitStack() as stack:
        sources = [_hashes(stack.enter_context(path.open('rb'))) for path in paths]
        with output.open('xb') as stream:
            for digest in heapq.merge(*sources):
                stream.write(digest)


def _sort_bucket(path, directory, *, chunk_hashes, merge_files):
    """Return one sorted binary hash file without loading a whole bucket."""
    run_count = 0
    with path.open('rb') as source:
        while raw := source.read(chunk_hashes * _HASH_BYTES):
            if len(raw) % _HASH_BYTES:
                raise ValueError('truncated restore-verification bucket')
            hashes = sorted(raw[i:i + _HASH_BYTES] for i in range(0, len(raw), _HASH_BYTES))
            run = directory / f'run-{run_count}'
            with run.open('xb') as stream:
                stream.write(b''.join(hashes))
            run_count += 1
    if not run_count:
        return path
    # File names are deterministic, so even their path list need not grow with
    # the number of runs. Only one merge fan-in is retained at a time.
    prefix = 'run-'
    generation = 0
    while run_count > 1:
        following_count = 0
        following_prefix = f'merge-{generation}-'
        for offset in range(0, run_count, merge_files):
            group = [directory / f'{prefix}{index}' for index in range(offset, min(offset + merge_files, run_count))]
            merged = directory / f'{following_prefix}{following_count}'
            _merge(group, merged)
            following_count += 1
            for old in group:
                old.unlink()
        prefix = following_prefix
        run_count = following_count
        generation += 1
    return directory / f'{prefix}0'


def _row_hash(values, *, packed=False):
    # Each row is complete, including BYTEA, codec, IDs, typed numbers and text.
    # Holding one row is necessary with the catalog's JSONL backup format;
    # neither payloads nor their encoded representations accumulate per table.
    digest = hashlib.sha256(b'[')
    for index, value in enumerate(values):
        if index:
            digest.update(b',')
        encoded = packed and isinstance(value, dict)
        if encoded:
            if set(value) != {'$bytes'} or not isinstance(value['$bytes'], str):
                raise ValueError('unsupported backup byte cell')
            value = value['$bytes']
        if encoded or isinstance(value, bytes):
            digest.update(b'{"$bytes":"')
            if encoded:
                # Decode/re-encode bounded base64 blocks, matching the bytes a
                # restoration receives without allocating another giant BYTEA.
                # A multiple of four characters is a whole base64 quantum.
                for offset in range(0, len(value), 65536):
                    part = value[offset:offset + 65536]
                    if '=' in part and offset + len(part) != len(value):
                        raise ValueError('invalid backup base64 padding')
                    try:
                        digest.update(base64.b64encode(base64.b64decode(part, validate=True)))
                    except (ValueError, binascii.Error) as exc:
                        raise ValueError('invalid backup base64 bytes') from exc
            else:
                # Whole three-byte groups avoid adding interior padding. The
                # largest objects need no full base64 string in SQL scanning.
                for offset in range(0, len(value), 49152):
                    digest.update(base64.b64encode(memoryview(value)[offset:offset + 49152]))
            digest.update(b'"}')
        else:
            if packed:
                value = c._unpack_cell(value)
            digest.update(c.canonical(value).encode())
    digest.update(b']')
    return digest.digest()


class _Rows:
    def __init__(self, directory, name, columns, *, chunk_hashes, merge_files):
        self.directory = directory
        self.name = name
        self.columns = columns
        self.chunk_hashes = chunk_hashes
        self.merge_files = merge_files
        self.paths = [directory / f'bucket-{i}' for i in range(_BUCKETS)]
        self.streams = []
        try:
            for path in self.paths:
                self.streams.append(path.open('xb'))
        except BaseException:
            self.close()
            raise
        self.counts = [0] * _BUCKETS
        self.count = 0

    def add(self, values, *, packed=False):
        digest = _row_hash(values, packed=packed)
        bucket = digest[0] >> 2
        self.streams[bucket].write(digest)
        self.counts[bucket] += 1
        self.count += 1

    def close(self):
        for stream in self.streams:
            stream.close()

    def fingerprint(self):
        self.close()
        digest = hashlib.sha256(b'study-catalog-restore-table.v1\0')
        digest.update(c.canonical({'table': self.name, 'columns': self.columns, 'rows': self.count}).encode())
        digest.update(b'\0')
        for index, path in enumerate(self.paths):
            # Explicit boundaries and counts prevent ambiguous concatenation;
            # sorting retains every hash, including repeated equal hashes.
            digest.update(index.to_bytes(1, 'big'))
            digest.update(self.counts[index].to_bytes(8, 'big'))
            with tempfile.TemporaryDirectory(prefix='runs-', dir=self.directory) as work:
                sorted_path = _sort_bucket(path, Path(work), chunk_hashes=self.chunk_hashes,
                                           merge_files=self.merge_files)
                with sorted_path.open('rb') as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
        return {'columns': self.columns, 'rows': self.count, 'sha256': digest.hexdigest()}


def _read_record(stream):
    line = stream.readline()
    if not line:
        raise ValueError('truncated PostgreSQL catalog backup')
    return line, json.loads(line)


def _backup_fingerprints(path, columns, directory, *, chunk_hashes, merge_files):
    expected = {'schema': 'study-catalog-postgresql-backup.v1', 'engine': 'postgresql', 'tables': columns}
    tables = {}
    counts = {}
    digest = hashlib.sha256()
    try:
        with gzip.open(path, 'rb') as stream:
            _, header = _read_record(stream)
            if header != expected:
                raise ValueError('backup and restored table columns or backup format differ')
            line, record = _read_record(stream)
            for ordinal, name in enumerate(c.TABLES):
                with tempfile.TemporaryDirectory(prefix=f'backup-{ordinal}-', dir=directory) as work:
                    rows = _Rows(Path(work), name, columns[name], chunk_hashes=chunk_hashes, merge_files=merge_files)
                    try:
                        while isinstance(record, list) and len(record) == 2 and record[0] == name:
                            values = record[1]
                            if not isinstance(values, list) or len(values) != len(columns[name]):
                                raise ValueError('invalid backup row in ' + name)
                            rows.add(values, packed=True)
                            digest.update(line)
                            line, record = _read_record(stream)
                        counts[name] = rows.count
                        tables[name] = rows.fingerprint()
                    finally:
                        rows.close()
            valid_counts = isinstance(record, dict) and isinstance(record.get('counts'), dict) and all(
                type(value) is int and value >= 0 for value in record['counts'].values())
            if not valid_counts or record != {'counts': counts, 'rows_sha256': digest.hexdigest()} or stream.read():
                raise ValueError('backup footer, row counts or rows_sha256 mismatch')
    except (EOFError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('invalid or incomplete PostgreSQL catalog backup') from exc
    return tables, digest.hexdigest()


def _sequences(db):
    """Check future inserts safely; sequences are not part of backup v1."""
    checked = {}
    for name in ('component_revisions', 'events'):
        sequence = db.execute("select pg_get_serial_sequence(%s,'id')", (name,)).fetchone()[0]
        if sequence is None:
            raise ValueError('missing restored identity sequence for ' + name)
        increment, maximum, cycle = db.execute(
            'select seqincrement,seqmax,seqcycle from pg_sequence where seqrelid=%s::regclass',
            (sequence,)).fetchone()
        if increment != 1 or cycle:
            raise ValueError('unsupported restored identity sequence for ' + name)
        # The name originates in PostgreSQL's own catalog, never in backup data.
        last, called = db.execute(sql.SQL('select last_value,is_called from {}').format(
            sql.Identifier(*sequence.split('.')))).fetchone()
        highest = db.execute(sql.SQL('select max(id) from {}').format(sql.Identifier(name))).fetchone()[0]
        following = last + 1 if called else last
        if (highest is not None and following <= highest) or following > maximum:
            raise ValueError('restored identity sequence would collide or exhaust for ' + name)
        checked[name] = {'max_id': highest, 'last_value': last, 'is_called': called, 'next_id': following}
    return checked


def verify_restore(backup_path, target, *, chunk_hashes=_CHUNK_HASHES, merge_files=_MERGE_FILES):
    """Verify every persisted row against a sealed backup, without any writes.

    A successful result proves complete table-payload recovery from this backup
    in one repeatable-read snapshot. Sequence *safety* is checked separately;
    backup v1 does not contain historical sequence high-water marks. Memory is
    bounded by the largest JSONL row, the catalog server cursor's fixed fetch
    batch and ``chunk_hashes`` fixed-size hashes, rather than total table size;
    merge fan-in never exceeds ``merge_files``. Temporary files are kept outside
    iCloud in /tmp and removed on both success and failure.
    """
    if type(chunk_hashes) is not int or chunk_hashes < 1:
        raise ValueError('chunk_hashes must be a positive integer')
    if type(merge_files) is not int or not 2 <= merge_files <= 64:
        raise ValueError('merge_files must be between 2 and 64')
    path = Path(backup_path).resolve(strict=True)
    original = path.stat()
    selected = c.target(target)
    with tempfile.TemporaryDirectory(prefix='study-catalog-restore-qa-', dir='/tmp') as work:
        directory = Path(work)
        with c.connect(selected, readonly=True) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            names = {row[0] for row in db.execute(
                "select table_name from information_schema.tables "
                "where table_schema=current_schema() and table_type='BASE TABLE'")}
            if names != set(c.TABLES):
                raise ValueError('restored catalog has missing or unexpected tables')
            columns = {name: c._columns(db, name) for name in c.TABLES}
            expected, rows_sha256 = _backup_fingerprints(path, columns, directory,
                                                       chunk_hashes=chunk_hashes, merge_files=merge_files)
            for ordinal, name in enumerate(c.TABLES):
                with tempfile.TemporaryDirectory(prefix=f'restored-{ordinal}-', dir=directory) as table_work:
                    rows = _Rows(Path(table_work), name, columns[name], chunk_hashes=chunk_hashes,
                                 merge_files=merge_files)
                    try:
                        for row in c._rows(db, name, ordered=False):
                            rows.add(row)
                        actual = rows.fingerprint()
                    finally:
                        rows.close()
                if actual != expected[name]:
                    raise ValueError('restored catalog differs from backup in table ' + name)
            sequences = _sequences(db)
    current = path.stat()
    if (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns) != (
            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns):
        raise ValueError('backup file changed during restore verification')
    return {'schema': 'study-catalog-restore-verification.v1', 'algorithm': _ALGORITHM,
            'backup': str(path), 'backup_size': original.st_size, 'rows_sha256': rows_sha256,
            'target_schema': selected.schema, 'tables': expected, 'sequences': sequences,
            'sequence_scope': 'future insert safety; historical sequence state is not stored in backup v1',
            'scope': 'all catalog tables, columns and complete packed row payloads in one repeatable-read snapshot; physical order ignored',
            'source_and_decompressed_object_verification': 'separate required checks', 'complete': True}
