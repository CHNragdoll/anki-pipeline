"""Complete-ready gate caches membership without caching readiness facts."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME


class GateMembersTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires existing JavaScript runtime")
    def test_membership_cache_preserves_dynamic_readiness_and_cleanup(self):
        start = PREPARED_FRAME_RUNTIME.find("function gateMemberCache(")
        if start < 0:
            start = PREPARED_FRAME_RUNTIME.index("function waitPrepared(")
        stop = PREPARED_FRAME_RUNTIME.index("\nasync function prepareView", start)
        fixture = (Path(__file__).parent / "fixtures/study-gate-members-contract.cjs").read_text()
        result = subprocess.run(
            [shutil.which("node"), "-e", fixture],
            input=json.dumps({"code": PREPARED_FRAME_RUNTIME[start:stop]}),
            text=True, capture_output=True, timeout=30,
            cwd=Path(__file__).resolve().parents[1],
        )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest("requires existing jsdom dependency")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["passed"])
        self.assertEqual(report["contracts"], 15)
