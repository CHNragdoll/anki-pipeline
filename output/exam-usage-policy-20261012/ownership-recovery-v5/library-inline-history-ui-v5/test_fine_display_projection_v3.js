'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const { JSDOM, requestInterceptor } = require('jsdom');
const own = __dirname, repo = path.resolve(own, '../../../..');
const jsPath = path.join(own, 'fine-display-projection-runtime-v3.js');
const runtime = fs.readFileSync(jsPath, 'utf8');
const basePath = path.join(repo, 'anki_pipeline/templates/card-chunks.js');
const base = fs.readFileSync(basePath, 'utf8'), whole = fs.readFileSync(path.join(own, 'chunk-fine-only-runtime.js'), 'utf8');
const sfPath = path.join(repo, 'anki_pipeline/templates/sense-frequency.js'), sfBase = fs.readFileSync(sfPath, 'utf8');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
assert.equal(hash(base), '0bfb570bbb082ac4967cd4d9d4bb184844f26e3144ea707551cdccbd8cf2e8fb');
assert.equal(hash(whole), '3431f1db7de02878f82a64a7495fd971b4d6ad8c698ab39a6b804ab80f485c16');
assert.equal(hash(sfBase), '599a74627d6f3ca6a3189deaca71c84281846790f19e328ca45ffd07bf223c47');
const pin = JSON.parse(fs.readFileSync(path.join(own, 'test-source-pins.json'))).card;
const raw = fs.readFileSync(pin.file); assert.equal(hash(raw), pin.sha256);
const sourceDoc = new JSDOM(raw.toString()).window.document;
const actual = Array.from(sourceDoc.querySelectorAll('li.example-card')).filter(li => li.querySelector('.example-text')?.textContent === 'According to Ortiz, AI companies are advised to adopt a different strategy for AI model training.');
assert.equal(actual.length, 1); const real = actual[0].outerHTML;
const q34Bytes = fs.readFileSync(path.join(own, 'projection-q34d-reviewed-fixture.json'));
const q34 = JSON.parse(q34Bytes);
for (const sourcePin of Object.values(q34.pins)) assert.equal(hash(fs.readFileSync(sourcePin.file)), sourcePin.sha256);
const tests = [];
function test(name, callback) { tests.push([name, callback]); }
const clone = value => JSON.parse(JSON.stringify(value));
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const span = (side, ids, text, wholeIds) => '<span class="card-chunk" data-chunk-side="' + side + '" data-chunk-ids="' + ids + '"' + (wholeIds === undefined ? '' : ' data-chunk-sentence-ids="' + wholeIds + '"') + '>' + text + '</span>';
function html(en, zh, extra = '', sf = false) { return sf ? '<div class="sf-sentence-pair example-card"><p class="sf-en">' + en + '</p><p class="sf-zh">' + zh + '</p>' + extra + '</div>' : '<li class="example-card"><div class="example-heading"><div class="example-text">' + en + '</div></div><p class="example-translation">' + zh + '</p>' + extra + '</li>'; }
function source(en, zh, er, zr) { return { english: en, translation: zh, english_hash: hash(en), translation_hash: hash(zh), chunk: { en: er, zh: zr, relation: 'equivalent' }, chunk_english: Array.from(en).slice(...er).join(''), chunk_chinese: zr.map(r => Array.from(zh).slice(...r).join('')), refs: [{ sentence_id: 'fixture:original:0', source_hash: hash(en), reviewed_content_hash: hash('fixture reviewed') }] }; }
function record(en, zh, chunks) {
  const eh = hash(en), ch = hash(zh);
  return { display_id: hash(JSON.stringify([eh, ch])), english: en, translation: zh, english_hash: eh, translation_hash: ch, chunks: chunks.map((c, n) => ({ mapping_id: hash('mapping-' + en + '-' + n), en: c.en, zh: c.zh, reason: c.reason || 'Fixture reviewed exact bilingual alignment', source: c.source || source(en, zh, c.en, c.zh) })), unmapped: [], source_comparisons: [] };
}
const bundle = records => ({ schema: 'derived-chunk-display-projection.v1', records, pins: { fixture: true } });
function comparison(r, item) {
  const s = item.source;
  return { source_id: hash(JSON.stringify([s.english_hash, s.translation_hash])), english: s.english, translation: s.translation, english_hash: s.english_hash, translation_hash: s.translation_hash,
    pins: { english_hash: s.english_hash, translation_hash: s.translation_hash, index_files: { 'fixture/index.json': hash('fixture') } },
    chunks: [{ mapping_id: item.mapping_id, en: s.chunk.en, zh: s.chunk.zh, en_fragment: s.chunk_english, zh_fragments: s.chunk_chinese, relation: 'equivalent', source_refs: s.refs, reason: item.reason }], original_losses: [{ source: s, loss_reason: 'No concept in current Chinese' }], reviewers: ['fixture-reviewer'] };
}
async function settle() { await new Promise(r => setImmediate(r)); await new Promise(r => setImmediate(r)); }
async function setup(content, data, options = {}) {
  const dom = new JSDOM('<html><body><ul>' + content + '</ul><p id="count">本义 7 次</p></body></html>', { runScripts: 'outside-only', url: 'http://localhost:8771/owned-shell.html' });
  const w = dom.window, d = w.document; w.PointerEvent = options.pointer ? w.MouseEvent : undefined;
  Object.defineProperty(w, 'crypto', { value: crypto.webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.eval(base); if (options.sfRuntime) w.eval(sfBase); w.eval(whole); const wholeHandle = w.AnkiFineChunkRuntime.install(d);
  w.eval(options.runtimeOverride || runtime); const token = await w.AnkiReviewedChunkProjection.prepare(data);
  const before = d.querySelector('ul').innerHTML;
  let adds = 0; const add = d.addEventListener.bind(d); d.addEventListener = (...args) => { adds++; return add(...args); };
  const handle = w.AnkiReviewedChunkProjection.install(d, token, options);
  assert.equal(adds, 1, 'one keyboard-only bridge; no duplicated pointer/click/touch delegates');
  assert.equal(w.AnkiReviewedChunkProjection.install(d, token), handle); assert.equal(adds, 1);
  function tap(el) { const e = new w.MouseEvent('click', { bubbles: true, cancelable: true }); el.dispatchEvent(e); return e; }
  function over(el) { el.dispatchEvent(new w.MouseEvent(options.pointer ? 'pointerover' : 'mouseover', { bubbles: true })); }
  const active = (scope = d) => Array.from(scope.querySelectorAll('.card-chunk-active')).map(el => el.textContent);
  return { dom, w, d, token, handle, wholeHandle, before, tap, over, active, close() { handle.dispose(); wholeHandle.dispose(); dom.window.close(); } };
}
function projected(d, text, side = 'en') { return Array.from(d.querySelectorAll('[data-reviewed-chunk-projection][data-chunk-side="' + side + '"]')).find(el => el.textContent === text); }

test('actual Q34D: restored AI model training↔模型训练, numeric ID5, target/u/history/source/audio/text preserved', async () => {
  const h = await setup(real, q34); const root = h.d.querySelector('li.example-card');
  const en = root.querySelector('.example-text'), zh = root.querySelector('.example-translation'), mark = en.querySelector('mark.target-word'), underline = mark.closest('u');
  assert.equal(en.textContent, q34.records[0].english); assert.equal(zh.textContent, '翻译 ' + q34.records[0].translation);
  assert.equal(mark.textContent, 'training'); assert.ok(underline?.classList.contains('cloze-answer'));
  const target = mark.querySelector('[data-reviewed-chunk-projection]'); assert.equal(target.dataset.chunkIds, '5'); assert.ok(target.classList.contains('sf-target-chunk'));
  assert.equal(target.title, 'AI model training ↔ 模型训练');
  assert.ok(Array.from(en.querySelectorAll('[data-chunk-ids=""][data-chunk-sentence-ids]')).every(el => el.title !== '整句对应：已审校双语全文，非词语级对齐'));
  assert.equal(projected(h.d, '模型训练', 'zh').dataset.chunkIds, '5');
  h.over(target); assert.equal(h.active().join(''), 'AI model training模型训练'); assert.ok(h.active().every(t => t !== en.textContent));
  h.tap(target); assert.equal(h.active().join(''), 'AI model training模型训练'); h.tap(target); assert.deepEqual(h.active(), []);
  const beforeDoc = new JSDOM('<ul>' + h.before + '</ul>').window.document;
  for (const selector of ['.sf-ownership-history', '.example-heading a', '.example-heading button', 'audio']) assert.deepEqual(Array.from(root.querySelectorAll(selector), x => x.outerHTML), Array.from(beforeDoc.querySelectorAll(selector), x => x.outerHTML));
  assert.equal(h.d.getElementById('count').textContent, '本义 7 次'); assert.equal(h.handle.stats().mappedChunks, 2); assert.deepEqual(Array.from(h.handle.stats().errors), []);
  h.handle.dispose(); assert.equal(h.d.querySelector('ul').innerHTML, h.before); h.wholeHandle.dispose(); assert.equal(root.outerHTML, real); h.dom.window.close();
});
test('native/SF exact double copies restore independently and do not cross-activate', async () => {
  const r = q34.records[0], sf = html(escape(r.english.slice(0, 88)) + '<mark class="sfwordhit">' + escape(r.english.slice(88, 96)) + '</mark>.', escape(r.translation), '', true);
  const h = await setup(real + sf, q34); assert.equal(h.handle.stats().exactPairs, 2);
  const roots = h.d.querySelectorAll('li.example-card,.sf-sentence-pair.example-card');
  const second = roots[roots.length - 1]; h.tap(projected(second, 'training')); assert.ok(second.querySelector('.card-chunk-active')); assert.equal(roots[0].querySelector('.card-chunk-active'), null);
  assert.equal(second.querySelector('.sf-en').textContent, r.english); h.close();
});
test('repeated English and Chinese fragments use supplied offsets, never first-word search', async () => {
  const r = record('one one', '一一', [{ en: [4, 7], zh: [[1, 2]] }]);
  const h = await setup(html('one <mark class="target-word">one</mark>', '一一'), bundle([r]));
  assert.equal(h.d.querySelector('.example-text').firstChild.data, 'one '); assert.equal(h.d.querySelector('.example-translation').firstChild.data, '一');
  h.tap(projected(h.d, 'one')); assert.deepEqual(h.active(), ['one', '一']); h.close();
});
test('Unicode astral offsets are codepoints converted to UTF16, preserving surrogate pairs', async () => {
  const r = record('😀x😀z', '甲😀乙😀', [{ en: [2, 4], zh: [[2, 4]] }]);
  const h = await setup(html('😀x<mark class="target-word">😀z</mark>', '甲😀乙😀'), bundle([r]));
  assert.equal(projected(h.d, '😀z').textContent, '😀z'); assert.equal(projected(h.d, '乙😀', 'zh').textContent, '乙😀'); h.tap(projected(h.d, '😀z')); assert.deepEqual(h.active(), ['😀z', '乙😀']); h.close();
});
test('disjoint Chinese ranges activate both exact reviewed fragments without intervening text', async () => {
  const r = record('fine', '甲间乙', [{ en: [0, 4], zh: [[0, 1], [2, 3]] }]); const h = await setup(html('<mark class="target-word">fine</mark>', '甲间乙'), bundle([r]));
  h.tap(projected(h.d, 'fine')); assert.deepEqual(h.active(), ['fine', '甲', '乙']); assert.equal(h.d.querySelector('.example-translation').textContent, '甲间乙'); h.close();
});
test('nested mark/u/em/strong nodes retain identity/attrs and exact reversibility', async () => {
  const r = record('ABCD', '甲乙', [{ en: [0, 4], zh: [[0, 2]] }]);
  const h = await setup(html('<u class="cloze-answer"><em>A</em><mark class="target-word" data-proof="keep"><strong>BC</strong></mark>D</u>', '<em>甲</em><strong>乙</strong>'), bundle([r]));
  const nodes = Array.from(h.d.querySelectorAll('u,mark,em,strong')); h.handle.refresh(); assert.deepEqual(Array.from(h.d.querySelectorAll('u,mark,em,strong')), nodes);
  assert.equal(h.d.querySelector('mark').getAttribute('data-proof'), 'keep'); assert.equal(h.d.querySelector('.example-text').textContent, 'ABCD');
  h.handle.dispose(); assert.equal(h.d.querySelector('ul').innerHTML, h.before); h.close();
});
test('existing fine IDs and source byte content stay intact; finer restored inner chunk has activation priority', async () => {
  const r = record('broad fine', '宽细', [{ en: [6, 10], zh: [[1, 2]] }]);
  const h = await setup(html(span('en', '2', 'broad <mark class="target-word">fine</mark>'), span('zh', '2', '宽细')), bundle([r]));
  const outer = h.d.querySelector('.example-text > .card-chunk'); assert.equal(outer.dataset.chunkIds, '2');
  const fine = projected(h.d, 'fine'); assert.equal(fine.dataset.chunkIds, '3 2'); assert.equal(outer.classList.contains('sf-target-chunk'), false);
  h.tap(fine); assert.deepEqual(h.active(), ['fine', '细']); h.close();
});
test('fine+whole max includes filtered whole ID and whole never regains ordinary interaction', async () => {
  const r = record('old new', '原新', [{ en: [4, 7], zh: [[1, 2]] }]);
  const h = await setup(html(span('en', '0 9', 'old ', '9') + span('en', '9', '<mark class="target-word">new</mark>', '9'), span('zh', '0 9', '原', '9') + span('zh', '9', '新', '9')), bundle([r]));
  assert.equal(projected(h.d, 'new').dataset.chunkIds, '10'); h.tap(projected(h.d, 'new')); assert.deepEqual(h.active(), ['new', '新']);
  assert.ok(Array.from(h.d.querySelectorAll('[data-chunk-ids]')).every(el => !el.dataset.chunkIds.split(' ').includes('9'))); h.close();
});
test('pure fine and legacy singleton stay interactive without treating them as whole', async () => {
  const r = record('old new', '原新', [{ en: [4, 7], zh: [[1, 2]] }]);
  const h = await setup(html(span('en', '0', 'old ') + '<mark class="target-word">new</mark>', span('zh', '0', '原') + '新'), bundle([r]));
  h.tap(h.d.querySelector('.example-text > .card-chunk')); assert.deepEqual(h.active(), ['old ', '原']); h.tap(projected(h.d, 'new')); assert.deepEqual(h.active(), ['new', '新']); h.close();
});
test('Chinese reverse, touch-style click, Enter/Space and Escape use existing delegates once', async () => {
  const r = record('fine', '细块', [{ en: [0, 4], zh: [[0, 2]] }]); const h = await setup(html('<mark class="target-word">fine</mark>', '细块', '<a id="source" href="/paper">原卷</a><button id="audio">发音</button>'), bundle([r]));
  const zh = projected(h.d, '细块', 'zh'); h.tap(zh); assert.deepEqual(h.active(), ['fine', '细块']); h.tap(zh); assert.deepEqual(h.active(), []);
  const en = projected(h.d, 'fine'); en.focus(); assert.equal(h.d.activeElement, en);
  let e = new h.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }); en.dispatchEvent(e); assert.ok(e.defaultPrevented); assert.deepEqual(h.active(), ['fine', '细块']);
  en.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })); assert.deepEqual(h.active(), []);
  h.tap(en); h.d.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); assert.deepEqual(h.active(), []);
  assert.equal(h.tap(h.d.getElementById('source')).defaultPrevented, false); e = new h.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }); h.d.getElementById('audio').dispatchEvent(e); assert.equal(e.defaultPrevented, false); h.close();
});
test('pointer path uses frozen delegate, no input rebinding at refresh', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]); const h = await setup(html('fine', '细'), bundle([r]), { pointer: true });
  h.over(projected(h.d, 'fine')); assert.deepEqual(h.active(), ['fine', '细']); for (let n = 0; n < 3; n++) h.handle.refresh(); assert.equal(h.d.querySelectorAll('[data-reviewed-chunk-projection]').length, 2); h.close();
});
test('exact native 翻译 plus one spacer supported; newline/NBSP/extra whitespace never normalized', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]);
  const h = await setup(html('fine', '<span class="translate-tag">翻译</span> 细') + html('fine', '<span class="translate-tag">翻译</span>  细') + html('fine', '<span class="translate-tag">翻译</span>\n细') + html('fine', '<span class="translate-tag">翻译</span>\u00a0细'), bundle([r]));
  assert.equal(h.handle.stats().exactPairs, 1); assert.equal(h.d.querySelectorAll('[data-reviewed-chunk-projection]').length, 2); h.close();
});
test('same English with different Chinese, different English or leading space stays unmodified', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]); const h = await setup(html('fine', '错') + html(' fine', '细') + html('finer', '细'), bundle([r]));
  assert.equal(h.handle.stats().exactPairs, 0); assert.equal(h.d.querySelector('ul').innerHTML, h.before); h.close();
});
test('unmapped and original ____ only appear in collapsed sentence-local exact source comparison', async () => {
  const r = record('completed sentence', '当前译文', []); const s = source('____ fine', '原细块', [5, 9], [[1, 3]]);
  const item = { mapping_id: hash('unmapped'), display_id: r.display_id, status: 'unmapped', en: null, zh: null, en_fragment: null, zh_fragments: null, reason: '原细块概念在当前译文缺失，保留原译依据。', source: s, reviewer: 'fixture', classification: 'blocked' };
  r.unmapped.push(item); r.source_comparisons.push(comparison(r, item));
  const h = await setup(html('<mark class="target-word">completed</mark> sentence', '当前译文'), bundle([r]));
  const detail = h.d.querySelector('[data-reviewed-source-comparison]'); assert.ok(detail); assert.equal(detail.open, false); assert.equal(detail.parentNode, h.d.querySelector('li'));
  assert.equal(detail.querySelector('summary').textContent, '原译分块对照'); assert.equal(detail.querySelector('.sf-en').textContent, '____ fine'); assert.equal(detail.querySelector('.sf-zh').textContent, '原细块');
  assert.equal(h.d.querySelector('.example-text').textContent, r.english); assert.equal(h.d.querySelector('.example-translation').textContent, r.translation); assert.equal(h.d.querySelector('.example-text [data-reviewed-chunk-projection]'), null);
  detail.open = true; h.tap(projected(detail, 'fine')); assert.deepEqual(h.active(detail), ['fine', '细块']); assert.equal(h.d.getElementById('count').textContent, '本义 7 次');
  assert.ok(detail.querySelector('pre').textContent.includes('original_losses')); h.handle.refresh(); assert.equal(h.d.querySelectorAll('[data-reviewed-source-comparison]').length, 1); h.close();
});
test('mapped reading-difference comparison retains source text and full old reason too', async () => {
  const s = source('study', '研究', [0, 5], [[0, 2]]), r = record('study', '学习', [{ en: [0, 5], zh: [[0, 2]], source: s, reason: '当前读法学习，原译研究单独保留。' }]);
  r.source_comparisons.push(comparison(r, r.chunks[0])); const h = await setup(html('<mark class="target-word">study</mark>', '学习'), bundle([r]));
  assert.equal(h.d.querySelector('.example-translation').textContent, '学习'); const detail = h.d.querySelector('details'); assert.equal(detail.querySelector('.sf-zh').textContent, '研究'); assert.equal(detail.querySelector('mark.target-word').textContent, 'study'); assert.equal(detail.querySelector('.sf-zh .sf-target-chunk').textContent, '研究'); h.close();
});
test('current and nested original comparisons reserve distinct numeric IDs, preventing hidden-source activation', async () => {
  const r = record('current', '当前', []), s = source('original', '原译', [0, 8], [[0, 2]]);
  const item = { mapping_id: hash('comparison-id-isolation'), status: 'unmapped', en: null, zh: null, en_fragment: null, zh_fragments: null, reason: '原译独立保留', source: s };
  r.unmapped.push(item); r.source_comparisons.push(comparison(r, item));
  const h = await setup(html(span('en', '0', '<mark class="target-word">current</mark>'), span('zh', '0', '当前')), bundle([r]));
  h.tap(h.d.querySelector('.example-text .card-chunk')); assert.deepEqual(h.active(), ['current', '当前']); const detail = h.d.querySelector('details'); assert.equal(detail.querySelector('.card-chunk').dataset.chunkIds, '1'); assert.equal(detail.querySelector('.card-chunk-active'), null);
  h.tap(projected(detail, 'original')); assert.deepEqual(h.active(), ['original', '原译']); h.close();
});
test('archive/history roots and malicious source strings are inert text, never executed', async () => {
  const en = '<img src=x onerror=window.pwned=1>', zh = '<script>window.pwned=2</script>', s = source(en, zh, [0, en.length], [[0, zh.length]]);
  const r = record('current', '当前', []), item = { mapping_id: hash('malicioustext'), status: 'unmapped', en: null, zh: null, en_fragment: null, zh_fragments: null, source: s, reason: '<iframe src="https://evil.invalid">', reviewer: 'fixture' };
  r.unmapped.push(item); r.source_comparisons.push(comparison(r, item));
  const history = '<details class="sf-ownership-history"><summary>本句归属</summary>' + html('current', '当前') + '</details>';
  const h = await setup(html('current', '当前', history), bundle([r])); assert.equal(h.w.pwned, undefined); assert.equal(h.d.querySelectorAll('img,iframe,script').length, 0); assert.equal(h.d.querySelector('.sf-ownership-history').outerHTML, new JSDOM(history).window.document.querySelector('details').outerHTML); h.close();
});
test('projection validation rejects wrong hashes/boundaries/duplicate IDs and missing comparison', async () => {
  const h = await setup('', bundle([]));
  for (const mutate of [b => b.records[0].english_hash = hash('wrong'), b => b.records[0].display_id = hash('wrong'), b => b.records[0].chunks[0].en = [0, 2], b => b.records[0].chunks[0].source.chunk_english = 'wrong', b => b.records.push(clone(b.records[0])), b => b.records[0].chunks.push(clone(b.records[0].chunks[0])), b => b.records[0].chunks[0].zh = [[0, 1], [0, 1]]]) {
    const b = bundle([record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }])]); mutate(b); await assert.rejects(h.w.AnkiReviewedChunkProjection.prepare(b));
  }
  const r = record('fine', '细', []); r.unmapped.push({ mapping_id: hash('no-compare'), status: 'unmapped', en: null, zh: null, en_fragment: null, zh_fragments: null, reason: 'unmapped', source: source('fine', '旧', [0, 4], [[0, 1]]) }); await assert.rejects(h.w.AnkiReviewedChunkProjection.prepare(bundle([r])), /comparison missing/); h.close();
});
test('validated token snapshots data and cannot be bypassed by raw object or later mutation', async () => {
  const data = bundle([record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }])]); const h = await setup(html('fine', '细'), data);
  data.records[0].chunks[0].en = [0, 1]; data.records[0].translation = '坏'; h.handle.refresh(); assert.equal(projected(h.d, 'fine').textContent, 'fine');
  assert.throws(() => h.w.AnkiReviewedChunkProjection.install(h.d, data), /validated token/); assert.ok(Object.isFrozen(h.token)); h.close();
});
test('lazy load checks exact file bytes, same-origin exact route, redirects, UTF8 and AbortSignal', async () => {
  const h = await setup('', bundle([])), bytes = Buffer.from(JSON.stringify(q34)), url = 'http://localhost:8771/output/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json';
  let calls = 0; h.w.fetch = async (requested, opts) => { calls++; assert.equal(requested, url); assert.equal(opts.redirect, 'error'); assert.equal(opts.credentials, 'same-origin'); return { ok: true, url, redirected: false, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) }; };
  const loaded = await h.w.AnkiReviewedChunkProjection.load({ url, sha256: hash(bytes) }); assert.equal(loaded.records, 1);
  await assert.rejects(h.w.AnkiReviewedChunkProjection.load({ url, sha256: hash('wrong') }), /hash mismatch/);
  for (const bad of [url.replace('localhost:8771', 'evil.invalid'), url + '?cache=1', url.replace('projection.json', 'other.json'), url.replace('http://', 'file://')]) await assert.rejects(h.w.AnkiReviewedChunkProjection.load({ url: bad, sha256: hash(bytes) }), /route/);
  assert.equal(calls, 2); h.w.fetch = async () => ({ ok: true, url: 'http://evil.invalid/projection.json', redirected: true }); await assert.rejects(h.w.AnkiReviewedChunkProjection.load({ url, sha256: hash(bytes) }), /response/);
  const controller = new AbortController(); controller.abort(); h.w.fetch = async () => ({ ok: true, url, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) }); await assert.rejects(h.w.AnkiReviewedChunkProjection.load({ url, sha256: hash(bytes) }, { signal: controller.signal }), /aborted/); h.close();
});
test('unavailable WebCrypto fails closed, never displays unchecked JSON', async () => {
  const h = await setup('', bundle([])); Object.defineProperty(h.w, 'crypto', { value: {} }); await assert.rejects(h.w.AnkiReviewedChunkProjection.prepare(q34), /integrity is mandatory/); h.close();
});
test('new AJAX pairs install once, disposed/queued observer never modifies next card', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]); let current = true; const h = await setup('', bundle([r]), { isCurrent: () => current });
  const holder = h.d.createElement('div'); holder.innerHTML = html('fine', '细'); h.d.body.append(holder); await settle(); assert.equal(h.handle.stats().exactPairs, 1);
  const count = holder.querySelectorAll('[data-reviewed-chunk-projection]').length; h.handle.refresh(); assert.equal(holder.querySelectorAll('[data-reviewed-chunk-projection]').length, count);
  current = false; const next = h.d.createElement('div'); next.innerHTML = html('fine', '细'); h.d.body.append(next); h.handle.dispose(); await settle(); assert.equal(next.querySelector('[data-reviewed-chunk-projection]'), null); assert.equal(holder.querySelector('[data-reviewed-chunk-projection]'), null); h.close();
});
test('dispose/reinstall exact reversal and external text edits preserved', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]); const h = await setup(html('fine', '细'), bundle([r]));
  h.handle.dispose(); assert.equal(h.d.querySelector('ul').innerHTML, h.before); const again = h.w.AnkiReviewedChunkProjection.install(h.d, h.token);
  projected(h.d, 'fine').firstChild.data = 'user edit'; again.dispose(); assert.equal(h.d.querySelector('.example-text').textContent, 'user edit'); assert.equal(h.d.querySelector('[data-reviewed-chunk-projection]'), null); h.close();
});
test('parent installs in same-origin child frame and leaves child delegates/mark untouched', async () => {
  const parent = new JSDOM('<iframe></iframe>', { runScripts: 'outside-only', url: 'http://localhost:8771/shell.html' }), w = parent.window, frame = w.document.querySelector('iframe');
  Object.defineProperty(w, 'crypto', { value: crypto.webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  const d = frame.contentDocument, child = frame.contentWindow; d.body.innerHTML = html('<mark class="target-word">fine</mark>', '细'); child.PointerEvent = undefined; child.eval(base); w.eval(whole); w.eval(runtime); const wholeHandle = w.AnkiFineChunkRuntime.install(d);
  const token = await w.AnkiReviewedChunkProjection.prepare(bundle([record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }])])); const handle = w.AnkiReviewedChunkProjection.install(d, token);
  projected(d, 'fine').dispatchEvent(new child.MouseEvent('click', { bubbles: true, cancelable: true })); assert.equal(d.querySelectorAll('.card-chunk-active').length, 2); assert.equal(child.__ankiCardChunksBound, true); assert.equal(w.__ankiCardChunksBound, undefined); handle.dispose(); wholeHandle.dispose(); parent.window.close();
});
test('actual generic Q34D page loads all pinned scripts and reviewed JSON before ready; restored pair interactive', async () => {
  const prefix = 'http://localhost:8771/anki_rebuild/', pageURL = prefix + path.relative(repo, path.join(own, 'projection-q34d-preview-v2.html'));
  const allowed = new Map([path.join(own, 'projection-card-chunks-base.js'), path.join(own, 'chunk-fine-only-runtime.js'), jsPath, path.join(own, 'projection-q34d-preview-v2.js')].map(file => [prefix + path.relative(repo, file), file]));
  const requests = [], errors = [];
  const dom = new JSDOM(fs.readFileSync(path.join(own, 'projection-q34d-preview-v2.html'), 'utf8').replace('fine-display-projection-runtime-v2.js','fine-display-projection-runtime-v3.js'), { url: pageURL, runScripts: 'dangerously',
    resources: { interceptors: [requestInterceptor(request => { requests.push(request.url); if (!allowed.has(request.url)) throw new Error('Unexpected resource ' + request.url); return new Response(fs.readFileSync(allowed.get(request.url)), { headers: { 'content-type': 'application/javascript' } }); })] },
    beforeParse(w) { Object.defineProperty(w, 'crypto', { value: crypto.webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder; w.PointerEvent = undefined;
      w.addEventListener('error', event => errors.push(event.message));
      w.fetch = async url => { const expected = prefix + path.relative(repo, path.join(own, 'projection-q34d-reviewed-fixture.json')); assert.equal(url, expected); return { ok: true, url, redirected: false, arrayBuffer: async () => q34Bytes.buffer.slice(q34Bytes.byteOffset, q34Bytes.byteOffset + q34Bytes.length) }; };
    }
  });
  for (let n = 0; n < 100 && !dom.window.document.querySelector('#projection-status').dataset.state; n++) await new Promise(r => setTimeout(r, 10));
  assert.deepEqual(errors, []); const d = dom.window.document, w = dom.window; assert.equal(d.getElementById('projection-status').dataset.state, 'ready'); assert.equal(requests.length, 4);
  const target = d.querySelector('.example-text mark.target-word [data-reviewed-chunk-projection]'); assert.equal(target.dataset.chunkIds, '5'); target.dispatchEvent(new w.MouseEvent('click', { bubbles: true, cancelable: true }));
  assert.equal(Array.from(d.querySelectorAll('.example-text .card-chunk-active,.example-translation .card-chunk-active'), el => el.textContent).join(''), 'AI model training模型训练');
  w.__reviewedProjectionPreview.projection.dispose(); w.__reviewedProjectionPreview.whole.dispose(); dom.window.close();
});
test('final merged 10MB candidate validates 2375 exact pairs/4011 mappings/72 unmapped, then restores actual Q34D', async () => {
  const file = path.join(repo, 'output/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json');
  const bytes = fs.readFileSync(file); assert.equal(hash(bytes), 'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8');
  const h = await setup('', bundle([])); const started = performance.now();
  const token = await h.w.AnkiReviewedChunkProjection.prepare(JSON.parse(bytes.toString())); assert.equal(token.records, 2375); assert.equal(token.mappings, 4011); assert.equal(token.unmapped, 72);
  h.handle.dispose(); h.d.querySelector('ul').innerHTML = real; h.wholeHandle.refresh();
  const applied = h.w.AnkiReviewedChunkProjection.install(h.d, token); assert.equal(applied.stats().exactPairs, 1); assert.equal(applied.stats().mappedChunks, 2); assert.deepEqual(Array.from(applied.stats().errors), []);
  const target = h.d.querySelector('.example-text mark.target-word [data-reviewed-chunk-projection]'); assert.equal(target.dataset.chunkIds, '5'); h.tap(target); assert.equal(h.active().join(''), 'AI model training模型训练');
  applied.dispose(); h.close(); process.stderr.write('merged candidate validate+Q34D ' + Math.round(performance.now() - started) + 'ms, ' + bytes.length + ' bytes\n');
});
test('exact whole-only tooltip removed only for bound pair; fine/custom/unmatched titles preserved and disposal restores', async () => {
  const r = record('fine', '细', [{ en: [0, 4], zh: [[0, 1]] }]);
  const title = '整句对应：已审校双语全文，非词语级对齐';
  const source = html(span('en', '7', '<mark class="target-word">fine</mark>', '7').replace('class="card-chunk"', 'class="card-chunk" title="' + title + '"'), span('zh', '7', '细', '7').replace('class="card-chunk"', 'class="card-chunk" title="custom"'));
  const unmatched = html(span('en', '7', 'other', '7').replace('class="card-chunk"', 'class="card-chunk" title="' + title + '"'), '错');
  const h = await setup(source + unmatched, bundle([r]));
  const en = h.d.querySelector('.example-text > [data-chunk-sentence-ids]'); assert.equal(en.hasAttribute('title'), false); assert.equal(h.d.querySelector('.example-translation > [data-chunk-sentence-ids]').title, 'custom');
  assert.equal(h.d.querySelectorAll('.example-text')[1].querySelector('[data-chunk-sentence-ids]').title, title);
  assert.equal(projected(h.d, 'fine').title, 'fine ↔ 细'); h.handle.dispose(); assert.equal(en.title, title); h.close();
});
test('actual Q34D SF and actual sense-frequency capture listener reproduce v2 gap; v3 Enter/Space work once and symmetric capture cleanup preserves flip', async () => {
  const actualSF = Array.from(sourceDoc.querySelectorAll('.sf-sentence-pair')).filter(pair => pair.querySelector('.sf-en')?.textContent === q34.records[0].english && pair.querySelector('.sf-zh')?.textContent === q34.records[0].translation);
  assert.equal(actualSF.length, 3, 'actual repeated SF Q34D copies must remain present');
  const content = '<section class="sf-report">' + actualSF[0].outerHTML + '</section>';
  const old = await setup(content, q34, { sfRuntime: true, runtimeOverride: fs.readFileSync(path.join(own, 'fine-display-projection-runtime-v2.js'), 'utf8') });
  let target = old.d.querySelector('mark.target-word [data-reviewed-chunk-projection]');
  target.dispatchEvent(new old.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); assert.deepEqual(old.active(), [], 'v2 real capture listener suppresses bubble bridge');
  target.dispatchEvent(new old.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })); assert.deepEqual(old.active(), [], 'v2 Space gap is reproduced'); old.close();
  const h = await setup(content + real, q34, { sfRuntime: true }); let clicks = 0, flips = 0, removed = [];
  h.d.addEventListener('click', () => clicks++, true);
  h.d.addEventListener('keydown', event => { if (event.key === ' ' && !event.defaultPrevented) flips++; });
  const remove = h.d.removeEventListener.bind(h.d); h.d.removeEventListener = (type, callback, capture) => { if (type === 'keydown') removed.push(capture); return remove(type, callback, capture); };
  target = h.d.querySelector('.sf-report mark.target-word [data-reviewed-chunk-projection]'); target.focus(); assert.equal(h.d.activeElement, target);
  let event = new h.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }); target.dispatchEvent(event); assert.equal(event.defaultPrevented, true);
  assert.equal(h.active().join(''), 'AI model training模型训练'); assert.equal(clicks, 1);
  event = new h.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }); target.dispatchEvent(event); assert.equal(event.defaultPrevented, true); assert.deepEqual(h.active(), []); assert.equal(clicks, 2); assert.equal(flips, 0);
  const native = h.d.querySelector('li.example-card mark.target-word [data-reviewed-chunk-projection]'); native.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })); assert.equal(clicks, 3); assert.equal(flips, 0, 'native capture bridge prevents library-style Space flip too');
  native.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); assert.deepEqual(h.active(), []);
  target.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); assert.equal(clicks, 4);
  target.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); assert.deepEqual(h.active(), []);
  h.handle.dispose(); assert.deepEqual(removed, [true], 'capture listener removed with matching capture flag'); assert.equal(h.d.querySelector('ul').innerHTML, h.before); h.close();
});

(async () => {
  const results = [];
  for (const [name, run] of tests) { try { await run(); results.push({ name, passed: true }); } catch (error) { results.push({ name, passed: false, error: error.stack }); } }
  process.stdout.write(JSON.stringify({ schema: 'reviewed-fine-display-projection-checks.v3', tests: results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length, runtime: { file: jsPath, sha256: hash(runtime) }, base_chunk_js: { file: basePath, sha256: hash(base) }, actual_sense_frequency_js:{file:sfPath,sha256:hash(sfBase)}, accepted_whole_filter_sha256: hash(whole), actual_q34d_card: pin, reviewed_q34d_fixture_sha256: hash(q34Bytes), actual_browser_accepted: false, production_applied: false, final_merged_projection_validated: false }, null, 2) + '\n');
  process.exitCode = results.some(r => !r.passed) ? 1 : 0;
})();
