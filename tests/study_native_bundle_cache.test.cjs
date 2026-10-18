'use strict';
// Exercise the actual host loader with real classic script execution.  In
// particular, no test fabricates document.currentScript or evals a carrier.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawnSync} = require('node:child_process');
const {JSDOM, requestInterceptor, VirtualConsole} = require('jsdom');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'anki_pipeline/compiled/native-bootstrap.js'), 'utf8');
const sha = text => crypto.createHash('sha256').update(text).digest('hex');
const texts = ['A 引号" 😀', JSON.stringify({items: Array(30).fill('双语 repeated leaf 😀 '.repeat(200))}), 'C legacy'];
const result = spawnSync(process.env.PYTHON || path.join(root, '.venv/bin/python'), ['-B', '-c',
  'import json,sys,hashlib;from anki_pipeline.study_native_carrier import build_native_carrier;print(json.dumps([build_native_carrier(hashlib.sha256(t.encode()).hexdigest(),t).decode() for t in json.load(sys.stdin)]))'],
  {cwd: root, input: JSON.stringify(texts), encoding: 'utf8'});
assert.equal(result.status, 0, result.stderr);
const carriers = JSON.parse(result.stdout);
assert.match(carriers[1], /\.map\(function\(p\)/, 'use the actual production dictionary IIFE');
const pins = texts.map(sha), bundle = '_study_native_' + sha(carriers[0] + '\n' + carriers[1]) + '.js';
const legacy = '_study_native_' + sha(carriers[2]) + '.js';
function slice(before, after) {
  assert.equal(source.split(before).length, 2, before);
  const at = source.indexOf(before), end = source.indexOf(after, at);
  assert.ok(end > at, after); return source.slice(at, end);
}
const definitions = slice('  function owns(owner) {', '  function execute(owner, text) {');
const disposal = slice('  function dispose(owner = current) {', '  function fail(owner, error) {');
const declarations = source.match(/^  const pending = .*;$/m)[0];
const tick = () => new Promise(resolve => setImmediate(resolve));
async function fixture() {
  const requested = [], waiting = [], errors = [];
  const intercept = requestInterceptor((request, {element}) => {
    const name = new URL(request.url).pathname.split('/').pop(); requested.push(name);
    return new Promise((resolve, reject) => {
      waiting.push({name, element, resolve: text => resolve(new Response(text,
        {headers: {'content-type': 'application/javascript'}})), reject});
    });
  });
  const vc = new VirtualConsole(); vc.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM('<!doctype html><head></head><body></body>', {
    url: 'https://anki.invalid/media/card.html', runScripts: 'dangerously', resources: {interceptors: [intercept]}, virtualConsole: vc,
  });
  const w = dom.window, d = w.document;
  w.hostDigest = async (text, pin) => sha(text) === pin;
  const harness = d.createElement('script');
  harness.textContent = `(function(win,doc){'use strict';const KEY='StudyCompiledNative';
    const hash=/^[a-f0-9]{64}$/,basename=/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/;
    let current=null,generation=0,stopped=false,modulePin=null,api=null;
    ${declarations}
    const knownPinMatches=win.hostDigest;
    function demand(value,message){if(!value)throw Error('Native compiled: '+message);}
    ${definitions}
    ${disposal}
    api={register,dispose,load(asset){return load(current,asset);},open(transport){
      dispose();const anchor=doc.createElement('section');doc.body.append(anchor);
      const owner={anchor,generation:++generation,disposed:false,loaded:new Map(),bundles:new Map(),
        tasks:new Set(),headNodes:[],globals:new Map(),value:{transport},state:'loading'};
      anchor.dataset.studyNativeGeneration=String(generation);current=owner;return owner;
    },counts(){return {tasks:current.tasks.size,pending:pending.size,loaded:current.loaded.size,
      bundles:current.bundles.size,cachedTexts:Array.from(current.bundles.values()).reduce((n,t)=>n+t.texts.size,0)};}};win[KEY]=api;
  })(window,document);`;
  d.head.append(harness); harness.remove();
  const api = w.StudyCompiledNative;
  const transport = {a: {src: bundle, sha256: pins[0]}, b: {src: bundle, sha256: pins[1]}};
  api.open(transport);
  return {w, d, api, requested, waiting, errors, transport,
    asset(name) {return {src: name, sha256: transport[name].sha256};},
    async release(text = carriers[0] + '\n' + carriers[1], at = 0) {while (!waiting[at]) await tick(); waiting[at].resolve(text);},
    close() {api.dispose(); w.close();}};
}

test('concurrent A/B: one real source execution, original literal + dictionary IIFE', async t => {
  const f = await fixture(); t.after(() => f.close());
  const a = f.api.load(f.asset('a')), b = f.api.load(f.asset('b'));
  assert.equal(f.api.load(f.asset('a')), a, 'same pending pin shares its verified promise');
  await tick(); assert.equal(f.requested.length, 1, 'one source load for two pending pins');
  f.release('window.executions=(window.executions||0)+1;window.sourceSeen=document.currentScript;\n' + carriers[0] + '\n' + carriers[1]);
  assert.deepEqual(await Promise.all([a, b]), texts.slice(0, 2));
  assert.equal(f.w.executions, 1); assert.equal(f.w.sourceSeen, f.waiting[0].element);
  assert.equal(f.api.counts().tasks, 0); assert.equal(f.api.counts().pending, 0);
});

test('sequential B uses authorized cached original text, with SHA recheck', async t => {
  const f = await fixture(); t.after(() => f.close());
  const a = f.api.load(f.asset('a')); f.release(); assert.equal(await a, texts[0]);
  assert.equal(await f.api.load(f.asset('b')), texts[1]);
  assert.equal(f.requested.length, 1, 'sequential second pin must not parse/join the bundle again');
  assert.equal(await f.api.load(f.asset('a')), texts[0]);
});

test('no-source and foreign real scripts cannot satisfy or cache pending pins', async t => {
  const f = await fixture(); t.after(() => f.close());
  let settled = false; const a = f.api.load(f.asset('a')).then(value => {settled = true; return value;});
  f.api.register(pins[0], texts[0]);
  const foreign = f.d.createElement('script'); foreign.textContent = carriers[0]; f.d.head.append(foreign); foreign.remove();
  await tick(); assert.equal(settled, false, 'a register call needs the requested source identity');
  f.release(carriers[0] + '\n' + carriers[1] + '\n' + carriers[2]); assert.equal(await a, texts[0]);
  assert.equal(f.api.counts().loaded, 1);
  assert.equal(f.api.counts().cachedTexts, 2, 'foreign pin must not enter raw text cache');
});

test('foreign bundle members are ignored, missing authorized member fails closed and retry loads anew', async t => {
  const f = await fixture(); t.after(() => f.close());
  const a = f.api.load(f.asset('a')); const rejected = assert.rejects(a, /did not register/);
  f.release(carriers[0] + '\n' + carriers[2]); await rejected;
  assert.equal(f.api.counts().tasks, 0); assert.equal(f.api.counts().bundles, 0);
  const retry = f.api.load(f.asset('a')); await tick(); assert.equal(f.requested.length, 2); f.release(undefined, 1);
  assert.equal(await retry, texts[0]); assert.equal(f.api.counts().loaded, 1);
});

test('corrupt authorized text and conflicting duplicate registration fail closed', async t => {
  const f = await fixture(); t.after(() => f.close());
  const a = f.api.load(f.asset('a')); f.release(carriers[0] + '\nwindow.StudyCompiledNative.register(' + JSON.stringify(pins[1]) + ',"corrupt");');
  assert.equal(await a, texts[0]);
  await assert.rejects(f.api.load(f.asset('b')), /SHA differs/);
  const second = f.api.open(f.transport); assert.ok(second);
  const conflict = f.api.load(f.asset('a')), rejected = assert.rejects(conflict, /conflicting/);
  f.release(carriers[0] + '\nwindow.StudyCompiledNative.register(' + JSON.stringify(pins[0]) + ',"other");\n' + carriers[1], 1);
  await rejected;
});

test('retired source cannot satisfy new owner, including the same pin', async t => {
  const f = await fixture(); t.after(() => f.close());
  const old = f.api.load(f.asset('a')), cancelled = assert.rejects(old, /cancelled/);
  f.api.open(f.transport); await cancelled;
  const next = f.api.load(f.asset('a')); let settled = false; next.then(() => {settled = true;});
  await f.release('window.retiredExecuted=true;\n' + carriers[0] + '\n' + carriers[1]);
  await tick(); await tick(); assert.equal(f.w.retiredExecuted, true, 'retired classic script actually ran');
  assert.equal(settled, false);
  f.release(undefined, 1); assert.equal(await next, texts[0]);
  assert.equal(f.requested.length, 2);
});

test('dispose releases completed bundle strings; next owner fetches the same src again', async t => {
  const f = await fixture(); t.after(() => f.close());
  const owner = f.api.open(f.transport);
  const a = f.api.load(f.asset('a')); f.release(); assert.equal(await a, texts[0]);
  assert.equal(owner.bundles.size, 1); assert.equal(f.api.counts().cachedTexts, 2);
  f.api.dispose(); assert.equal(owner.loaded.size, 0); assert.equal(owner.bundles.size, 0);
  f.api.open(f.transport); const next = f.api.load(f.asset('b'));
  await tick(); assert.equal(f.requested.length, 2); f.release(undefined, 1);
  assert.equal(await next, texts[1]);
});

test('legacy single carrier, onerror and timeout cleanup, failed source can retry', async t => {
  const f = await fixture(); t.after(() => f.close());
  const desc = {src: 'legacy', sha256: pins[2]}; f.api.open({legacy: {src: legacy, sha256: pins[2]}});
  const legacyRead = f.api.load(desc); f.release(carriers[2]); assert.equal(await legacyRead, texts[2]);
  f.api.open(f.transport);
  const failure = f.api.load(f.asset('a')), rejected = assert.rejects(failure, /unavailable/);
  await tick(); f.waiting[1].reject(Error('fixture network failure')); await rejected;
  assert.equal(f.api.counts().tasks, 0); assert.equal(f.api.counts().bundles, 0);
  const originalTimer = f.w.setTimeout; let timeout;
  f.w.setTimeout = (callback, ms) => ms === 30000 ? (timeout = callback, 0) : originalTimer(callback, ms);
  const timed = f.api.load(f.asset('a')), timedOut = assert.rejects(timed, /timed out/); timeout(); await timedOut;
  assert.equal(f.api.counts().tasks, 0); assert.equal(f.api.counts().bundles, 0);
});
