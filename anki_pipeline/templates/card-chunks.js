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
    return { root: root, ids: candidates, side: side };
  }
  function selectedIds(selected) {
    // An English overlap retains its authored first-ID priority. A Chinese
    // span can name several equally confirmed English chunks.
    var values = selected.side === 'en' ? selected.ids.slice(0, 1) : selected.ids.slice();
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
    window.__ankiCardChunkState = { root: selected.root, ids: selected.ids, side: selected.side, mode: mode };
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
