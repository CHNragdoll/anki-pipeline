// The countdown belongs to the translated card content, not a viewport row.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');
const templates = path.resolve(__dirname, '../anki_pipeline/templates');
const code = fs.readFileSync(path.join(templates, 'countdown.js'), 'utf8');
const styles = fs.readFileSync(path.join(templates, 'style.css'), 'utf8');
const cardCode = fs.readFileSync(path.join(templates, 'script.js'), 'utf8');
const target = Date.parse('2026-12-19T00:30:00Z');
// This freezes the installed model's timer contract without using generated or
// duplicate local template files as CI inputs.
const legacyCode = `(function () {
  if (window.__ankiExamTimer) clearInterval(window.__ankiExamTimer);
  var footer = document.querySelector('.exam-countdown');
  if (!footer) { footer = document.createElement('div'); footer.className = 'exam-countdown'; document.body.appendChild(footer); }
  var timer = setInterval(function () {
    if (document.querySelector('.exam-countdown') !== footer) {
      clearInterval(timer);
      if (window.__ankiExamTimer === timer) window.__ankiExamTimer = null;
    }
  }, 1000);
  window.__ankiExamTimer = timer;
})();`;
const cardContent = '<main class="vocab-card vocab-front"><div class="card-meta">Unit 1</div><div class="front-box"><h1 class="word">ambition</h1><audio id="word-audio" hidden src="oxford.mp3"></audio></div></main>';
const previewContent = '<div class="preview-controls"><button id="preview-flip" aria-pressed="false">显示答案</button></div><section id="preview-front">' + cardContent + '</section><section id="preview-back" hidden><div class="vocab-card vocab-back"><ol class="examples"><li id="last-example">The last sentence and its translation.</li></ol></div></section>';
function fixture(t, { qa = false, loading = false, oldStyle = false } = {}) {
  const body = qa ? '<nav id="anki-ui">Unrelated reviewer controls</nav><div id="qa">' + cardContent + '</div><script id="host-script"></script>' : previewContent;
  const oldCss = '.exam-countdown{position:fixed;right:12px;bottom:12px;z-index:10;border:1px solid #ccc;border-radius:8px;background:white;padding:10px}';
  const dom = new JSDOM('<!doctype html><html><head><style>' + (oldStyle ? oldCss : styles) + '</style></head><body>' + body + '</body></html>', { url: 'http://preview.test/card.html', runScripts: 'outside-only' });
  const window = dom.window;
  let now = target - (86400 + 2 * 3600 + 3 * 60 + 4) * 1000;
  let ready = loading ? 'loading' : 'complete';
  Object.defineProperty(window.document, 'readyState', { get: () => ready, configurable: true });
  window.Date.now = () => now;
  let counter = 0;
  const intervals = new Map();
  window.setInterval = fn => { intervals.set(++counter, fn); return counter; };
  window.clearInterval = id => intervals.delete(id);
  t.after(() => { window.dispatchEvent(new window.Event('pagehide')); window.close(); });
  return {
    window, document: window.document, intervals,
    load: () => window.eval(code),
    loadLegacy: () => window.eval(legacyCode),
    setNow: value => { now = value; },
    tick: () => [...intervals.values()].forEach(fn => fn()),
    ready: () => { ready = 'complete'; window.document.dispatchEvent(new window.Event('DOMContentLoaded')); },
  };
}

test('Beijing target, second rollover and expiry retain one timer and one footer on refresh', t => {
  const f = fixture(t);
  f.load();
  const footer = f.document.querySelector('.exam-countdown');
  assert.equal(footer.textContent, '2027 考研倒计时：1天 02时 03分 04秒');
  assert.equal(footer.getAttribute('role'), 'timer');
  assert.equal(footer.getAttribute('aria-live'), 'off');
  f.load();
  assert.equal(f.document.querySelector('.exam-countdown'), footer);
  assert.equal(f.document.querySelectorAll('.exam-countdown').length, 1);
  assert.equal(f.intervals.size, 1);
  f.setNow(target - 1); f.tick();
  assert.match(footer.textContent, /00时 00分 01秒$/);
  f.setNow(target); f.tick();
  assert.equal(footer.textContent, '2027 考研初试已开始');
  assert.equal(f.intervals.size, 0);
  f.setNow(target + 86400000); f.load();
  assert.equal(footer.textContent, '2027 考研初试已开始');
  assert.equal(f.intervals.size, 0);
});

test('web countdown stays at the translated content end without a viewport footer row', t => {
  const f = fixture(t);
  const audio = f.document.getElementById('word-audio');
  f.window.eval(cardCode);
  f.load();
  const content = f.document.querySelector('.anki-countdown-content');
  const footer = f.document.querySelector('.exam-countdown');
  assert.equal(content.parentElement, f.document.body);
  assert.equal(content.nextElementSibling, null);
  assert.equal(footer.parentElement, f.document.querySelector('.vocab-back'));
  assert.equal(f.document.getElementById('preview-front').parentElement, content);
  assert.equal(f.document.getElementById('preview-back').parentElement, content);
  assert.equal(f.document.querySelector('.preview-controls').parentElement, content);
  assert.equal(f.document.getElementById('word-audio'), audio, 'mounting never replaces an audio node');
  const style = element => f.window.getComputedStyle(element);
  assert.equal(style(content).overflowY, 'auto');
  assert.equal(parseFloat(style(content).minHeight), 0);
  assert.equal(style(footer).position, 'static');
  assert.equal(style(footer).width, 'fit-content');
  assert.equal(style(footer).padding, '0px');
  assert.equal(style(footer).textAlign, 'right');
  assert.equal(style(footer).backgroundColor, 'rgba(0, 0, 0, 0)');
  assert.equal(style(footer).borderTopWidth, '0px');
  assert.equal(style(footer).boxShadow, 'none');
  f.document.getElementById('preview-flip').click();
  assert.equal(f.document.getElementById('preview-back').hidden, false);
  assert.equal(f.document.getElementById('last-example').closest('.anki-countdown-content'), content);
  assert.equal(f.document.querySelector('.exam-countdown'), footer);
  assert.equal(f.intervals.size, 1);
  f.document.getElementById('preview-flip').click();
  assert.equal(f.document.getElementById('preview-front').hidden, false);
});

test('Anki mounts only within #qa and reapplies layout after real card-host contents are replaced', t => {
  const f = fixture(t, { qa: true, oldStyle: true });
  const nav = f.document.getElementById('anki-ui');
  const script = f.document.getElementById('host-script');
  const qa = f.document.getElementById('qa');
  f.load();
  const first = f.document.querySelector('.exam-countdown');
  assert.equal(first.parentElement, qa.querySelector('.vocab-front'));
  assert.equal(qa.querySelector('.anki-countdown-content').contains(f.document.querySelector('.word')), true);
  assert.equal(nav.parentElement, f.document.body);
  assert.equal(script.parentElement, f.document.body);
  assert.equal(f.window.getComputedStyle(first).position, 'static');
  assert.equal(f.window.getComputedStyle(first).width, 'fit-content', 'the retained model cannot reserve a full-width row');
  assert.equal(f.window.getComputedStyle(first).backgroundColor, 'rgba(0, 0, 0, 0)');
  qa.innerHTML = '<div class="vocab-card vocab-back"><ol class="examples"><li id="replacement">New card answer</li></ol></div>';
  f.load();
  const next = f.document.querySelector('.exam-countdown');
  assert.notEqual(next, first);
  assert.equal(next.parentElement, qa.querySelector('.vocab-back'));
  assert.equal(qa.querySelector('.anki-countdown-content').contains(f.document.getElementById('replacement')), true);
  assert.equal(f.document.querySelectorAll('.exam-countdown').length, 1);
  assert.equal(f.document.querySelectorAll('.anki-countdown-content').length, 1);
  assert.equal(f.intervals.size, 1);
  assert.equal(nav.parentElement, f.document.body);
});

test('a field script before DOM completion waits and safely adopts an already-running legacy timer', t => {
  const f = fixture(t, { qa: true, loading: true, oldStyle: true });
  const qa = f.document.getElementById('qa');
  f.load();
  f.load();
  assert.equal(qa.querySelector('.anki-countdown-content'), null);
  f.loadLegacy();
  const legacyFooter = f.document.querySelector('.exam-countdown');
  qa.append(f.document.createElement('section'));
  f.ready();
  assert.equal(f.document.querySelector('.exam-countdown'), legacyFooter);
  assert.equal(legacyFooter.parentElement, qa.querySelector('.vocab-front'));
  assert.equal(f.intervals.size, 1);
  assert.equal(f.document.querySelectorAll('.anki-countdown-content').length, 1);
});

test('an installed legacy timer after the field helper continues finding the same content countdown', t => {
  const f = fixture(t, { qa: true, oldStyle: true });
  f.load();
  const footer = f.document.querySelector('.exam-countdown');
  f.loadLegacy();
  f.tick();
  assert.equal(f.document.querySelector('.exam-countdown'), footer);
  assert.equal(f.intervals.size, 1);
  assert.equal(footer.parentElement, f.document.querySelector('.vocab-front'));
  assert.equal(f.window.getComputedStyle(footer).position, 'static');
  f.window.dispatchEvent(new f.window.Event('pagehide'));
  assert.equal(f.intervals.size, 0, 'cleanup also clears the active legacy interval');
});

test('detached cards stop their timer and a page-cache return resumes only the current card', t => {
  const f = fixture(t, { qa: true });
  f.load();
  const qa = f.document.getElementById('qa');
  qa.replaceChildren();
  f.tick();
  assert.equal(f.intervals.size, 0);
  qa.innerHTML = cardContent;
  f.load();
  f.window.dispatchEvent(new f.window.Event('pagehide'));
  assert.equal(f.intervals.size, 0);
  f.window.dispatchEvent(new f.window.Event('pageshow'));
  assert.equal(f.intervals.size, 1);
  assert.equal(f.document.querySelectorAll('.exam-countdown').length, 1);
});

const mutationsSettled = () => new Promise(resolve => setTimeout(resolve, 0));

test('Anki answer places countdown after the final translated example within the examples section', t => {
  const f = fixture(t, { qa: true, oldStyle: true });
  const qa = f.document.getElementById('qa');
  qa.innerHTML = cardContent + '<div class="vocab-card vocab-back"><section class="examples-section"><ol class="examples"><li class="example-card"><p class="translation">最后一条翻译</p></li></ol></section><section class="personal-note">笔记</section></div>';
  f.load();
  const examples = qa.querySelector('.examples-section');
  const footer = qa.querySelector('.exam-countdown');
  assert.equal(footer.parentElement, examples);
  assert.equal(footer.previousElementSibling, examples.querySelector('.examples'));
  assert.equal(examples.lastElementChild, footer);
  assert.equal(qa.querySelector(':scope > .exam-countdown'), null);
  assert.equal(f.window.getComputedStyle(footer).position, 'static');
});

test('detaching a plain retained-card fallback removes its countdown before unwrapping', async t => {
  const f = fixture(t, { qa: true });
  const qa = f.document.getElementById('qa');
  qa.innerHTML = '<article class="legacy-front">Retained card content</article>';
  f.load();
  assert.equal(qa.querySelector('.exam-countdown').parentElement, qa.querySelector('.anki-countdown-content'));
  qa.remove();
  await mutationsSettled();
  assert.equal(qa.querySelector('.exam-countdown'), null);
  assert.equal(qa.querySelector('.anki-countdown-content'), null);
  assert.equal(qa.firstElementChild.className, 'legacy-front');
  assert.equal(f.window.__ankiExamCountdownState, null);
  assert.equal(f.intervals.size, 0);
});

test('Anki question update restores the scroll layout after resetting body classes', async t => {
  const f = fixture(t, { qa: true });
  const qa = f.document.getElementById('qa');
  f.load();
  const content = qa.querySelector('.anki-countdown-content');
  const word = qa.querySelector('.word');
  // reviewer.js runs the template scripts before onUpdateHook sets body.className.
  f.document.body.className = 'card card1';
  await mutationsSettled();
  assert.equal(f.document.body.classList.contains('anki-countdown-document'), true);
  assert.equal(f.window.getComputedStyle(f.document.body).display, 'flex');
  assert.equal(content.contains(word), true);
  assert.equal(qa.querySelector('.exam-countdown').parentElement, qa.querySelector('.vocab-front'));
  f.window.dispatchEvent(new f.window.Event('pagehide'));
  f.document.body.className = 'card card1';
  f.window.dispatchEvent(new f.window.Event('pageshow'));
  assert.equal(f.document.body.classList.contains('anki-countdown-document'), true);
});

test('leaving the enhanced note type restores native scrolling even when a retained-model timer replaced v2', async t => {
  for (const legacyLast of [false, true]) {
    const f = fixture(t, { qa: true, oldStyle: true });
    const qa = f.document.getElementById('qa');
    qa.classList.add('existing-note-layout');
    f.document.body.classList.add('existing-reviewer-theme');
    if (!legacyLast) f.loadLegacy();
    f.load();
    if (legacyLast) f.loadLegacy();
    assert.equal(f.intervals.size, 1);
    qa.innerHTML = '<div id="other-note">Another note type with long content</div>';
    await mutationsSettled();
    assert.equal(f.document.querySelector('.anki-countdown-content'), null);
    assert.equal(f.document.querySelector('.exam-countdown'), null);
    assert.equal(f.document.getElementById('anki-exam-countdown-layout-v2'), null);
    for (const node of [f.document.documentElement, f.document.body, qa]) {
      assert.equal(node.classList.contains('anki-countdown-document'), false);
      assert.equal(node.classList.contains('anki-countdown-layout'), false);
      assert.notEqual(f.window.getComputedStyle(node).overflowY, 'hidden');
    }
    assert.equal(qa.classList.contains('existing-note-layout'), true);
    assert.equal(f.document.body.classList.contains('existing-reviewer-theme'), true);
    assert.equal(f.intervals.size, 0);
    f.window.dispatchEvent(new f.window.Event('pagehide'));
    f.window.dispatchEvent(new f.window.Event('pageshow'));
    assert.equal(f.document.querySelector('.anki-countdown-content'), null);
    assert.equal(f.document.querySelector('.exam-countdown'), null);
    assert.equal(f.intervals.size, 0);
    assert.equal(qa.firstElementChild.id, 'other-note');
  }
});

test('host lifecycle cleanup still runs after expiry without an interval', async t => {
  const f = fixture(t, { qa: true, oldStyle: true });
  f.setNow(target);
  f.load();
  assert.equal(f.intervals.size, 0);
  f.document.getElementById('qa').replaceChildren(f.document.createElement('article'));
  await mutationsSettled();
  assert.equal(f.document.querySelector('.exam-countdown'), null);
  assert.equal(f.document.body.classList.contains('anki-countdown-document'), false);
  f.window.dispatchEvent(new f.window.Event('pageshow'));
  assert.equal(f.document.querySelector('.exam-countdown'), null);
});

test('a pending parser boot cannot enhance a different note that replaced the original card', t => {
  const f = fixture(t, { qa: true, loading: true });
  f.load();
  f.document.getElementById('qa').innerHTML = '<article id="foreign-note">Another note type</article>';
  f.ready();
  f.window.dispatchEvent(new f.window.Event('pageshow'));
  assert.equal(f.document.querySelector('.anki-countdown-content'), null);
  assert.equal(f.document.querySelector('.exam-countdown'), null);
  assert.equal(f.document.body.classList.contains('anki-countdown-document'), false);
  assert.equal(f.intervals.size, 0);
});

test('an invalid host unwraps remaining content without removing foreign footers or their timer', async t => {
  const f = fixture(t, { qa: true, oldStyle: true });
  const qa = f.document.getElementById('qa');
  f.load();
  const content = qa.querySelector('.anki-countdown-content');
  const word = qa.querySelector('.word');
  qa.querySelector('.exam-countdown').remove();
  const foreign = f.document.createElement('aside');
  foreign.className = 'exam-countdown';
  foreign.textContent = 'Another note timer';
  qa.append(foreign);
  const foreignTimer = f.window.setInterval(() => {}, 1000);
  f.window.__ankiExamTimer = foreignTimer;
  await mutationsSettled();
  assert.equal(qa.contains(content), false);
  assert.equal(qa.contains(word), true);
  assert.equal(foreign.parentElement, qa);
  assert.equal(foreign.textContent, 'Another note timer');
  assert.equal(f.window.__ankiExamTimer, foreignTimer);
  assert.equal(f.intervals.size, 1);
  f.window.dispatchEvent(new f.window.Event('pageshow'));
  assert.equal(foreign.parentElement, qa);
  assert.equal(qa.querySelector('.anki-countdown-content'), null);
});

test('a pending old-host observer cannot tear down a freshly enhanced card', async t => {
  const f = fixture(t, { qa: true });
  const qa = f.document.getElementById('qa');
  f.load();
  qa.innerHTML = cardContent;
  f.load();
  const nextFooter = qa.querySelector('.exam-countdown');
  await mutationsSettled();
  assert.equal(qa.querySelector('.exam-countdown'), nextFooter);
  assert.equal(qa.classList.contains('anki-countdown-layout'), true);
  assert.equal(f.document.body.classList.contains('anki-countdown-document'), true);
  assert.equal(f.intervals.size, 1);
});
