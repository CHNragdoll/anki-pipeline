"""Approved derived Chinese must reject stale sources and incomplete review."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.option_context import prepare_option_contexts
from anki_pipeline.option_translation import (
    REVIEW_SCHEMA, author_input, context_hash, expected_translations, load_option_translations, validate_translation,
)
from anki_pipeline.reading_completion import _sha, load_reading_completions
from tests import test_option_context as context_fixture


class OptionTranslationTests(unittest.TestCase):
    def setUp(self):
        fixture = context_fixture.OptionContextTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        sentences, self.report = load_codex_exam_index(fixture.stage, allow_partial=True)
        completions, _, _ = load_reading_completions(fixture.root, fixture.sidecar, sentences, self.report)
        _, _, _, self.registry = prepare_option_contexts(fixture.root, sentences, self.report, completions)
        self.path = self.root / 'data/reading-option-translations-v1.json'
        self.directory = self.root / 'output/reading-option-translation-review'
        self.directory.mkdir(parents=True)
        self.header, self.expected = expected_translations(self.registry, self.report, _sha('source registry'))
        self.ids = list(self.expected)
        self.translations = {self.ids[0]: '这个比率表明比率更低。', self.ids[1]: '这个比率表明标准更低。'}
        evidence = {}
        for batch, sid in enumerate(self.ids, 1):
            before = {'schema': 'reading-option-translation-author-input.v1', 'batch': batch,
                'registrySha256': self.header['sourceRegistrySha256'], 'rows': [author_input(self.expected[sid])]}
            after = {'schema': 'reading-option-translation-author-output.v1', 'batch': batch,
                     'rows': [{'sentenceId': sid, 'translationZh': self.translations[sid]}]}
            for kind, value in (('input', before), ('output', after)):
                name = f'author-{kind}-{batch:02d}.json'
                self.write(self.directory / name, value)
                evidence[name] = _sha((self.directory / name).read_bytes())
        review = {'schema': 'reading-option-translation-semantic-review.v1', 'reviewer': 'reviewer_01',
            'authorBatches': [1, 2], 'evidenceFiles': dict(evidence), 'reviewedSentenceIds': self.ids,
            'corrections': [], 'blocked': []}
        self.write(self.directory / 'reviewer-01.json', review)
        evidence['reviewer-01.json'] = _sha((self.directory / 'reviewer-01.json').read_bytes())
        self.payload = {**self.header, 'rows': [
            {'sentenceId': sid, 'contextHash': context_hash(row), 'englishHash': _sha(row['completedEnglish']),
             'translationZh': self.translations[sid], 'translationHash': _sha(self.translations[sid]), 'status': 'reviewed'}
            for sid, row in self.expected.items()]}
        self.approval = {**self.header, 'schema': REVIEW_SCHEMA, 'status': 'approved',
            'sidecarSha256': '', 'reviewedSentenceIds': self.ids, 'evidenceFiles': evidence}
        self.save()

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

    def save(self):
        self.write(self.path, self.payload)
        self.approval['sidecarSha256'] = _sha(self.path.read_bytes())
        self.write(self.path.with_suffix('.review.json'), self.approval)

    def load(self):
        return load_option_translations(self.path, self.registry, self.report)

    def test_approved_complete_text_excludes_preserved_correct_candidate_and_does_not_mutate_sources(self):
        before = copy.deepcopy(self.registry)
        result, watched, counts = self.load()
        self.assertEqual(result, self.translations)
        self.assertEqual(self.registry, before)
        self.assertEqual(counts['preserved_reviewed_translations'], 1)
        self.assertEqual(counts['independently_reviewed_candidates'], 2)
        self.assertEqual(len(watched), 7)
        self.assertTrue(all(_sha(path.read_bytes()) == digest for path, digest in watched.items()))

    def test_context_hash_excludes_new_output_but_binds_original_chinese_and_refs(self):
        row = copy.deepcopy(self.registry[0]); original = context_hash(row)
        row.update(translationZh='新译文。', translationHash=_sha('新译文。'), newTranslationAuthored=True)
        self.assertEqual(context_hash(row), original)
        row['originalQuestionChinese'] = '不同的题干。'
        self.assertNotEqual(context_hash(row), original)
        row = copy.deepcopy(self.registry[0]); row['optionSentenceRefs'][0]['sourceBlockIds'].append('other')
        self.assertNotEqual(context_hash(row), original)

    def test_missing_sidecar_or_approval_fails_closed(self):
        self.path.with_suffix('.review.json').unlink()
        with self.assertRaises(ValueError): self.load()
        self.path.unlink()
        with self.assertRaises(ValueError): self.load()

    def test_sidecar_unknown_fields_missing_row_duplicate_row_and_unapproved_text_rejected(self):
        baseline = copy.deepcopy(self.payload)
        changes = [lambda p: p.update(unknown=True), lambda p: p['rows'].pop(),
            lambda p: p['rows'].__setitem__(1, copy.deepcopy(p['rows'][0])),
            lambda p: p['rows'][0].update(translationZh='未经复核的新译文。', translationHash=_sha('未经复核的新译文。')),
            lambda p: p['rows'][0].update(contextHash=_sha('stale')),
            lambda p: p['rows'][0].update(unknown=True)]
        for change in changes:
            with self.subTest(change=change):
                self.payload = copy.deepcopy(baseline); change(self.payload); self.save()
                with self.assertRaises(ValueError): self.load()

    def test_stale_approval_and_duplicate_or_incomplete_reviewed_ids_rejected(self):
        baseline = copy.deepcopy(self.approval)
        changes = [lambda p: p.update(status='pending'), lambda p: p.update(sidecarSha256=_sha('old')),
            lambda p: p.update(unknown=True), lambda p: p['reviewedSentenceIds'].append(self.ids[0]),
            lambda p: p['reviewedSentenceIds'].pop(), lambda p: p['excludedSentenceIds'].clear()]
        for change in changes:
            with self.subTest(change=change):
                self.approval = copy.deepcopy(baseline); change(self.approval)
                self.write(self.path.with_suffix('.review.json'), self.approval)
                with self.assertRaises(ValueError): self.load()

    def test_original_source_drift_and_invalid_reference_hash_rejected(self):
        baseline = copy.deepcopy(self.registry)
        changes = [lambda r: r[0]['optionSentenceRefs'][0].update(english='Changed English.'),
            lambda r: r[0]['stemSentenceRefs'][0].update(sourceHash=_sha('old')),
            lambda r: r[0].update(completedEnglish='Changed completed English.'),
            lambda r: r[0].update(indexFileHash=_sha('old')),
            lambda r: r[0].update(originalQuestionChinese='另一题干。'),
            lambda r: next(row for row in r if row['isCorrectCandidate']).update(
                translationZh='改写正确候选。', translationHash=_sha('改写正确候选。'))]
        for change in changes:
            with self.subTest(change=change):
                self.registry = copy.deepcopy(baseline); change(self.registry)
                with self.assertRaises(ValueError): self.load()

    def test_changed_author_file_rejected_even_when_approval_evidence_sha_is_refreshed(self):
        path = self.directory / 'author-output-01.json'
        value = json.loads(path.read_text()); value['rows'][0]['translationZh'] = '作者未经审校的修改。'
        self.write(path, value)
        with self.assertRaises(ValueError): self.load()
        self.approval['evidenceFiles'][path.name] = _sha(path.read_bytes()); self.save()
        with self.assertRaises(ValueError): self.load()

    def test_incomplete_blocked_or_unbound_reviewer_correction_rejected(self):
        path = self.directory / 'reviewer-01.json'; baseline = json.loads(path.read_text())
        changes = [lambda p: p['reviewedSentenceIds'].pop(), lambda p: p.update(blocked=['unresolved']),
            lambda p: p['corrections'].append({'sentenceId': self.registry[-1]['sentenceId'],
                'translationZh': '改写正确选项。', 'reason': 'outside scope'}),
            lambda p: p['evidenceFiles'].update({'author-output-01.json': _sha('old')})]
        for change in changes:
            with self.subTest(change=change):
                value = copy.deepcopy(baseline); change(value); self.write(path, value)
                self.approval['evidenceFiles'][path.name] = _sha(path.read_bytes()); self.save()
                with self.assertRaises(ValueError): self.load()

    def test_labels_blanks_html_newlines_and_numbers_rejected(self):
        for text in ('题干：完整句。', '选项 A：完整句。', '完整［选项 A］句。', '完整____句。',
                     '21. 完整句。', '完整\n句。', '<b>完整句。</b>', ' 完整句。'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_translation(text, self.expected[self.ids[0]])
        context = copy.deepcopy(self.expected[self.ids[0]])
        context.update(hasQuestionBlank=False, questionEnglish='Why does it fall?')
        with self.assertRaises(ValueError): validate_translation('下降，因为标准更低。', context)
        validate_translation('为什么会下降？标准更低。', context)

    def test_duplicate_json_keys_rejected(self):
        self.path.write_text('{"schema":"one","schema":"two"}', encoding='utf-8')
        with self.assertRaises(ValueError): self.load()

    def test_path_traversal_and_extraneous_evidence_rejected(self):
        self.approval['evidenceFiles']['../../unauthorized.json'] = _sha('other'); self.save()
        with self.assertRaises(ValueError): self.load()


if __name__ == '__main__':
    unittest.main()
