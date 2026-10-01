"""Bare option words count in the corpus but are not separate example cards."""
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.exam_library import library_examples
from tests.test_codex_exam_index import record, write_fixture
from tests import test_exam_library as legacy_fixture
from tests.test_packaging import card


class CodexExampleEligibilityTests(unittest.TestCase):
    def test_single_word_options_skip_display_without_losing_forms_cloze_or_frequency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / 'staging'
            pairs = []
            for index, (english, kind, form) in enumerate([
                ('rates', 'answer_option', 'rates'),
                ('“rate.”', 'answer_option', 'rate'),
                ('The rate rose.', 'reading', 'rate'),
                ('The rates rose.', 'cloze', 'rates'),
                ('higher rate', 'answer_option', 'rate'),
            ]):
                start = english.index(form)
                answers = [{'start': start, 'end': start + len(form), 'answer': form,
                            'number': '1'}] if kind == 'cloze' else []
                pairs.append(record(english=english, kind=kind,
                    identifier=f'kaoyan:2026-01:p:fixture-{index}',
                    cloze_answers=answers,
                    alignments=[{'en': [start, start + len(form)], 'zh': [[0, 2]],
                                 'relation': 'equivalent'}]))
            write_fixture(stage, records={'2026-01': pairs})
            source = {p: p.read_bytes() for p in stage.rglob('*.json')}
            value = card('rate-card', word='rate', audio='')
            value['local_dictionary'] = {'forms_source': 'webster',
                'forms': [{'kind': 'plural', 'form': 'rates', 'base': 'rate'}]}
            kwargs = dict(sentence_source='codex', codex_index_root=stage,
                          allow_partial_codex=True)
            actual, report = library_examples(root, [value], 'http://localhost:8765',
                                              'full-paper', **kwargs)
            self.assertEqual([row['text'] for row in actual[0]['examples']],
                             ['The rate rose.', 'The rates rose.', 'higher rate'])
            self.assertEqual(actual[0]['exam_frequency']['occurrences'], 5)
            self.assertEqual(actual[0]['examples'][1]['cloze_answers'],
                             [{'start': 4, 'end': 9, 'word': 'rates', 'number': 1}])
            self.assertEqual(actual[0]['examples'][1]['matched_english_ranges'], [[4, 9]])
            self.assertEqual(report['skipped_standalone_word_option_matches'], 2)
            capped, capped_report = library_examples(root, [value], 'http://localhost:8765',
                                                     'full-paper', 1, **kwargs)
            self.assertEqual([row['text'] for row in capped[0]['examples']], ['The rate rose.'])
            self.assertEqual(capped[0]['exam_frequency'], actual[0]['exam_frequency'])
            self.assertEqual(capped_report['skipped_standalone_word_option_matches'], 2)
            self.assertEqual(source, {p: p.read_bytes() for p in source})


class LegacyExampleEligibilityTests(unittest.TestCase):
    # Reuse the controlled catalog fixture without inheriting its test methods.
    setUp = legacy_fixture.ExamLibraryTests.setUp
    write_catalog = legacy_fixture.ExamLibraryTests.write_catalog
    import_cards = legacy_fixture.ExamLibraryTests.import_cards

    def test_legacy_export_applies_same_display_filter(self):
        options = legacy_fixture.paragraph('kaoyan:2026-01', ['rate', 'rated.', 'higher rate'],
                            ['比率', '评价', '更高的比率'], kind='answer_option')
        self.write_catalog([('kaoyan:2026-01', [options])])
        before = {p: p.read_bytes() for p in self.index.rglob('*.json')}
        values, report = self.import_cards()
        self.assertEqual([row['text'] for row in values[0]['examples']], ['higher rate'])
        self.assertEqual(values[0]['exam_frequency']['occurrences'], 3)
        self.assertEqual(report['skipped_standalone_word_option_matches'], 2)
        self.assertEqual(before, {p: p.read_bytes() for p in before})


if __name__ == '__main__':
    unittest.main()
