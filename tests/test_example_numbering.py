import unittest
from anki_pipeline.example_numbering import renumber_examples


def row(index, text='Original <mark>word</mark>'):
    return '<li class="example-card"><div class="example-heading"><span class="index-tag">'+str(index)+'</span><span class="example-text">'+text+'</span></div></li>'


class ExampleNumberingTests(unittest.TestCase):
    def test_component_sections_share_one_visible_list_sequence(self):
        markup = '<ol class="examples"><section><h3>a</h3>' + row(9) + row(13) + '</section><section><h3>an</h3>' + row(4) + '</section></ol>'
        expected = '<ol class="examples"><section><h3>a</h3>' + row(1) + row(2) + '</section><section><h3>an</h3>' + row(3) + '</section></ol>'
        self.assertEqual(renumber_examples(markup), expected)

    def test_hidden_component_sections_do_not_consume_visible_numbers(self):
        hidden = '<section hidden>' + row(9) + '</section><section style="display:none">' + row(13) + '</section>'
        markup = '<ol class="examples">' + hidden + '<section>' + row(8) + '</section></ol>'
        expected = '<ol class="examples">' + hidden + '<section>' + row(1) + '</section></ol>'
        self.assertEqual(renumber_examples(markup), expected)

    def test_remaining_single_example_starts_at_one_without_touching_content(self):
        original=row(2)
        self.assertEqual(renumber_examples(original),row(1))

    def test_gaps_and_different_lists_are_numbered_from_actual_rows(self):
        original='<ol class="examples">'+row(3)+row(9)+'</ol><ol class="examples">'+row(8)+'</ol>'
        expected='<ol class="examples">'+row(1)+row(2)+'</ol><ol class="examples">'+row(1)+'</ol>'
        self.assertEqual(renumber_examples(original),expected)

    def test_history_scripts_and_srcdoc_are_immutable(self):
        history='<details class="sf-inline-history"><summary>原审核</summary><ol>'+row(8)+'</ol></details>'
        opaque='<script>const saved = '+repr(row(9))+';</script><iframe srcdoc="&lt;span class=&quot;index-tag&quot;&gt;7&lt;/span&gt;"></iframe>'
        original=row(2)+history+opaque
        self.assertEqual(renumber_examples(original),row(1)+history+opaque)

    def test_aliases_hidden_rows_and_removed_source_spans(self):
        original=row(2).replace('example-card','ec').replace('index-tag','idx')
        self.assertEqual(renumber_examples(original,{'ec':'example-card','idx':'index-tag'}),original.replace('>2</span>','>1</span>'))
        hidden=row(5).replace('<li ','<li hidden ')
        self.assertEqual(renumber_examples(hidden+row(7)),hidden+row(1))

    def test_self_marked_archived_row_does_not_change_or_consume_an_ordinal(self):
        for marker in ('class="example-card sf-archived-native-example"',
                       'class="example-card" data-native-ownership-history="v1"',
                       'class="example-card" data-reviewed-source-comparison="v1"'):
            historical=row(7).replace('class="example-card"',marker,1)
            self.assertEqual(renumber_examples(historical+row(9)),historical+row(1))

    def test_nested_source_audit_badges_are_preserved_and_do_not_make_current_badge_ambiguous(self):
        for marker in ('class="sf-catalog-revision"',
                       'data-native-ownership-history="v1"',
                       'data-reviewed-source-comparison="v1"'):
            historical='<details '+marker+'><summary>完整旧句</summary><ol>'+row(7)+'</ol></details>'
            original=row(9).replace('</li>',historical+'</li>')
            expected=row(1).replace('</li>',historical+'</li>')
            self.assertEqual(renumber_examples(original),expected)

    def test_two_current_badges_still_reject(self):
        ambiguous=row(9).replace('</li>','<span class="index-tag">8</span></li>')
        with self.assertRaisesRegex(ValueError,'ambiguous ordinal badge'):
            renumber_examples(ambiguous)

    def test_generation_after_pruning_restores_full_original_byte_inverse(self):
        from copy import deepcopy
        from tests.test_native_example_usage import source, row as physical, prepared, native_example
        from anki_pipeline.native_example_usage import update_native_examples, restore_original
        item=source('kaoyan:2022-01:q-29-1:B:0','A novel.','一本小说。')
        excluded=physical(item,[2,7]);old=prepared([])
        from anki_pipeline import sense_display as sd
        old['candidate_scope']={'excluded':[{'occurrence':excluded,'occurrence_sha256':sd._sha(sd._json(excluded))}]}
        old.pop('snapshot_id');old['snapshot_id']=sd._sha(sd._json(old))
        first=native_example(item,item['english'],item['translationZh'],[[2,7]])
        second=native_example(item,'Which novel?','哪本小说？完整中文。',[[6,11]],source_ranges=[[2,7]])
        first=first.replace('<li class="example-card">','<li class="example-card"><span class="index-tag">1</span>',1)
        second=second.replace('<li class="example-card">','<li class="example-card"><span class="index-tag">2</span>',1)
        original=first+second
        result=update_native_examples(original,old,prepared([]))
        self.assertEqual(result['page'],second.replace('>2</span>','>1</span>'))
        self.assertEqual(restore_original(result['page'],result['inverse']),original)
