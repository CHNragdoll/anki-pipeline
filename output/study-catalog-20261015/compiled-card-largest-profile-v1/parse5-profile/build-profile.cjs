'use strict';
// Explicit opt-in entrypoint. No input is discovered and no producer is executed.
const fs = require('node:fs');
const path = require('node:path');
const api = require('./ast-profile.cjs');
const HASH = /^[a-f0-9]{64}$/;
const REQUEST_SCHEMA = 'study-parse5-profile-build-request.v1';
function descriptor(value, name) {
  if (!value || Object.keys(value).sort().join(',') !== 'path,sha256' ||
      !path.isAbsolute(value.path || '') || !HASH.test(value.sha256 || '')) {
    throw Error('Invalid pinned ' + name + ' descriptor');
  }
  return value;
}
function readRequest(requestPath) {
  if (!path.isAbsolute(requestPath) || fs.statSync(requestPath).size > 64 * 1024) {
    throw Error('Request must be an absolute, bounded JSON file');
  }
  const raw = fs.readFileSync(requestPath);
  const request = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw));
  if (request.schema !== REQUEST_SCHEMA ||
      Object.keys(request).sort().join(',') !== 'bindings,draft,html,schema') {
    throw Error('Unknown request schema/fields');
  }
  for (const name of ['html', 'draft', 'bindings']) descriptor(request[name], name);
  return {request, requestSha256: api.sha(raw)};
}
function build(requestPath, output) {
  const parent = fs.realpathSync(path.dirname(output));
  if (!path.isAbsolute(output) ||
      !(['/tmp', '/private/tmp'].some(root => parent === root || parent.startsWith(root + '/'))) ||
      fs.existsSync(output)) {
    throw Error('Output must be a new directory under /tmp');
  }
  const started = process.hrtime.bigint();
  const {request, requestSha256} = readRequest(requestPath);
  const html = api.readPinnedUTF8(request.html.path, request.html.sha256, api.LIMITS.htmlBytes);
  const draftRaw = api.readPinnedUTF8(request.draft.path, request.draft.sha256, api.LIMITS.draftBytes);
  const bindingRaw = api.readPinnedUTF8(request.bindings.path, request.bindings.sha256, 64 * 1024);
  const bindings = JSON.parse(bindingRaw);
  const result = api.makeSlotlessProfile({html, draft: JSON.parse(draftRaw), draftRaw, bindings});
  const report = {
    schema: 'study-parse5-profile-build-report.v1',
    requestSha256,
    inputs: request,
    limits: api.LIMITS,
    diagnostics: result.diagnostics,
    profileBytes: Buffer.byteLength(result.raw),
    profileSha256: api.sha(result.raw),
    parserVersion: require('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/node_modules/parse5/package.json').version,
    elapsedMs: Number(process.hrtime.bigint() - started) / 1e6,
    memory: {rssBytes: process.memoryUsage().rss, maxRSSKiB: process.resourceUsage().maxRSS},
    scope: 'AST only; no semantic producer, native runtime, browser, database, or package was executed.'
  };
  // No output directory exists until every input pin and semantic qualification passed.
  fs.mkdirSync(output);
  const files = {
    'profile.json': result.raw,
    'anchors.json': JSON.stringify(result.anchors),
    'diagnostics.json': JSON.stringify(report, null, 2) + '\n'
  };
  for (const [name, raw] of Object.entries(files)) fs.writeFileSync(path.join(output, name), raw, {flag: 'wx'});
  const manifest = {schema: 'study-parse5-profile-build-freeze.v1', files: Object.entries(files).map(([name, raw]) => ({name, bytes: Buffer.byteLength(raw), sha256: api.sha(raw)}))};
  fs.writeFileSync(path.join(output, 'FROZEN.json'), JSON.stringify(manifest, null, 2) + '\n', {flag: 'wx'});
  return report;
}
if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 4 || args[0] !== '--request' || args[2] !== '--output') {
      throw Error('Usage: node --max-old-space-size=1536 build-profile.cjs --request /tmp/request.json --output /tmp/new-output');
    }
    console.log(JSON.stringify(build(args[1], args[3])));
  } catch (error) {
    console.error(JSON.stringify({error: error.message, code: error.code || null, keyInsertions: error.keyInsertions || []}));
    process.exitCode = 1;
  }
}
module.exports = {REQUEST_SCHEMA, build, readRequest};
