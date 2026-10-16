"""Optional PG17 engine archives, with an isolated, real restore rehearsal.

This is not a replacement for the JSONL v1/v2 wire contracts. The binary COPY
proof deliberately preserves scan order: equality proves complete row bytes;
inequality is *unconfirmed*, not proof of damaged data. No source payload is
converted to JSON/base64 or sorted by random content-addressed keys.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

import psycopg
from psycopg import sql

from . import study_catalog as c
from . import study_catalog_recovery as recovery


FORMAT = 'study-catalog-native-postgresql-backup.v1'
ALGORITHM = 'sha256-pg17-binary-copy-stream.v1'
DEFAULT_BIN = Path('/opt/homebrew/opt/postgresql@17/bin')
_PRIVATE = 0o600
_MANIFEST_LIMIT = 4 * 1024 * 1024


class NativeBackupError(RuntimeError):
    """An archive was not published or a private rehearsal did not complete."""


class VerificationUnconfirmed(NativeBackupError):
    """Full binary streams differ, possibly only because scan order changed."""


@dataclass(frozen=True)
class NativeBackup:
    path: Path
    manifest_sha256: str


def _identity(info):
    return info.st_dev, info.st_ino, info.st_uid


def _private(info, *, directory=False):
    return (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) and (
        info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else _PRIVATE))


def _directory_fd(path):
    """Open every canonical component without following a replaced ancestor."""
    selected = Path(path).absolute()
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in selected.parts[1:]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        return fd
    except BaseException:
        os.close(fd)
        raise


def _assert_directory(fd, path):
    following = _directory_fd(path)
    try:
        if _identity(os.fstat(fd)) != _identity(os.fstat(following)) or not _private(os.fstat(fd), directory=True):
            raise NativeBackupError('private archive directory was replaced or changed')
    finally:
        os.close(following)


def _new_directory(path):
    requested = Path(path).expanduser().absolute()
    parent = requested.parent.resolve(strict=True)
    destination = parent / requested.name
    os.mkdir(destination, 0o700)  # Exclusive: never replace any existing output.
    fd = _directory_fd(destination)
    if not _private(os.fstat(fd), directory=True):
        os.close(fd)
        raise NativeBackupError('new archive directory is not private')
    return destination, fd


def _file(fd, name):
    handle = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, _PRIVATE, dir_fd=fd)
    return os.fdopen(handle, 'w+b')


def _inventory(fd, *, sync=False):
    result = {}
    # fwalk retains directory fds; file opens never follow a symlink.
    for relative, directories, files, current in os.fwalk('.', dir_fd=fd, follow_symlinks=False):
        if not _private(os.fstat(current), directory=True):
            raise NativeBackupError('archive contains a non-private directory')
        for name in directories:
            if not _private(os.stat(name, dir_fd=current, follow_symlinks=False), directory=True):
                raise NativeBackupError('archive contains an unsafe directory')
        for name in files:
            key = str(Path(relative) / name)
            if key == 'manifest.json':
                continue
            source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
            try:
                before = os.fstat(source)
                if not _private(before):
                    raise NativeBackupError('archive contains a non-private regular file')
                digest = hashlib.sha256()
                while block := os.read(source, 1024 * 1024):
                    digest.update(block)
                after = os.fstat(source)
                named = os.stat(name, dir_fd=current, follow_symlinks=False)
                if (_identity(before), before.st_size, before.st_mtime_ns) != (
                        _identity(after), after.st_size, after.st_mtime_ns) or _identity(named) != _identity(after):
                    raise NativeBackupError('archive changed while being sealed')
                if sync:
                    os.fsync(source)
                result[key] = {'bytes': before.st_size, 'sha256': digest.hexdigest()}
            finally:
                os.close(source)
        if sync:
            os.fsync(current)
    return result


def _remove_owned(path, fd, owned):
    """Remove only recorded files; never recursively erase unclaimed entries."""
    try:
        _assert_directory(fd, path)
    except (OSError, NativeBackupError):
        return
    for name, expected in owned.items():
        try:
            current = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if _identity(current) == expected:
                os.unlink(name, dir_fd=fd)
        except FileNotFoundError:
            pass
    try:
        os.rmdir(path)
    except OSError:
        # A pg_dump directory or concurrent writer's unclaimed files remain
        # private and incomplete. Preserving them is safer than recursive erase.
        pass


def _assert_owned(fd, owned):
    for name, expected in owned.items():
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if _identity(info) != expected or not _private(info):
            raise NativeBackupError('native archive output was replaced or changed permissions')


def _programs(bin_dir):
    directory = Path(bin_dir).resolve(strict=True)
    programs = {name: directory / name for name in ('pg_dump', 'pg_restore', 'initdb', 'postgres', 'pg_ctl')}
    for name in ('pg_dump', 'pg_restore'):
        reply = subprocess.run([str(programs[name]), '--version'], check=True, capture_output=True, text=True)
        if not re.search(r'\(PostgreSQL\) 17\.', reply.stdout):
            raise NativeBackupError('native archive tools must be PostgreSQL 17')
    return programs


def _connection(value, db=None):
    options = psycopg.conninfo.conninfo_to_dict(c.target(value).dsn)
    # libpq has no SSLPASSWORD environment channel. Refuse this unsupported
    # secret before starting any native tool, instead of exposing it in argv.
    if options.get('sslpassword'):
        raise NativeBackupError('sslpassword is unsupported by the native tool credential channel')
    environment = os.environ.copy()  # Preserve libpq service/default/auth semantics.
    if db is not None:
        options.update(db.info.get_parameters())
        options.update(host=db.info.host, port=str(db.info.port), dbname=db.info.dbname, user=db.info.user)
        if options.get('sslpassword'):
            raise NativeBackupError('sslpassword is unsupported by the native tool credential channel')
        # get_parameters may retain the original multi-host hostaddr list.
        # Pin its actually connected address together with host and port.
        if db.info.hostaddr:
            options['hostaddr'] = db.info.hostaddr
        else:
            options.pop('hostaddr', None)
            environment.pop('PGHOSTADDR', None)
        # The service has already been resolved; never re-read a mutable
        # service file after pinning the effective endpoint and credentials.
        options.pop('service', None)
        environment.pop('PGSERVICE', None)
        environment.pop('PGSERVICEFILE', None)
        # Includes an effective password supplied through a service or passfile.
        options['password'] = db.info.password
    password = options.pop('password', None)
    if password is not None:
        environment['PGPASSWORD'] = password
    # No password in process arguments, manifests, repr or raised exceptions.
    return psycopg.conninfo.make_conninfo(**options), environment


def _run(arguments, *, environment=None, directory_fd=None, **kwargs):
    if directory_fd is not None:
        # macOS /dev/fd/N does not act as a directory pathname. A tiny exec-only
        # child changes directory by retained fd without a threaded preexec_fn,
        # pathname race, shell or interpolated command/connection string.
        child = 'import os,sys;os.fchdir(int(sys.argv[1]));os.execve(sys.argv[2],sys.argv[2:],os.environ)'
        arguments = [sys.executable, '-c', child, str(directory_fd), *arguments]
        kwargs['pass_fds'] = (directory_fd,)
    try:
        result = subprocess.run(arguments, env=environment, check=False, **kwargs)
    except OSError as exc:
        raise NativeBackupError('native PostgreSQL tool could not start') from exc
    if result.returncode:
        raise NativeBackupError(f'native PostgreSQL tool failed with exit status {result.returncode}; see its private log')


def _server(db):
    row = db.execute("SELECT current_setting('server_version_num')::integer,current_setting('server_encoding'),"
                     "current_database(),(SELECT oid FROM pg_database WHERE datname=current_database()),"
                     "pg_postmaster_start_time()::text,(SELECT system_identifier::text FROM pg_control_system())").fetchone()
    if row[0] // 10000 != 17 or row[1] != 'UTF8':
        raise NativeBackupError('native stream proof requires a PostgreSQL 17 UTF8 database')
    return dict(zip(('server_version_num', 'encoding', 'database', 'database_oid', 'postmaster_started', 'system_identifier'), row))


def _columns(db, name):
    return [{'name': row[0], 'type': row[1], 'nullable': row[2]} for row in db.execute(
        'SELECT a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),NOT a.attnotnull '
        'FROM pg_attribute a JOIN pg_class t ON t.oid=a.attrelid JOIN pg_namespace n ON n.oid=t.relnamespace '
        'WHERE n.nspname=current_schema() AND t.relname=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum', (name,))]


def _stream(db, name):
    digest = hashlib.sha256()
    total = 0
    prefix = bytearray()
    with db.cursor() as cursor:
        with cursor.copy(sql.SQL('COPY {} TO STDOUT (FORMAT BINARY)').format(sql.Identifier(name))) as stream:
            for block in stream:
                if len(prefix) < 19:
                    prefix.extend(block[:19-len(prefix)])
                digest.update(block)
                total += len(block)
        count = cursor.rowcount
    if bytes(prefix) != b'PGCOPY\n\xff\r\n\x00' + bytes(8):
        raise NativeBackupError('unsupported binary COPY flags or extension header')
    if type(count) is not int or count < 0:
        raise NativeBackupError('binary COPY did not complete with a row count')
    return {'columns': _columns(db, name), 'rows': count,
            'bytes': total, 'sha256': digest.hexdigest()}


def _fingerprints(db, descriptor):
    return {name: _stream(db, name) for name in descriptor['tables']}


def backup(value, destination, *, format='custom', jobs=1, bin_dir=DEFAULT_BIN):
    """Seal one exact catalog schema; source is only read in one snapshot.

    ``destination`` must be new, on local storage. A returned external manifest
    SHA is required for later restore, not a self-trusting mutable sidecar.
    Directory-format failures can leave unclaimed private partial output.
    """
    if format not in ('custom', 'directory') or type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError('unsupported native format or job count')
    if format == 'custom' and jobs != 1:
        raise ValueError('parallel pg_dump requires directory format')
    selected = c.target(value)
    connection, environment = _connection(selected)
    programs = _programs(bin_dir)
    path, fd = _new_directory(destination)
    owned = {}
    try:
        with _file(fd, 'dump.stderr') as log:
            owned['dump.stderr'] = _identity(os.fstat(log.fileno()))
            with c.connect(selected, readonly=True) as db, db.transaction():
                db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                db.execute("SET LOCAL lock_timeout='5s'")
                descriptor = c._database_backup_header(db)
                for name in descriptor['tables']:
                    db.execute(sql.SQL('LOCK TABLE {} IN ACCESS SHARE MODE').format(sql.Identifier(name)))
                source = _server(db)
                snapshot = db.execute('SELECT pg_export_snapshot()').fetchone()[0]
                connection, environment = _connection(selected, db)
                arguments = [str(programs['pg_dump']), '--dbname', connection, '--schema', selected.schema,
                             '--strict-names', '--snapshot', snapshot, '--compress=zstd:level=1',
                             '--lock-wait-timeout=5s', '--no-password', '--format', 'c' if format == 'custom' else 'd']
                started = time.monotonic()
                if format == 'directory':
                    arguments += ['--jobs', str(jobs), '--file', 'archive']
                    _run(arguments, environment=environment, directory_fd=fd,
                         stdout=subprocess.DEVNULL, stderr=log, umask=0o077)
                else:
                    with _file(fd, 'archive.dump') as output:
                        owned['archive.dump'] = _identity(os.fstat(output.fileno()))
                        _run(arguments, environment=environment, stdout=output, stderr=log, umask=0o077)
                        output.flush()
                        os.fsync(output.fileno())
                        if _identity(os.stat('archive.dump', dir_fd=fd, follow_symlinks=False)) != owned['archive.dump']:
                            raise NativeBackupError('archive output was replaced')
                dump_seconds = time.monotonic() - started
                started = time.monotonic()
                fingerprints = _fingerprints(db, descriptor)
                fingerprint_seconds = time.monotonic() - started
                if c._database_backup_header(db) != descriptor:
                    raise NativeBackupError('catalog layout changed during archive creation')
            log.flush()
            os.fsync(log.fileno())
        _assert_owned(fd, owned)
        started = time.monotonic()
        files = _inventory(fd, sync=True)
        manifest = {'schema': FORMAT, 'format': format, 'compression': 'zstd:level=1', 'jobs': jobs,
                    'source_schema': selected.schema, 'source_server': source, 'descriptor': descriptor,
                    'proof': {'algorithm': ALGORITHM, 'tables': fingerprints,
                              'scope': 'all columns and all binary COPY bytes; scan order preserved; no table OIDs'},
                    'files': files,
                    'timings': {'pg_dump_seconds': dump_seconds, 'binary_copy_proof_seconds': fingerprint_seconds,
                                'initial_file_seal_seconds': time.monotonic() - started}}
        raw = (c.canonical(manifest) + '\n').encode()
        with _file(fd, 'manifest.json') as output:
            owned['manifest.json'] = _identity(os.fstat(output.fileno()))
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(fd)
        _assert_owned(fd, owned)
        _assert_directory(fd, path)
        result = NativeBackup(path, hashlib.sha256(raw).hexdigest())
        read_manifest(result)  # Reopen and prove the published paths, not just fds.
        return result
    except BaseException:
        _remove_owned(path, fd, owned)
        raise
    finally:
        os.close(fd)


@contextmanager
def _checked_bundle(archive):
    if not isinstance(archive, NativeBackup) or not re.fullmatch('[a-f0-9]{64}', archive.manifest_sha256):
        raise ValueError('a separately pinned native archive manifest is required')
    path = Path(archive.path).absolute()
    fd = _directory_fd(path)
    try:
        _assert_directory(fd, path)
        source = os.open('manifest.json', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(source, 'rb') as stream:
            if not _private(os.fstat(stream.fileno())):
                raise NativeBackupError('manifest must be a private regular file')
            raw = stream.read(_MANIFEST_LIMIT + 1)
        if len(raw) > _MANIFEST_LIMIT or hashlib.sha256(raw).hexdigest() != archive.manifest_sha256:
            raise NativeBackupError('native manifest differs from the external pin')
        manifest = json.loads(raw)
        if manifest.get('schema') != FORMAT or manifest.get('format') not in ('custom', 'directory'):
            raise NativeBackupError('unsupported native archive manifest')
        descriptor = c._validate_backup_header(manifest.get('descriptor'))
        if manifest.get('proof', {}).get('algorithm') != ALGORITHM or set(manifest['proof']['tables']) != set(descriptor['tables']):
            raise NativeBackupError('native archive proof scope differs from the catalog contract')
        c.Target(schema=manifest['source_schema'])
        if manifest.get('source_server', {}).get('server_version_num', 0) // 10000 != 17 or manifest['source_server'].get('encoding') != 'UTF8':
            raise NativeBackupError('unsupported source engine or encoding')
        if _inventory(fd) != manifest.get('files'):
            raise NativeBackupError('native archive file bytes differ from the sealed manifest')
        expected = 'archive.dump' if manifest['format'] == 'custom' else 'archive/toc.dat'
        if expected not in manifest['files']:
            raise NativeBackupError('native archive payload is absent')
        yield manifest, fd
        _assert_directory(fd, path)
        if _inventory(fd) != manifest['files']:
            raise NativeBackupError('native archive changed while it was used')
    finally:
        os.close(fd)


def read_manifest(archive):
    with _checked_bundle(archive) as (manifest, _):
        return manifest


class PrivateRestoreCluster:
    """A disposable PG17 capability; no arbitrary restore DSN is accepted.

    The new instance has its own role namespace and Unix-only socket. It never
    changes roles, databases, ports or services in the existing source instance.
    Call ``stop()`` in a finally block or use this as a context manager. Data and
    logs remain private for operator inspection; no automatic recursive delete.
    """
    def __init__(self, destination, *, bin_dir=DEFAULT_BIN):
        self.programs = _programs(bin_dir)
        self.path, self._fd = _new_directory(destination)
        self.data = self.path / 'data'
        self.socket = self.path / 's'
        self.owner = 'study_native_owner'
        self.process = None
        self.system_identifier = None
        self._log = None
        self._closed = False

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def start(self):
        if self.process is not None or self._closed:
            raise NativeBackupError('private cluster can only start once')
        try:
            _assert_directory(self._fd, self.path)
            os.mkdir(self.socket, 0o700)
            self._log = _file(self._fd, 'postgres.log')
            _run([str(self.programs['initdb']), '-D', str(self.data), '--username', self.owner,
                  '--auth-local=trust', '--auth-host=reject', '--encoding=UTF8', '--locale=C', '--no-instructions'],
                 stdout=self._log, stderr=self._log, umask=0o077)
            self.process = subprocess.Popen([str(self.programs['postgres']), '-D', str(self.data), '-k', str(self.socket),
                                             '-h', '', '-p', '5432'], stdout=self._log, stderr=self._log, umask=0o077)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise NativeBackupError('private PostgreSQL process exited during startup')
                try:
                    with psycopg.connect(self._dsn('postgres'), connect_timeout=1, autocommit=True) as db:
                        row = db.execute("SELECT system_identifier::text FROM pg_control_system()").fetchone()
                        if db.execute("SHOW listen_addresses").fetchone()[0] != '':
                            raise NativeBackupError('private restore instance unexpectedly accepts TCP')
                        self.system_identifier = row[0]
                        return self
                except psycopg.OperationalError:
                    time.sleep(.1)
            raise NativeBackupError('private PostgreSQL startup timed out')
        except BaseException:
            self.stop()
            raise

    def _dsn(self, database):
        return psycopg.conninfo.make_conninfo(host=str(self.socket), port='5432', dbname=database, user=self.owner)

    def _check(self):
        if self._closed or self.process is None or self.process.poll() is not None:
            raise NativeBackupError('private restore instance is not running')
        _assert_directory(self._fd, self.path)
        with psycopg.connect(self._dsn('postgres'), autocommit=True, connect_timeout=2) as db:
            if db.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0] != self.system_identifier:
                raise NativeBackupError('private restore instance identity changed')
            if db.execute('SHOW listen_addresses').fetchone()[0] != '':
                raise NativeBackupError('private restore instance accepts TCP')

    def create_database(self, name=None, *, schema='study_catalog'):
        self._check()
        name = name or 'native_' + uuid.uuid4().hex
        if not re.fullmatch('native_[a-z0-9_]{1,48}', name):
            raise ValueError('private database name must use the native_ prefix')
        with psycopg.connect(self._dsn('postgres'), autocommit=True) as db:
            db.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0 ENCODING \'UTF8\'').format(sql.Identifier(name)))
        return c.Target(self._dsn(name), schema)

    @property
    def stop_command(self):
        return [str(self.programs['pg_ctl']), '-D', str(self.data), '-m', 'fast', '-w', 'stop']

    def stop(self):
        if self._closed:
            return
        try:
            if self.process is not None and self.process.poll() is None:
                # Only our retained child process, never an arbitrary PID.
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
        finally:
            if self._log is not None:
                self._log.close()
            os.close(self._fd)
            self._closed = True


def _verify(manifest, pin, target):
    selected = c.target(target)
    if selected.schema != manifest['source_schema']:
        raise NativeBackupError('native rehearsal does not remap catalog schemas')
    with c.connect(selected, readonly=True) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        restored_server = _server(db)
        descriptor = c._database_backup_header(db)
        if descriptor != manifest['descriptor']:
            raise VerificationUnconfirmed('restored table contract differs from the sealed source')
        actual = _fingerprints(db, descriptor)
        sequence_safety = recovery._sequences(db)
    if actual != manifest['proof']['tables']:
        differing = [name for name in actual if actual[name] != manifest['proof']['tables'][name]]
        raise VerificationUnconfirmed('binary COPY stream not confirmed for tables: ' + ', '.join(differing)
                                      + '; scan-order differences require a separate canonical reconciliation')
    return {'schema': 'study-catalog-native-restore-verification.v1', 'complete': True,
            'algorithm': ALGORITHM, 'manifest_sha256': pin,
            'tables': actual, 'restored_server': restored_server,
            'identity_sequences': sequence_safety,
            'identity_sequence_scope': 'future insert safety; PG identity sequences are not MVCC snapshot rows',
            'scope': 'all registered table columns and complete binary row streams; order preserved'}


def verify_restored(archive, target):
    """Read-only complete stream proof; mismatch is explicitly unconfirmed."""
    with _checked_bundle(archive) as (manifest, _):
        return _verify(manifest, archive.manifest_sha256, target)


def restore_and_verify(archive, cluster, *, database_name=None):
    """Restore only into a fresh DB in a retained private-instance capability."""
    if not isinstance(cluster, PrivateRestoreCluster):
        raise ValueError('native restore requires a private-instance capability, never an arbitrary DSN')
    cluster._check()
    with _checked_bundle(archive) as (manifest, fd):
        target = cluster.create_database(database_name, schema=manifest['source_schema'])
        connection, environment = _connection(target)
        archive_name = 'archive.dump' if manifest['format'] == 'custom' else 'archive'
        log_name = 'restore-' + uuid.uuid4().hex + '.log'
        with _file(cluster._fd, log_name) as log:
            _run([str(cluster.programs['pg_restore']), '--dbname', connection, '--no-password', '--no-owner',
                  '--no-privileges', '--exit-on-error', '--single-transaction', archive_name],
                 environment=environment, directory_fd=fd,
                 stdout=log, stderr=log, umask=0o077)
        report = _verify(manifest, archive.manifest_sha256, target)
        return target, report
