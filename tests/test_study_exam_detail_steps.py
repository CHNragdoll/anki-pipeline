"""Regression checks for shared text/reflow and scan-backed solution projection."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from anki_pipeline.study_exam_source import read_bank, _omit_repeated_choice_key, _halfwidth_display_text, _omit_page_continuation


class DetailedSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.structured = self.root / 'exam-library/structured'
        (self.structured / 'papers/math3').mkdir(parents=True)
        self.clip = self.root / 'math3-detailed-steps/clips/detail.png'
        self.clip.parent.mkdir(parents=True)
        self.clip.write_bytes(b'\x89PNG\r\n\x1a\nsource solution pixels')
        self.question_image = self.root / 'question.png'
        self.question_image.write_bytes(b'\x89PNG\r\n\x1a\ncomplete question and all options')
        self.database = self.root / 'source.sqlite3'
        self.answer = {'value': 'B', 'solution': '旧完整文字解答', 'status': 'explicit',
                       'detailedSteps': {'status': 'source-matched', 'sourceFilename': '解析<&>.pdf',
                                        'sourceSha256': '1' * 64, 'conflict': '原卷 B，详解 C<&>',
                                        'segments': [{'src': '../../../../math3-detailed-steps/clips/detail.png',
                                                      'width': 100, 'height': 200, 'physicalPage': 1,
                                                      'sha256': hashlib.sha256(self.clip.read_bytes()).hexdigest()}]}}
        self.raw = {'id': 'q-1-1', 'number': '1', 'questionType': 'single_choice',
                    'sectionTitle': '一、选择题', 'stem': '完整题目',
                    'answer': copy.deepcopy(self.answer),
                    'options': [{'label': letter + '.', 'sourceLabel': '（' + letter + '）',
                                 'text': letter + '原选项', 'sourceOrder': index}
                                for index, letter in enumerate('ABCD', 1)]}
        with closing(sqlite3.connect(self.database)) as db, db:
            db.executescript('''
                CREATE TABLE papers(id TEXT,category TEXT,kind TEXT,title TEXT,year INTEGER,ordinal INTEGER,reader_path TEXT,raw_json TEXT);
                CREATE TABLE questions(id TEXT,paper_id TEXT,ordinal INTEGER,number TEXT,question_type TEXT,raw_json TEXT,in_bank INTEGER DEFAULT 1);
                CREATE TABLE answers(question_id TEXT,status TEXT,source_document_id TEXT,source_blocks_json TEXT,raw_json TEXT);
                CREATE TABLE source_blocks(id TEXT,paper_id TEXT,local_id TEXT,ordinal INTEGER,content_html TEXT,raw_json TEXT,role TEXT);
                CREATE TABLE question_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);
                CREATE TABLE context_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);
            ''')
            db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?)',
                       ('math3:2019-questions', 'math3', 'questions', '2019 数三', 2019, 1,
                        'papers/math3/2019-questions.htm', '{}'))
            db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?)',
                       ('math3:2019-questions:q-1-1', 'math3:2019-questions', 1, '1',
                        'single_choice', json.dumps(self.raw), 1))
            db.execute('INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?)',
                       ('stem', 'math3:2019-questions', 'b-1', 1,
                        '<p>完整题目</p><pre class="tex-source">alternate TeX</pre>', '{}', 'question'))
            db.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',
                       ('math3:2019-questions:q-1-1', 'stem', 1))
            db.execute('INSERT INTO source_blocks VALUES(?,?,?,?,?,?,?)',
                       ('answer', 'math3:2019-answers', 'a-1', 1,
                        '<p>原卷 B 及原完整推导</p>', '{}', 'answer'))
            db.execute('INSERT INTO answers VALUES(?,?,?,?,?)',
                       ('math3:2019-questions:q-1-1', 'explicit', 'math3:2019-answers', '["a-1"]',
                        json.dumps(self.answer)))

    def tearDown(self):
        self.temp.cleanup()

    def read(self):
        return read_bank(self.database, 'math3', structured_root=self.structured,
                         asset_root=self.root, type_labels={'free_response': '解答题'})

    def save_raw(self, raw):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE questions SET raw_json=?', (json.dumps(raw),))
            db.execute('UPDATE answers SET raw_json=?', (json.dumps(raw['answer']),))

    def test_details_follow_reflow_keep_original_answer_and_source_identity(self):
        before = self.database.read_bytes()
        snapshot = self.read()
        row = snapshot['questions'][0]
        self.assertEqual(row['key'], 'math3:2019-questions:q-1-1')
        self.assertIn('原卷 B 及原完整推导', row['answer'])
        self.assertIn('步骤详解', row['answer'])
        self.assertIn('解析&lt;&amp;&gt;.pdf', row['answer'])
        self.assertIn('来源差异：原卷 B，详解 C&lt;&amp;&gt;', row['answer'])
        self.assertNotIn('tex-source', row['question'])
        self.assertNotIn('detail.png', row['answer'])
        self.assertEqual(row['answer'].count('class="exam-detail-step"'), 1)
        self.assertEqual(row['source_record']['reflow_original_question'], self.raw)
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(len(snapshot['resources']), 1)
        self.assertEqual(next(iter(snapshot['resources'].values()))['sha256'],
                         hashlib.sha256(self.clip.read_bytes()).hexdigest())

    def test_grouped_key_normalization_cannot_drop_new_detail_images(self):
        raw = copy.deepcopy(self.raw)
        raw['id'], raw['number'] = 'q-2-1', '2'
        raw['answer'].pop('detailedSteps')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?)',
                       ('math3:2019-questions:q-2-1', 'math3:2019-questions', 2, '2',
                        'single_choice', json.dumps(raw), 1))
            db.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',
                       ('math3:2019-questions:q-2-1', 'stem', 1))
            db.execute('INSERT INTO answers VALUES(?,?,?,?,?)',
                       ('math3:2019-questions:q-2-1', 'explicit', 'math3:2019-answers', '["a-1"]',
                        json.dumps(raw['answer'])))
        row = self.read()['questions'][0]
        self.assertIn('旧完整文字解答', row['answer'])
        self.assertIn('步骤详解', row['answer'])
        self.assertEqual(row['answer'].count('class="exam-detail-step"'), 1)
        self.assertIn('原卷 B 及原完整推导', row['source_record']['answer_blocks'][0]['content_html'])

    def latex_detail(self):
        return {'status': 'source-matched', 'sourceFilename': '步骤<&>.pdf',
                'sourceSha256': '2' * 64, 'physicalPages': [2, 3],
                'verification': {'method': 'source-cross-check'},
                'paragraphs': [r'第一步：\(x < 1\)，并保留 A&B。',
                               r'第二步：\[\int_0^1 x\,dx=\frac12\]']}

    def test_verified_latex_takes_priority_without_loading_crop_resources(self):
        raw = copy.deepcopy(self.raw)
        raw['answer']['detailedLatex'] = self.latex_detail()
        # Missing image evidence must not be accessed when verified text exists.
        self.clip.unlink()
        self.save_raw(raw)
        before = self.database.read_bytes()
        snapshot = self.read()
        row = snapshot['questions'][0]
        self.assertIn('原卷 B 及原完整推导', row['answer'])
        self.assertNotIn('步骤&lt;&amp;&gt;.pdf', row['answer'])
        self.assertNotIn('exam-detail-source', row['answer'])
        self.assertIn(r'\(\displaystyle x &lt; 1\)', row['answer'])
        self.assertIn(r'\[\displaystyle \int_0^1 x\,dx=\frac12\]', row['answer'])
        self.assertIn('A&amp;B', row['answer'])
        self.assertEqual(row['answer'].count('<h3>步骤详解</h3>'), 1)
        self.assertNotIn('<img', row['answer'])
        self.assertNotIn('来源差异：', row['answer'])
        self.assertEqual(snapshot['resources'], {})
        self.assertEqual(row['source_record']['reflow_original_question'], raw)
        self.assertEqual(self.database.read_bytes(), before)

    def test_verified_latex_alone_is_projected_after_reflow(self):
        raw = copy.deepcopy(self.raw)
        raw['answer'].pop('detailedSteps')
        raw['answer']['detailedLatex'] = self.latex_detail()
        raw['scanSource'] = False
        self.save_raw(raw)
        row = self.read()['questions'][0]
        self.assertIn('exam-detail-latex', row['answer'])
        self.assertNotIn('exam-scan-option-buttons', row['question'])
        self.assertEqual(row['source_record']['reflow_original_question'], raw)

    def make_detail_only_free_response(self, detail):
        raw = copy.deepcopy(self.raw)
        raw.update(questionType='free_response', sectionTitle='三、解答题', options=[])
        raw['answer'] = {'status': 'explicit', 'value': '', 'solution': '',
                         'detailedLatex': detail}
        self.save_raw(raw)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE questions SET question_type='free_response'")
            db.execute("UPDATE answers SET source_document_id=NULL,source_blocks_json='[]'")
        return raw

    def test_free_response_can_have_only_verified_latex_and_no_old_answer_block(self):
        raw = self.make_detail_only_free_response(self.latex_detail())
        row = self.read()['questions'][0]
        self.assertEqual(row['status'], 'available')
        self.assertEqual(row['type'], 'free_response')
        self.assertIn('exam-detail-latex', row['answer'])
        self.assertIn('第一步', row['answer'])
        self.assertEqual(row['source_record']['answer_blocks'], [])
        self.assertEqual(row['source_record']['reflow_original_question'], raw)

    def test_empty_free_response_cannot_use_invalid_latex_to_bypass_answer_guard(self):
        for detail in [None, {}, {'status': 'source-matched'}]:
            with self.subTest(detail=detail):
                self.make_detail_only_free_response(detail)
                with self.assertRaises(ValueError):
                    self.read()

    def test_latex_source_conflict_is_retained_and_escaped(self):
        raw = copy.deepcopy(self.raw)
        raw['answer']['detailedLatex'] = self.latex_detail()
        raw['answer']['detailedLatex']['conflict'] = '原卷 B，详解 C<&>'
        self.save_raw(raw)
        answer = self.read()['questions'][0]['answer']
        self.assertIn('<p class="exam-source-conflict">来源差异：原卷 B，详解 C&lt;&amp;&gt;</p>', answer)
        self.assertEqual(answer.count('来源差异：'), 1)
        raw['answer']['detailedLatex']['conflict'] = {'unsafe': 'object'}
        self.save_raw(raw)
        with self.assertRaisesRegex(ValueError, 'conflict must be text'):
            self.read()

    def latex_with_figure(self):
        figure = self.root / 'math3-detailed-latex/figures/geometry.png'
        figure.parent.mkdir(parents=True, exist_ok=True)
        figure.write_bytes(b'\x89PNG\r\n\x1a\nverified geometry diagram')
        detail = self.latex_detail()
        detail['figures'] = [{'src': '../../../../math3-detailed-latex/figures/geometry.png',
                              'sha256': hashlib.sha256(figure.read_bytes()).hexdigest(),
                              'width': 150, 'height': 120, 'physicalPage': 2,
                              'caption': '几何图<&>'}]
        return detail, figure

    def test_latex_geometry_figure_is_bound_to_source_bytes_and_keeps_caption(self):
        raw = copy.deepcopy(self.raw)
        detail, figure = self.latex_with_figure()
        raw['answer']['detailedLatex'] = detail
        self.clip.unlink()
        self.save_raw(raw)
        snapshot = self.read()
        answer = snapshot['questions'][0]['answer']
        self.assertIn('<figcaption>几何图&lt;&amp;&gt;</figcaption>', answer)
        self.assertIn('width="150" height="120"', answer)
        self.assertGreater(answer.index('<figure'), answer.index('第二步'))
        self.assertEqual(len(snapshot['resources']), 1)
        resource = next(iter(snapshot['resources'].values()))
        self.assertEqual(resource['sha256'], hashlib.sha256(figure.read_bytes()).hexdigest())
        self.assertNotIn('geometry.png', answer)
        self.assertNotIn('class="exam-detail-step"', answer)

    def test_latex_geometry_changed_bytes_and_unconfined_path_are_rejected(self):
        raw = copy.deepcopy(self.raw)
        detail, figure = self.latex_with_figure()
        raw['answer']['detailedLatex'] = detail
        self.save_raw(raw)
        figure.write_bytes(b'\x89PNG\r\n\x1a\ncorrupted diagram')
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            self.read()
        detail['figures'][0]['src'] = '../../../../question.png'
        self.save_raw(raw)
        with self.assertRaisesRegex(ValueError, 'approved clip roots'):
            self.read()

    def test_latex_geometry_metadata_requires_source_page_dimensions_and_digest(self):
        detail, _ = self.latex_with_figure()
        for key, invalid in [('src', ''), ('sha256', 'broken'), ('width', 0),
                             ('height', True), ('physicalPage', -1), ('caption', None)]:
            with self.subTest(key=key):
                raw = copy.deepcopy(self.raw)
                raw['answer']['detailedLatex'] = copy.deepcopy(detail)
                raw['answer']['detailedLatex']['figures'][0][key] = invalid
                self.save_raw(raw)
                with self.assertRaisesRegex(ValueError, 'figure metadata'):
                    self.read()

    def test_latex_missing_provenance_is_rejected_instead_of_crop_fallback(self):
        malformed = [[], {'status': 'pending'}]
        for key in ['sourceFilename', 'sourceSha256', 'physicalPages', 'verification', 'paragraphs']:
            value = self.latex_detail()
            value.pop(key)
            malformed.append(value)
        for key, invalid in [('sourceFilename', ' '), ('sourceSha256', 'wrong'),
                             ('paragraphs', []), ('paragraphs', [' ']),
                             ('physicalPages', []), ('physicalPages', [True]),
                             ('physicalPages', [0]), ('verification', [])]:
            value = self.latex_detail()
            value[key] = invalid
            malformed.append(value)
        for value in malformed:
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw['answer']['detailedLatex'] = value
                self.save_raw(raw)
                with self.assertRaisesRegex(ValueError, 'detailedLatex'):
                    self.read()

    def test_changed_clip_fails_without_silently_registering_new_evidence(self):
        self.clip.write_bytes(b'\x89PNG\r\n\x1a\nchanged pixels')
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            self.read()

    def test_detail_path_must_remain_in_approved_clip_trees(self):
        raw = copy.deepcopy(self.raw)
        raw['answer']['detailedSteps']['segments'][0]['src'] = '../../../../question.png'
        self.save_raw(raw)
        with self.assertRaisesRegex(ValueError, 'approved clip roots'):
            self.read()

    def test_malformed_detail_metadata_is_rejected(self):
        for value in [[], {'status': 'pending'}, {'status': 'source-matched', 'segments': []}]:
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw['answer']['detailedSteps'] = value
                self.save_raw(raw)
                with self.assertRaisesRegex(ValueError, 'detailed'):
                    self.read()

    def test_scan_question_retains_full_image_and_uses_shared_choice_nodes(self):
        raw = copy.deepcopy(self.raw)
        raw['scanSource'] = True
        raw['answer'].pop('detailedSteps')
        raw['answer']['detailSourceSegments'] = [{'sourcePage': 1}]
        for option in raw['options']:
            option.update(scanSource=True, sourceImages=['../../../../question.png'])
        self.save_raw(raw)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE source_blocks SET content_html=? WHERE id="stem"',
                       ('<img class="scan-crop" src="../../../../question.png" alt="原题含所有选项">',))
        snapshot = self.read()
        row = snapshot['questions'][0]
        self.assertIn('alt="原题含所有选项"', row['question'])
        self.assertIn('choices exam-scan-option-buttons', row['question'])
        self.assertEqual(row['question'].count('class="choice"'), 4)
        self.assertNotIn('原完整推导', row['question'])
        self.assertNotIn('步骤详解', row['question'])
        self.assertEqual(row['source_record']['question'], raw)
        self.assertEqual(len(snapshot['resources']), 1)

    def test_scan_controls_do_not_guess_unproved_option_labels(self):
        raw = copy.deepcopy(self.raw)
        raw['scanSource'] = True
        for option in raw['options']:
            option.update(scanSource=True, sourceImages=['../../../../question.png'])
        raw['options'][1]['label'] = 'A.'
        self.save_raw(raw)
        with self.assertRaisesRegex(ValueError, 'explicit ordered source labels'):
            self.read()


if __name__ == '__main__':
    unittest.main()

class RepeatedChoiceKeyTests(unittest.TestCase):
    def test_only_matching_standalone_choice_key_is_omitted(self):
        body='<section><h3>答案</h3><p>B</p></section><p>原完整推导</p>'
        detail='<p>（1）【答案】（B）。</p><p>【解】完整公式</p>'
        self.assertEqual(_omit_repeated_choice_key(body,detail,'single_choice'),'<p>原完整推导</p>')
        self.assertEqual(_omit_repeated_choice_key(body,detail,'fill_blank'),body)
        self.assertEqual(_omit_repeated_choice_key(body,'<p>【答案】C。</p>','single_choice'),body)
        self.assertEqual(_omit_repeated_choice_key('<p>答案：B</p>',detail,'single_choice'),'')
        self.assertEqual(_omit_repeated_choice_key('<section><h3>答案</h3><p>C</p></section>',r'<p>【答案】\(\mathrm C\)。</p>','single_choice'),'')
        prose='<section><h3>答案</h3><p>B，因为原推导。</p></section>'
        self.assertEqual(_omit_repeated_choice_key(prose,detail,'single_choice'),prose)

class HalfwidthDisplayTests(unittest.TestCase):
    def test_visible_fullwidth_ascii_only_and_no_html_injection(self):
        value='<p data-original="（Ａ）">（Ｂ）１２３，中文。 ＜img＞</p>'
        actual=_halfwidth_display_text(value)
        self.assertEqual(actual,'<p data-original="（Ａ）">(B)123，中文。 &lt;img&gt;</p>')
        self.assertEqual(_halfwidth_display_text(actual),actual)

class PageContinuationTests(unittest.TestCase):
    def test_standalone_marker_removed_but_subquestion_preserved(self):
        self.assertEqual(_omit_page_continuation('<div class="paragraph question">（11）（续）</div><p>题目</p>'),'<p>题目</p>')
        actual='<p>（1）求函数（续）</p><p>（11）</p>'
        self.assertEqual(_omit_page_continuation(actual),actual)
