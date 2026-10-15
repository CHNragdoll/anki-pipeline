"""Actual a/an source siblings must not bypass a stale owner binding."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from anki_pipeline import native_example_usage as native, sense_display as sd


FIXTURES = Path(__file__).resolve().parents[1] / (
    'output/exam-usage-policy-20261012/ownership-recovery-v5/native-render-preflight')
ORIGINAL_FIXTURE = FIXTURES / 'actual-an-as-sibling-fixture.json'
DERIVED_FIXTURE = FIXTURES / 'actual-derived-an-as-sibling-fixtures.json'
CONTEXT_FIXTURE = FIXTURES / 'actual-context-an-native-sibling-fixtures.json'


def with_visible_ordinal(test, markup, aliases, ordinal):
    """Change only the original digit slice; every other HTML byte is guarded."""
    tree = native._Offsets(markup, aliases)
    badges = [node for node in tree.root.walk() if 'index-tag' in node.classes]
    test.assertEqual(len(badges), 1)
    badge = badges[0]
    test.assertRegex(markup[badge.opened:badge.closed], r'^\s*[0-9]+\s*$')
    return markup[:badge.opened] + str(ordinal) + markup[badge.closed:]


def assert_visible_ordinals(test, markup, aliases):
    tree = native._Offsets(markup, aliases)
    history = {'sf-original-history-panel', 'sf-ownership-history', 'sf-inline-history',
               'sf-native-ownership-history', 'sf-archived-example', 'sf-archived-native-example'}
    rows = []
    for node in tree.root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes:
            continue
        parent, historical, nested = node.parent, False, False
        while parent is not None:
            historical |= bool(parent.classes & history) or 'data-native-ownership-history' in parent.attrs
            nested |= parent.tag == 'li' and 'example-card' in parent.classes
            parent = parent.parent
        if not historical and not nested:
            rows.append(node)
    for ordinal, row in enumerate(rows, 1):
        badges = []
        for node in row.walk():
            if 'index-tag' not in node.classes:
                continue
            owner = node.parent
            while owner is not None and owner.tag != 'li':
                owner = owner.parent
            if owner is row:
                badges.append(node)
        test.assertEqual(len(badges), 1)
        test.assertEqual(markup[badges[0].opened:badges[0].closed], str(ordinal))


@unittest.skipUnless(ORIGINAL_FIXTURE.exists(), 'Private immutable original sibling fixture is not in this checkout')
class OriginalNativeSiblingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = ORIGINAL_FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != '1c91aaa49f74ff327822d1847f1b75fcd0ee2f9511f3e9d64c863ccf0fcbdd1b':
            raise ValueError('actual immutable sibling fixture differs')
        cls.fixture = json.loads(raw)

    def setUp(self):
        self.row = deepcopy(self.fixture['row'])
        self.as_html, self.an_html = [item['html'] for item in self.fixture['native_examples']]
        self.aliases = self.fixture['aliases']
        self.prepared = {'book_id': 'redbook2027',
            'card_id': 'de641765469727cc93be703fa2b72b2f0344a776ccbca7b3388efcbe19b84259',
            'occurrences': [deepcopy(self.row)]}
        self.prepared['snapshot_id'] = sd._sha(sd._json(self.prepared))

    def update(self, page):
        before = deepcopy(self.prepared)
        result = native.update_native_examples(page, self.prepared, self.prepared, aliases=self.aliases)
        self.assertEqual(self.prepared, before)
        self.assertEqual(native.restore_original(result['page'], result['inverse']), page)
        assert_visible_ordinals(self, result['page'], self.aliases)
        return result

    def test_actual_an_and_as_siblings_bind_only_the_exact_owner_and_invert(self):
        page = '<!--actual source--><ol>' + self.as_html + self.an_html + '</ol><!--unchanged-->'
        result = self.update(page)
        self.assertEqual(result['stats']['native_examples'], 2)
        self.assertEqual(result['stats']['updated_examples'], 1)
        self.assertEqual(result['stats']['unbound_examples'], 1)
        self.assertIn(with_visible_ordinal(self, self.as_html, self.aliases, 1), result['page'])
        self.assertEqual(sd._native_examples(result['page'], self.aliases), sd._native_examples(page, self.aliases))
        pins = result['inverse']['bindings']
        self.assertEqual([pin['targets'][0]['occurrence_id'] for pin in pins], [self.row['occurrence_id']])

    def test_original_history_keeps_its_old_ordinal_while_current_rows_are_contiguous(self):
        history = ('<details class="sf-original-history-panel"><summary>原历史</summary><ol>'
                   + self.as_html + '</ol></details>')
        page = '<ol>' + self.as_html + self.an_html + '</ol>' + history
        result = self.update(page)
        self.assertIn(history, result['page'])
        self.assertIn(with_visible_ordinal(self, self.as_html, self.aliases, 1), result['page'])

    def test_missing_exact_owner_counterpart_remains_rejected(self):
        with self.assertRaises(ValueError):
            self.update('<ol>' + self.as_html + '</ol>')

    def test_default_pinned_anchor_check_remains_strict_without_page_evidence(self):
        original = sd._native_examples(self.as_html, self.aliases)[0]
        with self.assertRaises(ValueError):
            native._view(self.row, original, self.row['display'])

    def test_overlapping_sibling_target_is_not_an_allowed_different_target(self):
        parsed = native._Offsets(self.as_html, self.aliases)
        text = next(node for node in parsed.root.walk() if 'example-text' in node.classes)
        markup = native._source_classes(native._highlight_example(self.row['english'], '', '', [],
            target_ranges=[[108, 111]], preserve_source=True), self.aliases)
        changed = self.as_html[:text.opened] + markup + self.as_html[text.closed:]
        changed = changed.replace('|38,40"', '|108,111"')
        with self.assertRaises(ValueError):
            self.update('<ol>' + changed + self.an_html + '</ol>')

    def test_same_target_stale_hash_and_changed_packed_binding_remain_rejected(self):
        packed = self.row['display']['provenance']['native_jump']['native_jump']
        fields = packed.split('|')
        altered_hash = list(fields)
        altered_hash[3] = ('A' if fields[3][0] != 'A' else 'B') + fields[3][1:]
        altered_packed = list(fields)
        altered_packed[0] = '1' if fields[0] != '1' else '0'
        for changed in (altered_hash, altered_packed):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.update('<ol>' + self.as_html + self.an_html.replace(packed, '|'.join(changed)) + '</ol>')

    def test_nonmatching_native_content_remains_unbound_under_the_existing_view_contract(self):
        # The sibling shortcut must not reject a different completed candidate
        # which would never enter the existing approved-display anchor check.
        for changed in (self.as_html.replace('culture', 'Culture'),
                        self.as_html.replace('然而', '另一个翻译')):
            with self.subTest(changed=changed):
                result = self.update('<ol>' + changed + self.an_html + '</ol>')
                self.assertEqual(result['stats']['updated_examples'], 1)
                self.assertEqual(result['stats']['unbound_examples'], 1)
                self.assertIn(with_visible_ordinal(self, changed, self.aliases, 1), result['page'])

    def test_sibling_jump_range_and_non_range_packed_identity_tampering_remain_rejected(self):
        jump = sd._native_examples(self.as_html, self.aliases)[0]['jump']['native_jump']
        fields = jump.split('|')
        fields[0] = '1' if fields[0] != '1' else '0'
        for changed in (self.as_html.replace('|38,40"', '|39,40"'),
                        self.as_html.replace(jump, '|'.join(fields))):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.update('<ol>' + changed + self.an_html + '</ol>')

    def test_counterpart_content_must_match_the_complete_approved_display(self):
        for changed in (self.an_html.replace('culture', 'Culture'),
                        self.an_html.replace('然而', '伪造')):
            self.assertNotEqual(changed, self.an_html)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.update('<ol>' + self.as_html + changed + '</ol>')

    def test_original_sibling_and_owner_cannot_claim_additional_unpinned_marks(self):
        for original, targets in ((self.as_html, [[38, 40], [42, 43]]),
                                  (self.an_html, [[109, 111], [42, 43]])):
            parsed = native._Offsets(original, self.aliases)
            text = next(node for node in parsed.root.walk() if 'example-text' in node.classes)
            markup = native._source_classes(native._highlight_example(self.row['english'], '', '', [],
                target_ranges=sorted(targets), preserve_source=True), self.aliases)
            changed = original[:text.opened] + markup + original[text.closed:]
            self.assertEqual(sd._native_examples(changed, self.aliases)[0]['target_ranges'], sorted(targets))
            page = ('<ol>' + (changed if original == self.as_html else self.as_html)
                    + (changed if original == self.an_html else self.an_html) + '</ol>')
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                self.update(page)


@unittest.skipUnless(DERIVED_FIXTURE.exists(), 'Private immutable derived sibling fixture is not in this checkout')
class DerivedNativeSiblingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = DERIVED_FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != 'bf1a647396db8a58b9bbca02ee99df5a50c474da740c5c069fe8c1288189ce4a':
            raise ValueError('actual approved derivation fixtures differ')
        cls.fixture = json.loads(raw)

    def update(self, case, page):
        prepared = {'book_id': 'redbook2027', 'card_id': 'actual-derived-an',
            'occurrences': [deepcopy(case['row'])]}
        prepared['snapshot_id'] = sd._sha(sd._json(prepared))
        before = deepcopy(prepared)
        result = native.update_native_examples(page, prepared, prepared, aliases=self.fixture['aliases'])
        self.assertEqual(prepared, before)
        self.assertEqual(native.restore_original(result['page'], result['inverse']), page)
        assert_visible_ordinals(self, result['page'], self.fixture['aliases'])
        return result

    def test_all_ten_actual_approved_completion_and_option_siblings_invert(self):
        for case in self.fixture['cases']:
            with self.subTest(oid=case['row']['occurrence_id'], kind=case['collision']['derivation']):
                page = '<ol>' + case['sibling_html'] + case['owner_html'] + '</ol>'
                result = self.update(case, page)
                self.assertEqual(result['stats']['updated_examples'], 1)
                self.assertIn(with_visible_ordinal(self, case['sibling_html'], self.fixture['aliases'], 1),
                              result['page'])
                self.assertEqual(sd._native_examples(result['page'], self.fixture['aliases']),
                    sd._native_examples(page, self.fixture['aliases']))

    def test_derived_sibling_needs_owner_dom_and_exact_approved_raw_mapping(self):
        # This actual option has different raw and displayed coordinates.
        case = next(c for c in self.fixture['cases'] if not c['collision']['raw_target_equals_display'])
        sibling, owner = case['sibling_html'], case['owner_html']
        with self.assertRaises(ValueError):
            self.update(case, '<ol>' + sibling + '</ol>')
        raw = case['collision']['actual_jump']['target_ranges'][0]
        packed = case['collision']['actual_jump']['native_jump']
        forged = sibling.replace(packed, packed.rsplit('|', 1)[0] + '|' + f'{raw[0]+1},{raw[1]+1}')
        with self.assertRaises(ValueError):
            self.update(case, '<ol>' + forged + owner + '</ol>')
        # Keep the exact jump but remove the approved owner's actual DOM mark.
        node = next(x for x in native._Offsets(owner, self.fixture['aliases']).root.walk()
                    if 'target-word' in x.classes)
        unmarked = owner[:node.start] + owner[node.opened:node.closed] + owner[node.end:]
        with self.assertRaises(ValueError):
            self.update(case, '<ol>' + sibling + unmarked + '</ol>')

    def test_different_completed_candidate_with_the_same_stem_is_not_a_sibling_shortcut(self):
        case = next(c for c in self.fixture['cases'] if 'ZIP disk' in c['approved_display']['english'])
        alternate = case['sibling_html'].replace('possibility', 'probability')
        self.assertNotEqual(alternate, case['sibling_html'])
        page = '<ol>' + alternate + case['sibling_html'] + case['owner_html'] + '</ol>'
        result = self.update(case, page)
        self.assertEqual(result['stats']['updated_examples'], 1)
        self.assertEqual(result['stats']['unbound_examples'], 2)
        self.assertIn(with_visible_ordinal(self, alternate, self.fixture['aliases'], 1), result['page'])
        self.assertIn(with_visible_ordinal(self, case['sibling_html'], self.fixture['aliases'], 2), result['page'])

    def test_nonmatching_completion_still_runs_the_strict_raw_source_hash_guard(self):
        case = next(c for c in self.fixture['cases'] if 'ZIP disk' in c['approved_display']['english'])
        alternate = case['sibling_html'].replace('possibility', 'probability')
        jump = case['sibling_native_example']['jump']['native_jump']
        fields = jump.split('|')
        fields[3] = ('A' if fields[3][0] != 'A' else 'B') + fields[3][1:]
        alternate = alternate.replace(jump, '|'.join(fields))
        with self.assertRaisesRegex(ValueError, 'source hash binding'):
            self.update(case, '<ol>' + alternate + case['owner_html'] + '</ol>')


@unittest.skipUnless(CONTEXT_FIXTURE.exists(), 'Private immutable context sibling fixture is not in this checkout')
class ContextNativeOwnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = CONTEXT_FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != '2c64d5273f4f9a6633490f4d252f0cda49ba32285d12b2c6758d8c0f56b23836':
            raise ValueError('actual context/native-owner fixtures differ')
        cls.fixture = json.loads(raw)

    def update(self, case, page):
        rows = {item['row']['occurrence_id']: deepcopy(item['row']) for item in case['initial_matches']}
        rows[case['occurrence_id']] = deepcopy(case['row'])
        prepared = {'book_id': 'redbook2027', 'card_id': 'actual-context-native-owner',
            'occurrences': list(rows.values())}
        prepared['snapshot_id'] = sd._sha(sd._json(prepared))
        unchanged = deepcopy(prepared)
        result = native.update_native_examples(page, prepared, prepared, aliases=self.fixture['aliases'])
        self.assertEqual(prepared, unchanged)
        self.assertEqual(native.restore_original(result['page'], result['inverse']), page)
        assert_visible_ordinals(self, result['page'], self.fixture['aliases'])
        self.assertEqual(sd._native_examples(result['page'], self.fixture['aliases']),
                         sd._native_examples(page, self.fixture['aliases']))
        return result

    def test_all_seven_actual_stem_marks_stay_in_their_exact_preferred_native_owner(self):
        for case in self.fixture['cases']:
            with self.subTest(oid=case['occurrence_id']):
                owner = case['actual_preferred_native_examples'][0]['html']
                result = self.update(case, '<ol>' + case['current_native_html'] + owner + '</ol>')
                self.assertEqual(result['stats']['updated_examples'], 2)
                current, preferred = result['inverse']['bindings']
                self.assertNotIn(case['occurrence_id'], [r['occurrence_id'] for r in current['targets']])
                self.assertIn(case['occurrence_id'], [r['occurrence_id'] for r in preferred['targets']])

    def test_missing_or_tampered_preferred_owner_never_skips_a_context_mark(self):
        case = self.fixture['cases'][0]
        owner = case['actual_preferred_native_examples'][0]['html']
        jump = case['preferred_display']['provenance']['native_jump']['native_jump']
        fields = jump.split('|'); fields[0] = '1' if fields[0] != '1' else '0'
        marked = next(node for node in native._Offsets(owner, self.fixture['aliases']).root.walk()
                      if 'target-word' in node.classes)
        missing_mark = owner[:marked.start] + owner[marked.opened:marked.closed] + owner[marked.end:]
        for changed in ('', owner.replace(jump, '|'.join(fields)), missing_mark,
                        owner.replace('What might', 'What could')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.update(case, '<ol>' + case['current_native_html'] + changed + '</ol>')

    def test_projected_token_or_reference_tampering_remains_rejected(self):
        case = self.fixture['cases'][0]
        matches = [(item['row']['occurrence_id'], item['row'], deepcopy(item['view']))
                   for item in case['initial_matches']]
        evidence = {case['occurrence_id']: case['row']}
        current = deepcopy(case['context_native'])
        target = case['projected_range']
        current['english'] = current['english'][:target[0]] + 'xx' + current['english'][target[1]:]
        with self.assertRaisesRegex(ValueError, 'exact projected range'):
            native._context_views(matches, evidence, current)
        stale = deepcopy(matches)
        ref = next(ref for ref in stale[0][2]['derivation_payload']['stemSentenceRefs']
                   if ref['sentenceId'] == case['row']['sentence_id'])
        ref['englishHash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'reference binding'):
            native._context_views(stale, evidence, case['context_native'])

    def test_current_physical_owner_missing_its_mark_is_not_a_different_candidate(self):
        case = self.fixture['cases'][0]
        current = deepcopy(case['context_native'])
        current['jump'] = deepcopy(case['preferred_display']['provenance']['native_jump'])
        matches = [(item['row']['occurrence_id'], item['row'], item['view'])
                   for item in case['initial_matches']]
        owner = case['actual_preferred_native_examples'][0]['view']
        index = {sd._json(owner['jump']): [owner]}
        with self.assertRaisesRegex(ValueError, 'exact projected range'):
            native._context_views(matches, {case['occurrence_id']: case['row']}, current,
                native_by_jump=index, approved={case['occurrence_id']: case['preferred_display']})


if __name__ == '__main__':
    unittest.main()
