"""Common algorithms keep legacy authored pages and future templates aligned."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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
                      env={'NUMBERING_SOURCE': str(TEMPLATES / 'example-numbering.js')}, expected_tests=14)

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
                         'd34134c8918205c51c842963c7354f090e6041dcecd00480e695d4e874b8e21d')
        self.assertEqual(hashlib.sha256(GROUP_TRANSLATION_ADAPTER.encode()).hexdigest(),
                         '6b3540a35acd4317cccf04267672e6833ac9889982bd23ed727ec66469340be7')
        self.assertTrue(_template('script.js').endswith(NUMBERING_SOURCE))
        self.assertIn(hashlib.sha256(NUMBERING_SOURCE.encode()).hexdigest(), AUDITED_MOUNT_EXTERNAL_SHA256)
        begin = PREPARED_FRAME_RUNTIME.index('function adaptNativeProjectionLookup(')
        end = PREPARED_FRAME_RUNTIME.index('// A source module must reuse', begin)
        collector_start = PREPARED_FRAME_RUNTIME.index('async function collectAuthoredScripts(')
        collector_end = PREPARED_FRAME_RUNTIME.index('function installCigen(', collector_start)
        module_start = PREPARED_FRAME_RUNTIME.index(' for(const item of scripts){const module=')
        module_end = PREPARED_FRAME_RUNTIME.index('\n win.AnkiSlimDecode', module_start)
        fixture = (FIXTURES / 'study-projection-lookup-contract.cjs').read_text()
        projection = fixture.split('const fixture=String.raw`', 1)[1].split('`;\nconst pin=', 1)[0]
        projection += ('\n  async function prepare(data) {\n    if (!data || data.schema !== SCHEMA) return;'
                       '\n        await new Promise(function (resolve) { window.setTimeout(resolve, 0); });'
                       '\n        work = 0; started = window.Date.now();\n  }\n')
        history_start = PREPARED_FRAME_RUNTIME.index('const staticHistoryCohorts=')
        history_end = PREPARED_FRAME_RUNTIME.index('function stageStaticHistory(', history_start)
        # Executable slices preserve the production call sites and source order.
        code = (FIXTURES / 'study-native-algorithm-integration.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], cwd=tempfile.gettempdir(),
                                input=json.dumps({'adapt': PREPARED_FRAME_RUNTIME[begin:end] + '\n' + PROJECTION_TASK_RUNTIME[PROJECTION_TASK_RUNTIME.index('function adaptNativeProjectionTask('):],
                                                  'collector': PREPARED_FRAME_RUNTIME[collector_start:collector_end],
                                                  'module': PREPARED_FRAME_RUNTIME[module_start:module_end],
                                                  'history': PREPARED_FRAME_RUNTIME[history_start:history_end],
                                                  'native': projection + '\n' + (FIXTURES / 'study-native-group-index.js').read_text(),
                                                  'canonical': NUMBERING_SOURCE, 'legacy': LEGACY_NUMBERING['source']}),
                                text=True, capture_output=True, timeout=45)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('jsdom is unavailable')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['contracts'], 10)
