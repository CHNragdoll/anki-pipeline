// Isolated event tests: no browser, audio output, or network requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {}, audios = [], voices = [], timers = new Map();
let timerId = 0, cancels = 0;
class Audio {
  constructor() { audios.push(this); }
  play() { return Promise.resolve(); }
  pause() { this.paused = true; }
  removeAttribute() {}
  remove() { this.removed = true; }
}
const window = {
  addEventListener() {},
  SpeechSynthesisUtterance: function(text) { this.text = text; },
  speechSynthesis: {speak(v) { voices.push(v); }, cancel() { cancels++; }},
};
const context = {
  window, Audio, SpeechSynthesisUtterance: window.SpeechSynthesisUtterance,
  encodeURIComponent,
  setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
  clearTimeout(id) { timers.delete(id); },
  document: {
    querySelectorAll() { return []; },
    body: { appendChild() {} },
    addEventListener(event, callback) { listeners[event] = callback; },
  },
};
vm.runInNewContext(fs.readFileSync('anki_pipeline/templates/script.js', 'utf8'), context);
function button() {
  const status = {textContent: ''};
  const text = {cloneNode() {
    return {textContent: 'rate\nrises & falls', querySelectorAll() {
      return [{replaceWith: (value) => { this.textContent = 'rate' + value + 'rises & falls'; }}];
    }};
  }};
  const card = {querySelector(s) { return s === '.example-text' ? text : status; }};
  return {pressed: 'false', status,
    setAttribute(k,v) { this.pressed = v; },
    closest(s) { return s === '.sentence-play' ? this : s === '.example-card' ? card : null; },
  };
}
const a = button(), b = button();
const click = (target) => listeners.click({target});
click(a);
assert.equal(a.pressed, 'true');
assert.equal(new URL(audios[0].src).searchParams.get('audio'), 'rate rises & falls');
click(b);
assert.equal(a.pressed, 'false');
assert.equal(audios[0].paused, true);
audios[0].onerror();
assert.equal(voices.length, 0, 'stale failure must not start a voice');
assert.equal(b.pressed, 'true');
audios[1].onerror();
assert.equal(voices[0].text, 'rate rises & falls');
voices[0].onstart();
click(b);
assert.equal(b.pressed, 'false');
assert.equal(cancels, 1);
click(a);
for (const fn of [...timers.values()]) fn();
assert.equal(voices.length, 2, 'network timeout falls back');
for (const fn of [...timers.values()]) fn();
assert.match(a.status.textContent, /朗读暂不可用/);
assert.equal(a.pressed, 'false');
assert.equal(timers.size, 0);
console.log('Sentence playback: encoding, multiline, switching, stale callbacks, stop, timeouts passed.');
