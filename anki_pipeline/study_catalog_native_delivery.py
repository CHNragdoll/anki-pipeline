"""Explicit registration of native host versions, without changing content.

Only three metadata rows are writable. A read-only plan authenticates all
selected projections; apply repeats that work under the catalog's write lock.
The private journal is a complete backup of this write set, not a replacement
for an operator's full catalog backup. Rollback is only for unpublished work.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import study_catalog as c
from . import study_catalog_anki as versions
from .study_catalog_export import compiled_source_sha256, project_book, project_note
from .study_compiled_runtime import ADMITTED_RUNTIME_SHA256

KEY = 'native.delivery-registration.v1'
WRITE_KEYS = (versions.MODEL_MODS, versions.MODS, KEY)
_HASH = re.compile('[a-f0-9]{64}')


def _explicit_target(value):
    if isinstance(value, c.Target):
        selected = value
    elif type(value) is str and value.strip():
        selected = c.Target(value)
    else:
        raise ValueError('an explicit catalog target is required')
    if type(selected.dsn) is not str or not selected.dsn.strip():
        raise ValueError('an explicit catalog connection is required')
    return selected


def _sha(value):
    return hashlib.sha256(c.canonical(value).encode()).hexdigest()


def _freeze(value):
    return json.loads(c.canonical(value))


def _inputs(books):
    if type(books) is not dict or not books:
        raise ValueError('explicit nonempty compiled books are required')
    normalized = {}
    fields = {'note_id', 'id', 'source_sha256', 'record_sha256', 'runtime_sha256'}
    for book, notes in books.items():
        if type(book) is not str or not book or type(notes) is not list or not notes:
            raise ValueError('each explicit book needs a complete compiled note list')
        seen, identities, rows = set(), set(), []
        for row in notes:
            if (type(row) is not dict or set(row) != fields or type(row['note_id']) is not int or
                    not 0 < row['note_id'] < 2**63 or type(row['id']) is not str or not row['id'] or
                    row['note_id'] in seen or row['id'] in identities or
                    any(type(row[key]) is not str or not _HASH.fullmatch(row[key])
                        for key in ('source_sha256', 'record_sha256', 'runtime_sha256')) or
                    row['runtime_sha256'] not in ADMITTED_RUNTIME_SHA256):
                raise ValueError('invalid or duplicate compiled source identity/digest')
            seen.add(row['note_id']); identities.add(row['id']); rows.append(dict(row))
        normalized[book] = sorted(rows, key=lambda row: row['note_id'])
    return {book: normalized[book] for book in sorted(normalized)}


def _metadata(db):
    return {key: (row[0] if (row := db.execute('select value from metadata where key=%s', (key,)).fetchone()) else None)
            for key in WRITE_KEYS}


def _target(db):
    row = db.execute('select current_database(),current_schema()').fetchone()
    return {'database': row[0], 'schema': row[1]}


def _snapshot(db, books):
    result = {}
    revision = db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    for bid, requested in books.items():
        book = project_book(db, bid)
        originals = json.loads(book['col']['models'])
        all_notes = dict(db.execute('select note_id,model_id from notes where book_id=%s order by note_id', (bid,)))
        selected = {row['note_id'] for row in requested}
        if not selected <= set(all_notes):
            raise ValueError('unknown compiled note in book: ' + bid)
        mids = {all_notes[nid] for nid in selected}
        if {nid for nid, mid in all_notes.items() if mid in mids} != selected:
            raise ValueError('compiled model coverage is incomplete: ' + bid)
        notes = []
        for expected in requested:
            note = project_note(db, book, expected['note_id'])
            source = compiled_source_sha256(note)
            if note['id'] != expected['id'] or source != expected['source_sha256']:
                raise ValueError('compiled source identity/hash changed: ' + bid)
            notes.append({'note_id': note['note_id'], 'id': note['id'], 'model_id': note['model_id'],
                          'source_sha256': source, 'model_mod': note['model']['mod'],
                          'original_note_mod': note['payload']['mod'], 'content_mod': note['content_mod']})
        result[bid] = {'collection_id': book['collection_id'], 'source_col_sha256': _sha(book['col']),
                       'manifest_sha256': _sha(book['manifest']), 'runtime_revision': book['runtime_revision'],
                       'models': {str(mid): {'original_mod': originals[str(mid)]['mod'],
                                           'mod': book['models'][str(mid)]['mod']} for mid in sorted(mids)},
                       'notes': notes}
    return {'revision': revision, 'books': result}


def plan_native_delivery(value, books):
    """Read-only RR plan. ``books`` maps book IDs to complete compiled notes.

    Each note supplies integer note_id, opaque id, source_sha256 from the
    exporter's original projection, and the common record/runtime SHA-256.
    All notes using an included model must be included, including suspended
    notes. Other models/books are unaffected. No version or content is written.
    """
    value = _explicit_target(value)
    books = _inputs(books)
    with c.connect(value, readonly=True) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        snapshot = _snapshot(db, books)
        plan = {'schema': 'study-native-delivery-plan.v1', 'target': _target(db), 'books': books,
                'fingerprints': {book: _sha({'book': book, 'notes': notes}) for book, notes in books.items()},
                'expected': snapshot, 'metadata': _metadata(db), 'write_keys': list(WRITE_KEYS)}
    return {**plan, 'sha256': _sha(plan)}


def _plan(plan):
    plan = _freeze(plan)
    pin = plan.pop('sha256', None)
    if (plan.get('schema') != 'study-native-delivery-plan.v1' or pin != _sha(plan) or
            plan.get('write_keys') != list(WRITE_KEYS) or _inputs(plan.get('books')) != plan.get('books')):
        raise ValueError('invalid or modified native delivery plan')
    if plan.get('fingerprints') != {book: _sha({'book': book, 'notes': notes}) for book, notes in plan['books'].items()}:
        raise ValueError('native delivery fingerprint differs')
    return plan, pin


def _registry(raw):
    result = json.loads(raw) if raw is not None else {'schema': KEY, 'books': {}, 'last_operation': None}
    if (type(result) is not dict or set(result) != {'schema', 'books', 'last_operation'} or
            result['schema'] != KEY or type(result['books']) is not dict or
            any(type(book) is not str or not book or type(row) is not dict or
                set(row) != {'fingerprint'} or type(row['fingerprint']) is not str or
                not _HASH.fullmatch(row['fingerprint']) for book, row in result['books'].items())):
        raise ValueError('invalid native delivery registration metadata')
    last = result['last_operation']
    if last is not None and (type(last) is not dict or
            set(last) != {'plan_sha256', 'post_source_sha256', 'post_versions'} or
            any(type(last[key]) is not str or not _HASH.fullmatch(last[key])
                for key in ('plan_sha256', 'post_source_sha256')) or
            type(last['post_versions']) is not dict or set(last['post_versions']) != set(WRITE_KEYS[:2]) or
            any(type(pin) is not str or not _HASH.fullmatch(pin) for pin in last['post_versions'].values())):
        raise ValueError('invalid native delivery registration receipt')
    return result


def _replay_metadata(plan, pin, snapshot, metadata):
    """Authenticate all three exact post-write rows without a self-hash cycle."""
    expected = _registry(plan['metadata'][KEY])
    changed = any(expected['books'].get(bid, {}).get('fingerprint') != fingerprint
                  for bid, fingerprint in plan['fingerprints'].items())
    if not changed:
        return False
    expected['books'].update({bid: {'fingerprint': fingerprint} for bid, fingerprint in plan['fingerprints'].items()})
    expected['last_operation'] = {'plan_sha256': pin, 'post_source_sha256': _sha(snapshot),
                                  'post_versions': _version_pins(metadata)}
    return metadata[KEY] == c.canonical(expected)


def _version_pins(metadata):
    return {key: _sha(metadata[key]) for key in WRITE_KEYS[:2]}


def _native_versions(snapshot):
    return {bid: {'models': {int(mid): row['mod'] for mid, row in book['models'].items()},
                  'notes': {row['note_id']: row['content_mod'] for row in book['notes']}}
            for bid, book in snapshot['books'].items()}


class _Journal:
    """Own a newly created directory, not whichever path later occupies it."""
    def __init__(self, path):
        self.path = path
        self.parent_fd = self.fd = None
        self.files = {}
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            self.parent_fd = os.open(path.parent, flags)
            self.parent_identity = self.identity(os.fstat(self.parent_fd))
            os.mkdir(path.name, mode=0o700, dir_fd=self.parent_fd)
            created = os.stat(path.name, dir_fd=self.parent_fd, follow_symlinks=False)
            self.fd = os.open(path.name, flags, dir_fd=self.parent_fd)
            self.directory_identity = self.identity(os.fstat(self.fd))
            if not stat.S_ISDIR(created.st_mode) or self.identity(created) != self.directory_identity:
                raise ValueError('native journal directory ownership changed during creation')
            self.check_directory()
        except BaseException:
            self.close()
            raise

    @staticmethod
    def identity(info):
        return info.st_dev, info.st_ino

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        for name in ('fd', 'parent_fd'):
            descriptor = getattr(self, name, None)
            if descriptor is not None:
                os.close(descriptor)
                setattr(self, name, None)

    def check_directory(self):
        parent = os.stat(self.path.parent, follow_symlinks=False)
        current = os.stat(self.path.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if (not stat.S_ISDIR(parent.st_mode) or self.identity(parent) != self.parent_identity or
                not stat.S_ISDIR(current.st_mode) or self.identity(current) != self.directory_identity):
            raise ValueError('native journal directory ownership changed')

    def verify(self):
        self.check_directory()
        for name, expected in self.files.items():
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
            with os.fdopen(descriptor, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or self.identity(info) != expected['identity']:
                    raise ValueError('native journal file ownership changed: ' + name)
                raw = stream.read(expected['bytes'] + 1)
                if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                    raise ValueError('native journal bytes changed before sealing: ' + name)
        self.check_directory()

    def sync(self):
        self.verify()
        os.fsync(self.fd)
        os.fsync(self.parent_fd)
        self.verify()


def _write_json(path, value, *, directory):
    if path.parent != directory.path or path.name in directory.files:
        raise ValueError('native journal write is outside its new owned file scope')
    directory.check_directory()
    raw = (c.canonical(value) + '\n').encode()
    descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory.fd)
    with os.fdopen(descriptor, 'wb') as stream:
        if stream.write(raw) != len(raw):
            raise OSError('incomplete native delivery journal write')
        stream.flush()
        os.fsync(stream.fileno())
        identity = directory.identity(os.fstat(stream.fileno()))
    pin = hashlib.sha256(raw).hexdigest()
    directory.files[path.name] = {'identity': identity, 'sha256': pin, 'bytes': len(raw)}
    directory.verify()
    return pin


def _journal(path, plan, pin, before):
    owned = _Journal(path)
    try:
        _write_json(path / 'plan.json', {**plan, 'sha256': pin}, directory=owned)
        _write_json(path / 'before.json', before, directory=owned)
        owned.sync()
        return owned
    except BaseException:
        owned.close()
        raise


def _post_journal(owned, before, after):
    owned.verify()
    _write_json(owned.path / 'after.json', after, directory=owned)
    seals = {name: owned.files[name]['sha256'] for name in ('plan.json', 'before.json', 'after.json')}
    pin = _write_json(owned.path / 'SEAL.json', {'schema': 'study-native-delivery-journal.v1', 'files': seals,
        'write_keys': list(WRITE_KEYS), 'metadata_before_sha256': _sha(before['metadata']),
        'metadata_after_sha256': _sha(after['metadata'])}, directory=owned)
    owned.sync()
    return pin


class NativeDeliveryCommittedError(RuntimeError):
    """The DB committed; only the final local receipt could not be persisted."""
    committed = True


def _committed(owned, result):
    try:
        owned.verify()
        _write_json(owned.path / 'COMMITTED.json', result, directory=owned)
        owned.sync()
    except Exception as error:
        raise NativeDeliveryCommittedError('native metadata committed; journal completion failed: ' + str(owned.path)) from error


def register_native_delivery(value, plan, *, journal):
    """CAS-register only the three planned metadata rows under the common lock.

    ``journal`` must be a new private directory. Exact before/after values and
    missing-row states are fsynced before commit. A missing COMMITTED marker
    means unconfirmed, never permission to overwrite later metadata: inspect
    the DB receipt or retry the same plan with a new journal. Sources, fields,
    media, event/object rows and all learner/native records remain untouched.
    """
    value = _explicit_target(value)
    plan, pin = _plan(plan)
    path = c.guard_new_output(journal)
    with ExitStack() as journals:
        with c.connect(value) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            c.write_lock(db)  # READ COMMITTED: acquire the lock before observing CAS state.
            if _target(db) != plan['target']:
                raise ValueError('native delivery plan belongs to another catalog')
            current = _snapshot(db, plan['books']); before_meta = _metadata(db)
            registry = _registry(before_meta[KEY])
            last = registry['last_operation']
            replay = (type(last) is dict and last.get('plan_sha256') == pin and
                      current['revision'] == plan['expected']['revision'] and
                      last.get('post_source_sha256') == _sha(current) and
                      last.get('post_versions') == _version_pins(before_meta) and
                      _replay_metadata(plan, pin, current, before_meta))
            if not replay and (current != plan['expected'] or before_meta != plan['metadata']):
                raise ValueError('stale native delivery source/revision/metadata snapshot')
            changed = [bid for bid, fingerprint in plan['fingerprints'].items()
                       if registry['books'].get(bid, {}).get('fingerprint') != fingerprint]
            before = {'target': plan['target'], 'snapshot': current, 'metadata': before_meta, 'plan_sha256': pin}
            owned = journals.enter_context(_journal(path, plan, pin, before))  # Complete write-set backup before the first DB mutation.
            if changed:
                models = [(bid, mid) for bid in changed for mid in current['books'][bid]['models']]
                notes = [(bid, row['note_id']) for bid in changed for row in current['books'][bid]['notes']]
                versions.bump_model_mods(db, models)
                versions.bump_content_mods(db, notes)
                post = _snapshot(db, plan['books'])
                for bid in changed:
                    previous, updated = current['books'][bid], post['books'][bid]
                    if (any(updated['models'][mid]['mod'] <= max(row['mod'], row['original_mod']) for mid, row in previous['models'].items()) or
                            any(new['content_mod'] <= max(old['content_mod'] or old['original_note_mod'], old['original_note_mod'])
                                for old, new in zip(previous['notes'], updated['notes']))):
                        raise ValueError('native delivery versions did not strictly advance')
                    registry['books'][bid] = {'fingerprint': plan['fingerprints'][bid]}
                registry['last_operation'] = {'plan_sha256': pin, 'post_source_sha256': _sha(post),
                    'post_versions': _version_pins(_metadata(db))}
                db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
                           (KEY, c.canonical(registry)))
            else:
                post = current
            after = {'target': plan['target'], 'snapshot': post, 'metadata': _metadata(db), 'plan_sha256': pin}
            seal = _post_journal(owned, before, after)
            result = {'schema': 'study-native-delivery-registration-result.v1', 'plan_sha256': pin,
                      'changed_books': changed, 'idempotent': not changed, 'native_versions': _native_versions(post),
                      'journal': str(path), 'journal_sha256': seal, 'metadata_after_sha256': _sha(after['metadata'])}
        _committed(owned, result)
    return result


def rollback_native_delivery(value, journal, *, expected_seal_sha256, unpublished=False, recovery_journal):
    """Restore this exact write set only before its packages were published.

    Source projections and all three current rows must still match after.json.
    A later registration, source change or unrelated version write rejects the
    entire rollback. No historical content/native/learning rows are restored.
    """
    if unpublished is not True:
        raise ValueError('explicit catalog and unpublished=True are required for rollback')
    value = _explicit_target(value)
    path = Path(journal)
    raw = (path / 'SEAL.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_seal_sha256:
        raise ValueError('native journal seal differs')
    seal = json.loads(raw)
    if (seal.get('schema') != 'study-native-delivery-journal.v1' or seal.get('write_keys') != list(WRITE_KEYS) or
            set(seal.get('files', {})) != {'plan.json', 'before.json', 'after.json'}):
        raise ValueError('invalid native journal scope')
    records = {}
    for name, expected in seal['files'].items():
        raw = (path / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('native journal bytes changed')
        records[name] = json.loads(raw)
    plan, pin = _plan(records['plan.json'])
    before, after = records['before.json'], records['after.json']
    if (set(before['metadata']) != set(WRITE_KEYS) or set(after['metadata']) != set(WRITE_KEYS) or
            _sha(before['metadata']) != seal['metadata_before_sha256'] or
            _sha(after['metadata']) != seal['metadata_after_sha256']):
        raise ValueError('native journal metadata scope differs')
    recovery = c.guard_new_output(recovery_journal)
    with ExitStack() as journals:
        with c.connect(value) as db, db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            c.write_lock(db)
            if (_target(db) != after['target'] or after['target'] != plan['target'] or
                    _snapshot(db, plan['books']) != after['snapshot'] or _metadata(db) != after['metadata']):
                raise ValueError('native rollback source or metadata changed after registration')
            owned = journals.enter_context(_journal(recovery, plan, pin, after))
            for key in WRITE_KEYS:
                raw = before['metadata'][key]
                if raw is None:
                    db.execute('delete from metadata where key=%s', (key,))
                else:
                    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value', (key, raw))
            restored = {'target': plan['target'], 'snapshot': _snapshot(db, plan['books']),
                        'metadata': _metadata(db), 'plan_sha256': pin}
            if restored['metadata'] != before['metadata'] or restored['snapshot'] != before['snapshot']:
                raise ValueError('native rollback did not restore exact metadata/projection')
            recovered_seal = _post_journal(owned, after, restored)
            result = {'schema': 'study-native-delivery-rollback-result.v1', 'plan_sha256': pin,
                      'restored_metadata_sha256': _sha(restored['metadata']), 'journal': str(recovery),
                      'journal_sha256': recovered_seal, 'native_versions': _native_versions(restored['snapshot'])}
        _committed(owned, result)
    return result
