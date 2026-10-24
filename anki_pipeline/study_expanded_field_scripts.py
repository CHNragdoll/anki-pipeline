"""Versioned carrier protection for already authenticated expanded HTML.

This is a preparation transform, never an admission exception in the browser.
The caller authenticates the source fragment against its external descriptor;
existing carriers are checked and retained byte for byte. Removing only newly
added carriers recovers the exact input. The base materializer and registered
inline field projector deliberately remain unchanged.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from . import study_field_scripts as fields

SCHEMA = 'study-expanded-field-script.v1'
_CARRIER_ATTRS = frozenset(('hidden', 'style', 'aria-hidden',
    'data-study-script-transport', 'data-study-script-key',
    'data-study-script-sha256', fields.MARKER))
_HASH = re.compile('[a-f0-9]{64}')


def _sha(value):
    return hashlib.sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def source_pins():
    return {'normalizer_sha256': _sha(Path(__file__).read_bytes()),
            **fields.source_pins()}


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError('duplicate existing carrier payload key')
        result[key] = value
    return result


class _Scripts(fields._Scripts):
    """Use the original grammar, allowing only exact empty carrier spans."""
    def __init__(self, raw):
        self.carriers, self.carrier = [], None
        super().__init__(raw)
        if self.carrier is not None:
            raise ValueError('unclosed existing field-script carrier')

    def handle_starttag(self, tag, attrs):
        if self.carrier is not None:
            raise ValueError('existing field-script carrier is not empty')
        if any(name.startswith('data-study-script-') for name, _ in attrs):
            attrs = [(name, (value or '').replace('\r\n', '\n').replace('\r', '\n'))
                     for name, value in attrs]
            values = dict(attrs)
            if (tag != 'span' or len(attrs) != len(_CARRIER_ATTRS) or set(values) != _CARRIER_ATTRS
                    or values['hidden'] != '' or values['aria-hidden'] != 'true'
                    or values['style'] != 'display:none!important'
                    or values['data-study-script-transport'] != 'v1'):
                raise ValueError('existing field-script carrier shape differs')
            start = self.absolute_offset()
            self.carrier = {'start': start, 'opened': start + len(self.get_starttag_text()),
                            'attrs': values}
            self.stack.append(tag)
            return
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.carrier is not None:
            if tag != 'span' or self.absolute_offset() != self.carrier['opened']:
                raise ValueError('existing field-script carrier is not empty')
            self.carriers.append(self.carrier)
            self.carrier = None
        super().handle_endtag(tag)


def _validate_existing(parser):
    by_end = {row['end']: row for row in parser.rows}
    paired, keys = set(), set()
    for carrier in parser.carriers:
        attrs = carrier['attrs']
        key, pin = attrs['data-study-script-key'], attrs['data-study-script-sha256']
        if not re.fullmatch('[a-f0-9]{64}:\\d+', key) or not _HASH.fullmatch(pin) or key in keys:
            raise ValueError('existing field-script carrier identity differs')
        keys.add(key)
        encoded = attrs[fields.MARKER]
        try:
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode('ascii') != encoded or _sha(raw) != pin:
                raise ValueError('existing field-script carrier SHA/Base64 differs')
            payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
        except (UnicodeError, ValueError) as error:
            raise ValueError('existing field-script carrier payload differs') from error
        row = by_end.get(carrier['start'])
        if row is None:
            raise ValueError('unpaired/moved existing field-script carrier')
        expected = {name: row[name] for name in ('attrs', 'text', 'parent', 'kind')}
        expected['attrs'] = [list(value) for value in row['attrs']]
        # Top-level source fields intentionally have no parent constraint;
        # rendering puts them in the template's already checked safe element.
        if isinstance(payload, dict) and payload.get('parent') is None:
            expected['parent'] = None
        expected['schema'] = fields.SCHEMA
        if payload != expected:
            raise ValueError('existing field-script carrier source differs')
        if row['kind'] == 'cigen' and _sha(row['text']) not in fields.CIGEN_PINS:
            raise ValueError('unverified existing Cigen field bridge')
        paired.add(row['start'])
    return paired


def protect_authenticated_fragment(raw, *, expected_sha256, context):
    """Protect a pinned fragment before producer/profile sealing.

    ``expected_sha256`` must come from the caller's authenticated source graph,
    not a hash invented to accept mutable input. ``context`` is a deterministic
    per-insertion identity, so repeated use of one source asset gets distinct
    carrier keys. This function neither loads resources nor changes source files.
    Newly introduced executable Cigen bridges need a controller capability and
    are intentionally rejected; existing authenticated bridges remain intact.
    """
    if (type(raw) is not str or type(expected_sha256) is not str
            or not _HASH.fullmatch(expected_sha256) or _sha(raw) != expected_sha256):
        raise ValueError('expanded fragment differs from its external SHA pin')
    if type(context) is not str or not context or len(context) > 1024 or '\x00' in context:
        raise ValueError('bounded explicit expanded-fragment context required')
    parser = _Scripts(raw)
    paired = _validate_existing(parser)
    field_key = _sha(SCHEMA + '\x00' + context + '\x00' + raw)
    edits = []
    for ordinal, row in enumerate(parser.rows):
        if row['start'] in paired:
            continue
        if row['kind'] == 'cigen':
            raise ValueError('expanded Cigen bridge lacks its explicit controller capability')
        payload = {name: row[name] for name in ('attrs', 'text', 'parent', 'kind')}
        payload['schema'] = fields.SCHEMA
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        carrier = ('<span hidden="" style="display:none!important" aria-hidden="true" '
                   'data-study-script-transport="v1" data-study-script-key="' + field_key + ':' + str(ordinal) + '" '
                   'data-study-script-sha256="' + _sha(encoded) + '" '
                   + fields.MARKER + '="' + base64.b64encode(encoded).decode('ascii') + '"></span>')
        edits.append((row['end'], carrier))
    pieces, removed, cursor, output_offset = [], [], 0, 0
    for at, carrier in edits:
        prefix = raw[cursor:at]
        pieces.extend((prefix, carrier))
        output_offset += len(prefix)
        removed.append((output_offset, output_offset + len(carrier)))
        output_offset += len(carrier)
        cursor = at
    pieces.append(raw[cursor:])
    result = ''.join(pieces) if edits else raw
    inverse, cursor = [], 0
    for start, end in removed:
        inverse.append(result[cursor:start])
        cursor = end
    inverse.append(result[cursor:])
    inverse = ''.join(inverse)
    if inverse != raw:
        raise ValueError('expanded carrier exact inverse differs')
    return {'html': result, 'proof': {'schema': SCHEMA,
            'source_sha256': expected_sha256, 'expanded_sha256': _sha(result),
            'added_carriers': len(edits), 'verified_carriers': len(paired),
            'context': context}}


def normalize_side(source, side, media, *, context='side'):
    """Normalize one original prepared side without changing its base factory.

    Only a source document already using the registered field transport opts
    into this transform. A changed side must exactly equal the base factory's
    recomputation from the original source and SHA-authenticated media graph.
    The outer preparer owns resealing the side/artifact/front/index descriptors.
    No-op callers must retain their original serialized bytes and descriptors.
    """
    if type(source) is not str or type(side) is not dict or type(side.get('html')) is not str:
        raise ValueError('explicit source and prepared HTML side required')
    if fields.MARKER not in source:
        return {'html': side['html'], 'evidence': {'schema': SCHEMA, 'changed': False}}
    original = _Scripts(source)
    paired = _validate_existing(original)
    if len(paired) != len(original.rows):
        raise ValueError('original source has an unpaired field transport')
    if not paired:
        return {'html': side['html'], 'evidence': {'schema': SCHEMA, 'changed': False}}
    proof = side.get('proof', {})
    if (type(proof) is not dict or proof.get('source_sha256') != _sha(source)
            or proof.get('expanded_sha256') != _sha(side['html'])):
        raise ValueError('prepared source/expanded side pin differs')
    result = protect_authenticated_fragment(side['html'],
        expected_sha256=proof['expanded_sha256'], context=context)
    if not result['proof']['added_carriers']:
        return {'html': side['html'], 'evidence': {'schema': SCHEMA, 'changed': False}}
    fragments = {}

    class AuthenticatedMedia:
        def __getattr__(self, name):
            return getattr(media, name)

        def read(self, part):
            raw = media.read(part)
            pin = part.get('sha256')
            if type(raw) is not str or type(pin) is not str or _sha(raw) != pin:
                raise ValueError('expanded media returned text outside its exact pin')
            fragments[pin] = {'sha256': pin, 'bytes': len(raw.encode('utf-8')),
                              **({'src': part['src']} if part.get('src') is not None else {})}
            return raw

    from .study_catalog_web_materialize import materialize_side
    actual = materialize_side(source, AuthenticatedMedia())
    if actual != side:
        raise ValueError('prepared side differs from its authenticated base materialization')
    return {'html': result['html'], 'evidence': {'schema': SCHEMA, 'changed': True,
        **{key: value for key, value in result['proof'].items() if key != 'schema'},
        'source_sha256': _sha(source), 'base_expanded_sha256': proof['expanded_sha256'],
        'sources': source_pins(),
        'authenticated_fragments': [fragments[pin] for pin in sorted(fragments)]}}
