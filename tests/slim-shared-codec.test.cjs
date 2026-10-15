const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.resolve(__dirname, '../anki_pipeline/templates/slim-shared-codec.js'), 'utf8');
const dictionarySchema = 'anki-slim-shared-dictionary.v1';
const sha = raw => crypto.createHash('sha256').update(raw).digest('hex');
function fixture() {
  const context = vm.createContext({});
  context.window = context;
  vm.runInContext(source, context);
  return context.AnkiSlimPackedDecode;
}
function info(raw) { const hash = sha(raw); return { src: '_as_' + hash.slice(0, 24) + '.js', sha256: hash }; }
function dictionary(strings) { return JSON.stringify({ schema: dictionarySchema, strings }); }
function packed(raw, pieces) { return { schema: 'anki-slim-shared-strings.v1', dict: info(raw), pieces }; }

test('exact Chinese, Unicode, whitespace and escaped JSON restore as inert original text', async () => {
  const decode = fixture();
  const strings = ['<p class="sf-en">', '目标词 👍 e\u0301', '</p>', '"escaped\\\"quote"'];
  const raw = dictionary(strings);
  const value = packed(raw, [0, '\r\n  ', 1, 2, '\\', 3]);
  const result = await decode(value, async reference => { assert.deepEqual(reference, info(raw)); return raw; });
  assert.equal(result, strings[0] + '\r\n  ' + strings[1] + strings[2] + '\\' + strings[3]);
  assert.equal(sha(result), sha(strings[0] + '\r\n  ' + strings[1] + strings[2] + '\\' + strings[3]));
});

test('strict dictionary schema, strings and JSON loader types are checked', async () => {
  for (const raw of ['not json', '[]', 'null', '{"schema":"other","strings":[]}',
    '{"schema":"anki-slim-shared-dictionary.v1","strings":[1]}',
    '{"schema":"anki-slim-shared-dictionary.v1","strings":[null]}',
    '{"schema":"anki-slim-shared-dictionary.v1","strings":{}}']) {
    await assert.rejects(fixture()(packed(raw, []), async () => raw), /dictionary/);
  }
  await assert.rejects(fixture()(packed(dictionary([]), []), async () => ({ strings: [] })), /original JSON string/);
});

test('boolean, floating, extreme, negative and nested pieces are never coerced', async () => {
  const raw = dictionary(['valid']);
  for (const bad of [true, false, null, 1.5, -1, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, {}, [], undefined]) {
    let calls = 0;
    await assert.rejects(fixture()(packed(raw, [bad]), async () => { calls++; return raw; }), /piece/);
    assert.equal(calls, 0, 'bad piece types are rejected before local I/O');
  }
  await assert.rejects(fixture()(packed(raw, Array(2)), async () => raw), /piece/);
  for (const index of [1, Number.MAX_SAFE_INTEGER]) {
    await assert.rejects(fixture()(packed(raw, [index]), async () => raw), /out of bounds/);
  }
});

test('remote, traversal and mismatched local dictionary references never reach loader', async () => {
  const raw = dictionary(['valid']);
  for (const change of [{ src: 'http://evil.invalid/x.js' }, { src: '../_as_' + 'a'.repeat(24) + '.js' },
    { src: '_as_' + 'a'.repeat(24) + '.js' }, { sha256: 'nope' }]) {
    let calls = 0;
    const value = packed(raw, [0]); value.dict = { ...value.dict, ...change };
    await assert.rejects(fixture()(value, async () => { calls++; return raw; }), /local dictionary/);
    assert.equal(calls, 0);
  }
});

test('parsed dictionary cache has an LRU bound of two, without changing restored text', async () => {
  const decode = fixture();
  const raws = ['A', 'B', 'C'].map(word => dictionary([word]));
  const calls = [0, 0, 0];
  async function run(n) { return decode(packed(raws[n], [0]), async () => { calls[n]++; return raws[n]; }); }
  assert.equal(await run(0), 'A'); assert.equal(await run(1), 'B'); assert.equal(await run(0), 'A');
  assert.equal(await run(2), 'C'); assert.equal(await run(0), 'A'); assert.equal(await run(1), 'B');
  assert.deepEqual(calls, [1, 2, 1]);
});

test('concurrent loads share a verified dictionary request and failures remain retryable', async () => {
  const decode = fixture(), raw = dictionary(['same source']);
  let calls = 0, resolve;
  const load = () => { calls++; return new Promise(done => { resolve = done; }); };
  const first = decode(packed(raw, [0]), load), second = decode(packed(raw, [0, '!']), load);
  await Promise.resolve(); assert.equal(calls, 1);
  resolve(raw);
  assert.deepEqual(await Promise.all([first, second]), ['same source', 'same source!']);
  const retry = fixture(); let failures = 0;
  const unstable = async () => { if (++failures === 1) throw Error('local file failure'); return raw; };
  await assert.rejects(retry(packed(raw, [0]), unstable), /local file failure/);
  assert.equal(await retry(packed(raw, [0]), unstable), 'same source');
  assert.equal(failures, 2);
});

test('in-flight pieces are snapshotted, and empty text remains empty', async () => {
  const decode = fixture(), raw = dictionary(['initial']);
  let finish;
  const value = packed(raw, [0, ' text']);
  const pending = decode(value, () => new Promise(resolve => { finish = resolve; }));
  value.pieces.splice(0, value.pieces.length, 'replaced');
  await Promise.resolve(); finish(raw);
  assert.equal(await pending, 'initial text');
  assert.equal(await decode(packed(raw, []), async () => raw), '');
});

test('packed top-level schemas and missing loaders are rejected', async () => {
  const decode = fixture(), raw = dictionary([]);
  for (const value of [null, [], {}, { schema: 'other', pieces: [] },
    { schema: 'anki-slim-shared-strings.v1', dict: info(raw), pieces: 'string' }]) {
    await assert.rejects(decode(value, async () => raw), /schema|pieces/);
  }
  await assert.rejects(decode(packed(raw, []), null), /loader/);
});

test('literal dictionary descriptor reaches the parent loader intact for mixed-version coexistence', async () => {
  const decode = fixture(), raw = dictionary(['完整原字符串']);
  const value = packed(raw, [0]);
  value.dict.literal = true;
  assert.equal(await decode(value, async reference => {
    assert.equal(reference.literal, true);
    assert.equal(reference.src, info(raw).src);
    assert.equal(reference.sha256, info(raw).sha256);
    return raw;
  }), '完整原字符串');
});
