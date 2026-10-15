"""Source-pinned, byte-invertible changes to existing native exam examples.

This presentation pass neither counts occurrences nor changes their review.
It accepts immutable prepared rows, reuses approved display chunks, and edits
only native example content. Unbound examples remain intact and are reported.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from weakref import WeakSet

from . import sense_display as sd
from .exam_usage import candidate_markup, occurrence_markup, occurrence_usage
from .packaging import (_annotate_sentence_chunks, _chunk_translation,
                        _example_chunk_ranges, _highlight_example)

SCHEMA = 'native-example-usage-inverse.v1'
_PHYSICAL = ('paper_id', 'sentence_id', 'english', 'english_hash', 'translation',
             'physical_source', 'target_range', 'source_provenance', 'alignment')
_ALIAS_TOKEN = object()
_VALIDATED_ALIASES = WeakSet()
_REVIEWED_ALIAS = 'kaoyan:2015-01:q-45-1:A:new:3'
_REVIEWED_CANONICAL = 'kaoyan:2015-01:p:b-12-1:3'


@dataclass(frozen=True)
class ValidatedSourceAliases:
    """Opaque immutable input snapshot produced only by load_source_aliases."""
    _payload: str
    _payload_sha256: str
    _file_sha256: str
    _token: object


def _sealed(value, field):
    data = deepcopy(value)
    claimed = data.pop(field, None)
    if claimed != sd._sha(sd._json(data)):
        raise ValueError('reviewed source alias ' + field + ' is stale')


def _load_source_aliases(pin):
    """Read one pinned alias ledger and verify its complete reviewed proof.

    Pass the returned immutable snapshot to multiple card calls. A plain dict
    of allegedly prevalidated entries never bypasses this verification.
    """
    from .codex_exam_index import _expected_sentences
    from .sentence_insertion import _GAP, _replace_gap
    from .chunk_projection import project_reviewed_chunks
    if isinstance(pin, ValidatedSourceAliases):
        if (pin not in _VALIDATED_ALIASES or pin._token is not _ALIAS_TOKEN or
                sd._sha(pin._payload) != pin._payload_sha256):
            raise ValueError('unvalidated or altered source alias snapshot')
        return pin
    if not isinstance(pin, dict) or set(pin) != {'file', 'sha256'}:
        raise ValueError('source_aliases requires an exact file/sha256 pin or validated snapshot')
    raw = Path(pin['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != sd._digest(pin['sha256'], 'source alias file SHA'):
        raise ValueError('reviewed source alias ledger file hash is stale')
    ledger = json.loads(raw)
    if ledger.get('schema') != 'native-reviewed-jump-alias-ledger.v1':
        raise ValueError('unsupported reviewed source alias ledger')
    _sealed(ledger, 'ledger_sha256')
    entries = ledger.get('entries')
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError('reviewed source alias ledger must bind its one authorized alias')
    entry = entries[0]
    _sealed(entry, 'entry_sha256')
    if (entry.get('alias_sentence_id') != _REVIEWED_ALIAS or
            entry.get('canonical_sentence_id') != _REVIEWED_CANONICAL or
            (entry.get('book_id'), entry.get('card_id'), entry.get('word')) != (
                'redbook2027', '761dddf2d5aa11495f624c8bdb41fe583bf604f07026152d8f93ac94f90e2854', 'train') or
            entry.get('physical_source_mutation_allowed') is not False or
            entry.get('frequency_change_allowed') is not False):
        raise ValueError('unsupported or unsafe reviewed source alias scope')
    files = {}
    for name, source_pin in ledger['source_files'].items():
        source_raw = Path(source_pin['file']).read_bytes()
        if (len(source_raw) != source_pin['bytes'] or
                hashlib.sha256(source_raw).hexdigest() != source_pin['sha256']):
            raise ValueError('reviewed source alias source byte hash is stale: ' + name)
        files[name] = source_raw
    values = {name: json.loads(files[name]) for name in (
        'index', 'inputs', 'translations', 'reviews', 'index_manifest', 'input_manifest', 'structured_source')}
    review, pins = values['reviews'], ledger['source_files']
    if (review.get('approved') is not True or review.get('issues') != [] or
            review['inputHash'] != pins['inputs']['sha256'] or
            review['translationHash'] != pins['translations']['sha256']):
        raise ValueError('reviewed source alias review/input/translation binding is stale')
    manifest = values['index_manifest']
    manifest_row = next(row for row in manifest['papers'] if row['paperId'] == 'kaoyan:2015-01')
    if manifest['inputManifestHash'] != pins['input_manifest']['sha256']:
        raise ValueError('reviewed source alias input inventory binding is stale')
    for field, name in (('inputHash', 'inputs'), ('translationHash', 'translations'),
                        ('reviewHash', 'reviews'), ('indexHash', 'index')):
        if manifest_row[field] != pins[name]['sha256']:
            raise ValueError('reviewed source alias index manifest binding is stale')
    expected, _, _ = _expected_sentences(values['inputs'], values['translations'])
    if expected != values['index']['sentences']:
        raise ValueError('reviewed source alias index differs from approved source reconstruction')
    by_id = {row['id']: row for row in expected}
    alias, canonical = by_id[_REVIEWED_ALIAS], by_id[_REVIEWED_CANONICAL]
    if (alias != entry['source_alias_index_row'] or canonical != entry['canonical_index_row'] or
            alias['context'].get('coverageStatus') != 'covered_by_paragraph' or
            alias['context'].get('translationRef') != canonical['paragraphId'] or
            alias['sourceBlockIds'] != canonical['sourceBlockIds'] or
            alias['sourceBlockIds'] != entry['source_block_ids']):
        raise ValueError('reviewed source alias declared paragraph/block binding is stale')
    prefix = entry['prefix_displacement']
    if (prefix != {'printed_prefix': 'A) ', 'codepoints': 3,
            'canonical_sentence_range': [canonical['start'], canonical['end']],
            'alias_sentence_range': [alias['start'], alias['end']]} or
            canonical['sourceEnglish'] != 'A) ' + alias['sourceEnglish'] or
            [canonical['start'] - 3, canonical['end'] - 3] != [alias['start'], alias['end']] or
            any(canonical[name] != alias[name] for name in (
                'english', 'englishHash', 'translationZh', 'translationHash', 'reviewedContentHash', 'alignments'))):
        raise ValueError('reviewed source alias prefix/range/chunk proof is stale')
    paper = values['structured_source']
    question = next(row for row in paper['questions'] if row['id'] == 'q-45-1')
    option = next(row for row in question['options'] if row['label'].rstrip('.') == 'A')
    block = next(row for row in paper['blocks'] if row['id'] == 'b-12-1')
    if (question['answer']['status'] != 'explicit' or question['answer']['value'] != 'A' or
            question['answer']['externalSource']['answerToken'] != '45-A' or
            option['text'] != alias['sourceEnglish'] or block['text'] != canonical['sourceEnglish']):
        raise ValueError('reviewed source alias structured option/answer proof is stale')
    rows = sorted([row for row in expected if row['paragraphId'] == alias['paragraphId']], key=lambda row: row['start'])
    stem = by_id['kaoyan:2015-01:p:b-11-8:1']
    derivation = entry['derivation']
    if (derivation['option_index_rows'] != rows or derivation['stem_index_row'] != stem or
            derivation['answer'] != question['answer'] or derivation['option'] != option):
        raise ValueError('reviewed source alias derivation sources are stale')
    english, blank, inserted = _replace_gap(stem['english'], next(_GAP.finditer(stem['english'])), option['text'], english=True)
    chinese, cn_blank, cn_inserted = _replace_gap(stem['translationZh'], next(_GAP.finditer(stem['translationZh'])),
        ''.join(row['translationZh'] for row in rows), english=False)
    physical_target = sd._span(entry['physical_target_range'], canonical['english'], 'reviewed alias physical target')
    target = [inserted[0] + alias['start'] + value for value in physical_target]
    answers = [{'start': inserted[0], 'end': inserted[1], 'number': 45, 'word': option['text']}]
    sources = [{'english': row['english'], 'translation': row['translationZh'], 'alignment': {
        'schema': 'codex-sentence-alignment.v1', 'englishHash': row['englishHash'],
        'translationHash': row['translationHash'], 'alignments': row['alignments']}} for row in [*rows, stem]]
    expected_view = {'english': english, 'translation': chinese, 'target_range': target,
        'cloze_answers': answers, 'alignment_sources': sources,
        'alignment': project_reviewed_chunks(english, chinese, sources, sentence_fallback=True)}
    native = entry['native_binding']
    if (entry['approved_display'] != expected_view or native['display_target_range'] != target or
            native['english_hash'] != sd._sha(english) or native['translation_hash'] != sd._sha(chinese) or
            native['cloze_answers'] != answers or
            native['jump']['sentence_id'] != alias['id'] or native['jump']['english_hash'] != alias['englishHash'] or
            native['jump']['reviewed_content_hash'] != alias['reviewedContentHash'] or
            native['jump']['target_ranges'] != [physical_target] or
            any(derivation[key] != value for key, value in (
                ('blank_range', blank), ('inserted_range', inserted),
                ('chinese_blank_range', cn_blank), ('chinese_inserted_range', cn_inserted)))):
        raise ValueError('reviewed source alias approved display/span reconstruction is stale')
    payload = sd._json(ledger)
    snapshot = ValidatedSourceAliases(payload, sd._sha(payload), pin['sha256'], _ALIAS_TOKEN)
    _VALIDATED_ALIASES.add(snapshot)
    return snapshot


def load_source_aliases(pin):
    """Validate an exact file/sha256 pin once; reuse its immutable snapshot."""
    try:
        return _load_source_aliases(pin)
    except (KeyError, TypeError, StopIteration, OSError, UnicodeError) as error:
        raise ValueError('malformed reviewed source alias proof') from error


def _source_alias_match(snapshot, prepared, evidence, original, native):
    if snapshot is None:
        return None
    entry = json.loads(snapshot._payload)['entries'][0]
    if any(prepared.get(key) != entry[key] for key in ('book_id', 'card_id', 'word')):
        return None
    if native['jump']['sentence_id'] != entry['alias_sentence_id']:
        return None
    row = evidence.get(entry['physical_occurrence_id'])
    if (row is None or prepared['snapshot_id'] != entry['physical_snapshot_id'] or
            sd._sha(sd._json(row)) != entry['physical_row_sha256'] or
            row['sentence_id'] != entry['canonical_sentence_id'] or
            row['target_range'] != entry['physical_target_range']):
        raise ValueError('reviewed source alias physical row/snapshot binding is stale')
    bound, view = entry['native_binding'], deepcopy(entry['approved_display'])
    if (sd._sha(original) != bound['source_markup_sha256'] or native['jump'] != bound['jump'] or
            native['english'] != view['english'] or native['translation'] != view['translation'] or
            native['cloze_answers'] != view['cloze_answers'] or native['source'] != bound['source_label'] or
            native['target_ranges'] != [view['target_range']]):
        raise ValueError('reviewed source alias native markup/jump/text binding is stale')
    view['source_alias_entry_sha256'] = entry['entry_sha256']
    view['native_match_origin'] = 'option'
    view['derivation_payload'] = {'questionId': entry['derivation']['question_id'],
        'candidateOptionLabel': 'A', 'isCorrectCandidate': True}
    return entry['physical_occurrence_id'], row, view


class _Element:
    def __init__(self, tag, attrs, start, opened, parent, aliases):
        self.tag, self.attrs = tag, dict(attrs)
        self.start, self.opened, self.closed, self.end = start, opened, None, None
        self.parent, self.children = parent, []
        self.classes = {aliases.get(value, value) for value in self.attrs.get('class', '').split()}

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def descendant(self, name):
        found = [node for node in self.walk() if name in node.classes]
        if len(found) != 1:
            raise ValueError('native example needs one exact ' + name + ' element')
        return found[0]


def _historical(node):
    from .example_numbering import _history_marker
    while node is not None:
        if _history_marker(node):
            return True
        node=node.parent
    return False


def _current_descendant(node, name):
    found=[part for part in node.walk() if name in part.classes and not _historical(part)]
    if len(found)!=1:
        raise ValueError('native example needs one exact current '+name+' element')
    return found[0]


def _current_native_example(raw, aliases):
    """Read the current view without interpreting embedded immutable archives."""
    edits=[]
    for node in _Offsets(raw,aliases).root.walk():
        if _historical(node) and not _historical(node.parent):
            edits.append((node.start,node.end,''))
    current=_apply(raw,edits)[0] if edits else raw
    examples=sd._native_examples(current,aliases)
    if len(examples)!=1:
        raise ValueError('native example needs one exact current source row')
    return examples[0]


class _Offsets(HTMLParser):
    """Read positions without serializing or normalizing the original HTML."""
    def __init__(self, page, aliases):
        super().__init__(convert_charrefs=True)
        self.page, self.aliases = page, aliases
        self.lines = [0]
        self.lines.extend(index + 1 for index, char in enumerate(page) if char == '\n')
        self.root = _Element('', [], 0, 0, None, aliases)
        self.stack = [self.root]
        self.feed(page)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        start = self.position()
        node = _Element(tag, attrs, start, start + len(self.get_starttag_text()), self.stack[-1], self.aliases)
        self.stack[-1].children.append(node)
        if tag in sd._Tree._VOID:
            node.closed = node.end = node.opened
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            node = self.stack.pop()
            node.closed = node.end = node.opened

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                node = self.stack[index]
                node.closed = self.position()
                end = self.page.find('>', node.closed)
                if end < 0:
                    raise ValueError('unterminated native HTML closing tag')
                node.end = end + 1
                del self.stack[index:]
                break


def _identity(row):
    if (not isinstance(row.get('english'), str) or not isinstance(row.get('translation'), str)
            or row.get('english_hash') != sd._sha(row['english'])):
        raise ValueError('native physical source English hash is stale')
    sd._span(row.get('target_range'), row['english'], 'native physical target')
    if ('translation_hash' in row and row['translation_hash'] != sd._sha(row['translation'])):
        raise ValueError('native physical source translation hash is stale')
    expected = sd._sha(sd._json([row['paper_id'], row['physical_source'], row['target_range']]))
    if row.get('occurrence_id', expected) != expected:
        raise ValueError('native physical occurrence identity is stale')
    return expected


def _rows(prepared):
    if not isinstance(prepared, dict):
        raise ValueError('native update requires a prepared snapshot')
    data = deepcopy(prepared)
    claimed = data.pop('snapshot_id', None)
    if claimed != sd._sha(sd._json(data)):
        raise ValueError('native prepared snapshot hash is stale')
    result = {}
    for row in data.get('occurrences', []):
        identity = _identity(row)
        if identity in result:
            raise ValueError('native snapshot repeats a physical occurrence')
        result[identity] = row
    return result


def _excluded(prepared):
    """Old scoped exclusions are evidence, never additional counted rows."""
    containers = [prepared.get('candidate_scope', {}), prepared.get('exam_usage_policy', {})]
    containers.append(prepared.get('exam_usage_policy', {}).get('inherited_candidate_scope', {}))
    for container in containers:
        for item in container.get('excluded', []):
            row = item.get('occurrence')
            if not isinstance(row, dict):
                raise ValueError('native exclusion lacks its exact original row')
            pin = item.get('occurrence_sha256')
            if pin is not None and pin != sd._sha(sd._json(row)):
                raise ValueError('native excluded row hash is stale')
            yield row


def _physical_equal(old, new):
    return all(old.get(key) == new.get(key) for key in _PHYSICAL)


def _jump_source(jump, row):
    if jump['sentence_id'] not in sd._source_ids(row):
        return False
    provenance = row['source_provenance']
    if (jump['english_hash'] != row['english_hash'] or
            jump['reviewed_content_hash'] != provenance.get('reviewedContentHash')):
        raise ValueError('native source hash binding is stale')
    return row['target_range'] in jump['target_ranges']


def _approved_anchor(jump, row, display):
    pinned = display['provenance'].get('native_jump')
    if pinned is not None:
        if jump['sentence_id'] == pinned['sentence_id'] and jump != pinned:
            raise ValueError('native source jump binding differs from its approved display')
        return jump == pinned
    if _jump_source(jump, row):
        return True
    derived = display.get('derivation_payload') or {}
    refs = [ref for key in ('stemSentenceRefs', 'optionSentenceRefs') for ref in derived.get(key, [])
            if ref['sentenceId'] == jump['sentence_id']]
    for ref in refs:
        if (ref.get('englishHash') == jump['english_hash'] and
                ref.get('reviewedContentHash') == jump['reviewed_content_hash']):
            return True
    return False


def _native_display_targets(row, display, ranges):
    """Replay stored approved coordinate transforms; never search the text."""
    kind = display['provenance']['derivation']
    if kind == 'original':
        return ranges
    targets = []
    for span in ranges:
        sd._span(span, row['english'], 'native sibling physical target')
        english, translation, target, answers = sd._approved_derived_view(
            {**row, 'target_range': span}, display['derivation_payload'], kind)
        if (english != display['english'] or translation != display['translation']
                or answers != display['cloze_answers']):
            raise ValueError('native sibling differs from its approved display transform')
        targets.append(target)
    return targets


def _same_packed_native_source(jump, pinned):
    """Only the packed target-range field may differ between source siblings."""
    actual = jump['native_jump'].split('|')
    expected = pinned['native_jump'].split('|')
    return (len(actual) in {6, 7} and len(actual) == len(expected)
            and actual[:5] == expected[:5] and actual[6:] == expected[6:])


def _other_approved_native_target(row, native, display, native_by_jump):
    """Skip a different marked target only with an exact owner counterpart.

    Compound source pages can contain separate native examples for the same
    sentence. Their jumps are deliberately distinct. This does not relax the
    pinned jump check for the owner's actual target. Derived coordinates use
    the existing, validated display transform and the exact original ranges.
    """
    if not display:
        return False
    if native['english'] != display['english'] or native['translation'] != display['translation']:
        return False
    pinned = display['provenance'].get('native_jump')
    jump = native['jump']
    if pinned is None or jump is None or jump == pinned or jump['sentence_id'] != pinned['sentence_id']:
        return False
    target = display['target_range']
    ranges = jump['target_ranges']
    physical = row['target_range']
    if ranges == pinned['target_ranges'] or any(start < physical[1] and physical[0] < end for start, end in ranges):
        return False
    counterpart = native_by_jump.get(sd._json(pinned), [])
    projected = _native_display_targets(row, display, ranges)
    pinned_targets = _native_display_targets(row, display, pinned['target_ranges'])
    original = display['provenance']['derivation'] == 'original'
    valid = (ranges and projected and all(span in native['target_ranges'] for span in projected)
        and (not original or native['target_ranges'] == projected)
        and all(not(start < target[1] and target[0] < end) for start, end in native['target_ranges'])
        and jump['sentence_id'] in sd._source_ids(row)
        and jump['english_hash'] == pinned['english_hash'] == row['english_hash']
        and jump['reviewed_content_hash'] == pinned['reviewed_content_hash'] == row['source_provenance'].get('reviewedContentHash')
        and _same_packed_native_source(jump, pinned)
        and native['english'] == display['english']
        and native['translation'] == display['translation']
        and native['cloze_answers'] == display['cloze_answers']
        and physical in pinned['target_ranges'] and target in pinned_targets
        and any(item['english'] == display['english']
                and item['translation'] == display['translation']
                and item['cloze_answers'] == display['cloze_answers']
                and all(span in item['target_ranges'] for span in pinned_targets)
                and (not original or item['target_ranges'] == pinned_targets) for item in counterpart))
    if not valid:
        raise ValueError('native source sibling lacks its exact approved owner counterpart')
    return True


def _view(row, native, approved=None):
    jump = native['jump']
    display = row.get('display')
    if display is not None:
        view = approved
        if (native['english'] == view['english'] and native['translation'] == view['translation']
                and _approved_anchor(jump, row, view)):
            if native['cloze_answers'] != view['cloze_answers']:
                raise ValueError('native cloze underlines differ from the approved display')
            return view
    if (_jump_source(jump, row) and native['english'] == row['english']
            and native['translation'] == row['translation']):
        return {**row, 'cloze_answers': native['cloze_answers']}
    return None


def _preferred_native_context_owner(row, native, display, native_by_jump):
    """Keep an unmarked stem occurrence in its exact original native owner."""
    if (not display or native_by_jump is None
            or native['jump']['sentence_id'] in sd._source_ids(row)):
        return False
    pinned = display['provenance'].get('native_jump')
    if pinned is None or row['target_range'] not in pinned['target_ranges']:
        return False
    projected = _native_display_targets(row, display, pinned['target_ranges'])
    if display['target_range'] not in projected:
        return False
    original = display['provenance']['derivation'] == 'original'
    for counterpart in native_by_jump.get(sd._json(pinned), []):
        if (counterpart['english'] == display['english']
                and counterpart['translation'] == display['translation']
                and counterpart['cloze_answers'] == display['cloze_answers']
                and all(span in counterpart['target_ranges'] for span in projected)
                and (not original or counterpart['target_ranges'] == projected)
                and _view(row, counterpart, display) is not None):
            return True
    return False


def _context_views(matches, evidence, native, *, native_by_jump=None, approved=None):
    """Project other physical marks through the same approved candidate refs.

    Stem occurrences can have a different preferred display in their stored
    row. The candidate's reviewed source refs still provide exact coordinates;
    spelling similarities or searches for a repeated word never provide them.
    """
    from .exam_library import _context_stem_targets
    from .option_context import context_target_ranges
    known = {identity for identity, _, _ in matches}
    additions = []
    for _, _, view in matches:
        derived = view.get('derivation_payload') or {}
        if not all(key in derived for key in ('originalQuestionEnglish', 'questionEnglish',
                                              'completedEnglish', 'stemSentenceRefs', 'optionSentenceRefs')):
            continue
        for key in ('stemSentenceRefs', 'optionSentenceRefs'):
            for ref in derived[key]:
                for identity, row in evidence.items():
                    if identity in known or ref['sentenceId'] not in sd._source_ids(row):
                        continue
                    if (ref.get('englishHash') != row['english_hash'] or
                            ref.get('english') != row['english'] or
                            ref.get('translationHash') != sd._sha(row['translation']) or
                            ref.get('translationZh') != row['translation'] or
                            ref.get('reviewedContentHash') != row['source_provenance'].get('reviewedContentHash')):
                        raise ValueError('native candidate source reference binding is stale')
                    sentence = {'id': ref['sentenceId'], 'english': row['english']}
                    if key == 'stemSentenceRefs':
                        single_ref_context = {**derived, 'stemSentenceRefs': [ref]}
                        targets = _context_stem_targets(single_ref_context, {ref['sentenceId']: sentence},
                            lambda source: [tuple(row['target_range'])] if source['id'] == sentence['id'] else [])
                        target = list(next(item[2] for item in targets)) if targets else None
                    else:
                        target = list(context_target_ranges(derived, sentence, [tuple(row['target_range'])])[0])
                    if target is None:
                        continue
                    if not derived.get('hasQuestionBlank'):
                        separator = derived['completedEnglish'].find('\n\n')
                        if separator >= 0:
                            target = [value - 1 if value > separator else value for value in target]
                    if native['english'][slice(*target)] != row['english'][slice(*row['target_range'])]:
                        raise ValueError('native candidate source target differs from its exact projected range')
                    if target not in native['target_ranges']:
                        if _preferred_native_context_owner(row, native, (approved or {}).get(identity), native_by_jump):
                            continue
                        raise ValueError('native candidate source target differs from its exact projected range')
                    additions.append((identity, row, {**view, 'target_range': target,
                        'native_match_origin': 'stem' if key == 'stemSentenceRefs' else 'option'}))
                    known.add(identity)
    return additions


def _label_row(row, view):
    """The source role is physical; correctness belongs to this shown candidate."""
    result = deepcopy(row)
    usage = result.get('usage') or occurrence_usage(result)
    derived = view.get('derivation_payload') or {}
    if derived.get('candidateOptionLabel'):
        old_candidate = usage.get('reading_candidate', {})
        origins = [view['native_match_origin']] if 'native_match_origin' in view else old_candidate.get('match_origins')
        if not origins:
            origins = ['option' if usage['source_role'] == 'reading_option' else 'stem']
        usage['reading_candidate'] = {'question_id': derived['questionId'],
            'option_label': derived['candidateOptionLabel'],
            'correctness': ('correct' if derived.get('isCorrectCandidate') is True else
                'incorrect' if derived.get('isCorrectCandidate') is False else 'unknown'),
            'match_origins': origins}
    result['usage'] = usage
    return result


def _labels(rows):
    candidates, others = {}, []
    for row in rows:
        usage = row.get('usage') or occurrence_usage(row)
        candidate = usage.get('reading_candidate')
        if candidate:
            key = (candidate.get('question_id'), candidate.get('option_label'), candidate['correctness'])
            merged = candidates.setdefault(key, deepcopy(candidate))
            merged['match_origins'] = list(dict.fromkeys([*merged['match_origins'], *candidate['match_origins']]))
        else:
            markup = occurrence_markup({**row, 'usage': usage})
            if markup and markup not in others:
                others.append(markup)
    markup = ''.join(candidate_markup(candidate) for candidate in candidates.values()) + ''.join(others)
    return '<span data-native-example-usage="v1">' + markup + '</span>' if markup else ''


def _apply(page, edits):
    pieces, proof, cursor, offset = [], [], 0, 0
    for start, end, replacement in sorted(edits, key=lambda edit: (edit[0], edit[1])):
        if not 0 <= cursor <= start <= end <= len(page):
            raise ValueError('native replacement spans overlap or are invalid')
        pieces.extend((page[cursor:start], replacement))
        proof.append({'range': [start + offset, start + offset + len(replacement)],
            'original': page[start:end], 'replacement_sha256': sd._sha(replacement)})
        offset += len(replacement) - (end - start)
        cursor = end
    pieces.append(page[cursor:])
    return ''.join(pieces), proof


def _source_classes(fragment, aliases):
    """Keep shipped compressed CSS applicable to the renderer's new spans."""
    reverse = {}
    for compact, canonical in aliases.items():
        reverse.setdefault(canonical, []).append(compact)
    def decorate(match):
        classes = match[1].split()
        classes = list(dict.fromkeys([*classes, *(compact for name in classes
                                                 for compact in reverse.get(name, []))]))
        return 'class="' + escape(' '.join(classes), quote=True) + '"'
    return re.sub(r'class="([^"]+)"', decorate, fragment)


def _validate_recovery_owner_match(prepared, row, history, documents):
    """Replay only the accepted recovery driver's finite lexical licenses.

    This is a read-only consumer of its pinned dictionary proof, not a new
    alias rule. The lazy import avoids a module initialization cycle. Original
    history bytes and the native updater's retained-row guard stay unchanged.
    """
    from scripts.patch_exam_usage_preview import _licensed_span
    source = history['source_parent_row']
    decision = history.get('owner_recovery_decision')
    if not isinstance(decision, dict) or not isinstance(decision.get('target'), dict):
        raise ValueError('licensed ownership history lacks its complete approved decision')
    chosen = decision['target']
    current = next((sense for sense in prepared.get('senses', [])
                    if sense['sense_id'] == row.get('sense_id')), None)
    if (decision.get('action') != 'append_owner_row' or
            decision.get('book_id') != prepared['book_id'] or
            decision.get('source_card_id') != history['source_card_id'] or
            decision.get('source_parent_snapshot_id') != history['source_parent_snapshot_id'] or
            decision.get('source_occurrence_id') != source['occurrence_id'] or
            decision.get('source_record_sha256') != sd._sha(sd._json(source)) or
            chosen.get('card_id') != prepared['card_id'] or
            chosen.get('word') != prepared.get('word') or
            chosen.get('occurrence_id') != row['occurrence_id'] or
            chosen.get('target_range') != row['target_range'] or
            current is None or any(chosen.get(key) != current[key]
                                   for key in ('sense_id', 'ordinal', 'pos', 'text')) or
            any(source.get(key) != row.get(key) for key in _PHYSICAL if key != 'target_range') or
            source.get('translation_hash') != row.get('translation_hash')):
        raise ValueError('licensed ownership decision differs from its complete actual source/target')
    variant_pin = (documents or {}).get('__owner_recovery_native_variant_addendum__')
    actual = _licensed_span(prepared, source, row, decision,
        source_word=history['source_word'], variant_pin=variant_pin)
    if actual != history['match_kind']:
        raise ValueError('licensed ownership history differs from its independently replayed lexical permission')


def _native_histories(prepared, rows, *, documents=None, target_urls=None):
    """Validate destination bindings without resealing historical evidence."""
    from .ownership_history import (_IDENTITY_FIELDS, _quantity_phrase,
                                    _validate_authority, _validate_row,
                                    render_ownership_history, validate_history_content)
    rendered, pins = {}, {}
    for identity, row in rows.items():
        histories = row.get('ownership_history', [])
        if not isinstance(histories, list):
            raise ValueError('native ownership history must be an array')
        if not histories:
            continue
        seen = set()
        for history in histories:
            validate_history_content(history)
            if (history['book_id'] != prepared['book_id'] or
                    history['target_card_id'] != prepared['card_id'] or
                    history['target_occurrence_id'] != identity or
                    history['target_word'] != prepared.get('word') or
                    history.get('target_range') != row['target_range'] or
                    history['target_reason'] != row['reason']):
                raise ValueError('native ownership history differs from its actual destination')
            source = history['source_parent_row']
            _validate_row(source)
            if any(history['source_identity'].get(key) != source[key] for key in _IDENTITY_FIELDS):
                raise ValueError('native ownership history original source identity differs')
            _validate_authority(history, source)
            expected = sd._sha(sd._json([history['book_id'], history['source_card_id'],
                history['source_parent_snapshot_id'], source, history['exclusion_authority'],
                history['target_card_id'], history['target_occurrence_id']]))
            if history['history_id'] != expected or expected in seen:
                raise ValueError('native ownership history fingerprint is stale or duplicated')
            seen.add(expected)
            if any(source.get(key) != row.get(key) for key in ('paper_id', 'physical_source', 'english_hash')):
                raise ValueError('native ownership history physical source differs from its destination')
            kind = history.get('match_kind', 'exact_span')
            if kind in {'exact_span', 'same_physical_exact_span'}:
                if source['occurrence_id'] != identity or source['target_range'] != row['target_range']:
                    raise ValueError('native ownership history exact physical target span differs')
            elif kind == 'same_native_quantity_phrase':
                _quantity_phrase(prepared, source, row, history)
            elif kind == 'fixed_phrase_contains_exact_component_span':
                a, b = row['target_range']; x, y = source['target_range']
                if not (a <= x < y <= b and ' '.join(row['english'][a:b].split()).casefold() ==
                        ' '.join(prepared['word'].split()).casefold()):
                    raise ValueError('native ownership history fixed phrase target span differs')
            elif kind in {'licensed_will_negative_contraction', 'licensed_native_owner_variant'}:
                _validate_recovery_owner_match(prepared, row, history, documents)
            else:
                raise ValueError('native ownership history has an unsupported physical match')
            sense = history['matched_sense']
            current = next((item for item in prepared.get('senses', [])
                            if item['sense_id'] == row.get('sense_id')), None)
            if (row.get('status') != 'reviewed' or row.get('reviewed_sense_id') != row.get('sense_id') or
                    current is None or any(sense.get(key) != current[key]
                                           for key in ('pos', 'text', 'ordinal'))):
                raise ValueError('native ownership history actual reviewed sense differs')
            provenance = prepared.get('definition_provenance', {})
            appended = next((item for item in provenance.get('supplemental_definitions', {}).get('appended', [])
                             if item.get('ordinal') == current['ordinal']), None)
            dictionary = (appended.get('source_dictionary') if appended else None) or prepared.get('definition_source')
            if sense['dictionary_source'] != dictionary:
                raise ValueError('native ownership history actual dictionary source differs')
        rendered[identity] = render_ownership_history(row, link_map=target_urls,
            documents=documents, include_source_example=False)
        pins[identity] = [{'history_id': item['history_id'], 'content_sha256': item['content_sha256']}
                          for item in histories]
    return rendered, pins


def update_native_examples(page, old_prepared, new_prepared, *, aliases=None, source_aliases=None,
                           ownership_history_documents=None, target_urls=None,
                           defer_ownership_coverage=False):
    """Return ``{page, inverse, stats}``, without changing either prepared input.

    Only exact source-pinned targets can be removed. A surviving or unbound
    target preserves its whole example. Existing source jumps are never edited.
    The returned inverse is independent of frequency and sense-report inverses.
    """
    if (not isinstance(page, str) or not isinstance(defer_ownership_coverage, bool) or
            not isinstance(aliases or {}, dict) or
            (ownership_history_documents is not None and not isinstance(ownership_history_documents, dict)) or
            (target_urls is not None and not isinstance(target_urls, dict))):
        raise ValueError('native page and class aliases have invalid types')
    old_rows, new_rows = _rows(old_prepared), _rows(new_prepared)
    alias_snapshot = load_source_aliases(source_aliases) if source_aliases is not None else None
    if any(old_prepared.get(key) != new_prepared.get(key) for key in ('book_id', 'card_id')):
        raise ValueError('native update snapshots belong to different cards')
    for identity, row in new_rows.items():
        if identity not in old_rows or not _physical_equal(old_rows[identity], row):
            raise ValueError('native update must preserve each retained physical row')
        if row.get('display'):
            sd.validate_display(row['display'], row)
        if any(item not in row.get('ownership_history', []) for item in old_rows[identity].get('ownership_history', [])):
            raise ValueError('native update changed an immutable ownership history')
    history_markup, history_pins = _native_histories(new_prepared, new_rows,
        documents=ownership_history_documents, target_urls=target_urls)
    evidence = deepcopy(old_rows)
    for prepared in (old_prepared, new_prepared):
        for row in _excluded(prepared):
            identity = _identity(row)
            if identity in evidence and not _physical_equal(evidence[identity], row):
                raise ValueError('native exclusion differs from its original physical row')
            evidence.setdefault(identity, row)
    approved = {identity: sd.refresh_derived_chunks(row)['display']
                for identity, row in evidence.items() if row.get('display')}
    by_anchor = {}
    for identity, row in evidence.items():
        anchors = set(sd._source_ids(row))
        view = approved.get(identity, {})
        native_jump = view.get('provenance', {}).get('native_jump')
        if native_jump:
            anchors.add(native_jump['sentence_id'])
        derived = view.get('derivation_payload') or {}
        anchors.update(ref['sentenceId'] for key in ('stemSentenceRefs', 'optionSentenceRefs')
                       for ref in derived.get(key, []))
        for anchor in anchors:
            by_anchor.setdefault(anchor, []).append((identity, row))
    stats = {'native_examples': 0, 'updated_examples': 0, 'removed_examples': 0,
             'unbound_examples': 0, 'unbound_targets': 0, 'removed_target_marks': 0,
             'reviewed_source_alias_examples': 0}
    if history_markup:
        stats.update(ownership_history_examples=0, ownership_histories=0)
    attached_histories = set()
    edits, bindings = [], []
    parser = _Offsets(page, aliases or {})
    native_examples, native_by_jump = [], {}
    for node in parser.root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or _historical(node):
            continue
        if node.closed is None or node.end is None:
            raise ValueError('native example has no exact closing boundary')
        original = page[node.start:node.end]
        native = _current_native_example(original, aliases or {})
        native_examples.append((node, original, native))
        if native['jump'] is not None:
            native_by_jump.setdefault(sd._json(native['jump']), []).append(native)
    for node, original, native in native_examples:
        stats['native_examples'] += 1
        if native['jump'] is None:
            stats['unbound_examples'] += 1
            continue
        matches = []
        for identity, row in by_anchor.get(native['jump']['sentence_id'], []):
            if _other_approved_native_target(row, native, approved.get(identity), native_by_jump):
                continue
            view = _view(row, native, approved.get(identity))
            if view is not None and view['target_range'] in native['target_ranges']:
                matches.append((identity, row, view))
        matches.extend(_context_views(matches, evidence, native, native_by_jump=native_by_jump, approved=approved))
        alias_match = _source_alias_match(alias_snapshot, old_prepared, evidence, original, native)
        if alias_match is not None:
            if any(identity == alias_match[0] for identity, _, _ in matches):
                raise ValueError('reviewed source alias duplicates an already bound native target')
            matches.append(alias_match)
            stats['reviewed_source_alias_examples'] += 1
        covered = {tuple(view['target_range']) for _, _, view in matches}
        unbound = {tuple(span) for span in native['target_ranges']} - covered
        stats['unbound_targets'] += len(unbound)
        if not matches:
            stats['unbound_examples'] += 1
            continue
        kept = [(identity, new_rows[identity], view) for identity, _, view in matches if identity in new_rows]
        removed = covered - {tuple(view['target_range']) for _, _, view in kept}
        stats['removed_target_marks'] += len(removed)
        bindings.append({'source_markup_sha256': sd._sha(original),
            'targets': [{'occurrence_id': identity, 'old_row_sha256': sd._sha(sd._json(row)),
                'new_row_sha256': sd._sha(sd._json(new_rows[identity])) if identity in new_rows else None,
                'display_target_range': view['target_range'],
                **({'source_alias_entry_sha256': view['source_alias_entry_sha256']}
                    if 'source_alias_entry_sha256' in view else {}),
                **({'ownership_history': history_pins[identity]}
                    if identity in history_pins and identity in new_rows else {})}
                for identity, row, view in matches]})
        if not kept and not unbound:
            edits.append((node.start, node.end, ''))
            stats['removed_examples'] += 1
            continue
        en, zh = _current_descendant(node,'example-text'), _current_descendant(node,'example-translation')
        if any(part.closed is None for part in (en, zh)):
            raise ValueError('native sentence spans have no exact closing boundaries')
        views = [view for _, _, view in kept] or [view for _, _, view in matches]
        aligned = [view.get('alignment') for view in views if view.get('alignment') is not None]
        if aligned and any(alignment != aligned[0] for alignment in aligned):
            raise ValueError('native matched targets disagree on approved chunk alignment')
        alignment = aligned[0] if aligned else None
        example = {'text': native['english'], 'translation': native['translation']}
        if alignment is not None:
            example.update(translation_source='codex', translation_alignment=alignment)
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        targets = sorted({tuple(span) for span in native['target_ranges']} - removed)
        en_markup = _highlight_example(native['english'], '', '', native['cloze_answers'],
            target_ranges=targets, chunk_ranges=en_chunks, preserve_source=True)
        zh_markup = _chunk_translation(native['translation'], zh_chunks)
        en_markup = _annotate_sentence_chunks(en_markup, alignment)
        zh_markup = _annotate_sentence_chunks(zh_markup, alignment)
        en_markup = _source_classes(en_markup, aliases or {})
        zh_markup = _source_classes(zh_markup, aliases or {})
        edits.append((en.opened, en.closed, en_markup))
        # Keep the original translation label and its packaging separator bytes.
        tags = [part for part in zh.walk() if 'translate-tag' in part.classes]
        if len(tags) > 1 or (tags and (tags[0].parent is not zh or tags[0].start != zh.opened)):
            raise ValueError('native translation label has an unsupported boundary')
        left = tags[0].end if tags else zh.opened
        if left is None:
            raise ValueError('native translation label is unterminated')
        if page[left:zh.closed].startswith(' '):
            left += 1
        edits.append((left, zh.closed, zh_markup))
        markers = [part for part in node.walk() if part.attrs.get('data-native-example-usage')
                   and not _historical(part)]
        if len(markers) > 1:
            raise ValueError('native usage label is duplicated')
        label = _labels([_label_row(row, view) for _, row, view in kept])
        if markers:
            marker = markers[0]
            if marker.end is None:
                raise ValueError('native usage label is unterminated')
            edits.append((marker.start, marker.end, label))
        elif label:
            edits.append((node.closed, node.closed, label))
        incoming = {identity: history_markup[identity] for identity, _, _ in kept if identity in history_markup}
        history_nodes = [part for part in node.walk() if part.attrs.get('data-native-ownership-history')
                         and not _historical(part.parent)]
        if len(history_nodes) > 1:
            raise ValueError('native ownership history wrapper is duplicated')
        history_block = ('<div class="sf-native-ownership-history" data-native-ownership-history="v1">' +
                         ''.join(incoming.values()) + '</div>') if incoming else ''
        if history_nodes:
            marker = history_nodes[0]
            if marker.parent is not node or marker.end is None:
                raise ValueError('native ownership history has an unsupported boundary')
            edits.append((marker.start, marker.end, history_block))
        elif history_block:
            edits.append((node.closed, node.closed, history_block))
        if incoming:
            attached_histories.update(incoming)
            stats['ownership_history_examples'] += 1
            stats['ownership_histories'] += sum(len(history_pins[identity]) for identity in incoming)
        stats['updated_examples'] += 1
    if set(history_markup) != attached_histories and not defer_ownership_coverage:
        raise ValueError('ownership history has no exactly bound native destination example')
    from .example_numbering import numbering_edits
    edits.extend(numbering_edits(page, aliases or {},
        removed_ranges=[(start, end) for start, end, replacement in edits if replacement == '']))
    updated, spans = _apply(page, edits)
    inverse = {'schema': SCHEMA, 'source_page_sha256': sd._sha(page),
        'updated_page_sha256': sd._sha(updated), 'old_rows_sha256': sd._sha(sd._json(old_prepared)),
        'new_rows_sha256': sd._sha(sd._json(new_prepared)), 'bindings': bindings, 'spans': spans}
    if alias_snapshot is not None:
        inverse['source_alias_ledger_file_sha256'] = alias_snapshot._file_sha256
    inverse['inverse_sha256'] = sd._sha(sd._json(inverse))
    if restore_original(updated, inverse) != page:
        raise ValueError('native byte inverse did not recover the original page')
    result = {'page': updated, 'inverse': inverse, 'stats': stats}
    if history_markup:
        # Deferral is an explicit obligation, never a successful render claim.
        # The caller must validate the complete final SF/native HTML jointly.
        coverage = {'schema': 'ownership-native-coverage.v1',
            'book_id': new_prepared['book_id'], 'card_id': new_prepared['card_id'],
            'snapshot_id': new_prepared['snapshot_id'],
            'native': {identity: history_pins[identity] for identity in history_pins
                       if identity in attached_histories},
            'deferred': {identity: history_pins[identity] for identity in history_pins
                         if identity not in attached_histories},
            'native_examples': {}}
        for element in _Offsets(updated, aliases or {}).root.walk():
            if element.tag != 'li' or 'example-card' not in element.classes:
                continue
            wrappers = [child for child in element.children
                        if child.attrs.get('data-native-ownership-history') == 'v1']
            for wrapper in wrappers:
                for detail in wrapper.children:
                    identity = detail.attrs.get('data-ownership-target-occurrence-id')
                    if identity in attached_histories:
                        coverage['native_examples'].setdefault(identity, set()).add(
                            sd._sha(updated[element.start:element.end]))
        coverage['native_examples'] = {identity: sorted(values)
                                      for identity, values in coverage['native_examples'].items()}
        coverage['coverage_sha256'] = sd._sha(sd._json(coverage))
        result['ownership_coverage'] = coverage
    return result


def restore_original(page, inverse):
    """Restore exact original HTML only when the native update remains intact."""
    if not isinstance(page, str) or not isinstance(inverse, dict):
        raise ValueError('native inverse page or payload has an invalid type')
    sealed = dict(inverse)
    claimed = sealed.pop('inverse_sha256', None)
    if claimed != sd._sha(sd._json(sealed)):
        raise ValueError('native inverse payload hash is stale')
    if (inverse.get('schema') != SCHEMA or
            sd._sha(page) != inverse.get('updated_page_sha256')):
        raise ValueError('native inverse updated page hash is stale')
    previous = len(page)
    for item in reversed(inverse.get('spans', [])):
        start, end = item['range']
        if (not 0 <= start <= end <= previous or
                sd._sha(page[start:end]) != item['replacement_sha256']):
            raise ValueError('native inverse replacement span is stale')
        page = page[:start] + item['original'] + page[end:]
        previous = start
    if sd._sha(page) != inverse.get('source_page_sha256'):
        raise ValueError('native inverse source page hash is stale')
    return page


_CHUNK_BLOCK = re.compile(
    r'^// Rendered spans contain only validated, existing chunk IDs\.[^\n]*\n'
    r'.*?^\}\)\(\);[^\S\n]*(?:\n|$)', re.MULTILINE | re.DOTALL)


def _adapted_runtime(aliases, *, history_roots=False):
    roots = ['example-card', 'sf-example']
    for compact, canonical in aliases.items():
        if canonical in {'example-card', 'sf-example'}:
            if not isinstance(compact, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', compact):
                raise ValueError('native chunk root alias is not a safe CSS class')
            if compact not in roots:
                roots.append(compact)
    if history_roots:
        roots.extend(['sf-native-ownership-history', 'sf-ownership-history',
                      'sf-archived-example', 'sf-archived-native-example'])
    selector = ','.join('.' + name for name in roots)
    source = Path(sd.__file__).with_name('templates').joinpath('card-chunks.js').read_text()
    expected = "var root = chunk && chunk.closest('.example-card');"
    if source.count(expected) != 1 or source.count('if (window.__ankiCardChunksBound) return;') != 1:
        raise ValueError('unsupported shared chunk runtime entry points')
    source = source.replace(expected, "var root = chunk && chunk.closest('" + selector + "');")
    if history_roots:
        # Archived explanations retain original IDs. Each nested source root
        # must select its own chunks, even when a containing sentence uses 0/1.
        activate = "selected.root.querySelectorAll('.card-chunk').forEach(function (chunk) {\n      var chunkIds = ids(chunk);"
        if source.count(activate) != 1:
            raise ValueError('unsupported shared chunk runtime activation boundary')
        source = source.replace(activate,
            "selected.root.querySelectorAll('.card-chunk').forEach(function (chunk) {\n" +
            "      if (chunk.closest('" + selector + "') !== selected.root) return;\n      var chunkIds = ids(chunk);")
    source = source.replace('__ankiCardChunksBound', '__ankiNativeCardChunksBoundV1')
    # Static pages replace every old bootstrap before it executes. Marking the
    # legacy guard also prevents any later legacy bundle from adding handlers.
    # The new guard works even if an earlier component set the legacy flag.
    source = source.replace('(function () {',
        '(function () {\n  window.__ankiCardChunksBound = true;', 1)
    return source, selector


def _replace_bootstrap(source, runtime):
    blocks = list(_CHUNK_BLOCK.finditer(source))
    if not blocks:
        if '__ankiCardChunksBound' in source or '__ankiNativeCardChunksBoundV1' in source:
            raise ValueError('unsupported existing chunk bootstrap')
        return None
    if len(blocks) != 1:
        raise ValueError('unsupported repeated chunk bootstrap inside one script')
    old = blocks[0]
    if ("chunk.closest('." not in old[0] or "document.addEventListener('click'" not in old[0]
            or not any(guard in old[0] for guard in (
                'if (window.__ankiCardChunksBound) return;',
                'if (window.__ankiNativeCardChunksBoundV1) return;'))):
        raise ValueError('unsupported existing chunk bootstrap entry points')
    return source[:old.start()] + runtime + source[old.end():]


def install_chunk_runtime(page, aliases=None, *, source_path=None):
    """Adapt existing chunk bootstraps while preserving all other bundle code.

    Returns ``{page, edits, inverse, stats}``. ``edits`` contains original-page
    offset triples and can join the caller's existing byte-inverse edit pass.
    External content-addressed bundles require their exact source HTML path;
    the helper resolves only its declared local assets and checks file hashes.
    It writes neither those assets nor the original HTML.
    """
    if not isinstance(page, str) or not isinstance(aliases or {}, dict):
        raise ValueError('native runtime page or aliases have invalid types')
    parsed = _Offsets(page, {})
    history_roots = any(node.attrs.get('data-native-ownership-history') or 'sf-ownership-history' in node.classes
                        for node in parsed.root.walk())
    runtime, selector = _adapted_runtime(aliases or {}, history_roots=history_roots)
    edits, assets = [], {}
    stats = {'replaced_scripts': 0, 'external_bundles_inlined': 0,
             'root_selector': selector, 'legacy_singleton_bypassed': True}
    for node in parsed.root.walk():
        if node.tag != 'script':
            continue
        if node.closed is None or node.end is None:
            raise ValueError('native runtime script has no exact closing boundary')
        src = node.attrs.get('src')
        if src:
            if source_path is None:
                raise ValueError('external native chunk bundles require exact source_path')
            parsed = urlsplit(src)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path.startswith('/'):
                raise ValueError('native runtime only supports declared relative local script assets')
            asset = (Path(source_path).resolve().parent / unquote(parsed.path)).resolve(strict=True)
            if not re.fullmatch(r'[0-9a-f]{64}\.js', asset.name):
                raise ValueError('native runtime asset is not content addressed')
            raw = asset.read_bytes()
            source = raw.decode('utf-8')
            if sd._sha(source) != asset.stem:
                raise ValueError('native runtime asset hash differs from its content address')
            assets[str(asset)] = asset.stem
        else:
            source = page[node.opened:node.closed]
        revised = _replace_bootstrap(source, runtime)
        if revised is None:
            continue
        if src:
            if any(key in node.attrs for key in ('async', 'defer')) or node.attrs.get('type', '').lower() == 'module':
                raise ValueError('native runtime cannot inline an asynchronous or module bootstrap')
            if re.search(r'</script\b', revised, flags=re.I):
                raise ValueError('native runtime bundle cannot safely become inline HTML')
            opening = page[node.start:node.opened]
            opening, count = re.subn(r'\s+src\s*=\s*(?:"[^"]*"|\x27[^\x27]*\x27|[^\s>]+)', '', opening, count=1, flags=re.I)
            if count != 1:
                raise ValueError('native runtime script source attribute has an unsupported boundary')
            replacement = opening + revised + page[node.closed:node.end]
            edits.append((node.start, node.end, replacement))
            stats['external_bundles_inlined'] += 1
        elif revised != source:
            edits.append((node.opened, node.closed, revised))
        else:
            continue
        stats['replaced_scripts'] += 1
    updated, spans = _apply(page, edits)
    inverse = {'schema': SCHEMA, 'source_page_sha256': sd._sha(page),
        'updated_page_sha256': sd._sha(updated), 'runtime_source_sha256': sd._sha(runtime),
        'source_assets': assets, 'root_selector': selector, 'spans': spans}
    inverse['inverse_sha256'] = sd._sha(sd._json(inverse))
    if restore_original(updated, inverse) != page:
        raise ValueError('native runtime inverse did not recover its original page')
    return {'page': updated, 'edits': edits, 'inverse': inverse, 'stats': stats}
