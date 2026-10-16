"""Explicit PostgreSQL storage for the one StudyStore business implementation.

SQL is a closed registry of reviewed legacy statements. No runtime SQL rewriting,
DDL on connect, JSONB conversion, or nontransactional review sequence is used.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from . import study_catalog as catalog
from .study_progress_storage import StorageError
from .study_progress_snapshot import _line

VERSION = 'study-progress-postgresql.v1'
METADATA_KEY = 'study.progress.storage.v1'
MAX_SAFE_INTEGER = 2**53 - 1
LOGICAL_TABLES = ('metadata', 'settings', 'cards', 'reviews', 'undo', 'requests',
                  'card_controls', 'card_actions', 'preferences', 'sequences')
TABLES = tuple('study_progress_' + name for name in LOGICAL_TABLES)
COLUMNS = dict(zip(TABLES, (
 ('key','value'), ('book','new_per_day','review_per_day','desired_retention'),
 ('book','card_id','revision','scheduler_json','introduced_at'),
 ('id','book','card_id','answered_at','day','rating','duration_ms','phase','undone',
  'before_json','after_json','before_introduced_at','revision_after'),
 ('book','review_id'), ('request_id','payload_hash','review_id'),
 ('book','card_id','flag','suspended','buried_until','note'),
 ('request_id','payload_hash'), ('id','value'), ('name','seq'))))
PRIMARY_KEYS = dict(zip(TABLES, (('key',),('book',),('book','card_id'),('id',),('book',),
 ('request_id',),('book','card_id'),('request_id',),('id',),('name',))))
DESCRIPTOR = {'schema': VERSION, 'version': 1, 'tables': list(TABLES)}
_TEXT = {
 'metadata': {'key'}, 'settings': {'book'},
 'cards': {'book','card_id','scheduler_json','introduced_at'},
 'reviews': {'book','card_id','answered_at','day','phase','before_json','after_json','before_introduced_at'},
 'undo': {'book'}, 'requests': {'request_id','payload_hash'},
 'card_controls': {'book','card_id','buried_until','note'},
 'card_actions': {'request_id','payload_hash'}, 'preferences': {'value'}, 'sequences': {'name'},
}
_NULLABLE = {'cards': {'scheduler_json','introduced_at'},
             'reviews': {'before_json','before_introduced_at'},
             'undo': {'review_id'}, 'card_controls': {'buried_until'}}
_DEFAULTS = {('reviews','undone'): '0', ('card_controls','flag'): '0',
             ('card_controls','suspended'): '0', ('card_controls','note'): "''::text"}
SCHEMA = """
CREATE TABLE study_progress_metadata (key TEXT PRIMARY KEY, value BIGINT NOT NULL);
CREATE TABLE study_progress_settings (book TEXT PRIMARY KEY, new_per_day BIGINT NOT NULL,
 review_per_day BIGINT NOT NULL, desired_retention DOUBLE PRECISION NOT NULL);
CREATE TABLE study_progress_cards (book TEXT NOT NULL, card_id TEXT NOT NULL, revision BIGINT NOT NULL,
 scheduler_json TEXT, introduced_at TEXT, PRIMARY KEY(book,card_id));
CREATE TABLE study_progress_reviews (id BIGINT PRIMARY KEY, book TEXT NOT NULL, card_id TEXT NOT NULL,
 answered_at TEXT NOT NULL, day TEXT NOT NULL, rating BIGINT NOT NULL, duration_ms BIGINT NOT NULL,
 phase TEXT NOT NULL, undone BIGINT NOT NULL DEFAULT 0, before_json TEXT, after_json TEXT NOT NULL,
 before_introduced_at TEXT, revision_after BIGINT NOT NULL,
 FOREIGN KEY(book,card_id) REFERENCES study_progress_cards(book,card_id));
CREATE INDEX study_progress_reviews_book_day ON study_progress_reviews(book,day,undone);
CREATE TABLE study_progress_undo (book TEXT PRIMARY KEY, review_id BIGINT);
CREATE TABLE study_progress_requests (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
 review_id BIGINT NOT NULL REFERENCES study_progress_reviews(id));
CREATE TABLE study_progress_card_controls (book TEXT NOT NULL, card_id TEXT NOT NULL,
 flag BIGINT NOT NULL DEFAULT 0, suspended BIGINT NOT NULL DEFAULT 0, buried_until TEXT,
 note TEXT NOT NULL DEFAULT '', PRIMARY KEY(book,card_id),
 FOREIGN KEY(book,card_id) REFERENCES study_progress_cards(book,card_id));
CREATE TABLE study_progress_card_actions (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL);
CREATE TABLE study_progress_preferences (id BIGINT PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
CREATE TABLE study_progress_sequences (name TEXT PRIMARY KEY CHECK(name='reviews'),
 seq BIGINT NOT NULL CHECK(seq>=0 AND seq<=9007199254740991));
"""


def write_lock(db):
    schema = db.execute('select current_schema()').fetchone()[0]
    db.execute('select pg_advisory_xact_lock(%s)',
               (int(catalog.identity(VERSION, schema)[:15], 16),))


def validate_connection(db):
    catalog.validate(db)
    row = db.execute('select value from metadata where key=%s', (METADATA_KEY,)).fetchone()
    if row is None or row[0] != catalog.canonical(DESCRIPTOR):
        raise StorageError('missing or unsupported PostgreSQL learning storage descriptor')
    actual = {}
    for table, name, data_type, nullable, default in db.execute(
            "select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns "
            "where table_schema=current_schema() and left(table_name,15)='study_progress_' "
            "order by table_name,ordinal_position"):
        actual.setdefault(table, []).append((name, data_type, nullable, default))
    expected = {}
    for logical, table in zip(LOGICAL_TABLES, TABLES):
        expected[table] = [(name, 'text' if name in _TEXT[logical] else 'double precision'
                            if name == 'desired_retention' else 'bigint',
                            'YES' if name in _NULLABLE.get(logical, ()) else 'NO',
                            _DEFAULTS.get((logical,name))) for name in COLUMNS[table]]
    if actual != expected:
        raise StorageError('PostgreSQL learning table/column contract mismatch')
    keys = {}
    for table, names in db.execute("select t.relname,array_agg(a.attname order by u.ordinality) "
            "from pg_constraint c join pg_class t on t.oid=c.conrelid "
            "join pg_namespace n on n.oid=t.relnamespace "
            "cross join lateral unnest(c.conkey) with ordinality u(attnum,ordinality) "
            "join pg_attribute a on a.attrelid=t.oid and a.attnum=u.attnum "
            "where n.nspname=current_schema() and c.contype='p' and t.relname=any(%s) "
            "group by t.relname", (list(TABLES),)):
        keys[table] = tuple(names)
    if keys != PRIMARY_KEYS:
        raise StorageError('PostgreSQL learning primary-key contract mismatch')
    foreign = {(table, definition.replace(' ', '')) for table, definition in db.execute(
        "select t.relname,pg_get_constraintdef(c.oid) from pg_constraint c "
        "join pg_class t on t.oid=c.conrelid join pg_namespace n on n.oid=t.relnamespace "
        "where n.nspname=current_schema() and c.contype='f' and t.relname=any(%s)", (list(TABLES),))}
    if foreign != {('study_progress_reviews', 'FOREIGNKEY(book,card_id)REFERENCESstudy_progress_cards(book,card_id)'),
                   ('study_progress_requests', 'FOREIGNKEY(review_id)REFERENCESstudy_progress_reviews(id)'),
                   ('study_progress_card_controls', 'FOREIGNKEY(book,card_id)REFERENCESstudy_progress_cards(book,card_id)')}:
        raise StorageError('PostgreSQL learning foreign-key contract mismatch')
    # These three simple CHECKs have no precedence ambiguity; normalize only
    # pg_get_constraintdef's parentheses/whitespace and redundant type labels.
    def check_key(value):
        return re.sub(r'[\s()]', '', value).replace('::text', '').replace('::bigint', '').lower()

    checks = {(table, check_key(definition)) for table, definition in db.execute(
        "select t.relname,pg_get_constraintdef(c.oid) from pg_constraint c "
        "join pg_class t on t.oid=c.conrelid join pg_namespace n on n.oid=t.relnamespace "
        "where n.nspname=current_schema() and c.contype='c' and t.relname=any(%s)", (list(TABLES),))}
    if checks != {('study_progress_preferences', 'checkid=1'),
                  ('study_progress_sequences', "checkname='reviews'"),
                  ('study_progress_sequences', "checkseq>=0andseq<='9007199254740991'")}:
        raise StorageError('PostgreSQL learning CHECK contract mismatch')


def initialize_connection(db):
    """Create learning tables inside the caller's existing catalog transaction."""
    if db.info.transaction_status != TransactionStatus.INTRANS:
        raise StorageError('learning initialization requires an explicit transaction')
    catalog.validate(db)
    write_lock(db)
    present = {row[0] for row in db.execute("select table_name from information_schema.tables "
        "where table_schema=current_schema() and table_name=any(%s)", (list(TABLES),))}
    marker = db.execute('select value from metadata where key=%s', (METADATA_KEY,)).fetchone()
    if marker is not None:
        validate_connection(db)
        return
    if present:
        raise StorageError('refuse partial or unregistered PostgreSQL learning tables')
    db.execute(SCHEMA, prepare=False)
    db.execute('insert into metadata values(%s,%s)', (METADATA_KEY, catalog.canonical(DESCRIPTOR)))
    validate_connection(db)


# Literal source -> literal PG SQL. Whitespace is normalized only for matching;
# identifiers, placeholders, aliases and dialect differences are not rewritten.
SQL = {
    'DELETE FROM card_actions':
        'DELETE FROM study_progress_card_actions',
    'DELETE FROM card_controls':
        'DELETE FROM study_progress_card_controls',
    'DELETE FROM cards':
        'DELETE FROM study_progress_cards',
    'DELETE FROM preferences':
        'DELETE FROM study_progress_preferences',
    'DELETE FROM requests':
        'DELETE FROM study_progress_requests',
    'DELETE FROM reviews':
        'DELETE FROM study_progress_reviews',
    'DELETE FROM settings':
        'DELETE FROM study_progress_settings',
    'DELETE FROM undo':
        'DELETE FROM study_progress_undo',
    'INSERT INTO card_actions VALUES (?,?)':
        'INSERT INTO study_progress_card_actions VALUES (%s,%s)',
    'INSERT INTO card_controls VALUES (?,?,?,?,?,?)':
        'INSERT INTO study_progress_card_controls VALUES (%s,%s,%s,%s,%s,%s)',
    'INSERT INTO card_controls VALUES (?,?,?,?,?,?) ON CONFLICT(book,card_id) DO UPDATE SET flag=excluded.flag,suspended=excluded.suspended,buried_until=excluded.buried_until,note=excluded.note':
        'INSERT INTO study_progress_card_controls VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(book,card_id) DO UPDATE SET flag=excluded.flag,suspended=excluded.suspended,buried_until=excluded.buried_until,note=excluded.note',
    'INSERT INTO cards VALUES (?,?,?,?,?)':
        'INSERT INTO study_progress_cards VALUES (%s,%s,%s,%s,%s)',
    'INSERT INTO cards VALUES (?,?,?,NULL,NULL)':
        'INSERT INTO study_progress_cards VALUES (%s,%s,%s,NULL,NULL)',
    'INSERT INTO preferences VALUES (1,?)':
        'INSERT INTO study_progress_preferences VALUES (1,%s)',
    'INSERT INTO preferences VALUES (1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value':
        'INSERT INTO study_progress_preferences VALUES (1,%s) ON CONFLICT(id) DO UPDATE SET value=excluded.value',
    'INSERT INTO requests VALUES (?,?,?)':
        'INSERT INTO study_progress_requests VALUES (%s,%s,%s)',
    'INSERT INTO reviews (book,card_id,answered_at,day,rating,duration_ms, phase,before_json,after_json,before_introduced_at,revision_after) VALUES (?,?,?,?,?,?,?,?,?,?,?)':
        'INSERT INTO study_progress_reviews (id,book,card_id,answered_at,day,rating,duration_ms, phase,before_json,after_json,before_introduced_at,revision_after) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
    'INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)':
        'INSERT INTO study_progress_reviews VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
    'INSERT INTO settings VALUES (?,?,?,?)':
        'INSERT INTO study_progress_settings VALUES (%s,%s,%s,%s)',
    'INSERT INTO undo VALUES (?,?)':
        'INSERT INTO study_progress_undo VALUES (%s,%s)',
    "INSERT OR IGNORE INTO metadata VALUES ('revision', 0)":
        "INSERT INTO study_progress_metadata VALUES ('revision', 0) ON CONFLICT DO NOTHING",
    'INSERT OR IGNORE INTO settings VALUES (?,20,200,.9)':
        'INSERT INTO study_progress_settings VALUES (%s,20,200,.9) ON CONFLICT DO NOTHING',
    'INSERT OR IGNORE INTO undo VALUES (?,NULL)':
        'INSERT INTO study_progress_undo VALUES (%s,NULL) ON CONFLICT DO NOTHING',
    'SELECT * FROM card_controls WHERE book=?':
        'SELECT * FROM study_progress_card_controls WHERE book=%s',
    'SELECT * FROM cards WHERE book=?':
        'SELECT * FROM study_progress_cards WHERE book=%s',
    'SELECT * FROM cards WHERE book=? AND card_id=?':
        'SELECT * FROM study_progress_cards WHERE book=%s AND card_id=%s',
    'SELECT * FROM reviews WHERE book=? AND card_id=? ORDER BY id DESC LIMIT 100':
        'SELECT * FROM study_progress_reviews WHERE book=%s AND card_id=%s ORDER BY id DESC LIMIT 100',
    'SELECT * FROM reviews WHERE book=? ORDER BY id':
        'SELECT * FROM study_progress_reviews WHERE book=%s ORDER BY id',
    'SELECT * FROM reviews WHERE id=? AND book=? AND undone=0':
        'SELECT * FROM study_progress_reviews WHERE id=%s AND book=%s AND undone=0',
    'SELECT * FROM settings WHERE book=?':
        'SELECT * FROM study_progress_settings WHERE book=%s',
    'SELECT COALESCE(SUM(duration_ms),0),COALESCE(SUM(CASE WHEN day=? THEN duration_ms ELSE 0 END),0) FROM reviews WHERE book=? AND undone=0':
        'SELECT COALESCE(SUM(duration_ms),0)::bigint,COALESCE(SUM(CASE WHEN day=%s THEN duration_ms ELSE 0 END),0)::bigint FROM study_progress_reviews WHERE book=%s AND undone=0',
    "SELECT COUNT(*) AS total, COALESCE(SUM(phase='new'),0) AS new_used, COALESCE(SUM(phase='review'),0) AS review_used FROM reviews WHERE book=? AND day=? AND undone=0":
        "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN phase='new' THEN 1 ELSE 0 END),0) AS new_used, COALESCE(SUM(CASE WHEN phase='review' THEN 1 ELSE 0 END),0) AS review_used FROM study_progress_reviews WHERE book=%s AND day=%s AND undone=0",
    'SELECT COUNT(*) FROM reviews WHERE book=? AND card_id=?':
        'SELECT COUNT(*) FROM study_progress_reviews WHERE book=%s AND card_id=%s',
    'SELECT COUNT(*) FROM reviews WHERE book=? AND card_id=? AND undone=0':
        'SELECT COUNT(*) FROM study_progress_reviews WHERE book=%s AND card_id=%s AND undone=0',
    'SELECT COUNT(*),COUNT(DISTINCT card_id) FROM reviews WHERE book=? AND undone=0':
        'SELECT COUNT(*),COUNT(DISTINCT card_id) FROM study_progress_reviews WHERE book=%s AND undone=0',
    'SELECT card_id FROM card_controls WHERE book=? AND buried_until>?':
        'SELECT card_id FROM study_progress_card_controls WHERE book=%s AND buried_until>%s ORDER BY card_id COLLATE "C"',
    'SELECT card_id FROM cards WHERE book=?':
        'SELECT card_id FROM study_progress_cards WHERE book=%s',
    'SELECT day,COUNT(*) FROM reviews WHERE book=? AND undone=0 GROUP BY day ORDER BY day':
        'SELECT day,COUNT(*) FROM study_progress_reviews WHERE book=%s AND undone=0 GROUP BY day ORDER BY day',
    'SELECT payload_hash FROM card_actions WHERE request_id=?':
        'SELECT payload_hash FROM study_progress_card_actions WHERE request_id=%s',
    'SELECT rating,COUNT(*) FROM reviews WHERE book=? AND undone=0 GROUP BY rating':
        'SELECT rating,COUNT(*) FROM study_progress_reviews WHERE book=%s AND undone=0 GROUP BY rating',
    'SELECT requests.payload_hash,reviews.undone FROM requests JOIN reviews ON reviews.id=requests.review_id WHERE request_id=?':
        'SELECT study_progress_requests.payload_hash,study_progress_reviews.undone FROM study_progress_requests JOIN study_progress_reviews ON study_progress_reviews.id=study_progress_requests.review_id WHERE request_id=%s',
    'SELECT review_id FROM undo WHERE book=?':
        'SELECT review_id FROM study_progress_undo WHERE book=%s',
    'SELECT revision FROM cards WHERE book=? AND card_id=?':
        'SELECT revision FROM study_progress_cards WHERE book=%s AND card_id=%s',
    'SELECT value FROM preferences WHERE id=1':
        'SELECT value FROM study_progress_preferences WHERE id=1',
    'UPDATE card_controls SET buried_until=NULL WHERE book=? AND card_id=?':
        'UPDATE study_progress_card_controls SET buried_until=NULL WHERE book=%s AND card_id=%s',
    'UPDATE cards SET revision=?':
        'UPDATE study_progress_cards SET revision=%s',
    'UPDATE cards SET revision=? WHERE book=? AND card_id=?':
        'UPDATE study_progress_cards SET revision=%s WHERE book=%s AND card_id=%s',
    'UPDATE cards SET scheduler_json=?,introduced_at=?,revision=? WHERE book=? AND card_id=?':
        'UPDATE study_progress_cards SET scheduler_json=%s,introduced_at=%s,revision=%s WHERE book=%s AND card_id=%s',
    "UPDATE metadata SET value=MAX(value,?) WHERE key='revision'":
        "UPDATE study_progress_metadata SET value=GREATEST(value,%s) WHERE key='revision'",
    "UPDATE metadata SET value=value+1 WHERE key='revision' AND value<? RETURNING value":
        "UPDATE study_progress_metadata SET value=value+1 WHERE key='revision' AND value<%s RETURNING value",
    'UPDATE reviews SET undone=1 WHERE id=?':
        'UPDATE study_progress_reviews SET undone=1 WHERE id=%s',
    'UPDATE settings SET new_per_day=?,review_per_day=?,desired_retention=? WHERE book=?':
        'UPDATE study_progress_settings SET new_per_day=%s,review_per_day=%s,desired_retention=%s WHERE book=%s',
    'UPDATE undo SET review_id=? WHERE book=?':
        'UPDATE study_progress_undo SET review_id=%s WHERE book=%s',
    'UPDATE undo SET review_id=NULL WHERE book=?':
        'UPDATE study_progress_undo SET review_id=NULL WHERE book=%s',
}

_AUTO_REVIEW = 'INSERT INTO reviews (book,card_id,answered_at,day,rating,duration_ms, phase,before_json,after_json,before_introduced_at,revision_after) VALUES (?,?,?,?,?,?,?,?,?,?,?)'
_EXPLICIT_REVIEW = 'INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)'
_ALLOCATE = """INSERT INTO study_progress_sequences VALUES ('reviews',1)
 ON CONFLICT(name) DO UPDATE SET seq=study_progress_sequences.seq+1
 WHERE study_progress_sequences.seq<9007199254740991 RETURNING seq"""
_HIGH_WATER = """INSERT INTO study_progress_sequences VALUES ('reviews',%s)
 ON CONFLICT(name) DO UPDATE SET seq=GREATEST(study_progress_sequences.seq,excluded.seq)"""


class Row(tuple):
    def __new__(cls, values, names):
        row = super().__new__(cls, values)
        row.names = tuple(names)
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self.names.index(key)
        return super().__getitem__(key)

    def keys(self):
        return self.names


class Cursor:
    def __init__(self, cursor=None, *, lastrowid=None):
        self.cursor = cursor
        self.lastrowid = lastrowid
        self.names = [item.name for item in cursor.description] if cursor and cursor.description else []

    def fetchone(self):
        value = self.cursor.fetchone() if self.cursor else None
        return Row(value, self.names) if value is not None else None

    def fetchall(self):
        return list(self)

    def __iter__(self):
        if self.cursor:
            for value in self.cursor:
                yield Row(value, self.names)


class Connection:
    def __init__(self, raw, manager, storage):
        self.raw, self.manager = raw, manager
        self.storage = storage
        self.write = False
        self.closed = False

    def execute(self, statement, parameters=()):
        key = ' '.join(statement.split())
        try:
            if key in ('BEGIN', 'BEGIN IMMEDIATE'):
                self.write = key == 'BEGIN IMMEDIATE'
                self.raw.execute('BEGIN' if self.write else 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
                if self.write:
                    write_lock(self.raw)
                validate_connection(self.raw)
                return Cursor()
            if key not in SQL:
                raise StorageError('unregistered learning SQL statement')
            if self.raw.info.transaction_status != TransactionStatus.INTRANS:
                raise StorageError('learning SQL requires an active transaction')
            if not self.write and not key.startswith('SELECT '):
                raise StorageError('learning writes require a locked write transaction')
            parameters = tuple(parameters)
            if key == _AUTO_REVIEW:
                allocated = self.raw.execute(_ALLOCATE).fetchone()
                if allocated is None:
                    raise StorageError('review sequence reached the safe integer ceiling')
                cursor = self.raw.execute(SQL[key], (allocated[0], *parameters))
                review_id = cursor.fetchone()[0]
                return Cursor(cursor, lastrowid=review_id)
            cursor = self.raw.execute(SQL[key], parameters)
            if key == _EXPLICIT_REVIEW:
                self.raw.execute(_HIGH_WATER, (parameters[0],))
            return Cursor(cursor)
        except psycopg.Error as error:
            raise StorageError('PostgreSQL learning operation failed') from error

    def commit(self):
        try:
            self.raw.commit()
        except psycopg.Error as error:
            raise StorageError('PostgreSQL learning commit failed') from error
        self.write = False

    def rollback(self):
        try:
            self.raw.rollback()
        except psycopg.Error as error:
            raise StorageError('PostgreSQL learning rollback failed') from error
        self.write = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.manager.__exit__(None, None, None)


def canonical_rows(db):
    """Typed logical legacy rows, including transactional review high-watermark."""
    for logical, table in zip(LOGICAL_TABLES, TABLES):
        order = sql.SQL(',').join(sql.SQL('{} COLLATE "C"').format(sql.Identifier(name))
                                 if name in _TEXT[logical] else sql.Identifier(name)
                                 for name in PRIMARY_KEYS[table])
        for row in db.execute(sql.SQL('select * from {} order by {}').format(sql.Identifier(table), order)):
            yield _line('sqlite_sequence' if logical == 'sequences' else logical, row)


class PgStudyStorage:
    def __init__(self, target, *, backups):
        self.target = catalog.target(target)
        self.backups = Path(backups).expanduser().resolve()

    def initialize(self):
        try:
            with catalog.connect(self.target) as db, db.transaction():
                initialize_connection(db)
        except (psycopg.Error, ValueError) as error:
            raise StorageError('PostgreSQL learning initialization failed') from error

    def validate(self):
        try:
            with catalog.connect(self.target, readonly=True) as db, db.transaction():
                validate_connection(db)
        except (psycopg.Error, ValueError) as error:
            raise StorageError('PostgreSQL learning validation failed') from error

    def connect(self):
        manager = catalog.connect(self.target)
        try:
            raw = manager.__enter__()
            validate_connection(raw)
            return Connection(raw, manager, self)
        except (psycopg.Error, ValueError) as error:
            manager.__exit__(None, None, None)
            raise StorageError('PostgreSQL learning connection failed') from error
        except BaseException:
            manager.__exit__(None, None, None)
            raise

    def automatic_backup(self, connection, now, reason):
        if (connection.storage is not self or not connection.write or
                connection.raw.info.transaction_status != TransactionStatus.INTRANS):
            raise StorageError('PG automatic backup requires the current locked write transaction')
        if reason not in {'restore', 'upgrade'}:
            raise StorageError('unsupported automatic backup reason')
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        basename = f"progress-before-{reason}-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}.pg.jsonl.gz"
        destination = self.backups / basename
        temporary = self.backups / ('.' + basename + '.tmp')
        counts = {table: 0 for table in LOGICAL_TABLES}
        digest = hashlib.sha256()
        descriptor = None
        output = None
        owned = None
        completed = None

        def matches(path, *, sealed):
            current = os.fstat(descriptor)
            actual = path.lstat()
            if (not stat.S_ISREG(current.st_mode) or not stat.S_ISREG(actual.st_mode) or
                    stat.S_IMODE(current.st_mode) != 0o600 or stat.S_IMODE(actual.st_mode) != 0o600 or
                    (current.st_dev,current.st_ino) != owned or
                    (actual.st_dev,actual.st_ino,actual.st_size,actual.st_mtime_ns) !=
                    (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)):
                return False
            return not sealed or ((current.st_size,current.st_mtime_ns) == completed)

        def verify(path):
            if not matches(path,sealed=True):
                raise StorageError('PG backup file ownership or completed contents changed')

        try:
            # Mode is private in the creation syscall, including a permissive
            # preexisting backup directory and umask. Retain this fd until all
            # publication checks finish so its inode cannot be recycled.
            descriptor = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_EXCL,0o600)
            created = os.fstat(descriptor)
            owned = created.st_dev,created.st_ino
            output = os.fdopen(descriptor,'wb')
            os.fchmod(descriptor,0o600)
            with gzip.GzipFile(fileobj=output, mode='wb', compresslevel=6, mtime=0) as stream:
                stream.write((catalog.canonical({'schema':'study-progress-postgresql-snapshot.v1',
                    'storage':DESCRIPTOR,'columns':COLUMNS,'source_schema':self.target.schema})+'\n').encode())
                for line in canonical_rows(connection.raw):
                    name = json.loads(line)[0]
                    counts['sequences' if name == 'sqlite_sequence' else name] += 1
                    digest.update(line)
                    stream.write(line)
                stream.write((catalog.canonical({'counts':counts,'rows_sha256':digest.hexdigest()})+'\n').encode())
            output.flush()
            os.fsync(descriptor)
            written = os.fstat(descriptor)
            completed = written.st_size,written.st_mtime_ns
            verify(temporary)
            # Never overwrite a recovery artifact or follow a swapped symlink.
            os.link(temporary,destination,follow_symlinks=False)
            verify(temporary)
            verify(destination)
            temporary.unlink()
            directory = os.open(self.backups, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            verify(destination)
        except BaseException:
            # A failed exclusive open owns nothing. Keep foreign substitutions
            # and any complete published backup; preserve the original error.
            if descriptor is not None:
                try:
                    if owned is not None and matches(temporary,sealed=False):
                        temporary.unlink()
                except OSError:
                    pass
                try:
                    output.close() if output is not None else os.close(descriptor)
                except OSError:
                    pass
            raise
        output.close()
        return basename
