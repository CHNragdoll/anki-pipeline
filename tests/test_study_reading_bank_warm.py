"""Bound-only prewarming preserves the real ReadingBank verification lifecycle."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


FIXTURES = Path(__file__).parent / 'fixtures'


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class ReadingBankWarmTests(unittest.TestCase):
    def test_real_bank_and_current_module_callsite_preserve_validation_and_disposal(self):
        from anki_pipeline import study_catalog_web_materialize as materialize

        source = (FIXTURES / 'study-reading-bank-runtime.js').read_text()
        # Extracted byte-identically from approved prepared modules 7f16cca5...
        # (original 5c361607...) and 6a2b0f26... (original be39224f...).
        # The fixture retains every original validator and the original 256 cap;
        # the contract applies the current, separately tested 2048 cache policy.
        self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),
                         '988fc9f1cc3494669504f50ad621bd707cea14b7242a0788643d711364f711f2')
        begin = materialize.PREPARED_FRAME_RUNTIME.index(' for(const item of scripts){const module=')
        end = materialize.PREPARED_FRAME_RUNTIME.index('\n', begin + 1)
        result = subprocess.run(
            [shutil.which('node'), str(FIXTURES / 'study-reading-bank-warm-contract.cjs')],
            input=json.dumps({'source': source,
                              'adapter': getattr(materialize, 'SHARED_READING_BANK_WARM_ADAPTER', ''),
                              'module': materialize.PREPARED_FRAME_RUNTIME[begin:end]}),
            cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=30,
        )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['passed'], 23)
        self.assertEqual(report['unboundDigestCalls'], 0)
        self.assertEqual(report['prewarmCalls'], 2)
        self.assertEqual(report['realReadingBankSha256'], hashlib.sha256(source.encode()).hexdigest())
        self.assertEqual(report['candidateReadingBankSha256'],
                         'ff50419742d2671c44553ad5faec0dd14160d7ed09d419c9c73748efdee2d018')
        adapter = materialize.SHARED_READING_BANK_WARM_ADAPTER
        admission = ", 'b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26', '286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67'"
        self.assertEqual(adapter.count(admission), 1)
        self.assertEqual(hashlib.sha256(adapter.replace(admission, '', 1).encode()).hexdigest(),
                         'd48e83c2cf0087a92adcf3e3afeea1a981c3a8d6c0ba8db3eb3d404876fe96d1')
        self.assertEqual(hashlib.sha256(adapter.encode()).hexdigest(),
                         'f0660cfea783ef7496671763799144935f67b468f2067b3bba0b5b08a1b8b1d8')
