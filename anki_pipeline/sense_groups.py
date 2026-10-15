"""Presentation-only common senses with reversible dictionary membership.

Chinese text alone does not establish semantic equivalence. Automatic grouping
requires equal part of speech, English definition and usage scope as well as
equal displayed text. A source-reviewed certificate can establish equivalence
across differently worded definitions. Original reports and assignments remain
unchanged; a common-sense review points to a group, never an arbitrary member.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sqlite3


SCHEMA = 'exam-sense-groups.v1'
_POS = {'n': 'noun', 'noun': 'noun', 'v': 'verb', 'verb': 'verb',
        'adj': 'adjective', 'adjective': 'adjective', 'adv': 'adverb', 'adverb': 'adverb'}
_SOURCE_KEYS = ('sense_ref', 'source_ref', 'source_headword', 'source_dictionary',
                'source_archive', 'source_version', 'source_name_zh', 'source_url',
                'scope_kind', 'original_chinese', 'english', 'english_definitions',
                'translation_kind', 'translation_label', 'target_lemma')
_PHYSICAL_KEYS = ('physical_source', 'paper_id', 'year', 'sentence_id', 'english',
                  'english_hash', 'translation', 'translation_hash', 'target_range',
                  'source_provenance')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be nonempty text')
    return value


def _normalized(value):
    return re.sub(r'\s+', ' ', value).strip().casefold()


def _pos(value):
    value = _normalized(value).rstrip('.')
    return _POS.get(value, value)


def _supplements(report):
    appended = report.get('definition_provenance', {}).get(
        'supplemental_definitions', {}).get('appended', [])
    if not isinstance(appended, list):
        raise ValueError('supplemental definitions must be an array')
    result = {}
    for item in appended:
        if not isinstance(item, dict) or type(item.get('ordinal')) is not int:
            raise ValueError('supplemental source needs its original ordinal')
        if item['ordinal'] in result:
            raise ValueError('supplemental source ordinal is duplicated')
        result[item['ordinal']] = item
    return result


def _source_context(report, sense, supplements):
    """Keep source identity separate from the semantic/scope equality key."""
    source = supplements.get(sense['ordinal'], {})
    native = source.get('native_definition') or {}
    if not isinstance(native, dict):
        raise ValueError('native sense source must be an object')
    english = sense.get('original_english', sense.get('source_english'))
    if english is None:
        english = source.get('english', native.get('english'))
    if english is not None and not isinstance(english, str):
        raise ValueError('original English definition must be text')
    scope = sense.get('usage_scope')
    if scope is None and source.get('scope_kind') and source.get('source_headword'):
        scope = {'headword': source['source_headword'], 'kind': source['scope_kind'],
                 'grammar': native.get('grammar', []),
                 'header_grammar': native.get('header_grammar', []),
                 'usage_labels': native.get('usage_labels', []),
                 'runon_headword': native.get('runon_headword', ''),
                 'guideword': native.get('guideword', '')}
    if scope is not None and (not isinstance(scope, (str, dict)) or not scope):
        raise ValueError('usage scope must be nonempty text or an object')
    components = report.get('definition_provenance', {}).get('components', [])
    component = next((item for item in components if
        item.get('sense_start', 0) <= sense['ordinal'] <
        item.get('sense_start', 0) + item.get('sense_count', 0)), None)
    provenance = {'definition_source': report.get('definition_source'),
                  'definition_snapshot_id': report.get('definition_snapshot_id'),
                  'ordinal': sense['ordinal']}
    if component is not None:
        provenance['component'] = deepcopy(component)
    if source:
        provenance['supplemental'] = deepcopy({key: source[key] for key in _SOURCE_KEYS if key in source})
        # The full immutable native source remains in definition_provenance.
        provenance['supplemental_ordinal'] = source['ordinal']
    if 'provenance' in sense:
        provenance['sense'] = deepcopy(sense['provenance'])
    definitions = sense.get('english_definitions', source.get('english_definitions', []))
    if not isinstance(definitions, list):
        raise ValueError('original English definitions must be an array')
    return {'original_english': english, 'english_definitions': deepcopy(definitions),
            'usage_scope': deepcopy(scope),
            'provenance': provenance}


def _context_key(context):
    english, scope = context['original_english'], context['usage_scope']
    if not english or scope is None:
        return None
    return _normalized(english), _json(context['english_definitions']), _json(scope)


def _certificate(certificate, senses, contexts):
    if not isinstance(certificate, dict):
        raise ValueError('sense equivalence must be an object')
    ids = certificate.get('member_sense_ids')
    if ids is None and 'member_ordinals' in certificate:
        ordinals = certificate['member_ordinals']
        by_ordinal = {sense['ordinal']: sense for sense in senses}
        if (not isinstance(ordinals, list) or any(type(i) is not int or i not in by_ordinal for i in ordinals)):
            raise ValueError('equivalence member ordinals are invalid')
        ids = [by_ordinal[i]['sense_id'] for i in ordinals]
    by_id = {s['sense_id']: s for s in senses}
    if (not isinstance(ids, list) or len(ids) < 2 or
            any(not isinstance(i, str) or i not in by_id for i in ids) or len(ids) != len(set(ids))):
        raise ValueError('equivalence needs distinct known member senses')
    if len({_pos(by_id[i]['pos']) for i in ids}) != 1 or not _pos(by_id[ids[0]]['pos']):
        raise ValueError('equivalence cannot cross part of speech')
    for key in ('meaning', 'reason', 'review_version'):
        _text(certificate.get(key), f'equivalence {key}')
    scope = certificate.get('usage_scope')
    if not isinstance(scope, (str, dict)) or not scope:
        raise ValueError('equivalence needs a reviewed usage scope')
    evidence = certificate.get('evidence')
    if not isinstance(evidence, list) or not evidence or any(not isinstance(e, dict) or not e for e in evidence):
        raise ValueError('equivalence needs original source evidence')
    available = {_context_key(contexts[i]) for i in ids if _context_key(contexts[i]) is not None}
    if len(available) > 1:
        # Differently worded source definitions need evidence that explicitly
        # addresses every member, rather than a blanket semantic assertion.
        accounted = {e.get('sense_id') for e in evidence}
        if not set(ids).issubset(accounted):
            raise ValueError('equivalence must account for each distinct source context')
    result = deepcopy(certificate)
    result['member_sense_ids'] = ids
    return result


def _candidates(metadata, by_id, label):
    if not isinstance(metadata, dict):
        raise ValueError(f'{label} must be an object')
    ids = metadata.get('candidate_sense_ids')
    if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id for i in ids)
            or len(ids) != len(set(ids))):
        raise ValueError(f'{label} needs distinct known candidate sense IDs')
    _text(metadata.get('reason'), f'{label} reason')
    return ids


def validate_match_metadata(metadata, report, *, common=False):
    """Validate explicit review labels without assigning a dictionary member."""
    by_id = {s['sense_id']: s for s in report['senses']}
    result = deepcopy(metadata)
    _candidates(result, by_id, 'common sense match' if common else 'broad match')
    if common:
        if result.get('method') != 'context-review':
            raise ValueError('common sense match must be a context review')
        _text(result.get('review_version'), 'common sense match review version')
    else:
        result.setdefault('label', '宽泛匹配')
        _text(result['label'], 'broad match label')
    return result


def _physical(row):
    identity = _text(row.get('occurrence_id'), 'physical occurrence identity')
    if type(row.get('year')) is not int:
        raise ValueError('physical occurrence year must be an integer')
    return identity, {key: row[key] for key in _PHYSICAL_KEYS if key in row}


def group_report(report, *, equivalences=None):
    """Return a shallow report copy plus common-sense presentation metadata.

    ``equivalences`` are context/source review certificates, each containing
    member_sense_ids (or member_ordinals), meaning, usage_scope, reason,
    evidence, and review_version. Lexical proposals never create counts.
    A pending ``common_sense_match`` can count once in one certified group;
    a reviewed broad match counts in its original reviewed sense once.
    Original source trees are retained by reference and treated as read-only;
    grouping never changes them. Derived row dictionaries are new objects.
    """
    if equivalences is None:
        equivalences = report.get('sense_group_equivalences', ()) if isinstance(report, dict) else ()
    return _group_report(report, equivalences=equivalences, retain_original=True)


def _group_report(report, *, equivalences, retain_original):
    if not isinstance(report, dict) or not isinstance(report.get('senses'), list):
        raise ValueError('sense grouping requires a report with original senses')
    if type(report.get('total')) is not int or report['total'] < 0:
        raise ValueError('sense grouping needs a nonnegative physical total')
    senses = report['senses']
    by_id, contexts = {}, {}
    supplements = _supplements(report)
    previous_ordinal = -1
    for sense in senses:
        if (not isinstance(sense, dict) or type(sense.get('ordinal')) is not int or
                sense['ordinal'] <= previous_ordinal):
            raise ValueError('sense grouping requires the original global ordinal order')
        previous_ordinal = sense['ordinal']
        identity = _text(sense.get('sense_id'), 'original sense identity')
        if identity in by_id:
            raise ValueError('original sense identity is duplicated')
        if not isinstance(sense.get('pos'), str):
            raise ValueError('original sense part of speech must be text')
        _text(sense.get('text'), 'original sense text')
        if not isinstance(sense.get('occurrences'), list):
            raise ValueError('sense occurrences must be an array')
        if type(sense.get('count')) is not int or sense['count'] != len(sense['occurrences']):
            raise ValueError('original sense count differs from its occurrences')
        by_id[identity] = sense
        contexts[identity] = _source_context(report, sense, supplements)
    parent = {identity: identity for identity in by_id}
    def find(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity
    def merge(ids):
        roots = [find(i) for i in ids]
        for root in roots[1:]:
            parent[root] = roots[0]
    exact, duplicates = defaultdict(list), defaultdict(list)
    for sense in senses:
        identity = sense['sense_id']
        base = (_pos(sense['pos']), _normalized(sense['text']))
        duplicates[base].append(identity)
        context = _context_key(contexts[identity])
        if context is not None and base[0]:
            exact[(*base, *context)].append(identity)
    for ids in exact.values():
        merge(ids)
    certificates = [_certificate(item, senses, contexts) for item in equivalences]
    for item in certificates:
        merge(item['member_sense_ids'])
    members = defaultdict(list)
    for sense in senses:
        members[find(sense['sense_id'])].append(sense)
    groups, group_by_id = [], {}
    for group_members in members.values():
        ids = [sense['sense_id'] for sense in group_members]
        identity = _sha({'schema': SCHEMA, 'book_id': report.get('book_id'),
                         'card_id': report.get('card_id'), 'members': sorted(ids)})
        for member_id in ids:
            group_by_id[member_id] = identity
        group = {'group_id': identity, 'sense_id': identity,
                 'ordinal': group_members[0]['ordinal'], 'pos': group_members[0]['pos'],
                 'text': group_members[0]['text'], 'member_sense_ids': ids,
                 'members': [{**{key: s[key] for key in ('sense_id', 'ordinal', 'pos', 'text', 'count')},
                              **deepcopy(contexts[s['sense_id']])} for s in group_members],
                 'equivalence_reviews': [deepcopy(c) for c in certificates
                                         if set(c['member_sense_ids']).issubset(ids)],
                 'count': 0, 'reviewed_count': 0, 'common_match_count': 0,
                 'deduplicated_count': 0, 'years': [], 'occurrences': []}
        groups.append(group)
    groups_by_id = {group['group_id']: group for group in groups}
    physical, rows_by_group, matches = {}, defaultdict(dict), []
    def take(row, group, original_ids, *, common=False):
        identity, fingerprint = _physical(row)
        if identity in physical and physical[identity] != fingerprint:
            raise ValueError('conflicting physical occurrence identity or source')
        physical[identity] = fingerprint
        previous = rows_by_group[group['group_id']].get(identity)
        if previous is not None:
            previous['original_member_sense_ids'] = sorted(
                set(previous['original_member_sense_ids']).union(original_ids),
                key=lambda i: by_id[i]['ordinal'])
            group['deduplicated_count'] += 1
            return
        copied = dict(row) if retain_original else {
            key: row[key] for key in ('occurrence_id', 'year', 'sentence_id', 'target_range') if key in row}
        copied['original_member_sense_ids'] = list(original_ids)
        copied['sense_group_id'] = group['group_id']
        # The SQL assignment deliberately cannot choose an arbitrary source
        # member for an equivalent group. Expose the resolved semantic state
        # separately so inventories do not mistake that raw ambiguity for an
        # unresolved meaning. The original status and member IDs remain intact.
        copied['original_status'] = row.get('status', 'reviewed')
        copied['semantic_status'] = 'reviewed-common-sense' if common else 'reviewed'
        rows_by_group[group['group_id']][identity] = copied
        group['common_match_count' if common else 'reviewed_count'] += 1
    def broad(row, *, reviewed=False):
        metadata = validate_match_metadata(row['broad_match'], report)
        ids = metadata['candidate_sense_ids']
        if reviewed and row.get('sense_id') not in ids:
            raise ValueError('reviewed broad match must include its original assigned sense')
        matches.append({**metadata, 'occurrence_id': row['occurrence_id'],
                        'kind': 'broad-match', 'counted': reviewed,
                        'candidate_group_ids': list(dict.fromkeys(group_by_id[i] for i in ids))})
    for sense in senses:
        group = groups_by_id[group_by_id[sense['sense_id']]]
        for row in sense['occurrences']:
            if 'sense_id' in row and row['sense_id'] != sense['sense_id']:
                raise ValueError('occurrence belongs to another original sense')
            take(row, group, [sense['sense_id']])
            if 'broad_match' in row:
                broad(row, reviewed=True)
    pending = report.get('pending', [])
    if not isinstance(pending, list):
        raise ValueError('pending occurrences must be an array')
    if type(report.get('pending_count')) is not int or report['pending_count'] != len(pending):
        raise ValueError('original pending count differs from its occurrences')
    common_ids = set()
    pending_ids = set()
    for row in pending:
        identity, fingerprint = _physical(row)
        if identity in physical or identity in pending_ids:
            raise ValueError('physical occurrence is both reviewed and pending')
        pending_ids.add(identity)
        if row.get('common_sense_match') is not None:
            if 'broad_match' in row:
                raise ValueError('pending occurrence cannot have both common and broad match')
            metadata = validate_match_metadata(row['common_sense_match'], report, common=True)
            ids = metadata['candidate_sense_ids']
            candidates = list(dict.fromkeys(group_by_id[i] for i in ids))
            if len(candidates) != 1:
                raise ValueError('common sense match candidates do not share one equivalent group')
            group = groups_by_id[candidates[0]]
            take(row, group, ids, common=True)
            common_ids.add(identity)
            matches.append({**metadata, 'occurrence_id': identity, 'group_id': group['group_id'],
                            'kind': 'reviewed-common-sense', 'counted': True})
        elif 'broad_match' in row:
            broad(row)
        elif isinstance(row.get('matching_proposal'), dict):
            proposal = row['matching_proposal']
            ids = proposal.get('candidate_sense_ids', [])
            if ids and all(i in group_by_id for i in ids):
                candidates = list(dict.fromkeys(group_by_id[i] for i in ids))
                if len(candidates) == 1 and len(ids) > 1:
                    matches.append({'occurrence_id': identity, 'kind': 'common-sense-candidate',
                                    'candidate_sense_ids': deepcopy(ids), 'group_id': candidates[0],
                                    'reason': proposal.get('reason', 'lexical proposal requires context review'),
                                    'counted': False})
    # A physical token can be repeated among equivalent source rows, but cannot
    # increase two distinct common-sense counts.
    assigned_groups = {}
    for group in groups:
        rows = list(rows_by_group[group['group_id']].values())
        for row in rows:
            identity = row['occurrence_id']
            if identity in assigned_groups and assigned_groups[identity] != group['group_id']:
                raise ValueError('physical occurrence is assigned to distinct sense groups')
            assigned_groups[identity] = group['group_id']
        group['occurrences'] = sorted(rows, key=lambda r: (-r['year'], r.get('sentence_id', ''),
                                                          r.get('target_range', []), r['occurrence_id']))
        group['count'] = len(rows)
        years = Counter(row['year'] for row in rows)
        group['years'] = [{'year': year, 'count': years[year]} for year in sorted(years, reverse=True)]
    if len(set(assigned_groups).union(pending_ids)) > report['total']:
        raise ValueError('common sense physical counts exceed the original total')
    proposals = [{'member_sense_ids': ids, 'status': 'needs-source-review',
                  'reason': '相同词性与中文释义尚不足以确认英文语义和用法范围等价'}
                 for ids in duplicates.values() if len(ids) > 1 and
                 len({group_by_id[i] for i in ids}) > 1 and
                 any(_context_key(contexts[i]) is None for i in ids)]
    result = dict(report) if retain_original else {}
    result.update(sense_group_schema=SCHEMA, sense_groups=groups,
                  sense_group_by_id=group_by_id, group_matches=matches,
                  merge_candidates=proposals, group_pending_count=len(pending) - len(common_ids))
    return result


def display_report(report, *, equivalences=None):
    """Use one row per common sense without changing the original denominator.

    The original sense rows remain in ``original_senses``. A pending token is
    removed only when an explicit context review counted it in a common group.
    Member IDs and provenance accompany each displayed row. Call this on the
    complete source report before component slicing; component renderers must
    retain a unique canonical row for a group crossing source components.
    """
    if report.get('sense_group_display') is True:
        if report.get('sense_group_schema') != SCHEMA:
            raise ValueError('unknown common sense display schema')
        if equivalences is None:
            return dict(report)
        report = {**report, 'senses': report['original_senses'],
                  'pending': report['original_pending'],
                  'pending_count': len(report['original_pending'])}
    grouped = group_report(report, equivalences=equivalences)
    resolved = {match['occurrence_id'] for match in grouped['group_matches']
                if match['kind'] == 'reviewed-common-sense' and match['counted']}
    result = dict(grouped)
    result['original_senses'] = grouped['senses']
    result['original_pending'] = grouped['pending']
    result['senses'] = grouped['sense_groups']
    result['pending'] = [row for row in grouped['pending'] if row['occurrence_id'] not in resolved]
    result['pending_count'] = len(result['pending'])
    result['sense_group_display'] = True
    return result


def _payload_report(payload):
    occurrences = payload.get('occurrences', [])
    by_sense = defaultdict(list)
    pending = []
    for row in occurrences:
        if row.get('sense_id') is None:
            pending.append(row)
        else:
            by_sense[row['sense_id']].append(row)
    return {**{key: payload.get(key) for key in ('schema', 'snapshot_id', 'definition_snapshot_id',
                 'word', 'book_id', 'card_id', 'definition_source', 'definition_provenance')},
            'sense_group_equivalences': payload.get('sense_group_equivalences', []),
            'total': payload['expected_occurrences'], 'pending': pending, 'pending_count': len(pending),
            'senses': [{**sense, 'count': len(by_sense[sense['sense_id']]),
                        'occurrences': by_sense[sense['sense_id']]} for sense in payload['senses']]}


def semantic_report(report, *, equivalences=None):
    """Classify every physical token without rewriting SQL assignment status.

    Use this on a complete report for unresolved inventories and status totals.
    A common-sense match is resolved only after ``display_report`` validates
    both the context review and its source-equivalence group. A lexical
    proposal alone remains pending. Raw statuses, candidate source IDs, and
    the reversible display report remain available to callers.
    """
    if report.get('sense_group_display') is True:
        # Revalidate the retained originals rather than accepting cached group
        # matches as new evidence when an inventory receives a display report.
        report = {**report, 'senses': report['original_senses'],
                  'pending': report['original_pending'],
                  'pending_count': len(report['original_pending'])}
        report.pop('sense_group_display')
    display = display_report(report, equivalences=equivalences)
    common = {match['occurrence_id']: match for match in display['group_matches']
              if match['kind'] == 'reviewed-common-sense' and match['counted']}
    states = {}
    for group in display['senses']:
        for row in group['occurrences']:
            identity = row['occurrence_id']
            match = common.get(identity)
            states[identity] = {
                'occurrence_id': identity,
                'original_status': row.get('original_status', row.get('status', 'reviewed')),
                'semantic_status': 'reviewed-common-sense' if match else 'reviewed',
                'counted': True, 'sense_group_id': group['group_id'],
                'original_member_sense_ids': list(row['original_member_sense_ids']),
            }
            if match:
                states[identity]['common_sense_match'] = deepcopy(match)
    for row in display['pending']:
        status = row.get('status')
        if status not in {'ambiguous', 'unmatched'}:
            raise ValueError('unresolved semantic status must remain ambiguous or unmatched')
        states[row['occurrence_id']] = {
            'occurrence_id': row['occurrence_id'], 'original_status': status,
            'semantic_status': status, 'counted': False,
            'original_member_sense_ids': [],
        }
    if len(states) != display['total']:
        raise ValueError('semantic status counts differ from the physical total')
    rows = [states[identity] for identity in sorted(states)]
    return {
        'schema': 'exam-sense-semantic-status.v1',
        **{key: display.get(key) for key in ('snapshot_id', 'book_id', 'card_id', 'word', 'total')},
        'source_status_counts': dict(Counter(row['original_status'] for row in rows)),
        'semantic_status_counts': dict(Counter(row['semantic_status'] for row in rows)),
        'resolved_common_sense_count': len(common),
        'pending_count': display['pending_count'], 'occurrences': rows,
    }


def write_database_proposal(database, output_directory, *, equivalences_by_card=None):
    """Write a complete active-snapshot mapping sidecar using a read-only DB.

    Keys of ``equivalences_by_card`` are (book_id, card_id) tuples. No database
    writes or assignment changes occur; output contains dictionary membership
    and source bindings, while full native source stays in its pinned snapshot.
    """
    database = Path(database).resolve(strict=True)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    mappings_final, proposals_final = output / 'groups.jsonl', output / 'merge-candidates.jsonl'
    mappings, proposals = output / '.groups.jsonl.partial', output / '.merge-candidates.jsonl.partial'
    certificates = equivalences_by_card or {}
    summary = {'schema': SCHEMA, 'database': str(database), 'cards': 0,
               'original_senses': 0, 'groups': 0, 'merged_groups': 0,
               'merge_candidates': 0, 'database_sql_mutations': 0,
               'read_only': 'mode=ro; query_only=ON; BEGIN',
               'active_snapshots_sha256': None, 'files': {}}
    before = database.stat()
    active = hashlib.sha256()
    con = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        query = ('SELECT a.book_id,a.card_id,a.snapshot_id,s.payload FROM active_snapshots a '
                 'JOIN snapshots s ON s.id=a.snapshot_id ORDER BY a.book_id,a.card_id')
        with mappings.open('w', encoding='utf-8') as group_file, proposals.open('w', encoding='utf-8') as candidate_file:
            for book, card, snapshot, text in con.execute(query):
                payload = json.loads(text)
                if (payload.get('snapshot_id'), payload.get('book_id'), payload.get('card_id')) != (snapshot, book, card):
                    raise ValueError('active snapshot payload identity differs from database binding')
                grouped = _group_report(_payload_report(payload),
                    equivalences=certificates.get((book, card), payload.get('sense_group_equivalences', ())),
                    retain_original=False)
                active.update((_json([book, card, snapshot]) + '\n').encode('utf-8'))
                binding = {'book_id': book, 'card_id': card, 'word': payload['word'],
                           'snapshot_id': snapshot, 'definition_snapshot_id': payload.get('definition_snapshot_id'),
                           'definition_provenance_sha256': _sha(payload['definition_provenance'])}
                slim = [{key: value for key, value in group.items() if key not in ('occurrences', 'years')}
                        for group in grouped['sense_groups']]
                group_file.write(_json({**binding, 'sense_groups': slim,
                                        'sense_group_by_id': grouped['sense_group_by_id']}) + '\n')
                for candidate in grouped['merge_candidates']:
                    candidate_file.write(_json({**binding, **candidate}) + '\n')
                summary['cards'] += 1
                summary['original_senses'] += len(payload['senses'])
                summary['groups'] += len(slim)
                summary['merged_groups'] += sum(len(group['member_sense_ids']) > 1 for group in slim)
                summary['merge_candidates'] += len(grouped['merge_candidates'])
        summary['active_snapshots_sha256'] = active.hexdigest()
        summary['database_sql_mutations'] = con.total_changes
    finally:
        con.close()
    after = database.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('source database changed while producing sense group sidecars')
    summary['database_binding'] = {'size': after.st_size, 'mtime_ns': after.st_mtime_ns}
    for path, final in ((mappings, mappings_final), (proposals, proposals_final)):
        summary['files'][final.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                      'bytes': path.stat().st_size}
        path.replace(final)
    receipt = output / '.summary.json.partial'
    receipt.write_text(_json(summary) + '\n', encoding='utf-8')
    receipt.replace(output / 'summary.json')
    return summary
