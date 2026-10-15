import copy
import unittest

from anki_pipeline import sense_frequency as sf
from anki_pipeline.exam_usage_policy import transform_record, producer_record, assignment_pin, _verified_cloze_reversal, dictionary_name_zh
from anki_pipeline.exam_frequency import exclude_cloze_option
from tests.test_sense_frequency import record, reseal


class UsagePolicyTests(unittest.TestCase):
    def test_dictionary_name_uses_exact_validated_identity_and_preserves_unknown_name(self):
        self.assertEqual(dictionary_name_zh({'name': 'Oxford Advanced Learner’s Dictionary',
            'source_ref_pin': {'dictionary': 'Oxford Advanced Learner’s Dictionary'}}), '牛津高阶英语词典')
        self.assertEqual(dictionary_name_zh({'name': 'Oxford Advanced Learner’s English–Chinese Dictionary',
            'source_ref_pin': {'dictionary': 'oald10'}}), '牛津高阶英汉双解词典')
        self.assertEqual(dictionary_name_zh({'name': 'Some other dictionary'}), 'Some other dictionary')

    def test_rehome_cloze_reversal_requires_exact_sealed_answers_and_untouched_target(self):
        english = 'We adjust our training program.'
        answers = [{'start': 3, 'end': 9, 'number': 13, 'word': 'adjust'}]
        source_hash = sf._sha('We 13 our training program.')
        row = {'english': english, 'target_range': [14, 22],
            'source_provenance': {'sourceHash': source_hash, 'sourceBlockIds': ['paper:b-1']},
            'display': {'provenance': {'source_cloze_answers': answers}}}
        proof = {'verified': True, 'answer_replacements': answers, 'source_hash': source_hash,
            'source_block_ids': ['paper:b-1'], 'target_is_answer_replacement': False,
            'original_sentence_unique_in_verified_paragraph': True,
            'reversed_answer_sentence': 'We 13 our training program.',
            'untouched_target_range_in_reversed_sentence': [10, 18],
            'original_source_target_text': 'training'}
        self.assertTrue(_verified_cloze_reversal(row, proof))
        for key, value in (('source_hash', sf._sha('other')), ('source_block_ids', ['other']),
                ('answer_replacements', [{'start': 3, 'end': 9, 'number': 12, 'word': 'adjust'}]),
                ('reversed_answer_sentence', 'We 12 our training program.'),
                ('untouched_target_range_in_reversed_sentence', [9, 17]),
                ('target_is_answer_replacement', True), ('original_sentence_unique_in_verified_paragraph', False)):
            with self.subTest(key=key):
                self.assertFalse(_verified_cloze_reversal(row, {**proof, key: value}))
        overlapping = copy.deepcopy(row)
        overlapping['display']['provenance']['source_cloze_answers'] = [{'start': 14, 'end': 22,
            'number': 13, 'word': 'training'}]
        self.assertFalse(_verified_cloze_reversal(overlapping, {**proof,
            'answer_replacements': overlapping['display']['provenance']['source_cloze_answers']}))

    def test_old_reading_number_and_explicit_section_never_mistaken_for_cloze(self):
        self.assertFalse(exclude_cloze_option({'paperId': 'kaoyan:2000-01',
            'kind': 'answer_option', 'context': {'questionId': 'kaoyan:2000-01:q-11-1'}}))
        self.assertFalse(exclude_cloze_option({'paperId': 'kaoyan:2022-01',
            'kind': 'answer_option', 'context': {'questionId': 'kaoyan:2022-01:q-11-1', 'sectionKind': 'reading'}}))
        self.assertTrue(exclude_cloze_option({'paperId': 'kaoyan:2000-01',
            'kind': 'answer_option', 'context': {'questionId': 'kaoyan:2000-01:q-11-1', 'sectionKind': 'cloze'}}))
    def test_cloze_options_filtered_with_lossless_source_ledger(self):
        value = record()
        value['occurrences'][0]['sentence_id'] = 'kaoyan:2022-01:q-3-1:A:new:0'
        value['occurrences'][0]['source_provenance']['sourcePathEvidence'] = {
            'kind': 'answer_option', 'questionId': 'kaoyan:2022-01:q-3-1', 'optionLabel': 'A'}
        value = reseal(value)
        baseline = sf.prepare_record(value)
        result = transform_record(value, baseline_prepared=baseline)
        new = sf.prepare_record(result['record'])
        self.assertEqual(new['expected_occurrences'], 1)
        ledger = result['scope_ledger']
        self.assertEqual(ledger['excluded'][0]['occurrence'], baseline['occurrences'][
            next(i for i, row in enumerate(baseline['occurrences']) if row['sentence_id'].endswith(':A:new:0'))])
        self.assertEqual(new['snapshot_id'], ledger['new_snapshot_id'])
        self.assertEqual(baseline, sf.prepare_record(value))

    def test_wrong_lemma_exclusion_needs_unchanged_source_and_authority(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        item = {'occurrence_id': row['occurrence_id'], 'occurrence': row,
                'exclusion_kind': 'wrong_lemma', 'authority': {'run': 'reviewed'}, 'ownership': {'word': 'novelty'}}
        result = transform_record(value, baseline_prepared=old, excluded_occurrences=[item])
        self.assertEqual(len(result['record']['occurrences']), 1)
        bad = copy.deepcopy(item); bad['occurrence']['english_hash'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'stale'):
            transform_record(value, baseline_prepared=old, excluded_occurrences=[bad])

    def test_reading_usage_keeps_wrong_option_and_semantic_binding(self):
        value = record(); row = value['occurrences'][0]
        row['sentence_id'] = 'kaoyan:2022-01:q-29-1:B:new:0'
        row['source_provenance']['sourcePathEvidence'] = {
            'kind': 'answer_option', 'questionId': 'kaoyan:2022-01:q-29-1', 'optionLabel': 'B'}
        value = reseal(value); old = sf.prepare_record(value)
        revised = transform_record(value, baseline_prepared=old, policy={'options': {
            row['sentence_id']: {'isCorrectCandidate': False, 'candidateOptionLabel': 'B'}}})
        candidate = next(row for row in revised['record']['occurrences'] if row['sentence_id'].endswith(':B:new:0'))
        self.assertEqual(candidate['usage']['reading_candidate']['correctness'], 'incorrect')
        original = next(row for row in old['occurrences'] if row['sentence_id'].endswith(':B:new:0'))
        self.assertEqual(candidate['assignment_context_hash'], original['assignment_context_hash'])

    def test_residual_decision_uses_current_assignment_pin_and_full_dictionary(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        decision = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'reviewed',
            'sense_id': row['sense_id'], 'reason': 'context and full definition',
            'evidence_ids': ['native:sense'], 'dictionary_explanation': {'english_definition': 'a story'}}
        result = transform_record(value, baseline_prepared=old, residual_decisions=[decision])
        self.assertEqual(result['scope_ledger']['semantic_decisions'], [decision])
        bad = copy.deepcopy(decision); bad['old_assignment_sha256'] = 'wrong'
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            transform_record(value, baseline_prepared=old, residual_decisions=[bad])

    def test_source_pinned_append_preserves_semantic_ordinals_and_evidence(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        pin = {'provider': 'native', 'source_entry_id': 'entry', 'raw_sha256': sf._sha('native source'),
            'sense_id': '2', 'source_headword': 'novel', 'dictionary': 'fixture'}
        registry = [{'source_ref': pin, 'sense_ref': sf._sha('native new sense'),
            'english': 'unusual', 'chinese': '不同寻常的',
            'native_definition_valid': True, 'raw_entry_valid': True}]
        decision = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'reviewed',
            'sense_id': None, 'reason': 'new exact dictionary range', 'evidence_ids': ['native:new'],
            'dictionary_explanation': {'source': 'native', 'name': '字典', 'version': '1',
                'exact_entry': 'novel', 'sense': '2', 'english_definition': 'unusual',
                'source_ref_pin': pin,
                'original_chinese': '不同寻常的', 'grammatical_scope': 'adjective', 'context_reason': 'modifies idea'},
            'dictionary_source_pins': [pin],
            'new_sense': {'pos': 'adj.', 'text': '不同寻常的', 'original_english': 'unusual',
                'original_chinese': '不同寻常的', 'translation_kind': 'original'}}
        result = transform_record(value, baseline_prepared=old, residual_decisions=[decision],
            policy={'verified_dictionary_sources': registry})
        child = sf.prepare_record(result['record'])
        self.assertEqual(len(child['senses']), 3)
        revised = next(r for r in child['occurrences'] if r['occurrence_id'] == row['occurrence_id'])
        self.assertEqual(revised['sense_id'], child['senses'][2]['sense_id'])
        self.assertEqual(revised['semantic_review'], decision)
        for previous in old['occurrences']:
            current = next(r for r in child['occurrences'] if r['occurrence_id'] == previous['occurrence_id'])
            self.assertEqual(current['english_hash'], previous['english_hash'])
            self.assertEqual(current['target_range'], previous['target_range'])
        bad = copy.deepcopy(decision); bad['new_sense']['translation_kind'] = 'reviewed_translation'
        with self.assertRaises(ValueError):
            transform_record(value, baseline_prepared=old, residual_decisions=[bad])

    def test_nested_translation_search_is_validated_without_rewriting_review(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        pin = {'provider': 'native', 'source_entry_id': 'entry', 'raw_sha256': sf._sha('native source'),
            'sense_id': '2', 'source_headword': 'novel', 'dictionary': 'fixture'}
        registry = [{'source_ref': pin, 'sense_ref': sf._sha('native new sense'),
            'english': 'unusual', 'chinese': '',
            'native_definition_valid': True, 'raw_entry_valid': True}]
        search = {'queries': ['novel unusual bilingual definition'], 'source_pins': [pin]}
        decision = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'reviewed',
            'sense_id': None, 'reason': 'full dictionary meaning reviewed after bilingual search',
            'evidence_ids': ['native:new'],
            'dictionary_explanation': {'source': 'native', 'name': '字典', 'version': '1',
                'exact_entry': 'novel', 'sense': '2', 'english_definition': 'unusual',
                'source_ref_pin': pin, 'original_chinese': '',
                'grammatical_scope': 'adjective', 'context_reason': 'modifies idea',
                'bilingual_search': search},
            'dictionary_source_pins': [pin],
            'new_sense': {'pos': 'adj.', 'text': '不同寻常的', 'original_english': 'unusual',
                'original_chinese': '', 'translation_kind': 'reviewed_translation'}}
        original = copy.deepcopy(decision)
        result = transform_record(value, baseline_prepared=old, residual_decisions=[decision],
            policy={'verified_dictionary_sources': registry})
        child = sf.prepare_record(result['record'])
        current = next(r for r in child['occurrences'] if r['occurrence_id'] == row['occurrence_id'])
        self.assertEqual(decision, original)
        self.assertEqual(current['semantic_review'], original)
        evidence = result['scope_ledger']['new_definitions'][0]['validated_source_evidence']
        self.assertEqual(evidence['bilingual_search']['queries'], search['queries'])
        missing = copy.deepcopy(decision)
        del missing['dictionary_explanation']['bilingual_search']
        with self.assertRaisesRegex(ValueError, 'bilingual_search'):
            transform_record(value, baseline_prepared=old, residual_decisions=[missing],
                policy={'verified_dictionary_sources': registry})
        for update in ({'queries': []}, {'source_pins': []},
                {'source_pins': [{**pin, 'raw_sha256': sf._sha('wrong source')}]}):
            bad = copy.deepcopy(decision)
            bad['dictionary_explanation']['bilingual_search'].update(update)
            with self.subTest(update=update), self.assertRaises(ValueError):
                transform_record(value, baseline_prepared=old, residual_decisions=[bad],
                    policy={'verified_dictionary_sources': registry})

    def test_cloze_filter_keeps_complete_old_wrong_lemma_proof_and_mask(self):
        value = record()
        value['occurrences'][0]['sentence_id'] = 'kaoyan:2022-01:q-3-1:A:new:0'
        value['occurrences'][0]['source_provenance']['sourcePathEvidence'] = {
            'kind': 'answer_option', 'questionId': 'kaoyan:2022-01:q-3-1', 'optionLabel': 'A'}
        value = reseal(value); old = sf.prepare_record(value)
        row = next(r for r in old['occurrences'] if r['sentence_id'].endswith(':A:new:0'))
        item = {'occurrence_id': row['occurrence_id'], 'occurrence': row,
            'exclusion_kind': 'wrong_lemma', 'authority': {'complete_old_reason': '旧核对全文'},
            'ownership': {'word': 'novelty'}}
        result = transform_record(value, baseline_prepared=old, excluded_occurrences=[item])
        excluded = result['scope_ledger']['excluded'][0]
        self.assertEqual(excluded['exclusion_kind'], 'cloze_option')
        self.assertEqual(excluded['prior_exclusion'], item)
        self.assertEqual(excluded['authority'], item['authority'])
        self.assertEqual(result['scope_ledger']['prior_wrong_lemma_ids'], [row['occurrence_id']])
        self.assertEqual(result['record']['exam_usage_policy']['excluded'][0]['prior_exclusion'], item)

    def test_common_review_survives_prepare_and_renders_one_counted_group(self):
        from anki_pipeline.sense_groups import display_report
        value = record()
        value['senses'] = [{'pos': 'n.', 'text': '小说'}, {'pos': 'n.', 'text': '长篇小说'}]
        value = reseal(value); old = sf.prepare_record(value); row = old['occurrences'][0]
        ids = [sense['sense_id'] for sense in old['senses']]
        decision = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'group',
            'reason': '两条完整词典释义均指长篇虚构叙事', 'evidence_ids': ['sense-a', 'sense-b'],
            'dictionary_explanation': {'english_definition': 'a long printed story'},
            'candidate_sense_ids': ids, 'common_meaning': '长篇虚构小说',
            'usage_scope': '可数名词，长篇虚构叙事',
            'candidate_explanations': [{'sense_id': identity, 'quote': 'a long printed story'} for identity in ids]}
        result = transform_record(value, baseline_prepared=old, residual_decisions=[decision])
        child = sf.prepare_record(result['record'])
        view = display_report(sf.report_from_record(child))
        self.assertEqual(view['total'], 2)
        self.assertEqual(len(view['senses']), 1)
        self.assertEqual(view['senses'][0]['count'], 2)
        self.assertEqual(view['pending_count'], 0)
        self.assertIn('sf-sense', sf.render_report(view))

    def test_broad_review_requires_explicit_flag_and_selected_candidate(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        base = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'broad',
            'sense_id': row['sense_id'], 'reason': '完整上下文仍只能确认此广义',
            'evidence_ids': ['native:sense'], 'dictionary_explanation': {'english_definition': 'a story'},
            'broad_flag': True, 'candidate_sense_ids': [row['sense_id']]}
        for update in ({'broad_flag': False}, {'candidate_sense_ids': []}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'broad'):
                transform_record(value, baseline_prepared=old, residual_decisions=[{**base, **update}])
        child = sf.prepare_record(transform_record(value, baseline_prepared=old,
            residual_decisions=[base])['record'])
        self.assertIn('上下文仅能确认广义', sf.render_report(sf.report_from_record(child)))

    def test_broad_assignment_can_be_separate_from_finer_candidates(self):
        value = record(); old = sf.prepare_record(value); row = old['occurrences'][0]
        finer = next(sense['sense_id'] for sense in old['senses'] if sense['sense_id'] != row['sense_id'])
        decision = {**{key: old[key] for key in ('book_id', 'card_id', 'snapshot_id')},
            **{key: row[key] for key in ('occurrence_id', 'english_hash', 'target_range')},
            'old_assignment_sha256': assignment_pin(old, row), 'status': 'broad',
            'sense_id': row['sense_id'], 'reason': '广义已确认，但无法在几个细义之间继续区分',
            'evidence_ids': ['native:broader-sense'],
            'dictionary_explanation': {'english_definition': 'original broader definition'},
            'broad_flag': True, 'candidate_sense_ids': [finer]}
        result = transform_record(value, baseline_prepared=old, residual_decisions=[decision])
        child = sf.prepare_record(result['record'])
        current = next(r for r in child['occurrences'] if r['occurrence_id'] == row['occurrence_id'])
        self.assertEqual(current['sense_id'], decision['sense_id'])
        self.assertEqual(current['semantic_review'], decision)
        self.assertEqual(set(current['broad_match']['candidate_sense_ids']), {finer, decision['sense_id']})
        from anki_pipeline.sense_groups import display_report
        self.assertEqual(display_report(sf.report_from_record(child))['total'], 2)
        for update in ({'sense_id': 'not-a-real-sense'}, {'candidate_sense_ids': ['unknown']},
                {'candidate_sense_ids': [finer, finer]}, {'broad_flag': False}):
            with self.subTest(update=update), self.assertRaisesRegex(ValueError, 'broad'):
                transform_record(value, baseline_prepared=old, residual_decisions=[{**decision, **update}])
