"""Derived reading answers, bound to the immutable reviewed source inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


SCHEMA = 'reading-question-completions.v1'
REVIEW_SCHEMA = 'reading-question-completion-review.v1'
_BLANK = re.compile(r'_{2,}')
_TERMINAL = re.compile(r'''[.!?]["'’”»)\]}）】》」』]*\Z''')
_HASH = re.compile(r'[0-9a-f]{64}\Z')


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate reading completion JSON field')
        result[key] = value
    return result


def complete_english(english: str, option: str):
    """Replace one printed blank and retain exact source-to-display offset maps."""
    _require(isinstance(english, str) and isinstance(option, str) and bool(option.strip()),
             'Reading completion requires exactly one blank and a nonempty answer')
    blanks = list(_BLANK.finditer(english))
    _require(len(blanks) == 1, 'Reading completion requires exactly one blank and a nonempty answer')
    blank = blanks[0]
    before, after = english[:blank.start()], english[blank.end():]
    answer = option.strip()
    if answer.endswith('.') and after.lstrip().startswith('.'):
        answer = answer[:-1]
    left = ' ' if before and before[-1].isalnum() and answer[0].isalnum() else ''
    right = ' ' if after and after[0].isalnum() and answer[-1].isalnum() else ''
    start = len(before) + len(left)
    completed = before + left + answer + right + after
    if not after.strip() and not _TERMINAL.search(completed.rstrip()):
        completed += '.'
    # Sentence punctuation remains visible but is not an answer word.
    end = start + len(answer.rstrip('.!?'))
    _require(start < end and not _BLANK.search(completed), 'Reading answer leaves an empty blank')
    return completed, [blank.start(), blank.end()], [start, end]


def prepare_reading_completions(root: Path, source_sentences: list[dict], index_report: dict):
    """Return authoring inputs and file hashes; this function never writes sources."""
    root = Path(root).resolve(strict=True)
    targets = [row for row in source_sentences
               if row['kind'] == 'question_prompt' and _BLANK.search(row['english'])]
    payload = {'schema': SCHEMA, 'indexManifestHash': index_report['manifest_sha256'],
               'inputManifestHash': index_report['input_manifest_sha256'], 'rows': []}
    papers, watched = {}, {}
    options = {}
    for sentence in source_sentences:
        if sentence['kind'] == 'answer_option':
            key = (sentence['paperId'], sentence['context'].get('questionId'))
            options.setdefault(key, []).append(sentence)
    for sentence in targets:
        paper_id = sentence['paperId']
        name = paper_id.split(':')[1]
        if paper_id not in papers:
            directory = root / 'data/sources/exam-library/structured/papers/kaoyan'
            try:
                path = (directory / (name + '.json')).resolve(strict=True)
            except OSError as exc:
                raise ValueError('Structured reading paper is missing') from exc
            _require(path.is_relative_to(directory.resolve(strict=True)),
                     'Structured reading paper path escapes its directory')
            raw = path.read_bytes()
            try:
                paper = json.loads(raw, object_pairs_hook=_unique_object)
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError('Invalid structured reading paper') from exc
            _require(isinstance(paper, dict) and paper.get('id') == paper_id,
                     'Structured reading paper identity mismatch')
            blocks = paper.get('blocks')
            questions = paper.get('questions')
            _require(isinstance(blocks, list) and isinstance(questions, list),
                     'Structured reading paper lacks blocks or questions')
            by_block, by_question = {}, {}
            for block in blocks:
                _require(isinstance(block, dict) and isinstance(block.get('id'), str)
                         and block['id'] not in by_block, 'Duplicate structured reading block')
                by_block[block['id']] = block
            for question in questions:
                _require(isinstance(question, dict) and isinstance(question.get('id'), str)
                         and question['id'] not in by_question, 'Duplicate structured reading question')
                by_question[question['id']] = question
            papers[paper_id] = by_block, by_question, _sha(raw)
            watched[path] = _sha(raw)
        blocks, questions, paper_hash = papers[paper_id]
        block_ids = sentence['context'].get('sourceBlockIds')
        _require(isinstance(block_ids, list) and bool(block_ids),
                 'Reading blank lacks source block provenance')
        question_ids = set()
        for block_id in block_ids:
            _require(isinstance(block_id, str) and block_id.startswith(paper_id + ':'),
                     'Reading source block belongs to another paper')
            block = blocks.get(block_id.removeprefix(paper_id + ':'))
            _require(block is not None, 'Reading source block is missing')
            if block.get('questionId'):
                question_ids.add(block['questionId'])
        _require(len(question_ids) == 1, 'Reading blank has missing or ambiguous question provenance')
        question_id = next(iter(question_ids))
        question = questions.get(question_id)
        _require(question is not None, 'Reading blank question is missing')
        answer = question.get('answer')
        _require(isinstance(answer, dict) and answer.get('status') == 'explicit'
                 and isinstance(answer.get('value'), str)
                 and re.fullmatch(r'[A-Z]', answer['value']),
                 'Reading question has missing or ambiguous explicit answer')
        label = answer['value']
        number = question.get('number')
        _require(isinstance(number, str) and re.fullmatch(r'[1-9][0-9]*', number),
                 'Reading question has no valid printed number')
        answer_source = answer.get('externalSource')
        source_url = answer_source.get('url') if isinstance(answer_source, dict) else None
        _require(isinstance(source_url, str), 'Reading explicit answer lacks external provenance')
        parsed_url = urlsplit(source_url)
        _require(parsed_url.scheme in {'http', 'https'} and bool(parsed_url.netloc)
                 and not parsed_url.username and not parsed_url.password
                 and isinstance(answer_source.get('capturedAt'), str)
                 and bool(answer_source['capturedAt'].strip())
                 and answer_source.get('answerToken') == number + '-' + label,
                 'Reading explicit answer has invalid external provenance')
        option_rows = question.get('options')
        _require(isinstance(option_rows, list), 'Reading question has no correct options')
        selected = [option for option in option_rows
                    if isinstance(option, dict) and isinstance(option.get('label'), str)
                    and option['label'].rstrip('.') == label]
        _require(len(selected) == 1 and isinstance(selected[0].get('text'), str)
                 and bool(selected[0]['text'].strip()), 'Reading question has no unique correct option')
        option_text = selected[0]['text']
        full_question_id = paper_id + ':' + question_id
        indexed = [row for row in options.get((paper_id, full_question_id), [])
                   if row['sourceEnglish'] == option_text]
        _require(len(indexed) == 1, 'Correct reading option lacks a unique reviewed sentence')
        option_sentence = indexed[0]
        _require(option_sentence['english'] == option_text
                 and option_sentence['start'] == 0 and option_sentence['end'] == len(option_text),
                 'Correct reading option is not one complete reviewed sentence')
        completed, blank, inserted = complete_english(sentence['english'], option_text)
        source_files = index_report['source_files']
        payload['rows'].append({'sentenceId': sentence['id'], 'paperId': paper_id,
            'questionId': full_question_id, 'structuredPaperHash': paper_hash,
            'originalEnglishHash': sentence['englishHash'],
            'originalTranslationHash': sentence['translationHash'],
            'originalSourceHash': sentence['sourceHash'],
            'originalReviewedContentHash': sentence['reviewedContentHash'],
            'indexFileHash': source_files['index/' + name + '.json'],
            'reviewedInputHash': source_files['inputs/' + name + '.json'],
            'reviewedTranslationHash': source_files['translations/' + name + '.json'],
            'reviewHash': source_files['reviews/' + name + '.json'],
            'optionLabel': label, 'optionTextHash': _sha(option_text),
            'optionSentenceId': option_sentence['id'],
            'optionEnglishHash': option_sentence['englishHash'],
            'optionSourceHash': option_sentence['sourceHash'],
            'optionTranslationHash': option_sentence['translationHash'],
            'optionReviewedContentHash': option_sentence['reviewedContentHash'],
            'answerSource': answer_source, 'answerNumber': number,
            'blankRange': blank, 'insertedRange': inserted,
            'originalEnglish': sentence['english'], 'originalChinese': sentence['translationZh'],
            'optionEnglish': option_sentence['english'], 'optionChinese': option_sentence['translationZh'],
            'optionText': option_text, 'completedEnglish': completed})
    return payload, watched


def _approved_completion_review(path: Path, sidecar_hash: str, expected: dict):
    """Bind independent approval to exactly these derived text bytes and IDs."""
    review_path = path.with_suffix('.review.json')
    _require(review_path.is_file(), 'Independent reading completion approval is missing')
    try:
        raw = review_path.read_bytes()
        review = json.loads(raw, object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid independent reading completion approval') from exc
    fields = {'schema', 'status', 'sidecarSha256', 'indexManifestHash',
              'inputManifestHash', 'reviewedSentenceIds', 'evidenceFiles'}
    _require(isinstance(review, dict) and set(review) == fields,
             'Reading completion approval has unknown or missing fields')
    _require(review['schema'] == REVIEW_SCHEMA and review['status'] == 'approved',
             'Reading completion requires independent approved review')
    _require(review['sidecarSha256'] == sidecar_hash,
             'Reading completion approval sidecar hash mismatch')
    _require(all(review[key] == expected[key]
                 for key in ('indexManifestHash', 'inputManifestHash')),
             'Reading completion approval has stale reviewed input')
    ids = review['reviewedSentenceIds']
    expected_ids = {row['sentenceId'] for row in expected['rows']}
    _require(isinstance(ids, list) and all(isinstance(sid, str) for sid in ids)
             and len(ids) == len(set(ids)) and set(ids) == expected_ids,
             'Reading completion approval must cover every current sentence exactly once')
    evidence = review['evidenceFiles']
    _require(isinstance(evidence, dict) and bool(evidence)
             and all(isinstance(name, str) and bool(name.strip())
                     and isinstance(value, str) and _HASH.fullmatch(value)
                     for name, value in evidence.items()),
             'Reading completion approval lacks valid independent review evidence hashes')
    return review_path, _sha(raw)


def load_reading_completions(root: Path, path: Path, source_sentences: list[dict], index_report: dict):
    """Fail closed unless every current reading blank has a reviewed translation."""
    expected, watched = prepare_reading_completions(root, source_sentences, index_report)
    if not expected['rows']:
        return {}, watched, {'completed_reading_questions': 0, 'sidecar_sha256': None,
                            'approval_sha256': None,
                            'translation_scope': 'reviewed_derived_reading_sentence',
                            'alignment_policy': 'exact_text_hashes_without_word_alignment',
                            'chinese_target_marking': 'disabled'}
    path = Path(path)
    _require(path.is_file(), 'Reviewed reading completion sidecar is missing')
    raw = path.read_bytes()
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid reading completion sidecar') from exc
    _require(isinstance(payload, dict) and set(payload) == set(expected),
             'Reading completion sidecar has unknown or missing fields')
    _require(all(payload.get(key) == expected[key]
             for key in ('schema', 'indexManifestHash', 'inputManifestHash')),
             'Reading completion sidecar has stale reviewed input')
    rows = payload.get('rows')
    _require(isinstance(rows, list) and len(rows) == len(expected['rows']),
             'Reading completion sidecar must cover every current blank')
    expected_by_id = {row['sentenceId']: row for row in expected['rows']}
    result = {}
    for row in rows:
        _require(isinstance(row, dict) and row.get('sentenceId') in expected_by_id
                 and row['sentenceId'] not in result, 'Duplicate or unknown reading completion sentence')
        expected_row = expected_by_id[row['sentenceId']]
        _require(set(row) == set(expected_row) | {'status', 'translationZh'},
                 'Reading completion row has unknown or missing fields')
        _require(all(row.get(key) == value for key, value in expected_row.items()),
                 'Reading completion has stale source, answer, offsets or reviewed input')
        translation = row.get('translationZh')
        _require(row.get('status') == 'reviewed' and isinstance(translation, str)
                 and bool(translation.strip()) and translation == translation.strip()
                 and not _BLANK.search(translation), 'Reading completion lacks a reviewed complete translation')
        result[row['sentenceId']] = {**row, 'englishHash': _sha(row['completedEnglish']),
            'translationHash': _sha(translation), 'translation_alignment': {
                'schema': 'codex-sentence-alignment.v1', 'englishHash': _sha(row['completedEnglish']),
                'translationHash': _sha(translation), 'alignments': []}}
    sidecar_hash = _sha(raw)
    review_path, approval_hash = _approved_completion_review(path, sidecar_hash, expected)
    watched[path] = sidecar_hash
    watched[review_path] = approval_hash
    return result, watched, {'completed_reading_questions': len(result), 'sidecar_sha256': sidecar_hash,
                            'approval_sha256': approval_hash,
                            'translation_scope': 'reviewed_derived_reading_sentence',
                            'alignment_policy': 'exact_text_hashes_without_word_alignment',
                            'chinese_target_marking': 'disabled'}


def original_range(completion: dict, span: tuple[int, int]):
    """Map a displayed stem occurrence back to reviewed sentence code points."""
    blank_start, blank_end = completion['blankRange']
    # The suffix shifts by the entire replacement, including glue spaces.
    original = completion['originalEnglish']
    suffix = original[blank_end:]
    suffix_start = len(completion['completedEnglish']) - len(suffix)
    if not suffix and completion['completedEnglish'].endswith('.'):
        suffix_start = len(completion['completedEnglish'])
    if span[1] <= blank_start:
        return span
    if span[0] >= suffix_start:
        shift = suffix_start - blank_end
        return span[0] - shift, span[1] - shift
    return None


def option_range(completion: dict, span: tuple[int, int]):
    """Map a displayed inserted-answer occurrence to its original option sentence."""
    start, end = completion['insertedRange']
    if start <= span[0] < span[1] <= end:
        offset = len(completion['optionText']) - len(completion['optionText'].lstrip())
        return span[0] - start + offset, span[1] - start + offset
    return None
