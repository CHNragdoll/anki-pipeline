"""Private pinned-byte QA snapshot. Default checks small metadata; --serve binds.

No directory fallback, proxying, writes API, PG connection, subprocess, installer
or production configuration exists. The launcher owns the one process/session.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import signal
import stat
import threading
import time
import uuid
from urllib.parse import urlsplit

SCHEMA = 'study-compiled-transport-private-qa.v1'
MAX_FILE = 64 * 1024 * 1024
MAX_SNAPSHOT = 300 * 1024 * 1024
MAX_ROUTES = 8192
SHA = re.compile(r'[a-f0-9]{64}')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def canonical_fd(path):
    """Open an already canonical path without following any ancestor symlink."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Canonical absolute source is required')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    finally:
        os.close(directory)


def read_pinned(path, pin, size):
    """Read each unique snapshot once, with the full fd and pathname bound."""
    path = Path(path)
    with os.fdopen(canonical_fd(path), 'rb') as stream:
        original = os.fstat(stream.fileno())
        if (not stat.S_ISREG(original.st_mode) or original.st_uid != os.geteuid()
                or original.st_size != size or not 0 <= size <= MAX_FILE):
            raise ValueError('Pinned QA source type, owner or size differs')
        raw = stream.read(size + 1)
        if (len(raw) != size or digest(raw) != pin
                or stamp(os.fstat(stream.fileno())) != stamp(original)
                or stamp(path.lstat()) != stamp(original)):
            raise ValueError('Pinned QA source changed')
        return raw, stamp(original)


def route_name(value):
    if (type(value) is not str or not value or len(value) > 512
            or value.startswith('/') or any(char in value for char in '%\\?#\x00')
            or any(part in ('', '.', '..') for part in value.split('/'))
            or not re.fullmatch(r'[A-Za-z0-9_./-]+', value)):
        raise ValueError('Invalid exact QA route')
    return value


def inspect_manifest(path, pin):
    path = Path(path).resolve(strict=True)
    directory = path.parent.lstat()
    info = path.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid()
            or stat.S_IMODE(directory.st_mode) != 0o700
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 2 * 1024 * 1024
            or not SHA.fullmatch(pin)):
        raise ValueError('External manifest must be owned/private and pinned')
    raw, _ = read_pinned(path, pin, info.st_size)
    value = json.loads(raw)
    if value.get('schema') != SCHEMA or not isinstance(value.get('routes'), list):
        raise ValueError('Unknown private QA manifest')
    if not 1 <= len(value['routes']) <= MAX_ROUTES:
        raise ValueError('QA route bound differs')
    roots = [Path(root) for root in value.get('source_roots', ())]
    if not roots or any(not root.is_absolute() or root.resolve(strict=True) != root for root in roots):
        raise ValueError('Explicit canonical source roots are required')
    routes = {}
    unique = {}
    for row in value['routes']:
        route = route_name(row['route'])
        if route in routes or not SHA.fullmatch(row.get('sha256', '')):
            raise ValueError('Duplicate route or invalid pin')
        source = Path(row['path'])
        canonical = Path(row['resolved'])
        if (not source.is_absolute() or not canonical.is_absolute()
                or source.resolve(strict=True) != canonical
                or not any(canonical.is_relative_to(root) for root in roots)
                or type(row.get('bytes')) is not int or not 0 <= row['bytes'] <= MAX_FILE):
            raise ValueError('Route source is outside its exact pinned scope')
        info = canonical.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size != row['bytes']:
            raise ValueError('Route source metadata differs')
        mime = row.get('mime') or mimetypes.guess_type(route)[0] or 'application/octet-stream'
        if '\r' in mime or '\n' in mime or not re.fullmatch(r'[a-z0-9.+-]+/[a-z0-9.+-]+', mime):
            raise ValueError('Invalid QA media type')
        # These are raw gzip carriers for browser DecompressionStream. Neither
        # Content-Encoding nor server-side decompression is applied.
        if route.endswith('.gz'):
            if mime not in ('application/gzip', 'application/octet-stream'):
                raise ValueError('Gzip carrier must retain its encoded bytes')
        key = (str(canonical), row['sha256'], row['bytes'])
        unique[key] = row['bytes']
        routes[route] = dict(row, mime=mime)
    total = sum(unique.values())
    if total > MAX_SNAPSHOT:
        raise ValueError('QA immutable response snapshot exceeds 300 MiB')
    return value, routes, total


@dataclass(frozen=True)
class Resource:
    raw: bytes
    canonical: Path
    original_stamp: tuple
    sha256: str


def make_snapshot(routes):
    cache = {}
    responses = {}
    for route, row in routes.items():
        key = (row['resolved'], row['sha256'], row['bytes'])
        if key not in cache:
            raw, identity = read_pinned(row['resolved'], row['sha256'], row['bytes'])
            cache[key] = Resource(raw, Path(row['resolved']), identity, row['sha256'])
        if Path(row['path']).resolve(strict=True) != cache[key].canonical:
            raise ValueError('Source alias changed while snapshotting')
        responses[route] = cache[key]
    return responses


def selected_route(target, host, port, routes):
    if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
        return 403, None
    try:
        parsed = urlsplit(target)
    except ValueError:
        return 404, None
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith('/'):
        return 404, None
    try:
        route = route_name(parsed.path[1:])
    except ValueError:
        return 404, None
    return (200, route) if route in routes else (404, None)


def byte_range(header, length):
    if not header:
        return 200, 0, length
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
    if not match or not any(match.groups()) or length == 0:
        raise ValueError('Unsatisfiable range')
    left, right = match.groups()
    if left:
        start = int(left)
        end = min(int(right) if right else length - 1, length - 1)
    else:
        suffix = int(right)
        if not suffix:
            raise ValueError('Unsatisfiable range')
        start, end = max(0, length - suffix), length - 1
    if start >= length or end < start:
        raise ValueError('Unsatisfiable range')
    return 206, start, end + 1


def check_used_sources(routes, responses, used):
    """After request drain, re-hash only sources used by this experiment."""
    checked = {}
    results = []
    for route in sorted(used):
        row, resource = routes[route], responses[route]
        key = (str(resource.canonical), resource.sha256)
        try:
            if Path(row['path']).resolve(strict=True) != resource.canonical:
                raise ValueError('Source alias changed')
            if key not in checked:
                with os.fdopen(canonical_fd(resource.canonical), 'rb') as stream:
                    original = os.fstat(stream.fileno())
                    if stamp(original) != resource.original_stamp:
                        raise ValueError('Source metadata changed after snapshot')
                    checksum = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        checksum.update(chunk)
                    if (checksum.hexdigest() != resource.sha256
                            or stamp(os.fstat(stream.fileno())) != resource.original_stamp
                            or stamp(resource.canonical.lstat()) != resource.original_stamp):
                        raise ValueError('Source bytes changed after snapshot')
                checked[key] = True
            results.append({'route': route, 'sha256': resource.sha256, 'source_unchanged': True})
        except (ValueError, OSError):
            results.append({'route': route, 'sha256': resource.sha256, 'source_unchanged': False})
    return results


def write_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def serve(path, pin, *, port=0):
    manifest, routes, total = inspect_manifest(path, pin)
    responses = make_snapshot(routes)
    stage = Path(path).resolve().parent
    stop, lock = threading.Event(), threading.Lock()
    used, ledger = set(), []

    def record(handler, status, route, size=0, checksum=None):
        try:
            path_only = urlsplit(handler.path).path[:512]
        except ValueError:
            path_only = handler.path.split('?', 1)[0].split('#', 1)[0][:512]
        with lock:
            if len(ledger) < 8192:
                ledger.append({'at': time.time(), 'method': handler.command[:16], 'path': path_only,
                               'route': route, 'status': status, 'bytes': size, 'sha256': checksum})

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *_):
            pass

        def do_HEAD(self):
            self.deliver(False)

        def do_GET(self):
            self.deliver(True)

        def deliver(self, body):
            status, route = selected_route(self.path, self.headers.get('Host'), self.server.server_port, routes)
            if status != 200:
                record(self, status, None)
                self.send_error(status)
                return
            row, resource = routes[route], responses[route]
            try:
                status, start, end = byte_range(self.headers.get('Range'), len(resource.raw))
            except ValueError:
                record(self, 416, route)
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{len(resource.raw)}')
                self.send_header('Content-Length', '0')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                return
            self.send_response(status)
            mime = row['mime']
            self.send_header('Content-Type', mime + ('; charset=utf-8' if mime.startswith('text/') or mime == 'application/json' else ''))
            self.send_header('Content-Length', str(end - start))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end-1}/{len(resource.raw)}')
            self.end_headers()
            with lock:
                used.add(route)
            record(self, status, route, end-start, resource.sha256)
            if body:
                try:
                    self.wfile.write(memoryview(resource.raw)[start:end])
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    pass

    class Server(ThreadingHTTPServer):
        request_queue_size = 128
        daemon_threads = False
        block_on_close = True

    server = Server(('127.0.0.1', port), Handler)
    server.timeout = .25
    token = uuid.uuid4().hex[:12]
    ready = {'state': 'ready', 'pid': os.getpid(), 'host': '127.0.0.1', 'port': server.server_port,
             'manifest_sha256': pin, 'script_sha256': digest(Path(__file__).read_bytes()),
             'snapshot_bytes': total, 'snapshot_limit_bytes': MAX_SNAPSHOT,
             'snapshot_semantics': 'One authenticated immutable byte snapshot shared by A/B; not dynamic current source',
             'urls': {variant: f'http://127.0.0.1:{server.server_port}/{variant}/index.html'
                      + ('#card=' + manifest['card_id'] if re.fullmatch(r'[a-f0-9]{64}', manifest.get('card_id', '')) else '')
                      for variant in ('A', 'B')},
             'close': 'SIGINT/SIGTERM flag only; main loop closes after request threads drain'}
    write_new(stage / ('ready-' + token + '.json'), ready)
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, lambda *_: stop.set())
    print(json.dumps(ready), flush=True)
    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        server.server_close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        proof = check_used_sources(routes, responses, used)
        write_new(stage / ('requests-' + token + '.json'), ledger)
        closed = {'state': 'closed', 'pid': os.getpid(), 'drained': True, 'request_count': len(ledger),
                  'used_source_checks': proof, 'used_sources_unchanged': all(row['source_unchanged'] for row in proof)}
        write_new(stage / ('closed-' + token + '.json'), closed)
        print(json.dumps(closed), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--serve', action='store_true')
    args = parser.parse_args()
    if args.serve:
        serve(args.manifest, args.manifest_sha256)
    else:
        _, routes, total = inspect_manifest(args.manifest, args.manifest_sha256)
        print(json.dumps({'mode': 'metadata-only-check', 'routes': len(routes), 'snapshot_planned_bytes': total,
                          'snapshot_limit_bytes': MAX_SNAPSHOT, 'resource_bytes_hashed': False,
                          'socket_bound': False, 'production_written': False, 'pg_connected': False}))


if __name__ == '__main__':
    main()
