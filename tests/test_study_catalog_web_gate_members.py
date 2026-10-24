"""Complete-ready gate caches membership without caching readiness facts."""
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


class GateMembersTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires existing JavaScript runtime")
    def test_membership_cache_preserves_dynamic_readiness_and_cleanup(self):
        fixture = (Path(__file__).parent / "fixtures/study-gate-members-contract.cjs").read_text()
        result = subprocess.run(
            [shutil.which("node"), "-e", fixture],
            input=json.dumps({"code": _gate_runtime()}),
            text=True, capture_output=True, timeout=30,
            cwd=Path(__file__).resolve().parents[1],
        )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest("requires existing jsdom dependency")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["contracts"], 15)
