from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import ipaddress
import threading
import unittest
from unittest.mock import patch

from scripts.serve_preview_lan import LATEST, LanPreviewHandler, rewrite_text, valid_path


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


if __name__ == '__main__':
    unittest.main()
