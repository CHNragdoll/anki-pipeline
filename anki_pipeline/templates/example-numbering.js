/* Display ordinals follow current rows. Source IDs and occurrence counts are never changed. */
(function () {
  'use strict';
  if (window.AnkiExampleNumbering) { window.AnkiExampleNumbering.install(document); return; }
  var installed = new WeakMap();
  var history = '.sf-inline-history,.sf-ownership-history,.sf-ownership-authority,.sf-native-ownership-history,.sf-original-history-panel,.residual-owner-history,.sf-source-confirmation-history,.sf-semantic-resolution-history,.sf-final-history,.sf-archived-example,.sf-archived-native-example,.sf-pending,[data-native-ownership-history],[data-reviewed-source-comparison]';
  function install(root) {
    if (installed.has(root)) return installed.get(root);
    var originals = new Map(), disposed = false;
    var doc = root.nodeType === 9 ? root : root.ownerDocument;
    function prune() { originals.forEach(function (_, badge) { if (!root.contains(badge)) originals.delete(badge); }); }
    function refresh() {
      if (disposed) return;
      prune();
      root.querySelectorAll('ol.examples').forEach(function (list) {
        if (list.closest(history)) return;
        var number = 0;
        Array.from(list.children).forEach(function (row) {
          if (!row.matches('li.example-card') || row.hidden || row.closest(history) || doc.defaultView.getComputedStyle(row).display === 'none') return;
          number++;
          var badge = row.querySelector('.index-tag');
          if (!badge || badge.closest('li.example-card') !== row || badge.closest(history) || !/^\s*[0-9]+\s*$/.test(badge.textContent)) return;
          if (badge.textContent !== String(number)) {
            if (!originals.has(badge)) originals.set(badge, badge.textContent);
            badge.textContent = String(number);
          }
        });
      });
    }
    var observer = new doc.defaultView.MutationObserver(function (records) {
      if (records.some(function (record) { return record.removedNodes && record.removedNodes.length; })) prune();
      if (records.some(function (record) {
        var target = record.target.nodeType === 1 ? record.target : record.target.parentElement;
        if (target && !target.closest(history) && target.matches('ol.examples,li.example-card,.index-tag')) return true;
        return Array.from(record.addedNodes || []).some(function (node) { return node.nodeType === 1 && (node.matches('ol.examples,li.example-card') || node.querySelector('ol.examples')); });
      })) refresh();
    });
    var handle = { refresh: refresh, stats: function () { return { retainedBadges: originals.size }; }, dispose: function () {
      if (disposed) return; disposed = true; observer.disconnect();
      originals.forEach(function (text, badge) { badge.textContent = text; }); originals.clear(); installed.delete(root);
    } };
    installed.set(root, handle); refresh();
    observer.observe(root.nodeType === 9 ? root.documentElement : root, {childList:true,subtree:true,attributes:true,attributeFilter:['hidden','style','class']});
    return handle;
  }
  window.AnkiExampleNumbering = Object.freeze({ install: install });
  install(document);
})();
