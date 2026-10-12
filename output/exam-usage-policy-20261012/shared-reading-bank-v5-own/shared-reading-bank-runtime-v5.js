/* OWN display-only consumer. Fetch belongs to the existing shell load hook.
 * Packed reader links must already be inflated by the card's pinned decoder.
 * No input handlers, text edits, frequency edits, ownership edits or AJAX.
 */
(function () {
  'use strict';
  if (window.AnkiSharedReadingBankRuntime) return;
  var SIDECAR_SHA = 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5';
  var installed = new WeakMap(), indexes = new WeakMap();
  var histories = '.sf-ownership-history,.sf-original-history-panel,.sf-ownership-authority,' +
    '.sf-archived-example,.sf-archived-native-example,.sf-inline-history,[data-native-ownership-history]';
  var sfRoots = '.sf-example,.sf-source-preview,.sf-year-preview';
  function demand(condition, message) { if (!condition) throw new Error(message); }
  function digest(value) {
    demand(window.crypto && window.crypto.subtle && window.TextEncoder, 'shared bank SHA runtime unavailable');
    return window.crypto.subtle.digest('SHA-256', new window.TextEncoder().encode(value)).then(function (buffer) {
      return Array.from(new Uint8Array(buffer)).map(function (n) { return n.toString(16).padStart(2, '0'); }).join('');
    });
  }
  function noSingleQuestion(part) {
    if (!part || typeof part !== 'object' || Array.isArray(part)) return false;
    return ['questionId', 'question_id'].every(function (key) { return part[key] === undefined || part[key] === null; });
  }
  function buildIndex(metadata) {
    demand(metadata && typeof metadata === 'object' && metadata.schema === 'exam-usage-shared-reading-bank.v5',
      'invalid shared bank sidecar');
    if (indexes.has(metadata)) return indexes.get(metadata);
    // The approved Python sidecar has exactly this serialized byte form.
    // Verify the whole fixed file pin before consuming any classifications.
    var bytes = JSON.stringify(metadata, null, 2) + '\n';
    var job = digest(bytes).then(function (actual) {
      demand(actual === SIDECAR_SHA, 'shared bank sidecar byte SHA mismatch');
      var snapshot = JSON.parse(bytes), groups = new Map(), bindings = new Map();
      snapshot.groups.forEach(function (group) { groups.set(group.group_id, group); });
      snapshot.sentence_bindings.forEach(function (binding) {
        demand(!bindings.has(binding.sentence_id), 'duplicate shared bank sentence identity');
        var group = groups.get(binding.group_id);
        demand(group && group.paper_id === binding.paper_id, 'shared bank binding group missing');
        var options = group.bank.filter(function (option) { return option.source_option_id === binding.source_option_id; });
        demand(options.length === 1, 'shared bank option identity ambiguous');
        bindings.set(binding.sentence_id, { binding: binding, group: group, option: options[0] });
      });
      var missing = snapshot.groups.filter(function (group) { return group.status === 'unknown'; });
      return { bindings: bindings, groups: groups,
        diagnostics: { sidecar_sha256: SIDECAR_SHA, verified_groups: snapshot.summary.verified_groups,
          missing_bank_groups: missing.map(function (group) { return {
            group_id: group.group_id, paper_id: group.paper_id, question_range: group.question_range,
            unknown_reasons: group.unknown_reasons, questions: group.questions.length
          }; }),
          unknown_questions: missing.reduce(function (n, group) { return n + group.questions.length; }, 0),
          info_text: '已审44套卷：27组共享选项库可核；另12组冻结题组缺原选项库，共60题答案对应仍未核实。未绑定原句保持原标签，不猜逐句归属。' } };
    });
    indexes.set(metadata, job);
    return job;
  }
  function oneParam(url, name) {
    var values = url.searchParams.getAll(name);
    demand(values.length === 1 && values[0], 'missing or duplicate original reader identity');
    return values[0];
  }
  function route(value, base) {
    var url = new URL(value, base);
    demand((url.protocol === 'http:' || url.protocol === 'https:') && !url.username && !url.password,
      'invalid original reader route');
    var id = oneParam(url, 'anki-codex-sentence');
    var match = /^(kaoyan:([0-9]{4}-0[12])):/.exec(id);
    demand(match, 'invalid original source sentence ID');
    var paper = match[1], name = match[2];
    if (url.pathname === '/exam-library/practice/full-paper.htm') {
      demand(oneParam(url, 'paper') === paper, 'original reader route paper differs');
    } else {
      demand(url.pathname === '/english-exams-reflow-latex/kaoyan/papers/' + name + '.htm',
        'original reader route is not the same source paper');
    }
    var englishHash = oneParam(url, 'anki-codex-hash'), reviewHash = oneParam(url, 'anki-codex-review');
    demand(/^[a-f0-9]{64}$/.test(englishHash) && /^[a-f0-9]{64}$/.test(reviewHash),
      'original reader source hashes malformed');
    var ranges = JSON.parse(oneParam(url, 'anki-codex-en'));
    demand(Array.isArray(ranges) && ranges.every(function (range) {
      return Array.isArray(range) && range.length === 2 && range.every(Number.isSafeInteger) &&
        range[0] >= 0 && range[0] < range[1];
    }), 'original reader target ranges malformed');
    var contexts = url.searchParams.getAll('anki-codex-context');
    demand(contexts.length <= 1, 'duplicate original reader candidate context');
    if (contexts.length) {
      var context = JSON.parse(contexts[0]);
      demand(noSingleQuestion(context), 'shared bank dual-key candidate claims a single question');
      ['reading_candidate', 'derivation_payload', 'option_context', 'reading_completion'].forEach(function (key) {
        if (context[key] !== undefined && context[key] !== null) {
          demand(noSingleQuestion(context[key]), 'shared bank dual-key derived source claims a single question');
        }
      });
    }
    return { sentence_id: id, paper_id: paper, english_hash: englishHash, review_hash: reviewHash, ranges: ranges };
  }
  function anchorIdentity(anchor, base) {
    demand(!anchor.hasAttribute('data-rb-j') && anchor.getAttribute('aria-disabled') !== 'true',
      'original reader anchor has not been successfully inflated');
    var values = ['href', 'data-latex-url', 'data-full-paper-url'].map(function (key) {
      return anchor.getAttribute(key);
    }).filter(Boolean);
    demand(values.length > 0, 'original reader anchor missing');
    var identities = values.map(function (value) { return route(value, base); });
    demand(identities.every(function (identity) { return JSON.stringify(identity) === JSON.stringify(identities[0]); }),
      'original reader anchors carry conflicting source identities');
    var candidate = anchor.getAttribute('data-reading-candidate');
    if (candidate !== null) demand(noSingleQuestion(JSON.parse(candidate)), 'shared bank dual-key DOM candidate claims a question');
    return identities[0];
  }
  function owned(container, element, kind) {
    if (element.closest(histories)) return false;
    return kind === 'native' ? element.closest('.example-card') === container : element.closest(sfRoots) === container;
  }
  function findOwned(container, selector, kind) {
    return Array.from(container.querySelectorAll(selector)).filter(function (element) { return owned(container, element, kind); });
  }
  function display(entry) {
    var option = entry.option, group = entry.group;
    var numbers = group.questions.filter(function (question) {
      return option.matched_question_ids.indexOf(question.question_id) !== -1;
    }).map(function (question) { return question.number; });
    var span = group.question_range[0] + '–' + group.question_range[1];
    var label = option.correctness === 'correct' ? '正确选项 ' + option.label + ' · 对应第' + numbers.join('、') + '题' :
      option.correctness === 'incorrect' ? '错误选项 ' + option.label + ' · ' + span + '题共享干扰项' :
      '答案未核实 ' + option.label + ' · ' + span + '题共享选项库';
    return { schema: 'exam-usage-shared-reading-bank-display.v5', group_id: group.group_id, question_id: null,
      option_label: option.label, source_option_id: option.source_option_id, correctness: option.correctness,
      matched_question_ids: option.matched_question_ids, matched_question_numbers: numbers,
      applicable_question_ids: group.questions.map(function (question) { return question.question_id; }),
      question_range: group.question_range, display_label: label, counting_effect: 'none',
      match_origins: ['option'], binding_sha256: entry.binding.binding_sha256,
      group_evidence_sha256: group.group_evidence_sha256 };
  }
  function install(root, metadata) {
    demand(root && root.querySelectorAll && (root.ownerDocument || root).createElement, 'shared bank DOM root invalid');
    if (installed.has(root)) return installed.get(root);
    var doc = root.ownerDocument || root, originals = new Map(), disposed = false, pending = false, generation = 0;
    var currentStats = {}, diagnostics = null, indexReady = buildIndex(metadata);
    function stamp(element, evidence, container) {
      if (!originals.has(element)) originals.set(element, { created: false, html: element.innerHTML,
        attributes: {}, lastHtml: null, lastAttributes: {}, container: container });
      var record = originals.get(element);
      var values = { 'data-shared-reading-bank-group-id': evidence.group_id,
        'data-shared-reading-bank-evidence': JSON.stringify(evidence),
        'data-shared-reading-bank-question-id': 'null',
        'data-shared-reading-bank-matched-question-ids': JSON.stringify(evidence.matched_question_ids) };
      Object.keys(values).forEach(function (key) {
        if (!(key in record.attributes)) record.attributes[key] = element.getAttribute(key);
        if (element.getAttribute(key) !== values[key]) element.setAttribute(key, values[key]);
        record.lastAttributes[key] = values[key];
      });
      return record;
    }
    function restore(element, record) {
      if (record.created && element.innerHTML === record.lastHtml && Object.keys(record.lastAttributes).every(function (key) {
        return element.getAttribute(key) === record.lastAttributes[key];
      })) { element.remove(); return; }
      if (element.innerHTML === record.lastHtml) element.innerHTML = record.html;
      Object.keys(record.attributes).forEach(function (key) {
        if (element.getAttribute(key) !== record.lastAttributes[key]) return;
        if (record.attributes[key] === null) element.removeAttribute(key);
        else element.setAttribute(key, record.attributes[key]);
      });
    }
    function retract(container) {
      originals.forEach(function (record, element) {
        if (record.container === container) { restore(element, record); originals.delete(element); }
      });
    }
    function apply(container, kind, evidence) {
      var labels = findOwned(container, '.exam-usage-labels', kind);
      demand(labels.length <= 1, 'shared bank display usage positions ambiguous');
      var label = labels[0], created = !label;
      var candidates = Array.from(label ? label.children : []).filter(function (child) {
        return /^(正确选项|错误选项|答案未核实) [A-H](?:$| ·)/.test(child.textContent);
      });
      demand(candidates.length <= 1, 'shared bank candidate labels ambiguous');
      var chip = candidates[0];
      if (chip) {
        var printed = /^(正确选项|错误选项|答案未核实) ([A-H])/.exec(chip.textContent);
        demand(printed[2] === evidence.option_label, 'shared bank existing printed letter conflicts');
        demand(printed[1] === '答案未核实' || printed[1] === (evidence.correctness === 'correct' ? '正确选项' : '错误选项'),
          'shared bank existing explicit correctness conflicts');
      }
      var place;
      if (!label) {
        place = kind === 'native' ? findOwned(container, '.example-source', kind) : findOwned(container, '.sf-source', kind);
        demand(place.length >= 1, 'shared bank source label position absent');
        label = doc.createElement('span'); label.className = 'exam-usage-labels';
        label.style.cssText = 'display:flex;flex-wrap:wrap;gap:.3rem;margin:.3rem 0;font-size:12px;line-height:1.5;color:var(--muted,#63718a)';
      }
      // All identity, source and existing-label checks finish before the first
      // mutation, so a rejected candidate cannot leave partial decorations.
      var record = stamp(label, evidence, container); if (created) { record.created = true; place[0].after(label); }
      if (!chip) {
        chip = doc.createElement('span'); chip.style.cssText = 'padding:1px 5px;border-radius:4px;background:var(--surface-soft,#f2f5fa)';
        label.prepend(chip);
      }
      if (chip.textContent !== evidence.display_label) chip.textContent = evidence.display_label;
      if (!Array.from(label.children).some(function (child) { return child.textContent === '匹配来自选项'; })) {
        var origin = doc.createElement('span'); origin.textContent = '匹配来自选项';
        origin.style.cssText = 'padding:1px 5px;border-radius:4px;background:var(--surface-soft,#f2f5fa)'; label.append(origin);
      }
      record.lastHtml = label.innerHTML;
    }
    async function process(container, kind, index, version, stats) {
      if (container.closest(histories)) { stats.skippedHistory++; return; }
      try {
        var anchors = findOwned(container, 'a.sentence-jump', kind);
        demand(anchors.length === 1, 'shared bank original source anchor count differs from one');
        var anchor = anchors[0], identity = anchorIdentity(anchor, doc.baseURI);
        var entry = index.bindings.get(identity.sentence_id);
        if (!entry) { stats.unbound++; retract(container); return; }
        var binding = entry.binding;
        demand(identity.paper_id === binding.paper_id && identity.english_hash === binding.english_hash &&
          identity.review_hash === binding.reviewed_content_hash, 'shared bank original source hash/review binding differs');
        var english = findOwned(container, kind === 'native' ? '.example-text' : '.sf-en', kind);
        demand(english.length === 1 && english[0].textContent === binding.english, 'shared bank actual English differs');
        demand(identity.ranges.every(function (range) { return range[1] <= Array.from(binding.english).length; }),
          'shared bank original target bounds differ');
        var text = english[0].textContent;
        demand(await digest(text) === binding.english_hash, 'shared bank actual English SHA differs');
        if (disposed || version !== generation || !root.contains(container)) return;
        demand(english[0].textContent === text && JSON.stringify(anchorIdentity(anchor, doc.baseURI)) === JSON.stringify(identity),
          'shared bank source changed during async verification');
        apply(container, kind, display(entry));
        stats[kind === 'native' ? 'projectedNative' : container.matches('.sf-source-preview,.sf-year-preview') ? 'projectedPreview' : 'projectedSf']++;
      } catch (error) {
        if (disposed || version !== generation) return;
        retract(container);
        stats.rejected++;
        stats.rejectionReasons[error.message] = (stats.rejectionReasons[error.message] || 0) + 1;
      }
    }
    async function refresh() {
      if (disposed) return currentStats;
      var version = ++generation, index = await indexReady;
      if (disposed || version !== generation) return currentStats;
      diagnostics = index.diagnostics;
      var stats = { projectedNative: 0, projectedSf: 0, projectedPreview: 0, unbound: 0, rejected: 0, skippedHistory: 0, rejectionReasons: {} };
      var containers = Array.from(root.querySelectorAll(sfRoots)).map(function (container) { return [container, 'sf']; });
      root.querySelectorAll('.example-card').forEach(function (container) {
        if (!container.closest(sfRoots)) containers.push([container, 'native']);
      });
      await Promise.all(containers.map(function (entry) { return process(entry[0], entry[1], index, version, stats); }));
      if (!disposed && version === generation) currentStats = stats;
      return currentStats;
    }
    var observer = new window.MutationObserver(function (records) {
      var relevant = records.some(function (record) {
        var element = record.target.nodeType === 1 ? record.target : record.target.parentElement;
        if (element && element.closest('.exam-usage-labels')) return false;
        if (record.type === 'childList') {
          var changed = Array.from(record.addedNodes).concat(Array.from(record.removedNodes));
          if (changed.length && changed.every(function (node) {
            return node.nodeType === 1 && node.matches('.exam-usage-labels');
          })) return false;
        }
        return true;
      });
      if (!relevant) return;
      if (pending || disposed) return;
      pending = true;
      Promise.resolve().then(function () { pending = false; if (!disposed) refresh().catch(function () {}); });
    });
    var handle = { refresh: refresh,
      stats: function () { return JSON.parse(JSON.stringify(currentStats)); },
      diagnostics: function () { return diagnostics && JSON.parse(JSON.stringify(diagnostics)); },
      dispose: function () {
        if (disposed) return;
        disposed = true; generation++; observer.disconnect();
        originals.forEach(function (record, element) { restore(element, record); });
        installed.delete(root);
      }
    };
    installed.set(root, handle);
    observer.observe(root.nodeType === 9 ? root.documentElement : root, { childList: true, subtree: true, characterData: true,
      attributes: true, attributeFilter: ['href', 'data-latex-url', 'data-full-paper-url', 'data-rb-j', 'data-reading-candidate'] });
    handle.ready = refresh();
    return handle;
  }
  window.AnkiSharedReadingBankRuntime = Object.freeze({ install: install, sidecarSha256: SIDECAR_SHA });
})();
