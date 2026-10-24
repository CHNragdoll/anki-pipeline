import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_native_examples_complete as completion


class CompletionAdmissionTests(unittest.TestCase):
    def test_only_authenticated_loader_changes_inside_the_original_module(self):
        legacy = (completion._TEMPLATES / 'slim-apkg-v2-legacy.js').read_text()
        revised = (completion._TEMPLATES / 'slim-apkg-v2.js').read_text()
        source = 'unchanged prefix\n' + legacy + '\nunchanged suffix'
        pin = hashlib.sha256(source.encode()).hexdigest()
        with patch.object(completion, '_SOURCE_MODULES', frozenset({pin})):
            expected = 'unchanged prefix\n' + revised + '\nunchanged suffix'
            self.assertEqual(completion.completion_runtime(source), expected)
            completion.validate_completion_runtime(source, expected)
            with self.assertRaisesRegex(ValueError, 'exact approved'):
                completion.validate_completion_runtime(source, expected + '\nforeign code')
        with self.assertRaisesRegex(ValueError, 'unknown original'):
            completion.completion_runtime(source)

    def test_replaced_current_loader_is_not_approved_by_reading_it_again(self):
        templates = completion._TEMPLATES
        legacy = (templates / 'slim-apkg-v2-legacy.js').read_bytes()
        source = legacy.decode()
        pin = hashlib.sha256(legacy).hexdigest()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / 'slim-apkg-v2-legacy.js').write_bytes(legacy)
            (root / 'slim-apkg-v2.js').write_bytes((templates / 'slim-apkg-v2.js').read_bytes() + b'\nforeign code')
            with patch.object(completion, '_TEMPLATES', root), patch.object(completion, '_SOURCE_MODULES', frozenset({pin})):
                with self.assertRaisesRegex(ValueError, 'completion loader differs'):
                    completion.completion_runtime(source)


class ModelDependencyTests(unittest.TestCase):
    def test_only_exact_source_and_explicit_dependencies_are_eligible(self):
        source = '<script src="module.js"></script><script>audio.src=url</script>'
        pin = hashlib.sha256(source.encode()).hexdigest()
        with patch.object(completion, '_MODEL_DEPENDENCIES', {pin: ('module.js', 'numbering.js')}):
            self.assertTrue(completion.model_runtime_dependencies(source, {'module.js': 'versioned.js'}))
            self.assertFalse(completion.model_runtime_dependencies(source + ' ', {'module.js': 'versioned.js'}))
            self.assertFalse(completion.model_runtime_dependencies(source, {'foreign.js': 'versioned.js'}))
