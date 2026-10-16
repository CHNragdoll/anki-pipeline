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


