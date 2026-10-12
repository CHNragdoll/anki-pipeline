"""Lossless wrong-card histories attached only to existing reviewed destinations.

This is a presentation overlay: no occurrence, source, assignment, count or
snapshot identity is changed. The caller must prepare/seal the resulting record
before persistence. Unbound transfers remain complete in the explicit audit list.
"""
from __future__ import annotations

from copy import deepcopy
import html
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from . import sense_frequency as sf

SCHEMA = 'exam-usage-ownership-history.v1'
_SOURCE_FIELDS = ('occurrence_id', 'paper_id', 'sentence_id', 'physical_source',
    'english', 'english_hash', 'translation', 'translation_hash', 'target_range',
    'translation_ranges', 'source', 'source_provenance', 'status', 'sense_id',
    'reason', 'method', 'review_version', 'reviewed_sense_id',
    'assignment_context_hash', 'alignment', 'alignment_evidence', 'year')
_IDENTITY_FIELDS = ('paper_id', 'physical_source', 'sentence_id', 'english_hash', 'target_range')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _content_sha256(history):
    return sf._sha(sf._json({key: value for key, value in history.items() if key != 'content_sha256'}))


def validate_history_content(history):
    """Validate the complete immutable history seal without rebinding snapshots.

    This checks historical content only. Its dictionary/parent snapshot pins
    continue to describe the verified binding event after a current card is
    prepared again. Rebinding against a destination is exclusively ``_bind``'s
    responsibility; this function never silently reseals changed explanations.
    """
    _require(isinstance(history, dict) and history.get('schema') == SCHEMA, 'unknown ownership history schema')
    checksum = history.get('content_sha256')
    _require(isinstance(checksum, str) and re.fullmatch(r'[0-9a-f]{64}', checksum), 'ownership history content SHA is required')
    _require(checksum == _content_sha256(history), 'ownership history content SHA differs')
    for key in ('history_id', 'book_id', 'source_card_id', 'source_word', 'source_parent_snapshot_id',
                'target_card_id', 'target_occurrence_id', 'target_word', 'target_reason'):
        _require(isinstance(history.get(key), str) and history[key].strip(), 'ownership history missing ' + key)
    _require(re.fullmatch(r'[0-9a-f]{64}', history['history_id']), 'invalid ownership history ID')
    _require(history.get('verified_physical_match') is True, 'ownership history lacks physical proof')
    _require(all(isinstance(history.get(key), dict) and history[key] for key in
                 ('source_parent_row', 'source_identity', 'exclusion_authority', 'matched_sense')), 'incomplete ownership history proof')
    sense = history['matched_sense']
    _require(all(isinstance(sense.get(key), str) and sense[key].strip() for key in
                 ('sense_id', 'pos', 'text', 'dictionary_source')) and
             isinstance(sense.get('ordinal'), int) and not isinstance(sense['ordinal'], bool) and sense['ordinal'] >= 0 and
             isinstance(sense.get('source_provenance'), dict) and sense['source_provenance'], 'incomplete historical actual sense')


def _validate_row(row):
    _require(isinstance(row, dict) and all(k in row for k in _SOURCE_FIELDS),
             'complete original prepared occurrence is required')
    _require(isinstance(row['english'], str) and isinstance(row['translation'], str), 'invalid bilingual source')
    _require(sf._sha(row['english']) == row['english_hash'], 'stale source English hash')
    _require(sf._sha(row['translation']) == row['translation_hash'], 'stale source translation hash')
    sf._span(row['target_range'], row['english'])
    _require(isinstance(row['physical_source'], list) and row['physical_source'], 'missing physical source')
    _require(isinstance(row['source_provenance'], dict) and row['source_provenance'], 'missing source provenance')
    _require(row['occurrence_id'] == sf._sha(sf._json([
        row['paper_id'], row['physical_source'], row['target_range']])), 'stale physical occurrence ID')
    _require(isinstance(row['reason'], str) and row['reason'].strip(), 'complete old review reason is required')
    if row.get('alignment') is not None:
        from .translation_alignment import validate_translation_alignment
        validate_translation_alignment(row['english'], row['translation'], row['alignment'])
    if 'display' in row:
        from .sense_display import validate_display
        validate_display(row['display'], row)


def _validate_authority(transfer, source):
    authority = transfer.get('exclusion_authority')
    _require(isinstance(authority, dict) and authority, 'complete old exclusion authority is required')
    # A complete scope-ledger item can wrap the unchanged authority object.
    outer = authority
    if 'authority' in authority:
        _require(authority.get('occurrence') == source, 'exclusion ledger original row changed')
        _require(authority.get('occurrence_id') == source['occurrence_id'], 'exclusion ledger occurrence differs')
        _require(authority.get('exclusion_kind') in {'wrong_lemma', 'reviewed_rehome'}, 'exclusion is not a lexical ownership decision')
        authority = authority['authority']
        _require(isinstance(authority, dict) and authority, 'exclusion ledger lacks complete authority')
    proof = authority.get('legacy_projection_proof')
    snapshot = transfer['source_parent_snapshot_id']
    if isinstance(proof, dict):
        decision = proof.get('decision')
        _require(isinstance(decision, dict) and proof.get('occurrence') == source, 'old X proof lacks the exact complete source row')
        _require(authority.get('parent_snapshot_id') == snapshot, 'old X parent snapshot differs')
        for key, expected in [('book_id', transfer['book_id']), ('card_id', transfer['source_card_id']),
                              ('after_snapshot_id', snapshot), ('occurrence_id', source['occurrence_id'])]:
            _require(decision.get(key) == expected, 'old X decision binding differs: ' + key)
        _require(authority.get('decision_sha256') == sf._sha(sf._json(decision)), 'old X decision SHA differs')
        after = decision.get('decision_after') or {}
        _require(after.get('status') in {'unmatched', 'ambiguous'} and after.get('status') == source['status'] and
                 after.get('reason') == source['reason'], 'old X status or complete reason differs')
    else:
        # A newly confirmed reviewed rehome has a separately pinned complete
        # parent row and the exact frozen ownership audit; no anonymous flag.
        _require(authority.get('source_parent_snapshot_id') == snapshot, 'reviewed rehome parent snapshot differs')
        _require(authority.get('source_parent_row_sha256') == sf._sha(sf._json(source)), 'reviewed rehome original row SHA differs')
        audit = authority.get('audit', outer.get('ownership'))
        _require(isinstance(audit, dict) and audit.get('exclusion_verified') is True and
                 audit.get('decision_status') == 'keep_exclusion', 'reviewed rehome lacks confirmed audit authority')
        _require(audit.get('book_id') == transfer['book_id'] and
                 audit.get('card_id') == transfer['source_card_id'] and
                 audit.get('occurrence_id') == source['occurrence_id'], 'reviewed rehome audit source differs')
        _require(audit.get('source_identity') == transfer['source_identity'] and
                 isinstance(audit.get('reason'), str) and audit['reason'].strip(), 'reviewed rehome audit identity or reason differs')
        _require(any(isinstance(t, dict) and t.get('card_id') == transfer['target_card_id'] and
                     t.get('occurrence_id') == transfer['target_occurrence_id'] and
                     t.get('verified_physical_match') is True for t in audit.get('targets', [])), 'reviewed rehome audit has no exact destination proof')


def _physical_equal(left, right):
    return all(left.get(k) == right.get(k) for k in ('paper_id', 'physical_source', 'english_hash'))


def _quantity_phrase(prepared, source, destination, transfer):
    """Accept only the reviewed native million quantity construction, not proximity."""
    proof = transfer.get('quantity_phrase_proof')
    _require(isinstance(proof, dict), 'native quantity phrase proof is required')
    grammar = proof.get('grammar_evidence'); native = proof.get('native_dictionary_evidence')
    pin = proof.get('source_pin')
    _require(isinstance(pin, dict) and isinstance(pin.get('file'), str) and pin['file'] and
             isinstance(pin.get('sha256'), str) and re.fullmatch(r'[0-9a-f]{64}', pin['sha256']), 'native quantity audit source is not pinned')
    _require(isinstance(grammar, dict) and isinstance(native, dict), 'native quantity grammar/dictionary proof is incomplete')
    x, y = source['target_range']; a, b = destination['target_range']
    _require(grammar.get('source_target_range') == [x, y] and grammar.get('destination_target_range') == [a, b] and
             grammar.get('whole_phrase_range') == proof.get('shared_whole_phrase_range') == [x, b] and
             grammar.get('distinct_component_ranges') is True and grammar.get('whole_phrase') == 'the millions' and
             grammar.get('scope') == 'by + the + plural number millions', 'native quantity component ranges or scope differ')
    english = source['english']
    _require(prepared['word'].casefold() == 'million' and transfer['source_word'].casefold() == 'the' and
             english[x:y].casefold() == 'the' and english[a:b].casefold() == 'millions' and
             x < y < a < b and english[y:a].isspace() and
             re.search(r'\bby\s+$', english[:x], re.IGNORECASE), 'native quantity phrase is not the proven by the millions construction')
    sense = transfer.get('matched_sense') or {}
    _require(native.get('native_definition_valid') is True and native.get('raw_entry_valid') is True and
             native.get('source_headword') == 'million' and native.get('pos') == sense.get('pos') == 'num.' and
             native.get('part_of_speech') == 'number' and native.get('chinese') == sense.get('text') == '一百万' and
             native.get('english') == '1 000 000', 'native quantity number sense differs')
    notes = native.get('native_usage_notes')
    _require(isinstance(notes, list) and any(isinstance(note, str) and
             'Millions (of' in note and 'no number or quantity before it' in note for note in notes), 'native plural quantity scope is missing')
    ref = native.get('source_ref')
    _require(isinstance(ref, dict) and ref.get('dictionary') == 'oald10' and ref.get('provider') == 'oxford' and
             ref.get('source_headword') == 'million' and isinstance(native.get('native_db_path'), str) and native['native_db_path'] and
             all(isinstance(ref.get(key), str) and re.fullmatch(r'[0-9a-f]{64}', ref[key]) for key in
                 ('raw_sha256', 'definition_html_sha256')), 'native quantity dictionary entry is not pinned')
    authority = transfer.get('exclusion_authority') or {}
    if isinstance(authority.get('authority'), dict): authority = authority['authority']
    audit = authority.get('audit')
    _require(isinstance(audit, dict) and audit.get('grammar_evidence') == grammar and
             any(isinstance(target, dict) and target.get('card_id') == transfer['target_card_id'] and
                 target.get('occurrence_id') == destination['occurrence_id'] and
                 target.get('match_kind') == 'same_native_quantity_phrase' and
                 target.get('grammar_evidence') == grammar and target.get('native_dictionary_evidence') == native and
                 target.get('shared_whole_phrase_range') == proof['shared_whole_phrase_range'] for target in audit.get('targets', [])),
             'native quantity proof is absent from confirmed exclusion authority')


def _matched_sense(prepared, destination, transfer):
    supplied = transfer.get('matched_sense')
    _require(isinstance(supplied, dict) and isinstance(supplied.get('source_provenance'), dict)
             and supplied['source_provenance'] and supplied.get('dictionary_source'), 'actual destination dictionary sense provenance is required')
    current = next((s for s in prepared['senses'] if s['sense_id'] == destination['sense_id']), None)
    _require(current is not None, 'destination assigned sense does not exist')
    _require(all(supplied.get(k) == current[k] for k in ('pos', 'text', 'ordinal')), 'destination meaning/POS/ordinal differs')
    provenance = prepared['definition_provenance']
    appended = next((part for part in provenance.get('supplemental_definitions', {}).get('appended', [])
                     if part.get('ordinal') == current['ordinal']), None)
    dictionary = (appended.get('source_dictionary') if appended else None) or prepared['definition_source']
    _require(supplied['dictionary_source'] == dictionary, 'actual destination dictionary source differs')
    native = supplied['source_provenance']
    if 'page_sha256' in native:
        _require(native['page_sha256'] == provenance.get('page_sha256'), 'actual destination dictionary page pin differs')
    if 'definition_headword' in native:
        _require(native['definition_headword'] == provenance.get('headword'), 'actual destination dictionary headword differs')
    if 'definition_source' in native:
        _require(native['definition_source'] == prepared['definition_source'], 'actual destination dictionary provenance differs')
    if 'components' in native:
        components = [part for part in provenance.get('components', []) if
            part['sense_start'] <= current['ordinal'] < part['sense_start'] + part['sense_count']]
        _require(native['components'] == components, 'actual destination dictionary component pins differ')
    _require(transfer.get('target_reason') == destination['reason'], 'actual destination review reason differs')
    result = deepcopy(supplied)
    if supplied.get('sense_id') != current['sense_id'] or native.get('snapshot_id') != prepared['snapshot_id']:
        parent = transfer.get('target_parent_row')
        _validate_row(parent)
        snapshot = transfer.get('target_parent_snapshot_id')
        _require(snapshot and supplied['source_provenance'].get('snapshot_id') == snapshot, 'technical rebind lacks actual parent snapshot proof')
        _require(parent['status'] == 'reviewed' and parent['sense_id'] == supplied.get('sense_id') and
                 parent['reviewed_sense_id'] == parent['sense_id'] and parent['reason'] == transfer['target_reason'], 'technical rebind lacks unchanged parent reviewed assignment')
        _require(_physical_equal(parent, destination) and parent['target_range'] == destination['target_range'] and
                 parent['occurrence_id'] == destination['occurrence_id'] and
                 parent['translation_hash'] == destination['translation_hash'] and
                 parent['source_provenance'] == destination['source_provenance'], 'technical rebind changed a physical or linguistic input')
        metadata = {'usage', 'ownership_history', 'ownership_history_unresolved',
                    'sense_id', 'reviewed_sense_id', 'assignment_context_hash'}
        parent_inputs = {k: v for k, v in parent.items() if k not in metadata}
        current_inputs = {k: v for k, v in destination.items() if k not in metadata}
        display_refresh = None
        if parent_inputs != current_inputs:
            _require(parent.get('display') and destination.get('display') and
                     {k: v for k, v in parent_inputs.items() if k != 'display'} ==
                     {k: v for k, v in current_inputs.items() if k != 'display'},
                     'technical rebind changed original review or bilingual presentation')
            from .sense_display import refresh_derived_chunks
            entries = [entry for entry in prepared.get('exam_usage_policy', {}).get('reading_display_projections', [])
                       if entry.get('occurrence_id') == destination['occurrence_id']]
            _require(len(entries) <= 1, 'reading display projection lineage repeats an occurrence')
            if entries:
                from .reading_display_projection import replay_projection
                entry = entries[0]
                _require(entry.get('parent_snapshot_id') == snapshot and
                         entry.get('parent_display_sha256') == parent['display']['display_hash'] and
                         entry.get('target_display_sha256') == destination['display']['display_hash'],
                         'reading display projection lineage is stale')
                projected = deepcopy(parent)
                projected['display'] = replay_projection(entry['authority'], entry['projection'], parent,
                    book_id=prepared['book_id'], card_id=prepared['card_id'], definition_provenance=provenance)
                projected = refresh_derived_chunks(projected)
                method = 'reading_display_projection.replay_projection'
            else:
                projected = refresh_derived_chunks(parent)
                method = 'sense_display.refresh_derived_chunks'
            _require(projected['display'] == destination['display'],
                     'technical rebind display is not the exact approved chunk refresh or reading projection')
            display_refresh = {'method': method,
                'parent_display_sha256': parent['display']['display_hash'],
                'target_display_sha256': projected['display']['display_hash'],
                'original_alignment_sha256': sf._sha(sf._json(parent['alignment'])),
                'alignment_sources_sha256': parent['display']['provenance']['alignment_sources_sha256']}
            if entries:
                display_refresh['projection_sha256'] = sf._sha(sf._json(entry['projection']))
                display_refresh['authority'] = deepcopy(entry['authority'])
        result['technical_rebinding'] = {'old_sense_id': supplied['sense_id'], 'new_sense_id': current['sense_id'],
            'kind': 'metadata_only' if supplied['sense_id'] == current['sense_id'] else 'sense_id_reseal',
            'parent_snapshot_id': snapshot, 'child_snapshot_id': prepared['snapshot_id'],
            'parent_assignment_sha256': sf._sha(sf._json({k: parent[k] for k in
                ('occurrence_id', 'sense_id', 'status', 'reason', 'method', 'review_version',
                 'reviewed_sense_id', 'assignment_context_hash')}))}
        result['sense_id'] = current['sense_id']
        if display_refresh is not None:
            result['technical_rebinding']['display_refresh'] = display_refresh
    return result


def _bind(prepared, destinations, transfer):
    _require(isinstance(transfer, dict), 'ownership transfer must be an object')
    for key in ('book_id', 'source_card_id', 'source_word', 'source_parent_snapshot_id',
                'target_card_id', 'target_occurrence_id'):
        _require(isinstance(transfer.get(key), str) and transfer[key].strip(), 'transfer missing ' + key)
    _require(transfer['book_id'] == prepared['book_id'], 'destination belongs to another book')
    _require(transfer['target_card_id'] == prepared['card_id'], 'destination card differs')
    _require(transfer['source_card_id'] != prepared['card_id'], 'source and destination card are identical')
    _require(transfer.get('verified_physical_match') is True, 'verified physical destination proof is required')
    destination = destinations.get(transfer['target_occurrence_id'])
    _require(destination is not None, 'destination occurrence is absent or excluded by counting scope')
    _validate_row(destination)
    _require(destination['status'] == 'reviewed' and destination['sense_id'] == destination['reviewed_sense_id'], 'destination is not actually reviewed')
    from .exam_frequency import exclude_cloze_option
    from .exam_usage import occurrence_sentence
    _require(not exclude_cloze_option(occurrence_sentence(destination)), 'destination is a count-excluded printed cloze option')
    source = transfer.get('source_parent_row')
    _validate_row(source)
    identity = transfer.get('source_identity')
    _require(isinstance(identity, dict) and all(identity.get(k) == source[k] for k in _IDENTITY_FIELDS), 'source physical/hash/range identity differs')
    _require(_physical_equal(source, destination), 'source and destination are different physical occurrences')
    for key in ('sourceHash',):
        old = source['source_provenance'].get(key); current = destination['source_provenance'].get(key)
        if old is not None or current is not None:
            _require(old == current, 'original paragraph source hash differs')
    _require(transfer.get('target_range') == destination['target_range'], 'actual destination target range differs')
    a, b = destination['target_range']; x, y = source['target_range']
    if transfer.get('match_kind', 'exact_span') in {'exact_span', 'same_physical_exact_span'}:
        _require([a, b] == [x, y] and source['occurrence_id'] == destination['occurrence_id'], 'exact physical target span differs')
    elif transfer.get('match_kind') == 'same_native_quantity_phrase':
        _quantity_phrase(prepared, source, destination, transfer)
    else:
        _require(transfer.get('match_kind') == 'fixed_phrase_contains_exact_component_span' and
                 a <= x < y <= b and ' '.join(destination['english'][a:b].split()).casefold() ==
                 ' '.join(prepared['word'].split()).casefold(), 'complete fixed phrase span does not contain the proven component')
    _validate_authority(transfer, source)
    if transfer.get('source_history_html') is not None:
        _require(isinstance(transfer['source_history_html'], str) and
                 sf._sha(transfer['source_history_html']) == transfer.get('source_history_html_sha256'), 'original historical HTML SHA differs')
    if transfer.get('source_history_ref') is not None:
        ref = transfer['source_history_ref']
        _require(isinstance(ref, dict) and ref.get('file') and re.fullmatch(r'[0-9a-f]{64}', ref.get('sha256', '')), 'historical source reference is not pinned')
    result = deepcopy(transfer)
    result.update(schema=SCHEMA, target_word=prepared['word'], matched_sense=_matched_sense(prepared, destination, transfer))
    result['history_id'] = sf._sha(sf._json([transfer['book_id'], transfer['source_card_id'],
        transfer['source_parent_snapshot_id'], source, transfer['exclusion_authority'],
        transfer['target_card_id'], transfer['target_occurrence_id']]))
    result['content_sha256'] = _content_sha256(result)
    validate_history_content(result)
    return destination, result


def bind_incoming_history(target_prepared, transfers):
    """Return a detached prepared overlay, keeping native counts/snapshot unchanged.

    Each transfer pins a book, source card/word/snapshot/full parent row and
    exclusion authority; an actual target card/occurrence/range; source identity
    (paper, physical source, sentence, English hash, original range); and actual
    dictionary ``matched_sense`` plus ``target_reason``. ``match_kind`` is either
    exact_span (including the same_physical_exact_span spelling),
    fixed_phrase_contains_exact_component_span, or the narrowly
    proven same_native_quantity_phrase construction (quantity_phrase_proof).
    Technical sense-ID
    resealing additionally requires the full target_parent_row and its snapshot.

    A matching English string alone never establishes ownership. Invalid
    transfers are preserved verbatim with a concrete reason in
    ``ownership_history_unresolved``. The caller must preserve both history
    fields through preparation and recompute its snapshot before persistence.
    """
    _require(isinstance(target_prepared, dict) and isinstance(target_prepared.get('occurrences'), list), 'prepared target record is required')
    _require(isinstance(transfers, (list, tuple)), 'transfers must be an array')
    result = deepcopy(target_prepared)
    _require(isinstance(result.get('senses'), list) and result.get('book_id') and result.get('card_id'), 'prepared target identity/senses are required')
    destinations = {r['occurrence_id']: r for r in result['occurrences']}
    _require(len(destinations) == len(result['occurrences']) == result['expected_occurrences'], 'target native physical count does not reconcile')
    unresolved = result.setdefault('ownership_history_unresolved', [])
    seen_unresolved = {sf._sha(sf._json(item)) for item in unresolved}
    for transfer in transfers:
        try:
            destination, history = _bind(result, destinations, transfer)
        except (ValueError, KeyError, TypeError) as error:
            item = {'schema': SCHEMA, 'status': 'unresolved', 'reason': str(error), 'transfer': deepcopy(transfer)}
            key = sf._sha(sf._json(item))
            if key not in seen_unresolved:
                unresolved.append(item); seen_unresolved.add(key)
            continue
        histories = destination.setdefault('ownership_history', [])
        if not any(h.get('history_id') == history['history_id'] for h in histories):
            histories.append(history)
    return result


def _safe_url(value):
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        return None
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {'', 'http', 'https'} or (not parsed.scheme and parsed.netloc):
        return None
    return value.strip()


class _HistoricalHTML(HTMLParser):
    """Keep readable historical panels and chunk markup without executable HTML."""
    tags = {'details', 'summary', 'article', 'section', 'div', 'p', 'span', 'mark', 'strong',
            'em', 'b', 'i', 'small', 'pre', 'code', 'ul', 'ol', 'li', 'a', 'br', 'hr',
            'table', 'thead', 'tbody', 'tr', 'th', 'td', 'h1', 'h2', 'h3', 'h4', 'button'}
    blocked = {'script', 'style', 'iframe', 'object', 'embed', 'svg', 'math', 'template'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output = []; self.suppressed = []
    def handle_starttag(self, tag, attrs):
        if tag in self.blocked:
            self.suppressed.append(tag); return
        if self.suppressed or tag not in self.tags: return
        safe = []
        for key, value in attrs:
            if value is None: continue
            if key == 'href' and tag == 'a': value = _safe_url(value)
            elif key not in {'class', 'title', 'aria-label', 'data-chunk-side', 'data-chunk-ids', 'data-sf-year'}:
                continue
            if key == 'class':
                aliases = {'sf-example': 'sf-archived-example', 'example-card': 'sf-archived-native-example'}
                value = ' '.join(aliases.get(token, token) for token in value.split())
            if value is not None: safe.append(' ' + key + '="' + html.escape(value, quote=True) + '"')
        self.output.append('<' + tag + ''.join(safe) + '>')
    def handle_endtag(self, tag):
        if self.suppressed:
            if tag == self.suppressed[-1]: self.suppressed.pop()
            return
        if tag in self.tags and tag not in {'br', 'hr'}: self.output.append('</' + tag + '>')
    def handle_data(self, data):
        if not self.suppressed: self.output.append(html.escape(data))


def _historical_document(history, documents):
    """Validate an optional document overlay against the immutable reference."""
    original = history.get('source_history_html')
    if original is not None:
        _require(sf._sha(original) == history.get('source_history_html_sha256'), 'historical HTML was modified after binding')
    ref = history.get('source_history_ref')
    if ref is None or documents is None:
        return original, _safe_url(ref.get('url')) if isinstance(ref, dict) else None
    _require(isinstance(documents, dict), 'historical document overlay must be an object')
    document = documents.get(ref['file'])
    _require(isinstance(document, dict) and document.get('reference') == ref, 'historical document reference differs')
    full = document.get('document_html'); raw = document.get('original_html')
    _require(isinstance(full, str) and sf._sha(full) == ref['sha256'], 'historical full document SHA differs')
    _require(isinstance(raw, str) and sf._sha(raw) == document.get('original_html_sha256') and
             html.escape(raw) in full, 'historical original diagnostic is not proven by its document')
    if original is not None:
        _require(raw == original, 'historical document original differs from sealed HTML')
    inline = document.get('inline_history_ids')
    if inline is not None:
        _require(isinstance(inline, list) and all(isinstance(value, str) for value in inline), 'historical inline history IDs must be an array')
        _require(history['history_id'] in inline or _safe_url(ref.get('url')), 'non-inline historical document needs a visible source link')
    return (raw if inline is None or history['history_id'] in inline else None), _safe_url(ref.get('url'))


def render_ownership_history(row, link_map=None, *, documents=None, include_source_example=True):
    """Render complete incoming evidence beneath the actual destination example."""
    _require(isinstance(include_source_example, bool), 'source example visibility must be a boolean')
    histories = row.get('ownership_history', [])
    if not histories: return ''
    _require(isinstance(histories, list), 'ownership history must be an array')
    links = link_map or {}; output = []
    for history in histories:
        validate_history_content(history)
        source = deepcopy(history['source_parent_row'])
        _validate_row(source)
        # The shared preview can itself be patched to render history. Removing
        # only this overlay prevents recursion while retaining all source chunks.
        source.pop('ownership_history', None); source.pop('ownership_history_unresolved', None)
        book, card = history['book_id'], history['source_card_id']
        url = links.get((book, card), links.get(book, {}).get(card) if isinstance(links.get(book), dict) else links.get(card))
        url = _safe_url(url or history.get('source_parent_page_url'))
        word = html.escape(history['source_word'])
        if url: word = '<a href="' + html.escape(url, quote=True) + '">' + word + '</a>'
        sense = history['matched_sense']
        correct = html.escape(str(sense['pos']) + ' ' + sense['text'])
        position = html.escape(source['paper_id'] + ' · ' + source['sentence_id'] + ' · ' + str(source['target_range']))
        summary = '原 ' + word + ' 卡的完整归属历史' if include_source_example else '本句归属说明'
        parts = ['<details class="sf-ownership-history" data-ownership-history-id="'
            + html.escape(history['history_id'], quote=True)
            + '" data-ownership-content-sha256="' + history['content_sha256']
            + '" data-ownership-target-occurrence-id="'
            + html.escape(history['target_occurrence_id'], quote=True) + '"><summary>' + summary + '</summary>',
            '<p class="sf-owner">实际词条：' + html.escape(history['target_word']) + ' · ' + correct +
            ' · ' + html.escape(str(sense['dictionary_source'])) + '</p>',
            '<p class="sf-reason">实际义项依据：' + html.escape(history['target_reason']) + '</p>',
            '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：' + html.escape(source['reason']) + '</p>',
            '<p class="sf-source">原物理位置：' + position + '</p>']
        if not include_source_example:
            parts.insert(1, '<p class="sf-source">原卡：' + word + '</p>')
        if include_source_example:
            parts.append(sf._previews([source]))
        else:
            start, end = source['target_range']
            parts.append('<p class="sf-source">原先目标标记：<mark>' + html.escape(source['english'][start:end]) +
                         '</mark> · ' + html.escape(source['source']) + '</p>')
        historical, document_url = _historical_document(history, documents)
        if historical:
            parser = _HistoricalHTML(); parser.feed(historical); parser.close()
            parts += ['<details class="sf-original-history-panel"><summary>原界面的完整审核说明</summary>', ''.join(parser.output), '</details>']
        if document_url:
            parts.append('<p><a class="sf-original-history-link" href="' + html.escape(document_url, quote=True) + '">查看完整原审核记录</a></p>')
        parts += ['<details class="sf-ownership-authority"><summary>原审核权威与来源记录</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">',
                  html.escape(sf._json({'source_parent_snapshot_id': history['source_parent_snapshot_id'],
                      'source_parent_definition_id': history.get('source_parent_definition_id'),
                      'source_parent_page_url': history.get('source_parent_page_url'),
                      'source_parent_page_sha256': history.get('source_parent_page_sha256'),
                      'source_history_ref': history.get('source_history_ref'),
                      'exclusion_authority': history['exclusion_authority'],
                      'matched_sense': sense})), '</pre></details></details>']
        output.append(''.join(parts))
    return ''.join(output)


def validate_rendered_history_coverage(page, prepared, coverage, *,
                                      ownership_history_documents=None, target_urls=None,
                                      aliases=None):
    """Prove complete histories are inline in their exact current sentences.

    Native absence is allowed only when the same retained physical occurrence
    has a fully rendered SF sentence and complete explanation. Metadata alone,
    an archived example, an old snapshot or a standalone panel cannot satisfy
    coverage. Rebuild expected HTML from validated immutable history/documents
    so deleting explanation text while retaining its SHA marker also fails.
    """
    from collections import Counter
    from .native_example_usage import _Offsets, _rows, _native_histories
    from .sense_chunks import render_sentence_pair

    _require(isinstance(page, str) and isinstance(coverage, dict),
             'ownership coverage requires final HTML and native proof')
    sealed = dict(coverage)
    claimed = sealed.pop('coverage_sha256', None)
    _require(claimed == sf._sha(sf._json(sealed)), 'ownership coverage SHA differs')
    _require(coverage.get('schema') == 'ownership-native-coverage.v1' and
             all(coverage.get(key) == prepared.get(key) for key in
                 ('book_id', 'card_id', 'snapshot_id')), 'ownership coverage snapshot/card differs')
    rows = _rows(prepared)
    markup, pins = _native_histories(prepared, rows,
        documents=ownership_history_documents, target_urls=target_urls)
    native, deferred = coverage.get('native'), coverage.get('deferred')
    native_examples = coverage.get('native_examples')
    _require(isinstance(native, dict) and isinstance(deferred, dict) and
             isinstance(native_examples, dict) and not (set(native) & set(deferred)) and
             set(native) | set(deferred) == set(pins), 'ownership coverage inventory differs')
    _require({**native, **deferred} == pins and set(native_examples) == set(native) and
             all(isinstance(values, list) and values and all(
                 isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                 for value in values) for values in native_examples.values()),
             'ownership coverage histories/native sentence pins differ')

    expected = {}
    for identity, raw in markup.items():
        for detail in _Offsets(raw, {}).root.children:
            key = (identity, detail.attrs.get('data-ownership-history-id'))
            _require(detail.tag == 'details' and detail.end is not None and key not in expected,
                     'ownership expected history HTML is invalid or duplicated')
            expected[key] = sf._sha(raw[detail.start:detail.end])

    sf_seen, native_seen, native_nodes = Counter(), Counter(), {}
    parser = _Offsets(page, aliases or {})
    current_articles = {}
    for detail in parser.root.walk():
        if 'sf-ownership-history' not in detail.classes:
            continue
        ancestors, parent = [], detail.parent
        while parent is not None:
            ancestors.append(parent)
            parent = parent.parent
        # Complete old panels are evidence, not current sentence coverage.
        if any('sf-ownership-history' in node.classes or
               'sf-original-history-panel' in node.classes for node in ancestors):
            continue
        _require(not any(node.tag == 'template' or node.classes & {
                 'sf-archived-example', 'sf-archived-native-example'} for node in ancestors),
                 'ownership archived/template history cannot satisfy current coverage')
        identity = detail.attrs.get('data-ownership-target-occurrence-id')
        hid = detail.attrs.get('data-ownership-history-id')
        key = identity, hid
        _require(key in expected and detail.end is not None,
                 'ownership history is foreign or has no complete sentence boundary')
        pin = next(item for item in pins[identity] if item['history_id'] == hid)
        _require(detail.attrs.get('data-ownership-content-sha256') == pin['content_sha256'] and
                 sf._sha(page[detail.start:detail.end]) == expected[key],
                 'ownership history rendered content differs from complete immutable evidence')
        container = detail.parent
        # A collapsed <details> remains available through its summary. Explicit
        # hidden/inert sentence content cannot count as accessible evidence.
        local_ancestors = [detail]
        for node in ancestors:
            local_ancestors.append(node)
            if 'sf-report' in node.classes or (node.tag == 'li' and 'example-card' in node.classes):
                break
        _require(not any('hidden' in node.attrs or 'inert' in node.attrs or
                 node.attrs.get('aria-hidden', '').lower() == 'true' or
                 re.search(r'(?:^|;)(?:display:none|visibility:hidden|content-visibility:hidden)(?:!important)?(?:;|$)',
                     re.sub(r'\s+', '', re.sub(r'/\*.*?\*/', '', node.attrs.get('style', ''), flags=re.S)).lower())
                 for node in local_ancestors), 'ownership sentence/history is explicitly hidden')
        if container.tag == 'article' and 'sf-example' in container.classes:
            _require(container.attrs.get('data-sf-occurrence-id') == identity and
                     container.end is not None, 'ownership SF sentence occurrence differs')
            reports = [node for node in ancestors if 'sf-report' in node.classes]
            _require(len(reports) == 1 and reports[0].attrs.get('data-snapshot') == prepared['snapshot_id']
                     and reports[0].attrs.get('data-sense-frequency') == 'v1',
                     'ownership SF sentence does not belong to the current snapshot')
            pairs = [node for node in container.children if 'sf-sentence-pair' in node.classes]
            _require(len(pairs) == 1 and pairs[0].end is not None and
                     page[pairs[0].start:pairs[0].end] == render_sentence_pair(rows[identity]),
                     'ownership SF sentence text/chunks differ from its actual occurrence')
            previous = current_articles.setdefault(identity, container)
            _require(previous is container, 'ownership SF sentence is duplicated')
            sf_seen[key] += 1
        elif container.attrs.get('data-native-ownership-history') == 'v1':
            example = container.parent
            _require(container.tag == 'div' and example is not None and example.tag == 'li' and
                     'example-card' in example.classes and example.end is not None and identity in native,
                     'ownership native explanation has no bound native sentence')
            native_nodes.setdefault(identity, {})[example.start] = sf._sha(page[example.start:example.end])
            native_seen[key] += 1
        else:
            raise ValueError('ownership history must be inline inside its actual sentence')

    _require(sf_seen == Counter({key: 1 for key in expected}),
             'ownership SF history coverage is missing or duplicated')
    actual_native = {identity: sorted(values.values()) for identity, values in native_nodes.items()}
    _require(actual_native == native_examples,
             'ownership native coverage differs from the actual final DOM')
    _require(native_seen == Counter({(identity, pin['history_id']): len(native_examples[identity])
                                    for identity, values in native.items() for pin in values}),
             'ownership native history coverage is missing or duplicated')
    proof = {'schema': 'ownership-rendered-coverage.v1',
        'book_id': prepared['book_id'], 'card_id': prepared['card_id'],
        'snapshot_id': prepared['snapshot_id'], 'page_sha256': sf._sha(page),
        'native_coverage_sha256': claimed, 'expected_histories': len(expected),
        'sf_histories': sum(sf_seen.values()), 'native_histories': sum(native_seen.values()),
        'sf_only_histories': sum(len(values) for values in deferred.values()),
        'bound_occurrences': sorted(pins)}
    proof['proof_sha256'] = sf._sha(sf._json(proof))
    return proof
