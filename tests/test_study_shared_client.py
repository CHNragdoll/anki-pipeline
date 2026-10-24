"""Portable bounded shared-learning client contracts; no ignored imports or service."""
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/study-shared-client'
RUNTIME = ROOT / 'anki_pipeline/web_runtime/study'


class StudySharedClientTests(unittest.TestCase):
    def test_original_source_fixtures_are_byte_exact_and_self_contained(self):
        manifest = json.loads((FIXTURE / 'source-seals.json').read_text())
        for row in manifest['files']:
            data = (FIXTURE / row['original_fixture']).read_bytes()
            if row.get('encoding') == 'base64':
                self.assertEqual(len(data), row['encoded_bytes'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['encoded_sha256'])
                data = base64.b64decode(data.rstrip(b'\n'), validate=True)
            self.assertEqual(len(data), row['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row['sha256'])

    def test_business_and_keyboard_functions_preserve_original_bytes(self):
        before = (FIXTURE / 'original-study.js').read_text()
        after = (RUNTIME / 'study.js').read_text()
        names = ['api', 'validateSession', 'applySession', 'fetchSession', 'refreshSession',
                 'loadOverview', 'requestId', 'submitAnswer', 'undoAnswer', 'saveSettings',
                 'loadStats', 'downloadBackup', 'chooseRestore', 'confirmRestore', 'keyboard']
        def block(text, name):
            start = re.search(r'^  (?:async )?function ' + name + r'\(', text, re.M)
            self.assertIsNotNone(start, name)
            remaining = text[start.start():]
            end = re.search(r'^  (?:async )?function |^  elements\[', remaining[start.end() - start.start():], re.M)
            self.assertIsNotNone(end, name)
            return remaining[:start.end() - start.start() + end.start()]
        for name in names:
            with self.subTest(function=name):
                self.assertEqual(block(before, name), block(after, name))

    def test_preferences_preserve_all_rules_except_authored_side_selectors(self):
        before = (FIXTURE / 'original-preferences.js').read_text()
        after = (RUNTIME / 'preferences.js').read_text()
        replacements = [
            ("'#preview-front .word{", "'#preview-front .word,.vocab-front .word,.vocab-back .word{"),
            ('html,body,#preview-front,#preview-back{', 'html,body,#preview-front,#preview-back,.vocab-front,.vocab-back{'),
            ('#preview-back h2,#preview-back h3,#preview-back h4,', '#preview-back h2,#preview-back h3,#preview-back h4,.vocab-back h2,.vocab-back h3,.vocab-back h4,'),
            ("doc.querySelector('#preview-front .phonetic-accent-'+accent)", "doc.querySelector('#preview-front .phonetic-accent-'+accent+',.vocab-front .phonetic-accent-'+accent+',.vocab-back .phonetic-accent-'+accent)"),
            ("doc.querySelector('#preview-front .word-audio-play')", "doc.querySelector('#preview-front .word-audio-play,.vocab-front .word-audio-play,.vocab-back .word-audio-play')"),
        ]
        for old, new in reversed(replacements):
            self.assertEqual(after.count(new), 1)
            after = after.replace(new, old)
        self.assertEqual(after, before)

    def _actual_payload(self):
        from anki_pipeline import study_catalog_web as web
        from anki_pipeline import study_catalog_web_materialize as materialize
        from tests.test_study_catalog_web_front import front_host_fixture
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for the installed jsdom fixture')
        payload = front_host_fixture()
        def packed(value):
            return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        def sha(value):
            return hashlib.sha256(value.encode()).hexdigest()
        index = json.loads(payload['files']['prepared-index.json'])
        for identity in ('A', 'B'):
            name = ('a' if identity == 'A' else 'b') * 64
            previous, current = 'cards/' + identity + '.html', 'cards/' + name + '.html'
            payload['files'].pop(previous)
            full = json.loads(payload['files']['full-' + identity + '.json'])
            disclosure = '<details id="audit-disclosure"><summary>审核依据</summary><p>原句、chunk与说明</p></details>'
            sides = [row['html'].replace('</body>', disclosure + '</body>') for row in full['sides']]
            literal = json.dumps(sides, ensure_ascii=False)
            wrapper = web.card_shell(literal, '../media/')
            payload['files'][current] = wrapper
            full['source_wrapper_sha256'] = sha(wrapper)
            full['source_payload_sha256'] = sha(literal)
            for row, html in zip(full['sides'], sides):
                row['html'] = html
                row['proof']['source_sha256'] = sha(html)
                row['proof']['expanded_sha256'] = sha(html)
            full_text = packed(full)
            payload['files']['full-' + identity + '.json'] = full_text
            index['cards'][identity]['sha256'] = sha(full_text)
            row = json.loads(payload['files']['front-' + identity + '.json'])
            row.update(wrapper_url=current, source_front=sides[0], side=full['sides'][0],
                       source_wrapper_sha256=sha(wrapper), source_payload_sha256=sha(literal),
                       source_front_sha256=sha(sides[0]), full_prepared_sha256=sha(full_text))
            text = packed(row)
            payload['files']['front-' + identity + '.json'] = text
            index['cards'][identity]['front']['sha256'] = sha(text)
            next(row for row in payload['navigation']['cards'] if row[0] == identity)[4] = current
        payload['files']['prepared-index.json'] = packed(index)
        payload['frame_page'] = materialize.prepared_frame_html()
        payload['frame_runtime'] = web.LAN_SHA256_RUNTIME + '\n' + materialize.PREPARED_FRAME_RUNTIME
        payload['host_runtime'] = web.HOST_RUNTIME
        payload['host_sha256'] = sha(web.HOST_RUNTIME)
        payload['frame_sha256'] = sha(materialize.PREPARED_FRAME_RUNTIME)
        shared = {'html': payload['frame_page'], 'policy': {'external': {}, 'inline': []},
                  'preparedIndex': {'src': 'prepared-index.json', 'sha256': sha(payload['files']['prepared-index.json'])}}
        payload['page'] = web.library_html('通用实际小卡', total=2, shared_frame=shared)
        return payload

    def test_actual_host_and_complete_prepared_frame_with_the_consumer(self):
        payload = self._actual_payload()
        node = shutil.which('node')
        script = FIXTURE / 'actual-host-contract.cjs'
        for mode in ('button', 'digit', 'space-good', 'enter-good'):
            with self.subTest(scoring_mode=mode):
                result = subprocess.run([node, str(script)], input=json.dumps({**payload, 'scoring_mode': mode}),
                                        cwd=ROOT, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report['contracts'], 6)
                self.assertTrue(report['actual_complete_frame'])
                self.assertFalse(report['capability_stub'])
                self.assertTrue(report['commit_fact_readiness'])
                self.assertEqual(report['direct_scoring_mode'], mode)
                self.assertFalse(report['extra_scoring_preparation'])
                self.assertEqual(report['snapshot_geometry_reads'], 0)
                self.assertEqual(report['rejected_old_document_keys'], 1)

    def test_actual_same_book_a_b_a_reuses_host_navigation_and_prepared_index(self):
        payload = self._actual_payload()
        result = subprocess.run([shutil.which('node'), str(FIXTURE / 'actual-host-contract.cjs')],
                                input=json.dumps({**payload, 'scoring_mode': 'reuse'}),
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['rejected_old_document_keys'], 3)
        reuse = report['same_book_reuse']
        self.assertEqual(reuse, {'configure_count': 1, 'navigation_reads': 1, 'index_reads': 1,
                               'frame_initializations': 1, 'generations': [1, 2, 3],
                               'score_ids': ['old-A', 'old-B', 'old-A']})

    def test_actual_dom_lifecycle_delivery_keyboard_preferences_and_aba(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for the installed jsdom fixture')
        result = subprocess.run([node, '--test', str(FIXTURE / 'client.test.cjs')],
                                cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
