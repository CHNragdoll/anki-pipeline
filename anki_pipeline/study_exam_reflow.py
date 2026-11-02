"""Adapt explicit reflow markup and resolved cross-form source references.

Only the authored reflow projection changes. Original questions, source blocks,
answer ownership and reference receipts remain available in SourceRecord.
"""
from __future__ import annotations
import copy
from collections import Counter
import html
import re


def markup(body):
    # These PREs are alternate copyable TeX for the immediately preceding
    # rendered paragraph, never independent question/answer content.
    body=re.sub(r'<pre\b[^>]*class=["\'][^"\']*\btex-source\b[^"\']*["\'][^>]*>.*?</pre>', '', body, flags=re.S)
    body=re.sub(r'class="math-options"', 'class="choices"', body)
    body=re.sub(r'class="math-option"', 'class="choice"', body)
    body=re.sub(r'<span class="math-option-label">(.*?)</span>', r'<b>\1</b>', body, flags=re.S)
    # The title already carries the question number; retain all inner parts.
    body=re.sub(r'^(<h2>)[一二三四五六七八九十]+、[（(]本题满分\s*\d+\s*分[）)]</h2>', '', body)
    body=re.sub(r'^(<(?:div|p)\b[^>]*>)\s*[（(]\d+[）)]\s*', r'\1', body)
    body=re.sub(r'^(<(?:div|p)\b[^>]*>)[（(](?:本题|本小题)(?:满分)?\s*\d+\s*分[）)]\s*', r'\1', body)
    return body


def normalized_answer(answer):
    parts=[]
    for name,label in [('value','答案'),('solution','解答'),('explanation','解析'),('commentary','考点点拨'),('knowledge','知识定位')]:
        value=answer.get(name)
        if value:
            parts.append('<section><h3>'+label+'</h3>'+''.join('<p>'+html.escape(p).replace('\n','<br>')+'</p>' for p in value.split('\n\n') if p)+'</section>')
    return ''.join(parts)


def adapt_reflow(snapshot, forms):
    rows=snapshot['questions'];by_key={q['key']:q for q in rows}
    shared=Counter(b['id'] for q in rows for b in q['source_record']['answer_blocks'])
    active=set();done=set()
    def project(q):
        if q['key'] in done:return
        if q['key'] in active:raise ValueError('cyclic resolved question reference')
        active.add(q['key'])
        record=q['source_record'];raw=record['question'];record['reflow_original_question']=copy.deepcopy(raw)
        raw=record['question']=copy.deepcopy(raw)
        q['question']=markup(q['question']);q['answer']=markup(q['answer'])
        answer=raw.get('answer') or {}
        refs=[r for r in answer.get('references',[]) if r.get('resolutionStatus')=='resolved']
        for ref in refs:
            key=ref['targetPaperId']+':'+ref['targetQuestionId']
            if key not in by_key:raise ValueError('resolved reflow target outside selected source')
            target=by_key[key];project(target)
            if ref.get('scope')=='whole_answer':
                # Only a stem consisting of its printed cross-form reference
                # (plus numbering/score) authorizes complete substitution.
                plain=html.unescape(re.sub('<[^>]+>','',q['question']))
                remaining=re.sub(r'\s+','',plain).replace(re.sub(r'\s+','',ref['printedText']),'')
                correction=ref.get('pdfVerifiedCorrection',{}).get('transcribedText')
                if correction:remaining=remaining.replace(re.sub(r'\s+','',correction),'')
                remaining=re.sub(r'试卷(?:IV|V)[（(]续[）)]','',remaining)
                remaining=re.sub(r'（[^）]*分[^）]*）|\([^)]*分[^)]*\)','',remaining)
                remaining=re.sub(r'[\s\d一二三四五六七八九十、（）、().．：:]+','',remaining)
                if remaining:raise ValueError('whole reference includes unprojected local question content: '+q['key'])
                q['question']=target['question'];q['answer']=target['answer']
                raw['options']=copy.deepcopy(target['source_record']['question'].get('options',[]))
                record['resolved_question_key']=key
            else:
                # Explicit part references keep local parts and append exactly
                # the linked source question, with a visible part label.
                if html.escape(ref['printedText']) in q['question'] or ref['printedText'] in q['question']:
                    q['question']=q['question'].replace(html.escape(ref['printedText']),'（该小问内容见下）').replace(ref['printedText'],'（该小问内容见下）')
                    q['question']+='<section class="exam-linked-question"><h3>引用小问</h3>'+target['question']+'</section>'
                q['answer']=normalized_answer(answer)
                record['resolved_question_key']=key
        if not refs and answer.get('value') and any(shared[b['id']]>1 for b in record['answer_blocks']):
            # A grouped answer-key paragraph is retained in audit. Its explicit
            # current-question mapping is the display, not all neighboring keys.
            q['answer']=normalized_answer(answer)
        if '判断题' in raw.get('sectionTitle',''):
            raw['questionType']=q['type']='true_false';q['type_label']='判断题'
        form=forms.get(q['key'])
        q['title']=' · '.join([str(q['year'])]+(['试卷'+form] if form else [])+[q['type_label'],'第 '+str(q['number'])+' 题'])
        record['question_type_label']=q['type_label']
        if form:record['source_form']=form
        active.remove(q['key']);done.add(q['key'])
    for q in rows:project(q)
    snapshot['question_type_labels']['true_false']='判断题'
    return snapshot


def source_forms(db, paper_ids):
    result={}
    for paper_id in paper_ids:
        form=None
        for row in db.execute('SELECT content_html,raw_json FROM source_blocks WHERE paper_id=? ORDER BY ordinal,id',(paper_id,)):
            plain=html.unescape(re.sub('<[^>]+>','',row['content_html']))
            match=re.search(r'试卷\s*(IV|V)(?=[）)（(\s]|$)',plain)
            if match and len(plain)<180:form=match[1]
            import json
            raw=json.loads(row['raw_json']);qid=raw.get('questionId')
            if qid and form:result[paper_id+':'+qid]=form
    return result
