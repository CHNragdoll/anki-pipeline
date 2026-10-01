"""User-facing source hierarchy follows original evidence, never question ranges."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.source_paths import display_source_path, prepare_source_paths
from tests.test_codex_exam_index import sha, write_json
from tests import test_option_context


class SourcePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'data/sources/exam-library/structured/papers/kaoyan/2000-01.json'
        self.paper_id = 'kaoyan:2000-01'
        self.paper = {'id': self.paper_id, 'title': '2000年考研英语（统一卷）', 'blocks': [
            {'id': 'section', 'text': 'Section II Reading Comprehension'},
            {'id': 'part', 'text': 'Part A'}, {'id': 'text5', 'text': 'Text 5'},
            {'id': 'body', 'text': 'Body sentence.'}, {'id': 'stem', 'text': '28. Why?'},
            {'id': 'option', 'text': 'A. Candidate answer.'},
            {'id': 'partB', 'text': 'Part B'}, {'id': 'bank', 'text': 'Shared answer.'}],
            'questions': [{'id': 'q-28-1', 'number': '28', 'sourceBlocks': ['stem', 'option']},
                {'id': 'q-41-1', 'number': '41', 'sourceBlocks': ['bank'], 'context': {'choiceBank': [
                    {'id': self.paper_id + ':part-b:A', 'text': 'Shared answer.'}]}}],
            'toc': [{'kind': 'section', 'id': 'section', 'label': 'Section II Reading Comprehension', 'parentId': None},
                {'kind': 'section', 'id': 'part', 'label': 'Part A', 'parentId': 'section'},
                {'kind': 'section', 'id': 'text5', 'label': 'Text 5', 'parentId': 'part'},
                {'kind': 'question', 'id': 'q-28-1', 'label': '第28题', 'parentId': 'text5'},
                {'kind': 'section', 'id': 'partB', 'label': 'Part B', 'parentId': 'section'}]}
        write_json(self.path, self.paper)

    def row(self, block='stem', *, kind='question_prompt', source='2000年考研英语（统一卷）',
            qid=None, paragraph=None, english='28. Why?'):
        return {'id': self.paper_id + ':p:' + block + ':0', 'paperId': self.paper_id, 'kind': kind,
            'paragraphId': paragraph or self.paper_id + ':p:' + block, 'sourceEnglish': english,
            'sourcePath': source, 'sourceBlockIds': [self.paper_id + ':' + block],
            'context': {'questionId': qid} if qid else {}, 'reviewedContentHash': sha(english)}

    def test_question_option_and_body_have_original_full_hierarchy_without_mutating_sources(self):
        rows = [self.row(), self.row('option', kind='answer_option', qid=self.paper_id + ':q-28-1',
                    paragraph=self.paper_id + ':q-28-1:A', english='Candidate answer.'),
                self.row('body', kind='reading', english='Body sentence.')]
        original = copy.deepcopy(rows)
        records, questions, watched, report = prepare_source_paths(self.root, rows)
        prefix = '2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Part A ➫ Text 5'
        self.assertEqual(records[rows[0]['id']]['sourcePath'], prefix + ' ➫ 第28题')
        self.assertEqual(records[rows[1]['id']]['sourcePath'], prefix + ' ➫ 第28题 ➫ 选项A')
        self.assertEqual(records[rows[2]['id']]['sourcePath'], prefix)
        self.assertEqual(display_source_path(records[rows[0]['id']],
            question_record=questions[self.paper_id + ':q-28-1'], option_label='C'), prefix + ' ➫ 第28题 ➫ 选项C')
        self.assertEqual(rows, original)
        self.assertEqual(watched[self.path.resolve()], sha(self.path.read_bytes()))
        self.assertEqual(report['internal_ids_displayed'], 0)

    def test_missing_original_layers_are_not_invented_and_question_numbers_do_not_define_text(self):
        self.paper['toc'][2]['parentId'] = 'section'
        self.paper['blocks'].remove(self.paper['blocks'][1]); self.paper['toc'].pop(1)
        self.paper['questions'][0]['number'] = '99'
        write_json(self.path, self.paper)
        row = self.row()
        records, _, _, _ = prepare_source_paths(self.root, [row])
        self.assertEqual(records[row['id']]['sourcePath'],
            '2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Text 5 ➫ 第99题')

    def test_pdf_shared_bank_keeps_option_identity_without_claiming_single_question(self):
        row = self.row('unused', kind='answer_option', qid=self.paper_id + ':q-41-1',
                       paragraph=self.paper_id + ':q-41-1:A', english='Shared answer.')
        row['sourceBlockIds'] = []
        row['context'].update(sourceOptionId=self.paper_id + ':part-b:A',
                              reflowBlockIds=[self.paper_id + ':bank'])
        records, _, _, _ = prepare_source_paths(self.root, [row])
        self.assertEqual(records[row['id']]['sourcePath'],
            '2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Part B ➫ 选项A')
        self.assertNotIn('第41题', records[row['id']]['sourcePath'])

    def test_missing_old_block_reuses_exact_block_or_reviewed_path_evidence(self):
        exact = self.row('old', kind='reading', english='Body sentence.')
        known = self.row('removed', kind='reading', english='Changed text.',
            source='2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Part B')
        records, _, _, _ = prepare_source_paths(self.root, [exact, known])
        self.assertEqual(records[exact['id']]['components'][-1], 'Text 5')
        self.assertEqual(records[known['id']]['components'][-1], 'Part B')
        self.assertEqual(records[known['id']]['evidence'][0]['kind'], 'reviewed_source_path')

    def test_inline_heading_bank_uses_exact_printed_label_and_heading_text(self):
        self.paper['blocks'][-1]['text'] = 'A. First heading B. Second heading C. Last heading'
        write_json(self.path, self.paper)
        row = self.row('bank', kind='heading_option', english='Second heading')
        row['context']['optionLabel'] = 'B'
        records, _, _, _ = prepare_source_paths(self.root, [row])
        self.assertEqual(records[row['id']]['sourcePath'],
            '2000年考研英语（统一卷） ➫ Section II Reading Comprehension ➫ Part B ➫ 选项B')
        row['context']['optionLabel'] = 'C'
        records, _, _, _ = prepare_source_paths(self.root, [row])
        self.assertIsNone(records[row['id']]['optionLabel'])

    def test_heading_parent_or_question_block_disagreement_fails_closed(self):
        for change in ('label', 'cycle', 'question'):
            with self.subTest(change=change):
                value = copy.deepcopy(self.paper)
                if change == 'label': value['toc'][2]['label'] = 'Text 7'
                if change == 'cycle': value['toc'][1]['parentId'] = 'text5'
                if change == 'question': value['toc'][3]['parentId'] = 'partB'
                write_json(self.path, value)
                with self.assertRaises(ValueError): prepare_source_paths(self.root, [self.row()])


class SourcePathIntegrationTests(unittest.TestCase):
    def test_completed_owner_and_wrong_candidates_show_same_unique_hierarchy(self):
        fixture = test_option_context.OptionContextTests('test_candidate_context_ranges_identity_translation_and_raw_frequency')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        paper = json.loads(fixture.structured.read_text())
        paper['title'] = '2026年考研英语一'
        paper['blocks'] = [{'id': 'section', 'text': 'Section II Reading Comprehension'},
            {'id': 'part', 'text': 'Part A'}, {'id': 'text', 'text': 'Text 1'}, *paper['blocks']]
        paper['toc'] = [
            {'id': 'section', 'kind': 'section', 'label': 'Section II Reading Comprehension', 'parentId': None},
            {'id': 'part', 'kind': 'section', 'label': 'Part A', 'parentId': 'section'},
            {'id': 'text', 'kind': 'section', 'label': 'Text 1', 'parentId': 'part'},
            {'id': 'q-21-1', 'kind': 'question', 'label': '第21题', 'parentId': 'text'}]
        write_json(fixture.structured, paper)
        # Structured evidence is independently pinned in the completion sidecar.
        payload = json.loads(fixture.sidecar.read_text())
        payload['rows'][0]['structuredPaperHash'] = sha(fixture.structured.read_bytes())
        write_json(fixture.sidecar, payload)
        review = json.loads(fixture.sidecar.with_suffix('.review.json').read_text())
        review['sidecarSha256'] = sha(fixture.sidecar.read_bytes())
        write_json(fixture.sidecar.with_suffix('.review.json'), review)
        values, report = fixture.import_word()
        prefix = '2026年考研英语一 ➫ Section II Reading Comprehension ➫ Part A ➫ Text 1 ➫ 第21题 ➫ 选项'
        self.assertEqual([row['source'] for row in values[0]['examples']], [prefix + 'C', prefix + 'A'])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 3)
        self.assertEqual(report['source_paths']['separator'], '➫')


class RealSourcePathTests(unittest.TestCase):
    def test_all_44_papers_and_2000_questions_27_to_30_use_evidenced_paths(self):
        root = Path(__file__).resolve().parents[2] / 'exam-library'
        if not root.exists(): self.skipTest('Reviewed corpus not available')
        rows, _ = load_codex_exam_index(root / 'data/staging/codex-translations-v1')
        records, questions, _, report = prepare_source_paths(root, rows)
        self.assertEqual(report['papers'], 44)
        self.assertEqual(report['source_sentences'], 17755)
        self.assertEqual(report['sentences_with_title_only'], 0)
        for record in records.values():
            self.assertNotIn('kaoyan:', record['sourcePath'])
            self.assertNotIn(' · ', record['sourcePath'])
            self.assertTrue(record['evidence'])
            if record['kind'] in {'passage_option', 'heading_option'}:
                self.assertIsNotNone(record['optionLabel'])
        for number in range(27, 31):
            qid = 'kaoyan:2000-01:q-' + str(number) + '-1'
            self.assertEqual(questions[qid]['components'], ['2000年考研英语（统一卷）',
                'Section II Reading Comprehension', 'Part A', 'Text 5', '第' + str(number) + '题'])
            for letter in 'ABCD':
                record = records[qid + ':' + letter + ':new:0']
                self.assertEqual(record['sourcePath'], ' ➫ '.join(questions[qid]['components']) + ' ➫ 选项' + letter)
