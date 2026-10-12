"""A preview frequency repair must remain bound to reread original sources."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_display as sd
from anki_pipeline import sense_frequency as sf
from anki_pipeline import sense_frequency_reconcile as reconcile
from anki_pipeline.exam_frequency import frequency_for_matches
from anki_pipeline.packaging import _exam_frequency_markup


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def source(row):
    """A complete original approved reading sentence, before display transforms."""
    return {'id': row['sentence_id'], 'english': row['english'],
        'englishHash': row['english_hash'], 'translationZh': row['translation'],
        'reviewedContentHash': row['source_provenance']['reviewedContentHash'],
        'paperId': row['paper_id'], 'paragraphId': row['sentence_id'].rsplit(':', 1)[0],
        'sourceHash': row['english_hash'], 'start': 0, 'end': len(row['english']),
        'sourceEnglish': row['english'], 'sourceBlockIds': [row['paper_id'] + ':b-first'],
        'sourceFragments': [], 'sourceSentenceRefs': [], 'kind': 'reading', 'context': {}}


class FrequencyReconciliationTests(unittest.TestCase):
    def compound_candidate_fixture(self, directory, *, uppercase='A-G', edition='redbook2027'):
        from tests.test_sense_candidate_scope import candidate_fixture, supplement_fixture
        record, page, sources, audit_path, digest = candidate_fixture(directory)
        inventory_path = Path(directory) / 'full-inventory-v2/records.jsonl'
        raw = json.loads(inventory_path.read_text())
        replacements = ((0, 'Curiously, some two-and-a-half years later.', 'a'),
                        (2, 'Choose from the list ' + uppercase + '.', 'A'))
        for index, english, target in replacements:
            start = english.index('-a-') + 1 if index == 0 else english.index(uppercase)
            for value in (record, raw):
                row = value['occurrences'][index]
                row.update(english=english, english_hash=sha(english), target_range=[start, start + len(target)])
                if row['status'] == 'reviewed':
                    row['reason'] = 'two and a half 的 a 表示一个半份'
                    value['occurrences'][index] = sf.seal_reviewed_assignment(value, row)
            sources['sentences'][record['occurrences'][index]['sentence_id']] = source(record['occurrences'][index])
        data = reconcile._json(raw) + '\n'
        inventory_path.write_text(data)
        audit = json.loads(audit_path.read_text())
        audit['source_snapshot']['inventory_record_sha256'] = sha(data)
        audit['source_snapshot']['inventory_record_byte_locator']['byte_length'] = len(data.encode())
        for row in raw['occurrences']:
            audit['context_proofs'][row['sentence_id']]['raw_source_english'] = row['english']
        text = json.dumps(audit, ensure_ascii=False, sort_keys=True) + '\n'
        audit_path.write_text(text)
        options = {'audit_path': audit_path, 'expected_audit_sha256': sha(text)}
        if edition == 'redbook':
            record, page, primary_sha, supplement, supplement_sha = supplement_fixture(
                directory, record, page, audit_path)
            options.update(expected_audit_sha256=primary_sha, supplement_path=supplement,
                           expected_supplement_sha256=supplement_sha)
            row = record['occurrences'][3]
            row.update(status='reviewed', sense_index=0, reason='two and a half 的 a 表示一个半份')
            record['occurrences'][3] = sf.seal_reviewed_assignment(record, row)
        return record, page, sources, options

    def test_scope_accepts_reviewed_complete_hyphen_component_and_keeps_unmatched_letter_candidates(self):
        from anki_pipeline import sense_candidate_scope as cs
        for edition in ('redbook', 'redbook2027'):
            for uppercase in ('A-G', 'A-H', 'A-grade'):
                with self.subTest(edition=edition, uppercase=uppercase), tempfile.TemporaryDirectory() as directory:
                    record, page, sources, options = self.compound_candidate_fixture(
                        directory, uppercase=uppercase, edition=edition)
                    checked, capability = self.verified(record, page, sources)
                    filtered, scopes = cs.apply_candidate_scope([checked], {record['card_id']: page}, {},
                                                              verified_sources=capability, **options)
                    candidate = filtered[0]
                    before = deepcopy(candidate)
                    plan = reconcile.plan_frequency_panel(page, candidate, {},
                        verified_sources=scopes.verified_sources, candidate_scope=scopes.for_record(candidate))
                    self.assertEqual(candidate, before)
                    self.assertEqual(candidate['expected_occurrences'], 2 if edition == 'redbook' else 3)
                    reviewed = next(row for row in candidate['occurrences'] if '-a-' in row['english'])
                    self.assertEqual(reviewed['status'], 'reviewed')
                    self.assertIn('assignment_context_hash', reviewed)
                    unresolved = next(row for row in candidate['occurrences'] if uppercase in row['english'])
                    self.assertEqual(unresolved['status'], 'unmatched')
                    self.assertIsNone(unresolved['sense_index'])
                    evidence = plan.verification()['source_evidence']
                    self.assertEqual(len(evidence['component_target_boundaries']), 2)
                    self.assertIsNone(evidence['certified_article_total'])
                    revised = reconcile.apply_frequency_panel(page, plan)
                    self.assertEqual(reconcile.restore_frequency_panel(revised, plan), page)

    def test_scope_collector_component_policy_rejects_letters_inside_a_plain_word(self):
        from anki_pipeline import sense_candidate_scope as cs
        with tempfile.TemporaryDirectory() as directory:
            record, page, sources, options = self.compound_candidate_fixture(directory)
            inventory_path = Path(directory) / 'full-inventory-v2/records.jsonl'
            raw = json.loads(inventory_path.read_text())
            for value in (record, raw):
                row = value['occurrences'][0]
                row.update(english='A banana.', english_hash=sha('A banana.'), target_range=[3, 4])
                if row['status'] == 'reviewed':
                    value['occurrences'][0] = sf.seal_reviewed_assignment(value, row)
            sources['sentences'][record['occurrences'][0]['sentence_id']] = source(record['occurrences'][0])
            data = reconcile._json(raw) + '\n'
            inventory_path.write_text(data)
            audit_path = options['audit_path']
            audit = json.loads(audit_path.read_text())
            audit['source_snapshot']['inventory_record_sha256'] = sha(data)
            audit['source_snapshot']['inventory_record_byte_locator']['byte_length'] = len(data.encode())
            audit['context_proofs'][raw['occurrences'][0]['sentence_id']]['raw_source_english'] = 'A banana.'
            text = json.dumps(audit, ensure_ascii=False, sort_keys=True) + '\n'
            audit_path.write_text(text)
            options['expected_audit_sha256'] = sha(text)
            checked, capability = self.verified(record, page, sources)
            filtered, scopes = cs.apply_candidate_scope([checked], {record['card_id']: page}, {},
                                                      verified_sources=capability, **options)
            with self.assertRaisesRegex(ValueError, 'whole original token|complete collector component'):
                reconcile.plan_frequency_panel(page, filtered[0], {}, verified_sources=scopes.verified_sources,
                                               candidate_scope=scopes.for_record(filtered[0]))

    def test_scope_boundary_contract_matches_original_collector_without_interior_substrings(self):
        from scripts.prepare_sense_frequency_records import token_index
        english = "two-and-a-half A-G A-H A-grade A's an's banana a_grade a1 e-mail"
        spans = {(start, end) for start in range(len(english)) for end in range(start + 1, len(english) + 1)}
        wanted = {english[start:end].casefold() for start, end in spans}
        expected = {tuple(span) for values in token_index([{'english': english}], wanted).values()
                    for _, span in values}
        actual = {span for span in spans if reconcile._collector_target_boundary(english, span) is not None}
        self.assertEqual(actual, expected)
        possessive = english.index("A's")
        self.assertEqual(reconcile._collector_target_boundary(english, (possessive, possessive + 1))['kind'],
                         'complete-collector-component')
        inside = english.index('banana') + 1
        self.assertIsNone(reconcile._collector_target_boundary(english, (inside, inside + 1)))

    def test_generic_panel_still_rejects_a_compound_component_even_when_scope_collector_accepts_it(self):
        value, page, sources = self.fixture()
        row = value['occurrences'][1]
        row.update(english='A novel-based story.', english_hash=sha('A novel-based story.'), target_range=[2, 7])
        value['occurrences'][1] = sf.seal_reviewed_assignment(value, row)
        sources['sentences'][row['sentence_id']] = source(row)
        self.assertIsNotNone(reconcile._collector_target_boundary(row['english'], (2, 7)))
        record, capability = self.verified(value, page, sources)
        with self.assertRaisesRegex(ValueError, 'whole source token'):
            reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def fixture(self, *, plural=True, duplicate=False, old_count=1):
        panel = _exam_frequency_markup({'exam_frequency': frequency_for_matches(
            [('kaoyan:2019-01', 'old', 0, old_count)] if old_count else [], 44)})
        forms = ('<div class="dictionary-form-groups" data-dictionary="ecdict">'
            '<section class="dictionary-inflections"><dl class="form-row">'
            '<dt>复数</dt><dd>novels<small>source note</small></dd></dl></section></div>') if plural else ''
        definition = '<div class="dictionary-definition" data-dictionary="oxford">original definition</div>'
        page = ('<html><body><div id="preview-front"><h1 class="word">novel</h1></div>'
            '<div id="preview-back"><h1 class="word">novel</h1>' + panel + definition + forms + '</div></body></html>')
        value = {'book_id': 'redbook2027', 'card_id': 'novel-card', 'word': 'novel',
            'definition_source': 'oxford', 'definition_provenance': {
                'headword': 'novel', 'page_sha256': sha(page), 'web_source': '/native/novel.html'},
            'expected_occurrences': 2, 'senses': [{'pos': 'n.', 'text': '小说'}], 'occurrences': []}
        for year, token in [(2019, 'novel'), (2020, 'novels')]:
            english, translation = 'A ' + token + '.', '一本小说。'
            row = {'physical_source': [f'kaoyan:{year}-01:p:first:0'],
                'paper_id': f'kaoyan:{year}-01', 'sentence_id': f'kaoyan:{year}-01:p:first:0',
                'english': english, 'english_hash': sha(english), 'translation': translation,
                'source': f'{year}年考研英语一', 'target_range': [2, 2 + len(token)],
                'translation_ranges': [], 'source_provenance': {'reviewedContentHash': sha(str(year))},
                'status': 'reviewed', 'sense_index': 0, 'reason': '名词小说',
                'method': 'context-review', 'review_version': 'test'}
            value['occurrences'].append(sf.seal_reviewed_assignment(value, row))
        if duplicate:
            value['occurrences'].append(deepcopy(value['occurrences'][0]))
        sources = {'sentences': {row['sentence_id']: source(row)
            for row in value['occurrences']}, 'completions': {}, 'options': {}, 'watched': {}}
        return value, page, sources

    def verified(self, value, page, sources, aliases=None):
        with patch.object(sd, '_load_sources', return_value=sources):
            records, capability = reconcile.reread_source_displays(
                [value], {value['card_id']: page}, aliases or {})
        return records[0], capability

    def test_correct_panel_is_reversible_and_preserves_assignments_and_source_definitions(self):
        value, page, sources = self.fixture()
        before = deepcopy(value)
        record, capability = self.verified(value, page, sources)
        plan = reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)
        revised = reconcile.apply_frequency_panel(page, plan)
        audit = plan.verification()
        self.assertEqual(value, before)
        self.assertEqual(record['definition_provenance'], before['definition_provenance'])
        self.assertEqual([row['assignment_context_hash'] for row in record['occurrences']],
                         [row['assignment_context_hash'] for row in before['occurrences']])
        self.assertEqual(audit['old_frequency']['occurrences'], 1)
        self.assertEqual(audit['new_frequency']['occurrences'], 2)
        self.assertEqual(audit['new_frequency']['paper_count'], 2)
        self.assertEqual(audit['new_frequency']['matched_sentences'], 2)
        self.assertIn('原网页1次，按明确词形和原文位置核对为2次', revised)
        self.assertIn('data-occurrences="2"', revised)
        self.assertIn('original definition', revised)
        self.assertEqual(reconcile.restore_frequency_panel(revised, plan), page)
        self.assertEqual(audit['old_panel_sha256'], sha(audit['old_panel_html']))
        self.assertEqual(audit['new_panel_sha256'], sha(audit['new_panel_html']))
        self.assertEqual(audit['source_page_sha256'], sha(page))
        self.assertEqual(audit['preview_page_sha256'], sha(revised))
        self.assertEqual(len(audit['source_evidence']['tokens']), 2)
        self.assertIn('source-displays-producer', audit['source_evidence']['trust_boundary'])
        self.assertEqual(json.loads(json.dumps(audit)), audit)
        audit['old_panel_html'] = 'corrupt external copy'
        self.assertEqual(reconcile.restore_frequency_panel(revised, plan), page)

    def test_a_hash_sealed_display_or_boolean_is_not_source_authority(self):
        value, page, sources = self.fixture()
        record, _ = self.verified(value, page, sources)
        for capability in (None, True, {}, {'sha256': sha(page)}):
            with self.subTest(capability=capability), self.assertRaisesRegex(ValueError, 'producer'):
                reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_producer_failure_does_not_issue_capability_or_mutate_inputs(self):
        value, page, sources = self.fixture()
        original = deepcopy(value)
        sources['sentences'][value['occurrences'][0]['sentence_id']]['english'] += ' stale'
        with patch.object(sd, '_load_sources', return_value=sources):
            with self.assertRaisesRegex(ValueError, 'stale'):
                reconcile.reread_source_displays([value], {value['card_id']: page}, {})
        self.assertEqual(value, original)

    def test_missing_explicit_inflection_cannot_be_inferred(self):
        value, page, sources = self.fixture(plural=False)
        record, capability = self.verified(value, page, sources)
        with self.assertRaisesRegex(ValueError, 'explicitly displayed'):
            reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_derived_word_rows_never_become_inflections(self):
        value, page, sources = self.fixture()
        page = page.replace('class="form-row"', 'class="form-row derived-word"')
        value['definition_provenance']['page_sha256'] = sha(page)
        record, capability = self.verified(value, page, sources)
        with self.assertRaisesRegex(ValueError, 'explicitly displayed'):
            reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_duplicate_physical_token_is_rejected_instead_of_counted_or_silently_deduplicated(self):
        value, page, sources = self.fixture(duplicate=True)
        with self.assertRaisesRegex(ValueError, 'duplicate physical'):
            self.verified(value, page, sources)

    def test_after_producer_changes_to_page_record_target_or_assignment_fail_closed(self):
        value, page, sources = self.fixture()
        record, capability = self.verified(value, page, sources)
        for mutation in ('page', 'word', 'english', 'range', 'physical', 'reason', 'old_count'):
            changed, changed_page = deepcopy(record), page
            if mutation == 'page': changed_page += ' '
            if mutation == 'word': changed['word'] = 'other'
            if mutation == 'english': changed['occurrences'][0]['english'] += ' changed'
            if mutation == 'range': changed['occurrences'][0]['target_range'] = [0, 1]
            if mutation == 'physical': changed['occurrences'][0]['physical_source'] = ['other']
            if mutation == 'reason': changed['occurrences'][0]['reason'] = 'a new review'
            if mutation == 'old_count': changed_page = page.replace('data-occurrences="1"', 'data-occurrences="9"')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reconcile.plan_frequency_panel(changed_page, changed, {}, verified_sources=capability)

    def test_whole_token_range_required_even_if_substring_is_the_lemma(self):
        value, page, sources = self.fixture()
        row = value['occurrences'][1]
        row['target_range'] = [2, 7]  # novel inside novels
        value['occurrences'][1] = sf.seal_reviewed_assignment(value, row)
        record, capability = self.verified(value, page, sources)
        with self.assertRaisesRegex(ValueError, 'whole source token'):
            reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_wrong_visible_headword_is_rejected_even_with_fresh_hash(self):
        value, page, sources = self.fixture()
        page = page.replace('class="word">novel', 'class="word">story')
        value['definition_provenance']['page_sha256'] = sha(page)
        record, capability = self.verified(value, page, sources)
        with self.assertRaisesRegex(ValueError, 'headword'):
            reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_two_tokens_in_one_original_sentence_have_one_coverage_unit(self):
        value, page, _ = self.fixture()
        english = 'A novel about novels.'
        for row, span in zip(value['occurrences'], ([2, 7], [14, 20])):
            row.update(english=english, english_hash=sha(english), paper_id='kaoyan:2019-01',
                sentence_id='kaoyan:2019-01:p:first:0', physical_source=['kaoyan:2019-01:p:first:0'],
                target_range=span, source_provenance={'reviewedContentHash': sha('2019')})
        value['occurrences'] = [sf.seal_reviewed_assignment(value, row) for row in value['occurrences']]
        sources = {'sentences': {value['occurrences'][0]['sentence_id']: source(value['occurrences'][0])},
                   'completions': {}, 'options': {}, 'watched': {}}
        record, capability = self.verified(value, page, sources)
        plan = reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)
        self.assertEqual(plan.verification()['new_frequency']['paper_count'], 1)
        self.assertEqual(plan.verification()['new_frequency']['matched_sentences'], 1)

    def test_already_matching_panel_needs_no_patch(self):
        value, page, sources = self.fixture()
        old = _exam_frequency_markup({'exam_frequency': frequency_for_matches([('kaoyan:2019-01', 'old', 0, 1)], 44)})
        correct = _exam_frequency_markup({'exam_frequency': frequency_for_matches(
            [('kaoyan:2019-01', 'first', 0, 1), ('kaoyan:2020-01', 'first', 0, 1)], 44)})
        page = page.replace(old, correct)
        value['definition_provenance']['page_sha256'] = sha(page)
        record, capability = self.verified(value, page, sources)
        self.assertIsNone(reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability))

    def test_unchanged_compound_panels_do_not_require_a_guessed_component_repair(self):
        value, page, sources = self.fixture()
        first = _exam_frequency_markup({'exam_frequency': frequency_for_matches([('kaoyan:2019-01', 'old', 0, 1)], 44)})
        second = _exam_frequency_markup({'exam_frequency': frequency_for_matches([('kaoyan:2020-01', 'old', 0, 1)], 44)})
        definition = '<div class="dictionary-definition" data-dictionary="oxford">original definition</div>'
        other = '<div class="dictionary-definition" data-dictionary="oxford">independent definition</div>'
        page = page.replace(definition, definition + '<h3>independent component</h3>' + second + other)
        value['definition_provenance']['components'] = [
            {'component_index': i, 'html_sha256': sha(fragment)}
            for i, fragment in enumerate((definition, other))]
        value['definition_provenance']['page_sha256'] = sha(page)
        record, capability = self.verified(value, page, sources)
        self.assertIsNone(reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability))

    def test_patch_and_restore_reject_unrelated_page_changes_and_repeated_application(self):
        value, page, sources = self.fixture()
        record, capability = self.verified(value, page, sources)
        plan = reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)
        revised = reconcile.apply_frequency_panel(page, plan)
        for function, target in ((reconcile.apply_frequency_panel, page + ' '),
                                 (reconcile.apply_frequency_panel, revised),
                                 (reconcile.restore_frequency_panel, revised + ' '),
                                 (reconcile.restore_frequency_panel, page)):
            with self.assertRaisesRegex(ValueError, 'page'):
                function(target, plan)

    def test_no_unique_complete_panel_is_not_a_frequency_guard_bypass(self):
        for mutation in ('missing', 'duplicate', 'malformed'):
            value, page, sources = self.fixture()
            panel = _exam_frequency_markup({'exam_frequency': frequency_for_matches([('kaoyan:2019-01', 'old', 0, 1)], 44)})
            if mutation == 'missing': page = page.replace(panel, '')
            if mutation == 'duplicate': page = page.replace(panel, panel + panel)
            if mutation == 'malformed': page = page.replace('data-paper-count="1"', 'data-paper-count="9"')
            value['definition_provenance']['page_sha256'] = sha(page)
            record, capability = self.verified(value, page, sources)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)

    def test_arbitrary_physical_key_is_rejected_even_when_the_sentence_display_would_validate(self):
        value, page, sources = self.fixture()
        value['occurrences'][0]['physical_source'] = ['fabricated-independent-location']
        with self.assertRaisesRegex(ValueError, 'canonical key'):
            self.verified(value, page, sources)

    def test_stale_original_paragraph_range_is_rejected_before_capability(self):
        value, page, sources = self.fixture()
        value['occurrences'][0]['source_provenance']['paragraphRange'] = [0, 999]
        with self.assertRaisesRegex(ValueError, 'paragraphRange'):
            self.verified(value, page, sources)

    def test_source_manifest_must_match_the_actual_producer_read(self):
        value, page, sources = self.fixture()
        changed = deepcopy(sources)
        changed['watched'] = {'never-read': '0' * 64}
        with patch.object(sd, '_load_sources', side_effect=[changed, sources]):
            with self.assertRaisesRegex(ValueError, 'source manifest differs'):
                reconcile.reread_source_displays([value], {value['card_id']: page}, {})

    def test_issued_capability_and_panel_plan_cannot_be_mutated(self):
        value, page, sources = self.fixture()
        record, capability = self.verified(value, page, sources)
        plan = reconcile.plan_frequency_panel(page, record, {}, verified_sources=capability)
        with self.assertRaises(AttributeError): capability._producer_sha256 = 'changed'
        with self.assertRaises(AttributeError): plan._payload = '{}'


if __name__ == '__main__':
    unittest.main()
