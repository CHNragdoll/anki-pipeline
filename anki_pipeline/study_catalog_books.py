"""Create future editions from unit/word mappings, without another source APKG."""
from __future__ import annotations

from contextlib import closing
import copy
import hashlib
import html
import json
import re
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

import genanki
from genanki.package import APKG_COL, APKG_SCHEMA

from . import study_catalog as c
from . import study_catalog_presentation as presentation
from .study_catalog_export import project_book, project_note, require_ready
from .study_catalog_import import insert, _zip_info
from .study_catalog_anki import field_cache


def _number(*parts):
    # Anki's signed integer IDs and JavaScript's exact integer range both fit.
    return int(c.identity(*parts)[:13], 16) or 1


def _deck(did, name):
    value = genanki.Deck(did, name).to_json()
    for field in ('lrnToday', 'newToday', 'revToday', 'timeToday'):
        value[field] = [0, 0]
    return value


def _choose_note(db, entry):
    # General learning entries use their explicit source identity. Word lookup
    # remains a convenience for vocabulary mappings, not a catalog constraint.
    if 'from_note' in entry or ('from_card' in entry and 'word' not in entry):
        if not entry.get('from_book'):
            raise ValueError('general entries require from_book and from_note/from_card')
        field='note_id' if 'from_note' in entry else 'source_card_id'
        rows=db.execute('select book_id,note_id,source_card_id from notes where book_id=%s and '+field+'=%s',
                        (entry['from_book'],entry.get('from_note',entry.get('from_card')))).fetchall()
        if len(rows)!=1:raise ValueError('general entry has no unique source note')
        return rows[0]
    word = entry.get('word')
    if not isinstance(word, str) or not word.strip():
        raise ValueError('each mapped word needs its exact spelling')
    rows = db.execute('select n.book_id,n.note_id,n.source_card_id from notes n join words w on w.id=n.word_id '
                      'where w.surface=%s and w.language=%s order by n.book_id,n.ordinal', (word, 'en')).fetchall()
    if entry.get('from_book'):
        rows = [r for r in rows if r[0] == entry['from_book']]
    if entry.get('from_card'):
        rows = [r for r in rows if r[2] == entry['from_card']]
    if len(rows) != 1:
        raise ValueError('word needs one explicit source bundle (from_book/from_card): ' + word)
    return rows[0]


def create_book(value, mapping):
    """Append a whole book transactionally; reuse shared fields and resource bytes.

    Ambiguous dictionary/presentation variants require an explicit source bundle.
    Existing books, GUIDs and study state are never rewritten by this operation.
    A failed mapping publishes no book. The immutable mapping is its replay and
    rollback authority; all inserted rows commit together.
    """
    if mapping.get('schema') != 'study-book-map.v1':
        raise ValueError('unknown book mapping schema')
    bid, title, edition = mapping['id'], mapping['title'], mapping['edition']
    if not isinstance(title, str) or '::' in title or not title.strip():
        raise ValueError('book title must be a nonempty Anki root name')
    units = mapping.get('units')
    if not isinstance(units, list) or not units:
        raise ValueError('book needs explicit units')
    seal = c.identity('book-map', mapping)
    with c.connect(value) as db, c.transaction(db), tempfile.TemporaryDirectory(prefix='anki-mapped-book-') as temp:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        c.write_lock(db)
        require_ready(db)
        old = db.execute('select source_id from book_sources where book_id=%s', (bid,)).fetchone()
        if old:
            if old[0] == seal:
                return {'book_id': bid, 'already_created': True, 'source_id': seal}
            raise ValueError('book exists; a different map requires a reviewed mapping revision')
        c.ensure_book(db, bid, title, edition)
        # Serialize allocation across mapped books: native note/card IDs encode
        # creation time in milliseconds. Opaque content hashes belong in GUIDs.
        db.execute('select pg_advisory_xact_lock(%s)',(int(c.identity('native-created-time')[:15],16),))
        allocation=db.execute("select value from metadata where key='native.created-ms.v1' FOR UPDATE").fetchone()
        next_native=max(int(time.time_ns()//1_000_000),int(allocation[0])+1 if allocation else 0)
        occupied={r[0] for r in db.execute('select note_id from notes union select native_id from native_cards')}
        def native_id():
            nonlocal next_native
            while next_native in occupied:next_native+=1
            result=next_native;occupied.add(result);next_native+=1
            return result
        native_path = Path(temp) / 'collection.anki2'
        with closing(sqlite3.connect(native_path)) as native, native:
            native.row_factory = sqlite3.Row
            native.executescript(APKG_SCHEMA)
            native.executescript(APKG_COL)
            col = dict(native.execute('select * from col').fetchone())
            root_id = _number('mapped-root', bid)
            decks = {str(root_id): _deck(root_id, title)}
            models = {}; model_keys = {}; seen = set(); used_books = set(); count = 0; references = {}
            for unit in units:
                path = unit.get('name')
                if not isinstance(path, str) or not path.strip() or any(not x.strip() for x in path.split('::')):
                    raise ValueError('each unit needs an exact nonempty path')
                if 'words' in unit and 'items' in unit:raise ValueError('use either items or words in a unit')
                words = unit.get('items',unit.get('words'))
                if not isinstance(words, list) or not words:
                    raise ValueError('each unit needs explicit learning items')
                parent_id = root_id
                for i in range(1, len(path.split('::')) + 1):
                    relative = '::'.join(path.split('::')[:i]); did = _number('mapped-unit', bid, relative)
                    decks[str(did)] = _deck(did, title + '::' + relative)
                    parent_id = did
                for position, entry in enumerate(words, 1):
                    source_book, source_nid, source_card = _choose_note(db, entry)
                    used_books.add(source_book)
                    source = project_book(db, source_book); note = project_note(db, source, source_nid, apply_runtime=False)
                    # Start with original model bytes; the shared registry then
                    # resolves revisions for both hosts, including later edits.
                    original_model = json.loads(source['col']['models'])[str(note['model_id'])]
                    model_key = c.identity('mapped-model', original_model)
                    if model_key not in model_keys:
                        mid = int(c.identity('mapped-model-id', bid, model_key)[:8], 16) & 0x7fffffff or 1
                        if str(mid) in models:
                            raise ValueError('generated model identity collision')
                        model_keys[model_key] = mid
                        models[str(mid)] = {**copy.deepcopy(original_model), 'id': mid, 'did': root_id}
                    mid = model_keys[model_key]
                    entry_key = c.identity(path, entry.get('key',entry.get('word',
                        [source_book,source_card or source_nid])))
                    if entry_key in seen:
                        raise ValueError('duplicate word in unit requires a distinct explicit key')
                    seen.add(entry_key)
                    nid = native_id(); guid = genanki.guid_for('study-book-map.v1', bid, entry_key)
                    source_id = c.identity('mapped-card', bid, entry_key)
                    fields = list(note['fields'])
                    metadata = path.replace('::', ' ') + ' ➫ ' + str(position)
                    if 'Meta' in note['field_names']:
                        fields[note['field_names'].index('Meta')] = metadata
                    stamp = int(time.time()); word,checksum=field_cache(fields,original_model)
                    native.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',
                                   (nid, guid, mid, stamp, -1, '', '\x1f'.join(fields), word, checksum, 0, ''))
                    payload = dict(native.execute('select * from notes where id=?', (nid,)).fetchone()); payload.pop('flds')
                    insert(db, 'notes', (bid, nid, guid, note['word_id'], note['kind'], count, mid, c.put_json(db, payload), source_id))
                    for ordinal, name, component in db.execute('select ordinal,name,component_id from note_fields where book_id=%s and note_id=%s order by ordinal', (source_book, source_nid)):
                        if name == 'Meta':
                            component = c.ensure_component(db, note['word_id'], name, metadata, scope=bid + ':' + str(nid))
                        insert(db, 'note_fields', (bid, nid, ordinal, name, component))
                    references[source_id] = source['manifest'].get('analysis_references', {}).get(source_card, {
                        'book_id': source_book, 'source_card_id': source_card, 'note_id': source_nid})
                    for ordinal, in db.execute('select ordinal from native_cards where book_id=%s and note_id=%s order by ordinal', (source_book, source_nid)):
                        cid = native_id()
                        native.execute('insert into cards values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                       (cid, nid, parent_id, ordinal, stamp, -1, 0, 0, count + 1, 0, 0, 0, 0, 0, 0, 0, 0, ''))
                    count += 1
            col['models'] = c.canonical(models); col['decks'] = c.canonical(decks)
            native.execute('update col set models=?,decks=?', (col['models'], col['decks']))
            # Units precede native_cards to retain database foreign keys.
            by_name = {d['name']: d['id'] for d in decks.values()}
            for did, deck in decks.items():
                parent = by_name.get(deck['name'].rsplit('::', 1)[0]) if '::' in deck['name'] else None
                insert(db, 'units', (bid, int(did), deck['name'], parent, c.put_json(db, deck)))
            for row in native.execute('select * from cards order by id'):
                data = dict(row)
                insert(db, 'native_cards', (bid, data['id'], data['nid'], data['did'], data['ord'], c.put_json(db, data)))
            # New books retain only a native schema/model skeleton. Their
            # content lives in shared components, not another hidden full copy.
            native.execute('delete from cards');native.execute('delete from notes');native.commit()
            native.execute('VACUUM')
        aliases = {}
        for source_book in sorted(used_books):
            for name, key, zip_info in db.execute('select name,object_id,zip_info_id from resource_aliases where book_id=%s', (source_book,)):
                if name in aliases and aliases[name][0] != key:
                    raise ValueError('source media filenames collide with different bytes: ' + name)
                aliases[name] = key, zip_info
        media = {str(i): name for i, name in enumerate(sorted(aliases))}
        info = zipfile.ZipInfo('collection.anki2'); info.compress_type = zipfile.ZIP_DEFLATED
        manifest = {'mapping_id': c.put_json(db, mapping), 'collection_mode': 'skeleton',
                    'media': media, 'collection_entry': 'collection.anki2',
                    'collection_zip_info': _zip_info(info), 'media_index_id': c.put_json(db, media), 'extra_members': {},
                    'analysis_references': references}
        insert(db, 'sources', (seal, 'book-map', bid, c.put_json(db, manifest), 'complete'))
        insert(db, 'book_sources', (bid, seal, c.put_file(db, native_path), c.put_json(db, col)))
        for name, (key, zip_info) in aliases.items():
            insert(db, 'resource_aliases', (bid, name, key, zip_info))
        presentation.register_book(db, bid, col)
        db.execute("insert into metadata values('native.created-ms.v1',%s) on conflict(key) do update set value=excluded.value",
                   (str(next_native-1),))
        if mapping.get('scope'):
            from .study_catalog_library import set_scope
            set_scope(db,bid,mapping['scope'])
        c.event(db, 'create-mapped-book', {'book_id': bid, 'source_id': seal, 'notes': count, 'source_books': sorted(used_books)})
        return {'book_id': bid, 'source_id': seal, 'notes': count, 'media': len(aliases), 'new_media_bytes': 0}
