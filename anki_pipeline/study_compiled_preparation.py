"""Explicit post-expansion protection before the shared producer seals inputs.

The base materializer remains independently versioned. Unchanged inputs keep
their exact original bytes and descriptors, including their existing cache key.
Changed inputs retain their base artifact and bind the lossless normalizer in
the new input itself; the ordinary producer/profile checks then run unchanged.
"""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

from . import study_catalog_web as web
from . import study_catalog_web_materialize as materialize
from . import study_expanded_field_scripts as protection


def source_pins():
    return {**protection.source_pins(),
            'preparation_stage_sha256': materialize.digest(Path(__file__).read_bytes())}


def normalize_artifact(raw, wrapper_raw, media):
    """Return the original bytes on a no-op; never rewrite the source wrapper."""
    value = json.loads(raw)
    payload = web.card_payload(wrapper_raw)
    sources = json.loads(payload)
    if (value.get('schema') != 'study-prepared-card.v1' or
            value.get('source_wrapper_sha256') != materialize.digest(wrapper_raw) or
            value.get('source_payload_sha256') != materialize.digest(payload) or
            not isinstance(sources, list) or len(sources) != 2 or
            not isinstance(value.get('sides'), list) or len(value['sides']) != 2 or
            'field_script_normalization' in value):
        raise ValueError('normalization requires an original bound two-sided artifact')
    updated = copy.deepcopy(value)
    changes = []
    for ordinal, (source, side) in enumerate(zip(sources, value['sides'])):
        if (not isinstance(source, str) or not isinstance(side, dict) or
                not isinstance(side.get('html'), str) or
                side.get('proof', {}).get('source_sha256') != materialize.digest(source) or
                side['proof'].get('expanded_sha256') != materialize.digest(side['html'])):
            raise ValueError('normalization base side source/expanded pins differ')
        result = protection.normalize_side(source, side, media, context='side-' + str(ordinal))
        if result['html'] == side['html']:
            continue
        updated['sides'][ordinal]['html'] = result['html']
        updated['sides'][ordinal]['proof']['expanded_sha256'] = materialize.digest(result['html'])
        updated['sides'][ordinal]['proof']['expanded_bytes'] = len(result['html'].encode('utf-8'))
        changes.append({'side': ordinal, 'evidence': result['evidence']})
    if not changes:
        return raw, None
    provenance = {'schema': 'study-prepared-field-normalization.v1',
                  'base_artifact_sha256': materialize.digest(raw),
                  'sources': source_pins(), 'changes': changes}
    updated['field_script_normalization'] = provenance
    return materialize._compiled_json(updated), provenance


def normalize_library(root, catalog, prepared, *, callback=None):
    """One shared stage for every book; called before any semantic/profile work."""
    root = Path(root)
    config = prepared['config']
    if config.get('compiledDelivery'):
        raise ValueError('normalization must precede profile sealing')
    descriptor = config['preparedIndex']
    original_index = materialize._compiled_output(root, descriptor)
    index = json.loads(original_index)
    if (index.get('schema') != 'study-prepared-index.v1' or
            set(index.get('cards', {})) != {row['id'] for row in catalog['cards']}):
        raise ValueError('normalization requires complete original prepared coverage')
    report = {'schema': 'study-prepared-field-normalization-batch.v1',
              'sources': source_pins(), 'cards': len(catalog['cards']),
              'changed': [], 'unchanged': 0, 'base_index': dict(descriptor)}
    media = materialize.ReadOnlyMedia(root / 'media')
    with materialize._CompiledWebOutput(root / 'evidence') as output:
        def put(prefix, suffix, data):
            return 'evidence/' + output.publish(prefix, suffix, data)

        for ordinal, card in enumerate(catalog['cards'], 1):
            rule = index['cards'][card['id']]
            raw = materialize._compiled_output(root, rule)
            from .study_catalog_web_delivery import _read
            wrapper_raw, _ = _read(root / card['url'], limit=64 * 1024 * 1024)
            normalized, provenance = normalize_artifact(raw, wrapper_raw, media)
            if provenance is None:
                report['unchanged'] += 1
            else:
                value = json.loads(normalized)
                pin = materialize.digest(normalized)
                original_front = json.loads(materialize._compiled_output(root, rule['front']))
                expected_front = materialize.front_artifact_bytes(
                    card, original_front['source_front'], json.loads(raw), rule['sha256'])
                if expected_front != materialize._compiled_output(root, rule['front']):
                    raise ValueError('normalization base front differs')
                front = materialize.front_artifact_bytes(card, original_front['source_front'], value, pin)
                index['cards'][card['id']] = {
                    'src': put('_study_prepared_card_', '.json', normalized), 'sha256': pin,
                    'gzipSrc': put('_study_prepared_card_', '.json.gz', gzip.compress(normalized, compresslevel=6, mtime=0)),
                    'front': {'src': put('_study_prepared_front_', '.json', front),
                              'sha256': materialize.digest(front),
                              'gzipSrc': put('_study_prepared_front_', '.json.gz', gzip.compress(front, compresslevel=6, mtime=0))}}
                report['changed'].append({'id': card['id'], 'base': dict(rule),
                                          'normalized': copy.deepcopy(index['cards'][card['id']]),
                                          'proof': provenance})
            if callback and (ordinal % 100 == 0 or ordinal == len(catalog['cards'])):
                callback({'stage': 'export-web-field-protection', 'book_id': catalog['book_id'],
                          'completed': ordinal, 'total': len(catalog['cards']),
                          'changed': len(report['changed']), 'unchanged': report['unchanged']})
        if not report['changed']:
            return {**prepared, 'normalization': report}
        data = materialize._compiled_json(index)
        updated_config = {**config, 'preparedIndex': {
            'src': put('_study_prepared_index_', '.json', data), 'sha256': materialize.digest(data),
            'gzipSrc': put('_study_prepared_index_', '.json.gz', gzip.compress(data, compresslevel=9, mtime=0))}}
    return {**prepared, 'config': updated_config, 'normalization': report}
