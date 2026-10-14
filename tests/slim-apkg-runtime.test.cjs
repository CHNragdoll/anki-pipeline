const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');
const runtime = fs.readFileSync(path.resolve(__dirname, process.env.ANKI_SLIM_RUNTIME || '../anki_pipeline/templates/slim-apkg.js'), 'utf8');
const sha = value => crypto.createHash('sha256').update(value).digest('hex');

function acceptedGroup(window) {
  const accepted = fs.readFileSync(path.resolve(__dirname, '../output/eleven-resolution-20261014/preview-own/final-v2/assets/library-preview.js'), 'utf8');
  const start = accepted.indexOf('/* Presentation only: physical occurrences and all source evidence remain intact. */');
  const end = accepted.indexOf('\n(function () {\n  \'use strict\';\n\n  var ALL_DECKS', start);
  assert.ok(start >= 0 && end > start);
  let helper = accepted.slice(start, end);
  const hook = 'if (disposed) return; var natives = physicalNativeIndex(doc);';
  assert.equal(helper.split(hook).length, 2);
  helper = helper.replace(hook, hook + ' if(window.AnkiSlimPhysicalNativeIndex)window.AnkiSlimPhysicalNativeIndex(doc).forEach(function(values,key){var set=natives.get(key)||new Set();values.forEach(function(value){set.add(value);});natives.set(key,set);});');
  const gate = "doc.querySelectorAll('.sf-sense > .sf-panel').forEach(function (panel) {";
  assert.equal(helper.split(gate).length, 2);
  helper = helper.replace(gate, gate + 'if(window.AnkiSlimPanelReady&&!window.AnkiSlimPanelReady(panel))return;');
  window.eval(helper);
}

function fixture(t, body, { delay = 0, broken = new Set() } = {}) {
  const dom = new JSDOM('<!doctype html><body>' + body + '</body>', { runScripts: 'outside-only', url: 'http://127.0.0.1/' });
  t.after(() => dom.window.close());
  const w = dom.window, doc = w.document;
  w.TextEncoder = TextEncoder;
  Object.defineProperty(w.crypto, 'subtle', { value: crypto.webcrypto.subtle });
  w.AnkiSlimAssets = {};
  const assets = new Map(), calls = { load: [], decode: [], prepare: 0, fine: 0, projected: 0, bank: 0, group: 0, disposed: 0 };
  function part(raw, count = 1) {
    const hash = sha(raw), src = '_as_' + hash.slice(0, 24) + '.js';
    assets.set(src, { hash, raw });
    return { src, sha256: hash, count };
  }
  function manifest(parts, kind) {
    const payload = JSON.stringify({ schema: 'anki-slim-segments.v1', parts, total: parts.reduce((n, p) => n + p.count, 0) });
    return '<' + (kind === 'examples' ? 'li' : 'div') + ' class="as-lazy" data-as-kind="' + kind + '"><script type="application/json" class="as-manifest">' + payload + '</script></' + (kind === 'examples' ? 'li' : 'div') + '>';
  }
  const append = doc.head.append.bind(doc.head);
  doc.head.append = function (...nodes) {
    append(...nodes);
    for (const node of nodes) {
      if (node.tagName !== 'SCRIPT' || !node.src) continue;
      const name = node.getAttribute('src'); calls.load.push(name);
      w.setTimeout(() => {
        const logical = name.replace(/^_ac_/, '_as_');
        const asset = assets.get(name) || assets.get(logical);
        if (!asset || broken.has(name) || broken.has(logical)) { if (node.onerror) node.onerror(); return; }
        w.AnkiSlimAssets[asset.hash] = asset.raw;
        if (node.onload) node.onload();
      }, delay);
    }
  };
  const handle = name => ({ refresh() { calls[name]++; return Promise.resolve(); }, stats() { return { errors: [] }; }, dispose() { calls.disposed++; } });
  w.AnkiFineChunkRuntime = { install() { return handle('fine'); } };
  w.AnkiReviewedChunkProjection = { async prepare(data) { calls.prepare++; return data; }, install() { return handle('projected'); } };
  w.AnkiSharedReadingBankRuntime = { install() { return { ...handle('bank'), ready: Promise.resolve() }; } };
  w.AnkiSameSenseGroupRuntime = { install() { return handle('group'); } };
  w.AnkiResidualReviewedChunkRuntime = { install() { return handle('residual'); } };
  w.AnkiSlimDecode = root => calls.decode.push(root);
  w.AnkiFinalReadingMetadata = {};
  w.eval(fs.readFileSync(path.resolve(__dirname, '../anki_pipeline/templates/slim-shared-codec.js'), 'utf8'));
  w.eval(runtime);
  return { w, doc, calls, assets, part, manifest };
}
const tick = () => new Promise(resolve => setTimeout(resolve, 15));
async function until(check) { for (let i = 0; i < 100; i++) { if (check()) return; await tick(); } assert.fail('runtime condition did not become ready'); }
const payload = '<script type="application/json" class="anki-final-reviewed-data">{}</script>';
function example(n) { return '<li class="example-card"><p class="example-text">word ' + n + '</p><p class="example-translation">译文 ' + n + '</p><a class="sentence-jump" data-latex-url="http://127.0.0.1/latex/' + n + '" data-full-paper-url="http://127.0.0.1/paper/' + n + '">原文</a></li>'; }
function sf(n, year = '2026') { return '<article class="sf-example" data-sf-year="' + year + '"><p class="sf-en">word ' + n + '</p><p class="sf-zh">译文 ' + n + '</p></article>'; }
function scrollAtSentinel(f) {
  f.doc.querySelector('.as-sentinel').getBoundingClientRect = () => ({ top: 100, bottom: 101, height: 1 });
  f.w.dispatchEvent(new f.w.Event('scroll'));
}

test('first paint loads only ten ordinary examples; a closed sense stays local and deferred', async t => {
  const f = fixture(t, payload);
  const parts = [f.part(Array.from({ length: 10 }, (_, n) => example(n)).join(''), 10), f.part(example(10))];
  const sense = f.part(sf(1));
  f.doc.body.insertAdjacentHTML('afterbegin', '<section class="examples-section"><label class="source-reader-setting" hidden><select class="source-reader"><option value="latex">重排</option><option value="full-paper">整卷</option></select></label><ol class="examples">' + f.manifest(parts, 'examples') + '</ol></section><details class="sf-sense"><summary>释义</summary><div class="sf-panel">' + f.manifest([sense], 'sense') + '</div></details>');
  f.w.__ankiExamSourceReader = 'full-paper';
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 10);
  assert.equal(f.doc.querySelectorAll('.sf-example').length, 0);
  assert.equal(f.calls.prepare, 1);
  assert.equal(f.calls.load.length, 1);
  assert.equal(f.doc.querySelector('.source-reader-setting').hidden, false);
  assert.equal(f.doc.querySelector('.sentence-jump').href, 'http://127.0.0.1/paper/0');
  assert.equal(f.doc.querySelector('.as-continue'), null, 'no new visible button changes the original flow');
  scrollAtSentinel(f);
  await until(() => f.doc.querySelectorAll('li.example-card').length === 11);
  assert.equal(f.calls.prepare, 1, 'the exact projection token is prepared once, not per part');
  assert.equal(f.doc.querySelectorAll('ol.examples > li.example-card').length, 11);
});

test('a complete sense loads progressively but runs each strict helper only once; year filter applies to late rows', async t => {
  const f = fixture(t, payload);
  const parts = [f.part(sf(1, '2025')), f.part(sf(2, '2026')), f.part(sf(3, '2026'))];
  f.doc.body.insertAdjacentHTML('afterbegin', '<details class="sf-sense"><summary>释义</summary><div class="sf-panel"><button data-sf-filter="all" aria-pressed="false">全部</button><button data-sf-filter="2026" aria-pressed="true">2026</button>' + f.manifest(parts, 'sense') + '</div></details>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.calls.load.length, 0);
  f.doc.querySelector('details').open = true;
  await until(() => f.doc.querySelector('.as-manifest').dataset.asState === 'ready');
  await until(() => f.calls.group === 1);
  assert.equal(f.doc.querySelectorAll('.sf-panel > .sf-example').length, 3, 'rows stay direct children');
  assert.deepEqual([...f.doc.querySelectorAll('.sf-example')].map(r => r.hidden), [true, false, false]);
  assert.equal(f.calls.fine, 1);
  assert.equal(f.calls.projected, 1);
  assert.equal(f.calls.bank, 1);
  assert.equal(f.calls.group, 1);
  assert.equal(f.w.AnkiSlimBatching, 0);
});

test('the producer inline first ten examples are immediately readable and are not loaded twice', async t => {
  const f = fixture(t, payload);
  const next = f.part(example(10));
  f.doc.body.insertAdjacentHTML('afterbegin', '<ol class="examples">' + Array.from({ length: 10 }, (_, n) => example(n)).join('') + f.manifest([next], 'examples') + '</ol>');
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 10, 'inline content is readable before hydration');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.calls.load.length, 0);
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 10);
  scrollAtSentinel(f);
  await until(() => f.doc.querySelectorAll('li.example-card').length === 11);
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 11);
});

test('independent static index and payload are hashed local assets, retaining source identity bytes', async t => {
  const f = fixture(t, '');
  const data = f.part(JSON.stringify({ a: 'all original projection' }), 0);
  const identity = JSON.stringify(['kaoyan:2026-01:p:test', 'B'.repeat(43), 'C'.repeat(43)]);
  const rows = [{ source: '  原文来源 ', english: 'all word', translation: ' 原译 ', identity }];
  const ix = f.part(JSON.stringify(rows), 0);
  f.doc.body.innerHTML = '<script type="application/json" class="anki-final-reviewed-data" data-as-src="' + data.src + '" data-as-sha="' + data.sha256 + '" data-as-index-src="' + ix.src + '" data-as-index-sha="' + ix.sha256 + '"></script>';
  await f.w.AnkiSlimApkgHydrate();
  const native = f.w.AnkiSlimPhysicalNativeIndex(f.doc);
  assert.equal(native.size, 1);
  assert.deepEqual([...native.get(JSON.stringify(['原文来源', 'all word', '原译']))], [identity]);
  assert.equal(f.calls.prepare, 1);
  f.w.AnkiFinalApkgDispose();
  assert.equal(f.w.AnkiSlimPhysicalNativeIndex(f.doc).size, 0);
});

test('hash mismatch never inserts a corrupt segment and a local retry recovers without duplicate rows', async t => {
  const f = fixture(t, payload);
  const part = f.part(example(1));
  f.w.AnkiSlimAssets[part.sha256] = '<li>wrong bytes</li>';
  f.doc.body.insertAdjacentHTML('afterbegin', '<ol class="examples">' + f.manifest([part], 'examples') + '</ol>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 0);
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asState, 'failed');
  assert.match(f.doc.querySelector('.anki-final-status').textContent, /校验失败/);
  await new Promise(resolve => setTimeout(resolve, 1010));
  scrollAtSentinel(f);
  await until(() => f.doc.querySelectorAll('li.example-card').length === 1);
  await until(() => f.doc.querySelector('.as-manifest').dataset.asState === 'ready');
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 1);
});

test('an old card asynchronous media response cannot write into the next card', async t => {
  const f = fixture(t, payload, { delay: 60 });
  const part = f.part(example(99));
  f.doc.body.insertAdjacentHTML('afterbegin', '<ol class="examples">' + f.manifest([part], 'examples') + '</ol>');
  const old = f.w.AnkiSlimApkgHydrate();
  await until(() => f.calls.load.length === 1);
  f.doc.body.innerHTML = '<h1>new card</h1>' + payload;
  await f.w.AnkiSlimApkgHydrate(); await old;
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 0);
  assert.equal(f.doc.querySelector('h1').textContent, 'new card');
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
});

test('complete review detail and nested original-HTML evidence remain lazy, literal and retryable', async t => {
  const f = fixture(t, payload);
  const rawProof = '<script>window.proofExecuted=true</script><p>全部原证据</p>', proof = sha(rawProof);
  f.w.AnkiFinalHistoryEvidence = { [proof]: rawProof };
  const inner = f.part('<p class="ownership-reason">完整审核说明，逐字保留。</p><details class="evidence"><summary>完整 HTML</summary><pre data-native-history-media="_af_' + proof.slice(0, 24) + '.js" data-native-history-sha="' + proof + '"></pre></details>');
  f.doc.body.insertAdjacentHTML('afterbegin', '<details class="sf-ownership-history"><summary>本句归属说明</summary>' + f.manifest([inner], 'detail') + '</details>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('.ownership-reason'), null);
  f.doc.querySelector('.sf-ownership-history').open = true;
  await until(() => f.doc.querySelector('.ownership-reason'));
  assert.equal(f.doc.querySelector('.ownership-reason').textContent, '完整审核说明，逐字保留。');
  f.doc.querySelector('.evidence').open = true;
  await until(() => f.doc.querySelector('pre').dataset.nativeHistoryReady === 'true');
  assert.equal(f.doc.querySelector('pre').textContent, rawProof);
  assert.equal(f.w.proofExecuted, undefined);
});

test('nested manifests discovered in later media restore in their original detail position', async t => {
  const f = fixture(t, payload);
  const inner = f.part('<p class="reason">nested exact reason</p>');
  const outer = f.part('<details class="nested"><summary>原核对记录</summary>' + f.manifest([inner], 'detail') + '</details>');
  f.doc.body.insertAdjacentHTML('afterbegin', '<div class="as-lazy"><script class="as-manifest" type="application/json">' + JSON.stringify({ schema: 'anki-slim-segments.v1', parts: [outer], total: 1 }) + '</script></div>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('.reason'), null);
  f.doc.querySelector('.nested').open = true;
  await until(() => f.doc.querySelector('.reason'));
  assert.equal(f.doc.querySelector('.nested > p.reason').textContent, 'nested exact reason');
});

test('ownership detail inside a sense panel loads on its own original summary, not the outer sense', async t => {
  const f = fixture(t, payload);
  const inner = f.part('<p class="ownership-reason">本句归属完整审核依据</p>');
  const outer = f.part('<article class="sf-example" data-sf-year="2026"><p class="sf-en">target word</p><details class="sf-ownership-history"><summary>本句归属说明</summary>' + f.manifest([inner], 'detail') + '</details></article>');
  f.doc.body.insertAdjacentHTML('afterbegin', '<details class="sf-sense"><summary>释义</summary><div class="sf-panel">' + f.manifest([outer], 'sense') + '</div></details>');
  await f.w.AnkiSlimApkgHydrate();
  f.doc.querySelector('.sf-sense').open = true;
  await until(() => f.doc.querySelector('.sf-ownership-history'));
  await until(() => f.doc.querySelector('.sf-panel > .as-lazy .as-manifest').dataset.asState === 'ready');
  assert.equal(f.doc.querySelector('.ownership-reason'), null, 'opening the sense must not load a closed audit');
  assert.equal(f.calls.load.length, 1);
  f.doc.querySelector('.sf-ownership-history').open = true;
  await until(() => f.doc.querySelector('.ownership-reason'));
  assert.equal(f.doc.querySelector('.sf-ownership-history > .ownership-reason').textContent, '本句归属完整审核依据');
  assert.equal(f.calls.load.length, 2);
  assert.equal(f.doc.querySelector('.as-continue'), null);
  assert.equal(f.doc.querySelector('.anki-final-status'), null);
});

test('remote or traversal media addresses are rejected before any request', async t => {
  const f = fixture(t, '<script class="anki-final-reviewed-data" data-as-src="https://example.com/asset.js" data-as-sha="' + 'a'.repeat(64) + '"></script>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.calls.load.length, 0);
  assert.equal(f.doc.querySelector('script').dataset.nativeState, 'failed');
  assert.match(f.doc.querySelector('.anki-final-status').textContent, /标识无效/);
});

test('a malformed total cannot alter occurrence arithmetic or append rows', async t => {
  const f = fixture(t, payload);
  const part = f.part(example(1), 1);
  f.doc.body.insertAdjacentHTML('afterbegin', '<ol class="examples"><li class="as-lazy" data-as-kind="examples"><script class="as-manifest" type="application/json">' + JSON.stringify({ schema: 'anki-slim-segments.v1', parts: [part], total: 3 }) + '</script></li></ol>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'failed');
  assert.equal(f.doc.querySelectorAll('.example-card').length, 0);
});

test('the accepted grouping helper merges three late parts only after completion while retaining all evidence', async t => {
  const f = fixture(t, '');
  acceptedGroup(f.w);
  const english = 'train train trains', translation = '列车 列车 列车';
  const source = '2026年考研英语二 ➫ Part A ➫ Text 3';
  const identity = JSON.stringify(['kaoyan:2026-02:p:test', 'B'.repeat(43), 'C'.repeat(43)]);
  const index = f.part(JSON.stringify([{ source, english, translation, identity }]), 0);
  const paragraph = selected => {
    const en = ['train', 'train', 'trains'].map((word, n) => '<span class="card-chunk' + (n === selected ? ' sf-target-chunk' : '') + '" data-chunk-ids="' + (n + 1) + '" data-chunk-side="en">' + (n === selected ? '<mark class="target-word">' + word + '</mark>' : word) + '</span>').join(' ');
    const zh = [0, 1, 2].map(n => '<span class="card-chunk' + (n === selected ? ' sf-target-chunk' : '') + '" data-chunk-ids="' + (n + 1) + '" data-chunk-side="zh">列车</span>').join(' ');
    return '<article class="sf-example" data-sf-year="2026" data-sf-occurrence-id="' + sha('occurrence-' + selected) + '"><p class="sf-source">' + source + '</p><div class="sf-sentence-pair"><p class="sf-en">' + en + '</p><p class="sf-zh">' + zh + '</p></div><p class="sf-evidence">独立依据 ' + selected + '</p></article>';
  };
  const parts = [0, 1, 2].map(n => f.part(paragraph(n)));
  f.doc.body.innerHTML = '<div class="sf-report"><span class="sf-summary-count">3 次</span><details class="sf-sense"><summary>列车义</summary><div class="sf-panel"><button data-sf-filter="all" aria-pressed="true">全部</button><p class="sf-preview-count">显示 3 条原文</p>' + f.manifest(parts, 'sense') + '</div></details></div><script type="application/json" class="anki-final-reviewed-data" data-as-index-src="' + index.src + '" data-as-index-sha="' + index.sha256 + '">{}</script>';
  await f.w.AnkiSlimApkgHydrate();
  f.doc.querySelector('.sf-sense').open = true;
  await until(() => f.doc.querySelectorAll('.sf-group-member-evidence').length === 3);
  const rows = [...f.doc.querySelectorAll('.sf-panel > .sf-example')];
  assert.equal(rows.length, 3, 'all original physical occurrences remain in DOM');
  assert.equal(rows.filter(row => !row.hidden).length, 1);
  assert.equal(f.doc.querySelector('.sf-summary-count').textContent, '3 次', 'frequency arithmetic is never rewritten');
  assert.equal(rows[0].querySelectorAll('mark.target-word').length, 3);
  assert.deepEqual([...f.doc.querySelectorAll('.sf-group-member-evidence .sf-evidence')].map(e => e.textContent), ['独立依据 0', '独立依据 1', '独立依据 2']);
});

test('a paused partial sense does not block grouping another complete sense and resumes safely', async t => {
  const f = fixture(t, '');
  acceptedGroup(f.w);
  const english = 'train train trains', translation = '列车 列车 列车', source = '2026年考研英语二 ➫ Text 3';
  const identity = JSON.stringify(['kaoyan:2026-02:p:test', 'B'.repeat(43), 'C'.repeat(43)]);
  const ix = f.part(JSON.stringify([{ source, english, translation, identity }]), 0);
  const row = (sense, selected) => {
    const en = ['train', 'train', 'trains'].map((word, n) => '<span class="card-chunk" data-chunk-ids="' + (n + 1) + '">' + (n === selected ? '<mark class="target-word">' + word + '</mark>' : word) + '</span>').join(' ');
    const zh = [0, 1, 2].map(n => '<span class="card-chunk" data-chunk-ids="' + (n + 1) + '">列车</span>').join(' ');
    return '<article class="sf-example" data-sf-year="2026" data-sf-occurrence-id="' + sha(sense + selected) + '"><p class="sf-source">' + source + '</p><div class="sf-sentence-pair"><p class="sf-en">' + en + '</p><p class="sf-zh">' + zh + '</p></div><p class="sf-evidence">' + sense + '依据' + selected + '</p></article>';
  };
  const a = [0, 1, 2].map(n => f.part(row('A', n))), b = [0, 1, 2].map(n => f.part(row('B', n)));
  f.doc.body.innerHTML = ['A', 'B'].map((sense, n) => '<details class="sf-sense" id="sense' + sense + '"><summary>' + sense + '释义</summary><div class="sf-panel"><button data-sf-filter="all" aria-pressed="true">全部</button>' + f.manifest(n ? b : a, 'panel') + '</div></details>').join('') + '<script type="application/json" class="anki-final-reviewed-data" data-as-index-src="' + ix.src + '" data-as-index-sha="' + ix.sha256 + '">{}</script>';
  await f.w.AnkiSlimApkgHydrate();
  const panelA = f.doc.querySelector('#senseA .sf-panel'), panelB = f.doc.querySelector('#senseB .sf-panel');
  assert.equal(f.w.AnkiSlimPanelReady(panelA), false);
  const observer = new f.w.MutationObserver(() => {
    if (panelA.querySelector('.sf-example')) { f.doc.querySelector('#senseA').open = false; observer.disconnect(); }
  });
  observer.observe(panelA, { childList: true });
  f.doc.querySelector('#senseA').open = true;
  await until(() => panelA.querySelectorAll(':scope > .sf-example').length === 1 && panelA.getAttribute('aria-busy') === null);
  assert.equal(f.w.AnkiSlimPanelReady(panelA), false);
  f.doc.querySelector('#senseB').open = true;
  await until(() => panelB.querySelectorAll('.sf-group-member-evidence').length === 3);
  assert.equal(f.w.AnkiSlimPanelReady(panelB), true);
  assert.equal([...panelB.querySelectorAll(':scope > .sf-example')].filter(el => !el.hidden).length, 1);
  assert.equal(panelA.querySelectorAll('.sf-group-member-evidence').length, 0);
  f.doc.querySelector('#senseA').open = true;
  await until(() => panelA.querySelectorAll('.sf-group-member-evidence').length === 3);
  assert.equal(f.w.AnkiSlimPanelReady(panelA), true);
  assert.equal([...panelA.querySelectorAll(':scope > .sf-example')].filter(el => !el.hidden).length, 1);
  assert.equal([...panelB.querySelectorAll(':scope > .sf-example')].filter(el => !el.hidden).length, 1);
});
