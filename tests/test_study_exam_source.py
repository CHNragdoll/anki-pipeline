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
            c.executescript('''CREATE TABLE papers(id TEXT,category TEXT,kind TEXT,title TEXT,year INTEGER,ordinal INTEGER,reader_path TEXT,raw_json TEXT);CREATE TABLE questions(id TEXT,paper_id TEXT,ordinal INTEGER,number TEXT,question_type TEXT,raw_json TEXT,in_bank INTEGER DEFAULT 1);CREATE TABLE answers(question_id TEXT,status TEXT,source_document_id TEXT,source_blocks_json TEXT,raw_json TEXT);CREATE TABLE source_blocks(id TEXT,paper_id TEXT,local_id TEXT,ordinal INTEGER,content_html TEXT,raw_json TEXT,role TEXT);CREATE TABLE question_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);CREATE TABLE context_source_blocks(question_id TEXT,block_id TEXT,ordinal INTEGER);''')
            c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?)',('politics:2023','politics','questions','政治2023',2023,1,'papers/politics/2023.htm','{}'))
            q={'id':'q-34','stem':'材料\n（1）说明理由（2）说明方法','subquestions':[{'number':'1'},{'number':'2'}],'options':[]}
            c.execute('INSERT INTO questions(id,paper_id,ordinal,number,question_type,raw_json) VALUES(?,?,?,?,?,?)',('politics:2023:q-34','politics:2023',1,'34','free_response',json.dumps(q)))
            c.execute('INSERT INTO source_blocks(id,paper_id,local_id,ordinal,content_html,raw_json) VALUES(?,?,?,?,?,?)',('stem','politics:2023','b1',1,'<p>材料与两个小问</p><img src="../../assets/chart.svg">','{}'))
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','stem',1))
            c.execute('INSERT INTO source_blocks(id,paper_id,local_id,ordinal,content_html,raw_json) VALUES(?,?,?,?,?,?)',('answer','politics:2023-answers','a1',1,'<p>完整答案要点，不能只保留解析。</p>','{}'))
            a={'value':None,'solution':None,'explanation':'仅解析','status':'explicit'}
            c.execute('INSERT INTO answers VALUES(?,?,?,?,?)',('politics:2023:q-34','explicit','politics:2023-answers','["a1"]',json.dumps(a)))
            c.execute("UPDATE source_blocks SET role='answer' WHERE id='answer'")

    def tearDown(self):self.temp.cleanup()

    def read(self, **options):return read_bank(self.db,'politics',structured_root=self.structured,asset_root=self.root,**options)

    def test_complete_papers_include_only_in_bank_questions(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE papers SET category='cs408',kind='complete'")
            c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?)',('answer-only','politics:2023',2,'34','free_response','{}',0))
            c.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?)',('cs408:answers','cs408','answers','答案',2023,2,'papers/politics/answers.htm','{}'))
            c.execute('INSERT INTO questions VALUES(?,?,?,?,?,?,?)',('other-answer','cs408:answers',1,'34','free_response','{}',1))
        result=read_bank(self.db,'cs408',structured_root=self.structured,asset_root=self.root)
        self.assertEqual(len(result['papers']),1)
        self.assertEqual([q['key'] for q in result['questions']],['politics:2023:q-34'])
        with self.assertRaisesRegex(ValueError,'no question papers'):
            read_bank(self.db,'cs408',structured_root=self.structured,asset_root=self.root,paper_kinds=('questions',))

    def test_inline_solution_is_removed_from_front_by_exact_block_identity(self):
        front='<pre><code>int f(int x) { return x &lt; 2 ? x : f(x-1); }</code></pre><p>\\(x+1\\)（1）说明理由（2）说明方法</p>'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE papers SET kind='complete'")
            c.execute("UPDATE source_blocks SET content_html=? WHERE id='stem'",(front,))
            c.execute("UPDATE source_blocks SET paper_id='politics:2023' WHERE id='answer'")
            c.execute("UPDATE answers SET source_document_id='politics:2023'")
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','answer',2))
        q=self.read()['questions'][0]
        self.assertEqual(q['question'],front)
        self.assertNotIn('完整答案要点',q['question'])
        self.assertIn('完整答案要点',q['answer'])
        self.assertEqual({r['id'] for r in q['source_record']['question_blocks']},{'stem','answer'})
        self.assertEqual(q['source_record']['front_answer_block_ids_excluded'],['answer'])

    def test_mixed_inline_block_keeps_stem_and_choices_before_explicit_answer(self):
        front='<p>将缓冲区的数据传送到用户区的时间是50us。</p><div class="choices"><div class="choice"><b>A.</b><span>1500us</span></div><div class="choice"><b>B.</b><span>1550us</span></div></div>'
        answer='<p class="paragraph"><strong>解答：</strong>B。单缓冲区分析过程。</p>'
        mixed='<div class="source-choice-block">'+front+answer+'</div>'
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE papers SET kind='complete'")
            c.execute("UPDATE source_blocks SET paper_id='politics:2023',content_html=?,role='choices' WHERE id='answer'",(mixed,))
            c.execute("UPDATE answers SET source_document_id='politics:2023'")
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','answer',2))
        q=self.read()['questions'][0]
        self.assertIn('<div class="source-choice-block">'+front+'</div>',q['question'])
        self.assertNotIn('解答：',q['question'])
        self.assertNotIn('单缓冲区分析过程',q['question'])
        self.assertEqual(q['answer'],'<div class="source-choice-block">'+answer+'</div>')
        self.assertNotIn('1550us',q['answer'])
        self.assertEqual(q['source_record']['answer_blocks'][0]['content_html'],mixed)
        self.assertEqual(next(b for b in q['source_record']['question_blocks'] if b['id']=='answer')['content_html'],mixed)
        receipt=q['source_record']['front_answer_block_partitions'][0]
        self.assertEqual(receipt['front_html'],'<div class="source-choice-block">'+front+'</div>')
        self.assertEqual(receipt['answer_html'],q['answer'])
        self.assertEqual(receipt['source_html_sha256'],hashlib.sha256(mixed.encode()).hexdigest())
        self.assertEqual(receipt['marker'],'解答：')

    def test_uncertain_mixed_ownership_is_rejected_instead_of_losing_question_content(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE source_blocks SET content_html='<div><p>题目继续，后面也许是答案。</p></div>',role='choices' WHERE id='answer'")
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','answer',2))
        with self.assertRaisesRegex(ValueError,'explicit answer boundary'):self.read()

    def test_answer_marker_mid_paragraph_is_not_a_proven_dom_boundary(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("UPDATE source_blocks SET content_html='<p>题面。解答：B。</p>',role='choices' WHERE id='answer'")
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','answer',2))
        with self.assertRaisesRegex(ValueError,'explicit answer boundary'):self.read()

    def test_answer_only_ownership_never_falls_back_to_potentially_combined_stem(self):
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute('DELETE FROM question_source_blocks')
            c.execute('INSERT INTO question_source_blocks VALUES(?,?,?)',('politics:2023:q-34','answer',1))
        with self.assertRaisesRegex(ValueError,'question-only source body'):self.read()

    def test_custom_type_labels_and_defaults_share_the_same_source_projection(self):
        default=self.read()['questions'][0]
        self.assertIn('材料分析题',default['title'])
        self.assertNotIn('question_type_label',default['source_record'])
        result=self.read(type_labels={'free_response':'综合应用题'})
        q=result['questions'][0]
        self.assertIn('综合应用题',q['title'])
        self.assertEqual(q['type_label'],'综合应用题')
        self.assertEqual(q['source_record']['question_type_label'],'综合应用题')
        self.assertEqual(q['question'],default['question'])
        self.assertEqual(q['answer'],default['answer'])
        self.assertEqual(q['key'],default['key'])
        self.assertEqual(result['question_type_labels']['single_choice'],'单选题')

    def test_invalid_paper_kinds_and_type_labels_are_rejected(self):
        for kinds in [(),('answers',),('questions','questions'),'questions',(['questions'],)]:
            with self.subTest(kinds=kinds),self.assertRaises(ValueError):self.read(paper_kinds=kinds)
        for labels in [{'unknown':'其他'},{'free_response':''},{'free_response':'X::Y'},{'free_response':'综合\n应用'}]:
            with self.subTest(labels=labels),self.assertRaises(ValueError):self.read(type_labels=labels)

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
            c.execute('INSERT INTO source_blocks(id,paper_id,local_id,ordinal,content_html,raw_json) VALUES(?,?,?,?,?,?)',
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
