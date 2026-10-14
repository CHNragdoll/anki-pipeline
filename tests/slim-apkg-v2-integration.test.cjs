const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { JSDOM } = require('jsdom');
const sha = x => crypto.createHash('sha256').update(x).digest('hex');
const runtime = fs.readFileSync('anki_pipeline/templates/slim-apkg-v2.js', 'utf8');
const codec = fs.readFileSync('anki_pipeline/templates/slim-shared-codec.js', 'utf8');

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
