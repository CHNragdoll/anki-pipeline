import hashlib
from importlib.resources import files
import json
import unittest


class OfflineMathAssetsTests(unittest.TestCase):
    def test_all_pinned_resources_are_available_without_database_or_network(self):
        root = files('anki_pipeline').joinpath('web_runtime/mathjax')
        manifest = json.loads(root.joinpath('SOURCE.json').read_text())
        self.assertEqual(manifest['version'], '3.2.2')
        self.assertTrue(any(name.endswith('.woff') for name in manifest['files']))
        for name, digest in manifest['files'].items():
            with self.subTest(resource=name):
                self.assertEqual(hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest(), digest)
