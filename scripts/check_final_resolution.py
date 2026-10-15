"""Read-only acceptance audit of the current two-book correction state."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from anki_pipeline import source_confirmations as sc
from anki_pipeline import residual_optimization as ro
from anki_pipeline import eleven_semantic_resolution as semantic
from anki_pipeline import final_reader_contexts as contexts

EXPECTED_WORD_DELTAS = {
    'be': -1, 'deep': -1, 'root': -1, 'deep-rooted': 1,
    'promote': -1, 'prompt': 1, 'date': -1, 'data': 1,
    'team': -1, 'teem': 1,
}
DEEP_COMPONENT_ID = '52956ebe7d8c94e9a3f97a391b988ee8ca36755f469cb49216ab6fc7ece65881'


def audit(source_plan, semantic_plan, baseline, *, context_plan=None, progress=None):
    """Check live pointers, physical counts, assignments and complete payloads.

    This deliberately does not claim browser or reader acceptance. Those require
    separate current runtime evidence, not an inference from these SQL checks.
    """
    candidate = ROOT / 'data/sense-frequency-optimized-20261013.sqlite3'
    sc.require(Path(source_plan['candidate']).resolve() == candidate
               and Path(semantic_plan['candidate']).resolve() == candidate,
               'audit must inspect the actual authorized current database')
    sc.require(sc.stat_pin(ROOT / 'data/sense-frequency-usage-20261012-v5-recovery.sqlite3')
               == baseline['protected_stat'], 'protected recovery baseline changed')
    plans = [source_plan, semantic_plan]
    context_inputs = context_scope = None
    if context_plan is not None:
        sc.require(Path(context_plan['candidate']).resolve() == candidate,
                   'context audit must use the same actual current database')
        sc.require(context_plan.get('schema') == contexts.PLAN
                   and context_plan['run_id'] == sc.digest({k: v for k, v in context_plan.items()
                                                           if k != 'run_id'}),
                   'context plan identity seal differs')
        context_inputs = contexts.load_inputs(context_plan['request'])
        context_scope = ro.read_json(context_plan['request']['scope'])
        sc.require(context_scope['expected_rows'] == 96 and context_scope['expected_cards'] == 75,
                   'exact known cross-stem dependency closure differs')
        plans.append(context_plan)
    final_cards = {}
    for plan in plans:
        for card in plan['cards']:
            key = card['book_id'], card['card_id']
            previous = final_cards.get(key)
            if previous:
                sc.require(card['parent_snapshot_id'] == previous['child_snapshot_id'],
                           'source/semantic/context shared-card lineage is not sequential')
            final_cards[key] = card
    old_counts = {(r['book_id'], r['word']): r['occurrences']
                  for r in baseline['word_counts']}
    counts, found_semantic, source_tokens = {}, [], Counter()
    checked_contexts = set()
    with closing(sc._connect(candidate)) as db:
        totals = list(db.execute('SELECT a.book_id,s.word,SUM(s.expected_occurrences),COUNT(*) '
            'FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id '
            'GROUP BY a.book_id,s.word'))
        current_counts = {(b, w): n for b, w, n, _ in totals}
        changes = {key: current_counts.get(key, 0) - old_counts.get(key, 0)
                   for key in set(old_counts) | set(current_counts)
                   if current_counts.get(key, 0) != old_counts.get(key, 0)}
        expected = {(book, word): delta for book in semantic.BOOKS
                    for word, delta in EXPECTED_WORD_DELTAS.items()}
        sc.require(changes == expected, 'live word-frequency deltas differ: ' + str(changes))
        for book in semantic.BOOKS:
            actual = {'cards': sum(n for b, w, total, n in totals if b == book),
                      'occurrences': sum(total for b, w, total, n in totals if b == book)}
            sc.require(actual['cards'] == baseline['books'][book]['cards'] + 2
                       and actual['occurrences'] == baseline['books'][book]['occurrences'] - 2,
                       'two supplementary entries / two invalid component counts differ')
            counts[book] = actual
        for index, (key, card) in enumerate(sorted(final_cards.items()), 1):
            active = db.execute('SELECT snapshot_id FROM active_snapshots '
                'WHERE book_id=? AND card_id=?', key).fetchone()
            sc.require(active and active[0] == card['child_snapshot_id'],
                       'current active pointer differs from final plan: ' + str(key))
            expected_payload = sc._payload(card)
            actual = sc._read_parent(db, *key, card['child_snapshot_id'])
            sc.require(actual == expected_payload, 'complete live child differs from approved plan')
            policy = actual.get('exam_usage_policy', {}).get('final_reader_contexts')
            if policy is not None:
                sc.require(context_plan is not None and policy.get('schema') == 'final-reader-context-card.v1',
                           'live context policy is not covered by the audited plan')
                context_card = next(c for c in context_plan['cards']
                                    if (c['book_id'], c['card_id']) == key)
                original_parent = sc._payload(context_card, before=True)
                sc.require(actual == contexts.build_child(original_parent, context_card['display_projections'])
                           and actual['occurrences'] == original_parent['occurrences']
                           and actual['senses'] == original_parent['senses']
                           and actual['expected_occurrences'] == original_parent['expected_occurrences'],
                           'context-only snapshot changed raw occurrences, definitions or physical counts')
                raw_rows = {r['occurrence_id']: r for r in actual['occurrences']}
                for oid, projection in policy['projections'].items():
                    sc.require(oid in raw_rows, 'context projection lost its physical occurrence')
                    new_display = contexts.validate_projection(projection, raw_rows[oid],
                                                               original_parent, context_plan['request'],
                                                               context_inputs)
                    question_id = new_display['derivation_payload']['questionId']
                    case = contexts.QUESTIONS[question_id]
                    stem = context_inputs['revisions'][case]['newRecord']['english']
                    sc.require(new_display['derivation_payload']['questionEnglish'] == stem
                               and new_display['english'].startswith(stem)
                               and new_display['translation'] == raw_rows[oid]['display']['translation'],
                               'effective option view does not use the current corrected bilingual stem')
                    checked_contexts.add((*key, oid))
            for row in actual['occurrences']:
                oid = row['occurrence_id']
                if oid in semantic.SCOPE:
                    review = row.get('semantic_review', {})
                    sc.require(review.get('schema') == 'eleven-semantic-row-review.v1'
                               and 'original_row' in review and 'alternatives' in review,
                               'complete semantic review is missing')
                    if oid == semantic.AS_ID:
                        sc.require(row['status'] == 'ambiguous' and row['sense_id'] is None
                            and review.get('lexical_sense_status') == 'standard_dictionary_sense_not_certified',
                            'as has been falsely assigned a standard sense')
                    else:
                        sc.require(row['status'] == 'reviewed' and row['sense_id'] is not None,
                                   'one of the ten researched meanings is not assigned')
                    found_semantic.append((key[0], oid))
                history = row['source_provenance'].get('source_confirmation', {})
                if history.get('schema') == 'final-source-confirmation-row.v1':
                    original = history['original_row']
                    sc.require(sc.digest(original) == history['original_row_sha256'],
                               'source correction original history seal differs')
                    if row['sentence_id'] == history['source_revision']['sentence_id']:
                        current_source = history['source_revision']['published_record']
                        sc.require(row['english'] == current_source['english']
                            and row['english_hash'] == current_source['englishHash']
                            and row['translation'] == current_source['translationZh']
                            and row['alignment']['alignments'] == current_source['alignments'],
                            'live corrected card does not match current bilingual reader source')
                    if (not history.get('metadata_only')
                            and actual['word'] in {'prompt', 'data', 'deep-rooted', 'teem'}):
                        source_tokens[key[0], actual['word']] += 1
            if progress and (index % 25 == 0 or index == len(final_cards)):
                progress(index, len(final_cards))
        sc.require(len(found_semantic) == 22
                   and set(found_semantic) == {(book, oid) for book in semantic.BOOKS for oid in semantic.SCOPE},
                   'ten meanings and the one as anomaly are not covered once in each book')
        canonical = json.loads((ROOT / 'output/residual-optimization-20261013/integration/'
            'semantic-adapter-own/canonical-merged-decisions-v2.json').read_text())
        common = {r['id'] for r in canonical['decisions'] if r['action'] == 'confirm_common_sense'}
        raw_pending = list(db.execute('SELECT a.book_id,x.occurrence_id FROM active_snapshots a '
            'JOIN assignments x ON x.snapshot_id=a.snapshot_id WHERE x.status<>?', ('reviewed',)))
        remaining = {(book, oid) for book, oid in raw_pending if oid not in common}
        sc.require(remaining == {(book, semantic.AS_ID) for book in semantic.BOOKS},
                   'there is an additional unresolved live occurrence: ' + str(remaining))
        retired = {json.loads(p.read_text())['original_occurrence_id'] for p in
                   (ROOT / 'docs/evidence').glob('source-confirmation-*-20261014.json')
                   if p.name.startswith(('source-confirmation-be-', 'source-confirmation-deep-rooted-'))}
        retired.add(DEEP_COMPONENT_ID)
        for oid in retired:
            sc.require(db.execute('SELECT COUNT(*) FROM active_snapshots a JOIN occurrences o '
                'ON o.snapshot_id=a.snapshot_id WHERE o.occurrence_id=?', (oid,)).fetchone()[0] == 0,
                'invalid be/compound component remains counted')
        if context_plan is not None:
            expected_contexts = {(r['book_id'], r['card_id'], r['occurrence_id'])
                                 for r in context_scope['rows']}
            sc.require(checked_contexts == expected_contexts,
                       'live corrected option display dependencies are not covered exactly once')
            placeholders = ','.join('?' for _ in contexts.OPTION_IDS)
            live_contexts = {tuple(row) for row in db.execute(
                'SELECT a.book_id,a.card_id,o.occurrence_id FROM active_snapshots a '
                'CROSS JOIN occurrences o INDEXED BY sqlite_autoindex_occurrences_1 '
                'ON o.snapshot_id=a.snapshot_id '
                f'WHERE a.book_id IN (?,?) AND o.sentence_id IN ({placeholders})',
                [*contexts.BOOKS, *contexts.OPTION_IDS])}
            sc.require(live_contexts == checked_contexts,
                       'current normalized eight-option occurrence closure differs from regenerated views')
    return {'schema': 'final-resolution-root-current-database-audit.v2',
        'database': str(candidate), 'books': counts, 'affected_final_cards_checked': len(final_cards),
        'normalized_payloads_and_active_pointers_exact': True,
        'word_frequency_deltas_exact': True, 'semantic_rows_checked': len(found_semantic),
        'remaining_unique_source_anomaly': semantic.AS_ID, 'remaining_unique_anomalies': 1,
        'raw_common_sense_rows_retained': len(raw_pending) - len(remaining),
        'protected_recovery_unchanged': True, 'browser_acceptance_claimed': False,
        'context_projections_checked': len(checked_contexts),
        'context_physical_rows_definitions_and_counts_unchanged': context_plan is not None,
        'all_known_corrected_stem_option_dependencies_current': context_plan is not None,
        'source_tokens': [{'book_id': b, 'word': w, 'rows': n} for (b, w), n in sorted(source_tokens.items())]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-plan', 'semantic-plan'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--context-plan', type=Path)
    parser.add_argument('--context-plan-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = ro.read_json({'file': str(args.source_plan), 'sha256': args.source_plan_sha256})
    meaning = ro.read_json({'file': str(args.semantic_plan), 'sha256': args.semantic_plan_sha256})
    baseline = json.loads(args.baseline.read_text())
    sc.require(bool(args.context_plan) == bool(args.context_plan_sha256),
               'context plan path and hash must be supplied together')
    context = (ro.read_json({'file': str(args.context_plan), 'sha256': args.context_plan_sha256})
               if args.context_plan else None)
    result = audit(source, meaning, baseline, context_plan=context,
                   progress=lambda done, total: print(f'Current DB verified {done}/{total}', flush=True))
    result['producer'] = {'file': str(Path(__file__).resolve()),
                          'sha256': sc.digest(Path(__file__).read_bytes())}
    result['input_pins'] = {
        'source_plan': {'file': str(args.source_plan.resolve()), 'sha256': args.source_plan_sha256},
        'semantic_plan': {'file': str(args.semantic_plan.resolve()), 'sha256': args.semantic_plan_sha256},
        'baseline': {'file': str(args.baseline.resolve()), 'sha256': sc.digest(args.baseline.read_bytes())},
    }
    if args.context_plan:
        result['input_pins']['context_plan'] = {'file': str(args.context_plan.resolve()),
                                                'sha256': args.context_plan_sha256}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sc.require(not args.output.exists(), 'fresh acceptance receipt required')
    sc._write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
