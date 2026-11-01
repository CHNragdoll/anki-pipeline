"""Scoped, identity-preserving refresh of an existing general exam source.

The caller owns the transaction. Raw imports remain immutable; current fields,
new questions and the source skeleton are changed under one catalog write lock.
Neither learner tables nor other books are written.
"""
from __future__ import annotations
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

import genanki
from . import study_catalog as c
from .study_catalog_import import insert, _zip_info
from .study_catalog_anki import bump_content_mods
from . import study_catalog_units as units
from .study_catalog_export import require_ready, project_book, project_note
from .study_exam_package import FIELDS, _number


def _identity(fields, guid, book_id):
    record = json.loads(html.unescape(fields[FIELDS.index('SourceRecord')]))
    key = record['paper']['id'] + ':' + record['question']['id']
    if guid != genanki.guid_for('anki-pipeline/exam-question/v1', book_id, key):
        raise ValueError('exam GUID differs from explicit source question key')
    if fields[FIELDS.index('Status')] not in {'available', 'missing', 'pending'}:
        raise ValueError('unsupported source answer status')
    year = str(record['paper']['year'])
    kind = {'single_choice': '单选题', 'multiple_choice': '多选题',
            'free_response': '材料分析题'}[record['question']['questionType']]
    return key, year + ' 年::' + kind


def _load(package, book_id):
    raw = Path(package).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(Path(package)) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('duplicate source package member')
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        try:
            db.deserialize(archive.read('collection.anki2'))
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('source collection corrupt')
            col = dict(db.execute('SELECT * FROM col').fetchone())
            models = json.loads(col['models']); entries = []; seen = set()
            for row in db.execute('SELECT * FROM notes ORDER BY id'):
                note = dict(row); fields = note.pop('flds').split('\x1f')
                model = models[str(note['mid'])]
                if tuple(f['name'] for f in model['flds']) != FIELDS or len(fields) != len(FIELDS):
                    raise ValueError('exam field schema differs')
                key, path = _identity(fields, note['guid'], book_id)
                if key in seen: raise ValueError('duplicate source question')
                seen.add(key)
                cards = list(db.execute('SELECT * FROM cards WHERE nid=?', (note['id'],)))
                if len(cards) != 1 or cards[0]['ord'] != 0:
                    raise ValueError('exam question requires exactly one card')
                entries.append({'note': note, 'fields': fields, 'key': key,
                                'path': path, 'card': dict(cards[0])})
            media = json.loads(archive.read('media')); resources = {}
            if len(set(media.values())) != len(media): raise ValueError('duplicate media alias')
            for member, name in media.items():
                if not member.isdecimal() or Path(name).name != name or '\\' in name:
                    raise ValueError('unsafe media alias')
                resources[name] = (archive.read(member), _zip_info(archive.getinfo(member)))
            return digest, entries, resources
        finally: db.close()


def _backup(db, book_id, backup_dir):
    saved = {'schema': 'study-exam-refresh-backup.v1', 'book_id': book_id, 'tables': {}}
    for table, column in [('books','id'), ('book_sources','book_id'), ('units','book_id'),
                          ('notes','book_id'), ('note_fields','book_id'),
                          ('native_cards','book_id'), ('resource_aliases','book_id')]:
        cur = db.execute('SELECT * FROM '+table+' WHERE '+column+'=%s', (book_id,))
        saved['tables'][table] = {'columns': [d.name for d in cur.description],
                                 'rows': [list(r) for r in cur]}
    component_ids = [r[0] for r in db.execute('SELECT component_id FROM note_fields WHERE book_id=%s', (book_id,))]
    saved['components'] = [list(r) for r in db.execute('SELECT * FROM components WHERE id=ANY(%s)', (component_ids,))]
    saved['metadata'] = dict(db.execute('SELECT key,value FROM metadata'))
    saved['revision'] = db.execute('SELECT coalesce(max(id),0) FROM component_revisions').fetchone()[0]
    saved['recovery'] = 'Retain immutable objects and prior sources. Restore only these book rows/component pointers and changed metadata entries under CAS; never replace learner tables or the whole catalog.'
    folder = Path(backup_dir); folder.mkdir(parents=True, exist_ok=True)
    destination = folder / ('exam-refresh-before-'+str(time.time_ns())+'.json')
    raw = c.canonical(saved).encode()
    with destination.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(folder, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    return str(destination), hashlib.sha256(raw).hexdigest()


def refresh(db, package, *, book_id, title, edition, expected_source, backup_dir):
    """Caller must commit/rollback the complete transaction; no nested commits.

    An append-only source mapping revision preserves every former native ID.
    The exact old source collection is retained, while the new export skeleton
    lets the existing common exporter reconstruct the expanded current book.
    """
    if not title.strip() or '::' in title or type(edition) is not int:
        raise ValueError('invalid refreshed book identity')
    c.write_lock(db); require_ready(db)
    current = db.execute('SELECT source_id,collection_id,col_payload_id FROM book_sources WHERE book_id=%s FOR UPDATE', (book_id,)).fetchone()
    if current is None or current[0] != expected_source:
        raise ValueError('stale exam source revision')
    digest, incoming, resources = _load(package, book_id)
    book = project_book(db, book_id); old_notes = {}
    for nid, guid in db.execute('SELECT note_id,guid FROM notes WHERE book_id=%s ORDER BY ordinal', (book_id,)):
        note = project_note(db, book, nid, apply_runtime=False)
        key, path = _identity(note['fields'], guid, book_id)
        old_notes[guid] = (note, key, path)
    by_guid = {r['note']['guid']: r for r in incoming}
    if len(by_guid) != len(incoming) or not set(old_notes).issubset(by_guid):
        raise ValueError('refresh cannot remove or duplicate existing exam questions')
    for guid, (_, key, _) in old_notes.items():
        if by_guid[guid]['key'] != key: raise ValueError('source question binding changed')
    # Model identity/schema and shared presentation stay exactly as registered.
    mids = {r[0] for r in db.execute('SELECT model_id FROM notes WHERE book_id=%s', (book_id,))}
    if len(mids) != 1: raise ValueError('exam refresh requires one existing model')
    mid = next(iter(mids))
    if tuple(f['name'] for f in book['models'][str(mid)]['flds']) != FIELDS:
        raise ValueError('existing exam model differs')
    saved, saved_sha = _backup(db, book_id, backup_dir)
    previous_overlay = units.registry(db).get(book_id)
    decks = copy.deepcopy(book['units']); membership = {}; relative = {}
    old_title = book['title']
    for did, deck in decks.items():
        name = deck['name']
        if name != old_title and not name.startswith(old_title+'::'):
            # Genanki retains an unused Default deck. Keep it unchanged, but
            # never permit authored exam cards to bind to an outside root.
            continue
        suffix = name[len(old_title):]
        deck['name'] = title + suffix
        relative[suffix.lstrip(':')] = int(did)
    old_membership = previous_overlay['cards'] if previous_overlay else {str(cid):did for cid,did in db.execute('SELECT native_id,unit_id FROM native_cards WHERE book_id=%s',(book_id,))}
    if any(not (decks[str(did)]['name'] == title or decks[str(did)]['name'].startswith(title+'::')) for did in old_membership.values()):
        raise ValueError('existing mapped exam card is outside book root')
    def deck_for(path):
        parts = path.split('::'); parent = None
        for index in range(1, len(parts)+1):
            local = '::'.join(parts[:index])
            if local not in relative:
                did = _number('exam-refresh-unit', book_id+':'+local)
                if str(did) in decks: raise ValueError('new exam deck identity collision')
                deck = genanki.Deck(did, title+'::'+local).to_json()
                decks[str(did)] = deck; relative[local] = did
                insert(db, 'units', (book_id,did,deck['name'],parent,c.put_json(db,deck)))
            parent = relative[local]
        return parent
    db.execute('SELECT pg_advisory_xact_lock(%s)', (int(c.identity('native-created-time')[:15],16),))
    allocation = db.execute("SELECT value FROM metadata WHERE key='native.created-ms.v1' FOR UPDATE").fetchone()
    next_id = max(time.time_ns()//1_000_000, int(allocation[0])+1 if allocation else 0)
    occupied = {r[0] for r in db.execute('SELECT note_id FROM notes UNION SELECT native_id FROM native_cards')}
    def allocate():
        nonlocal next_id
        while next_id in occupied: next_id += 1
        result = next_id; occupied.add(result); next_id += 1
        return result
    changed = []; created = []; unsuspended = []
    ordinal = db.execute('SELECT coalesce(max(ordinal),-1)+1 FROM notes WHERE book_id=%s',(book_id,)).fetchone()[0]
    for entry in incoming:
        guid = entry['note']['guid']; fields = entry['fields']
        if guid in old_notes:
            before, key, path = old_notes[guid]; nid = before['note_id']
            rows = list(db.execute('SELECT f.ordinal,f.name,f.component_id,c.current_id FROM note_fields f JOIN components c ON c.id=f.component_id WHERE f.book_id=%s AND f.note_id=%s ORDER BY f.ordinal',(book_id,nid)))
            if tuple(r[1] for r in rows) != FIELDS: raise ValueError('existing field bindings changed')
            dirty = False
            for row, text, prior in zip(rows, fields, before['fields']):
                if text == prior: continue
                # A scoped exam refresh must not rewrite another book's component.
                if db.execute('SELECT count(*) FROM note_fields WHERE component_id=%s',(row[2],)).fetchone()[0] != 1:
                    raise ValueError('exam field component is shared outside exact note')
                after = c.put_object(db, text.encode())
                updated = db.execute('UPDATE components SET current_id=%s WHERE id=%s AND current_id=%s',(after,row[2],row[3]))
                if updated.rowcount != 1: raise ValueError('stale exam field component')
                db.execute('INSERT INTO component_revisions(component_id,before_id,after_id,reason,created_at) VALUES(%s,%s,%s,%s,%s)',(row[2],row[3],after,'verified exam source refresh',c.now()))
                dirty = True
            if dirty: changed.append((book_id,nid))
            card = db.execute('SELECT native_id,unit_id,payload_id FROM native_cards WHERE book_id=%s AND note_id=%s',(book_id,nid)).fetchall()
            if len(card) != 1: raise ValueError('existing exam native card is ambiguous')
            cid, original_unit, payload_id = card[0]
            membership[str(cid)] = previous_overlay['cards'][str(cid)] if previous_overlay else original_unit
            payload = c.get_json(db,payload_id)
            if before['fields'][4] != 'available' and fields[4] == 'available' and payload.get('type') == 0 and payload.get('queue') == -1:
                payload['queue'] = 0
                db.execute('UPDATE native_cards SET payload_id=%s WHERE book_id=%s AND native_id=%s',(c.put_json(db,payload),book_id,cid)); unsuspended.append(cid)
        else:
            nid, cid = allocate(), allocate(); did = deck_for(entry['path'])
            note = {**entry['note'], 'id':nid, 'mid':mid}
            insert(db,'notes',(book_id,nid,guid,None,'guide',ordinal,mid,c.put_json(db,note),None)); ordinal += 1
            for index,(name,text) in enumerate(zip(FIELDS,fields)):
                component = c.ensure_component(db,None,name,text,scope=book_id+':'+str(nid))
                insert(db,'note_fields',(book_id,nid,index,name,component))
            payload = {**entry['card'],'id':cid,'nid':nid,'did':did}
            insert(db,'native_cards',(book_id,cid,nid,did,0,c.put_json(db,payload)))
            membership[str(cid)] = did; created.append(nid)
    for name,(raw,info) in resources.items():
        key = c.put_object(db,raw)
        old = db.execute('SELECT object_id FROM resource_aliases WHERE book_id=%s AND name=%s',(book_id,name)).fetchone()
        if old and old[0] != key: raise ValueError('source media alias changed bytes')
        if not old: insert(db,'resource_aliases',(book_id,name,key,c.put_json(db,info)))
    overlay = units.install(db,book_id,decks,membership,expected=previous_overlay)
    bump_content_mods(db,changed)
    if created:
        db.execute("INSERT INTO metadata VALUES('native.created-ms.v1',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(next_id-1),))
    # Preserve old schema/model bytes; only current PG contents become skeleton-backed.
    with tempfile.TemporaryDirectory(prefix='exam-refresh-') as temp:
        path = Path(temp)/'collection.anki2'
        with path.open('xb') as stream: c.write_object(db,current[1],stream)
        native = sqlite3.connect(path)
        try:
            native.execute('DELETE FROM cards'); native.execute('DELETE FROM notes'); native.commit()
            native.execute('VACUUM')
        finally: native.close()
        collection_id = c.put_file(db,path)
    package_id = c.put_file(db,package)
    if package_id != digest:
        raise ValueError('exam source package changed during refresh')
    manifest = copy.deepcopy(book['manifest'])
    manifest.update({'collection_mode':'skeleton','previous_source_id':current[0],
                     'previous_collection_id':current[1],'previous_col_payload_id':current[2],
                     'refresh_package_id':package_id,'refresh_package_sha256':digest,
                     'refresh_backup_sha256':saved_sha})
    aliases = [r[0] for r in db.execute('SELECT name FROM resource_aliases WHERE book_id=%s ORDER BY name',(book_id,))]
    manifest['media'] = {str(i):name for i,name in enumerate(aliases)}
    manifest['media_index_id'] = c.put_json(db,manifest['media'])
    source_id = c.identity('exam-source-refresh',book_id,current[0],digest)
    insert(db,'sources',(source_id,'exam-refresh',book_id,c.put_json(db,manifest),'complete'))
    db.execute('UPDATE book_sources SET source_id=%s,collection_id=%s WHERE book_id=%s AND source_id=%s',(source_id,collection_id,book_id,expected_source))
    db.execute('UPDATE books SET title=%s,edition=%s WHERE id=%s',(title,edition,book_id))
    # Resolve all final shared projections before the caller can commit.
    final = project_book(db,book_id)
    for nid, in db.execute('SELECT note_id FROM notes WHERE book_id=%s',(book_id,)): project_note(db,final,nid)
    receipt = {'schema':'study-exam-refresh.v1','book_id':book_id,'before_source_id':current[0],
               'source_id':source_id,'package_sha256':digest,'notes':len(incoming),
               'updated_notes':len(changed),'created_notes':len(created),
               'source_default_unsuspended_cards':unsuspended,'unit_cards':len(overlay['cards']),
               'backup':saved,'backup_sha256':saved_sha,'learning_tables_written':False}
    c.event(db,'refresh-exam-source',receipt)
    return receipt
