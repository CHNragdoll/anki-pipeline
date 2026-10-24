"""Reviewed, atomic ownership transfers of existing physical occurrences.

The API requires an existing dictionary-backed destination in every affected
book. It does not infer lexical forms, create a missing entry, or rewrite raw
sources. The complete former sentence and audit travel with the sentence.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
import hashlib
import html
import re

from . import sense_display as sd
from . import sense_frequency as sf
from . import study_catalog as c
from . import study_catalog_revision as revision
from .example_numbering import renumber_examples
from .native_example_usage import (_Offsets, _view, update_native_examples,
                                   _current_native_example, _current_descendant,
                                   _historical as _native_historical)


def _scope(db, source_word, target_word, physical_id):
    sources = db.execute(
        'select distinct a.book_id,a.source_card_id,a.record_id from analyses a '
        'join words w on w.id=a.word_id join analysis_occurrences x '
        'on x.book_id=a.book_id and x.source_card_id=a.source_card_id '
        'where w.surface=%s and x.original_occurrence_id=%s order by a.book_id,a.source_card_id',
        (source_word, physical_id)).fetchall()
    if not sources:
        raise ValueError('reviewed source physical word is absent')
    pairs = []
    for book, card, record_id in sources:
        targets = db.execute(
            'select a.source_card_id,a.record_id from analyses a '
            'join words w on w.id=a.word_id where a.book_id=%s and w.surface=%s',
            (book, target_word)).fetchall()
        if len(targets) != 1:
            raise ValueError('every affected book needs one existing dictionary-backed target entry')
        pairs.append(((book, card, record_id), (book, *targets[0])))
    if len({source[0] for source, _ in pairs}) != len(pairs):
        raise ValueError('source ownership is not unique within a book')
    owners = {r[0] for r in db.execute(
        'select distinct w.surface from analyses a join words w on w.id=a.word_id '
        'join analysis_occurrences x on x.book_id=a.book_id '
        'and x.source_card_id=a.source_card_id where x.original_occurrence_id=%s', (physical_id,))}
    if owners - {source_word, target_word}:
        raise ValueError('physical occurrence has another active owner outside the reviewed transfer')
    affected = {(book, card): rid for pair in pairs for book, card, rid in pair}
    return pairs, affected


def _mapped_notes(db, affected, pairs):
    """Mapped books must expose a target as well as the departing source."""
    notes = [(book, row[0]) for book, card in affected
             for row in db.execute('select note_id from notes where book_id=%s and source_card_id=%s',
                                   (book, card))]
    targets = {(row[0], row[1]) for _, row in pairs}
    sources = {(row[0], row[1]) for row, _ in pairs}
    for book, manifest_id in db.execute(
            'select b.book_id,s.manifest_id from book_sources b join sources s '
            "on s.id=b.source_id where s.kind='book-map'"):
        refs = c.get_json(db, manifest_id).get('analysis_references', {})
        identities = {(ref['book_id'], ref['source_card_id']) for ref in refs.values()}
        if identities & sources and not identities & targets:
            raise ValueError('mapped book contains the source but lacks the reviewed target entry')
        for card, ref in refs.items():
            if (ref['book_id'], ref['source_card_id']) in affected:
                notes.extend((book, row[0]) for row in db.execute(
                    'select note_id from notes where book_id=%s and source_card_id=%s', (book, card)))
    return notes


def _reseal(draft):
    """A changed membership gets a new active scope; old ledgers stay archived."""
    draft = deepcopy(draft)
    draft.pop('candidate_scope', None)
    draft.pop('candidate_source_record', None)
    draft['expected_occurrences'] = len(draft['occurrences'])
    indices = {sense['sense_id']: sense['ordinal'] for sense in draft['senses']}
    for row in draft['occurrences']:
        row['sense_index'] = indices.get(row.get('sense_id'))
        if row['status'] == 'reviewed':
            row.update(sf.seal_reviewed_assignment(draft, row))
    return sf.prepare_record(draft)


def _move_row(source_record, target_record, physical_id, ordinal, reason, evidence):
    original = next(row for row in source_record['occurrences'] if row['occurrence_id'] == physical_id)
    previous = next((row for row in target_record['occurrences'] if row['occurrence_id'] == physical_id), None)
    if previous is not None:
        exact = ('paper_id', 'physical_source', 'english', 'translation', 'target_range')
        if any(original[key] != previous[key] for key in exact):
            raise ValueError('existing target occurrence disagrees with the original physical source')
    moved = deepcopy(previous or original)
    # Old ownership certificates bind their original destination. Preserve them
    # inside the complete former row, rather than relabeling their destination.
    moved.pop('ownership_history', None)
    review = deepcopy(moved.get('semantic_review', {}))
    history = review.setdefault('catalog_ownership_transfers', [])
    proof = {'schema': 'study-reviewed-ownership.v1',
        'source_book_id': source_record['book_id'], 'source_card_id': source_record['card_id'],
        'source_word': source_record['word'], 'source_snapshot': source_record['snapshot_id'],
        'source_definition_provenance': deepcopy(source_record['definition_provenance']),
        'source_record': deepcopy(source_record),
        'source_record_sha256': hashlib.sha256(c.canonical(source_record).encode()).hexdigest(),
        'target_before_record': deepcopy(target_record),
        'target_before_record_sha256': hashlib.sha256(c.canonical(target_record).encode()).hexdigest(),
        'source_row': deepcopy(original), 'target_previous_row': deepcopy(previous),
        'target_word': target_record['word'], 'target_book_id': target_record['book_id'],
        'target_card_id': target_record['card_id'], 'physical_id': physical_id,
        'target_definition_snapshot_id': target_record['definition_snapshot_id'],
        'target_dictionary_sense': deepcopy(target_record['senses'][ordinal]),
        'reason': reason, 'evidence': deepcopy(evidence)}
    proof['proof_sha256'] = hashlib.sha256(c.canonical(proof).encode()).hexdigest()
    history.append(proof)
    # A prior dictionary explanation describes the old assignment; the exact
    # copy above remains available as history rather than a current assertion.
    if previous is None:
        review.pop('dictionary_explanation', None)
    review['occurrence_id'] = physical_id
    moved['semantic_review'] = review
    moved.update(status='reviewed', sense_index=ordinal,
                 sense_id=target_record['senses'][ordinal]['sense_id'],
                 reason=reason, method='shared-catalog-reviewed-ownership.v1')
    for key in ('broad_match', 'common_sense_match', 'matching_proposal', 'pending_category'):
        moved.pop(key, None)
    return moved, original, previous


def validate_grouping_origin(db, origin, current):
    """Replay one committed transfer from exact immutable catalog records.

    An approved display is optional for an original, exactly bound native
    example. Replaying the existing writer validates that same supported path
    without relaxing any of the display or native-source validators.
    """
    if (not isinstance(origin, dict) or not isinstance(current, dict)
            or any(origin.get(key) != current.get(key) for key in ('book_id', 'card_id', 'word'))):
        raise ValueError('native grouping origin belongs to another semantic owner')
    occurrences = origin.get('occurrences')
    if not isinstance(occurrences, list):
        raise ValueError('native grouping origin lacks its complete occurrences')
    for row in occurrences:
        if not isinstance(row, dict) or not isinstance(row.get('semantic_review') or {}, dict):
            raise ValueError('native grouping origin has invalid reviewed rows')
        history = (row.get('semantic_review') or {}).get('catalog_ownership_transfers')
        if not history:
            continue
        if not isinstance(history, list):
            raise ValueError('native grouping origin has invalid transfer history')
        proof = history[-1]
        if not isinstance(proof, dict) or proof.get('schema') != 'study-reviewed-ownership.v1':
            raise ValueError('native grouping origin lacks its complete reviewed transfer')
        if any(not isinstance(proof.get(key),str) or not re.fullmatch('[0-9a-f]{64}',proof[key])
               for key in ('source_record_sha256','target_before_record_sha256')):
            raise ValueError('native grouping origin lacks immutable source record identities')
        source = c.get_json(db, proof.get('source_record_sha256'))
        target = c.get_json(db, proof.get('target_before_record_sha256'))
        if (not isinstance(source,dict) or not isinstance(target,dict)
                or source != proof.get('source_record') or target != proof.get('target_before_record')):
            raise ValueError('native grouping origin differs from immutable source records')
        if (source.get('book_id') != target.get('book_id') or target.get('book_id') != origin.get('book_id')
                or any(record.get('snapshot_id') != sf._sha(sf._json({key: value for key, value in record.items() if key != 'snapshot_id'}))
                       for record in (source, target))):
            raise ValueError('native grouping origin has stale or mismatched source snapshots')
        if (not isinstance(proof.get('reason'), str) or not proof['reason'].strip()
                or not isinstance(proof.get('evidence'), dict) or not proof['evidence']):
            raise ValueError('native grouping origin lacks explicit reviewed evidence')
        if source['word'] == target['word']:
            raise ValueError('native grouping origin does not transfer lexical ownership')
        chosen = proof.get('target_dictionary_sense') or {}
        ordinal = chosen.get('ordinal')
        if (type(ordinal) is not int or not 0 <= ordinal < len(target['senses'])
                or target['senses'][ordinal] != chosen):
            raise ValueError('native grouping origin has no exact dictionary-backed destination')
        moved, _, _ = _move_row(source, target, proof.get('physical_id'), ordinal,
                               proof.get('reason'), proof.get('evidence'))
        replay = deepcopy(target)
        replay['occurrences'] = [entry for entry in replay['occurrences']
                                 if entry['occurrence_id'] != moved['occurrence_id']] + [moved]
        if _reseal(replay) == origin:
            return
    raise ValueError('native grouping origin is not an exact reviewed transfer result')


def _audit_markup(source_record, target_record, original, previous, reason, evidence, source_article):
    value = {'schema': 'study-reviewed-ownership.v1', 'source_word': source_record['word'],
             'source_book_id': source_record['book_id'], 'source_card_id': source_record['card_id'],
             'source_record_sha256': hashlib.sha256(c.canonical(source_record).encode()).hexdigest(),
             'original_record': source_record, 'target_previous_row': previous,
             'target_word': target_record['word'], 'target_card_id': target_record['card_id'],
             'physical_id': original['occurrence_id'], 'reason': reason, 'evidence': evidence}
    return ('<details class="sf-catalog-revision" data-study-ownership="v1">'
            '<summary>本句归属说明</summary><p>原词条：' + html.escape(source_record['word'])
            + '；实际词条：' + html.escape(target_record['word']) + '</p><p>转归依据：'
            + html.escape(reason) + '</p><details><summary>完整原句与审核说明</summary>'
            + _archived_article(source_article) + '</details><details><summary>完整原记录与转归证据</summary>'
            '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + html.escape(c.canonical(value)) + '</pre></details></details>')


def _archived_article(markup):
    edits = []
    for node in _Offsets(markup, {}).root.walk():
        if 'sf-example' not in node.classes:
            continue
        opening = markup[node.start:node.opened]
        match = re.search(r'\bclass\s*=\s*([\'\"])(.*?)\1', opening, re.S)
        if match is None:
            raise ValueError('historical article has no exact class attribute')
        classes = ' '.join('sf-archived-example' if item == 'sf-example' else item
                           for item in match.group(2).split())
        edits.append((node.start + match.start(2), node.start + match.end(2), classes))
    rendered = revision._edits(markup, edits)
    return (rendered + '<details><summary>完整原始内容存档</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + html.escape(markup) + '</pre></details>')


def _frequency_header(raw, before, after, aliases=None):
    """Recompute existing header slots from the same active physical rows."""
    from .exam_frequency import frequency_stars
    from .exam_usage import occurrence_usage, validate_usage
    from .packaging import _exam_frequency_markup
    panels = [node for node in _Offsets(raw, aliases or {}).root.walk()
              if node.tag == 'section' and 'exam-frequency' in node.classes
              and not revision._historical(node)]
    edits = []
    for node in panels:
        if any('sf-report' in child.classes for child in node.walk()):
            raise ValueError('frequency header overlaps current semantic report content')
        try:
            old_count = int(node.attrs['data-occurrences'])
            corpus = int(node.attrs['data-corpus-papers'])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError('frequency header lacks exact current corpus counts') from error
        if old_count != before['expected_occurrences']:
            raise ValueError('compound frequency header needs an explicit component ownership mapping')
        rows = after['occurrences']
        count = len(rows)
        papers = len({row['paper_id'] for row in rows})
        sentences = len({(row['paper_id'], c.canonical(row['physical_source'])) for row in rows})
        roles, choices = Counter(), Counter()
        for row in rows:
            usage = validate_usage(row['usage']) if row.get('usage') else occurrence_usage(row)
            roles[usage['source_role']] += 1
            if usage['source_role'] == 'reading_option' and usage['reading_candidate_correctness'] != 'not_applicable':
                choices[usage['reading_candidate_correctness']] += 1
        frequency = {'schema': 'kaoyan-frequency.v1', 'rule': 'occurrence-bands.v1',
            'occurrences': count, 'matched_sentences': sentences, 'paper_count': papers,
            'corpus_papers': corpus, 'stars': frequency_stars(count)}
        breakdown = {'schema': 'kaoyan-frequency-breakdown.v1', 'occurrences': count,
                     'source_role': dict(roles), 'reading_candidate_correctness': dict(choices)}
        markup = _exam_frequency_markup({'exam_frequency': frequency, 'exam_frequency_breakdown': breakdown})
        edits.append((node.start, node.end, markup))
    return revision._edits(raw, edits)


def _new_article(article, row, audit):
    nodes = [node for node in revision._nodes(article, 'sf-reason')
             if revision._text(article[node.opened:node.closed]).startswith('义项依据：')]
    if len(nodes) != 1:
        raise ValueError('transferred source article lacks one exact current reason')
    edits = [(nodes[0].opened, nodes[0].closed, '义项依据：' + html.escape(row['reason']))]
    for node in revision._nodes(article, 'sf-dictionary-explanation'):
        edits.append((node.start, node.end, ''))
    for node in revision._nodes(article, 'sf-reason'):
        if revision._text(article[node.opened:node.closed]).startswith('上下文仅能确认广义：'):
            edits.append((node.start, node.end, ''))
    article = revision._edits(article, edits)
    close = article.rfind('</article>')
    if close < 0:
        raise ValueError('transferred article has no complete boundary')
    return article[:close] + audit + article[close:]


def _prepared(record):
    # Native changes are limited to physical membership. Existing audit markup
    # is left byte-for-byte in the li, not regenerated by historical builders.
    result = {key: deepcopy(record[key]) for key in ('book_id', 'card_id', 'occurrences')}
    for row in result['occurrences']:
        row.pop('ownership_history', None)
    result['snapshot_id'] = sd._sha(sd._json(result))
    return result


def _native_nodes(raw, aliases):
    result = []
    for node in _Offsets(raw, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or _native_historical(node):
            continue
        article = raw[node.start:node.end]
        result.append((node, _current_native_example(article, aliases), article))
    return result


def _native_match(row, native):
    if native['jump'] is None:
        return None
    if native['jump']['sentence_id'] not in sd._source_ids(row) and not row.get('display'):
        return None
    approved = sd.refresh_derived_chunks(row)['display'] if row.get('display') else None
    pinned = (approved or {}).get('provenance', {}).get('native_jump')
    if (pinned is not None and native['jump'] != pinned
            and native['jump']['sentence_id'] == pinned['sentence_id']
            and native['jump']['english_hash'] == pinned['english_hash']
            and native['jump']['reviewed_content_hash'] == pinned['reviewed_content_hash']
            and row['target_range'] not in native['jump']['target_ranges']
            and not any(start < row['target_range'][1] and row['target_range'][0] < end
                        for start, end in native['jump']['target_ranges'])):
        # Another exact physical token in the same source paragraph is not an
        # alias for this occurrence and must not invalidate its separate owner.
        return None
    return _view(row, native, approved)


def _native_membership(raw, before, after, aliases):
    result = update_native_examples(raw, _prepared(before), _prepared(after), aliases=aliases)
    restore = []
    for span in result['inverse']['spans']:
        original = span['original']
        # The legacy helper owns regenerating its old ownership wrapper. This
        # operation instead carries exact history markup forward unchanged.
        roots = _Offsets(original, aliases).root.children if original else []
        if (len(roots) == 1 and roots[0].attrs.get('data-native-ownership-history')
                and span['range'][0] == span['range'][1]):
            restore.append((*span['range'], original))
    result['page'] = revision._edits(result['page'], restore)
    return result


def _native_transfer(source_raw, target_raw, source_before, source_after, target_before,
                     moved, audit, aliases):
    source_nodes = _native_nodes(source_raw, aliases)
    from .study_catalog_native_groups import _safe_sentence_nodes
    for node, _, _ in source_nodes:
        _safe_sentence_nodes(_current_descendant(node,'example-text'), _current_descendant(node,'example-translation'))
    matches = [(node, native, markup) for node, native, markup in source_nodes
               if (view := _native_match(moved, native)) is not None
               and view['target_range'] in native['target_ranges']]
    if len(matches) != 1:
        raise ValueError('transferred sentence needs one exactly source-bound native example')
    node, native, markup = matches[0]
    updated = _native_membership(source_raw, source_before, source_after, aliases)
    if updated['stats']['removed_target_marks'] < 1:
        raise ValueError('source native example did not remove the transferred target')
    only = deepcopy(source_before)
    only['occurrences'] = [row for row in only['occurrences'] if row['occurrence_id'] == moved['occurrence_id']]
    incoming = _native_membership(markup, source_before, only, aliases)
    if incoming['stats']['unbound_targets']:
        raise ValueError('transferred native sentence has unbound sibling targets')
    incoming_markup = incoming['page']
    target_nodes = _native_nodes(target_raw, aliases)
    same = [(part, view, raw) for part, view, raw in target_nodes
            if (matched := _native_match(moved, view)) is not None
            and matched['target_range'] in view['target_ranges']]
    if len(same) > 1:
        raise ValueError('target native example repeats the same physical occurrence')
    if same:
        part, _, existing = same[0]
        closing = existing.rfind('</li>')
        target_raw = revision._edits(target_raw, [(part.start, part.end, existing[:closing] + audit + existing[closing:])])
    else:
        closing = incoming_markup.rfind('</li>')
        incoming_markup = incoming_markup[:closing] + audit + incoming_markup[closing:]
        lists = [part for part in _Offsets(target_raw, aliases).root.walk() if part.tag == 'ol'
                 and not _native_historical(part)]
        if not lists:
            roots = _Offsets(target_raw, aliases).root.children
            if target_raw.strip() and (not roots or any(
                    part.tag != 'li' or 'example-card' not in part.classes for part in roots)):
                raise ValueError('target Examples has no exact native list insertion boundary')
            # Native note fields commonly contain list items only; their one
            # shared card template owns the surrounding ol element.
            target_raw += incoming_markup
        elif len(lists) != 1 or lists[0].closed is None:
            raise ValueError('target Examples needs one exact native example list')
        else:
            target_raw = revision._edits(target_raw, [(lists[0].closed, lists[0].closed, incoming_markup)])
    return renumber_examples(updated['page'], aliases), renumber_examples(target_raw, aliases)


def transfer_occurrence(value, *, source_word, target_word, physical_id, sense_id,
                        reason, evidence, expected, backups, aliases_by_book=None):
    """Move an explicitly reviewed physical token across all existing books.

    ``sense_id`` is the shared dictionary_senses ID. ``expected`` maps every
    affected source AND destination ``book/card`` to its current record SHA.
    No partial transfer is committed if any book cannot preserve its content.
    """
    for label, text in (('source word', source_word), ('target word', target_word),
                        ('physical identity', physical_id), ('dictionary sense', sense_id)):
        if not isinstance(text, str) or not text.strip() or '\x00' in text:
            raise ValueError(label + ' must be nonempty exact text')
    if not isinstance(expected, dict) or not expected or any(
            not isinstance(key, str) or not isinstance(seal, str) for key, seal in expected.items()):
        raise ValueError('complete expected ownership scope is required')
    if aliases_by_book is not None and (not isinstance(aliases_by_book, dict) or any(
            not isinstance(book, str) or not isinstance(aliases, dict) or any(
                not isinstance(key, str) or not isinstance(name, str) for key, name in aliases.items())
            for book, aliases in aliases_by_book.items())):
        raise ValueError('native class aliases must map each book to exact string aliases')
    if source_word == target_word:
        raise ValueError('ownership transfer requires different exact entries')
    if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, dict) or not evidence:
        raise ValueError('explicit reviewed reason and nonempty supporting evidence are required')
    c.canonical(evidence)
    saved = c.backup(value, backups)
    with c.connect(value) as db, c.transaction(db):
        from .study_catalog_export import project_book, project_note, require_ready
        from .study_catalog_normalize import import_analysis
        from .study_catalog_anki import bump_content_mods
        from .study_catalog_content import repartition_definition, source_articles
        c.write_lock(db)
        require_ready(db)
        pairs, affected = _scope(db, source_word, target_word, physical_id)
        actual = {book + '/' + card: rid for (book, card), rid in affected.items()}
        if actual != expected:
            raise ValueError('stale or incomplete cross-book ownership scope')
        note_versions = _mapped_notes(db, affected, pairs)
        projections = revision.registry(db)
        changes = []
        for source_ref, target_ref in pairs:
            source_before, target_before = [c.get_json(db, ref[2]) for ref in (source_ref, target_ref)]
            book = source_ref[0]
            for ref in (source_ref, target_ref):
                row = db.execute('select record_id from analyses where book_id=%s and source_card_id=%s for update', ref[:2]).fetchone()
                if row is None or row[0] != ref[2]:
                    raise ValueError('active ownership analysis changed during transfer')
            senses = db.execute('select ordinal from analysis_senses where book_id=%s '
                                'and source_card_id=%s and sense_id=%s', (*target_ref[:2], sense_id)).fetchall()
            if len(senses) != 1:
                raise ValueError('reviewed dictionary sense is not unique in every destination')
            ordinal = senses[0][0]
            moved, original, previous = _move_row(source_before, target_before, physical_id, ordinal, reason, evidence)
            source_after = deepcopy(source_before)
            source_after['occurrences'] = [row for row in source_after['occurrences'] if row['occurrence_id'] != physical_id]
            source_after = _reseal(source_after)
            target_after = deepcopy(target_before)
            target_after['occurrences'] = [row for row in target_after['occurrences'] if row['occurrence_id'] != physical_id] + [moved]
            target_after = _reseal(target_after)
            if {row['occurrence_id'] for record in (source_before, target_before) for row in record['occurrences']} != {
                    row['occurrence_id'] for record in (source_after, target_after) for row in record['occurrences']}:
                raise ValueError('ownership transfer changed the original physical universe')
            model = project_book(db, book)
            fields = []
            for ref in (source_ref, target_ref):
                notes = db.execute('select note_id from notes where book_id=%s and source_card_id=%s', ref[:2]).fetchall()
                if len(notes) != 1:
                    raise ValueError('ownership record needs one exact source note')
                note = project_note(db, model, notes[0][0], apply_runtime=False)
                fields.append(dict(zip(note['field_names'], note['fields'])))
            if any(not {'Definition', 'Examples'}.issubset(item) for item in fields):
                raise ValueError('ownership presentation needs exact Definition and Examples fields')
            departing_articles = source_articles(fields[0]['Definition'], source_before)
            target_articles = source_articles(fields[1]['Definition'], target_before)
            original_article = departing_articles.pop(physical_id)
            audit = _audit_markup(source_before, target_before, original, previous, reason, evidence, original_article)
            target_article = target_articles.get(physical_id, original_article)
            if previous is not None:
                audit += ('<details class="sf-catalog-revision"><summary>目标句合并前完整内容</summary>'
                          + _archived_article(target_article) + '</details>')
            moved_row = next(row for row in target_after['occurrences'] if row['occurrence_id'] == physical_id)
            target_articles[physical_id] = _new_article(target_article, moved_row, audit)
            aliases = (aliases_by_book or {}).get(book, {})
            definitions = [_frequency_header(repartition_definition(item['Definition'], before, after, articles), before, after, aliases)
                           for item, before, after, articles in zip(fields,
                               (source_before, target_before), (source_after, target_after),
                               (departing_articles, target_articles))]
            examples = _native_transfer(fields[0]['Examples'], fields[1]['Examples'], source_before,
                source_after, target_before, moved_row, audit, aliases)
            for ref, after, definition, example in zip((source_ref, target_ref),
                    (source_after, target_after), definitions, examples):
                db.execute('delete from analysis_occurrences where book_id=%s and source_card_id=%s', ref[:2])
                db.execute('delete from analysis_senses where book_id=%s and source_card_id=%s', ref[:2])
                db.execute('delete from analyses where book_id=%s and source_card_id=%s', ref[:2])
                import_analysis(db, after)
                after_id = c.put_json(db, after)
                prior = projections.get(c.identity(*ref[:2]), {})
                projections[c.identity(*ref[:2])] = {**prior,'record_id': after_id,'native_aliases':aliases,'fields': {**prior.get('fields',{}),
                    'Definition': c.put_object(db, definition.encode()), 'Examples': c.put_object(db, example.encode())}}
                if ref[:2] == target_ref[:2]:
                    projections[c.identity(*ref[:2])]['native_grouping_origin_record_id'] = after_id
                changes.append({'book_id': ref[0], 'source_card_id': ref[1], 'before': ref[2], 'after': after_id})
        db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
                   (revision.KEY, c.canonical(projections)))
        # Reads use the same source references for every mapped book. Grouping
        # stays a derived host view; failures roll back all provisional facts,
        # histories and fields before any native version is advanced.
        revision.preflight_display_projections(db, note_versions)
        bump_content_mods(db, note_versions)
        c.event(db, 'transfer-reviewed-ownership', {'source_word': source_word, 'target_word': target_word,
            'physical_id': physical_id, 'sense_id': sense_id, 'reason': reason, 'evidence': evidence, 'changes': changes})
    return {'changes': changes, 'backup': str(saved), 'physical_universe_changed': False}
