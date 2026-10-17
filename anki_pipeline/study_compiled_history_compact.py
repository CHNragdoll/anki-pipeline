"""Reversible delivery derivation of an immutable completed semantic result.

This does not rerun or claim to rerun semantic preparation. Only initial AF PRE
copies with their original closed, plain DETAILS owner return to the original
placeholder. The source AF resources and every original position are retained.
"""
from __future__ import annotations

from array import array
import copy
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
import time

_KEY = 'data-study-compiled-key'
_HASH = re.compile(r'[a-f0-9]{64}')
_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_LEGACY_LIMIT = 256 * 1024 * 1024
_DELIVERY_LIMIT = 128 * 1024 * 1024


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def _escape(text, *, attribute=False):
    text = text.replace('&', '&amp;').replace('\u00a0', '&nbsp;')
    return text.replace('"', '&quot;') if attribute else text.replace('<', '&lt;').replace('>', '&gt;')


def _pre(attrs, text):
    return '<pre' + ''.join(' ' + k + '="' + _escape(v, attribute=True) + '"' for k, v in attrs) + '>' + _escape(text) + '</pre>'


class _Scan(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lines = array('Q', [0])
        self.lines.extend(match.end() for match in re.finditer('\n', html))
        self.stack, self.nodes, self.active = [], [], None

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if self.active is not None:
            raise ValueError('prepared initial history text contains an element')
        excluded = any(name == 'template' for name, _ in self.stack)
        if tag == 'pre' and not excluded and any(k in {'data-native-history-media', 'data-native-history-sha'} for k, _ in attrs):
            parent = self.stack[-1] if self.stack else (None, [])
            self.active = {'start': self.source_offset(), 'inner_start': self.source_offset() + len(self.get_starttag_text()),
                           'attrs': attrs, 'owner': parent,
                           'foreign_ancestor': any(name in {'svg', 'math'} for name, _ in self.stack)}
        if tag not in _VOID:
            self.stack.append((tag, attrs))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError('completed HTML element boundary differs')
        if self.active is not None:
            if tag != 'pre':
                raise ValueError('prepared initial history PRE boundary differs')
            start = self.source_offset()
            end = self.html.find('>', start, start + 16)
            if end < 0 or self.html[start:end + 1] != '</pre>':
                raise ValueError('prepared initial history PRE closing tag differs')
            self.active.update(inner_end=start, end=end + 1)
            self.nodes.append(self.active)
            self.active = None
        self.stack.pop()

    def handle_comment(self, data):
        if self.active is not None:
            raise ValueError('prepared initial history text contains a comment')

    def finish(self):
        self.feed(self.html)
        self.close()
        if self.stack or self.active is not None:
            raise ValueError('completed HTML element boundary is incomplete')
        return self.nodes


def compact_html(html, initial_proof):
    """Qualify every initial PRE before returning any derived bytes or proof."""
    if not isinstance(html, str) or not isinstance(initial_proof, list):
        raise ValueError('initial history compaction inputs')
    nodes = _Scan(html).finish()
    if len(nodes) != len(initial_proof):
        raise ValueError('initial history evidence census differs')
    proof = copy.deepcopy(initial_proof)
    plans = []
    for ordinal, (node, item) in enumerate(zip(nodes, proof)):
        if not isinstance(item, dict):
            raise ValueError('initial history original proof shape differs')
        attrs = node['attrs']
        original_attrs = item.get('original_attributes')
        if (not isinstance(original_attrs, list) or any(not isinstance(pair, list) or len(pair) != 2 or
                any(not isinstance(value, str) for value in pair) for pair in original_attrs) or
                len({pair[0] for pair in original_attrs}) != len(original_attrs)):
            raise ValueError('initial history original attributes differ')
        original_text = item.get('original_text')
        original = _pre(original_attrs, original_text) if isinstance(original_text, str) else ''
        if (not isinstance(original_text, str) or item.get('ordinal') != ordinal or item.get('inverse_exact') is not True or
                not _HASH.fullmatch(item.get('sha256', '')) or
                not _HASH.fullmatch(item.get('resource_sha256', '')) or
                not re.fullmatch(r'_af_[a-f0-9]{24}\.js', item.get('media', '')) or
                item.get('complete_text_sha256') != item['sha256'] or
                _sha(original_text.encode()) != item.get('original_text_sha256') or
                _sha(original.encode()) != item.get('original_pre_dom_sha256')):
            raise ValueError('initial history original proof differs')
        wanted_attrs = list(map(list, original_attrs))
        ready = next((pair for pair in wanted_attrs if pair[0] == 'data-native-history-ready'), None)
        if ready is None:
            wanted_attrs.append(['data-native-history-ready', 'true'])
        else:
            ready[1] = 'true'
        without_key = [list(pair) for pair in attrs if pair[0] != _KEY]
        actual = dict(attrs)
        before = html[node['start']:node['end']]
        key = [(k, v) for k, v in attrs if k == _KEY]
        if len(key) > 1 or any(value is None for _, value in attrs):
            raise ValueError('initial history prepared attributes differ')
        unkeyed_start = '<pre' + ''.join(' ' + k + '="' + _escape(v, attribute=True) + '"' for k, v in attrs if k != _KEY) + '>'
        unkeyed = unkeyed_start + html[node['inner_start']:node['end']]
        if (without_key != wanted_attrs or actual.get('data-native-history-media') != item['media'] or
                actual.get('data-native-history-sha') != item['sha256'] or
                _sha(unkeyed.encode()) != item.get('prepared_pre_dom_sha256') or
                _sha(unescape(html[node['inner_start']:node['inner_end']]).encode()) != item['sha256']):
            raise ValueError('initial history prepared text/DOM proof differs')
        owner_tag, owner_attrs = node['owner']
        owner = dict(owner_attrs)
        if (owner_tag != 'details' or 'open' in owner or 'class' in owner or 'is' in owner or 'is' in actual or
                node['foreign_ancestor'] or
                dict(original_attrs).get('data-native-history-ready') not in {None, 'false'}):
            continue  # Visible, classed or already-complete source evidence stays exact.
        if item.get('preparation', 'expanded') != 'expanded':
            raise ValueError('initial history compaction requires the immutable expanded parent')
        after = _pre(original_attrs + [list(pair) for pair in key], original_text)
        item['preparation'] = 'deferred-closed'
        item['prepared_pre_dom_sha256'] = item['original_pre_dom_sha256']
        plans.append({**node, 'before_sha256': _sha(before.encode()), 'after': after,
                      'after_sha256': _sha(after.encode()), 'ordinal': ordinal,
                      'original_prepared_pre_dom_sha256': initial_proof[ordinal]['prepared_pre_dom_sha256']})
    pieces, at, byte_at, inverse = [], 0, 0, hashlib.sha256()
    edits = []
    for plan in plans:
        unchanged = html[at:plan['start']]
        pieces.extend((unchanged, plan['after']))
        unchanged_raw = unchanged.encode()
        before_raw = html[plan['start']:plan['end']].encode()
        inverse.update(unchanged_raw)
        inverse.update(before_raw)
        edits.append({name: plan[name] for name in ('ordinal', 'start', 'end', 'before_sha256',
                     'after_sha256', 'original_prepared_pre_dom_sha256')})
        edits[-1].update(start_byte=byte_at + len(unchanged_raw),
                         end_byte=byte_at + len(unchanged_raw) + len(before_raw),
                         after_bytes=len(plan['after'].encode()))
        byte_at += len(unchanged_raw) + len(before_raw)
        at = plan['end']
    pieces.append(html[at:])
    inverse.update(html[at:].encode())
    source_pin = _sha(html.encode())
    if inverse.hexdigest() != source_pin:
        raise ValueError('initial history compaction inverse differs')
    derived = ''.join(pieces)
    if len(derived.encode()) > _DELIVERY_LIMIT:
        raise ValueError('compacted delivery remains beyond the existing HTML byte limit')
    return {'html': derived, 'initial_proof': proof, 'edits': edits,
            'source_sha256': source_pin, 'inverse_sha256': inverse.hexdigest(),
            'derived_sha256': _sha(derived.encode())}


def _read(descriptor, *, root=None, limit=64 * 1024 * 1024):
    if (not isinstance(descriptor, dict) or not _HASH.fullmatch(descriptor.get('sha256', '')) or
            not isinstance(descriptor.get('path'), str)):
        raise ValueError('compaction requires an explicit pinned descriptor')
    path = Path(descriptor['path'])
    if root is not None:
        if path.name != str(path) or str(path) in {'.', '..'} or '\\' in str(path):
            raise ValueError('invalid completed semantic child')
        path = root / path
    elif not path.is_absolute():
        raise ValueError('compaction input path must be absolute')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('compaction source must be a bounded regular file')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    stamp = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if (stamp(before) != stamp(after) or len(raw) != before.st_size or _sha(raw) != descriptor['sha256'] or
            'bytes' in descriptor and descriptor['bytes'] != len(raw)):
        raise ValueError('compaction source pin/size changed')
    return raw


def compact_semantic_result(semantic_request, producer_report, destination):
    """Publish a new, explicitly derived report; never edit the parent snapshot."""
    started = time.monotonic()
    helper_raw = Path(__file__).read_bytes()
    request_raw, parent_raw = _read(semantic_request), _read(producer_report)
    request, parent = json.loads(request_raw), json.loads(parent_raw)
    if (request.get('schema') != 'study-compiled-semantic-request.v1' or
            parent.get('schema') != 'study-compiled-semantic-result.v1' or
            parent.get('real_native_ready') is not True or parent.get('pure_semantic_only') is not True or
            parent.get('authored_startup_executed') is not False or 'initial_history_compaction' in parent):
        raise ValueError('compaction requires an original completed semantic result')
    root = Path(producer_report['path']).parent
    children = {name: _read(parent[name], root=root, limit=_LEGACY_LIMIT if name == 'final_html' else 64 * 1024 * 1024)
                for name in ('final_html', 'bindings', 'source_proof', 'reconciliation', 'capture_inverse', 'metadata')}
    if parent.get('initial_numbering') is not None:
        children['initial_numbering'] = _read(parent['initial_numbering'], root=root)
    names = [parent[name]['path'] for name in children]
    if len(names) != len(set(names)) or set(names) & {'report.json', 'initial-history-compaction.json', 'compaction-helper.py'}:
        raise ValueError('compaction child output names collide')
    source_proof = json.loads(children['source_proof'])
    if (source_proof.get('request_sha256') != _sha(request_raw) or
            source_proof.get('artifact_sha256') != request.get('artifact', {}).get('sha256')):
        raise ValueError('compaction semantic request/source proof binding differs')
    for source in parent.get('sources', []):
        _read(source)
    result = compact_html(children['final_html'].decode('utf-8'), source_proof.get('initial_history_evidence', []))
    proof = {'schema': 'study-initial-history-compaction.v1',
             'parent_request': dict(semantic_request), 'parent_report': dict(producer_report),
             'helper_sha256': _sha(helper_raw),
             'source_html_sha256': result['source_sha256'], 'derived_html_sha256': result['derived_sha256'],
             'inverse_html_sha256': result['inverse_sha256'], 'edits': result['edits'],
             'offset_unit': 'unicode-codepoints+utf8-bytes',
             'semantic_preparation_rerun': False, 'original_positions_and_AF_resources_retained': True,
             'source_fields_counts_and_occurrence_ids_unchanged': True,
             'elapsed_ms': round((time.monotonic() - started) * 1000)}
    if Path(__file__).read_bytes() != helper_raw:
        raise ValueError('compaction helper changed during the derivation')
    destination = Path(destination).absolute()
    destination.mkdir()  # All source qualification precedes destination creation.
    def store(name, raw):
        with (destination / name).open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return {'path': name, 'sha256': _sha(raw), 'bytes': len(raw)}
    store('compaction-helper.py', helper_raw)
    compaction = store('initial-history-compaction.json', _json(proof))
    source_proof['initial_history_evidence'] = result['initial_proof']
    source_proof['initial_history_compaction'] = compaction
    reconciliation = json.loads(children['reconciliation'])
    reconciliation['initial_history_compaction'] = compaction
    report = copy.deepcopy(parent)
    for name, raw in children.items():
        if name == 'final_html':
            raw = result['html'].encode()
        elif name == 'source_proof':
            raw = _json(source_proof)
        elif name == 'reconciliation':
            raw = _json(reconciliation)
        report[name] = store(parent[name]['path'], raw)
    report['initial_history_compaction'] = compaction
    descriptor = store('report.json', _json(report))
    return {**descriptor, 'path': str(destination / descriptor['path'])}
