"""Ranges omits only Group's private, unconsumed element string."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from anki_pipeline import study_catalog_web_materialize as m

FIXTURES = Path(__file__).parent / 'fixtures'
TEMPLATES = Path(m.__file__).with_name('templates')


@unittest.skipUnless(shutil.which('node'), 'requires Node.js')
class NativeGroupUnusedTextTests(unittest.TestCase):
    def test_actual_ranges_path_runs_six_real_group_contracts_and_exact_inverse(self):
        bridge = (FIXTURES / 'study-native-group-unused-text-inverse.js').read_text()
        self.assertEqual(m.digest(bridge),
                         '972dafc5c324b51d941c5f1c966618b2dbbd61ee5b6aec18cac6c7b4f2ba5a77')
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
                                 str(FIXTURES / 'study-native-group-unused-text.test.cjs')],
                                cwd=tempfile.gettempdir(),
                                env={**os.environ, 'GROUP_UNUSED_TEMPLATES': str(TEMPLATES)},
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 6\n', result.stdout)

    def test_four_real_modules_match_frozen_bridge_and_invert_to_original_pins(self):
        base = Path.home() / 'Library/Application Support/AnkiStudyCatalog/exports/20261015'
        be = 'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'
        v26 = '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e'
        sources = [
            ('master-redbook-web-v1/media/_as_runtime_5c361607267287f859150ac4.js', v26, v26),
            ('master-redbook2027-web-v3/media/_as_runtime_be39224f5f2d47eee8cad800.js', be, be),
            ('master-redbook-web-v3/evidence/_study_prepared_module_7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4.js', '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4', v26),
            ('master-redbook2027-web-v3/evidence/_study_prepared_module_6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633.js', '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633', be),
        ]
        if not all((base / path).is_file() for path, _, _ in sources):
            self.skipTest('sealed original/prepared export fixtures are unavailable')
        before = m.GROUP_RANGES_ADAPTER.replace(
            'return { root: el, nodes: nodes };',
            'return { root: el, text: el.textContent, nodes: nodes };')
        self.assertEqual(m.digest(before),
                         '0faa57d85e721a0a3172ac3fa1e8da6431808043d773ee40a473309c1227a9d9')
        self.assertEqual(m.PREPARED_FRAME_RUNTIME.count(m.GROUP_RANGES_ADAPTER), 1)
        self.assertEqual(m.digest(m.PREPARED_FRAME_RUNTIME.replace(m.GROUP_RANGES_ADAPTER, before)),
                         '352c11a45d6ddca81b02cc2b9bb731aa85dafd2c14b57bd94360ce08ddb679ba')
        code = r'''const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto'),assert=require('node:assert/strict');
const v=JSON.parse(fs.readFileSync(0,'utf8')),current=vm.runInNewContext(v.current+';adaptNativeGroupRanges;'),previous=vm.runInNewContext(v.previous+';adaptNativeGroupRanges;'),bridge=vm.runInNewContext(v.bridge+';adaptNativeGroupUnusedText;'),hash=s=>crypto.createHash('sha256').update(s).digest('hex'),edits=vm.runInNewContext(v.current.split('  var edits = ')[1].split(';\n  if (edits.some')[0]);
for(const row of v.sources){const raw=fs.readFileSync(row.path);assert.equal(hash(raw),row.pin);const source=raw.toString(),next=current(source,row.original);assert.equal(next,bridge(previous(source,row.original),row.original));let inverse=next;for(const [a,b]of edits){assert.equal(inverse.split(b).length,2);inverse=inverse.replace(b,a);}assert.equal(inverse,source);assert.equal(hash(inverse),row.pin);assert.equal(hash(fs.readFileSync(row.path)),row.pin);}console.log(JSON.stringify({inputs:v.sources.length,exact:true}));'''
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps({'current': m.GROUP_RANGES_ADAPTER, 'previous': before,
                                                  'bridge': (FIXTURES / 'study-native-group-unused-text-inverse.js').read_text(),
                                                  'sources': [{'path': str(base / path), 'pin': pin, 'original': original}
                                                              for path, pin, original in sources]}),
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'inputs': 4, 'exact': True})
