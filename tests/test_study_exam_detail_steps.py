"""Regression checks for shared text/reflow and scan-backed solution projection."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from anki_pipeline.study_exam_source import read_bank


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
