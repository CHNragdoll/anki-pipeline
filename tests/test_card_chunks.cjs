// Observable delegated pointer/touch behavior, independent of live data/profile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');
const { JSDOM } = require('jsdom');

class Element {
  constructor(tag, classes = '', data = {}) {
    this.tag = tag;
    this.classes = new Set(classes.split(/\s+/).filter(Boolean));
    this.dataset = data;
    this.children = [];
    this.classList = {
      add: name => this.classes.add(name), remove: name => this.classes.delete(name),
      contains: name => this.classes.has(name),
      toggle: (name, force) => force ? this.classes.add(name) : this.classes.delete(name),
    };
  }
  append(...children) {
    children.forEach(child => { child.parentElement = this; this.children.push(child); });
    return this;
  }
  matches(selector) {
    return selector.split(',').some(part => {
      part = part.trim();
      return part[0] === '.' ? this.classes.has(part.slice(1)) : this.tag === part;
    });
  }
  closest(selector) {
    for (let node = this; node; node = node.parentElement) if (node.matches(selector)) return node;
    return null;
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [ ...(child.matches(selector) ? [child] : []),
                                           ...child.querySelectorAll(selector) ]);
  }
}

function chunk(side, ids) {
  return new Element('span', 'card-chunk', { chunkSide: side, chunkIds: ids });
}

function example() {
  const root = new Element('li', 'example-card');
  const en = chunk('en', '0'), target = new Element('mark', 'target-word');
  en.append(target);
  const enContinuation = chunk('en', '0'), enOther = chunk('en', '1');
  const zh = chunk('zh', '0'), zhOther = chunk('zh', '1'), zhSeparate = chunk('zh', '0');
  const overlapping = chunk('en', '2 0'), zhOverlap = chunk('zh', '0 2');
  const link = new Element('a'), icon = new Element('svg');
  link.append(icon);
  root.append(en, enContinuation, enOther, zh, zhSeparate, zhOther, overlapping, zhOverlap, link);
  return { root, en, target, enContinuation, enOther, zh, zhOther, zhSeparate, overlapping, zhOverlap, link, icon };
}

function fixture(pointerEvents = true) {
  const body = new Element('body');
  const first = example(), second = example();
  const button = new Element('button'), blank = new Element('div');
  body.append(first.root, second.root, button, blank);
  const listeners = new Map();
  const window = pointerEvents ? { PointerEvent() {} } : {};
  const document = {
    querySelectorAll: selector => body.querySelectorAll(selector),
    addEventListener(type, handler, options) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push({ handler, capture: options === true || options?.capture });
    },
  };
  const context = vm.createContext({ window, document, Date });
  const asset = path.join(__dirname, '../anki_pipeline/templates/card-chunks.js');
  const run = () => vm.runInContext(fs.readFileSync(asset, 'utf8'), context);
  return {
    first, second, body, button, blank, listeners, run,
    emit(type, target, options = {}) {
      const event = { target, pointerType: type.startsWith('pointer') ? 'mouse' : undefined,
        defaultPrevented: false, stopped: false,
        preventDefault() { this.defaultPrevented = true; },
        stopPropagation() { this.stopped = true; }, ...options };
      for (const {handler} of listeners.get(type) || []) handler(event);
      return event;
    },
  };
}

function active(element) { return element.classList.contains('card-chunk-active'); }

test('mouse hover activates every explicit correspondence only in its own example and clears on leave', () => {
  const f = fixture(); f.run();
  assert.equal(active(f.first.zh), false);
  f.emit('pointerover', f.first.target);
  for (const node of [f.first.en, f.first.enContinuation, f.first.zh, f.first.zhSeparate, f.first.zhOverlap]) assert.equal(active(node), true);
  for (const node of [f.first.enOther, f.first.zhOther, f.second.en, f.second.zh]) assert.equal(active(node), false);
  f.emit('pointerout', f.first.target, { relatedTarget: f.first.enContinuation });
  assert.equal(active(f.first.zh), true, 'movement within the same chunk must retain emphasis');
  f.emit('pointerout', f.first.enContinuation, { relatedTarget: f.blank });
  assert.equal(active(f.first.zh), false);
  f.emit('pointerover', f.first.zh);
  for (const node of [f.first.en, f.first.enContinuation, f.first.zh, f.first.zhSeparate]) assert.equal(active(node), true);
  for (const node of [f.first.enOther, f.first.zhOther, f.second.en, f.second.zh]) assert.equal(active(node), false);
  f.emit('pointerout', f.first.zh, { relatedTarget: f.first.enContinuation });
  assert.equal(active(f.first.en), true, 'moving across the same pair retains emphasis');
  f.emit('pointerout', f.first.enContinuation, { relatedTarget: f.blank });
  assert.equal(active(f.first.en), false);
  f.emit('pointerover', f.first.zhOverlap);
  for (const node of [f.first.en, f.first.enContinuation, f.first.overlapping,
                      f.first.zh, f.first.zhSeparate, f.first.zhOverlap]) assert.equal(active(node), true);
  for (const node of [f.first.enOther, f.first.zhOther, f.second.en, f.second.zh]) assert.equal(active(node), false);
  f.first.zhSeparate.dataset.chunkIds = '2 0';
  f.emit('pointerout', f.first.zhOverlap, { relatedTarget: f.first.zhSeparate });
  assert.equal(active(f.first.en), true, 'reordered IDs retain the same hover group');
  f.emit('pointerout', f.first.zhSeparate, { relatedTarget: f.blank });
  assert.equal(active(f.first.en), false);
});

test('touch and pen pointerover do not preactivate a chunk before its click toggle', () => {
  const f = fixture(); f.run();
  for (const pointerType of ['touch', 'pen']) {
    f.emit('pointerover', f.first.en, { pointerType });
    assert.equal(active(f.first.zh), false);
    f.emit('pointerover', f.first.zh, { pointerType });
    assert.equal(active(f.first.en), false);
  }
  const click = f.emit('click', f.first.target, { pointerType: 'touch' });
  assert.equal(active(f.first.zh), true);
  assert.equal(click.defaultPrevented, true);
  assert.equal(click.stopped, true, 'chunk taps must not bubble into card flip');
  assert.equal(f.listeners.get('click')[0].capture, true);
  f.emit('pointerout', f.first.en, { pointerType: 'touch' });
  assert.equal(active(f.first.zh), true);
  f.emit('click', f.first.enContinuation, { pointerType: 'touch' });
  assert.equal(active(f.first.zh), false, 'tapping any segment of the same chunk toggles off');
});

test('Chinese tap uses every existing index; repeated and blank taps clear the prior selection', () => {
  const f = fixture(); f.run();
  f.emit('pointerover', f.first.zh);
  assert.equal(active(f.first.en), true);
  f.emit('click', f.first.zh);
  assert.equal(active(f.first.en), true);
  f.emit('pointerout', f.first.zh, { relatedTarget: f.blank });
  assert.equal(active(f.first.en), true, 'click locks a Chinese hovered pair');
  f.emit('click', f.first.zhSeparate);
  assert.equal(active(f.first.en), false);
  f.emit('pointerover', f.first.zhOverlap);
  const multi = f.emit('click', f.first.zhOverlap);
  assert.equal(multi.defaultPrevented, true);
  assert.equal(multi.stopped, true);
  assert.equal(active(f.first.en), true);
  assert.equal(active(f.first.overlapping), true);
  assert.equal(active(f.second.en), false);
  f.emit('pointerout', f.first.zhOverlap, { relatedTarget: f.blank });
  assert.equal(active(f.first.en), true, 'multi-ID click stays locked after pointer exit');
  f.first.zhSeparate.dataset.chunkIds = '2 0';
  f.emit('click', f.first.zhSeparate);
  assert.equal(active(f.first.en), false);
  assert.equal(active(f.first.overlapping), false, 'reordered IDs identify the same selected set');
  f.emit('click', f.first.en);
  f.emit('click', f.second.enOther);
  assert.equal(active(f.first.en), false);
  assert.equal(active(f.second.zhOther), true);
  const clear = f.emit('click', f.blank);
  assert.equal(active(f.second.zhOther), false);
  assert.equal(clear.defaultPrevented, false);
  assert.equal(clear.stopped, false);
});

test('existing overlapping English indices use the finest authored chunk without text matching', () => {
  const f = fixture(); f.run();
  f.emit('click', f.first.overlapping);
  assert.equal(active(f.first.overlapping), true);
  assert.equal(active(f.first.zhOverlap), true);
  assert.equal(active(f.first.zh), false, 'broader authored chunk must not be selected');
});

test('links, audio/buttons, unrelated text, and escape keep their native behavior and clear emphasis', () => {
  const f = fixture(); f.run();
  // Defend even a future interactive element nested inside annotated text.
  f.first.en.append(f.first.link);
  const zhLink = new Element('a'), zhIcon = new Element('svg');
  zhLink.append(zhIcon); f.first.zh.append(zhLink);
  f.emit('pointerover', zhIcon);
  assert.equal(active(f.first.en), false);
  for (const node of [f.first.icon, zhIcon, f.button, f.blank]) {
    f.emit('click', f.first.en);
    const event = f.emit('click', node);
    assert.equal(event.defaultPrevented, false);
    assert.equal(event.stopped, false);
    assert.equal(active(f.first.zh), false);
  }
  f.emit('click', f.first.en);
  f.emit('keydown', f.first.en, { key: 'Escape' });
  assert.equal(active(f.first.zh), false);
  f.emit('click', {});
});

test('Anki webview reuse binds once and clears both old and newly rendered state', () => {
  const f = fixture(); f.run();
  f.emit('click', f.first.en);
  assert.equal(active(f.first.zh), true);
  f.run();
  assert.equal(active(f.first.zh), false);
  for (const list of f.listeners.values()) assert.equal(list.length, 1);
  const next = example(); f.body.append(next.root);
  f.emit('click', next.en);
  assert.equal(active(next.zh), true);
  f.run();
  assert.equal(active(next.zh), false);
});

test('older mouse-event webviews support hover but suppress synthetic mouse hover after touch', () => {
  const f = fixture(false); f.run();
  f.emit('mouseover', f.first.en);
  assert.equal(active(f.first.zh), true);
  f.emit('mouseout', f.first.en, { relatedTarget: null });
  assert.equal(active(f.first.zh), false);
  f.emit('mouseover', f.first.zh);
  assert.equal(active(f.first.en), true);
  f.emit('mouseout', f.first.zh, { relatedTarget: null });
  assert.equal(active(f.first.en), false);
  f.emit('touchstart', f.first.en);
  f.emit('mouseover', f.first.en);
  assert.equal(active(f.first.zh), false);
  f.emit('mouseover', f.first.zh);
  assert.equal(active(f.first.en), false);
  f.emit('click', f.first.en);
  assert.equal(active(f.first.zh), true);
  f.emit('click', f.first.en);
  assert.equal(active(f.first.zh), false);
});

test('actual shared rendered preview keeps target mark, clears on flip, and stops chunk taps before other document handlers', t => {
  const repository = path.resolve(__dirname, '..');
  const result = spawnSync(path.join(repository, '.venv/bin/python'), ['-c',
    'import sys; sys.path.insert(0, "tests"); from test_card_chunks import card; from anki_pipeline.packaging import render_preview; print(render_preview(card()))'],
    { cwd: repository, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  const dom = new JSDOM(result.stdout, { url: 'http://preview.test/card.html', runScripts: 'dangerously',
    beforeParse(window) { window.PointerEvent = window.MouseEvent; } });
  t.after(() => { dom.window.dispatchEvent(new dom.window.Event('pagehide')); dom.window.close(); });
  const window = dom.window, document = window.document;
  const button = document.querySelector('#preview-flip');
  button.click();
  assert.equal(document.querySelector('#preview-back').hidden, false);
  const target = document.querySelector('.example-text mark .card-chunk');
  assert.equal(target.closest('mark').className, 'target-word');
  const chinese = document.querySelector('[data-chunk-side="zh"]');
  const highlightColor = 'rgb(255, 230, 155)'; // Reader alignment highlight: #ffe69b.
  assert.equal(document.querySelectorAll('.example-translation mark, .example-translation .term-highlight').length, 0);
  assert.equal(window.getComputedStyle(target).backgroundColor, 'rgba(0, 0, 0, 0)');
  assert.equal(window.getComputedStyle(chinese).backgroundColor, 'rgba(0, 0, 0, 0)');
  target.dispatchEvent(new window.MouseEvent('pointerover', { bubbles: true }));
  assert.equal(active(chinese), true);
  assert.equal(window.getComputedStyle(target).backgroundColor, highlightColor);
  assert.equal(window.getComputedStyle(chinese).backgroundColor, highlightColor);
  target.dispatchEvent(new window.MouseEvent('pointerout', { bubbles: true, relatedTarget: document.body }));
  assert.equal(active(chinese), false);
  chinese.dispatchEvent(new window.MouseEvent('pointerover', { bubbles: true }));
  assert.equal(active(target), true);
  assert.equal(window.getComputedStyle(target).backgroundColor, highlightColor);
  assert.equal(window.getComputedStyle(chinese).backgroundColor, highlightColor);
  chinese.dispatchEvent(new window.MouseEvent('pointerout', { bubbles: true, relatedTarget: document.body }));
  assert.equal(active(target), false);
  let otherClicks = 0;
  document.addEventListener('click', () => { otherClicks++; });
  target.click();
  assert.equal(active(chinese), true);
  assert.equal(window.getComputedStyle(target).backgroundColor, highlightColor);
  assert.equal(window.getComputedStyle(chinese).backgroundColor, highlightColor);
  assert.equal(otherClicks, 0, 'capture must stop delegated card flip handlers');
  assert.equal(document.querySelector('#preview-back').hidden, false);
  target.click();
  assert.equal(active(chinese), false);
  chinese.click();
  assert.equal(active(target), true);
  button.click();
  assert.equal(active(chinese), false);
  assert.equal(document.querySelector('#preview-front').hidden, false);
  assert.equal(otherClicks, 1, 'the real flip retains native propagation');
});
