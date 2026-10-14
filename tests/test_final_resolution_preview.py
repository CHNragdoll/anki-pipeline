"""Focused safeguards for the finite final-preview derivation."""
from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest

from anki_pipeline import source_confirmations as sc, sense_display as sd, sense_frequency as sf
from anki_pipeline.native_example_usage import _Offsets
from anki_pipeline.packaging import _highlight_example, _source_jump
from scripts import patch_exam_usage_preview as owner
from scripts import update_exam_usage_preview as preview
from scripts import build_final_resolution_preview as final


def row(text='They promote action.', target=(5, 12), word='promote'):
    return {'occurrence_id': 'a' * 64, 'sentence_id': 'kaoyan:2000-01:p:b-1:0',
        'paper_id': 'kaoyan:2000-01', 'year': 2000, 'english': text,
        'english_hash': sc.digest(text.encode()), 'translation': '他们促使行动。',
        'translation_hash': sc.digest('他们促使行动。'.encode()), 'target_range': list(target),
        'source': '2000 英语真题', 'source_provenance': {'reviewedContentHash': 'b' * 64},
        'alignment': {'schema': 'codex-sentence-alignment.v1',
            'englishHash': sc.digest(text.encode()), 'translationHash': sc.digest('他们促使行动。'.encode()),
            'alignments': [
            {'en': [0, 4], 'zh': [[0, 2]], 'relation': 'equivalent'},
            {'en': list(target), 'zh': [[2, 4]], 'relation': 'equivalent'},
            {'en': [target[1] + 1, len(text) - 1], 'zh': [[4, 6]], 'relation': 'equivalent'}]},
        'reason': '完整原理由\n不能删去的第二行', 'status': 'ambiguous', 'sense_id': None}


def native(item):
    return '<ol><li class="example-card"><div class="example-text">' + _highlight_example(
        item['english'], '', '', [], target_ranges=[item['target_range']], preserve_source=True
    ) + '</div><div class="example-translation"><span class="translate-tag">翻译</span> ' + item['translation'] + '</div><p class="example-source">原来源' + _source_jump(
        owner.original_paper_jump(item, item['target_range'], 'http://localhost:8765')) + '</p></li></ol>'


class FinalPreviewTests(unittest.TestCase):
    def test_transition_topology_follows_payload_lineage_not_lane_order(self):
        first = {'book_id': 'redbook', 'card_id': 'x', 'parent_snapshot_id': 'p', 'child_snapshot_id': 'q'}
        second = {**first, 'parent_snapshot_id': 'q', 'child_snapshot_id': 'r'}
        chain = final.order_transitions([('semantic', second), ('source', first)])
        self.assertEqual([lane for lane, _ in chain], ['source', 'semantic'])
        with self.assertRaisesRegex(ValueError, 'chain'):
            final.order_transitions([('a', first), ('b', {**second, 'parent_snapshot_id': 'other'})])
        third = {**second, 'parent_snapshot_id': 'r', 'child_snapshot_id': 's'}
        self.assertEqual([lane for lane, _ in final.order_transitions([
            ('context', third), ('semantic', second), ('source', first)])], ['source', 'semantic', 'context'])

    def test_generic_native_correction_preserves_chunks_source_and_full_inverse(self):
        old = row()
        new = row('They prompt action.', (5, 11), 'prompt')
        new['occurrence_id'] = 'c' * 64
        new['source_provenance']['source_confirmation'] = {
            'key': 'promote', 'original_row': old, 'original_row_sha256': sc.digest(old),
            'note': '确证应为 prompt，保留原译与原审查', 'evidence': {'dictionary': 'Cambridge'}}
        before = {'book_id': 'redbook', 'card_id': 'x', 'word': 'prompt', 'occurrences': [old]}
        after = {**before, 'occurrences': [new]}
        page = native(old)
        revised, inverse, proof = final.correct_native(page, before, after, {}, 'http://localhost:8765')
        parsed = sd._native_examples(revised, {})[0]
        self.assertEqual(parsed['english'], new['english'])
        self.assertEqual(parsed['translation'], new['translation'])
        self.assertEqual(parsed['target_ranges'], [new['target_range']])
        self.assertEqual(parsed['jump']['english_hash'], new['english_hash'])
        self.assertEqual(proof['updated'], 1)
        self.assertIn('data-chunk-side="zh"', revised)
        self.assertIn('完整原理由', revised)
        self.assertEqual(preview.restore_edits(revised, inverse), page)

    def test_retired_wrong_native_has_no_active_example_and_exact_inverse(self):
        old = row('A rooted idea.', (2, 8), 'root')
        before = {'book_id': 'redbook', 'card_id': 'root', 'word': 'root', 'occurrences': [old]}
        after = {**before, 'occurrences': []}
        page = native(old)
        revised, inverse, proof = final.correct_native(page, before, after, {}, 'http://localhost:8765')
        self.assertFalse(final.default_native(revised, {}))
        self.assertEqual(proof['retired'], 1)
        self.assertEqual(preview.restore_edits(revised, inverse), page)

    def test_unchanged_native_is_byte_exact(self):
        old = row()
        record = {'book_id': 'redbook', 'card_id': 'x', 'word': 'promote', 'occurrences': [old]}
        dictionary = '<li class="example-card"><div class="example-text">A dictionary example.</div><div class="example-translation">词典例句。</div><p class="example-source">Oxford</p></li>'
        original = native(old) + dictionary
        revised, inverse, proof = final.correct_native(original, record, deepcopy(record), {}, 'http://localhost:8765')
        self.assertEqual(revised, original)
        self.assertEqual(inverse, [])
        self.assertEqual(proof['unchanged_native_examples'], 2)

    def test_as_badge_does_not_reclassify_other_raw_ambiguous_rows(self):
        old = row()
        old['semantic_review'] = {'schema': 'eleven-semantic-row-review.v1', 'action': 'source_anomaly_explained'}
        page = '<section class="sf-pending"><article class="sf-example" data-sf-occurrence-id="' + old['occurrence_id'] + '"><span class="sf-status">义项未细分</span></article><article class="sf-example" data-sf-occurrence-id="other"><span class="sf-status">宽泛匹配</span></article></section>'
        revised, inverse = final.source_anomaly_badge(page, {'occurrences': [old]}, {})
        self.assertIn('原文结构异常', revised)
        self.assertIn('宽泛匹配', revised)
        self.assertNotIn('义项未细分', revised)
        self.assertEqual(preview.restore_edits(revised, inverse), page)

    def test_atomic_rewrite_does_not_modify_a_reused_hardlink(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / 'parent'
            child = Path(directory) / 'child'
            parent.write_text('sealed')
            os.link(parent, child)
            final.atomic_write(child, 'derived')
            self.assertEqual(parent.read_text(), 'sealed')
            self.assertEqual(child.read_text(), 'derived')

    def test_projection_binding_cannot_hide_changed_physical_authority(self):
        old = row(); old['display'] = {'english': 'A complete display.', 'translation': '完整原译'}
        before = {'occurrences': [old]}
        after = deepcopy(before); after['occurrences'][0]['english'] = 'Changed physical wording.'
        view = {'english': old['display']['english'], 'translation': old['display']['translation']}
        item = {'before': view, 'after': view, 'before_sha256': sc.digest(view), 'after_sha256': sc.digest(view),
            'occurrence_ids': [old['occurrence_id']], 'book_id': 'redbook', 'card_id': 'x', 'child_snapshot_id': 'oldphysical'}
        with self.assertRaisesRegex(ValueError, 'physical source changed'):
            final.retain_entries(before, after, [item])
        retained = final.retain_entries(before, deepcopy(before), [item])
        self.assertNotIn('child_snapshot_id', retained[0])
        self.assertEqual(item['child_snapshot_id'], 'oldphysical')
        self.assertEqual(retained[0]['before'], item['before'])

    def test_retired_history_stays_inside_its_original_sentence(self):
        original = row()
        item = {'original_row': original, 'original_row_sha256': sc.digest(original),
            'target_card_id': 'correct', 'target_occurrence_id': 'new', 'action': 'source_correction'}
        page = '<div class="sf-report" data-snapshot="old"></div>'
        revised, inverse = final.retired_source_history(page, {'book_id': 'redbook', 'source_retirements': [item]}, {},
            {('redbook', 'correct'): '/correct.html'})
        nodes = _Offsets(revised, {}).root
        article = next(n for n in nodes.walk() if 'sf-archived-example' in n.classes)
        details = [n for n in article.walk() if 'sf-final-history' in n.classes]
        self.assertEqual(len(details), 1)
        self.assertIn('完整原理由', revised[details[0].start:details[0].end])
        self.assertIn('/correct.html', revised)
        self.assertEqual(preview.restore_edits(revised, inverse), page)

    def test_corrected_option_keeps_current_stem_and_whole_lexeme_chunks(self):
        from tests.test_sense_display import SenseDisplayTests, source, occurrence, native_example
        from anki_pipeline.sense_chunks import render_sentence_pair
        helper = SenseDisplayTests()
        raw = source('kaoyan:2021-01:q-34-1:A:0', 'a deep-root belief.', '一种根深蒂固的观念。',
            [{'en': [0, 18], 'zh': [[0, 9]], 'relation': 'equivalent'}])
        stem = source('kaoyan:2021-01:p:q34:0', 'What does it show?', '这说明什么？')
        expanded = stem['english'] + '\n\n' + raw['english']
        visible = stem['english'] + '\n' + raw['english']
        translation = stem['translationZh'] + raw['translationZh']
        start = len(stem['english']) + 2
        derived = {'sentenceId': raw['id'], 'completedEnglish': expanded, 'translationZh': translation,
            'insertedRange': [start, start + 18], 'answerNumber': '34', 'questionId': 'kaoyan:2021-01:q-34-1',
            'hasQuestionBlank': False, 'optionSentenceRefs': [{'sentenceId': raw['id'], 'range': [0, 18]}],
            'stemSentenceRefs': [{'sentenceId': stem['id'], 'range': [0, len(stem['english'])]}], 'optionSentenceIds': [raw['id']]}
        sources = helper.sources(raw, stem); sources['options'][raw['id']] = derived
        page = native_example(raw, visible, translation, [[start - 1 + 7, start - 1 + 11]],
            source_ranges=[[7, 11]], answer=[start - 1, start - 1 + 18], answer_number=34)
        old = helper.attach([occurrence(raw, [7, 11])], page, sources)['occurrences'][0]
        old['occurrence_id'] = 'd' * 64
        saved = deepcopy(old)
        new = deepcopy(old); new.pop('display')
        new.update(english='a deep-rooted belief.', english_hash=sf._sha('a deep-rooted belief.'), target_range=[2, 13])
        new['alignment'] = {'schema': 'codex-sentence-alignment.v1', 'englishHash': new['english_hash'],
            'translationHash': sf._sha(new['translation']), 'alignments': [
                {'en': [0, 20], 'zh': [[0, 9]], 'relation': 'equivalent'},
                {'en': [2, 13], 'zh': [[2, 6]], 'relation': 'equivalent'}]}
        new['source_provenance']['source_confirmation'] = {'metadata_only': False, 'source_revision': {'current': 'sealed-reader-row'}}
        witness = final.derive_projection(new, old, old['display'])
        self.assertEqual(witness['view']['english'], stem['english'] + '\na deep-rooted belief.')
        self.assertEqual(witness['view']['english'][slice(*witness['view']['target_range'])], 'deep-rooted')
        self.assertEqual(witness['view']['translation'], translation)
        target = next(c for c in witness['view']['alignment']['alignments'] if c['en'] == witness['view']['target_range'])
        self.assertEqual(target['zh'], [[len(stem['translationZh']) + 2, len(stem['translationZh']) + 6]])
        self.assertEqual(old, saved)
        markup = '<article class="sf-example" data-sf-occurrence-id="' + new['occurrence_id'] + '">' + render_sentence_pair(new) + '</article>'
        projected, inverse = final.project_composites(markup, {'occurrences': [new]}, {new['occurrence_id']: witness}, {})
        self.assertIn('What does it show?', projected)
        self.assertIn('sf-target-chunk', projected)
        self.assertEqual(preview.restore_edits(projected, inverse), markup)

    def context_fixture(self):
        physical = row()
        physical['physical_source'] = {'sentence_id': physical['sentence_id']}
        old_stem, new_stem, stem_zh = 'What promoted it?\n', 'What prompted it?\n', '是什么促使的？'
        def display(stem):
            english, translation = stem + physical['english'], stem_zh + physical['translation']
            alignment = deepcopy(physical['alignment'])
            for chunk in alignment['alignments']:
                chunk['en'] = [value + len(stem) for value in chunk['en']]
                chunk['zh'] = [[value + len(stem_zh) for value in span] for span in chunk['zh']]
            alignment['alignments'].insert(0, {'en': [0, len(stem) - 1], 'zh': [[0, len(stem_zh)]], 'relation': 'equivalent'})
            alignment.update(englishHash=sf._sha(english), translationHash=sf._sha(translation))
            return {'schema': 'exam-sense-display.v2', 'english': english, 'translation': translation,
                'english_hash': sf._sha(english), 'translation_hash': sf._sha(translation), 'alignment': alignment,
                'target_range': [value + len(stem) for value in physical['target_range']], 'cloze_answers': []}
        physical['display'] = display(old_stem)
        projection = {'schema': 'final-reader-context-projection.v1', 'original_row': deepcopy(physical),
            'original_display': deepcopy(physical['display']), 'new_display': display(new_stem),
            'context_source_jump': 'http://localhost:8765/current-stem?anki-codex-hash=' + 'c' * 64}
        before = {'occurrences': [physical], 'snapshot_id': 'old'}
        after = deepcopy(before); after['snapshot_id'] = 'new'
        supplied = {physical['occurrence_id']: projection}
        after['exam_usage_policy'] = {'final_reader_contexts': {'projections': supplied}}
        return before, after, {'display_projections': supplied}, supplied

    def test_context_projection_updates_native_and_report_keeps_raw_authority_and_inverse(self):
        from anki_pipeline.sense_chunks import render_sentence_pair
        before, after, card, validated = self.context_fixture()
        sealed = deepcopy(before)
        physical = before['occurrences'][0]
        witnesses = final.context_projection_witnesses(before, after, card, validated, exam_base='http://192.168.3.5:8765')
        witness = witnesses[physical['occurrence_id']]
        view = physical['display']
        native_page = '<li class="example-card"><div class="example-text">' + _highlight_example(
            view['english'], '', '', [], target_ranges=[view['target_range']], preserve_source=True) + '</div>' + \
            '<div class="example-translation"><span class="translate-tag">翻译</span> ' + view['translation'] + '</div>' + \
            '<p class="example-source">原来源' + _source_jump(owner.original_paper_jump(physical, physical['target_range'], 'http://localhost:8765')) + '</p></li>'
        revised, inverse, stats = final.project_context_native(native_page, before, witnesses, {})
        parsed = final.default_native(revised, {})[0][1]
        self.assertEqual(parsed['english'], witness['view']['english'])
        self.assertEqual(parsed['target_ranges'], [witness['view']['target_range']])
        self.assertEqual(parsed['jump']['english_hash'], physical['english_hash'])
        self.assertEqual(stats['updated'], 1)
        self.assertIn('data-chunk-side="zh"', revised)
        self.assertIn('http://192.168.3.5:8765/current-stem?', revised)
        self.assertEqual(preview.restore_edits(revised, inverse), native_page)
        report = '<article class="sf-example" data-sf-occurrence-id="' + physical['occurrence_id'] + '">' + render_sentence_pair(physical['display']) + '</article>'
        projected, projection_inverse = final.project_composites(report, after, witnesses, {})
        documented, history_inverse = final.inline_context_history(projected, witnesses, {})
        article = next(n for n in _Offsets(documented, {}).root.walk() if 'sf-example' in n.classes)
        self.assertEqual(len([n for n in article.walk() if 'sf-final-context-history' in n.classes]), 1)
        self.assertIn('完整原理由', documented)
        self.assertEqual(preview.restore_edits(preview.restore_edits(documented, history_inverse), projection_inverse), report)
        self.assertEqual(before, sealed)
        self.assertEqual(after['occurrences'], sealed['occurrences'])

        unrelated = '<li class="example-card"><div class="example-text">A preserved dictionary example.</div>' + \
            '<div class="example-translation">一个保留的词典例句。</div><p class="example-source">Oxford</p></li>'
        self.assertIsNone(final.default_native(unrelated, {})[0][1]['jump'])
        revised, inverse, stats = final.project_context_native(native_page + unrelated, before, witnesses, {})
        self.assertIn(unrelated, revised)
        self.assertEqual(stats['updated'], 1)
        self.assertEqual(preview.restore_edits(revised, inverse), native_page + unrelated)

    def test_context_projection_refuses_changed_raw_or_policy(self):
        before, after, card, validated = self.context_fixture()
        changed = deepcopy(after); changed['occurrences'][0]['english'] += 'x'
        with self.assertRaisesRegex(ValueError, 'immutable raw/v2'):
            final.context_projection_witnesses(before, changed, card, validated)
        changed = deepcopy(after); changed['exam_usage_policy']['final_reader_contexts']['projections'] = {}
        with self.assertRaisesRegex(ValueError, 'projection map differs'):
            final.context_projection_witnesses(before, changed, card, validated)


if __name__ == '__main__':
    unittest.main()
