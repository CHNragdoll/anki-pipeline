"""Compiled front delivery must stay bound to the complete authored card."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline import study_catalog_web as web


def front_host_fixture(runtime=None):
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def packed(value):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

    files, rules = {}, {}
    for identity in ('A', 'B'):
        first = '<html><head><base href="../media/"></head><body>完整正面 ' + identity + ' α 🧪</body></html>'
        back = first.replace('完整正面', '完整背面及审核依据')
        sides = [first, back]
        literal = json.dumps(sides, ensure_ascii=False)
        wrapper = web.card_shell(literal, '../media/')
        prepared_sides = [{'html': side, 'registry': {}, 'children': [],
                           'proof': {'source_sha256': digest(side), 'expanded_sha256': digest(side),
                                     'original_source_unmodified': True}} for side in sides]
        full = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': digest(wrapper),
                'source_payload_sha256': digest(literal), 'sides': prepared_sides, 'modules': {}}
        full_text = packed(full)
        front = {'schema': 'study-prepared-front.v1', 'card_id': identity,
                 'wrapper_url': 'cards/' + identity + '.html', 'base_href': '../media/',
                 'source_wrapper_sha256': digest(wrapper), 'source_payload_sha256': digest(literal),
                 'source_front_sha256': digest(first), 'full_prepared_sha256': digest(full_text),
                 'source_front': first, 'side': prepared_sides[0], 'modules': {}}
        front_text = packed(front)
        rules[identity] = {'src': 'full-' + identity + '.json', 'sha256': digest(full_text),
                           'front': {'src': 'front-' + identity + '.json', 'sha256': digest(front_text)}}
        files.update({'cards/' + identity + '.html': wrapper, 'full-' + identity + '.json': full_text,
                      'front-' + identity + '.json': front_text})
    index = packed({'schema': 'study-prepared-index.v1', 'cards': rules})
    files['prepared-index.json'] = index
    config = {'html': '<html><body>fixture frame API</body></html>',
              'policy': {'external': {}, 'inline': []},
              'preparedIndex': {'src': 'prepared-index.json', 'sha256': digest(index)}}
    navigation = {'schema': 'study-navigation.v2', 'units': ['通用书籍::单元1'],
                  'cards': [[identity, identity, identity, 0, 'cards/' + identity + '.html',
                             '释义', 1, True] for identity in ('A', 'B')],
                  'totals': {'groups': 1, 'examples': 2}}
    return {'runtime': runtime or web.HOST_RUNTIME,
            'page': web.library_html('通用学科测试', total=2, shared_frame=config),
            'files': files, 'navigation': navigation}


@unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
class FrontHostTests(unittest.TestCase):
    def test_front_precedes_blocked_full_and_cancelled_generations_never_attach(self):
        code = (Path(__file__).parent / 'fixtures/study-front-host-contract.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps(front_host_fixture()), text=True,
                                capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(json.loads(result.stdout)['contracts'], 12)


if __name__ == '__main__':
    unittest.main()
