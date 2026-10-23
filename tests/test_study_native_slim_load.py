"""Real Slim loader keeps all pin/cache/lifecycle rules with a private verifier."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from anki_pipeline import study_catalog_web_materialize as m
from tests.study_book_embed_seal import without_example_module_cohorts, authored_module_loop

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'
TEMPLATES = ROOT / 'anki_pipeline' / 'templates'
BE = 'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'
V26 = '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e'


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class NativeSlimLoadTests(unittest.TestCase):
    def test_source_loop_captures_only_after_verified_resource_and_valid_owner(self):
        self.assertIn('withSlimLoadChecker(win,enabled=>execute(', m.PREPARED_FRAME_RUNTIME)
        self.assertEqual(m.digest(without_example_module_cohorts(m.SLIM_LOAD_CHECKER_ADAPTER)),
                         'a700665eebdfb78e2eb7f5ef2de4efb372e079ac0800cfe895147b9b3abd89eb')
        self.assertEqual(m.digest(m.SLIM_LOAD_CHECKER_BRIDGE),
                         '954599732b93730c3b637ac37ad89117fc8d215f2611947c2343b7f656b8abd6')
        env = {**os.environ, 'SLIM_LOAD_TEMPLATES': str(TEMPLATES),
               'SLIM_LOAD_SOURCE': str(FIXTURES / 'study-native-slim-load-runtime.js'),
               'SLIM_LOAD_MODULE_LOOP': authored_module_loop(m.PREPARED_FRAME_RUNTIME)}
        result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap',
                                 str(FIXTURES / 'study-native-slim-load.test.cjs')],
                                cwd=tempfile.gettempdir(), env=env, text=True, capture_output=True, timeout=40)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# tests 15\n', result.stdout)

    def test_full_raw_and_prepared_pins_invert_exactly_without_other_source_changes(self):
        base = Path.home() / 'Library/Application Support/AnkiStudyCatalog/exports/20261015'
        sources = [
            ('master-redbook-web-v3/media/_as_runtime_5c361607267287f859150ac4.js', V26, V26),
            ('master-redbook-web-v3/evidence/_study_prepared_module_7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4.js', '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4', V26),
            ('master-redbook2027-web-v3/media/_as_runtime_be39224f5f2d47eee8cad800.js', BE, BE),
            ('master-redbook2027-web-v3/evidence/_study_prepared_module_6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633.js', '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633', BE)]
        if not all((base / path).is_file() for path, _, _ in sources):
            self.skipTest('sealed original/prepared export fixtures are unavailable')
        for path, pin, _ in sources:
            self.assertEqual(hashlib.sha256((base / path).read_bytes()).hexdigest(), pin)
        code = r'''const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),adapt=vm.runInNewContext(input.adapter+';adaptNativeSlimLoadChecker;'),hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const edits=vm.runInNewContext(input.adapter.split('  const edits = ')[1].split(';\n  if (edits.some')[0]);
for(const item of input.sources){const raw=fs.readFileSync(item.path);assert.equal(hash(raw),item.pin);const source=raw.toString(),result=adapt(source,item.original);let inverse=result;
for(const [before,after]of edits){assert.equal(source.split(before).length,2);assert.equal(inverse.split(after).length,2);inverse=inverse.replace(after,before);}assert.equal(inverse,source);assert.equal(hash(fs.readFileSync(item.path)),item.pin);}console.log(JSON.stringify({inputs:input.sources.length,exact:true}));'''
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps({'adapter': m.SLIM_LOAD_CHECKER_ADAPTER,
                                                  'sources': [{'path': str(base/path), 'pin': pin, 'original': original}
                                                              for path, pin, original in sources]}),
                                cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'inputs': 4, 'exact': True})
