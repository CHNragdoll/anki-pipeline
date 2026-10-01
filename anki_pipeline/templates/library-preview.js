(function () {
  'use strict';

  var ALL_DECKS = 'all';
  var readerStorageKey = 'anki:exam-source-reader:v1';
  // Only embedded web previews receive these constraints. The shared Anki
  // templates retain their styling, while text and controls fit the frame.
  var responsiveCardCss = [
    'html.anki-library-card, .anki-library-card body { width: 100%; min-width: 0; max-width: 100%; margin: 0; overflow-wrap: anywhere; }',
    '.anki-library-card * { box-sizing: border-box; }',
    '.anki-library-card *::before, .anki-library-card *::after { box-sizing: border-box; }',
    '.anki-library-card #preview-front, .anki-library-card #preview-back { width: 100%; min-width: 0; max-width: 100%; }',
    '.anki-library-card .vocab-card { min-width: 0; max-width: 100%; }',
    '.anki-library-card .front-box, .anki-library-card .center-container, .anki-library-card .word-wrapper, .anki-library-card .meaning-section, .anki-library-card .field-callout, .anki-library-card .field-content, .anki-library-card .examples-section, .anki-library-card .examples, .anki-library-card .examples li, .anki-library-card .example-heading, .anki-library-card .examples-bar, .anki-library-card .sense-row, .anki-library-card .forms-list, .anki-library-card .form-row, .anki-library-card .audio-line, .anki-library-card .recorded-audio { min-width: 0; max-width: 100%; }',
    '.anki-library-card .vocab-front, .anki-library-card .vocab-back { padding-inline: clamp(.65rem, 3vw, 1.5rem); }',
    '.anki-library-card .front-box { padding-inline: clamp(.75rem, 6vw, 3.5rem); }',
    '.anki-library-card .meaning-section { padding-inline: clamp(.6rem, 3vw, 1.3rem); }',
    '.anki-library-card .examples li { padding-inline: clamp(.6rem, 3vw, 1.25rem); }',
    '.anki-library-card .card-meta, .anki-library-card .word, .anki-library-card .phonetic-line, .anki-library-card .field-content, .anki-library-card .sense-pos, .anki-library-card .sense-text, .anki-library-card .form-row dt, .anki-library-card .form-row dd, .anki-library-card .example-text, .anki-library-card .example-translation, .anki-library-card .example-source, .anki-library-card .sentence-status, .anki-library-card .personal-note { min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: normal; white-space: normal; }',
    '.anki-library-card .word-wrapper { display: inline-grid; grid-template-columns: 44px minmax(0, 1fr) 44px; column-gap: .4rem; justify-content: center; align-items: start; }',
    '.anki-library-card .word { grid-column: 2; }',
    '.anki-library-card .dictionary-link { position: static; grid-column: 3; align-self: start; max-width: 100%; margin-top: -.35rem; }',
    '.anki-library-card .example-heading { flex-wrap: wrap; }',
    '.anki-library-card .example-text { flex: 1 1 0; }',
    '.anki-library-card .sentence-jump { max-width: 100%; margin-right: 0; }',
    '.anki-library-card .source-reader-setting, .anki-library-card .source-reader { min-width: 0; max-width: 100%; white-space: normal; }',
    '.anki-library-card img, .anki-library-card audio, .anki-library-card video, .anki-library-card button { max-width: 100%; }',
    '@media (max-width: 480px) { .anki-library-card .word.anki-preview-long-word { font-size: 6vw; } }',
    '@media (max-width: 300px) { .anki-library-card .word.anki-preview-long-word { font-size: 1.125rem; } }',
    '@media (max-width: 420px) { .anki-library-card .form-row { grid-template-columns: minmax(0, 1fr); } }'
  ].join('\n');
  var elements = {};
  ['library-name', 'library-summary', 'catalog-failure', 'catalog-error', 'retry-catalog',
    'browse-toggle', 'browse-close', 'browse-backdrop', 'browse-panel', 'deck-tree',
    'word-search', 'clear-search', 'word-count', 'word-list', 'word-empty',
    'card-stage', 'deck-path', 'card-position', 'previous-card', 'next-card', 'flip-card',
    'card-status', 'card-failure', 'card-error', 'retry-card', 'frame-host'].forEach(function (id) {
    elements[id] = document.getElementById(id);
  });
  var catalog = null;
  var cardsById = new Map();
  var decksById = new Map();
  var wordButtons = new Map();
  var deckButtons = new Map();
  var selectedDeck = ALL_DECKS;
  var query = '';
  var matchingCards = [];
  var currentCardId = null;
  var activeFrame = null;
  var fetchGeneration = 0;
  var browseOpen = false;
  var media = window.matchMedia ? window.matchMedia('(max-width: 900px)') : null;
  var narrow = media ? media.matches : window.innerWidth <= 900;

  function node(tag, className, text) {
    var result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function count(value) { return value.toLocaleString(); }
  function integer(value) { return Number.isSafeInteger(value) && value >= 0; }
  function string(value) { return typeof value === 'string'; }
  function identifier(value) { return string(value) && value.length > 0 && !/[\u0000-\u001f\u007f]/.test(value); }
  function requireCondition(condition, message) { if (!condition) throw new Error(message); }
  function sameOriginUrl(value, card) {
    requireCondition(string(value) && value && !/[\u0000-\u0020\u007f]/.test(value), '目录包含无效地址');
    var url = new URL(value, window.location.href);
    requireCondition((url.protocol === 'http:' || url.protocol === 'https:') &&
      url.origin === window.location.origin && !url.username && !url.password, '目录地址必须同源');
    if (card) requireCondition(/\/web-preview\/[a-z0-9_-]+\/cards\/[a-f0-9]+\.html$/i.test(url.pathname) &&
      !url.search && !url.hash, '卡片地址不属于生成的预览目录');
    return url;
  }
  function validateCatalog(value) {
    requireCondition(value && value.schema === 'anki-web-catalog.v1', '目录格式不受支持');
    requireCondition(string(value.deckName) && (value.defaultReader === 'latex' || value.defaultReader === 'full-paper') &&
      Array.isArray(value.decks) && Array.isArray(value.cards), '目录缺少必要字段');
    requireCondition(value.counts && integer(value.counts.cards) && integer(value.counts.decks) && integer(value.counts.examples), '目录计数无效');
    var deckMap = new Map();
    var cardMap = new Map();
    value.decks.forEach(function (deck) {
      requireCondition(deck && identifier(deck.id) && deck.id !== ALL_DECKS && !deckMap.has(deck.id) &&
        string(deck.name) && string(deck.unit) && string(deck.lesson) && integer(deck.count) && Array.isArray(deck.cardIds), '卡组字段或标识无效');
      requireCondition(deck.cardIds.length === deck.count && new Set(deck.cardIds).size === deck.cardIds.length, '卡组计数或卡片标识重复');
      deckMap.set(deck.id, deck);
    });
    var examples = 0;
    value.cards.forEach(function (card) {
      requireCondition(card && identifier(card.id) && !cardMap.has(card.id) && identifier(card.deckId) &&
        ['word', 'deckName', 'unit', 'lesson', 'position', 'definition'].every(function (key) { return string(card[key]); }) &&
        integer(card.exampleCount), '卡片字段或标识无效');
      var deck = deckMap.get(card.deckId);
      requireCondition(deck && card.deckName === deck.name && card.unit === deck.unit && card.lesson === deck.lesson, '卡片与卡组关联无效');
      cardMap.set(card.id, Object.assign({}, card, { previewHref: sameOriginUrl(card.previewUrl, true).href }));
      examples += card.exampleCount;
    });
    var assigned = new Set();
    value.decks.forEach(function (deck) {
      deck.cardIds.forEach(function (id) {
        var card = cardMap.get(id);
        requireCondition(card && card.deckId === deck.id && !assigned.has(id), '卡组包含缺失或重复关联的卡片');
        assigned.add(id);
      });
    });
    requireCondition(assigned.size === cardMap.size && value.counts.cards === cardMap.size &&
      value.counts.decks === deckMap.size && value.counts.examples === examples, '目录总计与卡片不一致');
    return { catalog: value, cards: cardMap, decks: deckMap };
  }

  function renderDecks() {
    var fragment = document.createDocumentFragment();
    deckButtons.clear();
    function deckButton(id, name, total) {
      var button = node('button', 'deck-entry');
      button.type = 'button';
      if (id !== ALL_DECKS) button.dataset.deckId = id;
      button.append(node('span', '', name), node('span', 'entry-count', count(total)));
      button.addEventListener('click', function () { chooseDeck(id); });
      deckButtons.set(id, button);
      return button;
    }
    fragment.append(deckButton(ALL_DECKS, '全部卡组', catalog.counts.cards));
    var units = new Map();
    catalog.decks.forEach(function (deck) {
      var name = deck.unit || '未分组';
      if (!units.has(name)) units.set(name, []);
      units.get(name).push(deck);
    });
    units.forEach(function (decks, name) {
      var group = node('details', 'unit-group');
      group.open = true;
      var summary = node('summary', '', name);
      summary.append(node('span', 'entry-count', count(decks.reduce(function (total, deck) { return total + deck.count; }, 0))));
      var lessons = node('ul', 'lesson-list');
      decks.forEach(function (deck) {
        var item = node('li');
        var button = deckButton(deck.id, deck.lesson || deck.name, deck.count);
        button.title = deck.name;
        item.append(button);
        lessons.append(item);
      });
      group.append(summary, lessons);
      fragment.append(group);
    });
    elements['deck-tree'].replaceChildren(fragment);
  }
  function deckCards() {
    if (selectedDeck === ALL_DECKS) return catalog.cards.map(function (card) { return cardsById.get(card.id); });
    return decksById.get(selectedDeck).cardIds.map(function (id) { return cardsById.get(id); });
  }
  function renderWords() {
    var normalized = query.trim().toLocaleLowerCase();
    matchingCards = deckCards().filter(function (card) {
      return !normalized || card.word.toLocaleLowerCase().includes(normalized) || card.definition.toLocaleLowerCase().includes(normalized);
    });
    var fragment = document.createDocumentFragment();
    wordButtons.clear();
    matchingCards.forEach(function (card) {
      var item = node('li');
      var button = node('button', 'word-entry');
      button.type = 'button';
      button.dataset.cardId = card.id;
      button.append(node('span', 'word-entry-name', card.word), node('span', 'word-entry-definition', card.definition),
        node('span', 'word-entry-meta', count(card.exampleCount) + ' 例句'));
      button.addEventListener('click', function () {
        selectCard(card.id, true);
        if (narrow) { setBrowseOpen(false); elements['card-stage'].focus(); }
      });
      item.append(button);
      fragment.append(item);
      wordButtons.set(card.id, button);
    });
    elements['word-list'].replaceChildren(fragment);
    elements['word-count'].textContent = count(matchingCards.length);
    elements['word-empty'].hidden = matchingCards.length > 0;
    elements['clear-search'].hidden = !query;
    deckButtons.forEach(function (button, id) {
      if (id === selectedDeck) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }
  function chooseDeck(id) {
    if (!catalog) return;
    selectedDeck = id;
    renderWords();
    selectCard(wordButtons.has(currentCardId) ? currentCardId : (matchingCards[0] && matchingCards[0].id), true);
  }
  function writeHash() {
    var params = new URLSearchParams();
    if (currentCardId) params.set('card', currentCardId);
    if (selectedDeck !== ALL_DECKS) params.set('deck', selectedDeck);
    var hash = params.toString();
    window.history.replaceState(null, '', window.location.pathname + window.location.search + (hash ? '#' + hash : ''));
  }
  function restoreHash() {
    if (!catalog) return;
    var params = new URLSearchParams(window.location.hash.slice(1));
    var deck = params.get('deck');
    selectedDeck = decksById.has(deck) ? deck : ALL_DECKS;
    query = '';
    elements['word-search'].value = '';
    renderWords();
    var id = params.get('card');
    selectCard(wordButtons.has(id) ? id : (matchingCards[0] && matchingCards[0].id), true);
  }
  function currentIndex() { return matchingCards.findIndex(function (card) { return card.id === currentCardId; }); }
  function updateToolbar() {
    var index = currentIndex();
    var card = cardsById.get(currentCardId);
    var deck = decksById.get(selectedDeck);
    elements['deck-path'].textContent = card ? card.deckName : (deck ? deck.name : '全部卡组');
    elements['card-position'].textContent = index >= 0 ? count(index + 1) + ' / ' + count(matchingCards.length) : '0 / ' + count(matchingCards.length);
    elements['previous-card'].disabled = index <= 0;
    elements['next-card'].disabled = index < 0 || index >= matchingCards.length - 1;
    var ready = activeFrame && activeFrame.ready && activeFrame.cardId === currentCardId;
    var back = ready && activeFrame.flip.getAttribute('aria-pressed') === 'true';
    elements['flip-card'].disabled = !ready;
    elements['flip-card'].setAttribute('aria-pressed', String(Boolean(back)));
    elements['flip-card'].textContent = back ? '返回正面' : '显示答案';
  }
  function disposeFrame() {
    if (!activeFrame) return;
    var old = activeFrame;
    activeFrame = null;
    window.clearTimeout(old.timeout);
    if (old.observer) old.observer.disconnect();
    if (old.document) old.document.removeEventListener('keydown', keyboard);
    old.frame.remove();
  }
  function frameIsCurrent(state) { return activeFrame === state && state.cardId === currentCardId; }
  function constrainCardDocument(cardDocument) {
    cardDocument.documentElement.classList.add('anki-library-card');
    var style = cardDocument.getElementById('anki-library-responsive');
    if (!style) {
      style = cardDocument.createElement('style');
      style.id = 'anki-library-responsive';
      cardDocument.head.append(style);
    }
    style.textContent = responsiveCardCss;
    cardDocument.querySelectorAll('.word').forEach(function (word) {
      var tokens = word.textContent.match(/[A-Za-z]+/g) || [];
      word.classList.toggle('anki-preview-long-word', tokens.some(function (token) { return token.length >= 12; }));
    });
  }
  function failFrame(state) {
    if (!frameIsCurrent(state)) return;
    window.clearTimeout(state.timeout);
    state.ready = false;
    state.frame.hidden = true;
    elements['card-status'].hidden = true;
    elements['card-failure'].hidden = false;
    elements['card-error'].hidden = false;
    elements['card-error'].textContent = '卡片加载失败，请重试。';
    elements['card-stage'].setAttribute('aria-busy', 'false');
    updateToolbar();
  }
  function loadCard(card) {
    disposeFrame();
    elements['card-failure'].hidden = true;
    elements['card-error'].hidden = true;
    elements['card-status'].hidden = false;
    elements['card-status'].textContent = '正在加载 ' + card.word + '…';
    elements['card-stage'].setAttribute('aria-busy', 'true');
    var frame = node('iframe');
    frame.id = 'card-frame';
    frame.title = card.word + ' · 卡片预览';
    frame.setAttribute('allow', 'autoplay');
    // Safari must initialize the subframe in a real layout box to inherit the
    // parent's page zoom. display:none during navigation delays that sync.
    frame.style.visibility = 'hidden';
    frame.setAttribute('aria-hidden', 'true');
    // These are generated, escaped, same-origin card documents. Keeping their
    // native context preserves eudic navigation, audio and target=_blank readers.
    var state = { frame: frame, cardId: card.id, ready: false, flip: null, document: null, observer: null, timeout: null };
    activeFrame = state;
    frame.addEventListener('error', function () { failFrame(state); });
    frame.addEventListener('load', function () {
      if (!frameIsCurrent(state)) return;
      try {
        var cardDocument = frame.contentDocument;
        if (cardDocument && cardDocument.URL === 'about:blank') return;
        requireCondition(cardDocument && cardDocument.URL === card.previewHref, '卡片地址不匹配');
        var flip = cardDocument.getElementById('preview-flip');
        var front = cardDocument.getElementById('preview-front');
        var back = cardDocument.getElementById('preview-back');
        requireCondition(flip && front && back, '卡片缺少翻面控件');
        constrainCardDocument(cardDocument);
        if (state.observer) state.observer.disconnect();
        if (state.document) state.document.removeEventListener('keydown', keyboard);
        state.document = cardDocument;
        state.flip = flip;
        cardDocument.querySelectorAll('.preview-controls').forEach(function (control) { control.hidden = true; });
        // A new frame starts at the front even if a browser restored form state.
        if (flip.getAttribute('aria-pressed') === 'true') flip.click();
        cardDocument.addEventListener('keydown', keyboard);
        state.observer = new MutationObserver(function () { if (frameIsCurrent(state)) updateToolbar(); });
        state.observer.observe(flip, { attributes: true, attributeFilter: ['aria-pressed'] });
        window.clearTimeout(state.timeout);
        state.ready = true;
        frame.hidden = false;
        frame.style.removeProperty('visibility');
        frame.removeAttribute('aria-hidden');
        elements['card-status'].hidden = true;
        elements['card-failure'].hidden = true;
        elements['card-error'].hidden = true;
        elements['card-stage'].setAttribute('aria-busy', 'false');
        updateToolbar();
      } catch (_) { failFrame(state); }
    });
    state.timeout = window.setTimeout(function () { failFrame(state); }, 20000);
    elements['frame-host'].replaceChildren(frame);
    // Resolve the positioned frame's geometry before beginning card navigation.
    frame.getBoundingClientRect();
    frame.src = card.previewHref;
  }
  function selectCard(id, updateHash) {
    var nextId = id || null;
    if (currentCardId && wordButtons.has(currentCardId)) wordButtons.get(currentCardId).removeAttribute('aria-current');
    var changed = currentCardId !== nextId;
    currentCardId = nextId;
    if (currentCardId) {
      var button = wordButtons.get(currentCardId);
      if (button) {
        button.setAttribute('aria-current', 'true');
        if (button.scrollIntoView) button.scrollIntoView({ block: 'nearest' });
      }
      if (changed || !activeFrame) loadCard(cardsById.get(currentCardId));
    } else {
      disposeFrame();
      elements['card-failure'].hidden = true;
      elements['card-error'].hidden = true;
      elements['card-status'].hidden = false;
      elements['card-status'].textContent = catalog && catalog.cards.length ? '没有匹配的卡片。' : '目录中暂无卡片。';
      elements['card-stage'].setAttribute('aria-busy', 'false');
    }
    updateToolbar();
    if (updateHash) writeHash();
  }
  function moveCard(offset) {
    var index = currentIndex();
    var next = index + offset;
    if (index >= 0 && next >= 0 && next < matchingCards.length) selectCard(matchingCards[next].id, true);
  }
  function flipCard() {
    if (!activeFrame || !activeFrame.ready || !frameIsCurrent(activeFrame)) return;
    activeFrame.flip.click();
    updateToolbar();
  }

  function setBrowseOpen(open, restoreFocus) {
    browseOpen = narrow && open;
    elements['browse-panel'].hidden = narrow && !browseOpen;
    elements['browse-backdrop'].hidden = !browseOpen;
    elements['browse-toggle'].setAttribute('aria-expanded', String(browseOpen));
    document.querySelector('.library-header').inert = browseOpen;
    elements['card-stage'].inert = browseOpen;
    elements['catalog-failure'].inert = browseOpen;
    if (browseOpen) {
      elements['browse-panel'].setAttribute('role', 'dialog');
      elements['browse-panel'].setAttribute('aria-modal', 'true');
      elements['word-search'].focus();
    } else {
      elements['browse-panel'].removeAttribute('role');
      elements['browse-panel'].removeAttribute('aria-modal');
      if (restoreFocus) elements['browse-toggle'].focus();
    }
  }
  function keyboard(event) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
    if (event.key === 'Escape' && browseOpen) {
      event.preventDefault();
      setBrowseOpen(false, true);
      return;
    }
    if (event.key === 'Tab' && browseOpen) {
      var controls = Array.from(elements['browse-panel'].querySelectorAll('*')).filter(function (control) {
        if (!control.matches('button:not(:disabled), input:not(:disabled), summary') || control.closest('[hidden]')) return false;
        var details = control.closest('details');
        return !details || details.open || control.tagName === 'SUMMARY';
      });
      var first = controls[0];
      var last = controls[controls.length - 1];
      if (event.shiftKey && event.target === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && event.target === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.shiftKey) return;
    var target = event.target;
    if (target && target.closest && target.closest('input, textarea, select, button, a[href], summary, audio, video, [contenteditable]:not([contenteditable="false"])')) return;
    if (event.repeat) return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      if (!catalog || browseOpen) return;
      event.preventDefault();
      moveCard(event.key === 'ArrowLeft' ? -1 : 1);
    } else if (event.key === ' ' || event.key === 'Spacebar') {
      if (!activeFrame || !activeFrame.ready || browseOpen) return;
      event.preventDefault();
      flipCard();
    }
  }

  async function loadCatalog() {
    var generation = ++fetchGeneration;
    elements['catalog-failure'].hidden = true;
    elements['catalog-error'].hidden = true;
    elements['retry-catalog'].hidden = true;
    elements['library-summary'].textContent = '正在加载目录…';
    try {
      var url = sameOriginUrl(document.body.dataset.catalogUrl, false);
      var response = await fetch(url.href, { credentials: 'same-origin' });
      requireCondition(response.ok, 'HTTP ' + response.status);
      var validated = validateCatalog(await response.json());
      if (generation !== fetchGeneration) return;
      catalog = validated.catalog;
      cardsById = validated.cards;
      decksById = validated.decks;
      elements['library-name'].textContent = catalog.deckName;
      document.title = catalog.deckName + ' · Anki 预览';
      elements['library-summary'].textContent = count(catalog.counts.cards) + ' 张卡 · ' + count(catalog.counts.decks) + ' 个卡组 · ' + count(catalog.counts.examples) + ' 条例句';
      elements['word-search'].disabled = false;
      // Existing cards share this key, so their reader choice persists across cards.
      try {
        var storedReader = localStorage.getItem(readerStorageKey);
        if (storedReader !== 'latex' && storedReader !== 'full-paper') localStorage.setItem(readerStorageKey, catalog.defaultReader);
      } catch (_) {}
      renderDecks();
      restoreHash();
    } catch (error) {
      if (generation !== fetchGeneration) return;
      elements['library-summary'].textContent = '目录不可用';
      elements['catalog-failure'].hidden = false;
      elements['catalog-error'].hidden = false;
      elements['retry-catalog'].hidden = false;
      elements['catalog-error'].textContent = '目录加载失败：' + (error.message || '请检查连接后重试');
      elements['card-status'].textContent = '请重新加载目录。';
      elements['card-stage'].setAttribute('aria-busy', 'false');
      updateToolbar();
    }
  }

  elements['word-search'].addEventListener('input', function () {
    if (!catalog) return;
    query = elements['word-search'].value;
    renderWords();
    selectCard(wordButtons.has(currentCardId) ? currentCardId : (matchingCards[0] && matchingCards[0].id), true);
  });
  elements['clear-search'].addEventListener('click', function () {
    elements['word-search'].value = '';
    elements['word-search'].dispatchEvent(new Event('input', { bubbles: true }));
    elements['word-search'].focus();
  });
  elements['previous-card'].addEventListener('click', function () { moveCard(-1); });
  elements['next-card'].addEventListener('click', function () { moveCard(1); });
  elements['flip-card'].addEventListener('click', flipCard);
  elements['retry-card'].addEventListener('click', function () {
    if (currentCardId) { loadCard(cardsById.get(currentCardId)); updateToolbar(); }
  });
  elements['retry-catalog'].addEventListener('click', loadCatalog);
  elements['browse-toggle'].addEventListener('click', function () { setBrowseOpen(!browseOpen); });
  elements['browse-close'].addEventListener('click', function () { setBrowseOpen(false, true); });
  elements['browse-backdrop'].addEventListener('click', function () { setBrowseOpen(false, true); });
  window.addEventListener('hashchange', restoreHash);
  document.addEventListener('keydown', keyboard);
  if (media) {
    var resize = function (event) { narrow = event.matches; setBrowseOpen(false); };
    if (media.addEventListener) media.addEventListener('change', resize);
    else if (media.addListener) media.addListener(resize);
  } else window.addEventListener('resize', function () { narrow = window.innerWidth <= 900; setBrowseOpen(false); });
  setBrowseOpen(false);
  loadCatalog();
})();
