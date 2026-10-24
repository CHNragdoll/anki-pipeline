from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import tempfile
import threading
import unittest
from unittest.mock import patch

from anki_pipeline.preview_static_mounts import MountDenied, StaticMounts
from scripts import configure_preview_mounts as installer


SERVER = '''from pathlib import Path
import io
import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
REPO_ROOT = Path({root!r})
MAX_BODY_BYTES = 128 * 1024 * 1024
class StudyHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.document_root = REPO_ROOT / 'output'
        super().__init__(*args, directory=str(self.document_root), **kwargs)
    def send_head(self):
        path = Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(self.document_root):
            self.send_error(403)
            return None
        return super().send_head()
    def log_message(self, *args):
        pass
class IPv6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6
def main():
    servers = []
    servers.append(ThreadingHTTPServer(('127.0.0.1', port), handler))
'''


class StaticMountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.document = self.root / 'output'
        self.document.mkdir()
        self.export = self.root / 'private/master-test-web-v3'
        self.export.mkdir(parents=True)
        self.cards = self.root / 'private/master-test-web-v2/cards'
        self.media = self.root / 'private/master-test-web-v1/media'
        self.cards.mkdir(parents=True)
        self.media.mkdir(parents=True)
        self.catalog = self.media.parent / 'catalog.json'
        self.catalog.write_bytes(b'{"cards":[]}')
        (self.export / 'index.html').write_bytes(b'<h1>approved export</h1>')
        (self.export / 'host.css').write_bytes(b'body{color:navy}')
        (self.cards / 'note.html').write_bytes(b'<p>original card</p>')
        (self.media / 'audio.mp3').write_bytes(b'0123456789audio')
        (self.export / 'cards').symlink_to(self.cards, target_is_directory=True)
        (self.export / 'media').symlink_to(self.media, target_is_directory=True)
        (self.export / 'catalog.json').symlink_to(self.catalog)
        self.prefix = '/study-catalog-20261015/master-test-web-v3/'
        self.entries = [{'url_mount': self.prefix, 'export': str(self.export),
                         'cards': str(self.cards), 'media': str(self.media), 'catalog': str(self.catalog)}]
        self.mounts = StaticMounts(self.entries)
        self.server_file = self.document / 'web-study/server.py'
        self.server_file.parent.mkdir()
        self.original = SERVER.format(root=str(self.root)).encode()
        self.server_file.write_bytes(self.original)
        self.config = self.root / 'data/web-study/service/static-mounts.json'
        self.config.parent.mkdir(parents=True)
        runtime = self.root / 'anki_pipeline/preview_static_mounts.py'
        runtime.parent.mkdir()
        runtime.write_bytes(installer.RUNTIME.read_bytes())
        self.manifest = self.root / 'manifest.json'
        self.manifest.write_text(json.dumps(self.entries))
        self.receipt = self.config.parent / 'receipt.json'

    def install(self, **kwargs):
        with patch.object(installer, 'ROOT', self.root):
            return installer.configure(self.manifest, self.server_file, self.receipt,
                expected_server_sha256=installer.digest(self.original),
                service_plist=self.root / 'service.plist', **kwargs)

    def test_exact_export_and_delegates_open_original_bytes(self):
        for suffix, expected in (('', b'<h1>approved export</h1>'),
                                 ('host.css', b'body{color:navy}'),
                                 ('cards/note.html', b'<p>original card</p>'),
                                 ('media/audio.mp3', b'0123456789audio'),
                                 ('catalog.json', b'{"cards":[]}')):
            with self.subTest(suffix=suffix):
                stream, _ = self.mounts.resolve(self.prefix + suffix).open()
                with stream:
                    self.assertEqual(stream.read(), expected)

    def test_nested_external_symlinks_and_encoded_traversal_are_denied(self):
        secret = self.root / 'private/secret.txt'
        secret.write_bytes(b'never serve this')
        (self.media / 'escape.txt').symlink_to(secret)
        for suffix in ('media/escape.txt', '../secret.txt', '%252e%252e/secret.txt',
                       'cards/%2e%2e/%2e%2e/secret.txt', 'media/%5csecret.txt', '.env', 'progress.sqlite3'):
            with self.subTest(suffix=suffix), self.assertRaises(MountDenied):
                self.mounts.resolve(self.prefix + suffix)
        self.assertIsNone(self.mounts.resolve('/unapproved/private/secret.txt'))

    def test_retargeted_delegate_is_not_accepted(self):
        (self.export / 'media').unlink()
        (self.export / 'media').symlink_to(self.root / 'private', target_is_directory=True)
        with self.assertRaises(MountDenied):
            self.mounts.resolve(self.prefix + 'media/catalog.json')

    def test_open_rejects_symlink_substituted_after_resolution(self):
        resource = self.mounts.resolve(self.prefix + 'host.css')
        (self.export / 'host.css').unlink()
        (self.export / 'host.css').symlink_to(self.catalog)
        with self.assertRaises(OSError):
            resource.open()

    def test_open_rejects_approved_root_ancestor_replaced_after_resolution(self):
        resource = self.mounts.resolve(self.prefix + 'cards/note.html')
        outside = self.root / 'outside/cards'
        outside.mkdir(parents=True)
        (outside / 'note.html').write_bytes(b'unapproved outside bytes')
        approved_book = self.cards.parent
        approved_book.rename(approved_book.with_name('saved-approved-book'))
        approved_book.symlink_to(outside.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            resource.open()

    def test_manifest_rejects_broad_roots_wrong_aliases_and_duplicate_urls(self):
        for entries in ([{**self.entries[0], 'export': str(self.root / 'private')}],
                        [{**self.entries[0], 'media': str(self.cards)}], self.entries * 2):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                StaticMounts(entries)

    def test_installer_is_reversible_and_preserves_original_handler(self):
        record = self.install()
        actual = self.server_file.read_bytes().decode()
        recovered = actual.replace('import runpy\n', '', 1).replace(installer.LOADER, '', 1)
        recovered = recovered.replace(installer.HOOK, '', 1).replace(installer.QUEUE_CLASS, '', 1)
        recovered = recovered.replace('class IPv6Server(PreviewThreadingHTTPServer):',
                                      'class IPv6Server(ThreadingHTTPServer):')
        recovered = recovered.replace("servers.append(PreviewThreadingHTTPServer(('127.0.0.1', port), handler))",
                                      "servers.append(ThreadingHTTPServer(('127.0.0.1', port), handler))")
        self.assertEqual(recovered.encode(), self.original)
        self.assertEqual(installer.patch_server(actual.encode()), actual.encode())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        installer.restore_files(record)
        self.assertEqual(self.server_file.read_bytes(), self.original)
        self.assertFalse(self.config.exists())

    def test_existing_loopback_families_share_a_bounded_large_accept_queue(self):
        self.install()
        namespace = runpy.run_path(str(self.server_file), run_name='queue_test_preflight')
        ipv4 = namespace['PreviewThreadingHTTPServer']
        ipv6 = namespace['IPv6Server']
        self.assertEqual(ipv4.request_queue_size, 128)
        self.assertEqual(ipv6.request_queue_size, 128)
        self.assertTrue(issubclass(ipv6, ipv4))
        actual = self.server_file.read_bytes()
        self.assertIn(b"servers.append(PreviewThreadingHTTPServer(('127.0.0.1', port), handler))", actual)
        self.assertEqual(installer.patch_server(actual), actual)

    def test_later_queue_edits_are_rejected_and_unchanged_config_is_not_rewritten(self):
        self.install()
        queued = self.server_file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'queue patch was independently changed'):
            installer.patch_server(queued.replace(b'request_queue_size = 128', b'request_queue_size = 32'))
        original_queue = queued.decode().replace(installer.QUEUE_CLASS, '', 1)
        original_queue = original_queue.replace('class IPv6Server(PreviewThreadingHTTPServer):',
                                                 'class IPv6Server(ThreadingHTTPServer):')
        original_queue = original_queue.replace("servers.append(PreviewThreadingHTTPServer(('127.0.0.1', port), handler))",
                                                 "servers.append(ThreadingHTTPServer(('127.0.0.1', port), handler))")
        self.server_file.write_text(original_queue)
        before = self.config.stat()
        with patch.object(installer, 'ROOT', self.root):
            installer.configure(self.manifest, self.server_file, self.receipt.with_name('queue-receipt.json'),
                expected_server_sha256=installer.digest(original_queue.encode()),
                service_plist=self.root / 'service.plist')
        after = self.config.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.assertEqual(self.server_file.read_bytes(), queued)

    def test_install_refuses_changed_server_before_any_mutation(self):
        self.server_file.write_bytes(self.original + b'# user edit\n')
        with self.assertRaisesRegex(ValueError, 'server bytes changed'):
            self.install()
        self.assertFalse(self.config.exists())
        self.assertFalse(self.receipt.exists())

    def test_relative_install_paths_produce_standalone_absolute_recovery_paths(self):
        with patch.object(installer, 'ROOT', self.root):
            record = installer.configure(Path(os.path.relpath(self.manifest)), self.server_file,
                Path(os.path.relpath(self.receipt)),
                expected_server_sha256=installer.digest(self.original),
                service_plist=self.root / 'service.plist')
        self.assertTrue(Path(record['server_backup']).is_absolute())
        installer.restore_files(record)
        self.assertEqual(self.server_file.read_bytes(), self.original)

    def test_failed_preflight_restores_both_files_without_reloading(self):
        with patch.object(installer, 'validate_installed_server', side_effect=ValueError('bad runtime')), \
                patch.object(installer, 'reload_service') as reload:
            with self.assertRaisesRegex(ValueError, 'bad runtime'):
                self.install()
        self.assertEqual(self.server_file.read_bytes(), self.original)
        self.assertFalse(self.config.exists())
        reload.assert_not_called()

    def test_rollback_preserves_later_server_or_configuration_edits(self):
        record = self.install()
        self.config.write_bytes(b'later user configuration')
        with self.assertRaisesRegex(RuntimeError, 'subsequently edited'):
            installer.restore_files(record)
        self.assertEqual(self.config.read_bytes(), b'later user configuration')
        self.assertEqual(installer.digest(self.server_file.read_bytes()), record['server_after_sha256'])

    def test_rollback_rechecks_configuration_after_restoring_server(self):
        record = self.install()
        write = installer.atomic_write

        def concurrent_write(path, raw, mode):
            write(path, raw, mode)
            if path == self.server_file.resolve():
                self.config.write_bytes(b'user config written between restores')

        with patch.object(installer, 'atomic_write', side_effect=concurrent_write):
            with self.assertRaisesRegex(RuntimeError, 'subsequently edited'):
                installer.restore_files(record)
        self.assertEqual(self.config.read_bytes(), b'user config written between restores')
        self.assertEqual(self.server_file.read_bytes(), self.original)

    def test_install_rechecks_server_after_configuration_write(self):
        write = installer.atomic_write
        later = self.original + b'# independent user edit\n'

        def concurrent_write(path, raw, mode):
            write(path, raw, mode)
            if path == self.config:
                self.server_file.write_bytes(later)

        with patch.object(installer, 'atomic_write', side_effect=concurrent_write):
            with self.assertRaisesRegex(RuntimeError, 'server changed before installation'):
                self.install()
        self.assertEqual(self.server_file.read_bytes(), later)
        self.assertFalse(self.config.exists())

    def test_real_http_routes_ranges_and_outside_links(self):
        self.install()
        handler = runpy.run_path(str(self.server_file))['StudyHandler']
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        (self.document / 'outside').symlink_to(self.root / 'private', target_is_directory=True)
        (self.media / 'escape.txt').symlink_to(self.root / 'private/secret.txt')
        (self.root / 'private/secret.txt').write_bytes(b'no access')

        def request(path, method='GET', headers=None):
            connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request(method, path, headers=headers or {})
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()

        for suffix in ('index.html', 'host.css', 'cards/note.html', 'catalog.json', 'media/audio.mp3'):
            self.assertEqual(request(self.prefix + suffix)[0], 200)
        for path in ('/outside/secret.txt', self.prefix + 'media/escape.txt', self.prefix + '%252e%252e/secret.txt'):
            self.assertEqual(request(path)[0], 403)
        status, headers, body = request(self.prefix + 'media/audio.mp3', headers={'Range': 'bytes=2-5'})
        self.assertEqual((status, body, headers['Content-Range']), (206, b'2345', 'bytes 2-5/15'))
        status, headers, body = request(self.prefix + 'cards/note.html', method='HEAD')
        self.assertEqual((status, body, int(headers['Content-Length'])), (200, b'', 20))
        self.assertEqual(request(self.prefix + 'media/audio.mp3', headers={'Range': 'bytes=100-110'})[0], 416)
        self.assertEqual(request(self.prefix + 'media/')[0], 403)


if __name__ == '__main__':
    unittest.main()
