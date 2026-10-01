"""Attach reviewed reading questions to their original candidate options.

The display adds context; matching, exclusions, frequency and reader links keep
the identity and code-point ranges of the originally printed option sentence.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from .exam_library import standalone_word_option
from .reading_completion import _require, _sha, _unique_object, complete_english


_BLANK = re.compile(r'_{2,}(?:\s+_{2,})*')


def _without_number(text, number):
    return re.sub(r'^\s*(?:' + re.escape(number) + r'\s*[.)、]|[（(]' +
                  re.escape(number) + r'[）)])\s*', '', text, count=1)


def _refs(rows):
    return [{'sentenceId': row['id'], 'paragraphId': row['paragraphId'],
        'range': [row['start'], row['end']], 'english': row['english'],
        'translationZh': row['translationZh'], 'englishHash': row['englishHash'],
        'translationHash': row['translationHash'], 'sourceHash': row['sourceHash'],
        'reviewedContentHash': row['reviewedContentHash'],
        'sourceBlockIds': copy.deepcopy(row['sourceBlockIds'])} for row in rows]


def _paragraph(rows, label):
    _require(bool(rows) and len({row['paragraphId'] for row in rows}) == 1,
             f'Reading option context lacks one complete {label} paragraph')
    rows = sorted(rows, key=lambda row: row['start'])
    text, cursor = rows[0]['sourceEnglish'], 0
    for row in rows:
        _require(row['sourceEnglish'] == row['filledEnglish'] == text and row['start'] >= cursor
                 and not text[cursor:row['start']].strip() and text[row['start']:row['end']] == row['english']
                 and _sha(row['english']) == row['englishHash']
                 and _sha(row['translationZh']) == row['translationHash'],
                 f'Reading option context {label} coverage/hash mismatch')
        cursor = row['end']
    _require(not text[cursor:].strip(), f'Reading option context {label} coverage is incomplete')
    return rows, text


def prepare_option_contexts(root: Path, source_sentences: list[dict], index_report: dict,
                            reading_completions: dict, *, joined_translation_path: Path | None = None):
    """Return eligible option contexts, watched structured files and source counts."""
    root = Path(root).resolve(strict=True)
    paragraphs, prompts_by_block, bare_by_question = {}, {}, {}
    for row in source_sentences:
        paragraphs.setdefault(row['paragraphId'], []).append(row)
        if row['kind'] == 'question_prompt':
            for block in row['sourceBlockIds']:
                prompts_by_block.setdefault(block, []).append(row)
        if row['kind'] == 'answer_option' and standalone_word_option(row['english'], row['kind']):
            bare_by_question.setdefault(row['context'].get('questionId'), set()).add(row['id'])
    completed_by_question = {}
    for value in reading_completions.values():
        if value.get('completionType') != 'sentence_insertion':
            _require(value['questionId'] not in completed_by_question,
                     'Duplicate reviewed completed reading question')
            completed_by_question[value['questionId']] = value
    candidate_paragraphs = {}
    for row in source_sentences:
        qid = row['context'].get('questionId')
        match = re.fullmatch(re.escape(row['paperId']) + r':q-([1-9][0-9]*)-[1-9][0-9]*', qid or '')
        if row['kind'] == 'answer_option' and match and int(match[1]) <= 40:
            candidate_paragraphs[row['paragraphId']] = row
    by_sentence, registry, watched, papers, questions_seen, reading_questions = {}, [], {}, {}, set(), set()
    bare_reading_options = set()
    for paragraph_id, representative in candidate_paragraphs.items():
        paper_id = representative['paperId']
        name = paper_id.split(':')[1]
        if paper_id not in papers:
            directory = root / 'data/sources/exam-library/structured/papers/kaoyan'
            try:
                path = (directory / (name + '.json')).resolve(strict=True)
                _require(path.is_relative_to(directory.resolve(strict=True)),
                         'Reading option context paper escapes its directory')
                raw = path.read_bytes()
                paper = json.loads(raw, object_pairs_hook=_unique_object)
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f'Reading option context structured paper is unavailable: {paper_id}') from exc
            _require(isinstance(paper, dict) and paper.get('id') == paper_id
                     and isinstance(paper.get('questions'), list) and isinstance(paper.get('blocks'), list),
                     'Invalid reading option context structured paper')
            questions = {row.get('id'): row for row in paper['questions'] if isinstance(row, dict)}
            blocks = {row.get('id'): row for row in paper['blocks'] if isinstance(row, dict)}
            _require(len(questions) == len(paper['questions']) and len(blocks) == len(paper['blocks'])
                     and all(isinstance(key, str) for key in (*questions, *blocks)),
                     'Duplicate or invalid reading option context question/block')
            papers[paper_id] = questions, blocks, _sha(raw)
            watched[path] = _sha(raw)
        questions, blocks, paper_hash = papers[paper_id]
        qid = representative['context']['questionId']
        question = questions.get(qid.removeprefix(paper_id + ':'))
        _require(question is not None, 'Reading option context question is missing')
        if not any(isinstance(label, dict) and label.get('kind') == 'reading'
                   for label in question.get('labels', [])):
            continue
        reading_questions.add(qid)
        bare_reading_options.update(bare_by_question.get(qid, ()))
        if all(standalone_word_option(row['english'], row['kind']) for row in paragraphs[paragraph_id]):
            continue
        _require(isinstance(question.get('sourceBlocks'), list) and bool(question['sourceBlocks'])
                 and all(isinstance(block, str) and block in blocks for block in question['sourceBlocks']),
                 'Reading option context has invalid question source blocks')
        _require(blocks[question['sourceBlocks'][0]].get('questionId') == qid.removeprefix(paper_id + ':'),
                 'Reading option context question block has another question identity')
        number = question.get('number')
        _require(isinstance(number, str) and re.fullmatch(r'[1-9][0-9]*', number)
                 and qid.removeprefix(paper_id + ':').split('-')[1] == number,
                 'Reading option context question number is invalid')
        options = question.get('options')
        _require(isinstance(options, list), 'Reading option context options are missing')
        letter = re.fullmatch(re.escape(qid) + r':([A-D])', paragraph_id)
        _require(letter is not None, 'Reading option context lacks its original candidate label')
        candidate_label = letter[1]
        selected = [option for option in options if isinstance(option, dict)
                    and option.get('label') in {candidate_label, candidate_label + '.'}]
        _require(len(selected) == 1 and isinstance(selected[0].get('text'), str),
                 'Reading option context candidate label is ambiguous')
        option_rows, option_text = _paragraph(paragraphs[paragraph_id], 'option')
        _require(option_text == selected[0]['text'] and all(
            row['context'].get('questionId') == qid and bool(row['sourceBlockIds'])
            and all(block.startswith(paper_id + ':') and block.removeprefix(paper_id + ':')
                    in question['sourceBlocks'] for block in row['sourceBlockIds']) for row in option_rows),
                 'Reading option context candidate text/source block mismatch')
        stem_rows, stem_text = _paragraph(prompts_by_block.get(
            paper_id + ':' + question['sourceBlocks'][0], []), 'question')
        _require(all(row['paperId'] == paper_id and all(block.removeprefix(paper_id + ':')
            in question['sourceBlocks'] for block in row['sourceBlockIds']) for row in stem_rows),
                 'Reading option context question source blocks mismatch')
        stem_english = _without_number(stem_text, number)
        stem_parts = [(row, _without_number(row['translationZh'], number)) for row in stem_rows
                      if _without_number(row['english'], number).strip()]
        stem_chinese = ''.join(text for _, text in stem_parts)
        _require(bool(stem_english.strip()) and bool(stem_chinese.strip()),
                 'Reading option context question translation is incomplete')
        answer = question.get('answer')
        _require(isinstance(answer, dict) and answer.get('status') == 'explicit'
                 and isinstance(answer.get('value'), str) and re.fullmatch(r'[A-D]', answer['value']),
                 'Reading option context has no unique explicit correct label')
        _require(len([option for option in options if isinstance(option, dict) and
                      option.get('label') in {answer['value'], answer['value'] + '.'}]) == 1,
                 'Reading option context correct option label is missing or ambiguous')
        answer_source = answer.get('externalSource')
        _require(isinstance(answer_source, dict) and isinstance(answer_source.get('url'), str),
                 'Reading option context answer provenance is missing')
        url = urlsplit(answer_source['url'])
        _require(url.scheme in {'http', 'https'} and bool(url.netloc) and not url.username and not url.password
                 and isinstance(answer_source.get('capturedAt'), str) and bool(answer_source['capturedAt'].strip())
                 and answer_source.get('answerToken') == number + '-' + answer['value'],
                 'Reading option context correct label provenance is invalid')
        is_correct = candidate_label == answer['value']
        blank_count = len(list(_BLANK.finditer(stem_english)))
        _require(blank_count <= 1, 'Reading option context has multiple unrecognized question blanks')
        if blank_count:
            completed, _, inserted = complete_english(stem_english, option_text)
        else:
            completed = stem_english + '\n\n' + option_text
            inserted = [len(stem_english) + 2, len(stem_english) + 2 + len(option_text.rstrip('.!?'))]
        correct = completed_by_question.get(qid) if is_correct and blank_count else None
        _require(not (is_correct and blank_count) or correct is not None,
                 'Reading option context lacks its validated correct completion')
        if correct is not None:
            _require(correct['optionLabel'] == candidate_label and correct['optionTextHash'] == _sha(option_text),
                     'Reading option context correct completion has stale option identity')
            if completed == correct['completedEnglish']:
                translation = correct['translationZh']
                translation_scope = 'reviewed_correct_completion'
            else:
                _require(any(row['id'] == correct['sentenceId'] for row, _ in stem_parts),
                         'Reading option context correct completion belongs to another question paragraph')
                translation = ''.join(correct['translationZh'] if row['id'] == correct['sentenceId'] else text
                                      for row, text in stem_parts)
                translation_scope = 'approved_context_with_reviewed_correct_completion'
        else:
            translation = ('题干：' + _BLANK.sub('［选项 ' + candidate_label + '］', stem_chinese) +
                           '\n选项 ' + candidate_label + '：' + ''.join(row['translationZh'] for row in option_rows))
            translation_scope = 'separate_approved_question_and_candidate_translations'
        context = {'sentenceId': option_rows[0]['id'], 'optionSentenceIds': [row['id'] for row in option_rows],
            'optionParagraphId': paragraph_id, 'paperId': paper_id, 'questionId': qid, 'answerNumber': number,
            'candidateOptionLabel': candidate_label, 'correctOptionLabel': answer['value'],
            'isCorrectCandidate': is_correct, 'answerSource': copy.deepcopy(answer_source),
            'structuredPaperHash': paper_hash, 'originalQuestionEnglish': stem_text,
            'questionEnglish': stem_english, 'originalQuestionChinese': stem_chinese,
            'stemSentenceRefs': _refs(stem_rows), 'optionSentenceRefs': _refs(option_rows),
            'optionText': option_text, 'optionTextHash': _sha(option_text), 'hasQuestionBlank': bool(blank_count),
            'completedEnglish': completed, 'translationZh': translation, 'insertedRange': inserted,
            'englishHash': _sha(completed), 'translationHash': _sha(translation),
            'translationScope': translation_scope, 'newTranslationAuthored': False,
            'reviewedCompletionSentenceId': correct['sentenceId'] if correct else None,
            'indexFileHash': index_report['source_files']['index/' + name + '.json'],
            'reviewedInputHash': index_report['source_files']['inputs/' + name + '.json'],
            'reviewedTranslationHash': index_report['source_files']['translations/' + name + '.json'],
            'reviewHash': index_report['source_files']['reviews/' + name + '.json'],
            'translation_alignment': {'schema': 'codex-sentence-alignment.v1', 'englishHash': _sha(completed),
                                     'translationHash': _sha(translation), 'alignments': []}}
        registry.append(context)
        questions_seen.add(qid)
        for row in option_rows:
            if not standalone_word_option(row['english'], row['kind']):
                by_sentence[row['id']] = context
    new_translation_count = 0
    if joined_translation_path is not None and registry:
        from .option_translation import load_option_translations
        translations, translation_watched, _ = load_option_translations(
            joined_translation_path, registry, index_report)
        for context in registry:
            if context['sentenceId'] not in translations:
                continue
            translation = translations[context['sentenceId']]
            context['translationZh'] = translation
            context['translationHash'] = _sha(translation)
            context['translationScope'] = 'independently_reviewed_complete_candidate_translation'
            context['newTranslationAuthored'] = True
            context['translation_alignment']['translationHash'] = _sha(translation)
        watched.update(translation_watched)
        new_translation_count = len(translations)
    return by_sentence, watched, {'reading_questions': len(reading_questions),
        'contextualized_reading_questions': len(questions_seen),
        'contextualized_option_paragraphs': len(registry), 'contextualized_option_sentences': len(by_sentence),
        'bare_reading_option_sentences_skipped': len(bare_reading_options),
        'new_translations': new_translation_count, 'word_alignments_added': 0, 'chinese_target_marking': 'disabled',
        'frequency_policy': 'original_option_sentence_occurrences_only'}, registry


def context_target_ranges(context: dict, sentence: dict, ranges: list[tuple[int, int]]):
    """Move only this original option's selected targets into its contextual display."""
    refs = [ref for ref in context['optionSentenceRefs'] if ref['sentenceId'] == sentence['id']]
    _require(len(refs) == 1, 'Reading option target lacks exact original sentence provenance')
    offset = context['insertedRange'][0] + refs[0]['range'][0]
    result = [(offset + start, offset + end) for start, end in ranges]
    _require(all(context['insertedRange'][0] <= start < end <= context['insertedRange'][1]
                 and context['completedEnglish'][start:end] == sentence['english'][old_start:old_end]
                 for (start, end), (old_start, old_end) in zip(result, ranges)),
             'Reading option contextual target offset/text mismatch')
    return result
