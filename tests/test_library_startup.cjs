const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const backup = path.join(root, 'output/library-startup-20261014/before-library-preview.js');
const fullPreview = path.join(root, 'output/eleven-resolution-20261014/preview-own/final-v2');
const projectionPath = path.join(root,
  'output/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json');
// A source-only checkout intentionally has none of this full-book fixture.
// A partially present fixture must still fail on its missing/invalid declared
// dependencies; do not turn broken local evidence into a successful skip.
const hasPrivateFixture = [backup, fullPreview, projectionPath].some(file => fs.existsSync(file));
const privateFixture = {skip: !hasPrivateFixture && 'Private full-book startup fixture is not in this checkout'};
let runtime, projection;
if (hasPrivateFixture) {
  const frozen = fs.existsSync(backup) ? backup : path.join(fullPreview, 'assets/library-preview.js');
  const original = fs.readFileSync(frozen, 'utf8');
  runtime = process.env.STARTUP_BASELINE ? original : execFileSync('python3',
    [path.join(root, 'scripts/optimize_library_startup.py'), frozen], {maxBuffer: 2e6}).toString();
  projection = JSON.parse(fs.readFileSync(projectionPath));
}
const digest = x => crypto.createHash('sha256').update(x).digest('hex');
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function environment(html = '<html><body></body></html>', url = 'http://library.test/index.html') {
  const dom = new JSDOM(html, {url, runScripts: 'outside-only', pretendToBeVisual: true});
  const w = dom.window;
  w.TextEncoder = TextEncoder; w.TextDecoder = TextDecoder;
  // Match the LAN fallback's immediately resolved microtask behavior.
  Object.defineProperty(w, 'crypto', {value: {subtle: {digest: async (_alg, bytes) => {
    const result = crypto.createHash('sha256').update(new Uint8Array(bytes)).digest();
    return result.buffer.slice(result.byteOffset, result.byteOffset + result.byteLength);
  }}}});
  w.matchMedia = () => ({matches:false, addEventListener(){}, removeEventListener(){}});
  w.fetch = async () => { throw new Error('unexpected fetch'); };
  const api = runtime.indexOf('window.AnkiReviewedChunkProjection = Object.freeze');
  assert.ok(api > 0);
  w.eval(runtime.slice(0, runtime.indexOf('})();', api) + 5));
  return dom;
}

test('all real projection checks allow user-input tasks before completion on the LAN fallback', privateFixture, async t => {
  const dom = environment(); t.after(() => dom.window.close());
  let inputTaskRan = false;
  dom.window.setTimeout(() => { inputTaskRan = true; }, 0);
  const token = await dom.window.AnkiReviewedChunkProjection.prepare(projection);
  assert.equal(token.records, 2375); assert.equal(token.mappings, 4011); assert.equal(token.unmapped, 72);
  assert.equal(inputTaskRan, true, 'Input tasks must run while full integrity validation is pending');
});

test('duplicate text with a changed claimed hash still rejects and cannot poison a later prepare', privateFixture, async t => {
  const dom = environment(); t.after(() => dom.window.close());
  const fixture = JSON.parse(JSON.stringify(projection));
  const seen = new Map(); let repeated;
  for (const record of fixture.records) {
    for (const chunk of record.chunks) {
      const key = JSON.stringify([chunk.source.english, chunk.source.translation]);
      if (seen.has(key)) { repeated = [seen.get(key), chunk]; break; }
      seen.set(key, chunk);
    }
    if (repeated) break;
  }
  assert.ok(repeated, 'Real data contains a repeated source checked earlier');
  assert.equal(repeated[0].source.english, repeated[1].source.english);
  assert.equal(repeated[0].source.translation, repeated[1].source.translation);
  repeated[1].source.english_hash = '0'.repeat(64);
  await assert.rejects(dom.window.AnkiReviewedChunkProjection.prepare(fixture), /hash mismatch/);
  const token = await dom.window.AnkiReviewedChunkProjection.prepare(projection);
  assert.equal(token.records, 2375);
});

test('actual empty first-card catalog skips sidecars while flipping and navigation remain enabled', privateFixture, async t => {
  const folder = path.join(fullPreview, 'redbook2027');
  const full = JSON.parse(fs.readFileSync(path.join(folder, 'catalog.json')));
  const cards = full.cards.slice(0, 2), deck = full.decks.find(d => d.id === cards[0].deckId);
  const catalog = {...full, cards, decks:[{...deck,cardIds:cards.map(c=>c.id),count:2}],
    counts:{cards:2,decks:1,examples:0}};
  const html = fs.readFileSync(path.join(folder, 'preview-library.html'), 'utf8');
  const dom = new JSDOM(html, {url:'http://library.test/eleven-resolution-20261014/preview-own/final-v2/redbook2027/preview-library.html',
    runScripts:'outside-only', pretendToBeVisual:true});
  t.after(() => dom.window.close());
  const w = dom.window, d = w.document, requests = [];
  w.matchMedia = () => ({matches:false,addEventListener(){},removeEventListener(){}});
  w.fetch = async url => {requests.push(String(url)); return {ok:true,json:async()=>catalog};};
  w.eval(runtime); await settle();
  const frame = d.querySelector('#card-frame'), cd = frame.contentDocument;
  cd.open(); cd.write('<html><body><button id="preview-flip" aria-pressed="false">显示答案</button><section id="preview-front">radiate</section><section id="preview-back" hidden>definitions</section></body></html>'); cd.close();
  cd.querySelector('#preview-flip').addEventListener('click', e => e.target.setAttribute('aria-pressed', String(e.target.getAttribute('aria-pressed') !== 'true')));
  frame.dispatchEvent(new w.Event('load')); await settle();
  assert.equal(requests.length, 1, 'Only the catalog is needed for a truly empty card');
  assert.equal(frame.getAttribute('data-owned-runtime-state'), 'ready');
  assert.equal(d.querySelector('#flip-card').disabled, false);
  d.querySelector('#flip-card').click();
  assert.equal(cd.querySelector('#preview-flip').getAttribute('aria-pressed'), 'true');
  d.querySelector('#next-card').click();
  assert.match(w.location.hash, new RegExp(cards[1].id));
});
