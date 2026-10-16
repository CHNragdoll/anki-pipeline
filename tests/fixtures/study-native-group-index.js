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
