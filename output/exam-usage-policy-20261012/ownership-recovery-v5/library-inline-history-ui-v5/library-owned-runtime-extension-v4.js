  // Additive runtime integration. Frozen URL/flip/ready/history guards stay
  // unchanged. These two shared JSON promises are loaded once per shell.
  var reviewedProjectionPromise = null, sharedBankPromise = null;
  function reviewedProjection() {
    if (!reviewedProjectionPromise) reviewedProjectionPromise = window.AnkiReviewedChunkProjection.load({
      url: '/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json',
      sha256: 'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8'
    }).catch(function (error) { reviewedProjectionPromise = null; throw error; });
    return reviewedProjectionPromise;
  }
  function sharedBank() {
    if (!sharedBankPromise) sharedBankPromise = (async function () {
      var url = new URL('/exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-v5.json', window.location.href);
      var response = await window.fetch(url.href, { credentials: 'same-origin', redirect: 'error' });
      requireCondition(response.ok && response.url === url.href && !response.redirected, '来源对照地址或响应无效');
      var bytes = await response.arrayBuffer();
      requireCondition(bytes.byteLength <= 4 * 1024 * 1024 && window.crypto && window.crypto.subtle, '来源对照无法进行完整核验');
      var digest = await window.crypto.subtle.digest('SHA-256', bytes);
      var hash = Array.from(new Uint8Array(digest)).map(function (v) { return v.toString(16).padStart(2, '0'); }).join('');
      requireCondition(hash === 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5', '来源对照校验失败');
      return JSON.parse(new window.TextDecoder('utf-8', { fatal: true }).decode(bytes));
    })().catch(function (error) { sharedBankPromise = null; throw error; });
    return sharedBankPromise;
  }
  function installOwnedCardRuntime(state, cardDocument) {
    var disposed = false, generation = 0, projectionHandle = null, bankHandle = null, groupHandle = null;
    var wholeHandle = window.AnkiFineChunkRuntime.install(cardDocument);
    var status = node('div', 'owned-runtime-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
    var message = node('span'), retry = node('button', 'small-button', '重试细块与来源对照'); retry.type = 'button'; retry.hidden = true;
    status.append(message, retry); state.frame.before(status);
    var style = cardDocument.createElement('style');
    style.textContent = '[data-reviewed-chunk-projection]:focus-visible{outline:2px solid #1262a3;outline-offset:2px}' +
      '[data-reviewed-source-comparison]{margin-block:.7rem;overflow-wrap:anywhere;min-width:0}' +
      '[data-reviewed-source-comparison] pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}';
    cardDocument.head.append(style);
    function alive(version) { return !disposed && generation === version && frameIsCurrent(state) && state.document === cardDocument && state.ready; }
    function clearHandles() {
      if (groupHandle) groupHandle.dispose(); groupHandle = null;
      if (bankHandle) bankHandle.dispose(); bankHandle = null;
      if (projectionHandle) projectionHandle.dispose(); projectionHandle = null;
    }
    function failure(error, version) {
      if (!alive(version)) return;
      status.hidden = false; status.setAttribute('aria-busy', 'false'); status.dataset.state = 'failed';
      message.textContent = '细块与来源对照加载失败，可重试。'; retry.hidden = false; retry.disabled = false;
      state.frame.setAttribute('data-owned-runtime-state', 'failed');
      // Diagnostic text remains data, never HTML or a substitute card error.
      status.setAttribute('data-error', String(error && error.message || error));
    }
    async function run() {
      var version = ++generation; if (!alive(version)) return; clearHandles();
      status.hidden = false; status.dataset.state = 'loading'; status.removeAttribute('data-error'); status.setAttribute('aria-busy', 'true');
      message.textContent = '正在加载细块与来源对照…'; retry.hidden = true; retry.disabled = true; state.frame.setAttribute('data-owned-runtime-state', 'loading');
      try {
        var inputs = await Promise.all([reviewedProjection(), sharedBank()]);
        if (!alive(version)) return;
        wholeHandle.refresh();
        projectionHandle = window.AnkiReviewedChunkProjection.install(cardDocument, inputs[0], {
          isCurrent: function () { return alive(version); }, onError: function (error) { failure(error, version); }
        });
        requireCondition(!projectionHandle.stats().errors.length, '本句细块投影核验失败');
        bankHandle = window.AnkiSharedReadingBankRuntime.install(cardDocument, inputs[1]);
        await bankHandle.ready;
        if (!alive(version)) return;
        groupHandle = window.AnkiSameSenseGroupRuntime.install(cardDocument);
        status.dataset.state = 'ready'; status.setAttribute('aria-busy', 'false'); status.hidden = true; state.frame.setAttribute('data-owned-runtime-state', 'ready');
      } catch (error) { failure(error, version); }
    }
    retry.addEventListener('click', run); run();
    return function () {
      if (disposed) return; disposed = true; generation++;
      retry.removeEventListener('click', run); clearHandles(); wholeHandle.dispose(); style.remove(); status.remove(); state.frame.removeAttribute('data-owned-runtime-state');
    };
  }
