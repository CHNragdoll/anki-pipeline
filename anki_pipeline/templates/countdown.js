// 2027 admissions: first exam begins 2026-12-19 08:30 Beijing time.
(function () {
  var target = Date.parse("2026-12-19T08:30:00+08:00");
  if (window.__ankiExamTimer) clearInterval(window.__ankiExamTimer);
  window.__ankiExamTimer = null;
  var footer = document.querySelector(".exam-countdown");
  if (!footer) {
    footer = document.createElement("div");
    footer.className = "exam-countdown";
    footer.setAttribute("role", "timer");
    // Do not announce each second to screen readers.
    footer.setAttribute("aria-live", "off");
    footer.title = "2027 考研初试：2026年12月19日 08:30（北京时间）";
    document.body.appendChild(footer);
  }
  function render() {
    var seconds = Math.max(0, Math.ceil((target - Date.now()) / 1000));
    if (!seconds) {
      footer.textContent = "2027 考研初试已开始";
      return false;
    }
    var days = Math.floor(seconds / 86400);
    var hours = Math.floor(seconds % 86400 / 3600);
    var minutes = Math.floor(seconds % 3600 / 60);
    footer.textContent = "2027 考研倒计时：" + days + "天 "
      + String(hours).padStart(2, "0") + "时 "
      + String(minutes).padStart(2, "0") + "分 "
      + String(seconds % 60).padStart(2, "0") + "秒";
    return true;
  }
  if (render()) {
    var timer = setInterval(function () {
      if (document.querySelector(".exam-countdown") !== footer || !render()) {
        clearInterval(timer);
        if (window.__ankiExamTimer === timer) window.__ankiExamTimer = null;
      }
    }, 1000);
    window.__ankiExamTimer = timer;
  }
  if (!window.__ankiExamLifecycleBound) {
    window.__ankiExamLifecycleBound = true;
    window.addEventListener("pagehide", function () {
      clearInterval(window.__ankiExamTimer);
      window.__ankiExamTimer = null;
    });
  }
})();
