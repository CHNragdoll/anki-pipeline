"""Review provenance, exact context preservation and fail-closed partial merging."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from scripts import merge_sense_reviews as mr
from tests.test_sense_frequency import aligned_record


class MergeSenseReviewsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inventory = self.root / 'inventory'; self.inventory.mkdir()
        self.parallel = self.root / 'parallel'; self.parallel.mkdir()
        self.unit = self.root / 'unit'; self.unit.mkdir()
        self.output = self.root / 'merged'
        first = aligned_record(); first.update(book_id='redbook', card_id='card26')
        for row in first['occurrences']:
            row.update(status='unmatched', sense_index=None, reason='待核对')
            row.pop('reviewed_sense_id'); row.pop('assignment_context_hash')
        second = deepcopy(first); second.update(book_id='redbook2027', card_id='card27')
        self.records = [first, second]
        prepared = sf.prepare_record(first)
        self.work_id = mr.fingerprint([first['word'], first['definition_source'], first['senses'],
                                      [row['occurrence_id'] for row in prepared['occurrences']]])
        self.work = {'work_id': self.work_id, 'record': first,
                     'cards': [{'book_id': record['book_id'], 'card_id': record['card_id']}
                               for record in self.records]}
        self.write_jsonl(self.inventory / 'work-items.jsonl', [self.work])
        self.write_jsonl(self.inventory / 'records.jsonl', self.records)
        self.write_json(self.inventory / 'inventory.json', {
            'records': 2, 'unique_work_items': 1, 'unique_work_tokens': 2,
            'jsonl_sha256': {name: mr.sha256_file(self.inventory / name)
                            for name in ('records.jsonl', 'work-items.jsonl')}})
        parallel_row = {key: first['occurrences'][0][key] for key in mr._COMMON}
        parallel_row.update(index=0, physical_source=first['occurrences'][0]['physical_source'],
                            aligned_target_chunks=first['occurrences'][0].get('alignment_evidence', []))
        self.input_block = {'work_id': self.work_id, 'word': first['word'], 'senses': first['senses'],
                            'definition_source': first['definition_source'], 'occurrences': [parallel_row]}
        self.write_jsonl(self.parallel / 'shard-01.jsonl', [self.input_block])
        self.input_hash = mr.sha256_file(self.parallel / 'shard-01.jsonl')
        self.manifest = self.parallel / 'manifest.json'
        self.write_json(self.manifest, {'schema': 'semantic-parallel-manifest.v1',
            'source_sha256': mr.sha256_file(self.inventory / 'work-items.jsonl'),
            'new_occurrences': 1, 'existing_unit20_occurrences': 1,
            'shards': [{'id': 1, 'file': 'shard-01.jsonl', 'sha256': self.input_hash,
                        'blocks': 1, 'occurrences': 1}]})
        self.parallel_review = self.parallel / 'shard-01-reviewed.jsonl'
        self.decision = {'work_id': self.work_id, 'word': first['word'], 'index': 0,
                         'status': 'reviewed', 'sense_index': 1, 'reason': 'novel 修饰 idea，指新颖',
                         'input_shard_sha256': self.input_hash}
        self.write_jsonl(self.parallel_review, [self.decision])
        unit_row = {key: first['occurrences'][1][key] for key in mr._COMMON}; unit_row['index'] = 1
        self.write_json(self.unit / 'unit20-1.json', [{'work_id': self.work_id, 'word': first['word'],
                          'senses': first['senses'], 'occurrences': [unit_row]}])
        self.unit_review = self.unit / 'unit20-1-reviewed.json'
        self.unit_decision = {'schema': 'semantic-shard-review.v1', 'review_method': 'context-agent.v1',
            'input_sha256': mr.sha256_file(self.unit / 'unit20-1.json'),
            'words': [{'work_id': self.work_id, 'word': first['word'],
                       'assignments': [{'index': 1, 'status': 'ambiguous', 'sense_index': None,
                                        'reason': '需更多上下文'}]}]}
        self.write_json(self.unit_review, self.unit_decision)

    def write_json(self, path, value): path.write_text(json.dumps(value, ensure_ascii=False))

    def write_jsonl(self, path, values):
        path.write_text(''.join(mr.canonical(value) + '\n' for value in values))

    def merge(self, **kwargs):
        return mr.merge_reviews(self.inventory, self.manifest, self.output,
                               reviewed_shards=[self.parallel_review], **kwargs)

    def test_partial_merge_preserves_raw_context_and_reseals_each_edition(self):
        report = self.merge()
        self.assertEqual(report['considered_occurrences'], 1)
        self.assertEqual(report['not_yet_considered'], 1)
        self.assertFalse(report['semantic_coverage_complete'])
        self.assertEqual(report['physical_tokens_by_book'], {'redbook': 2, 'redbook2027': 2})
        merged = list(mr.jsonl(self.output / 'records.jsonl'))
        self.assertEqual(len(merged), 2)
        for old, new in zip(self.records, merged):
            self.assertEqual(new['senses'], old['senses'])
            self.assertEqual(new['definition_provenance'], old['definition_provenance'])
            self.assertEqual([mr._raw_hash(row) for row in new['occurrences']],
                             [mr._raw_hash(row) for row in old['occurrences']])
            self.assertEqual(new['occurrences'][1]['status'], 'unmatched')
            sf.prepare_record(new)
        self.assertNotEqual(merged[0]['occurrences'][0]['assignment_context_hash'],
                            merged[1]['occurrences'][0]['assignment_context_hash'])
        self.assertFalse(report['database_written'])

    def test_complete_means_all_considered_including_ambiguous_not_all_confirmed(self):
        report = self.merge(unit20_reviews=[self.unit_review], require_complete=True)
        self.assertTrue(report['semantic_coverage_complete'])
        self.assertEqual(report['considered_statuses'], {'reviewed': 1, 'ambiguous': 1})
        for record in mr.jsonl(self.output / 'records.jsonl'):
            self.assertIsNone(record['occurrences'][1]['sense_index'])

    def test_require_complete_rejects_missing_decisions_without_output(self):
        with self.assertRaisesRegex(ValueError, 'incomplete semantic coverage'):
            self.merge(require_complete=True)
        self.assertFalse(self.output.exists())

    def test_source_editions_cannot_carry_unreviewed_assignments_into_output(self):
        records = deepcopy(self.records)
        records[0]['occurrences'][1].update(status='reviewed', sense_index=0, reason='不是审核输出')
        self.write_jsonl(self.inventory / 'records.jsonl', records)
        report = json.loads((self.inventory / 'inventory.json').read_text())
        report['jsonl_sha256']['records.jsonl'] = mr.sha256_file(self.inventory / 'records.jsonl')
        self.write_json(self.inventory / 'inventory.json', report)
        with self.assertRaisesRegex(ValueError, 'edition source inventory.*pending'):
            self.merge()
        self.assertFalse(self.output.exists())

    def test_iterator_inputs_preserve_unit20_source_bindings(self):
        report = self.merge(unit20_reviews=iter([self.unit_review]), require_complete=True)
        bindings = {binding['file']: binding['sha256'] for binding in report['input_bindings']}
        source = self.unit / 'unit20-1.json'
        self.assertEqual(bindings[str(source)], mr.sha256_file(source))

    def test_repeated_merge_is_idempotent_and_does_not_mutate_source_files(self):
        paths = [self.inventory / name for name in ('inventory.json', 'records.jsonl', 'work-items.jsonl')]
        paths.extend([self.manifest, self.parallel_review, self.unit_review])
        before = {path: mr.sha256_file(path) for path in paths}
        first = self.merge(unit20_reviews=[self.unit_review], require_complete=True)
        second_dir = self.root / 'merged-again'
        second = mr.merge_reviews(self.inventory, self.manifest, second_dir,
            reviewed_shards=[self.parallel_review], unit20_reviews=[self.unit_review], require_complete=True)
        self.assertEqual(first['records_sha256'], second['records_sha256'])
        self.assertEqual((self.output / 'records.jsonl').read_bytes(),
                         (second_dir / 'records.jsonl').read_bytes())
        self.assertEqual({path: mr.sha256_file(path) for path in paths}, before)

    def test_stale_hash_unknown_index_status_sense_empty_reason_and_duplicates_fail(self):
        for change in ('hash', 'index', 'status', 'status-type', 'sense', 'reason', 'duplicate', 'unknown-field'):
            with self.subTest(change=change):
                decision = deepcopy(self.decision)
                if change == 'hash': decision['input_shard_sha256'] = '0' * 64
                if change == 'index': decision['index'] = 1
                if change == 'status': decision['status'] = 'suggested'
                if change == 'status-type': decision['status'] = {'reviewed': True}
                if change == 'sense': decision['sense_index'] = 99
                if change == 'reason': decision['reason'] = ' '
                if change == 'unknown-field': decision['matching_proposal'] = {'automatic_confirmation': True}
                values = [decision, decision] if change == 'duplicate' else [decision]
                self.write_jsonl(self.parallel_review, values)
                with self.assertRaises(ValueError): self.merge()
                self.assertFalse(self.output.exists())

    def test_mutated_input_even_with_updated_manifest_hash_is_rejected_by_raw_binding(self):
        block = deepcopy(self.input_block); block['occurrences'][0]['translation'] = '另一个译文'
        self.write_jsonl(self.parallel / 'shard-01.jsonl', [block])
        manifest = json.loads(self.manifest.read_text())
        manifest['shards'][0]['sha256'] = mr.sha256_file(self.parallel / 'shard-01.jsonl')
        self.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, 'differs from its source context'): self.merge()
        self.assertFalse(self.output.exists())

    def test_source_or_manifest_hash_mutation_fail_before_output(self):
        manifest = json.loads(self.manifest.read_text()); manifest['source_sha256'] = '0' * 64
        self.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, 'another work-items'): self.merge()
        self.assertFalse(self.output.exists())

    def test_full_alignment_validation_still_runs_for_each_final_source_record(self):
        # Source work and edition rows agree exactly, but the full alignment is
        # stale. The optimized source pass must not bypass final core checks.
        records = deepcopy(self.records)
        for record in records:
            record['occurrences'][0]['alignment']['translationHash'] = '0' * 64
        self.write_jsonl(self.inventory / 'records.jsonl', records)
        self.write_jsonl(self.inventory / 'work-items.jsonl', [{**self.work, 'record': records[0]}])
        report = json.loads((self.inventory / 'inventory.json').read_text())
        report['jsonl_sha256'] = {name: mr.sha256_file(self.inventory / name)
                                 for name in ('records.jsonl', 'work-items.jsonl')}
        self.write_json(self.inventory / 'inventory.json', report)
        manifest = json.loads(self.manifest.read_text())
        manifest['source_sha256'] = report['jsonl_sha256']['work-items.jsonl']
        self.write_json(self.manifest, manifest)
        with self.assertRaisesRegex(ValueError, 'hash|translation|alignment'):
            mr.merge_reviews(self.inventory, self.manifest, self.output)
        self.assertFalse(self.output.exists())

    def test_invalid_review_reason_names_exact_source_work_and_index(self):
        decision = {**self.decision, 'reason': None}
        self.write_jsonl(self.parallel_review, [decision])
        with self.assertRaises(ValueError) as error:
            self.merge()
        self.assertIn(str(self.parallel_review), str(error.exception))
        self.assertIn(self.work_id, str(error.exception))
        self.assertIn('index=0', str(error.exception))

    def test_edition_counts_and_inventory_metadata_changes_fail_closed(self):
        report_path = self.inventory / 'inventory.json'
        report = json.loads(report_path.read_text())
        report['physical_tokens_by_book'] = {'redbook': 3, 'redbook2027': 2}
        self.write_json(report_path, report)
        with self.assertRaisesRegex(ValueError, 'physical_tokens_by_book totals'):
            self.merge()
        self.assertFalse(self.output.exists())
        report.pop('physical_tokens_by_book')
        self.write_json(report_path, report)
        original = mr.sha256_file
        with patch.object(mr, 'sha256_file', side_effect=lambda path:
                          '0' * 64 if Path(path) == report_path else original(path)):
            with self.assertRaisesRegex(ValueError, 'changed during merge'):
                self.merge()
        self.assertFalse(self.output.exists())

    def test_progress_separates_source_review_and_edition_reconciliation(self):
        events = []
        self.merge(progress=lambda stage, **fields: events.append((stage, fields)))
        stages = [stage for stage, fields in events]
        self.assertLess(stages.index('source-work-items-complete'),
                        stages.index('review-coverage-verified'))
        self.assertLess(stages.index('review-coverage-verified'),
                        stages.index('edition-records-complete'))
        self.assertEqual(events[-1][1]['records_by_book'], {'redbook': 1, 'redbook2027': 1})

    def test_existing_output_is_never_replaced(self):
        self.output.mkdir(); marker = self.output / 'keep.txt'; marker.write_text('user file')
        with self.assertRaises(FileExistsError): self.merge()
        self.assertEqual(marker.read_text(), 'user file')

    def test_zero_occurrence_cards_need_no_semantic_review(self):
        records = deepcopy(self.records)
        for record in records:
            record.update(expected_occurrences=0, occurrences=[])
        first = records[0]
        work_id = mr.fingerprint([first['word'], first['definition_source'], first['senses'], []])
        work = {**self.work, 'work_id': work_id, 'record': first}
        self.write_jsonl(self.inventory / 'records.jsonl', records)
        self.write_jsonl(self.inventory / 'work-items.jsonl', [work])
        self.write_json(self.inventory / 'inventory.json', {'records': 2, 'unique_work_items': 1,
            'unique_work_tokens': 0, 'jsonl_sha256': {name: mr.sha256_file(self.inventory / name)
            for name in ('records.jsonl', 'work-items.jsonl')}})
        self.write_json(self.manifest, {'schema': 'semantic-parallel-manifest.v1',
            'source_sha256': mr.sha256_file(self.inventory / 'work-items.jsonl'),
            'new_occurrences': 0, 'existing_unit20_occurrences': 0, 'shards': []})
        report = mr.merge_reviews(self.inventory, self.manifest, self.output, require_complete=True)
        self.assertTrue(report['semantic_coverage_complete'])
        self.assertEqual(report['considered_occurrences'], 0)
        self.assertEqual(report['records'], 2)

    def test_final_move_failure_removes_only_owned_partial_output(self):
        original = mr.os.replace
        moved = []
        def replace(source, destination):
            moved.append(destination)
            if len(moved) == 2: raise OSError('fixture final move failure')
            return original(source, destination)
        with patch.object(mr.os, 'replace', side_effect=replace):
            with self.assertRaises(OSError): self.merge()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(mr.jsonl(self.inventory / 'records.jsonl')), self.records)

    def test_source_change_during_merge_rejects_staged_output(self):
        original = mr.sha256_file
        target = self.inventory / 'work-items.jsonl'
        calls = 0
        def sha(path):
            nonlocal calls
            if Path(path) == target:
                calls += 1
                if calls == 2: return '0' * 64
            return original(path)
        with patch.object(mr, 'sha256_file', side_effect=sha):
            with self.assertRaisesRegex(ValueError, 'changed during merge'): self.merge()
        self.assertFalse(self.output.exists())

    def test_unit20_wrong_input_hash_or_conflicting_overlap_fail(self):
        value = deepcopy(self.unit_decision); value['input_sha256'] = '0' * 64
        self.write_json(self.unit_review, value)
        with self.assertRaisesRegex(ValueError, 'stale source'): self.merge(unit20_reviews=[self.unit_review])
        self.write_json(self.unit_review, self.unit_decision)
        source = json.loads((self.unit / 'unit20-1.json').read_text())
        source[0]['occurrences'][0] = {key: self.records[0]['occurrences'][0][key] for key in mr._COMMON}
        source[0]['occurrences'][0]['index'] = 0
        self.write_json(self.unit / 'unit20-1.json', source)
        value = deepcopy(self.unit_decision)
        value['input_sha256'] = mr.sha256_file(self.unit / 'unit20-1.json')
        self.write_json(self.unit_review, value)
        with self.assertRaisesRegex(ValueError, 'duplicate unit20 source token'):
            self.merge(unit20_reviews=[self.unit_review])

    def test_accepted_prior_sample_conflict_is_rejected(self):
        value = deepcopy(self.records[0]); value['occurrences'][0].update(
            status='reviewed', sense_index=0, reason='先前错误确认')
        value['occurrences'][0] = sf.seal_reviewed_assignment(value, value['occurrences'][0])
        prior = self.root / 'accepted.json'; self.write_json(prior, [value])
        with self.assertRaises(mr.ReviewConflictError) as error:
            self.merge(accepted_records=prior)
        self.assertEqual(error.exception.conflicts[0]['work_id'], self.work_id)
        self.assertEqual(error.exception.conflicts[0]['index'], 0)
        self.assertEqual(error.exception.conflicts[0]['accepted_sample']['sense_index'], 0)
        self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
