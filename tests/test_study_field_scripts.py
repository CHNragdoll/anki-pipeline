"""Shared inline field transport; no PG, SDK, GUI or real package generation."""
import copy
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_export as export


ROOT = Path(__file__).resolve().parents[1]


def model():
    return {'id': 12, 'mod': 20, 'flds': [{'name': 'Word'}, {'name': 'Definition'}],
            'css': '.card{color:black}', 'tmpls': [{'qfmt': '{{Word}}',
            'afmt': '{{FrontSide}}<div>{{Definition}}</div><script>window.AnkiSlimApkgHydrate();</script>'}]}


def registered(book):
    from anki_pipeline import study_field_scripts as f
    book['runtime_revision'] = {'revision': 2, 'floor': 100,
        'field_script_transport': {'schema': 'study-field-script-registration.v1', 'sources': f.source_pins(),
            'previous_runtime': {'revision': 1, 'floor': 90},
            'models': {mid: {'before': value['mod'] - 1, 'after': value['mod']} for mid, value in book['models'].items()}}}
    return book


class FieldScriptTests(unittest.TestCase):
    def test_default_APKG_and_web_use_same_template_overlay(self):
        for fmt in ('apkg', 'web'):
            with self.subTest(format=fmt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stage = root / 'stage'
                stage.mkdir()
                source = model()
                original = copy.deepcopy(source)
                original['mod'] = 10
                book = registered({'models': {'12': source}, 'col': {'models': json.dumps({'12': original})},
                        'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}, 'id': 'opaque-book'})
                seen = []
                def apkg(db, projected, folder, name, callback, **options):
                    seen.append(projected)
                    (folder / name).write_bytes(b'tiny synthetic output')
                    return {'schema': 'tiny-test'}
                def web(db, projected, folder, callback):
                    seen.append(projected)
                    (folder / 'web').mkdir()
                    return {'schema': 'tiny-test'}
                with patch.object(export, '_apkg', side_effect=apkg), patch.object(export, '_web', side_effect=web):
                    # A registered policy is the default path, with no flag.
                    export._export_projected(None, book, root / 'result', format=fmt, staging=stage)
                template = seen[0]['models']['12']['tmpls'][0]['afmt']
                self.assertIn('data-study-field-restore', template)
                self.assertLess(template.index('data-study-field-restore'), template.index('window.AnkiSlimApkgHydrate();'))
                self.assertEqual(book['models']['12'], source)
                if fmt == 'web':
                    report = json.loads((root / 'result' / 'COMPLETE.json').read_text())
                    self.assertEqual(report['field_script_transport']['schema'], 'study-field-script.v1')

    def source(self):
        return ('<article><p>原句 😀 &amp; quote</p>'
                '<script class="anki-final-reviewed-data" type="application/json" data-as-src="_as_one.js">'
                '{"quoted":"\\\" & <\\/script>","unicode":"词😀"}</script>'
                '<details><div><script type="application/json" class="as-manifest"></script></div></details></article>')

    def test_exact_inverse_empty_carriers_and_Unicode_payload(self):
        from anki_pipeline import study_field_scripts as f
        from lxml import html
        raw = self.source()
        protected = f.protect_field(raw)
        before, after = html.fragment_fromstring(raw), html.fragment_fromstring(protected)
        carriers = after.xpath('.//span[@data-study-script-source]')
        self.assertEqual(len(carriers), 2)
        for node in carriers:
            self.assertEqual(node.text_content(), '')
            self.assertEqual(node.getprevious().tag, 'script')
            payload = base64.b64decode(node.get('data-study-script-source'), validate=True)
            self.assertEqual(hashlib.sha256(payload).hexdigest(), node.get('data-study-script-sha256'))
            node.getparent().remove(node)
        self.assertEqual(html.tostring(before), html.tostring(after))
        import re
        self.assertEqual(re.sub(r'<span hidden=""[^>]*data-study-script-source="[A-Za-z0-9+/=]+"></span>', '', protected), raw)

    def test_unsupported_ambiguous_parent_and_attributes_rejected(self):
        from anki_pipeline import study_field_scripts as f
        script = '<script class="as-manifest" type="application/json">{}</script>'
        for raw in ('<table>' + script + '</table>', '<svg><foreignObject><div>' + script + '</div></foreignObject></svg>',
                    script.replace('class="as-manifest"', 'class="as-manifest" class="as-manifest"'),
                    script.replace('class="as-manifest"', 'class="as-manifest anki-final-reviewed-data"'),
                    script.replace('type="application/json"', 'src="unknown.js" type="application/json"')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                f.protect_field(raw)

    def test_unregistered_model_mod_and_unsupported_template_boundary_rejected(self):
        from anki_pipeline import study_field_scripts as f
        m = model()
        book = registered({'models': {'12': m}, 'col': {'models': json.dumps({'12': m})},
                'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}})
        with self.assertRaisesRegex(ValueError, 'committed'):
            f.project_inline_book(book)
        m['tmpls'][0]['afmt'] = '{{Definition}}'
        with self.assertRaisesRegex(ValueError, 'boundary'):
            f.protect_fields(m, ['Definition'], [self.source()])

    def test_no_hydrate_projection_does_not_enable_field_protection(self):
        from anki_pipeline import study_field_scripts as f
        from anki_pipeline.etymology import _PARENT_FRAME_BRIDGE
        m = model()
        m['tmpls'][0]['afmt'] = '<main>{{Definition}}</main>'
        book = {'id': 'opaque', 'models': {'12': m}, 'col': {'models': json.dumps({'12': m})},
                'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}, 'content_mods': {},
                'runtime_revision': None}
        source = '<section><script data-cigen-frame-bridge="v1">' + _PARENT_FRAME_BRIDGE + '</script></section>'
        class DB:
            def execute(self, *args): return self
            def fetchone(self): return ('guid', 'word-id', 'word', 0, 12, 'payload', 'source-id')
        for fmt in ('apkg', 'web'):
            with self.subTest(format=fmt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); stage = root / 'stage'; stage.mkdir()
                def output(db, projected, folder, *args, **options):
                    self.assertIs(projected['field_script_transport'], False)
                    self.assertEqual(projected['models'], book['models'])
                    self.assertEqual(projected['runtime'], book['runtime'])
                    self.assertEqual(export.project_note(db, projected, 1)['fields'], ['word', source])
                    if fmt == 'apkg': (folder / args[0]).write_bytes(b'tiny')
                    else: (folder / 'web').mkdir()
                    return {}
                with patch.object(export, '_apkg', side_effect=output), patch.object(export, '_web', side_effect=output), \
                     patch.object(export.c, 'note_fields', return_value=['word', source]), \
                     patch.object(export.c, 'get_json', return_value={'mod': 1}), \
                     patch('anki_pipeline.study_catalog_revision.project_fields', side_effect=lambda db,b,s,n,v:v), \
                     patch('anki_pipeline.study_catalog_revision.project_display_fields', side_effect=lambda db,b,s,n,v:v), \
                     patch.object(f, 'protect_fields', side_effect=AssertionError('no restoration boundary')):
                    report = export._export_projected(DB(), book, root / 'result', format=fmt,
                                                     staging=stage, field_script_protection=True)
                self.assertIs(report['field_script_transport'], False)
        self.assertNotIn('field_script_transport', book)
        # Losing a previously registered boundary still fails closed.
        with self.assertRaisesRegex(ValueError, 'exact affected models'):
            f.project_inline_book(registered(copy.deepcopy(book)))

    def test_noop_normalization_requires_unchanged_unregistered_overlay(self):
        for change in ('models', 'runtime', 'registration'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                book = {'models': {'12': model()}, 'runtime': {'generated': {}}, 'runtime_revision': None}
                overlay = copy.deepcopy(book)
                overlay['field_script_transport'] = True
                if change == 'models': overlay['models']['12']['css'] += ' '
                elif change == 'runtime': overlay['runtime']['generated']['new.js'] = b'new'
                else: book['runtime_revision'] = {'field_script_transport': {}}
                root = Path(temporary); stage = root / 'stage'; stage.mkdir()
                def web(db, projected, folder, callback):
                    self.assertIs(projected['field_script_transport'], True)
                    (folder / 'web').mkdir()
                    return {}
                with patch('anki_pipeline.study_field_scripts.project_inline_book', return_value=overlay), \
                     patch.object(export, '_web', side_effect=web):
                    export._export_projected(None, book, root / 'result', format='web',
                                             staging=stage, field_script_protection=True)

    def test_project_note_applies_after_display_and_skips_semantic_writer(self):
        from anki_pipeline import study_field_scripts as f
        m = model()
        original = copy.deepcopy(m)
        original['mod'] = 10
        book = f.project_inline_book(registered({'id': 'generic', 'models': {'12': m}, 'col': {'models': json.dumps({'12': original})},
            'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}, 'content_mods': {}}))
        class DB:
            def execute(self, *args): return self
            def fetchone(self): return ('guid', 'word-id', 'vocab', 0, 12, 'payload', 'source-id')
        with patch.object(export.c, 'note_fields', return_value=['word', self.source()]), \
             patch.object(export.c, 'get_json', return_value={'mod': 1}), \
             patch('anki_pipeline.study_catalog_revision.project_fields', side_effect=lambda db,b,s,n,v:v), \
             patch('anki_pipeline.study_catalog_revision.project_display_fields', side_effect=lambda db,b,s,n,v:v):
            final = export.project_note(DB(), book, 1)
            raw = export.project_note(DB(), book, 1, apply_runtime=False)
        self.assertIn('data-study-script-source', final['fields'][1])
        self.assertEqual(raw['fields'][1], self.source())

    def test_real_JS_editor_deletion_restore_tamper_repeat_and_face_replacement(self):
        from anki_pipeline import study_field_scripts as f
        m = model(); original = copy.deepcopy(m); original['mod'] = 10
        book = f.project_inline_book(registered({'models': {'12': m}, 'col': {'models': json.dumps({'12': original})},
            'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}}))
        long_source = self.source().replace('词😀', '词😀' * 20000)
        projected = {'field_names': ['Word', 'Definition'], 'fields': ['word', f.protect_field(long_source)], 'model': book['models']['12']}
        same = '<div><script class="as-manifest" type="application/json">{}</script></div>'
        same_model = copy.deepcopy(book['models']['12'])
        same_model['tmpls'][0]['afmt'] = '{{First}}{{Second}}<script>window.AnkiSlimApkgHydrate();</script>'
        identical_fields = f.protect_fields(same_model, ['First', 'Second'], [same, same])
        payload = {'html': projected['fields'][1], 'runtime': f.RUNTIME_PATH.read_text(),
                   'template': export._render_note(projected)[1], 'identical_fields': identical_fields}
        result = subprocess.run(['node', str(ROOT / 'tests/fixtures/field-script-restore.cjs')],
                                input=json.dumps(payload), text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_exposes_opt_in_without_changing_normal_default(self):
        from anki_pipeline.study_catalog_cli import parser
        base = ['export', '--book', 'opaque', '--format', 'apkg', '--output', 'new.apkg']
        self.assertFalse(parser().parse_args(base).protect_field_scripts)
        self.assertTrue(parser().parse_args(base + ['--protect-field-scripts']).protect_field_scripts)

    def test_explicit_mode_and_registration_are_required_old_paths_stay_unchanged(self):
        from anki_pipeline import study_field_scripts as f
        m = model()
        original = copy.deepcopy(m)
        original['mod'] = 10
        book = {'id': 'opaque', 'models': {'12': m}, 'col': {'models': json.dumps({'12': original})},
                'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}}
        with self.assertRaisesRegex(ValueError, 'explicitly registered'):
            f.project_inline_book(book)
        for change in ('source', 'same-mod', 'runtime'):
            revised = registered(copy.deepcopy(book))
            marker = revised['runtime_revision']['field_script_transport']
            if change == 'source': marker['sources']['runtime_sha256'] = '0' * 64
            elif change == 'same-mod': marker['models']['12']['before'] = 20
            else: revised['runtime_revision']['revision'] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                f.project_inline_book(revised)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / 'stage'; stage.mkdir()
            def old(db, projected, folder, name, callback, **options):
                self.assertEqual(projected, book)
                (folder / name).write_bytes(b'tiny')
                return {}
            with patch.object(export, '_apkg', side_effect=old):
                export._export_projected(None, book, root / 'old', format='apkg', staging=stage)
        with self.assertRaisesRegex(ValueError, 'cannot wrap compiled'):
            export._export_projected(None, book, Path('unused'), format='apkg', compiled_delivery={}, field_script_protection=True)

    def test_registration_plan_uses_existing_writers_without_DB_writes_and_CAS(self):
        from anki_pipeline import study_field_scripts as f
        from anki_pipeline import study_catalog_anki as native
        from anki_pipeline import study_catalog as c
        m = model()
        original = copy.deepcopy(m); original['mod'] = 10
        book = {'models': {'12': m}}
        class Rows:
            def __init__(self, values): self.values = values
            def fetchone(self): return self.values[0] if self.values else None
            def __iter__(self): return iter(self.values)
        class DB:
            def __init__(self):
                self.revision = 14
                self.metadata = {native.MODEL_MODS: json.dumps({c.identity('opaque', '12'): 20}),
                                 native.RUNTIME_REVISIONS: json.dumps({'opaque': {'revision': 1, 'floor': 100}})}
                self.queries = []
            def execute(self, query, params=()):
                self.queries.append(query)
                self_test.assertTrue(query.lower().startswith('select '), 'plan attempted real DB write')
                if 'max(id)' in query: return Rows([(self.revision,)])
                if 'select key,value' in query: return Rows(list(self.metadata.items()))
                if 'select value' in query: return Rows([(self.metadata[params[0]],)] if params[0] in self.metadata else [])
                if 'col_payload_id' in query: return Rows([('original-col',)])
                if 'count(*) from notes' in query: return Rows([(2,)])
                raise AssertionError(query)
        self_test = self
        db = DB(); before = copy.deepcopy(db.metadata)
        with patch.object(export, 'project_book', return_value=book), patch.object(c, 'get_json', return_value={'models': json.dumps({'12': original})}):
            plan = f.registration_plan(db, ['opaque'], expected_revision=14)
        self.assertEqual(db.metadata, before)
        self.assertEqual(set(plan['writes']), {native.MODEL_MODS, native.RUNTIME_REVISIONS})
        after = f.validate_registration_plan(db, plan, expected_sha256=plan['sha256'])
        next_model = json.loads(after[native.MODEL_MODS])[c.identity('opaque', '12')]
        runtime = json.loads(after[native.RUNTIME_REVISIONS])['opaque']
        self.assertGreater(next_model, 20)
        self.assertEqual(runtime['revision'], 2)
        self.assertEqual(runtime['field_script_transport']['models']['12'], {'before': 20, 'after': next_model})
        self.assertGreater(native.effective_content_mod(10, 50, runtime), native.effective_content_mod(10, 50, {'revision': 1, 'floor': 100}))
        db.metadata = copy.deepcopy(after)
        with self.assertRaisesRegex(ValueError, 'unpublished'):
            f.validate_registration_plan(db, plan, expected_sha256=plan['sha256'], rollback=True)
        self.assertEqual(f.validate_registration_plan(db, plan, expected_sha256=plan['sha256'],
                                                     rollback=True, unpublished=True), before)
        db.metadata = copy.deepcopy(before)
        db.metadata[native.MODEL_MODS] += ' '
        with self.assertRaisesRegex(ValueError, 'CAS'):
            f.validate_registration_plan(db, plan, expected_sha256=plan['sha256'])

    def test_real_runtime_writer_preserves_policy_and_default_rejects_stale_registration(self):
        from anki_pipeline import study_catalog_anki as native
        from anki_pipeline import study_field_scripts as f
        from anki_pipeline import study_catalog as c
        m = model(); original = copy.deepcopy(m); original['mod'] = 10
        book = registered({'models': {'12': m}, 'col': {'models': json.dumps({'12': original})},
                           'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}})
        previous = copy.deepcopy(book['runtime_revision'])
        class DB:
            raw = c.canonical({'opaque': previous})
            def execute(self, query, params=()):
                if query.startswith('select value from metadata'):
                    self_test.assertEqual(params, (native.RUNTIME_REVISIONS,))
                    return self
                self_test.assertTrue(query.startswith('insert into metadata values'))
                self_test.assertEqual(params[0], native.RUNTIME_REVISIONS)
                self.raw = params[1]
            def fetchone(self): return (self.raw,)
        self_test = self
        db = DB()
        with patch.object(native.time, 'time', return_value=100):
            native._advance_runtime_revisions(db, ['opaque'])
        current = json.loads(db.raw)['opaque']
        self.assertEqual(current['field_script_transport'], previous['field_script_transport'])
        self.assertEqual(current['revision'], previous['revision'] + 1)
        self.assertEqual(current['floor'], previous['floor'])
        book['runtime_revision'] = current
        with patch.object(export, '_apkg') as build, self.assertRaisesRegex(ValueError, 'runtime version'):
            export._export_projected(None, book, Path('unused'), format='apkg', staging=Path('unused-stage'))
        build.assert_not_called()

    def test_template_insertions_have_exact_inverse_and_no_ambiguous_comment_boundary(self):
        from anki_pipeline import study_field_scripts as f
        m = model(); original = copy.deepcopy(m); original['mod'] = 10
        book = registered({'models': {'12': m}, 'col': {'models': json.dumps({'12': original})},
                           'runtime': {'generated': {}, 'aliases': {}, 'sources': {}}})
        result = f.project_inline_book(book)
        value = result['models']['12']['tmpls'][0]['afmt']
        alias = result['field_script_transport']['runtime_alias']
        value = value.replace('<script src="' + alias + '" data-study-field-restore="v1"></script>', '', 1)
        value = value.replace('window.StudyFieldScriptTransport.restore(document);', '', 1)
        self.assertEqual(value, m['tmpls'][0]['afmt'])
        self.assertEqual(result['models']['12']['tmpls'][0]['qfmt'], m['tmpls'][0]['qfmt'])
        self.assertEqual(result['models']['12']['css'], m['css'])
        self.assertEqual(f._hydrate_rows('<!--<script>window.AnkiSlimApkgHydrate();</script>-->'), [])


if __name__ == '__main__':
    unittest.main()
