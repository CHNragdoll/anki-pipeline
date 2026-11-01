"""Explicit book-unit overlays shared by native and Web projections.

Original imported collection/deck/card payloads remain immutable. A binding
changes only membership; it never changes note identities or scheduling data.
"""
from __future__ import annotations
import copy
import json
import time
from . import study_catalog as c

REGISTRY = 'book.units.v1'


def registry(db):
    row = db.execute('SELECT value FROM metadata WHERE key=%s', (REGISTRY,)).fetchone()
    return json.loads(row[0]) if row else {}


def validate(units, cards, native_ids):
    if not isinstance(units, dict) or not isinstance(cards, dict):
        raise ValueError('unit overlay requires explicit deck and card maps')
    if set(cards) != {str(value) for value in native_ids}:
        raise ValueError('unit mapping must cover every native card exactly once')
    names = set()
    for key, deck in units.items():
        if (not isinstance(key, str) or not key.isdecimal() or int(key) <= 0
                or type(deck) is not dict or deck.get('id') != int(key)
                or not isinstance(deck.get('name'), str) or not deck['name'].strip()
                or deck['name'] in names):
            raise ValueError('invalid or duplicate mapped deck')
        names.add(deck['name'])
    if any(type(unit) is not int or str(unit) not in units for unit in cards.values()):
        raise ValueError('card refers to an unknown mapped deck')


def install(db, book_id, units, cards, *, expected):
    """Caller holds a recoverable transaction; fail on stale mapping or coverage."""
    c.write_lock(db)
    row = db.execute('SELECT 1 FROM books WHERE id=%s', (book_id,)).fetchone()
    if not row:
        raise ValueError('unknown book')
    data = registry(db)
    if data.get(book_id) != expected:
        raise ValueError('stale book unit overlay')
    native_ids = [r[0] for r in db.execute('SELECT native_id FROM native_cards WHERE book_id=%s', (book_id,))]
    validate(units, cards, native_ids)
    previous = expected.get('mod', 0) if expected else 0
    value = {'units': units, 'cards': cards, 'mod': max(int(time.time()), previous + 1)}
    data[book_id] = value
    db.execute('INSERT INTO metadata VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (REGISTRY, c.canonical(data)))
    c.event(db, 'map-book-units', {'book_id': book_id, 'cards': len(cards), 'units': len(units)})
    return value


def project(db, book_id, original):
    binding = registry(db).get(book_id)
    if binding is None:
        return original, None
    native_ids = [r[0] for r in db.execute('SELECT native_id FROM native_cards WHERE book_id=%s', (book_id,))]
    validate(binding['units'], binding['cards'], native_ids)
    return copy.deepcopy(binding['units']), binding


def membership(book, native_id, original_id):
    binding = book.get('unit_overlay')
    unit = binding['cards'][str(native_id)] if binding else original_id
    return unit, book['units'][str(unit)]['name']
