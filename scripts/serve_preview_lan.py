#!/usr/bin/env python3
"""Expose existing preview services on a LAN IP without restarting loopback apps."""
from __future__ import annotations

import argparse
import base64
from collections import OrderedDict
import errno
import gzip
import hashlib
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import re
import threading
import time
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5'
LATEST = '/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/runtime-candidate-overlay-v4'
MATERIAL = RUNTIME / 'ui-runtime/material-from-git-index.css'
MATERIAL_SHA = 'd8870ea69da54a28187edaafe91c3fcad27f39475ea6efd066a596d197c52f94'
LAN_HASH_RUNTIME = ROOT / 'scripts/lan_sha256.js'
LAN_HASH_SHA = '5e4026b6f4d092924ef92ef8552882815df43614efa70a8bd6e20904f3a91075'
LAN_HASH_URL = '/_preview_lan_sha256.js'
LAN_LINK_RUNTIME = ROOT / 'scripts/lan_links.js'
LAN_LINK_SHA = '0bbbc9deedde4b44f38c83d86c6d099c66d7a7e331524e0b9dfb8fb75e2c040f'
LAN_LINK_URL = '/_preview_lan_links.js'
AUXILIARY_LINK_ASSET = ('/residual-optimization-20261013/engineering/preview-own/'
                       'root-full-preview-v1/assets/auxiliary-chunks.js')
TEXT_TYPES = {'text/html', 'text/javascript', 'application/javascript', 'text/css'}
COMPRESSIBLE_TYPES = TEXT_TYPES | {'application/json', 'image/svg+xml', 'text/plain'}
FORWARD_HEADERS = ('Accept', 'Range', 'Content-Type', 'X-Study-Request')
SKIP_HEADERS = {'connection', 'transfer-encoding', 'server', 'date', 'content-length',
                'etag', 'last-modified', 'cache-control', 'set-cookie', 'vary'}
GZIP_CACHE_BYTES = 16 * 1024 * 1024
IMMUTABLE_CACHE = 'private, max-age=31536000, immutable'
IMMUTABLE_MAX_BYTES = 16 * 1024 * 1024
IMMUTABLE_TYPES = COMPRESSIBLE_TYPES | {
    'application/gzip', 'application/octet-stream', 'image/png', 'image/jpeg',
    'image/gif', 'image/webp', 'image/x-icon', 'audio/mpeg', 'audio/ogg',
    'audio/wav', 'font/woff', 'font/woff2',
}
UPSTREAM_CONNECT_TIMEOUT = 3
UPSTREAM_READ_TIMEOUT = 60
_gzip_cache: OrderedDict[str, bytes] = OrderedDict()
_gzip_cache_size = 0
_gzip_lock = threading.Lock()


def accepts_gzip(value: str) -> bool:
    qualities = {}
    for part in value.lower().split(','):
        name, *parameters = part.strip().split(';')
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith('q='):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        qualities[name] = quality if 0 <= quality <= 1 else 0.0
    return qualities.get('gzip', qualities.get('*', 0.0)) > 0


def static_representation(payload: bytes, accept_encoding: str) -> tuple[bytes, str | None, str]:
    """Lossless transport compression, bounded across all books and URLs."""
    global _gzip_cache_size
    digest = hashlib.sha256(payload).hexdigest()
    encoding = None
    if len(payload) >= 1024 and accepts_gzip(accept_encoding):
        with _gzip_lock:
            compressed = _gzip_cache.get(digest)
            if compressed is not None:
                _gzip_cache.move_to_end(digest)
        if compressed is None:
            compressed = gzip.compress(payload, compresslevel=4, mtime=0)
            if len(compressed) < len(payload) and len(compressed) <= GZIP_CACHE_BYTES:
                with _gzip_lock:
                    if digest not in _gzip_cache:
                        _gzip_cache[digest] = compressed
                        _gzip_cache_size += len(compressed)
                        while _gzip_cache_size > GZIP_CACHE_BYTES:
                            _, removed = _gzip_cache.popitem(last=False)
                            _gzip_cache_size -= len(removed)
        if len(compressed) < len(payload):
            payload, encoding = compressed, 'gzip'
            digest = hashlib.sha256(payload).hexdigest()
    return payload, encoding, f'"sha256-{digest}"'


def etag_matches(header: str, etag: str) -> bool:
    return any(value.strip() == '*' or value.strip().removeprefix('W/') == etag
               for value in header.split(','))


def content_address(path: str) -> str | None:
    """Recognize digest filenames, never a mutable study API or ordinary name.

    Native _rb_ images use 96-bit SHA-256 prefixes; the other accepted assets
    carry the full 256-bit digest. A name alone does not grant caching: callers
    must also verify it against the complete, unmodified response bytes.
    """
    for _ in range(5):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    if path.startswith('/api/'):
        return None
    name = path.rsplit('/', 1)[-1]
    full = re.fullmatch(r'[A-Za-z0-9_-]*?([a-f0-9]{64})\.'
                        r'(?:js|css|json|png|jpe?g|gif|webp|svg|ico|mp3|ogg|wav|woff2?)(?:\.gz)?', name)
    native = re.fullmatch(r'_rb_([a-f0-9]{24})\.(?:png|jpe?g|gif|webp|svg|ico)', name)
    match = full or native
    return match[1] if match else None


def open_upstream(port: int, method: str, path: str, body: bytes | None, headers: dict):
    """Retry only a transient connect failure before sending a safe request."""
    attempts = 2 if method in {'GET', 'HEAD'} else 1
    transient = {errno.ECONNRESET, errno.ECONNREFUSED, errno.ETIMEDOUT,
                 errno.EAGAIN, errno.ENOBUFS, errno.EINVAL}
    # macOS can report EINVAL when a saturated loopback accept queue resets the
    # connection during connect(). Do not retry request/response/body failures.
    for attempt in range(attempts):
        connection = HTTPConnection('127.0.0.1', port, timeout=UPSTREAM_CONNECT_TIMEOUT)
        try:
            connection.connect()
        except OSError as exc:
            connection.close()
            if attempt + 1 < attempts and (isinstance(exc, TimeoutError) or exc.errno in transient):
                time.sleep(0.02)
                continue
            raise
        try:
            connection.sock.settimeout(UPSTREAM_READ_TIMEOUT)
            # GET for HEAD keeps lengths correct after text substitutions.
            connection.request('GET' if method == 'HEAD' else method, path, body=body, headers=headers)
            return connection, connection.getresponse()
        except BaseException:
            connection.close()
            raise
    raise AssertionError('The bounded upstream connection loop did not return')


class LanPreviewServer(ThreadingHTTPServer):
    # A browser can request more than five resources at once, and several LAN
    # devices must not compete for the stdlib's very small default accept queue.
    request_queue_size = 128
    daemon_threads = True


def valid_path(target: str) -> bool:
    """Never turn an absolute URL or an encoded traversal into a proxy target."""
    try:
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
            return False
        path = parsed.path
        for _ in range(5):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        parts = path.split('/')
        return not ('%' in path or '\\' in path or '\x00' in path
                    or any(part.startswith('.') for part in parts if part)
                    or Path(path).suffix.lower() in {'.py', '.db', '.sqlite', '.sqlite3', '.toml'})
    except ValueError:
        return False


def signed_evidence_path(path: str) -> bool:
    """Pinned documents and registered media keep their original HTTP bytes."""
    for _ in range(5):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    # Native loaders verify the registered text after script execution. Even a
    # reader-origin substitution would invalidate that original text's pin.
    pinned_media = re.fullmatch(r'_(?:(?:ac|as|af)_[a-f0-9]{24}|study_[a-f0-9]{64})\.js',
                                path.rsplit('/', 1)[-1])
    return (any(part in {'history', 'cards', 'sources', 'evidence'} for part in path.split('/'))
            or bool(re.search(r'/[a-fA-F0-9]{64}\.html?$', path)) or bool(pinned_media))


def rewrite_text(payload: bytes, lan_ip: str, port: int, path: str) -> bytes:
    if signed_evidence_path(path):
        return payload
    for source_port in (8771, 8765):
        destination = f'http://{lan_ip}:{source_port}'.encode()
        for host in ('localhost', '127.0.0.1', '[::1]'):
            payload = payload.replace(f'http://{host}:{source_port}'.encode(), destination)
    if port == 8771 and path in ('/', '/index.html'):
        for old, book in (('/redbook-20261004/preview-library.html', 'redbook'),
                          ('/redbook-2027-20261006/preview-library.html', 'redbook2027')):
            payload = payload.replace(f'href="{old}"'.encode(),
                                      f'href="{LATEST}/{book}/preview-library.html"'.encode())
    return payload


def bootstrap_hash_runtime(payload: bytes, path: str) -> bytes:
    """Add pinned LAN companions to shells; signed evidence bytes stay intact."""
    if signed_evidence_path(path):
        return payload
    head = re.search(br'<head(?:\s[^>]*)?>', payload, re.I)
    if not head:
        return payload
    scripts = []
    for url, checksum in ((LAN_HASH_URL, LAN_HASH_SHA), (LAN_LINK_URL, LAN_LINK_SHA)):
        if not checksum or url.encode() in payload:
            continue
        integrity = base64.b64encode(bytes.fromhex(checksum)).decode('ascii')
        scripts.append((f'<script src="{url}" integrity="sha256-{integrity}" '
                        'crossorigin="anonymous"></script>').encode('ascii'))
    return payload[:head.end()] + b''.join(scripts) + payload[head.end():]


def bootstrap_auxiliary_links(payload: bytes, path: str) -> bytes:
    """The approved unsealed auxiliary asset keeps its exact bytes as prefix."""
    if path != AUXILIARY_LINK_ASSET:
        return payload
    integrity = base64.b64encode(bytes.fromhex(LAN_LINK_SHA)).decode('ascii')
    suffix = ('\n;/* LAN reader links companion for this auxiliary asset only. */\n'
              '(function(){"use strict";'
              'if(window.AnkiLanLinksRuntime){window.AnkiLanLinksRuntime.install(document);return;}'
              f'if(document.querySelector(\'script[src="{LAN_LINK_URL}"]\'))return;'
              'var script=document.createElement("script");'
              f'script.src="{LAN_LINK_URL}";script.integrity="sha256-{integrity}";'
              'script.crossOrigin="anonymous";script.async=false;'
              '(document.head||document.documentElement).appendChild(script);})();\n').encode('ascii')
    return payload if payload.endswith(suffix) else payload + suffix


class LanPreviewHandler(BaseHTTPRequestHandler):
    def _allowed_client(self) -> bool:
        try:
            host = urlsplit('http://' + self.headers.get('Host', ''))
            return (ipaddress.ip_address(self.client_address[0]) in self.server.lan_network
                    and host.netloc == f'{self.server.lan_ip}:{self.server.server_port}'
                    and not host.path and not host.query and not host.fragment)
        except ValueError:
            return False

    def forward(self, method: str):
        if not self._allowed_client() or not valid_path(self.path):
            self.send_error(403)
            return
        parsed = urlsplit(self.path)
        port = self.server.backend_port
        body = None
        headers = {key: self.headers[key] for key in FORWARD_HEADERS if key in self.headers}
        if method == 'POST':
            # Retain the original study API's same-origin/custom-header gate.
            if (port != 8771 or not parsed.path.startswith('/api/study/')
                    or self.headers.get('Origin') != f'http://{self.server.lan_ip}:{self.server.server_port}'
                    or self.headers.get('X-Study-Request') != '1'
                    or self.headers.get_content_type() != 'application/json'
                    or self.headers.get('Transfer-Encoding')):
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 <= length <= 128 * 1024 * 1024:
                    raise ValueError()
            except ValueError:
                self.send_error(413)
                return
            body = self.rfile.read(length)
            headers['Origin'] = f'http://127.0.0.1:{port}'
        if parsed.path in (LAN_HASH_URL, LAN_LINK_URL):
            runtime, checksum = ((LAN_HASH_RUNTIME, LAN_HASH_SHA) if parsed.path == LAN_HASH_URL
                                 else (LAN_LINK_RUNTIME, LAN_LINK_SHA))
            payload = runtime.read_bytes()
            if hashlib.sha256(payload).hexdigest() != checksum:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if method != 'HEAD':
                self.wfile.write(payload)
            return
        if port == 8765 and parsed.path == '/exam-library/ui/material.css':
            payload = MATERIAL.read_bytes()
            if hashlib.sha256(payload).hexdigest() != MATERIAL_SHA:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/css')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if method != 'HEAD':
                self.wfile.write(payload)
            return
        headers['Accept-Encoding'] = 'identity'
        connection = None
        response_started = False
        try:
            connection, response = open_upstream(port, method, self.path, body, headers)
            mime = response.getheader('Content-Type', '').split(';', 1)[0].lower()
            full_response = response.status == 200 and not self.headers.get('Range')
            plaintext = not response.getheader('Content-Encoding')
            textual = mime in TEXT_TYPES and full_response and plaintext
            cacheable = (method in {'GET', 'HEAD'} and full_response and plaintext
                         and not parsed.path.startswith('/api/')
                         and mime in COMPRESSIBLE_TYPES)
            address = content_address(parsed.path) if method in {'GET', 'HEAD'} and full_response and plaintext else None
            try:
                bounded_asset = (address is not None and mime in IMMUTABLE_TYPES
                                 and 0 <= int(response.getheader('Content-Length', '-1')) <= IMMUTABLE_MAX_BYTES)
            except ValueError:
                bounded_asset = False
            payload = None
            immutable = False
            if textual or cacheable or bounded_asset:
                raw = response.read()
                if (mime in {'text/javascript', 'application/javascript'}
                        and parsed.path == AUXILIARY_LINK_ASSET):
                    payload = bootstrap_auxiliary_links(raw, parsed.path)
                elif textual:
                    payload = rewrite_text(raw, self.server.lan_ip, port, parsed.path)
                else:
                    payload = raw
            if mime == 'text/html' and textual:
                payload = bootstrap_hash_runtime(payload, parsed.path)
            if bounded_asset and payload == raw:
                immutable = hashlib.sha256(raw).hexdigest().startswith(address)
            cacheable = cacheable or immutable
            cache_control = IMMUTABLE_CACHE if immutable else 'no-cache' if cacheable else 'no-store'
            encoding = etag = None
            if cacheable:
                payload, encoding, etag = static_representation(
                    payload, self.headers.get('Accept-Encoding', '') if mime in COMPRESSIBLE_TYPES else '')
                if etag_matches(self.headers.get('If-None-Match', ''), etag):
                    self.send_response(304)
                    response_started = True
                    self.send_header('ETag', etag)
                    self.send_header('Vary', 'Accept-Encoding')
                    self.send_header('Cache-Control', cache_control)
                    self.end_headers()
                    return
            self.send_response(response.status, response.reason)
            response_started = True
            for key, value in response.getheaders():
                if key.lower() not in SKIP_HEADERS:
                    if key.lower() == 'location':
                        value = rewrite_text(value.encode(), self.server.lan_ip, port, '').decode()
                    self.send_header(key, value)
            length = str(len(payload)) if payload is not None else response.getheader('Content-Length')
            if length is not None:
                self.send_header('Content-Length', length)
            if encoding:
                self.send_header('Content-Encoding', encoding)
            if etag:
                self.send_header('ETag', etag)
                self.send_header('Vary', 'Accept-Encoding')
            self.send_header('Cache-Control', cache_control)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if method != 'HEAD':
                if payload is not None:
                    self.wfile.write(payload)
                else:
                    while chunk := response.read(1024 * 1024):
                        self.wfile.write(chunk)
        except (OSError, HTTPException) as exc:
            # Browser navigation may close an outstanding large catalog request.
            self.log_error('Preview request closed or loopback service unavailable (%s, errno=%s)',
                           type(exc).__name__, getattr(exc, 'errno', None))
            if not response_started:
                try:
                    self.send_error(502, 'Loopback preview service unavailable')
                except OSError:
                    pass  # The browser may have closed the socket already.
        finally:
            if connection is not None:
                connection.close()

    def do_GET(self):
        self.forward('GET')

    def do_HEAD(self):
        self.forward('HEAD')

    def do_POST(self):
        self.forward('POST')


def create_server(lan_ip: str, port: int, network: str | None = None):
    address = ipaddress.ip_address(lan_ip)
    if not address.is_private or address.is_loopback or address.is_unspecified or address.version != 4:
        raise ValueError('Use a concrete private LAN IPv4 address')
    if port not in (8771, 8765):
        raise ValueError('Only the existing preview ports are supported')
    server = LanPreviewServer((lan_ip, port), LanPreviewHandler)
    server.lan_ip = lan_ip
    server.lan_network = ipaddress.ip_network(network or f'{lan_ip}/24', strict=False)
    if address not in server.lan_network:
        server.server_close()
        raise ValueError('The bind address must belong to the LAN network')
    server.backend_port = port
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', required=True, help='Mac LAN IPv4 address')
    parser.add_argument('--network', help='Allowed LAN subnet (defaults to bind address /24)')
    args = parser.parse_args()
    servers = []
    try:
        for port in (8771, 8765):
            servers.append(create_server(args.bind, port, args.network))
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(f'LAN ready: http://{args.bind}:{server.server_port}/', flush=True)
        threading.Event().wait()
    finally:
        for server in servers:
            server.server_close()


if __name__ == '__main__':
    main()
