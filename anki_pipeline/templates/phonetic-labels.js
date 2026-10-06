// IPA is display text. Recordings must declare both dictionary and accent.
(function () {
  'use strict';
  var keys = {uk: 'anki-dictionary-uk-pronunciation-v1', us: 'anki-dictionary-pronunciation-v1'};
  var memories = {uk: '__ankiDictionaryUKPronunciation', us: '__ankiDictionaryPronunciation'};
  var sources = {uk: ['cambridge', 'oxford'], us: ['oxford', 'webster']};
  var recordingSources = {
    uk: ['cambridge', 'oxford', 'collins', 'wiktionary', 'forvo'],
    us: ['oxford', 'webster', 'cambridge', 'collins', 'wiktionary', 'forvo']
  };
  var names = {cambridge: '剑桥', oxford: '牛津', webster: '韦氏', collins: '柯林斯', wiktionary: '维基词典', forvo: 'Forvo'};
  function preference(accent) {
    var value = window[memories[accent]];
    if (sources[accent].indexOf(value) < 0) {
      try { value = localStorage.getItem(keys[accent]); } catch (_) {}
    }
    if (sources[accent].indexOf(value) < 0) value = sources[accent][0];
    window[memories[accent]] = value;
    return value;
  }
  function recording(block, accent, source) {
    var found = null;
    function find(actual) {
      block.querySelectorAll('audio').forEach(function (audio) {
        if (!found && audio.getAttribute('data-dictionary-accent') === accent &&
            audio.getAttribute('data-dictionary-source') === actual && audio.getAttribute('src')) found = audio;
      });
    }
    find(source);
    // This same-accent fallback also covers older cards without a declaration.
    if (!found && accent === 'us' && source === 'webster') find('oxford');
    if (!found) {
      var fallback = block.getAttribute('data-fallback-' + accent + '-' + source);
      // Keep the chosen preference, but allow the requested Webster -> Oxford
      // US fallback. The caption and accessible label name the actual provider.
      var otherUSBrand = accent === 'us' &&
        (fallback === 'oxford' || fallback === 'webster') &&
        !(source === 'webster' && fallback === 'oxford');
      if (!otherUSBrand && recordingSources[accent].indexOf(fallback) >= 0 && fallback !== source) find(fallback);
    }
    return found;
  }
  function stop(message) {
    if (window.__ankiStopPreviewWord) { window.__ankiStopPreviewWord(message); return; }
    var state = window.__ankiPreviewWordPlayback;
    if (!state) return;
    window.__ankiPreviewWordPlayback = null;
    state.audio.onended = state.audio.onerror = null;
    state.audio.pause();
    try { state.audio.currentTime = 0; } catch (_) {}
    state.button.setAttribute('aria-pressed', 'false');
    if (state.status) state.status.textContent = message || state.restingMessage || '';
  }
  function exception(accent, requested, audio) {
    var actual = audio && audio.getAttribute('data-dictionary-source');
    return actual && actual !== requested ? (accent === 'uk' ? '英式' : '美式') + names[requested] + '未收录，此词使用' + names[actual] + '录音' : '';
  }
  function icon(accent) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'phonetic-accent-icon phonetic-accent-' + accent;
    button.setAttribute('data-accent', accent);
    button.setAttribute('aria-label', accent === 'uk' ? '英式音标 BrE' : '美式音标 NAmE');
    button.setAttribute('aria-pressed', 'false');
    return button;
  }
  function enhance(line) {
    if (line.querySelector('.phonetic-accent')) return;
    var match = /^英:([\s\S]+?)\s+美:([\s\S]+)$/.exec(line.textContent.trim());
    if (!match) return;
    var fragment = document.createDocumentFragment();
    ['uk', 'us'].forEach(function (accent, index) {
      var group = document.createElement('span');
      group.className = 'phonetic-accent';
      var button = icon(accent);
      var value = document.createElement('span');
      value.className = 'phonetic-accent-value';
      value.textContent = match[index + 1];
      group.appendChild(button); group.appendChild(value);
      if (index) fragment.appendChild(document.createTextNode(' '));
      fragment.appendChild(group);
    });
    line.textContent = ''; line.appendChild(fragment); line.classList.add('phonetic-accents');
  }
  function setting(accent) {
    var label = document.createElement('label');
    label.className = 'dictionary-audio-setting accent-audio-setting';
    label.setAttribute('data-accent', accent);
    label.appendChild(document.createTextNode(accent === 'uk' ? '英式发音 ' : '美式发音 '));
    var select = document.createElement('select');
    select.className = 'dictionary-audio-source-' + accent;
    select.setAttribute('data-accent-source', accent);
    select.setAttribute('aria-label', accent === 'uk' ? '选择英式发音来源' : '选择美式发音来源');
    sources[accent].forEach(function (source) {
      var option = document.createElement('option'); option.value = source; option.textContent = names[source]; select.appendChild(option);
    });
    label.appendChild(select); return label;
  }
  function refresh() {
    document.querySelectorAll('.phonetic-line').forEach(enhance);
    document.querySelectorAll('.dictionary-word-audio[data-accent-playback="v1"]').forEach(function (block) {
      var card = block.closest('.vocab-front');
      var heading = card && card.querySelector('.card-heading');
      if (!heading) return;
      if (!card.querySelector('.phonetic-accent')) {
        // Audio availability is independent of whether IPA is dual, single,
        // or absent. Keep the authored IPA text; never invent a second accent.
        var line = card.querySelector('.phonetic-line');
        if (!line) {
          line = document.createElement('div'); line.className = 'phonetic-line';
          var audioLine = block.closest('.audio-line') || block;
          audioLine.parentNode.insertBefore(line, audioLine);
        }
        ['uk', 'us'].forEach(function (accent) {
          var group = document.createElement('span'); group.className = 'phonetic-accent';
          group.appendChild(icon(accent)); line.appendChild(group);
        });
        line.classList.add('phonetic-accents');
      }
      var controls = heading.querySelector('.pronunciation-settings');
      if (!controls) {
        controls = document.createElement('div'); controls.className = 'pronunciation-settings';
        heading.insertBefore(controls, heading.firstChild);
        // Remove the legacy selector and replay icon only from opted-in cards.
        card.querySelectorAll('.dictionary-audio-setting').forEach(function (old) { old.remove(); });
        controls.appendChild(setting('uk')); controls.appendChild(setting('us'));
      }
      block.querySelectorAll('.preview-word-play').forEach(function (old) { old.remove(); });
      ['uk', 'us'].forEach(function (accent) {
        var source = preference(accent);
        controls.querySelector('[data-accent-source="' + accent + '"]').value = source;
        var button = card.querySelector('.phonetic-accent-' + accent);
        var audio = recording(block, accent, source);
        var label = (accent === 'uk' ? '英式发音 BrE' : '美式发音 NAmE');
        var notice = audio ? exception(accent, source, audio) : label + '暂无录音';
        button.disabled = !audio;
        button.setAttribute('aria-disabled', String(!audio));
        button.setAttribute('aria-label', audio ? '播放' + label + '（' + names[audio.getAttribute('data-dictionary-source')] + '）' : notice);
        button.title = notice || button.getAttribute('aria-label');
        var status = block.querySelector('.accent-status-' + accent);
        if (!status) {
          status = document.createElement('span'); status.className = 'word-audio-status accent-status-' + accent;
          status.setAttribute('role', 'status'); block.appendChild(status);
        }
        if (!window.__ankiPreviewWordPlayback || window.__ankiPreviewWordPlayback.status !== status) status.textContent = notice;
      });
      var legacyStatus = block.querySelector('.word-audio-status:not([class*="accent-status-"])');
      if (legacyStatus) legacyStatus.remove();
    });
  }
  function change(event) {
    var accent = event.target.getAttribute && event.target.getAttribute('data-accent-source');
    if (!sources[accent] || sources[accent].indexOf(event.target.value) < 0) return;
    // An already open Anki webview can retain anonymous v1 bubble listeners.
    // Handle only our controls in capture phase before those old closures run.
    event.stopImmediatePropagation();
    stop(); window[memories[accent]] = event.target.value;
    try { localStorage.setItem(keys[accent], event.target.value); } catch (_) {}
    refresh();
  }
  function storage(event) {
    ['uk', 'us'].forEach(function (accent) {
      if (event.key !== keys[accent] && event.key !== null) return;
      window[memories[accent]] = null; stop(); refresh();
    });
  }
  function click(event) {
    if (!event.target.closest) return;
    var button = event.target.closest('.phonetic-accent-icon');
    if (!button) { if (event.target.closest('#preview-flip')) refresh(); return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    var card = button.closest('.vocab-front');
    var block = card && card.querySelector('.dictionary-word-audio[data-accent-playback="v1"]');
    if (!block) {
      var pressed = button.getAttribute('aria-pressed') !== 'true';
      button.closest('.phonetic-line').querySelectorAll('.phonetic-accent-icon').forEach(function (other) {
        other.setAttribute('aria-pressed', String(other === button && pressed));
      });
      return;
    }
    var previous = window.__ankiPreviewWordPlayback;
    stop();
    if (previous && previous.button === button) return;
    var accent = button.getAttribute('data-accent'); var source = preference(accent);
    var audio = recording(block, accent, source);
    if (!audio) { refresh(); return; }
    var status = block.querySelector('.accent-status-' + accent);
    var state = {audio: audio, button: button, status: status, restingMessage: exception(accent, source, audio)};
    window.__ankiPreviewWordPlayback = state;
    button.setAttribute('aria-pressed', 'true');
    status.textContent = (accent === 'uk' ? '英式' : '美式') + names[audio.getAttribute('data-dictionary-source')] + '：正在播放…';
    function finish(message) { if (window.__ankiPreviewWordPlayback === state) stop(message); }
    audio.onended = function () { finish(''); };
    var failure = '录音暂不可用，请重试';
    audio.onerror = function () { finish(failure); };
    try { Promise.resolve(audio.play()).catch(function () { finish(failure); }); } catch (_) { finish(failure); }
  }
  // Update the runtime for each newly rendered native face. The installed
  // capture listeners dispatch to it, so future template upgrades keep neither
  // stale provider lists nor duplicate playback handlers.
  window.__ankiPhoneticLabelsRuntimeV2 = {change: change, click: click, storage: storage};
  refresh();
  if (window.__ankiPhoneticLabelsV2) return;
  window.__ankiPhoneticLabelsV2 = true;
  document.addEventListener('change', function (event) {
    window.__ankiPhoneticLabelsRuntimeV2.change(event);
  }, true);
  document.addEventListener('click', function (event) {
    window.__ankiPhoneticLabelsRuntimeV2.click(event);
  }, true);
  window.addEventListener('storage', function (event) {
    window.__ankiPhoneticLabelsRuntimeV2.storage(event);
  });
})();
