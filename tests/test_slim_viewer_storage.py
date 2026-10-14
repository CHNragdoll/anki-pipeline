import html
import tempfile
import unittest
from pathlib import Path

from anki_pipeline.slim_viewer_storage import ViewerStore, collect_blocks, factor_frames, restore_frames


class ViewerStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ViewerStore(Path(self.temp.name))
        self.style = '<style>body{color:red}' + ' /* identical original viewer */ ' * 15 + '</style>'
        self.script = '<script>window.original=true;' + ' /* original viewer */ ' * 15 + '</script>'

    def frame(self, word='train', tail=''):
        source = '<html><head>' + self.style + '</head><body><p>' + word + '</p>' + self.script + tail + '</body></html>'
        return '<iframe class="etymology-source-frame" title="词根" srcdoc="' + html.escape(source, quote=True) + '"></iframe>'

    def test_shared_original_code_and_exact_field_inverse(self):
        raw = self.frame() + self.frame('火车')
        blocks = collect_blocks([raw], min_repetitions=2)
        revised = factor_frames(raw, self.store, blocks)
        self.assertNotEqual(raw, revised)
        self.assertEqual(restore_frames(revised, self.store), raw)
        self.assertEqual(len(self.store.files), 2)
        self.assertIn('etymology-source-frame', revised)
        for path in self.store.files.values():
            self.assertNotIn('<script>', path.read_text())
            self.assertNotIn('<style>', path.read_text())

    def test_body_control_order_and_unicode_are_unchanged(self):
        raw = self.frame('novel & 小说', '<button>展开例句</button>') * 2
        revised = factor_frames(raw, self.store, collect_blocks([raw]))
        self.assertEqual(restore_frames(revised, self.store), raw)
        self.assertIn('&lt;button&gt;展开例句&lt;/button&gt;', revised)
        self.assertLess(revised.index('.css'), revised.index('novel'))
        self.assertLess(revised.index('novel'), revised.index('.js'))

    def test_source_with_noncanonical_entities_or_base_is_not_rewritten(self):
        raw = (self.frame(tail='<p title="entity">source</p>') * 2).replace('&quot;', '&#34;')
        self.assertEqual(factor_frames(raw, self.store, collect_blocks([raw])), raw)
        raw = self.frame(tail='<base href="https://example.invalid/">') * 2
        self.assertEqual(factor_frames(raw, self.store, collect_blocks([raw])), raw)

    def test_current_script_introspection_and_data_script_stay_inline(self):
        dangerous = '<script>var original=document.currentScript.textContent;' + 'x' * 300 + '</script>'
        data = '<script type="application/json">{"word":"train"}</script>'
        raw = self.frame(tail=dangerous + data) * 2
        revised = factor_frames(raw, self.store, collect_blocks([raw]))
        self.assertIn(html.escape(dangerous, quote=True), revised)
        self.assertIn(html.escape(data, quote=True), revised)
        self.assertEqual(restore_frames(revised, self.store), raw)

    def test_changed_shared_resource_is_rejected(self):
        raw = self.frame() * 2
        revised = factor_frames(raw, self.store, collect_blocks([raw]))
        next(iter(self.store.files.values())).write_text('tampered')
        with self.assertRaises(ValueError):
            restore_frames(revised, self.store)

    def test_original_crlf_code_bytes_are_not_normalized(self):
        self.style = self.style.replace('body{', '\r\nbody{')
        self.script = self.script.replace('window.', '\r\nwindow.')
        raw = self.frame() * 2
        revised = factor_frames(raw, self.store, collect_blocks([raw]))
        self.assertEqual(restore_frames(revised, self.store), raw)
        self.assertTrue(all(b'\r\n' in p.read_bytes() for p in self.store.files.values()))


if __name__ == '__main__':
    unittest.main()
