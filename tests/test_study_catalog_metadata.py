"""Catalog-only projection contracts; SELECT fixtures and owned tiny web output."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_catalog_export as export


class Rows:
    def __init__(self, values):
        self.values = list(values)

    def __iter__(self):
        return iter(self.values)

    def fetchone(self):
        return self.values[0] if self.values else None

    def fetchall(self):
        return self.values


class CatalogMetadataTests(unittest.TestCase):
    def setUp(self):
        self.book = {'id': 'opaque-book', 'title': '任意资料',
                     'scope': {'subject': '数学', 'exam': '考研'}, 'revision': 14,
                     'runtime': {'sources': {}, 'generated': {}}}
        model = {'id': 17, 'sortf': 0, 'css': '', 'tmpls': [
            {'name': '正向', 'qfmt': '', 'afmt': ''}, {'name': '反向', 'qfmt': '', 'afmt': ''}]}
        self.notes = {
            9: {'id': 'source-word', 'guid': 'word-guid', 'ordinal': 30, 'kind': 'guide',
                'field_names': ['Word', 'Title'], 'fields': ['<b>A&amp;B</b>', 'unused title'],
                'model': copy.deepcopy(model)},
            3: {'id': 'source-title', 'guid': 'title-guid', 'ordinal': 10, 'kind': 'item',
                'field_names': ['Title'], 'fields': ['积分 &lt;x&gt;'], 'model': copy.deepcopy(model)},
            5: {'id': 'source-sort', 'guid': 'sort-guid', 'ordinal': 20, 'kind': 'item',
                'field_names': ['Formula', 'Definition'], 'fields': ['unused', '&sum; &amp; Δ'],
                'model': {**copy.deepcopy(model), 'sortf': 1}}}
        self.natives = {9: [(901, 0, '原书::说明')],
                        3: [(402, 1, '原书::单元乙'), (401, 0, '原书::单元乙')],
                        5: [(501, 1, '原书::单元甲')]}
        self.calls = []
        owner = self

        class Database:
            def execute(self, query, args):
                owner.calls.append((query, args))
                if query == 'select note_id from notes where book_id=%s order by ordinal':
                    return Rows((nid,) for nid in sorted(owner.notes, key=lambda nid: owner.notes[nid]['ordinal']))
                if query == 'select n.native_id,n.ordinal,u.name from native_cards n join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s and n.note_id=%s order by n.ordinal':
                    return Rows(sorted(owner.natives[args[1]], key=lambda row: row[1]))
                if query == 'select value from metadata where key=%s':
                    return Rows([])
                if query == 'select name,object_id from resource_aliases where book_id=%s order by name':
                    return Rows([])
                raise AssertionError('unexpected catalog read/write: ' + query)

        self.db = Database()

    def projected_notes(self):
        return patch.object(export, 'project_note', side_effect=lambda db, book, nid: copy.deepcopy(self.notes[nid]))

    def expected(self):
        def row(identity, guid, native, ordinal, position, word, label, template, unit, multi):
            return {'id': identity, 'guid': guid, 'word': word, 'label': label,
                    'template': template, 'template_ordinal': ordinal, 'unit': unit,
                    'url': 'cards/' + catalog.identity('page', self.book['id'], guid, *((ordinal,) if multi else ())) + '.html',
                    'ordinal': position, 'native_id': native}
        return {'schema': 'shared-book-web.v1', 'book_id': self.book['id'], 'title': self.book['title'],
                'scope': self.book['scope'], 'catalog_revision': 14, 'cards': [
                    row('401', 'title-guid', 401, 0, 10, '积分 <x>', '积分 <x> · 正向', '正向', '原书::单元乙', True),
                    row('402', 'title-guid', 402, 1, 10, '积分 <x>', '积分 <x> · 反向', '反向', '原书::单元乙', True),
                    row('source-sort', 'sort-guid', 501, 1, 20, '∑ & Δ', '∑ & Δ', '反向', '原书::单元甲', False),
                    row('source-word', 'word-guid', 901, 0, 30, '<b>A&B</b>', '<b>A&B</b>', '正向', '原书::说明', False)]}

    def render_tiny_web(self, folder):
        with ExitStack() as stack:
            stack.enter_context(self.projected_notes())
            stack.enter_context(patch.object(export, '_web_model', side_effect=lambda model, media, cache: (model, 'fixture.css')))
            stack.enter_context(patch.object(export, '_card_page', side_effect=lambda note, base, **kw: str(kw['template_ordinal'])))
            stack.enter_context(patch.object(export.study_catalog_math, 'required', return_value=False))
            stack.enter_context(patch('anki_pipeline.study_catalog_web_materialize.prepare_library', return_value={'config': {}, 'report': {}}))
            stack.enter_context(patch.object(export.study_catalog_web, 'audited_shared_config', return_value={}))
            stack.enter_context(patch.object(export.study_catalog_web, 'write_library', return_value={}))
            export._web(self.db, self.book, folder, None)
        return json.loads((folder / 'web/catalog.json').read_bytes())

    def test_existing_full_web_catalog_preserves_multitemplate_order_and_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.render_tiny_web(Path(folder)), self.expected())

    def test_catalog_only_projection_matches_full_web_without_media_or_renderer(self):
        before = copy.deepcopy((self.book, self.notes, self.natives))
        with self.projected_notes(), patch.object(export, '_card_page', side_effect=AssertionError('rendered card')), \
                patch.object(export, '_web_model', side_effect=AssertionError('created model assets')), \
                patch.object(export.c, 'get_object', side_effect=AssertionError('read media')), \
                patch.object(export.c, 'write_object', side_effect=AssertionError('wrote media')), \
                patch.object(export.study_catalog_math, 'write_assets', side_effect=AssertionError('wrote math')):
            projected = export.project_web_catalog(self.db, self.book)
        self.assertEqual(projected, self.expected())
        self.assertTrue(all(query.startswith('select ') and 'resource_aliases' not in query and 'metadata' not in query
                            for query, _ in self.calls))
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(catalog.canonical(projected), catalog.canonical(self.render_tiny_web(Path(folder))))
        self.assertEqual((self.book, self.notes, self.natives), before)

    def test_missing_template_rejected_and_empty_catalog_retains_current_scope(self):
        self.natives[3] = [(401, 2, '原书::单元乙')]
        with self.projected_notes(), self.assertRaisesRegex(ValueError, 'missing template'):
            export.project_web_catalog(self.db, self.book)
        self.notes.clear()
        with self.projected_notes():
            projected = export.project_web_catalog(self.db, self.book)
        self.assertEqual(projected, {**self.expected(), 'cards': []})


if __name__ == '__main__':
    unittest.main()
