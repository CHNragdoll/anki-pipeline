"""Shared presentation revisions; native model IDs are book mapping data.

The registry stores references to common exact template/runtime components.
Original model/ZIP bytes remain immutable. Both output hosts resolve the same
current references, without a renderer branch for a title or edition year.
"""
from __future__ import annotations

import copy
import json

from . import study_catalog as c

REGISTRY = 'presentation.registry.v1'


def registry(db):
    row = db.execute('select value from metadata where key=%s', (REGISTRY,)).fetchone()
    return c.get_json(db, row[0]) if row else {'schema': REGISTRY, 'books': {}}


def register_book(db, book_id, col):
    """Append an idempotent binding. Existing revisions are never reset."""
    db.execute('select pg_advisory_xact_lock(%s)', (int(c.identity(REGISTRY)[:15], 16),))
    data = registry(db)
    if book_id in data['books']:
        return data['books'][book_id]
    models = {}
    for mid, model in json.loads(col['models']).items():
        parts = {'css': c.ensure_component(db, None, 'template:css', model['css'], scope='presentation')}
        for ordinal, template in enumerate(model['tmpls']):
            for side in ('qfmt', 'afmt'):
                name = f'template:{side}:{ordinal}'
                parts[f'{side}:{ordinal}'] = c.ensure_component(db, None, name, template[side], scope='presentation')
        models[mid] = parts
    resources = {}
    for name, key in db.execute('select name,object_id from resource_aliases where book_id=%s', (book_id,)):
        suffix = name.rsplit('.', 1)[-1].lower()
        if suffix not in {'js', 'css'}:
            continue
        text = c.get_object(db, key).decode('utf-8')
        resources[name] = c.ensure_component(db, None, 'runtime:' + suffix, text, scope='presentation')
    binding = {'models': models, 'resources': resources}
    data['books'][book_id] = binding
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (REGISTRY, c.put_json(db, data)))
    c.event(db, 'register-shared-presentation', {'book_id': book_id, 'models': len(models), 'resources': len(resources)})
    return binding


def install(value):
    from .study_catalog_export import require_ready
    with c.connect(value) as db, c.transaction(db):
        require_ready(db)
        for book_id, col_id in db.execute('select book_id,col_payload_id from book_sources order by book_id'):
            register_book(db, book_id, c.get_json(db, col_id))
    return {'schema': REGISTRY, 'installed': True}


def project(db, book_id, original):
    binding = registry(db)['books'].get(book_id, {})
    models = copy.deepcopy(json.loads(original['models']))
    for mid, parts in binding.get('models', {}).items():
        model = models[mid]
        for name, component in parts.items():
            row = db.execute('select current_id from components where id=%s', (component,)).fetchone()
            if row is None:
                raise ValueError('missing shared presentation component')
            text = c.get_object(db, row[0]).decode('utf-8')
            if name == 'css':
                model['css'] = text
            else:
                side, ordinal = name.split(':')
                model['tmpls'][int(ordinal)][side] = text
    resources = {}
    for name, component in binding.get('resources', {}).items():
        row = db.execute('select current_id from components where id=%s', (component,)).fetchone()
        if row is None:
            raise ValueError('missing shared runtime component')
        resources[name] = row[0]
    return models, resources
