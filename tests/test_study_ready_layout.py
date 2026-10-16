import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME


class PreparedLayoutCostTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
    def test_pending_readiness_does_not_force_whole_card_layout(self):
        begin = PREPARED_FRAME_RUNTIME.index('function gateMemberCache(')
        end = PREPARED_FRAME_RUNTIME.index('\nasync function prepareView(', begin)
        fixture = Path(__file__).parent / 'fixtures/study-ready-layout-contract.cjs'
        result = subprocess.run(
            [shutil.which('node'), str(fixture)],
            input=json.dumps(PREPARED_FRAME_RUNTIME[begin:end]),
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 8)
