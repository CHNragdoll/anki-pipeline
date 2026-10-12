"""Recover reviewed owner evidence from an immutable committed usage database.

The accepted base is never updated. A macOS APFS clone is mandatory (there is
no full-copy fallback); a single transaction appends only affected snapshots
and small, independently sealed delta ledgers. Original large parent payloads
remain references to the base run. Preparation and rendering are separate
operations so a page failure never destroys a certified working database.
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from copy import deepcopy
import ctypes
import errno
import hashlib
import json
import os
import re
import argparse
import shutil
from pathlib import Path
import sqlite3
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anki_pipeline import exam_frequency, exam_usage, ownership_history as history
from anki_pipeline import sense_frequency as sf
from anki_pipeline.exam_usage_policy import producer_record
from anki_pipeline import sense_display
from scripts import update_exam_usage_preview as preview
from urllib.parse import urlencode

SCHEMA = 'exam-usage-owner-data-patch.v1'
CHECKPOINT_SCHEMA = 'exam-usage-owner-patch-checkpoint.v1'
RENDER_CONTINUATION_SCHEMA = 'exam-usage-owner-render-continuation.v1'
DECISIONS_SCHEMA = 'exam-usage-owner-recovery-decisions.v1'
_DELTA_SQL = '''
CREATE TABLE exam_usage_owner_patch_runs (
 id TEXT PRIMARY KEY, parent_run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id),
 payload_sha256 TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE exam_usage_owner_patch_cards (
 run_id TEXT NOT NULL REFERENCES exam_usage_owner_patch_runs(id),
 book_id TEXT NOT NULL, card_id TEXT NOT NULL,
 parent_child_snapshot_id TEXT NOT NULL, child_snapshot_id TEXT NOT NULL,
 delta_sha256 TEXT NOT NULL, delta TEXT NOT NULL,
 PRIMARY KEY(run_id,book_id,card_id),
 FOREIGN KEY(parent_child_snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id),
 FOREIGN KEY(child_snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id));
CREATE TABLE exam_usage_owner_patch_outcomes (
 run_id TEXT NOT NULL REFERENCES exam_usage_owner_patch_runs(id),
 book_id TEXT NOT NULL, source_card_id TEXT NOT NULL, source_occurrence_id TEXT NOT NULL,
 target_card_id TEXT NOT NULL, target_occurrence_id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('bound','retained_unresolved')),
 history_id TEXT, decision_sha256 TEXT NOT NULL, decision TEXT NOT NULL,
 PRIMARY KEY(run_id,book_id,source_card_id,source_occurrence_id,target_card_id,target_occurrence_id));
CREATE TABLE exam_usage_owner_patch_documents (
 run_id TEXT NOT NULL REFERENCES exam_usage_owner_patch_runs(id), book_id TEXT NOT NULL,
 card_id TEXT NOT NULL, parent_snapshot_id TEXT NOT NULL, source_url TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, document_sha256 TEXT NOT NULL, original_html TEXT NOT NULL,
 PRIMARY KEY(run_id,book_id,card_id));
'''


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def clone_working_copy(source_pin, destination):
    """Clone accepted standalone SQLite bytes, never falling back to a copy."""
    source = preview.pin_file(source_pin)
    preview._assert_standalone_database(source)
    destination = Path(destination).resolve()
    if destination.exists() or any(Path(str(destination)+suffix).exists() for suffix in ('-wal','-journal','-shm')):
        raise FileExistsError(destination)
    _require(source != destination and destination.parent.is_dir(), 'APFS clone destination must be a new independent local file')
    _require(sys.platform == 'darwin', 'owner recovery requires macOS APFS clonefile; full-copy fallback is forbidden')
    before = preview._database_stat(source)
    libc = ctypes.CDLL(None, use_errno=True)
    clone = libc.clonefile
    clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clone.restype = ctypes.c_int
    if clone(os.fsencode(source), os.fsencode(destination), 0) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))
    identity = destination.stat().st_dev, destination.stat().st_ino
    try:
        _require(preview._database_stat(source) == before, 'accepted source changed during its APFS clone')
        _require(source.stat().st_ino != destination.stat().st_ino, 'working database shares the source inode')
        preview._assert_standalone_database(destination)
        _require(preview.file_sha(destination) == source_pin['sha256'], 'APFS cloned database differs from accepted complete source bytes')
    except BaseException:
        current = destination.stat()
        if (current.st_dev, current.st_ino) == identity:
            destination.unlink()
        raise
    return {'clone_method': 'apfs_clonefile', 'source': deepcopy(source_pin),
            'source_stat': before, 'destination': str(destination), 'destination_inode': identity[1]}


def _discard_uncertified_clone(database, inode):
    database = Path(database)
    if database.exists() and database.stat().st_ino == inode:
        for suffix in ('-journal', '-wal', '-shm', ''):
            Path(str(database)+suffix).unlink(missing_ok=True)


def validate_decision(record, decision, source_parent, source_ledger, target):
    """Validate the precise accepted source and destination before any write."""
    _require(isinstance(record, dict) and isinstance(decision, dict), 'owner decision and original input record are required')
    _require(decision.get('input_id') == preview.digest(record) and
             decision.get('source_record_sha256') == preview.digest(record['source_parent_row']),
             'owner recovery input/source full-record SHA differs')
    for key, value in [('book_id', source_parent['book_id']), ('source_card_id', source_parent['card_id']),
                       ('source_parent_snapshot_id', source_parent['snapshot_id']),
                       ('source_occurrence_id', record['source_parent_row']['occurrence_id'])]:
        _require(record.get(key) == decision.get(key) == value, 'owner recovery exact source binding differs: ' + key)
    source = next((r for r in source_parent['occurrences'] if r['occurrence_id'] == record['source_occurrence_id']), None)
    _require(source == record['source_parent_row'], 'owner recovery full old physical/meaning/source row differs')
    _require(record.get('source_word') == source_parent['word'] and
             record.get('source_parent_definition_snapshot_id', source_parent['definition_snapshot_id']) == source_parent['definition_snapshot_id'],
             'owner recovery source word/definition identity differs')
    _require(preview.digest(source_ledger) == record['scope_ledger_sha256'] and
             record['source_exclusion'] in source_ledger.get('excluded', []), 'owner recovery exclusion ledger differs')
    action = decision.get('action')
    _require(action in {'bind_existing', 'attach_existing', 'append_owner_row', 'retain_unresolved'}, 'unknown owner recovery action')
    _require(isinstance(decision.get('rationale'), str) and decision['rationale'].strip() and
             isinstance(decision.get('review_version'), str) and decision['review_version'].strip(), 'owner decision lacks its actual review rationale/version')
    if action == 'retain_unresolved':
        return
    _require(not exam_frequency.exclude_cloze_option(exam_usage.occurrence_sentence(source)), 'printed cloze option cannot become a counted owner occurrence')
    chosen = decision.get('target')
    _require(isinstance(chosen, dict) and target is not None, 'approved owner card is absent')
    for key, value in [('card_id', target['card_id']), ('word', target['word']),
                       ('parent_snapshot_id', target['snapshot_id']), ('definition_snapshot_id', target['definition_snapshot_id'])]:
        _require(chosen.get(key) == value, 'owner target current snapshot/definition differs: ' + key)
    _require(target['book_id'] == source_parent['book_id'], 'owner target is in a different edition')
    sense = _target_sense(target, chosen)
    dictionary = next((part.get('source_dictionary') for part in target['definition_provenance'].get(
        'supplemental_definitions', {}).get('appended', []) if part.get('ordinal') == sense['ordinal']), None) or target['definition_source']
    supplied_provenance = chosen.get('source_provenance')
    _require(chosen.get('dictionary_source') == dictionary and isinstance(supplied_provenance, dict)
             and supplied_provenance, 'owner target dictionary provenance differs')
    # The frozen families distinguish definition metadata from the copied
    # physical source provenance. The outer target IDs are always mandatory;
    # optional identity fields must agree, never grant their own authority.
    for key, value in [('snapshot_id', target['snapshot_id']), ('page_sha256', target['definition_provenance'].get('page_sha256')),
                       ('headword', target['definition_provenance'].get('headword'))]:
        if key in supplied_provenance:
            _require(supplied_provenance[key] == value, 'owner target supplied provenance differs: ' + key)
    if 'sourceHash' in supplied_provenance:
        _require(all(supplied_provenance.get(key) == value for key, value in source['source_provenance'].items()),
                 'owner target copied physical provenance differs from the complete original source')
    _require(isinstance(decision.get('dictionary_evidence'), dict) and decision['dictionary_evidence'] and
             isinstance(decision.get('physical_proof'), dict) and decision['physical_proof'], 'owner assignment lacks full dictionary/physical review evidence')
    start, end = chosen.get('target_range', [None, None])
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(source['english']), 'owner canonical lexical range is invalid')
    identity = preview.digest([source['paper_id'], source['physical_source'], [start, end]])
    _require(chosen.get('occurrence_id') == identity, 'owner canonical physical/range occurrence ID differs')
    _require(isinstance(chosen.get('reason'), str) and chosen['reason'].strip(), 'owner assignment lacks its actual sense reason')
    for span in chosen.get('translation_ranges', []):
        _require(isinstance(span, list) and len(span) == 2 and all(type(n) is int for n in span)
                 and 0 <= span[0] < span[1] <= len(source['translation']), 'owner original Chinese range is invalid')
    existing = next((r for r in target['occurrences'] if r['occurrence_id'] == identity), None)
    if action in {'bind_existing', 'attach_existing'}:
        _require(existing is not None and chosen.get('target_row') == existing and
                 existing['status'] == 'reviewed' and existing['sense_id'] == existing['reviewed_sense_id'] == sense['sense_id'] and
                 chosen['reason'] == existing['reason'] and chosen['target_range'] == existing['target_range'] and
                 chosen.get('translation_ranges') == existing['translation_ranges'],
                 'existing owner row/assignment/seals/reason are not exact')
        _require(all(existing.get(k) == source.get(k) for k in ('paper_id', 'physical_source', 'english', 'translation',
                 'english_hash', 'translation_hash')), 'existing owner belongs to another physical bilingual source')
    else:
        _require(existing is None and 'target_row' not in chosen, 'new owner row already exists or falsely claims an old assignment')


def _target_sense(target, chosen):
    sense = next((s for s in target['senses'] if s['sense_id'] == chosen.get('sense_id')), None)
    _require(sense is not None and all(chosen.get(k) == sense[k] for k in ('ordinal', 'pos', 'text')),
             'approved owner meaning/POS/ordinal differs from the actual dictionary sense')
    return sense


def add_approved_owner_rows(target, sources, *, reading_answers=None):
    """Return a prepared child; shared canonical physical owners count once."""
    record = producer_record(target, preserve_scope=False)
    existing = {r['occurrence_id']: r for r in target['occurrences']}
    pending = {}
    definition = sf._definition(record)
    for source, decision in sources:
        if decision['action'] != 'append_owner_row':
            continue
        chosen, original = decision['target'], source['source_parent_row']
        sense = _target_sense(target, chosen)
        identity = preview.digest([original['paper_id'], original['physical_source'], chosen['target_range']])
        _require(identity == chosen['occurrence_id'] and identity not in existing, 'new owner physical identity is stale or already counted')
        old = deepcopy(original)
        for field in ('sense_id', 'matching_proposal', 'ownership_history', 'ownership_history_unresolved',
                      'semantic_review', 'broad_match', 'common_sense_match', 'pending_category'):
            old.pop(field, None)
        old.update(target_range=deepcopy(chosen['target_range']), translation_ranges=deepcopy(chosen['translation_ranges']),
            status='reviewed', sense_index=sense['ordinal'], reason=chosen['reason'],
            method='owner-recovery.v5', review_version=decision['review_version'],
            reviewed_sense_id=None, assignment_context_hash=None)
        if original.get('display'):
            old['display'] = project_owner_display(original, old, target, decision)
        old['usage'] = exam_usage.occurrence_usage(old)
        if reading_answers is not None:
            from anki_pipeline.reading_usage_metadata import apply_question_metadata
            old['usage'] = apply_question_metadata(old, old['usage'], reading_answers)
        sealed = sf._occurrence(old, definition, require_binding=False)
        old['reviewed_sense_id'], old['assignment_context_hash'] = sealed['reviewed_sense_id'], sealed['assignment_context_hash']
        if identity in pending:
            _require(pending[identity]['sense_index'] == old['sense_index'] and
                     all(pending[identity].get(k) == old.get(k) for k in ('english', 'translation', 'physical_source',
                         'target_range', 'translation_ranges', 'source_provenance', 'alignment')),
                     'two approved sources disagree about one canonical owner occurrence')
            # Separate complete reviewed reasons remain in each incoming history.
            continue
        pending[identity] = old
    record['occurrences'].extend(pending.values())
    record['expected_occurrences'] = len(record['occurrences'])
    after = sf.prepare_record(record)
    _require(after['senses'] == target['senses'] and after['definition_provenance'] == target['definition_provenance'],
             'owner recovery changed original dictionary senses/provenance')
    rows = {r['occurrence_id']: r for r in after['occurrences']}
    _require(all(rows.get(r['occurrence_id']) == r for r in target['occurrences']), 'owner recovery changed an existing physical/meaning/history row')
    _require(after['expected_occurrences'] == target['expected_occurrences'] + len(pending), 'owner count delta is not the unique appended physical set')
    return after


def project_owner_display(original, owner_row, target, decision):
    """Rebind approved source maps explicitly, preserving old text and chunks."""
    original_view = sense_display.validate_display(original['display'], original)
    view = deepcopy(original_view)
    provenance = view['provenance']
    kind = provenance['derivation']
    if kind == 'original':
        _require(view['english'] == owner_row['english'] and view['translation'] == owner_row['translation'],
                 'transferred original display is not the actual bilingual source')
        mapped = owner_row['target_range']
    else:
        english, chinese, mapped, answers = sense_display._approved_derived_view(
            owner_row, view['derivation_payload'], kind)
        _require((english, chinese, answers) == (view['english'], view['translation'], view['cloze_answers']),
                 'transferred source maps do not independently replay the approved complete bilingual context')
    proof = decision['physical_proof'].get('display_phrase_proof')
    if proof is not None:
        _require(proof.get('english') == view['english'] and proof.get('english_hash') == view['english_hash'] and
                 proof.get('translation') == view['translation'] and proof.get('translation_hash') == view['translation_hash'] and
                 proof.get('canonical_full_target_range') == list(mapped), 'approved lexical display mapping differs from independent source replay')
    view['target_range'] = list(mapped)
    provenance.update(method='approved-source-maps', native_jump=None,
        source_card_sha256=target['definition_provenance']['page_sha256'],
        physical_target_range=deepcopy(owner_row['target_range']),
        raw_context_hash=sense_display._raw_context_hash(owner_row),
        owner_transfer_projection={'method': 'owner-transfer.v5',
            'input_id': decision['input_id'], 'source_record_sha256': decision['source_record_sha256'],
            'original_display_sha256': original_view['display_hash'],
            'original_source_provenance': deepcopy(original_view['provenance']),
            'target_definition_snapshot_id': target['definition_snapshot_id'],
            'target_definition_page_sha256': target['definition_provenance']['page_sha256'],
            'original_physical_target_range': deepcopy(original['target_range']),
            'canonical_owner_target_range': deepcopy(owner_row['target_range'])})
    view.pop('display_hash')
    view['display_hash'] = sf._sha(sf._json(view))
    checked = sense_display.validate_display(view, owner_row, target['definition_provenance'])
    _require(all(checked[k] == original_view[k] for k in ('english', 'translation', 'english_hash',
             'translation_hash', 'alignment', 'alignment_sources', 'cloze_answers', 'derivation_payload')),
             'owner display projection changed the original complete bilingual chunks/source maps')
    return checked


def resolve_prepared(db, base_run_id, patch_run_id, book_id, card_id):
    """Resolve only a small delta, retaining original parent bytes for inverse."""
    row = db.execute("SELECT COALESCE(NULLIF(p.parent_payload,''),old.payload),p.scope_ledger,"
        "s.payload,d.delta,d.parent_child_snapshot_id,d.child_snapshot_id "
        "FROM exam_usage_parent_snapshots p JOIN snapshots s ON s.id=p.child_snapshot_id "
        "LEFT JOIN snapshots old ON old.id=p.parent_snapshot_id "
        "LEFT JOIN exam_usage_owner_patch_cards d ON d.run_id=? AND d.book_id=p.book_id AND d.card_id=p.card_id "
        "WHERE p.run_id=? AND p.book_id=? AND p.card_id=?",
        (patch_run_id, base_run_id, book_id, card_id)).fetchone()
    if row is None:
        return None
    before, ledger, after = (json.loads(value) for value in row[:3])
    if row[3] is not None:
        delta = json.loads(row[3])
        _require(preview.digest(delta) == db.execute(
            'SELECT delta_sha256 FROM exam_usage_owner_patch_cards WHERE run_id=? AND book_id=? AND card_id=?',
            (patch_run_id, book_id, card_id)).fetchone()[0], 'owner patch delta SHA differs')
        _require(row[4] == after['snapshot_id'], 'owner patch parent differs from its immutable base child')
        saved = db.execute('SELECT payload FROM snapshots WHERE id=? AND book_id=? AND card_id=?',
            (row[5], book_id, card_id)).fetchone()
        _require(saved is not None, 'owner patch child payload is absent')
        after = json.loads(saved[0])
        _require(after.get('snapshot_id') == row[5] and preview.digest({k: v for k, v in after.items() if k != 'snapshot_id'}) == row[5],
                 'owner patch child payload differs')
        ledger['owner_recovery_patch'] = delta
        ledger['new_snapshot_id'] = after['snapshot_id']
    return before, ledger, after


def load_reviewed_decisions(pins):
    """Validate each family once, keeping candidate and approved data separate."""
    seen, rows, watched = set(), [], {}
    def verify(pin):
        path = str(Path(pin['file']).resolve())
        if path in watched:
            _require(watched[path] == pin['sha256'], 'owner recovery source has conflicting accepted pins')
            return Path(path)
        result = preview.pin_file(pin)
        watched[str(result)] = pin['sha256']
        return result
    for pin in pins:
        path = verify(pin)
        decisions = json.loads(path.read_text())
        _require(decisions.get('schema') == DECISIONS_SCHEMA and isinstance(decisions.get('decisions'), list),
                 'unknown owner recovery decisions schema')
        input_pin = decisions['input_pin']
        original = json.loads(verify(input_pin).read_text())
        records = {preview.digest(row): row for row in original['records']}
        _require(len(records) == len(original['records']), 'owner recovery family has duplicate source cases')
        actual = set()
        for evidence in decisions.get('evidence_pins', []):
            verify(evidence)
        for decision in decisions['decisions']:
            identity = decision.get('input_id')
            _require(identity in records and identity not in actual and identity not in seen,
                     'owner recovery approval duplicates or lacks its exact original source case')
            actual.add(identity); seen.add(identity)
            rows.append((records[identity], decision, {'decision_file': deepcopy(pin),
                'input_file': deepcopy(input_pin), 'input_bundle_sha256': decisions.get('input_bundle_sha256')}))
            for evidence in decision.get('evidence_pins', []):
                verify(evidence)
        _require(actual == set(records), 'owner recovery family does not have one explicit decision per source case')
        watched[str(path)] = pin['sha256']; watched[input_pin['file']] = input_pin['sha256']
    return rows, watched


def _source_parent(db, run_id, record):
    row = db.execute("SELECT COALESCE(NULLIF(p.parent_payload,''),s.payload),p.scope_ledger "
        "FROM exam_usage_parent_snapshots p LEFT JOIN snapshots s ON s.id=p.parent_snapshot_id "
        "WHERE p.run_id=? AND p.book_id=? AND p.card_id=?",
        (run_id, record['book_id'], record['source_card_id'])).fetchone()
    _require(row is not None, 'owner recovery source card is absent from the accepted base run')
    return tuple(json.loads(value) for value in row)


def _render_code_pins(request, continuation=None):
    if continuation is None:
        return request['code_pins']
    payload = continuation['payload']
    _require(json.loads(preview.pin_file(continuation['pin']).read_text()) == payload,
             'owner render continuation changed during execution')
    preview.pin_file(payload['request']); preview.pin_file(payload['prepared_checkpoint'])
    replacements = {}
    for change in payload['code_changes']:
        preview.pin_file(change['backup']); preview.pin_file(change['new'])
        replacements[change['old']['file']] = change['new']
    for proof in payload['proof_pins']:
        preview.pin_file(proof)
    return {key: replacements.get(value['file'], value)
            for key, value in request['code_pins'].items()}


def _load_render_continuation(pin, checkpoint_pin, checkpoint, request):
    payload = json.loads(preview.pin_file(pin).read_text())
    required = {'schema', 'scope', 'request', 'prepared_checkpoint', 'run_id',
                'database', 'original_code_pins', 'code_changes', 'proof_pins'}
    _require(set(payload) == required and payload.get('schema') == RENDER_CONTINUATION_SCHEMA
             and payload.get('scope') == 'native_existing_rows_projection_only'
             and payload['request'] == checkpoint['request']
             and payload['prepared_checkpoint'] == checkpoint_pin
             and payload['run_id'] == checkpoint['run_id']
             and payload['database'] == checkpoint['database']
             and payload['original_code_pins'] == checkpoint['code_pins'] == request['code_pins'],
             'owner render continuation differs from its sealed request/checkpoint/database/run')
    changes = payload['code_changes']
    allowed = {str(Path(__file__).resolve()), str(ROOT / 'anki_pipeline/native_example_usage.py')}
    _require(isinstance(changes, list) and 1 <= len(changes) <= 2
             and isinstance(payload['proof_pins'], list) and payload['proof_pins'],
             'owner render continuation requires bounded code changes and pinned review evidence')
    seen = set()
    for change in changes:
        _require(isinstance(change, dict) and set(change) == {'old', 'new', 'backup'},
                 'owner render continuation requires original/new bytes and complete backup')
        old, new, backup = (change[key] for key in ('old', 'new', 'backup'))
        _require(all(isinstance(value, dict) and set(value) == {'file', 'sha256'}
                     for value in (old, new, backup))
                 and old['file'] == new['file'] and old['file'] in allowed and old['file'] not in seen
                 and old['sha256'] != new['sha256'] and backup['sha256'] == old['sha256']
                 and Path(backup['file']).resolve() != Path(old['file']).resolve()
                 and sum(value == old for value in request['code_pins'].values()) == 1,
                 'owner render continuation may replace only the exact backed-up native renderer and driver')
        seen.add(old['file'])
    _require(str(Path(__file__).resolve()) in seen, 'owner render continuation must pin its actual driver')
    continuation = {'pin': deepcopy(pin), 'payload': payload}
    _render_code_pins(request, continuation)
    return continuation


def _render_continuation_evidence(request, continuation):
    if continuation is None:
        return {}
    return {'render_code_continuation': {
        'approval': continuation['pin'], 'code_changes': continuation['payload']['code_changes'],
        'prepared_checkpoint': continuation['payload']['prepared_checkpoint'],
        'proof_pins': continuation['payload']['proof_pins'],
        'original_code_pins': request['code_pins'],
        'actual_code_pins': _render_code_pins(request, continuation)}}


def _patch_inputs(request, base, original_request, extra_pins=(), *, render_continuation=None):
    preview.pin_file(request['base_checkpoint'])
    preview.pin_file(base['request'])
    for pin in _render_code_pins(request, render_continuation).values():
        preview.pin_file(pin)
    for pin in request['decisions']:
        preview.pin_file(pin)
    for pin in extra_pins:
        preview.pin_file(pin)
    if request.get('native_variant_addendum'):
        load_native_variant_addendum(request['native_variant_addendum'])
    # A new data-patch approval declares the actual full code inventory. The
    # old run remains historical; it is never silently re-signed as new code.
    effective = {**original_request, 'code_pins': _render_code_pins(request, render_continuation)}
    preview._execution_pins(effective, base.get('residual_context_pins', []))


def _load_request(path, checksum, *, render_continuation=None):
    path = preview.pin_file({'file': str(path), 'sha256': checksum})
    request = json.loads(path.read_text())
    _require(request.get('schema') == SCHEMA and request.get('scope') == 'v5-owner-recovery',
             'unknown owner recovery data-patch scope')
    _require(request.get('ready') is True and request.get('draft') is False,
             'owner recovery draft has not been explicitly accepted for execution')
    _require(tuple(request.get(k) for k in ('expected_source_cases','expected_added_occurrences','expected_bound_histories','expected_retained_unresolved','expected_affected_cards'))
             == (534,243,524,10,50), 'owner recovery differs from the fixed approved full case/count scope')
    base = json.loads(preview.pin_file(request['base_checkpoint']).read_text())
    _require(base.get('schema') == preview.CHECKPOINT_SCHEMA and base.get('integrity') == {
        'quick_check': 'ok', 'foreign_keys': 'ok', 'write_connections_closed': True}, 'base usage database is not certified')
    original_request = json.loads(preview.pin_file(base['request']).read_text())
    _require(request.get('parent_run_id') == base['run_id'] and request.get('source_database') == base['database'],
             'owner patch base run/database is not the accepted immutable checkpoint')
    preview._assert_standalone_database(base['database']['file'])
    _require(preview._database_stat(base['database']['file']) == base['database']['stat'], 'immutable owner-recovery base identity changed')
    expected_codes = {p['file']: p for p in base['code_pins'].values()}
    actual_codes = {p['file']: p for p in request['code_pins'].values()}
    changes = request.get('code_changes', [])
    declared = {}
    for change in changes:
        old, new, backup = change['old'], change['new'], change['backup']
        _require(old['file'] == new['file'] and expected_codes.get(old['file']) == old and
                 backup['sha256'] == old['sha256'] and Path(backup['file']).resolve() != Path(old['file']).resolve()
                 and old['sha256'] != new['sha256'] and old['file'] not in declared and change.get('review_pins'),
                 'owner patch has an unbound or duplicate original/new code delta')
        preview.pin_file(backup); declared[old['file']] = new
        for pin in change.get('review_pins', []):
            preview.pin_file(pin)
    for file, pin in expected_codes.items():
        _require(actual_codes.get(file) == declared.get(file, pin), 'owner patch code differs without its explicit accepted delta: ' + file)
    _require(set(actual_codes) - set(expected_codes) == {str(Path(__file__).resolve())},
             'owner patch may add only this bounded data-patch driver')
    _patch_inputs(request, base, original_request, render_continuation=render_continuation)
    return path, request, base, original_request


def _record_document(db, run_id, base_run_id, record, metadata, output, web_root):
    existing = db.execute('SELECT parent_snapshot_id,source_url,source_sha256,document_sha256,original_html '
        'FROM exam_usage_history_documents WHERE run_id=? AND book_id=? AND card_id=?',
        (base_run_id, record['book_id'], record['source_card_id'])).fetchone()
    if existing is None:
        from scripts.prepare_sense_frequency_records import class_aliases
        source = preview._local_url(metadata['previewUrl'], web_root)
        page = source.read_bytes().decode('utf-8')
        raw = ''.join(page[n['start']:n['end']] for n in preview._Spans(page, class_aliases(source.parent.parent)).nodes
                      if n['kind'] == 'diagnostic')
        document = preview._history_document(record['source_word'], record['source_parent_snapshot_id'], metadata['previewUrl'], raw)
        existing = (record['source_parent_snapshot_id'], metadata['previewUrl'], preview.file_sha(source),
                    sf._sha(document), raw)
        db.execute('INSERT OR IGNORE INTO exam_usage_owner_patch_documents VALUES(?,?,?,?,?,?,?,?)',
                   (run_id, record['book_id'], record['source_card_id'], *existing))
    _require(existing[0] == record['source_parent_snapshot_id'], 'complete source historical document has another parent')
    filename = output / 'history' / (record['source_card_id'] + '.html')
    return {'file': str(filename), 'url': '/' + str(filename.relative_to(web_root)), 'sha256': existing[3]}


def _transfer(record, decision, semantic, document):
    chosen = decision['target']; source = record['source_parent_row']
    destination = next(row for row in semantic['occurrences'] if row['occurrence_id'] == chosen['occurrence_id'])
    sense = next(s for s in semantic['senses'] if s['sense_id'] == destination['sense_id'])
    definition = semantic['definition_provenance']
    supplied = {**sense, 'dictionary_source': chosen['dictionary_source'],
        'source_provenance': {'snapshot_id': semantic['snapshot_id'], 'definition_source': semantic['definition_source'],
            'definition_headword': definition.get('headword'), 'page_sha256': definition.get('page_sha256'),
            'components': [deepcopy(c) for c in definition.get('components', [])
                if c['sense_start'] <= sense['ordinal'] < c['sense_start'] + c['sense_count']]}}
    a, b = destination['target_range']; x, y = source['target_range']
    kind = 'exact_span' if [a, b] == [x, y] else 'fixed_phrase_contains_exact_component_span'
    return {'book_id': record['book_id'], 'source_card_id': record['source_card_id'], 'source_word': record['source_word'],
        'source_parent_snapshot_id': record['source_parent_snapshot_id'], 'source_parent_row': deepcopy(source),
        'source_parent_definition_id': record.get('source_parent_definition_snapshot_id'),
        'exclusion_authority': deepcopy(record['source_exclusion'].get('prior_exclusion') or record['source_exclusion']),
        'source_identity': {k: deepcopy(source[k]) for k in history._IDENTITY_FIELDS},
        'target_card_id': chosen['card_id'], 'target_occurrence_id': chosen['occurrence_id'],
        'target_parent_row': deepcopy(destination), 'target_parent_snapshot_id': semantic['snapshot_id'],
        'target_range': deepcopy(chosen['target_range']), 'target_reason': destination['reason'],
        'matched_sense': supplied, 'verified_physical_match': True, 'match_kind': kind,
        'source_history_ref': document,
        'owner_recovery_decision': deepcopy(decision),
        'original_target_definition_snapshot_id': chosen['definition_snapshot_id'],
        'original_target_snapshot_id': chosen['parent_snapshot_id']}


def _reference(ref):
    """Read only the pinned native fragment, retaining its actual source bytes."""
    path = preview.pin_file({'file': ref['file'], 'sha256': ref['sha256']})
    value = json.loads(path.read_text())
    for part in ref.get('json_pointer', '').split('/')[1:]:
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    if ref.get('content_sha256'):
        _require(isinstance(value, str) and sf._sha(value) == ref['content_sha256'], 'native fragment bytes differ')
    return value


def _native_markup(value):
    if isinstance(value, dict):
        return '\n'.join(str(v) if k in {'html', 'header_html', 'native_header_html'} and isinstance(v, str)
                         else _native_markup(v) for k, v in value.items())
    if isinstance(value, list):
        return '\n'.join(_native_markup(v) for v in value)
    return ''


def _verified_native_entry(source, definition):
    """Re-read the selected exact local entry, not an authored markup claim."""
    _require(isinstance(source, dict) and isinstance(definition, dict), 'native lexical bridge entry/definition is absent')
    path = Path(source['db_path']).resolve()
    with closing(preview._ro(path)) as db:
        saved = db.execute('SELECT headword,html,sha256 FROM entries WHERE id=?', (source['source_entry_id'],)).fetchone()
    raw = source.get('raw_html')
    _require(saved is not None and saved[0] == source['headword'] and saved[1] == raw
             and saved[2] == source['raw_sha256'] == sf._sha(raw), 'native lexical bridge original entry bytes/headword differ')
    ref = definition.get('source_ref') or {}
    _require(ref.get('source_entry_id') == source['source_entry_id'] and ref.get('raw_sha256') == source['raw_sha256']
             and ref.get('source_headword') == definition.get('source_headword') and ref.get('part_of_speech') == definition.get('part_of_speech')
             and isinstance(definition.get('header_html'),str) and definition['header_html'] in raw
             and isinstance(definition.get('html'),str) and definition['html'] in raw
             and sf._sha(definition['html']) == ref.get('definition_html_sha256'),
             'native lexical bridge exact definition/header/POS/source-ref differs')
    return definition['header_html'], definition['html']


def load_native_variant_addendum(pin):
    """Verify two finite auxiliary spellings against exact indexed raw bytes."""
    value = json.loads(preview.pin_file(pin).read_text())
    _require(value.get('schema') == 'exam-usage-native-variant-addendum.v1', 'unknown native variant addendum')
    approved = json.loads(preview.pin_file(value['frozen_primary_decisions_pin']).read_text())
    decisions = {d['input_id']: d for d in approved['decisions']}
    _require(len(value['affected_decisions']) == 4, 'native variant authorization exceeds its four frozen decisions')
    aliases = {}
    for item in value['aliases']:
        pair = item['canonical_headword'], item['printed_variant']
        _require(pair in {('offline','off-line'),('sightseeing','sight-seeing')} and pair not in aliases,
                 'native variant addendum exceeds the two approved exact spellings')
        source = item['source']
        with closing(preview._ro(Path(source['db_path']))) as db:
            actual = db.execute('SELECT headword,html,sha256,redirect_target FROM entries WHERE id=?', (source['source_entry_id'],)).fetchone()
            _require(actual == (source['headword'],source['raw_html'],source['raw_sha256'],source['redirect_target'])
                     and sf._sha(actual[1]) == actual[2] == item['rawfile']['sha256'], 'native auxiliary entry identity/raw bytes differ')
            if pair[0] == 'sightseeing':
                _require(item['kind'] == 'native_redirect' and source['headword'] == pair[1]
                         and actual[1] == '@@@LINK=sightseeing\r\n' and actual[3] == pair[0], 'sight-seeing requires the exact original OALD redirect')
                target = item['target_source']
                saved = db.execute('SELECT headword,html,sha256 FROM entries WHERE id=?',(item['target_entry_id'],)).fetchone()
                _require(saved == (pair[0],target['raw_html'],item['target_raw_sha256'])
                         and target['source_entry_id'] == item['target_entry_id'] and sf._sha(saved[1]) == saved[2]
                         == item['target_rawfile']['sha256'], 'native redirect does not reach the exact approved canonical noun entry')
            else:
                header,_ = _verified_native_entry(source,item['native_definition'])
                start, stop = item['header_byte_range']
                _require(item['kind']=='native_header' and source['headword']==pair[0]
                         and source['raw_html'].encode()[start:stop] == item['header_html'].encode()
                         and header == item['header_html'] and sf._sha(header)==item['header_sha256']
                         and item['native_definition']['part_of_speech']=='adjective, adverb'
                         and item['native_definition']['source_ref']==item['native_source_ref']
                         and item['native_definition']['sense_ref']==item['native_sense_ref']
                         and 'off-line' in header and 'also' in header, 'off-line requires the exact CALD4 native header spelling permission')
        for file, checksum in item.get('parser_pins', {}).items(): preview.pin_file({'file':file,'sha256':checksum})
        aliases[pair] = {**item, 'affected_decisions': value['affected_decisions'], 'frozen_decisions': decisions}
    _require(set(aliases)=={('offline','off-line'),('sightseeing','sight-seeing')}, 'native auxiliary spelling coverage differs')
    return aliases


def _licensed_span(prepared, source, destination, decision, *, source_word=None, variant_pin=None):
    a, b = destination['target_range']; x, y = source['target_range']
    _require(a <= x < y <= b and destination['english_hash'] == source['english_hash'] and
             destination['english'] == source['english'] and destination['translation'] == source['translation'],
             'licensed owner lexical expansion must contain the same exact original bilingual component')
    surface, word = source['english'][a:b], prepared['word'].casefold()
    evidence = decision['dictionary_evidence']
    if word == 'will':
        _require(isinstance(source_word, str) and source_word.casefold() == 'win' and surface.casefold() in {"won't", 'won’t'} and source['english'][x:y].casefold() == 'won'
                 and [x, y] == [a, a + 3] and b == a + 5,
                 'will recovery permits only the complete approved negative contraction, not past-tense won')
        native = _reference(evidence['negative_contraction_proof_ref'])
        raw = _reference(evidence['native_raw_entry_ref'])
        _require(native == evidence['negative_contraction_evidence'] and native.get('source_headword') == 'will'
                 and native.get('part_of_speech') == 'modal verb' and native.get('context_id') == 'will_3'
                 and prepared['senses'][decision['target']['ordinal']]['pos'] == 'modal v.'
                 and native.get('source_entry') == evidence['source_entry']
                 and evidence['source_entry'].get('provider') == 'oxford' and evidence['source_entry'].get('archive_source')=='oald10'
                 and sf._sha(raw) == evidence['source_entry']['raw_sha256'],
                 'negative contraction does not belong to the actual native will modal entry')
        start, stop = native['forms_source_range']
        _require(raw[start:stop] == native['forms_native_html'] and
                 sf._sha(native['forms_native_html']) == native['forms_native_html_sha256'], 'negative verb-form table bytes/range differ')
        matches = []
        for form in native['forms']:
            if (form.get('kind'), form.get('text')) in {('neg', 'will not'), ('short', "won't")}:
                start, stop = form['source_range']
                _require(raw[start:stop] == form['native_html'] and sf._sha(form['native_html']) == form['native_html_sha256'],
                         'negative form native row bytes differ')
                matches.append((form['kind'], form['text']))
        _require(set(matches) == {('neg', 'will not'), ('short', "won't")}, 'native negative and contraction rows are both required')
        return 'licensed_will_negative_contraction'
    licensed = {('layoff', 'lay-off'), ('offline', 'off-line'), ('sightseeing', 'sight-seeing'),
                ('number', 'no.'), ('high', 'hi-tech')}
    _require((word, surface.casefold()) in licensed, 'owner span differs without an explicitly reviewed native variant')
    # These finite, individually reviewed forms are not a generic hyphen or
    # abbreviation normalizer. Both the exact printed form and canonical
    # native identity must exist in the approved immutable dictionary evidence.
    header, block = _verified_native_entry(evidence['native_source'], evidence['native_definition'])
    if word == 'layoff':
        bridge = evidence.get('explicit_variant_bridge') or {}
        _require(bridge.get('canonical_headword') == word and bridge.get('printed_variant') == surface
                 and bridge.get('native_header_html') == header and bridge.get('source_ref') == evidence['native_definition']['source_ref']
                 and bridge.get('part_of_speech') == 'noun' and surface in header,
                 'layoff requires the actual noun header explicitly licensing lay-off')
    elif word in {'number', 'high'}:
        valid = False
        for bridge in evidence.get('native_equivalence_bridges', []):
            for native in bridge['definitions']:
                h, text = _verified_native_entry(bridge['source'], native)
                if word == 'number' and native['source_headword'] == 'No.' and native['part_of_speech'] == 'abbreviation':
                    valid |= native['english'] == 'number' and 'No.' in h
                if word == 'high' and native['source_headword'] in {'hi-tech','high-tech'} and native['part_of_speech'] == 'adjective':
                    valid |= 'hi-tech' in h and 'high-tech' in h
        _require(valid, 'native exact abbreviation/compound header does not license the approved owner')
    else:
        _require(variant_pin is not None, 'native exact header requires its separately approved hyphen variant addendum')
        auxiliary = load_native_variant_addendum(variant_pin)[(word,surface.casefold())]
        _require(auxiliary['frozen_decisions'].get(decision['input_id']) == decision,
                 'native auxiliary variant is not the exact approved original decision')
        scope = next((s for s in auxiliary['affected_decisions'] if s['input_id']==decision['input_id']), None)
        chosen = decision['target']; native = evidence['native_definition']
        _require(scope is not None and scope['book_id']==decision['book_id'] and scope['canonical_headword']==word
                 and scope['printed_variant']==surface.casefold() and scope['target_card_id']==chosen['card_id']
                 and scope['target_occurrence_id']==chosen['occurrence_id'] and scope['target_range']==chosen['target_range']
                 and all(scope['actual_target_sense'][k]==chosen[k] for k in ('sense_id','ordinal','pos','text'))
                 and scope['primary_dictionary_sense_ref']==native['sense_ref']
                 and scope['primary_dictionary_source_ref']==native['source_ref'],
                 'native auxiliary spelling authorization differs from its actual frozen primary row/sense/ref')
        if word=='sightseeing':
            _require(auxiliary['target_entry_id']==evidence['native_source']['source_entry_id']
                     and auxiliary['target_raw_sha256']==evidence['native_source']['raw_sha256'], 'native alias reaches another primary dictionary entry')
        _require(evidence['native_definition']['part_of_speech']==('noun' if word=='sightseeing' else 'adjective'),
                 'auxiliary spelling must not replace the actual Oxford primary POS')
    return 'licensed_native_owner_variant'


def bind_recovery_histories(prepared, transfers, *, variant_pin=None):
    """Keep the normal binder strict; validate finite approved expanded forms."""
    result = deepcopy(prepared)
    for transfer in transfers:
        source = transfer['source_parent_row']
        row = next(r for r in result['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id'])
        exact_or_phrase = (row['target_range'] == source['target_range'] or
            row['english'][slice(*row['target_range'])].casefold() == result['word'].casefold())
        if result['word'].casefold() == 'will' and transfer['source_word'].casefold() == 'win':
            exact_or_phrase = False
        if exact_or_phrase:
            result = history.bind_incoming_history(result, [transfer])
            continue
        history._validate_row(row); history._validate_row(source)
        _require(transfer['book_id'] == result['book_id'] and transfer['target_card_id'] == result['card_id']
                 and transfer['source_card_id'] != result['card_id'] and transfer['verified_physical_match'] is True,
                 'licensed transfer exact source/destination identity differs')
        _require(row['status'] == 'reviewed' and row['sense_id'] == row['reviewed_sense_id']
                 and not exam_frequency.exclude_cloze_option(exam_usage.occurrence_sentence(row)),
                 'licensed owner is not a reviewed countable physical occurrence')
        _require(all(transfer['source_identity'].get(k) == source[k] for k in history._IDENTITY_FIELDS)
                 and history._physical_equal(source, row) and source['translation_hash'] == row['translation_hash']
                 and transfer['target_range'] == row['target_range']
                 and source['source_provenance'].get('sourceHash') == row['source_provenance'].get('sourceHash'),
                 'licensed transfer physical/original paragraph/Chinese/target binding differs')
        kind = _licensed_span(result, source, row, transfer['owner_recovery_decision'], source_word=transfer['source_word'], variant_pin=variant_pin)
        history._validate_authority(transfer, source)
        matched = history._matched_sense(result, row, transfer)
        document = transfer['source_history_ref']
        _require(isinstance(document.get('file'), str) and re.fullmatch('[0-9a-f]{64}', document.get('sha256', '')),
                 'licensed source original history document is not pinned')
        value = deepcopy(transfer)
        value.update(schema=history.SCHEMA, target_word=result['word'], matched_sense=matched, match_kind=kind)
        value['history_id'] = sf._sha(sf._json([transfer['book_id'], transfer['source_card_id'],
            transfer['source_parent_snapshot_id'], source, transfer['exclusion_authority'],
            transfer['target_card_id'], transfer['target_occurrence_id']]))
        value['content_sha256'] = history._content_sha256(value)
        history.validate_history_content(value)
        values = row.setdefault('ownership_history', [])
        if not any(h['history_id'] == value['history_id'] for h in values): values.append(value)
    return result


def prepare_patch(request_path, checksum):
    """Make one private COW clone and append only the reviewed affected cards."""
    started = time.monotonic()
    path, request, base, original_request = _load_request(request_path, checksum)
    cases, watched = load_reviewed_decisions(request['decisions'])
    _require(len(cases) == request['expected_source_cases'], 'owner recovery full decision coverage differs')
    pin = {'file': str(path), 'sha256': checksum}
    database = Path(request['new_database']).resolve()
    _require(not database.exists() and not Path(str(database) + '.prepared.json').exists(), 'owner patch destination or checkpoint already exists')
    web_root = Path(original_request['web_root'])
    books = [(book, preview.load_catalog(book, web_root)) for book in original_request['books']]
    outputs = {b['book_id']: Path(b['output']) for b, _ in books}
    _require(all(not output.exists() for output in outputs.values()), 'original unpublished recovery output appeared')
    metadata = {(b['book_id'], c['id']): c for b, (_, _, _, catalog) in books for c in catalog['cards']}
    reading_answers = None
    if original_request.get('reading_answers'):
        from anki_pipeline.reading_usage_metadata import build_question_metadata_index
        reading_answers = build_question_metadata_index(json.loads(preview.pin_file(original_request['reading_answers']).read_text()))
    targets = defaultdict(list)
    with closing(preview._ro(Path(base['database']['file']))) as old:
        run = old.execute('SELECT payload_sha256,payload FROM exam_usage_update_runs WHERE id=?', (base['run_id'],)).fetchone()
        _require(run == (preview.digest(base['run']), preview.canonical(base['run'])), 'base database run payload changed')
        for record, decision, origin in cases:
            source, ledger = _source_parent(old, base['run_id'], record)
            chosen = decision.get('target') or {}
            target = preview._active_prepared(old, record['book_id'], chosen.get('card_id')) if chosen else None
            validate_decision(record, decision, source, ledger, target)
            if decision['action'] != 'retain_unresolved':
                targets[(record['book_id'], chosen['card_id'])].append((record, decision, origin))
    clone = None; certified = False; owned_checkpoint = None
    _require(len(targets) == request['expected_affected_cards'], 'owner recovery approved affected-card coverage differs')
    checkpoint_path = Path(str(database) + '.prepared.json')
    run_payload = {'schema': SCHEMA, 'scope': request['scope'], 'request': pin,
                   'base_checkpoint': request['base_checkpoint'], 'parent_run_id': base['run_id'],
                   'source_cases': len(cases), 'decisions': request['decisions'], 'code_pins': request['code_pins']}
    run_id = preview.digest(run_payload)
    try:
        clone = clone_working_copy({'file': base['database']['file'], 'sha256': base['database']['sha256']}, database)
        with closing(sqlite3.connect(database)) as db:
            db.execute('PRAGMA foreign_keys=ON'); db.execute('BEGIN IMMEDIATE')
            try:
                for statement in _DELTA_SQL.split(';'):
                    if statement.strip(): db.execute(statement)
                db.execute('INSERT INTO exam_usage_owner_patch_runs VALUES(?,?,?,?)',
                           (run_id, base['run_id'], preview.digest(run_payload), preview.canonical(run_payload)))
                added = bound = 0
                for (book, card), items in sorted(targets.items()):
                    current = preview._active_prepared(db, book, card)
                    semantic = add_approved_owner_rows(current, [(r, d) for r, d, _ in items], reading_answers=reading_answers)
                    # The recorded semantic parent is a real immutable snapshot,
                    # not merely an in-memory ID claimed by the history binding.
                    preview.insert_prepared(db, semantic)
                    transfers = []
                    for record, decision, _ in items:
                        document = _record_document(db, run_id, base['run_id'], record,
                            metadata[(book, record['source_card_id'])], outputs[book], web_root)
                        transfers.append(_transfer(record, decision, semantic, document))
                    overlay = bind_recovery_histories(semantic, transfers, variant_pin=request.get('native_variant_addendum'))
                    ids = {h['history_id'] for r in overlay['occurrences'] for h in r.get('ownership_history', [])}
                    expected = {sf._sha(sf._json([t['book_id'], t['source_card_id'], t['source_parent_snapshot_id'],
                        t['source_parent_row'], t['exclusion_authority'], t['target_card_id'], t['target_occurrence_id']])) for t in transfers}
                    _require(expected <= ids, 'approved recovery history failed its strict physical/meaning/source binding')
                    final = sf.prepare_record(producer_record(overlay, preserve_scope=False))
                    preview.insert_prepared(db, final)
                    delta = {'schema': SCHEMA, 'parent_snapshot_id': current['snapshot_id'],
                        'child_snapshot_id': final['snapshot_id'], 'semantic_snapshot_id': semantic['snapshot_id'],
                        'new_occurrence_ids': sorted({r['occurrence_id'] for r in final['occurrences']} - {r['occurrence_id'] for r in current['occurrences']}),
                        'count_before': current['expected_occurrences'], 'count_after': final['expected_occurrences'],
                        'decisions': [d for _, d, _ in items], 'origins': [o for _, _, o in items]}
                    db.execute('INSERT INTO exam_usage_owner_patch_cards VALUES(?,?,?,?,?,?,?)',
                        (run_id, book, card, current['snapshot_id'], final['snapshot_id'], preview.digest(delta), preview.canonical(delta)))
                    for transfer, (_, decision, _) in zip(transfers, items):
                        hid = sf._sha(sf._json([transfer['book_id'], transfer['source_card_id'], transfer['source_parent_snapshot_id'],
                            transfer['source_parent_row'], transfer['exclusion_authority'], transfer['target_card_id'], transfer['target_occurrence_id']]))
                        db.execute('INSERT INTO exam_usage_owner_patch_outcomes VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (run_id, book, transfer['source_card_id'], transfer['source_parent_row']['occurrence_id'],
                             card, transfer['target_occurrence_id'], 'bound', hid, preview.digest(decision), preview.canonical(decision)))
                        bound += 1
                    added += len(delta['new_occurrence_ids'])
                    print(preview.canonical({'stage': 'owner_patch_card', 'book_id': book, 'card_id': card,
                        'new_occurrences': len(delta['new_occurrence_ids']), 'histories': len(transfers)}), file=sys.stderr, flush=True)
                for record, decision, _ in cases:
                    if decision['action'] == 'retain_unresolved':
                        db.execute('INSERT INTO exam_usage_owner_patch_outcomes VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (run_id, record['book_id'], record['source_card_id'], record['source_occurrence_id'],
                             '', '', 'retained_unresolved', None, preview.digest(decision), preview.canonical(decision)))
                _require(added == request['expected_added_occurrences'] and bound == request['expected_bound_histories']
                         and sum(d['action'] == 'retain_unresolved' for _, d, _ in cases) == request['expected_retained_unresolved'],
                         'owner recovery approved unique count/history/retained totals differ')
                _require(not db.execute('PRAGMA foreign_key_check').fetchone(), 'owner patch foreign keys differ')
                db.commit()
            except BaseException:
                db.rollback(); raise
            _require(db.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete', 'owner patch is not standalone DELETE SQLite')
            preview._check_private_integrity(db)
        _patch_inputs(request, base, original_request, [{'file': f, 'sha256': h} for f, h in watched.items()])
        _require(preview._database_stat(base['database']['file']) == base['database']['stat'], 'accepted base changed during its owner patch')
        checkpoint = {'schema': CHECKPOINT_SCHEMA, 'request': pin, 'run_id': run_id, 'run': run_payload,
            'parent_run_id': base['run_id'], 'base_checkpoint': request['base_checkpoint'],
            'database': preview._checked_database_hash(database), 'code_pins': request['code_pins'],
            'integrity': {'foreign_keys': 'ok', 'quick_check': 'ok', 'write_connections_closed': True},
            'word_cards': base['word_cards'], 'affected_cards': len(targets), 'bound_histories': bound,
            'added_occurrences': added, 'retained_unresolved': sum(d['action'] == 'retain_unresolved' for _, d, _ in cases),
            'watched_pins': [{'file': f, 'sha256': h} for f, h in watched.items()],
            'clone_proof': clone, 'elapsed_seconds': round(time.monotonic() - started, 3)}
        owned_checkpoint = preview._write_prepared_checkpoint(checkpoint_path, checkpoint)
        checkpoint_pin = {'file': str(checkpoint_path), 'sha256': preview.file_sha(checkpoint_path)}
        certified = True
        print(preview.canonical({'stage': 'owner_patch_checkpoint_saved', 'run_id': run_id,
            'checkpoint': checkpoint_pin, 'affected_cards': len(targets), 'added_occurrences': added}), file=sys.stderr, flush=True)
        return checkpoint_pin
    except BaseException:
        if clone is not None and not certified:
            if owned_checkpoint is not None: preview._unlink_owned_checkpoint(checkpoint_path, owned_checkpoint)
            _discard_uncertified_clone(database, clone['destination_inode'])
        raise


def _history_documents(db, base_run, patch_run, data):
    documents = {}
    for row in data['occurrences']:
        for h in row.get('ownership_history', []):
            ref = h['source_history_ref']
            if ref['file'] in documents: continue
            saved = db.execute('SELECT parent_snapshot_id,source_url,document_sha256,original_html '
                'FROM exam_usage_history_documents WHERE run_id=? AND book_id=? AND card_id=?',
                (base_run, h['book_id'], h['source_card_id'])).fetchone()
            if saved is None:
                saved = db.execute('SELECT parent_snapshot_id,source_url,document_sha256,original_html '
                    'FROM exam_usage_owner_patch_documents WHERE run_id=? AND book_id=? AND card_id=?',
                    (patch_run, h['book_id'], h['source_card_id'])).fetchone()
            _require(saved is not None and saved[0] == h['source_parent_snapshot_id'] and saved[2] == ref['sha256'],
                     'recovered history has no exact immutable original source document')
            full = preview._history_document(h['source_word'], saved[0], saved[1], saved[3])
            _require(sf._sha(full) == ref['sha256'], 'recovered full historical document bytes differ')
            documents[ref['file']] = {'reference': deepcopy(ref), 'document_html': full,
                'original_html': saved[3], 'original_html_sha256': sf._sha(saved[3]), 'inline_history_ids': [h['history_id']]}
    return documents


def _effective_outcomes(db, base_run, patch_run, book, card):
    rows = {(r[0], r[1], r[2]): (r[3], r[4]) for r in db.execute(
        'SELECT source_occurrence_id,target_card_id,target_occurrence_id,status,reason '
        'FROM exam_usage_transfer_outcomes WHERE run_id=? AND book_id=? AND source_card_id=?', (base_run, book, card))}
    for oid, target, target_oid, status, raw in db.execute(
            'SELECT source_occurrence_id,target_card_id,target_occurrence_id,status,decision '
            'FROM exam_usage_owner_patch_outcomes WHERE run_id=? AND book_id=? AND source_card_id=?', (patch_run, book, card)):
        decision = json.loads(raw)
        rows[(oid, target, target_oid)] = status, decision.get('rationale', '')
    bound = {key for key, (state, _) in rows.items() if state == 'bound'}
    failures = {key[0]: reason for key, (state, reason) in rows.items() if state != 'bound' and not any(k[0] == key[0] for k in bound)}
    return bound, failures


def original_paper_jump(physical, raw_range, base_url):
    from urllib.parse import urlsplit
    from anki_pipeline.packaging import _source_jump
    origin = urlsplit(base_url)
    _require(origin.scheme in {'http', 'https'} and origin.netloc and not origin.username and not origin.password
             and not origin.query and not origin.fragment, 'original-paper configured origin is unsafe')
    start, stop = raw_range
    _require(0 <= start < stop <= len(physical['english']) and physical['english_hash'] == sf._sha(physical['english']),
             'original-paper raw English/range pin differs')
    review = physical['source_provenance'].get('reviewedContentHash')
    _require(isinstance(review, str) and re.fullmatch('[0-9a-f]{64}', review), 'original-paper reviewed sentence pin is absent')
    params = {'anki-codex-sentence': physical['sentence_id'], 'anki-codex-hash': physical['english_hash'],
        'anki-codex-review': review, 'anki-codex-en': json.dumps([raw_range], separators=(',', ':'))}
    root = base_url.rstrip('/'); stem = physical['paper_id'].split(':')[1]
    result = {'reader': 'full-paper',
        'latex_url': root + '/english-exams-reflow-latex/kaoyan/papers/' + stem + '.htm?' + urlencode(params),
        'full_paper_url': root + '/exam-library/practice/full-paper.htm?' + urlencode({'paper': physical['paper_id'], **params})}
    _require(_source_jump(result), 'original-paper safe jump could not be generated')
    return result


def _source_jumps(data, base_url):
    result = {}
    for row in data['occurrences']:
        if not row.get('ownership_history'): continue
        candidates = []
        for h in row['ownership_history']:
            original = h['source_parent_row']
            decision = h.get('owner_recovery_decision')
            raw_range = row['target_range']
            if decision:
                proof = decision['physical_proof']
                raw_range = proof.get('canonical_full_target_range', decision['target']['target_range'])
                _require(decision['target']['occurrence_id'] == row['occurrence_id'] and decision['target']['target_range'] == row['target_range'],
                         'owner original-paper jump differs from its actual reviewed physical row')
                if 'canonical_full_target_range' in proof:
                    _require(all(proof.get(k) == original[k] for k in ('english','english_hash','paper_id','physical_source')),
                             'original-paper canonical range is not bound to the frozen raw source')
                if raw_range != row['target_range']:
                    a, b = raw_range; x, y = row['target_range']
                    _require(decision['action'] in {'bind_existing','attach_existing'} and data['word'].casefold() == 'according'
                             and a <= x < y <= b and original['english'][a:b].casefold() == 'according to'
                             and decision['dictionary_evidence'].get('scope_proof'),
                             'original-paper extended range lacks the exact reviewed according-to alias proof')
            candidates.append(original_paper_jump(original, raw_range, base_url))
        _require(all(item == candidates[0] for item in candidates), 'merged owner histories disagree about their actual raw-paper jump')
        result[row['occurrence_id']] = candidates[0]
    return result


def _native_owner_projection(before, after, documents, target_urls):
    """Keep the native updater's retained-row contract; new owners live in SF.

    The complete certified snapshot is never changed. A separately sealed
    presentation projection contains only identities the source card had.
    Every omitted identity must have a complete validated owner history.
    """
    old_ids = {row['occurrence_id'] for row in before['occurrences']}
    new_ids = {row['occurrence_id'] for row in after['occurrences']}
    if not (new_ids - old_ids):
        return after, None
    from anki_pipeline.native_example_usage import _rows, _native_histories
    old_rows, new_rows = _rows(before), _rows(after)
    _, full_pins = _native_histories(after, new_rows, documents=documents, target_urls=target_urls)
    _require(new_ids - old_ids <= set(full_pins),
             'new native-absent owner lacks its complete validated sentence history')
    projection = deepcopy(after)
    projection['occurrences'] = [row for row in projection['occurrences'] if row['occurrence_id'] in old_rows]
    projection['expected_occurrences'] = len(projection['occurrences'])
    projection.pop('snapshot_id')
    projection['snapshot_id'] = preview.digest(projection)
    return projection, full_pins


def _complete_native_owner_coverage(native, after, full_history_pins):
    """Bind native and SF-only histories to the real complete snapshot."""
    if full_history_pins is None:
        return native.get('ownership_coverage')
    original = native.get('ownership_coverage')
    if original is not None:
        unsigned = deepcopy(original); claimed = unsigned.pop('coverage_sha256', None)
        _require(claimed == preview.digest(unsigned), 'native owner projection coverage seal differs')
        inventory = {**original['native'], **original['deferred']}
        _require(not (set(original['native']) & set(original['deferred']))
                 and all(full_history_pins.get(key) == pins for key, pins in inventory.items())
                 and set(original['native_examples']) == set(original['native']),
                 'native owner projection has foreign or incomplete histories')
        coverage = deepcopy(original)
    else:
        coverage = {'schema': 'ownership-native-coverage.v1', 'book_id': after['book_id'],
                    'card_id': after['card_id'], 'native': {}, 'deferred': {}, 'native_examples': {}}
    _require(coverage['book_id'] == after['book_id'] and coverage['card_id'] == after['card_id'],
             'native owner projection coverage belongs to another card')
    coverage['snapshot_id'] = after['snapshot_id']
    coverage['deferred'] = {identity: pins for identity, pins in full_history_pins.items()
                            if identity not in coverage['native']}
    coverage.pop('coverage_sha256', None)
    coverage['coverage_sha256'] = preview.digest(coverage)
    return coverage


def _render_one(db, base, checkpoint, card, book, output, web_root, aliases, source_aliases, target_urls, request, *, payload):
    from anki_pipeline.native_example_usage import update_native_examples, restore_original
    before, ledger, after = payload
    source = preview._local_url(card['previewUrl'], web_root); page = source.read_bytes().decode('utf-8')
    documents = _history_documents(db, base['run_id'], checkpoint['run_id'], after)
    if documents and request.get('native_variant_addendum'):
        documents['__owner_recovery_native_variant_addendum__'] = deepcopy(request['native_variant_addendum'])
    native_after, full_history_pins = _native_owner_projection(before, after, documents, target_urls)
    native = update_native_examples(page, before, native_after, aliases=aliases,
        **({'source_aliases': source_aliases} if source_aliases is not None else {}),
        **({'ownership_history_documents': documents, 'target_urls': target_urls, 'defer_ownership_coverage': True}
            if documents else {}))
    runtime, references = preview.install_native_runtime(native['page'], aliases, source_path=source, web_root=web_root)
    additions = {}
    for addition in ledger.get('new_definitions', []):
        content = preview.render_append_source_evidence(addition)
        filename = sf._sha(content) + '.html'
        additions[addition['ordinal']] = ('/' + str((output / 'sources' / filename).relative_to(web_root)), content, filename)
    bound, failures = _effective_outcomes(db, base['run_id'], checkpoint['run_id'], book['book_id'], card['id'])
    revised, inverse, frequency, breakdown = preview.render_page(runtime['page'], before, after, ledger,
        source_url=card['previewUrl'], target_url=target_urls[card['id']], aliases=aliases, target_urls=target_urls,
        appended_source_urls={k: v[0] for k, v in additions.items()}, ownership_history_documents=documents,
        actual_bound_targets=bound, transfer_failures=failures, source_jumps=_source_jumps(after, request['exam_base_url']))
    native_coverage = _complete_native_owner_coverage(native, after, full_history_pins)
    coverage = (history.validate_rendered_history_coverage(revised, after, native_coverage,
        ownership_history_documents=documents, target_urls=target_urls, aliases=aliases) if documents else None)
    restored = restore_original(preview.restore_edits(revised, inverse), runtime['inverse'])
    restored = preview.restore_edits(restored, references)
    _require(restore_original(restored, native['inverse']) == page, 'complete original source/native/runtime/SF inverse differs')
    row = {**card, 'previewUrl': target_urls[card['id']], 'definition': preview._catalog_summary(card['definition'], frequency),
        'source_definition_summary': card['definition'], 'exam_frequency': frequency, 'exam_frequency_breakdown': breakdown,
        'source_example_count': card['exampleCount'],
        'owner_recovery_projection': {'parent_run_id': base['run_id'], 'run_id': checkpoint['run_id'], 'snapshot_id': after['snapshot_id']}}
    if 'definition_summary_projection' in row: row['source_definition_summary_projection'] = row.pop('definition_summary_projection')
    if native['stats']['native_examples'] or not card['exampleCount']:
        row['exampleCount'] = native['stats']['native_examples'] - native['stats']['removed_examples']
    proof = {'card_id': card['id'], 'parent_snapshot_id': before['snapshot_id'], 'snapshot_id': after['snapshot_id'],
        'source_url': card['previewUrl'], 'source_sha256': sf._sha(page), 'inverse': inverse,
        'native_inverse': native['inverse'], 'native_stats': native['stats'], 'runtime_inverse': runtime['inverse'],
        'runtime_reference_inverse': references, 'runtime_stats': runtime['stats'], 'scope_ledger_sha256': preview.digest(ledger),
        'ownership_coverage': coverage, 'owner_recovery_parent_run_id': base['run_id']}
    if full_history_pins is not None:
        proof['native_owner_projection'] = {
            'snapshot_id': native_after['snapshot_id'], 'complete_snapshot_id': after['snapshot_id'],
            'native_snapshot': native_after,
            'retained_after_row_sha256': {row['occurrence_id']: preview.digest(row)
                for row in after['occurrences'] if row['occurrence_id'] in
                    {item['occurrence_id'] for item in native_after['occurrences']}},
            'retained_occurrences': [row['occurrence_id'] for row in native_after['occurrences']],
            'sf_only_occurrences': sorted(set(full_history_pins) -
                {row['occurrence_id'] for row in native_after['occurrences']}),
            'complete_native_coverage': native_coverage}
    return revised, row, proof, additions


def _write_card(path, content, proof):
    """Seal the bytes actually materialized for downstream source overlays."""
    with Path(path).open('xb') as handle:
        handle.write(content.encode('utf-8'))
    proof['after_sha256'] = preview.file_sha(path)


def render_patch(checkpoint_pin, *, render_continuation_pin=None):
    """Render the certified clone through read-only connections; keep it on error."""
    checkpoint = json.loads(preview.pin_file(checkpoint_pin).read_text())
    _require(checkpoint.get('schema') == CHECKPOINT_SCHEMA, 'unknown owner patch checkpoint')
    continuation = None
    if render_continuation_pin is not None:
        sealed_request = json.loads(preview.pin_file(checkpoint['request']).read_text())
        continuation = _load_render_continuation(render_continuation_pin, checkpoint_pin, checkpoint, sealed_request)
    path, request, base, original_request = _load_request(checkpoint['request']['file'], checkpoint['request']['sha256'],
        **({'render_continuation': continuation} if continuation else {}))
    _require(checkpoint['code_pins'] == request['code_pins'] and checkpoint['base_checkpoint'] == request['base_checkpoint']
             and checkpoint['parent_run_id'] == base['run_id'] and checkpoint['integrity'] == {
                 'foreign_keys': 'ok', 'quick_check': 'ok', 'write_connections_closed': True}, 'owner patch checkpoint scope/code differs')
    db_path = Path(checkpoint['database']['file'])
    _require(checkpoint['database'] == preview._checked_database_hash(db_path), 'owner patch certified database bytes/stat differ')
    web_root = Path(original_request['web_root']); staged = []; published = []; entries = []
    from scripts.prepare_sense_frequency_records import class_aliases
    from anki_pipeline.native_example_usage import load_source_aliases
    source_aliases = load_source_aliases(original_request['native_source_aliases']) if original_request.get('native_source_aliases') else None
    aliases_by_version = {}; relative = Path('web-preview') / checkpoint['run_id']; started = time.monotonic()
    try:
        with closing(preview._ro(db_path)) as db:
            run = db.execute('SELECT payload_sha256,payload FROM exam_usage_owner_patch_runs WHERE id=?', (checkpoint['run_id'],)).fetchone()
            _require(run == (preview.digest(checkpoint['run']), preview.canonical(checkpoint['run'])), 'owner patch database run payload changed')
            for book in original_request['books']:
                entry, entry_page, catalog_path, catalog = preview.load_catalog(book, web_root)
                output = Path(book['output']); _require(not output.exists(), 'owner recovery output already exists')
                stage = Path(tempfile.mkdtemp(prefix='.owner-recovery-', dir=output.parent)); staged.append((stage, output))
                (stage / relative / 'cards').mkdir(parents=True); (stage / 'sources').mkdir(); (stage / 'history').mkdir()
                docs = {}
                cards_by_id = {c['id']: c for c in catalog['cards']}
                for table, run_id in [('exam_usage_history_documents', base['run_id']), ('exam_usage_owner_patch_documents', checkpoint['run_id'])]:
                    for card_id, parent, url, sha, raw in db.execute('SELECT card_id,parent_snapshot_id,source_url,document_sha256,original_html '
                            'FROM ' + table + ' WHERE run_id=? AND book_id=?', (run_id, book['book_id'])):
                        metadata = cards_by_id[card_id]
                        content = preview._history_document(metadata['word'], parent, url, raw)
                        _require(sf._sha(content) == sha and (card_id not in docs or docs[card_id] == sha), 'history source document content conflicts')
                        docs[card_id] = sha; (stage / 'history' / (card_id + '.html')).write_bytes(content.encode())
                urls = {c['id']: '/' + str((output / relative / 'cards' / preview._card_filename(c['id'])).relative_to(web_root)) for c in catalog['cards']}
                rows = []; proof_file = stage / 'verification-card-proofs.jsonl'; phase = time.monotonic()
                with proof_file.open('x') as proofs:
                    for card in catalog['cards']:
                        payload = resolve_prepared(db, base['run_id'], checkpoint['run_id'], book['book_id'], card['id'])
                        if payload is None:
                            rows.append(card); continue
                        source = preview._local_url(card['previewUrl'], web_root); version = source.parent.parent
                        if version not in aliases_by_version: aliases_by_version[version] = class_aliases(version)
                        content, row, proof, additions = _render_one(db, base, checkpoint, card, book, output, web_root,
                            aliases_by_version[version], source_aliases, urls, request, payload=payload)
                        for _, evidence, filename in additions.values():
                            dest = stage / 'sources' / filename
                            _require(not dest.exists() or dest.read_bytes() == evidence.encode(), 'immutable dictionary source bytes conflict')
                            dest.write_bytes(evidence.encode())
                        card_path = stage / relative / 'cards' / preview._card_filename(card['id'])
                        _write_card(card_path, content, proof)
                        proofs.write(preview.canonical(proof) + '\n'); rows.append(row)
                        if len(rows) % 100 == 0:
                            print(preview.canonical({'stage': 'owner_recovery_render', 'book_id': book['book_id'],
                                'cards': len(rows), 'elapsed_seconds': round(time.monotonic()-phase, 3)}), file=sys.stderr, flush=True)
                new_catalog = {**catalog, 'cards': rows, 'source_counts': catalog['counts'],
                    'counts': {**catalog['counts'], 'examples': sum(c['exampleCount'] for c in rows)},
                    'owner_recovery': {'scope': 'v5-owner-recovery', 'parent_run_id': base['run_id'], 'run_id': checkpoint['run_id']}}
                (stage / 'catalog.json').write_text(preview.canonical(new_catalog) + '\n')
                _require('<base ' not in entry_page, 'original library shell already has a resource base')
                shell = re.sub(r'data-catalog-url="[^"]+"', 'data-catalog-url="/' + str((output / 'catalog.json').relative_to(web_root)) + '"', entry_page)
                shell = shell.replace('<head>', '<head><base href="/' + str(entry.relative_to(web_root)) + '">', 1)
                (stage / 'preview-library.html').write_text(shell)
                verification = {'schema': SCHEMA, 'run_id': checkpoint['run_id'], 'parent_run_id': base['run_id'],
                    'word_cards': sum('owner_recovery_projection' in c for c in rows), 'prepared_checkpoint': checkpoint_pin,
                    'source_entry': book['entry'], 'source_catalog': {'file': str(catalog_path), 'sha256': preview.file_sha(catalog_path)},
                    'code_pins': request['code_pins'], 'base_code_pins': base['code_pins'], 'code_changes': request.get('code_changes', []),
                    'card_proofs': {'file': str(output / proof_file.name), 'sha256': preview.file_sha(proof_file)},
                    **_render_continuation_evidence(request, continuation)}
                (stage / 'verification.json').write_text(preview.canonical(verification)+'\n')
                expected_cards = db.execute('SELECT count(*) FROM exam_usage_parent_snapshots WHERE run_id=? AND book_id=?',
                    (base['run_id'], book['book_id'])).fetchone()[0]
                _require(verification['word_cards'] == expected_cards, 'full owner recovery word-card coverage differs')
                entries.append({'book_id': book['book_id'], 'entry': str(output / 'preview-library.html')})
                print(preview.canonical({'stage': 'owner_recovery_book_complete', 'book_id': book['book_id'],
                    'cards': len(rows), 'elapsed_seconds': round(time.monotonic()-phase, 3)}), file=sys.stderr, flush=True)
        _patch_inputs(request, base, original_request, checkpoint['watched_pins'], render_continuation=continuation)
        if source_aliases is not None:
            load_source_aliases(original_request['native_source_aliases'])
        preview.pin_file(checkpoint_pin)
        _require(preview._checked_database_hash(db_path) == checkpoint['database'], 'certified patch database changed during read-only rendering')
        for stage, output in staged:
            _require(not output.exists(), 'owner recovery destination appeared before publication')
            stage.rename(output); published.append(output)
        return {'schema': SCHEMA, 'scope': 'v5-owner-recovery', 'run_id': checkpoint['run_id'], 'parent_run_id': base['run_id'],
            'new_database': checkpoint['database'], 'prepared_checkpoint': checkpoint_pin, 'word_cards': base['word_cards'],
            'affected_cards': checkpoint['affected_cards'], 'added_occurrences': checkpoint['added_occurrences'],
            'bound_histories': checkpoint['bound_histories'], 'retained_unresolved': checkpoint['retained_unresolved'],
            'entries': entries, 'render_seconds': round(time.monotonic()-started, 3),
            'base_database_unchanged': True, 'code_pins': request['code_pins'], 'base_code_pins': base['code_pins'],
            **_render_continuation_evidence(request, continuation)}
    except BaseException as error:
        failures = []
        for item in [*(p for p, _ in staged), *published]:
            try:
                if item.exists(): shutil.rmtree(item)
            except OSError as cleanup: failures.append({'file': str(item), 'error': str(cleanup)})
        preview._save_failed_render(checkpoint_pin, checkpoint, error, failures,
            continuation_evidence=_render_continuation_evidence(request, continuation))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path); parser.add_argument('--sha256', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true'); mode.add_argument('--execute', action='store_true')
    mode.add_argument('--resume-render', type=Path); parser.add_argument('--checkpoint-sha256')
    parser.add_argument('--render-code-continuation', type=Path)
    parser.add_argument('--render-code-continuation-sha256')
    args = parser.parse_args(argv)
    if args.resume_render:
        _require(args.checkpoint_sha256, 'owner recovery resume requires its exact checkpoint SHA')
        checkpoint_pin = {'file': str(args.resume_render), 'sha256': args.checkpoint_sha256}
        checkpoint = json.loads(preview.pin_file(checkpoint_pin).read_text())
        _require(checkpoint['request'] == {'file': str(args.request.resolve()), 'sha256': args.sha256}, 'owner recovery resume request differs')
    else:
        _require(args.checkpoint_sha256 is None, 'checkpoint SHA is valid only for read-only resume')
        _require(args.render_code_continuation is None and args.render_code_continuation_sha256 is None,
                 'owner render continuation is valid only for read-only resume')
        checkpoint_pin = prepare_patch(args.request, args.sha256)
    _require((args.render_code_continuation is None) == (args.render_code_continuation_sha256 is None),
             'owner render continuation requires its file and exact SHA together')
    continuation_pin = ({'file': str(args.render_code_continuation.resolve()),
                         'sha256': args.render_code_continuation_sha256}
                        if args.render_code_continuation is not None else None)
    result = (render_patch(checkpoint_pin, render_continuation_pin=continuation_pin)
              if args.execute or args.resume_render else checkpoint_pin)
    print(preview.canonical(result), flush=True)


if __name__ == '__main__':
    main()
