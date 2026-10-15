"""Run the DOM runtime regressions through the project's local Node runtime."""
import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SlimRuntimeTests(unittest.TestCase):
    def test_lossless_lazy_runtime(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the production card runtime tests')
        result = subprocess.run(
            [node, '--test', 'tests/slim-apkg-runtime.test.cjs'],
            cwd=ROOT, text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_transport_preserves_runtime_regressions(self):
        node = shutil.which('node')
        self.assertIsNotNone(node)
        result = subprocess.run(
            [node, '--test', 'tests/slim-apkg-runtime.test.cjs', 'tests/slim-apkg-v2-integration.test.cjs', 'tests/slim-shared-codec.test.cjs'],
            cwd=ROOT, text=True, capture_output=True, timeout=60,
            env={**os.environ, 'ANKI_SLIM_RUNTIME':'../anki_pipeline/templates/slim-apkg-v2.js'},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
