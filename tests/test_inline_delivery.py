import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_inline_disclosure_delivery import SampleMedia


def pin(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def registration(key, value):
    return 'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets[' + json.dumps(key) + ']=' + json.dumps(value) + ';'


class SampleMediaTests(unittest.TestCase):
    def test_packed_logical_alias_and_nested_style_audio_are_included(self):
        raw = '<p>完整原文</p><link href="style.css"><audio src="word.mp3"></audio>'
        bank = json.dumps({'schema': 'anki-slim-shared-dictionary.v1', 'strings': [raw, 'unrelated.js']})
        bank_pin = pin(bank); bank_name = '_as_' + bank_pin[:24] + '.js'
        raw_pin = pin(raw); logical = '_as_' + raw_pin[:24] + '.js'; physical = logical.replace('_as_', '_ac_')
        packed = {'schema': 'anki-slim-shared-strings.v1', 'dict': {'src': bank_name, 'sha256': bank_pin, 'literal': True}, 'pieces': [0]}
        contents = {physical: registration(raw_pin, packed), bank_name: registration(bank_pin, bank),
                    'style.css': 'x{background:url(icon.png)}', 'icon.png': b'png', 'word.mp3': b'audio', 'unrelated.js': 'not used'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.zip'; mapping = {str(i): name for i, name in enumerate(contents)}
            with zipfile.ZipFile(path, 'w') as archive:
                for key, name in mapping.items():
                    archive.writestr(key, contents[name])
            with zipfile.ZipFile(path) as archive:
                result = SampleMedia(archive, mapping).closure(['data-as-src="' + logical + '"'])
            self.assertEqual(set(result.values()), set(contents) - {'unrelated.js'})

    def test_invalid_reconstructed_string_is_rejected(self):
        raw = '<p>original</p>'; key = pin(raw); name = '_ac_' + key[:24] + '.js'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('0', registration(key, 'changed'))
            with zipfile.ZipFile(path) as archive:
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    SampleMedia(archive, {'0': name}).closure([name])


if __name__ == '__main__':
    unittest.main()
