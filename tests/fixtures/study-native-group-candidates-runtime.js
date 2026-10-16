/* Presentation only: physical occurrences and all source evidence remain intact. */
(function () {
  'use strict';
  var installed = new WeakMap();
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
  function sourceKey(source, en, zh) { return JSON.stringify([source, en, zh]); }
  function physicalNativeIndex(doc) {
    var result = new Map();
    doc.querySelectorAll('li.example-card,li._r28').forEach(function (row) {
      var en = row.querySelector('.example-text,._r31'), zh = row.querySelector('.example-translation,._r34'), source = row.querySelector('.example-source,._r36');
      var link = row.querySelector('.sentence-jump,[data-rb-j]'); if (!en || !zh || !source || !link) return;
      var translation = zh.cloneNode(true); translation.querySelectorAll('.translation-label,.translate-tag,._r35').forEach(function (el) { el.remove(); });
      var identity;
      try {
        if (link.hasAttribute('data-rb-j')) {
          var fields = link.getAttribute('data-rb-j').split('|');
          if (fields.length < 6 || !/^[A-Za-z0-9_-]{43}$/.test(fields[3]) || !/^[A-Za-z0-9_-]{43}$/.test(fields[4])) return;
          identity = JSON.stringify(['kaoyan:' + fields[1] + ':' + decodeURIComponent(fields[2]), fields[3], fields[4]]);
        } else {
          var url = new URL(link.href, doc.URL), p = url.searchParams;
          if (!p.get('anki-codex-sentence') || !/^[a-f0-9]{64}$/.test(p.get('anki-codex-hash') || '') || !/^[a-f0-9]{64}$/.test(p.get('anki-codex-review') || '')) return;
          identity = JSON.stringify([p.get('anki-codex-sentence'), p.get('anki-codex-hash'), p.get('anki-codex-review')]);
        }
      } catch (_) { return; }
      var key = sourceKey(source.textContent.trim(), en.textContent, translation.textContent.trim()), identities = result.get(key) || new Set(); identities.add(identity); result.set(key, identities);
    }); return result;
  }
  function install(doc) {
    if (installed.has(doc)) return installed.get(doc);
    var disposed = false, groups = [], restores = [], processed = new WeakSet(), style = doc.createElement('style');
    style.textContent = '.sf-group-evidence{margin-block:.6rem;min-width:0;overflow-wrap:anywhere}.sf-group-evidence>summary{cursor:pointer;min-height:36px;display:flex;align-items:center}.sf-group-member-evidence{border-top:1px solid #e5ebf4;padding-block:.5rem}.sf-group-member-evidence pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}'; doc.head.append(style);
    function attribute(el, name, value) { var before = el.getAttribute(name); restores.push(function () { if (before === null) el.removeAttribute(name); else el.setAttribute(name, before); }); el.setAttribute(name, value); }
    function relocate(el, parent) { var before = el.parentNode, next = el.nextSibling; restores.push(function () { before.insertBefore(el, next && next.parentNode === before ? next : null); }); parent.append(el); }
    function markTargets(en, targets) {
      var view = textView(en);
      view.nodes.forEach(function (part) {
        if (part.node.parentElement.closest('mark.target-word')) return;
        var cuts = new Set([part.start, part.end]); targets.forEach(function (r) { if (r[0] > part.start && r[0] < part.end) cuts.add(r[0]); if (r[1] > part.start && r[1] < part.end) cuts.add(r[1]); });
        var bounds = Array.from(cuts).sort(function (a, b) { return a - b; }), fragments = [], touched = false;
        for (var n = 0; n < bounds.length - 1; n++) {
          var start = bounds[n], end = bounds[n + 1], text = doc.createTextNode(part.node.data.slice(start - part.start, end - part.start));
          if (targets.some(function (r) { return r[0] <= start && r[1] >= end; })) { var mark = doc.createElement('mark'); mark.className = 'target-word'; mark.append(text); fragments.push(mark); touched = true; } else fragments.push(text);
        }
        if (!touched) return;
        var parent = part.node.parentNode, next = part.node.nextSibling; fragments.forEach(function (el) { parent.insertBefore(el, part.node); }); part.node.remove();
        restores.push(function () { parent.insertBefore(part.node, fragments[0] && fragments[0].parentNode === parent ? fragments[0] : next && next.parentNode === parent ? next : null); fragments.forEach(function (el) { el.remove(); }); });
      });
    }
    function updatePanel(panel) {
      var filter = panel.querySelector('[data-sf-filter][aria-pressed="true"]'), year = filter ? filter.dataset.sfFilter : 'all';
      groups.filter(function (group) { return group.panel === panel; }).forEach(function (group) {
        group.members.forEach(function (member, n) { member.hidden = n > 0 || (year !== 'all' && member.dataset.sfYear !== year); });
      });
      var status = panel.querySelector('.sf-preview-count'); if (!status) return;
      var count = Array.from(panel.querySelectorAll(':scope > .sf-example')).filter(function (row) { return !row.hidden; }).length;
      var label = '显示 ' + count + ' 条原文'; if (status.textContent !== label) status.textContent = label;
    }
    function refresh() {
      if (disposed) return; var natives = physicalNativeIndex(doc);
      if (window.AnkiSlimPhysicalNativeIndex) window.AnkiSlimPhysicalNativeIndex(doc).forEach(function(values,key){var current=natives.get(key)||new Set();values.forEach(function(v){current.add(v);});natives.set(key,current);});
      doc.querySelectorAll('.sf-sense > .sf-panel').forEach(function (panel) {
        if (window.AnkiSlimPanelReady && !window.AnkiSlimPanelReady(panel)) return;
        var buckets = new Map();
        panel.querySelectorAll(':scope > .sf-example').forEach(function (row) {
          if (processed.has(row)) return;
          var pair = row.querySelector(':scope > .sf-sentence-pair'), source = row.querySelector(':scope > .sf-source'), oid = row.dataset.sfOccurrenceId;
          if (!pair || !source || !/^[a-f0-9]{64}$/.test(oid || '')) return;
          var en = pair.querySelector(':scope > .sf-en'), zh = pair.querySelector(':scope > .sf-zh'); if (!en || !zh) return;
          var physical = natives.get(sourceKey(source.textContent.trim(), en.textContent, zh.textContent.trim())); if (!physical || physical.size !== 1) return;
          var usage = row.querySelector(':scope > .exam-usage-labels'), graph = chunkGraph(pair);
          var signature = Array.from(graph.values()).sort();
          var key = JSON.stringify([Array.from(physical)[0], row.dataset.sfYear, source.textContent.trim(), en.textContent, zh.textContent, usage ? usage.textContent : '', signature]);
          var bucket = buckets.get(key) || []; bucket.push({ row: row, pair: pair, graph: graph }); buckets.set(key, bucket);
        });
        buckets.forEach(function (entries) {
          if (entries.length < 2) return;
          var memberIds = entries.map(function (entry) { return entry.row.dataset.sfOccurrenceId; }); if (new Set(memberIds).size !== memberIds.length) return;
          var first = entries[0], chosen = new Set(), targets = [], bySignature = new Map();
          first.graph.forEach(function (signature, id) { if (!bySignature.has(signature)) bySignature.set(signature, []); bySignature.get(signature).push(id); });
          entries.forEach(function (entry) {
            processed.add(entry.row);
            var en = entry.pair.querySelector(':scope > .sf-en');
            ranges(textView(en), function (el) { return el.matches('mark.target-word') && en.contains(el); }).forEach(function (record) { targets.push.apply(targets, record.ranges); });
            entry.pair.querySelectorAll(':scope > p .sf-target-chunk').forEach(function (el) { ids(el).forEach(function (id) { (bySignature.get(entry.graph.get(id)) || []).forEach(function (mapped) { chosen.add(mapped); }); }); });
          });
          markTargets(first.pair.querySelector(':scope > .sf-en'), mergeRanges(targets));
          first.pair.querySelectorAll(':scope > p .card-chunk').forEach(function (el) { if (ids(el).some(function (id) { return chosen.has(id); }) && !el.classList.contains('sf-target-chunk')) attribute(el, 'class', el.className + ' sf-target-chunk'); });
          attribute(first.row, 'data-sf-group-member-ids', JSON.stringify(memberIds)); attribute(first.row, 'data-sf-group-occurrences', String(entries.length));
          var detail = doc.createElement('details'); detail.className = 'sf-group-evidence'; var summary = doc.createElement('summary'); summary.textContent = '本句各处依据与归属说明'; detail.append(summary); first.row.append(detail);
          restores.push(function () { detail.remove(); });
          entries.forEach(function (entry, n) {
            var section = doc.createElement('section'); section.className = 'sf-group-member-evidence'; section.dataset.sfGroupMemberId = memberIds[n]; detail.append(section);
            var label = doc.createElement('p'); label.className = 'sf-source'; label.textContent = '目标位置 ' + (n + 1); section.append(label);
            Array.from(entry.row.children).filter(function (el) { return el !== entry.pair && el !== detail && !el.matches('.sf-source,.exam-usage-labels'); }).forEach(function (el) { relocate(el, section); });
            entry.pair.querySelectorAll(':scope > [data-reviewed-source-comparison]').forEach(function (el) { relocate(el, section); });
            var hidden = entry.row.hidden; restores.push(function () { entry.row.hidden = hidden; });
          });
          groups.push({ panel: panel, members: entries.map(function (entry) { return entry.row; }) });
        });
        if (!panel.hasAttribute('data-sf-group-count-ready')) { var status = panel.querySelector('.sf-preview-count'), old = status && status.textContent; if (status) restores.push(function () { status.textContent = old; }); attribute(panel, 'data-sf-group-count-ready', 'true'); }
        updatePanel(panel);
      });
    }
    function filter(event) { var button = event.target.closest && event.target.closest('[data-sf-filter]'), panel = button && button.closest('.sf-panel'); if (panel) updatePanel(panel); }
    var handle = { refresh: refresh, stats: function () { return { groups: groups.length, groupedOccurrences: groups.reduce(function (n, group) { return n + group.members.length; }, 0), hiddenDuplicateRows: groups.reduce(function (n, group) { return n + group.members.length - 1; }, 0) }; }, dispose: function () { if (disposed) return; disposed = true; doc.removeEventListener('click', filter, true); restores.reverse().forEach(function (restore) { restore(); }); style.remove(); installed.delete(doc); } };
    installed.set(doc, handle); doc.addEventListener('click', filter, true); refresh(); return handle;
  }
  window.AnkiSameSenseGroupRuntime = Object.freeze({ install: install });
})();