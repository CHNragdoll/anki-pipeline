"""Reviewed shared dictionary and bilingual source amendments.

These operations are deliberately separate from arbitrary HTML edits. Every
active source analysis participates in a caller-supplied compare-and-swap scope;
all replacements, projections, native versions and audit objects commit together.
Original dictionaries, records and authored markup remain immutable evidence.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import sense_frequency as sf
from . import study_catalog as c
from . import study_catalog_revision as rev
from .final_apkg_content import _text
from .native_example_usage import _Offsets
from .sense_chunks import render_sentence_pair
from .sense_groups import display_report


SOURCE_KEYS = ('english', 'translation', 'alignment', 'source_provenance')
ROW_KEYS = ('target_range', 'translation_ranges', 'alignment_evidence', 'reason', 'display')
SOURCE_REVISION_KEYS = ('paper_id', 'sentence_id', 'physical_source', 'english', 'english_hash',
    'translation', 'translation_hash', 'target_range', 'translation_ranges', 'alignment',
    'alignment_evidence', 'source_provenance', 'display')


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _required(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise ValueError(label + ' must be nonempty text')
    return value


def _audit_payload(value):
    if isinstance(value, list):
        return [_audit_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    references = {'catalog_source_revisions', 'catalog_source_revision_chain', 'catalog_ownership_transfers'}
    return {key: ({'retained_proof_sha256': _sha(c.canonical(item)),
                   'location': '本句完整来源链或原归属说明'} if key in references else _audit_payload(item))
            for key, item in value.items()}


def _without_catalog_audits(markup, aliases=None):
    nodes = list(_Offsets(markup, aliases or {}).root.walk())
    selected = [node for node in nodes if 'sf-catalog-revision' in node.classes]
    roots = []
    for node in selected:
        parent = node.parent
        while parent is not None and 'sf-catalog-revision' not in parent.classes:
            parent = parent.parent
        if parent is None:
            roots.append(node)
    return rev._edits(markup, [(node.start, node.end, '') for node in roots])


def _audit(before, after, reason, *, original_html='', aliases=None):
    # Each historical snapshot contains its own former visible sentence; prior
    # revision disclosures remain once on the current article, never copied
    # recursively into each later historical snapshot.
    original_html = _without_catalog_audits(original_html, aliases) if original_html else ''
    # Historical examples remain fully readable with their original chunks, but
    # must not masquerade as current .sf-example rows in year-filter counters.
    if original_html:
        edits = []
        for node in _Offsets(original_html, aliases or {}).root.walk():
            if 'sf-example' not in node.classes:
                continue
            opening = original_html[node.start:node.opened]
            revised = re.sub(r'(?<![A-Za-z0-9_-])sf-example(?![A-Za-z0-9_-])',
                             'sf-archived-example', opening)
            edits.append((node.start, node.opened, revised))
        original_html = rev._edits(original_html, edits)
    return ('<details class="sf-catalog-revision" data-reviewed-source-comparison="catalog-revision"><summary>本句完整修订记录</summary>'
            '<p>' + html.escape(reason) + '</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + html.escape(c.canonical({'before': _audit_payload(before), 'after': _audit_payload(after)})) + '</pre>'
            + original_html + '</details>')


def source_articles(raw, record):
    """Extract only current physical articles, never nested historical copies."""
    expected = {r['occurrence_id'] for r in record['occurrences']}
    articles = {}
    for node in rev._nodes(raw, 'sf-example'):
        identity = node.attrs.get('data-sf-occurrence-id')
        if identity not in expected:
            continue
        if identity in articles:
            raise ValueError('duplicate live source article')
        articles[identity] = raw[node.start:node.end]
    if set(articles) != expected:
        raise ValueError('source Definition lacks complete live physical articles')
    return articles


def repartition_definition(raw, before, after, articles, *, changed_senses=None):
    """Rebuild current report containers around exact caller-owned articles.

    Source dictionary partitions follow original sense ordinals. Membership may
    move or change; every resulting physical article must be supplied exactly
    once. Archived blocks and all bytes outside current reports are retained.
    """
    if len(before['senses']) != len(after['senses']):
        raise ValueError('dictionary membership changes require an explicit partition map')
    if set(articles) != {r['occurrence_id'] for r in after['occurrences']}:
        raise ValueError('replacement articles do not cover exact resulting physical scope')
    old_view = display_report(sf.report_from_record(before))
    new_view = display_report(sf.report_from_record(after))
    reports = rev._nodes(raw, 'sf-report')
    ordinal = 0
    owners = {}
    for index, node in enumerate(reports):
        if node.attrs.get('data-snapshot') != before['snapshot_id']:
            raise ValueError('source report has a stale active snapshot')
        meanings = [_text(raw[n.opened:n.closed]) for n in node.walk()
                    if 'sf-meaning' in n.classes and not rev._historical(n)]
        local = old_view['senses'][ordinal:ordinal + len(meanings)]
        normalize = lambda text: ' '.join(text.split())
        if [normalize(t) for t in meanings] != [normalize(s['pos'] + ' ' + s['text']) for s in local]:
            raise ValueError('source dictionary partitions differ from reviewed common senses')
        for sense in local:
            for member in sense.get('members', [sense]):
                owners[member['ordinal']] = index
        ordinal += len(meanings)
    if ordinal != len(old_view['senses']) or set(owners) != set(range(len(before['senses']))):
        raise ValueError('source reports do not cover every dictionary sense')
    partitions = [[] for _ in reports]
    for sense in new_view['senses']:
        owners_for_group = {owners[m['ordinal']] for m in sense.get('members', [sense])}
        # A source-certified common group has one canonical visible owner.
        partitions[min(owners_for_group)].append(sense)
    edits = []
    active_ids = {r['occurrence_id'] for r in before['occurrences']}
    for index, (node, local) in enumerate(zip(reports, partitions)):
        subset = deepcopy({**new_view, 'senses': local,
                           'pending': new_view['pending'] if index == 0 else [],
                           'pending_count': len(new_view['pending']) if index == 0 else 0})
        for row in [r for s in subset['senses'] for r in s['occurrences']] + subset['pending']:
            row.pop('ownership_history', None)
        generated = sf.render_report(subset)
        replacements = []
        for article in rev._nodes(generated, 'sf-example'):
            identity = article.attrs.get('data-sf-occurrence-id')
            replacements.append((article.start, article.end, articles[identity]))
        generated = rev._edits(generated, replacements)
        extras = []
        for child in node.children:
            ids = {n.attrs.get('data-sf-occurrence-id') for n in child.walk() if 'sf-example' in n.classes}
            if 'sf-pending' in child.classes and ids - active_ids:
                original = raw[child.start:child.end]
                if ids & active_ids:
                    original = _audit({'snapshot_id': before['snapshot_id']}, {},
                                      '原待核对区完整记录；当前记录已重新归并。', original_html=original)
                extras.append(original)
            elif not child.classes & {'sf-hint', 'sf-sense', 'sf-row', 'sf-pending'}:
                extras.append(raw[child.start:child.end])
        if changed_senses:
            extras.extend(changed_senses.get(index, []))
        if extras:
            end = generated.rfind('</div>')
            generated = generated[:end] + ''.join(extras) + generated[end:]
        edits.append((node.start, node.end, generated))
    return rev._edits(raw, edits)


def _record_rows(db, query, parameters):
    return [(book, card, rid, c.get_json(db, rid)) for book, card, rid in db.execute(query, parameters)]


def _expect(rows, expected):
    actual = {book + '/' + card: rid for book, card, rid, _ in rows}
    if not rows:
        raise ValueError('reviewed shared source is absent')
    if not isinstance(expected, dict) or actual != expected:
        raise ValueError('stale or incomplete cross-book revision scope')


def _current_note(db, book, card):
    from .study_catalog_export import project_book, project_note
    notes = db.execute('select note_id from notes where book_id=%s and source_card_id=%s', (book, card)).fetchall()
    if len(notes) != 1:
        raise ValueError('active semantic record needs one exact source note')
    note = project_note(db, project_book(db, book), notes[0][0], apply_runtime=False)
    return notes[0][0], dict(zip(note['field_names'], note['fields']))


def _activate(db, changes, projections):
    """Apply precompiled changes; caller owns the enclosing shared write lock."""
    from .study_catalog_anki import bump_content_mods
    from .study_catalog_normalize import import_analysis
    mapped = []
    for bid, manifest in db.execute("select b.book_id,s.manifest_id from book_sources b join sources s on s.id=b.source_id where s.kind='book-map'"):
        mapped.append((bid, c.get_json(db, manifest).get('analysis_references', {})))
    result = []
    affected = []
    for before, after, fields, nid in changes:
        book, card = before['book_id'], before['card_id']
        current = db.execute('select record_id from analyses where book_id=%s and source_card_id=%s for update',
                             (book, card)).fetchone()
        before_id = _sha(c.canonical(before))
        if current is None or current[0] != before_id:
            raise ValueError('active analysis changed during amendment')
        for table in ('analysis_occurrences', 'analysis_senses', 'analyses'):
            db.execute('delete from ' + table + ' where book_id=%s and source_card_id=%s', (book, card))
        import_analysis(db, after)
        after_id = c.put_json(db, after)
        previous = projections.get(c.identity(book, card), {})
        projections[c.identity(book, card)] = {**previous,'record_id': after_id,
            'fields': {**previous.get('fields',{}), **{name: c.put_object(db, value.encode()) for name, value in fields.items()}}}
        affected.append((book, nid))
        for mapped_book, refs in mapped:
            for mapped_card, ref in refs.items():
                if (ref['book_id'], ref['source_card_id']) == (book, card):
                    affected.extend((mapped_book, n[0]) for n in db.execute(
                        'select note_id from notes where book_id=%s and source_card_id=%s', (mapped_book, mapped_card)))
        result.append({'book_id': book, 'source_card_id': card, 'before': before_id, 'after': after_id})
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (rev.KEY, c.canonical(projections)))
    rev.preflight_display_projections(db, affected)
    bump_content_mods(db, affected)
    return result


def _restore_sense_indexes(draft):
    indexes = {s['sense_id']: s['ordinal'] for s in draft['senses']}
    for row in draft['occurrences']:
        row['sense_index'] = indexes.get(row['sense_id'])


def _remap_senses(draft, old, new):
    """Reseal unchanged explicit choices, without choosing any new meaning."""
    mapping = {a['sense_id']: b['sense_id'] for a, b in zip(old, new)}
    for row in draft['occurrences']:
        for label in ('broad_match', 'common_sense_match', 'matching_proposal'):
            value = row.get(label)
            if value:
                value['candidate_sense_ids'] = [mapping[i] for i in value['candidate_sense_ids']]
        if row.get('matching_proposal'):
            # A definition correction invalidates machine lexical proposals.
            # Keep their complete old value in immutable record/audit, rather
            # than presenting an unreviewed proposal as a newly verified one.
            row.pop('matching_proposal')
    for certificate in draft.get('sense_group_equivalences', []):
        if 'member_sense_ids' in certificate:
            certificate['member_sense_ids'] = [mapping[i] for i in certificate['member_sense_ids']]
        for evidence in certificate.get('evidence', []):
            if evidence.get('sense_id') in mapping:
                evidence['sense_id'] = mapping[evidence['sense_id']]


def _prepare(draft):
    """Preserve a/an exclusion ledgers while issuing a new reviewed record."""
    scope = draft.pop('candidate_scope', None)
    original_candidate_source = draft.pop('candidate_source_record', None)
    draft.pop('snapshot_id', None)
    draft.pop('definition_snapshot_id', None)
    for row in draft['occurrences']:
        if row['status'] == 'reviewed':
            row.update(sf.seal_reviewed_assignment(draft, row))
    if scope is None:
        return sf.prepare_record(draft)
    # The old exclusion ledger is historical authority. No exclusion choice or
    # excluded source evidence may change through a dictionary/source edit.
    from .sense_candidate_scope import _record_context, _row_context, validate_stored_scope
    if not isinstance(original_candidate_source, dict):
        raise ValueError('candidate revision needs its complete original source record')
    validate_stored_scope(original_candidate_source, scope)
    ledger = deepcopy(scope)
    rows = draft['occurrences']
    if len(rows) != len(ledger['retained_map']):
        raise ValueError('source amendment cannot change candidate exclusion membership')
    # Normalized records are SHA-sorted, while retained_map is indexed in the
    # original source order. Match each former physical identity explicitly;
    # array position must never acquire authority to relabel an original index.
    # Source amendments keep row.occurrence_id as their exact old token ID until
    # this stage, even when an explicitly reviewed new target span changes it.
    current = {}
    for row in rows:
        old_identity = row.get('occurrence_id') or _sha(c.canonical(
            [row['paper_id'], row['physical_source'], row['target_range']]))
        if old_identity in current:
            raise ValueError('candidate revision repeats an old physical identity')
        current[old_identity] = row
    restored = [None] * ledger['raw_total']; ordered = []; consumed = set()
    for entry in ledger['retained_map']:
        former = original_candidate_source['occurrences'][entry['candidate_index']]
        old_identity = _sha(c.canonical([former['paper_id'], former['physical_source'], former['target_range']]))
        if old_identity not in current or old_identity in consumed:
            raise ValueError('candidate revision lacks an exact old-to-new physical binding')
        consumed.add(old_identity); row = current[old_identity]
        row['occurrence_id'] = _sha(c.canonical([row['paper_id'], row['physical_source'], row['target_range']]))
        ordered.append(row)
        entry['occurrence_sha256'] = _sha(c.canonical(row))
        entry['context_sha256'] = _sha(c.canonical(_row_context(row)))
        restored[entry['original_index']] = row
    if consumed != set(current):
        raise ValueError('candidate revision contains unrelated physical tokens')
    draft['occurrences'] = ordered
    for entry in ledger['excluded']:
        restored[entry['original_index']] = entry['occurrence']
    ledger['definition_provenance'] = deepcopy(draft['definition_provenance'])
    ledger['definition_context_sha256'] = _sha(c.canonical(_record_context(draft)))
    ledger['candidate_record_sha256'] = _sha(c.canonical(draft))
    raw = {**draft, 'occurrences': restored, 'expected_occurrences': ledger['raw_total']}
    ledger['raw_record_sha256'] = _sha(c.canonical(raw))
    ledger['raw_linguistic_sha256'] = _sha(c.canonical([_row_context(row) for row in restored]))
    ledger.pop('ledger_sha256', None)
    ledger['ledger_sha256'] = _sha(c.canonical(ledger))
    draft['candidate_scope'] = ledger
    return sf.prepare_record(draft)


def _dictionary_evidence(evidence, dictionary, word, new):
    if not isinstance(evidence, dict):
        raise ValueError('complete reviewed dictionary evidence is required')
    for key in ('dictionary', 'entry', 'entry_html', 'locator', 'quoted_definition'):
        _required(evidence.get(key), 'dictionary evidence ' + key)
    if evidence['dictionary'] != dictionary or evidence['entry'] != word:
        raise ValueError('dictionary correction cannot silently change source dictionary or headword')
    if evidence.get('reviewed_pos') != new['pos'] or evidence.get('reviewed_text') != new['text']:
        raise ValueError('dictionary evidence does not bind the exact reviewed new sense')
    plain = _text(evidence['entry_html'])
    if evidence['quoted_definition'] not in plain:
        raise ValueError('reviewed quotation is absent from exact dictionary entry')
    if new['text'] not in plain and evidence.get('translation_kind') != 'reviewed-translation':
        raise ValueError('new Chinese sense must be quoted or explicitly reviewed translation')


def amend_dictionary_sense(value, *, sense_id, expected_sense, new_sense, evidence,
                           expected, reason, backups):
    """Correct one shared dictionary meaning using a supplied exact entry.

    The source dictionary identity cannot be relabeled. Existing assignments
    retain their ordinal; if the meaning itself changes, the caller must provide
    an explicit review for all affected usages in ``usage_reviews`` in evidence.
    """
    _required(reason, 'review reason')
    if (not isinstance(new_sense, dict) or set(new_sense) != {'pos', 'text'} or
            not isinstance(new_sense['pos'], str)):
        raise ValueError('new sense must contain exact pos and text')
    _required(new_sense['text'], 'new sense text')
    saved = c.backup(value, backups)
    with c.connect(value) as db, c.transaction(db):
        from .study_catalog_export import require_ready
        from .study_catalog_import import _dictionary_binding
        c.write_lock(db); require_ready(db)
        rows = _record_rows(db, 'select distinct a.book_id,a.source_card_id,a.record_id from analyses a '
            'join analysis_senses s on s.book_id=a.book_id and s.source_card_id=a.source_card_id '
            'where s.sense_id=%s order by a.book_id,a.source_card_id', (sense_id,))
        _expect(rows, expected)
        changes = []
        all_reviews = evidence.get('usage_reviews') if isinstance(evidence, dict) else None
        review_scope = {}
        for book, card, _, before in rows:
            choices = db.execute('select ordinal from analysis_senses where book_id=%s and source_card_id=%s and sense_id=%s',
                                 (book, card, sense_id)).fetchall()
            if len(choices) != 1:
                raise ValueError('dictionary correction needs one exact source sense per book')
            index = choices[0][0]; old = before['senses'][index]
            if {'pos': old['pos'], 'text': old['text']} != expected_sense:
                raise ValueError('stale expected dictionary sense')
            proof = _dictionary_binding(before, old)
            _dictionary_evidence(evidence, proof['dictionary'], before['word'], new_sense)
            selected = [r for r in before['occurrences'] if r['sense_id'] == old['sense_id'] or any(
                old['sense_id'] in r.get(label, {}).get('candidate_sense_ids', [])
                for label in ('broad_match', 'common_sense_match', 'matching_proposal'))]
            selected_ids = {r['occurrence_id'] for r in selected}
            review_scope[book + '/' + card] = {r['occurrence_id'] for r in selected}
            if not isinstance(all_reviews, dict) or set(all_reviews.get(book + '/' + card, {})) != review_scope[book + '/' + card]:
                raise ValueError('definition correction needs explicit review of every assigned usage')
            draft = deepcopy(before); _restore_sense_indexes(draft)
            draft['senses'][index].update(new_sense)
            payload = {k: v for k, v in evidence.items() if k != 'usage_reviews'}
            correction = {'schema': 'study-catalog-dictionary-correction.v1', 'dictionary': proof['dictionary'],
                'entry_html_sha256': c.put_object(db, evidence['entry_html'].encode()),
                'evidence_sha256': c.put_json(db, payload), 'original_binding': proof, 'reason': reason}
            draft['definition_provenance'].setdefault('catalog_sense_revisions', {})[str(index)] = correction
            new = sf._definition(draft)['senses']
            _remap_senses(draft, before['senses'], new)
            # A formerly equivalent sense may no longer be equivalent after
            # correction. The caller must review that grouping explicitly; no
            # certificate is silently dropped or reasserted as fresh evidence.
            group_reviews = evidence.get('group_reviews', {})
            affected_group = any(old['sense_id'] in cert.get('member_sense_ids', []) or
                index in cert.get('member_ordinals', []) for cert in before.get('sense_group_equivalences', []))
            if affected_group and book + '/' + card not in group_reviews:
                raise ValueError('corrected common sense needs explicit reviewed equivalence certificates')
            if book + '/' + card in group_reviews:
                if not isinstance(group_reviews[book + '/' + card], list):
                    raise ValueError('reviewed equivalence certificates must be an array')
                draft['sense_group_equivalences'] = deepcopy(group_reviews[book + '/' + card])
                for certificate in draft['sense_group_equivalences']:
                    if 'member_ordinals' in certificate:
                        ordinals = certificate['member_ordinals']
                        if (not isinstance(ordinals, list) or any(type(ordinal) is not int or
                                not 0 <= ordinal < len(new) for ordinal in ordinals)):
                            raise ValueError('reviewed equivalence ordinals are invalid')
                        certificate['member_sense_ids'] = [new[ordinal]['sense_id'] for ordinal in ordinals]
            for row in draft['occurrences']:
                if row['occurrence_id'] in selected_ids:
                    row['reason'] = _required(all_reviews[book + '/' + card][row['occurrence_id']], 'usage review reason')
                    row['method'] = 'shared-catalog-dictionary-review.v1'
                    # Old source-specific dictionary explanation remains in the
                    # original article, within its explicitly historical audit.
                    if row.get('semantic_review'):
                        row['semantic_review'].pop('dictionary_explanation', None)
            after = _prepare(draft)
            nid, fields = _current_note(db, book, card)
            originals = source_articles(fields['Definition'], before)
            articles = {}
            old_rows = {r['occurrence_id']: r for r in before['occurrences']}
            for row in after['occurrences']:
                original = originals[row['occurrence_id']]
                article = original
                if row['occurrence_id'] not in selected_ids:
                    # Definition fingerprints also change unrelated sense IDs;
                    # exact authored articles for those usages stay intact.
                    articles[row['occurrence_id']] = article
                    continue
                article = _replace_reason(article, old_rows[row['occurrence_id']]['reason'], row['reason'])
                article = _remove_current_dictionary_explanation(article)
                explanation = ('<details class="sf-dictionary-explanation" open><summary>词典依据 · '
                    + html.escape(evidence['dictionary']) + ' · 本次核订</summary><p>'
                    + html.escape(new_sense['pos'] + ' ' + new_sense['text']) + '</p><blockquote>'
                    + html.escape(evidence['quoted_definition']) + '</blockquote><p>'
                    + html.escape(evidence['locator']) + '</p></details>')
                end = article.rfind('</article>')
                article = article[:end] + explanation + _audit(old_rows[row['occurrence_id']], row, reason,
                    original_html=original) + article[end:]
                articles[row['occurrence_id']] = article
            annotation = ('<details class="sf-catalog-revision"><summary>词典释义完整核订依据</summary>'
                '<pre style="white-space:pre-wrap">' + html.escape(c.canonical({'before_record': before,
                'correction': correction, 'evidence': payload})) + '</pre></details>')
            definition = repartition_definition(fields['Definition'], before, after, articles,
                                                 changed_senses={0: [annotation]})
            changes.append((before, after, {'Definition': definition}, nid))
        if set(all_reviews) != set(review_scope):
            raise ValueError('definition correction usage review scope contains unrelated records')
        result = _activate(db, changes, rev.registry(db))
        c.event(db, 'amend-shared-dictionary-sense', {'sense_id': sense_id, 'expected_sense': expected_sense,
            'new_sense': new_sense, 'evidence_id': c.put_json(db, evidence), 'reason': reason, 'changes': result})
    return {'changes': result, 'backup': str(saved), 'physical_frequency_changed': False}


def _replace_reason(article, old, new):
    nodes = [n for n in rev._nodes(article, 'sf-reason')
             if _text(article[n.opened:n.closed]) == '义项依据：' + old]
    if len(nodes) != 1:
        raise ValueError('source article lacks exact current reviewed reason')
    node = nodes[0]
    return rev._edits(article, [(node.opened, node.closed, '义项依据：' + html.escape(new))])


def _remove_current_dictionary_explanation(article):
    return rev._edits(article, [(n.start, n.end, '') for n in rev._nodes(article, 'sf-dictionary-explanation')])


def _source(row):
    return {key: deepcopy(row.get(key)) for key in SOURCE_KEYS}


def _row_review(row):
    return {key: deepcopy(row.get(key)) for key in ROW_KEYS}


def _append_source_chain(before, original, new_source, review, reason):
    chain = deepcopy((original.get('semantic_review') or {}).get('catalog_source_revision_chain'))
    owner = {key: before[key] for key in ('book_id', 'card_id', 'word')}
    if not chain or any(chain.get(key) != value for key, value in owner.items()):
        chain = {'schema': 'study-catalog-reviewed-source-chain.v2', **owner,
                 'base_record': deepcopy(before), 'base_occurrence_id': original['occurrence_id'], 'steps': []}
    else:
        seal = chain.pop('chain_sha256', None)
        if seal != _sha(c.canonical(chain)):
            raise ValueError('source revision chain seal is stale')
    previous = chain['steps'][-1]['step_sha256'] if chain['steps'] else chain['base_record']['snapshot_id']
    step = {'expected_source': _source(original), 'new_source': deepcopy(new_source),
            'token_review': deepcopy(review), 'reason': reason, 'previous_sha256': previous}
    step['step_sha256'] = _sha(c.canonical(step))
    chain['steps'].append(step)
    chain['chain_sha256'] = _sha(c.canonical(chain))
    return chain


def _source_chain_panel(row):
    chain = (row.get('semantic_review') or {}).get('catalog_source_revision_chain')
    if not chain:
        return ''
    return ('<details class="sf-catalog-revision sf-catalog-source-chain" '
            'data-reviewed-source-comparison="catalog-source-chain"><summary>本句完整来源修订链</summary>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + html.escape(c.canonical(chain)) + '</pre></details>')


def _replace_pair(article, before, after, reason):
    full_original = article
    # Replace the single current chain panel; previous per-step audits remain.
    panels = [node for node in _Offsets(article, {}).root.walk() if 'sf-catalog-source-chain' in node.classes]
    article = rev._edits(article, [(node.start, node.end, '') for node in panels])
    pairs = rev._nodes(article, 'sf-sentence-pair')
    if len(pairs) != 1:
        raise ValueError('source article lacks one exact bilingual pair')
    node = pairs[0]
    current = render_sentence_pair(before)
    if article[node.start:node.end] != current:
        raise ValueError('source article chunks differ from sealed current source')
    result = rev._edits(article, [(node.start, node.end, render_sentence_pair(after))])
    result = _replace_reason(result, before['reason'], after['reason'])
    result = result.replace('data-sf-occurrence-id="' + before['occurrence_id'] + '"',
                            'data-sf-occurrence-id="' + after['occurrence_id'] + '"', 1)
    end = result.rfind('</article>')
    return result[:end] + _audit(before, after, reason, original_html=full_original) + _source_chain_panel(after) + result[end:]


def _native_text(raw, node, *, translation=False, aliases=None):
    # Native examples represent real line breaks with <br>; the dictionary
    # plain-text extractor deliberately omits them and is not suitable here.
    from .local_dictionary import _Tree
    from .sense_display import _text_and_ranges
    root = _Tree(raw[node.opened:node.closed]).root
    for child in root.walk():
        if 'class' in child.attrs:
            child.attrs['class'] = ' '.join((aliases or {}).get(name, name) for name in child.attrs['class'].split())
    text = _text_and_ranges(root, 'translate-tag' if translation else None)[0]
    return text[1:] if translation and text.startswith(' ') else text


def _jump_source_matches(row, jump):
    declared = (row.get('display') or {}).get('provenance', {}).get('native_jump')
    return jump is not None and jump['sentence_id'] == (declared or {}).get('sentence_id', row.get('sentence_id'))


def _jump_matches(row, jump):
    if jump is None:
        return False
    declared = (row.get('display') or {}).get('provenance', {}).get('native_jump')
    if declared:
        return all(jump.get(key) == declared.get(key) for key in
                   ('sentence_id', 'english_hash', 'reviewed_content_hash', 'target_ranges'))
    return (jump['sentence_id'] == row.get('sentence_id') and
            jump['english_hash'] == row.get('english_hash') and
            jump['reviewed_content_hash'] == row.get('source_provenance', {}).get('reviewedContentHash') and
            row.get('target_range') in jump['target_ranges'])


def _physical_source_key(row):
    return c.canonical([row.get('paper_id'), row.get('physical_source')])


def _examples(raw, pairs, reason, *, known_occurrences=None, aliases=None):
    """Update source-bound native Examples without reconstructing their shell."""
    from .packaging import (_example_chunk_ranges, _highlight_example,
                            _chunk_translation, _annotate_sentence_chunks)
    from .native_example_usage import _source_classes
    aliases = {} if aliases is None else aliases
    if not isinstance(aliases, dict) or any(not isinstance(key, str) or not isinstance(name, str) for key, name in aliases.items()):
        raise ValueError('native source class aliases must be a string mapping')
    root = _Offsets(raw, aliases).root
    nodes = [node for node in root.walk() if not rev._historical(node)]
    cards = [node for node in nodes if 'example-card' in node.classes]
    # Unknown compact shells cannot be silently skipped: normalized facts and
    # Definition would otherwise advance while the native Examples stay old.
    # The caller supplies exact aliases; this operation never guesses a class.
    if raw.strip() and not cards:
        raise ValueError('native source class aliases are missing or incomplete')
    from .sense_display import _decode_jump
    for node in nodes:
        ancestor = node.parent
        while ancestor is not None and 'example-card' not in ancestor.classes:
            ancestor = ancestor.parent
        if node.tag == 'li' and node.classes and 'example-card' not in node.classes and ancestor is None:
            raise ValueError('native source class aliases are missing or incomplete')
        if ('data-rb-j' not in node.attrs and not any('anki-codex-sentence=' in node.attrs.get(name, '')
                for name in ('href', 'data-latex-url'))):
            continue
        jump = _decode_jump(node)
        if jump is not None and any(_jump_source_matches(before, jump) for before, _ in pairs):
            if 'sentence-jump' not in node.classes or ancestor is None:
                raise ValueError('native source class aliases are missing or incomplete')
    changes = []
    for node in cards:
        if 'example-card' not in node.classes or rev._historical(node):
            continue
        if 'sf-sentence-pair' in node.classes:
            continue
        en = next((n for n in node.walk() if 'example-text' in n.classes and not rev._historical(n)), None)
        zh = next((n for n in node.walk() if 'example-translation' in n.classes and not rev._historical(n)), None)
        if en is None:
            raise ValueError('native source class aliases are missing or incomplete')
        key = (_native_text(raw, en, aliases=aliases), '' if zh is None else _native_text(raw, zh, translation=True, aliases=aliases))
        from .sense_display import _decode_jump
        jumps = [_decode_jump(anchor) for anchor in node.walk()
                 if 'sentence-jump' in anchor.classes and not rev._historical(anchor)]
        jumps = [jump for jump in jumps if jump is not None]
        if jumps:
            for jump in jumps:
                declared = [before for before, _ in pairs if _jump_source_matches(before, jump)]
                if declared and not any(_jump_matches(before, jump) for before in declared):
                    raise ValueError('native source jump has stale hash, review or target binding')
            scoped_pairs = [(before, after) for before, after in pairs
                            if any(_jump_matches(before, jump) for jump in jumps)]
            # Equal text is not a source identity. An example bound to another
            # exam/year stays exactly intact, including its own translation.
            if not scoped_pairs:
                if any(_jump_source_matches(before, jump) for before, _ in pairs for jump in jumps):
                    raise ValueError('native source jump has stale hash, review or target binding')
                continue
        else:
            scoped_pairs = pairs
        candidates = [(before, after) for before, after in scoped_pairs
            if key == (before.get('display', before)['english'], before.get('display', before)['translation'])]
        known = [row for row in (known_occurrences or []) if key ==
                 (row.get('display', row)['english'], row.get('display', row)['translation'])]
        if not candidates:
            if jumps:
                raise ValueError('native source example text differs from its sealed current source')
            # Another exact source can have the same English and a distinct
            # translation. It is unrelated when its full bilingual pair is
            # uniquely retained elsewhere in this note's reviewed records.
            if known:
                continue
            if any(key[0] == before.get('display', before)['english'] for before, _ in scoped_pairs):
                raise ValueError('native source example translation differs from its sealed current source')
            continue
        if not jumps and len({_physical_source_key(row) for row in known}) > 1:
            raise ValueError('unbound identical native examples have ambiguous physical sources')
        # Rebuilding an inner sentence must retain the class contract used by
        # compressed CSS and chunk interaction. Structural attributes identify
        # authored semantic nodes without guessing the missing compact alias.
        for field in (en, zh):
            if field is None:
                continue
            for part in field.walk():
                if rev._historical(part):
                    continue
                is_chunk = 'data-chunk-side' in part.attrs or 'data-chunk-ids' in part.attrs
                is_cloze = part.tag == 'u' and 'data-blank-number' in part.attrs
                semantic_node = part.tag == 'mark' or is_chunk or is_cloze
                if ((part.tag == 'mark' and 'target-word' not in part.classes) or
                        (is_chunk and 'card-chunk' not in part.classes) or
                        (is_cloze and 'cloze-answer' not in part.classes) or
                        (semantic_node and part.classes - {'target-word', 'card-chunk', 'cloze-answer', 'sf-target-chunk'})):
                    raise ValueError('native source class aliases are missing or incomplete')
        views = {c.canonical({k: after.get('display', after).get(k) for k in
                 ('english', 'translation', 'alignment', 'cloze_answers')}) for _, after in candidates}
        if len(views) != 1:
            raise ValueError('native example maps to conflicting replacement views')
        view = candidates[0][1].get('display', candidates[0][1])
        example = {'text': view['english'], 'translation': view['translation']}
        if view.get('alignment') is not None:
            example.update(translation_source='codex', translation_alignment=view['alignment'])
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        targets = sorted({tuple(after.get('display', after)['target_range']) for _, after in candidates})
        en_html = _highlight_example(view['english'], '', '', view.get('cloze_answers', []),
            target_ranges=targets, chunk_ranges=en_chunks, preserve_source=True)
        zh_html = _chunk_translation(view['translation'], zh_chunks)
        en_html = _source_classes(_annotate_sentence_chunks(en_html, view.get('alignment')), aliases)
        zh_html = _source_classes(_annotate_sentence_chunks(zh_html, view.get('alignment')), aliases)
        fragment = raw[node.start:node.end]
        local = [(en.opened-node.start, en.closed-node.start, en_html)]
        prefix = ''
        if zh is not None:
            if zh.children and 'translate-tag' in zh.children[0].classes:
                prefix = raw[zh.children[0].start:zh.children[0].end] + ' '
            local.append((zh.opened-node.start, zh.closed-node.start, prefix + zh_html))
        elif view['translation']:
            closing = raw.rfind('</' + node.tag + '>', node.start, node.end)
            if closing < node.opened:
                raise ValueError('native example lacks its exact closing shell')
            local.append((closing-node.start, closing-node.start,
                _source_classes('<span class="example-translation"><span class="translate-tag">翻译</span> ' + zh_html + '</span>', aliases)))
        jump_views = {c.canonical((after.get('display') or {}).get('provenance', {}).get('native_jump'))
                      for _, after in candidates}
        if len(jump_views) != 1:
            raise ValueError('native source example has conflicting explicitly reviewed jumps')
        reviewed_jump = json.loads(next(iter(jump_views)))
        if reviewed_jump:
            from types import SimpleNamespace
            from .sense_display import _decode_jump
            native = reviewed_jump.get('native_jump')
            if not isinstance(native, str) or not native:
                raise ValueError('reviewed native jump representation is required')
            attrs = {'href': native} if '://' in native else {'data-rb-j': native}
            if _decode_jump(SimpleNamespace(attrs=attrs)) != reviewed_jump:
                raise ValueError('reviewed native jump representation differs from its source metadata')
        for anchor in node.walk():
            if 'sentence-jump' not in anchor.classes or rev._historical(anchor):
                continue
            if not any(_jump_matches(before, _decode_jump(anchor)) for before, _ in candidates):
                continue
            opening = raw[anchor.start:anchor.opened]
            # A supplied derived display carries the exact reviewed jump. For
            # ordinary physical source examples the caller's explicit new
            # source review hash, token positions and immutable sentence ID
            # provide the equivalent source-pinned URL fields.
            for attribute in ('href', 'data-latex-url'):
                old_url = anchor.attrs.get(attribute)
                if old_url is None:
                    continue
                if reviewed_jump:
                    new_url = reviewed_jump['native_jump']
                    if '://' not in new_url:
                        raise ValueError('native URL example requires an explicitly reviewed URL jump')
                else:
                    current_row = candidates[0][1]
                    review_hash = current_row['source_provenance'].get('reviewedContentHash')
                    if not isinstance(review_hash, str) or not re.fullmatch('[0-9a-f]{64}', review_hash):
                        raise ValueError('native jump amendment needs its exact reviewed content SHA256')
                    parsed = urlsplit(old_url)
                    replacements = {'anki-codex-sentence': current_row['sentence_id'],
                        'anki-codex-hash': current_row['english_hash'], 'anki-codex-review': review_hash,
                        'anki-codex-en': json.dumps([list(span) for span in targets])}
                    query = [(key, replacements.pop(key, value)) for key, value in parse_qsl(parsed.query, keep_blank_values=True)]
                    query.extend(replacements.items())
                    new_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
                pattern = r'(' + re.escape(attribute) + r'\s*=\s*)([\"\'])(.*?)\2'
                opening, count = re.subn(pattern, lambda m: m[1] + m[2] + html.escape(new_url, quote=True) + m[2], opening, count=1)
                if count != 1:
                    raise ValueError('native source jump attribute is malformed')
            packed = anchor.attrs.get('data-rb-j')
            if packed is not None:
                if not reviewed_jump or '://' in reviewed_jump['native_jump']:
                    raise ValueError('packed native jump needs its explicit reviewed packed replacement')
                revised_packed = html.escape(reviewed_jump['native_jump'], quote=True)
                opening, count = re.subn(r'(data-rb-j\s*=\s*)([\"\'])(.*?)\2',
                    lambda m: m[1] + m[2] + revised_packed + m[2], opening, count=1)
                if count != 1:
                    raise ValueError('packed native source jump is malformed')
            local.append((anchor.start-node.start, anchor.opened-node.start, opening))
        fragment = rev._edits(fragment, local)
        # Keep all original source links and markup available in the sentence's
        # revision disclosure rather than dropping them during source updates.
        end = fragment.rfind('</' + node.tag + '>')
        fragment = fragment[:end] + _audit({'source_pairs': [b for b, _ in candidates]},
            {'source_pairs': [a for _, a in candidates]}, reason, original_html='<ol class="examples">' + raw[node.start:node.end] + '</ol>', aliases=aliases) + fragment[end:]
        changes.append((node.start, node.end, fragment))
    return rev._edits(raw, changes)


def _source_variants(expected, replacement):
    """Accept one exact source or an explicit complete set of source variants."""
    if isinstance(expected, dict) and set(expected) == {'variants'}:
        if not isinstance(replacement, dict) or set(replacement) != {'variants'}:
            raise ValueError('source variant replacements need matching expected/new maps')
        originals, revised = expected['variants'], replacement['variants']
        if (not isinstance(originals, dict) or not originals or
                not isinstance(revised, dict) or set(originals) != set(revised)):
            raise ValueError('source variant replacements need matching expected/new maps')
    else:
        originals = {_sha(c.canonical(expected)): expected}
        revised = {next(iter(originals)): replacement}
    result = {}
    for identity, old in originals.items():
        new = revised[identity]
        if (not isinstance(old, dict) or set(old) != set(SOURCE_KEYS) or
                not isinstance(new, dict) or set(new) != set(SOURCE_KEYS) or
                identity != _sha(c.canonical(old))):
            raise ValueError('sentence revision needs exact full expected/new source payloads')
        _required(new['english'], 'new English source')
        if not isinstance(new['translation'], str):
            raise ValueError('new translation must be text')
        if not isinstance(new['source_provenance'], dict) or not new['source_provenance']:
            raise ValueError('new source provenance is required')
        result[identity] = (old, new)
    return result


def amend_sentence(value, *, paper_id, physical_source, expected_source, new_source,
                   occurrence_reviews, expected, reason, backups, aliases_by_book=None):
    """Replace a whole shared bilingual source and its explicit token reviews.

    Every word using the physical source participates, including other books and
    mapped future books. ``occurrence_reviews[book/card][old_occurrence_id]``
    contains exactly ``expected`` and ``new`` ROW_KEYS. New token spellings must
    remain the same; changing lexical ownership is a different reviewed action.
    Chunk-only amendments use the same interface with unchanged EN/CN strings.
    Completed option/cloze displays require an explicitly revalidated replacement
    ``display``; no generated whole-sentence fallback may replace authored chunks.
    ``aliases_by_book`` maps source book IDs to exact compact-to-standard native
    class maps. The first amendment persists the supplied map for both hosts and
    future mapped books; later amendments reuse it and reject conflicting maps.
    """
    _required(reason, 'review reason')
    if not isinstance(physical_source, list) or not physical_source:
        raise ValueError('sentence revision needs its exact physical source identity')
    variants = _source_variants(expected_source, new_source)
    if not isinstance(occurrence_reviews, dict):
        raise ValueError('explicit per-token review scope is required')
    if aliases_by_book is not None and (not isinstance(aliases_by_book, dict) or any(
            not isinstance(book, str) or not isinstance(aliases, dict) or any(
                not isinstance(key, str) or not isinstance(name, str) for key, name in aliases.items())
            for book, aliases in aliases_by_book.items())):
        raise ValueError('native class aliases must map each book to exact string aliases')
    saved = c.backup(value, backups)
    with c.connect(value) as db, c.transaction(db):
        from .study_catalog_export import require_ready
        c.write_lock(db); require_ready(db)
        source_id = _sha(c.canonical(physical_source))
        sentence_ids = [r[0] for r in db.execute('select distinct s.source_sentence_id '
            'from analysis_occurrences x join tokens t on t.id=x.token_id join sentences s on s.id=t.sentence_id '
            'where s.paper_id=%s and t.physical_source_id=%s', (paper_id, source_id))]
        rows = _record_rows(db, 'select distinct a.book_id,a.source_card_id,a.record_id from analyses a '
            'join analysis_occurrences x on x.book_id=a.book_id and x.source_card_id=a.source_card_id '
            'join tokens t on t.id=x.token_id join sentences s on s.id=t.sentence_id '
            'where s.paper_id=%s and (t.physical_source_id=%s or s.source_sentence_id=any(%s)) '
            'order by a.book_id,a.source_card_id', (paper_id, source_id, sentence_ids))
        _expect(rows, expected)
        if set(aliases_by_book or {}) - {book for book, _, _, _ in rows}:
            raise ValueError('native class alias scope contains an unrelated source book')
        if set(occurrence_reviews) != set(expected):
            raise ValueError('stale or incomplete per-token cross-book revision scope')
        projections = rev.registry(db)
        changes = []; used_variants = set()
        for book, card, _, before in rows:
            prior = projections.get(c.identity(book, card), {})
            supplied_aliases = (aliases_by_book or {}).get(book)
            if (supplied_aliases is not None and 'native_aliases' in prior and
                    supplied_aliases != prior['native_aliases']):
                raise ValueError('native class aliases conflict with the current shared projection')
            aliases = supplied_aliases if supplied_aliases is not None else prior.get('native_aliases', {})
            scope = {r['occurrence_id']: r for r in before['occurrences']
                     if r['paper_id'] == paper_id and (r['physical_source'] == physical_source or r['sentence_id'] in sentence_ids)}
            reviews = occurrence_reviews[book + '/' + card]
            if not isinstance(reviews, dict) or set(reviews) != set(scope):
                raise ValueError('sentence revision does not cover every physical token')
            draft = deepcopy(before); _restore_sense_indexes(draft)
            changed = []
            for row in draft['occurrences']:
                original = scope.get(row['occurrence_id'])
                if original is None:
                    continue
                variant_id = _sha(c.canonical(_source(original)))
                if variant_id not in variants or variants[variant_id][0] != _source(original):
                    raise ValueError('shared source differs from exact expected source')
                used_variants.add(variant_id)
                replacement_source = variants[variant_id][1]
                review = reviews[row['occurrence_id']]
                if (not isinstance(review, dict) or set(review) != {'expected', 'new'} or
                        review['expected'] != _row_review(original) or not isinstance(review['new'], dict) or
                        set(review['new']) != set(ROW_KEYS)):
                    raise ValueError('token revision needs exact full expected/new reviewed payloads')
                _required(review['new']['reason'], 'new token review reason')
                row.update(deepcopy(replacement_source)); row.update(deepcopy(review['new']))
                if row['display'] is None:
                    if original.get('display') is not None:
                        raise ValueError('derived display must be explicitly preserved and revalidated')
                    row.pop('display')
                if row.get('alignment') is None:
                    raise ValueError('reviewed source amendment must supply its complete authored chunk alignment')
                row['english_hash'] = _sha(row['english']); row['translation_hash'] = _sha(row['translation'])
                old_token = original['english'][slice(*original['target_range'])]
                if row['english'][slice(*row['target_range'])] != old_token:
                    raise ValueError('sentence revision cannot change lexical token ownership or spelling')
                row['method'] = 'shared-catalog-source-review.v1'
                row.pop('matching_proposal', None)
                identity = _sha(c.canonical([row['paper_id'], row['physical_source'], row['target_range']]))
                semantic = row.setdefault('semantic_review', {})
                semantic['occurrence_id'] = identity
                display = row.get('display')
                if display and display['provenance']['source_card_sha256'] != draft['definition_provenance'].get('page_sha256'):
                    # Only transferred displays need an offline ownership bridge.
                    # Ordinary revisions retain old snapshots once in immutable
                    # storage and their sentence audit; duplicating a whole
                    # previous record inside every ordinary token would grow
                    # history geometrically after repeated source corrections.
                    chain = _append_source_chain(before, original, replacement_source, review, reason)
                    semantic['catalog_source_revision_chain'] = chain
                    # Complete legacy bridges are retained once in base_record.
                    semantic.pop('catalog_source_revisions', None)
                    semantic.pop('catalog_ownership_transfers', None)
                if row.get('ownership_history') and identity != original['occurrence_id']:
                    # Old immutable transfers are retained in the complete audit;
                    # they cannot be reasserted with a fabricated new identity.
                    row.pop('ownership_history')
                changed.append((original, row))
            after = _prepare(draft)
            if after['expected_occurrences'] != before['expected_occurrences']:
                raise ValueError('sentence amendment changed physical frequency')
            pairs = []
            for original, draft_row in changed:
                identity = _sha(c.canonical([draft_row['paper_id'], draft_row['physical_source'], draft_row['target_range']]))
                final = next(r for r in after['occurrences'] if r['occurrence_id'] == identity)
                pairs.append((original, final))
            nid, fields = _current_note(db, book, card)
            originals = source_articles(fields['Definition'], before)
            replacement = {b['occurrence_id']: a for b, a in pairs}
            articles = {}
            for original in before['occurrences']:
                oid = original['occurrence_id']; new = replacement.get(oid)
                if new is None:
                    articles[oid] = originals[oid]
                else:
                    articles[new['occurrence_id']] = _replace_pair(originals[oid], original, new, reason)
            projected = {'Definition': repartition_definition(fields['Definition'], before, after, articles)}
            if 'Examples' in fields:
                projected['Examples'] = _examples(fields['Examples'], pairs, reason, known_occurrences=before['occurrences'],
                                                  aliases=aliases)
            if supplied_aliases is not None or 'native_aliases' in prior:
                projections[c.identity(book, card)] = {**prior, 'native_aliases': deepcopy(aliases)}
            changes.append((before, after, projected, nid))
        if used_variants != set(variants):
            raise ValueError('source revision includes unrelated or stale variants')
        result = _activate(db, changes, projections)
        c.event(db, 'amend-shared-bilingual-source', {'paper_id': paper_id, 'physical_source': physical_source,
            'expected_source_id': c.put_json(db, expected_source), 'new_source_id': c.put_json(db, new_source),
            'occurrence_reviews_id': c.put_json(db, occurrence_reviews),
            'native_aliases_by_book_id': c.put_json(db, aliases_by_book or {}),
            'reason': reason, 'changes': result})
    return {'changes': result, 'backup': str(saved), 'physical_frequency_changed': False}
