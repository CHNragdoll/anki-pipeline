"""Reading completion display remains separate from printed corpus and anchors."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.exam_library import library_examples
from anki_pipeline.reading_completion import (complete_english, load_reading_completions,
    option_range, original_range, prepare_reading_completions)
from tests.test_codex_exam_index import record, sha, write_fixture, write_json
from tests.test_packaging import card


class ReadingCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'staging'
        self.sidecar = self.root / 'data/reading-completions-v1.json'
        self.structured = self.root / 'data/sources/exam-library/structured/papers/kaoyan/2026-01.json'
        self.english = 'The rate indicates ____.'
        self.option = 'higher rate.'
        self.stem_id = 'kaoyan:2026-01:p:stem'
        self.option_id = 'kaoyan:2026-01:q-21-1:C'
        self.create_source()
        self.rows, self.index_report = load_codex_exam_index(self.stage, allow_partial=True)
        self.payload, _ = prepare_reading_completions(self.root, self.rows, self.index_report)
        self.payload['rows'][0].update(translationZh='这个比率表明比率更高。', status='reviewed')
        write_json(self.sidecar, self.payload)
        self.write_approval(self.payload)

    def write_approval(self, payload):
        review = {'schema': 'reading-question-completion-review.v1', 'status': 'approved',
            'sidecarSha256': sha(self.sidecar.read_bytes()),
            'indexManifestHash': payload['indexManifestHash'],
            'inputManifestHash': payload['inputManifestHash'],
            'reviewedSentenceIds': [row['sentenceId'] for row in payload['rows']],
            'evidenceFiles': {'independent-review.json': sha('Independent review evidence')}}
        write_json(self.sidecar.with_suffix('.review.json'), review)
        return review

    def create_source(self, *, english=None, option=None):
        self.english = english or self.english
        self.option = option or self.option
        stem = record(english=self.english, translation='这个比率表明____。', kind='question_prompt',
            identifier=self.stem_id, context={'sourcePath': 'Reading question 21',
                'sourceBlockIds': ['kaoyan:2026-01:b-1']})
        option_start = self.option.index('rate')
        choice = record(english=self.option, translation='更高的比率。', kind='answer_option',
            identifier=self.option_id, context={'questionId': 'kaoyan:2026-01:q-21-1',
                'sourceBlockIds': ['kaoyan:2026-01:b-2']}, alignments=[
                {'en': [option_start, option_start+4], 'zh': [[3, 5]], 'relation': 'equivalent'}])
        write_fixture(self.stage, records={'2026-01': [stem, choice]})
        # The structured stem differs deliberately; block identity is authoritative.
        write_json(self.structured, {'id': 'kaoyan:2026-01', 'blocks': [
            {'id': 'b-1', 'questionId': 'q-21-1'}, {'id': 'b-2', 'questionId': 'q-21-1'}],
            'questions': [{'id': 'q-21-1', 'number': '21', 'stem': 'A differently printed prompt ____',
                'answer': {'status': 'explicit', 'value': 'C', 'externalSource': {
                    'url': 'https://example.test/answers', 'capturedAt': '2026-10-01',
                    'answerToken': '21-C'}}, 'options': [
                    {'label': 'A.', 'text': 'other'}, {'label': 'C.', 'text': self.option}]}]})

    def import_card(self, word='rate'):
        return library_examples(self.root, [card('rate-card', word=word, audio='')],
            'http://localhost:8765', 'latex', sentence_source='codex',
            codex_index_root=self.stage, allow_partial_codex=True,
            reading_completion_path=self.sidecar)

    def test_default_sidecar_uses_input_root_when_module_is_installed_elsewhere(self):
        # A wheel lives in site-packages, independently of external study inputs.
        installed_module = self.root / 'environment/site-packages/anki_pipeline/exam_library.py'
        with patch('anki_pipeline.exam_library.__file__', str(installed_module)):
            values, report = library_examples(
                self.root, [card('rate-card', word='rate', audio='')],
                'http://localhost:8765', 'latex', sentence_source='codex',
                codex_index_root=self.stage, allow_partial_codex=True)
        self.assertEqual(values[0]['examples'][0]['text'], 'The rate indicates higher rate.')
        self.assertEqual(report['reading_completions']['completed_reading_questions'], 1)

    def test_completed_display_underlines_answer_and_frequency_uses_printed_source(self):
        source = {path: path.read_bytes() for path in self.stage.rglob('*.json')}
        values, report = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], 'The rate indicates higher rate.')
        self.assertEqual(example['translation'], '这个比率表明比率更高。')
        self.assertEqual(example['matched_english_ranges'], [[4, 8], [26, 30]])
        self.assertEqual(example['cloze_answers'], [
            {'start': 19, 'end': 30, 'word': 'higher rate', 'number': 21}])
        self.assertEqual(example['translation_alignment']['alignments'], [])
        self.assertEqual(example['translation_alignment']['englishHash'], sha(example['text']))
        self.assertEqual(example['translation_alignment']['translationHash'], sha(example['translation']))
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 2)
        self.assertEqual(report['reading_completions']['completed_reading_questions'], 1)
        self.assertEqual(report['reading_completions']['approval_sha256'],
                         sha(self.sidecar.with_suffix('.review.json').read_bytes()))
        self.assertEqual(source, {path: path.read_bytes() for path in source})
        params = parse_qs(urlsplit(example['latex_url']).query)
        self.assertEqual(params['anki-codex-sentence'], [self.stem_id + ':0'])
        self.assertEqual(json.loads(params['anki-codex-en'][0]), [[4, 8]])
        self.assertEqual(params['anki-codex-hash'], [sha(self.english)])
        self.assertNotEqual(params['anki-codex-hash'][0], example['english_hash'])

    def test_added_answer_target_links_to_original_option_sentence(self):
        values, _ = self.import_card('higher')
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], 'The rate indicates higher rate.')
        self.assertEqual(example['matched_english_ranges'], [[19, 25]])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 1)
        params = parse_qs(urlsplit(example['full_paper_url']).query)
        self.assertEqual(params['anki-codex-sentence'], [self.option_id + ':0'])
        self.assertEqual(params['anki-codex-hash'], [sha(self.option)])
        self.assertEqual(json.loads(params['anki-codex-en'][0]), [[0, 6]])
        self.assertEqual(example['source_anchor']['sentence_id'], self.option_id + ':0')

    def test_ordinary_completed_links_keep_their_single_original_pin(self):
        for word in ('rate', 'higher', 'indicates'):
            with self.subTest(word=word):
                values, _ = self.import_card(word)
                example = values[0]['examples'][0]
                for field in ('full_paper_url', 'latex_url'):
                    params = parse_qs(urlsplit(example[field]).query)
                    self.assertNotIn('anki-codex-context', params)

    def test_raw_exclusions_apply_before_completion_for_stem_and_inserted_option(self):
        for excluded_id, source, excluded_range, displayed_range, anchor_id, anchor_range in (
            (self.stem_id, self.english, [4, 8], [26, 30], self.option_id, [7, 11]),
            (self.option_id, self.option, [7, 11], [4, 8], self.stem_id, [4, 8]),
        ):
            with self.subTest(excluded_id=excluded_id):
                write_json(self.stage / 'targets/occurrence-exclusions.json', {
                    'schema': 'codex-anki-occurrence-exclusions.v1',
                    'rangeUnit': 'sentence-codepoints', 'exclusions': [{
                        'sentenceId': excluded_id + ':0', 'cardId': 'rate-card',
                        'paperId': 'kaoyan:2026-01', 'englishHash': sha(source),
                        'sourceHash': sha(source), 'word': 'rate', 'form': 'rate',
                        'en': excluded_range, 'reason': 'Reviewed source sense exclusion'}]})
                values, report = self.import_card()
                example = values[0]['examples'][0]
                self.assertEqual(example['matched_english_ranges'], [displayed_range])
                self.assertEqual(values[0]['exam_frequency']['occurrences'], 1)
                self.assertEqual(report['excluded_homograph_occurrences'], 1)
                params = parse_qs(urlsplit(example['latex_url']).query)
                self.assertEqual(params['anki-codex-sentence'], [anchor_id + ':0'])
                self.assertEqual(json.loads(params['anki-codex-en'][0]), [anchor_range])

    def test_suffix_matches_and_exclusions_keep_original_offsets_after_replacement(self):
        self.create_source(english='The ____ raises rate.')
        self.rows, self.index_report = load_codex_exam_index(self.stage, allow_partial=True)
        payload, _ = prepare_reading_completions(self.root, self.rows, self.index_report)
        payload['rows'][0].update(translationZh='更高的比率提高了比率。', status='reviewed')
        write_json(self.sidecar, payload)
        self.write_approval(payload)
        values, _ = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], 'The higher rate. raises rate.')
        self.assertEqual(example['matched_english_ranges'], [[11, 15], [24, 28]])
        params = parse_qs(urlsplit(example['latex_url']).query)
        self.assertEqual(json.loads(params['anki-codex-en'][0]), [[16, 20]])
        write_json(self.stage / 'targets/occurrence-exclusions.json', {
            'schema': 'codex-anki-occurrence-exclusions.v1', 'rangeUnit': 'sentence-codepoints',
            'exclusions': [{'sentenceId': self.stem_id + ':0', 'cardId': 'rate-card',
                'paperId': 'kaoyan:2026-01', 'englishHash': sha(self.english),
                'sourceHash': sha(self.english), 'word': 'rate', 'form': 'rate',
                'en': [16, 20], 'reason': 'Reviewed source sense exclusion'}]})
        values, _ = self.import_card()
        self.assertEqual(values[0]['examples'][0]['matched_english_ranges'], [[11, 15]])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 1)

    def test_selected_dictionary_inflection_can_match_the_completed_answer(self):
        self.create_source(option='rates grow.')
        self.rows, self.index_report = load_codex_exam_index(self.stage, allow_partial=True)
        payload, _ = prepare_reading_completions(self.root, self.rows, self.index_report)
        payload['rows'][0].update(translationZh='这个比率表明比率上升。', status='reviewed')
        write_json(self.sidecar, payload)
        self.write_approval(payload)
        value = card('rate-card', word='rate', audio='')
        value['local_dictionary'] = {'forms_source': 'webster',
            'forms': [{'kind': 'plural', 'form': 'rates', 'base': 'rate'}]}
        values, _ = library_examples(self.root, [value], 'http://localhost:8765', 'latex',
            sentence_source='codex', codex_index_root=self.stage, allow_partial_codex=True,
            reading_completion_path=self.sidecar)
        self.assertEqual(values[0]['examples'][0]['matched_english_ranges'], [[4, 8], [19, 24]])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 2)

    def test_missing_stale_ambiguous_or_unreviewed_data_fails_closed(self):
        baseline = copy.deepcopy(self.payload)
        for field in ('originalEnglishHash', 'originalTranslationHash', 'originalSourceHash',
                      'originalReviewedContentHash', 'structuredPaperHash', 'indexFileHash',
                      'reviewedInputHash', 'reviewedTranslationHash', 'reviewHash',
                      'optionTextHash', 'optionEnglishHash', 'optionTranslationHash',
                      'optionReviewedContentHash', 'optionSourceHash'):
            with self.subTest(field=field):
                changed = copy.deepcopy(baseline)
                changed['rows'][0][field] = '0' * 64
                write_json(self.sidecar, changed)
                with self.assertRaisesRegex(ValueError, 'stale'):
                    self.import_card()
        for change in ('blank-translation', 'missing-translation', 'unreviewed', 'missing-row',
                       'duplicate-row', 'blank-left', 'shifted-offset', 'stale-manifest'):
            with self.subTest(change=change):
                changed = copy.deepcopy(baseline)
                if change == 'blank-translation': changed['rows'][0]['translationZh'] = '____'
                if change == 'missing-translation': changed['rows'][0].pop('translationZh')
                if change == 'unreviewed': changed['rows'][0]['status'] = 'draft'
                if change == 'missing-row': changed['rows'] = []
                if change == 'duplicate-row': changed['rows'].append(copy.deepcopy(changed['rows'][0]))
                if change == 'blank-left': changed['rows'][0]['completedEnglish'] = self.english
                if change == 'shifted-offset': changed['rows'][0]['insertedRange'][0] += 1
                if change == 'stale-manifest': changed['indexManifestHash'] = '0' * 64
                write_json(self.sidecar, changed)
                with self.assertRaises(ValueError): self.import_card()
        self.sidecar.unlink()
        with self.assertRaisesRegex(ValueError, 'sidecar is missing'): self.import_card()

    def test_changed_structured_source_and_duplicate_json_fields_are_rejected(self):
        self.structured.write_bytes(self.structured.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'stale'):
            self.import_card()
        self.create_source()
        self.sidecar.write_text('{"schema":"reading-question-completions.v1", "schema":"other"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.import_card()

    def test_sidecar_rejects_unknown_top_level_and_row_fields(self):
        for location in ('top', 'row'):
            with self.subTest(location=location):
                changed = copy.deepcopy(self.payload)
                target = changed if location == 'top' else changed['rows'][0]
                target['futureSchemaExtension'] = {'changesMeaning': True}
                write_json(self.sidecar, changed)
                with self.assertRaisesRegex(ValueError, 'unknown or missing fields'):
                    self.import_card()

    def test_independent_approval_is_exact_complete_and_source_bound(self):
        baseline = self.write_approval(self.payload)
        path = self.sidecar.with_suffix('.review.json')
        for change in ('wrong-schema', 'unapproved', 'sidecar-hash', 'index-hash', 'input-hash',
                       'missing-id', 'duplicate-id', 'unknown-id', 'unknown-field',
                       'missing-field', 'empty-evidence', 'invalid-evidence-hash'):
            with self.subTest(change=change):
                review = copy.deepcopy(baseline)
                if change == 'wrong-schema': review['schema'] = 'other'
                if change == 'unapproved': review['status'] = 'draft'
                if change == 'sidecar-hash': review['sidecarSha256'] = '0' * 64
                if change == 'index-hash': review['indexManifestHash'] = '0' * 64
                if change == 'input-hash': review['inputManifestHash'] = '0' * 64
                if change == 'missing-id': review['reviewedSentenceIds'] = []
                if change == 'duplicate-id': review['reviewedSentenceIds'] *= 2
                if change == 'unknown-id': review['reviewedSentenceIds'] = ['unknown']
                if change == 'unknown-field': review['futureApproval'] = True
                if change == 'missing-field': review.pop('status')
                if change == 'empty-evidence': review['evidenceFiles'] = {}
                if change == 'invalid-evidence-hash': review['evidenceFiles'] = {'review': 'not-a-hash'}
                write_json(path, review)
                with self.assertRaises(ValueError): self.import_card()
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'approval is missing'): self.import_card()

    def test_chinese_or_valid_english_changes_invalidate_independent_approval(self):
        changed = copy.deepcopy(self.payload)
        changed['rows'][0]['translationZh'] = '这个比率说明比率较高。'
        self.assertEqual(changed['rows'][0]['status'], 'reviewed')
        write_json(self.sidecar, changed)
        with self.assertRaisesRegex(ValueError, 'approval sidecar hash mismatch'):
            self.import_card()
        # A legitimate new reviewed source and a correctly regenerated sidecar
        # still need a new independent approval of the exact derived bytes.
        self.create_source(english='The rate shows ____.')
        self.rows, self.index_report = load_codex_exam_index(self.stage, allow_partial=True)
        payload, _ = prepare_reading_completions(self.root, self.rows, self.index_report)
        payload['rows'][0].update(translationZh='这个比率表明比率更高。', status='reviewed')
        write_json(self.sidecar, payload)
        with self.assertRaisesRegex(ValueError, 'approval sidecar hash mismatch'):
            self.import_card()
        self.write_approval(payload)
        self.assertEqual(self.import_card()[0][0]['examples'][0]['text'],
                         'The rate shows higher rate.')

    def test_approval_file_is_watched_and_evidence_hashes_are_metadata(self):
        _, watched, report = load_reading_completions(
            self.root, self.sidecar, self.rows, self.index_report)
        review_path = self.sidecar.with_suffix('.review.json')
        self.assertIn(review_path, watched)
        self.assertEqual(watched[review_path], report['approval_sha256'])
        self.assertFalse((self.root / 'independent-review.json').exists())
        review_path.write_bytes(review_path.read_bytes() + b' ')
        self.assertNotEqual(sha(review_path.read_bytes()), watched[review_path])

    def test_missing_ambiguous_answers_or_blocks_are_never_guessed(self):
        original = json.loads(self.structured.read_text())
        for change in ('missing', 'ambiguous', 'duplicate-option', 'missing-block', 'extra-question',
                       'no-provenance', 'wrong-token', 'no-capture', 'non-http-source'):
            with self.subTest(change=change):
                changed = copy.deepcopy(original)
                if change == 'missing': changed['questions'][0]['answer'] = None
                if change == 'ambiguous': changed['questions'][0]['answer']['value'] = 'C/D'
                if change == 'duplicate-option': changed['questions'][0]['options'].append(
                    copy.deepcopy(changed['questions'][0]['options'][1]))
                if change == 'missing-block': changed['blocks'][0]['id'] = 'other'
                if change == 'extra-question': changed['questions'].append(
                    copy.deepcopy(changed['questions'][0]))
                if change == 'no-provenance': changed['questions'][0]['answer'].pop('externalSource')
                if change == 'wrong-token': changed['questions'][0]['answer']['externalSource']['answerToken'] = '22-C'
                if change == 'no-capture': changed['questions'][0]['answer']['externalSource']['capturedAt'] = ''
                if change == 'non-http-source': changed['questions'][0]['answer']['externalSource']['url'] = 'file:///tmp/answers'
                write_json(self.structured, changed)
                with self.assertRaises(ValueError):
                    prepare_reading_completions(self.root, self.rows, self.index_report)

    def test_terminal_period_attached_blank_and_suffix_offsets(self):
        for english, option, expected in (
            ('A century____', 'changed.', 'A century changed.'),
            ('A century ____.', 'changed.', 'A century changed.'),
            ('A century ____', 'changed', 'A century changed.'),
            ('A ____ later rate.', 'higher rate.', 'A higher rate. later rate.'),
            ('The remedy concerns ____', '“long-termism.”', 'The remedy concerns “long-termism.”'),
            ('The remedy concerns ____', '(lasting change.)', 'The remedy concerns (lasting change.)'),
        ):
            with self.subTest(english=english):
                completed, blank, inserted = complete_english(english, option)
                self.assertEqual(completed, expected)
                self.assertNotIn('..', completed)
                binding = {'originalEnglish': english, 'completedEnglish': completed,
                    'blankRange': blank, 'insertedRange': inserted, 'optionText': option}
                self.assertEqual(original_range(binding, (0, 1)), (0, 1))
                self.assertEqual(option_range(binding, tuple(inserted)),
                                 (0, len(option.rstrip('.'))))
                if 'later' in english:
                    displayed = completed.index('later')
                    self.assertEqual(original_range(binding, (displayed, displayed+5)),
                                     (english.index('later'), english.index('later')+5))
        for english in ('No blank here.', 'Two ____ and ____.'):
            with self.assertRaises(ValueError): complete_english(english, 'answer.')

    def test_2019_english_i_question_24_does_not_add_period_after_closing_quote(self):
        english = 'The US and France examples are used to illustrate ______'
        option = 'the approaches to promoting “long-termism.”'
        completed, _, inserted = complete_english(english, option)
        self.assertEqual(completed, english.replace('______', option))
        self.assertTrue(completed.endswith('“long-termism.”'))
        self.assertFalse(completed.endswith('.”.'))
        self.assertEqual(completed[slice(*inserted)], option)


class AvailableCorpusReadingCompletionTests(unittest.TestCase):
    def test_all_695_current_blanks_have_unique_verified_answers_and_exact_offsets(self):
        root = Path(__file__).resolve().parents[2] / 'exam-library'
        stage = root / 'data/staging/codex-translations-v1'
        if not (stage / 'index/manifest.json').is_file():
            self.skipTest('The local immutable 44-paper corpus is unavailable')
        source, report = load_codex_exam_index(stage)
        payload, watched = prepare_reading_completions(root, source, report)
        self.assertEqual(len(payload['rows']), 695)
        self.assertEqual(len(watched), 44)
        self.assertEqual(len({row['sentenceId'] for row in payload['rows']}), 695)
        by_id = {row['id']: row for row in source}
        attached = period_suffix = options_without_period = 0
        for row in payload['rows']:
            with self.subTest(sentence_id=row['sentenceId']):
                completed = row['completedEnglish']
                original = row['originalEnglish']
                blank_start, blank_end = row['blankRange']
                start, end = row['insertedRange']
                self.assertNotIn('_', completed)
                self.assertLessEqual(completed.count('..'), original.count('..'))
                self.assertTrue(completed[start:end])
                self.assertEqual(original[:blank_start], completed[:blank_start])
                self.assertEqual(row['originalEnglishHash'], sha(original))
                self.assertEqual(row['optionTextHash'], sha(row['optionText']))
                self.assertEqual(row['optionSentenceId'], by_id[row['optionSentenceId']]['id'])
                self.assertEqual(by_id[row['optionSentenceId']]['english'], row['optionText'])
                option_span = option_range(row, (start, end))
                self.assertEqual(row['optionText'][slice(*option_span)], completed[start:end])
                if blank_start and original[blank_start-1].isalnum(): attached += 1
                if original[blank_end:].startswith('.'): period_suffix += 1
                if not row['optionText'].endswith('.'): options_without_period += 1
                for match in re.finditer(r'[A-Za-z]+', completed):
                    span = (match.start(), match.end())
                    stem_span = original_range(row, span)
                    answer_span = option_range(row, span)
                    self.assertIsNotNone(stem_span or answer_span)
                    source_text = original if stem_span is not None else row['optionText']
                    self.assertEqual(source_text[slice(*(stem_span or answer_span))], match[0])
        self.assertEqual((attached, period_suffix, options_without_period), (7, 7, 13))
        self.assertTrue(all(sha(path.read_bytes()) == expected for path, expected in watched.items()))


if __name__ == '__main__':
    unittest.main()
