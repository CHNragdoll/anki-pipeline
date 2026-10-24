"""Both verified author codecs share the audited compact candidate selector."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.study_book_embed_seal import without_consumer_runtime, without_example_module_cohorts

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
        # The accepted compiled path adds an optional numbering capability and
        # diagnostic finally around the same immediate authored execution.
        runtime = m.PREPARED_FRAME_RUNTIME
        self.assertIn('execute(doc,item.code,item.pin,initialNumbering)', runtime)
        self.assertIn("if(execute(doc,item.code,item.pin,initialNumbering)===false){if(!valid())return false;throw Error('Compiled initial numbering owner changed before authored execution')}", runtime)
        self.assertIn('initialNumbering?.after(item.pin);item.node.remove()', runtime)
        execution = runtime.index('execute(doc,item.code,item.pin,initialNumbering)')
        self.assertLess(execution, runtime.index('initialNumbering?.after(item.pin);item.node.remove()', execution))

    def test_reviewed_40_contracts_run_against_common_runtime_and_exact_template(self):
        self.assertEqual(m.digest(TEMPLATE.read_bytes()),
                         '64f9178c2d57a12eb35dc1f2fa5e20f8c939db93eea2cf79d7954b6984fa605a')
        raw = TEMPLATE.read_text()
        helper, _ = json.JSONDecoder().raw_decode(raw.split('const compactClassCandidateHelper=', 1)[1])
        self.assertEqual(m.digest(helper), '7fc5002f0180b47c0b74abcdfd71de372551f8e89184e55860e610ddb599a1ba')
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
        self.assertIn('# tests 40\n', result.stdout)

    def test_v5_runtime_only_replaces_the_exact_reviewed_v3_template(self):
        previous = (FIXTURES / 'previous-adapter-v3.js').read_text()
        self.assertEqual(m.digest(previous),
                         'c7193f98e2b3b5fbe4dab6a230f49d45abbea44f897b5ea0cff9e467db289c2a')
        self.assertEqual(m.PREPARED_FRAME_RUNTIME.count(m.COMPACT_CANDIDATES_ADAPTER), 1)
        inverse = without_consumer_runtime(m.PREPARED_FRAME_RUNTIME).replace(m.COMPACT_CANDIDATES_ADAPTER, previous)
        # Reverse only the subsequent, independently reviewed private Group
        # field removal before checking the pre-v5 compact checkpoint.
        ranges = without_example_module_cohorts(m.GROUP_RANGES_ADAPTER)
        previous_ranges = ranges.replace(
            'return { root: el, nodes: nodes };',
            'return { root: el, text: el.textContent, nodes: nodes };')
        self.assertEqual(m.digest(previous_ranges),
                         '0faa57d85e721a0a3172ac3fa1e8da6431808043d773ee40a473309c1227a9d9')
        self.assertEqual(inverse.count(ranges), 1)
        inverse = inverse.replace(ranges, previous_ranges)
        self.assertEqual(m.digest(inverse),
                         '84198fc2a3569e99d4db02caa93ec15d843e92697ea2b9fbaf1ee41bd254b552')
