"""Conservative suggestions must not become confirmed semantic assignments."""
import copy
import hashlib
import unittest

from anki_pipeline import sense_matching as sm
from anki_pipeline.sense_frequency import seal_reviewed_assignment
from tests.test_sense_frequency import record


def example(english='A novel idea.', translation='一个新颖的想法。', target=(2, 7),
            chinese=(2, 5), aligned=(2, 7)):
    return {
        'english': english, 'english_hash': hashlib.sha256(english.encode()).hexdigest(),
        'translation': translation, 'target_range': list(target),
        'translation_ranges': [list(chinese)],
        'alignment_evidence': [{'english_range': list(aligned),
                                'translation_ranges': [list(chinese)]}],
    }


SENSES = [{'pos': 'n.', 'text': '（长篇）小说'},
          {'pos': 'adj.', 'text': '新颖的；与众不同的；珍奇的'}]


class SenseMatchingTests(unittest.TestCase):
    def test_unique_exact_aligned_term_is_only_a_suggestion(self):
        proposal = sm.propose_match(SENSES, example())
        self.assertEqual(proposal['status'], 'suggested')
        self.assertEqual(proposal['candidate_sense_indices'], [1])
        self.assertFalse(proposal['automatic_confirmation'])
        self.assertEqual(proposal['candidates'][0]['evidence'][0]['translation_text'], '新颖的')

    def test_words_elsewhere_in_sentence_cannot_match(self):
        occurrence = example(translation='一本小说带来一个新颖的想法。', chinese=(8, 11))
        proposal = sm.propose_match(SENSES, occurrence)
        self.assertEqual(proposal['candidate_sense_indices'], [1])

    def test_missing_alignment_does_not_fall_back_to_whole_sentence(self):
        occurrence = example(); occurrence.pop('alignment_evidence')
        proposal = sm.propose_match(SENSES, occurrence)
        self.assertEqual(proposal['status'], 'unmatched')
        self.assertEqual(proposal['candidate_sense_indices'], [])
        self.assertEqual(proposal['reason_code'], 'missing_alignment')

    def test_whole_sentence_alignment_does_not_suggest(self):
        occurrence = example(aligned=(0, 13))
        self.assertEqual(sm.propose_match(SENSES, occurrence)['reason_code'], 'broad_alignment')

    def test_two_glosses_in_target_chunk_remain_ambiguous(self):
        occurrence = example(translation='新颖的小说', chinese=(0, 5))
        proposal = sm.propose_match(SENSES, occurrence)
        self.assertEqual(proposal['status'], 'ambiguous')
        self.assertEqual(proposal['candidate_sense_indices'], [0, 1])

    def test_same_gloss_in_two_senses_is_not_broken_by_sense_order(self):
        senses = [{'pos': 'n.', 'text': '记录；会议记录'}, {'pos': 'v.', 'text': '记录；写下'}]
        occurrence = example(translation='记录', chinese=(0, 2))
        self.assertEqual(sm.propose_match(senses, occurrence)['candidate_sense_indices'], [0, 1])

    def test_single_sense_without_lexical_evidence_is_not_assumed_correct(self):
        self.assertEqual(sm.propose_match([SENSES[0]], example())['status'], 'unmatched')

    def test_ranges_are_codepoints_and_discontinuous_ranges_never_join_into_new_terms(self):
        occurrence = example(translation='😀新被改颖', chinese=(1, 2))
        occurrence['translation_ranges'] = [[1, 2], [4, 5]]
        occurrence['alignment_evidence'][0]['translation_ranges'] = [[1, 2], [4, 5]]
        self.assertEqual(sm.propose_match(SENSES, occurrence)['candidate_sense_indices'], [])

    def test_stale_hash_invalid_range_and_mismatched_alignment_are_rejected(self):
        for mutation in ('hash', 'range', 'alignment'):
            with self.subTest(mutation=mutation):
                occurrence = example()
                if mutation == 'hash': occurrence['english_hash'] = '0' * 64
                if mutation == 'range': occurrence['target_range'] = [False, 7]
                if mutation == 'alignment':
                    occurrence['alignment_evidence'][0]['translation_ranges'] = [[0, 2]]
                with self.assertRaises(ValueError): sm.propose_match(SENSES, occurrence)

    def test_verified_full_alignment_payload_can_supply_evidence(self):
        occurrence = example(); occurrence.pop('alignment_evidence')
        occurrence['translation_alignment'] = {
            'schema': 'codex-sentence-alignment.v1',
            'englishHash': occurrence['english_hash'],
            'translationHash': hashlib.sha256(occurrence['translation'].encode()).hexdigest(),
            'alignments': [{'en': [2, 7], 'zh': [[2, 5]], 'relation': 'equivalent'}],
        }
        self.assertEqual(sm.propose_match(SENSES, occurrence)['candidate_sense_indices'], [1])
        occurrence['translation_alignment']['translationHash'] = '0' * 64
        with self.assertRaises(ValueError): sm.propose_match(SENSES, occurrence)

    def test_canonical_alignment_is_validated_and_finest_scope_differs_from_display_union(self):
        occurrence = example(); occurrence.pop('alignment_evidence')
        occurrence['translation_ranges'] = [[0, 8], [2, 5]]
        occurrence['alignment'] = {
            'schema': 'codex-sentence-alignment.v1',
            'englishHash': occurrence['english_hash'],
            'translationHash': hashlib.sha256(occurrence['translation'].encode()).hexdigest(),
            'alignments': [{'en': [0, 13], 'zh': [[0, 8]], 'relation': 'equivalent'},
                           {'en': [2, 7], 'zh': [[2, 5]], 'relation': 'equivalent'}],
        }
        proposal = sm.propose_match(SENSES, occurrence)
        self.assertEqual(proposal['candidate_sense_indices'], [1])
        self.assertEqual(proposal['alignment_scope']['translation_ranges'], [[2, 5]])
        self.assertEqual(occurrence['translation_ranges'], [[0, 8], [2, 5]])
        occurrence['alignment']['translationHash'] = '0' * 64
        with self.assertRaises(ValueError): sm.propose_match(SENSES, occurrence)

    def test_exact_implicit_target_cannot_borrow_equivalent_evidence_from_parent_chunk(self):
        occurrence = example(); occurrence.pop('alignment_evidence')
        occurrence['alignment'] = {
            'schema': 'codex-sentence-alignment.v1',
            'englishHash': occurrence['english_hash'],
            'translationHash': hashlib.sha256(occurrence['translation'].encode()).hexdigest(),
            'alignments': [{'en': [2, 12], 'zh': [[2, 5]], 'relation': 'equivalent'},
                           {'en': [2, 7], 'zh': [], 'relation': 'implicit', 'note': '隐含'}],
        }
        self.assertEqual(sm.propose_match(SENSES, occurrence)['reason_code'], 'untranslated_target')

    def test_long_scope_and_ambiguous_equally_small_alignments_are_not_used(self):
        occurrence = example(translation='这是非常长的背景信息，与此处这个词的语义归属没有明确关系新颖的',
                             chinese=(0, 32))
        # Use exact current string length rather than a guessed offset.
        occurrence['translation_ranges'] = [[0, len(occurrence['translation'])]]
        occurrence['alignment_evidence'][0]['translation_ranges'] = occurrence['translation_ranges']
        self.assertEqual(sm.propose_match(SENSES, occurrence)['reason_code'], 'broad_translation')
        occurrence = example()
        occurrence['alignment_evidence'] = [
            {'english_range': [1, 7], 'translation_ranges': [[2, 5]]},
            {'english_range': [2, 8], 'translation_ranges': [[2, 5]]},
        ]
        self.assertEqual(sm.propose_match(SENSES, occurrence)['reason_code'], 'ambiguous_alignment')

    def test_linguistic_qualifier_is_visible_in_evidence_and_never_confirms(self):
        occurrence = example(translation='小说', chinese=(0, 2))
        proposal = sm.propose_match(SENSES, occurrence)
        evidence = proposal['candidates'][0]['evidence'][0]
        self.assertEqual(evidence['gloss_atom'], '小说')
        self.assertEqual(evidence['source_gloss'], '（长篇）小说')
        self.assertTrue(evidence['qualifier_removed'])

    def test_record_annotation_preserves_original_review_status_and_values(self):
        original = record()
        original['occurrences'][0].update(status='unmatched', sense_index=None, reason='待核对')
        original['occurrences'][0].pop('reviewed_sense_id')
        original['occurrences'][0].pop('assignment_context_hash')
        before = copy.deepcopy(original)
        proposed = sm.propose_record(original)
        self.assertEqual(original, before)
        for source, output in zip(original['occurrences'], proposed['occurrences']):
            self.assertEqual(source, {key: value for key, value in output.items()
                                      if key != 'matching_proposal'})
            self.assertFalse(output['matching_proposal']['automatic_confirmation'])

    def test_evaluation_deduplicates_same_physical_token_across_book_versions(self):
        value = record()
        first, second = value['occurrences']
        first['translation_ranges'] = [[6, 8]]
        first['alignment_evidence'] = [{'english_range': first['target_range'],
                                        'translation_ranges': first['translation_ranges']}]
        second['translation_ranges'] = [[2, 4]]
        second['alignment_evidence'] = [{'english_range': second['target_range'],
                                         'translation_ranges': second['translation_ranges']}]
        value['occurrences'] = [seal_reviewed_assignment(value, row) for row in value['occurrences']]
        other = copy.deepcopy(value); other['book_id'] = 'redbook'
        other['occurrences'] = [seal_reviewed_assignment(other, row) for row in other['occurrences']]
        result = sm.evaluate_reviewed_records([value, other])
        self.assertEqual(result['counts']['reviewed_tokens'], 2)
        self.assertEqual(result['counts']['single_candidate_tokens'], 2)
        self.assertEqual(result['single_candidate_agreement'], 1)
        self.assertFalse(result['automatic_confirmation'])

    def test_conflicting_review_across_versions_cannot_be_hidden_by_calibration_dedup(self):
        value = record()
        other = copy.deepcopy(value); other['book_id'] = 'redbook'
        other['occurrences'][0]['sense_index'] = 0
        other['occurrences'] = [seal_reviewed_assignment(other, row) for row in other['occurrences']]
        with self.assertRaisesRegex(ValueError, 'conflicting reviews'):
            sm.evaluate_reviewed_records([value, other])

    def strict_example(self, translation='新颖的', zh=(0, 3)):
        occurrence = example(translation=translation, chinese=zh)
        occurrence['alignment'] = {
            'schema': 'codex-sentence-alignment.v1', 'englishHash': occurrence['english_hash'],
            'translationHash': hashlib.sha256(translation.encode()).hexdigest(),
            'alignments': [{'en': [2, 7], 'zh': [list(zh)], 'relation': 'equivalent'}]}
        return occurrence

    def test_exact_eligibility_requires_entire_unmodified_gloss_and_is_never_confirmation(self):
        result = sm.propose_match(SENSES, self.strict_example(), headword='novel')['exact_match_eligibility']
        self.assertTrue(result['eligible'])
        self.assertEqual(result['candidate_sense_index'], 1)
        self.assertFalse(result['automatic_confirmation'])
        for text in ('新颖', '真正新颖的'):
            occurrence = self.strict_example(text, (0, len(text)))
            self.assertFalse(sm.propose_match(SENSES, occurrence, headword='novel')['exact_match_eligibility']['eligible'])
        self.assertFalse(sm.propose_match(SENSES, self.strict_example('小说', (0, 2)), headword='novel')[
            'exact_match_eligibility']['eligible'])

    def test_exact_eligibility_rejects_parent_scope_shared_translation_and_function_gloss(self):
        occurrence = self.strict_example()
        occurrence['alignment']['alignments'].append(
            {'en': [2, 12], 'zh': [[0, 3]], 'relation': 'equivalent'})
        self.assertFalse(sm.propose_match(SENSES, occurrence, headword='novel')['exact_match_eligibility']['eligible'])
        occurrence = self.strict_example('我们', (0, 2))
        self.assertFalse(sm.propose_match([{'pos': 'pron.', 'text': '我们'}], occurrence, headword='novel')[
            'exact_match_eligibility']['eligible'])
        occurrence = self.strict_example()
        occurrence['alignment']['alignments'][0]['en'] = [2, 12]
        self.assertFalse(sm.propose_match(SENSES, occurrence, headword='novel')['exact_match_eligibility']['eligible'])

    def test_real_pos_mismatches_cannot_be_confirmed_or_enter_exact_eligibility_queue(self):
        # Source cases: 2006-01:b-11-6:3 charging, 2011-02:b-13-5:1 right,
        # and 2025-02:b-1-5:1 interested. Chinese alone can select wrong POS.
        cases = [
            ('charge', 'He is charging that the casino knew.', '他指控赌场知情。', 'charging', '指控',
             [{'pos': 'n.', 'text': '指控；控告'}, {'pos': 'v.', 'text': '控告；起诉'}]),
            ('right', 'Get the right answer.', '找到正确的答案。', 'right', '正确',
             [{'pos': 'adj.', 'text': '正确的；真正的；真实的'},
              {'pos': 'n.', 'text': '正当；公正；正义；正确'}]),
            ('interest', 'Psychologists have been interested in this question.', '心理学家关注这个问题。',
             'interested', '关注', [{'pos': 'n.', 'text': '兴趣；关注'},
                                  {'pos': 'v.', 'text': '使感兴趣；使关注'}]),
        ]
        for headword, english, translation, target, chinese, senses in cases:
            with self.subTest(headword=headword):
                en_start, zh_start = english.index(target), translation.index(chinese)
                occurrence = example(english, translation, (en_start, en_start + len(target)),
                                     (zh_start, zh_start + len(chinese)),
                                     (en_start, en_start + len(target)))
                occurrence['alignment'] = {
                    'schema': 'codex-sentence-alignment.v1', 'englishHash': occurrence['english_hash'],
                    'translationHash': hashlib.sha256(translation.encode()).hexdigest(),
                    'alignments': [{'en': occurrence['target_range'],
                                    'zh': occurrence['translation_ranges'], 'relation': 'equivalent'}]}
                proposal = sm.propose_match(senses, occurrence, headword=headword)
                self.assertNotEqual(proposal['status'], 'reviewed')
                self.assertFalse(proposal['automatic_confirmation'])
                self.assertFalse(proposal['exact_match_eligibility']['eligible'])

    def test_composite_headwords_keep_identical_senses_separate_and_limit_candidate_source(self):
        value = record(); value['word'] = 'okay/OK'
        value['senses'] = [{'pos': 'n.', 'text': '允许'}, {'pos': 'n.', 'text': '允许'}]
        value['definition_provenance']['components'] = [
            {'headword': 'okay', 'sense_start': 0, 'sense_count': 1},
            {'headword': 'OK', 'sense_start': 1, 'sense_count': 1}]
        english, translation = 'An okay is followed by an OK.', '一份允许接着另一份允许。'
        spans = [[english.index(token), english.index(token) + len(token)] for token in ('okay', 'OK')]
        chinese = [[translation.index('允许'), translation.index('允许') + 2],
                   [translation.rindex('允许'), translation.rindex('允许') + 2]]
        alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': hashlib.sha256(english.encode()).hexdigest(),
                     'translationHash': hashlib.sha256(translation.encode()).hexdigest(),
                     'alignments': [{'en': en, 'zh': [zh], 'relation': 'equivalent'}
                                    for en, zh in zip(spans, chinese)]}
        for row, en, zh in zip(value['occurrences'], spans, chinese):
            row.update(english=english, english_hash=alignment['englishHash'], translation=translation,
                       target_range=en, translation_ranges=[zh], alignment=alignment,
                       status='unmatched', sense_index=None, reason='待核对')
            row.pop('reviewed_sense_id'); row.pop('assignment_context_hash')
        result = sm.propose_record(value)
        self.assertEqual([row['matching_proposal']['candidate_sense_indices']
                          for row in result['occurrences']], [[0], [1]])
        self.assertEqual([row['status'] for row in result['occurrences']], ['unmatched', 'unmatched'])
        reviewed = copy.deepcopy(value)
        for index, row in enumerate(reviewed['occurrences']):
            row.update(status='reviewed', sense_index=index, reason='来源分量独立核对')
        reviewed['occurrences'] = [seal_reviewed_assignment(reviewed, row) for row in reviewed['occurrences']]
        self.assertEqual(sm.evaluate_reviewed_records([reviewed])['counts']['single_candidate_correct'], 2)
        value['definition_provenance']['components'][0].pop('headword')
        self.assertEqual(sm.propose_record(value)['occurrences'][0]['matching_proposal']['reason_code'],
                         'unmapped_component_target')


if __name__ == '__main__':
    unittest.main()
