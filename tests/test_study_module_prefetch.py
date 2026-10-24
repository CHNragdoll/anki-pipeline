"""Prepared module reads overlap authored reads without moving execution."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME


class PreparedModulePrefetchTests(unittest.TestCase):
    def test_verified_modules_are_prefetched_after_policy_validation(self):
        begin = PREPARED_FRAME_RUNTIME.index('async function collectAuthoredScripts(')
        end = PREPARED_FRAME_RUNTIME.index('\nfunction installCigen(', begin)
        collector = PREPARED_FRAME_RUNTIME[begin:end]
        begin = PREPARED_FRAME_RUNTIME.index(
            ' for(const item of scripts){const module=packet.prepared.modules?.[item.pin];'
        )
        end = PREPARED_FRAME_RUNTIME.index('\n', begin + 1)
        module_loop = PREPARED_FRAME_RUNTIME[begin:end]
        begin = PREPARED_FRAME_RUNTIME.index(' const authoredComplete=')
        end = PREPARED_FRAME_RUNTIME.index('\n // Media adopted', begin)
        author_loop = PREPARED_FRAME_RUNTIME[begin:end]
        fixture = Path(__file__).with_name('fixtures') / 'study-module-prefetch-contract.cjs'
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the actual-runtime contract')
        result = subprocess.run(
            [node, str(fixture)],
            input=json.dumps({'collector': collector, 'moduleLoop': module_loop,
                              'authorLoop': author_loop}),
            capture_output=True, text=True, cwd='/tmp', timeout=15,
        )
        self.assertEqual(result.returncode, 0,
                         'collector SHA256=' + hashlib.sha256(collector.encode()).hexdigest()
                         + '\n' + result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['pass'])
        self.assertGreaterEqual(len(report['passed']), 16)


if __name__ == '__main__':
    unittest.main()
