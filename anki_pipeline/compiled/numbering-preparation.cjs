'use strict';

// A synchronous preparation of the authenticated author's initial refresh only.
// This module never evaluates the authored script or installs its observers.
const crypto = require('node:crypto');

const NUMBERING_PIN = '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1';
const CANONICAL_NUMBERING_PIN = '00b6bb353c279483c8254c68a1a64a06f33476dd5cedbafd66767a32a5e7d626';
const NUMBERING_PINS = Object.freeze([NUMBERING_PIN, CANONICAL_NUMBERING_PIN]);
const HTML_NAMESPACE = 'http://www.w3.org/1999/xhtml';
const proofs = new WeakMap();
const SHA = text => crypto.createHash('sha256').update(text, 'utf8').digest('hex');
const STATES = new Set(['hover', 'active', 'focus', 'focus-visible', 'focus-within', 'visited',
  'link', 'any-link', 'target', 'target-within', 'fullscreen', 'modal', 'popover-open',
  'autofill', 'user-valid', 'user-invalid', 'playing', 'paused', 'seeking', 'buffering',
  'stalled', 'muted', 'volume-locked', 'picture-in-picture', 'state', 'checked', 'disabled',
  'enabled', 'required', 'optional', 'valid', 'invalid', 'in-range', 'out-of-range',
  'read-only', 'read-write', 'indeterminate', 'default', 'placeholder-shown', 'defined',
  'open', 'closed', 'current', 'past', 'future']);
const STATIC_PSEUDOS = new Set(['not', 'is', 'where', 'has', 'root', 'empty', 'first-child',
  'last-child', 'only-child', 'nth-child', 'nth-last-child', 'first-of-type', 'last-of-type',
  'only-of-type', 'nth-of-type', 'nth-last-of-type', 'lang', 'dir', 'scope']);

function requireThat(value, message) {
  if (!value) throw new Error(message);
}

function pathOf(node, doc) {
  const path = [];
  while (node !== doc) {
    const parent = node.parentNode;
    requireThat(parent, 'Numbering node is outside the live document');
    const index = Array.prototype.indexOf.call(parent.childNodes, node);
    requireThat(index >= 0, 'Numbering node has no live child position');
    path.push(index);
    node = parent;
  }
  return path.reverse();
}

function atPath(doc, path) {
  return path.reduce((node, index) => node && node.childNodes[index], doc);
}

function attributes(node) {
  requireThat(node.namespaceURI === HTML_NAMESPACE, 'Ambiguous numbering element namespace');
  const names = new Set();
  return Array.from(node.attributes, attribute => {
    requireThat(!names.has(attribute.name) && !attribute.namespaceURI,
      'Ambiguous numbering attribute namespace or duplicate qualified name');
    names.add(attribute.name);
    return [attribute.name, attribute.value];
  });
}

function checkAncestors(node, checked) {
  for (let element = node; element && element.nodeType === 1; element = element.parentElement) {
    if (checked.has(element)) break;
    attributes(element);
    checked.add(element);
  }
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// Split only top-level selector commas. Commas inside :is(), strings and attribute
// selectors are not list boundaries. Unknown/malformed selectors fail closed.
function selectorList(selector) {
  const result = [];
  let start = 0, quote = '', brackets = 0, parentheses = 0;
  for (let i = 0; i < selector.length; i++) {
    const char = selector[i];
    if (char === '\\') { i++; continue; }
    if (quote) { if (char === quote) quote = ''; continue; }
    if (char === '"' || char === "'") { quote = char; continue; }
    if (char === '[') brackets++;
    else if (char === ']') brackets--;
    else if (!brackets && char === '(') parentheses++;
    else if (!brackets && char === ')') parentheses--;
    else if (char === ',' && !brackets && !parentheses) {
      result.push(selector.slice(start, i).trim()); start = i + 1;
    }
    requireThat(brackets >= 0 && parentheses >= 0, 'Unknown display selector');
  }
  requireThat(!quote && !brackets && !parentheses, 'Unknown display selector');
  result.push(selector.slice(start).trim());
  requireThat(result.every(Boolean), 'Unknown display selector');
  return result;
}

// Remove environmental states to obtain a conservative structural superset.
// If a state occurs inside :not/:is/:has/etc, remove that whole function:
// simply deleting :hover within :not(:hover) would incorrectly narrow the set.
function structuralSelector(selector) {
  // Escaped pseudo names can hide environmental states from a lexical guard.
  // Escaped display selectors need separate qualification; do not guess.
  requireThat(!selector.includes('\\'), 'Unknown escaped numbering display selector');
  function scan(text) {
    let output = '', dynamic = false, pseudoElement = false;
    for (let i = 0; i < text.length;) {
      const char = text[i];
      if (char === '\\') { output += text.slice(i, i + 2); i += 2; continue; }
      if (char === '[' || char === '"' || char === "'") {
        const start = i, end = char === '[' ? ']' : char;
        let quote = char === '[' ? '' : char;
        i++;
        for (; i < text.length; i++) {
          if (text[i] === '\\') { i++; continue; }
          if (char === '[' && (text[i] === '"' || text[i] === "'")) {
            if (!quote) quote = text[i]; else if (quote === text[i]) quote = '';
          }
          if (text[i] === end && (char !== '[' || !quote)) { i++; break; }
        }
        output += text.slice(start, i); continue;
      }
      if (char !== ':') { output += char; i++; continue; }
      const match = /^(:{1,2})([a-zA-Z-]+)/.exec(text.slice(i));
      requireThat(match, 'Unknown display selector pseudo class');
      const name = match[2].toLowerCase(), start = i;
      const isPseudoElement = match[1] === '::' || ['before', 'after', 'first-line', 'first-letter'].includes(name);
      if (isPseudoElement) {
        pseudoElement = true;
      }
      requireThat(isPseudoElement || STATES.has(name) || STATIC_PSEUDOS.has(name),
        'Unknown numbering display selector pseudo class');
      i += match[0].length;
      let child = null;
      if (text[i] === '(') {
        const contentStart = ++i;
        let depth = 1, quote = '';
        for (; i < text.length && depth; i++) {
          if (text[i] === '\\') { i++; continue; }
          if (quote) { if (text[i] === quote) quote = ''; continue; }
          if (text[i] === '"' || text[i] === "'") { quote = text[i]; continue; }
          if (text[i] === '(') depth++;
          else if (text[i] === ')') depth--;
        }
        requireThat(!depth, 'Unknown display selector function');
        child = scan(text.slice(contentStart, i - 1));
      }
      if (STATES.has(name) || (child && child.dynamic)) dynamic = true;
      else output += text.slice(start, i);
    }
    return {selector: output.trim() || '*', dynamic, pseudoElement};
  }
  return scan(selector);
}

function qualifyStyles(doc, sources, rows, checked) {
  requireThat(Array.isArray(sources), 'Explicit complete styleSources are required');
  const nodes = new Set(), sheets = new Set(), links = new Set(), facts = [];
  for (const source of sources) {
    requireThat(source && ['inline', 'external'].includes(source.kind) &&
      typeof source.sourceText === 'string' && /^[a-f0-9]{64}$/.test(source.sha256 || '') &&
      SHA(source.sourceText) === source.sha256, 'Unauthenticated numbering stylesheet bytes');
    const node = source.node, original = source.sourceNode;
    requireThat(node && node.ownerDocument === doc && node.isConnected && node.localName === 'style' &&
      !node.closest('template') && node.textContent === source.sourceText && node.sheet &&
      !nodes.has(node) && !sheets.has(node.sheet), 'Unknown or duplicate live numbering style');
    checkAncestors(node, checked);
    requireThat(!node.disabled && (!node.type || node.type.toLowerCase() === 'text/css') &&
      (!node.media || node.media.trim().toLowerCase() === 'all'), 'Conditional or disabled numbering style');
    if (source.kind === 'inline') {
      requireThat(original === node, 'Inline numbering style source differs');
    } else {
      requireThat(original && original.ownerDocument === doc && original.isConnected &&
        original.localName === 'link' && original.nextSibling === node &&
        original.rel.trim().toLowerCase() === 'stylesheet' &&
        !original.disabled && (!original.media || original.media.trim().toLowerCase() === 'all') &&
        !links.has(original), 'External numbering style is not its original live link sibling');
      checkAncestors(original, checked);
      let url, base;
      try { url = new URL(original.href); base = new URL(doc.URL); }
      catch { throw new Error('Invalid external numbering style URL'); }
      requireThat(['http:', 'https:'].includes(url.protocol) && url.origin === base.origin &&
        !url.username && !url.password && !url.search && !url.hash &&
        url.pathname.split('/').at(-1) === '_study_' + source.sha256 + '.css',
      'External numbering style URL is not the authenticated same-origin CSS');
      links.add(original);
    }
    nodes.add(node); sheets.add(node.sheet);
    // textContent alone cannot authenticate insertRule/deleteRule mutations.
    // Parse only this already-pinned CSS with the same CSSOM implementation;
    // this detached constructed sheet adds no DOM, fetch, or live cascade.
    const expected = new doc.defaultView.CSSStyleSheet();
    expected.replaceSync(source.sourceText);
    const ruleText = sheet => JSON.stringify([...sheet.cssRules].map(rule => rule.cssText));
    requireThat(ruleText(expected) === ruleText(node.sheet),
      'Live numbering stylesheet CSSOM differs from authenticated source text');
    facts.push({kind: source.kind, sha256: source.sha256,
      stylePath: pathOf(node, doc), sourcePath: pathOf(original, doc)});
  }
  requireThat([...doc.querySelectorAll('style')].every(node => nodes.has(node)) &&
    [...doc.styleSheets].length === sheets.size && [...doc.styleSheets].every(sheet => sheets.has(sheet)),
  'Unqualified live numbering stylesheet');
  for (const link of doc.querySelectorAll('link[rel]')) {
    if (link.rel.toLowerCase().split(/\s+/).includes('stylesheet')) {
      requireThat(links.has(link), 'Unqualified external numbering style');
    }
  }
  requireThat(!doc.adoptedStyleSheets || doc.adoptedStyleSheets.length === 0,
    'Unqualified adopted numbering styles');

  function inspect(rules, conditional) {
    for (const rule of rules) {
      requireThat(rule.type !== 3 && !/^\s*@import\b/i.test(rule.cssText),
        'Unqualified stylesheet @import');
      const display = rule.style && rule.style.getPropertyValue('display');
      if (display) {
        requireThat(typeof rule.selectorText === 'string', 'Unknown conditional display rule');
        for (const selector of selectorList(rule.selectorText)) {
          const structural = structuralSelector(selector);
          if (structural.pseudoElement) continue;
          let matching;
          try { matching = rows.some(row => row.matches(structural.selector)); }
          catch { throw new Error('Unknown numbering display selector'); }
          requireThat(!matching || (!conditional && !structural.dynamic),
            'Conditional or environmental row display is not qualified');
        }
      }
      // CSSStyleRule.cssRules may be an empty array; a nested rule is still a
      // conditional scope unless it is an ordinary top-level selector rule.
      if (rule.cssRules && rule.cssRules.length) inspect(rule.cssRules, true);
    }
  }
  for (const sheet of sheets) inspect(sheet.cssRules, false);
  return facts;
}

/**
 * Prepare only numeric badges using the pinned author's initial refresh rules.
 * The caller authenticates original HTML (including raw duplicate attributes)
 * and the causal origin of styleSources. This helper checks their exact live
 * CSS/CSSOM and DOM eligibility, not the provenance of arbitrary new styles.
 * External CSS must already be mounted as a temporary STYLE immediately after
 * its unchanged source LINK. The caller removes that mount after preparation.
 * No template contents, counts, source IDs, scripts, or other text are edited.
 */
function prepareInitialNumbering(doc, options) {
  requireThat(doc && doc.nodeType === 9 && doc.defaultView &&
    typeof doc.defaultView.getComputedStyle === 'function', 'A live CSS-capable source document is required');
  requireThat(options && NUMBERING_PINS.includes(options.sourcePin) &&
    typeof options.sourceCode === 'string' && SHA(options.sourceCode) === options.sourcePin,
  'Unknown original numbering source');
  const historyMatch = [...options.sourceCode.matchAll(/var history = '([^']+)';/g)];
  requireThat(historyMatch.length === 1, 'Unknown original numbering history guard');
  const history = historyMatch[0][1], checked = new Set();
  const canonical = options.sourcePin === CANONICAL_NUMBERING_PIN;
  const lists = [...doc.querySelectorAll('ol.examples')];
  // The two exact author cohorts have different initial row ownership rules.
  // Preserve legacy direct-child semantics; canonical sections share their
  // nearest logical ol, excluding nested ordinary rows in that same ol.
  const listRows = list => canonical ? [...list.querySelectorAll('li.example-card')].filter(row => {
    if (row.closest('ol.examples') !== list) return false;
    const parent = row.parentElement.closest('li.example-card');
    return !parent || parent.closest('ol.examples') !== list;
  }) : [...list.children];
  const rowScope = (row, list) => {
    const scope = [row];
    if (canonical) for (let node = row.parentElement; node && node !== list; node = node.parentElement) scope.push(node);
    return scope;
  };
  const rows = [];
  for (const list of lists) {
    checkAncestors(list, checked);
    if (list.closest(history)) continue;
    for (const row of listRows(list)) {
      checkAncestors(row, checked);
      if (row.matches('li.example-card') && !row.hidden && !row.closest(history)) rows.push(...rowScope(row, list));
    }
  }
  const styleFacts = qualifyStyles(doc, options.styleSources, [...new Set(rows)], checked);
  const edits = [], bindings = [], listFacts = [];
  const stats = {lists: lists.length, excludedLists: 0, eligibleRows: 0, missingBadges: 0,
    invalidBadges: 0, foreignOrHistoryFirstBadges: 0, legalBadges: 0, changedBadges: 0};
  for (const list of lists) {
    if (list.closest(history)) { stats.excludedLists++; continue; }
    let number = 0;
    for (const row of listRows(list)) {
      if (!row.matches('li.example-card') || row.hidden || row.closest(history)) continue;
      let visible = true;
      for (const node of rowScope(row, list)) {
        if (node.hidden) { visible = false; break; }
        const display = doc.defaultView.getComputedStyle(node).display;
        if (node === row) requireThat(display === 'none' || display === 'list-item', 'Unknown computed numbering row display');
        if (display === 'none') { visible = false; break; }
      }
      if (!visible) continue;
      number++; stats.eligibleRows++;
      const badge = row.querySelector('.index-tag');
      if (!badge) { stats.missingBadges++; continue; }
      if (badge.closest('li.example-card') !== row || badge.closest(history)) {
        stats.foreignOrHistoryFirstBadges++; continue;
      }
      checkAncestors(badge, checked);
      const before = badge.textContent;
      if (!/^\s*[0-9]+\s*$/.test(before)) { stats.invalidBadges++; continue; }
      requireThat(badge.childNodes.length === 1 && badge.firstChild.nodeType === 3,
        'Legal numbering badge is not one original Text slot');
      stats.legalBadges++;
      const after = String(number), text = badge.firstChild;
      if (before !== after) {
        edits.push({decodedBefore: before, after, beforeSha256: SHA(before), afterSha256: SHA(after),
          ordinal: number, listPath: pathOf(list, doc), rowPath: pathOf(row, doc),
          badgePath: pathOf(badge, doc), textPath: pathOf(text, doc),
          rowKey: row.getAttribute('data-study-compiled-key'),
          badgeClosestLIIsRow: true, history: false});
        bindings.push({text, row, badge, list, rowAttributes: attributes(row), badgeAttributes: attributes(badge)});
        stats.changedBadges++;
      }
    }
    listFacts.push({path: pathOf(list, doc), eligibleRows: number});
  }
  // All source, CSS, eligibility and slot checks precede every mutation.
  const proof = freeze({schema: 'study-original-numbering-dom-preparation.v1',
    numberingSha256: options.sourcePin, historySelector: history, styleFacts, stats, listFacts, edits,
    rawAttributeQualification: 'caller-source-qualification'});
  for (let i = 0; i < edits.length; i++) bindings[i].text.data = edits[i].after;
  proofs.set(proof, {doc, bindings, undone: false});
  return proof;
}

function inverse(doc, proof) {
  const state = proofs.get(proof);
  requireThat(state, 'Unrecognized original numbering proof');
  requireThat(state.doc === doc, 'Numbering inverse document differs');
  requireThat(!state.undone, 'Numbering proof has already been reversed');
  for (let i = 0; i < proof.edits.length; i++) {
    const edit = proof.edits[i], binding = state.bindings[i];
    requireThat(atPath(doc, edit.textPath) === binding.text && atPath(doc, edit.rowPath) === binding.row &&
      atPath(doc, edit.badgePath) === binding.badge && atPath(doc, edit.listPath) === binding.list &&
      binding.badge.childNodes.length === 1 && binding.badge.firstChild === binding.text &&
      binding.text.data === edit.after &&
      JSON.stringify(attributes(binding.row)) === JSON.stringify(binding.rowAttributes) &&
      JSON.stringify(attributes(binding.badge)) === JSON.stringify(binding.badgeAttributes),
    'Numbering inverse target changed after preparation');
  }
  for (let i = 0; i < proof.edits.length; i++) state.bindings[i].text.data = proof.edits[i].decodedBefore;
  state.undone = true;
  return proof;
}

module.exports = {prepareInitialNumbering, inverse, NUMBERING_PIN, CANONICAL_NUMBERING_PIN, NUMBERING_PINS};
