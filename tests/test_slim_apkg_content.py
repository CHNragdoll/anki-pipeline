import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.slim_apkg_content import Store,Slices,transform,restore,native_index,compact


class SlimContent(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(Path(self.tmp.name))

    def example(self,n):
        return ('<li class="example-card"><p class="example-text">A <span title="a &gt; b">train</span> '+str(n)+'</p>'
            '<p class="example-translation"><span class="translation-label">翻译</span> 火车 '+str(n)+'</p>'
            '<p class="example-source">Source</p><a class="sentence-jump" href="http://local/?anki-codex-sentence=s'+str(n)+'&amp;anki-codex-hash='+('a'*64)+'&amp;anki-codex-review='+('b'*64)+'"></a></li>')

    def test_exact_roundtrip_and_first_ten_are_inline(self):
        raw='\n'.join(self.example(n) for n in range(27))+'\n'
        new=transform(raw,self.store,'examples')
        self.assertEqual(new.count('<li class="example-card">'),10)
        self.assertIn('data-as-kind="examples"',new)
        self.assertEqual(restore(new,self.store),raw)

    def test_nested_audit_dedup_and_panel_offsets_are_invertible(self):
        audit='<details class="sf-ownership-history"><summary>依据</summary>\n'+('证据 &lt;div&gt; '*250)+'<details><summary>嵌套</summary>原文</details></details>'
        rows='\n'.join('<article class="sf-example" data-sf-occurrence-id="'+str(n)+'"><p>原句 '+str(n)+'</p>'+audit+'</article>' for n in range(31))
        raw='<div class="sf-report"><details class="sf-sense"><summary class="sf-row">31 次</summary><div class="sf-panel"><p>年份</p>'+rows+'</div></details></div>'
        new=transform(raw,self.store)
        self.assertIn('class="sf-example"',new)
        self.assertNotIn('class="as-lazy"',new)
        self.assertIn('31 次',new)
        self.assertEqual(restore(new,self.store),raw)
        self.assertLess(len(self.store.files),6)

    def test_script_comments_and_quoted_srcdoc_are_opaque(self):
        raw='<div title="x > y"><iframe srcdoc="&lt;div class=&quot;sf-panel&quot;&gt;x&lt;/div&gt;"></iframe></div><!-- <li class="example-card">fake</li> --><script type="application/json">'+compact({'text':'<div class="sf-panel">fake</div>'})+'</script>'
        self.assertEqual(transform(raw,self.store),raw)

    def test_payload_exact_json_and_original_opening_retained(self):
        raw='<script class="anki-final-reviewed-data" type="application/json">{ "pins": {}, "records": [] }</script>'
        idx=self.store.add('[]');new=transform(raw,self.store,index_part=idx)
        self.assertIn('data-as-index-src=',new)
        self.assertEqual(restore(new,self.store),raw)

    def test_native_physical_index_preserves_actual_text_and_label_removal(self):
        rows=native_index(self.example(2))
        self.assertEqual(rows[0]['english'],'A train 2')
        self.assertEqual(rows[0]['translation'],'火车 2')
        self.assertEqual(json.loads(rows[0]['identity']),['s2','a'*64,'b'*64])

    def test_lazy_sha_mismatch_is_rejected(self):
        part=self.store.add('original');self.store.files[part['sha256']].write_text('broken')
        with self.assertRaises(ValueError):self.store.read(part)

    def test_malformed_target_subtree_fails_closed(self):
        with self.assertRaises(ValueError):Slices('<div class="sf-panel"><p>x</p>')


if __name__=='__main__':unittest.main()
