(function(){
  'use strict';
  var defaults={"theme":"light","fontSize":18,"lineHeight":1.8,"fontFamily":"system","cardWidth":1120,"wordSize":48,"phoneticSize":24,"showIntervals":true,"showRatingHints":true,"showQueueCounts":true,"showTimer":true,"showPosition":true,"showPhonetics":true,"showSources":true,"showFrequency":true,"showTags":true,"showEtymology":true,"showForms":true,"showExamples":true,"showCountdown":true,"spaceAction":"flip","autoplay":"off","autoplayBack":"off","ukSource":"keep","usSource":"keep","audioVolume":100,"audioRate":1,"audioBalance":true,"lookup":"eudic","selectionLookup":false,"newOrder":"original","newPosition":"after","reviewOrder":"due","learningSteps":"1,10","relearningSteps":"10"};
  var value=Object.assign({},defaults);
  function el(tag,text){var n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  function select(form,key,label,choices){var row=el('label',label);var input=el('select');input.name=key;input.id='pref-'+key;choices.forEach(function(c){input.append(new Option(c[1],c[0]));});row.append(input);form.append(row);}
  function input(form,key,label,type,min,max,step){var row=el('label',label);var n=el('input');n.name=key;n.id='pref-'+key;n.type=type;if(min!==undefined){n.min=min;n.max=max;n.step=step;}row.append(n);form.append(row);}
  function render(host){
    host.replaceChildren();host.className='preferences-grid';
    var groups={};
    [['display','卡片显示'],['content','学习内容'],['audio','发音与播放'],['schedule','学习顺序与步骤'],['interaction','复习交互'],['query','查词']].forEach(function(pair){
      var field=el('fieldset');field.id='preferences-'+pair[0];field.append(el('legend',pair[1]));groups[pair[0]]=field;host.append(field);
    });
    var display=groups.display,content=groups.content,audio=groups.audio,schedule=groups.schedule,interaction=groups.interaction,query=groups.query;
    select(display,'theme','主题',[['light','浅色'],['dark','深色'],['system','跟随系统']]);
    select(display,'fontFamily','正文字体',[['system','系统字体'],['serif','衬线字体']]);
    input(display,'cardWidth','学习区最大宽度 (px)','number',720,1440,10);
    input(display,'wordSize','正面单词大小 (px)','number',24,96,1);
    input(display,'phoneticSize','音标大小 (px)','number',14,40,1);
    input(display,'fontSize','正文大小 (px)','number',14,28,1);
    input(display,'lineHeight','正文行距','number',1.4,2.4,.1);
    [['showPosition','显示书中位置'],['showPhonetics','显示音标文字'],['showSources','显示卡片上的音源选择'],['showFrequency','显示真题词频'],['showTags','显示考试等级'],['showForms','显示词形变化'],['showEtymology','显示词根与词源'],['showExamples','显示真题例句'],['showCountdown','显示考研倒计时']].forEach(function(row){input(content,row[0],row[1],'checkbox');});
    select(audio,'autoplay','进入正面时播放',[['off','关闭'],['uk','英式发音'],['us','美式发音']]);
    select(audio,'autoplayBack','显示答案时播放',[['off','关闭'],['uk','英式发音'],['us','美式发音']]);
    select(audio,'ukSource','英式音源',[['keep','沿用卡片偏好'],['cambridge','剑桥'],['oxford','牛津']]);
    select(audio,'usSource','美式音源',[['keep','沿用卡片偏好'],['oxford','牛津'],['webster','韦氏']]);
    input(audio,'audioVolume','录音音量 (%)','number',0,100,5);input(audio,'audioRate','录音播放速度','number',.5,1.5,.05);
    input(audio,'audioBalance','英美响度均衡','checkbox');
    var balanceHelp=el('p','按词典音源统一调整英美响度。原录音保留，关闭后恢复原声。');balanceHelp.className='preference-help';audio.append(balanceHelp);
    select(schedule,'newOrder','新词顺序',[['original','原书顺序'],['alphabetical','按单词字母排序'],['random','每天固定的随机顺序']]);
    select(schedule,'newPosition','新词与复习卡片',[['after','先复习，再学新词'],['before','先学新词，再复习'],['mixed','复习和新词交替']]);
    select(schedule,'reviewOrder','复习卡片顺序',[['due','按到期时间'],['original','按原书顺序']]);
    input(schedule,'learningSteps','新词学习步骤 (分钟)','text');input(schedule,'relearningSteps','忘词重学步骤 (分钟)','text');
    var help=el('p','步骤用逗号分隔，例如 1,10 或 2,20。学习中的到期卡片始终优先；每日额度仍按整本书计算。');help.className='preference-help';schedule.append(help);
    select(interaction,'spaceAction','背面按空格 / 回车',[['flip','返回正面'],['good','评分为良好（Anki 方式）']]);
    [['showIntervals','显示评分后的复习间隔'],['showRatingHints','显示评分说明与按键提示'],['showQueueCounts','显示待学数量'],['showTimer','显示本轮学习计时']].forEach(function(row){input(interaction,row[0],row[1],'checkbox');});
    select(query,'lookup','查词工具',[['eudic','欧路词典 App'],['oxford','牛津在线'],['cambridge','剑桥在线'],['webster','韦氏在线'],['off','隐藏查词按钮']]);
    input(query,'selectionLookup','选中英文后显示查词按钮','checkbox');fill();
  }
  function fill(prefs){var values=prefs||value;Object.keys(defaults).forEach(function(k){var n=document.getElementById('pref-'+k);if(n){if(n.type==='checkbox')n.checked=values[k];else n.value=values[k];}});}
  function theme(){return value.theme==='system'?(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):value.theme;}
  function set(prefs){value=Object.assign({},defaults,prefs||{});document.documentElement.dataset.theme=theme();document.documentElement.dataset.intervals=String(value.showIntervals);document.documentElement.style.setProperty('--study-width',value.cardWidth+'px');['showRatingHints','showQueueCounts','showTimer','showPosition'].forEach(function(k){document.documentElement.dataset[k]=String(value[k]);});fill();}
  function read(){var result={};Object.keys(defaults).forEach(function(k){var n=document.getElementById('pref-'+k);result[k]=n.type==='checkbox'?n.checked:n.type==='number'?Number(n.value):n.value;});return result;}
  function lookup(word){var q=encodeURIComponent(word.trim());return value.lookup==='eudic'?'eudic://x-callback-url/searchword?word='+q:value.lookup==='oxford'?'https://www.oxfordlearnersdictionaries.com/search/english/?q='+q:value.lookup==='cambridge'?'https://dictionary.cambridge.org/zhs/词典/英语-汉语-简体/'+q:'https://www.merriam-webster.com/dictionary/'+q;}
  function applyFrame(doc,word){var style=doc.getElementById('study-preferences-style');if(!style){style=doc.createElement('style');style.id='study-preferences-style';doc.head.append(style);}
    var dark=theme()==='dark';
    var font=value.fontFamily==='serif'?'Georgia,"Noto Serif",serif':'-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif';
    var rules=['html{font-size:'+value.fontSize+'px!important}',
      'body,.field-content,.example-text,.example-translation,.sense-text,.etymology-sentence{line-height:'+value.lineHeight+'!important;font-family:'+font+'!important}',
      '#preview-front .word{font-size:min('+value.wordSize+'px,10vw)!important;line-height:1.2!important}',
      '.phonetic-line{font-size:'+value.phoneticSize+'px!important}',
      '.selection-lookup{position:fixed;right:16px;bottom:16px;z-index:100;min-height:44px;padding:10px 16px;border-radius:8px;background:#215fbb;color:white!important;font:14px system-ui;text-decoration:none;box-shadow:0 3px 12px #0002}.selection-lookup[hidden]{display:none!important}'];
    var sections={showPosition:'.card-meta',showPhonetics:'.phonetic-accent-value',showSources:'.pronunciation-settings',showFrequency:'.exam-frequency',showTags:'.level-section',showForms:'.forms-section',showEtymology:'.etymology-section',showExamples:'.examples-section',showCountdown:'.exam-countdown'};
    Object.keys(sections).forEach(function(k){if(!value[k])rules.push(sections[k]+'{display:none!important}');});
    style.textContent=rules.join('\n')+(dark?'html,body,#preview-front,#preview-back{background:#18212e!important;color:#e3eaf4!important}.vocab-card,.front-box,.meaning-section,.examples li,.field-callout,.field-content,.memory-example,.root-memory-example{background:#202c3c!important;color:#e3eaf4!important;border-color:#394c65!important}.word,.sense-text,.example-text,.example-translation,.field-content,.root-memory-word,.frequency-count strong{color:#e3eaf4!important}.card-meta,.example-source,.exam-tags,.sense-pos,.frequency-coverage,.frequency-score{color:#adbed3!important}.primary-definition h2,.primary-definition h3,.primary-definition h4,#preview-back h2,#preview-back h3,#preview-back h4,.section-title,.frequency-label,.exam-frequency-label,.etymology-heading,.field-title,.field-label,.definition-source,.examples-heading{color:#b4c9e4!important}.definition-source,.etymology-heading a{color:#84b5ff!important}select{background:#263449!important;color:#e3eaf4!important}':'');
    function applyAudio(audio){audio.volume=value.audioVolume/100;audio.playbackRate=value.audioRate;}
    doc.querySelectorAll('audio').forEach(applyAudio);
    if(!doc.documentElement.dataset.studyAudioBound){doc.documentElement.dataset.studyAudioBound='true';doc.addEventListener('play',function(e){if(e.target.tagName==='AUDIO')applyAudio(e.target);},true);}
    doc.querySelectorAll('.dictionary-link').forEach(function(link){link.hidden=value.lookup==='off';if(value.lookup!=='off'){link.href=lookup(word);link.target=value.lookup==='eudic'?'_self':'_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label','查找 '+word);}});
    ['uk','us'].forEach(function(accent){var source=value[accent+'Source'];doc.querySelectorAll('[data-accent-source="'+accent+'"]').forEach(function(select){if(source!=='keep'&&select.value!==source){select.value=source;select.dispatchEvent(new doc.defaultView.Event('change',{bubbles:true}));}});});
    balanceAudio(doc);
    if(!doc.getElementById('selection-lookup')){var link=doc.createElement('a');link.id='selection-lookup';link.className='selection-lookup';link.hidden=true;link.rel='noopener noreferrer';doc.body.append(link);var refresh=function(){var text=doc.defaultView.getSelection().toString().trim();if(!value.selectionLookup||value.lookup==='off'||!text||text.length>80||!/[a-zA-Z]/.test(text)){link.hidden=true;return;}link.textContent='查词：'+text;link.href=lookup(text);link.target=value.lookup==='eudic'?'_self':'_blank';link.hidden=false;};doc.addEventListener('selectionchange',refresh);doc.addEventListener('click',function(e){if(e.target.closest&&e.target.closest('#preview-flip'))link.hidden=true;});}
    var selectionLink=doc.getElementById('selection-lookup');if(!value.selectionLookup||value.lookup==='off')selectionLink.hidden=true;
  }
  function balanceAudio(doc){
    // Restore old on-demand URLs before enabling the shared template rules.
    doc.querySelectorAll('audio[data-study-original-src]').forEach(function(audio){
      var original=audio.dataset.studyOriginalSrc;
      if(original&&audio.getAttribute('src')!==original)audio.setAttribute('src',original);
      delete audio.dataset.studyOriginalSrc;
    });
    if(doc.defaultView.AnkiAudioLoudness){
      doc.defaultView.AnkiAudioLoudness.refresh();
      doc.defaultView.AnkiAudioLoudness.setEnabled(value.audioBalance);
    }
  }
  function play(doc,accent){var btn=doc.querySelector('#preview-front .phonetic-accent-'+accent);if(!btn)btn=doc.querySelector('#preview-front .word-audio-play');if(btn&&!btn.disabled){btn.click();return true;}return false;}
  window.StudyPreferences={defaults:defaults,resetForm:function(){fill(defaults);},set:set,get:function(){return value;},read:read,render:render,applyFrame:applyFrame,play:play,lookup:lookup};
  if(window.matchMedia){window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change',function(){document.documentElement.dataset.theme=theme();document.dispatchEvent(new Event('study-theme-change'));});}
}());
