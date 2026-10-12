import copy
import unittest

from anki_pipeline.exam_usage import occurrence_usage
from anki_pipeline.exam_frequency import frequency_breakdown_for_matches
from anki_pipeline.reading_usage_metadata import (
    apply_question_metadata, build_question_metadata_index,
)


def metadata(*, status='verified', question_id='q-11-1', paper='kaoyan:2000-01'):
    pin = {'file': '/fixture/contexts.jsonl', 'sha256': 'a' * 64,
        'line_number': 1, 'question_index': 0,
        'json_pointer': '/questions/0/answer', 'question_sha256': 'b' * 64,
        'answer_status': 'explicit', 'answer_value': 'C',
        'captured_answer_token': question_id.split('-')[1] + '-C',
        'captured_source_url': 'https://example.org/answers', 'captured_at': '2026-09-29'}
    question = {'paper_id': paper, 'question_id': question_id,
        'question_kind': 'reading', 'status': status, 'source_pin': pin,
        'correct_labels': ['C'] if status == 'verified' else [],
        'incorrect_labels': ['A', 'B', 'D'] if status == 'verified' else [],
        'unknown_reasons': [] if status == 'verified' else ['answer_unverified'],
        'options': [{'label': letter, 'source_label': letter + '.', 'source_order': i + 1,
            'text': 'option ' + letter, 'source_option_id': None,
            'source_identity': {'question_id': question_id, 'label': letter},
            'source_json_pointer': f'/questions/0/options/{i}'}
            for i, letter in enumerate('ABCD')]}
    return {'schema': 'exam-usage-reading-answer-metadata.v1',
        'source_pin': {'file': pin['file'], 'sha256': pin['sha256']}, 'questions': [question]}


def occurrence(*, label='C', question_id='kaoyan:2000-01:q-11-1', kind='answer_option'):
    return {'paper_id': 'kaoyan:2000-01', 'sentence_id': 'kaoyan:2000-01:q-11-1:C:new:0',
        'occurrence_id': 'physical-occurrence', 'target_range': [0, 3],
        'physical_source': ['kaoyan:2000-01:q-11-1:C:new:0'],
        'source_provenance': {'sourcePathEvidence': {'kind': kind,
            'questionId': question_id, 'optionLabel': label}}}


class ReadingUsageMetadataTests(unittest.TestCase):
    def test_old_reading_question_11_is_reading_and_correct_without_number_guess(self):
        row = occurrence(); original = copy.deepcopy(row)
        usage = occurrence_usage(row); before = copy.deepcopy(usage)
        result = apply_question_metadata(row, usage, build_question_metadata_index(metadata()))
        self.assertEqual(result['source_role'], 'reading_option')
        self.assertEqual(result['reading_candidate_correctness'], 'correct')
        self.assertEqual(result['reading_candidate']['match_origins'], ['option'])
        self.assertEqual(result['reading_answer_metadata']['source_pin']['line_number'], 1)
        self.assertEqual(row, original); self.assertEqual(usage, before)

    def test_incorrect_option_remains_a_physical_reading_option(self):
        row = occurrence(label='A')
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))
        self.assertEqual(result['reading_candidate']['correctness'], 'incorrect')
        self.assertEqual(result['reading_candidate']['option_label'], 'A')
        self.assertEqual(row['occurrence_id'], 'physical-occurrence')

    def test_unknown_answer_does_not_assume_correctness_from_correct_option_label(self):
        row = occurrence(label=None, kind='question_prompt')
        row['display'] = {'derivation_payload': {'questionId': 'q-11-1', 'correctOptionLabel': 'C'}}
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata(status='unknown')))
        self.assertEqual(result['reading_candidate']['correctness'], 'unknown')
        self.assertEqual(result['reading_candidate']['match_origins'], ['stem'])
        self.assertEqual(result['source_role'], 'question_stem')

    def test_stem_candidate_uses_source_label_without_counting_a_copy(self):
        row = occurrence(label=None, kind='question_prompt')
        row['display'] = {'derivation_payload': {'questionId': 'q-11-1', 'correctOptionLabel': 'C'}}
        before = copy.deepcopy(row)
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))
        self.assertEqual(result['reading_candidate']['correctness'], 'correct')
        self.assertEqual(result['reading_candidate']['match_origins'], ['stem'])
        self.assertEqual(result['reading_candidate_correctness'], 'not_applicable')
        self.assertEqual(row, before)
        option = occurrence(label='A')
        option_usage = apply_question_metadata(option, occurrence_usage(option), build_question_metadata_index(metadata()))
        breakdown = frequency_breakdown_for_matches([
            (row['paper_id'], 'printed-stem', 0, 1, result),
            (option['paper_id'], 'printed-option-A', 0, 1, option_usage)])
        self.assertEqual(breakdown['occurrences'], 2)
        self.assertEqual(breakdown['source_role'], {'question_stem': 1, 'reading_option': 1})
        self.assertEqual(breakdown['reading_candidate_correctness'], {'incorrect': 1})

    def test_correct_option_label_never_replaces_printed_option_label(self):
        row = occurrence(label='A')
        row['display'] = {'derivation_payload': {'questionId': 'q-11-1', 'correctOptionLabel': 'C'}}
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))
        self.assertEqual(result['reading_candidate']['option_label'], 'A')
        self.assertEqual(result['reading_candidate']['correctness'], 'incorrect')

    def test_conflicting_explicit_candidate_flag_fails(self):
        row = occurrence(label='A')
        row['display'] = {'derivation_payload': {'questionId': 'q-11-1',
            'candidateOptionLabel': 'A', 'isCorrectCandidate': True}}
        with self.assertRaisesRegex(ValueError, 'conflict'):
            apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))

    def test_explicit_option_context_flag_is_checked_after_core_projection(self):
        row = occurrence(label='A')
        usage = occurrence_usage(row, options={row['sentence_id']: {
            'candidateOptionLabel': 'A', 'isCorrectCandidate': True}})
        with self.assertRaisesRegex(ValueError, 'conflict'):
            apply_question_metadata(row, usage, build_question_metadata_index(metadata()))

    def test_candidate_label_invalid_or_contradictory_fails(self):
        index = build_question_metadata_index(metadata())
        for change in ({'candidateOptionLabel': 'B'}, {'candidateOptionLabel': 'Z'}):
            row = occurrence(label='A'); row['display'] = {'derivation_payload': change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                apply_question_metadata(row, {'source_kind': 'answer_option'}, index)

    def test_unknown_metadata_preserves_existing_explicit_candidate_evidence(self):
        row = occurrence(label='A')
        row['display'] = {'derivation_payload': {'questionId': 'q-11-1',
            'candidateOptionLabel': 'A', 'isCorrectCandidate': False}}
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata(status='unknown')))
        self.assertEqual(result['reading_candidate']['correctness'], 'incorrect')
        self.assertEqual(result['reading_answer_metadata']['status'], 'unknown')
        self.assertEqual(result['reading_answer_metadata']['correctness_basis'], 'existing_explicit_candidate')

    def test_bare_and_exact_paper_prefixed_question_ids_normalize(self):
        data = metadata(); data['questions'][0]['question_id'] = 'kaoyan:2000-01:q-11-1'
        data['questions'][0]['options'][0]['source_identity']['question_id'] = 'q-11-1'
        index = build_question_metadata_index(data)
        row = occurrence(question_id='q-11-1')
        result = apply_question_metadata(row, occurrence_usage(row), index)
        self.assertEqual(result['reading_candidate']['question_id'], 'kaoyan:2000-01:q-11-1')
        self.assertEqual(result['reading_candidate']['correctness'], 'correct')

    def test_no_matching_exact_question_id_does_not_guess_from_number(self):
        row = occurrence(question_id='q-11-2')
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))
        self.assertEqual(result, occurrence_usage(row))

    def test_other_paper_prefix_and_conflicting_candidate_identity_fail(self):
        index = build_question_metadata_index(metadata())
        row = occurrence(question_id='kaoyan:2001-01:q-11-1')
        with self.assertRaisesRegex(ValueError, 'paper'):
            apply_question_metadata(row, occurrence_usage(row), index)
        row = occurrence(); row['display'] = {'derivation_payload': {'questionId': 'q-12-1', 'candidateOptionLabel': 'C'}}
        with self.assertRaisesRegex(ValueError, 'question'):
            apply_question_metadata(row, occurrence_usage(row), index)

    def test_metadata_rejects_duplicate_ids_fabricated_ids_overlap_and_incomplete_labels(self):
        changes = [lambda d: d['questions'].append(copy.deepcopy(d['questions'][0])),
            lambda d: d['questions'][0].update(question_id='11'),
            lambda d: d['questions'][0]['incorrect_labels'].append('C'),
            lambda d: d['questions'][0]['incorrect_labels'].remove('D'),
            lambda d: d['questions'][0]['options'][0].update(source_option_id='guessed-id'),
            lambda d: d['questions'][0]['source_pin'].update(sha256='stale')]
        for change in changes:
            with self.subTest(change=change):
                data = metadata(); change(data)
                with self.assertRaises(ValueError): build_question_metadata_index(data)

    def test_no_label_on_original_stem_has_no_option_correctness(self):
        row = occurrence(label=None, kind='question_prompt')
        result = apply_question_metadata(row, occurrence_usage(row), build_question_metadata_index(metadata()))
        self.assertEqual(result['reading_candidate']['option_label'], None)
        self.assertEqual(result['reading_candidate']['correctness'], 'not_applicable')
        self.assertEqual(result['reading_candidate']['match_origins'], ['stem'])


if __name__ == '__main__':
    unittest.main()
