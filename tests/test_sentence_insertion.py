"""Part B gaps reuse complete reviewed option text and translations."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from anki_pipeline.exam_library import library_examples
from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.reading_completion import original_range
from anki_pipeline.sentence_insertion import insertion_option_source, prepare_sentence_insertions
from tests.test_codex_exam_index import record, sha, write_fixture, write_json
from tests.test_packaging import card


class SentenceInsertionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'staging'
        self.structured = self.root / 'data/sources/exam-library/structured/papers/kaoyan/2021-01.json'
        self.stem_id = 'kaoyan:2021-01:p:body'
        self.option_id = 'kaoyan:2021-01:q-41-1:F'
        self.english = '(41)_____ ______ Later, the rate rose.'
        self.chinese = '（41）_____ ______ 后来，比率上升了。'
        self.option = 'Rates are high. The rate rises.'
        self.make_source()

    def make_source(self, *, english=None, chinese=None):
        self.english = english or self.english
        self.chinese = chinese or self.chinese
        rate_start = self.english.find('rate')
        stem_alignment = ([{'en': [rate_start, rate_start + 4], 'zh': [[self.chinese.index('比率'),
            self.chinese.index('比率')+2]], 'relation': 'equivalent'}] if rate_start >= 0 else
            [{'en': [0, 4], 'zh': [[0, 4]], 'relation': 'equivalent'}])
        stem = record('2021-01', english=self.english, translation=self.chinese,
            identifier=self.stem_id, kind='reading', context={
                'sourcePath': '2021 Part B', 'sourceBlockIds': ['kaoyan:2021-01:b-body']},
            alignments=stem_alignment)
        option, translated = record('2021-01', english=self.option, translation='比率很高。比率上升。',
            identifier=self.option_id, kind='answer_option', context={
                'questionId': 'kaoyan:2021-01:q-41-1',
                'sourceBlockIds': ['kaoyan:2021-01:b-option']})
        parts = [('Rates are high.', '比率很高。', [0, 5]), ('The rate rises.', '比率上升。', [4, 8])]
        option['sentences'], translated['sentences'] = [], []
        for index, (english, chinese, en_range) in enumerate(parts):
            start = self.option.index(english)
            sid = self.option_id + ':' + str(index)
            option['sentences'].append({'id': sid, 'start': start, 'end': start+len(english),
                                        'english': english, 'clozeAnswers': []})
            translated['sentences'].append({'id': sid, 'englishHash': sha(english),
                'translationZh': chinese, 'alignments': [
                    {'en': en_range, 'zh': [[0, 2]], 'relation': 'equivalent'}]})
        write_fixture(self.stage, names=('2021-01',), records={'2021-01': [stem, (option, translated)]})
        write_json(self.structured, {'id': 'kaoyan:2021-01', 'blocks': [
            {'id': 'b-body', 'questionId': 'q-41-1'}, {'id': 'b-option', 'questionId': 'q-41-1'}],
            'questions': [{'id': 'q-41-1', 'number': '41', 'sourceBlocks': ['b-body', 'b-option'],
                'context': {'kind': 'numbered_gap_passage', 'taskForm': 'sentence_insertion',
                            'id': 'kaoyan:2021-01:part-b'},
                'answer': {'status': 'explicit', 'value': 'F', 'externalSource': {
                    'url': 'https://example.test/answers', 'capturedAt': '2026-10-01',
                    'answerToken': '41-F'}},
                'options': [{'label': 'F.', 'text': self.option,
                             'sourceOptionId': 'kaoyan:2021-01:part-b:F'}]}]})

    def import_card(self, *, maximum=0, word='rate'):
        value = card('rate-card', word=word, audio='')
        if word == 'rate':
            value['local_dictionary'] = {'forms_source': 'webster',
                'forms': [{'kind': 'plural', 'form': 'rates', 'base': 'rate'}]}
        return library_examples(self.root, [value], 'http://localhost:8765', 'latex', maximum,
            sentence_source='codex', codex_index_root=self.stage, allow_partial_codex=True)

    def test_gap_uses_all_approved_option_sentences_and_reuses_both_chinese_fragments(self):
        values, report = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], self.option + ' Later, the rate rose.')
        self.assertEqual(example['translation'], '比率很高。比率上升。 后来，比率上升了。')
        self.assertNotIn('_', example['text'])
        self.assertNotIn('_', example['translation'])
        self.assertEqual(example['cloze_answers'], [{'start': 0, 'end': len(self.option),
                                                    'word': self.option, 'number': 41}])
        self.assertEqual(example['translation_alignment']['alignments'], [])
        self.assertEqual(example['translation_alignment']['englishHash'], sha(example['text']))
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 3)
        self.assertEqual(report['sentence_insertions']['completed_gaps'], 1)
        self.assertEqual(report['sentence_insertions']['reused_option_sentences'], 2)
        self.assertEqual(report['sentence_insertions']['new_translations'], 0)
        params = parse_qs(urlsplit(example['latex_url']).query)
        self.assertEqual(params['anki-codex-sentence'], [self.stem_id + ':0'])
        self.assertEqual(json.loads(params['anki-codex-en'][0]),
                         [[self.english.index('rate'), self.english.index('rate')+4]])
        refs = {ref['sentence_id']: ref for ref in example['source_target_refs']}
        self.assertEqual(refs[self.option_id + ':0']['ranges'], [[0, 5]])
        self.assertEqual(refs[self.option_id + ':1']['ranges'], [[4, 8]])
        self.assertEqual(refs[self.option_id + ':1']['english_hash'], sha('The rate rises.'))
        capped, _ = self.import_card(maximum=1)
        self.assertEqual(capped[0]['exam_frequency'], values[0]['exam_frequency'])

    def test_added_targets_in_each_option_sentence_use_that_sentence_local_anchor(self):
        for word, index, english in [('high', 0, 'Rates are high.'), ('rises', 1, 'The rate rises.')]:
            with self.subTest(word=word):
                values, _ = self.import_card(word=word)
                example = values[0]['examples'][0]
                params = parse_qs(urlsplit(example['latex_url']).query)
                start = english.index(word)
                self.assertEqual(params['anki-codex-sentence'], [self.option_id + ':' + str(index)])
                self.assertEqual(params['anki-codex-hash'], [sha(english)])
                self.assertEqual(json.loads(params['anki-codex-en'][0]), [[start, start+len(word)]])
                self.assertEqual(example['matched_english_ranges'],
                    [[example['text'].index(word), example['text'].index(word)+len(word)]])
                self.assertEqual(values[0]['exam_frequency']['occurrences'], 1)

    def test_pure_blank_generates_full_example_with_no_double_period_or_fresh_translation(self):
        self.make_source(english='(41)________.', chinese='（41）________。')
        values, report = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], self.option)
        self.assertEqual(example['translation'], '比率很高。比率上升。')
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 2)
        self.assertEqual(example['matched_english_ranges'], [[0, 5], [20, 24]])
        self.assertEqual(report['sentence_insertions']['new_translations'], 0)
        self.assertEqual(example['cloze_answers'][0]['word'], self.option[:-1])

    def test_quoted_gap_preserves_original_quotes_without_an_extra_period(self):
        self.make_source(english='In addition, “(41)________”', chinese='此外，“（41）________”')
        values, _ = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual(example['text'], 'In addition, “' + self.option + '”')
        self.assertEqual(example['translation'], '此外，“比率很高。比率上升。”')
        self.assertNotIn('.”.', example['text'])

    def test_old_option_and_stem_exclusions_still_use_original_offsets(self):
        sources, _ = load_codex_exam_index(self.stage, allow_partial=True)
        by_id = {row['id']: row for row in sources}
        source = by_id[self.option_id + ':1']
        write_json(self.stage / 'targets/occurrence-exclusions.json', {
            'schema': 'codex-anki-occurrence-exclusions.v1', 'rangeUnit': 'sentence-codepoints',
            'exclusions': [{'sentenceId': source['id'], 'cardId': 'rate-card',
                'paperId': source['paperId'], 'englishHash': source['englishHash'],
                'sourceHash': source['sourceHash'], 'word': 'rate', 'form': 'rate',
                'en': [4, 8], 'reason': 'Reviewed source sense exclusion'}]})
        values, report = self.import_card()
        example = values[0]['examples'][0]
        self.assertEqual([example['text'][slice(*span)] for span in example['matched_english_ranges']],
                         ['Rates', 'rate'])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 2)
        self.assertEqual(report['excluded_homograph_occurrences'], 1)
        self.assertNotIn(self.option_id + ':1', [ref['sentence_id'] for ref in example['source_target_refs']])

    def test_missing_or_ambiguous_answer_and_number_or_block_drift_fail_closed(self):
        baseline = json.loads(self.structured.read_text())
        for change in ('missing-answer', 'ambiguous-answer', 'wrong-token', 'duplicate-option',
                       'wrong-number', 'wrong-block', 'wrong-kind'):
            with self.subTest(change=change):
                paper = copy.deepcopy(baseline)
                question = paper['questions'][0]
                if change == 'missing-answer': question['answer'] = None
                if change == 'ambiguous-answer': question['answer']['value'] = 'A/F'
                if change == 'wrong-token': question['answer']['externalSource']['answerToken'] = '42-F'
                if change == 'duplicate-option': question['options'] *= 2
                if change == 'wrong-number': question['number'] = '42'
                if change == 'wrong-block': question['sourceBlocks'] = ['b-option']
                if change == 'wrong-kind': question['context']['taskForm'] = 'other'
                write_json(self.structured, paper)
                with self.assertRaises(ValueError): self.import_card()

    def test_missing_numbered_chinese_placeholder_or_option_fragment_fails_closed(self):
        self.make_source(chinese='（42）_____ ______ 后来，比率上升了。')
        with self.assertRaisesRegex(ValueError, 'Chinese placeholder'): self.import_card()
        self.make_source(chinese='（41）_____ ______ 后来，比率上升了。')
        sources, report = load_codex_exam_index(self.stage, allow_partial=True)
        missing = [row for row in sources if row['id'] != self.option_id + ':0']
        with self.assertRaisesRegex(ValueError, 'coverage'):
            prepare_sentence_insertions(self.root, missing, report)
        missing_translation = copy.deepcopy(sources)
        next(row for row in missing_translation if row['id'] == self.option_id + ':1')['translationZh'] = None
        with self.assertRaisesRegex(ValueError, 'coverage/translation'):
            prepare_sentence_insertions(self.root, missing_translation, report)

    def test_unknown_or_multiple_reading_blanks_are_not_silently_left_visible(self):
        for english in ('_____ Later, the rate rose.', '(41)____ and (42)____ Later, the rate rose.'):
            with self.subTest(english=english):
                self.make_source(english=english)
                with self.assertRaisesRegex(ValueError, 'numbered gap'): self.import_card()

    def test_structured_answer_file_is_watched_during_matching(self):
        from anki_pipeline.match_forms import card_match_forms
        def changed_source(value):
            self.structured.write_bytes(self.structured.read_bytes() + b' ')
            return card_match_forms(value)
        with patch('anki_pipeline.exam_library.card_match_forms', side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, '来源发生变化'): self.import_card()


class AvailableSentenceInsertionCorpusTests(unittest.TestCase):
    def test_all_33_gaps_reuse_50_complete_approved_option_sentences_with_exact_offsets(self):
        root = Path(__file__).resolve().parents[2] / 'exam-library'
        stage = root / 'data/staging/codex-translations-v1'
        if not (stage / 'index/manifest.json').is_file():
            self.skipTest('The local immutable 44-paper corpus is unavailable')
        source, index = load_codex_exam_index(stage)
        by_id = {row['id']: row for row in source}
        completions, watched, report = prepare_sentence_insertions(root, source, index)
        self.assertEqual((len(completions), report['reused_option_sentences'], len(watched)), (33, 50, 8))
        self.assertEqual(report['new_translations'], 0)
        self.assertEqual(report['derived_semantic_review_status'], 'not_separately_marked')
        pure = 0
        for row in completions.values():
            with self.subTest(sentence_id=row['sentenceId']):
                self.assertNotIn('_', row['completedEnglish'])
                self.assertNotIn('_', row['translationZh'])
                self.assertEqual(row['englishHash'], sha(row['completedEnglish']))
                self.assertEqual(row['translationHash'], sha(row['translationZh']))
                self.assertEqual(row['optionChinese'], ''.join(
                    by_id[sid]['translationZh'] for sid in row['optionSentenceIds']))
                self.assertNotIn('status', row)
                remaining = row['originalEnglish'][:row['blankRange'][0]] + row['originalEnglish'][row['blankRange'][1]:]
                if not re.search(r'[A-Za-z]', remaining): pure += 1
                for match in re.finditer(r'[A-Za-z]+', row['completedEnglish']):
                    span = (match.start(), match.end())
                    stem = original_range(row, span)
                    option = insertion_option_source(row, span, by_id)
                    self.assertIsNotNone(stem or option)
                    original = row['originalEnglish'][slice(*stem)] if stem else option[0]['english'][slice(*option[1])]
                    self.assertEqual(original, match[0])
        self.assertEqual(pure, 19)
        self.assertTrue(all(sha(path.read_bytes()) == expected for path, expected in watched.items()))


if __name__ == '__main__':
    unittest.main()
