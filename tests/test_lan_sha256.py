"""Execute the LAN SHA-256 browser fallback in an isolated Node VM."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/lan_sha256.js"
NODE = shutil.which("node")

# This literal and hash are pinned in the 2013-01 source-reader sentence record,
# kaoyan:2013-01:p:b-9-4:1; punctuation and the source's federal’s are retained.
SOURCE_SENTENCE = (
    "On the overturned provisions the majority held that Congress had deliberately "
    "“occupied the field,” and Arizona had thus intruded on the federal’s privileged powers."
)
SOURCE_SHA256 = "57a85421684502e778fd939d3ef3288675160af94fd06d74bcd484e43d38d087"

HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const {createHash, webcrypto} = require('node:crypto');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.existsSync(input.script) ? fs.readFileSync(input.script, 'utf8') : '';
const sandbox = (crypto = {}) => ({
  crypto, isSecureContext: false, TextEncoder, DOMException,
  Uint8Array, Uint16Array, ArrayBuffer, DataView, Promise,
});
const install = context => { vm.runInNewContext(source, context); return context; };
const hex = result => Buffer.from(new Uint8Array(result)).toString('hex');
const expected = bytes => createHash('sha256').update(bytes).digest('hex');
const digest = (context, algorithm, data) => context.crypto.subtle.digest(algorithm, data);
const textHash = (context, text, algorithm = 'SHA-256') =>
  digest(context, algorithm, new TextEncoder().encode(text)).then(hex);
const run = async () => {
__TEST_BODY__
};
run().then(() => process.stdout.write('PASS\n')).catch(error => {
  console.error(error);
  process.exitCode = 1;
});
"""


class LanSha256Tests(unittest.TestCase):
    def run_node(self, body):
        self.assertIsNotNone(NODE, "The SHA-256 runtime checks require Node")
        run = subprocess.run(
            [NODE, "-e", HARNESS.replace("__TEST_BODY__", body)],
            input=json.dumps({"script": str(SCRIPT), "sentence": SOURCE_SENTENCE,
                              "sentenceHash": SOURCE_SHA256}),
            capture_output=True, text=True, cwd=ROOT, timeout=30,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(run.stdout.strip(), "PASS")

    def test_http_reader_digest_matches_source_sentence(self):
        self.run_node(r"""
  const context = install(sandbox());
  assert.equal(typeof context.crypto.subtle?.digest, 'function',
    'The HTTP reader needs crypto.subtle.digest before its hash comparison');
  assert.equal(await textHash(context, input.sentence), input.sentenceHash);
  assert.equal(context.isSecureContext, false);
""")

    def test_standard_sha256_vectors_and_padding_boundaries(self):
        self.run_node(r"""
  const context = install(sandbox());
  const vectors = [
    ['', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'],
    ['abc', 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'],
    ['abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq',
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1'],
    ['a'.repeat(1000000), 'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0'],
  ];
  for (const [text, reference] of vectors) {
    assert.equal(await textHash(context, text), reference);
  }
  for (const length of [1, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 129, 4096]) {
    const bytes = Uint8Array.from({length}, (_, index) => (index * 73 + 191) & 255);
    assert.equal(hex(await digest(context, {name: 'sha-256'}, bytes)), expected(bytes));
  }
""")

    def test_utf8_chinese_and_source_punctuation(self):
        self.run_node(r"""
  const context = install(sandbox());
  for (const text of ['中文译文：穿越沙漠。', '考研英语“联邦政府”😀', input.sentence]) {
    assert.equal(await textHash(context, text, 'sha-256'),
      expected(new TextEncoder().encode(text)));
  }
  const translation = '对于被推翻的条款，多数大法官认定国会有意“占据了这一领域”，因此亚利桑那州侵犯了联邦政府的专属权力。';
  assert.equal(await textHash(context, translation),
    '7e250303c525567d8445e957478007254cd11ee360deb146d5a8665c727f2406');
""")

    def test_buffer_sources_respect_offsets_and_snapshot_at_call(self):
        self.run_node(r"""
  const context = install(sandbox());
  const backing = Uint8Array.from([99, 98, 97, 98, 99, 96, 95, 94]);
  const views = [backing.buffer, backing.subarray(2, 5),
    new DataView(backing.buffer, 2, 3), new Uint16Array(backing.buffer, 2, 2)];
  for (const view of views) {
    const bytes = ArrayBuffer.isView(view)
      ? new Uint8Array(view.buffer, view.byteOffset, view.byteLength)
      : new Uint8Array(view);
    const result = digest(context, 'SHA-256', view);
    assert.equal(typeof result.then, 'function');
    const buffer = await result;
    assert.ok(buffer instanceof ArrayBuffer);
    assert.equal(buffer.byteLength, 32);
    assert.equal(hex(buffer), expected(bytes));
  }
  const bytes = new TextEncoder().encode('abc');
  const pending = digest(context, 'SHA-256', bytes);
  bytes.fill(0);
  assert.equal(hex(await pending),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  const crossRealm = vm.runInNewContext('new Uint8Array([97, 98, 99]).buffer');
  assert.equal(hex(await digest(context, 'SHA-256', crossRealm)),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
""")

    def test_unsupported_algorithms_and_invalid_inputs_reject(self):
        self.run_node(r"""
  const context = install(sandbox());
  for (const algorithm of ['SHA-1', 'SHA-512', 'SHA256', ' SHA-256 ',
    {name: 'AES-GCM'}, '']) {
    const result = digest(context, algorithm, new Uint8Array());
    assert.equal(typeof result.then, 'function');
    await assert.rejects(result, error => error.name === 'NotSupportedError');
  }
  for (const data of ['abc', null, undefined, [97, 98, 99], {byteLength: 3}]) {
    const result = digest(context, 'SHA-256', data);
    assert.equal(typeof result.then, 'function');
    await assert.rejects(result, error => error.name === 'TypeError');
  }
  for (const algorithm of [null, undefined, {}]) {
    await assert.rejects(digest(context, algorithm, new Uint8Array()),
      error => error.name === 'TypeError');
  }
  if (typeof SharedArrayBuffer === 'function') {
    await assert.rejects(digest(context, 'SHA-256', new Uint8Array(new SharedArrayBuffer(3))),
      error => error.name === 'TypeError');
  }
  const noDOMException = sandbox();
  delete noDOMException.DOMException;
  install(noDOMException);
  await assert.rejects(digest(noDOMException, 'SHA-1', new Uint8Array()),
    error => error.name === 'NotSupportedError');
""")

    def test_preserves_native_crypto_and_is_idempotent(self):
        self.run_node(r"""
  const originalDigest = webcrypto.subtle.digest;
  const context = install(sandbox(webcrypto));
  assert.equal(context.crypto, webcrypto);
  assert.equal(context.crypto.subtle.digest, originalDigest);
  assert.equal(await textHash(context, 'abc'),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  install(context);
  assert.equal(context.crypto.subtle.digest, originalDigest);
  const fallback = install(sandbox());
  const fallbackDigest = fallback.crypto.subtle.digest;
  install(fallback);
  assert.equal(fallback.crypto.subtle.digest, fallbackDigest);
""")

    def test_adds_only_digest_and_keeps_browser_crypto_getter(self):
        self.run_node(r"""
  const existingSubtle = {encrypt: () => 'original'};
  const random = () => 'native-random';
  const existingCrypto = {subtle: existingSubtle, getRandomValues: random};
  const context = sandbox();
  Object.defineProperty(context, 'crypto', {get: () => existingCrypto, configurable: false});
  install(context);
  assert.equal(context.crypto, existingCrypto);
  assert.equal(context.crypto.subtle, existingSubtle);
  assert.equal(context.crypto.getRandomValues, random);
  assert.equal(context.crypto.subtle.encrypt(), 'original');
  assert.deepEqual(Object.keys(context.crypto).sort(), ['getRandomValues', 'subtle']);
  assert.equal(context.isSecureContext, false);
  const missing = sandbox();
  delete missing.crypto;
  install(missing);
  assert.equal(await textHash(missing, 'abc'),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.equal(missing.crypto.getRandomValues, undefined);
  assert.equal(missing.crypto.subtle.encrypt, undefined);
  assert.equal(missing.isSecureContext, false);
  const browserCrypto = Object.create({get subtle() { return undefined; }});
  browserCrypto.getRandomValues = random;
  const browser = install(sandbox(browserCrypto));
  assert.equal(browser.crypto.getRandomValues, random);
  assert.equal(await textHash(browser, 'abc'),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
""")


if __name__ == "__main__":
    unittest.main()
