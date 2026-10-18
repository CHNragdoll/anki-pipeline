"""Standalone carrier checks; no exporter, host, collection or client writes."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from anki_pipeline import study_native_carrier as carrier


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/compiled-history-text-split-v1'
PREFIX = 'window.StudyCompiledNative.register('


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def literal(pin, text):
    return (PREFIX + compact(pin) + ',' + compact(text).replace('<', '\\u003c') + ');').encode()


def compressed_size(raw):
    encoder = zlib.compressobj(9, zlib.DEFLATED, -15)
    return len(encoder.compress(raw) + encoder.flush())


def unpack(raw):
    text = raw.decode('utf-8')
    if text.startswith(PREFIX):
        pin, restored = json.loads('[' + text[len(PREFIX):-2] + ']')
        return pin, restored
    if not text.startswith(carrier.PACK_PREFIX) or not text.endswith(carrier.PACK_END):
        raise AssertionError('unknown carrier wrapper')
    pin, dictionary, parts = json.loads(text[len(carrier.PACK_PREFIX):-len(carrier.PACK_END)])
    if any(not isinstance(value, str) for value in dictionary):
        raise AssertionError('non-string dictionary')
    if any(type(part) is not str and (type(part) is not int or not 0 <= part < len(dictionary))
           for part in parts):
        raise AssertionError('invalid dictionary reference')
    return pin, ''.join(part if isinstance(part, str) else dictionary[part] for part in parts)


def real_profile():
    text = gzip.decompress((FIXTURE / 'profile.json.gz').read_bytes()).decode('utf-8')
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    if sha(text) != manifest['source_profile_sha256']:
        raise AssertionError('real fixture SHA changed')
    return text


def unicode_profile():
    # A source audit is repeated inside both bound text and history evidence.
    words = ''.join(hashlib.sha256(str(n).encode()).hexdigest() for n in range(100))
    gap = ''.join(hashlib.sha256(('gap' + str(n)).encode()).hexdigest() for n in range(700))
    evidence = '原文😀 e\u0301 </script> <tag> & "quoted" \\\t\n\x00\u2028\u2029' + words
    return compact({'2': {'exactText': '前缀' + evidence + '后缀'},
                    'gap1': gap, '1': {'history': evidence},
                    'gap2': gap[::-1], 'bank': {'😀': evidence}})


class NativeCarrierTests(unittest.TestCase):
    def assert_inverse(self, text, raw):
        pin, restored = unpack(raw)
        self.assertEqual(pin, sha(text))
        self.assertEqual(restored.encode('utf-8'), text.encode('utf-8'))
        self.assertEqual(sha(restored), pin)
        self.assertNotIn(b'<', raw)

    def test_real_frozen_profile_packs_with_actual_deflate_savings(self):
        text = real_profile()
        raw = carrier.build_native_carrier(sha(text), text)
        self.assertTrue(raw.decode().startswith(carrier.PACK_PREFIX))
        self.assert_inverse(text, raw)
        self.assertGreaterEqual(compressed_size(literal(sha(text), text)) - compressed_size(raw), 128)
        self.assertEqual(carrier.build_native_carrier(sha(text), text), raw)

    def test_unicode_script_end_and_json_escaping_are_exact(self):
        text = unicode_profile()
        raw = carrier.build_native_carrier(sha(text), text)
        self.assertTrue(raw.decode().startswith(carrier.PACK_PREFIX))
        self.assert_inverse(text, raw)
        self.assertNotIn(b'</script>', raw)

    def test_original_whitespace_duplicate_keys_and_escape_spelling_survive(self):
        evidence = json.loads(unicode_profile())['1']['history']
        text = ' \n{ "2" : ' + compact(evidence) + ', "1":' + compact(evidence) + ', "2":0, "escaped":"\\u4e2d" }\t'
        self.assert_inverse(text, carrier.build_native_carrier(sha(text), text))

    def test_non_json_and_json_without_useful_repetition_keep_literal_bytes(self):
        values = ['<!doctype html></script>中文😀\\\n' * 200, 'window.x="<tag>";',
                  '{', '', '{}', '[]', 'null', compact({'unique': 'z' * 4096}),
                  compact({'a': 'z' * 4096, 'b': 'z' * 4096}),
                  '[' * 2000 + '0' + ']' * 2000,
                  '{"escaped":"' + '\\ud800' * 1024 + '"}']
        for text in values:
            with self.subTest(text=text[:40]):
                self.assertEqual(carrier.build_native_carrier(sha(text), text), literal(sha(text), text))

    def test_invalid_pin_or_non_text_input_is_rejected(self):
        for pin, text in [('0' * 64, 'different'), (sha('x').upper(), 'x'),
                          ('g' * 64, 'x'), (sha('x') + '0', 'x'), (None, 'x'),
                          (sha('x'), b'x'), (sha('x'), '\ud800')]:
            with self.subTest(pin=pin, text=repr(text)):
                with self.assertRaises(ValueError):
                    carrier.build_native_carrier(pin, text)

    def test_optimization_budget_exhaustion_returns_the_original_literal(self):
        text = unicode_profile()
        for name in ['_MAX_JSON_BYTES', '_MAX_VISITED_VALUES', '_MAX_LEAF_VALUES',
                     '_MAX_LEAF_CHARS', '_MAX_PARTS']:
            with self.subTest(budget=name), patch.object(carrier, name, 1):
                self.assertEqual(carrier.build_native_carrier(sha(text), text), literal(sha(text), text))

    def test_compressed_saving_threshold_is_at_least_128_bytes(self):
        text = unicode_profile()
        with patch.object(carrier, '_deflate_size', side_effect=[1000, 873]):
            self.assertEqual(carrier.build_native_carrier(sha(text), text), literal(sha(text), text))
        with patch.object(carrier, '_deflate_size', side_effect=[1000, 872]):
            self.assertTrue(carrier.build_native_carrier(sha(text), text).decode().startswith(carrier.PACK_PREFIX))

    def test_node_registers_once_and_restores_original_utf8_and_sha(self):
        texts = [real_profile(), unicode_profile(), '<p>literal 😀 </script></p>',
                 ' { "raw" : "\\u4e2d", "raw": 1 }\n']
        payload = [{'pin': sha(text), 'text': text,
                    'carrier': carrier.build_native_carrier(sha(text), text).decode()} for text in texts]
        script = '''const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const inputs=JSON.parse(fs.readFileSync(0,'utf8'));
for(const input of inputs){let calls=0;const context={window:{StudyCompiledNative:{register(pin,text){calls++;assert.equal(pin,input.pin);assert.equal(typeof text,'string');assert.deepEqual(Buffer.from(text,'utf8'),Buffer.from(input.text,'utf8'));assert.equal(crypto.createHash('sha256').update(text,'utf8').digest('hex'),pin);}}}};vm.runInNewContext(input.carrier,context,{timeout:5000});assert.equal(calls,1);}
console.log(JSON.stringify({cases:inputs.length,registerCallsPerCase:1,exactUTF8:true}));'''
        result = subprocess.run(['node', '-e', script], input=json.dumps(payload), text=True,
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'cases': 4, 'registerCallsPerCase': 1, 'exactUTF8': True})


class NativeCarrierBundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def source(self, raw, alias=None):
        pin = hashlib.sha256(raw).hexdigest()
        alias = alias or '_study_native_' + pin + '.js'
        path = self.root / alias
        path.write_bytes(raw)
        return alias, path, pin

    def plan(self, sources, consumers=None):
        # Existing streaming tests describe one profile requiring every source.
        if consumers is None:
            consumers = {alias: {'opaque-profile'} for alias, _, _ in sources}
        return carrier.plan_native_carrier_bundles(
            {alias: path for alias, path, pin in sources},
            {alias: pin for alias, path, pin in sources}, consumers=consumers)

    def test_missing_consumer_map_preserves_every_source_without_bundling(self):
        sources = [self.source(b'/* profile one */'), self.source(b'/* profile two */')]
        plan = carrier.plan_native_carrier_bundles(
            {alias: path for alias, path, _ in sources},
            {alias: pin for alias, _, pin in sources})
        self.assertEqual(plan['replacements'], {})
        self.assertEqual(plan['media'], {alias: path for alias, path, _ in sources})
        self.assertEqual(plan['media_pins'], {alias: pin for alias, _, pin in sources})

    def test_large_back_assets_group_without_front_initial_payloads(self):
        back = [self.source(b'/*' + bytes([n]) * (300 * 1024) + b'*/') for n in (65, 66)]
        front = self.source(b'/* packet required on both initial sides */')
        identity = ('opaque-card', 'a' * 64)
        consumers = {alias: {(*identity, 'back-initial')} for alias, _, _ in back}
        consumers[front[0]] = {(*identity, stage) for stage in ('front-initial', 'back-initial')}
        plan = self.plan(back + [front], consumers)
        self.assertEqual(set(plan['replacements']), {alias for alias, _, _ in back})
        bundle = plan['media'][plan['replacements'][back[0][0]]]
        self.assertEqual({member.alias for member in bundle.members}, set(consumers) - {front[0]})
        self.assertIs(plan['media'][front[0]], front[1])

    def test_explicit_unknown_consumers_are_never_grouped(self):
        sources = [self.source(('/* stage ' + str(n) + ' */').encode()) for n in range(3)]
        consumers = {alias: {('card', 'a' * 64, 'back-initial')} for alias, _, _ in sources}
        consumers[sources[0][0]] = None
        plan = self.plan(sources, consumers)
        self.assertIs(plan['media'][sources[0][0]], sources[0][1])
        self.assertEqual(set(plan['replacements']), {alias for alias, _, _ in sources[1:]})

    def test_only_identical_nonempty_consumer_sets_share_a_bundle(self):
        sources = [self.source(('/* consumer ' + str(n) + ' */').encode()) for n in range(9)]
        first, second = ('opaque-id', 'a' * 64), ('opaque-id', 'b' * 64)
        consumers = {sources[n][0]: users for n, users in enumerate(
            ({first}, {first}, {second}, {second}, {first, second}, {second, first}, set()))}
        # Last two aliases have no usage record. An explicit empty record is also inert.
        plan = self.plan(sources, consumers)
        self.assertEqual(len(plan['media']), 6)
        self.assertEqual(set(plan['replacements']), {alias for alias, _, _ in sources[:6]})
        for alias, path, _ in sources[6:]:
            self.assertIs(plan['media'][alias], path)
        for value in plan['media'].values():
            if isinstance(value, carrier.NativeCarrierBundle):
                cohort, = {frozenset(consumers[member.alias]) for member in value.members}
                self.assertTrue(cohort)
                for consumer in cohort:
                    original = {alias for alias, users in consumers.items() if consumer in users}
                    self.assertLessEqual({member.alias for member in value.members}, original)
        self.assertEqual(plan, self.plan(list(reversed(sources)), dict(reversed(list(consumers.items())))))

    def test_caps_split_within_each_consumer_cohort(self):
        sources = [self.source(('/* split ' + str(n) + ' */').encode()) for n in range(9)]
        consumers = {alias: {n % 2} for n, (alias, _, _) in enumerate(sources)}
        with patch.object(carrier, '_BUNDLE_COUNT_LIMIT', 2), patch.object(carrier, '_BUNDLE_SIZE_LIMIT', 100):
            plan = self.plan(sources, consumers)
        for value in plan['media'].values():
            if isinstance(value, carrier.NativeCarrierBundle):
                self.assertLessEqual(len(value.members), 2)
                self.assertLessEqual(value.size, 100)
                self.assertEqual(len({frozenset(consumers[member.alias]) for member in value.members}), 1)
        self.assertEqual(len(plan['media']), 5)

    def test_sorted_stream_bundles_are_deterministic_lossless_and_do_not_write_or_delete(self):
        sources = [self.source(literal(sha(text), text)) for text in ('中文😀', '</script>', 'third')]
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        first, second = self.plan(sources), self.plan(list(reversed(sources)))
        self.assertEqual(first, second)
        self.assertEqual(len(first['media']), 1)
        alias, bundle = next(iter(first['media'].items()))
        self.assertIsInstance(bundle, carrier.NativeCarrierBundle)
        expected = b''.join(path.read_bytes() for _, path, _ in sorted(sources))
        self.assertEqual(b''.join(bundle.iter_chunks(chunk_size=7)), expected)
        self.assertEqual(bundle.size, len(expected))
        self.assertEqual(bundle.sha256, hashlib.sha256(expected).hexdigest())
        self.assertEqual(alias, '_study_native_' + bundle.sha256 + '.js')
        self.assertEqual(first['media_pins'], {alias: bundle.sha256})
        self.assertEqual(first['replacements'], {old: alias for old, _, _ in sources})
        self.assertEqual([member.alias for member in bundle.members], sorted(before))
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, before)
        with self.assertRaises(AttributeError):
            bundle.size = 0
        with self.assertRaises(AttributeError):
            bundle.members[0].size = 0

    def test_singletons_bootstrap_and_oversized_carriers_keep_the_original_paths(self):
        small = self.source(b'/* small */')
        exact = self.source(b'/*' + b'x' * (8 * 1024 * 1024 - 3) + b'*/')
        bootstrap = self.source(b'/* bootstrap */', '_study_native_bootstrap_' + 'a' * 64 + '.js')
        other = self.source(b'original media', 'original.mp3')
        sources = [small, exact, bootstrap, other]
        plan = self.plan(sources)
        self.assertEqual(plan['replacements'], {})
        for alias, path, pin in sources:
            self.assertIs(plan['media'][alias], path)
            self.assertEqual(plan['media_pins'][alias], pin)
        below = self.source(b'/*' + b'y' * (256 * 1024 - 5) + b'*/')
        plan = self.plan(sources + [below])
        self.assertIs(plan['media'][exact[0]], exact[1])
        self.assertEqual(set(plan['replacements']), {small[0], below[0]})

    def test_bundle_limits_include_exactly_eight_mib_and_at_most_256_members(self):
        sources = []
        for n in range(32):
            prefix = ('/*' + str(n) + ':').encode()
            sources.append(self.source(prefix + b'x' * (256 * 1024 - 1 - len(prefix) - 2) + b'*/'))
        sources.append(self.source(b'/*' + b'y' * 28 + b'*/'))
        plan = self.plan(sources)
        bundle, = plan['media'].values()
        self.assertEqual(bundle.size, 8 * 1024 * 1024)
        plan = self.plan(sources + [self.source(b';')])
        self.assertEqual(len(plan['media']), 2)
        for item in plan['media'].values():
            if isinstance(item, carrier.NativeCarrierBundle):
                self.assertLessEqual(item.size, 8 * 1024 * 1024)
        tiny = [self.source(('/* count ' + str(n) + ' */').encode()) for n in range(257)]
        plan = self.plan(tiny)
        bundles = [item for item in plan['media'].values() if isinstance(item, carrier.NativeCarrierBundle)]
        self.assertEqual([len(bundle.members) for bundle in bundles], [256])
        last_alias, last_path, _ = sorted(tiny)[-1]
        self.assertIs(plan['media'][last_alias], last_path)

    def test_changed_missing_nonregular_or_unpinned_sources_fail_closed(self):
        sources = [self.source(b'/* one */'), self.source(b'/* two */')]
        media = {alias: path for alias, path, pin in sources}
        pins = {alias: pin for alias, path, pin in sources}
        for bad in ({}, {**pins, sources[0][0]: '0' * 64}):
            with self.subTest(pins=bad), self.assertRaises(ValueError):
                carrier.plan_native_carrier_bundles(media, bad)
        bundle, = self.plan(sources)['media'].values()
        bundle.members[0].path.write_bytes(b'x' * bundle.members[0].size)
        with self.assertRaises(ValueError):
            b''.join(bundle.iter_chunks())
        target = self.root / 'target.bin'; target.write_bytes(b'target')
        link = self.root / 'link.js'; link.symlink_to(target)
        for path in (link, self.root, self.root / 'missing.js'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                carrier.plan_native_carrier_bundles({'other.js': path}, {'other.js': hashlib.sha256(b'target').hexdigest()})
        with self.assertRaises(ValueError):
            carrier.plan_native_carrier_bundles({'other.js': target}, {'other.js': '0' * 64})
        corrupt = self.source(b'/* before */')
        corrupt[1].write_bytes(b'/* after! */')
        with self.assertRaises(ValueError):
            self.plan([corrupt])

    def test_identical_replacement_and_late_member_changes_are_detected(self):
        sources = [self.source(b'/* alpha */'), self.source(b'/* beta */')]
        bundle, = self.plan(sources)['media'].values()
        member = bundle.members[0]
        replacement = self.root / 'replacement.js'
        replacement.write_bytes(member.path.read_bytes())
        replacement.replace(member.path)
        with self.assertRaises(ValueError):
            b''.join(bundle.iter_chunks())
        bundle, = self.plan(sources)['media'].values()
        chunks = bundle.iter_chunks(chunk_size=256)
        self.assertTrue(next(chunks))
        self.assertTrue(next(chunks))  # First source has already passed its EOF check.
        bundle.members[0].path.write_bytes(b'x' * bundle.members[0].size)
        with self.assertRaises(ValueError):
            b''.join(chunks)
        for chunk_size in (0, -1, True, 1.5):
            with self.subTest(chunk_size=chunk_size), self.assertRaises(ValueError):
                next(bundle.iter_chunks(chunk_size))

    def test_source_change_during_planning_or_streaming_is_not_swallowed(self):
        sources = [self.source(b'/* first */'), self.source(b'/* second */')]
        original = carrier._iter_source_chunks
        def changed(member, chunk_size):
            for chunk in original(member, chunk_size):
                yield chunk
                member.path.write_bytes(b'x' * member.size)
        with patch.object(carrier, '_iter_source_chunks', side_effect=changed):
            with self.assertRaises(ValueError):
                self.plan(sources)
        sources = [self.source(b'/* third */'), self.source(b'/* fourth */')]
        bundle, = self.plan(sources)['media'].values()
        chunks = bundle.iter_chunks(chunk_size=3)
        self.assertTrue(next(chunks))
        member = bundle.members[0]
        member.path.write_bytes(b'x' * member.size)
        with self.assertRaises(ValueError):
            b''.join(chunks)

    def test_concatenated_canonical_programs_register_every_original_text_once(self):
        texts = ['原文😀 </script> e\u0301', unicode_profile()]
        sources = [self.source(carrier.build_native_carrier(sha(text), text)) for text in texts]
        plan = self.plan(sources)
        bundle, = plan['media'].values()
        expected = {sha(text): text for text in texts}
        payload = {'program': b''.join(bundle.iter_chunks()).decode(), 'expected': expected}
        script = '''const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const v=JSON.parse(fs.readFileSync(0,'utf8')),seen=new Set();
vm.runInNewContext(v.program,{window:{StudyCompiledNative:{register(pin,text){assert.equal(text,v.expected[pin]);assert.equal(crypto.createHash('sha256').update(text,'utf8').digest('hex'),pin);assert.ok(!seen.has(pin));seen.add(pin);}}}},{timeout:5000});assert.equal(seen.size,Object.keys(v.expected).length);'''
        result = subprocess.run(['node', '-e', script], input=json.dumps(payload), text=True,
            capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
