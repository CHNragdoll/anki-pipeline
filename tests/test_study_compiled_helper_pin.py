"""A current producer helper requires an exact pin, including the full build."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from anki_pipeline import study_compiled as inputs
from anki_pipeline.study_compiled_schedule import StageSeparatedBuild


class HelperPinTests(unittest.TestCase):
    def test_current_helper_bytes_have_the_explicit_reviewed_pin(self):
        self.assertEqual(hashlib.sha256(inputs._HELPERS.read_bytes()).hexdigest(),
                         inputs._HELPERS_SHA256)
        self.assertEqual(inputs._read(inputs._HELPERS, inputs._HELPERS_SHA256),
                         inputs._HELPERS.read_bytes())

    def test_one_changed_helper_byte_is_rejected(self):
        raw = inputs._HELPERS.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'semantic-helpers.js'
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            with self.assertRaisesRegex(ValueError, 'source bytes differ from the explicit pin'):
                inputs._read(path, inputs._HELPERS_SHA256)

    @unittest.skipUnless(os.environ.get('ANKI_STUDY_COMPILED_ACTUAL_SAMPLE') and shutil.which('node'),
                         'requires a pinned read-only actual small prepared export and Node')
    def test_actual_small_protected_card_runs_full_semantic_profile_publish(self):
        sample = json.loads(Path(os.environ['ANKI_STUDY_COMPILED_ACTUAL_SAMPLE']).read_bytes())
        with tempfile.TemporaryDirectory() as folder:
            with StageSeparatedBuild(Path(folder) / 'build') as builder:
                result = builder.build(sample['root'], sample['wrapper'], sample['artifact'],
                    identity=sample['identity'], policy=sample['policy'], source_url=sample['source_url'])
                self.assertEqual(result['mode'], 'compiled')
                self.assertEqual(result['identity'], sample['identity'])
                self.assertEqual(builder.worker_count, 2)
                builder._verify_cached_result(result)
                record = json.loads((builder.store.assets / result['record']['src']).read_bytes())
                bindings = record['entry']['anchors']['bindings']
                self.assertEqual(bindings['sourceWrapperSha256'], sample['wrapper']['sha256'])
                self.assertEqual(bindings['sourceArtifactSha256'], sample['artifact']['sha256'])


if __name__ == '__main__':
    unittest.main()
