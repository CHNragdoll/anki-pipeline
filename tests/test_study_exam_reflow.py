import copy
import unittest
from anki_pipeline.study_exam_reflow import adapt_reflow

class ReflowTests(unittest.TestCase):
    def row(self,key,body,section='',answer=None):
        raw={'id':key,'number':1,'questionType':'free_response','sectionTitle':section,'answer':answer or {'value':'×'},'options':[]}
        return {'key':'p:'+key,'year':1987,'number':1,'type':'free_response','type_label':'解答题','title':'old','question':body,'answer':'grouped answers','source_record':{'paper':{'id':'p'},'question':raw,'question_blocks':[],'answer_blocks':[{'id':'shared'}]}}
    def test_resolved_reference_expands_target_keeps_raw_evidence(self):
        a=self.row('a','<div>Complete \\(x\\)</div><pre class="tex-source">raw</pre>','一、判断题')
        b=self.row('b','<div>【same】</div>','一、判断题',{'value':'×','references':[{'scope':'whole_answer','resolutionStatus':'resolved','targetPaperId':'p','targetQuestionId':'a','printedText':'【same】'}]})
        s={'questions':[a,b],'question_type_labels':{}}
        adapt_reflow(s,{})
        self.assertIn('Complete',b['question']);self.assertNotIn('【same】',b['question'])
        self.assertEqual(b['type'],'true_false');self.assertEqual(b['source_record']['reflow_original_question']['questionType'],'free_response')
        self.assertEqual(b['source_record']['question']['answer']['references'][0]['targetQuestionId'],'a')
        self.assertNotIn('tex-source',a['question']);self.assertNotIn('grouped',a['answer'])
    def test_unresolved_reference_is_not_guessed(self):
        a=self.row('a','<p>【same】</p>',answer={'references':[{'resolutionStatus':'pending'}]})
        adapt_reflow({'questions':[a],'question_type_labels':{}},{})
        self.assertIn('【same】',a['question'])
    def test_options_keep_math_markup(self):
        q=self.row('a','<div class="math-options"><div class="math-option"><span class="math-option-label">（A）</span><span>\\(x\\)</span></div></div>')
        adapt_reflow({'questions':[q],'question_type_labels':{}},{})
        self.assertIn('class="choices"',q['question']);self.assertIn('class="choice"',q['question']);self.assertIn('<b>（A）</b>',q['question']);self.assertIn(r'\(x\)',q['question'])
