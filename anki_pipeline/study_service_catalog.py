"""Read-only catalogs for the existing study HTTP and scheduler identities.

The caller owns one REPEATABLE READ, READ ONLY transaction. Registration selects
presentation paths/separators, never a subject-specific code path. The migrated
aliases select learning membership; native supplements are not implicitly added.
This module opens no connection, initializes nothing, and reads no card HTML.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urljoin, urlsplit

from psycopg.pq import TransactionStatus

from . import study_catalog as catalog
from . import study_catalog_library as library
from . import study_progress_migration as migration
from . import study_progress_pg as pg
from .preview_static_mounts import MountDenied, Resource, request_path


REGISTRY_SCHEMA = 'study-service-catalog.v1'
PROJECTION_REGISTRY_SCHEMA = 'study-service-catalog.v2'
_REPORT_SCHEMA = 'study-progress-current-bindings-readonly.v1'
_HEX = re.compile(r'[a-f0-9]{64}')
_TARGET_FIELDS = {'book_id', 'source_id', 'note_id', 'guid', 'model_id',
                  'native_id', 'template_ordinal', 'unit_id'}
_TARGET_INTS = {'note_id', 'model_id', 'native_id', 'template_ordinal', 'unit_id'}


class ServiceCatalogError(ValueError):
    """The runtime registration or authenticated catalog cannot be served."""


def _require(condition, message):
    if not condition:
        raise ServiceCatalogError(message)


def _fields(value, names, message):
    _require(type(value) is dict and set(value) == set(names), message)


def _text(value):
    return type(value) is str and bool(value) and '\x00' not in value


def _integer(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _parse(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _require(False, 'nonfinite JSON'))
    except (ValueError, TypeError, UnicodeError) as error:
        raise ServiceCatalogError('invalid catalog or migration JSON') from error


def _stamp(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _path(root, url):
    _require(_text(url), 'a registered local URL is required')
    parsed = urlsplit(url)
    _require(not (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment),
             'only local paths without queries or fragments are registered')
    return root / request_path(url).lstrip('/')


def _read_file(root, path, proof=None):
    """Authenticate and parse bytes read on the same, confined descriptor."""
    path = Path(path)
    before = path.lstat()
    resolved = path.resolve(strict=True)
    _require(resolved.is_relative_to(root), 'catalog path escapes the document root')
    stream, opened = Resource(resolved, root).open()
    with stream:
        _require(stat.S_ISREG(opened.st_mode), 'catalog is not a regular file')
        size = proof['bytes'] if proof is not None else opened.st_size
        raw = stream.read(size + 1)
        _require(len(raw) == size and _stamp(os.fstat(stream.fileno())) == _stamp(opened),
                 'catalog changed during its read')
        _require(_stamp(resolved.lstat()) == _stamp(opened) and
                 _stamp(path.lstat()) == _stamp(before) and path.resolve(strict=True) == resolved,
                 'catalog path changed during its read')
        if proof is not None:
            _require(_sha(raw) == proof['sha256'], 'catalog byte SHA differs from its approved pin')
    return raw


def _regular_file(root, path):
    resolved = path.resolve(strict=True)
    _require(resolved.is_relative_to(root), 'preview path escapes the document root')
    stream, _ = Resource(resolved, root).open()
    stream.close()  # Existence/type validation only; never read large card HTML.


def _authenticated_report(db):
    _require(db.info.transaction_status == TransactionStatus.INTRANS,
             'caller must own an explicit read-only transaction')
    isolation, readonly, schema = db.execute(
        "select current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_schema()"
    ).fetchone()
    _require((isolation, readonly) == ('repeatable read', 'on'),
             'runtime catalog requires REPEATABLE READ, READ ONLY')
    rows = db.execute('select key,value from metadata where key=any(%s)',
                      ([migration.ALIASES_KEY, migration.RECEIPT_KEY],)).fetchall()
    _require(len(rows) == 2 and {row[0] for row in rows} ==
             {migration.ALIASES_KEY, migration.RECEIPT_KEY}, 'complete migrated aliases and receipt are required')
    values = dict(rows)
    aliases, receipt = _parse(values[migration.ALIASES_KEY]), _parse(values[migration.RECEIPT_KEY])
    _fields(aliases, {'schema', 'approved_report', 'artifact', 'inactive_cards', 'inactive_books'},
            'unsupported migrated aliases')
    _require(aliases['schema'] == 'study-progress-aliases.v1' and
             type(aliases['inactive_cards']) is list and type(aliases['inactive_books']) is list,
             'unsupported migrated aliases')
    _fields(receipt, {'schema', 'target_schema', 'storage', 'source', 'aliases_sha256',
                     'alias_artifact', 'catalog_revision', 'plan_sha256', 'ready_to_switch'},
            'unsupported migration receipt')
    _fields(aliases['artifact'], {'sha256', 'bytes'}, 'invalid alias artifact pin')
    _require(type(aliases['artifact']['sha256']) is str and
             _HEX.fullmatch(aliases['artifact']['sha256']) and
             _integer(aliases['artifact']['bytes']) and aliases['artifact']['bytes'] > 0,
             'invalid alias artifact pin')
    _fields(receipt['source'], {'sha256', 'bytes', 'snapshot'}, 'invalid source seal')
    _require(type(receipt['source']['sha256']) is str and
             _HEX.fullmatch(receipt['source']['sha256']) and
             _integer(receipt['source']['bytes']) and receipt['source']['bytes'] > 0 and
             type(receipt['source']['snapshot']) is dict, 'invalid source seal')
    core = {key: value for key, value in receipt.items() if key not in {'plan_sha256', 'ready_to_switch'}}
    _require(receipt['schema'] == migration.IMPORT_SCHEMA and receipt['target_schema'] == schema and
             receipt['storage'] == pg.DESCRIPTOR and receipt['ready_to_switch'] is False and
             receipt['alias_artifact'] == aliases['artifact'] and
             receipt['aliases_sha256'] == _sha(catalog.canonical(aliases).encode()) and
             receipt['plan_sha256'] == _sha(catalog.canonical(core).encode()),
             'migration receipt does not authenticate these aliases')
    report = aliases['approved_report']
    _fields(report, {'schema', 'catalog_revision', 'books', 'bindings', 'guide_proofs',
                     'excluded_from_legacy_learning_catalog', 'captured_at', 'scope', 'ready_to_switch'},
            'unsupported approved identity report')
    _require(report['schema'] == _REPORT_SCHEMA and report['ready_to_switch'] is False and
             _integer(report['catalog_revision']) and receipt['catalog_revision'] == report['catalog_revision'] and
             type(report['books']) is list and type(report['bindings']) is list and
             type(report['guide_proofs']) is dict and
             type(report['excluded_from_legacy_learning_catalog']) is list,
             'invalid approved identity report')
    # The report revision is historical provenance, not the current event count:
    # a later scope registration legitimately advances catalog events.
    return report


def _native_identities(db, book):
    source = db.execute('select s.source_id,x.status,s.col_payload_id from book_sources s '
                        'join books b on b.id=s.book_id join sources x on x.id=s.source_id '
                        'where b.id=%s', (book['book_id'],)).fetchone()
    _require(source is not None and source[:2] == (book['source_id'], 'complete'),
             'canonical book/source is absent, incomplete, or changed')
    try:
        models = _parse(catalog.get_json(db, source[2])['models'])
    except (KeyError, TypeError) as error:
        raise ServiceCatalogError('invalid source model registry') from error
    _require(type(models) is dict, 'invalid source model registry')
    rows = db.execute('select n.native_id,n.note_id,a.guid,a.model_id,n.ordinal,n.unit_id,'
                      'a.source_card_id,a.kind from native_cards n join notes a '
                      'on a.book_id=n.book_id and a.note_id=n.note_id '
                      'join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s',
                      (book['book_id'],)).fetchall()
    _require(len(rows) == book['native_cards'], 'canonical native card count changed')
    result = {}
    for native, note, guid, model, ordinal, unit, source_id, kind in rows:
        _require(all(_integer(value) for value in (native, note, model, ordinal, unit)) and _text(guid),
                 'invalid native identity tuple')
        model_value = models.get(str(model))
        templates = model_value.get('tmpls') if type(model_value) is dict else None
        _require(type(templates) is list and ordinal < len(templates) and
                 type(templates[ordinal]) is dict and type(templates[ordinal].get('ord')) is int and
                 templates[ordinal]['ord'] == ordinal, 'canonical model/template changed')
        key = (book['book_id'], native)
        _require(key not in result, 'duplicate native identity')
        result[key] = ({'book_id': book['book_id'], 'source_id': book['source_id'], 'note_id': note,
                        'guid': guid, 'model_id': model, 'native_id': native,
                        'template_ordinal': ordinal, 'unit_id': unit}, source_id, kind)
    return result


def _book(root, registration, approved):
    proof = approved['catalog']
    _fields(proof, {'path', 'sha256', 'bytes'}, 'invalid approved catalog pin')
    _require(_text(proof['path']) and Path(proof['path']).is_absolute() and
             type(proof['sha256']) is str and _HEX.fullmatch(proof['sha256']) and
             _integer(proof['bytes']) and proof['bytes'] > 0, 'invalid approved catalog pin')
    preview = _path(root, registration['previewPath'])
    _require(preview.suffix == '.html', 'registered entry must be HTML')
    book_root = preview.parent.resolve(strict=True)
    match = re.search(r'data-catalog-url="([^"]+)"', _read_file(root, preview).decode('utf-8'))
    _require(match is not None, 'registered entry has no catalog')
    declared = _path(root, urljoin(registration['previewPath'], match[1]))
    _require(declared.resolve(strict=True).is_relative_to(book_root) and
             declared.resolve(strict=True) == Path(proof['path']).resolve(strict=True),
             'registered entry points to an unapproved catalog')
    legacy = _parse(_read_file(root, Path(proof['path']), proof))
    _require(type(legacy) is dict and legacy.get('schema') == 'anki-web-catalog.v1' and
             _text(legacy.get('deckName')) and type(legacy.get('cards')) is list and
             type(legacy.get('decks')) is list and type(legacy.get('counts')) is dict and
             type(legacy['counts'].get('cards')) is int, 'unsupported learning catalog')
    decks, members, cards, local = {}, set(), [], {}
    for deck in legacy['decks']:
        _require(type(deck) is dict and _text(deck.get('id')) and deck['id'] not in decks and
                 type(deck.get('cardIds')) is list and all(_text(key) for key in deck['cardIds']) and
                 len(set(deck['cardIds'])) == len(deck['cardIds']), 'invalid deck membership')
        _require('count' not in deck or type(deck['count']) is int and deck['count'] == len(deck['cardIds']),
                 'deck count differs from membership')
        decks[deck['id']] = set(deck['cardIds'])
        members.update(deck['cardIds'])
    for source in legacy['cards']:
        _require(type(source) is dict and all(type(source.get(name)) is str for name in
                 ('id', 'deckId', 'unit', 'lesson', 'position', 'previewUrl')) and
                 _text(source['id']) and source['id'] not in local and
                 source['deckId'] in decks and source['id'] in decks[source['deckId']],
                 'card/deck membership differs')
        href = urljoin(registration['previewPath'], source['previewUrl'])
        path = _path(root, href)
        _require(path.parent.name == 'cards' and path.suffix == '.html', 'unregistered card preview path')
        _require(path.resolve(strict=True).is_relative_to(book_root),
                 'card path escapes its registered book directory')
        _regular_file(root, path)
        card = dict(source)
        card['previewUrl'] = urlsplit(href).path
        unit = re.sub(r'\b(Unit|Lesson)\s+0*(\d+)', r'\1 \2', card['unit'])
        lesson = re.sub(r'\b(Unit|Lesson)\s+0*(\d+)', r'\1 \2', card['lesson'])
        card['meta'] = unit + registration['unitLessonSeparator'] + lesson + ' ➫ ' + card['position']
        cards.append(card)
        local[card['id']] = card['deckId']
    _require(len(cards) == approved['cards'] == legacy['counts']['cards'] and members == set(local) and
             all(keys == {card for card, owner in local.items() if owner == deck} for deck, keys in decks.items()),
             'complete catalog/card/deck membership differs')
    key = registration['id']
    return {'id': key, 'name': legacy['deckName'], 'cards': cards, 'decks': legacy['decks'],
            'previewPath': registration['previewPath']}, local


def _bindings(report, active, native, approved):
    seen, targets, guide_books = set(), set(), set()
    for binding in report['bindings']:
        _fields(binding, {'evidence', 'legacy', 'target'}, 'invalid approved binding')
        old, target = binding['legacy'], binding['target']
        _fields(old, {'book', 'card_id', 'deck_id'}, 'invalid legacy binding')
        _fields(target, _TARGET_FIELDS, 'invalid native binding')
        _require(all(_text(value) for value in old.values()) and
                 all(_integer(target[key]) if key in _TARGET_INTS else _text(target[key])
                     for key in _TARGET_FIELDS), 'invalid binding identity fields')
        key, new = (old['book'], old['card_id']), (target['book_id'], target['native_id'])
        _require(key not in seen and new not in targets and key in active and
                 active[key] == old['deck_id'] and approved[old['book']]['book_id'] == target['book_id'] and
                 new in native and native[new][0] == target, 'approved identity tuple changed')
        seen.add(key)
        targets.add(new)
        _, source_id, kind = native[new]
        if binding['evidence'] == 'exact-source-card-id':
            _require(source_id == old['card_id'], 'source card identity changed')
        elif binding['evidence'] == 'exact-guide-proof':
            proof = report['guide_proofs'].get(old['book'])
            _fields(proof, {'evidence', 'guid', 'id', 'native_id', 'note_id', 'template_ordinal'},
                    'guide identity proof is missing')
            _require(source_id is None and kind == 'guide' and proof['id'] == old['card_id'] and
                     all(proof[key] == target[key] for key in ('guid', 'native_id', 'note_id', 'template_ordinal')) and
                     type(proof['evidence']) is dict and proof['evidence'].get('kind') in
                     {'exact-native-and-web-identity-derivation', 'every-original-field-exact-in-legacy-page-and-native-GUID'},
                     'guide identity proof changed')
            guide_books.add(old['book'])
        else:
            raise ServiceCatalogError('unsupported approved binding evidence')
    _require(seen == set(active) and guide_books == set(report['guide_proofs']),
             'approved aliases do not exactly cover learning membership')
    excluded = set()
    for item in report['excluded_from_legacy_learning_catalog']:
        _require(type(item) is dict and _TARGET_FIELDS.issubset(item) and
                 _integer(item['native_id']) and _text(item['book_id']), 'invalid excluded identity')
        key = item['book_id'], item['native_id']
        _require(key not in excluded and key not in targets and key in native and
                 all(item[name] == native[key][0][name] for name in _TARGET_FIELDS) and
                 item.get('id') == native[key][1] and item.get('kind') == native[key][2] and
                 _text(item.get('reason')), 'excluded native identity changed')
        excluded.add(key)
    _require(targets | excluded == set(native), 'native coverage requires explicit bindings or exclusions')


def _load_books(db, *, document_root, registry, static_mounts=None):
    """Return legacy books plus current registered scope, without writes/seeding.

    v1 rows have exactly ``id``, ``previewPath`` and ``unitLessonSeparator``;
    v2 adds exactly one ``projection`` descriptor. List order and every returned
    field retain the legacy public shape when a book has no classification.
    Current scopes use canonical book IDs in this same read-only PG snapshot;
    presentation paths and learning aliases never determine classification.
    Routes follow the same native/alias authentication, not a second loader.
    """
    try:
        root = Path(document_root).resolve(strict=True)
        _require(root.is_dir(), 'document root must be an existing directory')
        _fields(registry, {'schema', 'books'}, 'unsupported service catalog registry')
        _require(registry['schema'] in {REGISTRY_SCHEMA, PROJECTION_REGISTRY_SCHEMA} and type(registry['books']) is list and
                 registry['books'], 'empty or unsupported service catalog registry')
        projected = registry['schema'] == PROJECTION_REGISTRY_SCHEMA
        registrations = {}
        for row in registry['books']:
            _fields(row, {'id', 'previewPath', 'unitLessonSeparator'} | ({'projection'} if projected else set()),
                    'invalid book registration')
            _require(_text(row['id']) and row['id'] not in registrations and
                     type(row['unitLessonSeparator']) is str and '\x00' not in row['unitLessonSeparator'],
                     'invalid or duplicate book registration')
            registrations[row['id']] = row
        report = _authenticated_report(db)
        scopes = library.scopes(db)
        _require(type(scopes) is dict, 'invalid library scope registry')
        approved, canonical_books = {}, set()
        for book in report['books']:
            _fields(book, {'book_id', 'legacy_book', 'source_id', 'cards', 'native_cards', 'catalog'},
                    'invalid approved book')
            _require(all(_text(book[key]) for key in ('book_id', 'legacy_book', 'source_id')) and
                     all(_integer(book[key]) for key in ('cards', 'native_cards')) and
                     book['legacy_book'] not in approved and book['book_id'] not in canonical_books,
                     'invalid or duplicate approved book')
            approved[book['legacy_book']] = book
            canonical_books.add(book['book_id'])
        _require(set(registrations) == set(approved), 'registration must exactly cover approved books')
        books, active, native = {}, {}, {}
        for key, row in registrations.items():
            books[key], members = _book(root, row, approved[key])
            canonical = approved[key]['book_id']
            if canonical in scopes:
                books[key]['scope'] = library.validate_scope(scopes[canonical])
            active.update({(key, card): deck for card, deck in members.items()})
            native.update(_native_identities(db, approved[key]))
        _bindings(report, active, native, approved)
        existing = set(db.execute('select book,card_id from study_progress_cards where book=any(%s)',
                                  (list(books),)).fetchall())
        _require(set(active).issubset(existing), 'migrated active progress identities are missing; no implicit seed')
        for table in ('settings', 'undo'):
            present = {row[0] for row in db.execute(
                'select book from study_progress_' + table + ' where book=any(%s)', (list(books),)).fetchall()}
            _require(present == set(books), 'migrated book ' + table + ' rows are incomplete')
        routes = None
        if projected:
            from .study_preview_routes import StudyPreviewRoutes
            routes = StudyPreviewRoutes(static_mounts, books, registrations, report)
        return books, routes
    except ServiceCatalogError:
        raise
    except (OSError, ValueError, TypeError, KeyError, MountDenied) as error:
        raise ServiceCatalogError('runtime catalog cannot be authenticated: ' + type(error).__name__) from error


def load_books(db, *, document_root, registry, static_mounts=None):
    """Return authenticated books and optional scopes; v2 also verifies routes."""
    return _load_books(db, document_root=document_root, registry=registry, static_mounts=static_mounts)[0]


def load_books_and_routes(db, *, document_root, registry, static_mounts):
    """Authenticate once in the caller's RR/RO transaction; v2 routes are mandatory."""
    _require(type(registry) is dict and registry.get('schema') == PROJECTION_REGISTRY_SCHEMA,
             'projection service requires a v2 catalog registry')
    return _load_books(db, document_root=document_root, registry=registry, static_mounts=static_mounts)
