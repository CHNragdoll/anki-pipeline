"""Initialization-only history staging; original nodes return before the full gate."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import (
    AUTHORED_ALGORITHM_RUNTIME, KNOWN_PIN_INTEGRITY_RUNTIME, PROJECTION_TASK_RUNTIME,
    PREPARED_FRAME_RUNTIME, prepared_frame_html,
)


# The reviewed, browser-checked candidate is intentionally an exact checkpoint.
# Include the independently reviewed gate-members cache and two terminal-error
# fixes. Reversing exactly those fixes must restore the previous full-page pin;
# no static-history algorithm, source order or complete-ready gate was changed.
# The subsequent numbering/group algorithms have their own behavioral/pin tests;
# reverse only their explicit common-host wiring before this historical seal.
PREVIOUS_REVIEWED_FRAME_SHA256 = 'd0cec92b5e38ffef47fa19ef67460e61a306127595b47bc69f7918a5eaf8fc33'
REVIEWED_FRAME_SHA256 = 'f8916e4fe67748ca466e6d8804dcbfb0697bc4c8d4cfe1c600d1d0d55b10ad51'
TERMINAL_ERROR_FIXES = (
    (
        'requestAnimationFrame(check)}catch(error){release();throw error}}try{requestAnimationFrame(check)}catch(error){release();throw error}})}',
        'requestAnimationFrame(check)}catch(error){reject(error)}}try{requestAnimationFrame(check)}catch(error){release();throw error}})}',
    ),
    (
        'const result=promote(view,requestedAt);if(result&&!index)prepareBack(packet);return result}',
        "const result=promote(view,requestedAt);if(!result&&ownsView(view))throw Error('Prepared side lost readiness before commit');if(result&&!index)prepareBack(packet);return result}",
    ),
)
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
        html = prepared_frame_html()
        # Reverse only Bank's independent fixed-pin checker hook; its helper
        # is removed with the shared authored runtime below, not by resealing.
        bank_call = ('adaptNativeBankSideChecker('
                     'adaptNativeSlimLoadChecker(slimLoadSource,item.pin),item.pin)')
        self.assertEqual(html.count(bank_call), 1)
        html = html.replace(bank_call, 'adaptNativeSlimLoadChecker(slimLoadSource,item.pin)')
        ranges_call = ('adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask('
                       'adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin)')
        coarse_call = 'adaptNativeGroupCoarseBuckets(' + ranges_call + ',item.pin)'
        warm_call = 'adaptSharedReadingBankWarm(' + coarse_call + ',item.pin)'
        fine_call = 'adaptNativeFineWholeProbe(' + warm_call + ',item.pin)'
        # Reverse the separately reviewed private Slim checker wrapper before
        # the older seal; the source/native/gate and prior adapters stay exact.
        checker_call = ('const slimLoadSource=' + fine_call
                        + ';withSlimLoadChecker(win,enabled=>execute(doc,enabled?'
                        'adaptNativeSlimLoadChecker(slimLoadSource,item.pin):slimLoadSource,'
                        "item.pin+'-prepared-'+module.sha256))")
        original_execute = 'execute(doc,' + fine_call + ",item.pin+'-prepared-'+module.sha256)"
        self.assertEqual(html.count(checker_call), 1)
        html = html.replace(checker_call, original_execute)
        self.assertEqual(html.count(fine_call), 1)
        html = html.replace(fine_call, warm_call)
        self.assertEqual(html.count(warm_call), 1)
        html = html.replace(warm_call, coarse_call)
        self.assertEqual(html.count(coarse_call), 1)
        html = html.replace(coarse_call, ranges_call)
        original_call = ('adaptNativeGroupTranslationText(adaptNativeProjectionTask('
                         'adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin)')
        self.assertEqual(html.count(ranges_call), 1)
        html = html.replace(ranges_call, original_call)
        # Reverse only the reviewed integrity/task wiring before checking the
        # earlier algorithm seal. The verifier helper has its own exact pin.
        verifier = (KNOWN_PIN_INTEGRITY_RUNTIME + '\n'
                    + "const knownPinMatches=createKnownPinVerifier(globalThis,async bytes=>{const provider=parent.crypto.subtle?parent.crypto:window.crypto;return Array.from(new Uint8Array(await provider.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('')});\n"
                    + PROJECTION_TASK_RUNTIME + '\n')
        self.assertEqual(html.count(verifier), 1)
        html = html.replace(verifier, '')
        integrity_task_wiring = (
            ("if(!await knownPinMatches(text,pin))throw Error('Prepared resource byte SHA differs');",
             "if(await sha(text)!==pin)throw Error('Prepared resource byte SHA differs');"),
            ("if(!await knownPinMatches(raw,pin))throw Error('Prepared native registration SHA differs');",
             "if(await sha(raw)!==pin)throw Error('Prepared native registration SHA differs');"),
            ("const verified=await Promise.all([knownPinMatches(packet.sides[index],prepared.proof.source_sha256),knownPinMatches(prepared.html,prepared.proof.expanded_sha256)]);if(!verified.every(Boolean))throw Error('Prepared body differs from its source proof');",
             "const hashes=await Promise.all([sha(packet.sides[index]),sha(prepared.html)]);if(hashes[0]!==prepared.proof.source_sha256||hashes[1]!==prepared.proof.expanded_sha256)throw Error('Prepared body differs from its source proof');"),
            ('adaptNativeProjectionTask(adaptNativeProjectionLookup(code,item.pin),item.pin)',
             'adaptNativeProjectionLookup(code,item.pin)'),
            ('const projectionOwner=projectionTaskBegin(win,packet,index,token,active);try{await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw))}finally{projectionOwner?.close()}',
             'await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw));'),
            ('function startSession(packet,session){projectionTaskCloseAll();', 'function startSession(packet,session){'),
            ('reservedToken)return false;projectionTaskCloseAll();', 'reservedToken)return false;'),
        )
        for after, before in integrity_task_wiring:
            self.assertEqual(html.count(after), 1)
            html = html.replace(after, before)
        self.assertEqual(html.count(AUTHORED_ALGORITHM_RUNTIME), 1)
        html = html.replace(AUTHORED_ALGORITHM_RUNTIME, '')
        algorithm_wiring = (
            (" if(originalPin==='9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1')return adaptExampleNumbering(code,originalPin);\n", ''),
            ('execute(doc,adaptNativeGroupTranslationText(adaptNativeProjectionLookup(code,item.pin),item.pin),',
             'execute(doc,adaptNativeProjectionLookup(code,item.pin),'),
            ("scripts.map(item=>['d34134c8918205c51c842963c7354f090e6041dcecd00480e695d4e874b8e21d','ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'].includes(item.pin)?'9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1':item.pin)",
             'scripts.map(item=>item.pin)'),
        )
        for after, before in algorithm_wiring:
            self.assertEqual(html.count(after), 1)
            html = html.replace(after, before)
        previous = html
        for before, after in TERMINAL_ERROR_FIXES:
            self.assertEqual(previous.count(after), 1)
            previous = previous.replace(after, before)

        def reviewed_html(value):
            value = names.sub(lambda match: REVIEWED_NAMES[match[0]], value)
            # Match only the private local's access/assignment sites, not the
            # word history in unchanged selectors, comments or error strings.
            return re.sub(r'\bhistory(?=[?.=])', 'qaHistory', value)

        self.assertEqual(hashlib.sha256(reviewed_html(previous).encode()).hexdigest(),
                         PREVIOUS_REVIEWED_FRAME_SHA256)
        reviewed = reviewed_html(html)
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
