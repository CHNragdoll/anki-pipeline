"""Retain migration-pinned learning catalogs before retiring legacy exports.

Default operation is read-only. --apply adds immutable content objects and their
ownership keys after writing verified private backups; it changes no learning
row, source pin, native identity or existing catalog. Run before starting v2 on
an installation whose learning catalogs have not yet been retained.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import psycopg

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_service_catalog as provider
from anki_pipeline.study_progress_migration import ALIASES_KEY, RECEIPT_KEY
from anki_pipeline.study_service import load_config


def retain(config_path, backup_directory, *, apply=False):
    config = load_config(config_path)
    root = config.document_root.resolve(strict=True)
    registry = json.loads(config.registry_path.read_text())
    if registry['schema'] != provider.PROJECTION_REGISTRY_SCHEMA:
        raise ValueError('Only an explicitly projected v2 service is eligible')
    backup_directory = Path(backup_directory).resolve(strict=False)
    mounts = json.loads(config.static_mounts_path.read_text())
    public = [root] + [Path(row['export']).resolve() for row in mounts['mounts']]
    if any(backup_directory.is_relative_to(path) for path in public):
        raise ValueError('Catalog backups must remain outside HTTP roots')
    captured, active, native = [], {}, {}
    with psycopg.connect(config.target.dsn) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        db.execute(psycopg.sql.SQL('SET LOCAL search_path TO {}').format(psycopg.sql.Identifier(config.target.schema)))
        report = provider._authenticated_report(db)
        before_seals = dict(db.execute('select key,value from metadata where key=any(%s)',
                                      ([ALIASES_KEY, RECEIPT_KEY],)).fetchall())
        approved = {book['legacy_book']: book for book in report['books']}
        if {row['id'] for row in registry['books']} != set(approved):
            raise ValueError('Registry must exactly cover the approved learning books')
        for row in registry['books']:
            book = approved[row['id']]
            proof = provider._catalog_pin(book)
            object_id = proof['sha256']
            exists = db.execute('select 1 from objects where id=%s', (object_id,)).fetchone() is not None
            raw = catalog.get_object(db, object_id) if exists else provider._read_file(root, Path(proof['path']), proof)
            _, members = provider._book(root, row, book, retained_raw=raw)
            active.update({(row['id'], card): deck for card, deck in members.items()})
            native.update(provider._native_identities(db, book))
            owner = 'source.learning-catalog.v1.' + row['id']
            old = db.execute('select value from metadata where key=%s', (owner,)).fetchone()
            if old is not None and old[0] != object_id:
                raise ValueError('An existing retained catalog cannot be replaced')
            if exists and catalog.get_object(db, object_id) != raw:
                raise ValueError('Existing content object differs from its approved bytes')
            captured.append({'book': row['id'], 'object_id': object_id, 'bytes': len(raw),
                'owner_key': owner, 'previous_owner': old[0] if old else None,
                'object_preexisted': exists, 'raw': raw})
        provider._bindings(report, active, native, approved)
    summary = [{key: value for key, value in row.items() if key != 'raw'} for row in captured]
    if not apply:
        return {'state': 'dry_run', 'books': summary}
    if all(row['object_preexisted'] and row['previous_owner'] == row['object_id'] for row in captured):
        return {'state': 'already_retained', 'books': summary}
    backup_directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    for row in captured:
        path = backup_directory / (row['object_id'] + '.json.gz')
        with gzip.open(path, 'wb') as stream:
            stream.write(row['raw'])
        with gzip.open(path, 'rb') as stream:
            restored = stream.read()
        if restored != row['raw'] or hashlib.sha256(restored).hexdigest() != row['object_id']:
            raise ValueError('Learning catalog backup failed verification')
    (backup_directory / 'before.json').write_text(json.dumps(summary, indent=2))
    with psycopg.connect(config.target.dsn) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
        db.execute(psycopg.sql.SQL('SET LOCAL search_path TO {}').format(psycopg.sql.Identifier(config.target.schema)))
        current = dict(db.execute('select key,value from metadata where key=any(%s)',
                                  ([ALIASES_KEY, RECEIPT_KEY],)).fetchall())
        if current != before_seals:
            raise ValueError('Learning identity seals changed; start a fresh retention plan')
        added = []
        for row in captured:
            object_id = catalog.put_object(db, row['raw'])
            if object_id != row['object_id'] or catalog.get_object(db, object_id) != row['raw']:
                raise ValueError('Retained object failed exact reconciliation')
            old = db.execute('select value from metadata where key=%s', (row['owner_key'],)).fetchone()
            if old is None:
                db.execute('insert into metadata values(%s,%s)', (row['owner_key'], object_id))
                added.append(row['owner_key'])
            elif old[0] != object_id:
                raise ValueError('Concurrent retention owner changed')
        if added:
            catalog.event(db, 'retain-runtime-learning-catalogs', {'owners_added': added,
                'catalogs': {row['book']: row['object_id'] for row in captured}})
    with psycopg.connect(config.target.dsn) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        db.execute(psycopg.sql.SQL('SET LOCAL search_path TO {}').format(psycopg.sql.Identifier(config.target.schema)))
        for row in captured:
            if catalog.get_object(db, row['object_id']) != row['raw']:
                raise ValueError('Committed catalog reconciliation failed')
    result = {'state': 'retained', 'books': summary, 'backup_directory': str(backup_directory),
        'rollback': 'Before activation, remove only newly added ownership keys if needed. '
                    'Keep immutable objects as audit data; restore verified gzip catalog bytes for legacy tools.'}
    (backup_directory / 'retained.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--backup-directory', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(retain(args.config, args.backup_directory, apply=args.apply), indent=2))


if __name__ == '__main__':
    main()
