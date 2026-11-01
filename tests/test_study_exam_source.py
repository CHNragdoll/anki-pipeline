import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from anki_pipeline.study_exam_source import read_bank

class ExamSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=self.root/'bank.sqlite3'
        self.structured=self.root/'structured';(self.structured/'papers/politics').mkdir(parents=True)
        (self.structured/'assets').mkdir();(self.structured/'assets/chart.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>图</text></svg>')
        with closing(sqlite3.connect(self.db)) as c, c:
            c.executescript('''CREATE TABLE papers(id TEXT,category TEXT,kind TEXT,title TEXT,year INTEGER,ordinal INTEGER,reader_path TEXT,raw_json TEXT);CREATE TABLE questions(id TEXT,paper_id TEXT,ordinal INTEGER,number TEXT,question_type TEXT,raw_json TEXT);CREATE TABLE answers(question_id TEXT,status TEXT,source_document_id TEXT,source_blocks_json TEXT,raw_json TEXT);CREATE TABLE source_blocks(id TEXT,paper_id TEXT,local_id TEXT,ordinal INTEGER,content_html TEXT,raw_json TEXT);CREATE TABLE question_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);CREATE TABLE context_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);''')
            c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?)',('politics:2023','politics','questions','政治2023',2023,1,'papers/politics/2023.htm','{}'))
            q={'id':'q-34','stem':'材料\n（1）说明理由（2）说明方法','subquestions':[{'number':'1'},{'number':'2'}],'options':[]}
            c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?)',('politics:2023:q-34','politics:2023',1,'34','free_response',json.dumps(q)))
            c.execute('INSERT INTO source_blocks VALUES(?,?,?,?,?,?)',('stem','politics:2023','b1',1,'<p>材料与两个小问</p><img src="../../assets/chart.svg">','{}'))
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','stem',1))
            c.execute('INSERT INTO source_blocks VALUES(?,?,?,?,?,?)',('answer','politics:2023-answers','a1',1,'<p>完整答案要点，不能只保留解析。</p>','{}'))
            a={'value':None,'solution':None,'explanation':'仅解析','status':'explicit'}
            c.execute('INSERT INTO answers VALUES(?,?,?,?,?)',('politics:2023:q-34','explicit','politics:2023-answers','["a1"]',json.dumps(a)))

    def tearDown(self):self.temp.cleanup()

    def read(self):return read_bank(self.db,'politics',structured_root=self.structured,asset_root=self.root)

    def test_preserves_full_answer_blocks_material_and_portable_media(self):
        before=hashlib.sha256(self.db.read_bytes()).hexdigest();first=self.read();second=self.read();q=first['questions'][0]
        self.assertIn('完整答案要点',q['answer']);self.assertIn('材料与两个小问',q['question'])
        self.assertNotIn('../../assets',q['question']);self.assertEqual(len(first['resources']),1)
        self.assertEqual(q['source_record']['question']['subquestions'],[{'number':'1'},{'number':'2'}])
        self.assertEqual(q['key'],second['questions'][0]['key']);self.assertEqual(first['source_sha256'],before)
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)

    def test_table_key_is_scoped_and_source_warning_retained(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            raw=json.loads(c.execute('SELECT raw_json FROM questions').fetchone()[0])
            raw.update(questionType='single_choice', options=[{'label':x,'text':x} for x in 'ABCD'])
            c.execute('UPDATE questions SET raw_json=?',(json.dumps(raw),))
            c.execute('UPDATE source_blocks SET content_html=? WHERE id=?',
                      ('<table><tr><td>1 A 2 B</td></tr></table>','answer'))
            c.execute('UPDATE answers SET raw_json=?',(json.dumps({'value':'A'}),))
            c.execute('INSERT INTO source_blocks VALUES(?,?,?,?,?,?)',
                      ('warning','politics:2023-answers','warn',0,'<h2>非官方答案，仅供参考</h2>','{}'))
        q=self.read()['questions'][0]
        self.assertIn('【答案】A',q['answer'])
        self.assertNotIn('1 A 2 B',q['answer'])
        self.assertIn('非官方答案，仅供参考',q['answer'])
        self.assertIn('1 A 2 B',q['source_record']['answer_blocks'][0]['content_html'])
        self.assertEqual(len(q['source_record']['answer_context']),1)

    def test_missing_answer_is_explicit_never_inferred(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute('DELETE FROM answers')
        q=self.read()['questions'][0];self.assertEqual(q['status'],'missing');self.assertIn('未提供',q['answer']);self.assertNotIn('完整答案要点',q['answer'])

    def test_missing_referenced_answer_block_fails_instead_of_truncating(self):
        with closing(sqlite3.connect(self.db)) as c, c:c.execute("DELETE FROM source_blocks WHERE id='answer'")
        with self.assertRaisesRegex(ValueError,'answer source'):self.read()

    def test_media_escape_and_remote_resources_are_rejected(self):
        for src in ['../../../../outside.svg','https://example.com/chart.svg']:
            with self.subTest(src=src):
                with closing(sqlite3.connect(self.db)) as c, c:c.execute('UPDATE source_blocks SET content_html=? WHERE id=?',('<img src="'+src+'">','stem'))
                with self.assertRaises(ValueError):self.read()

if __name__=='__main__':unittest.main()
