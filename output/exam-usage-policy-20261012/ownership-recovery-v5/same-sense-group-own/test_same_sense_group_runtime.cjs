'use strict';
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto'), assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const own = __dirname, repo = path.resolve(own, '../../../..'), runtime = fs.readFileSync(path.join(own, 'same-sense-group-runtime.js'), 'utf8');
const results = [], live = [];
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
function setup(book = 'redbook2027', word = 'train') {
  const catalogFile = path.join(own, '../owner-source-display-v5/final-overlay', book, 'catalog.json');
  const catalog = JSON.parse(fs.readFileSync(catalogFile)), card = catalog.cards.find(row => row.word === word), file = path.join(repo, 'output', card.previewUrl);
  const raw = fs.readFileSync(file), dom = new JSDOM(raw.toString(), { runScripts: 'outside-only', url: 'http://localhost:8771' + card.previewUrl }); live.push(dom);
  const w = dom.window, d = w.document;
  w.eval(fs.readFileSync(path.join(repo, 'anki_pipeline/templates/card-chunks.js'), 'utf8'));
  w.eval(fs.readFileSync(path.join(repo, 'anki_pipeline/templates/sense-frequency.js'), 'utf8'));
  w.eval(runtime);
  return { w, d, card, raw, file, install: () => w.AnkiSameSenseGroupRuntime.install(d) };
}
function trainRows(d) { return [...d.querySelectorAll('.sf-example')].filter(row => row.querySelector(':scope > .sf-sentence-pair > .sf-en')?.textContent.startsWith('Ferrovie dello Stato Italiane')); }
function visible(rows) { return rows.filter(row => !row.hidden); }
async function test(name, run) { try { await run(); results.push({ name, passed: true }); } catch (error) { results.push({ name, passed: false, error: error.stack }); } finally { live.splice(0).forEach(dom => dom.window.close()); } }
(async () => {
  for (const book of ['redbook', 'redbook2027']) await test(book + ': actual source train three physical tokens show one sentence, three fine chunks, all counts and original text unchanged', () => {
    const h = setup(book), rows = trainRows(h.d); assert.equal(rows.length, 3);
    const panel = rows[0].closest('.sf-panel'), count = panel.parentElement.querySelector('.sf-count').textContent, buttons = [...panel.querySelectorAll('[data-sf-filter]')].map(e => e.textContent), ids = rows.map(row => row.dataset.sfOccurrenceId);
    const native = [...h.d.querySelectorAll('li._r28,li.example-card')].find(row => row.textContent.includes('Ferrovie dello Stato'));
    const compressed = native.querySelector('[data-rb-j]');
    if (compressed) { const source = compressed.dataset.rbJ.split('|'); assert.equal(decodeURIComponent(source[2]), 'p:b-7-4:1'); assert.equal(source[5], '71,76;114,119;167,173'); }
    else { const url = new URL(native.querySelector('.sentence-jump').href); assert.equal(url.searchParams.get('anki-codex-sentence'), 'kaoyan:2026-02:p:b-7-4:1'); assert.deepEqual(JSON.parse(url.searchParams.get('anki-codex-en')), [[71,76],[114,119],[167,173]]); }
    const texts = rows.map(row => [row.querySelector('.sf-en').textContent, row.querySelector('.sf-zh').textContent]);
    const reasons = rows.map(row => row.querySelector(':scope > .sf-reason').textContent), handle = h.install();
    assert.equal(visible(rows).length, 1); assert.equal(rows.length, 3); assert.deepEqual(JSON.parse(rows[0].dataset.sfGroupMemberIds), ids); assert.equal(rows[0].dataset.sfGroupOccurrences, '3');
    assert.equal(panel.parentElement.querySelector('.sf-count').textContent, count); assert.deepEqual([...panel.querySelectorAll('[data-sf-filter]')].map(e => e.textContent), buttons);
    assert.deepEqual(rows.map(row => [row.querySelector(':scope > .sf-sentence-pair > .sf-en').textContent, row.querySelector(':scope > .sf-sentence-pair > .sf-zh').textContent]), texts);
    assert.deepEqual([...rows[0].querySelectorAll(':scope > .sf-sentence-pair > .sf-en mark.target-word')].map(e => e.textContent), ['train', 'train', 'trains']);
    assert.deepEqual([...rows[0].querySelectorAll('.sf-group-member-evidence > .sf-reason')].map(e => e.textContent), reasons);
    assert.equal(rows[0].querySelectorAll('.sf-group-member-evidence').length, 3); assert.equal(native.querySelectorAll('mark.target-word').length, 3);
    assert.ok(!rows[0].textContent.includes('次出现')); assert.ok(!rows[0].textContent.includes('×3'));
    const pair = rows[0].querySelector(':scope > .sf-sentence-pair');
    for (const id of ['2', '3', '6']) {
      const en = [...pair.querySelectorAll('.sf-en .card-chunk')].find(el => el.dataset.chunkIds === id), zh = [...pair.querySelectorAll('.sf-zh .card-chunk')].find(el => el.dataset.chunkIds === id);
      en.dispatchEvent(new h.w.MouseEvent('click', { bubbles: true, cancelable: true })); assert.ok(zh.classList.contains('card-chunk-active'));
      const wrong = [...pair.querySelectorAll('.sf-zh .card-chunk')].filter(el => el.dataset.chunkIds !== id); assert.ok(wrong.every(el => !el.classList.contains('card-chunk-active')));
      en.dispatchEvent(new h.w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      zh.dispatchEvent(new h.w.MouseEvent('click', { bubbles: true, cancelable: true })); assert.ok(en.classList.contains('card-chunk-active'));
    }
    const year2026 = panel.querySelector('[data-sf-filter="2026"]'); year2026.click(); assert.equal(visible(rows).length, 1); assert.equal(panel.querySelector('.sf-preview-count').textContent, '显示 ' + [...panel.querySelectorAll(':scope > .sf-example')].filter(e => !e.hidden).length + ' 条原文');
    const other = [...panel.querySelectorAll('[data-sf-filter]')].find(e => !['all', '2026'].includes(e.dataset.sfFilter)); if (other) { other.click(); assert.equal(visible(rows).length, 0); }
    panel.querySelector('[data-sf-filter="all"]').click(); assert.equal(visible(rows).length, 1);
    const before = rows[0].innerHTML, stats = handle.stats(); handle.refresh(); handle.refresh(); assert.equal(rows[0].innerHTML, before); assert.deepEqual(handle.stats(), stats); assert.equal(h.install(), handle);
    assert.equal(hash(fs.readFileSync(h.file)), hash(h.raw));
  });
  await test('same text and visible source label from two different physical sentence IDs never combine', () => {
    const h = setup(), rows = trainRows(h.d), native = [...h.d.querySelectorAll('li._r28,li.example-card')].find(row => row.textContent.includes('Ferrovie dello Stato')), duplicate = native.cloneNode(true), link = duplicate.querySelector('[data-rb-j]'), fields = link.dataset.rbJ.split('|');
    fields[2] = encodeURIComponent('p:b-7-5:1'); link.dataset.rbJ = fields.join('|'); native.after(duplicate); h.install(); assert.equal(visible(rows).length, 3); assert.ok(rows.every(row => !row.dataset.sfGroupMemberIds));
  });
  await test('different sense panels and source metadata remain separate', () => {
    const h = setup(), rows = trainRows(h.d), panel = rows[0].closest('.sf-panel');
    const clone = rows[2].cloneNode(true); clone.dataset.sfOccurrenceId = 'e'.repeat(64); clone.querySelector('.sf-source').textContent += ' ➫ another source'; panel.append(clone);
    const otherSense = h.d.createElement('details'); otherSense.className = 'sf-sense'; const otherPanel = h.d.createElement('div'); otherPanel.className = 'sf-panel'; otherPanel.append(rows[2]); otherSense.append(otherPanel); panel.parentElement.after(otherSense);
    h.install(); assert.equal(visible(rows.slice(0, 2)).length, 1); assert.equal(rows[2].hidden, false); assert.equal(clone.hidden, false); assert.ok(!clone.dataset.sfGroupMemberIds); assert.ok(!rows[2].dataset.sfGroupMemberIds);
  });
  await test('actual original training history and detailed explanation relocate intact to the merged sentence; disposal restores the exact original DOM', () => {
    const h = setup('redbook2027', 'training');
    const row = [...h.d.querySelectorAll('.sf-example')].find(e => e.querySelector(':scope > .sf-ownership-history') && e.querySelector('.sf-en').textContent.includes('AI model training'));
    assert.ok(row); const other = row.cloneNode(true); other.dataset.sfOccurrenceId = 'f'.repeat(64); row.after(other); const original = h.d.documentElement.outerHTML;
    const history = [row, other].map(e => e.querySelector(':scope > .sf-ownership-history')), originals = history.map(e => e.outerHTML); const handle = h.install();
    assert.equal(other.hidden, true); assert.deepEqual(history.map(e => e.outerHTML), originals); assert.ok(history.every(e => e.closest('.sf-group-member-evidence')));
    history.forEach(e => { e.open = true; e.open = false; });
    handle.dispose(); assert.equal(h.d.documentElement.outerHTML, original); const again = h.install(); assert.equal(other.hidden, true); again.dispose(); assert.equal(h.d.documentElement.outerHTML, original);
  });
  process.stdout.write(JSON.stringify({ schema: 'same-sense-display-group-checks.v1', runtime_sha256: hash(runtime), tests: results, passed: results.filter(r => r.passed).length, failed: results.filter(r => !r.passed).length, scope: 'Actual two-book formal source train/training HTML and original card-chunks/sense-frequency scripts; synthetic negative cases isolated in memory; no source or database writes; browser acceptance remains ROOT gate' }, null, 2) + '\n'); process.exitCode = results.some(r => !r.passed) ? 1 : 0;
})();
