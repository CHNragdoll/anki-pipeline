'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const api = require('./ast-profile.cjs');
const {build, REQUEST_SCHEMA} = require('./build-profile.cjs');
const HTML = '/tmp/study-canonical-replay-export-v2-20261017-zbjrug7d/36d114906f1f97c4c7d3bf7070a8b35ec213e037106f759edd395633e3d50ee3/replay-input-derived.html';
const DRAFT = '/tmp/study-canonical-small-producer-20261017-v1gfo3ot/full-authored-capture/runtime-bindings-minimal-draft.json';
const REFERENCE = '/tmp/study-compiled-card-binder-v2-20261017-gjmnnl5m/replay/abolish/profile.json';
function fixture() {
  const dir = fs.mkdtempSync('/tmp/study-ast-build-contract-');
  const reference = JSON.parse(fs.readFileSync(REFERENCE, 'utf8'));
  const bindings = path.join(dir, 'bindings.json');
  fs.writeFileSync(bindings, JSON.stringify(reference.bindings));
  const descriptor = file => ({path: file, sha256: api.sha(fs.readFileSync(file))});
  const request = {schema: REQUEST_SCHEMA, html: descriptor(HTML), draft: descriptor(DRAFT), bindings: descriptor(bindings)};
  return {dir, reference, request, requestPath: path.join(dir, 'request.json'), output: path.join(dir, 'output')};
}
test('bounded pinned CLI core emits the exact real slotless profile and matching external anchors', () => {
  const f = fixture();
  try {
    fs.writeFileSync(f.requestPath, JSON.stringify(f.request));
    const report = build(f.requestPath, f.output);
    const raw = fs.readFileSync(path.join(f.output, 'profile.json'), 'utf8');
    const anchors = JSON.parse(fs.readFileSync(path.join(f.output, 'anchors.json'), 'utf8'));
    assert.deepEqual(JSON.parse(raw), f.reference);
    assert.equal(anchors.profileSha256, api.sha(raw));
    assert.equal(anchors.htmlSha256, f.request.html.sha256);
    assert.equal(report.diagnostics.bindings, 15);
    const frozen = JSON.parse(fs.readFileSync(path.join(f.output, 'FROZEN.json'), 'utf8'));
    for (const entry of frozen.files) {
      const bytes = fs.readFileSync(path.join(f.output, entry.name));
      assert.equal(entry.bytes, bytes.length);
      assert.equal(entry.sha256, api.sha(bytes));
    }
    assert.throws(() => build(f.requestPath, f.output), /new directory/);
  } finally { fs.rmSync(f.dir, {recursive: true, force: true}); }
});
test('wrong input pin or unknown request field leaves no partial output', () => {
  const f = fixture();
  try {
    f.request.html.sha256 = '0'.repeat(64);
    fs.writeFileSync(f.requestPath, JSON.stringify(f.request));
    assert.throws(() => build(f.requestPath, f.output), /input SHA differs/);
    assert.equal(fs.existsSync(f.output), false);
    f.request.extra = true;
    fs.writeFileSync(f.requestPath, JSON.stringify(f.request));
    assert.throws(() => build(f.requestPath, f.output), /schema\/fields/);
    assert.equal(fs.existsSync(f.output), false);
  } finally { fs.rmSync(f.dir, {recursive: true, force: true}); }
});
