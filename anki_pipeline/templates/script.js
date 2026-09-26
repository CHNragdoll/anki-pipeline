// Local pronunciation is opt-in. Recorded Anki media remains independent.
if (!window.__ankiRebuildSpeechBound) {
  window.__ankiRebuildSpeechBound = true;
  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest(".speak-button");
    if (!button || !window.speechSynthesis || !window.SpeechSynthesisUtterance) return;
    var word = button.getAttribute("data-word");
    if (!word) return;
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(word);
    utterance.lang = "en-US";
    window.speechSynthesis.speak(utterance);
  });
}
