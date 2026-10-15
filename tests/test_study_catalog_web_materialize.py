import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.study_catalog_web_materialize import (
    ReadOnlyMedia, digest, inline_child, materialize_side, prepare_native_module,
    prepared_frame_html, prepare_library,
)


class PreparedDeliveryTests(unittest.TestCase):
    def register(self, root, text):
        pin = digest(text)
        (root / ('_as_' + pin[:24] + '.js')).write_text(
            'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['
            + json.dumps(pin) + ']=' + json.dumps(text) + ';')
        return {'src': '_as_' + pin[:24] + '.js', 'sha256': pin}

    def test_pins_and_native_payload_index_are_preserved_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = self.register(root, '{"schema":"projection","records":[]}')
            index = self.register(root, '[{"physical":"original"}]')
            native = ('<script class="anki-final-reviewed-data" type="application/json" '
                      'data-as-src="' + content['src'] + '" data-as-sha="' + content['sha256']
                      + '" data-as-index-src="' + index['src'] + '" data-as-index-sha="'
                      + index['sha256'] + '">{"original":"placeholder"}</script>')
            source = '<html><head><base href="../media/"></head><body>原文' + native + '</body></html>'
            before = source.encode()
            result = materialize_side(source, ReadOnlyMedia(root))
            self.assertEqual(source.encode(), before)
            self.assertIn(native, result['html'])
            self.assertEqual(result['registry'], {content['sha256']: '{"schema":"projection","records":[]}',
                                                index['sha256']: '[{"physical":"original"}]'})
            self.assertEqual(result['proof']['source_sha256'], digest(before))
            self.assertEqual(result['proof']['expanded_sha256'], digest(result['html']))
            path = root / content['src']
            path.write_text(path.read_text().replace('projection', 'CORRUPTION'))
            with self.assertRaisesRegex(ValueError, 'SHA'):
                ReadOnlyMedia(root).read(content)

    def test_media_cache_is_bounded_and_reuses_exact_verified_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parts = [self.register(root, '原始字典文本' + str(i) * 200) for i in range(8)]
            media = ReadOnlyMedia(root, max_cache_bytes=1500)
            for part in parts:
                self.assertEqual(digest(media.read(part)), part['sha256'])
                self.assertLessEqual(media.cache_bytes, 1500)
            last = parts[-1]
            value = media.read(last)
            self.assertIs(media.read(last), value)
            self.assertLess(len(media.values), len(parts))

    def test_shared_dictionary_parsing_and_index_are_reused_by_exact_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bank = self.register(root, json.dumps({'schema': 'anki-slim-shared-dictionary.v1',
                                                  'strings': ['shared prefix ']}, separators=(',', ':')))
            values = []
            for tail in ('one', 'two'):
                raw = 'shared prefix ' + tail
                pin = digest(raw)
                name = '_as_' + pin[:24] + '.js'
                packed = {'schema': 'anki-slim-shared-strings.v1', 'dict': bank, 'pieces': [0, tail]}
                (root / name).write_text('window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['
                                         + json.dumps(pin) + ']=' + json.dumps(packed) + ';')
                values.append({'src': name, 'sha256': pin})
            media = ReadOnlyMedia(root)
            self.assertEqual([media.read(part) for part in values], ['shared prefix one', 'shared prefix two'])
            self.assertEqual(media.dictionary_decodes, 1)
            with self.assertRaisesRegex(ValueError, 'reference'):
                media.dictionary({**bank, 'src': '../outside.js'})
            self.assertLessEqual(media.cache_bytes, media.max_cache_bytes)

    def test_original_history_references_and_already_inline_text_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = '完整审核 <tag> & 中文\n原始证据'
            pin = digest(text)
            name = '_af_' + pin[:24] + '.js'
            (root / name).write_text('window.AnkiFinalHistoryEvidence=window.AnkiFinalHistoryEvidence||{};'
                                    'window.AnkiFinalHistoryEvidence[' + json.dumps(pin) + ']=' + json.dumps(text) + ';')
            source = '<pre data-native-history-media="' + name + '" data-native-history-sha="' + pin + '">placeholder</pre>'
            media = ReadOnlyMedia(root)
            with patch.object(media, 'history', side_effect=AssertionError('history must stay native-lazy')):
                result = materialize_side(source, media)
            self.assertEqual(result['html'], source)
            self.assertNotIn('data-native-history-ready="true"', result['html'])
            self.assertEqual(result['proof']['history_pins'], [pin])
            self.assertEqual(result['proof']['history_storage'], 'original-native-lazy')
            self.assertEqual(result['proof']['history_references'], [
                {'src': name, 'sha256': pin, 'count': 1}])
            ready = source.replace('>placeholder</pre>', ' data-native-history-ready="true">已有完整原稿 &lt;tag&gt;</pre>')
            self.assertEqual(materialize_side(ready, media)['html'], ready)

    def test_closed_history_slices_stay_shared_while_current_examples_are_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            history = self.register(root, '<p>完整旧审核，不应提前反复内嵌。</p>')
            example = self.register(root, '<li class="example-card">当前完整原句与译文</li>')
            def slot(part, kind, tag):
                return ('<' + tag + ' class="as-lazy" data-as-kind="' + kind + '"><script class="as-manifest" type="application/json">'
                        + json.dumps({'schema': 'anki-slim-segments.v1', 'parts': [{**part, 'count': 1}], 'total': 1})
                        + '</script></' + tag + '>')
            history_slot = slot(history, 'detail', 'div')
            source = '<details><summary>原审核</summary>' + history_slot + '</details><ol class="examples">' + slot(example, 'examples', 'li') + '</ol>'
            media = ReadOnlyMedia(root)
            with patch.object(media, 'read', wraps=media.read) as reads:
                result = materialize_side(source, media)
            self.assertIn(history_slot, result['html'])
            self.assertNotIn('<p>完整旧审核', result['html'])
            self.assertIn('<li class="example-card">当前完整原句与译文</li>', result['html'])
            self.assertEqual([call.args[0]['sha256'] for call in reads.call_args_list], [example['sha256']])
            self.assertEqual(len(result['proof']['preserved_disclosure_payloads']), 1)

    def test_repeated_history_references_never_multiply_evidence_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = ReadOnlyMedia(Path(tmp))
            counts = (468, 102, 2, 6)
            references = []
            for number, count in enumerate(counts):
                pin = digest('original shared audit ' + str(number))
                references.extend(['<details><summary>完整原审核</summary><pre data-native-history-media="_af_'
                                   + pin[:24] + '.js" data-native-history-sha="' + pin
                                   + '">原按需载入说明</pre></details>'] * count)
            source = ''.join(references)
            with patch.object(media, 'history', side_effect=AssertionError('must not eagerly read history')):
                result = materialize_side(source, media)
            self.assertEqual(result['html'], source)
            self.assertEqual(len(result['proof']['history_pins']), 4)
            self.assertEqual([item['count'] for item in result['proof']['history_references']], list(counts))
            self.assertEqual(sum(item['count'] for item in result['proof']['history_references']), 578)
            self.assertEqual(result['proof']['expanded_bytes'], len(source.encode()))

    def test_nested_closed_history_placeholders_are_preserved_as_one_subtree(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = ('<div class="as-lazy" data-as-kind="detail"><div class="as-lazy" '
                      'data-as-kind="detail"><script class="as-manifest" type="application/json">'
                      '{"schema":"anki-slim-segments.v1","parts":[],"total":0}'
                      '</script></div></div>')
            self.assertEqual(materialize_side(source, ReadOnlyMedia(Path(tmp)))['html'], source)

    def test_unknown_child_code_paths_and_changed_native_modules_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = ReadOnlyMedia(Path(tmp))
            with self.assertRaisesRegex(ValueError, 'audited'):
                inline_child('<body><script>window.unknown=true</script></body>', media)
            with self.assertRaisesRegex(ValueError, 'local resource'):
                media.local('../outside.js')
            with self.assertRaisesRegex(ValueError, 'audited'):
                prepare_native_module('window.unknown=true;')
        self.assertNotIn('</script', prepared_frame_html().split('<script>', 1)[1].rsplit('</script>', 1)[0].lower())

    def test_whole_book_factory_preserves_source_and_indexes_unknown_fallbacks(self):
        from anki_pipeline import study_catalog_web as web
        import gzip
        code = 'window.auditedFixture=true;'
        known = '<html><head><base href="../media/"></head><body>全部原文<script>' + code + '</script></body></html>'
        unknown = known.replace(code, 'window.unreviewed=true;')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'cards').mkdir()
            (root / 'media').mkdir()
            source_bytes = {}
            cards = []
            for identity, side in [('known', known), ('unknown', unknown), ('custom', None)]:
                raw = (web.card_shell(json.dumps([side, side], ensure_ascii=False), '../media/').encode()
                       if side is not None else b'<html><body>Authored custom wrapper</body></html>')
                (root / 'cards' / (identity + '.html')).write_bytes(raw)
                source_bytes[identity] = raw
                cards.append({'id': identity, 'word': identity, 'unit': '任意学科', 'url': 'cards/' + identity + '.html'})
            catalog = {'schema': 'shared-book-web.v1', 'title': '未来书籍', 'cards': cards}
            policy = {'external': {}, 'inline': [{'source': code, 'sha256': digest(code), 'src': 'unused.js'}]}
            result = prepare_library(root, catalog, {'html': 'older host', 'policy': policy, 'metricsAsset': 'qa.js'})
            report, config = result['report'], result['config']
            self.assertEqual((report['cards'], report['prepared'], report['fallbacks']), (3, 1, 2))
            self.assertEqual(report['fallback_samples'][0]['id'], 'unknown')
            self.assertFalse(report['qa_observation_enabled'])
            self.assertNotIn('prepared', config)
            self.assertNotIn('metricsAsset', config)
            self.assertIn('prepareView', config['html'])
            index_rule = config['preparedIndex']
            index_raw = (root / index_rule['src']).read_bytes()
            self.assertEqual(digest(index_raw), index_rule['sha256'])
            self.assertEqual(gzip.decompress((root / index_rule['gzipSrc']).read_bytes()), index_raw)
            index = json.loads(index_raw)
            self.assertEqual(set(index['cards']), {'known'})
            rule = index['cards']['known']
            artifact = (root / rule['src']).read_bytes()
            self.assertEqual(digest(artifact), rule['sha256'])
            self.assertEqual(gzip.decompress((root / rule['gzipSrc']).read_bytes()), artifact)
            self.assertEqual(json.loads(artifact)['source_wrapper_sha256'], digest(source_bytes['known']))
            self.assertTrue(rule['src'].startswith('evidence/'))
            for identity, raw in source_bytes.items():
                self.assertEqual((root / 'cards' / (identity + '.html')).read_bytes(), raw)
            web.write_library(root, catalog, shared_frame=config)
            self.assertIn('preparedIndex', (root / 'index.html').read_text())

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_browser_fetches_and_verifies_compressed_index_and_only_selected_payload(self):
        from anki_pipeline import study_catalog_web as web
        import base64
        import gzip
        sides = ['<html><head><base href="../media/"></head><body>全部原文</body></html>'] * 2
        wrapper = web.card_shell(json.dumps(sides), '../media/')
        artifact = json.dumps({'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': digest(wrapper),
                               'sides': [{'proof': {}}] * 2}, separators=(',', ':'))
        index = json.dumps({'schema': 'study-prepared-index.v1', 'cards': {
            'one': {'src': 'evidence/card.json', 'gzipSrc': 'evidence/card.gz', 'sha256': digest(artifact)}}}, separators=(',', ':'))
        catalog = {'title': '统一书籍', 'cards': [
            {'id': word, 'word': word, 'unit': 'Unit 01', 'url': 'cards/' + word + '.html'} for word in ('one', 'two')]}
        config = {'html': prepared_frame_html(), 'policy': {}, 'preparedIndex': {
            'src': 'evidence/index.json', 'gzipSrc': 'evidence/index.gz', 'sha256': digest(index)}}
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs'),{webcrypto}=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const dom=new JSDOM(input.page,{url:'http://localhost/book/index.html',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document,calls=[],mounted=[];w.Response=Response;w.DecompressionStream=DecompressionStream;w.TextEncoder=TextEncoder;assert.equal(w.crypto.subtle,undefined,'fixture must model an insecure HTTP LAN origin');
w.fetch=async url=>{calls.push(url);if(url==='nav.json')return new Response(JSON.stringify(input.nav));const path=new URL(url).pathname;if(path.endsWith('/evidence/index.gz'))return new Response(Buffer.from(input.index,'base64'));if(path.endsWith('/evidence/card.gz'))return new Response(Buffer.from(input.artifact,'base64'));if(path.endsWith('.html'))return new Response(input.wrapper);throw Error('unexpected resource '+path)};
w.eval(input.runtime);await new Promise(r=>setTimeout(r,30));const frame=d.getElementById('frame');frame.contentWindow.StudySharedFrame={mount:packet=>{mounted.push(packet);return true}};frame.dispatchEvent(new w.Event('load'));for(let i=0;i<100&&!mounted.length;i++)await new Promise(r=>setTimeout(r,10));assert.equal(mounted.length,1);assert.equal(mounted[0].id,'one');assert.equal(mounted[0].prepared.schema,'study-prepared-card.v1');assert.equal(calls.filter(u=>String(u).endsWith('index.gz')).length,1);assert.equal(calls.filter(u=>String(u).endsWith('card.gz')).length,1);assert.equal(calls.some(u=>String(u).endsWith('.json')),true,'navigation request expected');assert.equal(calls.some(u=>String(u).endsWith('/evidence/card.json')),false,'successful gzip should not load duplicate raw artifact');
d.getElementById('next-card').click();await new Promise(r=>setTimeout(r,50));assert.equal(frame.dataset.mountMode,'original-wrapper-compatibility');assert.equal(frame.getAttribute('src'),'http://localhost/book/cards/two.html');assert.equal(d.getElementById('card-render-notice').hidden,true,'known unsupported source should retain its wrapper without claiming a resource failure');assert.equal(calls.filter(u=>String(u).endsWith('index.gz')).length,1);assert.equal(mounted.length,1);dom.window.close();})().catch(e=>{console.error(e);process.exit(1)});'''
        value = {'page': web.library_html('统一书籍', navigation_href='nav.json', shared_frame=config),
                 'runtime': web.HOST_RUNTIME, 'nav': web.navigation_index(catalog), 'wrapper': wrapper,
                 'index': base64.b64encode(gzip.compress(index.encode(), mtime=0)).decode(),
                 'artifact': base64.b64encode(gzip.compress(artifact.encode(), mtime=0)).decode()}
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(value),
                                text=True, capture_output=True, timeout=45)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_pinned_static_resource_accepts_only_complete_range_or_verified_200(self):
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        helper = PREPARED_FRAME_RUNTIME[PREPARED_FRAME_RUNTIME.index('async function resource('):
                                        PREPARED_FRAME_RUNTIME.index('function installCigen(')]
        code = r'''const assert=require('node:assert/strict'),fs=require('node:fs'),{createHash}=require('node:crypto');
const helper=JSON.parse(fs.readFileSync(0,'utf8')),hash=text=>createHash('sha256').update(text).digest('hex'),text='原文 localhost stays unchanged',bytes=Buffer.byteLength(text,'utf8');
function reader(status,range,body=text){let calls=0;const fetch=async(url,options)=>{calls++;assert.deepEqual(options,{headers:{Range:'bytes=0-'}});return{ok:true,status,headers:new Headers(range?{'Content-Range':range}:{}),text:async()=>body}};return{read:new Function('fetch','sha','scriptCache','TextEncoder',helper+';return resource;')(fetch,async value=>hash(value),new Map(),TextEncoder),calls:()=>calls}}
(async()=>{const complete=reader(206,'bytes 0-'+(bytes-1)+'/'+bytes);assert.equal(await complete.read('/media/exact.js',hash(text)),text);assert.equal(await complete.read('/media/exact.js',hash(text)),text);assert.equal(complete.calls(),1,'exact verified resources should remain cached');assert.equal(await reader(200,null).read('/media/ignored-range.js',hash(text)),text);await assert.rejects(reader(206,'bytes 0-2/'+bytes).read('/media/partial.js',hash(text)),/complete|range/i);await assert.rejects(reader(206,'bytes 1-'+(bytes-1)+'/'+bytes).read('/media/wrong-start.js',hash(text)),/complete|range/i);await assert.rejects(reader(206,'bytes 0-'+bytes+'/'+(bytes+1)).read('/media/wrong-length.js',hash(text)),/length|byte/i);await assert.rejects(reader(206,null).read('/media/no-range.js',hash(text)),/range/i);await assert.rejects(reader(200,null,'rewritten LAN source').read('/media/changed.js',hash(text)),/SHA/);await assert.rejects(reader(206,'bytes 0-'+(bytes-1)+'/'+bytes,text.replace('localhost','127.0.0.1')).read('/media/wrong-pin.js',hash(text)),/SHA|byte|length/);})().catch(error=>{console.error(error);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(helper),
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_obsolete_artifact_download_never_retries_or_parses(self):
        from anki_pipeline.study_catalog_web import HOST_RUNTIME
        helper = HOST_RUNTIME[HOST_RUNTIME.index('let preparedIndexPromise='):HOST_RUNTIME.index('async function fetchCard(')]
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
(async()=>{const w=new JSDOM('',{url:'http://example.test/book/',runScripts:'outside-only'}).window;w.DecompressionStream=DecompressionStream;w.eval('const config={sharedFrame:{}};function safeURL(value){return value};'+JSON.parse(fs.readFileSync(0,'utf8'))+';window.artifact=deliveryArtifact');const controller=new w.AbortController(),calls=[];let began=false;w.fetch=(url,options)=>{calls.push(url);assert.equal(options.signal,controller.signal);began=true;return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new w.DOMException('obsolete','AbortError')),{once:true}))};const pending=w.artifact({src:'raw.json',gzipSrc:'packed.gz',sha256:'irrelevant'},controller.signal);assert.equal(began,true);controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');assert.deepEqual(calls,['packed.gz'],'aborted gzip was retried as a raw download');const afterRead=new w.AbortController();let digests=0;Object.defineProperty(w.crypto,'subtle',{value:{digest:()=>{digests++;throw Error('must not hash obsolete bytes')}}});w.fetch=async()=>({ok:true,text:async()=>{afterRead.abort();return '{"large":"obsolete"}'}});await assert.rejects(w.artifact({src:'raw.json',sha256:'irrelevant'},afterRead.signal),error=>error.name==='AbortError');assert.equal(digests,0,'obsolete bytes reached hashing/parsing');w.close()})().catch(e=>{console.error(e);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(helper),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaged_lan_digest_is_the_existing_audited_implementation(self):
        from anki_pipeline.study_catalog_web import LAN_SHA256_RUNTIME
        original = Path(__file__).parents[1] / 'scripts' / 'lan_sha256.js'
        self.assertEqual(LAN_SHA256_RUNTIME, (Path(__file__).resolve().parents[1] / 'anki_pipeline/templates/lan-sha256.js').read_text())
        import re
        for name in ('copyBufferSource', 'sha256'):
            pattern = r'  function ' + name + r'\([^\n]*\) \{[\s\S]*?\n  \}'
            self.assertEqual(re.search(pattern, LAN_SHA256_RUNTIME)[0], re.search(pattern, original.read_text())[0])

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_native_preparation_reuses_only_identical_validated_input(self):
        # Small source-contract fixture. Production entry accepts only the two
        # audited full-module hashes and verifies every exact replacement site.
        source = '''(function(){var calls=0;async function prepare(data){calls++;if(data.fail)throw Error('invalid');return {verified:data.value,calls:calls};}var load=function(){},install=function(){};
window.AnkiReviewedChunkProjection = Object.freeze({ prepare: prepare, load: load, install: install });})();
(function(){var SIDECAR_SHA='original';function demand(value){if(!value)throw Error('crypto');}
function digest(value) {
    demand(window.crypto && window.crypto.subtle && window.TextEncoder, 'mandatory');return Promise.resolve(value);}
function install(){}async function buildIndex(metadata){if(!metadata.valid)throw Error('bank pin');}
window.AnkiSharedReadingBankRuntime = Object.freeze({ install: install, sidecarSha256: SIDECAR_SHA });})();
(function(){function load(part){if(!part.valid)throw Error('pin');return Promise.resolve(part.raw);}function hydrate(){}
window.AnkiSlimApkgHydrate = window.AnkiFinalApkgHydrate = hydrate;})();'''
        with patch('anki_pipeline.study_catalog_web_materialize.AUDITED_NATIVE_MODULES', {digest(source)}):
            adapted = prepare_native_module(source)
        changed = source.replace('function digest(value)', 'function digest(other)')
        with patch('anki_pipeline.study_catalog_web_materialize.AUDITED_NATIVE_MODULES', {digest(changed)}):
            with self.assertRaisesRegex(ValueError, 'boundary'):
                prepare_native_module(changed)
        code = r'''const assert=require('node:assert/strict'),fs=require('fs');global.window={crypto:{subtle:{}},TextEncoder};const source=JSON.parse(fs.readFileSync(0,'utf8'));new Function(source)();(async()=>{const api=window.AnkiReviewedChunkProjection,a=await api.prepare({value:'same'}),b=await api.prepare({value:'same'});assert.equal(a,b);const c=await api.prepare({value:'changed'});assert.notEqual(a,c);assert.equal(c.calls,2);await assert.rejects(api.prepare({fail:true}),/invalid/);const d=await api.prepare({value:'same'});assert.equal(d.calls,4);await window.AnkiSharedReadingBankRuntime.warm({valid:true},['original']);await assert.rejects(window.AnkiSharedReadingBankRuntime.warm({valid:false},[]),/bank pin/);await assert.rejects(async()=>window.StudySlimWarm.load({valid:false}),/pin/);})().catch(e=>{console.error(e);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(adapted), text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_authored_script_batch_defers_only_owned_layout_and_flushes_exact_final_style(self):
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        begin = PREPARED_FRAME_RUNTIME.index('function installCigen(')
        end = PREPARED_FRAME_RUNTIME.index('function copyAttributes(', begin)
        controller = PREPARED_FRAME_RUNTIME[begin:end]
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
const source=JSON.parse(fs.readFileSync(0,'utf8'));
function fixture(){const dom=new JSDOM('<section class="meaning-section"><div class="primary-definition"><span class="field-title">释义</span><div class="field-content" style="font-size:17px">完整正文</div></div><div class="level-list"><li>等级</li></div><iframe class="etymology-source-frame" style="width:240px"></iframe></section>',{runScripts:'dangerously',pretendToBeVisual:true});const w=dom.window,doc=w.document,node=doc.querySelector('iframe'),messages=[];let reads=0;w.ResizeObserver=class{observe(){}unobserve(){}};node.getBoundingClientRect=()=>{reads++;return{width:240,height:320}};node.contentWindow.postMessage=data=>messages.push(JSON.parse(JSON.stringify(data)));w.eval(source+';installCigen(window,document);');return{dom,w,doc,node,messages,reads:()=>reads}}
const direct=fixture();direct.w.__ankiCigenFrames.refresh();direct.doc.querySelector('.field-content').style.fontSize='19px';direct.w.__ankiCigenFrames.refresh();const expected=direct.messages.slice(-2);
const grouped=fixture(),bridge=grouped.w.__ankiCigenFrames;assert.equal(typeof bridge.batch,'function');let scripts=0;bridge.batch(()=>{for(let i=0;i<6;i++){scripts++;bridge.refresh();assert.equal(grouped.reads(),0,'an authored refresh synchronously forced layout inside the batch')}grouped.doc.querySelector('.field-content').style.fontSize='19px';bridge.batch(()=>{scripts++;bridge.refresh()});assert.equal(grouped.reads(),0)});assert.equal(scripts,7,'author execution was skipped or reordered');assert.ok(grouped.reads()>0,'final real layout was skipped');assert.deepEqual(grouped.messages,expected);assert.equal(bridge.known.get(grouped.node).signature,direct.w.__ankiCigenFrames.known.get(direct.node).signature);const before=grouped.reads();bridge.refresh();assert.ok(grouped.reads()>before,'readiness/current preparation refresh must remain synchronous');const failed=fixture();assert.throws(()=>failed.w.__ankiCigenFrames.batch(()=>{failed.w.__ankiCigenFrames.refresh();throw Error('authored failure')}),/authored failure/);assert.ok(failed.reads()>0,'finally failed to flush the owned bridge');for(const value of [direct,grouped,failed])value.dom.window.close();'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(controller),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_connected_child_events_are_registered_before_owned_layout_batch(self):
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        begin = PREPARED_FRAME_RUNTIME.index('function installCigen(')
        end = PREPARED_FRAME_RUNTIME.index('function copyAttributes(', begin)
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
const dom=new JSDOM('<iframe class="etymology-source-frame" data-study-child-token="current" data-study-child-source="source-pin"></iframe>',{runScripts:'dangerously'}),w=dom.window,child=w.document.querySelector('iframe');
let reads=0;child.getBoundingClientRect=()=>{reads++;return{width:240,height:320}};child.contentWindow.postMessage=()=>{};w.ResizeObserver=class{constructor(callback){w.deliverResize=callback}observe(){}unobserve(){}};w.eval(JSON.parse(fs.readFileSync(0,'utf8'))+';installCigen(window,document);');
const bridge=w.__ankiCigenFrames,send=data=>w.dispatchEvent(new w.MessageEvent('message',{source:child.contentWindow,data:{token:'current',sourceSha:'source-pin',...data}}));
bridge.batch(()=>{assert.ok(bridge.known.has(child),'the connected child must be registered before authored code runs');child.dispatchEvent(new w.Event('load'));w.deliverResize([{target:child}]);assert.equal(reads,0,'load/resize forced an intermediate layout');send({type:'study-child-error',token:'stale',message:'ignored stale error'});assert.equal(bridge.known.get(child).error,null);send({type:'study-child-error',message:'original child resource failed early'});assert.match(bridge.known.get(child).error.message,/resource failed early/)});
const entry=bridge.known.get(child);assert.equal(entry.inits,1);assert.ok(entry.signature);assert.equal(reads,2,'the batch omitted or duplicated its final real measurement');send({type:'study-child-ready',signature:entry.signature,width:240,height:400});assert.equal(entry.ready,false,'a later ready message concealed an original initialization error');assert.match(entry.error.message,/resource failed early/);dom.window.close();'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(PREPARED_FRAME_RUNTIME[begin:end]),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_native_projection_builds_detailed_views_only_for_new_exact_matches(self):
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        begin = PREPARED_FRAME_RUNTIME.index('function adaptNativeProjectionLookup(')
        end = PREPARED_FRAME_RUNTIME.index('// A source module must reuse', begin)
        fixture = (Path(__file__).parent / 'fixtures/study-projection-lookup-contract.cjs').read_text()
        payload = {'adapt': PREPARED_FRAME_RUNTIME[begin:end], 'disable': True}
        # Negative control: the unchanged native lookup must reproduce the
        # measured wasted work before its optimized counterpart is accepted.
        old = subprocess.run([shutil.which('node'), '-e', fixture], input=json.dumps(payload),
                             text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in old.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertNotEqual(old.returncode, 0)
        self.assertIn('unmatched pair allocated detailed views', old.stderr)
        payload['disable'] = False
        new = subprocess.run([shutil.which('node'), '-e', fixture], input=json.dumps(payload),
                             text=True, capture_output=True, timeout=30)
        self.assertEqual(new.returncode, 0, new.stderr)
        result = json.loads(new.stdout)
        self.assertEqual(result['oldDetailedCalls'], 180)
        self.assertEqual(result['newDetailedCalls'], 18)
        self.assertTrue(result['sameDOMAndErrors'])

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_native_hash_cache_keeps_warm_hits_with_the_same_byte_and_failure_limits(self):
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        begin = PREPARED_FRAME_RUNTIME.index('function adaptNativeProjectionLookup(')
        end = PREPARED_FRAME_RUNTIME.index('// A source module must reuse', begin)
        fixture = (Path(__file__).parent / 'fixtures/study-projection-lookup-contract.cjs').read_text()
        source = fixture.split('const fixture=String.raw`', 1)[1].split('`;\nconst pin=', 1)[0]
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
(async()=>{const input=JSON.parse(fs.readFileSync(0,'utf8')),adapt=new Function(input.adapt+';return adaptNativeProjectionLookup;')(),pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';function fixture(source){const w=new JSDOM('',{runScripts:'dangerously'}).window;w.digestBehavior=value=>Promise.resolve('sha:'+value);w.eval(source);return w}
const old=fixture(input.source),next=fixture(adapt(input.source,pin)),texts=Array.from({length:894},(_,i)=>'verified original sentence '+i);for(const w of [old,next]){await Promise.all(texts.map(w.cacheContract.digest));assert.equal(w.realDigestCalls,894);await Promise.all(texts.map(w.cacheContract.digest))}assert.equal(old.realDigestCalls,1788,'negative control no longer reproduces the original FIFO thrash');assert.equal(next.realDigestCalls,894,'warm traversal was rehashed despite fitting both cache limits');const cache=next.cacheContract;assert.equal(cache.entries(),894);assert.equal(cache.bytes(),texts.reduce((sum,text)=>sum+text.length*2,0));
const many=Array.from({length:3000},(_,i)=>'bounded-'+i);await Promise.all(many.map(cache.digest));assert.equal(cache.entries(),2048,'the new entry limit is not enforced');assert.equal(cache.bytes(),cache.keys().reduce((sum,text)=>sum+text.length*2,0));assert.ok(cache.bytes()<=1048576);
const large=Array.from({length:40},(_,i)=>('original-'+i).padEnd(32768,'x'));await Promise.all(large.map(cache.digest));assert.equal(cache.entries(),16);assert.equal(cache.bytes(),1048576,'the original one MiB byte budget changed');const before=next.realDigestCalls,oversize='x'.repeat(65537);await cache.digest(oversize);await cache.digest(oversize);assert.equal(next.realDigestCalls,before+2);assert.equal(cache.has(oversize),false,'the original single-text limit changed');
const bad='original validation failure';next.digestBehavior=value=>value===bad?Promise.reject(Error('pin rejected')):Promise.resolve('sha:'+value);const failures=next.realDigestCalls;await assert.rejects(cache.digest(bad),/pin rejected/);assert.equal(cache.has(bad),false);await assert.rejects(cache.digest(bad),/pin rejected/);assert.equal(next.realDigestCalls,failures+2,'a failed digest was cached');assert.equal(cache.has(bad),false);assert.equal(cache.bytes(),cache.keys().reduce((sum,text)=>sum+text.length*2,0));assert.ok(cache.bytes()<=1048576);old.close();next.close()})().catch(error=>{console.error(error);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps({'adapt': PREPARED_FRAME_RUNTIME[begin:end], 'source': source}),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_missing_realm_digest_reuses_host_contract_without_replacing_native_crypto(self):
        from anki_pipeline.study_catalog_web import LAN_SHA256_RUNTIME
        from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME
        begin = PREPARED_FRAME_RUNTIME.index('function bridgeRealmDigest(')
        end = PREPARED_FRAME_RUNTIME.index('async function realm(', begin)
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs'),vm=require('node:vm'),{createHash,webcrypto}=require('node:crypto');
(async()=>{const input=JSON.parse(fs.readFileSync(0,'utf8')),host=vm.createContext({crypto:{},setTimeout,clearTimeout,TextEncoder,DOMException});vm.runInContext(input.lan,host);const upstream=host.crypto.subtle,original=upstream.digest;let calls=0;upstream.digest=function(...args){assert.equal(this,upstream,'the native/worker digest receiver changed');calls++;return Reflect.apply(original,this,args)};
const dom=new JSDOM('',{url:'http://192.168.3.5/book/',runScripts:'dangerously'}),w=dom.window;Object.defineProperty(w,'parent',{value:host});w.eval(input.bridge+';window.installDigestBridge=bridgeRealmDigest;');assert.equal(w.crypto.subtle,undefined);assert.equal(w.installDigestBridge(w),true);const installed=w.crypto.subtle;assert.equal(w.installDigestBridge(w),false);assert.equal(w.crypto.subtle,installed);assert.equal(calls,0);
const source=new w.Uint8Array([99,1,2,3,88]),view=new w.DataView(source.buffer,1,3),result=installed.digest({name:'sha-256'},view);source[1]=42;assert.equal(Buffer.from(await result).toString('hex'),createHash('sha256').update(Buffer.from([1,2,3])).digest('hex'),'cross-realm view offsets or immediate snapshot changed');const bytes=new w.Uint8Array([4,5,6]);assert.equal(Buffer.from(await installed.digest('SHA-256',bytes.buffer)).toString('hex'),createHash('sha256').update(Buffer.from([4,5,6])).digest('hex'));
await assert.rejects(installed.digest('SHA-1',bytes),error=>error.name==='NotSupportedError');await assert.rejects(installed.digest('SHA-256',{byteLength:3,[Symbol.toStringTag]:'ArrayBuffer'}),error=>error.name==='TypeError');const detached=new w.Uint8Array([7,8,9]);structuredClone(detached.buffer,{transfer:[detached.buffer]});await assert.rejects(installed.digest('SHA-256',detached),error=>error.name==='TypeError');await assert.rejects(installed.digest('SHA-256',detached.buffer),error=>error.name==='TypeError');const sentinel=Error('algorithm getter failed');await assert.rejects(installed.digest({get name(){throw sentinel}},bytes),error=>error===sentinel);
const native=new JSDOM('').window;Object.defineProperty(native.crypto,'subtle',{value:webcrypto.subtle,configurable:true});const before=calls;assert.equal(w.installDigestBridge(native),false);assert.equal(native.crypto.subtle,webcrypto.subtle,'a secure-context native implementation was overwritten');assert.equal(calls,before);const unavailable=new JSDOM('').window;Object.preventExtensions(unavailable.crypto);assert.equal(w.installDigestBridge(unavailable),false,'a blocked installation must retain the original fallback path');assert.equal(unavailable.crypto.subtle,undefined);dom.window.close();native.close();unavailable.close();})().catch(error=>{console.error(error);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps({'lan': LAN_SHA256_RUNTIME, 'bridge': PREPARED_FRAME_RUNTIME[begin:end]}),
                                text=True, capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_complete_shell_reuses_realm_and_runs_original_per_card_scripts_in_order(self):
        code = r'''const {JSDOM,VirtualConsole}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs'),{webcrypto,createHash}=require('node:crypto');
const shell=JSON.parse(fs.readFileSync(0,'utf8')),hash=s=>createHash('sha256').update(s).digest('hex'),children=[],errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
(async()=>{let outer;outer=new JSDOM(shell,{url:'http://localhost/book/index.html',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,beforeParse(w){w.HTMLMediaElement.prototype.pause=()=>{};w.HTMLMediaElement.prototype.load=function(){this.selectionReset={connected:this.isConnected,base:this.ownerDocument.baseURI}};w.HTMLMediaElement.prototype.play=function(){if(this.dataset.requiresLoad==='true'&&!this.selectionReset?.connected)return Promise.reject(new w.DOMException('Media load rejected by URL safety check','NotSupportedError'));w.nativePlays=(w.nativePlays||0)+1;return Promise.resolve()};w.TextEncoder=TextEncoder;Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle});Object.defineProperty(w.HTMLIFrameElement.prototype,'srcdoc',{configurable:true,set(value){const frame=this;frame.dispatchEvent(new w.Event('load'));const child=new JSDOM(value,{url:'http://localhost/book/media/',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc,beforeParse(c){Object.defineProperty(c,'parent',{value:w});c.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};c.scrollTo=()=>{};c.HTMLMediaElement.prototype.pause=()=>{}}});children.push(child);Object.defineProperty(frame,'contentDocument',{configurable:true,get:()=>child.window.document});Object.defineProperty(frame,'contentWindow',{configurable:true,get:()=>child.window});setTimeout(()=>frame.dispatchEvent(new w.Event('load')),0)}})}});const w=outer.window,api=w.StudySharedFrame;assert.ok(api);assert.equal(errors.length,0);
function packet(id,token){const code='window.runs=window.runs||[];window.runs.push({text:document.body.textContent.includes("完整正文"),state:document.readyState,hasDigest:typeof window.crypto?.subtle?.digest==="function"});',source='<!doctype html><html><head><base href="../media/"></head><body><main>完整正文 '+id+'</main><script>'+code+'</script></body></html>',side={html:source,registry:{},children:[],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}};return{id,token,requestedAt:0,base:'http://localhost/book/media/',sides:[source,source],prepared:{sides:[side,side],modules:{}},policy:{external:{},inline:[{source:code,sha256:hash(code)}]}}}
const digestOriginal=w.crypto.subtle.digest.bind(w.crypto.subtle),heldDigests=[];w.crypto.subtle.digest=(...args)=>new Promise(resolve=>heldDigests.push(()=>digestOriginal(...args).then(resolve)));const initialMount=api.mount(packet('one',1));await new Promise(r=>setTimeout(r,10));assert.equal(heldDigests.length,2,'the independent source and expanded proofs must begin together');for(const release of heldDigests)release();w.crypto.subtle.digest=digestOriginal;assert.equal(await initialMount,true);const first=w.document.getElementById('study-side').contentWindow;assert.equal(first.runs.length,1);assert.ok(first.__ankiCigenFrames.refresh instanceof first.Function,'Cigen postMessage sender must be the actual inner realm');assert.equal(first.runs[0].text,true);assert.equal(first.runs[0].state,'complete');assert.equal(first.runs[0].hasDigest,true,'native author validation must receive the host digest before any authored module executes');assert.ok(first.document.body.textContent.includes('完整正文 one'));
const space=new first.KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true,cancelable:true});first.document.body.dispatchEvent(space);assert.equal(space.defaultPrevented,true);for(let i=0;i<100&&w.document.getElementById('study-flip').getAttribute('aria-pressed')!=='true';i++)await new Promise(r=>setTimeout(r,10));const back=w.document.getElementById('study-side').contentWindow;assert.notEqual(back,first);assert.equal(back.runs.length,1);assert.ok(first.document.body.textContent.includes('完整正文 one'),'the current card front must be retained when its back is shown');for(const expected of [false,true,false,true]){w.document.getElementById('study-flip').click();for(let i=0;i<100&&w.document.getElementById('study-flip').getAttribute('aria-pressed')!==String(expected);i++)await new Promise(r=>setTimeout(r,10));assert.equal(w.document.getElementById('study-flip').getAttribute('aria-pressed'),String(expected));assert.equal(w.document.getElementById('study-side').contentWindow,expected?back:first);assert.equal(first.runs.length,1,'returning to a prepared front reran its source scripts');assert.equal(back.runs.length,1,'returning to a prepared back reran its source scripts')}assert.equal(w.document.querySelectorAll('iframe').length,2);assert.equal(w.document.getElementById('study-flip').getAttribute('aria-pressed'),'true');assert.equal(await api.mount(packet('two',2)),true);assert.equal(w.document.getElementById('study-side').contentWindow,first);assert.equal(first.runs.length,2);assert.ok(first.document.body.textContent.includes('完整正文 two'));assert.equal(back.document.body.textContent,'','changing cards must dispose the previous card other face');
const bad=packet('bad',3);bad.prepared.sides[0].proof.expanded_sha256='0'.repeat(64);await assert.rejects(api.mount(bad),/proof/);assert.ok(first.document.body.textContent.includes('完整正文 two'),'failed preparation altered the visible previous card');assert.deepEqual(errors,[]);
const versioned=packet('version',4);versioned.prepared.modules={changed:{sha256:'different',src:'unused.js'}};await api.mount(versioned);assert.notEqual(w.document.getElementById('study-side').contentWindow,first,'same-base new module fingerprint reused stale globals');
const throwing=packet('throwing',5),throwCode='throw Error("audited failure");';for(let i=0;i<2;i++){const source=throwing.sides[i].replace(/<script>[\s\S]*?<\/script>/,'<script>'+throwCode+'</script>');throwing.sides[i]=source;throwing.prepared.sides[i]={html:source,registry:{},children:[],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}}}throwing.policy.inline=[{source:throwCode,sha256:hash(throwCode)}];await assert.rejects(api.mount(throwing),/audited failure/);assert.ok(errors.some(e=>e.includes('audited failure')));
let release;const slowCode='window.slow=true;',stale=packet('stale',6);for(let i=0;i<2;i++){const source=stale.sides[i].replace(/<script>[\s\S]*?<\/script>/,'<script src="slow.js"></script>');stale.sides[i]=source;stale.prepared.sides[i]={html:source,registry:{},children:[],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}}}stale.policy.external={'slow.js':hash(slowCode)};w.fetch=()=>new Promise(resolve=>release=()=>resolve({ok:true,text:async()=>slowCode}));const late=api.mount(stale);for(let i=0;i<50&&!release;i++)await new Promise(r=>setTimeout(r,5));assert.ok(release);const winner=packet('winner',7);winner.base='http://localhost/different/media/';await api.mount(winner);const winnerWindow=w.document.getElementById('study-side').contentWindow;release();assert.equal(await late,false);assert.equal(w.document.getElementById('study-side').contentWindow,winnerWindow);assert.ok(winnerWindow.document.body.textContent.includes('完整正文 winner'),'obsolete preparation erased the current card');
const childPacket=packet('child',8),originalChild='<html><head></head><body>真实原词源</body></html>',childHTML='<section class="meaning-section"><div class="level-section">等级</div><section class="etymology-section"><iframe class="etymology-source-frame" sandbox="allow-scripts" style="width:200px;height:320px" srcdoc="&lt;html>&lt;body>原词源&lt;/body>&lt;/html>"></iframe></section></section><audio preload="none" src="original.mp3" data-requires-load="true"></audio>',audioCode='(function(){const a=document.querySelector("audio"),original=a.play;a.play=function(){return original.apply(this,arguments)};window.audioWrapped=true;})();';
const source=childPacket.sides[1].replace('</body>',childHTML+'<script>'+audioCode+'</script></body>');childPacket.sides[1]=source;childPacket.prepared.sides[1]={html:source,registry:{},children:[{html:originalChild,source_sha256:hash(originalChild),scripts:[]}],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}};childPacket.policy.inline.push({source:audioCode,sha256:hash(audioCode)});
let childWidth=200;const nativeRect=w.HTMLIFrameElement.prototype.getBoundingClientRect,nativeRects=w.HTMLIFrameElement.prototype.getClientRects;w.HTMLIFrameElement.prototype.getBoundingClientRect=function(){if(this.classList.contains('etymology-source-frame'))return{top:100,left:0,width:childWidth,height:parseFloat(this.style.height)||320,right:childWidth,bottom:420,x:0,y:100};return nativeRect.call(this)};w.HTMLIFrameElement.prototype.getClientRects=function(){return this.classList.contains('etymology-source-frame')?[this.getBoundingClientRect()]:nativeRects.call(this)};
await api.mount(childPacket);const visibleFront=w.document.getElementById('study-side');let preparedFrame,childFrame;for(let i=0;i<100&&!childFrame;i++){preparedFrame=Array.from(w.document.querySelectorAll('iframe')).find(frame=>frame!==visibleFront&&frame.contentDocument?.querySelector('iframe.etymology-source-frame'));childFrame=preparedFrame?.contentDocument.querySelector('iframe.etymology-source-frame');if(!childFrame)await new Promise(r=>setTimeout(r,10))}assert.ok(childFrame);const pw=preparedFrame.contentWindow,doc=pw.document,preparedSrcdoc=childFrame.getAttribute('srcdoc');for(let i=0;i<100&&(!pw.audioWrapped||!pw.__ankiCigenFrames.known.has(childFrame));i++)await new Promise(r=>setTimeout(r,10));const entry=pw.__ankiCigenFrames.known.get(childFrame);assert.equal(pw.audioWrapped,true,'original audio script must retain writable play wrapping');assert.equal(doc.querySelector('audio').selectionReset?.connected,true,'inert-document URL-safety state must reset only after the final media node is connected');assert.equal(doc.querySelector('audio').selectionReset.base,childPacket.base);assert.equal(doc.querySelector('audio').getAttribute('preload'),'none');await assert.rejects(doc.querySelector('audio').play(),/before commit/);assert.equal(w.nativePlays||0,0);
w.document.getElementById('study-flip').click();await new Promise(r=>setTimeout(r,40));assert.equal(w.document.getElementById('study-side'),visibleFront,'unmeasured child replaced the complete front');const message={type:'study-child-ready',token:childFrame.dataset.studyChildToken,sourceSha:childFrame.dataset.studyChildSource,signature:entry.signature,width:200,height:400};pw.dispatchEvent(new pw.MessageEvent('message',{source:childFrame.contentWindow,data:{...message,token:'stale'}}));await new Promise(r=>setTimeout(r,30));assert.equal(w.document.getElementById('study-side'),visibleFront);pw.dispatchEvent(new pw.MessageEvent('message',{source:childFrame.contentWindow,data:message}));for(let i=0;i<100&&w.document.getElementById('study-side')===visibleFront;i++)await new Promise(r=>setTimeout(r,10));assert.equal(w.document.getElementById('study-side'),preparedFrame,'measured source frame was recreated');assert.equal(preparedFrame.contentWindow,pw);assert.equal(doc.querySelector('iframe.etymology-source-frame'),childFrame);assert.equal(childFrame.getAttribute('srcdoc'),preparedSrcdoc,'commit navigated the measured child again');assert.equal(childFrame.style.height,'400px');await doc.querySelector('audio').play();assert.equal(w.nativePlays,1);assert.equal(w.document.getElementById('study-render-metrics'),null,'production must not install per-frame QA sampling');const childInitCount=entry.inits;for(const expected of [false,true,false,true]){w.document.getElementById('study-flip').click();for(let i=0;i<100&&w.document.getElementById('study-flip').getAttribute('aria-pressed')!==String(expected);i++)await new Promise(r=>setTimeout(r,10));assert.equal(w.document.getElementById('study-flip').getAttribute('aria-pressed'),String(expected));assert.equal(preparedFrame.contentDocument,doc);assert.equal(doc.querySelector('iframe.etymology-source-frame'),childFrame,'same-card flips recreated the original child document');assert.equal(childFrame.getAttribute('srcdoc'),preparedSrcdoc);assert.equal(entry.inits,childInitCount,'same-card flips reinitialized the original child viewer')}
const resizePacket=JSON.parse(JSON.stringify(childPacket));resizePacket.id='resized';resizePacket.token=9;await api.mount(resizePacket);const resizeFront=w.document.getElementById('study-side');let resizePrepared,resizeChild;for(let i=0;i<100&&!resizeChild;i++){resizePrepared=Array.from(w.document.querySelectorAll('iframe')).find(frame=>frame!==resizeFront&&frame.contentDocument?.querySelector('iframe.etymology-source-frame'));resizeChild=resizePrepared?.contentDocument.querySelector('iframe.etymology-source-frame');if(!resizeChild)await new Promise(r=>setTimeout(r,10))}assert.ok(resizeChild);const rw=resizePrepared.contentWindow;for(let i=0;i<100&&!rw.__ankiCigenFrames.known.has(resizeChild);i++)await new Promise(r=>setTimeout(r,10));const re=rw.__ankiCigenFrames.known.get(resizeChild),oldSignature=re.signature,resizeMessage={type:'study-child-ready',token:resizeChild.dataset.studyChildToken,sourceSha:resizeChild.dataset.studyChildSource,signature:oldSignature,width:200,height:400};rw.dispatchEvent(new rw.MessageEvent('message',{source:resizeChild.contentWindow,data:resizeMessage}));await new Promise(r=>setTimeout(r,150));assert.equal(re.ready,true,'background ready must settle before resize');childWidth=350;rw.__ankiCigenFrames.refresh();assert.notEqual(re.signature,oldSignature);assert.equal(re.ready,false,'new layout signature must invalidate previously measured readiness');w.document.getElementById('study-flip').click();await new Promise(r=>setTimeout(r,40));assert.equal(w.document.getElementById('study-side'),resizeFront,'cached prepared view committed stale width');rw.dispatchEvent(new rw.MessageEvent('message',{source:resizeChild.contentWindow,data:resizeMessage}));await new Promise(r=>setTimeout(r,30));assert.equal(w.document.getElementById('study-side'),resizeFront,'obsolete child-ready signature was accepted');rw.dispatchEvent(new rw.MessageEvent('message',{source:resizeChild.contentWindow,data:{...resizeMessage,signature:re.signature,width:350,height:500}}));for(let i=0;i<100&&w.document.getElementById('study-side')===resizeFront;i++)await new Promise(r=>setTimeout(r,10));assert.equal(w.document.getElementById('study-side'),resizePrepared);assert.equal(resizeChild.style.height,'500px');
resizeFront.srcdoc='<!doctype html><html><head></head><body>Unrelated navigation</body></html>';await new Promise(r=>setTimeout(r,30));w.document.getElementById('study-flip').click();for(let i=0;i<100&&w.document.getElementById('study-flip').getAttribute('aria-pressed')!=='false';i++)await new Promise(r=>setTimeout(r,10));assert.equal(w.document.getElementById('study-flip').getAttribute('aria-pressed'),'false');assert.notEqual(w.document.getElementById('study-side'),resizeFront,'a navigated iframe document was reused as a verified source face');assert.ok(w.document.getElementById('study-side').contentDocument.body.textContent.includes('完整正文'));assert.equal(w.document.querySelectorAll('iframe').length,2);
const uninterrupted=packet('ordered-complete',10),normalCodes=['window.tagOrder=[1];','window.tagOrder.push(2);','window.tagOrder.push(3);'];uninterrupted.policy.inline=normalCodes.map(source=>({source,sha256:hash(source)}));for(let i=0;i<2;i++){const source=uninterrupted.sides[i].replace(/<script>[\s\S]*?<\/script>/,normalCodes.map(code=>'<script>'+code+'</script>').join(''));uninterrupted.sides[i]=source;uninterrupted.prepared.sides[i]={html:source,registry:{},children:[],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}}}assert.equal(await api.mount(uninterrupted),true);assert.deepEqual(Array.from(w.document.getElementById('study-side').contentWindow.tagOrder),[1,2,3],'task yields changed authored script order');
const css=packet('css',11);for(let i=0;i<2;i++){const source=css.sides[i].replace('</head>','<link rel="stylesheet" href="x.css" media="print"></head>');css.sides[i]=source;css.prepared.sides[i]={html:source,registry:{},children:[],proof:{source_sha256:hash(source),expanded_sha256:hash(source)}}}await assert.rejects(api.mount(css),/stylesheet attributes/);for(const child of children)child.window.close();outer.window.close();})().catch(e=>{console.error(e);process.exit(1)});'''
        result = subprocess.run([shutil.which('node'), '-e', code], input=json.dumps(prepared_frame_html()),
                                text=True, capture_output=True, timeout=45)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
