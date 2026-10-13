from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import base64
import hashlib
import ipaddress
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from scripts.serve_preview_lan import (LATEST, LAN_HASH_SHA, LAN_HASH_URL,
    LanPreviewHandler, bootstrap_hash_runtime, rewrite_text, valid_path)


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
