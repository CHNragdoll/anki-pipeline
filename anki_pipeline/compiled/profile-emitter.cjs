'use strict';

/** Shared v1 profile emission from one pinned semantic-producer result. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { pathToFileURL } = require('node:url');
const ast = require('./profile-ast.cjs');
const { writeAll, publishNoReplace } = require('./semantic-producer.cjs');

const REQUEST_SCHEMA = 'study-compiled-profile-request.v1';
const PROFILE_SCHEMA = 'study-compiled-card-interactions.v1';
const HASH = /^[a-f0-9]{64}$/;
const REQUIRED_BINDINGS = Object.freeze([
  'producerInputSha256', 'sourceArtifactSha256', 'derivedHTMLSha256', 'sourceWrapperSha256',
  'sourcePayloadSha256', 'sourceSideSha256', 'expandedSideSha256', 'materializerSha256',
  'frameRuntimeSha256', 'frameHTMLSha256', 'adapterSha256', 'nativeModuleSha256',
  'originalModuleSha256', 'rawSideSha256', 'rawIndexSha256', 'residualListenerSha256', 'readerDelegateSha256',
]);
const LIMITS = Object.freeze({ ...ast.LIMITS, htmlBytes: 128 * 1024 * 1024, requestBytes: 1024 * 1024, reportBytes: 16 * 1024 * 1024,
  headerBytes: 65536, metadataBytes: 8 * 1024 * 1024 });
function demand(value, message) { if (!value) throw Error('Compiled profile: ' + message); }
function object(value, name) {
  demand(value && typeof value === 'object' && !Array.isArray(value), 'invalid ' + name);
  return value;
}
function descriptor(value, name) {
  object(value, name);
  demand(typeof value.path === 'string' && path.isAbsolute(value.path) && !value.path.includes('\0') && HASH.test(value.sha256 || ''), 'invalid pinned ' + name);
  return value;
}
function read(value, limit, name) {
  descriptor(value, name);
  return ast.readPinnedUTF8(value.path, value.sha256, limit);
}
function childDescriptor(directory, value, name) {
  object(value, name);
  demand(typeof value.path === 'string' && value.path === path.basename(value.path) && value.path !== '.'
    && value.path !== '..' && !value.path.includes('\\') && !value.path.includes('\0')
    && HASH.test(value.sha256 || '') && Number.isSafeInteger(value.bytes) && value.bytes >= 0, 'invalid producer ' + name);
  return { ...value, path: path.join(directory, value.path) };
}
function readChild(directory, value, limit, name) {
  const child = childDescriptor(directory, value, name), raw = read(child, limit, name);
  demand(Buffer.byteLength(raw) === child.bytes, 'producer byte count differs: ' + name);
  return { descriptor: child, raw };
}
function validateBindings(bindings) {
  object(bindings, 'external bindings');
  demand(REQUIRED_BINDINGS.every(name => HASH.test(bindings[name] || ''))
    && Object.values(bindings).every(value => typeof value === 'string' && HASH.test(value)), 'external binding pins');
}

/** Apply only the original AST's explicit missing-logical-root key plan. */
function insertAnchorKeys(html, plans) {
  demand(typeof html === 'string' && Array.isArray(plans) && plans.length > 0, 'invalid anchor insertion plan');
  const sorted = plans.slice().sort((a, b) => a.insertOffset - b.insertOffset), keys = new Set();
  let previousEnd = -1;
  for (const item of sorted) {
    demand(item && /^anchor-\d{5,}$/.test(item.key || '') && !keys.has(item.key)
      && ['startTagStart', 'startTagEnd', 'insertOffset'].every(name => Number.isSafeInteger(item[name]))
      && item.startTagStart >= previousEnd && item.startTagStart >= 0 && item.startTagEnd <= html.length
      && item.startTagEnd > item.startTagStart, 'invalid or overlapping anchor plan');
    const tag = html.slice(item.startTagStart, item.startTagEnd);
    demand(tag.startsWith('<') && tag.endsWith('>') && ast.sha(tag) === item.startTagSha256
      && item.insertOffset === item.startTagEnd - (tag.endsWith('/>') ? 2 : 1)
      && item.insertText === ' data-study-compiled-key="' + item.key + '"'
      && !/\bdata-study-compiled-key\s*=/i.test(tag), 'anchor start-tag SHA/boundary differs');
    keys.add(item.key); previousEnd = item.startTagEnd;
  }
  const pieces = [];
  let at = 0;
  for (const item of sorted) { pieces.push(html.slice(at, item.insertOffset), item.insertText); at = item.insertOffset; }
  pieces.push(html.slice(at));
  const derived = pieces.join(''), inversePieces = [];
  let cursor = 0, added = 0;
  for (const item of sorted) {
    const offset = item.insertOffset + added;
    demand(derived.slice(offset, offset + item.insertText.length) === item.insertText, 'anchor inverse boundary differs');
    inversePieces.push(derived.slice(cursor, offset));
    cursor = offset + item.insertText.length; added += item.insertText.length;
  }
  inversePieces.push(derived.slice(cursor));
  const inverse = inversePieces.join('');
  demand(inverse === html, 'anchor insertion inverse differs');
  return { html: derived, inverse, insertions: sorted };
}

function validateHistoryInputs(history, manifests, initial = 0) {
  if (!history) { demand(manifests === 0 && initial === 0, 'manifest or initial evidence requires explicit history inputs'); return; }
  object(history, 'history inputs');
  demand(manifests > 0 || initial > 0, 'unused history capability');
  demand(Object.keys(history).length === 3 && Object.keys(history).every(name => ['parts', 'source_request', 'evidence'].includes(name)), 'history input fields');
  descriptor(history.source_request, 'history source request');
  object(history.parts, 'history parts'); object(history.evidence, 'history evidence');
  demand((manifests === 0 || Object.keys(history.parts).length > 0) && Object.keys(history.parts).length <= 1024, 'history part input limit');
  for (const [pin, value] of Object.entries(history.parts)) {
    demand(HASH.test(pin) && value.sha256 === pin, 'history part source pin'); descriptor(value, 'history part');
  }
  for (const [name, value] of Object.entries(history.evidence)) {
    demand(/^_af_[a-f0-9]{24}\.js$/.test(name), 'history evidence name'); descriptor(value, 'history evidence');
  }
}

function loadHistory(input, projected) {
  const history = input.request.history;
  const initial = projected.index.initialEvidence;
  const initialProof = input.sourceProof.initial_history_evidence || [];
  demand(Array.isArray(initialProof) && initialProof.length === initial.length, 'initial history source proof census differs');
  validateHistoryInputs(history, projected.index.manifests.length, initial.length);
  if (!history) return null;
  demand(history.source_request.sha256 === input.sourceProof.request_sha256, 'history source request binding differs');
  const original = JSON.parse(read(history.source_request, LIMITS.requestBytes, 'history source request'));
  demand(original.schema === 'study-compiled-semantic-request.v1' && original.artifact.sha256 === input.bindings.sourceArtifactSha256,
    'history source artifact binding differs');
  const { validateArtifact } = require('./semantic-producer.cjs');
  const artifact = JSON.parse(read(original.artifact, ast.LIMITS.htmlBytes * 2, 'history source artifact'));
  validateArtifact(artifact, original.source, original.module);
  demand(original.module.sha256 === input.bindings.nativeModuleSha256 && original.module.original_sha256 === input.bindings.originalModuleSha256,
    'history native module binding differs');
  for (const pin of [input.bindings.rawSideSha256, input.bindings.rawIndexSha256])
    demand(Object.hasOwn(artifact.sides[1].registry, pin), 'history raw/index registry absent');
  const moduleCode = read(original.module, LIMITS.metadataBytes, 'history native module');
  const parts = {}, evidence = {};
  let bytes = 0;
  for (const [pin, value] of Object.entries(history.parts)) {
    const raw = read(value, ast.LIMITS.htmlBytes, 'history part'); bytes += Buffer.byteLength(raw);
    demand(bytes <= LIMITS.exactTextBytes, 'history input byte limit'); parts[pin] = raw;
  }
  for (const [name, value] of Object.entries(history.evidence)) {
    const raw = read(value, ast.LIMITS.htmlBytes, 'history evidence'); bytes += Buffer.byteLength(raw);
    demand(bytes <= LIMITS.exactTextBytes, 'history input byte limit'); evidence[name] = { raw, sha256: value.sha256 };
  }
  const initialResources = {};
  for (const pre of initial) {
    const name = ast.get(pre, 'data-native-history-media');
    demand(typeof original.base_url === 'string', 'initial history base URL absent');
    const resource = original.resources?.[new URL(name, original.base_url).href];
    demand(resource && resource.sha256 === evidence[name]?.sha256, 'initial history source capability absent/differs');
    initialResources[name] = resource.sha256;
  }
  return ast.buildHistorySlots({ index: projected.index, sourceArtifactSha256: input.bindings.sourceArtifactSha256,
    moduleCode, module: original.module, parts, evidence, initialProof, initialResources,
    nodeBindings: projected.fields.nodeBindings, limits: LIMITS });
}

function validateSourceHeader(input, bindings) {
  validateBindings(bindings);
  const proof = input.sourceProof;
  demand(proof.schema === 'study-compiled-semantic-source.v1', 'semantic source proof schema');
  const names = [
    ['artifact_sha256', 'sourceArtifactSha256'], ['source_wrapper_sha256', 'sourceWrapperSha256'],
    ['source_payload_sha256', 'sourcePayloadSha256'], ['source_side_sha256', 'sourceSideSha256'],
    ['expanded_side_sha256', 'expandedSideSha256'], ['helpers_sha256', 'adapterSha256'],
    ['prepared_module_sha256', 'nativeModuleSha256'], ['original_module_sha256', 'originalModuleSha256'],
  ];
  for (const [source, binding] of names) demand(proof[source] === bindings[binding], 'source/header binding differs: ' + binding);
  demand(bindings.derivedHTMLSha256 === input.report.final_html.sha256
    && bindings.producerInputSha256 === input.report.bindings.sha256
    && input.draft.source_artifact_sha256 === bindings.sourceArtifactSha256, 'delivery/draft/source SHA differs');
  demand(Array.isArray(proof.registry_pins) && proof.registry_pins.includes(bindings.rawSideSha256)
    && proof.registry_pins.includes(bindings.rawIndexSha256), 'native registry binding absent');
  demand(input.report.metadata.sha256 === proof.metadata_sha256, 'metadata source binding differs');
}

function loadInputs(requestFile) {
  const requestPath = path.resolve(requestFile);
  const fd = fs.openSync(requestPath, 'r');
  let requestBytes;
  try {
    const stat = fs.fstatSync(fd);
    demand(stat.isFile() && stat.size <= LIMITS.requestBytes, 'request byte limit');
    const buffer = Buffer.allocUnsafe(stat.size + 1);
    let at = 0;
    while (at < buffer.length) {
      const count = fs.readSync(fd, buffer, at, buffer.length - at, at);
      if (count === 0) break;
      at += count;
    }
    demand(at <= stat.size && at <= LIMITS.requestBytes, 'request grew beyond byte limit');
    requestBytes = buffer.subarray(0, at);
  } finally { fs.closeSync(fd); }
  const request = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(requestBytes));
  object(request, 'request');
  demand(request.schema === REQUEST_SCHEMA && Object.keys(request).every(name => ['schema', 'producer_report', 'bindings', 'history'].includes(name)), 'request schema/fields');
  const reportRaw = read(request.producer_report, LIMITS.reportBytes, 'producer report');
  const report = JSON.parse(reportRaw), directory = path.dirname(request.producer_report.path);
  demand(report.schema === 'study-compiled-semantic-result.v1' && report.real_native_ready === true
    && report.pure_semantic_only === true && report.authored_startup_executed === false, 'producer result is not a completed semantic source');
  const html = readChild(directory, report.final_html, LIMITS.htmlBytes, 'HTML');
  const draft = readChild(directory, report.bindings, LIMITS.draftBytes, 'draft');
  const sourceProof = readChild(directory, report.source_proof, LIMITS.reportBytes, 'source proof');
  const metadata = readChild(directory, report.metadata, LIMITS.metadataBytes, 'metadata');
  const bindingsRaw = read(request.bindings, LIMITS.headerBytes, 'bindings header');
  const value = { request, requestPath, requestSha256: ast.sha(requestBytes), report, directory,
    html: html.raw, draft: JSON.parse(draft.raw), draftRaw: draft.raw,
    sourceProof: JSON.parse(sourceProof.raw), metadataRaw: metadata.raw, metadata: JSON.parse(metadata.raw),
    bindings: JSON.parse(bindingsRaw) };
  validateSourceHeader(value, value.bindings);
  return value;
}

function* objectJSON(value) {
  yield '{'; let comma = false;
  for (const [name, entry] of Object.entries(value)) {
    if (comma) yield ','; comma = true;
    yield JSON.stringify(name) + ':';
    if (Array.isArray(entry)) {
      yield '[';
      for (let n = 0; n < entry.length; n++) { if (n) yield ','; yield JSON.stringify(entry[n]); }
      yield ']';
    } else yield JSON.stringify(entry);
  }
  yield '}';
}
function openOutput(directory, name, limit) {
  const partial = path.join(directory, name + '.partial'), final = path.join(directory, name);
  const fd = fs.openSync(partial, 'wx+'), digest = crypto.createHash('sha256');
  let bytes = 0, published = false, closed = false;
  return {
    fd,
    write(buffer) {
      demand(!closed && !published && Buffer.isBuffer(buffer), 'output writer state');
      demand(buffer.length <= limit - bytes, 'output byte limit: ' + name);
      bytes += writeAll(fd, buffer); digest.update(buffer);
    },
    publish() {
      demand(!closed && !published, 'output publication state');
      fs.fsyncSync(fd);
      const record = { path: name, bytes, sha256: digest.digest('hex') };
      publishNoReplace(partial, final, fd, record); published = true;
      return record;
    },
    close() { if (!closed) { closed = true; fs.closeSync(fd); } },
  };
}
function writeStrings(writer, chunks, createUtf8Sink) {
  const sink = createUtf8Sink(buffer => writer.write(buffer));
  for (const chunk of chunks) sink.write(chunk);
  sink.end();
}
function writeJSON(directory, name, value, limit, createUtf8Sink) {
  const writer = openOutput(directory, name, limit);
  try { writeStrings(writer, objectJSON(value), createUtf8Sink); return writer.publish(); }
  finally { writer.close(); }
}

async function emitProfile(requestFile, outputDirectory) {
  const started = Date.now(), output = path.resolve(outputDirectory);
  demand(!fs.existsSync(output), 'output must use a new directory');
  const input = loadInputs(requestFile);
  let html = input.html, projected, insertions = [];
  try { projected = ast.projectFields({ html, draft: input.draft, limits: LIMITS }); }
  catch (error) {
    if (error.code !== 'NEEDS_DELIVERY_ANCHOR_KEYS') throw error;
    const inserted = insertAnchorKeys(html, error.keyInsertions);
    html = inserted.html; insertions = inserted.insertions;
    demand(Buffer.byteLength(html) <= LIMITS.htmlBytes, 'anchored HTML byte limit');
    projected = ast.projectFields({ html, draft: input.draft, limits: LIMITS });
  }
  const bindings = { ...input.bindings, derivedHTMLSha256: ast.sha(html) };
  const payloads = projected.index.payloads;
  demand(payloads.length === 1 && ast.get(payloads[0], 'data-as-sha') === bindings.rawSideSha256
    && ast.get(payloads[0], 'data-as-index-sha') === bindings.rawIndexSha256, 'raw/index payload pins differ');
  const fields = projected.fields;
  const history = loadHistory(input, projected);
  if (history) {
    fields.historySlots = history.slots;
    const historyBindings = {
      historyScopeEvidenceSha256: ast.sha(JSON.stringify(history.scope)),
      historyProducerSourceSha256: ast.sha(fs.readFileSync(require.resolve('./profile-ast.cjs'))),
    };
    for (const [name, pin] of Object.entries(historyBindings)) {
      if (Object.hasOwn(bindings, name)) demand(bindings[name] === pin, 'history provenance binding differs: ' + name);
      else bindings[name] = pin;
    }
  }
  const { createUtf8Sink } = await import(pathToFileURL(path.join(__dirname, 'stream-serializer.mjs')).href);
  fs.mkdirSync(output);
  const writers = [];
  try {
    const htmlWriter = openOutput(output, 'delivery.html', LIMITS.htmlBytes); writers.push(htmlWriter);
    writeStrings(htmlWriter, [html], createUtf8Sink);
    const delivery = htmlWriter.publish();
    demand(delivery.sha256 === bindings.derivedHTMLSha256, 'written delivery SHA differs');
    const fieldWriter = openOutput(output, 'fields.json', LIMITS.profileBytes); writers.push(fieldWriter);
    writeStrings(fieldWriter, objectJSON(fields), createUtf8Sink);
    const fieldRecord = fieldWriter.publish();
    const profileWriter = openOutput(output, 'profile.json', LIMITS.profileBytes); writers.push(profileWriter);
    const header = { schema: PROFILE_SCHEMA, version: 1, filter_mode: 'host-after-authored-filter', bindings };
    writeStrings(profileWriter, [JSON.stringify(header).slice(0, -1) + ','], createUtf8Sink);
    const first = Buffer.alloc(1), last = Buffer.alloc(1);
    demand(fs.readSync(fieldWriter.fd, first, 0, 1, 0) === 1
      && fs.readSync(fieldWriter.fd, last, 0, 1, fieldRecord.bytes - 1) === 1
      && first[0] === 123 && last[0] === 125, 'fields object boundary differs');
    const copied = crypto.createHash('sha256').update(first), buffer = Buffer.allocUnsafe(65536);
    let position = 1;
    while (position < fieldRecord.bytes - 1) {
      const count = fs.readSync(fieldWriter.fd, buffer, 0, Math.min(buffer.length, fieldRecord.bytes - 1 - position), position);
      demand(count > 0, 'copied fields read incomplete');
      const bytes = buffer.subarray(0, count); copied.update(bytes); profileWriter.write(bytes); position += count;
    }
    copied.update(last);
    demand(copied.digest('hex') === fieldRecord.sha256, 'copied fields SHA differs');
    profileWriter.write(Buffer.from('}'));
    const profile = profileWriter.publish();
    const anchors = writeJSON(output, 'anchors.json', { schema: PROFILE_SCHEMA, version: 1,
      profileSha256: profile.sha256, htmlSha256: delivery.sha256, bindings }, LIMITS.headerBytes * 2, createUtf8Sink);
    const scope = history ? writeJSON(output, 'history-scope.json', history.scope, LIMITS.reportBytes, createUtf8Sink) : null;
    if (scope) demand(scope.sha256 === bindings.historyScopeEvidenceSha256, 'written history scope SHA differs');
    const report = { schema: 'study-compiled-profile-result.v1', profile, anchors, delivery_html: delivery, fields: fieldRecord,
      producer_report_sha256: input.request.producer_report.sha256, request_sha256: input.requestSha256,
      metadata_sha256: input.report.metadata.sha256, external_bindings: bindings,
      anchor_inverse: { count: insertions.length, insertions, original_html_sha256: input.report.final_html.sha256,
        derived_html_sha256: delivery.sha256, inverse_sha256: input.report.final_html.sha256, inverse_exact: true },
      copied_fields_sha256: fieldRecord.sha256, copied_fields_exact: true, diagnostics: projected.diagnostics,
      history_scope: scope, history: history?.diagnostics || { slots: 0, parts: 0, initial: 0, evidence: 0 },
      browser_or_speed_acceptance: false, product_enabled: false, elapsed_ms: Date.now() - started };
    writeJSON(output, 'report.json', report, LIMITS.reportBytes, createUtf8Sink);
    return report;
  } finally { for (const writer of writers.reverse()) writer.close(); }
}

module.exports = { REQUEST_SCHEMA, REQUIRED_BINDINGS, LIMITS, insertAnchorKeys, validateHistoryInputs, validateBindings, loadInputs, emitProfile };
if (require.main === module) {
  if (process.argv.length !== 4) { process.stderr.write('Usage: node profile-emitter.cjs REQUEST.json NEW_OUTPUT_DIRECTORY\n'); process.exitCode = 2; }
  else emitProfile(process.argv[2], process.argv[3]).then(report => process.stdout.write(JSON.stringify({
    schema: report.schema, profile: report.profile, anchors: report.anchors,
    delivery_html: report.delivery_html, history: report.history, elapsed_ms: report.elapsed_ms,
  }) + '\n'))
    .catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
}
