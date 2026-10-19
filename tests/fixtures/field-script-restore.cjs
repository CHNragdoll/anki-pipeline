const fs = require('node:fs');
const assert = require('node:assert/strict');
const {JSDOM, VirtualConsole} = require('jsdom');
const {TextDecoder, TextEncoder} = require('node:util');
const {html, runtime, template, identical_fields} = JSON.parse(fs.readFileSync(0, 'utf8'));
function boot(value = html) {
  const dom = new JSDOM('<body>' + value + '</body>', {runScripts: 'outside-only'});
  dom.window.TextDecoder = TextDecoder;
  dom.window.TextEncoder = TextEncoder;
  dom.window.eval(runtime);
  return dom;
}
let dom = boot(), doc = dom.window.document, api = dom.window.StudyFieldScriptTransport;
const original = Array.from(doc.querySelectorAll('script'), node => ({attrs: Array.from(node.attributes, a => [a.name, a.value]), text: node.textContent}));
const parentText = doc.querySelector('article').textContent;
assert.deepEqual(JSON.parse(JSON.stringify(api.restore(doc))), {restored: 0, verified: 2});
assert.deepEqual(JSON.parse(JSON.stringify(api.restore(doc))), {restored: 0, verified: 2});
assert.equal(doc.querySelector('article').textContent, parentText);
assert.throws(() => api.restore(new JSDOM().window.document), /wrong document owner/);
dom.window.close();
dom = boot(); doc = dom.window.document; api = dom.window.StudyFieldScriptTransport;
for (const script of doc.querySelectorAll('script')) script.remove();
assert.deepEqual(JSON.parse(JSON.stringify(api.restore(doc))), {restored: 2, verified: 2});
assert.deepEqual(Array.from(doc.querySelectorAll('script'), node => ({attrs: Array.from(node.attributes, a => [a.name, a.value]), text: node.textContent})), original);
assert.equal(doc.querySelector('article').textContent, parentText);
doc.querySelector('script').dataset.nativeState = 'ready';
assert.equal(api.restore(doc).restored, 0);
doc.querySelector('script').textContent = 'tampered';
assert.throws(() => api.restore(doc), /text\/tag differs/);
doc.body.innerHTML = '<div>front face</div>';
assert.equal(api.restore(doc).restored, 0);
doc.body.innerHTML = html;
assert.equal(api.restore(doc).restored, 0);
dom.window.close();
for (const mutation of [
  d => d.querySelector('span[data-study-script-source]').setAttribute('data-study-script-source', 'invalid'),
  d => d.querySelector('span[data-study-script-source]').append('polluting text'),
  d => d.querySelector('span[data-study-script-source]').setAttribute('data-study-script-sha256', '0'.repeat(64)),
  d => d.querySelector('span[data-study-script-source]').setAttribute('style', 'display:block'),
  d => d.querySelector('span[data-study-script-source]').removeAttribute('data-study-script-source'),
  d => d.querySelector('script').setAttribute('data-foreign', 'changed'),
  d => d.querySelector('span[data-study-script-source]').after(d.querySelector('span[data-study-script-source]').cloneNode(true)),
  d => d.querySelector('span[data-study-script-source]').parentElement.append(d.querySelector('script')),
  d => {
    for (const carrier of d.querySelectorAll('[data-study-script-source]')) carrier.remove();
    d.querySelector('script.anki-final-reviewed-data').textContent = 'tampered without carrier';
  },
]) {
  dom = boot();
  mutation(dom.window.document);
  assert.throws(() => dom.window.StudyFieldScriptTransport.restore(dom.window.document));
  dom.window.close();
}
dom = boot(identical_fields.join(''));
assert.equal(dom.window.StudyFieldScriptTransport.restore(dom.window.document).verified, 2);
dom.window.close();
dom = boot(identical_fields.join(''));
for (const script of dom.window.document.querySelectorAll('script')) script.remove();
assert.equal(dom.window.StudyFieldScriptTransport.restore(dom.window.document).restored, 2);
dom.window.close();
console.log('PASS: actual field deletion/restoration, empty carriers, repeat, face switch, tamper and ambiguity');
// Run the actual generated template script boundary after an Editor-like DOM
// deletion/serialization, keeping original hydrate as an observable stub.
const editor = new JSDOM('<body>' + template + '</body>');
for (const script of editor.window.document.querySelectorAll('script.anki-final-reviewed-data,script.as-manifest')) script.remove();
const edited = editor.window.document.body.innerHTML;
editor.window.close();
const missing = new JSDOM('<body>' + template + '</body>');
for (const carrier of missing.window.document.querySelectorAll('[data-study-script-source]')) carrier.remove();
missing.window.document.querySelector('script.anki-final-reviewed-data').textContent = 'tampered without carrier';
const withoutCarriers = missing.window.document.body.innerHTML;
missing.window.close();
for (const [value, malformed] of [[edited, false], [edited.replace('data-study-script-sha256="', 'data-study-script-sha256="BAD'), true], [withoutCarriers, true]]) {
  let calls = 0, errors = 0;
  const view = new JSDOM('<body>' + value + '</body>', {runScripts: 'dangerously', virtualConsole: new VirtualConsole(),
    beforeParse(w) {
      w.TextDecoder = TextDecoder;
      w.TextEncoder = TextEncoder;
      w.eval(runtime);
      w.addEventListener('error', () => errors++);
      w.AnkiSlimApkgHydrate = () => { calls++; assert.equal(w.document.querySelectorAll('script.anki-final-reviewed-data,script.as-manifest').length, 2); };
    }});
  assert.equal(calls, malformed ? 0 : 1);
  assert.equal(errors, malformed ? 1 : 0);
  view.window.close();
}
// Independent execution check: a fragment-created restored executable bridge
// must remain inert even in a realm where ordinary inserted scripts execute.
const crypto = require('node:crypto');
const code = 'window.__fieldRuns=(window.__fieldRuns||0)+1;';
const payload = {attrs: [['data-cigen-frame-bridge', 'v1']], text: code, parent: 'div', kind: 'cigen', schema: 'study-field-script.v1'};
const raw = Buffer.from(JSON.stringify(payload)), pin = crypto.createHash('sha256').update(raw).digest('hex');
const carrier = `<span hidden="" style="display:none!important" aria-hidden="true" data-study-script-transport="v1" data-study-script-key="${'a'.repeat(64)}:0" data-study-script-sha256="${pin}" data-study-script-source="${raw.toString('base64')}"></span>`;
dom = new JSDOM(`<body><div><script data-cigen-frame-bridge="v1">${code}</script>${carrier}</div></body>`, {runScripts: 'dangerously'});
dom.window.TextDecoder = TextDecoder;
dom.window.TextEncoder = TextEncoder;
assert.equal(dom.window.__fieldRuns, 1);
dom.window.eval(runtime);
dom.window.document.querySelector('script').remove();
assert.equal(dom.window.StudyFieldScriptTransport.restore(dom.window.document).restored, 1);
assert.equal(dom.window.__fieldRuns, 1);
dom.window.close();
console.log('PASS: actual generated pre-hydrate boundary fail-closed and restored bridge stays inert');
