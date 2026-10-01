"""Deterministic Part B completion from already reviewed sentence fragments.

No new translation or word alignment is authored here. Every inserted option
sentence and retained body translation stays pinned to the reviewed index.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .reading_completion import _require, _sha, _unique_object


_GAP = re.compile(r'[（(](4[1-5])[）)]\s*_{2,}(?:\s+_{2,})*')
_BLANK = re.compile(r'_{2,}')


def _replace_gap(text: str, gap: re.Match, option: str, *, english: bool):
    before, after = text[:gap.start()], text[gap.end():]
    answer = option.strip()
    # Preserve the source's punctuation after a stand-alone printed blank.
    if answer.endswith('.') and after.lstrip().startswith('.'):
        answer = answer[:-1]
    if not english and answer.endswith('。') and after.lstrip().startswith('。'):
        answer = answer[:-1]
    _require(bool(answer.strip()), 'Sentence insertion has an empty correct option')
    left = ' ' if english and before and before[-1].isalnum() and answer[0].isalnum() else ''
    right = ' ' if english and after and after[0].isalnum() else ''
    start = len(before) + len(left)
    completed = before + left + answer + right + after
    _require(not _BLANK.search(completed), 'Sentence insertion leaves another printed blank')
    return completed, [gap.start(), gap.end()], [start, start + len(answer)]


def prepare_sentence_insertions(root: Path, source_sentences: list[dict], index_report: dict):
    """Return source-bound assembled examples, watched hashes and a clear report."""
    root = Path(root).resolve(strict=True)
    targets = [row for row in source_sentences
               if row['kind'] == 'reading' and _BLANK.search(row['english'])]
    result, watched, papers = {}, {}, {}
    options = {}
    for sentence in source_sentences:
        if sentence['kind'] == 'answer_option':
            options.setdefault((sentence['paperId'], sentence['context'].get('questionId'),
                                sentence['sourceEnglish']), []).append(sentence)
    for sentence in targets:
        sid, paper_id = sentence['id'], sentence['paperId']
        gaps = list(_GAP.finditer(sentence['english']))
        _require(len(gaps) == 1, f'Sentence insertion lacks one unambiguous numbered gap: {sid}')
        gap = gaps[0]
        number = gap[1]
        chinese_gaps = [match for match in _GAP.finditer(sentence['translationZh'])
                        if match[1] == number]
        _require(len(chinese_gaps) == 1,
                 f'Sentence insertion has no matching original Chinese placeholder: {sid}')
        name = paper_id.split(':')[1]
        if paper_id not in papers:
            directory = root / 'data/sources/exam-library/structured/papers/kaoyan'
            try:
                path = (directory / (name + '.json')).resolve(strict=True)
                _require(path.is_relative_to(directory.resolve(strict=True)),
                         'Sentence insertion paper path escapes its directory')
                raw = path.read_bytes()
                paper = json.loads(raw, object_pairs_hook=_unique_object)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f'Cannot read structured sentence insertion paper: {paper_id}') from exc
            _require(isinstance(paper, dict) and paper.get('id') == paper_id
                     and isinstance(paper.get('questions'), list)
                     and isinstance(paper.get('blocks'), list),
                     'Invalid structured sentence insertion paper')
            block_ids = [block.get('id') for block in paper['blocks'] if isinstance(block, dict)]
            question_ids = [question.get('id') for question in paper['questions']
                            if isinstance(question, dict)]
            _require(all(isinstance(value, str) for value in block_ids + question_ids)
                     and len(block_ids) == len(paper['blocks']) == len(set(block_ids))
                     and len(question_ids) == len(paper['questions']) == len(set(question_ids)),
                     'Duplicate or invalid sentence insertion block/question')
            papers[paper_id] = paper, set(block_ids), _sha(raw)
            watched[path] = _sha(raw)
        paper, physical_blocks, paper_hash = papers[paper_id]
        source_blocks = sentence['sourceBlockIds']
        _require(bool(source_blocks) and all(block.startswith(paper_id + ':') for block in source_blocks),
                 f'Sentence insertion lacks physical source blocks: {sid}')
        local_blocks = {block.removeprefix(paper_id + ':') for block in source_blocks}
        _require(local_blocks <= physical_blocks, 'Sentence insertion source block is missing')
        candidates = [question for question in paper['questions']
            if question.get('number') == number
            and isinstance(question.get('context'), dict)
            and question['context'].get('kind') == 'numbered_gap_passage'
            and question['context'].get('taskForm') == 'sentence_insertion'
            and isinstance(question.get('sourceBlocks'), list)
            and all(isinstance(block, str) for block in question['sourceBlocks'])
            and local_blocks <= set(question['sourceBlocks'])]
        _require(len(candidates) == 1, f'Sentence insertion has ambiguous question provenance: {sid}')
        question = candidates[0]
        answer = question.get('answer')
        _require(isinstance(answer, dict) and answer.get('status') == 'explicit'
                 and isinstance(answer.get('value'), str) and re.fullmatch(r'[A-G]', answer['value']),
                 'Sentence insertion requires one explicit correct answer')
        answer_source = answer.get('externalSource')
        _require(isinstance(answer_source, dict) and isinstance(answer_source.get('url'), str),
                 'Sentence insertion explicit answer lacks external provenance')
        url = urlsplit(answer_source['url'])
        _require(url.scheme in {'http', 'https'} and bool(url.netloc) and not url.username
                 and not url.password and isinstance(answer_source.get('capturedAt'), str)
                 and bool(answer_source['capturedAt'].strip())
                 and answer_source.get('answerToken') == number + '-' + answer['value'],
                 'Sentence insertion explicit answer has invalid external provenance')
        _require(isinstance(question.get('options'), list), 'Sentence insertion correct options are missing')
        selected = [option for option in question['options']
                    if isinstance(option, dict) and isinstance(option.get('label'), str)
                    and option['label'].rstrip('.') == answer['value']]
        _require(len(selected) == 1 and isinstance(selected[0].get('text'), str)
                 and bool(selected[0]['text'].strip()), 'Sentence insertion correct option is ambiguous')
        option = selected[0]
        option_text = option['text']
        qid = paper_id + ':' + question['id']
        option_sentences = sorted(options.get((paper_id, qid, option_text), []),
                                  key=lambda row: row['start'])
        _require(bool(option_sentences) and len({row['paragraphId'] for row in option_sentences}) == 1,
                 'Sentence insertion has no unique complete reviewed option paragraph')
        cursor, references, chinese_parts = 0, [], []
        for row in option_sentences:
            _require(row['start'] >= cursor and not option_text[cursor:row['start']].strip()
                     and option_text[row['start']:row['end']] == row['english']
                     and row['filledEnglish'] == option_text
                     and isinstance(row['translationZh'], str) and bool(row['translationZh'].strip())
                     and not _BLANK.search(row['translationZh'])
                     and _sha(row['english']) == row['englishHash']
                     and _sha(row['translationZh']) == row['translationHash'],
                     'Sentence insertion reviewed option coverage/translation is incomplete')
            cursor = row['end']
            chinese_parts.append(row['translationZh'])
            references.append({'sentenceId': row['id'], 'paragraphId': row['paragraphId'],
                'optionRange': [row['start'], row['end']], 'english': row['english'],
                'translationZh': row['translationZh'], 'englishHash': row['englishHash'],
                'translationHash': row['translationHash'], 'sourceHash': row['sourceHash'],
                'reviewedContentHash': row['reviewedContentHash'],
                'sourceBlockIds': copy.deepcopy(row['sourceBlockIds'])})
        _require(not option_text[cursor:].strip(), 'Sentence insertion option sentence coverage is incomplete')
        option_chinese = ''.join(chinese_parts)
        completed, blank, inserted = _replace_gap(sentence['english'], gap, option_text, english=True)
        translation, zh_blank, zh_inserted = _replace_gap(
            sentence['translationZh'], chinese_gaps[0], option_chinese, english=False)
        source_files = index_report['source_files']
        result[sid] = {'completionType': 'sentence_insertion', 'sentenceId': sid, 'paperId': paper_id,
            'questionId': qid, 'answerNumber': number, 'optionLabel': answer['value'],
            'physicalOptionId': option.get('sourceOptionId') or option.get('id') or
                question['context'].get('id', paper_id + ':part-b') + ':' + answer['value'],
            'answerSource': copy.deepcopy(answer_source), 'structuredPaperHash': paper_hash,
            'sourceBlockIds': copy.deepcopy(source_blocks), 'originalEnglish': sentence['english'],
            'originalChinese': sentence['translationZh'], 'originalEnglishHash': sentence['englishHash'],
            'originalTranslationHash': sentence['translationHash'], 'originalSourceHash': sentence['sourceHash'],
            'originalReviewedContentHash': sentence['reviewedContentHash'],
            'indexFileHash': source_files['index/' + name + '.json'],
            'reviewedInputHash': source_files['inputs/' + name + '.json'],
            'reviewedTranslationHash': source_files['translations/' + name + '.json'],
            'reviewHash': source_files['reviews/' + name + '.json'],
            'optionText': option_text, 'optionTextHash': _sha(option_text), 'optionChinese': option_chinese,
            'optionSentenceIds': [ref['sentenceId'] for ref in references], 'optionSentenceRefs': references,
            'blankRange': blank, 'insertedRange': inserted,
            'chineseBlankRange': zh_blank, 'chineseInsertedRange': zh_inserted,
            'completedEnglish': completed, 'translationZh': translation,
            'englishHash': _sha(completed), 'translationHash': _sha(translation),
            'translationDerivation': 'reused_approved_sentence_translations',
            'translation_alignment': {'schema': 'codex-sentence-alignment.v1',
                'englishHash': _sha(completed), 'translationHash': _sha(translation), 'alignments': []}}
    return result, watched, {'completed_gaps': len(result),
        'reused_option_sentences': sum(len(row['optionSentenceIds']) for row in result.values()),
        'reused_body_translations': len(result), 'new_translations': 0, 'word_alignments_added': 0,
        'translation_scope': 'assembled_from_approved_source_sentences',
        'derived_semantic_review_status': 'not_separately_marked', 'chinese_target_marking': 'disabled',
        'frequency_policy': 'printed_original_occurrences_only'}


def insertion_option_source(completion: dict, span: tuple[int, int], by_source_id: dict):
    """Resolve an inserted occurrence to exactly one original option sentence."""
    from .reading_completion import option_range
    absolute = option_range(completion, span)
    if absolute is None:
        return None
    refs = [ref for ref in completion['optionSentenceRefs']
            if ref['optionRange'][0] <= absolute[0] < absolute[1] <= ref['optionRange'][1]]
    _require(len(refs) == 1, 'Sentence insertion target crosses original option sentence boundaries')
    ref = refs[0]
    row = by_source_id[ref['sentenceId']]
    start = ref['optionRange'][0]
    return row, (absolute[0] - start, absolute[1] - start)
