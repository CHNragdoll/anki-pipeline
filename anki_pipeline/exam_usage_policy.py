"""Apply reviewed usage/sense decisions to a new snapshot, never to raw sources."""
from copy import deepcopy

from . import sense_frequency as sf
from .exam_frequency import exclude_cloze_option, frequency_breakdown_for_matches
from .exam_usage import POLICY, occurrence_sentence, occurrence_usage
from .sense_display import refresh_derived_chunks


def producer_record(prepared, *, preserve_scope=True):
    """Recover the producer shape while retaining all original semantic seals."""
    if preserve_scope and 'candidate_scope' in prepared:
        result = deepcopy(prepared['candidate_source_record'])
        result['candidate_scope'] = deepcopy(prepared['candidate_scope'])
        return result
    result = deepcopy(prepared)
    indices = {sense['sense_id']: sense['ordinal'] for sense in prepared['senses']}
    for row in result['occurrences']:
        row['sense_index'] = indices[row['sense_id']] if row['status'] == 'reviewed' else None
    result.pop('candidate_scope', None)
    result.pop('candidate_source_record', None)
    return result


def assignment_pin(prepared, row):
    """Canonical hash of the exact persisted assignments row used by reviewers."""
    value = {key: row.get(key) for key in ('occurrence_id', 'sense_id', 'status',
        'reason', 'method', 'review_version', 'reviewed_sense_id', 'assignment_context_hash')}
    value['snapshot_id'] = prepared['snapshot_id']
    value['matching_proposal_json'] = sf._json(row['matching_proposal']) if 'matching_proposal' in row else None
    return sf._sha(sf._json(value))


def _verified_cloze_reversal(row, proof):
    """Recheck the recorded answer substitution without changing the target."""
    if not isinstance(proof, dict) or proof.get('verified') is not True:
        return False
    source = row['source_provenance']
    answers = row.get('display', {}).get('provenance', {}).get('source_cloze_answers', [])
    if (not answers or proof.get('answer_replacements') != answers
            or proof.get('source_hash') != source.get('sourceHash')
            or not proof.get('source_hash') or len(proof['source_hash']) != 64
            or proof.get('source_block_ids') != source.get('sourceBlockIds')
            or not proof.get('source_block_ids')
            or proof.get('target_is_answer_replacement') is not False
            or proof.get('original_sentence_unique_in_verified_paragraph') is not True):
        return False
    english = row['english']
    start, end = row['target_range']
    previous_end = 0
    ordered = sorted(answers, key=lambda item: item.get('start', -1))
    for answer in ordered:
        a, b, number = answer.get('start'), answer.get('end'), answer.get('number')
        if (type(a) is not int or type(b) is not int or type(number) is not int
                or not 1 <= number <= 20 or not previous_end <= a < b <= len(english)
                or english[a:b] != answer.get('word') or (a < end and b > start)):
            return False
        previous_end = b
    restored = english
    for answer in reversed(ordered):
        restored = restored[:answer['start']] + str(answer['number']) + restored[answer['end']:]
    shift = sum(len(str(answer['number'])) - (answer['end'] - answer['start'])
                for answer in ordered if answer['end'] <= start)
    bounds = [start + shift, end + shift]
    return (proof.get('reversed_answer_sentence') == restored
            and proof.get('untouched_target_range_in_reversed_sentence') == bounds
            and restored[bounds[0]:bounds[1]] == english[start:end]
            and proof.get('original_source_target_text') == english[start:end])


def _confirmed_rehomes(baseline, policy):
    rows = {row['occurrence_id']: row for row in baseline['occurrences']}
    result = []
    for audit in policy.get('confirmed_new_exclusions', []):
        identity = audit.get('occurrence_id')
        row = rows.get(identity)
        if (row is None or any(audit.get(key) != baseline[key] for key in ('book_id', 'card_id', 'word'))
                or audit.get('exclusion_verified') is not True
                or audit.get('ownership_status') != 'rehome_verified'
                or audit.get('decision_status') != 'keep_exclusion'):
            raise ValueError('reviewed rehome lacks a current verified ownership audit')
        if (audit.get('previous_status') != row['status'] or audit.get('previous_sense_id') != row['sense_id']
                or row['status'] not in {'reviewed', 'ambiguous', 'unmatched'}
                or audit.get('english') != row['english']):
            raise ValueError('reviewed rehome original assignment changed')
        source = audit.get('source_identity', {})
        if any(source.get(key) != row[key] for key in
                ('paper_id', 'sentence_id', 'physical_source', 'english_hash', 'target_range')):
            raise ValueError('reviewed rehome original physical source changed')
        checks = audit.get('source_checks', {})
        if (checks.get('english_hash_valid') is not True or checks.get('exact_target_match') is not True
                or not (checks.get('materialized_raw_sentence_contained') is True
                    or checks.get('frozen_context_sentence_contained') is True
                    or _verified_cloze_reversal(row, checks.get('recorded_cloze_answer_reversal')))):
            raise ValueError('reviewed rehome needs verified original source evidence')
        targets = audit.get('targets', [])
        if (not audit.get('reason') or not targets or any(
                target.get('status') != 'reviewed' or target.get('verified_physical_match') is not True
                or not target.get('matched_sense') or target.get('card_id') == baseline['card_id']
                for target in targets)):
            raise ValueError('reviewed rehome needs a distinct verified destination and its actual sense')
        result.append({'occurrence_id': identity, 'occurrence': deepcopy(row),
            'exclusion_kind': 'reviewed_rehome', 'ownership': deepcopy(audit),
            'authority': {'source_parent_snapshot_id': baseline['snapshot_id'],
                'source_parent_row_sha256': sf._sha(sf._json(row)), 'audit': deepcopy(audit)}})
    return result


def _validate_decision_binding(old, row, decision):
    for key in ('book_id', 'card_id', 'snapshot_id'):
        if decision.get(key) != old[key]:
            raise ValueError('residual decision has stale ' + key)
    for key in ('occurrence_id', 'english_hash', 'target_range'):
        if decision.get(key) != row[key]:
            raise ValueError('residual decision has stale ' + key)
    original_row = next(part for part in old['occurrences'] if part['occurrence_id'] == row['occurrence_id'])
    if decision.get('old_assignment_sha256') != assignment_pin(old, original_row):
        raise ValueError('residual assignment fingerprint changed')
    status = decision.get('status')
    if status not in {'reviewed', 'group', 'broad', 'ambiguous', 'unmatched'}:
        raise ValueError('unsupported residual decision')
    if not decision.get('reason') or not decision.get('evidence_ids'):
        raise ValueError('residual decision needs reason and source evidence')
    if status in {'reviewed', 'group', 'broad'} and not decision.get('dictionary_explanation'):
        raise ValueError('matched decision needs full dictionary explanation')
    if status == 'broad':
        actual_ids = {sense['sense_id'] for sense in old['senses']}
        candidates = decision.get('candidate_sense_ids')
        # The assigned upper meaning can be distinct from the unresolved finer
        # alternatives. Bind both to actual original senses; never manufacture
        # membership in the immutable review's finer-candidate list.
        if (decision.get('broad_flag') is not True or decision.get('sense_id') not in actual_ids
                or not isinstance(candidates, list) or not candidates
                or any(not isinstance(identity, str) or identity not in actual_ids for identity in candidates)
                or len(candidates) != len(set(candidates))):
            raise ValueError('broad match needs explicit flag, actual assigned broad sense and known distinct candidates')
    if status != 'broad' and decision.get('broad_flag') not in {None, False}:
        raise ValueError('non-broad decision cannot carry a broad flag')


def _decision(record, old, row, decision, *, new_index=None):
    _validate_decision_binding(old, row, decision)
    status = decision['status']
    indices = {sense['sense_id']: n for n, sense in enumerate(old['senses'])}
    row.pop('matching_proposal', None)
    row.pop('broad_match', None)
    row.pop('common_sense_match', None)
    row['status'] = 'reviewed' if status in {'reviewed', 'broad'} else 'ambiguous' if status in {'group', 'ambiguous'} else 'unmatched'
    row['reason'] = decision['reason']
    row['method'] = 'full-context-dictionary-explanation-review.v1'
    row['review_version'] = '20261012'
    if row['status'] == 'reviewed':
        if new_index is not None:
            row['sense_index'] = new_index
        elif decision.get('sense_id') not in indices:
            raise ValueError('reviewed decision must identify an actual current sense')
        else:
            row['sense_index'] = indices[decision['sense_id']]
    else:
        row['sense_index'] = None
        row['reviewed_sense_id'] = row['assignment_context_hash'] = None
    if status in {'group', 'broad'}:
        metadata = {'candidate_sense_ids': decision.get('candidate_sense_ids', []),
            'reason': decision['reason'], 'method': 'context-review', 'review_version': '20261012'}
        if status == 'broad': metadata['label'] = '上下文仅能确认广义'
        current = sf._definition(record)['senses']
        metadata['candidate_sense_ids'] = [current[indices[identity]]['sense_id']
            for identity in metadata['candidate_sense_ids'] if identity in indices]
        if status == 'broad':
            # Presentation grouping includes the actual counted assignment as
            # well as finer alternatives; semantic_review remains unchanged.
            assigned = current[row['sense_index']]['sense_id']
            metadata['candidate_sense_ids'] = list(dict.fromkeys([assigned, *metadata['candidate_sense_ids']]))
        row['common_sense_match' if status == 'group' else 'broad_match'] = metadata
    row['semantic_review'] = deepcopy(decision)
    return sf.seal_reviewed_assignment(record, row) if row['status'] == 'reviewed' else row


def dictionary_name_zh(source):
    """Translate a validated dictionary identity; retain its original name separately."""
    pin = source.get('source_ref_pin', {})
    name = source.get('name', '')
    identity = str(pin.get('dictionary') or name).replace('’', "'")
    names = {
        'oald10': '牛津高阶英汉双解词典', 'cald4': '剑桥高阶英汉双解词典',
        'mw-now': '韦氏词典（MW-Now 本地版）',
        "Oxford Advanced Learner's Dictionary": '牛津高阶英语词典',
        'Merriam-Webster.com Dictionary': '韦氏在线词典',
        'Collins English Dictionary': '柯林斯英语词典',
        "Collins / Webster's New World College Dictionary": '韦氏新世界大学词典（柯林斯在线版）',
        "Webster's New World College Dictionary": '韦氏新世界大学词典（柯林斯在线版）',
        'Random House Unabridged via Collins': '兰登书屋英语大词典（柯林斯在线版）',
        'Collins / Penguin Random House American English': '兰登书屋美式英语词典（柯林斯在线版）',
        'Collins American English 1 (Random House source)': '兰登书屋美式英语词典（柯林斯在线版）',
        'American Heritage Dictionary of the English Language': '美国传统英语词典',
        "Cambridge Advanced Learner's Dictionary & Thesaurus": '剑桥高阶英语词典及同义词词典',
    }
    return names.get(identity, name)


def _append_definitions(result, decisions, *, registry=()):
    """Append only explicitly reviewed and source-pinned dictionary definitions."""
    appended, indices, seen = [], {}, {}
    for identity, decision in decisions.items():
        sense = decision.get('new_sense')
        if not sense:
            continue
        if decision.get('status') != 'reviewed' or decision.get('sense_id') is not None:
            raise ValueError('a new definition must be an explicitly reviewed new sense')
        for key in ('pos', 'text', 'original_english', 'translation_kind'):
            if not isinstance(sense.get(key), str) or not sense[key].strip():
                raise ValueError('new definition missing ' + key)
        kind = sense['translation_kind']
        if kind not in {'original', 'cross_dictionary_original', 'reviewed_translation'}:
            raise ValueError('new definition has unsupported translation attribution')
        if kind == 'original' and not sense.get('original_chinese'):
            raise ValueError('original Chinese attribution needs native Chinese')
        pins = decision.get('dictionary_source_pins')
        if (not isinstance(pins, list) or not pins or
                any(not isinstance(pin, dict) or not pin for pin in pins)):
            raise ValueError('new definition needs actual dictionary source pins')
        from .dictionary_review_evidence import validate_new_sense
        verified_evidence = validate_new_sense(decision, registry=registry)
        key = sf._json([sense, pins])
        if key not in seen:
            index = len(result['senses'])
            seen[key] = index
            result['senses'].append({'pos': sense['pos'], 'text': sense['text']})
            source = decision['dictionary_explanation']
            appended.append({'ordinal': index, 'source_dictionary': source['source'],
                'source_name_zh': dictionary_name_zh(source), 'source_name_original': source['name'],
                'source_version': source['version'],
                'source_headword': source['exact_entry'], 'sense_ref': source['sense'],
                'english': sense['original_english'], 'original_chinese': sense.get('original_chinese'),
                'translation_kind': kind, 'translation_label': '补译' if kind == 'reviewed_translation' else '词典原译',
                'scope_kind': sense.get('scope_kind', 'headword'),
                'target_lemma': decision.get('target_lemma'),
                'source_pins': deepcopy(pins), 'native_definition': deepcopy(source),
                'review_evidence': deepcopy(decision), 'validated_source_evidence': verified_evidence})
        indices[identity] = seen[key]
    if appended:
        supplement = result['definition_provenance'].setdefault('supplemental_definitions', {})
        supplement.setdefault('appended', []).extend(appended)
    return indices, appended


def transform_record(record, *, baseline_prepared, policy=None, residual_decisions=None,
                     sense_groups=None, excluded_occurrences=None):
    """Return producer record + lossless scope ledger for an isolated new DB.

    Exclusions require an authority object and the complete baseline occurrence.
    All old semantic bindings are validated before filtering or presentation edits.
    """
    baseline = sf.prepare_record(producer_record(baseline_prepared))
    if baseline['snapshot_id'] != baseline_prepared['snapshot_id']:
        raise ValueError('baseline payload no longer reproduces its immutable snapshot')
    incoming = sf.prepare_record(record)
    if incoming['snapshot_id'] != baseline['snapshot_id']:
        raise ValueError('policy input must be the exact accepted parent snapshot')
    policy = policy or {}
    if policy.get('policy', POLICY) != POLICY:
        raise ValueError('unknown counting policy')
    result = producer_record(baseline, preserve_scope=False)
    old_rows = {row['occurrence_id']: row for row in baseline['occurrences']}
    exclusions = {}
    for item in [*(excluded_occurrences or []), *_confirmed_rehomes(baseline, policy)]:
        identity = item.get('occurrence_id')
        if identity not in old_rows or identity in exclusions:
            raise ValueError('exclusion must identify one current physical occurrence')
        if not item.get('authority') or item.get('exclusion_kind') not in {'wrong_lemma', 'cloze_option', 'reviewed_rehome'}:
            raise ValueError('exclusion needs exact review authority and kind')
        source = item.get('occurrence', item)
        if any(source.get(key) != old_rows[identity].get(key) for key in
               ('english_hash', 'target_range', 'physical_source')):
            raise ValueError('exclusion source binding is stale')
        exclusions[identity] = deepcopy(item)
    display_projections, projection_ledger = {}, []
    projection_policy = policy.get('reading_display_projection')
    if projection_policy is not None:
        from .reading_display_projection import replay_projection
        if (not isinstance(projection_policy, dict) or set(projection_policy) != {'authority', 'entries'}
                or not isinstance(projection_policy['entries'], dict)):
            raise ValueError('reading display projection needs exact authority and occurrence entries')
        for identity, item in projection_policy['entries'].items():
            if (identity not in old_rows or item.get('occurrence_id') != identity
                    or item.get('book_id') != baseline['book_id'] or item.get('card_id') != baseline['card_id']
                    or item.get('snapshot_id') != baseline['snapshot_id']):
                raise ValueError('reading display projection must bind the exact parent card and snapshot')
            original = old_rows[identity]
            if identity in exclusions or exclude_cloze_option(occurrence_sentence(original)):
                continue
            view = replay_projection(projection_policy['authority'], item, original,
                book_id=baseline['book_id'], card_id=baseline['card_id'],
                definition_provenance=baseline['definition_provenance'])
            display_projections[identity] = view
            projection_ledger.append({'occurrence_id': identity, 'projection': deepcopy(item),
                'authority': deepcopy(projection_policy['authority']), 'parent_snapshot_id': baseline['snapshot_id'],
                'parent_display_sha256': original['display']['display_hash'],
                'target_display_sha256': view['display_hash']})
    decisions = {}
    decision_ids = set()
    ignored_decisions = []
    for item in residual_decisions or []:
        identity = item.get('occurrence_id')
        if identity in decision_ids or identity not in old_rows:
            raise ValueError('residual decisions must have unique current identities')
        decision_ids.add(identity)
        _validate_decision_binding(baseline, old_rows[identity], item)
        if identity in exclusions or exclude_cloze_option(occurrence_sentence(old_rows[identity])):
            ignored_decisions.append({'decision': deepcopy(item), 'reason': 'physical source excluded by the current counting/ownership policy'})
        else:
            decisions[identity] = item
    new_indices, new_definitions = _append_definitions(result, decisions,
        registry=policy.get('verified_dictionary_sources', ()))
    semantic_rebindings = []
    if new_definitions:
        # Definition fingerprints include the source inventory. Preserve the
        # old semantic ordinal and record every purely technical reseal.
        # Definitions stay unchanged throughout this loop. Validate their
        # complete provenance once, retaining the original per-row checks.
        definition_data = sf._definition(result)
        for row in result['occurrences']:
            if row['status'] == 'reviewed':
                old_seal = row['assignment_context_hash']
                checked = sf._occurrence(row, definition_data, require_binding=False)
                sealed = deepcopy(row)
                sealed['reviewed_sense_id'] = checked['reviewed_sense_id']
                sealed['assignment_context_hash'] = checked['assignment_context_hash']
                row.update(sealed)
                semantic_rebindings.append({'occurrence_id': row['occurrence_id'],
                    'sense_ordinal': row['sense_index'], 'old_context_hash': old_seal,
                    'new_context_hash': row['assignment_context_hash'], 'reason': 'source-pinned definition append; original semantic ordinal retained'})
            if 'matching_proposal' in row:
                row['matching_proposal'] = sf.seal_matching_proposal(result, row, row['matching_proposal'])
    kept, removed, changed = [], [], []
    for row in result['occurrences']:
        identity = row['occurrence_id']
        cloze = exclude_cloze_option(occurrence_sentence(row))
        if cloze or identity in exclusions:
            prior = exclusions.get(identity)
            removed.append({'occurrence_id': identity,
                'exclusion_kind': 'cloze_option' if cloze else exclusions[identity]['exclusion_kind'],
                'authority': deepcopy(prior['authority']) if prior else {'policy': POLICY},
                'counting_policy': POLICY,
                'occurrence': deepcopy(old_rows[identity]),
                'ownership': deepcopy(prior.get('ownership')) if prior else None,
                'prior_exclusion': deepcopy(prior) if prior else None})
            continue
        row['usage'] = occurrence_usage(row, options=policy.get('options'), completions=policy.get('completions'))
        if policy.get('reading_answers') is not None:
            from .reading_usage_metadata import apply_question_metadata
            row['usage'] = apply_question_metadata(row, row['usage'], policy['reading_answers'])
        if identity in display_projections:
            row['display'] = deepcopy(display_projections[identity])
        if row.get('display'):
            row = refresh_derived_chunks(row)
        if identity in decisions:
            row = _decision(result, baseline, row, decisions[identity], new_index=new_indices.get(identity))
            changed.append(deepcopy(decisions[identity]))
        if row['status'] != 'reviewed':
            reason = row['reason']
            row['pending_category'] = ('原文待核对' if any(word in reason for word in ('OCR', '源文本', '原文异常', '误字', '缺字')) else
                '选项用法未明确' if row['usage']['source_role'] == 'reading_option' else
                '义项未细分' if row['status'] == 'ambiguous' else '缺少对应义项')
        kept.append(row)
    result['occurrences'] = kept
    result['expected_occurrences'] = len(kept)
    if sense_groups:
        result['sense_group_equivalences'] = deepcopy(sense_groups)
    current_senses = sf._definition(result)['senses']
    old_to_new = {old['sense_id']: current_senses[n]['sense_id'] for n, old in enumerate(baseline['senses'])}
    for certificate in result.get('sense_group_equivalences', []):
        certificate['member_sense_ids'] = [old_to_new.get(i, i) for i in certificate.get('member_sense_ids', [])]
        for evidence in certificate.get('evidence', []):
            if evidence.get('sense_id') in old_to_new: evidence['sense_id'] = old_to_new[evidence['sense_id']]
    kept_ids = {row['occurrence_id'] for row in kept}
    for identity, decision in decisions.items():
        if decision['status'] != 'group' or identity not in kept_ids:
            continue
        ids = decision.get('candidate_sense_ids', [])
        evidence = decision.get('candidate_explanations')
        if not decision.get('common_meaning') or not decision.get('usage_scope') or not evidence:
            raise ValueError('common sense needs a reviewed shared meaning, scope and per-member evidence')
        evidence = deepcopy(evidence)
        for part in evidence:
            if part.get('sense_id') in old_to_new: part['sense_id'] = old_to_new[part['sense_id']]
        certificate = {'member_sense_ids': [old_to_new.get(i, i) for i in ids],
            'meaning': decision['common_meaning'], 'usage_scope': decision['usage_scope'],
            'reason': decision['reason'], 'review_version': '20261012', 'evidence': evidence}
        certificates = result.setdefault('sense_group_equivalences', [])
        if not any(set(item['member_sense_ids']) == set(certificate['member_sense_ids']) for item in certificates):
            certificates.append(certificate)
    breakdown = frequency_breakdown_for_matches([
        (row['paper_id'], row['occurrence_id'], 0, 1, row['usage']) for row in kept],
        excluded_cloze_option_occurrences=sum(row['exclusion_kind'] == 'cloze_option' for row in removed))
    ledger = {'schema': 'exam-usage-scope-ledger.v1', 'policy': POLICY,
        'parent_snapshot_id': baseline['snapshot_id'], 'book_id': baseline['book_id'],
        'card_id': baseline['card_id'], 'original_count': len(old_rows), 'retained_count': len(kept),
        'retained_occurrence_ids': [row['occurrence_id'] for row in kept], 'excluded': removed,
        'semantic_decisions': changed, 'original_payload_sha256': sf._sha(sf._json(baseline)),
        'frequency_breakdown': breakdown, 'new_definitions': new_definitions,
        'technical_semantic_rebindings': [entry for entry in semantic_rebindings
            if entry['occurrence_id'] in kept_ids],
        'ignored_semantic_decisions': ignored_decisions,
        'prior_wrong_lemma_ids': [identity for identity, item in exclusions.items()
            if item['exclusion_kind'] == 'wrong_lemma']}
    if projection_ledger:
        ledger['reading_display_projections'] = projection_ledger
    if 'candidate_scope' in baseline:
        ledger['inherited_candidate_scope'] = deepcopy(baseline['candidate_scope'])
    if len(kept) + len(removed) != len(old_rows):
        raise ValueError('scope ledger lost an original physical occurrence')
    result['exam_usage_policy'] = deepcopy(ledger)
    prepared = sf.prepare_record(result)
    ledger['new_snapshot_id'] = prepared['snapshot_id']
    return {'record': result, 'scope_ledger': ledger}
