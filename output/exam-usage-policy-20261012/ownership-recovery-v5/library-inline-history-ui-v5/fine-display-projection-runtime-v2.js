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
      if (disposed) return; disposed = true; observer.disconnect(); doc.removeEventListener('keydown', keyboard);
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
    installed.set(doc, handle); doc.addEventListener('keydown', keyboard); refresh();
    observer.observe(doc.documentElement, { childList: true, subtree: true, characterData: true }); return handle;
  }
  window.AnkiReviewedChunkProjection = Object.freeze({ prepare: prepare, load: load, install: install });
})();
