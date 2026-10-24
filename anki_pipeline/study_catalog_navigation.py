"""Read-only, bounded navigation metadata for the common study projection.

This is an index projection, never a second card renderer or a frequency
calculator. Displayed example rows and physical word occurrences are different
quantities. Missing example information stays unknown instead of becoming zero.
"""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re

from .slim_apkg_content import Slices
from .example_numbering import HISTORY_CLASSES


SUMMARY_LIMIT = 480
_EXAMPLES = frozenset({'example-card', '_r28'})
_OMIT = HISTORY_CLASSES | frozenset({'sf-panel', 'etymology-section', 'sf-example',
                                     'sf-wrong-bindings', 'sf-ownership-pending-note'})
_INTERESTS = _OMIT | _EXAMPLES | frozenset({'sf-meaning', 'sense-row', 'exam-frequency',
                                         'as-lazy', 'as-manifest'})


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1
        elif tag in {'br', 'p', 'div', 'li', 'span', 'h1', 'h2', 'h3', 'section'} and not self.ignored:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.ignored = max(0, self.ignored - 1)
        elif not self.ignored:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def _plain(raw):
    parser = _Text()
    parser.feed(raw)
    parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def _bounded(text):
    return text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT - 1].rstrip() + '…'


def _ancestor(node, classes):
    node = node.parent
    while node:
        if node.classes & classes:
            return True
        node = node.parent
    return False


def _nodes(raw, interests):
    # The compact scanner retains selected classes. Attribute-only immutable
    # source comparisons need the existing full offset parser so their parent
    # marker is visible to the same shared current/history predicate.
    if re.search(r'<[^>]+\sdata-(?:native-ownership-history|reviewed-source-comparison)(?:\s|=|>)', raw):
        from .native_example_usage import _Offsets
        return list(_Offsets(raw, {}).root.walk())[1:]
    return Slices(raw, interests=interests).nodes


def _digest(raw, *, examples_only=False, nodes=None, bounds=None):
    from .native_example_usage import _historical
    lower, upper = bounds if bounds is not None else (0, len(raw))
    if nodes is None:
        nodes = _nodes(raw, _INTERESTS)
    nodes = [node for node in nodes if lower <= node.start and node.end is not None and node.end <= upper]
    senses = []
    frequency = None
    examples = 0
    lazy = False
    for node in nodes:
        if _historical(node) or node.classes & _OMIT or _ancestor(node, _OMIT):
            continue
        if 'as-lazy' in node.classes and not _ancestor(node, {'as-lazy'}):
            if _ancestor(node, _EXAMPLES):
                # An audit disclosure inside an already counted example cannot
                # add another top-level native example to the rendered list.
                continue
            if node.attrs.get('data-as-kind') == 'examples':
                manifests = [child for child in node.children if 'as-manifest' in child.classes]
                if len(manifests) != 1 or manifests[0].closed is None:
                    raise ValueError('current example storage has no unique count manifest')
                manifest = json.loads(raw[manifests[0].opened:manifests[0].closed])
                total = manifest.get('total')
                parts = manifest.get('parts')
                if (manifest.get('schema') != 'anki-slim-segments.v1' or
                        isinstance(total, bool) or not isinstance(total, int) or total < 0 or
                        not isinstance(parts, list) or any(not isinstance(part, dict) or
                            isinstance(part.get('count'), bool) or not isinstance(part.get('count'), int) or
                            part['count'] < 0 for part in parts) or
                        sum(part['count'] for part in parts) != total):
                    raise ValueError('current example storage count manifest is inconsistent')
                examples += total
            else:
                lazy = True
        if not examples_only and node.classes & {'sf-meaning', 'sense-row'} and node.closed is not None:
            text = _plain(raw[node.opened:node.closed])
            if text and text not in senses:
                senses.append(text)
        if node.tag == 'li' and node.classes & _EXAMPLES and not _ancestor(node, _EXAMPLES):
            examples += 1
        if 'exam-frequency' in node.classes and frequency is None:
            values = [node.attrs.get(key) for key in ('data-occurrences', 'data-paper-count', 'data-corpus-papers', 'data-stars')]
            if all(isinstance(value, str) and re.fullmatch(r'\d+(?:\.\d+)?', value) for value in values):
                frequency = '真题词频 {} 次 覆盖 {} / {} 套 {} / 5'.format(*values)
    if examples_only:
        # An arbitrary subject may author prose in an Examples field instead
        # of this renderer's row DOM. Missing row DOM is not proof of zero.
        count = None if lazy or examples == 0 and _plain(raw[lower:upper]) else examples
        return '', count
    if not senses:
        # Remove source/history panels at their exact offsets before flattening
        # an ordinary generic field. Never index embedded iframe srcdoc or JS.
        omitted = []
        for node in nodes:
            if ((_historical(node) or node.classes & _OMIT) and node.end is not None
                    and not _historical(node.parent) and not _ancestor(node, _OMIT)):
                omitted.append((node.start, node.end))
        fragment = raw[lower:upper]
        for start, end in reversed(omitted):
            fragment = fragment[:start - lower] + ' ' + fragment[end - lower:]
        text = _plain(fragment)
    else:
        text = ' '.join(senses)
    return _bounded(' '.join(part for part in (frequency, text) if part)), None


def note_navigation_metadata(note, *, source_entry=None):
    """Derive compact current metadata from one already projected note.

    ``source_entry`` contributes only its original grouping path. Its old
    definitions/counts cannot override a current projected field revision.
    Arbitrary subjects need no Word field, frequency schema or specific model.
    """
    names, values = note['field_names'], note['fields']
    if len(names) != len(values) or len(set(names)) != len(names) or any(not isinstance(value, str) for value in values):
        raise ValueError('navigation requires an exact named text field mapping')
    fields = dict(zip(names, values))
    return _metadata(fields, source_entry, lambda name, examples_only=False: _digest(fields[name], examples_only=examples_only))


def _metadata(fields, source_entry, digest):
    summary = ''
    preferred = ('Definition', 'SimpleDefinition', 'Answer', 'Back', 'Solution', 'Question', 'Title', 'Front')
    candidates = (*preferred, *(name for name in fields if name not in preferred and name not in {
        'Word', 'Phonetic', 'Audio', 'Examples', 'Meta', 'Level', 'WordForms', 'Note'}))
    for name in candidates:
        if fields.get(name):
            summary = digest(name)[0]
            if summary:
                break
    count = digest('Examples', examples_only=True)[1] if 'Examples' in fields else None
    result = {'summary': summary, 'example_count': count}
    if source_entry and source_entry.get('deckName'):
        result['deck_name'] = source_entry['deckName']
    return result


def catalog_navigation_metadata(catalog, *, grouping_only=False):
    """Extract only authored scalar metadata; do not trust cached totals."""
    cards = {}
    groups = set()
    for entry in catalog['cards']:
        identity = entry['id']
        if not isinstance(identity, str) or not identity or identity in cards:
            raise ValueError('source catalog has a missing or duplicate card identity')
        raw_summary = '' if grouping_only else entry.get('definition')
        if raw_summary is None:
            raw_summary = entry.get('source_definition_summary', '')
        if not isinstance(raw_summary, str):
            raise ValueError('source catalog summary must be text')
        count = None if grouping_only else entry.get('exampleCount', entry.get('source_example_count'))
        if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
            raise ValueError('source example count must be a nonnegative integer or unknown')
        row = {'summary': _bounded(_plain(raw_summary)), 'example_count': count}
        if entry.get('deckName'):
            if not isinstance(entry['deckName'], str):
                raise ValueError('source grouping path must be text')
            row['deck_name'] = entry['deckName']
            groups.add(entry['deckName'])
        cards[identity] = row
    counts = [row['example_count'] for row in cards.values()]
    return {'cards': cards, 'totals': {'notes': len(cards),
            'examples': sum(counts) if all(count is not None for count in counts) else None,
            'groups': len(groups)}}


def load_navigation_metadata(value, book_id):
    """Fast baseline refresh from the sealed retained PG source catalog.

    Counts and summaries in an imported source catalog may predate its exact
    APKG. They are therefore NEVER authoritative here: only grouping paths are
    returned. New exports use ``note_navigation_metadata`` on projected fields;
    refreshes use ``rendered_navigation_metadata`` on their existing card pages.
    A book without an original catalog returns unknown totals so its existing
    rendered card payload can supply metadata without a full PG re-projection.
    """
    from . import study_catalog as c
    with c.connect(value, readonly=True) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        row = db.execute('select value from metadata where key=%s', ('source.catalog.' + book_id,)).fetchone()
        if row is None:
            return {'cards': {}, 'totals': {'notes': None, 'examples': None, 'groups': None},
                    'provenance': {'kind': 'source-catalog-absent', 'book_id': book_id}}
        raw = c.get_object(db, row[0])
        result = catalog_navigation_metadata(json.loads(raw), grouping_only=True)
        result['provenance'] = {'kind': 'sealed-source-catalog', 'book_id': book_id, 'source_catalog_sha256': row[0],
                                'original_bytes_modified': False, 'current_projected_fields': False,
                                'scope': 'original-grouping-only'}
        return result


def rendered_navigation_metadata(page, *, source_entry=None):
    """Read an existing common wrapper's answer payload without executing it."""
    from .study_catalog_web import card_payload
    from .native_example_usage import _historical
    sides = json.loads(card_payload(page))
    if not isinstance(sides, list) or len(sides) != 2 or any(not isinstance(side, str) for side in sides):
        raise ValueError('rendered navigation needs the exact two-sided common payload')
    raw = sides[1]
    nodes = _nodes(raw, _INTERESTS | {'primary-definition', 'secondary-definition', 'field-content', 'examples', 'vocab-back'})
    fields = {}
    bounds = {}
    for node in nodes:
        if node.closed is None or _historical(node):
            continue
        if 'examples' in node.classes and not _ancestor(node, {'examples', 'field-content', 'primary-definition', 'secondary-definition'}):
            fields['Examples'] = raw[node.opened:node.closed]
            bounds['Examples'] = (node.opened, node.closed)
        elif 'field-content' in node.classes and not _ancestor(node, {'field-content', 'examples'}):
            for class_name, field in (('primary-definition', 'Definition'), ('secondary-definition', 'SimpleDefinition')):
                if _ancestor(node, {class_name}):
                    fields[field] = raw[node.opened:node.closed]
                    bounds[field] = (node.opened, node.closed)
    if not any(fields.get(name) for name in ('Definition', 'SimpleDefinition')):
        fields['Answer'] = raw
        bounds['Answer'] = (0, len(raw))
    if 'Examples' not in fields and any('vocab-back' in node.classes and not _historical(node) for node in nodes):
        # The authored vocabulary template conditionally omits this entire
        # section when its existing Examples field is empty. This proves zero;
        # a generic subject/model without that DOM contract remains unknown.
        fields['Examples'] = ''
    def digest(name, examples_only=False):
        if name not in bounds:
            return _digest(fields[name], examples_only=examples_only)
        return _digest(raw, examples_only=examples_only, nodes=nodes, bounds=bounds[name])
    return _metadata(fields, source_entry, digest)
