"""Initialization-only history staging; original nodes return before the full gate."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import (
    PREPARED_FRAME_RUNTIME, prepared_frame_html,
)


# The reviewed, browser-checked candidate is intentionally an exact checkpoint.
# Include the independently reviewed gate-members cache. Reversing that one
# addition restores the earlier db9a56f7 checkpoint exactly; staging is unchanged.
REVIEWED_FRAME_SHA256 = 'd0cec92b5e38ffef47fa19ef67460e61a306127595b47bc69f7918a5eaf8fc33'
REVIEWED_NAMES = {
    'staticHistoryCohorts': 'qaStaticHistoryCohorts',
    'staticHistoryRoots': 'qaStaticHistoryRoots',
    'staticHistorySelected': 'qaStaticHistorySelected',
    'staticHistoryForbidden': 'qaStaticHistoryForbidden',
    'staticHistoryEligible': 'qaStaticHistoryEligible',
    'staticHistoryCohort': 'qaStaticHistoryCohort',
    'stageStaticHistory': 'qaStageStaticHistory',
    'awaitStaticHistoryNative': 'qaAwaitStaticHistoryNative',
    'historyBegan': 'qaHistoryBegan',
}


class StaticHistoryInitializationTests(unittest.TestCase):
    def test_runtime_is_only_an_alpha_rename_of_the_reviewed_candidate(self):
        names = re.compile(r'\b(' + '|'.join(REVIEWED_NAMES) + r')\b')
        reviewed = names.sub(lambda match: REVIEWED_NAMES[match[0]], prepared_frame_html())
        # Match only the private local's access/assignment sites, not the word
        # history inside untouched selectors, comments or error strings.
        reviewed = re.sub(r'\bhistory(?=[?.=])', 'qaHistory', reviewed)
        self.assertEqual(hashlib.sha256(reviewed.encode()).hexdigest(), REVIEWED_FRAME_SHA256)
        self.assertNotRegex(PREPARED_FRAME_RUNTIME, r'\bqa(?:StaticHistory|StageStaticHistory|AwaitStaticHistory|History)')

    def test_original_nodes_qualification_cohort_cancellation_and_shared_full_gate(self):
        if not shutil.which('node'):
            self.skipTest('Node.js is unavailable')
        self.assertIn('const staticHistoryCohorts=', PREPARED_FRAME_RUNTIME)
        start = PREPARED_FRAME_RUNTIME.index('const staticHistoryCohorts=')
        end = PREPARED_FRAME_RUNTIME.index('function copyAttributes(', start)
        gate_start = PREPARED_FRAME_RUNTIME.index('function gateMemberCache(')
        gate_end = PREPARED_FRAME_RUNTIME.index('async function prepareView(', gate_start)
        wait_start = PREPARED_FRAME_RUNTIME.index('const historyBegan=performance.now();')
        wait_end = PREPARED_FRAME_RUNTIME.index('if(packet.metricsAsset){row.readyAt=', wait_start)
        fixture = Path(__file__).parent / 'fixtures' / 'study-static-history-contract.cjs'
        result = subprocess.run(
            [shutil.which('node'), str(fixture)],
            input=json.dumps({'helper': PREPARED_FRAME_RUNTIME[start:end],
                              'gate': PREPARED_FRAME_RUNTIME[gate_start:gate_end],
                              'wait': PREPARED_FRAME_RUNTIME[wait_start:wait_end],
                              'runtime': PREPARED_FRAME_RUNTIME}),
            text=True, capture_output=True, timeout=45,
        )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('jsdom is unavailable')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['contracts'], 13)
        self.assertGreaterEqual(report['negative_cases'], 90)
        self.assertTrue(report['passed'])
