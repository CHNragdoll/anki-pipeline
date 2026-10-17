import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.study_compiled_build import ArtifactStore
from anki_pipeline.study_compiled_runtime import (
    CURRENT_RUNTIME_SHA256, LEGACY_RUNTIME_SHA256, upgrade_delivery_runtime,
)


class CompatibleRuntimeTests(unittest.TestCase):
    def source(self, parent):
        raw = (Path(__file__).parent / 'fixtures/experimental-compiled-card-v1/history-slots-v1/runtime.js').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), LEGACY_RUNTIME_SHA256)
        name = '_qa_compiled_' + LEGACY_RUNTIME_SHA256 + '.js'
        path = parent / name
        path.write_bytes(raw)
        return {'mode': 'compiled', 'entry': {'html': {'src': 'unchanged.html', 'sha256': '1' * 64},
                    'profile': {'src': 'unchanged.json', 'sha256': '2' * 64}, 'anchors': {'opaque': 'unchanged'}},
                'record': {'src': 'original-record.json', 'sha256': '3' * 64},
                'runtime': {'src': name, 'sha256': LEGACY_RUNTIME_SHA256},
                'resources': {'https://example.test/book/' + name:
                              {'path': str(path), 'sha256': LEGACY_RUNTIME_SHA256, 'bytes': len(raw)}}}

    def test_upgrade_preserves_entry_profile_original_record_and_input(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = self.source(parent); before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], before['entry'])
            self.assertEqual(result['record'], before['record'])
            self.assertEqual(result['runtime']['sha256'], CURRENT_RUNTIME_SHA256)
            self.assertTrue(result['runtime_projection']['body_profile_bytes_unchanged'])
            again = upgrade_delivery_runtime(result, ArtifactStore(parent / 'unused'))
            self.assertEqual(again, result)

    def test_corrupt_original_or_ambiguous_resource_cannot_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = self.source(parent); store = ArtifactStore(parent / 'out')
            descriptor = next(iter(source['resources'].values()))
            source['resources']['https://other.test/alias.js'] = descriptor
            with self.assertRaisesRegex(ValueError, 'one explicit'):
                upgrade_delivery_runtime(source, store)
            del source['resources']['https://other.test/alias.js']
            Path(descriptor['path']).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'resource differs'):
                upgrade_delivery_runtime(source, store)

    def test_unknown_runtime_rejected_authored_content_untouched(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = self.source(parent); store = ArtifactStore(parent / 'out')
            source['runtime']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'unsupported completed'):
                upgrade_delivery_runtime(source, store)
            original = {'mode': 'authored', 'identity': 'original'}
            self.assertEqual(upgrade_delivery_runtime(original, store), original)


if __name__ == '__main__':
    unittest.main()
