"""Source-bound, reversible sense reports for compound dictionary cards.

Each original dictionary block has a physical location, source and an ordered
slice of the card's global senses. Headword headings, frequency panels and
source notices between those blocks remain byte for byte unchanged. Rendering
does not classify or redistribute occurrences: it consumes the same immutable
global report and retains its denominator and snapshot identity.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re

from . import sense_frequency as sf


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@dataclass
class _Node:
    tag: str
    attrs: dict
    start: int
    end: int | None = None
    opening_end: int | None = None
    closing_start: int | None = None
    parent: _Node | None = None
    children: list = field(default_factory=list)

    def text(self):
        return ''.join(child if isinstance(child, str) else child.text() for child in self.children)

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()


class _Page(HTMLParser):
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _END = re.compile(r'</[^>]*>')

    def __init__(self, page, aliases):
        super().__init__(convert_charrefs=True)
        self.page, self.aliases = page, aliases
        self.lines = [0] + [match.end() for match in re.finditer('\n', page)]
        # Compound cards can contain thousands of unrelated exam examples.
        # Keep only the answer shell, component headings and dictionary trees;
        # ordinary markup needs a tiny stack entry, not a second full-page DOM.
        self.nodes, self.stack, self.back, self.capture, self.counts = [], [], None, None, []
        self.feed(page)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def classes(self, node):
        return {self.aliases.get(value, value) for value in node.attrs.get('class', '').split()}

    def handle_starttag(self, tag, attrs):
        start = self.position()
        attrs = dict(attrs)
        if self.back is not None and 'data-occurrences' in attrs:
            value = attrs['data-occurrences']
            if not isinstance(value, str) or not re.fullmatch(r'\d+', value):
                raise ValueError('original component physical frequency is invalid')
            self.counts.append(int(value))
        node, starts_capture = None, False
        if attrs.get('id') == 'preview-back':
            node = _Node(tag, attrs, start)
            self.back = node
            self.nodes.append(node)
        elif self.back is not None and (self.capture is not None or
                'dictionary-definition' in {self.aliases.get(value, value)
                                            for value in attrs.get('class', '').split()} or
                (tag == 'h3' and not attrs)):
            parent = self.stack[-1][1] if self.capture is not None else self.back
            node = _Node(tag, attrs, start, parent=parent)
            parent.children.append(node)
            if self.capture is None:
                self.capture, starts_capture = node, True
        if tag in self._VOID:
            if node is not None:
                node.end = start + len(self.get_starttag_text())
            if starts_capture:
                self.capture = None
        else:
            if node is not None:
                node.opening_end = start + len(self.get_starttag_text())
            self.stack.append((tag, node))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            _, node = self.stack.pop()
            if node is not None:
                node.end = self.position() + len(self.get_starttag_text())
                if node is self.capture:
                    self.capture = None
                if node is self.back:
                    self.back = None

    def handle_endtag(self, tag):
        # Non-critical historical source markup can have optional end tags.
        # Critical dictionary/answer nodes must still have their real endings.
        index = next((i for i in range(len(self.stack) - 1, -1, -1)
                      if self.stack[i][0] == tag), None)
        if index is None:
            return
        # Match in place. Slicing the remaining multi-megabyte card for every
        # closing example span would turn this scan into quadratic copying.
        closing = self._END.match(self.page, self.position())
        if closing is None:
            raise ValueError('invalid closing markup in component source')
        _, node = self.stack[index]
        if node is not None:
            node.end = closing.end()
            node.closing_start = closing.start()
        if any(item is self.capture for _, item in self.stack[index:]):
            self.capture = None
        if any(item is self.back for _, item in self.stack[index:]):
            self.back = None
        del self.stack[index:]

    def handle_data(self, data):
        if self.capture is not None and self.stack:
            node = self.stack[-1][1]
            if node is not None:
                node.children.append(data)


@dataclass(frozen=True)
class DefinitionComponent:
    """An exact original block and its non-overlapping global sense slice."""
    index: int
    start: int
    end: int
    html: str
    source: str
    headword: str | None
    sense_start: int
    senses: tuple[tuple[str, str], ...]
    opening_html: str
    closing_html: str

    @property
    def sense_count(self):
        return len(self.senses)


@dataclass(frozen=True)
class ComponentPlan:
    page_sha256: str
    components: tuple[DefinitionComponent, ...]
    provenance: tuple[dict, ...]
    declared_counts: tuple[int, ...] = ()

    @property
    def senses(self):
        return tuple(sense for component in self.components for sense in component.senses)


def plan_components(page, components, aliases=None):
    """Validate provenance and locate answer-side blocks by character offsets.

    ``components`` is the original ``definition_provenance.components`` list.
    Class aliases map compressed names to the original renderer names. Unlike
    text replacement by uniqueness, physical offsets distinguish identical
    blocks and never select a matching fragment on the front of the card.
    """
    if not isinstance(page, str) or not isinstance(components, list) or not components:
        raise ValueError('component insertion needs an original page and provenance list')
    parsed = _Page(page, aliases or {})
    backs = [node for node in parsed.nodes if node.attrs.get('id') == 'preview-back']
    if len(backs) != 1 or backs[0].end is None:
        raise ValueError('component insertion needs exactly one complete answer side')
    back = backs[0]
    definitions = [node for node in back.walk() if 'dictionary-definition' in parsed.classes(node)]
    if len(definitions) != len(components):
        raise ValueError('dictionary component count differs from source provenance')
    headings = [node for node in back.walk() if node.tag == 'h3' and not node.attrs]
    output, cursor, previous_end = [], 0, back.start
    for index, (node, expected) in enumerate(zip(definitions, components)):
        if (node.end is None or node.opening_end is None or node.closing_start is None or
                node.opening_end > node.closing_start or node.start < previous_end):
            raise ValueError('dictionary component markup is unterminated or overlaps')
        previous_end = node.end
        original = page[node.start:node.end]
        source = node.attrs.get('data-dictionary', 'unknown')
        candidates = [heading for heading in headings if heading.start < node.start]
        headword = candidates[-1].text().strip() if candidates else None
        senses = []
        for row in node.walk():
            if 'sense-row' not in parsed.classes(row):
                continue
            pos = next((child for child in row.walk() if 'sense-pos' in parsed.classes(child)), None)
            text = next((child for child in row.walk() if 'sense-text' in parsed.classes(child)), None)
            if text is not None and text.text().strip():
                senses.append((pos.text().strip() if pos else '', text.text().strip()))
        if not senses:
            senses = [('', row.text().strip()) for row in node.walk()
                      if 'sense-unlabelled' in parsed.classes(row) and row.text().strip()]
        if (not isinstance(expected, dict) or expected.get('component_index') != index or
                type(expected.get('component_index')) is not int or
                expected.get('sense_start') != cursor or type(expected.get('sense_start')) is not int or
                expected.get('sense_count') != len(senses) or type(expected.get('sense_count')) is not int or
                expected.get('source') != source or expected.get('html_sha256') != _sha(original)):
            raise ValueError('dictionary component source, hash or global sense order changed')
        if 'headword' in expected and expected['headword'] != headword:
            raise ValueError('dictionary component headword changed')
        if len(definitions) > 1 and (not headword or 'headword' not in expected):
            raise ValueError('compound component needs its original headword provenance')
        output.append(DefinitionComponent(index, node.start, node.end, original, source,
                                          headword, cursor, tuple(senses),
                                          page[node.start:node.opening_end],
                                          page[node.closing_start:node.end]))
        cursor += len(senses)
    return ComponentPlan(_sha(page), tuple(output), tuple(deepcopy(components)), tuple(parsed.counts))


def _validate_report(plan, report):
    if report.get('schema') != sf.SCHEMA or not isinstance(report.get('snapshot_id'), str) or not report['snapshot_id']:
        raise ValueError('component report requires a real global sense snapshot')
    if report.get('definition_provenance', {}).get('components') != list(plan.provenance):
        raise ValueError('component report is bound to different dictionary provenance')
    names = sorted({component.source for component in plan.components})
    source = names[0] if len(names) == 1 else 'mixed'
    if report.get('definition_source') != source:
        raise ValueError('component report has a different dictionary source')
    senses = report.get('senses')
    if not isinstance(senses, list) or len(senses) != len(plan.senses):
        raise ValueError('component report does not cover the complete global sense list')
    identities, physical, assigned = set(), set(), 0
    for ordinal, (sense, expected) in enumerate(zip(senses, plan.senses)):
        if ((sense.get('pos'), sense.get('text')) != expected or
                sense.get('ordinal') != ordinal or type(sense.get('ordinal')) is not int):
            raise ValueError('component report sense order or displayed meaning changed')
        identity = sense.get('sense_id')
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('component report sense identities are not unique')
        identities.add(identity)
        rows, count = sense.get('occurrences'), sense.get('count')
        if not isinstance(rows, list) or type(count) is not int or count != len(rows):
            raise ValueError('component report count differs from physical occurrences')
        years = Counter()
        for row in rows:
            _take_occurrence(row, physical)
            if 'sense_id' in row and row['sense_id'] != identity:
                raise ValueError('physical occurrence belongs to another global sense')
            years[row['year']] += 1
        expected_years = [{'year': year, 'count': years[year]} for year in sorted(years, reverse=True)]
        if sense.get('years') != expected_years:
            raise ValueError('component report years do not reconcile with physical occurrences')
        assigned += count
    pending, pending_count = report.get('pending'), report.get('pending_count')
    if not isinstance(pending, list) or type(pending_count) is not int or len(pending) != pending_count:
        raise ValueError('component pending count does not reconcile')
    for row in pending:
        _take_occurrence(row, physical)
        if row.get('sense_id') is not None:
            raise ValueError('pending occurrence already belongs to a sense')
    if type(report.get('total')) is not int or report['total'] != assigned + pending_count:
        raise ValueError('component counts do not reconcile with the global physical total')
    if plan.declared_counts and report['total'] != sum(plan.declared_counts):
        raise ValueError('component report total differs from the original physical word frequency')


def _take_occurrence(row, physical):
    identity = row.get('occurrence_id')
    if not isinstance(identity, str) or not identity or identity in physical or type(row.get('year')) is not int:
        raise ValueError('physical occurrence identity or year is invalid or duplicated')
    physical.add(identity)


def _markers(component):
    identity = f'{component.index}:{_sha(component.html)}'
    return (f'<!--sense-component:start:{identity}-->', f'<!--sense-component:end:{identity}-->')


def inject_component_report(page, plan, report):
    """Replace nonempty blocks' contents, retaining their original outer shells.

    Existing zero-sense dictionary notices stay as their exact original HTML.
    The first rendered component owns the global pending section. Every report
    continues to expose the same real ``data-snapshot`` and global denominator.
    Literal wrapper tags retain dictionary classes, sources and reviewed
    headings used by the shared card runtime, without adding another title.
    """
    if not isinstance(plan, ComponentPlan) or _sha(page) != plan.page_sha256:
        raise ValueError('component source page changed after the insertion plan')
    if 'sense-component:start:' in page or 'data-sense-components-' in page or 'data-sense-frequency=' in page:
        raise ValueError('component source already contains a sense report')
    _validate_report(plan, report)
    rendered = [component for component in plan.components if component.sense_count]
    if not rendered:
        return page
    first = rendered[0].index
    replacements = []
    for component in rendered:
        view = {**report, 'senses': report['senses'][component.sense_start:
                                                   component.sense_start + component.sense_count]}
        if component.index != first:
            view.update(pending=[], pending_count=0)
        block = sf.render_report(view)
        if report['pending_count'] and component.index != first:
            block = block.replace('<p class="sf-hint">真题出现次数',
                                  '<p class="sf-hint">已核对次数', 1)
        opening, closing = _markers(component)
        replacements.append((component.start, component.end,
                             opening + component.opening_html + block + component.closing_html + closing))
    for start, end, revised in reversed(replacements):
        page = page[:start] + revised + page[end:]
    if page.count('</head>') != 1 or page.count('</body>') != 1:
        raise ValueError('component source needs one complete head and body')
    templates = Path(sf.__file__).with_name('templates')
    css = (templates / 'sense-frequency.css').read_text(encoding='utf-8')
    script = (templates / 'sense-frequency.js').read_text(encoding='utf-8')
    return page.replace('</head>', '<style data-sense-components-style>' + css + '</style></head>', 1).replace(
        '</body>', '<script data-sense-components-script>' + script + '</script></body>', 1)


def remove_component_report(page, plan):
    """Restore exact original blocks and assert the entire original page hash."""
    if not isinstance(plan, ComponentPlan):
        raise ValueError('component inverse requires the original insertion plan')
    rendered = [component for component in plan.components if component.sense_count]
    if not rendered:
        if _sha(page) != plan.page_sha256:
            raise ValueError('unchanged zero-sense page differs from original source')
        return page
    if page.count('<!--sense-component:start:') != len(rendered) or page.count('<!--sense-component:end:') != len(rendered):
        raise ValueError('component inverse markers do not cover original blocks exactly once')
    for component in rendered:
        opening, closing = _markers(component)
        if page.count(opening) != 1 or page.count(closing) != 1:
            raise ValueError('component inverse identity differs from source block')
        start, end = page.index(opening), page.index(closing)
        if end < start:
            raise ValueError('component inverse markers are out of order')
        page = page[:start] + component.html + page[end + len(closing):]
    for tag in ('style', 'script'):
        page, count = re.subn(r'<' + tag + r' data-sense-components-' + tag + r'>.*?</' + tag + r'>',
                              '', page, flags=re.S)
        if count != 1:
            raise ValueError('component inverse resources are missing or duplicated')
    if _sha(page) != plan.page_sha256:
        raise ValueError('unrelated page bytes changed during component rendering')
    return page
