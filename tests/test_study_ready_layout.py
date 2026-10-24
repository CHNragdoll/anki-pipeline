import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME


def _gate_runtime():
    # Keep the current QA helpers used by waitPrepared, without including the
    # unrelated compiled-profile initialization inserted before prepareView.
    start = PREPARED_FRAME_RUNTIME.index('const qaLayoutCostRecords=')
    stop = PREPARED_FRAME_RUNTIME.index("\nif(!('StudyCompiledLayoutCostStatus'", start)
    gate = PREPARED_FRAME_RUNTIME.index('function gateMemberCache(')
    end = PREPARED_FRAME_RUNTIME.index('\n/* Called only from the externally pinned', gate)
    return PREPARED_FRAME_RUNTIME[start:stop] + '\n' + PREPARED_FRAME_RUNTIME[gate:end]


class PreparedLayoutCostTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
    def test_pending_readiness_does_not_force_whole_card_layout(self):
        fixture = Path(__file__).parent / 'fixtures/study-ready-layout-contract.cjs'
        result = subprocess.run(
            [shutil.which('node'), str(fixture)],
            input=json.dumps(_gate_runtime()),
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 8)
