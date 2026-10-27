// Rendered spans contain only validated, existing chunk IDs. Never match words
// or translations here; the shared Python renderer owns exact text/range checks.
(function () {
  function element(value) {
    return value && typeof value.closest === 'function' ? value : value && value.parentElement;
  }
  function ids(chunk) {
    var value = chunk && chunk.dataset.chunkIds;
    return typeof value === 'string' && /^\d+( \d+)*$/.test(value) ? value.split(' ') : [];
  }
  function sentenceIds(chunk) {
    var value = chunk && chunk.dataset.chunkSentenceIds;
    return typeof value === 'string' && /^\d+( \d+)*$/.test(value) ? value.split(' ') : [];
  }
  function choice(value) {
    var target = element(value);
    // Preserve source navigation, audio, controls, and disclosure behavior even
    // if a future template places one inside a chunk span.
    if (!target || typeof target.closest !== 'function' ||
        target.closest('a, button, input, select, textarea, summary, audio, video, [role="button"], [contenteditable]')) return null;
    var chunk = target.closest('.card-chunk');
    var candidates = ids(chunk);
    var side = chunk && chunk.dataset.chunkSide;
    var root = chunk && chunk.closest('.example-card');
    if (!root || !candidates.length || (side !== 'en' && side !== 'zh')) return null;
    return { root: root, ids: candidates, sentenceIds: sentenceIds(chunk), side: side };
  }
  function selectedIds(selected) {
    // An English overlap retains its authored first-ID priority. A Chinese
    // span can name several equally confirmed English chunks.
    var candidates = selected.ids;
    if (selected.side === 'zh' && selected.sentenceIds) {
      var finer = candidates.filter(function (id) { return selected.sentenceIds.indexOf(id) === -1; });
      if (finer.length) candidates = finer;
    }
    var values = selected.side === 'en' ? candidates.slice(0, 1) : candidates.slice();
    return values.filter(function (id, index) { return values.indexOf(id) === index; }).sort();
  }
  function same(left, right) {
    if (!left || !right || left.root !== right.root) return false;
    var leftIds = selectedIds(left), rightIds = selectedIds(right);
    return leftIds.length === rightIds.length && leftIds.every(function (id, index) {
      return id === rightIds[index];
    });
  }
  function clear() {
    var state = window.__ankiCardChunkState;
    if (state) state.root.querySelectorAll('.card-chunk').forEach(function (chunk) {
      chunk.classList.remove('card-chunk-active');
    });
    window.__ankiCardChunkState = null;
  }
  function activate(selected, mode) {
    clear();
    var activeIds = selectedIds(selected);
    selected.root.querySelectorAll('.card-chunk').forEach(function (chunk) {
      var chunkIds = ids(chunk);
      chunk.classList.toggle('card-chunk-active', activeIds.some(function (id) {
        return chunkIds.indexOf(id) !== -1;
      }));
    });
    window.__ankiCardChunkState = { root: selected.root, ids: selected.ids,
      sentenceIds: selected.sentenceIds, side: selected.side, mode: mode };
  }
  // Anki reuses the webview between card sides and cards. Clear old state while
  // keeping one delegated event set that can also handle newly inserted spans.
  clear();
  document.querySelectorAll('.card-chunk-active').forEach(function (chunk) {
    chunk.classList.remove('card-chunk-active');
  });
  if (window.__ankiCardChunksBound) return;
  window.__ankiCardChunksBound = true;
  var ignoreMouseUntil = 0;
  function mouse(event) {
    return (!event.pointerType || event.pointerType === 'mouse') && Date.now() >= ignoreMouseUntil;
  }
  function over(event) {
    if (!mouse(event)) return;
    var selected = choice(event.target);
    if (selected) {
      if (!same(selected, window.__ankiCardChunkState)) activate(selected, 'hover');
    } else if (window.__ankiCardChunkState && window.__ankiCardChunkState.mode === 'hover') clear();
  }
  function out(event) {
    if (!mouse(event)) return;
    var state = window.__ankiCardChunkState;
    if (state && state.mode === 'hover' && same(choice(event.target), state) &&
        !same(choice(event.relatedTarget), state)) clear();
  }
  if (window.PointerEvent) {
    document.addEventListener('pointerover', over);
    document.addEventListener('pointerout', out);
  } else {
    document.addEventListener('mouseover', over);
    document.addEventListener('mouseout', out);
    document.addEventListener('touchstart', function () { ignoreMouseUntil = Date.now() + 1000; }, { passive: true });
  }
  document.addEventListener('click', function (event) {
    var selected = choice(event.target);
    if (!selected) { clear(); return; }
    var state = window.__ankiCardChunkState;
    if (same(selected, state) && state.mode === 'tap') clear();
    else activate(selected, 'tap');
    // Capture prevents a chunk tap from reaching an Anki/card flip handler.
    // Other clicks retain their native default and propagation.
    event.preventDefault();
    event.stopPropagation();
  }, true);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') clear();
  });
})();

// Native details supply expand/collapse even if JavaScript is unavailable.
(function () {
  if (window.__ankiSenseFrequencyBound) return;
  window.__ankiSenseFrequencyBound = true;
  function clearPinnedChunks(report) {
    // The original card-chunks.js owns bilingual hover/tap behavior. Clear its
    // pinned state when filtering hides a sentence or Escape leaves emphasis.
    // Default .sf-target-chunk accents remain, because they are source markup.
    var state = window.__ankiCardChunkState;
    if (!state || state.root.closest('.sf-report') !== report) return;
    state.root.querySelectorAll('.card-chunk-active').forEach(function (chunk) {
      chunk.classList.remove('card-chunk-active');
    });
    window.__ankiCardChunkState = null;
  }
  document.addEventListener('click', function (event) {
    var target = event.target.closest && event.target.closest('.sf-report');
    if (!target) return;
    // Retain native summary/button activation, but keep review tap zones and
    // card flip handlers from interpreting a sense/year tap as a rating.
    event.stopPropagation();
    var filter = event.target.closest('[data-sf-filter]');
    if (!filter) return;
    var panel = filter.closest('.sf-panel');
    if (!panel) return;
    clearPinnedChunks(target);
    var year = filter.dataset.sfFilter, count = 0;
    panel.querySelectorAll('[data-sf-filter]').forEach(function (button) {
      button.setAttribute('aria-pressed', String(button === filter));
    });
    panel.querySelectorAll('.sf-example').forEach(function (example) {
      example.hidden = year !== 'all' && example.dataset.sfYear !== year;
      if (!example.hidden) count += 1;
    });
    var status = panel.querySelector('.sf-preview-count');
    if (status) status.textContent = '显示 ' + count + ' 处原文';
  }, true);
  document.addEventListener('keydown', function (event) {
    var report = event.target.closest && event.target.closest('.sf-report');
    if (!report) return;
    if (event.key === 'Escape') clearPinnedChunks(report);
    event.stopPropagation();
  }, true);
})();

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

/* Reviewed residual spans reuse the existing bilingual click delegate. */
(function () {
  'use strict';
  var installed = new WeakMap();
  function install(doc) {
    if (installed.has(doc)) return installed.get(doc);
    var disposed = false;
    function keyboard(event) {
      if (disposed || event.defaultPrevented || event.repeat || event.ctrlKey || event.altKey || event.metaKey ||
          (event.key !== 'Enter' && event.key !== ' ')) return;
      var el = event.target;
      if (!el || !el.matches || !el.matches('.card-chunk[data-reviewed-chunk-projection="residual"]') ||
          !/^[0-9]+(?: [0-9]+)*$/.test(el.getAttribute('data-chunk-ids') || '') ||
          el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable],.sf-archived-example,.sf-inline-history')) return;
      var whole = (el.getAttribute('data-chunk-sentence-ids') || '').split(' ');
      if (el.getAttribute('data-chunk-ids').split(' ').every(function (id) { return whole.indexOf(id) >= 0; })) return;
      event.preventDefault();
      el.dispatchEvent(new doc.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    }
    var handle = { dispose: function () {
      if (disposed) return; disposed = true;
      doc.removeEventListener('keydown', keyboard, true); installed.delete(doc);
    } };
    installed.set(doc, handle); doc.addEventListener('keydown', keyboard, true); return handle;
  }
  window.AnkiResidualReviewedChunkRuntime = Object.freeze({ install: install });
})();

window.AnkiFineChunkRuntime.install(document);window.AnkiResidualReviewedChunkRuntime.install(document);
