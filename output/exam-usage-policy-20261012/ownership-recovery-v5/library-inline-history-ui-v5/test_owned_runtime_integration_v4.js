'use strict';
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto'), assert = require('node:assert/strict');
const { JSDOM, requestInterceptor, VirtualConsole } = require('jsdom');
const own = __dirname, repo = path.resolve(own, '../../../..'), output = path.join(repo, 'output'), origin = 'http://localhost:8771';
const combined = fs.readFileSync(path.join(own, 'library-preview-owned-runtime-v4.js'), 'utf8');
const sourceRoot = path.join(own, '../owner-source-display-v5/final-overlay');
const shellRaw = fs.readFileSync(path.join(sourceRoot, 'redbook/preview-library.html'), 'utf8');
const fullCatalogRaw = fs.readFileSync(path.join(sourceRoot, 'redbook/catalog.json'));
const catalog = JSON.parse(fullCatalogRaw), training = catalog.cards.find(c => c.word === 'training'), train = catalog.cards.find(c => c.word === 'train');
assert.equal(training.id, '50dae402dda20e63b789a8638ed49c6c108eca2005f3f78be68d6e5b70a3c3f5');
const deck = catalog.decks.find(d => d.id === training.deckId);
const micro = { ...catalog, cards: [training, train], decks: [{ ...deck, cardIds: [training.id, train.id], count: 2 }], counts: { cards: 2, decks: 1, examples: training.exampleCount + train.exampleCount } };
// Only in-memory test catalog counts are reconstructed. Real source catalog
// rows, routes, HTML, assets and all production counts remain untouched.
const projectionPath = path.join(output, 'exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json');
const bankPath = path.join(output, 'exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-v5.json');
const hash = x => crypto.createHash('sha256').update(x).digest('hex');
assert.equal(hash(fs.readFileSync(projectionPath)), 'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8');
assert.equal(hash(fs.readFileSync(bankPath)), 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5');
const tests = [];
const live = new Set();
const observedLimitations = [];
function test(name, callback) { tests.push([name, callback]); }
async function until(condition, label, timeout = 10000) { const start = Date.now(); while (!condition()) { if (Date.now() - start > timeout) throw new Error('Timed out: ' + label); await new Promise(r => setTimeout(r, 10)); } }
async function setup(options = {}) {
  const resourceRequests = [], fetchRequests = [], failures = [], loadFailures = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', err => { if (!/navigation/i.test(err.message)) failures.push({message:err.message,stack:err.cause?.stack || err.stack}); });
  const resources = { interceptors: [requestInterceptor(request => {
    resourceRequests.push(request.url); const url = new URL(request.url); if (url.origin !== origin) return new Response('', { status: 404 });
    const local = path.resolve(output, '.' + url.pathname);
    if (!local.startsWith(output + path.sep) || !fs.existsSync(local) || !fs.statSync(local).isFile()) { loadFailures.push(url.pathname); return new Response('', { status: 404 }); }
    return new Response(fs.readFileSync(local), { headers: { 'content-type': local.endsWith('.js') ? 'application/javascript' : local.endsWith('.css') ? 'text/css' : 'text/html' } });
  })] };
  const dom = new JSDOM(shellRaw, { url: origin + '/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/runtime-candidate-overlay-v4/redbook/preview-library.html#card=' + (options.startCard || training).id, runScripts: 'outside-only', resources, virtualConsole: vc });
  live.add(dom);
  const w = dom.window, d = w.document; Object.defineProperty(w, 'crypto', { value: crypto.webcrypto }); w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  w.fetch = async (value, init) => {
    const url = new URL(value, w.location.href); fetchRequests.push(url.href);
    assert.equal(url.origin, origin); let bytes;
    if (url.pathname.endsWith('/redbook/catalog.json')) return { ok: true, url: url.href, json: async () => micro };
    if (url.pathname.endsWith('/projection.json')) {
      if (options.failProjectionOnce && fetchRequests.filter(x => x.endsWith('/projection.json')).length === 1) throw new Error('test transient projection unavailable');
      if (options.delayProjection) await options.delayProjection;
      bytes = fs.readFileSync(projectionPath);
    } else if (url.pathname.endsWith('/shared-reading-bank-v5.json')) bytes = fs.readFileSync(bankPath);
    else { const file = path.resolve(output, '.' + url.pathname); assert.ok(file.startsWith(output + path.sep)); if (url.pathname.includes('/history/') && options.delayHistory) await options.delayHistory; bytes = fs.readFileSync(file); }
    if (init.redirect) assert.equal(init.redirect, 'error');
    return { ok: true, url: url.href, redirected: false, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length), text: async () => bytes.toString() };
  };
  // Test-only API wrappers observe real integration ordering without editing
  // any production helper or replacing its DOM behavior.
  const runtimeTrace = [], fineReady = new WeakSet(), bankReady = new WeakSet();
  for (const [global, kind] of [['AnkiReviewedChunkProjection', 'fine'], ['AnkiSharedReadingBankRuntime', 'bank'], ['AnkiSameSenseGroupRuntime', 'group']]) {
    let api;
    Object.defineProperty(w, global, { configurable: true, get() { return api; }, set(value) {
      api = Object.assign({}, value, { install(doc, ...args) {
        if (kind === 'group') {
          assert.ok(fineReady.has(doc), 'group follows successful fine install');
          assert.ok(bankReady.has(doc), 'group follows bank ready');
          assert.equal(d.getElementById('card-frame').contentDocument, doc, 'group belongs to current iframe');
        }
        runtimeTrace.push({ kind, phase: 'install', doc });
        const handle = value.install(doc, ...args);
        if (kind === 'fine') fineReady.add(doc);
        const wrapped = Object.assign({}, handle, { dispose() {
          runtimeTrace.push({ kind, phase: 'dispose', doc });
          if (kind === 'fine') fineReady.delete(doc);
          if (kind === 'bank') bankReady.delete(doc);
          return handle.dispose();
        } });
        if (kind === 'bank') wrapped.ready = handle.ready.then(result => { bankReady.add(doc); return result; });
        return wrapped;
      } });
    } });
  }
  w.eval(combined);
  await until(() => d.getElementById('card-frame')?.contentDocument?.getElementById('preview-flip'), 'actual source card frame parsed');
  // outside-only controls parent execution; execute the exact child scripts in
  // document order against their actual preserved asset URLs and source bytes.
  const child = d.getElementById('card-frame').contentWindow; child.PointerEvent = undefined;
  // JSDOM has no layout ResizeObserver. This no-op shim only permits the
  // unchanged card's resize notification script; layout/browser stays ROOT's gate.
  child.ResizeObserver = class { observe() {} disconnect() {} unobserve() {} };
  for (const script of Array.from(child.document.scripts)) {
    if (script.src) {
      const file = path.resolve(output, '.' + new URL(script.src).pathname); assert.ok(file.startsWith(output + path.sep)); if (fs.existsSync(file)) child.eval(fs.readFileSync(file, 'utf8')); else loadFailures.push(new URL(script.src).pathname);
    } else if (!script.type || /javascript/.test(script.type)) child.eval(script.textContent);
  }
  return { dom, w, d, child, runtimeTrace, fetchRequests, resourceRequests, failures, loadFailures, frame: () => d.getElementById('card-frame'), async ready() { await until(() => this.frame()?.dataset.ownedRuntimeState === 'ready', 'owned runtime ready'); }, close() { dom.window.close(); } };
}

test('actual training iframe full source HTML/resources: precise Space guard, fine tap/reverse, old history stays inline, original owner navigation ready', async () => {
  const h = await setup(); await h.ready(); let frame = h.frame(), cd = frame.contentDocument, child = frame.contentWindow;
  assert.equal(cd.URL, origin + training.previewUrl); assert.equal(frame.hidden, false); assert.equal(h.d.getElementById('flip-card').disabled, false);
  const target = Array.from(cd.querySelectorAll('.example-text mark.target-word [data-reviewed-chunk-projection]')).find(e => e.textContent === 'training' && e.title === 'AI model training ↔ 模型训练'); assert.ok(target);
  const before = cd.getElementById('preview-flip').getAttribute('aria-pressed'); target.focus(); target.dispatchEvent(new child.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }));
  assert.equal(cd.getElementById('preview-flip').getAttribute('aria-pressed'), before, 'fine Space never flips');
  assert.equal(Array.from(target.closest('.example-card').querySelectorAll('.card-chunk-active'), e => e.textContent).join(''), 'AI model training模型训练');
  target.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); assert.equal(cd.querySelector('.example-text .card-chunk-active'), null);
  h.d.getElementById('flip-card').click(); assert.equal(cd.getElementById('preview-flip').getAttribute('aria-pressed'), 'true'); h.d.getElementById('flip-card').click(); assert.equal(cd.getElementById('preview-flip').getAttribute('aria-pressed'), 'false');
  const history = target.closest('.example-card').querySelector('.sf-original-history-link'); history.click(); await until(() => target.closest('.example-card').querySelector('.sf-inline-history .sf-archived-example'), 'full old record inline');
  assert.equal(cd.URL, origin + training.previewUrl); assert.equal(frame.hidden, false);
  assert.deepEqual(h.failures, [], 'no errors before original-owner navigation');
  const owner = Array.from(target.closest('.example-card').querySelectorAll('.sf-ownership-history a')).find(a => a.href === origin + train.previewUrl && !a.classList.contains('sf-original-history-link')); assert.ok(owner); owner.click();
  await until(() => h.frame()?.contentDocument?.URL === origin + train.previewUrl && h.frame().dataset.ownedRuntimeState === 'ready', 'exact owner selectCard ready');
  assert.ok(!h.d.getElementById('card-error').textContent); assert.equal(h.d.querySelectorAll('.owned-runtime-status').length, 1);
  assert.ok(h.fetchRequests.filter(u => u.endsWith('/projection.json')).length === 1, 'projection fetched once per shell'); assert.ok(h.fetchRequests.filter(u => u.endsWith('/shared-reading-bank-v5.json')).length === 1, 'bank fetched once per shell');
  // After removal, JSDOM destroys the child window's global document while
  // two unchanged original child-asset MutationObservers still have queued
  // callbacks. These are explicitly recorded, not silently suppressed or
  // counted as real-browser acceptance. New parent-owned helpers are disposed.
  assert.ok(h.failures.every(error =>
    /Cannot read properties of undefined \(reading '(documentElement|querySelectorAll)'\)/.test(error.message) &&
    /at (ownsHost|MutationObserver\.refresh)/.test(error.stack) && /eval at setup/.test(error.stack)), 'unexpected error outside known original-child detached-window limitation');
  if (h.failures.length) observedLimitations.push({ phase:'after actual original-owner navigation removes old child frame', type:'jsdom-clears-detached-child-global-document', errors:h.failures, production_source_changed:false, browser_gate_owner:'/root' });
  assert.deepEqual(h.loadFailures, []); h.close();
});
test('transient projection failure has local ARIA retry and retry preserves strict frame ready/flip state', async () => {
  const h = await setup({ failProjectionOnce: true }); await until(() => h.frame().dataset.ownedRuntimeState === 'failed', 'local runtime failure');
  assert.equal(h.frame().hidden, false); assert.equal(h.d.getElementById('flip-card').disabled, false); const status = h.d.querySelector('.owned-runtime-status'); assert.equal(status.getAttribute('role'), 'status'); assert.equal(status.getAttribute('aria-busy'), 'false');
  status.querySelector('button').click(); await h.ready(); assert.equal(h.frame().contentDocument.URL, origin + training.previewUrl); assert.equal(h.d.getElementById('card-failure').hidden, true); assert.equal(h.fetchRequests.filter(u => u.endsWith('/projection.json')).length, 2); h.close();
});
test('disposed old iframe never receives async projection/bank, next frame shares once-loaded sidecars', async () => {
  let release; const delayed = new Promise(r => release = r); const h = await setup({ delayProjection: delayed }); const old = h.frame(), oldDoc = old.contentDocument;
  h.d.getElementById('word-search').value = 'train'; h.d.getElementById('word-search').dispatchEvent(new h.w.Event('input', { bubbles: true }));
  await until(() => h.frame() !== old, 'old frame disposed'); release(); await h.ready();
  assert.equal(oldDoc.querySelector('[data-reviewed-chunk-projection]'), null); assert.equal(h.frame().contentDocument.URL, origin + train.previewUrl); assert.equal(h.d.querySelectorAll('.owned-runtime-status').length, 1); assert.equal(h.fetchRequests.filter(u => u.endsWith('/projection.json')).length, 1); h.close();
});
test('actual formal training SF report capture listener: Enter/Space each synthesize one click and never flip the iframe', async () => {
  const h = await setup(); await h.ready(); const frame = h.frame(), d = frame.contentDocument, child = frame.contentWindow;
  assert.equal(child.__ankiSenseFrequencyBound, true, 'actual unchanged sense-frequency.js executes in source card');
  const target = Array.from(d.querySelectorAll('.sf-report .sf-en mark.target-word [data-reviewed-chunk-projection]')).find(el => el.textContent === 'training' && el.title === 'AI model training ↔ 模型训练'); assert.ok(target, 'actual reviewed Q34D SF target present');
  const root = target.closest('.example-card'), flip = d.getElementById('preview-flip'), before = flip.getAttribute('aria-pressed'); let clicks = 0;
  d.addEventListener('click', () => clicks++, true); target.focus();
  target.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); assert.equal(clicks, 1); assert.equal(flip.getAttribute('aria-pressed'), before);
  assert.equal(Array.from(root.querySelectorAll('.card-chunk-active'), el => el.textContent).join(''), 'AI model training模型训练');
  target.dispatchEvent(new child.KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })); assert.equal(clicks, 2); assert.equal(root.querySelector('.card-chunk-active'), null); assert.equal(flip.getAttribute('aria-pressed'), before);
  target.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); target.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); assert.equal(root.querySelector('.card-chunk-active'), null); assert.equal(clicks, 3); assert.equal(flip.getAttribute('aria-pressed'), before); h.close();
});

test('actual train iframe groups three same-sense physical tokens once after fine/bank ready; retry and disposal reverse order without count or chunk loss', async () => {
  const h = await setup({ startCard: train }); await h.ready(); const frame = h.frame(), d = frame.contentDocument, child = frame.contentWindow;
  const rows = Array.from(d.querySelectorAll('.sf-example')).filter(row => row.querySelector(':scope > .sf-sentence-pair > .sf-en')?.textContent.startsWith('Ferrovie dello Stato Italiane'));
  assert.equal(rows.length, 3); assert.equal(rows.filter(row => !row.hidden).length, 1); assert.equal(rows[0].dataset.sfGroupOccurrences, '3');
  assert.deepEqual(JSON.parse(rows[0].dataset.sfGroupMemberIds), rows.map(row => row.dataset.sfOccurrenceId));
  const panel = rows[0].closest('.sf-panel'), count = panel.parentElement.querySelector('.sf-count').textContent, filters = Array.from(panel.querySelectorAll('[data-sf-filter]'), el => el.textContent);
  const pair = rows[0].querySelector(':scope > .sf-sentence-pair'), english = pair.querySelector('.sf-en').textContent, chinese = pair.querySelector('.sf-zh').textContent;
  assert.deepEqual(Array.from(pair.querySelectorAll('mark.target-word'), el => el.textContent), ['train', 'train', 'trains']);
  assert.equal(rows[0].querySelectorAll('.sf-group-member-evidence').length, 3);
  for (const id of ['2', '3', '6']) {
    const en = Array.from(pair.querySelectorAll('.sf-en .card-chunk')).find(el => el.dataset.chunkIds === id), zh = Array.from(pair.querySelectorAll('.sf-zh .card-chunk')).find(el => el.dataset.chunkIds === id);
    en.dispatchEvent(new child.MouseEvent('click', { bubbles: true, cancelable: true })); assert.ok(zh.classList.contains('card-chunk-active'));
    en.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    zh.dispatchEvent(new child.MouseEvent('click', { bubbles: true, cancelable: true })); assert.ok(en.classList.contains('card-chunk-active'));
    zh.dispatchEvent(new child.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  }
  // Exercise the existing retry lifecycle on a successfully installed group.
  // The button is deliberately hidden; direct test click calls the same run()
  // used by visible failure retry, without adding a production test hook.
  const checkpoint = h.runtimeTrace.length; h.d.querySelector('.owned-runtime-status button').dispatchEvent(new h.w.MouseEvent('click', { bubbles: true })); await h.ready();
  assert.deepEqual(h.runtimeTrace.slice(checkpoint, checkpoint + 3).map(e => e.kind + ':' + e.phase), ['group:dispose', 'bank:dispose', 'fine:dispose']);
  assert.equal(rows.filter(row => !row.hidden).length, 1); assert.equal(rows[0].querySelectorAll('.sf-group-evidence').length, 1);
  assert.equal(panel.parentElement.querySelector('.sf-count').textContent, count); assert.deepEqual(Array.from(panel.querySelectorAll('[data-sf-filter]'), el => el.textContent), filters);
  assert.equal(pair.querySelector('.sf-en').textContent, english); assert.equal(pair.querySelector('.sf-zh').textContent, chinese);
  panel.querySelector('[data-sf-filter="2026"]').click(); assert.equal(rows.filter(row => !row.hidden).length, 1);
  panel.querySelector('[data-sf-filter="all"]').click(); assert.equal(rows.filter(row => !row.hidden).length, 1);
  const beforeNav = h.runtimeTrace.length; h.d.getElementById('word-search').value = 'training'; h.d.getElementById('word-search').dispatchEvent(new h.w.Event('input', { bubbles: true }));
  await until(() => h.frame() !== frame, 'group frame disposed on card navigation'); await h.ready();
  assert.deepEqual(h.runtimeTrace.slice(beforeNav, beforeNav + 3).map(e => e.kind + ':' + e.phase), ['group:dispose', 'bank:dispose', 'fine:dispose']);
  assert.equal(d.querySelector('.sf-group-evidence'), null); assert.equal(d.querySelector('[data-sf-group-occurrences]'), null);
  assert.ok(h.runtimeTrace.filter(e => e.kind === 'group' && e.phase === 'install').every(e => e.doc === d || e.doc === h.frame().contentDocument));
  assert.equal(h.fetchRequests.filter(u => u.endsWith('/projection.json')).length, 1); assert.equal(h.fetchRequests.filter(u => u.endsWith('/shared-reading-bank-v5.json')).length, 1);
  assert.deepEqual(h.loadFailures, []); h.close();
});

test('actual SF history record moved into group loads exactly one complete archived record and HTML evidence; exact owner link navigates and capture cleanup matches', async () => {
  let release; const delayed = new Promise(resolve => release = resolve); const h = await setup({ delayProjection: delayed }), frame = h.frame(), d = frame.contentDocument;
  const link = Array.from(d.querySelectorAll('.sf-report .sf-ownership-history .sf-original-history-link')).find(el => el.closest('.sf-example')?.querySelector('.sf-en')?.textContent.includes('AI model training'));
  assert.ok(link, 'actual Q34D SF old history link exists');
  const row = link.closest('.sf-example'), details = link.closest('.sf-ownership-history'), clone = row.cloneNode(true); clone.dataset.sfOccurrenceId = 'f'.repeat(64); row.after(clone);
  // The isolated in-memory duplicate activates the grouping relocation branch.
  // All original actual history fields/record and physical source stay exact;
  // this is not a claim that production has a fourth reviewed occurrence.
  const sourceDetails = details.outerHTML; release(); await h.ready(); assert.ok(details.closest('.sf-group-member-evidence')); assert.equal(details.outerHTML, sourceDetails);
  const removed = [], originalRemove = d.removeEventListener.bind(d); d.removeEventListener = (type, callback, capture) => { removed.push({ type, name:callback.name, capture }); return originalRemove(type, callback, capture); };
  row.querySelector('.sf-group-evidence').open = true; details.open = true; link.click();
  await until(() => details.querySelector('.sf-inline-history .sf-archived-example'), 'actual grouped SF full old record inline');
  link.click(); const archiveURL = link.href; assert.equal(h.fetchRequests.filter(url => url === archiveURL).length, 1, 'loaded record is reused without duplicate fetch');
  const archivedDoc = new JSDOM(fs.readFileSync(path.resolve(output, '.' + new URL(archiveURL).pathname), 'utf8')).window.document;
  const expectedReason = details.querySelector(':scope > .sf-history-old-reason').textContent.slice('原审核完整说明：'.length);
  const expected = Array.from(archivedDoc.querySelectorAll('.sf-archived-example')).filter(article => article.querySelector(':scope > .sf-reason')?.textContent === '义项依据：' + expectedReason); assert.equal(expected.length, 1);
  const loaded = details.querySelector('.sf-inline-history .sf-archived-example');
  assert.equal(loaded.querySelector('.sf-en').textContent, expected[0].querySelector('.sf-en').textContent); assert.equal(loaded.querySelector('.sf-zh').textContent, expected[0].querySelector('.sf-zh').textContent);
  assert.equal(loaded.querySelector('.sf-source').textContent, expected[0].querySelector('.sf-source').textContent); assert.equal(loaded.querySelector('.sf-reason').textContent, expected[0].querySelector('.sf-reason').textContent);
  assert.equal(loaded.querySelector('mark.target-word').textContent, expected[0].querySelector('mark.target-word').textContent);
  assert.deepEqual(Array.from(loaded.querySelectorAll('.card-chunk'), el => [el.textContent, el.dataset.chunkSide, el.dataset.chunkIds]), Array.from(expected[0].querySelectorAll('.card-chunk'), el => [el.textContent, el.dataset.chunkSide, el.dataset.chunkIds]));
  const evidence = Array.from(archivedDoc.querySelectorAll('details')).find(el => el.querySelector(':scope > summary')?.textContent.replace(/\s/g, '') === '完整原HTML证据').querySelector(':scope > pre').textContent;
  assert.equal(details.querySelector('.sf-inline-history details > pre').textContent, evidence); archivedDoc.defaultView.close();
  assert.equal(d.URL, origin + training.previewUrl); assert.equal(frame.hidden, false);
  const owner = Array.from(details.querySelectorAll('a[href]')).find(el => el.href === origin + train.previewUrl && !el.classList.contains('sf-original-history-link')); assert.ok(owner); owner.click();
  await until(() => h.frame() !== frame && h.frame().dataset.ownedRuntimeState === 'ready', 'grouped SF exact owner selectCard');
  assert.equal(h.frame().contentDocument.URL, origin + train.previewUrl); assert.equal(h.d.getElementById('card-failure').hidden, true);
  assert.deepEqual(removed.filter(e => e.type === 'click' && e.name === 'click').map(e => e.capture), [true]);
  assert.deepEqual(h.loadFailures, []); h.close();
});

test('grouped SF pending history is aborted and never writes stale document after exact owner navigation', async () => {
  let releaseProjection, releaseHistory; const projectionDelay = new Promise(resolve => releaseProjection = resolve), historyDelay = new Promise(resolve => releaseHistory = resolve);
  const h = await setup({ delayProjection: projectionDelay, delayHistory: historyDelay }), frame = h.frame(), d = frame.contentDocument;
  const link = Array.from(d.querySelectorAll('.sf-report .sf-ownership-history .sf-original-history-link')).find(el => el.closest('.sf-example')?.querySelector('.sf-en')?.textContent.includes('AI model training')); assert.ok(link);
  const row = link.closest('.sf-example'), details = link.closest('.sf-ownership-history'), clone = row.cloneNode(true); clone.dataset.sfOccurrenceId = 'e'.repeat(64); row.after(clone); releaseProjection(); await h.ready();
  assert.ok(details.closest('.sf-group-member-evidence')); link.click(); assert.equal(h.fetchRequests.filter(url => url === link.href).length, 1);
  const owner = Array.from(details.querySelectorAll('a[href]')).find(el => el.href === origin + train.previewUrl && !el.classList.contains('sf-original-history-link')); assert.ok(owner); owner.click();
  await until(() => h.frame() !== frame, 'pending grouped history frame disposed'); releaseHistory(); await h.ready(); await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(details.querySelector('.sf-inline-history .sf-archived-example'), null); assert.equal(h.frame().contentDocument.URL, origin + train.previewUrl); assert.equal(h.frame().hidden, false); h.close();
});

(async () => {
  const results=[];
  for (const [name, run] of tests) { try { await run(); results.push({name,passed:true}); } catch(error) {results.push({name,passed:false,error:error.stack});} finally { for (const dom of live) dom.window.close(); live.clear(); } }
  process.stdout.write(JSON.stringify({schema:'library-owned-runtime-integration-checks.v4',tests:results,passed:results.filter(r=>r.passed).length,failed:results.filter(r=>!r.passed).length,observedLimitations,combined_sha256:hash(combined),source_catalog_sha256:hash(fullCatalogRaw),scope:'Exact source3 training/train rows in memory microcatalog; actual original source HTML/asset paths; no card/catalog/DB writes; JSDOM iframe, not browser acceptance',production_applied:false},null,2)+'\n');process.exitCode=results.some(r=>!r.passed)?1:0;
})();
