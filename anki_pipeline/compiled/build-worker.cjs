'use strict';

/**
 * Sequential JSONL transport for the existing, unchanged shared builders.
 * Usage: node [--max-old-space-size=4096] [--expose-gc] build-worker.cjs
 * stdin: {id,operation:'semantic'|'profile',request:absolutePath,output:newAbsolutePath}
 * stdout contains one bounded response per command; full reports stay on disk.
 * EOF drains the current command and exits. No child process or network is used.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { TextDecoder } = require('node:util');
const { produce } = require('./semantic-producer.cjs');
const { emitProfile } = require('./profile-emitter.cjs');

const LIMITS = Object.freeze({ lineBytes: 16384, idCharacters: 128, pathBytes: 4096,
  reportBytes: 16 * 1024 * 1024, errorCharacters: 512, idleGcHeapBytes: 512 * 1024 * 1024 });
const OPERATIONS = Object.freeze({
  semantic: { build: produce, schema: 'study-compiled-semantic-result.v1' },
  profile: { build: emitProfile, schema: 'study-compiled-profile-result.v1' },
});
const utf8 = new TextDecoder('utf-8', { fatal: true });

function demand(value, message) { if (!value) throw new TypeError('Build worker: ' + message); }
function validId(value) {
  return typeof value === 'string' && value.length <= LIMITS.idCharacters
    && /^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value);
}
function localPath(value, name) {
  demand(typeof value === 'string' && Buffer.byteLength(value) <= LIMITS.pathBytes
    && !/[\x00-\x1f\x7f\\]/.test(value) && Buffer.from(value).toString('utf8') === value
    && path.isAbsolute(value) && path.resolve(value) === value, 'invalid absolute ' + name + ' path');
  return value;
}
function absent(filename) {
  try { fs.lstatSync(filename); return false; }
  catch (error) { if (error.code === 'ENOENT') return true; throw error; }
}
function validateCommand(command) {
  demand(command && typeof command === 'object' && !Array.isArray(command), 'command must be an object');
  const keys = Object.keys(command);
  demand(keys.length === 4 && keys.every(key => ['id', 'operation', 'request', 'output'].includes(key)), 'command fields');
  demand(validId(command.id), 'invalid command id');
  demand(typeof command.operation === 'string' && Object.hasOwn(OPERATIONS, command.operation), 'unknown operation');
  localPath(command.request, 'request'); localPath(command.output, 'output');
  demand(command.request !== command.output, 'request and output paths must differ');
  demand(fs.lstatSync(command.request).isFile(), 'request must be a regular file');
  demand(absent(command.output), 'output must use a new directory');
  return command;
}

/** Keep at most one bounded line, including when a client never sends a newline. */
async function* commandLines(input) {
  let pieces = [], bytes = 0, oversized = false;
  function append(part) {
    if (oversized || part.length === 0) return;
    if (bytes + part.length > LIMITS.lineBytes) { pieces = []; bytes = 0; oversized = true; }
    else { pieces.push(part); bytes += part.length; }
  }
  function take() {
    const value = oversized ? null : Buffer.concat(pieces, bytes);
    pieces = []; bytes = 0; oversized = false;
    return value;
  }
  for await (const chunk of input) {
    const raw = typeof chunk === 'string' ? Buffer.from(chunk) : chunk;
    demand(Buffer.isBuffer(raw), 'input transport must provide bytes');
    let at = 0, newline;
    while ((newline = raw.indexOf(10, at)) !== -1) {
      append(raw.subarray(at, newline));
      yield take();
      at = newline + 1;
    }
    append(raw.subarray(at));
  }
  if (bytes || oversized) yield take();
}

function boundedError(error) {
  const name = typeof error?.name === 'string' ? error.name : 'Error';
  const message = typeof error?.message === 'string' ? error.message : 'Unknown build failure';
  return { name: name.replace(/[\x00-\x1f\x7f]/g, ' ').slice(0, 64),
    message: message.slice(0, LIMITS.errorCharacters) };
}
function reportDescriptor(output, expectedSchema) {
  const filename = path.join(output, 'report.json'), fd = fs.openSync(filename, 'r');
  try {
    const before = fs.fstatSync(fd);
    demand(before.isFile() && before.size > 0 && before.size <= LIMITS.reportBytes, 'report file/byte limit');
    const buffer = Buffer.allocUnsafe(before.size + 1);
    let at = 0;
    while (at < buffer.length) {
      const count = fs.readSync(fd, buffer, at, buffer.length - at, at);
      if (count === 0) break;
      at += count;
    }
    const after = fs.fstatSync(fd);
    demand(at === before.size && before.dev === after.dev && before.ino === after.ino
      && before.size === after.size && before.mtimeMs === after.mtimeMs
      && before.ctimeMs === after.ctimeMs, 'report changed while reading');
    const raw = buffer.subarray(0, at), report = JSON.parse(utf8.decode(raw));
    demand(report?.schema === expectedSchema, 'completed report schema differs');
    return { path: filename, sha256: crypto.createHash('sha256').update(raw).digest('hex'), bytes: raw.length };
  } finally { fs.closeSync(fd); }
}
async function respond(output, response) {
  const line = JSON.stringify(response) + '\n';
  await new Promise((resolve, reject) => output.write(line, error => error ? reject(error) : resolve()));
}
function collectIdleGarbage() {
  if (typeof global.gc === 'function' && process.memoryUsage().heapUsed > LIMITS.idleGcHeapBytes) {
    // Called only after the completed response, with no builder in flight.
    try { global.gc(); }
    catch (error) { process.stderr.write('Build worker: optional idle GC failed: ' + boundedError(error).message + '\n'); }
  }
}
async function runWorker(input = process.stdin, output = process.stdout) {
  for await (const line of commandLines(input)) {
    let id = null, response;
    try {
      demand(line !== null, 'command line byte limit');
      const command = JSON.parse(utf8.decode(line));
      if (validId(command?.id)) id = command.id;
      validateCommand(command);
      const operation = OPERATIONS[command.operation];
      const result = await operation.build(command.request, command.output);
      demand(result?.schema === operation.schema, 'builder did not return a completed result');
      response = { id, ok: true, report: reportDescriptor(command.output, operation.schema) };
    } catch (error) { response = { id, ok: false, error: boundedError(error) }; }
    // A transport failure escapes the loop, never becoming a second command response.
    await respond(output, response);
    collectIdleGarbage();
  }
}

module.exports = { LIMITS, validateCommand, runWorker };
if (require.main === module) {
  if (process.argv.length !== 2) {
    process.stderr.write('Usage: node build-worker.cjs < commands.jsonl\n');
    process.exitCode = 2;
  } else runWorker().catch(error => {
    process.stderr.write('Build worker transport failed: ' + boundedError(error).message + '\n');
    process.exitCode = 1;
  });
}
