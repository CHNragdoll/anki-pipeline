// Refresh every time Anki reuses its card webview; bind delegated events once.
(function () {
  var key = 'anki:exam-source-reader:v1';
  var pronunciationKey = 'anki-dictionary-pronunciation-v1';
  function isPronunciation(source) {
    return source === 'oxford' || source === 'webster';
  }
  function pronunciationName(source) {
    return source === 'webster' ? '韦氏' : '牛津';
  }
  function preferredPronunciation(fallback) {
    // Keep an in-memory choice when a webview can read storage but cannot write
    // it. Same-origin changes refresh this value through the storage event.
    var source = window.__ankiDictionaryPronunciation;
    if (!isPronunciation(source)) {
      try { source = localStorage.getItem(pronunciationKey); } catch (_) {}
    }
    if (!isPronunciation(source)) source = isPronunciation(fallback) ? fallback : 'oxford';
    window.__ankiDictionaryPronunciation = source;
    return source;
  }
  function dictionaryRecording(block, source) {
    var found = null;
    block.querySelectorAll('audio').forEach(function (audio) {
      if (!found && audio.dataset.dictionarySource === source && audio.getAttribute('src')) found = audio;
    });
    if (found) return found;
    // A missing source may use another packaged recording only when the build
    // explicitly declares that per-word exception. Never follow a fallback
    // chain or infer that the first audio element has the requested identity.
    var fallback = block.getAttribute('data-fallback-' + source);
    if (!isPronunciation(fallback) || fallback === source) return null;
    block.querySelectorAll('audio').forEach(function (audio) {
      if (!found && audio.dataset.dictionarySource === fallback && audio.getAttribute('src')) found = audio;
    });
    return found;
  }
  function pronunciationException(source, audio) {
    var actual = audio && audio.dataset.dictionarySource;
    return isPronunciation(actual) && actual !== source ? pronunciationName(source) + '未收录，此词使用' + pronunciationName(actual) + '录音' : '';
  }
  function refreshPronunciation() {
    document.querySelectorAll('.dictionary-word-audio').forEach(function (block) {
      // Accent-aware cards own separate UK/US controls and exact-accent tracks.
      if (block.getAttribute('data-accent-playback') === 'v1') return;
      var source = preferredPronunciation(block.dataset.defaultSource);
      var card = block.closest('.vocab-front');
      var heading = card && card.querySelector('.card-heading');
      var setting = block.querySelector('.dictionary-audio-setting') || heading && heading.querySelector('.dictionary-audio-setting');
      // Keep the source setting in the same top row as metadata, independently
      // of the centered word, IPA and replay button. Repeated Anki refreshes
      // reuse the moved label instead of cloning controls or losing its value.
      if (setting && heading && setting.parentElement !== heading) {
        heading.insertBefore(setting, heading.querySelector('.card-meta'));
      }
      var control = setting ? setting.querySelector('.dictionary-audio-source') : block.querySelector('.dictionary-audio-source');
      var button = block.querySelector('.preview-word-play');
      var status = block.querySelector('.word-audio-status');
      var audio = dictionaryRecording(block, source);
      var available = !!audio;
      var exception = pronunciationException(source, audio);
      var actual = audio ? audio.dataset.dictionarySource : source;
      var replayLabel = '播放' + pronunciationName(actual) + '单词发音' + (exception ? '（' + pronunciationName(source) + '未收录）' : '');
      if (control) control.value = source;
      if (button) {
        button.disabled = !available;
        button.setAttribute('aria-disabled', String(!available));
        button.setAttribute('aria-label', replayLabel);
        button.title = available ? replayLabel : pronunciationName(source) + '发音暂无收录';
      }
      if (status) status.textContent = available ? exception : pronunciationName(source) + '发音暂无收录';
    });
  }
  function refreshDefinitions() {
    document.querySelectorAll('.primary-definition').forEach(function (section) {
      var definition = section.querySelector('.dictionary-definition');
      var enriched = !!definition;
      var fromWordbook = definition && definition.getAttribute('data-dictionary') === 'wordbook';
      var fromEcdict = definition && definition.getAttribute('data-dictionary') === 'ecdict';
      var reviewed = definition && definition.getAttribute('data-dictionary') === 'reviewed';
      var title = section.querySelector('.field-title');
      var meanings = section.closest('.meaning-section');
      var secondary = meanings && meanings.querySelector('.secondary-definition');
      if (enriched) section.setAttribute('data-dictionary-definition', 'oxford');
      else section.removeAttribute('data-dictionary-definition');
      if (title) title.textContent = reviewed ? (definition.getAttribute('data-definition-heading') || '核对后的释义') : fromEcdict ? 'ECDICT 释义（牛津未收录）' : fromWordbook ? '词表释义（牛津未收录）' : enriched ? '牛津释义' : '核心释义';
      if (enriched) section.setAttribute('data-definition-source', reviewed ? 'reviewed' : fromEcdict ? 'ecdict' : fromWordbook ? 'wordbook' : 'oxford');
      else section.removeAttribute('data-definition-source');
      if (secondary) secondary.hidden = enriched;
    });
  }
  function refreshForms() {
    document.querySelectorAll('.forms-section').forEach(function (section) {
      var heading = section.querySelector('.field-title');
      // Dictionary forms already supply separate titles for inflections and
      // word-family members. Keep the legacy heading only for ungrouped cards.
      if (heading) heading.hidden = !!section.querySelector('.dictionary-form-groups');
    });
  }
  function firstLine(card) {
    var word = card && card.querySelector('.word');
    if (!word) return '';
    var copy = word.cloneNode(true);
    copy.querySelectorAll('br').forEach(function (br) { br.replaceWith('\n'); });
    return (copy.textContent || '').split(/\r?\n/)[0].trim();
  }
  function isReader(reader) {
    return reader === 'latex' || reader === 'full-paper';
  }
  function preferredReader(fallback) {
    var reader = window.__ankiExamSourceReader;
    if (!isReader(reader)) {
      try { reader = localStorage.getItem(key); } catch (_) {}
    }
    if (!isReader(reader)) reader = isReader(fallback) ? fallback : 'latex';
    window.__ankiExamSourceReader = reader;
    return reader;
  }
  function sourceUrl(value) {
    if (typeof value !== 'string' || /[\u0000-\u0020\u007f]/.test(value)) return '';
    try {
      var url = new URL(value);
      if ((url.protocol === 'http:' || url.protocol === 'https:') && url.hostname && !url.username && !url.password) return value;
    } catch (_) {}
    return '';
  }
  function updateJump(link, reader) {
    var url = sourceUrl(reader === 'latex' ? link.dataset.latexUrl : link.dataset.fullPaperUrl);
    if (url) {
      link.href = url;
      link.removeAttribute('aria-disabled');
    } else {
      link.removeAttribute('href');
      link.setAttribute('aria-disabled', 'true');
    }
    link.title = '在' + (reader === 'latex' ? ' LaTeX 重排版' : '整卷版') + '定位原句';
  }
  function stopPreviewWord(message) {
    var state = window.__ankiPreviewWordPlayback;
    if (!state) return;
    window.__ankiPreviewWordPlayback = null;
    state.audio.onended = null;
    state.audio.onerror = null;
    state.audio.pause();
    try { state.audio.currentTime = 0; } catch (_) {}
    state.button.setAttribute('aria-pressed', 'false');
    if (state.status) state.status.textContent = message || state.restingMessage || '';
  }
  function playPreviewWord(button) {
    var dictionary = button.closest('.dictionary-word-audio');
    var recording = dictionary || button.closest('.recorded-audio');
    var source = dictionary && preferredPronunciation(dictionary.dataset.defaultSource);
    var audio = dictionary ? dictionaryRecording(dictionary, source) : recording && recording.querySelector('audio');
    if (dictionary && !audio) {
      stopPreviewWord();
      refreshPronunciation();
      return;
    }
    if (!audio) return;
    stopPreviewWord();
    var exception = source ? pronunciationException(source, audio) : '';
    var actual = source ? audio.dataset.dictionarySource : '';
    var state = {audio: audio, button: button, status: recording.querySelector('.word-audio-status'), restingMessage: exception};
    window.__ankiPreviewWordPlayback = state;
    button.setAttribute('aria-pressed', 'true');
    if (state.status) state.status.textContent = (exception ? exception + '；' : '') + (actual ? pronunciationName(actual) + '：' : '') + '正在播放单词发音…';
    function finish(message) {
      if (window.__ankiPreviewWordPlayback === state) stopPreviewWord(message);
    }
    audio.onended = function () { finish(''); };
    var unavailable = (actual ? pronunciationName(actual) : '单词') + '发音暂不可用，请重试' + (exception ? '（' + exception + '）' : '');
    audio.onerror = function () { finish(unavailable); };
    try {
      Promise.resolve(audio.play()).catch(function () { finish(unavailable); });
    } catch (_) { finish(unavailable); }
  }
  function refresh() {
    refreshPronunciation();
    refreshDefinitions();
    refreshForms();
    document.querySelectorAll('.vocab-front').forEach(function (card) {
      var link = card.querySelector('.dictionary-link');
      if (!link) return;
      var word = firstLine(card);
      if (word) {
        link.href = 'eudic://x-callback-url/searchword?word=' + encodeURIComponent(word) + '&x-success=anki%3A%2F%2F';
        link.setAttribute('aria-label', '在欧路词典查找 ' + word);
      } else link.removeAttribute('href');
    });
    document.querySelectorAll('.examples-section').forEach(function (section) {
      var first = section.querySelector('.sentence-jump');
      var control = section.querySelector('.source-reader');
      var label = section.querySelector('.source-reader-setting');
      if (!control || !label) return;
      // Let AnkiMobile deliver reader taps to the native select instead of review tap zones.
      control.classList.add('tappable');
      label.classList.add('tappable');
      label.hidden = !first;
      if (!first) return;
      var reader = preferredReader(first.dataset.reader);
      control.value = reader;
      section.querySelectorAll('.sentence-jump').forEach(function (link) {
        updateJump(link, reader);
      });
    });
  }
  // Stop playback from an older template if its webview is still alive.
  if (window.__ankiStopSentence) window.__ankiStopSentence();
  if (window.__ankiStopPreviewWord) window.__ankiStopPreviewWord();
  window.__ankiStopPreviewWord = stopPreviewWord;
  refresh();
  if (window.__ankiLibraryEventsBound) return;
  window.__ankiLibraryEventsBound = true;
  document.addEventListener('change', function (event) {
    if (event.target.matches && event.target.matches('.dictionary-audio-source')) {
      var source = event.target.value;
      if (!isPronunciation(source)) { refreshPronunciation(); return; }
      stopPreviewWord();
      window.__ankiDictionaryPronunciation = source;
      try { localStorage.setItem(pronunciationKey, source); } catch (_) {}
      refreshPronunciation();
      return;
    }
    if (!event.target.matches || !event.target.matches('.source-reader')) return;
    var reader = event.target.value;
    if (!isReader(reader)) { refresh(); return; }
    window.__ankiExamSourceReader = reader;
    try { localStorage.setItem(key, reader); } catch (_) {}
    document.querySelectorAll('.source-reader').forEach(function (control) { control.value = reader; });
    document.querySelectorAll('.sentence-jump').forEach(function (link) {
      updateJump(link, reader);
    });
  });
  if (window.addEventListener) window.addEventListener('storage', function (event) {
    if (event.key !== pronunciationKey && event.key !== null) return;
    stopPreviewWord();
    window.__ankiDictionaryPronunciation = isPronunciation(event.newValue) ? event.newValue : null;
    refreshPronunciation();
  });
  document.addEventListener('click', function (event) {
    if (!event.target.closest) return;
    var play = event.target.closest('.preview-word-play');
    if (play) { playPreviewWord(play); return; }
    var flip = event.target.closest('#preview-flip');
    if (!flip) return;
    var front = document.getElementById('preview-front');
    var back = document.getElementById('preview-back');
    if (!front || !back) return;
    stopPreviewWord();
    var showBack = flip.getAttribute('aria-pressed') !== 'true';
    front.hidden = showBack;
    back.hidden = !showBack;
    flip.setAttribute('aria-pressed', String(showBack));
    flip.textContent = showBack ? '返回正面' : '显示答案';
    refresh();
  });
})();
