"""Audited, reversible candidate exclusions for the a/an source-form error.

Only a caller-approved audit digest and a live source-displays capability can
issue an overlay. Serialized ledgers are evidence of consistency, not source
authority. No input records, source pages, files, or databases are modified.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

from . import sense_frequency_reconcile as reconcile


SCHEMA = 'exam-sense-candidate-scope.v1'
_ISSUER = object()
_REVIEW = frozenset({'status', 'sense_index', 'reason', 'method', 'review_version',
    'reviewed_sense_id', 'assignment_context_hash', 'matching_proposal', 'display',
    'semantic_review_provenance'})


def _row_context(row):
    return {key: value for key, value in row.items() if key not in _REVIEW}


def _record_context(record):
    return {key: value for key, value in record.items()
            if key not in {'occurrences', 'expected_occurrences', 'candidate_scope'}}


def _physical(row):
    return {field: deepcopy(row[field]) for field in
            ('paper_id', 'sentence_id', 'physical_source', 'target_range')}


def _read_approved(path, expected):
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError('a caller-approved audit SHA256 is required')
    path = Path(path).resolve()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('audit file differs from the caller-approved digest')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('approved audit must be an object')
    return value, {'path': str(path), 'sha256': expected}


def _inventory(audit_path, locator, expected, manifest_sha):
    directory = Path(audit_path).resolve().parent / 'full-inventory-v2'
    if hashlib.sha256((directory / 'inventory.json').read_bytes()).hexdigest() != manifest_sha:
        raise ValueError('audited inventory manifest changed')
    if (type(locator.get('byte_offset')) is not int or locator['byte_offset'] < 0 or
            type(locator.get('byte_length')) is not int or locator['byte_length'] <= 0):
        raise ValueError('audited inventory byte locator is invalid')
    path = directory / 'records.jsonl'
    with path.open('rb') as handle:
        handle.seek(locator['byte_offset'])
        raw = handle.read(locator['byte_length'])
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('audited original inventory record changed')
    record = json.loads(raw)
    if (reconcile._key(record) != (locator['book_id'], locator['card_id']) or
            record['word'] != locator['word'] or
            record['expected_occurrences'] != locator['occurrences'] or
            len(record['senses']) != locator['senses']):
        raise ValueError('audited inventory locator differs from its record')
    reconcile._physical_rows(record)
    return record, {'path': str(path), 'byte_locator': deepcopy(locator),
        'record_sha256': expected, 'manifest_sha256': manifest_sha}


def _primary_bindings(audit):
    if audit.get('schema') != 'codex-a-an-form-audit.v1':
        raise ValueError('unsupported candidate exclusion audit schema')
    summary = audit['summary']
    if (audit.get('pending') or audit.get('same_headword_as_records') or
            summary.get('pending_as') != 0 or
            summary.get('confirmed_same_original_article_headword_as') != 0 or
            summary.get('confirmed_letter_or_grade_a_noun_plural_as') != 0 or
            summary.get('safe_to_exclude_all_as_from_article_candidate_denominator') is not True or
            summary.get('non_as_candidate_count_is_not_certified_article_total') is not True):
        raise ValueError('audit does not authorize an exact other-lemma exclusion')
    snapshot = audit['source_snapshot']
    return {'book_id': audit['book_id'], 'card_id': audit['card_id'], 'word': 'a/an',
        'work_id': audit['work_id'], 'raw_total': summary['raw_physical_total'],
        'candidate_total': summary['non_as_candidate_count_after_overlay'],
        'indices': summary['excluded_as_indices'],
        'retained': audit['non_as_retained_candidate_indices'],
        'evidence': audit['confirmed_exclusions'], 'definition_provenance':
        audit['original_book_intent']['definition_provenance'],
        'locator': snapshot['inventory_record_byte_locator'],
        'inventory_sha': snapshot['inventory_record_sha256'],
        'page_path': snapshot['official_page'], 'page_sha': snapshot['official_page_sha256'],
        'forms_html': audit['word_form_origin']['formal_page_forms_raw'],
        'forms_range': audit['word_form_origin']['formal_page_form_raw_character_range'],
        'raw_casefold_counts': summary['raw_casefold_counts']}


def _supplement_binding(supplement, primary, primary_digest):
    if (supplement.get('schema') != 'codex-a-an-form-audit-2026-supplement.v1' or
            supplement['primary_audit']['sha256'] != primary_digest or
            supplement['primary_audit']['2027_work_id'] != primary['work_id'] or
            supplement['primary_audit']['2027_card_id'] != primary['card_id']):
        raise ValueError('2026 audit does not bind the approved primary audit')
    summary, binding = supplement['summary'], supplement['bindings']['a']
    if (summary.get('safe_to_reuse_primary_as_exclusion_by_exact_physical_binding') is not True or
            supplement.get('pending_2026_as_indices') or
            summary.get('2026_a_as_pending') != 0 or summary.get('2027_as_missing_in_2026')):
        raise ValueError('2026 audit has unresolved source mappings')
    originals = {item['global_index']: item for item in primary['confirmed_exclusions']}
    evidence = []
    for mapped in supplement['physical_evidence_map']:
        proof = originals.get(mapped['global_index_2027'])
        if (proof is None or mapped.get('identical_raw_english_translation_source_and_provenance') is not True or
                mapped.get('classification') != 'different_lemma_as' or
                any(mapped.get(field) != proof.get(field) for field in
                    ('physical_id', 'raw_english_hash', 'actual_token', 'source')) or
                mapped.get('context_proof_ref_in_primary_audit') != proof.get('context_proof_ref')):
            raise ValueError('2026 physical mapping differs from the original approved proof')
        proof = deepcopy(proof)
        proof.update(global_index=mapped['global_index_2026'], work_id=binding['work_id'],
                     mapped_primary_index=mapped['global_index_2027'])
        evidence.append(proof)
    total = binding['raw_occurrences']
    indices = supplement['strict_2026_as_exclusion_indices']
    excluded = set(indices)
    return {'book_id': binding['inventory_record_byte_locator']['book_id'],
        'card_id': binding['inventory_card_id'], 'word': 'a', 'work_id': binding['work_id'],
        'raw_total': total, 'candidate_total': summary['2026_a_candidate_total_after_as_only_overlay'],
        'indices': indices, 'retained': [i for i in range(total) if i not in excluded],
        'evidence': evidence, 'definition_provenance': binding['definition_provenance'],
        'locator': binding['inventory_record_byte_locator'],
        'inventory_sha': binding['inventory_record_sha256'],
        'page_path': binding['formal_page'], 'page_sha': binding['formal_page_sha256'],
        'forms_html': binding['formal_page_forms_raw'],
        'forms_range': binding['formal_page_forms_raw_character_range'],
        'raw_casefold_counts': binding['surface_casefold_counts']}


class CandidateCardScope(reconcile._ImmutableIssued):
    """One immutable, serializable ledger, also bound to its live filtered row."""
    __slots__ = ('_payload', '_raw_record', '_record_sha256')

    def __init__(self, payload, raw_record, record_sha256, *, _issuer=None):
        if _issuer is not _ISSUER:
            raise ValueError('candidate scope must be issued by the approved live overlay')
        object.__setattr__(self, '_payload', reconcile._json(payload))
        object.__setattr__(self, '_raw_record', reconcile._json(raw_record))
        object.__setattr__(self, '_record_sha256', record_sha256)

    def verification(self):
        return json.loads(self._payload)

    def _require(self, record, page):
        clean = {key: value for key, value in record.items() if key != 'candidate_scope'}
        if (reconcile._sha(reconcile._json(clean)) != self._record_sha256 or
                reconcile._sha(page) != self.verification()['source_page_sha256']):
            raise ValueError('candidate record or original page changed after the live overlay')
        validate_stored_scope(clean, self.verification())


class CandidateScopes(reconcile._ImmutableIssued):
    __slots__ = ('_cards', 'verified_sources')

    def __init__(self, cards, verified_sources, *, _issuer=None):
        if _issuer is not _ISSUER:
            raise ValueError('candidate scopes require an approved live overlay')
        object.__setattr__(self, '_cards', MappingProxyType(dict(cards)))
        object.__setattr__(self, 'verified_sources', verified_sources)

    def for_record(self, record):
        """Return the issued single-card scope, or None for an unchanged card."""
        scope = self._cards.get(reconcile._key(record))
        if scope is not None:
            clean = {key: value for key, value in record.items() if key != 'candidate_scope'}
            if reconcile._sha(reconcile._json(clean)) != scope._record_sha256:
                raise ValueError('candidate record changed after the live overlay')
        return scope

    def verification(self):
        return {'schema': SCHEMA, 'cards': [scope.verification() for scope in self._cards.values()]}


def _verify_evidence(row, item, binding, approved):
    start, end = row['target_range']
    if (item.get('work_id') != binding['work_id'] or item.get('physical_id') != _physical(row) or
            item.get('raw_english_hash') != row['english_hash'] or
            item.get('english') != row['english'] or item.get('translation') != row['translation'] or
            item.get('source') != row['source'] or item.get('source_provenance') != row['source_provenance'] or
            item.get('actual_token') != row['english'][start:end] or
            row['english'][start:end].casefold() != 'as' or
            not any(match.span() == (start, end) for match in reconcile._TOKEN.finditer(row['english'])) or
            item.get('classification') != 'different_lemma_as' or
            item.get('canonical_sentence_exact_match') is not True or
            item.get('same_original_article_headword') is not False or item.get('a_noun_plural') is not False or
            not isinstance(item.get('reason'), str) or not item['reason'].strip()):
        raise ValueError('approved exclusion differs from its exact raw physical/source context')
    if (row.get('status') not in {'pending', 'unmatched'} or row.get('sense_index') is not None or
            row.get('reviewed_sense_id') is not None or row.get('assignment_context_hash') is not None):
        raise ValueError('a reviewed assignment conflicts with the other-lemma exclusion')
    if (approved['canonical_physical_source'] != row['physical_source'] or
            approved['source_english_hash'] != row['english_hash'] or
            approved['source_reviewed_content_hash'] != row['source_provenance']['reviewedContentHash']):
        raise ValueError('exclusion is not bound to the live canonical source proof')


def apply_candidate_scope(records, pages, aliases, *, verified_sources, audit_path,
                          expected_audit_sha256, supplement_path=None,
                          expected_supplement_sha256=None):
    """Return fresh records and issued scopes after an approved, exact overlay.

    Audit paths resolve the adjacent ``full-inventory-v2`` byte snapshot. Review
    status/reasons/seals may legitimately differ from that original pending
    inventory; every linguistic/source field and definition snapshot must match.
    Additional words are never implicitly assigned exclusion authority.
    """
    if type(verified_sources) is not reconcile.VerifiedSourceDisplays:
        raise ValueError('candidate scope requires the live source-displays producer capability')
    if not isinstance(records, list):
        raise ValueError('candidate records must be an array')
    primary, approval = _read_approved(audit_path, expected_audit_sha256)
    binding = _primary_bindings(primary)
    bindings = {(binding['book_id'], binding['card_id']): binding}
    approvals = [approval]
    if supplement_path is not None or expected_supplement_sha256 is not None:
        supplement, other_approval = _read_approved(supplement_path, expected_supplement_sha256)
        other = _supplement_binding(supplement, primary, expected_audit_sha256)
        bindings[(other['book_id'], other['card_id'])] = other
        approvals.append(other_approval)
    snapshot = primary['source_snapshot']
    manifest = json.loads(verified_sources._source_manifest)
    # Reuse the producer's loaded canonical proofs rather than loading the whole
    # corpus again. Every audited source path must belong to that live manifest.
    for path, digest in snapshot['canonical_and_structured_files'].items():
        if manifest.get(path) != digest or hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('audited canonical source differs from the live producer manifest')
    original_meta = primary['original_book_intent'].get('raw_original_source', {})
    for path, digest in ((original_meta.get('file'), snapshot.get('original_csv_sha256')),
            (original_meta.get('selection_metadata_file'), snapshot.get('original_input_selection_sha256'))):
        if path and hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('approved original-book source evidence changed')
    result, cards, issued_bindings, issued_proofs = [], {}, {}, {}
    for record in records:
        key, page = reconcile._key(record), reconcile._page(pages, reconcile._key(record))
        verified_sources._require(page, record, aliases)
        if key in issued_bindings:
            raise ValueError('duplicate candidate book/card identity')
        current = deepcopy(record)
        bound = bindings.get(key)
        if bound is None:
            if record['book_id'] == 'redbook' and record['word'] == 'a':
                raise ValueError('2026 a requires its own approved supplementary source mapping')
            issued_proofs[key] = verified_sources._source_proofs[key]
        else:
            raw, inventory = _inventory(audit_path, bound['locator'], bound['inventory_sha'],
                                        snapshot['inventory_manifest_sha256'])
            rows = reconcile._physical_rows(record)
            if (record['word'] != bound['word'] or record['expected_occurrences'] != bound['raw_total'] or
                    _record_context(raw) != _record_context(record) or
                    raw['definition_provenance'] != bound['definition_provenance'] or
                    reconcile._sha(page) != bound['page_sha'] or
                    record['definition_provenance']['page_sha256'] != bound['page_sha'] or
                    hashlib.sha256(Path(bound['page_path']).read_bytes()).hexdigest() != bound['page_sha']):
                raise ValueError('candidate card, definitions or original source page changed')
            indices, retained = bound['indices'], bound['retained']
            if (any(type(i) is not int for i in indices + retained) or len(set(indices)) != len(indices) or
                    len(set(retained)) != len(retained) or set(indices) & set(retained) or
                    set(indices) | set(retained) != set(range(len(rows))) or
                    retained != sorted(retained) or len(retained) != bound['candidate_total']):
                raise ValueError('approved indices do not exactly partition the original candidate record')
            if any(_row_context(row) != _row_context(old) for row, old in zip(rows, raw['occurrences'])):
                raise ValueError('merged linguistic/source context differs from the audited raw inventory')
            evidence = {item['global_index']: item for item in bound['evidence']}
            if len(evidence) != len(bound['evidence']) or set(evidence) != set(indices):
                raise ValueError('approved exclusions have missing or duplicate physical indices')
            proofs = json.loads(verified_sources._source_proofs[key])
            if len(proofs) != len(rows):
                raise ValueError('live source proof count differs from the raw record')
            excluded = []
            for index in indices:
                row, item, approved = rows[index], evidence[index], proofs[index]
                _verify_evidence(row, item, bound, approved)
                excluded.append({'original_index': index, 'occurrence': deepcopy(row),
                    'occurrence_sha256': reconcile._sha(reconcile._json(row)),
                    'context_sha256': reconcile._sha(reconcile._json(_row_context(row))),
                    'reason': item['reason'], 'classification': 'different_lemma_as',
                    'audit_evidence': deepcopy(item), 'approved_canonical_source': approved})
            current['occurrences'] = [deepcopy(rows[i]) for i in retained]
            current['expected_occurrences'] = len(retained)
            retained_map = [{'original_index': i, 'candidate_index': candidate,
                'occurrence_sha256': reconcile._sha(reconcile._json(rows[i])),
                'context_sha256': reconcile._sha(reconcile._json(_row_context(rows[i])))}
                for candidate, i in enumerate(retained)]
            notice = (f"原始词形候选{len(rows)}次；已核实其中{len(excluded)}次为另一个 lemma as，"
                f"已从 a/an 冠词候选统计范围排除。剩余{len(retained)}次为候选，"
                "仍包含待区分的字母或选项 A，不能视为全部已确认的冠词用法。原始记录保留可查。")
            ledger = {'schema': SCHEMA, 'book_id': key[0], 'card_id': key[1], 'word': record['word'],
                'work_id': bound['work_id'], 'preview_only': True, 'raw_total': len(rows),
                'excluded_total': len(excluded), 'candidate_total': len(retained),
                'certified_article_total': None, 'candidate_total_is_certified_article_total': False,
                'source_page_sha256': reconcile._sha(page),
                'definition_provenance': deepcopy(record['definition_provenance']),
                'definition_context_sha256': reconcile._sha(reconcile._json(_record_context(record))),
                'raw_record_sha256': reconcile._sha(reconcile._json(record)),
                'candidate_record_sha256': reconcile._sha(reconcile._json(current)),
                'raw_linguistic_sha256': reconcile._sha(reconcile._json([_row_context(row) for row in rows])),
                'audit_files': approvals, 'inventory_source': inventory,
                'approved_source_manifest': manifest, 'producer_sha256': verified_sources._producer_sha256,
                'raw_casefold_counts': deepcopy(bound['raw_casefold_counts']),
                'original_forms': {'html': bound['forms_html'], 'range': bound['forms_range']},
                'retained_map': retained_map, 'excluded': excluded, 'notice': notice,
                'context_proofs': {item['context_proof_ref']: primary['context_proofs'][item['context_proof_ref']]
                    for item in bound['evidence']},
                'trust_boundary': 'approved audit digest plus live source-displays producer; JSON validation is consistency only'}
            ledger['ledger_sha256'] = reconcile._sha(reconcile._json(ledger))
            validate_stored_scope(current, ledger)
            cards[key] = CandidateCardScope(ledger, record, ledger['candidate_record_sha256'], _issuer=_ISSUER)
            issued_proofs[key] = reconcile._json([proofs[i] for i in retained])
        result.append(current)
        issued_bindings[key] = (reconcile._sha(reconcile._json(current)), reconcile._sha(page))
    derived = reconcile.VerifiedSourceDisplays(issued_bindings, verified_sources._producer_sha256,
        verified_sources._aliases_sha256, issued_proofs, manifest, _issuer=reconcile._ISSUER,
        candidate_ledger_hashes={key: scope.verification()['ledger_sha256'] for key, scope in cards.items()})
    return result, CandidateScopes(cards, derived, _issuer=_ISSUER)


def validate_stored_scope(record, scope):
    """Validate serialized ledger consistency; never grant live source authority.

    Reconstructs the complete original ordering and checks retained review seals
    byte-for-byte. This is suitable for immutable database payload validation.
    It does not reread sources and cannot replace ``apply_candidate_scope``.
    """
    if not isinstance(scope, dict) or scope.get('schema') != SCHEMA:
        raise ValueError('stored candidate scope has an unsupported schema')
    ledger = deepcopy(scope)
    digest = ledger.pop('ledger_sha256', None)
    if digest != reconcile._sha(reconcile._json(ledger)):
        raise ValueError('stored candidate ledger hash is stale')
    clean = {key: value for key, value in record.items() if key != 'candidate_scope'}
    if (reconcile._key(clean) != (scope['book_id'], scope['card_id']) or clean.get('word') != scope['word'] or
            clean.get('definition_provenance') != scope['definition_provenance'] or
            scope['source_page_sha256'] != clean['definition_provenance']['page_sha256'] or
            reconcile._sha(reconcile._json(_record_context(clean))) != scope['definition_context_sha256'] or
            reconcile._sha(reconcile._json(clean)) != scope['candidate_record_sha256']):
        raise ValueError('stored candidate scope differs from its bound card or definitions')
    totals = [scope.get(field) for field in ('raw_total', 'excluded_total', 'candidate_total')]
    if (any(type(value) is not int or value < 0 for value in totals) or totals[0] != totals[1] + totals[2] or
            totals[2] != clean.get('expected_occurrences') or
            scope.get('certified_article_total') is not None or
            scope.get('candidate_total_is_certified_article_total') is not False):
        raise ValueError('stored candidate counts cannot certify all remaining article uses')
    rows = reconcile._physical_rows(clean)
    mapping, excluded = scope['retained_map'], scope['excluded']
    if len(mapping) != len(rows) or len(excluded) != totals[1]:
        raise ValueError('stored candidate ledger count is incomplete')
    restored, indices = [None] * totals[0], set()
    for position, (entry, row) in enumerate(zip(mapping, rows)):
        index = entry.get('original_index')
        if (type(index) is not int or not 0 <= index < totals[0] or index in indices or
                type(entry.get('candidate_index')) is not int or entry['candidate_index'] != position or
                entry.get('occurrence_sha256') != reconcile._sha(reconcile._json(row)) or
                entry.get('context_sha256') != reconcile._sha(reconcile._json(_row_context(row)))):
            raise ValueError('stored retained index or reviewed seal changed')
        indices.add(index)
        restored[index] = row
    for entry in excluded:
        index, row = entry.get('original_index'), entry.get('occurrence')
        if (type(index) is not int or not 0 <= index < totals[0] or index in indices or
                not isinstance(row, dict) or
                entry.get('occurrence_sha256') != reconcile._sha(reconcile._json(row)) or
                entry.get('context_sha256') != reconcile._sha(reconcile._json(_row_context(row))) or
                entry.get('classification') != 'different_lemma_as' or
                entry.get('audit_evidence', {}).get('global_index') != index or
                entry.get('reason') != entry.get('audit_evidence', {}).get('reason')):
            raise ValueError('stored excluded record or original index changed')
        _verify_evidence(row, entry['audit_evidence'], {'work_id': scope['work_id']},
                         entry['approved_canonical_source'])
        indices.add(index)
        restored[index] = row
    if indices != set(range(totals[0])):
        raise ValueError('stored ledger does not cover every original position')
    if [item['original_index'] for item in mapping] != sorted(item['original_index'] for item in mapping):
        raise ValueError('stored retained candidates changed their original order')
    raw = deepcopy(clean)
    raw['occurrences'], raw['expected_occurrences'] = restored, totals[0]
    reconcile._physical_rows(raw)
    if (reconcile._sha(reconcile._json(raw)) != scope['raw_record_sha256'] or
            reconcile._sha(reconcile._json([_row_context(row) for row in restored])) != scope['raw_linguistic_sha256']):
        raise ValueError('stored ledger cannot restore its exact original record')
    return deepcopy(scope)
