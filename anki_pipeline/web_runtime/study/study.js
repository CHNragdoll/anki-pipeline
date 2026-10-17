(function () {
  'use strict';

  var elements = {};
  document.querySelectorAll('[id]').forEach(function (element) { elements[element.id] = element; });
  var state = { books: [], book: null, deck: 'all', session: null, frame: null, busy: false,
    pendingAnswer: null, retry: null, restore: null, statsGeneration: 0, dueTimer: null, shownAt: 0, refreshOnResume: false };
  var focusNext = false;
  var overviewMode = new URLSearchParams(location.search).get('view') === 'overview';
  var paused = false, activeMs = 0, activeStarted = null, sessionMs = 0;
  var cardTools = StudyCardTools.create(elements['card-tools'], api, function(){return {book:state.book,deck:state.deck,advance:true};}, function(result,action){
    if(action==='bury'||action==='suspend') {focusNext=true;applySession(result.session);} else {state.session=result.session;updateControls();renderFlag();}
  });
  StudyPreferences.render(elements['preferences-fields']);
  function settingPage(page){
    elements['settings-nav'].querySelectorAll('button').forEach(function(n){n.setAttribute('aria-pressed',String(n.dataset.settingPage===page));});
    elements['statistics-section'].hidden=page!=='stats';elements['backup-section'].hidden=page!=='backup';elements['book-settings-section'].hidden=page!=='schedule';
    elements['preference-section'].hidden=page==='stats'||page==='backup';
    elements['preferences-fields'].querySelectorAll('fieldset').forEach(function(n){n.hidden=n.id!=='preferences-'+page;});
    elements['preferences-heading'].textContent=page==='schedule'?'学习偏好（所有词书）':'本机偏好';
    elements['study-panel'].scrollTop=0;
  }
  elements['settings-nav'].addEventListener('click',function(e){var n=e.target.closest('[data-setting-page]');if(n&&!state.busy&&!state.restore)settingPage(n.dataset.settingPage);});
  elements['preferences-form'].addEventListener('invalid',function(e){var group=e.target.closest('fieldset');if(group)settingPage(group.id.replace('preferences-',''));},true);
  settingPage('schedule');
  function tick(){
    var running = Boolean(state.frame && state.frame.ready && !document.hidden && !state.busy && !state.pendingAnswer && !state.restore && !overviewMode && !paused && !elements['study-panel'].open && !elements['card-tools'].open);
    var now=performance.now();if(activeStarted!==null){var delta=now-activeStarted;activeMs+=delta;sessionMs+=delta;}activeStarted=running?now:null;
    var seconds=Math.floor(sessionMs/1000);elements['study-timer'].textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');
  }
  var timer=window.setInterval(tick,500);
  function renderFlag(){var flag=state.session&&state.session.card&&state.session.card.controls&&state.session.card.controls.flag;elements['card-flag'].hidden=!flag;elements['card-flag'].textContent=flag?StudyCardTools.flagNames[flag]+'标记':'';elements['card-flag'].dataset.flag=String(flag||0);}
  function renderView(){
    elements['deck-overview'].hidden=!overviewMode;elements['card-stage'].hidden=overviewMode;elements['show-answer'].closest('.answer-bar').hidden=overviewMode;
    elements['start-session'].disabled=!state.session||!state.session.card||state.busy;elements['show-overview'].hidden=overviewMode;elements['overview-description'].textContent=book()?StudyScope.label(book(),state.deck)+' · 新词'+({original:'按原书顺序',alphabetical:'按字母排序',random:'按每日随机顺序'})[StudyPreferences.get().newOrder]+'；学习中的到期卡片优先。':'';
    if(state.session){elements['start-session'].disabled=!state.session.card||state.busy;elements['start-session'].textContent=state.session.counts.todayReviews?'继续学习':'开始学习';elements['overview-next'].textContent=state.session.card?'本范围本轮可学 '+(state.session.counts.new+state.session.counts.learning+state.session.counts.due)+' 张。':'当前没有可学卡片，可检查学习范围、额度或到期时间。';}
    tick();
  }
  function toggleOverview(value){if(state.busy||state.pendingAnswer||state.restore)return;overviewMode=value;paused=false;elements['pause-overlay'].hidden=true;writeLocation();renderView();if(value)loadStats();else {tick();elements['card-stage'].focus({preventScroll:true});}}
  function renderUnits(){var host=elements['overview-units'];host.replaceChildren();var groups=new Map();book().decks.forEach(function(d){var group=d.unit||'单元';if(!groups.has(group)){var detail=node('details');var summary=node('summary','',group);detail.append(summary);groups.set(group,detail);host.append(detail);}var button=node('button','unit-choice',(d.lesson||d.name)+' · '+count(d.count)+' 张');button.type='button';button.dataset.deck=String(d.id);button.setAttribute('aria-pressed',String(String(d.id)===state.deck));button.addEventListener('click',function(){if(state.busy||state.pendingAnswer)return;state.deck=String(d.id);renderBook();writeLocation();refreshSession(true);});groups.get(group).append(button);});}
  async function savePreferences(event){
    if(event)event.preventDefault();if(state.busy||state.pendingAnswer||state.restore)return;
    clearError();setBusy(true);
    try{
      var before=StudyPreferences.get(), draft=StudyPreferences.read();
      var scheduleChanged=['newOrder','newPosition','reviewOrder','learningSteps','relearningSteps'].some(function(k){return before[k]!==draft[k];});
      if(scheduleChanged){disposeFrame();state.session=null;updateControls();}
      var result=await api('/api/study/preferences',{preferences:draft});
      StudyPreferences.set(result.preferences);
      if(scheduleChanged)applySession(await fetchSession());
      else await refreshCardPreferences();
      elements['preferences-status'].textContent=scheduleChanged?'偏好已保存，学习队列和评分间隔已更新。':'偏好已保存，已应用到当前卡片。';
      updateControls();
    }catch(e){elements['preferences-status'].textContent='偏好保存或重新读取未确认：'+e.message;showError(e.message,function(){refreshSession();},'重新读取进度');}
    finally{setBusy(false);}
  }
  var phaseLabels = { new: '新词', learning: '学习中', review: '复习' };
  var ratingNames = ['重来', '困难', '良好', '简单'];
  var responsiveCss = [
    'html.anki-study-card, .anki-study-card body { width:auto; min-width:0; max-width:100%; margin:0; overflow-wrap:anywhere; }',
    '.anki-study-card *, .anki-study-card *::before, .anki-study-card *::after { box-sizing:border-box; }',
    '.anki-study-card #preview-front, .anki-study-card #preview-back, .anki-study-card .vocab-card, .anki-study-card .front-box, .anki-study-card .center-container, .anki-study-card .word-wrapper, .anki-study-card .meaning-section, .anki-study-card .field-callout, .anki-study-card .field-content, .anki-study-card .examples-section, .anki-study-card .examples, .anki-study-card .examples li, .anki-study-card .example-heading, .anki-study-card .examples-bar, .anki-study-card .sense-row, .anki-study-card .forms-list, .anki-study-card .form-row, .anki-study-card .audio-line, .anki-study-card .recorded-audio { min-width:0; max-width:100%; }',
    '.anki-study-card .vocab-front, .anki-study-card .vocab-back { padding-inline:clamp(.65rem,3vw,1.5rem); }',
    '.anki-study-card .front-box { padding-inline:clamp(.75rem,6vw,3.5rem); }',
    '.anki-study-card .meaning-section, .anki-study-card .examples li { padding-inline:clamp(.6rem,3vw,1.3rem); }',
    '.anki-study-card .card-meta, .anki-study-card .word, .anki-study-card .phonetic-line, .anki-study-card .field-content, .anki-study-card .sense-pos, .anki-study-card .sense-text, .anki-study-card .form-row dt, .anki-study-card .form-row dd, .anki-study-card .example-text, .anki-study-card .example-translation, .anki-study-card .example-source, .anki-study-card .sentence-status, .anki-study-card .personal-note { min-width:0; max-width:100%; overflow-wrap:anywhere; word-break:normal; white-space:normal; }',
    '.anki-study-card .word-wrapper { display:inline-grid; grid-template-columns:44px minmax(0,1fr) 44px; column-gap:.4rem; justify-content:center; align-items:start; }',
    '.anki-study-card .word { grid-column:2; } .anki-study-card .dictionary-link { position:static; grid-column:3; align-self:start; max-width:100%; margin-top:-.35rem; }',
    '.anki-study-card .example-heading { flex-wrap:wrap; } .anki-study-card .example-text { flex:1 1 0; }',
    '.anki-study-card .sentence-jump { max-width:100%; margin-right:0; } .anki-study-card .source-reader-setting, .anki-study-card .source-reader { min-width:0; max-width:100%; white-space:normal; }',
    '.anki-study-card img, .anki-study-card audio, .anki-study-card video, .anki-study-card button { max-width:100%; }',
    '.anki-study-card :is(#preview-back,.vocab-back) .vocab-front { padding-block:.6rem .2rem; }',
    '.anki-study-card :is(#preview-back,.vocab-back) .front-box { padding-block:.65rem; border-color:transparent; background:transparent; box-shadow:none; }',
    '.anki-study-card :is(#preview-back,.vocab-back) .center-container { min-height:0; }',
    '.anki-study-card :is(#preview-back,.vocab-back) .word { font-size:2rem; line-height:1.25; }',
    '.anki-study-card :is(#preview-back,.vocab-back) .phonetic-line { font-size:1.25rem; margin-top:.35rem; }',
    '.anki-study-card :is(#preview-back,.vocab-back) hr#answer { margin-block:.35rem; }',
    '@media(max-width:480px) { .anki-study-card .word.anki-study-long-word { font-size:6vw; } }',
    '@media(max-width:300px) { .anki-study-card .word.anki-study-long-word { font-size:1.125rem; } }',
    '@media(max-width:420px) { .anki-study-card .form-row { grid-template-columns:minmax(0,1fr); } }'
  ].join('\n');

  function requireCondition(value, message) { if (!value) throw new Error(message); }
  function nonnegative(value) { return Number.isSafeInteger(value) && value >= 0; }
  function count(value) { return Number(value || 0).toLocaleString('zh-CN'); }
  function node(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function book() { return state.books.find(function (item) { return item.id === state.book; }); }
  function urlFor(value, isCard) {
    requireCondition(typeof value === 'string' && value && !/[\u0000-\u0020\u007f]/.test(value), '服务返回了无效地址');
    var url = new URL(value, window.location.href);
    requireCondition(url.origin === window.location.origin && /^https?:$/.test(url.protocol) && !url.username && !url.password, '卡片和词书地址必须同源');
    if (isCard) requireCondition(/\/web-preview\/[a-z0-9_-]+\/cards\/[a-f0-9]+\.html$/i.test(url.pathname) && !url.search && !url.hash, '卡片地址不属于词书预览');
    return url.href;
  }
  async function api(path, body) {
    var options = { credentials: 'same-origin', cache: 'no-store' };
    if (body !== undefined) {
      options.method = 'POST'; options.headers = { 'Content-Type': 'application/json', 'X-Study-Request': '1' };
      options.body = JSON.stringify(body);
    }
    var response = await fetch(path, options);
    var value;
    try { value = await response.json(); } catch (_) { throw new Error('本地服务未返回有效数据，请检查服务后重试'); }
    if (!response.ok) {
      var error = new Error(value.error || value.message || ('请求失败（HTTP ' + response.status + '）'));
      error.status = response.status; throw error;
    }
    return value;
  }
  function placeMessages() {
    var host = elements['study-panel'].open ? elements['panel-messages'] : elements['message-host'];
    if (elements.notice.parentElement !== host) host.append(elements.notice, elements['error-box']);
  }
  function notice(text) { placeMessages(); elements.notice.textContent = text || ''; elements.notice.hidden = !text; }
  function clearError() { state.retry = null; elements['error-box'].hidden = true; elements['retry-action'].hidden = true; }
  function showError(text, retry, label) {
    placeMessages();
    elements['error-message'].textContent = text;
    state.retry = retry || null; elements['error-box'].hidden = false;
    elements['retry-action'].hidden = !retry; elements['retry-action'].textContent = label || '重试';
    if (elements['study-panel'].open) {
      elements['error-box'].tabIndex = -1;
      elements['error-box'].scrollIntoView({block:'nearest',behavior:'instant'});
      elements['error-box'].focus({preventScroll:true});
    }
  }
  function resumeIfNeeded() {
    if (!state.refreshOnResume || state.busy || state.restore) return;
    state.refreshOnResume = false;
    if (book()) refreshSession(true); else loadOverview();
  }
  function setBusy(value) {
    tick();state.busy = value; updateControls();
    if (!value && state.refreshOnResume) window.setTimeout(resumeIfNeeded, 0);
  }
  function currentFrame(frame) { return state.frame === frame && !frame.failed && !frame.disposed && frame.book === state.book && state.session && state.session.card && frame.cardId === state.session.card.id; }
  function hasAnswer() { var committed = committedState(state.frame); return Boolean(committed && committed.answer); }
  function updateControls() {
    var loaded = Boolean(state.books.length && state.book);
    var locked = state.busy || Boolean(state.pendingAnswer) || Boolean(state.restore) || paused;
    var ready = Boolean(state.frame && currentFrame(state.frame) && state.frame.ready);
    var back = Boolean(ready && hasAnswer());
    elements['show-answer'].closest('.answer-bar').dataset.face = back ? 'back' : 'front';
    elements['open-panel'].disabled = !loaded || locked;
    elements['open-card-tools'].disabled=!ready||locked;elements['pause-study'].disabled=!ready||locked;
    elements['settings-nav'].querySelectorAll('button').forEach(function(n){n.disabled=locked;});
    elements['preferences-form'].querySelectorAll('input,select,button').forEach(function(n){n.disabled=!loaded||locked;});
    renderView();
    elements['close-panel'].disabled = state.busy || Boolean(state.restore);
    elements['book-select'].disabled = !loaded || locked;
    elements['deck-select'].disabled = !loaded || locked;
    elements['show-answer'].disabled = !ready || locked;
    elements['show-answer'].classList.toggle('is-back', back);
    elements['show-answer'].setAttribute('aria-pressed', String(back));
    elements['show-answer'].textContent = back ? '返回正面' : '显示答案';
    if (!back) elements['show-answer'].append(node('kbd', '', '空格'));
    elements.ratings.hidden = !back;
    for (var rating = 1; rating <= 4; rating++) {
      var button = elements['rating-' + rating];
      button.disabled = !back || locked;
      var interval = state.session && state.session.card && state.session.card.intervals.find(function (item) { return item.rating === rating; });
      button.querySelector('.rating-interval').textContent = back && interval ? interval.display + '后' : '';
    }
    elements['undo-answer'].disabled = locked || !state.session || !state.session.canUndo;
    elements['refresh-session'].disabled = !loaded || state.busy || Boolean(state.restore);
    elements['refresh-empty'].disabled = !loaded || locked;
    elements['refresh-stats'].disabled = !loaded || state.busy;
    ['new-per-day', 'review-per-day', 'desired-retention', 'save-settings', 'download-backup', 'restore-file'].forEach(function (id) {
      elements[id].disabled = !loaded || locked;
    });
    elements['retry-action'].disabled = state.busy;
    elements['retry-card'].disabled = state.busy || Boolean(state.pendingAnswer);
    elements['confirm-restore'].disabled = state.busy || !state.restore;
    elements['cancel-restore'].disabled = state.busy;
    elements['rating-hint'].textContent = state.busy ? '正在保存或读取进度…' : state.pendingAnswer ? '当前评分尚未确认，请重试保存或刷新进度。' : back ? '按刚才的回忆评分；没想起来请选择“重来”。' : state.session && !state.session.card ? '这轮已完成，可以浏览全书或查看学习设置。' : (StudyPreferences.get().spaceAction==='good'?'空格 / 回车显示答案，背面按键评分为良好；1–4 选择评分。':'先回忆词义，再显示答案。空格翻面，1–4 评分。');
  }
  function writeLocation() {
    var params = new URLSearchParams(); params.set('book', state.book);
    if (state.deck !== 'all') params.set('deck', state.deck);
    window.history.replaceState(null, '', window.location.pathname + '?' + (overviewMode?'view=overview&':'') + params.toString());
    StudyScope.write(state.book, state.deck);
  }
  function renderBook() {
    var selected = book();
    elements['study-title'].textContent = StudyScope.shortName(selected);
    elements['study-title'].title = selected.name;
    document.title = selected.name + ' · 学习';
    elements['study-subtitle'].textContent = StudyScope.label(selected, state.deck) + ' · 进度独立于 Anki';
    elements['browse-book'].href = urlFor(selected.previewPath, false); elements['browse-book'].hidden = false;
    elements['book-select'].value = selected.id;
    var fragment = document.createDocumentFragment(); fragment.append(new Option('全部范围', 'all'));
    var units = new Map();
    selected.decks.forEach(function (deck) {
      var label = deck.unit || '其他单元';
      if (!units.has(label)) { var group = node('optgroup'); group.label = label; units.set(label, group); fragment.append(group); }
      units.get(label).append(new Option((deck.lesson || deck.name) + ' · ' + count(deck.count) + ' 张', String(deck.id)));
    });
    elements['deck-select'].replaceChildren(fragment); elements['deck-select'].value = state.deck;
    elements['manage-cards'].href='manage.html?book='+encodeURIComponent(state.book)+'&deck='+encodeURIComponent(state.deck);renderUnits();renderView();
  }
  function validateSession(value) {
    requireCondition(value && value.book && value.book.id === state.book && value.deck === state.deck, '学习会话与当前词书或单元不匹配');
    requireCondition(value.counts && ['new', 'learning', 'due', 'todayReviews'].every(function (key) { return nonnegative(value.counts[key]); }) && value.settings, '学习进度格式不完整');
    if (value.card) {
      requireCondition(typeof value.card.id === 'string' && typeof value.card.word === 'string' && nonnegative(value.card.revision) && Array.isArray(value.card.intervals), '当前卡片格式不完整');
      requireCondition(value.card.intervals.length === 4 && [1, 2, 3, 4].every(function (rating) { return value.card.intervals.some(function (item) { return item.rating === rating && typeof item.display === 'string'; }); }), '卡片缺少评分间隔');
      urlFor(value.card.previewUrl, true);
    }
    return value;
  }
  function applySession(value) {
    validateSession(value); state.session = value; state.pendingAnswer = null;
    if(value.preferences)StudyPreferences.set(value.preferences);renderFlag();
    if (state.dueTimer) window.clearTimeout(state.dueTimer);
    ['new', 'learning', 'due'].forEach(function (key) { elements['count-' + key].textContent = count(value.counts[key]); });
    elements['today-count'].textContent = '今日已评分 ' + count(value.counts.todayReviews) + ' 次';
    elements['new-per-day'].value = value.settings.newPerDay;
    elements['review-per-day'].value = value.settings.reviewPerDay;
    elements['desired-retention'].value = Math.round(value.settings.desiredRetention * 100);
    elements['completion'].hidden = Boolean(value.card);
    if (value.card) {
      elements['card-meta'].textContent = value.card.word + (value.card.meta ? ' · ' + value.card.meta : '');
      elements['card-phase'].textContent = phaseLabels[value.card.phase] || '';
      elements['card-stage'].dataset.phase = value.card.phase;
      loadCard(value.card);
    } else {
      disposeFrame(); elements['card-loading'].hidden = true; elements['card-failure'].hidden = true;
      elements['card-stage'].setAttribute('aria-busy', 'false'); elements['card-meta'].textContent = StudyScope.label(book(), state.deck); elements['card-phase'].textContent = '';
      renderCompletion();
    }
    updateControls();
    if (elements['study-panel'].open || overviewMode) loadStats();
  }
  function renderCompletion() {
    if (!state.session || state.session.card) return;
    var reason = state.session.finishedReason;
    var messages = {
      waiting: ['等待下次学习', '当前没有到期卡片，请等待下次学习。学习中的卡片将在到期后继续出现。'],
      'daily-limit': ['今日额度已用完', '当前范围的今日新词或复习已达到每日上限。可调整设置，或明天继续学习。'],
      'no-due': ['当前学习已完成', '当前范围没有需要学习或到期复习的卡片。可以稍后再来。']
    };
    var message = messages[reason] || messages['no-due'];
    elements['completion-title'].textContent = message[0]; elements['completion-message'].textContent = message[1];
    var due = state.session.nextDue ? new Date(state.session.nextDue).getTime() : NaN;
    if (Number.isFinite(due)) {
      var remaining = Math.max(0, due - Date.now());
      var duration = remaining < 60000 ? Math.ceil(remaining / 1000) + ' 秒' : remaining < 3600000 ? Math.ceil(remaining / 60000) + ' 分钟' : Math.ceil(remaining / 3600000) + ' 小时';
      var time = new Date(due).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false });
      elements['next-due'].textContent = '下次到期：' + time + '（北京时间，约 ' + duration + '后）';
      state.dueTimer = window.setTimeout(function () {
        if (!state.session || state.session.card) return;
        if (due <= Date.now() && !state.busy && !state.restore && !document.hidden) refreshSession();
        else renderCompletion();
      }, Math.max(1000, Math.min(30000, remaining)));
    } else elements['next-due'].textContent = '';
  }
  function disposeFrame() {
    if (!state.frame) return;
    var old = state.frame; state.frame = null; old.disposed = true;
    window.clearTimeout(old.timeout);
    old.abort.abort();
    try { if (old.controller) old.controller.dispose(); } finally { old.ready = false; old.commit = null; old.element.remove(); }
  }
  function failFrame(frame) {
    if (!currentFrame(frame)) return;
    window.clearTimeout(frame.timeout); frame.failed = true; frame.ready = false; frame.commit = null;
    frame.abort.abort();
    try { if (frame.controller) frame.controller.dispose(); } catch (_) {}
    frame.element.hidden = true;
    elements['card-loading'].hidden = true; elements['card-failure'].hidden = false; elements['retry-card'].hidden = false;
    elements['card-stage'].setAttribute('aria-busy', 'false'); updateControls();
  }
  function deliveryDescriptor(value, card) {
    requireCondition(value && typeof value === 'object' && !Array.isArray(value) &&
      Object.keys(value).sort().join(',') === 'book,canonical_id,card_id,entry_url,preview_url,schema,wrapper_url', '卡片交付描述不完整');
    requireCondition(value.schema === 'study-card-delivery.v1' && value.book === state.book && value.card_id === card.id &&
      typeof value.canonical_id === 'string' && value.canonical_id.length > 0, '卡片交付身份不匹配');
    var preview = new URL(urlFor(value.preview_url, true));
    requireCondition(preview.pathname === new URL(urlFor(card.previewUrl, true)).pathname, '旧卡片身份已改变');
    var entry = new URL(urlFor(value.entry_url, false)), wrapper = new URL(urlFor(value.wrapper_url, false));
    requireCondition(!entry.search && !entry.hash && /^\/study-catalog-\d{8}\/master-[a-z0-9_-]+-web-v3\/index\.html$/.test(entry.pathname), '未登记的共同词书入口');
    requireCondition(!wrapper.search && !wrapper.hash && wrapper.pathname.startsWith(entry.pathname.slice(0, -10) + 'cards/') &&
      /^cards\/[a-f0-9]{64}\.html$/.test(wrapper.pathname.slice(entry.pathname.length - 10)), '卡片不属于该共同词书');
    entry.search = new URLSearchParams({'study-embed': '1'}).toString();
    entry.hash = new URLSearchParams({card: value.canonical_id}).toString();
    return { id: value.canonical_id, href: entry.href };
  }
  function currentHost(frame) {
    try { return currentFrame(frame) && frame.element.isConnected && frame.element.parentElement === elements['frame-host'] &&
      frame.hostDocument && frame.element.contentDocument === frame.hostDocument &&
      frame.element.contentWindow.location.href === frame.href; } catch (_) { return false; }
  }
  function stateShape(frame, value) {
    return value && value.id === frame.canonicalId && Number.isSafeInteger(value.generation) && value.generation > 0 &&
      (typeof value.viewToken === 'string' && value.viewToken.length > 0 || !value.ready && (value.viewToken === null || value.viewToken === '')) && typeof value.answer === 'boolean' &&
      typeof value.busy === 'boolean' && typeof value.ready === 'boolean' && !(value.busy && value.ready) &&
      (value.document === null || value.document && value.document.nodeType === 9);
  }
  function sameView(left, right) {
    return left && right && ['id', 'generation', 'viewToken', 'answer', 'busy', 'ready', 'document'].every(function (key) { return left[key] === right[key]; });
  }
  function committedState(frame) {
    if (!frame || !currentFrame(frame) || !frame.ready || !frame.controller || !frame.commit) return null;
    if (!currentHost(frame)) { failFrame(frame); return null; }
    try {
      var snapshot = frame.controller.snapshot();
      return stateShape(frame, snapshot) && snapshot.ready && !snapshot.busy && snapshot.document && sameView(snapshot, frame.commit) ? snapshot : null;
    } catch (_) { failFrame(frame); return null; }
  }
  function applyCardPreferences(frame, doc, owner) {
    requireCondition(currentHost(frame) && stateShape(frame, owner) && typeof owner.viewToken === 'string' && owner.viewToken.length > 0 &&
      owner.document === doc && owner.busy && !owner.ready && frame.controller.snapshot().generation === owner.generation, '卡片准备代次已改变');
    doc.documentElement.classList.add('anki-study-card');
    var style = doc.getElementById('anki-study-responsive');
    if (!style) { style = doc.createElement('style'); style.id = 'anki-study-responsive'; doc.head.append(style); }
    style.textContent = responsiveCss;
    doc.querySelectorAll('.word').forEach(function (word) {
      word.classList.toggle('anki-study-long-word', (word.textContent.match(/[A-Za-z]+/g) || []).some(function (token) { return token.length >= 12; }));
    });
    doc.querySelectorAll('.preview-controls').forEach(function (control) { control.hidden = true; });
    StudyPreferences.applyFrame(doc, frame.word);
    frame.prepared.set(doc, { generation: owner.generation, viewToken: owner.viewToken, answer: owner.answer });
  }
  function frameCall(frame, method, argument) {
    if (!currentFrame(frame) || !frame.controller) return Promise.resolve(null);
    var action = ++frame.action;
    frame.ready = false; frame.commit = null;
    elements['card-stage'].setAttribute('aria-busy', 'true'); updateControls();
    try {
      return Promise.resolve(frame.controller[method](argument)).catch(function () {
        if (currentFrame(frame) && frame.action === action) failFrame(frame);
        return null;
      });
    } catch (_) { failFrame(frame); return Promise.resolve(null); }
  }
  function refreshCardPreferences() {
    var frame = state.frame;
    return frame && currentFrame(frame) && frame.controller ? frameCall(frame, 'refresh') : Promise.resolve(null);
  }
  function loadCard(card) {
    disposeFrame(); elements['card-failure'].hidden = true; elements['retry-card'].hidden = true;
    elements['card-loading'].hidden = false; elements['card-loading'].textContent = '正在加载 ' + card.word + '…';
    elements['card-stage'].setAttribute('aria-busy', 'true');
    var element = node('iframe'); element.id = 'card-frame'; element.title = card.word + ' · 学习卡片';
    element.setAttribute('allow', 'autoplay'); element.style.visibility = 'hidden'; element.setAttribute('aria-hidden', 'true');
    var frame = { element: element, book: state.book, cardId: card.id, word: card.word, ready: false, commit: null, document: null,
      hostDocument: null, controller: null, canonicalId: null, href: null, timeout: null, abort: new AbortController(), prepared: new WeakMap(),
      action: 0, seenCommit: false, failed: false, disposed: false };
    state.frame = frame;
    element.addEventListener('error', function () { failFrame(frame); });
    element.addEventListener('load', function () {
      if (!currentFrame(frame) || !frame.href) return;
      try {
        var hostDocument = element.contentDocument;
        if (hostDocument && hostDocument.URL === 'about:blank') return;
        requireCondition(hostDocument && element.contentWindow.location.href === frame.href, '共同词书导航已改变');
        if (frame.controller) { requireCondition(currentHost(frame), '共同词书已重新载入'); return; }
        frame.hostDocument = hostDocument;
        var embed = element.contentWindow.StudyBookEmbed;
        requireCondition(embed && typeof embed.configure === 'function', '共同词书不支持学习嵌入');
        var controller = embed.configure({
          beforePrepare: function (doc, owner) { applyCardPreferences(frame, doc, owner); },
          onBusy: function (value) {
            if (!currentFrame(frame)) return;
            if (!currentHost(frame)) { failFrame(frame); return; }
            if (!stateShape(frame, value) || !sameView(value, frame.controller.snapshot())) return;
            frame.ready = false; frame.commit = null;
            elements['card-loading'].hidden = false; elements['card-stage'].setAttribute('aria-busy', 'true'); updateControls();
          },
          onCommit: function (value) {
            if (!currentFrame(frame)) return;
            if (!currentHost(frame)) { failFrame(frame); return; }
            if (!stateShape(frame, value) || !sameView(value, frame.controller.snapshot()) || !value.ready || value.busy || !value.document) return;
            var prepared = frame.prepared.get(value.document);
            if (!prepared || prepared.generation !== value.generation || prepared.viewToken !== value.viewToken || prepared.answer !== value.answer) { failFrame(frame); return; }
            if (sameView(frame.commit, value)) return;
            frame.commit = { id: value.id, generation: value.generation, viewToken: value.viewToken, answer: value.answer, busy: false, ready: true, document: value.document };
            frame.document = value.document; frame.ready = true;
            if (!frame.seenCommit) { state.shownAt = performance.now(); activeMs = 0; activeStarted = null; frame.seenCommit = true; }
            var autoplay = StudyPreferences.get()[value.answer ? 'autoplayBack' : 'autoplay'];
            if (!overviewMode && !paused && autoplay !== 'off') StudyPreferences.play(value.document, autoplay);
            window.clearTimeout(frame.timeout); element.hidden = false; element.style.removeProperty('visibility'); element.removeAttribute('aria-hidden');
            elements['card-loading'].hidden = true; elements['card-failure'].hidden = true; elements['card-stage'].setAttribute('aria-busy', 'false'); updateControls();
            if (focusNext && !elements['study-panel'].open) { elements['card-stage'].focus({preventScroll:true}); focusNext = false; }
          },
          onError: function (_, value) {
            if (!currentFrame(frame)) return;
            if (!currentHost(frame) || stateShape(frame, value) && sameView(value, frame.controller.snapshot())) failFrame(frame);
          },
          onKey: function (event, value) {
            var committed = committedState(frame);
            if (!committed || !sameView(committed, value)) return false;
            keyboard(event); return event.defaultPrevented;
          }
        });
        requireCondition(controller && ['select', 'show', 'refresh', 'snapshot', 'dispose'].every(function (key) { return typeof controller[key] === 'function'; }), '共同词书能力不完整');
        frame.controller = controller;
        frameCall(frame, 'select', frame.canonicalId);
      } catch (_) { failFrame(frame); }
    });
    frame.timeout = window.setTimeout(function () { failFrame(frame); }, 20000);
    elements['frame-host'].replaceChildren(element); updateControls();
    fetch('/api/study/delivery?book=' + encodeURIComponent(frame.book) + '&card=' + encodeURIComponent(frame.cardId),
      { credentials: 'same-origin', cache: 'no-store', signal: frame.abort.signal }).then(async function (response) {
        requireCondition(response.ok, '读取共同卡片交付失败');
        var value = await response.json();
        if (!currentFrame(frame) || frame.abort.signal.aborted) return;
        var selected = deliveryDescriptor(value, card);
        frame.canonicalId = selected.id; frame.href = selected.href;
        element.getBoundingClientRect(); element.src = selected.href;
      }).catch(function () { failFrame(frame); });
  }
  function flipCard() {
    if (state.busy || state.pendingAnswer || state.restore || !committedState(state.frame)) return;
    var frame = state.frame, answer = !hasAnswer();
    frameCall(frame, 'show', answer);
  }
  async function fetchSession() {
    return api('/api/study/session?book=' + encodeURIComponent(state.book) + '&deck=' + encodeURIComponent(state.deck));
  }
  async function refreshSession(clearCard) {
    if (state.busy || !book() || state.restore) return;
    clearError(); notice(''); setBusy(true);
    if (clearCard) {
      state.session = null; state.pendingAnswer = null; disposeFrame(); elements['completion'].hidden = true;
      elements['card-failure'].hidden = true; elements['card-loading'].hidden = false;
      elements['card-loading'].textContent = '正在读取学习进度…'; elements['card-stage'].setAttribute('aria-busy', 'true');
    }
    try { applySession(await fetchSession()); }
    catch (error) { showError('读取学习进度失败：' + error.message, function () { refreshSession(clearCard); }); }
    finally { setBusy(false); }
  }
  async function loadOverview() {
    if (state.busy) return;
    clearError(); setBusy(true);
    try {
      var value = await api('/api/study/overview');
      requireCondition(value && value.independent === true && Array.isArray(value.books) && value.books.length, '服务未返回独立词书列表');
      value.books.forEach(function (item) {
        requireCondition(typeof item.id === 'string' && typeof item.name === 'string' && Array.isArray(item.decks) && nonnegative(item.cardCount), '词书列表格式不完整');
        urlFor(item.previewPath, false);
      });
      state.books = value.books;
      var query = new URLSearchParams(window.location.search);
      state.book = value.books.some(function (item) { return item.id === query.get('book'); }) ? query.get('book') : value.books[0].id;
      state.deck = query.has('deck') ? (book().decks.some(function (deck) { return String(deck.id) === query.get('deck'); }) ? query.get('deck') : 'all') : StudyScope.deck(state.book, state.books);
      elements['book-select'].replaceChildren.apply(elements['book-select'], value.books.map(function (item) { return new Option(StudyScope.shortName(item), item.id); }));
      renderBook(); writeLocation(); applySession(await fetchSession());
    } catch (error) {
      elements['study-subtitle'].textContent = '学习服务暂时不可用';
      elements['card-loading'].textContent = '请重新读取词书和进度。';
      showError('加载失败：' + error.message, loadOverview, '重新读取');
    } finally { setBusy(false); }
  }
  function requestId() {
    if (window.crypto.randomUUID) return window.crypto.randomUUID();
    return Array.from(window.crypto.getRandomValues(new Uint8Array(16))).map(function (byte) { return byte.toString(16).padStart(2, '0'); }).join('');
  }
  async function submitAnswer(rating, retry) {
    if (state.busy || state.restore || !state.session || !state.session.card) return;
    if (!retry && (!hasAnswer() || state.pendingAnswer)) return;
    if (retry && !state.pendingAnswer) return;
    tick();
    if (!retry) state.pendingAnswer = { book: state.book, deck: state.deck, cardId: state.session.card.id,
      revision: state.session.card.revision, rating: rating, requestId: requestId(), durationMs: Math.min(86400000, Math.max(0, Math.round(activeMs))) };
    clearError(); notice(''); setBusy(true);
    var answeredWord = state.session.card.word; var chosenRating = state.pendingAnswer.rating;
    elements['save-feedback'].hidden = false; elements['save-feedback'].textContent = '正在保存评分…';
    try {
      var saved = await api('/api/study/answer', state.pendingAnswer);
      focusNext = true; applySession(saved);
      elements['save-feedback'].textContent = '已保存：' + answeredWord + ' · ' + ratingNames[chosenRating - 1];
    }
    catch (error) {
      elements['save-feedback'].hidden = true;
      if (error.status === 409) {
        state.pendingAnswer = null;
        notice('学习进度已在其他页面更新，已重新读取当前待学卡片。');
        try { applySession(await fetchSession()); }
        catch (reloadError) { state.session = null; disposeFrame(); showError('重新读取进度失败：' + reloadError.message, function () { refreshSession(true); }); }
      } else showError('评分尚未确认保存，当前卡片已保留：' + error.message, function () { submitAnswer(null, true); }, '重试保存评分');
    } finally { setBusy(false); }
  }
  async function undoAnswer() {
    if (state.busy || state.pendingAnswer || state.restore || !state.session || !state.session.canUndo) return;
    clearError(); setBusy(true);
    try { focusNext = true; applySession(await api('/api/study/undo', { book: state.book, deck: state.deck })); notice('已撤销上一次评分。'); elements['save-feedback'].hidden = true; }
    catch (error) { showError('撤销失败：' + error.message, function () { refreshSession(); }, '刷新进度'); }
    finally { setBusy(false); }
  }
  function renderStatTile(label, value) { var tile = node('div', 'stat-tile'); tile.append(node('span', '', label), node('strong', '', typeof value==='number'?count(value):String(value))); return tile; }
  function renderHistory(id, values, empty) {
    var fragment = document.createDocumentFragment();
    values.forEach(function (entry) { var row = node('div', 'history-row'); row.append(node('span', '', entry.date), node('strong', '', count(entry.count) + ' 次')); fragment.append(row); });
    if (!values.length) fragment.append(node('p', 'muted', empty));
    elements[id].replaceChildren(fragment);
  }
  async function loadStats() {
    if (!book()) return;
    var generation = ++state.statsGeneration; var currentBook = state.book;
    elements['stats-status'].textContent = '正在读取统计…';
    try {
      var value = await api('/api/study/stats?book=' + encodeURIComponent(currentBook));
      if (generation !== state.statsGeneration || currentBook !== state.book) return;
      requireCondition(value && value.summary && Array.isArray(value.days) && Array.isArray(value.ratings) && Array.isArray(value.forecast), '统计格式不完整');
      elements['stats-summary'].replaceChildren(renderStatTile('今日评分', value.summary.today), renderStatTile('累计评分', value.summary.totalReviews), renderStatTile('已学词数', value.summary.studied), renderStatTile('今日可学新词', value.summary.newRemaining));
      if(value.summary.todayTimeMs!==undefined){var time=node('p','muted','今日用时 '+(value.summary.todayTimeMs/60000).toFixed(1)+' 分钟 · 累计 '+(value.summary.totalTimeMs/60000).toFixed(1)+' 分钟 · 平均 '+(value.summary.averageTimeMs/1000).toFixed(1)+' 秒 / 次');elements['stats-summary'].append(time);}
      elements['overview-summary'].replaceChildren(renderStatTile('今日已评分',value.summary.today),renderStatTile('已学词数',value.summary.studied),renderStatTile('今天用时',((value.summary.todayTimeMs||0)/60000).toFixed(1)+' 分钟'),renderStatTile('累计评分',value.summary.totalReviews));
      if(value.distribution){var dist=node('div','state-distribution');Object.entries(value.distribution).forEach(function(pair){dist.append(node('span','',({new:'未学',learning:'学习中',review:'复习',buried:'今天暂缓',suspended:'暂停',flagged:'已标记'})[pair[0]]+' '+count(pair[1])));});elements['stats-summary'].append(dist);}
      elements['stats-ratings'].replaceChildren.apply(elements['stats-ratings'], value.ratings.map(function (entry) { return node('span', '', entry.label + ' ' + count(entry.count)); }));
      renderHistory('stats-days', value.days, '暂无学习记录'); renderHistory('stats-forecast', value.forecast.filter(function (entry) { return entry.count > 0; }), '暂无未来复习');
      elements['stats-status'].textContent = '本书全部单元 · 北京时间 · 到期 ' + count(value.summary.due) + ' 张 / 学习中 ' + count(value.summary.learning) + ' 张';
    } catch (error) { if (generation === state.statsGeneration) elements['stats-status'].textContent = '统计读取失败：' + error.message + '，可点击刷新统计重试。'; }
  }
  async function saveSettings(event) {
    event.preventDefault(); if (state.busy || state.pendingAnswer || state.restore || !book()) return;
    var dailyNew = Number(elements['new-per-day'].value); var dailyReview = Number(elements['review-per-day'].value); var retention = Number(elements['desired-retention'].value) / 100;
    if (![dailyNew, dailyReview].every(function (value) { return nonnegative(value) && value <= 10000; }) || !Number.isFinite(retention) || retention < .7 || retention > .99) {
      showError('每天新词和复习须为 0–10000 的整数，目标记忆率须为 70–99%。'); return;
    }
    clearError(); setBusy(true);
    try {
      var value = await api('/api/study/settings', { book: state.book, newPerDay: dailyNew, reviewPerDay: dailyReview, desiredRetention: retention });
      if (state.deck !== 'all') value = await fetchSession();
      applySession(value); notice('本书的学习设置已保存。');
    } catch (error) { showError('设置保存未确认：' + error.message, function () { refreshSession(); }, '重新读取设置'); }
    finally { setBusy(false); }
  }
  async function downloadBackup() {
    if (state.busy || state.pendingAnswer || state.restore) return;
    clearError(); setBusy(true); elements['backup-status'].textContent = '正在导出所有词书的进度…';
    var href = null;
    try {
      var value = await api('/api/study/backup');
      var blob = new Blob([JSON.stringify(value, null, 2) + '\n'], { type: 'application/json' });
      href = URL.createObjectURL(blob); var link = node('a'); link.href = href;
      link.download = 'web-study-progress-' + new Date().toISOString().replace(/[:.]/g, '-') + '.json';
      document.body.append(link); link.click(); link.remove();
      elements['backup-status'].textContent = '已生成进度备份 JSON，请在浏览器下载记录中确认保存。';
    } catch (error) { elements['backup-status'].textContent = '导出失败。'; showError('备份导出失败：' + error.message, downloadBackup, '重试导出'); }
    finally { if (href) window.setTimeout(function () { URL.revokeObjectURL(href); }, 1000); setBusy(false); }
  }
  function readFile(file) {
    if (typeof file.text === 'function') return file.text();
    return new Promise(function (resolve, reject) { var reader = new FileReader(); reader.onload = function () { resolve(reader.result); }; reader.onerror = function () { reject(new Error('无法读取备份文件')); }; reader.readAsText(file); });
  }
  async function chooseRestore() {
    var file = elements['restore-file'].files[0]; elements['restore-file'].value = '';
    if (!file || state.busy || state.pendingAnswer || state.restore) return;
    clearError(); setBusy(true);
    try {
      var value = JSON.parse(await readFile(file));
      requireCondition(value && value.format === 'independent-web-study' && [1,2].includes(value.schemaVersion) && Array.isArray(value.books), '请选择从本学习服务导出的进度 JSON');
      var cardCount = value.books.reduce(function (total, item) { return total + (Array.isArray(item.cards) ? item.cards.length : 0); }, 0);
      var studiedCount = value.books.reduce(function (total, item) { return total + (Array.isArray(item.cards) ? item.cards.filter(function (card) { return card.scheduler !== null; }).length : 0); }, 0);
      var reviewCount = value.books.reduce(function (total, item) { return total + (Array.isArray(item.reviews) ? item.reviews.filter(function (review) { return !review.undone; }).length : 0); }, 0);
      state.restore = value;
      elements['restore-error'].hidden = true;
      elements['restore-counts'].textContent = '所选文件：' + file.name + '。包含 ' + count(value.books.length) + ' 本词书、' + count(cardCount) + ' 张卡片（' + count(studiedCount) + ' 张已学）、' + count(reviewCount) + ' 次有效评分。所有词书的网页版进度将全部被替换。';
      var dialog = elements['restore-dialog'];
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else { dialog.classList.add('dialog-fallback'); dialog.setAttribute('open', ''); }
      elements['cancel-restore'].focus();
    } catch (error) { showError('备份读取失败：' + error.message); }
    finally { setBusy(false); }
  }
  function closeRestore() {
    if (state.busy) return;
    var dialog = elements['restore-dialog'];
    if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open');
    state.restore = null; updateControls(); elements['restore-file'].focus();
    if (state.refreshOnResume) window.setTimeout(resumeIfNeeded, 0);
  }
  async function confirmRestore() {
    if (state.busy || !state.restore) return;
    clearError(); elements['restore-error'].hidden = true; setBusy(true);
    try {
      var result = await api('/api/study/restore', { backup: state.restore });
      requireCondition(result.restored === true, '恢复结果未确认');
      elements['backup-status'].textContent = '已恢复 ' + count(result.books) + ' 本词书、' + count(result.cards) + ' 条进度。恢复前自动备份：' + result.automaticBackup;
      setBusy(false); closeRestore(); setBusy(true); state.pendingAnswer = null;
      // A restore may replace every current revision; only server data can choose the next card.
      state.session = null; disposeFrame(); elements['completion'].hidden = true;
      elements['card-failure'].hidden = true; elements['card-loading'].hidden = false;
      elements['card-loading'].textContent = '进度已恢复，正在读取待学卡片…';
      try { applySession(await fetchSession()); notice('全部网页版进度已恢复，当前待学卡片已重新读取。'); }
      catch (reloadError) { showError('进度已恢复，待学卡片读取失败：' + reloadError.message, function () { refreshSession(true); }, '重新读取进度'); }
    } catch (error) {
      showError('恢复未确认：' + error.message + '。请先刷新进度核对；失败的恢复会由服务回滚。');
      elements['restore-error'].textContent = '恢复尚未确认：' + error.message + '。可取消后刷新进度核对。'; elements['restore-error'].hidden = false;
      elements['backup-status'].textContent = '恢复结果未确认，请检查错误信息。';
    } finally { setBusy(false); }
  }
  function keyboard(event) {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing || event.repeat || state.restore || paused || overviewMode || elements['study-panel'].open || elements['card-tools'].open) return;
    var target = event.target;
    if (target && target.closest && target.closest('input, textarea, select, audio, video, [contenteditable]:not([contenteditable="false"])')) return;
    if (event.key === ' ' || event.key === 'Spacebar' || event.key === 'Enter') {
      if (target && target.closest && target.closest('button, a[href], summary')) return;
      if (!state.frame || !state.frame.ready || state.busy || state.pendingAnswer) return;
      event.preventDefault();if(hasAnswer()&&StudyPreferences.get().spaceAction==='good')submitAnswer(3,false);else flipCard();
    } else if(event.key.toLowerCase()==='s'){event.preventDefault();toggleOverview(true);
    } else if(event.key.toLowerCase()==='m'&&state.session&&state.session.card&&!state.busy&&!state.pendingAnswer){event.preventDefault();tick();cardTools.open(state.session.card.id);tick();
    } else if(event.key.toLowerCase()==='r'&&state.frame&&state.frame.ready&&!state.busy&&!state.pendingAnswer){event.preventDefault();StudyPreferences.play(state.frame.document,StudyPreferences.get().autoplay==='uk'?'uk':'us');
    } else if (event.key.toLowerCase() === 'z' && !state.busy && !state.pendingAnswer && state.session && state.session.canUndo) {
      event.preventDefault(); undoAnswer();
    } else if (/^[1-4]$/.test(event.key) && hasAnswer() && !state.busy && !state.pendingAnswer) {
      event.preventDefault(); submitAnswer(Number(event.key), false);
    }
  }
  elements['book-select'].addEventListener('change', function () {
    if (state.busy || state.pendingAnswer || state.restore) return;
    state.book = elements['book-select'].value; state.deck = StudyScope.deck(state.book, state.books); elements['save-feedback'].hidden = true; renderBook(); writeLocation(); refreshSession(true);
  });
  elements['deck-select'].addEventListener('change', function () {
    if (state.busy || state.pendingAnswer || state.restore) return;
    state.deck = elements['deck-select'].value; elements['save-feedback'].hidden = true; renderBook(); writeLocation(); refreshSession(true);
  });
  elements['show-answer'].addEventListener('click', flipCard);
  elements['show-overview'].addEventListener('click',function(){toggleOverview(true);});
  elements['start-session'].addEventListener('click',function(){toggleOverview(false);if(state.frame&&state.frame.ready&&StudyPreferences.get().autoplay!=='off')StudyPreferences.play(state.frame.document,StudyPreferences.get().autoplay);});
  elements['overview-settings'].addEventListener('click',function(){elements['open-panel'].click();elements['settings-heading'].scrollIntoView({block:'start'});});
  elements['open-card-tools'].addEventListener('click',function(){if(state.session&&state.session.card){tick();cardTools.open(state.session.card.id);tick();}});
  elements['preferences-form'].addEventListener('submit',savePreferences);
  elements['reset-preferences'].addEventListener('click',function(){StudyPreferences.resetForm();savePreferences();});
  elements['pause-study'].addEventListener('click',function(){tick();paused=true;elements['pause-overlay'].hidden=false;elements['resume-study'].focus();updateControls();});
  elements['resume-study'].addEventListener('click',function(){paused=false;elements['pause-overlay'].hidden=true;activeStarted=null;updateControls();elements['card-stage'].focus({preventScroll:true});});
  elements['unbury-all'].addEventListener('click',async function(){if(state.busy)return;setBusy(true);try{var r=await api('/api/study/card-action',{book:state.book,deck:state.deck,action:'unburyAll',requestId:requestId()});applySession(r.session);notice('本范围今天暂缓的卡片已恢复。');}catch(e){showError(e.message);}finally{setBusy(false);}});
  document.addEventListener('study-theme-change',function(){refreshCardPreferences();});
  for (var rating = 1; rating <= 4; rating++) elements['rating-' + rating].addEventListener('click', function () { submitAnswer(Number(this.dataset.rating), false); });
  elements['retry-action'].addEventListener('click', function () { if (!state.busy && state.retry) state.retry(); });
  elements['retry-card'].addEventListener('click', function () { if (!state.busy && state.session && state.session.card && !state.pendingAnswer) loadCard(state.session.card); });
  elements['refresh-session'].addEventListener('click', function () { refreshSession(); });
  elements['refresh-empty'].addEventListener('click', function () { refreshSession(); });
  elements['undo-answer'].addEventListener('click', undoAnswer);
  elements['settings-form'].addEventListener('submit', saveSettings);
  elements['refresh-stats'].addEventListener('click', loadStats);
  elements['download-backup'].addEventListener('click', downloadBackup);
  elements['restore-file'].addEventListener('change', chooseRestore);
  elements['confirm-restore'].addEventListener('click', confirmRestore);
  elements['cancel-restore'].addEventListener('click', closeRestore);
  elements['restore-dialog'].addEventListener('cancel', function (event) { event.preventDefault(); closeRestore(); });
  elements['open-panel'].addEventListener('click', function () {
    if (state.busy || state.pendingAnswer || state.restore) return;
    tick();elements['study-panel'].showModal();tick(); placeMessages(); loadStats();
  });
  elements['close-panel'].addEventListener('click', function () { if (state.busy || state.restore) return; elements['study-panel'].close(); elements['open-panel'].focus(); });
  elements['study-panel'].addEventListener('click', function (event) {
    if (event.target !== elements['study-panel'] || state.busy || state.restore) return;
    var rect = elements['study-panel'].getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) elements['study-panel'].close();
  });
  elements['study-panel'].addEventListener('close', function(){placeMessages();tick();});
  elements['card-tools'].addEventListener('close',tick);
  elements['study-panel'].addEventListener('cancel', function (event) { if (state.busy || state.restore) event.preventDefault(); });
  document.addEventListener('keydown', keyboard);
  document.addEventListener('visibilitychange', function () {
    tick();
    if (!document.hidden && state.session && !state.session.card && state.session.nextDue && new Date(state.session.nextDue).getTime() <= Date.now()) refreshSession();
  });
  window.addEventListener('pagehide', function () { if (state.dueTimer) window.clearTimeout(state.dueTimer);window.clearInterval(timer);tick();disposeFrame(); updateControls(); });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) { timer=window.setInterval(tick,500);activeStarted=null;state.refreshOnResume = true; resumeIfNeeded(); }
  });
  loadOverview();
})();
