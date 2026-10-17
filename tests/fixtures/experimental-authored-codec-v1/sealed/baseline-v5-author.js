(function(){'use strict';
/* Approved codecs create an ordinary literal; standard reflection intrinsics
 * belong to the audited realm. Eligibility never reads mapping/getter values.
 * Unknown accessors/coercions/prototypes retain the original all-class scan. */
function compactClassCandidates(root, classes) {
  var selector = '[class]';
  try {
    var prototype = Object.getPrototypeOf(classes);
    if (prototype === Object.prototype && Object.getPrototypeOf(prototype) === null) {
      var own = Object.getOwnPropertyNames(classes);
      var inherited = Object.getOwnPropertyNames(prototype);
      var functionPrototype = Function.prototype;
      var stringifier = Object.getOwnPropertyDescriptor(functionPrototype, 'toString');
      var stringifierValue = stringifier && Object.getOwnPropertyDescriptor(stringifier, 'value');
      var safe = own.length + inherited.length <= 128 && Object.getOwnPropertySymbols(prototype).length === 0 &&
        Object.getPrototypeOf(functionPrototype) === prototype &&
        !Object.getOwnPropertyDescriptor(functionPrototype, Symbol.toPrimitive) &&
        !Object.getOwnPropertyDescriptor(functionPrototype, 'valueOf') &&
        !!stringifierValue && typeof stringifierValue.value === 'function';
      var token = /^[A-Za-z0-9_-]{1,64}$/;
      function nativeFunction(value, name) {
        if (typeof value !== 'function') return false;
        var nativeText = Function.prototype.toString.call(value);
        return (nativeText === 'function ' + name + '() { [native code] }' ||
          nativeText === 'function ' + name + '() {\n    [native code]\n}') &&
          Object.getPrototypeOf(value) === functionPrototype &&
          !Object.getOwnPropertyDescriptor(value, 'toString') &&
          !Object.getOwnPropertyDescriptor(value, 'valueOf') &&
          !Object.getOwnPropertyDescriptor(value, Symbol.toPrimitive);
      }
      for (var i = 0; safe && i < own.length; i++) {
        var alias = Object.getOwnPropertyDescriptor(classes, own[i]);
        var ownValue = Object.getOwnPropertyDescriptor(alias, 'value');
        safe = token.test(own[i]) && own[i].indexOf('_r') === 0 &&
          !!ownValue && typeof ownValue.value === 'string';
      }
      for (var n = 0; safe && n < inherited.length; n++) {
        var name = inherited[n], description = Object.getOwnPropertyDescriptor(prototype, name);
        var data = Object.getOwnPropertyDescriptor(description, 'value');
        safe = token.test(name);
        if (safe && data) {
          var value = data.value;
          var standard = ['constructor','__defineGetter__','__defineSetter__','hasOwnProperty',
            '__lookupGetter__','__lookupSetter__','isPrototypeOf','propertyIsEnumerable',
            'toString','valueOf','toLocaleString'];
          safe = typeof value === 'string' ||
            (standard.indexOf(name) !== -1 && nativeFunction(value, name === 'constructor' ? 'Object' : name));
        } else if (safe) {
          // The stock __proto__ accessor is pure; any custom accessor can add
          // aliases to a later ordinary node that the original NodeList owns.
          safe = name === '__proto__' && description.enumerable === false &&
            nativeFunction(description.get, 'get __proto__') &&
            nativeFunction(description.set, 'set __proto__');
        }
      }
      if (safe) {
        var selectors = [];
        for (var k = 0; k < own.length + inherited.length; k++) {
          var mappedName = k < own.length ? own[k] : inherited[k - own.length];
          selectors.push(/^[A-Za-z_][A-Za-z0-9_-]*$/.test(mappedName) ?
            '.' + mappedName : '[class~="' + mappedName + '"]');
        }
        selector = selectors.join(',');
      }
    }
  } catch (_) {
    // Failed eligibility retains the original query and original error order.
  }
  var candidates = root.querySelectorAll(selector);
  if (selector === '[class]') return candidates;
  try {
    // Use native Element operations without reading node-owned accessors.
    // Adopted ordinary elements may retain a different realm's prototypes.
    var elementPrototype = Element.prototype;
    var localName = Object.getOwnPropertyDescriptor(elementPrototype, 'localName').get;
    var hasAttribute = Object.getOwnPropertyDescriptor(elementPrototype, 'hasAttribute').value;
    var closest = Object.getOwnPropertyDescriptor(elementPrototype, 'closest').value;
    function ordinaryElement(node) {
      var actualPrototype = Object.getPrototypeOf(node);
      var constructor = Object.getOwnPropertyDescriptor(actualPrototype, 'constructor');
      var value = constructor && Object.getOwnPropertyDescriptor(constructor, 'value');
      if (!value || typeof value.value !== 'function') return false;
      var ctor = value.value;
      var declaredPrototype = Object.getOwnPropertyDescriptor(ctor, 'prototype');
      var declaredName = Object.getOwnPropertyDescriptor(ctor, 'name');
      if (!declaredPrototype || !Object.prototype.hasOwnProperty.call(declaredPrototype, 'value') ||
          declaredPrototype.value !== actualPrototype || !declaredName ||
          !Object.prototype.hasOwnProperty.call(declaredName, 'value') ||
          typeof declaredName.value !== 'string' || !/^(HTML[A-Za-z0-9_]*Element|SVG[A-Za-z0-9_]*Element|MathML[A-Za-z0-9_]*Element|Element)$/.test(declaredName.value)) return false;
      var text = Function.prototype.toString.call(ctor), name = declaredName.value;
      if (text !== 'function ' + name + '() { [native code] }' &&
          text !== 'function ' + name + '() {\n    [native code]\n}') return false;
      return Reflect.apply(localName, node, []).indexOf('-') === -1 &&
        !Reflect.apply(hasAttribute, node, ['is']);
    }
    for (var c = 0; c < candidates.length; c++) {
      var node = candidates[c];
      if (!ordinaryElement(node)) return root.querySelectorAll('[class]');
      var card = Reflect.apply(closest, node, ['.vocab-card']);
      if (card && !ordinaryElement(card)) return root.querySelectorAll('[class]');
    }
  } catch (_) {
    return root.querySelectorAll('[class]');
  }
  return candidates;
}
var config={"classes":{"_r0":"exam-frequency","_r1":"field-title","_r2":"frequency-summary","_r3":"frequency-count","_r4":"frequency-coverage","_r5":"frequency-rating","_r6":"frequency-star","_r7":"frequency-star-track","_r8":"frequency-star-fill","_r9":"frequency-score","_r10":"frequency-definition-title","_r11":"dictionary-definition","_r12":"sense-row","_r13":"sense-pos","_r14":"sense-text","_r15":"etymology-section","_r16":"etymology-entry","_r17":"etymology-source-frame","_r18":"level-list","_r19":"dictionary-form-groups","_r20":"dictionary-forms","_r21":"dictionary-inflections","_r22":"forms-list","_r23":"form-row","_r24":"dictionary-derived","_r25":"derived-word","_r26":"dictionary-word-audio","_r27":"word-audio-status","_r28":"example-card","_r29":"example-heading","_r30":"index-tag","_r31":"example-text","_r32":"target-word","_r33":"sentence-jump","_r34":"example-translation","_r35":"translate-tag","_r36":"example-source","_r37":"sentence-status","_r38":"cloze-answer","_r39":"dictionary-source","_r40":"dictionary-missing","_r41":"sense-unlabelled","_r42":"definition-source-notice","_r43":"audio-supplement-credits","_r44":"source-variant-notice"},"origins":["http://localhost:8765"],"attributes":{"class":"sentence-jump","data-reader":"latex","target":"_blank","rel":"noopener","aria-label":"跳转到真题原句","title":"跳转到真题原句"},"icon":"\u003csvg viewBox=\"0 0 24 24\" aria-hidden=\"true\">\u003cpath fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\" d=\"M14 4h6v6M20 4L10 14M10 4H4v16h16v-6\"/>\u003c/svg>","keys":["anki-codex-sentence","anki-codex-hash","anki-codex-review","anki-codex-en","anki-codex-context"]};
compactClassCandidates(document,config.classes).forEach(function(el){Array.from(el.classList).forEach(function(name){if(config.classes[name]){var card=el.closest('.vocab-card');if(card)card.classList.add('rb-compact-note');el.classList.remove(name);el.classList.add(config.classes[name]);}});});
document.querySelectorAll('span[_c]').forEach(function(el){var value=el.getAttribute('_c');if(!/^[ez]\d+(,\d+)*$/.test(value))return;el.classList.add('card-chunk');el.setAttribute('data-chunk-side',value[0]==='e'?'en':'zh');el.setAttribute('data-chunk-ids',value.slice(1).replace(/,/g,' '));el.removeAttribute('_c');});
function hex(value){if(!/^[A-Za-z0-9_-]{43}$/.test(value))throw new Error('Invalid source hash');var raw=atob(value.replace(/-/g,'+').replace(/_/g,'/')+'=');if(raw.length!==32)throw new Error('Invalid source hash length');return Array.from(raw).map(function(x){return x.charCodeAt(0).toString(16).padStart(2,'0');}).join('');}
document.querySelectorAll('a[data-rb-j]').forEach(function(el){try{var p=el.getAttribute('data-rb-j').split('|');if(p.length<6||p.length>7||!/^\d+$/.test(p[0])||!/^\d{4}-\d{2}$/.test(p[1])||!config.origins[+p[0]])throw new Error('Invalid source identity');var origin=config.origins[+p[0]],paper=p[1],spans=p[5]?p[5].split(';').map(function(x){if(!/^\d+,\d+$/.test(x))throw new Error('Invalid source range');return x.split(',').map(Number);}):[];var v=['kaoyan%3A'+paper+'%3A'+p[2],hex(p[3]),hex(p[4]),encodeURIComponent(JSON.stringify(spans))];if(p.length===7)v.push(p[6]);var query=v.map(function(x,i){return config.keys[i]+'='+x;}).join('&');var latex=origin+'/english-exams-reflow-latex/kaoyan/papers/'+paper+'.htm?'+query,full=origin+'/exam-library/practice/full-paper.htm?paper=kaoyan%3A'+paper+'&'+query;Object.keys(config.attributes).forEach(function(k){el.setAttribute(k,config.attributes[k]);});el.setAttribute('href',latex);el.setAttribute('data-latex-url',latex);el.setAttribute('data-full-paper-url',full);el.innerHTML=config.icon;el.removeAttribute('aria-disabled');el.removeAttribute('data-rb-j');}catch(_){el.removeAttribute('href');el.setAttribute('aria-disabled','true');el.title='真题定位数据无法读取';}});
})();
(function(){
const key='__ankiCigenFrames';if(window[key]){window[key].refresh();return;}
const known=new WeakSet(),visible=new WeakSet();const selector='iframe.etymology-source-frame';
function prepare(frame){const section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section');if(!section||!meaning)return;const levels=[...meaning.children].find(item=>item.classList.contains('level-section'));if(levels&&(section.parentElement!==meaning||section.previousElementSibling!==levels))levels.after(section);if(section.style.marginTop!=='0.2rem'||section.style.marginBottom!=='0.65rem')section.style.margin='.2rem 0 .65rem';const sample=meaning.querySelector('.form-row')||meaning.querySelector('.primary-definition .field-content');if(sample){const text=getComputedStyle(sample);if(frame.style.fontSize!==text.fontSize)frame.style.fontSize=text.fontSize;if(frame.style.lineHeight!==text.lineHeight)frame.style.lineHeight=text.lineHeight;}}
function theme(frame){const meaning=frame.closest('.meaning-section');if(!meaning)return;const text=getComputedStyle(frame),title=meaning.querySelector('.primary-definition .field-title'),callout=meaning.querySelector('.field-callout'),tag=meaning.querySelector('.level-list li');const metrics={'--ety-text-size':text.fontSize,'--ety-text-line':text.lineHeight};if(title){const style=getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':style.fontSize,'--ety-title-line':style.lineHeight,'--ety-title-gap':style.marginBottom});}if(callout)metrics['--ety-section-space']=getComputedStyle(callout).paddingTop;if(tag){const style=getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':style.fontSize,'--ety-tag-line':style.lineHeight,'--ety-tag-padding':style.padding,'--ety-tag-gap':getComputedStyle(tag.parentElement).gap});}frame.contentWindow.postMessage({type:'cigen:theme',metrics},'*');}
function layout(frame){prepare(frame);if(!frame.contentWindow||frame.getBoundingClientRect().width<=0)return;if(!visible.has(frame)){visible.add(frame);frame.style.height='320px';frame.srcdoc=frame.getAttribute('srcdoc');return;}const style=getComputedStyle(frame);frame.contentWindow.postMessage({type:'cigen:layout',font:{fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color}},'*');theme(frame);}
const sizes=new ResizeObserver(entries=>{for(const entry of entries)layout(entry.target);});
function refresh(){for(const frame of document.querySelectorAll(selector)){if(!known.has(frame)){known.add(frame);sizes.observe(frame);frame.addEventListener('load',()=>layout(frame));}layout(frame);}}
window.addEventListener('message',event=>{const data=event.data;if(!data||data.type!=='cigen:size'||!Number.isFinite(data.height)||data.height<=0)return;const frame=[...document.querySelectorAll(selector)].find(item=>item.contentWindow===event.source);if(!frame)return;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value;frame.scrolling='no';frame.style.overflow='hidden';});
new MutationObserver(refresh).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','style','hidden']});
window.addEventListener('resize',refresh);window[key]={refresh};refresh();
})();

// Refresh every time Anki reuses its card webview; bind delegated events once.
(function () {
  var key = 'anki:exam-source-reader:v1';
  var pronunciationKey = 'anki-dictionary-pronunciation-v1';
  function isPronunciation(source) {
    return source === 'oxford' || source === 'webster';
  }
  function pronunciationName(source) {
    return source === 'webster' ? '韦氏' : '牛津';
  }
  function preferredPronunciation(fallback) {
    // Keep an in-memory choice when a webview can read storage but cannot write
    // it. Same-origin changes refresh this value through the storage event.
    var source = window.__ankiDictionaryPronunciation;
    if (!isPronunciation(source)) {
      try { source = localStorage.getItem(pronunciationKey); } catch (_) {}
    }
    if (!isPronunciation(source)) source = isPronunciation(fallback) ? fallback : 'oxford';
    window.__ankiDictionaryPronunciation = source;
    return source;
  }
  function dictionaryRecording(block, source) {
    var found = null;
    block.querySelectorAll('audio').forEach(function (audio) {
      if (!found && audio.dataset.dictionarySource === source && audio.getAttribute('src')) found = audio;
    });
    if (found) return found;
    // A missing source may use another packaged recording only when the build
    // explicitly declares that per-word exception. Never follow a fallback
    // chain or infer that the first audio element has the requested identity.
    var fallback = block.getAttribute('data-fallback-' + source);
    if (!isPronunciation(fallback) || fallback === source) return null;
    block.querySelectorAll('audio').forEach(function (audio) {
      if (!found && audio.dataset.dictionarySource === fallback && audio.getAttribute('src')) found = audio;
    });
    return found;
  }
  function pronunciationException(source, audio) {
    var actual = audio && audio.dataset.dictionarySource;
    return isPronunciation(actual) && actual !== source ? pronunciationName(source) + '未收录，此词使用' + pronunciationName(actual) + '录音' : '';
  }
  function refreshPronunciation() {
    document.querySelectorAll('.dictionary-word-audio').forEach(function (block) {
      // Accent-aware cards own separate UK/US controls and exact-accent tracks.
      if (block.getAttribute('data-accent-playback') === 'v1') return;
      var source = preferredPronunciation(block.dataset.defaultSource);
      var card = block.closest('.vocab-front');
      var heading = card && card.querySelector('.card-heading');
      var setting = block.querySelector('.dictionary-audio-setting') || heading && heading.querySelector('.dictionary-audio-setting');
      // Keep the source setting in the same top row as metadata, independently
      // of the centered word, IPA and replay button. Repeated Anki refreshes
      // reuse the moved label instead of cloning controls or losing its value.
      if (setting && heading && setting.parentElement !== heading) {
        heading.insertBefore(setting, heading.querySelector('.card-meta'));
      }
      var control = setting ? setting.querySelector('.dictionary-audio-source') : block.querySelector('.dictionary-audio-source');
      var button = block.querySelector('.preview-word-play');
      var status = block.querySelector('.word-audio-status');
      var audio = dictionaryRecording(block, source);
      var available = !!audio;
      var exception = pronunciationException(source, audio);
      var actual = audio ? audio.dataset.dictionarySource : source;
      var replayLabel = '播放' + pronunciationName(actual) + '单词发音' + (exception ? '（' + pronunciationName(source) + '未收录）' : '');
      if (control) control.value = source;
      if (button) {
        button.disabled = !available;
        button.setAttribute('aria-disabled', String(!available));
        button.setAttribute('aria-label', replayLabel);
        button.title = available ? replayLabel : pronunciationName(source) + '发音暂无收录';
      }
      if (status) status.textContent = available ? exception : pronunciationName(source) + '发音暂无收录';
    });
  }
  function refreshDefinitions() {
    document.querySelectorAll('.primary-definition').forEach(function (section) {
      var definition = section.querySelector('.dictionary-definition');
      var enriched = !!definition;
      var fromWordbook = definition && definition.getAttribute('data-dictionary') === 'wordbook';
      var fromEcdict = definition && definition.getAttribute('data-dictionary') === 'ecdict';
      var reviewed = definition && definition.getAttribute('data-dictionary') === 'reviewed';
      var title = section.querySelector('.field-title');
      var meanings = section.closest('.meaning-section');
      var secondary = meanings && meanings.querySelector('.secondary-definition');
      if (enriched) section.setAttribute('data-dictionary-definition', 'oxford');
      else section.removeAttribute('data-dictionary-definition');
      if (title) title.textContent = reviewed ? (definition.getAttribute('data-definition-heading') || '核对后的释义') : fromEcdict ? 'ECDICT 释义（牛津未收录）' : fromWordbook ? '词表释义（牛津未收录）' : enriched ? '牛津释义' : '核心释义';
      if (enriched) section.setAttribute('data-definition-source', reviewed ? 'reviewed' : fromEcdict ? 'ecdict' : fromWordbook ? 'wordbook' : 'oxford');
      else section.removeAttribute('data-definition-source');
      if (secondary) secondary.hidden = enriched;
    });
  }
  function refreshForms() {
    document.querySelectorAll('.forms-section').forEach(function (section) {
      var heading = section.querySelector('.field-title');
      // Dictionary forms already supply separate titles for inflections and
      // word-family members. Keep the legacy heading only for ungrouped cards.
      if (heading) heading.hidden = !!section.querySelector('.dictionary-form-groups');
    });
  }
  function firstLine(card) {
    var word = card && card.querySelector('.word');
    if (!word) return '';
    var copy = word.cloneNode(true);
    copy.querySelectorAll('br').forEach(function (br) { br.replaceWith('\n'); });
    return (copy.textContent || '').split(/\r?\n/)[0].trim();
  }
  function isReader(reader) {
    return reader === 'latex' || reader === 'full-paper';
  }
  function preferredReader(fallback) {
    var reader = window.__ankiExamSourceReader;
    if (!isReader(reader)) {
      try { reader = localStorage.getItem(key); } catch (_) {}
    }
    if (!isReader(reader)) reader = isReader(fallback) ? fallback : 'latex';
    window.__ankiExamSourceReader = reader;
    return reader;
  }
  function sourceUrl(value) {
    if (typeof value !== 'string' || /[\u0000-\u0020\u007f]/.test(value)) return '';
    try {
      var url = new URL(value);
      if ((url.protocol === 'http:' || url.protocol === 'https:') && url.hostname && !url.username && !url.password) return value;
    } catch (_) {}
    return '';
  }
  function updateJump(link, reader) {
    var url = sourceUrl(reader === 'latex' ? link.dataset.latexUrl : link.dataset.fullPaperUrl);
    if (url) {
      link.href = url;
      link.removeAttribute('aria-disabled');
    } else {
      link.removeAttribute('href');
      link.setAttribute('aria-disabled', 'true');
    }
    link.title = '在' + (reader === 'latex' ? ' LaTeX 重排版' : '整卷版') + '定位原句';
  }
  function stopPreviewWord(message) {
    var state = window.__ankiPreviewWordPlayback;
    if (!state) return;
    window.__ankiPreviewWordPlayback = null;
    state.audio.onended = null;
    state.audio.onerror = null;
    state.audio.pause();
    try { state.audio.currentTime = 0; } catch (_) {}
    state.button.setAttribute('aria-pressed', 'false');
    if (state.status) state.status.textContent = message || state.restingMessage || '';
  }
  function playPreviewWord(button) {
    var dictionary = button.closest('.dictionary-word-audio');
    var recording = dictionary || button.closest('.recorded-audio');
    var source = dictionary && preferredPronunciation(dictionary.dataset.defaultSource);
    var audio = dictionary ? dictionaryRecording(dictionary, source) : recording && recording.querySelector('audio');
    if (dictionary && !audio) {
      stopPreviewWord();
      refreshPronunciation();
      return;
    }
    if (!audio) return;
    stopPreviewWord();
    var exception = source ? pronunciationException(source, audio) : '';
    var actual = source ? audio.dataset.dictionarySource : '';
    var state = {audio: audio, button: button, status: recording.querySelector('.word-audio-status'), restingMessage: exception};
    window.__ankiPreviewWordPlayback = state;
    button.setAttribute('aria-pressed', 'true');
    if (state.status) state.status.textContent = (exception ? exception + '；' : '') + (actual ? pronunciationName(actual) + '：' : '') + '正在播放单词发音…';
    function finish(message) {
      if (window.__ankiPreviewWordPlayback === state) stopPreviewWord(message);
    }
    audio.onended = function () { finish(''); };
    var unavailable = (actual ? pronunciationName(actual) : '单词') + '发音暂不可用，请重试' + (exception ? '（' + exception + '）' : '');
    audio.onerror = function () { finish(unavailable); };
    try {
      Promise.resolve(audio.play()).catch(function () { finish(unavailable); });
    } catch (_) { finish(unavailable); }
  }
  function refresh() {
    refreshPronunciation();
    refreshDefinitions();
    refreshForms();
    document.querySelectorAll('.vocab-front').forEach(function (card) {
      var link = card.querySelector('.dictionary-link');
      if (!link) return;
      var word = firstLine(card);
      if (word) {
        link.href = 'eudic://x-callback-url/searchword?word=' + encodeURIComponent(word) + '&x-success=anki%3A%2F%2F';
        link.setAttribute('aria-label', '在欧路词典查找 ' + word);
      } else link.removeAttribute('href');
    });
    document.querySelectorAll('.examples-section').forEach(function (section) {
      var first = section.querySelector('.sentence-jump');
      var control = section.querySelector('.source-reader');
      var label = section.querySelector('.source-reader-setting');
      if (!control || !label) return;
      // Let AnkiMobile deliver reader taps to the native select instead of review tap zones.
      control.classList.add('tappable');
      label.classList.add('tappable');
      label.hidden = !first;
      if (!first) return;
      var reader = preferredReader(first.dataset.reader);
      control.value = reader;
      section.querySelectorAll('.sentence-jump').forEach(function (link) {
        updateJump(link, reader);
      });
    });
  }
  // Stop playback from an older template if its webview is still alive.
  if (window.__ankiStopSentence) window.__ankiStopSentence();
  if (window.__ankiStopPreviewWord) window.__ankiStopPreviewWord();
  window.__ankiStopPreviewWord = stopPreviewWord;
  refresh();
  if (window.__ankiLibraryEventsBound) return;
  window.__ankiLibraryEventsBound = true;
  document.addEventListener('change', function (event) {
    if (event.target.matches && event.target.matches('.dictionary-audio-source')) {
      var source = event.target.value;
      if (!isPronunciation(source)) { refreshPronunciation(); return; }
      stopPreviewWord();
      window.__ankiDictionaryPronunciation = source;
      try { localStorage.setItem(pronunciationKey, source); } catch (_) {}
      refreshPronunciation();
      return;
    }
    if (!event.target.matches || !event.target.matches('.source-reader')) return;
    var reader = event.target.value;
    if (!isReader(reader)) { refresh(); return; }
    window.__ankiExamSourceReader = reader;
    try { localStorage.setItem(key, reader); } catch (_) {}
    document.querySelectorAll('.source-reader').forEach(function (control) { control.value = reader; });
    document.querySelectorAll('.sentence-jump').forEach(function (link) {
      updateJump(link, reader);
    });
  });
  if (window.addEventListener) window.addEventListener('storage', function (event) {
    if (event.key !== pronunciationKey && event.key !== null) return;
    stopPreviewWord();
    window.__ankiDictionaryPronunciation = isPronunciation(event.newValue) ? event.newValue : null;
    refreshPronunciation();
  });
  document.addEventListener('click', function (event) {
    if (!event.target.closest) return;
    var play = event.target.closest('.preview-word-play');
    if (play) { playPreviewWord(play); return; }
    var flip = event.target.closest('#preview-flip');
    if (!flip) return;
    var front = document.getElementById('preview-front');
    var back = document.getElementById('preview-back');
    if (!front || !back) return;
    stopPreviewWord();
    var showBack = flip.getAttribute('aria-pressed') !== 'true';
    front.hidden = showBack;
    back.hidden = !showBack;
    flip.setAttribute('aria-pressed', String(showBack));
    flip.textContent = showBack ? '返回正面' : '显示答案';
    refresh();
  });
})();

// 2027 admissions: first exam begins 2026-12-19 08:30 Beijing time.
// This fixed helper can also travel in Meta when Anki retains an older model.
(function () {
  var target = Date.parse("2026-12-19T08:30:00+08:00");
  var styleId = "anki-exam-countdown-layout-v2";
  // Keep the upgrade self-contained in retained models. The countdown belongs
  // to the card content, after its translated examples, rather than the window.
  var layoutCss = [
    // The client owns its reviewer shell and scrolling. In AnkiDroid #qa can
    // be nested inside #content; a zero flex basis there collapses the card.
    '.anki-countdown-content{box-sizing:border-box;display:block;flex:none;min-width:0;min-height:0;height:auto;width:100%;max-width:100%;overflow:visible}',
    '.anki-countdown-content .exam-countdown{position:static!important;inset:auto!important;z-index:auto!important;transform:none!important;box-sizing:border-box;width:fit-content!important;max-width:100%!important;margin:.35rem 0 0 auto!important;padding:0!important;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;color:var(--pink,#b51c83);font-size:.8rem;line-height:1.6;text-align:right;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;pointer-events:none}'
  ].join('\n');
  function stop() {
    if (window.__ankiExamTimer) clearInterval(window.__ankiExamTimer);
    window.__ankiExamTimer = null;
  }
  function ownsHost(state) {
    return state && window.__ankiExamCountdownState === state
      && document.documentElement.contains(state.host)
      && state.content.parentElement === state.host && state.footer.parentElement === state.footerHost
      && state.content.contains(state.footer);
  }
  function release(state) {
    if (!state) return;
    if (state.observer) state.observer.disconnect();
    if (window.__ankiExamCountdownState !== state) return;
    clearInterval(state.timer);
    var activeFooter = document.querySelector('.exam-countdown');
    // A retained model may have replaced our interval. Clear that old timer
    // when no other note owns a footer, while leaving a foreign timer alone.
    if (window.__ankiExamTimer === state.timer || !activeFooter || activeFooter === state.footer) stop();
    // Remove our countdown before unwrapping, including a plain-card fallback
    // whose footerHost is the content wrapper itself.
    if (state.footer.parentElement === state.footerHost) state.footer.remove();
    if (state.content.parentElement === state.host) {
      while (state.content.firstChild) state.host.insertBefore(state.content.firstChild, state.content);
      state.content.remove();
    }
    // Older helpers may have taken over the document layout. Release only
    // the classes they owned when upgrading a still-mounted card.
    (state.classes || []).forEach(function (item) {
      if (!item.present) item.node.classList.remove(item.name);
    });
    if (document.getElementById(styleId) === state.style) {
      if (state.styleText === null) state.style.remove();
      else state.style.textContent = state.styleText;
    }
    window.__ankiExamCountdownState = null;
  }
  function mount() {
    var previous = window.__ankiExamCountdownState;
    if (previous && (!ownsHost(previous) || previous.layoutVersion !== 3)) release(previous);
    stop();
    var state = window.__ankiExamCountdownState;
    var host = document.getElementById('qa') || document.getElementById('content') || document.body;
    if (!host) return;
    var style = document.getElementById(styleId);
    var styleText = style ? style.textContent : null;
    if (!style) {
      style = document.createElement('style');
      style.id = styleId;
      (document.head || document.body).appendChild(style);
    }
    style.textContent = layoutCss;
    var content = null;
    Array.from(host.children).some(function (node) {
      if (node.classList.contains('anki-countdown-content')) { content = node; return true; }
      return false;
    });
    if (!content) {
      content = document.createElement('div');
      content.className = 'anki-countdown-content';
      // Anki iterates a live script collection. Keep the field helper before
      // the trailing card initializer when its containing card is wrapped.
      host.insertBefore(content, host.firstChild);
    }
    var footer = host.querySelector('.exam-countdown') || document.querySelector('.exam-countdown');
    if (!footer) {
      footer = document.createElement('div');
      footer.className = 'exam-countdown';
    }
    footer.setAttribute('role', 'timer');
    footer.setAttribute('aria-live', 'off');
    footer.title = '2027 考研初试：2026年12月19日 08:30（北京时间）';
    document.querySelectorAll('.exam-countdown').forEach(function (node) {
      if (node !== footer) node.remove();
    });
    Array.from(host.childNodes).forEach(function (node) {
      if (node === content || node === footer || /^(SCRIPT|STYLE|LINK)$/.test(node.nodeName)) return;
      content.appendChild(node);
    });
    var footerHost = content.querySelector('.examples-section') || content.querySelector('.vocab-back')
      || content.querySelector('.vocab-front') || content;
    footerHost.appendChild(footer);
    if (!state) {
      state = { host: host, content: content, footer: footer, footerHost: footerHost, style: style,
                styleText: styleText, layoutVersion: 3, timer: null, observer: null, observing: false };
      window.__ankiExamCountdownState = state;
      // This lifecycle is independent of either timer: it still runs when the
      // retained model replaced our interval or the target has already passed.
      state.observer = new MutationObserver(function () {
        if (window.__ankiExamCountdownState !== state) { state.observer.disconnect(); return; }
        if (!ownsHost(state)) { release(state); return; }
      });
    }
    if (!state.observing) {
      state.observer.observe(document.body, { childList: true, subtree: true });
      state.observing = true;
    }
    function render() {
      var seconds = Math.max(0, Math.ceil((target - Date.now()) / 1000));
      if (!seconds) { footer.textContent = '2027 考研初试已开始'; return false; }
      footer.textContent = '2027 考研倒计时：' + Math.floor(seconds / 86400) + '天 '
        + String(Math.floor(seconds % 86400 / 3600)).padStart(2, '0') + '时 '
        + String(Math.floor(seconds % 3600 / 60)).padStart(2, '0') + '分 '
        + String(seconds % 60).padStart(2, '0') + '秒';
      return true;
    }
    if (render()) {
      var timer = setInterval(function () {
        if (!ownsHost(state)) { release(state); return; }
        if (document.querySelector('.exam-countdown') !== footer || !render()) {
          clearInterval(timer);
          if (window.__ankiExamTimer === timer) window.__ankiExamTimer = null;
        }
      }, 1000);
      state.timer = timer;
      window.__ankiExamTimer = timer;
    }
  }
  window.__ankiExamCountdownMount = mount;
  window.__ankiExamCountdownCleanup = function () {
    var state = window.__ankiExamCountdownState;
    if (ownsHost(state)) {
      stop();
      state.observer.disconnect();
      state.observing = false;
    }
    else release(state);
  };
  window.__ankiExamCountdownResume = function () {
    var state = window.__ankiExamCountdownState;
    if (ownsHost(state)) mount();
    else release(state);
  };
  if (!window.__ankiExamCountdownLifecycleBound) {
    window.__ankiExamCountdownLifecycleBound = true;
    window.addEventListener('pagehide', function () { window.__ankiExamCountdownCleanup(); });
    window.addEventListener('pageshow', function () { window.__ankiExamCountdownResume(); });
  }
  if (document.readyState === 'loading') {
    var pendingHost = document.getElementById('qa') || document.getElementById('content') || document.body;
    window.__ankiExamCountdownPending = {
      host: pendingHost, anchor: pendingHost && (pendingHost.querySelector('.vocab-card') || pendingHost.firstElementChild)
    };
    if (!window.__ankiExamCountdownReadyBound) {
      window.__ankiExamCountdownReadyBound = true;
      document.addEventListener('DOMContentLoaded', function () {
        window.__ankiExamCountdownReadyBound = false;
        var pending = window.__ankiExamCountdownPending;
        window.__ankiExamCountdownPending = null;
        if (!pending || !pending.host || !document.documentElement.contains(pending.host)
            || pending.anchor && !pending.host.contains(pending.anchor)) return;
        window.__ankiExamCountdownMount();
      }, { once: true });
    }
  } else mount();
})();

// Rendered spans contain only validated, existing chunk IDs. Never match words
// or translations here; the shared Python renderer owns exact text/range checks.
(function () {
  function element(value) {
    return value && typeof value.closest === 'function' ? value : value && value.parentElement;
  }
  function ids(chunk) {
    var value = chunk && chunk.dataset.chunkIds;
    return typeof value === 'string' && /^\d+( \d+)*$/.test(value) ? value.split(' ') : [];
  }
  function choice(value) {
    var target = element(value);
    // Preserve source navigation, audio, controls, and disclosure behavior even
    // if a future template places one inside a chunk span.
    if (!target || typeof target.closest !== 'function' ||
        target.closest('a, button, input, select, textarea, summary, audio, video, [role="button"], [contenteditable]')) return null;
    var chunk = target.closest('.card-chunk');
    var candidates = ids(chunk);
    var side = chunk && chunk.dataset.chunkSide;
    var root = chunk && chunk.closest('.example-card');
    if (!root || !candidates.length || (side !== 'en' && side !== 'zh')) return null;
    return { root: root, ids: candidates, side: side };
  }
  function selectedIds(selected) {
    // An English overlap retains its authored first-ID priority. A Chinese
    // span can name several equally confirmed English chunks.
    var values = selected.side === 'en' ? selected.ids.slice(0, 1) : selected.ids.slice();
    return values.filter(function (id, index) { return values.indexOf(id) === index; }).sort();
  }
  function same(left, right) {
    if (!left || !right || left.root !== right.root) return false;
    var leftIds = selectedIds(left), rightIds = selectedIds(right);
    return leftIds.length === rightIds.length && leftIds.every(function (id, index) {
      return id === rightIds[index];
    });
  }
  function clear() {
    var state = window.__ankiCardChunkState;
    if (state) state.root.querySelectorAll('.card-chunk').forEach(function (chunk) {
      chunk.classList.remove('card-chunk-active');
    });
    window.__ankiCardChunkState = null;
  }
  function activate(selected, mode) {
    clear();
    var activeIds = selectedIds(selected);
    selected.root.querySelectorAll('.card-chunk').forEach(function (chunk) {
      var chunkIds = ids(chunk);
      chunk.classList.toggle('card-chunk-active', activeIds.some(function (id) {
        return chunkIds.indexOf(id) !== -1;
      }));
    });
    window.__ankiCardChunkState = { root: selected.root, ids: selected.ids, side: selected.side, mode: mode };
  }
  // Anki reuses the webview between card sides and cards. Clear old state while
  // keeping one delegated event set that can also handle newly inserted spans.
  clear();
  document.querySelectorAll('.card-chunk-active').forEach(function (chunk) {
    chunk.classList.remove('card-chunk-active');
  });
  if (window.__ankiCardChunksBound) return;
  window.__ankiCardChunksBound = true;
  var ignoreMouseUntil = 0;
  function mouse(event) {
    return (!event.pointerType || event.pointerType === 'mouse') && Date.now() >= ignoreMouseUntil;
  }
  function over(event) {
    if (!mouse(event)) return;
    var selected = choice(event.target);
    if (selected) {
      if (!same(selected, window.__ankiCardChunkState)) activate(selected, 'hover');
    } else if (window.__ankiCardChunkState && window.__ankiCardChunkState.mode === 'hover') clear();
  }
  function out(event) {
    if (!mouse(event)) return;
    var state = window.__ankiCardChunkState;
    if (state && state.mode === 'hover' && same(choice(event.target), state) &&
        !same(choice(event.relatedTarget), state)) clear();
  }
  if (window.PointerEvent) {
    document.addEventListener('pointerover', over);
    document.addEventListener('pointerout', out);
  } else {
    document.addEventListener('mouseover', over);
    document.addEventListener('mouseout', out);
    document.addEventListener('touchstart', function () { ignoreMouseUntil = Date.now() + 1000; }, { passive: true });
  }
  document.addEventListener('click', function (event) {
    var selected = choice(event.target);
    if (!selected) { clear(); return; }
    var state = window.__ankiCardChunkState;
    if (same(selected, state) && state.mode === 'tap') clear();
    else activate(selected, 'tap');
    // Capture prevents a chunk tap from reaching an Anki/card flip handler.
    // Other clicks retain their native default and propagation.
    event.preventDefault();
    event.stopPropagation();
  }, true);
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') clear();
  });
})();

