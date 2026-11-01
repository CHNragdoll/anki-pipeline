"""Rename a legacy APKG deck root while preserving every card and media byte."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def rename_root(source, destination, old, new):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or destination.exists():
        raise ValueError('Use a new destination; original packages must be retained')
    if not old or not new or '::' in new:
        raise ValueError('Provide nonempty root names, without a hierarchy in the new root')
    with zipfile.ZipFile(source) as package, tempfile.TemporaryDirectory() as temp:
        db = Path(package.extract('collection.anki2', temp))
        with sqlite3.connect(db) as conn:
            before = '\n'.join(conn.iterdump())
            decks = json.loads(conn.execute('SELECT decks FROM col').fetchone()[0])
            originals = json.loads(json.dumps(decks))
            changed = 0
            for deck in decks.values():
                name = deck['name']
                if name == old or name.startswith(old + '::'):
                    deck['name'] = new + name[len(old):]
                    changed += 1
            if not changed:
                raise ValueError('No matching source deck root')
            names = [d['name'] for d in decks.values()]
            if len(set(names)) != len(names):
                raise ValueError('Renaming would collide with another deck')
            conn.execute('UPDATE col SET decks=?', (json.dumps(decks, ensure_ascii=False),))
            conn.commit()
            assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            notes = conn.execute('SELECT count(*) FROM notes').fetchone()[0]
            cards = conn.execute('SELECT count(*) FROM cards').fetchone()[0]
            # Prove that restoring just this metadata reproduces every SQL row.
            conn.execute('UPDATE col SET decks=?', (json.dumps(originals, ensure_ascii=False),))
            # Compare with the original serialization, including original whitespace.
            original_db = Path(temp) / 'original.sqlite'
            original_db.write_bytes(package.read('collection.anki2'))
            with sqlite3.connect(original_db) as orig:
                original_decks = orig.execute('SELECT decks FROM col').fetchone()[0]
            conn.execute('UPDATE col SET decks=?', (original_decks,))
            assert '\n'.join(conn.iterdump()) == before
            conn.rollback()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'w') as result:
            for member in package.infolist():
                result.writestr(copy.copy(member), db.read_bytes() if member.filename == 'collection.anki2' else package.read(member))
        with zipfile.ZipFile(destination) as result:
            assert result.testzip() is None
            for member in package.namelist():
                if member != 'collection.anki2':
                    assert package.read(member) == result.read(member)
    return {'old_root': old, 'new_root': new, 'renamed_decks': changed,
            'notes': notes, 'cards': cards, 'only_deck_names_changed': True,
            'media_bytes_unchanged': True, 'bytes': destination.stat().st_size,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'destination', 'old', 'new'):
        parser.add_argument(arg)
    args = parser.parse_args()
    print(json.dumps(rename_root(args.source, args.destination, args.old, args.new), ensure_ascii=False, indent=2))
