#!/usr/bin/env python3
"""Build a separate source-bound sense-frequency web library.

All cards, resources and immutable snapshots are checked in private staging
before the output is published and the live sense database is activated. Never
replace a formal library entry, an APKG, media or the learning database.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_pipeline import sense_frequency as sf
from anki_pipeline import sense_components as sc
from anki_pipeline import sense_frequency_reconcile as sr
from anki_pipeline.web_preview import _UI_TEMPLATE_DIR
from scripts.prepare_sense_frequency_records import class_aliases, parse_card_page


def sha(content):
    return hashlib.sha256(content).hexdigest()


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _candidate_scope_options(source_displays, audit, audit_sha, supplement, supplement_sha):
    if not any(value is not None for value in (audit, audit_sha, supplement, supplement_sha)):
        return None
    if (not source_displays or audit is None or not isinstance(audit_sha, str) or
            not re.fullmatch(r'[0-9a-f]{64}', audit_sha) or
            (supplement is None) != (supplement_sha is None) or
            (supplement_sha is not None and (not isinstance(supplement_sha, str) or
                                             not re.fullmatch(r'[0-9a-f]{64}', supplement_sha)))):
        raise ValueError('candidate scope needs live source displays and explicitly pinned audit files')
    return {'audit_path': Path(audit).resolve(), 'expected_audit_sha256': audit_sha,
            'supplement_path': Path(supplement).resolve() if supplement is not None else None,
            'expected_supplement_sha256': supplement_sha}


def _read_records(path, book_id, *, inventory_records):
    """Read the explicitly selected format and bind the full input bytes."""
    if not inventory_records:
        content = path.read_bytes()
        records = json.loads(content)
        if not isinstance(records, list) or not records:
            raise ValueError('assignment input must be a nonempty array')
        return records, {'format': 'json-array', 'sha256': sha(content),
                         'source_records': len(records), 'selected_records': len(records)}
    records, book_counts, digest, source_count = [], {}, hashlib.sha256(), 0
    with path.open('rb') as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or record.get('book_id') not in {'redbook', 'redbook2027'}:
                raise ValueError(f'unknown book in mixed inventory at line {line_number}')
            source_count += 1
            identity = record['book_id']
            book_counts[identity] = book_counts.get(identity, 0) + 1
            if identity == book_id:
                records.append(record)
    if not records:
        raise ValueError('mixed inventory has no records for the selected book')
    return records, {'format': 'jsonl-mixed-inventory', 'sha256': digest.hexdigest(),
                     'source_records': source_count, 'selected_records': len(records),
                     'book_counts': book_counts}


def _book_identity(catalog, library):
    explicit = catalog.get('bookId', catalog.get('book_id'))
    if isinstance(explicit, str) and explicit.strip():
        return explicit
    # Shipped Red Book catalogs predate explicit book IDs. Bind these existing
    # editions to canonical identities instead of trusting an assignment file.
    title = catalog.get('deckName', '')
    if re.search(r'2027.*红宝书', title):
        return 'redbook2027'
    if re.search(r'2026.*红宝书', title):
        return 'redbook'
    raise ValueError(f'catalog has no recognized book identity: {library}')


def _validate_card(card, record, page, aliases, *, defer_frequency=False):
    provenance = record['definition_provenance']
    if (record['card_id'] != card['id'] or record['word'] != card['word'] or
            provenance.get('headword') != card['word'] or
            provenance.get('web_source') != card['previewUrl'] or
            provenance.get('page_sha256') != sha(page.encode('utf-8'))):
        raise ValueError('card, word or dictionary snapshot changed; recheck the assignments')
    parsed = parse_card_page(page, aliases)
    expected_senses = [{'pos': sense['pos'], 'text': sense['text']} for sense in record['senses']]
    if parsed['senses'] != expected_senses:
        raise ValueError('displayed definition order, part of speech or text differs from reviewed senses')
    names = sorted({component['source'] for component in parsed['definitions']})
    expected_source = names[0] if len(names) == 1 else 'mixed'
    if record['definition_source'] != expected_source:
        raise ValueError('displayed dictionary source differs from the reviewed source')
    if 'components' in provenance and provenance['components'] != parsed['definitions']:
        raise ValueError('displayed dictionary components differ from the reviewed snapshot')
    if parsed['declared_counts'] and sum(parsed['declared_counts']) != record['expected_occurrences']:
        if defer_frequency:
            # Only the live source-producer path may subsequently issue an
            # exact, reversible correction; no component report is planned yet.
            return None
        raise ValueError('physical occurrences differ from the displayed word frequency')
    return sc.plan_components(page, provenance.get('components'), aliases)


class _ResourceReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = set()
        self.embedded = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attribute = 'href' if tag == 'link' else 'data' if tag == 'object' else 'src'
        if tag in {'audio', 'video', 'source', 'img', 'script', 'iframe', 'link', 'object'}:
            if attrs.get(attribute):
                self.references.add(attrs[attribute])
        for name in ('srcdoc', 'data-web-etymology-srcdoc'):
            if name in attrs:
                self.embedded.append(attrs[name])

    handle_startendtag = handle_starttag


def _resource_references(page):
    parser = _ResourceReferences()
    parser.feed(page)
    references = parser.references
    for embedded in parser.embedded:
        child = _ResourceReferences()
        child.feed(embedded)
        references.update(child.references)
    return references


_RB_ASSET = re.compile(r'_rb_([0-9a-f]{24})\.(png|css|js)')
_RB_LITERAL = re.compile(r'''(?P<quote>["'])(?P<reference>_rb_[0-9a-f]{24}\.(?:png|css|js)(?:\#[^\s"']*)?)(?P=quote)''')


def _rb_asset_name(reference):
    """Only the original viewer's bare content-addressed media URLs qualify."""
    url = urlsplit(reference)
    if (url.scheme or url.netloc or url.query or '%' in url.path or
            not _RB_ASSET.fullmatch(url.path)):
        return None
    return url.path


def _is_viewer_resource_reference(reference):
    url = urlsplit(reference)
    return (not url.scheme and not url.netloc and
            _RB_ASSET.fullmatch(unquote(url.path).rsplit('/', 1)[-1]) is not None)


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate recovery package media key')
        value[key] = item
    return value


class _RecoveryPackage:
    """Read-only, explicitly pinned source for omitted original viewer media.

    An approved archive is not general missing-resource authority. Its media
    are usable only through each original card's exact URL or a literal in a
    byte-identical approved viewer script/style already reached from that URL.
    """
    def __init__(self, path, expected_sha256):
        self.path = Path(path).resolve(strict=True)
        if not isinstance(expected_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
            raise ValueError('recovery package needs an explicitly pinned full hash')
        if _file_sha(self.path) != expected_sha256:
            raise ValueError('recovery package hash differs from the approved input')
        self.sha256 = expected_sha256
        self.assets = {}
        with zipfile.ZipFile(self.path) as package:
            names = package.namelist()
            if len(names) != len(set(names)):
                raise ValueError('duplicate recovery package archive entry')
            media = package.read('media')
            mapping = json.loads(media, object_pairs_hook=_unique_json_object)
            if (not isinstance(mapping, dict) or any(not isinstance(key, str) or
                    not key.isdecimal() or not isinstance(name, str) for key, name in mapping.items())):
                raise ValueError('invalid recovery package media map')
            if len(mapping.values()) != len(set(mapping.values())):
                raise ValueError('duplicate recovery package media name')
            self.media_sha256 = sha(media)
            for member, name in mapping.items():
                match = _RB_ASSET.fullmatch(name)
                if match is None:
                    continue
                content = package.read(member)
                digest = sha(content)
                if not digest.startswith(match[1]):
                    raise ValueError('recovery package media content address differs from its bytes')
                self.assets[name] = {'content': content, 'archive_member': member,
                    'sha256': digest, 'bytes': len(content)}
        # The ZIP was read after hashing; close that race before issuing any
        # original-page resource evidence. It is checked again at activation.
        self.check()

    def check(self):
        if _file_sha(self.path) != self.sha256:
            raise ValueError('recovery package changed during construction')

    def verification(self):
        return {'path': str(self.path), 'sha256': self.sha256, 'media_sha256': self.media_sha256,
                'policy': 'exact original bare content-addressed viewer references and pinned literal dependency chains only'}


def _recovery_plan(page, document, version, card_url, package, *, references=None):
    """Bind an omitted-media plan to one unmodified original card.

    Never rewrite the source page, select another version by basename, or
    classify an image as inert. Missing media are actual viewer dependencies.
    """
    if package is None:
        return {}
    original = references if references is not None else _resource_references(page)
    queue = [(reference, [reference], []) for reference in sorted(original)]
    reached, recovered = set(), {}
    while queue:
        reference, chain, dependencies = queue.pop(0)
        if reference in reached:
            continue
        reached.add(reference)
        name = _rb_asset_name(reference)
        asset = package.assets.get(name) if name is not None else None
        if asset is None:
            # Ordinary validation still rejects a missing unapproved asset.
            if name is not None and len(chain) > 1:
                path = (document.parent / name).resolve()
                if not path.is_relative_to(version.resolve()) or not path.is_file():
                    raise FileNotFoundError('missing unapproved viewer dependency: ' + reference)
            continue
        path = (document.parent / name).resolve()
        if not path.is_relative_to(version.resolve()):
            raise ValueError('recovered card resource escapes its immutable version')
        node = {'reference': reference, 'media_name': name, 'archive_member': asset['archive_member'],
                'sha256': asset['sha256'], 'bytes': asset['bytes']}
        dependencies = dependencies + [node]
        if path.exists():
            if not path.is_file() or _file_sha(path) != asset['sha256']:
                raise ValueError('original viewer asset differs from the pinned content address')
        else:
            recovered[reference] = {'relative_path': str(path.relative_to(version.resolve())),
                'archive_member': asset['archive_member'], 'media_name': name,
                'sha256': asset['sha256'], 'bytes': asset['bytes'],
                'source_card_url': card_url, 'source_page_sha256': sha(page.encode('utf-8')),
                'reference_chain': chain,
                'dependency_chain': dependencies,
                'dependency_kind': 'original-html' if len(chain) == 1 else 'pinned-viewer-literal'}
        if name.endswith(('.js', '.css')):
            # The old image bridge stores state filenames as quoted literals.
            # Inspect only fully pinned original assets; no JS is executed and
            # arbitrary scripts/styles cannot grant additional recovery scope.
            text = asset['content'].decode('utf-8', errors='strict')
            queue.extend((match['reference'], chain + [match['reference']], dependencies)
                         for match in _RB_LITERAL.finditer(text))
    return recovered


def _check_recovered_resources(recovered_by_card, package, directory):
    if package is None:
        if any(recovered_by_card.values()):
            raise ValueError('recovered resources have no approved package')
        return
    package.check()
    checked = set()
    for resources in recovered_by_card.values():
        for proof in resources.values():
            parent = (directory / proof['relative_path']).parent
            # Existing original JS can also authorize a recovered state icon.
            # Its staged bytes must still match the pinned dependency evidence,
            # not only the final PNG or the archive from which it was read.
            for dependency in proof['dependency_chain']:
                path = parent / dependency['media_name']
                identity = (str(path), dependency['sha256'])
                if identity in checked:
                    continue
                if (path.is_symlink() or not path.is_file() or
                        path.stat().st_size != dependency['bytes'] or _file_sha(path) != dependency['sha256']):
                    raise ValueError('recovered source resource or authorizing dependency changed before activation')
                checked.add(identity)


def _shared_resource_path(reference, web_root):
    """Resolve an existing immutable asset without traversal or symlink aliases."""
    if web_root is None:
        raise ValueError('absolute card resource needs the local web root')
    url = urlsplit(reference)
    decoded = unquote(url.path)
    parts = decoded.split('/')
    if (url.scheme or url.netloc or '\\' in decoded or '\x00' in decoded or
            any(part in {'', '.', '..'} for part in parts[1:]) or
            not re.fullmatch(r'/[^/]+/web-preview/[0-9a-f]{64}/assets/(?:[^/]+/)*[^/]+', decoded)):
        raise ValueError('absolute shared card resource must name a versioned asset without traversal')
    root = Path(web_root).resolve()
    path = root
    for part in parts[1:]:
        path = path / part
        # An apparent version directory must not borrow another location's
        # identity through a symlink, even if the target happens to be in root.
        if path.is_symlink():
            raise ValueError('absolute shared card resource has a symlink escape or alias')
    path = path.resolve(strict=True)
    if not path.is_relative_to(root):
        raise ValueError('absolute shared card resource escapes the local web root')
    if not path.is_file():
        raise FileNotFoundError(f'missing shared card resource: {reference}')
    return path


def _local_resource(reference, document, version, *, web_root=None, shared_resources=None):
    url = urlsplit(reference)
    if url.scheme or url.netloc or reference.startswith('#'):
        return None
    if reference.startswith('/'):
        path = _shared_resource_path(reference, web_root)
        if shared_resources is not None:
            proof = shared_resources.get(reference)
            if proof is None:
                raise ValueError('shared resource is not authorized by this original card')
            if proof['path'] != str(path) or proof['sha256'] != _file_sha(path):
                raise ValueError('original shared card resource changed during construction')
        return path
    path = (document.parent / unquote(url.path)).resolve()
    if not path.is_relative_to(version.resolve()):
        raise ValueError('card resource escapes its immutable version')
    if not path.is_file():
        raise FileNotFoundError(f'missing card resource: {reference}')
    return path


def _check_shared_resources(shared_by_card, web_root):
    """Recheck original URL/path/bytes immediately before live activation."""
    checked = set()
    for resources in shared_by_card.values():
        for reference, proof in resources.items():
            path = _shared_resource_path(reference, web_root)
            if str(path) != proof['path']:
                raise ValueError('original shared card resource path changed before activation')
            identity = (str(path), proof['sha256'])
            if identity not in checked:
                if _file_sha(path) != proof['sha256']:
                    raise ValueError('original shared card resource changed before activation')
                checked.add(identity)


def _copy_resource(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        os.link(source, destination)


def _clone_database(source, destination):
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(destination)) as clone:
            original.backup(clone)
            if clone.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('sense database staging copy failed integrity check')


def _database_digest(path):
    """Hash SQLite's logical state, including committed WAL content."""
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        digest = hashlib.sha256()
        db.execute('BEGIN')
        for statement in db.iterdump():
            digest.update(statement.encode('utf-8'))
            digest.update(b'\n')
        digest.update(str(db.execute('PRAGMA user_version').fetchone()[0]).encode())
        return digest.hexdigest()


def _restore_database(original, destination):
    with closing(sqlite3.connect(original.resolve().as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(destination)) as active:
            source.backup(active)
            if active.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('sense database rollback failed integrity check')


def _publish(stage, output, database, records, backups, before_digest, original,
             *, shared_by_card=None, web_root=None, recovery_package=None,
             recovered_by_card=None, version=None):
    if _database_digest(database) != before_digest:
        raise ValueError('sense database changed during construction; rebuild from its current state')
    published = False
    try:
        # A filesystem failure must not activate assignments for an artifact
        # that was not successfully built. Nothing is rendered after activation.
        if output.exists():
            raise FileExistsError('preview output appeared during construction')
        os.rename(stage, output)
        published = True
        _check_shared_resources(shared_by_card or {}, web_root)
        _check_recovered_resources(recovered_by_card or {}, recovery_package,
                                   output / 'web-preview' / version if version else output)
        return sf.save_records(database, records, backups)
    except BaseException:
        if published:
            shutil.rmtree(output)
        if _database_digest(database) != before_digest:
            if original is None:
                database.unlink(missing_ok=True)
                for suffix in ('-wal', '-shm', '-journal'):
                    Path(str(database) + suffix).unlink(missing_ok=True)
            else:
                _restore_database(original, database)
                if _database_digest(database) != before_digest:
                    raise ValueError('sense database rollback did not restore the original state')
        raise


def build(library, records_path, database, output, backups, web_root, *, source_displays=False,
          inventory_records=False, candidate_scope_audit=None, candidate_scope_audit_sha256=None,
          candidate_scope_supplement=None, candidate_scope_supplement_sha256=None,
          recovery_package=None, recovery_package_sha256=None):
    scope_options = _candidate_scope_options(source_displays, candidate_scope_audit,
        candidate_scope_audit_sha256, candidate_scope_supplement, candidate_scope_supplement_sha256)
    library, records_path, database, output, backups, web_root = (
        Path(path).resolve() for path in (library, records_path, database, output, backups, web_root))
    if (recovery_package is None) != (recovery_package_sha256 is None):
        raise ValueError('recovery package and its explicitly approved hash must be supplied together')
    recovery = (_RecoveryPackage(recovery_package, recovery_package_sha256)
                if recovery_package is not None else None)
    if output.exists():
        raise FileExistsError('preview output must be a new directory')
    if not output.is_relative_to(web_root):
        raise ValueError('preview output must be inside the local web root')
    if database.is_relative_to(output) or library.is_relative_to(output):
        raise ValueError('preview output must not contain a live input or database')
    entry = library.read_text(encoding='utf-8')
    match = re.search(r'data-catalog-url="([^"]+)"', entry)
    if match is None:
        raise ValueError('source library has no catalog reference')
    catalog_path = (library.parent / html.unescape(match[1])).resolve(strict=True)
    if not catalog_path.is_relative_to(web_root):
        raise ValueError('source catalog escapes the local web root')
    source_version = catalog_path.parent
    if output.is_relative_to(source_version):
        raise ValueError('preview output must not be inside an immutable source version')
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    book_id = _book_identity(catalog, library)
    records, record_input = _read_records(records_path, book_id, inventory_records=inventory_records)
    if any('candidate_scope' in record for record in records):
        raise ValueError('serialized candidate scope requires original source replay and a live approved overlay')
    prepared = [sf.prepare_record(record) for record in records]
    if any(record['book_id'] != book_id for record in prepared):
        raise ValueError('reviewed records belong to another book')
    by_id = {record['card_id']: record for record in prepared}
    if len(by_id) != len(prepared):
        raise ValueError('assignment batch contains duplicate card identities')
    identities = [card['id'] for card in catalog['cards']]
    if len(set(identities)) != len(identities):
        raise ValueError('source catalog contains duplicate card identities')
    cards = [card for card in catalog['cards'] if card['id'] in by_id]
    if len(cards) != len(prepared):
        raise ValueError('reviewed cards must belong to the selected library')
    aliases, pages = class_aliases(source_version), []
    shared_by_card, shared_hashes, recovered_by_card, original_references = {}, {}, {}, {}
    for card in cards:
        url = card['previewUrl']
        source = (web_root / url.lstrip('/') if url.startswith('/') else library.parent / url).resolve(strict=True)
        if not source.is_relative_to(source_version):
            raise ValueError('card source escapes its immutable version')
        page = source.read_text(encoding='utf-8')
        region = _validate_card(card, by_id[card['id']], page, aliases, defer_frequency=source_displays)
        resources, shared = [], {}
        references = _resource_references(page)
        original_references[card['id']] = references
        recovered = _recovery_plan(page, source, source_version, card['previewUrl'], recovery,
                                   references=references)
        recovered_by_card[card['id']] = recovered
        for reference in sorted(references):
            try:
                resource = _local_resource(reference, source, source_version, web_root=web_root)
            except FileNotFoundError:
                if reference not in recovered:
                    raise
                continue
            if resource is None:
                continue
            if reference.startswith('/'):
                if resource not in shared_hashes:
                    shared_hashes[resource] = _file_sha(resource)
                shared[reference] = {'path': str(resource), 'sha256': shared_hashes[resource],
                    'source_card_url': card['previewUrl'], 'source_page_sha256': sha(page.encode('utf-8'))}
            else:
                resources.append(resource)
        shared_by_card[card['id']] = shared
        pages.append((card, source, page, region, resources))

    frequency_plans, render_pages, candidate_ledgers = {}, {}, {}
    if source_displays:
        from anki_pipeline.sense_display import attach_source_displays
        originals = {card['id']: page for card, _, page, _, _ in pages}
        mismatches = {card['id'] for card, _, _, plan, _ in pages if plan is None}
        scope_cards = ({record['card_id'] for record in records if record['word'] in {'a', 'a/an'}}
                       if scope_options else set())
        if scope_options and not scope_cards:
            raise ValueError('candidate scope has no eligible source card in this library')
        checked_ids = mismatches | scope_cards
        verified_by_id = {}
        if checked_ids:
            checked, authority = sr.reread_source_displays(
                [record for record in records if record['card_id'] in checked_ids], originals, aliases)
            scopes = None
            if scope_options:
                from anki_pipeline.sense_candidate_scope import apply_candidate_scope
                checked, scopes = apply_candidate_scope(checked, originals, aliases,
                                                       verified_sources=authority, **scope_options)
                authority = scopes.verified_sources
            for record in checked:
                identifier = record['card_id']
                scope = scopes.for_record(record) if scopes is not None else None
                plan = sr.plan_frequency_panel(originals[identifier], record, aliases,
                                               verified_sources=authority, candidate_scope=scope)
                if plan is None and identifier in mismatches:
                    raise ValueError('displayed frequency discrepancy was not reconciled by the approved sources')
                if plan is not None:
                    frequency_plans[identifier] = plan
                    render_pages[identifier] = sr.apply_frequency_panel(originals[identifier], plan)
                if scope is not None:
                    candidate_ledgers[identifier] = scope.verification()
                    record = {**record, 'candidate_scope': candidate_ledgers[identifier]}
                verified_by_id[identifier] = record
        remaining = [record for record in records if record['card_id'] not in checked_ids]
        if remaining:
            checked = attach_source_displays(remaining, originals, aliases)
            verified_by_id.update({record['card_id']: record for record in checked})
        records = [verified_by_id[record['card_id']] for record in records]
        prepared = [sf.prepare_record(record) for record in records]
        by_id = {record['card_id']: record for record in prepared}
        pages = [(card, source, page, plan if card['id'] not in frequency_plans else sc.plan_components(
            render_pages[card['id']], by_id[card['id']]['definition_provenance'].get('components'), aliases), resources)
            for card, source, page, plan, resources in pages]

    before_digest = _database_digest(database)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.sense-preview-', dir=output.parent))
    try:
        # Private database copies stay outside the public web root.
        with tempfile.TemporaryDirectory(prefix='sense-preview-db-') as private:
            private = Path(private)
            original = private / 'original.sqlite3' if database.exists() else None
            staged_database = private / 'staged.sqlite3'
            if original is not None:
                _clone_database(database, original)
                _clone_database(original, staged_database)
            staged_save = sf.save_records(staged_database, records, private / 'backups')
            renderer = {name: sha(path.read_bytes()) for name, path in {
                'sense_frequency.py': Path(sf.__file__),
                'sense_chunks.py': Path(sf.__file__).with_name('sense_chunks.py'),
                'sense_display.py': Path(sf.__file__).with_name('sense_display.py'),
                'sense_components.py': Path(sf.__file__).with_name('sense_components.py'),
                'sense_frequency_reconcile.py': Path(sr.__file__),
                'sense_candidate_scope.py': Path(sf.__file__).with_name('sense_candidate_scope.py'),
                'sense-frequency.css': _UI_TEMPLATE_DIR / 'sense-frequency.css',
                'sense-frequency.js': _UI_TEMPLATE_DIR / 'sense-frequency.js',
                'build_sense_frequency_preview.py': Path(__file__),
            }.items()}
            version = sha(json.dumps({'snapshots': staged_save['snapshots'], 'renderer': renderer,
                                     'shared_source_resources': shared_by_card,
                                     'recovered_source_resources': recovered_by_card,
                                     'recovery_package': recovery.verification() if recovery else None},
                                     sort_keys=True).encode('utf-8'))
            directory = stage / 'web-preview' / version
            (directory / 'cards').mkdir(parents=True)
            (directory / 'assets').mkdir()
            selected, manifest, counts = [], {}, []
            for path in (source_version / 'cards').iterdir():
                if path.is_file() and path.suffix in {'.css', '.js', '.png', '.gif', '.svg'}:
                    _copy_resource(path, directory / 'cards' / path.name)
            for path in (source_version / 'assets').iterdir():
                if path.is_file():
                    _copy_resource(path, directory / 'assets' / path.name)
            for recovered in recovered_by_card.values():
                for proof in recovered.values():
                    target = directory / proof['relative_path']
                    content = recovery.assets[proof['media_name']]['content']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        if _file_sha(target) != proof['sha256']:
                            raise ValueError('conflicting recovered source resource bytes')
                    else:
                        target.write_bytes(content)
            for card, source, page, definition, resources in pages:
                report = sf.read_card(staged_database, book_id, card['id'])
                if report is None:
                    raise ValueError('staged sense snapshot is missing')
                if (report['book_id'] != book_id or report['card_id'] != card['id'] or
                        report['snapshot_id'] != by_id[card['id']]['snapshot_id'] or
                        report['definition_provenance'] != by_id[card['id']]['definition_provenance']):
                    raise ValueError('staged report does not match its validated assignment snapshot')
                render_page = render_pages.get(card['id'], page)
                revised = sc.inject_component_report(render_page, definition, report)
                restored = sc.remove_component_report(revised, definition)
                if card['id'] in frequency_plans:
                    restored = sr.restore_frequency_panel(restored, frequency_plans[card['id']])
                if restored != page:
                    raise ValueError('unrelated card content changed')
                target = directory / source.relative_to(source_version)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(revised, encoding='utf-8')
                for resource in resources:
                    _copy_resource(resource, directory / resource.relative_to(source_version))
                for reference in _resource_references(revised):
                    if (_is_viewer_resource_reference(reference) and
                            reference not in original_references[card['id']]):
                        raise ValueError('viewer resource is not authorized by this original card')
                    _local_resource(reference, target, directory, web_root=web_root,
                                    shared_resources=shared_by_card[card['id']])
                manifest[source.name] = {'before': sha(page.encode('utf-8')),
                    'after': sha(revised.encode('utf-8')), 'snapshot_id': report['snapshot_id']}
                selected.append({**card, 'previewUrl': '/' + str(output.relative_to(web_root) /
                    'web-preview' / version / source.relative_to(source_version))})
                counts.append({'word': report['word'], 'total': report['total'],
                    'pending': report['pending_count'],
                    'senses': [{'meaning': sense['text'], 'count': sense['count'], 'years': sense['years']}
                               for sense in report['senses']]})
            ids = set(by_id)
            decks = [{**deck, 'cardIds': [card_id for card_id in deck['cardIds'] if card_id in ids],
                      'count': sum(card_id in ids for card_id in deck['cardIds'])}
                     for deck in catalog['decks'] if any(card_id in ids for card_id in deck['cardIds'])]
            trial = {**catalog, 'deckName': f"{catalog['deckName']} · 义项频次预览（{len(selected)}词）",
                     'cards': selected, 'decks': decks, 'counts': {'cards': len(selected),
                     'decks': len(decks), 'examples': sum(card['exampleCount'] for card in selected)}}
            (directory / 'catalog.json').write_text(json.dumps(trial, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            shell = (_UI_TEMPLATE_DIR / 'library-preview.html').read_text(encoding='utf-8').replace(
                '__CATALOG_URL__', f'web-preview/{version}/catalog.json').replace(
                '__ASSET_BASE__', f'web-preview/{version}/assets/')
            for name in ('library-preview.css', 'library-preview.js'):
                path = directory / 'assets' / name
                if path.exists():
                    path.unlink()
                shutil.copyfile(_UI_TEMPLATE_DIR / name, path)
            (stage / 'preview-library.html').write_text(shell, encoding='utf-8')
            verification = {'scope': 'source-bound sense-frequency preview', 'book_id': book_id,
                'database': str(database), 'source_catalog': str(catalog_path),
                'record_input': record_input,
                'shared_source_resources': shared_by_card,
                'shared_resource_policy': 'original per-card URLs only; existing versioned assets inside web_root; rechecked before activation',
                'recovery_package': recovery.verification() if recovery else None,
                'recovered_source_resources': recovered_by_card,
                'frequency_reconciliations': {identifier: plan.verification()
                    for identifier, plan in frequency_plans.items()},
                'candidate_scopes': candidate_ledgers,
                'cards': manifest, 'counts': counts, 'renderer_sha256': renderer,
                'snapshot_ids': staged_save['snapshots'], 'database_activation': 'after resource and page validation'}
            (stage / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            if _file_sha(records_path) != record_input['sha256']:
                raise ValueError('assignment input changed during construction; rebuild from a fixed input')
            if scope_options:
                for path_key, sha_key in (('audit_path', 'expected_audit_sha256'),
                                          ('supplement_path', 'expected_supplement_sha256')):
                    if scope_options[path_key] is not None and _file_sha(scope_options[path_key]) != scope_options[sha_key]:
                        raise ValueError('candidate scope audit changed during construction')
            save = _publish(stage, output, database, records, backups, before_digest, original,
                            shared_by_card=shared_by_card, web_root=web_root,
                            recovery_package=recovery, recovered_by_card=recovered_by_card, version=version)
            return {'entry': str(output / 'preview-library.html'), 'version': version,
                    'words': counts, 'save': save}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('library', 'records', 'database', 'output', 'backups', 'web-root'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--source-displays', action='store_true',
                        help='reuse approved native question/option displays and authored chunk mappings')
    parser.add_argument('--inventory-records', action='store_true',
                        help='read a mixed Red Book JSONL inventory and select the source library edition')
    parser.add_argument('--candidate-scope-audit', type=Path)
    parser.add_argument('--candidate-scope-audit-sha256')
    parser.add_argument('--candidate-scope-supplement', type=Path)
    parser.add_argument('--candidate-scope-supplement-sha256')
    parser.add_argument('--recovery-package', type=Path,
                        help='explicitly approved APKG containing omitted original viewer media')
    parser.add_argument('--recovery-package-sha256',
                        help='approved full SHA256 of --recovery-package; no implicit archive discovery')
    args = parser.parse_args()
    print(json.dumps(build(args.library, args.records, args.database, args.output,
                           args.backups, args.web_root, source_displays=args.source_displays,
                           inventory_records=args.inventory_records,
                           candidate_scope_audit=args.candidate_scope_audit,
                           candidate_scope_audit_sha256=args.candidate_scope_audit_sha256,
                           candidate_scope_supplement=args.candidate_scope_supplement,
                           candidate_scope_supplement_sha256=args.candidate_scope_supplement_sha256,
                           recovery_package=args.recovery_package,
                           recovery_package_sha256=args.recovery_package_sha256),
                     ensure_ascii=False, indent=2))
