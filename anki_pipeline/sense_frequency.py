"""Reviewed sense-to-physical-token links, stored separately from study progress.

This module validates and renders assignments; it never guesses a meaning from
whole-sentence keywords. Snapshots are immutable and can be reactivated without
altering the original wordbook, sentence corpus or Anki scheduling data.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3

from .store import backup_database, utc_now
from .study_source_identity import validate_source_identity, year_label
from .translation_alignment import validate_translation_alignment


SCHEMA = 'exam-sense-frequency.v2'
_SQL = '''
CREATE TABLE snapshots (
 id TEXT PRIMARY KEY, book_id TEXT NOT NULL, card_id TEXT NOT NULL, word TEXT NOT NULL,
 definition_source TEXT NOT NULL, definition_provenance TEXT NOT NULL,
 expected_occurrences INTEGER NOT NULL CHECK(expected_occurrences>=0),
 created_at TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(id,book_id,card_id));
CREATE TABLE active_snapshots (
 book_id TEXT NOT NULL, card_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 PRIMARY KEY(book_id,card_id),
 FOREIGN KEY(snapshot_id,book_id,card_id) REFERENCES snapshots(id,book_id,card_id));
CREATE TABLE senses (
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id), sense_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK(ordinal>=0), pos TEXT NOT NULL, text TEXT NOT NULL,
 PRIMARY KEY(snapshot_id,sense_id), UNIQUE(snapshot_id,ordinal));
CREATE TABLE occurrences (
 snapshot_id TEXT NOT NULL REFERENCES snapshots(id), occurrence_id TEXT NOT NULL,
 physical_source TEXT NOT NULL, paper_id TEXT NOT NULL, year INTEGER NOT NULL,
 sentence_id TEXT NOT NULL, english TEXT NOT NULL, english_hash TEXT NOT NULL,
 translation TEXT NOT NULL, translation_hash TEXT NOT NULL,
 target_start INTEGER NOT NULL, target_end INTEGER NOT NULL,
 translation_ranges TEXT NOT NULL, source TEXT NOT NULL, source_provenance TEXT NOT NULL,
 alignment_json TEXT,
 PRIMARY KEY(snapshot_id,occurrence_id), CHECK(target_start>=0 AND target_end>target_start));
CREATE TABLE assignments (
 snapshot_id TEXT NOT NULL, occurrence_id TEXT NOT NULL, sense_id TEXT,
 status TEXT NOT NULL CHECK(status IN ('reviewed','ambiguous','unmatched')),
 reason TEXT NOT NULL, method TEXT NOT NULL, review_version TEXT NOT NULL,
 reviewed_sense_id TEXT, assignment_context_hash TEXT, matching_proposal_json TEXT,
 PRIMARY KEY(snapshot_id,occurrence_id),
 FOREIGN KEY(snapshot_id,occurrence_id) REFERENCES occurrences(snapshot_id,occurrence_id),
 FOREIGN KEY(snapshot_id,sense_id) REFERENCES senses(snapshot_id,sense_id),
 CHECK((status='reviewed' AND sense_id IS NOT NULL AND reviewed_sense_id IS NOT NULL
        AND reviewed_sense_id=sense_id
        AND assignment_context_hash IS NOT NULL) OR
       (status<>'reviewed' AND sense_id IS NULL)));
CREATE INDEX assignment_senses ON assignments(snapshot_id,sense_id);
'''


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _text(value, label, *, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ValueError(f'{label} must be text')
    return value


def _span(value, text):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(n) is not int for n in value) or not 0 <= value[0] < value[1] <= len(text)):
        raise ValueError('invalid Unicode codepoint target range')
    return value


def _definition(record):
    if not isinstance(record, dict):
        raise ValueError('record must be an object')
    data = {key: _text(record.get(key), key) for key in
            ('book_id', 'card_id', 'word', 'definition_source')}
    data['definition_provenance'] = record.get('definition_provenance')
    if not isinstance(data['definition_provenance'], dict) or not data['definition_provenance']:
        raise ValueError('definition provenance is required')
    total = record.get('expected_occurrences')
    if type(total) is not int or total < 0:
        raise ValueError('expected occurrences must be a nonnegative integer')
    data['expected_occurrences'] = total
    senses = record.get('senses')
    if not isinstance(senses, list) or not senses:
        raise ValueError('sense list is required')
    data['senses'] = []
    for index, item in enumerate(senses):
        if not isinstance(item, dict):
            raise ValueError('sense must be an object')
        pos, text = _text(item.get('pos'), 'part of speech', empty=True), _text(item.get('text'), 'sense')
        key = _sha(_json([data['word'], data['definition_source'], index, pos, text,
                          data['definition_provenance']]))
        data['senses'].append({'sense_id': key, 'pos': pos, 'text': text, 'ordinal': index})
    data['definition_snapshot_id'] = _sha(_json({key: data[key] for key in (
        'word', 'definition_source', 'definition_provenance', 'senses')}))
    return data


def _assignment_context(data, row):
    # Display aliases share the same physical token; sentence_id is intentionally
    # absent. Every linguistic input used by the review is otherwise sealed.
    return _sha(_json({'schema': 'exam-sense-review-binding.v1',
        'book_id': data['book_id'], 'card_id': data['card_id'],
        'definition_snapshot_id': data['definition_snapshot_id'],
        **{key: row[key] for key in ('occurrence_id', 'english_hash', 'translation_hash',
           'target_range', 'translation_ranges', 'source_provenance', 'alignment',
           'alignment_evidence')}}))


def _occurrence(item, data, *, require_binding=True):
    if not isinstance(item, dict):
        raise ValueError('occurrence must be an object')
    row = {key: _text(item.get(key), key) for key in
           ('paper_id', 'sentence_id', 'english', 'english_hash', 'source',
            'status', 'reason', 'method', 'review_version')}
    row['translation'] = _text(item.get('translation'), 'translation', empty=True)
    row['translation_hash'] = _sha(row['translation'])
    if row['english_hash'] != _sha(row['english']):
        raise ValueError('stale source English hash')
    if 'translation_hash' in item and item['translation_hash'] != row['translation_hash']:
        raise ValueError('stale source translation hash')
    row['year'] = validate_source_identity(row['paper_id'], row['sentence_id'],
                                           item.get('source_provenance'))
    row['target_range'] = _span(item.get('target_range'), row['english'])
    row['translation_ranges'] = item.get('translation_ranges', [])
    if not isinstance(row['translation_ranges'], list):
        raise ValueError('translation ranges must be an array')
    for span in row['translation_ranges']: _span(span, row['translation'])
    row['physical_source'] = item.get('physical_source')
    if not isinstance(row['physical_source'], list) or not row['physical_source']:
        raise ValueError('physical source identity is required')
    row['source_provenance'] = item.get('source_provenance')
    if not isinstance(row['source_provenance'], dict) or not row['source_provenance']:
        raise ValueError('original source provenance is required')
    row['alignment'] = item.get('alignment', item.get('translation_alignment'))
    if (item.get('alignment') is not None and item.get('translation_alignment') is not None and
            item['alignment'] != item['translation_alignment']):
        raise ValueError('conflicting canonical and legacy alignment payloads')
    if row['alignment'] is not None:
        validate_translation_alignment(row['english'], row['translation'], row['alignment'])
    row['alignment_evidence'] = item.get('alignment_evidence', [])
    if not isinstance(row['alignment_evidence'], list):
        raise ValueError('alignment evidence must be an array')
    for evidence in row['alignment_evidence']:
        if not isinstance(evidence, dict): raise ValueError('alignment evidence must be an object')
        en = _span(evidence.get('english_range'), row['english'])
        ranges = evidence.get('translation_ranges')
        if not isinstance(ranges, list): raise ValueError('alignment evidence ranges must be an array')
        for span in ranges: _span(span, row['translation'])
        relation = evidence.get('relation', 'equivalent')
        if relation not in {'equivalent', 'implicit', 'untranslated'}:
            raise ValueError('alignment evidence relation is not supported')
        if ((relation == 'equivalent' and not ranges) or
                (relation != 'equivalent' and ranges)):
            raise ValueError('alignment evidence relation does not reconcile with its ranges')
        if row['alignment'] is not None and not any(
                part['en'] == en and part['zh'] == ranges and part['relation'] == relation
                for part in row['alignment']['alignments']):
            raise ValueError('alignment evidence does not match the canonical source')
    row['occurrence_id'] = _sha(_json([row['paper_id'], row['physical_source'], row['target_range']]))
    expected_context = _assignment_context(data, row)
    sense_index = item.get('sense_index')
    if row['status'] == 'reviewed':
        if type(sense_index) is not int or not 0 <= sense_index < len(data['senses']):
            raise ValueError('reviewed occurrence must refer to one declared sense')
        row['sense_id'] = data['senses'][sense_index]['sense_id']
        if require_binding and (item.get('reviewed_sense_id') != row['sense_id'] or
                item.get('assignment_context_hash') != expected_context):
            raise ValueError('stale or missing reviewed sense/context binding')
        row['reviewed_sense_id'] = row['sense_id']
        row['assignment_context_hash'] = expected_context
    elif row['status'] in {'ambiguous', 'unmatched'} and sense_index is None:
        row['sense_id'] = row['reviewed_sense_id'] = row['assignment_context_hash'] = None
        if item.get('reviewed_sense_id') is not None or item.get('assignment_context_hash') is not None:
            raise ValueError('unresolved occurrence cannot retain a reviewed binding')
    else:
        raise ValueError('unresolved occurrence cannot be assigned a sense')
    if item.get('display') is not None:
        from .sense_display import validate_display
        # Completed questions are presentation only. Counts and semantic review
        # bindings above remain tied to the exact physical source token.
        row['display'] = validate_display(item['display'],
            {**row, 'semantic_review': item.get('semantic_review')},
            data['definition_provenance'], ownership_context=data)
    if 'usage' in item:
        from .exam_usage import validate_usage
        row['usage'] = validate_usage(item['usage'])
    for key in ('broad_match', 'common_sense_match'):
        if key in item:
            from .sense_groups import validate_match_metadata
            row[key] = validate_match_metadata(item[key], data, common=key == 'common_sense_match')
    if 'pending_category' in item:
        if item['pending_category'] not in {'选项用法未明确', '义项未细分', '原文待核对', '缺少对应义项'}:
            raise ValueError('unknown pending classification')
        row['pending_category'] = item['pending_category']
    if 'semantic_review' in item:
        review = item['semantic_review']
        if not isinstance(review, dict) or review.get('occurrence_id') != row['occurrence_id']:
            raise ValueError('semantic evidence must bind to the physical occurrence')
        row['semantic_review'] = json.loads(_json(review))
    if 'ownership_history' in item:
        histories = item['ownership_history']
        if not isinstance(histories, list):
            raise ValueError('ownership history must be an array')
        from .ownership_history import _validate_row, validate_history_content
        for history in histories:
            validate_history_content(history)
            if (not isinstance(history, dict) or history.get('schema') != 'exam-usage-ownership-history.v1'
                    or history.get('book_id') != data['book_id'] or history.get('target_card_id') != data['card_id']
                    or history.get('target_occurrence_id') != row['occurrence_id']):
                raise ValueError('ownership history differs from its actual destination')
            original = history.get('source_parent_row')
            _validate_row(original)
            identity = _sha(_json([history['book_id'], history['source_card_id'],
                history['source_parent_snapshot_id'], original, history['exclusion_authority'],
                history['target_card_id'], history['target_occurrence_id']]))
            if history.get('history_id') != identity:
                raise ValueError('ownership history content fingerprint changed')
        row['ownership_history'] = json.loads(_json(histories))
    return row


def seal_reviewed_assignment(record, occurrence):
    """Bind an explicitly reviewed choice to its exact current context.

    The caller must first review the meaning and supply ``status='reviewed'``,
    one ``sense_index`` and its reason. This helper validates source integrity;
    it neither decides a meaning nor validates the reviewer's semantic judgment.
    It returns a copy and performs no writes.
    """
    data = _definition(record)
    if not isinstance(occurrence, dict) or occurrence.get('status') != 'reviewed':
        raise ValueError('only an explicitly reviewed assignment can be sealed')
    row = _occurrence(occurrence, data, require_binding=False)
    result = deepcopy(occurrence)
    result['reviewed_sense_id'] = row['reviewed_sense_id']
    result['assignment_context_hash'] = row['assignment_context_hash']
    return result


def _proposal(proposal, data, row, *, require_binding=True):
    if not isinstance(proposal, dict):
        raise ValueError('matching proposal must be an object')
    # JSON copies exclude executable objects and non-finite numbers. Suggestions
    # remain separate from status/sense_id and can never enter confirmed counts.
    proposal = json.loads(_json(proposal))
    if (proposal.get('schema') != 'exam-sense-proposal.v1' or
            proposal.get('automatic_confirmation') is not False or
            proposal.get('status') not in {'suggested', 'ambiguous', 'unmatched'}):
        raise ValueError('matching proposal cannot confirm a sense')
    for key in ('method', 'reason_code', 'reason'): _text(proposal.get(key), key)
    for key in ('english_hash', 'translation_hash'):
        if key in proposal and proposal[key] != row[key]:
            raise ValueError('stale matching proposal text hash')
    indices, candidates = proposal.get('candidate_sense_indices'), proposal.get('candidates')
    if not isinstance(indices, list) or not isinstance(candidates, list):
        raise ValueError('matching proposal candidates must be arrays')
    if (any(type(index) is not int or not 0 <= index < len(data['senses']) for index in indices)
            or len(indices) != len(set(indices)) or len(candidates) != len(indices)):
        raise ValueError('matching proposal has invalid sense candidates')
    if ((proposal['status'] == 'suggested' and len(indices) != 1) or
            (proposal['status'] == 'ambiguous' and len(indices) < 2) or
            (proposal['status'] == 'unmatched' and indices)):
        raise ValueError('matching proposal status does not reconcile with its candidates')
    for index, candidate in zip(indices, candidates):
        sense = data['senses'][index]
        if (not isinstance(candidate, dict) or candidate.get('sense_index') != index or
                candidate.get('sense_text') != sense['text'] or candidate.get('pos', '') != sense['pos']):
            raise ValueError('stale matching proposal definition')
        evidence = candidate.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError('matching proposal candidate needs evidence')
        for item in evidence:
            if not isinstance(item, dict): raise ValueError('proposal evidence must be an object')
            en = _span(item.get('english_range'), row['english'])
            zh = _span(item.get('translation_range'), row['translation'])
            if not en[0] <= row['target_range'][0] < row['target_range'][1] <= en[1]:
                raise ValueError('proposal evidence must cover its target')
            if zh not in row['translation_ranges']:
                raise ValueError('proposal evidence must belong to target translation ranges')
            if item.get('translation_text') != row['translation'][zh[0]:zh[1]]:
                raise ValueError('stale matching proposal evidence')
            atom = _text(item.get('gloss_atom'), 'gloss atom')
            gloss = _text(item.get('source_gloss'), 'source gloss')
            if atom not in item['translation_text'] or gloss not in sense['text']:
                raise ValueError('proposal evidence does not reconcile with its gloss')
    scope = proposal.get('alignment_scope')
    if candidates and scope is None:
        raise ValueError('matching candidates require a source alignment scope')
    if scope is not None:
        if not isinstance(scope, dict): raise ValueError('proposal alignment scope must be an object')
        en = _span(scope.get('english_range'), row['english'])
        if not en[0] <= row['target_range'][0] < row['target_range'][1] <= en[1]:
            raise ValueError('proposal scope must cover its target')
        ranges = scope.get('translation_ranges')
        if not isinstance(ranges, list): raise ValueError('proposal scope ranges must be an array')
        for span in ranges: _span(span, row['translation'])
        if any(span not in row['translation_ranges'] for span in ranges):
            raise ValueError('proposal scope translation ranges do not reconcile')
        evidence_scopes = [(part['en'], part['zh']) for part in row['alignment']['alignments']
                           if part['relation'] == 'equivalent'] if row['alignment'] else []
        evidence_scopes.extend((part['english_range'], part['translation_ranges'])
                               for part in row['alignment_evidence']
                               if part.get('relation', 'equivalent') == 'equivalent')
        if (en, scope['translation_ranges']) not in evidence_scopes:
            raise ValueError('proposal scope has no source alignment evidence')
        if any(item['english_range'] != en or item['translation_range'] not in ranges
               for candidate in candidates for item in candidate['evidence']):
            raise ValueError('proposal candidate evidence differs from its aligned scope')
    expected_context = _assignment_context(data, row)
    if require_binding and (proposal.get('definition_snapshot_id') != data['definition_snapshot_id'] or
            proposal.get('assignment_context_hash') != expected_context):
        raise ValueError('stale or missing matching proposal binding')
    proposal['definition_snapshot_id'] = data['definition_snapshot_id']
    proposal['assignment_context_hash'] = expected_context
    sense_ids = [data['senses'][index]['sense_id'] for index in indices]
    if require_binding and proposal.get('candidate_sense_ids') != sense_ids:
        raise ValueError('stale matching proposal sense identities')
    proposal['candidate_sense_ids'] = sense_ids
    proposal['english_hash'], proposal['translation_hash'] = row['english_hash'], row['translation_hash']
    return proposal


def seal_matching_proposal(record, occurrence, proposal):
    """Validate and fingerprint a non-confirming suggestion, without assigning it."""
    data = _definition(record)
    row = _occurrence(occurrence, data)
    return _proposal(proposal, data, row, require_binding=False)


def prepare_record(record):
    """Reject stale, contradictory or unreconciled records before any writes."""
    data = _definition(record)
    if 'ownership_history_unresolved' in record and not isinstance(record['ownership_history_unresolved'], list):
        raise ValueError('unbound ownership histories must remain a complete audit array')
    if 'candidate_scope' in record:
        from .sense_candidate_scope import validate_stored_scope
        # Keep the exact filtered source as well as normalized database rows.
        # The ledger reconstructs the original ordering and excluded records;
        # it cannot grant the live source authority required by the builder.
        data['candidate_scope'] = validate_stored_scope(record, record['candidate_scope'])
        data['candidate_source_record'] = deepcopy({key: value for key, value in record.items()
                                                    if key != 'candidate_scope'})
    rows = record.get('occurrences')
    if not isinstance(rows, list):
        raise ValueError('occurrences must be an array')
    unique = {}
    for item in rows:
        row = _occurrence(item, data)
        if 'matching_proposal' in item:
            row['matching_proposal'] = _proposal(item['matching_proposal'], data, row)
        previous = unique.get(row['occurrence_id'])
        if previous:
            # Aliased completion/option displays can use another sentence ID;
            # every other source value and assignment must still agree.
            if {k: v for k, v in row.items() if k != 'sentence_id'} != {
                    k: v for k, v in previous.items() if k != 'sentence_id'}:
                raise ValueError('conflicting physical occurrence or assignment')
        else:
            unique[row['occurrence_id']] = row
    if len(unique) != data['expected_occurrences']:
        raise ValueError('physical occurrences do not reconcile with the declared word frequency')
    data['occurrences'] = sorted(unique.values(), key=lambda row: row['occurrence_id'])
    for key in ('exam_usage_policy', 'sense_group_equivalences', 'ownership_history_unresolved'):
        if key in record:
            data[key] = json.loads(_json(record[key]))
    data['snapshot_id'] = _sha(_json(data))
    return data


def _connect(path, *, readonly=False):
    path = Path(path).resolve()
    db = sqlite3.connect(path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'), uri=True)
    try:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if readonly: db.execute('PRAGMA query_only=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] not in {1, 2} or db.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='active_snapshots'").fetchone()[0] != 1:
            raise ValueError('not a sense-frequency database')
    except BaseException:
        db.close()
        raise
    return db


def _migrate(db):
    """Migrate inside the same transaction as the activating batch.

    Old immutable snapshots retain their original JSON and identity. Existing
    assignments have no manufactured review fingerprint; only newly sealed
    records populate the new columns.
    """
    if db.execute('PRAGMA user_version').fetchone()[0] == 1:
        db.execute('ALTER TABLE occurrences ADD COLUMN alignment_json TEXT')
        db.execute('ALTER TABLE assignments ADD COLUMN reviewed_sense_id TEXT')
        db.execute('ALTER TABLE assignments ADD COLUMN assignment_context_hash TEXT')
        db.execute('ALTER TABLE assignments ADD COLUMN matching_proposal_json TEXT')
        db.execute('PRAGMA user_version=2')


def save_records(path, records, backups):
    """Atomically activate a validated batch; keep old snapshots and backups."""
    prepared = [prepare_record(record) for record in records]
    keys = [(r['book_id'], r['card_id']) for r in prepared]
    if len(set(keys)) != len(keys) or not prepared:
        raise ValueError('batch must contain unique book/card identities')
    path = Path(path).resolve()
    backup = None
    if path.exists():
        with closing(_connect(path, readonly=True)): pass
        backup = backup_database(path, backups, label='sense-frequency-before-write')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb'): pass
        try:
            with closing(sqlite3.connect(path)) as db:
                try:
                    db.executescript('BEGIN IMMEDIATE;\n' + _SQL + '\nPRAGMA user_version=2;\nCOMMIT;')
                except BaseException:
                    db.rollback()
                    raise
        except BaseException:
            path.unlink(missing_ok=True); raise
    with closing(_connect(path)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            _migrate(db)
            for data in prepared:
                sid = data['snapshot_id']
                if not db.execute('SELECT 1 FROM snapshots WHERE id=?', (sid,)).fetchone():
                    db.execute('INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?)',
                        (sid, data['book_id'], data['card_id'], data['word'], data['definition_source'],
                         _json(data['definition_provenance']), data['expected_occurrences'], utc_now(), _json(data)))
                    for sense in data['senses']:
                        db.execute('INSERT INTO senses VALUES(?,?,?,?,?)',
                                   (sid, sense['sense_id'], sense['ordinal'], sense['pos'], sense['text']))
                    for row in data['occurrences']:
                        db.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (sid, row['occurrence_id'], _json(row['physical_source']), row['paper_id'], row['year'],
                             row['sentence_id'], row['english'], row['english_hash'], row['translation'],
                             row['translation_hash'], *row['target_range'], _json(row['translation_ranges']),
                             row['source'], _json(row['source_provenance']),
                             _json(row['alignment']) if row['alignment'] is not None else None))
                        db.execute('INSERT INTO assignments VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (sid, row['occurrence_id'], row['sense_id'], row['status'], row['reason'],
                             row['method'], row['review_version'], row['reviewed_sense_id'],
                             row['assignment_context_hash'],
                             _json(row['matching_proposal']) if 'matching_proposal' in row else None))
                db.execute('INSERT INTO active_snapshots VALUES(?,?,?) ON CONFLICT(book_id,card_id) '
                           'DO UPDATE SET snapshot_id=excluded.snapshot_id', (data['book_id'], data['card_id'], sid))
            if db.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('sense foreign keys do not reconcile')
            db.commit()
        except BaseException:
            db.rollback(); raise
    return {'schema': SCHEMA, 'snapshots': [r['snapshot_id'] for r in prepared],
            'backup': str(backup) if backup else None}


def read_card(path, book_id, card_id):
    with closing(_connect(path, readonly=True)) as db:
        active = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',
                            (book_id, card_id)).fetchone()
        if not active: return None
        data = json.loads(db.execute('SELECT payload FROM snapshots WHERE id=?', (active[0],)).fetchone()[0])
    return report_from_record(data)


def report_from_record(data):
    """Project one already validated immutable payload without another DB read."""
    result = {'schema': SCHEMA, 'snapshot_id': data['snapshot_id'], 'word': data['word'],
              'book_id': data['book_id'], 'card_id': data['card_id'],
              'definition_provenance': data['definition_provenance'],
              'definition_snapshot_id': data.get('definition_snapshot_id'),
              'definition_source': data['definition_source'], 'total': data['expected_occurrences'],
              'senses': [], 'pending': [], 'pending_count': 0}
    if 'candidate_scope' in data:
        result['candidate_scope'] = deepcopy(data['candidate_scope'])
    for key in ('exam_usage_policy', 'sense_group_equivalences', 'ownership_history_unresolved'):
        if key in data: result[key] = deepcopy(data[key])
    for sense in data['senses']:
        rows = [row for row in data['occurrences'] if row['sense_id'] == sense['sense_id']]
        counts = Counter(row['year'] for row in rows)
        result['senses'].append({**sense, 'count': len(rows),
            'years': [{'year': year, 'count': counts[year]} for year in sorted(counts, reverse=True)],
            'occurrences': sorted(rows, key=lambda row: (-row['year'], row['sentence_id'], row['target_range']))})
    result['pending'] = [row for row in data['occurrences'] if row['sense_id'] is None]
    result['pending_count'] = len(result['pending'])
    return result


def _marked(text, spans):
    # Union overlapping alignment ranges before escaping the exact text.
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]: merged[-1][1] = max(end, merged[-1][1])
        else: merged.append([start, end])
    pieces, cursor = [], 0
    for start, end in merged:
        pieces += [html.escape(text[cursor:start]), '<mark>' + html.escape(text[start:end]) + '</mark>']
        cursor = end
    return ''.join(pieces) + html.escape(text[cursor:])


def _previews(rows, *, ownership_history_documents=None, ownership_pending_diagnostics=None,
              ownership_history_target_urls=None):
    from .sense_chunks import render_sentence_pair
    from .exam_usage import occurrence_markup
    from .ownership_history import render_ownership_history
    output = []
    for row in rows:
        review = row.get('semantic_review') or {}
        dictionary = review.get('dictionary_explanation') or {}
        explanation = ''
        if dictionary:
            source_name = dictionary.get('name') or dictionary.get('source', '')
            explanation = ('<details class="sf-dictionary-explanation"><summary>词典依据 · '
                + html.escape(str(source_name)) + '</summary><p>'
                + html.escape(str(dictionary.get('context_reason') or review.get('context_reason', '')))
                + '</p><p>' + html.escape(str(dictionary.get('grammatical_scope', '')))
                + '</p><p class="sf-native-definition">'
                + html.escape(str(dictionary.get('english_definition') or ''))
                + '</p><p class="sf-native-chinese">'
                + html.escape(str(dictionary.get('original_chinese') or ''))
                + '</p><p class="sf-source">'
                + html.escape(' · '.join(str(dictionary.get(key) or '') for key in ('name', 'version', 'exact_entry', 'sense')))
                + '</p></details>')
        source = row.get('display', {}).get('source', row['source'])
        output.append(f'<article class="sf-example" data-sf-year="{row["year"]}" '
            'data-sf-occurrence-id="' + html.escape(row['occurrence_id'], quote=True) + '">'
            '<p class="sf-source">' + html.escape(source) + '</p>'
            + occurrence_markup(row)
            + ('<p class="sf-reason">上下文仅能确认广义：' + html.escape(row['broad_match']['reason']) + '</p>' if 'broad_match' in row else '')
            + render_sentence_pair(row) +
            '<p class="sf-reason">义项依据：' + html.escape(row['reason']) + '</p>' + explanation
            + (render_ownership_history(row, link_map=ownership_history_target_urls,
                documents=ownership_history_documents,
                include_source_example=False) if row.get('ownership_history') else '')
            + _ownership_pending_notes(row, ownership_pending_diagnostics or []) + '</article>')
    return ''.join(output)


def _ownership_pending_notes(row, diagnostics):
    """Keep unbound evidence on its own sentence; never change occurrence counts."""
    from .ownership_history import _validate_row
    pieces = []
    for diagnostic in diagnostics:
        original = diagnostic.get('occurrence')
        _validate_row(original)
        identity = diagnostic.get('target_occurrence_id', original['occurrence_id'])
        if identity != row['occurrence_id']:
            continue
        reason = diagnostic.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('unbound ownership diagnostic needs its actual reason')
        pieces.append('<details class="sf-ownership-pending-note"><summary>本句归属仍待核</summary>'
            '<p class="sf-reason">' + html.escape(reason) + '</p>'
            '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：'
            + html.escape(original['reason']) + '</p><details><summary>完整原记录与来源证据</summary>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(_json(diagnostic))
            + '</pre></details></details>')
    return ''.join(pieces)


def render_report(report):
    if report.get('schema') != SCHEMA: raise ValueError('unknown sense frequency report')
    from .sense_groups import display_report
    ids = {sense['sense_id'] for sense in report['senses']}
    # Only replace top-level presentation fields. The grouping/rendering
    # helpers read nested evidence and create their own rows; copying the
    # complete immutable audit ledger for every dictionary component is costly.
    view = dict(report)
    view['sense_group_equivalences'] = [certificate for certificate in report.get('sense_group_equivalences', [])
        if certificate.get('member_sense_ids') and set(certificate['member_sense_ids']).issubset(ids)]
    report = display_report(view)
    documents = report.get('ownership_history_documents')
    target_urls = report.get('ownership_history_target_urls')
    diagnostics = report.get('ownership_pending_diagnostics', [])
    if not isinstance(diagnostics, list) or any(not isinstance(item, dict) for item in diagnostics):
        raise ValueError('ownership rendering diagnostics must be an array of records')
    from .ownership_history import _validate_row
    for item in diagnostics:
        _validate_row(item.get('occurrence'))
    pieces = ['<div class="sf-report" data-sense-frequency="v1" data-snapshot="'
              + html.escape(report['snapshot_id'], quote=True) + '">']
    total, pending = report['total'], report['pending_count']
    label = '已核对次数' if pending else '真题出现次数'
    pieces.append(f'<p class="sf-hint">{label} · 横条占该词总次数的比例 · 点击查看年份与原句</p>')
    for sense in report['senses']:
        count = sense['count']; width = count / total * 100 if total else 0
        content = ('<span class="sf-bar" aria-hidden="true" style="width:' + f'{width:.3f}' + '%"></span>'
            '<span class="sf-meaning"><span class="sf-pos">' + html.escape(sense['pos']) + '</span> '
            + html.escape(sense['text']) + '</span><span class="sf-count">' + str(count) + ' 次</span>')
        if not count:
            pieces.append('<div class="sf-row sf-empty">' + content + '</div>'); continue
        year_text = ''.join('<span class="sf-year-chip">' + year_label(row['year']) + '</span>'
                            for row in sense['years'])
        pieces.append('<details class="sf-sense"><summary class="sf-row">' + content
            + '</summary><div class="sf-panel">'
            + '<span class="sf-years" aria-label="出现年份">' + year_text + '</span>'
            '<div class="sf-filters" aria-label="按年份预览"><button type="button" '
            'data-sf-filter="all" aria-pressed="true">全部 ' + str(count) + '</button>'
            + ''.join(f'<button type="button" data-sf-filter="{r["year"]}" aria-pressed="false">'
                      f'{year_label(r["year"])} · {r["count"]}</button>' for r in sense['years'])
            + '</div><p class="sf-preview-count" role="status">显示 ' + str(count) + ' 处原文</p>'
            + _previews(sense['occurrences'], ownership_history_documents=documents,
                ownership_pending_diagnostics=diagnostics,
                ownership_history_target_urls=target_urls) + '</div></details>')
    if pending:
        categories = {}
        for row in report['pending']:
            categories.setdefault(row.get('pending_category', '待核对'), []).append(row)
        for category, rows in categories.items():
            pieces.append(f'<details class="sf-pending"><summary>{category} {len(rows)} 次</summary>'
                          '<p class="sf-hint">以下记录尚未计入任何义项。</p>'
                          + _previews(rows, ownership_history_documents=documents,
                              ownership_pending_diagnostics=diagnostics,
                              ownership_history_target_urls=target_urls) + '</details>')
    retained_ids = {row['occurrence_id'] for sense in report['senses'] for row in sense['occurrences']}
    retained_ids.update(row['occurrence_id'] for row in report['pending'])
    archived = [item for item in diagnostics
                if item.get('target_occurrence_id', item['occurrence']['occurrence_id']) not in retained_ids]
    if archived:
        archived_rows = [item['occurrence'] for item in archived]
        pieces.append('<details class="sf-pending"><summary>待核对例句（不计本词频）</summary>'
            '<p class="sf-hint">原记录仍待确认归属，以下例句不进入本词或义项次数。</p>'
            + _previews(archived_rows, ownership_pending_diagnostics=[
                {**item, 'target_occurrence_id': item['occurrence']['occurrence_id']} for item in archived])
            + '</details>')
    if not total: pieces.append('<p class="sf-hint">当前真题语料中没有该词的出现记录。</p>')
    pieces.append('</div>')
    return ''.join(pieces)


def inject_report(page, definition_html, report):
    if not definition_html or page.count(definition_html) != 1:
        raise ValueError('sense insertion must identify exactly one original definition block')
    css = Path(__file__).with_name('templates').joinpath('sense-frequency.css').read_text()
    script = Path(__file__).with_name('templates').joinpath('sense-frequency.js').read_text()
    block = '<!--sense-frequency:start-->' + render_report(report) + '<!--sense-frequency:end-->'
    page = page.replace(definition_html, block, 1)
    return page.replace('</head>', '<style data-sense-frequency-style>' + css + '</style></head>', 1).replace(
        '</body>', '<script data-sense-frequency-script>' + script + '</script></body>', 1)


def remove_report(page, original):
    """Inverse used by build audits to prove every unrelated byte is preserved."""
    page = re.sub(r'<!--sense-frequency:start-->.*?<!--sense-frequency:end-->', lambda _: original, page, flags=re.S)
    page = re.sub(r'<style data-sense-frequency-style>.*?</style>', '', page, flags=re.S)
    return re.sub(r'<script data-sense-frequency-script>.*?</script>', '', page, flags=re.S)
