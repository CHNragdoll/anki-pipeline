"""Pure, source-pinned presentation exclusions issued from approved audits.

The audit's externally supplied digest is authority for the linguistic decision;
its adjacent pinned inventory proves the complete original physical rows. A
fresh capability additionally binds this exact current snapshot and fully
restored Examples string. Neither a serialized old scope nor token spelling
alone grants permission. No files, records, frequencies or databases are changed.
"""
from __future__ import annotations

from copy import deepcopy
from collections import Counter
from dataclasses import dataclass
import json
import hashlib
from pathlib import Path
import re
from weakref import WeakSet

from . import native_example_usage as native
from . import sense_candidate_scope as scopes
from . import sense_display as sd
from . import sense_frequency_reconcile as reconcile


SCHEMA = 'study-native-candidate-exclusions.v1'
LEXICAL_SCHEMA = 'study-native-lexical-presentation-exclusions.v1'
_ISSUER = object()
_ISSUED = WeakSet()


def _need(value, message):
    if not value:
        raise ValueError(message)


@dataclass(frozen=True, eq=False)
class CandidateExclusions:
    """Opaque, immutable, per-input authority; JSON is evidence only."""
    _payload: str
    _sha256: str
    _issuer: object

    def verification(self):
        _need(self in _ISSUED and self._issuer is _ISSUER and
              sd._sha(self._payload) == self._sha256, 'unissued exclusion capability')
        return json.loads(self._payload)


def _audited_rows(binding, raw):
    rows = reconcile._physical_rows(raw)
    _need((raw['book_id'], raw['card_id'], raw['word']) ==
          (binding['book_id'], binding['card_id'], binding['word']) and
          raw['definition_provenance'] == binding['definition_provenance'] and
          len(rows) == binding['raw_total'], 'audited inventory card/definition differs')
    indices, retained = binding['indices'], binding['retained']
    _need(isinstance(indices, list) and isinstance(retained, list) and
          all(type(i) is int for i in indices + retained) and
          len(set(indices)) == len(indices) and len(set(retained)) == len(retained) and
          not set(indices) & set(retained) and set(indices) | set(retained) == set(range(len(rows))) and
          len(retained) == binding['candidate_total'], 'audit does not partition its original inventory')
    evidence = {item['global_index']: item for item in binding['evidence']}
    _need(len(evidence) == len(binding['evidence']) and set(evidence) == set(indices),
          'audit exclusion evidence is missing or duplicated')
    result = []
    for index in indices:
        row, proof = rows[index], evidence[index]
        start, end = row['target_range']
        _need(proof.get('work_id') == binding['work_id'] and
              proof.get('physical_id') == scopes._physical(row) and
              proof.get('raw_english_hash') == row['english_hash'] and
              all(proof.get(key) == row.get(key) for key in
                  ('english', 'translation', 'source', 'source_provenance')) and
              proof.get('actual_token') == row['english'][start:end] and
              row['english'][start:end].casefold() == 'as' and
              any(match.span() == (start, end) for match in reconcile._TOKEN.finditer(row['english'])) and
              proof.get('classification') == 'different_lemma_as' and
              proof.get('canonical_sentence_exact_match') is True and
              proof.get('same_original_article_headword') is False and proof.get('a_noun_plural') is False and
              isinstance(proof.get('reason'), str) and bool(proof['reason'].strip()) and
              row.get('status') in {'pending', 'unmatched'} and row.get('sense_index') is None and
              row.get('reviewed_sense_id') is None and row.get('assignment_context_hash') is None,
              'approved exclusion differs from its exact physical/source evidence')
        row = deepcopy(row)
        sd._digest(row['source_provenance'].get('reviewedContentHash'), 'audited source review SHA')
        row['occurrence_id'] = native._identity(row)
        result.append(row)
    return result


def issue_exclusions(examples, current_prepared, *, audit_path, expected_audit_sha256,
                     supplement_path=None, expected_supplement_sha256=None, aliases=None,
                     source_display_records=None, lexical_presentation_rule=None):
    """Issue authority from caller-approved audit pins and one pinned inventory.

    ``current_prepared`` is the already filtered, sealed current record. The
    caller restores all lazy Examples before this call; this is not an AS
    decoder. The existing primary/supplement helpers resolve exact book/card
    mappings, including independently ordered inventories. No word/year rule is
    inferred and no semantic totals are certified by this presentation pass.
    """
    _need(isinstance(examples, str), 'fully restored Examples must be a string')
    current = native._rows(current_prepared)
    aliases = {} if aliases is None else deepcopy(aliases)
    _need(type(aliases) is dict and all(type(k) is str and type(v) is str for k, v in aliases.items()),
          'native class aliases must be an exact string map')
    sd._digest(expected_audit_sha256, 'approved audit SHA')
    primary, approval = scopes._read_approved(audit_path, expected_audit_sha256)
    binding = scopes._primary_bindings(primary)
    key = (current_prepared['book_id'], current_prepared['card_id'])
    approvals = [approval]
    if supplement_path is not None or expected_supplement_sha256 is not None:
        sd._digest(expected_supplement_sha256, 'approved supplement SHA')
        supplement, extra = scopes._read_approved(supplement_path, expected_supplement_sha256)
        other = scopes._supplement_binding(supplement, primary, expected_audit_sha256)
        approvals.append(extra)
        if key == (other['book_id'], other['card_id']):
            binding = other
    _need(key == (binding['book_id'], binding['card_id']) and
          current_prepared.get('word') == binding['word'], 'approved audit does not cover this exact card')
    raw, inventory = scopes._inventory(audit_path, binding['locator'], binding['inventory_sha'],
                                      primary['source_snapshot']['inventory_manifest_sha256'])
    excluded = _audited_rows(binding, raw)
    _need(not set(current) & {row['occurrence_id'] for row in excluded},
          'certified excluded physical row is still present in the current record')
    bridges, source_files = _source_display_bridges(current_prepared, excluded, source_display_records)
    lexical = _lexical_rule(lexical_presentation_rule, current, excluded)
    payload = {'schema': SCHEMA, 'book_id': key[0], 'card_id': key[1],
               'current_snapshot_id': current_prepared['snapshot_id'],
               'current_record_sha256': sd._sha(sd._json(current_prepared)),
               'examples_sha256': sd._sha(examples), 'aliases': aliases,
               'audit_files': approvals, 'inventory': inventory, 'excluded': excluded,
               'source_display_bridges': bridges, 'source_display_files': source_files,
               'lexical_presentation_rule': lexical}
    text = sd._json(payload)
    capability = CandidateExclusions(text, sd._sha(text), _ISSUER)
    _ISSUED.add(capability)
    return capability


def _lexical_rule(rule, current, excluded):
    """Bind an explicit presentation decision, independently of physical proof.

    This capability can only deny forms already classified as other lemmas in
    the approved audit, when every retained physical token has an explicitly
    allowed form. It does not claim that a derived native view is physically
    matched to any particular occurrence or change the semantic record.
    """
    if rule is None:
        return None
    _need(type(rule) is dict and set(rule) ==
          {'schema', 'denied_forms', 'retained_forms', 'reason'} and
          rule['schema'] == LEXICAL_SCHEMA and type(rule['reason']) is str and
          bool(rule['reason'].strip()), 'lexical presentation rule needs an explicit approved decision')
    for key in ('denied_forms', 'retained_forms'):
        values = rule[key]
        _need(type(values) is list and bool(values) and
              all(type(value) is str and bool(value) and value == value.casefold() and
                  value == value.strip() for value in values) and len(values) == len(set(values)),
              'lexical presentation forms must be unique exact casefold strings')
    denied, retained = set(rule['denied_forms']), set(rule['retained_forms'])
    audited = {row['english'][slice(*row['target_range'])].casefold() for row in excluded}
    counts = Counter(row['english'][slice(*row['target_range'])].casefold() for row in current.values())
    _need(denied <= audited and not denied & retained and bool(counts) and set(counts) <= retained,
          'lexical presentation rule differs from the audited exclusions or retained physical tokens')
    return {**deepcopy(rule), 'retained_token_counts': dict(sorted(counts.items())),
            'audited_denied_forms': sorted(audited)}


def _source_display_bridges(current, excluded, pins):
    """Validate externally pinned formal owners; never invent display offsets."""
    pins = [] if pins is None else pins
    _need(type(pins) is list, 'formal source display records require an explicit pin list')
    originals = {row['occurrence_id']: row for row in excluded}
    surfaces = {row['english'][slice(*row['target_range'])].casefold() for row in excluded}
    bridges, verified_files, records = {}, {}, set()
    for pin in pins:
        _need(type(pin) is dict and set(pin) == {'file', 'sha256'}, 'formal display record requires file/SHA')
        sd._digest(pin['sha256'], 'formal display record SHA')
        record, descriptor = scopes._read_approved(pin['file'], pin['sha256'])
        _need(pin['sha256'] not in records, 'formal display record is duplicated')
        records.add(pin['sha256'])
        rows = native._rows(record)
        _need(record.get('book_id') == current['book_id'] and record.get('card_id') != current['card_id'] and
              record.get('word') in surfaces, 'formal display owner is outside the audited other lemma')
        for identity in originals.keys() & rows.keys():
            row, original = rows[identity], originals[identity]
            display = row.get('display')
            if not display or display.get('provenance', {}).get('derivation') == 'original':
                continue
            _need(native._physical_equal(original, row) and row.get('source') == original.get('source'),
                  'formal display physical/source context differs from the audited token')
            display = sd.validate_display(display, row, record['definition_provenance'], ownership_context=record)
            _need(display['english'][slice(*display['target_range'])] ==
                  original['english'][slice(*original['target_range'])], 'formal display moved to a different token')
            files = display['provenance']['source_files']
            _need(bool(files), 'derived formal display needs its authenticated source files')
            for name, digest in files.items():
                _need(Path(name).is_absolute(), 'formal display source file must be absolute')
                if name in verified_files:
                    _need(verified_files[name]['sha256'] == digest, 'formal display source pins conflict')
                else:
                    raw = Path(name).read_bytes()
                    _need(hashlib.sha256(raw).hexdigest() == digest, 'formal display source file SHA differs')
                    verified_files[name] = {'path': name, 'sha256': digest, 'bytes': len(raw)}
            _need(identity not in bridges, 'physical exclusion has duplicate formal display owners')
            bridges[identity] = {'record': descriptor, 'record_snapshot_id': record['snapshot_id'],
                'owner': {key: record[key] for key in ('book_id', 'card_id', 'word')},
                'row_sha256': sd._sha(sd._json(row)), 'display_sha256': sd._sha(sd._json(display)),
                'definition_provenance_sha256': sd._sha(sd._json(record['definition_provenance'])),
                'display': display}
    return bridges, [verified_files[name] for name in sorted(verified_files)]


def _bridge_target(physical, bridge, view):
    """Intersect an issued formal display with one unchanged native source."""
    display, jump = bridge['display'], view['jump']
    if (jump is None or jump['sentence_id'] not in sd._source_ids(physical) or
            jump['english_hash'] != physical['english_hash'] or
            jump['reviewed_content_hash'] != physical['source_provenance']['reviewedContentHash'] or
            physical['target_range'] not in jump['target_ranges'] or
            any(view[key] != display[key] for key in ('english', 'translation', 'source', 'cloze_answers')) or
            display['target_range'] not in view['target_ranges']):
        return None
    target = tuple(display['target_range'])
    _need(view['english'][slice(*target)] == physical['english'][slice(*physical['target_range'])],
          'native bridge target differs from the certified physical token')
    return target


def _anchors(row):
    return set(sd._source_ids(row))


def _probe_snapshot(record, rows):
    # The common updater decides source/range coverage, not archive ownership.
    # Its re-rendered markup is never published. Keep complete original archive
    # bytes in the caller's LI instead of asking this probe to re-emit them.
    data = {'book_id': record['book_id'], 'card_id': record['card_id'], 'occurrences': deepcopy(rows)}
    for row in data['occurrences']:
        row.pop('ownership_history', None)
        # The audit certifies the original physical token, not a newly inferred
        # location in a derived completion/question display.
        row.pop('display', None)
    data['snapshot_id'] = sd._sha(sd._json(data))
    return data


def _unmark(original, aliases, removed):
    tree = native._Offsets(original, aliases)
    owners = [node for node in tree.root.children if node.tag == 'li' and 'example-card' in node.classes]
    _need(len(owners) == 1, 'exclusion needs one exact native owner')
    en = native._current_descendant(owners[0], 'example-text')
    _need(en.closed is not None, 'native English has no closing boundary')
    marks, edits = {}, []
    for node in en.walk():
        if 'target-word' not in node.classes or native._historical(node):
            continue
        _need(node.closed is not None and node.end is not None, 'target wrapper has no exact boundary')
        prefix = sd._text_and_ranges(sd._Tree(original[en.opened:node.start]).root)[0]
        text = sd._text_and_ranges(sd._Tree(original[node.opened:node.closed]).root)[0]
        span = (len(prefix), len(prefix) + len(text))
        _need(span not in marks, 'target range has ambiguous nested wrappers')
        marks[span] = node
    for span in removed:
        node = marks.get(span)
        _need(node is not None and node.tag == 'mark' and node.classes == {'target-word'} and
              set(node.attrs) == {'class'} and re.fullmatch(
                  r'''<mark\s+class=(?:"[^"]*"|'[^']*')\s*>''', original[node.start:node.opened], re.I),
              'certified target wrapper has an unsupported boundary')
        edits.extend(((node.start, node.opened, ''), (node.closed, node.end, '')))
    return native._apply(original, edits)[0]


def apply_exclusions(examples, current_prepared, capability):
    """Remove only certified native marks; all other markup stays byte exact.

    The common native updater authorizes each affected LI's removal/ranges. For
    mixed or unbound targets, only its proven target wrappers are unwrapped;
    chunks, translations, source links, media, scripts and archives are retained
    as original bytes. All noncertified targets are conservatively unbound;
    current rows bind the capability but never supply derived-as inference.
    Optional externally authenticated formal other-lemma displays contribute
    only their already validated offsets at exact native source intersections.
    Unsupported wrappers fail closed. Numbering remains the
    responsibility of the existing shared presentation pipeline.
    """
    _need(type(capability) is CandidateExclusions, 'an issued exclusion capability is required')
    proof = capability.verification()
    _need(isinstance(examples, str) and sd._sha(examples) == proof['examples_sha256'] and
          sd._sha(sd._json(current_prepared)) == proof['current_record_sha256'],
          'Examples or current record changed after capability issuance')
    native._rows(current_prepared)
    aliases, excluded = proof['aliases'], proof['excluded']
    bridges = proof['source_display_bridges']
    evidence = {row['occurrence_id']: row for row in excluded}
    excluded_by_source, certified_anchors = {}, set()
    for row in excluded:
        for anchor in _anchors(row):
            key = (anchor, row['english_hash'], row['source_provenance']['reviewedContentHash'])
            excluded_by_source.setdefault(key, []).append(row)
            certified_anchors.add(anchor)
    revisions, bindings, consumed, groups, owners = {}, [], set(), {}, []
    stats = {'native_examples': 0, 'updated_examples': 0, 'removed_examples': 0,
             'removed_target_marks': 0, 'unbound_targets': 0, 'unbound_native_sources': 0,
             'certified_exclusions': len(excluded), 'formal_display_bridges': len(bridges),
             'lexical_removed_target_marks': 0, 'lexical_removed_examples': 0}
    for node in native._Offsets(examples, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or native._historical(node):
            continue
        stats['native_examples'] += 1
        owners.append(node)
        jumps = [part for part in node.walk() if 'sentence-jump' in part.classes and not native._historical(part)]
        if not jumps:
            continue
        _need(len(jumps) == 1, 'native candidate has ambiguous source jumps')
        jump = sd._decode_jump(jumps[0])
        if jump is None or jump['sentence_id'] not in certified_anchors:
            continue
        key = (jump['sentence_id'], jump['english_hash'], jump['reviewed_content_hash'])
        if key not in excluded_by_source:
            stats['unbound_native_sources'] += 1
            continue
        _need(node.closed is not None and node.end is not None, 'native candidate has no closing boundary')
        original = examples[node.start:node.end]
        groups.setdefault(key, []).append((node, original))
    for key, members in groups.items():
        # Only these certified physical rows can be removed. Other targets,
        # including retained article marks, remain unbound and cannot be
        # removed with the whole LI. No retained derived display is inferred.
        old = _probe_snapshot(current_prepared, excluded_by_source[key])
        new = _probe_snapshot(current_prepared, [])
        context = ''.join(original for _, original in members)
        result = native.update_native_examples(context, old, new, aliases=aliases)
        stats['unbound_targets'] += result['stats']['unbound_targets']
        by_markup = {}
        for binding in result['inverse']['bindings']:
            markup_key = binding['source_markup_sha256']
            _need(markup_key not in by_markup or by_markup[markup_key] == binding,
                  'identical native source markup has conflicting target proofs')
            by_markup[markup_key] = binding
        for node, original in members:
            binding = deepcopy(by_markup.get(sd._sha(original)) or
                               {'source_markup_sha256': sd._sha(original), 'targets': []})
            before = native._current_native_example(original, aliases)
            covered = {tuple(target['display_target_range']) for target in binding['targets']}
            for row in excluded_by_source[key]:
                bridge = bridges.get(row['occurrence_id'])
                if bridge is None:
                    continue
                target = _bridge_target(row, bridge, before)
                if target is None or target in covered:
                    continue
                binding['targets'].append({'occurrence_id': row['occurrence_id'],
                    'old_row_sha256': sd._sha(sd._json(row)), 'new_row_sha256': None,
                    'display_target_range': list(target),
                    'approved_source_display': {name: value for name, value in bridge.items() if name != 'display'}})
                covered.add(target)
                stats['unbound_targets'] -= 1
            covered = {tuple(target['display_target_range']) for target in binding['targets']}
            surviving = {tuple(target['display_target_range']) for target in binding['targets']
                         if target['new_row_sha256'] is not None}
            removed = covered - surviving
            if not removed:
                continue
            for target in binding['targets']:
                if tuple(target['display_target_range']) in removed:
                    _need(target['occurrence_id'] in evidence, 'updater removed an uncertified occurrence')
                    consumed.add(target['occurrence_id'])
            unbound = set(map(tuple, before['target_ranges'])) - covered
            if not surviving and not unbound:
                revised = ''
                stats['removed_examples'] += 1
            else:
                revised = _unmark(original, aliases, removed)
                after = native._current_native_example(revised, aliases)
                _need(all(before[key] == after[key] for key in before if key != 'target_ranges') and
                      sorted(map(tuple, after['target_ranges'])) ==
                      sorted(span for span in map(tuple, before['target_ranges']) if span not in removed),
                      'candidate exclusion changed source text or an unauthorized target')
                stats['updated_examples'] += 1
            revisions[node.start] = (node.start, node.end, revised)
            stats['removed_target_marks'] += len(removed)
            bindings.append(binding)
    lexical = proof['lexical_presentation_rule']
    if lexical is not None:
        denied = set(lexical['denied_forms'])
        rule_sha = sd._sha(sd._json(lexical))
        for node in owners:
            _need(node.closed is not None and node.end is not None, 'native lexical owner has no closing boundary')
            original = examples[node.start:node.end]
            revised = revisions.get(node.start, (None, None, original))[2]
            if not revised:
                continue
            before = native._current_native_example(revised, aliases)
            removed = {tuple(span) for span in before['target_ranges']
                       if before['english'][slice(*span)].casefold() in denied}
            if not removed:
                continue
            lexical_targets = [{'display_target_range': list(span),
                                'text': before['english'][slice(*span)], 'rule_sha256': rule_sha}
                               for span in sorted(removed)]
            if removed == set(map(tuple, before['target_ranges'])):
                replacement = ''
                stats['lexical_removed_examples'] += 1
            else:
                replacement = _unmark(revised, aliases, removed)
                after = native._current_native_example(replacement, aliases)
                _need(all(before[key] == after[key] for key in before if key != 'target_ranges') and
                      sorted(map(tuple, after['target_ranges'])) ==
                      sorted(span for span in map(tuple, before['target_ranges']) if span not in removed),
                      'lexical presentation changed source text or a retained target')
            revisions[node.start] = (node.start, node.end, replacement)
            stats['lexical_removed_target_marks'] += len(removed)
            stats['removed_target_marks'] += len(removed)
            bindings.append({'source_markup_sha256': sd._sha(original), 'targets': [],
                             'lexical_presentation_targets': lexical_targets})
    edits = list(revisions.values())
    stats['updated_examples'] = sum(bool(replacement) for _, _, replacement in edits)
    stats['removed_examples'] = sum(not replacement for _, _, replacement in edits)
    updated, spans = native._apply(examples, edits)
    stats['consumed_exclusions'] = len(consumed)
    stats['unconsumed_exclusions'] = len(evidence.keys() - consumed)
    inverse = {'schema': native.SCHEMA, 'operation': SCHEMA,
               'source_page_sha256': sd._sha(examples), 'updated_page_sha256': sd._sha(updated),
               'capability_sha256': capability._sha256, 'current_snapshot_id': current_prepared['snapshot_id'],
               'bindings': bindings, 'spans': spans}
    inverse['inverse_sha256'] = sd._sha(sd._json(inverse))
    _need(restore_original(updated, inverse) == examples, 'candidate inverse did not restore exact input bytes')
    return {'page': updated, 'inverse': inverse, 'stats': stats}


def restore_original(examples, inverse):
    """Restore the complete original Examples, including removed whole rows."""
    _need(isinstance(inverse, dict) and inverse.get('operation') == SCHEMA,
          'not a native candidate exclusion inverse')
    return native.restore_original(examples, inverse)
