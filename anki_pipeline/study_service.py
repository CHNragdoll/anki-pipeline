"""Explicit PostgreSQL study-service launcher, with dual-loopback request drain.

Run ``python -m anki_pipeline.study_service --config /private/service.json``.
No configuration, directory, database or socket is accessed during import. This
launcher validates existing migrated state; it never initializes or seeds it.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import partial
import json
import os
from pathlib import Path
import signal
import stat
import sys
import threading
from typing import Callable

from . import study_catalog as catalog
from .preview_static_mounts import StaticMounts
from .study_audio import AudioBalancer
from .study_http import StudyHandler, create_server
from .study_progress import StudyStore
from .study_progress_pg import PgStudyStorage
from .study_service_catalog import load_books


class ServiceError(ValueError):
    """A safe, noncredential-bearing launcher diagnostic."""


@dataclass(frozen=True)
class ServiceConfig:
    target: catalog.Target = field(repr=False)
    document_root: Path
    registry_path: Path
    static_mounts_path: Path | None
    backups_path: Path
    audio_cache_path: Path
    port: int
    config_path: Path


@dataclass(frozen=True)
class Dependencies:
    """Injection seams for small fixtures; defaults use the real common stack."""
    connect: Callable = catalog.connect
    load_books: Callable = load_books
    storage_factory: Callable = PgStudyStorage
    store_factory: Callable = StudyStore
    server_factory: Callable = create_server
    audio_factory: Callable = AudioBalancer


def _json_file(path, *, private=False):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_size > 1024 * 1024 or
            private and (before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600)):
        raise ServiceError('configuration must be an owned regular file with appropriate private permissions')
    stamp = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    with os.fdopen(os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)), 'rb') as stream:
        if stamp(os.fstat(stream.fileno())) != stamp(before):
            raise ServiceError('configuration identity changed')
        raw = stream.read(1024 * 1024 + 1)
        if (len(raw) != before.st_size or stamp(os.fstat(stream.fileno())) != stamp(before) or
                stamp(path.lstat()) != stamp(before)):
            raise ServiceError('configuration changed during read')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ServiceError('duplicate configuration field')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ServiceError('nonfinite configuration value')))


def _absolute(value):
    if type(value) is not str or not value or '\x00' in value or not Path(value).is_absolute():
        raise ServiceError('explicit absolute configuration paths are required')
    return Path(value).resolve()


def load_config(path):
    """Read one explicit private JSON configuration, without environment fallbacks."""
    try:
        path = _absolute(os.fspath(path))
        value = _json_file(path, private=True)
        names = {'schema','postgres','document_root','registry_path','static_mounts_path',
                 'backups_path','audio_cache_path','port'}
        if (type(value) is not dict or set(value) != names or value['schema'] != 'study-service.v1' or
                type(value['postgres']) is not dict or set(value['postgres']) != {'dsn','schema'} or
                type(value['postgres']['dsn']) is not str or not value['postgres']['dsn'].strip() or
                '\x00' in value['postgres']['dsn'] or type(value['postgres']['schema']) is not str or
                type(value['port']) is not int or not 0 <= value['port'] <= 65535):
            raise ServiceError('invalid explicit study service configuration')
        return ServiceConfig(target=catalog.Target(value['postgres']['dsn'], value['postgres']['schema']),
            document_root=_absolute(value['document_root']), registry_path=_absolute(value['registry_path']),
            static_mounts_path=None if value['static_mounts_path'] is None else _absolute(value['static_mounts_path']),
            backups_path=_absolute(value['backups_path']), audio_cache_path=_absolute(value['audio_cache_path']),
            port=value['port'], config_path=path)
    except ServiceError:
        raise
    except Exception as error:
        raise ServiceError('cannot read study service configuration') from error


def _private_directory(path):
    # mkdir never changes the permissions of an existing path. Reject an unsafe
    # pre-existing directory rather than silently taking over or chmodding it.
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ServiceError('backup and audio directories must already be private or new')


class _QuietStudyHandler(StudyHandler):
    def log_message(self, *_):
        # URLs, client-supplied fields and exception strings never reach the
        # service status log. All original request/response methods are reused.
        pass


def _quiet_server(server, log):
    handler = server.RequestHandlerClass
    if not isinstance(handler, partial) or handler.func is not StudyHandler:
        raise ServiceError('unsupported study HTTP handler factory')
    server.RequestHandlerClass = partial(_QuietStudyHandler, *handler.args, **handler.keywords)
    server.handle_error = lambda *_: _emit(log, {'state':'request_failed'})
    server.daemon_threads = False
    server.block_on_close = True


def _log(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def _emit(log, value):
    # A closed status pipe must never prevent listener/request cleanup.
    try:
        log(value)
    except Exception:
        pass


class StudyService:
    """Own already-bound listeners, accept loops, and every request thread."""
    def __init__(self, servers, *, stop_event=None, log=None):
        self.servers = tuple(servers)
        self.port = self.servers[0].server_port
        self.threads = []
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.log = log if log is not None else _log
        self._lock = threading.RLock()
        self._closed = False
        self._started = False
        self._failed = False

    def request_stop(self, *_):
        # Thread control path: no shutdown(), joining, printing, or PG work.
        self.stop_event.set()

    def _serve(self, server):
        try:
            server.serve_forever(poll_interval=.05)
        except Exception:
            self._failed = True
        finally:
            self.stop_event.set()

    def start(self):
        with self._lock:
            if self._closed or self._started:
                raise ServiceError('study service cannot be started twice')
            self._started = True
            try:
                for index, server in enumerate(self.servers):
                    worker = threading.Thread(target=self._serve, args=(server,), name=f'study-http-{index}', daemon=False)
                    worker.start()
                    self.threads.append(worker)
                _emit(self.log, {'state':'ready','backend':'postgresql','port':self.port,'listeners':2})
            except BaseException as error:
                self.close()
                if isinstance(error, (KeyboardInterrupt,SystemExit)):
                    raise
                raise ServiceError('cannot start study accept loops') from error
        return self

    def close(self):
        """Stop both accept loops, then wait for all in-flight handlers to finish.

        There is deliberately no forced timeout or successful-drain claim while
        any request thread is still running. Call request_stop() from handlers;
        shutdown/close belongs to a separate lifecycle thread.
        """
        if threading.current_thread() in self.threads:
            raise ServiceError('service accept workers cannot close themselves')
        with self._lock:
            if self._closed:
                return
            self.stop_event.set()
            _emit(self.log, {'state':'stopping'})
            try:
                for server, worker in zip(self.servers, self.threads):
                    if worker.is_alive():
                        server.shutdown()
                for worker in self.threads:
                    worker.join()
            finally:
                for server in self.servers:
                    server.server_close()  # Non-daemon request threads are joined here.
            self._closed = True
            _emit(self.log, {'state':'stopped','drained':True})

    def serve(self, signal_requested=None):
        try:
            if signal_requested is not None and signal_requested():
                self.request_stop()
            if not self.stop_event.is_set():
                self.start()
            while not self.stop_event.wait(.05):
                if signal_requested is not None and signal_requested():
                    break
        finally:
            self.close()
        if self._failed:
            raise ServiceError('study HTTP accept loop failed')


def build_service(config, *, dependencies=None, log=None, stop_event=None):
    """Authenticate existing PG/books and bind both loopbacks, without seeding."""
    if not isinstance(config, ServiceConfig):
        raise ServiceError('an explicit loaded ServiceConfig is required')
    deps = dependencies if dependencies is not None else Dependencies()
    emit = log if log is not None else _log
    servers = []
    try:
        if not config.document_root.is_dir():
            raise ServiceError('document root must be an existing directory')
        mounts = None if config.static_mounts_path is None else StaticMounts.load(config.static_mounts_path)
        public = [config.document_root]
        if mounts is not None:
            public.extend(paths[key] for paths in mounts.mounts.values() for key in ('export','cards','media'))
            public.extend(paths['catalog'] for paths in mounts.mounts.values())
        private = [config.config_path,config.registry_path,config.backups_path,config.audio_cache_path]
        if config.static_mounts_path is not None:
            private.append(config.static_mounts_path)
        if any(path.is_relative_to(root) for path in private for root in public):
            raise ServiceError('configuration and private storage must remain outside all HTTP roots')
        registry = _json_file(config.registry_path)
        _private_directory(config.backups_path)
        _private_directory(config.audio_cache_path)
        with deps.connect(config.target, readonly=True) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            books = deps.load_books(db, document_root=config.document_root, registry=registry)
        storage = deps.storage_factory(config.target, backups=config.backups_path)
        store = deps.store_factory(None, books, storage=storage)
        audio = deps.audio_factory(config.document_root, config.audio_cache_path,
            {card['previewUrl'] for book in books.values() for card in book['cards']}, static_mounts=mounts)
        for host in ('127.0.0.1','::1'):
            selected_port = config.port if not servers else servers[0].server_port
            server = deps.server_factory(store, config.document_root, host=host, port=selected_port,
                                         static_mounts=mounts, audio_balancer=audio)
            servers.append(server)
            _quiet_server(server, emit)
        return StudyService(servers, stop_event=stop_event, log=emit)
    except BaseException as error:
        for server in servers:
            server.server_close()
        if isinstance(error, (KeyboardInterrupt,SystemExit)):
            raise
        if isinstance(error,ServiceError):
            raise
        raise ServiceError('cannot construct the study service') from error


@contextmanager
def _signals():
    if threading.current_thread() is not threading.main_thread():
        raise ServiceError('signal handling belongs to the main thread')
    previous = {}
    requested = False
    def stop(*_):
        # A Python signal callback may interrupt Event.wait() while its lock is
        # held. Only assign a flag here; the lifecycle loop observes it without
        # acquiring locks, printing, or joining from the signal callback.
        nonlocal requested
        requested = True
    try:
        for signum in (signal.SIGINT,signal.SIGTERM):
            previous[signum] = signal.signal(signum, stop)
        yield lambda: requested
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run(config, *, dependencies=None, log=None, stop_event=None, handle_signals=True):
    """Run until a stop request, returning only after complete request drain."""
    from contextlib import nullcontext
    event = stop_event if stop_event is not None else threading.Event()
    with _signals() if handle_signals else nullcontext() as signal_requested:
        service = build_service(config, dependencies=dependencies, log=log, stop_event=event)
        service.serve(signal_requested)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the explicit loopback PostgreSQL study service')
    parser.add_argument('--config',required=True,help='absolute path to private study-service.v1 JSON')
    args = parser.parse_args(argv)
    try:
        run(load_config(args.config))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        # Exception messages/chains may contain a DSN or filesystem details.
        # Never print them, the config object, environment, or a traceback.
        print(json.dumps({'state':'failed','error':'study_service_failed'}),file=sys.stderr,flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
