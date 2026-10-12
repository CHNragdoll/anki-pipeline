"""Pure projection of source-pinned reading answer metadata onto usage labels.

The caller must verify the pinned frozen file bytes, question hash and line
before building the index. This module performs structural reconciliation only;
it never reads source files or reconstructs question IDs from printed numbers.
"""
from __future__ import annotations

from copy import deepcopy
import re
from urllib.parse import urlsplit

SCHEMA = 'exam-usage-reading-answer-metadata.v1'
_PAPER = re.compile(r'kaoyan:[0-9]{4}-0[12]')
_QUESTION = re.compile(r'q-([1-9][0-9]*)-[1-9][0-9]*')
_HASH = re.compile(r'[0-9a-f]{64}')
_LABEL = re.compile(r'\s*[\[(]?([A-H])[\]).]?\s*')


class _QuestionMetadataIndex(dict):
    """Marker for metadata that passed the complete index validation."""


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _question_id(paper, value):
    _require(isinstance(paper, str) and _PAPER.fullmatch(paper), 'invalid metadata paper ID')
    _require(isinstance(value, str), 'invalid question ID')
    if ':' in value:
        _require(value.startswith(paper + ':'), 'question ID belongs to another paper')
        value = value[len(paper) + 1:]
    _require(_QUESTION.fullmatch(value), 'invalid exact question ID')
    return value


def _label(value):
    match = _LABEL.fullmatch(value) if isinstance(value, str) else None
    _require(match is not None, 'invalid source option label')
    return match[1]


def _labels(value, name):
    _require(isinstance(value, list) and all(isinstance(v, str) and re.fullmatch('[A-H]', v) for v in value),
             'invalid ' + name)
    _require(len(set(value)) == len(value), 'duplicate ' + name)
    return set(value)


def build_question_metadata_index(metadata, *, expected_source_pin=None):
    """Return a validated index keyed by exact ``(paper_id, bare_question_id)``.

    ``expected_source_pin`` can bind the caller's independently verified file
    and SHA. No SHA-shaped string alone establishes actual source validation.
    """
    _require(isinstance(metadata, dict) and metadata.get('schema') == SCHEMA,
             'unsupported reading metadata schema')
    source = metadata.get('source_pin')
    _require(isinstance(source, dict) and isinstance(source.get('file'), str) and bool(source['file'])
             and isinstance(source.get('sha256'), str) and _HASH.fullmatch(source['sha256']),
             'invalid reading metadata source pin')
    if expected_source_pin is not None:
        _require(isinstance(expected_source_pin, dict) and all(source.get(k) == expected_source_pin.get(k)
                 for k in ('file', 'sha256')), 'reading metadata source pin mismatch')
    questions = metadata.get('questions')
    _require(isinstance(questions, list), 'reading metadata questions must be a list')
    result = _QuestionMetadataIndex()
    for question in questions:
        _require(isinstance(question, dict), 'invalid reading metadata question')
        paper = question.get('paper_id')
        identity = _question_id(paper, question.get('question_id'))
        key = (paper, identity)
        _require(key not in result, 'duplicate exact reading question ID')
        status = question.get('status')
        _require(status in {'verified', 'unknown'} and question.get('question_kind') in {'reading', 'matching'},
                 'invalid reading question metadata status or kind')
        pin = question.get('source_pin')
        _require(isinstance(pin, dict) and all(pin.get(k) == source[k] for k in ('file', 'sha256'))
                 and isinstance(pin.get('question_sha256'), str) and _HASH.fullmatch(pin['question_sha256'])
                 and type(pin.get('line_number')) is int and pin['line_number'] > 0
                 and type(pin.get('question_index')) is int and pin['question_index'] >= 0
                 and pin.get('json_pointer') == f"/questions/{pin['question_index']}/answer",
                 'invalid question source pin')
        options = question.get('options')
        _require(isinstance(options, list), 'question options must be a list')
        available, orders = set(), set()
        for position, option in enumerate(options):
            _require(isinstance(option, dict), 'invalid source option')
            letter = _label(option.get('label'))
            _require(option.get('label') == letter and _label(option.get('source_label')) == letter,
                     'source option label mismatch')
            _require(letter not in available, 'duplicate source option label')
            available.add(letter)
            order = option.get('source_order')
            _require(type(order) is int and order > 0 and order not in orders, 'invalid source option order')
            orders.add(order)
            _require(isinstance(option.get('text'), str) and bool(option['text'].strip()), 'source option text missing')
            _require(option.get('source_option_id') is None, 'unsupported fabricated source option ID')
            original = option.get('source_identity')
            _require(isinstance(original, dict) and _question_id(paper, original.get('question_id')) == identity
                     and original.get('label') == letter, 'source option identity mismatch')
            _require(option.get('source_json_pointer') == f"/questions/{pin['question_index']}/options/{position}",
                     'source option pointer mismatch')
        correct = _labels(question.get('correct_labels'), 'correct labels')
        incorrect = _labels(question.get('incorrect_labels'), 'incorrect labels')
        _require(not correct.intersection(incorrect), 'correct and incorrect labels overlap')
        if status == 'verified':
            _require(len(correct) == 1 and correct.union(incorrect) == available and bool(available),
                     'verified labels must completely partition actual options')
            if question['question_kind'] == 'reading':
                _require(available == set('ABCD'), 'verified reading options must cover original A-D labels')
            answer = next(iter(correct))
            _require(isinstance(pin.get('captured_source_url'), str), 'invalid captured answer source URL')
            try:
                url = urlsplit(pin['captured_source_url'])
            except ValueError as exc:
                raise ValueError('invalid captured answer source URL') from exc
            _require(pin.get('answer_status') == 'explicit' and pin.get('answer_value') == answer
                     and pin.get('captured_answer_token') == _QUESTION.fullmatch(identity)[1] + '-' + answer
                     and url.scheme in {'http', 'https'} and bool(url.netloc)
                     and not url.username and not url.password
                     and isinstance(pin.get('captured_at'), str) and bool(pin['captured_at'].strip()),
                     'verified answer source evidence mismatch')
        else:
            _require(not correct and not incorrect, 'unknown answers cannot assert verified labels')
            _require(isinstance(question.get('unknown_reasons'), list) and bool(question['unknown_reasons']),
                     'unknown answer needs its unresolved source reason')
        value = deepcopy(question)
        value['question_id'] = identity
        result[key] = value
    if 'counts' in metadata:
        counts = metadata['counts']
        expected = {'questions': len(result), 'papers': len({paper for paper, _ in result}),
            **{status: sum(q['status'] == status for q in result.values()) for status in ('verified', 'unknown')}}
        _require(isinstance(counts, dict) and all(type(counts.get(k)) is int and counts[k] == value
                 for k, value in expected.items()), 'reading metadata coverage counts do not reconcile')
    return result


def apply_question_metadata(row, usage, index):
    """Return usage labels without changing the source row or its token count.

    Printed options and derived stem candidates remain separate origins. A
    completion's ``correctOptionLabel`` names its display candidate only.
    """
    _require(isinstance(row, dict) and isinstance(usage, dict), 'invalid reading usage input')
    _require(isinstance(index, _QuestionMetadataIndex), 'reading metadata index must be validated')
    result = deepcopy(usage)
    paper = row.get('paper_id', row.get('paperId'))
    provenance, display = row.get('source_provenance') or {}, row.get('display') or {}
    _require(isinstance(provenance, dict) and isinstance(display, dict), 'invalid source or display provenance')
    evidence = provenance.get('sourcePathEvidence') or {}
    derived = display.get('derivation_payload') or {}
    prior = usage.get('reading_candidate') or {}
    candidates = [evidence, derived, prior, row.get('option_context') or {}, row.get('reading_completion') or {}]
    _require(all(isinstance(part, dict) for part in candidates), 'invalid reading candidate metadata')
    identities = {_question_id(paper, value) for part in candidates
                  if (value := part.get('questionId', part.get('question_id'))) is not None}
    _require(len(identities) <= 1, 'conflicting exact question identities')
    if not identities:
        return result
    identity = next(iter(identities))
    question = index.get((paper, identity))
    if question is None:
        return result
    kind = evidence.get('kind', usage.get('source_kind'))
    if kind not in {'answer_option', 'question_prompt'}:
        return result
    _require(not any(part.get(key) == 'cloze' for part in candidates
                     for key in ('sectionKind', 'questionKind')), 'reading metadata conflicts with explicit cloze source')
    role, origin = ('reading_option', 'option') if kind == 'answer_option' else ('question_stem', 'stem')
    printed = evidence.get('optionLabel') if kind == 'answer_option' else None
    candidate_labels = {_label(part['candidateOptionLabel']) for part in candidates
                        if part.get('candidateOptionLabel') is not None}
    if printed is not None:
        candidate_labels.add(_label(printed))
    _require(len(candidate_labels) <= 1, 'conflicting printed and derived candidate option labels')
    candidate = next(iter(candidate_labels), None)
    if candidate is None:
        value = (derived.get('correctOptionLabel') if kind == 'question_prompt' else None)
        value = value if value is not None else prior.get('option_label')
        candidate = _label(value) if value is not None else None
    explicit = {part['isCorrectCandidate'] for part in [*candidates, row]
                if part.get('isCorrectCandidate') is not None and type(part['isCorrectCandidate']) is bool}
    _require(all(part.get('isCorrectCandidate') is None or type(part['isCorrectCandidate']) is bool
                 for part in [*candidates, row]), 'invalid explicit candidate correctness')
    # Core option usage retains the explicit flag as correctness, after dropping
    # its original boolean. A stem completion can infer "correct" from its
    # display label, so that inference cannot be used as an explicit assertion.
    prior_correctness = prior.get('correctness', usage.get('reading_candidate_correctness'))
    if kind == 'answer_option' and prior_correctness in {'correct', 'incorrect'}:
        _require(prior.get('option_label') is None or _label(prior['option_label']) == candidate,
                 'explicit option usage conflicts with original printed candidate label')
        explicit.add(prior_correctness == 'correct')
    _require(len(explicit) <= 1, 'conflicting explicit candidate correctness')
    _require(not explicit or candidate is not None, 'explicit candidate correctness needs its option label')
    correctness, basis = ('not_applicable', 'original_stem') if candidate is None else ('unknown', 'unverified_answer')
    if candidate is not None and question['status'] == 'verified':
        _require(candidate in question['correct_labels'] + question['incorrect_labels'],
                 'candidate label absent from source question options')
        verified = candidate in question['correct_labels']
        _require(not explicit or verified in explicit, 'explicit isCorrectCandidate conflicts with source answer')
        correctness, basis = ('correct' if verified else 'incorrect'), 'verified_question_metadata'
    elif explicit:
        correctness = 'correct' if next(iter(explicit)) else 'incorrect'
        basis = 'existing_explicit_candidate'
    result.update(source_role=role,
        reading_candidate_correctness=correctness if origin == 'option' else 'not_applicable')
    result['reading_candidate'] = {**deepcopy(prior), 'question_id': paper + ':' + identity,
        'option_label': candidate, 'correctness': correctness, 'match_origins': [origin]}
    result['reading_answer_metadata'] = {'status': question['status'],
        'question_id': paper + ':' + identity, 'source_pin': deepcopy(question['source_pin']),
        'correctness_basis': basis}
    return result
