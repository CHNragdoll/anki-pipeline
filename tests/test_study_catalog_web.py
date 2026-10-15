import gzip
import json
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.study_catalog_web import DEFER_SCRIPTS_RUNTIME, SHARED_FRAME_RUNTIME, HOST_RUNTIME, card_shell, script_deferral_policy, shared_frame_html, write_deferred_inline_assets, card_payload, library_html, navigation_index, plain_label, redirect_library_entry, refresh_library, upgrade_card_base, write_library, write_shelf


class CommonWebNavigationTests(unittest.TestCase):
    def test_shelf_reuses_original_dom_progress_and_downloads(self):
        entries = [{'study_book_id': name, 'href': 'book-' + name + '/index.html'}
                   for name in ('alpha', 'beta', 'gamma')]
        original = '<!doctype html><html><head><link href="/bookshelf.css"><script src="/web-study/bookshelf-study.js" defer></script></head><body>'
        for entry in entries:
            name = entry['study_book_id']
            original += ('<article class="book" data-study-book="' + name + '"><div class="book-spine">Original cover ' + name + '</div>'
                         '<p data-book-progress>Original progress</p><a class="start-book" href="/web-study/study.html?book=' + name + '">开始学习</a>'
                         '<a class="browse-book" href="/old-' + name + '">浏览全书</a><a class="download" href="' + name + '.apkg" download>下载</a></article>')
        original += '<a class="quiet-link" href="#home-help">使用帮助</a><details id="home-help">Original help</details></body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'index.html'
            source.write_text(original)
            root = base / 'new'
            report = write_shelf(root, entries, source=source, service_origin='http://192.168.3.5:8771')
            page = (root / 'index.html').read_text()
            self.assertEqual(report['books'], 3)
            expected = original
            for entry in entries:
                expected = expected.replace('/old-' + entry['study_book_id'], '/new/' + entry['href'])
            expected = expected.replace('href="#home-help"', 'href="/new/index.html#home-help"')
            self.assertEqual(page[page.index('<body>'):], expected[expected.index('<body>'):])
            import re
            from urllib.parse import urljoin, urlsplit
            help_href = re.search(r'<a class="quiet-link" href="([^"]+)"', page)[1]
            help_url = urlsplit(urljoin('http://192.168.3.5:8771/', help_href))
            self.assertEqual(help_url.path, '/new/index.html')
            self.assertEqual(help_url.fragment, 'home-help')
            self.assertEqual(source.read_text(), original)
            self.assertIn('<base href="http://192.168.3.5:8771/">', page)
            self.assertIn('if(location.origin!==target.origin)', page)
            self.assertEqual(report['stable_study_ids'], ['alpha', 'beta', 'gamma'])
            for unsafe in ('https://example.test/book', '//example.test/book', '../book/index.html', '%2e%2e/book', '/book', 'book\\index.html', 'javascript:alert(1)'):
                with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                    write_shelf(root, [{**entries[0], 'href': unsafe}], source=source, service_origin='http://192.168.3.5:8771')
            with self.assertRaisesRegex(ValueError, 'missing'):
                write_shelf(root, [{'study_book_id': 'unknown', 'href': 'book/index.html'}], source=source, service_origin='http://192.168.3.5:8771')
            with self.assertRaisesRegex(ValueError, 'overwritten'):
                write_shelf(base, entries, source=source, service_origin='http://192.168.3.5:8771')

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
            {'name': '正向', 'qfmt': '{{Word}}<script>window.unreviewedBookBehavior=true;</script>', 'afmt': '{{Definition}}'},
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
            report = exporter._web(Database(), {'id': 'subject-neutral', 'title': '任意学科', 'scope': {}, 'revision': 3,
                                       'runtime': {'sources': {}, 'generated': {}}}, Path(tmp), None)
            nav = json.loads(next((Path(tmp) / 'web').glob('_study_navigation_*.json')).read_bytes())
            self.assertEqual(nav['totals']['cards'], 3)
            self.assertEqual([row[7] for row in nav['cards']], [True, True, True, False])
            self.assertEqual(nav['cards'][0][5:7], ['当前统一释义', 1])
            self.assertEqual(nav['units'][nav['cards'][0][3]], '库::原分组::Unit 01')
            self.assertEqual([row[0] for row in nav['cards'][:2]], ['train-0', 'train-1'])
            page = (Path(tmp) / 'web/index.html').read_text()
            config = json.loads(re.search(r'<script id="study-library-config" type="application/json">(.*?)</script>', page, re.S)[1])
            self.assertIn('StudySharedFrame', config['sharedFrame']['html'])
            self.assertEqual(config['sharedFrame']['policy']['external'], {})
            self.assertIn('preparedIndex', config['sharedFrame'])
            self.assertGreater(report['delivery']['fallbacks'], 0)
            self.assertFalse(report['delivery']['qa_observation_enabled'])
            source = next((Path(tmp) / 'web/cards').glob('*.html')).read_bytes()
            self.assertTrue(any('_study_' in side for side in json.loads(card_payload(source))))

    def test_shared_mount_factory_collects_only_approved_exact_bytes(self):
        from anki_pipeline import study_catalog_web as web
        import hashlib
        known = 'window.AnkiSlimApkgDispose();'
        inline = '\nwindow.fixture=true;\n'
        digest = hashlib.sha256(inline.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'AUDITED_MOUNT_INLINE_SHA256', frozenset({digest})):
            root = Path(tmp)
            (root / 'media').mkdir()
            (root / 'media/known.js').write_text(known)
            (root / 'media/unknown.js').write_text('window.unknown=true;')
            audit = web.SharedMountAudit()
            source = '<script src="known.js"></script><script src="unknown.js"></script><script type>' + inline + '</script><script type="application/json">{"source":"preserved"}</script>'
            audit.observe([source, source])
            config = web.audited_shared_config(root, audit)
            self.assertEqual(set(config['policy']['external']), {'known.js'})
            self.assertEqual(config['policy']['inline'][0]['source'], inline)
            self.assertEqual((root / config['policy']['inline'][0]['src']).read_bytes(), inline.encode())
            self.assertEqual(audit.sides, 2)
            self.assertEqual(len(audit.inline), 1)
            self.assertEqual(source.count(inline), 1)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for mounting regression')
    def test_opt_in_script_deferral_preserves_markup_order_and_rejects_unsafe_documents(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)
            (media / 'one.js').write_text('window.first = true;')
            (media / 'two.js').write_text('window.second = true;')
            (media / 'unsafe.js').write_text('document.write("parser-time content");')
            source = '<!doctype html><head></head><body><main id="front">原正面</main><script src="one.js"></script><script src="two.js"></script><main id="answer">完整背面、审核、细块</main></body>'
            import hashlib
            self.assertEqual(script_deferral_policy([source], media), {})
            audits = {hashlib.sha256(path.read_bytes()).hexdigest() for path in media.iterdir()}
            policy = script_deferral_policy([source, '<script src="unsafe.js"></script>'], media, audited_sha256=audits)
            self.assertEqual(set(policy), {'one.js', 'two.js'})
            payload = json.dumps([source, source], ensure_ascii=False).replace('<', '\\u003c').encode()
            wrapper = card_shell(payload.decode(), '../media/', script_policy=policy).encode()
            self.assertEqual(card_payload(wrapper), payload)
            script = r'''const {JSDOM,VirtualConsole,requestInterceptor}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
const {runtime,source,policy,wrapper}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
const inert=new JSDOM('',{runScripts:'outside-only'});inert.window.eval(runtime+';window.mount=prepareScriptMount');
const mount=inert.window.mount,changed=mount(source,policy);
assert.equal(changed.inserted,2);assert.equal(changed.html.replaceAll(' defer>','>'),source);
for(const [value,reason] of [[source.replace('</body>','<script>window.inline=first</script></body>'),'inline-classic-script'],[source.replace('two.js','unsafe.js'),'unaudited-script'],[source.replace('src="one.js"','defer src="one.js"'),'mixed-defer-and-parser-blocking'],[source.replace('src="one.js"','async src="one.js"'),'unordered-script'],[source.replace('src="one.js"','type="module" src="one.js"'),'unsupported-script-type']]){const result=mount(value,policy);assert.equal(result.html,value);assert.equal(result.reason,reason)}
const resources={interceptors:[requestInterceptor(async request=>{await new Promise(resolve=>setTimeout(resolve,15));return new Response('window.executed.push({name:'+JSON.stringify(new URL(request.url).pathname)+',answerPresent:!!document.getElementById("answer")});',{headers:{'Content-Type':'application/javascript'}})})]};
// Parse and execute the complete generated wrapper. Evaluating the helper
// alone misses literal closing-script text prematurely ending its HTML block.
const shellErrors=[],shellConsole=new VirtualConsole();shellConsole.on('jsdomError',error=>shellErrors.push(error.message));
const shell=new JSDOM(wrapper,{url:'http://localhost/book/cards/one.html',runScripts:'dangerously',virtualConsole:shellConsole});
const mounted=shell.window.document.getElementById('study-side');
assert.deepEqual(shellErrors,[]);assert.ok(mounted.srcdoc.includes('src="one.js" defer>'));assert.equal(mounted.dataset.mountReason,'deferred-in-source-order');assert.equal(mounted.dataset.deferredScripts,'2');
assert.equal(Array.from(shell.window.document.body.children,el=>el.tagName).join(','),'BUTTON,IFRAME,SCRIPT');
assert.equal(Array.from(shell.window.document.body.childNodes).filter(node=>node.nodeType===3&&node.textContent.trim()).length,0);
shell.window.document.getElementById('study-flip').click();assert.equal(mounted.title,'学习卡片背面');
assert.equal(mounted.dataset.deferredScripts,'2');shell.window.close();
const results={};
for(const [name,html] of [['before',source],['after',changed.html]]){
const dom=new JSDOM(html,{url:'http://localhost/media/',runScripts:'dangerously',resources,beforeParse(window){window.executed=[]}});
await new Promise(resolve=>dom.window.addEventListener('load',resolve,{once:true}));
assert.deepEqual(Array.from(dom.window.executed,row=>row.name),['/media/one.js','/media/two.js']);
results[name]=Array.from(dom.window.executed,row=>row.answerPresent);assert.equal(dom.window.document.getElementById('answer').textContent,'完整背面、审核、细块');dom.window.close();
}
// jsdom parses the supplied string eagerly; actual parser blocking and paint
// timing are browser acceptance, not a timing assertion in this DOM test.
assert.deepEqual(results.after,[true,true]);inert.window.close();console.log('ordered external execution and complete markup passed');
})().catch(error=>{console.error(error);process.exitCode=1});'''
            result = subprocess.run([shutil.which('node'), '-e', script],
                                    input=json.dumps({'runtime': DEFER_SCRIPTS_RUNTIME, 'source': source, 'policy': policy, 'wrapper': wrapper.decode()}),
                                    text=True, capture_output=True, timeout=60)
            if "Cannot find module 'jsdom'" in result.stderr:
                self.skipTest('requires existing jsdom development dependency')
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for inline script regression')
    def test_audited_inline_assets_keep_exact_bytes_and_execution_order(self):
        import hashlib
        code = '\nwindow.executed.push("inline");\n'
        digest = hashlib.sha256(code.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'exact-byte audit'):
                write_deferred_inline_assets(root, [code], audited_sha256=set())
            rules = write_deferred_inline_assets(root, [code, code], audited_sha256={digest})
            self.assertEqual(len(rules), 1)
            self.assertEqual((root / rules[0]['src']).read_bytes(), code.encode())
            rules[0]['src'] = 'http://localhost/media/' + rules[0]['src']
            source = '<!doctype html><body><script src="one.js"></script><script>' + code + '</script><script src="two.js"></script><p>原完整内容</p></body>'
            script = r'''const {JSDOM,requestInterceptor}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');const {runtime,source,code,rule}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const inert=new JSDOM('',{url:'http://localhost/media/',runScripts:'outside-only'});inert.window.eval(runtime+';window.mount=prepareScriptMount');const result=inert.window.mount(source,{external:{'one.js':'approved','two.js':'approved'},inline:[rule]});assert.equal(result.inserted,3);assert.equal(result.externalized,1);assert.equal(source.includes(code),true);const empty=source.replace('<script>'+code,'<script src="">'+code),retained=inert.window.mount(empty,{external:{'one.js':'approved','two.js':'approved'},inline:[rule]});assert.equal(retained.reason,'empty-script-resource');assert.equal(retained.html,empty);
for(const html of [source,result.html]){const resources={interceptors:[requestInterceptor(request=>new Response(request.url===rule.src?code:'window.executed.push('+JSON.stringify(new URL(request.url).pathname)+');',{headers:{'Content-Type':'application/javascript'}}))]};const dom=new JSDOM(html,{url:'http://localhost/media/',runScripts:'dangerously',resources,beforeParse(window){window.executed=[]}});await new Promise(resolve=>dom.window.addEventListener('load',resolve,{once:true}));assert.deepEqual(Array.from(dom.window.executed),['/media/one.js','inline','/media/two.js']);assert.equal(dom.window.document.querySelector('p').textContent,'原完整内容');dom.window.close()}inert.window.close()})().catch(error=>{console.error(error);process.exitCode=1});'''
            result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({'runtime': DEFER_SCRIPTS_RUNTIME, 'source': source, 'code': code, 'rule': rules[0]}), text=True, capture_output=True, timeout=60)
            if "Cannot find module 'jsdom'" in result.stderr:
                self.skipTest('requires existing jsdom development dependency')
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for shared frame regression')
    def test_shared_frame_extracts_data_without_evaluating_wrapper_and_preserves_both_sides(self):
        sides = ['<!doctype html><head><base href="../media/"></head><body>原文 ;let answer=false;const side= [ ] \\"</body>',
                 '<!doctype html><head><base href="../media/"></head><body>完整背面、审核、音频</body>']
        payload = json.dumps(sides, ensure_ascii=False).replace('<', '\\u003c')
        wrapper = card_shell(payload, '../media/')
        helper = HOST_RUNTIME[HOST_RUNTIME.index('function readAuthoredCard('):HOST_RUNTIME.index('let sharedReady=')]
        script = r'''const {JSDOM,VirtualConsole}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
const {helper,wrapper,payload,sides,shell}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const parser=new JSDOM('',{url:'http://localhost/book/index.html',runScripts:'outside-only'});parser.window.eval(helper+';window.parse=readAuthoredCard');
const parsed=parser.window.parse(wrapper,'http://localhost/book/cards/one.html');assert.equal(parsed.literal,payload);assert.deepEqual(Array.from(parsed.sides),sides);assert.equal(parsed.base,'http://localhost/book/media/');
for(const bad of [wrapper.replace('new URL("../media/"','new URL("https://other.test/"'),wrapper.replace('const sides=[','const sides={'),wrapper.replace('.map(content=>content.replace(','.unknown('),wrapper.replace('};show();','};sides[0]="MUTATED";show();')])assert.throws(()=>parser.window.parse(bad,'http://localhost/book/cards/one.html'));
const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));const dom=new JSDOM(shell,{url:'http://localhost/book/index.html',runScripts:'dangerously',virtualConsole:vc}),w=dom.window;
assert.deepEqual(errors,[]);assert.ok(w.StudySharedFrame);assert.equal(await w.StudySharedFrame.mount({...parsed,id:'one',token:2,requestedAt:0,policy:{},execution:'parser'}),true);
let side=w.document.getElementById('study-side');assert.equal(side.srcdoc,sides[0].replace('<base href="../media/">','<base href="http://localhost/book/media/">'));
w.document.getElementById('study-flip').click();side=w.document.getElementById('study-side');assert.equal(side.title,'学习卡片背面');assert.ok(side.srcdoc.includes('完整背面、审核、音频'));
assert.equal(await w.StudySharedFrame.mount({...parsed,id:'obsolete',token:1,policy:{}}),false);assert.equal(side.dataset.cardId,'one');assert.deepEqual(errors,[]);dom.window.close();parser.window.close();})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({'helper': helper, 'wrapper': wrapper, 'payload': payload, 'sides': sides, 'shell': shared_frame_html()}), text=True, capture_output=True, timeout=60)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom development dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for atomic document regression')
    def test_atomic_document_commits_complete_body_before_scripts_and_uses_natural_lifecycle(self):
        sides = ['<!doctype html><html lang="zh"><head><base href="../media/"><script src="one.js"></script></head><body><main class="vocab-back"><section class="meaning-section">完整释义</section><section class="examples-section"><p class="example-card">完整原句与细块</p></section></main><script src="two.js"></script></body></html>'] * 2
        script = r'''const {JSDOM,VirtualConsole,requestInterceptor}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');const {shell,sides}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));const outer=new JSDOM(shell,{url:'http://localhost/book/index.html',runScripts:'dangerously',virtualConsole:vc}),w=outer.window,api=w.StudySharedFrame;
const ready=api.mount({id:'atomic',token:1,sides,base:'http://localhost/book/media/',baseTags:['<base href="../media/">','<base href="../media/">'],policy:{'one.js':'audited','two.js':'audited'}});await new Promise(r=>setTimeout(r,0));const side=w.document.getElementById('study-side');assert.match(side.dataset.mountReason,/^atomic-/);assert.ok(side.srcdoc.includes('StudySharedFrame.commit'));assert.equal(w.document.getElementById('study-flip').disabled,true);
const scriptCode=`window.runs=window.runs||[];window.runs.push({name:document.currentScript.src,complete:!!document.querySelector('.example-card'),state:document.readyState});if(!window.lifecycle){window.lifecycle={dcl:0,load:0,branch:0};document.addEventListener('DOMContentLoaded',()=>window.lifecycle.dcl++,{once:true});window.addEventListener('load',()=>window.lifecycle.load++,{once:true});if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>window.lifecycle.branch++,{once:true});else window.lifecycle.branch++}`;
const resources={interceptors:[requestInterceptor(request=>new Response(scriptCode,{headers:{'Content-Type':'application/javascript'}}))]};let child;
child=new JSDOM(side.srcdoc,{url:'http://localhost/book/inner.html',runScripts:'dangerously',resources,virtualConsole:vc,beforeParse(win){Object.defineProperty(win,'parent',{value:w});Object.defineProperty(side,'contentDocument',{configurable:true,get:()=>win.document});Object.defineProperty(side,'contentWindow',{configurable:true,get:()=>win})}});
assert.equal(await ready,true);assert.equal(w.document.getElementById('study-flip').disabled,false);await new Promise(r=>child.window.addEventListener('load',r,{once:true}));assert.deepEqual(Array.from(child.window.runs,r=>new URL(r.name).pathname),['/book/media/one.js','/book/media/two.js']);assert.ok(child.window.runs.every(r=>r.complete));assert.equal(child.window.document.querySelector('.example-card').textContent,'完整原句与细块');assert.equal(child.window.lifecycle.branch,1);assert.equal(child.window.lifecycle.load,1);
// Dynamically loaded approved scripts use their readyState-complete branch;
// parser-only lifecycle scripts remain original-parser documents without a policy.
assert.ok(child.window.runs.every(r=>r.state!=='loading')||child.window.lifecycle.dcl===1);assert.deepEqual(errors,[]);child.window.close();outer.window.close();
for(const defer of [false,true]){const before=new JSDOM('<!doctype html><head><script '+(defer?'defer ':'')+'src="lifecycle.js"></script></head><body>完整正文</body>',{url:'http://localhost/',runScripts:'dangerously',resources:{interceptors:[requestInterceptor(()=>new Response(`window.counts={dcl:0,load:0,ready:0};document.addEventListener('DOMContentLoaded',()=>counts.dcl++,{once:true});window.addEventListener('load',()=>counts.load++,{once:true});if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>counts.ready++,{once:true});else counts.ready++;`,{headers:{'Content-Type':'application/javascript'}}))]}});await new Promise(r=>before.window.addEventListener('load',r,{once:true}));assert.equal(before.window.counts.dcl,1);assert.equal(before.window.counts.load,1);assert.equal(before.window.counts.ready,1);before.window.close()}
})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({'shell': shared_frame_html(), 'sides': sides}), text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for bounded diagnostics regression')
    def test_qa_diagnostics_keep_first_render_and_ready_evidence_bounded(self):
        helper = SHARED_FRAME_RUNTIME[SHARED_FRAME_RUNTIME.index('function recordEvent('):SHARED_FRAME_RUNTIME.index('function report(')]
        script = r'''const assert=require('node:assert/strict'),fs=require('fs');const helper=JSON.parse(fs.readFileSync(0,'utf8'));const append=new Function(helper+';return recordEvent')(),row={events:[]};for(const event of ['atomic-body-commit','first-any-animation-frame','first-visible-animation-frame','DOMContentLoaded'])append(row,{event});for(let i=0;i<200;i++)append(row,{event:'child-diagnostic',i});append(row,{event:'native-state',nativeStates:['ready']});for(let i=200;i<600;i++)append(row,{event:'child-diagnostic',i});assert.equal(row.events.length,100);for(const name of ['atomic-body-commit','first-any-animation-frame','first-visible-animation-frame','DOMContentLoaded','native-state'])assert.ok(row.events.some(x=>x.event===name),name);assert.equal(row.events.at(-1).i,599);'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps(helper), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for atomic boundary regression')
    def test_atomic_stale_preload_failure_and_noscript_retain_current_semantics(self):
        script = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');const {shell}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const outer=new JSDOM(shell,{url:'http://localhost/book/index.html',runScripts:'dangerously'}),w=outer.window,api=w.StudySharedFrame,messages=[];w.postMessage=value=>messages.push(value);const html=body=>'<!doctype html><head><base href="../media/"></head><body>'+body+'</body>';const front=html('<p>当前完整正文</p>'),back=front.replace('</head>','<link rel="stylesheet" href="slow.css"></head>');const packet=(id,token,sides)=>({id,token,sides,base:'http://localhost/book/media/',baseTags:['<base href="../media/">','<base href="../media/">'],policy:{}});
async function commit(promise){await new Promise(r=>setTimeout(r,0));const side=w.document.getElementById('study-side'),match=/commit\(document,("[^"]+")\);/.exec(side.srcdoc);assert.ok(match);assert.equal(api.commit(side.contentDocument,JSON.parse(match[1])),true);assert.equal(await promise,true)}
await commit(api.mount(packet('A',1,[front,back])));w.document.getElementById('study-flip').click();const preload=w.document.querySelector('link[rel=preload]');assert.ok(preload);await commit(api.mount(packet('B',2,[front,front])));preload.dispatchEvent(new w.Event('error'));await new Promise(r=>setTimeout(r,0));assert.equal(w.document.getElementById('study-side').dataset.cardId,'B');assert.equal(messages.filter(row=>row.type==='study-source-error').length,0,'obsolete A failure was incorrectly attributed to B');
const authored=html('<noscript><p id="fallback">仅禁用脚本时的内容</p></noscript><p>原正文</p>'),original=new JSDOM(authored,{runScripts:'dangerously'});assert.equal(original.window.document.getElementById('fallback'),null);assert.ok(new w.DOMParser().parseFromString(authored,'text/html').getElementById('fallback'));await assert.rejects(api.mount(packet('noscript',3,[authored,authored])),/noscript/);assert.equal(w.document.getElementById('study-side').dataset.cardId,'B','unsupported parsing must not replace current body');const nested=html('<template><noscript><p>模板中的后备内容</p></noscript></template>');await assert.rejects(api.mount(packet('nested-noscript',4,[nested,nested])),/noscript/);const unknown=html('<p>原内容</p><script src="unknown.js"></script>');await assert.rejects(api.mount(packet('unknown',5,[unknown,unknown])),/not approved/);original.window.close();outer.window.close()})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({'shell': shared_frame_html()}), text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for shared host regression')
    def test_shared_navigation_rejects_stale_results_and_falls_back_to_original_wrapper(self):
        sides = ['<!doctype html><head><base href="../media/"></head><body>原正面</body>',
                 '<!doctype html><head><base href="../media/"></head><body>完整背面</body>']
        wrapper = card_shell(json.dumps(sides).replace('<', '\\u003c'), '../media/')
        script = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');const {page,runtime,data,wrapper}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const dom=new JSDOM(page,{url:'http://localhost/book/index.html',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,doc=w.document,frame=doc.getElementById('frame'),pending=new Map(),calls=[],mounted=[];
w.console.warn=()=>{};w.fetch=async(url,options)=>{if(url==='nav.json')return{ok:true,json:async()=>data};const id=new URL(url).pathname.split('/').pop().replace('.html','');calls.push(id);if(id==='three')return{ok:false,status:404};return new Promise(resolve=>pending.set(id,()=>resolve({ok:true,text:async()=>wrapper}))) };
w.eval(runtime);await new Promise(r=>setTimeout(r,30));assert.equal(doc.getElementById('flip-card').disabled,true,'flip must wait for the selected card mount');const api={mount:packet=>{mounted.push(packet);return true}};frame.contentWindow.StudySharedFrame=api;frame.dispatchEvent(new w.Event('load'));
doc.getElementById('next-card').click();pending.get('two')();await new Promise(r=>setTimeout(r,20));assert.deepEqual(mounted.map(x=>x.id),['two']);assert.equal(mounted[0].base,'http://localhost/book/media/');assert.equal(doc.getElementById('flip-card').disabled,false,'flip should be restored after mount');
pending.get('one')();await new Promise(r=>setTimeout(r,20));assert.deepEqual(mounted.map(x=>x.id),['two'],'obsolete request overwrote latest selection');
doc.getElementById('next-card').click();await new Promise(r=>setTimeout(r,20));assert.equal(frame.dataset.mountMode,'original-wrapper-fallback');assert.equal(frame.getAttribute('src'),'http://localhost/book/cards/three.html');assert.equal(doc.getElementById('card-render-notice').hidden,false);
doc.getElementById('previous-card').click();frame.contentWindow.StudySharedFrame=api;frame.dispatchEvent(new w.Event('load'));await new Promise(r=>setTimeout(r,20));assert.equal(mounted.at(-1).id,'two');assert.equal(calls.filter(x=>x==='two').length,1,'cached card was fetched again');assert.equal(calls.length,3,'host fetched cards outside visited inventory');dom.window.close();console.log('shared host stale-result/cache/fallback regression passed');})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({'page': library_html('测试书', navigation_href='nav.json', shared_frame={'html': shared_frame_html(), 'policy': {}}), 'runtime': HOST_RUNTIME, 'data': navigation_index(self.catalog()), 'wrapper': wrapper}), text=True, capture_output=True, timeout=60)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom development dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime for cache regression')
    def test_prepared_card_cache_and_prediction_are_bounded_and_share_inflight_requests(self):
        sides = ['<!doctype html><head><base href="../media/"></head><body>正面</body>',
                 '<!doctype html><head><base href="../media/"></head><body>完整背面</body>']
        wrapper = card_shell(json.dumps(sides).replace('<', '\\u003c'), '../media/')
        # A realistic expanded body exceeds the old 2 MiB accounting limit.
        # Revisit and prediction must retain the complete proven payload, with
        # a finite budget and at most one speculative request.
        script = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs'),crypto=require('node:crypto');
const {page,runtime,wrapper}=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const dom=new JSDOM(page,{url:'http://localhost/book/index.html',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,doc=w.document;
w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;Object.defineProperty(w.crypto,'subtle',{value:crypto.webcrypto.subtle});
const hash=s=>crypto.createHash('sha256').update(s).digest('hex'),payload=JSON.stringify({schema:'study-prepared-card.v1',source_wrapper_sha256:hash(wrapper),sides:[{html:'front'},{html:'x'.repeat(1300000)}]}),rules={};
for(let i=0;i<8;i++)rules['c'+i]={src:'evidence/c'+i+'.json',sha256:hash(payload)};
const oversized=payload.replace('x'.repeat(1300000),'z'.repeat(3000000));rules.c8={src:'evidence/c8.json',sha256:hash(oversized)};let oversizedParsed=0;const parse=w.JSON.parse;w.JSON.parse=(s,...rest)=>{if(s===oversized)oversizedParsed++;return parse(s,...rest)};
doc.getElementById('study-library-config').textContent=JSON.stringify({navigation:'nav.json',sharedFrame:{prepared:rules}});
const calls=[],pending=new Map();w.fetch=async(url,options={})=>{if(url==='nav.json')return new Promise(()=>{});const key=new URL(url).pathname;calls.push(key);if(key.endsWith('/cards/c7.html'))return new Promise((resolve,reject)=>{pending.set('c7',()=>resolve(new Response(wrapper)));options.signal.addEventListener('abort',()=>reject(new w.DOMException('cancelled','AbortError')))});return new Response(key.endsWith('/evidence/c8.json')?oversized:key.includes('/evidence/')?payload:wrapper)};
const exposed=runtime.replace('function ensureSharedFrame(){','window.hostQA={fetchCard,prefetchCard,cache:cardCache,requests:cardRequests,setSelected:id=>{selected=id},bytes:()=>cardCacheBytes};function ensureSharedFrame(){');assert.notEqual(exposed,runtime);w.eval(exposed);
const api=w.hostQA,card=i=>({id:'c'+i,url:'cards/c'+i+'.html'});api.setSelected('c0');
await api.fetchCard(card(0));await api.fetchCard(card(0));assert.equal(calls.filter(x=>x.endsWith('/cards/c0.html')).length,1,'large complete payload was not cached');
api.prefetchCard(card(7));await new Promise(r=>setTimeout(r,0));assert.ok(calls.some(x=>x.endsWith('/evidence/c7.json')),'artifact waited for the independent source wrapper');const shared=api.fetchCard(card(7));pending.get('c7')();await shared;assert.equal(calls.filter(x=>x.endsWith('/cards/c7.html')).length,1,'selection refetched its in-flight prediction');
for(let i=1;i<7;i++)await api.fetchCard(card(i));assert.ok(api.cache.size<=4);assert.ok(api.bytes()<=16*1024*1024);assert.equal(api.requests.size,0);
api.prefetchCard(card(7));await new Promise(r=>setTimeout(r,0));api.prefetchCard(card(0));await new Promise(r=>setTimeout(r,10));assert.ok(api.requests.size<=1,'more than one speculative request survived');
assert.equal(api.cache.has('c0'),false,'selected card should not be speculatively fetched');api.prefetchCard(card(8));await new Promise(r=>setTimeout(r,10));assert.equal(oversizedParsed,0,'large speculative JSON was parsed before the cap');assert.equal(api.cache.has('c8'),false);api.prefetchCard(card(8));await api.fetchCard(card(8));assert.equal(oversizedParsed,1,'foreground selection must still load the complete large card');assert.ok(api.bytes()<=16*1024*1024);dom.window.close();console.log('bounded complete-payload cache and prediction passed');})().catch(e=>{console.error(e);process.exitCode=1});'''
        result = subprocess.run([shutil.which('node'), '-e', script], input=json.dumps({
            'page': library_html('测试书', navigation_href='nav.json'),
            'runtime': HOST_RUNTIME, 'wrapper': wrapper}), text=True, capture_output=True, timeout=60)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom development dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

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
// A selection within the mounted window changes selection state, not the
// entire word list. Rebuilding all rows also repeats layout and event work.
const initialRow=$('list').querySelector('.word-entry');
$('next').click();assert.equal($('position').textContent,'2 / 3');assert.equal($('frame').dataset.studyCardId,'two');
assert.equal($('list').querySelector('.word-entry'),initialRow,'switching card rebuilt the mounted navigation rows');
assert.equal($('list').querySelector('[data-card-id="two"]').getAttribute('aria-current'),'true');
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
