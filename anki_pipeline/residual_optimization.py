"""Source-pinned, candidate-only residual updates, separate from study progress.

Preparation reads only affected immutable parents. Application is an explicit
transaction against ROOT's independent clone; it never copies or opens the
baseline for writing. Old snapshots remain the lossless rollback store.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import inspect
import json
from pathlib import Path
import re
import shutil
import sqlite3

from . import sense_frequency as sf
from . import exam_usage_policy as policy
from .ownership_history import bind_incoming_history
from .store import utc_now
from .translation_alignment import validate_translation_alignment
from .sense_groups import group_report

REQUEST = 'residual-optimization-request.v1'
PLAN = 'residual-optimization-plan.v1'
CHECKPOINT = 'residual-optimization-checkpoint.v1'
ACTIONS = {'match_existing_sense', 'confirm_common_sense', 'append_dictionary_sense',
           'contextual_usage', 'rehome', 'exclude_nonlexical', 'source_correction',
           'retain_specific_ambiguity'}
_DDL = (
    'CREATE TABLE IF NOT EXISTS residual_batches (run_id TEXT PRIMARY KEY, plan_sha256 TEXT NOT NULL, state TEXT NOT NULL, baseline TEXT NOT NULL, created_at TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS residual_cards (run_id TEXT NOT NULL REFERENCES residual_batches(run_id), book_id TEXT NOT NULL, card_id TEXT NOT NULL, parent_snapshot_id TEXT NOT NULL REFERENCES snapshots(id), child_snapshot_id TEXT NOT NULL REFERENCES snapshots(id), ledger TEXT NOT NULL, PRIMARY KEY(run_id,book_id,card_id))',
    'CREATE TABLE IF NOT EXISTS residual_decisions (run_id TEXT NOT NULL REFERENCES residual_batches(run_id), decision_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,decision_id))',
    'CREATE TABLE IF NOT EXISTS residual_entities (entity_id TEXT PRIMARY KEY, lemma TEXT NOT NULL, payload TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS residual_entity_usages (run_id TEXT NOT NULL REFERENCES residual_batches(run_id), entity_id TEXT NOT NULL REFERENCES residual_entities(entity_id), book_id TEXT NOT NULL, occurrence_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,entity_id,book_id,occurrence_id))',
    'CREATE TABLE IF NOT EXISTS residual_display_updates (run_id TEXT NOT NULL REFERENCES residual_batches(run_id), display_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,display_id))',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    result = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    for chunk in encoder.iterencode(value):
        result.update(chunk.encode('utf-8'))
    return result.hexdigest()


def stat_pin(path):
    s = Path(path).stat()
    return {'dev': s.st_dev, 'inode': s.st_ino, 'bytes': s.st_size, 'mtime_ns': s.st_mtime_ns}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def read_pin(pin):
    require(isinstance(pin, dict) and re.fullmatch(r'[0-9a-f]{64}', pin.get('sha256', '')),
            'exact file/SHA256 pin required')
    p = Path(pin.get('file', pin.get('path', ''))).resolve(strict=True)
    require(p.is_file() and p.suffix not in {'.sqlite', '.sqlite3', '.db'}, 'DB is not a JSON/evidence source pin')
    before = stat_pin(p)
    raw = p.read_bytes()
    require(digest(raw) == pin['sha256'] and stat_pin(p) == before, 'pinned source changed: ' + str(p))
    return raw


def read_json(pin):
    return json.loads(read_pin(pin), object_pairs_hook=_unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


class _Watched(dict):
    def __init__(self, pins=()):
        super().__init__(pins)
        self.stats = {p: stat_pin(p) for p in self}


def _pins(items, watched):
    require(isinstance(items, list) and items, 'actual source evidence pins required')
    for pin in items:
        path = str(Path(pin.get('file', pin.get('path', ''))).resolve())
        require(path not in watched or watched[path] == pin['sha256'], 'conflicting source pins')
        if path not in watched:
            require(re.fullmatch(r'[0-9a-f]{64}', pin.get('sha256', '')) and Path(path).is_file()
                    and Path(path).suffix not in {'.db', '.sqlite', '.sqlite3'}, 'actual evidence file/SHA pin required')
            before = stat_pin(path)
            result = hashlib.sha256()
            with Path(path).open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(chunk)
            require(result.hexdigest() == pin['sha256'] and stat_pin(path) == before, 'pinned source changed: ' + path)
        elif isinstance(watched, _Watched):
            require(stat_pin(path) == watched.stats[path], 'previously verified source changed during preparation')
        else:
            read_pin(pin)
        watched[path] = pin['sha256']
        if isinstance(watched, _Watched):
            watched.stats[path] = stat_pin(path)


def _capture_pins(value, watched):
    if isinstance(value, dict):
        if value.get('capture_file') and value.get('capture_sha256'):
            _pins([{'file': value['capture_file'], 'sha256': value['capture_sha256']}], watched)
        for item in value.values():
            _capture_pins(item, watched)
    elif isinstance(value, list):
        for item in value:
            _capture_pins(item, watched)


def _connect(path, *, write=False):
    p = Path(path).resolve(strict=True)
    require(not Path(str(p) + '-wal').exists() or Path(str(p) + '-wal').stat().st_size == 0,
            'database has a live WAL; certified checkpoint required before immutable reads or writes')
    db = sqlite3.connect(p.as_uri() + ('?mode=rw' if write else '?mode=ro&immutable=1'), uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if not write:
            db.execute('PRAGMA query_only=ON')
        require(db.execute('PRAGMA user_version').fetchone()[0] == 2, 'current v2 sense schema required; no migration')
    except BaseException:
        db.close()
        raise
    return db


def _graph(db):
    return [list(r) for r in db.execute('SELECT book_id,card_id,snapshot_id FROM active_snapshots ORDER BY book_id,card_id')]


def _parent(db, key, expected):
    row = db.execute('SELECT s.payload FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id '
                     'WHERE a.book_id=? AND a.card_id=? AND a.snapshot_id=?', (*key, expected)).fetchone()
    require(row is not None, 'stale or absent current book/card/snapshot')
    data = json.loads(row[0])
    require(data['snapshot_id'] == expected and (data['book_id'], data['card_id']) == key,
            'snapshot payload identity differs')
    require(digest({k: v for k, v in data.items() if k != 'snapshot_id'}) == expected,
            'parent immutable payload fingerprint differs')
    require(_physical_prepare(policy.producer_record(data), certified=data) == data,
            'parent does not reproduce its exact immutable physical payload')
    return data


def _physical_prepare(record, *, certified, reseal=False):
    """Reuse exact accepted v2 display bytes; validate physical rows with core APIs.

    The baseline's full SHA/stat and parent canonical fingerprint are separately
    bound. No newly authored v2 display can enter this lane; changed display text
    exists only in the independent residual presentation ledger.
    """
    data = sf._definition(record)
    original = {r['occurrence_id']: r for r in certified['occurrences']}
    unique = {}
    for item in record['occurrences']:
        raw = {k: v for k, v in item.items() if k != 'display'}
        row = sf._occurrence(raw, data, require_binding=not reseal)
        history = row.get('semantic_review', {}).get('residual_owner_history')
        if history:
            require(history.get('schema') == 'residual-native-phrase-history.v1'
                    and history['history_sha256'] == digest({k: v for k, v in history.items() if k != 'history_sha256'})
                    and history['source_parent_row_sha256'] == digest(history['source_parent_row'])
                    and history['companion_parent_row_sha256'] == digest(history['companion_parent_row'])
                    and history['canonical_occurrence_id'] == row['occurrence_id']
                    and history['canonical_owner_card_id'] == data['card_id'] and history['source_book_id'] == data['book_id'],
                    'native phrase canonical history/identity seal differs')
        if 'display' in item:
            accepted = original.get(row['occurrence_id'])
            require(accepted is not None and item['display'] == accepted.get('display'),
                    'new or modified legacy v2 display cannot use certified-copy lane')
            # All source and target values participating in v2 validation remain
            # exactly the same as its certified physical parent.
            for field in ('english', 'translation', 'target_range', 'translation_ranges',
                          'physical_source', 'paper_id', 'source_provenance', 'alignment', 'alignment_evidence'):
                require(row[field] == accepted[field], 'legacy display physical authority changed: ' + field)
            row['display'] = deepcopy(item['display'])
        if 'matching_proposal' in item:
            row['matching_proposal'] = sf._proposal(item['matching_proposal'], data, row, require_binding=not reseal)
        previous = unique.get(row['occurrence_id'])
        require(previous is None or {k: v for k, v in previous.items() if k != 'sentence_id'} ==
                {k: v for k, v in row.items() if k != 'sentence_id'}, 'conflicting physical occurrence/assignment')
        unique[row['occurrence_id']] = row
    require(len(unique) == data['expected_occurrences'], 'physical count differs from exact producer records')
    data['occurrences'] = sorted(unique.values(), key=lambda r: r['occurrence_id'])
    for field in ('exam_usage_policy', 'sense_group_equivalences', 'ownership_history_unresolved',
                  'candidate_scope', 'candidate_source_record'):
        if field in record:
            require(field not in {'candidate_scope', 'candidate_source_record'} or record[field] == certified.get(field),
                    'candidate scope cannot change in certified-copy lane')
            data[field] = deepcopy(record[field])
    data['snapshot_id'] = digest(data)
    return data
def _append_native(record, technical, registry):
    """Keep the legacy validator, plus an explicitly authorized pinned CN-only bridge."""
    from . import dictionary_review_evidence as evidence
    source, sense = technical['dictionary_explanation'], technical['new_sense']
    require(all(isinstance(sense.get(k), str) and sense[k].strip() for k in ('pos', 'text', 'original_english'))
            and isinstance(technical.get('dictionary_source_pins'), list) and technical['dictionary_source_pins'],
            'full bilingual new sense and actual dictionary source pins required')
    secondary = source.get('secondary_source', sense.get('secondary_source', {}))
    chinese_only = (sense['translation_kind'] == 'cross_dictionary_original' and secondary and
                    not secondary.get('english_definition') and secondary.get('source_ref_pin', secondary).get('provider') == 'official_web')
    key = digest([sense['pos'], sense['text'], sense['original_english'], sense['translation_kind'],
                  source.get('source_ref_pin'), secondary])
    prior = record['definition_provenance'].get('supplemental_definitions', {}).get('appended', [])
    existing = next((s for s in prior if s.get('residual_native_key') == key), None)
    if existing:
        return existing['ordinal']
    if not chinese_only:
        technical = deepcopy(technical)
        technical.update(status='reviewed', sense_id=None)
        indices, appended = policy._append_definitions(record, {'new': technical}, registry=registry)
        ordinal = indices['new']
        entry = appended[0]
        # _append_definitions stores the same entry object in provenance.
    else:
        require(source['exact_entry'].casefold() == record['word'].casefold(), 'Chinese-only primary headword differs')
        primary = evidence._source(source['source_ref_pin'], registry, source['english_definition'], source.get('original_chinese', ''))
        require(source['source'] == primary['source_ref_pin']['provider'] and
                primary['source_ref_pin'].get('source_headword', '').casefold() == record['word'].casefold() and
                sense['original_english'] == primary['english_definition'] and source.get('original_chinese', '') == primary['original_chinese'],
                'Chinese-only bridge cannot alter primary native EN/CN')
        pin = secondary.get('source_ref_pin', secondary)
        require(pin.get('source_headword', '').casefold() == record['word'].casefold() and secondary.get('scope_reason')
                and secondary.get('sense_equivalence', {}).get('reading_rationale') and secondary.get('native_locator'),
                'official Chinese-only sense needs headword, exact locator and contextual equivalence rationale')
        cn = secondary.get('original_chinese')
        require(cn and sense.get('original_chinese') == sense['text'] == cn, 'official Chinese-only text must remain original Chinese exactly')
        captured = evidence._official_capture(pin, chinese=cn)
        raw = read_pin({'file': pin['capture_file'], 'sha256': pin['capture_sha256']}).decode('utf-8')
        block = secondary.get('native_block', {})
        bounds = sf._span(block.get('capture_range'), raw)
        require(raw[slice(*bounds)] == block.get('text') and cn in block['text']
                and re.search(r'(?<![\w-])' + re.escape(record['word']) + r'(?![\w-])', raw, re.I),
                'official Chinese-only native block/headword not in exact captured bytes')
        verified = {'schema': 'dictionary-review-evidence.v1', 'translation_kind': sense['translation_kind'],
                    'english_definition': primary['english_definition'], 'text': cn, 'original_chinese': cn,
                    'primary_source': primary, 'secondary_source': captured,
                    'official_chinese_only_bridge': deepcopy(secondary), 'secondary_english_was_available': False}
        ordinal = len(record['senses'])
        record['senses'].append({'pos': sense['pos'], 'text': sense['text']})
        entry = {'ordinal': ordinal, 'source_name_zh': policy.dictionary_name_zh(source), 'source_name_original': source['name'],
            'source_version': source['version'], 'source_headword': source['exact_entry'], 'sense_ref': source['sense'],
            'english': sense['original_english'], 'original_chinese': cn, 'translation_kind': sense['translation_kind'],
            'translation_label': '其他词典原译', 'scope_kind': sense.get('scope_kind', 'headword'),
            'source_pins': deepcopy(technical['dictionary_source_pins']), 'native_definition': deepcopy(source),
            'review_evidence': deepcopy(technical), 'validated_source_evidence': verified}
        record['definition_provenance'].setdefault('supplemental_definitions', {}).setdefault('appended', []).append(entry)
    ref = source.get('source_ref_pin', {})
    lane = source.get('dictionary', ref.get('dictionary', ref.get('dictionary_id')))
    require(lane, 'dictionary source lane must be explicit, separate from parser/provider')
    entry.update(source_dictionary=lane, source_provider=source['source'], kind='dictionary_sense',
                 is_dictionary_native=True, residual_native_key=key)
    if secondary:
        sec_ref = secondary.get('source_ref_pin', secondary)
        entry['chinese_source'] = {'dictionary': secondary.get('dictionary', sec_ref.get('dictionary', sec_ref.get('dictionary_id'))),
                                 'provider': sec_ref.get('provider'), 'definition': deepcopy(secondary)}
        require(entry['chinese_source']['dictionary'], 'independent Chinese dictionary source lane required')
    return ordinal


def _card_scope(parent, row, decision, book, watched):
    """An explicit original native scope can license an inflection/context label."""
    if decision['actual_lemma'].strip() == parent['word'].strip():
        return
    scope = book.get('card_lexical_scope', {})
    require(scope.get('kind') in {'existing_sense_context', 'native_inflection'} and
            (scope.get('card_lemma'), scope.get('snapshot_id'), scope.get('occurrence_id'), scope.get('actual_lemma')) ==
            (parent['word'], parent['snapshot_id'], row['occurrence_id'], decision['actual_lemma']) and scope.get('reason'),
            'wrong lexical card; explicit native scope, rehome or auxiliary entity required')
    senses = {s['sense_id'] for s in parent['senses']}
    declared = scope.get('sense_ids')
    require(isinstance(declared, list) and declared and set(declared) <= senses, 'card lexical scope must bind original book senses')
    selected = (book.get('common_sense_certificate', {}).get('member_sense_ids', [])
                if book.get('action', decision['action']) == 'confirm_common_sense' else [book.get('sense_id')])
    require(set(selected) <= set(declared), 'selected sense is outside explicit native card scope')
    surface = row['english'][slice(*row['target_range'])]
    require(scope.get('target_surface') == surface, 'native card scope target surface differs')
    if scope['kind'] == 'existing_sense_context':
        require(scope.get('actual_target_lemma') == parent['word'] and surface.casefold() == parent['word'].casefold(),
                'context-expression label cannot change the target lexical word')
    proofs = scope.get('native_evidence')
    require(isinstance(proofs, list) and proofs, 'original native scope/header evidence required')
    _pins(scope['source_pins'], watched)
    for proof in proofs:
        require(proof.get('native_locator') and proof.get('source_headword') == parent['word'], 'native card scope source headword/locator differs')
        _pins([proof['source_pin']], watched)
        raw = read_pin(proof['source_pin']).decode('utf-8')
        bounds = sf._span(proof['capture_range'], raw)
        require(raw[slice(*bounds)] == proof['text'], 'native scope block differs from exact captured bytes')
        if scope['kind'] == 'native_inflection':
            require(surface in proof['text'], 'target inflection absent from captured native forms')


def _meaning(record, parent, row, decision, book, registry, watched):
    _card_scope(parent, row, decision, book, watched)
    action = book.get('action', decision['action'])
    indices = {s['sense_id']: s['ordinal'] for s in parent['senses']}
    row.pop('matching_proposal', None)
    row.pop('broad_match', None)
    row.pop('common_sense_match', None)
    if action == 'append_dictionary_sense':
        technical = deepcopy(book.get('technical_decision', {}))
        require(technical.get('new_sense') and technical.get('dictionary_explanation'),
                'append needs full core dictionary evidence technical_decision')
        require(technical['dictionary_explanation']['exact_entry'].casefold() == parent['word'].casefold(),
                'append dictionary entry belongs to another lexical card')
        row['sense_index'] = _append_native(record, technical, registry)
    elif action == 'confirm_common_sense':
        certificate = deepcopy(book.get('common_sense_certificate'))
        require(isinstance(certificate, dict) and certificate.get('meaning') and certificate.get('usage_scope')
                and certificate.get('evidence'), 'common sense needs full per-member equivalence certificate')
        members = certificate['member_sense_ids']
        require(len(set(members)) == len(members) >= 2 and all(i in indices for i in members),
                'common sense members must be actual distinct card senses')
        from .sense_groups import _pos
        require(len({_pos(parent['senses'][indices[i]]['pos']) for i in members}) == 1,
                f"common sense certificate crosses POS: {parent['book_id']}/{parent['word']}/{row['occurrence_id']}; members={members}")
        record.setdefault('sense_group_equivalences', []).append(certificate)
        row.update(status='ambiguous', sense_index=None, reviewed_sense_id=None, assignment_context_hash=None)
        row['common_sense_match'] = {'candidate_sense_ids': members, 'reason': decision['reason'],
                                   'method': 'context-review', 'review_version': '20261013'}
    elif action == 'contextual_usage':
        contextual = deepcopy(book.get('contextual_sense', {}))
        require(contextual.get('kind') == 'contextual_usage' and contextual.get('is_dictionary_native') is False,
                'contextual sense must explicitly distinguish review from native dictionary text')
        require(all(isinstance(contextual.get(k), str) and contextual[k].strip() for k in ('pos', 'text', 'english'))
                and contextual.get('native_base_evidence') and decision.get('dictionary_evidence'),
                'contextual sense needs bilingual meaning, original dictionary base and context evidence')
        bases = contextual.get('base_sense_ids', [])
        require(isinstance(bases, list) and len(bases) == len(set(bases)) and all(i in indices for i in bases),
                'contextual base IDs must belong to the actual current card')
        evidence = {'kind': 'contextual_usage', 'is_dictionary_native': False,
                    'source_dictionary': 'contextual_review', 'source_name_zh': '语境用法（非词典原义）',
                    'source_name_original': 'Context review', 'source_version': '20261013',
                    'source_headword': parent['word'], 'english': contextual['english'],
                    'original_chinese': None, 'translation_kind': 'contextual_review',
                    'translation_label': '语境释义', 'base_sense_ids': deepcopy(bases),
                    'native_base_evidence': deepcopy(contextual['native_base_evidence']),
                    'context_evidence': deepcopy(decision['context_evidence']),
                    'review_evidence': deepcopy(decision), 'contextual_sense': contextual,
                    'source_pins': deepcopy(decision['source_pins'])}
        supplement = record['definition_provenance'].setdefault('supplemental_definitions', {}).setdefault('appended', [])
        semantic_key = digest([contextual, decision['context_evidence']])
        existing = next((s for s in supplement if s.get('contextual_key') == semantic_key), None)
        if existing:
            row['sense_index'] = existing['ordinal']
        else:
            row['sense_index'] = len(record['senses'])
            record['senses'].append({'pos': contextual['pos'], 'text': contextual['text']})
            supplement.append({**evidence, 'ordinal': row['sense_index'], 'contextual_key': semantic_key})
    elif action == 'retain_specific_ambiguity' or (action == 'source_correction' and not book.get('sense_id')):
        require(decision.get('remaining_reason') or decision.get('meaning_zh'), 'specific unresolved reason required')
        row.update(status='ambiguous' if action == 'retain_specific_ambiguity' else 'unmatched',
                   sense_index=None, reviewed_sense_id=None, assignment_context_hash=None)
    else:
        require(book.get('sense_id') in indices, 'sense must belong to this actual book/card')
        row['sense_index'] = indices[book['sense_id']]
    row['reason'] = decision['reason']
    row['method'] = 'residual-optimization-context-review.v1'
    row['review_version'] = '20261013'
    row['semantic_review'] = {**deepcopy(decision), 'occurrence_id': row['occurrence_id']}
    if row['sense_index'] is not None:
        row['status'] = 'reviewed'
        row.pop('pending_category', None)
    elif action == 'confirm_common_sense':
        row.pop('pending_category', None)
    return row


def _preflight_equivalences(record, parent):
    """Validate every actual definition certificate before expensive chunk I/O."""
    data = sf._definition(record)
    remap = {sense['sense_id']: data['senses'][sense['ordinal']]['sense_id'] for sense in parent['senses']}
    def rebound(value):
        if isinstance(value, list):
            return [rebound(v) for v in value]
        if isinstance(value, dict):
            return {k: rebound(v) for k, v in value.items()}
        return remap.get(value, value) if isinstance(value, str) else value
    certificates = rebound(record.get('sense_group_equivalences', []))
    data.update(snapshot_id=parent['snapshot_id'], expected_occurrences=0, occurrences=[], sense_group_equivalences=certificates)
    try:
        group_report(sf.report_from_record(data))
    except ValueError as exc:
        members = [c.get('member_sense_ids', c.get('member_ordinals')) for c in certificates]
        raise ValueError(f"common preflight {parent['book_id']}/{parent['word']}/{parent['card_id']}: {exc}; members={members}") from exc


class _NativeBlock(HTMLParser):
    """Extract one exact native sense element, preserving its real capture pin."""
    def __init__(self, identity):
        super().__init__(convert_charrefs=True)
        self.identity, self.depth, self.matches, self.parts = identity, 0, 0, []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self.depth:
            if tag not in {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr'}:
                self.depth += 1
        elif self.identity in (attributes.get('id'), attributes.get('data-wl-senseid')):
            self.depth = 1
            self.matches += 1
        if self.depth:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if self.depth and tag not in {'br', 'hr', 'img', 'input', 'meta', 'link', 'wbr'}:
            self.depth -= 1
            self.parts.append(' ')

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)


def _auxiliary_entity(decision, book, registry, watched):
    """Use the author's native definition without inventing a book learning card."""
    entity = deepcopy(book.get('auxiliary_entity', {}))
    native = deepcopy(book.get('new_sense', entity.get('new_sense', {})))
    if not entity:
        entity = {'lemma': decision['actual_lemma'], 'pos': native.get('pos', decision.get('actual_pos')),
                  'meaning_zh': decision.get('meaning_zh'), 'meaning_en': decision.get('meaning_en'),
                  'dictionary_evidence': deepcopy(decision.get('dictionary_evidence')), 'learning_card': False}
    require(entity.get('lemma', '').casefold() == decision['actual_lemma'].casefold()
            and entity.get('learning_card', False) is False and entity.get('dictionary_evidence')
            and entity.get('meaning_zh') and entity.get('pos'), 'absent target needs a sourced auxiliary lexical entity')
    technical = book.get('technical_decision', entity.get('technical_decision'))
    native_lemma = entity.get('native_base_lemma', entity['lemma'])
    if native_lemma.casefold() != entity['lemma'].casefold():
        require(entity.get('native_scope_evidence') and
                (entity.get('kind') != 'contextual_usage' or entity.get('is_dictionary_native') is False),
                'distinct native base needs explicit scope and contextual-source labels')
    bases = entity.get('native_base_evidence')
    if entity.get('kind') == 'contextual_usage' and bases:
        from .dictionary_review_evidence import _source
        require(entity.get('is_dictionary_native') is False and entity.get('native_scope_evidence'),
                'contextual lexical entity must label source scope and non-native definition explicitly')
        bases = bases if isinstance(bases, list) else [bases]
        verified = []
        for base in bases:
            proof = _source(base['source_ref_pin'], registry, base['english_definition'], base.get('original_chinese', ''))
            require(proof['source_ref_pin'].get('source_headword', '').casefold() == native_lemma.casefold()
                    and proof['original_chinese'] == base.get('original_chinese', ''), 'contextual native base headword or Chinese differs')
            verified.append(proof)
            _capture_pins(base, watched)
        entity['native_definition'] = {'kind': 'dictionary_base_only', 'is_definition_of_complete_lexeme': False,
                                       'native_base_lemma': native_lemma, 'bases': deepcopy(bases)}
        entity['validated_source_evidence'] = {'kind': 'contextual_usage', 'is_dictionary_native': False,
                                              'native_base_sources': verified, 'context_evidence': deepcopy(decision['context_evidence'])}
    elif entity.get('kind') == 'contextual_usage' and entity.get('contextual_source_evidence'):
        require(entity.get('is_dictionary_native') is False and entity.get('native_scope_evidence'),
                'professional/context source cannot masquerade as a native dictionary term')
        proofs = entity['contextual_source_evidence']
        require(isinstance(proofs, list) and proofs, 'exact professional/context source blocks required')
        for proof in proofs:
            require(proof.get('source_type') in {'professional_original', 'exam_context_original', 'reference_original', 'contextual_original'}
                    and proof.get('source_title') and proof.get('reading_rationale'), 'contextual source must preserve its real role and rationale')
            _pins([proof['source_pin']], watched)
            raw = read_pin(proof['source_pin']).decode('utf-8')
            bounds = sf._span(proof['capture_range'], raw)
            require(raw[slice(*bounds)] == proof['text'], 'professional/context definition block differs from original capture')
        entity['native_definition'] = {'kind': 'contextual_source_only', 'is_dictionary_native': False,
                                       'canonical_native_base_bound': False,
                                       'native_base_search_exhausted': None, 'sources': deepcopy(proofs),
                                       'binding_failures': deepcopy(entity.get('binding_failures', []))}
        entity['validated_source_evidence'] = {'kind': 'contextual_usage', 'is_dictionary_native': False,
            'contextual_sources': deepcopy(proofs), 'context_evidence': deepcopy(decision['context_evidence'])}
    elif technical:
        from .dictionary_review_evidence import validate_new_sense
        verified = validate_new_sense(technical, registry=registry)
        source = technical['dictionary_explanation']
        require(source['exact_entry'].casefold() == native_lemma.casefold(), 'auxiliary native entry differs')
        entity['native_definition'] = deepcopy(technical)
        entity['validated_source_evidence'] = verified
    else:
        require(native.get('original_english') and native.get('original_chinese') and native.get('dictionary')
                and native.get('exact_headword', native.get('lemma', '')).casefold() == native_lemma.casefold()
                and native.get('native_sense_id') and native.get('source_entry_id') is not None,
                'auxiliary native bilingual definition and physical entry identity required')
        pin = native.get('source_evidence')
        _pins([pin], watched)
        raw = read_pin(pin).decode('utf-8')
        parser = _NativeBlock(native['native_sense_id'])
        parser.feed(raw)
        parser.close()
        text = ' '.join(''.join(parser.parts).split())
        require(parser.matches == 1 and ' '.join(native['original_english'].split()) in text
                and ' '.join(native['original_chinese'].split()) in text, 'native bilingual wording not in exact captured sense block')
        entity['native_definition'] = native
        entity['validated_source_evidence'] = {'kind': 'native_bilingual_capture', 'capture': deepcopy(pin),
            'native_sense_id': native['native_sense_id'], 'source_entry_id': native['source_entry_id'],
            'dictionary': native['dictionary'], 'version': native.get('version'), 'block_text_sha256': sf._sha(text),
            'original_english': native['original_english'], 'original_chinese': native['original_chinese']}
    entity.update(schema='residual-auxiliary-lexeme.v1', learning_card=False, canonical_owner=True,
                  contextual_gloss=entity.get('contextual_gloss', decision['reason']))
    if entity.get('kind') == 'contextual_usage':
        require(entity.get('is_dictionary_native') is False and entity.get('native_scope_evidence')
                and decision.get('context_evidence'), 'contextual entity requires independently labelled dictionary base and physical context')
    return entity


def _source_phrase_chinese_ranges(old, span):
    """Use a real source fine block covering the full lexeme; never infer Chinese."""
    candidates = [a for a in (old.get('alignment') or {}).get('alignments', [])
        if a.get('zh') and a['en'][0] <= span[0] and span[1] <= a['en'][1]
        and (a['en'] != [0, len(old['english'])] or span == a['en'])]
    if candidates:
        width = min(a['en'][1] - a['en'][0] for a in candidates)
        return [list(r) for r in sorted({tuple(r) for a in candidates
            if a['en'][1] - a['en'][0] == width for r in a['zh']})]
    return deepcopy(old['translation_ranges']) if old['target_range'] == span else []


def _canonical_auxiliary(auxiliary):
    """One full lexical token per book; component aliases remain complete history."""
    entities, usages = {}, {}
    for origin in auxiliary:
        entity = origin['entity']
        native = entity['native_definition']
        from .sense_groups import _pos
        kind = entity.get('kind', 'dictionary_sense')
        # Lexical identity is independent of which source describes this use.
        # Native/contextual truth remains on each actual definition variant.
        identity_kind = 'lexical_owner'
        eid = digest(['residual-lexical-owner.v1', entity['lemma'].casefold(), _pos(entity['pos']), identity_kind])
        definition = {'definition_id': digest([native, entity['validated_source_evidence']]),
            'kind': kind, 'is_dictionary_native': entity.get('is_dictionary_native', kind != 'contextual_usage'),
            'native_definition': deepcopy(native), 'validated_source_evidence': deepcopy(entity['validated_source_evidence']),
            'meaning_zh': entity['meaning_zh'], 'meaning_en': entity.get('meaning_en'),
            'contextual_gloss': entity.get('contextual_gloss')}
        if eid in entities:
            if not any(d['definition_id'] == definition['definition_id'] for d in entities[eid]['definition_variants']):
                entities[eid]['definition_variants'].append(definition)
        else:
            entities[eid] = {**deepcopy(entity), 'canonical_identity_kind': identity_kind, 'definition_variants': [definition]}
        old, span = origin['source_parent_row'], origin['target_range']
        oid = digest([old['paper_id'], old['physical_source'], span])
        key = (eid, origin['book_id'], oid)
        if key not in usages:
            row = {k: deepcopy(old[k]) for k in ('paper_id', 'physical_source', 'sentence_id', 'english', 'english_hash',
                'translation', 'translation_hash', 'source', 'source_provenance', 'alignment')}
            row.update(occurrence_id=oid, target_range=span, translation_ranges=origin['translation_ranges'])
            usages[key] = {'schema': 'residual-auxiliary-usage.v1', 'entity_id': eid, 'book_id': origin['book_id'],
                'occurrence_id': oid, 'status': 'reviewed', 'canonical_owner': True, 'learning_card': False,
                'physical_count': 1, 'selected_definition_id': definition['definition_id'],
                'sense_id': digest([eid, definition['definition_id']]),
                'meaning_zh': entity['meaning_zh'], 'meaning_en': entity.get('meaning_en'),
                'row': row, 'explanation_placement': 'within_correct_target_sentence', 'origins': [], 'definition_variants': []}
        usage = usages[key]
        require(usage['row']['english_hash'] == old['english_hash'] and usage['row']['translation_hash'] == old['translation_hash'],
                'auxiliary aliases disagree on physical sentence')
        # Component aliases can have distinct original Chinese ranges. Keep them
        # in full origins; the usage uses only the source block of the full phrase.
        if usage['row']['translation_ranges'] != origin['translation_ranges']:
            usage['row']['translation_ranges'] = _source_phrase_chinese_ranges(old, span)
            usage['translation_range_authorities'] = ['source_full_lexeme_alignment' if usage['row']['translation_ranges']
                                                      else 'source_full_lexeme_not_aligned']
        usage['translation_range_authorities'] = sorted(set(usage.get('translation_range_authorities', []) +
            [origin.get('translation_range_authority', 'reviewed_full_lexeme')]))
        require(not any(o['source_card_id'] == origin['source_card_id'] and
                        o['source_parent_row']['occurrence_id'] == old['occurrence_id'] for o in usage['origins']), 'duplicate auxiliary source alias')
        usage['origins'].append(deepcopy({k: v for k, v in origin.items() if k != 'entity'}))
        if definition not in usage['definition_variants']:
            usage['definition_variants'].append(deepcopy(definition))
        selected = next(d for d in usage['definition_variants'] if d['definition_id'] == usage['selected_definition_id'])
        if definition['is_dictionary_native'] and not selected['is_dictionary_native']:
            usage.update(selected_definition_id=definition['definition_id'], sense_id=digest([eid, definition['definition_id']]),
                         meaning_zh=definition['meaning_zh'], meaning_en=definition['meaning_en'])
        usage['history_sha256'] = digest(usage['origins'])
        usage['review_seal'] = digest({k: v for k, v in usage.items() if k != 'review_seal'})
    return [{'entity_id': eid, **e} for eid, e in sorted(entities.items())], [u for _, u in sorted(usages.items())]


def _lexical_span(old, lemma, span, book, watched):
    span = sf._span(span, old['english'])
    surface = old['english'][slice(*span)]
    if surface.casefold() != lemma.casefold():
        form = book.get('lexical_form_evidence', {})
        if form.get('kind') == 'native_scope_inflection_bridge':
            require(form.get('surface') == surface and form.get('lemma', '').casefold() == lemma.casefold()
                    and form.get('native_scope') == lemma and form.get('native_scope_text'), 'native scope inflection identity differs')
            _pins(form['source_pins'], watched)
            _pins([form['scope_source_pin']], watched)
            require(form['native_scope_text'] in read_pin(form['scope_source_pin']).decode('utf-8')
                    and lemma.casefold() in form['native_scope_text'].casefold(), 'native phrase scope absent from pinned original header')
            normalized = surface
            for component in form['components']:
                _pins([component['source_pin']], watched)
                require(component['form_text'] in read_pin(component['source_pin']).decode('utf-8')
                        and component['surface'].casefold() in component['form_text'].casefold(), 'native inflection absent from pinned forms')
                normalized, count = re.subn(r'(?<!\w)' + re.escape(component['surface']) + r'(?!\w)', component['lemma'], normalized)
                require(count == 1, 'native inflection bridge is not an exact single component')
            require(normalized.casefold() == lemma.casefold(), 'native scope bridge changes other literal components')
            return span
        if form.get('kind') == 'reviewed_contextual_expression':
            entity = book.get('auxiliary_entity', {})
            context = form.get('context_evidence', {})
            require(form.get('surface') == surface and form.get('lemma', '').casefold() == lemma.casefold()
                    and form.get('reason') and entity.get('kind') == 'contextual_usage' and entity.get('is_dictionary_native') is False
                    and context.get('english_hash') == old['english_hash'] and context.get('target_range') == span
                    and context.get('paper_id') == old['paper_id'], 'reviewed expression must bind exact source surface, scope and non-native label')
            _pins(form['source_pins'], watched)
            return span
        require(form.get('surface') == surface and form.get('lemma', '').casefold() == lemma.casefold()
                and form.get('kind') == 'native_inflected_form' and form.get('native_locator')
                and form.get('form_text'), 'complete inflected lexical form needs explicit native form evidence')
        _pins([form['source_pin']], watched)
        raw = read_pin(form['source_pin']).decode('utf-8')
        require(form['form_text'] in raw and surface.casefold() in form['form_text'].casefold(),
                'approved surface form absent from pinned native forms')
    return span


def _immutable_row(db, book, card, snapshot, oid):
    value = db.execute('SELECT payload FROM snapshots WHERE id=? AND book_id=? AND card_id=?',
                       (snapshot, book, card)).fetchone()
    require(value is not None, 'excluded original snapshot not found in this book/card')
    parent = json.loads(value[0])
    require(digest({k: v for k, v in parent.items() if k != 'snapshot_id'}) == parent['snapshot_id'] == snapshot,
            'original excluded snapshot seal differs')
    row = next((r for r in parent['occurrences'] if r['occurrence_id'] == oid), None)
    require(row is not None, 'full original excluded occurrence not in immutable parent')
    return row


def _review_batches(request, manifest, watched):
    allowed = {x['file']: x['sha256'] for x in manifest['semantic_jobs']}
    result = []
    seen = set()
    cached = {}
    for batch in request.get('semantic', []):
        require(allowed.get(batch['input']['file']) == batch['input']['sha256'], 'semantic input not sealed by work manifest')
        require(batch['input']['file'] not in seen, 'duplicate semantic input batch')
        seen.add(batch['input']['file'])
        items = read_json(batch['input'])
        key = (batch['decisions']['file'], batch['decisions']['sha256'])
        if key not in cached:
            cached[key] = read_json(batch['decisions'])
        reviewed = cached[key]
        _pins([batch['input'], batch['decisions']], watched)
        reviewed = reviewed['decisions'] if isinstance(reviewed, dict) else reviewed
        ids = {x['id'] for x in items}
        reviewed = [d for d in reviewed if d['id'] in ids]
        require(len(ids) == len(items) == len(reviewed) and {d['id'] for d in reviewed} == ids,
                'semantic shard coverage missing/duplicated')
        result.append((items, reviewed))
    if request.get('ownership'):
        batch = request['ownership']
        require(any(p == batch['input'] for p in manifest['source_inputs']), 'ownership inventory not sealed by work manifest')
        inventory, reviewed = read_json(batch['input']), read_json(batch['decisions'])
        _pins([batch['input'], batch['decisions']], watched)
        reviewed = reviewed['decisions'] if isinstance(reviewed, dict) else reviewed
        indexed = {(x['source_word'], x['source_occurrence_id']): x for x in inventory['core_items']}
        require(len(reviewed) == len(indexed) and {(d['word'], d['id']) for d in reviewed} == set(indexed), 'ownership exact coverage differs')
        items = []
        for decision in reviewed:
            item = indexed[(decision['word'], decision['id'])]
            books = decision['book_decisions']
            require({(b['book_id'], b['card_id']) for b in books} ==
                    {(b['book_id'], b['source_card_id']) for b in item['book_records']}, 'ownership cross-book coverage differs')
            raw = []
            for book in books:
                old = next(b for b in item['book_records'] if b['book_id'] == book['book_id'] and b['source_card_id'] == book['card_id'])
                original_snapshot = book.get('scope_parent_snapshot_id', book.get('previous_binding', {}).get('scope_parent_snapshot_id'))
                require(original_snapshot == old['parent_snapshot_id'], 'ownership original parent not frozen inventory parent')
                row = book['source_occurrence']
                require(all(row.get(k) == v for k, v in old['source'].items()), 'ownership original source fields differ')
                book['source_state'] = 'excluded'
                book['source_parent_snapshot_id'] = original_snapshot
                raw.append({'book_id': book['book_id'], 'card_id': book['card_id'], 'occurrence': row})
            items.append({'id': decision['id'], 'word': decision['word'], 'book_refs': books, 'raw': raw})
        result.append((items, reviewed))
    return result


def _display_update(decision, item, watched):
    require(decision['mapping_id'] == item['mapping_id'] and decision['display_id'] == item['display_id'],
            'chunk mapping/display identity differs')
    for field in ('english', 'translation'):
        require(decision['before_display_' + field] == item['display_' + field], 'stale chunk display ' + field)
        claimed = decision.get('before_display_' + field + '_hash', decision.get('before_display_' + field + '_sha256',
                                decision.get('before_display_hashes', {}).get(field)))
        require(claimed == sf._sha(item['display_' + field]), 'chunk before text hash required')
    _pins(decision['original_source_pins'], watched)
    before = deepcopy(item['raw']['projection_record'])
    english, chinese = decision['after_display_english'], decision['after_display_translation']
    require(english == before['english'], 'chunk repair cannot silently rewrite completed English')
    chunks = deepcopy(decision['chunks'])
    require(chunks and len({c['mapping_id'] for c in chunks}) == len(chunks), 'unique complete chunk mappings required')
    old_ids = {c['mapping_id'] for c in before['chunks']}
    require(old_ids | {item['mapping_id']} <= {c.get('source_mapping_id', c['mapping_id']) for c in chunks}, 'all prior mapped blocks must be retained/re-offset')
    alignments = []
    for chunk in chunks:
        require(chunk.get('reason') and chunk.get('source') and chunk.get('mapping_id'), 'complete chunk reason/source required')
        a, b = sf._span(chunk['en'], english)
        require(chunk.get('en_fragment', english[a:b]) == english[a:b], 'chunk English slice differs')
        for x, y in chunk['zh']:
            sf._span([x, y], chinese)
        require(chunk.get('zh_fragments', [chinese[x:y] for x, y in chunk['zh']]) == [chinese[x:y] for x, y in chunk['zh']],
                'chunk Chinese slices differ')
        require(not (chunk['en'] == [0, len(english)] and len(old_ids) > 1), 'whole-sentence chunk fallback prohibited')
        alignments.append({'en': chunk['en'], 'zh': chunk['zh'], 'relation': chunk.get('relation', 'equivalent'),
                           **({'note': chunk['reason']} if not chunk['zh'] else {})})
    alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': sf._sha(english),
                 'translationHash': sf._sha(chinese), 'alignments': alignments}
    validate_translation_alignment(english, chinese, alignment)
    after = {**before, 'english': english, 'english_hash': sf._sha(english), 'translation': chinese,
             'translation_hash': sf._sha(chinese), 'chunks': chunks, 'alignment': alignment}
    comparisons = deepcopy(before.get('source_comparisons', []))
    for comparison in decision.get('source_comparisons', []):
        if comparison not in comparisons:
            comparisons.append(deepcopy(comparison))
    after['source_comparisons'] = comparisons
    after['residual_transform_evidence'] = deepcopy(decision.get('transform', decision.get('transforms', [])))
    after['unmapped'] = [c for c in before.get('unmapped', []) if c['mapping_id'] != item['mapping_id']]
    # The complete original source comparisons are retained, never reinterpreted as new source bytes.
    return {'schema': 'residual-display-update.v1', 'display_id': item['display_id'],
            'before': before, 'before_sha256': digest(before), 'after': after,
            'after_sha256': digest(after), 'decision': deepcopy(decision)}


def presentation_record(prepared, *, display_updates=None):
    """Render-only overlay: original physical rows, jumps and v2 views remain stored."""
    result = deepcopy(prepared)
    entries = (result.get('exam_usage_policy', {}).get('residual_display_updates', [])
               if display_updates is None else display_updates)
    for entry in entries:
        if entry.get('book_id') is not None:
            require((entry['book_id'], entry['card_id'], entry['child_snapshot_id']) ==
                    (prepared['book_id'], prepared['card_id'], prepared['snapshot_id']), 'presentation overlay belongs to another physical child')
        require(digest(entry['before']) == entry['before_sha256'] and digest(entry['after']) == entry['after_sha256'],
                'residual display ledger changed')
        after = entry['after']
        validate_translation_alignment(after['english'], after['translation'], after['alignment'])
        for oid in entry['occurrence_ids']:
            row = next((r for r in result['occurrences'] if r['occurrence_id'] == oid), None)
            require(row is not None and row.get('display'), 'residual display occurrence missing')
            view = deepcopy(row['display'])
            require(view['english'] == entry['before']['english'] and view['translation'] == entry['before']['translation'],
                    'residual presentation parent text differs')
            view.update(english=after['english'], english_hash=after['english_hash'], translation=after['translation'],
                        translation_hash=after['translation_hash'], alignment=after['alignment'])
            view['residual_optimization'] = deepcopy(entry)
            view['display_hash'] = sf._sha(sf._json({k: v for k, v in view.items() if k != 'display_hash'}))
            row['display'] = view
    return result


def _source_cache_contract():
    from . import sense_display, translation_alignment, ownership_history, sense_groups
    return digest([inspect.getsource(_parent), inspect.getsource(_physical_prepare),
        *[digest(Path(module.__file__).read_bytes()) for module in
          (sf, policy, sense_display, translation_alignment, ownership_history, sense_groups)]])


def prepare(request):
    """Prepare; retain only sealed immutable source cache after late failures."""
    spool = request.get('readonly_spool')
    if not spool:
        return _prepare_impl(request, None)
    root = Path(read_json(request['work_manifest'])['root']).resolve() / 'engineering/writer-own'
    directory = Path(spool).resolve()
    require(directory.is_relative_to(root) and directory != root and not directory.exists(), 'fresh writer-owned readonly spool required')
    certification_contract = _source_cache_contract()
    cache_rows = {}
    cache_graph = None
    cache_pin = request.get('readonly_source_cache')
    if cache_pin:
        cache_path = Path(cache_pin['file']).resolve()
        require(cache_path.is_relative_to(root), 'source cache must be writer-owned')
        cache = read_json(cache_pin)
        require(cache.get('schema') == 'residual-certified-source-cache.v1'
                and cache['baseline'] == request['baseline'] and cache['work_manifest'] == request['work_manifest']
                and cache['certification_contract_sha256'] == certification_contract, 'source cache certified lineage differs')
        require(re.fullmatch(r'[0-9a-f]{64}', cache.get('active_graph_sha256', '')), 'source cache active graph pin required')
        cache_graph = cache['active_graph_sha256']
        for entry in cache['entries']:
            key = (entry['book_id'], entry['card_id'])
            require(key not in cache_rows and Path(entry['payload_file']['file']).resolve().is_relative_to(root),
                    'source cache duplicate or foreign payload path')
            cache_rows[key] = entry
    directory.mkdir(parents=True)
    certified_cache = {}
    try:
        return _prepare_impl(request, directory, cache_rows, certified_cache, cache_graph)
    except BaseException as exc:
        if certified_cache and stat_pin(request['baseline']['file']) == request['baseline']['stat']:
            with closing(_connect(request['baseline']['file'])) as db:
                active_graph = digest(_graph(db))
            cache = {'schema': 'residual-certified-source-cache.v1', 'baseline': deepcopy(request['baseline']),
                'work_manifest': deepcopy(request['work_manifest']), 'certification_contract_sha256': certification_contract,
                'active_graph_sha256': active_graph,
                'entries': list(certified_cache.values()), 'failed_preparation': str(exc), 'database_writes': 0}
            with (directory / 'certified-source-cache.json').open('xb') as file:
                file.write(canonical(cache).encode())
        else:
            shutil.rmtree(directory)
        raise


def _prepare_impl(request, spool, cache_rows=None, certified_cache=None, cache_graph=None):
    """Build a detached plan from manifest-bound reviewer decisions; no DB writes."""
    require(request.get('schema') == REQUEST, 'residual request schema required')
    manifest = read_json(request['work_manifest'])
    baseline = request['baseline']
    source = Path(baseline['file']).resolve(strict=True)
    candidate = Path(request['candidate']['file']).resolve()
    require(source == Path(manifest['baseline']['database']).resolve() and source != candidate,
            'candidate must be distinct from protected manifest baseline')
    require(not candidate.exists() or not source.samefile(candidate), 'candidate aliases protected baseline inode')
    require(stat_pin(source) == baseline['stat'] and re.fullmatch(r'[0-9a-f]{64}', baseline['certified_sha256']),
            'ROOT certified baseline stat/SHA required; no full DB hash recomputation')
    watched = _Watched({str(Path(request['work_manifest']['file']).resolve()): request['work_manifest']['sha256']})
    cache_rows = cache_rows or {}
    certified_cache = certified_cache if certified_cache is not None else {}
    if request.get('readonly_source_cache'):
        _pins([request['readonly_source_cache']], watched)
    from . import dictionary_review_evidence, sense_groups, sense_display, translation_alignment, ownership_history
    for module in (Path(__file__), Path(sf.__file__), Path(policy.__file__), Path(dictionary_review_evidence.__file__),
                   Path(sense_groups.__file__), Path(sense_display.__file__), Path(translation_alignment.__file__), Path(ownership_history.__file__)):
        watched[str(module.resolve())] = digest(module.read_bytes())
        watched.stats[str(module.resolve())] = stat_pin(module)
    registry = read_json(request['dictionary_registry']) if request.get('dictionary_registry') else []
    if isinstance(registry, dict):
        registry = registry['registry']
    require(isinstance(registry, list), 'dictionary registry must contain actual native rows')
    if request.get('dictionary_registry'):
        _pins([request['dictionary_registry']], watched)
    display_bindings = read_json(request['display_bindings']) if request.get('display_bindings') else {}
    if request.get('display_bindings'):
        _pins([request['display_bindings']], watched)
    parents, producers, ledgers, decisions, auxiliary, displays, transfers, supporting = {}, {}, {}, [], [], {}, [], []
    presentation_cards = {}
    def get(db, book, card, snapshot):
        key = (book, card)
        if key not in parents:
            parent = _parent(db, key, snapshot)
            parents[key], producers[key] = parent, policy.producer_record(parent, preserve_scope=False)
            ledgers[key] = {'schema': 'residual-card-ledger.v1', 'book_id': book, 'card_id': card,
                'parent_snapshot_id': snapshot, 'original_count': parent['expected_occurrences'],
                'new_definitions': [], 'excluded': [], 'prior_wrong_lemma_ids': [], 'decisions': []}
        require(parents[key]['snapshot_id'] == snapshot, 'conflicting current parent snapshots')
        return key
    with closing(_connect(source)) as db:
        graph = _graph(db)
        require(cache_graph is None or digest(graph) == cache_graph, 'source cache active graph differs')
        for items, reviewed in _review_batches(request, manifest, watched):
            indexed = {(x.get('word', ''), x['id']): x for x in items}
            for decision in reviewed:
                require(decision['action'] in ACTIONS and decision.get('reason') and decision.get('context_evidence'), 'complete semantic decision required')
                item = indexed.get((decision['word'], decision['id']))
                require(item is not None, 'decision word/OID differs from input')
                books = decision['book_decisions']
                require({(x['book_id'], x['card_id'], x['snapshot_id']) for x in books} ==
                        {(x['book_id'], x['card_id'], x['snapshot_id']) for x in item['book_refs']} and
                        len(books) == len(item['book_refs']), 'all cross-book refs must be covered exactly')
                _pins(decision['source_pins'], watched)
                _capture_pins(decision, watched)
                decisions.append(deepcopy(decision))
                for book in books:
                    key = get(db, book['book_id'], book['card_id'], book['snapshot_id'])
                    parent, record = parents[key], producers[key]
                    raw = next(r for r in item['raw'] if (r['book_id'], r['card_id']) == key)['occurrence']
                    oid = book['occurrence_id']
                    old = next((r for r in parent['occurrences'] if r['occurrence_id'] == oid), None)
                    excluded = book.get('source_state') == 'excluded'
                    if excluded:
                        require(old is None, 'declared excluded occurrence still present in active source')
                        old = _immutable_row(db, key[0], key[1], book['source_parent_snapshot_id'], oid)
                    require(old == raw and oid == item['id'], 'complete old occurrence/identity differs from frozen input')
                    require(not any(d['occurrence_id'] == oid for d in ledgers[key]['decisions']), 'duplicate update for one physical occurrence')
                    row = next((r for r in record['occurrences'] if r['occurrence_id'] == oid), None)
                    source_snapshot = book.get('source_parent_snapshot_id', parent['snapshot_id']) if excluded else parent['snapshot_id']
                    entry = {'occurrence_id': oid, 'before_row': deepcopy(old), 'source_parent_snapshot_id': source_snapshot,
                             'source_state': 'excluded' if excluded else 'active', 'old_assignment_sha256': policy.assignment_pin({**parent, 'snapshot_id': source_snapshot}, old),
                             'decision': deepcopy(decision), 'book_decision': deepcopy(book)}
                    ledgers[key]['decisions'].append(entry)
                    action = book.get('action', decision['action'])
                    require(action in ACTIONS, 'unsupported per-book action')
                    if book.get('source_notice_only'):
                        require(not excluded and book.get('notice'), 'source notice requires existing physical token and complete notice')
                        record.setdefault('exam_usage_policy', {}).setdefault('source_notices', []).append({
                            'occurrence_id': oid, 'notice': deepcopy(book['notice']), 'decision': deepcopy(decision)})
                        continue
                    if action in {'exclude_nonlexical', 'rehome'}:
                        if not excluded:
                            record['occurrences'].remove(row)
                        ledgers[key]['excluded'].append({'occurrence_id': oid, 'occurrence': deepcopy(old),
                            'already_excluded': excluded, 'exclusion_kind': 'reviewed_rehome' if action == 'rehome' else 'nonlexical', 'authority': deepcopy(decision)})
                        record.setdefault('exam_usage_policy', {}).setdefault('residual_ownership_decisions', []).append(deepcopy(entry))
                        if action == 'rehome':
                            target = book.get('target')
                            if target:
                                tkey = get(db, key[0], target['card_id'], target['snapshot_id'])
                                require(target.get('book_id', key[0]) == key[0], 'ownership destination belongs to another book')
                                target_record, target_parent = producers[tkey], parents[tkey]
                                scope = target.get('lexical_scope')
                                if scope:
                                    require(scope.get('kind') == 'native_phrase' and scope.get('card_lemma', '').casefold() == target_parent['word'].casefold()
                                            and scope.get('complete_lemma', '').casefold() == decision['actual_lemma'].casefold()
                                            and scope.get('native_scope_evidence') and target.get('replace_occurrence_id'), 'unverified base-card native phrase bridge')
                                else:
                                    require(target_parent['word'].casefold() == decision['actual_lemma'].casefold(), 'wrong actual destination lemma')
                                dest = deepcopy(old)
                                dest['target_range'] = _lexical_span(old, decision['actual_lemma'], target['target_range'], book, watched)
                                if dest['target_range'] != old['target_range']:
                                    require('translation_ranges' in target, 'expanded lexical target needs its reviewed Chinese ranges')
                                    dest['translation_ranges'] = target['translation_ranges']
                                dest.pop('display', None)  # A different lexical span cannot inherit the component display/mark.
                                dest.pop('ownership_history', None)
                                dest.pop('matching_proposal', None)
                                dest.pop('semantic_review', None)  # Old evidence belongs to the component OID and stays in full history.
                                dest.pop('pending_category', None)
                                companion = None
                                if target.get('replace_occurrence_id'):
                                    require(scope, 'companion replacement requires explicit native phrase scope')
                                    companion = next((r for r in target_parent['occurrences'] if r['occurrence_id'] == target['replace_occurrence_id']), None)
                                    require(companion is not None and digest(companion) == target['companion_source_row_sha256']
                                            and all(companion[k] == old[k] for k in ('paper_id', 'physical_source', 'english_hash', 'translation_hash'))
                                            and dest['target_range'][0] <= companion['target_range'][0] < companion['target_range'][1] <= dest['target_range'][1],
                                            'companion is not the exact counted component of this complete physical expression')
                                    to_remove = next((r for r in target_record['occurrences'] if r['occurrence_id'] == companion['occurrence_id']), None)
                                    require(to_remove is not None, 'companion already replaced by another operation')
                                    target_record['occurrences'].remove(to_remove)
                                if target.get('technical_decision'):
                                    _capture_pins(target['technical_decision'], watched)
                                    index = _append_native(target_record, target['technical_decision'], registry)
                                else:
                                    index = next((s['ordinal'] for s in target_parent['senses'] if s['sense_id'] == target.get('sense_id')), None)
                                require(index is not None, 'destination sense absent in this book')
                                dest.update(status='reviewed', sense_index=index, reason=decision['reason'], method='residual-optimization-rehome.v1', review_version='20261013')
                                dest = sf.seal_reviewed_assignment(target_record, dest)
                                actual = sf._occurrence(dest, sf._definition(target_record))
                                if scope:
                                    history = {'schema': 'residual-native-phrase-history.v1', 'source_book_id': key[0],
                                        'source_card_id': key[1], 'source_parent_snapshot_id': source_snapshot,
                                        'source_parent_row': deepcopy(old), 'source_parent_row_sha256': digest(old),
                                        'companion_card_id': tkey[1], 'companion_parent_snapshot_id': target_parent['snapshot_id'],
                                        'companion_parent_row': deepcopy(companion), 'companion_parent_row_sha256': digest(companion),
                                        'canonical_owner_card_id': tkey[1], 'canonical_occurrence_id': actual['occurrence_id'],
                                        'native_scope': deepcopy(scope), 'decision': deepcopy(decision), 'book_decision': deepcopy(book)}
                                    history['history_sha256'] = digest(history)
                                    dest['semantic_review'] = {'occurrence_id': actual['occurrence_id'], 'action': 'rehome',
                                        'reason': decision['reason'], 'residual_owner_history': history}
                                    ledgers[tkey].setdefault('companion_replacements', []).append(deepcopy(history))
                                    target_record.setdefault('exam_usage_policy', {}).setdefault('residual_native_phrase_owners', []).append(deepcopy(history))
                                # Parents were fully certified on load. A newly appended
                                # definition changes their semantic context seals; locating
                                # a physical row must not revalidate those interim seals.
                                # The final child pass rebinds and validates every row.
                                existing = next((r for r in target_record['occurrences'] if
                                    digest([r['paper_id'], r['physical_source'], r['target_range']]) == actual['occurrence_id']), None)
                                if existing:
                                    require(all(existing[k] == dest[k] for k in ('paper_id', 'physical_source', 'english_hash',
                                        'translation_hash', 'target_range')), 'existing destination physical proof differs')
                                else:
                                    target_record['occurrences'].append(dest)
                                if not scope:
                                    transfers.append((key, tkey, old, actual['occurrence_id'], deepcopy(decision), {**deepcopy(book), 'source_parent_snapshot_id': source_snapshot}))
                            else:
                                entity = _auxiliary_entity(decision, book, registry, watched)
                                payload = book.get('display_payload', {})
                                span = _lexical_span(old, entity['lemma'], book.get('target_range', payload.get('target_range')), book, watched)
                                chinese = book.get('translation_ranges', payload.get('target_translation_ranges'))
                                chinese_authority = 'reviewed_full_lexeme'
                                if chinese is None:
                                    chinese = _source_phrase_chinese_ranges(old, span)
                                    chinese_authority = 'source_full_lexeme_alignment' if chinese else 'source_full_lexeme_not_aligned'
                                require(isinstance(chinese, list), 'complete auxiliary Chinese target ranges required')
                                for bounds in chinese:
                                    sf._span(bounds, old['translation'])
                                auxiliary.append({'entity': deepcopy(entity), 'book_id': key[0], 'occurrence_id': sf._sha(sf._json([old['paper_id'], old['physical_source'], span])),
                                                  'target_range': span, 'translation_ranges': chinese,
                                                  'translation_range_authority': chinese_authority,
                                                  'source_card_id': key[1], 'source_parent_snapshot_id': source_snapshot,
                                                  'current_source_snapshot_id': parent['snapshot_id'],
                                                  'source_parent_row': deepcopy(old), 'decision': deepcopy(decision), 'book_decision': deepcopy(book)})
                    else:
                        require(not excluded, 'excluded source may only be classified or rehomed')
                        _meaning(record, parent, row, decision, book, registry, watched)
        for key, record in producers.items():
            _preflight_equivalences(record, parents[key])
        chunk_allowed = {x['file']: x['sha256'] for x in manifest['chunk_jobs']}
        for batch in request.get('chunks', []):
            require(chunk_allowed.get(batch['input']['file']) == batch['input']['sha256'], 'chunk input not sealed by work manifest')
            items, reviewed = read_json(batch['input']), read_json(batch['decisions'])
            reviewed = reviewed['decisions'] if isinstance(reviewed, dict) else reviewed
            _pins([batch['input'], batch['decisions']], watched)
            ids = {x['mapping_id'] for x in items}
            reviewed = [d for d in reviewed if d['mapping_id'] in ids]
            require(len(reviewed) == len(items) and {x['mapping_id'] for x in reviewed} == {x['mapping_id'] for x in items}, 'chunk coverage differs')
            for decision in reviewed:
                item = next(x for x in items if x['mapping_id'] == decision['mapping_id'])
                update = _display_update(decision, item, watched)
                did = item['display_id']
                if did in displays:
                    require(displays[did]['after'] == update['after'], 'conflicting full repairs for one display')
                else:
                    displays[did] = update
                matches = []
                # One indexed active-payload query for the explicitly supplied card bindings, never all payloads.
                refs = decision.get('book_refs', display_bindings.get(did))
                if not refs:
                    proof = request.get('inactive_displays', {}).get(did)
                    if proof is None and did in request.get('unused_display_ids', []):
                        proof = {'reason': 'No active instance; complete review retained', 'evidence_pins': [request['absence_proof']]}
                    require(proof and proof.get('reason') and refs == [], 'empty binding needs explicit pinned inactive-display proof')
                    _pins(proof['evidence_pins'], watched)
                    displays[did]['inactive'] = deepcopy(proof)
                    continue
                grouped_refs = {}
                for ref in refs:
                    grouped_refs.setdefault((ref['book_id'], ref['card_id'], ref['snapshot_id']), []).append(ref)
                for (bid, cid, sid), card_refs in grouped_refs.items():
                    key = (bid, cid)
                    if key in parents:
                        parent = parents[key]
                        require(parent['snapshot_id'] == sid, 'conflicting semantic/display parent')
                    elif key in presentation_cards:
                        parent = read_json(presentation_cards[key]['payload_file'])
                        require(parent['snapshot_id'] == sid, 'conflicting repeated display parent')
                    else:
                        require(spool is not None, 'chunk-only cards require a fresh readonly_spool to bound memory')
                        cached = cache_rows.get(key)
                        if cached:
                            active = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', key).fetchone()
                            require(active is not None and active['snapshot_id'] == sid == cached['snapshot_id'], 'source cache active parent differs')
                            pin = cached['payload_file']
                            parent = read_json(pin)
                            require((parent['book_id'], parent['card_id'], parent['snapshot_id']) == (*key, sid)
                                    and digest({k: v for k, v in parent.items() if k != 'snapshot_id'}) == sid,
                                    'source cache physical payload fingerprint differs')
                        else:
                            parent = _parent(db, key, sid)
                            path = spool / (digest(key) + '-physical.json')
                            raw = canonical(parent).encode()
                            with path.open('xb') as stream:
                                stream.write(raw)
                            pin = {'file': str(path), 'sha256': digest(raw)}
                        certified_cache[key] = {'book_id': bid, 'card_id': cid, 'snapshot_id': sid, 'payload_file': deepcopy(pin)}
                        _pins([pin], watched)
                        presentation_cards[key] = {'book_id': bid, 'card_id': cid, 'word': parent['word'],
                            'parent_snapshot_id': sid, 'child_snapshot_id': sid, 'parent_payload_sha256': digest(parent),
                            'child_payload_sha256': digest(parent), 'before_payload_file': pin, 'payload_file': pin,
                            'original_count': parent['expected_occurrences'], 'new_count': parent['expected_occurrences'], 'physical_updated': False,
                            'ledger': {'schema': 'residual-card-ledger.v1', 'book_id': bid, 'card_id': cid,
                                'parent_snapshot_id': sid, 'new_snapshot_id': sid, 'new_definitions': [], 'excluded': [],
                                'prior_wrong_lemma_ids': [], 'decisions': [], 'original_count': parent['expected_occurrences'],
                                'retained_count': parent['expected_occurrences']}}
                    for ref in card_refs:
                        row = next((r for r in parent['occurrences'] if r['occurrence_id'] == ref['occurrence_id']), None)
                        require(row and row.get('display') and row['display']['english'] == update['before']['english']
                                and row['display']['translation'] == update['before']['translation'], 'chunk physical display reference differs')
                        target = row['display']['target_range']
                        covered_before = any(a['zh'] and not (a['en'] == [0, len(row['display']['english'])] and a.get('note', '').startswith('整句对应'))
                                             and a['en'][0] <= target[0] < target[1] <= a['en'][1]
                                             for a in row['display']['alignment']['alignments'])
                        covered_after = any(a['zh'] and a['en'][0] <= target[0] < target[1] <= a['en'][1]
                                            for a in update['after']['alignment']['alignments'])
                        require(not covered_before or covered_after, 'chunk repair drops a previously aligned actual lexical target')
                        matches.append((key, ref['occurrence_id']))
                for key in {k for k, _ in matches}:
                    entry = {**deepcopy(update), 'occurrence_ids': sorted(o for k, o in matches if k == key)}
                    ledger = ledgers[key] if key in ledgers else presentation_cards[key]['ledger']
                    ledger.setdefault('residual_display_updates', []).append(entry)
                    ledger.setdefault('render_context', {}).setdefault('residual_display_updates', []).append(deepcopy(entry))
                displays[did]['book_refs'] = deepcopy(refs)
        children = {}
        for key, record in producers.items():
            record['expected_occurrences'] = len(record['occurrences'])
            # Definition append changes IDs/context fingerprints, never original semantic ordinals.
            original_senses = {s['sense_id']: s['ordinal'] for s in parents[key]['senses']}
            current = sf._definition(record)['senses']
            remap = {sid: current[index]['sense_id'] for sid, index in original_senses.items()}
            def rebound(value):
                if isinstance(value, list):
                    return [rebound(v) for v in value]
                if isinstance(value, dict):
                    return {k: rebound(v) for k, v in value.items()}
                return remap.get(value, value) if isinstance(value, str) else value
            for certificate in record.get('sense_group_equivalences', []):
                certificate.update(rebound(certificate))
            for row in record['occurrences']:
                for field in ('common_sense_match', 'broad_match', 'matching_proposal'):
                    if field in row:
                        row[field] = rebound(row[field])
            child = _physical_prepare(record, certified=parents[key], reseal=True)
            group_report(sf.report_from_record(child))
            children[key] = child
        for source_key, target_key, old, oid, decision, book in transfers:
            child = children[target_key]
            supporting.append(deepcopy(child))
            row = next(r for r in child['occurrences'] if r['occurrence_id'] == oid)
            sense = next(s for s in child['senses'] if s['sense_id'] == row['sense_id'])
            identity = {k: old[k] for k in ('paper_id', 'physical_source', 'sentence_id', 'english_hash', 'target_range', 'occurrence_id')}
            audit = {'exclusion_verified': True, 'decision_status': 'keep_exclusion', 'book_id': source_key[0], 'card_id': source_key[1],
                     'occurrence_id': old['occurrence_id'], 'source_identity': identity, 'reason': decision['reason'],
                     'targets': [{'card_id': target_key[1], 'occurrence_id': oid, 'verified_physical_match': True}]}
            transfer = {'book_id': source_key[0], 'source_card_id': source_key[1], 'source_word': parents[source_key]['word'],
                'source_parent_snapshot_id': book['source_parent_snapshot_id'], 'source_parent_row': old, 'source_identity': identity,
                'target_card_id': target_key[1], 'target_occurrence_id': oid, 'target_range': row['target_range'], 'verified_physical_match': True,
                'match_kind': book.get('match_kind', 'same_physical_exact_span' if row['target_range'] == old['target_range']
                                      else 'fixed_phrase_contains_exact_component_span'), 'target_reason': row['reason'],
                'exclusion_authority': {'source_parent_snapshot_id': book['source_parent_snapshot_id'], 'source_parent_row_sha256': digest(old), 'audit': audit},
                'matched_sense': {**sense, 'dictionary_source': child['definition_source'],
                                  'source_provenance': {'snapshot_id': child['snapshot_id'], 'definition_source': child['definition_source']}}}
            bound = bind_incoming_history(child, [transfer])
            require(len(bound.get('ownership_history_unresolved', [])) == len(child.get('ownership_history_unresolved', [])), 'native ownership API refused transfer')
            children[target_key] = _physical_prepare(policy.producer_record(bound, preserve_scope=False), certified=parents[target_key])
        entities, usages = _canonical_auxiliary(auxiliary)
        from .sense_display import _map_range
        for usage in usages:
            for update in displays.values():
                refs = update.get('book_refs', [])
                matched = [o for o in usage['origins'] if any(r['book_id'] == usage['book_id'] and
                           r['card_id'] == o['source_card_id'] and r['occurrence_id'] == o['source_parent_row']['occurrence_id'] for r in refs)]
                if not matched:
                    continue
                target = _map_range(usage['row']['english'], usage['row']['target_range'], update['after']['english'])
                require(target is not None, 'reassigned complete lexeme has no unique source-preserving completed display range')
                view = {'english': update['after']['english'], 'english_hash': update['after']['english_hash'],
                        'translation': update['after']['translation'], 'translation_hash': update['after']['translation_hash'],
                        'target_range': target, 'alignment': deepcopy(update['after']['alignment']),
                        'source_comparisons': deepcopy(update['after']['source_comparisons']),
                        'residual_display_update': deepcopy(update), 'physical_occurrence_id': usage['occurrence_id']}
                require(not usage.get('presentation') or usage['presentation'] == view, 'conflicting completed canonical owner presentations')
                usage['presentation'] = view
            usage['review_seal'] = digest({k: v for k, v in usage.items() if k != 'review_seal'})
        by_entity = {e['entity_id']: e for e in entities}
        for key, child in list(children.items()):
            related = [u for u in usages if u['book_id'] == key[0] and
                       any(o['source_card_id'] == key[1] for o in u['origins'])]
            if related:
                rendered = [{**deepcopy(u), 'entity': deepcopy(by_entity[u['entity_id']])} for u in related]
                record = policy.producer_record(child, preserve_scope=False)
                record.setdefault('exam_usage_policy', {})['residual_auxiliary_usages'] = rendered
                children[key] = _physical_prepare(record, certified=parents[key])
                ledgers[key].setdefault('render_context', {})['residual_auxiliary_usages'] = deepcopy(rendered)
        affected = []
        for key, child in children.items():
            parent = parents[key]
            ledger = ledgers[key]
            ledger.update(new_snapshot_id=child['snapshot_id'], retained_count=child['expected_occurrences'],
                          new_definitions=deepcopy([s for s in child['definition_provenance'].get('supplemental_definitions', {}).get('appended', [])
                                                   if s['ordinal'] >= len(parent['senses'])]))
            affected.append({'book_id': key[0], 'card_id': key[1], 'word': child['word'],
                'parent_snapshot_id': parent['snapshot_id'], 'parent_payload_sha256': digest(parent),
                'child_snapshot_id': child['snapshot_id'], 'child_payload_sha256': digest(child),
                'original_count': parent['expected_occurrences'], 'new_count': child['expected_occurrences'],
                'before_payload': parent, 'payload': child, 'ledger': ledger, 'physical_updated': True})
        affected.extend(presentation_cards.values())
        for card in affected:
            payload = _payload(card)
            retained = {r['occurrence_id'] for r in payload['occurrences']}
            for update in card['ledger'].get('residual_display_updates', []):
                moved = set(update['occurrence_ids']) - retained
                destinations = [{'entity_id': u['entity_id'], 'occurrence_id': u['occurrence_id'],
                                 'source_occurrence_id': o['source_parent_row']['occurrence_id']}
                                for u in usages if u['book_id'] == card['book_id'] for o in u['origins']
                                if o['source_card_id'] == card['card_id'] and o['source_parent_row']['occurrence_id'] in moved]
                require({x['source_occurrence_id'] for x in destinations} == moved,
                        'removed display target has no verified canonical owner; cannot silently drop projection')
                update['ownership_reassigned_occurrences'] = destinations
                update['occurrence_ids'] = sorted(set(update['occurrence_ids']) & retained)
                update.update(book_id=card['book_id'], card_id=card['card_id'],
                              parent_snapshot_id=card['parent_snapshot_id'], child_snapshot_id=card['child_snapshot_id'])
            if card['ledger'].get('residual_display_updates'):
                card['ledger'].setdefault('render_context', {})['residual_display_updates'] = deepcopy(card['ledger']['residual_display_updates'])
    require(stat_pin(source) == baseline['stat'], 'baseline changed during readonly preparation')
    require(all(stat_pin(p) == s for p, s in watched.stats.items()), 'unique verified source stat changed before plan closure')
    require(affected or auxiliary or displays, 'empty residual plan')
    child_ids = {(c['book_id'], c['card_id']): c['child_snapshot_id'] for c in affected}
    child_graph = [[b, c, child_ids.get((b, c), sid)] for b, c, sid in graph]
    plan = {'schema': PLAN, 'request': deepcopy(request), 'baseline': deepcopy(baseline), 'candidate': str(candidate),
            'active_graph_sha256': digest(graph), 'affected': sorted(affected, key=lambda x: (x['book_id'], x['card_id'])),
            'child_graph_sha256': digest(child_graph),
            'decisions': decisions, 'entities': entities, 'entity_usages': usages,
            'auxiliary': auxiliary, 'display_updates': list(displays.values()), 'source_files': watched,
            'source_stats': watched.stats, 'supporting_snapshots': supporting,
            'summary': {'cards': len(affected), 'actions': dict(Counter(d['action'] for d in decisions)),
                        'learning_cards_added': 0, 'physical_before': sum(c['original_count'] for c in affected),
                        'physical_after': sum(c['new_count'] for c in affected),
                        'auxiliary_entities': len(entities), 'auxiliary_physical_usages': len(usages),
                        'active_displays': sum(not d.get('inactive') for d in displays.values()),
                        'inactive_displays': sum(bool(d.get('inactive')) for d in displays.values())}}
    plan['run_id'] = digest(plan)
    return plan


def materialize(plan, output):
    """Export affected payloads once, without putting another copy in plan JSON."""
    require(plan['run_id'] == digest({k: v for k, v in plan.items() if k != 'run_id'}), 'plan changed before export')
    output = Path(output).resolve()
    require(not output.exists(), 'fresh immutable preparation directory required')
    root = Path(read_json(plan['request']['work_manifest'])['root']).resolve() / 'engineering/writer-own'
    require(output.is_relative_to(root), 'preparation artifacts must stay in writer-owned directory')
    output.mkdir(parents=True)
    created = []
    def write(name, value):
        path = output / name
        raw = canonical(value).encode()
        created.append(path)
        with path.open('xb') as f:
            f.write(raw)
            f.flush()
        return {'file': str(path), 'sha256': digest(raw)}
    try:
        wire = dict(plan)
        wire['source_files'] = dict(plan['source_files'])
        wire['affected'] = [dict(card) for card in plan['affected']]
        for c in wire['affected']:
            prefix = digest([c['book_id'], c['card_id']])
            if 'before_payload' in c:
                c['before_payload_file'] = write(prefix + '-before.json', c.pop('before_payload'))
            if 'payload' in c:
                c['payload_file'] = write(prefix + '-after.json', c.pop('payload'))
            c['ledger_file'] = write(prefix + '-ledger.json', c.pop('ledger'))
            for key in ('before_payload_file', 'payload_file', 'ledger_file'):
                pin = c[key]
                wire['source_files'][pin['file']] = pin['sha256']
        for field in ('entities', 'entity_usages'):
            pin = write(field + '.json', wire[field])
            wire[field + '_file'] = pin
            wire['source_files'][pin['file']] = pin['sha256']
        wire['run_id'] = digest({k: v for k, v in wire.items() if k != 'run_id'})
        pin = write('plan.json', wire)
        return {'plan': pin, 'run_id': wire['run_id'], 'affected': wire['affected'], 'summary': wire['summary']}
    except BaseException:
        for p in reversed(created):
            p.unlink(missing_ok=True)
        output.rmdir()
        raise


def _payload(card):
    return card['payload'] if 'payload' in card else read_json(card['payload_file'])


def _ledger(card):
    return card['ledger'] if 'ledger' in card else read_json(card['ledger_file'])


def _checkpoint(plan, candidate, *, already_applied=False):
    return {'schema': CHECKPOINT, 'run_id': plan['run_id'], 'already_applied': already_applied,
            'parent_database': plan['baseline'], 'database': {'file': str(candidate), 'stat': stat_pin(candidate)},
            'cards': [{k: v for k, v in c.items() if k not in {'payload', 'before_payload', 'ledger'}} for c in plan['affected']],
            'entities_file': plan.get('entities_file'), 'entity_usages_file': plan.get('entity_usages_file'),
            'summary': plan['summary']}


def _validate_plan(plan):
    require(plan.get('schema') == PLAN and plan.get('run_id') == digest({k: v for k, v in plan.items() if k != 'run_id'}), 'plan content seal differs')
    require(stat_pin(plan['baseline']['file']) == plan['baseline']['stat'], 'protected baseline changed')
    for file, sha in plan['source_files'].items():
        read_pin({'file': file, 'sha256': sha})
    source, candidate = Path(plan['baseline']['file']).resolve(strict=True), Path(plan['candidate']).resolve(strict=True)
    require(source != candidate and not source.samefile(candidate), 'refusing protected source/alias write')
    return candidate


def _insert(db, data):
    sid = data['snapshot_id']
    existing = db.execute('SELECT payload FROM snapshots WHERE id=?', (sid,)).fetchone()
    if existing:
        require(existing[0] == canonical(data), 'existing child snapshot bytes differ')
        return
    db.execute('INSERT INTO snapshots(id,book_id,card_id,word,definition_source,definition_provenance,expected_occurrences,created_at,payload) VALUES(?,?,?,?,?,?,?,?,?)',
               (sid, data['book_id'], data['card_id'], data['word'], data['definition_source'], canonical(data['definition_provenance']), data['expected_occurrences'], utc_now(), canonical(data)))
    for sense in data['senses']:
        db.execute('INSERT INTO senses VALUES(?,?,?,?,?)', (sid, sense['sense_id'], sense['ordinal'], sense['pos'], sense['text']))
    for row in data['occurrences']:
        db.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (sid, row['occurrence_id'], canonical(row['physical_source']), row['paper_id'], row['year'], row['sentence_id'], row['english'], row['english_hash'], row['translation'], row['translation_hash'],
             *row['target_range'], canonical(row['translation_ranges']), row['source'], canonical(row['source_provenance']), canonical(row['alignment']) if row['alignment'] is not None else None))
        db.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?,?,?,?,?)',
            (sid, row['occurrence_id'], row['sense_id'], row['status'], row['reason'], row['method'], row['review_version'], row['reviewed_sense_id'], row['assignment_context_hash'], canonical(row['matching_proposal']) if 'matching_proposal' in row else None))


def _reconcile(db, data):
    """Compare every normalized row in the changed snapshot, including real seals."""
    sid = data['snapshot_id']
    senses = [(sid, s['sense_id'], s['ordinal'], s['pos'], s['text']) for s in data['senses']]
    require([tuple(r) for r in db.execute('SELECT * FROM senses WHERE snapshot_id=? ORDER BY ordinal', (sid,))] == senses,
            'candidate sense rows/ordinals differ')
    occurrences, assignments = [], []
    for row in sorted(data['occurrences'], key=lambda r: r['occurrence_id']):
        occurrences.append((sid, row['occurrence_id'], canonical(row['physical_source']), row['paper_id'], row['year'], row['sentence_id'],
            row['english'], row['english_hash'], row['translation'], row['translation_hash'], *row['target_range'],
            canonical(row['translation_ranges']), row['source'], canonical(row['source_provenance']),
            canonical(row['alignment']) if row['alignment'] is not None else None))
        assignments.append((sid, row['occurrence_id'], row['sense_id'], row['status'], row['reason'], row['method'], row['review_version'],
            row['reviewed_sense_id'], row['assignment_context_hash'], canonical(row['matching_proposal']) if 'matching_proposal' in row else None))
    require(len(occurrences) == data['expected_occurrences'] and
            [tuple(r) for r in db.execute('SELECT * FROM occurrences WHERE snapshot_id=? ORDER BY occurrence_id', (sid,))] == occurrences,
            'candidate physical occurrence contents/count differ')
    require([tuple(r) for r in db.execute('SELECT * FROM assignments WHERE snapshot_id=? ORDER BY occurrence_id', (sid,))] == assignments,
            'candidate reviewed assignment contents/count differ')


def read_auxiliary_usages(database, *, book_id=None):
    """Read only active optimization owners; rolled-back audit rows stay intact."""
    with closing(_connect(database)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='residual_entity_usages'").fetchone():
            return []
        sql = ('SELECT u.payload FROM residual_entity_usages u JOIN residual_batches b ON b.run_id=u.run_id '
               "WHERE b.state='applied'")
        args = ()
        if book_id is not None:
            sql += ' AND u.book_id=?'
            args = (book_id,)
        result = [json.loads(r[0]) for r in db.execute(sql + ' ORDER BY u.book_id,u.entity_id,u.occurrence_id', args)]
        require(len({(r['book_id'], r['entity_id'], r['occurrence_id']) for r in result}) == len(result),
                'more than one active batch owns the same complete physical lexeme')
        return result


def apply(plan, *, root_write_approved=False, fail_after_cards=None):
    """ROOT-only transaction entry. Test fault injection never changes production defaults."""
    require(root_write_approved is True, 'ROOT candidate write approval required')
    candidate = _validate_plan(plan)
    with closing(_connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for sql in _DDL:
                db.execute(sql)
            existing = db.execute('SELECT state,plan_sha256 FROM residual_batches WHERE run_id=?', (plan['run_id'],)).fetchone()
            if existing and existing['state'] == 'applied':
                require(existing['plan_sha256'] == digest(plan), 'run already exists with different plan')
                require(digest(_graph(db)) == plan['child_graph_sha256'], 'already applied run active graph drifted')
                for c in plan['affected']:
                    require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (c['book_id'], c['card_id'])).fetchone()[0] == c['child_snapshot_id'], 'already applied run has stale active pointers')
                    _reconcile(db, _payload(c))
                db.rollback()
                return _checkpoint(plan, candidate, already_applied=True)
            require(digest(_graph(db)) == plan['active_graph_sha256'], 'candidate active graph differs from approved baseline clone')
            if plan['request']['candidate'].get('stat'):
                require(stat_pin(candidate) == plan['request']['candidate']['stat'], 'ROOT certified candidate clone stat drifted before first apply')
            loaded_parents = {}
            for c in plan['affected']:
                parent = _parent(db, (c['book_id'], c['card_id']), c['parent_snapshot_id'])
                if c.get('physical_updated', True):
                    loaded_parents[(c['book_id'], c['card_id'])] = parent
                require(digest(parent) == c['parent_payload_sha256'], 'candidate parent payload differs')
                data = _payload(c)
                require(digest(data) == c['child_payload_sha256'] and _physical_prepare(policy.producer_record(data), certified=parent) == data
                        and (data['book_id'], data['card_id'], data['snapshot_id']) == (c['book_id'], c['card_id'], c['child_snapshot_id']),
                        'child semantic/snapshot seal differs')
            db.execute('INSERT INTO residual_batches VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET state=excluded.state',
                       (plan['run_id'], digest(plan), 'applied', canonical(plan['baseline']), utc_now()))
            for supporting in plan.get('supporting_snapshots', []):
                parent = loaded_parents[(supporting['book_id'], supporting['card_id'])]
                require(_physical_prepare(policy.producer_record(supporting), certified=parent) == supporting, 'intermediate ownership snapshot seal differs')
                _insert(db, supporting)
                _reconcile(db, supporting)
            for n, c in enumerate(plan['affected'], 1):
                if c.get('physical_updated', True):
                    data = _payload(c)
                    _insert(db, data)
                    _reconcile(db, data)
                db.execute('INSERT OR REPLACE INTO residual_cards VALUES(?,?,?,?,?,?)',
                    (plan['run_id'], c['book_id'], c['card_id'], c['parent_snapshot_id'], c['child_snapshot_id'], canonical(_ledger(c))))
                if c.get('physical_updated', True):
                    db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',
                               (c['child_snapshot_id'], c['book_id'], c['card_id']))
                if fail_after_cards == n:
                    raise RuntimeError('injected transaction failure')
            for decision in plan['decisions']:
                db.execute('INSERT OR REPLACE INTO residual_decisions VALUES(?,?,?)', (plan['run_id'], digest([decision['word'], decision['id']]), canonical(decision)))
            for entity in plan['entities']:
                eid = entity['entity_id']
                old_entity = db.execute('SELECT payload FROM residual_entities WHERE entity_id=?', (eid,)).fetchone()
                require(not old_entity or old_entity[0] == canonical(entity), 'canonical entity identity already has conflicting evidence')
                db.execute('INSERT OR IGNORE INTO residual_entities VALUES(?,?,?)', (eid, entity['lemma'], canonical(entity)))
            for usage in plan['entity_usages']:
                require(usage['review_seal'] == digest({k: v for k, v in usage.items() if k != 'review_seal'})
                        and usage['history_sha256'] == digest(usage['origins']), 'auxiliary review/history seal differs')
                db.execute('INSERT OR REPLACE INTO residual_entity_usages VALUES(?,?,?,?,?)',
                    (plan['run_id'], usage['entity_id'], usage['book_id'], usage['occurrence_id'], canonical(usage)))
            for update in plan['display_updates']:
                db.execute('INSERT OR REPLACE INTO residual_display_updates VALUES(?,?,?)', (plan['run_id'], update['display_id'], canonical(update)))
            # SQLite FK enforcement validates each insertion; do not scan the 15GB baseline with a full FK sweep.
            expected = {(b, c): s for b, c, s in _graph(db)}
            require(len(expected) == len(_graph(db)), 'active card graph identity collision')
            for c in plan['affected']:
                require(expected[(c['book_id'], c['card_id'])] == c['child_snapshot_id'], 'activation differs')
            require(digest(_graph(db)) == plan['child_graph_sha256'], 'unrelated active pointers changed')
            for file, sha in plan['source_files'].items():
                read_pin({'file': file, 'sha256': sha})
            require(stat_pin(plan['baseline']['file']) == plan['baseline']['stat'], 'baseline changed before commit')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return _checkpoint(plan, candidate)


def rollback(plan, *, root_write_approved=False):
    """Reactivate complete immutable parents; keep the new snapshots and audit."""
    require(root_write_approved is True, 'ROOT candidate rollback approval required')
    candidate = _validate_plan(plan)
    with closing(_connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            batch = db.execute('SELECT state,plan_sha256 FROM residual_batches WHERE run_id=?', (plan['run_id'],)).fetchone()
            require(batch and batch['state'] == 'applied' and batch['plan_sha256'] == digest(plan), 'exact applied batch required')
            require(digest(_graph(db)) == plan['child_graph_sha256'], 'rollback would overwrite later active graph changes')
            for c in plan['affected']:
                current = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (c['book_id'], c['card_id'])).fetchone()
                require(current and current[0] == c['child_snapshot_id'], 'rollback would overwrite a later active snapshot')
            for c in plan['affected']:
                db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?', (c['parent_snapshot_id'], c['book_id'], c['card_id']))
            db.execute("UPDATE residual_batches SET state='rolled_back' WHERE run_id=?", (plan['run_id'],))
            require(digest(_graph(db)) == plan['active_graph_sha256'], 'rollback graph differs from original')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return {'schema': CHECKPOINT, 'run_id': plan['run_id'], 'rolled_back': True,
            'database': {'file': str(candidate), 'stat': stat_pin(candidate)}}
