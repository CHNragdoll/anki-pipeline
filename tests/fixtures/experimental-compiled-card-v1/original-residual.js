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
