"""Source gzip is only a transport; the complete authored proof stays mandatory."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline import study_catalog_web as web


@unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
class WrapperGzipHostTests(unittest.TestCase):
    def test_verified_source_gzip_transport_preserves_full_checks_and_bounded_cancellation(self):
        source = '<html><head><base href="../media/"></head><body>完整原文 α 🧪</body></html>'
        sides = [source, source.replace('完整原文', '完整背面及审核')]
        literal = json.dumps(sides, ensure_ascii=False)
        wrapper = web.card_shell(literal, '../media/')
        digest = lambda text: hashlib.sha256(text.encode()).hexdigest()
        full = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': digest(wrapper),
                'source_payload_sha256': digest(literal), 'sides': [{'proof': {}}] * 2, 'modules': {}}
        full_text = json.dumps(full, ensure_ascii=False, separators=(',', ':'))
        rule = {'src': 'full.json', 'sha256': digest(full_text)}
        index = json.dumps({'schema': 'study-prepared-index.v1', 'cards': {'A': rule}}, separators=(',', ':'))
        begin = web.HOST_RUNTIME.index('function cacheCard(')
        end = web.HOST_RUNTIME.index('\nfunction prefetchCard(', begin)
        self.assertTrue('async function authoredWrapperText(' in web.HOST_RUNTIME[begin:end],
                        'the full source fetch still bypasses the verified gzip transport')
        fixture = (Path(__file__).parent / 'fixtures/study-wrapper-gzip-host-contract.cjs').read_text()
        value = {'parsers': web.HOST_RUNTIME[web.HOST_RUNTIME.index('function readAuthoredCard('):
                                           web.HOST_RUNTIME.index('let sharedReady=')],
                 'delivery': web.HOST_RUNTIME[begin:end], 'sides': sides, 'wrapper': wrapper,
                 'full': full, 'fullText': full_text, 'rule': rule, 'index': index,
                 'config': {'sharedFrame': {'wrapperDelivery': 'source-gzip.v1',
                                            'preparedIndex': {'src': 'prepared-index.json', 'sha256': digest(index)}}}}
        result = subprocess.run([shutil.which('node'), '-e', fixture], input=json.dumps(value),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 15)
