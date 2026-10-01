// Anki executes a live getElementsByTagName('script') collection, so the Meta
// helper must not move its field script past the trailing card initializer.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { spawnSync } = require('node:child_process');
const { JSDOM } = require('jsdom');
const root = path.resolve(__dirname, '..');
const templates = path.join(root, 'anki_pipeline/templates');
const countdown = fs.readFileSync(path.join(templates, 'countdown.js'), 'utf8');
const cardScript = fs.readFileSync(path.join(templates, 'script.js'), 'utf8');
const chunks = fs.readFileSync(path.join(templates, 'card-chunks.js'), 'utf8');
const generated = spawnSync(path.join(root, '.venv/bin/python'), ['-c',
  'from anki_pipeline.packaging import _dictionary_audio_markup; '
  + 'print(_dictionary_audio_markup({"local_dictionary":{"audio":{"oxford":[{"filename":"o.mp3"}],"webster":[{"filename":"w.mp3"}]},"fallback_audio":{}}},None,preview=False))'],
  { cwd: root, encoding: 'utf8' });
assert.equal(generated.status, 0, generated.stderr);

function front(word) {
  return '<main class="vocab-card vocab-front"><div class="card-heading"><div class="card-meta">Unit 1 ➫ Lesson 1<script>'
    + countdown + '</script></div></div><div class="front-box"><h1 class="word">' + word
    + '</h1><a class="dictionary-link" href="#">查词</a><div class="recorded-audio">'
    + generated.stdout + '</div></div></main><script>' + cardScript + '\n' + countdown + '\n' + chunks + '</script>';
}

test('Anki live script execution initializes source, lookup and chunks on front, answer and next card', async t => {
  const dom = new JSDOM('<!doctype html><body class="card card1"><div id="qa"></div><nav id="native-ui">Anki controls</nav></body>',
    { runScripts: 'outside-only', url: 'http://localhost/' });
  t.after(() => { if (dom.window.__ankiExamCountdownCleanup) dom.window.__ankiExamCountdownCleanup(); dom.window.close(); });
  const window = dom.window;
  const document = window.document;
  await new Promise(resolve => window.setTimeout(resolve, 0));
  async function update(html) {
    const qa = document.getElementById('qa');
    qa.innerHTML = html;
    // Same live iterable and per-script await as installed reviewer.js Jc/Op.
    for (const old of qa.getElementsByTagName('script')) {
      const replacement = document.createElement('script');
      replacement.textContent = old.textContent;
      old.replaceWith(replacement);
      window.eval(replacement.textContent);
      await Promise.resolve();
    }
    document.body.className = 'card card1';
    await Promise.resolve();
  }
  function verify(word, source) {
    const heading = document.querySelector('.card-heading');
    const setting = document.querySelector('.dictionary-audio-setting');
    assert.equal(setting.parentElement, heading, 'source belongs in top heading, before metadata');
    assert.equal(heading.firstElementChild, setting);
    assert.equal(document.querySelectorAll('.dictionary-audio-setting').length, 1);
    assert.equal(document.querySelector('.front-box .dictionary-audio-setting'), null);
    assert.equal(setting.querySelector('select').value, source);
    assert.match(document.querySelector('.dictionary-link').href, new RegExp('searchword\\?word=' + word + '&'));
    assert.equal(window.__ankiLibraryEventsBound, true);
    assert.equal(window.__ankiCardChunksBound, true);
    assert.equal(document.querySelectorAll('.exam-countdown').length, 1);
    assert.equal(document.getElementById('native-ui').parentElement, document.body);
  }
  await update(front('ambition'));
  verify('ambition', 'oxford');
  const choice = document.querySelector('.dictionary-audio-source');
  choice.value = 'webster';
  choice.dispatchEvent(new window.Event('change', { bubbles: true }));
  verify('ambition', 'webster');
  await update(front('ambition') + '<hr id="answer"><div class="vocab-back">释义</div><script>' + cardScript + '\n' + countdown + '</script>');
  verify('ambition', 'webster');
  await update(front('action'));
  verify('action', 'webster');
});
