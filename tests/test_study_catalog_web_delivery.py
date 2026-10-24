"""Complete web loading around immutable exports; no PG, SDK or large DOM."""
import hashlib
import json
import copy
import gzip
import os
from pathlib import Path
import re
import shutil
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize


ROOT = Path(__file__).resolve().parents[1]
RESTORE = '5f4fe78687c65beed0efc5bf6174734ace66e3baad5bebabc8f7f347b1ed2832'
HYDRATE = 'window.StudyFieldScriptTransport.restore(document);window.AnkiSlimApkgHydrate();'
HYDRATE_SHA = 'f4c286f153cc85f23027fb0ed952d7498c6dcba55e2408db2ef1a0f295f7b1f2'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ProtectedDeliveryTests(unittest.TestCase):
    def test_registered_restoration_then_hydrate_is_eligible_with_exact_bytes(self):
        source = (ROOT / 'anki_pipeline/templates/field-script-restore.js').read_bytes()
        self.assertEqual(sha(source), RESTORE)
        self.assertEqual(sha(HYDRATE.encode()), HYDRATE_SHA)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'media').mkdir()
            names = ['_study_field_script_' + RESTORE + '.js', '_study_' + HYDRATE_SHA + '.js']
            for name, raw in zip(names, (source, HYDRATE.encode())):
                (root / 'media' / name).write_bytes(raw)
            side = ''.join('<script src="' + name + '"></script>' for name in names)
            audit = web.SharedMountAudit(); audit.observe([side])
            config = web.audited_shared_config(root, audit)
            materialize._eligible_side(side, config['policy'])
            self.assertEqual(set(config['policy']['external'].values()), {RESTORE, HYDRATE_SHA})
            # An arbitrary change does not inherit this exact-byte approval.
            (root / 'media' / names[1]).write_bytes(HYDRATE.encode() + b' ')
            changed = web.audited_shared_config(root, audit)
            with self.assertRaisesRegex(ValueError, 'exact audit'):
                materialize._eligible_side(side, changed['policy'])

    def test_real_collector_restoration_order_repeat_realm_and_failure_blocks_hydrate(self):
        from anki_pipeline import study_catalog_web_delivery as delivery
        start = materialize.PREPARED_FRAME_RUNTIME.index('async function collectAuthoredScripts(')
        end = materialize.PREPARED_FRAME_RUNTIME.index('function installCigen(', start)
        code = r'''const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),{TextEncoder,TextDecoder}=require('node:util'),{createHash}=require('node:crypto'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8')),hash=s=>createHash('sha256').update(s).digest('hex');
const cigen='window.bridgeRan=(window.bridgeRan||0)+1;',data='{"original":"完整原文😀"}';
function protectedScript(attrs,text,kind,n){const raw=JSON.stringify({attrs,text,kind,parent:'section',schema:'study-field-script.v1'}),source=Buffer.from(raw).toString('base64');return '<script '+attrs.map(([k,v])=>k+'="'+v+'"').join(' ')+'>'+text+'</script><span hidden="" style="display:none!important" aria-hidden="true" data-study-script-transport="v1" data-study-script-key="'+'a'.repeat(64)+':'+n+'" data-study-script-sha256="'+hash(raw)+'" data-study-script-source="'+source+'"></span>'}
const body='<section>'+protectedScript([['data-cigen-frame-bridge','v1']],cigen,'cigen',0)+protectedScript([['class','anki-final-reviewed-data'],['type','application/json']],data,'reviewed',1)+'</section><script src="restore.js"></script><script src="hydrate.js"></script>';
function fixture(){const d=new JSDOM('<body></body>',{runScripts:'outside-only',url:'https://study.test/book/index.html'}),w=d.window;w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;w.hydrates=0;w.AnkiSlimApkgHydrate=()=>{assert.equal(w.document.querySelector('script.anki-final-reviewed-data').textContent,data);assert.equal(w.document.querySelector('script[data-cigen-frame-bridge]').textContent,cigen);w.hydrates++};const sources={'restore.js':input.restore,'hydrate.js':input.hydrate};w.resource=async(url,pin)=>{const raw=sources[new URL(url).pathname.split('/').pop()];assert.equal(hash(raw),pin);return raw};w.adaptAuthoredCompactClassScan=s=>s;w.eval(input.collect+';window.collect=collectAuthoredScripts;');const policy={external:Object.fromEntries(Object.entries(sources).map(([k,v])=>[k,hash(v)])),inline:[{source:cigen,sha256:hash(cigen)}]};return{d,w,policy}}
async function run(f,value=body){f.w.document.body.innerHTML=value;const scripts=await f.w.collect(f.w.document,{base:'https://study.test/book/',policy:f.policy,prepared:{modules:{}}});for(const item of scripts){f.w.eval(item.code);item.node.remove()}}
(async()=>{const f=fixture();await run(f);assert.equal(f.w.bridgeRan,1);assert.equal(f.w.hydrates,1);assert.equal(f.w.StudyFieldScriptTransport.restore(f.w.document).verified,2);assert.equal(f.w.bridgeRan,1,'restored Cigen script replayed');await run(f);assert.equal(f.w.bridgeRan,2);assert.equal(f.w.hydrates,2);const bad=body.replace('data-study-script-source="','data-study-script-source="!');await assert.rejects(run(f,bad),/Base64|base64|invalid character/i);assert.equal(f.w.hydrates,2,'restore failure failed to block hydrate');f.d.window.close();const reversed=fixture();await assert.rejects(run(reversed,body.replace('<script src="restore.js"></script><script src="hydrate.js"></script>','<script src="hydrate.js"></script><script src="restore.js"></script>')),/undefined|restore/);assert.equal(reversed.w.hydrates,0);reversed.d.window.close();console.log('source collector / original recovery / two faces / failure blocking PASS')})().catch(e=>{console.error(e);process.exit(1)});'''
        result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True, timeout=20,
            input=json.dumps({'collect': materialize.PREPARED_FRAME_RUNTIME[start:end],
                              'restore': (ROOT / 'anki_pipeline/templates/field-script-restore.js').read_text(),
                              'hydrate': HYDRATE}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        from anki_pipeline import study_catalog_web_delivery
        self.delivery = study_catalog_web_delivery

    def fixture(self):
        source = self.root / 'parent'; source.mkdir()
        root = source / 'web'; root.mkdir(); (root / 'cards').mkdir(); (root / 'media').mkdir()
        (root / 'media' / 'ordinary.mp3').write_bytes(b'original opaque media')
        catalog = {'schema': 'shared-book-web.v1', 'book_id': 'arbitrary-subject', 'title': '通用学科',
            'catalog_revision': 7, 'cards': [
                {'id': 'one', 'url': 'cards/one.html', 'word': 'one', 'unit': 'current'},
                {'id': 'guide', 'url': 'cards/guide.html', 'word': 'guide', 'unit': 'current'}]}
        for card in catalog['cards']:
            raw = web.card_shell(json.dumps(['<html><head></head><body>完整正面</body></html>',
                    '<html><head></head><body>完整背面😀</body></html>'], ensure_ascii=False), '../media/').encode()
            (root / card['url']).write_bytes(raw)
        (root / 'catalog.json').write_bytes(self.delivery._json(catalog))
        metadata = {'cards': {'one': {'summary': '原摘要 & 句子', 'example_count': 7, 'deck_name': 'original::group'}},
                    'member_ids': ['one'], 'provenance': {'kind': 'current-projected-fields'}}
        web.write_library(root, catalog, metadata, shared_frame={'policy': {'external': {}, 'inline': []}})
        report = {'format': 'web', 'cards': 2}
        (root / 'COMPLETE.json').write_bytes(self.delivery._json(report))
        manifest = {'schema': 'study-catalog-export-batch.v1', 'snapshot': {'catalog_revision': 7,
            'read_only': True, 'isolation': 'repeatable read', 'snapshot': 'fixture:1'},
            'books': {'arbitrary-subject': {'catalog_revision': 7}}, 'artifacts': [
                {'book_id': 'arbitrary-subject', 'name': 'web', 'format': 'web', 'report': report,
                 'report_sha256': sha(self.delivery._json(report))}]}
        self.reseal(source, manifest)
        return source, root, catalog

    def reseal(self, source, manifest):
        raw = self.delivery._json(manifest); (source / 'manifest.json').write_bytes(raw)
        complete = {'schema': 'study-catalog-export-batch-complete.v1', 'artifacts': len(manifest['artifacts']),
                    'manifest_sha256': sha(raw), 'manifest_bytes': len(raw)}
        (source / 'COMPLETE.json').write_bytes(self.delivery._json(complete))

    def derive(self, source, **kwargs):
        return self.delivery.derive_batch(source, self.root / 'derived',
            expected_complete_sha256=sha((source / 'COMPLETE.json').read_bytes()),
            base_url='https://study.test/new/', heap_mb=512, **kwargs)

    def test_existing_export_navigation_and_every_raw_byte_identity_are_preserved(self):
        source, root, _ = self.fixture()
        originals = {p.relative_to(root).as_posix(): (p.read_bytes(), self.delivery._six(p.stat()))
                     for p in self.delivery._tree_files(root)}
        config = self.delivery.library_config((root / 'index.html').read_bytes())
        nav = (root / config['navigation']).read_bytes()
        packed = (root / config['navigationGzip']).read_bytes()
        result = self.derive(source)
        derived = self.root / 'derived' / 'web'
        self.assertEqual((derived / config['navigation']).read_bytes(), nav)
        self.assertEqual((derived / config['navigationGzip']).read_bytes(), packed)
        self.assertEqual(self.delivery.library_config((derived / 'index.html').read_bytes())['totals'], config['totals'])
        for name, (raw, identity) in originals.items():
            self.assertEqual((derived / name).read_bytes(), raw)
            self.assertEqual(self.delivery._six((root / name).stat()), identity)
        self.assertEqual(result['webs'][0]['delivery']['modes'], {'compiled': 0, 'authored': 2})
        self.assertTrue((self.root / 'derived' / 'COMPLETE.json').is_file())
        self.assertFalse((derived / 'COMPLETE.json').exists(), 'not an original parent child completion')
        self.assertFalse(result['native_artifacts_regenerated'])

    def test_unknown_script_fails_without_success_or_parent_change(self):
        source, root, catalog = self.fixture()
        path = root / catalog['cards'][0]['url']
        sides = ['<html><head></head><body>front</body></html>',
                 '<html><head></head><body><script>window.unknown=true;</script></body></html>']
        path.write_bytes(web.card_shell(json.dumps(sides), '../media/').encode())
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'fallback'):
            self.derive(source)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.root / 'derived/COMPLETE.json').exists())

    def test_source_mutation_during_compilation_fails_final_full_ledger(self):
        source, root, _ = self.fixture()
        touched = []
        def change(event):
            if event['stage'] == 'export-web-compile' and not touched:
                (root / 'media/ordinary.mp3').write_bytes(b'outside mutation'); touched.append(True)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.derive(source, callback=change)
        self.assertFalse((self.root / 'derived/COMPLETE.json').exists())

    def test_external_complete_pin_and_parent_child_report_are_not_self_attestation(self):
        source, root, _ = self.fixture()
        with self.assertRaisesRegex(ValueError, 'SHA'):
            self.delivery.derive_batch(source, self.root/'bad', expected_complete_sha256='0'*64, base_url='https://study.test/')
        (root / 'COMPLETE.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'completion differs'):
            self.derive(source)
        self.assertFalse((self.root / 'derived').exists())

    def test_revision_mismatch_path_escape_and_existing_output_rejected(self):
        source, root, _ = self.fixture()
        catalog = json.loads((root/'catalog.json').read_bytes()); catalog['catalog_revision'] = 8
        (root/'catalog.json').write_bytes(self.delivery._json(catalog))
        with self.assertRaisesRegex(ValueError, 'revision'):
            self.derive(source)
        manifest = json.loads((source/'manifest.json').read_bytes()); manifest['artifacts'][0]['name'] = '../escape'
        self.reseal(source, manifest)
        with self.assertRaisesRegex(ValueError, 'basename'):
            self.derive(source)
        (self.root/'derived').mkdir(); (self.root/'derived/actor').write_bytes(b'actor')
        with self.assertRaises(FileExistsError):
            self.derive(source)
        self.assertEqual((self.root/'derived/actor').read_bytes(), b'actor')

    def test_missing_navigation_metadata_never_silently_rebuilds_unknown_counts(self):
        root = self.root
        with self.assertRaisesRegex(ValueError, 'exactly one navigation'):
            self.delivery.build_library(root, {'cards': []}, {}, source_url='https://study.test/', builder=None)

    def test_actual_read_buffer_is_pinned_and_replaced_file_never_authenticates(self):
        path = self.root/'metadata.json'; path.write_bytes(b'{"old":1}')
        original_read = os.read; changed = []
        def replace(fd, count):
            raw = original_read(fd, count)
            if raw and not changed:
                path.rename(self.root/'old.json'); path.write_bytes(b'{"new":1}'); changed.append(True)
            return raw
        with patch.object(self.delivery.os, 'read', new=replace), self.assertRaisesRegex(ValueError, 'identity changed'):
            self.delivery._read(path, sha(b'{"old":1}'))
        self.assertEqual(path.read_bytes(), b'{"new":1}')

    def test_navigation_source_change_after_copy_is_not_an_immutable_success(self):
        source, root, _ = self.fixture()
        config = self.delivery.library_config((root/'index.html').read_bytes())
        changed = []
        def change(event):
            if event['stage']=='export-web-compile' and not changed:
                path=root/config['navigationGzip']; raw=path.read_bytes()
                # Valid equivalent gzip decoded text is insufficient: retain exact original bytes.
                path.write_bytes(gzip.compress(gzip.decompress(raw),mtime=123)); changed.append(True)
        with self.assertRaisesRegex(ValueError, 'SHA|identity'):
            self.derive(source,callback=change)
        self.assertFalse((self.root/'derived/COMPLETE.json').exists())

    def test_compressed_navigation_wrong_text_does_not_get_regenerated(self):
        source, root, _ = self.fixture()
        config = self.delivery.library_config((root/'index.html').read_bytes())
        (root/config['navigationGzip']).write_bytes(gzip.compress(b'{}',mtime=0))
        with self.assertRaisesRegex(ValueError, 'compressed navigation differs'):
            self.derive(source)
        self.assertFalse((self.root/'derived/COMPLETE.json').exists())

    def two_book_fixture(self):
        source, first, _ = self.fixture()
        second = source/'web2'; shutil.copytree(first, second)
        catalog = json.loads((second/'catalog.json').read_bytes())
        catalog['book_id'] = 'second-subject'
        (second/'catalog.json').write_bytes(self.delivery._json(catalog))
        manifest = json.loads((source/'manifest.json').read_bytes())
        row = copy.deepcopy(manifest['artifacts'][0]); row.update(name='web2', book_id='second-subject')
        manifest['artifacts'].append(row); manifest['books']['second-subject'] = {'catalog_revision': 7}
        self.reseal(source, manifest)
        return source, first

    def test_two_book_stable_batch_has_final_consistent_completion(self):
        source, _ = self.two_book_fixture()
        result = self.derive(source)
        self.assertEqual([row['name'] for row in result['webs']], ['web','web2'])
        self.assertTrue(all(row['raw_cards_media_catalog_SHA_six_unchanged'] for row in result['webs']))
        self.assertTrue((self.root/'derived/COMPLETE.json').is_file())

    def test_later_book_cannot_change_earlier_raw_navigation_metadata_or_links(self):
        for kind in ('media', 'navigation', 'index', 'completion', 'catalog', 'link'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                self.root = Path(temporary)
                source, first = self.two_book_fixture()
                config = self.delivery.library_config((first/'index.html').read_bytes())
                changed = []
                def change(event):
                    if event['stage']!='export-web-compile' or event['book_id']!='second-subject' or changed:
                        return
                    changed.append(True)
                    if kind=='media':
                        (first/'media/ordinary.mp3').write_bytes(b'changed earlier source after its per-book ledger')
                    elif kind=='navigation':
                        path=first/config['navigationGzip']
                        path.write_bytes(gzip.compress(gzip.decompress(path.read_bytes()),mtime=123))
                    elif kind=='index':
                        path=first/'index.html';path.write_bytes(path.read_bytes()+b' ')
                    elif kind=='completion':
                        (first/'COMPLETE.json').write_bytes(b'{}')
                    elif kind=='catalog':
                        path=first/'catalog.json';path.write_bytes(path.read_bytes()+b' ')
                    else:
                        path=self.root/'derived/web/media';path.unlink()
                        path.symlink_to(source/'web2/media',target_is_directory=True)
                with self.assertRaises((ValueError, OSError)):
                    self.derive(source,callback=change)
                self.assertEqual(changed,[True])
                self.assertFalse((self.root/'derived/COMPLETE.json').exists())
                self.assertTrue((self.root/'derived/FAILED.json').is_file())

    def test_symlink_parent_cannot_put_derivative_inside_source(self):
        source, _, _ = self.fixture()
        alias=self.root/'source-alias';alias.symlink_to(source,target_is_directory=True)
        output=alias/'unexpected-child'
        with self.assertRaisesRegex(ValueError,'independent'):
            self.delivery.derive_batch(source,output,
                expected_complete_sha256=sha((source/'COMPLETE.json').read_bytes()),
                base_url='https://study.test/new/',heap_mb=512)
        self.assertFalse((source/'unexpected-child').exists())

    def test_fifo_metadata_is_rejected_before_blocking_open(self):
        fifo=self.root/'not-regular';os.mkfifo(fifo)
        code = """import pathlib,sys,types
raw=pathlib.Path(sys.argv[1]).read_bytes()
m=types.ModuleType('anki_pipeline._bounded_read_test');m.__package__='anki_pipeline';m.__file__=sys.argv[1]
exec(compile(raw,sys.argv[1],'exec'),m.__dict__)
try:m._read(pathlib.Path(sys.argv[2]),'0'*64)
except ValueError:print('REGULAR_FILE_REJECTION')
else:raise AssertionError('FIFO accepted')
"""
        result=subprocess.run([sys.executable,'-B','-W','error::ResourceWarning','-c',code,
            self.delivery.__file__,str(fifo)],cwd=ROOT,text=True,capture_output=True,timeout=0.6)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('REGULAR_FILE_REJECTION',result.stdout)

    def test_original_builder_results_really_attach_compiled_envelopes(self):
        from tests.test_study_compiled_web_delivery import CompiledWebDeliveryTests
        catalog, config, results, _ = CompiledWebDeliveryTests().fixture(self.root, 2)
        catalog.update(book_id='subject', title='任意学科', catalog_revision=7)
        for card in catalog['cards']:
            card.update(word=card['id'], unit='unit')
        calls = []
        class Builder:
            def build(_self, root, wrapper, artifact, **kwargs):
                calls.append((wrapper, artifact, kwargs))
                return results[kwargs['identity'].split(':')[1]]
        initial = {'config': config, 'report': {'prepared': 2, 'cards': 2, 'fallbacks': 0}}
        with patch.object(materialize, 'prepare_library', return_value=initial):
            result = self.delivery.build_library(self.root, catalog, config, builder=Builder(),
                metadata={'cards': {}}, source_url='https://study.test/book/index.html')
        self.assertEqual(result['report']['modes'], {'compiled': 2, 'authored': 0})
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['config']['compiledDelivery'], 'envelope.v1')
        index = json.loads((self.root/result['config']['preparedIndex']['src']).read_bytes())
        for row in index['cards'].values():
            self.assertEqual(json.loads((self.root/row['src']).read_bytes())['schema'], 'study-compiled-delivery.v1')


if __name__ == '__main__':
    unittest.main()
