/* Display ordinals follow current rows. Source IDs and occurrence counts are never changed. */
(function () {
  'use strict';
  if (window.AnkiExampleNumbering) { window.AnkiExampleNumbering.install(document); return; }
  var installed = new WeakMap();
  var history = '.sf-inline-history,.sf-ownership-history,.sf-ownership-authority,.sf-native-ownership-history,.sf-original-history-panel,.residual-owner-history,.sf-source-confirmation-history,.sf-semantic-resolution-history,.sf-final-history,.sf-archived-example,.sf-archived-native-example,.sf-pending,[data-native-ownership-history],[data-reviewed-source-comparison]';
  function install(root) {
    if (installed.has(root)) return installed.get(root);
    var originals = new Map(), disposed = false, observing = false, ownedMutations = new WeakMap();
    var doc = root.nodeType === 9 ? root : root.ownerDocument;
    function prune() { originals.forEach(function (_, badge) { if (!root.contains(badge)) originals.delete(badge); }); }
    function sameNodes(actual, expected) {
      if (actual.length !== expected.length) return false;
      for (var n = 0; n < actual.length; n++) if (actual[n] !== expected[n]) return false;
      return true;
    }
    function consumeOwned(record, batch) {
      if (record.type !== 'childList') return false;
      var queue = batch.get(record.target), expected = queue && queue.entries[queue.next];
      if (!expected || !sameNodes(record.addedNodes, expected.added) || !sameNodes(record.removedNodes, expected.removed)) return false;
      queue.next++;
      if (queue.next === queue.entries.length) batch.delete(record.target);
      return true;
    }
    function refresh() {
      if (disposed) return;
      prune();
      var updates = [];
      root.querySelectorAll('ol.examples').forEach(function (list) {
        if (list.closest(history)) return;
        var number = 0;
        Array.from(list.querySelectorAll('li.example-card')).forEach(function (row) {
          if (row.closest('ol.examples') !== list || row.closest(history)) return;
          var parentRow = row.parentElement.closest('li.example-card');
          if (parentRow && parentRow.closest('ol.examples') === list) return;
          for (var ancestor = row; ancestor && ancestor !== list; ancestor = ancestor.parentElement) {
            if (ancestor.hidden || doc.defaultView.getComputedStyle(ancestor).display === 'none') return;
          }
          number++;
          var badge = row.querySelector('.index-tag');
          if (!badge || badge.closest('li.example-card') !== row || badge.closest(history) || !/^\s*[0-9]+\s*$/.test(badge.textContent)) return;
          if (badge.textContent !== String(number)) {
            updates.push({ badge: badge, original: badge.textContent, text: String(number) });
          }
        });
      });
      updates.forEach(function (update) {
        if (!originals.has(update.badge)) originals.set(update.badge, update.original);
        var removed = observing ? Array.from(update.badge.childNodes) : null;
        update.badge.textContent = update.text;
        if (observing) {
          var queue = ownedMutations.get(update.badge) || { entries: [], next: 0 };
          queue.entries.push({ removed: removed, added: Array.from(update.badge.childNodes) });
          ownedMutations.set(update.badge, queue);
        }
      });
    }
    var observer = new doc.defaultView.MutationObserver(function (records) {
      var batch = ownedMutations; ownedMutations = new WeakMap();
      if (records.some(function (record) { return record.removedNodes && record.removedNodes.length; })) prune();
      records = records.filter(function (record) { return !consumeOwned(record, batch); });
      if (records.some(function (record) {
        var target = record.target.nodeType === 1 ? record.target : record.target.parentElement;
        if (target && !target.closest(history) && (target.matches('ol.examples,li.example-card,.index-tag') || (record.type === 'attributes' && target.closest('ol.examples')))) return true;
        return Array.from(record.addedNodes || []).concat(Array.from(record.removedNodes || [])).some(function (node) { return node.nodeType === 1 && (node.matches('ol.examples,li.example-card') || node.querySelector('ol.examples,li.example-card')); });
      })) refresh();
    });
    var handle = { refresh: refresh, stats: function () { return { retainedBadges: originals.size }; }, dispose: function () {
      if (disposed) return; disposed = true; observing = false; observer.disconnect(); ownedMutations = new WeakMap();
      originals.forEach(function (text, badge) { badge.textContent = text; }); originals.clear(); installed.delete(root);
    } };
    installed.set(root, handle); refresh();
    observer.observe(root.nodeType === 9 ? root.documentElement : root, {childList:true,subtree:true,attributes:true,attributeFilter:['hidden','style','class']});
    observing = true;
    return handle;
  }
  window.AnkiExampleNumbering = Object.freeze({ install: install });
  install(document);
})();
