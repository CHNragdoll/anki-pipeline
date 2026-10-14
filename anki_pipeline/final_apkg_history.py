"""Materialize only the browser-selected sentence from an ownership archive.

Selection and inert copying mirror ``installInlineHistory`` in accepted final-v2
``library-preview.js``. An absent archive sentence may additionally use an exact
SHA-pinned original parent page identified in the retained audit authority.
The caller owns reading/pinning archive bytes and any
optional offline evidence storage.  This module neither fetches nor writes.
Only real history anchors inside ownership disclosures are replaced; all other
input bytes, including the complete outer audit explanation, remain unchanged.
"""
from dataclasses import dataclass, field
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit


_PATH = re.compile(
    r'/(?:exam-usage-policy-20261012/full-(?:2026|2027)-v4|'
    r'residual-optimization-20261013/engineering/preview-own/root-full-preview-v1/(?:redbook|redbook2027)|'
    r'source-confirmations-20261014/cards-own/preview-v1/(?:redbook|redbook2027)|'
    r'eleven-resolution-20261014/preview-own/final-v2/(?:redbook|redbook2027))'
    r'/history/[a-f0-9]{64}\.html\Z')
_BAD_URL = re.compile(r'[\x00-\x20\x7f\\%]')
_PARENT_PATH = re.compile(
    r'/(?:sense-frequency-20261011/(?:[a-zA-Z0-9_-]+/)*|'
    r'exam-usage-policy-20261012/full-(?:2026|2027)-v4/|'
    r'residual-optimization-20261013/engineering/preview-own/root-full-preview-v1/(?:redbook|redbook2027)/|'
    r'source-confirmations-20261014/cards-own/preview-v1/(?:redbook|redbook2027)/|'
    r'eleven-resolution-20261014/preview-own/final-v2/(?:redbook|redbook2027)/)'
    r'web-preview/[a-f0-9]{64}/cards/[a-f0-9]{64}\.html\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_HISTORICAL = frozenset(('sf-ownership-history', 'sf-ownership-authority', 'sf-original-history-panel',
                         'sf-archived-example', 'sf-archived-native-example'))
_SAFE_CLASS = re.compile(r'[a-zA-Z0-9_\s-]*\Z')
_SAFE_TAGS = frozenset(('article section div p span mark strong em b i u s br hr small sub sup '
                        'table thead tbody tr th td dl dt dd ol ul li code pre details summary a').split())
_SAFE_ATTRS = ('class', 'data-chunk-side', 'data-chunk-ids', 'data-sf-year')
_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_MAX_ARCHIVE = 20_000_000


class HistoryError(ValueError):
    """A history cannot be uniquely and safely reproduced; no output is returned."""


class _RecordMatchError(HistoryError):
    def __init__(self, count):
        self.count = count
        super().__init__(f'original sentence matched {count} records; unique match required')


@dataclass
class _Node:
    tag: str
    attrs: dict
    parent: object
    start: int
    end: int | None = None
    foreign: bool = False
    children: list = field(default_factory=list)

    @property
    def classes(self):
        return self.attrs.get('class', '').split()

    @property
    def text(self):
        if self.tag == 'template':
            return ''
        return ''.join(child.text if isinstance(child, _Node) else child for child in self.children)

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                # HTML template children belong to its separate .content fragment
                # and are not descendants for querySelectorAll/textContent.
                if child.tag != 'template':
                    yield from child.walk()


class _Tree(HTMLParser):
    """Detached parsing with exact source offsets; evidence is never evaluated."""
    CDATA_CONTENT_ELEMENTS = ('script', 'style', 'textarea', 'title')
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.lines = [0] + [i + 1 for i, char in enumerate(text) if char == '\n']
        self.root = _Node('', {}, None, 0, len(text))
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        # HTML DOM keeps the first duplicate attribute, not the last one.
        attributes = {}
        for key, value in attrs:
            if key not in attributes:
                attributes[key] = '' if value is None else value
        parent = self.stack[-1]
        start = self.position()
        node = _Node(tag, attributes, parent, start,
                     foreign=parent.foreign or tag in ('svg', 'math'))
        parent.children.append(node)
        if tag in _VOID:
            node.end = start + len(self.get_starttag_text())
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag not in _VOID and not self.stack[-1].foreign and tag not in ('svg', 'math'):
            raise HistoryError('history contains a non-HTML self-closing element')
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag and self.stack[-1].foreign:
            self.stack.pop().end = self.position() + len(self.get_starttag_text())

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                end = self.text.find('>', self.position())
                if end < 0:
                    raise HistoryError('unterminated history closing tag')
                self.stack[index].end = end + 1
                del self.stack[index:]
                break

    def handle_data(self, value):
        if self.stack[-1].tag in ('textarea', 'title'):
            value = unescape(value)
        self.stack[-1].children.append(value)


def _direct(parent, *, class_name=None, tag=None):
    return [child for child in parent.children if isinstance(child, _Node) and
            (class_name is None or class_name in child.classes) and
            (tag is None or child.tag == tag)]


def _one(parent, label, *, class_name=None, tag=None):
    found = _direct(parent, class_name=class_name, tag=tag)
    if len(found) != 1 or found[0].end is None:
        raise HistoryError(label + ' must be one complete direct element')
    return found[0]


def _after_prefix(node, prefix):
    text = node.text
    if not text.startswith(prefix) or len(text) <= len(prefix):
        raise HistoryError('original history field is absent or incorrectly formatted')
    return text[len(prefix):]


def _identity(details):
    reason = _after_prefix(_one(details, 'original audit reason', class_name='sf-history-old-reason'),
                           '原审核完整说明：')
    markers = [node for node in _direct(details, class_name='sf-source')
               if node.text.startswith('原先目标标记：')]
    if markers:
        if len(markers) != 1:
            raise HistoryError('original target position is not unique')
        marks = [node for node in markers[0].walk() if node.tag == 'mark']
        if len(marks) != 1 or marks[0].end is None:
            raise HistoryError('original target mark is not unique')
        target = marks[0].text
        source = _after_prefix(markers[0], '原先目标标记：' + target + ' · ')
    else:
        example = _one(details, 'original example', class_name='sf-example')
        source = _one(example, 'original example source', class_name='sf-source').text
        marks = [node for node in example.walk() if 'target-word' in node.classes]
        if len(marks) != 1 or marks[0].end is None:
            raise HistoryError('original target mark is not unique')
        target = marks[0].text
    if not source or not target:
        raise HistoryError('original source or target is empty')
    return reason, source, target


def _origin(url):
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise HistoryError('history requires an unauthenticated HTTP(S) origin')
    return url.scheme, url.hostname, url.port or (443 if url.scheme == 'https' else 80)


def _validated_path(value, base_url, pattern):
    if not isinstance(value, str) or not value or _BAD_URL.search(value):
        raise HistoryError('invalid history URL')
    try:
        base = urlsplit(urljoin('http://localhost/', base_url))
        url = urlsplit(urljoin(base.geturl(), value))
        if (_origin(url) != _origin(base) or url.query or url.fragment or
                not pattern.fullmatch(url.path)):
            raise HistoryError('history URL is outside same-origin frozen archive directories')
        return url.path
    except (TypeError, ValueError) as error:
        if isinstance(error, HistoryError):
            raise
        raise HistoryError('invalid history URL') from error


def _archive_path(value, base_url):
    return _validated_path(value, base_url, _PATH)


def _historical(node):
    while node is not None:
        if (_HISTORICAL.intersection(node.classes) or
                'data-native-ownership-history' in node.attrs or
                'data-reviewed-source-comparison' in node.attrs):
            return True
        node = node.parent
    return False


def _text_range(parent, target):
    offset = 0
    found = None
    def visit(node):
        nonlocal offset, found
        if isinstance(node, str):
            offset += len(node)
            return
        if node is target:
            found = (offset, offset + len(node.text))
        for child in node.children:
            visit(child)
    visit(parent)
    return found


def _selected_record(tree, expected, *, source_parent=False, english=None, target_range=None,
                     option_label=None):
    reason, source, target = expected
    matches = []
    for article in tree.root.walk():
        wanted = 'sf-example' if source_parent else 'sf-archived-example'
        if wanted not in article.classes or (source_parent and _historical(article)):
            continue
        sources = _direct(article, class_name='sf-source')
        reasons = _direct(article, class_name='sf-reason')
        if (len(sources) == len(reasons) == 1 and sources[0].text == source and
                reasons[0].text == '义项依据：' + reason):
            if source_parent:
                pairs = _direct(article, class_name='sf-sentence-pair')
                ens = _direct(pairs[0], class_name='sf-en') if len(pairs) == 1 else []
                marks = [node for node in ens[0].walk() if 'target-word' in node.classes] if len(ens) == 1 else []
                if len(ens) != 1 or len(marks) != 1:
                    continue
                if option_label is None:
                    if ens[0].text != english or _text_range(ens[0], marks[0]) != target_range:
                        continue
                else:
                    # Accepted reading presentation inserts the physical option
                    # into its stem. Only an explicitly identified option may use
                    # this exact unique displacement; body text cannot do so.
                    if not source.endswith('选项' + option_label) or ens[0].text.count(english) != 1:
                        continue
                    displacement = ens[0].text.index(english)
                    displayed = tuple(displacement + offset for offset in target_range)
                    if _text_range(ens[0], marks[0]) != displayed:
                        continue
            matches.append(article)
    if len(matches) != 1:
        raise _RecordMatchError(len(matches))
    if matches[0].end is None:
        raise HistoryError('original sentence record is unclosed')
    record = matches[0]
    pair = _one(record, 'original bilingual pair', class_name='sf-sentence-pair')
    en = _one(pair, 'original English', class_name='sf-en')
    zh = _one(pair, 'original Chinese', class_name='sf-zh')
    marks = [node for node in en.walk() if 'target-word' in node.classes]
    if not en.text or not zh.text or len(marks) != 1 or marks[0].text != target:
        raise HistoryError('original bilingual sentence or target does not match')
    return record


def _source_parent_pin(details, base_url, target):
    try:
        authority = _one(details, 'original audit authority', class_name='sf-ownership-authority')
        value = json.loads(_one(authority, 'original audit authority JSON', tag='pre').text)
        if not isinstance(value, dict):
            raise HistoryError('original authority must be a JSON object')
        url, pin = value['source_parent_page_url'], value['source_parent_page_sha256']
        if not isinstance(pin, str) or not _SHA.fullmatch(pin):
            raise HistoryError('source-parent HTML SHA256 is invalid')
        audit = value['exclusion_authority']['audit']
        english = audit['english']
        identity = audit['source_identity']
        english_sha, span = identity['english_hash'], identity['target_range']
        if (not isinstance(english, str) or not isinstance(english_sha, str) or
                not _SHA.fullmatch(english_sha) or hashlib.sha256(english.encode('utf-8')).hexdigest() != english_sha or
                not isinstance(span, list) or len(span) != 2 or
                any(type(index) is not int for index in span) or
                not 0 <= span[0] < span[1] <= len(english) or english[span[0]:span[1]] != target):
            raise HistoryError('source-parent audited English or target range proof is invalid')
        option = re.fullmatch(r'kaoyan:\d{4}-\d{2}:q-\d+-\d+:([A-D]):new:\d+',
                              identity.get('sentence_id', ''))
        return _validated_path(url, base_url, _PARENT_PATH), pin, english, tuple(span), option[1] if option else None
    except (KeyError, TypeError, json.JSONDecodeError, HistoryError) as error:
        raise HistoryError('original sentence matched 0 records; valid pinned source-parent proof is required') from error


def _html_evidence(tree):
    matches = []
    for node in tree.root.walk():
        if node.tag != 'details':
            continue
        summaries = _direct(node, tag='summary')
        if len(summaries) == 1 and re.sub(r'\s', '', summaries[0].text) == '完整原HTML证据':
            matches.append(node)
    if len(matches) != 1:
        raise HistoryError('complete original HTML evidence is not unique')
    return _one(matches[0], 'complete original HTML evidence', tag='pre').text


def _safe_copy(node):
    if isinstance(node, str):
        return escape(node)
    if node.foreign or node.tag not in _SAFE_TAGS:
        return ''
    attributes = []
    for name in _SAFE_ATTRS:
        value = node.attrs.get(name)
        if value is not None and (name != 'class' or _SAFE_CLASS.fullmatch(value)):
            attributes.append(' ' + name + '="' + escape(value, quote=True) + '"')
    opened = '<' + node.tag + ''.join(attributes) + '>'
    if node.tag in _VOID:
        return opened
    return opened + ''.join(_safe_copy(child) for child in node.children) + '</' + node.tag + '>'


class HistoryMaterializer:
    """Cache immutable archives while selecting each anchor's exact sentence.

    ``loader`` receives only a validated root-absolute history or pinned original
    parent path and returns
    str or UTF-8 bytes. ``base_url`` resolves relative links and fixes the trusted
    origin. ``evidence_renderer`` optionally accepts the decoded original HTML
    evidence and returns trusted inert/offline presentation HTML *inside* its
    disclosure. Its caller must preserve the complete evidence without executing
    it. The default is a fully escaped pre, identical to browser textContent.
    """
    def __init__(self, loader, *, base_url='http://localhost/', evidence_renderer=None):
        self.loader = loader
        self.base_url = base_url
        self.evidence_renderer = evidence_renderer
        self._archives = {}
        self._parents = {}
        self._selections = {}
        self._evidence_html = {}

    def _load(self, path):
        raw = self.loader(path)
        if isinstance(raw, bytes):
            try:
                raw = raw.decode('utf-8')
            except UnicodeError as error:
                raise HistoryError('history is not UTF-8') from error
        if not isinstance(raw, str):
            raise HistoryError('history loader must return HTML text or UTF-8 bytes')
        if len(raw) > _MAX_ARCHIVE or (len(raw) > _MAX_ARCHIVE // 2 and
                len(raw) + sum(ord(char) > 0xffff for char in raw) > _MAX_ARCHIVE):
            raise HistoryError('history exceeds browser load limit')
        return raw

    def _archive(self, path):
        if path not in self._archives:
            raw = self._load(path)
            tree = _Tree(raw)
            evidence = _html_evidence(tree)
            self._archives[path] = (tree, evidence)
        return self._archives[path]

    def _source_parent(self, path, pin):
        if path not in self._parents:
            raw = self._load(path)
            actual = hashlib.sha256(raw.encode('utf-8')).hexdigest()
            if actual != pin:
                raise HistoryError('source-parent HTML SHA256 mismatch')
            self._parents[path] = (_Tree(raw), raw, actual)
        tree, raw, actual = self._parents[path]
        if actual != pin:
            raise HistoryError('source-parent HTML SHA256 mismatch')
        return tree, raw

    def _present_evidence(self, value):
        key = hashlib.sha256(value.encode('utf-8')).hexdigest()
        if key not in self._evidence_html:
            presented = ('<pre>' + escape(value) + '</pre>' if self.evidence_renderer is None else
                         self.evidence_renderer(value))
            if not isinstance(presented, str):
                raise HistoryError('evidence renderer must return trusted inert HTML text')
            self._evidence_html[key] = presented
        return self._evidence_html[key]

    def _replacement(self, path, identity, details, base_url):
        tree, evidence = self._archive(path)
        parent_ref = None
        try:
            record = _selected_record(tree, identity)
        except _RecordMatchError as error:
            if error.count != 0:
                raise
            parent_ref = _source_parent_pin(details, base_url, identity[2])
            parent, original = self._source_parent(*parent_ref[:2])
            record = _selected_record(parent, identity, source_parent=True,
                                      english=parent_ref[2], target_range=parent_ref[3], option_label=parent_ref[4])
        key = (path, identity, parent_ref)
        if key not in self._selections:
            selected = _safe_copy(record)
            if not selected:
                raise HistoryError('selected original sentence cannot be safely copied')
            proof = '<details><summary>完整原 HTML 证据</summary>' + self._present_evidence(evidence) + '</details>'
            if parent_ref is not None:
                proof += ('<details><summary>本句封存父页面完整原 HTML 证据</summary>' +
                          '<p class="sf-history-source-pin">来源：' + escape(parent_ref[0]) +
                          ' · SHA256：' + parent_ref[1] + '</p>' +
                          self._present_evidence(original) + '</details>')
            self._selections[key] = (
                '<details class="sf-inline-history"><summary>本句完整原文与转归审核记录</summary>' +
                selected + proof + '</details>')
        return self._selections[key]

    def materialize(self, text, *, base_url=None):
        """Return exact original text except for audited history-anchor ranges.

        Any validation error raises before a changed value can be returned.
        Already inlined fields and nonownership links remain byte-identical.
        """
        if not isinstance(text, str):
            raise HistoryError('card field must be HTML text')
        if 'sf-original-history-link' not in text:
            return text
        tree = _Tree(text)
        edits = []
        for anchor in tree.root.walk():
            if anchor.tag != 'a' or 'sf-original-history-link' not in anchor.classes:
                continue
            owner = anchor.parent
            while owner is not None and not (owner.tag == 'details' and 'sf-ownership-history' in owner.classes):
                owner = owner.parent
            if owner is None:
                continue
            if anchor.end is None or owner.end is None:
                raise HistoryError('original history anchor or disclosure is unclosed')
            expected = _identity(owner)
            trusted_base = self.base_url if base_url is None else base_url
            path = _archive_path(anchor.attrs.get('href'), trusted_base)
            edits.append((anchor.start, anchor.end, self._replacement(path, expected, owner, trusted_base)))
        previous = 0
        pieces = []
        for start, end, replacement in edits:
            if start < previous:
                raise HistoryError('history anchor replacements overlap')
            pieces.extend((text[previous:start], replacement))
            previous = end
        pieces.append(text[previous:])
        return ''.join(pieces)


def materialize_history(text, loader, *, base_url='http://localhost/', evidence_renderer=None):
    """Single-call convenience API; use HistoryMaterializer for cross-card caching."""
    return HistoryMaterializer(loader, base_url=base_url,
                               evidence_renderer=evidence_renderer).materialize(text)
