"""Read-only, lossless inspection of the legacy web-learning SQLite schema.

This module neither initializes StudyStore nor migrates data. Canonical rows
retain SQLite storage classes and exact text, including serialized JSON. A
successful source inspection is not permission or evidence to switch a service.
SQLite opens only verified private main/WAL copies, so sidecar creation never
requires writing beside the source. The private directory is removed on close.
"""
from __future__ import annotations

import base64
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

from .study_catalog import canonical


MAX_SAFE_INTEGER = 2**53 - 1
TABLES = ('metadata', 'settings', 'cards', 'reviews', 'undo', 'requests',
          'card_controls', 'card_actions', 'preferences', 'sqlite_sequence')
# Schema 1 is the deployed legacy backend's actual contract. Formatting and
# keyword case are immaterial; added columns/constraints require a new contract.
_DDL = {
    'metadata': 'CREATE TABLE metadata (key TEXT PRIMARY KEY, value INTEGER NOT NULL)',
    'settings': '''CREATE TABLE settings (book TEXT PRIMARY KEY, new_per_day INTEGER NOT NULL,
        review_per_day INTEGER NOT NULL, desired_retention REAL NOT NULL)''',
    'cards': '''CREATE TABLE cards (book TEXT NOT NULL, card_id TEXT NOT NULL, revision INTEGER NOT NULL,
        scheduler_json TEXT, introduced_at TEXT, PRIMARY KEY(book, card_id))''',
    'reviews': '''CREATE TABLE reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT NOT NULL,
        card_id TEXT NOT NULL, answered_at TEXT NOT NULL, day TEXT NOT NULL, rating INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL, phase TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0,
        before_json TEXT, after_json TEXT NOT NULL, before_introduced_at TEXT, revision_after INTEGER NOT NULL,
        FOREIGN KEY(book, card_id) REFERENCES cards(book, card_id))''',
    'undo': 'CREATE TABLE undo (book TEXT PRIMARY KEY, review_id INTEGER)',
    'requests': '''CREATE TABLE requests (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
        review_id INTEGER NOT NULL, FOREIGN KEY(review_id) REFERENCES reviews(id))''',
    'card_controls': '''CREATE TABLE card_controls (book TEXT NOT NULL, card_id TEXT NOT NULL,
        flag INTEGER NOT NULL DEFAULT 0, suspended INTEGER NOT NULL DEFAULT 0, buried_until TEXT,
        note TEXT NOT NULL DEFAULT '', PRIMARY KEY(book,card_id),
        FOREIGN KEY(book,card_id) REFERENCES cards(book,card_id))''',
    'card_actions': 'CREATE TABLE card_actions (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL)',
    'preferences': 'CREATE TABLE preferences (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)',
    'sqlite_sequence': 'CREATE TABLE sqlite_sequence(name,seq)',
}
_INDEX = 'CREATE INDEX reviews_book_day ON reviews(book, day, undone)'
_TOKENS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\w+|[^\s]", re.UNICODE)


class SnapshotError(ValueError):
    """The input is unreadable, changed, or has an unsupported structure."""


def _tokens(value):
    tokens = [part if part.startswith(("'", '"')) else part.lower()
              for part in _TOKENS.findall(value)]
    if tokens[2:5] == ['if', 'not', 'exists']:
        del tokens[2:5]
    return tokens


def _file_identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
            'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns}


def _file_record(candidate, role):
    before = _file_identity(candidate.lstat())
    if not stat.S_ISREG(before['mode']):
        raise SnapshotError('snapshot and WAL must be regular files, not symlinks')
    digest = hashlib.sha256()
    with candidate.open('rb') as stream:
        if _file_identity(os.fstat(stream.fileno())) != before:
            raise SnapshotError('snapshot source changed while opening')
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        if _file_identity(os.fstat(stream.fileno())) != before:
            raise SnapshotError('snapshot source changed while hashing')
    if _file_identity(candidate.lstat()) != before:
        raise SnapshotError('snapshot source changed while hashing')
    return {'role': role, 'sha256': digest.hexdigest(), **before}


def _source_files(path):
    result = []
    if Path(str(path) + '-journal').exists():
        raise SnapshotError('rollback journal requires an explicit consistent offline snapshot')
    for role, candidate in (('main', path), ('wal', Path(str(path) + '-wal'))):
        try:
            candidate.lstat()
        except FileNotFoundError:
            if role == 'main':
                raise SnapshotError('snapshot file does not exist') from None
            continue
        try:
            result.append(_file_record(candidate, role))
        except FileNotFoundError:
            raise SnapshotError('snapshot source changed while hashing') from None
    return result


def _copy_source_file(source, target, sealed):
    """Stage only sealed bytes; never let SQLite open the source itself."""
    identity = _file_identity(source.lstat())
    if any(identity[key] != sealed[key] for key in identity):
        raise SnapshotError('snapshot source changed before copying')
    digest = hashlib.sha256()
    length = 0
    with source.open('rb') as incoming, target.open('xb') as outgoing:
        if _file_identity(os.fstat(incoming.fileno())) != identity:
            raise SnapshotError('snapshot source changed before copying')
        for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
            length += len(chunk)
            if length > sealed['bytes']:
                raise SnapshotError('snapshot source changed while copying')
            outgoing.write(chunk)
            digest.update(chunk)
        if _file_identity(os.fstat(incoming.fileno())) != identity:
            raise SnapshotError('snapshot source changed while copying')
    if _file_identity(source.lstat()) != identity:
        raise SnapshotError('snapshot source changed while copying')
    copied = _file_record(target, 'copy')
    if (length != sealed['bytes'] or digest.hexdigest() != sealed['sha256'] or
            copied['bytes'] != sealed['bytes'] or copied['sha256'] != sealed['sha256']):
        raise SnapshotError('snapshot private copy does not match the source seal')


@contextmanager
def _view(value):
    path = Path(value).expanduser().absolute()
    if path.is_symlink():
        raise SnapshotError('snapshot path must not be a symlink')
    before = _source_files(path)
    try:
        # mode=ro alone may create SHM beside a WAL source. Let SQLite use only
        # a verified, owned private pair; no immutable=1 may hide committed WAL.
        with tempfile.TemporaryDirectory(prefix='study-progress-read-') as temporary:
            staged = Path(temporary) / 'snapshot.sqlite3'
            for sealed in before:
                suffix = '' if sealed['role'] == 'main' else '-wal'
                _copy_source_file(Path(str(path) + suffix), Path(str(staged) + suffix), sealed)
            if _source_files(path) != before:
                raise SnapshotError('snapshot source changed while staging the private copy')
            connection = None
            try:
                connection = sqlite3.connect(staged.as_uri() + '?mode=ro', uri=True, timeout=5)
                connection.execute('PRAGMA query_only=ON')
                connection.execute('PRAGMA trusted_schema=OFF')
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('BEGIN')
                yield connection, {'path': str(path), 'files': before,
                                   'read_isolation': 'verified-private-copy',
                                   'private_temporary_writes': True}
            finally:
                if connection is not None:
                    try:
                        connection.rollback()
                    finally:
                        connection.close()
    except sqlite3.Error as error:
        raise SnapshotError('snapshot SQLite read failed: ' + type(error).__name__) from error
    except OSError as error:
        raise SnapshotError('snapshot file read failed: ' + type(error).__name__) from error
    finally:
        if _source_files(path) != before:
            raise SnapshotError('snapshot source changed during the read transaction')


def _structure(db):
    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
        raise SnapshotError('unsupported web-learning SQLite schema version')
    tables = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
    if set(tables) != set(TABLES):
        raise SnapshotError('unsupported snapshot table set')
    for name, definition in tables.items():
        if _tokens(definition) != _tokens(_DDL[name]):
            raise SnapshotError('unsupported schema, columns, keys or constraints: ' + name)
    other = list(db.execute("SELECT type,name,sql FROM sqlite_master WHERE type!='table' AND sql IS NOT NULL"))
    if len(other) != 1 or other[0][:2] != ('index', 'reviews_book_day') or _tokens(other[0][2]) != _tokens(_INDEX):
        raise SnapshotError('unsupported snapshot index, view or trigger')
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SnapshotError('snapshot integrity check failed')
    result = {}
    for name in TABLES:
        columns = list(db.execute('PRAGMA table_info("' + name + '")'))
        if any(column[1] != column[1].lower() for column in columns):
            raise SnapshotError('unsupported source column spelling: ' + name)
        result[name] = {'definition': tables[name], 'columns': columns,
                        'foreign_keys': list(db.execute('PRAGMA foreign_key_list("' + name + '")'))}
    return result


def _rows(db, name, structure):
    columns = structure[name]['columns']
    keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    if name == 'sqlite_sequence':
        keys = ['name', 'seq']
    order = ','.join('"' + key + '" COLLATE BINARY' for key in keys)
    yield from db.execute('SELECT * FROM "' + name + '" ORDER BY ' + order)


def _cell(value):
    if value is None:
        return ['null']
    if type(value) is int:
        return ['integer', str(value)]
    if type(value) is float:
        return ['real', value.hex()]
    if isinstance(value, str):
        return ['text', value]
    if isinstance(value, bytes):
        return ['blob', base64.b64encode(value).decode('ascii')]
    raise SnapshotError('unsupported SQLite cell type')


def _line(name, row):
    return (canonical([name, [_cell(value) for value in row]]) + '\n').encode('utf-8')


def canonical_rows(path, *, table=None):
    """Yield typed UTF-8 JSONL rows, in fixed table/primary-key order.

    The generator owns one read transaction until exhausted or closed. Exact
    JSON strings stay strings; floats use hex so their binary value survives.
    Structural drift or a moving main/WAL source raises SnapshotError.
    """
    if table is not None and table not in TABLES:
        raise SnapshotError('unknown canonical table')
    with _view(path) as (db, _):
        structure = _structure(db)
        for name in TABLES if table is None else (table,):
            for row in _rows(db, name, structure):
                yield _line(name, row)


def _issue(issues, code, table=None, column=None, row=None):
    value = {'code': code}
    value.update({key: item for key, item in (('table', table), ('column', column), ('row', row)) if item is not None})
    issues.append(value)


def _json_text(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def invalid(_):
        raise ValueError('nonfinite JSON value')

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')

    def safe(item):
        if type(item) is int and abs(item) > MAX_SAFE_INTEGER:
            raise ValueError('unsafe JSON integer')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('nonfinite JSON number')
        if isinstance(item, dict):
            for nested in item.values():
                safe(nested)
        elif isinstance(item, list):
            for nested in item:
                safe(nested)
    safe(value)
    return value


def _validate_row(name, row, columns, issues, ordinal):
    record = dict(zip((column[1] for column in columns), row))
    for column, value in zip(columns, row):
        _, key, declared, required, _, primary = column
        if value is None:
            if required or primary:
                _issue(issues, 'storage_type_invalid', name, key, ordinal)
            continue
        expected = {'INTEGER': int, 'REAL': float, 'TEXT': str}.get(declared)
        if expected is not None and type(value) is not expected:
            _issue(issues, 'storage_type_invalid', name, key, ordinal)
        if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
            _issue(issues, 'unsafe_integer', name, key, ordinal)
        if type(value) is float and not math.isfinite(value):
            _issue(issues, 'nonfinite_number', name, key, ordinal)
    for key in ('book', 'card_id', 'request_id'):
        if key in record and (not isinstance(record[key], str) or not record[key] or '\0' in record[key]):
            _issue(issues, 'identity_invalid', name, key, ordinal)
    ranges = {'revision': (1, MAX_SAFE_INTEGER), 'revision_after': (1, MAX_SAFE_INTEGER),
              'rating': (1, 4), 'duration_ms': (0, 86400000), 'undone': (0, 1),
              'flag': (0, 7), 'suspended': (0, 1), 'new_per_day': (0, 10000), 'review_per_day': (0, 10000)}
    for key, (low, high) in ranges.items():
        if key in record and (type(record[key]) is not int or not low <= record[key] <= high):
            _issue(issues, 'integer_range_invalid', name, key, ordinal)
    if name == 'reviews' and record['phase'] not in ('new', 'learning', 'review'):
        _issue(issues, 'review_phase_invalid', name, 'phase', ordinal)
    if name in ('requests', 'card_actions') and not re.fullmatch('[a-f0-9]{64}', str(record['payload_hash'])):
        _issue(issues, 'request_hash_invalid', name, 'payload_hash', ordinal)
    if name == 'settings':
        value = record['desired_retention']
        if type(value) is not float or not math.isfinite(value) or not .70 <= value <= .99:
            _issue(issues, 'retention_invalid', name, 'desired_retention', ordinal)
    for key in ('scheduler_json', 'before_json', 'after_json', 'value'):
        if key not in record or record[key] is None or name == 'metadata':
            continue
        if key == 'value' and name != 'preferences':
            continue
        try:
            value = _json_text(record[key])
        except (ValueError, TypeError, RecursionError):
            _issue(issues, 'json_invalid', name, key, ordinal)
            continue
        if key != 'value':
            expected = int.from_bytes(hashlib.sha256((str(record['book']) + '\0' + str(record['card_id'])).encode()).digest()[:8], 'big') & MAX_SAFE_INTEGER
            if type(value.get('card_id')) is not int or value['card_id'] != expected:
                _issue(issues, 'scheduler_identity_invalid', name, key, ordinal)
    return record


def _inspect(db, source):
    structure = _structure(db)
    issues, tables, books, cards = [], {}, set(), {}
    combined = hashlib.sha256()
    global_revision = None
    card_max = review_max = maximum_id = 0
    sequences = []
    for name in TABLES:
        digest, count, storage = hashlib.sha256(), 0, Counter()
        for ordinal, row in enumerate(_rows(db, name, structure)):
            line = _line(name, row)
            digest.update(line)
            combined.update(line)
            count += 1
            storage.update(_cell(value)[0] for value in row)
            record = _validate_row(name, row, structure[name]['columns'], issues, ordinal)
            book = record.get('book')
            if isinstance(book, str):
                books.add(book)
            if name == 'cards' and isinstance(book, str) and isinstance(record['card_id'], str):
                cards.setdefault(book, set()).add(record['card_id'])
                if type(record['revision']) is int:
                    card_max = max(card_max, record['revision'])
            elif name == 'reviews':
                if type(record['id']) is int:
                    maximum_id = max(maximum_id, record['id'])
                    if not 1 <= record['id'] <= MAX_SAFE_INTEGER:
                        _issue(issues, 'unsafe_integer', name, 'id', ordinal)
                if type(record['revision_after']) is int:
                    review_max = max(review_max, record['revision_after'])
            elif name == 'metadata' and record['key'] == 'revision':
                global_revision = record['value']
            elif name == 'preferences' and record['id'] != 1:
                _issue(issues, 'preferences_identity_invalid', name, 'id', ordinal)
            elif name == 'sqlite_sequence':
                sequences.append(record)
        info = structure[name]
        tables[name] = {'rows': count, 'rows_sha256': digest.hexdigest(),
                        'columns': [list(column) for column in info['columns']],
                        'primary_key': [column[1] for column in sorted(info['columns'], key=lambda column: column[5]) if column[5]],
                        'storage_classes': dict(sorted(storage.items()))}
    for table, rowid, parent, key in db.execute('PRAGMA foreign_key_check'):
        issues.append({'code': 'foreign_key_violation', 'table': table, 'rowid': rowid, 'parent': parent, 'foreign_key': key})
    for _, in db.execute('''SELECT u.book FROM undo u LEFT JOIN reviews r ON r.id=u.review_id
                            WHERE u.review_id IS NOT NULL AND (r.id IS NULL OR r.book!=u.book OR r.undone!=0)'''):
        _issue(issues, 'undo_reference_invalid', 'undo')
    if type(global_revision) is not int or not 0 <= global_revision <= MAX_SAFE_INTEGER:
        _issue(issues, 'global_revision_invalid', 'metadata', 'value')
    elif global_revision < max(card_max, review_max):
        _issue(issues, 'global_revision_behind', 'metadata', 'value')
    elif global_revision == MAX_SAFE_INTEGER:
        _issue(issues, 'global_revision_exhausted', 'metadata', 'value')
    high = sequences[0]['seq'] if len(sequences) == 1 else None
    if sequences and (len(sequences) != 1 or sequences[0]['name'] != 'reviews' or
                      type(high) is not int or not 0 <= high < MAX_SAFE_INTEGER):
        _issue(issues, 'review_sequence_invalid', 'sqlite_sequence')
    if maximum_id and (type(high) is not int or high < maximum_id):
        _issue(issues, 'review_sequence_behind', 'sqlite_sequence')
    report = {'schema': 'study-progress-snapshot.v1', 'canonical_rows_schema': 'study-progress-canonical-rows.v1',
              'sqlite_schema_version': 1, 'source': source, 'tables': tables,
              'schema_sha256': hashlib.sha256(canonical(structure).encode()).hexdigest(),
              'rows_sha256': combined.hexdigest(), 'books': sorted(books),
              'revisions': {'global': global_revision, 'card_max': card_max, 'review_max': review_max},
              'review_sequence': {'present': bool(sequences), 'high_watermark': high, 'maximum_id': maximum_id},
              'snapshot_valid': not issues, 'blockers': issues,
              'unverified_scope': ['full_fsrs_scheduler_and_review_chain_semantics', 'catalog_target_identity',
                                   'pg_import_and_full_reconciliation', 'backup_restore_and_service_switch']}
    return report, cards


def inspect_snapshot(path):
    """Inspect all source rows without normalizing text or initializing cards.

    Unknown DDL/version raises SnapshotError. Invalid data stays in canonical
    rows and is reported as blockers. FSRS replay and PG reconciliation are
    explicitly outside this first-stage inspector.
    """
    with _view(path) as (db, source):
        report, _ = _inspect(db, source)
        return report


def _alias_coverage(aliases, books, cards, issues):
    if aliases is None:
        _issue(issues, 'aliases_missing')
        return False
    valid = (isinstance(aliases, dict) and set(aliases) == {'schema', 'books'} and
             aliases['schema'] == 'study-progress-aliases.v1' and isinstance(aliases['books'], dict))
    if not valid:
        _issue(issues, 'aliases_invalid')
        return False
    complete = set(aliases['books']) == set(books)
    destinations = set()
    for book, value in aliases['books'].items():
        if (not isinstance(book, str) or not isinstance(value, dict) or set(value) != {'catalog_book', 'cards'} or
                not isinstance(value['catalog_book'], str) or not value['catalog_book'] or not isinstance(value['cards'], dict)):
            _issue(issues, 'aliases_invalid')
            return False
        complete = complete and set(value['cards']) == cards.get(book, set())
        for original, destination in value['cards'].items():
            if not isinstance(original, str) or not isinstance(destination, str) or not destination:
                _issue(issues, 'aliases_invalid')
                return False
            key = value['catalog_book'], destination
            if key in destinations:
                _issue(issues, 'aliases_destination_collision')
                return False
            destinations.add(key)
    if not complete:
        _issue(issues, 'aliases_incomplete')
    return complete


def dry_run(path, *, aliases=None):
    """Check source and explicit alias coverage; never claim cutover readiness.

    aliases = {'schema': 'study-progress-aliases.v1', 'books': {
      old_book: {'catalog_book': target_book, 'cards': {old_card: target_card}}}}
    This proves coverage only, not target existence or a catalog proof. The old
    namespace is never renamed and no database/service is written.
    """
    with _view(path) as (db, source):
        report, cards = _inspect(db, source)
        issues = list(report['blockers'])
        covered = _alias_coverage(aliases, report['books'], cards, issues)
        _issue(issues, 'catalog_bindings_unverified')
        return {'schema': 'study-progress-dry-run.v1', 'snapshot': report,
                'snapshot_valid': report['snapshot_valid'], 'alias_coverage_complete': covered,
                'ready_to_switch': False, 'blockers': issues,
                'unverified_scope': list(report['unverified_scope'])}
