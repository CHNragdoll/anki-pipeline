"""Real disposable loopback requests exercise the extracted legacy boundary."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import importlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlencode

from anki_pipeline import study_http as web
from anki_pipeline import study_progress
from anki_pipeline.preview_static_mounts import StaticMounts
from anki_pipeline.study_progress import StudyStore
from anki_pipeline.study_progress_snapshot import canonical_rows


def mount_fixture(root):
    export = root / 'external' / 'master-fixture-web-v1'
    (export / 'cards').mkdir(parents=True)
    (export / 'media').mkdir()
    (export / 'catalog.json').write_text('{"fixture":true}')
    (export / 'index.html').write_bytes(b'export index')
    prefix = '/study-catalog-20261017/master-fixture-web-v1/'
    row = {'url_mount': prefix, 'export': str(export), 'cards': str(export / 'cards'),
           'media': str(export / 'media'), 'catalog': str(export / 'catalog.json')}
    return StaticMounts([row]), prefix, export


@contextmanager
def serving(store, directory, **options):
    server = web.create_server(store, directory, **options)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        if thread.is_alive():
            raise AssertionError('Temporary HTTP thread did not stop')


def request(server, method, path, *, body=None, headers=None, host=None, add_length=True):
    connection = http.client.HTTPConnection(server.server_address[0], server.server_port, timeout=5)
    try:
        connection.putrequest(method, path, skip_host=True)
        selected = dict(headers or {})
        if host is not False:
            selected['Host'] = host if host is not None else (
                f'[::1]:{server.server_port}' if server.address_family == socket.AF_INET6
                else f'127.0.0.1:{server.server_port}')
        if body is not None and add_length and 'Content-Length' not in selected:
            selected['Content-Length'] = str(len(body))
        for key, value in selected.items():
            connection.putheader(key, value)
        connection.endheaders(body)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def state(path):
    return hashlib.sha256(b''.join(canonical_rows(path))).hexdigest()


class StudyHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='study-http-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.public = self.root / 'public'; self.public.mkdir()
        (self.public / 'index.html').write_bytes(b'bookshelf')
        (self.public / 'ordinary.bin').write_bytes(b'0123456789')
        (self.public / 'web-study').mkdir()
        (self.public / 'web-study' / 'asset.js').write_bytes(b'window.fixture=true;')
        fixture = json.loads((Path(__file__).parent / 'fixtures/study-progress-legacy-v1.json').read_text())
        self.store = StudyStore(self.root / 'private/progress.sqlite3', fixture['catalog'],
                                now=lambda: datetime(2026, 10, 17, tzinfo=timezone.utc))
        self.quiet = patch.object(web.StudyHandler, 'log_message', return_value=None)
        self.quiet.start(); self.addCleanup(self.quiet.stop)

    def test_real_store_get_and_post_preserve_json_headers_and_state(self):
        with serving(self.store, self.public) as server:
            status, headers, data = request(server, 'GET', '/api/study/overview')
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(int(headers['Content-Length']), len(data))
            self.assertEqual(json.loads(data)['algorithm'], 'FSRS')
            status, _, data = request(server, 'GET', '/api/study/session?book=missing&book=liu')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)['book']['id'], 'liu')
            payload = {'book': 'liu', 'newPerDay': 7, 'reviewPerDay': 80, 'desiredRetention': .91}
            before = state(self.store.db_path)
            status, _, data = request(server, 'POST', '/api/study/settings', body=json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json; charset=utf-8', 'X-Study-Request': '1'})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)['settings']['newPerDay'], 7)
            self.assertNotEqual(state(self.store.db_path), before)

    def test_frozen_legacy_http_sequence_uses_the_actual_extracted_handler(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/study-progress-legacy-v1.json').read_text())
        clock = [datetime.fromisoformat(fixture['clock_start'])]
        store = StudyStore(self.root / 'private/replay.sqlite3', fixture['catalog'], now=lambda: clock[0])
        self.assertEqual(state(store.db_path), fixture['initial_state_sha256'])
        with patch.object(study_progress.uuid, 'uuid4', return_value=uuid.UUID(fixture['uuid4'])), \
                serving(store, self.public) as server:
            for step in fixture['requests']:
                with self.subTest(request=step['name']):
                    clock[0] = datetime.fromisoformat(step['at'])
                    body = json.dumps(step['body'], ensure_ascii=False, allow_nan=False).encode() if step['body'] is not None else None
                    status, headers, data = request(server, step['method'], step['path'], body=body,
                        headers={'Content-Type': 'application/json', 'X-Study-Request': '1'})
                    self.assertEqual(status, step['status'])
                    self.assertEqual(data.decode(), step['response_text'])
                    self.assertEqual({key: headers[key] for key in step['headers']}, step['headers'])
                    self.assertEqual(state(store.db_path), step['state_sha256'])

    def test_host_origin_and_custom_header_rejections_never_change_progress(self):
        before = state(self.store.db_path)
        with serving(self.store, self.public) as server:
            for host in (False, 'example.com', '127.0.0.1', f'127.0.0.1:{server.server_port + 1}',
                         f'user@127.0.0.1:{server.server_port}', f'127.0.0.1:{server.server_port}/path',
                         '127.0.0.1:invalid'):
                with self.subTest(host=host):
                    self.assertEqual(request(server, 'GET', '/api/study/overview', host=host)[0], 403)
            for headers in ({'Content-Type': 'application/json'},
                            {'Content-Type': 'application/json', 'X-Study-Request': '0'},
                            {'Content-Type': 'application/json', 'X-Study-Request': '1', 'Origin': 'https://example.com'}):
                self.assertEqual(request(server, 'POST', '/api/study/settings', body=b'{}', headers=headers)[0], 403)
        self.assertEqual(state(self.store.db_path), before)

    def test_request_body_limits_json_and_route_errors_keep_legacy_statuses(self):
        before = state(self.store.db_path)
        valid = {'Content-Type': 'application/json', 'X-Study-Request': '1'}
        with serving(self.store, self.public) as server:
            for body in (b'', b'[]', b'{', b'{"x":NaN}', b'{"x":Infinity}', b'\xff'):
                with self.subTest(body=body):
                    self.assertEqual(request(server, 'POST', '/api/study/settings', body=body, headers=valid)[0], 400)
            for value, expected in (('-1', 413), (str(web.MAX_BODY_BYTES + 1), 413), ('not-a-number', 400)):
                self.assertEqual(request(server, 'POST', '/api/study/settings',
                    headers={**valid, 'Content-Length': value})[0], expected)
            self.assertEqual(request(server, 'POST', '/api/study/settings', headers=valid)[0], 413)
            self.assertEqual(request(server, 'POST', '/api/study/settings', body=b'{}',
                                     headers={**valid, 'Content-Type': 'text/plain'})[0], 415)
            self.assertEqual(request(server, 'POST', '/ordinary.bin', body=b'{}', headers=valid)[0], 404)
            self.assertEqual(request(server, 'GET', '/api/study/unknown')[0], 404)
            self.assertEqual(request(server, 'GET', '/api/study/answer')[0], 405)
            self.assertEqual(request(server, 'HEAD', '/api/study/overview')[0], 405)
            self.assertEqual(request(server, 'OPTIONS', '/api/study/overview', host='untrusted.example')[0], 405)
        self.assertEqual(state(self.store.db_path), before)

    def test_api_internal_error_is_sanitized_and_not_serialized(self):
        with serving(self.store, self.public) as server, patch.object(self.store, 'dispatch', side_effect=RuntimeError('private marker')):
            status, _, data = request(server, 'GET', '/api/study/overview')
        self.assertEqual(status, 500)
        self.assertNotIn(b'private marker', data)
        self.assertEqual(json.loads(data), {'error': '操作失败，进度未保存，请重试。'})

    def test_unmounted_static_html_injection_cache_and_containment_are_unchanged(self):
        cards = self.public / 'cards'; cards.mkdir()
        data = b'<body><audio data-dictionary-accent="uk"></audio></body>'
        (cards / 'word.html').write_bytes(data)
        (self.public / 'private-link').symlink_to(self.store.db_path)
        with serving(self.store, self.public) as server:
            self.assertEqual(request(server, 'GET', '/')[1]['Cache-Control'], 'no-cache')
            self.assertEqual(request(server, 'GET', '/web-study/asset.js')[1]['Cache-Control'], 'no-cache')
            status, headers, result = request(server, 'GET', '/cards/word.html')
            self.assertEqual(status, 200)
            self.assertEqual(result, data.replace(b'</body>', b'<script src="/web-study/audio-loudness.js?v=20261008template1"></script></body>'))
            self.assertEqual(int(headers['Content-Length']), len(result))
            # Plain stdlib assets ignored Range in the existing handler.
            self.assertEqual(request(server, 'GET', '/ordinary.bin', headers={'Range': 'bytes=2-4'})[2], b'0123456789')
            for path in ('/private-link', '/../private/progress.sqlite3', '/%252e%252e/private/progress.sqlite3'):
                self.assertEqual(request(server, 'GET', path)[0], 403)
        self.assertEqual((cards / 'word.html').read_bytes(), data)

    def test_exact_mount_range_head_and_private_sibling_denial(self):
        mounts, prefix, export = mount_fixture(self.root)
        (export / 'media' / 'asset.bin').write_bytes(b'0123456789')
        original = b'<body data-dictionary-accent="uk">same bytes</body>'
        (export / 'cards' / 'word.html').write_bytes(original)
        outside = self.root / 'private.txt'; outside.write_bytes(b'private outside')
        (export / 'media' / 'leak.txt').symlink_to(outside)
        with serving(self.store, self.public, static_mounts=mounts) as server:
            status, headers, data = request(server, 'GET', prefix + 'media/asset.bin', headers={'Range': 'bytes=2-4'})
            self.assertEqual((status, data), (206, b'234'))
            self.assertEqual(headers['Content-Range'], 'bytes 2-4/10')
            self.assertEqual(headers['Accept-Ranges'], 'bytes')
            status, headers, data = request(server, 'HEAD', prefix + 'media/asset.bin', headers={'Range': 'bytes=-3'})
            self.assertEqual((status, data, headers['Content-Length']), (206, b'', '3'))
            self.assertEqual(request(server, 'GET', prefix + 'cards/word.html')[2], original)
            for tail in ('media/leak.txt', 'media/../catalog.json', 'media/private.sqlite3', 'media/.hidden', '%252e%252e/private.txt'):
                self.assertEqual(request(server, 'GET', prefix + tail)[0], 403)
            status, headers, data = request(server, 'GET', prefix + 'media/asset.bin', headers={'Range': 'bytes=99-'})
            self.assertEqual((status, data, headers['Content-Range']), (416, b'', 'bytes */10'))
            self.assertEqual(request(server, 'GET', prefix + 'media/asset.bin',
                                     headers={'Range': 'bytes=2-4', 'If-Range': 'arbitrary'})[0], 200)

    def test_factory_has_no_wildcard_listener_and_never_publishes_progress_file(self):
        for host in ('0.0.0.0', '192.168.3.5', '::', 'localhost'):
            with self.assertRaises(ValueError):
                web.create_server(self.store, self.public, host=host)
        with self.assertRaises(ValueError):
            web.create_server(self.store, self.public, port=True)
        unsafe = StudyStore(self.public / 'unsafe.sqlite3', self.store.books)
        with self.assertRaisesRegex(ValueError, 'Progress database'):
            web.create_server(unsafe, self.public)
        self.assertTrue(unsafe.db_path.is_file())  # Reject exposure, do not erase caller data.
        self.assertEqual(web.PreviewThreadingHTTPServer.request_queue_size, 128)

    def test_factory_rejects_progress_database_delegated_as_public_catalog(self):
        mounts, prefix, export = mount_fixture(self.root)
        database = self.root / 'private' / 'catalog.json'
        unsafe = StudyStore(database, self.store.books)
        (export / 'catalog.json').unlink()
        (export / 'catalog.json').symlink_to(database)
        row = {'url_mount': prefix, 'export': str(export), 'cards': str(export / 'cards'),
               'media': str(export / 'media'), 'catalog': str(database)}
        mounts = StaticMounts([row])
        stream, _ = mounts.resolve(prefix + 'catalog.json').open()
        with stream:
            self.assertTrue(stream.read(16).startswith(b'SQLite format 3'))
        with patch.object(web, 'PreviewThreadingHTTPServer') as listener:
            with self.assertRaisesRegex(ValueError, 'Progress database'):
                web.create_server(unsafe, self.public, static_mounts=mounts)
        listener.assert_not_called()
        self.assertTrue(database.is_file())

    def test_ipv6_loopback_uses_the_original_host_boundary(self):
        try:
            with serving(self.store, self.public, host='::1') as server:
                self.assertEqual(request(server, 'GET', '/api/study/overview')[0], 200)
                self.assertEqual(request(server, 'GET', '/api/study/overview', host='[::1]')[0], 403)
        except OSError as error:
            if not socket.has_ipv6:
                self.skipTest(str(error))
            raise

    def test_audio_range_head_and_rejections_keep_the_original_wire_contract(self):
        media = self.root / 'private' / 'fixture.wav'; media.write_bytes(b'RIFF' + bytes(range(40)))
        class Audio:
            def get(self, **values):
                self.values = values
                return type('Result', (), {'path': media, 'matched': False})()
        audio = Audio()
        query = urlencode({'card': '/card.html', 'source': '/us.wav', 'reference': '/uk.wav'})
        url = '/api/study/audio-balanced?' + query
        with serving(self.store, self.public, audio_balancer=audio) as server:
            status, headers, data = request(server, 'GET', url, headers={'Range': 'bytes=4-7'})
            self.assertEqual((status, data), (206, bytes(range(4))))
            self.assertEqual(headers['X-Study-Audio-Balanced'], '0')
            self.assertEqual(headers['Content-Type'], 'audio/wav')
            self.assertEqual(headers['Cache-Control'], 'private, max-age=86400')
            self.assertEqual(request(server, 'HEAD', url)[2], b'')
            self.assertEqual(request(server, 'GET', url, headers={'Range': 'bytes=999-'})[0], 416)
            self.assertEqual(request(server, 'GET', url, headers={'Range': 'bytes=-'})[0], 416)
            self.assertEqual(request(server, 'GET', url, headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
            self.assertEqual(request(server, 'GET', url, headers={'Origin': 'https://example.com'})[0], 403)
            self.assertEqual(request(server, 'GET', url + '&source=another')[0], 400)
            self.assertEqual(request(server, 'GET', '/api/study/audio-balanced?card=only')[0], 400)
        self.assertEqual(audio.values, {'card': '/card.html', 'source': '/us.wav', 'reference': '/uk.wav'})

    def test_import_does_not_read_a_catalog_config_or_user_path(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('implicit text read')), \
                patch.object(Path, 'resolve', side_effect=AssertionError('implicit path resolve')):
            importlib.reload(web)


if __name__ == '__main__':
    unittest.main()
