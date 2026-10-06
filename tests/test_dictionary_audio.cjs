// Dictionary playback must be entirely local and retain one choice across cards.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../anki_pipeline/templates/script.js'), 'utf8');
const storageKey = 'anki-dictionary-pronunciation-v1';

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
      if (child.parentElement) {
        const siblings = child.parentElement.children;
        siblings.splice(siblings.indexOf(child), 1);
      }
      child.parentElement = this; this.children.push(child);
    }
    return this;
  }
  insertBefore(child, reference) {
    if (child.parentElement) {
      const siblings = child.parentElement.children;
      siblings.splice(siblings.indexOf(child), 1);
    }
    child.parentElement = this;
    this.children.splice(reference ? this.children.indexOf(reference) : this.children.length, 0, child);
  }
  matches(selector) {
    if (selector.startsWith('.')) return this.className.split(/\s+/).includes(selector.slice(1));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    return this.tag === selector;
  }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node;
    return null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [
      ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  setAttribute(key, value) { this.attributes.set(key, String(value)); }
  getAttribute(key) { return this.attributes.get(key) ?? null; }
  removeAttribute(key) { this.attributes.delete(key); }
}

function dictionaryAudio({ sources = ['webster', 'oxford'], defaultSource = 'oxford', fallback = {} } = {}) {
  const block = new Element('div', 'dictionary-word-audio');
  block.dataset.defaultSource = defaultSource;
  for (const [requested, actual] of Object.entries(fallback)) block.setAttribute('data-fallback-' + requested, actual);
  const selector = new Element('select', 'dictionary-audio-source');
  const setting = new Element('label', 'dictionary-audio-setting').append(selector);
  const button = new Element('button', 'preview-word-play replay-button');
  const icon = new Element('svg');
  button.append(icon);
  const status = new Element('span', 'word-audio-status');
  const audios = new Map(sources.map(source => {
    const audio = new Element('audio');
    audio.dataset.dictionarySource = source;
    audio.setAttribute('src', source + '-word.mp3');
    audio.hidden = true;
    audio.playCalls = 0;
    audio.pauseCalls = 0;
    audio.currentTime = 0;
    audio.play = () => { audio.playCalls++; return Promise.resolve(); };
    audio.pause = () => { audio.pauseCalls++; };
    return [source, audio];
  }));
  block.append(setting, button, ...audios.values(), status);
  return { block, selector, setting, button, icon, status, audios };
}

function fixture({ preference, blockedStorage = false, blockedWrites = false, ...audioOptions } = {}) {
  const root = new Element('body');
  const front = new Element('section', '', 'preview-front');
  const back = new Element('section', '', 'preview-back');
  back.hidden = true;
  const flip = new Element('button', '', 'preview-flip');
  flip.setAttribute('aria-pressed', 'false');
  const first = dictionaryAudio(audioOptions);
  front.append(first.block);
  root.append(front, back, flip);
  const events = new Map();
  const windowEvents = new Map();
  const add = (map, event, callback) => {
    if (!map.has(event)) map.set(event, []);
    map.get(event).push(callback);
  };
  const storage = new Map(preference === undefined ? [] : [[storageKey, preference]]);
  const writes = [];
  const window = { addEventListener: (event, callback) => add(windowEvents, event, callback) };
  const context = vm.createContext({
    window, URL, encodeURIComponent,
    document: {
      querySelectorAll: selector => root.querySelectorAll(selector),
      getElementById: id => root.querySelector('#' + id),
      addEventListener: (event, callback) => add(events, event, callback),
    },
    localStorage: {
      getItem(key) { if (blockedStorage) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem(key, value) {
        if (blockedStorage || blockedWrites) throw Error('blocked');
        writes.push([key, value]); storage.set(key, value);
      },
    },
    fetch() { assert.fail('dictionary playback must not query a server'); },
    Audio() { assert.fail('play the packaged media rather than a remote fallback'); },
    speechSynthesis: { speak() { assert.fail('dictionary pronunciation must not use TTS'); } },
  });
  return {
    ...first, root, front, back, flip, window, storage, writes, events, windowEvents,
    run: () => vm.runInContext(script, context),
    emit(event, target) { for (const callback of events.get(event) || []) callback({ target }); },
    emitStorage(value) {
      if (value === null) storage.delete(storageKey); else storage.set(storageKey, value);
      for (const callback of windowEvents.get('storage') || []) callback({ key: storageKey, newValue: value });
    },
  };
}

test('Oxford is selected by source identity even when Webster media comes first', async () => {
  const f = fixture();
  f.run();
  assert.equal(f.selector.value, 'oxford');
  f.emit('click', f.icon);
  await Promise.resolve();
  assert.equal(f.audios.get('oxford').playCalls, 1);
  assert.equal(f.audios.get('webster').playCalls, 0);
  assert.match(f.status.textContent, /牛津/);
});

test('pronunciation setting moves into the card heading before metadata on both faces and remains functional', () => {
  const f = fixture();
  function wrap(cardAudio, face) {
    const card = new Element('main', 'vocab-card vocab-front');
    const heading = new Element('div', 'card-heading');
    const metadata = new Element('div', 'card-meta');
    const frontBox = new Element('div', 'front-box').append(cardAudio.block);
    heading.append(metadata);
    card.append(heading, frontBox);
    face.append(card);
    return { card, heading, metadata, frontBox };
  }
  const frontCard = wrap(f, f.front);
  const answerAudio = dictionaryAudio();
  const answerCard = wrap(answerAudio, f.back);
  f.run();
  assert.equal(f.setting.parentElement, frontCard.heading);
  assert.equal(answerAudio.setting.parentElement, answerCard.heading);
  assert.deepEqual(frontCard.heading.children, [f.setting, frontCard.metadata]);
  assert.equal(frontCard.frontBox.querySelector('.dictionary-audio-source'), null);
  assert.equal(f.button.parentElement, f.block, 'only the source control leaves the centered audio block');
  f.selector.value = 'webster';
  f.emit('change', f.selector);
  assert.equal(answerAudio.selector.value, 'webster');
  f.emit('click', f.button);
  assert.equal(f.audios.get('webster').playCalls, 1);
  f.emit('click', f.flip);
  f.run();
  assert.equal(f.selector.value, 'webster');
  assert.equal(frontCard.heading.children.length, 2, 'refreshes do not duplicate the moved control');
});

test('one selection is persisted and applied to both card faces and a new card webview', () => {
  const f = fixture();
  const answer = dictionaryAudio();
  f.back.append(answer.block);
  f.run();
  f.selector.value = 'webster';
  f.emit('change', f.selector);
  assert.equal(answer.selector.value, 'webster');
  assert.deepEqual(f.writes, [[storageKey, 'webster']]);
  f.run();
  assert.equal(f.events.get('click').length, 1);
  assert.equal(f.events.get('change').length, 1);
  assert.equal(f.windowEvents.get('storage').length, 1);
  const next = fixture({ preference: f.storage.get(storageKey) });
  next.run();
  assert.equal(next.selector.value, 'webster');
  next.emit('click', next.button);
  assert.equal(next.audios.get('webster').playCalls, 1);
});

test('blocked storage preserves the active source through a flip and template reuse', () => {
  const f = fixture({ blockedStorage: true });
  f.run();
  f.selector.value = 'webster';
  f.emit('change', f.selector);
  f.emit('click', f.button);
  f.emit('click', f.flip);
  assert.equal(f.front.hidden, true);
  assert.equal(f.back.hidden, false);
  assert.equal(f.audios.get('webster').pauseCalls, 1);
  f.run();
  assert.equal(f.selector.value, 'webster');
});

test('a write-only storage failure does not restore an older persisted source on the same webview', () => {
  const f = fixture({ preference: 'oxford', blockedWrites: true });
  f.run();
  f.selector.value = 'webster';
  f.emit('change', f.selector);
  assert.equal(f.selector.value, 'webster');
  f.run();
  assert.equal(f.selector.value, 'webster');
  f.emit('click', f.button);
  assert.equal(f.audios.get('webster').playCalls, 1);
});

test('missing selected pronunciation reports its source and never plays the other recording', () => {
  const f = fixture({ sources: ['oxford'], preference: 'webster' });
  f.run();
  assert.equal(f.selector.value, 'webster');
  assert.equal(f.button.disabled, true);
  assert.match(f.status.textContent, /韦氏.*暂无/);
  f.emit('click', f.button);
  assert.equal(f.audios.get('oxford').playCalls, 0);
  f.selector.value = 'oxford';
  f.emit('change', f.selector);
  assert.equal(f.button.disabled, false);
  assert.equal(f.status.textContent, '');
  f.emit('click', f.button);
  assert.equal(f.audios.get('oxford').playCalls, 1);
});

test('an explicit local fallback keeps the requested global source and permanently identifies the actual recording', () => {
  const f = fixture({ sources: ['oxford'], preference: 'webster', fallback: { webster: 'oxford' } });
  const note = '韦氏未收录，此词使用牛津录音';
  f.run();
  assert.equal(f.selector.value, 'webster');
  assert.equal(f.button.disabled, false);
  assert.equal(f.status.textContent, note);
  assert.equal(f.button.getAttribute('aria-label'), '播放牛津单词发音（韦氏未收录）');
  f.emit('click', f.button);
  assert.equal(f.audios.get('oxford').playCalls, 1);
  assert.match(f.status.textContent, /韦氏未收录.*牛津.*正在播放/);
  f.audios.get('oxford').onended();
  assert.equal(f.status.textContent, note);
  f.emit('click', f.flip);
  assert.equal(f.status.textContent, note);
  f.run();
  assert.equal(f.selector.value, 'webster');
  assert.equal(f.status.textContent, note);
  assert.equal(f.writes.length, 0, 'the per-word exception must not replace the global preference');
});

test('exact-source audio wins over a fallback and invalid or unrecorded fallback declarations remain disabled', () => {
  const exact = fixture({ fallback: { oxford: 'webster' } });
  exact.run();
  exact.emit('click', exact.button);
  assert.equal(exact.audios.get('oxford').playCalls, 1);
  assert.equal(exact.audios.get('webster').playCalls, 0);
  assert.doesNotMatch(exact.status.textContent, /未收录/);
  for (const actual of ['invalid', 'webster', 'oxford']) {
    const missing = fixture({ sources: actual === 'oxford' ? [] : ['oxford'], preference: 'webster', fallback: { webster: actual } });
    missing.run();
    assert.equal(missing.button.disabled, true);
    assert.match(missing.status.textContent, /韦氏.*暂无/);
    missing.emit('click', missing.button);
    for (const audio of missing.audios.values()) assert.equal(audio.playCalls, 0);
  }
});

test('fallback playback failures identify the real source and retain the exception after retry', async () => {
  const f = fixture({ sources: ['webster'], fallback: { oxford: 'webster' } });
  const audio = f.audios.get('webster');
  f.run();
  audio.play = () => Promise.reject(Error('missing bundled recording'));
  f.emit('click', f.button);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(f.status.textContent, /韦氏发音暂不可用/);
  assert.match(f.status.textContent, /牛津未收录.*韦氏录音/);
  audio.play = () => Promise.resolve();
  f.emit('click', f.button);
  f.emit('click', f.flip);
  assert.equal(f.status.textContent, '牛津未收录，此词使用韦氏录音');
});

test('switching source stops playback and stale errors cannot overwrite the new choice', async () => {
  const f = fixture();
  f.run();
  let rejectPlayback;
  f.audios.get('oxford').play = () => new Promise((_, reject) => { rejectPlayback = reject; });
  f.emit('click', f.button);
  const staleError = f.audios.get('oxford').onerror;
  f.selector.value = 'webster';
  f.emit('change', f.selector);
  assert.equal(f.audios.get('oxford').pauseCalls, 1);
  f.emit('click', f.button);
  rejectPlayback(Error('stale media'));
  staleError();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(f.button.getAttribute('aria-pressed'), 'true');
  assert.match(f.status.textContent, /韦氏.*正在播放/);
  assert.equal(f.audios.get('webster').playCalls, 1);
});

test('media failure identifies the chosen dictionary and permits retry', async () => {
  const f = fixture({ preference: 'webster' });
  f.run();
  f.audios.get('webster').play = () => Promise.reject(Error('missing file'));
  f.emit('click', f.button);
  await new Promise(resolve => setImmediate(resolve));
  assert.match(f.status.textContent, /韦氏发音暂不可用/);
  assert.equal(f.button.getAttribute('aria-pressed'), 'false');
  assert.equal(f.audios.get('oxford').playCalls, 0);
  f.audios.get('webster').play = () => Promise.resolve();
  f.emit('click', f.button);
  assert.equal(f.button.getAttribute('aria-pressed'), 'true');
  f.audios.get('webster').onended();
  assert.equal(f.status.textContent, '');
});

test('same-origin storage updates refresh both selectors and stop the previous source', () => {
  const f = fixture();
  const other = dictionaryAudio();
  f.back.append(other.block);
  f.run();
  f.emit('click', f.button);
  f.emitStorage('webster');
  assert.equal(f.selector.value, 'webster');
  assert.equal(other.selector.value, 'webster');
  assert.equal(f.audios.get('oxford').pauseCalls, 1);
  f.emitStorage(null);
  assert.equal(f.selector.value, 'oxford');
});

test('invalid preferences and empty recordings do not create fallback playback', () => {
  const f = fixture({ preference: 'invalid', defaultSource: 'invalid' });
  f.audios.get('oxford').setAttribute('src', '');
  f.run();
  assert.equal(f.selector.value, 'oxford');
  assert.match(f.status.textContent, /牛津.*暂无/);
  f.selector.value = 'invalid';
  f.emit('change', f.selector);
  assert.equal(f.selector.value, 'oxford');
  assert.equal(f.writes.length, 0);
  f.emit('click', f.button);
  assert.equal(f.audios.get('webster').playCalls, 0);
});

test('Oxford-enriched cards use one meaning section while unenriched cards retain their headings', () => {
  const f = fixture();
  const meanings = new Element('div', 'meaning-section');
  const primary = new Element('section', 'primary-definition');
  const title = new Element('h2', 'field-title');
  title.textContent = '核心释义';
  primary.append(title, new Element('div', 'dictionary-definition'));
  const secondary = new Element('section', 'secondary-definition');
  meanings.append(primary, secondary);
  f.back.append(meanings);
  f.run();
  assert.equal(title.textContent, '牛津释义');
  assert.equal(secondary.hidden, true);
  assert.equal(primary.getAttribute('data-dictionary-definition'), 'oxford');
  primary.children.pop();
  f.run();
  assert.equal(title.textContent, '核心释义');
  assert.equal(secondary.hidden, false);
});

test('a declared wordbook definition has a truthful heading and still removes the obsolete meaning split', () => {
  const f = fixture();
  const meanings = new Element('div', 'meaning-section');
  const primary = new Element('section', 'primary-definition');
  const title = new Element('h2', 'field-title');
  const definition = new Element('div', 'dictionary-definition');
  definition.setAttribute('data-dictionary', 'wordbook');
  primary.append(title, definition);
  const secondary = new Element('section', 'secondary-definition');
  meanings.append(primary, secondary);
  f.back.append(meanings);
  f.run();
  assert.equal(title.textContent, '词表释义（牛津未收录）');
  assert.equal(secondary.hidden, true);
  assert.equal(primary.getAttribute('data-definition-source'), 'wordbook');
});

test('a declared ECDICT fallback uses a truthful heading across flips without another meaning section', () => {
  const f = fixture();
  const meanings = new Element('div', 'meaning-section');
  const primary = new Element('section', 'primary-definition');
  const title = new Element('h2', 'field-title');
  const definition = new Element('div', 'dictionary-definition');
  definition.setAttribute('data-dictionary', 'ecdict');
  primary.append(title, definition);
  const secondary = new Element('section', 'secondary-definition');
  meanings.append(primary, secondary);
  f.back.append(meanings);
  f.run();
  f.emit('click', f.flip);
  f.run();
  assert.equal(title.textContent, 'ECDICT 释义（牛津未收录）');
  assert.equal(secondary.hidden, true);
  assert.equal(primary.getAttribute('data-definition-source'), 'ecdict');
  definition.setAttribute('data-dictionary', 'oxford');
  f.run();
  assert.equal(title.textContent, '牛津释义', 'a reused view keeps its actual dictionary source');
  assert.equal(primary.getAttribute('data-definition-source'), 'oxford');
});

test('reviewed definitions without frequency retain their true heading across flips and upgrades', () => {
  const f = fixture();
  const meanings = new Element('div', 'meaning-section');
  const primary = new Element('section', 'primary-definition');
  const title = new Element('h2', 'field-title');
  const definition = new Element('div', 'dictionary-definition');
  definition.setAttribute('data-dictionary', 'reviewed');
  definition.setAttribute('data-definition-heading', 'Collins 释义（英文校译）');
  primary.append(title, definition);
  meanings.append(primary); f.back.append(meanings);
  for (let face = 0; face < 3; face++) {
    f.run();
    assert.equal(title.textContent, 'Collins 释义（英文校译）');
    assert.equal(primary.getAttribute('data-definition-source'), 'reviewed');
    f.emit('click', f.flip);
  }
  definition.removeAttribute('data-definition-heading'); f.run();
  assert.equal(title.textContent, '核对后的释义');
  definition.setAttribute('data-dictionary', 'oxford'); f.run();
  assert.equal(title.textContent, '牛津释义');
});

test('grouped inflections and derived words retain separate titles without repeating the old outer heading', () => {
  const f = fixture();
  const forms = new Element('section', 'forms-section');
  const outerHeading = new Element('h2', 'field-title');
  const groups = new Element('div', 'dictionary-form-groups');
  const inflections = new Element('section', 'dictionary-inflections');
  const inflectionHeading = new Element('h3');
  const derived = new Element('section', 'dictionary-derived');
  const derivedHeading = new Element('h3');
  inflections.append(inflectionHeading, new Element('div', 'forms-list'));
  derived.append(derivedHeading, new Element('div', 'forms-list'));
  groups.append(inflections, derived);
  forms.append(outerHeading, groups);
  f.back.append(forms);
  f.run();
  assert.equal(outerHeading.hidden, true);
  assert.equal(inflectionHeading.hidden, false);
  assert.equal(derivedHeading.hidden, false);
  f.emit('click', f.flip);
  f.run();
  assert.equal(outerHeading.hidden, true);
  forms.children.pop();
  forms.append(new Element('div', 'forms-list'));
  f.run();
  assert.equal(outerHeading.hidden, false, 'legacy cards still need their original forms heading');
});
