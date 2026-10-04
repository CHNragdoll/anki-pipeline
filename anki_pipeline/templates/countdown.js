// 2027 admissions: first exam begins 2026-12-19 08:30 Beijing time.
// This fixed helper can also travel in Meta when Anki retains an older model.
(function () {
  var target = Date.parse("2026-12-19T08:30:00+08:00");
  var styleId = "anki-exam-countdown-layout-v2";
  // Keep the upgrade self-contained in retained models. The countdown belongs
  // to the card content, after its translated examples, rather than the window.
  var layoutCss = [
    // The client owns its reviewer shell and scrolling. In AnkiDroid #qa can
    // be nested inside #content; a zero flex basis there collapses the card.
    '.anki-countdown-content{box-sizing:border-box;display:block;flex:none;min-width:0;min-height:0;height:auto;width:100%;max-width:100%;overflow:visible}',
    '.anki-countdown-content .exam-countdown{position:static!important;inset:auto!important;z-index:auto!important;transform:none!important;box-sizing:border-box;width:fit-content!important;max-width:100%!important;margin:.35rem 0 0 auto!important;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:var(--pink,#b51c83);font-size:.8rem;line-height:1.6;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;pointer-events:none}'
  ].join('\n');
  function stop() {
    if (window.__ankiExamTimer) clearInterval(window.__ankiExamTimer);
    window.__ankiExamTimer = null;
  }
  function ownsHost(state) {
    return state && window.__ankiExamCountdownState === state
      && document.documentElement.contains(state.host)
      && state.content.parentElement === state.host && state.footer.parentElement === state.footerHost
      && state.content.contains(state.footer);
  }
  function release(state) {
    if (!state) return;
    if (state.observer) state.observer.disconnect();
    if (window.__ankiExamCountdownState !== state) return;
    clearInterval(state.timer);
    var activeFooter = document.querySelector('.exam-countdown');
    // A retained model may have replaced our interval. Clear that old timer
    // when no other note owns a footer, while leaving a foreign timer alone.
    if (window.__ankiExamTimer === state.timer || !activeFooter || activeFooter === state.footer) stop();
    // Remove our countdown before unwrapping, including a plain-card fallback
    // whose footerHost is the content wrapper itself.
    if (state.footer.parentElement === state.footerHost) state.footer.remove();
    if (state.content.parentElement === state.host) {
      while (state.content.firstChild) state.host.insertBefore(state.content.firstChild, state.content);
      state.content.remove();
    }
    // Older helpers may have taken over the document layout. Release only
    // the classes they owned when upgrading a still-mounted card.
    (state.classes || []).forEach(function (item) {
      if (!item.present) item.node.classList.remove(item.name);
    });
    if (document.getElementById(styleId) === state.style) {
      if (state.styleText === null) state.style.remove();
      else state.style.textContent = state.styleText;
    }
    window.__ankiExamCountdownState = null;
  }
  function mount() {
    var previous = window.__ankiExamCountdownState;
    if (previous && (!ownsHost(previous) || previous.layoutVersion !== 3)) release(previous);
    stop();
    var state = window.__ankiExamCountdownState;
    var host = document.getElementById('qa') || document.getElementById('content') || document.body;
    if (!host) return;
    var style = document.getElementById(styleId);
    var styleText = style ? style.textContent : null;
    if (!style) {
      style = document.createElement('style');
      style.id = styleId;
      (document.head || document.body).appendChild(style);
    }
    style.textContent = layoutCss;
    var content = null;
    Array.from(host.children).some(function (node) {
      if (node.classList.contains('anki-countdown-content')) { content = node; return true; }
      return false;
    });
    if (!content) {
      content = document.createElement('div');
      content.className = 'anki-countdown-content';
      // Anki iterates a live script collection. Keep the field helper before
      // the trailing card initializer when its containing card is wrapped.
      host.insertBefore(content, host.firstChild);
    }
    var footer = host.querySelector('.exam-countdown') || document.querySelector('.exam-countdown');
    if (!footer) {
      footer = document.createElement('div');
      footer.className = 'exam-countdown';
    }
    footer.setAttribute('role', 'timer');
    footer.setAttribute('aria-live', 'off');
    footer.title = '2027 考研初试：2026年12月19日 08:30（北京时间）';
    document.querySelectorAll('.exam-countdown').forEach(function (node) {
      if (node !== footer) node.remove();
    });
    Array.from(host.childNodes).forEach(function (node) {
      if (node === content || node === footer || /^(SCRIPT|STYLE|LINK)$/.test(node.nodeName)) return;
      content.appendChild(node);
    });
    var footerHost = content.querySelector('.examples-section') || content.querySelector('.vocab-back')
      || content.querySelector('.vocab-front') || content;
    footerHost.appendChild(footer);
    if (!state) {
      state = { host: host, content: content, footer: footer, footerHost: footerHost, style: style,
                styleText: styleText, layoutVersion: 3, timer: null, observer: null, observing: false };
      window.__ankiExamCountdownState = state;
      // This lifecycle is independent of either timer: it still runs when the
      // retained model replaced our interval or the target has already passed.
      state.observer = new MutationObserver(function () {
        if (window.__ankiExamCountdownState !== state) { state.observer.disconnect(); return; }
        if (!ownsHost(state)) { release(state); return; }
      });
    }
    if (!state.observing) {
      state.observer.observe(document.body, { childList: true, subtree: true });
      state.observing = true;
    }
    function render() {
      var seconds = Math.max(0, Math.ceil((target - Date.now()) / 1000));
      if (!seconds) { footer.textContent = '2027 考研初试已开始'; return false; }
      footer.textContent = '2027 考研倒计时：' + Math.floor(seconds / 86400) + '天 '
        + String(Math.floor(seconds % 86400 / 3600)).padStart(2, '0') + '时 '
        + String(Math.floor(seconds % 3600 / 60)).padStart(2, '0') + '分 '
        + String(seconds % 60).padStart(2, '0') + '秒';
      return true;
    }
    if (render()) {
      var timer = setInterval(function () {
        if (!ownsHost(state)) { release(state); return; }
        if (document.querySelector('.exam-countdown') !== footer || !render()) {
          clearInterval(timer);
          if (window.__ankiExamTimer === timer) window.__ankiExamTimer = null;
        }
      }, 1000);
      state.timer = timer;
      window.__ankiExamTimer = timer;
    }
  }
  window.__ankiExamCountdownMount = mount;
  window.__ankiExamCountdownCleanup = function () {
    var state = window.__ankiExamCountdownState;
    if (ownsHost(state)) {
      stop();
      state.observer.disconnect();
      state.observing = false;
    }
    else release(state);
  };
  window.__ankiExamCountdownResume = function () {
    var state = window.__ankiExamCountdownState;
    if (ownsHost(state)) mount();
    else release(state);
  };
  if (!window.__ankiExamCountdownLifecycleBound) {
    window.__ankiExamCountdownLifecycleBound = true;
    window.addEventListener('pagehide', function () { window.__ankiExamCountdownCleanup(); });
    window.addEventListener('pageshow', function () { window.__ankiExamCountdownResume(); });
  }
  if (document.readyState === 'loading') {
    var pendingHost = document.getElementById('qa') || document.getElementById('content') || document.body;
    window.__ankiExamCountdownPending = {
      host: pendingHost, anchor: pendingHost && (pendingHost.querySelector('.vocab-card') || pendingHost.firstElementChild)
    };
    if (!window.__ankiExamCountdownReadyBound) {
      window.__ankiExamCountdownReadyBound = true;
      document.addEventListener('DOMContentLoaded', function () {
        window.__ankiExamCountdownReadyBound = false;
        var pending = window.__ankiExamCountdownPending;
        window.__ankiExamCountdownPending = null;
        if (!pending || !pending.host || !document.documentElement.contains(pending.host)
            || pending.anchor && !pending.host.contains(pending.anchor)) return;
        window.__ankiExamCountdownMount();
      }, { once: true });
    }
  } else mount();
})();
