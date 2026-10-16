"""Lossless, observed PostgreSQL learning snapshot -> new legacy SQLite file.

This is a fallback *export*, not a service switch. It neither acquires writer
ownership nor initializes StudyStore. Callers must separately stop/reconcile
writers before using an observed snapshot as the active learning database.
"""
from __future__ import annotations

import base64
from contextlib import closing, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import tempfile

import psycopg
from psycopg.pq import TransactionStatus

from . import study_catalog as catalog
from . import study_progress_pg as pg
from . import study_progress_snapshot as snapshot


SCHEMA = 'study-progress-sqlite-export.v1'


class SQLiteExportError(ValueError):
    """The source or resulting fixed-schema fallback cannot be verified."""


@contextmanager
def _source(source):
    if isinstance(source, catalog.Target):
        with catalog.connect(source, readonly=True) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            yield db
    elif isinstance(source, psycopg.Connection):
        # A borrowed transaction remains entirely caller-owned, even on error.
        if source.info.transaction_status != TransactionStatus.INTRANS:
            raise SQLiteExportError('caller must supply an active read-only repeatable-read transaction')
        yield source
    else:
        raise SQLiteExportError('source must be an explicit catalog Target or PostgreSQL connection')


def _transaction_info(db):
    isolation, readonly, database, schema, transaction = db.execute(
        "SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only'), "
        'current_database(), current_schema(), pg_current_snapshot()::text').fetchone()
    if isolation != 'repeatable read' or readonly != 'on':
        raise SQLiteExportError('export requires a read-only repeatable-read transaction')
    pg.validate_connection(db)
    return {'database': database, 'schema': schema, 'snapshot': transaction,
            'isolation': isolation, 'read_only': True, 'storage_schema': pg.VERSION}


def _decode(cell):
    if type(cell) is not list or not cell:
        raise SQLiteExportError('invalid typed canonical cell')
    if cell == ['null']:
        return None
    if len(cell) != 2 or type(cell[1]) is not str:
        raise SQLiteExportError('invalid typed canonical cell')
    tag, value = cell
    try:
        if tag == 'integer':
            result = int(value)
            if str(result) != value or abs(result) > snapshot.MAX_SAFE_INTEGER:
                raise ValueError
        elif tag == 'real':
            result = float.fromhex(value)
            if not math.isfinite(result) or result.hex() != value:
                raise ValueError
        elif tag == 'text':
            result = value
        elif tag == 'blob':
            result = base64.b64decode(value, validate=True)
        else:
            raise ValueError
    except (ValueError, OverflowError) as error:
        raise SQLiteExportError('invalid typed canonical cell') from error
    if snapshot._cell(result) != cell:
        raise SQLiteExportError('noncanonical typed cell')
    return result


def _open_private(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb')


def _build(db, path, rows_path):
    """Use only local reviewed DDL; never replay DDL/SQL from a data source."""
    # Reserve before SQLite opens so the database is private from its first byte.
    with _open_private(path):
        pass
    digests = {name: hashlib.sha256() for name in snapshot.TABLES}
    counts = dict.fromkeys(snapshot.TABLES, 0)
    combined = hashlib.sha256()
    previous = -1
    sequence_cleared = False
    with closing(sqlite3.connect(path)) as output, _open_private(rows_path) as spool:
        output.execute('PRAGMA trusted_schema=OFF')
        output.execute('PRAGMA foreign_keys=ON')
        for name in snapshot.TABLES:
            if name != 'sqlite_sequence':
                output.execute(snapshot._DDL[name])
        output.execute(snapshot._INDEX)
        output.execute('PRAGMA user_version=1')
        with closing(pg.canonical_rows(db)) as incoming:
            for line in incoming:
                try:
                    name, cells = json.loads(line)
                    ordinal = snapshot.TABLES.index(name)
                    row = tuple(_decode(cell) for cell in cells)
                except (ValueError, TypeError) as error:
                    raise SQLiteExportError('invalid typed canonical row') from error
                expected_columns = pg.COLUMNS[pg.TABLES[ordinal]]
                if (ordinal < previous or len(row) != len(expected_columns) or
                        snapshot._line(name, row) != line):
                    raise SQLiteExportError('noncanonical table/column/order in source rows')
                previous = ordinal
                if name == 'sqlite_sequence' and not sequence_cleared:
                    # AUTOINCREMENT inserts create their own value. Preserve the
                    # source's exact presence and high-watermark instead.
                    output.execute('DELETE FROM sqlite_sequence')
                    sequence_cleared = True
                output.execute('INSERT INTO "' + name + '" VALUES (' +
                               ','.join('?' for _ in row) + ')', row)
                spool.write(line)
                combined.update(line); digests[name].update(line); counts[name] += 1
        if not sequence_cleared:
            output.execute('DELETE FROM sqlite_sequence')
        output.commit()
        spool.flush(); os.fsync(spool.fileno())
    return {'rows_sha256': combined.hexdigest(),
            'tables': {name: {'rows': counts[name], 'rows_sha256': digests[name].hexdigest()}
                       for name in snapshot.TABLES}}


def _reconcile(path, rows_path, source):
    # Both inspector and canonical reader open verified private SQLite copies;
    # neither can normalize or repair the file which will be published.
    with rows_path.open('rb') as expected:
        def compare(line):
            if line != expected.readline():
                raise SQLiteExportError('SQLite row differs from the PostgreSQL snapshot')
        report = snapshot.inspect_snapshot(path, row_sink=compare)
        if expected.read(1):
            raise SQLiteExportError('SQLite export omitted PostgreSQL rows')
    if not report['snapshot_valid']:
        raise SQLiteExportError('SQLite snapshot validation failed: ' +
                                ','.join(sorted({item['code'] for item in report['blockers']})))
    with rows_path.open('rb') as expected, closing(snapshot.canonical_rows(path)) as actual:
        for line in actual:
            if line != expected.readline():
                raise SQLiteExportError('SQLite canonical row reconciliation failed')
        if expected.read(1):
            raise SQLiteExportError('SQLite canonical row reconciliation is incomplete')
    tables = {name: {key: report['tables'][name][key] for key in ('rows', 'rows_sha256')}
              for name in snapshot.TABLES}
    if report['rows_sha256'] != source['rows_sha256'] or tables != source['tables']:
        raise SQLiteExportError('SQLite table summaries differ from the source')
    return report


def _unlink_owned(path, identity):
    try:
        current = path.lstat()
        if (current.st_dev, current.st_ino) == identity:
            path.unlink()
    except FileNotFoundError:
        pass


def _verify_published(path, identity, record):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if ((before.st_dev, before.st_ino) != identity or not stat.S_ISREG(before.st_mode) or
                stat.S_IMODE(before.st_mode) != 0o600):
            raise SQLiteExportError('published export identity or permissions changed')
        digest, size = hashlib.sha256(), 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            size += len(chunk); digest.update(chunk)
        if (snapshot._file_identity(os.fstat(stream.fileno())) != snapshot._file_identity(before) or
                snapshot._file_identity(path.lstat()) != snapshot._file_identity(before) or
                size != record['bytes'] or digest.hexdigest() != record['sha256']):
            raise SQLiteExportError('published export bytes changed after validation')


def export_sqlite(source, destination):
    """Publish a new 0600 SQLite file and sibling ``.proof.json``; never replace.

    ``source`` is an explicit catalog.Target (we own one read-only RR transaction)
    or an already active psycopg read-only RR transaction (caller owns its life).
    Every logical row, exact JSON string, float, null and review sequence row is
    copied and reconciled. The receipt is always observed, never switch-ready.
    Failure/cancellation removes only files published by this invocation.
    """
    requested = Path(destination).expanduser().absolute()
    destination = requested.parent.resolve(strict=True) / requested.name
    proof_path = destination.with_name(destination.name + '.proof.json')
    for path in (destination, proof_path):
        if os.path.lexists(path):
            raise FileExistsError(path)
    published = []
    try:
        with tempfile.TemporaryDirectory(prefix='.study-progress-sqlite-', dir=destination.parent) as temporary:
            stage = Path(temporary)
            private, rows, proof_file = stage/'progress.sqlite3', stage/'rows.jsonl', stage/'proof.json'
            with _source(source) as db:
                info = _transaction_info(db)
                summaries = _build(db, private, rows)
                report = _reconcile(private, rows, summaries)
                # Holding the RR snapshot does not prevent a writer committing.
                # Publication therefore never implies an exclusive cutover.
                proof = {'schema': SCHEMA, 'source': info,
                         'consistency': 'observed-repeatable-read',
                         'writer_quiescence_verified': False, 'ready_to_switch': False,
                         'canonical_rows_schema': report['canonical_rows_schema'],
                         **summaries, 'revisions': report['revisions'],
                         'review_sequence': report['review_sequence'],
                         'reconciliation': {'typed_rows_equal': True, 'snapshot_valid': True},
                         'snapshot_inspection': report}
                with private.open('rb') as stream:
                    os.fsync(stream.fileno())
                sealed = snapshot._file_record(private, 'sqlite')
                verified_files = report['source']['files']
                if (len(verified_files) != 1 or verified_files[0]['role'] != 'main' or
                        any(sealed[key] != verified_files[0][key] for key in ('sha256', 'bytes'))):
                    raise SQLiteExportError('SQLite bytes changed after snapshot reconciliation')
                proof['sqlite'] = {'sha256': sealed['sha256'], 'bytes': sealed['bytes']}
                with _open_private(proof_file) as stream:
                    stream.write((catalog.canonical(proof) + '\n').encode('utf-8'))
                    stream.flush(); os.fsync(stream.fileno())
                proof_record = snapshot._file_record(proof_file, 'proof')
                for incoming, target, record in ((private, destination, sealed),
                                                  (proof_file, proof_path, proof_record)):
                    current = incoming.lstat()
                    identity = current.st_dev, current.st_ino
                    # Register ownership BEFORE link: a signal after the system
                    # call succeeds must still remove our newly published inode.
                    published.append((target, identity))
                    os.link(incoming, target, follow_symlinks=False)
                # Verify the pair after BOTH publications, so publishing the
                # proof cannot hide an intervening change to the SQLite file.
                for (target, identity), record in zip(published, (sealed, proof_record)):
                    _verify_published(target, identity, record)
                folder = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(folder)
                finally:
                    os.close(folder)
                return proof
    except BaseException:
        for path, identity in reversed(published):
            _unlink_owned(path, identity)
        raise
