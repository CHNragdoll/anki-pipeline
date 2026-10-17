'use strict';

/**
 * Pure, build-time execution of the already audited semantic renderers.
 *
 * Usage: node semantic-producer.cjs REQUEST.json NEW_OUTPUT_DIRECTORY
 * No source script startup, network transport, browser readiness or learning
 * state is simulated. The result is the existing intermediate binding draft;
 * the shared profile emitter and binder retain their own validation boundary.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { TextDecoder, TextEncoder } = require('node:util');

const SCHEMA = 'study-compiled-semantic-request.v1';
const PREPARED_MODULES = Object.freeze({
  '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e':
    '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4',
  'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93':
    '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633',
});
const SHA = /^[a-f0-9]{64}$/;
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const utf8 = raw => new TextDecoder('utf-8', { fatal: true }).decode(raw);
const attributes = element => Array.from(element.attributes, item => [item.name, item.value]);

function demand(condition, message) {
  if (!condition) throw Error(message);
}
function record(value, name) {
  demand(value !== null && typeof value === 'object' && !Array.isArray(value), 'Invalid ' + name);
  return value;
}
function pin(value, name) {
  demand(typeof value === 'string' && SHA.test(value), 'Invalid SHA: ' + name);
  return value;
}
function fileDescriptor(value, name) {
  record(value, name);
  demand(typeof value.path === 'string' && path.isAbsolute(value.path) && !value.path.includes('\0'), 'Invalid local path: ' + name);
  pin(value.sha256, name);
  return value;
}
function readPinned(value, name, ledger) {
  fileDescriptor(value, name);
  // Decode the authenticated bytes, never re-open the path after hashing it.
  const raw = fs.readFileSync(value.path);
  demand(hash(raw) === value.sha256, 'Source SHA differs: ' + name);
  if (ledger) ledger.set(value.path, { path: value.path, sha256: value.sha256, bytes: raw.length });
  return utf8(raw);
}
function logicalURL(value, name) {
  demand(typeof value === 'string' && !/[\x00-\x20\x7f\\]/.test(value), 'Invalid URL: ' + name);
  const url = new URL(value);
  demand(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash,
    'Invalid logical URL: ' + name);
  demand(url.href === value, 'Noncanonical logical URL: ' + name);
  return url;
}
function validateModule(value) {
  record(value, 'module');
  pin(value.original_sha256, 'original module');
  demand(Object.hasOwn(PREPARED_MODULES, value.original_sha256), 'Unsupported native module cohort');
  demand(value.sha256 === PREPARED_MODULES[value.original_sha256], 'Audited prepared module SHA differs');
}

function validateArtifact(artifact, source, module) {
  record(artifact, 'prepared artifact');
  record(source, 'source binding');
  validateModule(module);
  demand(artifact.schema === 'study-prepared-card.v1', 'Unsupported prepared artifact schema');
  for (const [a, b] of [['source_wrapper_sha256', 'wrapper_sha256'], ['source_payload_sha256', 'payload_sha256']]) {
    pin(source[b], b);
    demand(artifact[a] === source[b], 'Prepared source binding differs: ' + a);
  }
  demand(Array.isArray(artifact.sides) && artifact.sides.length === 2, 'Complete front/back artifact required');
  for (const side of artifact.sides) {
    record(side, 'prepared side');
    demand(typeof side.html === 'string' && Array.isArray(side.children), 'Invalid complete prepared side');
    const proof = record(side.proof, 'side proof');
    pin(proof.source_sha256, 'side source');
    demand(hash(side.html) === proof.expanded_sha256, 'Expanded side SHA differs');
    demand(Buffer.byteLength(side.html) === proof.expanded_bytes && Number.isSafeInteger(proof.source_bytes)
      && proof.source_bytes >= 0 && proof.original_source_unmodified === true, 'Expanded side byte proof differs');
    const registry = record(side.registry, 'registry');
    for (const [key, raw] of Object.entries(registry)) {
      pin(key, 'registry');
      demand(typeof raw === 'string' && hash(raw) === key, 'Registry content SHA differs');
    }
    demand(Array.isArray(proof.registry_pins) && JSON.stringify(proof.registry_pins) === JSON.stringify(Object.keys(registry).sort()),
      'Registry pin census differs');
  }
  const modules = record(artifact.modules, 'prepared modules');
  demand(Object.keys(modules).length === 1 && Object.hasOwn(modules, module.original_sha256), 'Prepared module source binding differs');
  const descriptor = record(modules[module.original_sha256], 'prepared module descriptor');
  demand(descriptor.original_sha256 === module.original_sha256 && descriptor.sha256 === module.sha256
    && typeof descriptor.src === 'string' && descriptor.src.length > 0, 'Prepared module SHA binding differs');
  return { side: artifact.sides[1], descriptor };
}

/** Explicit local allowlist: there is deliberately no network fallback. */
function createResourceResolver(resources, scope, ledger = new Map()) {
  record(resources, 'resource manifest');
  const base = logicalURL(scope, 'resource scope');
  demand(base.pathname.endsWith('/'), 'Resource scope must be a directory');
  const entries = new Map();
  for (const [url, descriptor] of Object.entries(resources)) {
    const parsed = logicalURL(url, 'resource');
    demand(parsed.origin === base.origin && parsed.pathname.startsWith(base.pathname), 'Resource leaves approved base');
    fileDescriptor(descriptor, 'resource');
    entries.set(url, { path: descriptor.path, sha256: descriptor.sha256 });
  }
  const cache = new Map();
  return async (url, expected) => {
    const parsed = logicalURL(url, 'resource lookup');
    demand(parsed.origin === base.origin && parsed.pathname.startsWith(base.pathname), 'Resource leaves approved base');
    const descriptor = entries.get(parsed.href);
    demand(descriptor, 'Unknown producer resource');
    demand(descriptor.sha256 === expected && SHA.test(expected), 'Resource expected pin differs');
    if (!cache.has(parsed.href)) cache.set(parsed.href, readPinned(descriptor, 'resource', ledger));
    return cache.get(parsed.href);
  };
}

function validatePolicy(policy) {
  record(policy, 'author policy');
  record(policy.external, 'external policy');
  demand(Array.isArray(policy.inline), 'Invalid inline policy');
  for (const [name, value] of Object.entries(policy.external)) {
    demand(name.length > 0, 'Invalid external policy name');
    pin(value, 'author external');
  }
  const seen = new Set();
  for (const rule of policy.inline) {
    record(rule, 'inline rule');
    demand(typeof rule.source === 'string' && hash(rule.source) === rule.sha256 && !seen.has(rule.source), 'Inline author SHA differs');
    seen.add(rule.source);
  }
}

// These are the accepted producer's four read-only closure captures. No private
// Map, target assignment, grouping decision or undo log is replaced or seeded.
const CAPTURE_EDITS = Object.freeze([
  ['    installed.set(cardDocument, handle); refresh();',
    "    window.__canonicalProducerCapture('fine',function(){return {stats:handle.stats()};});\n    installed.set(cardDocument, handle); refresh();"],
  ["    installed.set(doc, handle); doc.addEventListener('keydown', keyboard, true); refresh();",
    "    window.__canonicalProducerCapture('projection',function(){return {wrappers:Array.from(wrappers),comparisons:comparisons.slice(),stats:handle.stats()};});\n    installed.set(doc, handle); doc.addEventListener('keydown', keyboard, true); refresh();"],
  ['    installed.set(root, handle);\n    if (!window.__ankiSlimManualRefresh) observer.observe',
    "    window.__canonicalProducerCapture('bank',function(){return {records:Array.from(originals),stats:handle.stats(),diagnostics:handle.diagnostics()};});\n    installed.set(root, handle);\n    if (!window.__ankiSlimManualRefresh) observer.observe"],
  ["    installed.set(doc, handle); doc.addEventListener('click', filter, true); refresh(); return handle;",
    "    window.__canonicalProducerCapture('group',function(){return {groups:groups.map(function(g){return {panel:g.panel,members:g.members.slice()};}),stats:handle.stats()};});\n    installed.set(doc, handle); doc.addEventListener('click', filter, true); refresh(); return handle;"],
].map(Object.freeze));
function instrument(source) {
  let code = source;
  for (const [before, after] of CAPTURE_EDITS) {
    demand(code.split(before).length === 2, 'Native capture boundary differs');
    code = code.replace(before, after);
  }
  let inverse = code;
  for (const [before, after] of [...CAPTURE_EDITS].reverse()) {
    demand(inverse.split(after).length === 2, 'Native inverse boundary differs');
    inverse = inverse.replace(after, before);
  }
  demand(inverse === source, 'Native capture inverse differs');
  return { code, inverse, edits: CAPTURE_EDITS };
}

function nativeScriptReferences(scripts, originalPin) {
  demand(Array.isArray(scripts), 'Author collector result differs');
  const count = scripts.filter(item => item.pin === originalPin).length;
  // A complete answer can contain both original front and back scripts. The
  // collector checks each reference; its module is still defined only once.
  demand(count > 0, 'Native module script census differs');
  return count;
}

function loadRequest(filename) {
  const requestPath = path.resolve(filename);
  const requestRaw = fs.readFileSync(requestPath);
  const request = JSON.parse(utf8(requestRaw));
  record(request, 'request');
  demand(request.schema === SCHEMA, 'Unsupported semantic request schema');
  const sourceURL = logicalURL(request.source_url, 'source_url');
  const baseURL = logicalURL(request.base_url, 'base_url');
  const scope = new URL('.', sourceURL).href;
  demand(baseURL.origin === sourceURL.origin && baseURL.pathname.endsWith('/') && baseURL.href.startsWith(scope), 'Base URL leaves source directory');
  validatePolicy(request.policy);
  validateModule(request.module);
  const ledger = new Map();
  const artifact = JSON.parse(readPinned(request.artifact, 'artifact', ledger));
  const { side, descriptor } = validateArtifact(artifact, request.source, request.module);
  const moduleCode = readPinned(request.module, 'module', ledger);
  const helpers = readPinned(request.helpers, 'helpers', ledger);
  const resource = createResourceResolver(request.resources, scope, ledger);
  return { request, requestPath, requestSha: hash(requestRaw), artifact, side, descriptor, moduleCode, helpers, resource, ledger };
}

function jsonFile(output, name, value) {
  const raw = JSON.stringify(value, null, 2) + '\n';
  fs.writeFileSync(path.join(output, name), raw, { flag: 'wx' });
  return { path: name, bytes: Buffer.byteLength(raw), sha256: hash(raw) };
}

/** Blocking regular-file writes can still be short; account for actual bytes. */
function writeAll(fd, buffer, writeSync = fs.writeSync) {
  let offset = 0;
  while (offset < buffer.length) {
    const remaining = buffer.length - offset;
    const written = writeSync(fd, buffer, offset, remaining);
    demand(Number.isInteger(written) && written > 0 && written <= remaining, 'Incomplete output write');
    offset += written;
  }
  return offset;
}

/** Publish only the still-open caller-owned inode and its completed bytes. */
function publishNoReplace(partial, final, fd, expected) {
  demand(expected && Number.isSafeInteger(expected.bytes) && expected.bytes >= 0, 'Invalid completed output size');
  pin(expected.sha256, 'completed output');
  const owner = fs.fstatSync(fd);
  demand(owner.isFile() && owner.size === expected.bytes, 'Completed output size differs');
  function owns(filename) {
    let actual;
    try { actual = fs.lstatSync(filename); }
    catch (error) { if (error.code === 'ENOENT') return false; throw error; }
    return actual.isFile() && actual.dev === owner.dev && actual.ino === owner.ino;
  }
  demand(owns(partial), 'Partial output ownership differs');
  const digest = crypto.createHash('sha256'), buffer = Buffer.allocUnsafe(65536);
  let position = 0;
  while (position < expected.bytes) {
    const count = fs.readSync(fd, buffer, 0, Math.min(buffer.length, expected.bytes - position), position);
    demand(count > 0, 'Completed output read is incomplete');
    digest.update(buffer.subarray(0, count)); position += count;
  }
  const verified = fs.fstatSync(fd);
  demand(digest.digest('hex') === expected.sha256 && verified.size === owner.size
    && verified.mtimeMs === owner.mtimeMs && owns(partial), 'Completed output content/ownership differs');
  // Both paths are in the same newly created output directory. Unlike rename,
  // link fails with EEXIST if another writer published that final name first.
  // Keep our partial intact on that failure for diagnosis/recovery.
  fs.linkSync(partial, final);
  demand(owns(final), 'Published output ownership differs');
  // The pathname may have been replaced after linking. It no longer grants
  // permission to delete that replacement, even though our final is valid.
  if (owns(partial)) {
    try { fs.unlinkSync(partial); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}

function copyAttributes(source, target) {
  for (const item of Array.from(target.attributes)) target.removeAttribute(item.name);
  for (const item of source.attributes) target.setAttribute(item.name, item.value);
}

async function prepareInitialHistory(doc, request, resource) {
  const plans = [];
  for (const pre of doc.querySelectorAll('pre[data-native-history-media],pre[data-native-history-sha]')) {
    const name = pre.getAttribute('data-native-history-media'), pin = pre.getAttribute('data-native-history-sha');
    demand(/^_af_[a-f0-9]{24}\.js$/.test(name || '') && /^[a-f0-9]{64}$/.test(pin || ''), 'Initial history reference');
    const url = new URL(name, request.base_url).href, descriptor = request.resources[url];
    demand(descriptor && /^[a-f0-9]{64}$/.test(descriptor.sha256 || ''), 'Initial history source capability absent');
    const raw = await resource(url, descriptor.sha256);
    demand(typeof raw === 'string' && hash(raw) === descriptor.sha256, 'Initial history resource SHA');
    const match = raw.match(/^window\.AnkiFinalHistoryEvidence=window\.AnkiFinalHistoryEvidence\|\|\{\};window\.AnkiFinalHistoryEvidence\["([a-f0-9]{64})"\]=([\s\S]*);$/);
    demand(match && match[1] === pin, 'Initial history inert registration');
    const text = JSON.parse(match[2]);
    demand(typeof text === 'string' && hash(text) === pin, 'Initial history original text SHA');
    if (pre.getAttribute('data-native-history-ready') === 'true') demand(pre.textContent === text, 'Initial ready evidence differs');
    plans.push({ pre, name, pin, text, resourcePin: descriptor.sha256,
      beforeText: pre.textContent, beforeAttrs: attributes(pre), beforeHTML: pre.outerHTML });
  }
  // Qualify every source before changing any node. The active original loader
  // treats ready=true as complete, so it never rewrites these protected nodes.
  return plans.map((plan, ordinal) => {
    const { pre } = plan;
    pre.textContent = plan.text;
    pre.setAttribute('data-native-history-ready', 'true');
    const inverse = pre.cloneNode(false);
    for (const attr of Array.from(inverse.attributes)) inverse.removeAttribute(attr.name);
    for (const [name, value] of plan.beforeAttrs) inverse.setAttribute(name, value);
    inverse.textContent = plan.beforeText;
    demand(inverse.outerHTML === plan.beforeHTML, 'Initial history expansion inverse');
    return { ordinal, media: plan.name, sha256: plan.pin, resource_sha256: plan.resourcePin,
      original_text: plan.beforeText, original_attributes: plan.beforeAttrs,
      original_pre_dom_sha256: hash(plan.beforeHTML), prepared_pre_dom_sha256: hash(pre.outerHTML),
      original_text_sha256: hash(plan.beforeText), complete_text_sha256: hash(pre.textContent), inverse_exact: true };
  });
}

async function produce(requestPath, outputPath) {
  const started = Date.now();
  const output = path.resolve(outputPath);
  demand(!fs.existsSync(output), 'Output directory already exists');
  const input = loadRequest(requestPath); // authenticate before creating output
  const { request, artifact, side, descriptor, moduleCode, helpers, resource } = input;
  fs.mkdirSync(output); // intentionally neither recursive nor replace-existing
  const phases = [];
  const phase = name => phases.push({ phase: name, elapsed_ms: Date.now() - started });
  const { JSDOM, VirtualConsole } = require('jsdom');
  const { implForWrapper } = require('jsdom/lib/generated/idl/utils');
  const serializationAdapter = require('jsdom/lib/jsdom/living/domparsing/parse5-adapter-serialization');
  const errors = [], captures = new Map(), console = new VirtualConsole();
  console.on('jsdomError', error => errors.push({ name: error.name, message: error.message }));
  // The collector resolves prepared modules relative to source_url, while
  // authored resources and the eventual native DOM use base_url. Add the live
  // media <base> only after collect has authenticated every original script.
  const dom = new JSDOM('<!doctype html><html><head></head><body></body></html>', {
    url: request.source_url, runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: console,
  });
  const win = dom.window, doc = win.document;
  Object.defineProperty(win.crypto, 'subtle', { value: crypto.webcrypto.subtle, configurable: true });
  win.TextEncoder = TextEncoder;
  win.TextDecoder = TextDecoder;
  win.__studyProducerResource = resource;
  win.__ankiExamSourceReader = 'full-paper';
  // The original semantic batch boundary is preserved without a visual layout
  // service; no browser-ready, font-ready or Cigen-ready assertion is made.
  win.__ankiCigenFrames = { refresh() {}, batch(action) { return action(); } };
  win.__canonicalProducerCapture = (name, getter) => {
    demand(!captures.has(name) && typeof getter === 'function', 'Duplicate native capture');
    captures.set(name, getter);
  };
  try {
    phase('input-authenticated');
    let parsed = new win.DOMParser().parseFromString(side.html, 'text/html');
    const bases = parsed.querySelectorAll('base');
    demand(bases.length === 1, 'Prepared side must have one explicit base');
    bases[0].href = request.base_url;
    win.eval(helpers);
    const adapter = win.ProducerNativeAdapter;
    demand(adapter && ['adapt', 'execute', 'matches', 'collect'].every(name => typeof adapter[name] === 'function'), 'Producer helper API differs');
    const sourceScripts = Array.from(parsed.scripts);
    const scriptSnapshots = sourceScripts.map(node => ({ node, type: node.getAttribute('type'), html: node.outerHTML, text: node.textContent }));
    const scripts = await adapter.collect(parsed, { base: request.base_url, policy: request.policy, prepared: artifact });
    const nativeReferences = nativeScriptReferences(scripts, request.module.original_sha256);
    const authoredOrder = scripts.map((item, index) => ({ index, original_sha256: item.pin,
      adapted_sha256: item.code === null ? null : hash(item.code), module: item.pin === request.module.original_sha256, executed: false }));
    const adapted = adapter.adapt(moduleCode, request.module.original_sha256);
    const captured = instrument(adapted);
    const inverse = jsonFile(output, 'capture-inverse.json', {
      source_prepared_sha256: request.module.sha256, canonical_adapted_sha256: hash(adapted),
      captured_sha256: hash(captured.code), inverse_sha256: hash(captured.inverse), inverse_exact: true,
      readonly_hooks: 4, no_fine_undo_export: true, edits: captured.edits,
    });
    adapter.execute(captured.code, request.module.original_sha256);
    demand(typeof win.AnkiSlimDecode === 'function' && typeof win.AnkiSlimApkgHydrate === 'function', 'Native semantic API absent');
    win.AnkiSlimDecode(parsed);
    phase('native-defined-and-decoded');
    for (const [key, raw] of Object.entries(side.registry)) {
      demand(await adapter.matches(raw, key) === true, 'Registry native SHA verification failed');
      win.AnkiSlimAssets = win.AnkiSlimAssets || {};
      win.AnkiSlimAssets[key] = raw;
    }
    const payloads = Array.from(parsed.querySelectorAll('script.anki-final-reviewed-data'));
    demand(payloads.length === 1, 'Unsupported native payload census');
    for (const payload of payloads) {
      demand(!payload.hasAttribute('data-native-state'), 'Source native state is not pristine');
      for (const [src, sha] of [['asSrc', 'asSha'], ['asIndexSrc', 'asIndexSha']]) {
        if (payload.dataset[src]) {
          demand(Object.hasOwn(side.registry, payload.dataset[sha]), 'Native registry binding absent');
          await win.StudySlimWarm.load({ src: payload.dataset[src], sha256: payload.dataset[sha] });
        }
      }
      const raw = payload.dataset.asSha ? side.registry[payload.dataset.asSha] : payload.textContent;
      await win.AnkiReviewedChunkProjection.prepare(win.JSON.parse(raw));
      await win.AnkiSharedReadingBankRuntime.warm(win.AnkiFinalReadingMetadata,
        Array.from(parsed.querySelectorAll('.sf-en,.example-text'), node => node.textContent));
    }
    phase('semantic-inputs-verified');
    win.AnkiSlimApkgDispose();
    win.__ankiCardChunkState = null;
    copyAttributes(parsed.documentElement, doc.documentElement);
    copyAttributes(parsed.body, doc.body);
    // Snapshot before adopting! A mapper over the live source NodeList skips
    // adjacent children as adoption removes each prior child from that list.
    const headNodes = Array.from(parsed.head.childNodes), bodyNodes = Array.from(parsed.body.childNodes);
    doc.head.replaceChildren(...headNodes.map(node => doc.adoptNode(node)));
    doc.body.replaceChildren(...bodyNodes.map(node => doc.adoptNode(node)));
    assert.deepEqual(Array.from(doc.head.childNodes), headNodes);
    assert.deepEqual(Array.from(doc.body.childNodes), bodyNodes);
    assert.deepEqual(Array.from(doc.scripts), sourceScripts);
    parsed = null;
    const initialHistory = await prepareInitialHistory(doc, request, resource);
    const closedManifests = Array.from(doc.querySelectorAll('script.as-manifest'))
      .filter(node => node.closest('details') && !node.closest('details').open)
      .map(node => ({ node, owner: node.closest('details'), html: node.outerHTML }));
    const rows = Array.from(doc.querySelectorAll('.sf-sense>.sf-panel>.sf-example,.examples-section li.example-card'));
    const before = rows.map(node => ({ node, occurrence: node.getAttribute('data-sf-occurrence-id'),
      english: hash(node.querySelector('.sf-en,.example-text')?.textContent || ''),
      chinese: hash(node.querySelector('.sf-zh,.example-translation')?.textContent || '') }));
    const auditSelector = '.sf-ownership-history,.sf-ownership-authority,.sf-original-history-panel,.sf-inline-history,.sf-ownership-inline,.sf-reason,.sf-history-old-reason,[data-native-ownership-history]';
    const audits = Array.from(doc.querySelectorAll(auditSelector), node => ({ node, text: hash(node.textContent) }));
    await win.AnkiSlimApkgHydrate(); // no authored startup execution
    phase('native-semantic-hydrate-complete');
    assert.deepEqual(Array.from(doc.scripts), sourceScripts);
    for (const item of closedManifests) {
      demand(item.node.isConnected && item.node.ownerDocument === doc && item.node.closest('details') === item.owner
        && !item.owner.open && item.node.outerHTML === item.html, 'Closed history disclosure changed');
    }
    for (const payload of payloads) demand(payload.dataset.nativeState === 'ready', doc.querySelector('.anki-final-status')?.textContent || 'Native semantic preparation failed');
    assert.deepEqual(errors, []);
    assert.deepEqual(Array.from(captures.keys()), ['fine', 'projection', 'bank', 'group']);
    const handles = win.__ankiFinalApkgHandles;
    demand(Array.isArray(handles) && handles.length === 5, 'Native handle census differs');
    const stats = handles.map(handle => ({ stats: handle.stats?.() || null, diagnostics: handle.diagnostics?.() || null }));
    demand(Array.isArray(stats[1].stats?.errors) && stats[1].stats.errors.length === 0, 'Projection reported semantic errors');
    const projection = captures.get('projection')(), bank = captures.get('bank')(), group = captures.get('group')();
    const roles = new Map(), keys = new WeakMap();
    let nextKey = 0;
    function key(node) {
      if (!node) return null;
      demand(node.nodeType === 1 && node.ownerDocument === doc && node.isConnected, 'Detached/non-element binding');
      if (!keys.has(node)) keys.set(node, 'node-' + String(++nextKey).padStart(7, '0'));
      return keys.get(node);
    }
    function role(node, name) {
      if (!node) return;
      if (!roles.has(node)) roles.set(node, { key: key(node), roles: [] });
      const entry = roles.get(node);
      if (!entry.roles.includes(name)) entry.roles.push(name);
    }
    const panels = Array.from(doc.querySelectorAll('.sf-sense>.sf-panel'));
    for (const panel of panels) {
      role(panel, 'sense-panel');
      role(panel.querySelector('.sf-preview-count'), 'group-status');
      for (const row of panel.querySelectorAll(':scope>.sf-example')) role(row, 'sf-member');
    }
    for (const node of projection.wrappers) role(node, 'projection-keyboard-wrapper');
    for (const node of projection.comparisons) role(node, 'projection-comparison');
    for (const entry of group.groups) {
      role(entry.panel, 'group-panel');
      for (const member of entry.members) role(member, 'group-member');
    }
    for (const [label, entry] of bank.records) {
      role(label, 'bank-label');
      role(entry.container, 'bank-container');
    }
    let englishSame = 0, chineseSame = 0;
    for (const item of before) {
      demand(item.node.ownerDocument === doc && item.node.isConnected && item.node.getAttribute('data-sf-occurrence-id') === item.occurrence,
        'Original physical occurrence changed');
      englishSame += Number(hash(item.node.querySelector('.sf-en,.example-text')?.textContent || '') === item.english);
      chineseSame += Number(hash(item.node.querySelector('.sf-zh,.example-translation')?.textContent || '') === item.chinese);
    }
    demand(englishSame === rows.length && chineseSame === rows.length, 'Original bilingual sentence text changed');
    for (const item of audits) demand(item.node.ownerDocument === doc && item.node.isConnected && hash(item.node.textContent) === item.text, 'Original audit text changed');
    const nodeBindings = [];
    for (const [node, entry] of roles) {
      demand(!node.hasAttribute('data-study-compiled-key'), 'Source collides with compiled binding keys');
      nodeBindings.push({ key: entry.key, tag: node.tagName, namespace: node.namespaceURI,
        roles: entry.roles, attributes: attributes(node), text_sha256: hash(node.textContent) });
      node.setAttribute('data-study-compiled-key', entry.key);
    }
    const bindings = jsonFile(output, 'runtime-bindings-minimal-draft.json', {
      schema: 'study-canonical-interaction-bindings.draft.v1', source_artifact_sha256: request.artifact.sha256,
      nodeBindings, projectionWrappers: projection.wrappers.map(key), projectionComparisons: projection.comparisons.map(key),
      panels: panels.map(panel => ({ panelKey: key(panel), statusKey: key(panel.querySelector('.sf-preview-count')),
        memberKeys: Array.from(panel.querySelectorAll(':scope>.sf-example'), key) })),
      groups: group.groups.map(entry => ({ panelKey: key(entry.panel), memberKeys: entry.members.map(key) })),
      bankRecords: bank.records.map(([label, entry]) => ({ labelKey: key(label), containerKey: key(entry.container),
        createdAtBuild: entry.created, evidence: label.getAttribute('data-shared-reading-bank-evidence'), compiledAttributes: attributes(label) })),
      doesNotContainFineUndo: true,
    });
    const metadata = win.JSON.stringify(win.AnkiFinalReadingMetadata, null, 2) + '\n';
    demand(hash(metadata) === win.AnkiSharedReadingBankRuntime.sidecarSha256, 'Native metadata sidecar SHA differs');
    const metadataRecord = { path: 'source-bank-' + hash(metadata) + '.json', bytes: Buffer.byteLength(metadata), sha256: hash(metadata) };
    fs.writeFileSync(path.join(output, metadataRecord.path), metadata, { flag: 'wx' });
    const sourceProof = jsonFile(output, 'source-proof.json', {
      schema: 'study-compiled-semantic-source.v1', request_sha256: input.requestSha,
      artifact_sha256: request.artifact.sha256, helpers_sha256: request.helpers.sha256,
      source_wrapper_sha256: artifact.source_wrapper_sha256, source_payload_sha256: artifact.source_payload_sha256,
      raw_wrapper_and_payload_require_request_builder_authentication: true,
      raw_wrapper_and_payload_rehashed_here: false,
      source_side_sha256: side.proof.source_sha256, expanded_side_sha256: side.proof.expanded_sha256,
      source_side_utf8_bytes: side.proof.source_bytes, expanded_side_utf8_bytes: Buffer.byteLength(side.html),
      original_module_sha256: request.module.original_sha256, prepared_module_sha256: request.module.sha256,
      registry_pins: side.proof.registry_pins, metadata_sha256: hash(metadata),
      initial_history_evidence: initialHistory,
    });
    for (const item of scriptSnapshots) {
      demand(item.node.textContent === item.text, 'Source script text changed');
      if (item.type === null) item.node.removeAttribute('type');
      else item.node.setAttribute('type', item.type);
      if (item.node.classList.contains('anki-final-reviewed-data')) {
        demand(item.node.dataset.nativeState === 'ready', 'Native payload not ready before restoration');
        item.node.removeAttribute('data-native-state');
      }
      demand(item.node.outerHTML === item.html, 'Original source script DOM changed');
    }
    assert.deepEqual(Array.from(doc.scripts), sourceScripts);
    const reconciliation = jsonFile(output, 'reconciliation.json', {
      // SF and native examples may display one physical occurrence twice.
      // This DOM census is not a vocabulary-frequency total.
      schema: 'study-compiled-semantic-reconciliation.v1', original_rendered_rows: rows.length,
      sf_rows: rows.filter(node => node.matches('.sf-example')).length,
      native_rows: rows.filter(node => node.matches('li.example-card')).length,
      all_original_rows_same_live_nodes: true, original_english_same_count: englishSame, original_chinese_same_count: chineseSame,
      original_audit_nodes: audits.length, all_original_audit_nodes_connected_and_text_exact: true,
      audit_snapshot: 'after-exact-initial-history-expansion', initial_history_evidence: initialHistory.length,
      groups: group.groups.length, grouped_occurrences: group.groups.reduce((count, item) => count + item.members.length, 0),
      projection_wrappers: projection.wrappers.length, bank_records: bank.records.length, minimal_runtime_keys: nodeBindings.length,
      closed_history_manifests_preserved: closedManifests.length,
      source_node_adoption: { static_snapshot: true, head_nodes: headNodes.length, body_nodes: bodyNodes.length, all_nodes_identity_order_exact: true },
      source_scripts: { count: sourceScripts.length, actual_nodes_same_order: true, parser_script_dom_exact: true,
        native_module_references: nativeReferences, native_module_executions: 1,
        raw_lexeme_equality_not_claimed: true, authored_startup_executed: false, authored_order: authoredOrder,
        scripts: scriptSnapshots.map((item, index) => ({ index, dom_sha256: hash(item.html), code_sha256: hash(item.text) })) },
      native_stats: stats,
    });
    phase('reconciliation-complete');
    const { serializeToSink, createUtf8Sink } = await import(pathToFileURL(path.join(__dirname, 'stream-serializer.mjs')).href);
    const name = 'native-pure-document-keyed.html', partial = path.join(output, name + '.partial');
    const fd = fs.openSync(partial, 'wx+'), htmlHash = crypto.createHash('sha256');
    let bytes = 0, htmlDigest;
    try {
      const sink = createUtf8Sink(buffer => {
        const written = writeAll(fd, buffer);
        htmlHash.update(buffer); bytes += written;
      });
      serializeToSink(implForWrapper(doc), { treeAdapter: serializationAdapter, scriptingEnabled: true }, sink.write);
      sink.end();
      fs.fsyncSync(fd);
      htmlDigest = htmlHash.digest('hex');
      publishNoReplace(partial, path.join(output, name), fd, { bytes, sha256: htmlDigest });
    } finally { fs.closeSync(fd); }
    phase('html-written');
    const report = {
      schema: 'study-compiled-semantic-result.v1', final_html: { path: name, bytes, sha256: htmlDigest },
      bindings, source_proof: sourceProof, reconciliation, capture_inverse: inverse, metadata: metadataRecord,
      sources: Array.from(input.ledger.values()),
      pure_semantic_only: true, authored_startup_executed: false, real_native_ready: true,
      browser_or_speed_acceptance: false, no_full_before_snapshot_or_fine_undo: true,
      native_handles: handles.length, phases, elapsed_ms: Date.now() - started,
    };
    jsonFile(output, 'report.json', report); // success marker is written last
    return report;
  } catch (error) {
    jsonFile(output, 'failure.json', { schema: 'study-compiled-semantic-failure.v1', name: error.name, message: error.message,
      elapsed_ms: Date.now() - started, phases });
    throw error;
  } finally {
    try { win.AnkiSlimApkgDispose?.(); win.__ankiExamCountdownCleanup?.(); }
    finally { dom.window.close(); }
  }
}

module.exports = { CAPTURE_EDITS, validateArtifact, validateModule, createResourceResolver, instrument, nativeScriptReferences, loadRequest, writeAll, publishNoReplace, prepareInitialHistory, produce };
if (require.main === module) {
  if (process.argv.length !== 4) {
    process.stderr.write('Usage: node semantic-producer.cjs REQUEST.json NEW_OUTPUT_DIRECTORY\n');
    process.exitCode = 2;
  } else {
    produce(process.argv[2], process.argv[3]).then(result => {
      process.stdout.write(JSON.stringify({ schema: result.schema, final_html: result.final_html,
        bindings: result.bindings, elapsed_ms: result.elapsed_ms }) + '\n');
    }).catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
  }
}
