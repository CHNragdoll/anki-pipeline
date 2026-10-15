"""Runtime resource revisions must never become authored semantic content."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
import uuid
import zipfile

import genanki
import psycopg
from psycopg import sql

from anki_pipeline import sense_frequency as sf, study_catalog as c
from anki_pipeline import study_catalog_presentation as presentation
from anki_pipeline import study_catalog_revision as revision
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_content import amend_sentence
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_normalize import import_analysis
from anki_pipeline.study_catalog_query import frequency_report
from tests.test_sense_frequency import aligned_record, reseal
from tests import test_study_catalog_content as content_tests
from tests import test_study_catalog_revision as revision_tests


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires isolated PostgreSQL test connection')
class RuntimeSemanticSequenceTests(unittest.TestCase):
    request = revision_tests.SharedFactRevisionTests.request
    scope = content_tests.SharedContentRevisionTests.scope
    sentence_request = content_tests.SharedContentRevisionTests.sentence_request

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_' + uuid.uuid4().hex)
        self.before = {}
        self.books = ('one', 'two', 'future')
        self.asset_names = {'js': '_review.js', 'css': '_review.css'}
        self.resource_markup = '<link rel="stylesheet" href="_review.css"><script src="_review.js"></script>'
        for index, book in enumerate(('one', 'two')):
            raw = aligned_record()
            raw.update(book_id=book, card_id=book + '-novel')
            record = sf.prepare_record(reseal(raw))
            row = record['occurrences'][0]
            definition = self.resource_markup + sf.render_report(sf.report_from_record(record))
            examples = (self.resource_markup + '<li class="example-card"><div class="example-heading">'
                '<span class="index-tag">1</span><span class="example-text">' + row['english'] + '</span></div>'
                '<span class="example-translation"><span class="translate-tag">翻译</span> '
                + row['translation'] + '</span><span class="example-source">完整原来源</span></li>')
            model = genanki.Model(7381, 'Runtime semantic sequence',
                fields=[{'name': name} for name in ('Word', 'Definition', 'Examples')],
                templates=[{'name': 'Card', 'qfmt': self.resource_markup + '{{Word}}',
                            'afmt': '{{Definition}} {{Examples}}'}])
            deck = genanki.Deck(7382 + index, book)
            deck.add_note(genanki.Note(model=model, fields=['novel', definition, examples],
                                      guid=genanki.guid_for('runtime-semantics', book)))
            files = []
            for kind, name in self.asset_names.items():
                path = self.root / name
                path.write_text(self.asset_text(kind, 'A'))
                files.append(str(path))
            path = self.root / (book + '.apkg')
            package = genanki.Package(deck)
            package.media_files = files
            package.write_to_file(str(path))
            import_package(self.target, path, book_id=book, title=book, edition=2027)
            path.unlink()
            with c.connect(self.target) as db, c.transaction(db):
                import_analysis(db, record)
                db.execute('update notes set source_card_id=%s where book_id=%s', (record['card_id'], book))
            self.before[book] = record
        presentation.install(self.target)
        create_book(self.target, {'schema': 'study-book-map.v1', 'id': 'future', 'title': 'Mapped sequence',
            'edition': 2028, 'units': [{'name': 'Unit 01', 'items': [{'word': 'novel', 'from_book': 'one'}]}]})
        with c.connect(self.target, readonly=True) as db:
            self.runtime_components = presentation.registry(db)['books']['one']['resources']

    def tearDown(self):
        with psycopg.connect(self.target.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    @staticmethod
    def asset_text(kind, version):
        return ('window.reviewRuntime="' + version + '";' if kind == 'js'
                else '.review-evidence{--version:"' + version + '";}')

    def change_runtime(self, previous, version):
        for kind, name in self.asset_names.items():
            c.edit_component(self.target, self.runtime_components[name], self.asset_text(kind, version),
                expected=self.asset_text(kind, previous), reason='组合修订运行时验证', backups=self.root/'backups')

    def refresh_records(self):
        with c.connect(self.target, readonly=True) as db:
            self.before = {book: c.get_json(db, rid) for book, rid in db.execute(
                'select book_id,record_id from analyses order by book_id')}

    def add_late_mapping(self):
        create_book(self.target, {'schema': 'study-book-map.v1', 'id': 'late', 'title': 'Mapped during runtime B',
            'edition': 2028, 'units': [{'name': 'Unit 01', 'items': [{'word': 'novel', 'from_book': 'one'}]}]})
        self.books += ('late',)

    def assert_authored_projections(self):
        with c.connect(self.target, readonly=True) as db:
            for entry in revision.registry(db).values():
                for key in entry['fields'].values():
                    self.assertNotIn('_study_runtime_', c.get_object(db, key).decode())
            for book in self.books:
                nid = db.execute('select note_id from notes where book_id=%s', (book,)).fetchone()[0]
                note = project_note(db, project_book(db, book), nid, apply_runtime=False)
                for field in note['fields']:
                    self.assertNotIn('_study_runtime_', field)
                self.assertIn('_review.js', note['fields'][note['field_names'].index('Definition')])

    def assert_resources(self, label, version):
        artifacts = {}
        pattern = re.compile(r'_review\.(?:js|css)|_study_runtime_[0-9a-f]+\.(?:js|css)')
        for book in self.books:
            with c.connect(self.target, readonly=True) as db:
                projected = project_book(db, book)
                current = {kind: projected['runtime']['aliases'].get(name, name)
                           for kind, name in self.asset_names.items()}
            apkg = self.root / (book + '-' + label + '.apkg')
            export_book(self.target, book, apkg)
            with zipfile.ZipFile(apkg) as archive:
                media = {name: archive.read(member) for member, name in json.loads(archive.read('media')).items()}
                native = sqlite3.connect(':memory:')
                try:
                    native.deserialize(archive.read('collection.anki2'))
                    fields = native.execute('select flds from notes').fetchone()[0]
                    models = native.execute('select models from col').fetchone()[0]
                    references = set(pattern.findall(fields + models))
                finally:
                    native.close()
            self.assertEqual(references, set(current.values()), (book, label))
            for kind, name in current.items():
                self.assertEqual(media[name], self.asset_text(kind, version).encode(), (book, label, name))
            folder = self.root / (book + '-' + label + '-web')
            export_book(self.target, book, folder, format='web')
            card = json.loads((folder/'catalog.json').read_text())['cards'][0]
            page = (folder/card['url']).read_text()
            self.assertEqual(set(pattern.findall(page)), set(current.values()), (book, label))
            for kind, name in current.items():
                self.assertEqual((folder/'media'/name).read_bytes(), self.asset_text(kind, version).encode())
            artifacts[book] = apkg
        return artifacts

    def test_runtime_decision_source_runtime_revert_uses_only_current_media(self):
        self.assert_resources('baseline', 'A')
        self.change_runtime('A', 'B')
        self.assert_authored_projections()
        revision.amend_decision(self.target, **self.request())
        self.assert_authored_projections()
        self.refresh_records()
        amend_sentence(self.target, **self.sentence_request())
        self.add_late_mapping()
        self.assert_authored_projections()
        self.assert_resources('semantic-b', 'B')
        self.change_runtime('B', 'C')
        self.assert_resources('semantic-c', 'C')
        self.change_runtime('C', 'A')
        self.assert_resources('semantic-a', 'A')
        self.assertEqual(frequency_report(self.target, word='novel')['physical_occurrences'], 2)


if __name__ == '__main__':
    unittest.main()
