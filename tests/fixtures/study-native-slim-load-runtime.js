/* Lossless local-media segments. The producer pins the exact UTF-8 HTML/JSON;
 * this renderer does no word matching, translation, or frequency arithmetic. */
(function () {
  'use strict';
  if (window.AnkiSlimApkgHydrate && window.__AnkiSlimStorageVersion === 'shared-v2') return;
  if (window.AnkiSlimApkgDispose) window.AnkiSlimApkgDispose();
  window.__AnkiSlimStorageVersion = 'shared-v2';
  var registry = window.AnkiSlimAssets = window.AnkiSlimAssets || Object.create(null);
  var pending = new Map(), verified = new Map(), current = null;
  var MAX_CACHE_BYTES = 32 * 1024 * 1024, cacheBytes = 0;
  var SCHEMA = 'anki-slim-segments.v1';
  function hash(value) {
    return window.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)).then(function (buffer) {
      return Array.from(new Uint8Array(buffer), function (byte) { return byte.toString(16).padStart(2, '0'); }).join('');
    });
  }
  function pin(part) {
    if (!part || typeof part.src !== 'string' || !/^_as_[a-f0-9]{24}\.js$/.test(part.src) ||
        typeof part.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(part.sha256) ||
        part.src !== '_as_' + part.sha256.slice(0, 24) + '.js') throw Error('本地片段标识无效');
    return part;
  }
  function cache(key, raw) {
    var size = new TextEncoder().encode(raw).byteLength;
    verified.set(key, { raw: raw, size: size }); cacheBytes += size;
    while (cacheBytes > MAX_CACHE_BYTES && verified.size > 1) {
      var oldest = verified.keys().next().value, item = verified.get(oldest);
      verified.delete(oldest); cacheBytes -= item.size; delete registry[oldest];
    }
  }
  function load(part) {
    pin(part);
    if (part.literal === true && registry[part.sha256] !== undefined && typeof registry[part.sha256] !== 'string') {
      throw Error('共享字典必须是原始文本');
    }
    if (verified.has(part.sha256)) {
      var cached = verified.get(part.sha256); verified.delete(part.sha256); verified.set(part.sha256, cached);
      return Promise.resolve(cached.raw);
    }
    if (pending.has(part.sha256)) return pending.get(part.sha256);
    var promise = new Promise(function (resolve, reject) {
      if (registry[part.sha256] !== undefined) { resolve(); return; }
      var script, finished = false, timer;
      function end(error) {
        if (finished) return; finished = true; window.clearTimeout(timer); if (script) script.remove();
        if (error) reject(error); else resolve();
      }
      function attempt(name, fallback) {
        if (script) script.remove();
        script = document.createElement('script'); script.src = name;
        script.onload = function () { end(); };
        script.onerror = function () {
          // Old and new packages may share a profile. Keep the old filenames
          // intact and use a fresh script element for an actual failed-load retry.
          if (fallback) attempt(part.src, false);
          else end(Error('本地片段媒体无法载入'));
        };
        document.head.append(script);
      }
      timer = window.setTimeout(function () { end(Error('本地片段媒体载入超时')); }, 30000);
      attempt(part.literal === true ? part.src : part.src.replace(/^_as_/, '_ac_'), part.literal !== true);
    }).then(async function () {
      var raw = registry[part.sha256];
      if (raw && typeof raw === 'object' && window.AnkiSlimPackedDecode) raw = await window.AnkiSlimPackedDecode(raw, load);
      if (typeof raw !== 'string') throw Error('本地片段内容缺失');
      if (await hash(raw) !== part.sha256) { delete registry[part.sha256]; throw Error('本地片段校验失败'); }
      cache(part.sha256, raw); return raw;
    }).finally(function () { pending.delete(part.sha256); });
    pending.set(part.sha256, promise); return promise;
  }
  function manifest(script) {
    var value = JSON.parse(script.textContent);
    if (!value || value.schema !== SCHEMA || !Array.isArray(value.parts) ||
        !Number.isSafeInteger(value.total) || value.total < 0) throw Error('片段清单无效');
    var count = 0;
    value.parts.forEach(function (part) {
      pin(part); if (!Number.isSafeInteger(part.count) || part.count < 0) throw Error('片段条数无效');
      count += part.count; if (!Number.isSafeInteger(count)) throw Error('片段条数越界');
    });
    if (count !== value.total) throw Error('片段清单条数不一致');
    return value;
  }
  function reader(root) {
    var choice = window.__ankiExamSourceReader;
    if (choice !== 'latex' && choice !== 'full-paper') {
      try { choice = window.localStorage.getItem('anki:exam-source-reader:v1'); } catch (_) {}
    }
    root.querySelectorAll('.sentence-jump').forEach(function (link) {
      var section = link.closest('.examples-section'), control = section && section.querySelector('.source-reader');
      var selected = choice === 'full-paper' || choice === 'latex' ? choice : control && control.value || link.dataset.reader || 'latex';
      var address = selected === 'full-paper' ? link.dataset.fullPaperUrl : link.dataset.latexUrl;
      var valid = false;
      try { var url = new URL(address); valid = /^https?:$/.test(url.protocol) && !!url.hostname && !url.username && !url.password && !/[\u0000-\u0020\u007f]/.test(address); } catch (_) {}
      if (valid) { link.href = address; link.removeAttribute('aria-disabled'); }
      else { link.removeAttribute('href'); link.setAttribute('aria-disabled', 'true'); }
      link.title = '在' + (selected === 'latex' ? ' LaTeX 重排版' : '整卷版') + '定位原句';
      if (section) {
        var label = section.querySelector('.source-reader-setting');
        if (label) { label.hidden = false; label.classList.add('tappable'); }
        if (control) { control.value = selected; control.classList.add('tappable'); }
      }
    });
  }
  function index(data) {
    var result = new Map(), rows = data.as_native_index || [];
    if (!Array.isArray(rows)) throw Error('原句物理位置索引无效');
    rows.forEach(function (row) {
      if (!row || typeof row.source !== 'string' || typeof row.english !== 'string' ||
          typeof row.translation !== 'string' || typeof row.identity !== 'string') throw Error('原句物理位置索引无效');
      var identity = JSON.parse(row.identity);
      if (!Array.isArray(identity) || identity.length !== 3 || typeof identity[0] !== 'string' ||
          !/^(?:[a-f0-9]{64}|[A-Za-z0-9_-]{43})$/.test(identity[1]) ||
          !/^(?:[a-f0-9]{64}|[A-Za-z0-9_-]{43})$/.test(identity[2])) throw Error('原句物理位置证明无效');
      var key = JSON.stringify([row.source.trim(), row.english, row.translation.trim()]), values = result.get(key) || new Set();
      values.add(row.identity); result.set(key, values);
    });
    return result;
  }
  window.AnkiSlimPhysicalNativeIndex = function (doc) {
    return current && current.alive() && doc === document ? current.nativeIndex : new Map();
  };
  window.AnkiSlimPanelReady = function (panel) {
    if (!panel || typeof panel.querySelectorAll !== 'function') return false;
    // Read only this sense's direct slice marker. A paused, incomplete sense
    // must not prevent a different complete sense from grouping its rows.
    var scripts = panel.querySelectorAll(':scope > .as-lazy[data-as-kind="panel"] > script.as-manifest,:scope > .as-lazy[data-as-kind="sense"] > script.as-manifest,:scope > script.as-manifest');
    return Array.from(scripts).every(function (script) {
      try {
        var value = manifest(script), loaded = Number(script.dataset.asLoadedParts || '0');
        return Number.isSafeInteger(loaded) && loaded === value.parts.length;
      } catch (_) { return false; }
    });
  };
  function dispose() {
    window.__ankiFinalApkgGeneration = (window.__ankiFinalApkgGeneration || 0) + 1;
    var state = current; current = null;
    if (state) state.dispose();
    var handles = window.__ankiFinalApkgHandles || []; window.__ankiFinalApkgHandles = [];
    handles.reverse().forEach(function (handle) { if (handle && typeof handle.dispose === 'function') handle.dispose(); });
  }
  async function hydrate() {
    dispose();
    var payload = document.querySelector('script.anki-final-reviewed-data'); if (!payload) return;
    var generation = window.__ankiFinalApkgGeneration, slots = [], handles = [], observer = null;
    var queue = Promise.resolve(), historyBusy = new WeakSet(), known = new WeakSet();
    function alive() { return generation === window.__ankiFinalApkgGeneration && document.contains(payload); }
    function keep(handle) { handles.push(handle); window.__ankiFinalApkgHandles.push(handle); return handle; }
    var state = current = { alive: alive, nativeIndex: new Map(), dispose: function () {
      if (observer) observer.disconnect();
      document.removeEventListener('toggle', toggle, true); document.removeEventListener('click', click, true);
      window.removeEventListener('scroll', scroll, true); window.removeEventListener('resize', scroll);
      slots.forEach(function (slot) { if (slot.sentinel) slot.sentinel.remove(); });
    } };
    window.__ankiSlimManualRefresh = true;
    document.querySelectorAll('.vocab-card').forEach(function (el) { el.classList.add('rb-compact-note'); });
    var status = document.createElement('div'); status.className = 'anki-final-status'; status.setAttribute('role', 'status');
    // Normal hydration changes no visible content or spacing. The pre-existing
    // status style is used only if exact local-media verification fails.
    var fine, projected, bank, group;
    function filter(panel) {
      var selected = panel.querySelector('[data-sf-filter][aria-pressed="true"]'), year = selected ? selected.dataset.sfFilter : 'all';
      panel.querySelectorAll('.sf-example').forEach(function (row) { row.hidden = year !== 'all' && row.dataset.sfYear !== year; });
    }
    async function refresh(slot) {
      if (!alive()) return;
      fine.refresh(); projected.refresh();
      if (projected.stats().errors.length) throw Error('本卡细块核验失败');
      await bank.refresh(); if (!alive()) return;
      if (slot.panel) filter(slot.panel);
      // The compiled grouping helper checks AnkiSlimPanelReady for each
      // individual panel before touching its processed WeakSet.
      group.refresh();
    }
    function schedule(task) {
      var result = queue.then(function () { if (alive()) return task(); });
      queue = result.catch(function () {}); return result;
    }
    async function one(slot) {
      if (!alive() || !document.contains(slot.manifest) || slot.at >= slot.value.parts.length) return false;
      var position = slot.at, part = slot.value.parts[position], raw = await load(part);
      if (!alive() || !document.contains(slot.manifest) || slot.anchor.parentElement !== slot.holder || slot.at !== position) return false;
      var template = document.createElement('template'); template.innerHTML = raw;
      // Input is a build-pinned, original HTML slice; content scripts remain
      // inert during append. This also keeps archived proof scripts inert.
      if (window.AnkiSlimDecode) window.AnkiSlimDecode(template.content);
      var inserted = Array.from(template.content.children);
      slot.holder.insertBefore(template.content, slot.anchor);
      inserted.forEach(reader); discover(slot.holder);
      slot.at++; slot.manifest.dataset.asLoadedParts = String(slot.at);
      if (!alive()) return false;
      if (slot.sentinel) slot.sentinel.hidden = slot.at >= slot.value.parts.length;
      slot.manifest.dataset.asState = slot.at === slot.value.parts.length ? 'ready' : 'partial';
      if (status.dataset.asFailure === 'true' && !slots.some(function (item) { return item.manifest.dataset.asState === 'failed'; })) {
        status.remove(); delete status.dataset.asFailure;
      }
      return true;
    }
    function request(slot, all) {
      if (!alive() || slot.busy || slot.at >= slot.value.parts.length || Date.now() < slot.retryAfter) return slot.busy || Promise.resolve();
      slot.manifest.dataset.asState = 'loading';
      slot.holder.setAttribute('aria-busy', 'true');
      slot.busy = schedule(async function () {
        window.AnkiSlimBatching = (window.AnkiSlimBatching || 0) + 1;
        try {
          do {
            if (!await one(slot)) break;
            if (!all || !alive() || (slot.detail && !slot.detail.open)) break;
            await new Promise(function (resolve) { window.setTimeout(resolve, 0); });
          } while (slot.at < slot.value.parts.length);
        } finally { window.AnkiSlimBatching = Math.max(0, (window.AnkiSlimBatching || 1) - 1); }
        await refresh(slot);
      }).catch(function (error) {
        if (!alive() || !document.contains(slot.manifest)) return;
        slot.manifest.dataset.asState = 'failed';
        slot.retryAfter = Date.now() + 1000;
        status.dataset.asFailure = 'true';
        status.textContent = '本地片段载入失败：' + String(error.message || error);
        if (!document.contains(status)) payload.before(status);
      }).finally(function () {
        slot.busy = null;
        if (alive()) { slot.holder.removeAttribute('aria-busy'); if (slot.kind === 'examples') scroll(); }
      });
      return slot.busy;
    }
    function nearby(slot) {
      if (!slot.sentinel || slot.sentinel.hidden || slot.busy) return false;
      var rect = slot.sentinel.getBoundingClientRect();
      // A layout-less environment is not a scrolling viewport.
      return rect.height > 0 && rect.top < window.innerHeight + 500 && rect.bottom >= -50;
    }
    function scroll() { if (alive()) slots.forEach(function (slot) { if (slot.kind === 'examples' && nearby(slot)) request(slot, false); }); }
    async function history(detail) {
      var pre = detail.querySelector(':scope > pre[data-native-history-media]');
      if (!pre || historyBusy.has(pre) || pre.dataset.nativeHistoryReady === 'true') return;
      historyBusy.add(pre);
      try {
        var name = pre.dataset.nativeHistoryMedia, proof = pre.dataset.nativeHistorySha;
        if (!/^_af_[0-9a-f]{24}\.js$/.test(name) || !/^[a-f0-9]{64}$/.test(proof)) throw Error('证据媒体标识无效');
        if (typeof (window.AnkiFinalHistoryEvidence || {})[proof] !== 'string') await new Promise(function (resolve, reject) {
          var script = document.createElement('script'); script.src = name;
          script.onload = function () { script.remove(); resolve(); }; script.onerror = function () { script.remove(); reject(Error('本地证据媒体无法载入')); }; document.head.append(script);
        });
        var raw = (window.AnkiFinalHistoryEvidence || {})[proof]; if (typeof raw !== 'string') throw Error('证据内容缺失');
        if (await hash(raw) !== proof) throw Error('完整证据校验失败');
        if (alive() && document.contains(pre)) { pre.textContent = raw; pre.dataset.nativeHistoryReady = 'true'; }
      } catch (error) { if (alive() && document.contains(pre)) pre.textContent = '证据载入失败：' + String(error.message || error); }
      finally { historyBusy.delete(pre); }
    }
    function toggle(event) {
      var detail = event.target; if (!alive() || !detail.matches || !detail.matches('details[open]')) return;
      slots.filter(function (slot) { return slot.detail === detail; }).forEach(function (slot) { request(slot, true); });
      history(detail);
    }
    function click(event) {
      if (!alive()) return;
      var button = event.target.closest && event.target.closest('[data-sf-filter]'), panel = button && button.closest('.sf-panel');
      if (panel) { filter(panel); if (group) group.refresh(); }
    }
    function discover(root) {
      root.querySelectorAll('script.as-manifest').forEach(function (script) {
        if (known.has(script)) return; known.add(script);
        var anchor = script.parentElement.matches('.as-lazy') ? script.parentElement : script;
        var holder = anchor.parentElement, panel = holder.matches('.sf-panel') ? holder : holder.closest('.sf-panel');
        var declared = anchor.dataset.asKind;
        // A sentence's ownership/history disclosure can sit inside a sense
        // panel. Its owner is its nearest details, never the outer sense row.
        var detail = declared === 'detail' ? holder.closest('details') : panel ? panel.closest('details.sf-sense') : holder.closest('details');
        var kind = panel && declared !== 'detail' ? 'sense' : declared === 'examples' || holder.matches('ol.examples') ? 'examples' : detail ? 'disclosure' : 'eager';
        var slot = { manifest: script, anchor: anchor, holder: holder, panel: kind === 'sense' ? panel : null,
          detail: detail, kind: kind, value: manifest(script), at: 0, busy: null, sentinel: null, retryAfter: 0 };
        if (kind === 'examples' && slot.value.parts.length) {
          anchor.style.cssText = 'display:block;position:relative;height:0;padding:0;margin:0;border:0;list-style:none';
          slot.sentinel = document.createElement('span'); slot.sentinel.className = 'as-sentinel'; slot.sentinel.setAttribute('aria-hidden', 'true');
          slot.sentinel.style.cssText = 'position:absolute;top:0;left:0;width:1px;height:1px;padding:0;margin:0;border:0;pointer-events:none'; anchor.append(slot.sentinel);
        }
        slots.push(slot);
        if (observer && slot.kind === 'examples' && slot.sentinel) observer.observe(slot.sentinel);
      });
    }
    try {
      var raw = payload.textContent;
      if (payload.dataset.asSrc || payload.dataset.asSha) raw = await load({ src: payload.dataset.asSrc, sha256: payload.dataset.asSha });
      if (!alive()) return;
      var data = JSON.parse(raw), nativeData = data;
      if (payload.dataset.asIndexSrc || payload.dataset.asIndexSha) {
        var nativeRaw = await load({ src: payload.dataset.asIndexSrc, sha256: payload.dataset.asIndexSha });
        if (!alive()) return;
        nativeData = { as_native_index: JSON.parse(nativeRaw) };
      }
      state.nativeIndex = index(nativeData);
      fine = keep(window.AnkiFineChunkRuntime.install(document));
      var token = await window.AnkiReviewedChunkProjection.prepare(data); if (!alive()) return;
      projected = keep(window.AnkiReviewedChunkProjection.install(document, token, { isCurrent: alive }));
      if (projected.stats().errors.length) throw Error('本卡细块核验失败');
      bank = keep(window.AnkiSharedReadingBankRuntime.install(document, window.AnkiFinalReadingMetadata)); await bank.ready; if (!alive()) return;
      // Install grouping on the initial empty shell, and refresh only after
      // every loaded sense panel is complete; physical metadata is pre-pinned.
      group = keep(window.AnkiSameSenseGroupRuntime.install(document));
      keep(window.AnkiResidualReviewedChunkRuntime.install(document));
      discover(document);
      document.addEventListener('toggle', toggle, true); document.addEventListener('click', click, true);
      window.addEventListener('scroll', scroll, true); window.addEventListener('resize', scroll);
      if (window.IntersectionObserver) {
        observer = new window.IntersectionObserver(function (entries) {
          entries.forEach(function (entry) { if (entry.isIntersecting) { var slot = slots.find(function (item) { return item.sentinel === entry.target; }); if (slot) request(slot, false); } });
        }, { rootMargin: '500px' });
        slots.forEach(function (slot) { if (slot.kind === 'examples' && slot.sentinel) observer.observe(slot.sentinel); });
      }
      for (var n = 0; n < slots.length; n++) {
        var slot = slots[n];
        if (slot.kind === 'examples' && !slot.holder.querySelector(':scope > li.example-card,:scope > li._r28')) await request(slot, false);
        else if (slot.kind === 'eager' || slot.detail && slot.detail.open) await request(slot, true);
        if (!alive()) return;
      }
      if (!slots.some(function (slot) { return slot.manifest.dataset.asState === 'failed'; })) status.remove();
      payload.dataset.nativeState = 'ready'; scroll();
    } catch (error) {
      if (alive()) {
        status.textContent = '本卡细块核验失败：' + String(error.message || error);
        if (!document.contains(status)) payload.before(status);
        payload.dataset.nativeState = 'failed';
      }
    }
  }
  window.AnkiSlimApkgDispose = window.AnkiFinalApkgDispose = dispose;
  window.AnkiSlimApkgHydrate = window.AnkiFinalApkgHydrate = hydrate;
  window.StudySlimWarm = Object.freeze({load:load});
})();
