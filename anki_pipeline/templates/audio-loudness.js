// Shared offline/browser playback rules; original recordings stay byte-identical.
(function () {
  'use strict';
  if (window.AnkiAudioLoudness) { window.AnkiAudioLoudness.refresh(); return; }
  // Measured source medians against Cambridge UK; no per-word re-encoding.
  var rules = {uk: {cambridge: 0, oxford: 4.4}, us: {webster: 5.4, oxford: 5.3}};
  var enabled = true, context = null, bindings = new WeakMap(), active = new Set();
  function decibels(audio) {
    var lane = rules[audio.getAttribute('data-dictionary-accent')];
    var source = audio.getAttribute('data-dictionary-source');
    return enabled && lane && Object.prototype.hasOwnProperty.call(lane, source) ? lane[source] : 0;
  }
  function update(entry) {
    if (!entry.graph) return;
    var db = decibels(entry.audio), graph = entry.graph;
    graph.gain.gain.value = Math.pow(10, db / 20) * (entry.audio.muted ? 0 : entry.audio.volume);
    graph.compressor.threshold.value = enabled ? -1 : 0;
    graph.compressor.ratio.value = enabled ? 20 : 1;
    entry.audio.setAttribute('data-loudness-db', String(db));
    entry.audio.setAttribute('data-loudness-state', enabled ? 'active' : 'original');
  }
  function stop(entry) {
    entry.serial++;
    if (!entry.graph) return;
    var graph = entry.graph; entry.graph = null; active.delete(entry);
    graph.source.onended = null;
    try { graph.source.stop(); } catch (_) {}
    graph.source.disconnect(); graph.gain.disconnect(); graph.compressor.disconnect();
  }
  function restoreOrdinary(entry) {
    if (!entry.graph) return;
    var graph = entry.graph, position = graph.offset + Math.max(0, context.currentTime - graph.started);
    stop(entry);
    try { entry.audio.currentTime = position; } catch (_) {}
    entry.audio.setAttribute('data-loudness-state', 'original');
    Promise.resolve(entry.play.call(entry.audio)).catch(function () { entry.audio.dispatchEvent(new Event('error')); });
  }
  function balancedPlay(entry, args) {
    stop(entry);
    var audio = entry.audio, serial = entry.serial;
    // Preserve an ordinary media path throughout, including the original gesture.
    // Buffer sources never reroute HTMLMediaElement output into a suspended context.
    var ordinary = Promise.resolve(entry.play.apply(audio, args));
    var Constructor = window.AudioContext || window.webkitAudioContext;
    if (!decibels(audio) || !Constructor || !window.fetch || audio.playbackRate !== 1) {
      audio.setAttribute('data-loudness-state', 'original'); return ordinary;
    }
    var url;
    try {
      url = new URL(audio.src || audio.currentSrc, document.baseURI);
      if (url.origin !== location.origin || !/^https?:$/.test(url.protocol)) return ordinary;
      if (!context) {
        context = new Constructor();
        context.onstatechange = function () {
          if (context.state !== 'running') Array.from(active).forEach(restoreOrdinary);
        };
      }
    } catch (_) { return ordinary; }
    var ready;
    try {
      ready = context.state === 'running' ? Promise.resolve() : Promise.resolve(context.resume());
      if (entry.url !== url.href || !entry.buffer) {
        entry.url = url.href;
        entry.buffer = fetch(url.href).then(function (response) {
          if (!response.ok) throw new Error('Audio unavailable'); return response.arrayBuffer();
        }).then(function (bytes) { return context.decodeAudioData(bytes); });
      }
    } catch (_) { return ordinary; }
    // Attach a rejection handler immediately, even while media is decoding.
    var ordinaryResult = ordinary.then(function () { return null; }, function (error) { return error; });
    return Promise.all([ready, entry.buffer, ordinaryResult]).then(function (values) {
      if (entry.serial !== serial) return;
      if (context.state !== 'running' || audio.src !== url.href || audio.playbackRate !== 1) {
        audio.setAttribute('data-loudness-state', 'original'); if (values[2]) throw values[2]; return;
      }
      var buffer = values[1], offset = audio.currentTime || 0;
      if (offset >= buffer.duration) return;
      var source = context.createBufferSource(), gain = context.createGain(), compressor = context.createDynamicsCompressor();
      source.buffer = buffer; compressor.knee.value = 0; compressor.attack.value = 0.003; compressor.release.value = 0.08;
      source.connect(gain); gain.connect(compressor); compressor.connect(context.destination);
      entry.graph = {source: source, gain: gain, compressor: compressor, offset: offset, started: context.currentTime}; active.add(entry); update(entry);
      source.onended = function () {
        if (entry.graph && entry.graph.source === source) { stop(entry); audio.dispatchEvent(new Event('ended')); }
      };
      // Skip the part already played; do not restart a word after loading.
      source.start(0, offset); entry.pause.call(audio);
    }).catch(function () {
      if (entry.serial !== serial) return;
      stop(entry);
      audio.setAttribute('data-loudness-state', 'original'); entry.buffer = null;
      // Ordinary audio was never disconnected, so resume/decode errors keep it audible.
      return ordinary;
    });
  }
  function refresh() {
    active.forEach(function (entry) { if (!entry.audio.isConnected) { stop(entry); entry.pause.call(entry.audio); } });
    document.querySelectorAll('audio[data-dictionary-accent="uk"],audio[data-dictionary-accent="us"]').forEach(function (audio) {
      if (bindings.has(audio)) return;
      var entry = {audio: audio, play: audio.play, pause: audio.pause, serial: 0, graph: null};
      bindings.set(audio, entry); audio.setAttribute('data-loudness-rule-db', String(decibels(audio)));
      audio.play = function () { return balancedPlay(entry, arguments); };
      audio.pause = function () { stop(entry); return entry.pause.apply(audio, arguments); };
      audio.addEventListener('volumechange', function () { update(entry); });
      // HTMLMediaElement preserves pitch; a buffer's rate would alter it.
      audio.addEventListener('ratechange', function () { if (audio.playbackRate !== 1) restoreOrdinary(entry); });
      audio.addEventListener('emptied', function () { stop(entry); });
    });
  }
  window.AnkiAudioLoudness = {
    refresh: refresh,
    setEnabled: function (value) {
      enabled = value !== false; active.forEach(update);
      document.querySelectorAll('audio[data-dictionary-accent]').forEach(function (audio) {
        audio.setAttribute('data-loudness-rule-db', String(decibels(audio)));
      });
    }
  };
  refresh();
}());
