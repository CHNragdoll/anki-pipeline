"""Shared output storage, source identity and persistent transport contracts."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled_build as build
from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materializer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CompiledBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self):
        root = self.root / 'source'
        root.mkdir()
        (root / 'media').mkdir()
        sides = ['<!doctype html><html><body>正面</body></html>',
                 '<!doctype html><html><body>完整背面😀</body></html>']
        payload = json.dumps(sides, ensure_ascii=False).replace('<', '\\u003c')
        wrapper = web.card_shell(payload, '../media/').encode()
        (root / 'card.html').write_bytes(wrapper)
        value = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': sha(wrapper),
                 'source_payload_sha256': sha(payload.encode()), 'modules': {},
                 'sides': [materializer.materialize_side(side, materializer.ReadOnlyMedia(root / 'media')) for side in sides]}
        raw = json.dumps(value, ensure_ascii=False).encode()
        (root / 'card.json').write_bytes(raw)
        return root, {'path': 'card.html', 'sha256': sha(wrapper)}, {'path': 'card.json', 'sha256': sha(raw)}

    def test_complete_bytes_deduplicate_without_overwriting_another_file(self):
        store = build.ArtifactStore(self.root / 'store')
        raw = '完整原文和审核😀'.encode()
        one = store.put(raw, 'html')
        inode = (store.assets / one['src']).stat().st_ino
        self.assertEqual(store.put(raw, 'html'), one)
        self.assertEqual((store.assets / one['src']).stat().st_ino, inode)
        self.assertEqual(store.descriptor(one)['bytes'], len(raw))
        (store.assets / one['src']).write_bytes(b'outside change')
        with self.assertRaisesRegex(ValueError, 'pin'):
            store.put(raw, 'html')
        self.assertEqual((store.assets / one['src']).read_bytes(), b'outside change')

    def test_address_symlink_and_existing_store_are_rejected(self):
        store = build.ArtifactStore(self.root / 'store')
        outside = self.root / 'outside'
        outside.write_bytes(b'owned elsewhere')
        raw = b'new product'
        (store.assets / ('_qa_compiled_' + sha(raw) + '.html')).symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            store.put(raw, 'html')
        with self.assertRaises(FileExistsError):
            build.ArtifactStore(store.root)
        self.assertEqual(outside.read_bytes(), b'owned elsewhere')

    def test_failed_write_never_publishes_a_partial_content_address(self):
        store = build.ArtifactStore(self.root / 'store')
        def fail(stream, raw):
            stream.write(raw[:3])
            raise OSError('disk full fixture')
        with patch.object(build, '_write_all', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'disk full'):
                store.put(b'full original content', 'html')
        self.assertEqual(list(store.assets.iterdir()), [])

    def test_short_writes_preserve_utf8_and_zero_write_is_rejected(self):
        class Short(io.BytesIO):
            def write(self, raw):
                return super().write(bytes(raw[:3]))
        stream = Short()
        raw = '句子😀完整'.encode()
        build._write_all(stream, raw)
        self.assertEqual(stream.getvalue(), raw)
        with self.assertRaises(OSError):
            build._write_all(type('Zero', (), {'write': lambda *_: 0})(), raw)

    def test_authored_cohort_keeps_complete_source_without_launching_worker(self):
        root, wrapper, artifact = self.source()
        original = (root / 'card.html').read_bytes(), (root / 'card.json').read_bytes()
        with build.CompiledBuild(self.root / 'build') as context:
            result = context.build(root, wrapper, artifact, identity='book:note', policy={'external': {}, 'inline': []},
                                   source_url='https://study.invalid/book/index.html')
            self.assertEqual(result['mode'], 'authored')
            self.assertTrue(result['source_unchanged'])
            self.assertIsNone(context.worker)
            result['mode'] = 'outside mutation'
            again = context.build(root, wrapper, artifact, identity='book:note', policy={'external': {}, 'inline': []},
                                  source_url='https://study.invalid/book/index.html')
            self.assertEqual(again['mode'], 'authored')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                context.build(root, wrapper, artifact, identity='book:note', policy={'external': {}, 'inline': []},
                              source_url='https://study.invalid/other/index.html')
        self.assertEqual(original, ((root / 'card.html').read_bytes(), (root / 'card.json').read_bytes()))

    def test_wrong_source_or_runtime_pin_is_not_a_successful_cached_result(self):
        root, wrapper, artifact = self.source()
        with build.CompiledBuild(self.root / 'build') as context:
            value = json.loads((root / 'card.json').read_bytes())
            value['source_payload_sha256'] = '0' * 64
            raw = json.dumps(value).encode()
            (root / 'card.json').write_bytes(raw)
            artifact['sha256'] = sha(raw)
            with self.assertRaisesRegex(ValueError, 'payload'):
                context.build(root, wrapper, artifact, identity='book:note', policy={},
                              source_url='https://study.invalid/book/index.html')
            self.assertEqual(context.cache, {})
        with patch.object(build, 'RUNTIME_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'runtime pin'):
                build.CompiledBuild(self.root / 'wrong-runtime')

    def test_packaged_runtime_is_exact_existing_complete_binder(self):
        fixture = Path(__file__).parent / 'fixtures/experimental-compiled-card-v1/history-slots-v1/runtime.js'
        raw = (build.COMPILED / 'card-runtime.js').read_bytes()
        self.assertEqual(raw, fixture.read_bytes())
        self.assertEqual(sha(raw), build.RUNTIME_SHA256)

    def test_success_cleanup_rejects_replaced_job_directory(self):
        stage = self.root / 'job'
        stage.mkdir()
        (stage / 'own.txt').write_text('own data')
        descriptor = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            renamed = self.root / 'original-job'
            stage.rename(renamed)
            stage.mkdir()
            (stage / 'foreign.txt').write_text('preserve foreign data')
            with self.assertRaisesRegex(ValueError, 'ownership changed'):
                build._clear_job(stage, descriptor)
            self.assertEqual((stage / 'foreign.txt').read_text(), 'preserve foreign data')
            self.assertEqual((renamed / 'own.txt').read_text(), 'own data')
        finally:
            os.close(descriptor)

    def test_success_cleanup_is_fd_relative_and_does_not_follow_child_symlink(self):
        stage = self.root / 'job'
        stage.mkdir()
        (stage / 'inputs').mkdir()
        (stage / 'inputs/data').write_text('temporary copy')
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'raw-source').write_text('preserve source')
        (stage / 'link').symlink_to(outside, target_is_directory=True)
        descriptor = os.open(stage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            build._clear_job(stage, descriptor)
            self.assertEqual(list(stage.iterdir()), [])
            self.assertEqual((outside / 'raw-source').read_text(), 'preserve source')
        finally:
            os.close(descriptor)

    def test_cache_rechecks_original_resources_and_audit_record(self):
        with build.CompiledBuild(self.root / 'build') as context:
            html = context.store.put(b'<p>complete</p>', 'html')
            profile = context.store.put(b'{}', 'json')
            css = context.store.put(b'body{color:blue}', 'css')
            evidence = context.store.put(b'{"reconciled":true}', 'json')
            record = context.store.put(json.dumps({'evidence': {'proof': evidence}}).encode(), 'json')
            result = {'mode': 'compiled', 'entry': {'html': html, 'profile': profile},
                      'runtime': context.runtime, 'record': record,
                      'resources': {'https://study.invalid/style.css': context.store.descriptor(css)}}
            context._verify_cached_result(result)
            (context.store.assets / css['src']).write_bytes(b'outside modification')
            with self.assertRaisesRegex(ValueError, 'pin'):
                context._verify_cached_result(result)
            (context.store.assets / css['src']).write_bytes(b'body{color:blue}')
            (context.store.assets / evidence['src']).write_bytes(b'changed evidence')
            with self.assertRaisesRegex(ValueError, 'pin'):
                context._verify_cached_result(result)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for the existing profile emitter')
    def test_python_client_reuses_actual_worker_and_recovers_after_declined_job(self):
        from tests.test_study_compiled_profiles import FIXTURE_JS
        root = Path(__file__).resolve().parents[1]
        script = FIXTURE_JS + '\nprocess.stdout.write(fixture(process.argv[1]).requestFile);'
        result = subprocess.run(['node', '-e', script, str(self.root)], cwd=root,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        request = Path(result.stdout)
        worker = build.BuildWorker(self.root / 'worker.log')
        try:
            pid = worker.process.pid
            with self.assertRaisesRegex(ValueError, 'semantic failed'):
                worker.run('semantic', request, self.root / 'declined')
            descriptor, report = worker.run('profile', request, self.root / 'profile')
            self.assertEqual(worker.process.pid, pid)
            self.assertEqual(report['schema'], 'study-compiled-profile-result.v1')
            self.assertEqual(sha(Path(descriptor['path']).read_bytes()), descriptor['sha256'])
            self.assertIsNone(worker.process.poll())
        finally:
            worker.close()
        with self.assertRaisesRegex(RuntimeError, 'no automatic restart'):
            worker.run('profile', request, self.root / 'never-restarted')
        self.assertFalse((self.root / 'never-restarted').exists())


if __name__ == '__main__':
    unittest.main()
