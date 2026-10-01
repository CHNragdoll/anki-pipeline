// The real Anki reviewer adds replay-button SVG and button rules after card CSS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');
const { JSDOM } = require('jsdom');

const repository = path.resolve(__dirname, '..');
const styles = fs.readFileSync(path.join(repository, 'anki_pipeline/templates/style.css'), 'utf8');
const reviewerCss = [
  'button{margin:1em .5em}',
  '.replay-button{text-decoration:none;display:inline-flex;vertical-align:middle;margin:3px}',
  '.replay-button svg{width:40px;height:40px}',
  '.replay-button svg circle{fill:#fff;stroke:#414141}',
  '.replay-button svg path{fill:#414141}',
  '.card .replay-button{border:1px solid #888;border-radius:50%;background-image:linear-gradient(#fff,#ddd);box-shadow:0 2px 3px #777}',
].join('\n');

test('packaged dictionary replay keeps its SVG ring without an outer button frame', t => {
  const result = spawnSync(path.join(repository, '.venv/bin/python'), ['-c',
    'from anki_pipeline.packaging import _dictionary_audio_markup; '
    + 'card={"local_dictionary":{"audio":{"oxford":[{"filename":"o.mp3","accent":"us"}],'
    + '"webster":[{"filename":"w.mp3","accent":"us"}]},"fallback_audio":{}}}; '
    + 'print(_dictionary_audio_markup(card,None,preview=False))'],
  { cwd: repository, encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  const dom = new JSDOM('<!doctype html><style>' + styles + '\n' + reviewerCss + '</style>'
    + '<body class="card"><main class="vocab-card">' + result.stdout
    + '<button class="review-score">评分</button></main></body>');
  t.after(() => dom.window.close());
  const button = dom.window.document.querySelector('.preview-word-play');
  const svgCircle = button.querySelector('svg circle');
  const svgPath = button.querySelector('svg path');
  const computed = dom.window.getComputedStyle(button);
  assert.notEqual(dom.window.getComputedStyle(svgCircle).display, 'none');
  assert.equal(dom.window.getComputedStyle(svgPath).fill, 'rgb(65, 65, 65)');
  assert.equal(computed.borderTopWidth, '0px');
  assert.equal(computed.boxShadow, 'none');
  assert.equal(computed.backgroundImage, 'none');
  button.setAttribute('aria-pressed', 'true');
  assert.equal(dom.window.getComputedStyle(button).boxShadow, 'none');
  assert.equal(dom.window.getComputedStyle(button).backgroundImage, 'none');
  assert.equal(button.getAttribute('aria-label'), '播放单词发音');
  assert.equal(dom.window.document.querySelectorAll('.dictionary-audio-source option').length, 2);
  assert.notEqual(dom.window.getComputedStyle(dom.window.document.querySelector('.review-score')).borderTopWidth, '0px');
});
