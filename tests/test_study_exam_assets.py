import hashlib
import json
from pathlib import Path
import tempfile
import struct
import unittest

from anki_pipeline.study_exam_assets import image_dimensions, resolve_redraws
from anki_pipeline.study_exam_source import _portable


class RedrawAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.original = self.root / 'figure.svg'
        self.original.write_bytes(b'<svg width="320" height="80" viewBox="0 0 320 80">original</svg>')
        self.replacement = self.root / 'redraw.png'
        self.replacement.write_bytes(b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', 640, 400) + b'replacement')
        self.manifest = self.root / 'manifest.json'
        self.entries = [{'original': 'figure.svg', 'replacement': 'redraw.png'}]
        self.overrides = {str(self.original): self.seal(self.original)}

    def seal(self, path):
        cache = self.root / (path.name + '.cache')
        cache.write_bytes(path.read_bytes())
        stat = path.stat()
        return {'path': str(cache), 'source_path': str(path),
                'source_bytes': stat.st_size, 'source_mtime_ns': stat.st_mtime_ns,
                'sha256': hashlib.sha256(cache.read_bytes()).hexdigest()}

    def resolve(self):
        self.manifest.write_text(json.dumps({'version': 1, 'images': self.entries}))
        return resolve_redraws(self.root, self.overrides, self.manifest)

    def test_svg_to_png_uses_sealed_replacement_cache_and_correct_alias(self):
        self.overrides[str(self.replacement)] = self.seal(self.replacement)
        resolved = self.resolve()
        self.assertEqual(self.overrides[str(self.original)]['sha256'], hashlib.sha256(self.original.read_bytes()).hexdigest())
        seal = resolved[str(self.original)]
        self.assertEqual(seal['source_bytes'], self.original.stat().st_size)
        self.assertEqual(seal['bytes'], self.replacement.stat().st_size)
        self.assertEqual(seal['derivative']['original_seal'], self.overrides[str(self.original)])
        resources = {}
        rendered = _portable('<img src="figure.svg">', self.root, self.root, resources, resolved)
        alias = next(iter(resources))
        self.assertTrue(alias.endswith('.png'))
        self.assertIn(alias, rendered)
        self.assertEqual(seal['derivative']['original_dimensions'], {'width':320,'height':80})
        self.assertEqual(seal['derivative']['replacement_dimensions'], {'width':640,'height':400})
        for name, value in (('original-width',320),('original-height',80),('redraw-width',640),('redraw-height',400)):
            self.assertIn('data-exam-'+name+'="'+str(value)+'"', rendered)

        self.assertEqual(Path(resources[alias]['path']).read_bytes(), self.replacement.read_bytes())
        self.assertEqual(seal['derivative']['manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())

    def test_svg_viewbox_fallback_and_absolute_units(self):
        self.assertEqual(image_dimensions(b'<svg viewBox="0 0 120 40"/>','.svg'), {'width':120,'height':40})
        self.assertEqual(image_dimensions(b'<svg width="72pt" height="1in"/>','.svg'), {'width':96,'height':96})
        self.assertEqual(image_dimensions(b'<svg height="60" viewBox="0 0 120 40"/>','.svg'), {'width':180,'height':60})
        for data, suffix in ((b'<svg width="100%"/>','.svg'),(b'notpng','.png'),(b'jpeg','.jpg'),(b'<svg viewBox="0 0 0 40"/>','.svg')):
            self.assertIsNone(image_dimensions(data,suffix))

    def test_no_selected_original_leaves_overrides_unchanged_without_reading_missing_replacement(self):
        self.overrides = {}
        self.replacement.unlink()
        self.assertEqual(self.resolve(), {})

    def test_original_without_redraw_remains_svg(self):
        resources = {}
        _portable('<img src="figure.svg">', self.root, self.root, resources, self.overrides)
        self.assertTrue(next(iter(resources)).endswith('.svg'))

    def test_selected_missing_replacement_fails(self):
        self.replacement.unlink()
        with self.assertRaises(FileNotFoundError): self.resolve()

    def test_manifest_hashes_are_checked(self):
        for field in ('sourceSha256', 'replacementSha256'):
            with self.subTest(field=field):
                self.entries[0][field] = '0' * 64
                with self.assertRaisesRegex(ValueError, field): self.resolve()
                del self.entries[0][field]

    def test_duplicates_chains_and_path_escapes_fail(self):
        cases = [
            [self.entries[0], self.entries[0]],
            [self.entries[0], {'original': 'redraw.png', 'replacement': 'last.png'}],
            [{'original': '../figure.svg', 'replacement': 'redraw.png'}],
            [{'original': 'figure.svg', 'replacement': 'https://host/image.png'}],
            [{'original': 'figure.svg', 'replacement': '%2e%2e/escape.png'}],
        ]
        for entries in cases:
            with self.subTest(entries=entries):
                self.entries = entries
                with self.assertRaises(ValueError): self.resolve()

    def test_symlink_escape_fails(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'x.png'
            target.write_bytes(b'x')
            (self.root / 'escape.png').symlink_to(target)
            self.entries[0]['replacement'] = 'escape.png'
            with self.assertRaisesRegex(ValueError, 'escapes'): self.resolve()

    def test_original_and_replacement_seals_are_checked(self):
        self.overrides[str(self.replacement)] = self.seal(self.replacement)
        for path in (self.original, self.replacement):
            seal = self.overrides[str(path)]
            cache = Path(seal['path'])
            original = cache.read_bytes()
            cache.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'sealed image bytes differ'): self.resolve()
            cache.write_bytes(original)

    def test_invalid_presentation_suffix_fails(self):
        self.overrides[str(self.original)]['presentation_suffix'] = '.html'
        with self.assertRaisesRegex(ValueError, 'unsupported exam image type'):
            _portable('<img src="figure.svg">', self.root, self.root, {}, self.overrides)
