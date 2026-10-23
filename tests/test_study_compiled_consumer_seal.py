"""Fixed historical inverse admission; never derive a baseline from live edits."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_web_materialize as materialize
from tests import study_book_embed_seal as seal


class StudyCompiledConsumerSealTests(unittest.TestCase):
    def test_exact_compiled_and_existing_consumer_return_the_same_historical_runtime(self):
        raw = (Path(__file__).parent/'fixtures/study-compiled-consumer-inverse.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), seal._COMPILED_FIXTURE_SHA256)
        proof = json.loads(raw)
        consumer = seal.without_section_numbering(materialize.PREPARED_FRAME_RUNTIME)
        for edit in reversed(proof['edits']):
            self.assertEqual(consumer.count(edit['after']), 1)
            consumer = consumer.replace(edit['after'], edit['before'], 1)
        self.assertEqual(hashlib.sha256(consumer.encode()).hexdigest(), seal._COMMITTED_READY_SHA256)
        expected = seal.without_consumer_runtime(consumer)
        self.assertEqual(seal.without_consumer_runtime(materialize.PREPARED_FRAME_RUNTIME), expected)
        self.assertEqual(hashlib.sha256(expected.encode()).hexdigest(), seal._BASELINE_SHA256)

    def test_changed_runtime_never_acquires_the_frozen_inverse(self):
        for changed in (materialize.PREPARED_FRAME_RUNTIME+'\n',
                        materialize.PREPARED_FRAME_RUNTIME.replace('10000', '10001', 1)):
            with self.subTest(pin=materialize.digest(changed)), self.assertRaises(AssertionError):
                seal.without_consumer_runtime(changed)

    def test_only_the_exact_default_html_removes_the_empty_configuration(self):
        runtime = materialize.PREPARED_FRAME_RUNTIME
        html = materialize.prepared_frame_html()
        restored = seal.without_consumer_frame_html(html, runtime)
        self.assertEqual(materialize.digest(restored),
                         '8b6e59ff2457dc7cd2cfefbe46d81404dc55ce8c2dd941b040a7ac5ac9de1710')
        self.assertNotIn('id="study-compiled-assets"', restored)
        alternatives = [html+'\n', html.replace('{"entries":{}}', '{"entries":{ }}', 1),
                        materialize.prepared_frame_html({'entries': {}, 'runtime': {}})]
        for alternative in alternatives:
            with self.subTest(pin=materialize.digest(alternative)), self.assertRaises(AssertionError):
                seal.without_consumer_frame_html(alternative, runtime)

    def test_changed_inverse_fixture_pin_is_rejected_before_any_edits(self):
        with patch.object(seal, '_COMPILED_FIXTURE_SHA256', '0'*64), self.assertRaisesRegex(AssertionError, 'evidence'):
            seal.without_consumer_runtime(materialize.PREPARED_FRAME_RUNTIME)

    def test_section_numbering_inverse_preserves_historical_admission_and_rejects_unpinned_changes(self):
        current = materialize.PREPARED_FRAME_RUNTIME
        previous = seal.without_section_numbering(current)
        self.assertEqual(materialize.digest(previous), seal._COMPILED_SHA256)
        self.assertEqual(seal.without_section_numbering(previous), previous)
        self.assertEqual(seal.without_consumer_runtime(previous), seal.without_consumer_runtime(current))
        with self.assertRaisesRegex(AssertionError, 'runtime differs'):
            seal.without_section_numbering(current+'\n')
        with patch.object(seal, '_NUMBERING_FIXTURE_SHA256', '0'*64), self.assertRaisesRegex(AssertionError, 'evidence'):
            seal.without_section_numbering(current)

    def test_module_cohort_admissions_inverse_exactly_without_refreshing_any_prior_checkpoint(self):
        ready = materialize.PREPARED_FRAME_RUNTIME
        for before, after in reversed(materialize._COMPILED_FRAME_PATCHES):
            self.assertEqual(ready.count(after), 1)
            ready = ready.replace(after, before, 1)
        values = {'authored': materialize.AUTHORED_ALGORITHM_RUNTIME,
                  'projection': materialize.PROJECTION_TASK_RUNTIME,
                  'compiled': materialize.PREPARED_FRAME_RUNTIME,
                  'delivery': materialize.COMPILED_DELIVERY_FRAME_RUNTIME, 'ready': ready}
        for row in seal._module_cohort_inverse()['variants']:
            with self.subTest(source=row['name']):
                value = values.get(row['name'])
                if value is None:
                    value = (Path(__file__).resolve().parents[1] / row['name']).read_text()
                self.assertEqual(materialize.digest(value), row['after_sha256'])
                previous = seal.without_example_module_cohorts(value)
                self.assertEqual(materialize.digest(previous), row['before_sha256'])
                self.assertEqual(seal.without_example_module_cohorts(previous), previous)
        with self.assertRaisesRegex(AssertionError, 'source differs'):
            seal.without_example_module_cohorts(materialize.PREPARED_FRAME_RUNTIME+'\n')
        with patch.object(seal, '_MODULE_COHORT_FIXTURE_SHA256', '0'*64), self.assertRaisesRegex(AssertionError, 'evidence'):
            seal.without_example_module_cohorts(materialize.PREPARED_FRAME_RUNTIME)


if __name__ == '__main__':
    unittest.main()
