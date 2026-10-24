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

    def without_canonical_numbering_admission(self, value):
        # f1d3aa9 admits the already-pinned canonical numbering source. Invert
        # those exact producer edits before the older module-cohort seal.
        previous = '91d665d9a6145895f4e9d1c31206b1ba916fc419f92ce15abeb453b56d98dac3'
        current = '4e85b5a111a9f9cd7c773cf8f1823718494be1ed325c402ae79bc4b63d652bc3'
        pin = materialize.digest(value)
        self.assertIn(pin, (previous, current), 'numbering producer source differs')
        if pin == previous:
            return value
        edits = (
            ("const NUMBERING_PIN = '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1';",
             "const { NUMBERING_PINS } = require('./numbering-preparation.cjs');"),
            ('.filter(name => name && request.policy.external[name] === NUMBERING_PIN)',
             '.filter(name => name && NUMBERING_PINS.includes(request.policy.external[name]))'),
            ("      const name = Array.from(numberingSources)[0], sourceCode = await resource(new URL(name, request.base_url).href, NUMBERING_PIN);",
             "      const name = Array.from(numberingSources)[0], sourcePin = request.policy.external[name];\n      const sourceCode = await resource(new URL(name, request.base_url).href, sourcePin);"),
            ("      demand(hash(sourceCode) === NUMBERING_PIN, 'Original numbering source SHA differs');",
             "      demand(hash(sourceCode) === sourcePin, 'Original numbering source SHA differs');"),
            ('const options = {sourceCode, sourcePin: NUMBERING_PIN, styleSources: styles.sources};',
             'const options = {sourceCode, sourcePin, styleSources: styles.sources};'),
            ("schema: 'study-semantic-initial-numbering.v1', source_sha256: NUMBERING_PIN,",
             "schema: 'study-semantic-initial-numbering.v1', source_sha256: sourcePin,"),
        )
        for before, after in reversed(edits):
            self.assertEqual(value.count(after), 1, 'numbering producer inverse boundary differs')
            value = value.replace(after, before, 1)
        self.assertEqual(materialize.digest(value), previous, 'nonnumbering producer code changed')
        return value

    def test_canonical_numbering_admission_keeps_the_fixed_previous_producer(self):
        path = Path(__file__).resolve().parents[1]/'anki_pipeline/compiled/semantic-producer.cjs'
        current = path.read_text()
        previous = self.without_canonical_numbering_admission(current)
        self.assertEqual(self.without_canonical_numbering_admission(previous), previous)
        for changed in (current+'\n', current.replace('NUMBERING_PINS', 'NUMBERING_OTHER', 1)):
            with self.subTest(pin=materialize.digest(changed)), self.assertRaisesRegex(AssertionError, 'source differs'):
                self.without_canonical_numbering_admission(changed)

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
                if row['name'] == 'anki_pipeline/compiled/semantic-producer.cjs':
                    value = self.without_canonical_numbering_admission(value)
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
