#!/usr/bin/env python3
"""Publish the five-source follow-up report from ROOT's actual write evidence.

The baseline and its complete records remain immutable. This formatter does
not perform database writes or claim browser acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import html
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWN = REPO / 'output/residual-optimization-20261013/docs-own'
BASE = OWN / 'pending-v2-after-root-apply-v2/pending-v2.json'
FORMATTER = OWN / 'pending_report_display_v2.py'
EXPECTED = {
    'remote': '0737f3946519137ae600ddf2bf7e5d91bf08fcbb1e19708ade9d9884ca588d63',
    'pick': '14e6e7b432b56d9c4cf07fc6cf6b02498aa3d10cd849c327828b38bb71df0307',
    'as': '1d1712e52c6b4347ea86a146de5a699aef386a3016428d6e229ed5feb25f5546',
    'number': '32180affdd27f964e17c839abe725d17d6785c97f50d0881a469fba2b3f6787c',
    'jug': 'eae64cd295e10e1c6f8021f2aee5b55623be2424fe8c661912dc9ca24a391cb9',
}


def pin(path: Path):
    raw = path.read_bytes()
    return {'file': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def build(evidence):
    if evidence.get('schema') != 'five-source-confirmations-actual-data.v1' or evidence.get('state') != 'applied':
        raise ValueError('Actual applied five-source evidence required')
    updates = evidence.get('outcomes', [])
    if Counter(u['original_occurrence_id'] for u in updates) != Counter(EXPECTED.values()):
        raise ValueError('Exactly the five original source positions required')
    report = json.loads(BASE.read_text())
    previous_summary = deepcopy(report['summary'])
    rows = {r['id']: r for r in report['records']}
    if not set(EXPECTED.values()).issubset(report['queues']['specific_remaining']):
        raise ValueError('Baseline unresolved inventory changed')
    for update in updates:
        oid = update['original_occurrence_id']
        if not update.get('actual_snapshot_bindings') or not update.get('reason'):
            raise ValueError('Actual snapshot bindings and explanatory reason required')
        if not isinstance(update.get('meaning_zh'), str) or not update['meaning_zh']:
            raise ValueError('Current meaning must be nonempty display text')
        word = next(word for word, expected_oid in EXPECTED.items() if expected_oid == oid)
        allowed_actions = {
            'remote': {'contextual_usage'}, 'pick': {'contextual_usage'},
            'as': {'retain_specific_ambiguity'},
            'number': {'source_correction', 'match_existing_sense'},
            'jug': {'rehome', 'source_correction'},
        }
        if update['action'] not in allowed_actions[word] or update['unique_resolution'] is not (word != 'as'):
            raise ValueError('Source-specific outcome contract differs: ' + word)
        if word in {'remote', 'pick'} and update.get('is_dictionary_native') is not False:
            raise ValueError('Phrase interpretation cannot masquerade as dictionary-native: ' + word)
        bindings = update['actual_snapshot_bindings']
        if len(bindings) != 2 or {binding.get('book_id') for binding in bindings} != {'redbook', 'redbook2027'}:
            raise ValueError('Both actual book bindings required: ' + word)
        if len({(binding['book_id'], binding['card_id']) for binding in bindings}) != len(bindings):
            raise ValueError('Repeated actual card binding: ' + word)
        if any(not binding.get('child_snapshot_id') for binding in bindings):
            raise ValueError('Actual child snapshot IDs required: ' + word)
        row = rows[oid]
        row['source_confirmation_previous_record'] = deepcopy(row)
        row['source_confirmation_update'] = deepcopy(update)
        row['reason'] = update['reason']
        row['meaning_zh'] = update['meaning_zh']
        row['remaining_reason'] = update.get('remaining_reason', '')
        row['action'] = update['action']
        row['application_status'] = 'root_receipt_applied'
        row['actual_lemma'] = update.get('actual_lemma', row['actual_lemma'])
        if update['unique_resolution']:
            row['category_tags'] = [tag for tag in row['category_tags'] if tag != 'source'] + [
                'source_corrected' if word in {'number', 'jug'} else 'source_verified']
            report['queues']['specific_remaining'].remove(oid)
        elif not row['remaining_reason']:
            raise ValueError('Unresolved source use needs a specific remaining reason')
    report['schema'] = 'five-source-confirmations-pending-report.v1'
    report['source_confirmation_evidence'] = evidence
    report['source_confirmation_previous_summary'] = previous_summary
    summary = report['summary']
    remaining = report['queues']['specific_remaining']
    summary['specific_remaining_positions'] = len(remaining)
    summary['specific_remaining_category_counts'] = dict(Counter(
        tag for oid in remaining for tag in rows[oid]['category_tags']))
    resolved = sum(bool(u['unique_resolution']) for u in updates)
    summary['root_receipt_new_handling_applied_positions'] += resolved
    summary['source_confirmation_followup'] = {'positions_processed': 5, 'resolved_or_context_explained': resolved,
                                              'specific_sense_still_unresolved': 5 - resolved}
    summary['queue_counts'] = {k: len(v) for k, v in report['queues'].items()}
    summary['claims'] = 'Versioned follow-up from actual snapshot bindings. Contextual phrase explanations are explicitly non-native; source wording verification alone is not unique lexical sense resolution. No new browser claim from this formatter.'
    if summary['root_receipt_new_handling_applied_positions'] + summary['prior_common_baseline_only_positions'] + len(remaining) != summary['reviewed_unique_positions']:
        raise ValueError('Unique position reconciliation failed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-evidence', type=Path, required=True)
    parser.add_argument('--evidence-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence_pin = pin(args.actual_evidence)
    if evidence_pin['sha256'] != args.evidence_sha256:
        raise ValueError('Actual evidence hash differs')
    if args.output.exists():
        raise ValueError('Fresh report output required; historical reports are immutable')
    report = build(json.loads(args.actual_evidence.read_text()))
    report['input_pins'].extend([pin(BASE), evidence_pin])
    spec = importlib.util.spec_from_file_location('source_confirmation_formatter', FORMATTER)
    formatter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(formatter)
    formatter.QUEUE_LABELS['specific_remaining'] = f"{report['summary']['specific_remaining_positions']} 处具体未决"
    formatter.QUEUE_LABELS['source_anomaly_notices'] = '来源核验与校勘记录'
    formatter.CATEGORY_LABELS['source'] = '来源用法存疑'
    formatter.CATEGORY_LABELS['source_corrected'] = '校勘完成'
    formatter.CATEGORY_LABELS['source_verified'] = '来源已核实，语境已说明'
    document = formatter.render(report)
    document = document.replace('这里保留原稿告知，不重复统计词频。',
                                '这里保留来源核验、校勘和历史告知，不重复统计词频。')
    history = ['<h2>本次五处更新与完整旧记录</h2>']
    for row in report['records']:
        if not row.get('source_confirmation_update'):
            continue
        update = row['source_confirmation_update']
        history.append('<section class="entry"><h3>' + html.escape(row['word']) + '</h3><p>' +
                       html.escape(update['meaning_zh']) + '</p><p>' + html.escape(update['reason']) + '</p>')
        current = update.get('current_context_evidence', {})
        for key in ('paper_id', 'sentence_id', 'english', 'translation'):
            if current.get(key):
                history.append('<p>' + html.escape(str(current[key])) + '</p>')
        if update.get('remaining_reason'):
            history.append('<p>仍未唯一判定：' + html.escape(update['remaining_reason']) + '</p>')
        history.append('</section>')
        history.append('<details class="entry"><summary>' + html.escape(row['word']) + ' · 修改前完整记录</summary><pre>' +
                       html.escape(json.dumps(row['source_confirmation_previous_record'], ensure_ascii=False, indent=2)) + '</pre></details>')
    document = document.replace('</main>', '\n'.join(history) + '</main>')
    args.output.mkdir(parents=True)
    (args.output / 'pending-v2.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'pending-v2.html').write_text(document)
    receipt = {'schema': 'five-source-confirmations-report-generation.v1', 'input_pins': [pin(BASE), pin(FORMATTER), evidence_pin],
               'summary': report['summary'], 'outputs': [pin(args.output / n) for n in ('pending-v2.json', 'pending-v2.html')],
               'database_writes': 0, 'browser_accepted': False}
    (args.output / 'generation-receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
