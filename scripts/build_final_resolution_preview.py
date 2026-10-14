"""Derive the authorized final two-book preview from committed immutable children.

This is a presentation-only lane. It never applies a plan, changes a reader,
rebuilds a database, switches the shelf, or imports/publishes an Anki package.
Every edited accepted page has a complete, executable inverse.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from copy import deepcopy
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anki_pipeline import residual_optimization as ro, sense_frequency as sf, sense_display as sd
from anki_pipeline import source_confirmations as sc
from anki_pipeline import eleven_semantic_resolution as semantic
from anki_pipeline.sense_chunks import render_sentence_pair
from anki_pipeline.translation_alignment import validate_translation_alignment
from anki_pipeline.native_example_usage import _Offsets, _source_classes
from anki_pipeline.packaging import (_highlight_example, _chunk_translation,
    _example_chunk_ranges, _annotate_sentence_chunks, _source_jump, render_preview)
from scripts import apply_source_confirmations as prior
from scripts import build_residual_optimization_preview as renderer
from scripts import patch_exam_usage_preview as owner
from scripts import update_exam_usage_preview as preview

OWNED = ROOT / 'output/eleven-resolution-20261014/preview-own'
ACCEPTED = ROOT / 'output/source-confirmations-20261014/cards-own/preview-v1'
BOOKS = {'redbook', 'redbook2027'}
SCHEMAS = {'source': 'final-source-corrections-plan.v1', 'semantic': semantic.PLAN,
    'context': 'final-reader-contexts-plan.v1'}
canonical, digest, require = sc.canonical, sc.digest, sc.require
atomic_write = prior.atomic_write
pin = prior.pin


def order_transitions(items):
    """Order one card's lanes by their immutable identities, rejecting branches."""
    require(items, 'empty transition chain')
    children = {card['child_snapshot_id'] for _, card in items}
    require(len(children) == len(items), 'duplicate child in transition chain')
    roots = [item for item in items if item[1].get('parent_snapshot_id') not in children]
    require(len(roots) == 1, 'transition chain has multiple roots or a cycle')
    result, pending = [roots[0]], [item for item in items if item is not roots[0]]
    while pending:
        matches = [item for item in pending if item[1].get('parent_snapshot_id') == result[-1][1]['child_snapshot_id']]
        require(len(matches) == 1, 'transition chain is disconnected or branching')
        result.append(matches[0]); pending.remove(matches[0])
    return result


def historical(node):
    for part in (node, *preview._ancestors(node)):
        if renderer._inside_history(part) or part.attrs.get('data-native-ownership-history') or part.attrs.get('data-source-confirmation-history'):
            return True
        if {'sf-source-confirmation-history', 'sf-semantic-resolution-history', 'sf-final-context-history', 'sf-final-history'} & part.classes:
            return True
    return False


def default_native(page, aliases):
    result = []
    for node in _Offsets(page, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or historical(node):
            continue
        values = sd._native_examples(page[node.start:node.end], aliases)
        require(len(values) == 1, 'native example has no exact unique identity')
        result.append((node, values[0]))
    return result


def source_history_markup(row):
    history = row.get('source_provenance', {}).get('source_confirmation')
    if not history:
        return ''
    original = history['original_row']
    require(digest(original) == history['original_row_sha256'], 'complete source history seal differs')
    for origin in [*history.get('origins', []), *history.get('incoming', {}).get('origins', [])]:
        original_origin = origin.get('original_row')
        checksum = origin.get('original_row_sha256') or origin.get('row_sha256')
        require(original_origin is not None and checksum and digest(original_origin) == checksum,
            'supplemental compound original ownership row seal differs')
    evidence = history.get('evidence')
    expanded = ro.read_json(evidence) if isinstance(evidence, dict) and {'file', 'sha256'} <= set(evidence) else evidence
    context = {'source_confirmation': history, 'complete_evidence': expanded}
    # Exact fields remain in the JSON; the readable text does not replace them.
    return ('<details class="sf-source-confirmation-history sf-final-history"><summary>来源校勘、原句与完整旧审查</summary>'
        '<p class="sf-reason" style="white-space:pre-wrap">' + html.escape(history.get('note') or history.get('reason') or '') + '</p>'
        '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：' + html.escape(original['reason']) + '</p>'
        '<p class="sf-source">原文：' + html.escape(original['english']) + '</p>'
        '<p class="sf-source">原译：' + html.escape(original['translation']) + '</p>'
        '<p class="sf-source">原目标标记：' + html.escape(canonical(original.get('target_range'))) + '</p>'
        '<p class="sf-source">原来源：' + html.escape(original.get('source', original['sentence_id'])) + '</p>'
        '<details><summary>完整原记录、词典与来源证据、历史权属</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
        + html.escape(canonical(context)) + '</pre></details></details>')


def inline_source_history(page, data, aliases):
    if not any(row.get('source_provenance', {}).get('source_confirmation') for row in data['occurrences']):
        return page, []
    rows = {row['occurrence_id']: row for row in data['occurrences']}
    edits = []
    for node in _Offsets(page, aliases).root.walk():
        if 'sf-example' not in node.classes or historical(node):
            continue
        row = rows.get(node.attrs.get('data-sf-occurrence-id'))
        markup = source_history_markup(row) if row else ''
        if markup:
            require(node.closed is not None, 'source history lacks a sentence boundary')
            edits.append((node.closed, node.closed, _source_classes(markup, aliases)))
    return preview.apply_edits(page, edits)


def retired_source_history(page, card, aliases, target_urls):
    """A retired binding keeps its original sentence as an explicitly old example."""
    retirements = card.get('source_retirements', [])
    if not retirements:
        return page, []
    reports = [node for node in _Offsets(page, aliases).root.walk() if 'sf-report' in node.classes and not historical(node)]
    require(reports and reports[0].closed is not None, 'retired source records lack a report archive boundary')
    items = []
    for item in retirements:
        original = item['original_row']
        if item.get('original_row_sha256'):
            require(digest(original) == item['original_row_sha256'], 'retired source original row seal differs')
        target_card = item.get('target_card_id') or item.get('target_cardid')
        target_url = target_urls.get((card['book_id'], target_card)) if target_card else None
        link = '<p class="sf-source"><a href="' + html.escape(target_url, quote=True) + '">校勘后的词卡与原句</a></p>' if target_url else ''
        # The complete accepted display remains available in the record below.
        # This retired sentence shows the exact physical original wording.
        view = deepcopy(original); view.pop('display', None)
        items.append('<article class="sf-example sf-archived-example" data-sf-occurrence-id="' + original['occurrence_id'] + '">'
            + render_sentence_pair(view) + '<details class="sf-final-history"><summary>旧错误绑定与完整校勘记录（不计词频）</summary>'
            + '<p class="sf-history-old-reason" style="white-space:pre-wrap">' + html.escape(original['reason']) + '</p>' + link
            + '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(canonical(item)) + '</pre></details></article>')
    markup = '<details class="sf-inline-history"><summary>本句校勘前的历史绑定</summary>' + ''.join(items) + '</details>'
    boundary = reports[0].closed
    return preview.apply_edits(page, [(boundary, boundary, _source_classes(markup, aliases))])


def _changed_source_sentences(before, after):
    old = {row['occurrence_id']: row for row in before['occurrences']}
    current = {row['occurrence_id']: row for row in after['occurrences']}
    fields = ('english', 'translation', 'alignment', 'target_range', 'source_provenance')
    sids = {row['sentence_id'] for oid, row in old.items() if oid not in current or any(row.get(field) != current[oid].get(field) for field in fields)}
    sids.update(row['sentence_id'] for oid, row in current.items() if oid not in old)
    return sids


def _native_pair(row, targets, aliases, cloze_answers=()):
    example = {'text': row['english'], 'translation': row['translation'],
        'translation_source': 'codex', 'translation_alignment': row['alignment']}
    en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
    from anki_pipeline.sense_chunks import _accent_chunks
    selected = renderer.finest_target_ids(en_chunks, row['alignment'], targets)
    en = _annotate_sentence_chunks(_accent_chunks(_highlight_example(row['english'], '', '', list(cloze_answers),
        target_ranges=targets, chunk_ranges=en_chunks, preserve_source=True), selected), row['alignment'])
    zh = _annotate_sentence_chunks(_accent_chunks(_chunk_translation(row['translation'], zh_chunks), selected), row['alignment'])
    return _source_classes(en, aliases), _source_classes(zh, aliases)


def _jump(row, targets, exam_base):
    jump = owner.original_paper_jump(row, targets[0], exam_base)
    if len(targets) > 1:
        for field in ('latex_url', 'full_paper_url'):
            value = urlsplit(jump[field]); query = dict(parse_qsl(value.query))
            query['anki-codex-en'] = json.dumps(targets, separators=(',', ':'))
            jump[field] = urlunsplit((value.scheme, value.netloc, value.path, urlencode(query), value.fragment))
    return jump


def native_markup(rows, ordinal, aliases, exam_base, projections=None):
    row = rows[0]
    views = [(projections or {}).get(r['occurrence_id'], {}).get('view') or r.get('display') or r for r in rows]
    view = views[0]
    require(all((r['english'], r['translation'], r['alignment']) == (view['english'], view['translation'], view['alignment']) for r in views),
        'incoming native source siblings disagree')
    targets = [list(span) for span in sorted({tuple(r['target_range']) for r in views})]
    physical_targets = [list(span) for span in sorted({tuple(r['target_range']) for r in rows})]
    en, zh = _native_pair(view, targets, aliases, view.get('cloze_answers', []))
    return _source_classes('<li class="example-card" data-final-source-native-occurrence="' + row['occurrence_id'] + '">'
        '<div class="example-heading"><span class="index-tag">' + str(ordinal) + '</span><span class="example-text">' + en + '</span>'
        + _source_jump(_jump(row, physical_targets, exam_base)) + '</div><span class="example-translation" data-translation-source="codex">'
        '<span class="translate-tag">翻译</span> ' + zh + '</span><span class="example-source">' + html.escape(row['source'])
        + '</span><span class="sentence-status" role="status"></span>' + source_history_markup(row) + '</li>', aliases)


def correct_native(page, before, after, aliases, exam_base, shown_before=None, projections=None):
    """Update/retire only an exact old sentence and preserve every other byte."""
    affected = _changed_source_sentences(before, after)
    originals = defaultdict(list); current = defaultdict(list)
    for row in (shown_before or before)['occurrences']:
        originals[row['sentence_id']].append(row)
    for row in after['occurrences']:
        current[row['sentence_id']].append(row)
    edits, updated, retired, unchanged, removed_marks = [], 0, 0, 0, 0
    unaffected_fragments = []
    natives = default_native(page, aliases)
    existing_sids = {(value.get('jump') or {}).get('sentence_id') for _, value in natives}
    for node, value in natives:
        jump = value.get('jump') or {}
        sid = jump.get('sentence_id')
        if sid not in affected:
            unchanged += 1; unaffected_fragments.append(page[node.start:node.end]); continue
        old_rows = originals.get(sid, [])
        require(old_rows, 'changed native has no immutable old source row')
        candidates = [row for row in old_rows if any(value['english'] == view['english'] and value['translation'] == view['translation']
            for view in [row, row.get('display') or row])]
        require(candidates, 'native old bilingual text differs from its accepted physical/display row: ' + sid)
        require(any(row['english_hash'] == jump.get('english_hash') and
            row['source_provenance'].get('reviewedContentHash') == jump.get('reviewed_content_hash') for row in candidates),
            'native source hash differs from immutable accepted authority: ' + sid)
        targets = sorted(set(map(tuple, value['target_ranges'])))
        require(any(left <= r['target_range'][0] < r['target_range'][1] <= right for left, right in jump['target_ranges'] for r in candidates),
            'native source jump lacks an owned physical occurrence')
        old_targets = {(row.get('display') or row)['target_range'][0]: (row.get('display') or row)['target_range'][1] for row in candidates}
        require(any(left <= a < b <= right for left, right in targets for a, b in old_targets.items()),
            'changed native mark lacks an owned old occurrence')
        rows = current.get(sid, [])
        if not rows:
            edits.append((node.start, node.end, '')); retired += 1; continue
        row = rows[0]
        views = [(projections or {}).get(other['occurrence_id'], {}).get('view') or other.get('display') or other for other in rows]
        view = views[0]
        require(all((other['english'], other['translation'], other['alignment']) ==
            (view['english'], view['translation'], view['alignment']) for other in views),
            'corrected native source rows disagree')
        new_targets = [list(span) for span in sorted({tuple(other['target_range']) for other in views})]
        physical_targets = [list(span) for span in sorted({tuple(other['target_range']) for other in rows})]
        owned_old_targets = {tuple((r.get('display') or r)['target_range']) for r in candidates}
        removed_marks += sum(tuple(span) not in owned_old_targets for span in targets)
        en, zh = node.descendant('example-text'), node.descendant('example-translation')
        require(en and zh and en.closed is not None and zh.closed is not None, 'native bilingual boundaries incomplete')
        en_markup, zh_markup = _native_pair(view, new_targets, aliases, view.get('cloze_answers', value.get('cloze_answers', [])))
        edits.append((en.opened, en.closed, en_markup))
        labels = [part for part in zh.walk() if 'translate-tag' in part.classes]
        require(len(labels) <= 1, 'native translation label duplicated')
        left = labels[0].end if labels else zh.opened
        if page[left:zh.closed].startswith(' '):
            left += 1
        edits.append((left, zh.closed, zh_markup))
        anchors = [part for part in node.walk() if 'sentence-jump' in part.classes]
        require(len(anchors) == 1, 'changed native has no unique reader jump')
        edits.append((anchors[0].start, anchors[0].end, _source_classes(_source_jump(_jump(row, physical_targets, exam_base)), aliases)))
        source_details = [part for part in node.children if 'sf-source-confirmation-history' in part.classes]
        markup = _source_classes(source_history_markup(row), aliases)
        if source_details:
            require(len(source_details) == 1, 'native source history duplicated')
            edits.append((source_details[0].start, source_details[0].end, markup))
        elif markup:
            edits.append((node.closed, node.closed, markup))
        updated += 1
    incoming_sids = sorted(sid for sid in affected if sid not in existing_sids and current.get(sid)
        and any(row['occurrence_id'] not in {old['occurrence_id'] for old in before['occurrences']} for row in current[sid]))
    if incoming_sids:
        lists = {node.parent.start: node.parent for node, _ in natives}
        require(len(lists) == 1, 'incoming native has no exact existing example list')
        parent = next(iter(lists.values()))
        require(parent.tag in {'ol', 'ul'} and parent.closed is not None, 'incoming native example list is incomplete')
        additions = ''.join(native_markup(current[sid], len(natives) - retired + index + 1, aliases, exam_base,
            projections=projections) for index, sid in enumerate(incoming_sids))
        edits.append((parent.closed, parent.closed, additions))
    revised, inverse = preview.apply_edits(page, edits)
    require(preview.restore_edits(revised, inverse) == page, 'generic native source inverse differs')
    before_unchanged = Counter(digest(fragment.encode()) for fragment in unaffected_fragments)
    after_unchanged = Counter(digest(revised[node.start:node.end].encode()) for node, value in default_native(revised, aliases)
        if (value.get('jump') or {}).get('sentence_id') not in affected)
    require(before_unchanged == after_unchanged, 'unrelated current native bytes changed')
    return revised, inverse, {'updated': updated, 'retired': retired, 'inserted': len(incoming_sids),
        'removed_stale_marks': removed_marks, 'unchanged_native_examples': unchanged,
        'unchanged_native_bytes_exact': True, 'affected_sentence_ids': sorted(affected)}


def _edit_span(span, start, end, replacement):
    """Map authored boundaries through the one exact source correction."""
    left, right = span; delta = len(replacement) - (end - start)
    if left <= start and end <= right:
        return [left, right + delta]
    if right <= start:
        return [left, right]
    if left >= end:
        return [left + delta, right + delta]
    raise ValueError('source correction crosses an authored chunk boundary')


def derive_projection(row, original, display):
    """A new render-only composite witness; never a forged v2 source certificate."""
    approved = original.get('display')
    require(approved, 'composite origin has no original approved display')
    sd.validate_display(approved, original)
    if display != approved:
        overlay = display.get('residual_optimization')
        require(overlay and original['occurrence_id'] in overlay['occurrence_ids'], 'fine composite origin has no exact accepted projection binding')
        require(digest(overlay['before']) == overlay['before_sha256'] and digest(overlay['after']) == overlay['after_sha256'], 'fine composite origin ledger seal differs')
        renderer.validate_presentation_view(approved, display)
        invariant = {'english', 'english_hash', 'translation', 'translation_hash', 'alignment', 'residual_optimization', 'display_hash'}
        require({k: v for k, v in approved.items() if k not in invariant} == {k: v for k, v in display.items() if k not in invariant},
            'fine composite origin changed its original source/target authority')
    view = {key: deepcopy(display[key]) for key in ('english', 'translation', 'target_range', 'alignment', 'cloze_answers')}
    history = row['source_provenance']['source_confirmation']
    metadata = history.get('metadata_only') is True
    require(row['translation'] == original['translation'], 'composite projection cannot invent a translation')
    if metadata:
        require(all(row.get(key) == original.get(key) for key in ('english', 'translation', 'target_range', 'alignment')),
            'metadata-only projection changed linguistic inputs')
        edit, raw_start = None, None
    else:
        old, new = original['english'], row['english']
        require(view['english'].count(old) == 1, 'corrected composite has no unique complete source segment')
        raw_start = view['english'].index(old)
        common_start = 0
        while common_start < min(len(old), len(new)) and old[common_start] == new[common_start]:
            common_start += 1
        common_end = 0
        while common_end < min(len(old), len(new)) - common_start and old[len(old) - common_end - 1] == new[len(new) - common_end - 1]:
            common_end += 1
        old_end = len(old) - common_end; new_end = len(new) - common_end
        edit = {'range': [raw_start + common_start, raw_start + old_end], 'old': old[common_start:old_end], 'new': new[common_start:new_end]}
        left, right = edit['range']
        require(view['english'][left:right] == edit['old'], 'composite edit source differs')
        view['english'] = view['english'][:left] + edit['new'] + view['english'][right:]
        view['target_range'] = [raw_start + value for value in row['target_range']]
        for chunk in view['alignment']['alignments']:
            chunk['en'] = _edit_span(chunk['en'], left, right, edit['new'])
        for answer in view['cloze_answers']:
            answer['start'], answer['end'] = _edit_span([answer['start'], answer['end']], left, right, edit['new'])
            answer['word'] = view['english'][answer['start']:answer['end']]
        require(view['translation'].count(row['translation']) == 1, 'corrected composite has no unique original translation segment')
        zh_start = view['translation'].index(row['translation'])
        target_left, target_right = view['target_range']
        indexed = {tuple(chunk['en']): chunk for chunk in view['alignment']['alignments']
            if not (target_left <= chunk['en'][0] < chunk['en'][1] <= target_right)}
        for chunk in row['alignment']['alignments']:
            projected = deepcopy(chunk)
            projected['en'] = [raw_start + value for value in chunk['en']]
            projected['zh'] = [[zh_start + value for value in span] for span in chunk['zh']]
            indexed[tuple(projected['en'])] = projected
        view['alignment']['alignments'] = sorted(indexed.values(), key=lambda chunk: chunk['en'])
    view['alignment']['englishHash'] = sf._sha(view['english'])
    view['alignment']['translationHash'] = sf._sha(view['translation'])
    validate_translation_alignment(view['english'], view['translation'], view['alignment'])
    require(view['english'][slice(*view['target_range'])] == row['english'][slice(*row['target_range'])], 'render-only composite target differs from current owned token')
    view.update(english_hash=sf._sha(view['english']), translation_hash=sf._sha(view['translation']))
    witness = {'schema': 'final-source-composite-projection.v1', 'metadata_only': metadata,
        'original_row': original, 'original_row_sha256': digest(original), 'original_display': display,
        'original_display_sha256': digest(display), 'physical_context_sha256': sd._raw_context_hash(row),
        'current_source_revision': history['source_revision'], 'exact_composite_edit': edit,
        'source_segment_start': raw_start, 'view': view, 'physical_source_payload_modified': False,
        'old_v2_authority_modified': False, 'source_jump_uses_current_physical_metadata': True}
    witness['projection_sha256'] = digest(witness)
    return witness


def derive_projections(before, after, shown_before, previous, origin_resolver=None):
    old = {r['occurrence_id']: r for r in before['occurrences']} if before else {}
    shown = {r['occurrence_id']: r for r in shown_before['occurrences']} if shown_before else {}
    result = {}
    for row in after['occurrences']:
        oid = row['occurrence_id']
        if oid in previous:
            witness = previous[oid]
            require(witness['physical_context_sha256'] == sd._raw_context_hash(row), 'retained composite current physical context changed')
            result[oid] = witness; continue
        history = row.get('source_provenance', {}).get('source_confirmation', {})
        if history.get('schema') != 'final-source-confirmation-row.v1' or row.get('display'):
            continue
        original = history['original_row']
        require(digest(original) == history['original_row_sha256'], 'composite original row differs')
        accepted = shown.get(original['occurrence_id'])
        if accepted is not None and old.get(original['occurrence_id']) == original:
            display = accepted.get('display')
            binding = {'accepted_same_card_snapshot_id': before['snapshot_id']}
        elif origin_resolver:
            display, binding = origin_resolver(history, original)
        else:
            display, binding = original.get('display'), {'original_display_from_sealed_history': True}
        if display:
            witness = derive_projection(row, original, display)
            witness['accepted_origin_lineage'] = binding
            witness['projection_sha256'] = digest({k: v for k, v in witness.items() if k != 'projection_sha256'})
            result[oid] = witness
    return result


def project_composites(page, data, projections, aliases, *, to_raw=False):
    if not projections:
        return page, []
    rows = {r['occurrence_id']: r for r in data['occurrences']}
    edits, seen = [], set()
    for article in _Offsets(page, aliases).root.walk():
        oid = article.attrs.get('data-sf-occurrence-id')
        if 'sf-example' not in article.classes or historical(article) or oid not in projections:
            continue
        row, witness = rows[oid], projections[oid]
        require(witness.get('projection_sha256') == digest({k: v for k, v in witness.items() if k != 'projection_sha256'}),
            'render-only composite witness seal differs')
        require(witness['physical_context_sha256'] == sd._raw_context_hash(row), 'composite projection physical source witness differs')
        pairs = [node for node in article.children if 'sf-sentence-pair' in node.classes]
        require(len(pairs) == 1, 'composite current sentence pair is not unique')
        pair = pairs[0]; expected = witness['view'] if to_raw else row.get('display') or row
        for name, key in [('sf-en', 'english'), ('sf-zh', 'translation')]:
            node = pair.descendant(name)
            require(node is not None and sd._text_and_ranges(sd._Tree(page[node.opened:node.closed]).root)[0] == expected[key], 'composite current bilingual text differs')
        rendered = render_sentence_pair(row if to_raw else witness['view'])
        if not to_raw:
            display = witness['original_display']
            comparisons = display.get('source_comparisons', display.get('residual_optimization', {}).get('after', {}).get('source_comparisons', []))
            rendered = rendered[:-6] + renderer._comparison_markup(comparisons, len(witness['view']['alignment']['alignments'])) + '</div>'
        edits.append((pair.start, pair.end, _source_classes(rendered, aliases))); seen.add(oid)
    require(seen == set(projections), 'render-only composite has no exact current sentence')
    return preview.apply_edits(page, edits)


def context_projection_witnesses(before, after, card, validated, *, shown_before=None, exam_base=None):
    """Bind independently replayed context views without changing raw/v2 rows."""
    require(before['occurrences'] == after['occurrences'], 'reader context lane changed immutable raw/v2 occurrence bytes')
    supplied = card.get('display_projections', {})
    stored = after.get('exam_usage_policy', {}).get('final_reader_contexts', {}).get('projections')
    require(supplied == stored == validated, 'reader context plan/policy/replayed projection map differs')
    rows = {row['occurrence_id']: row for row in after['occurrences']}
    shown = {row['occurrence_id']: row for row in (shown_before or before)['occurrences']}
    result = {}
    for oid, projection in supplied.items():
        require(oid in rows and projection.get('schema') == 'final-reader-context-projection.v1', 'foreign reader context projection')
        row = rows[oid]; original = projection['original_row']
        require(original == row, 'reader context projection original differs from unchanged physical row')
        display = projection['new_display']
        view = {key: deepcopy(display[key]) for key in ('english', 'translation', 'target_range', 'alignment', 'cloze_answers', 'english_hash', 'translation_hash')}
        validate_translation_alignment(view['english'], view['translation'], view['alignment'])
        require(view['english'][slice(*view['target_range'])] == row['english'][slice(*row['target_range'])], 'reader context projection changed owned token')
        require(view['english_hash'] == sf._sha(view['english']) and view['translation_hash'] == sf._sha(view['translation']), 'reader context projection text hashes differ')
        witness = {'schema': 'final-source-composite-projection.v1', 'kind': 'reader_context_only',
            'physical_context_sha256': sd._raw_context_hash(row), 'original_row': original,
            'original_row_sha256': digest(original), 'original_display': projection.get('original_display', original.get('display')),
            'view': view, 'reader_context_certificate': projection, 'physical_source_payload_modified': False,
            'old_v2_authority_modified': False, 'source_jump_uses_current_physical_metadata': True}
        witness['accepted_previous_presentation'] = deepcopy(shown[oid].get('display', original.get('display')))
        jump = urlsplit(projection['context_source_jump'])
        base = urlsplit(exam_base) if exam_base else jump
        witness['current_context_source_jump'] = urlunsplit((base.scheme, base.netloc, jump.path, jump.query, jump.fragment))
        witness['projection_sha256'] = digest(witness); result[oid] = witness
    return result


def context_history_markup(witnesses):
    return '<details class="sf-final-context-history"><summary>本句题干校勘、原组合句与完整旧区块</summary>' + ''.join(
        '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：' + html.escape(w['original_row']['reason']) + '</p>'
        '<p class="sf-source">原组合句：' + html.escape(w['original_display']['english']) + '</p>'
        '<p class="sf-source">原组合句译文：' + html.escape(w['original_display']['translation']) + '</p>'
        '<p class="sf-source"><a href="' + html.escape(w['current_context_source_jump'], quote=True) + '">查看当前校勘题干</a></p>'
        '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(canonical({
            'reader_context_certificate': w['reader_context_certificate'],
            'accepted_previous_presentation': w['accepted_previous_presentation']})) + '</pre>'
        for w in witnesses) + '</details>'


def inline_context_history(page, projections, aliases):
    edits = []
    for article in _Offsets(page, aliases).root.walk():
        oid = article.attrs.get('data-sf-occurrence-id')
        if 'sf-example' not in article.classes or historical(article) or oid not in projections:
            continue
        witness = projections[oid]
        if witness.get('kind') == 'reader_context_only':
            edits.append((article.closed, article.closed, _source_classes(context_history_markup([witness]), aliases)))
    return preview.apply_edits(page, edits)


def project_context_native(page, before, projections, aliases):
    if not projections:
        return page, [], {'updated': 0, 'unchanged_native_bytes_exact': True}
    rows = {r['occurrence_id']: r for r in before['occurrences']}
    edits, changed, unaffected = [], 0, []
    for node, native in default_native(page, aliases):
        matches = [(rows[oid], witness) for oid, witness in projections.items()
            if rows[oid].get('display') and (rows[oid]['display']['english'], rows[oid]['display']['translation']) ==
            (native['english'], native['translation']) and (native.get('jump') or {}).get('sentence_id') == rows[oid]['sentence_id']]
        if not matches:
            unaffected.append(digest(page[node.start:node.end].encode())); continue
        view = matches[0][1]['view']
        require(all((w['view']['english'], w['view']['translation'], w['view']['alignment']) ==
            (view['english'], view['translation'], view['alignment']) for _, w in matches), 'same native context has conflicting views')
        require(all(native['jump']['english_hash'] == row['english_hash'] and native['jump']['reviewed_content_hash'] ==
            row['source_provenance'].get('reviewedContentHash') for row, _ in matches), 'native context physical jump differs')
        old_text, new_text = native['english'], view['english']
        left = 0
        while left < min(len(old_text), len(new_text)) and old_text[left] == new_text[left]:
            left += 1
        tail = 0
        while tail < min(len(old_text), len(new_text)) - left and old_text[-tail - 1] == new_text[-tail - 1]:
            tail += 1
        end = len(old_text) - tail; replacement = new_text[left:len(new_text) - tail]
        targets = set()
        for span in native['target_ranges']:
            mapped = _edit_span(span, left, end, replacement)
            if mapped[0] < mapped[1]:
                require(old_text[slice(*span)] == new_text[slice(*mapped)], 'context correction changed a retained native target token')
                targets.add(tuple(mapped))
        targets.update(tuple(w['view']['target_range']) for _, w in matches)
        en, zh = node.descendant('example-text'), node.descendant('example-translation')
        require(en and zh and en.closed is not None and zh.closed is not None, 'native context bilingual boundaries missing')
        en_markup, zh_markup = _native_pair(view, sorted(targets), aliases, view['cloze_answers'])
        labels = [part for part in zh.walk() if 'translate-tag' in part.classes]
        require(len(labels) <= 1, 'native context translation label duplicated')
        start = labels[0].end if labels else zh.opened
        if page[start:zh.closed].startswith(' '):
            start += 1
        edits.extend([(en.opened, en.closed, en_markup), (start, zh.closed, zh_markup),
            (node.closed, node.closed, _source_classes(context_history_markup([w for _, w in matches]), aliases))])
        changed += 1
    revised, inverse = preview.apply_edits(page, edits)
    current_unaffected = Counter(digest(revised[node.start:node.end].encode()) for node, value in default_native(revised, aliases)
        if not any((value.get('jump') or {}).get('sentence_id') == rows[oid]['sentence_id'] and
            (value['english'], value['translation']) == (w['view']['english'], w['view']['translation']) for oid, w in projections.items()))
    require(Counter(unaffected) == current_unaffected, 'unrelated current native context bytes changed')
    return revised, inverse, {'updated': changed, 'unchanged_native_bytes_exact': True}


def source_anomaly_badge(page, data, aliases):
    ids = {row['occurrence_id'] for row in data['occurrences'] if row.get('semantic_review', {}).get('schema') == 'eleven-semantic-row-review.v1'
        and row['semantic_review'].get('action') == 'source_anomaly_explained'}
    if not ids:
        return page, []
    edits, badges = [], 0
    tree = _Offsets(page, aliases).root
    for node in tree.walk():
        if 'sf-example' not in node.classes or historical(node) or node.attrs.get('data-sf-occurrence-id') not in ids:
            continue
        require(not any('sf-sense' in parent.classes for parent in preview._ancestors(node)), 'source anomaly was assigned a dictionary sense')
        labels = [part for part in node.walk() if not historical(part) and 'sf-status' in part.classes]
        if labels:
            require(len(labels) == 1, 'source anomaly has duplicate status labels')
            edits.append((labels[0].opened, labels[0].closed, '原文结构异常'))
        else:
            edits.append((node.opened, node.opened, _source_classes('<span class="sf-status">原文结构异常</span>', aliases)))
        badges += 1
    for node in tree.walk():
        if 'sf-pending' not in node.classes or historical(node):
            continue
        members = {part.attrs.get('data-sf-occurrence-id') for part in node.walk() if 'sf-example' in part.classes and not historical(part)}
        if members != ids:
            continue
        summaries = [part for part in node.children if part.tag == 'summary']
        hints = [part for part in node.children if 'sf-hint' in part.classes]
        if summaries:
            require(len(summaries) == 1, 'source anomaly disclosure summary duplicated')
            edits.append((summaries[0].opened, summaries[0].closed, '原文结构异常'))
        for hint in hints:
            edits.append((hint.opened, hint.closed, '来源原文已核验，结构说明与兼容分析保留；本处未分配标准词典义项。'))
    revised, inverse = preview.apply_edits(page, edits)
    require(badges == len(ids), 'source anomaly has no exact current sentence badge')
    return revised, inverse


def project_record(data, entries):
    return ro.presentation_record(data, display_updates=entries)


def retain_entries(before, after, entries):
    old, new = ({r['occurrence_id']: r for r in data['occurrences']} for data in (before, after))
    result = []
    for item in entries:
        require(digest(item['before']) == item['before_sha256'] and digest(item['after']) == item['after_sha256'], 'retained projection seal differs')
        kept = []
        for oid in item['occurrence_ids']:
            require(oid in old, 'retained projection has no immutable old occurrence')
            if oid not in new or not new[oid].get('display'):
                continue
            require(new[oid]['display'] == old[oid].get('display'), 'retained projection display changed')
            for field in ('english', 'translation', 'target_range', 'alignment', 'source_provenance'):
                require(new[oid].get(field) == old[oid].get(field), 'retained projection physical source changed')
            kept.append(oid)
        if kept:
            copy = deepcopy(item); copy['occurrence_ids'] = kept
            for field in ('book_id', 'card_id', 'child_snapshot_id'):
                copy.pop(field, None)
            result.append(copy)
    return result


def restore_transition(page, proof):
    for name in reversed(proof['inverse_order']):
        page = preview.restore_edits(page, proof[name])
    return page


def render_transition(page, before, after, card, *, source_url, target_url,
        exam_base, db, target_urls, display_updates=(), lane='semantic',
        retained_projections=None, origin_resolver=None, validated_context=None):
    aliases = renderer.source_class_aliases(page)
    inverses, order = {}, []
    unchanged_native = [page[node.start:node.end] for node, _ in default_native(page, aliases)] if lane == 'semantic' else []
    def save(name, result):
        revised, inverse, *extra = result
        inverses[name] = inverse; order.append(name)
        return (revised, *extra)
    bases = list(re.finditer(r'<base\b[^>]*>', page, re.I))
    require(len(bases) <= 1, 'source page contains duplicate bases')
    asset_base = source_url; working = page
    edits = []
    if bases:
        match = re.search(r'\bhref=["\']([^"\']+)["\']', bases[0][0], re.I)
        require(match, 'source base is not exact')
        asset_base = html.unescape(match[1]); edits.append((bases[0].start(), bases[0].end(), ''))
    working, = save('base_inverse', preview.apply_edits(working, edits))
    shown_before = project_record(before, display_updates)
    previous_projections = retained_projections or {}
    current_projections = derive_projections(before, after, shown_before, previous_projections, origin_resolver)
    context_projections = {}
    if lane == 'context':
        require(validated_context is not None, 'reader context requires independent current source replay')
        context_projections = context_projection_witnesses(before, after, card, validated_context,
            shown_before=shown_before, exam_base=exam_base)
        require(not set(current_projections) & set(context_projections), 'reader context conflicts with an existing source composite')
        current_projections.update(context_projections)
    working, = save('composite_normalization_inverse', project_composites(working, before, previous_projections, aliases, to_raw=True))
    working, comparisons = save('comparison_inverse', prior.source_report_comparisons(working, shown_before, aliases))
    working, bridge = save('bridge_inverse', renderer.source_report_bridge(working, shown_before, aliases=aliases))
    if lane == 'source':
        working, native_stats = save('native_inverse', correct_native(working, before, after, aliases, exam_base,
            shown_before, current_projections))
    elif lane == 'context':
        working, native_stats = save('native_inverse', project_context_native(working, before, context_projections, aliases))
    else:
        working, = save('native_inverse', (working, []))
        native_stats = {'updated': 0, 'retired': 0, 'unchanged_native_examples': len(unchanged_native), 'unchanged_native_bytes_exact': True}
    shown_entries = retain_entries(before, after, display_updates)
    shown_after = project_record(after, shown_entries)
    documents = renderer.history_documents(db, after) if db is not None else {}
    jumps = owner._source_jumps(after, exam_base)
    for row in after['occurrences']:
        if row['source_provenance'].get('source_confirmation'):
            jumps[row['occurrence_id']] = owner.original_paper_jump(row, row['target_range'], exam_base)
    require(not card.get('new_definitions'), 'finite final preview cannot append unreviewed dictionary senses')
    ledger = {'new_definitions': [], 'excluded': [], 'prior_wrong_lemma_ids': []}
    working, frequency, breakdown = save('report_inverse', preview.render_page(working, before, after, ledger,
        source_url=asset_base, target_url=target_url, aliases=aliases, target_urls=target_urls,
        ownership_history_documents=documents, source_jumps=jumps))
    working, projection = save('projection_inverse', prior.project_current_reports(working, after, shown_after, aliases))
    working, = save('composite_projection_inverse', project_composites(working, after, current_projections, aliases))
    working, = save('context_history_inverse', inline_context_history(working, current_projections, aliases))
    working, = save('source_history_inverse', inline_source_history(working, after, aliases))
    semantic_result = semantic.render_semantic_history(working, after, aliases) if any(
        row.get('semantic_review', {}).get('schema') == 'eleven-semantic-row-review.v1' for row in after['occurrences']) else (working, [])
    working, = save('semantic_history_inverse', semantic_result)
    working, = save('anomaly_badge_inverse', source_anomaly_badge(working, after, aliases))
    working, = save('retired_history_inverse', retired_source_history(working, card, aliases, target_urls))
    require('data-residual-source-report-scaffold=' not in working, 'temporary report scaffold escaped')
    proof = {**inverses, 'inverse_order': order, 'source_sha256': digest(page.encode()),
        'after_sha256': digest(working.encode()), 'parent_snapshot_id': before['snapshot_id'],
        'snapshot_id': after['snapshot_id'], 'lane': lane, 'native': native_stats,
        'render_only_composite_projections': current_projections,
        'projection': projection, 'source_report_bridge': bridge, 'source_report_comparisons': comparisons,
        'inverse_exact': restore_transition(working, {'inverse_order': order, **inverses}) == page}
    require(proof['inverse_exact'], 'complete transition inverse differs')
    if lane == 'semantic':
        require(Counter(digest(fragment.encode()) for fragment in unchanged_native) == Counter(
            digest(working[node.start:node.end].encode()) for node, _ in default_native(working, aliases)),
            'semantic classification changed current accepted native bytes')
    return working, frequency, breakdown, proof, shown_entries, current_projections


def supplemental_card(after, *, exam_base, target_url, lexeme=None, projections=None):
    lexeme = lexeme or after.get('supplemental_lexeme') or after.get('definition_provenance', {}).get('supplemental_lexeme')
    require(isinstance(lexeme, dict), 'new word card needs its exact supplemental lexeme source')
    definition = '\n'.join(s['pos'] + ' ' + s['text'] for s in after['senses'])
    fields = {key: '' for key in ('phonetic', 'simple_definition', 'level', 'word_forms', 'audio_filename', 'sheet', 'lesson', 'position')}
    forms = sorted({row['english'][row['target_range'][0]:row['target_range'][1]] for row in after['occurrences']
        if row['english'][row['target_range'][0]:row['target_range'][1]].casefold() != after['word'].casefold()})
    if forms:
        require(after['word'] == 'teem' and forms == ['teeming'], 'supplemental form lacks its finite native grammar evidence')
        fields['word_forms'] = '现在分词: teeming'
    card = {**fields, 'id': after['card_id'], 'word': after['word'], 'definition': definition, 'examples': [],
        'exam_frequency': preview._frequency(after['occurrences']), 'exam_frequency_breakdown': preview._breakdown(after['occurrences'], 0)}
    for row in after['occurrences']:
        view = (projections or {}).get(row['occurrence_id'], {}).get('view') or row
        card['examples'].append({'text': view['english'], 'translation': view['translation'], 'source': row['source'],
            'translation_source': 'codex', 'translation_alignment': view['alignment'], 'cloze_answers': view.get('cloze_answers', []),
            'matched_english_ranges': [view['target_range']], **_jump(row, [row['target_range']], exam_base)})
    page = render_preview(card, max_examples=0)
    native = lexeme.get('native_definition') or lexeme.get('native_sense') or after.get('definition_provenance', {}).get('native_sense') or lexeme.get('definition') or lexeme
    english = native.get('original_english') or native.get('english') or native.get('english_definition')
    chinese = native.get('original_chinese') or native.get('chinese')
    source_name = native.get('dictionary_name_zh') or native.get('source_name_zh') or native.get('dictionary') or native.get('source')
    require(english and chinese and source_name, 'supplemental card requires explicit native English, original Chinese and source')
    source = ('<p class="supplement-source">' + html.escape(str(source_name)) + ' · 补充词卡 · 原英文定义与原中文译文</p>'
        '<p class="sf-source">英文原定义：' + html.escape(english) + '</p><p class="sf-source">中文原译：' + html.escape(chinese) + '</p>'
        '<details class="sf-supplemental-lexeme"><summary>词典原定义、原译与来源证据</summary>'
        '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(canonical(lexeme)) + '</pre></details>')
    page = page.replace('</head>', '<base href="' + html.escape(target_url, quote=True) + '"><style data-supplement-preview="style">' +
        (ROOT / 'anki_pipeline/templates/sense-frequency.css').read_text() + '</style></head>', 1)
    from anki_pipeline.sense_groups import display_report
    report = preview._render_with_source_jumps(display_report(sf.report_from_record(after)),
        {row['occurrence_id']: owner.original_paper_jump(row, row['target_range'], exam_base) for row in after['occurrences']})
    marker = page.find('<section class="examples-section')
    require(marker >= 0, 'supplemental card has no existing examples section')
    page = page[:marker] + source + report + page[marker:]
    page, _ = project_composites(page, after, projections or {}, {})
    page = page.replace('</body>', '<script>' + (ROOT / 'anki_pipeline/templates/sense-frequency.js').read_text() + '</script></body>', 1)
    page, _ = inline_source_history(page, after, {})
    native_edits = [(node.closed, node.closed, source_history_markup(after['occurrences'][index]))
        for index, (node, _) in enumerate(default_native(page, {}))]
    page, _ = preview.apply_edits(page, native_edits)
    return page


def runtime_routes(source, prefix):
    """Extend only the cloned runtime's existing guarded accepted path."""
    old = re.escape('/' + str(ACCEPTED.relative_to(ROOT / 'output'))).replace('/', r'\/')
    new = re.escape(prefix).replace('/', r'\/')
    replacements, edits, patterns = 0, [], {}
    for kind in ('source-correction-cards', 'history'):
        pattern = old + r'\/(redbook|redbook2027)\/' + kind + r'\/[a-f0-9]{64}\.html$'
        literal = '/^' + pattern + '/.test(url.pathname)'
        require(source.count(literal) == 1, 'accepted runtime route is not exact: ' + kind)
        start = source.index(literal)
        addition = '(' + literal + ' || /^' + new + r'\/(redbook|redbook2027)\/' + kind + r'\/[a-f0-9]{64}\.html$/.test(url.pathname))'
        patterns[kind] = '^' + new + r'\/(redbook|redbook2027)\/' + kind + r'\/[a-f0-9]{64}\.html$'
        edits.append((start, start + len(literal), addition)); replacements += 1
    revised, inverse = preview.apply_edits(source, edits)
    require(preview.restore_edits(revised, inverse) == source, 'runtime route inverse differs')
    script = "const patterns=" + json.dumps(patterns) + ";const prefix=" + json.dumps(prefix) + ";const id='a'.repeat(64);for(const [kind,value] of Object.entries(patterns)){const r=new RegExp(value);for(const book of ['redbook','redbook2027'])if(!r.test(prefix+'/'+book+'/'+kind+'/'+id+'.html'))throw Error('positive route');for(const p of [prefix+'/other/'+kind+'/'+id+'.html',prefix+'/redbook/'+kind+'/'+id.slice(1)+'.html',prefix+'/redbook/'+kind+'/'+id+'.html?x=1','/other/redbook/'+kind+'/'+id+'.html'])if(r.test(p))throw Error('unsafe route');}"
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
    return revised, {'inverse': inverse, 'inverse_exact': True, 'extended_guards': replacements,
        'patterns': patterns, 'positive_negative_node_tests': True}


def _load_plan(lane, value, receipt_pin):
    plan = ro.read_json(value)
    require(plan.get('schema') == SCHEMAS[lane] and plan['run_id'] == digest({k: v for k, v in plan.items() if k != 'run_id'}), 'sealed final plan required: ' + lane)
    receipt = ro.read_json(receipt_pin)
    require(receipt.get('state') == 'applied' and receipt.get('run_id') == plan['run_id'], 'matching committed receipt required: ' + lane)
    require(set(card['book_id'] for card in plan['cards']) == BOOKS, 'both book bindings required')
    for file, checksum in plan.get('source_files', {}).items():
        if Path(file).suffix not in {'.db', '.sqlite', '.sqlite3'}:
            ro.read_pin({'file': file, 'sha256': checksum})
    return plan


def accepted_context(directory):
    manifest_pin = pin(directory / 'preview-manifest.json'); manifest = ro.read_json(manifest_pin)
    checkpoint_pin = manifest.get('checkpoint') or manifest.get('parent_presentation_checkpoint')
    require(checkpoint_pin, 'accepted preview has no immutable presentation checkpoint')
    checkpoint = ro.read_json(checkpoint_pin)
    cards = {(c['book_id'], c['card_id']): c for c in checkpoint['cards']}
    inherited = ro.read_json(manifest['receipt']) if manifest.get('receipt') else {'cards': []}
    source_cards = {(c['book_id'], c['card_id']): c for c in inherited['cards']}
    post = directory / 'post-adapter/receipt.json'
    post_cards = {(c['book_id'], c['card_id']): c for c in ro.read_json(pin(post))['cards']} if post.exists() else {}
    proofs = {}
    line_file = directory / 'card-proofs.jsonl'
    if line_file.exists():
        for line in line_file.read_text().splitlines():
            proof = json.loads(line); proofs[(proof['book_id'], proof['card_id'])] = proof
    return {'manifest': manifest, 'manifest_pin': manifest_pin, 'checkpoint_pin': checkpoint_pin,
        'cards': cards, 'source_cards': source_cards, 'post_cards': post_cards, 'proofs': proofs}


def accepted_entries(context, directory, book, card_id, before, page):
    key = (book, card_id); inherited = context['cards'].get(key); corrected = context['source_cards'].get(key)
    evidence = {'immutable_payload_lineage': [], 'physical_authority_modified': False}
    if corrected:
        require(sc._payload(corrected) == before, 'accepted source child differs from the first new parent')
        proof = ro.read_json(pin(directory / 'card-proofs' / book / (card_id + '.json')))
        effective = context['post_cards'].get(key)
        require(digest(page.encode()) == (effective['after_sha256'] if effective else proof['after_sha256']), 'accepted source card bytes differ')
        if effective:
            require(effective['before_sha256'] == proof['after_sha256'], 'post-adapter inverse lineage differs')
        evidence['immutable_payload_lineage'].append({'parent': corrected['parent_snapshot_id'], 'child': corrected['child_snapshot_id'], 'payload': corrected['payload_file']})
    elif inherited:
        require(ro.read_json(inherited['payload_file']) == before, 'accepted residual child differs from first new parent')
        proof = context['proofs'].get(key)
        require(proof and digest(page.encode()) == proof['after_sha256'], 'accepted residual card bytes differ')
    else:
        parsed = preview._Spans(page, renderer.source_class_aliases(page))
        require(any(n['kind'] == 'report' and n['attrs'].get('data-snapshot') == before['snapshot_id'] for n in parsed.nodes), 'unregistered accepted card lacks exact parent report')
    if not inherited:
        return [], evidence
    physical = ro.read_json(inherited['payload_file'])
    require(physical['snapshot_id'] == inherited['child_snapshot_id'], 'inherited physical snapshot differs')
    if corrected:
        require(sc._payload(corrected, True) == physical and corrected['parent_snapshot_id'] == physical['snapshot_id'], 'accepted source parent does not continue residual immutable child')
    else:
        require(physical == before, 'inherited accepted physical payload differs')
    ledger = ro.read_json(inherited['ledger_file'])
    entries = ledger.get('residual_display_updates', [])
    for item in entries:
        if item.get('book_id') is not None:
            require((item['book_id'], item['card_id'], item['child_snapshot_id']) == (book, card_id, physical['snapshot_id']), 'old residual binding is not its immutable physical authority')
    projected = retain_entries(physical, before, entries)
    evidence.update(accepted_page_sha256=digest(page.encode()), original_ledger=inherited['ledger_file'],
        residual_snapshot_id=physical['snapshot_id'], accepted_snapshot_id=before['snapshot_id'],
        projection_binding_removed_only=True, retained_entries=len(projected))
    return projected, evidence


def pending_inventory(payloads):
    from anki_pipeline.sense_groups import display_report
    anomalies, classified, common, unresolved = {}, {}, 0, {}
    for data in payloads:
        effective = display_report(sf.report_from_record(data))
        for row in effective['pending']:
            if row.get('semantic_review', {}).get('action') != 'source_anomaly_explained':
                unresolved.setdefault(row['occurrence_id'], {'occurrence_id': row['occurrence_id'], 'word': data['word'],
                    'reason': row['reason'], 'bindings': []})['bindings'].append({
                    'book_id': data['book_id'], 'card_id': data['card_id'], 'snapshot_id': data['snapshot_id']})
        for row in data['occurrences']:
            common += bool(row.get('common_sense_match'))
            review = row.get('semantic_review', {})
            if review.get('schema') != 'eleven-semantic-row-review.v1':
                continue
            identity = row['occurrence_id']
            binding = {'book_id': data['book_id'], 'card_id': data['card_id'], 'snapshot_id': data['snapshot_id']}
            if review.get('action') == 'source_anomaly_explained':
                require(data['word'] == 'as' and row['sense_id'] is None, 'only as may be an unassigned source anomaly')
                item = anomalies.setdefault(identity, {'occurrence_id': identity, 'word': 'as', 'label': '原文结构异常',
                    'workflow_status': '已完成来源说明', 'dictionary_sense_certified': False,
                    'reason': row['reason'], 'complete_review': review, 'bindings': []})
                item['bindings'].append(binding)
            elif review.get('action') == 'match_existing_sense':
                item = classified.setdefault(identity, {'occurrence_id': identity, 'word': data['word'],
                    'status': '教学主释义已审定，兼容解释保留', 'complete_review': review, 'bindings': []})
                item['bindings'].append(binding)
    return {'schema': 'final-resolution-pending-inventory.v1', 'scope': 'Current final children of the authorized source and semantic plans',
        'specific_sense_unresolved_positions': len(unresolved), 'specific_sense_unresolved_records': list(unresolved.values()),
        'source_structure_anomalies': list(anomalies.values()), 'source_structure_anomaly_positions': len(anomalies),
        'reviewed_teaching_classifications': list(classified.values()), 'reviewed_teaching_positions': len(classified),
        'preserved_common_sense_rows_in_affected_cards': common,
        'claim': '仅 as 为原文结构异常；已审定教学主释义不排除句法兼容解释。已有 common_sense_match 按共同义显示，不从 raw ambiguous 误造待匹配。'}


def validate_catalog(catalog, stage, prefix):
    """Check the shell's actual deck/card contract, including new supplements."""
    decks = {deck['id']: deck for deck in catalog['decks']}
    cards = {card['id']: card for card in catalog['cards']}
    require(len(decks) == len(catalog['decks']) and len(cards) == len(catalog['cards']), 'catalog identity duplicated')
    assigned = []
    for deck in decks.values():
        require(deck['count'] == len(deck['cardIds']) and len(set(deck['cardIds'])) == deck['count'], 'catalog deck count differs')
        for card_id in deck['cardIds']:
            require(card_id in cards and cards[card_id]['deckId'] == deck['id'], 'catalog deck/card association differs')
            assigned.append(card_id)
    require(len(assigned) == len(set(assigned)) == len(cards), 'catalog card membership is incomplete or repeated')
    for card in cards.values():
        deck = decks[card['deckId']]
        require(all(card[key] == deck[other] for key, other in [('deckName', 'name'), ('unit', 'unit'), ('lesson', 'lesson')]), 'catalog card/unit metadata differs')
        parts = urlsplit(card['previewUrl'])
        require(parts.path.startswith('/') and not parts.scheme and not parts.netloc and not parts.query and not parts.fragment and '%' not in parts.path,
            'catalog preview path is unsafe')
        if parts.path.startswith(prefix + '/'):
            path = stage / parts.path[len(prefix) + 1:]
            require(path.is_relative_to(stage) and path.is_file(), 'derived catalog page is missing')
        else:
            renderer.local_url(card['previewUrl'], ROOT / 'output')
    require(catalog['counts'] == {'cards': len(cards), 'decks': len(decks), 'examples': sum(card['exampleCount'] for card in cards.values())},
        'catalog totals differ from actual cards/decks/examples')
    return {'cards': len(cards), 'decks': len(decks), 'catalog_card_deck_counts_exact': True, 'all_card_routes_present': True}


def build(plan_pins, receipt_pins, output, exam_base, *, database=None, trial_words=()):
    plans = {lane: _load_plan(lane, value, receipt_pins[lane]) for lane, value in plan_pins.items()}
    output = Path(output).resolve()
    require(output != OWNED and output.is_relative_to(OWNED) and not output.exists(), 'fresh owned final-preview output required')
    stage = output.with_name('.' + output.name + '-stage')
    require(not stage.exists(), 'owned preview stage already exists')
    databases = {Path(plan['candidate']).resolve(strict=True) for plan in plans.values()}
    require(len(databases) == 1, 'final plan lanes refer to different databases')
    candidate = database or next(iter(databases)); candidate = Path(candidate).resolve(strict=True)
    if database:
        require(candidate.is_relative_to(ROOT / 'output/eleven-resolution-20261014') and candidate.suffix == '.sqlite3', 'trial database must remain in this task output')
    require(not any(Path(str(candidate) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')), 'render requires a committed standalone database')
    candidate_before = sc.stat_pin(candidate)
    render_inputs = [pin(path) for path in [__file__, prior.__file__, renderer.__file__, preview.__file__, owner.__file__,
        semantic.__file__, sf.__file__, sd.__file__, ROOT / 'anki_pipeline/packaging.py',
        ROOT / 'anki_pipeline/sense_chunks.py', ROOT / 'anki_pipeline/sense_groups.py',
        ROOT / 'anki_pipeline/templates/sense-frequency.css', ROOT / 'anki_pipeline/templates/sense-frequency.js']]
    context_inputs = None
    if 'context' in plans:
        from anki_pipeline import final_reader_contexts as reader_contexts
        render_inputs.append(pin(reader_contexts.__file__))
        context_inputs = reader_contexts.load_inputs(plans['context']['request'])
    grouped = defaultdict(list)
    for lane, plan in plans.items():
        for card in plan['cards']:
            grouped[(card['book_id'], card['card_id'])].append((lane, card))
    chains = {key: order_transitions(items) for key, items in grouped.items()}
    selected = {key: chain for key, chain in chains.items() if not trial_words or chain[-1][1]['word'] in trial_words}
    require(selected, 'scoped render contains no card')
    context = accepted_context(ACCEPTED)
    catalogs = {book: ro.read_json(pin(ACCEPTED / book / 'catalog.json')) for book in BOOKS}
    old_prefix = '/' + str(ACCEPTED.relative_to(ROOT / 'output')); prefix = '/' + str(output.relative_to(ROOT / 'output'))
    target_urls = {(book, row['id']): row['previewUrl'] for book, catalog in catalogs.items() for row in catalog['cards']}
    accepted_urls = dict(target_urls)
    for key in selected:
        target_urls[key] = prefix + '/' + key[0] + '/source-correction-cards/' + preview._card_filename(key[1])
    def reuse(source, target):
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        return target
    proofs, outcomes = [], []
    with closing(renderer.owned_readonly(candidate)) as db:
        for key, chain in chains.items():
            for _, card in chain:
                after = sc._payload(card)
                require(renderer.snapshot(db, *key, card['child_snapshot_id'], card['payload_sha256']) == after,
                    'committed child SQL payload differs from sealed plan')
                if card.get('parent_snapshot_id'):
                    require(renderer.snapshot(db, *key, card['parent_snapshot_id'], card['before_payload_sha256']) == sc._payload(card, True),
                        'immutable SQL parent differs from sealed plan')
            require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', key).fetchone() == (chain[-1][1]['child_snapshot_id'],), 'final active child differs from committed plan chain')
        shutil.copytree(ACCEPTED, stage, copy_function=reuse)
        origin_cache = {}
        def resolve_origin(history, original):
            key = history['original_book_id'], history['original_card_id']
            parent_id = history['original_parent_snapshot_id']
            cache_key = (*key, parent_id)
            if cache_key not in origin_cache:
                parent = sc._read_parent(db, *key, parent_id)
                origin_page = renderer.local_url(accepted_urls[key], ROOT / 'output').read_text()
                origin_entries, origin_proof = accepted_entries(context, ACCEPTED, *key, parent, origin_page)
                shown = project_record(parent, origin_entries)
                origin_cache[cache_key] = ({r['occurrence_id']: r for r in shown['occurrences']}, parent, origin_proof)
            shown, parent, binding = origin_cache[cache_key]
            physical = next((r for r in parent['occurrences'] if r['occurrence_id'] == original['occurrence_id']), None)
            require(physical == original, 'composite incoming origin differs from immutable accepted source parent')
            return shown[original['occurrence_id']].get('display'), binding
        for index, (key, chain) in enumerate(sorted(selected.items()), 1):
            book, card_id = key; first = chain[0][1]; after = sc._payload(chain[-1][1])
            catalog = catalogs[book]; rows = [row for row in catalog['cards'] if row['id'] == card_id]
            require(len(rows) <= 1, 'accepted catalog card identity duplicated')
            proof_chain = []
            if first.get('parent_snapshot_id') is None:
                require(not rows and first.get('created') is True, 'supplemental card already exists in accepted catalog')
                projections = derive_projections(None, sc._payload(first), None, {}, resolve_origin)
                original = None; page = supplemental_card(sc._payload(first), exam_base=exam_base, target_url=target_urls[key],
                    lexeme=first['supplemental_lexeme'], projections=projections); entries = []
                lineage = {'new_supplemental_card': True, 'immutable_child': first['payload_file']}
                following = chain[1:]
                definition = '\n'.join(s['pos'] + ' ' + s['text'] for s in after['senses'])
                lexeme = first['supplemental_lexeme']
                association = lexeme.get('book_unit_mapping') or after['definition_provenance'].get('book_unit_mapping')
                require(isinstance(association, dict) and association.get('book_id') == book, 'new supplemental card lacks exact original book/unit association')
                source_cards = [item for item in catalog['cards'] if item['id'] == association['source_card_id']]
                require(len(source_cards) == 1, 'new supplemental unit association has no exact original card')
                source_card = source_cards[0]
                decks = [item for item in catalog['decks'] if item['id'] == source_card['deckId']]
                require(len(decks) == 1, 'new supplemental unit association has no exact existing deck')
                row = {'id': card_id, 'word': after['word'], 'unit': source_card['unit'], 'lesson': source_card['lesson'],
                    'position': source_card['position'] + '-校勘', 'deckId': source_card['deckId'], 'deckName': source_card['deckName'], 'definition': definition,
                    'source_definition_summary': definition, 'source_example_count': 0, 'supplemental_lexeme': True,
                    'supplemental_book_unit_association': association, 'original_learning_card_created': False}
                catalog['cards'].append(row)
                decks[0]['cardIds'].append(card_id); decks[0]['count'] += 1
            else:
                require(rows, 'existing immutable card missing from accepted catalog')
                row = rows[0]; source = renderer.local_url(row['previewUrl'], ROOT / 'output')
                original = source.read_text(); page = original; projections = {}
                entries, lineage = accepted_entries(context, ACCEPTED, book, card_id, sc._payload(first, True), page)
                following = chain
            retirements = []
            for lane, card in following:
                before, child = sc._payload(card, True), sc._payload(card)
                retirements.extend(card.get('source_retirements', []))
                render_card = {**card, 'source_retirements': retirements}
                validated_context = None
                if lane == 'context':
                    validated_context = deepcopy(card['display_projections'])
                    physical_rows = {r['occurrence_id']: r for r in before['occurrences']}
                    for oid, projection in validated_context.items():
                        require(reader_contexts.validate_projection(projection, physical_rows[oid], before,
                            plans['context']['request'], context_inputs) == projection['new_display'],
                            'independent reader context view replay differs')
                page, frequency, breakdown, proof, entries, projections = render_transition(page, before, child, render_card,
                    source_url=row.get('previewUrl', target_urls[key]), target_url=target_urls[key],
                    exam_base=exam_base, db=db, target_urls=target_urls, display_updates=entries, lane=lane,
                    retained_projections=projections, origin_resolver=resolve_origin, validated_context=validated_context)
                proof_chain.append(proof)
            frequency, breakdown = preview._frequency(after['occurrences']), preview._breakdown(after['occurrences'], 0)
            restored = page
            for proof in reversed(proof_chain):
                restored = restore_transition(restored, proof)
            require(original is None or restored == original, 'full parent-to-final inverse chain differs')
            relative = Path(book) / 'source-correction-cards' / preview._card_filename(card_id)
            atomic_write(stage / relative, page)
            row.update(previewUrl=target_urls[key], exam_frequency=frequency, exam_frequency_breakdown=breakdown,
                exampleCount=frequency['matched_sentences'], final_resolution={'snapshot_id': after['snapshot_id'], 'lanes': [lane for lane, _ in chain]})
            if 'definition' in row:
                row['definition'] = preview._catalog_summary(row['definition'], frequency)
            proof = {'book_id': book, 'card_id': card_id, 'word': after['word'], 'target_url': target_urls[key],
                'parent_snapshot_id': first.get('parent_snapshot_id'), 'snapshot_id': after['snapshot_id'],
                'source_sha256': digest(original.encode()) if original is not None else None, 'after_sha256': digest(page.encode()),
                'accepted_lineage': lineage, 'transitions': proof_chain, 'source_inverse_exact': original is None or restored == original,
                'render_only_composite_projections': projections,
                'created': original is None, 'source_inverse_applicable': original is not None,
                'committed_active_child_SQL_readback_exact': True}
            atomic_write(stage / 'final-card-proofs' / book / (card_id + '.json'), canonical(proof)); proofs.append(proof)
            outcomes.append({k: proof[k] for k in ('book_id', 'card_id', 'word', 'snapshot_id', 'created')})
            print(json.dumps({'rendered': index, 'cards': len(selected), 'word': after['word'], 'book': book}), flush=True)
    runtime_file = ACCEPTED / 'assets/library-preview.js'
    runtime, runtime_proof = runtime_routes(runtime_file.read_text(), prefix)
    atomic_write(stage / 'assets/library-preview.js', runtime)
    catalog_proofs = {}
    for book, catalog in catalogs.items():
        for row in catalog['cards']:
            if row['previewUrl'].startswith(old_prefix + '/'):
                row['previewUrl'] = prefix + row['previewUrl'][len(old_prefix):]
        if 'counts' in catalog:
            catalog['counts']['examples'] = sum(row['exampleCount'] for row in catalog['cards'])
            catalog['counts']['cards'] = len(catalog['cards'])
            catalog['counts']['decks'] = len(catalog['decks'])
        catalog_proofs[book] = validate_catalog(catalog, stage, prefix)
        atomic_write(stage / book / 'catalog.json', canonical(catalog))
        atomic_write(stage / book / 'preview-library.html', (ACCEPTED / book / 'preview-library.html').read_text().replace(old_prefix + '/', prefix + '/'))
    inventory = pending_inventory(sc._payload(chain[-1][1]) for chain in chains.values())
    atomic_write(stage / 'pending-inventory.json', canonical(inventory))
    inventory_html = '<!doctype html><meta charset="utf-8"><title>最终来源说明与教学主释义记录</title><main><h1>最终来源说明与教学主释义记录</h1><p>' + html.escape(inventory['claim']) + '</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + html.escape(canonical(inventory)) + '</pre></main>'
    atomic_write(stage / 'pending-inventory.html', inventory_html)
    atomic_write(stage / 'final-card-proofs.jsonl', '\n'.join(canonical(proof) for proof in proofs) + '\n')
    atomic_write(stage / 'accepted-parent-preview-manifest.json', (ACCEPTED / 'preview-manifest.json').read_bytes())
    require(sc.stat_pin(candidate) == candidate_before, 'candidate database changed during read-only rendering')
    for captured in render_inputs:
        ro.read_pin(captured)
    ro.read_pin(context['manifest_pin'])
    manifest = {'schema': 'final-resolution-preview.v1', 'output': str(output), 'parent_preview': str(ACCEPTED),
        'parent_preview_manifest': context['manifest_pin'], 'parent_presentation_checkpoint': context['checkpoint_pin'],
        'plans': plan_pins, 'receipts': receipt_pins, 'render_driver': pin(__file__), 'rendered_cards': len(proofs),
        'render_input_pins': render_inputs,
        'created_cards': sum(proof['created'] for proof in proofs), 'outcomes': outcomes,
        'source_inverses_exact': all(proof['source_inverse_exact'] for proof in proofs),
        'committed_active_children_checked': len(chains), 'database': {'file': str(candidate), 'stat': candidate_before},
        'runtime_routes': runtime_proof, 'pending_inventory': {'file': str(output / 'pending-inventory.json'), 'sha256': digest(canonical(inventory).encode())},
        'catalog_validation': catalog_proofs,
        'trial_words': list(trial_words), 'database_writes': False, 'reader_writes': False, 'shelf_switched': False, 'browser_accepted': False,
        'books': {book: {'cards': len(catalog['cards']), 'catalog_url': prefix + '/' + book + '/catalog.json', 'entry_url': prefix + '/' + book + '/preview-library.html'} for book, catalog in catalogs.items()}}
    atomic_write(stage / 'preview-manifest.json', canonical(manifest))
    os.replace(stage, output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for lane in SCHEMAS:
        parser.add_argument('--' + lane + '-plan', type=Path)
        parser.add_argument('--' + lane + '-plan-sha256')
        parser.add_argument('--' + lane + '-receipt', type=Path)
        parser.add_argument('--' + lane + '-receipt-sha256')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exam-base', default='http://192.168.3.5:8765')
    parser.add_argument('--database', type=Path, help='An affected-only committed scratch database in task output')
    parser.add_argument('--trial-word', action='append', default=[])
    args = parser.parse_args(argv); plans, receipts = {}, {}
    for lane in SCHEMAS:
        path = getattr(args, lane + '_plan')
        values = [path, getattr(args, lane + '_plan_sha256'), getattr(args, lane + '_receipt'), getattr(args, lane + '_receipt_sha256')]
        if any(values):
            require(all(values), 'all plan/receipt pins required for lane: ' + lane)
            plans[lane] = {'file': str(path.resolve()), 'sha256': values[1]}
            receipts[lane] = {'file': str(values[2].resolve()), 'sha256': values[3]}
    require(plans, 'at least one committed lane is required')
    manifest = build(plans, receipts, args.output, args.exam_base, database=args.database, trial_words=args.trial_word)
    print(json.dumps({'manifest': pin(Path(manifest['output']) / 'preview-manifest.json'),
        'rendered_cards': manifest['rendered_cards'], 'created_cards': manifest['created_cards'], 'source_inverses_exact': manifest['source_inverses_exact'],
        'database_writes': False, 'browser_accepted': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
