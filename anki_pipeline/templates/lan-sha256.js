/* SHA-256 digest fallback for the source reader on an HTTP LAN origin.
 * Install before reader scripts. This supplies only a missing native digest;
 * it does not make the origin secure or implement any other crypto operation.
 */
(function (root) {
  'use strict';

  const existing = root.crypto && root.crypto.subtle;
  if (existing && typeof existing.digest === 'function' &&
      (existing.digest.__ankiStudyAsyncSha256 ||
       Object.prototype.toString.call(existing) === '[object SubtleCrypto]')) return;

  // FIPS 180-4, section 4.2.2: the first 32 bits of the fractional parts of
  // the cube roots of the first 64 primes.
  const ROUND_CONSTANTS = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const rotateRight = (word, count) => (word >>> count) | (word << (32 - count));
  const arrayBufferByteLength = Object.getOwnPropertyDescriptor(
    ArrayBuffer.prototype, 'byteLength').get;

  function copyBufferSource(data) {
    let bytes;
    if (ArrayBuffer.isView(data)) {
      // Brand-check the backing buffer, rejecting SharedArrayBuffer just as
      // Web Crypto's BufferSource does. Views use byte offsets, not elements.
      arrayBufferByteLength.call(data.buffer);
      bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    } else {
      // This accepts real ArrayBuffers from other realms, without accepting
      // an object that merely claims to be an ArrayBuffer.
      arrayBufferByteLength.call(data);
      bytes = new Uint8Array(data);
    }
    return new Uint8Array(bytes);
  }

  function sha256(bytes) {
    const state = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ]);
    const schedule = new Uint32Array(64);

    function compress(block, offset) {
      for (let index = 0; index < 16; index++) {
        const start = offset + index * 4;
        schedule[index] = ((block[start] << 24) | (block[start + 1] << 16) |
          (block[start + 2] << 8) | block[start + 3]) >>> 0;
      }
      for (let index = 16; index < 64; index++) {
        const previous = schedule[index - 15];
        const recent = schedule[index - 2];
        const sigma0 = rotateRight(previous, 7) ^ rotateRight(previous, 18) ^ (previous >>> 3);
        const sigma1 = rotateRight(recent, 17) ^ rotateRight(recent, 19) ^ (recent >>> 10);
        schedule[index] = (schedule[index - 16] + sigma0 +
          schedule[index - 7] + sigma1) >>> 0;
      }
      let [a, b, c, d, e, f, g, h] = state;
      for (let index = 0; index < 64; index++) {
        const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
        const choice = (e & f) ^ (~e & g);
        const first = (h + sum1 + choice + ROUND_CONSTANTS[index] + schedule[index]) >>> 0;
        const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (sum0 + majority) >>> 0;
        h = g; g = f; f = e; e = (d + first) >>> 0;
        d = c; c = b; b = a; a = (first + second) >>> 0;
      }
      const words = [a, b, c, d, e, f, g, h];
      for (let index = 0; index < 8; index++) {
        state[index] = (state[index] + words[index]) >>> 0;
      }
    }

    const completeLength = bytes.byteLength - (bytes.byteLength % 64);
    for (let offset = 0; offset < completeLength; offset += 64) compress(bytes, offset);
    const remaining = bytes.byteLength - completeLength;
    const tail = new Uint8Array(remaining < 56 ? 64 : 128);
    tail.set(bytes.subarray(completeLength));
    tail[remaining] = 0x80;
    const length = new DataView(tail.buffer);
    // Encode the 64-bit bit length as two big-endian 32-bit words, avoiding
    // truncation when an input contains 2^29 or more bytes.
    length.setUint32(tail.byteLength - 8, Math.floor(bytes.byteLength / 0x20000000), false);
    length.setUint32(tail.byteLength - 4, (bytes.byteLength * 8) >>> 0, false);
    compress(tail, 0);
    if (tail.byteLength === 128) compress(tail, 64);

    const result = new ArrayBuffer(32);
    const output = new DataView(result);
    for (let index = 0; index < 8; index++) output.setUint32(index * 4, state[index], false);
    return result;
  }

  // Equivalent core shared by worker and local recovery: inline rotations
  // and scalar state avoid per-block arrays/function calls.
  function fastSha256(bytes) {
    const state = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ]);
    const schedule = new Uint32Array(64);

    function compress(block, offset) {
      for (let index = 0; index < 16; index++) {
        const start = offset + index * 4;
        schedule[index] = ((block[start] << 24) | (block[start + 1] << 16) |
          (block[start + 2] << 8) | block[start + 3]) >>> 0;
      }
      for (let index = 16; index < 64; index++) {
        const previous = schedule[index - 15];
        const recent = schedule[index - 2];
        const sigma0 = ((previous >>> 7) | (previous << 25)) ^ ((previous >>> 18) | (previous << 14)) ^ (previous >>> 3);
        const sigma1 = ((recent >>> 17) | (recent << 15)) ^ ((recent >>> 19) | (recent << 13)) ^ (recent >>> 10);
        schedule[index] = (schedule[index - 16] + sigma0 +
          schedule[index - 7] + sigma1) >>> 0;
      }
      let a = state[0], b = state[1], c = state[2], d = state[3];
      let e = state[4], f = state[5], g = state[6], h = state[7];
      for (let index = 0; index < 64; index++) {
        const sum1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const choice = (e & f) ^ (~e & g);
        const first = (h + sum1 + choice + ROUND_CONSTANTS[index] + schedule[index]) >>> 0;
        const sum0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const majority = (a & b) ^ (a & c) ^ (b & c);
        const second = (sum0 + majority) >>> 0;
        h = g; g = f; f = e; e = (d + first) >>> 0;
        d = c; c = b; b = a; a = (first + second) >>> 0;
      }
      state[0] = (state[0] + a) >>> 0;
      state[1] = (state[1] + b) >>> 0;
      state[2] = (state[2] + c) >>> 0;
      state[3] = (state[3] + d) >>> 0;
      state[4] = (state[4] + e) >>> 0;
      state[5] = (state[5] + f) >>> 0;
      state[6] = (state[6] + g) >>> 0;
      state[7] = (state[7] + h) >>> 0;
    }

    const completeLength = bytes.byteLength - (bytes.byteLength % 64);
    for (let offset = 0; offset < completeLength; offset += 64) compress(bytes, offset);
    const remaining = bytes.byteLength - completeLength;
    const tail = new Uint8Array(remaining < 56 ? 64 : 128);
    tail.set(bytes.subarray(completeLength));
    tail[remaining] = 0x80;
    const length = new DataView(tail.buffer);
    // Encode the 64-bit bit length as two big-endian 32-bit words, avoiding
    // truncation when an input contains 2^29 or more bytes.
    length.setUint32(tail.byteLength - 8, Math.floor(bytes.byteLength / 0x20000000), false);
    length.setUint32(tail.byteLength - 4, (bytes.byteLength * 8) >>> 0, false);
    compress(tail, 0);
    if (tail.byteLength === 128) compress(tail, 64);

    const result = new ArrayBuffer(32);
    const output = new DataView(result);
    for (let index = 0; index < 8; index++) output.setUint32(index * 4, state[index], false);
    return result;
  }

  // Keep large HTTP-origin hashes off the rendering thread. Only internal
  // copies are transferred; a second, bounded snapshot permits exact recovery
  // if a worker cannot start, crashes, or returns an invalid response.
  const WORKER_THRESHOLD = 256 * 1024;
  const MAX_WORKERS = 2, MAX_JOBS = 8, MAX_PENDING_BYTES = 64 * 1024 * 1024;
  const WORKER_TIMEOUT = 10000;
  const slots = [], queue = [];
  let nextId = 0, pendingBytes = 0, pendingJobs = 0;
  let workerURL = null, workersDisabled = false;

  function localDigest(bytes) {
    return Promise.resolve().then(() => fastSha256(bytes));
  }

  function workerSource() {
    return "'use strict';const ROUND_CONSTANTS=new Uint32Array(" +
      JSON.stringify(Array.from(ROUND_CONSTANTS)) + ');const rotateRight=' +
      rotateRight.toString() + ';const sha256=' + fastSha256.toString() +
      `;self.onmessage=function(event){const data=event.data;try{
        const result=sha256(new Uint8Array(data.bytes));
        self.postMessage({id:data.id,result:result},[result]);
      }catch(error){self.postMessage({id:data.id,error:String(error.message||error)});}};`;
  }

  function settle(slot, result, fallback) {
    const job = slot.job;
    if (!job) return;
    slot.job = null;
    root.clearTimeout(job.timer);
    pendingBytes -= job.bytes.byteLength;
    pendingJobs--;
    if (fallback) localDigest(job.bytes).then(job.resolve, job.reject);
    else job.resolve(result);
  }

  function stopWorkers() {
    if (workersDisabled) return;
    workersDisabled = true;
    for (const slot of slots) {
      slot.worker.terminate();
      settle(slot, null, true);
    }
    while (queue.length) {
      const job = queue.shift();
      pendingBytes -= job.bytes.byteLength;
      pendingJobs--;
      localDigest(job.bytes).then(job.resolve, job.reject);
    }
    if (workerURL) { root.URL.revokeObjectURL(workerURL); workerURL = null; }
  }

  function createSlot() {
    if (!workerURL) {
      workerURL = root.URL.createObjectURL(new root.Blob([workerSource()],
        {type: 'text/javascript'}));
    }
    const slot = {worker: new root.Worker(workerURL), job: null};
    slot.worker.onmessage = event => {
      const job = slot.job, data = event.data;
      // A stale or unrelated response must never resolve a different digest.
      if (!job || !data || data.id !== job.id) return;
      let valid = false;
      try { valid = arrayBufferByteLength.call(data.result) === 32; } catch (_) {}
      if (!valid || data.error) { stopWorkers(); return; }
      settle(slot, data.result, false);
      drain();
    };
    slot.worker.onerror = event => { event.preventDefault?.(); stopWorkers(); };
    slot.worker.onmessageerror = stopWorkers;
    slots.push(slot);
    return slot;
  }

  function drain() {
    if (workersDisabled) return;
    try {
      while (queue.length) {
        let slot = slots.find(value => !value.job);
        if (!slot && slots.length < MAX_WORKERS) slot = createSlot();
        if (!slot) return;
        const job = queue.shift();
        slot.job = job;
        job.timer = root.setTimeout(stopWorkers, WORKER_TIMEOUT);
        const transferred = new Uint8Array(job.bytes);
        slot.worker.postMessage({id: job.id, bytes: transferred.buffer}, [transferred.buffer]);
      }
    } catch (_) { stopWorkers(); }
  }

  function offThreadDigest(bytes) {
    if (workersDisabled || bytes.byteLength < WORKER_THRESHOLD ||
        typeof root.Worker !== 'function' || typeof root.Blob !== 'function' ||
        typeof root.URL?.createObjectURL !== 'function' ||
        typeof root.setTimeout !== 'function' || typeof root.clearTimeout !== 'function' ||
        pendingJobs >= MAX_JOBS || pendingBytes + bytes.byteLength > MAX_PENDING_BYTES) {
      return localDigest(bytes);
    }
    return new Promise((resolve, reject) => {
      queue.push({id: ++nextId, bytes, resolve, reject, timer: null});
      pendingJobs++; pendingBytes += bytes.byteLength;
      drain();
    });
  }

  function digest(algorithm, data) {
    try {
      let name;
      if (typeof algorithm === 'string') name = algorithm;
      else if (algorithm && typeof algorithm === 'object' && 'name' in algorithm) {
        name = String(algorithm.name);
      } else throw new TypeError('A digest algorithm name is required');
      if (name.toUpperCase() !== 'SHA-256') {
        const message = 'The LAN digest fallback supports only SHA-256';
        let error;
        if (typeof root.DOMException === 'function') {
          error = new root.DOMException(message, 'NotSupportedError');
        } else {
          error = new Error(message);
          error.name = 'NotSupportedError';
        }
        throw error;
      }
      // Snapshot immediately, before yielding: later caller mutations must
      // not change the digest, matching subtle.digest's byte-copy behavior.
      const bytes = copyBufferSource(data);
      return offThreadDigest(bytes);
    } catch (error) {
      return Promise.reject(error);
    }
  }
  Object.defineProperty(digest, '__ankiStudyAsyncSha256', {value: true});

  let cryptoObject = root.crypto;
  if (!cryptoObject) {
    cryptoObject = {};
    Object.defineProperty(root, 'crypto', {value: cryptoObject, configurable: true});
  }
  let subtle = cryptoObject.subtle;
  if (!subtle) {
    subtle = {};
    Object.defineProperty(cryptoObject, 'subtle', {value: subtle, configurable: true});
  }
  Object.defineProperty(subtle, 'digest', {value: digest, configurable: true, writable: true});
})(globalThis);
