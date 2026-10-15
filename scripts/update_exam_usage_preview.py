"""Stream an accepted SF database into a new, reversible usage preview.

The request is a pinned local input, not an approval mechanism. Trial runs keep
only their selected parent payloads in a small new database. Full runs clone the
accepted database once and append snapshots in one transaction. Neither mode
changes the accepted database, pages, dictionary evidence or learning data.
An integrity-checked committed private database is retained if rendering fails.
Its exact pinned request and code may resume rendering through read-only SQLite
connections. A separately pinned presentation-only writer continuation records
the approved old/new bytes explicitly; it never changes the prepared checkpoint
or its database run. A resume never clones or prepares snapshots again.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from copy import deepcopy
import hashlib
from html import escape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
import unicodedata
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anki_pipeline import exam_frequency as ef
from anki_pipeline import exam_usage, sense_frequency as sf
from anki_pipeline.packaging import _exam_frequency_markup
from anki_pipeline.store import utc_now

SCHEMA = 'exam-usage-preview-update.v1'
CHECKPOINT_SCHEMA = 'exam-usage-prepared-checkpoint.v1'
RENDER_CONTINUATION_SCHEMA = 'exam-usage-render-code-continuation.v1'
_LEDGER_SQL = '''
CREATE TABLE IF NOT EXISTS exam_usage_update_runs (
 id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS exam_usage_parent_snapshots (
 run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id),
 book_id TEXT NOT NULL, card_id TEXT NOT NULL, parent_snapshot_id TEXT NOT NULL,
 child_snapshot_id TEXT NOT NULL, parent_payload_sha256 TEXT NOT NULL,
 parent_payload TEXT NOT NULL, scope_ledger_sha256 TEXT NOT NULL, scope_ledger TEXT NOT NULL,
 PRIMARY KEY(run_id,book_id,card_id),
 FOREIGN KEY(child_snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id));
CREATE TABLE IF NOT EXISTS exam_usage_history_documents (
 run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id), book_id TEXT NOT NULL,
 card_id TEXT NOT NULL, parent_snapshot_id TEXT NOT NULL, source_url TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, document_sha256 TEXT NOT NULL, original_html TEXT NOT NULL,
 PRIMARY KEY(run_id,book_id,card_id));
CREATE TABLE IF NOT EXISTS exam_usage_ownership_overlays (
 run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id), book_id TEXT NOT NULL,
 card_id TEXT NOT NULL, semantic_snapshot_id TEXT NOT NULL, final_snapshot_id TEXT NOT NULL,
 transfers_sha256 TEXT NOT NULL, transfers TEXT NOT NULL, unresolved_count INTEGER NOT NULL,
 PRIMARY KEY(run_id,book_id,card_id),
 FOREIGN KEY(semantic_snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id),
 FOREIGN KEY(final_snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id));
CREATE TABLE IF NOT EXISTS exam_usage_transfer_outcomes (
 run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id), book_id TEXT NOT NULL,
 source_card_id TEXT NOT NULL, source_occurrence_id TEXT NOT NULL,
 target_card_id TEXT NOT NULL, target_occurrence_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('bound','unresolved','absent_target')),
 reason TEXT NOT NULL, history_id TEXT,
 PRIMARY KEY(run_id,book_id,source_card_id,source_occurrence_id,target_card_id,target_occurrence_id));
'''


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def pin_file(pin):
    if (not isinstance(pin, dict) or not isinstance(pin.get('file'), str)
            or not re.fullmatch(r'[0-9a-f]{64}', str(pin.get('sha256')))):
        raise ValueError('an explicit file/SHA256 pin is required')
    path = Path(pin['file']).resolve(strict=True)
    if not path.is_file() or file_sha(path) != pin['sha256']:
        raise ValueError('pinned input changed: ' + str(path))
    return path


def _read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def _ro(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA foreign_keys=ON')
    return db


def _local_url(url, web_root):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.query:
        raise ValueError('catalog page must be an absolute local web URL')
    path = (Path(web_root).resolve() / parsed.path.lstrip('/')).resolve(strict=True)
    path.relative_to(Path(web_root).resolve())
    return path


def load_catalog(book, web_root):
    entry = pin_file(book['entry'])
    page = entry.read_bytes().decode('utf-8')
    matches = re.findall(r'data-catalog-url="([^"]+)"', page)
    if len(matches) != 1:
        raise ValueError('accepted entry must name exactly one catalog')
    url = matches[0]
    path = _local_url(url, web_root) if url.startswith('/') else (entry.parent / url).resolve(strict=True)
    path.relative_to(Path(web_root).resolve())
    if book.get('catalog') and pin_file(book['catalog']) != path:
        raise ValueError('catalog pin differs from the accepted entry')
    catalog = _read_json(path)
    cards = catalog.get('cards')
    if not isinstance(cards, list) or len({c['id'] for c in cards}) != len(cards):
        raise ValueError('catalog card identities must be unique')
    if book.get('expected_cards') is not None and len(cards) != book['expected_cards']:
        raise ValueError('full catalog count changed')
    return entry, page, path, catalog


def _sidecar_rows(path):
    if path.suffix == '.jsonl':
        with path.open(encoding='utf-8') as handle:
            return [json.loads(line) for line in handle if line.strip()]
    value = _read_json(path)
    rows = value.get('cards', value.get('rows')) if isinstance(value, dict) else value
    return list(rows.values()) if isinstance(rows, dict) else rows


def _index_sidecar(pin, *, collection=None):
    if pin is None:
        return {}, None
    path = pin_file(pin)
    rows = _sidecar_rows(path)
    if not isinstance(rows, list):
        raise ValueError('policy sidecar needs explicit card rows')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('book_id', 'card_id')):
            raise ValueError('sidecar row lacks its exact book/card identity')
        key = row['book_id'], row['card_id']
        if collection and collection not in row:
            item = row
            if collection == 'equivalences' and 'candidate_sense_ids' in row:
                ids, evidence = row['candidate_sense_ids'], row.get('candidate_explanations')
                reason = row.get('reason')
                if reason is None:
                    if any(not isinstance(row.get(k), str) or not row[k].strip()
                           for k in ('context_reason', 'grammar_reason')):
                        raise ValueError('reviewed group certificate needs its actual context and grammar evidence')
                    reason = row['context_reason'] + '\n' + row['grammar_reason']
                if (not isinstance(ids, list) or len(ids) < 2
                        or any(not isinstance(identity, str) or not identity for identity in ids)
                        or len(set(ids)) != len(ids)
                        or not isinstance(evidence, list) or not evidence
                        or any(not isinstance(item, dict) or not item for item in evidence)
                        or any(item.get('sense_id') not in ids for item in evidence)
                        or {item.get('sense_id') for item in evidence} != set(ids)
                        or not isinstance(row.get('common_meaning'), str) or not row['common_meaning'].strip()
                        or not row.get('usage_scope') or not isinstance(reason, str) or not reason.strip()):
                    raise ValueError('reviewed group certificate lacks distinct members or complete meaning evidence')
                item = {'member_sense_ids': row['candidate_sense_ids'], 'meaning': row['common_meaning'],
                    'usage_scope': row['usage_scope'], 'reason': reason,
                    'review_version': row.get('review_version', '20261012'), 'evidence': row['candidate_explanations'],
                    'original_certificate': deepcopy(row), 'certificate_source_pin': deepcopy(pin)}
            result.setdefault(key, {'book_id': key[0], 'card_id': key[1], collection: []})[collection].append(item)
            continue
        if key in result:
            raise ValueError('duplicate card in a policy sidecar')
        result[key] = row
    return result, path


def load_validated_policy_sidecars(request):
    result = {}
    for name in ('policies', 'residual_decisions', 'sense_groups', 'legacy_wrong_bindings'):
        result[name], _ = _index_sidecar(request.get(name), collection={
            'residual_decisions': 'decisions', 'sense_groups': 'equivalences'}.get(name))
    result['dictionary_sources'] = _sidecar_rows(pin_file(request['dictionary_sources'])) if request.get('dictionary_sources') else []
    result['reading_answers'] = None
    if request.get('reading_answers'):
        from anki_pipeline.reading_usage_metadata import build_question_metadata_index
        result['reading_answers'] = build_question_metadata_index(_read_json(pin_file(request['reading_answers'])))
    if not request.get('policies'):
        raise ValueError('ownership policy must be explicitly pinned')
    result['reading_display_projection'] = _load_reading_projections(request)
    return result


def _load_reading_projections(request):
    pin, replay = request.get('reading_display_projection'), request.get('reading_display_replay')
    if pin is None:
        if replay is not None:
            raise ValueError('reading replay configuration lacks its pinned projection sidecar')
        return {}
    from anki_pipeline.reading_display_projection import validate_sidecar
    document = _read_json(pin_file(pin))
    validate_sidecar(document)
    if (not isinstance(replay, dict) or set(replay) != {'exam_root', 'staging', 'completion_path'}
            or not all(isinstance(value, str) and value for value in replay.values())):
        raise ValueError('reading projection needs exact replay paths')
    source = document.get('source_database', {})
    accepted = request['source_database']
    stat = Path(accepted['file']).stat()
    if (not isinstance(source.get('file'), str)
            or Path(source['file']).resolve(strict=True) != Path(accepted['file']).resolve(strict=True)
            or source.get('sha256') != accepted['sha256']
            or source.get('stat') != {key: getattr(stat, 'st_' + key)
                                     for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}):
        raise ValueError('reading projection source database differs from the accepted request')
    authority = {'sidecar': deepcopy(pin), 'replay': deepcopy(replay)}
    indexed = {}
    for item in document['projected']:
        card = indexed.setdefault((item['book_id'], item['card_id']),
                                  {'authority': authority, 'entries': {}})
        card['entries'][item['occurrence_id']] = item
    return indexed


def _validate_reading_projection_delta(before, after, ledger, projection_policy):
    entries = ledger.get('reading_display_projections', [])
    if not isinstance(entries, list):
        raise ValueError('reading projection ledger must be an array')
    if projection_policy is None:
        if entries:
            raise ValueError('reading projection ledger lacks request-pinned authority')
        return
    if (not isinstance(projection_policy, dict) or set(projection_policy) != {'authority', 'entries'}
            or not isinstance(projection_policy['entries'], dict)):
        raise ValueError('reading projection policy lacks exact authority and entries')
    original = {row['occurrence_id']: row for row in before['occurrences']}
    retained = {row['occurrence_id']: row for row in after['occurrences']}
    selected = projection_policy['entries']
    for identity, item in selected.items():
        if (identity not in original or item.get('occurrence_id') != identity
                or item.get('book_id') != before['book_id'] or item.get('card_id') != before['card_id']
                or item.get('snapshot_id') != before['snapshot_id']):
            raise ValueError('reading projection is detached from the actual parent card/snapshot')
    by_id = {entry.get('occurrence_id'): entry for entry in entries if isinstance(entry, dict)}
    if len(by_id) != len(entries) or set(by_id) != set(selected).intersection(retained):
        raise ValueError('reading projection ledger does not exactly cover retained projected rows')
    if after.get('exam_usage_policy', {}).get('reading_display_projections', []) != entries:
        raise ValueError('reading projection ledger differs from its persistent prepared metadata')
    from anki_pipeline.reading_display_projection import get_projection, replay_projection
    authority = projection_policy['authority']
    for identity, entry in by_id.items():
        item, parent = selected[identity], original[identity]
        if get_projection(authority, before['book_id'], before['card_id'], identity) != item:
            raise ValueError('reading projection differs from its pinned sidecar item')
        view = replay_projection(authority, item, parent, book_id=before['book_id'],
                                 card_id=before['card_id'], definition_provenance=before['definition_provenance'])
        expected = {'occurrence_id': identity, 'projection': item, 'authority': authority,
                    'parent_snapshot_id': before['snapshot_id'],
                    'parent_display_sha256': parent['display']['display_hash'],
                    'target_display_sha256': view['display_hash']}
        if entry != expected or retained[identity].get('display') != view:
            raise ValueError('reading projection display or complete provenance ledger changed')


def record_from_prepared(data):
    """Recover the sealed source record, without rereading an exam corpus."""
    if 'candidate_source_record' in data:
        record = deepcopy(data['candidate_source_record'])
        record['candidate_scope'] = deepcopy(data['candidate_scope'])
    else:
        record = {k: deepcopy(data[k]) for k in ('book_id', 'card_id', 'word',
            'definition_source', 'definition_provenance', 'expected_occurrences')}
        record['senses'] = [{'pos': s['pos'], 'text': s['text']} for s in data['senses']]
        ordinals = {s['sense_id']: s['ordinal'] for s in data['senses']}
        record['occurrences'] = []
        for row in data['occurrences']:
            raw = deepcopy(row)
            raw['sense_index'] = ordinals.get(raw.pop('sense_id'))
            for key in ('occurrence_id', 'year'):
                raw.pop(key)
            record['occurrences'].append(raw)
        for key in ('exam_usage_policy', 'sense_group_equivalences', 'ownership_history_unresolved'):
            if key in data:
                record[key] = deepcopy(data[key])
    recovered = sf.prepare_record(record)
    if recovered != data:
        raise ValueError('stored source payload cannot be reproduced exactly')
    return record


def _validate_append(before, after, ledger, registry):
    additions = ledger.get('new_definitions', [])
    old_senses, senses = before['senses'], after['senses']
    if len(senses) != len(old_senses) + len(additions) or any(
            any(old[key] != new[key] for key in ('ordinal', 'pos', 'text'))
            for old, new in zip(old_senses, senses)):
        raise ValueError('dictionary update must retain the exact original sense prefix')
    old_provenance, new_provenance = deepcopy(before['definition_provenance']), deepcopy(after['definition_provenance'])
    old_parts = old_provenance.get('supplemental_definitions', {}).get('appended', [])
    new_parts = new_provenance.get('supplemental_definitions', {}).get('appended', [])
    if new_parts != old_parts + additions:
        raise ValueError('dictionary provenance append differs from its complete source ledger')
    if additions:
        for value in (old_provenance, new_provenance):
            supplement = value.get('supplemental_definitions')
            if supplement is not None:
                supplement.pop('appended', None)
                if not supplement:
                    value.pop('supplemental_definitions')
    if old_provenance != new_provenance:
        raise ValueError('original dictionary provenance changed outside the append')
    if not additions:
        if before['definition_snapshot_id'] != after['definition_snapshot_id'] or old_senses != senses:
            raise ValueError('unchanged definitions acquired different identities')
        return False
    from anki_pipeline.dictionary_review_evidence import validate_new_sense
    for index, addition in enumerate(additions, len(old_senses)):
        decision = addition.get('review_evidence')
        if (addition.get('ordinal') != index or not isinstance(decision, dict)
                or senses[index]['pos'] != decision['new_sense']['pos']
                or senses[index]['text'] != decision['new_sense']['text']):
            raise ValueError('new dictionary sense is detached from its explicit reviewed source')
        if validate_new_sense(decision, registry=registry) != addition.get('validated_source_evidence'):
            raise ValueError('new dictionary source evidence no longer validates exactly')
    return True


def _validate_rehome(before, row, item, parent_lookup):
    authority = item.get('authority', {})
    audit = authority.get('audit')
    if (authority.get('source_parent_snapshot_id') != before['snapshot_id']
            or authority.get('source_parent_row_sha256') != digest(row)
            or not isinstance(audit, dict) or audit.get('exclusion_verified') is not True
            or audit.get('decision_status') != 'keep_exclusion'
            or any(audit.get(key) != before[key] for key in ('book_id', 'card_id', 'word'))
            or audit.get('occurrence_id') != row['occurrence_id']
            or audit.get('previous_status') != row['status']
            or audit.get('previous_sense_id') != row['sense_id']):
        raise ValueError('reviewed rehome lacks exact original assignment/source authority')
    if parent_lookup is None:
        raise ValueError('reviewed rehome requires an actual read-only destination lookup')
    from anki_pipeline.ownership_history import bind_incoming_history
    valid = 0
    for target in audit.get('targets', []):
        if target.get('verified_physical_match') is not True:
            continue
        parent = parent_lookup(before['book_id'], target['card_id'])
        if parent is None:
            raise ValueError('reviewed rehome destination is absent from the accepted database')
        transfer = {'book_id': before['book_id'], 'source_card_id': before['card_id'],
            'source_word': before['word'], 'source_parent_row': row,
            'source_parent_snapshot_id': before['snapshot_id'], 'exclusion_authority': authority,
            'source_identity': audit['source_identity'], **{key: target.get(key) for key in
            ('verified_physical_match', 'target_range', 'matched_sense', 'target_reason', 'match_kind')},
            'target_card_id': target['card_id'], 'target_occurrence_id': target['occurrence_id']}
        if target.get('quantity_phrase_proof') is not None:
            transfer['quantity_phrase_proof'] = deepcopy(target['quantity_phrase_proof'])
        bound = bind_incoming_history(parent, [transfer])
        if bound.get('ownership_history_unresolved'):
            raise ValueError('reviewed rehome actual destination proof failed: ' + bound['ownership_history_unresolved'][-1]['reason'])
        valid += 1
    if not valid:
        raise ValueError('reviewed rehome has no verified actual reviewed destination')


def merge_confirmed_rehomes(before, policy_audits, residual_audits, *, policy_pin, parent_lookup):
    """Merge a repeated verified exclusion without losing either authority.

    Each input stream must have unique identities. A cross-stream overlap is
    accepted only after both complete audits bind to the actual parent and
    destination, with identical physical and semantic owners. The residual
    audit remains primary; the exact earlier policy audit and pin are retained.
    """
    from anki_pipeline.exam_usage_policy import _confirmed_rehomes
    old = {}
    for audit in policy_audits:
        identity = audit.get('occurrence_id')
        if identity in old:
            raise ValueError('duplicate ownership audit in original policy')
        old[identity] = audit
    seen, replacements = set(), {}
    policy_payload = None
    for newer in residual_audits:
        identity = newer.get('occurrence_id')
        if identity in seen:
            raise ValueError('duplicate residual ownership audit')
        seen.add(identity)
        if identity not in old:
            replacements[identity] = deepcopy(newer)
            continue
        previous = old[identity]
        if policy_payload is None:
            policy_payload = _read_json(pin_file(policy_pin))
        original_candidates = [policy_payload['audit']] if 'audit' in policy_payload else [
            audit for card in policy_payload.get('cards', [])
            if (card.get('book_id'), card.get('card_id')) == (before['book_id'], before['card_id'])
            for audit in card.get('confirmed_new_exclusions', [])]
        if previous not in original_candidates:
            raise ValueError('overlapping original authority is absent from its pinned policy')
        for audit in (previous, newer):
            item = _confirmed_rehomes(before, {'confirmed_new_exclusions': [audit]})[0]
            _validate_rehome(before, item['occurrence'], item, parent_lookup)
        source_keys = ('book_id', 'card_id', 'word', 'occurrence_id', 'previous_status',
                       'previous_sense_id', 'english')
        physical_keys = ('paper_id', 'sentence_id', 'physical_source', 'english_hash', 'target_range')
        if (any(previous.get(key) != newer.get(key) for key in source_keys)
                or any(previous['source_identity'].get(key) != newer['source_identity'].get(key)
                       for key in physical_keys)):
            raise ValueError('overlapping ownership audits disagree on the actual original assignment/source')

        def owners(audit):
            return sorted(canonical({'card_id': target['card_id'], 'occurrence_id': target['occurrence_id'],
                'target_range': target['target_range'], 'sense': {key: target['matched_sense'].get(key)
                    for key in ('sense_id', 'ordinal', 'pos', 'text', 'dictionary_source')}})
                for target in audit['targets'])

        if owners(previous) != owners(newer):
            raise ValueError('overlapping ownership audits disagree on their actual semantic destinations')
        replacement = deepcopy(newer)
        replacement.setdefault('additional_authorities', []).append({
            'source_kind': 'original_ownership_card_policy', 'source_pin': deepcopy(policy_pin),
            'audit_sha256': digest(previous), 'audit': deepcopy(previous)})
        replacements[identity] = replacement
    return [replacements.get(identity, deepcopy(audit)) for identity, audit in old.items()] + [
        replacements[audit['occurrence_id']] for audit in residual_audits if audit['occurrence_id'] not in old]


def validate_delta(before, after, ledger, *, verified_dictionary_sources=(), parent_lookup=None,
                   reading_display_projection=None):
    if any(before[k] != after[k] for k in ('book_id', 'card_id', 'word', 'definition_source')):
        raise ValueError('usage update changed the original word/dictionary identity')
    original = {r['occurrence_id']: r for r in before['occurrences']}
    changed = {r['occurrence_id']: r for r in after['occurrences']}
    if not set(changed).issubset(original):
        raise ValueError('usage update manufactured a physical occurrence')
    if (not isinstance(ledger, dict) or ledger.get('parent_snapshot_id') != before['snapshot_id']
            or ledger.get('book_id') != before['book_id'] or ledger.get('card_id') != before['card_id']):
        raise ValueError('child scope is not bound to its actual parent snapshot')
    _validate_reading_projection_delta(before, after, ledger, reading_display_projection)
    definitions_changed = _validate_append(before, after, ledger, verified_dictionary_sources)
    excluded = ledger.get('excluded', [])
    by_id = {}
    for item in excluded:
        row = item.get('occurrence') if isinstance(item, dict) else None
        oid = row.get('occurrence_id') if isinstance(row, dict) else None
        if oid not in original or oid in by_id or row != original[oid]:
            raise ValueError('excluded original row is stale, duplicated or detached')
        kind = item.get('exclusion_kind')
        if kind == 'cloze_option':
            if not ef.exclude_cloze_option(exam_usage.occurrence_sentence(row)):
                raise ValueError('excluded row is not a printed cloze option')
        elif kind == 'wrong_lemma':
            authority = item.get('authority')
            if (row['status'] == 'reviewed' or row.get('sense_id') is not None
                    or not isinstance(authority, dict) or not authority):
                raise ValueError('wrong-lemma exclusion lacks original non-R authority')
            proof = authority.get('legacy_projection_proof')
            decision = proof.get('decision', {}) if isinstance(proof, dict) else {}
            if (not isinstance(proof, dict) or proof.get('occurrence') != row
                    or authority.get('parent_snapshot_id') != before['snapshot_id']
                    or authority.get('decision_sha256') != digest(decision)
                    or any(decision.get(key) != expected for key, expected in (
                        ('book_id', before['book_id']), ('card_id', before['card_id']),
                        ('after_snapshot_id', before['snapshot_id']), ('occurrence_id', oid)))):
                raise ValueError('wrong-lemma exclusion lacks its complete immutable parent proof')
        elif kind == 'reviewed_rehome':
            _validate_rehome(before, row, item, parent_lookup)
        else:
            raise ValueError('unsupported physical-source exclusion')
        by_id[oid] = item
    if set(by_id) != set(original) - set(changed):
        raise ValueError('child scope does not account for every excluded original position')
    decisions = ledger.get('semantic_decisions', [])
    decision_ids = {d.get('occurrence_id') for d in decisions}
    if len(decision_ids) != len(decisions):
        raise ValueError('duplicate residual review decision')
    rebindings = ledger.get('technical_semantic_rebindings', [])
    rebound = {item.get('occurrence_id'): item for item in rebindings}
    expected_rebindings = {oid for oid, row in changed.items() if original[oid]['status'] == 'reviewed'} if definitions_changed else set()
    if len(rebound) != len(rebindings) or set(rebound) != expected_rebindings:
        raise ValueError('technical reseal ledger does not cover exactly the retained original reviewed rows')
    metadata = {'usage', 'broad_match', 'common_sense_match', 'pending_category', 'display',
                'semantic_review', 'ownership_history'}
    semantic = {'status', 'sense_id', 'reviewed_sense_id', 'assignment_context_hash',
                'reason', 'method', 'review_version', 'matching_proposal'}
    projected_ids = set(reading_display_projection['entries']) if reading_display_projection else set()
    for oid, row in changed.items():
        old = original[oid]
        if oid not in projected_ids:
            from anki_pipeline.sense_display import refresh_derived_chunks
            if row.get('display') != refresh_derived_chunks(old).get('display'):
                raise ValueError('unprojected display changed outside its deterministic chunk refresh')
        if {k: v for k, v in row.items() if k not in metadata | semantic} != {
                k: v for k, v in old.items() if k not in metadata | semantic}:
            raise ValueError('usage update altered original bilingual source or position')
        comparable = semantic - ({'sense_id', 'reviewed_sense_id', 'assignment_context_hash', 'matching_proposal'} if definitions_changed else set())
        if {k: row.get(k) for k in comparable} != {k: old.get(k) for k in comparable} and oid not in decision_ids:
            raise ValueError('semantic assignment changed without a residual decision')
        if old['status'] == 'reviewed' and any(row.get(k) != old.get(k) for k in comparable):
            raise ValueError('an accepted reviewed assignment or seal changed')
        if oid in rebound:
            index = next(s['ordinal'] for s in before['senses'] if s['sense_id'] == old['sense_id'])
            binding = rebound[oid]
            if (binding.get('sense_ordinal') != index or binding.get('old_context_hash') != old['assignment_context_hash']
                    or binding.get('new_context_hash') != row['assignment_context_hash']
                    or row['sense_id'] != after['senses'][index]['sense_id'] or row['reviewed_sense_id'] != row['sense_id']):
                raise ValueError('technical reviewed reseal changed its original semantic ordinal')
        if definitions_changed and oid not in decision_ids:
            proposal_keys = {'definition_snapshot_id', 'assignment_context_hash', 'candidate_sense_ids'}
            if {k: v for k, v in row.get('matching_proposal', {}).items() if k not in proposal_keys} != {
                    k: v for k, v in old.get('matching_proposal', {}).items() if k not in proposal_keys}:
                raise ValueError('technical proposal reseal altered its candidate evidence')
        if oid in decision_ids:
            from anki_pipeline.exam_usage_policy import _validate_decision_binding
            decision = next(d for d in decisions if d['occurrence_id'] == oid)
            _validate_decision_binding(before, old, decision)
            if old['status'] == 'reviewed' or row.get('semantic_review') != decision or row['reason'] != decision['reason']:
                raise ValueError('residual review altered an old reviewed meaning or lost its complete evidence')
    if decision_ids - set(changed):
        raise ValueError('semantic decision refers to a removed or unknown occurrence')
    if ledger.get('new_snapshot_id') != after['snapshot_id']:
        raise ValueError('child snapshot does not match its sealed scope ledger')
    if after['expected_occurrences'] != len(changed):
        raise ValueError('filtered snapshot count does not reconcile')


def insert_prepared(db, data):
    """Single-transaction counterpart of SF persistence, no extra backup."""
    sid = data['snapshot_id']
    saved = db.execute('SELECT payload FROM snapshots WHERE id=?', (sid,)).fetchone()
    if saved:
        if saved[0] != sf._json(data):
            raise ValueError('immutable snapshot ID has conflicting content')
    else:
        db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)', (sid, data['book_id'],
            data['card_id'], data['word'], data['definition_source'], sf._json(data['definition_provenance']),
            data['expected_occurrences'], utc_now(), sf._json(data)))
        db.executemany('INSERT INTO senses VALUES(?,?,?,?,?)', [(sid, s['sense_id'],
            s['ordinal'], s['pos'], s['text']) for s in data['senses']])
        for row in data['occurrences']:
            db.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (sid,
                row['occurrence_id'], sf._json(row['physical_source']), row['paper_id'], row['year'],
                row['sentence_id'], row['english'], row['english_hash'], row['translation'], row['translation_hash'],
                *row['target_range'], sf._json(row['translation_ranges']), row['source'], sf._json(row['source_provenance']),
                sf._json(row['alignment']) if row['alignment'] is not None else None))
            db.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?,?,?,?,?)', (sid, row['occurrence_id'],
                row['sense_id'], row['status'], row['reason'], row['method'], row['review_version'],
                row['reviewed_sense_id'], row['assignment_context_hash'],
                sf._json(row['matching_proposal']) if 'matching_proposal' in row else None))
    db.execute('INSERT INTO active_snapshots VALUES(?,?,?) ON CONFLICT(book_id,card_id) '
        'DO UPDATE SET snapshot_id=excluded.snapshot_id', (data['book_id'], data['card_id'], sid))


def _active_prepared(db, book_id, card_id):
    row = db.execute('SELECT s.payload FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id '
        'WHERE a.book_id=? AND a.card_id=?', (book_id, card_id)).fetchone()
    return json.loads(row[0]) if row else None


def normalized_residual_rehomes(pin, original):
    """Bind explicit residual owners to actual parents and frozen paper contexts."""
    if not pin:
        return {}, []
    from anki_pipeline.exam_usage_policy import assignment_pin, _verified_cloze_reversal
    result, context_pins = {}, {}
    for raw in _read_json(pin_file(pin)).get('confirmed_targets', []):
        if raw.get('apply_policy_change') is not True or raw.get('exclusion_verified') is not True:
            raise ValueError('residual ownership adapter received an unconfirmed source')
        parent = _active_prepared(original, raw['book_id'], raw['card_id'])
        row = next((r for r in parent['occurrences'] if r['occurrence_id'] == raw['occurrence_id']), None) if parent else None
        if (row is None or raw.get('snapshot_id') != parent['snapshot_id']
                or raw.get('old_assignment_sha256') != assignment_pin(parent, row)):
            raise ValueError('residual ownership source assignment changed')
        audit = deepcopy(raw)
        identity = audit['source_identity']
        if isinstance(identity.get('physical_source'), str):
            identity['physical_source'] = json.loads(identity['physical_source'])
        if any(identity.get(k) != row[k] for k in ('paper_id', 'physical_source', 'sentence_id', 'english_hash', 'target_range')):
            raise ValueError('residual ownership physical source changed')
        cp = raw['context_pin']
        cache_pin = {'file': cp['cache_file'], 'sha256': cp['cache_file_sha256']}
        cache = _read_json(pin_file(cache_pin))
        actual = original.execute('SELECT kind,payload_sha256,payload FROM supplemental_review_entities '
            'WHERE run_id=? AND entity_id=?', (cp['run_id'], cp['entity_id'])).fetchone()
        if (actual is None or actual[0] != 'full-paper-context' or cache.get('kind') != actual[0]
                or cache.get('run_id') != cp['run_id'] or cache.get('entity_id') != cp['entity_id']
                or cache.get('payload_sha256') != cp['payload_sha256'] or actual[1] != cp['payload_sha256']
                or digest(cache['payload']) != actual[1] or json.loads(actual[2]) != cache['payload']
                or cache['payload'].get('paper_id') != row['paper_id']):
            raise ValueError('residual ownership context is not the exact accepted paper entity')
        context_pins[cache_pin['file']] = cache_pin
        normal = lambda text: ' '.join(text.split())
        blocks = cache['payload']['blocks']
        contained = any(normal(row['english']) in normal(b.get('text', '')) for b in blocks)
        checks = {'english_hash_valid': hashlib.sha256(row['english'].encode()).hexdigest() == row['english_hash'],
            'exact_target_match': row['english'][slice(*row['target_range'])] == raw['physical_target'],
            'materialized_raw_sentence_contained': False, 'frozen_context_sentence_contained': contained}
        if checks['english_hash_valid'] is not True or checks['exact_target_match'] is not True:
            raise ValueError('residual ownership actual English hash or target slice differs')
        if not contained:
            answers = row.get('display', {}).get('provenance', {}).get('source_cloze_answers', [])
            sentence = row['english']
            for a in sorted(answers, key=lambda a: a['start'], reverse=True):
                sentence = sentence[:a['start']] + str(a['number']) + sentence[a['end']:]
            matching = [b for b in blocks if normal(sentence) in normal(b.get('text', ''))]
            if (not answers or len(matching) != 1 or normal(matching[0]['text']).count(normal(sentence)) != 1
                    or hashlib.sha256(matching[0]['text'].encode()).hexdigest() != row['source_provenance'].get('sourceHash')):
                raise ValueError('residual ownership source is absent from its frozen context')
            shift = sum(len(str(a['number'])) - (a['end'] - a['start']) for a in answers if a['end'] <= row['target_range'][0])
            proof = {'verified': True, 'answer_replacements': deepcopy(answers),
                'source_hash': row['source_provenance']['sourceHash'], 'source_block_ids': row['source_provenance']['sourceBlockIds'],
                'target_is_answer_replacement': False, 'original_sentence_unique_in_verified_paragraph': True,
                'reversed_answer_sentence': sentence, 'untouched_target_range_in_reversed_sentence': [v + shift for v in row['target_range']],
                'original_source_target_text': row['english'][slice(*row['target_range'])]}
            if not _verified_cloze_reversal(row, proof):
                raise ValueError('residual ownership cloze reversal altered the actual target')
            checks['recorded_cloze_answer_reversal'] = proof
        audit['source_checks'] = checks
        audit['english'] = row['english']
        audit['origin'] = {'file_pin': pin, 'original_audit_sha256': digest(raw), 'original_audit': raw}
        for target in audit['targets']:
            if target.get('match_kind') == 'same_native_quantity_phrase':
                target['quantity_phrase_proof'] = {key: deepcopy(target[key]) for key in
                    ('grammar_evidence', 'shared_whole_phrase_range', 'native_dictionary_evidence')}
                target['quantity_phrase_proof']['source_pin'] = deepcopy(pin)
        result.setdefault((raw['book_id'], raw['card_id']), []).append(audit)
    return result, list(context_pins.values())


def _card_filename(card_id):
    return (card_id if re.fullmatch('[a-f0-9]{64}', card_id) else hashlib.sha256(card_id.encode()).hexdigest()) + '.html'


def _transfer_outcome(db, run_id, transfer, status, reason='', history_id=None):
    db.execute('INSERT INTO exam_usage_transfer_outcomes VALUES(?,?,?,?,?,?,?,?,?)',
        (run_id, transfer['book_id'], transfer['source_card_id'], transfer['source_parent_row']['occurrence_id'],
         transfer['target_card_id'], transfer['target_occurrence_id'], status, reason, history_id))


def _history_document(word, snapshot, source_url, original_html):
    from anki_pipeline.ownership_history import _HistoricalHTML
    safe = _HistoricalHTML()
    safe.feed(original_html)
    safe.close()
    css = Path(sf.__file__).with_name('templates').joinpath('sense-frequency.css').read_text()
    return ('<!doctype html><html lang="zh"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>' + escape(word) +
        ' · 原核对记录</title><style>' + css +
        '\nbody{margin:0;padding:16px;font:14px/1.7 system-ui;overflow-wrap:anywhere}</style></head><body>'
        '<h1 style="font-size:18px">' + escape(word) + ' · 原核对记录</h1><p>父快照：' + escape(snapshot) +
        '</p><p><a href="' + escape(source_url, quote=True) + '">已封存的原词卡</a></p>' +
        (''.join(safe.output) if original_html else '<p>原页面无独立诊断块；完整原审核理由与双语记录在目标例句中保留。</p>') +
        '<details><summary>完整原 HTML 证据</summary><pre style="white-space:pre-wrap">' +
        escape(original_html) + '</pre></details></body></html>')


def attach_incoming_histories(db, original, run_id, card_sources, outputs, web_root, aliases_by_version):
    """Reverse verified links into existing destinations, using bounded SQL staging.

    Complete old rows and authority remain in the source scope ledger. Historical
    HTML is stored once per source card; destinations carry an immutable document
    reference and their own complete original row, never another native count.
    """
    from anki_pipeline.ownership_history import bind_incoming_history
    from anki_pipeline.exam_usage_policy import producer_record
    from scripts.prepare_sense_frequency_records import class_aliases
    db.execute('CREATE TEMP TABLE incoming_usage_transfers(book_id TEXT,card_id TEXT,payload TEXT)')
    db.execute('CREATE INDEX incoming_usage_target ON incoming_usage_transfers(book_id,card_id)')
    sources = db.execute('SELECT p.book_id,p.card_id,p.parent_snapshot_id,p.scope_ledger,'
        'COALESCE(NULLIF(p.parent_payload,\'\'),s.payload) FROM exam_usage_parent_snapshots p '
        'LEFT JOIN snapshots s ON s.id=p.parent_snapshot_id WHERE p.run_id=? ORDER BY p.book_id,p.card_id', (run_id,))
    transfers_count = 0
    required_sources = set()
    for book, card, parent_sid, ledger_json, parent_json in sources:
        parent, ledger = json.loads(parent_json), json.loads(ledger_json)
        required_sources.update((book, card, i['occurrence_id']) for i in ledger['excluded']
            if (i.get('prior_exclusion') or i).get('exclusion_kind') in {'wrong_lemma', 'reviewed_rehome'})
        items = [i for i in ledger['excluded'] if i.get('ownership')]
        if not items:
            continue
        card_meta = card_sources[(book, card)]
        source = _local_url(card_meta['previewUrl'], web_root)
        page = source.read_bytes().decode('utf-8')
        version = source.parent.parent
        if version not in aliases_by_version:
            aliases_by_version[version] = class_aliases(version)
        historical = ''.join(page[n['start']:n['end']] for n in _Spans(page, aliases_by_version[version]).nodes
            if n['kind'] == 'diagnostic')
        document = _history_document(parent['word'], parent_sid, card_meta['previewUrl'], historical)
        document_sha = hashlib.sha256(document.encode()).hexdigest()
        document_path = outputs[book] / 'history' / (card + '.html')
        db.execute('INSERT INTO exam_usage_history_documents VALUES(?,?,?,?,?,?,?,?)',
            (run_id, book, card, parent_sid, card_meta['previewUrl'], hashlib.sha256(page.encode()).hexdigest(),
             document_sha, historical))
        target_parents = {}
        for item in items:
            ownership = item['ownership']
            for target in ownership.get('targets', []):
                if target.get('verified_physical_match') is not True:
                    continue
                target_card = target.get('card_id')
                if target_card not in target_parents:
                    target_parents[target_card] = _active_prepared(original, book, target_card)
                target_parent = target_parents[target_card]
                if target_parent is None:
                    raise ValueError('verified incoming target has no immutable source snapshot')
                target_row = next((r for r in target_parent['occurrences'] if r['occurrence_id'] == target.get('occurrence_id')), None)
                prior = item.get('prior_exclusion') or item
                transfer = {'book_id': book, 'source_card_id': card, 'source_word': parent['word'],
                    'source_parent_row': item['occurrence'], 'source_parent_snapshot_id': parent_sid,
                    'source_parent_definition_id': parent['definition_snapshot_id'],
                    'source_parent_page_url': card_meta['previewUrl'],
                    'source_parent_page_sha256': hashlib.sha256(page.encode()).hexdigest(),
                    'exclusion_authority': prior['authority'], 'source_identity': ownership.get('source_identity'),
                    'target_card_id': target_card, 'target_occurrence_id': target.get('occurrence_id'),
                    'target_parent_row': target_row, 'target_parent_snapshot_id': target_parent['snapshot_id'],
                    'source_history_ref': {'file': str(document_path), 'sha256': document_sha,
                        'url': '/' + str(document_path.relative_to(web_root))},
                    **{key: target.get(key) for key in ('verified_physical_match', 'target_range',
                        'matched_sense', 'target_reason', 'match_kind')}}
                if target.get('quantity_phrase_proof') is not None:
                    transfer['quantity_phrase_proof'] = deepcopy(target['quantity_phrase_proof'])
                if not db.execute('SELECT 1 FROM exam_usage_parent_snapshots WHERE run_id=? AND book_id=? AND card_id=?',
                        (run_id, book, target_card)).fetchone():
                    _transfer_outcome(db, run_id, transfer, 'absent_target', '目标词卡未包含在本次生成范围中，完整原记录尚未转归')
                    continue
                db.execute('INSERT INTO incoming_usage_transfers VALUES(?,?,?)', (book, target_card, canonical(transfer)))
                transfers_count += 1
        if file_sha(source) != hashlib.sha256(page.encode()).hexdigest():
            raise ValueError('ownership historical source changed while reading')
    unresolved_count = 0
    for book, card in db.execute('SELECT DISTINCT book_id,card_id FROM incoming_usage_transfers ORDER BY book_id,card_id'):
        transfers = [json.loads(r[0]) for r in db.execute('SELECT payload FROM incoming_usage_transfers '
            'WHERE book_id=? AND card_id=? ORDER BY rowid', (book, card))]
        semantic = _active_prepared(db, book, card)
        bound = bind_incoming_history(semantic, transfers)
        for row in bound['occurrences']:
            for history in row.get('ownership_history', []):
                if history['source_parent_snapshot_id'] in {t['source_parent_snapshot_id'] for t in transfers}:
                    _transfer_outcome(db, run_id, history, 'bound', history_id=history['history_id'])
        for unresolved in bound.get('ownership_history_unresolved', []):
            _transfer_outcome(db, run_id, unresolved['transfer'], 'unresolved', unresolved['reason'])
        final = sf.prepare_record(producer_record(bound, preserve_scope=False))
        if (final['expected_occurrences'] != semantic['expected_occurrences'] or final['senses'] != semantic['senses']
                or [{k: v for k, v in r.items() if k != 'ownership_history'} for r in final['occurrences']] !=
                [{k: v for k, v in r.items() if k != 'ownership_history'} for r in semantic['occurrences']]):
            raise ValueError('ownership history overlay changed a native source/meaning/count')
        insert_prepared(db, final)
        db.execute('UPDATE exam_usage_parent_snapshots SET child_snapshot_id=? WHERE run_id=? AND book_id=? AND card_id=?',
            (final['snapshot_id'], run_id, book, card))
        unresolved = len(final.get('ownership_history_unresolved', []))
        db.execute('INSERT INTO exam_usage_ownership_overlays VALUES(?,?,?,?,?,?,?,?)',
            (run_id, book, card, semantic['snapshot_id'], final['snapshot_id'], digest(transfers), canonical(transfers), unresolved))
        unresolved_count += unresolved
    db.execute('DROP TABLE incoming_usage_transfers')
    outcome_counts = dict(db.execute('SELECT status,count(*) FROM exam_usage_transfer_outcomes WHERE run_id=? GROUP BY status', (run_id,)))
    bound_sources = set(db.execute('SELECT DISTINCT book_id,source_card_id,source_occurrence_id '
        'FROM exam_usage_transfer_outcomes WHERE run_id=? AND status=\'bound\'', (run_id,)))
    return {'transfers': transfers_count, 'bound': outcome_counts.get('bound', 0),
        'unresolved': unresolved_count, 'absent_targets': outcome_counts.get('absent_target', 0),
        'source_records': len(required_sources), 'bound_source_records': len(bound_sources),
        'pending_source_records': len(required_sources - bound_sources)}


def render_history_payload(db, run_id, data):
    """Validate documents without mutating the sealed per-occurrence histories."""
    documents = {}
    for row in data['occurrences']:
        for history in row.get('ownership_history', []):
            key = history['book_id'], history['source_card_id']
            ref = history['source_history_ref']
            if ref['file'] in documents:
                continue
            saved = db.execute('SELECT parent_snapshot_id,source_url,document_sha256,original_html '
                'FROM exam_usage_history_documents WHERE run_id=? AND book_id=? AND card_id=?', (run_id, *key)).fetchone()
            if saved is None or saved[0] != history['source_parent_snapshot_id'] or saved[2] != ref['sha256']:
                raise ValueError('incoming history has no exact persisted original document')
            document = _history_document(history['source_word'], saved[0], saved[1], saved[3])
            if hashlib.sha256(document.encode()).hexdigest() != saved[2]:
                raise ValueError('incoming historical document content no longer matches its source reference')
            documents[ref['file']] = {'reference': deepcopy(ref), 'document_html': document,
                'original_html': saved[3], 'original_html_sha256': hashlib.sha256(saved[3].encode()).hexdigest(),
                'inline_history_ids': [history['history_id']]}
    return documents


class _Spans(HTMLParser):
    """Find complete report/panel/diagnostic nodes without rebuilding HTML."""
    def __init__(self, page, aliases=None):
        super().__init__(convert_charrefs=True)
        self.page = page
        self.aliases = aliases or {}
        self.lines = [0]
        for m in re.finditer('\n', page):
            self.lines.append(m.end())
        self.active = None
        self.nodes = []
        self.meaning_depth = 0
        self.meaning_text = []
        self.elements = []
        self.feed(page)
        self.close()
        if self.active:
            raise ValueError('unterminated accepted report or frequency block')

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = {self.aliases.get(name, name) for name in attrs.get('class', '').split()}
        historical = (bool(self.elements and self.elements[-1][1]) or bool(classes & {
            'sf-native-ownership-history', 'sf-ownership-history', 'sf-original-history-panel'}))
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
                       'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.elements.append((tag, historical))
        kind = (None if historical else
                'report' if tag == 'div' and 'sf-report' in classes else
                'frequency' if tag == 'section' and 'exam-frequency' in classes else
                'diagnostic' if tag == 'details' and 'sf-wrong-bindings' in classes else None)
        if kind:
            if self.active:
                raise ValueError('report, frequency or diagnostic blocks overlap')
            self.active = {'kind': kind, 'tag': tag, 'start': self.position(), 'depth': 0,
                           'attrs': attrs, 'meanings': []}
        if self.active and tag == self.active['tag']:
            self.active['depth'] += 1
        if not historical and self.active and self.active['kind'] == 'report' and tag == 'span':
            if self.meaning_depth:
                self.meaning_depth += 1
            elif 'sf-meaning' in classes:
                self.meaning_depth = 1
                self.meaning_text = []

    def handle_endtag(self, tag):
        historical = bool(self.elements and self.elements[-1][1])
        if not historical and self.meaning_depth and tag == 'span':
            self.meaning_depth -= 1
            if not self.meaning_depth:
                self.active['meanings'].append(''.join(self.meaning_text))
        if self.active and tag == self.active['tag']:
            self.active['depth'] -= 1
            if not self.active['depth']:
                self.active['end'] = self.position() + len('</' + tag + '>')
                self.nodes.append(self.active)
                self.active = None
        for index in range(len(self.elements) - 1, -1, -1):
            if self.elements[index][0] == tag:
                del self.elements[index:]
                break

    def handle_data(self, data):
        if self.meaning_depth:
            self.meaning_text.append(data)


def _frequency(rows, corpus=44):
    counts, sources = Counter(), {}
    for row in rows:
        key = row['paper_id'], canonical(row['physical_source'])
        text = row['english_hash'], row['translation_hash']
        if key in sources and sources[key] != text:
            raise ValueError('a physical source has conflicting bilingual content')
        sources[key] = text
        counts[key] += 1
    return ef.frequency_for_matches([(p, physical, 0, n) for (p, physical), n in counts.items()], corpus)


def _breakdown(rows, excluded_cloze):
    by_source = {}
    for row in rows:
        key = row['paper_id'], canonical(row['physical_source'])
        usage = row.get('usage') or exam_usage.occurrence_usage(row)
        old = by_source.get(key)
        if old and old[1] != usage:
            raise ValueError('same printed source has conflicting usage classifications')
        by_source[key] = ((old[0] if old else 0) + 1, usage)
    return ef.frequency_breakdown_for_matches([(p, physical, 0, n, usage)
        for (p, physical), (n, usage) in by_source.items()], excluded_cloze_option_occurrences=excluded_cloze)


def _component_rows(rows, names):
    normalized = [unicodedata.normalize('NFKC', name).casefold() for name in names]
    if len(normalized) != len(set(normalized)):
        raise ValueError('component headwords are not distinct')
    groups = [[] for _ in names]
    for row in rows:
        surface = unicodedata.normalize('NFKC', row['english'][slice(*row['target_range'])]).casefold()
        if surface not in normalized:
            raise ValueError('physical target does not belong to an explicit compound component')
        groups[normalized.index(surface)].append(row)
    return groups


def render_exclusions(excluded, *, target_urls=None, historical_html='', actual_bound_targets=()):
    """Keep each old explanation while quoting only verified owner meanings."""
    target_urls = target_urls or {}
    kinds = Counter(item['exclusion_kind'] for item in excluded)
    label = ' · '.join(name + ' ' + str(kinds[key]) + ' 处' for key, name in
        (('wrong_lemma', '已核实归属调整'), ('cloze_option', '完形选项')) if kinds[key])
    entries = []
    for item in excluded:
        row, ownership = item['occurrence'], item.get('ownership') or {}
        targets = []
        for target in ownership.get('targets', []):
            sense = target.get('matched_sense')
            if target.get('status') != 'reviewed' or not target.get('verified_physical_match') or not isinstance(sense, dict):
                continue
            if (row['occurrence_id'], target.get('card_id'), target.get('occurrence_id')) not in actual_bound_targets:
                continue
            word = str(target.get('word', ''))
            url = target_urls.get(target.get('card_id'))
            word_html = ('<a href="' + escape(url, quote=True) + '">' + escape(word) + '</a>') if url else escape(word)
            targets.append('<p class="sf-owner">已归入 ' + word_html + '：' + escape(
                str(sense.get('pos', '')) + ' ' + str(sense.get('text', ''))) +
                ' · ' + escape(str(target.get('dictionary_source', sense.get('dictionary_source', '')))) + '</p><p class="sf-reason">' +
                escape(str(target.get('target_reason', ''))) + '</p>')
        gaps = ownership.get('unresolved_reasons', [])
        moved = bool(targets)
        if not moved and ownership.get('targets'):
            targets.append('<p class="sf-owner">本次尚未完成转归：目标卡未输出或现行范围/证据绑定未通过；完整原记录保留如下。</p>')
        elif not targets and item['exclusion_kind'] in {'wrong_lemma', 'reviewed_rehome'}:
            targets.append('<p class="sf-owner">归属仍待核：' + escape('、'.join(map(str, gaps)) or '目标词卡或对应义项尚未核实') + '</p>')
        if item['exclusion_kind'] == 'cloze_option' and item.get('authority', {}).get('legacy_projection_proof'):
            targets.append('<p class="sf-reason">原核对为错归词条；本版按完形选项统计口径排除。</p>')
        if moved:
            entries.append('<article class="exam-usage-transfer-entry">' + ''.join(targets) +
                '<p class="sf-hint">完整原句、译文、标记、出处与原核对依据已随记录保存在目标词卡；原位置不在本卡重复计数。</p></article>')
            continue
        position = row['paper_id'] + ' · ' + row['sentence_id'] + ' · ' + str(row['target_range'])
        entries.append('<article class="exam-usage-exclusion">' + ''.join(targets) +
            '<p class="sf-reason">原审核解释：' + escape(row['reason']) + '</p><p class="sf-source">' +
            escape(position) + '</p>' + sf._previews([row]) +
            '<details><summary>原审核归属与证据记录</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
            escape(canonical({'authority': item.get('authority'), 'ownership': ownership,
                'original_assignment': {k: row.get(k) for k in ('status', 'sense_id', 'reason', 'method',
                    'review_version', 'reviewed_sense_id', 'assignment_context_hash')}})) + '</pre></details></article>')
    # Complete historical panels are separately immutable and move with verified
    # incoming histories. Showing the whole original panel here would also show
    # examples whose owner has already been corrected.
    historical = ''
    return ('<details class="exam-usage-exclusions"><summary>' + escape(label) +
        '</summary><p class="sf-hint">原始位置与审核证据保留在父快照中；已核实转归位置在目标词条只统计一次。</p>' +
        ''.join(entries) + historical + '</details>')


def render_unresolved_histories(data):
    entries = []
    for item in data.get('ownership_history_unresolved', []):
        transfer = item['transfer']
        row = deepcopy(transfer['source_parent_row'])
        row.pop('ownership_history', None)
        ref = transfer.get('source_history_ref', {})
        link = ('<p><a href="' + escape(ref['url'], quote=True) + '">原界面的完整核对记录</a></p>') if ref.get('url') else ''
        entries.append('<details class="sf-ownership-unresolved"><summary>归属仍待核 · 原 '
            + escape(transfer['source_word']) + ' 记录</summary><p class="sf-reason">' + escape(item['reason'])
            + '</p><p class="sf-reason">原审核完整说明：' + escape(row['reason']) + '</p>' + sf._previews([row])
            + link + '<details><summary>完整来源与归属证据</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + escape(canonical(transfer)) + '</pre></details></details>')
    return ''.join(entries)


def render_append_source_evidence(addition):
    source = addition['native_definition']
    evidence = addition['validated_source_evidence']
    primary = evidence['primary_source']
    pin = primary['source_ref_pin']
    label = addition['source_name_zh'] + ' · ' + addition['source_version']
    url = pin.get('source_url')
    if url and (urlsplit(url).scheme not in {'http', 'https'} or urlsplit(url).username):
        raise ValueError('validated dictionary source URL is not a safe actual web link')
    link = '<p><a href="' + escape(url, quote=True) + '">实际词典原条目</a></p>' if url else ''
    body = ('<h1>' + escape(label) + '</h1><p>实际词头：' + escape(addition['source_headword']) +
        ' · 义项：' + escape(str(addition['sense_ref'])) + '</p>' + link)
    body += ('<h2>原英文释义</h2><p>' + escape(primary['english_definition']) + '</p><h2>主词典原中文</h2><p>' +
        escape(primary['original_chinese'] or '原条目未提供中文') + '</p>')
    kind = addition['translation_kind']
    if kind == 'cross_dictionary_original':
        secondary = evidence['secondary_source']
        body += ('<h2>另一词典原译</h2><p>' + escape(secondary['original_chinese']) + '</p><p>原译词头：' +
            escape(str(secondary['source_ref_pin'].get('source_headword', ''))) + '</p>')
    elif kind == 'reviewed_translation':
        body += '<h2>本次补译</h2><p>' + escape(evidence['text']) + '</p><p>实际双语检索证据完整保存在下方来源记录。</p>'
    body += ('<h2>词性、范围与上下文依据</h2><p>' + escape(str(source.get('grammatical_scope', ''))) +
        '</p><p>' + escape(str(source.get('context_reason', ''))) + '</p><details><summary>完整不可变来源与翻译记录</summary><pre>' +
        escape(canonical(addition)) + '</pre></details>')
    return ('<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>' + escape(label) +
        '</title><style>body{margin:16px auto;padding:0 16px;max-width:760px;font:14px/1.7 system-ui;overflow-wrap:anywhere}'
        'h1{font-size:20px}h2{font-size:16px}pre{white-space:pre-wrap}a{overflow-wrap:anywhere}</style></head><body>' + body + '</body></html>')


def _render_with_source_jumps(report, source_jumps=None):
    """Add safe original-paper links only to the current physical SF sentence."""
    from anki_pipeline.native_example_usage import _Offsets
    from anki_pipeline.packaging import _source_jump
    rendered = sf.render_report(report)
    if not source_jumps:
        return rendered
    edits = []
    for article in _Offsets(rendered, {}).root.walk():
        if article.tag != 'article' or 'sf-example' not in article.classes:
            continue
        identity = article.attrs.get('data-sf-occurrence-id')
        if identity not in source_jumps:
            continue
        if any('sf-ownership-history' in node.classes or 'sf-original-history-panel' in node.classes
               for node in _ancestors(article.parent)):
            continue
        sources = [node for node in article.children if node.tag == 'p' and 'sf-source' in node.classes]
        if len(sources) != 1 or sources[0].end is None:
            raise ValueError('owner sentence lacks its unique actual source label')
        jump = _source_jump(source_jumps[identity])
        if not jump:
            raise ValueError('owner sentence has no safe original-paper source URLs')
        position = rendered.rfind('</p>', sources[0].start, sources[0].end)
        if position < 0:
            raise ValueError('owner sentence source label has no exact closing boundary')
        edits.append((position, position, jump))
    return apply_edits(rendered, edits)[0]


def _ancestors(node):
    while node is not None:
        yield node
        node = node.parent


def _render_without_global_hint(report, source_jumps=None):
    """Suppress only repeated current-report prose, never archived evidence."""
    from anki_pipeline.native_example_usage import _Offsets
    rendered = _render_with_source_jumps(report, source_jumps)
    parsed = _Offsets(rendered, {})
    edits = []
    for node in parsed.root.walk():
        if (node.tag == 'p' and 'sf-hint' in node.classes and node.parent is not None
                and 'sf-report' in node.parent.classes and node.parent.parent is parsed.root):
            if node.end is None:
                raise ValueError('current report global hint has no complete boundary')
            edits.append((node.start, node.end, ''))
    return apply_edits(rendered, edits)[0]


def render_page(page, before, after, ledger, *, source_url, target_url, aliases=None, target_urls=None,
                appended_source_urls=None, ownership_history_documents=None, actual_bound_targets=(), transfer_failures=None,
                source_jumps=None):
    """Replace reports and counts; retain original source labels and media base."""
    parsed = _Spans(page, aliases)
    reports = [n for n in parsed.nodes if n['kind'] == 'report']
    if not reports:
        raise ValueError('word card has no accepted SF report')
    old_senses = before['senses']
    expected = [' '.join((s['pos'] + ' ' + s['text']).split()) for s in old_senses]
    meanings = [' '.join(m.split()) for n in reports for m in n['meanings']]
    if meanings != expected or any(n['attrs'].get('data-snapshot') != before['snapshot_id'] for n in reports):
        raise ValueError('accepted report senses/order/snapshot differ from the parent payload')
    from anki_pipeline.sense_groups import display_report
    # A common group may span dictionaries/components. Resolve it exactly once
    # against the complete report, then retain its canonical global ordinal.
    view = display_report(sf.report_from_record(after))
    view['ownership_history_documents'] = ownership_history_documents or {}
    view['ownership_history_target_urls'] = target_urls or {}
    diagnostics = []
    for item in ledger.get('excluded', []):
        if item['exclusion_kind'] == 'cloze_option':
            continue
        prior = item.get('prior_exclusion') or item
        if prior.get('exclusion_kind') not in {'wrong_lemma', 'reviewed_rehome'}:
            continue
        oid = item['occurrence_id']
        if any(key[0] == oid for key in actual_bound_targets):
            continue
        diagnostics.append({'occurrence': item['occurrence'], 'ownership': item.get('ownership'),
            'authority': item.get('authority'), 'exclusion_kind': item['exclusion_kind'],
            'reason': (transfer_failures or {}).get(oid, '目标词卡或对应义项尚未核实；完整原记录未完成转归，不计本词频次')})
    view['ownership_pending_diagnostics'] = diagnostics
    def historical_source_key(transfer):
        return (transfer['book_id'],transfer['source_card_id'],transfer['source_parent_snapshot_id'],
            sf._sha(sf._json(transfer['source_parent_row'])),transfer['target_card_id'],transfer['target_occurrence_id'])
    resolved_history_keys = {historical_source_key(h) for row in after['occurrences'] for h in row.get('ownership_history', [])}
    for item in after.get('ownership_history_unresolved', []):
        transfer = item['transfer']
        if historical_source_key(transfer) in resolved_history_keys:
            continue  # Original failed attempt stays immutable in the DB audit.
        if not ef.exclude_cloze_option(exam_usage.occurrence_sentence(transfer['source_parent_row'])):
            view['ownership_pending_diagnostics'].append({'occurrence': transfer['source_parent_row'],
                'reason': item['reason'], 'ownership': transfer, 'target_occurrence_id': transfer['target_occurrence_id']})

    retained_ids = {row['occurrence_id'] for group in view['senses'] for row in group['occurrences']}
    retained_ids.update(row['occurrence_id'] for row in view['pending'])

    def report_subset(groups, pending, *, include_archived=False):
        # Resolve ownership notes against the complete view before splitting
        # dictionary components. A target in another component is not an
        # archived example, and a genuinely unbound example appears once.
        local_ids = {row['occurrence_id'] for group in groups for row in group['occurrences']}
        local_ids.update(row['occurrence_id'] for row in pending)
        notes = []
        for item in view['ownership_pending_diagnostics']:
            identity = item.get('target_occurrence_id', item['occurrence']['occurrence_id'])
            if identity in local_ids or (include_archived and identity not in retained_ids):
                notes.append(item)
        return {**view, 'senses': groups, 'pending': pending, 'pending_count': len(pending),
                'ownership_pending_diagnostics': notes}

    edits, ordinal = [], 0
    for index, node in enumerate(reports):
        count = len(node['meanings'])
        subset = report_subset([group for group in view['senses']
            if ordinal <= group['ordinal'] < ordinal + count],
            view['pending'] if not index else [], include_archived=not index)
        rendered = (_render_without_global_hint(subset, source_jumps) if index
                    else _render_with_source_jumps(subset, source_jumps))
        edits.append((node['start'], node['end'], rendered))
        ordinal += count
    appended_source_urls = appended_source_urls or {}
    new_groups = [group for group in view['senses'] if group['ordinal'] >= len(before['senses'])]
    additions = {item['ordinal']: item for item in ledger.get('new_definitions', [])}
    appended_html = []
    for group in new_groups:
        addition = additions[group['ordinal']]
        href = appended_source_urls.get(group['ordinal'])
        if not href:
            raise ValueError('new dictionary sense lacks its actual immutable source page')
        label = addition['source_name_zh'] + ' · ' + addition['source_version']
        if addition['translation_kind'] == 'cross_dictionary_original': label += ' · 另一词典原译'
        elif addition['translation_kind'] == 'reviewed_translation': label += ' · 本次补译'
        source_label = ('<p class="supplement-source"><a href="' + escape(href, quote=True) + '" title="' +
            escape(addition['source_headword'] + ' · ' + str(addition['sense_ref']), quote=True) + '">' + escape(label) + '</a></p>')
        subset = report_subset([group], [])
        report = _render_without_global_hint(subset, source_jumps)
        appended_html.append('<section class="supplement-definition">' + source_label + report + '</section>')
    if appended_html:
        start, end, replacement = edits[len(reports) - 1]
        edits[len(reports) - 1] = start, end, replacement + ''.join(appended_html)
    for node in parsed.nodes:
        if node['kind'] == 'diagnostic':
            edits.append((node['start'], node['end'], ''))
    excluded = ledger.get('excluded', [])
    panels = [n for n in parsed.nodes if n['kind'] == 'frequency']
    # Classification of a removed row may now be "cloze_option", while the
    # accepted parent already excluded it as X. The parent mask is independent
    # of the new counting label and must never be inferred from that label.
    wrong = set(ledger.get('prior_wrong_lemma_ids', []))
    if not wrong.issubset({r['occurrence_id'] for r in before['occurrences']}):
        raise ValueError('parent wrong-binding mask names an unknown source position')
    old_candidates = [r for r in before['occurrences'] if r['occurrence_id'] not in wrong]
    new_rows = after['occurrences']
    if len(panels) > 1:
        components = before['definition_provenance'].get('components', [])
        names = [c['headword'] for c in components]
        if len(names) != len(panels):
            raise ValueError('compound frequency panels lack complete source components')
        old_groups, groups = _component_rows(old_candidates, names), _component_rows(new_rows, names)
    else:
        old_groups, groups = [old_candidates], [new_rows]
    if not panels:
        raise ValueError('accepted word card lacks its frequency panel')
    for node, old_rows, rows in zip(panels, old_groups, groups):
        corpus = int(node['attrs']['data-corpus-papers'])
        old_frequency = _frequency(old_rows, corpus)
        attrs = node['attrs']
        for field, key in [('data-occurrences', 'occurrences'), ('data-paper-count', 'paper_count'),
                ('data-matched-sentences', 'matched_sentences')]:
            if int(attrs[field]) != old_frequency[key]:
                raise ValueError('accepted frequency differs from its parent candidate set')
        if float(attrs['data-stars']) != old_frequency['stars']:
            raise ValueError('accepted star rating differs from its parent candidate set')
        frequency = _frequency(rows, corpus)
        breakdown = _breakdown(rows, sum(i['exclusion_kind'] == 'cloze_option' for i in excluded))
        edits.append((node['start'], node['end'], _exam_frequency_markup(
            {'exam_frequency': frequency, 'exam_frequency_breakdown': breakdown})))
    css = Path(sf.__file__).with_name('templates').joinpath('sense-frequency.css').read_text()
    style = re.search(r'(<style data-supplement-preview="style">)(.*?)(</style>)', page, flags=re.S)
    if not style:
        raise ValueError('accepted card lacks its scoped SF style')
    # Preserve source attribution CSS after the SF template's final dark rule.
    suffix = style[2][style[2].find('\n.supplement-definition'):] if '\n.supplement-definition' in style[2] else ''
    edits.append((style.start(2), style.end(2), css + suffix))
    if re.search(r'<base\b', page, flags=re.I):
        raise ValueError('accepted page already has a base URL')
    head = page.find('<head>')
    if head < 0:
        raise ValueError('accepted card has no unique head')
    edits.append((head + len('<head>'), head + len('<head>'), '<base href="' + escape(source_url, quote=True) + '">'))
    for match in re.finditer(r'(\bhref\s*=\s*["\'])(#[^"\']*)(["\'])', page):
        edits.append((match.start(2), match.end(2), escape(target_url + match[2], quote=True)))
    updated, proof = apply_edits(page, edits)
    if restore_edits(updated, proof) != page:
        raise ValueError('unrelated source page bytes did not survive the inverse')
    return updated, proof, _frequency(new_rows), _breakdown(new_rows,
        sum(i['exclusion_kind'] == 'cloze_option' for i in excluded))


def apply_edits(page, edits):
    edits = sorted(edits, key=lambda e: (e[0], e[1]))
    previous, pieces, cursor, offset, proof = -1, [], 0, 0, []
    for start, end, replacement in edits:
        if not 0 <= start <= end <= len(page) or start < previous:
            raise ValueError('page replacement spans overlap or are invalid')
        original = page[start:end]
        pieces.extend((page[cursor:start], replacement))
        proof.append({'range': [start + offset, start + offset + len(replacement)],
            'original': original, 'replacement_sha256': hashlib.sha256(replacement.encode()).hexdigest()})
        cursor, previous = end, end
        offset += len(replacement) - (end - start)
    pieces.append(page[cursor:])
    return ''.join(pieces), proof


def restore_edits(page, proof):
    for item in reversed(proof):
        start, end = item['range']
        if hashlib.sha256(page[start:end].encode()).hexdigest() != item['replacement_sha256']:
            raise ValueError('changed report cannot pass the original byte inverse')
        page = page[:start] + item['original'] + page[end:]
    return page


def _catalog_summary(summary, frequency):
    match = re.match(r'^真题词频\s+\d+\s+次\s+覆盖\s+\d+\s*/\s*\d+\s+套\s+[0-5](?:\.5)?\s*/\s*5(?P<tail>.*)$', summary, flags=re.S)
    if summary.startswith('真题词频') and not match:
        raise ValueError('unknown accepted catalog frequency prefix')
    tail = match['tail'] if match else ' ' + summary
    return (f"真题词频 {frequency['occurrences']} 次 覆盖 {frequency['paper_count']} / "
            f"{frequency['corpus_papers']} 套 {frequency['stars']:g} / 5" + tail)


def _fresh_path(path, forbidden):
    path = Path(path).resolve()
    if path.exists() or any(Path(str(path) + s).exists() for s in ('-wal', '-shm', '-journal')):
        raise ValueError('new destination already exists: ' + str(path))
    if any(path == p or p in path.parents or path in p.parents for p in forbidden):
        raise ValueError('destination overlaps an accepted input')
    return path


def _card_items(row, field):
    if not row:
        return []
    values = row.get(field, [])
    if not isinstance(values, list):
        raise ValueError('per-card ' + field + ' must be an array')
    return values


def install_native_runtime(page, aliases, *, source_path, web_root):
    """Resolve absolute local bundle URLs for the helper's exact source path.

    Only script-reference text is adapted, reversibly; the helper still checks
    content-addressed bytes and replaces only its supported chunk bootstrap.
    """
    from anki_pipeline.native_example_usage import install_chunk_runtime
    edits = []
    for tag in re.finditer(r'<script\b[^>]*>', page, flags=re.I):
        match = re.search(r'\bsrc\s*=\s*(["\'])(/[^"\']*)\1', tag[0], flags=re.I)
        if match:
            asset = _local_url(match[2], web_root)
            relative = os.path.relpath(asset, Path(source_path).resolve(strict=True).parent)
            edits.append((tag.start() + match.start(2), tag.start() + match.end(2), relative))
    adapted, reference_inverse = apply_edits(page, edits)
    runtime = install_chunk_runtime(adapted, aliases, source_path=source_path)
    return runtime, reference_inverse


def _database_stat(path):
    stat = Path(path).stat()
    return {'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'inode': stat.st_ino}


def _checked_database_hash(path):
    _assert_standalone_database(path)
    before = _database_stat(path)
    sha256 = file_sha(path)
    _assert_standalone_database(path)
    if _database_stat(path) != before:
        raise ValueError('private database changed while hashing its checkpoint')
    return {'file': str(Path(path).resolve()), 'sha256': sha256, 'stat': before}


def _assert_standalone_database(path):
    """A main-file hash must certify every committed SQLite data page."""
    with Path(path).open('rb') as handle:
        header = handle.read(100)
    if header[:16] != b'SQLite format 3\0' or header[18:20] != b'\x01\x01':
        raise ValueError('private checkpoint database is not standalone DELETE journal mode')
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('private checkpoint database has an unaccepted nonempty sidecar: ' + str(sidecar))


def _load_render_code_continuation(path, checksum, checkpoint_pin, checkpoint, request):
    pin = {'file': str(pin_file({'file': str(path), 'sha256': checksum})), 'sha256': checksum}
    continuation = {'pin': pin, 'payload': _read_json(Path(pin['file']))}
    payload = continuation['payload']
    expected_keys = {'schema', 'scope', 'request', 'prepared_checkpoint', 'run_id', 'database',
                     'original_code_pins', 'writer_change', 'proof_pins'}
    if (set(payload) != expected_keys or payload.get('schema') != RENDER_CONTINUATION_SCHEMA
            or payload.get('scope') != 'writer_report_hint_presentation_only'
            or payload.get('request') != checkpoint.get('request')
            or payload.get('prepared_checkpoint') != checkpoint_pin
            or payload.get('run_id') != checkpoint.get('run_id')
            or payload.get('database') != checkpoint.get('database')
            or payload.get('original_code_pins') != checkpoint.get('code_pins')
            or payload.get('original_code_pins') != request.get('code_pins', {})):
        raise ValueError('render code continuation differs from its original checkpoint/request/run/database/code scope')
    change = payload['writer_change']
    if not isinstance(change, dict) or set(change) != {'old', 'new', 'backup'}:
        raise ValueError('render code continuation requires one exact old/new writer and complete backup')
    old, new, backup = change['old'], change['new'], change['backup']
    if (not all(isinstance(value, dict) and set(value) == {'file', 'sha256'} for value in (old, new, backup))
            or old['file'] != new['file'] or Path(old['file']).resolve() != Path(__file__).resolve()
            or old['sha256'] == new['sha256'] or backup['sha256'] != old['sha256']
            or Path(backup['file']).resolve() == Path(old['file']).resolve()
            or sum(value == old for value in payload['original_code_pins'].values()) != 1):
        raise ValueError('render code continuation may replace only this exact writer, retaining its accepted backup')
    if not isinstance(payload['proof_pins'], list) or not payload['proof_pins']:
        raise ValueError('render code continuation lacks its pinned follow and independent review evidence')
    _render_code_pins(request, continuation)
    return continuation


def _render_code_pins(request, continuation=None):
    """Use a bounded approved writer delta; every other code pin stays exact."""
    if continuation is None:
        return request.get('code_pins', {})
    pin, payload = continuation['pin'], continuation['payload']
    if _read_json(pin_file(pin)) != payload:
        raise ValueError('render code continuation payload changed')
    pin_file(payload['request'])
    pin_file(payload['prepared_checkpoint'])
    change = payload['writer_change']
    pin_file(change['backup'])
    pin_file(change['new'])
    for proof in payload['proof_pins']:
        pin_file(proof)
    return {key: change['new'] if value == change['old'] else value
            for key, value in request['code_pins'].items()}


def _render_continuation_evidence(request, continuation):
    if continuation is None:
        return {}
    payload = continuation['payload']
    change = payload['writer_change']
    return {'render_code_continuation': {'approval': continuation['pin'],
        'prepared_checkpoint': payload['prepared_checkpoint'],
        'writer_change': payload['writer_change'], 'proof_pins': payload['proof_pins'],
        'original_code_pins': payload['original_code_pins'],
        'actual_code_pins': {key: change['new'] if value == change['old'] else value
                             for key, value in request['code_pins'].items()}}}


def _execution_pins(request, context_pins=(), *, render_continuation=None):
    pin_file(request['source_database'])
    for pin in context_pins:
        pin_file(pin)
    for name in ('policies', 'residual_decisions', 'sense_groups', 'legacy_wrong_bindings',
                 'dictionary_sources', 'reading_answers', 'native_source_aliases', 'residual_ownership',
                 'reading_display_projection'):
        if request.get(name):
            pin_file(request[name])
    if request.get('reading_display_projection'):
        for path, checksum in _read_json(pin_file(request['reading_display_projection']))['source_files'].items():
            pin_file({'file': path, 'sha256': checksum})
    for pin in _render_code_pins(request, render_continuation).values():
        pin_file(pin)
    for book in request['books']:
        pin_file(book['entry'])
        if book.get('catalog'):
            pin_file(book['catalog'])


def _check_private_integrity(db):
    if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise ValueError('new database integrity check failed')


def _write_prepared_checkpoint(path, payload):
    # A partial checkpoint never certifies a retained database.
    identity = None
    try:
        with Path(path).open('x', encoding='utf-8') as handle:
            stat = os.fstat(handle.fileno())
            identity = (stat.st_dev, stat.st_ino)
            handle.write(canonical(payload) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if identity is not None:
            _unlink_owned_checkpoint(path, identity)
        raise
    return identity


def _unlink_owned_checkpoint(path, identity):
    try:
        stat = Path(path).stat()
    except FileNotFoundError:
        return
    if (stat.st_dev, stat.st_ino) != identity:
        raise ValueError('unready checkpoint was replaced by an external file; it was preserved')
    Path(path).unlink()


def _validate_prepared_checkpoint(checkpoint, request_path, expected_sha256, request, run, new_db,
                                  *, render_continuation=None):
    if (checkpoint.get('schema') != CHECKPOINT_SCHEMA
            or checkpoint.get('request') != {'file': str(request_path), 'sha256': expected_sha256}
            or checkpoint.get('run') != run or checkpoint.get('run_id') != digest(run)
            or checkpoint.get('code_pins') != request.get('code_pins', {})
            or checkpoint.get('source_database') != request['source_database']
            or checkpoint.get('integrity') != {'quick_check': 'ok', 'foreign_keys': 'ok', 'write_connections_closed': True}):
        raise ValueError('prepared checkpoint does not exactly bind the accepted request/run/code/source')
    database = checkpoint.get('database', {})
    _assert_standalone_database(new_db)
    if (database.get('file') != str(new_db) or database.get('stat') != _database_stat(new_db)
            or database.get('sha256') != file_sha(new_db)):
        raise ValueError('prepared checkpoint database pin or identity changed')
    _assert_standalone_database(new_db)
    _execution_pins(request, checkpoint.get('residual_context_pins', []),
                    render_continuation=render_continuation)
    with closing(_ro(new_db)) as db:
        if db.execute('PRAGMA journal_mode').fetchone()[0] != 'delete':
            raise ValueError('prepared checkpoint database journal mode changed')
        row = db.execute('SELECT payload_sha256,payload FROM exam_usage_update_runs WHERE id=?',
                         (checkpoint['run_id'],)).fetchone()
        if row != (digest(run), canonical(run)):
            raise ValueError('prepared checkpoint database run payload does not reconcile')
        count = db.execute('SELECT count(*) FROM exam_usage_parent_snapshots WHERE run_id=?',
                           (checkpoint['run_id'],)).fetchone()[0]
        if count != checkpoint.get('word_cards') or not count:
            raise ValueError('prepared checkpoint word-card count differs from its persisted run')


def resume_render(checkpoint_path, expected_sha256, *, request_path=None, request_sha256=None,
                  continuation_path=None, continuation_sha256=None):
    checkpoint_path = pin_file({'file': str(checkpoint_path), 'sha256': expected_sha256})
    checkpoint = _read_json(checkpoint_path)
    accepted = checkpoint.get('request', {})
    if request_path is not None and Path(request_path).resolve() != Path(accepted.get('file', '')).resolve():
        raise ValueError('resume request differs from its pinned prepared checkpoint')
    if request_sha256 is not None and request_sha256 != accepted.get('sha256'):
        raise ValueError('resume request pin differs from its prepared checkpoint')
    continuation = None
    if continuation_path is not None or continuation_sha256 is not None:
        if continuation_path is None or continuation_sha256 is None:
            raise ValueError('render code continuation requires both its file and exact SHA pin')
        request = _read_json(pin_file(accepted))
        continuation = _load_render_code_continuation(continuation_path, continuation_sha256,
            {'file': str(checkpoint_path), 'sha256': expected_sha256}, checkpoint, request)
    return update(accepted['file'], accepted['sha256'], trial_words=checkpoint['run']['trial_words'],
                  _prepared_checkpoint=checkpoint,
                  _checkpoint_pin={'file': str(checkpoint_path), 'sha256': expected_sha256},
                  _render_code_continuation=continuation)


def _save_failed_render(checkpoint_pin, checkpoint, error, cleanup_errors, *, continuation_evidence=None):
    """Record an observed failure, without inventing the later process exit code."""
    database = Path(checkpoint['database']['file'])
    parent = Path(checkpoint_pin['file']).parent
    descriptor, name = tempfile.mkstemp(prefix=database.name + '.render-failure-', suffix='.json', dir=parent)
    payload = {'schema': 'exam-usage-render-failure.v1', 'request': checkpoint['request'],
        'run_id': checkpoint['run_id'], 'prepared_checkpoint': checkpoint_pin,
        'database': checkpoint['database'], 'database_retained': database.is_file(),
        'database_stat_matches_checkpoint': database.is_file() and _database_stat(database) == checkpoint['database']['stat'],
        'exception_type': type(error).__name__, 'message': str(error),
        'traceback': traceback.format_exc(), 'cleanup_errors': cleanup_errors,
        'terminal_exit_code': None, 'terminal_status': 'awaiting actual executor terminal readback',
        **(continuation_evidence or {})}
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        handle.write(canonical(payload) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    pin = {'file': name, 'sha256': file_sha(name)}
    print(canonical({'stage': 'render_failed_private_database_retained', 'run_id': checkpoint['run_id'],
        'prepared_checkpoint': checkpoint_pin, 'failure_receipt': pin}), file=sys.stderr, flush=True)
    return pin


def update(request_path, expected_sha256, *, trial_words=(), transform=None,
           _prepared_checkpoint=None, _checkpoint_pin=None, _render_code_continuation=None):
    started = time.monotonic()
    timings = {}
    request_path = pin_file({'file': str(request_path), 'sha256': expected_sha256})
    request = _read_json(request_path)
    if request.get('schema') != SCHEMA:
        raise ValueError('unknown usage update request')
    if _render_code_continuation is not None:
        if _prepared_checkpoint is None or _checkpoint_pin is None:
            raise ValueError('render code continuation requires an existing pinned checkpoint and read-only resume')
        _render_code_continuation = _load_render_code_continuation(
            _render_code_continuation['pin']['file'], _render_code_continuation['pin']['sha256'],
            _checkpoint_pin, _prepared_checkpoint, request)
    source_db = pin_file(request['source_database'])
    for pin in _render_code_pins(request, _render_code_continuation).values():
        pin_file(pin)
    sidecars = load_validated_policy_sidecars(request) if _prepared_checkpoint is None else None
    source_aliases = None
    if request.get('native_source_aliases'):
        pin_file(request['native_source_aliases'])
        from anki_pipeline.native_example_usage import load_source_aliases
        source_aliases = load_source_aliases(request['native_source_aliases'])
    web_root = Path(request['web_root']).resolve(strict=True)
    books = [(book, load_catalog(book, web_root)) for book in request['books']]
    selected_words = {w.casefold() for w in trial_words}
    trial = bool(selected_words)
    trial_root = Path(request['trial_output']).resolve() if trial else None
    if trial:
        if _prepared_checkpoint is None:
            _fresh_path(trial_root, [source_db, *(entry.parent for _, (entry, _, _, _) in books)])
        new_db = trial_root / 'usage-trial.sqlite3'
    else:
        new_db = (Path(request['new_database']).resolve(strict=True) if _prepared_checkpoint is not None
                  else _fresh_path(request['new_database'], [source_db]))
    outputs = [trial_root / book['book_id'] if trial else Path(book['output']).resolve() for book, _ in books]
    outputs_by_book = {book['book_id']: output for (book, _), output in zip(books, outputs)}
    card_sources = {(book['book_id'], c['id']): c for book, (_, _, _, catalog) in books for c in catalog['cards']}
    for output in outputs:
        _fresh_path(output, [entry.parent for _, (entry, _, _, _) in books])
    if transform is None:
        from anki_pipeline.exam_usage_policy import transform_record
        transform = transform_record
    run = {'schema': SCHEMA, 'request': {'file': str(request_path), 'sha256': expected_sha256},
        'source_database': request['source_database'], 'mode': 'trial' if trial else 'full',
        'trial_words': sorted(selected_words), 'input_pins': {k: request[k] for k in
        ('policies', 'residual_decisions', 'sense_groups', 'legacy_wrong_bindings', 'dictionary_sources', 'reading_answers',
            'native_source_aliases', 'residual_ownership') if k in request}}
    for name in ('reading_display_projection', 'reading_display_replay'):
        if name in request:
            run['input_pins'][name] = deepcopy(request[name])
    run_id = digest(run)
    version_relative = Path('web-preview') / run_id
    checkpoint_path = Path(str(new_db) + '.prepared.json')
    if _prepared_checkpoint is None:
        _fresh_path(checkpoint_path, [source_db])
    elif _checkpoint_pin is None or Path(_checkpoint_pin['file']) != checkpoint_path:
        raise ValueError('prepared checkpoint path does not belong to the requested private database')
    stages, published, created_db = [], [], False
    checkpoint_ready = False
    owned_checkpoint_identity = None
    aliases_by_version = {}
    total, snapshot_changes = 0, 0
    timings['input_validation'] = time.monotonic() - started
    print(canonical({'stage': 'inputs_validated', 'elapsed_seconds': round(timings['input_validation'], 3)}), file=sys.stderr, flush=True)
    try:
        if _prepared_checkpoint is None:
            new_db.parent.mkdir(parents=True, exist_ok=True)
            with new_db.open('xb'):
                pass
            created_db = True
            with closing(_ro(source_db)) as original, closing(sqlite3.connect(new_db)) as db:
                original.execute('BEGIN')
                residual_rehomes, residual_context_pins = normalized_residual_rehomes(request.get('residual_ownership'), original)
                phase_started = time.monotonic()
                if trial:
                    db.executescript('BEGIN IMMEDIATE;\n' + sf._SQL + '\nPRAGMA user_version=2;\nCOMMIT;')
                else:
                    original.backup(db)
                timings['clone_or_trial_schema'] = time.monotonic() - phase_started
                db.execute('PRAGMA foreign_keys=ON')
                db.executescript(_LEDGER_SQL)
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO exam_usage_update_runs VALUES(?,?,?)', (run_id, digest(run), canonical(run)))
                try:
                    phase_started = time.monotonic()
                    for book, (_, _, _, catalog) in books:
                        for card in catalog['cards']:
                            if selected_words and card.get('word', '').casefold() not in selected_words:
                                continue
                            key = book['book_id'], card['id']
                            saved = original.execute('SELECT s.id,s.payload FROM active_snapshots a JOIN snapshots s '
                                'ON s.id=a.snapshot_id WHERE a.book_id=? AND a.card_id=?', key).fetchone()
                            if saved is None:
                                if selected_words:
                                    raise ValueError('selected word has no active source snapshot')
                                continue
                            before = json.loads(saved[1])
                            if before['snapshot_id'] != saved[0] or before['word'] != card['word']:
                                raise ValueError('catalog differs from its accepted database source')
                            # The ownership audit is intentionally sparse: omitted
                            # cards receive only the already approved count policy,
                            # never a manufactured ownership decision.
                            policy = dict(sidecars['policies'].get(key, {}))
                            if key in residual_rehomes:
                                policy['confirmed_new_exclusions'] = merge_confirmed_rehomes(before,
                                    policy.get('confirmed_new_exclusions', []), residual_rehomes[key],
                                    policy_pin=request['policies'],
                                    parent_lookup=lambda book, card: _active_prepared(original, book, card))
                            if sidecars['dictionary_sources']:
                                policy['verified_dictionary_sources'] = sidecars['dictionary_sources']
                            if sidecars['reading_answers'] is not None:
                                policy['reading_answers'] = sidecars['reading_answers']
                            if key in sidecars['reading_display_projection']:
                                policy['reading_display_projection'] = sidecars['reading_display_projection'][key]
                            wrong = sidecars['legacy_wrong_bindings'].get(key, {}).get('excluded', [])
                            try:
                                changed = transform(record_from_prepared(before), baseline_prepared=before,
                                    policy=policy, residual_decisions=_card_items(sidecars['residual_decisions'].get(key), 'decisions'),
                                    sense_groups=_card_items(sidecars['sense_groups'].get(key), 'equivalences'), excluded_occurrences=wrong)
                            except ValueError as error:
                                raise ValueError(f"{book['book_id']}/{card['word']}/{card['id']}/parent={before['snapshot_id']}: {error}") from error
                            if not isinstance(changed, dict) or set(changed) != {'record', 'scope_ledger'}:
                                raise ValueError('transform must return a record and independently bound scope ledger')
                            after = sf.prepare_record(changed['record'])
                            validate_delta(before, after, changed['scope_ledger'],
                                verified_dictionary_sources=sidecars['dictionary_sources'],
                                reading_display_projection=policy.get('reading_display_projection'),
                                parent_lookup=lambda book, card: _active_prepared(original, book, card))
                            insert_prepared(db, after)
                            db.execute('INSERT INTO exam_usage_parent_snapshots VALUES(?,?,?,?,?,?,?,?,?)',
                                (run_id, *key, before['snapshot_id'], after['snapshot_id'],
                                 hashlib.sha256(saved[1].encode()).hexdigest(), saved[1] if trial else '',
                                 digest(changed['scope_ledger']), canonical(changed['scope_ledger'])))
                            total += 1
                            snapshot_changes += before['snapshot_id'] != after['snapshot_id']
                            if total % 250 == 0:
                                print(canonical({'stage': 'snapshots', 'cards': total,
                                    'elapsed_seconds': round(time.monotonic() - phase_started, 3)}), file=sys.stderr, flush=True)
                    if not total:
                        raise ValueError('request selected no active word cards')
                    timings['prepare_snapshots'] = time.monotonic() - phase_started
                    print(canonical({'stage': 'snapshots_prepared', 'cards': total,
                        'elapsed_seconds': round(timings['prepare_snapshots'], 3)}), file=sys.stderr, flush=True)
                    phase_started = time.monotonic()
                    history_stats = attach_incoming_histories(db, original, run_id, card_sources,
                        outputs_by_book, web_root, aliases_by_version)
                    timings['incoming_history'] = time.monotonic() - phase_started
                    print(canonical({'stage': 'incoming_history_bound', **history_stats,
                        'elapsed_seconds': round(timings['incoming_history'], 3)}), file=sys.stderr, flush=True)
                    if db.execute('PRAGMA foreign_key_check').fetchone():
                        raise ValueError('new snapshot/audit foreign keys do not reconcile')
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
                if db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
                    raise ValueError('private database could not be sealed in DELETE journal mode')
                _check_private_integrity(db)
            _execution_pins(request, residual_context_pins)
            checkpoint = {'schema': CHECKPOINT_SCHEMA,
                'request': {'file': str(request_path), 'sha256': expected_sha256},
                'run': run, 'run_id': run_id, 'source_database': request['source_database'],
                'code_pins': request.get('code_pins', {}), 'database': _checked_database_hash(new_db),
                'integrity': {'quick_check': 'ok', 'foreign_keys': 'ok', 'write_connections_closed': True},
                'word_cards': total, 'snapshot_changes': snapshot_changes, 'ownership_history': history_stats,
                'timing_seconds': dict(timings), 'residual_context_pins': residual_context_pins}
            owned_checkpoint_identity = _write_prepared_checkpoint(checkpoint_path, checkpoint)
            _checkpoint_pin = {'file': str(checkpoint_path), 'sha256': file_sha(checkpoint_path)}
            checkpoint_ready = True
            print(canonical({'stage': 'database_checkpoint_saved', 'run_id': run_id,
                'word_cards': total, 'checkpoint': _checkpoint_pin}), file=sys.stderr, flush=True)
        else:
            _validate_prepared_checkpoint(_prepared_checkpoint, request_path, expected_sha256, request, run, new_db,
                                          render_continuation=_render_code_continuation)
            checkpoint = _prepared_checkpoint
            total, snapshot_changes = checkpoint['word_cards'], checkpoint['snapshot_changes']
            history_stats = checkpoint['ownership_history']
            timings = {**checkpoint['timing_seconds'], 'resume_input_validation': time.monotonic() - started}
            residual_context_pins = checkpoint['residual_context_pins']
            checkpoint_ready = True
            print(canonical({'stage': 'readonly_render_resumed', 'run_id': run_id,
                'word_cards': total, 'checkpoint': _checkpoint_pin}), file=sys.stderr, flush=True)
        # Bound rendering reads one parent/child payload at a time, never a run
        # bundle, complete exam corpus or the large composition manifests.
        with closing(_ro(new_db)) as db:
            for (book, (entry, entry_page, catalog_path, catalog)), output in zip(books, outputs):
                phase_started = time.monotonic()
                output.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='.usage-preview-', dir=output.parent))
                stages.append(stage)
                (stage / version_relative / 'cards').mkdir(parents=True)
                (stage / 'sources').mkdir()
                (stage / 'history').mkdir()
                for card_id, parent_sid, source_url, doc_sha, historical in db.execute(
                        'SELECT card_id,parent_snapshot_id,source_url,document_sha256,original_html '
                        'FROM exam_usage_history_documents WHERE run_id=? AND book_id=?', (run_id, book['book_id'])):
                    source_word = card_sources[(book['book_id'], card_id)]['word']
                    doc = _history_document(source_word, parent_sid, source_url, historical)
                    if hashlib.sha256(doc.encode()).hexdigest() != doc_sha:
                        raise ValueError('historical document differs from its immutable SQLite evidence')
                    (stage / 'history' / (card_id + '.html')).write_bytes(doc.encode())
                rows, proofs = [], []
                proof_count = 0
                proof_path = stage / 'verification-card-proofs.jsonl'
                if not trial:
                    proof_path.touch(exist_ok=False)
                target_urls = {c['id']: ('/' + str((output / version_relative / 'cards' / _card_filename(c['id'])).relative_to(web_root))
                    if not selected_words or c['word'].casefold() in selected_words else c['previewUrl']) for c in catalog['cards']}
                for card in catalog['cards']:
                    if selected_words and card.get('word', '').casefold() not in selected_words:
                        continue
                    saved = db.execute('SELECT COALESCE(NULLIF(p.parent_payload,\'\'),parent.payload),p.scope_ledger,s.payload '
                        'FROM exam_usage_parent_snapshots p JOIN snapshots s ON s.id=p.child_snapshot_id '
                        'LEFT JOIN snapshots parent ON parent.id=p.parent_snapshot_id '
                        'WHERE p.run_id=? AND p.book_id=? AND p.card_id=?',
                        (run_id, book['book_id'], card['id'])).fetchone()
                    target_url = '/' + str((output / version_relative / 'cards' / _card_filename(card['id'])).relative_to(web_root))
                    source = _local_url(card['previewUrl'], web_root)
                    page = source.read_bytes().decode('utf-8')
                    source_sha = hashlib.sha256(page.encode()).hexdigest()
                    if saved:
                        before, ledger, after = (json.loads(part) for part in saved)
                        version = source.parent.parent
                        if version not in aliases_by_version:
                            from scripts.prepare_sense_frequency_records import class_aliases
                            aliases_by_version[version] = class_aliases(version)
                        try:
                            from anki_pipeline.native_example_usage import update_native_examples, restore_original
                            history_documents = render_history_payload(db, run_id, after)
                            native = update_native_examples(page, before, after, aliases=aliases_by_version[version],
                                **({'source_aliases': source_aliases} if source_aliases is not None else {}),
                                **({'ownership_history_documents': history_documents, 'target_urls': target_urls,
                                    'defer_ownership_coverage': True}
                                    if history_documents else {}))
                            runtime, runtime_references = install_native_runtime(native['page'], aliases_by_version[version],
                                source_path=source, web_root=web_root)
                            appended_source_urls = {}
                            for addition in ledger.get('new_definitions', []):
                                evidence_page = render_append_source_evidence(addition)
                                evidence_sha = hashlib.sha256(evidence_page.encode()).hexdigest()
                                evidence_path = stage / 'sources' / (evidence_sha + '.html')
                                if evidence_path.exists() and evidence_path.read_bytes() != evidence_page.encode():
                                    raise ValueError('immutable new dictionary evidence has conflicting content')
                                evidence_path.write_bytes(evidence_page.encode())
                                appended_source_urls[addition['ordinal']] = '/' + str(
                                    (output / 'sources' / (evidence_sha + '.html')).relative_to(web_root))
                            revised, inverse, frequency, breakdown = render_page(runtime['page'], before, after, ledger,
                                source_url=card['previewUrl'], target_url=target_url,
                                aliases=aliases_by_version[version], target_urls=target_urls,
                                appended_source_urls=appended_source_urls,
                                ownership_history_documents=history_documents,
                                actual_bound_targets=set(db.execute('SELECT source_occurrence_id,target_card_id,target_occurrence_id '
                                    'FROM exam_usage_transfer_outcomes WHERE run_id=? AND book_id=? AND source_card_id=? AND status=\'bound\'',
                                    (run_id, book['book_id'], card['id']))),
                                transfer_failures=dict(db.execute('SELECT source_occurrence_id,reason FROM exam_usage_transfer_outcomes '
                                    'WHERE run_id=? AND book_id=? AND source_card_id=? AND status!=\'bound\'',
                                    (run_id, book['book_id'], card['id']))))
                            ownership_coverage_proof = None
                            if history_documents:
                                from anki_pipeline.ownership_history import validate_rendered_history_coverage
                                ownership_coverage_proof = validate_rendered_history_coverage(revised, after,
                                    native['ownership_coverage'], ownership_history_documents=history_documents,
                                    target_urls=target_urls, aliases=aliases_by_version[version])
                            restored = restore_original(restore_edits(revised, inverse), runtime['inverse'])
                            restored = restore_edits(restored, runtime_references)
                            restored = restore_original(restored, native['inverse'])
                            if restored != page:
                                raise ValueError('combined SF/native inverse differs from the accepted original')
                        except ValueError as error:
                            raise ValueError(f"{book['book_id']}/{card['word']}/{card['id']}: {error}") from error
                        row = {**card, 'previewUrl': target_url, 'definition': _catalog_summary(card['definition'], frequency),
                            'source_definition_summary': card['definition'], 'exam_frequency': frequency,
                            'exam_frequency_breakdown': breakdown}
                        if 'definition_summary_projection' in row:
                            row['source_definition_summary_projection'] = row.pop('definition_summary_projection')
                        row['exam_usage_summary_projection'] = {'snapshot_id': after['snapshot_id'],
                            'source_summary_sha256': hashlib.sha256(card['definition'].encode()).hexdigest(),
                            'summary_sha256': hashlib.sha256(row['definition'].encode()).hexdigest(), 'frequency': frequency}
                        row['source_example_count'] = card['exampleCount']
                        if native['stats']['native_examples'] or not card['exampleCount']:
                            row['exampleCount'] = native['stats']['native_examples'] - native['stats']['removed_examples']
                        proof = {'card_id': card['id'], 'parent_snapshot_id': before['snapshot_id'],
                            'snapshot_id': after['snapshot_id'], 'source_url': card['previewUrl'],
                            'source_sha256': source_sha, 'inverse': inverse, 'native_inverse': native['inverse'],
                            'native_stats': native['stats'], 'runtime_inverse': runtime['inverse'],
                            'runtime_reference_inverse': runtime_references, 'runtime_stats': runtime['stats'],
                            'scope_ledger_sha256': digest(ledger)}
                        if ownership_coverage_proof is not None:
                            proof['ownership_coverage'] = ownership_coverage_proof
                    else:
                        # The explanation card is source content, not a word
                        # snapshot. Keep its exact bytes and immutable URL.
                        row, revised, proof = dict(card), page, None
                    if proof:
                        target = stage / version_relative / 'cards' / _card_filename(card['id'])
                        target.write_bytes(revised.encode())
                        proof['after_sha256'] = file_sha(target)
                        if file_sha(source) != source_sha:
                            raise ValueError('accepted page changed while rendering')
                        proof_count += 1
                        if trial:
                            proofs.append(proof)
                        else:
                            with proof_path.open('a', encoding='utf-8') as handle:
                                handle.write(canonical(proof) + '\n')
                    rows.append(row)
                    if len(rows) % 100 == 0:
                        print(canonical({'stage': 'render_cards', 'book_id': book['book_id'], 'cards': len(rows),
                            'elapsed_seconds': round(time.monotonic() - phase_started, 3)}), file=sys.stderr, flush=True)
                new_catalog = deepcopy(catalog)
                new_catalog['cards'] = rows
                if trial:
                    ids = {c['id'] for c in rows}
                    new_catalog['decks'] = [{**d, 'cardIds': [i for i in d['cardIds'] if i in ids],
                        'count': sum(i in ids for i in d['cardIds'])} for d in catalog['decks'] if any(i in ids for i in d['cardIds'])]
                    new_catalog['counts'] = {**catalog['counts'], 'cards': len(rows),
                        'decks': len(new_catalog['decks']), 'examples': sum(c['exampleCount'] for c in rows)}
                    new_catalog['source_deck_name'] = catalog['deckName']
                    new_catalog['deckName'] = ('2027' if book['book_id'] == 'redbook2027' else '2026') + ' 红宝书 · '
                    new_catalog['deckName'] += '试览 ' + str(len(rows)) + ' 词（语义与转归验收未完成）'
                else:
                    new_catalog['source_counts'] = catalog['counts']
                    new_catalog['counts'] = {**catalog['counts'], 'examples': sum(c['exampleCount'] for c in rows)}
                (stage / 'catalog.json').write_text(canonical(new_catalog) + '\n')
                catalog_url = '/' + str((output / 'catalog.json').relative_to(web_root))
                shell = re.sub(r'data-catalog-url="[^"]+"', 'data-catalog-url="' + catalog_url + '"', entry_page)
                if '<base ' in shell:
                    raise ValueError('accepted library shell already defines a resource base')
                source_entry_url = '/' + str(entry.relative_to(web_root))
                shell = shell.replace('<head>', '<head><base href="' + escape(source_entry_url, quote=True) + '">', 1)
                if trial:
                    shell = re.sub(r'<title>[^<]*</title>', '<title>' + escape(new_catalog['deckName']) + '</title>', shell, count=1)
                (stage / 'preview-library.html').write_text(shell)
                verification = {'schema': SCHEMA, 'run_id': run_id,
                    'mode': run['mode'], 'card_count': proof_count, 'source_catalog': {'file': str(catalog_path),
                    'sha256': file_sha(catalog_path)}, 'source_entry': book['entry'],
                    **_render_continuation_evidence(request, _render_code_continuation)}
                if trial:
                    verification['cards'] = proofs
                else:
                    verification['card_proofs'] = {'file': str(output / proof_path.name), 'sha256': file_sha(proof_path),
                        'format': 'JSONL', 'records': proof_count}
                (stage / 'verification.json').write_text(canonical(verification) + '\n')
                timings['render_' + book['book_id']] = time.monotonic() - phase_started
                print(canonical({'stage': 'rendered', 'book_id': book['book_id'], 'cards': len(rows),
                    'elapsed_seconds': round(timings['render_' + book['book_id']], 3)}), file=sys.stderr, flush=True)
        _execution_pins(request, residual_context_pins, render_continuation=_render_code_continuation)
        if request.get('native_source_aliases'):
            # This is a fresh validation at publication, not the sealed object
            # reused during the card loop.
            load_source_aliases(request['native_source_aliases'])
        for pin in _render_code_pins(request, _render_code_continuation).values():
            pin_file(pin)
        for book, _ in books:
            pin_file(book['entry'])
            if book.get('catalog'):
                pin_file(book['catalog'])
        _assert_standalone_database(new_db)
        if (_database_stat(new_db) != checkpoint['database']['stat']
                or file_sha(new_db) != checkpoint['database']['sha256']):
            raise ValueError('checkpoint database changed during read-only rendering')
        _assert_standalone_database(new_db)
        for stage, output in zip(stages, outputs):
            if output.exists():
                raise ValueError('destination appeared before publication')
            stage.rename(output)
            published.append(output)
        return {'schema': SCHEMA, 'run_id': run_id, 'new_database': str(new_db), 'mode': run['mode'],
            'word_cards': total, 'snapshot_changes': snapshot_changes,
            'ownership_history': history_stats,
            'timing_seconds': {**timings, 'whole': time.monotonic() - started},
            'entries': [{'book_id': book['book_id'], 'entry': str(output / 'preview-library.html')}
                for (book, _), output in zip(books, outputs)], 'accepted_source_unchanged': True,
            'database_sha256': checkpoint['database']['sha256'], 'prepared_checkpoint': _checkpoint_pin,
            'render_resumed': _prepared_checkpoint is not None,
            **_render_continuation_evidence(request, _render_code_continuation)}
    except BaseException as error:
        cleanup_errors = []
        for path in [*stages, *published]:
            if path.exists():
                try:
                    shutil.rmtree(path)
                except OSError as cleanup_error:
                    cleanup_errors.append({'file': str(path), 'error': str(cleanup_error)})
        if created_db and not checkpoint_ready:
            if owned_checkpoint_identity is not None:
                try:
                    _unlink_owned_checkpoint(checkpoint_path, owned_checkpoint_identity)
                except (OSError, ValueError) as cleanup_error:
                    cleanup_errors.append({'file': str(checkpoint_path), 'error': str(cleanup_error)})
            for suffix in ('', '-wal', '-shm', '-journal'):
                try:
                    Path(str(new_db) + suffix).unlink(missing_ok=True)
                except OSError as cleanup_error:
                    cleanup_errors.append({'file': str(new_db) + suffix, 'error': str(cleanup_error)})
        if trial_root and trial_root.exists() and not any(trial_root.iterdir()):
            trial_root.rmdir()
        if checkpoint_ready:
            try:
                _save_failed_render(_checkpoint_pin, checkpoint, error, cleanup_errors,
                    continuation_evidence=_render_continuation_evidence(request, _render_code_continuation))
            except OSError as receipt_error:
                print(canonical({'stage': 'render_failure_receipt_write_failed', 'error': str(receipt_error),
                    'prepared_checkpoint': _checkpoint_pin}), file=sys.stderr, flush=True)
        if cleanup_errors:
            print(canonical({'stage': 'private_output_cleanup_incomplete', 'errors': cleanup_errors}),
                file=sys.stderr, flush=True)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--trial-word', action='append', dest='trial_words')
    mode.add_argument('--resume-render', type=Path)
    parser.add_argument('--checkpoint-sha256')
    parser.add_argument('--render-code-continuation', type=Path)
    parser.add_argument('--render-code-continuation-sha256')
    args = parser.parse_args(argv)
    if args.resume_render:
        if not args.checkpoint_sha256:
            parser.error('--resume-render requires --checkpoint-sha256')
        result = resume_render(args.resume_render, args.checkpoint_sha256,
            request_path=args.request, request_sha256=args.sha256,
            continuation_path=args.render_code_continuation,
            continuation_sha256=args.render_code_continuation_sha256)
    else:
        if args.checkpoint_sha256:
            parser.error('--checkpoint-sha256 is valid only for --resume-render')
        if args.render_code_continuation is not None or args.render_code_continuation_sha256 is not None:
            parser.error('--render-code-continuation is valid only for --resume-render')
        result = update(args.request, args.sha256, trial_words=args.trial_words or ())
    print(canonical(result), flush=True)


if __name__ == '__main__':
    main()
