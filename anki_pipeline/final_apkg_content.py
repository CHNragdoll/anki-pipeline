"""Extract the accepted card presentation without reserializing source HTML.

This module does not open collections or packages.  The caller owns package
identity, media, and verification of the complete chunk-projection sidecar.
Only outer HTML class attributes are expanded; scripts and iframe srcdoc stay
byte-for-byte intact.
"""
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
import re

from .native_example_usage import _Offsets


_FIELDS = {
    'Definition': 'primary-definition',
    'SimpleDefinition': 'secondary-definition',
    'Level': 'level-section',
    'WordForms': 'forms-section',
}
_HISTORY_CLASSES = frozenset({
    'sf-ownership-history', 'sf-original-history-panel', 'sf-ownership-authority',
    'sf-archived-example', 'sf-archived-native-example',
})
_HISTORY_ATTRIBUTES = ('data-native-ownership-history', 'data-reviewed-source-comparison')
_PAIR_CLASSES = frozenset({'example-card', 'sf-sentence-pair'})
_ATTRIBUTE = re.compile(r'''([^\s=/<>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?''')
_CLASS_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*\Z')
_SCHEMA = 'derived-chunk-display-projection.v1'
_SUPPLEMENT_PREFIX = ('supplement-source', 'sf-source', 'sf-source', 'sf-supplemental-lexeme')


def _within(node, ancestor):
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _historical(node):
    while node is not None:
        if node.classes.intersection(_HISTORY_CLASSES) or any(
                name in node.attrs for name in _HISTORY_ATTRIBUTES):
            return True
        node = node.parent
    return False


def _one(nodes, label, *, optional=False):
    if optional and not nodes:
        return None
    if len(nodes) != 1:
        raise ValueError(f'accepted card needs one exact {label}; found {len(nodes)}')
    node = nodes[0]
    if node.closed is None or node.end is None:
        raise ValueError(f'accepted card has an unclosed {label}')
    return node


def _class_edits(page, tree, aliases, start, end):
    """Change actual class attributes, never class-like text inside attributes."""
    edits = []
    for node in tree.root.walk():
        if not start <= node.start < node.opened <= end or 'class' not in node.attrs:
            continue
        tag = page[node.start:node.opened]
        tag_name = re.match(r'<\s*[^\s/>]+', tag)
        if tag_name is None:
            raise ValueError('accepted card start-tag position is invalid')
        for attribute in _ATTRIBUTE.finditer(tag, tag_name.end()):
            value = attribute[2]
            if attribute[1].lower() != 'class' or value is None:
                continue
            quoted = value[0] in ('"', "'")
            original = value[1:-1] if quoted else value
            decoded = unescape(original)
            revised = re.sub(r'\S+', lambda match: aliases.get(match[0], match[0]), decoded)
            if revised != decoded:
                offset = node.start + attribute.start(2) + int(quoted)
                edits.append((offset, offset + len(original), revised))
    return edits


def _slice(page, tree, aliases, start, end):
    result = page[start:end]
    for left, right, replacement in reversed(_class_edits(page, tree, aliases, start, end)):
        result = result[:left - start] + replacement + result[right - start:]
    return result


def extract_fields(page: str, aliases: dict) -> dict:
    """Return current Definition, SimpleDefinition, Level, WordForms, Examples.

    The preview's duplicated front is excluded by anchoring the one vocab-back
    inside preview-back.  Missing optional fields are empty strings.  A current
    SF report outside the ordinary fields is appended to Definition in source
    order.  Supplemental cards retain the preceding Oxford source label,
    English definition, Chinese translation, and complete lexeme evidence as
    one exact slice with their report.
    """
    if not isinstance(page, str) or not isinstance(aliases, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and
            _CLASS_TOKEN.fullmatch(key) and _CLASS_TOKEN.fullmatch(value)
            for key, value in aliases.items()):
        raise ValueError('accepted card requires HTML and exact class aliases')
    tree = _Offsets(page, aliases)
    preview = _one([node for node in tree.root.walk()
                    if node.attrs.get('id') == 'preview-back'], 'preview-back')
    back = _one([node for node in preview.walk() if 'vocab-back' in node.classes
                 and not _historical(node)], 'vocab-back')
    fields, containers = {}, []
    for name, class_name in _FIELDS.items():
        section = _one([node for node in back.walk() if class_name in node.classes
                        and not _historical(node)], class_name, optional=name != 'Definition')
        content = None if section is None else _one(
            [node for node in section.children if 'field-content' in node.classes],
            class_name + ' field-content')
        fields[name] = '' if content is None else _slice(
            page, tree, aliases, content.opened, content.closed)
        if content is not None:
            containers.append(content)
    examples = _one([node for node in back.walk() if node.tag == 'ol'
                     and 'examples' in node.classes and not _historical(node)],
                    'ol.examples', optional=True)
    fields['Examples'] = '' if examples is None else _slice(
        page, tree, aliases, examples.opened, examples.closed)
    if examples is not None:
        containers.append(examples)
    notes = [node for node in back.walk() if 'personal-note' in node.classes
             and not _historical(node)]
    boundary = min((node.start for node in notes), default=back.closed)
    reports = [node for node in back.walk() if 'sf-report' in node.classes
               and not _historical(node) and not any(_within(node, owner) for owner in containers)]
    external = []
    for report in reports:
        if report.end is None or report.end > boundary:
            raise ValueError('current supplemental SF report must precede personal notes')
        if any(_within(report.parent, other) for other in reports):
            raise ValueError('current supplemental SF reports must not nest')
        start = report.start
        siblings = report.parent.children
        index = siblings.index(report)
        if index and 'sf-supplemental-lexeme' in siblings[index - 1].classes:
            prefix = siblings[max(0, index - len(_SUPPLEMENT_PREFIX)):index]
            if (len(prefix) != len(_SUPPLEMENT_PREFIX) or
                    any(class_name not in node.classes or _historical(node)
                        for node, class_name in zip(prefix, _SUPPLEMENT_PREFIX)) or
                    [node.tag for node in prefix] != ['p', 'p', 'p', 'details'] or
                    any(node.end is None for node in prefix)):
                raise ValueError('current supplemental SF report needs its complete source prefix')
            start = prefix[0].start
        external.append((start, report.end))
    # A changed layout must fail explicitly instead of silently dropping the
    # supplemental dictionary evidence again.  Already extracted fields and
    # complete external report slices own their nested content exactly once.
    for node in back.walk():
        if (node.classes.intersection({'supplement-source', 'sf-supplemental-lexeme'}) and
                not _historical(node) and not any(_within(node, owner) for owner in containers) and
                not any(start <= node.start < node.end <= end for start, end in external
                        if node.end is not None)):
            raise ValueError('current supplemental source evidence has no complete report slice')
    for start, end in external:
        fields['Definition'] += _slice(page, tree, aliases, start, end)
    return fields


class _Text(HTMLParser):
    """DOM text-node contents, without inventing newlines for br elements."""
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(markup)
        self.close()

    def handle_data(self, data):
        self.parts.append(data)


def _text(markup):
    return ''.join(_Text(markup).parts)


def _view(page, node, native_chinese):
    start = node.opened
    if native_chinese and node.children:
        first = node.children[0]
        # The runtime removes only a literal first-child 翻译 label, then one
        # leading space in its immediate text-node sibling.  No trim/normalize.
        if (first.start == start and first.tag == 'span' and
                'translate-tag' in first.classes and first.end is not None and
                _text(page[first.opened:first.closed]) == '翻译'):
            start = first.end
            remainder = page[start:node.closed]
            first_text = remainder.split('<', 1)[0]
            text = _text(remainder)
            if unescape(first_text).startswith(' '):
                return text[1:]
            return text
    return _text(page[start:node.closed])


def current_pairs(pagefields: dict) -> set[tuple[str, str]]:
    """Collect the exact active EN/CN keys used by the reviewed-chunk runtime."""
    if not isinstance(pagefields, dict) or not all(isinstance(value, str) for value in pagefields.values()):
        raise ValueError('current pair collection requires HTML fields')
    result = set()
    for field in pagefields.values():
        tree = _Offsets(field, {})
        for root in tree.root.walk():
            if not root.classes.intersection(_PAIR_CLASSES) or _historical(root):
                continue
            sf = 'sf-sentence-pair' in root.classes

            def own(class_name):
                for node in root.walk():
                    if class_name not in node.classes or _historical(node):
                        continue
                    parent = node
                    while parent is not None and not parent.classes.intersection(_PAIR_CLASSES):
                        parent = parent.parent
                    if parent is root:
                        if node.closed is None:
                            raise ValueError('current example has an unclosed bilingual text container')
                        return node
                return None

            en = own('sf-en' if sf else 'example-text')
            zh = own('sf-zh' if sf else 'example-translation')
            if en is not None and zh is not None:
                result.add((_view(field, en, False), _view(field, zh, not sf)))
    return result


def scoped_projection(pagefields: dict, full_verified_projection: dict) -> dict:
    """Subset an already fully verified projection to exact current field pairs.

    Complete pins and selected records are copied intact, including source
    comparisons and unmapped evidence.  This is selection, not certification;
    the caller must first verify the complete original sidecar's file SHA and
    runtime schema/hash/range proofs, and validate the resulting subset too.
    """
    if (not isinstance(full_verified_projection, dict) or
            full_verified_projection.get('schema') != _SCHEMA or
            not isinstance(full_verified_projection.get('records'), list) or
            not isinstance(full_verified_projection.get('pins'), dict)):
        raise ValueError('scoped projection requires the verified complete projection')
    pairs = current_pairs(pagefields)
    records, seen = [], set()
    for record in full_verified_projection['records']:
        if (not isinstance(record, dict) or not isinstance(record.get('english'), str) or
                not isinstance(record.get('translation'), str)):
            raise ValueError('projection record needs an exact bilingual pair')
        pair = (record['english'], record['translation'])
        if pair in seen:
            raise ValueError('verified projection repeats an exact display pair')
        seen.add(pair)
        if pair in pairs:
            records.append(record)
    subset = deepcopy({key: value for key, value in full_verified_projection.items() if key != 'records'})
    subset['records'] = deepcopy(records)
    return subset
