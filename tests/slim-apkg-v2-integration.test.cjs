const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { JSDOM } = require('jsdom');
const sha = x => crypto.createHash('sha256').update(x).digest('hex');
const runtime = fs.readFileSync('anki_pipeline/templates/slim-apkg-v2.js', 'utf8');
const codec = fs.readFileSync('anki_pipeline/templates/slim-shared-codec.js', 'utf8');
const releasedV2 = fs.readFileSync('tests/fixtures/experimental-compiled-card-v1/native/original-slim.js', 'utf8');
assert.equal(sha(releasedV2), '17b5c61a67f0efa96251065352361c0c8afadb61a417a3c2ed5bb611006ec0d7');

function fixture(t, data, { corrupt = false, oldLiteral = false, startLegacy = false, delay = 0 } = {}) {
  const raw = JSON.stringify(data), pin = sha(raw), logical = '_as_' + pin.slice(0,24) + '.js';
  const bankRaw = JSON.stringify({schema:'anki-slim-shared-dictionary.v1',strings:[raw]});
  const bankPin = sha(bankRaw), bankName = '_as_' + bankPin.slice(0,24) + '.js';
  const bank = {src:bankName,sha256:bankPin,literal:true};
  const packed = {schema:'anki-slim-shared-strings.v1',dict:bank,pieces:[0]};
  const html = '<h1>original front</h1><script class="anki-final-reviewed-data" data-as-src="'+logical+'" data-as-sha="'+pin+'"></script>';
  const dom = new JSDOM(html,{url:'http://127.0.0.1/',runScripts:'outside-only'}); t.after(()=>dom.window.close());
  const w=dom.window, doc=w.document, requests=[], seen=[];
  w.TextEncoder=TextEncoder; Object.defineProperty(w.crypto,'subtle',{value:crypto.webcrypto.subtle});
  w.AnkiSlimAssets={};
  const media = new Map([[bankName,{pin:bankPin,value:corrupt ? bankRaw+'tampered':bankRaw}],
    [oldLiteral ? logical:logical.replace('_as_','_ac_'),{pin,value:oldLiteral ? raw:packed}]]);
  const append=doc.head.append.bind(doc.head);
  doc.head.append=(node)=>{ append(node); const name=node.getAttribute('src'); requests.push(name);
    w.setTimeout(()=>{const a=media.get(name); if(!a){node.onerror();return;} w.AnkiSlimAssets[a.pin]=a.value;node.onload();},delay); };
  const handle=()=>({refresh(){return Promise.resolve();},stats(){return{errors:[]};},dispose(){}});
  w.AnkiFineChunkRuntime={install:handle};
  w.AnkiReviewedChunkProjection={prepare:async d=>{seen.push(d);return d;},install:handle};
  w.AnkiSharedReadingBankRuntime={install:()=>({...handle(),ready:Promise.resolve()})};
  w.AnkiSameSenseGroupRuntime={install:handle}; w.AnkiResidualReviewedChunkRuntime={install:handle};
  w.eval(codec);w.eval(startLegacy ? fs.readFileSync('anki_pipeline/templates/slim-apkg.js','utf8'):runtime);
  return {w,doc,requests,seen,logical,bankName};
}

test('packed payload uses verified shared bank and original bytes without normal visible loading UI', async t=>{
  const f=fixture(t,{word:'train',explanation:'火车 & 原文',as_native_index:[]});
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script').dataset.nativeState,'ready');
  assert.equal(f.seen[0].word,'train'); assert.equal(f.seen[0].explanation,'火车 & 原文');
  assert.deepEqual(f.requests,[f.logical.replace('_as_','_ac_'),f.bankName]);
  assert.equal(f.doc.querySelector('.anki-final-status'),null);
  assert.equal(f.doc.querySelector('h1').textContent,'original front');
});

test('corrupt shared bank fails before projection or content mutation',async t=>{
  const f=fixture(t,{as_native_index:[]},{corrupt:true});
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script').dataset.nativeState,'failed');
  assert.equal(f.seen.length,0); assert.equal(f.doc.querySelector('h1').textContent,'original front');
  assert.match(f.doc.querySelector('.anki-final-status').textContent,/校验失败/);
});

test('mixed profile can load an earlier literal without overwriting its media filename',async t=>{
  const f=fixture(t,{as_native_index:[],legacy:true},{oldLiteral:true});
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script').dataset.nativeState,'ready');
  assert.equal(f.seen[0].legacy,true);
  assert.deepEqual(f.requests,[f.logical.replace('_as_','_ac_'),f.logical]);
});

test('actual V1 in-flight hydration is disposed before V2 takes over the next card',async t=>{
  const f=fixture(t,{as_native_index:[],oldCard:true},{oldLiteral:true,startLegacy:true,delay:40});
  const prior=f.w.AnkiSlimApkgHydrate();
  assert.equal(f.requests.length,1);
  f.doc.body.innerHTML='<h1>next card</h1><script class="anki-final-reviewed-data">{"as_native_index":[],"nextCard":true}</script>';
  f.w.eval(runtime);
  await f.w.AnkiSlimApkgHydrate(); await prior;
  assert.equal(f.w.__AnkiSlimStorageVersion,'shared-v2');
  assert.equal(f.doc.querySelector('h1').textContent,'next card');
  assert.equal(f.doc.querySelector('script').dataset.nativeState,'ready');
  assert.equal(f.seen.length,1); assert.equal(f.seen[0].nextCard,true);
});

function examplesFixture(t, { total = 31, closed = false, failedPart = -1,
  missingPart = -1, delay = 0, intersectImmediately = false, runtimeSource = runtime } = {}) {
  const row = n => '<li class="example-card" data-row="' + n + '"><p class="example-text">原句 ' + n +
    '</p><p class="example-translation">原译 ' + n + '</p></li>';
  const assets = new Map(), parts = [];
  for (let n = 10; n < total; n += 10) {
    const raw = Array.from({ length: Math.min(10, total - n) }, (_, k) => row(n + k)).join('');
    const pin = sha(raw), src = '_as_' + pin.slice(0, 24) + '.js';
    parts.push({ src, sha256: pin, count: Math.min(10, total - n) });
    if (parts.length - 1 !== missingPart) assets.set(src, { pin,
      raw: parts.length - 1 === failedPart ? raw + 'corrupt' : raw });
  }
  const manifest = JSON.stringify({ schema: 'anki-slim-segments.v1', parts, total: total - 10 });
  const list = '<ol class="examples">' + Array.from({ length: 10 }, (_, n) => row(n)).join('') +
    '<li class="as-lazy" data-as-kind="examples"><script type="application/json" class="as-manifest">' +
    manifest + '</script></li></ol>';
  const body = (closed ? '<details id="outer"><summary>原例句</summary>' + list + '</details>' : list) +
    '<script class="anki-final-reviewed-data">{"as_native_index":[]}</script>';
  const dom = new JSDOM(body, { url: 'http://127.0.0.1/', runScripts: 'outside-only' });
  t.after(() => dom.window.close());
  const w = dom.window, doc = w.document, requests = [], release = [];
  w.TextEncoder = TextEncoder;
  Object.defineProperty(w.crypto, 'subtle', { value: crypto.webcrypto.subtle });
  w.AnkiSlimAssets = {};
  const append = doc.head.append.bind(doc.head);
  doc.head.append = node => {
    append(node); const name = node.getAttribute('src'); requests.push(name);
    const respond = () => {
      const asset = assets.get(name.replace(/^_ac_/, '_as_'));
      if (!asset) { node.onerror(); return; }
      w.AnkiSlimAssets[asset.pin] = asset.raw; node.onload();
    };
    if (delay === 'held') release.push(respond); else w.setTimeout(respond, delay);
  };
  let disposed = 0;
  const handle = () => ({ refresh() { return Promise.resolve(); }, stats() { return { errors: [] }; }, dispose() { disposed++; } });
  w.AnkiFineChunkRuntime = { install: handle };
  w.AnkiReviewedChunkProjection = { prepare: async data => data, install: handle };
  w.AnkiSharedReadingBankRuntime = { install: () => ({ ...handle(), ready: Promise.resolve() }) };
  w.AnkiSameSenseGroupRuntime = { install: handle };
  w.AnkiResidualReviewedChunkRuntime = { install: handle };
  if (intersectImmediately) w.IntersectionObserver = class {
    constructor(callback) { this.callback = callback; }
    observe(target) { this.callback([{ target, isIntersecting: true }]); }
    disconnect() {}
  };
  w.eval(runtimeSource);
  return { w, doc, requests, parts, release, row, disposed: () => disposed };
}

for (const total of [11, 31]) test('V2 initial hydration completes all ' + total + ' ordinary examples without scrolling', async t => {
  const f = examplesFixture(t, { total });
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 10);
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
  assert.deepEqual([...f.doc.querySelectorAll('li.example-card')].map(n => n.dataset.row),
    Array.from({ length: total }, (_, n) => String(n)));
  assert.deepEqual([...f.doc.querySelectorAll('li.example-card')].map(n => n.outerHTML),
    Array.from({ length: total }, (_, n) => f.row(n)));
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asLoadedParts, String(f.parts.length));
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asState, 'ready');
  assert.equal(f.requests.length, f.parts.length);
  assert.equal(f.w.AnkiSlimBatching, 0);
});

test('V2 completes ordinary examples inside a closed outer detail without opening it or loading audits/senses', async t => {
  const f = examplesFixture(t, { closed: true });
  const blocked = JSON.stringify({ schema: 'anki-slim-segments.v1', parts: [
    { src: '_as_' + 'a'.repeat(24) + '.js', sha256: 'a'.repeat(64), count: 1 }], total: 1 });
  f.doc.body.insertAdjacentHTML('beforeend', '<details class="sf-sense"><summary>原义项</summary><div class="sf-panel">' +
    '<div class="as-lazy" data-as-kind="sense"><script class="as-manifest">' + blocked + '</script></div></div></details>' +
    '<details class="sf-ownership-history"><summary>原审核</summary><div class="as-lazy" data-as-kind="detail">' +
    '<script class="as-manifest">' + blocked + '</script></div></details>');
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 31);
  assert.ok([...f.doc.querySelectorAll('details')].every(n => !n.open));
  assert.equal(f.requests.length, f.parts.length, 'closed sense/audit media stay deferred');
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
});

for (const failure of ['failedPart', 'missingPart']) test('V2 ' + failure + ' leaves native failed instead of accepting partial ordinary examples', async t => {
  const f = examplesFixture(t, { [failure]: 1 });
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 20, 'first verified part stays intact');
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asLoadedParts, '1');
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asState, 'failed');
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'failed');
  assert.match(f.doc.querySelector('.anki-final-status').textContent, failure === 'failedPart' ? /校验失败/ : /无法载入/);
  assert.equal(f.w.AnkiSlimBatching, 0);
});

test('V2 initial all-parts request drains a preceding observer single-part request exactly once', async t => {
  const f = examplesFixture(t, { intersectImmediately: true });
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 31);
  assert.equal(f.requests.length, f.parts.length);
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asState, 'ready');
});

test('V2 dispose during complete ordinary loading cannot append old rows or mark a new card ready', async t => {
  const f = examplesFixture(t, { delay: 'held' });
  const payload = f.doc.querySelector('script.anki-final-reviewed-data');
  const pending = f.w.AnkiSlimApkgHydrate();
  for (let n = 0; n < 20 && !f.release.length; n++) await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.release.length, 1);
  f.w.AnkiSlimApkgDispose();
  f.doc.body.innerHTML = '<h1>next owner</h1><script class="anki-final-reviewed-data">{}</script>';
  f.release.shift()(); await pending;
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 0);
  assert.equal(payload.dataset.nativeState, 'loading', 'the cancelled owner never publishes ready');
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, undefined);
  assert.equal(f.requests.length, 1);
  assert.equal(f.w.AnkiSlimBatching, 0);
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
});

async function drainHeld(f, pending) {
  let done = false;
  const complete = pending.finally(() => { done = true; });
  for (let n = 0; n < 100 && !done; n++) {
    while (f.release.length) f.release.shift()();
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  assert.ok(done, 'bounded fake-media hydration must finish');
  await complete;
}

test('released V2 upgrades to complete-example V2 and retires its old ready signal before loading', async t => {
  const f = examplesFixture(t, { runtimeSource: releasedV2, delay: 'held' });
  await f.w.AnkiSlimApkgHydrate();
  const oldHydrate = f.w.AnkiSlimApkgHydrate;
  const payload = f.doc.querySelector('script.anki-final-reviewed-data');
  assert.equal(payload.dataset.nativeState, 'ready');
  assert.equal(f.requests.length, 0);
  f.w.eval(runtime);
  assert.notEqual(f.w.AnkiSlimApkgHydrate, oldHydrate);
  assert.equal(f.disposed(), 5, 'the old five semantic handles are disposed once');
  assert.equal(f.w.__AnkiSlimStorageVersion, 'shared-v2');
  const capability = Object.getOwnPropertyDescriptor(f.w.AnkiSlimApkgHydrate, 'completeExamplesOnHydrate');
  assert.equal(capability.value, true);
  assert.equal(capability.writable, false);
  assert.equal(capability.configurable, false);
  const pending = f.w.AnkiSlimApkgHydrate();
  assert.equal(payload.dataset.nativeState, 'loading', 'an earlier ready must not authenticate this hydration');
  await drainHeld(f, pending);
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 31);
  assert.equal(payload.dataset.nativeState, 'ready');
});

test('released V2 arriving after the new V2 cannot downgrade it or dispose its current handles', async t => {
  const f = examplesFixture(t);
  await f.w.AnkiSlimApkgHydrate();
  const currentHydrate = f.w.AnkiSlimApkgHydrate, generation = f.w.__ankiFinalApkgGeneration;
  const count = f.requests.length, disposed = f.disposed();
  f.w.eval(releasedV2);
  assert.equal(f.w.AnkiSlimApkgHydrate, currentHydrate);
  assert.equal(f.w.__ankiFinalApkgGeneration, generation);
  assert.equal(f.disposed(), disposed);
  assert.equal(f.requests.length, count);
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 31);
});

test('repeated new V2 during loading is idempotent without cancelling or duplicating its owner', async t => {
  const f = examplesFixture(t, { delay: 'held' });
  const pending = f.w.AnkiSlimApkgHydrate();
  const currentHydrate = f.w.AnkiSlimApkgHydrate, generation = f.w.__ankiFinalApkgGeneration;
  f.w.eval(runtime);
  assert.equal(f.w.AnkiSlimApkgHydrate, currentHydrate);
  assert.equal(f.w.__ankiFinalApkgGeneration, generation);
  assert.equal(f.disposed(), 0);
  await drainHeld(f, pending);
  assert.equal(f.doc.querySelectorAll('li.example-card').length, 31);
  assert.equal(f.requests.length, 3);
});

test('upgrading an in-flight released V2 cancels its old insertion and completes only the new owner', async t => {
  const f = examplesFixture(t, { runtimeSource: releasedV2, delay: 'held', intersectImmediately: true });
  await f.w.AnkiSlimApkgHydrate();
  assert.equal(f.release.length, 1, 'the old observer started exactly one part');
  const oldResponse = f.release.shift();
  f.w.eval(runtime);
  assert.equal(f.disposed(), 5);
  const pending = f.w.AnkiSlimApkgHydrate();
  oldResponse();
  await drainHeld(f, pending);
  assert.deepEqual([...f.doc.querySelectorAll('li.example-card')].map(n => n.dataset.row),
    Array.from({ length: 31 }, (_, n) => String(n)));
  assert.equal(f.doc.querySelector('.as-manifest').dataset.asLoadedParts, '3');
  assert.equal(f.doc.querySelector('script.anki-final-reviewed-data').dataset.nativeState, 'ready');
  assert.equal(f.w.AnkiSlimBatching, 0);
});
