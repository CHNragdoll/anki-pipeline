from contextlib import nullcontext
import copy
import json
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_navigation as navigation


class NavigationMetadataTests(unittest.TestCase):
    def note(self, **fields):
        return {'id': 'source-id', 'kind': 'word', 'field_names': list(fields),
                'fields': list(fields.values())}

    def test_projected_senses_and_display_examples_override_legacy_values(self):
        note = self.note(Word='train', Definition='''<section class="exam-frequency"
            data-occurrences="3" data-paper-count="1" data-corpus-papers="44" data-stars="1"></section>
            <div class="dictionary-definition"><div class="sf-report"><summary class="sf-row">
            <span class="sf-meaning"><span class="sf-pos">n.</span> 火车</span>
            <span class="sf-count">3 次</span></summary><div class="sf-panel">NEVER INCLUDE LARGE AUDIT
            <span class="sf-meaning">not a current sense</span></div></div></div>''',
            Examples='<li class="example-card">same paragraph, 3 occurrences</li>')
        original = copy.deepcopy(note)
        actual = navigation.note_navigation_metadata(note, source_entry={
            'definition': 'OLD MEANING', 'exampleCount': 99, 'deckName': '书::必考词::Unit 01'})
        self.assertEqual(actual['example_count'], 1)
        self.assertIn('n. 火车', actual['summary'])
        self.assertIn('3 次', actual['summary'])
        self.assertNotIn('NEVER', actual['summary'])
        self.assertNotIn('not a current', actual['summary'])
        self.assertNotIn('OLD', actual['summary'])
        self.assertEqual(actual['deck_name'], '书::必考词::Unit 01')
        self.assertEqual(note, original)

    def test_plain_senses_without_frequency_and_literal_breaks(self):
        actual = navigation.note_navigation_metadata(self.note(Word='a<br>b', Definition=
            '<div class="sense-row"><span class="sense-pos">n.</span><span class="sense-text">目标</span></div>', Examples=''))
        self.assertEqual(actual, {'summary': 'n. 目标', 'example_count': 0})

    def test_subject_neutral_summary_does_not_invent_statistics(self):
        actual = navigation.note_navigation_metadata(self.note(Title='积分', Question=r'求 \(\int x\,dx\)', Answer='解：x²/2+C'))
        self.assertEqual(actual['summary'], '解：x²/2+C')
        self.assertIsNone(actual['example_count'])
        self.assertNotIn('0 次', actual['summary'])
        custom = navigation.note_navigation_metadata(self.note(题目='数学题', 解答='自定义字段'))
        self.assertEqual(custom['summary'], '数学题')
        self.assertIsNone(custom['example_count'])

    def test_examples_ignore_nested_audit_and_support_existing_compact_class(self):
        examples = '''<li class="_r28">current <li class="example-card">nested copy</li></li>
            <div class="sf-ownership-history"><li class="example-card">archived copy</li></div>
            <li class="example-card sf-archived-native-example">standalone archive copy</li>
            <li class="example-card">current two</li><script>"<li class='example-card'>"</script>'''
        actual = navigation.note_navigation_metadata(self.note(Definition='词义', Examples=examples))
        self.assertEqual(actual['example_count'], 2)

    def test_unknown_lazy_examples_are_unknown_not_zero(self):
        actual = navigation.note_navigation_metadata(self.note(Definition='词义', Examples='<div class="as-lazy" data-as-src="large.js"></div>'))
        self.assertIsNone(actual['example_count'])
        generic = navigation.note_navigation_metadata(self.note(Examples='<p>A custom worked example</p>'))
        self.assertIsNone(generic['example_count'])

    def test_known_lazy_example_manifest_counts_all_rows_without_media_fetch(self):
        manifest = {'schema': 'anki-slim-segments.v1', 'total': 33,
                    'parts': [{'src': 'one.js', 'count': 20}, {'src': 'two.js', 'count': 13}]}
        examples = '<li class="example-card">inline</li>' * 10
        examples += '<li class="as-lazy" data-as-kind="examples"><script class="as-manifest" type="application/json">' + json.dumps(manifest) + '</script></li>'
        self.assertEqual(navigation.note_navigation_metadata(self.note(Examples=examples))['example_count'], 43)
        manifest['total'] = 34
        invalid = '<li class="as-lazy" data-as-kind="examples"><script class="as-manifest">' + json.dumps(manifest) + '</script></li>'
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            navigation.note_navigation_metadata(self.note(Examples=invalid))

    def test_retained_catalog_metadata_validates_identity_and_count(self):
        source = {'schema': 'anki-web-catalog.v1', 'counts': {'cards': 2, 'decks': 1, 'examples': 4},
                  'cards': [{'id': 'a', 'definition': '新释义', 'exampleCount': 4, 'deckName': '书::单元'},
                            {'id': 'b', 'source_definition_summary': '补充', 'source_example_count': 0, 'deckName': '书::单元'}]}
        original = copy.deepcopy(source)
        result = navigation.catalog_navigation_metadata(source)
        self.assertEqual(result['totals'], {'notes': 2, 'examples': 4, 'groups': 1})
        self.assertEqual(result['cards']['b']['summary'], '补充')
        self.assertEqual(source, original)
        source['cards'][1]['id'] = 'a'
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            navigation.catalog_navigation_metadata(source)

    def test_catalog_unknown_count_does_not_make_false_total(self):
        value = navigation.catalog_navigation_metadata({'cards': [{'id': 'a', 'definition': 'A'}, {'id': 'b', 'exampleCount': 1}]})
        self.assertIsNone(value['totals']['examples'])
        with self.assertRaisesRegex(ValueError, 'nonnegative'):
            navigation.catalog_navigation_metadata({'cards': [{'id': 'a', 'exampleCount': True}]})

    def test_summary_is_bounded_without_embedded_resources(self):
        result = navigation.note_navigation_metadata(self.note(Answer='<p>' + '字' * 3000 + '</p><script>secret</script>'))
        self.assertLessEqual(len(result['summary']), navigation.SUMMARY_LIMIT)
        self.assertNotIn('secret', result['summary'])

    def test_rendered_payload_uses_answer_and_keeps_source_bytes(self):
        answer = '''<section class="primary-definition"><h2>核心释义</h2><div class="field-content">
                    <span class="sf-meaning">v. 遵守</span></div></section>
                    <ol class="examples"><li class="example-card">one</li></ol>'''
        payload = json.dumps(['<main>FRONT</main>', answer], ensure_ascii=False).replace('<', '\\u003c')
        raw = ('<script>const sides=' + payload + ';let answer=false;const side=x;</script>').encode()
        before = bytes(raw)
        with patch.object(navigation, 'Slices', wraps=navigation.Slices) as scan:
            result = navigation.rendered_navigation_metadata(raw)
        self.assertEqual(scan.call_count, 1)
        self.assertEqual(result, {'summary': 'v. 遵守', 'example_count': 1})
        self.assertEqual(raw, before)

    def test_note_field_mapping_must_be_exact(self):
        with self.assertRaisesRegex(ValueError, 'field'):
            navigation.note_navigation_metadata({'field_names': ['Answer', 'Answer'], 'fields': ['a', 'b']})

    def test_generic_rendered_card_needs_no_vocabulary_dom(self):
        raw = ('<script>const sides=' + json.dumps(['题目', '<main>数学解答</main>']) +
               ';let answer=false;const side=x;</script>').encode()
        self.assertEqual(navigation.rendered_navigation_metadata(raw),
                         {'summary': '数学解答', 'example_count': None})
        vocabulary = ('<script>const sides=' + json.dumps(['word', '<div class="vocab-back">zero examples</div>']) +
                      ';let answer=false;const side=x;</script>').encode()
        self.assertEqual(navigation.rendered_navigation_metadata(vocabulary)['example_count'], 0)

    def test_rendered_current_fields_ignore_nested_complete_source_audits(self):
        for marker in ('class="sf-catalog-revision"', 'data-reviewed-source-comparison="v1"'):
            with self.subTest(marker=marker):
                answer = ('<section class="primary-definition"><div class="field-content">当前词义'
                          '<details ' + marker + '><summary>原审计</summary>'
                          '<section class="primary-definition"><div class="field-content">完整旧词义</div></section>'
                          '</details></div></section><ol class="examples"><li class="example-card">当前句'
                          '<details ' + marker + '><summary>原审计</summary><ol class="examples">'
                          '<li class="example-card">完整旧句</li></ol></details></li></ol>')
                raw = ('<script>const sides=' + json.dumps(['front', answer], ensure_ascii=False) +
                       ';let answer=false;const side=x;</script>').encode()
                original = bytes(raw)
                self.assertEqual(navigation.rendered_navigation_metadata(raw),
                                 {'summary': '当前词义', 'example_count': 1})
                self.assertEqual(raw, original)

    def test_absent_source_is_explicitly_unknown_and_connection_is_readonly(self):
        class Result:
            def fetchone(self):
                return None
        class DB:
            def transaction(self):
                return nullcontext()
            def execute(self, *_):
                return Result()
        with patch('anki_pipeline.study_catalog.connect', return_value=nullcontext(DB())) as connect:
            result = navigation.load_navigation_metadata('DSN', 'math')
        connect.assert_called_once_with('DSN', readonly=True)
        self.assertEqual(result['cards'], {})
        self.assertIsNone(result['totals']['examples'])

    def test_retained_source_only_contributes_grouping_even_after_semantic_edits(self):
        class Result:
            def __init__(self, row=None):
                self.row = row
            def fetchone(self):
                return self.row
            def __iter__(self):
                return iter([])
        class DB:
            statements = []
            def transaction(self):
                return nullcontext()
            def execute(self, sql, *args):
                self.statements.append(sql)
                if 'source.catalog.' in str(args):
                    return Result(('source-sha',))
                return Result()
        db = DB()
        raw = json.dumps({'cards': [{'id': 'source-id', 'definition': 'STALE DEFINITION',
                                    'exampleCount': 999, 'deckName': '书::单元'}]}).encode()
        with patch('anki_pipeline.study_catalog.connect', return_value=nullcontext(db)), \
                patch('anki_pipeline.study_catalog.get_object', return_value=raw):
            result = navigation.load_navigation_metadata('DSN', 'book')
        self.assertEqual(result['cards']['source-id'], {'summary': '', 'example_count': None, 'deck_name': '书::单元'})
        self.assertIsNone(result['totals']['examples'])
        self.assertEqual(result['provenance']['scope'], 'original-grouping-only')
        self.assertFalse(any('components' in statement or 'semantic.projections' in statement for statement in db.statements))


if __name__ == '__main__':
    unittest.main()
