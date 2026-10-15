"""Guarded semantic changes; fixtures never read the production database."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import eleven_semantic_resolution as lane
from anki_pipeline import sense_frequency as sf


class ElevenSemanticTests(unittest.TestCase):
    def fixture(self, *, source=False):
        word = 'as' if source else 'mature'
        english = 'This made us mature.' if not source else 'For instance, as convenient.'
        start = english.index(word)
        record = {'book_id': 'redbook', 'card_id': 'fixture', 'word': word,
            'definition_source': 'original', 'definition_provenance': {'source': 'original', 'headword': word},
            'senses': [{'pos': 'v.', 'text': '情感成熟'}, {'pos': 'adj.', 'text': '成熟的'}],
            'expected_occurrences': 2, 'occurrences': []}
        for n in range(2):
            row = {'paper_id': 'kaoyan:2015-02', 'sentence_id': 'kaoyan:2015-02:p:test:' + str(n),
                'physical_source': ['test', n], 'english': english, 'english_hash': sf._sha(english),
                'translation': '原译', 'target_range': [start, start + len(word)], 'translation_ranges': [],
                'source': '原来源', 'source_provenance': {'original': True},
                'alignment': None, 'alignment_evidence': [], 'status': 'ambiguous', 'sense_index': None,
                'reason': '原审核完整说明', 'method': 'old', 'review_version': 'old'}
            record['occurrences'].append(row)
        parent = sf.prepare_record(record)
        oid = parent['occurrences'][0]['occurrence_id']
        parent['occurrences'][0]['semantic_review'] = {'occurrence_id': oid, 'reason': '原先所有证据'}
        parent.pop('snapshot_id')
        parent['snapshot_id'] = lane.digest(parent)
        row = parent['occurrences'][0]
        evidence = {'word': word, 'english': english, 'sentence_id': row['sentence_id'], 'target_range': row['target_range'],
            'native_primary': {'original_chinese': '情感成熟', 'english_definition': 'emotionally mature', 'name': 'Original dictionary'},
            'assignment_reason': '心理成熟，按最合适的动词义归类', 'confidence': 'medium',
            'other_native_candidates_preserved': [{'meaning': '形容词的结果状态'}]}
        if source:
            evidence['recommendation'] = {'reason_zh': '原稿结构存疑；保留原文和全部证据'}
        return parent, oid, evidence

    def test_semantic_primary_preserves_full_original_and_untargeted_rows(self):
        parent, oid, evidence = self.fixture()
        saved = deepcopy(parent)
        with patch.object(lane, 'SCOPE', {oid: 'mature'}):
            child = lane.transform(parent, {oid: evidence}, {oid})
        self.assertEqual(parent, saved)
        target = next(r for r in child['occurrences'] if r['occurrence_id'] == oid)
        self.assertEqual(target['status'], 'reviewed')
        self.assertFalse(target['semantic_review']['unique_native_sense_proven'])
        self.assertEqual(target['semantic_review']['original_row'], parent['occurrences'][0])
        self.assertEqual(child['definition_snapshot_id'], parent['definition_snapshot_id'])
        self.assertEqual(child['occurrences'][1], parent['occurrences'][1])
        self.assertEqual(child['expected_occurrences'], 2)

    def test_as_is_explicit_anomaly_without_fake_sense(self):
        parent, oid, evidence = self.fixture(source=True)
        with patch.object(lane, 'SCOPE', {oid: 'as'}), patch.object(lane, 'AS_ID', oid):
            child = lane.transform(parent, {oid: evidence}, {oid})
        row = next(r for r in child['occurrences'] if r['occurrence_id'] == oid)
        self.assertEqual(row['status'], 'ambiguous')
        self.assertIsNone(row['sense_id'])
        self.assertEqual(row['semantic_review']['workflow_resolution_status'], 'handled_source_anomaly')
        self.assertEqual(row['semantic_review']['source_notice']['display_label'], '原文结构异常')
        self.assertEqual(child['senses'], parent['senses'])
        page = '<article class="sf-example" data-sf-occurrence-id="' + oid + '"><p>fixture</p></article>'
        with patch.object(lane, 'AS_ID', oid):
            markup, inverse = lane.render_semantic_history(page, child, {})
        self.assertIn('原文结构异常', markup)
        self.assertNotIn('归类方法：按最有依据的释义', markup)
        self.assertIn('未分配标准词典义项', markup)
        from scripts import update_exam_usage_preview as preview
        self.assertEqual(preview.restore_edits(markup, inverse), page)

    def test_source_and_unrelated_semantic_mutations_rejected(self):
        parent, oid, evidence = self.fixture()
        with patch.object(lane, 'SCOPE', {oid: 'mature'}):
            child = lane.transform(parent, {oid: evidence}, {oid})
            wrong = deepcopy(child)
            wrong['occurrences'][0]['translation'] = '擅自改译'
            with self.assertRaisesRegex(ValueError, 'physical/chunk'):
                lane.validate_child(parent, wrong, {oid})
            wrong = deepcopy(child)
            wrong['occurrences'][1]['reason'] = '改了其他记录'
            with self.assertRaisesRegex(ValueError, 'unrelated'):
                lane.validate_child(parent, wrong, {oid})

    def test_stale_evidence_rejected_and_apply_requires_explicit_authority(self):
        parent, oid, evidence = self.fixture()
        evidence['target_range'] = [0, 2]
        with patch.object(lane, 'SCOPE', {oid: 'mature'}):
            with self.assertRaisesRegex(ValueError, 'source text/range'):
                lane.transform(parent, {oid: evidence}, {oid})
        with self.assertRaisesRegex(ValueError, 'authorization'):
            lane.apply({})

    def test_twenty_card_atomic_idempotent_recovery_on_small_real_SQL_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            records, evidence, scope = [], [], {}
            words = ['mature', 'fantastic', 'as', 'quiet', 'great', 'application', 'share', 'secure', 'quite', 'be', 'quite']
            for book in sorted(lane.BOOKS):
                for word in dict.fromkeys(words):
                    record = {'book_id': book, 'card_id': book + '-' + word, 'word': word,
                        'definition_source': 'fixture', 'definition_provenance': {'source': 'fixture', 'headword': word},
                        'senses': [{'pos': 'v.', 'text': '测试原义'}],
                        'expected_occurrences': words.count(word), 'occurrences': []}
                    for n, item in enumerate(words):
                        if item != word:
                            continue
                        english = 'A ' + word + ' example.'
                        row = {'paper_id': 'kaoyan:2015-02', 'sentence_id': 'kaoyan:2015-02:p:test:' + str(n),
                            'physical_source': ['fixture', n], 'english': english,
                            'english_hash': sf._sha(english), 'translation': '原译', 'target_range': [2, 2 + len(word)],
                            'translation_ranges': [], 'source': '原来源', 'source_provenance': {'fixture': True},
                            'alignment': None, 'alignment_evidence': [], 'status': 'ambiguous', 'sense_index': None,
                            'reason': '旧完整审查', 'method': 'fixture', 'review_version': 'fixture'}
                        record['occurrences'].append(row)
                    prepared = sf.prepare_record(record)
                    records.append(record)
                    if book == 'redbook':
                        for row in prepared['occurrences']:
                            oid = row['occurrence_id']
                            scope[oid] = word
                            evidence.append({'word': word, 'occurrence_id': oid, 'english': row['english'],
                                'sentence_id': row['sentence_id'], 'target_range': row['target_range'],
                                'native_primary': {'original_chinese': '测试原义', 'english_definition': 'fixture native sense', 'name': 'fixture'},
                                'assignment_reason': '依据原译匹配', 'confidence': 'medium',
                                'other_native_candidates_preserved': ['保留其他读法'],
                                'recommendation': {'reason_zh': '原稿结构存疑'}})
            protected, candidate = root / 'protected.sqlite3', root / 'candidate.sqlite3'
            sf.save_records(protected, records, root / 'backups')
            protected_bytes = protected.read_bytes()
            shutil.copyfile(protected, candidate)
            selected = [x for x in evidence if x['word'] != 'as']
            as_row = next(x for x in evidence if x['word'] == 'as')
            def pin(name, value):
                path = root / name
                path.write_text(lane.canonical(value))
                return lane.pin(path)
            request = {'schema': lane.REQUEST, 'candidate': {'file': str(candidate)},
                'protected': {'file': str(protected), 'stat': lane.sc.stat_pin(protected)},
                'body_evidence': pin('body.json', {'records': selected[:5]}),
                'option_evidence': pin('options.json', {'records': selected[5:]}),
                'as_evidence': pin('as.json', as_row)}
            with patch.object(lane, 'SCOPE', scope), patch.object(lane, 'AS_ID', as_row['occurrence_id']):
                prepared = lane.prepare(request, root / 'plan')
                plan = lane.ro.read_json(prepared['plan'])
                result = lane.rehearse(plan, root / 'scratch')
            self.assertTrue(result['injected_failure_atomic'])
            self.assertTrue(result['apply_idempotent'])
            self.assertTrue(result['rollback_idempotent'])
            self.assertEqual(result['cards'], 20)
            self.assertEqual(protected.read_bytes(), protected_bytes)
            with closing(sqlite3.connect(candidate)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 20)


if __name__ == '__main__':
    unittest.main()
