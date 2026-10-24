"""Common algorithms keep legacy authored pages and future templates aligned."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.study_book_embed_seal import without_example_module_cohorts, authored_module_loop

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'anki_pipeline' / 'templates'
FIXTURES = ROOT / 'tests' / 'fixtures'


class NativeAlgorithmAdapterTests(unittest.TestCase):
    def run_node(self, sources, *, env=None, expected_tests=None):
        if not shutil.which('node'):
            self.skipTest('Node.js is unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, source in sources.items():
                path = Path(tmp) / name
                path.write_text(source)
                paths.append(str(path))
            result = subprocess.run([shutil.which('node'), '--test', '--test-reporter=tap', *paths],
                                    env={**os.environ, **(env or {})}, cwd=tmp,
                                    text=True, capture_output=True, timeout=60)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('jsdom is unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if expected_tests is not None:
            self.assertIn('# tests ' + str(expected_tests) + '\n', result.stdout)
        return result.stdout

    def test_numbering_reads_before_writes_and_preserves_all_legacy_lifecycle_behavior(self):
        legacy = (ROOT / 'tests' / 'example-numbering.test.cjs').read_text().replace(
            "'anki_pipeline/templates/example-numbering.js'", 'process.env.NUMBERING_SOURCE')
        self.run_node({'legacy.test.cjs': legacy,
                       'read-write.test.cjs': (FIXTURES / 'example-numbering-read-write.test.cjs').read_text()},
                      env={'NUMBERING_SOURCE': str(TEMPLATES / 'example-numbering.js')}, expected_tests=15)

    def test_group_translation_is_clone_equivalent_without_clones_and_has_exact_source_guards(self):
        self.run_node({'translation.test.cjs': (FIXTURES / 'study-native-group-translation.test.cjs').read_text()},
                      env={'NATIVE_SOURCE': str(FIXTURES / 'study-native-group-index.js'),
                           'GROUP_ADAPTER': str(TEMPLATES / 'native-group-translation-adapter.js')}, expected_tests=16)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
    def test_new_exports_and_legacy_scripts_share_one_verified_numbering_template(self):
        from anki_pipeline.packaging import _template
        from anki_pipeline.study_catalog_web import AUDITED_MOUNT_EXTERNAL_SHA256
        from anki_pipeline.study_catalog_web_materialize import (
            PREPARED_FRAME_RUNTIME, PROJECTION_TASK_RUNTIME, NUMBERING_SOURCE, LEGACY_NUMBERING, GROUP_TRANSLATION_ADAPTER,
        )
        self.assertEqual(hashlib.sha256(NUMBERING_SOURCE.encode()).hexdigest(),
                         '00b6bb353c279483c8254c68a1a64a06f33476dd5cedbafd66767a32a5e7d626')
        self.assertEqual(hashlib.sha256(without_example_module_cohorts(GROUP_TRANSLATION_ADAPTER).encode()).hexdigest(),
                         '5cf41bf203bdaaac12804997b1f340bfcaa70a9f5092338db70913df47617fdc')
        self.assertTrue(_template('script.js').endswith(NUMBERING_SOURCE))
        self.assertIn(hashlib.sha256(NUMBERING_SOURCE.encode()).hexdigest(), AUDITED_MOUNT_EXTERNAL_SHA256)
        begin = PREPARED_FRAME_RUNTIME.index('function adaptNativeProjectionLookup(')
        end = PREPARED_FRAME_RUNTIME.index('// A source module must reuse', begin)
        collector_start = PREPARED_FRAME_RUNTIME.index('async function collectAuthoredScripts(')
        collector_end = PREPARED_FRAME_RUNTIME.index('function installCigen(', collector_start)
        module = authored_module_loop(PREPARED_FRAME_RUNTIME)
        fixture = (FIXTURES / 'study-projection-lookup-contract.cjs').read_text()
        projection = fixture.split('const fixture=String.raw`', 1)[1].split('`;\nconst pin=', 1)[0]
        # This composed module includes the real ReadingBank IIFE below. Keep
        # exactly its original digest/cache boundary rather than the lookup
        # contract's duplicate synthetic cache implementation.
        cache_start = projection.index('  var warmHashes=')
        cache_end = projection.index('  var excluded=', cache_start)
        projection = projection[:cache_start] + projection[cache_end:]
        projection += ('\n  async function prepare(data) {\n    if (!data || data.schema !== SCHEMA) return;'
                       '\n        await new Promise(function (resolve) { window.setTimeout(resolve, 0); });'
                       '\n        work = 0; started = window.Date.now();\n  }\n')
        projection += '\n' + (FIXTURES / 'study-reading-bank-runtime.js').read_text()
        projection += '\n' + (FIXTURES / 'study-native-fine-runtime.js').read_text()
        history_start = PREPARED_FRAME_RUNTIME.index('const staticHistoryCohorts=')
        history_end = PREPARED_FRAME_RUNTIME.index('function stageStaticHistory(', history_start)
        # Executable slices preserve the production call sites and source order.
        code = (FIXTURES / 'study-native-algorithm-integration.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], cwd=tempfile.gettempdir(),
                                input=json.dumps({'adapt': PREPARED_FRAME_RUNTIME[begin:end] + '\n' + PROJECTION_TASK_RUNTIME[PROJECTION_TASK_RUNTIME.index('function adaptNativeProjectionTask('):],
                                                  'collector': PREPARED_FRAME_RUNTIME[collector_start:collector_end],
                                                  'module': module,
                                                  'history': PREPARED_FRAME_RUNTIME[history_start:history_end],
                                                  'native': projection + '\n' + (FIXTURES / 'study-native-group-candidates-runtime.js').read_text(),
                                                  'canonical': NUMBERING_SOURCE, 'legacy': LEGACY_NUMBERING['source']}),
                                text=True, capture_output=True, timeout=45)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('jsdom is unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 10)

    def test_current_numbering_guard_and_historical_canonical_execution_stay_distinct(self):
        from anki_pipeline import study_catalog_web_materialize as materialize
        from tests import study_book_embed_seal as seal
        proof = seal._numbering_inverse()
        previous = json.loads(proof['edits'][0]['before'].split('=', 1)[1].rstrip(';\n'))
        self.assertEqual(materialize.digest(previous), proof['before_source_sha256'])
        runtime = materialize.PREPARED_FRAME_RUNTIME
        begin = runtime.index('function adaptCompiledInitialNumbering(')
        end = runtime.index('const compiledNumberingStatuses=', begin)
        execute = next(line for line in runtime.splitlines() if line.startswith('function execute('))
        source = 'const input=' + json.dumps({'adapter': runtime[begin:end], 'execute': execute,
            'canonical': materialize.NUMBERING_SOURCE, 'currentPin': proof['after_source_sha256'],
            'previous': previous, 'previousPin': proof['before_source_sha256'],
            'legacyPin': materialize.LEGACY_NUMBERING['sha256']}) + ';\n' + r'''
const {test}=require('node:test'),assert=require('node:assert/strict');
test('verified current and legacy inputs use the exact canonical guard; previous canonical retains its authored refresh',()=>{
 const adapt=new Function('canonicalExampleNumberingSource',input.adapter+';return adaptCompiledInitialNumbering;')(input.canonical);
 for(const pin of [input.currentPin,input.legacyPin]){
  assert.ok(adapt(input.canonical,pin).includes('compiledInitialNumbering = null'));
  assert.throws(()=>adapt(input.canonical+'\n',pin),/canonical numbering source differs/);
 }
 assert.equal(adapt(input.previous,input.previousPin),input.previous);
 const execute=new Function('canonicalExampleNumberingSource','const current=null;'+input.adapter+input.execute+';return execute;')(input.canonical);
 const written=[],doc={defaultView:{addEventListener(){},removeEventListener(){}},head:{append(node){written.push(node.textContent)}},createElement(){return{remove(){}}}};
 execute(doc,input.previous,input.previousPin,{run(){throw Error('historical source must retain its full refresh')}});
 assert.equal(written.pop(),input.previous);
 let calls=0;execute(doc,input.canonical,input.currentPin,{run(action){calls++;return action(true)}});
 assert.equal(calls,1);assert.ok(written.pop().includes('compiledInitialNumbering = null'));
 assert.throws(()=>execute(doc,input.canonical+'\n',input.currentPin,{run:action=>action(true)}),/canonical numbering source differs/);
 assert.equal(written.length,0);
});
'''
        self.run_node({'numbering-pins.test.cjs': source}, expected_tests=1)

    def test_complete_examples_cohorts_keep_exact_request_and_loop_owner_guards(self):
        from anki_pipeline import study_catalog_web_materialize as materialize
        runtime = materialize.PREPARED_FRAME_RUNTIME
        owner = runtime[runtime.index('function adaptCompiledHistorySlotsOwner('):runtime.index('const compiledAssets=')]
        line = next(line for line in owner.splitlines() if line.startswith('  const edits = '))
        edits = json.loads(line[len('  const edits = '):-1])
        source = 'const input=' + json.dumps({'owner': owner, 'edits': edits}) + ';\n' + r'''
const {test}=require('node:test'),assert=require('node:assert/strict');
test('only exact complete-examples cohorts use the new guarded request shape',()=>{
 const adapt=new Function('adaptCompiledHistorySlots',input.owner+';return adaptCompiledHistorySlotsOwner;')(code=>code);
 const legacy=input.edits.map(edit=>edit.before).join('\n');
 const oldRequest='      if (!alive() || slot.busy || slot.at >= slot.value.parts.length || Date.now() < slot.retryAfter) return slot.busy || Promise.resolve();';
 const request='      if (!alive() || slot.at >= slot.value.parts.length || Date.now() < slot.retryAfter) return slot.busy || Promise.resolve();';
 const busy="      if (slot.busy) return all && slot.kind === 'examples' ? slot.busy.then(function () { return request(slot, true); }) : slot.busy;";
 const oldBreak='            if (!all || !alive() || (slot.detail && !slot.detail.open)) break;';
 const stop="            if (!all || !alive() || (slot.kind !== 'examples' && slot.detail && !slot.detail.open)) break;";
 const complete=legacy.replace(oldRequest,request+'\n'+busy).replace(oldBreak,stop);
 for(const pin of ['b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26','286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67']){
  const changed=adapt(complete,pin);assert.ok(changed.includes(request.replace('!alive()','!ownsWork()')));
  assert.ok(changed.includes(stop.replace('!alive()','!ownsWork()')));assert.ok(changed.includes(busy));
  assert.throws(()=>adapt(legacy,pin),/owner boundary differs/);
  assert.throws(()=>adapt(complete+'\n'+request,pin),/owner boundary differs/);
 }
 for(const pin of ['5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e','be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93']){
  const changed=adapt(legacy,pin);assert.ok(changed.includes(oldRequest.replace('!alive()','!ownsWork()')));
  assert.throws(()=>adapt(complete,pin),/owner boundary differs/);
 }
 assert.equal(adapt(complete,'f'.repeat(64)),complete);
});
'''
        self.run_node({'complete-examples-owner.test.cjs': source}, expected_tests=1)

    @unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
    def test_verified_group_ranges_are_bounded_and_unknown_or_changed_sources_are_preserved(self):
        from anki_pipeline import study_catalog_web_materialize as materialize
        code = (FIXTURES / 'study-native-ranges-integration.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps({'adapter': getattr(materialize, 'GROUP_RANGES_ADAPTER', ''),
                                                  'fixture': (FIXTURES / 'study-native-ranges.js').read_text()}),
                                text=True, capture_output=True, cwd=tempfile.gettempdir(), timeout=20)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('jsdom is unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Exact inverse of the private unused-field removal preserves the old
        # ranges algorithm checkpoint, rather than blindly refreshing its pin.
        self.assertEqual(materialize.GROUP_RANGES_ADAPTER.count(
            'return { root: el, nodes: nodes };'), 1)
        previous = without_example_module_cohorts(materialize.GROUP_RANGES_ADAPTER).replace(
            'return { root: el, nodes: nodes };',
            'return { root: el, text: el.textContent, nodes: nodes };')
        self.assertEqual(hashlib.sha256(previous.encode()).hexdigest(),
                         '0faa57d85e721a0a3172ac3fa1e8da6431808043d773ee40a473309c1227a9d9')
