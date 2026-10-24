"""Post-expansion protection preserves no-op cache inputs and source bytes."""
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize
from anki_pipeline import study_compiled_preparation as stage
from anki_pipeline.study_field_scripts import protect_field
from tests import test_study_catalog_web_materialize as fixtures


class PreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'cards').mkdir()
        (self.root / 'media').mkdir()
        (self.root / 'evidence').mkdir()

    def fixture(self, changed):
        if changed:
            part = fixtures.PreparedDeliveryTests().register(self.root / 'media',
                '<li>原句／译文<details><summary>原审核</summary>'
                '<div class="as-lazy" data-as-kind="detail">'
                '<script class="as-manifest" type="application/json">'
                '{"schema":"anki-slim-segments.v1","parts":[],"total":0}'
                '</script></div></details></li>')
            manifest = json.dumps({'schema': 'anki-slim-segments.v1',
                                   'parts': [{**part, 'count': 1}], 'total': 1})
            back = protect_field('<html><body><ol class="examples"><li class="as-lazy" '
                'data-as-kind="examples"><script class="as-manifest" type="application/json">' +
                manifest + '</script></li></ol></body></html>', field_name='Examples')
        else:
            back = '<html><body>完整背面😀</body></html>'
        sides = ['<html><body>原正面</body></html>', back]
        wrapper = web.card_shell(json.dumps(sides, ensure_ascii=False), '../media/').encode()
        value = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': materialize.digest(wrapper),
                 'source_payload_sha256': materialize.digest(web.card_payload(wrapper)),
                 'sides': [materialize.materialize_side(side, materialize.ReadOnlyMedia(self.root / 'media'))
                           for side in sides], 'modules': {}}
        raw = json.dumps(value, ensure_ascii=False, indent=2).encode()
        return wrapper, raw

    def test_noop_preserves_exact_noncanonical_bytes_and_all_bindings(self):
        wrapper, raw = self.fixture(False)
        normalized, proof = stage.normalize_artifact(raw, wrapper, materialize.ReadOnlyMedia(self.root / 'media'))
        self.assertIs(normalized, raw)
        self.assertIsNone(proof)

    def test_change_reseals_input_without_changing_source_or_registered_modules(self):
        wrapper, raw = self.fixture(True)
        before = {path: path.read_bytes() for path in (self.root / 'media').iterdir()}
        normalized, proof = stage.normalize_artifact(raw, wrapper, materialize.ReadOnlyMedia(self.root / 'media'))
        old, new = json.loads(raw), json.loads(normalized)
        self.assertNotEqual(raw, normalized)
        self.assertEqual(proof['base_artifact_sha256'], materialize.digest(raw))
        self.assertEqual(new['modules'], old['modules'])
        self.assertEqual(new['sides'][0], old['sides'][0])
        self.assertEqual(new['source_wrapper_sha256'], materialize.digest(wrapper))
        self.assertEqual(new['source_payload_sha256'], old['source_payload_sha256'])
        self.assertEqual(new['sides'][1]['proof']['source_sha256'], old['sides'][1]['proof']['source_sha256'])
        self.assertEqual(new['sides'][1]['proof']['expanded_sha256'], materialize.digest(new['sides'][1]['html']))
        self.assertEqual(new['sides'][1]['proof']['expanded_bytes'], len(new['sides'][1]['html'].encode('utf-8')))
        self.assertEqual(proof['changes'][0]['side'], 1)
        self.assertEqual(proof['changes'][0]['evidence']['added_carriers'], 1)
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_changed_wrapper_and_expanded_pin_are_rejected(self):
        wrapper, raw = self.fixture(True)
        with self.assertRaisesRegex(ValueError, 'bound'):
            stage.normalize_artifact(raw, wrapper + b' ', materialize.ReadOnlyMedia(self.root / 'media'))
        value = json.loads(raw)
        value['sides'][1]['html'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'pins differ'):
            stage.normalize_artifact(json.dumps(value).encode(), wrapper, materialize.ReadOnlyMedia(self.root / 'media'))

    def test_library_changed_front_and_index_bind_new_full_artifact(self):
        wrapper, _ = self.fixture(True)
        card = {'id': 'one', 'url': 'cards/one.html', 'word': 'one', 'unit': 'unit'}
        (self.root / card['url']).write_bytes(wrapper)
        catalog = {'book_id': 'unrelated-subject', 'cards': [card]}
        base = materialize.prepare_library(self.root, catalog, {'policy': {'external': {}, 'inline': []}})
        base_index_raw = materialize._compiled_output(self.root, base['config']['preparedIndex'])
        base_rule = json.loads(base_index_raw)['cards']['one']
        base_raw = materialize._compiled_output(self.root, base_rule)
        updated = stage.normalize_library(self.root, catalog, base)
        rule = json.loads(materialize._compiled_output(self.root, updated['config']['preparedIndex']))['cards']['one']
        artifact = materialize._compiled_output(self.root, rule)
        front = json.loads(materialize._compiled_output(self.root, rule['front']))
        self.assertNotEqual(rule['sha256'], base_rule['sha256'])
        self.assertEqual(front['full_prepared_sha256'], materialize.digest(artifact))
        self.assertEqual(front['source_wrapper_sha256'], materialize.digest(wrapper))
        self.assertEqual(materialize._compiled_output(self.root, base_rule), base_raw)
        self.assertEqual(materialize._compiled_output(self.root, base['config']['preparedIndex']), base_index_raw)
        self.assertEqual(updated['normalization']['changed'][0]['base'], base_rule)

    def test_library_noop_preserves_original_config_and_descriptors(self):
        wrapper, _ = self.fixture(False)
        card = {'id': 'one', 'url': 'cards/one.html', 'word': 'one', 'unit': 'unit'}
        (self.root / card['url']).write_bytes(wrapper)
        catalog = {'book_id': 'unrelated-subject', 'cards': [card]}
        base = materialize.prepare_library(self.root, catalog, {'policy': {'external': {}, 'inline': []}})
        before = {path: path.read_bytes() for path in (self.root / 'evidence').iterdir()}
        updated = stage.normalize_library(self.root, catalog, base)
        self.assertIs(updated['config'], base['config'])
        self.assertEqual(updated['normalization']['unchanged'], 1)
        self.assertEqual(updated['normalization']['changed'], [])
        self.assertEqual({path: path.read_bytes() for path in (self.root / 'evidence').iterdir()}, before)


if __name__ == '__main__':
    unittest.main()
