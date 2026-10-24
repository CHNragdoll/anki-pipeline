/* Private HOST/FRAME verifier for an already-known SHA-256 pin. No digest API
 * replacement, source execution, network URL, normalization or public cache. */
function createKnownPinVerifier(scope, fallbackDigest) {
  let capability = null;
  const fetchBlob = typeof scope.fetch === 'function' ? scope.fetch.bind(scope) : null;
  const byteLength = Object.getOwnPropertyDescriptor(scope.ArrayBuffer.prototype, 'byteLength').get;
  function snapshot(value) {
    if (typeof value === 'string') return new scope.TextEncoder().encode(value);
    let bytes;
    if (scope.ArrayBuffer.isView(value)) {
      byteLength.call(value.buffer);
      bytes = new scope.Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    } else {
      byteLength.call(value);
      bytes = new scope.Uint8Array(value);
    }
    return new scope.Uint8Array(bytes);
  }
  function metadata(pin) {
    let binary = '';
    for (let i = 0; i < 64; i += 2) binary += String.fromCharCode(parseInt(pin.slice(i, i + 2), 16));
    return 'sha256-' + scope.btoa(binary);
  }
  async function blobCheck(bytes, pin, budget = 8000) {
    if (budget <= 0) throw Error('Known-pin verification deadline expired');
    let url = null, response = null, timer = null, controller = null;
    let closed = false, timedOut = false, phase = 'setup';
    function cancelBody() {
      if (response && response.body && !response.bodyUsed) {
        try { Promise.resolve(response.body.cancel()).catch(() => {}); } catch (_) {}
      }
    }
    try {
      url = scope.URL.createObjectURL(new scope.Blob([bytes], {type: 'application/octet-stream'}));
      if (new scope.URL(url).protocol !== 'blob:') throw Error('Known-pin verifier requires a local blob URL');
      controller = new scope.AbortController();
      const deadline = new Promise((_, reject) => {
        timer = scope.setTimeout(() => { timedOut = true; controller.abort(); reject(Error('Known-pin verification timed out')); }, Math.min(8000, budget));
      });
      const operation = (async () => {
        phase = 'fetch';
        response = await fetchBlob(url, {integrity: metadata(pin), credentials: 'omit', redirect: 'error', signal: controller.signal});
        if (closed) { cancelBody(); throw Error('Known-pin verification expired'); }
        phase = 'consume';
        if (!response.ok) throw Error('Known-pin blob response failed');
        const received = await response.arrayBuffer();
        if (closed || byteLength.call(received) !== bytes.byteLength) throw Error('Known-pin blob response length differs');
        return true;
      })();
      return await Promise.race([operation, deadline]);
    } catch (error) {
      const failure = Error('Known-pin blob verification unavailable');
      failure.sriFetchRejected = !timedOut && phase === 'fetch' && error && error.name === 'TypeError';
      throw failure;
    } finally {
      closed = true;
      if (timer !== null) scope.clearTimeout(timer);
      if (controller) controller.abort();
      cancelBody();
      if (url !== null) { try { scope.URL.revokeObjectURL(url); } catch (_) {} }
    }
  }
  async function probe() {
    if (typeof fetchBlob !== 'function' || typeof scope.Blob !== 'function' ||
        typeof scope.URL !== 'function' || typeof scope.URL.createObjectURL !== 'function' ||
        typeof scope.URL.revokeObjectURL !== 'function' || typeof scope.AbortController !== 'function' ||
        typeof scope.btoa !== 'function' || typeof scope.setTimeout !== 'function' || typeof scope.clearTimeout !== 'function') return false;
    const bytes = new scope.Uint8Array([97, 98, 99]), until = Date.now() + 8000;
    try { await blobCheck(bytes, 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', until - Date.now()); }
    catch (_) { return false; }
    try { await blobCheck(bytes, '0'.repeat(64), until - Date.now()); return false; }
    catch (error) { return error.sriFetchRejected === true; }
  }
  return async function knownPinMatches(value, expected) {
    if (typeof expected !== 'string' || !/^[a-f0-9]{64}$/.test(expected)) throw TypeError('Known-pin SHA-256 syntax is invalid');
    // This copy happens synchronously before the shared capability await.
    const bytes = snapshot(value), until = Date.now() + 8000;
    if (!capability) capability = probe().catch(() => false);
    if (await capability && Date.now() < until) {
      try { if (await blobCheck(bytes, expected, until - Date.now())) return true; } catch (_) {}
    }
    // Every unsupported/failed fast path keeps the original digest comparison
    // on the same private byte snapshot. A wrong pin never becomes success.
    return await fallbackDigest(bytes) === expected;
  };
}
