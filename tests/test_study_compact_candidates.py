"""Both verified author codecs share the audited compact candidate selector."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from anki_pipeline import study_catalog_web_materialize as m

FIXTURES = Path(__file__).parent / 'fixtures/study-compact-candidates'
TEMPLATE = Path(m.__file__).with_name('templates') / 'authored-compact-candidates-adapter.js'


@unittest.skipUnless(shutil.which('node'), 'requires Node.js')
class CompactCandidateTests(unittest.TestCase):
    def runtime_adapter(self):
        begin = m.PREPARED_FRAME_RUNTIME.index('function adaptAuthoredCompactClassScan(')
        end = m.PREPARED_FRAME_RUNTIME.index('// A source module must reuse', begin)
        return m.PREPARED_FRAME_RUNTIME[begin:end]

    def node(self, code, payload):
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps(payload), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_actual_common_runtime_adapts_both_verified_sources_and_inverses_exactly(self):
        code = r'''const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),adapt=new Function(input.runtime+';return adaptAuthoredCompactClassScan;')(),hash=s=>crypto.createHash('sha256').update(s).digest('hex');
for(const row of input.sources){assert.equal(hash(row.source),row.original_sha256);const next=adapt(row.source,row.original_sha256);assert.equal(hash(next),row.candidate_sha256,'common runtime must use the reviewed candidate for '+row.year);assert.ok(next.includes('compactClassCandidates(document,config.classes)'));assert.equal(adapt(row.source,'unapproved'),row.source);}
console.log(JSON.stringify({sources:input.sources.length,exact:true}));'''
        inputs = []
        for row in json.loads((FIXTURES / 'inverse-check.json').read_text()):
            inputs.append({**row, 'source': (FIXTURES / ('original-' + row['year'] + '.js')).read_text()})
        self.assertEqual(json.loads(self.node(code, {'runtime': self.runtime_adapter(), 'sources': inputs})),
                         {'sources': 2, 'exact': True})
        collection = m.PREPARED_FRAME_RUNTIME.split('const scripts=[];', 1)[1].split('// Source styles', 1)[0]
        self.assertLess(collection.index('code=await resource('),
                        collection.index('code=adaptAuthoredCompactClassScan('))
        self.assertIn('execute(doc,item.code,item.pin);item.node.remove()', m.PREPARED_FRAME_RUNTIME)

    def test_reviewed_33_contracts_run_against_common_runtime_and_exact_template(self):
        self.assertEqual(m.digest(TEMPLATE.read_bytes()),
                         'c7193f98e2b3b5fbe4dab6a230f49d45abbea44f897b5ea0cff9e467db289c2a')
        raw = TEMPLATE.read_text()
        helper, _ = json.JSONDecoder().raw_decode(raw.split('const compactClassCandidateHelper=', 1)[1])
        self.assertEqual(m.digest(helper), '7ecfe9ec048b9833cfc6d9cbc1fec7edf4c51966e6c0181a214643b1f41251f3')
        candidate = self.node("const fs=require('node:fs'),v=JSON.parse(fs.readFileSync(0,'utf8'));const adapt=new Function(v.runtime+';return adaptAuthoredCompactClassScan;')();process.stdout.write(adapt(v.source,v.pin));",
                              {'runtime': self.runtime_adapter(),
                               'source': (FIXTURES / 'original-codec.js').read_text(),
                               'pin': '12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373'})
        with tempfile.TemporaryDirectory(prefix='study-compact-contract-') as folder:
            candidate_path, helper_path = Path(folder) / 'candidate.js', Path(folder) / 'helper.js'
            candidate_path.write_text(candidate)
            helper_path.write_text(helper)
            result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
                                     str(FIXTURES / 'compact.test.cjs'), str(FIXTURES / 'native-format.test.cjs')],
                                    env={**os.environ, 'COMPACT_SOURCE': str(candidate_path),
                                         'COMPACT_HELPER_SOURCE': str(helper_path),
                                         'COMPACT_ADAPTER_SOURCE': str(TEMPLATE)},
                                    text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 33\n', result.stdout)
