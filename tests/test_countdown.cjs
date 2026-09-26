const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('anki_pipeline/templates/countdown.js', 'utf8');
const target = Date.parse('2026-12-19T00:30:00Z');
let now = target - (86400 + 2 * 3600 + 3 * 60 + 4) * 1000;
let footer = null, counter = 0;
const intervals = new Map(), events = {};
const context = {
  Date: {parse: Date.parse, now: () => now},
  window: {addEventListener: (name, fn) => {events[name] = fn;}},
  document: {
    querySelector: () => footer,
    createElement: () => ({setAttribute() {}}),
    body: {appendChild: el => {footer = el;}},
  },
  setInterval: fn => {intervals.set(++counter, fn); return counter;},
  clearInterval: id => intervals.delete(id),
};
function load() { vm.runInNewContext(code, context); }
load();
assert.equal(footer.textContent, '2027 考研倒计时：1天 02时 03分 04秒');
const first = footer;
load();
assert.equal(footer, first);
assert.equal(intervals.size, 1, 'card refresh keeps one timer');
now = target - 1;
[...intervals.values()][0]();
assert.match(footer.textContent, /00时 00分 01秒$/);
now = target;
[...intervals.values()][0]();
assert.equal(footer.textContent, '2027 考研初试已开始');
assert.equal(intervals.size, 0);
now = target + 86400000;
load();
assert.equal(footer.textContent, '2027 考研初试已开始');
assert.equal(intervals.size, 0);
now = target - 10000; load(); events.pagehide();
assert.equal(intervals.size, 0);
load(); footer = null; [...intervals.values()][0]();
assert.equal(intervals.size, 0, 'removed card clears timer');
console.log('Countdown: Beijing timezone, rollover, expiry, refresh and cleanup passed.');
