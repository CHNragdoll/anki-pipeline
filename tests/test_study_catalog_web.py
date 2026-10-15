import gzip
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.study_catalog_web import HOST_RUNTIME, card_payload, library_html, navigation_index, plain_label, redirect_library_entry, refresh_library, upgrade_card_base, write_library, write_shelf


class CommonWebNavigationTests(unittest.TestCase):
    def test_shelf_uses_actual_generic_metadata_and_safe_relative_book_links(self):
        entries = [{'title': '<任意学科>', 'href': 'book-one/index.html', 'cards': 12, 'groups': 2, 'examples': None},
                   {'title': '第二本', 'href': 'book-two/index.html', 'cards': 1, 'groups': 1, 'examples': 3},
                   {'title': '第三本', 'href': 'book-three/index.html', 'cards': 4, 'groups': 1, 'examples': 0}]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = write_shelf(root, entries)
            page = (root / 'index.html').read_text()
            self.assertEqual(report['books'], 3)
            self.assertEqual(page.count('class="book"'), 3)
            self.assertIn('&lt;任意学科&gt;', page)
            self.assertIn('12 张卡片 · 2 个卡组', page)
            self.assertIn('min-height:104px', page)
            for unsafe in ('https://example.test/book', '//example.test/book', '../book/index.html', '%2e%2e/book', '/book', 'book\\index.html', 'javascript:alert(1)'):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    write_shelf(root, [{**entries[0], 'href': unsafe}])

    def catalog(self):
        return {'title': '完整书名', 'catalog_revision': 'revision', 'cards': [
            {'id': 'one', 'word': 'a<br>b', 'label': 'a<br>b', 'unit': '全书::第一单元',
             'url': 'cards/one.html', 'guid': 'original-guid', 'native_id': 123},
            {'id': 'two', 'word': 'train', 'unit': '全书::第一单元', 'url': 'cards/two.html'},
            {'id': 'three', 'word': 'training', 'unit': '全书::第二单元', 'url': 'cards/three.html'}]}

    def test_navigation_is_lossless_for_order_identity_and_plain_label_only(self):
        source = self.catalog()
        nav = navigation_index(source)
        self.assertEqual(nav['units'], ['全书::第一单元', '全书::第二单元'])
        self.assertEqual(nav['cards'][0], ['one', 'a b', 'a b', 0, 'cards/one.html', '', None, True])
        self.assertEqual([row[0] for row in nav['cards']], ['one', 'two', 'three'])
        self.assertEqual(source['cards'][0]['word'], 'a<br>b')
        self.assertEqual(source['cards'][0]['guid'], 'original-guid')
        self.assertEqual(plain_label('<b>词</b><script>bad()</script><br>义 &amp; 数学 x < y'), '词 义 & 数学 x < y')

    def test_bootstrap_and_versioned_assets_keep_complete_catalog_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = self.catalog()
            original = json.dumps(catalog).encode()
            (root / 'catalog.json').write_bytes(original)
            result = write_library(root, catalog)
            self.assertEqual(result['navigation_cards'], 3)
            self.assertEqual((root / 'catalog.json').read_bytes(), original)
            self.assertEqual(len(list(root.glob('_study_navigation_*.json'))), 1)
            self.assertEqual(len(list(root.glob('_study_library_*.js'))), 1)
            page = (root / 'index.html').read_text()
            self.assertIn('frame', page)
            self.assertIn('f.src=c.initial[4]', page)
            self.assertNotIn("fetch('catalog.json')", page)
            self.assertIn('study-library-config', page)
            self.assertIn('navigationGzip', page)
            compressed = next(root.glob('_study_navigation_*.json.gz'))
            self.assertEqual(gzip.decompress(compressed.read_bytes()), next(root.glob('_study_navigation_*.json')).read_bytes())

    def test_current_metadata_retains_explicit_inventory_and_unknown_counts(self):
        source = self.catalog()
        metadata = {'member_ids': ['one', 'two'], 'cards': {
            'one': {'summary': '真题词频 3 次 n. 铁路', 'example_count': 1, 'deck_name': '全书::必考词::Unit 01'},
            'two': {'summary': '当前补充释义', 'example_count': None},
            'three': {'summary': '完整说明卡', 'example_count': None}}}
        nav = navigation_index(source, metadata)
        self.assertEqual(nav['cards'][0][5:8], ['真题词频 3 次 n. 铁路', 1, True])
        self.assertEqual(nav['cards'][2][7], False)
        self.assertEqual(nav['totals'], {'cards': 2, 'groups': 2, 'examples': 1, 'unknown_example_cards': 1})
        self.assertEqual(nav['units'][0], '全书::必考词::Unit 01')
        with self.assertRaisesRegex(ValueError, 'missing card'):
            navigation_index(source, {'member_ids': ['missing']})

    def test_config_cannot_close_script_or_inject_title(self):
        page = library_html('</title><script>bad()</script>', initial=['</script>', '', '', 0, 'cards/one.html'])
        self.assertIn('&lt;/title&gt;', page)
        self.assertIn('\\u003c/script>', page)
        self.assertNotIn('<script>bad()', page)

    def test_new_exports_index_current_projection_and_keep_new_content_listed(self):
        from anki_pipeline import study_catalog_export as exporter
        model = {'id': 7, 'css': '.card{color:black}', 'tmpls': [
            {'name': '正向', 'qfmt': '{{Word}}', 'afmt': '{{Definition}}'},
            {'name': '反向', 'qfmt': '{{Definition}}', 'afmt': '{{Word}}'}]}
        notes = {identity: {'id': identity, 'guid': identity + '-guid', 'ordinal': index, 'kind': kind,
                           'field_names': ['Word', 'Definition', 'Examples'],
                           'fields': [identity, '当前统一释义', '<ul><li class="example-card">原句</li></ul>'],
                           'model': model}
                 for index, (identity, kind) in enumerate([('train', 'word'), ('new', 'word'), ('guide', 'guide')])}

        class Rows(list):
            def fetchone(self): return self[0] if self else None
            def fetchall(self): return list(self)

        class Database:
            def execute(self, query, params):
                if query.startswith('select value from metadata'): return Rows([('catalog-object',)])
                if query.startswith('select note_id'): return Rows((identity,) for identity in notes)
                if query.startswith('select n.native_id'):
                    return Rows([(params[1] + '-0', 0, '库::新单元')] +
                                ([(params[1] + '-1', 1, '库::新单元')] if params[1] == 'train' else []))
                if query.startswith('select name,object_id'): return Rows()
                raise AssertionError(query)

        retained = {'cards': [{'id': 'train', 'deckName': '库::原分组::Unit 01',
                                'definition': '过时摘要', 'exampleCount': 999}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(exporter, 'project_note', side_effect=lambda db, book, identity: notes[identity]), patch.object(exporter.c, 'get_object', return_value=json.dumps(retained).encode()):
            exporter._web(Database(), {'id': 'subject-neutral', 'title': '任意学科', 'scope': {}, 'revision': 3,
                                       'runtime': {'sources': {}, 'generated': {}}}, Path(tmp), None)
            nav = json.loads(next((Path(tmp) / 'web').glob('_study_navigation_*.json')).read_bytes())
            self.assertEqual(nav['totals']['cards'], 3)
            self.assertEqual([row[7] for row in nav['cards']], [True, True, True, False])
            self.assertEqual(nav['cards'][0][5:7], ['当前统一释义', 1])
            self.assertEqual(nav['units'][nav['cards'][0][3]], '库::原分组::Unit 01')
            self.assertEqual([row[0] for row in nav['cards'][:2]], ['train-0', 'train-1'])

    def test_card_host_upgrade_retains_every_authored_payload_byte(self):
        payload = json.dumps(['<main>original chunks 中文 ;let answer=false;const side= quoted example</main>',
                              '<details>full audit 音频 ].map(content=>content.replace( another example</details>'], ensure_ascii=False).replace('<', '\\u003c').encode()
        raw = b'<head></head><script>const sides=' + payload + b';let answer=false;const side=document.getElementById("study-side");rest unchanged</script>'
        changed = upgrade_card_base(raw)
        self.assertIn(payload, changed)
        self.assertIn(b'absoluteBase.href=new URL("../media/",location.href)', changed)
        self.assertIn(b'side.srcdoc=sides[answer?1:0]', changed)
        self.assertIn(b'parent.postMessage', changed)
        self.assertEqual(upgrade_card_base(changed), changed)
        self.assertEqual(card_payload(raw), payload)
        self.assertEqual(card_payload(changed), payload)
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            upgrade_card_base(b'<html>unknown host</html>')

    def test_refresh_reuses_immutable_cards_and_media_and_refuses_partial_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'original'
            source.mkdir()
            catalog = {**self.catalog(), 'schema': 'shared-book-web.v1', 'catalog_revision': 11}
            (source / 'catalog.json').write_text(json.dumps(catalog))
            (source / 'index.html').write_text('Original recoverable directory host')
            (source / 'cards').mkdir()
            (source / 'media').mkdir()
            for card in catalog['cards']:
                (source / card['url']).write_text('Original bilingual chunks and full audit')
            (source / 'media' / 'audio.mp3').write_bytes(b'original audio bytes')
            target = root / 'updated'
            with self.assertRaises(FileNotFoundError):
                refresh_library(source, target)
            self.assertFalse(target.exists())
            (source / 'COMPLETE.json').write_text(json.dumps({'format': 'web', 'cards': 3, 'notes': 3}))
            with self.assertRaisesRegex(ValueError, 'revision'):
                refresh_library(source, target, expected_revision=12)
            result = refresh_library(source, target, expected_revision=11)
            self.assertEqual(result['source_catalog_revision'], 11)
            self.assertTrue((target / 'cards').is_symlink())
            self.assertTrue((target / 'media').is_symlink())
            self.assertEqual((target / 'catalog.json').read_bytes(), (source / 'catalog.json').read_bytes())
            self.assertEqual((target / 'cards' / 'one.html').read_text(), 'Original bilingual chunks and full audit')
            self.assertEqual((target / 'media' / 'audio.mp3').read_bytes(), b'original audio bytes')
            self.assertEqual(json.loads((target / 'COMPLETE.json').read_text())['cards'], 3)
            with self.assertRaises(FileExistsError):
                refresh_library(source, target)
            catalog_before = (source / 'catalog.json').read_bytes()
            marker_before = (source / 'COMPLETE.json').read_bytes()
            redirect = redirect_library_entry(source, target)
            self.assertEqual(Path(redirect['backup']).read_text(), 'Original recoverable directory host')
            self.assertEqual((source / 'catalog.json').read_bytes(), catalog_before)
            self.assertEqual((source / 'COMPLETE.json').read_bytes(), marker_before)
            self.assertEqual(redirect['relative_target'], '../updated/index.html')
            self.assertIn('target.search=location.search;target.hash=location.hash;', (source / 'index.html').read_text())
            with self.assertRaisesRegex(ValueError, 'different'):
                redirect_library_entry(source, source)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for host regression')
    def test_browser_navigation_empty_search_hash_and_keyboard_regressions(self):
        # Test the real common host with a DOM. Card bodies are deliberately not
        # loaded here: the browser acceptance separately covers actual rendering.
        script = r'''
const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('node:fs');
const {runtime,data,page}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
const d=new JSDOM(page,{url:'http://localhost/book/index.html',runScripts:'outside-only',pretendToBeVisual:true});
const w=d.window;w.fetch=async()=>({ok:true,json:async()=>data});w.eval(runtime);await new Promise(r=>setTimeout(r,20));
const aliases={previous:'previous-card',next:'next-card',position:'card-position',query:'word-search',list:'word-list'};const $=id=>w.document.getElementById(aliases[id]||id),input=value=>{$('query').value=value;$('query').dispatchEvent(new w.Event('input'))};
assert.equal($('position').textContent,'1 / 3');assert.equal($('list').querySelector('.word-entry-name').textContent,'a b');assert.equal($('previous').disabled,true);
$('next').click();assert.equal($('position').textContent,'2 / 3');assert.equal($('frame').dataset.studyCardId,'two');
// A repeated selection must keep the actual mounted side instead of resetting it.
$('frame').dataset.keep='answer';const before=$('frame').getAttribute('src');$('list').querySelector('[data-card-id="two"]').click();assert.equal($('frame').getAttribute('src'),before);
input('definitely absent');assert.equal($('position').textContent,'0 / 0');assert.equal($('frame').hidden,true);assert.equal($('frame').hasAttribute('src'),false);assert.equal($('next').disabled,true);assert.equal($('previous').disabled,true);assert.equal($('empty').hidden,false);
input('train');assert.equal($('position').textContent,'1 / 2');assert.equal($('frame').dataset.studyCardId,'two');
w.document.querySelector('.deck-entry[data-deck-key="1"]').click();assert.equal($('position').textContent,'1 / 1');assert.equal($('frame').dataset.studyCardId,'three');
assert.equal(new URLSearchParams(w.location.hash.slice(1)).get('deck'),'1');
w.location.hash='card=one';await new Promise(r=>setTimeout(r,20));assert.equal(w.document.querySelector('.deck-entry[aria-current="page"]').dataset.deckKey,'');assert.equal($('query').value,'');assert.equal($('position').textContent,'1 / 3');
$('query').dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal($('position').textContent,'1 / 3');
w.document.body.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));assert.equal($('position').textContent,'2 / 3');
d.window.close();console.log('common host DOM regression passed');
// A full inventory keeps its old information density and scroll access without
// putting thousands of interactive rows on the main thread.
const large=new JSDOM(page,{url:'http://localhost/book/index.html#card=row300',runScripts:'outside-only',pretendToBeVisual:true}),lw=large.window;
const largeData={...data,cards:Array.from({length:500},(_,i)=>['row'+i,'word'+i,'word'+i,0,'cards/one.html',i===300?'铁路 专门释义':'释义'+i,2,true]),totals:{cards:500,groups:1,examples:1000}};
// Browsers clamp scrollTop while an empty virtual list has no scroll range;
// jsdom normally does not. Reproduce the native constraint for deep links.
const preList=lw.document.getElementById('word-list');let scrollPosition=0;Object.defineProperty(preList,'scrollTop',{get:()=>scrollPosition,set:value=>{const height=Array.from(preList.children).reduce((sum,li)=>sum+(li.classList.contains('virtual-spacer')?parseFloat(li.style.height)||0:91),0);scrollPosition=Math.min(Math.max(0,value),Math.max(0,height-400))}});
lw.matchMedia=()=>({matches:true,addEventListener(){}});lw.fetch=async()=>({ok:true,json:async()=>largeData});lw.eval(runtime);await new Promise(r=>setTimeout(r,25));
const ll=lw.document.getElementById('word-list');assert.equal(ll.querySelectorAll('.word-entry').length,90);assert.equal(lw.document.getElementById('browse-panel').hidden,true);
assert.equal(ll.querySelector('.word-entry[aria-current="true"] .word-entry-name')?.textContent,'word300');assert.ok(ll.scrollTop>0);
lw.document.getElementById('browse-toggle').click();assert.equal(lw.document.getElementById('browse-panel').hidden,false);
ll.scrollTop=23000;ll.dispatchEvent(new lw.Event('scroll'));await new Promise(r=>setTimeout(r,40));assert.equal(ll.querySelectorAll('.word-entry').length,90);assert.notEqual(ll.querySelector('.word-entry-name').textContent,'word0');
const lq=lw.document.getElementById('word-search');lq.value='铁路';lq.dispatchEvent(new lw.Event('input'));assert.equal(lw.document.getElementById('card-position').textContent,'1 / 1');assert.equal(ll.querySelector('.word-entry-name').textContent,'word300');
ll.querySelector('.word-entry').click();assert.equal(lw.document.getElementById('browse-panel').hidden,true);
const outer=lw.document.getElementById('frame').contentDocument;outer.open();outer.write('<!doctype html><body></body>');outer.close();const button=outer.createElement('button');button.id='study-flip';button.setAttribute('aria-pressed','false');button.onclick=()=>button.setAttribute('aria-pressed',String(button.getAttribute('aria-pressed')!=='true'));outer.body.append(button);
lw.document.body.dispatchEvent(new lw.KeyboardEvent('keydown',{key:' ',code:'Space',bubbles:true,cancelable:true}));assert.equal(button.getAttribute('aria-pressed'),'true');assert.equal(lw.document.getElementById('flip-card').textContent,'返回正面');large.window.close();
// Compressed delivery and its compatibility fallback use the exact same data.
if(typeof global.DecompressionStream==='function'){
const markup=page;
for(const compressedWorks of [true,false]){
 const dom=new JSDOM(markup,{url:'http://localhost/book/index.html',runScripts:'outside-only',pretendToBeVisual:true}),win=dom.window,calls=[];
 win.document.getElementById('study-library-config').textContent=JSON.stringify({navigation:'nav.json',navigationGzip:'nav.json.gz'});
 win.DecompressionStream=global.DecompressionStream;win.Response=global.Response;
 win.fetch=async url=>{calls.push(url);if(url.endsWith('.gz')){if(!compressedWorks)throw Error('offline gzip fallback');return new Response(require('node:zlib').gzipSync(Buffer.from(JSON.stringify(data))))}return new Response(JSON.stringify(data))};
 win.console.warn=()=>{};win.eval(runtime);
 for(let n=0;n<100&&win.document.querySelector('#card-position').textContent!=='1 / 3';n++)await new Promise(r=>setTimeout(r,10));
 assert.equal(win.document.querySelector('#card-position').textContent,'1 / 3');
 assert.deepEqual(calls,compressedWorks?['nav.json.gz']:['nav.json.gz','nav.json']);dom.window.close();
}
}
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script],
                                input=json.dumps({'runtime': HOST_RUNTIME, 'data': navigation_index(self.catalog()),'page':library_html('测试书',navigation_href='nav.json')}),
                                text=True, capture_output=True, timeout=60)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom development dependency')
        self.assertEqual(result.returncode, 0, result.stderr)
