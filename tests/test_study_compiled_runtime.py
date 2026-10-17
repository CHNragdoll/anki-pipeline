import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.study_compiled_build import ArtifactStore
from anki_pipeline.study_compiled_runtime import (
    CURRENT_RUNTIME_SHA256, LEGACY_RUNTIME_SHA256, PREVIOUS_RUNTIME_SHA256,
    SUPPLEMENTAL_RUNTIME_SHA256, TEXT_SPLIT_RUNTIME_SHA256, INITIAL_HISTORY_RUNTIME_SHA256,
    SHARED_HISTORY_RUNTIME_SHA256, ARCHIVED_FILTER_RUNTIME_SHA256, upgrade_delivery_runtime,
)


class CompatibleRuntimeTests(unittest.TestCase):
    def source(self, parent, previous=False, supplemental=False, text_split=False, initial=False, shared=False, archived_filter=False):
        filename = ('archived-filter-runtime.js' if archived_filter else
                    'shared-history-runtime.js' if shared else
                    'initial-history-runtime.js' if initial else
                    'text-split-history-runtime.js' if text_split else
                    'supplemental-history-runtime.js' if supplemental else
                    'previous-owner-runtime.js' if previous else 'runtime.js')
        pin = (ARCHIVED_FILTER_RUNTIME_SHA256 if archived_filter else
               SHARED_HISTORY_RUNTIME_SHA256 if shared else
               INITIAL_HISTORY_RUNTIME_SHA256 if initial else
               TEXT_SPLIT_RUNTIME_SHA256 if text_split else
               SUPPLEMENTAL_RUNTIME_SHA256 if supplemental else
               PREVIOUS_RUNTIME_SHA256 if previous else LEGACY_RUNTIME_SHA256)
        raw = (Path(__file__).parent / 'fixtures/experimental-compiled-card-v1/history-slots-v1' / filename).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), pin)
        name = '_qa_compiled_' + pin + '.js'
        path = parent / name
        path.write_bytes(raw)
        return {'mode': 'compiled', 'entry': {'html': {'src': 'unchanged.html', 'sha256': '1' * 64},
                    'profile': {'src': 'unchanged.json', 'sha256': '2' * 64}, 'anchors': {'opaque': 'unchanged'}},
                'record': {'src': 'original-record.json', 'sha256': '3' * 64},
                'runtime': {'src': name, 'sha256': pin},
                'resources': {'https://example.test/book/' + name:
                              {'path': str(path), 'sha256': pin, 'bytes': len(raw)}}}

    def test_previous_binder_and_existing_projection_keep_the_original_build_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = self.source(parent, previous=True)
            direct = upgrade_delivery_runtime(source, ArtifactStore(parent / 'direct'))
            self.assertEqual(direct['runtime_projection']['from_sha256'], PREVIOUS_RUNTIME_SHA256)
            source['runtime_projection'] = {'schema': 'study-compatible-binder-projection.v1',
                'source_build_record': source['record'], 'from_sha256': LEGACY_RUNTIME_SHA256,
                'to_sha256': PREVIOUS_RUNTIME_SHA256, 'html': source['entry']['html'],
                'profile': source['entry']['profile'], 'body_profile_bytes_unchanged': True}
            upgraded = upgrade_delivery_runtime(source, ArtifactStore(parent / 'upgraded'))
            self.assertEqual(upgraded['runtime_projection']['from_sha256'], LEGACY_RUNTIME_SHA256)
            self.assertEqual(upgraded['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)
            self.assertEqual(upgraded['entry'], source['entry'])
            source['runtime_projection']['to_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'projection differs'):
                upgrade_delivery_runtime(source, ArtifactStore(parent / 'bad'))

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

    def test_supplemental_binder_upgrades_without_rebuilding_its_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder); source = self.source(parent, supplemental=True)
            before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], before['entry'])
            self.assertEqual(result['record'], before['record'])
            self.assertEqual(result['runtime_projection']['from_sha256'], SUPPLEMENTAL_RUNTIME_SHA256)
            self.assertEqual(result['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)

    def test_text_split_binder_keeps_prior_body_profile_and_record(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            source = self.source(parent, text_split=True)
            before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], source['entry'])
            self.assertEqual(result['record'], source['record'])
            self.assertEqual(result['runtime_projection']['from_sha256'], TEXT_SPLIT_RUNTIME_SHA256)
            self.assertEqual(result['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)

    def test_initial_history_binder_upgrade_keeps_record_and_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            source = self.source(parent, initial=True)
            before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], before['entry'])
            self.assertEqual(result['record'], before['record'])
            self.assertEqual(result['runtime_projection']['from_sha256'], INITIAL_HISTORY_RUNTIME_SHA256)

    def test_shared_history_binder_upgrade_keeps_complete_bank_body_and_record(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            source = self.source(parent, shared=True)
            before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], before['entry'])
            self.assertEqual(result['record'], before['record'])
            self.assertEqual(result['runtime_projection']['from_sha256'], SHARED_HISTORY_RUNTIME_SHA256)
            self.assertEqual(result['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)

    def test_archived_filter_upgrade_preserves_body_profile_record_and_input(self):
        with tempfile.TemporaryDirectory() as folder:
            parent = Path(folder)
            source = self.source(parent, archived_filter=True)
            before = copy.deepcopy(source)
            result = upgrade_delivery_runtime(source, ArtifactStore(parent / 'out'))
            self.assertEqual(source, before)
            self.assertEqual(result['entry'], before['entry'])
            self.assertEqual(result['record'], before['record'])
            self.assertEqual(result['runtime_projection']['from_sha256'], ARCHIVED_FILTER_RUNTIME_SHA256)
            self.assertEqual(result['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)

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
