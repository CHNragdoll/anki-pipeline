import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled as compiler
from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materializer


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class CompiledInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('cards', 'media', 'evidence'):
            (self.root / name).mkdir()
        original = b'window.fixtureNative = true;'
        self.native_pin = sha(original)
        self.prepared = original + b'\n// prepared test capability\n'
        (self.root / 'media/native.js').write_bytes(original)
        (self.root / 'evidence/prepared.js').write_bytes(self.prepared)
        self.policy = {'external': {'native.js': self.native_pin}, 'inline': []}
        front = '<!doctype html><html><head></head><body>front</body></html>'
        back = ('<!doctype html><html><head><base href="../media/"></head>'
                '<body><div>完整原文 中文</div><script src="native.js"></script></body></html>')
        payload = json.dumps([front, back], ensure_ascii=False).replace('<', '\\u003c')
        raw = web.card_shell(payload, '../media/').encode()
        self.wrapper = self.root / 'cards/source.html'
        self.wrapper.write_bytes(raw)
        media = materializer.ReadOnlyMedia(self.root / 'media')
        self.value = {'schema': 'study-prepared-card.v1',
                      'source_wrapper_sha256': sha(raw),
                      'source_payload_sha256': sha(payload.encode()),
                      'sides': [materializer.materialize_side(side, media) for side in (front, back)],
                      'modules': {self.native_pin: {'original_sha256': self.native_pin,
                                  'src': 'evidence/prepared.js', 'sha256': sha(self.prepared)}}}
        self.artifact = self.root / 'evidence/card.json'
        self.save_artifact()
        self.output = self.root / 'new-inputs'
        self.addCleanup(patch.stopall)
        patch.object(materializer, 'AUDITED_NATIVE_MODULES', frozenset({self.native_pin})).start()
        patch.object(materializer, 'prepare_native_module', return_value=self.prepared.decode()).start()

    def save_artifact(self):
        self.artifact.write_text(json.dumps(self.value, ensure_ascii=False))

    def build(self):
        return compiler.build_semantic_request(
            self.root,
            {'path': 'cards/source.html', 'sha256': sha(self.wrapper.read_bytes())},
            {'path': 'evidence/card.json', 'sha256': sha(self.artifact.read_bytes())},
            self.output, policy=self.policy, source_url='https://study.invalid/book/index.html')

    def test_frozen_request_preserves_source_and_copies_only_referenced_resources(self):
        (self.root / 'media/unrelated.mp3').write_bytes(b'untouched audio')
        before = self.wrapper.read_bytes(), self.artifact.read_bytes()
        result = self.build()
        request = json.loads((self.output / 'request.json').read_text())
        self.assertEqual(request['schema'], 'study-compiled-semantic-request.v1')
        self.assertEqual(request['source']['wrapper_sha256'], self.value['source_wrapper_sha256'])
        self.assertEqual(set(request['resources']), {'https://study.invalid/book/media/native.js',
                                                   'https://study.invalid/book/evidence/prepared.js'})
        for row in [request['artifact'], request['module'], request['helpers'], *request['resources'].values()]:
            self.assertEqual(sha(Path(row['path']).read_bytes()), row['sha256'])
        self.assertEqual(before, (self.wrapper.read_bytes(), self.artifact.read_bytes()))
        self.assertNotIn(b'untouched audio', [p.read_bytes() for p in self.output.iterdir() if p.is_file()])
        self.assertTrue(result['raw_wrapper_and_payload_verified'])

    def test_changed_source_payload_or_registry_is_rejected_before_output(self):
        for mutate in ('payload', 'expanded', 'registry'):
            with self.subTest(mutate=mutate):
                original = json.loads(json.dumps(self.value))
                if mutate == 'payload': self.value['source_payload_sha256'] = '0' * 64
                elif mutate == 'expanded': self.value['sides'][1]['html'] += '<p>other</p>'
                else: self.value['sides'][1]['registry']['0' * 64] = 'changed source'
                self.save_artifact()
                with self.assertRaises(ValueError): self.build()
                self.assertFalse(self.output.exists())
                self.value = original
                self.save_artifact()

    def test_prepared_module_must_be_exact_derivative_of_approved_original(self):
        (self.root / 'media/native.js').write_text('window.changedOriginal=true;')
        with self.assertRaises(ValueError): self.build()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'owner.txt'
        sentinel.write_text('external change')
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(sentinel.read_text(), 'external change')


if __name__ == '__main__':
    unittest.main()
