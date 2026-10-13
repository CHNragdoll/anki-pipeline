#!/usr/bin/env python3
"""Expose existing preview services on a LAN IP without restarting loopback apps."""
from __future__ import annotations

import argparse
import base64
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
from pathlib import Path
import re
import threading
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
FORWARD_HEADERS = ('Accept', 'Range', 'Content-Type', 'X-Study-Request')
SKIP_HEADERS = {'connection', 'transfer-encoding', 'server', 'date', 'content-length',
                'etag', 'last-modified', 'cache-control', 'set-cookie'}


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
    """Content-addressed documents must keep their original HTTP bytes."""
    for _ in range(5):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    return (any(part in {'history', 'cards', 'sources', 'evidence'} for part in path.split('/'))
            or bool(re.search(r'/[a-fA-F0-9]{64}\.html?$', path)))


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
        connection = HTTPConnection('127.0.0.1', port, timeout=60)
        try:
            # GET for HEAD keeps lengths correct after text URL substitutions.
            connection.request('GET' if method == 'HEAD' else method,
                               self.path, body=body, headers=headers)
            response = connection.getresponse()
            mime = response.getheader('Content-Type', '').split(';', 1)[0].lower()
            textual = mime in TEXT_TYPES
            payload = None
            if textual:
                raw = response.read()
                if (mime in {'text/javascript', 'application/javascript'} and response.status == 200
                        and parsed.path == AUXILIARY_LINK_ASSET):
                    payload = bootstrap_auxiliary_links(raw, parsed.path)
                else:
                    payload = rewrite_text(raw, self.server.lan_ip, port, parsed.path)
            if mime == 'text/html' and response.status == 200:
                payload = bootstrap_hash_runtime(payload, parsed.path)
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in SKIP_HEADERS:
                    if key.lower() == 'location':
                        value = rewrite_text(value.encode(), self.server.lan_ip, port, '').decode()
                    self.send_header(key, value)
            length = str(len(payload)) if payload is not None else response.getheader('Content-Length')
            if length is not None:
                self.send_header('Content-Length', length)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if method != 'HEAD':
                if payload is not None:
                    self.wfile.write(payload)
                else:
                    while chunk := response.read(1024 * 1024):
                        self.wfile.write(chunk)
        except (OSError, TimeoutError):
            # Browser navigation may close an outstanding large catalog request.
            self.log_error('Preview request closed or loopback service unavailable')
        finally:
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
    server = ThreadingHTTPServer((lan_ip, port), LanPreviewHandler)
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
