"""Two audited native pins share the same exact adapters and resource path."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from anki_pipeline import study_catalog_web_materialize as m

BE = 'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93'
V26 = '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e'
TEMPLATES = Path(m.__file__).with_name('templates')
OLD_PINS = {'native-group-translation-adapter.js': '6b3540a35acd4317cccf04267672e6833ac9889982bd23ed727ec66469340be7',
            'native-group-ranges-adapter.js': '0af6f317e88157d209c53919248a9be231cfa8e18bee66f06f7d0606e9d479fc',
            'projection-task.js': '0c641ed490393963ba9f8156c2126b56fa7099ed96d32b8a8c259bccb6fb7d4a'}


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class NativeCompatibilityTests(unittest.TestCase):
    def test_both_approved_pins_share_exact_shapes_and_original_algorithm_bytes(self):
        fixtures = Path(__file__).with_name('fixtures')
        projection = (fixtures / 'study-projection-lookup-contract.cjs').read_text().split('const fixture=String.raw`', 1)[1].split('`;\nconst pin=', 1)[0]
        source = (projection + '\n' + (fixtures / 'study-native-group-index.js').read_text()
                  + '\n' + (fixtures / 'study-native-ranges.js').read_text()
                  + '\n  async function prepare(data) {\n    if (!data || data.schema !== SCHEMA) return;'
                    '\n        await new Promise(function (resolve) { window.setTimeout(resolve, 0); });'
                    '\n        work = 0; started = window.Date.now();\n  }\n')
        entries = []
        for file, old_pin in OLD_PINS.items():
            text = (TEMPLATES / file).read_text()
            old = ("if(originalPin!=='" + BE + "')return code;" if file == 'projection-task.js'
                   else 'if (originalPin !== "' + BE + '") return code;')
            new = ("if(![\"" + V26 + '\",\"' + BE + '\"].includes(originalPin))return code;' if file == 'projection-task.js'
                   else 'if (!["' + V26 + '","' + BE + '"].includes(originalPin)) return code;')
            legacy = text.replace(new, old)
            # Preserve the prior dual-pin seal by reversing only the later
            # removal of Group's private, unused textView field.
            sealed_legacy = legacy
            if file == 'native-group-ranges-adapter.js':
                self.assertEqual(sealed_legacy.count('return { root: el, nodes: nodes };'), 1)
                sealed_legacy = sealed_legacy.replace(
                    'return { root: el, nodes: nodes };',
                    'return { root: el, text: el.textContent, nodes: nodes };')
            self.assertEqual(hashlib.sha256(sealed_legacy.encode()).hexdigest(), old_pin)
            entries.append({'source': text, 'legacy': legacy})
        code = (fixtures / 'study-native-compatibility.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps({'source': source, 'entries': entries}),
                                cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_saved_raw_and_prepared_resources_use_both_verified_call_paths(self):
        base = Path.home() / 'Library/Application Support/AnkiStudyCatalog/exports/20261015'
        sources = [
            ('master-redbook-web-v3/media/_as_runtime_5c361607267287f859150ac4.js', V26, V26),
            ('master-redbook-web-v3/evidence/_study_prepared_module_7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4.js', '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4', V26),
            ('master-redbook2027-web-v3/media/_as_runtime_be39224f5f2d47eee8cad800.js', BE, BE),
            ('master-redbook2027-web-v3/evidence/_study_prepared_module_6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633.js', '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633', BE)]
        if not all((base / path).is_file() for path, _, _ in sources):
            self.skipTest('sealed original/prepared export fixtures are unavailable')
        runtime = m.PREPARED_FRAME_RUNTIME
        start = runtime.index('function adaptNativeProjectionLookup(')
        end = runtime.index('// A source module must reuse', start)
        begin = runtime.index(' for(const item of scripts){const module=')
        finish = runtime.index('\n win.AnkiSlimDecode', begin)
        helpers = (runtime[start:end] + '\n' + m.PROJECTION_TASK_RUNTIME[m.PROJECTION_TASK_RUNTIME.index('function adaptNativeProjectionTask('):])
        code = (Path(__file__).with_name('fixtures') / 'study-native-compatibility.cjs').read_text()
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps({'actual': True, 'helpers': helpers,
                                'module': runtime[begin:finish], 'sources': [{'path': str(base/path), 'pin': pin, 'original': original} for path, pin, original in sources]}),
                                cwd=tempfile.gettempdir(), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['real_inputs'], 4)
