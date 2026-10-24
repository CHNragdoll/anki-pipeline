"""Bounded real-card contracts for an isolated compiled FRAME candidate.

No product import, database, live HTTP service, large card, or APKG is used.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


FIXTURE = Path(__file__).parent / "fixtures/experimental-authored-codec-frame-v1"
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "requires existing Node.js")
class ExperimentalAuthoredCodecFrameTests(unittest.TestCase):
    def run_node(self, name: str, *args: str, success: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [shutil.which("node"), str(FIXTURE / name), *args],
            cwd=ROOT, env={**os.environ, "NODE_PATH": str(ROOT / "node_modules")},
            text=True, capture_output=True, timeout=40, check=False,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, "Negative control unexpectedly passed")
        return result

    def test_sealed_small_source_and_exact_candidate_inverses(self):
        manifest = json.loads((FIXTURE / "FROZEN.json").read_bytes())
        actual = {str(p.relative_to(FIXTURE)) for p in FIXTURE.rglob("*") if p.is_file()}
        self.assertEqual(actual, {row["path"] for row in manifest["files"]} | {"FROZEN.json"})
        for row in manifest["files"]:
            path = FIXTURE / row["path"]
            self.assertFalse(path.is_symlink())
            raw = path.read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (row["bytes"], row["sha256"]), row["path"])
        for row in manifest["reused_inputs"]:
            raw = (ROOT / row["path"]).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                             (row["bytes"], row["sha256"]), row["path"])
        proof = json.loads(self.run_node("inverse.test.cjs").stdout)
        for key in ("frameInverseExact", "capabilityInverseExact", "projectInverseExact",
                    "authoredGuardInverseExact", "noNewProfileParseHashFreeze"):
            self.assertTrue(proof[key], key)
        self.assertEqual(proof["candidateFrameSha256"], manifest["candidate"]["frame_sha256"])
        self.assertEqual(proof["originalScriptLexemesAndOrder"], 15)
        self.assertEqual(proof["sourceArtifactSha256"],
                         "a6d88ed5971734e4366cfb71b3077a2f4e938b6bc03de24218738e3edb58ddf8")
        report = json.loads(gzip.decompress((FIXTURE / "export-report.json.gz").read_bytes()))
        self.assertTrue(report["source_iframe_attributes_srcdoc_sandbox_exact"])

    def test_real_policy_resource_ledger_red_then_green(self):
        red = self.run_node("ledger.test.cjs", "--red", success=False)
        self.assertIn("filename-only eligibility rejected", red.stderr)
        proof = json.loads(self.run_node("ledger.test.cjs").stdout)
        self.assertTrue(proof["approvedRealCohort"])
        self.assertTrue(proof["filenameIndependentIdentity"])
        self.assertEqual(proof["rejectedUnchangedCases"], 9)

    def test_authenticated_reuse_and_one_shot_failure_boundaries(self):
        result = self.run_node("capability.test.cjs")
        self.assertEqual(result.stdout.count("PASS "), 5)
        self.assertIn("CAPABILITY CONTRACTS 5", result.stdout)

    def test_full_real_frame_original_authors_red_then_green(self):
        red = self.run_node("frame.test.cjs", "--red", success=False)
        self.assertIn("first certified codec still repeats static discovery", red.stderr)
        proof = json.loads(self.run_node("frame.test.cjs").stdout)
        self.assertEqual((proof["baselineScans"], proof["candidateScans"]), (6, 3))
        self.assertEqual(len(proof["sourceCohort"]), 14)
        self.assertEqual(len(proof["negativeCases"]), 5)
        for key in ("fontGateVerified", "nativeReady", "fullFrameMounted",
                    "allOriginalAuthorsExecuted", "sameDOM"):
            self.assertTrue(proof[key], key)
        self.assertIn("JSDOM only", proof["scope"])
        self.assertIn("simulated", proof["childGate"])


if __name__ == "__main__":
    unittest.main()
