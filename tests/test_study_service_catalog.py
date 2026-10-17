"""Runtime-provider contracts using small files and a SELECT-only PG fixture."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urljoin, urlsplit

from psycopg.pq import TransactionStatus

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_progress_migration as migration
from anki_pipeline import study_progress_pg as pg
from anki_pipeline import study_service_catalog as provider


def digest(value):
    return hashlib.sha256(value).hexdigest()


class Rows:
    def __init__(self, values):
        self.values = list(values)

    def fetchone(self):
        return self.values[0] if self.values else None

    def fetchall(self):
        return self.values


class ReadOnlyDatabase:
    """Records SQL and refuses every statement outside the provider's reads."""
    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        self.isolation, self.read_only, self.schema = 'repeatable read', 'on', 'fixture_catalog'
        self.metadata, self.sources, self.natives, self.objects = {}, {}, {}, {}
        self.progress, self.settings, self.undo, self.calls = set(), set(), set(), []

    def execute(self, statement, parameters=None):
        query = ' '.join(statement.split())
        self.calls.append((query, parameters))
        if not query.lower().startswith('select '):
            raise AssertionError('provider attempted a write: ' + query)
        if query == "select current_setting('transaction_isolation'),current_setting('transaction_read_only'),current_schema()":
            return Rows([(self.isolation, self.read_only, self.schema)])
        if query == 'select key,value from metadata where key=any(%s)':
            return Rows((key, value) for key, value in self.metadata.items() if key in parameters[0])
        if query.startswith('select s.source_id,x.status,s.col_payload_id from book_sources s '):
            return Rows([self.sources[parameters[0]]] if parameters[0] in self.sources else [])
        if query.startswith('select n.native_id,n.note_id,a.guid,a.model_id,n.ordinal,n.unit_id,'):
            return Rows(self.natives.get(parameters[0], []))
        if query == 'select book,card_id from study_progress_cards where book=any(%s)':
            return Rows(sorted(row for row in self.progress if row[0] in parameters[0]))
        if query == 'select book from study_progress_settings where book=any(%s)':
            return Rows((key,) for key in sorted(self.settings & set(parameters[0])))
        if query == 'select book from study_progress_undo where book=any(%s)':
            return Rows((key,) for key in sorted(self.undo & set(parameters[0])))
        raise AssertionError('unregistered provider SELECT: ' + query)


class ServiceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'public'
        self.root.mkdir()
        self.db = ReadOnlyDatabase()
        self.registry = {'schema': 'study-service-catalog.v1', 'books': []}
        self.report = {'schema': 'study-progress-current-bindings-readonly.v1',
                       'catalog_revision': 11, 'books': [], 'bindings': [], 'guide_proofs': {},
                       'excluded_from_legacy_learning_catalog': [], 'captured_at': 'fixture',
                       'scope': 'fixture', 'ready_to_switch': False}

    def add_book(self, legacy='liu', canonical='liuxiaoyan2027', *, separator=' ➫ ',
                 entry='preview-library.html', card_id='a' * 64, template=0):
        entry_path = self.root / entry
        card_url = 'web-preview/fixture/cards/' + card_id + '.html'
        card_path = entry_path.parent / card_url
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_text('not parsed by provider')
        value = {'schema': 'anki-web-catalog.v1', 'deckName': 'Any subject ' + legacy,
                 'cards': [{'id': card_id, 'deckId': 'deck-' + legacy, 'word': 'label',
                            'unit': 'Unit 01', 'lesson': 'Lesson 002', 'position': '7',
                            'previewUrl': card_url, 'definition': 'retained unchanged'}],
                 'decks': [{'id': 'deck-' + legacy, 'cardIds': [card_id], 'count': 1}],
                 'counts': {'cards': 1}}
        catalog_path = entry_path.parent / 'catalog.json'
        raw = json.dumps(value, ensure_ascii=False).encode()
        catalog_path.write_bytes(raw)
        entry_path.write_text('<div data-catalog-url="catalog.json"></div>')
        source = 'source-' + canonical
        target = {'book_id': canonical, 'source_id': source, 'note_id': 101,
                  'guid': 'guid-' + legacy, 'model_id': 301, 'native_id': 201,
                  'template_ordinal': template, 'unit_id': 401}
        self.registry['books'].append({'id': legacy, 'previewPath': '/' + entry,
                                       'unitLessonSeparator': separator})
        self.report['books'].append({'book_id': canonical, 'legacy_book': legacy,
            'source_id': source, 'cards': 1, 'native_cards': 1,
            'catalog': {'path': str(catalog_path), 'sha256': digest(raw), 'bytes': len(raw)}})
        self.report['bindings'].append({'evidence': 'exact-source-card-id',
            'legacy': {'book': legacy, 'card_id': card_id, 'deck_id': 'deck-' + legacy},
            'target': target})
        self.db.sources[canonical] = (source, 'complete', 'col-' + canonical)
        self.db.objects['col-' + canonical] = {'models': json.dumps({'301': {
            'tmpls': [{'ord': i} for i in range(template + 1)]}})}
        self.db.natives[canonical] = [(201, 101, target['guid'], 301, template, 401, card_id, 'word')]
        self.db.progress.add((legacy, card_id))
        self.db.settings.add(legacy)
        self.db.undo.add(legacy)
        return value, catalog_path

    def seal(self):
        artifact = {'sha256': 'b' * 64, 'bytes': 123}
        aliases = {'schema': 'study-progress-aliases.v1', 'approved_report': self.report,
                   'artifact': artifact, 'inactive_cards': [], 'inactive_books': []}
        core = {'schema': migration.IMPORT_SCHEMA, 'target_schema': self.db.schema,
                'storage': pg.DESCRIPTOR, 'source': {'sha256': 'c' * 64, 'bytes': 234,
                'snapshot': {'schema': 'fixture'}},
                'aliases_sha256': digest(catalog.canonical(aliases).encode()),
                'alias_artifact': artifact, 'catalog_revision': self.report['catalog_revision']}
        receipt = {**core, 'plan_sha256': digest(catalog.canonical(core).encode()),
                   'ready_to_switch': False}
        self.db.metadata = {migration.ALIASES_KEY: catalog.canonical(aliases),
                            migration.RECEIPT_KEY: catalog.canonical(receipt)}

    def load(self):
        with patch.object(catalog, 'get_json', side_effect=lambda db, key: self.db.objects[key]):
            return provider.load_books(self.db, document_root=self.root, registry=self.registry)

    def write_catalog(self, value, index=0):
        proof = self.report['books'][index]['catalog']
        raw = json.dumps(value, ensure_ascii=False).encode()
        Path(proof['path']).write_bytes(raw)
        proof.update(sha256=digest(raw), bytes=len(raw))

    def rejects(self):
        with self.assertRaises(provider.ServiceCatalogError):
            self.load()

    def test_registered_original_catalog_preserves_identity_and_display(self):
        original, _ = self.add_book()
        self.seal()
        books = self.load()
        card = dict(original['cards'][0])
        card['previewUrl'] = '/web-preview/fixture/cards/' + 'a' * 64 + '.html'
        card['meta'] = 'Unit 1 ➫ Lesson 2 ➫ 7'
        self.assertEqual(books, {'liu': {'id': 'liu', 'name': original['deckName'],
            'cards': [card], 'decks': original['decks'], 'previewPath': '/preview-library.html'}})
        self.assertTrue(all(sql.startswith('select ') for sql, _ in self.db.calls))

    def test_registry_versions_have_exact_fields_and_v2_cannot_omit_routes(self):
        self.add_book();self.seal()
        self.registry['books'][0]['projection']={}
        self.rejects()  # v1 must not silently accept an unverified projection.
        self.registry['schema']=provider.PROJECTION_REGISTRY_SCHEMA
        self.rejects()  # v2 requires a real formal mount and complete pin.
        del self.registry['books'][0]['projection']
        self.rejects()
        with self.assertRaises(provider.ServiceCatalogError):
            provider.load_books_and_routes(self.db,document_root=self.root,
                registry={'schema':provider.REGISTRY_SCHEMA,'books':[]},static_mounts=None)

    def test_three_legacy_books_are_byte_equal_to_the_actual_frozen_load_books(self):
        self.add_book()
        self.add_book('redbook', 'redbook', separator=' ',
                      entry='redbook-20261004/preview-library.html', card_id='b' * 64)
        self.add_book('redbook2027', 'redbook2027', separator=' ',
                      entry='redbook-2027-20261006/preview-library.html', card_id='c' * 64)
        self.seal()
        self.assertEqual(digest(LEGACY_LOAD_BOOKS_SOURCE.encode()), LEGACY_LOAD_BOOKS_SHA256)
        namespace = {'DOCUMENT_ROOT': self.root, 'Path': Path, 're': re, 'json': json,
                     'urljoin': urljoin, 'urlsplit': urlsplit, 'unquote': unquote}
        exec(compile(LEGACY_LOAD_BOOKS_SOURCE, '<frozen-original-load-books>', 'exec'), namespace)
        expected = namespace['load_books'](self.root)
        actual = self.load()
        self.assertEqual(json.dumps(actual, ensure_ascii=False).encode(),
                         json.dumps(expected, ensure_ascii=False).encode())
        self.report['books'].reverse()
        self.seal()
        self.assertEqual(list(self.load()), ['liu', 'redbook', 'redbook2027'])

    def test_subject_neutral_registry_and_nonzero_template_without_word(self):
        for index, (name, separator) in enumerate((('mathematics', ' / '), ('ielts-course', ' · '))):
            value, _ = self.add_book(name, 'canonical-' + name, separator=separator,
                entry=name + '/index.html', card_id=str(index + 1) * 64, template=1)
            del value['cards'][0]['word']
            value['cards'][0]['title'] = 'Equation' if index == 0 else 'Listening'
            self.write_catalog(value, index)
        self.seal()
        books = self.load()
        self.assertEqual(list(books), ['mathematics', 'ielts-course'])
        self.assertEqual(books['mathematics']['cards'][0]['meta'], 'Unit 1 / Lesson 2 ➫ 7')
        self.assertNotIn('word', books['mathematics']['cards'][0])
        self.assertEqual(books['ielts-course']['cards'][0]['title'], 'Listening')

    def test_requires_existing_repeatable_read_read_only_transaction(self):
        self.add_book()
        self.seal()
        for isolation, readonly, status in [('read committed', 'on', TransactionStatus.INTRANS),
                ('repeatable read', 'off', TransactionStatus.INTRANS),
                ('repeatable read', 'on', TransactionStatus.IDLE)]:
            with self.subTest(isolation=isolation, readonly=readonly, status=status):
                self.db.isolation, self.db.read_only, self.db.info.transaction_status = isolation, readonly, status
                self.rejects()

    def test_missing_or_modified_aliases_or_receipt_reject_before_catalog_reads(self):
        self.add_book()
        self.seal()
        original = deepcopy(self.db.metadata)
        for missing in [migration.ALIASES_KEY, migration.RECEIPT_KEY]:
            self.db.metadata = {key: value for key, value in original.items() if key != missing}
            self.rejects()
        for key in original:
            self.db.metadata = deepcopy(original)
            parsed = json.loads(self.db.metadata[key])
            parsed['schema'] = 'unregistered'
            self.db.metadata[key] = json.dumps(parsed)
            self.rejects()
        self.db.metadata = deepcopy(original)
        receipt = json.loads(self.db.metadata[migration.RECEIPT_KEY])
        receipt['source']['bytes'] += 1
        self.db.metadata[migration.RECEIPT_KEY] = json.dumps(receipt)
        self.rejects()

    def test_later_catalog_events_do_not_invalidate_historical_receipt_revision(self):
        self.add_book()
        self.seal()
        self.db.current_event_revision = 999
        self.assertIn('liu', self.load())
        self.assertFalse(any('events' in query for query, _ in self.db.calls))

    def test_registry_must_exactly_cover_approved_books_without_duplicates(self):
        self.add_book()
        self.seal()
        original = deepcopy(self.registry)
        for rows in [[], original['books'] * 2,
                     [{**original['books'][0], 'id': 'unregistered'}]]:
            self.registry['books'] = rows
            self.rejects()

    def test_approved_catalog_sha_and_byte_count_are_mandatory(self):
        self.add_book()
        self.seal()
        path = Path(self.report['books'][0]['catalog']['path'])
        path.write_bytes(path.read_bytes() + b' ')
        self.rejects()
        self.report['books'][0]['catalog']['bytes'] = True
        self.seal()
        self.rejects()

    def test_entry_card_and_catalog_escape_paths_are_rejected(self):
        value, _ = self.add_book()
        self.seal()
        registration = deepcopy(self.registry['books'][0])
        for url in ['/../preview-library.html', '/%2e%2e/preview-library.html',
                    '//foreign.example/preview-library.html', '/preview-library.html?x=1']:
            self.registry['books'][0]['previewPath'] = url
            self.rejects()
        self.registry['books'][0] = registration
        for url in ['../../../private.html', 'https://foreign.example/cards/a.html',
                    '/%2e%2e/cards/a.html', 'web-preview/fixture/cards/a.html#fragment']:
            value['cards'][0]['previewUrl'] = url
            self.write_catalog(value)
            self.seal()
            self.rejects()
        outside = self.root.parent / 'outside.json'
        outside.write_text('{}')
        self.report['books'][0]['catalog'].update(path=str(outside), sha256=digest(b'{}'), bytes=2)
        self.seal()
        self.rejects()

    def test_symlink_to_private_card_is_rejected(self):
        value, _ = self.add_book()
        self.seal()
        card = self.root / value['cards'][0]['previewUrl']
        private = self.root.parent / 'private.html'
        private.write_text('PRIVATE')
        card.unlink()
        card.symlink_to(private)
        self.rejects()

    def test_card_cannot_escape_its_registered_book_into_a_sibling(self):
        value, _ = self.add_book(entry='registered/preview-library.html')
        sibling = self.root / 'sibling/cards/other.html'
        sibling.parent.mkdir(parents=True)
        sibling.write_text('must not be borrowed by this catalog')
        value['cards'][0]['previewUrl'] = '../sibling/cards/other.html'
        self.write_catalog(value)
        self.seal()
        self.rejects()

    def test_complete_deck_membership_and_counts_are_checked(self):
        value, _ = self.add_book()
        original = deepcopy(value)
        mutations = [lambda v: v['decks'][0]['cardIds'].append('missing'),
                     lambda v: v['decks'][0]['cardIds'].append('a' * 64),
                     lambda v: v['cards'].append(deepcopy(v['cards'][0])),
                     lambda v: v['cards'][0].update(deckId='unregistered'),
                     lambda v: v['counts'].update(cards=2)]
        for mutate in mutations:
            value = deepcopy(original)
            mutate(value)
            self.write_catalog(value)
            self.seal()
            self.rejects()

    def test_every_current_native_identity_component_is_checked(self):
        self.add_book(template=1)
        self.seal()
        original = self.db.natives['liuxiaoyan2027'][0]
        for position, replacement in [(0, 202), (1, 102), (2, 'different-guid'), (3, 302),
                                      (4, 0), (5, 402), (6, 'b' * 64)]:
            with self.subTest(position=position):
                row = list(original)
                row[position] = replacement
                self.db.natives['liuxiaoyan2027'] = [tuple(row)]
                self.rejects()
        self.db.natives['liuxiaoyan2027'] = [original]
        source = self.db.sources['liuxiaoyan2027']
        self.db.sources['liuxiaoyan2027'] = (source[0], 'incomplete', source[2])
        self.rejects()
        self.db.sources['liuxiaoyan2027'] = source
        self.db.objects[source[2]]['models'] = json.dumps({'301': {'tmpls': [{'ord': 0}]}})
        self.rejects()

    def test_explicit_supplements_are_validated_but_never_seeded_or_returned(self):
        self.add_book()
        target = self.report['bindings'][0]['target']
        for index in range(4):
            native, note, source_id = 300 + index, 400 + index, 'supplement-' + str(index)
            new = {**target, 'native_id': native, 'note_id': note, 'guid': source_id}
            self.db.natives['liuxiaoyan2027'].append((native, note, source_id, 301, 0, 401,
                                                   source_id, 'supplemental'))
            self.report['excluded_from_legacy_learning_catalog'].append(
                {**new, 'id': source_id, 'word': source_id, 'kind': 'supplemental', 'reason': 'Explicitly excluded'})
        self.report['books'][0]['native_cards'] = 5
        self.seal()
        before = deepcopy(self.db.progress)
        self.assertEqual(len(self.load()['liu']['cards']), 1)
        self.assertEqual(self.db.progress, before)
        self.report['excluded_from_legacy_learning_catalog'].pop()
        self.seal()
        self.rejects()

    def test_guide_exception_requires_its_exact_approved_proof(self):
        self.add_book()
        target = self.report['bindings'][0]['target']
        self.report['bindings'][0]['evidence'] = 'exact-guide-proof'
        self.report['guide_proofs']['liu'] = {
            'id': 'a' * 64, **{key: target[key] for key in ('guid', 'native_id', 'note_id', 'template_ordinal')},
            'evidence': {'kind': 'every-original-field-exact-in-legacy-page-and-native-GUID'}}
        self.db.natives['liuxiaoyan2027'][0] = (201, 101, target['guid'], 301, 0, 401, None, 'guide')
        self.seal()
        self.assertEqual(len(self.load()['liu']['cards']), 1)
        self.report['guide_proofs']['liu']['guid'] = 'not-the-guid'
        self.seal()
        self.rejects()

    def test_missing_migrated_rows_never_trigger_initialization(self):
        self.add_book()
        self.seal()
        for name in ['progress', 'settings', 'undo']:
            with self.subTest(table=name):
                before = getattr(self.db, name)
                setattr(self.db, name, set())
                self.rejects()
                setattr(self.db, name, before)
        self.assertTrue(all(query.startswith('select ') for query, _ in self.db.calls))

    def test_catalog_replacement_after_read_is_rejected_even_with_identical_bytes(self):
        _, path = self.add_book()
        self.seal()
        original_open = provider.Resource.open
        changed = []
        class ChangingReader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *_): self.stream.close()
            def fileno(self): return self.stream.fileno()
            def read(self, amount):
                raw = self.stream.read(amount)
                replacement = path.with_suffix('.new')
                replacement.write_bytes(raw)
                os.replace(replacement, path)
                changed.append(True)
                return raw
        def opening(resource):
            stream, info = original_open(resource)
            return (ChangingReader(stream), info) if resource.path == path.resolve() else (stream, info)
        with patch.object(provider.Resource, 'open', opening):
            self.rejects()
        self.assertEqual(changed, [True])

    def test_card_html_is_not_read_and_input_registration_is_not_modified(self):
        self.add_book()
        self.seal()
        before = deepcopy(self.registry)
        original_open = provider.Resource.open
        class NoCardRead:
            def __init__(self, stream): self.stream = stream
            def close(self): self.stream.close()
            def read(self, *_): raise AssertionError('large card HTML was read')
        def opening(resource):
            stream, info = original_open(resource)
            return (NoCardRead(stream), info) if resource.path.parent.name == 'cards' else (stream, info)
        with patch.object(provider.Resource, 'open', opening):
            self.assertIn('liu', self.load())
        self.assertEqual(self.registry, before)


# Exact current legacy function, frozen before extracting the runtime provider.
LEGACY_LOAD_BOOKS_SOURCE = 'def load_books(document_root: Path = DOCUMENT_ROOT) -> dict:\n    """Read the live entry catalogs; never change cards or the APKGs."""\n    books = {}\n    for book_id, relative in [(\'liu\', \'preview-library.html\'),\n                              (\'redbook\', \'redbook-20261004/preview-library.html\'),\n                              (\'redbook2027\', \'redbook-2027-20261006/preview-library.html\')]:\n        entry = document_root / relative\n        match = re.search(r\'data-catalog-url="([^"]+)"\', entry.read_text())\n        if not match:\n            raise ValueError(f\'Missing catalog in {relative}\')\n        catalog_path = (entry.parent / unquote(match[1])).resolve()\n        if not catalog_path.is_relative_to(document_root.resolve()):\n            raise ValueError(\'Catalog must remain within the document root\')\n        catalog = json.loads(catalog_path.read_text())\n        cards = []\n        for source in catalog[\'cards\']:\n            card = dict(source)\n            href = urljoin(\'/\' + relative, card[\'previewUrl\'])\n            parsed = urlsplit(href)\n            if parsed.scheme or parsed.netloc or not re.fullmatch(\n                    r\'/(?:[a-zA-Z0-9_-]+/(?:candidates/[a-f0-9]{64}/)?)?web-preview/[a-z0-9_-]+/cards/[a-f0-9]+\\.html\', parsed.path):\n                raise ValueError(\'Unexpected generated card path\')\n            path = (document_root / unquote(parsed.path.lstrip(\'/\'))).resolve()\n            if not path.is_relative_to(document_root.resolve()) or not path.is_file():\n                raise ValueError(\'Card is unavailable\')\n            card[\'previewUrl\'] = parsed.path\n            unit = re.sub(r\'\\b(Unit|Lesson)\\s+0*(\\d+)\', r\'\\1 \\2\', card[\'unit\'])\n            lesson = re.sub(r\'\\b(Unit|Lesson)\\s+0*(\\d+)\', r\'\\1 \\2\', card[\'lesson\'])\n            card[\'meta\'] = (unit + \' \' + lesson if book_id.startswith(\'redbook\')\n                            else unit + \' ➫ \' + lesson) + \' ➫ \' + card[\'position\']\n            cards.append(card)\n        if len(cards) != catalog[\'counts\'][\'cards\'] or len({c[\'id\'] for c in cards}) != len(cards):\n            raise ValueError(\'Card counts or identities do not reconcile\')\n        books[book_id] = {\'id\': book_id, \'name\': catalog[\'deckName\'], \'cards\': cards,\n                          \'decks\': catalog[\'decks\'], \'previewPath\': \'/\' + relative}\n    return books'
LEGACY_LOAD_BOOKS_SHA256 = '056a80ad7c75bced78a772b3eab3041cc02fc6ec757dfb548da70ae7edd825c8'

if __name__ == '__main__':
    unittest.main()
