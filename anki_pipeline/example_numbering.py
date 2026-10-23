"""Number current example rows without changing source or occurrence identities."""
import re

HISTORY_CLASSES = frozenset({
    'sf-inline-history', 'sf-ownership-history', 'sf-ownership-authority',
    'sf-native-ownership-history', 'sf-original-history-panel', 'residual-owner-history',
    'sf-source-confirmation-history', 'sf-semantic-resolution-history', 'sf-final-history',
    'sf-archived-example', 'sf-archived-native-example', 'sf-pending',
    'sf-catalog-revision',
})


def _history_marker(node):
    return (node.classes & HISTORY_CLASSES or 'data-native-ownership-history' in node.attrs
            or 'data-reviewed-source-comparison' in node.attrs)


def numbering_edits(markup, aliases=None, removed_ranges=()):
    # Import only on use: the offset parser also uses the packaging module.
    from .native_example_usage import _Offsets
    tree = _Offsets(markup, aliases or {})
    counters, edits = {}, []
    for node in tree.root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes:
            continue
        ancestors, parent = [], node.parent
        while parent is not None:
            ancestors.append(parent); parent = parent.parent
        if any(_history_marker(part) for part in [node, *ancestors]):
            continue
        if any(part.tag == 'li' and 'example-card' in part.classes for part in ancestors):
            continue
        list_owner = next((part for part in ancestors if part.tag == 'ol' and 'examples' in part.classes), node.parent)
        visibility = [node]
        for part in ancestors:
            if part is list_owner:
                break
            visibility.append(part)
        if (any('hidden' in part.attrs or re.search(r'(?:^|;)\s*display\s*:\s*none\b', part.attrs.get('style') or '', re.I)
                for part in visibility)
                or any(start <= node.start and node.end is not None and node.end <= end for start, end in removed_ranges)):
            continue
        key = id(list_owner)
        counters[key] = counters.get(key, 0) + 1
        badges = [part for part in node.walk() if 'index-tag' in part.classes
                  and not any(_history_marker(parent) for parent in _ancestors(part, node))]
        if not badges:
            continue
        if len(badges) != 1 or badges[0].closed is None:
            raise ValueError('current example has an ambiguous ordinal badge')
        badge = badges[0]; original = markup[badge.opened:badge.closed]
        if not re.fullmatch(r'\s*[0-9]+\s*', original):
            raise ValueError('current example ordinal must contain only digits')
        revised = str(counters[key])
        if original != revised:
            edits.append((badge.opened, badge.closed, revised))
    return edits


def _ancestors(node, stop):
    node = node.parent
    while node is not None and node is not stop:
        yield node; node = node.parent


def renumber_examples(markup, aliases=None):
    result = markup
    for start, end, revised in reversed(numbering_edits(markup, aliases)):
        result = result[:start] + revised + result[end:]
    return result
