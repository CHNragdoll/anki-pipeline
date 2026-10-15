"""Finite, reversible teaching classifications; not exclusive linguistic proofs.

Only the eleven reviewed physical tokens in two books may change. Immutable
parents and dictionary definitions remain the recovery and provenance store.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import html
import json
from pathlib import Path
import sqlite3

from . import residual_optimization as ro
from . import sense_frequency as sf
from . import source_confirmations as sc
from .store import utc_now

REQUEST = 'eleven-semantic-resolution-request.v1'
PLAN = 'eleven-semantic-resolution-plan.v1'
BOOKS = {'redbook', 'redbook2027'}
SCOPE = {
    '0b8c9a8acaa98cd20405738bbc3a40fdac04f27004cb014bce060241fc18456c': 'mature',
    '1a6d71bdf6a2a379dcef82bc9396582a07873941fc0f2dcbaebdfbb9f9b668e4': 'fantastic',
    '1d1712e52c6b4347ea86a146de5a699aef386a3016428d6e229ed5feb25f5546': 'as',
    '31c818127df64010da3c20ee7182a070c338a4f896715916d4eee2129c7b7ac6': 'quiet',
    '3f033a4e7260eef4e1aa8033c59882afcf81391393452ce686004da005089151': 'great',
    '44588b5978fa34ddbf49d8afb8df504ee0174d553557397d4c05d7a36f0d2299': 'application',
    '462b2f2dd0692ff231fa73f7f658e49e31e8df91c9e45c5cc2eed7f6aca0df73': 'share',
    'a4bc1d7624f768b728e0037c74ef6aef4c54a1b6696e90e37a2fcd3921d5ce1b': 'secure',
    'ba8a650d74d832c9e9262bdb3573694f8170e27b28a8cfc878cdcd0a950d5a04': 'quite',
    'd52629b3851012aa28713b2a71d7c4ef99dfb9afbe8ce1a97be1cb88fe45562f': 'be',
    'fa89e348d02db3b2bdb7cecfabc3ae25122fda7c18750391fef8e9c2d1bc57e3': 'quite',
}
AS_ID = next(oid for oid, word in SCOPE.items() if word == 'as')
SEMANTIC_FIELDS = {'status', 'sense_id', 'reviewed_sense_id', 'assignment_context_hash',
    'reason', 'method', 'review_version', 'semantic_review', 'pending_category',
    'matching_proposal', 'broad_match', 'common_sense_match'}
_DDL = (
    'CREATE TABLE IF NOT EXISTS eleven_semantic_runs(run_id TEXT PRIMARY KEY,plan_sha256 TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS eleven_semantic_cards(run_id TEXT NOT NULL REFERENCES eleven_semantic_runs(run_id),book_id TEXT NOT NULL,card_id TEXT NOT NULL,parent_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),child_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),before_sha256 TEXT NOT NULL,PRIMARY KEY(run_id,book_id,card_id))',
)
canonical, digest, require = ro.canonical, sc.digest, ro.require


def pin(path):
    path = Path(path).resolve(strict=True)
    return {'file': str(path), 'sha256': digest(path.read_bytes())}


def _evidence(request):
    body = ro.read_json(request['body_evidence'])
    options = ro.read_json(request['option_evidence'])
    source = ro.read_json(request['as_evidence'])
    records = body['records'] + options['records']
    require(len(records) == 10 and len({r['occurrence_id'] for r in records}) == 10,
            'exact ten semantic research records required')
    indexed = {r['occurrence_id']: r for r in records}
    require(set(indexed) == set(SCOPE) - {AS_ID} and all(SCOPE[oid] == row['word'] for oid, row in indexed.items()),
            'research physical token/word scope differs')
    require(source['occurrence_id'] == AS_ID and source['word'] == 'as', 'source anomaly scope differs')
    if request.get('as_deep_evidence'):
        summary = ro.read_json(request['as_deep_evidence'])
        require(summary.get('occurrence_id') == AS_ID and summary.get('standard_native_main_assignment_found') is False,
                'deep source research must preserve the unverified standard-sense boundary')
        require(len(summary.get('input_pins', [])) == 5 and len(summary.get('search_results', [])) == 19,
                'complete five reports and nineteen archived searches required')
        documents = []
        for reference in summary['input_pins'] + summary['search_results']:
            raw = ro.read_pin(reference)
            content = raw.decode('utf-8') if isinstance(raw, bytes) else raw
            documents.append({'pin': deepcopy(reference), 'content': content})
        source = {**source, 'deep_research': {'summary_pin': deepcopy(request['as_deep_evidence']),
            'summary': summary, 'complete_documents': documents}}
    if request.get('secure_chinese_evidence'):
        chinese = ro.read_json(request['secure_chinese_evidence'])
        secure_id = next(oid for oid, word in SCOPE.items() if word == 'secure')
        require(chinese.get('occurrence_id') == secure_id and chinese.get('word') == 'secure',
                'Chinese dictionary-priority review scope differs')
        indexed[secure_id] = {**indexed[secure_id], 'chinese_priority_check': {
            'pin': deepcopy(request['secure_chinese_evidence']), 'complete_report': chinese}}
    indexed[AS_ID] = source
    watched = {request[k]['file']: request[k]['sha256'] for k in ('body_evidence', 'option_evidence', 'as_evidence')}
    def capture(value):
        if isinstance(value, dict):
            if isinstance(value.get('file'), str) and isinstance(value.get('sha256'), str):
                if Path(value['file']).suffix not in {'.db', '.sqlite', '.sqlite3'}:
                    ro.read_pin(value)
                    old = watched.setdefault(value['file'], value['sha256'])
                    require(old == value['sha256'], 'conflicting evidence pin')
            for child in value.values():
                capture(child)
        elif isinstance(value, list):
            for child in value:
                capture(child)
    for evidence in (body, options, source, *[r for r in indexed.values() if r.get('chinese_priority_check')]):
        capture(evidence)
    return indexed, watched


def _native(evidence, parent):
    chosen = evidence.get('native_primary') or evidence['selected_native_sense']
    chinese = chosen.get('original_chinese') or chosen.get('definition_zh') or chosen.get('chinese_rendering')
    matches = [s for s in parent['senses'] if s['text'] == chinese]
    require(len(matches) == 1, 'selected native definition absent or nonunique in current card')
    return matches[0], {
        'name': chosen.get('name') or chosen.get('dictionary') or chosen.get('source'),
        'version': chosen.get('version') or 'OALD10', 'exact_entry': parent['word'],
        'sense': chosen.get('sense') or chosen.get('native_sense_id'),
        'english_definition': chosen.get('english_definition') or chosen.get('definition_en'),
        'original_chinese': chosen.get('original_chinese') or chosen.get('definition_zh'),
        'chinese_rendering': chosen.get('chinese_rendering'),
        'chinese_provenance': chosen.get('chinese_provenance', 'native_dictionary_original'),
        'translation_label': ('补译（沿用原选项译文）' if chosen.get('original_chinese') is None
                              and chosen.get('definition_zh') is None else '词典原译'),
        'grammatical_scope': canonical(chosen.get('grammatical_scope') or chosen.get('part_of_speech')),
        'context_reason': evidence.get('assignment_reason') or evidence.get('explanation'),
        'complete_selected_native_evidence': deepcopy(chosen),
    }


def transform(parent, evidence_by_id, target_ids):
    """Seal only semantic deltas, retaining all physical/display/history bytes."""
    record = sc._producer(parent)
    # The producer deliberately shares old trees. This lane changes no source,
    # definition or policy tree; each target semantic review becomes a new tree.
    originals = {r['occurrence_id']: r for r in parent['occurrences']}
    for row in record['occurrences']:
        oid = row['occurrence_id']
        if oid not in target_ids:
            continue
        old, evidence = originals[oid], evidence_by_id[oid]
        require(parent['word'] == SCOPE[oid] == evidence['word'], 'semantic target lemma differs')
        expected_english = (evidence.get('english') or evidence.get('original_english')
                            or evidence.get('observed_source', {}).get('english'))
        require(expected_english == old['english'] and evidence['sentence_id'] == old['sentence_id']
                and evidence['target_range'] == old['target_range'], 'research source text/range differs from current parent')
        history = {'schema': 'eleven-semantic-row-review.v1', 'occurrence_id': oid,
            'original_row': deepcopy(old), 'original_row_sha256': digest(old),
            'original_reason': old['reason'], 'original_semantic_review': deepcopy(old.get('semantic_review')),
            'evidence': deepcopy(evidence), 'unique_native_sense_proven': False,
            'method': 'reviewed-primary-teaching-classification-with-retained-alternatives.v1'}
        if oid == AS_ID:
            recommendation = evidence['recommendation']
            reason = recommendation['reason_zh']
            history.update(action='source_anomaly_explained', workflow_resolution_status='handled_source_anomaly',
                lexical_sense_status='standard_dictionary_sense_not_certified', confidence='source_wording_verified',
                alternatives=deepcopy(evidence.get('hypotheses', [])), source_notice=deepcopy(recommendation),
                reason=reason)
            history['source_notice']['display_label'] = '原文结构异常'
            row.update(status='ambiguous', sense_index=None, reviewed_sense_id=None, assignment_context_hash=None)
            row['pending_category'] = '义项未细分'
        else:
            sense, dictionary = _native(evidence, parent)
            reason = evidence.get('assignment_reason') or evidence['explanation']
            history.update(action='match_existing_sense', workflow_resolution_status='reviewed_primary_meaning',
                selected_sense_id=sense['sense_id'], confidence=evidence['confidence'], reason=reason,
                alternatives=deepcopy(evidence.get('other_native_candidates_preserved', evidence.get('alternatives', []))),
                grammar_note=evidence.get('grammar_note'), dictionary_explanation=dictionary)
            row.update(status='reviewed', sense_index=sense['ordinal'])
            row.pop('pending_category', None)
            for field in ('matching_proposal', 'broad_match', 'common_sense_match'):
                row.pop(field, None)
        row.update(reason=reason, method='eleven-semantic-reviewed-primary.v1', review_version='20261014',
                   semantic_review=history)
    child = sc._seal(record, parent)
    validate_child(parent, child, target_ids)
    return child


def validate_child(before, after, target_ids):
    require(set(target_ids) <= set(SCOPE), 'foreign semantic target')
    for field in set(before) - {'snapshot_id', 'occurrences'}:
        require(before[field] == after.get(field), 'semantic lane changed card/definition/policy: ' + field)
    old = {r['occurrence_id']: r for r in before['occurrences']}
    current = {r['occurrence_id']: r for r in after['occurrences']}
    require(set(old) == set(current) and before['expected_occurrences'] == after['expected_occurrences'],
            'semantic lane changed physical count or IDs')
    definition = sf._definition(after)
    for oid, row in current.items():
        if oid not in target_ids:
            require(row == old[oid], 'unrelated semantic/source/display row changed')
            continue
        require({k: v for k, v in row.items() if k not in SEMANTIC_FIELDS}
                == {k: v for k, v in old[oid].items() if k not in SEMANTIC_FIELDS},
                'target physical/chunk/source/history bytes changed')
        history = row['semantic_review']
        require(history['original_row'] == old[oid] and history['original_row_sha256'] == digest(old[oid])
                and history['original_semantic_review'] == old[oid].get('semantic_review')
                and history['unique_native_sense_proven'] is False, 'complete semantic history differs')
        require(history.get('confidence') and history.get('method') and 'alternatives' in history,
                'explicit judgment scope/confidence/alternatives required')
        require(row['status'] == ('ambiguous' if oid == AS_ID else 'reviewed'), 'wrong resolution status')
        raw = {k: v for k, v in row.items() if k != 'display'}
        raw['sense_index'] = next((s['ordinal'] for s in after['senses'] if s['sense_id'] == row['sense_id']), None)
        checked = sf._occurrence(raw, definition)
        if 'display' in row:
            checked['display'] = row['display']
        require(checked == row, 'reviewed row normalization differs')
    sc._identity(after)


def prepare(request, output):
    """Read dynamic active parents and export complete inverse/child payloads."""
    require(request.get('schema') == REQUEST, 'finite semantic request schema required')
    candidate = Path(request['candidate']['file']).resolve(strict=True)
    protected = Path(request['protected']['file']).resolve(strict=True)
    require(candidate != protected and not candidate.samefile(protected), 'protected source is not candidate')
    require(sc.stat_pin(protected) == request['protected']['stat'], 'protected source changed')
    evidence, watched = _evidence(request)
    output = Path(output).resolve()
    require(not output.exists(), 'fresh immutable preparation directory required')
    output.mkdir(parents=True)
    cards, seen, files = [], set(), dict(watched)
    with closing(sc._connect(candidate)) as db:
        graph = sc._graph(db)
        keys = {}
        for oid, word in SCOPE.items():
            refs = []
            for book, card, sid in db.execute('SELECT a.book_id,a.card_id,a.snapshot_id FROM active_snapshots a '
                    'JOIN snapshots s ON s.id=a.snapshot_id WHERE s.word=?', (word,)):
                if book not in BOOKS:
                    continue
                if db.execute('SELECT 1 FROM occurrences WHERE snapshot_id=? AND occurrence_id=?', (sid, oid)).fetchone():
                    keys.setdefault((book, card, sid), set()).add(oid)
                    refs.append(book)
                    seen.add((book, oid))
            require(set(refs) == BOOKS and len(refs) == 2, 'exact per-book physical token coverage required')
        require(len(keys) == 20 and len(seen) == 22, 'finite twenty-card scope differs')
        for (book, card, sid), targets in sorted(keys.items()):
            parent = sc._read_parent(db, book, card, sid)
            child = transform(parent, evidence, targets)
            entry = {'book_id': book, 'card_id': card, 'word': parent['word'],
                'parent_snapshot_id': sid, 'child_snapshot_id': child['snapshot_id'],
                'target_ids': sorted(targets), 'before_payload_sha256': digest(parent),
                'payload_sha256': digest(child), 'original_count': parent['expected_occurrences'],
                'new_count': child['expected_occurrences'], 'before_payload': parent, 'payload': child,
                'new_definitions': []}
            sc._export_card(entry, output, files)
            cards.append(entry)
    for module in (__file__, sf.__file__, sc.__file__, ro.__file__):
        files[str(Path(module).resolve())] = digest(Path(module).read_bytes())
    plan = {'schema': PLAN, 'request': deepcopy(request), 'candidate': str(candidate),
        'candidate_stat': sc.stat_pin(candidate), 'protected': deepcopy(request['protected']),
        'active_graph_sha256': digest(graph), 'cards': cards, 'source_files': files,
        'summary': {'cards': 20, 'reviewed_rows': 20, 'source_anomaly_rows': 2,
                    'physical_count_delta': 0, 'exclusive_native_proofs': 0, 'definition_changes': 0}}
    plan['run_id'] = digest(plan)
    plan_pin = sc._write_json(output / 'plan.json', plan)
    return {'plan': plan_pin, 'run_id': plan['run_id'], 'summary': plan['summary']}


def _validate(plan):
    require(plan.get('schema') == PLAN and plan['run_id'] == digest({k: v for k, v in plan.items() if k != 'run_id'}),
            'finite semantic plan seal differs')
    candidate = Path(plan['candidate']).resolve(strict=True)
    protected = Path(plan['protected']['file']).resolve(strict=True)
    require(candidate != protected and not candidate.samefile(protected), 'protected candidate alias')
    require(sc.stat_pin(protected) == plan['protected']['stat'], 'protected source changed')
    for file, sha in plan['source_files'].items():
        ro.read_pin({'file': file, 'sha256': sha})
    seen = set()
    require(len(plan['cards']) == 20 and len({(c['book_id'], c['card_id']) for c in plan['cards']}) == 20,
            'finite semantic card scope differs')
    for card in plan['cards']:
        before, after = sc._payload(card, True), sc._payload(card)
        require(digest(before) == card['before_payload_sha256'] and digest(after) == card['payload_sha256'], 'payload pin differs')
        require((before['book_id'], before['card_id'], before['snapshot_id']) ==
                (card['book_id'], card['card_id'], card['parent_snapshot_id'])
                and after['snapshot_id'] == card['child_snapshot_id'], 'plan card identity differs')
        sc._identity(before)
        validate_child(before, after, card['target_ids'])
        for oid in card['target_ids']:
            require(SCOPE[oid] == card['word'] and (card['book_id'], oid) not in seen, 'duplicate/foreign operation')
            seen.add((card['book_id'], oid))
    require(seen == {(book, oid) for book in BOOKS for oid in SCOPE}, 'cross-book target scope differs')
    return candidate


def _receipt(plan, state, already=False):
    return {'schema': 'eleven-semantic-receipt.v1', 'run_id': plan['run_id'], 'state': state,
        'database': {'file': plan['candidate'], 'stat': sc.stat_pin(plan['candidate'])},
        'already_' + ('applied' if state == 'applied' else 'rolled_back'): already,
        'summary': plan['summary'], 'cards': plan['cards']}


def apply(plan, *, root_write_approved=False, fail_after_cards=None):
    require(root_write_approved is True, 'explicit ROOT write authorization required')
    candidate = _validate(plan)
    with closing(sc._connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for ddl in _DDL:
                db.execute(ddl)
            previous = db.execute('SELECT plan_sha256,state FROM eleven_semantic_runs WHERE run_id=?', (plan['run_id'],)).fetchone()
            if previous:
                require(tuple(previous) == (digest(plan), 'applied'), 'existing semantic batch state differs')
                for card in plan['cards']:
                    require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',
                        (card['book_id'], card['card_id'])).fetchone()[0] == card['child_snapshot_id'], 'idempotent child pointer drifted')
                    ro._reconcile(db, sc._payload(card))
                db.rollback()
                return _receipt(plan, 'applied', True)
            require(sc.stat_pin(candidate) == plan['candidate_stat'] and digest(sc._graph(db)) == plan['active_graph_sha256'],
                    'candidate identity/current active graph changed; prepare again')
            db.execute('INSERT INTO eleven_semantic_runs VALUES(?,?,?,?)', (plan['run_id'], digest(plan), 'applied', utc_now()))
            for n, card in enumerate(plan['cards'], 1):
                require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == sc._payload(card, True),
                        'immutable recovery parent differs')
                child = sc._payload(card)
                ro._insert(db, child)
                ro._reconcile(db, child)
                db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=? AND snapshot_id=?',
                    (card['child_snapshot_id'], card['book_id'], card['card_id'], card['parent_snapshot_id']))
                require(db.execute('SELECT changes()').fetchone()[0] == 1, 'current parent activation guard failed')
                db.execute('INSERT INTO eleven_semantic_cards VALUES(?,?,?,?,?,?)',
                    (plan['run_id'], card['book_id'], card['card_id'], card['parent_snapshot_id'], card['child_snapshot_id'], card['before_payload_sha256']))
                if fail_after_cards == n:
                    raise RuntimeError('injected semantic transaction failure')
            actual = {(b, c): sid for b, c, sid in sc._graph(db)}
            restored = [[b, c, next((i['parent_snapshot_id'] for i in plan['cards'] if (i['book_id'], i['card_id']) == (b, c)), sid)]
                        for (b, c), sid in sorted(actual.items())]
            require(digest(restored) == plan['active_graph_sha256'], 'unrelated active pointers changed')
            require(sc.stat_pin(plan['protected']['file']) == plan['protected']['stat'], 'protected source changed during apply')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return _receipt(plan, 'applied')


def rollback(plan, *, root_write_approved=False):
    require(root_write_approved is True, 'explicit ROOT rollback authorization required')
    candidate = _validate(plan)
    with closing(sc._connect(candidate, write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            saved = db.execute('SELECT plan_sha256,state FROM eleven_semantic_runs WHERE run_id=?', (plan['run_id'],)).fetchone()
            require(saved and saved[0] == digest(plan) and saved[1] in {'applied', 'rolled_back'}, 'exact semantic batch required')
            already = saved[1] == 'rolled_back'
            for card in plan['cards']:
                sid = card['parent_snapshot_id'] if already else card['child_snapshot_id']
                require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',
                        (card['book_id'], card['card_id'])).fetchone()[0] == sid, 'rollback would overwrite later work')
                require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == sc._payload(card, True),
                        'complete recovery parent differs')
                if not already:
                    db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',
                        (card['parent_snapshot_id'], card['book_id'], card['card_id']))
            db.execute('UPDATE eleven_semantic_runs SET state=? WHERE run_id=?', ('rolled_back', plan['run_id']))
            require(digest(sc._graph(db)) == plan['active_graph_sha256'], 'full active graph recovery differs')
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return _receipt(plan, 'rolled_back', already)


def rehearse(plan, output):
    """Only the twenty actual affected immutable parents enter a scratch DB."""
    output = Path(output).resolve()
    require(not output.exists(), 'fresh affected-only rehearsal required')
    output.mkdir(parents=True)
    database = output / 'affected-only.sqlite3'
    with closing(sqlite3.connect(database)) as db:
        db.executescript(sf._SQL + '\nPRAGMA user_version=2;')
        for card in plan['cards']:
            ro._insert(db, sc._payload(card, True))
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', (card['book_id'], card['card_id'], card['parent_snapshot_id']))
        db.commit()
        graph = sc._graph(db)
    trial = deepcopy(plan)
    trial.update(candidate=str(database), candidate_stat=sc.stat_pin(database), active_graph_sha256=digest(graph))
    trial['run_id'] = digest({k: v for k, v in trial.items() if k != 'run_id'})
    try:
        apply(trial, root_write_approved=True, fail_after_cards=2)
        raise AssertionError('fault injection did not fail')
    except RuntimeError as exc:
        require('injected' in str(exc), 'unexpected scratch failure')
    with closing(sc._connect(database)) as db:
        require(sc._graph(db) == graph, 'failed semantic transaction changed pointers')
        for card in trial['cards']:
            require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == sc._payload(card, True), 'failed transaction changed parent')
    trial['candidate_stat'] = sc.stat_pin(database)
    trial['run_id'] = digest({k: v for k, v in trial.items() if k != 'run_id'})
    applied = apply(trial, root_write_approved=True)
    repeated = apply(trial, root_write_approved=True)
    restored = rollback(trial, root_write_approved=True)
    repeat_restore = rollback(trial, root_write_approved=True)
    with closing(sc._connect(database)) as db:
        require(sc._graph(db) == graph, 'scratch rollback graph differs')
        for card in trial['cards']:
            require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == sc._payload(card, True), 'scratch immutable parent differs')
            ro._reconcile(db, sc._payload(card))
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall(), 'scratch integrity differs')
    result = {'schema': 'eleven-semantic-rehearsal.v1', 'real_candidate_modified': False, 'cards': len(plan['cards']),
        'scratch_bytes': database.stat().st_size, 'injected_failure_atomic': True,
        'apply_idempotent': repeated['already_applied'], 'rollback_idempotent': repeat_restore['already_rolled_back'],
        'complete_parents_preserved': True, 'child_SQL_readback_exact': True, 'integrity_check': 'ok',
        'applied': applied['state'], 'restored': restored['state'], 'production_plan_run_id': plan['run_id']}
    sc._write_json(output / 'rehearsal.json', result)
    return result


def render_semantic_history(page, data, aliases):
    """Keep new and original audits inside their sentence, never a separate list."""
    from .native_example_usage import _Offsets
    from scripts import update_exam_usage_preview as preview
    rows = {r['occurrence_id']: r for r in data['occurrences']}
    edits = []
    for node in _Offsets(page, aliases).root.walk():
        if node.tag != 'article' or 'sf-example' not in node.classes:
            continue
        row = rows.get(node.attrs.get('data-sf-occurrence-id'))
        review = row and row.get('semantic_review', {})
        if not review or review.get('schema') != 'eleven-semantic-row-review.v1':
            continue
        source_anomaly = row['occurrence_id'] == AS_ID
        title = '原文结构异常 · 完整来源说明' if source_anomaly else '本句释义归类与完整旧审查'
        note = '<details class="sf-semantic-resolution-history"><summary>' + title + '</summary>'
        note += '<p class="sf-reason">' + html.escape(review['reason']) + '</p>'
        note += ('<p class="sf-reason">处理方式：保留来源原文和整句解释；未分配标准词典义项。</p>' if source_anomaly else
                 '<p class="sf-reason">归类方法：按最有依据的释义；未宣称唯一排除所有其他分析。</p>')
        note += '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：' + html.escape(review['original_reason']) + '</p>'
        note += '<details><summary>全部原记录、词典详细释义与判断证据</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(canonical(review)) + '</pre></details></details>'
        require(node.closed is not None, 'semantic sentence disclosure boundary absent')
        edits.append((node.closed, node.closed, note))
    return preview.apply_edits(page, edits)
