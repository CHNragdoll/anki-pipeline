"""Only exact prepared-module paths may omit the legacy raw-byte Range."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME


class PreparedModuleResourceTests(unittest.TestCase):
    def test_content_addressed_module_get_keeps_all_resource_proofs(self):
        begin = PREPARED_FRAME_RUNTIME.index('async function resource(')
        end = PREPARED_FRAME_RUNTIME.index('\n// Validate every execution rule', begin)
        helper = PREPARED_FRAME_RUNTIME[begin:end]
        fixture = Path(__file__).with_name('fixtures') / 'study-module-resource-contract.cjs'
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the actual resource contract')
        result = subprocess.run([node, str(fixture)], input=json.dumps(helper),
                                text=True, capture_output=True, cwd='/tmp', timeout=15)
        self.assertEqual(result.returncode, 0,
                         'resource SHA256=' + hashlib.sha256(helper.encode()).hexdigest()
                         + '\n' + result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['pass'])
        self.assertGreaterEqual(report['contracts'], 35)


if __name__ == '__main__':
    unittest.main()
