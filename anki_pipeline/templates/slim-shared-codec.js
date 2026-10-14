/* Offline shared literals only. The outer loader verifies the dictionary and
 * restored original SHA; this codec never executes or interprets the text. */
(function () {
  'use strict';
  if (window.AnkiSlimPackedDecode) return;
  var cache = new Map(), pending = new Map();
  function fail(message) { throw Error('Shared strings: ' + message); }
  function reference(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        typeof value.src !== 'string' || !/^_as_[a-f0-9]{24}\.js$/.test(value.src) ||
        typeof value.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.sha256) ||
        value.src !== '_as_' + value.sha256.slice(0, 24) + '.js') fail('invalid local dictionary reference');
  }
  async function dictionary(info, load) {
    reference(info);
    var key = info.sha256;
    if (cache.has(key)) {
      var prior = cache.get(key); cache.delete(key); cache.set(key, prior); return prior;
    }
    if (pending.has(key)) return pending.get(key);
    var work = Promise.resolve().then(function () { return load(info); }).then(function (raw) {
      if (typeof raw !== 'string') fail('dictionary loader must return its original JSON string');
      var value;
      try { value = JSON.parse(raw); } catch (_) { fail('dictionary JSON is invalid'); }
      if (!value || typeof value !== 'object' || Array.isArray(value) ||
          value.schema !== 'anki-slim-shared-dictionary.v1' || !Array.isArray(value.strings) ||
          value.strings.some(function (entry) { return typeof entry !== 'string'; })) fail('dictionary schema or strings are invalid');
      var strings = Object.freeze(value.strings.slice());
      cache.set(key, strings);
      while (cache.size > 2) cache.delete(cache.keys().next().value);
      return strings;
    });
    pending.set(key, work);
    work.then(function () { pending.delete(key); }, function () { pending.delete(key); });
    return work;
  }
  window.AnkiSlimPackedDecode = async function (value, load) {
    if (!value || typeof value !== 'object' || Array.isArray(value) ||
        value.schema !== 'anki-slim-shared-strings.v1' || !Array.isArray(value.pieces)) fail('packed schema or pieces are invalid');
    if (typeof load !== 'function') fail('verified local loader is required');
    reference(value.dict);
    // Snapshot the pieces before awaiting I/O, so an in-flight caller mutation
    // cannot change the exact string being decoded for the outer SHA check.
    var pieces = value.pieces.slice();
    for (var n = 0; n < pieces.length; n++) {
      var piece = pieces[n];
      if (typeof piece !== 'string' && !(typeof piece === 'number' && Number.isSafeInteger(piece) && piece >= 0)) fail('piece type or integer is invalid');
    }
    var strings = await dictionary(value.dict, load);
    return pieces.map(function (piece) {
      if (typeof piece === 'string') return piece;
      if (piece >= strings.length) fail('dictionary reference is out of bounds');
      return strings[piece];
    }).join('');
  };
})();
