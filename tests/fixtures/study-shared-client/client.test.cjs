'use strict';
// Real legacy UI/business with a bounded capability stub, no HTTP, PG or browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '../../..');
const runtime = path.join(root, 'anki_pipeline/web_runtime/study');
const read = (file) => fs.readFileSync(file, 'utf8');
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise(r => setTimeout(r, 0)); };
const settings = {newPerDay: 20, reviewPerDay: 200, desiredRetention: .9};
const oldId = 'old-A';
const preview = '/web-preview/redbook/cards/' + 'a'.repeat(64) + '.html';
const entry = '/study-catalog-20261015/master-redbook-web-v3/index.html';
function session(id = oldId) {
  return {book: {id:'redbook', name:'红宝书'}, deck:'all', settings, counts:{new:1,learning:0,due:0,todayReviews:0}, canUndo:false,
    nextDue:null, finishedReason:null, card: id === null ? null : {id, word:'move', meta:'Unit 01', revision:7, phase:'new', previewUrl:preview,
      intervals:[1,2,3,4].map(r => ({rating:r,display:'1 分钟',seconds:60,label:'评分'}))}};
}
const descriptor = (id = oldId) => ({schema:'study-card-delivery.v1',book:'redbook',card_id:id,preview_url:preview,
  canonical_id:'guide:canonical/'+id,entry_url:entry,wrapper_url:entry.replace('index.html','cards/'+'b'.repeat(64)+'.html')});
const stats = {summary:{today:0,totalReviews:0,studied:0,newRemaining:1,due:0,learning:0},ratings:[],days:[],forecast:[]};
async function boot(t, options = {}) {
  const dom = new JSDOM(Buffer.from(read(path.join(__dirname,'study.html.base64')).trim(),'base64').toString('utf8'), {url:'http://localhost:8771/web-study/study.html?book=redbook',runScripts:'outside-only',pretendToBeVisual:true});
  t.after(() => dom.window.close());
  const w = dom.window, requests = [], children = [];
  t.after(() => children.forEach(c => c.window.close()));
  w.HTMLElement.prototype.scrollIntoView = function(){};
  w.HTMLDialogElement.prototype.showModal = function(){this.open=true;};
  w.HTMLDialogElement.prototype.close = function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  const c = {window:w, document:w.document, requests, session:session(), descriptor:descriptor(), children, playCount:0};
  w.fetch = async (url, init = {}) => {
    const req = {url:new URL(url,w.location),method:init.method||'GET',body:init.body&&JSON.parse(init.body),options:init}; requests.push(req);
    let value;
    if(options.route) value = await options.route(req,c);
    if(value === undefined) {
      if(req.url.pathname.endsWith('/overview')) value = {independent:true,books:[{id:'redbook',name:'红宝书',cardCount:1,previewPath:'/redbook/index.html',settings,counts:c.session.counts,decks:[{id:'unit-1',name:'Unit 01',unit:'必考词',lesson:'Unit 01',count:1}]}]};
      else if(req.url.pathname.endsWith('/delivery')) value = options.descriptor || {...c.descriptor,card_id:c.session.card.id};
      else if(req.url.pathname.endsWith('/stats')) value = stats;
      else if(req.url.pathname.endsWith('/preferences')) value = {preferences:req.body.preferences};
      else if(req.url.pathname.endsWith('/answer')) value = session(null);
      else value = c.session;
    }
    if(value && value.httpStatus) return {ok:false,status:value.httpStatus,json:async()=>({error:value.message})};
    return {ok:true,status:200,json:async()=>value};
  };
  for (const name of ['scope.js','card-tools.js']) w.eval(read(path.join(__dirname,name)));
  w.eval(read(path.join(runtime,'preferences.js')));
  w.StudyPreferences.play = function(doc,accent){c.playCount++;c.lastPlay={doc,accent};return true;};
  w.eval(read(path.join(runtime,'study.js')));
  await settle();
  c.el = id => w.document.getElementById(id);
  c.frame = () => c.el('card-frame');
  c.click = id => c.el(id).click();
  c.answers = () => requests.filter(r=>r.url.pathname.endsWith('/answer'));
  return c;
}
function authored(c, answer) {
  const dom = new JSDOM('<!doctype html><html><head></head><body><main class="'+(answer?'vocab-back':'vocab-front')+'"><span class="word">move</span><span class="examples-section">原句 chunk 审核</span><button class="word-audio-play">播放</button><input id="note"></main></body></html>',{url:'http://localhost:8771/study-catalog-20261015/master-redbook-web-v3/media/',runScripts:'outside-only'});
  c.children.push(dom); dom.window.HTMLElement.prototype.scrollIntoView=function(){};
  return dom.window.document;
}
async function embed(c) {
  const iframe = c.frame(); assert.ok(iframe,'iframe mounted after delivery');
  const host = iframe.contentWindow;
  let hooks, pending=[], serial=0, disposed=false, generation=1;
  let current={id:c.descriptor.canonical_id,generation,viewToken:'view:0',answer:false,busy:true,ready:false,document:null};
  const calls={select:[],show:[],refresh:0,dispose:0};
  const cap={snapshot(){return {...current};},select(id){calls.select.push(id);current.id=id;return begin(false);},show(answer){calls.show.push(answer);return begin(answer);},refresh(){calls.refresh++;return begin(current.answer);},dispose(){disposed=true;calls.dispose++;pending.splice(0).forEach(r=>r(null));}};
  function begin(answer){current={...current,answer,busy:true,ready:false,viewToken:'view:'+(++serial)};hooks.onBusy({...current});return new Promise(resolve=>pending.push(resolve));}
  host.StudyBookEmbed={configure(value){hooks=value;return cap;}};
  iframe.dispatchEvent(new c.window.Event('load')); await settle();
  const e={iframe,host,cap,calls,get hooks(){return hooks;},get disposed(){return disposed;},state:()=>({...current}),setState(patch){current={...current,...patch};},busy(){hooks.onBusy({...current});},error(){hooks.onError(new Error('authored failure'),{...current});},
    commit(answer=current.answer, customDoc){const doc=customDoc||authored(c,answer);current={...current,answer,busy:true,ready:false};hooks.beforePrepare(doc,{...current,document:doc});current={...current,document:doc,busy:false,ready:true};hooks.onCommit({...current});pending.splice(0).forEach(r=>r({...current}));return doc;},
    key(key,target){const doc=current.document,event=new doc.defaultView.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true});target=target||doc.body;target.addEventListener('keydown',ev=>hooks.onKey(ev,{...current}),{once:true});target.dispatchEvent(event);return event;}};
  return e;
}

test('delivery uses shared entry and canonical capability; no legacy shell', async t=>{
  const c=await boot(t),request=c.requests.find(r=>r.url.pathname.endsWith('/delivery'));
  assert.ok(request,'one descriptor GET is required'); assert.equal(request.method,'GET');
  assert.equal(request.url.searchParams.get('book'),'redbook');assert.equal(request.url.searchParams.get('card'),oldId);
  assert.equal(c.frame().src,'http://localhost:8771'+entry+'?study-embed=1#'+new URLSearchParams({card:c.descriptor.canonical_id}));
  const e=await embed(c);assert.deepEqual(e.calls.select,[c.descriptor.canonical_id]);
  assert.equal(c.el('show-answer').disabled,true);const doc=e.commit(false);assert.equal(c.el('show-answer').disabled,false);
  assert.ok(doc.getElementById('anki-study-responsive'));assert.ok(doc.getElementById('study-preferences-style'));
  assert.equal(c.answers().length,0);
});

test('only complete current back authorizes original scoring identity',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(false);c.click('rating-3');assert.equal(c.answers().length,0);
  c.click('show-answer');assert.deepEqual(e.calls.show,[true]);assert.equal(c.el('show-answer').disabled,true);c.click('rating-3');assert.equal(c.answers().length,0);
  e.commit(true);assert.equal(c.el('rating-3').disabled,false);c.click('rating-3');await settle();
  assert.equal(c.answers().length,1);assert.equal(c.answers()[0].body.cardId,oldId);assert.equal(c.answers()[0].body.book,'redbook');assert.equal(c.answers()[0].body.revision,7);assert.equal(e.disposed,true);
});

test('stale commit and same-card ABA cannot reopen readiness',async t=>{
  const c=await boot(t),a=await embed(c);const old=a.commit(false),oldState=a.state();
  c.click('refresh-session');await settle();const b=await embed(c);b.commit(false);
  a.hooks.onCommit({...oldState,answer:true});a.hooks.onBusy(oldState);a.hooks.onError(new Error('late'),oldState);
  assert.equal(c.el('card-failure').hidden,true);assert.equal(c.el('ratings').hidden,true);assert.equal(c.frame(),b.iframe);assert.equal(a.disposed,true);
  b.setState({viewToken:'new-view',busy:true,ready:false});b.hooks.onCommit({...oldState,document:old,answer:true});
  c.click('rating-3');assert.equal(c.answers().length,0);
});

test('exact current generation view and authored document are required for scoring',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);e.setState({viewToken:'view:new'});
  c.click('rating-3');assert.equal(c.answers().length,0);
  const f=await boot(t),fresh=await embed(f);fresh.commit(true);fresh.setState({document:authored(f,true)});f.click('rating-3');assert.equal(f.answers().length,0);
});

test('preferences refresh clears readiness until the new full commit',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);
  c.el('pref-wordSize').value='64';c.el('preferences-form').dispatchEvent(new c.window.Event('submit',{bubbles:true,cancelable:true}));await settle();
  assert.equal(e.calls.refresh,1);assert.equal(c.el('rating-3').disabled,true);
  const doc=e.commit(true);await settle();assert.match(doc.getElementById('study-preferences-style').textContent,/64px/);assert.equal(c.el('rating-3').disabled,false);
});

test('theme refresh is gated and no postcommit preference observer is installed',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(false);c.document.dispatchEvent(new c.window.Event('study-theme-change'));await settle();
  assert.equal(e.calls.refresh,1);assert.equal(c.el('show-answer').disabled,true);e.commit(false);await settle();assert.equal(c.el('show-answer').disabled,false);
});

test('author key callback reuses keyboard once with no synthetic key or hidden score',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(false);let ev=e.key(' ');assert.equal(ev.defaultPrevented,true);assert.equal(e.calls.show.length,1);assert.equal(c.answers().length,0);
  e.commit(true);ev=e.key(' ',e.state().document.getElementById('note'));assert.equal(ev.defaultPrevented,false);assert.equal(e.calls.show.length,1);
  e.key('r');assert.equal(c.playCount,1);e.key('3');await settle();assert.equal(c.answers().length,1);
});

test('autoplay occurs on committed actual face, never on busy or stale state',async t=>{
  const c=await boot(t),e=await embed(c);c.window.StudyPreferences.set({autoplay:'uk',autoplayBack:'us'});
  assert.equal(c.playCount,0);const front=e.commit(false);assert.equal(c.playCount,1);assert.equal(c.lastPlay.doc,front);
  e.hooks.onCommit(e.state());assert.equal(c.playCount,1);c.click('show-answer');assert.equal(c.playCount,1);const back=e.commit(true);assert.equal(c.playCount,2);assert.equal(c.lastPlay.doc,back);assert.equal(c.lastPlay.accent,'us');
});

test('failure is terminal and disposal cancels descriptor plus capability without scoring',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);e.error();assert.equal(c.el('card-failure').hidden,false);assert.equal(c.el('rating-3').disabled,true);assert.equal(e.disposed,true);
  e.hooks.onCommit(e.state());assert.equal(c.el('card-failure').hidden,false);assert.equal(c.answers().length,0);
  const f=await boot(t);const req=f.requests.find(r=>r.url.pathname.endsWith('/delivery'));f.window.dispatchEvent(new f.window.Event('pagehide'));assert.equal(req.options.signal.aborted,true);assert.equal(f.frame(),null);
});

test('late descriptor cannot replace a newer same-card frame',async t=>{
  let release,number=0;
  const c=await boot(t,{route(req){if(req.url.pathname.endsWith('/delivery')&&++number===1)return new Promise(r=>release=r);}});
  const first=c.requests.find(r=>r.url.pathname.endsWith('/delivery'));c.click('refresh-session');await settle();const current=c.frame();release(descriptor());await settle();
  assert.equal(first.options.signal.aborted,true);assert.equal(c.frame(),current);assert.equal(c.el('card-failure').hidden,true);
});

for (const [name,change] of [
  ['cross-origin entry',d=>{d.entry_url='http://evil.test'+entry;}],['query',d=>{d.entry_url+='?x=1';}],['hash',d=>{d.wrapper_url+='#x';}],
  ['sibling wrapper',d=>{d.wrapper_url=d.wrapper_url.replace('master-redbook-','master-other-');}],['wrong preview',d=>{d.preview_url=d.preview_url.replace('/redbook/','/other/');}],
  ['wrong card',d=>{d.card_id='different';}],['wrong book',d=>{d.book='other';}],['extra key',d=>{d.fallback_url=preview;}],['wrong schema',d=>{d.schema='old';}],
  ['credentials',d=>{d.entry_url='http://user@localhost:8771'+entry;}],['encoded path',d=>{d.entry_url=entry.replace('index','%69ndex');}],
]) test('reject descriptor '+name+' with no legacy fallback',async t=>{
  const value=descriptor();change(value);const c=await boot(t,{descriptor:value});assert.equal(c.el('card-failure').hidden,false);assert.equal(c.el('show-answer').disabled,true);assert.equal(c.frame()&&c.frame().src.includes('/web-preview/'),false);
});

test('host missing API or changed actual entry fails closed',async t=>{
  const c=await boot(t);c.frame().dispatchEvent(new c.window.Event('load'));assert.equal(c.el('card-failure').hidden,false);
  const f=await boot(t),e=await embed(f);e.commit(true);e.host.history.replaceState(null,'',entry+'?study-embed=1#wrong');e.hooks.onCommit(e.state());assert.equal(f.el('card-failure').hidden,false);f.click('rating-3');assert.equal(f.answers().length,0);
});

test('preferences cover actual front and back without source/audio/lookup changes',t=>{
  const outer=new JSDOM('<!doctype html><body></body>',{url:'http://localhost/',runScripts:'outside-only'});t.after(()=>outer.window.close());const w=outer.window;w.eval(read(path.join(runtime,'preferences.js')));
  const dom=new JSDOM('<!doctype html><head></head><body><main class="vocab-back"><span class="word">move</span><div class="examples-section">原句</div><audio></audio><a class="dictionary-link"></a><select data-accent-source="us"><option value="oxford">Oxford</option><option value="webster">Webster</option></select><button class="phonetic-accent-us">audio</button></main></body>',{url:'http://localhost/',runScripts:'outside-only'});t.after(()=>dom.window.close());const doc=dom.window.document;let clicked=0,changed=0;doc.querySelector('button').onclick=()=>clicked++;doc.querySelector('select').onchange=()=>changed++;
  w.StudyPreferences.set({theme:'dark',wordSize:72,audioVolume:35,audioRate:1.25,usSource:'webster',lookup:'oxford',showExamples:false});w.StudyPreferences.applyFrame(doc,'move');
  assert.match(doc.getElementById('study-preferences-style').textContent,/\.vocab-front/);assert.match(doc.getElementById('study-preferences-style').textContent,/\.vocab-back/);
  assert.equal(doc.querySelector('audio').volume,.35);assert.equal(doc.querySelector('audio').playbackRate,1.25);assert.equal(changed,1);assert.match(doc.querySelector('.dictionary-link').href,/oxford/);assert.equal(w.StudyPreferences.play(doc,'us'),true);assert.equal(clicked,1);
});

test('uncommitted empty public token clears ready and initial error fails immediately',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);e.setState({viewToken:null,busy:true,ready:false,document:null});e.busy();
  assert.equal(c.el('show-answer').disabled,true);assert.equal(c.el('rating-3').disabled,true);
  e.setState({busy:false});e.error();assert.equal(c.el('card-failure').hidden,false);
});

test('Space good and Enter preserve one pending original rating request',async t=>{
  let release;
  const c=await boot(t,{route(req){if(req.url.pathname.endsWith('/answer'))return new Promise(r=>release=r);}}),e=await embed(c);
  c.window.StudyPreferences.set({spaceAction:'good'});e.commit(true);e.key('Enter');e.key(' ');await settle();
  assert.equal(c.answers().length,1);assert.equal(c.answers()[0].body.rating,3);assert.equal(c.answers()[0].body.cardId,oldId);assert.match(c.answers()[0].body.requestId,/^[a-f0-9-]+$/);
  release(session(null));await settle();assert.equal(e.disposed,true);
});

test('generation mutation cannot authorize scoring and old beforePrepare cannot write',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);e.setState({generation:2});c.click('rating-3');assert.equal(c.answers().length,0);
  const doc=authored(c,false);assert.throws(()=>e.hooks.beforePrepare(doc,{...e.state(),generation:1,busy:true,ready:false,document:doc}));assert.equal(doc.getElementById('anki-study-responsive'),null);
  c.window.dispatchEvent(new c.window.Event('pagehide'));
  assert.throws(()=>e.hooks.beforePrepare(doc,{...e.state(),busy:true,ready:false,document:doc}));assert.equal(doc.getElementById('anki-study-responsive'),null);
});

test('same entry reload is rejected by actual host Document identity',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);const previous=e.iframe.contentDocument;
  e.iframe.src=e.iframe.src;assert.notEqual(e.iframe.contentDocument,previous);e.hooks.onCommit(e.state());
  assert.equal(c.el('card-failure').hidden,false);assert.equal(c.el('rating-3').disabled,true);assert.equal(e.disposed,true);assert.equal(c.answers().length,0);
});

test('show rejection and snapshot errors disable readiness without a score',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(false);e.cap.show=()=>Promise.reject(new Error('preparation failed'));c.click('show-answer');await settle();
  assert.equal(c.el('card-failure').hidden,false);assert.equal(c.el('show-answer').disabled,true);assert.equal(c.answers().length,0);
  const f=await boot(t),other=await embed(f);other.commit(true);other.cap.snapshot=()=>{throw new Error('revoked');};f.click('rating-3');await settle();
  assert.equal(f.el('card-failure').hidden,false);assert.equal(f.answers().length,0);
});

test('removed or reparented host cannot commit or score',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);c.document.body.append(e.iframe);e.hooks.onCommit(e.state());c.click('rating-3');
  assert.equal(c.answers().length,0);assert.equal(c.el('card-failure').hidden,false);assert.equal(e.disposed,true);
});

test('revoked commit readiness cannot reuse old identity for any action',async t=>{
  const c=await boot(t),e=await embed(c);e.commit(true);e.setState({ready:false,busy:false});c.click('rating-3');c.click('show-answer');
  assert.equal(c.answers().length,0);assert.equal(e.calls.show.length,0);assert.equal(e.key('3').defaultPrevented,false);assert.equal(e.key(' ').defaultPrevented,false);
});

test('legal disclosure changes keep committed fact and original scoring path',async t=>{
  for(const mode of ['button','digit','space-good','enter-good']){
    const c=await boot(t),e=await embed(c);const doc=e.commit(true),detail=doc.createElement('details');detail.innerHTML='<summary>审核依据</summary><p>完整原句</p>';doc.body.append(detail);detail.open=true;
    if(mode.includes('good'))c.window.StudyPreferences.set({spaceAction:'good'});
    if(mode==='button')c.click('rating-3');else e.key(mode==='digit'?'3':mode==='enter-good'?'Enter':' ');
    await settle();assert.equal(c.answers().length,1);assert.equal(c.answers()[0].body.rating,3);assert.equal(e.calls.show.length,0);
  }
});
