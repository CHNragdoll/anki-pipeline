// Keep this entry point for CI; sentence playback is now a source-reader jump.
// Isolated DOM/event tests: no browser, profile, audio output, or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../anki_pipeline/templates/script.js'), 'utf8');
const storageKey = 'anki:exam-source-reader:v1';

class Element {
  constructor(tag, className = '', id = '') {
    this.tag = tag;
    this.className = className;
    this.id = id;
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.hidden = false;
  }
  append(...children) {
    for (const child of children) {
      if (child instanceof Element) child.parentElement = this;
      this.children.push(child);
    }
    return this;
  }
  matches(selector) {
    if (selector[0] === '.') return this.className.split(/\s+/).includes(selector.slice(1));
    if (selector[0] === '#') return this.id === selector.slice(1);
    return this.tag === selector;
  }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (node.matches(selector)) return node;
    }
    return null;
  }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (!(child instanceof Element)) continue;
      if (child.matches(selector)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); }
  get classList() {
    return { add: (...names) => { this.className = [...new Set([...this.className.split(/\s+/).filter(Boolean), ...names])].join(' '); } };
  }
  get href() { return this.getAttribute('href') || ''; }
  set href(value) { this.setAttribute('href', value); }
  get title() { return this.getAttribute('title') || ''; }
  set title(value) { this.setAttribute('title', value); }
  get textContent() {
    return this.children.map(child => child instanceof Element ? child.textContent : child).join('');
  }
  set textContent(value) { this.children = [String(value)]; }
  cloneNode() {
    const copy = new Element(this.tag, this.className, this.id);
    copy.append(...this.children.map(child => child instanceof Element ? child.cloneNode() : child));
    return copy;
  }
  replaceWith(value) {
    this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1, value);
  }
}

function exampleSection({ reader = 'latex', links } = {}) {
  const section = new Element('section', 'examples-section');
  const label = new Element('label', 'source-reader-setting');
  const control = new Element('select', 'source-reader');
  control.value = 'latex';
  label.append(control);
  const jumps = (links || [
    { latexUrl: 'http://localhost:8765/latex.htm?anki_sentence=rate%20%26%20rise#block-1',
      fullPaperUrl: 'http://localhost:8765/full-paper.htm?anki_sentence=rate%20%26%20rise#block-1' },
    { latexUrl: 'https://example.test/latex.htm?anki_word=rate#block-2',
      fullPaperUrl: 'https://example.test/full-paper.htm?anki_word=rate#block-2' },
  ]).map(data => {
    const link = new Element('a', 'sentence-jump');
    link.dataset = { ...data, reader };
    link.href = data.latexUrl || 'javascript:unexpected()';
    link.append(new Element('svg'));
    return link;
  });
  section.append(label, ...jumps);
  return { section, label, control, jumps };
}

function wordAudio() {
  const recorded = new Element('div', 'recorded-audio');
  const previewButton = new Element('button', 'preview-word-play replay-button');
  const playIcon = new Element('svg');
  previewButton.append(playIcon);
  const audio = new Element('audio');
  audio.hidden = true;
  audio.playCalls = 0;
  audio.pauseCalls = 0;
  audio.currentTime = 0;
  audio.play = () => { audio.playCalls++; return Promise.resolve(); };
  audio.pause = () => { audio.pauseCalls++; };
  const audioStatus = new Element('span', 'word-audio-status');
  recorded.append(previewButton, audio, audioStatus);
  return { recorded, previewButton, playIcon, audio, audioStatus };
}

function fixture({ preference, blockedStorage = false, ...exampleOptions } = {}) {
  const listeners = new Map();
  const root = new Element('body');
  const front = new Element('section', '', 'preview-front');
  const back = new Element('section', '', 'preview-back');
  back.hidden = true;
  const vocab = new Element('div', 'vocab-front');
  const word = new Element('h1', 'word').append('rate & rise', new Element('br'), 'rates');
  const dictionary = new Element('a', 'dictionary-link');
  const audioBlock = wordAudio();
  vocab.append(word, dictionary, audioBlock.recorded);
  front.append(vocab);
  const examples = exampleSection(exampleOptions);
  back.append(examples.section);
  const flip = new Element('button', '', 'preview-flip');
  const flipIcon = new Element('span');
  flip.setAttribute('aria-pressed', 'false');
  flip.append(flipIcon);
  root.append(front, back, flip);
  const writes = [];
  const storage = new Map(preference === undefined ? [] : [[storageKey, preference]]);
  const window = {};
  const document = {
    querySelectorAll: selector => root.querySelectorAll(selector),
    getElementById: id => root.querySelector('#' + id),
    addEventListener(event, callback) {
      if (!listeners.has(event)) listeners.set(event, []);
      listeners.get(event).push(callback);
    },
  };
  const context = vm.createContext({
    document, window, URL, encodeURIComponent,
    localStorage: {
      getItem(key) {
        if (blockedStorage) throw new Error('storage access denied');
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        if (blockedStorage) throw new Error('storage access denied');
        writes.push([key, value]);
        storage.set(key, value);
      },
    },
    Audio() { assert.fail('sentence audio was removed'); },
    speechSynthesis: { speak() { assert.fail('sentence speech was removed'); } },
  });
  return {
    ...examples, ...audioBlock, root, front, back, flip, flipIcon, dictionary, window, storage, writes, listeners,
    run: () => vm.runInContext(script, context),
    emit(event, target) {
      for (const callback of listeners.get(event) || []) callback({
        target, preventDefault() { assert.fail('jump navigation must retain its native default'); },
      });
    },
  };
}

function expectReader(examples, reader) {
  assert.equal(examples.control.value, reader);
  for (const link of examples.jumps) {
    assert.equal(link.href, reader === 'latex' ? link.dataset.latexUrl : link.dataset.fullPaperUrl);
    assert.match(link.title, reader === 'latex' ? /LaTeX/ : /整卷/);
  }
}

test('configured default, encoded source links, EuDic first line, and word audio stay intact', () => {
  const f = fixture({ reader: 'full-paper' });
  f.run();
  expectReader(f, 'full-paper');
  assert.equal(f.label.hidden, false);
  assert.equal(f.dictionary.href, 'eudic://x-callback-url/searchword?word=rate%20%26%20rise&x-success=anki%3A%2F%2F');
  assert.equal(f.dictionary.getAttribute('aria-label'), '在欧路词典查找 rate & rise');
  assert.equal(f.front.querySelector('audio'), f.audio);
  f.emit('click', f.jumps[0].children[0]);
  assert.equal(f.front.hidden, false, 'jump clicks must not flip the card');
  assert.equal(f.audio.playCalls, 0);
});

test('stored preference overrides the configured reader and changes update every link and title', () => {
  const f = fixture({ reader: 'full-paper', preference: 'latex' });
  const other = exampleSection();
  f.back.append(other.section);
  f.run();
  expectReader(f, 'latex');
  f.control.value = 'full-paper';
  f.emit('change', f.control);
  expectReader(f, 'full-paper');
  expectReader(other, 'full-paper');
  assert.deepEqual(f.writes, [[storageKey, 'full-paper']]);
  f.run();
  assert.equal(f.listeners.get('click').length, 1);
  assert.equal(f.listeners.get('change').length, 1);
  const nextCard = exampleSection();
  f.back.append(nextCard.section);
  f.run();
  expectReader(nextCard, 'full-paper');
  const nextWebview = fixture({ preference: f.storage.get(storageKey) });
  nextWebview.run();
  expectReader(nextWebview, 'full-paper');
});

test('blocked storage preserves the current reader through flips and webview reuse', () => {
  const f = fixture({ blockedStorage: true });
  f.run();
  f.control.value = 'full-paper';
  f.emit('change', f.control);
  expectReader(f, 'full-paper');
  f.emit('click', f.flipIcon);
  assert.equal(f.front.hidden, true);
  assert.equal(f.back.hidden, false);
  assert.equal(f.flip.getAttribute('aria-pressed'), 'true');
  assert.equal(f.flip.textContent, '返回正面');
  expectReader(f, 'full-paper');
  f.emit('click', f.flip);
  assert.equal(f.front.hidden, false);
  assert.equal(f.back.hidden, true);
  assert.equal(f.flip.textContent, '显示答案');
  f.run();
  expectReader(f, 'full-paper');
});

test('invalid preferences are ignored and unrelated events do not change the reader', () => {
  const f = fixture({ reader: 'unknown', preference: 'javascript:unexpected()' });
  f.run();
  expectReader(f, 'latex');
  f.control.value = 'unknown';
  f.emit('change', f.control);
  assert.equal(f.writes.length, 0);
  for (const link of f.jumps) assert.equal(link.href, link.dataset.latexUrl);
  f.emit('change', new Element('select', 'unrelated'));
  f.emit('change', {});
  f.emit('click', {});
  f.emit('click', new Element('button'));
});

test('unsafe or missing source URLs never become active hrefs', () => {
  const unsafe = [
    'javascript:alert(1)', 'data:text/html,unsafe', 'file:///tmp/exam.htm',
    '/relative.htm', '//example.test/latex.htm', 'http://user:password@example.test/latex.htm',
    'https://example.test/\nunsafe', 'http://', undefined,
  ];
  const f = fixture({ links: unsafe.map(latexUrl => ({
    latexUrl, fullPaperUrl: 'https://example.test/full-paper.htm?anki_sentence=a%26b#block-1',
  })) });
  f.run();
  for (const link of f.jumps) {
    assert.equal(link.getAttribute('href'), null);
    assert.equal(link.getAttribute('aria-disabled'), 'true');
  }
  f.control.value = 'full-paper';
  f.emit('change', f.control);
  expectReader(f, 'full-paper');
  for (const link of f.jumps) assert.equal(link.getAttribute('aria-disabled'), null);
  f.jumps[0].dataset.fullPaperUrl = 'https://user@example.test/full-paper.htm';
  f.emit('change', f.control);
  assert.equal(f.jumps[0].getAttribute('href'), null);
});

test('examples without source jumps hide the setting and stop old playback on each refresh', () => {
  const f = fixture({ links: [] });
  let stops = 0;
  f.window.__ankiStopSentence = () => stops++;
  f.run();
  f.run();
  assert.equal(f.label.hidden, true);
  assert.equal(stops, 2);
});

test('preview word play targets its own audio and leaves native Anki replay controls intact', async () => {
  const f = fixture();
  const other = wordAudio();
  f.back.append(other.recorded);
  const native = new Element('a', 'replay-button');
  f.front.append(native);
  f.run();
  f.emit('click', native);
  assert.equal(f.audio.playCalls, 0);
  f.emit('click', f.playIcon);
  await Promise.resolve();
  assert.equal(f.audio.playCalls, 1);
  assert.equal(other.audio.playCalls, 0);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'true');
  assert.match(f.audioStatus.textContent, /正在播放/);
  f.emit('click', other.playIcon);
  assert.equal(f.audio.pauseCalls, 1);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  assert.equal(f.audioStatus.textContent, '');
  assert.equal(other.audio.playCalls, 1);
  other.audio.onended();
  assert.equal(other.previewButton.getAttribute('aria-pressed'), 'false');
  assert.equal(other.audioStatus.textContent, '');
});

test('preview word audio reports rejected or thrown playback and supports retry', async () => {
  const f = fixture();
  f.run();
  f.audio.play = () => Promise.reject(new Error('media unavailable'));
  f.emit('click', f.previewButton);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  assert.match(f.audioStatus.textContent, /单词发音暂不可用/);
  f.audio.play = () => { throw new Error('play blocked'); };
  f.emit('click', f.previewButton);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  assert.match(f.audioStatus.textContent, /单词发音暂不可用/);
  f.audio.play = () => Promise.resolve();
  f.emit('click', f.previewButton);
  await Promise.resolve();
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'true');
  f.audio.onerror();
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  assert.match(f.audioStatus.textContent, /单词发音暂不可用/);
});

test('flips and template reuse stop preview audio and ignore stale asynchronous failures', async () => {
  const f = fixture();
  f.run();
  let rejectPlayback;
  f.audio.play = () => new Promise((resolve, reject) => { rejectPlayback = reject; });
  f.emit('click', f.previewButton);
  const staleError = f.audio.onerror;
  f.audio.currentTime = 2;
  f.emit('click', f.flip);
  assert.equal(f.audio.pauseCalls, 1);
  assert.equal(f.audio.currentTime, 0);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  rejectPlayback(new Error('old card unavailable'));
  staleError();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.audioStatus.textContent, '');
  f.audio.play = () => Promise.resolve();
  f.emit('click', f.previewButton);
  f.run();
  assert.equal(f.audio.pauseCalls, 2);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'false');
  f.emit('click', f.previewButton);
  assert.equal(f.previewButton.getAttribute('aria-pressed'), 'true');
});
