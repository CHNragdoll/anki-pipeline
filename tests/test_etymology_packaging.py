"""Root explanations are offline, source-preserving and answer-only."""
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from anki_pipeline.packaging import _fields, build_package, render_preview
from anki_pipeline.etymology import enrich_etymology_cards, original_viewer_document
from tests.test_frequency_packaging import card


def source_card():
    value = card()
    value['etymology'] = {
        'schema': 'cigen-etymology.v1', 'found': True, 'has_content': True,
        'query': 'rate', 'entries': [{
            'id': 12, 'headword': 'rate', 'html_sha256': 'a' * 64, 'match': 'exact',
            'etymology_tree': [
                {'level': 0, 'parts': ['rate'], 'text': 'rate'},
                {'level': 1, 'parts': ['rat-', '-e'], 'text': 'rat- + -e'}],
            'root_affixes': [{'type': '词根', 'description': 'rat- 表示“计算”。'}],
            'root_memory': ['原文记忆 <img src=x onerror=alert(1)> & 保留'],
        }],
    }
    return value


class EtymologyPackagingTests(unittest.TestCase):
    def test_compact_assets_keep_source_dom_css_and_controls_while_bundling_ui(self):
        from lxml import html
        original = '<div class="etymology"><p>完整原文 &amp; 对应译文</p></div>'
        entry = {'headword': 'rate', 'source_html': original,
                 'html_sha256': hashlib.sha256(original.encode()).hexdigest()}
        bundle = {'schema': 'cigen-original-viewer.v1', 'images': {},
                  'entry_page_css': 'body{margin:0}', 'css': '.source{color:red}',
                  'viewer_js': '/* original entry controls */'}
        document = original_viewer_document(entry, bundle)
        tree = html.fromstring(document)
        templates = Path(__file__).resolve().parents[1] / 'anki_pipeline/templates'
        styles, scripts = tree.xpath('//style/text()'), tree.xpath('//script/text()')
        self.assertEqual(styles[1], bundle['css'])
        self.assertEqual(scripts[1], bundle['viewer_js'])
        self.assertEqual(tree.xpath('//body/div/p/text()'), ['完整原文 & 对应译文'])
        self.assertTrue(styles[2].endswith((templates / 'etymology-card.css').read_text()))
        self.assertTrue(scripts[2].endswith((templates / 'etymology-card.js').read_text()))
        self.assertIn('cigen:theme', scripts[2])
        self.assertIn('展开例句', scripts[2])
        self.assertIn('收起例句', scripts[2])
        self.assertNotIn('content: "翻译"', styles[2])
        self.assertNotIn('localhost', document)
        self.assertNotIn('allow-same-origin', document)

    def test_compact_ui_templates_are_bound_to_immutable_web_version(self):
        from anki_pipeline.web_preview import _source_checksums
        templates = Path(__file__).resolve().parents[1] / 'anki_pipeline/templates'
        checksums = _source_checksums()
        for name in ('etymology-card.css', 'etymology-card.js'):
            self.assertEqual(checksums['renderer/' + name]['sha256'],
                             hashlib.sha256((templates / name).read_bytes()).hexdigest())

    def test_full_static_resources_keep_deep_tree_breaks_and_highlights(self):
        value = source_card()
        entry = value['etymology']['entries'][0]
        entry['resource_schema'] = 'cigen-resource-sections.v1'
        entry['resource_sections'] = [{'kind': 'tree', 'title': '词源树', 'node': {
            'tag': 'div', 'classes': ['etymology-source-section'], 'children': [
                {'tag': 'div', 'classes': ['etymology-source-heading'], 'children': ['词源树']},
                {'tag': 'div', 'classes': ['etymology-tree-node'], 'level': 4, 'children': ['deep-root']},
                {'tag': 'p', 'classes': ['etymology-related-word'], 'children': [
                    'circu', {'tag': 'mark', 'classes': ['etymology-key'], 'children': ['it']}]},
                {'tag': 'p', 'classes': ['etymology-related-translation'], 'children': ['全部原释义']},
                {'tag': 'span', 'classes': ['etymology-exam-tag'], 'children': ['#考研']},
                {'tag': 'p', 'classes': ['etymology-example-english'], 'children': ['原句 <img src=x>']},
                {'tag': 'br', 'classes': [], 'children': []}, '原译文']}}]
        content = _fields(value, None, 0)[0]['Definition']
        self.assertIn('词源树', content)
        self.assertIn('data-level="4"', content)
        self.assertIn('deep-root', content)
        self.assertIn('<mark class="etymology-key"', content)
        self.assertIn('全部原释义', content)
        self.assertIn('#考研', content)
        self.assertIn('原句 &lt;img src=x&gt;', content)
        self.assertIn('<br>', content)
        self.assertNotIn('<img src=x>', content)
        entry['resource_sections'][0]['node']['children'].append({'tag': 'script', 'classes': [], 'children': ['bad()']})
        with self.assertRaises(ValueError):
            _fields(value, None, 0)

    @unittest.skipUnless((Path(__file__).resolve().parents[2] / 'dictionary-unpacked/cigen-en-new/dictionary.sqlite3').is_file(),
                         'Local root dictionary is not installed')
    def test_actual_ambition_renders_all_source_related_semantics_in_answer_only(self):
        from lxml import html
        dictionary = Path(__file__).resolve().parents[2] / 'dictionary-unpacked/cigen-en-new'
        value = source_card()
        value['word'] = 'ambition'
        del value['etymology']
        enriched, _ = enrich_etymology_cards([value], dictionary)
        content = _fields(enriched[0], None, 0)[0]['Definition']
        field = html.fragment_fromstring(content, create_parent='div')
        frames = field.xpath('.//iframe')
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].get('scrolling'), 'no')
        self.assertNotIn('allow-same-origin', frames[0].get('sandbox'))
        self.assertEqual(len(field.xpath('.//script[@data-cigen-frame-bridge="v1"]')), 1)
        tree = html.fromstring(frames[0].get('srcdoc'))
        names = tree.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," name ")]')
        self.assertEqual([''.join(node.itertext()) for node in names], ['circuit', 'exit', 'transition', 'ambitious', 'transit'])
        self.assertEqual(names[0].xpath('.//span[@class="key"]/text()'), ['it'])
        text = ''.join(tree.xpath('//body')[0].itertext())
        for original in ('词源树', '同根词', 'I ran a circuit of the village.', '我绕村子跑了个环线。', '#高考', '#GMAT'):
            self.assertIn(original, text)
        preview = render_preview(enriched[0], None)
        front = html.fromstring(preview).get_element_by_id('preview-front')
        self.assertEqual(front.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," etymology-related-word ")]'), [])
        self.assertEqual(front.xpath('.//iframe'), [])
        self.assertNotIn('eures://', frames[0].get('srcdoc'))
        self.assertNotIn('/api/', frames[0].get('srcdoc'))
        bundle = enriched[0]['etymology']['original_viewer']
        self.assertEqual(tree.xpath('//style/text()')[1].replace('\r\n','\n'), bundle['css'].replace('\r\n','\n'))
        self.assertEqual(tree.xpath('//script/text()')[1], bundle['viewer_js'])
        self.assertEqual(len(tree.xpath('//style')), 3)
        self.assertIn('max-width:100%', tree.xpath('//style/text()')[2])
        self.assertIn('overflow:hidden!important', tree.xpath('//style/text()')[2])
        self.assertNotIn('window.frameElement', frames[0].get('srcdoc'))
        self.assertNotIn('parent.document', frames[0].get('srcdoc'))
        self.assertEqual(len(bundle['images']), 10)
        self.assertTrue(all(node.get('src','').startswith('data:image/png;base64,') for node in tree.xpath('//img')))
        self.assertTrue(all(node.get('href','').startswith('eudic://') for node in tree.xpath('//a')))
        self.assertIn('activeSameWord', frames[0].get('srcdoc'))

    def test_roots_after_original_meaning_without_other_field_changes(self):
        value = source_card()
        original = copy.deepcopy(value)
        before = copy.deepcopy(value)
        del before['etymology']
        plain, _, _ = _fields(before, None, 0)
        fields, _, _ = _fields(value, None, 0)
        content = fields['Definition']
        self.assertIn('class="etymology-section"', content)
        self.assertLess(content.index('class="exam-frequency"'), content.index('class="etymology-section"'))
        self.assertLess(content.index('frequency-definition-title'), content.index('class="etymology-section"'))
        self.assertLess(content.index('比率</span></div>'), content.index('class="etymology-section"'))
        for name in fields.keys() - {'Definition'}:
            self.assertEqual(fields[name], plain[name], name)
        self.assertTrue(content.startswith(plain['Definition']))
        self.assertEqual(value, original)

    def test_plain_source_text_is_escaped_and_self_contained(self):
        content = _fields(source_card(), None, 0)[0]['Definition']
        self.assertIn('rat- 表示“计算”。', content)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt; &amp; 保留', content)
        self.assertNotIn('<img', content)
        self.assertNotIn('<script', content)
        self.assertNotIn('localhost', content)
        self.assertNotIn('href=', content)
        self.assertIn('style=', content)  # Retained legacy model CSS is sufficient.

    def test_missing_or_empty_entry_leaves_no_blank_root_section(self):
        value = source_card()
        for entries, found in [([], False), ([{
            'id': 12, 'headword': 'rate', 'html_sha256': 'a' * 64, 'match': 'exact',
            'etymology_tree': [{'level': 0, 'parts': ['rate'], 'text': 'rate'}],
            'root_affixes': [], 'root_memory': []}], True)]:
            value['etymology'].update(found=found, has_content=False, entries=entries)
            self.assertNotIn('class="etymology-section"', _fields(value, None, 0)[0]['Definition'])

    def test_bad_schema_and_invalid_structured_text_fail_closed(self):
        value = source_card()
        value['etymology']['schema'] = 'unknown'
        with self.assertRaises(ValueError):
            _fields(value, None, 0)
        value = source_card()
        value['etymology']['entries'][0]['root_affixes'][0]['description'] = 1
        with self.assertRaises(ValueError):
            _fields(value, None, 0)

    def test_preview_and_apkg_match_and_front_has_no_root_content(self):
        from lxml import html
        value = source_card()
        fields, _, _ = _fields(value, None, 0)
        preview = render_preview(value, None)
        self.assertIn(fields['Definition'], preview)
        front = html.fromstring(preview).get_element_by_id('preview-front')
        self.assertEqual(front.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," etymology-section ")]'), [])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'audio'
            audio.mkdir()
            target = root / 'test.apkg'
            build_package([value], audio, target)
            with zipfile.ZipFile(target) as package:
                db = root / 'collection.anki2'
                db.write_bytes(package.read('collection.anki2'))
            with sqlite3.connect(db) as conn:
                packed = conn.execute('SELECT flds FROM notes').fetchone()[0].split('\x1f')
            self.assertEqual(len(packed), 10)
            self.assertEqual(packed[2], fields['Definition'])


if __name__ == '__main__':
    unittest.main()
