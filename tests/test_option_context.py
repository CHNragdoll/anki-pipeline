"""Candidate context changes display without changing original option evidence."""
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
from anki_pipeline.option_context import context_target_ranges, prepare_option_contexts
from anki_pipeline.packaging import _fields
from anki_pipeline.reading_completion import load_reading_completions, prepare_reading_completions
from tests.test_codex_exam_index import record, sha, write_fixture, write_json
from tests.test_packaging import card


class OptionContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'staging'
        self.sidecar = self.root / 'reading-completions.json'
        self.structured = self.root / 'data/sources/exam-library/structured/papers/kaoyan/2026-01.json'
        self.qid = 'kaoyan:2026-01:q-21-1'
        self.stem = 'The rate indicates ____.'
        self.options = {'A': 'lower rate.', 'B': 'high', 'C': 'higher rate.', 'D': 'lower standards.'}
        self.create_source()

    def create_source(self, *, stem=None, multipart=False, option_parts=False, kind='reading'):
        self.stem = stem or self.stem
        stem_id = 'kaoyan:2026-01:p:stem'
        prompt = record(identifier=stem_id, english=self.stem, translation='这个比率表明____。',
            kind='question_prompt', context={'sourcePath': 'Reading',
                'sourceBlockIds': ['kaoyan:2026-01:b-1']})
        pairs = [prompt]
        if multipart:
            text = '21. First context. ' + self.stem
            prompt[0].update(sourceEnglish=text, filledEnglish=text, sourceHash=sha(text))
            prompt[1]['sourceHash'] = sha(text)
            prompt[0]['sentences'], prompt[1]['sentences'] = [], []
            for n, (english, chinese) in enumerate([('21.', '21.'), ('First context.', '前文。'),
                                                    (self.stem, '这个比率表明____。')]):
                start = text.index(english)
                sid = stem_id + ':' + str(n)
                prompt[0]['sentences'].append({'id': sid, 'start': start, 'end': start+len(english),
                                               'english': english, 'clozeAnswers': []})
                prompt[1]['sentences'].append({'id': sid, 'englishHash': sha(english),
                    'translationZh': chinese, 'alignments': [{'en': [0, 2], 'zh': [[0, 2]],
                                                            'relation': 'equivalent'}]})
        if option_parts:
            self.options['A'] = 'Lower rate. Another rate.'
        for letter, english in self.options.items():
            pair = record(identifier=self.qid + ':' + letter, english=english, translation='选项译文。',
                kind='answer_option', context={'questionId': self.qid,
                    'sourceBlockIds': ['kaoyan:2026-01:b-2']},
                alignments=[{'en': [0, 2], 'zh': [[0, 2]], 'relation': 'equivalent'}])
            if option_parts and letter == 'A':
                pair[0]['sentences'], pair[1]['sentences'] = [], []
                for n, text in enumerate(['Lower rate.', 'Another rate.']):
                    start = english.index(text); sid = self.qid + ':A:' + str(n)
                    pair[0]['sentences'].append({'id': sid, 'start': start, 'end': start+len(text),
                                                'english': text, 'clozeAnswers': []})
                    pair[1]['sentences'].append({'id': sid, 'englishHash': sha(text),
                        'translationZh': '选项译文。', 'alignments': [{'en': [0, 2], 'zh': [[0, 2]],
                                                                  'relation': 'equivalent'}]})
            pairs.append(pair)
        write_fixture(self.stage, records={'2026-01': pairs})
        write_json(self.structured, {'id': 'kaoyan:2026-01', 'blocks': [
            {'id': 'b-1', 'questionId': 'q-21-1'}, {'id': 'b-2', 'questionId': 'q-21-1'}],
            'questions': [{'id': 'q-21-1', 'number': '21', 'labels': [{'kind': kind}],
                'sourceBlocks': ['b-1', 'b-2'], 'stem': 'Different source layout ____',
                'answer': {'status': 'explicit', 'value': 'C', 'externalSource': {
                    'url': 'https://example.test/answers', 'capturedAt': '2026-10-01', 'answerToken': '21-C'}},
                'options': [{'label': letter + '.', 'text': text} for letter, text in self.options.items()]}]})
        rows, report = load_codex_exam_index(self.stage, allow_partial=True)
        payload, _ = prepare_reading_completions(self.root, rows, report)
        for row in payload['rows']:
            row.update(status='reviewed', translationZh='这个比率表明比率更高。')
        write_json(self.sidecar, payload)
        write_json(self.sidecar.with_suffix('.review.json'), {
            'schema': 'reading-question-completion-review.v1', 'status': 'approved',
            'sidecarSha256': sha(self.sidecar.read_bytes()), 'indexManifestHash': payload['indexManifestHash'],
            'inputManifestHash': payload['inputManifestHash'],
            'reviewedSentenceIds': [row['sentenceId'] for row in payload['rows']],
            'evidenceFiles': {'test.json': sha('review')}})

    def import_word(self, word='rate', maximum=0):
        return library_examples(self.root, [card('test-card', word=word, audio='')],
            'http://localhost:8765', 'latex', maximum, sentence_source='codex',
            codex_index_root=self.stage, allow_partial_codex=True, reading_completion_path=self.sidecar)

    def test_candidate_context_ranges_identity_translation_and_raw_frequency(self):
        values, report = self.import_word()
        examples = values[0]['examples']
        candidate = next(row for row in examples if row.get('option_context', {}).get('candidateOptionLabel') == 'A')
        self.assertEqual(candidate['text'], 'The rate indicates lower rate.')
        self.assertEqual(candidate['matched_english_ranges'], [[25, 29]])
        self.assertEqual(candidate['cloze_answers'][0]['word'], 'lower rate')
        self.assertEqual(candidate['translation'], '题干：这个比率表明［选项 A］。\n选项 A：选项译文。')
        self.assertFalse(candidate['option_context']['isCorrectCandidate'])
        self.assertEqual(candidate['option_context']['correctOptionLabel'], 'C')
        self.assertIn('第21题 ➫ 选项A', candidate['source'])
        self.assertEqual(candidate['translation_alignment']['alignments'], [])
        self.assertEqual(candidate['english_hash'], sha(candidate['text']))
        query = parse_qs(urlsplit(candidate['full_paper_url']).query)
        self.assertEqual(query['anki-codex-sentence'], [self.qid + ':A:0'])
        self.assertEqual(query['anki-codex-hash'], [sha(self.options['A'])])
        self.assertEqual(json.loads(query['anki-codex-en'][0]), [[6, 10]])
        self.assertEqual(candidate['source_target_refs'][0]['ranges'], [[6, 10]])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 3)
        self.assertEqual(report['option_contexts']['deduplicated_correct_option_examples'], 1)
        self.assertFalse(any(row.get('option_context', {}).get('isCorrectCandidate') for row in examples))
        self.assertEqual(examples[0]['deduplicated_option_contexts'][0]['sentence_id'], self.qid + ':C:0')
        self.assertIn('第21题 ➫ 选项C', examples[0]['source'])
        self.assertEqual(self.import_word(maximum=1)[0][0]['exam_frequency'], values[0]['exam_frequency'])

    def test_only_deduplicated_correct_link_frames_both_printed_parts(self):
        values, _ = self.import_word()
        dual_count = 0
        for example in values[0]['examples']:
            if not (example.get('reading_completion') or example.get('option_context')):
                continue
            dual = bool(example.get('deduplicated_option_contexts'))
            dual_count += dual
            for field in ('latex_url', 'full_paper_url'):
                params = parse_qs(urlsplit(example[field]).query)
                if not dual:
                    self.assertNotIn('anki-codex-context', params)
                    continue
                self.assertEqual(len(params['anki-codex-context']), 1)
                context = json.loads(params['anki-codex-context'][0])
                self.assertEqual(context['questionId'], self.qid)
                label = context['optionLabel']
                self.assertEqual(label, 'C')
                self.assertEqual(context['stem'][0]['englishHash'], sha(self.stem))
                self.assertEqual(context['option'][0]['englishHash'], sha(self.options[label]))
                self.assertEqual(context['option'][0]['id'], self.qid + ':' + label + ':0')
        self.assertEqual(dual_count, 1)

    def test_added_stem_words_do_not_make_candidate_examples_and_bare_words_stay_hidden(self):
        values, _ = self.import_word('indicates')
        self.assertFalse(any('option_context' in row for row in values[0]['examples']))
        values, report = self.import_word('high')
        self.assertEqual(values[0]['examples'], [])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 1)
        self.assertEqual(report['skipped_standalone_word_option_matches'], 1)

    def test_restored_stem_targets_are_visible_without_changing_source_matches(self):
        values, _ = self.import_word()
        candidate = next(row for row in values[0]['examples']
                         if row.get('option_context', {}).get('candidateOptionLabel') == 'A')
        before = copy.deepcopy(values[0])
        fields = _fields({**values[0], 'examples': [candidate]}, None, 0)[0]
        rendered = fields['Examples']
        self.assertIn('The <mark class="target-word">rate</mark> indicates', rendered)
        self.assertIn('<u class="cloze-answer" data-blank-number="21">lower '
                      '<mark class="target-word">rate</mark></u>', rendered)
        self.assertEqual(rendered.count('<mark class="target-word">'), 2)
        self.assertNotIn('<mark', rendered.split('class="example-translation"', 1)[1])
        self.assertEqual(values[0], before)
        self.assertEqual(candidate['matched_english_ranges'], [[25, 29]])
        self.assertEqual(candidate['source_target_refs'][0]['ranges'], [[6, 10]])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 3)

    def test_restored_stem_marking_keeps_word_boundaries_and_declared_forms(self):
        self.create_source(stem='The rate and rates, unrated standards indicate ____.')
        values, _ = self.import_word()
        candidate = next(row for row in values[0]['examples']
                         if row.get('option_context', {}).get('candidateOptionLabel') == 'A')
        values[0]['word_forms'] = '复数：rates\n过去式：rated'
        fields = _fields({**values[0], 'examples': [candidate]}, None, 0)[0]
        rendered = fields['Examples']
        self.assertIn('<mark class="target-word">rate</mark> and '
                      '<mark class="target-word">rates</mark>, unrated', rendered)
        self.assertEqual(rendered.count('<mark class="target-word">'), 3)

    def test_original_pinned_occurrence_selection_stays_selective(self):
        item = card('pinned', audio='')
        item['examples'] = [{'text': 'The rate and rate.', 'source': '', 'translation': '比率。',
                             'matched_english_ranges': [[13, 17]]}]
        rendered = _fields(item, None, 0)[0]['Examples']
        self.assertIn('The rate and <mark class="target-word">rate</mark>.', rendered)
        self.assertEqual(rendered.count('<mark class="target-word">'), 1)

    def test_approved_joined_translation_replaces_only_candidate_output(self):
        rows, index_report = load_codex_exam_index(self.stage, allow_partial=True)
        completions, _, _ = load_reading_completions(self.root, self.sidecar, rows, index_report)
        before, _, _, registry = prepare_option_contexts(self.root, rows, index_report, completions)
        candidate_id = self.qid + ':A:0'
        approved = '这个比率表明比率较低。'
        joined_path = self.root / 'reading-option-translations-v1.json'
        with patch('anki_pipeline.option_translation.load_option_translations',
                   return_value=({candidate_id: approved}, {joined_path: sha(approved)},
                                 {'new_translations': 1})) as loader:
            after, watched, report, current_registry = prepare_option_contexts(
                self.root, rows, index_report, completions, joined_translation_path=joined_path)
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(loader.call_args.args[0], joined_path)
        self.assertEqual(loader.call_args.args[2], index_report)
        self.assertEqual(after[candidate_id]['translationZh'], approved)
        self.assertEqual(after[candidate_id]['translationHash'], sha(approved))
        self.assertTrue(after[candidate_id]['newTranslationAuthored'])
        self.assertEqual(after[candidate_id]['translation_alignment'], {
            'schema': 'codex-sentence-alignment.v1', 'englishHash': before[candidate_id]['englishHash'],
            'translationHash': sha(approved), 'alignments': []})
        self.assertEqual(after[self.qid + ':C:0'], before[self.qid + ':C:0'])
        self.assertEqual(report['new_translations'], 1)
        self.assertEqual(watched[joined_path], sha(approved))
        self.assertEqual(current_registry[0]['stemSentenceRefs'], registry[0]['stemSentenceRefs'])
        with patch('anki_pipeline.option_translation.load_option_translations',
                   side_effect=ValueError('stale approved evidence')):
            with self.assertRaisesRegex(ValueError, 'stale approved evidence'):
                prepare_option_contexts(self.root, rows, index_report, completions,
                                        joined_translation_path=joined_path)

    def test_no_blank_keeps_question_plus_option_without_inferred_fill(self):
        self.create_source(stem='Why does the rate rise?')
        values, _ = self.import_word()
        candidates = [row for row in values[0]['examples'] if 'option_context' in row]
        self.assertEqual(len(candidates), 2)
        candidate = candidates[0]
        self.assertEqual(candidate['text'], 'Why does the rate rise?\n\nlower rate.')
        self.assertEqual(candidate['matched_english_ranges'], [[31, 35]])
        self.assertEqual(candidate['cloze_answers'][0]['word'], 'lower rate')
        self.assertEqual(candidate['translation_scope'], 'separate_approved_question_and_candidate_translations')
        before = copy.deepcopy(values[0])
        fields, _, _ = _fields(values[0], None, 0)
        html = fields['Examples']
        self.assertIn('rise?<br><u class="cloze-answer" data-blank-number="21">lower ', html)
        self.assertNotIn('rise?<br><br>', html)
        self.assertIn('题干：这个比率表明［选项 A］。<br>选项 A：选项译文。', html)
        self.assertNotIn('aligned-translation-target', html)
        self.assertEqual(values[0], before)
        ordinary = copy.deepcopy(candidate)
        ordinary.pop('option_context')
        ordinary_html = _fields({**values[0], 'examples': [ordinary]}, None, 0)[0]['Examples']
        self.assertIn('rise?<br><br><u class="cloze-answer"', ordinary_html)

    def test_complete_multi_sentence_question_and_option_with_sentence_local_source_jump(self):
        self.create_source(multipart=True, option_parts=True)
        values, _ = self.import_word()
        candidate = next(row for row in values[0]['examples'] if row['sentence_id'] == self.qid + ':A:1')
        self.assertEqual(candidate['text'], 'First context. The rate indicates Lower rate. Another rate.')
        self.assertEqual(candidate['matched_english_ranges'], [[54, 58]])
        self.assertEqual(len(candidate['option_context']['stemSentenceRefs']), 3)
        self.assertEqual(len(candidate['option_context']['optionSentenceRefs']), 2)
        query = parse_qs(urlsplit(candidate['latex_url']).query)
        self.assertEqual(query['anki-codex-sentence'], [self.qid + ':A:1'])
        self.assertEqual(json.loads(query['anki-codex-en'][0]), [[8, 12]])
        correct = next(row for row in values[0]['examples'] if row.get('option_context', {}).get('isCorrectCandidate'))
        self.assertEqual(correct['translation'], '前文。这个比率表明比率更高。')
        self.assertEqual(correct['translation_scope'], 'approved_context_with_reviewed_correct_completion')

    def test_cloze_or_matching_banks_are_not_bound_to_reading_stems(self):
        for kind in ('cloze', 'matching'):
            with self.subTest(kind=kind):
                self.create_source(kind=kind)
                values, report = self.import_word()
                self.assertFalse(any('option_context' in row for row in values[0]['examples']))
                self.assertEqual(report['option_contexts']['contextualized_option_paragraphs'], 0)

    def test_raw_option_exclusion_removes_candidate_but_does_not_shift_source_range(self):
        source = next(row for row in load_codex_exam_index(self.stage, allow_partial=True)[0]
                      if row['id'] == self.qid + ':A:0')
        write_json(self.stage / 'targets/occurrence-exclusions.json', {
            'schema': 'codex-anki-occurrence-exclusions.v1', 'rangeUnit': 'sentence-codepoints',
            'exclusions': [{'sentenceId': source['id'], 'cardId': 'test-card', 'paperId': source['paperId'],
                'englishHash': source['englishHash'], 'sourceHash': source['sourceHash'],
                'word': 'rate', 'form': 'rate', 'en': [6, 10], 'reason': 'Reviewed source exclusion'}]})
        values, report = self.import_word()
        self.assertFalse(any(row['sentence_id'] == source['id'] for row in values[0]['examples']))
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 2)
        self.assertEqual(report['excluded_homograph_occurrences'], 1)

    def test_missing_ambiguous_or_stale_provenance_fails_closed(self):
        baseline = json.loads(self.structured.read_text())
        for change in ('answer', 'label', 'block', 'option', 'token', 'number'):
            with self.subTest(change=change):
                value = copy.deepcopy(baseline); question = value['questions'][0]
                if change == 'answer': question['answer']['value'] = 'A/C'
                if change == 'label': question['options'].append(question['options'][0])
                if change == 'block': value['blocks'][0]['questionId'] = 'q-22-1'
                if change == 'option': question['options'][0]['text'] = 'Changed rate.'
                if change == 'token': question['answer']['externalSource']['answerToken'] = '22-C'
                if change == 'number':
                    question['number'] = '22'
                    question['answer']['externalSource']['answerToken'] = '22-C'
                write_json(self.structured, value)
                rows, report = load_codex_exam_index(self.stage, allow_partial=True)
                with self.assertRaises(ValueError):
                    prepare_option_contexts(self.root, rows, report, {})
        write_json(self.structured, baseline)


class RealOptionContextTests(unittest.TestCase):
    def test_all_880_questions_and_3251_eligible_options_keep_original_evidence(self):
        root = Path(__file__).resolve().parents[2] / 'exam-library'
        if not root.exists(): self.skipTest('Reviewed corpus not available')
        rows, report = load_codex_exam_index(root / 'data/staging/codex-translations-v1')
        completed, _, _ = load_reading_completions(root,
            Path(__file__).resolve().parents[1] / 'data/reading-completions-v1.json', rows, report)
        contexts, _, counts, registry = prepare_option_contexts(root, rows, report, completed)
        self.assertEqual(counts['reading_questions'], 880)
        self.assertEqual(counts['contextualized_option_paragraphs'], 3251)
        self.assertEqual(counts['bare_reading_option_sentences_skipped'], 269)
        by_id = {row['id']: row for row in rows}
        for context in registry:
            self.assertNotIn('_', context['completedEnglish'])
            self.assertEqual(context['englishHash'], sha(context['completedEnglish']))
            self.assertEqual(context['translationHash'], sha(context['translationZh']))
            self.assertEqual(context['translation_alignment']['alignments'], [])
            self.assertEqual(context['isCorrectCandidate'],
                             context['candidateOptionLabel'] == context['correctOptionLabel'])
            self.assertEqual(context['answerSource']['answerToken'],
                             context['answerNumber'] + '-' + context['correctOptionLabel'])
            for ref in context['optionSentenceRefs']:
                source = by_id[ref['sentenceId']]
                ranges = [(m.start(), m.end()) for m in re.finditer(r'[A-Za-z]+', source['english'])]
                projected = context_target_ranges(context, source, ranges)
                self.assertEqual([context['completedEnglish'][slice(*span)] for span in projected],
                                 [source['english'][slice(*span)] for span in ranges])
        ambition = contexts['kaoyan:2000-01:q-28-1:A:new:0']
        self.assertIn('The last sentence of the first paragraph', ambition['completedEnglish'])
        self.assertIn('customary of the educated', ambition['completedEnglish'])
        self.assertFalse(ambition['isCorrectCandidate'])
