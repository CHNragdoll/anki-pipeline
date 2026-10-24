"""Known-pin verification and native-task ownership share audited helpers."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class RuntimeIntegrityTaskTests(unittest.TestCase):
    def node(self, name, payload):
        code = (Path(__file__).parent / 'fixtures' / name).read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(payload),
                                cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_real_known_pin_calls_preserve_unknown_digest_paths(self):
        report = self.node('study-known-pin-integration.cjs', {
            'frame': materialize.PREPARED_FRAME_RUNTIME, 'host': web.HOST_RUNTIME})
        self.assertEqual(report['sites'], 6)
        self.assertTrue(report['unknownDigestsUnchanged'])

    def test_private_tasks_keep_task_yield_fallback_and_owner_cleanup(self):
        report = self.node('study-projection-task-integration.cjs', {
            'runtime': materialize.PREPARED_FRAME_RUNTIME,
            'task': getattr(materialize, 'PROJECTION_TASK_RUNTIME', '')})
        self.assertTrue(report['passed'])

    def test_helpers_packaged_without_qa_or_wasm(self):
        helper = ROOT / 'anki_pipeline/templates/known-pin-integrity.js'
        self.assertTrue(helper.is_file(), 'shared known-pin helper must be packaged')
        self.assertEqual(hashlib.sha256(helper.read_bytes()).hexdigest(),
                         'eddf7d86a1d50ab18e033e7f847b27bf0999fd61d5c8c91c490b84b5a6ca4876')
        source = helper.read_text()
        self.assertEqual(web.HOST_RUNTIME.count(source), 1)
        self.assertEqual(materialize.PREPARED_FRAME_RUNTIME.count(source), 1)
        self.assertNotIn('StudyQaProjection', materialize.PREPARED_FRAME_RUNTIME)
        self.assertNotIn('qaFiveStage', materialize.PREPARED_FRAME_RUNTIME)
        self.assertNotIn('WebAssembly', materialize.PREPARED_FRAME_RUNTIME)
        self.assertIn('"templates/*"', (ROOT / 'pyproject.toml').read_text())
