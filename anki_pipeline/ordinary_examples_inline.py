"""Restore ordinary examples at generation time, without changing their HTML.

The same function serves every book and host. Only ordinary-example storage
wrappers are removed; definitions, history disclosures and facts stay intact.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict

from .slim_apkg_content import Slices, apply, SCHEMA
from .slim_shared_codec import expand, prepare_dictionary

_REGISTRY = re.compile(r'window\.AnkiSlimAssets=window\.AnkiSlimAssets\|\|\{\};window\.AnkiSlimAssets\["([a-f0-9]{64})"\]=(.*);', re.S)


class PinnedMedia:
    """Read only inert, SHA-checked registrations through an explicit reader."""
    def __init__(self, read_resource):
        self.read_resource = read_resource
        self.dictionaries = OrderedDict()
        self.pending = set()

    def read(self, part):
        pin = part.get('sha256', '')
        if (not isinstance(pin, str) or not re.fullmatch('[a-f0-9]{64}', pin)
                or part.get('src') != '_as_' + pin[:24] + '.js'):
            raise ValueError('invalid ordinary-example content reference')
        if pin in self.pending:
            raise ValueError('cyclic ordinary-example media')
        self.pending.add(pin)
        try:
            raw = self.read_resource(part['src'].replace('_as_', '_ac_', 1))
            if raw is None:
                raw = self.read_resource(part['src'])
            if raw is None:
                raise ValueError('missing ordinary-example media: ' + pin)
            if isinstance(raw, bytes):
                raw = raw.decode('utf-8')
            match = _REGISTRY.fullmatch(raw)
            if not match or match[1] != pin:
                raise ValueError('ordinary-example media is not an exact inert registration')
            value = json.loads(match[2])
            if isinstance(value, dict):
                if value.get('schema') != 'anki-slim-shared-strings.v1':
                    raise ValueError('unknown ordinary-example packed schema')
                ref = value['dict']
                key = (ref.get('src'), ref.get('sha256'))
                dictionary = self.dictionaries.get(key)
                if dictionary is None:
                    bank = json.loads(self.read(ref))
                    if bank.get('schema') != 'anki-slim-shared-dictionary.v1':
                        raise ValueError('invalid ordinary-example dictionary')
                    dictionary = prepare_dictionary(bank['strings'])
                    self.dictionaries[key] = dictionary
                    while len(self.dictionaries) > 2:
                        self.dictionaries.popitem(last=False)
                else:
                    self.dictionaries.move_to_end(key)
                value = expand(value['pieces'], dictionary)
            if not isinstance(value, str) or hashlib.sha256(value.encode()).hexdigest() != pin:
                raise ValueError('ordinary-example decoded SHA differs')
            return value
        finally:
            self.pending.remove(pin)


def complete_examples(raw, store, *, _depth=0):
    """Expand only ordinary-list carriers, preserving every other source byte."""
    if 'as-lazy' not in raw:
        return raw
    if _depth >= 32:
        raise ValueError('ordinary-example nesting limit exceeded')
    edits = []
    for node in Slices(raw).nodes:
        if 'as-lazy' not in node.classes or node.attrs.get('data-as-kind') != 'examples':
            continue
        if any(start <= node.start < end for start, end, _ in edits):
            continue
        manifests = [child for child in node.children if 'as-manifest' in child.classes]
        if len(manifests) != 1:
            raise ValueError('ordinary-example carrier needs one manifest')
        script = manifests[0]
        value = json.loads(raw[script.opened:script.closed])
        if value.get('schema') != SCHEMA or not isinstance(value.get('parts'), list):
            raise ValueError('invalid ordinary-example manifest')
        parts = value['parts']
        if (type(value.get('total')) is not int or value['total'] < 0
                or any(type(part.get('count')) is not int or part['count'] < 0 for part in parts)
                or sum(part['count'] for part in parts) != value['total']):
            raise ValueError('ordinary-example part counts differ')
        body = ''.join(complete_examples(store.read(part), store, _depth=_depth + 1) for part in parts)
        edits.append((node.start, node.end, body))
    return apply(raw, edits)


def catalog_media(db, book):
    from . import study_catalog as c
    def read(name):
        generated = book['runtime']['generated'].get(name)
        if generated is not None:
            return generated
        row = db.execute('select object_id from resource_aliases where book_id=%s and name=%s',
                         (book['id'], name)).fetchone()
        return None if row is None else c.get_object(db, row[0])
    return PinnedMedia(read)
