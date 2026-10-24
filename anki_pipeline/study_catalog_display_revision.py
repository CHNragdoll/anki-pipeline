"""Explicit, source-bound display repairs without changing semantic facts.

The caller supplies a reviewed plan and its digest. Original note fields,
analysis records and learning tables remain immutable. Rollback is another
forward version revision, never a restore of an entire learning database.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
import stat
import json
from pathlib import Path

from . import study_catalog as c
from . import study_catalog_revision as revisions


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_plan(path, expected):
    raw = Path(path).read_bytes()
    if digest(raw) != expected:
        raise ValueError('display repair plan digest differs')
    plan = json.loads(raw)
    if plan.get('schema') != 'study-reviewed-display-repair.v1':
        raise ValueError('unknown display repair plan')
    if not plan.get('reason') or not plan.get('fields'):
        raise ValueError('explicit display repair scope is required')
    seen = set()
    authenticated = {}
    for item in plan['fields']:
        key = (item['book_id'], item['source_card_id'])
        if key in seen or item['field'] != 'Examples':
            raise ValueError('ambiguous or unsupported display repair field')
        seen.add(key)
        for descriptor in (item['after'], item['inverse'], item['authority']):
            content = Path(descriptor['path']).read_bytes()
            if digest(content) != descriptor['sha256']:
                raise ValueError('display repair evidence changed')
            authenticated[(descriptor['path'], descriptor['sha256'])] = content
    for item in plan.get('components', []):
        if item['component_id'] in seen:
            raise ValueError('duplicate component repair')
        seen.add(item['component_id'])
        content = Path(item['after']['path']).read_bytes()
        if digest(content) != item['after']['sha256']:
            raise ValueError('runtime repair evidence changed')
        authenticated[(item['after']['path'], item['after']['sha256'])] = content
    plan['_authenticated_bytes'] = authenticated
    return plan


_BACKUP_STAT = ('st_dev', 'st_ino', 'st_uid', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')


@contextmanager
def _held_backup(saved, backups, expected=None):
    saved = Path(saved)
    if saved.is_symlink() or not saved.resolve().is_relative_to(Path(backups).resolve()):
        raise ValueError('prepared backup leaves explicit backup directory')
    fd = os.open(saved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        initial = os.fstat(fd)
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError('prepared backup must be a regular file')
        def check():
            try:
                states = (os.fstat(fd), saved.lstat())
            except OSError as exc:
                raise ValueError('prepared catalog backup changed') from exc
            if any(any(getattr(state, key) != getattr(initial, key) for key in _BACKUP_STAT)
                   for state in states):
                raise ValueError('prepared catalog backup changed')
        check()
        with os.fdopen(os.dup(fd), 'rb') as stream:
            pin = hashlib.file_digest(stream, 'sha256').hexdigest()
            if expected is not None and (initial.st_size != expected['bytes'] or pin != expected['sha256']):
                raise ValueError('prepared catalog backup changed')
            stream.seek(0)
            c.read_backup_header(stream)
        check()
        yield check
        check()
    finally:
        os.close(fd)


def apply(value, path, *, expected, backups, prepared_backup=None):
    plan = read_plan(path, expected)
    saved = c.backup(value, backups) if prepared_backup is None else Path(prepared_backup['path'])
    with _held_backup(saved, backups, prepared_backup) as check_backup:
        return _apply_plan(value, plan, expected, saved, check_backup)


def _apply_plan(value, plan, expected, saved, check_backup):
    from .study_catalog_export import project_book, project_note, require_ready
    from .study_catalog_anki import bump_content_mods, bump_component_mods
    with c.connect(value) as db, c.transaction(db):
        c.write_lock(db)
        require_ready(db)
        db.execute('select pg_advisory_xact_lock(%s)',
                   (int(c.identity(revisions.KEY)[:15], 16),))
        check_backup()
        projections = revisions.registry(db)
        if digest(c.canonical(projections).encode()) != plan['before_registry_sha256']:
            raise ValueError('display projection registry changed')
        before, after, affected, runtime_changes = {}, {}, [], []
        for item in plan['fields']:
            bid, cid, nid = item['book_id'], item['source_card_id'], item['note_id']
            row = db.execute('select record_id from analyses where book_id=%s and source_card_id=%s for update',
                             (bid, cid)).fetchone()
            if row is None or row[0] != item['record_id']:
                raise ValueError('display repair active facts changed')
            note = project_note(db, project_book(db, bid), nid, apply_runtime=False)
            if note['id'] != cid:
                raise ValueError('display repair native note binding differs')
            original = note['fields'][note['field_names'].index('Examples')]
            if digest(original.encode()) != item['before_sha256']:
                raise ValueError('display repair source field changed')
            key = c.identity(bid, cid)
            previous = projections.get(key)
            before[key] = previous
            revised = {**(previous or {}), 'record_id': row[0],
                       'fields': {**(previous or {}).get('fields', {}),
                                  'Examples': c.put_object(db, plan['_authenticated_bytes'][(item['after']['path'], item['after']['sha256'])])}}
            revised['example_display_repair'] = {
                'schema': 'study-reviewed-example-exclusion.v1', 'plan_sha256': expected,
                'source_record_id': row[0], 'before_field_sha256': item['before_sha256'],
                'authority_object_id': c.put_object(db, plan['_authenticated_bytes'][(item['authority']['path'], item['authority']['sha256'])]),
                'inverse_object_id': c.put_object(db, plan['_authenticated_bytes'][(item['inverse']['path'], item['inverse']['sha256'])]),
            }
            projections[key] = revised
            after[key] = revised
            affected.append((bid, nid))
        for item in plan.get('components', []):
            row = db.execute('select current_id,word_id from components where id=%s for update',
                             (item['component_id'],)).fetchone()
            if row is None or row[0] != item['before_id'] or row[1] is not None:
                raise ValueError('runtime repair component binding changed')
            new = c.put_object(db, plan['_authenticated_bytes'][(item['after']['path'], item['after']['sha256'])])
            db.execute('update components set current_id=%s where id=%s', (new, item['component_id']))
            db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) values(%s,%s,%s,%s,%s)',
                       (item['component_id'], row[0], new, plan['reason'], c.now()))
            bump_component_mods(db, item['component_id'])
            runtime_changes.append({'component_id': item['component_id'], 'before': row[0], 'after': new})
        db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
                   (revisions.KEY, c.canonical(projections)))
        bump_content_mods(db, affected)
        revisions.preflight_display_projections(db, affected)
        receipt = {'schema': 'study-reviewed-display-repair-applied.v1',
                   'plan_sha256': expected, 'before_projections': before,
                   'after_projections': after, 'runtime_changes': runtime_changes,
                   'affected_notes': affected, 'backup': str(saved),
                   'semantic_facts_changed': False, 'learning_tables_written': False}
        c.event(db, 'repair-shared-example-display', receipt)
        check_backup()
    return receipt


def rollback(value, receipt):
    """CAS only this revision; keep all concurrent learning state intact."""
    from .study_catalog_anki import bump_content_mods, bump_component_mods
    with c.connect(value) as db, c.transaction(db):
        c.write_lock(db)
        db.execute('select pg_advisory_xact_lock(%s)',
                   (int(c.identity(revisions.KEY)[:15], 16),))
        data = revisions.registry(db)
        for key, after in receipt['after_projections'].items():
            if data.get(key) != after:
                raise ValueError('later display revision prevents rollback')
        for item in receipt['runtime_changes']:
            row = db.execute('select current_id from components where id=%s for update',
                             (item['component_id'],)).fetchone()
            if row is None or row[0] != item['after']:
                raise ValueError('later runtime revision prevents rollback')
        for key, before in receipt['before_projections'].items():
            if before is None:
                data.pop(key, None)
            else:
                data[key] = before
        for item in receipt['runtime_changes']:
            db.execute('update components set current_id=%s where id=%s',
                       (item['before'], item['component_id']))
            db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) values(%s,%s,%s,%s,%s)',
                       (item['component_id'], item['after'], item['before'], 'revert exact example display repair', c.now()))
            bump_component_mods(db, item['component_id'])
        db.execute('update metadata set value=%s where key=%s', (c.canonical(data), revisions.KEY))
        bump_content_mods(db, receipt['affected_notes'])
        revisions.preflight_display_projections(db, receipt['affected_notes'])
        c.event(db, 'revert-shared-example-display', {'plan_sha256': receipt['plan_sha256']})
