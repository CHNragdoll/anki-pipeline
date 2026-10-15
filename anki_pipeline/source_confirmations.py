"""Five explicitly reviewed source confirmations, as reversible new snapshots.

This is a narrow correction lane. It does not weaken the residual writer's
certified-copy rules, rewrite historical snapshots, or access study progress.
Complete immutable parents are the recovery store and are exported before use.
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

from . import sense_frequency as sf
from . import residual_optimization as ro
from . import exam_usage_policy as policy
from .store import utc_now

REQUEST = 'five-source-confirmations-request.v1'
PLAN = 'five-source-confirmations-plan.v1'
RECEIPT = 'five-source-confirmations-receipt.v1'
CORRECTIONS = {
    'number': {'sentence_id': 'kaoyan:2017-02:p:b-11-3:new:0', 'old_phrase': 'number items',
        'new_phrase': 'numbered items', 'offset': 52, 'insert': 'ed',
        'old_hash': '7d96ad884702cdd176c0181a95a7d4954bdf5dab34b44cb9ec8b54dbc1b3899b',
        'new_hash': 'e575ad6ecfb749816d4c40ab879217a926c9794cf5150d3084f6a0daa7fb8669'},
    'jug': {'sentence_id': 'kaoyan:2001-01:p:b-11-4:0', 'old_phrase': 'jugging your life',
        'new_phrase': 'juggling your life', 'offset': 172, 'insert': 'l',
        'old_hash': '0c549705a28d2b80683cbfdf9e06e35849f65c4d8aa24bbc8f61df9db50da2ca',
        'new_hash': '8ce832e70f359fc3798fa8051a702c35b6cdeb54c3e1ae93a3bc17e10ed706e2'},
}
SOURCE_IDS = {
    'remote': '0737f3946519137ae600ddf2bf7e5d91bf08fcbb1e19708ade9d9884ca588d63',
    'pick': '14e6e7b432b56d9c4cf07fc6cf6b02498aa3d10cd849c327828b38bb71df0307',
    'as': '1d1712e52c6b4347ea86a146de5a699aef386a3016428d6e229ed5feb25f5546',
    'number': '32180affdd27f964e17c839abe725d17d6785c97f50d0881a469fba2b3f6787c',
    'jug': 'eae64cd295e10e1c6f8021f2aee5b55623be2424fe8c661912dc9ca24a391cb9',
}
NOTES = {
    'number': '用户已核对其他版本并确认 number items 漏 ed；本次派生校勘为 numbered items，number 的过去分词修饰 items，归入“标号；给…编号”。原句、原译及旧审查完整保留。',
    'jug': '用户已确认原位置应为 juggling your life；本次派生校勘补 l，并将同一物理位置从 jug 转归 juggle“同时应付；兼顾”。原句、全部旧转归依据及审查完整保留；该位置每本书仅计一次。',
    'remote': 'FT 对应文章（2024-01-03）原样使用 remote heat，来源字样已核实。此句 remote heat 指回收后输送给卡亚尼区域供暖网络的热量；LUMI 官方说明该热量来自设备余热。本条为整句短语的语境用法（非词典原义），不把 remote 单独释为“余热”，不补改来源英文。',
    'pick': 'IBTimes 对应文章（2014-07-15）原样使用 picked pace，来源字样已核实。此句 picked pace 表达演化速度加快；通常搭配为 pick up pace。本条为此短语的语境用法（非词典原义），不把“加速”冒充普通 pick 的词典原义，不补改来源英文。',
    'as': 'Psychology Today 对应文章（2023-06-19）原样使用 as convenient and provocative，来源字样已核实；不再标为本地解析漏词或待核原稿。整句说明 AI 虚拟试用体验便利且引人思考，但 as 的具体语法关系及唯一词典义仍未确定，保留本处明确不确定性。',
}
_DDL = (
    'CREATE TABLE IF NOT EXISTS source_confirmation_runs(run_id TEXT PRIMARY KEY,plan_sha256 TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS source_confirmation_cards(run_id TEXT NOT NULL REFERENCES source_confirmation_runs(run_id),book_id TEXT NOT NULL,card_id TEXT NOT NULL,parent_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),child_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),inverse_sha256 TEXT NOT NULL,PRIMARY KEY(run_id,book_id,card_id))',
)

canonical = ro.canonical
stat_pin = ro.stat_pin
require = ro.require


def digest(value):
    """Canonical SHA with bounded buffers and identical existing JSON bytes."""
    result = hashlib.sha256()
    if isinstance(value, bytes):
        result.update(value)
    else:
        for raw in _json_chunks(value):
            result.update(raw)
    return result.hexdigest()


def _json_chunks(value):
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    buffer = bytearray()
    for part in encoder.iterencode(value):
        buffer.extend(part.encode())
        if len(buffer) >= 65536:
            yield bytes(buffer)
            buffer.clear()
    if buffer:
        yield bytes(buffer)


def _producer(parent):
    """Share immutable old trees; only modified rows acquire new dictionaries."""
    result = dict(parent)
    result['senses'] = [{'pos': s['pos'], 'text': s['text']} for s in parent['senses']]
    indices = {s['sense_id']: s['ordinal'] for s in parent['senses']}
    result['occurrences'] = [{**row, 'sense_index': indices.get(row['sense_id'])} for row in parent['occurrences']]
    result['exam_usage_policy'] = dict(parent.get('exam_usage_policy', {}))
    if parent['word'] in {'remote', 'pick'}:
        result['definition_provenance'] = deepcopy(parent['definition_provenance'])
    return result


def _write_json(path, value, expected=None):
    checksum = hashlib.sha256()
    with Path(path).open('xb', buffering=1048576) as stream:
        for raw in _json_chunks(value):
            checksum.update(raw)
            stream.write(raw)
    claimed = checksum.hexdigest()
    require(expected is None or expected == claimed, 'exported complete payload seal differs')
    return {'file': str(Path(path).resolve()), 'sha256': claimed}


def _export_card(card, output, files):
    prefix = digest([card['book_id'], card['card_id']])
    for field, checksum in (('before_payload', 'before_payload_sha256'), ('payload', 'payload_sha256')):
        filename = prefix + ('-before.json' if field == 'before_payload' else '-after.json')
        pin = _write_json(output / filename, card[field], card[checksum])
        card[field + '_file'] = pin
        files[pin['file']] = pin['sha256']
        del card[field]


def _connect(path, *, write=False):
    path = Path(path).resolve(strict=True)
    require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
            'standalone committed database required')
    return ro._connect(path, write=write)


def _graph(db):
    return [list(row) for row in db.execute('SELECT book_id,card_id,snapshot_id FROM active_snapshots ORDER BY book_id,card_id')]


def _identity(data):
    require(data['snapshot_id'] == digest({key: value for key, value in data.items() if key != 'snapshot_id'}),
            'immutable payload seal differs')
    require(data['expected_occurrences'] == len(data['occurrences']), 'declared count differs')


def remap_range(span, offset, insertion):
    """An insertion belongs to a span ending at it, but not one starting there."""
    start, end = span
    size = len(insertion)
    return [start + (size if start >= offset else 0), end + (size if end >= offset else 0)]


def _remap_alignment(alignment, correction, english):
    result = deepcopy(alignment)
    if result is not None:
        result['englishHash'] = sf._sha(english)
        for chunk in result['alignments']:
            chunk['en'] = remap_range(chunk['en'], correction['offset'], correction['insert'])
    return result


def _history(row, key, evidence, canonical_decision=None):
    return {'schema': 'five-source-confirmation-row.v1', 'key': key,
        'authority': 'human-approved-source-correction' if key in CORRECTIONS else 'verified-original-article',
        'original_row': deepcopy(row), 'original_row_sha256': digest(row),
        'prior_canonical_decision': deepcopy(canonical_decision), 'evidence': deepcopy(evidence),
        'note': NOTES[key], 'physical_origin': deepcopy(row['physical_source']),
        'original_occurrence_id': row['occurrence_id']}


def _correct(row, key, revisions, evidence, decision):
    correction, meta = CORRECTIONS[key], revisions[key]
    require(row['sentence_id'] == correction['sentence_id'] and row['english_hash'] == correction['old_hash'],
            'source correction current English differs')
    english = row['english'][:correction['offset']] + correction['insert'] + row['english'][correction['offset']:]
    require(sf._sha(english) == correction['new_hash'] and correction['old_phrase'] in row['english']
            and correction['new_phrase'] in english, 'finite reviewed correction differs')
    original = deepcopy(row)
    result = deepcopy(row)
    result.pop('display', None)  # Historical v2 source-card seal never becomes authority for new text.
    # Old transfer seals bind the old target ID. The complete old history stays
    # in original_row and its inline disclosure; it cannot certify a new ID.
    result.pop('ownership_history', None)
    result['english'], result['english_hash'] = english, sf._sha(english)
    result['target_range'] = remap_range(row['target_range'], correction['offset'], correction['insert'])
    result['alignment'] = _remap_alignment(row['alignment'], correction, english)
    for chunk in result['alignment_evidence']:
        chunk['english_range'] = remap_range(chunk['english_range'], correction['offset'], correction['insert'])
    source = result['source_provenance']
    source['reviewedContentHash'], source['sourceHash'] = meta['reviewed_content_hash'], meta['source_hash']
    if 'paragraphRange' in source:
        source['paragraphRange'] = remap_range(source['paragraphRange'], correction['offset'], correction['insert'])
    path = source.get('sourcePathEvidence', {})
    if path:
        path['structuredPaperHash'] = meta['structured_paper_hash']
        for item in path.get('evidence', []):
            if 'reviewedContentHash' in item:
                item['reviewedContentHash'] = meta['reviewed_content_hash']
    source['source_confirmation'] = _history(original, key, evidence, decision)
    source['source_confirmation']['source_revision'] = deepcopy(meta)
    result['occurrence_id'] = digest([result['paper_id'], result['physical_source'], result['target_range']])
    if result.get('semantic_review'):
        result['semantic_review'] = {'occurrence_id': result['occurrence_id'],
            'action': 'source_confirmed_correction', 'reason': NOTES[key],
            'original_semantic_review': deepcopy(original['semantic_review'])}
    if 'matching_proposal' in result:
        # Retain the full old proposal as history; a stale suggestion cannot bind new text.
        result.pop('matching_proposal')
    result['assignment_context_hash'] = None
    if result['status'] == 'reviewed':
        result['reviewed_sense_id'] = None
    return result


def _migrate_metadata(row, key, revisions, evidence):
    """Later sentences keep their local linguistic inputs and migrate position."""
    correction, meta = CORRECTIONS[key], revisions[key]
    result = deepcopy(row)
    result.pop('display', None)
    source = result['source_provenance']
    source['sourceHash'] = meta['source_hash']
    source['paragraphRange'] = remap_range(source['paragraphRange'], correction['offset'], correction['insert'])
    path = source.get('sourcePathEvidence', {})
    if path:
        path['structuredPaperHash'] = meta['structured_paper_hash']
    history = _history(row, key, evidence)
    history['metadata_only'] = True
    history['note'] = ('同段落已按用户确认校正 ' + correction['old_phrase'] + ' → ' + correction['new_phrase']
        + '；本句英文、中文及句内区块不变，段落位置与来源 hash 同步更新。')
    history['source_revision'] = deepcopy(meta)
    source['source_confirmation'] = history
    return result


def _contextual(record, row, key, evidence, decision):
    phrase = 'remote heat' if key == 'remote' else 'picked pace'
    meaning = ('本句中指回收后用于卡亚尼区域供暖的热量（设备余热）' if key == 'remote'
               else '本句中表示演化速度加快；通常搭配 pick up pace')
    text = '语境用法（非词典原义） · ' + phrase + '：' + meaning
    english = ('In this sentence the phrase remote heat refers to recovered heat used for district heating; this is not an independent definition of remote.' if key == 'remote'
               else 'In this source sentence picked pace expresses an increase in the pace of evolution; the usual expression is pick up pace, not an independent dictionary sense of pick.')
    ordinal = len(record['senses'])
    record['senses'].append({'pos': 'adj.' if key == 'remote' else 'v.', 'text': text})
    addition = {'ordinal': ordinal, 'kind': 'contextual_usage', 'is_dictionary_native': False,
        'source_dictionary': 'contextual_review', 'source_name_zh': '来源核验 · 语境用法（非词典原义）',
        'source_name_original': 'Verified article context', 'source_version': '20261014',
        'source_headword': key, 'english': english, 'original_chinese': None,
        'translation_kind': 'contextual_review', 'translation_label': '短语语境释义',
        'contextual_key': digest([key, row['occurrence_id'], text, evidence]),
        'usage_scope': {'sentence_id': row['sentence_id'], 'phrase': phrase,
                        'independent_lexeme_meaning': False},
        'native_base_evidence': deepcopy(decision.get('dictionary_evidence', {})),
        'review_evidence': deepcopy(decision), 'source_pins': [deepcopy(evidence)]}
    record['definition_provenance'].setdefault('supplemental_definitions', {}).setdefault('appended', []).append(addition)
    return ordinal, addition


def _remap_ids(value, mapping):
    if isinstance(value, dict):
        return {key: _remap_ids(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_remap_ids(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def _seal(record, parent):
    """Validate new raw rows; copy v2 display only from the exact physical parent."""
    data = sf._definition(record)
    mapping = {sense['sense_id']: data['senses'][sense['ordinal']]['sense_id'] for sense in parent['senses']}
    originals = {row['occurrence_id']: row for row in parent['occurrences']}
    for name in ('sense_group_equivalences',):
        if name in record:
            record[name] = _remap_ids(record[name], mapping)
    rows = []
    for item in record['occurrences']:
        accepted = originals.get(item.get('occurrence_id'))
        if data['definition_snapshot_id'] == parent['definition_snapshot_id'] and accepted is not None:
            ordinal = next((s['ordinal'] for s in parent['senses'] if s['sense_id'] == accepted['sense_id']), None)
            if item == {**accepted, 'sense_index': ordinal}:
                rows.append(accepted)
                continue
        item = deepcopy(item)
        display = item.pop('display', None)
        for name in ('broad_match', 'common_sense_match'):
            if name in item:
                item[name] = _remap_ids(item[name], mapping)
        row = sf._occurrence(item, data, require_binding=False)
        if display is not None:
            accepted = originals.get(row['occurrence_id'])
            require(accepted is not None and display == accepted.get('display'), 'modified v2 display rejected')
            for name in ('english', 'translation', 'target_range', 'translation_ranges', 'physical_source',
                         'paper_id', 'source_provenance', 'alignment', 'alignment_evidence'):
                require(row[name] == accepted[name], 'certified display physical authority differs: ' + name)
            row['display'] = display
        if 'matching_proposal' in item:
            row['matching_proposal'] = sf._proposal(_remap_ids(item['matching_proposal'], mapping), data, row, require_binding=False)
        rows.append(row)
    require(len({row['occurrence_id'] for row in rows}) == len(rows) == data['expected_occurrences'],
            'corrected physical positions duplicate or count differs')
    data['occurrences'] = sorted(rows, key=lambda row: row['occurrence_id'])
    for name in ('exam_usage_policy', 'sense_group_equivalences', 'ownership_history_unresolved'):
        if name in record:
            data[name] = record[name]
    data['snapshot_id'] = digest(data)
    _identity(data)
    from .sense_groups import group_report
    # Full source/assignment checks ran for changed rows; old rows are exact
    # certified parents. Equivalence certificates are checked against all
    # current definition IDs without hashing thousands of unchanged sources.
    context = {**data, 'expected_occurrences': 0, 'occurrences': []}
    group_report(sf.report_from_record(context))
    return data


def _read_parent(db, book, card, sid):
    saved = db.execute('SELECT payload FROM snapshots WHERE id=? AND book_id=? AND card_id=?', (sid, book, card)).fetchone()
    require(saved is not None, 'immutable parent absent')
    data = json.loads(saved[0])
    require((data['book_id'], data['card_id'], data['snapshot_id']) == (book, card, sid), 'parent identity differs')
    _identity(data)
    ro._reconcile(db, data)
    return data


def prepare(request, *, progress=None, artifact_root=None):
    def report(stage, completed, total):
        if progress is not None:
            progress({'stage': stage, 'completed': completed, 'total': total})
    require(request.get('schema') == REQUEST, 'unsupported source confirmation request')
    candidate = Path(request['candidate']['file']).resolve(strict=True)
    protected = Path(request['protected']['file']).resolve(strict=True)
    require(candidate != protected and not candidate.samefile(protected), 'protected database/alias cannot be candidate')
    require(stat_pin(protected) == request['protected']['stat'], 'protected database changed')
    evidence = ro.read_json(request['evidence'])
    require(evidence.get('schema') == 'five-source-confirmations-evidence.v1', 'five-source evidence required')
    evidence_by_key = {item['key']: item for item in evidence['items']}
    for key, correction in CORRECTIONS.items():
        approval = evidence_by_key[key + '-human-confirmation']
        require(approval['authority'] == 'direct_user_confirmation_in_current_conversation'
                and approval['original'] == correction['old_phrase'] and approval['corrected'] == correction['new_phrase'],
                'finite source correction has no human authority')
    for key in ('remote', 'pick', 'as', 'remote-technical'):
        require(evidence_by_key[key].get('verified_in_current_conversation') is True, 'original article unverified')
    decisions = ro.read_json(request['canonical_decisions'])['decisions']
    decision_map = {item['id']: item for item in decisions}
    revisions = ro.read_json(request['source_revisions'])
    require(set(revisions) == set(CORRECTIONS), 'exact two source revisions required')
    for key, meta in revisions.items():
        require(meta['sentence_id'] == CORRECTIONS[key]['sentence_id'] and meta['english_hash'] == CORRECTIONS[key]['new_hash'], 'new source revision text differs')
        for name in ('english_hash', 'reviewed_content_hash', 'source_hash', 'structured_paper_hash'):
            require(re.fullmatch('[a-f0-9]{64}', meta[name]), 'new source hash invalid')
    with closing(_connect(candidate)) as db:
        graph = _graph(db)
        keys, words = {}, {}
        sql = ('SELECT x.book_id,x.card_id,x.snapshot_id,s.word FROM active_snapshots x '
            'CROSS JOIN occurrences o INDEXED BY sqlite_autoindex_occurrences_1 ON o.snapshot_id=x.snapshot_id '
            'JOIN snapshots s ON s.id=x.snapshot_id WHERE o.sentence_id LIKE ? OR o.sentence_id LIKE ? OR o.occurrence_id IN (?,?,?)')
        prefixes = [v['sentence_id'].rsplit(':', 1)[0] + ':%' for v in CORRECTIONS.values()]
        for book, card, sid, word in db.execute(sql, (*prefixes, *(SOURCE_IDS[k] for k in ('remote', 'pick', 'as')))):
            keys[(book, card)] = sid
            words[(book, card)] = word
        books = sorted({book for book, _ in keys})
        require(books == sorted(request['expected_books']), 'source confirmation book scope differs')
        for book in books:
            targets = db.execute('SELECT a.card_id,a.snapshot_id FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id WHERE a.book_id=? AND s.word=?', (book, 'juggle')).fetchall()
            require(len(targets) == 1, 'one existing juggle destination required')
            keys[(book, targets[0][0])] = targets[0][1]
            words[(book, targets[0][0])] = 'juggle'
        require(len(keys) == request['expected_cards'], 'affected card scope differs')

    artifacts = Path(artifact_root).resolve() if artifact_root is not None else None
    if artifacts is not None:
        require(not artifacts.exists(), 'fresh preparation output required')
        artifacts.mkdir(parents=True)
    moved, moved_seen, corrected_rows, metadata_rows, operations = {}, set(), 0, 0, []
    additions, cards, payload_files = {}, [], {}
    # Only the two tiny jug source cards are retained for forward rehoming.
    with closing(_connect(candidate)) as db:
        for key, sid in keys.items():
            if words[key] != 'jug':
                continue
            parent = _read_parent(db, *key, sid)
            original = next(row for row in parent['occurrences'] if row['occurrence_id'] == SOURCE_IDS['jug'])
            row = _correct(original, 'jug', revisions, request['evidence'], decision_map[SOURCE_IDS['jug']])
            row.update(status='reviewed', sense_index=1, reason=NOTES['jug'], method='source-confirmed-context-review.v1', review_version='20261014')
            row.pop('pending_category', None)
            history = row['source_provenance']['source_confirmation']
            history.update(prior_card_source_notices=deepcopy(parent.get('exam_usage_policy', {}).get('source_notices', [])),
                original_card_id=parent['card_id'], original_parent_snapshot_id=parent['snapshot_id'])
            moved[key[0]] = row
        require(set(moved) == set(books), 'wrong jug physical source missing')
        for n, (identity, sid) in enumerate(sorted(keys.items()), 1):
            parent = _read_parent(db, *identity, sid)
            parent_sha = digest(parent)
            record, changed = _producer(parent), []
            for index, original in enumerate(parent['occurrences']):
                row = record['occurrences'][index]
                correction_key = next((key for key, correction in CORRECTIONS.items() if original['sentence_id'] == correction['sentence_id']), None)
                paragraph_key = next((key for key, correction in CORRECTIONS.items() if original['sentence_id'].startswith(correction['sentence_id'].rsplit(':', 1)[0] + ':')), None)
                special_key = next((key for key, oid in SOURCE_IDS.items() if oid == original['occurrence_id'] and parent['word'] == key), None)
                if correction_key:
                    corrected_rows += 1
                    old_index = row.get('sense_index')
                    row = _correct(original, correction_key, revisions, request['evidence'], decision_map.get(original['occurrence_id']))
                    row['sense_index'] = old_index
                    if special_key == 'number':
                        require(len(record['senses']) > 9 and record['senses'][9]['pos'] == 'v.', 'existing numbering verb sense required')
                        row.update(status='reviewed', sense_index=9, reason=NOTES['number'], method='source-confirmed-context-review.v1', review_version='20261014')
                        row.pop('pending_category', None)
                    if special_key == 'jug':
                        require(identity[0] not in moved_seen, 'duplicate wrong jug physical source')
                        moved_seen.add(identity[0])
                        row.update(status='reviewed', sense_index=1, reason=NOTES['jug'], method='source-confirmed-context-review.v1', review_version='20261014')
                        row.pop('pending_category', None)
                        row['source_provenance']['source_confirmation']['prior_card_source_notices'] = deepcopy(parent.get('exam_usage_policy', {}).get('source_notices', []))
                        row['source_provenance']['source_confirmation']['original_card_id'] = parent['card_id']
                        row['source_provenance']['source_confirmation']['original_parent_snapshot_id'] = parent['snapshot_id']
                        moved[identity[0]] = row
                        record['expected_occurrences'] -= 1
                        continue
                elif paragraph_key:
                    metadata_rows += 1
                    old_index = row.get('sense_index')
                    row = _migrate_metadata(original, paragraph_key, revisions, request['evidence'])
                    row['sense_index'] = old_index
                if special_key in ('remote', 'pick', 'as'):
                    row['source_provenance'] = deepcopy(row['source_provenance'])
                    row['source_provenance']['source_confirmation'] = _history(original, special_key, request['evidence'], decision_map[original['occurrence_id']])
                    # Its unchanged v2 display has an old raw_context_hash; preserve it in history.
                    row.pop('display', None)
                    row['reason'], row['method'], row['review_version'] = NOTES[special_key], 'source-confirmed-context-review.v1', '20261014'
                    row['semantic_review'] = {'occurrence_id': original['occurrence_id'], 'action': 'contextual_usage' if special_key != 'as' else 'retain_specific_ambiguity',
                        'reason': NOTES[special_key], 'original_semantic_review': deepcopy(original.get('semantic_review')),
                        'source_evidence': deepcopy(evidence_by_key[special_key])}
                    if special_key == 'as':
                        row.update(status='ambiguous', sense_index=None, reviewed_sense_id=None, assignment_context_hash=None, pending_category='义项未细分')
                    else:
                        ordinal, addition = _contextual(record, original, special_key, request['evidence'], decision_map[original['occurrence_id']])
                        row.update(status='reviewed', sense_index=ordinal, reviewed_sense_id=None, assignment_context_hash=None)
                        row.pop('pending_category', None)
                        additions[identity] = [addition]
                changed.append(row)
                if special_key:
                    operations.append({'book_id': identity[0], 'card_id': identity[1], 'key': special_key,
                        'original_occurrence_id': original['occurrence_id'], 'occurrence_id': row['occurrence_id'],
                        'action': 'contextual_usage' if special_key in ('remote', 'pick') else 'source_verified_specific_ambiguity' if special_key == 'as' else 'correct_source_and_match_existing_sense'})
            record['occurrences'] = changed

            if parent['word'] == 'juggle':
                row = moved[identity[0]]
                require(len(record['senses']) > 1 and record['senses'][1]['pos'] == 'v.', 'juggle existing verb meaning required')
                matches = [r for r in record['occurrences'] if r['physical_source'] == row['physical_source'] and r['target_range'] == row['target_range']]
                require(len(matches) <= 1, 'duplicate destination physical position')
                if matches:
                    matches[0]['source_provenance'] = deepcopy(matches[0]['source_provenance'])
                    matches[0]['source_provenance']['source_confirmation'] = deepcopy(row['source_provenance']['source_confirmation'])
                else:
                    record['occurrences'].append(row)
                    record['expected_occurrences'] += 1
                operations.append({'book_id': identity[0], 'card_id': identity[1], 'key': 'jug', 'original_occurrence_id': SOURCE_IDS['jug'],
                    'occurrence_id': row['occurrence_id'], 'action': 'correct_source_and_rehome_once', 'deduplicated': bool(matches)})
            key = identity
            source_policy = record.setdefault('exam_usage_policy', {})
            # Prior notices are full historical evidence, never current prohibitions.
            old_notices = source_policy.pop('source_notices', [])
            source_policy['source_confirmation'] = {'schema': 'five-source-confirmation-card.v1',
                'parent_snapshot_id': parent['snapshot_id'], 'parent_payload_sha256': parent_sha,
                'prior_source_notices': old_notices, 'evidence': deepcopy(request['evidence']),
                'operations': [deepcopy(op) for op in operations if (op['book_id'], op['card_id']) == key]}
            # A changed sentence no longer uses an older display-only projection.
            updates = source_policy.get('residual_display_updates', [])
            if updates:
                corrected_english = {c['old_hash'] for c in CORRECTIONS.values()}
                retired = [u for u in updates if u.get('before', {}).get('english_hash') in corrected_english]
                source_policy['source_confirmation']['prior_display_updates'] = retired
                source_policy['residual_display_updates'] = [u for u in updates if u not in retired]
            child = _seal(record, parent)
            require([(s['ordinal'], s['pos'], s['text']) for s in child['senses'][:len(parent['senses'])]] == [(s['ordinal'], s['pos'], s['text']) for s in parent['senses']], 'original dictionary meanings changed')
            cards.append({'book_id': key[0], 'card_id': key[1], 'word': child['word'], 'parent_snapshot_id': parent['snapshot_id'],
                'child_snapshot_id': child['snapshot_id'], 'before_payload_sha256': parent_sha, 'payload_sha256': digest(child),
                'before_payload': parent, 'payload': child, 'original_count': parent['expected_occurrences'], 'new_count': child['expected_occurrences'],
                'new_definitions': additions.get(key, [])})
            if artifacts is not None:
                _export_card(cards[-1], artifacts, payload_files)
            if n % 10 == 0 or n == len(keys):
                report('exported_cards' if artifacts else 'seal_children', n, len(keys))

    require(moved_seen == set(books), 'wrong jug source processing scope differs')
    require(corrected_rows == request['expected_corrected_rows'], 'corrected source row scope differs')
    require(metadata_rows == request.get('expected_metadata_rows', 0), 'later paragraph metadata row scope differs')
    for book in books:
        require(sum(c['original_count'] for c in cards if c['book_id'] == book) == sum(c['new_count'] for c in cards if c['book_id'] == book), 'physical positions inflated or lost')
    files = {pin['file']: pin['sha256'] for pin in (request['evidence'], request['canonical_decisions'], request['source_revisions'])}
    for module in (__file__, sf.__file__, ro.__file__, policy.__file__):
        files[str(Path(module).resolve())] = digest(Path(module).read_bytes())
    result = {'schema': PLAN, 'request': deepcopy(request), 'protected': deepcopy(request['protected']),
        'candidate': str(candidate), 'candidate_stat': stat_pin(candidate), 'active_graph_sha256': digest(graph),
        'cards': cards, 'summary': {'cards': len(cards), 'corrected_rows': corrected_rows, 'metadata_only_rows': metadata_rows,
            'operations': operations, 'physical_count_delta': 0, 'original_sources_modified': False,
            'study_progress_modified': False, 'as_unique_sense_resolved': False},
        'source_files': files}
    result['source_files'].update(payload_files)
    result['run_id'] = digest(result)
    report('prepared_in_memory', len(cards), len(cards))
    return result


def _payload(card, before=False):
    field = 'before_payload' if before else 'payload'
    return card[field] if field in card else ro.read_json(card[field + '_file'])


def materialize(plan, output):
    require(plan['run_id'] == digest({key: value for key, value in plan.items() if key != 'run_id'}), 'plan seal differs')
    output = Path(output).resolve()
    if all('payload_file' in card and 'before_payload_file' in card for card in plan['cards']):
        require(output.is_dir() and not (output / 'plan.json').exists(), 'fresh streamed plan file required')
        pin = _write_json(output / 'plan.json', plan)
        return {'plan': pin, 'run_id': plan['run_id'], 'summary': plan['summary']}
    require(not output.exists(), 'fresh preparation output required')
    output.mkdir(parents=True)
    wire = {**plan, 'cards': [dict(card) for card in plan['cards']], 'source_files': dict(plan['source_files'])}
    for card in wire['cards']:
        _export_card(card, output, wire['source_files'])
    wire['run_id'] = digest({key: value for key, value in wire.items() if key != 'run_id'})
    p = output / 'plan.json'
    pin = _write_json(p, wire)
    return {'plan': pin, 'run_id': wire['run_id'], 'summary': wire['summary']}


def _validate(plan):
    require(plan.get('schema') == PLAN and plan['run_id'] == digest({key: value for key, value in plan.items() if key != 'run_id'}), 'plan seal differs')
    protected, candidate = Path(plan['protected']['file']).resolve(strict=True), Path(plan['candidate']).resolve(strict=True)
    require(candidate != protected and not candidate.samefile(protected), 'refusing protected source/alias write')
    require(stat_pin(protected) == plan['protected']['stat'], 'protected database changed')
    for file, sha in plan['source_files'].items():
        ro.read_pin({'file': file, 'sha256': sha})
    for card in plan['cards']:
        before, after = _payload(card, True), _payload(card)
        require(digest(before) == card['before_payload_sha256'] and digest(after) == card['payload_sha256'], 'full payload seal differs')
        _identity(before); _identity(after)
        _validate_child(before, after)
    return candidate


def _validate_child(before, after):
    """Reuse exact immutable parent rows; revalidate every changed linguistic row.

    The parent export, its complete SHA, canonical snapshot identity and live
    normalized SQL rows are separately guarded. A row may reuse that evidence
    only when its full normalized value and definition binding are identical.
    New or changed rows always pass the existing source/assignment validators.
    """
    data = sf._definition(after)
    require(all(before[name] == after[name] for name in ('book_id', 'card_id', 'word', 'definition_source')),
            'child card scope identity differs')
    require(data['senses'] == after['senses'] and data['definition_snapshot_id'] == after['definition_snapshot_id'],
            'child definition seal differs')
    same_definition = before['definition_snapshot_id'] == after['definition_snapshot_id']
    if not same_definition:
        require(after['word'] in {'remote', 'pick'} and len(after['senses']) == len(before['senses']) + 1,
                'unrelated definition content change')
        require([(s['ordinal'], s['pos'], s['text']) for s in after['senses'][:-1]] ==
                [(s['ordinal'], s['pos'], s['text']) for s in before['senses']], 'original definition content changed')
        old_prov, new_prov = before['definition_provenance'], after['definition_provenance']
        require({k: v for k, v in old_prov.items() if k != 'supplemental_definitions'} ==
                {k: v for k, v in new_prov.items() if k != 'supplemental_definitions'}, 'definition provenance changed')
        old_supp, new_supp = old_prov.get('supplemental_definitions', {}), new_prov['supplemental_definitions']
        require({k: v for k, v in old_supp.items() if k != 'appended'} == {k: v for k, v in new_supp.items() if k != 'appended'}
                and new_supp['appended'][:-1] == old_supp.get('appended', []), 'old supplemental definition content changed')
        addition = new_supp['appended'][-1]
        require(addition['ordinal'] == len(before['senses']) and addition['kind'] == 'contextual_usage'
                and addition['is_dictionary_native'] is False and addition['source_headword'] == after['word']
                and addition['usage_scope']['independent_lexeme_meaning'] is False, 'contextual definition scope differs')
    originals = {row['occurrence_id']: row for row in before['occurrences']}
    ordinals = {sense['sense_id']: sense['ordinal'] for sense in after['senses']}
    mapping = {sense['sense_id']: data['senses'][sense['ordinal']]['sense_id'] for sense in before['senses']}
    require(len({row['occurrence_id'] for row in after['occurrences']}) == after['expected_occurrences'],
            'child physical occurrence count differs')
    for row in after['occurrences']:
        original = originals.get(row['occurrence_id'])
        if same_definition and original == row:
            continue
        history = row['source_provenance'].get('source_confirmation')
        if history:
            _validate_correction_scope(before, after, row, originals, history)
        else:
            require(not same_definition and original is not None, 'unrelated row changed outside source correction scope')
            expected = deepcopy(original)
            for field in ('sense_id', 'reviewed_sense_id'):
                expected[field] = mapping.get(expected[field], expected[field])
            expected['assignment_context_hash'] = row['assignment_context_hash']
            for field in ('common_sense_match', 'broad_match'):
                if field in expected:
                    expected[field] = _remap_ids(expected[field], mapping)
            if 'matching_proposal' in expected:
                proposal = _remap_ids(expected['matching_proposal'], mapping)
                proposal['definition_snapshot_id'] = data['definition_snapshot_id']
                proposal['assignment_context_hash'] = row['matching_proposal']['assignment_context_hash']
                expected['matching_proposal'] = proposal
            require(expected == row, 'unrelated contextual-card row changed beyond definition rebinding')
        item = deepcopy(row)
        item['sense_index'] = ordinals[row['sense_id']] if row['status'] == 'reviewed' else None
        display = item.pop('display', None)
        checked = sf._occurrence(item, data)
        if display is not None:
            require(original is not None and original.get('display') == display,
                    'new or modified v2 display cannot reuse a parent seal')
            for name in ('english', 'translation', 'target_range', 'translation_ranges', 'physical_source',
                         'paper_id', 'source_provenance', 'alignment', 'alignment_evidence'):
                require(checked[name] == original[name], 'certified display authority changed: ' + name)
            checked['display'] = display
        if 'matching_proposal' in item:
            checked['matching_proposal'] = sf._proposal(item['matching_proposal'], data, checked)
        require(checked == row, 'child changed-row normalization seal differs')


def _validate_correction_scope(before, after, row, originals, history):
    require(history.get('schema') == 'five-source-confirmation-row.v1' and history.get('key') in NOTES,
            'unknown source correction scope')
    old = history['original_row']
    require(digest(old) == history['original_row_sha256'] and old['occurrence_id'] == history['original_occurrence_id'],
            'complete source correction parent row seal differs')
    local = originals.get(old['occurrence_id'])
    incoming = local is None
    require(local == old or (incoming and after['word'] == 'juggle' and history['key'] == 'jug'
            and old['occurrence_id'] == SOURCE_IDS['jug'] and history.get('original_card_id')
            and history.get('original_parent_snapshot_id')), 'source correction original row is outside pinned parent scope')
    require(row['physical_source'] == old['physical_source'] and row['sentence_id'] == old['sentence_id']
            and row['translation'] == old['translation'] and row['translation_hash'] == old['translation_hash']
            and row['translation_ranges'] == old['translation_ranges'], 'source correction changed physical origin or Chinese')
    key = history['key']
    if key in CORRECTIONS:
        correction = CORRECTIONS[key]
        require(old['sentence_id'].startswith(correction['sentence_id'].rsplit(':', 1)[0] + ':'),
                'source correction paragraph scope differs')
        if history.get('metadata_only'):
            require(row['english'] == old['english'] and row['english_hash'] == old['english_hash']
                    and row['target_range'] == old['target_range'] and row['alignment'] == old['alignment']
                    and row['alignment_evidence'] == old['alignment_evidence'], 'metadata-only scope changed sentence text/chunks')
            for field in ('status', 'sense_id', 'reviewed_sense_id', 'reason', 'method', 'review_version',
                          'pending_category', 'semantic_review', 'broad_match', 'common_sense_match', 'usage', 'ownership_history'):
                require(row.get(field) == old.get(field), 'metadata-only scope changed semantic field: ' + field)
        else:
            require(old['english_hash'] == correction['old_hash'] and row['english_hash'] == correction['new_hash'],
                    'source correction English hash differs')
            expected_english = old['english'][:correction['offset']] + correction['insert'] + old['english'][correction['offset']:]
            require(row['english'] == expected_english and row['target_range'] == remap_range(old['target_range'], correction['offset'], correction['insert'])
                    and row['alignment'] == _remap_alignment(old['alignment'], correction, expected_english),
                    'source correction English/target/chunk scope differs')
    else:
        require(before['word'] == key and old['occurrence_id'] == SOURCE_IDS[key]
                and all(row[field] == old[field] for field in ('english', 'english_hash', 'target_range', 'alignment', 'alignment_evidence')),
                'verified-source phrase scope differs')


def _receipt(plan, *, already=False, rollback=False):
    return {'schema': RECEIPT, 'run_id': plan['run_id'], 'database': {'file': plan['candidate'], 'stat': stat_pin(plan['candidate'])},
        'already_applied': already if not rollback else False, 'already_rolled_back': already if rollback else False,
        'state': 'rolled_back' if rollback else 'applied', 'summary': deepcopy(plan['summary']),
        'cards': [{key: value for key, value in c.items() if key not in ('payload', 'before_payload')} for c in plan['cards']]}


def apply(plan, *, root_write_approved=False, fail_after_cards=None):
    require(root_write_approved is True, 'explicit root write approval required')
    candidate = _validate(plan)
    with closing(_connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for ddl in _DDL:
                db.execute(ddl)
            previous = db.execute('SELECT plan_sha256,state FROM source_confirmation_runs WHERE run_id=?', (plan['run_id'],)).fetchone()
            if previous:
                require(tuple(previous) == (digest(plan), 'applied'), 'existing run state or plan differs')
                for c in plan['cards']:
                    require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (c['book_id'], c['card_id'])).fetchone()[0] == c['child_snapshot_id'], 'already applied pointers stale')
                    ro._reconcile(db, _payload(c))
                db.rollback()
                return _receipt(plan, already=True)
            require(stat_pin(candidate) == plan['candidate_stat'] and digest(_graph(db)) == plan['active_graph_sha256'], 'candidate identity/active graph changed')
            db.execute('INSERT INTO source_confirmation_runs VALUES(?,?,?,?)', (plan['run_id'], digest(plan), 'applied', utc_now()))
            for n, c in enumerate(plan['cards'], 1):
                parent = _read_parent(db, c['book_id'], c['card_id'], c['parent_snapshot_id'])
                require(parent == _payload(c, True), 'current parent payload differs')
                child = _payload(c)
                ro._insert(db, child); ro._reconcile(db, child)
                db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=? AND snapshot_id=?',
                    (c['child_snapshot_id'], c['book_id'], c['card_id'], c['parent_snapshot_id']))
                require(db.execute('SELECT changes()').fetchone()[0] == 1, 'current parent activation guard failed')
                db.execute('INSERT INTO source_confirmation_cards VALUES(?,?,?,?,?,?)',
                    (plan['run_id'], c['book_id'], c['card_id'], c['parent_snapshot_id'], c['child_snapshot_id'], c['before_payload_sha256']))
                if fail_after_cards == n:
                    raise RuntimeError('injected source confirmation failure')
            expected_graph = {(b, c): sid for b, c, sid in _graph(db)}
            for c in plan['cards']:
                require(expected_graph[(c['book_id'], c['card_id'])] == c['child_snapshot_id'], 'child graph reconciliation differs')
            require(stat_pin(plan['protected']['file']) == plan['protected']['stat'], 'protected source changed during write')
            db.commit()
        except BaseException:
            db.rollback(); raise
    return _receipt(plan)


def rollback(plan, *, root_write_approved=False):
    require(root_write_approved is True, 'explicit root rollback approval required')
    candidate = _validate(plan)
    with closing(_connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            previous = db.execute('SELECT plan_sha256,state FROM source_confirmation_runs WHERE run_id=?', (plan['run_id'],)).fetchone()
            require(previous is not None and previous[0] == digest(plan), 'applied run absent or seal differs')
            require(previous[1] in {'applied', 'rolled_back'}, 'rollback run state differs')
            already = previous[1] == 'rolled_back'
            for c in plan['cards']:
                current = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (c['book_id'], c['card_id'])).fetchone()
                require(current is not None and current[0] == (c['parent_snapshot_id'] if already else c['child_snapshot_id']), 'rollback would overwrite a later active parent')
                require(_read_parent(db, c['book_id'], c['card_id'], c['parent_snapshot_id']) == _payload(c, True), 'full recovery parent differs')
                if not already:
                    db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?', (c['parent_snapshot_id'], c['book_id'], c['card_id']))
            db.execute('UPDATE source_confirmation_runs SET state=? WHERE run_id=?', ('rolled_back', plan['run_id']))
            require(digest(_graph(db)) == plan['active_graph_sha256'], 'rollback full active graph inverse differs')
            db.commit()
        except BaseException:
            db.rollback(); raise
    return _receipt(plan, already=already, rollback=True)
