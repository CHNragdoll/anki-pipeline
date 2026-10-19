/* Known field-script restoration before the original Slim hydrate call.
 * Empty Base64 attribute carriers never add parent textContent. Restored script
 * nodes remain inert; original authored startup order is not replayed.
 */
(function install(win) {
  'use strict';
  // Exact synchronous SHA core shared with templates/lan-sha256.js.
  const ROUND_CONSTANTS = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const rotateRight = (word, count) => (word >>> count) | (word << (32 - count));
  function sha256(bytes) {
    const state = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ]);
    const schedule = new Uint32Array(64);

    function compress(block, offset) {
      for (let index = 0; index < 16; index++) {
        const start = offset + index * 4;
        schedule[index] = ((block[start] << 24) | (block[start + 1] << 16) |
          (block[start + 2] << 8) | block[start + 3]) >>> 0;
      }
      for (let index = 16; index < 64; index++) {
        const previous = schedule[index - 15];
        const recent = schedule[index - 2];
        const sigma0 = rotateRight(previous, 7) ^ rotateRight(previous, 18) ^ (previous >>> 3);
        const sigma1 = rotateRight(recent, 17) ^ rotateRight(recent, 19) ^ (recent >>> 10);
        schedule[index] = (schedule[index - 16] + sigma0 +
          schedule[index - 7] + sigma1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = state;
      for (let index = 0; index < 64; index++) {
        const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const choice = (e & f) ^ (~e & g);
        const first = (h + sum1 + choice + ROUND_CONSTANTS[index] + schedule[index]) >>> 0;
        const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (sum0 + majority) >>> 0;
        h = g; g = f; f = e; e = (d + first) >>> 0;
        d = c; c = b; b = a; a = (first + second) >>> 0;
      }
      const words = [a, b, c, d, e, f, g, h];
      for (let index = 0; index < 8; index++) {
        state[index] = (state[index] + words[index]) >>> 0;
      }
    }

    const completeLength = bytes.byteLength - (bytes.byteLength % 64);
    for (let offset = 0; offset < completeLength; offset += 64) compress(bytes, offset);
    const remaining = bytes.byteLength - completeLength;
    const tail = new Uint8Array(remaining < 56 ? 64 : 128);
    tail.set(bytes.subarray(completeLength));
    tail[remaining] = 0x80;
    const length = new DataView(tail.buffer);
    // Encode the 64-bit bit length as two big-endian 32-bit words, avoiding
    // truncation when an input contains 2^29 or more bytes.
    length.setUint32(tail.byteLength - 8, Math.floor(bytes.byteLength / 0x20000000), false);
    length.setUint32(tail.byteLength - 4, (bytes.byteLength * 8) >>> 0, false);
    compress(tail, 0);
    if (tail.byteLength === 128) compress(tail, 64);

    const result = new ArrayBuffer(32);
    const output = new DataView(result);
    for (let index = 0; index < 8; index++) output.setUint32(index * 4, state[index], false);
    return result;
  }

  const factorySha256 = Array.from(new Uint8Array(sha256(new win.TextEncoder().encode(install.toString()))), n => n.toString(16).padStart(2, '0')).join('');
  if (win.StudyFieldScriptTransport) {
    if (win.StudyFieldScriptTransport.version !== 'v1' || typeof win.StudyFieldScriptTransport.restore !== 'function') throw Error('Unknown field-script restoration runtime');
    if (win.StudyFieldScriptTransport.factorySha256 === factorySha256) return;
    // No listeners/timers/global native state are owned; replacing this small
    // binding map is sufficient when a new content-addressed runtime arrives.
  }
  const HTML = 'http://www.w3.org/1999/xhtml';
  const selector = '[data-study-script-source],[data-study-script-transport],[data-study-script-key],[data-study-script-sha256]';
  const transport = 'script.anki-final-reviewed-data,script.as-manifest,script[data-cigen-frame-bridge]';
  const safe = new Set('div section article aside main header footer nav figure figcaption details li dd dt blockquote p span a b i em strong small label body'.split(' '));
  const carrierAttrs = new Set(['hidden', 'style', 'aria-hidden', 'data-study-script-transport',
    'data-study-script-key', 'data-study-script-sha256', 'data-study-script-source']);
  const bindings = new WeakMap();
  function need(ok, message) { if (!ok) throw Error('Field script recovery: ' + message); }
  function attributes(node) { return Array.from(node.attributes, a => [a.name, a.value]); }
  function known(attrs, kind) {
    const a = Object.fromEntries(attrs), classes = (a.class || '').split(/\s+/);
    return kind === 'reviewed' ? classes.includes('anki-final-reviewed-data') && (a.type || '').toLowerCase() === 'application/json' :
      kind === 'manifest' ? classes.includes('as-manifest') && (a.type || '').toLowerCase() === 'application/json' :
      kind === 'cigen' && a['data-cigen-frame-bridge'] === 'v1';
  }
  function decode(carrier) {
    need(carrier.namespaceURI === HTML && carrier.tagName === 'SPAN' && !carrier.childNodes.length &&
      carrier.attributes.length === carrierAttrs.size && attributes(carrier).every(a => carrierAttrs.has(a[0])) &&
      carrier.hasAttribute('hidden') && carrier.getAttribute('aria-hidden') === 'true' &&
      carrier.getAttribute('data-study-script-transport') === 'v1' && carrier.style.length === 1 &&
      carrier.style.getPropertyValue('display') === 'none' && carrier.style.getPropertyPriority('display') === 'important', 'carrier shape differs');
    const key = carrier.getAttribute('data-study-script-key'), pin = carrier.getAttribute('data-study-script-sha256');
    need(/^[a-f0-9]{64}:\d+$/.test(key) && /^[a-f0-9]{64}$/.test(pin), 'carrier identity differs');
    const encoded = carrier.getAttribute('data-study-script-source'), binary = win.atob(encoded);
    need(win.btoa(binary) === encoded, 'noncanonical Base64');
    const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
    const actual = Array.from(new Uint8Array(sha256(bytes)), n => n.toString(16).padStart(2, '0')).join('');
    need(actual === pin, 'carrier payload SHA differs');
    const p = JSON.parse(new win.TextDecoder('utf-8', {fatal: true}).decode(bytes));
    need(Object.keys(p).sort().join(',') === 'attrs,kind,parent,schema,text' && p.schema === 'study-field-script.v1' &&
      typeof p.text === 'string' && (p.parent === null || typeof p.parent === 'string') && Array.isArray(p.attrs), 'payload schema differs');
    const names = new Set();
    for (const a of p.attrs) {
      need(Array.isArray(a) && a.length === 2 && a.every(x => typeof x === 'string') &&
        /^[a-z_][a-z0-9_.:-]*$/.test(a[0]) && !names.has(a[0]) && a[0] !== 'src' && a[0] !== 'is' && !a[0].startsWith('on'), 'payload attributes differ');
      names.add(a[0]);
    }
    need(known(p.attrs, p.kind), 'unknown field transport');
    const parent = carrier.parentElement;
    need(parent && parent.namespaceURI === HTML && safe.has(parent.localName) &&
      (p.parent === null || parent.localName === p.parent) &&
      !carrier.closest('table,thead,tbody,tfoot,tr,colgroup,select,option,optgroup,svg,math,template,noscript,head'), 'carrier parent grammar differs');
    return {p, key, pin, parent};
  }
  function matches(node, p, owned) {
    need(node.namespaceURI === HTML && node.tagName === 'SCRIPT' && node.textContent === p.text, 'existing script text/tag differs');
    let attrs = attributes(node);
    if (owned) attrs = attrs.filter(a => !['data-native-state', 'data-as-state', 'data-as-loaded-parts'].includes(a[0]) || p.attrs.some(old => old[0] === a[0]));
    need(JSON.stringify(attrs) === JSON.stringify(p.attrs), 'existing script attributes differ');
  }
  function restore(doc) {
    need(doc === win.document, 'wrong document owner');
    const carriers = Array.from(doc.querySelectorAll(selector));
    if (!carriers.length) {
      need(!doc.querySelector(transport), 'unpaired/moved existing transport');
      return {restored: 0, verified: 0};
    }
    const keys = new Set(), paired = new Set(), plans = [];
    for (const carrier of carriers) {
      const row = decode(carrier), bound = bindings.get(carrier);
      need(!keys.has(row.key), 'duplicate/ambiguous carrier'); keys.add(row.key);
      const previous = carrier.previousSibling;
      let script = previous && previous.nodeType === 1 && previous.tagName === 'SCRIPT' ? previous : null;
      if (bound) need(script === bound.script && row.parent === bound.parent && row.pin === bound.pin, 'bound node/position changed');
      if (script) { matches(script, row.p, !!bound); paired.add(script); }
      plans.push({carrier, ...row, script});
    }
    for (const script of doc.querySelectorAll(transport)) need(paired.has(script), 'unpaired/moved existing transport');
    let restored = 0;
    for (const row of plans) {
      if (!row.script) {
        // HTML fragment-created scripts are already inert; moving one never
        // replays executable Cigen/author startup. Later original startup owns it.
        const holder = doc.createElement('div'); holder.innerHTML = '<script></script>';
        row.script = holder.firstChild;
        for (const a of row.p.attrs) row.script.setAttribute(a[0], a[1]);
        row.script.textContent = row.p.text;
        row.parent.insertBefore(row.script, row.carrier); restored++;
      }
      bindings.set(row.carrier, {script: row.script, parent: row.parent, pin: row.pin});
    }
    return {restored, verified: plans.length};
  }
  win.StudyFieldScriptTransport = Object.freeze({version: 'v1', factorySha256, restore});
})(window);
