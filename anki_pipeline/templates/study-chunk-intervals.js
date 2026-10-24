/* Shared interval interaction runtime. No delivery format enables it by default.
 *
 * install(document, profile, {binding, isCurrent, clearLegacy, onInvalid})
 * requires a CALLER-AUTHENTICATED envelope: binding contains externally verified
 * source_sha256, compact_sha256, profile_sha256 and css_sha256. Matching these
 * strings is not authentication. The caller must authenticate the original
 * source/prepared chain, profile bytes, exact compact bytes and reviewed CSS
 * capability before calling. This module neither fetches nor serializes a DOM
 * to pretend it verified those bytes. It independently checks the new semantic
 * tables and live node bindings. It never accepts an old DOM/pilot profile.
 *
 * One initial anchor index; interaction validation visits only its current
 * sentence root. Paint splits TEXT only, never clones/extracts source elements.
 * release() is the reverse handoff for the legacy private-clear integration.
 * The caller must exclude these roots from legacy delegated callbacks.
 */
(function () {
  'use strict';
  var SCHEMA = 'study-chunk-intervals.v1';
  var REVISION = 'study-chunk-intervals.runtime.v1';
  var ROOT = 'data-study-chunk-interval-root';
  var PAR = 'data-study-chunk-interval-paragraph';
  var PAINT = 'data-study-chunk-interval-painted';
  var CONTROL = 'a,button,input,select,textarea,summary,audio,video,[role="button"],[contenteditable]';
  var PIN = /^[a-f0-9]{64}$/;
  var KEY = /^[A-Za-z0-9_.:-]{1,160}$/;
  var PAR_KEY = /^[A-Za-z0-9_.:-]{1,163}$/;
  var ID = /^(0|[1-9][0-9]*)$/;
  // Re-executing the same authenticated template in an Anki webview reuses
  // the private owner registry. A different runtime revision must explicitly
  // dispose the old owners and create a new document; never silently replace
  // its API/listeners. No registry or ownership token is exposed publicly.
  var previous = Object.getOwnPropertyDescriptor(window, 'StudyChunkIntervals');
  if (previous) {
    var previousAPI = previous.value;
    var schema = previousAPI && Object.getOwnPropertyDescriptor(previousAPI, 'schema');
    var revision = previousAPI && Object.getOwnPropertyDescriptor(previousAPI, 'revision');
    var entry = previousAPI && Object.getOwnPropertyDescriptor(previousAPI, 'install');
    if (Object.prototype.hasOwnProperty.call(previous, 'value') && previousAPI && Object.isFrozen(previousAPI) &&
        schema && schema.value === SCHEMA && revision && revision.value === REVISION && entry && typeof entry.value === 'function') return;
    fail('existing runtime revision conflict');
  }
  var owners = new WeakMap();
  function fail(message) { throw Error('Chunk intervals: ' + message); }
  function own(object, key) {
    if (!object || typeof object !== 'object') fail('JSON object required');
    var descriptor = Object.getOwnPropertyDescriptor(object, key);
    if (!descriptor || !Object.prototype.hasOwnProperty.call(descriptor, 'value')) fail('own JSON data: ' + key);
    return descriptor.value;
  }
  function json(value, depth) {
    if (depth > 64) fail('JSON nesting');
    if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (!value || typeof value !== 'object') fail('JSON value');
    var proto = Object.getPrototypeOf(value);
    if (!Array.isArray(value) && proto !== null && Object.getPrototypeOf(proto) !== null) fail('JSON prototype');
    if (Array.isArray(value)) {
      var length = own(value, 'length'), result = [];
      if (!Number.isSafeInteger(length) || length < 0) fail('JSON array');
      for (var i = 0; i < length; i++) result.push(json(own(value, String(i)), depth + 1));
      if (Object.keys(value).length !== length) fail('JSON array properties');
      return result;
    }
    var copy = Object.create(null);
    Object.keys(value).forEach(function (key) { copy[key] = json(own(value, key), depth + 1); });
    return copy;
  }
  function list(value, label) { if (!Array.isArray(value)) fail(label); return value; }
  function text(value, label) { if (typeof value !== 'string') fail(label); return value; }
  function integer(value, label) { if (!Number.isSafeInteger(value) || value < 0) fail(label); return value; }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function attrs(node) { return Array.from(node.attributes, function (a) { return [a.name, a.value]; }); }
  function element(node) { return node && (node.nodeType === 1 ? node : node.parentElement); }
  function utf16Boundaries(value) {
    var offsets = [0], size = 0;
    Array.from(value).forEach(function (c) { size += c.length; offsets.push(size); });
    return offsets;
  }
  // Same interpretation as packaging._example_chunk_ranges: non-equivalent
  // entries are validated but never become ranges; English prioritizes the
  // shortest authored range and Chinese preserves alignment enumeration.
  // Byte hashes remain the authenticated caller's responsibility.
  function canonical(source) {
    var ex = source.example, alignment = ex && ex.translation_alignment;
    if (!ex || ex.translation_source !== 'codex' || !alignment ||
        !equal(Object.keys(alignment).sort(), ['alignments', 'englishHash', 'schema', 'translationHash']) ||
        alignment.schema !== 'codex-sentence-alignment.v1' || !PIN.test(alignment.englishHash) ||
        !PIN.test(alignment.translationHash) || !PIN.test(source.alignment_sha256)) fail('reviewed source');
    var value = {en: text(ex.text, 'English text'), zh: text(ex.translation, 'Chinese text')};
    if (!value.en.trim() || !value.zh.trim()) fail('blank canonical text');
    var bounds = {en: utf16Boundaries(value.en), zh: utf16Boundaries(value.zh)};
    var raw = {en: [], zh: []}, whole = [], seen = new Set();
    function range(row, side) {
      if (!Array.isArray(row) || row.length !== 2) fail('alignment range');
      var a = integer(row[0], 'alignment start'), z = integer(row[1], 'alignment end');
      if (a >= z || z >= bounds[side].length) fail('alignment bounds');
      return [a, z];
    }
    list(alignment.alignments, 'alignments').forEach(function (entry, identity) {
      if (!entry || !equal(Object.keys(entry).sort(), ('note' in entry ? ['en', 'note', 'relation', 'zh'] : ['en', 'relation', 'zh'])) ||
          ['equivalent', 'implicit', 'untranslated'].indexOf(entry.relation) === -1 ||
          'note' in entry && typeof entry.note !== 'string') fail('alignment entry');
      var en = range(entry.en, 'en'), enKey = en.join(':');
      if (seen.has(enKey)) fail('duplicate English alignment');
      seen.add(enKey);
      var zh = list(entry.zh, 'Chinese alignment').map(function (r) { return range(r, 'zh'); });
      if (entry.relation === 'equivalent') {
        if (!zh.length) fail('empty equivalent alignment');
        raw.en.push([en[0], en[1], identity]);
        zh.forEach(function (r) { raw.zh.push([r[0], r[1], identity]); });
      } else if (zh.length || !entry.note || !entry.note.trim()) fail('unexplained alignment');
      if (entry.note && entry.note.indexOf('整句对应：') === 0) whole.push(String(identity));
    });
    raw.en.sort(function (a, b) { return (a[1] - a[0]) - (b[1] - b[0]) || a[2] - b[2]; });
    if (!source.ranges || !equal(Object.keys(source.ranges).sort(), ['en', 'zh']) ||
        !equal(source.ranges.en, raw.en) || !equal(source.ranges.zh, raw.zh) ||
        !equal(source.sentence_ids, whole)) fail('canonical ranges/whole table');
    var ranges = {};
    ['en', 'zh'].forEach(function (side) {
      ranges[side] = raw[side].map(function (r) { return [bounds[side][r[0]], bounds[side][r[1]], String(r[2])]; });
    });
    return {text: value, whole: whole, ranges: ranges};
  }
  function selected(segment) {
    var ids = segment.ids;
    if (segment.par.side === 'en') ids = ids.slice(0, 1);
    else {
      var fine = ids.filter(function (id) { return segment.whole.indexOf(id) === -1; });
      if (fine.length) ids = fine;
    }
    return ids.filter(function (id, i) { return ids.indexOf(id) === i; }).slice().sort();
  }
  function install(doc, original, options) {
    options = options || {};
    var win = doc && doc.defaultView;
    if (doc && owners.has(doc)) fail('document already owned');
    if (!win || doc.nodeType !== 9 || typeof options.isCurrent !== 'function' ||
        typeof options.clearLegacy !== 'function') fail('document/owner/private-clear required');
    if ((!doc.caretRangeFromPoint && !doc.caretPositionFromPoint) ||
        !win.Range || typeof win.Range.prototype.getClientRects !== 'function') fail('glyph hit testing unavailable');
    var isCurrent = options.isCurrent, clearLegacy = options.clearLegacy;
    var onInvalid = typeof options.onInvalid === 'function' ? options.onInvalid : null;
    var binding = json(options.binding, 0);
    ['source_sha256', 'compact_sha256', 'profile_sha256', 'css_sha256'].forEach(function (name) {
      if (!PIN.test(binding[name])) fail('external ' + name);
    });
    // Do not retain the caller's mutable profile, archive lexemes or callbacks.
    var p = Object.create(null);
    ['schema', 'version', 'offset_unit', 'anchors', 'source_sha256', 'source_bytes',
      'compact_sha256', 'compact_bytes', 'css_sha256', 'sources', 'attributes',
      'id_sets', 'segment_columns', 'sentences'].forEach(function (name) { p[name] = json(own(original, name), 0); });
    if (p.schema !== SCHEMA || p.version !== 1 || p.offset_unit !== 'utf16' ||
        p.anchors.root !== ROOT || p.anchors.paragraph !== PAR ||
        !equal(p.segment_columns, ['start', 'end', 'ids', 'whole', 'attributes', 'retained'])) fail('new interval schema');
    ['source_sha256', 'compact_sha256', 'css_sha256'].forEach(function (name) {
      if (p[name] !== binding[name]) fail('external ' + name + ' mismatch');
    });
    integer(p.source_bytes, 'source bytes'); integer(p.compact_bytes, 'compact bytes');
    var sources = list(p.sources, 'sources').map(canonical);
    var sets = list(p.id_sets, 'ID sets').map(function (ids) {
      list(ids, 'ID set');
      if (ids.some(function (id, i) { return typeof id !== 'string' || !ID.test(id) || ids.indexOf(id) !== i; })) fail('ID set');
      return ids;
    });
    var attributes = list(p.attributes, 'attributes').map(function (row) {
      var names = [];
      list(row, 'attributes').forEach(function (pair) {
        if (!Array.isArray(pair) || pair.length !== 2 || typeof pair[0] !== 'string' || !pair[0] ||
            pair[0] !== pair[0].toLowerCase() || typeof pair[1] !== 'string' || names.indexOf(pair[0]) !== -1 ||
            pair[0] === PAINT || pair[0] === ROOT || pair[0] === PAR) fail('attribute record');
        names.push(pair[0]);
      });
      return row;
    });
    var disposed = false, invalid = null, active = null, hoverSegment = null, ownerToken = {};
    var roots = new Map(), paragraphs = new Map(), retained = new Map(), listeners = [];
    var handled = 0, keyboardHandled = 0, validations = 0, ignoreMouseUntil = 0;
    function current() { return !disposed && !invalid && owners.get(doc) === ownerToken && doc.defaultView === win && isCurrent() === true; }
    function owner() { if (!current()) fail('cancelled owner'); }
    function tree(node) {
      var rows = [];
      function walk(n) {
        var row = {node: n, parent: n.parentNode, next: n.nextSibling, first: n.firstChild, type: n.nodeType};
        if (n.nodeType === 1) { row.name = n.localName; row.attrs = attrs(n); }
        else row.data = n.data;
        rows.push(row);
        for (var child = n.firstChild; child; child = child.nextSibling) walk(child);
      }
      walk(node); return rows;
    }
    function sameTree(rows) {
      return rows.every(function (row) {
        var n = row.node;
        return n.parentNode === row.parent && n.nextSibling === row.next && n.firstChild === row.first && n.nodeType === row.type &&
          (row.type === 1 ? n.localName === row.name && equal(attrs(n), row.attrs) : n.data === row.data);
      });
    }
    function placement(node) {
      var result = [];
      for (var n = node; n && n !== doc; n = n.parentNode) result.push([n, n.parentNode]);
      return result;
    }
    function validRoot(root) {
      owner(); validations++;
      if (root.node.ownerDocument !== doc || !root.node.isConnected || root.node.getAttribute(ROOT) !== root.key ||
          !root.node.classList.contains('example-card') ||
          !equal(immutableRootAttrs(root.node), root.attrs) ||
          root.node.closest('[data-sf-occurrence-id]') !== root.physical ||
          root.physical && root.physical.getAttribute('data-sf-occurrence-id') !== root.occurrence ||
          root.node.previousSibling !== root.previous || root.node.nextSibling !== root.next ||
          root.parents.some(function (row) { return row[0].parentNode !== row[1]; })) fail('root moved/replaced');
      root.paragraphs.forEach(function (par) {
        if (par.node.getAttribute(PAR) !== par.key || par.node.closest('[' + ROOT + ']') !== root.node ||
            !sameTree(active && active.root === root ? active.after.get(par) : par.before)) fail('paragraph structure/text changed');
      });
    }
    function immutableRootAttrs(node) {
      // The existing year filter may hide an otherwise identical source row.
      // No other root attribute is a permitted interval-runtime UI mutation.
      return attrs(node).filter(function (pair) { return pair[0] !== 'hidden'; });
    }
    function inspect(par) {
      var offset = 0, spans = [], texts = [];
      function walk(node, depth) {
        if (node.nodeType === 3) { texts.push({node: node, next: node.nextSibling, start: offset, end: offset + node.data.length}); offset += node.data.length; return; }
        var start = offset;
        for (var child = node.firstChild; child; child = child.nextSibling) walk(child, depth + 1);
        if (node.nodeType === 1 && node.classList.contains('card-chunk')) spans.push({node: node, start: start, end: offset, depth: depth});
      }
      walk(par.node, 0);
      spans.sort(function (a, b) { return a.start - b.start || b.end - a.end || a.depth - b.depth; });
      return {spans: spans, texts: texts};
    }
    // The only document-wide selector in installation or event handling.
    var nodes = doc.querySelectorAll('.example-card,[' + ROOT + '],[' + PAR + ']');
    var rootOrdinals = new Map(), rootOrdinal = 0;
    nodes.forEach(function (node) {
      if (node.classList.contains('example-card')) rootOrdinals.set(node, rootOrdinal++);
      [ROOT, PAR].forEach(function (attribute) {
        if (!node.hasAttribute(attribute)) return;
        var key = node.getAttribute(attribute), map = attribute === ROOT ? roots : paragraphs;
        if (!(attribute === ROOT ? KEY : PAR_KEY).test(key) || map.has(key) || node.hasAttribute(ROOT) && node.hasAttribute(PAR)) fail('duplicate/invalid anchor');
        map.set(key, node);
      });
    });
    var sentenceList = list(p.sentences, 'sentences');
    if (!sentenceList.length || roots.size !== sentenceList.length) fail('root coverage');
    var usedRoots = new Set(), usedParagraphs = new Set();
    sentenceList.forEach(function (sentence) {
      var key = sentence.key, node = roots.get(key), source = sources[sentence.source];
      if (!node || usedRoots.has(key) || !source || !Number.isSafeInteger(sentence.source) ||
          !Number.isSafeInteger(sentence.root_index) || sentence.root_index < 0 || rootOrdinals.get(node) !== sentence.root_index || !node.classList.contains('example-card') ||
          node.parentElement && node.parentElement.closest('[' + ROOT + ']')) fail('sentence root binding');
      usedRoots.add(key);
      var physical = node.closest('[data-sf-occurrence-id]');
      var root = {key: key, node: node, attrs: immutableRootAttrs(node), physical: physical,
        occurrence: physical ? physical.getAttribute('data-sf-occurrence-id') : null,
        previous: node.previousSibling, next: node.nextSibling, parents: placement(node), paragraphs: []};
      roots.set(key, root);
      var sides = [];
      list(sentence.paragraphs, 'paragraphs').forEach(function (record) {
        var parNode = paragraphs.get(record.key), side = record.side;
        if (!parNode || usedParagraphs.has(record.key) || record.key !== key + ':' + side || (side !== 'en' && side !== 'zh') || sides.indexOf(side) !== -1 ||
            parNode.closest('[' + ROOT + ']') !== node || parNode.parentElement.closest('[' + PAR + ']')) fail('paragraph binding');
        sides.push(side); usedParagraphs.add(record.key);
        var prefix = text(record.prefix, 'prefix'), wanted = prefix + source.text[side];
        if (!PIN.test(record.text_sha256) || record.utf16_length !== wanted.length || parNode.textContent !== wanted) fail('canonical paragraph text');
        var par = {key: record.key, node: parNode, root: root, side: side, text: wanted, segments: []};
        var inspected = inspect(par), seen = new Set();
        list(record.segments, 'segments').forEach(function (row, ordinal) {
          if (!Array.isArray(row) || row.length !== 6 || typeof row[5] !== 'boolean') fail('segment columns');
          var start = integer(row[0], 'start'), end = integer(row[1], 'end');
          var ids = sets[row[2]], whole = sets[row[3]], attr = attributes[row[4]];
          if (start >= end || end > wanted.length || !ids || !whole || !attr || !ids.length ||
              !Number.isSafeInteger(row[2]) || !Number.isSafeInteger(row[3]) || !Number.isSafeInteger(row[4])) fail('segment bounds/table');
          var left = start - prefix.length, right = end - prefix.length;
          var expected = source.ranges[side].filter(function (r) { return r[0] <= left && left < right && right <= r[1]; })
            .map(function (r) { return r[2]; }).filter(function (id, i, a) { return a.indexOf(id) === i; });
          if (!equal(ids, expected) || !equal(whole, ids.filter(function (id) { return source.whole.indexOf(id) !== -1; }))) fail('canonical ID position');
          if (start && /[\uD800-\uDBFF]/.test(wanted[start - 1]) && /[\uDC00-\uDFFF]/.test(wanted[start]) ||
              end && /[\uD800-\uDBFF]/.test(wanted[end - 1]) && /[\uDC00-\uDFFF]/.test(wanted[end])) fail('surrogate boundary');
          var values = Object.fromEntries(attr);
          if (!/(^|\s)card-chunk(\s|$)/.test(values['class']) || values['data-chunk-side'] !== side ||
              values['data-chunk-ids'] !== ids.join(' ') || (values['data-chunk-sentence-ids'] || '') !== whole.join(' ')) fail('segment attributes');
          var segment = {par: par, start: start, end: end, ids: ids, whole: whole, attrs: attr, ordinal: ordinal, retained: row[5], node: null};
          if (row[5]) {
            var match = inspected.spans.find(function (span) { return !seen.has(span.node) && span.start === start && span.end === end && equal(attrs(span.node), attr); });
            if (!match) fail('retained span binding');
            seen.add(match.node); segment.node = match.node; segment.depth = match.depth; retained.set(match.node, segment);
          } else {
            if (values['class'] !== 'card-chunk' || attr.some(function (a) {
              return ['class', 'data-chunk-side', 'data-chunk-ids', 'data-chunk-sentence-ids', 'title'].indexOf(a[0]) === -1;
            }) || !inspected.texts.some(function (t) { return t.start <= start && end <= t.end; })) fail('removed span binding');
          }
          par.segments.push(segment);
        });
        if (inspected.spans.length !== seen.size) fail('unlisted retained span');
        var removed = par.segments.filter(function (s) { return !s.retained; }).slice().sort(function (a, b) { return a.start - b.start; });
        for (var i = 1; i < removed.length; i++) if (removed[i].start < removed[i - 1].end) fail('overlapping removed spans');
        function union(rows) {
          var result = [];
          rows.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
          rows.forEach(function (r) {
            var last = result[result.length - 1];
            if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]); else result.push(r.slice());
          });
          return result;
        }
        if (!equal(union(par.segments.map(function (s) { return [s.start, s.end]; })),
          union(source.ranges[side].map(function (r) { return [r[0] + prefix.length, r[1] + prefix.length]; })))) fail('canonical interval coverage');
        par.texts = inspected.texts; par.before = tree(parNode);
        paragraphs.set(par.key, par); root.paragraphs.push(par);
      });
      if (sides.length !== 2) fail('bilingual paragraph coverage');
    });
    if (paragraphs.size !== usedParagraphs.size) fail('paragraph coverage');
    p = null; sources = null; attributes = null; sets = null; original = null; options = null; nodes = null; rootOrdinals = null;
    if (owners.has(doc)) fail('document already owned');
    owners.set(doc, ownerToken);
    try { owner(); } catch (error) {
      if (owners.get(doc) === ownerToken) owners.delete(doc);
      throw error;
    }
    function invalidate(error) {
      if (invalid || disposed) return;
      invalid = error instanceof Error ? error : Error(String(error));
      if (onInvalid && isCurrent() === true) { try { onInvalid(invalid); } catch (_) {} }
    }
    function clear() {
      owner();
      if (!active) return true;
      validRoot(active.root);
      active.texts.forEach(function (change) {
        var first = change.parts[0];
        if (first !== change.node) change.parent.insertBefore(change.node, first);
        change.node.data = change.before;
        change.parts.forEach(function (part) { if (part !== change.node) part.remove(); });
      });
      active.classes.forEach(function (change) {
        if (change.before === null) change.node.removeAttribute('class'); else change.node.setAttribute('class', change.before);
      });
      active.decorations.forEach(function (change) {
        if (change.before === null) change.node.removeAttribute(change.name); else change.node.setAttribute(change.name, change.before);
      });
      active = null; return true;
    }
    function activate(segment, mode) {
      owner(); clear(); validRoot(segment.par.root);
      clearLegacy(); owner(); validRoot(segment.par.root);
      var ids = selected(segment), root = segment.par.root;
      var paint = {root: root, ids: ids, mode: mode, texts: [], classes: [], decorations: [], after: new Map(), generated: new Map()};
      root.paragraphs.forEach(function (par) {
        var selectedSegments = par.segments.filter(function (s) { return s.ids.some(function (id) { return ids.indexOf(id) !== -1; }); });
        selectedSegments.filter(function (s) { return s.retained; }).forEach(function (s) {
          paint.classes.push({node: s.node, before: s.node.getAttribute('class')});
          s.node.classList.add('card-chunk-active');
        });
        var removed = selectedSegments.filter(function (s) { return !s.retained; }).sort(function (a, b) { return a.start - b.start; });
        par.texts.forEach(function (record) {
          var applicable = removed.filter(function (s) { return record.start <= s.start && s.end <= record.end; });
          if (!applicable.length) return;
          var source = record.node.data, pieces = [], cursor = 0;
          applicable.forEach(function (s) {
            var start = s.start - record.start, end = s.end - record.start;
            if (start > cursor) pieces.push({text: source.slice(cursor, start), segment: null});
            pieces.push({text: source.slice(start, end), segment: s}); cursor = end;
          });
          if (cursor < source.length) pieces.push({text: source.slice(cursor), segment: null});
          var parent = record.node.parentNode, fragment = doc.createDocumentFragment(), parts = [];
          pieces.forEach(function (piece, index) {
            var n = index === 0 ? record.node : doc.createTextNode(piece.text);
            if (index === 0) n.data = piece.text;
            if (piece.segment) {
              var span = doc.createElement('span');
              piece.segment.attrs.forEach(function (a) { span.setAttribute(a[0], a[1]); });
              span.classList.add('card-chunk-active'); span.setAttribute(PAINT, ''); span.appendChild(n);
              paint.generated.set(span, piece.segment);
              fragment.appendChild(span); parts.push(span);
            } else { fragment.appendChild(n); parts.push(n); }
          });
          // Moving the original Text into the fragment does not clone its
          // surrounding mark, ARIA, tabindex or unknown source elements.
          parent.insertBefore(fragment, record.next || null);
          paint.texts.push({node: record.node, parent: parent, before: source, parts: parts});
        });
      });
      if (mode === 'hover') {
        var parNode = segment.par.node, title = segment.attrs.find(function (a) { return a[0] === 'title'; });
        if (title) { paint.decorations.push({node: parNode, name: 'title', before: parNode.getAttribute('title')}); parNode.setAttribute('title', title[1]); }
        paint.decorations.push({node: parNode, name: 'style', before: parNode.getAttribute('style')}); parNode.style.cursor = 'pointer';
      }
      root.paragraphs.forEach(function (par) { paint.after.set(par, tree(par.node)); });
      active = paint; handled++;
    }
    function point(par, at, endBias) {
      var walker = doc.createTreeWalker(par.node, win.NodeFilter.SHOW_TEXT), n, offset = 0, last = null;
      while ((n = walker.nextNode())) {
        last = n;
        if (at < offset + n.data.length || endBias && at === offset + n.data.length) return [n, at - offset];
        offset += n.data.length;
      }
      return last && at === offset ? [last, last.data.length] : null;
    }
    function rangeFor(segment) {
      var a = point(segment.par, segment.start, false), z = point(segment.par, segment.end, true);
      if (!a || !z) fail('text range changed');
      var range = doc.createRange(); range.setStart(a[0], a[1]); range.setEnd(z[0], z[1]); return range;
    }
    function hit(event, keyboard) {
      var target = element(event.target);
      if (!target || target.closest(CONTROL)) return null;
      var parNode = target.closest('[' + PAR + ']'), par = parNode && paragraphs.get(parNode.getAttribute(PAR));
      if (!par || par.node !== parNode) return null;
      validRoot(par.root);
      if (keyboard) {
        var chunk = target.closest('.card-chunk'), s = retained.get(chunk);
        return s && s.par === par ? s : null;
      }
      var caret;
      if (doc.caretRangeFromPoint) caret = doc.caretRangeFromPoint(event.clientX, event.clientY);
      else { var position = doc.caretPositionFromPoint(event.clientX, event.clientY); if (position) caret = {startContainer: position.offsetNode, startOffset: position.offset}; }
      if (!caret || !parNode.contains(caret.startContainer)) return null;
      var prefix = doc.createRange(); prefix.selectNodeContents(parNode); prefix.setEnd(caret.startContainer, caret.startOffset);
      var at = prefix.toString().length;
      var candidates = par.segments.filter(function (s) { return s.start <= at && at <= s.end; });
      candidates.sort(function (a, b) { return (b.depth || 0) - (a.depth || 0) || (a.end - a.start) - (b.end - b.start) || b.ordinal - a.ordinal; });
      return candidates.find(function (s) {
        return Array.from(rangeFor(s).getClientRects()).some(function (rect) {
          return rect.width !== 0 && rect.height !== 0 && event.clientX >= rect.left && event.clientX <= rect.right &&
            event.clientY >= rect.top && event.clientY <= rect.bottom;
        });
      }) || null;
    }
    function same(segment) { return active && active.root === segment.par.root && equal(active.ids, selected(segment)); }
    function mouse(event) { return (!event.pointerType || event.pointerType === 'mouse') && Date.now() >= ignoreMouseUntil; }
    function over(event, move) {
      if (!current() || !mouse(event)) return;
      var segment = hit(event, false);
      if (move && segment === hoverSegment) return;
      hoverSegment = segment;
      if (segment) { if (!same(segment)) activate(segment, 'hover'); }
      else if (active && active.mode === 'hover') clear();
    }
    function out(event) {
      if (!current() || !mouse(event)) return;
      var related = element(event.relatedTarget), chunk = related && related.closest('.card-chunk');
      var segment = chunk && (retained.get(chunk) || active && active.generated.get(chunk));
      hoverSegment = segment || null;
      if (segment && same(segment)) return;
      if (active && active.mode === 'hover') clear();
    }
    function listen(name, callback, capture) {
      var wrapped = function (event) {
        if (!current()) return;
        try { callback(event); } catch (error) { invalidate(error); }
      };
      try { doc.addEventListener(name, wrapped, capture || false); }
      catch (error) {
        listeners.forEach(function (row) { doc.removeEventListener(row[0], row[1], row[2]); });
        if (owners.get(doc) === ownerToken) owners.delete(doc);
        throw error;
      }
      listeners.push([name, wrapped, capture || false]);
    }
    if (win.PointerEvent) {
      listen('pointerover', function (e) { over(e, false); });
      listen('pointermove', function (e) { over(e, true); });
      listen('pointerout', out);
    } else {
      listen('mouseover', function (e) { over(e, false); });
      listen('mousemove', function (e) { over(e, true); });
      listen('mouseout', out);
      listen('touchstart', function () { ignoreMouseUntil = Date.now() + 1000; });
    }
    listen('click', function (event) {
      var s = hit(event, false);
      if (!s) { clear(); return; }
      hoverSegment = s;
      if (same(s) && active.mode === 'tap') clear(); else activate(s, 'tap');
      event.preventDefault(); event.stopPropagation();
    }, true);
    listen('keydown', function (event) {
      if (event.key === 'Escape') { clear(); return; }
      if ((event.key !== 'Enter' && event.key !== ' ') || event.defaultPrevented || event.repeat ||
          event.ctrlKey || event.metaKey || event.altKey) return;
      var s = hit(event, true);
      if (!s) return;
      if (same(s) && active.mode === 'tap') clear(); else activate(s, 'tap');
      keyboardHandled++; event.preventDefault(); event.stopPropagation();
    }, true);
    return Object.freeze({
      release: function () { if (!current()) return false; try { return clear(); } catch (e) { invalidate(e); return false; } },
      refresh: function () { owner(); roots.forEach(validRoot); return true; },
      stats: function () { return {schema: SCHEMA, roots: roots.size, paragraphs: paragraphs.size, handled: handled,
        keyboardHandled: keyboardHandled, validations: validations, disposed: disposed,
        invalid: invalid ? invalid.message : null, activeIds: active ? active.ids.slice() : []}; },
      dispose: function () {
        if (disposed) return;
        if (current()) { try { clear(); } catch (error) { invalidate(error); } }
        listeners.forEach(function (row) { doc.removeEventListener(row[0], row[1], row[2]); });
        if (owners.get(doc) === ownerToken) owners.delete(doc);
        disposed = true; active = null; hoverSegment = null; roots.clear(); paragraphs.clear(); retained.clear();
        listeners.length = 0; isCurrent = null; clearLegacy = null; onInvalid = null;
      }
    });
  }
  Object.defineProperty(window, 'StudyChunkIntervals', {value: Object.freeze({schema: SCHEMA, revision: REVISION, install: install}),
    enumerable: true, configurable: true, writable: false});
})();
