"""Production card links cannot silently target stale or absent reader data."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.exam_library import _codex_examples, _published_codex_index
from tests.test_codex_exam_index import PAPERS, record, write_fixture, write_json
from tests.test_packaging import card


class CodexReaderBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stage = self.root / 'staging'
        self.public = self.root / 'data/sources/exam-library/structured/codex-translations/kaoyan'
        write_fixture(self.stage, names=PAPERS, scope='full')
        _, self.report = load_codex_exam_index(self.stage)

    def publish_fixture(self):
        self.public.mkdir(parents=True, exist_ok=True)
        rows = []
        for name in PAPERS:
            shutil.copyfile(self.stage / 'index' / (name + '.json'), self.public / (name + '.json'))
            rows.append({'paperId': 'kaoyan:' + name, 'file': name + '.json',
                         'sha256': self.report['source_files']['index/' + name + '.json'],
                         **{field: self.report['source_files'][folder + '/' + name + '.json']
                            for field, folder in [('inputHash', 'inputs'),
                                                  ('translationHash', 'translations'),
                                                  ('reviewHash', 'reviews')]}})
        manifest = {'schema': 'codex-exam-static-manifest.v1', 'scope': 'full',
                    'semanticReviewStatus': 'approved',
                    'indexManifestHash': self.report['manifest_sha256'],
                    'inputManifestHash': self.report['input_manifest_sha256'],
                    'totals': {key: self.report[key] for key in
                               ('papers', 'paragraphs', 'sentences', 'alignments', 'blocked')},
                    'papers': rows}
        write_json(self.public / 'manifest.json', manifest)
        return manifest

    def test_missing_changed_unapproved_or_incomplete_static_snapshot_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not been published'):
            _published_codex_index(self.root, self.report)
        baseline = self.publish_fixture()
        self.assertEqual(len(_published_codex_index(self.root, self.report)), 45)
        for change in ('unapproved', 'stale-index', 'stale-input', 'missing-paper', 'duplicate-paper',
                       'wrong-review', 'wrong-filename', 'changed-file'):
            with self.subTest(change=change):
                self.publish_fixture()
                manifest = copy.deepcopy(baseline)
                if change == 'unapproved': manifest['semanticReviewStatus'] = 'unreviewed'
                if change == 'stale-index': manifest['indexManifestHash'] = '0' * 64
                if change == 'stale-input': manifest['inputManifestHash'] = '0' * 64
                if change == 'missing-paper': manifest['papers'].pop()
                if change == 'duplicate-paper': manifest['papers'].append(copy.deepcopy(manifest['papers'][0]))
                if change == 'wrong-review': manifest['papers'][0]['reviewHash'] = '0' * 64
                if change == 'wrong-filename': manifest['papers'][0]['file'] = '../2000-01.json'
                if change == 'changed-file':
                    path = self.public / '2000-01.json'
                    path.write_bytes(path.read_bytes() + b' ')
                write_json(self.public / 'manifest.json', manifest)
                with self.assertRaises(ValueError):
                    _published_codex_index(self.root, self.report)

    def test_reader_sidecar_symlink_cannot_escape_published_directory(self):
        self.publish_fixture()
        path = self.public / '2000-01.json'
        path.unlink()
        path.symlink_to(self.stage / 'index/2000-01.json')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            _published_codex_index(self.root, self.report)

    def test_full_build_links_pin_reviewed_sentence_hash_and_exact_word_ranges(self):
        self.publish_fixture()
        value = card(audio='')
        cards, report = _codex_examples(self.root, [value], 'http://localhost:8765', 'latex', 0,
                                        self.stage, False)
        self.assertEqual(report['examples'], 44)
        self.assertEqual(report['option_contexts']['contextualized_option_paragraphs'], 0)
        self.assertEqual(report['option_contexts']['new_translations'], 0)
        self.assertEqual(report['sentences_without_source_anchor'], [])
        for example in cards[0]['examples']:
            for key in ('latex_url', 'full_paper_url'):
                params = parse_qs(urlsplit(example[key]).query)
                self.assertEqual(params['anki-codex-sentence'], [example['sentence_id']])
                self.assertEqual(params['anki-codex-hash'], [example['english_hash']])
                self.assertEqual(params['anki-codex-review'], [example['reviewed_content_hash']])
                self.assertEqual(json.loads(params['anki-codex-en'][0]), [[4, 8]])
                self.assertNotIn('anki-sentence', params)

    def test_review_pin_changes_for_chinese_or_alignment_without_english_drift(self):
        hashes = []
        for translation, alignments in (
            ('比率上升了。', [{'en': [4, 8], 'zh': [[0, 2]], 'relation': 'equivalent'}]),
            ('比例上升了。', [{'en': [4, 8], 'zh': [[0, 2]], 'relation': 'equivalent'}]),
            ('比率上升了。', [{'en': [4, 8], 'zh': [[0, 1]], 'relation': 'equivalent'}]),
        ):
            write_fixture(self.stage, names=('2026-01',), records={'2026-01': [
                record(translation=translation, alignments=alignments)]})
            cards, _ = _codex_examples(self.root, [card(audio='')], '', 'latex', 0, self.stage, True)
            example = cards[0]['examples'][0]
            hashes.append((example['english_hash'], parse_qs(urlsplit(example['latex_url']).query)[
                'anki-codex-review'][0]))
        self.assertEqual(len({english for english, _ in hashes}), 1)
        self.assertEqual(len({review for _, review in hashes}), 3)

    def test_only_selected_dictionary_inflections_match_without_derived_or_old_forms(self):
        pair = record(english='rate rated rates rating ambitious', translation='比率评价比率评价有野心',
                      alignments=[{'en': [0, 4], 'zh': [[0, 2]], 'relation': 'equivalent'}])
        write_fixture(self.stage, names=('2026-01',), records={'2026-01': [pair]})
        value = card(audio='')
        value['local_dictionary'] = {'forms_source': 'webster',
            'forms': [{'kind': 'past', 'form': 'rated', 'base': 'rate'}],
            'derived': [{'kind': 'adjective', 'form': 'ambitious'}]}
        cards, _ = _codex_examples(self.root, [value], '', 'latex', 0, self.stage, True)
        self.assertEqual(cards[0]['examples'][0]['matched_english_ranges'], [[0, 4], [5, 10]])
        value.pop('local_dictionary')
        cards, _ = _codex_examples(self.root, [value], '', 'latex', 0, self.stage, True)
        self.assertEqual(cards[0]['examples'][0]['matched_english_ranges'], [[0, 4]])


if __name__ == '__main__':
    unittest.main()
