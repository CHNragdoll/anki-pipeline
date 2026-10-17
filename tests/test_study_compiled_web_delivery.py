"""Per-card web envelopes: tiny protocol fixtures, no producer/PG/live browser."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
ORIGINAL = '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e'
MODULE = '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4'
SHA = lambda raw: hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()
JSON = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


class CompiledWebDeliveryTests(unittest.TestCase):
    def fixture(self, root, count=1, history=False):
        (root / 'cards').mkdir()
        (root / 'media').mkdir()
        store = root / 'build-assets'
        store.mkdir()
        front = '<html><head><base href="../media/"></head><body>original front 中文</body></html>'
        back = front.replace('original front 中文', 'complete back 中文😀')
        cards = [{'id': 'card-' + str(i), 'url': 'cards/original-' + str(i) + '.html'} for i in range(count)]
        wrapper = web.card_shell(JSON([front, back]).decode(), '../media/').encode()
        for card in cards:
            (root / card['url']).write_bytes(wrapper)
        catalog = {'cards': cards}
        initial = materialize.prepare_library(root, catalog, {'policy': {'external': {}, 'inline': []}})
        index = json.loads((root / initial['config']['preparedIndex']['src']).read_bytes())
        results, inputs = {}, {}
        for card in cards:
            original_rule = index['cards'][card['id']]
            prepared = json.loads((root / original_rule['src']).read_bytes())
            # Explicit source/module protocol fixture; no original JS is run.
            prepared['modules'] = {ORIGINAL: {'src': 'evidence/original.js',
                                            'sha256': MODULE, 'original_sha256': ORIGINAL}}
            raw = JSON(prepared)
            name = 'evidence/' + materialize._write_addressed(
                root / 'evidence', '_study_prepared_card_', '.json', raw)
            packed = gzip.compress(raw, compresslevel=6, mtime=0)
            gzip_name = 'evidence/' + materialize._write_addressed(
                root / 'evidence', '_study_prepared_card_', '.json.gz', packed)
            first = materialize.front_artifact_bytes(card, front, prepared, SHA(raw))
            first_name = 'evidence/_study_prepared_front_' + SHA(first) + '.json'
            (root / first_name).write_bytes(first)
            original_rule = {'src': name, 'sha256': SHA(raw), 'gzipSrc': gzip_name,
                             'front': {'src': first_name, 'sha256': SHA(first)}}
            index['cards'][card['id']] = original_rule
            bindings = {key: SHA(key) for key in materialize._COMPILED_BINDINGS}
            bindings.update(sourceArtifactSha256=SHA(raw), sourceWrapperSha256=SHA(wrapper),
                            sourcePayloadSha256=prepared['source_payload_sha256'],
                            sourceSideSha256=SHA(back), expandedSideSha256=SHA(back),
                            frameRuntimeSha256=materialize.COMPILED_DELIVERY_BASE_SHA256,
                            frameHTMLSha256='b1510d852c94f7bdd98fd90fa3853ed006e1b90345f194819e4900e0a0e99b8a',
                            originalModuleSha256=ORIGINAL, nativeModuleSha256=MODULE,
                            derivedHTMLSha256=SHA(back))
            if history:
                bindings.update(historyScopeEvidenceSha256=SHA('actual scope fixture'),
                                historyProducerSourceSha256=SHA('qualified history producer fixture'))
            profile = {'schema': 'study-compiled-card-interactions.v1', 'version': 1,
                       'bindings': bindings, 'nodeBindings': []}
            profile_raw = JSON(profile)
            resources = {}

            def asset(content, suffix):
                pin = SHA(content)
                name = '_qa_compiled_' + pin + suffix
                path = store / name
                path.write_bytes(content)
                resources['https://study.test/book/' + name] = {
                    'path': str(path), 'sha256': pin, 'bytes': len(content)}
                return {'src': name, 'sha256': pin}

            entry = {'decoded': True, 'source': {
                'wrapper_sha256': SHA(wrapper), 'payload_sha256': prepared['source_payload_sha256'],
                'side_sha256': SHA(back), 'expanded_sha256': SHA(back), 'registry_pins': []},
                'module': {'original_sha256': ORIGINAL, 'sha256': MODULE},
                'anchors': {'schema': profile['schema'], 'version': 1, 'bindings': bindings,
                            'profileSha256': SHA(profile_raw), 'htmlSha256': SHA(back)},
                'html': asset(back.encode(), '.html'), 'profile': asset(profile_raw, '.json')}
            runtime = asset((ROOT / 'anki_pipeline/compiled/card-runtime.js').read_bytes(), '.js')
            results[card['id']] = {'mode': 'compiled', 'identity': card['id'], 'entry': entry,
                                   'runtime': runtime, 'resources': resources}
            inputs[card['id']] = {'rule': original_rule, 'prepared': prepared,
                                   'preparedRaw': raw.decode(), 'wrapper': wrapper.decode(), 'front': front}
        raw_index = JSON(index)
        index_name = 'evidence/_study_prepared_index_' + SHA(raw_index) + '.json'
        (root / index_name).write_bytes(raw_index)
        initial['config']['preparedIndex'] = {'src': index_name, 'sha256': SHA(raw_index)}
        return catalog, initial['config'], results, inputs

    def test_fixed_transport_inverse_keeps_8a_and_default_inline_html_unchanged(self):
        runtime = materialize.COMPILED_DELIVERY_FRAME_RUNTIME
        self.assertEqual(SHA(runtime), '3ace5fac8fa04838fe7bcb000825f1b7410f8fa419d4121b466e98d5bf5f0df2')
        from anki_pipeline.study_compiled_runtime import PREVIOUS_RUNTIME_SHA256, SUPPLEMENTAL_RUNTIME_SHA256, TEXT_SPLIT_RUNTIME_SHA256, INITIAL_HISTORY_RUNTIME_SHA256, SHARED_HISTORY_RUNTIME_SHA256
        shared_pins = json.dumps(sorted((materialize.LEGACY_RUNTIME_SHA256,
                                        PREVIOUS_RUNTIME_SHA256, SUPPLEMENTAL_RUNTIME_SHA256,
                                        TEXT_SPLIT_RUNTIME_SHA256, INITIAL_HISTORY_RUNTIME_SHA256,
                                        SHARED_HISTORY_RUNTIME_SHA256)))
        shared = runtime.replace(json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)), shared_pins)
        self.assertEqual(SHA(shared), 'd4ea42351e5bd6f99ba7b3ea262fcd895e4b27832f27183caf0b87d905a97e21')
        initial_pins = json.dumps(sorted((materialize.LEGACY_RUNTIME_SHA256,
                                         PREVIOUS_RUNTIME_SHA256, SUPPLEMENTAL_RUNTIME_SHA256,
                                         TEXT_SPLIT_RUNTIME_SHA256, INITIAL_HISTORY_RUNTIME_SHA256)))
        initial = runtime.replace(json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)), initial_pins)
        self.assertEqual(SHA(initial), '2c63e43a7da3bdea79b1e6bc0792fe62a5ae191cc0524b7ac9ceddc4ec3d710c')
        text_split_pins = json.dumps(sorted((materialize.LEGACY_RUNTIME_SHA256,
                                            PREVIOUS_RUNTIME_SHA256, SUPPLEMENTAL_RUNTIME_SHA256,
                                            TEXT_SPLIT_RUNTIME_SHA256)))
        text_split = runtime.replace(json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)), text_split_pins)
        self.assertEqual(SHA(text_split), '37edcb1777358d9898261f034a332a7fda948e6a9e8795c64778c3837fee567a')
        supplemental_pins = json.dumps(sorted((materialize.LEGACY_RUNTIME_SHA256,
                                              PREVIOUS_RUNTIME_SHA256, SUPPLEMENTAL_RUNTIME_SHA256)))
        supplemental = runtime.replace(json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)), supplemental_pins)
        self.assertEqual(SHA(supplemental), '9c5beff39c9359b67d4dc6f0f62d8f845d81d742f3d5e67067987d8e98c712fa')
        previous_pins = json.dumps(sorted((materialize.LEGACY_RUNTIME_SHA256, PREVIOUS_RUNTIME_SHA256)))
        previous = runtime.replace(json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)), previous_pins)
        self.assertEqual(SHA(previous), 'bf919e2645c327dacbe1493fb9e42fe48971676626cc0852c2c31fd17e77c379')
        # Preserve the previous transport seal as an independently reversible
        # intermediate; never silently replace the historical 8a/A baselines.
        before, after = materialize._COMPILED_DELIVERY_FRAME_PATCHES[-1]
        legacy = runtime.replace(after, before, 1)
        expanded = '!' + json.dumps(sorted(materialize.ADMITTED_RUNTIME_SHA256)) + '.includes(assets.runtime?.sha256)'
        self.assertEqual(legacy.count(expanded), 1)
        legacy = legacy.replace(expanded, "assets.runtime?.sha256!=='" + materialize.LEGACY_RUNTIME_SHA256 + "'", 1)
        self.assertEqual(SHA(legacy), 'f6dae439b3136f09aa0f1aa56ef39fa16b03ef2e83d9122b3f088028a97b0925')
        for before, after in reversed(materialize._COMPILED_DELIVERY_FRAME_PATCHES):
            self.assertEqual(runtime.count(after), 1)
            runtime = runtime.replace(after, before, 1)
        self.assertEqual(SHA(runtime), materialize.COMPILED_DELIVERY_BASE_SHA256)
        self.assertEqual(runtime, materialize.PREPARED_FRAME_RUNTIME)
        self.assertEqual(SHA(materialize.prepared_frame_html()),
                         'b1510d852c94f7bdd98fd90fa3853ed006e1b90345f194819e4900e0a0e99b8a')

    def test_one_envelope_per_card_keeps_original_source_profile_and_global_small(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, config, results, inputs = self.fixture(root, 2)
            source_bytes = {str(path.relative_to(root)): path.read_bytes()
                            for path in (root / 'cards').iterdir()}
            old_profile = {key: copy.deepcopy(value['entry']['anchors']) for key, value in results.items()}
            (root / 'index.html').write_bytes(b'active original entry')
            attached = materialize.attach_compiled_library(root, catalog, config, results)
            self.assertEqual((root / 'index.html').read_bytes(), b'active original entry')
            self.assertEqual(attached['report']['compiled'], 2)
            new_index = json.loads((root / attached['config']['preparedIndex']['src']).read_bytes())
            for card in catalog['cards']:
                key = card['id']
                rule = new_index['cards'][key]
                wire = (root / rule['src']).read_bytes()
                envelope = json.loads(wire)
                self.assertLess(len(wire), 6000)
                self.assertEqual(gzip.decompress((root / rule['gzipSrc']).read_bytes()), wire)
                self.assertEqual(envelope['prepared']['sha256'], inputs[key]['rule']['sha256'])
                self.assertEqual(envelope['prepared']['gzipSrc'], inputs[key]['rule']['gzipSrc'])
                self.assertNotEqual(envelope['prepared']['gzipSrc'], envelope['prepared']['src'] + '.gz')
                self.assertEqual(SHA((root / envelope['prepared']['gzipSrc']).read_bytes()),
                                 Path(envelope['prepared']['gzipSrc']).name.removeprefix('_study_prepared_card_').removesuffix('.json.gz'))
                self.assertEqual((root / envelope['prepared']['src']).read_text(), inputs[key]['preparedRaw'])
                self.assertEqual(envelope['entry']['anchors'], old_profile[key])
                self.assertEqual((root / envelope['entry']['profile']['src']).read_bytes(),
                                 (root / 'build-assets' / results[key]['entry']['profile']['src']).read_bytes())
                first = json.loads((root / rule['front']['src']).read_bytes())
                self.assertEqual(first['full_prepared_sha256'], rule['sha256'])
                self.assertEqual(first['source_front'], inputs[key]['front'])
            html = attached['config']['html']
            data = html.split('<script id="study-compiled-assets" type="application/json">', 1)[1].split('</script>', 1)[0]
            assets = json.loads(data)
            self.assertEqual(assets['entries'], {})
            self.assertEqual(assets['delivery'], 'envelope.v1')
            self.assertLess(len(data), 512)
            self.assertTrue(all(card['id'] not in data for card in catalog['cards']))
            self.assertEqual(source_bytes, {str(path.relative_to(root)): path.read_bytes()
                                          for path in (root / 'cards').iterdir()})

    def test_invalid_source_resource_and_all_seventeen_bindings_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, config, results, _ = self.fixture(root)
            changes = [lambda r: r['entry']['anchors']['bindings'].pop('readerDelegateSha256'),
                       lambda r: r['entry']['anchors']['bindings'].update(sourceArtifactSha256='0'*64),
                       lambda r: r['entry']['anchors']['bindings'].update(frameRuntimeSha256='0'*64),
                       lambda r: r['entry']['anchors']['bindings'].update(sourceSideSha256='0'*64),
                       lambda r: r['entry']['source'].update(wrapper_sha256='0'*64),
                       lambda r: r['entry']['html'].update(src='https://outside.test/body.html'),
                       lambda r: r['runtime'].update(sha256='0'*64),
                       lambda r: r.update(resources={})]
            for change in changes:
                bad = copy.deepcopy(results)
                change(bad['card-0'])
                with self.subTest(change=change), self.assertRaises(ValueError):
                    materialize.attach_compiled_library(root, catalog, config, bad)
            self.assertNotIn('compiledDelivery', config)
            self.assertEqual(SHA(materialize.PREPARED_FRAME_RUNTIME), materialize.COMPILED_DELIVERY_BASE_SHA256)

    def test_history_headers_require_the_exact_paired_provenance_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, config, results, _ = self.fixture(root, history=True)
            attached = materialize.attach_compiled_library(root, catalog, config, results)
            index = json.loads((root / attached['config']['preparedIndex']['src']).read_bytes())
            envelope = json.loads((root / index['cards']['card-0']['src']).read_bytes())
            self.assertEqual(envelope['entry']['anchors']['bindings'], results['card-0']['entry']['anchors']['bindings'])
            for change in [lambda b: b.pop('historyScopeEvidenceSha256'),
                           lambda b: b.update(historyProducerSourceSha256='invalid'),
                           lambda b: b.update(unknownBindingSha256='0'*64)]:
                bad = copy.deepcopy(results)
                change(bad['card-0']['entry']['anchors']['bindings'])
                with self.assertRaises(ValueError):
                    materialize.attach_compiled_library(root, catalog, config, bad)

    def test_replaced_evidence_directory_never_receives_new_publications(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, config, results, _ = self.fixture(root)
            foreign = root / 'foreign'
            foreign.mkdir()
            original = materialize._compiled_blob
            changed = False

            def replace_then_publish(*args):
                nonlocal changed
                if not changed:
                    changed = True
                    (root / 'evidence').rename(root / 'owned-evidence')
                    (root / 'evidence').symlink_to(foreign, target_is_directory=True)
                return original(*args)

            with patch.object(materialize, '_compiled_blob', side_effect=replace_then_publish):
                with self.assertRaises(ValueError):
                    materialize.attach_compiled_library(root, catalog, config, results)
            self.assertEqual(list(foreign.iterdir()), [])

    @unittest.skipUnless(os.environ.get('STUDY_COMPILED_RESULTS_JSONL') and
                         os.environ.get('STUDY_COMPILED_SOURCE_ROOT'), 'explicit read-only batch inputs not supplied')
    def test_real_batch_17_and_19_headers_and_compressed_source_addresses(self):
        """Opt-in: read two completed results; publish only to a private fixture."""
        import re
        source = Path(os.environ['STUDY_COMPILED_SOURCE_ROOT'])
        page = (source / 'index.html').read_text()
        config = json.loads(re.search(r'<script id="study-library-config" type="application/json">(.*?)</script>',
                                      page, re.S).group(1))['sharedFrame']
        index_raw = (source / config['preparedIndex']['src']).read_bytes()
        self.assertEqual(SHA(index_raw), config['preparedIndex']['sha256'])
        source_index = json.loads(index_raw)
        catalog = json.loads((source / 'catalog.json').read_bytes())
        selected = {}
        with Path(os.environ['STUDY_COMPILED_RESULTS_JSONL']).open() as stream:
            for number, line in enumerate(stream):
                if number >= 150:
                    break
                value = json.loads(line)
                result = value.get('result', {})
                count = len(result.get('entry', {}).get('anchors', {}).get('bindings', {}))
                if value.get('status') == 'ok' and result.get('mode') == 'compiled' and count in {17, 19}:
                    selected.setdefault(count, result)
                if set(selected) == {17, 19}:
                    break
        self.assertEqual(set(selected), {17, 19})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'evidence').mkdir()
            cards, index, results = [], {'schema': 'study-prepared-index.v1', 'cards': {}}, {}
            for count, result in selected.items():
                pin = result['entry']['anchors']['bindings']['sourceArtifactSha256']
                matches = [(identity, rule) for identity, rule in source_index['cards'].items() if rule['sha256'] == pin]
                self.assertEqual(len(matches), 1)
                identity, rule = matches[0]
                card = next(card for card in catalog['cards'] if card['id'] == identity)
                cards.append(card)
                index['cards'][identity] = rule
                results[identity] = result
                for descriptor in (rule, rule['front']):
                    raw = (source / descriptor['src']).read_bytes()
                    self.assertEqual(SHA(raw), descriptor['sha256'])
                    (root / descriptor['src']).write_bytes(raw)
                packed = (source / rule['gzipSrc']).read_bytes()
                self.assertEqual(SHA(packed), Path(rule['gzipSrc']).name.removeprefix('_study_prepared_card_').removesuffix('.json.gz'))
                self.assertEqual(gzip.decompress(packed), (root / rule['src']).read_bytes())
                profile_descriptor = next(item for item in result['resources'].values()
                                          if Path(item['path']).name == result['entry']['profile']['src'])
                profile_raw = Path(profile_descriptor['path']).read_bytes()
                self.assertEqual(SHA(profile_raw), result['entry']['profile']['sha256'])
                self.assertEqual(json.loads(profile_raw)['bindings'], result['entry']['anchors']['bindings'])
            raw = JSON(index)
            name = 'evidence/_study_prepared_index_' + SHA(raw) + '.json'
            (root / name).write_bytes(raw)
            result = materialize.attach_compiled_library(root, {'cards': cards},
                {**config, 'preparedIndex': {'src': name, 'sha256': SHA(raw)}}, results)
            self.assertEqual(result['report']['compiled'], 2)
            attached = json.loads((root / result['config']['preparedIndex']['src']).read_bytes())
            packets = []
            for identity, rule in attached['cards'].items():
                envelope = json.loads((root / rule['src']).read_bytes())
                original = source_index['cards'][identity]
                self.assertEqual(envelope['prepared']['gzipSrc'], original['gzipSrc'])
                self.assertEqual(envelope['entry']['anchors'], results[identity]['entry']['anchors'])
                prepared = json.loads((root / original['src']).read_bytes())
                prepared['compiled_delivery'] = {'schema': 'study-compiled-packet.v1', 'card_id': identity,
                    'source_artifact_sha256': original['sha256'], 'entry': envelope['entry'], 'runtime': envelope['runtime']}
                packets.append({'id': identity, 'prepared': prepared})
            program = r"""
const fs=require('node:fs'),assert=require('node:assert/strict'),v=JSON.parse(fs.readFileSync(0,'utf8'));
const canonicalJSON=JSON.stringify;eval(v.helper);
for(const packet of v.packets){const assets={entries:{},runtime:packet.prepared.compiled_delivery.runtime,delivery:'envelope.v1'};
assert.equal(compiledDeliveryEntry(assets,packet),packet.prepared.compiled_delivery.entry)}
"""
            completed = subprocess.run([NODE, '-e', program], cwd=ROOT, text=True, capture_output=True,
                input=json.dumps({'helper': materialize.COMPILED_DELIVERY_ENTRY_RUNTIME, 'packets': packets}), timeout=20)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    @unittest.skipUnless(NODE, 'Node.js is unavailable')
    def test_host_to_frame_loads_the_single_card_and_rejects_cross_card_and_async_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, config, results, inputs = self.fixture(root, history=True)
            attached = materialize.attach_compiled_library(root, catalog, config, results)
            config = attached['config']
            index = json.loads((root / config['preparedIndex']['src']).read_bytes())
            rule = index['cards']['card-0']
            envelope = json.loads((root / rule['src']).read_bytes())
            resources = {str(path.relative_to(root)): path.read_text()
                         for path in (root / 'evidence').iterdir()
                         if path.suffix in {'.html', '.js', '.json'}}
            resources.update({path.name: path.read_text() for path in (root / 'build-assets').iterdir()})
            host = web.HOST_RUNTIME
            host = host[host.index('async function compiledPreparedDelivery('):host.index('async function authoredWrapperText(')]
            frame = materialize.COMPILED_DELIVERY_FRAME_RUNTIME
            frame = frame[frame.index('function makeCompiledProfileSupport('):frame.index('// Experimental explicit compiled profile;')]
            program = r"""
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),config={sharedFrame:input.config};
const hash=text=>crypto.createHash('sha256').update(text).digest('hex'),knownPinMatches=async(text,pin)=>hash(text)===pin;
const deliveryAborted=signal=>{if(signal?.aborted)throw Error('aborted')};let rule=input.rule,source=input.input.wrapper;
const preparedRule=async()=>rule,requests=[];
const deliveryArtifact=async value=>{requests.push(value.src);const text=input.resources[value.src];assert.equal(hash(text),value.sha256);return JSON.parse(text)};
const deliveryHash=async text=>hash(text),canonicalJSON=JSON.stringify,verifiedResourceString=()=>false;
const authoredResourceBase=()=>({base:'https://study.test/book/media/',baseTags:['<base href="../media/">']});
const safeURL=url=>new URL(url,'https://study.test/book/').href;
const document={baseURI:'https://study.test/book/index.html'};
eval(input.host);eval(input.helper);eval(input.frame);
(async()=>{
 const card={id:'card-0',url:'cards/original-0.html'},signal=new AbortController().signal;
 const original=JSON.stringify(input.envelope),prepared=await preparedCard(card,source,signal,null,Promise.resolve(input.envelope));
 assert.equal(JSON.stringify(input.envelope),original);assert.equal(requests.length,1);
 assert.equal(prepared.compiled_delivery.source_artifact_sha256,input.envelope.prepared.sha256);
 const assets={entries:{},runtime:input.envelope.runtime,delivery:'envelope.v1'},packet={id:card.id,prepared};
 const calls=[],resource=async(url,pin)=>{calls.push(url);const text=input.resources[new URL(url).pathname.replace('/book/','')];assert.equal(hash(text),pin);return text};
 const api=makeCompiledProfileSupport(assets,resource,knownPinMatches,canonicalJSON,()=>true);
 const result=await api.load(packet,1,prepared.sides[1],()=>true);
 assert.equal(result.html,'<html><head><base href="../media/"></head><body>complete back 中文😀</body></html>');
 assert.equal(calls.length,3);assert.ok(Object.isFrozen(result.profile));
 const front=await preparedFront(card,rule,JSON.parse(input.resources[rule.front.src]),signal);
 const full={sides:[input.input.front,'back'],base:front.base,baseTags:front.baseTags,prepared};
 assert.equal(completeFrontPacket(card,front,full).prepared.compiled_delivery,prepared.compiled_delivery);
 for(const mutate of [e=>e.card_id='other',e=>e.wrapper_url='cards/other.html',
   e=>e.entry.anchors.bindings.sourceArtifactSha256='0'.repeat(64),
   e=>e.prepared.src='https://outside.test/body.json',e=>e.source_payload_sha256='0'.repeat(64)]){
   const bad=JSON.parse(original);mutate(bad);await assert.rejects(()=>preparedCard(card,source,signal,null,Promise.resolve(bad)));
 }
 const oldFlag=config.sharedFrame.compiledDelivery;delete config.sharedFrame.compiledDelivery;
 await assert.rejects(()=>preparedCard(card,source,signal,null,Promise.resolve(input.envelope)));
 config.sharedFrame.compiledDelivery=oldFlag;
 const stale={id:card.id,prepared:JSON.parse(JSON.stringify(prepared))};let release;const wait=new Promise(resolve=>release=resolve);
 const drifting=makeCompiledProfileSupport(assets,async(url,pin)=>{await wait;return resource(url,pin)},knownPinMatches,canonicalJSON,()=>true);
 const pending=drifting.load(stale,1,stale.prepared.sides[1],()=>true);
 stale.prepared.compiled_delivery.entry=JSON.parse(JSON.stringify(stale.prepared.compiled_delivery.entry));release();
 await assert.rejects(()=>pending,/owner changed/);
 const invalid={id:card.id,prepared:JSON.parse(JSON.stringify(prepared))};
 invalid.prepared.compiled_delivery.entry.html.src='https://outside.test/body.html';
 await assert.rejects(()=>api.load(invalid,1,invalid.prepared.sides[1],()=>true),/binding/);
 const plain=JSON.parse(input.input.preparedRaw);
 const old=await preparedCard(card,source,signal,null,Promise.resolve(plain));
 assert.deepEqual(old,plain);assert.equal(old.compiled_delivery,undefined);
 eval(input.legacyFrame);
 const inline={entries:{[card.id]:input.legacyEntry},runtime:input.legacyRuntime};
 const inlinePacket={id:card.id,prepared:plain};
 const originalSupport=makeCompiledProfileSupport(inline,resource,knownPinMatches,canonicalJSON,()=>true);
 assert.equal((await originalSupport.load(inlinePacket,1,plain.sides[1],()=>true)).html,result.html);
 console.log('complete per-card source/envelope/profile ownership protocol passed');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
            result = subprocess.run([NODE, '-e', program], cwd=ROOT, capture_output=True, text=True,
                                    input=json.dumps({'config': config, 'rule': rule, 'envelope': envelope,
                                                      'input': inputs['card-0'], 'resources': resources,
                                                      'host': host, 'frame': frame,
                                                      'legacyFrame': materialize.PREPARED_FRAME_RUNTIME[
                                                          materialize.PREPARED_FRAME_RUNTIME.index('function makeCompiledProfileSupport('):
                                                          materialize.PREPARED_FRAME_RUNTIME.index('// Experimental explicit compiled profile;')],
                                                      'legacyEntry': results['card-0']['entry'],
                                                      'legacyRuntime': results['card-0']['runtime'],
                                                      'helper': materialize.COMPILED_DELIVERY_ENTRY_RUNTIME}), timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
