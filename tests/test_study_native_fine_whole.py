"""The verified shared module uses Fine's exact two-stage whole probe."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

FIXTURES = Path(__file__).parent / 'fixtures'


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class NativeFineWholeTests(unittest.TestCase):
    def module_contract(self, mode):
        from anki_pipeline import study_catalog_web_materialize as materialize

        source = (FIXTURES / 'study-native-fine-runtime.js').read_text()
        # Complete 6,627-byte IIFE, identical in both source-pinned originals.
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                         'b0be6520ffe3ee5e0ee1efa901e5b724f3b2d80364d73910d2f64c8f1dc10c71')
        begin = materialize.PREPARED_FRAME_RUNTIME.index(' for(const item of scripts){const module=')
        end = materialize.PREPARED_FRAME_RUNTIME.index('\n win.AnkiSlimDecode', begin)
        result = subprocess.run(
            [shutil.which('node'), str(FIXTURES / 'study-native-fine-whole-integration.cjs')],
            input=json.dumps({'adapter': getattr(materialize, 'FINE_WHOLE_ADAPTER', ''),
                              'call': materialize.PREPARED_FRAME_RUNTIME[begin:end],
                              'source': source, 'mode': mode}),
            cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_real_fine_dom_contracts_execute_current_module_callsite(self):
        prepared = self.module_contract('prepare')
        with tempfile.TemporaryDirectory() as folder:
            candidate = Path(folder) / 'fine-candidate.js'
            candidate.write_text(prepared['candidate'])
            result = subprocess.run(
                [shutil.which('node'), '--test', '--test-reporter=tap',
                 str(FIXTURES / 'study-native-fine-whole.test.cjs')],
                env={**os.environ, 'FINE_SOURCE': str(candidate),
                     'FINE_BASELINE': str(FIXTURES / 'study-native-fine-runtime.js')},
                cwd=folder, text=True, capture_output=True, timeout=30,
            )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 11\n', result.stdout)

    def test_exact_dual_pin_inverse_and_real_callsite_resource_cancel_once_guards(self):
        from anki_pipeline import study_catalog_web_materialize as materialize

        report = self.module_contract('contracts')
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['contracts']), 8)
        self.assertEqual(hashlib.sha256(materialize.FINE_WHOLE_ADAPTER.encode()).hexdigest(),
                         '41e76ef2439ca7e100a11621d5fc620f74bd7efb95675f9426759b01155b5aed')
