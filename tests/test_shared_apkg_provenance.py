import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import build_shared_apkg as producer


class SharedProvenanceTest(unittest.TestCase):
    def test_report_drift_does_not_inherit_a_new_unprepared_semantic_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'2027').mkdir()
            report=root/'2027/build-report.json';report.write_text('original verified report')
            source=root/'sealed.apkg'
            prepared={'storage_source':str(source),'storage_source_sha256':producer.SOURCE_SHA['2027'],
                      'inherited_v1_inverse_report_sha256':hashlib.sha256(report.read_bytes()).hexdigest()}
            with patch.object(producer,'INPUT',root):
                producer.check_prepare_provenance('2027',prepared,source)
                report.write_text('changed evidence')
                with self.assertRaisesRegex(ValueError,'report changed'):
                    producer.check_prepare_provenance('2027',prepared,source)

    def test_wrong_prepared_package_is_rejected(self):
        prepared={'storage_source':'different.apkg','storage_source_sha256':producer.SOURCE_SHA['2027'],
                  'inherited_v1_inverse_report_sha256':'unused'}
        with self.assertRaisesRegex(ValueError,'storage source changed'):
            producer.check_prepare_provenance('2027',prepared,Path('sealed.apkg'))


if __name__=='__main__':unittest.main()
