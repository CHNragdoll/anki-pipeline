/* LAN shell companion: repair reader links in DOM; never change sealed HTTP bytes. */
(function () {
  'use strict';
  if (window.AnkiLanLinksRuntime) return;
  var installed = new WeakMap(), frames = new WeakMap();
  var selector = 'a.sentence-jump,a[data-rb-j],a[data-latex-url],a[data-full-paper-url],' +
    '.sf-report[data-residual-auxiliary-entry] .sf-example a[href]';
  var attributes = ['href', 'data-latex-url', 'data-full-paper-url', 'data-reader-url'];
  var destination = window.location;
  var octets = destination.hostname.split('.').map(Number);
  var privateHost = octets.length === 4 && octets.every(function (part, index) {
    return /^[0-9]+$/.test(destination.hostname.split('.')[index]) && part >= 0 && part <= 255;
  }) && (octets[0] === 10 || (octets[0] === 172 && octets[1] >= 16 && octets[1] <= 31) ||
    (octets[0] === 192 && octets[1] === 168));
  var active = destination.protocol === 'http:' && privateHost && /^(8765|8771)$/.test(destination.port);

  function rewritten(value) {
    if (!active || typeof value !== 'string' || /[\u0000-\u0020\u007f]/.test(value)) return value;
    var authority = /^http:\/\/(localhost|127\.0\.0\.1|\[::1\]):(8765|8771)(?=\/)/i.exec(value);
    if (!authority) return value;
    var url;
    try { url = new URL(value); } catch (_) { return value; }
    if (url.username || url.password || url.protocol !== 'http:') return value;
    var reader = /^(?:\/exam-library)?\/practice\/full-paper\.htm$/.test(url.pathname) ||
      /^\/english-exams-reflow-latex\/(kaoyan|cet4|cet6|tem4|tem8)\/papers\/[^/]+\.html?$/.test(url.pathname);
    if (!reader) return value;
    // Keep the source path, query encoding and fragment byte-for-byte.
    return 'http://' + destination.hostname + ':' + authority[2] + value.slice(authority[0].length);
  }

  function repair(anchor) {
    if (!anchor.matches || !anchor.matches(selector)) return;
    attributes.forEach(function (name) {
      var old = anchor.getAttribute(name), current = rewritten(old);
      if (current !== old) anchor.setAttribute(name, current);
    });
  }

  function owned(document) {
    try {
      return document && document.defaultView && (document.defaultView.location.origin === destination.origin ||
        /^(about:blank|about:srcdoc)$/.test(document.URL));
    } catch (_) { return false; }
  }

  function attach(frame) {
    var state = frames.get(frame);
    if (!state) {
      state = { document: null, handle: null };
      frames.set(frame, state);
      frame.addEventListener('load', function () { attach(frame); });
    }
    var document;
    try { document = frame.contentDocument; } catch (_) {}
    if (state.document === document) return;
    if (state.handle) state.handle.dispose();
    state.document = document; state.handle = null;
    if (owned(document)) state.handle = install(document);
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.matches) {
      repair(root);
      if (root.matches('iframe')) attach(root);
    }
    root.querySelectorAll(selector).forEach(repair);
    root.querySelectorAll('iframe').forEach(attach);
  }

  function install(document) {
    if (!active || !owned(document)) return null;
    if (installed.has(document)) return installed.get(document);
    var disposed = false;
    var observer = new MutationObserver(function (changes) {
      if (disposed) return;
      changes.forEach(function (change) {
        if (change.type === 'attributes') repair(change.target);
        else change.addedNodes.forEach(scan);
      });
    });
    function sourceClick(event) {
      var anchor = event.target.closest && event.target.closest(selector);
      if (anchor) repair(anchor);
    }
    function readerChange() { scan(document); }
    function loaded(event) { if (event.target.matches && event.target.matches('iframe')) attach(event.target); }
    var handle = { dispose: function () {
      if (disposed) return;
      disposed = true; observer.disconnect(); installed.delete(document);
      document.removeEventListener('click', sourceClick, true);
      document.removeEventListener('auxclick', sourceClick, true);
      document.removeEventListener('change', readerChange);
      document.removeEventListener('load', loaded, true);
    } };
    installed.set(document, handle);
    document.addEventListener('click', sourceClick, true);
    document.addEventListener('auxclick', sourceClick, true);
    document.addEventListener('change', readerChange);
    document.addEventListener('load', loaded, true);
    observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true,
      attributeFilter: attributes.concat(['class', 'data-rb-j', 'data-reader']) });
    scan(document);
    return handle;
  }
  window.AnkiLanLinksRuntime = Object.freeze({ install: install });
  install(window.document);
})();
