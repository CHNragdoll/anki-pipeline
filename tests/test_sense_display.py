"""Approved display mapping never changes a physical occurrence's meaning/count."""
from copy import deepcopy
import hashlib
from html import escape
import json
from unittest.mock import patch
from urllib.parse import urlencode
import unittest

from anki_pipeline import sense_display as sd
from anki_pipeline.chunk_projection import SENTENCE_FALLBACK_NOTE
from anki_pipeline.packaging import _highlight_example
from anki_pipeline.sense_chunks import render_sentence_pair, _target_chunk_ids


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def sentence_correspondence(english, translation):
    return {'en': [0, len(english)], 'zh': [[0, len(translation)]],
            'relation': 'equivalent', 'note': SENTENCE_FALLBACK_NOTE}


def reseal(display):
    display.pop('display_hash', None)
    display['display_hash'] = sha(json.dumps(display, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return display


def source(identity, english, translation, alignments=None):
    return {'id': identity, 'english': english, 'translationZh': translation,
            'englishHash': sha(english), 'reviewedContentHash': sha(identity),
            'translation_alignment': {'schema': 'codex-sentence-alignment.v1',
                'englishHash': sha(english), 'translationHash': sha(translation),
                'alignments': alignments or []}}


def occurrence(item, span):
    return {'sentence_id': item['id'], 'english': item['english'], 'translation': item['translationZh'],
            'english_hash': item['englishHash'], 'target_range': span,
            'source_provenance': {'sourceSentenceIds': [item['id']], 'reviewedContentHash': item['reviewedContentHash']},
            'alignment': deepcopy(item['translation_alignment']), 'physical_source': [item['id']],
            'source': '原始出处', 'status': 'reviewed', 'sense_index': 0, 'reason': '已核对'}


def native_example(item, english, translation, targets, *, anchor=None, source_ranges=None, answer=None, answer_number=31):
    anchor = anchor or item
    ranges = source_ranges if source_ranges is not None else targets
    answers = ([{'start': answer[0], 'end': answer[1], 'number': answer_number,
                 'word': english[slice(*answer)]}] if answer else [])
    markup = _highlight_example(english, '', '', answers,
                               target_ranges=[tuple(span) for span in targets], preserve_source=True)
    query = urlencode({'anki-codex-sentence': anchor['id'], 'anki-codex-hash': anchor['englishHash'],
                       'anki-codex-review': anchor['reviewedContentHash'], 'anki-codex-en': json.dumps(ranges)})
    return ('<li class="example-card"><span class="example-text">' + markup + '</span>'
            '<a class="sentence-jump" href="' + escape('http://localhost:8765/?' + query, quote=True) + '"></a>'
            '<span class="example-translation"><span class="translate-tag">翻译</span> ' + escape(translation) + '</span>'
            '<span class="example-source">原版完整出处</span></li>')


class SenseDisplayTests(unittest.TestCase):
    def attach(self, rows, page, sources):
        record = {'book_id': 'redbook2027', 'card_id': 'card', 'word': 'novel',
                  'definition_provenance': {'headword': 'novel', 'page_sha256': sha(page)},
                  'occurrences': rows}
        before = deepcopy(record)
        with patch.object(sd, '_load_sources', return_value=sources):
            result = sd.attach_source_displays([record], {'card': page}, {})[0]
        self.assertEqual(record, before)
        for old, revised in zip(rows, result['occurrences']):
            self.assertEqual({key: value for key, value in revised.items() if key != 'display'}, old)
        return result

    def sources(self, *rows):
        return {'sentences': {row['id']: row for row in rows}, 'completions': {}, 'options': {}, 'watched': {}}

    def test_completed_question_reuses_unchanged_chunks_and_native_translation(self):
        raw = source('kaoyan:2019-01:p:q31:0', 'A novel idea ______', '一个新颖想法______',
            [{'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'},
             {'en': [13, 19], 'zh': [[6, 12]], 'relation': 'equivalent'}])
        english, translation = 'A novel idea succeeds.', '一个新颖想法成功了。'
        derived = {'sentenceId': raw['id'], 'originalEnglish': raw['english'], 'completedEnglish': english,
                   'translationZh': translation, 'blankRange': [13, 19], 'insertedRange': [13, 21],
                   'answerNumber': '31', 'questionId': 'kaoyan:2019-01:q-31-1'}
        sources = self.sources(raw); sources['completions'][raw['id']] = derived
        page = native_example(raw, english, translation, [[2, 7]], source_ranges=[[2, 7]], answer=[13, 21])
        display = self.attach([occurrence(raw, [2, 7])], page, sources)['occurrences'][0]['display']
        self.assertNotIn('______', display['english'])
        self.assertEqual(display['target_range'], [2, 7])
        self.assertEqual(display['source'], '原版完整出处')
        self.assertEqual(display['alignment']['alignments'], [
            {'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'},
            sentence_correspondence(english, translation)])
        self.assertTrue(display['cloze_answers'])
        self.assertEqual(display['provenance']['method'], 'native-example-with-approved-source-maps')

    def test_same_sentence_two_identical_tokens_keep_distinct_display_positions(self):
        raw = source('kaoyan:2022-02:p:minutes:0', 'A minute plus a minute.', '一分钟再加一分钟。',
            [{'en': [2, 8], 'zh': [[1, 3]], 'relation': 'equivalent'},
             {'en': [16, 22], 'zh': [[6, 8]], 'relation': 'equivalent'}])
        spans = [[2, 8], [16, 22]]
        page = native_example(raw, raw['english'], raw['translationZh'], spans)
        records = self.attach([occurrence(raw, span) for span in spans], page, self.sources(raw))
        self.assertEqual([row['display']['target_range'] for row in records['occurrences']], spans)
        self.assertEqual(len(records['occurrences']), 2)

    def test_option_context_reuses_compacted_native_question_and_offsets(self):
        raw = source('kaoyan:2019-01:q-35-1:B:0', 'A novel.', '一本小说。',
            [{'en': [2, 7], 'zh': [[2, 4]], 'relation': 'equivalent'}])
        prompt = source('kaoyan:2019-01:p:q35:0', 'Which title?', '哪个标题？')
        english, translation = 'Which title?\n\nA novel.', '哪个标题？一本小说。'
        derived = {'sentenceId': raw['id'], 'completedEnglish': english, 'translationZh': translation,
                   'insertedRange': [14, 21], 'answerNumber': '35', 'questionId': 'kaoyan:2019-01:q-35-1',
                   'hasQuestionBlank': False, 'optionSentenceRefs': [{'sentenceId': raw['id'], 'range': [0, 8]}],
                   'stemSentenceRefs': [{'sentenceId': prompt['id'], 'range': [0, 12]}], 'optionSentenceIds': [raw['id']]}
        sources = self.sources(raw, prompt); sources['options'][raw['id']] = derived
        visible = 'Which title?\nA novel.'
        page = native_example(raw, visible, translation, [[15, 20]], source_ranges=[[2, 7]], answer=[13, 20], answer_number=35)
        display = self.attach([occurrence(raw, [2, 7])], page, sources)['occurrences'][0]['display']
        self.assertEqual(display['english'], visible)
        self.assertEqual(display['target_range'], [15, 20])
        self.assertEqual(display['alignment']['alignments'], [
            {'en': [15, 20], 'zh': [[7, 9]], 'relation': 'equivalent'},
            sentence_correspondence(visible, translation)])

    def test_inserted_correct_option_can_reuse_a_merged_native_stem_display(self):
        raw = source('kaoyan:2020-01:q-31-1:C:0', 'novel.', '小说。')
        stem = source('kaoyan:2020-01:p:q31:0', 'A ______', '一本______')
        derived = {'sentenceId': stem['id'], 'optionSentenceId': raw['id'], 'optionText': raw['english'],
                   'originalEnglish': stem['english'], 'completedEnglish': 'A novel.', 'translationZh': '一本小说。',
                   'blankRange': [2, 8], 'insertedRange': [2, 7], 'answerNumber': '31', 'questionId': 'kaoyan:2020-01:q-31-1'}
        sources = self.sources(raw, stem); sources['completions'][stem['id']] = derived
        page = native_example(raw, 'A novel.', '一本小说。', [[2, 7]], anchor=stem, source_ranges=[], answer=[2, 7])
        display = self.attach([occurrence(raw, [0, 5])], page, sources)['occurrences'][0]['display']
        self.assertEqual(display['target_range'], [2, 7])
        self.assertEqual(display['provenance']['derivation'], 'inserted_option')

    def test_part_b_stem_target_after_inserted_gap_is_shifted_without_recounting(self):
        raw = source('kaoyan:2005-01:p:partb:0', 'Start ______ novel.', '开始______小说。')
        english = 'Start an answer novel.'
        derived = {'sentenceId': raw['id'], 'completionType': 'sentence_insertion',
                   'originalEnglish': raw['english'], 'completedEnglish': english,
                   'translationZh': '开始一个答案小说。', 'blankRange': [6, 12], 'insertedRange': [6, 15],
                   'answerNumber': '41', 'questionId': 'kaoyan:2005-01:q-41-1'}
        sources = self.sources(raw); sources['completions'][raw['id']] = derived
        display = self.attach([occurrence(raw, [13, 18])], '<div></div>', sources)['occurrences'][0]['display']
        self.assertEqual(display['target_range'], [16, 21])
        self.assertEqual(display['english'][16:21], 'novel')

    def test_html_entities_round_trip_as_exact_source_strings(self):
        raw = source('kaoyan:2023-01:p:escaped:0', 'A novel <idea> & hope.', '新颖<想法> & 希望。')
        page = native_example(raw, raw['english'], raw['translationZh'], [[2, 7]])
        display = self.attach([occurrence(raw, [2, 7])], page, self.sources(raw))['occurrences'][0]['display']
        self.assertEqual(display['english'], raw['english'])
        self.assertEqual(display['translation'], raw['translationZh'])

    def test_duplicate_native_matches_and_stale_source_fail_closed(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。')
        page = native_example(raw, raw['english'], raw['translationZh'], [[2, 7]])
        with self.assertRaisesRegex(ValueError, 'multiple native'):
            self.attach([occurrence(raw, [2, 7])], page + page, self.sources(raw))
        row = occurrence(raw, [2, 7]); row['english_hash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source text is stale'):
            self.attach([row], page, self.sources(raw))

    def test_rewritten_or_ambiguous_chinese_chunk_is_not_guessed(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel ______', '一个新颖______',
            [{'en': [2, 7], 'zh': [[2, 4]], 'relation': 'equivalent'}])
        derived = {'sentenceId': raw['id'], 'originalEnglish': raw['english'], 'completedEnglish': 'A novel example.',
                   'translationZh': '一个新颖又新颖的例子。', 'blankRange': [8, 14], 'insertedRange': [8, 15],
                   'answerNumber': '31', 'questionId': 'kaoyan:2023-01:q-31-1'}
        sources = self.sources(raw); sources['completions'][raw['id']] = derived
        display = self.attach([occurrence(raw, [2, 7])], '<div></div>', sources)['occurrences'][0]['display']
        self.assertEqual(display['alignment']['alignments'], [
            sentence_correspondence(derived['completedEnglish'], derived['translationZh'])])

    def test_refresh_legacy_derived_chunks_round_trips_without_changing_physical_bindings(self):
        raw = source('kaoyan:2019-01:p:q31:0', 'A novel idea ______', '一个新颖想法______',
            [{'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'}])
        physical = occurrence(raw, [2, 7])
        derived = {'sentenceId': raw['id'], 'originalEnglish': raw['english'],
                   'completedEnglish': 'A novel idea succeeds.', 'translationZh': '一个新颖想法成功了。',
                   'blankRange': [13, 19], 'insertedRange': [13, 21], 'answerNumber': '31',
                   'questionId': 'kaoyan:2019-01:q-31-1'}
        sources = self.sources(raw); sources['completions'][raw['id']] = derived
        legacy = self.attach([physical], '<div></div>', sources)['occurrences'][0]
        old_view = legacy['display']
        old_view['provenance'].pop('alignment_projection')
        old_view['alignment'] = sd._project_alignment(legacy, old_view['english'], old_view['translation'],
                                                    old_view['alignment_sources'])
        reseal(old_view)
        before = deepcopy(legacy)
        physical_hash = sd._raw_context_hash(legacy)
        self.assertEqual(sd.validate_display(old_view, legacy), old_view)

        upgraded = sd.refresh_derived_chunks(legacy)
        view = upgraded['display']
        self.assertEqual(legacy, before)
        self.assertEqual({key: value for key, value in upgraded.items() if key != 'display'}, physical)
        self.assertEqual(sd._raw_context_hash(upgraded), physical_hash)
        self.assertEqual(view['provenance']['raw_context_hash'], old_view['provenance']['raw_context_hash'])
        self.assertEqual(view['derivation_payload'], old_view['derivation_payload'])
        self.assertEqual(view['provenance']['derivation_sha256'], old_view['provenance']['derivation_sha256'])
        self.assertNotEqual(view['display_hash'], old_view['display_hash'])
        self.assertEqual(view['alignment']['alignments'], [
            {'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'},
            sentence_correspondence(view['english'], view['translation'])])
        restored = json.loads(json.dumps(upgraded, ensure_ascii=False))
        self.assertEqual(sd.validate_display(restored['display'], restored), view)
        self.assertEqual(sd.refresh_derived_chunks(restored), upgraded)

        priority = [(entry['en'][0], entry['en'][1], index)
                    for index, entry in enumerate(view['alignment']['alignments'])]
        self.assertEqual(_target_chunk_ids(priority, tuple(view['target_range'])), {0})
        markup = render_sentence_pair(upgraded)
        self.assertIn('class="card-chunk sf-target-chunk"', markup)
        self.assertIn('data-chunk-ids="0 1"', markup)
        self.assertIn('class="card-chunk" data-chunk-side="en" data-chunk-ids="1"', markup)

    def test_refresh_original_or_absent_display_stays_exact_and_returns_a_copy(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。')
        physical = occurrence(raw, [2, 7])
        no_display = sd.refresh_derived_chunks(physical)
        self.assertEqual(no_display, physical)
        self.assertIsNot(no_display, physical)
        original = self.attach([physical], '<div></div>', self.sources(raw))['occurrences'][0]
        refreshed = sd.refresh_derived_chunks(original)
        self.assertEqual(refreshed, original)
        self.assertIsNot(refreshed, original)

    def test_validator_preserves_complete_payload_and_returns_a_copy(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。')
        row = occurrence(raw, [2, 7])
        page = native_example(raw, raw['english'], raw['translationZh'], [[2, 7]])
        record = self.attach([row], page, self.sources(raw))
        display = record['occurrences'][0]['display']
        copy = sd.validate_display(display, row, record['definition_provenance'])
        self.assertEqual(copy, display)
        copy['provenance']['source_files']['changed'] = '0' * 64
        self.assertNotEqual(copy, display)
        # Canonical storage can add its own computed fields without changing
        # this physical-source binding or the review assignment.
        canonical_row = dict(row, translation_hash=sha(row['translation']), occurrence_id='computed')
        self.assertEqual(sd.validate_display(display, canonical_row), display)

    def test_validator_rejects_independently_resealed_invalid_text_ranges_and_provenance(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。',
                     [{'en': [2, 7], 'zh': [[2, 4]], 'relation': 'equivalent'}])
        row = occurrence(raw, [2, 7])
        page = native_example(raw, raw['english'], raw['translationZh'], [[2, 7]])
        record = self.attach([row], page, self.sources(raw))
        original = record['occurrences'][0]['display']
        mutations = [
            lambda display: display.update(english_hash='0' * 64),
            lambda display: display.update(translation_hash='0' * 64),
            lambda display: display.update(target_range=[0, 1]),
            lambda display: display['alignment'].update(translationHash='0' * 64),
            lambda display: display['alignment']['alignments'][0].update(en=[2, 999]),
            lambda display: display['alignment']['alignments'][0].update(zh=[[0, 2]]),
            lambda display: display.update(cloze_answers=[{'start': 0, 'end': 1, 'number': 31, 'word': 'wrong'}]),
            lambda display: display.update(cloze_answers=[{'start': 0, 'end': 1, 'number': 0, 'word': 'A'}]),
            lambda display: display['provenance'].update(source_card_sha256='0' * 64),
            lambda display: display['provenance'].update(raw_context_hash='0' * 64),
            lambda display: display['provenance'].update(physical_target_range=[0, 1]),
            lambda display: display['provenance']['native_jump'].update(target_ranges=[[False, 7]]),
            lambda display: display['provenance'].update(source_files={'file': 'invalid'}),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(original)
                mutate(changed)
                changed.pop('display_hash')
                changed['display_hash'] = sha(json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
                with self.assertRaises(ValueError):
                    sd.validate_display(changed, row, record['definition_provenance'])
        changed = deepcopy(original); changed['source'] = '未经核对的来源'
        with self.assertRaisesRegex(ValueError, 'payload hash'):
            sd.validate_display(changed, row)

    def test_validator_rejects_changed_physical_context_even_when_target_text_is_same(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。')
        row = occurrence(raw, [2, 7])
        page = native_example(raw, raw['english'], raw['translationZh'], [[2, 7]])
        display = self.attach([row], page, self.sources(raw))['occurrences'][0]['display']
        for key, value in [('physical_source', ['other']), ('source_provenance', {'reviewedContentHash': '0' * 64})]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'binding is stale'):
                changed = deepcopy(row); changed[key] = value
                sd.validate_display(display, changed)

    def test_resealed_derived_translation_target_and_cloze_still_match_approved_payload(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel and a novel ______', '一本小说和另一本小说______')
        row = occurrence(raw, [2, 7])
        derived = {'sentenceId': raw['id'], 'originalEnglish': raw['english'],
                   'completedEnglish': 'A novel and a novel succeeds.',
                   'translationZh': '一本小说和另一本小说获得成功。', 'blankRange': [20, 26],
                   'insertedRange': [20, 28], 'answerNumber': '31', 'questionId': 'kaoyan:2023-01:q31'}
        sources = self.sources(raw); sources['completions'][raw['id']] = derived
        display = self.attach([row], '<div></div>', sources)['occurrences'][0]['display']
        mutations = [lambda value: value.update(translation='未经批准的伪造译文。'),
                     lambda value: value.update(target_range=[14, 19]),
                     lambda value: value.update(cloze_answers=[{'start': 0, 'end': 1, 'number': 999, 'word': 'A'}])]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(display); mutate(changed)
                changed['translation_hash'] = sha(changed['translation'])
                changed['alignment']['translationHash'] = changed['translation_hash']
                changed.pop('display_hash')
                changed['display_hash'] = sha(json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
                with self.assertRaisesRegex(ValueError, 'approved derivation'):
                    sd.validate_display(changed, row)

    def test_page_binding_and_current_review_provenance_fail_closed(self):
        raw = source('kaoyan:2023-01:p:novel:0', 'A novel.', '一本小说。')
        row = occurrence(raw, [2, 7])
        row['source_provenance']['reviewedContentHash'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'source text is stale'):
            self.attach([row], '<div></div>', self.sources(raw))
        record = {'book_id': 'redbook2027', 'card_id': 'card', 'word': 'novel',
                  'definition_provenance': {'headword': 'novel', 'page_sha256': '0' * 64},
                  'occurrences': [occurrence(raw, [2, 7])]}
        before = deepcopy(record)
        with patch.object(sd, '_load_sources', return_value=self.sources(raw)):
            with self.assertRaisesRegex(ValueError, 'source card page'):
                sd.attach_source_displays([record], {'card': '<div></div>'}, {})
        self.assertEqual(record, before)


if __name__ == '__main__': unittest.main()
