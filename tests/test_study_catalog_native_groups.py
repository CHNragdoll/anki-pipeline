"""Native examples share semantic grouping while physical counts stay intact."""
from copy import deepcopy
import json
import re
import unittest
from unittest.mock import patch

from anki_pipeline import sense_display as sd, sense_frequency as sf
from anki_pipeline.example_numbering import HISTORY_CLASSES
from anki_pipeline.native_example_usage import _Offsets, update_native_examples
from anki_pipeline.study_catalog_native_groups import group_native_examples
from tests.test_sense_display import native_example, occurrence, source


def live_nodes(markup, aliases=None):
    result = []
    for node in _Offsets(markup, aliases or {}).root.walk():
        ancestors = []
        parent = node.parent
        while parent:
            ancestors.append(parent)
            parent = parent.parent
        if node.tag == 'li' and 'example-card' in node.classes and not any(
                n.classes & HISTORY_CLASSES for n in [node, *ancestors]):
            result.append(node)
    return result


def fixture(*, one_native=False, cross_year=False, display=False):
    english = 'A train and a train can train staff.'
    chinese = '一列火车和另一列火车可以训练员工。'
    spans = [[m.start(), m.end()] for m in re.finditer('train', english)]
    alignments = [{'en': span, 'zh': [zh], 'relation': 'equivalent'}
                  for span, zh in zip(spans, [[2, 4], [8, 10], [12, 14]])]
    item = source('kaoyan:2024-01:p:shared-paragraph:0', english, chinese, alignments)
    value = {'book_id': 'one', 'card_id': 'one-train', 'word': 'train',
             'definition_source': 'oxford', 'definition_provenance': {'entry': 'train'},
             'expected_occurrences': 3, 'senses': [{'pos': 'n.', 'text': '火车'},
                                                {'pos': 'v.', 'text': '训练'}], 'occurrences': []}
    natives = []
    for index, (span, sense) in enumerate(zip(spans, [0, 0, 1])):
        owner = deepcopy(item)
        if cross_year and index == 1:
            owner['id'] = owner['id'].replace('2024', '2023')
            owner['reviewedContentHash'] = sd._sha(owner['id'])
        row = occurrence(owner, span)
        row.update(paper_id=owner['id'].split(':p:')[0], sense_index=sense,
                   method='context-review', review_version='20261015', reason='完整审核-' + str(index + 1))
        value['occurrences'].append(row)
        if not one_native:
            raw = native_example(owner, english, chinese, [span])
            raw = raw.replace('<li class="example-card">', '<li class="example-card"><span class="index-tag">9</span>')
            raw = raw.replace('</li>', '<audio src="token-' + str(index + 1) + '.mp3"></audio>'
                '<details class="sf-catalog-revision"><summary>原审核</summary><p>历史解释-'
                + str(index + 1) + '</p></details></li>')
            natives.append(raw)
    if one_native:
        natives = [native_example(item, english, chinese, spans).replace('<li class="example-card">',
            '<li class="example-card"><span class="index-tag">9</span>')]
    raw = 'PREFIX<ol>' + ''.join(natives) + '</ol>SUFFIX'
    value['definition_provenance'].update(headword='train', page_sha256=sd._sha(raw))
    for row in value['occurrences']:
        row.update(sf.seal_reviewed_assignment(value, row))
    if display:
        sources = {'sentences': {item['id']: item}, 'completions': {}, 'options': {}, 'watched': {}}
        with patch.object(sd, '_load_sources', return_value=sources):
            value = sd.attach_source_displays([value], {'one-train': raw}, {})[0]
    record = sf.prepare_record(value)
    # Existing native runtime supplies the same authored bilingual chunks.
    physical = {key: record[key] for key in ('book_id', 'card_id', 'occurrences')}
    physical['snapshot_id'] = sd._sha(sd._json(physical))
    if not display:
        raw = update_native_examples(raw, physical, physical)['page']
    return raw, record, spans


class NativeGroupTests(unittest.TestCase):
    def test_same_paragraph_three_targets_two_senses_show_two_rows_count_three(self):
        raw, record, spans = fixture()
        before = deepcopy(record)
        result = group_native_examples(raw, record)
        nodes = live_nodes(result)
        self.assertEqual(len(nodes), 2)
        views = [sd._native_examples(result[node.start:node.end], {})[0] for node in nodes]
        self.assertEqual([view['target_ranges'] for view in views], [spans[:2], spans[2:]])
        self.assertEqual([view['jump']['target_ranges'] for view in views], [spans[:2], spans[2:]])
        self.assertEqual(record, before)
        report = sf.report_from_record(record)
        self.assertEqual(report['total'], 3)
        self.assertEqual([sense['count'] for sense in report['senses']], [2, 1])
        for marker in ('完整审核-1', '完整审核-2', '历史解释-1', '历史解释-2', '历史解释-3',
                       'token-1.mp3', 'token-2.mp3', 'token-3.mp3', 'card-chunk'):
            self.assertIn(marker, result)
        for node in nodes:
            for kind in ('example-text', 'example-translation'):
                self.assertEqual(len([part for part in node.descendant(kind).walk()
                                      if 'card-chunk' in part.classes]), 3)
        self.assertEqual([part.attrs['src'] for part in _Offsets(result, {}).root.walk()
                          if part.tag == 'audio'], ['token-1.mp3', 'token-2.mp3', 'token-3.mp3'])
        self.assertEqual([result[n.descendant('index-tag').opened:n.descendant('index-tag').closed]
                          for n in nodes], ['1', '2'])
        self.assertTrue(result.startswith('PREFIX<ol>'))
        self.assertTrue(result.endswith('</ol>SUFFIX'))
        self.assertNotIn('次出现', result)
        self.assertEqual(group_native_examples(result, record), result)

    def test_single_native_row_with_distinct_senses_splits_only_its_own_marks(self):
        raw, record, spans = fixture(one_native=True)
        result = group_native_examples(raw, record)
        nodes = live_nodes(result)
        self.assertEqual(len(nodes), 2)
        self.assertEqual([sd._native_examples(result[n.start:n.end], {})[0]['target_ranges']
                          for n in nodes], [spans[:2], spans[2:]])

    def test_same_text_in_another_year_never_merges(self):
        raw, record, _ = fixture(cross_year=True)
        result = group_native_examples(raw, record)
        self.assertEqual(len(live_nodes(result)), 3)
        self.assertIn('kaoyan%3A2023-01', result)
        self.assertIn('kaoyan%3A2024-01', result)

    def test_same_paper_and_text_with_different_physical_paragraphs_never_merge(self):
        raw, record, spans = fixture()
        draft = deepcopy(record)
        for row in draft['occurrences']:
            row['sense_index'] = 1 if row['target_range'] == spans[2] else 0
            if row['target_range'] == spans[1]:
                row['physical_source'] = ['another-explicit-physical-paragraph']
            row.update(sf.seal_reviewed_assignment(draft, row))
        separate = sf.prepare_record(draft)
        self.assertEqual(len(live_nodes(group_native_examples(raw, separate))), 3)

    def test_original_native_jump_proofs_are_preserved_not_resealed_to_union(self):
        raw, record, spans = fixture(display=True)
        original = deepcopy(record)
        result = group_native_examples(raw, record)
        self.assertEqual(record, original)
        proof_rows = []
        for node in _Offsets(result, {}).root.walk():
            if node.attrs.get('data-study-native-group-proof') == 'v1':
                from html import unescape
                proof_rows.extend(json.loads(unescape(result[node.opened:node.closed]))['occurrences'])
        self.assertTrue(proof_rows)
        pinned = {row['occurrence_id']: row['display']['provenance']['native_jump']
                  for row in original['occurrences']}
        for row in proof_rows:
            self.assertEqual(row['display']['provenance']['native_jump'], pinned[row['occurrence_id']])
        self.assertEqual(len(live_nodes(result)), 2)

    def test_unbound_extra_mark_in_a_rewritten_group_fails_instead_of_disappearing(self):
        raw, record, _ = fixture(one_native=True)
        record = deepcopy(record)
        record['occurrences'] = record['occurrences'][:-1]
        record['expected_occurrences'] = 2
        record.pop('snapshot_id')
        record['snapshot_id'] = sd._sha(sd._json(record))
        with self.assertRaisesRegex(ValueError, 'unbound|unreviewed'):
            group_native_examples(raw, record)

    def test_only_formally_certified_equivalent_senses_merge(self):
        raw, record, spans = fixture()
        draft = deepcopy(record)
        draft['senses'].append({'pos': 'n.', 'text': '列车'})
        for row in draft['occurrences']:
            row['sense_index'] = (2 if row['target_range'] == spans[1] else
                                  0 if row['target_range'] == spans[0] else 1)
            row.update(sf.seal_reviewed_assignment(draft, row))
        distinct = sf.prepare_record(draft)
        self.assertEqual(len(live_nodes(group_native_examples(raw, distinct))), 3)
        draft['sense_group_equivalences'] = [{
            'member_ordinals': [0, 2], 'meaning': '铁路车辆', 'usage_scope': '铁路运输名词',
            'reason': '两词典原义及语法使用范围已核对一致', 'review_version': 'test-review-1',
            'evidence': [{'dictionary': 'Oxford', 'entry': 'train', 'definition': 'railway vehicles'}]}]
        same = sf.prepare_record(draft)
        self.assertEqual(len(live_nodes(group_native_examples(raw, same))), 2)
        self.assertEqual(same['expected_occurrences'], 3)

    def test_compressed_classes_and_packed_jumps_keep_union_source_hashes(self):
        import base64
        raw, record, spans = fixture()
        aliases = {'ec': 'example-card', 'et': 'example-text', 'ez': 'example-translation',
                   'es': 'example-source', 'sj': 'sentence-jump', 'tt': 'translate-tag',
                   'tw': 'target-word', 'ix': 'index-tag', 'cc': 'card-chunk'}
        replacements = []
        for node in live_nodes(raw):
            article = raw[node.start:node.end]
            jump = sd._native_examples(article, {})[0]['jump']
            packed = '|'.join(['1', '2024-01', 'p%3Ashared-paragraph%3A0', *[
                base64.urlsafe_b64encode(bytes.fromhex(jump[key])).decode().rstrip('=')
                for key in ('english_hash', 'reviewed_content_hash')],
                ';'.join(str(start) + ',' + str(end) for start, end in jump['target_ranges'])])
            anchor = node.descendant('sentence-jump')
            opening = raw[anchor.start:anchor.opened]
            revised = re.sub(r'href="[^"]+"', 'data-rb-j="' + packed + '"', opening)
            replacements.append((anchor.start, anchor.opened, revised))
        for start, end, revised in reversed(replacements):
            raw = raw[:start] + revised + raw[end:]
        for compact, full in aliases.items():
            raw = raw.replace('class="' + full + '"', 'class="' + compact + '"')
        result = group_native_examples(raw, record, aliases)
        nodes = live_nodes(result, aliases)
        self.assertEqual(len(nodes), 2)
        view = sd._native_examples(result[nodes[0].start:nodes[0].end], aliases)[0]
        self.assertEqual(view['target_ranges'], spans[:2])
        self.assertEqual(view['jump']['target_ranges'], spans[:2])
        self.assertEqual(view['jump']['english_hash'], record['occurrences'][0]['english_hash'])
        self.assertEqual(group_native_examples(result, record, aliases), result)

    def test_unsupported_inline_audio_is_rejected_and_input_is_unchanged(self):
        raw, record, _ = fixture()
        part = live_nodes(raw)[0].descendant('example-text')
        raw = raw[:part.closed] + '<audio src="inline.mp3"></audio>' + raw[part.closed:]
        original = raw
        with self.assertRaisesRegex(ValueError, 'unsupported native sentence'):
            group_native_examples(raw, record)
        self.assertEqual(raw, original)

    def test_secondary_jump_with_another_source_is_rejected(self):
        raw, record, _ = fixture()
        jump = live_nodes(raw)[0].descendant('sentence-jump')
        # data-latex-url becomes the active source, while href incorrectly
        # points to another source. A union must not silently rewrite either.
        active = jump.attrs['href']
        opening = raw[jump.start:jump.opened]
        from html import escape
        revised = opening[:-1] + ' data-latex-url="' + escape(active, quote=True) + '">'
        revised = revised.replace('href="' + escape(active, quote=True) + '"',
                                  'href="' + escape(active.replace('2024-01', '2023-01'), quote=True) + '"')
        raw = raw[:jump.start] + revised + raw[jump.opened:]
        with self.assertRaisesRegex(ValueError, 'secondary jump'):
            group_native_examples(raw, record)

    def test_source_revision_archives_never_become_current_group_members(self):
        from anki_pipeline.study_catalog_native_groups import _historical
        raw, record, _ = fixture()
        first=live_nodes(raw)[0]
        archived=('<details class="sf-catalog-revision" data-reviewed-source-comparison="catalog-revision">'
                  '<summary>完整旧句</summary><ol>'+raw[first.start:first.end]+'</ol></details>')
        raw=raw[:first.closed]+archived+raw[first.closed:]
        result=group_native_examples(raw,record)
        current=[node for node in _Offsets(result,{}).root.walk()
                 if node.tag=='li' and 'example-card' in node.classes and not _historical(node)]
        self.assertEqual(len(current),2)
        self.assertIn(archived,result)

    def test_merged_secondary_source_revision_archive_is_preserved_exactly(self):
        from anki_pipeline.study_catalog_native_groups import _historical
        raw,record,_=fixture()
        second=live_nodes(raw)[1]
        archived=('<details class="sf-catalog-revision" data-reviewed-source-comparison="catalog-revision">'
                  '<summary>第二处完整旧句</summary><ol>'+raw[second.start:second.end]+'</ol></details>')
        raw=raw[:second.closed]+archived+raw[second.closed:]
        result=group_native_examples(raw,record)
        current=[node for node in _Offsets(result,{}).root.walk()
                 if node.tag=='li' and 'example-card' in node.classes and not _historical(node)]
        self.assertEqual(len(current),2)
        self.assertIn(archived,result)

    def test_genuinely_separate_current_list_containers_still_reject(self):
        raw,record,_=fixture()
        first=live_nodes(raw)[0]
        raw=raw[:first.end]+'</ol><ol>'+raw[first.end:]
        with self.assertRaisesRegex(ValueError,'separate example list containers'):
            group_native_examples(raw,record)


if __name__ == '__main__':
    unittest.main()
