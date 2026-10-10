const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { JSDOM } = require('jsdom');
const { spawnSync } = require('node:child_process');
const script = fs.readFileSync(process.env.PHONETIC_RUNTIME_UNDER_TEST || path.join(__dirname, '../anki_pipeline/templates/phonetic-labels.js'), 'utf8');

test('offline artwork retains blue BrE and red NAmE for speaker, hover and active states', () => {
  const css = fs.readFileSync(path.join(__dirname, '../anki_pipeline/templates/phonetic-labels.css'), 'utf8');
  let images = 0;
  for (const line of css.split('\n')) {
    for (const match of line.matchAll(/data:image\/svg\+xml;base64,([A-Za-z0-9+/=]+)/g)) {
      const svg = Buffer.from(match[1], 'base64').toString('utf8');
      const uk = line.includes('.phonetic-accent-uk');
      assert.ok(svg.includes(uk ? '#283583' : '#d31245'));
      assert.ok(!svg.includes(uk ? '#d31245' : '#283583'));
      if (svg.includes('<text')) {
        assert.ok(svg.includes('>' + (uk ? 'BrE' : 'NAmE') + '</text>'));
        assert.ok(!svg.includes('>' + (uk ? 'NAmE' : 'BrE') + '</text>'));
      }
      images++;
    }
  }
  assert.equal(images, 6);
});

function setup(text) {
  const dom = new JSDOM('<body><div id="qa"><div class="phonetic-line"></div></div></body>', { runScripts: 'outside-only' });
  dom.window.document.querySelector('.phonetic-line').textContent = text;
  dom.window.eval(script);
  return dom;
}

test('dual IPA retains all readings and clicking toggles the accent label', t => {
  const dom = setup('英:/ˈwɔː.təʳ/ 美:/ˈwɔ·t̬ər；ˈwɑt̬·ər/');
  t.after(() => dom.window.close());
  const doc = dom.window.document;
  assert.deepEqual(Array.from(doc.querySelectorAll('.phonetic-accent-value'), el => el.textContent), ['/ˈwɔː.təʳ/', '/ˈwɔ·t̬ər；ˈwɑt̬·ər/']);
  const [uk, us] = doc.querySelectorAll('button');
  uk.click(); assert.equal(uk.getAttribute('aria-pressed'), 'true');
  us.click(); assert.equal(uk.getAttribute('aria-pressed'), 'false'); assert.equal(us.getAttribute('aria-pressed'), 'true');
  us.click(); assert.equal(us.getAttribute('aria-pressed'), 'false');
});

test('reused native webview enhances each new face without doubling handlers', t => {
  const dom = setup('英:/ˌɒf ðə ˈkʌf/ 美:/ˌɔːf ðə ˈkʌf/');
  t.after(() => dom.window.close());
  const doc = dom.window.document;
  dom.window.eval(script);
  assert.equal(doc.querySelectorAll('button').length, 2);
  doc.querySelector('button').click();
  assert.equal(doc.querySelector('button').getAttribute('aria-pressed'), 'true');
  const qa = doc.getElementById('qa');
  qa.innerHTML = '<div class="phonetic-line">英:/ˌæresˈtiː/ 美:/əˌrɛsˈtiː/</div>';
  dom.window.eval(script);
  const button = qa.querySelector('button');
  button.click(); assert.equal(button.getAttribute('aria-pressed'), 'true');
  assert.deepEqual(Array.from(qa.querySelectorAll('.phonetic-accent-value'), el => el.textContent), ['/ˌæresˈtiː/', '/əˌrɛsˈtiː/']);
});

test('single IPA stays visible and enhancement does not interpret IPA as markup', t => {
  const single = setup('/æmˈbɪʃn/'); t.after(() => single.window.close());
  assert.equal(single.window.document.querySelector('.phonetic-line').textContent, '/æmˈbɪʃn/');
  assert.equal(single.window.document.querySelectorAll('button').length, 0);
  const dual = setup('英:<img src=x> 美:/abc/'); t.after(() => dual.window.close());
  assert.equal(dual.window.document.querySelectorAll('img').length, 0);
  assert.equal(dual.window.document.querySelector('.phonetic-accent-value').textContent, '<img src=x>');
});

const legacy = fs.readFileSync(path.join(__dirname, '../anki_pipeline/templates/script.js'), 'utf8');

test('actual accent markup remains playable with single or absent IPA without inventing readings', t => {
  const root = path.resolve(__dirname, '..');
  const generated = spawnSync(path.join(root, '.venv/bin/python'), ['-c',
    'from anki_pipeline.packaging import _dictionary_audio_markup; '
    + 'print(_dictionary_audio_markup({"local_dictionary":{"audio":{},"accent_audio":'
    + '{"uk":{"cambridge":[{"filename":"uk.mp3","accent":"uk"}]},'
    + '"us":{"oxford":[{"filename":"us.mp3","accent":"us"}]}}}},None,preview=False))'],
    {cwd:root, encoding:'utf8'});
  assert.equal(generated.status, 0, generated.stderr);
  for (const ipa of ['/ˈwɔːtə/', '']) {
    const dom = new JSDOM('<body><main class="vocab-front"><div class="card-heading"></div>'
      + '<div class="front-box">' + (ipa ? '<div class="phonetic-line">' + ipa + '</div>' : '')
      + '<div class="audio-line">' + generated.stdout + '</div></div></main></body>',
      {runScripts:'outside-only',url:'http://localhost/'});
    t.after(() => dom.window.close());
    const calls = [];
    dom.window.HTMLMediaElement.prototype.play = function () {calls.push(this.getAttribute('src'));return Promise.resolve();};
    dom.window.HTMLMediaElement.prototype.pause = function () {};
    dom.window.eval(legacy);dom.window.eval(script);dom.window.eval(script);
    const doc = dom.window.document;
    assert.equal(doc.querySelectorAll('.phonetic-accent-icon').length, 2);
    assert.equal(doc.querySelectorAll('[data-accent-source]').length, 2);
    assert.equal(doc.querySelector('.phonetic-line').textContent, ipa);
    assert.equal(doc.querySelector('.phonetic-accent-value'), null);
    doc.querySelector('.phonetic-accent-uk').click();
    doc.querySelector('.phonetic-accent-us').click();
    assert.deepEqual(calls, ['uk.mp3', 'us.mp3']);
  }
});
function accentSetup(extra = '') {
  const dom = new JSDOM('<body><div id="qa"><div id="preview-front">' + accentFace(extra) + '</div><div id="preview-back" hidden></div><button id="preview-flip" aria-pressed="false">显示答案</button></div></body>',
    { runScripts: 'outside-only', url: 'http://localhost/' });
  const calls = [];
  dom.window.HTMLMediaElement.prototype.play = function () { calls.push(this.getAttribute('src')); return Promise.resolve(); };
  dom.window.HTMLMediaElement.prototype.pause = function () { calls.push('pause:' + this.getAttribute('src')); };
  dom.window.eval(legacy); dom.window.eval(script);
  return {dom, calls};
}
function accentFace(extra) {
  return '<main class="vocab-front"><div class="card-heading"><div class="card-meta">Unit 1 ➫ 1</div></div>'
    + '<div class="phonetic-line">英:/ˈæn.ɪ.mᵊl/ 美:/ˈæn·ə·məl/</div>'
    + '<div class="dictionary-word-audio" data-accent-playback="v1" ' + extra + '>'
    + '<label class="dictionary-audio-setting">发音<select class="dictionary-audio-source"><option value="oxford">牛津</option></select></label><button class="preview-word-play">triangle</button>'
    + '<audio src="c-uk.mp3" data-dictionary-source="cambridge" data-dictionary-accent="uk"></audio>'
    + '<audio src="o-uk.mp3" data-dictionary-source="oxford" data-dictionary-accent="uk"></audio>'
    + '<audio src="o-us.mp3" data-dictionary-source="oxford" data-dictionary-accent="us"></audio>'
    + '<audio src="w-us.mp3" data-dictionary-source="webster" data-dictionary-accent="us"></audio>'
    + '<span class="word-audio-status"></span></div></main>';
}

test('mobile pronunciation targets bypass tap zones across reused card faces', t => {
  const {dom} = accentSetup(); t.after(() => dom.window.close());
  const win = dom.window, doc = win.document;
  // AnkiMobile reserves unrecognized elements for its flip/rating tap zones.
  // Selects and label text require the documented tappable marker.
  const passesToCard = target => {
    for (let node = target; node && node !== doc; node = node.parentNode) {
      if (['A', 'BUTTON'].includes(node.nodeName) || node.onclick ||
          node.classList?.contains('tappable')) return true;
    }
    return false;
  };
  for (let face = 0; face < 2; face++) {
    if (face) {
      doc.getElementById('preview-front').innerHTML = accentFace('');
      win.eval(script);
    }
    for (const target of doc.querySelectorAll('[data-accent-source], .accent-audio-setting, .phonetic-accent-icon')) {
      assert.equal(passesToCard(target), true, target.outerHTML);
    }
    assert.equal(passesToCard(doc.querySelector('.card-meta')), false,
      'ordinary card content must retain the native tap action');
    assert.equal(doc.querySelectorAll('[data-accent-source]').length, 2);
  }
});

test('UK and US selectors stay separate and icons play declared accents only', t => {
  const {dom, calls} = accentSetup(); t.after(() => dom.window.close());
  const doc = dom.window.document;
  assert.deepEqual(Array.from(doc.querySelectorAll('.pronunciation-settings label'), x => x.firstChild.textContent.trim()), ['英式发音', '美式发音']);
  assert.equal(doc.querySelector('.preview-word-play'), null);
  assert.equal(doc.querySelector('.front-box .dictionary-audio-setting'), null);
  const uk = doc.querySelector('.phonetic-accent-uk'), us = doc.querySelector('.phonetic-accent-us');
  uk.click(); assert.equal(calls.at(-1), 'c-uk.mp3');
  us.click(); assert.deepEqual(calls.slice(-2), ['pause:c-uk.mp3', 'o-us.mp3']);
  const ukChoice = doc.querySelector('[data-accent-source="uk"]');
  ukChoice.value = 'oxford'; ukChoice.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  const usChoice = doc.querySelector('[data-accent-source="us"]');
  usChoice.value = 'webster'; usChoice.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
  uk.click(); assert.equal(calls.at(-1), 'o-uk.mp3');
  us.click(); assert.equal(calls.at(-1), 'w-us.mp3');
  assert.equal(dom.window.localStorage.getItem('anki-dictionary-uk-pronunciation-v1'), 'oxford');
  assert.equal(dom.window.localStorage.getItem('anki-dictionary-pronunciation-v1'), 'webster');
  assert.equal(ukChoice.value, 'oxford'); assert.equal(usChoice.value, 'webster');
});

test('same accent fallback must be explicit; UK and unknown tracks never stand in for US', t => {
  const {dom, calls} = accentSetup('data-fallback-us-oxford="cambridge"'); t.after(() => dom.window.close());
  const doc = dom.window.document;
  doc.querySelector('audio[src="o-us.mp3"]').remove(); dom.window.eval(script);
  doc.querySelector('.dictionary-word-audio').insertAdjacentHTML('beforeend', '<audio src="c-us.mp3" data-dictionary-source="cambridge" data-dictionary-accent="us"></audio>');
  dom.window.eval(script);
  doc.querySelector('.phonetic-accent-us').click(); assert.equal(calls.at(-1), 'c-us.mp3');
  assert.match(doc.querySelector('.accent-status-us').textContent, /美式剑桥/);
  doc.querySelector('audio[src="c-us.mp3"]').setAttribute('data-dictionary-accent', 'unknown');
  dom.window.__ankiStopPreviewWord(); dom.window.eval(script);
  assert.equal(doc.querySelector('.phonetic-accent-us').disabled, true);
  const count = calls.length; doc.querySelector('.phonetic-accent-us').click(); assert.equal(calls.length, count);
  assert.match(doc.querySelector('.accent-status-us').textContent, /暂无录音/);
});

test('missing US Webster uses declared Oxford US with a persistent source notice after runtime upgrade', t => {
  const oldV2 = fs.readFileSync(path.join(__dirname, 'fixtures/phonetic-labels-v2-before-brand-lanes.js'), 'utf8');
  const {dom,calls}=accentSetup('data-fallback-us-webster="oxford"');
  t.after(()=>dom.window.close());
  const win=dom.window,doc=win.document;
  win.eval(oldV2);
  doc.querySelector('audio[src="w-us.mp3"]').remove();
  win.localStorage.setItem('anki-dictionary-pronunciation-v1','webster');
  win.__ankiDictionaryPronunciation='webster';
  win.eval(script);win.eval(script);
  const icon=doc.querySelector('.phonetic-accent-us');
  const notice='美式韦氏未收录，此词使用牛津录音';
  assert.equal(icon.disabled,false);
  assert.equal(doc.querySelector('[data-accent-source="us"]').value,'webster');
  assert.equal(doc.querySelector('.accent-status-us').textContent,notice);
  assert.match(icon.getAttribute('aria-label'),/美式发音.*牛津/);
  icon.click();assert.equal(calls.filter(x=>x==='o-us.mp3').length,1);
  win.__ankiPreviewWordPlayback.audio.onended();
  assert.equal(doc.querySelector('.accent-status-us').textContent,notice);
  assert.equal(win.localStorage.getItem('anki-dictionary-pronunciation-v1'),'webster');
  doc.querySelector('audio[src="o-us.mp3"]').setAttribute('data-dictionary-accent','uk');
  win.eval(script);
  assert.equal(icon.disabled,true);
  assert.match(doc.querySelector('.accent-status-us').textContent,/暂无录音/);
});

test('missing US Oxford still requires its own declared supplementary source', t => {
  const oldV2 = fs.readFileSync(path.join(__dirname, 'fixtures/phonetic-labels-v2-before-brand-lanes.js'), 'utf8');
  for (const [choice, missing, other] of [['oxford','o-us.mp3','w-us.mp3']]) {
    const {dom,calls}=accentSetup('data-fallback-us-oxford="webster" data-fallback-us-webster="oxford"');
    t.after(()=>dom.window.close());
    const win=dom.window,doc=win.document;
    win.eval(oldV2);
    doc.querySelector('audio[src="'+missing+'"]').remove();
    win.__ankiDictionaryPronunciation=choice;
    win.eval(script);win.eval(script);
    const button=doc.querySelector('.phonetic-accent-us');
    assert.equal(button.disabled,true);
    button.click();assert.equal(calls.includes(other),false);
    assert.match(doc.querySelector('.accent-status-us').textContent,/暂无录音/);
    const select=doc.querySelector('[data-accent-source="us"]');
    select.value=choice==='oxford'?'webster':'oxford';
    select.dispatchEvent(new win.Event('change',{bubbles:true}));
    button.click();assert.equal(calls.at(-1),other);
  }
});

test('Webster fallback covers older cards without a declaration and keeps native Webster first', t => {
  const {dom,calls}=accentSetup();t.after(()=>dom.window.close());
  const win=dom.window,doc=win.document;
  win.__ankiDictionaryPronunciation='webster';win.eval(script);
  doc.querySelector('.phonetic-accent-us').click();assert.equal(calls.at(-1),'w-us.mp3');
  win.__ankiStopPreviewWord();
  doc.querySelector('audio[src="w-us.mp3"]').remove();win.eval(script);
  doc.querySelector('.phonetic-accent-us').click();assert.equal(calls.at(-1),'o-us.mp3');
  assert.equal(doc.querySelector('[data-accent-source="us"]').value,'webster');
  win.__ankiPreviewWordPlayback.audio.onended();
  assert.match(doc.querySelector('.accent-status-us').textContent,/美式韦氏未收录.*牛津/);
});

test('UK cross-dictionary fallback and shared Cambridge US fallback remain available', t => {
  const {dom,calls}=accentSetup('data-fallback-uk-cambridge="oxford" data-fallback-us-oxford="cambridge" data-fallback-us-webster="cambridge"');
  t.after(()=>dom.window.close());
  const win=dom.window,doc=win.document;
  doc.querySelector('audio[src="c-uk.mp3"]').remove();
  doc.querySelectorAll('audio[data-dictionary-accent="us"]').forEach(x=>x.remove());
  doc.querySelector('.dictionary-word-audio').insertAdjacentHTML('beforeend','<audio src="c-us.mp3" data-dictionary-source="cambridge" data-dictionary-accent="us"></audio>');
  win.eval(script);
  doc.querySelector('.phonetic-accent-uk').click();assert.equal(calls.at(-1),'o-uk.mp3');
  const select=doc.querySelector('[data-accent-source="us"]');
  for(const choice of ['oxford','webster']) {
    select.value=choice;select.dispatchEvent(new win.Event('change',{bubbles:true}));
    doc.querySelector('.phonetic-accent-us').click();assert.equal(calls.at(-1),'c-us.mp3');
    assert.match(doc.querySelector('.accent-status-us').textContent,/美式剑桥/);
  }
});

test('US preference is retained across upgrade and reused webview binds one player', t => {
  const {dom, calls} = accentSetup(); t.after(() => dom.window.close());
  const win = dom.window, doc = win.document;
  win.localStorage.setItem('anki-dictionary-pronunciation-v1', 'webster');
  win.__ankiDictionaryPronunciation = null;
  win.eval(legacy); win.eval(script); win.eval(script);
  assert.equal(doc.querySelector('[data-accent-source="us"]').value, 'webster');
  doc.querySelector('.phonetic-accent-us').click(); assert.deepEqual(calls, ['w-us.mp3']);
  doc.querySelector('#preview-flip').click(); assert.equal(win.__ankiPreviewWordPlayback, null);
  assert.equal(doc.querySelector('.phonetic-accent-us').getAttribute('aria-pressed'), 'false');
  doc.querySelector('#preview-front').innerHTML = accentFace('');
  win.eval(legacy); win.eval(script);
  doc.querySelector('.phonetic-accent-us').click();
  assert.equal(calls.filter(x => x === 'w-us.mp3').length, 2);
  assert.equal(doc.querySelectorAll('.pronunciation-settings').length, 1);
  assert.equal(doc.querySelectorAll('[data-accent-source]').length, 2);
});

test('completion and playback errors reset icon and allow retry', async t => {
  const {dom, calls} = accentSetup(); t.after(() => dom.window.close());
  const doc = dom.window.document, uk = doc.querySelector('.phonetic-accent-uk');
  uk.click(); dom.window.__ankiPreviewWordPlayback.audio.onended();
  assert.equal(uk.getAttribute('aria-pressed'), 'false'); assert.equal(dom.window.__ankiPreviewWordPlayback, null);
  uk.click(); dom.window.__ankiPreviewWordPlayback.audio.onerror();
  assert.match(doc.querySelector('.accent-status-uk').textContent, /暂不可用/);
  uk.click(); assert.equal(calls.at(-1), 'c-uk.mp3');
});

test('verified supplementary fallback keeps actual source labels and original selectors', t => {
  for (const [source, label] of [['collins', '柯林斯'], ['wiktionary', '维基词典'], ['forvo', 'Forvo']]) {
    const {dom, calls} = accentSetup('data-fallback-uk-cambridge="' + source + '" data-fallback-us-oxford="' + source + '"');
    t.after(() => dom.window.close());
    const doc = dom.window.document;
    doc.querySelectorAll('audio').forEach(audio => audio.remove());
    const block = doc.querySelector('.dictionary-word-audio');
    block.insertAdjacentHTML('beforeend', '<audio src="extra-uk.mp3" data-dictionary-source="' + source + '" data-dictionary-accent="uk"></audio>'
      + '<audio src="extra-us.mp3" data-dictionary-source="' + source + '" data-dictionary-accent="us"></audio>');
    dom.window.eval(script);
    assert.deepEqual(Array.from(doc.querySelectorAll('[data-accent-source="uk"] option'), el => el.value), ['cambridge', 'oxford']);
    assert.deepEqual(Array.from(doc.querySelectorAll('[data-accent-source="us"] option'), el => el.value), ['oxford', 'webster']);
    assert.match(doc.querySelector('.accent-status-uk').textContent, new RegExp('使用' + label + '录音'));
    assert.match(doc.querySelector('.phonetic-accent-uk').getAttribute('aria-label'), new RegExp(label));
    doc.querySelector('.phonetic-accent-uk').click(); assert.equal(calls.at(-1), 'extra-uk.mp3');
    doc.querySelector('.phonetic-accent-us').click(); assert.equal(calls.at(-1), 'extra-us.mp3');
    assert.match(doc.querySelector('.accent-status-us').textContent, new RegExp('美式' + label));
  }
});

test('supplementary fallback rejects an undeclared source and the wrong accent', t => {
  for (const [source, accent] of [['forvo', 'us'], ['untrusted', 'uk']]) {
    const {dom, calls} = accentSetup('data-fallback-uk-cambridge="' + source + '"');
    t.after(() => dom.window.close());
    const doc = dom.window.document;
    doc.querySelectorAll('audio').forEach(audio => audio.remove());
    doc.querySelector('.dictionary-word-audio').insertAdjacentHTML('beforeend', '<audio src="extra.mp3" data-dictionary-source="' + source + '" data-dictionary-accent="' + accent + '"></audio>');
    dom.window.eval(script);
    assert.equal(doc.querySelector('.phonetic-accent-uk').disabled, true);
    doc.querySelector('.phonetic-accent-uk').click(); assert.equal(calls.length, 0);
  }
});

test('an already open v1 Anki webview upgrades to new sources without stale or duplicate playback', t => {
  const frozenV1 = fs.readFileSync(path.join(__dirname, 'fixtures/phonetic-labels-v1.js'), 'utf8');
  const dom = new JSDOM('<body><div id="qa">' + accentFace('') + '</div></body>',
    {runScripts:'outside-only',url:'http://localhost/'});
  t.after(()=>dom.window.close());
  const win=dom.window,doc=win.document,calls=[];
  win.HTMLMediaElement.prototype.play=function(){calls.push(this.getAttribute('src'));return Promise.resolve();};
  win.HTMLMediaElement.prototype.pause=function(){};
  win.eval(legacy);win.eval(frozenV1);
  assert.equal(win.__ankiPhoneticLabelsV1,true);
  const fresh=()=>accentFace('data-fallback-uk-cambridge="wiktionary" data-fallback-uk-oxford="wiktionary" data-fallback-us-oxford="cambridge" data-fallback-us-webster="cambridge"')
    .replace(/<audio[^>]+><\/audio>/g,'')
    .replace('</div></main>','<audio src="wiki-uk.mp3" data-dictionary-source="wiktionary" data-dictionary-accent="uk"></audio>'
      +'<audio src="cambridge-us.mp3" data-dictionary-source="cambridge" data-dictionary-accent="us"></audio></div></main>');
  for(let face=0;face<2;face++) {
    doc.getElementById('qa').innerHTML=fresh();
    win.eval(legacy);win.eval(script);win.eval(script);
    for(const [accent,choice,expected] of [['uk','oxford','wiki-uk.mp3'],['us','webster','cambridge-us.mp3']]) {
      const select=doc.querySelector('[data-accent-source="'+accent+'"]');
      select.value=choice;select.dispatchEvent(new win.Event('change',{bubbles:true}));
      const icon=doc.querySelector('.phonetic-accent-'+accent);
      assert.equal(icon.disabled,false);
      const before=calls.length;icon.click();
      assert.equal(calls.length,before+1);assert.equal(calls.at(-1),expected);
      icon.click();assert.equal(calls.length,before+1);
      assert.equal(win.localStorage.getItem(accent==='uk'?'anki-dictionary-uk-pronunciation-v1':'anki-dictionary-pronunciation-v1'),choice);
    }
    win.dispatchEvent(new win.StorageEvent('storage',{key:null}));
    assert.equal(doc.querySelector('.phonetic-accent-uk').disabled,false);
    assert.equal(doc.querySelector('.phonetic-accent-us').disabled,false);
    assert.equal(doc.querySelectorAll('.pronunciation-settings').length,1);
  }
});
