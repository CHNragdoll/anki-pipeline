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
        consumer = materialize.PREPARED_FRAME_RUNTIME
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


if __name__ == '__main__':
    unittest.main()
