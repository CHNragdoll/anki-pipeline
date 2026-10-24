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
  function retainedTargetRanges(en) { return ranges(textView(en), function (el) { return el.matches('mark.target-word') && en.contains(el); }); }
