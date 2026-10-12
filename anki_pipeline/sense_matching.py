"""Auditable lexical *suggestions* for context review, never sense assignments.

An aligned Chinese phrase can help a reviewer find candidate dictionary senses.
It does not prove the sense: a chunk may contain other words, a translation may
be loose, and the dictionary may omit the contextual meaning or a homograph.
Consequently this module never produces ``reviewed`` or changes ``sense_index``.
Only target-linked ranges are inspected; whole-sentence keyword matching and
the assumption that a one-sense entry must be right are deliberately excluded.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re

from .translation_alignment import validate_translation_alignment


SCHEMA = 'exam-sense-proposal.v1'
METHOD = 'target-aligned-gloss-candidates.v1'
_HANZI = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
_WORDS = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
_QUALIFIER = re.compile(r'\([^()]*\)|（[^（）]*）')
_GENERIC = frozenset({'某人', '某事', '一种', '一类', '事情', '东西', '有关', '表示',
                      '进行', '方式', '方面', '情况', '可以', '能够', '使得', '作为'})
_FUNCTION_GLOSSES = _GENERIC | frozenset({'我们', '他们', '你们', '这个', '那个', '这些', '那些',
    '这里', '那里', '什么', '任何', '所有', '某些', '每个', '各自', '自己', '一些', '许多',
    '其他', '其他的', '另外', '不是', '没有', '不能', '应该', '必须', '以及', '为了',
    '因为', '所以', '但是', '如果', '由于', '关于', '可能'})
_FUNCTION_POS = re.compile(r'\b(?:pron|pronoun|prep|preposition|conj|conjunction|det|determiner|'
                           r'article|art|aux|auxiliary|modal|numeral|number|num)\b', re.I)
_NUMERIC_GLOSS = re.compile(r'(?:第)?[零〇一二三四五六七八九十百千万亿两几]+(?:个|次|项)?\Z')


@dataclass(frozen=True)
class MatchingPolicy:
    """Limits apply to suggestions, not to a claimed semantic confidence score."""
    max_english_words: int = 8
    max_translation_characters: int = 24
    min_gloss_hanzi: int = 2

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in (
                self.max_english_words, self.max_translation_characters, self.min_gloss_hanzi)):
            raise ValueError('matching limits must be positive integers')


DEFAULT_POLICY = MatchingPolicy()


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _span(value, text):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(n) is not int for n in value) or not 0 <= value[0] < value[1] <= len(text)):
        raise ValueError('invalid Unicode codepoint alignment range')
    return tuple(value)


def _ranges(values, text):
    if not isinstance(values, list):
        raise ValueError('alignment ranges must be an array')
    return tuple(_span(value, text) for value in values)


def _merged(ranges):
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


def _lexical_body(text):
    positions = [i for i, char in enumerate(text) if char.isalnum()]
    return (positions[0], positions[-1] + 1) if positions else (0, len(text))


def _aligned_scope(occurrence, english, translation, target, supplied_ranges):
    """Select the same finest range as the existing sentence alignment renderer."""
    payload = occurrence.get('alignment', occurrence.get('translation_alignment'))
    legacy = occurrence.get('translation_alignment')
    if payload is not None and legacy is not None and payload != legacy:
        raise ValueError('conflicting canonical and legacy alignment payloads')
    if payload is not None:
        validate_translation_alignment(english, translation, payload)
        entries = [(tuple(item['en']), tuple(tuple(span) for span in item['zh']), item['relation'])
                   for item in payload['alignments']]
        provenance = 'hash-validated-translation-alignment'
    else:
        evidence = occurrence.get('alignment_evidence')
        if evidence is None:
            return None, 'missing_alignment'
        if not isinstance(evidence, list):
            raise ValueError('alignment_evidence must be an array')
        entries = []
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError('alignment evidence must be an object')
            relation = item.get('relation', 'equivalent')
            if relation not in {'equivalent', 'implicit', 'untranslated'}:
                raise ValueError('unknown extracted alignment relation')
            entries.append((_span(item.get('english_range'), english),
                            _ranges(item.get('translation_ranges'), translation), relation))
        provenance = 'extracted-target-alignment'
    covering = list(dict.fromkeys((span, ranges, relation) for span, ranges, relation in entries
                                 if span[0] <= target[0] and target[1] <= span[1]))
    if not covering:
        return None, 'missing_alignment'
    exact = [entry for entry in covering if entry[0] == target]
    if exact:
        smallest = exact
    else:
        width = min(span[1] - span[0] for span, _, _ in covering)
        smallest = [entry for entry in covering if entry[0][1] - entry[0][0] == width]
    if len(smallest) != 1:
        return None, 'ambiguous_alignment'
    span, ranges, relation = smallest[0]
    # Rendering may deliberately retain all authored overlapping chunks. Their
    # union is distinct from the finest scope used for lexical suggestions.
    if payload is None and _merged(ranges) != _merged(supplied_ranges):
        raise ValueError('declared target translation ranges do not match the finest alignment')
    body = _lexical_body(english)
    if span != target and span[0] <= body[0] and body[1] <= span[1]:
        return None, 'broad_alignment'
    if relation != 'equivalent':
        return None, 'untranslated_target'
    return {'english_range': list(span), 'translation_ranges': [list(value) for value in ranges],
            'alignment_source': provenance, 'target_only': span == target}, None


def _gloss_parts(text):
    # Commas inside qualifiers cannot create unrelated dictionary keywords.
    parts, start, depth = [], 0, 0
    for index, char in enumerate(text):
        if char in '(（': depth += 1
        elif char in ')）': depth = max(0, depth - 1)
        elif char in ';；,，' and depth == 0:
            parts.append(text[start:index]); start = index + 1
    parts.append(text[start:])
    return parts


def _gloss_atoms(text, policy):
    atoms = []
    for part in _gloss_parts(text):
        source = part.strip()
        # Qualifiers remain in the evidence, and are never grounds to confirm.
        plain = _QUALIFIER.sub('', source).strip()
        plain = re.sub(r'\s+', '', plain).strip('：:。.!！?？')
        if len(_HANZI.findall(plain)) < policy.min_gloss_hanzi or plain in _GENERIC:
            continue
        for atom in (plain, plain[:-1] if plain.endswith('的') else plain):
            if (len(_HANZI.findall(atom)) >= policy.min_gloss_hanzi and atom not in _GENERIC
                    and all(item['atom'] != atom for item in atoms)):
                atoms.append({'atom': atom, 'source': source, 'qualifier_removed': plain != source})
    return atoms


def _proposal(reason_code, *, status='unmatched', candidates=(), scope=None):
    reasons = {
        'missing_alignment': '没有可归因到目标词的英中对应，不能使用整句译文分配义项。',
        'ambiguous_alignment': '多个同样细的对应范围无法区分，等待上下文核对。',
        'broad_alignment': '对应覆盖整句或英文范围过宽，不能把范围内的中文词归给目标词。',
        'broad_translation': '目标对应的中文范围过宽，不能作为义项候选证据。',
        'untranslated_target': '目标词在译文中隐含或未译出，不能从其他词的对应借用义项证据。',
        'no_discriminating_gloss': '目标对应范围中没有可区分的词典释义原词，等待上下文核对。',
        'overlapping_senses': '目标对应范围支持多个释义，不能按列表顺序决定归属。',
        'aligned_gloss_candidate': '目标对应范围与词典释义存在明确文字对应，仅供上下文核对。',
        'unmapped_component_target': '组合词条中无法确定目标词所属的来源分量，等待逐条核对。',
    }
    return {'schema': SCHEMA, 'method': METHOD, 'status': status,
            'automatic_confirmation': False, 'reason_code': reason_code,
            'reason': reasons[reason_code], 'candidate_sense_indices': [item['sense_index'] for item in candidates],
            'candidates': list(candidates), 'alignment_scope': scope,
            'exact_match_eligibility': {'schema': 'exam-sense-exact-eligibility.v1',
                'eligible': False, 'automatic_confirmation': False,
                'candidate_sense_index': None, 'rejection_reasons': [reason_code], 'evidence': None}}


def _exact_match_eligibility(senses, occurrence, scope, candidates, headword, allowed):
    """A strict review queue, still not a license to confirm a semantic meaning."""
    result = {'schema': 'exam-sense-exact-eligibility.v1', 'eligible': False,
              'automatic_confirmation': False, 'candidate_sense_index': None,
              'rejection_reasons': [], 'evidence': None}
    failures = result['rejection_reasons']
    payload = occurrence.get('alignment', occurrence.get('translation_alignment'))
    if payload is None:
        failures.append('requires_hash_validated_full_alignment')
        return result
    english, translation = occurrence['english'], occurrence['translation']
    target_start, target_end = occurrence['target_range']
    if headword is None:
        failures.append('requires_source_headword')
    elif english[target_start:target_end] != headword:
        # Inflection, nominalization, participles and capitalized proper names
        # need grammatical/context review even if their Chinese gloss is exact.
        failures.append('changed_form_or_case_requires_context_review')
    start, end = scope['english_range']
    left, right = _lexical_body(english[start:end])
    if [start + left, start + right] != occurrence['target_range']:
        failures.append('english_scope_contains_other_lexical_content')
    ranges = _merged(scope['translation_ranges'])
    if len(ranges) != 1:
        failures.append('requires_one_continuous_translation_phrase')
        return result
    zh_start, zh_end = ranges[0]
    phrase = translation[zh_start:zh_end].strip()
    if (len(_HANZI.findall(phrase)) < 2 or phrase in _FUNCTION_GLOSSES or
            _NUMERIC_GLOSS.fullmatch(phrase) or any(char.isdigit() for char in phrase)):
        failures.append('generic_numeric_or_function_gloss')
    # A broad or separate English chunk sharing the same Chinese phrase makes
    # attribution nonexclusive even when the selected English chunk is exact.
    overlaps = [entry['en'] for entry in payload['alignments']
                if entry['en'] != scope['english_range'] and any(
                    span[0] < zh_end and zh_start < span[1] for span in entry['zh'])]
    if overlaps:
        failures.append('translation_phrase_shared_with_other_english_scope')
    exact = []
    for index, sense in enumerate(senses):
        if index not in allowed:
            continue
        if any(part.strip() == phrase for part in _gloss_parts(sense['text'])):
            exact.append(index)
    if len(exact) != 1:
        failures.append('requires_one_exact_unmodified_dictionary_gloss')
    elif _FUNCTION_POS.search(senses[exact[0]].get('pos', '')):
        failures.append('functional_part_of_speech')
    if len(candidates) != 1:
        failures.append('other_lexical_senses_require_review')
    if failures:
        return result
    index = exact[0]
    result.update(eligible=True, candidate_sense_index=index, evidence={
        'english_range': scope['english_range'], 'english_text': english[start:end],
        'translation_range': [zh_start, zh_end], 'translation_text': phrase,
        'dictionary_gloss_atom': phrase, 'sense_text': senses[index]['text'],
        'sense_pos': senses[index].get('pos', ''),
        'english_hash': _hash(english), 'translation_hash': _hash(translation),
    })
    return result


def propose_match(senses, occurrence, *, policy=DEFAULT_POLICY, headword=None,
                  allowed_sense_indices=None):
    """Return transparent candidates without assigning a confirmed sense.

    Offsets address exact Unicode codepoints, and the source English hash must
    match. A supplied full alignment payload is hash-validated; extracted
    evidence must reconcile with the selected target translation ranges.
    No synonym expansion, English-context guessing or order tie-break occurs.
    """
    if not isinstance(senses, list) or not senses:
        raise ValueError('a nonempty dictionary sense list is required')
    if not isinstance(occurrence, dict):
        raise ValueError('occurrence must be an object')
    allowed = set(range(len(senses))) if allowed_sense_indices is None else set(allowed_sense_indices)
    if any(type(index) is not int or not 0 <= index < len(senses) for index in allowed):
        raise ValueError('candidate sense scope must use original dictionary ordinals')
    english, translation = occurrence.get('english'), occurrence.get('translation')
    if not isinstance(english, str) or not isinstance(translation, str):
        raise ValueError('English and translation must be exact strings')
    if occurrence.get('english_hash') != _hash(english):
        raise ValueError('stale source English hash')
    target = _span(occurrence.get('target_range'), english)
    supplied = _ranges(occurrence.get('translation_ranges', []), translation)
    scope, reason = _aligned_scope(occurrence, english, translation, target, supplied)
    if reason:
        return _proposal(reason)
    start, end = scope['english_range']
    if len(_WORDS.findall(english[start:end])) > policy.max_english_words:
        return _proposal('broad_alignment', scope=scope)
    if sum(right - left for left, right in _merged(scope['translation_ranges'])) > policy.max_translation_characters:
        return _proposal('broad_translation', scope=scope)
    candidates = []
    for index, sense in enumerate(senses):
        if index not in allowed:
            continue
        if not isinstance(sense, dict) or not isinstance(sense.get('text'), str):
            raise ValueError('dictionary senses must contain exact text')
        evidence = []
        for atom in _gloss_atoms(sense['text'], policy):
            # Discontinuous spans are not concatenated into invented phrases.
            for left, right in scope['translation_ranges']:
                fragment = translation[left:right]
                if atom['atom'] in fragment:
                    evidence.append({'gloss_atom': atom['atom'], 'source_gloss': atom['source'],
                                     'qualifier_removed': atom['qualifier_removed'],
                                     'translation_range': [left, right], 'translation_text': fragment,
                                     'english_range': scope['english_range'],
                                     'target_only_alignment': scope['target_only']})
        if evidence:
            candidates.append({'sense_index': index, 'pos': sense.get('pos', ''),
                               'sense_text': sense['text'], 'evidence': evidence})
    if not candidates:
        result = _proposal('no_discriminating_gloss', scope=scope)
    elif len(candidates) > 1:
        result = _proposal('overlapping_senses', status='ambiguous', candidates=candidates, scope=scope)
    else:
        result = _proposal('aligned_gloss_candidate', status='suggested', candidates=candidates, scope=scope)
    result['english_hash'] = _hash(english)
    result['translation_hash'] = _hash(translation)
    result['exact_match_eligibility'] = _exact_match_eligibility(
        senses, occurrence, scope, candidates, headword, allowed)
    return result


def _component_scope(record, occurrence):
    components = record['definition_provenance'].get('components', [])
    if len(components) <= 1:
        return None, record['word'], None
    token = occurrence['english'][slice(*occurrence['target_range'])]
    matching, allowed = [], set()
    for component in components:
        start, count = component.get('sense_start'), component.get('sense_count')
        if (type(start) is not int or type(count) is not int or count <= 0 or
                not 0 <= start < start + count <= len(record['senses'])):
            raise ValueError('invalid composite dictionary sense scope')
        headword = component.get('headword')
        if isinstance(headword, str) and token.casefold() == headword.casefold():
            matching.append(component); allowed.update(range(start, start + count))
    headword = matching[0]['headword'] if len(matching) == 1 else None
    return allowed, headword, [{key: item[key] for key in ('headword', 'sense_start', 'sense_count')}
                               for item in matching]


def propose_record(record, *, policy=DEFAULT_POLICY):
    """Annotate a validated record copy; preserve every manual status and sense."""
    from .sense_frequency import prepare_record, seal_matching_proposal

    prepare_record(record)
    result = deepcopy(record)
    for occurrence in result['occurrences']:
        allowed, headword, components = _component_scope(result, occurrence)
        if allowed == set():
            proposal = _proposal('unmapped_component_target')
        else:
            proposal = propose_match(result['senses'], occurrence, policy=policy,
                                     headword=headword, allowed_sense_indices=allowed)
        if components is not None:
            proposal['source_components'] = components
        occurrence['matching_proposal'] = seal_matching_proposal(
            result, occurrence, proposal)
    return result


def evaluate_reviewed_records(records, *, policy=DEFAULT_POLICY):
    """Measure candidate agreement on an explicitly limited reviewed sample.

    This is calibration for reviewer suggestions, not evidence that unreviewed
    assignments are semantically correct. Nothing is written to a database.
    """
    from .sense_frequency import prepare_record

    totals = Counter()
    comparisons = []
    seen = {}
    for record in records:
        prepared = prepare_record(record)
        for occurrence in prepared['occurrences']:
            identity = (record['word'], occurrence['occurrence_id'])
            if occurrence['status'] != 'reviewed':
                continue
            original = next(row for row in record['occurrences'] if
                            row['physical_source'] == occurrence['physical_source'] and
                            row['target_range'] == occurrence['target_range'])
            expected = original['sense_index']
            signature = (occurrence['english_hash'], occurrence['translation_hash'],
                         record['senses'][expected]['pos'], record['senses'][expected]['text'])
            if identity in seen:
                if seen[identity] != signature:
                    raise ValueError('conflicting reviews for the same physical token in calibration')
                continue
            seen[identity] = signature
            allowed, headword, _ = _component_scope(record, original)
            proposal = (_proposal('unmapped_component_target') if allowed == set() else
                        propose_match(record['senses'], original, policy=policy, headword=headword,
                                      allowed_sense_indices=allowed))
            candidates = proposal['candidate_sense_indices']
            totals['reviewed_tokens'] += 1
            totals[proposal['status']] += 1
            if candidates: totals['candidate_tokens'] += 1
            if expected in candidates: totals['expected_in_candidates'] += 1
            if len(candidates) == 1:
                totals['single_candidate_tokens'] += 1
                totals['single_candidate_correct'] += int(candidates[0] == expected)
            comparisons.append({'word': record['word'], 'occurrence_id': occurrence['occurrence_id'],
                                'sentence_id': occurrence['sentence_id'],
                                'target_range': occurrence['target_range'],
                                'english': occurrence['english'], 'translation': occurrence['translation'],
                                'expected_sense_index': expected,
                                'candidate_sense_indices': candidates,
                                'reason_code': proposal['reason_code']})
    denominator = totals['single_candidate_tokens']
    reviewed = totals['reviewed_tokens']
    return {'schema': 'exam-sense-proposal-evaluation.v1', 'method': METHOD,
            'automatic_confirmation': False, 'counts': dict(totals),
            'single_candidate_agreement': totals['single_candidate_correct'] / denominator if denominator else None,
            'single_candidate_coverage': denominator / reviewed if reviewed else None,
            'scope': 'Provided manually reviewed tokens only; not full-corpus semantic accuracy.',
            'comparisons': comparisons}
