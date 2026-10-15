"""Group source-bound native examples using the existing formal sense groups.

Only presentation changes here. A prepared record, every physical token and its
sealed display proof remain immutable. Original native markup is retained in a
readable audit alongside each rewritten example; counts come from the record.
"""
from __future__ import annotations

from collections import defaultdict
from html import escape
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import sense_display as sd, sense_frequency as sf
from .example_numbering import renumber_examples
from .native_example_usage import (_Offsets, _apply, _rows, _source_classes, _view,
                                   _historical, _current_descendant, _current_native_example)
from .packaging import (_annotate_sentence_chunks, _chunk_translation,
                        _example_chunk_ranges, _highlight_example)
from .sense_groups import display_report


def _anchor(jump):
    """Compare the same original link while excluding only target coordinates."""
    value = jump['native_jump']
    fields = value.split('|')
    if len(fields) in {6, 7} and fields[0].isdigit():
        return ('packed', tuple(fields[:5]), tuple(fields[6:]))
    parsed = urlsplit(value)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if len([item for item in query if item[0] == 'anki-codex-en']) != 1:
        raise ValueError('native grouping needs one exact source range query')
    return ('url', parsed.scheme, parsed.netloc, parsed.path, parsed.fragment,
            tuple(sorted(item for item in query if item[0] != 'anki-codex-en')))


def _match(row, native, approved):
    if native['jump'] is None:
        return None
    expected = approved or row
    if (expected['english'] != native['english'] or expected['translation'] != native['translation']
            or expected['target_range'] not in native['target_ranges']):
        return None
    pinned = (approved or {}).get('provenance', {}).get('native_jump')
    if pinned is not None and native['jump'] != pinned:
        jump = native['jump']
        if (jump['sentence_id'] != pinned['sentence_id'] or _anchor(jump) != _anchor(pinned)
                or any(jump[key] != pinned[key] for key in ('english_hash', 'reviewed_content_hash'))
                or row['target_range'] not in jump['target_ranges']):
            return None
        # Validate the immutable approved proof, then use only its authored
        # display coordinates. The union jump is a separate presentation link;
        # neither the row nor its original native_jump gets resealed.
        return _view(row, {**native, 'jump': pinned}, approved)
    return _view(row, native, approved)


def _replace_attribute(opening, name, value):
    pattern = re.compile(r'(?<![\w:-])' + re.escape(name) + r'\s*=\s*([\'\"])(.*?)\1', re.S)
    matches = list(pattern.finditer(opening))
    if len(matches) != 1:
        raise ValueError('native grouping needs one exact ' + name + ' attribute')
    match = matches[0]
    return opening[:match.start(2)] + escape(value, quote=True) + opening[match.end(2):]


def _jump_opening(raw, node, ranges, reference):
    opening = raw[node.start:node.opened]
    edited = False
    if 'data-rb-j' in node.attrs:
        fields = node.attrs['data-rb-j'].split('|')
        if len(fields) not in {6, 7}:
            raise ValueError('unsupported packed native grouping jump')
        fields[5] = ';'.join(str(start) + ',' + str(end) for start, end in ranges)
        opening = _replace_attribute(opening, 'data-rb-j', '|'.join(fields))
        edited = True
    for key in ('href', 'data-latex-url'):
        value = node.attrs.get(key)
        if not value:
            continue
        parsed = urlsplit(value)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if not any(name == 'anki-codex-en' for name, _ in query):
            continue
        if len([pair for pair in query if pair[0] == 'anki-codex-en']) != 1:
            raise ValueError('native grouping jump repeats its target ranges')
        for parameter, source_key in (('anki-codex-sentence', 'sentence_id'),
                               ('anki-codex-hash', 'english_hash'),
                               ('anki-codex-review', 'reviewed_content_hash')):
            if [text for name, text in query if name == parameter] != [reference[source_key]]:
                raise ValueError('native grouping secondary jump differs from its sealed source identity')
        query = [(name, sd._json(ranges) if name == 'anki-codex-en' else text)
                 for name, text in query]
        opening = _replace_attribute(opening, key,
            urlunsplit(parsed._replace(query=urlencode(query))))
        edited = True
    if not edited:
        raise ValueError('unsupported native grouping source link')
    return opening


def _extra(markup, aliases):
    """Keep every non-core authored fragment, including audio and audit HTML."""
    root = _Offsets(markup, aliases).root.children[0]
    core = {'example-text', 'example-translation', 'example-source', 'sentence-jump', 'index-tag'}
    removals = []
    for node in root.walk():
        if node is root or not node.classes & core or _historical(node):
            continue
        ancestor = node.parent
        while ancestor is not None and ancestor is not root and not ancestor.classes & core:
            ancestor = ancestor.parent
        if ancestor is root:
            removals.append((node.start, node.end, ''))
    interior = markup[root.opened:root.closed]
    return _apply(interior, [(start - root.opened, end - root.opened, text)
                            for start, end, text in removals])[0]


def _safe_sentence_nodes(*parts):
    """Do not silently discard media or unsupported authored inline elements."""
    supported = {'target-word', 'card-chunk', 'cloze-answer', 'chunk-sentence'}
    for part in parts:
        for node in part.walk():
            if node is part or 'translate-tag' in node.classes:
                continue
            if (node.tag not in {'span', 'mark', 'u', 'br'} or
                    node.classes - supported or
                    (node.tag != 'br' and not node.classes) or
                    any(name != 'class' and name != 'title' and not name.startswith(('data-chunk-', 'data-blank-'))
                        for name in node.attrs)):
                raise ValueError('unsupported native sentence element prevents lossless grouping')


def _render(group, record, aliases):
    members = group['members']
    first = group['natives'][0]
    raw, native = first['raw'], first['native']
    node = _Offsets(raw, aliases).root.children[0]
    views = [view for _, view in members.values()]
    alignments = [view.get('alignment') for view in views]
    if any(alignment != alignments[0] for alignment in alignments):
        raise ValueError('native grouped targets disagree on their exact bilingual chunks')
    if any(item['native']['source'] != native['source'] or
           item['native']['cloze_answers'] != native['cloze_answers'] or
           _anchor(item['native']['jump']) != _anchor(native['jump']) for item in group['natives']):
        raise ValueError('native grouping needs the same source label, answers and exact source anchor')
    ranges = sorted({tuple(view['target_range']) for view in views})
    source_ranges = []
    for row, view in members.values():
        jump = native['jump']
        if (jump['sentence_id'] not in sd._source_ids(row) or jump['english_hash'] != row['english_hash']
                or jump['reviewed_content_hash'] != row['source_provenance'].get('reviewedContentHash')):
            raise ValueError('unsupported derived native anchor needs an explicit physical coordinate mapping')
        source_ranges.append(tuple(row['target_range']))
    source_ranges = [list(span) for span in sorted(set(source_ranges))]
    example = {'text': native['english'], 'translation': native['translation']}
    alignment = alignments[0]
    if alignment is not None:
        example.update(translation_source='codex', translation_alignment=alignment)
    en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
    english = _highlight_example(native['english'], '', '', native['cloze_answers'],
        target_ranges=ranges, chunk_ranges=en_chunks, preserve_source=True)
    chinese = _chunk_translation(native['translation'], zh_chunks)
    english = _source_classes(_annotate_sentence_chunks(english, alignment), aliases)
    chinese = _source_classes(_annotate_sentence_chunks(chinese, alignment), aliases)
    en, zh, jump_node = (_current_descendant(node,key) for key in
                         ('example-text', 'example-translation', 'sentence-jump'))
    if any(part.closed is None for part in (node, en, zh, jump_node)):
        raise ValueError('native grouping requires complete source element boundaries')
    for original in group['natives']:
        original_node = _Offsets(original['raw'], aliases).root.children[0]
        _safe_sentence_nodes(_current_descendant(original_node,'example-text'),
                             _current_descendant(original_node,'example-translation'))
    labels = [part for part in zh.walk() if 'translate-tag' in part.classes]
    if len(labels) > 1 or (labels and (labels[0].parent is not zh or labels[0].start != zh.opened)):
        raise ValueError('unsupported native translation label boundary')
    left = labels[0].end if labels else zh.opened
    if raw[left:zh.closed].startswith(' '):
        left += 1
    proof = {'schema': 'study-native-example-group.v1', 'snapshot_id': record['snapshot_id'],
             'occurrences': [row for row, _ in members.values()],
             'native_markup': [item['raw'] for item in group['natives']]}
    audit = ('<details class="sf-archived-native-example" data-study-native-group-evidence="v1">'
        '<summary>本段各处审核与完整来源</summary>'
        + ''.join('<p>义项依据：' + escape(row['reason']) + '</p>' for row, _ in members.values())
        + '<pre data-study-native-group-proof="v1" style="white-space:pre-wrap;overflow-wrap:anywhere">'
        + escape(sd._json(proof)) + '</pre></details>')
    extras = ''.join(_extra(item['raw'], aliases) for item in group['natives'][1:])
    return _apply(raw, [(en.opened, en.closed, english), (left, zh.closed, chinese),
        (jump_node.start, jump_node.opened, _jump_opening(raw, jump_node, source_ranges, native['jump'])),
        (node.closed, node.closed, extras + audit)])[0]


def group_native_examples(raw, record, aliases=None):
    """Return grouped native HTML, preserving all authoritative physical counts.

    Group only exact paper + physical paragraph + bilingual display + formal
    common-sense matches. Unrelated native rows stay byte-for-byte intact;
    partly bound, ambiguous or unsupported rewritten rows fail explicitly.
    """
    if not isinstance(raw, str):
        raise ValueError('native grouping markup must be text')
    aliases = {} if aliases is None else aliases
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in aliases.items()):
        raise ValueError('native grouping class aliases must be a string mapping')
    rows = _rows(record)
    report = display_report(sf.report_from_record(record))
    meanings = {row['occurrence_id']: sense['group_id'] for sense in report['senses']
                for row in sense['occurrences']}
    meanings.update({row['occurrence_id']: 'pending:' + row['occurrence_id'] for row in report['pending']})
    approved = {oid: sd.refresh_derived_chunks(row)['display'] for oid, row in rows.items() if row.get('display')}
    groups, items = {}, []
    for node in _Offsets(raw, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or _historical(node):
            continue
        if node.closed is None or node.end is None:
            raise ValueError('native grouping requires a complete current example')
        original = raw[node.start:node.end]
        native = _current_native_example(original, aliases)
        matches = [(oid, row, view) for oid, row in rows.items()
                   if (view := _match(row, native, approved.get(oid))) is not None]
        if not matches:
            continue
        covered = [tuple(view['target_range']) for _, _, view in matches]
        if len(covered) != len(set(covered)):
            raise ValueError('native grouping target has ambiguous physical source owners')
        if set(covered) != {tuple(span) for span in native['target_ranges']}:
            raise ValueError('native grouping contains an unbound or unreviewed target mark')
        item = {'node': node, 'raw': original, 'native': native, 'groups': []}
        items.append(item)
        for oid, row, view in matches:
            key = sd._json([row['paper_id'], row['physical_source'], view['english'],
                            view['translation'], meanings[oid]])
            group = groups.setdefault(key, {'members': {}, 'natives': []})
            group['members'][oid] = (row, view)
            if key not in item['groups']:
                item['groups'].append(key)
                group['natives'].append(item)
    rewrite = {key for key, group in groups.items() if len(group['natives']) > 1 or
               any(len(item['groups']) > 1 for item in group['natives'])}
    replacements = defaultdict(list)
    for key in rewrite:
        group = groups[key]
        if len({id(item['node'].parent) for item in group['natives']}) != 1:
            raise ValueError('unsupported native grouping across separate example list containers')
        first = min(group['natives'], key=lambda item: item['node'].start)
        replacements[first['node'].start].append((min(view['target_range'][0] for _, view in group['members'].values()),
                                                  _render(group, record, aliases)))
    edits = []
    for item in items:
        if not any(key in rewrite for key in item['groups']):
            continue
        node = item['node']
        replacement = ''.join(text for _, text in sorted(replacements[node.start], key=lambda part: part[0]))
        edits.append((node.start, node.end, replacement))
    return renumber_examples(_apply(raw, edits)[0], aliases)
