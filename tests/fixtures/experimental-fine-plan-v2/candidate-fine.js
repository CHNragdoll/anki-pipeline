/* Owned, reversible candidate. No text matching, semantic edits or event handlers.
 * Call window.AnkiFineChunkRuntime.install(cardDocument) after strict loadCard
 * success; call its dispose() when that frame is disposed. Existing delegated
 * card-chunks.js listeners read the filtered attributes on each interaction.
 */
(function () {
  'use strict';
  if (window.AnkiFineChunkRuntime) return;
  var installed = new WeakMap();
  var historySelector = '.sf-ownership-history,.sf-original-history-panel,.sf-ownership-authority,' +
    '.sf-archived-example,.sf-archived-native-example,[data-native-ownership-history]';
  function ids(value) { return typeof value === 'string' && /^\d+( \d+)*$/.test(value) ? value.split(' ') : []; }
  function isNative(chunk, root) {
    return chunk.closest('.example-card') === root && !chunk.closest(historySelector);
  }
  // Experimental protocol: original semantic execution is moved to compilation.
  var compiledPending = new WeakMap(), compiledVersion = 'study-fine-plan.v2';
  var originalFineSha = 'b0be6520ffe3ee5e0ee1efa901e5b724f3b2d80364d73910d2f64c8f1dc10c71';
  function need(value, why) { if (!value) throw Error('Fine plan: ' + why); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function versions(value) {
    need(value && Object.keys(value).sort().join(',') === 'metadata_sha256,module_sha256,source_sha256', 'versions');
    var out = {};
    ['module_sha256','source_sha256','metadata_sha256'].forEach(function (key) {
      var descriptor = Object.getOwnPropertyDescriptor(value, key);
      need(descriptor && Object.prototype.hasOwnProperty.call(descriptor, 'value'), 'version data field');
      var pin = descriptor.value;
      need(typeof pin === 'string' && /^[a-f0-9]{64}$/.test(pin), 'version pin'); out[key] = pin;
    });
    need(out.module_sha256 === originalFineSha, 'module version'); return out;
  }
  function snapshot(doc) {
    // Complete Fine semantic members, once; no Text, unrelated attrs or subtrees.
    need(doc.contentType === 'text/html', 'native HTML document required');
    var selector = '.example-card,[data-chunk-ids],[data-chunk-sentence-ids],mark.target-word,' + historySelector;
    var list = Array.from(doc.querySelectorAll(selector)), proof = [], nodes = new Map(), paths = new Map();
    list.forEach(function (node, n) { var path = String(n); need(!paths.has(node), 'duplicate semantic member'); nodes.set(path, node); paths.set(node, path); });
    list.forEach(function (node) {
      var parent = node.parentElement;
      while (parent && !paths.has(parent)) parent = parent.parentElement;
      var attrs = [];
      ['class','data-chunk-ids','data-chunk-sentence-ids'].forEach(function (name) { var attribute = node.getAttributeNode(name); if (attribute) { need(attribute.namespaceURI === null, 'namespaced Fine input unsupported'); attrs.push([null, name, attribute.value]); } });
      var kinds = (node.matches('.example-card') ? 1 : 0) |
        (node.hasAttribute('data-chunk-ids') ? 2 : 0) |
        (node.hasAttribute('data-chunk-sentence-ids') ? 4 : 0) |
        (node.matches('mark.target-word') ? 8 : 0) |
        (node.matches(historySelector) ? 16 : 0);
      proof.push([paths.get(node), 1, node.nodeName, node.namespaceURI || null, attrs, null, parent ? paths.get(parent) : null, kinds]);
    });
    return { proof: proof, nodes: nodes, paths: paths };
  }
  function rejectInheritedStateField(value, key) {
    for (var prototype = Object.getPrototypeOf(value); prototype; prototype = Object.getPrototypeOf(prototype)) {
      need(!Object.getOwnPropertyDescriptor(prototype, key), 'inherited state field unsupported: ' + key);
    }
  }
  function activeState(doc, snap) {
    var desc = Object.getOwnPropertyDescriptor(doc.defaultView, '__ankiCardChunkState');
    if (!desc) {
      rejectInheritedStateField(doc.defaultView, '__ankiCardChunkState');
      return { kind: 'absent' };
    }
    need(Object.prototype.hasOwnProperty.call(desc, 'value'), 'state accessor');
    if (desc.value == null) return { kind: desc.value === null ? 'null' : 'undefined' };
    var out = []; need(typeof desc.value === 'object', 'state object');
    ['root','side','ids','sentenceIds'].forEach(function (key) {
      var field = Object.getOwnPropertyDescriptor(desc.value, key);
      if (!field) rejectInheritedStateField(desc.value, key);
      else need(Object.prototype.hasOwnProperty.call(field, 'value') && field.enumerable,
        'own enumerable state consumer required: ' + key);
    });
    Object.keys(desc.value).sort().forEach(function (key) {
      var d = Object.getOwnPropertyDescriptor(desc.value, key); need(Object.prototype.hasOwnProperty.call(d, 'value'), 'state getter'); var value = d.value;
      if (key === 'root') { need(snap.paths.has(value), 'foreign state root'); out.push([key, { node: snap.paths.get(value) }]); }
      else if (Array.isArray(value)) { need(value.every(function (v) { return typeof v === 'string'; }), 'state array'); out.push([key, value.slice()]); }
      else { need(value === null || ['string','number','boolean'].indexOf(typeof value) >= 0, 'unsupported state field'); out.push([key, value]); }
    }); return { kind: 'object', fields: out };
  }
  function logFine(ctx, kind, node, value) {
    if (!ctx || ctx.mode !== 'build') return; var op = { kind: kind };
    if (node) { need(ctx.before.paths.has(node), 'new operation node'); op.path = ctx.before.paths.get(node); }
    if (value !== undefined) op.value = value; ctx.operations.push(op);
  }
  function rememberFine(ctx, originals, node) { if (ctx && ctx.mode === 'build' && !originals.has(node)) logFine(ctx, 'remember', node); }
  function setFineIds(ctx, node, value) { logFine(ctx, 'ids', node, value); node.setAttribute('data-chunk-ids', value); }
  function removeFine(ctx, node, value, active) { logFine(ctx, active ? 'active' : 'remove', node, value); node.classList.remove(value); }
  function resetFine(ctx, view) { logFine(ctx, 'reset'); view.__ankiCardChunkState = null; }
  function compileFine(doc, bindings) {
    bindings = versions(bindings); need(!installed.has(doc) && !compiledPending.has(doc), 'already installed');
    var before = snapshot(doc), stateBefore = activeState(doc, before), ctx = { mode: 'build', before: before, operations: [] };
    compiledPending.set(doc, ctx);
    try {
      var handle = install(doc), after = snapshot(doc), records = Array.from(ctx.originals, function (entry) { var r = entry[1]; return { path: before.paths.get(entry[0]), originalIds: r.originalIds, originalClass: r.originalClass, lastIds: r.lastIds, lastClass: r.lastClass, removedClasses: Array.from(r.removedClasses) }; });
      need(after.proof.length === before.proof.length && after.proof.every(function (entry, n) { return after.nodes.get(entry[0]) === before.nodes.get(entry[0]) && equal(entry.slice(0, 4), before.proof[n].slice(0, 4)) && equal(entry.slice(6), before.proof[n].slice(6)); }), 'compiler changed semantic membership');
      var delta = after.proof.filter(function (entry, n) { return !equal(entry[4], before.proof[n][4]); }).map(function (entry) { return [entry[0], entry[4]]; });
      return { handle: handle, serialized: JSON.stringify({ schema: compiledVersion, bindings: bindings, before: before.proof, stateBefore: stateBefore, operations: ctx.operations.slice(), records: records, stats: handle.stats(), after: delta, stateAfter: activeState(doc, after) }) };
    } finally { compiledPending.delete(doc); ctx.mode = 'closed'; ctx.before = null; ctx.originals = null; ctx.operations = null; }
  }
  function validateFine(doc, plan, bindings) {
    need(plan && plan.schema === compiledVersion, 'schema'); need(equal(versions(plan.bindings), versions(bindings)), 'source/metadata version');
    var snap = snapshot(doc); need(equal(plan.before, snap.proof), 'complete Fine semantic graph'); need(equal(plan.stateBefore, activeState(doc, snap)), 'active state');
    need(Array.isArray(plan.records) && Array.isArray(plan.operations), 'record arrays'); var records = new Map(), seen = new Set();
    plan.records.forEach(function (r) { need(r && typeof r.path === 'string' && !records.has(r.path), 'duplicate record'); var n = snap.nodes.get(r.path); need(n && n.nodeType === 1, 'record path'); ['originalIds','originalClass','lastIds','lastClass'].forEach(function (key) { need(r[key] === null || typeof r[key] === 'string', 'record attribute'); }); need(Array.isArray(r.removedClasses) && new Set(r.removedClasses).size === r.removedClasses.length && r.removedClasses.every(function (v) { return ['card-chunk','card-chunk-active','sf-target-chunk'].indexOf(v) >= 0; }), 'removed classes'); records.set(r.path, r); });
    plan.operations.forEach(function (op) { need(op && ['remember','ids','remove','active','reset'].indexOf(op.kind) >= 0, 'operation'); if (op.kind === 'reset') { need(!Object.prototype.hasOwnProperty.call(op, 'path'), 'reset path'); return; } var node = snap.nodes.get(op.path); need(node && node.nodeType === 1, 'operation path'); if (op.kind === 'remember') { need(records.has(op.path) && !seen.has(op.path), 'Map coverage'); seen.add(op.path); } else if (op.kind === 'active') need(op.value === 'card-chunk-active', 'active clear'); else { need(seen.has(op.path) && typeof op.value === 'string', 'write before record'); if (op.kind === 'remove') need(['card-chunk','card-chunk-active','sf-target-chunk'].indexOf(op.value) >= 0, 'class operation'); } });
    // Validate the recorded attribute transaction as data, not by rerunning Fine semantics.
    var simulated = new Map(), removed = new Map();
    snap.proof.forEach(function (entry) { if (entry[1] === 1) simulated.set(entry[0], entry[4].map(function (a) { return a.slice(); })); });
    function attr(path, name, value, write) {
      var attrs = simulated.get(path), at = attrs.findIndex(function (a) { return a[0] === null && a[1] === name; });
      if (!write) return at < 0 ? null : attrs[at][2];
      if (at < 0) attrs.push([null, name, value]); else attrs[at][2] = value;
    }
    plan.operations.forEach(function (op) {
      if (op.kind === 'remember') { var r = records.get(op.path); need(attr(op.path, 'class') === r.originalClass && attr(op.path, 'data-chunk-ids') === r.originalIds, 'Map original values'); }
      else if (op.kind === 'ids') attr(op.path, 'data-chunk-ids', op.value, true);
      else if (op.kind === 'remove' || op.kind === 'active') {
        var value = attr(op.path, 'class');
        if (value !== null) attr(op.path, 'class', Array.from(new Set(value.split(/[\t\n\f\r ]+/).filter(Boolean))).filter(function (token) { return token !== op.value; }).join(' '), true);
        if (op.kind === 'remove') { var values = removed.get(op.path) || new Set(); values.add(op.value); removed.set(op.path, values); }
      }
    });
    records.forEach(function (r, path) { need(attr(path, 'class') === r.lastClass && attr(path, 'data-chunk-ids') === r.lastIds && equal(Array.from(removed.get(path) || []), r.removedClasses), 'Map last values'); });
    var delta = snap.proof.filter(function (entry) { return !equal(simulated.get(entry[0]), entry[4]); }).map(function (entry) { return [entry[0], simulated.get(entry[0])]; });
    need(Array.isArray(plan.after) && equal(plan.after, delta), 'operation coverage');
    var finalState = plan.operations.some(function (op) { return op.kind === 'reset'; }) ? { kind: 'null' } : plan.stateBefore;
    need(equal(finalState, plan.stateAfter), 'reset coverage');
    need(seen.size === records.size, 'incomplete Map coverage'); need(plan.stats && Object.keys(plan.stats).sort().join(',') === 'filteredSpans,malformedMetadata,rootsWithWhole,wholeOnlySpans' && Object.keys(plan.stats).every(function (k) { return Number.isSafeInteger(plan.stats[k]) && plan.stats[k] >= 0; }), 'stats');

    return { mode: 'hydrate', plan: plan, nodes: snap.nodes, records: records };
  }
  function applyFine(ctx, originals, doc) {
    ctx.plan.operations.forEach(function (op) { var node = ctx.nodes.get(op.path), r; if (op.kind === 'remember') { r = ctx.records.get(op.path); originals.set(node, { originalIds: r.originalIds, originalClass: r.originalClass, lastIds: r.lastIds, lastClass: r.lastClass, removedClasses: new Set(r.removedClasses) }); } else if (op.kind === 'ids') node.setAttribute('data-chunk-ids', op.value); else if (op.kind === 'remove' || op.kind === 'active') node.classList.remove(op.value); else doc.defaultView.__ankiCardChunkState = null; });
  }
  async function hydrateFine(doc, serialized, expectedSha, bindings, options) {
    need(typeof serialized === 'string' && typeof expectedSha === 'string' && /^[a-f0-9]{64}$/.test(expectedSha), 'external expected pin'); bindings = versions(bindings); var current = options && options.isCurrent || function () { return true; }; need(current(), 'cancelled');
    var bytes = new TextEncoder().encode(serialized), digest = await window.crypto.subtle.digest('SHA-256', bytes), actual = Array.from(new Uint8Array(digest), function (x) { return x.toString(16).padStart(2, '0'); }).join('');
    need(actual === expectedSha, 'external expected pin differs'); need(current(), 'cancelled'); need(!installed.has(doc) && !compiledPending.has(doc), 'already installed');
    var ctx = validateFine(doc, JSON.parse(serialized), bindings); need(current(), 'cancelled'); compiledPending.set(doc, ctx);
    try { return install(doc); } finally { compiledPending.delete(doc); ctx.mode = 'closed'; ctx.plan = null; ctx.nodes = null; ctx.records = null; }
  }
  function install(cardDocument) {
    if (installed.has(cardDocument)) return installed.get(cardDocument);
    var originals = new Map(), pending = false, disposed = false;
    var compiledCtx = compiledPending.get(cardDocument); if (compiledCtx) compiledCtx.originals = originals;
    var stats = { rootsWithWhole: 0, filteredSpans: 0, wholeOnlySpans: 0, malformedMetadata: 0 };
    function remember(element) {
      rememberFine(compiledCtx, originals, element);
      if (!originals.has(element)) originals.set(element, {
        originalIds: element.getAttribute('data-chunk-ids'), originalClass: element.getAttribute('class'),
        lastIds: element.getAttribute('data-chunk-ids'), lastClass: element.getAttribute('class'), removedClasses: new Set()
      });
      return originals.get(element);
    }
    function removeClass(element, value, record) {
      if (element.classList.contains(value)) { removeFine(compiledCtx, element, value, false); record.removedClasses.add(value); }
    }
    function process(root) {
      if (root.closest(historySelector)) return;
      var chunks = Array.from(root.querySelectorAll('[data-chunk-ids],[data-chunk-sentence-ids]')).filter(function (chunk) {
        return isNative(chunk, root);
      });
      var whole = new Set();
      chunks.forEach(function (chunk) {
        var value = chunk.getAttribute('data-chunk-sentence-ids');
        if (value !== null && ids(value).length === 0) stats.malformedMetadata++;
        ids(value).forEach(function (id) { whole.add(id); });
      });
      if (!whole.size) return; // Absence of metadata never makes a singleton a whole sentence.
      stats.rootsWithWhole++;
      var targetFine = new Set();
      root.querySelectorAll('mark.target-word').forEach(function (mark) {
        if (!isNative(mark, root)) return;
        var marked = Array.from(mark.querySelectorAll('[data-chunk-ids]'));
        var enclosing = mark.closest('[data-chunk-ids]');
        if (enclosing) marked.push(enclosing);
        marked.forEach(function (chunk) {
          if (isNative(chunk, root)) ids(chunk.getAttribute('data-chunk-ids')).forEach(function (id) {
            if (!whole.has(id)) targetFine.add(id);
          });
        });
      });
      // A previously tapped whole sentence must not keep its stale active state.
      var view = cardDocument.defaultView, state = view && view.__ankiCardChunkState;
      if (state && state.root === root) {
        var selected = state.side === 'en' ? state.ids.slice(0, 1) : state.ids.filter(function (id) {
          return !state.sentenceIds || state.sentenceIds.indexOf(id) === -1;
        });
        if (!selected.length || selected.some(function (id) { return whole.has(id); })) {
          chunks.forEach(function (chunk) { removeFine(compiledCtx, chunk, 'card-chunk-active', true); });
          resetFine(compiledCtx, view);
        }
      }
      chunks.forEach(function (chunk) {
        var originalIds = ids(chunk.getAttribute('data-chunk-ids'));
        var fine = originalIds.filter(function (id) { return !whole.has(id); });
        var wholeMember = originalIds.some(function (id) { return whole.has(id); });
        var wrongTarget = chunk.classList.contains('sf-target-chunk') &&
          !fine.some(function (id) { return targetFine.has(id); });
        if (!wholeMember && !wrongTarget) return;
        var record = remember(chunk);
        // Preserve external sidecar replacements for an eventual disposer.
        if (chunk.getAttribute('data-chunk-ids') !== record.lastIds) record.originalIds = chunk.getAttribute('data-chunk-ids');
        if (chunk.getAttribute('class') !== record.lastClass) {
          record.originalClass = chunk.getAttribute('class'); record.removedClasses.clear();
        }
        if (wholeMember) {
          stats.filteredSpans++;
          if (fine.length) setFineIds(compiledCtx, chunk, fine.join(' '));
          else {
            setFineIds(compiledCtx, chunk, ''); stats.wholeOnlySpans++;
            removeClass(chunk, 'card-chunk', record); removeClass(chunk, 'card-chunk-active', record);
          }
        }
        if (wrongTarget || !fine.length) removeClass(chunk, 'sf-target-chunk', record);
        record.lastIds = chunk.getAttribute('data-chunk-ids'); record.lastClass = chunk.getAttribute('class');
      });
    }
    function refresh() {
      if (disposed) return;
      stats = { rootsWithWhole: 0, filteredSpans: 0, wholeOnlySpans: 0, malformedMetadata: 0 };
      cardDocument.querySelectorAll('.example-card').forEach(process);
    }
    var observer = new MutationObserver(function () {
      if (pending || disposed) return;
      pending = true;
      Promise.resolve().then(function () { pending = false; refresh(); });
    });
    var handle = {
      refresh: refresh,
      stats: function () { return Object.assign({}, stats); },
      dispose: function () {
        if (disposed) return;
        disposed = true; observer.disconnect();
        originals.forEach(function (record, element) {
          if (element.getAttribute('data-chunk-ids') === record.lastIds) {
            if (record.originalIds === null) element.removeAttribute('data-chunk-ids');
            else element.setAttribute('data-chunk-ids', record.originalIds);
          }
          if (element.getAttribute('class') === record.lastClass) {
            if (record.originalClass === null) element.removeAttribute('class');
            else element.setAttribute('class', record.originalClass);
          }
        });
        installed.delete(cardDocument);
      }
    };
    installed.set(cardDocument, handle);
    if (compiledCtx && compiledCtx.mode === 'hydrate') { applyFine(compiledCtx, originals, cardDocument); stats = Object.assign({}, compiledCtx.plan.stats); } else refresh();
    if (!window.__ankiSlimManualRefresh) observer.observe(cardDocument.documentElement, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-chunk-ids', 'data-chunk-sentence-ids', 'class'] });
    return handle;
  }
  window.AnkiFineChunkRuntime = Object.freeze({ install: install, compile: compileFine, hydrate: hydrateFine });
})();