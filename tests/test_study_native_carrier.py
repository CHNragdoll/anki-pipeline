"""Standalone carrier checks; no exporter, host, collection or client writes."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
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


if __name__ == '__main__':
    unittest.main()
