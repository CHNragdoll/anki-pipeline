// Runtime regressions for the outer library UI. The existing card script owns card behavior.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');

const templates = path.resolve(__dirname, '../anki_pipeline/templates');
const htmlPath = path.join(templates, 'library-preview.html');
const scriptPath = path.join(templates, 'library-preview.js');
const cardScript = fs.readFileSync(path.join(templates, 'script.js'), 'utf8');
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

function catalogFixture(cardCount = 7, deckCount = 3) {
  const decks = Array.from({ length: deckCount }, (_, index) => ({
    id: `deck-${index}`, name: `Vocabulary::Unit ${Math.floor(index / 3) + 1}::Lesson ${index + 1}`,
    unit: `Unit ${Math.floor(index / 3) + 1}`, lesson: `Lesson ${index + 1}`, count: 0, cardIds: [],
  }));
  const cards = Array.from({ length: cardCount }, (_, index) => {
    const deck = decks[index % deckCount];
    const card = {
      id: `card-${index}`, word: `word ${index}`, deckId: deck.id, deckName: deck.name,
      unit: deck.unit, lesson: deck.lesson, position: String(index + 1),
      definition: index === 0 ? 'a quiet definition' : `meaning ${index}`,
      exampleCount: index % 4,
      previewUrl: `web-preview/abc123/cards/${index.toString(16).padStart(16, '0')}.html`,
    };
    deck.cardIds.push(card.id);
    deck.count += 1;
    return card;
  });
  return {
    schema: 'anki-web-catalog.v1', deckName: 'Vocabulary', defaultReader: 'latex',
    counts: { cards: cards.length, decks: decks.length, examples: cards.reduce((n, c) => n + c.exampleCount, 0) },
    decks, cards,
  };
}

async function boot(catalog = catalogFixture(), { hash = '', width = 1280, fetchError = null, traceFrameNavigation = false } = {}) {
  const source = fs.existsSync(htmlPath) ? fs.readFileSync(htmlPath, 'utf8') : '<!doctype html><body data-catalog-url="__CATALOG_URL__"></body>';
  const dom = new JSDOM(source.replaceAll('__CATALOG_URL__', 'web-preview/abc123/catalog.json').replaceAll('__ASSET_BASE__', 'web-preview/abc123/'), {
    url: `http://library.test/index.html${hash}`, runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const { window } = dom;
  const listeners = [];
  const media = {
    matches: width <= 900, media: '(max-width: 900px)',
    addEventListener: (_, callback) => listeners.push(callback),
    removeEventListener: (_, callback) => { const i = listeners.indexOf(callback); if (i >= 0) listeners.splice(i, 1); },
    setMatches(matches) { this.matches = matches; listeners.forEach(callback => callback({ matches })); },
  };
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true });
  window.matchMedia = () => media;
  const frameNavigations = [];
  if (traceFrameNavigation) {
    const source = Object.getOwnPropertyDescriptor(window.HTMLIFrameElement.prototype, 'src');
    Object.defineProperty(window.HTMLIFrameElement.prototype, 'src', {
      ...source,
      set(value) {
        frameNavigations.push({ connected: this.isConnected, hidden: this.hidden,
          visibility: this.style.visibility, ariaHidden: this.getAttribute('aria-hidden') });
        source.set.call(this, value);
      },
    });
  }
  window.fetch = async () => {
    if (fetchError) throw new Error(fetchError);
    return { ok: true, json: async () => catalog };
  };
  if (fs.existsSync(scriptPath)) window.eval(fs.readFileSync(scriptPath, 'utf8'));
  await settle();
  return { dom, window, document: window.document, media, frameNavigations, close: () => window.close() };
}

function click(document, selector) {
  const element = document.querySelector(selector);
  assert.ok(element, `Expected ${selector} to be rendered`);
  element.click();
}

function input(context, value) {
  const field = context.document.querySelector('#word-search');
  assert.ok(field, 'Search field is available');
  field.value = value;
  field.dispatchEvent(new context.window.Event('input', { bubbles: true }));
}

function currentFrame(context) { return context.document.querySelector('#card-frame'); }

async function loadFrame(context, content) {
  const frame = currentFrame(context);
  assert.ok(frame, 'A card iframe is available');
  const document = frame.contentDocument;
  document.open();
  document.write(content || '<!doctype html><html><body><div class="preview-controls"><button id="preview-flip" aria-pressed="false">显示答案</button></div><section id="preview-front"><div class="vocab-front"><span class="word">word</span><a class="dictionary-link">欧路</a></div></section><section id="preview-back" hidden><p class="definition">definition</p><section class="examples-section"><label class="source-reader-setting"><select class="source-reader"><option value="latex">LaTeX</option><option value="full-paper">整卷</option></select></label><a class="sentence-jump" data-reader="latex" data-latex-url="http://library.test/latex.htm#sentence" data-full-paper-url="http://library.test/full-paper.htm#sentence" target="_blank">原句</a></section></section></body></html>');
  document.close();
  frame.contentWindow.eval(cardScript);
  frame.dispatchEvent(new context.window.Event('load'));
  await settle();
  return { frame, document, window: frame.contentWindow };
}

function key(window, target, name, properties = {}) {
  const event = new window.KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true, ...properties });
  target.dispatchEvent(event);
  return event;
}

test('renders every card and all nested lessons, including cards without examples', async t => {
  const catalog = catalogFixture(1960, 41);
  const context = await boot(catalog);
  t.after(context.close);
  assert.equal(context.document.querySelectorAll('.word-entry').length, 1960, 'The full library is browsable');
  assert.equal(context.document.querySelectorAll('.deck-entry[data-deck-id]').length, 41);
  assert.equal(context.document.querySelectorAll('.unit-group').length, 14);
  assert.match(context.document.querySelector('.word-entry').textContent, /0 例句/);
  assert.match(context.document.querySelector('#library-summary').textContent, /1,960/);
  assert.equal(currentFrame(context).getAttribute('allow'), 'autoplay');
});

test('searches word and definition inside the selected deck, renders over 100 matches, and clears', async t => {
  const context = await boot(catalogFixture(131, 1));
  t.after(context.close);
  input(context, 'WORD');
  assert.equal(context.document.querySelectorAll('.word-entry').length, 131);
  input(context, 'QUIET');
  assert.equal(context.document.querySelectorAll('.word-entry').length, 1);
  assert.match(currentFrame(context).src, /0000000000000000.html$/);
  input(context, 'nothing matches');
  assert.equal(currentFrame(context), null);
  assert.match(context.document.querySelector('#word-empty').textContent, /没有/);
  assert.equal(context.document.querySelector('#next-card').disabled, true);
  assert.equal(context.document.querySelector('#flip-card').disabled, true);
  click(context.document, '#clear-search');
  assert.equal(context.document.querySelectorAll('.word-entry').length, 131);
  assert.equal(context.document.querySelector('#word-search').value, '');
});

test('completing a searched word opens its exact card while results keep source order', async t => {
  const catalog = catalogFixture(4, 1);
  ['waterfall', 'water', 'waters', 'remote'].forEach((word, index) => { catalog.cards[index].word = word; });
  const context = await boot(catalog);
  t.after(context.close);
  for (const value of ['w', 'wa', 'wat', 'wate']) {
    input(context, value);
    assert.match(currentFrame(context).src, /0000000000000000.html$/, 'Partial searches retain the matching card');
  }
  input(context, 'water');
  assert.match(currentFrame(context).src, /0000000000000001.html$/, 'The complete word opens water instead of waterfall');
  assert.equal(context.window.location.hash, '#card=card-1');
  assert.deepEqual(Array.from(context.document.querySelectorAll('.word-entry'), button => button.dataset.cardId), ['card-0', 'card-1', 'card-2']);
  click(context.document, '#clear-search');
  assert.match(currentFrame(context).src, /0000000000000001.html$/, 'Clearing search keeps the selected card');
  assert.deepEqual(Array.from(context.document.querySelectorAll('.word-entry'), button => button.dataset.cardId), ['card-0', 'card-1', 'card-2', 'card-3']);
});

test('exact search ignores casing and outer spaces, preserves selected duplicates and prefers word over definition', async t => {
  const catalog = catalogFixture(5, 1);
  ['waterfall', 'water', 'Water', 'waters', 'remote'].forEach((word, index) => { catalog.cards[index].word = word; });
  catalog.cards[0].definition = 'remote control';
  const context = await boot(catalog);
  t.after(context.close);
  input(context, ' WATER ');
  assert.match(currentFrame(context).src, /0000000000000001.html$/, 'Without a selected exact duplicate, choose the first in source order');
  click(context.document, '[data-card-id="card-2"]');
  input(context, ' wAtEr ');
  assert.match(currentFrame(context).src, /0000000000000002.html$/, 'A selected exact duplicate is preserved');
  assert.deepEqual(Array.from(context.document.querySelectorAll('.word-entry'), button => button.dataset.cardId), ['card-0', 'card-1', 'card-2', 'card-3']);
  click(context.document, '[data-card-id="card-0"]');
  input(context, 'rem');
  assert.match(currentFrame(context).src, /0000000000000000.html$/, 'Definition matches remain selected for incomplete words');
  input(context, 'remote');
  assert.match(currentFrame(context).src, /0000000000000004.html$/, 'An exact word wins over an earlier matching definition');
  assert.deepEqual(Array.from(context.document.querySelectorAll('.word-entry'), button => button.dataset.cardId), ['card-0', 'card-4']);
});

test('partial search preserves matching selection and exact search stays within the selected deck', async t => {
  const catalog = catalogFixture(4, 2);
  ['waterfall', 'water', 'watery', 'remote'].forEach((word, index) => { catalog.cards[index].word = word; });
  const context = await boot(catalog);
  t.after(context.close);
  click(context.document, '[data-deck-id="deck-0"]');
  input(context, 'water');
  assert.match(currentFrame(context).src, /0000000000000000.html$/, 'An exact word in another deck is not selected');
  assert.deepEqual(Array.from(context.document.querySelectorAll('.word-entry'), button => button.dataset.cardId), ['card-0', 'card-2']);
  click(context.document, '[data-card-id="card-2"]');
  input(context, 'wate');
  assert.match(currentFrame(context).src, /0000000000000002.html$/, 'No exact word keeps the current matching card');
  input(context, 'waterf');
  assert.match(currentFrame(context).src, /0000000000000000.html$/, 'When the selected card no longer matches, choose the first result');
  assert.equal(context.window.location.hash, '#card=card-0&deck=deck-0');
});

test('deck filtering, word selection and next/previous use the displayed sequence', async t => {
  const context = await boot();
  t.after(context.close);
  click(context.document, '[data-deck-id="deck-1"]');
  assert.equal(context.document.querySelectorAll('.word-entry').length, 2);
  assert.match(context.document.querySelector('#deck-path').textContent, /Lesson 2/);
  click(context.document, '[data-card-id="card-1"]');
  const loaded = await loadFrame(context);
  const reader = loaded.document.querySelector('.source-reader');
  const readerLabel = loaded.document.querySelector('.source-reader-setting');
  assert.equal(reader.classList.contains('tappable'), true, 'AnkiMobile must pass taps to the native source-reader select');
  assert.equal(readerLabel.classList.contains('tappable'), true, 'Taps on the reader label must also stay inside the control');
  assert.equal(loaded.document.querySelector('.examples-section').classList.contains('tappable'), false, 'Normal review tap zones outside the reader remain unchanged');
  assert.equal(loaded.document.querySelector('.preview-controls').hidden, true);
  click(context.document, '#flip-card');
  assert.equal(loaded.document.querySelector('#preview-back').hidden, false);
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'true');
  assert.equal(loaded.document.querySelector('.dictionary-link').protocol, 'eudic:');
  loaded.document.querySelector('.source-reader').value = 'full-paper';
  loaded.document.querySelector('.source-reader').dispatchEvent(new loaded.window.Event('change', { bubbles: true }));
  assert.match(loaded.document.querySelector('.sentence-jump').href, /full-paper.htm/);
  click(context.document, '#next-card');
  assert.match(currentFrame(context).src, /0000000000000004.html$/);
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'false');
  const next = await loadFrame(context);
  assert.equal(next.document.querySelector('#preview-front').hidden, false);
  assert.equal(context.document.querySelector('#next-card').disabled, true);
  click(context.document, '#previous-card');
  assert.match(currentFrame(context).src, /0000000000000001.html$/);
  input(context, 'word 4');
  assert.equal(context.document.querySelectorAll('.word-entry').length, 1);
  assert.equal(context.document.querySelector('#previous-card').disabled, true);
  assert.equal(context.document.querySelector('#next-card').disabled, true);
});

test('deep links restore card and deck on refresh and react to hash navigation', async t => {
  const context = await boot(catalogFixture(), { hash: '#card=card-4&deck=deck-1' });
  t.after(context.close);
  assert.equal(context.document.querySelectorAll('.word-entry').length, 2);
  assert.match(currentFrame(context).src, /0000000000000004.html$/);
  assert.equal(context.document.querySelector('[data-card-id="card-4"]').getAttribute('aria-current'), 'true');
  context.window.location.hash = '#card=card-6';
  await settle();
  await settle();
  assert.equal(context.document.querySelectorAll('.word-entry').length, 7);
  assert.match(currentFrame(context).src, /0000000000000006.html$/);
  const refresh = await boot(catalogFixture(), { hash: context.window.location.hash });
  t.after(refresh.close);
  assert.match(currentFrame(refresh).src, /0000000000000006.html$/);
});

test('shortcuts work in both documents and preserve text editing, controls and modifier keys', async t => {
  const context = await boot();
  t.after(context.close);
  const loaded = await loadFrame(context);
  assert.equal(key(context.window, context.document.body, ' ').defaultPrevented, true);
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'true');
  key(loaded.window, loaded.document.body, ' ');
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'false');
  for (const tag of ['input', 'textarea', 'select']) {
    const element = loaded.document.createElement(tag);
    loaded.document.body.append(element);
    assert.equal(key(loaded.window, element, 'ArrowRight').defaultPrevented, false);
  }
  const editable = loaded.document.createElement('div');
  editable.setAttribute('contenteditable', 'true');
  const child = loaded.document.createElement('span');
  editable.append(child);
  loaded.document.body.append(editable);
  assert.equal(key(loaded.window, child, 'ArrowRight').defaultPrevented, false);
  for (const modifier of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) {
    assert.equal(key(context.window, context.document.body, 'ArrowRight', { [modifier]: true }).defaultPrevented, false);
  }
  assert.equal(key(context.window, context.document.querySelector('#word-search'), ' ').defaultPrevented, false);
  assert.match(currentFrame(context).src, /0000000000000000.html$/);
  key(loaded.window, loaded.document.body, 'ArrowRight');
  assert.match(currentFrame(context).src, /0000000000000001.html$/);
});

test('stale iframe loads, errors and mutations cannot change the current toolbar', async t => {
  const context = await boot();
  t.after(context.close);
  const old = await loadFrame(context);
  const oldFlip = old.document.querySelector('#preview-flip');
  click(context.document, '#next-card');
  const current = await loadFrame(context);
  oldFlip.setAttribute('aria-pressed', 'true');
  old.frame.dispatchEvent(new context.window.Event('load'));
  old.frame.dispatchEvent(new context.window.Event('error'));
  await settle();
  assert.equal(context.document.querySelector('#flip-card').disabled, false);
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'false');
  assert.equal(current.frame, currentFrame(context));
  assert.equal(context.document.querySelector('#card-error').hidden, true);
  current.document.querySelector('#preview-flip').click();
  await settle();
  assert.equal(context.document.querySelector('#flip-card').getAttribute('aria-pressed'), 'true');
});

test('narrow layouts begin with the drawer closed and provide keyboard dismissal', async t => {
  const context = await boot(catalogFixture(), { width: 390 });
  t.after(context.close);
  const panel = context.document.querySelector('#browse-panel');
  const toggle = context.document.querySelector('#browse-toggle');
  assert.equal(panel.hidden, true);
  assert.equal(toggle.getAttribute('aria-expanded'), 'false');
  toggle.click();
  assert.equal(panel.hidden, false);
  assert.equal(toggle.getAttribute('aria-expanded'), 'true');
  const first = context.document.querySelector('#browse-close');
  const last = context.document.querySelector('.word-list li:last-child button');
  key(context.window, first, 'Tab', { shiftKey: true });
  assert.equal(context.document.activeElement, last);
  key(context.window, last, 'Tab');
  assert.equal(context.document.activeElement, first);
  key(context.window, context.document.querySelector('#word-search'), 'Escape');
  assert.equal(panel.hidden, true);
  assert.equal(context.document.activeElement, toggle);
  toggle.click();
  click(context.document, '[data-card-id="card-2"]');
  assert.equal(panel.hidden, true);
  context.media.setMatches(false);
  assert.equal(panel.hidden, false);
});

test('fetch and iframe failures are explicit and retryable', async t => {
  const failed = await boot(catalogFixture(), { fetchError: 'offline' });
  t.after(failed.close);
  assert.match(failed.document.querySelector('#catalog-error').textContent, /目录加载失败/);
  assert.equal(failed.document.querySelector('#retry-catalog').hidden, false);
  assert.equal(failed.document.querySelector('#flip-card').disabled, true);
  failed.window.fetch = async () => ({ ok: true, json: async () => catalogFixture() });
  click(failed.document, '#retry-catalog');
  await settle();
  assert.equal(failed.document.querySelectorAll('.word-entry').length, 7);
  const frame = currentFrame(failed);
  frame.dispatchEvent(new failed.window.Event('error'));
  assert.equal(failed.document.querySelector('#card-error').hidden, false);
  assert.match(failed.document.querySelector('#card-error').textContent, /卡片加载失败/);
  click(failed.document, '#retry-card');
  assert.notEqual(currentFrame(failed), frame);
  await loadFrame(failed);
  assert.equal(failed.document.querySelector('#flip-card').disabled, false);
});

test('validates identifiers, deck membership, counts and same-origin generated card URLs', async t => {
  const mutations = [
    c => { c.cards[1].id = c.cards[0].id; },
    c => { c.decks[0].cardIds[0] = 'missing-card'; },
    c => { c.cards[0].deckId = 'missing-deck'; },
    c => { c.counts.cards += 1; },
    c => { c.cards[0].previewUrl = 'https://other.test/web-preview/abc123/cards/abc.html'; },
    c => { c.cards[0].previewUrl = 'javascript:alert(1)'; },
    c => { c.cards[0].previewUrl = '/arbitrary.html'; },
  ];
  for (const mutate of mutations) {
    const catalog = catalogFixture();
    mutate(catalog);
    const context = await boot(catalog);
    t.after(context.close);
    assert.equal(currentFrame(context), null);
    assert.equal(context.document.querySelector('#catalog-error').hidden, false);
  }
});

test('metadata is rendered as text, never as document HTML', async t => {
  const catalog = catalogFixture();
  catalog.deckName = '<img src=x onerror=alert(1)>';
  catalog.cards[0].word = '<svg onload=alert(1)>';
  catalog.cards[0].definition = '<img src=x onerror=alert(1)>';
  const context = await boot(catalog);
  t.after(context.close);
  assert.equal(context.document.querySelectorAll('img, svg').length, 0);
  assert.match(context.document.querySelector('[data-card-id="card-0"]').textContent, /<svg/);
  assert.match(context.document.querySelector('#library-name').textContent, /<img/);
});

test('an empty catalog and a non-card iframe document have explicit states', async t => {
  const empty = await boot(catalogFixture(0, 0));
  t.after(empty.close);
  assert.equal(empty.document.querySelector('#catalog-error').hidden, true);
  assert.equal(currentFrame(empty), null);
  assert.match(empty.document.querySelector('#card-status').textContent, /暂无卡片/);
  assert.equal(empty.document.querySelector('#flip-card').disabled, true);
  const broken = await boot();
  t.after(broken.close);
  const frame = currentFrame(broken);
  frame.contentDocument.open();
  frame.contentDocument.write('<!doctype html><p>404 Not Found</p>');
  frame.contentDocument.close();
  frame.dispatchEvent(new broken.window.Event('load'));
  assert.equal(broken.document.querySelector('#card-error').hidden, false);
  assert.equal(broken.document.querySelector('#flip-card').disabled, true);
});

test('web-only card constraints shrink text and controls without clipping or losing examples', async t => {
  const context = await boot(catalogFixture(), { width: 319 });
  t.after(context.close);
  const unbroken = 'uninterrupted'.repeat(30);
  const examples = Array.from({ length: 25 }, (_, i) => '<li><div class="example-heading"><span class="index-tag">' + (i + 1) + '</span><span class="example-text">' + unbroken + '</span><a class="sentence-jump" href="http://library.test/reader" target="_blank">原句</a></div><span class="example-translation">译文 ' + unbroken + '</span><span class="example-source">/source/' + unbroken + '.html</span></li>').join('');
  const content = '<!doctype html><html><head><style>' + fs.readFileSync(path.join(templates, 'style.css'), 'utf8') + '</style></head><body><div class="preview-controls"><button id="preview-flip" aria-pressed="false">显示答案</button></div><section id="preview-front"><main class="vocab-card vocab-front"><div class="card-meta">' + unbroken + '</div><div class="front-box"><div class="center-container"><div class="word-wrapper"><h1 class="word">' + unbroken + '</h1><a class="dictionary-link">欧路</a></div></div></div></main></section><section id="preview-back" hidden><div class="vocab-card vocab-back"><div class="meaning-section"><div class="field-content">' + unbroken + '<dl class="forms-list"><div class="form-row"><dt>' + unbroken + '</dt><dd>' + unbroken + '</dd></div></dl></div></div><section class="examples-section"><div class="examples-bar"><label class="source-reader-setting">跳转到 <select class="source-reader"><option value="latex">LaTeX 重排</option></select></label></div><ol class="field-content examples">' + examples + '</ol></section></div></section></body></html>';
  const loaded = await loadFrame(context, content);
  const style = element => loaded.window.getComputedStyle(element);
  assert.equal(style(loaded.document.querySelector('.front-box')).boxSizing, 'border-box', 'Padding and borders stay inside card width');
  assert.equal(style(loaded.document.body).maxWidth, '100%');
  for (const selector of ['.word', '.card-meta', '.field-content', '.form-row dt', '.form-row dd', '.example-text', '.example-translation', '.example-source']) {
    assert.equal(style(loaded.document.querySelector(selector)).overflowWrap, 'anywhere', selector + ' can break long text');
    assert.equal(style(loaded.document.querySelector(selector)).whiteSpace, 'normal');
  }
  assert.equal(style(loaded.document.querySelector('.word-wrapper')).display, 'inline-grid');
  assert.equal(style(loaded.document.querySelector('.dictionary-link')).position, 'static', 'Lookup has an in-flow width instead of a negative right offset');
  assert.equal(parseFloat(style(loaded.document.querySelector('.example-text')).minWidth), 0);
  assert.equal(style(loaded.document.querySelector('.sentence-jump')).marginRight, '0px');
  assert.equal(style(loaded.document.querySelector('.source-reader')).maxWidth, '100%');
  for (const element of loaded.document.querySelectorAll('html, body, #preview-front, #preview-back, .vocab-card, .front-box, .meaning-section, .examples, .examples li')) {
    assert.ok(!['hidden', 'clip'].includes(style(element).overflowX), 'Card content is not clipped');
    assert.ok(!['hidden', 'clip'].includes(style(element).overflowY), 'Vertical examples remain readable');
  }
  assert.equal(loaded.document.querySelectorAll('.examples li').length, 25);
  assert.equal(loaded.document.querySelectorAll('#anki-library-responsive').length, 1);
  loaded.frame.dispatchEvent(new context.window.Event('load'));
  assert.equal(loaded.document.querySelectorAll('#anki-library-responsive').length, 1, 'Repeated loads do not stack overrides');
  click(context.document, '#flip-card');
  assert.equal(loaded.document.querySelector('#preview-back').hidden, false);
  assert.equal(loaded.document.querySelector('.example-source').textContent, '/source/' + unbroken + '.html');
});

test('Safari viewer bounds use a positioned containing block instead of nested percentage flex sizing', async t => {
  const context = await boot();
  t.after(context.close);
  const stylesheet = context.document.createElement('style');
  stylesheet.textContent = fs.readFileSync(path.join(templates, 'library-preview.css'), 'utf8');
  context.document.head.append(stylesheet);
  const area = context.window.getComputedStyle(context.document.querySelector('.frame-area'));
  const host = context.window.getComputedStyle(context.document.querySelector('.frame-host'));
  const frame = context.window.getComputedStyle(currentFrame(context));
  assert.equal(area.display, 'block', 'The available reader area does not flex-size its iframe descendants');
  assert.equal(area.position, 'relative');
  assert.equal(host.display, 'block');
  assert.equal(host.position, 'absolute');
  assert.equal(parseFloat(host.getPropertyValue('inset')), 0);
  assert.equal(frame.position, 'absolute');
  assert.equal(parseFloat(frame.getPropertyValue('inset')), 0);
  assert.equal(frame.boxSizing, 'border-box');
  assert.equal(frame.width, '100%');
  assert.equal(frame.height, '100%');
  assert.equal(frame.maxWidth, '100%');
  assert.equal(parseFloat(frame.minWidth), 0);
  for (const style of [area, host, frame]) {
    assert.ok(!['hidden', 'clip'].includes(style.overflowX), 'Bounds are resolved without clipping card content');
    assert.ok(!['hidden', 'clip'].includes(style.overflowY), 'Vertical browsing stays available');
  }
});

test('card navigation starts in a connected layout box and visibility changes after load', async t => {
  const context = await boot(catalogFixture(), { traceFrameNavigation: true });
  t.after(context.close);
  const frame = currentFrame(context);
  assert.equal(frame.hidden, false, 'The child must not initialize while display:none');
  assert.deepEqual(context.frameNavigations[0], { connected: true, hidden: false, visibility: 'hidden', ariaHidden: 'true' });
  const loaded = await loadFrame(context);
  assert.equal(loaded.frame.style.visibility, '');
  assert.equal(loaded.frame.hasAttribute('aria-hidden'), false);
  assert.equal(context.document.querySelector('#card-status').hidden, true);
  click(context.document, '#next-card');
  assert.deepEqual(context.frameNavigations[1], { connected: true, hidden: false, visibility: 'hidden', ariaHidden: 'true' });
  assert.equal(currentFrame(context).hidden, false);
});

test('word text has balanced grid space independently of the lookup button', async t => {
  const context = await boot(catalogFixture(), { width: 319 });
  t.after(context.close);
  const content = '<!doctype html><html><head><style>' + fs.readFileSync(path.join(templates, 'style.css'), 'utf8') + '</style></head><body><button id="preview-flip" aria-pressed="false">显示答案</button><section id="preview-front"><main class="vocab-card vocab-front"><div class="front-box"><div class="center-container"><div class="word-wrapper"><h1 class="word">neighbourhood<br>(美neighborhood)</h1><a class="dictionary-link">欧路</a></div></div></div></main></section><section id="preview-back" hidden></section></body></html>';
  const loaded = await loadFrame(context, content);
  const style = selector => loaded.window.getComputedStyle(loaded.document.querySelector(selector));
  assert.equal(style('.word-wrapper').display, 'inline-grid');
  assert.match(style('.word-wrapper').gridTemplateColumns, /^44px minmax\(0,\s*1fr\) 44px$/);
  assert.equal(style('.word').gridColumn, '2');
  assert.equal(style('.dictionary-link').gridColumn, '3');
  assert.equal(style('.dictionary-link').position, 'static');
  assert.equal(style('.dictionary-link').alignSelf, 'start');
  assert.equal(style('.word-wrapper').maxWidth, '100%');
  assert.equal(style('.word').overflowWrap, 'anywhere');
  assert.equal(loaded.document.querySelector('.word').textContent, 'neighbourhood(美neighborhood)');
});

test('only long English words receive the narrow-screen type adjustment', async t => {
  const context = await boot(catalogFixture(), { width: 319 });
  t.after(context.close);
  const content = '<!doctype html><html><head><style>' + fs.readFileSync(path.join(templates, 'style.css'), 'utf8') + '</style></head><body><button id="preview-flip" aria-pressed="false">显示答案</button><section id="preview-front"><h1 class="word" id="long-word">neighbourhood<br>(美neighborhood)</h1><h1 class="word" id="short-word">ambition</h1><h1 class="word" id="other-short-word">domestic</h1></section><section id="preview-back" hidden><h1 class="word" id="back-word">neighbourhood<br>(美neighborhood)</h1></section></body></html>';
  const loaded = await loadFrame(context, content);
  const long = loaded.document.getElementById('long-word');
  const short = loaded.document.getElementById('short-word');
  const otherShort = loaded.document.getElementById('other-short-word');
  assert.equal(long.classList.contains('anki-preview-long-word'), true);
  assert.equal(loaded.document.getElementById('back-word').classList.contains('anki-preview-long-word'), true);
  assert.equal(short.classList.contains('anki-preview-long-word'), false);
  assert.equal(otherShort.classList.contains('anki-preview-long-word'), false);
  assert.equal(long.querySelectorAll('br').length, 1);
  assert.equal(long.textContent, 'neighbourhood(美neighborhood)');
  assert.equal(loaded.window.getComputedStyle(long).fontSize, '3rem', 'Desktop keeps the existing type size');
  // jsdom does not evaluate viewport media queries. Activate parsed CSSOM
  // rules for this viewport to test their cascade and element scope.
  const activeRules = Array.from(loaded.document.styleSheets).flatMap(sheet => Array.from(sheet.cssRules))
    .filter(rule => rule.media && /max-width:\s*480px/.test(rule.media.mediaText))
    .flatMap(rule => Array.from(rule.cssRules).map(child => child.cssText));
  const active = loaded.document.createElement('style');
  active.textContent = activeRules.join('\n');
  loaded.document.head.append(active);
  assert.equal(loaded.window.getComputedStyle(short).fontSize, '2.3rem');
  assert.equal(loaded.window.getComputedStyle(otherShort).fontSize, '2.3rem');
  const adjustment = Array.from(active.sheet.cssRules).find(rule => rule.selectorText.includes('.anki-preview-long-word'));
  assert.equal(adjustment.style.fontSize, '6vw');
  assert.equal(loaded.window.getComputedStyle(long).fontSize, '6vw');
  assert.equal(long.matches(adjustment.selectorText), true);
  assert.equal(short.matches(adjustment.selectorText), false);
  assert.equal(otherShort.matches(adjustment.selectorText), false);
});
