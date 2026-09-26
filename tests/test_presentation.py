"""Keep dictionary content complete and safe when replacing delimiter-heavy prose."""
import unittest
from html.parser import HTMLParser
from anki_pipeline.presentation import render_forms, render_levels, render_senses


class Text(HTMLParser):
    def __init__(self, markup):
        super().__init__(); self.parts = []; self.feed(markup)
    def handle_data(self, value):
        self.parts.append(value)


class ReadingLayoutTests(unittest.TestCase):
    def test_separate_parts_of_speech_without_losing_definitions(self):
        result = render_senses('n.追求的目标，抱负；雄心 | v. 追求，有……野心\n【名】人名')
        self.assertEqual(Text(result).parts, ['n.', '追求的目标，抱负；雄心', 'v.', '追求，有……野心', '【名】人名'])
        self.assertEqual(result.count('class="sense-pos"'), 2)

    def test_level_items_are_complete(self):
        result = render_levels('高中 | CET4 | 商务英语')
        self.assertEqual(Text(result).parts, ['高中', 'CET4', '商务英语'])
        self.assertEqual(result.count('<li>'), 3)

    def test_forms_keep_every_label_and_multiword_value(self):
        result = render_forms('复数：actives | 比较级: more active | 最高级：most active\n未标记文本')
        self.assertEqual(Text(result).parts, ['复数', 'actives', '比较级', 'more active', '最高级', 'most active', '未标记文本'])
        self.assertEqual(result.count('<dt>'), 3)

    def test_unrecognised_and_incomplete_content_is_preserved_and_escaped(self):
        for render in (render_senses, render_forms, render_levels):
            source = '<img src=x onerror="alert(1)"> & 尾部'
            result = render(source)
            self.assertNotIn('<img', result)
            self.assertEqual(''.join(Text(result).parts), source)
            self.assertEqual(render('  '), '')
        self.assertEqual(Text(render_forms('名称： | :value | 不完整')).parts, ['名称：', ':value', '不完整'])
        self.assertEqual(Text(render_senses('n.')).parts, ['n.'])


if __name__ == '__main__':
    unittest.main()
