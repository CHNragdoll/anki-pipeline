import io
import html
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_final_apkg import Media, capture_inputs, embedded_json, verify_inputs


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        raw = io.BytesIO()
        with zipfile.ZipFile(raw, 'w') as package:
            package.writestr('media', json.dumps({'0': '_old.css', '1': 'audio.mp3'}))
        raw.seek(0)
        self.archive = zipfile.ZipFile(raw)
        self.addCleanup(self.archive.close)
        self.media = Media(self.archive, self.folder)

    def test_rewrites_actual_attributes_only_and_keeps_evidence_and_script(self):
        inert = '<script>const x=\'href="/private" data-web-etymology-srcdoc="abc"\';</script>'
        inert += '<pre>&lt;a href="/proof" data-web-etymology-srcdoc="abc"&gt;</pre><!-- href="/comment" -->'
        text = inert + '\n<a href="/paper">paper</a>\n<link href="/assets/_old.css">'
        result = self.media.references(text, '/source/cards/card.html')
        self.assertTrue(result.startswith(inert))
        self.assertIn('href="http://192.168.3.5:8771/paper"', result)
        self.assertIn('href="_old.css"', result)
        self.assertEqual(self.media.additions, {})

    def test_preserved_nested_srcdoc_is_materialized_with_flat_local_asset(self):
        inside = '<link href="../assets/_old.css"><a href="http://localhost:8765/exam">exam</a>'
        text = '<iframe data-web-etymology-srcdoc="' + html.escape(inside, quote=True) + '"></iframe>'
        result = self.media.references(text, '/source/cards/card.html')
        self.assertNotIn('data-web-etymology-srcdoc=', result)
        self.assertIn('srcdoc=', result)
        self.assertIn('&quot;_old.css&quot;', result)
        self.assertIn('http://192.168.3.5:8765/exam', result)

    def test_same_tag_quoted_proof_and_title_attributes_remain_exact(self):
        text = '''<a href="/actual" data-proof='href="/proof"'>text</a>'''
        result = self.media.references(text, '/source/card.html')
        self.assertEqual(result, text.replace('href="/actual"', 'href="http://192.168.3.5:8771/actual"'))
        text = '''<iframe data-web-etymology-srcdoc='<p>source</p>' title="data-web-etymology-srcdoc='old literal'"></iframe>'''
        result = self.media.references(text, '/source/card.html')
        self.assertIn('title="data-web-etymology-srcdoc=\'old literal\'"', result)
        self.assertTrue(result.startswith("<iframe srcdoc='&lt;p&gt;source&lt;/p&gt;'"))

    def test_many_link_rewrites_preserve_all_other_bytes_in_source_order(self):
        text = '\n'.join(f'<p>{n}<a href="/p/{n}">text{n}</a></p>' for n in range(2000))
        result = self.media.references(text, '/source/card.html')
        self.assertEqual(result, text.replace('href="/', 'href="http://192.168.3.5:8771/'))

    def test_external_rendering_media_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'external rendering media'):
            self.media.references('<img src="https://other.test/image.png">', '/source/card.html')

    def test_embedded_projection_json_roundtrips_without_closing_script(self):
        value = {'proof': '</script><script>danger</script> 中文 < > &'}
        encoded = embedded_json(value)
        self.assertNotIn('<', encoded)
        self.assertEqual(json.loads(encoded), value)

    def test_changed_input_is_detected(self):
        path = self.folder/'runtime.js';path.write_text('original')
        pins = capture_inputs([path]);verify_inputs(pins)
        path.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'generation input changed'):
            verify_inputs(pins)

    def test_original_html_evidence_is_deduplicated_as_inert_literal_media(self):
        original = '<script>evil()</script><p>原文 & 翻译</p>'
        first = self.media.history_evidence(original)
        second = self.media.history_evidence(original)
        self.assertEqual(first, second)
        self.assertEqual(len(self.media.additions), 1)
        self.assertNotIn('<script>evil()', first)
        data = next(iter(self.media.additions.values())).read_text()
        literal = data.split(']=', 1)[1][:-1]
        self.assertEqual(json.loads(literal), original)
        self.assertNotIn('<script>', data)


if __name__ == '__main__':
    unittest.main()
