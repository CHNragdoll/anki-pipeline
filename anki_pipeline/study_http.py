"""Injectable loopback study HTTP transport; no catalogs, paths or services load at import."""
from __future__ import annotations

import io
import ipaddress
import json
import re
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .preview_static_mounts import MountDenied, StaticMounts, request_path
from .study_progress import StudyStore

MAX_BODY_BYTES = 128 * 1024 * 1024


class StudyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, store, directory, audio_balancer=None, static_mounts=None, **kwargs):
        if static_mounts is not None and not isinstance(static_mounts, StaticMounts):
            raise TypeError('static_mounts must be an approved StaticMounts instance')
        self.static_mounts = static_mounts
        self.store = store
        self.audio_balancer = audio_balancer
        self.document_root = Path(directory).resolve()
        super().__init__(*args, directory=str(directory), **kwargs)

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _allowed_host(self) -> bool:
        try:
            host = urlsplit('http://' + self.headers.get('Host', ''))
            return (host.hostname in {'localhost', '127.0.0.1', '::1'}
                    and host.port == self.server.server_port and not host.username
                    and not host.password and not host.path and not host.query and not host.fragment
                    and ipaddress.ip_address(self.client_address[0]).is_loopback)
        except ValueError:
            return False

    def _same_origin(self) -> bool:
        origin = self.headers.get('Origin')
        if origin is None:
            return True  # Required custom header still prevents simple cross-origin POSTs.
        return origin == 'http://' + self.headers.get('Host', '')

    def _route(self, method: str, payload=None):
        parsed = urlsplit(self.path)
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        try:
            result = self.store.dispatch(method, parsed.path, query, payload or {})
            self._json(200, result)
        except Exception as exc:
            status = getattr(exc, 'status', 500)
            message = getattr(exc, 'message', '操作失败，进度未保存，请重试。')
            if status == 500:
                self.log_error('API failed: %s', type(exc).__name__)
            self._json(status, {'error': message})

    def do_GET(self):
        if not self._allowed_host():
            self._json(403, {'error': '仅允许本机书架地址'})
            return
        if urlsplit(self.path).path == '/api/study/delivery':
            self._delivery()
        elif urlsplit(self.path).path == '/api/study/audio-balanced':
            self._audio()
        elif urlsplit(self.path).path.startswith('/api/study/'):
            self._route('GET')
        else:
            super().do_GET()

    def _delivery(self):
        # This capability is provided only by an authenticated v2 route map.
        # Do not send these identities through StudyStore or infer file paths.
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True,
                             strict_parsing=True, errors='strict', max_num_fields=2)
            if set(query) != {'book', 'card'} or any(
                    len(values) != 1 or not values[0] or any(
                        ord(char) < 32 or ord(char) == 127 for char in values[0])
                    for values in query.values()):
                raise ValueError('invalid delivery identity')
        except (ValueError, UnicodeError):
            self._json(400, {'error': '卡片交付参数不完整或无效'}); return
        delivery = getattr(self.static_mounts, 'delivery', None)
        if not callable(delivery):
            self._json(409, {'error': '当前入口尚未启用统一卡片显示'}); return
        descriptor = delivery(query['book'][0], query['card'][0])
        if descriptor is None:
            self._json(404, {'error': '未找到已核验的卡片交付映射'}); return
        self._json(200, descriptor)

    def do_HEAD(self):
        if not self._allowed_host():
            self.send_error(403)
            return
        if urlsplit(self.path).path == '/api/study/audio-balanced':
            self._audio(head=True)
            return
        if urlsplit(self.path).path.startswith('/api/study/'):
            self.send_error(405)
            return
        super().do_HEAD()

    def _audio(self, head=False):
        if self.headers.get('Sec-Fetch-Site') == 'cross-site' or not self._same_origin():
            self._json(403, {'error': '请从本机词卡播放录音'}); return
        query = parse_qs(urlsplit(self.path).query)
        if not self.audio_balancer or set(query) != {'card', 'source', 'reference'} or any(len(v) != 1 for v in query.values()):
            self._json(400, {'error': '录音参数不完整'}); return
        try:
            result = self.audio_balancer.get(**{k: v[0] for k, v in query.items()})
        except Exception as exc:
            self._json(getattr(exc, 'status', 500), {'error': getattr(exc, 'message', '暂时无法读取录音')}); return
        size = result.path.stat().st_size
        start, end = 0, size - 1
        requested = self.headers.get('Range')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            if not match or not any(match.groups()): self.send_error(416); return
            if match[1]:
                start = int(match[1]); end = min(int(match[2]), end) if match[2] else end
            else:
                start = max(0, size - int(match[2]))
            if start > end or start >= size:
                self.send_response(416); self.send_header('Content-Range', f'bytes */{size}'); self.send_header('Content-Length', '0'); self.end_headers(); return
        self.send_response(206 if requested else 200)
        self.send_header('Content-Type', 'audio/wav' if result.path.suffix == '.wav' else self.guess_type(str(result.path)))
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Cache-Control', 'private, max-age=86400')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Study-Audio-Balanced', '1' if result.matched else '0')
        if requested: self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if not head:
            with result.path.open('rb') as source:
                source.seek(start); self.wfile.write(source.read(end - start + 1))

    def do_POST(self):
        if not self._allowed_host() or not self._same_origin() or self.headers.get('X-Study-Request') != '1':
            self._json(403, {'error': '请从本机学习页面提交操作'})
            return
        if not urlsplit(self.path).path.startswith('/api/study/'):
            self._json(404, {'error': '不存在此操作'})
            return
        if self.headers.get_content_type() != 'application/json':
            self._json(415, {'error': '操作数据必须是 JSON'})
            return
        try:
            length = int(self.headers.get('Content-Length', '-1'))
            if length < 0 or length > MAX_BODY_BYTES:
                self._json(413, {'error': '备份大小超出限制或缺少长度'})
                return
            body = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(body, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            self._json(400, {'error': '无法读取操作数据'})
            return
        self._route('POST', body)

    def do_OPTIONS(self):
        self._json(405, {'error': '不支持跨站调用'})

    def send_head(self):
        try:
            if self.static_mounts is None:
                request_path(self.path)  # Keep the legacy global guard without loading user configuration.
                mounted = None
            else:
                mounted = self.static_mounts.resolve(self.path)
        except (OSError, ValueError, RuntimeError, MountDenied):
            self.send_error(403)
            return None
        if mounted is not None:
            return self.static_mounts.send_head(self, mounted)
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(self.document_root):
            self.send_error(403)
            return None
        if path.parent.name == 'cards' and path.suffix == '.html' and path.is_file():
            data = path.read_bytes()
            # Compact exports replace CSS classes (for example with _r26).
            # Audio provenance attributes survive both export formats.
            if b'data-dictionary-accent=' in data or b'dictionary-word-audio' in data:
                script = b'<script src="/web-study/audio-loudness.js?v=20261008template1"></script>'
                data = data.replace(b'</body>', script + b'</body>')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                return io.BytesIO(data)
        return super().send_head()

    def end_headers(self):
        if urlsplit(self.path).path in {'/', '/index.html', '/preview-library.html',
                                      '/redbook-20261004/preview-library.html',
                                      '/redbook-2027-20261006/preview-library.html'} or self.path.startswith('/web-study/'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


# preview.request-queue.v1
class PreviewThreadingHTTPServer(ThreadingHTTPServer):
    # Both original loopback listeners must accept a browser resource burst.
    request_queue_size = 128


class IPv6Server(PreviewThreadingHTTPServer):
    address_family = socket.AF_INET6


def create_server(store: StudyStore, directory, *, host='127.0.0.1', port=0,
                  audio_balancer=None, static_mounts: StaticMounts | None = None):
    """Construct one explicit loopback listener without starting a thread.

    The caller owns server_close()/shutdown(), catalog loading and the store's
    storage selection. No production location or active service is inferred.
    """
    if host not in ('127.0.0.1', '::1'):
        raise ValueError('Study HTTP binds only 127.0.0.1 or ::1')
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError('Invalid study HTTP port')
    if static_mounts is not None and not isinstance(static_mounts, StaticMounts):
        raise TypeError('static_mounts must be an approved StaticMounts instance')
    database = getattr(store, 'db_path', None)
    if database is not None:
        database = Path(database).resolve()
        if database.is_relative_to(Path(directory).resolve()) or (
                static_mounts is not None and any(database == paths['catalog'] or any(
                    database.is_relative_to(paths[key]) for key in ('export', 'cards', 'media'))
                    for paths in static_mounts.mounts.values())):
            raise ValueError('Progress database must remain outside HTTP document and approved export roots')
    handler = partial(StudyHandler, store=store, directory=directory,
                      audio_balancer=audio_balancer, static_mounts=static_mounts)
    return (IPv6Server if host == '::1' else PreviewThreadingHTTPServer)((host, port), handler)
