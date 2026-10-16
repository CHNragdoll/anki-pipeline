"""The common verified module path skips graphs only for impossible merges."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'
TEMPLATES = ROOT / 'anki_pipeline' / 'templates'


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class NativeGroupCandidatesTests(unittest.TestCase):
    def test_verified_source_callsite_uses_candidate_adapter_after_previous_algorithms(self):
        from anki_pipeline import study_catalog_web_materialize as m
        self.assertIn('function adaptNativeGroupCoarseBuckets(', m.PREPARED_FRAME_RUNTIME)
        begin = m.PREPARED_FRAME_RUNTIME.index(' for(const item of scripts){const module=')
        end = m.PREPARED_FRAME_RUNTIME.index('\n win.AnkiSlimDecode', begin)
        call = m.PREPARED_FRAME_RUNTIME[begin:end]
        code = (FIXTURES / 'study-native-group-candidates-integration.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], cwd=tempfile.gettempdir(),
                                input=json.dumps({'adapter': m.GROUP_CANDIDATES_ADAPTER, 'call': call,
                                                  'warmAdapter': m.SHARED_READING_BANK_WARM_ADAPTER,
                                                  'fineAdapter': m.FINE_WHOLE_ADAPTER,
                                                  'source': (FIXTURES / 'study-native-group-candidates-runtime.js').read_text()
                                                  + '\n' + (FIXTURES / 'study-reading-bank-runtime.js').read_text()
                                                  + '\n' + (FIXTURES / 'study-native-fine-runtime.js').read_text(),
                                                  'history': m.PREPARED_FRAME_RUNTIME[m.PREPARED_FRAME_RUNTIME.index('const staticHistoryCohorts='):m.PREPARED_FRAME_RUNTIME.index('function stageStaticHistory(')]}),
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 8)

    def test_group_behavior_matches_legacy_with_singletons_late_parts_and_dispose(self):
        from anki_pipeline import study_catalog_web_materialize as m
        self.assertEqual(hashlib.sha256(m.GROUP_CANDIDATES_ADAPTER.encode()).hexdigest(),
                         '840879cbda99e4f69577774d77774a4712b22a07f66098ff33d963cf11ae1c5c')
        # Only the production comment differs from the independently reviewed
        # prototype; keep the complete adapter algorithm and guards identical.
        prototype = m.GROUP_CANDIDATES_ADAPTER.replace(
            '// Only call after the existing host verifies the exact raw/prepared module SHA.',
            '// QA-only prototype: caller must first verify the exact raw/prepared module SHA.', 1)
        self.assertEqual(hashlib.sha256(prototype.encode()).hexdigest(),
                         '173794bf59646871f3abefd5400a5587a9f3faa293d6d583b3138ab8fec5f51c')
        self.assertEqual(hashlib.sha256((FIXTURES / 'study-native-group-candidates-runtime.js').read_bytes()).hexdigest(),
                         '71d58ba4d44f6c4636f00d017e1cc67aec01fb2286f3ec0880142fd90720993b')
        env = {**os.environ, 'GROUP_CANDIDATES_TEMPLATES': str(TEMPLATES),
               'GROUP_CANDIDATES_SOURCE': str(FIXTURES / 'study-native-group-candidates-runtime.js')}
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
                                 str(FIXTURES / 'study-native-group-candidates.test.cjs')],
                                cwd=tempfile.gettempdir(), env=env, text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 14\n', result.stdout)
