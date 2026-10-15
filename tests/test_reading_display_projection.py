"""The display-only migration must replay approved bilingual source chunks."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import reading_display_projection as p
from anki_pipeline import sense_frequency as sf
from anki_pipeline.exam_usage_policy import producer_record, transform_record


class ReadingProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fixture = json.loads((Path(__file__).parent / 'fixtures/reading-display-projection-q30.json').read_text())
        self.entry = fixture['entry']
        self.row = self.entry['row']
        self.structured = self.root / 'structured/papers/kaoyan/2013-01.json'
        self.structured.parent.mkdir(parents=True)
        self.structured.write_text('{}')
        self.row['source_provenance']['sourcePathEvidence']['structuredPaperHash'] = p.sha(b'{}')
        self.row['display']['provenance']['raw_context_hash'] = p.sd._raw_context_hash(self.row)
        self.row['display'].pop('display_hash')
        self.row['display']['display_hash'] = p.sha(p.canonical(self.row['display']))
        replay = fixture['replay']
        context = replay['generated_option_context']
        self.sources = {'sentences': {row['id']: row for row in replay['replay_source_rows']},
            'completions': {replay['correct_completion']['sentenceId']: replay['correct_completion']},
            'options': {ref['sentenceId']: context for ref in context['optionSentenceRefs']},
            'watched': {self.structured: p.sha(self.structured.read_bytes())}}
        record = {key: deepcopy(self.entry[key]) for key in ('book_id', 'card_id', 'word', 'definition_provenance')}
        row = deepcopy(self.row)
        row.update(sense_index=0)
        record.update(definition_source='oxford', senses=[{'pos': 'n.', 'text': '理解'}], expected_occurrences=1)
        record['occurrences'] = [sf.seal_reviewed_assignment(record, row)]
        self.parent = sf.prepare_record(record)
        self.row = self.parent['occurrences'][0]
        self.entry.update(row=deepcopy(self.row), snapshot_id=self.parent['snapshot_id'])
        self.view = p.sd._display(self.row, p.sd._source_row(self.row, self.sources), [], self.sources,
                                 self.row['display']['provenance']['source_card_sha256'])
        self.item = {key: deepcopy(self.entry[key]) for key in ('book_id', 'card_id', 'word', 'snapshot_id', 'occurrence_id')}
        self.item.update(physical_row_sha256=p.physical_row_sha256(self.row),
                         raw_context_hash=p.sd._raw_context_hash(self.row),
                         old_display_hash=self.row['display']['display_hash'], new_display=self.view,
                         source_refs=deepcopy(self.view['derivation_payload']),
                         source_files={str(path): value for path, value in self.sources['watched'].items()})
        db = self.root / 'old.sqlite3'; db.write_bytes(b'immutable fixture source')
        self.sidecar = self.root / 'projection.json'
        document = {'schema': 'reading-option-display-projection.v1', 'projected': [self.item], 'blocked': [],
            'source_files': deepcopy(self.item['source_files']),
            'source_database': {'file': str(db), 'sha256': p.sha(db.read_bytes()), 'stat': p.stat_pin(db)},
            'books': {self.parent['book_id']: {'original': 1, 'projected': 1, 'blocked_original_retained': 0}}}
        document['projection_sha256'] = p.sha(p.canonical(document))
        self.sidecar.write_text(p.canonical(document))
        self.authority = {'sidecar': {'file': str(self.sidecar), 'sha256': p.sha(self.sidecar.read_bytes())},
                          'replay': {'exam_root': str(self.root), 'staging': str(self.root),
                                     'completion_path': str(self.structured)}}

    def approved(self):
        return p.ApprovedInputs(p._VALIDATED, self.row['paper_id'], deepcopy(self.sources))

    def test_authority_returns_detached_projection_and_rejects_changed_sidecar(self):
        first = p.get_projection(self.authority, self.parent['book_id'], self.parent['card_id'], self.row['occurrence_id'])
        first['new_display']['translation'] = 'changed caller copy'
        self.assertEqual(p.get_projection(self.authority, self.parent['book_id'], self.parent['card_id'], self.row['occurrence_id']), self.item)
        self.assertIsNone(p.get_projection(self.authority, self.parent['book_id'], self.parent['card_id'], 'absent'))
        self.sidecar.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'sidecar'):
            p.get_projection(self.authority, self.parent['book_id'], self.parent['card_id'], self.row['occurrence_id'])

    def test_replay_rejects_resealed_unapproved_translation_and_stale_parent(self):
        with patch.object(p, 'load_approved_inputs', return_value=self.approved()):
            self.assertEqual(p.replay_projection(self.authority, self.item, self.row,
                book_id=self.parent['book_id'], card_id=self.parent['card_id'],
                definition_provenance=self.parent['definition_provenance']), self.view)
            bad = deepcopy(self.item); bad['new_display']['translation'] += '伪造'
            with self.assertRaisesRegex(ValueError, 'authorized sidecar'):
                p.replay_projection(self.authority, bad, self.row, book_id=self.parent['book_id'],
                    card_id=self.parent['card_id'], definition_provenance=self.parent['definition_provenance'])
            old = deepcopy(self.row); old['reason'] += 'changed semantic reason'
            with self.assertRaisesRegex(ValueError, 'parent row'):
                p.replay_projection(self.authority, self.item, old, book_id=self.parent['book_id'],
                    card_id=self.parent['card_id'], definition_provenance=self.parent['definition_provenance'])

    def test_transform_preserves_physical_meaning_and_records_display_only_lineage(self):
        policy = {'reading_display_projection': {'authority': self.authority, 'entries': {self.row['occurrence_id']: self.item}}}
        before = deepcopy(self.parent)
        with patch.object(p, 'load_approved_inputs', return_value=self.approved()):
            result = transform_record(producer_record(self.parent), baseline_prepared=self.parent, policy=policy)
        child = sf.prepare_record(result['record'])
        self.assertEqual(child['expected_occurrences'], self.parent['expected_occurrences'])
        current = child['occurrences'][0]
        self.assertEqual(current['display'], self.view)
        for key in ('english', 'translation', 'english_hash', 'translation_hash', 'target_range',
                    'alignment', 'physical_source', 'source_provenance', 'status', 'reason', 'sense_id', 'assignment_context_hash'):
            self.assertEqual(current[key], self.row[key], key)
        entry = result['scope_ledger']['reading_display_projections'][0]
        self.assertEqual(entry['parent_snapshot_id'], self.parent['snapshot_id'])
        self.assertEqual(entry['projection'], self.item)
        self.assertEqual(entry['authority'], self.authority)
        self.assertEqual(entry['target_display_sha256'], self.view['display_hash'])
        self.assertEqual(self.parent, before)

    def test_transform_rejects_projection_for_another_snapshot_or_card(self):
        for key in ('snapshot_id', 'card_id'):
            bad = deepcopy(self.item); bad[key] = 'not-the-parent'
            policy = {'reading_display_projection': {'authority': self.authority, 'entries': {self.row['occurrence_id']: bad}}}
            with self.subTest(key=key), self.assertRaises(ValueError):
                transform_record(producer_record(self.parent), baseline_prepared=self.parent, policy=policy)

    def test_original_parent_display_rebinds_only_with_exact_replayed_lineage(self):
        from tests.test_ownership_history import fixture
        from anki_pipeline.ownership_history import bind_incoming_history, validate_history_content
        parent, transfer = fixture(self.parent)
        transfer['target_parent_row'] = deepcopy(self.row)
        transfer['target_parent_snapshot_id'] = parent['snapshot_id']
        policy = {'reading_display_projection': {'authority': self.authority, 'entries': {self.row['occurrence_id']: self.item}}}
        with patch.object(p, 'load_approved_inputs', return_value=self.approved()):
            transformed = transform_record(producer_record(parent), baseline_prepared=parent, policy=policy)
            current = sf.prepare_record(transformed['record'])
            result = bind_incoming_history(current, [transfer])
            self.assertEqual(result['ownership_history_unresolved'], [])
            history = result['occurrences'][0]['ownership_history'][0]
            refresh = history['matched_sense']['technical_rebinding']['display_refresh']
            self.assertEqual(refresh['method'], 'reading_display_projection.replay_projection')
            self.assertEqual(history['source_parent_row'], transfer['source_parent_row'])
            self.assertEqual(result['occurrences'][0]['display']['english'], self.view['english'])
            self.assertEqual(result['expected_occurrences'], 1)
            validate_history_content(history)
            for kind in ('missing', 'duplicate', 'stale'):
                bad = deepcopy(current)
                entries = bad['exam_usage_policy']['reading_display_projections']
                if kind == 'missing': entries.clear()
                elif kind == 'duplicate': entries.append(deepcopy(entries[0]))
                else: entries[0]['parent_display_sha256'] = '0' * 64
                with self.subTest(kind=kind):
                    denied = bind_incoming_history(bad, [transfer])
                    self.assertEqual(len(denied['ownership_history_unresolved']), 1)
                    self.assertEqual(denied['ownership_history_unresolved'][0]['transfer'], transfer)

    def test_independent_replay_rejects_a_self_resealed_forged_bilingual_view(self):
        item = deepcopy(self.item)
        derived = item['new_display']['derivation_payload']
        derived['translationZh'] += '伪造审核译文'
        english, translation, _, _ = p.sd._approved_derived_view(self.row, derived, 'option_context')
        view = item['new_display']
        view['translation'] = translation
        view['translation_hash'] = p.sha(translation)
        view['alignment'] = p.sd._project_alignment(self.row, english, translation, view['alignment_sources'], sentence_fallback=True)
        view['provenance']['derivation_sha256'] = p.sha(json.dumps(derived, ensure_ascii=False, sort_keys=True))
        view.pop('display_hash'); view['display_hash'] = p.sha(p.canonical(view))
        item['source_refs'] = deepcopy(derived)
        p.sd.validate_display(view, self.row, self.parent['definition_provenance'])
        with self.assertRaisesRegex(ValueError, 'independently replayed'):
            p.validate_projection(item, self.row, book_id=self.parent['book_id'], card_id=self.parent['card_id'],
                                  definition_provenance=self.parent['definition_provenance'], inputs=self.approved())


if __name__ == '__main__':
    unittest.main()
