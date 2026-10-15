'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const { JSDOM } = require('jsdom');
const own = __dirname;
const sourceText = fs.readFileSync(path.join(own, 'shared-reading-bank-runtime-v5.js'), 'utf8');
const sidecarBytes = fs.readFileSync(path.join(own, 'shared-reading-bank-v5.json'));
assert.equal(crypto.createHash('sha256').update(sidecarBytes).digest('hex'), 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5');
const metadata = JSON.parse(sidecarBytes);
const locators = JSON.parse(fs.readFileSync(path.join(own, 'actual-understand-D-native-sf-locators.json')));
const sourceBytes = fs.readFileSync(locators.source_pin.file);
assert.equal(crypto.createHash('sha256').update(sourceBytes).digest('hex'), locators.source_pin.sha256);
const sourceDoc = new JSDOM(sourceBytes.toString()).window.document;
const inflaterScripts = Array.from(sourceDoc.scripts).map(s => s.textContent).filter(s => s.includes('function hex(value)') && s.includes("document.querySelectorAll('a[data-rb-j]')")).map(s => {
  const start = s.indexOf("(function(){'use strict';var config=");
  const anchors = s.indexOf("document.querySelectorAll('a[data-rb-j]')", start);
  const end = s.indexOf('\n})();', anchors);
  assert.ok(start >= 0 && anchors > start && end > anchors);
  return s.slice(start, end + '\n})();'.length);
});
const uniqueInflaters = Array.from(new Set(inflaterScripts));
assert.equal(uniqueInflaters.length, 1, 'all actual decoder copies have identical bytes');
const inflater = uniqueInflaters[0];
const realSf = sourceDoc.querySelector('article[data-sf-occurrence-id="4f78510949289f71afe90e6b8b65817f392ee17d2088170203d48fa6cd043eac"]').outerHTML;
const realNativeAnchors = Array.from(sourceDoc.querySelectorAll('a[data-rb-j]')).filter(a => a.getAttribute('data-rb-j').startsWith('0|2012-02|q-41-1%3AD%3Anew%3A0|'));
assert.equal(realNativeAnchors.length, 1);
const realNative = realNativeAnchors[0].closest('li').outerHTML;
const q34SourcePin = {
  file: path.resolve(own, '../full-2026-v4/web-preview/1680addfd790b86896aee3132fd280c9a00c6c2466e2fe67717d06f0376c2855/cards/50dae402dda20e63b789a8638ed49c6c108eca2005f3f78be68d6e5b70a3c3f5.html'),
  sha256: '110ce4e381e2d1bb56b306200829be87825cb1071fa7293b26888f8d2c5a98e5'
};
const q34Bytes = fs.readFileSync(q34SourcePin.file);
assert.equal(crypto.createHash('sha256').update(q34Bytes).digest('hex'), q34SourcePin.sha256);
const q34Doc = new JSDOM(q34Bytes.toString()).window.document;
const q34Anchors = Array.from(q34Doc.querySelectorAll('a.sentence-jump')).filter(anchor => {
  const route = new URL(anchor.getAttribute('href'), 'http://localhost:8765');
  return route.searchParams.get('anki-codex-sentence') === 'kaoyan:2024-01:q-34-1:D:new:0';
});
assert.equal(q34Anchors.length, 2, 'actual Q34 native and SF original reader anchors');
const realQ34 = q34Anchors.map(anchor => anchor.closest('.sf-example') || anchor.closest('li.example-card'));
assert.ok(realQ34.every(Boolean));
const D = metadata.sentence_bindings.find(b => b.sentence_id === 'kaoyan:2012-02:q-41-1:D:new:0');
const A = metadata.sentence_bindings.find(b => b.sentence_id === 'kaoyan:2012-02:q-41-1:A:new:0');
const tests = [], results = [];
function test(name, callback) { tests.push([name, callback]); }
function esc(value) { return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'); }
function url(binding, extra = {}) {
  const u = new URL('http://localhost:8765/exam-library/practice/full-paper.htm');
  u.searchParams.set('paper', binding.paper_id); u.searchParams.set('anki-codex-sentence', binding.sentence_id);
  u.searchParams.set('anki-codex-hash', binding.english_hash); u.searchParams.set('anki-codex-review', binding.reviewed_content_hash);
  u.searchParams.set('anki-codex-en', JSON.stringify([[0, 1]]));
  Object.entries(extra).forEach(([k, v]) => u.searchParams.set(k, v));
  return u.toString();
}
function fixture(binding, kind = 'sf', { label = '答案未核实 ' + binding.option_label, extra = '', rawText = binding.english } = {}) {
  const anchor = '<a class="sentence-jump" href="' + esc(url(binding)) + '"></a>';
  const usage = label === null ? '' : '<span class="exam-usage-labels"><span>' + esc(label) + '</span><span>匹配来自选项</span></span>';
  return kind === 'native' ? '<li class="example-card"><div class="example-heading"><span class="example-text">' + esc(rawText) + '</span>' + anchor + '</div><p class="example-translation">原中文不改</p><span class="example-source">来源</span>' + usage + extra + '</li>' :
    '<article class="' + (kind === 'sf' ? 'sf-example' : kind) + '"><p class="sf-source">来源' + anchor + '</p>' + usage + '<div class="sf-sentence-pair example-card"><p class="sf-en">' + esc(rawText) + '</p><p class="sf-zh">原中文不改</p></div>' + extra + '</article>';
}
async function settle() { for (let i = 0; i < 5; i++) await new Promise(r => setImmediate(r)); }
function setup(html, options = {}) {
  const dom = new JSDOM('<html><body><div class="frequency-count">99</div><p class="sf-preview-count">显示 2 处原文</p><ul>' + html + '</ul></body></html>',
    { url: 'http://localhost:8766/card.html', runScripts: 'outside-only' });
  const w = dom.window, d = w.document;
  Object.defineProperty(w, 'crypto', { value: crypto.webcrypto }); w.TextEncoder = TextEncoder;
  w.eval(inflater); // Exact actual card program, before the independent consumer.
  if (options.beforeInstall) options.beforeInstall(d, w);
  const before = d.body.innerHTML;
  let handlers = 0; const add = d.addEventListener.bind(d);
  d.addEventListener = (...args) => { handlers++; return add(...args); };
  w.eval(sourceText);
  const handle = w.AnkiSharedReadingBankRuntime.install(d, options.metadata || metadata);
  assert.equal(handlers, 0, 'consumer adds no click/keyboard handlers');
  assert.equal(w.AnkiSharedReadingBankRuntime.install(d, options.metadata || metadata), handle);
  return { dom, w, d, handle, before };
}
function frozenBodies(d) {
  return {
    en: Array.from(d.querySelectorAll('.sf-en,.example-text')).map(e => e.outerHTML),
    zh: Array.from(d.querySelectorAll('.sf-zh,.example-translation')).map(e => e.outerHTML),
    marks: Array.from(d.querySelectorAll('mark.target-word')).map(e => e.outerHTML),
    anchors: Array.from(d.querySelectorAll('a.sentence-jump')).map(e => e.outerHTML),
    histories: Array.from(d.querySelectorAll('.sf-ownership-history,[data-native-ownership-history]')).map(e => e.outerHTML),
    counts: Array.from(d.querySelectorAll('.frequency-count,.sf-preview-count')).map(e => e.outerHTML),
    examples: d.querySelectorAll('.sf-example,.example-card').length
  };
}
async function unchangedNegative(html, change) {
  const h = setup(html, { beforeInstall: change });
  await h.handle.ready; await settle();
  assert.equal(h.d.body.innerHTML, h.before, 'rejection must leave the complete DOM unchanged');
  assert.equal(h.d.querySelector('[data-shared-reading-bank-group-id]'), null);
  h.handle.dispose(); h.dom.window.close();
}

test('actual understand D native + SF, including complete history and raw bilingual/target/count preservation', async () => {
  const h = setup(realSf + realNative), before = frozenBodies(h.d);
  await h.handle.ready; await settle();
  const labels = Array.from(h.d.querySelectorAll('[data-shared-reading-bank-group-id]'));
  assert.equal(labels.length, 2);
  for (const label of labels) {
    assert.ok(label.textContent.includes('错误选项 D · 41–45题共享干扰项'));
    const evidence = JSON.parse(label.dataset.sharedReadingBankEvidence);
    assert.equal(evidence.question_id, null); assert.equal(evidence.counting_effect, 'none');
    assert.deepEqual(evidence.matched_question_ids, []);
  }
  assert.deepEqual(frozenBodies(h.d), before);
  assert.equal(h.handle.stats().projectedNative, 1); assert.equal(h.handle.stats().projectedSf, 1);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('real used A reports matched q41, while single-question claim stays null', async () => {
  const h = setup(fixture(A, 'native')); await h.handle.ready;
  const e = JSON.parse(h.d.querySelector('[data-shared-reading-bank-evidence]').dataset.sharedReadingBankEvidence);
  assert.equal(e.display_label, '正确选项 A · 对应第41题'); assert.equal(e.question_id, null);
  assert.deepEqual(e.matched_question_ids, ['kaoyan:2012-02:q-41-1']); h.dom.window.close();
});
test('all 632 pinned aliases classify independently from exact source identity, covering all 172 bank items', async () => {
  const h = setup(metadata.sentence_bindings.map(b => fixture(b)).join(''));
  const before = frozenBodies(h.d); await h.handle.ready; await settle();
  const labels = Array.from(h.d.querySelectorAll('[data-shared-reading-bank-evidence]'));
  assert.equal(labels.length, 632); assert.equal(new Set(labels.map(l => JSON.parse(l.dataset.sharedReadingBankEvidence).source_option_id)).size, 172);
  assert.equal(new Set(labels.map(l => l.dataset.sharedReadingBankGroupId)).size, 27);
  labels.forEach(l => { assert.equal(JSON.parse(l.dataset.sharedReadingBankEvidence).question_id, null); });
  assert.deepEqual(frozenBodies(h.d), before); h.dom.window.close();
});
test('wrong paper reader route is rejected', async () => unchangedNegative(fixture(D), d => {
  const a = d.querySelector('a'), u = new URL(a.href); u.searchParams.set('paper', 'kaoyan:2014-02'); a.href = u;
}));
test('conflicting multiple route attributes are rejected', async () => unchangedNegative(fixture(D), d => {
  d.querySelector('a').setAttribute('data-full-paper-url', url(A));
}));
test('source text substring is insufficient; whole English must match', async () => unchangedNegative(fixture(D, 'sf', { rawText: 'prefix ' + D.english })));
test('wrong original English hash is rejected', async () => unchangedNegative(fixture(D), d => {
  d.querySelector('a').href = url(D, { 'anki-codex-hash': '0'.repeat(64) });
}));
test('wrong reviewed source hash is rejected', async () => unchangedNegative(fixture(D), d => {
  d.querySelector('a').href = url(D, { 'anki-codex-review': '0'.repeat(64) });
}));
test('multiple source anchors are ambiguous even when both printed English and hashes repeat', async () => unchangedNegative(fixture(D), d => {
  d.querySelector('.sf-source').append(d.querySelector('a').cloneNode(true));
}));
test('same word and printed D on a nonbank original source do not license a label change', async () => {
  const other = { ...D, sentence_id: 'kaoyan:2012-02:q-34-1:D:new:0' };
  await unchangedNegative(fixture(other));
});
test('actual 2024 English I Q34 correct D native + SF keep all source, target, count and usage bytes', async () => {
  const h = setup(realQ34.map(element => element.outerHTML).join(''));
  assert.equal(h.d.querySelectorAll('.exam-usage-labels').length, 2);
  assert.ok(Array.from(h.d.querySelectorAll('.exam-usage-labels')).every(label => label.textContent === '正确选项 D匹配来自选项'));
  await h.handle.ready; await settle();
  assert.equal(h.d.body.innerHTML, h.before);
  assert.equal(h.d.querySelector('[data-shared-reading-bank-group-id]'), null);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('exact-binding archived comparison stays byte-for-byte unchanged', async () => {
  await unchangedNegative('<details class="sf-ownership-history">' + fixture(D) + '</details>');
});
test('repeated bank sentence counts stay fixed and same D across different groups never merges', async () => {
  const other = metadata.sentence_bindings.find(b => b.sentence_id === 'kaoyan:2014-02:q-41-1:D:new:0');
  const h = setup(fixture(D) + fixture(D, 'native') + fixture(other));
  const before = frozenBodies(h.d); await h.handle.ready;
  const labels = Array.from(h.d.querySelectorAll('[data-shared-reading-bank-group-id]'));
  assert.equal(labels.length, 3); assert.equal(new Set(labels.map(l => l.dataset.sharedReadingBankGroupId)).size, 2);
  assert.deepEqual(frozenBodies(h.d), before); h.dom.window.close();
});
test('SF source/year preview clones bind exact source independently and update after DOM insertion', async () => {
  const h = setup(fixture(D, 'sf-source-preview')); await h.handle.ready;
  const holder = h.d.createElement('div'); holder.innerHTML = fixture(D, 'sf-year-preview'); h.d.body.append(holder);
  await settle(); await h.handle.refresh();
  assert.equal(h.d.querySelectorAll('[data-shared-reading-bank-group-id]').length, 2);
  assert.equal(h.handle.stats().projectedPreview, 2); h.dom.window.close();
});
test('12 missing banks remain unbound unknown; only general info diagnoses the 60 questions', async () => {
  const unknown = { ...D, paper_id: 'kaoyan:2007-01', sentence_id: 'kaoyan:2007-01:q-41-1:D:new:0' };
  const h = setup(fixture(unknown)); await h.handle.ready;
  assert.equal(h.d.body.innerHTML, h.before);
  assert.equal(h.handle.diagnostics().missing_bank_groups.length, 12);
  assert.equal(h.handle.diagnostics().unknown_questions, 60);
  assert.ok(h.handle.diagnostics().info_text.includes('缺原选项库')); h.dom.window.close();
});
test('mutated sidecar bytes are rejected before any display mutation', async () => {
  const changed = JSON.parse(sidecarBytes); changed.groups[0].bank[0].correctness = 'correct';
  const h = setup(fixture(D), { metadata: changed });
  await assert.rejects(h.handle.ready, /sidecar byte SHA mismatch/);
  assert.equal(h.d.body.innerHTML, h.before); h.handle.dispose(); h.dom.window.close();
});
test('camel null cannot mask snake qid in reader context or any derived metadata source', async () => {
  for (const key of ['self', 'reading_candidate', 'derivation_payload', 'option_context', 'reading_completion']) {
    const pair = { questionId: null, question_id: 'kaoyan:2012-02:q-41-1' };
    const context = key === 'self' ? pair : { [key]: pair };
    await unchangedNegative(fixture(D), d => { d.querySelector('a').href = url(D, { 'anki-codex-context': JSON.stringify(context) }); });
  }
});
test('dispose before async validation cannot write labels to an old frame', async () => {
  const h = setup(fixture(D)); h.handle.dispose(); await h.handle.ready; await settle();
  assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('changing the original English withdraws stale projection while preserving the new source text', async () => {
  const h = setup(fixture(D)); await h.handle.ready;
  h.d.querySelector('.sf-en').firstChild.data += ' changed';
  await settle(); await h.handle.refresh();
  assert.equal(h.d.querySelector('[data-shared-reading-bank-group-id]'), null);
  assert.equal(h.d.querySelector('.sf-en').textContent, D.english + ' changed');
  assert.equal(h.d.querySelector('.exam-usage-labels').textContent, '答案未核实 D匹配来自选项'); h.dom.window.close();
});
test('conflicting explicit label correctness leaves no partial group annotations', async () => {
  await unchangedNegative(fixture(D, 'sf', { label: '正确选项 D' }));
});
test('passage bank without old usage markup receives only additive labels, reversible on dispose', async () => {
  const binding = metadata.sentence_bindings.find(b => b.source_kind === 'passage_option');
  const h = setup(fixture(binding, 'native', { label: null })), before = frozenBodies(h.d);
  await h.handle.ready; assert.equal(h.d.querySelectorAll('.exam-usage-labels').length, 1);
  assert.deepEqual(frozenBodies(h.d), before);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('reader target bounds outside the exact full original sentence are rejected', async () => unchangedNegative(fixture(D), d => {
  d.querySelector('a').href = url(D, { 'anki-codex-en': '[[24,100]]' });
}));

(async () => {
  for (const [name, callback] of tests) {
    await callback(); results.push({ name, pass: true }); console.log('PASS', name);
  }
  const receipt = { schema: 'shared-reading-bank-runtime-js-tests.v5', status: 'pass', tests: results,
    source_pin: locators.source_pin,
    actual_q34_source_pin: q34SourcePin,
    actual_inflater_sha256: crypto.createHash('sha256').update(inflater).digest('hex'),
    runtime_sha256: crypto.createHash('sha256').update(sourceText).digest('hex'),
    sidecar_sha256: crypto.createHash('sha256').update(sidecarBytes).digest('hex'),
    claims: { actual_generated_D_native_and_sf_fixture: true, all_632_aliases_172_items: true,
      actual_generated_Q34_native_and_sf_unchanged: true,
      no_frequency_or_bilingual_body_or_history_edits: true, no_input_handlers: true,
      final_browser_or_sqlite_acceptance: false } };
  fs.writeFileSync(path.join(own, 'runtime-js-test-receipt-v5.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ tests: results.length, status: 'pass', runtime_sha256: receipt.runtime_sha256 }));
  sourceDoc.defaultView.close();
  q34Doc.defaultView.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
