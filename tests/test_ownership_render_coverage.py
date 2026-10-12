"""A moved history must be visible under its exact current sentence."""
from copy import deepcopy
import unittest

from anki_pipeline import sense_frequency as sf
from anki_pipeline import ownership_history as oh
from anki_pipeline.native_example_usage import update_native_examples
from tests.test_native_example_usage import NativeOwnershipHistoryTests


class OwnershipRenderCoverageTests(unittest.TestCase):
    def fixture(self, native=True):
        old, new, page, documents = NativeOwnershipHistoryTests.history_fixture()
        if not native:
            page = '<ol></ol><footer>原末尾</footer>'
        result = update_native_examples(page, old, new,
            ownership_history_documents=documents, defer_ownership_coverage=True)
        report = sf.report_from_record(new)
        report['ownership_history_documents'] = documents
        rendered = result['page'] + sf.render_report(report)
        return old, new, page, documents, result, rendered

    def test_sf_only_history_is_visible_in_exact_destination_without_native_count(self):
        _, new, page, documents, native, rendered = self.fixture(native=False)
        self.assertEqual(native['page'], page)
        self.assertEqual(native['stats']['native_examples'], 0)
        self.assertEqual(len(native['ownership_coverage']['deferred']), 1)
        proof = oh.validate_rendered_history_coverage(rendered, new, native['ownership_coverage'],
            ownership_history_documents=documents)
        self.assertEqual(proof['expected_histories'], 1)
        self.assertEqual(proof['sf_histories'], 1)
        self.assertEqual(proof['native_histories'], 0)
        self.assertEqual(proof['sf_only_histories'], 1)

    def test_native_and_sf_both_retain_full_history_with_no_deferred_row(self):
        _, new, _, documents, native, rendered = self.fixture()
        self.assertEqual(native['ownership_coverage']['deferred'], {})
        proof = oh.validate_rendered_history_coverage(rendered, new, native['ownership_coverage'],
            ownership_history_documents=documents)
        self.assertEqual(proof['expected_histories'], 1)
        self.assertEqual(proof['sf_histories'], 1)
        self.assertEqual(proof['native_histories'], 1)
        self.assertEqual(proof['sf_only_histories'], 0)
        self.assertIn('完整旧错归解释', rendered)
        self.assertIn('第二段不能截短', rendered)

    def test_missing_sf_history_cannot_be_authorized_by_deferred_pins(self):
        _, new, _, documents, native, _ = self.fixture(native=False)
        with self.assertRaisesRegex(ValueError, 'coverage|sentence|history'):
            oh.validate_rendered_history_coverage(native['page'], new, native['ownership_coverage'],
                ownership_history_documents=documents)

    def test_foreign_or_duplicate_sentence_and_altered_history_marker_fail(self):
        _, new, _, documents, native, rendered = self.fixture(native=False)
        oid = next(iter(native['ownership_coverage']['deferred']))
        for bad in (rendered.replace(oid, 'a' * 64), rendered + rendered,
                    rendered.replace('data-ownership-content-sha256="', 'data-ownership-content-sha256="tamper')):
            with self.subTest(bad=bad[:80]):
                with self.assertRaises(ValueError):
                    oh.validate_rendered_history_coverage(bad, new, native['ownership_coverage'],
                        ownership_history_documents=documents)

    def test_snapshot_and_forged_native_claim_cannot_bypass_actual_dom(self):
        _, new, _, documents, native, rendered = self.fixture(native=False)
        with self.assertRaises(ValueError):
            oh.validate_rendered_history_coverage(rendered.replace(new['snapshot_id'], 'a' * 64),
                new, native['ownership_coverage'], ownership_history_documents=documents)
        bad = deepcopy(native['ownership_coverage'])
        bad['native'], bad['deferred'] = bad['deferred'], {}
        bad.pop('coverage_sha256')
        bad['coverage_sha256'] = sf._sha(sf._json(bad))
        with self.assertRaises(ValueError):
            oh.validate_rendered_history_coverage(rendered, new, bad,
                ownership_history_documents=documents)

    def test_intact_markers_do_not_authorize_shortened_text_or_hidden_archive(self):
        _, new, _, documents, native, rendered = self.fixture(native=False)
        for bad in (rendered.replace('第二段不能截短。', ''),
                    rendered.replace('完整旧错归解释', '截断'),
                    rendered.replace('<article class="sf-example"', '<article hidden class="sf-example"'),
                    '<template>' + rendered + '</template>',
                    rendered.replace('<article class="sf-example"',
                        '<article style="display: none" class="sf-example"')):
            with self.subTest(bad=bad[:100]):
                with self.assertRaises(ValueError):
                    oh.validate_rendered_history_coverage(bad, new, native['ownership_coverage'],
                        ownership_history_documents=documents)

    def test_default_native_only_contract_still_rejects_missing_destination(self):
        old, new, _, documents = NativeOwnershipHistoryTests.history_fixture()
        with self.assertRaisesRegex(ValueError, 'exactly bound native'):
            update_native_examples('<ol></ol>', old, new, ownership_history_documents=documents)

    def test_important_hidden_styles_cannot_satisfy_accessible_sentence_coverage(self):
        _, new, _, documents, native, rendered = self.fixture(native=False)
        for style in ('display:none!important', 'visibility:hidden !important',
                      'content-visibility:hidden!important', 'display:none/**/ !important'):
            bad = rendered.replace('<article class="sf-example"',
                '<article style="' + style + '" class="sf-example"')
            with self.subTest(style=style), self.assertRaisesRegex(ValueError, 'explicitly hidden'):
                oh.validate_rendered_history_coverage(bad, new, native['ownership_coverage'],
                    ownership_history_documents=documents)


if __name__ == '__main__':
    unittest.main()
