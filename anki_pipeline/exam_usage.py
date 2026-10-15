"""Exam provenance labels. Meaning decisions remain separately reviewed."""
from copy import deepcopy
import html

from .exam_frequency import sentence_usage

POLICY = 'cloze-filled-passage-reading-all-options.v1'
CORRECTNESS = {'correct': '正确选项', 'incorrect': '错误选项', 'unknown': '答案未核实'}
ORIGINS = {'stem': '题干', 'option': '选项'}


def occurrence_sentence(row):
    provenance = row['source_provenance']
    evidence = provenance.get('sourcePathEvidence', {})
    components = evidence.get('components', [])
    context = {'questionId': evidence.get('questionId'), 'optionLabel': evidence.get('optionLabel')}
    if 'Section I Use of English' in components: context['sectionKind'] = 'cloze'
    if any('Reading Comprehension' in text for text in components): context['sectionKind'] = 'reading'
    return {'id': row['sentence_id'], 'paperId': row['paper_id'],
        'paragraphId': provenance.get('paragraphId', row['sentence_id']),
        'kind': evidence.get('kind', 'unknown'),
        'context': context}


def occurrence_usage(row, *, options=None, completions=None):
    sentence = occurrence_sentence(row)
    derived = row.get('display', {}).get('derivation_payload') or {}
    option = (options or {}).get(sentence['id'])
    completion = (completions or {}).get(sentence['id'])
    if not option and 'candidateOptionLabel' in derived: option = derived
    if not completion and derived.get('correctOptionLabel') and not option: completion = derived
    usage = sentence_usage(sentence, option_context=option, completion=completion)
    if sentence['kind'] == 'answer_option' and sentence['context'].get('sectionKind') == 'reading' and usage['source_role'] != 'reading_option':
        usage['source_role'] = 'reading_option'
        usage['reading_candidate_correctness'] = 'unknown'
    usage['policy'] = POLICY
    if usage['source_role'] in {'question_stem', 'reading_option'}:
        candidate = option or completion or derived
        label = candidate.get('candidateOptionLabel', candidate.get('correctOptionLabel', sentence['context'].get('optionLabel')))
        correctness = usage['reading_candidate_correctness']
        if usage['source_role'] == 'question_stem' and label:
            correctness = ('correct' if completion or 'candidateOptionLabel' not in candidate else
                'correct' if candidate.get('isCorrectCandidate') is True else
                'incorrect' if candidate.get('isCorrectCandidate') is False else 'unknown')
        usage['reading_candidate'] = {'question_id': candidate.get('questionId', sentence['context'].get('questionId')),
            'option_label': label, 'correctness': correctness,
            'match_origins': ['option' if usage['source_role'] == 'reading_option' else 'stem']}
    return validate_usage(usage)


def validate_candidate(value):
    if not isinstance(value, dict) or value.get('correctness') not in {*CORRECTNESS, 'not_applicable'}:
        raise ValueError('invalid reading candidate correctness')
    origins = value.get('match_origins')
    if (not isinstance(origins, list) or not origins or any(key not in ORIGINS for key in origins)
            or len(set(origins)) != len(origins)):
        raise ValueError('reading match origin must name its printed stem/option')
    if value.get('option_label') is not None and value['option_label'] not in tuple('ABCDEFGH'):
        raise ValueError('invalid reading option label')
    return deepcopy(value)


def validate_usage(value):
    if (not isinstance(value, dict) or value.get('policy') != POLICY or
        not all(isinstance(value.get(key), str) for key in ('source_kind', 'source_role')) or
        value.get('reading_candidate_correctness') not in {*CORRECTNESS, 'not_applicable'}):
        raise ValueError('unknown exam occurrence usage policy')
    if 'reading_candidate' in value: validate_candidate(value['reading_candidate'])
    return deepcopy(value)


def candidate_markup(value):
    if value is None: return ''
    value = validate_candidate(value)
    parts = []
    if value['correctness'] in CORRECTNESS and value.get('option_label'):
        parts.append(CORRECTNESS[value['correctness']] + ' ' + value['option_label'])
    parts.append('匹配来自' + '、'.join(ORIGINS[key] for key in value['match_origins']))
    return '<span class="exam-usage-labels" style="display:flex;flex-wrap:wrap;gap:.3rem;margin:.3rem 0;font-size:12px;line-height:1.5;color:var(--muted,#63718a)">' + ''.join(
        '<span style="padding:1px 5px;border-radius:4px;background:var(--surface-soft,#f2f5fa)">' + html.escape(part) + '</span>' for part in parts) + '</span>'


def occurrence_markup(row):
    usage = row.get('usage')
    if not usage: return ''
    usage = validate_usage(usage)
    if 'reading_candidate' in usage: return candidate_markup(usage['reading_candidate'])
    roles = {'cloze_passage': '完形原文（已填正确答案）', 'reading_passage': '阅读正文'}
    role = roles.get(usage['source_role'])
    return '<span class="exam-usage-labels" style="font-size:12px;color:var(--muted,#63718a)">' + html.escape(role) + '</span>' if role else ''


def frequency_breakdown_markup(data, *, expected_total):
    if (not isinstance(data, dict) or data.get('schema') != 'kaoyan-frequency-breakdown.v1'
            or data.get('occurrences') != expected_total):
        raise ValueError('usage breakdown must reconcile with the displayed frequency')
    roles, choices = data.get('source_role', {}), data.get('reading_candidate_correctness', {})
    if (any(type(n) is not int or n < 0 for n in [*roles.values(), *choices.values()]) or
            sum(roles.values()) != expected_total or sum(choices.values()) > roles.get('reading_option', 0)):
        raise ValueError('usage breakdown categories do not reconcile')
    labels = [f'{label} {roles[key]}' for key, label in
        (('cloze_passage', '完形原文'), ('reading_passage', '阅读正文'), ('question_stem', '题干')) if roles.get(key)]
    labels += [f'{label} {choices[key]}' for key, label in CORRECTNESS.items() if choices.get(key)]
    other = sum(n for key, n in roles.items() if key not in {'cloze_passage', 'reading_passage', 'question_stem', 'reading_option'})
    if other: labels.append(f'其他原文 {other}')
    return ('<div class="frequency-breakdown" style="margin-top:.3rem;font-size:12px;line-height:1.6;color:var(--muted,#63718a)">' + html.escape(' · '.join(labels)) +
        '<details style="margin-top:2px"><summary style="cursor:pointer">统计口径</summary>'
        '完形：只计正确答案填回原文；阅读：正文、题干及所有选项。补全副本不重复计次。</details></div>')
