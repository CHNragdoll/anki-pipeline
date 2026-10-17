"""Explicit backward-compatible binder admission for completed deliveries."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from urllib.parse import urljoin

LEGACY_RUNTIME_SHA256 = 'e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc'
PREVIOUS_RUNTIME_SHA256 = 'f703169353965e8d74d2c5a9ef7e2b49be3a99d75cf6be97571304d41fb3c93b'
SUPPLEMENTAL_RUNTIME_SHA256 = '99ec0aeda2483b4cba389f1c802a96ccdd4c00af618cedbe72e07e423b85a593'
CURRENT_RUNTIME_SHA256 = '79736762ee2abba0461ae034ca2de577402df007a87576a2ed32916779ad66e9'
ADMITTED_RUNTIME_SHA256 = frozenset((LEGACY_RUNTIME_SHA256, PREVIOUS_RUNTIME_SHA256,
                                    SUPPLEMENTAL_RUNTIME_SHA256, CURRENT_RUNTIME_SHA256))
_SIZES = {LEGACY_RUNTIME_SHA256: 27260, PREVIOUS_RUNTIME_SHA256: 29243,
          SUPPLEMENTAL_RUNTIME_SHA256: 30040, CURRENT_RUNTIME_SHA256: 30784}


def upgrade_delivery_runtime(result, store):
    """Reuse exact completed HTML/profile; record the compatible host upgrade.

    Source/semantic evidence remains the original build record. The separate
    projection explicitly records the new delivery binder, rather than changing
    that historic record or rerunning its producer.
    """
    result = copy.deepcopy(result)
    if result.get('mode') != 'compiled':
        return result
    runtime = result.get('runtime', {})
    previous = runtime.get('sha256')
    if previous not in ADMITTED_RUNTIME_SHA256:
        raise ValueError('unsupported completed binder version')
    matches = [(url, item) for url, item in result.get('resources', {}).items()
               if isinstance(item, dict) and isinstance(item.get('path'), str)
               and item.get('sha256') == previous and Path(item['path']).name == runtime.get('src')]
    if len(matches) != 1:
        raise ValueError('completed binder needs one explicit original resource')
    url, old = matches[0]
    if old.get('bytes') != _SIZES[previous]:
        raise ValueError('completed binder length differs')
    with Path(old['path']).open('rb') as source:
        raw = source.read(_SIZES[previous] + 1)
    if hashlib.sha256(raw).hexdigest() != previous or len(raw) != old['bytes']:
        raise ValueError('completed binder resource differs')
    origin = previous
    projection = result.get('runtime_projection')
    if projection is not None:
        origin = projection.get('from_sha256') if isinstance(projection, dict) else None
        expected = {'schema': 'study-compatible-binder-projection.v1',
                    'source_build_record': result['record'], 'from_sha256': origin,
                    'to_sha256': previous, 'html': result['entry']['html'],
                    'profile': result['entry']['profile'], 'body_profile_bytes_unchanged': True}
        if origin not in ADMITTED_RUNTIME_SHA256 or origin == previous or projection != expected:
            raise ValueError('completed binder projection differs')
    if previous == CURRENT_RUNTIME_SHA256:
        return result
    current = Path(__file__).with_name('compiled').joinpath('card-runtime.js').read_bytes()
    if hashlib.sha256(current).hexdigest() != CURRENT_RUNTIME_SHA256:
        raise ValueError('current compatible binder source differs')
    asset = store.put(current, 'js')
    result['runtime'] = asset
    result['resources'][urljoin(url, asset['src'])] = store.descriptor(asset)
    projection = {'schema': 'study-compatible-binder-projection.v1',
                  'source_build_record': result['record'], 'from_sha256': origin,
                  'to_sha256': CURRENT_RUNTIME_SHA256, 'html': result['entry']['html'],
                  'profile': result['entry']['profile'], 'body_profile_bytes_unchanged': True}
    result['runtime_projection'] = projection
    return result
