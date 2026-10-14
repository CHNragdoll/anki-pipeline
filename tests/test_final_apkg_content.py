"""Offset preservation and runtime-exact projection selection for full APKGs."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from anki_pipeline.final_apkg_content import current_pairs, extract_fields, scoped_projection
from anki_pipeline.native_example_usage import _Offsets


def page(definition='D', examples='', extra='', optional=''):
    return ('<div id="preview-front"><div class="vocab-back"><section class="primary-definition">'
            '<div class="field-content">wrong front</div></section></div></div>'
            '<div id="preview-back"><div class="vocab-front">FrontSide</div>'
            '<div class="vocab-back"><section class="primary-definition">'
            '<div class="field-content">' + definition + '</div></section>' + optional + extra +
            '<section class="examples-section"><ol class="field-content examples">' + examples +
            '</ol></section><section class="personal-note"><div class="field-content">'
            'private note</div></section></div></div>')


def native(en='A &amp; B', zh='翻译', label='<span class="translate-tag">翻译</span> '):
    return ('<li class="example-card"><div class="example-text">' + en +
            '</div><div class="example-translation">' + label + zh + '</div></li>')


def sf_pair(en, zh):
    return ('<div class="sf-sentence-pair"><div class="sf-en">' + en +
            '</div><div class="sf-zh">' + zh + '</div></div>')


def supplement_prefix():
    return ('<p class="supplement-source">牛津高阶英汉双解词典（第10版） · 补充词卡</p>\n'
            '<p class="sf-source">英文原定义：very fixed &amp; strong</p>\n'
            '<p class="sf-source">中文原译：根深蒂固的</p>\n'
            '<details class="sf-supplemental-lexeme"><summary>完整来源</summary>'
            '<pre>{&quot;original_row&quot;:{&quot;reason&quot;:&quot;原完整理由\\n第二行&quot;},'
            '&quot;native_sense&quot;:{&quot;source&quot;:&quot;Oxford&quot;}}</pre></details>\n')


class FinalApkgContentTests(unittest.TestCase):
    def test_exact_slices_preserve_entities_whitespace_chunks_and_full_history(self):
        definition = ('\n<div class="sf-report"><span data-chunk-ids="1">😀 &amp;  x</span>'
                      '<details class="sf-ownership-history"><pre>{"reason":"old\\nreason",'
                      '"source":"甲 &quot;乙&quot;"}</pre></details></div>\n')
        examples = native('<mark class="target-word">A</mark>  &amp; B', ' 原译\n')
        optional = ''.join('<section class="' + name + '"><div class="field-content">' + value +
                           '</div></section>' for name, value in [
                           ('secondary-definition', 'S &lt; T'), ('level-section', '<b>L</b>'),
                           ('forms-section', '形：<i>forms</i>\n')])
        self.assertEqual(extract_fields(page(definition, examples, optional=optional), {}), {
            'Definition': definition, 'SimpleDefinition': 'S &lt; T', 'Level': '<b>L</b>',
            'WordForms': '形：<i>forms</i>\n', 'Examples': examples})

    def test_aliases_change_only_real_class_attributes_not_srcdoc_script_or_history_text(self):
        original = ('<div class = \'_r1  other\'><iframe srcdoc="&lt;p class=\'_r1\'&gt;'
                    '原文&lt;/p&gt;" class="_r2"></iframe>'
                    '<script>const original = \'<div class="_r1">\';</script>'
                    '<pre>class=&quot;_r1&quot;</pre></div>')
        expected = original.replace("class = '_r1  other'", "class = 'sf-report  other'").replace(
            'class="_r2"', 'class="etymology-frame"')
        self.assertEqual(extract_fields(page(original), {'_r1': 'sf-report', '_r2': 'etymology-frame'})[
            'Definition'], expected)

    def test_aliases_anchor_front_and_back_and_optional_fields_are_empty(self):
        source = page('accepted').replace('vocab-back', '_r1').replace('primary-definition', '_r2').replace(
            'field-content', '_r3').replace('examples-section', '_r4').replace('examples"', '_r5"')
        result = extract_fields(source, {'_r1': 'vocab-back', '_r2': 'primary-definition',
                                '_r3': 'field-content', '_r4': 'examples-section', '_r5': 'examples'})
        self.assertEqual(result['Definition'], 'accepted')
        self.assertEqual([result[key] for key in ['SimpleDefinition', 'Level', 'WordForms', 'Examples']],
                         ['', '', '', ''])

    def test_external_current_reports_are_appended_once_in_source_order(self):
        first = '<div class="sf-report">nested report</div>'
        second = '<div class="sf-report">new compound' + sf_pair('one', '一') + '</div>'
        archived = '<div class="sf-original-history-panel"><div class="sf-report">old</div></div>'
        third = '<div class="sf-report">another</div>'
        result = extract_fields(page(first, extra=second + archived + third), {})
        self.assertEqual(result['Definition'], first + second + third)
        self.assertNotIn('private note', result['Definition'])

    def test_supplemental_prefix_and_report_are_preserved_as_one_exact_slice(self):
        prefix = supplement_prefix()
        report = '<div class="sf-report">compound report' + sf_pair('one', '一') + '</div>'
        result = extract_fields(page('dictionary', native('one', '一'), extra=prefix + report), {})
        self.assertEqual(result['Definition'], 'dictionary' + prefix + report)
        self.assertEqual(result['Examples'], native('one', '一'))
        for marker in ('supplement-source', 'sf-supplemental-lexeme', 'class="sf-report"'):
            self.assertEqual(result['Definition'].count(marker), 1)

    def test_supplemental_group_already_in_definition_is_not_duplicated(self):
        definition = supplement_prefix() + '<div class="sf-report">inside</div>'
        self.assertEqual(extract_fields(page(definition), {})['Definition'], definition)

    def test_incomplete_or_orphan_external_supplement_is_rejected(self):
        for extra in [supplement_prefix(),
                      supplement_prefix().replace('<p class="supplement-source">', '<p class="other">') +
                      '<div class="sf-report">report</div>']:
            with self.subTest(extra=extra[:80]), self.assertRaisesRegex(ValueError, 'supplemental'):
                extract_fields(page(extra=extra), {})

    def test_external_supplemental_group_cannot_cross_personal_note(self):
        source = page(extra=supplement_prefix()).replace(
            '</section></div></div>', '</section><div class="sf-report">late</div></div></div>')
        with self.assertRaises(ValueError):
            extract_fields(source, {})

    def test_actual_four_supplemental_cards_preserve_oxford_definition_and_complete_evidence(self):
        root = Path(__file__).resolve().parents[1]
        preview = root / 'output/eleven-resolution-20261014/preview-own/final-v2'
        if not all((preview / book / 'catalog.json').is_file() for book in ('redbook', 'redbook2027')):
            self.skipTest('accepted final-v2 artifacts are not available in this checkout')
        for book in ('redbook', 'redbook2027'):
            catalog = json.loads((preview / book / 'catalog.json').read_text())
            for word in ('deep-rooted', 'teem'):
                with self.subTest(book=book, word=word):
                    card = next(value for value in catalog['cards'] if value['word'] == word)
                    source = (root / 'output' / card['previewUrl'].lstrip('/')).read_text()
                    fields = extract_fields(source, {})
                    tree = _Offsets(source, {})
                    back = next(node for node in tree.root.walk() if 'vocab-back' in node.classes)
                    group = [node for node in back.children if node.classes.intersection({
                        'supplement-source', 'sf-source', 'sf-supplemental-lexeme', 'sf-report'})]
                    self.assertEqual([node.attrs['class'] for node in group], [
                        'supplement-source', 'sf-source', 'sf-source', 'sf-supplemental-lexeme', 'sf-report'])
                    exact = source[group[0].start:group[-1].end]
                    self.assertTrue(fields['Definition'].endswith(exact))
                    for node in group:
                        self.assertEqual(fields['Definition'].count(source[node.start:node.end]), 1)
                    self.assertIn('牛津高阶英汉双解词典（第10版）', fields['Definition'])
                    self.assertIn('英文原定义：', fields['Definition'])
                    self.assertIn('中文原译：', fields['Definition'])
                    native_english = ('very fixed and strong; difficult to change or to destroy'
                                      if word == 'deep-rooted' else
                                      'to be full of people, animals, etc. moving around')
                    native_chinese = ('根深蒂固的；强烈的；坚定的' if word == 'deep-rooted' else
                                      '充满，遍布，到处都是（移动着的人、动物等）')
                    self.assertEqual(source[group[1].opened:group[1].closed], '英文原定义：' + native_english)
                    self.assertEqual(source[group[2].opened:group[2].closed], '中文原译：' + native_chinese)
                    self.assertIn('source_origins', source[group[3].start:group[3].end])
                    self.assertIn('native_sense', source[group[3].start:group[3].end])
                    examples = next(node for node in back.walk() if node.tag == 'ol' and 'examples' in node.classes)
                    self.assertEqual(fields['Examples'], source[examples.opened:examples.closed])

    def test_report_after_personal_note_is_rejected(self):
        source = page().replace('</div></div>', '<div class="sf-report">late</div></div></div>')
        with self.assertRaisesRegex(ValueError, 'precede personal notes'):
            extract_fields(source, {})

    def test_ambiguous_or_unclosed_required_layout_is_rejected(self):
        for source in [page().replace('id="preview-back"', 'id="missing"'),
                       page().replace('<section class="primary-definition">',
                                      '<section class="primary-definition"><section class="primary-definition">'),
                       '<div id="preview-back"><div class="vocab-back"><section class="primary-definition">']:
            with self.subTest(source=source[:80]), self.assertRaises(ValueError):
                extract_fields(source, {})

    def test_native_exact_label_and_one_space_only_sf_has_no_label_rule(self):
        fields = {'Examples': native(zh='  原译') + native(en='leading', zh='原译', label=' \n') +
                  native(en='entity', zh='译', label='<span class="translate-tag">翻译</span>&#32;') +
                  native(en='comment', zh='译', label='<span class="translate-tag">翻译</span><!--x--> ') +
                  native(en='other label', zh='译', label='<span class="translate-tag">译文</span> ') +
                  sf_pair('A<br>B', '<span class="translate-tag">翻译</span> 中文')}
        self.assertEqual(current_pairs(fields), {('A & B', '  原译'), ('leading', ' \n原译'),
                        ('entity', '译'), ('comment', ' 译'), ('other label', '译文 译'),
                        ('AB', '翻译 中文')})

    def test_histories_excluded_and_nested_pairs_are_owned_by_nearest_root(self):
        markup = native('current', '现译')
        for classes in ['sf-ownership-history', 'sf-original-history-panel', 'sf-ownership-authority',
                        'sf-archived-example', 'sf-archived-native-example']:
            markup += '<div class="' + classes + '">' + native('old', '旧') + '</div>'
        for attr in ['data-native-ownership-history', 'data-reviewed-source-comparison']:
            markup += '<div ' + attr + '>' + sf_pair('old', '旧') + '</div>'
        markup += '<li class="example-card">' + sf_pair('nested', '内译') + '</li>'
        self.assertEqual(current_pairs({'Definition': markup}), {('current', '现译'), ('nested', '内译')})

    def test_projection_subset_preserves_full_pins_proofs_and_record_order(self):
        full = {'schema': 'derived-chunk-display-projection.v1', 'pins': {'complete': {'sha256': 'p'}},
                'audit': ['retained'], 'records': [
                {'english': 'old', 'translation': '旧', 'chunks': ['old']},
                {'english': 'SF', 'translation': '义项', 'chunks': ['sf'], 'source_comparisons': [{'full': True}]},
                {'english': 'N', 'translation': '原译', 'chunks': ['native'], 'unmapped': [{'full': True}]}]}
        before = deepcopy(full)
        fields = {'Definition': sf_pair('SF', '义项') + '<div class="sf-archived-example">' +
                  sf_pair('old', '旧') + '</div>', 'Examples': native('N', '原译')}
        result = scoped_projection(fields, full)
        self.assertEqual(result['records'], full['records'][1:])
        self.assertEqual(result['pins'], full['pins'])
        self.assertEqual(result['audit'], full['audit'])
        result['records'][0]['chunks'].append('mutation')
        result['pins']['complete']['sha256'] = 'mutation'
        self.assertEqual(full, before)

    def test_duplicate_projection_keys_rejected_even_outside_this_card(self):
        full = {'schema': 'derived-chunk-display-projection.v1', 'pins': {},
                'records': [{'english': 'old', 'translation': '旧'}] * 2}
        with self.assertRaisesRegex(ValueError, 'repeats'):
            scoped_projection({}, full)


if __name__ == '__main__':
    unittest.main()
