from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from http.server import BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
import base64
import errno
import gzip
import hashlib
import ipaddress
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.serve_preview_lan import (LATEST, LAN_HASH_RUNTIME, LAN_HASH_SHA, LAN_HASH_URL,
    LanPreviewHandler, LanPreviewServer, accepts_gzip, bootstrap_hash_runtime,
    rewrite_text, valid_path)


class LanPreviewTests(unittest.TestCase):
    def test_complete_existing_paths_and_queries_are_preserved(self):
        self.assertTrue(valid_path('/exam-usage-policy-20261012/a/cards/b.html?card=x'))
        self.assertTrue(valid_path('/exam-library/practice/full-paper.htm?paper=kaoyan%3A2024-01'))
        self.assertTrue(valid_path('/audio-unified-20261007/中文词书.apkg'))
        self.assertTrue(valid_path('/api/study/audio-balanced?card=x&source=y&reference=z'))

    def test_rejects_traversal_private_files_and_absolute_proxy_targets(self):
        for path in ('/../data/x', '/%252e%252e/data/x', '/%5cdata', '/.env',
                     '/data/a.sqlite3', '/server.py', 'http://example.com/a', '//example.com/a'):
            with self.subTest(path=path):
                self.assertFalse(valid_path(path))

    def test_reader_origins_change_but_source_text_and_hashes_do_not(self):
        original = b'{"origins":["http://localhost:8765"],"englishHash":"hash"} training'
        expected = b'{"origins":["http://192.168.3.5:8765"],"englishHash":"hash"} training'
        self.assertEqual(rewrite_text(original, '192.168.3.5', 8771, '/card.html'), expected)

    def test_lan_shelf_browses_latest_without_rewriting_old_card_urls(self):
        old = b'<a href="/redbook-2027-20261006/preview-library.html">browse</a>'
        self.assertIn(f'{LATEST}/redbook2027/preview-library.html'.encode(),
                      rewrite_text(old, '192.168.3.5', 8771, '/'))
        self.assertEqual(rewrite_text(old, '192.168.3.5', 8771, '/other.html'), old)

    def test_hash_bootstrap_precedes_reader_and_has_integrity_pin(self):
        original = b'<HTML><HEAD><script src="translations.js"></script></HEAD></HTML>'
        changed = bootstrap_hash_runtime(original, '/practice/full-paper.htm')
        integrity = base64.b64encode(bytes.fromhex(LAN_HASH_SHA))
        self.assertIn(b'integrity="sha256-' + integrity + b'"', changed)
        self.assertLess(changed.index(LAN_HASH_URL.encode()), changed.index(b'translations.js'))
        self.assertEqual(bootstrap_hash_runtime(changed, '/practice/full-paper.htm'), changed)

    def test_hash_bootstrap_preserves_signed_cards_and_history_bytes(self):
        original = b'<head><script src="http://localhost:8765/old.js"></script></head>exact evidence'
        for path in ('/a/history/abc.html', '/a/cards/abc.html', '/book/sources/abc.html',
                     '/a/evidence/raw.html', '/a/%73ources/raw.html',
                     '/a/%2568istory/raw.html', '/a/' + 'a' * 64 + '.html'):
            self.assertEqual(bootstrap_hash_runtime(original, path), original)
            self.assertEqual(rewrite_text(original, '192.168.3.5', 8771, path), original)
        self.assertEqual(bootstrap_hash_runtime(b'not a page', '/index.html'), b'not a page')

    def test_pinned_media_protocol_preserves_localhost_bytes(self):
        original = b'<head></head> http://localhost:8765 http://127.0.0.1:8771 http://[::1]:8765'
        for name in ('_ac_' + 'a' * 24 + '.js', '_as_' + 'b' * 24 + '.js',
                     '_af_' + 'c' * 24 + '.js', '_study_' + 'd' * 64 + '.js'):
            with self.subTest(name=name):
                path = '/book/media/' + name
                self.assertEqual(rewrite_text(original, '192.168.3.5', 8771, path), original)
                self.assertEqual(bootstrap_hash_runtime(original, path), original)
        encoded = '/book/media/%255faf_' + 'c' * 24 + '.js'
        self.assertTrue(valid_path(encoded))
        self.assertEqual(rewrite_text(original, '192.168.3.5', 8771, encoded), original)

    def test_media_protection_does_not_expand_beyond_exact_file_names(self):
        original = b'http://localhost:8765/source'
        expected = b'http://192.168.3.5:8765/source'
        for name in ('ordinary.js', '_af_' + 'a' * 23 + '.js',
                     '_af_' + 'a' * 25 + '.js', '_af_' + 'a' * 24 + '.js.extra',
                     'prefix_af_' + 'a' * 24 + '.js', '_AF_' + 'a' * 24 + '.js',
                     '_study_' + 'a' * 63 + '.js', '_study_' + 'A' * 64 + '.js',
                     '_study_library_' + 'a' * 64 + '.js'):
            with self.subTest(name=name):
                self.assertEqual(rewrite_text(original, '192.168.3.5', 8771,
                                              '/book/media/' + name), expected)


class LanHttpGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), LanPreviewHandler)
        cls.server.lan_ip = '127.0.0.1'
        cls.server.lan_network = ipaddress.ip_network('127.0.0.0/8')
        cls.server.backend_port = 8771
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_hash_runtime_serves_the_canonical_template_and_matching_sri(self):
        canonical_path = Path(__file__).resolve().parents[1] / 'anki_pipeline/templates/lan-sha256.js'
        canonical = canonical_path.read_bytes()
        checksum = hashlib.sha256(canonical).hexdigest()
        with patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
            for method in ('GET', 'HEAD'):
                with self.subTest(method=method):
                    connection = HTTPConnection('127.0.0.1', self.server.server_port)
                    try:
                        connection.request(method, LAN_HASH_URL)
                        response = connection.getresponse()
                        payload = response.read()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.getheader('Content-Length'), str(len(canonical)))
                        self.assertEqual(response.getheader('Content-Type'), 'application/javascript; charset=utf-8')
                        self.assertEqual(payload, canonical if method == 'GET' else b'')
                    finally:
                        connection.close()
            upstream.assert_not_called()
        self.assertEqual(LAN_HASH_RUNTIME, canonical_path)
        self.assertEqual(LAN_HASH_SHA, checksum)
        shell = bootstrap_hash_runtime(b'<html><head></head></html>', '/index.html')
        sri = base64.b64encode(hashlib.sha256(canonical).digest())
        self.assertIn(b'src="' + LAN_HASH_URL.encode() + b'" integrity="sha256-' + sri + b'"', shell)

    def test_changed_canonical_hash_runtime_is_rejected_without_serving_its_bytes(self):
        canonical = (Path(__file__).resolve().parents[1] / 'anki_pipeline/templates/lan-sha256.js').read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            changed = Path(folder) / 'changed-runtime.js'
            changed.write_bytes(canonical + b'\n/* unexpected change */')
            with patch('scripts.serve_preview_lan.LAN_HASH_RUNTIME', changed), \
                    patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
                for method in ('GET', 'HEAD'):
                    with self.subTest(method=method):
                        connection = HTTPConnection('127.0.0.1', self.server.server_port)
                        try:
                            connection.request(method, LAN_HASH_URL)
                            response = connection.getresponse()
                            self.assertEqual(response.status, 503)
                            self.assertNotIn(b'unexpected change', response.read())
                        finally:
                            connection.close()
                upstream.assert_not_called()

    def test_rejects_bad_host_without_contacting_study_backend(self):
        with patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
            connection = HTTPConnection('127.0.0.1', self.server.server_port)
            connection.request('GET', '/', headers={'Host': 'evil.example:8771'})
            response = connection.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
            connection.close()
            upstream.assert_not_called()

    def test_cross_site_or_missing_custom_header_never_reaches_backend(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        cases = ({'Origin': 'http://evil.example', 'X-Study-Request': '1'},
                 {'Origin': origin}, {'X-Study-Request': '1'})
        for headers in cases:
            with self.subTest(headers=headers), patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
                connection = HTTPConnection('127.0.0.1', self.server.server_port)
                connection.request('POST', '/api/study/import', body=b'{}',
                                   headers={'Content-Type': 'application/json', **headers})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.close()
                upstream.assert_not_called()

    def test_pinned_media_name_does_not_bypass_encoded_path_guard(self):
        name = '%255faf_' + 'a' * 24 + '.js'
        for path in ('/book/%252e%252e/media/' + name,
                     '/book/%252e%252e%252fmedia/' + name,
                     '/book/%255cmedia/' + name):
            with self.subTest(path=path), patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
                connection = HTTPConnection('127.0.0.1', self.server.server_port)
                connection.request('GET', path)
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.close()
                upstream.assert_not_called()


class LanTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Source(BaseHTTPRequestHandler):
            payload = b'<html><head></head><body>' + b'original example ' * 1024 + b'</body></html>'

            def do_GET(self):
                payload = self.payload
                if self.path == '/range.html':
                    payload = payload[:12]
                    self.send_response(206)
                    self.send_header('Content-Range', 'bytes 0-11/16422')
                elif self.headers.get('Range') == 'bytes=0-31':
                    payload = payload[:32]
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes 0-31/{len(self.payload)}')
                else:
                    self.send_response(200)
                mime = ('application/json' if self.path.startswith('/api/') or self.path.endswith('.json')
                        else 'text/javascript' if self.path.endswith('.js')
                        else 'image/png' if self.path.endswith('.png')
                        else 'application/gzip' if self.path.endswith('.gz') else 'text/html')
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        cls.source_type = Source
        cls.backend = LanPreviewServer(('127.0.0.1', 0), Source)
        cls.server = LanPreviewServer(('127.0.0.1', 0), LanPreviewHandler)
        cls.server.lan_ip = '127.0.0.1'
        cls.server.lan_network = ipaddress.ip_network('127.0.0.0/8')
        cls.server.backend_port = cls.backend.server_port
        cls.threads = []
        for server in (cls.backend, cls.server):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.backend):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join()

    def fetch(self, path='/cards/source.html', method='GET', headers=None):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_gzip_is_lossless_for_signed_source_and_head_has_same_length(self):
        status, headers, payload = self.fetch(headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Encoding'], 'gzip')
        self.assertEqual(gzip.decompress(payload), self.source_type.payload)
        self.assertLess(len(payload), len(self.source_type.payload))
        status, head, payload = self.fetch(method='HEAD', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(status, 200)
        self.assertEqual(payload, b'')
        self.assertEqual(head['Content-Length'], headers['Content-Length'])

    def test_etag_revalidation_and_content_revision_never_reuses_old_content(self):
        _, first, _ = self.fetch()
        status, headers, payload = self.fetch(headers={'If-None-Match': first['ETag']})
        self.assertEqual((status, payload), (304, b''))
        self.assertEqual(headers['Cache-Control'], 'no-cache')
        original = self.source_type.payload
        try:
            self.source_type.payload = original + b'revision'
            status, changed, payload = self.fetch(headers={'If-None-Match': first['ETag']})
            self.assertEqual(status, 200)
            self.assertNotEqual(changed['ETag'], first['ETag'])
            self.assertEqual(payload, original + b'revision')
        finally:
            self.source_type.payload = original

    def test_ranges_and_progress_api_are_not_compressed_or_cached(self):
        status, headers, payload = self.fetch('/range.html', headers={'Range': 'bytes=0-11', 'Accept-Encoding': 'gzip'})
        self.assertEqual(status, 206)
        self.assertEqual(payload, self.source_type.payload[:12])
        self.assertNotIn('Content-Encoding', headers)
        self.assertNotIn('ETag', headers)
        status, headers, payload = self.fetch('/api/study/overview', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(status, 200)
        self.assertEqual(payload, self.source_type.payload)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Content-Encoding', headers)
        self.assertNotIn('ETag', headers)

    def test_browser_resource_burst_is_served_concurrently(self):
        self.assertGreaterEqual(self.server.request_queue_size, 64)
        with ThreadPoolExecutor(max_workers=16) as executor:
            responses = list(executor.map(lambda _: self.fetch(), range(32)))
        self.assertTrue(all(status == 200 and payload == self.source_type.payload
                            for status, _, payload in responses))

    def test_encoding_negotiation_honors_explicit_gzip_refusal(self):
        for header in ('gzip;q=0', 'gzip;q=0, *;q=1', 'br', 'gzip;q=invalid'):
            self.assertFalse(accepts_gzip(header))
        self.assertTrue(accepts_gzip('br, gzip;q=0.8'))
        _, headers, payload = self.fetch(headers={'Accept-Encoding': 'gzip;q=0'})
        self.assertNotIn('Content-Encoding', headers)
        self.assertEqual(payload, self.source_type.payload)

    def test_json_bytes_are_not_rewritten_during_compression(self):
        original = self.source_type.payload
        try:
            self.source_type.payload = b'{"original":"http://localhost:8765/source"}' * 100
            status, headers, payload = self.fetch('/projection.json', headers={'Accept-Encoding': 'gzip'})
            self.assertEqual(status, 200)
            self.assertEqual(gzip.decompress(payload), self.source_type.payload)
        finally:
            self.source_type.payload = original

    def test_pinned_javascript_keeps_byte_identity_with_gzip_etag_and_range(self):
        original = self.source_type.payload
        try:
            self.source_type.payload = (b'http://localhost:8765/raw http://127.0.0.1:8771/raw '
                                        b'http://[::1]:8765/raw;\n') * 100
            for name in ('_ac_' + 'a' * 24 + '.js', '_as_' + 'b' * 24 + '.js',
                         '_af_' + 'c' * 24 + '.js', '_study_' + 'd' * 64 + '.js'):
                with self.subTest(name=name):
                    path = '/book/media/' + name
                    status, headers, payload = self.fetch(path, headers={'Accept-Encoding': 'gzip'})
                    self.assertEqual(status, 200)
                    self.assertEqual(gzip.decompress(payload), self.source_type.payload)
                    status, _, payload = self.fetch(path, headers={'If-None-Match': headers['ETag'],
                                                                 'Accept-Encoding': 'gzip'})
                    self.assertEqual((status, payload), (304, b''))
                    status, partial, payload = self.fetch(path, headers={'Range': 'bytes=0-31',
                                                                       'Accept-Encoding': 'gzip'})
                    self.assertEqual(status, 206)
                    self.assertEqual(payload, self.source_type.payload[:32])
                    self.assertEqual(partial['Content-Range'], f'bytes 0-31/{len(self.source_type.payload)}')
                    self.assertNotIn('Content-Encoding', partial)
                    self.assertNotIn('ETag', partial)
            status, _, payload = self.fetch('/book/media/ordinary.js')
            self.assertEqual(status, 200)
            expected = self.source_type.payload.replace(b'http://localhost:8765', b'http://127.0.0.1:8765')
            expected = expected.replace(b'http://[::1]:8765', b'http://127.0.0.1:8765')
            self.assertEqual(payload, expected)
        finally:
            self.source_type.payload = original

    def test_backend_failure_returns_explicit_502_instead_of_empty_reply(self):
        with patch('scripts.serve_preview_lan.HTTPConnection') as connection:
            connection.return_value.request.side_effect = ConnectionRefusedError()
            status, _, payload = self.fetch()
        self.assertEqual(status, 502)
        self.assertIn(b'Loopback preview service unavailable', payload)

    def test_get_and_head_retry_a_failed_connect_with_a_new_bounded_connection(self):
        for method in ('GET', 'HEAD'):
            attempts = []

            class Connection(HTTPConnection):
                def connect(inner):
                    if len(attempts) == 1:
                        raise ConnectionResetError(errno.ECONNRESET, 'queue rejected connection')
                    super().connect()

            def create(*args, **kwargs):
                connection = Connection(*args, **kwargs)
                attempts.append(connection)
                return connection

            with self.subTest(method=method), patch('scripts.serve_preview_lan.HTTPConnection', side_effect=create):
                status, _, payload = self.fetch(method=method)
                self.assertEqual(status, 200)
                self.assertEqual(payload, self.source_type.payload if method == 'GET' else b'')
                self.assertEqual(len(attempts), 2)
                self.assertIsNot(attempts[0], attempts[1])
                self.assertLessEqual(attempts[0].timeout, 5)

    def test_post_and_non_connection_failures_are_never_replayed(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        for method, phase, error, expected in (
            ('POST', 'connect', ConnectionResetError(errno.ECONNRESET, 'reset'), 1),
            ('GET', 'connect', PermissionError(errno.EACCES, 'denied'), 1),
            ('GET', 'response', ConnectionResetError(errno.ECONNRESET, 'response reset'), 1),
        ):
            attempts = []

            class Connection(HTTPConnection):
                def connect(inner):
                    if phase == 'connect':
                        raise error
                    super().connect()

                def getresponse(inner):
                    if phase == 'response':
                        raise error
                    return super().getresponse()

            def create(*args, **kwargs):
                connection = Connection(*args, **kwargs)
                attempts.append(connection)
                return connection

            with self.subTest(method=method, phase=phase, error=type(error).__name__), \
                    patch('scripts.serve_preview_lan.HTTPConnection', side_effect=create), \
                    patch.object(self.server, 'backend_port', 8771 if method == 'POST' else self.backend.server_port):
                status, _, _ = self.fetch('/api/study/import' if method == 'POST' else '/', method=method,
                    headers={'Origin': origin, 'X-Study-Request': '1', 'Content-Type': 'application/json'})
                self.assertEqual(status, 502)
                self.assertEqual(len(attempts), expected)

    def test_transient_connect_retry_is_limited_to_two_attempts(self):
        for error in (OSError(errno.EINVAL, 'macOS connect reset'), TimeoutError('connect timeout')):
            attempts = []

            class Connection(HTTPConnection):
                def connect(inner):
                    raise error

            def create(*args, **kwargs):
                connection = Connection(*args, **kwargs)
                attempts.append(connection)
                return connection

            with self.subTest(error=type(error).__name__), \
                    patch('scripts.serve_preview_lan.HTTPConnection', side_effect=create):
                status, _, _ = self.fetch()
                self.assertEqual(status, 502)
                self.assertEqual(len(attempts), 2)
                self.assertTrue(all(connection.timeout <= 5 for connection in attempts))

    def test_content_addressed_media_cache_requires_verified_original_bytes(self):
        original = self.source_type.payload
        try:
            self.source_type.payload = b'\x89PNG\r\n\x1a\n' + b'original image bytes' * 8
            checksum = hashlib.sha256(self.source_type.payload).hexdigest()
            path = '/book/media/_rb_' + checksum[:24] + '.png'
            status, headers, payload = self.fetch(path)
            self.assertEqual((status, payload), (200, self.source_type.payload))
            self.assertEqual(headers['Cache-Control'], 'private, max-age=31536000, immutable')
            self.assertEqual(headers['ETag'], f'"sha256-{checksum}"')
            status, revalidated, payload = self.fetch(path, headers={'If-None-Match': headers['ETag']})
            self.assertEqual((status, payload), (304, b''))
            self.assertEqual(revalidated['Cache-Control'], headers['Cache-Control'])
            status, head, payload = self.fetch(path, method='HEAD')
            self.assertEqual((status, payload), (200, b''))
            self.assertEqual(head['Content-Length'], headers['Content-Length'])
            self.assertEqual(head['Cache-Control'], headers['Cache-Control'])
            for invalid in ('/book/media/ordinary.png', '/book/media/_rb_' + '0' * 24 + '.png',
                            '/book/media/_rb_' + checksum[:23] + '.png',
                            '/api/study/media/_rb_' + checksum[:24] + '.png'):
                with self.subTest(invalid=invalid):
                    _, rejected, _ = self.fetch(invalid)
                    self.assertEqual(rejected['Cache-Control'], 'no-store')
            _, ranged, payload = self.fetch(path, headers={'Range': 'bytes=0-31'})
            self.assertEqual(payload, self.source_type.payload[:32])
            self.assertEqual(ranged['Cache-Control'], 'no-store')
            self.assertNotIn('ETag', ranged)
        finally:
            self.source_type.payload = original

    def test_verified_gzip_artifact_and_pinned_javascript_can_cache_without_changing_bytes(self):
        original = self.source_type.payload
        try:
            self.source_type.payload = gzip.compress(b'{"full":"original source"}' * 100, mtime=0)
            checksum = hashlib.sha256(self.source_type.payload).hexdigest()
            path = '/book/evidence/_study_prepared_card_' + checksum + '.json.gz'
            status, headers, payload = self.fetch(path, headers={'Accept-Encoding': 'gzip'})
            self.assertEqual((status, payload), (200, self.source_type.payload))
            self.assertNotIn('Content-Encoding', headers)
            self.assertEqual(headers['Cache-Control'], 'private, max-age=31536000, immutable')
            self.source_type.payload = b'http://localhost:8765/source;\n' * 100
            checksum = hashlib.sha256(self.source_type.payload).hexdigest()
            path = '/book/media/_study_' + checksum + '.js'
            status, headers, payload = self.fetch(path, headers={'Accept-Encoding': 'gzip'})
            self.assertEqual(gzip.decompress(payload), self.source_type.payload)
            self.assertEqual(headers['Cache-Control'], 'private, max-age=31536000, immutable')
            # An unpinned script whose bytes are rewritten is not immutable,
            # even if its original filename contains a valid content hash.
            _, changed, payload = self.fetch('/book/media/ordinary_' + checksum + '.js')
            self.assertEqual(changed['Cache-Control'], 'no-cache')
            self.assertNotEqual(payload, self.source_type.payload)
        finally:
            self.source_type.payload = original

    def test_hash_runtime_get_head_and_fingerprint_guard(self):
        content = b'/* tested runtime */'
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder) / 'runtime.js'
            script.write_bytes(content)
            with patch('scripts.serve_preview_lan.LAN_HASH_RUNTIME', script), \
                    patch('scripts.serve_preview_lan.LAN_HASH_SHA', hashlib.sha256(content).hexdigest()), \
                    patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
                for method in ('GET', 'HEAD'):
                    connection = HTTPConnection('127.0.0.1', self.server.server_port)
                    connection.request(method, LAN_HASH_URL)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.getheader('Content-Length'), str(len(content)))
                    self.assertEqual(response.read(), content if method == 'GET' else b'')
                    connection.close()
                script.write_bytes(b'changed')
                connection = HTTPConnection('127.0.0.1', self.server.server_port)
                connection.request('GET', LAN_HASH_URL)
                response = connection.getresponse()
                self.assertEqual(response.status, 503)
                response.read()
                connection.close()
                upstream.assert_not_called()


if __name__ == '__main__':
    unittest.main()
