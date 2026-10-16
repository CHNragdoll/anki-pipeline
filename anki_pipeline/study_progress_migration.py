"""Authenticated legacy seals and lossless explicit-transaction PG migration.

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


# These metadata rows are covered by the registered catalog backup, without
# adding an unversioned table or changing the learning storage descriptor.
ALIASES_KEY = 'study.progress.aliases.v1'
RECEIPT_KEY = 'study.progress.migration.v1'
IMPORT_SCHEMA = 'study-progress-import.v1'
_ALIAS_SCHEMA = 'study-progress-current-bindings-readonly.v1'


class MigrationError(SealError):
    """A migration prerequisite, explicit identity, or full-row CAS failed."""


def _load_pinned_json(path, sha256, size, *, compressed=False):
    """Parse the very bytes authenticated on one FD, never a second path read."""
    if (not isinstance(path, (str, Path)) or not str(path) or type(sha256) is not str or
            not _HEX.fullmatch(sha256) or type(size) is not int or size <= 0):
        raise MigrationError('external JSON SHA and byte count are required')
    path = Path(path).expanduser().absolute()
    try:
        before = snapshot._file_identity(path.lstat())
        # Input catalog aliases are permitted, but their inode and resolution
        # must remain fixed throughout the read; output paths are never used.
        resolved = path.resolve(strict=True)
        target_before = snapshot._file_identity(resolved.lstat())
        if not stat.S_ISREG(target_before['mode']):
            raise MigrationError('pinned JSON must resolve to a regular file')
        descriptor = os.open(resolved, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if (not stat.S_ISREG(target_before['mode']) or
                    snapshot._file_identity(os.fstat(stream.fileno())) != target_before):
                raise MigrationError('pinned JSON is not the expected regular file')
            raw = stream.read(size + 1)
            if (len(raw) != size or hashlib.sha256(raw).hexdigest() != sha256 or
                    snapshot._file_identity(os.fstat(stream.fileno())) != target_before or
                    snapshot._file_identity(resolved.lstat()) != target_before or
                    snapshot._file_identity(path.lstat()) != before or path.resolve(strict=True) != resolved):
                raise MigrationError('pinned JSON bytes or file identity changed')
        if compressed:
            import gzip
            raw = gzip.decompress(raw)
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise MigrationError('duplicate identity JSON key')
                result[key] = value
            return result
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(MigrationError('nonfinite identity JSON')))
    except (OSError, ValueError, UnicodeError, EOFError) as error:
        if isinstance(error, MigrationError):
            raise
        raise MigrationError('pinned identity JSON read failed: ' + type(error).__name__) from error


def _transaction(db, *, write=False):
    from psycopg.pq import TransactionStatus
    from . import study_progress_pg as pg
    from . import study_catalog as catalog
    if db.info.transaction_status != TransactionStatus.INTRANS:
        raise MigrationError('caller must open an explicit transaction')
    isolation = db.execute("select current_setting('transaction_isolation')").fetchone()[0]
    if isolation not in ('read committed', 'repeatable read', 'serializable'):
        raise MigrationError('unsupported reconciliation transaction isolation')
    if write or isolation == 'read committed':
        if write and db.execute("select current_setting('transaction_read_only')").fetchone()[0] != 'off':
            raise MigrationError('migration needs a writable transaction')
        schema = db.execute('select current_schema()').fetchone()[0]
        key = int(catalog.identity(pg.VERSION, schema)[:15], 16)
        held = db.execute("select 1 from pg_locks where locktype='advisory' and pid=pg_backend_pid() "
                          "and granted and mode='ExclusiveLock' and classid=%s and objid=%s and objsubid=1",
                          (key >> 32, key & 0xffffffff)).fetchone()
        if held is None:
            raise MigrationError('caller must hold the PostgreSQL learning lock')
    pg.validate_connection(db)


def _migration_fence(db):
    """Serialize with both existing writer families, without an old RR view.

    An advisory-lock SELECT can establish its snapshot BEFORE it waits. Under
    RR/SERIALIZABLE even a later lock plus repeated identity reads stays stale.
    READ COMMITTED gives the first identity read after the catalog lock a fresh
    view. Both transaction locks then prevent normal writers until outer exit.
    Lock order is learning (caller) then catalog content; do not reverse it.
    """
    from . import study_catalog as catalog
    _transaction(db, write=True)
    if db.execute("select current_setting('transaction_isolation')").fetchone()[0] != 'read committed':
        raise MigrationError('migration plan/import requires READ COMMITTED; old fixed snapshots are not accepted')
    catalog.write_lock(db)


def _seal_rows(seal):
    # iter_sealed_rows revalidates the SAME authenticated private handle before
    # every pass and verifies it again at exhaustion; never reopen the path.
    with closing(iter_sealed_rows(seal)) as rows:
        for line in rows:
            name, cells = _parse(line)
            row = tuple(_decode(cell) for cell in cells)
            if any(type(value) is str and '\x00' in value for value in row):
                raise MigrationError('PostgreSQL TEXT cannot preserve source U+0000')
            yield name, row


def reconcile(db, seal):
    """Compare every typed cell, including sequence absence, in the caller TX.

    RR/SERIALIZABLE can reconcile read-only without writer locks. READ COMMITTED
    requires the learning lock for a stable cross-table view. Mismatch output contains table names and
    counts/digests, never scheduler JSON, notes, or other personal row values.
    """
    from itertools import zip_longest
    from . import study_progress_pg as pg
    _transaction(db)
    source_hash, target_hash = hashlib.sha256(), hashlib.sha256()
    counts = {name: {'source': 0, 'target': 0, 'equal': True} for name in snapshot.TABLES}
    with closing(iter_sealed_rows(seal)) as source_rows, closing(pg.canonical_rows(db)) as target_rows:
        for left, right in zip_longest(source_rows, target_rows):
            for line, digest, side in ((left, source_hash, 'source'), (right, target_hash, 'target')):
                if line is not None:
                    digest.update(line)
                    counts[_parse(line)[0]][side] += 1
            if left != right:
                for line in (left, right):
                    if line is not None:
                        counts[_parse(line)[0]]['equal'] = False
    return {'schema': 'study-progress-reconciliation.v1', 'equal': all(v['equal'] for v in counts.values()),
            'tables': counts, 'source_rows_sha256': source_hash.hexdigest(),
            'target_rows_sha256': target_hash.hexdigest(), 'ready_to_switch': False}


def _identities(db, seal, report):
    """Validate approved identity evidence, actual catalog files, and PG tuples."""
    from . import study_catalog as catalog
    required = {'schema', 'catalog_revision', 'books', 'bindings', 'guide_proofs',
                'excluded_from_legacy_learning_catalog', 'captured_at', 'scope', 'ready_to_switch'}
    if (type(report) is not dict or set(report) != required or report['schema'] != _ALIAS_SCHEMA or
            report['ready_to_switch'] is not False or type(report['catalog_revision']) is not int or
            type(report['books']) is not list or type(report['bindings']) is not list or
            type(report['guide_proofs']) is not dict or type(report['excluded_from_legacy_learning_catalog']) is not list):
        raise MigrationError('unsupported approved alias report')
    revision = db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    if revision != report['catalog_revision']:
        raise MigrationError('catalog revision differs from approved aliases')
    source_cards = {(row[0], row[1]) for name, row in _seal_rows(seal) if name == 'cards'}
    active, books, native = {}, {}, {}
    for book in report['books']:
        if (type(book) is not dict or set(book) != {'book_id','legacy_book','source_id','cards','native_cards','catalog'} or
                any(type(book[k]) is not str or not book[k] for k in ('book_id','legacy_book','source_id')) or
                type(book['cards']) is not int or type(book['native_cards']) is not int or
                type(book['catalog']) is not dict or set(book['catalog']) != {'path','sha256','bytes'} or
                book['legacy_book'] in books or any(b['book_id'] == book['book_id'] for b in books.values())):
            raise MigrationError('invalid or duplicate book alias')
        legacy = _load_pinned_json(book['catalog']['path'], book['catalog']['sha256'], book['catalog']['bytes'])
        if (type(legacy) is not dict or legacy.get('schema') != 'anki-web-catalog.v1' or
                type(legacy.get('cards')) is not list or type(legacy.get('decks')) is not list):
            raise MigrationError('unsupported legacy catalog')
        decks = {}
        for deck in legacy['decks']:
            if (type(deck) is not dict or type(deck.get('id')) is not str or not deck['id'] or
                    deck['id'] in decks or type(deck.get('cardIds')) is not list or
                    any(type(v) is not str for v in deck['cardIds']) or
                    len(set(deck['cardIds'])) != len(deck['cardIds'])):
                raise MigrationError('invalid legacy deck membership')
            decks[deck['id']] = set(deck['cardIds'])
        local = {}
        for card in legacy['cards']:
            if (type(card) is not dict or type(card.get('id')) is not str or not card['id'] or
                    type(card.get('deckId')) is not str or card['id'] in local or
                    card['deckId'] not in decks or card['id'] not in decks[card['deckId']]):
                raise MigrationError('legacy card/deck membership differs')
            local[card['id']] = card['deckId']
        if (len(local) != book['cards'] or set().union(set(), *decks.values()) != set(local) or
                any(members != {c for c, d in local.items() if d == deck} for deck, members in decks.items())):
            raise MigrationError('legacy active card/deck set differs')
        active.update({(book['legacy_book'], card): deck for card, deck in local.items()})
        books[book['legacy_book']] = book
        source = db.execute('select s.source_id,x.status,s.col_payload_id from book_sources s '
                            'join books b on b.id=s.book_id join sources x on x.id=s.source_id '
                            'where b.id=%s', (book['book_id'],)).fetchone()
        if source is None or source[:2] != (book['source_id'], 'complete'):
            raise MigrationError('canonical book/source is missing, incomplete, or different')
        col = catalog.get_json(db, source[2])
        try:
            models = json.loads(col['models'])
        except (KeyError, ValueError, TypeError) as error:
            raise MigrationError('source model registry is invalid') from error
        if type(models) is not dict:
            raise MigrationError('source model registry is invalid')
        rows = db.execute('select n.native_id,n.note_id,a.guid,a.model_id,n.ordinal,n.unit_id,'
                          'a.source_card_id,a.kind from native_cards n join notes a '
                          'on a.book_id=n.book_id and a.note_id=n.note_id '
                          'join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s',
                          (book['book_id'],)).fetchall()
        if len(rows) != book['native_cards']:
            raise MigrationError('canonical native card count differs')
        for native_id, note, guid, model, ordinal, unit, source_id, kind in rows:
            model_value = models.get(str(model))
            templates = model_value.get('tmpls') if type(model_value) is dict else None
            if (not isinstance(templates, list) or not 0 <= ordinal < len(templates) or
                    type(templates[ordinal]) is not dict or templates[ordinal].get('ord') != ordinal):
                raise MigrationError('canonical model/template is missing')
            native[(book['book_id'],native_id)] = (
                {'book_id':book['book_id'],'source_id':book['source_id'],'note_id':note,
                 'guid':guid,'model_id':model,'native_id':native_id,'template_ordinal':ordinal,'unit_id':unit},
                source_id,kind)
    if not set(active).issubset(source_cards):
        raise MigrationError('sealed rows are missing active legacy catalog cards')
    seen, targets, guide_books = set(), set(), set()
    for binding in report['bindings']:
        if type(binding) is not dict or set(binding) != {'evidence','legacy','target'}:
            raise MigrationError('invalid explicit card binding')
        old, target = binding['legacy'], binding['target']
        if (type(old) is not dict or set(old) != {'book','card_id','deck_id'} or
                any(type(v) is not str for v in old.values()) or type(target) is not dict or
                set(target) != {'book_id','source_id','note_id','guid','model_id','native_id','template_ordinal','unit_id'} or
                any(type(target[k]) is not int for k in ('note_id','model_id','native_id','template_ordinal','unit_id')) or
                any(type(target[k]) is not str for k in ('book_id','source_id','guid'))):
            raise MigrationError('invalid legacy/native identity fields')
        key = (old['book'], old['card_id']); new = (target['book_id'],target['native_id'])
        if (key in seen or new in targets or key not in active or active[key] != old['deck_id'] or
                books[old['book']]['book_id'] != target['book_id'] or new not in native or native[new][0] != target):
            raise MigrationError('legacy/native identity differs or repeats')
        seen.add(key); targets.add(new)
        _, source_id, kind = native[new]
        if binding['evidence'] == 'exact-source-card-id':
            if source_id != old['card_id']:
                raise MigrationError('canonical source card ID differs')
        elif binding['evidence'] == 'exact-guide-proof':
            proof = report['guide_proofs'].get(old['book'])
            if (source_id is not None or kind != 'guide' or type(proof) is not dict or
                    set(proof) != {'evidence','guid','id','native_id','note_id','template_ordinal'} or
                    proof['id'] != old['card_id'] or any(proof[k] != target[k] for k in
                    ('guid','native_id','note_id','template_ordinal')) or type(proof['evidence']) is not dict or
                    proof['evidence'].get('kind') not in ('exact-native-and-web-identity-derivation',
                        'every-original-field-exact-in-legacy-page-and-native-GUID')):
                raise MigrationError('approved exceptional identity proof differs')
            guide_books.add(old['book'])
        else:
            raise MigrationError('unsupported binding evidence type')
    if seen != set(active) or guide_books != set(report['guide_proofs']):
        raise MigrationError('approved aliases do not cover the exact active identity set')
    excluded = set()
    for item in report['excluded_from_legacy_learning_catalog']:
        if type(item) is not dict or not {'book_id','native_id'}.issubset(item):
            raise MigrationError('invalid explicit excluded native card')
        key = (item['book_id'],item['native_id'])
        if key in excluded or key in targets or key not in native:
            raise MigrationError('excluded native identity differs or repeats')
        if any(item.get(k) != native[key][0][k] for k in native[key][0]):
            raise MigrationError('excluded native tuple differs')
        if (item.get('id') != native[key][1] or item.get('kind') != native[key][2] or
                type(item.get('reason')) is not str or not item['reason']):
            raise MigrationError('excluded source identity or explicit reason differs')
        excluded.add(key)
    if targets | excluded != set(native):
        raise MigrationError('native coverage differs; no implicit learning cards may be seeded')
    return [{'book':book,'card_id':card} for book,card in sorted(source_cards - set(active))]


def plan_import(db, seal, alias_path, *, expected_alias_sha256, expected_alias_bytes):
    """Read-only import plan; approved aliases and source both need external pins.

    Caller owns a READ COMMITTED transaction and learning lock. This function
    takes the existing catalog-content lock before identity reads; both locks
    last until the caller exits its transaction. The plan is not cutover
    approval. Same-receipt reuse requires an exact full-row comparison.
    """
    from . import study_progress_pg as pg
    _migration_fence(db)
    report = _load_pinned_json(alias_path, expected_alias_sha256, expected_alias_bytes, compressed=True)
    inactive = _identities(db, seal, report)
    aliases = {'schema': 'study-progress-aliases.v1', 'approved_report': report,
               'artifact': {'sha256':expected_alias_sha256,'bytes':expected_alias_bytes},
               'inactive_cards': inactive, 'inactive_books': sorted(set(seal.report['books']) -
                   {book['legacy_book'] for book in report['books']})}
    schema = db.execute('select current_schema()').fetchone()[0]
    core = {'schema': IMPORT_SCHEMA,'target_schema':schema,'storage':pg.DESCRIPTOR,
            'source': {'sha256':seal.sha256,'bytes':seal.bytes,'snapshot':seal.report},
            'aliases_sha256':hashlib.sha256(canonical(aliases).encode()).hexdigest(),
            'alias_artifact':aliases['artifact'],'catalog_revision':report['catalog_revision']}
    digest = hashlib.sha256(canonical(core).encode()).hexdigest()
    receipt = {**core, 'plan_sha256':digest, 'ready_to_switch':False}
    existing = dict(db.execute('select key,value from metadata where key=any(%s)',([ALIASES_KEY,RECEIPT_KEY],)))
    if existing:
        if existing != {ALIASES_KEY:canonical(aliases),RECEIPT_KEY:canonical(receipt)}:
            raise MigrationError('target migration receipt or aliases differ')
        if not reconcile(db,seal)['equal']:
            raise MigrationError('same-receipt target rows differ from the authenticated seal')
        state = 'same-receipt'
    else:
        if any(db.execute('select exists(select 1 from '+table+')').fetchone()[0] for table in pg.TABLES):
            raise MigrationError('target learning tables are not empty')
        state = 'empty'
    return {'schema':'study-progress-import-plan.v1','plan_sha256':digest,'target_state':state,
            'ready_to_import':True,'ready_to_switch':False,'aliases':aliases,'receipt':receipt}


def import_snapshot(db, seal, alias_path, *, expected_alias_sha256, expected_alias_bytes, expected_plan_sha256):
    """Losslessly import into an empty initialized target, or verify exact reuse.

    No connection, initialization, commit, user restore, or card seeding occurs.
    Caller must own a READ COMMITTED transaction and learning write lock. The
    catalog fence remains held until outer exit. A nested savepoint also undoes
    Python validation failures if the caller catches them inside its TX.
    """
    from psycopg import sql
    from . import study_progress_pg as pg
    _migration_fence(db)
    with db.transaction():
        plan = plan_import(db,seal,alias_path,expected_alias_sha256=expected_alias_sha256,
                           expected_alias_bytes=expected_alias_bytes)
        if type(expected_plan_sha256) is not str or plan['plan_sha256'] != expected_plan_sha256:
            raise MigrationError('import plan CAS differs')
        if plan['target_state'] == 'same-receipt':
            return {'status':'reused','receipt':plan['receipt'],'reconciliation':reconcile(db,seal),'ready_to_switch':False}
        mapping = dict(zip(snapshot.TABLES,pg.TABLES))
        # Fixed trusted table/column registry, not arbitrary artifact SQL.
        with db.cursor() as cursor:
            current, batch = None, []
            def flush():
                if batch:
                    table = mapping[current]
                    statement = sql.SQL('insert into {} ({}) values ({})').format(sql.Identifier(table),
                        sql.SQL(',').join(map(sql.Identifier,pg.COLUMNS[table])),
                        sql.SQL(',').join(sql.Placeholder() for _ in pg.COLUMNS[table]))
                    cursor.executemany(statement,batch)
                    batch.clear()
            with closing(_seal_rows(seal)) as rows:
                for name,row in rows:
                    if name != current:
                        flush(); current = name
                    batch.append(row)
                    if len(batch) >= 500:
                        flush()
            flush()
        result = reconcile(db,seal)
        if not result['equal']:
            raise MigrationError('imported full rows differ from the authenticated seal')
        db.execute('insert into metadata(key,value) values(%s,%s)',(ALIASES_KEY,canonical(plan['aliases'])))
        db.execute('insert into metadata(key,value) values(%s,%s)',(RECEIPT_KEY,canonical(plan['receipt'])))
        published = dict(db.execute('select key,value from metadata where key=any(%s)',
                                   ([ALIASES_KEY,RECEIPT_KEY],)))
        if published != {ALIASES_KEY:canonical(plan['aliases']),RECEIPT_KEY:canonical(plan['receipt'])}:
            raise MigrationError('published migration receipt or aliases differ')
        result = reconcile(db,seal)
        if not result['equal']:
            raise MigrationError('published migration rows differ from the authenticated seal')
        return {'status':'imported','receipt':plan['receipt'],'reconciliation':result,'ready_to_switch':False}
