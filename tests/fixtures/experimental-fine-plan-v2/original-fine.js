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
    if (!window.__ankiSlimManualRefresh) observer.observe(cardDocument.documentElement, { childList: true, subtree: true, attributes: true,
      attributeFilter: ['data-chunk-ids', 'data-chunk-sentence-ids', 'class'] });
    return handle;
  }
  window.AnkiFineChunkRuntime = Object.freeze({ install: install });
})();