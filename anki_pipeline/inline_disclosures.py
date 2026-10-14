"""Restore live sense disclosures from a caller-pinned inline Definition.

Only original string slices are copied. This module neither reads a database
nor expands media: callers bind the two Definitions to the same note GUID and
verify their snapshots. Offsets are Python string offsets; hashes cover UTF-8.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .slim_apkg_content import Slices, _NAME, _TAG, _VOID, attributes

_HISTORY = frozenset({
    'sf-inline-history', 'sf-ownership-history', 'sf-ownership-authority',
    'sf-native-ownership-history', 'sf-original-history-panel',
    'residual-owner-history', 'sf-source-confirmation-history',
    'sf-semantic-resolution-history', 'sf-final-history',
    'sf-archived-example', 'sf-archived-native-example', 'sf-pending',
})
_HISTORY_ATTRS = ('data-native-ownership-history', 'data-reviewed-source-comparison')
_INTEREST = _HISTORY | frozenset({
    'sf-report', 'sf-sense', 'sf-panel', 'as-lazy', 'as-manifest',
})
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_OPEN = re.compile(r'<[\w:-]+\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*?>', re.I)


class DisclosureRestoreError(ValueError):
    """A current and baseline disclosure cannot be matched without guessing."""


@dataclass(frozen=True)
class RestoreResult:
    html: str
    regions: list[dict]


def _fail(message):
    raise DisclosureRestoreError('inline disclosures: ' + message)


def _digest(raw):
    return sha256(raw.encode('utf-8')).hexdigest()


def _attribute_history_ranges(raw):
    """Find rare history wrappers without materializing descendant spans."""
    if not any(name in raw for name in _HISTORY_ATTRS):
        return []
    stack, result = [], []
    for match in _TAG.finditer(raw):
        text = match[0]
        if text.startswith('<!--'):
            continue
        name = _NAME.match(text)
        closing, tag = bool(name[1]), name[2].lower()
        if closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == tag:
                    for _, start, historical in stack[index:]:
                        if historical:
                            result.append((start, match.end()))
                    del stack[index:]
                    break
            continue
        opening = _OPEN.match(text)[0]
        historical = any(name in opening for name in _HISTORY_ATTRS)
        if historical:
            attrs = attributes(opening)
            historical = any(name in attrs for name in _HISTORY_ATTRS)
        if tag in ('script', 'style') or tag in _VOID or opening.rstrip().endswith('/>'):
            if historical:
                result.append((match.start(), match.end()))
        else:
            stack.append((tag, match.start(), historical))
    if any(entry[2] for entry in stack):
        _fail('unclosed history wrapper')
    return result


def _ancestors(node):
    node = node.parent
    while node:
        yield node
        node = node.parent


def _historical(node, ranges):
    return (any(parent.classes & _HISTORY for parent in _ancestors(node)) or
            any(start < node.start < end for start, end in ranges))


def _direct(node, parent):
    return node.direct_parent == parent.start


def _summary(node):
    values = [child for child in node.children if child.tag == 'summary' and _direct(child, node)]
    if len(values) != 1:
        _fail('target disclosure has no unique direct summary')
    return values[0]


@dataclass(frozen=True)
class _Region:
    kind: str
    start: int
    end: int
    key: tuple


def _targets(raw):
    try:
        tree = Slices(raw, interests=_INTEREST)
    except (ValueError, AttributeError) as error:
        _fail('malformed selected HTML: ' + str(error))
    ranges = _attribute_history_ranges(raw)
    reports = [node for node in tree.nodes if 'sf-report' in node.classes and not _historical(node, ranges)]
    report_ids = {node.start: index for index, node in enumerate(reports)}
    result = []
    for node in tree.nodes:
        kinds = node.classes & {'sf-pending', 'sf-panel'}
        if not kinds or _historical(node, ranges):
            continue
        if len(kinds) != 1:
            _fail('ambiguous target classes')
        kind = next(iter(kinds))
        report = next((parent for parent in _ancestors(node) if 'sf-report' in parent.classes), None)
        if report is None or report.start not in report_ids:
            _fail('live target has no current sense report')
        if kind == 'sf-pending':
            if node.tag != 'details':
                _fail('pending target is not details')
            owner, summary = node, _summary(node)
            start = summary.end
        else:
            owner = node.parent
            if (node.tag != 'div' or owner is None or owner.tag != 'details' or
                    'sf-sense' not in owner.classes or not _direct(node, owner)):
                _fail('sense panel is not a direct child of its sense')
            summary = _summary(owner)
            if node.start < summary.end:
                _fail('sense panel precedes its summary')
            panels = [child for child in owner.children if 'sf-panel' in child.classes and _direct(child, owner)]
            if len(panels) != 1:
                _fail('sense has no unique direct panel')
            start = node.opened
        if node.closed is None or node.end is None or start > node.closed:
            _fail('unclosed disclosure body')
        key = (kind, report_ids[report.start], raw[report.start:report.opened],
               raw[owner.start:summary.end], raw[node.start:node.opened], raw[node.closed:node.end])
        result.append(_Region(kind, start, node.closed, key))
    for previous, following in zip(result, result[1:]):
        if previous.end > following.start:
            _fail('overlapping current disclosure targets')
    return result, tree


def _placeholder(raw, node, kind):
    declared = node.attrs.get('data-as-kind')
    if node.tag != 'div' or declared not in {'detail', 'panel'} or (kind == 'sf-pending' and declared != 'detail'):
        _fail('unsupported lazy disclosure kind')
    manifests = [child for child in node.children if 'as-manifest' in child.classes and _direct(child, node)]
    if len(manifests) != 1:
        _fail('lazy disclosure has no unique direct manifest')
    manifest = manifests[0]
    if manifest.tag != 'script' or manifest.attrs.get('type') != 'application/json':
        _fail('invalid lazy manifest element')
    if raw[node.opened:manifest.start].strip() or raw[manifest.end:node.closed].strip():
        _fail('unexpected content beside lazy manifest')
    try:
        value = json.loads(raw[manifest.opened:manifest.closed])
    except (ValueError, TypeError) as error:
        _fail('invalid lazy manifest JSON: ' + str(error))
    if not isinstance(value, dict) or value.get('schema') != 'anki-slim-segments.v1':
        _fail('unsupported lazy manifest schema')
    parts, total = value.get('parts'), value.get('total')
    if not isinstance(parts, list) or not parts or type(total) is not int or total <= 0:
        _fail('invalid lazy manifest parts or total')
    count = 0
    for part in parts:
        if not isinstance(part, dict):
            _fail('invalid lazy manifest part')
        pin, units = part.get('sha256'), part.get('count')
        if (not isinstance(pin, str) or _SHA.fullmatch(pin) is None or
                part.get('src') != '_as_' + pin[:24] + '.js' or
                type(units) is not int or units <= 0):
            _fail('invalid lazy manifest pin or count')
        count += units
    if count != total or (declared == 'detail' and total != 1):
        _fail('lazy manifest count differs from total')
    return manifest


def _verify_shell(current, baseline, region, current_tree, baseline_region, baseline_tree):
    current_body = current[region.start:region.end]
    baseline_body = baseline[baseline_region.start:baseline_region.end]
    baseline_nodes = [node for node in baseline_tree.nodes if baseline_region.start <= node.start < baseline_region.end]
    if any(node.classes & {'as-lazy', 'as-manifest'} for node in baseline_nodes):
        _fail('baseline disclosure must be completely inline, not lazy')
    nodes = [node for node in current_tree.nodes if region.start <= node.start < region.end]
    lazy = [node for node in nodes if 'as-lazy' in node.classes]
    owned_manifests = set()
    for node in lazy:
        owned_manifests.add(_placeholder(current, node, region.kind).start)
    if any('as-manifest' in node.classes and node.start not in owned_manifests for node in nodes):
        _fail('orphan lazy manifest in disclosure')
    if not lazy:
        if current_body != baseline_body:
            _fail('inline disclosure differs from baseline without a lazy placeholder')
        return
    # Match exact static spans around complete lazy holes. Year buttons/counts
    # and surviving inline text must still match, without semantic guessing.
    lazy_starts = {node.start for node in lazy}
    outer = [node for node in lazy if not any(parent.start in lazy_starts for parent in _ancestors(node))]
    spans, cursor = [], region.start
    for node in outer:
        if node.end > region.end:
            _fail('lazy placeholder crosses target boundary')
        spans.append(current[cursor:node.start])
        cursor = node.end
    spans.append(current[cursor:region.end])
    if not baseline_body.startswith(spans[0]) or not baseline_body.endswith(spans[-1]):
        _fail('inline disclosure shell differs from baseline')
    left, right = len(spans[0]), len(baseline_body) - len(spans[-1])
    if left > right:
        _fail('inline disclosure shell overlaps')
    for span in spans[1:-1]:
        if not span:
            continue
        position = baseline_body.find(span, left, right)
        if position < 0 or baseline_body.find(span, position + 1, right) >= 0:
            _fail('inline disclosure shell cannot be uniquely matched')
        left = position + len(span)


def restore_definition_disclosures(current_html: str, baseline_html: str) -> RestoreResult:
    """Copy all matched live pending/panel bodies, or reject the whole change.

    Historical disclosures are opaque unless inside a body being restored.
    Bytes outside selected bodies stay untouched. ``regions`` records only
    changed bodies and supplies their exact inverse and UTF-8 SHA-256 proofs.
    """
    if not isinstance(current_html, str) or not isinstance(baseline_html, str):
        _fail('Definitions must be strings')
    current, current_tree = _targets(current_html)
    baseline, baseline_tree = _targets(baseline_html)
    if len(current) != len(baseline):
        _fail('current and baseline target counts differ')
    edits = []
    for ordinal, (target, source) in enumerate(zip(current, baseline)):
        if target.key != source.key:
            _fail('target summary, order or structure differs at region ' + str(ordinal))
        _verify_shell(current_html, baseline_html, target, current_tree, source, baseline_tree)
        old, replacement = current_html[target.start:target.end], baseline_html[source.start:source.end]
        if old != replacement:
            edits.append((ordinal, target, source, old, replacement))
    pieces, regions, cursor, revised_length = [], [], 0, 0
    for ordinal, target, source, old, replacement in edits:
        unchanged = current_html[cursor:target.start]
        pieces.extend((unchanged, replacement))
        revised_length += len(unchanged)
        regions.append({
            'kind': target.kind, 'ordinal': ordinal,
            'current_start': target.start, 'current_end': target.end,
            'revised_start': revised_length, 'revised_end': revised_length + len(replacement),
            'baseline_start': source.start, 'baseline_end': source.end,
            'original': old, 'current_sha256': _digest(old), 'baseline_sha256': _digest(replacement),
        })
        revised_length += len(replacement)
        cursor = target.end
    pieces.append(current_html[cursor:])
    return RestoreResult(''.join(pieces), regions)
