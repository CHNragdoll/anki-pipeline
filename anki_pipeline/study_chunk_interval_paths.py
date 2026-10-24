"""Representation-only childNodes path proposals for authenticated chunk HTML.

No DOM, source execution, semantic producer, file IO or capability installation.
The parser keeps counters on the open-element stack and only retains requested
bindings, readers, regions and new anchors. Adjacent character/entity callbacks
are one DOM Text child; comments are separate children. Generated HTML outside
this deliberately conservative subset is rejected, never repaired with an XML
path guess. Unchanged templates/selects and text-free SVG icons are explicitly
opaque; bindings inside them are unsupported. Tables and implicit closures in
semantic regions are rejected.

Archive reversibility is not edit permission. Only exact new anchor insertions
and paired ordinary chunk-span tags removable by the current compiler's same
structural preservation rules are authorized, inside selected paragraphs.

The result is NOT a compiled profile and cannot select the compiled Slim branch.
It proposes only path/requiredAttrs differences. Existing semantic tables, source
identities, validation, mutation/owned-paint protocols and all FRAME gates still
need their original authority. Do not modify old sealed profiles in place.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib
import html
from html.parser import HTMLParser
import json
import re

from . import study_chunk_intervals as intervals

SCHEMA = 'study-chunk-interval-path-ledger.v1'
_KEY = 'data-study-compiled-key'
_HTML = 'http://www.w3.org/1999/xhtml'
_REGIONS = {'.sf-report', '.examples-section'}
_ANCHORS = {intervals.ROOT_ATTRIBUTE, intervals.PARAGRAPH_ATTRIBUTE}
_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
_BLOCK = set('address article aside blockquote center dd details dialog div dl dt fieldset figcaption figure '
             'footer form h1 h2 h3 h4 h5 h6 header hgroup hr li main menu nav ol p pre section summary table ul'.split())
_SVG = set('svg g path circle ellipse line polyline polygon rect defs use symbol clippath mask '
           'lineargradient radialgradient stop'.split())
_UNSAFE = set('table caption tbody thead tfoot tr td th colgroup col textarea title xmp plaintext noscript math '
              'frameset frame iframe noembed noframes ruby rb rt rtc rp option optgroup'.split())
_SEMANTIC = ('panels', 'groups', 'bankRecords', 'projectionWrappers', 'residualWrappers', 'historySlots',
             'filter_mode', 'residual_mode')
_PIN = re.compile(r'[a-f0-9]{64}\Z')


def _fail(message):raise ValueError('Interval path ledger: ' + message)
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _json_bytes(value):return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def _u16(text):return len(text.encode('utf-16-le')) // 2


def _pinned(raw, pin, label):
    if type(raw) is not bytes or type(pin) is not str or not _PIN.fullmatch(pin) or _sha(raw) != pin:_fail(label + ' external SHA')


def _decode(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:_fail('duplicate JSON field')
            result[key] = value
        return result
    try:return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=lambda v:_fail('nonfinite JSON'))
    except (UnicodeError, json.JSONDecodeError) as error:raise ValueError('Interval path ledger: JSON encoding') from error


def _path(value):
    if type(value) is not list or any(type(i) is not int or i < 0 for i in value):_fail('childNodes path type')
    return tuple(value)


def _attrs(value):
    if type(value) is not list:_fail('attribute list')
    result = {}
    for row in value:
        if (type(row) is not list or len(row) != 2 or type(row[0]) is not str or
                (row[1] is not None and type(row[1]) is not str) or row[0] in result):_fail('attribute row')
        result[row[0]] = row[1]
    return result


def _relative(root, node):
    if node['path'][:len(root['path'])] != root['path']:_fail('node outside logical root')
    return list(node['path'][len(root['path']):])


class _Positions:
    def __init__(self, profile):
        self.rows = []
        self.ends = []
        self.deltas = [0]
        lexemes = profile['lexemes']
        for start, compact_at, before, after in profile['edits']:
            left, right = lexemes[before].encode(), lexemes[after].encode()
            self.rows.append((start, start + len(left)))
            self.ends.append(start + len(left))
            self.deltas.append(self.deltas[-1] + len(right) - len(left))
    def new(self, old):
        at = bisect_right(self.ends, old)
        if at < len(self.rows) and self.rows[at][0] <= old < self.rows[at][1]:_fail('bound node was removed')
        return old + self.deltas[at]


def _marker_edits(profile):
    expected, targets, deletions = {}, {}, set()
    for sentence in profile['sentences']:
        root = (intervals.ROOT_ATTRIBUTE, sentence['key'])
        if root in expected:_fail('duplicate interval root')
        expected[root] = {'root_index':sentence['root_index'], 'root_key':sentence['key']}
        source = profile['sources'][sentence['source']]['example']
        for paragraph in sentence['paragraphs']:
            pair = (intervals.PARAGRAPH_ATTRIBUTE, paragraph['key'])
            if pair in expected:_fail('duplicate interval paragraph')
            text = paragraph['prefix'] + source['text' if paragraph['side'] == 'en' else 'translation']
            if _sha(text.encode()) != paragraph['text_sha256'] or _u16(text) != paragraph['utf16_length']:_fail('interval paragraph text')
            expected[pair] = {'root_key':sentence['key'], 'text_sha256':paragraph['text_sha256'],
                              'utf16_length':paragraph['utf16_length']}
    for start, compact_at, before, after in profile['edits']:
        old, new = profile['lexemes'][before], profile['lexemes'][after]
        if not old and new:
            match = re.fullmatch(r' (data-study-chunk-interval-(?:root|paragraph))="([A-Za-z0-9_.:-]+)"', new)
            if not match or tuple(match.groups()) not in expected:_fail('unauthorized inserted attribute')
            targets.setdefault(start, []).append(tuple(match.groups()))
        elif old and not new:deletions.add((start, start + len(old.encode())))
        else:_fail('unauthorized replacement/no-op edit')
    if sum(map(len, targets.values())) != len(expected):_fail('missing/duplicate marker edit')
    return expected, targets, deletions


class _Stream(HTMLParser):
    def __init__(self, raw, specs, readers, expected_markers, marker_targets, *, compact=False, max_depth=512,
                 deletions=()):
        super().__init__(convert_charrefs=False)
        try:self.text = raw.decode('utf-8')
        except UnicodeError as error:raise ValueError('Interval path ledger: HTML UTF8') from error
        if '\0' in self.text:_fail('NUL parsing ambiguity')
        self.raw, self.specs, self.readers = raw, specs, readers
        self.expected_markers, self.marker_targets, self.compact = expected_markers, marker_targets, compact
        self.max_depth = max_depth
        self.deletions, self.authorized_deletions = set(deletions), set()
        self.lines = [0] + [m.end() for m in re.finditer('\n', self.text)]
        self.char_cursor = self.byte_cursor = 0
        self.stack = []
        self.document = {'path':(), 'children':0, 'last_text':False, 'ignore_lf':False}
        self.nodes, self.reader_nodes, self.markers = {}, {}, {}
        self.regions, self.region_counts, self.first_jumps = {}, {}, {}
        self.opaque, self.opaque_rows = None, []
        self.example_index = -1
        self.watchers = []
        self.by_root = {}
        for index, row in enumerate(readers):self.by_root.setdefault(row['rootKey'], []).append((index, _path(row['relativePath'])))
        self.new_readers = marker_targets.get('readers', {}) if compact else {}

    def _position(self):
        line, column = self.getpos()
        at = self.lines[line - 1] + column
        if at < self.char_cursor:_fail('token order')
        self.byte_cursor += len(self.text[self.char_cursor:at].encode())
        self.char_cursor = at
        return at, self.byte_cursor

    def _end(self, at):
        if at < self.char_cursor:_fail('token order')
        self.byte_cursor += len(self.text[self.char_cursor:at].encode())
        self.char_cursor = at
        return self.byte_cursor

    def _in_region(self):return any(f.get('regions') for f in self.stack)
    def _parent(self):return self.stack[-1] if self.stack else self.document
    def _child(self, text=False):
        parent = self._parent()
        if text and parent['last_text']:return parent['children'] - 1
        index = parent['children']
        parent['children'] += 1
        parent['last_text'] = text
        return index

    def handle_starttag(self, tag, attrs):self._start(tag, attrs, False)
    def handle_startendtag(self, tag, attrs):self._start(tag, attrs, True)

    def _start(self, tag, attrs, self_closing):
        at, start = self._position()
        text = self.get_starttag_text()
        end = self._end(at + len(text))
        values = {}
        for name, value in attrs:
            if name in values:_fail('duplicate HTML attribute')
            values[name] = '' if value is None else value
        classes = values.get('class', '').split()
        if 'example-card' in classes:self.example_index += 1
        if self.opaque:
            mode = self.opaque['tag']
            if len(self.stack) + len(self.opaque['nested']) >= self.max_depth:_fail('opaque nesting limit')
            if mode == 'template':
                if tag == 'template' and not self_closing:self.opaque['nested'].append(tag)
                return
            if (_KEY in values and values[_KEY] in self.specs) or _ANCHORS.intersection(values) or any(s[1:] in classes for s in _REGIONS):
                _fail('binding inside opaque subtree')
            allowed = _SVG if mode == 'svg' else {'option', 'optgroup', 'hr'}
            if tag not in allowed:_fail('ambiguous opaque subtree')
            if not self_closing and tag not in _VOID:self.opaque['nested'].append(tag)
            return
        in_region = self._in_region()
        if not self.compact:
            if self._parent().get('chunk_paragraph') is not None and (tag in intervals._BLOCK or tag in intervals._UNSAFE):
                _fail('ambiguous selected paragraph content')
            if 'example-card' in classes and any(f.get('interval_root') for f in self.stack):
                _fail('nested selected example root')
        if in_region:
            if tag in _UNSAFE or tag in {'html', 'head', 'body', 'image'}:_fail('unsupported HTML5 region context')
            opened = [f['tag'] for f in self.stack]
            if ('p' in opened and tag in _BLOCK) or (tag in {'a', 'button', 'form', 'nobr'} and tag in opened):
                _fail('implicit HTML5 closure')
            if tag in {'li', 'dt', 'dd'}:
                scope = {'ul', 'ol', 'menu'} if tag == 'li' else {'dl'}
                boundary = max((i for i, f in enumerate(self.stack) if f['tag'] in scope), default=-1)
                if any(f['tag'] in ({'li'} if tag == 'li' else {'dt', 'dd'}) for f in self.stack[boundary + 1:]):_fail('implicit list closure')
            if tag in {'h1','h2','h3','h4','h5','h6'} and any(t in {'h1','h2','h3','h4','h5','h6'} for t in opened):_fail('implicit heading closure')
        selectors = [s for s in _REGIONS if s[1:] in classes]
        if selectors and any(f['tag'] in _UNSAFE or f['tag'] in {'select', 'template', 'svg'} for f in self.stack):_fail('semantic region in ambiguous context')
        if self_closing and tag not in _VOID and tag != 'svg':_fail('HTML nonvoid self-closing')
        parent = self._parent()
        parent['complex'] = True
        parent['ignore_lf'] = False
        path = parent['path'] + (self._child(),)
        frame = {'tag':tag, 'attrs':values, 'path':path, 'children':0, 'last_text':False,
                 'ignore_lf':tag in {'pre','listing'}, 'start':start, 'regions':selectors,
                 'digest':None, 'utf16':0, 'text_bytes':0, 'example_index':self.example_index,
                 'open_end':end, 'complex':False, 'has_text':False, 'chunk':False,
                 'chunk_paragraph':parent.get('chunk_paragraph')}
        if selectors:
            for selector in selectors:
                ordinal = self.region_counts.get(selector, 0)
                self.region_counts[selector] = ordinal + 1
                self.regions[(selector, ordinal)] = frame
        key = values.get(_KEY)
        if key in self.specs:
            if key in self.nodes:_fail('duplicate bound key')
            self.nodes[key] = frame
        else:key = None
        reader_indices = []
        if self.compact:reader_indices = self.new_readers.get(start, [])
        else:
            for root in self.stack + [frame]:
                root_key = root['attrs'].get(_KEY)
                for index, relative in self.by_root.get(root_key, []):
                    if path == root['path'] + relative:reader_indices.append(index)
        for index in reader_indices:
            if index in self.reader_nodes:_fail('duplicate reader position')
            self.reader_nodes[index] = frame
        markers = [(name, values[name]) for name in _ANCHORS if name in values] if self.compact else self.marker_targets.get(end - 1, [])
        for pair in markers:
            if pair not in self.expected_markers or pair in self.markers:_fail('unauthorized/duplicate anchor')
            if not self.compact and pair[0] in values:_fail('anchor already in original')
            requirement = self.expected_markers[pair]
            if pair[0] == intervals.ROOT_ATTRIBUTE:
                if 'example-card' not in classes or self.example_index != requirement['root_index']:_fail('root marker identity')
                if not self.compact and any(f['tag'] in intervals._UNSAFE or 'example-card' in f['attrs'].get('class','').split() for f in self.stack):
                    _fail('ambiguous selected root context')
                frame['interval_root'] = pair[1]
            else:
                if not any(f.get('interval_root') == requirement['root_key'] for f in self.stack):_fail('paragraph marker owner')
                if frame['chunk_paragraph'] is not None:_fail('nested selected paragraph')
                frame['chunk_paragraph'] = pair
                frame['paragraph_owner'] = True
            self.markers[pair] = frame
        if not self.compact and frame['chunk_paragraph'] is not None and 'card-chunk' in classes:
            if tag != 'span' or frame.get('paragraph_owner') or self_closing:_fail('invalid selected chunk')
            frame['chunk'] = True
            # Same structural preservation boundary as the source compiler.
            # Reversible edits alone never authorize removal of emphasis,
            # unknown attributes, nested/interactive or keyboard-owned nodes.
            frame['protected'] = any(f['tag'] == 'mark' or 'sf-target-chunk' in f['attrs'].get('class','').split() or
                f.get('chunk') or f['tag'] in intervals._INTERACTIVE or
                any(k in f['attrs'] for k in ('tabindex','contenteditable','role')) for f in self.stack)
        if not self.compact and _ANCHORS.intersection(values):_fail('original has interval anchors')
        if 'sentence-jump' in classes or 'data-rb-j' in values:
            for root in self.stack + [frame]:
                root_key = root['attrs'].get(_KEY)
                if root_key in self.specs and self.specs[root_key]['rootKey'] == root_key:self.first_jumps.setdefault(root_key, values)
        if key or reader_indices or markers:
            frame['digest'] = hashlib.sha256()
            self.watchers.append(frame)
        if tag in _VOID:self._finish(frame, end);return
        if len(self.stack) >= self.max_depth:_fail('nesting limit')
        self.stack.append(frame)
        if tag in {'template', 'select', 'svg'}:
            self.opaque = {'tag':tag, 'frame':frame, 'nested':[]}
            if self_closing:self.stack.pop();self._opaque_finish(end)

    def handle_endtag(self, tag):
        at, start = self._position()
        close = self.text.find('>', at)
        if close < 0:_fail('unterminated end tag')
        end = self._end(close + 1)
        if self.opaque:
            state = self.opaque
            if state['tag'] == 'template':
                if tag != 'template':return
                if state['nested']:state['nested'].pop();return
            else:
                if state['nested']:
                    if state['nested'][-1] != tag:_fail('implicit opaque closure')
                    state['nested'].pop();return
                if tag != state['tag']:_fail('opaque closing tag')
            self.stack.pop();self._opaque_finish(end);return
        if tag in _VOID and self._in_region():_fail('void end tag HTML5 ambiguity')
        if not self.stack:return
        if self.stack[-1]['tag'] != tag:
            if self._in_region():_fail('implicit/unbalanced HTML5 closure')
            found = [i for i, f in enumerate(self.stack) if f['tag'] == tag]
            if not found:return
            del self.stack[found[-1] + 1:]
        self._finish(self.stack.pop(), end, close_start=start)

    def _opaque_finish(self, end):
        frame = self.opaque['frame']
        self.opaque_rows.append({'tag':frame['tag'], 'start':frame['start'], 'end':end,
                                 'sha256':_sha(memoryview(self.raw)[frame['start']:end])})
        self.opaque = None
        self._finish(frame, end)

    def _finish(self, frame, end, *, close_start=None):
        frame['end'] = end
        if frame.get('chunk') and close_start is not None:
            values = frame['attrs']
            removable = (values.get('class') == 'card-chunk' and not frame['protected'] and
                not frame['complex'] and frame['has_text'] and set(values).issubset(intervals._ALLOWED) and
                values.get('title', intervals._WHOLE_TITLE) == intervals._WHOLE_TITLE)
            opening, closing = (frame['start'], frame['open_end']), (close_start, end)
            if removable and (opening in self.deletions or closing in self.deletions):
                if opening not in self.deletions or closing not in self.deletions:_fail('unauthorized unpaired span deletion')
                self.authorized_deletions.update((opening, closing))
        if frame['digest'] is not None:
            frame['text_sha256'] = frame['digest'].hexdigest()
            del frame['digest']
            if not self.watchers or self.watchers.pop() is not frame:_fail('text scope imbalance')

    def handle_data(self, value):self._text(value.replace('\r\n','\n').replace('\r','\n'))
    def handle_entityref(self, name):self._reference(name, False)
    def handle_charref(self, name):self._reference(name, True)
    def _reference(self, name, numeric):
        line, column = self.getpos();at = self.lines[line - 1] + column
        raw = ('&#' if numeric else '&') + name
        if self.text[at + len(raw):at + len(raw) + 1] == ';':raw += ';'
        self._text(html.unescape(raw))
    def _text(self, value):
        if not value:return
        if self.opaque and self.opaque['tag'] == 'template':return
        if self.opaque and self.opaque['tag'] == 'svg' and value.strip():_fail('textful SVG needs explicit AST support')
        parent = self._parent()
        if parent.get('chunk_paragraph') is not None:parent['has_text'] = True
        if parent['ignore_lf']:
            if value.startswith('\n'):value = value[1:]
            parent['ignore_lf'] = False
        if not value:return
        if not self.opaque:self._child(text=True)
        encoded = value.encode()
        for frame in self.watchers:
            frame['digest'].update(encoded)
            frame['utf16'] += _u16(value)
            frame['text_bytes'] += len(encoded)
    def handle_comment(self, value):
        if not self.opaque:
            self._parent()['complex'] = True
            self._parent()['ignore_lf'] = False
            self._child()
    def handle_pi(self, value):self.handle_comment(value)
    def handle_decl(self, value):
        if self._in_region():_fail('declaration in semantic region')
        self._child()
    def unknown_decl(self, value):
        if self._in_region():_fail('unknown HTML5 declaration')
    def run(self):
        self.feed(self.text);self.close()
        if self.deletions != self.authorized_deletions:_fail('unauthorized deletion edit')
        if self.opaque or self.watchers or self._in_region():_fail('unclosed semantic context')
        if set(self.nodes) != set(self.specs) or len(self.reader_nodes) != len(self.readers) or set(self.markers) != set(self.expected_markers):
            _fail('missing bound node/reader/anchor')
        for pair, frame in self.markers.items():
            wanted = self.expected_markers[pair]
            if 'text_sha256' in wanted and (frame['text_sha256'] != wanted['text_sha256'] or frame['utf16'] != wanted['utf16_length']):
                _fail('anchored paragraph text')
        return self


def _validate(stream, profile, *, original, markers=None):
    specs = {row['key']:row for row in profile['nodeBindings']}
    for spec in specs.values():
        node, root = stream.nodes[spec['key']], stream.nodes[spec['rootKey']]
        region = spec['region']
        identity = (region['selector'], region['ordinal'])
        if stream.region_counts.get(region['selector'], 0) != region['total'] or identity not in stream.regions:_fail('region count/identity')
        if node['tag'].upper() != spec['tag'] or spec['namespace'] != _HTML:_fail('bound tag/namespace')
        if original:
            if _relative(stream.regions[identity], root) != region['rootPath'] or _relative(root, node) != spec['relativePath']:_fail('old compiled position')
            if node['attrs'] != _attrs(spec['requiredAttrs']):_fail('old required attributes/key')
        else:
            wanted = _attrs(spec['requiredAttrs'])
            wanted.update({name:value for name,value in (markers or {}).get(node['start'], [])})
            if node['attrs'] != wanted:_fail('unapproved compact attribute change')
        if not set(spec['roles']).intersection({'sense-panel','group-panel','group-status'}):
            if type(spec.get('exactText')) is not str or node['text_sha256'] != _sha(spec['exactText'].encode()):_fail('old exact text')
        logical = spec['logicalRoot']
        kind = logical['kind']
        if kind == 'occurrence':
            if root['attrs'].get('data-sf-occurrence-id') != logical['id']:_fail('occurrence source identity')
        elif kind == 'native-source':
            jump = stream.first_jumps.get(spec['rootKey'])
            try:expected = None if logical['id'] is None else json.loads(logical['id'])
            except (ValueError, TypeError) as error:raise ValueError('Interval path ledger: native identity JSON') from error
            actual = [jump.get(name) for name in ('data-rb-j','data-latex-url','data-full-paper-url')] if jump is not None else None
            if actual != expected:_fail('native source identity')
        elif kind == 'panel':
            if logical['id'] != spec['rootKey']:_fail('panel source identity')
        else:_fail('unsupported logical source kind')
    for index, spec in enumerate(profile['readerLinks']):
        node, root = stream.reader_nodes[index], stream.nodes[spec['rootKey']]
        if 'sentence-jump' not in node['attrs'].get('class','').split():_fail('reader class/position')
        if original and _relative(root,node) != spec['relativePath']:_fail('old reader path')
        if any(node['attrs'].get(k) != v for k,v in _attrs(spec['immutableAttrs']).items()):_fail('reader immutable identity')
        current = {k:node['attrs'].get(attr) for k,attr in [('href','href'),('title','title'),('disabled','aria-disabled')]}
        if current != spec['baseline']:_fail('reader baseline identity')


def build_path_ledger(source, compact, interval_profile, compiled_profile, *, expected_source_sha256,
                      expected_compact_sha256, expected_interval_profile_sha256, expected_compiled_profile_sha256,
                      max_source_bytes=128*1024*1024, max_depth=512):
    """Propose local path/anchor changes; all four inputs require external SHA.

    Original compiled JSON must bind this source's exact derivedHTMLSha256.
    Returned JSON patches are not applied, do not alter semantic tables or
    bindings, and do not create runtime authority. No original file is reopened.
    """
    for raw,pin,label in [(source,expected_source_sha256,'source'),(compact,expected_compact_sha256,'compact'),
                          (interval_profile,expected_interval_profile_sha256,'interval profile'),
                          (compiled_profile,expected_compiled_profile_sha256,'compiled profile')]:_pinned(raw,pin,label)
    if (type(max_source_bytes) is not int or max_source_bytes <= 0 or max(len(source),len(compact)) > max_source_bytes or
            type(max_depth) is not int or not 1 <= max_depth <= 4096):_fail('input/depth limit')
    new, old = _decode(interval_profile), _decode(compiled_profile)
    if not isinstance(new,dict) or not isinstance(old,dict):_fail('profile objects required')
    if (old.get('schema') != 'study-compiled-card-interactions.v1' or type(old.get('version')) is not int or old['version'] != 1 or
            old.get('bindings',{}).get('derivedHTMLSha256') != expected_source_sha256):_fail('original compiled source pin/schema')
    if intervals.restore_html(compact,new,expected_source_sha256=expected_source_sha256,
                              expected_profile_sha256=_sha(intervals.profile_bytes(new))) != source:_fail('inverse is not original')
    if new['compact_sha256'] != expected_compact_sha256:_fail('compact binding')
    if type(old.get('nodeBindings')) is not list:_fail('node binding table')
    if type(old.get('bindings')) is not dict or any(type(v) is not str or not _PIN.fullmatch(v) for v in old['bindings'].values()):_fail('original binding pins')
    specs = {}
    for spec in old['nodeBindings']:
        if (type(spec) is not dict or type(spec.get('key')) is not str or spec['key'] in specs or
                not isinstance(spec.get('region'),dict) or spec['region'].get('selector') not in _REGIONS or
                any(type(spec['region'].get(k)) is not int or spec['region'][k] < 0 for k in ('ordinal','total')) or
                type(spec.get('rootKey')) is not str or type(spec.get('tag')) is not str or type(spec.get('namespace')) is not str or
                type(spec.get('roles')) is not list or any(type(r) is not str for r in spec.get('roles',[])) or
                type(spec.get('logicalRoot')) is not dict or not {'kind','id'}.issubset(spec.get('logicalRoot',{})) or
                not {'rootKey','relativePath','requiredAttrs','tag','namespace'}.issubset(spec)):_fail('node binding shape')
        _path(spec['relativePath']);_path(spec['region']['rootPath']);_attrs(spec['requiredAttrs'])
        specs[spec['key']] = spec
    if not specs or any(spec.get('rootKey') not in specs for spec in specs.values()):_fail('missing logical root binding')
    readers = old.get('readerLinks')
    if type(readers) is not list or any(type(r) is not dict or type(r.get('rootKey')) is not str or r.get('rootKey') not in specs or
        not {'relativePath','immutableAttrs','baseline'}.issubset(r) or type(r['baseline']) is not dict or
        set(r['baseline']) != {'href','title','disabled'} for r in readers):_fail('reader table')
    expected, marker_targets, deletions = _marker_edits(new)
    original = _Stream(source,specs,readers,expected,marker_targets,max_depth=max_depth,deletions=deletions).run()
    _validate(original,old,original=True)
    positions = _Positions(new)
    new_readers = {}
    for index,node in original.reader_nodes.items():new_readers.setdefault(positions.new(node['start']),[]).append(index)
    projected = _Stream(compact,specs,readers,expected,{'readers':new_readers},compact=True,max_depth=max_depth).run()
    marker_attrs = {}
    for pair,node in projected.markers.items():marker_attrs.setdefault(node['start'],[]).append(list(pair))
    _validate(projected,old,original=False,markers=marker_attrs)
    for key,node in original.nodes.items():
        other = projected.nodes[key]
        if (positions.new(node['start']) != other['start'] or node['text_sha256'] != other['text_sha256'] or node['tag'] != other['tag']):
            _fail('retained key source postimage')
    for index,node in original.reader_nodes.items():
        other = projected.reader_nodes[index]
        if node['attrs'] != other['attrs'] or node['tag'] != other['tag'] or node['text_sha256'] != other['text_sha256']:_fail('reader source postimage')
    for pair,node in original.markers.items():
        other = projected.markers[pair]
        if (positions.new(node['start']) != other['start'] or node['tag'] != other['tag'] or node['text_sha256'] != other['text_sha256'] or
                {k:v for k,v in other['attrs'].items() if k not in _ANCHORS} != node['attrs']):_fail('anchor source postimage')
    opaque = {positions.new(row['start']):row for row in original.opaque_rows}
    if len(opaque) != len(projected.opaque_rows):_fail('opaque subtree count')
    for row in projected.opaque_rows:
        before = opaque.get(row['start'])
        if not before or before['tag'] != row['tag'] or before['sha256'] != row['sha256']:_fail('opaque subtree not preserved')
    changes, nodes, links = [], [], []
    def change(path,before,after):
        if before != after:changes.append({'op':'replace','path':path,'old':before,'value':after})
    for index,spec in enumerate(old['nodeBindings']):
        node,root = projected.nodes[spec['key']],projected.nodes[spec['rootKey']]
        region = projected.regions[(spec['region']['selector'],spec['region']['ordinal'])]
        relative,region_path = _relative(root,node),_relative(region,root)
        additions = marker_attrs.get(node['start'],[])
        if relative != spec['relativePath'] or region_path != spec['region']['rootPath'] or additions:
            nodes.append({'index':index,'key':spec['key'],'old_relative_path':spec['relativePath'],'new_relative_path':relative,
                          'old_region_root_path':spec['region']['rootPath'],'new_region_root_path':region_path,
                          'required_attrs_additions':additions})
            change(['nodeBindings',index,'relativePath'],spec['relativePath'],relative)
            change(['nodeBindings',index,'region','rootPath'],spec['region']['rootPath'],region_path)
            change(['nodeBindings',index,'requiredAttrs'],spec['requiredAttrs'],spec['requiredAttrs']+additions)
    for index,spec in enumerate(readers):
        relative = _relative(projected.nodes[spec['rootKey']],projected.reader_nodes[index])
        if relative != spec['relativePath']:
            links.append({'index':index,'root_key':spec['rootKey'],'old_relative_path':spec['relativePath'],'new_relative_path':relative})
            change(['readerLinks',index,'relativePath'],spec['relativePath'],relative)
    return {'schema':SCHEMA,'version':1,'proposal_only':True,'requires_new_external_descriptor':True,
            'pins':{'source_sha256':expected_source_sha256,'compact_sha256':expected_compact_sha256,
                    'interval_profile_sha256':expected_interval_profile_sha256,'compiled_profile_sha256':expected_compiled_profile_sha256},
            'node_bindings':nodes,'reader_links':links,'proposed_changes':changes,
            'anchor_additions':[{'attribute':pair[0],'value':pair[1],'node_key':node['attrs'].get(_KEY),
                                 'tag':node['tag'].upper(),'source_start':original.markers[pair]['start'],
                                 'compact_start':node['start'],'text_sha256':node['text_sha256']}
                                for pair,node in sorted(projected.markers.items())],
            'semantic_tables_sha256':_sha(_json_bytes({key:old[key] for key in _SEMANTIC if key in old})),
            'validated':{'node_bindings':len(specs),'reader_links':len(readers),'regions':len(original.regions)},
            'opaque_preserved':original.opaque_rows}
