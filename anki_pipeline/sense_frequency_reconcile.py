"""Source-bound, reversible frequency repairs for isolated preview copies.

The live source-displays producer is the trust boundary. A serialized display
hash only proves internal consistency; it does not authorize a frequency repair.
This module performs no database, page, package or other filesystem writes.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import html
import json
import re
from types import MappingProxyType
import unicodedata

from . import sense_display
from .exam_frequency import frequency_for_matches
from .exam_library import _canonical_codex_sentences
from .local_dictionary import _Tree
from .packaging import _exam_frequency_markup
from .text import word_variants


SCHEMA = 'exam-frequency-preview-reconciliation.v1'
_ISSUER = object()
_TOKEN = re.compile(r"(?<!\w)[^\W\d_]+(?:[-'][^\W\d_]+)*(?!\w)", re.UNICODE)
_FORM_LABELS = frozenset({'原形', '复数', '第三人称单数', '现在分词',
                          '过去式', '过去分词', '比较级', '最高级'})


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _key(record):
    try:
        key = (record['book_id'], record['card_id'])
    except (KeyError, TypeError) as error:
        raise ValueError('source record needs its book and card identity') from error
    if any(not isinstance(value, str) or not value.strip() for value in key):
        raise ValueError('source record needs its book and card identity')
    return key


def _page(pages, key):
    page = pages.get(key, pages.get(key[1]))
    if not isinstance(page, str):
        raise ValueError('source record needs its exact original page')
    return page


def _physical_rows(record):
    """Reject duplicate positions; never silently deduplicate a repair input."""
    rows, unique = record.get('occurrences'), set()
    if not isinstance(rows, list):
        raise ValueError('source occurrences must be an array')
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('physical occurrence must be an object')
        paper, sentence, source = row.get('paper_id'), row.get('sentence_id'), row.get('physical_source')
        english, span = row.get('english'), row.get('target_range')
        if (not isinstance(paper, str) or not re.fullmatch(r'kaoyan:\d{4}-\d{2}', paper) or
                not isinstance(sentence, str) or not sentence.startswith(paper + ':') or
                not isinstance(source, list) or not source or
                not isinstance(english, str) or not english or
                row.get('english_hash') != _sha(english) or
                not isinstance(span, list) or len(span) != 2 or
                any(type(part) is not int for part in span) or
                not 0 <= span[0] < span[1] <= len(english)):
            raise ValueError('physical source identity, English hash or target range is invalid')
        identity = _json([paper, source, span])
        if identity in unique:
            raise ValueError('duplicate physical token cannot authorize frequency reconciliation')
        unique.add(identity)
    if type(record.get('expected_occurrences')) is not int or len(rows) != record['expected_occurrences']:
        raise ValueError('physical occurrences differ from the record count')
    return rows


def _require_unpersisted_source(record):
    # A stored ledger proves serialization consistency, not a live exclusion
    # capability. Reissuing ordinary authority from its already filtered rows
    # would erase the candidate-ledger binding and let a single-panel a card
    # enter generic frequency reconciliation without its exclusion audit.
    if isinstance(record, dict) and 'candidate_scope' in record:
        raise ValueError('persisted candidate scope requires original source replay and a live approved overlay')


class _ImmutableIssued:
    __slots__ = ()

    def __setattr__(self, name, value):
        raise AttributeError('producer-issued source bindings and plans are immutable')


class VerifiedSourceDisplays(_ImmutableIssued):
    """Ephemeral producer-issued capability, not a source signature or JSON API.

    Callers obtain this only from ``reread_source_displays``. Records and pages
    are bound to that exact successful read; arbitrary booleans, validators or
    exported display digests cannot be promoted to source authority.
    """
    __slots__ = ('_bindings', '_producer_sha256', '_aliases_sha256', '_source_proofs',
                 '_source_manifest', '_candidate_ledger_hashes')

    def __init__(self, bindings, producer_sha256, aliases_sha256, source_proofs, source_manifest,
                 *, _issuer=None, candidate_ledger_hashes=None):
        if _issuer is not _ISSUER:
            raise ValueError('source authority must come from the source-displays producer')
        object.__setattr__(self, '_bindings', MappingProxyType(dict(bindings)))
        object.__setattr__(self, '_producer_sha256', producer_sha256)
        object.__setattr__(self, '_aliases_sha256', aliases_sha256)
        object.__setattr__(self, '_source_proofs', MappingProxyType(dict(source_proofs)))
        object.__setattr__(self, '_source_manifest', _json(source_manifest))
        object.__setattr__(self, '_candidate_ledger_hashes', MappingProxyType(dict(candidate_ledger_hashes or {})))

    def _require(self, page, record, aliases):
        binding = self._bindings.get(_key(record))
        if (binding is None or binding != (_sha(_json(record)), _sha(page)) or
                self._aliases_sha256 != _sha(_json(aliases))):
            raise ValueError('record, page or aliases changed after the source-displays producer read')


def _source_proofs(records, sources):
    """Verify canonical physical keys using the same approved corpus rules."""
    selected, _ = _canonical_codex_sentences(list(sources['sentences'].values()))
    by_id = {}
    for sentence in selected:
        for identifier in sentence['source_sentence_ids']:
            if identifier in by_id:
                raise ValueError('approved canonical source has a duplicate sentence identity')
            by_id[identifier] = sentence
    proofs = {}
    for record in records:
        rows = []
        for row in record['occurrences']:
            source = by_id.get(row['sentence_id'])
            if source is None or (source['canonical_occurrence_key'] != row['physical_source'] or
                    source['paperId'] != row['paper_id']):
                raise ValueError('physical source does not match its approved canonical key')
            if (source['english'] != row['english'] or source['englishHash'] != row['english_hash'] or
                    source['translationZh'] != row['translation'] or
                    source['reviewedContentHash'] != row['source_provenance'].get('reviewedContentHash')):
                raise ValueError('canonical physical source English or reviewed context is stale')
            provenance = row['source_provenance']
            expected = {'sourceHash': source['sourceHash'], 'paragraphId': source['paragraphId'],
                'paragraphRange': [source['start'], source['end']],
                'sourceBlockIds': source['sourceBlockIds'], 'sourceFragments': source['sourceFragments'],
                'sourceSentenceRefs': source['sourceSentenceRefs'],
                'sourceSentenceIds': source['source_sentence_ids']}
            for field, value in expected.items():
                if field in provenance and provenance[field] != value:
                    raise ValueError(f'canonical source {field} differs from its approved position')
            rows.append({'canonical_physical_source': deepcopy(source['canonical_occurrence_key']),
                'paper_id': source['paperId'], 'sentence_id': source['id'],
                'source_english_hash': source['englishHash'],
                'source_reviewed_content_hash': source['reviewedContentHash'],
                **deepcopy(expected)})
        proofs[_key(record)] = _json(rows)
    return proofs


def reread_source_displays(records, pages, aliases, **source_options):
    """Return ``(records, capability)`` after the approved producer rereads sources.

    All producer options are forwarded to ``attach_source_displays``. Its source
    loading and before/after watched-file validation are deliberately retained.
    Only optional presentation is added; original definitions, counts, physical
    source positions and explicit review seals remain unchanged.
    Persisted candidate overlays must first be restored to original records;
    serialized ledgers cannot obtain ordinary producer authority.
    """
    if not isinstance(records, list) or not isinstance(pages, dict) or not isinstance(aliases, dict):
        raise ValueError('producer requires record, source-page and alias collections')
    bindings = {}
    for record in records:
        _require_unpersisted_source(record)
        _physical_rows(record)
        key = _key(record)
        if key in bindings:
            raise ValueError('duplicate book/card source record')
        page = _page(pages, key)
        bindings[key] = (_sha(_json(record)), _sha(page))
    # Read the actual producer implementation rather than trusting provenance
    # fields carried in caller-supplied displays from an earlier run.
    from pathlib import Path
    producer_sha = hashlib.sha256(Path(sense_display.__file__).read_bytes()).hexdigest()
    # Display validation alone does not bind arbitrary physical_source values.
    # Reread approved source metadata independently and preserve its complete
    # manifest; the actual producer must subsequently observe the same inputs.
    sources = sense_display._load_sources(**source_options)
    source_proofs = _source_proofs(records, sources)
    source_manifest = {str(path): digest for path, digest in sources['watched'].items()}
    producer_manifest_sha = _sha(json.dumps(source_manifest, sort_keys=True))
    result = sense_display.attach_source_displays(records, pages, aliases, **source_options)
    if not isinstance(result, list) or len(result) != len(records):
        raise ValueError('source-displays producer changed the record collection')
    approved = {}
    for original, record in zip(records, result):
        key = _key(record)
        if key != _key(original):
            raise ValueError('source-displays producer changed a book/card identity')
        unchanged = deepcopy(record)
        for row, old in zip(unchanged['occurrences'], original['occurrences']):
            if 'display' in old:
                row['display'] = deepcopy(old['display'])
            else:
                row.pop('display', None)
        if unchanged != original:
            raise ValueError('source-displays producer changed physical or reviewed inputs')
        page = _page(pages, key)
        if bindings[key] != (_sha(_json(original)), _sha(page)):
            raise ValueError('source inputs changed during the source-displays producer read')
        for row in record['occurrences']:
            display = sense_display.validate_display(row.get('display'), row, record['definition_provenance'])
            if display['provenance']['input_manifest_sha256'] != producer_manifest_sha:
                raise ValueError('source manifest differs from the source-displays producer read')
        approved[key] = (_sha(_json(record)), _sha(page))
    if hashlib.sha256(Path(sense_display.__file__).read_bytes()).hexdigest() != producer_sha:
        raise ValueError('source-displays producer changed during source verification')
    for path, digest in sources['watched'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('approved canonical source input changed during producer verification')
    return result, VerifiedSourceDisplays(approved, producer_sha, _sha(_json(aliases)),
        source_proofs, source_manifest, _issuer=_ISSUER)


def _tree(fragment, aliases):
    root = _Tree(fragment).root
    for node in root.walk():
        if 'class' in node.attrs:
            node.attrs['class'] = ' '.join(aliases.get(value, value)
                                         for value in node.attrs['class'].split())
    return root


def _fragments(page, tag, class_name, aliases):
    """Locate complete source blocks and preserve their exact original bytes."""
    for opening in re.finditer(r'<' + tag + r'\b[^>]*>', page):
        node = next((node for node in _tree(opening[0] + '</' + tag + '>', aliases).walk()
                     if node.tag == tag), None)
        if node is None or not node.has_class(class_name):
            continue
        depth = 1
        for closing in re.finditer(r'</?' + tag + r'\b[^>]*>', page[opening.end():]):
            depth += -1 if closing[0].startswith('</') else 1
            if depth == 0:
                yield page[opening.start():opening.end() + closing.end()]
                break
        else:
            raise ValueError('unterminated original frequency or word-form block')


def _forms(page, word, aliases):
    root = _tree(page, aliases)
    headwords = [node.text().strip() for node in root.walk()
                 if node.tag == 'h1' and node.has_class('word')]
    if not headwords or any(value != word for value in headwords):
        raise ValueError('visible original headword differs from the bound card')
    lemmas = word_variants(word, infer=False)
    if not lemmas:
        raise ValueError('frequency repair requires an explicit single-token headword')
    evidence = [{'form': value, 'kind': 'lemma', 'source': 'original-headword'}
                for value in sorted(lemmas)]
    allowed = set(lemmas)
    for group in root.walk():
        if not group.has_class('dictionary-form-groups'):
            continue
        for section in group.walk():
            if not section.has_class('dictionary-inflections'):
                continue
            source = section.attrs.get('data-dictionary', group.attrs.get('data-dictionary', 'webster'))
            for row in section.walk():
                if not row.has_class('form-row') or row.has_class('derived-word'):
                    continue
                label = next((node for node in row.walk() if node.tag == 'dt'), None)
                value = next((node for node in row.walk() if node.tag == 'dd'), None)
                if label is None or value is None:
                    raise ValueError('displayed inflection lacks its original label or text')
                if label.text().strip() not in _FORM_LABELS:
                    continue
                raw = ''.join(child if isinstance(child, str) else child.text()
                              for child in value.children if isinstance(child, str) or child.tag != 'small').strip()
                form = unicodedata.normalize('NFKC', raw).casefold()
                if not re.fullmatch(r"[a-z]+(?:[-'][a-z]+)*", form):
                    continue
                if label.text().strip() == '原形' and form not in lemmas:
                    raise ValueError('displayed base form belongs to another headword')
                allowed.add(form)
                evidence.append({'form': form, 'kind': label.text().strip(), 'source': source,
                                 'displayed_text': raw})
    return allowed, evidence


def _old_frequency(panel, aliases):
    section = next(node for node in _tree(panel, aliases).walk() if node.tag == 'section')
    attrs, result = section.attrs, {}
    fields = {'occurrences': 'data-occurrences', 'paper_count': 'data-paper-count',
              'corpus_papers': 'data-corpus-papers', 'matched_sentences': 'data-matched-sentences'}
    for key, attribute in fields.items():
        raw = attrs.get(attribute)
        if not isinstance(raw, str) or not re.fullmatch(r'\d+', raw):
            raise ValueError('old frequency panel has incomplete count declarations')
        result[key] = int(raw)
    stars = attrs.get('data-stars')
    if not isinstance(stars, str) or not re.fullmatch(r'\d+(?:\.\d+)?', stars):
        raise ValueError('old frequency panel has no exact rating declaration')
    result.update(stars=float(stars), schema=attrs.get('data-schema'), rule=attrs.get('data-rule'))
    _exam_frequency_markup({'exam_frequency': result})  # Existing authoritative guards.
    return result


class FrequencyPanelPlan(_ImmutableIssued):
    """Immutable original/new panel bytes and JSON audit for a preview-only edit."""
    __slots__ = ('_payload',)

    def __init__(self, payload, *, _issuer=None):
        if _issuer is not _ISSUER:
            raise ValueError('frequency panel plans must be issued by the source-bound planner')
        object.__setattr__(self, '_payload', _json(payload))

    def verification(self):
        """Return a serializable audit copy, including the reversible old panel."""
        return json.loads(self._payload)


def _frequency(rows, corpus_papers):
    counts, contexts = Counter(), {}
    for row in rows:
        identity = (row['paper_id'], _json(row['physical_source']))
        context = (row['english_hash'], _sha(row['translation']))
        if identity in contexts and contexts[identity] != context:
            raise ValueError('one physical source cannot have contradictory sentence text')
        contexts[identity] = context
        counts[identity] += 1
    return frequency_for_matches(((paper, physical, 0, count)
        for (paper, physical), count in counts.items()), corpus_papers)


def _scope_component_forms(page, raw_record, aliases, ledger):
    """Assign original explicit forms to the correct source component only."""
    root = _tree(page, aliases)
    words = [node.text().strip() for node in root.walk()
             if node.tag == 'h1' and node.has_class('word')]
    if not words or any(word != raw_record['word'] for word in words):
        raise ValueError('candidate panel headword differs from the original source')
    provenance = raw_record['definition_provenance']
    components = provenance.get('components')
    definitions = list(_fragments(page, 'div', 'dictionary-definition', aliases))
    names = ['a', 'an'] if raw_record['word'] == 'a/an' else ['a']
    if (not isinstance(components, list) or len(components) != len(names) or len(definitions) != len(names) or
            raw_record['word'] not in {'a', 'a/an'}):
        raise ValueError('candidate repair needs original a/an component definitions')
    for index, (component, definition, name) in enumerate(zip(components, definitions, names)):
        if (component.get('component_index') != index or component.get('html_sha256') != _sha(definition) or
                component.get('headword', name) != name):
            raise ValueError('candidate component headword or definition bytes changed')
    original_forms = ledger['original_forms']
    span, forms_html = original_forms['range'], original_forms['html']
    if (not isinstance(span, list) or len(span) != 2 or any(type(i) is not int for i in span) or
            not 0 <= span[0] < span[1] <= len(page) or page[span[0]:span[1]] != forms_html):
        raise ValueError('candidate original word-form evidence differs from its source page')
    allowed = {name: {name} for name in names}
    evidence = {name: [{'form': name, 'kind': 'lemma', 'source': 'original-component-headword'}]
                for name in names}
    form_tree = _tree(forms_html, aliases)
    for group in form_tree.walk():
        if not group.has_class('dictionary-form-groups'):
            continue
        owner = names[0] if len(names) == 1 else None
        if len(names) > 1:
            ancestor = group.parent
            while ancestor is not None and owner is None:
                headings = [child.text().strip() for child in ancestor.children
                            if not isinstance(child, str) and child.tag == 'h3']
                matches = [name for name in names if name + ' · 词形' in headings]
                if len(matches) > 1:
                    raise ValueError('original word-form group has ambiguous component ownership')
                owner = matches[0] if matches else None
                ancestor = ancestor.parent
        if owner is None:
            raise ValueError('original word-form group lacks its component headword')
        for row in group.walk():
            if not row.has_class('form-row') or row.has_class('derived-word'):
                continue
            label = next((child for child in row.walk() if child.tag == 'dt'), None)
            value = next((child for child in row.walk() if child.tag == 'dd'), None)
            if label is None or value is None:
                raise ValueError('original component inflection lacks label or value')
            if label.text().strip() not in _FORM_LABELS:
                continue
            text = ''.join(child if isinstance(child, str) else child.text()
                           for child in value.children if isinstance(child, str) or child.tag != 'small').strip()
            form = unicodedata.normalize('NFKC', text).casefold()
            if not re.fullmatch(r"[a-z]+(?:[-'][a-z]+)*", form):
                continue
            allowed[owner].add(form)
            evidence[owner].append({'form': form, 'kind': label.text().strip(),
                'displayed_text': text, 'source': group.attrs.get('data-dictionary', 'webster')})
    return names, allowed, evidence


def _collector_target_boundary(english, span):
    """Recognize an exact boundary emitted by the original token collector.

    ``prepare_sense_frequency_records.token_index`` indexes a full token and
    consecutive complete letter components joined by ASCII hyphen/apostrophe.
    A component such as ``a`` in ``two-and-a-half`` remains the original exact
    physical target; it must not be extended to the parent compound. This is a
    candidate-boundary check, not a semantic confirmation or an inflection rule.
    """
    for parent in _TOKEN.finditer(english):
        if not parent.start() <= span[0] < span[1] <= parent.end():
            continue
        evidence = {'parent_text': parent[0], 'parent_range': list(parent.span()),
                    'target_text': english[slice(*span)], 'target_range': list(span)}
        if span == parent.span():
            return {'kind': 'whole-token', **evidence}
        pieces = list(re.finditer(r"[^\W\d_]+", parent[0], re.UNICODE))
        starts = {parent.start() + piece.start(): index for index, piece in enumerate(pieces)}
        ends = {parent.start() + piece.end(): index for index, piece in enumerate(pieces)}
        first, last = starts.get(span[0]), ends.get(span[1])
        if first is not None and last is not None and first <= last:
            return {'kind': 'complete-collector-component', **evidence}
    return None


def _scope_panel_plan(page, record, aliases, verified_sources, scope, panels, frequencies):
    from .sense_candidate_scope import CandidateCardScope
    if type(scope) is not CandidateCardScope:
        raise ValueError('candidate panel correction needs an issued live candidate scope')
    scope._require(record, page)
    ledger, raw = scope.verification(), json.loads(scope._raw_record)
    if verified_sources._candidate_ledger_hashes.get(_key(record)) != ledger['ledger_sha256']:
        raise ValueError('candidate scope does not belong to this derived source capability')
    names, allowed, forms = _scope_component_forms(page, raw, aliases, ledger)
    if len(panels) != len(names) or any(page.count(panel) != 1 for panel in panels):
        raise ValueError('candidate panels do not match their unique original components')
    original, filtered = {name: [] for name in names}, {name: [] for name in names}
    component_boundaries = []
    for rows, groups, is_filtered in ((raw['occurrences'], original, False),
            (record['occurrences'], filtered, True)):
        for original_index, row in enumerate(rows):
            span = tuple(row['target_range'])
            boundary = _collector_target_boundary(row['english'], span)
            if boundary is None:
                raise ValueError('component candidate target must cover a whole original token or complete collector component')
            if not is_filtered and boundary['kind'] == 'complete-collector-component':
                component_boundaries.append({'original_index': original_index,
                    'paper_id': row['paper_id'], 'sentence_id': row['sentence_id'],
                    'physical_source': row['physical_source'], 'english_hash': row['english_hash'],
                    'status': row['status'], 'sense_index': row.get('sense_index'), **boundary})
            token = unicodedata.normalize('NFKC', row['english'][slice(*span)]).casefold()
            owners = [name for name in names if token in ({name} if is_filtered else allowed[name])]
            if len(owners) != 1:
                raise ValueError('candidate target lacks one explicit original component or retained lemma')
            groups[owners[0]].append(row)
    actual_surface_counts = Counter(row['english'][slice(*row['target_range'])].casefold()
                                    for row in raw['occurrences'])
    if dict(actual_surface_counts) != ledger['raw_casefold_counts']:
        raise ValueError('audited original casefold counts differ from actual physical targets')
    edits, component_audits, preview = [], [], page
    for index, (name, panel, old) in enumerate(zip(names, panels, frequencies)):
        raw_frequency = _frequency(original[name], old['corpus_papers'])
        if raw_frequency != old:
            raise ValueError('original component frequency does not match audited raw physical positions')
        new = _frequency(filtered[name], old['corpus_papers'])
        new_panel = _exam_frequency_markup({'exam_frequency': new}) if new != old else panel
        notice = ledger['notice'] if index == 0 else ''
        replacement = new_panel
        if notice:
            replacement += ('<p class="sf-frequency-reconciliation-note" role="note" '
                'style="margin:.35rem 0 .7rem;color:var(--secondary,#47566c);font-size:.8rem;line-height:1.6">'
                + html.escape(notice) + '</p>')
        edit = {'component_index': index, 'headword': name,
            'old_panel_html': panel, 'old_panel_sha256': _sha(panel), 'old_frequency': old,
            'new_panel_html': new_panel, 'new_panel_sha256': _sha(new_panel), 'new_frequency': new,
            'replacement_html': replacement, 'replacement_sha256': _sha(replacement), 'notice': notice}
        component_audits.append(edit)
        if replacement != panel:
            edits.append(edit)
            preview = preview.replace(panel, replacement, 1)
    if sum(item['new_frequency']['occurrences'] for item in component_audits) != record['expected_occurrences']:
        raise ValueError('candidate component frequencies differ from the filtered denominator')
    evidence = {'trust_boundary': 'approved candidate audit plus live source-displays producer',
        'producer_sha256': verified_sources._producer_sha256,
        'producer_record_sha256': _sha(_json(record)),
        'approved_source_manifest': json.loads(verified_sources._source_manifest),
        'candidate_scope_ledger_sha256': ledger['ledger_sha256'],
        'candidate_audit_files': ledger['audit_files'], 'definition_provenance': raw['definition_provenance'],
        'explicit_forms_by_component': forms, 'raw_total': ledger['raw_total'],
        'excluded_total': ledger['excluded_total'], 'candidate_total': ledger['candidate_total'],
        'target_boundary_policy': 'original-collector-full-token-or-complete-hyphen-apostrophe-components.v1',
        'component_target_boundaries': component_boundaries,
        'certified_article_total': None}
    return FrequencyPanelPlan({'schema': SCHEMA, 'preview_only': True,
        'book_id': record['book_id'], 'card_id': record['card_id'], 'word': record['word'],
        'source_page_sha256': _sha(page), 'preview_page_sha256': _sha(preview),
        'component_panels': component_audits, 'panel_edits': edits,
        'old_frequency': _frequency(raw['occurrences'], frequencies[0]['corpus_papers']),
        'new_frequency': _frequency(record['occurrences'], frequencies[0]['corpus_papers']),
        'notice': ledger['notice'], 'source_evidence': evidence,
        'source_evidence_sha256': _sha(_json(evidence))}, _issuer=_ISSUER)


def plan_frequency_panel(page, record, aliases, *, verified_sources, candidate_scope=None):
    """Plan a discrepancy repair, or return ``None`` when all counts agree.

    Pass one raw record returned by ``reread_source_displays``, not the normalized
    sense database representation. The capability is required even for a no-op.
    Each exact physical token must be an original displayed lemma/inflection.
    """
    _require_unpersisted_source(record)
    if type(verified_sources) is not VerifiedSourceDisplays:
        raise ValueError('frequency repair requires the source-displays producer capability')
    verified_sources._require(page, record, aliases)
    if _key(record) in verified_sources._candidate_ledger_hashes and candidate_scope is None:
        raise ValueError('filtered candidate panel requires its issued exclusion audit scope')
    provenance = record.get('definition_provenance', {})
    if (provenance.get('page_sha256') != _sha(page) or
            provenance.get('headword') != record.get('word')):
        raise ValueError('frequency repair page or word differs from the original snapshot')
    panels = list(_fragments(page, 'section', 'exam-frequency', aliases))
    if not panels:
        raise ValueError('frequency repair requires one unique original frequency panel')
    frequencies = [_old_frequency(panel, aliases) for panel in panels]
    if candidate_scope is not None:
        return _scope_panel_plan(page, record, aliases, verified_sources, candidate_scope, panels, frequencies)
    if len(panels) > 1:
        # Compound cards retain independent component panels. An already
        # reconciled total needs no edit; a discrepancy requires a separate
        # component-aware review, never guessed attribution to one headword.
        components = provenance.get('components')
        definitions = list(_fragments(page, 'div', 'dictionary-definition', aliases))
        if (isinstance(components, list) and len(components) == len(panels) == len(definitions) and
                sum(item['occurrences'] for item in frequencies) == record['expected_occurrences']):
            return None
        raise ValueError('frequency repair requires one unique original frequency panel')
    old_panel, old = panels[0], frequencies[0]
    if page.count(old_panel) != 1:
        raise ValueError('frequency repair requires one unique original frequency panel')
    rows = _physical_rows(record)
    counts, contexts = Counter(), {}
    for row in rows:
        identity = (row['paper_id'], _json(row['physical_source']))
        context = (row['english_hash'], _sha(row['translation']))
        if identity in contexts and contexts[identity] != context:
            raise ValueError('one physical source cannot have contradictory sentence text')
        contexts[identity] = context
        counts[identity] += 1
    new = frequency_for_matches(((paper, physical, 0, count)
                                 for (paper, physical), count in counts.items()), old['corpus_papers'])
    if new == old:
        return None
    allowed, forms = _forms(page, record['word'], aliases)
    tokens = []
    source_proofs = json.loads(verified_sources._source_proofs[_key(record)])
    for row, approved in zip(rows, source_proofs):
        start, end = row['target_range']
        token = row['english'][start:end]
        if not any(match.span() == (start, end) for match in _TOKEN.finditer(row['english'])):
            raise ValueError('target range must cover a whole source token')
        if unicodedata.normalize('NFKC', token).casefold() not in allowed:
            raise ValueError('source target is not an explicitly displayed lemma or inflection')
        display = sense_display.validate_display(row.get('display'), row, provenance)
        tokens.append({'paper_id': row['paper_id'], 'sentence_id': row['sentence_id'],
            'physical_source': deepcopy(row['physical_source']), 'target_range': list(row['target_range']),
            'token': token, 'english_hash': row['english_hash'],
            'translation_hash': _sha(row['translation']),
            'source_provenance': deepcopy(row['source_provenance']),
            'display_hash': display['display_hash'],
            'producer_input_manifest_sha256': display['provenance']['input_manifest_sha256'],
            'producer_source_files': deepcopy(display['provenance']['source_files']),
            'approved_canonical_source': approved})
    notice = f"原网页{old['occurrences']}次，按明确词形和原文位置核对为{new['occurrences']}次"
    new_panel = _exam_frequency_markup({'exam_frequency': new})
    replacement = (new_panel + '<p class="sf-frequency-reconciliation-note" role="note" '
        'style="margin:.35rem 0 .7rem;color:var(--secondary,#47566c);font-size:.8rem;line-height:1.6">'
        + html.escape(notice) + '</p>')
    preview = page.replace(old_panel, replacement, 1)
    evidence = {'trust_boundary': 'live source-displays-producer reread; display hashes are not source signatures',
        'producer_sha256': verified_sources._producer_sha256,
        'producer_record_sha256': _sha(_json(record)),
        'approved_source_manifest': json.loads(verified_sources._source_manifest),
        'definition_provenance': deepcopy(provenance), 'explicit_forms': forms,
        'tokens': tokens}
    return FrequencyPanelPlan({'schema': SCHEMA, 'preview_only': True,
        'book_id': record['book_id'], 'card_id': record['card_id'], 'word': record['word'],
        'source_page_sha256': _sha(page), 'preview_page_sha256': _sha(preview),
        'old_panel_html': old_panel, 'old_panel_sha256': _sha(old_panel), 'old_frequency': old,
        'new_panel_html': new_panel, 'new_panel_sha256': _sha(new_panel), 'new_frequency': new,
        'replacement_html': replacement, 'replacement_sha256': _sha(replacement),
        'notice': notice, 'source_evidence': evidence, 'source_evidence_sha256': _sha(_json(evidence))},
        _issuer=_ISSUER)


def _replace_panel(page, plan, *, restore):
    if type(plan) is not FrequencyPanelPlan:
        raise ValueError('frequency patch requires an issued immutable plan')
    data = plan.verification()
    source_hash = data['preview_page_sha256'] if restore else data['source_page_sha256']
    target_hash = data['source_page_sha256'] if restore else data['preview_page_sha256']
    if not isinstance(page, str) or _sha(page) != source_hash:
        raise ValueError('frequency patch page changed or its unique panel is missing')
    edits = data.get('panel_edits', [data])
    result = page
    for edit in reversed(edits) if restore else edits:
        before = edit['replacement_html'] if restore else edit['old_panel_html']
        after = edit['old_panel_html'] if restore else edit['replacement_html']
        if result.count(before) != 1:
            raise ValueError('frequency patch page changed or its unique panel is missing')
        result = result.replace(before, after, 1)
    if _sha(result) != target_hash:
        raise ValueError('frequency patch did not preserve the bound page bytes')
    return result


def apply_frequency_panel(page, plan):
    """Apply only to the exact original page string; perform no writes."""
    return _replace_panel(page, plan, restore=False)


def restore_frequency_panel(page, plan):
    """Restore after other preview-only insertions have first been removed."""
    return _replace_panel(page, plan, restore=True)
