// This script may run again when Anki reuses its card webview.
(function () {
  function firstLine(card) {
    var word = card && card.querySelector(".word");
    if (!word) return "";
    var copy = word.cloneNode(true);
    copy.querySelectorAll("br").forEach(function (br) { br.replaceWith("\n"); });
    return (copy.textContent || "").split(/\r?\n/)[0].trim();
  }

  function refreshDictionaryLinks() {
    document.querySelectorAll(".vocab-front").forEach(function (card) {
      var link = card.querySelector(".dictionary-link");
      if (!link) return;
      var word = firstLine(card);
      if (word) {
        link.href = "eudic://x-callback-url/searchword?word=" + encodeURIComponent(word)
          + "&x-success=anki%3A%2F%2F";
        link.setAttribute("aria-label", "在欧路词典查找 " + word);
      } else {
        link.removeAttribute("href");
      }
    });
  }

  refreshDictionaryLinks();
  if (window.__ankiStopSentence) window.__ankiStopSentence();
  if (window.__ankiRebuildCardEventsBound) return;
  window.__ankiRebuildCardEventsBound = true;

  var activePlayback = null;
  function stopSentence() {
    if (!activePlayback) return;
    var old = activePlayback;
    activePlayback = null;
    clearTimeout(old.timer);
    old.audio.pause();
    old.audio.removeAttribute("src");
    old.audio.remove();
    if (old.local && window.speechSynthesis) window.speechSynthesis.cancel();
    old.button.setAttribute("aria-pressed", "false");
  }
  window.__ankiStopSentence = stopSentence;
  window.addEventListener("pagehide", stopSentence);

  function playSentence(button) {
    var repeated = activePlayback && activePlayback.button === button;
    stopSentence();
    if (repeated) return;
    var card = button.closest(".example-card");
    var textNode = card.querySelector(".example-text").cloneNode(true);
    textNode.querySelectorAll("br").forEach(function (br) { br.replaceWith(" "); });
    var sentence = textNode.textContent.replace(/\s+/g, " ").trim();
    if (!sentence) return;
    var status = card.querySelector(".sentence-status");
    status.textContent = "";
    var playback = {audio: new Audio(), button: button, local: false};
    activePlayback = playback;
    playback.audio.className = "sentence-audio";
    playback.audio.hidden = true;
    document.body.appendChild(playback.audio);
    button.setAttribute("aria-pressed", "true");
    function failed() {
      if (activePlayback !== playback) return;
      status.textContent = "朗读暂不可用，请检查网络或语音设置。";
      stopSentence();
    }
    function finished() { if (activePlayback === playback) stopSentence(); }
    function fallback() {
      if (activePlayback !== playback || playback.local) return;
      playback.local = true;
      clearTimeout(playback.timer);
      if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) { failed(); return; }
      playback.audio.pause();
      var voice = new SpeechSynthesisUtterance(sentence);
      voice.lang = "en-US";
      voice.onstart = function () { clearTimeout(playback.timer); };
      voice.onend = finished;
      voice.onerror = failed;
      playback.voice = voice;
      playback.timer = setTimeout(failed, 10000);
      window.speechSynthesis.speak(voice);
    }
    playback.audio.onended = finished;
    playback.audio.onplaying = function () { clearTimeout(playback.timer); };
    playback.audio.onerror = fallback;
    playback.audio.onstalled = function () {
      clearTimeout(playback.timer);
      playback.timer = setTimeout(fallback, 8000);
    };
    playback.timer = setTimeout(fallback, 8000);
    playback.audio.src = "https://dict.youdao.com/dictvoice?type=0&audio=" + encodeURIComponent(sentence);
    playback.audio.play().catch(fallback);
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || !target.closest) return;

    var flip = target.closest("#preview-flip");
    if (flip) {
      stopSentence();
      var front = document.getElementById("preview-front");
      var back = document.getElementById("preview-back");
      if (!front || !back) return;
      var showBack = flip.getAttribute("aria-pressed") !== "true";
      front.hidden = showBack;
      back.hidden = !showBack;
      flip.setAttribute("aria-pressed", String(showBack));
      flip.textContent = showBack ? "返回正面" : "显示答案";
      refreshDictionaryLinks();
      return;
    }
    var sentenceButton = target.closest(".sentence-play");
    if (sentenceButton) playSentence(sentenceButton);
  });
})();
