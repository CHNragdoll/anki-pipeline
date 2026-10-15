"""Retain source catalogs and resolve legacy identities by exact original GUID."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import genanki

from . import study_catalog as c
from .study_catalog_export import require_ready


def retain_catalogs(value, manifest):
    retained = []
    with c.connect(value) as db, c.transaction(db):
        require_ready(db)
        for book in manifest['books']:
            if not book.get('catalog'):
                continue
            bid = book['id']; raw = Path(book['catalog']).read_bytes()
            sealed = db.execute('select s.manifest_id from book_sources b join sources s on s.id=b.source_id where b.book_id=%s', (bid,)).fetchone()
            if sealed is None or c.get_json(db, sealed[0])['catalog_sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError('catalog changed since its exact package binding')
            catalog = json.loads(raw)
            expected = {r[0] for r in db.execute('select source_card_id from notes where book_id=%s and source_card_id is not null', (bid,))}
            if expected != {entry['id'] for entry in catalog['cards']}:
                raise ValueError('source catalog no longer covers every native word note')
            key = c.put_object(db, raw); name = 'source.catalog.' + bid
            old = db.execute('select value from metadata where key=%s', (name,)).fetchone()
            if old and old[0] != key:
                raise ValueError('an existing source catalog cannot be silently replaced')
            if not old:
                db.execute('insert into metadata values(%s,%s)', (name, key))
                c.event(db, 'retain-source-catalog', {'book_id': bid, 'object_id': key, 'cards': len(expected)})
            retained.append({'book_id': bid, 'cards': len(expected), 'sha256': key})
    return retained


def archive_records(db, source, table):
    row = db.execute('select columns_id from archive_tables where source_id=%s and name=%s', (source, table)).fetchone()
    if row is None:
        raise ValueError('requested source table is absent')
    columns = c.get_json(db, row[0])
    with db.cursor(name='source_rows') as cursor:
        cursor.execute('select payload_id from archive_rows where source_id=%s and table_name=%s order by ordinal', (source, table))
        for key, in cursor:
            values = [c._unpack_cell(v) for v in c.get_json(db, key)]
            yield dict(zip(columns, values))


def bind_legacy(value):
    """An existing pipeline GUID is evidence; spelling similarity is not."""
    bindings = []
    with c.connect(value) as db, c.transaction(db):
        require_ready(db)
        for source, in db.execute("select id from sources where kind='legacy' order by id"):
            tables = {r[0] for r in db.execute('select name from archive_tables where source_id=%s', (source,))}
            if not {'cards', 'sentences', 'legacy_rows'}.issubset(tables):
                continue
            for card in archive_records(db, source, 'cards'):
                guid = genanki.guid_for('anki-rebuild-card-v1', card['id'])
                for bid, nid, wid, old in db.execute('select book_id,note_id,word_id,source_card_id from notes where guid=%s', (guid,)):
                    exact = db.execute('select surface from words where id=%s', (wid,)).fetchone()
                    if exact is None or exact[0] != card['word'] or old not in (None, card['id']):
                        raise ValueError('legacy GUID and exact word/card identity disagree')
                    if old is None:
                        db.execute('update notes set source_card_id=%s where book_id=%s and note_id=%s', (card['id'], bid, nid))
                    bindings.append({'book_id': bid, 'note_id': nid, 'source_id': source, 'card_id': card['id']})
        key = c.put_json(db, bindings)
        old = db.execute("select value from metadata where key='legacy.bindings.v1'").fetchone()
        if old and old[0] != key:
            raise ValueError('existing legacy bindings need an explicit migration')
        if not old:
            db.execute("insert into metadata values('legacy.bindings.v1',%s)", (key,))
            c.event(db, 'bind-legacy-identities', {'bindings': len(bindings), 'object_id': key})
    return {'schema': 'legacy.bindings.v1', 'bindings': len(bindings)}
