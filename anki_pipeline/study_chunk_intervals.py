"""Experimental byte-preserving chunk compilation shared by delivery formats.

This token-stream pass constructs no DOM and never executes source scripts. Its
input must be the same already-validated final chunk markup used by the common
semantic producer. The future common integration belongs before web/APKG field
projection diverges (project_note/project_display_fields), not in web's
_render_note. Nothing enables this compiler in either delivery path yet.

A caller supplies an external source SHA, independently reviewed alignments and
an explicit capability for its entire pinned stylesheet: plain ``card-chunk``
wrappers have no default visual/keyboard meaning. A CSS SHA alone cannot prove
that capability. Unknown attrs/classes, marks, keyboard nodes and nested spans
remain. Ambiguous selected HTML is rejected rather than normalized by a second
HTML5 parser. This is a conservative generated-HTML subset, not an HTML5 parser.

The new runtime must verify the external artifact/source/metadata/CSS bindings,
index the new anchors once, and validate only the active root for interactions.
It must use explicit legacy-private-clear/owned-release handoff, never an old
DOM profile. Source/native/registry validation, full content commit, child/fonts
and the original stable-ready gate remain separate integration requirements.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import html
from html.parser import HTMLParser
import json
import re

SCHEMA = 'study-chunk-intervals.v1'
ROOT_ATTRIBUTE = 'data-study-chunk-interval-root'
PARAGRAPH_ATTRIBUTE = 'data-study-chunk-interval-paragraph'
SEGMENT_COLUMNS = ['start', 'end', 'ids', 'whole', 'attributes', 'retained']
EDIT_COLUMNS = ['source_start', 'compact_start', 'before', 'after']
_WHOLE_TITLE = '整句对应：已审校双语全文，非词语级对齐'
_PINS = re.compile(r'[a-f0-9]{64}\Z')
_KEYS = re.compile(r'[A-Za-z0-9_.:-]{1,160}\Z')
_VOID = set('area base br col embed hr img input link meta param source track wbr'.split())
_UNSAFE = set('table select template svg math script style textarea title pre xmp plaintext noscript'.split())
_BLOCK = set('address article aside blockquote caption center dd details dialog div dl dt fieldset '
             'figcaption figure footer form h1 h2 h3 h4 h5 h6 header hgroup hr li main menu nav ol p '
             'section summary table tbody td tfoot th thead tr ul'.split())
_INTERACTIVE = set('a button input select textarea summary audio video'.split())
_ALLOWED = {'class', 'data-chunk-side', 'data-chunk-ids', 'data-chunk-sentence-ids', 'title'}


def _fail(message):raise ValueError('Chunk intervals: ' + message)
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _u16(text):return len(text.encode('utf-16-le')) // 2

def _pin(value, label):
    if type(value) is not str or not _PINS.fullmatch(value):_fail(label + ' SHA')
    return value


def profile_bytes(profile):
    """The only serialization hashed by this version; no NaN/non-UTF8 values."""
    try:return json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as error:raise ValueError('Chunk intervals: invalid profile JSON') from error


@dataclass(frozen=True)
class SentenceBinding:
    """Explicit ordinal in the input's .example-card stream, never an old path.

    Classes identify the two paragraph containers under this root. ``example``
    has the unchanged packaging._example_chunk_ranges input. Prefixes include
    real DOM text such as the native translation label; no text is trimmed.
    """
    key: str
    root_index: int
    example: dict
    english_class: str = 'sf-en'
    chinese_class: str = 'sf-zh'
    english_prefix: str = ''
    chinese_prefix: str = ''


@dataclass(frozen=True)
class CompiledIntervals:
    compact_html: bytes
    profile: dict

    @property
    def profile_sha256(self):return _sha(profile_bytes(self.profile))


class _Table:
    def __init__(self, empty=None):
        self.rows = []
        self.keys = {}
        if empty is not None:self.add(empty)
    def add(self, value):
        key = profile_bytes(value)
        if key not in self.keys:self.keys[key] = len(self.rows);self.rows.append(value)
        return self.keys[key]


def _plans(bindings):
    from .packaging import _example_chunk_ranges
    if type(bindings) not in (list, tuple) or not bindings:_fail('explicit sentence bindings required')
    plans, keys, sources = {}, set(), _Table()
    for binding in bindings:
        if not isinstance(binding, SentenceBinding):_fail('sentence binding type')
        if (type(binding.key) is not str or not _KEYS.fullmatch(binding.key) or binding.key in keys or
                type(binding.root_index) is not int or binding.root_index < 0 or binding.root_index in plans):
            _fail('duplicate/invalid sentence identity')
        for name in (binding.english_class, binding.chinese_class):
            if type(name) is not str or not name or any(c.isspace() for c in name):_fail('paragraph class')
        if binding.english_class == binding.chinese_class:_fail('paragraph classes overlap')
        if any(type(s) is not str or '\0' in s for s in (binding.english_prefix, binding.chinese_prefix)):_fail('paragraph prefix')
        try:
            original = copy.deepcopy(binding.example)
            example = {name:original[name] for name in ('text', 'translation', 'translation_alignment')}
            example['translation_source'] = 'codex'
            en, zh, ready = _example_chunk_ranges(example)
            if not ready:_fail('reviewed alignment required')
            whole = [str(i) for i, row in enumerate(example['translation_alignment']['alignments'])
                     if row.get('note', '').startswith('整句对应：')]
        except (KeyError, TypeError, ValueError) as error:raise ValueError('Chunk intervals: invalid canonical alignment') from error
        source = {'example':example, 'ranges':{'en':en, 'zh':zh}, 'sentence_ids':whole,
                  'alignment_sha256':_sha(profile_bytes(example['translation_alignment']))}
        source_index = sources.add(source)
        plans[binding.root_index] = {'binding':binding, 'source_index':source_index, 'source':source,
                                     'seen':False, 'paragraphs':{}, 'root':None}
        keys.add(binding.key)
    return plans, sources.rows


class _Compiler(HTMLParser):
    def __init__(self, source, text, plans, max_depth):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.source = source
        self.preserved = []
        self.plans = plans
        self.max_depth = max_depth
        self.stack = []
        self.root_index = -1
        self.lines = [0]
        self.lines.extend(m.end() for m in re.finditer('\n', text))
        self.char_cursor = self.byte_cursor = 0
        self.edits = []
        self.segment_count = self.removed = 0
        self.attributes = _Table()
        self.id_sets = _Table([])

    def _position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def _byte(self, position):
        # Monotonic token positions make this O(source bytes), including a
        # single-line giant card; never re-encode every tag's entire prefix.
        if position < self.char_cursor:_fail('nonmonotonic token position')
        self.byte_cursor += len(self.text[self.char_cursor:position].encode('utf-8'))
        self.char_cursor = position
        return self.byte_cursor

    def _marker(self, frame, attribute, value):
        at = frame['open_end'] - 1
        self.edits.append((at, at, (' ' + attribute + '="' + value + '"').encode()))

    def _active_paragraph(self):
        return self.stack[-1]['paragraph'] if self.stack else None

    def handle_starttag(self, tag, attrs):self._start(tag, attrs, False)
    def handle_startendtag(self, tag, attrs):self._start(tag, attrs, True)

    def _start(self, tag, attrs, self_closing):
        raw = self.get_starttag_text()
        pos = self._position()
        start, end = self._byte(pos), self._byte(pos + len(raw))
        values = {}
        duplicate = False
        for name, value in attrs:
            if name in values:duplicate = True
            else:values[name] = value if value is not None else ''
        if ROOT_ATTRIBUTE in values or PARAGRAPH_ATTRIBUTE in values:_fail('reserved anchor in source')
        if self_closing and tag not in _VOID and not any(f['tag'] in {'svg', 'math'} for f in self.stack):
            _fail('HTML5 nonvoid self-closing ambiguity')
        classes = values.get('class', '').split()
        parent = self.stack[-1] if self.stack else None
        par = parent['paragraph'] if parent else None
        plan = parent['plan'] if parent else None
        if par is not None and (tag in _BLOCK or tag in _UNSAFE):_fail('HTML5 ambiguous paragraph content')
        if parent:parent['complex'] = True
        if 'example-card' in classes:
            self.root_index += 1
            selected = self.plans.get(self.root_index)
            if selected:
                if plan or any(f['tag'] in _UNSAFE or 'example-card' in f['classes'] for f in self.stack):
                    _fail('HTML5 ambiguous/nested root context')
                if duplicate or self_closing:_fail('invalid selected root')
                plan = selected
                plan['seen'] = True
            elif plan:_fail('nested example root')
        frame = {'tag':tag, 'attrs':list(values.items()), 'classes':classes, 'plan':plan, 'paragraph':par,
                 'open_start':start, 'open_end':end, 'complex':False, 'has_text':False,
                 'chunk':False, 'depth':len(self.stack),
                 'root_index':self.root_index if 'example-card' in classes else None}
        if plan and plan['root'] is None:
            plan['root'] = frame
            self._marker(frame, ROOT_ATTRIBUTE, plan['binding'].key)
        if plan:
            b = plan['binding']
            sides = [side for side, cls in [('en', b.english_class), ('zh', b.chinese_class)] if cls in classes]
            if sides:
                side = sides[0]
                if len(sides) != 1 or side in plan['paragraphs'] or par is not None or duplicate or self_closing or tag in _VOID:
                    _fail('duplicate/ambiguous paragraph')
                par = {'side':side, 'parts':[], 'cp':0, 'utf16':0, 'segments':[], 'owner':plan,
                       'key':b.key + ':' + side, 'frame':frame}
                frame['paragraph'] = par
                plan['paragraphs'][side] = par
                self._marker(frame, PARAGRAPH_ATTRIBUTE, par['key'])
            if frame['paragraph'] is not None and 'card-chunk' in classes:
                par = frame['paragraph']
                if duplicate or tag != 'span' or frame is par['frame'] or self_closing:_fail('invalid chunk element')
                frame['chunk'] = True
                frame['start'] = par['utf16']
                frame['cp_start'] = par['cp']
                frame['protected'] = any(f['tag'] == 'mark' or 'sf-target-chunk' in f['classes'] or f['chunk'] or
                                         f['tag'] in _INTERACTIVE or any(k in dict(f['attrs']) for k in ('tabindex', 'contenteditable', 'role'))
                                         for f in self.stack)
        if tag not in _VOID:
            if len(self.stack) >= self.max_depth:_fail('HTML nesting limit')
            self.stack.append(frame)
            if self_closing:self.stack.pop()

    def handle_endtag(self, tag):
        pos = self._position()
        start = self._byte(pos)
        close = self.text.find('>', pos)
        if close < 0:_fail('unterminated closing tag')
        end = self._byte(close + 1)
        if not self.stack:return
        if self.stack[-1]['tag'] != tag:
            if self.stack[-1]['plan']:_fail('unbalanced selected HTML')
            matching = [i for i, f in enumerate(self.stack) if f['tag'] == tag]
            if not matching:return
            if any(f['root_index'] is not None for f in self.stack[matching[-1] + 1:]):_fail('unbalanced example root')
            del self.stack[matching[-1] + 1:]
        frame = self.stack.pop()
        par = frame['paragraph']
        if frame['root_index'] is not None and frame['root_index'] not in self.plans:
            self.preserved.append({'root_index':frame['root_index'], 'start':frame['open_start'], 'end':end,
                                   'sha256':_sha(memoryview(self.source)[frame['open_start']:end]), 'reason':'unselected'})
        if frame['chunk']:
            values = dict(frame['attrs'])
            removable = (frame['tag'] == 'span' and values.get('class') == 'card-chunk' and
                         not frame['protected'] and not frame['complex'] and frame['has_text'] and
                         set(values).issubset(_ALLOWED) and values.get('title', _WHOLE_TITLE) == _WHOLE_TITLE)
            par['segments'].append({'frame':frame, 'start':frame['start'], 'end':par['utf16'],
                                    'cp_start':frame['cp_start'], 'cp_end':par['cp'], 'retained':not removable})
            self.segment_count += 1
            if removable:
                self.removed += 1
                self.edits.extend([(frame['open_start'], frame['open_end'], b''), (start, end, b'')])
        if par is not None and frame is par['frame']:self._finish_paragraph(par)

    def _text(self, value, *, literal=False):
        par = self._active_paragraph()
        if par is None:return
        # HTML normalizes literal source line endings before tokenization.
        # A character reference is decoded later: &#13; remains a real CR.
        if literal:value = value.replace('\r\n', '\n').replace('\r', '\n')
        par['parts'].append(value)
        par['cp'] += len(value)
        par['utf16'] += _u16(value)
        if self.stack:self.stack[-1]['has_text'] = True

    def handle_data(self, data):self._text(data, literal=True)
    def handle_entityref(self, name):self._reference(name, False)
    def handle_charref(self, name):self._reference(name, True)
    def _reference(self, name, numeric):
        pos = self._position()
        raw = ('&#' if numeric else '&') + name
        if self.text[pos + len(raw):pos + len(raw) + 1] == ';':raw += ';'
        self._text(html.unescape(raw))
    def handle_comment(self, data):
        if self.stack:self.stack[-1]['complex'] = True
    def handle_decl(self, decl):
        if self._active_paragraph() is not None:_fail('declaration inside paragraph')
    def unknown_decl(self, data):
        if self._active_paragraph() is not None:_fail('unknown declaration inside paragraph')
    def handle_pi(self, data):
        if self._active_paragraph() is not None:_fail('processing instruction inside paragraph')

    def _finish_paragraph(self, par):
        plan = par['owner']
        binding, side = plan['binding'], par['side']
        example = plan['source']['example']
        prefix = binding.english_prefix if side == 'en' else binding.chinese_prefix
        text = ''.join(par['parts'])
        if text != prefix + example['text' if side == 'en' else 'translation']:_fail('canonical paragraph text')
        segments = []
        for row in sorted(par['segments'], key=lambda r:(r['start'], -r['end'], r['frame']['depth'])):
            attrs = row['frame']['attrs']
            values = dict(attrs)
            encoded = values.get('data-chunk-ids', '')
            if not re.fullmatch(r'\d+( \d+)*', encoded):_fail('malformed chunk IDs')
            ids = encoded.split(' ')
            left, right = row['cp_start'] - len(prefix), row['cp_end'] - len(prefix)
            wanted = list(dict.fromkeys(str(i) for a, z, i in plan['source']['ranges'][side] if a <= left < right <= z))
            if ids != wanted:_fail('canonical ID position')
            whole = [identity for identity in ids if identity in plan['source']['sentence_ids']]
            if values.get('data-chunk-sentence-ids', '').split() != whole or values.get('data-chunk-side') != side:
                _fail('whole IDs/side mismatch')
            segments.append([row['start'], row['end'], self.id_sets.add(ids), self.id_sets.add(whole),
                             self.attributes.add(attrs), row['retained']])
        par['result'] = {'key':par['key'], 'side':side, 'prefix':prefix, 'text_sha256':_sha(text.encode()),
                         'utf16_length':par['utf16'], 'segments':segments}
        del par['parts']


def compile_html(source, bindings, *, expected_source_sha256, css_sha256,
                 plain_chunks_are_interaction_only, max_source_bytes=128 * 1024 * 1024, max_depth=512):
    """Compile explicit roots with bounded token state, no DOM/library IO.

    Only exact wrapper tags are removed. All other source bytes remain unchanged
    (including entity spellings, CRLF, scripts, JSON, comments and attr order).
    The token/edit pass is linear in input+intervals; preserved root hashes also
    read each reported subtree (overlapping unselected roots may overlap).
    Limits are actual rejection bounds, never instructions to enlarge a heap.
    ``css_sha256`` binds a caller-reviewed style capability, not arbitrary CSS.
    """
    if type(source) is not bytes:_fail('source must be immutable UTF8 bytes')
    if type(max_source_bytes) is not int or max_source_bytes <= 0 or len(source) > max_source_bytes:_fail('source byte limit')
    if type(max_depth) is not int or not 1 <= max_depth <= 4096:_fail('nesting limit')
    if _sha(source) != _pin(expected_source_sha256, 'source'):_fail('source SHA mismatch')
    _pin(css_sha256, 'CSS')
    if plain_chunks_are_interaction_only is not True:_fail('explicit style capability required')
    try:text = source.decode('utf-8')
    except UnicodeError as error:raise ValueError('Chunk intervals: source UTF8') from error
    if '\0' in text:_fail('source NUL parsing ambiguity')
    plans, sources = _plans(bindings)
    parser = _Compiler(source, text, plans, max_depth)
    parser.feed(text)
    parser.close()
    if any(f['plan'] or f['root_index'] is not None for f in parser.stack):_fail('unclosed example HTML')
    sentences = []
    for index, plan in sorted(plans.items()):
        if not plan['seen'] or set(plan['paragraphs']) != {'en', 'zh'}:_fail('missing selected root/paragraph')
        if any('result' not in p for p in plan['paragraphs'].values()):_fail('unclosed paragraph')
        sentences.append({'key':plan['binding'].key, 'root_index':index, 'source':plan['source_index'],
                          'paragraphs':[plan['paragraphs'][side]['result'] for side in ('en', 'zh')]})
    lexemes = _Table('')
    edits, parts, cursor, delta = [], [], 0, 0
    for start, end, replacement in sorted(parser.edits, key=lambda row:(row[0], row[1])):
        if start < cursor or end < start:_fail('overlapping byte edits')
        parts.extend((source[cursor:start], replacement))
        before = source[start:end]
        edits.append([start, start + delta, lexemes.add(before.decode()), lexemes.add(replacement.decode())])
        cursor = end
        delta += len(replacement) - len(before)
    parts.append(source[cursor:])
    compact = b''.join(parts)
    profile = {'schema':SCHEMA, 'version':1, 'offset_unit':'utf16',
               'anchors':{'root':ROOT_ATTRIBUTE, 'paragraph':PARAGRAPH_ATTRIBUTE},
               'source_sha256':expected_source_sha256, 'source_bytes':len(source),
               'compact_sha256':_sha(compact), 'compact_bytes':len(compact), 'css_sha256':css_sha256,
               'sources':sources, 'attributes':parser.attributes.rows, 'id_sets':parser.id_sets.rows,
               'segment_columns':SEGMENT_COLUMNS[:], 'edit_columns':EDIT_COLUMNS[:],
               'sentences':sentences, 'preserved_roots':sorted(parser.preserved, key=lambda r:r['root_index']),
               'lexemes':lexemes.rows, 'edits':edits,
               'stats':{'roots':len(sentences), 'paragraphs':2 * len(sentences), 'segments':parser.segment_count,
                        'removed_spans':parser.removed, 'retained_spans':parser.segment_count - parser.removed}}
    return CompiledIntervals(compact, profile)


def restore_html(compact, profile, *, expected_source_sha256, expected_profile_sha256):
    """Exact archive inverse, requiring external source AND profile SHA pins.

    This does not replace runtime canonical/DOM semantic validation. It never
    executes DDL/scripts, loads assets, normalizes HTML, or opens an old profile.
    """
    if type(compact) is not bytes or type(profile) is not dict:_fail('inverse input types')
    if _sha(profile_bytes(profile)) != _pin(expected_profile_sha256, 'profile'):_fail('profile SHA mismatch')
    fields = {'schema', 'version', 'offset_unit', 'anchors', 'source_sha256', 'source_bytes', 'compact_sha256',
              'compact_bytes', 'css_sha256', 'sources', 'attributes', 'id_sets', 'segment_columns', 'edit_columns',
              'sentences', 'preserved_roots', 'lexemes', 'edits', 'stats'}
    if (set(profile) != fields or profile['schema'] != SCHEMA or type(profile['version']) is not int or
            profile['version'] != 1 or profile['offset_unit'] != 'utf16' or
            profile['anchors'] != {'root':ROOT_ATTRIBUTE, 'paragraph':PARAGRAPH_ATTRIBUTE} or
            profile['edit_columns'] != EDIT_COLUMNS or profile['segment_columns'] != SEGMENT_COLUMNS):_fail('inverse schema')
    if profile['source_sha256'] != _pin(expected_source_sha256, 'source'):_fail('source SHA binding')
    if (type(profile['compact_bytes']) is not int or profile['compact_bytes'] != len(compact) or
            profile['compact_sha256'] != _sha(compact)):_fail('compact SHA/bytes mismatch')
    size, lexemes, edits = profile['source_bytes'], profile['lexemes'], profile['edits']
    if type(size) is not int or size < 0 or type(lexemes) is not list or not lexemes or lexemes[0] != '' or type(edits) is not list:
        _fail('inverse tables')
    if any(type(s) is not str for s in lexemes) or len(set(lexemes)) != len(lexemes):_fail('inverse lexemes')
    try:raw_lexemes = [s.encode('utf-8') for s in lexemes]
    except UnicodeError as error:raise ValueError('Chunk intervals: inverse lexeme UTF8') from error
    parts, cursor, source_end, delta = [], 0, 0, 0
    for row in edits:
        if type(row) is not list or len(row) != 4 or any(type(i) is not int or i < 0 for i in row):_fail('inverse edit row')
        at, compact_at, before_id, after_id = row
        if max(before_id, after_id) >= len(raw_lexemes):_fail('inverse lexeme reference')
        before, after = raw_lexemes[before_id], raw_lexemes[after_id]
        if (at < source_end or at + len(before) > size or compact_at != at + delta or compact_at < cursor or
                compact_at + len(after) > len(compact) or compact[compact_at:compact_at + len(after)] != after):_fail('inverse edit position/bytes')
        parts.extend((compact[cursor:compact_at], before))
        cursor, source_end = compact_at + len(after), at + len(before)
        delta += len(after) - len(before)
    parts.append(compact[cursor:])
    source = b''.join(parts)
    if len(source) != size or _sha(source) != expected_source_sha256:_fail('inverse source SHA/bytes mismatch')
    return source
