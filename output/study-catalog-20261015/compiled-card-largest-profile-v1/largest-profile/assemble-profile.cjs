'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {sha} = require('/tmp/study-parse5-compiled-profile-20261017-jfnwtv1v/ast-profile.cjs');
const HASH = /^[a-f0-9]{64}$/;
const REQUIRED = ['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'];
async function fileSha(file) {
  const hash = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}
async function assemble({fieldsFile, fieldsSha256, bindings, extraction}, output) {
  if (fs.existsSync(output) || !path.isAbsolute(output)) throw Error('Output must be new and absolute');
  const parent = fs.realpathSync(path.dirname(output));
  if (!['/tmp','/private/tmp'].some(root => parent === root || parent.startsWith(root + '/'))) throw Error('Output must be under /tmp');
  if (!HASH.test(fieldsSha256 || '') || !bindings || REQUIRED.some(k => !HASH.test(bindings[k] || '')) || Object.values(bindings).some(pin => !HASH.test(pin || ''))) throw Error('Missing exact external binding pin');
  if (extraction.status !== 'FIELDS_EXTRACTED_NOT_PROFILE' || extraction.fields.sha256 !== fieldsSha256 ||
      extraction.inputs.html.sha256 !== bindings.derivedHTMLSha256 || extraction.inputs.draft.sha256 !== bindings.producerInputSha256 ||
      extraction.draftSourceArtifactSha256 !== bindings.sourceArtifactSha256 || extraction.diagnostics.manifests !== 0 ||
      extraction.payloads.length !== 1 || extraction.payloads[0].rawSideSha256 !== bindings.rawSideSha256 || extraction.payloads[0].rawIndexSha256 !== bindings.rawIndexSha256) throw Error('Extraction/delivery/header identity differs');
  const size = fs.statSync(fieldsFile).size;
  if (size !== extraction.fields.bytes || size < 2 || size > 256*1024*1024 || await fileSha(fieldsFile) !== fieldsSha256) throw Error('Fields byte pin differs');
  const input = fs.openSync(fieldsFile, 'r');
  try {
    const first = Buffer.alloc(1), last = Buffer.alloc(1);
    fs.readSync(input, first, 0, 1, 0); fs.readSync(input, last, 0, 1, size - 1);
    if (first[0] !== 123 || last[0] !== 125) throw Error('Expected exact object stream');
  } finally { fs.closeSync(input); }
  fs.mkdirSync(output);
  const fd = fs.openSync(path.join(output, 'profile.json'), 'wx');
  const hash = crypto.createHash('sha256');
  let bytes = 0;
  function write(value) { const buffer=Buffer.isBuffer(value)?value:Buffer.from(value); let offset=0; while(offset<buffer.length){const n=fs.writeSync(fd,buffer,offset,buffer.length-offset);if(n<=0)throw Error('Short output write');offset+=n;} bytes+=buffer.length;hash.update(buffer); }
  try {
    write(JSON.stringify({schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',bindings}).slice(0,-1) + ',');
    for await (const chunk of fs.createReadStream(fieldsFile, {start:1,end:size-2})) write(chunk);
    write('}');
  } finally { fs.closeSync(fd); }
  const profileSha256 = hash.digest('hex');
  const anchors = {schema:'study-compiled-card-interactions.v1',version:1,profileSha256,htmlSha256:bindings.derivedHTMLSha256,bindings};
  fs.writeFileSync(path.join(output, 'anchors.json'), JSON.stringify(anchors), {flag:'wx'});
  const report = {schema:'study-compiled-stream-profile-report.v1',profileBytes:bytes,profileSha256,fieldsSha256,htmlSha256:bindings.derivedHTMLSha256,externalPins:bindings,qaAssetLimitBytes:64*1024*1024,qaAssetWithinExistingLimit:bytes<=64*1024*1024,exactTextBytes:extraction.diagnostics.exactTextBytes,tables:extraction.tables,scope:'Profile byte assembly only; no HTML parsing, DOM, semantic replay, runtime, browser, deployment or gate change.'};
  fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report,null,2)+'\n', {flag:'wx'});
  return report;
}
module.exports = {assemble, fileSha, REQUIRED};
