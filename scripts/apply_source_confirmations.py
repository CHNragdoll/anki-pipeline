"""Prepare/apply/restore the authorized local five-source snapshot correction."""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from anki_pipeline import source_confirmations as sc
from anki_pipeline import residual_optimization as ro

OWNED = ROOT / 'output/source-confirmations-20261014/cards-own'
PROTECTED = ROOT / 'data/sense-frequency-usage-20261012-v5-recovery.sqlite3'
CANDIDATE = ROOT / 'data/sense-frequency-optimized-20261013.sqlite3'
EVIDENCE = ROOT / 'output/source-confirmations-20261014/evidence/source-evidence.json'
EVIDENCE_SHA = 'a3eff08e8b7cacc6455a0596e9920607f797b4c56c9ccb5de437532c922c0c1d'
CANONICAL = ROOT / 'output/residual-optimization-20261013/integration/semantic-adapter-own/canonical-merged-decisions-v2.json'
ACCEPTED = ROOT / 'output/residual-optimization-20261013/engineering/preview-own/root-full-preview-v1'


def pin(path):
    path = Path(path).resolve(strict=True)
    return {'file': str(path), 'sha256': sc.digest(path.read_bytes())}


def owned(path):
    path = Path(path).resolve()
    sc.require(path.is_relative_to(OWNED) and path != OWNED, 'artifacts must stay in the cards-owned output')
    return path


def load_plan(path, sha):
    path = owned(path)
    plan = ro.read_json({'file': str(path), 'sha256': sha})
    sc.require(Path(plan['candidate']).resolve() == CANDIDATE and Path(plan['protected']['file']).resolve() == PROTECTED,
               'only the authorized optimized candidate may be mutated')
    sc.require(plan['summary']['cards'] == 180 and plan['summary']['corrected_rows'] == 134 and plan['summary']['metadata_only_rows'] == 110,
               'authorized source correction scope differs')
    return plan


def atomic_write(path, raw):
    """Never open a reused hardlink for writing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(raw if isinstance(raw, bytes) else raw.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def rehearse(plan, output):
    """Rehearse real five-case parents plus small paragraph metadata examples."""
    output = owned(output)
    sc.require(not output.exists(), 'fresh rehearsal directory required')
    output.mkdir(parents=True)
    database = output / 'affected-only.sqlite3'
    selected = [card for card in plan['cards'] if card['word'] in {'number', 'jug', 'juggle', 'remote', 'pick', 'as'}]
    for book in plan['request']['expected_books']:
        candidates = [card for card in plan['cards'] if card['book_id'] == book and card not in selected]
        if candidates:
            selected.append(min(candidates, key=lambda c: c['original_count']))
    with closing(sqlite3.connect(database)) as db:
        db.executescript(sf_schema())
        for card in selected:
            parent = sc._payload(card, True)
            ro._insert(db, parent)
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', (card['book_id'], card['card_id'], card['parent_snapshot_id']))
        db.commit()
        before = sc._graph(db)
    trial = deepcopy(plan)
    trial['cards'] = deepcopy(selected)
    trial['summary']['cards'] = len(selected)
    trial['candidate'], trial['candidate_stat'], trial['active_graph_sha256'] = str(database), sc.stat_pin(database), sc.digest(before)
    trial['run_id'] = sc.digest({key: value for key, value in trial.items() if key != 'run_id'})
    try:
        sc.apply(trial, root_write_approved=True, fail_after_cards=2)
        raise AssertionError('failure injection did not fail')
    except RuntimeError as error:
        sc.require('injected' in str(error), 'unexpected rehearsal failure')
    with closing(sc._connect(database)) as db:
        sc.require(sc._graph(db) == before, 'failed transaction changed the active graph')
        for card in selected:
            parent = sc._payload(card, True)
            sc.require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == parent,
                       'failed transaction changed an immutable parent')
            ro._reconcile(db, parent)
    # A rolled-back SQLite write can change the scratch file mtime. Rebind only
    # after proving the restored graph and all selected parent rows are exact.
    trial['candidate_stat'] = sc.stat_pin(database)
    trial['run_id'] = sc.digest({key: value for key, value in trial.items() if key != 'run_id'})
    applied = sc.apply(trial, root_write_approved=True)
    repeated = sc.apply(trial, root_write_approved=True)
    restored = sc.rollback(trial, root_write_approved=True)
    repeated_restore = sc.rollback(trial, root_write_approved=True)
    with closing(sc._connect(database)) as db:
        sc.require(sc._graph(db) == before, 'rehearsal restoration differs')
        for card in selected:
            sc.require(sc._read_parent(db, card['book_id'], card['card_id'], card['parent_snapshot_id']) == sc._payload(card, True), 'rehearsal immutable parent differs')
            ro._reconcile(db, sc._payload(card))
        sc.require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok' and not db.execute('PRAGMA foreign_key_check').fetchall(), 'rehearsal normalized database integrity failed')
    result = {'schema': 'five-source-confirmations-rehearsal.v1', 'actual_candidate_modified': False,
        'plan_run_id': plan['run_id'], 'trial_run_id': trial['run_id'], 'cards': len(selected), 'full_prepared_scope_cards': len(plan['cards']),
        'database_bytes': database.stat().st_size, 'injected_failure_atomic': True, 'apply_idempotent': repeated['already_applied'],
        'rollback_idempotent': repeated_restore['already_rolled_back'], 'full_parent_recovery_exact': True,
        'normalized_before_after_exact': True, 'integrity_check': 'ok',
        'applied': applied['state'], 'restored': restored['state']}
    atomic_write(output / 'rehearsal.json', sc.canonical(result))
    return result


def sf_schema():
    from anki_pipeline import sense_frequency as sf
    return sf._SQL + '\nPRAGMA user_version=2;'


def bind_published_sources(plan, input_pin, output):
    """Freeze exact current reader records and published paper bytes into plan."""
    from anki_pipeline import sense_frequency as sf
    from scripts import update_exam_usage_preview as preview
    from scripts import build_residual_optimization_preview as renderer
    revisions = ro.read_json(plan['request']['source_revisions'])
    source_root = ROOT.parent / 'exam-library/data/sources/exam-library/structured'
    codex_root = source_root / 'codex-translations/kaoyan'
    manifest_pin = pin(codex_root / 'manifest.json')
    source_manifest = ro.read_json(manifest_pin)
    published, index_rows = [], {}
    for key, meta in revisions.items():
        stem = meta['sentence_id'].split(':')[1]
        index_pin = pin(codex_root / (stem + '.json'))
        paper_pin = pin(source_root / 'papers/kaoyan' / (stem + '.json'))
        sc.require(paper_pin['sha256'] == meta['structured_paper_hash'], 'published structured source differs from planned correction')
        index = ro.read_json(index_pin)
        row = next(row for row in index['sentences'] if row['id'] == meta['sentence_id'])
        approved = next(row for row in source_manifest['papers'] if row['paperId'] == row_paper_id(meta))
        sc.require(approved['sha256'] == index_pin['sha256'], 'published reader manifest/index binding differs')
        sc.require(row['englishHash'] == meta['english_hash'] and row['reviewedContentHash'] == meta['reviewed_content_hash']
            and row['sourceHash'] == meta['source_hash'], 'published reader text/review/source hash differs')
        reviewed = sf._sha(row['translationZh'] + '\0' + json.dumps(row['alignments'], ensure_ascii=False, separators=(',', ':')))
        sc.require(reviewed == meta['reviewed_content_hash'], 'published reviewed content hash does not reproduce')
        published.append({'key': key, 'index': index_pin, 'structured_paper': paper_pin, 'sentence': deepcopy(row)})
        for item in index['sentences']:
            index_rows[item['id']] = item
    rows_checked = 0
    for card in plan['cards']:
        after = sc._payload(card)
        for row in after['occurrences']:
            history = row['source_provenance'].get('source_confirmation')
            if not history or history['key'] not in sc.CORRECTIONS:
                continue
            current = index_rows[row['sentence_id']]
            sc.require(row['english'] == current['english'] and row['english_hash'] == current['englishHash']
                and row['translation'] == current['translationZh'] and row['translation_hash'] == current['translationHash']
                and row['alignment']['alignments'] == current['alignments'], 'corrected card bilingual/chunk text differs from published reader')
            sc.require(row['source_provenance']['reviewedContentHash'] == current['reviewedContentHash']
                and row['source_provenance']['sourceHash'] == current['sourceHash']
                and row['source_provenance']['paragraphRange'] == [current['start'], current['end']], 'corrected card source jump/provenance differs from published reader')
            rows_checked += 1
    # One corrected jug position leaves the original card and enters juggle in each book.
    sc.require(rows_checked == 244, 'published correction provenance scope differs')
    wire = deepcopy(plan)
    wire['published_source_guard'] = {'manifest': manifest_pin, 'papers': published, 'checked_current_rows': rows_checked}
    wire['prepared_payload_plan'] = input_pin
    producer_files = {name: sha for name, sha in plan['source_files'].items()
                      if Path(name).parent == ROOT / 'anki_pipeline'}
    for name, sha in producer_files.items():
        sc.require(pin(name)['sha256'] == sha, 'prepared payload producer implementation changed')
    wire['payload_producer_guard'] = {'prepared_plan': input_pin, 'implementation_files': producer_files,
        'payload_leaf_hashes_preserved': True,
        'driver_role': 'published source binding, scratch rehearsal, apply and rendering; no payload regeneration'}
    for row in published:
        for field in ('index', 'structured_paper'):
            wire['source_files'][row[field]['file']] = row[field]['sha256']
    wire['source_files'][manifest_pin['file']] = manifest_pin['sha256']
    wire['source_files'][input_pin['file']] = input_pin['sha256']
    for module in (__file__, sc.__file__, renderer.__file__, preview.__file__):
        wire['source_files'][str(Path(module).resolve())] = pin(module)['sha256']
    for operation in wire['summary']['operations']:
        operation['note'] = sc.NOTES[operation['key']]
        card = next(c for c in wire['cards'] if c['book_id'] == operation['book_id'] and c['card_id'] == operation['card_id'])
        target = next(r for r in sc._payload(card)['occurrences'] if r['occurrence_id'] == operation['occurrence_id'])
        operation['status'], operation['sense_id'] = target['status'], target['sense_id']
    wire['run_id'] = sc.digest({key: value for key, value in wire.items() if key != 'run_id'})
    output = owned(output)
    sc.require(not output.exists(), 'fresh final bound plan path required')
    atomic_write(output, sc.canonical(wire))
    return {'plan': pin(output), 'run_id': wire['run_id'], 'summary': wire['summary'], 'published_rows_verified': rows_checked}


def row_paper_id(meta):
    return ':'.join(meta['sentence_id'].split(':')[:2])


def inline_history(page, data, aliases):
    from anki_pipeline.native_example_usage import _Offsets
    from scripts import update_exam_usage_preview as preview
    rows = {row['occurrence_id']: row for row in data['occurrences']}
    edits = []
    for node in _Offsets(page, aliases).root.walk():
        if node.tag != 'article' or 'sf-example' not in node.classes:
            continue
        row = rows.get(node.attrs.get('data-sf-occurrence-id'))
        history = row and row['source_provenance'].get('source_confirmation')
        if not history:
            continue
        original = history['original_row']
        sc.require(sc.digest(original) == history['original_row_sha256'], 'inline full source history differs')
        evidence = ro.read_json(history['evidence'])
        citations = ''.join('<p class="sf-source"><a href="' + html.escape(item['url'], quote=True)
            + '" target="_blank" rel="noopener">' + html.escape(item['url']) + '</a></p>'
            for item in evidence['items'] if item.get('url') and item['key'] in {history['key'], 'remote-technical' if history['key'] == 'remote' else ''})
        prior_rehomes = ''.join('<p class="sf-history-old-reason" style="white-space:pre-wrap">旧转归完整说明：'
            + html.escape(h['source_parent_row']['reason']) + '</p>' for h in original.get('ownership_history', []))
        prior_notices = history.get('prior_card_source_notices', [])
        if prior_notices:
            prior_rehomes += '<details><summary>历史 jug 卡片完整来源与转归审查（原判断）</summary>'
            for notice in prior_notices:
                old_reason = notice.get('reason') or notice.get('decision', {}).get('reason') or notice.get('original_row', {}).get('reason') or ''
                prior_rehomes += '<p class="sf-history-old-reason" style="white-space:pre-wrap">' + html.escape(old_reason) + '</p>'
            prior_rehomes += '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(sc.canonical(prior_notices)) + '</pre></details>'
        note = ('<details class="sf-source-confirmation-history"><summary>来源核验、原句与完整旧审查</summary>'
            '<p class="sf-reason">' + html.escape(history['note']) + '</p>' + citations + '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：'
            + html.escape(original['reason']) + '</p><p class="sf-source">原文：' + html.escape(original['english'])
            + '</p><p class="sf-source">原译：' + html.escape(original['translation']) + '</p>' + prior_rehomes + '<details><summary>完整原记录、来源与审查证据</summary>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(sc.canonical(history)) + '</pre></details></details>')
        sc.require(node.closed is not None, 'current sentence history has no exact insertion boundary')
        edits.append((node.closed, node.closed, note))
    return preview.apply_edits(page, edits)


def correct_native_examples(page, before, after, aliases, exam_base):
    """Exact, invertible source derivation using the shared card/chunk renderer."""
    from anki_pipeline import sense_display as sd
    from anki_pipeline.native_example_usage import _Offsets, _source_classes
    from anki_pipeline.packaging import (_highlight_example, _chunk_translation,
        _example_chunk_ranges, _annotate_sentence_chunks, _source_jump)
    from scripts import patch_exam_usage_preview as owner
    from scripts import update_exam_usage_preview as preview
    originals = {row['occurrence_id']: row for row in before['occurrences']}
    by_sentence = {}
    for row in after['occurrences']:
        history = row['source_provenance'].get('source_confirmation')
        if history:
            by_sentence.setdefault(row['sentence_id'], []).append(row)
    edits, changed, removed, removed_marks = [], 0, 0, 0
    for node in _Offsets(page, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes:
            continue
        ancestor = node.parent
        historical = False
        while ancestor:
            historical |= bool(ancestor.attrs.get('data-native-ownership-history')) or bool(ancestor.attrs.get('data-source-confirmation-history'))
            ancestor = ancestor.parent
        if historical:
            continue
        markup = page[node.start:node.end]
        parsed = sd._native_examples(markup, aliases)
        sc.require(len(parsed) == 1, 'native example identity differs')
        native = parsed[0]
        jump = native.get('jump')
        if not jump:
            continue
        sid = jump['sentence_id']
        corrected_key = next((key for key, c in sc.CORRECTIONS.items() if sid == c['sentence_id']), None)
        special_rows = by_sentence.get(sid, [])
        if not corrected_key and not special_rows:
            continue
        if before['word'] == 'jug' and corrected_key == 'jug':
            sc.require(not special_rows and any(r['sentence_id'] == sid for r in before['occurrences']), 'jug removed position differs')
            edits.append((node.start, node.end, '')); removed += 1
            continue
        sc.require(special_rows, 'new source sentence has no exact active row')
        row = special_rows[0]
        old_rows = [r['source_provenance']['source_confirmation']['original_row'] for r in special_rows]
        sc.require(all(r['english'] == native['english'] and r['translation'] == native['translation'] for r in old_rows), 'native source text differs from exact historical row')
        sc.require(all(r['source_provenance']['reviewedContentHash'] == jump['reviewed_content_hash'] for r in old_rows),
                   'native source reviewed context differs from exact historical row')
        sc.require(all(r['english'] == row['english'] and r['translation'] == row['translation'] and r['alignment'] == row['alignment'] for r in special_rows), 'new native source rows disagree')
        targets = native['target_ranges']
        sc.require(set(map(tuple, targets)) == set(map(tuple, jump['target_ranges'])), 'native marks differ from declared source jump')
        sc.require(any(span[0] <= old['target_range'][0] < old['target_range'][1] <= span[1]
                       for old in old_rows for span in targets), 'native declared marks have no actual owned occurrence')
        removed_marks += len([span for span in targets if tuple(span) not in {tuple(old['target_range']) for old in old_rows}])
        if corrected_key:
            correction = sc.CORRECTIONS[corrected_key]
            sc.require(jump['english_hash'] == correction['old_hash'], 'native old source hash differs')
        targets = sorted({tuple(current['target_range']) for current in special_rows})
        example = {'text': row['english'], 'translation': row['translation'], 'translation_source': 'codex', 'translation_alignment': row['alignment']}
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        en_markup = _highlight_example(row['english'], '', '', native['cloze_answers'], target_ranges=targets, chunk_ranges=en_chunks, preserve_source=True)
        zh_markup = _chunk_translation(row['translation'], zh_chunks)
        en_markup = _source_classes(_annotate_sentence_chunks(en_markup, row['alignment']), aliases)
        zh_markup = _source_classes(_annotate_sentence_chunks(zh_markup, row['alignment']), aliases)
        en, zh = node.descendant('example-text'), node.descendant('example-translation')
        edits.append((en.opened, en.closed, en_markup))
        tags = [part for part in zh.walk() if 'translate-tag' in part.classes]
        sc.require(len(tags) <= 1, 'native translation label is duplicated')
        left = tags[0].end if tags else zh.opened
        if page[left:zh.closed].startswith(' '):
            left += 1
        edits.append((left, zh.closed, zh_markup))
        jump_nodes = [part for part in node.walk() if 'sentence-jump' in part.classes]
        sc.require(len(jump_nodes) == 1, 'native example needs one exact source jump')
        new_jump = owner.original_paper_jump(row, targets[0], exam_base)
        # Preserve all marks in the safe shared source jump, including a repeated token.
        if len(targets) > 1:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
            for field in ('latex_url', 'full_paper_url'):
                parts = urlsplit(new_jump[field]); query = dict(parse_qsl(parts.query)); query['anki-codex-en'] = json.dumps(targets, separators=(',', ':'))
                new_jump[field] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        jump_node = jump_nodes[0]
        edits.append((jump_node.start, jump_node.end, _source_jump(new_jump)))
        changed += 1
    revised, proof = preview.apply_edits(page, edits)
    sc.require(preview.restore_edits(revised, proof) == page, 'native source derivation inverse differs')
    return revised, proof, {'updated_native_examples': changed, 'removed_wrong_jug_examples': removed,
        'removed_stale_declared_marks_not_owned': removed_marks}


def source_report_comparisons(page, shown, aliases):
    """Retire exact nested archived comparisons before the legacy report guard."""
    from anki_pipeline.native_example_usage import _Offsets
    from scripts import build_residual_optimization_preview as renderer
    from scripts import update_exam_usage_preview as preview
    rows = {row['occurrence_id']: row for row in shown['occurrences']}
    edits, blocks = [], []
    for article in _Offsets(page, aliases).root.walk():
        if 'sf-example' not in article.classes or renderer._inside_history(article):
            continue
        details = [node for node in article.walk()
                   if node.attrs.get('data-reviewed-source-comparison') == 'residual']
        if not details:
            continue
        row = rows.get(article.attrs.get('data-sf-occurrence-id'))
        sc.require(row is not None and row.get('display'), 'archived source comparison lacks pinned parent display')
        view = row['display']
        comparisons = view.get('source_comparisons', view.get('residual_optimization', {}).get('after', {}).get('source_comparisons', []))
        expected = renderer._comparison_markup(comparisons, len((view.get('alignment') or {}).get('alignments', [])))
        sc.require(''.join(page[node.start:node.end] for node in details) == expected,
                   'archived source comparison differs from pinned parent presentation')
        edits.extend((node.start, node.end, '') for node in details)
        blocks.append({'occurrence_id': row['occurrence_id'], 'details': len(details),
            'sha256': sc.digest(expected.encode()), 'source_count': page.count(expected), 'markup': expected})
    adapted, inverse = preview.apply_edits(page, edits)
    return adapted, inverse, {'details': len(edits), 'blocks': blocks}


def project_current_reports(page, after, shown, aliases):
    """Project regenerated SF reports while preserving accepted native bytes."""
    from scripts import build_residual_optimization_preview as renderer
    from scripts import update_exam_usage_preview as preview
    reports = [node for node in preview._Spans(page, aliases).nodes if node['kind'] == 'report']
    sc.require(reports, 'current report projection has no complete reports')
    source = ''.join(page[node['start']:node['end']] for node in reports)
    projected, inverse, stats = renderer.project_displays(source, after, shown, aliases=aliases)
    sc.require(preview.restore_edits(projected, inverse) == source and stats['native_pairs'] == 0,
               'current report projection changed native content or inverse')
    parts = [node for node in preview._Spans(projected, aliases).nodes if node['kind'] == 'report']
    sc.require(len(parts) == len(reports) and ''.join(projected[node['start']:node['end']] for node in parts) == projected,
               'current report projection component scope differs')
    revised, page_inverse = preview.apply_edits(page, [(old['start'], old['end'], projected[new['start']:new['end']])
        for old, new in zip(reports, parts)])
    sc.require(preview.restore_edits(revised, page_inverse) == page, 'current report projection page inverse differs')
    return revised, page_inverse, stats


def render_card(page, before, after, card, *, source_url, target_url, exam_base, db, target_urls, display_updates=None):
    from anki_pipeline import sense_frequency as sf
    from scripts import update_exam_usage_preview as preview
    from scripts import patch_exam_usage_preview as owner
    from scripts import build_residual_optimization_preview as renderer
    aliases = renderer.source_class_aliases(page)
    bases = list(re.finditer(r'<base\b[^>]*>', page, re.I))
    sc.require(len(bases) <= 1, 'source page has duplicate bases')
    asset_base = source_url
    base_inverse = []
    if bases:
        match = re.search(r'\bhref=["\']([^"\']+)["\']', bases[0][0], re.I)
        sc.require(match is not None, 'source base identity absent')
        asset_base = html.unescape(match[1])
        page0, base_inverse = preview.apply_edits(page, [(bases[0].start(), bases[0].end(), '')])
    else:
        page0 = page
    shown_before = ro.presentation_record(before, display_updates=display_updates)
    primary, comparison_inverse, comparison_proof = source_report_comparisons(page0, shown_before, aliases)
    bridged, source_bridge_inverse, source_bridge_proof = renderer.source_report_bridge(primary, shown_before, aliases=aliases)
    native, native_inverse, native_stats = correct_native_examples(bridged, before, after, aliases, exam_base)
    documents = renderer.history_documents(db, after)
    jumps = owner._source_jumps(after, exam_base)
    for row in after['occurrences']:
        if row['source_provenance'].get('source_confirmation'):
            jumps[row['occurrence_id']] = owner.original_paper_jump(row, row['target_range'], exam_base)
    additions = deepcopy(card.get('new_definitions', []))
    addition_pages = {}
    urls = {}
    for item in additions:
        evidence_html = '<!doctype html><meta charset="utf-8"><title>来源核验与短语语境释义</title><h1>语境用法（非词典原义）</h1><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(sc.canonical(item)) + '</pre>'
        name = sc.digest(evidence_html.encode()) + '.html'
        addition_pages[name] = evidence_html
        urls[item['ordinal']] = target_url.rsplit('/source-correction-cards/', 1)[0] + '/source-confirmation-evidence/' + name
        item['sense_ref'] = item['contextual_key']
    ledger = {'new_definitions': additions, 'excluded': [], 'prior_wrong_lemma_ids': []}
    shown = retained_presentation(before, after, display_updates=display_updates)
    revised, report_inverse, frequency, breakdown = preview.render_page(native, before, after, ledger,
        source_url=asset_base, target_url=target_url, aliases=aliases, target_urls=target_urls,
        appended_source_urls=urls, ownership_history_documents=documents, source_jumps=jumps)
    revised, projection_inverse, projection_stats = project_current_reports(revised, after, shown, aliases)
    revised, history_inverse = inline_history(revised, after, aliases)
    for block in comparison_proof['blocks']:
        markup = block.pop('markup')
        sc.require(revised.count(markup) == block['source_count'], 'historical source comparison was not recreated exactly')
    sc.require(revised.count('data-reviewed-source-comparison="residual"') == page.count('data-reviewed-source-comparison="residual"'),
               'historical source comparison count changed')
    restored = preview.restore_edits(revised, history_inverse)
    restored = preview.restore_edits(restored, projection_inverse)
    restored = preview.restore_edits(restored, report_inverse)
    restored = preview.restore_edits(restored, native_inverse)
    restored = preview.restore_edits(restored, source_bridge_inverse)
    restored = preview.restore_edits(restored, comparison_inverse)
    sc.require(preview.restore_edits(restored, base_inverse) == page, 'complete card source inverse differs')
    sc.require('data-residual-source-report-scaffold=' not in revised, 'temporary source report scaffold escaped rendering')
    return revised, frequency, breakdown, {'source_sha256': sc.digest(page.encode()), 'after_sha256': sc.digest(revised.encode()),
        'base_inverse': base_inverse, 'native_inverse': native_inverse, 'report_inverse': report_inverse,
        'projection_inverse': projection_inverse, 'inline_history_inverse': history_inverse,
        'source_report_bridge_inverse': source_bridge_inverse, 'source_report_bridge_certification': source_bridge_proof,
        'source_report_comparison_inverse': comparison_inverse,
        'source_report_comparison_certification': comparison_proof,
        'inverse_exact': True, 'native': native_stats, 'projection': projection_stats}, addition_pages


def retained_presentation(before, after, *, display_updates=None):
    """Replay an unchanged accepted overlay only after an exact parent comparison.

    The old writer's child guard remains intact. This finite derivation verifies
    the complete old overlay and identical physical/display inputs, then uses
    its existing display renderer against the new immutable correction child.
    """
    old_rows = {row['occurrence_id']: row for row in before['occurrences']}
    new_rows = {row['occurrence_id']: row for row in after['occurrences']}
    entries = []
    source_entries = (after.get('exam_usage_policy', {}).get('residual_display_updates', [])
                      if display_updates is None else display_updates)
    for item in source_entries:
        sc.require(sc.digest(item['before']) == item['before_sha256'] and sc.digest(item['after']) == item['after_sha256'], 'retained display projection seal differs')
        if item.get('book_id') is not None:
            sc.require((item['book_id'], item['card_id'], item['child_snapshot_id']) ==
                       (before['book_id'], before['card_id'], before['snapshot_id']), 'retained display overlay does not belong to the accepted parent')
        affected = [oid for oid in item['occurrence_ids'] if oid not in new_rows or new_rows[oid].get('display') is None]
        if affected:
            sc.require(all(oid in old_rows and (oid not in new_rows or new_rows[oid]['source_provenance'].get('source_confirmation')) for oid in affected), 'display retired without complete source-correction history')
            continue
        for oid in item['occurrence_ids']:
            sc.require(oid in old_rows and new_rows[oid]['display'] == old_rows[oid].get('display'), 'retained display bytes changed')
            for field in ('english', 'translation', 'target_range', 'alignment', 'source_provenance'):
                sc.require(new_rows[oid][field] == old_rows[oid][field], 'retained projection physical input changed')
        projected = deepcopy(item)
        for field in ('book_id', 'card_id', 'child_snapshot_id'):
            projected.pop(field, None)
        entries.append(projected)
    return ro.presentation_record(after, display_updates=entries)


def render(plan, receipt_pin, output, exam_base):
    from scripts import update_exam_usage_preview as preview
    receipt = ro.read_json(receipt_pin)
    sc.require(receipt['run_id'] == plan['run_id'] and receipt['state'] == 'applied', 'committed apply receipt required before rendering')
    output = owned(output)
    sc.require(not output.exists(), 'fresh complete preview output required')
    prefix = '/' + str(output.relative_to(ROOT / 'output'))
    old_prefix = '/' + str(ACCEPTED.relative_to(ROOT / 'output'))
    stage = output.with_name('.' + output.name + '-stage')
    sc.require(not stage.exists(), 'preview stage already exists')
    def reuse(source, target):
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        return target
    shutil.copytree(ACCEPTED, stage, copy_function=reuse)
    catalogs = {book: json.loads((ACCEPTED / book / 'catalog.json').read_text()) for book in plan['request']['expected_books']}
    accepted_manifest_pin = pin(ACCEPTED / 'preview-manifest.json')
    accepted_manifest = ro.read_json(accepted_manifest_pin)
    accepted_checkpoint = ro.read_json(accepted_manifest['checkpoint'])
    accepted_cards = {(c['book_id'], c['card_id']): c for c in accepted_checkpoint['cards']}
    all_urls = {(book, row['id']): row['previewUrl'] for book, catalog in catalogs.items() for row in catalog['cards']}
    for card in plan['cards']:
        all_urls[(card['book_id'], card['card_id'])] = prefix + '/' + card['book_id'] + '/source-correction-cards/' + preview._card_filename(card['card_id'])
    proofs, outcomes = [], []
    with closing(sc._connect(plan['candidate'])) as db:
        for card in plan['cards']:
            before, after = sc._payload(card, True), sc._payload(card)
            sc.require(sc._read_parent(db, card['book_id'], card['card_id'], card['child_snapshot_id']) == after, 'committed child differs from sealed plan')
            active = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (card['book_id'], card['card_id'])).fetchone()
            sc.require(active[0] == after['snapshot_id'], 'render current active parent guard differs')
            row = next(row for row in catalogs[card['book_id']]['cards'] if row['id'] == card['card_id'])
            source = (ROOT / 'output' / row['previewUrl'].lstrip('/')).resolve(strict=True)
            sc.require(source.is_relative_to(ROOT / 'output'), 'accepted card URL escapes web root')
            page = source.read_text()
            accepted = accepted_cards.get((card['book_id'], card['card_id']))
            display_updates, accepted_ledger_pin = None, None
            if accepted:
                sc.require(accepted['child_snapshot_id'] == before['snapshot_id']
                    and accepted['child_payload_sha256'] == card['before_payload_sha256'], 'accepted presentation ledger parent differs')
                accepted_ledger_pin = accepted['ledger_file']
                ledger = ro.read_json(accepted_ledger_pin)
                display_updates = ledger.get('residual_display_updates', [])
            target_url = all_urls[(card['book_id'], card['card_id'])]
            revised, frequency, breakdown, proof, additions = render_card(page, before, after, card,
                source_url=row['previewUrl'], target_url=target_url, exam_base=exam_base, db=db, target_urls=all_urls,
                display_updates=display_updates)
            relative = Path(card['book_id']) / 'source-correction-cards' / preview._card_filename(card['card_id'])
            atomic_write(stage / relative, revised)
            for name, content in additions.items():
                atomic_write(stage / card['book_id'] / 'source-confirmation-evidence' / name, content)
            row['previewUrl'] = target_url
            row['exam_frequency'], row['exam_frequency_breakdown'] = frequency, breakdown
            if card['original_count'] != card['new_count']:
                row['exampleCount'] = frequency['matched_sentences']
            if 'definition' in row:
                row['definition'] = preview._catalog_summary(row['definition'], frequency)
            row['source_confirmation'] = {'run_id': plan['run_id'], 'parent_snapshot_id': before['snapshot_id'], 'snapshot_id': after['snapshot_id']}
            proof.update(book_id=card['book_id'], card_id=card['card_id'], word=card['word'], source={'file': str(source), 'sha256': sc.digest(page.encode())}, target_url=target_url)
            proof['accepted_presentation_ledger'] = accepted_ledger_pin
            atomic_write(stage / 'card-proofs' / card['book_id'] / (card['card_id'] + '.json'), sc.canonical(proof))
            proofs.append(proof)
            outcomes.append({'book_id': card['book_id'], 'card_id': card['card_id'], 'word': card['word'], 'occurrences': frequency['occurrences'], 'pending': len([r for r in after['occurrences'] if r['sense_id'] is None])})
    for book, catalog in catalogs.items():
        for row in catalog['cards']:
            if row['previewUrl'].startswith(old_prefix + '/'):
                row['previewUrl'] = prefix + row['previewUrl'][len(old_prefix):]
        if 'counts' in catalog:
            catalog['counts']['examples'] = sum(row['exampleCount'] for row in catalog['cards'])
        atomic_write(stage / book / 'catalog.json', sc.canonical(catalog))
        shell = (ACCEPTED / book / 'preview-library.html').read_text()
        atomic_write(stage / book / 'preview-library.html', shell.replace(old_prefix + '/', prefix + '/'))
    # Preserve the prior complete manifest as historical evidence.
    os.replace(stage / 'preview-manifest.json', stage / 'accepted-parent-preview-manifest.json')
    atomic_write(stage / 'source-confirmation-card-proofs.jsonl', '\n'.join(sc.canonical(proof) for proof in proofs) + '\n')
    manifest = {'schema': 'five-source-confirmations-preview.v1', 'run_id': plan['run_id'], 'receipt': receipt_pin,
        'render_driver': pin(__file__), 'approved_apply_driver_sha256': plan['source_files'][str(Path(__file__).resolve())],
        'render_derivation': 'Existing guarded source_report_bridge adapts the pinned parent common display; exact source inverse retained.',
        'parent_preview': str(ACCEPTED), 'rendered_cards': len(proofs), 'source_inverses_exact': all(p['inverse_exact'] for p in proofs),
        'parent_preview_manifest': accepted_manifest_pin, 'parent_presentation_checkpoint': accepted_manifest['checkpoint'],
        'database_writes': False, 'browser_accepted': False, 'output': str(output), 'outcomes': outcomes,
        'books': {book: {'cards': len(catalog['cards']), 'catalog_url': prefix + '/' + book + '/catalog.json', 'entry_url': prefix + '/' + book + '/preview-library.html'} for book, catalog in catalogs.items()}}
    atomic_write(stage / 'preview-manifest.json', sc.canonical(manifest))
    sc.require(sc.stat_pin(plan['protected']['file']) == plan['protected']['stat'], 'protected source changed during rendering')
    os.replace(stage, output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--source-revisions', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    for name in ('apply', 'rollback'):
        command = sub.add_parser(name)
        command.add_argument('--plan', type=Path, required=True)
        command.add_argument('--plan-sha256', required=True)
        command.add_argument('--root-write-approved', action='store_true')
        command.add_argument('--receipt', type=Path, required=True)
    rehearsal = sub.add_parser('rehearse')
    render_parser = sub.add_parser('render')
    binder = sub.add_parser('bind-published')
    for command in (rehearsal, render_parser, binder):
        command.add_argument('--plan', type=Path, required=True)
        command.add_argument('--plan-sha256', required=True)
        command.add_argument('--output', type=Path, required=True)
    render_parser.add_argument('--apply-receipt', type=Path, required=True)
    render_parser.add_argument('--apply-receipt-sha256', required=True)
    render_parser.add_argument('--exam-base-url', default='http://localhost:8765')
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        sc.require(pin(EVIDENCE)['sha256'] == EVIDENCE_SHA, 'approved source evidence changed')
        request = {'schema': sc.REQUEST, 'protected': {'file': str(PROTECTED), 'stat': sc.stat_pin(PROTECTED)},
            'candidate': {'file': str(CANDIDATE)}, 'evidence': pin(EVIDENCE), 'canonical_decisions': pin(CANONICAL),
            'source_revisions': pin(args.source_revisions), 'expected_cards': 180, 'expected_corrected_rows': 134, 'expected_metadata_rows': 110,
            'expected_books': ['redbook', 'redbook2027']}
        started = time.monotonic()
        def progress(value):
            value['elapsed_seconds'] = round(time.monotonic() - started, 2)
            atomic_write(owned(args.output).with_suffix('.progress.json'), sc.canonical(value))
            print(json.dumps(value, ensure_ascii=False), file=sys.stderr, flush=True)
        result = sc.materialize(sc.prepare(request, progress=progress, artifact_root=owned(args.output)), owned(args.output))
    elif args.command in ('apply', 'rollback'):
        plan = load_plan(args.plan, args.plan_sha256)
        if args.command == 'apply':
            sc.require(plan.get('published_source_guard', {}).get('checked_current_rows') == 244,
                       'published source/reader binding required before actual apply')
        result = getattr(sc, args.command)(plan, root_write_approved=args.root_write_approved)
        receipt = owned(args.receipt)
        sc.require(not receipt.exists(), 'fresh receipt path required')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(sc.canonical(result))
    elif args.command == 'rehearse':
        result = rehearse(load_plan(args.plan, args.plan_sha256), args.output)
    elif args.command == 'bind-published':
        result = bind_published_sources(load_plan(args.plan, args.plan_sha256),
            {'file': str(owned(args.plan)), 'sha256': args.plan_sha256}, args.output)
    else:
        result = render(load_plan(args.plan, args.plan_sha256),
            {'file': str(owned(args.apply_receipt)), 'sha256': args.apply_receipt_sha256}, args.output, args.exam_base_url)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
