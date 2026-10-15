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
  function install(cardDocument) {
    if (installed.has(cardDocument)) return installed.get(cardDocument);
    var originals = new Map(), pending = false, disposed = false;
    var stats = { rootsWithWhole: 0, filteredSpans: 0, wholeOnlySpans: 0, malformedMetadata: 0 };
    function remember(element) {
      if (!originals.has(element)) originals.set(element, {
        originalIds: element.getAttribute('data-chunk-ids'), originalClass: element.getAttribute('class'),
        lastIds: element.getAttribute('data-chunk-ids'), lastClass: element.getAttribute('class'), removedClasses: new Set()
      });
      return originals.get(element);
    }
    function removeClass(element, value, record) {
      if (element.classList.contains(value)) { element.classList.remove(value); record.removedClasses.add(value); }
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
          chunks.forEach(function (chunk) { chunk.classList.remove('card-chunk-active'); });
          view.__ankiCardChunkState = null;
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
          if (fine.length) chunk.setAttribute('data-chunk-ids', fine.join(' '));
          else {
            chunk.setAttribute('data-chunk-ids', ''); stats.wholeOnlySpans++;
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
    installed.set(cardDocument, handle); refresh();
    observer.observe(cardDocument.documentElement, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-chunk-ids', 'data-chunk-sentence-ids', 'class'] });
    return handle;
  }
  window.AnkiFineChunkRuntime = Object.freeze({ install: install });
})();

/* Candidate only. Exact reviewed bilingual display projections, no semantic
 * inference. Install after strict card readiness AND the accepted whole-ID
 * filter; dispose this handle before disposing that filter. Existing chunk
 * delegation remains the only activation path (including keyboard bridge).
 */
(function () {
  'use strict';
  if (window.AnkiReviewedChunkProjection) return;
  var SCHEMA = 'derived-chunk-display-projection.v1';
  var prepared = new WeakMap(), installed = new WeakMap();
  var excluded = '.sf-ownership-history,.sf-original-history-panel,.sf-ownership-authority,' +
    '.sf-archived-example,.sf-archived-native-example,[data-native-ownership-history],[data-reviewed-source-comparison]';
  var targetSelector = 'mark.target-word,mark.sf-word-hit,mark.sf-wordhit,mark.sfwordhit';
  function fail(message) { throw new Error('Reviewed chunk projection: ' + message); }
  function ids(value) { return typeof value === 'string' && /^\d+( \d+)*$/.test(value) ? value.split(' ') : []; }
  function points(text) { return Array.from(text); }
  function slice(text, range) { return points(text).slice(range[0], range[1]).join(''); }
  function range(value, text) {
    return Array.isArray(value) && value.length === 2 && value.every(Number.isSafeInteger) &&
      value[0] >= 0 && value[0] < value[1] && value[1] <= points(text).length;
  }
  function requireText(value, label) { if (typeof value !== 'string' || !value.length) fail(label + ' is empty'); }
  function requireHash(value, label) { if (typeof value !== 'string' || !/^[a-f0-9]{64}$/.test(value)) fail(label + ' hash invalid'); }
  async function sha(text) {
    if (!window.crypto || !window.crypto.subtle || typeof window.TextEncoder !== 'function') fail('WebCrypto/TextEncoder unavailable; integrity is mandatory');
    return digest(new window.TextEncoder().encode(text));
  }
  async function digest(bytes) {
    if (!window.crypto || !window.crypto.subtle) fail('WebCrypto unavailable; integrity is mandatory');
    var result = await window.crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(result)).map(function (v) { return v.toString(16).padStart(2, '0'); }).join('');
  }
  function key(en, zh) { return JSON.stringify([en, zh]); }
  async function validateSource(source) {
    if (!source || typeof source !== 'object') fail('source absent');
    requireText(source.english, 'source English'); requireText(source.translation, 'source Chinese');
    requireHash(source.english_hash, 'source English'); requireHash(source.translation_hash, 'source Chinese');
    if (await sha(source.english) !== source.english_hash || await sha(source.translation) !== source.translation_hash) fail('source text hash mismatch');
    var chunk = source.chunk;
    if (!chunk || !range(chunk.en, source.english) || !Array.isArray(chunk.zh) || !chunk.zh.length ||
        !chunk.zh.every(function (r) { return range(r, source.translation); })) fail('source chunk range invalid');
    if (slice(source.english, chunk.en) !== source.chunk_english || !Array.isArray(source.chunk_chinese) ||
        JSON.stringify(chunk.zh.map(function (r) { return slice(source.translation, r); })) !== JSON.stringify(source.chunk_chinese)) fail('source fragments disagree');
    if (!Array.isArray(source.refs) || !source.refs.length) fail('source refs absent');
  }
  async function prepare(data) {
    if (!data || data.schema !== SCHEMA || !Array.isArray(data.records) || !data.pins) fail('schema/pins invalid');
    // Snapshot the supplied JSON before any await. Callers cannot mutate a
    // validated projection after its hashes and ranges have been checked.
    var copy = JSON.parse(JSON.stringify(data)), index = new Map(), mappings = 0, unmapped = 0;
    for (var record of copy.records) {
      requireText(record.english, 'display English'); requireText(record.translation, 'display Chinese');
      requireHash(record.english_hash, 'display English'); requireHash(record.translation_hash, 'display Chinese');
      if (await sha(record.english) !== record.english_hash || await sha(record.translation) !== record.translation_hash) fail('display text hash mismatch');
      if (await sha(JSON.stringify([record.english_hash, record.translation_hash])) !== record.display_id) fail('display ID mismatch');
      if (!Array.isArray(record.chunks) || !Array.isArray(record.unmapped)) fail('mapping arrays absent');
      var seen = new Set();
      for (var chunk of record.chunks.concat(record.unmapped)) {
        requireHash(chunk.mapping_id, 'mapping ID');
        if (seen.has(chunk.mapping_id)) fail('duplicate mapping ID'); seen.add(chunk.mapping_id);
        requireText(chunk.reason, 'review reason'); await validateSource(chunk.source);
        if (record.chunks.indexOf(chunk) !== -1) {
          if (!range(chunk.en, record.english) || !Array.isArray(chunk.zh) || !chunk.zh.length ||
              !chunk.zh.every(function (r) { return range(r, record.translation); })) fail('display range invalid');
          if (slice(record.english, chunk.en) !== chunk.source.chunk_english) fail('reviewed English boundary changed');
          for (var i = 1; i < chunk.zh.length; i++) if (chunk.zh[i][0] < chunk.zh[i - 1][1]) fail('Chinese ranges overlap/are unordered');
          mappings++;
        } else {
          if (chunk.status !== 'unmapped' || chunk.en !== null || chunk.zh !== null || chunk.en_fragment !== null || chunk.zh_fragments !== null) fail('unmapped item has an unauthorized display range');
          unmapped++;
        }
      }
      if (!Array.isArray(record.source_comparisons)) fail('source comparisons absent');
      var comparisonIds = new Set(), comparedMappings = new Set();
      for (var comparison of record.source_comparisons) {
        requireText(comparison.english, 'comparison English'); requireText(comparison.translation, 'comparison Chinese');
        requireHash(comparison.english_hash, 'comparison English'); requireHash(comparison.translation_hash, 'comparison Chinese');
        if (await sha(comparison.english) !== comparison.english_hash || await sha(comparison.translation) !== comparison.translation_hash ||
            await sha(JSON.stringify([comparison.english_hash, comparison.translation_hash])) !== comparison.source_id) fail('comparison text/ID hash mismatch');
        if (comparisonIds.has(comparison.source_id)) fail('duplicate original comparison'); comparisonIds.add(comparison.source_id);
        if (!comparison.pins || !comparison.pins.index_files || !Array.isArray(comparison.chunks) || !comparison.chunks.length ||
            !Array.isArray(comparison.original_losses) || !Array.isArray(comparison.reviewers)) fail('comparison evidence absent');
        if (comparison.pins.english_hash !== comparison.english_hash || comparison.pins.translation_hash !== comparison.translation_hash) fail('comparison source pins disagree');
        for (var proof of comparison.chunks) {
          if (!seen.has(proof.mapping_id) || comparedMappings.has(proof.mapping_id)) fail('comparison mapping missing/duplicate');
          if (!range(proof.en, comparison.english) || !Array.isArray(proof.zh) || !proof.zh.length ||
              !proof.zh.every(function (r) { return range(r, comparison.translation); }) || proof.relation !== 'equivalent' ||
              slice(comparison.english, proof.en) !== proof.en_fragment || JSON.stringify(proof.zh.map(function (r) { return slice(comparison.translation, r); })) !== JSON.stringify(proof.zh_fragments)) fail('comparison chunk boundary invalid');
          requireText(proof.reason, 'comparison reason'); if (!Array.isArray(proof.source_refs) || !proof.source_refs.length) fail('comparison source refs absent');
          var original = record.chunks.concat(record.unmapped).find(function (item) { return item.mapping_id === proof.mapping_id; }).source;
          if (original.english !== comparison.english || original.translation !== comparison.translation ||
              JSON.stringify(original.chunk.en) !== JSON.stringify(proof.en) || JSON.stringify(original.chunk.zh) !== JSON.stringify(proof.zh)) fail('comparison is not the exact original mapping source');
          comparedMappings.add(proof.mapping_id);
        }
      }
      if (record.unmapped.some(function (item) { return !comparedMappings.has(item.mapping_id); })) fail('unmapped original comparison missing');
      var pairKey = key(record.english, record.translation);
      if (index.has(pairKey)) fail('duplicate exact display pair'); index.set(pairKey, record);
    }
    var token = Object.freeze({ schema: SCHEMA, records: index.size, mappings: mappings, unmapped: unmapped });
    prepared.set(token, index); return token;
  }
  async function load(pin, options) {
    options = options || {};
    if (!pin || typeof pin.url !== 'string') fail('projection URL absent'); requireHash(pin.sha256, 'projection file');
    var url;
    try { url = new URL(pin.url, window.location.href); } catch (_) { fail('projection URL outside exact candidate route'); }
    if (url.origin !== window.location.origin || !/^https?:$/.test(url.protocol) || url.username || url.password || url.hash || url.search ||
        !url.pathname.endsWith('/derived-chunk-display-projection/merge-own/candidate-v1/projection.json')) fail('projection URL outside exact candidate route');
    var response = await window.fetch(url.href, { credentials: 'same-origin', redirect: 'error', signal: options.signal });
    if (!response.ok || response.url !== url.href || response.redirected) fail('projection response URL/status rejected');
    var bytes = await response.arrayBuffer();
    if (bytes.byteLength > 16 * 1024 * 1024 || await digest(bytes) !== pin.sha256) fail('projection file size/hash mismatch');
    var data = JSON.parse(new window.TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (options.signal && options.signal.aborted) fail('projection load aborted');
    return prepare(data);
  }
  // Text offsets deliberately include every ordinary byte of whitespace. Only
  // the native renderer's exact label plus its one literal spacer are excluded.
  function view(container, nativeChinese) {
    var skip = new Set(), spacer = null, first = container.firstChild;
    if (nativeChinese && first && first.nodeType === 1 && first.matches('span.translate-tag') && first.textContent === '翻译') {
      skip.add(first);
      if (first.nextSibling && first.nextSibling.nodeType === 3 && first.nextSibling.data.startsWith(' ')) spacer = first.nextSibling;
    }
    var walker = container.ownerDocument.createTreeWalker(container, 4), nodes = [], text = '', node;
    while ((node = walker.nextNode())) {
      if (skip.has(node) || Array.from(skip).some(function (part) { return part.contains && part.contains(node); })) continue;
      var localStart = node === spacer ? 1 : 0, value = node.data.slice(localStart);
      if (value.length) nodes.push({ node: node, localStart: localStart, start: text.length, end: text.length + value.length }); text += value;
    }
    var offsets = [0], cursor = 0;
    for (var character of text) { cursor += character.length; offsets.push(cursor); }
    return { container: container, text: text, nodes: nodes, offsets: offsets };
  }
  function pairs(doc) {
    var result = [];
    doc.querySelectorAll('.example-card,.sf-sentence-pair').forEach(function (root) {
      if (root.closest(excluded)) return;
      var sf = root.classList.contains('sf-sentence-pair');
      function own(selector) { return Array.from(root.querySelectorAll(selector)).find(function (el) {
        return !el.closest(excluded) && el.closest('.example-card,.sf-sentence-pair') === root;
      }); }
      var en = own(sf ? '.sf-en' : '.example-text'), zh = own(sf ? '.sf-zh' : '.example-translation');
      if (en && zh) result.push({ root: root, en: view(en, false), zh: view(zh, !sf) });
    });
    return result;
  }
  function wholeIds(root) {
    var result = new Set();
    root.querySelectorAll('[data-chunk-sentence-ids]').forEach(function (el) {
      if (!el.closest(excluded) && el.closest('.example-card,.sf-sentence-pair') === root) ids(el.getAttribute('data-chunk-sentence-ids')).forEach(function (id) { result.add(id); });
    }); return result;
  }
  function inherited(node, root, whole) {
    var found = [];
    for (var parent = node.parentElement; parent && parent !== root; parent = parent.parentElement) {
      ids(parent.getAttribute('data-chunk-ids')).forEach(function (id) { if (!whole.has(id) && found.indexOf(id) < 0) found.push(id); });
    }
    return found;
  }
  function existingRanges(v, root, whole) {
    var result = new Map();
    v.nodes.forEach(function (part) { inherited(part.node, root, whole).forEach(function (id) {
      var ranges = result.get(id) || []; ranges.push([part.start, part.end]); result.set(id, ranges);
    }); });
    return Array.from(result, function (item) { return chunkRange(item[0], item[1]); });
  }
  function chunkRange(id, ranges) {
    var merged = [];
    ranges.forEach(function (r) {
      var last = merged[merged.length - 1]; if (last && last[1] === r[0]) last[1] = r[1]; else merged.push(r.slice());
    });
    return { id: id, ranges: merged, start: merged[0][0], end: merged[merged.length - 1][1], size: merged.reduce(function (sum, r) { return sum + r[1] - r[0]; }, 0) };
  }
  function targetRanges(v) {
    var found = new Map();
    v.nodes.forEach(function (part) {
      var mark = part.node.parentElement.closest(targetSelector);
      if (mark && v.container.contains(mark)) {
        var previous = found.get(mark); found.set(mark, previous ? [previous[0], part.end] : [part.start, part.end]);
      }
    }); return Array.from(found.values());
  }
  function finest(chunks, targets) {
    var selected = new Set();
    targets.forEach(function (target) {
      var covering = chunks.filter(function (chunk) { return chunk.ranges.some(function (r) { return r[0] <= target[0] && r[1] >= target[1]; }); });
      if (covering.length) {
        var size = Math.min.apply(null, covering.map(function (chunk) { return chunk.size; }));
        covering.filter(function (chunk) { return chunk.size === size; }).forEach(function (chunk) { selected.add(chunk.id); });
      } else chunks.filter(function (chunk) { return chunk.ranges.some(function (r) { return r[0] < target[1] && r[1] > target[0]; }); }).forEach(function (chunk) { selected.add(chunk.id); });
    }); return selected;
  }
  function install(doc, token, options) {
    options = options || {};
    if (!prepared.has(token)) fail('install requires an integrity-validated token');
    if (installed.has(doc)) {
      var old = installed.get(doc); if (old.token !== token) fail('different projection already installed'); return old;
    }
    var index = prepared.get(token), disposed = false, pending = false, busy = false;
    var processed = new WeakMap(), mutations = [], attributeChanges = [], titleChanges = [], comparisons = [], wrappers = new Set();
    var stats = { exactPairs: 0, mappedChunks: 0, sourceComparisons: 0, unmatchedPairs: 0, errors: [] };
    function changeClass(el, selected) {
      var before = el.getAttribute('class'); el.classList.toggle('sf-target-chunk', selected);
      if (before !== el.getAttribute('class')) attributeChanges.push({ el: el, before: before, after: el.getAttribute('class') });
    }
    function annotate(v, root, annotations, whole, targets) {
      var all = existingRanges(v, root, whole).concat(annotations.map(function (a) { return chunkRange(a.id, a.ranges); }));
      var defaults = finest(all, targets || []);
      v.container.querySelectorAll('.sf-target-chunk').forEach(function (el) { changeClass(el, ids(el.getAttribute('data-chunk-ids')).some(function (id) { return defaults.has(id); })); });
      v.nodes.forEach(function (part) {
        var boundaries = new Set([part.start, part.end]);
        annotations.forEach(function (a) { a.ranges.forEach(function (r) {
          if (r[0] > part.start && r[0] < part.end) boundaries.add(r[0]); if (r[1] > part.start && r[1] < part.end) boundaries.add(r[1]);
        }); });
        var cuts = Array.from(boundaries).sort(function (a, b) { return a - b; }), fragments = [], touched = false;
        if (part.localStart) fragments.push(doc.createTextNode(part.node.data.slice(0, part.localStart)));
        var oldIds = inherited(part.node, root, whole);
        for (var i = 0; i < cuts.length - 1; i++) {
          var start = cuts[i], end = cuts[i + 1];
          var active = annotations.filter(function (a) { return a.ranges.some(function (r) { return r[0] <= start && r[1] >= end; }); });
          var text = doc.createTextNode(part.node.data.slice(start - part.start + part.localStart, end - part.start + part.localStart));
          if (!active.length) { fragments.push(text); continue; }
          touched = true;
          var span = doc.createElement('span'); span.className = 'card-chunk';
          var activeIds = oldIds.concat(active.map(function (a) { return a.id; })).filter(function (id, n, values) { return values.indexOf(id) === n; });
          // A newly restored finer block takes precedence inside its own span;
          // existing IDs/outer spans remain intact. Stable ties keep old order.
          if (v.side === 'en') activeIds.sort(function (left, right) {
            return all.find(function (a) { return a.id === left; }).size - all.find(function (a) { return a.id === right; }).size;
          });
          span.setAttribute('data-chunk-side', v.side); span.setAttribute('data-chunk-ids', activeIds.join(' '));
          span.setAttribute('data-reviewed-chunk-projection', active.map(function (a) { return a.mapping_id; }).join(' '));
          span.setAttribute('title', active.map(function (a) { return a.title; }).filter(function (value, n, values) { return values.indexOf(value) === n; }).join('\n'));
          span.classList.toggle('sf-target-chunk', activeIds.some(function (id) { return defaults.has(id); }));
          // Focusable new fine fragments use the existing capture-click path.
          span.tabIndex = 0; span.setAttribute('aria-label', (v.side === 'en' ? '英文细块：' : '中文细块：') + text.data);
          span.append(text); wrappers.add(span); fragments.push(span);
        }
        if (!touched) return;
        var parent = part.node.parentNode, next = part.node.nextSibling, fragment = doc.createDocumentFragment();
        fragments.forEach(function (item) { fragment.append(item); });
        parent.replaceChild(fragment, part.node);
        mutations.push({ original: part.node, text: part.node.data, parent: parent, next: next, fragments: fragments });
      });
      return defaults;
    }
    function addComparison(pair, source, record, currentTargets, allocate) {
      var detail = doc.createElement('details'); detail.setAttribute('data-reviewed-source-comparison', source.source_id);
      var summary = doc.createElement('summary'); summary.textContent = '原译分块对照'; detail.append(summary);
      source.chunks.forEach(function (chunk) { var explanation = doc.createElement('p'); explanation.textContent = chunk.reason; detail.append(explanation); });
      var original = doc.createElement('div'); original.className = 'sf-sentence-pair example-card';
      var en = doc.createElement('p'); en.className = 'sf-en';
      var originalTargets = [];
      source.chunks.forEach(function (chunk) {
        var mapping = record.chunks.find(function (item) { return item.mapping_id === chunk.mapping_id; });
        if (!mapping) return; // Unmapped has no authorized current English range.
        currentTargets.forEach(function (target) {
          var start = pair.en.offsets.indexOf(target[0]), end = pair.en.offsets.indexOf(target[1]);
          if (start >= mapping.en[0] && end <= mapping.en[1]) {
            var originalRange = [chunk.en[0] + start - mapping.en[0], chunk.en[0] + end - mapping.en[0]];
            if (originalRange[0] < originalRange[1] && slice(source.english, originalRange) === slice(record.english, [start, end]) &&
                !originalTargets.some(function (r) { return r[0] === originalRange[0] && r[1] === originalRange[1]; })) originalTargets.push(originalRange);
          }
        });
      });
      var sourceText = points(source.english), cuts = new Set([0, sourceText.length]);
      originalTargets.forEach(function (r) { cuts.add(r[0]); cuts.add(r[1]); });
      var boundaries = Array.from(cuts).sort(function (a, b) { return a - b; });
      for (var n = 0; n < boundaries.length - 1; n++) {
        var begin = boundaries[n], finish = boundaries[n + 1], text = doc.createTextNode(sourceText.slice(begin, finish).join(''));
        if (originalTargets.some(function (r) { return r[0] <= begin && r[1] >= finish; })) {
          var mark = doc.createElement('mark'); mark.className = 'target-word'; mark.append(text); en.append(mark);
        } else en.append(text);
      }
      var zh = doc.createElement('p'); zh.className = 'sf-zh'; zh.textContent = source.translation; original.append(en, zh); detail.append(original);
      var provenance = doc.createElement('pre'); provenance.textContent = JSON.stringify({ pins: source.pins, original_losses: source.original_losses, reviewers: source.reviewers, source_refs: source.chunks.map(function (chunk) { return chunk.source_refs; }) }, null, 2); detail.append(provenance);
      pair.root.append(detail); comparisons.push(detail);
      var ev = view(en, false), zv = view(zh, false); ev.side = 'en'; zv.side = 'zh';
      // Base delegation searches descendants of the physical sentence. Reserve
      // distinct IDs even for nested comparison roots, preventing accidental
      // activation of a different original sentence by a current fine ID.
      var sourceChunks = source.chunks.map(function (chunk) { return { chunk: chunk, id: allocate() }; });
      var selected = annotate(ev, original, sourceChunks.map(function (entry) { return { id: entry.id, mapping_id: entry.chunk.mapping_id, title: entry.chunk.en_fragment + ' ↔ ' + entry.chunk.zh_fragments.join('…'), ranges: [[ev.offsets[entry.chunk.en[0]], ev.offsets[entry.chunk.en[1]]]] }; }), new Set(), targetRanges(ev));
      annotate(zv, original, sourceChunks.map(function (entry) { return { id: entry.id, mapping_id: entry.chunk.mapping_id, title: entry.chunk.en_fragment + ' ↔ ' + entry.chunk.zh_fragments.join('…'), ranges: entry.chunk.zh.map(function (r) { return [zv.offsets[r[0]], zv.offsets[r[1]]]; }) }; }), new Set(), []);
      zh.querySelectorAll('.card-chunk').forEach(function (el) { changeClass(el, ids(el.getAttribute('data-chunk-ids')).some(function (id) { return selected.has(id); })); });
      stats.sourceComparisons++;
    }
    function process(pair) {
      var exact = key(pair.en.text, pair.zh.text), prior = processed.get(pair.root);
      if (prior === exact) return;
      if (prior !== undefined) { stats.errors.push('An already projected pair changed text; dispose/reinstall required'); processed.set(pair.root, exact); return; }
      var record = index.get(exact); if (!record) { stats.unmatchedPairs++; processed.set(pair.root, exact); return; }
      var whole = wholeIds(pair.root), maximum = -1;
      pair.root.querySelectorAll('[data-chunk-ids],[data-chunk-sentence-ids]').forEach(function (el) {
        if (el.closest(excluded) || el.closest('.example-card,.sf-sentence-pair') !== pair.root) return;
        ids(el.getAttribute('data-chunk-ids')).concat(ids(el.getAttribute('data-chunk-sentence-ids'))).forEach(function (id) { maximum = Math.max(maximum, Number(id)); });
        if (ids(el.getAttribute('data-chunk-ids')).some(function (id) { return whole.has(id); })) fail('accepted whole-ID filter must run before projection');
        if (!ids(el.getAttribute('data-chunk-ids')).length && ids(el.getAttribute('data-chunk-sentence-ids')).some(function (id) { return whole.has(id); }) &&
            el.getAttribute('title') === '整句对应：已审校双语全文，非词语级对齐') {
          titleChanges.push({ el: el, original: el.getAttribute('title') }); el.removeAttribute('title');
        }
      });
      if (!Number.isSafeInteger(maximum + record.chunks.length + record.source_comparisons.reduce(function (count, comparison) { return count + comparison.chunks.length; }, 0))) fail('chunk ID exceeds safe integer');
      processed.set(pair.root, exact); stats.exactPairs++;
      pair.en.side = 'en'; pair.zh.side = 'zh';
      var chunks = record.chunks.map(function (chunk) { return { chunk: chunk, id: String(++maximum), title: chunk.source.chunk_english + ' ↔ ' + chunk.zh.map(function (r) { return slice(record.translation, r); }).join('…') }; });
      var target = targetRanges(pair.en);
      var chosen = annotate(pair.en, pair.root, chunks.map(function (entry) { return { id: entry.id, mapping_id: entry.chunk.mapping_id, title: entry.title, ranges: [[pair.en.offsets[entry.chunk.en[0]], pair.en.offsets[entry.chunk.en[1]]]] }; }), whole, target);
      annotate(pair.zh, pair.root, chunks.map(function (entry) { return { id: entry.id, mapping_id: entry.chunk.mapping_id, title: entry.title, ranges: entry.chunk.zh.map(function (r) { return [pair.zh.offsets[r[0]], pair.zh.offsets[r[1]]]; }) }; }), whole, []);
      // Chinese target chunks mirror the finest English IDs, not a guessed word.
      pair.zh.container.querySelectorAll('.card-chunk').forEach(function (el) { changeClass(el, ids(el.getAttribute('data-chunk-ids')).some(function (id) { return chosen.has(id); })); });
      stats.mappedChunks += chunks.length;
      record.source_comparisons.forEach(function (source) { addComparison(pair, source, record, target, function () { return String(++maximum); }); });
    }
    function refresh() {
      if (disposed || busy || (options.isCurrent && !options.isCurrent())) return;
      busy = true;
      try { pairs(doc).forEach(function (pair) { try { process(pair); } catch (error) { stats.errors.push(error.message); if (options.onError) options.onError(error); } }); }
      finally { busy = false; }
    }
    function keyboard(event) {
      if (disposed || event.defaultPrevented || event.repeat || event.ctrlKey || event.altKey || event.metaKey || (event.key !== 'Enter' && event.key !== ' ')) return;
      var el = event.target;
      if (!wrappers.has(el) || el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable]')) return;
      event.preventDefault();
      el.dispatchEvent(new doc.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    }
    var observer = new MutationObserver(function () {
      if (pending || disposed) return; pending = true;
      Promise.resolve().then(function () { pending = false; refresh(); });
    });
    var handle = { token: token, refresh: refresh, stats: function () { return JSON.parse(JSON.stringify(stats)); }, dispose: function () {
      if (disposed) return; disposed = true; observer.disconnect(); doc.removeEventListener('keydown', keyboard, true);
      var child = doc.defaultView, state = child && child.__ankiCardChunkState;
      if (state && Array.from(wrappers).some(function (el) { return el.closest('.example-card') === state.root; })) {
        state.root.querySelectorAll('.card-chunk-active').forEach(function (el) { el.classList.remove('card-chunk-active'); }); child.__ankiCardChunkState = null;
      }
      titleChanges.forEach(function (item) { if (!item.el.hasAttribute('title')) item.el.setAttribute('title', item.original); });
      attributeChanges.reverse().forEach(function (item) { if (item.el.getAttribute('class') === item.after) { if (item.before === null) item.el.removeAttribute('class'); else item.el.setAttribute('class', item.before); } });
      mutations.reverse().forEach(function (item) {
        var exact = item.fragments.every(function (fragment, n) { return fragment.parentNode === item.parent && (n === 0 || item.fragments[n - 1].nextSibling === fragment); });
        if (exact && item.fragments.map(function (part) { return part.textContent; }).join('') === item.text && item.original.data === item.text) {
          item.parent.insertBefore(item.original, item.fragments[0]); item.fragments.forEach(function (part) { part.remove(); });
        } else item.fragments.forEach(function (part) { if (wrappers.has(part) && part.parentNode) part.replaceWith.apply(part, Array.from(part.childNodes)); });
      });
      comparisons.forEach(function (el) { el.remove(); }); installed.delete(doc);
    } };
    installed.set(doc, handle); doc.addEventListener('keydown', keyboard, true); refresh();
    observer.observe(doc.documentElement, { childList: true, subtree: true, characterData: true }); return handle;
  }
  window.AnkiReviewedChunkProjection = Object.freeze({ prepare: prepare, load: load, install: install });
})();

/* OWN display-only consumer. Fetch belongs to the existing shell load hook.
 * Packed reader links must already be inflated by the card's pinned decoder.
 * No input handlers, text edits, frequency edits, ownership edits or AJAX.
 */
(function () {
  'use strict';
  if (window.AnkiSharedReadingBankRuntime) return;
  var SIDECAR_SHA = 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5';
  var installed = new WeakMap(), indexes = new WeakMap();
  var histories = '.sf-ownership-history,.sf-original-history-panel,.sf-ownership-authority,' +
    '.sf-archived-example,.sf-archived-native-example,.sf-inline-history,[data-native-ownership-history]';
  var sfRoots = '.sf-example,.sf-source-preview,.sf-year-preview';
  function demand(condition, message) { if (!condition) throw new Error(message); }
  function digest(value) {
    demand(window.crypto && window.crypto.subtle && window.TextEncoder, 'shared bank SHA runtime unavailable');
    return window.crypto.subtle.digest('SHA-256', new window.TextEncoder().encode(value)).then(function (buffer) {
      return Array.from(new Uint8Array(buffer)).map(function (n) { return n.toString(16).padStart(2, '0'); }).join('');
    });
  }
  function noSingleQuestion(part) {
    if (!part || typeof part !== 'object' || Array.isArray(part)) return false;
    return ['questionId', 'question_id'].every(function (key) { return part[key] === undefined || part[key] === null; });
  }
  function buildIndex(metadata) {
    demand(metadata && typeof metadata === 'object' && metadata.schema === 'exam-usage-shared-reading-bank.v5',
      'invalid shared bank sidecar');
    if (indexes.has(metadata)) return indexes.get(metadata);
    // The approved Python sidecar has exactly this serialized byte form.
    // Verify the whole fixed file pin before consuming any classifications.
    var bytes = JSON.stringify(metadata, null, 2) + '\n';
    var job = digest(bytes).then(function (actual) {
      demand(actual === SIDECAR_SHA, 'shared bank sidecar byte SHA mismatch');
      var snapshot = JSON.parse(bytes), groups = new Map(), bindings = new Map();
      snapshot.groups.forEach(function (group) { groups.set(group.group_id, group); });
      snapshot.sentence_bindings.forEach(function (binding) {
        demand(!bindings.has(binding.sentence_id), 'duplicate shared bank sentence identity');
        var group = groups.get(binding.group_id);
        demand(group && group.paper_id === binding.paper_id, 'shared bank binding group missing');
        var options = group.bank.filter(function (option) { return option.source_option_id === binding.source_option_id; });
        demand(options.length === 1, 'shared bank option identity ambiguous');
        bindings.set(binding.sentence_id, { binding: binding, group: group, option: options[0] });
      });
      var missing = snapshot.groups.filter(function (group) { return group.status === 'unknown'; });
      return { bindings: bindings, groups: groups,
        diagnostics: { sidecar_sha256: SIDECAR_SHA, verified_groups: snapshot.summary.verified_groups,
          missing_bank_groups: missing.map(function (group) { return {
            group_id: group.group_id, paper_id: group.paper_id, question_range: group.question_range,
            unknown_reasons: group.unknown_reasons, questions: group.questions.length
          }; }),
          unknown_questions: missing.reduce(function (n, group) { return n + group.questions.length; }, 0),
          info_text: '已审44套卷：27组共享选项库可核；另12组冻结题组缺原选项库，共60题答案对应仍未核实。未绑定原句保持原标签，不猜逐句归属。' } };
    });
    indexes.set(metadata, job);
    return job;
  }
  function oneParam(url, name) {
    var values = url.searchParams.getAll(name);
    demand(values.length === 1 && values[0], 'missing or duplicate original reader identity');
    return values[0];
  }
  function route(value, base) {
    var url = new URL(value, base);
    demand((url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password,
      'invalid original reader route');
    var id = oneParam(url, 'anki-codex-sentence');
    var match = /^(kaoyan:([0-9]{4}-0[12])):/.exec(id);
    demand(match, 'invalid original source sentence ID');
    var paper = match[1], name = match[2];
    if (url.pathname === '/exam-library/practice/full-paper.htm') {
      demand(oneParam(url, 'paper') === paper, 'original reader route paper differs');
    } else {
      demand(url.pathname === '/english-exams-reflow-latex/kaoyan/papers/' + name + '.htm',
        'original reader route is not the same source paper');
    }
    var englishHash = oneParam(url, 'anki-codex-hash'), reviewHash = oneParam(url, 'anki-codex-review');
    demand(/^[a-f0-9]{64}$/.test(englishHash) && /^[a-f0-9]{64}$/.test(reviewHash),
      'original reader source hashes malformed');
    var ranges = JSON.parse(oneParam(url, 'anki-codex-en'));
    demand(Array.isArray(ranges) && ranges.every(function (range) {
      return Array.isArray(range) && range.length === 2 && range.every(Number.isSafeInteger) &&
        range[0] >= 0 && range[0] < range[1];
    }), 'original reader target ranges malformed');
    var contexts = url.searchParams.getAll('anki-codex-context');
    demand(contexts.length <= 1, 'duplicate original reader candidate context');
    if (contexts.length) {
      var context = JSON.parse(contexts[0]);
      demand(noSingleQuestion(context), 'shared bank dual-key candidate claims a single question');
      ['reading_candidate', 'derivation_payload', 'option_context', 'reading_completion'].forEach(function (key) {
        if (context[key] !== undefined && context[key] !== null) {
          demand(noSingleQuestion(context[key]), 'shared bank dual-key derived source claims a single question');
        }
      });
    }
    return { sentence_id: id, paper_id: paper, english_hash: englishHash, review_hash: reviewHash, ranges: ranges };
  }
  function anchorIdentity(anchor, base) {
    demand(!anchor.hasAttribute('data-rb-j') && anchor.getAttribute('aria-disabled') !== 'true',
      'original reader anchor has not been successfully inflated');
    var values = ['href', 'data-latex-url', 'data-full-paper-url'].map(function (key) {
      return anchor.getAttribute(key);
    }).filter(Boolean);
    demand(values.length > 0, 'original reader anchor missing');
    var identities = values.map(function (value) { return route(value, base); });
    demand(identities.every(function (identity) { return JSON.stringify(identity) === JSON.stringify(identities[0]); }),
      'original reader anchors carry conflicting source identities');
    var candidate = anchor.getAttribute('data-reading-candidate');
    if (candidate !== null) {
      var parsedCandidate = JSON.parse(candidate);
      demand(noSingleQuestion(parsedCandidate), 'shared bank dual-key DOM candidate claims a question');
      ['reading_candidate', 'derivation_payload', 'option_context', 'reading_completion'].forEach(function (key) {
        if (parsedCandidate[key] !== undefined && parsedCandidate[key] !== null) {
          demand(noSingleQuestion(parsedCandidate[key]), 'shared bank dual-key DOM derived source claims a question');
        }
      });
    }
    return identities[0];
  }
  function owned(container, element, kind) {
    if (element.closest(histories)) return false;
    return kind === 'native' ? element.closest('.example-card') === container : element.closest(sfRoots) === container;
  }
  function findOwned(container, selector, kind) {
    return Array.from(container.querySelectorAll(selector)).filter(function (element) { return owned(container, element, kind); });
  }
  function display(entry) {
    var option = entry.option, group = entry.group;
    var numbers = group.questions.filter(function (question) {
      return option.matched_question_ids.indexOf(question.question_id) !== -1;
    }).map(function (question) { return question.number; });
    var span = group.question_range[0] + '–' + group.question_range[1];
    var label = option.correctness === 'correct' ? '正确选项 ' + option.label + ' · 对应第' + numbers.join('、') + '题' :
      option.correctness === 'incorrect' ? '错误选项 ' + option.label + ' · ' + span + '题共享干扰项' :
      '答案未核实 ' + option.label + ' · ' + span + '题共享选项库';
    return { schema: 'exam-usage-shared-reading-bank-display.v5', group_id: group.group_id, question_id: null,
      option_label: option.label, source_option_id: option.source_option_id, correctness: option.correctness,
      matched_question_ids: option.matched_question_ids, matched_question_numbers: numbers,
      applicable_question_ids: group.questions.map(function (question) { return question.question_id; }),
      question_range: group.question_range, display_label: label, counting_effect: 'none',
      match_origins: ['option'], binding_sha256: entry.binding.binding_sha256,
      group_evidence_sha256: group.group_evidence_sha256 };
  }
  function install(root, metadata) {
    demand(root && root.querySelectorAll && (root.ownerDocument || root).createElement, 'shared bank DOM root invalid');
    if (installed.has(root)) return installed.get(root);
    var doc = root.ownerDocument || root, originals = new Map(), disposed = false, pending = false, generation = 0;
    var currentStats = {}, diagnostics = null, indexReady = buildIndex(metadata);
    function stamp(element, evidence, container) {
      if (!originals.has(element)) originals.set(element, { created: false, html: element.innerHTML,
        attributes: {}, lastHtml: null, lastAttributes: {}, container: container });
      var record = originals.get(element);
      var values = { 'data-shared-reading-bank-group-id': evidence.group_id,
        'data-shared-reading-bank-evidence': JSON.stringify(evidence),
        'data-shared-reading-bank-question-id': 'null',
        'data-shared-reading-bank-matched-question-ids': JSON.stringify(evidence.matched_question_ids) };
      Object.keys(values).forEach(function (key) {
        if (!(key in record.attributes)) record.attributes[key] = element.getAttribute(key);
        if (element.getAttribute(key) !== values[key]) element.setAttribute(key, values[key]);
        record.lastAttributes[key] = values[key];
      });
      return record;
    }
    function restore(element, record) {
      if (record.created && element.innerHTML === record.lastHtml && Object.keys(record.lastAttributes).every(function (key) {
        return element.getAttribute(key) === record.lastAttributes[key];
      })) { element.remove(); return; }
      if (element.innerHTML === record.lastHtml) element.innerHTML = record.html;
      Object.keys(record.attributes).forEach(function (key) {
        if (element.getAttribute(key) !== record.lastAttributes[key]) return;
        if (record.attributes[key] === null) element.removeAttribute(key);
        else element.setAttribute(key, record.attributes[key]);
      });
    }
    function retract(container) {
      originals.forEach(function (record, element) {
        if (record.container === container) { restore(element, record); originals.delete(element); }
      });
    }
    function apply(container, kind, evidence) {
      var labels = findOwned(container, '.exam-usage-labels', kind);
      demand(labels.length <= 1, 'shared bank display usage positions ambiguous');
      var label = labels[0], created = !label;
      var candidates = Array.from(label ? label.children : []).filter(function (child) {
        return /^(正确选项|错误选项|答案未核实) [A-H](?:$| ·)/.test(child.textContent);
      });
      demand(candidates.length <= 1, 'shared bank candidate labels ambiguous');
      var chip = candidates[0];
      if (chip) {
        var printed = /^(正确选项|错误选项|答案未核实) ([A-H])/.exec(chip.textContent);
        demand(printed[2] === evidence.option_label, 'shared bank existing printed letter conflicts');
        demand(printed[1] === '答案未核实' || printed[1] === (evidence.correctness === 'correct' ? '正确选项' : '错误选项'),
          'shared bank existing explicit correctness conflicts');
      }
      var place;
      if (!label) {
        place = kind === 'native' ? findOwned(container, '.example-source', kind) : findOwned(container, '.sf-source', kind);
        demand(place.length >= 1, 'shared bank source label position absent');
        label = doc.createElement('span'); label.className = 'exam-usage-labels';
        label.style.cssText = 'display:flex;flex-wrap:wrap;gap:.3rem;margin:.3rem 0;font-size:12px;line-height:1.5;color:var(--muted,#63718a)';
      }
      // All identity, source and existing-label checks finish before the first
      // mutation, so a rejected candidate cannot leave partial decorations.
      var record = stamp(label, evidence, container); if (created) { record.created = true; place[0].after(label); }
      if (!chip) {
        chip = doc.createElement('span'); chip.style.cssText = 'padding:1px 5px;border-radius:4px;background:var(--surface-soft,#f2f5fa)';
        label.prepend(chip);
      }
      if (chip.textContent !== evidence.display_label) chip.textContent = evidence.display_label;
      if (!Array.from(label.children).some(function (child) { return child.textContent === '匹配来自选项'; })) {
        var origin = doc.createElement('span'); origin.textContent = '匹配来自选项';
        origin.style.cssText = 'padding:1px 5px;border-radius:4px;background:var(--surface-soft,#f2f5fa)'; label.append(origin);
      }
      record.lastHtml = label.innerHTML;
    }
    async function process(container, kind, index, version, stats) {
      if (container.closest(histories)) { stats.skippedHistory++; return; }
      try {
        var anchors = findOwned(container, 'a.sentence-jump', kind);
        demand(anchors.length === 1, 'shared bank original source anchor count differs from one');
        var anchor = anchors[0], identity = anchorIdentity(anchor, doc.baseURI);
        var entry = index.bindings.get(identity.sentence_id);
        if (!entry) { stats.unbound++; retract(container); return; }
        var binding = entry.binding;
        demand(identity.paper_id === binding.paper_id && identity.english_hash === binding.english_hash &&
          identity.review_hash === binding.reviewed_content_hash, 'shared bank original source hash/review binding differs');
        var english = findOwned(container, kind === 'native' ? '.example-text' : '.sf-en', kind);
        demand(english.length === 1 && english[0].textContent === binding.english, 'shared bank actual English differs');
        demand(identity.ranges.every(function (range) { return range[1] <= Array.from(binding.english).length; }),
          'shared bank original target bounds differ');
        var text = english[0].textContent;
        demand(await digest(text) === binding.english_hash, 'shared bank actual English SHA differs');
        if (disposed || version !== generation || !root.contains(container)) return;
        demand(english[0].textContent === text && JSON.stringify(anchorIdentity(anchor, doc.baseURI)) === JSON.stringify(identity),
          'shared bank source changed during async verification');
        apply(container, kind, display(entry));
        stats[kind === 'native' ? 'projectedNative' : container.matches('.sf-source-preview,.sf-year-preview') ? 'projectedPreview' : 'projectedSf']++;
      } catch (error) {
        if (disposed || version !== generation) return;
        retract(container);
        stats.rejected++;
        stats.rejectionReasons[error.message] = (stats.rejectionReasons[error.message] || 0) + 1;
      }
    }
    async function refresh() {
      if (disposed) return currentStats;
      var version = ++generation, index = await indexReady;
      if (disposed || version !== generation) return currentStats;
      diagnostics = index.diagnostics;
      var stats = { projectedNative: 0, projectedSf: 0, projectedPreview: 0, unbound: 0, rejected: 0, skippedHistory: 0, rejectionReasons: {} };
      var containers = Array.from(root.querySelectorAll(sfRoots)).map(function (container) { return [container, 'sf']; });
      root.querySelectorAll('.example-card').forEach(function (container) {
        if (!container.closest(sfRoots)) containers.push([container, 'native']);
      });
      await Promise.all(containers.map(function (entry) { return process(entry[0], entry[1], index, version, stats); }));
      if (!disposed && version === generation) currentStats = stats;
      return currentStats;
    }
    var observer = new window.MutationObserver(function (records) {
      var relevant = records.some(function (record) {
        var element = record.target.nodeType === 1 ? record.target : record.target.parentElement;
        if (element && element.closest('.exam-usage-labels')) return false;
        if (record.type === 'childList') {
          var changed = Array.from(record.addedNodes).concat(Array.from(record.removedNodes));
          if (changed.length && changed.every(function (node) {
            return node.nodeType === 1 && node.matches('.exam-usage-labels');
          })) return false;
        }
        return true;
      });
      if (!relevant) return;
      if (pending || disposed) return;
      pending = true;
      Promise.resolve().then(function () { pending = false; if (!disposed) refresh().catch(function () {}); });
    });
    var handle = { refresh: refresh,
      stats: function () { return JSON.parse(JSON.stringify(currentStats)); },
      diagnostics: function () { return diagnostics && JSON.parse(JSON.stringify(diagnostics)); },
      dispose: function () {
        if (disposed) return;
        disposed = true; generation++; observer.disconnect();
        originals.forEach(function (record, element) { restore(element, record); });
        installed.delete(root);
      }
    };
    installed.set(root, handle);
    observer.observe(root.nodeType === 9 ? root.documentElement : root, { childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['href', 'data-latex-url', 'data-full-paper-url', 'data-rb-j', 'data-reading-candidate'] });
    handle.ready = refresh();
    return handle;
  }
  window.AnkiSharedReadingBankRuntime = Object.freeze({ install: install, sidecarSha256: SIDECAR_SHA });
})();

/* Presentation only: physical occurrences and all source evidence remain intact. */
(function () {
  'use strict';
  var installed = new WeakMap();
  function ids(el) { var raw = el.getAttribute('data-chunk-ids') || ''; return /^\d+( \d+)*$/.test(raw) ? raw.split(' ') : []; }
  function textView(el) {
    var walker = el.ownerDocument.createTreeWalker(el, 4), nodes = [], offset = 0, node;
    while ((node = walker.nextNode())) { nodes.push({ node: node, start: offset, end: offset + node.data.length }); offset += node.data.length; }
    return { text: el.textContent, nodes: nodes };
  }
  function ranges(view, predicate) {
    var found = new Map();
    view.nodes.forEach(function (part) {
      for (var el = part.node.parentElement; el && el !== part.node.ownerDocument; el = el.parentElement) {
        if (!el.contains(part.node) || !predicate(el)) continue;
        var values = found.get(el) || []; values.push([part.start, part.end]); found.set(el, values);
      }
    });
    return Array.from(found, function (entry) { return { el: entry[0], ranges: entry[1] }; });
  }
  function mergeRanges(values) {
    var result = [];
    values.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; }).forEach(function (r) {
      var last = result[result.length - 1]; if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]); else result.push(r.slice());
    }); return result;
  }
  function chunkGraph(pair) {
    var graph = new Map();
    ['en', 'zh'].forEach(function (side) {
      var paragraph = pair.querySelector('.sf-' + side), view = textView(paragraph);
      ranges(view, function (el) { return el.classList.contains('card-chunk') && paragraph.contains(el); }).forEach(function (entry) {
        ids(entry.el).forEach(function (id) { var record = graph.get(id) || { en: [], zh: [] }; record[side].push.apply(record[side], entry.ranges); graph.set(id, record); });
      });
    });
    var result = new Map(); graph.forEach(function (record, id) { result.set(id, JSON.stringify({ en: mergeRanges(record.en), zh: mergeRanges(record.zh) })); }); return result;
  }
  function sourceKey(source, en, zh) { return JSON.stringify([source, en, zh]); }
  function physicalNativeIndex(doc) {
    var result = new Map();
    doc.querySelectorAll('li.example-card,li._r28').forEach(function (row) {
      var en = row.querySelector('.example-text,._r31'), zh = row.querySelector('.example-translation,._r34'), source = row.querySelector('.example-source,._r36');
      var link = row.querySelector('.sentence-jump,[data-rb-j]'); if (!en || !zh || !source || !link) return;
      var translation = zh.cloneNode(true); translation.querySelectorAll('.translation-label,.translate-tag,._r35').forEach(function (el) { el.remove(); });
      var identity;
      try {
        if (link.hasAttribute('data-rb-j')) {
          var fields = link.getAttribute('data-rb-j').split('|');
          if (fields.length < 6 || !/^[A-Za-z0-9_-]{43}$/.test(fields[3]) || !/^[A-Za-z0-9_-]{43}$/.test(fields[4])) return;
          identity = JSON.stringify(['kaoyan:' + fields[1] + ':' + decodeURIComponent(fields[2]), fields[3], fields[4]]);
        } else {
          var url = new URL(link.href, doc.URL), p = url.searchParams;
          if (!p.get('anki-codex-sentence') || !/^[a-f0-9]{64}$/.test(p.get('anki-codex-hash') || '') || !/^[a-f0-9]{64}$/.test(p.get('anki-codex-review') || '')) return;
          identity = JSON.stringify([p.get('anki-codex-sentence'), p.get('anki-codex-hash'), p.get('anki-codex-review')]);
        }
      } catch (_) { return; }
      var key = sourceKey(source.textContent.trim(), en.textContent, translation.textContent.trim()), identities = result.get(key) || new Set(); identities.add(identity); result.set(key, identities);
    }); return result;
  }
  function install(doc) {
    if (installed.has(doc)) return installed.get(doc);
    var disposed = false, groups = [], restores = [], processed = new WeakSet(), style = doc.createElement('style');
    style.textContent = '.sf-group-evidence{margin-block:.6rem;min-width:0;overflow-wrap:anywhere}.sf-group-evidence>summary{cursor:pointer;min-height:36px;display:flex;align-items:center}.sf-group-member-evidence{border-top:1px solid #e5ebf4;padding-block:.5rem}.sf-group-member-evidence pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}'; doc.head.append(style);
    function attribute(el, name, value) { var before = el.getAttribute(name); restores.push(function () { if (before === null) el.removeAttribute(name); else el.setAttribute(name, before); }); el.setAttribute(name, value); }
    function relocate(el, parent) { var before = el.parentNode, next = el.nextSibling; restores.push(function () { before.insertBefore(el, next && next.parentNode === before ? next : null); }); parent.append(el); }
    function markTargets(en, targets) {
      var view = textView(en);
      view.nodes.forEach(function (part) {
        if (part.node.parentElement.closest('mark.target-word')) return;
        var cuts = new Set([part.start, part.end]); targets.forEach(function (r) { if (r[0] > part.start && r[0] < part.end) cuts.add(r[0]); if (r[1] > part.start && r[1] < part.end) cuts.add(r[1]); });
        var bounds = Array.from(cuts).sort(function (a, b) { return a - b; }), fragments = [], touched = false;
        for (var n = 0; n < bounds.length - 1; n++) {
          var start = bounds[n], end = bounds[n + 1], text = doc.createTextNode(part.node.data.slice(start - part.start, end - part.start));
          if (targets.some(function (r) { return r[0] <= start && r[1] >= end; })) { var mark = doc.createElement('mark'); mark.className = 'target-word'; mark.append(text); fragments.push(mark); touched = true; } else fragments.push(text);
        }
        if (!touched) return;
        var parent = part.node.parentNode, next = part.node.nextSibling; fragments.forEach(function (el) { parent.insertBefore(el, part.node); }); part.node.remove();
        restores.push(function () { parent.insertBefore(part.node, fragments[0] && fragments[0].parentNode === parent ? fragments[0] : next && next.parentNode === parent ? next : null); fragments.forEach(function (el) { el.remove(); }); });
      });
    }
    function updatePanel(panel) {
      var filter = panel.querySelector('[data-sf-filter][aria-pressed="true"]'), year = filter ? filter.dataset.sfFilter : 'all';
      groups.filter(function (group) { return group.panel === panel; }).forEach(function (group) {
        group.members.forEach(function (member, n) { member.hidden = n > 0 || (year !== 'all' && member.dataset.sfYear !== year); });
      });
      var status = panel.querySelector('.sf-preview-count'); if (!status) return;
      var count = Array.from(panel.querySelectorAll(':scope > .sf-example')).filter(function (row) { return !row.hidden; }).length;
      var label = '显示 ' + count + ' 条原文'; if (status.textContent !== label) status.textContent = label;
    }
    function refresh() {
      if (disposed) return; var natives = physicalNativeIndex(doc);
      doc.querySelectorAll('.sf-sense > .sf-panel').forEach(function (panel) {
        var buckets = new Map();
        panel.querySelectorAll(':scope > .sf-example').forEach(function (row) {
          if (processed.has(row)) return;
          var pair = row.querySelector(':scope > .sf-sentence-pair'), source = row.querySelector(':scope > .sf-source'), oid = row.dataset.sfOccurrenceId;
          if (!pair || !source || !/^[a-f0-9]{64}$/.test(oid || '')) return;
          var en = pair.querySelector(':scope > .sf-en'), zh = pair.querySelector(':scope > .sf-zh'); if (!en || !zh) return;
          var physical = natives.get(sourceKey(source.textContent.trim(), en.textContent, zh.textContent.trim())); if (!physical || physical.size !== 1) return;
          var usage = row.querySelector(':scope > .exam-usage-labels'), graph = chunkGraph(pair);
          var signature = Array.from(graph.values()).sort();
          var key = JSON.stringify([Array.from(physical)[0], row.dataset.sfYear, source.textContent.trim(), en.textContent, zh.textContent, usage ? usage.textContent : '', signature]);
          var bucket = buckets.get(key) || []; bucket.push({ row: row, pair: pair, graph: graph }); buckets.set(key, bucket);
        });
        buckets.forEach(function (entries) {
          if (entries.length < 2) return;
          var memberIds = entries.map(function (entry) { return entry.row.dataset.sfOccurrenceId; }); if (new Set(memberIds).size !== memberIds.length) return;
          var first = entries[0], chosen = new Set(), targets = [], bySignature = new Map();
          first.graph.forEach(function (signature, id) { if (!bySignature.has(signature)) bySignature.set(signature, []); bySignature.get(signature).push(id); });
          entries.forEach(function (entry) {
            processed.add(entry.row);
            var en = entry.pair.querySelector(':scope > .sf-en');
            ranges(textView(en), function (el) { return el.matches('mark.target-word') && en.contains(el); }).forEach(function (record) { targets.push.apply(targets, record.ranges); });
            entry.pair.querySelectorAll(':scope > p .sf-target-chunk').forEach(function (el) { ids(el).forEach(function (id) { (bySignature.get(entry.graph.get(id)) || []).forEach(function (mapped) { chosen.add(mapped); }); }); });
          });
          markTargets(first.pair.querySelector(':scope > .sf-en'), mergeRanges(targets));
          first.pair.querySelectorAll(':scope > p .card-chunk').forEach(function (el) { if (ids(el).some(function (id) { return chosen.has(id); }) && !el.classList.contains('sf-target-chunk')) attribute(el, 'class', el.className + ' sf-target-chunk'); });
          attribute(first.row, 'data-sf-group-member-ids', JSON.stringify(memberIds)); attribute(first.row, 'data-sf-group-occurrences', String(entries.length));
          var detail = doc.createElement('details'); detail.className = 'sf-group-evidence'; var summary = doc.createElement('summary'); summary.textContent = '本句各处依据与归属说明'; detail.append(summary); first.row.append(detail);
          restores.push(function () { detail.remove(); });
          entries.forEach(function (entry, n) {
            var section = doc.createElement('section'); section.className = 'sf-group-member-evidence'; section.dataset.sfGroupMemberId = memberIds[n]; detail.append(section);
            var label = doc.createElement('p'); label.className = 'sf-source'; label.textContent = '目标位置 ' + (n + 1); section.append(label);
            Array.from(entry.row.children).filter(function (el) { return el !== entry.pair && el !== detail && !el.matches('.sf-source,.exam-usage-labels'); }).forEach(function (el) { relocate(el, section); });
            entry.pair.querySelectorAll(':scope > [data-reviewed-source-comparison]').forEach(function (el) { relocate(el, section); });
            var hidden = entry.row.hidden; restores.push(function () { entry.row.hidden = hidden; });
          });
          groups.push({ panel: panel, members: entries.map(function (entry) { return entry.row; }) });
        });
        if (!panel.hasAttribute('data-sf-group-count-ready')) { var status = panel.querySelector('.sf-preview-count'), old = status && status.textContent; if (status) restores.push(function () { status.textContent = old; }); attribute(panel, 'data-sf-group-count-ready', 'true'); }
        updatePanel(panel);
      });
    }
    function filter(event) { var button = event.target.closest && event.target.closest('[data-sf-filter]'), panel = button && button.closest('.sf-panel'); if (panel) updatePanel(panel); }
    var handle = { refresh: refresh, stats: function () { return { groups: groups.length, groupedOccurrences: groups.reduce(function (n, group) { return n + group.members.length; }, 0), hiddenDuplicateRows: groups.reduce(function (n, group) { return n + group.members.length - 1; }, 0) }; }, dispose: function () { if (disposed) return; disposed = true; doc.removeEventListener('click', filter, true); restores.reverse().forEach(function (restore) { restore(); }); style.remove(); installed.delete(doc); } };
    installed.set(doc, handle); doc.addEventListener('click', filter, true); refresh(); return handle;
  }
  window.AnkiSameSenseGroupRuntime = Object.freeze({ install: install });
})();

(function () {
  'use strict';

  var ALL_DECKS = 'all';
  var readerStorageKey = 'anki:exam-source-reader:v1';
  // Only embedded web previews receive these constraints. The shared Anki
  // templates retain their styling, while text and controls fit the frame.
  var responsiveCardCss = [
    'html.anki-library-card, .anki-library-card body { width: 100%; min-width: 0; max-width: 100%; margin: 0; overflow-wrap: anywhere; }',
    '.anki-library-card * { box-sizing: border-box; }',
    '.anki-library-card *::before, .anki-library-card *::after { box-sizing: border-box; }',
    '.anki-library-card #preview-front, .anki-library-card #preview-back { width: 100%; min-width: 0; max-width: 100%; }',
    '.anki-library-card .vocab-card { min-width: 0; max-width: 100%; }',
    '.anki-library-card .front-box, .anki-library-card .center-container, .anki-library-card .word-wrapper, .anki-library-card .meaning-section, .anki-library-card .field-callout, .anki-library-card .field-content, .anki-library-card .examples-section, .anki-library-card .examples, .anki-library-card .examples li, .anki-library-card .example-heading, .anki-library-card .examples-bar, .anki-library-card .sense-row, .anki-library-card .forms-list, .anki-library-card .form-row, .anki-library-card .audio-line, .anki-library-card .recorded-audio { min-width: 0; max-width: 100%; }',
    '.anki-library-card .vocab-front, .anki-library-card .vocab-back { padding-inline: clamp(.65rem, 3vw, 1.5rem); }',
    '.anki-library-card .front-box { padding-inline: clamp(.75rem, 6vw, 3.5rem); }',
    '.anki-library-card .meaning-section { padding-inline: clamp(.6rem, 3vw, 1.3rem); }',
    '.anki-library-card .examples li { padding-inline: clamp(.6rem, 3vw, 1.25rem); }',
    '.anki-library-card .card-meta, .anki-library-card .word, .anki-library-card .phonetic-line, .anki-library-card .field-content, .anki-library-card .sense-pos, .anki-library-card .sense-text, .anki-library-card .form-row dt, .anki-library-card .form-row dd, .anki-library-card .example-text, .anki-library-card .example-translation, .anki-library-card .example-source, .anki-library-card .sentence-status, .anki-library-card .personal-note { min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: normal; white-space: normal; }',
    '.anki-library-card .word-wrapper { display: inline-grid; grid-template-columns: 44px minmax(0, 1fr) 44px; column-gap: .4rem; justify-content: center; align-items: start; }',
    '.anki-library-card .word { grid-column: 2; }',
    '.anki-library-card .dictionary-link { position: static; grid-column: 3; align-self: start; max-width: 100%; margin-top: -.35rem; }',
    '.anki-library-card .example-heading { flex-wrap: wrap; }',
    '.anki-library-card .example-text { flex: 1 1 0; }',
    '.anki-library-card .sentence-jump { max-width: 100%; margin-right: 0; }',
    '.anki-library-card .source-reader-setting, .anki-library-card .source-reader { min-width: 0; max-width: 100%; white-space: normal; }',
    '.anki-library-card img, .anki-library-card audio, .anki-library-card video, .anki-library-card button { max-width: 100%; }',
    '@media (max-width: 480px) { .anki-library-card .word.anki-preview-long-word { font-size: 6vw; } }',
    '@media (max-width: 300px) { .anki-library-card .word.anki-preview-long-word { font-size: 1.125rem; } }',
    '@media (max-width: 420px) { .anki-library-card .form-row { grid-template-columns: minmax(0, 1fr); } }'
  ].join('\n');
  var elements = {};
  ['library-name', 'library-summary', 'catalog-failure', 'catalog-error', 'retry-catalog',
    'browse-toggle', 'browse-close', 'browse-backdrop', 'browse-panel', 'deck-tree',
    'word-search', 'clear-search', 'word-count', 'word-list', 'word-empty',
    'card-stage', 'deck-path', 'card-position', 'previous-card', 'next-card', 'flip-card',
    'card-status', 'card-failure', 'card-error', 'retry-card', 'frame-host'].forEach(function (id) {
    elements[id] = document.getElementById(id);
  });
  var catalog = null;
  var cardsById = new Map();
  var decksById = new Map();
  var wordButtons = new Map();
  var deckButtons = new Map();
  var selectedDeck = ALL_DECKS;
  var query = '';
  var matchingCards = [];
  var currentCardId = null;
  var activeFrame = null;
  var fetchGeneration = 0;
  var browseOpen = false;
  var media = window.matchMedia ? window.matchMedia('(max-width: 900px)') : null;
  var narrow = media ? media.matches : window.innerWidth <= 900;

  function node(tag, className, text) {
    var result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function count(value) { return value.toLocaleString(); }
  function integer(value) { return Number.isSafeInteger(value) && value >= 0; }
  function string(value) { return typeof value === 'string'; }
  function identifier(value) { return string(value) && value.length > 0 && !/[\u0000-\u001f\u007f]/.test(value); }
  function requireCondition(condition, message) { if (!condition) throw new Error(message); }
  function sameOriginUrl(value, card) {
    requireCondition(string(value) && value && !/[\u0000-\u0020\u007f]/.test(value), '目录包含无效地址');
    var url = new URL(value, window.location.href);
    requireCondition((url.protocol === 'http:' || url.protocol === 'https:') &&
      url.origin === window.location.origin && !url.username && !url.password, '目录地址必须同源');
    if (card) requireCondition(/\/web-preview\/[a-z0-9_-]+\/cards\/[a-f0-9]+\.html$/i.test(url.pathname) &&
      !url.search && !url.hash, '卡片地址不属于生成的预览目录');
    return url;
  }
  function validateCatalog(value) {
    requireCondition(value && value.schema === 'anki-web-catalog.v1', '目录格式不受支持');
    requireCondition(string(value.deckName) && (value.defaultReader === 'latex' || value.defaultReader === 'full-paper') &&
      Array.isArray(value.decks) && Array.isArray(value.cards), '目录缺少必要字段');
    requireCondition(value.counts && integer(value.counts.cards) && integer(value.counts.decks) && integer(value.counts.examples), '目录计数无效');
    var deckMap = new Map();
    var cardMap = new Map();
    value.decks.forEach(function (deck) {
      requireCondition(deck && identifier(deck.id) && deck.id !== ALL_DECKS && !deckMap.has(deck.id) &&
        string(deck.name) && string(deck.unit) && string(deck.lesson) && integer(deck.count) && Array.isArray(deck.cardIds), '卡组字段或标识无效');
      requireCondition(deck.cardIds.length === deck.count && new Set(deck.cardIds).size === deck.cardIds.length, '卡组计数或卡片标识重复');
      deckMap.set(deck.id, deck);
    });
    var examples = 0;
    value.cards.forEach(function (card) {
      requireCondition(card && identifier(card.id) && !cardMap.has(card.id) && identifier(card.deckId) &&
        ['word', 'deckName', 'unit', 'lesson', 'position', 'definition'].every(function (key) { return string(card[key]); }) &&
        integer(card.exampleCount), '卡片字段或标识无效');
      var deck = deckMap.get(card.deckId);
      requireCondition(deck && card.deckName === deck.name && card.unit === deck.unit && card.lesson === deck.lesson, '卡片与卡组关联无效');
      cardMap.set(card.id, Object.assign({}, card, { previewHref: sameOriginUrl(card.previewUrl, true).href }));
      examples += card.exampleCount;
    });
    var assigned = new Set();
    value.decks.forEach(function (deck) {
      deck.cardIds.forEach(function (id) {
        var card = cardMap.get(id);
        requireCondition(card && card.deckId === deck.id && !assigned.has(id), '卡组包含缺失或重复关联的卡片');
        assigned.add(id);
      });
    });
    requireCondition(assigned.size === cardMap.size && value.counts.cards === cardMap.size &&
      value.counts.decks === deckMap.size && value.counts.examples === examples, '目录总计与卡片不一致');
    return { catalog: value, cards: cardMap, decks: deckMap };
  }

  function renderDecks() {
    var fragment = document.createDocumentFragment();
    deckButtons.clear();
    function deckButton(id, name, total) {
      var button = node('button', 'deck-entry');
      button.type = 'button';
      if (id !== ALL_DECKS) button.dataset.deckId = id;
      button.append(node('span', '', name), node('span', 'entry-count', count(total)));
      button.addEventListener('click', function () { chooseDeck(id); });
      deckButtons.set(id, button);
      return button;
    }
    fragment.append(deckButton(ALL_DECKS, '全部卡组', catalog.counts.cards));
    var units = new Map();
    catalog.decks.forEach(function (deck) {
      var name = deck.unit || '未分组';
      if (!units.has(name)) units.set(name, []);
      units.get(name).push(deck);
    });
    units.forEach(function (decks, name) {
      var group = node('details', 'unit-group');
      group.open = true;
      var summary = node('summary', '', name);
      summary.append(node('span', 'entry-count', count(decks.reduce(function (total, deck) { return total + deck.count; }, 0))));
      var lessons = node('ul', 'lesson-list');
      decks.forEach(function (deck) {
        var item = node('li');
        var button = deckButton(deck.id, deck.lesson || deck.name, deck.count);
        button.title = deck.name;
        item.append(button);
        lessons.append(item);
      });
      group.append(summary, lessons);
      fragment.append(group);
    });
    elements['deck-tree'].replaceChildren(fragment);
  }
  function deckCards() {
    if (selectedDeck === ALL_DECKS) return catalog.cards.map(function (card) { return cardsById.get(card.id); });
    return decksById.get(selectedDeck).cardIds.map(function (id) { return cardsById.get(id); });
  }
  function renderWords() {
    var normalized = query.trim().toLocaleLowerCase();
    matchingCards = deckCards().filter(function (card) {
      return !normalized || card.word.toLocaleLowerCase().includes(normalized) || card.definition.toLocaleLowerCase().includes(normalized);
    });
    var fragment = document.createDocumentFragment();
    wordButtons.clear();
    matchingCards.forEach(function (card) {
      var item = node('li');
      var button = node('button', 'word-entry');
      button.type = 'button';
      button.dataset.cardId = card.id;
      button.append(node('span', 'word-entry-name', card.word), node('span', 'word-entry-definition', card.definition),
        node('span', 'word-entry-meta', count(card.exampleCount) + ' 例句'));
      button.addEventListener('click', function () {
        selectCard(card.id, true);
        if (narrow) { setBrowseOpen(false); elements['card-stage'].focus(); }
      });
      item.append(button);
      fragment.append(item);
      wordButtons.set(card.id, button);
    });
    elements['word-list'].replaceChildren(fragment);
    elements['word-count'].textContent = count(matchingCards.length);
    elements['word-empty'].hidden = matchingCards.length > 0;
    elements['clear-search'].hidden = !query;
    deckButtons.forEach(function (button, id) {
      if (id === selectedDeck) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }
  function chooseDeck(id) {
    if (!catalog) return;
    selectedDeck = id;
    renderWords();
    selectCard(wordButtons.has(currentCardId) ? currentCardId : (matchingCards[0] && matchingCards[0].id), true);
  }
  function writeHash() {
    var params = new URLSearchParams();
    if (currentCardId) params.set('card', currentCardId);
    if (selectedDeck !== ALL_DECKS) params.set('deck', selectedDeck);
    var hash = params.toString();
    window.history.replaceState(null, '', window.location.pathname + window.location.search + (hash ? '#' + hash : ''));
  }
  function restoreHash() {
    if (!catalog) return;
    var params = new URLSearchParams(window.location.hash.slice(1));
    var deck = params.get('deck');
    selectedDeck = decksById.has(deck) ? deck : ALL_DECKS;
    query = '';
    elements['word-search'].value = '';
    renderWords();
    var id = params.get('card');
    selectCard(wordButtons.has(id) ? id : (matchingCards[0] && matchingCards[0].id), true);
  }
  function currentIndex() { return matchingCards.findIndex(function (card) { return card.id === currentCardId; }); }
  function updateToolbar() {
    var index = currentIndex();
    var card = cardsById.get(currentCardId);
    var deck = decksById.get(selectedDeck);
    elements['deck-path'].textContent = card ? card.deckName : (deck ? deck.name : '全部卡组');
    elements['card-position'].textContent = index >= 0 ? count(index + 1) + ' / ' + count(matchingCards.length) : '0 / ' + count(matchingCards.length);
    elements['previous-card'].disabled = index <= 0;
    elements['next-card'].disabled = index < 0 || index >= matchingCards.length - 1;
    var ready = activeFrame && activeFrame.ready && activeFrame.cardId === currentCardId;
    var back = ready && activeFrame.flip.getAttribute('aria-pressed') === 'true';
    elements['flip-card'].disabled = !ready;
    elements['flip-card'].setAttribute('aria-pressed', String(Boolean(back)));
    elements['flip-card'].textContent = back ? '返回正面' : '显示答案';
  }
  function disposeFrame() {
    if (!activeFrame) return;
    var old = activeFrame;
    activeFrame = null;
    window.clearTimeout(old.timeout);
    if (old.runtimeCleanup) old.runtimeCleanup();
    if (old.historyCleanup) old.historyCleanup();
    if (old.observer) old.observer.disconnect();
    if (old.document) old.document.removeEventListener('keydown', keyboard);
    old.frame.remove();
  }
  function frameIsCurrent(state) { return activeFrame === state && state.cardId === currentCardId; }
  // Owned candidate: installed only after the existing strict card ready guard.
  function installInlineHistory(cardDocument, cardMap, select, isCurrent) {
    var jobs = new Map();
    var disposed = false;
    var cardHrefs = new Map();
    cardMap.forEach(function (card) { cardHrefs.set(card.previewHref, card.id); });
    var style = cardDocument.createElement('style');
    style.textContent = '.sf-inline-history{margin-block:.75rem;overflow-wrap:anywhere;min-width:0}' +
      '.sf-inline-history pre,.sf-inline-history .sf-reason{white-space:pre-wrap;overflow-wrap:anywhere}' +
      '.sf-ownership-history a,.sf-inline-history button{touch-action:manipulation}' +
      '.sf-inline-history button{min-height:44px;padding:.5rem .75rem}' +
      '.sf-ownership-history a:focus-visible,.sf-inline-history button:focus-visible{outline:2px solid currentColor;outline-offset:3px}';
    cardDocument.head.append(style);

    function demand(value, message) { if (!value) throw new Error(message); }
    function direct(parent, selector) {
      return Array.from(parent.children).filter(function (child) { return child.matches(selector); });
    }
    function one(parent, selector, message) {
      var found = direct(parent, selector);
      demand(found.length === 1, message);
      return found[0];
    }
    function afterPrefix(element, prefix) {
      var text = element.textContent;
      demand(text.indexOf(prefix) === 0 && text.length > prefix.length, '原记录字段缺失或格式不符');
      return text.slice(prefix.length);
    }
    function archiveUrl(value, base) {
      demand(typeof value === 'string' && value && !/[\u0000-\u0020\u007f\\%]/.test(value), '历史地址无效');
      var url = new URL(value, base);
      demand((url.protocol === 'http:' || url.protocol === 'https:') &&
        url.origin === window.location.origin && !url.username && !url.password && !url.search && !url.hash &&
        /^\/exam-usage-policy-20261012\/full-(2026|2027)-v4\/history\/[a-f0-9]{64}\.html$/.test(url.pathname),
        '历史地址不属于同源封存目录');
      return url;
    }
    function identity(details) {
      var reason = afterPrefix(one(details, '.sf-history-old-reason', '原审核理由不唯一'), '原审核完整说明：');
      var markers = direct(details, '.sf-source').filter(function (p) {
        return p.textContent.indexOf('原先目标标记：') === 0;
      });
      var source, target;
      if (markers.length) {
        demand(markers.length === 1, '原目标位置不唯一');
        var mark = markers[0].querySelectorAll('mark');
        demand(mark.length === 1, '原目标标记不唯一');
        target = mark[0].textContent;
        source = afterPrefix(markers[0], '原先目标标记：' + target + ' · ');
      } else {
        var example = one(details, '.sf-example', '原句位置不唯一');
        source = one(example, '.sf-source', '原句来源不唯一').textContent;
        var targets = example.querySelectorAll('.target-word');
        demand(targets.length === 1, '原目标标记不唯一');
        target = targets[0].textContent;
      }
      demand(source && target, '原来源或目标为空');
      return { reason: reason, source: source, target: target };
    }
    function selectedRecord(archive, expected) {
      var matches = Array.from(archive.querySelectorAll('.sf-archived-example')).filter(function (article) {
        var sources = direct(article, '.sf-source'), reasons = direct(article, '.sf-reason');
        return sources.length === 1 && reasons.length === 1 && sources[0].textContent === expected.source &&
          reasons[0].textContent === '义项依据：' + expected.reason;
      });
      demand(matches.length === 1, '原句记录匹配 ' + matches.length + ' 条；需要唯一匹配，未载入其他句');
      var record = matches[0];
      var pair = one(record, '.sf-sentence-pair', '原双语句对不唯一');
      var en = one(pair, '.sf-en', '原英文不唯一'), zh = one(pair, '.sf-zh', '原中文不唯一');
      var marks = en.querySelectorAll('.target-word');
      demand(en.textContent && zh.textContent && marks.length === 1 && marks[0].textContent === expected.target,
        '原双语句或目标标记不符');
      return record;
    }
    function htmlEvidence(archive) {
      var found = Array.from(archive.querySelectorAll('details')).filter(function (details) {
        var summaries = direct(details, 'summary');
        return summaries.length === 1 && summaries[0].textContent.replace(/\s/g, '') === '完整原HTML证据';
      });
      demand(found.length === 1, '完整原 HTML 证据不唯一');
      return one(found[0], 'pre', '完整原 HTML 证据缺失').textContent;
    }
    // Rebuild an inert, bounded subset. Never import nodes or parse evidence HTML.
    function safeCopy(source) {
      if (source.nodeType === 3) return cardDocument.createTextNode(source.nodeValue);
      if (source.nodeType !== 1 || source.namespaceURI !== 'http://www.w3.org/1999/xhtml') return null;
      var tag = source.localName;
      if (!/^(article|section|div|p|span|mark|strong|em|b|i|u|s|br|hr|small|sub|sup|table|thead|tbody|tr|th|td|dl|dt|dd|ol|ul|li|code|pre|details|summary|a)$/.test(tag)) return null;
      var result = cardDocument.createElement(tag);
      ['class', 'data-chunk-side', 'data-chunk-ids', 'data-sf-year'].forEach(function (name) {
        var value = source.getAttribute(name);
        if (value !== null && (name !== 'class' || /^[a-zA-Z0-9_\s-]*$/.test(value))) result.setAttribute(name, value);
      });
      // Anchors become inert text containers. No href, style, events, src, id,
      // forms, SVG, frames or executable attributes enter the card document.
      source.childNodes.forEach(function (child) { var copy = safeCopy(child); if (copy) result.append(copy); });
      return result;
    }
    function make(tag, text) {
      var element = cardDocument.createElement(tag);
      if (text !== undefined) element.textContent = text;
      return element;
    }
    function jobFor(details, link) {
      if (jobs.has(details)) return jobs.get(details);
      var panel = make('section'); panel.className = 'sf-inline-history';
      panel.setAttribute('role', 'region'); panel.setAttribute('aria-label', '原句完整审核记录'); panel.tabIndex = -1;
      var status = make('p'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
      var content = make('div');
      var retry = make('button', '重试载入原句记录'); retry.type = 'button'; retry.hidden = true;
      panel.append(status, content, retry); details.append(panel);
      var job = { panel: panel, status: status, content: content, retry: retry, link: link,
        busy: false, loaded: false, controller: null, timeout: null };
      retry.addEventListener('click', function () { load(details, job); });
      jobs.set(details, job); return job;
    }
    async function load(details, job) {
      details.open = true;
      if (job.busy || disposed || !isCurrent()) return;
      if (job.loaded) { job.panel.focus(); return; }
      job.busy = true; job.retry.hidden = true; job.retry.disabled = true;
      job.panel.setAttribute('aria-busy', 'true'); job.link.setAttribute('aria-busy', 'true');
      job.status.textContent = '正在载入本句的完整原审核记录…';
      job.controller = new AbortController();
      var timedOut = false;
      job.timeout = window.setTimeout(function () { timedOut = true; job.controller.abort(); }, 20000);
      try {
        var expected = identity(details);
        var url = archiveUrl(job.link.getAttribute('href'), cardDocument.URL);
        var response = await fetch(url.href, { credentials: 'same-origin', redirect: 'error', signal: job.controller.signal });
        demand(response.ok, 'HTTP ' + response.status);
        demand(response.url === url.href && !response.redirected, '历史响应地址不符，已拒绝重定向');
        var raw = await response.text();
        demand(raw.length <= 20000000, '历史记录超过载入上限');
        // Template contents remain detached/inert, including resource elements;
        // unlike an HTMLDocument they cannot start image/frame requests.
        var template = cardDocument.createElement('template'); template.innerHTML = raw;
        var archive = template.content;
        var record = selectedRecord(archive, expected), evidence = htmlEvidence(archive);
        if (disposed || !isCurrent()) return;
        var copy = safeCopy(record), disclosure = make('details');
        disclosure.append(make('summary', '完整原 HTML 证据'), make('pre', evidence));
        job.content.replaceChildren(copy, disclosure);
        job.loaded = true; job.status.textContent = '已载入本句完整原审核记录。';
        job.link.setAttribute('aria-expanded', 'true');
      } catch (error) {
        if (disposed || !isCurrent()) return;
        job.content.replaceChildren();
        job.status.textContent = '原句记录加载失败：' + (timedOut ? '载入超时，请重试' : (error.message || '请重试'));
        job.retry.hidden = false;
      } finally {
        job.busy = false; job.retry.disabled = false;
        window.clearTimeout(job.timeout);
        job.panel.setAttribute('aria-busy', 'false'); job.link.setAttribute('aria-busy', 'false');
      }
    }
    function click(event) {
      var link = event.target && event.target.closest && event.target.closest('a[href]');
      if (!link || disposed || !isCurrent()) return;
      var details = link.closest('details.sf-ownership-history');
      if (!details) return;
      if (link.classList.contains('sf-original-history-link')) {
        // Reject invalid addresses inside the inline error/retry UI, never in the iframe.
        event.preventDefault();
        load(details, jobFor(details, link));
        return;
      }
      var url;
      try { url = new URL(link.getAttribute('href'), cardDocument.URL); } catch (_) { return; }
      var id = cardHrefs.get(url.href);
      if (id && url.origin === window.location.origin && !url.username && !url.password && !url.search && !url.hash) {
        event.preventDefault(); select(id, true);
      }
    }
    cardDocument.addEventListener('click', click, true);
    return function () {
      disposed = true; cardDocument.removeEventListener('click', click, true);
      jobs.forEach(function (job) { window.clearTimeout(job.timeout); if (job.controller) job.controller.abort(); });
      style.remove();
    };
  }

  // Additive runtime integration. Frozen URL/flip/ready/history guards stay
  // unchanged. These two shared JSON promises are loaded once per shell.
  var reviewedProjectionPromise = null, sharedBankPromise = null;
  function reviewedProjection() {
    if (!reviewedProjectionPromise) reviewedProjectionPromise = window.AnkiReviewedChunkProjection.load({
      url: '/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json',
      sha256: 'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8'
    }).catch(function (error) { reviewedProjectionPromise = null; throw error; });
    return reviewedProjectionPromise;
  }
  function sharedBank() {
    if (!sharedBankPromise) sharedBankPromise = (async function () {
      var url = new URL('/exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-v5.json', window.location.href);
      var response = await window.fetch(url.href, { credentials: 'same-origin', redirect: 'error' });
      requireCondition(response.ok && response.url === url.href && !response.redirected, '来源对照地址或响应无效');
      var bytes = await response.arrayBuffer();
      requireCondition(bytes.byteLength <= 4 * 1024 * 1024 && window.crypto && window.crypto.subtle, '来源对照无法进行完整核验');
      var digest = await window.crypto.subtle.digest('SHA-256', bytes);
      var hash = Array.from(new Uint8Array(digest)).map(function (v) { return v.toString(16).padStart(2, '0'); }).join('');
      requireCondition(hash === 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5', '来源对照校验失败');
      return JSON.parse(new window.TextDecoder('utf-8', { fatal: true }).decode(bytes));
    })().catch(function (error) { sharedBankPromise = null; throw error; });
    return sharedBankPromise;
  }
  function installOwnedCardRuntime(state, cardDocument) {
    var disposed = false, generation = 0, projectionHandle = null, bankHandle = null, groupHandle = null;
    var wholeHandle = window.AnkiFineChunkRuntime.install(cardDocument);
    var status = node('div', 'owned-runtime-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    var message = node('span'), retry = node('button', 'small-button', '重试细块与来源对照'); retry.type = 'button'; retry.hidden = true;
    status.append(message, retry); state.frame.before(status);
    var style = cardDocument.createElement('style');
    style.textContent = '[data-reviewed-chunk-projection]:focus-visible{outline:2px solid #1262a3;outline-offset:2px}' +
      '[data-reviewed-source-comparison]{margin-block:.7rem;overflow-wrap:anywhere;min-width:0}' +
      '[data-reviewed-source-comparison] pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}';
    cardDocument.head.append(style);
    function alive(version) { return !disposed && generation === version && frameIsCurrent(state) && state.document === cardDocument && state.ready; }
    function clearHandles() {
      if (groupHandle) groupHandle.dispose(); groupHandle = null;
      if (bankHandle) bankHandle.dispose(); bankHandle = null;
      if (projectionHandle) projectionHandle.dispose(); projectionHandle = null;
    }
    function failure(error, version) {
      if (!alive(version)) return;
      status.hidden = false; status.setAttribute('aria-busy', 'false'); status.dataset.state = 'failed';
      message.textContent = '细块与来源对照加载失败，可重试。'; retry.hidden = false; retry.disabled = false;
      state.frame.setAttribute('data-owned-runtime-state', 'failed');
      // Diagnostic text remains data, never HTML or a substitute card error.
      status.setAttribute('data-error', String(error && error.message || error));
    }
    async function run() {
      var version = ++generation; if (!alive(version)) return; clearHandles();
      status.hidden = false; status.dataset.state = 'loading'; status.removeAttribute('data-error'); status.setAttribute('aria-busy', 'true');
      message.textContent = '正在加载细块与来源对照…'; retry.hidden = true; retry.disabled = true; state.frame.setAttribute('data-owned-runtime-state', 'loading');
      try {
        var inputs = await Promise.all([reviewedProjection(), sharedBank()]);
        if (!alive(version)) return;
        wholeHandle.refresh();
        projectionHandle = window.AnkiReviewedChunkProjection.install(cardDocument, inputs[0], {
          isCurrent: function () { return alive(version); }, onError: function (error) { failure(error, version); }
        });
        requireCondition(!projectionHandle.stats().errors.length, '本句细块投影核验失败');
        bankHandle = window.AnkiSharedReadingBankRuntime.install(cardDocument, inputs[1]);
        await bankHandle.ready;
        if (!alive(version)) return;
        groupHandle = window.AnkiSameSenseGroupRuntime.install(cardDocument);
        status.dataset.state = 'ready'; status.setAttribute('aria-busy', 'false'); status.hidden = true; state.frame.setAttribute('data-owned-runtime-state', 'ready');
      } catch (error) { failure(error, version); }
    }
    retry.addEventListener('click', run); run();
    return function () {
      if (disposed) return; disposed = true; generation++;
      retry.removeEventListener('click', run); clearHandles(); wholeHandle.dispose(); style.remove(); status.remove(); state.frame.removeAttribute('data-owned-runtime-state');
    };
  }

  function constrainCardDocument(cardDocument) {
    cardDocument.documentElement.classList.add('anki-library-card');
    var style = cardDocument.getElementById('anki-library-responsive');
    if (!style) {
      style = cardDocument.createElement('style');
      style.id = 'anki-library-responsive';
      cardDocument.head.append(style);
    }
    style.textContent = responsiveCardCss;
    cardDocument.querySelectorAll('.word').forEach(function (word) {
      var tokens = word.textContent.match(/[A-Za-z]+/g) || [];
      word.classList.toggle('anki-preview-long-word', tokens.some(function (token) { return token.length >= 12; }));
    });
  }
  function failFrame(state) {
    if (!frameIsCurrent(state)) return;
    window.clearTimeout(state.timeout);
    state.ready = false;
    state.frame.hidden = true;
    elements['card-status'].hidden = true;
    elements['card-failure'].hidden = false;
    elements['card-error'].hidden = false;
    elements['card-error'].textContent = '卡片加载失败，请重试。';
    elements['card-stage'].setAttribute('aria-busy', 'false');
    updateToolbar();
  }
  function loadCard(card) {
    disposeFrame();
    elements['card-failure'].hidden = true;
    elements['card-error'].hidden = true;
    elements['card-status'].hidden = false;
    elements['card-status'].textContent = '正在加载 ' + card.word + '…';
    elements['card-stage'].setAttribute('aria-busy', 'true');
    var frame = node('iframe');
    frame.id = 'card-frame';
    frame.title = card.word + ' · 卡片预览';
    frame.setAttribute('allow', 'autoplay');
    // Safari must initialize the subframe in a real layout box to inherit the
    // parent's page zoom. display:none during navigation delays that sync.
    frame.style.visibility = 'hidden';
    frame.setAttribute('aria-hidden', 'true');
    // These are generated, escaped, same-origin card documents. Keeping their
    // native context preserves eudic navigation, audio and target=_blank readers.
    var state = { frame: frame, cardId: card.id, ready: false, flip: null, document: null, observer: null, timeout: null };
    activeFrame = state;
    frame.addEventListener('error', function () { failFrame(state); });
    frame.addEventListener('load', function () {
      if (!frameIsCurrent(state)) return;
      try {
        var cardDocument = frame.contentDocument;
        if (cardDocument && cardDocument.URL === 'about:blank') return;
        requireCondition(cardDocument && cardDocument.URL === card.previewHref, '卡片地址不匹配');
        var flip = cardDocument.getElementById('preview-flip');
        var front = cardDocument.getElementById('preview-front');
        var back = cardDocument.getElementById('preview-back');
        requireCondition(flip && front && back, '卡片缺少翻面控件');
        constrainCardDocument(cardDocument);
        if (state.observer) state.observer.disconnect();
        if (state.document) state.document.removeEventListener('keydown', keyboard);
        state.document = cardDocument;
        state.flip = flip;
        cardDocument.querySelectorAll('.preview-controls').forEach(function (control) { control.hidden = true; });
        // A new frame starts at the front even if a browser restored form state.
        if (flip.getAttribute('aria-pressed') === 'true') flip.click();
        cardDocument.addEventListener('keydown', keyboard);
        state.observer = new MutationObserver(function () { if (frameIsCurrent(state)) updateToolbar(); });
        state.observer.observe(flip, { attributes: true, attributeFilter: ['aria-pressed'] });
        window.clearTimeout(state.timeout);
        state.ready = true;
        frame.hidden = false;
        frame.style.removeProperty('visibility');
        frame.removeAttribute('aria-hidden');
        elements['card-status'].hidden = true;
        elements['card-failure'].hidden = true;
        elements['card-error'].hidden = true;
        elements['card-stage'].setAttribute('aria-busy', 'false');
        updateToolbar();
        if (state.historyCleanup) state.historyCleanup();
        state.historyCleanup = installInlineHistory(cardDocument, cardsById, selectCard, function () { return frameIsCurrent(state); });
        if (state.runtimeCleanup) state.runtimeCleanup();
        state.runtimeCleanup = installOwnedCardRuntime(state, cardDocument);
      } catch (_) { failFrame(state); }
    });
    state.timeout = window.setTimeout(function () { failFrame(state); }, 20000);
    elements['frame-host'].replaceChildren(frame);
    // Resolve the positioned frame's geometry before beginning card navigation.
    frame.getBoundingClientRect();
    frame.src = card.previewHref;
  }
  function selectCard(id, updateHash) {
    var nextId = id || null;
    if (currentCardId && wordButtons.has(currentCardId)) wordButtons.get(currentCardId).removeAttribute('aria-current');
    var changed = currentCardId !== nextId;
    currentCardId = nextId;
    if (currentCardId) {
      var button = wordButtons.get(currentCardId);
      if (button) {
        button.setAttribute('aria-current', 'true');
        if (button.scrollIntoView) button.scrollIntoView({ block: 'nearest' });
      }
      if (changed || !activeFrame) loadCard(cardsById.get(currentCardId));
    } else {
      disposeFrame();
      elements['card-failure'].hidden = true;
      elements['card-error'].hidden = true;
      elements['card-status'].hidden = false;
      elements['card-status'].textContent = catalog && catalog.cards.length ? '没有匹配的卡片。' : '目录中暂无卡片。';
      elements['card-stage'].setAttribute('aria-busy', 'false');
    }
    updateToolbar();
    if (updateHash) writeHash();
  }
  function moveCard(offset) {
    var index = currentIndex();
    var next = index + offset;
    if (index >= 0 && next >= 0 && next < matchingCards.length) selectCard(matchingCards[next].id, true);
  }
  function flipCard() {
    if (!activeFrame || !activeFrame.ready || !frameIsCurrent(activeFrame)) return;
    activeFrame.flip.click();
    updateToolbar();
  }

  function setBrowseOpen(open, restoreFocus) {
    browseOpen = narrow && open;
    elements['browse-panel'].hidden = narrow && !browseOpen;
    elements['browse-backdrop'].hidden = !browseOpen;
    elements['browse-toggle'].setAttribute('aria-expanded', String(browseOpen));
    document.querySelector('.library-header').inert = browseOpen;
    elements['card-stage'].inert = browseOpen;
    elements['catalog-failure'].inert = browseOpen;
    if (browseOpen) {
      elements['browse-panel'].setAttribute('role', 'dialog');
      elements['browse-panel'].setAttribute('aria-modal', 'true');
      elements['word-search'].focus();
    } else {
      elements['browse-panel'].removeAttribute('role');
      elements['browse-panel'].removeAttribute('aria-modal');
      if (restoreFocus) elements['browse-toggle'].focus();
    }
  }
  function keyboard(event) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
    if (event.key === 'Escape' && browseOpen) {
      event.preventDefault();
      setBrowseOpen(false, true);
      return;
    }
    if (event.key === 'Tab' && browseOpen) {
      var controls = Array.from(elements['browse-panel'].querySelectorAll('*')).filter(function (control) {
        if (!control.matches('button:not(:disabled), input:not(:disabled), summary') || control.closest('[hidden]')) return false;
        var details = control.closest('details');
        return !details || details.open || control.tagName === 'SUMMARY';
      });
      var first = controls[0];
      var last = controls[controls.length - 1];
      if (event.shiftKey && event.target === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && event.target === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.shiftKey) return;
    var target = event.target;
    if (target && target.closest && target.closest('[data-reviewed-chunk-projection]') && (event.key === ' ' || event.key === 'Spacebar' || event.key === 'Enter')) return;
    if (target && target.closest && target.closest('input, textarea, select, button, a[href], summary, audio, video, [contenteditable]:not([contenteditable="false"])')) return;
    if (event.repeat) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (!catalog || browseOpen) return;
      event.preventDefault();
      moveCard(event.key === 'ArrowLeft' ? -1 : 1);
    } else if (event.key === ' ' || event.key === 'Spacebar') {
      if (!activeFrame || !activeFrame.ready || browseOpen) return;
      event.preventDefault();
      flipCard();
    }
  }

  async function loadCatalog() {
    var generation = ++fetchGeneration;
    elements['catalog-failure'].hidden = true;
    elements['catalog-error'].hidden = true;
    elements['retry-catalog'].hidden = true;
    elements['library-summary'].textContent = '正在加载目录…';
    try {
      var url = sameOriginUrl(document.body.dataset.catalogUrl, false);
      var response = await fetch(url.href, { credentials: 'same-origin' });
      requireCondition(response.ok, 'HTTP ' + response.status);
      var validated = validateCatalog(await response.json());
      if (generation !== fetchGeneration) return;
      catalog = validated.catalog;
      cardsById = validated.cards;
      decksById = validated.decks;
      elements['library-name'].textContent = catalog.deckName;
      document.title = catalog.deckName + ' · Anki 预览';
      elements['library-summary'].textContent = count(catalog.counts.cards) + ' 张卡 · ' + count(catalog.counts.decks) + ' 个卡组 · ' + count(catalog.counts.examples) + ' 条例句';
      elements['word-search'].disabled = false;
      // Existing cards share this key, so their reader choice persists across cards.
      try {
        var storedReader = localStorage.getItem(readerStorageKey);
        if (storedReader !== 'latex' && storedReader !== 'full-paper') localStorage.setItem(readerStorageKey, catalog.defaultReader);
      } catch (_) {}
      renderDecks();
      restoreHash();
    } catch (error) {
      if (generation !== fetchGeneration) return;
      elements['library-summary'].textContent = '目录不可用';
      elements['catalog-failure'].hidden = false;
      elements['catalog-error'].hidden = false;
      elements['retry-catalog'].hidden = false;
      elements['catalog-error'].textContent = '目录加载失败：' + (error.message || '请检查连接后重试');
      elements['card-status'].textContent = '请重新加载目录。';
      elements['card-stage'].setAttribute('aria-busy', 'false');
      updateToolbar();
    }
  }

  elements['word-search'].addEventListener('input', function () {
    if (!catalog) return;
    query = elements['word-search'].value;
    renderWords();
    // Select the completed word without changing the source order of results.
    var normalized = query.trim().toLocaleLowerCase();
    var exactCards = normalized ? matchingCards.filter(function (card) {
      return card.word.trim().toLocaleLowerCase() === normalized;
    }) : [];
    var exact = exactCards.find(function (card) { return card.id === currentCardId; }) || exactCards[0];
    selectCard(exact ? exact.id : (wordButtons.has(currentCardId) ? currentCardId : (matchingCards[0] && matchingCards[0].id)), true);
  });
  elements['clear-search'].addEventListener('click', function () {
    elements['word-search'].value = '';
    elements['word-search'].dispatchEvent(new Event('input', { bubbles: true }));
    elements['word-search'].focus();
  });
  elements['previous-card'].addEventListener('click', function () { moveCard(-1); });
  elements['next-card'].addEventListener('click', function () { moveCard(1); });
  elements['flip-card'].addEventListener('click', flipCard);
  elements['retry-card'].addEventListener('click', function () {
    if (currentCardId) { loadCard(cardsById.get(currentCardId)); updateToolbar(); }
  });
  elements['retry-catalog'].addEventListener('click', loadCatalog);
  elements['browse-toggle'].addEventListener('click', function () { setBrowseOpen(!browseOpen); });
  elements['browse-close'].addEventListener('click', function () { setBrowseOpen(false, true); });
  elements['browse-backdrop'].addEventListener('click', function () { setBrowseOpen(false, true); });
  window.addEventListener('hashchange', restoreHash);
  document.addEventListener('keydown', keyboard);
  if (media) {
    var resize = function (event) { narrow = event.matches; setBrowseOpen(false); };
    if (media.addEventListener) media.addEventListener('change', resize);
    else if (media.addListener) media.addListener(resize);
  } else window.addEventListener('resize', function () { narrow = window.innerWidth <= 900; setBrowseOpen(false); });
  setBrowseOpen(false);
  loadCatalog();
})();
