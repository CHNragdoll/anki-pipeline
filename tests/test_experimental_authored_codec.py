"""Portable, isolated acceptance of the reviewed authored-codec small prototype."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURE = REPOSITORY / "tests/fixtures/experimental-authored-codec-v1"


@unittest.skipUnless(shutil.which("node"), "requires existing Node.js")
@unittest.skipUnless((REPOSITORY / "node_modules/jsdom/package.json").is_file(),
                     "requires existing node_modules/jsdom; never installs dependencies")
class ExperimentalAuthoredCodecTests(unittest.TestCase):
    def test_original_fourteen_groups_two_p2_contracts_and_exact_inverses(self):
        result = subprocess.run(
            [sys.executable, "-B", str(FIXTURE / "run.py")],
            cwd=REPOSITORY,
            env={**os.environ, "NODE_PATH": str(REPOSITORY / "node_modules")},
            capture_output=True, text=True, timeout=120, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source_files_verified"], 50)
        self.assertEqual(report["base_contract_groups"], 14)
        self.assertEqual(report["focused_p2_programs"], 2)
        self.assertTrue(report["exact_code_html_authors_inverse"])
        self.assertTrue(report["exact_portability_inverse"])
        self.assertTrue(report["temporary_stage_removed"])
        self.assertFalse(report["historical_noninstallable_executed"])
        self.assertEqual([r["exit"] for r in report["programs"]], [0, 0, 0, 0])
        print(result.stdout)


if __name__ == "__main__":
    unittest.main()
