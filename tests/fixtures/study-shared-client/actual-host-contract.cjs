'use strict';
// Actual client -> actual HOST -> complete production FRAME. Only same-origin
// transport and jsdom's missing srcdoc navigation are emulated for tiny sources.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {JSDOM,VirtualConsole}=require('jsdom'),{webcrypto}=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8')),root=path.resolve(__dirname,'../../..');
const read=p=>fs.readFileSync(p,'utf8'),tick=()=>new Promise(r=>setTimeout(r,5));
const watchdog=setTimeout(()=>{console.error('Actual shared client did not settle');process.exit(2);},12000);
async function until(check,message){for(let i=0;i<300;i++){if(check())return;await tick();}assert.fail(message);}
const vc=new VirtualConsole(),scriptErrors=[];vc.on('jsdomError',error=>{if(!/Not implemented.*scrollTo/.test(error.message))scriptErrors.push(error.message);});
const page=Buffer.from(read(path.join(__dirname,'study.html.base64')).trim(),'base64').toString('utf8');
const dom=new JSDOM(page,{url:'http://example.test/web-study/study.html?book=redbook',runScripts:'dangerously',pretendToBeVisual:true,virtualConsole:vc});
const outer=dom.window,requestLog=[],events=[],fontStates=new WeakMap(),fullGates=[];
let cap,appFrame,host,frontDoc,backDoc,holdFront=true,holdBack=true,preferences={},observedBack=false;
const scoringMode=input.scoring_mode||'button';
const preview='/web-preview/redbook/cards/'+'c'.repeat(64)+'.html',entry='/study-catalog-20261015/master-redbook-web-v3/index.html';
const settings={newPerDay:20,reviewPerDay:200,desiredRetention:.9};
const current={book:{id:'redbook',name:'红宝书'},deck:'all',settings,counts:{new:1,learning:0,due:0,todayReviews:0},canUndo:false,nextDue:null,
 card:{id:'old-A',word:'move',meta:'Unit 01',revision:7,phase:'new',previewUrl:preview,intervals:[1,2,3,4].map(r=>({rating:r,display:'1 分钟',seconds:60,label:'评分'}))}};
const descriptor={schema:'study-card-delivery.v1',book:'redbook',card_id:'old-A',preview_url:preview,canonical_id:'A',entry_url:entry,wrapper_url:entry.replace('index.html','cards/'+'a'.repeat(64)+'.html')};
const el=id=>outer.document.getElementById(id),answers=()=>requestLog.filter(r=>r.url.pathname.endsWith('/answer'));
outer.HTMLElement.prototype.scrollIntoView=function(){};
outer.HTMLDialogElement.prototype.showModal=function(){this.open=true;};
outer.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new outer.Event('close'));};
outer.fetch=async(raw,options={})=>{const url=new URL(raw,outer.location),body=options.body&&JSON.parse(options.body);requestLog.push({url,body,options});let value;
 if(url.pathname.endsWith('/overview'))value={independent:true,books:[{id:'redbook',name:'红宝书',cardCount:1,previewPath:'/redbook/index.html',settings,counts:current.counts,decks:[{id:'u',name:'Unit 01',unit:'必考词',lesson:'Unit 01',count:1}]}]};
 else if(url.pathname.endsWith('/delivery'))value=descriptor;
 else if(url.pathname.endsWith('/preferences')){preferences=body.preferences;value={preferences};}
 else if(url.pathname.endsWith('/answer'))value={...current,card:null};
 else value=current;
 return {ok:true,status:200,json:async()=>value};};
for(const name of ['scope.js','card-tools.js'])outer.eval(read(path.join(__dirname,name)));
outer.eval(read(path.join(root,'anki_pipeline/web_runtime/study/preferences.js')));
outer.eval(read(path.join(root,'anki_pipeline/web_runtime/study/study.js')));
function inertScripts(html){return html.replace(/<script>/g,'<script type="text/plain">');}
// No child frames exist in these sources; the ResizeObserver shim supplies the
// absent jsdom constructor, not visibility/readiness or geometry acceptance.
function globals(w){w.ResizeObserver=class {observe(){} unobserve(){} disconnect(){}};w.TextEncoder=TextEncoder;w.TextDecoder=TextDecoder;w.Response=Response;Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle,configurable:true});w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=function(){};}
function wire(w){
 globals(w);
 Object.defineProperty(w.HTMLIFrameElement.prototype,'srcdoc',{configurable:true,get(){return this.getAttribute('srcdoc')||'';},set(html){
  this.setAttribute('srcdoc',html);events.push({type:'srcdoc',path:html===input.frame_page?'frame':'realm'});const child=this.contentWindow;wire(child);
  const d=child.document;d.open();d.write(inertScripts(html));d.close();
  if(html===input.frame_page){child.eval(input.frame_runtime);events.push({type:'actual-frame-installed'});}
  setTimeout(()=>{events.push({type:'srcdoc-load',path:String(d.readyState)+':'+d.documentElement.dataset.studyRealm+':'+typeof this.onload});this.dispatchEvent(new w.Event('load'));},0);
 }});
}
(async()=>{
 await until(()=>el('card-frame')?.src.includes('study-embed=1'),'descriptor did not produce shared entry');
 appFrame=el('card-frame');host=appFrame.contentWindow;wire(host);
 host.fetch=async(raw,options={})=>{const path=new URL(raw,host.location).pathname.slice(entry.lastIndexOf('/')+1);events.push({type:'transport',path});
  if(path==='navigation.json')return new Response(JSON.stringify(input.navigation));
  if(path.startsWith('cards/'))return new Promise((resolve,reject)=>{const gate={path,signal:options.signal,release:()=>resolve(new Response(input.files[path]))};fullGates.push(gate);options.signal?.addEventListener('abort',()=>reject(new host.DOMException('cancelled','AbortError')),{once:true});});
  assert.ok(path in input.files,'unexpected actual HOST transport '+path);return new Response(input.files[path]);};
 const hostDoc=host.document;hostDoc.open();hostDoc.write(inertScripts(input.page));hostDoc.close();host.eval(input.host_runtime);
 const actualEmbed=host.StudyBookEmbed;assert.equal(typeof actualEmbed.configure,'function');
 // Observe callbacks, but configure/select/show/refresh/snapshot are the actual
 // public implementation and are returned untouched to the actual consumer.
 host.StudyBookEmbed={configure(callbacks){
  cap=actualEmbed.configure({
   beforePrepare(doc,state){events.push({type:'before',...state,document:doc});callbacks.beforePrepare(doc,state);
    assert.ok(doc.getElementById('anki-study-responsive'));assert.ok(doc.getElementById('study-preferences-style'));
    if(state.answer){backDoc=doc;if(holdBack)fontStates.set(doc,'loading');}else{frontDoc=doc;if(holdFront)fontStates.set(doc,'loading');}
    if(!Object.getOwnPropertyDescriptor(doc,'fonts'))Object.defineProperty(doc,'fonts',{value:{get status(){return fontStates.get(doc)||'loaded';}}});
   },
   onBusy(state){events.push({type:'busy',...state});callbacks.onBusy(state);},
   onCommit(state){events.push({type:'commit',...state});assert.equal(state.document,cap.snapshot().document);assert.equal(state.ready,true);assert.equal(state.busy,false);callbacks.onCommit(state);},
   onError(error,state){events.push({type:'error',message:error.message,...state});callbacks.onError(error,state);},
   onKey(event,state){events.push({type:'key',key:event.key});return callbacks.onKey(event,state);}
  });return cap;
 }};
 appFrame.dispatchEvent(new outer.Event('load'));
 await until(()=>frontDoc||!el('card-failure').hidden,'actual front did not reach beforePrepare');
 assert.equal(cap.snapshot().ready,false);assert.equal(el('show-answer').disabled,true);assert.equal(events.filter(e=>e.type==='commit').length,0);
 holdFront=false;fontStates.set(frontDoc,'loaded');
 await until(()=>cap?.snapshot().ready||!el('card-failure').hidden,'actual front did not settle');
 assert.equal(el('card-failure').hidden,true,JSON.stringify(events.map(e=>({type:e.type,message:e.message}))));
 assert.equal(cap.snapshot().id,'A');assert.equal(cap.snapshot().answer,false);assert.equal(el('show-answer').disabled,false);
 assert.ok(events.some(e=>e.type==='actual-frame-installed'));assert.ok(cap.snapshot().document.defaultView.frameElement.isConnected);
 const front=cap.snapshot();assert.equal(front.document.querySelector('body').textContent.includes('完整正面 A'),true);
 await until(()=>fullGates.length===1,'full wrapper was not pending');
 front.document.body.getBoundingClientRect=()=>({height:20});assert.equal(cap.snapshot().ready,true,'legal viewport changes retain the complete commit fact');
 el('show-answer').click();await tick();assert.equal(el('rating-3').disabled,true);assert.equal(cap.snapshot().ready,false);assert.equal(answers().length,0);
 fullGates[0].release();await until(()=>backDoc||!el('card-failure').hidden,'actual back did not reach beforePrepare');
 assert.equal(el('card-failure').hidden,true);assert.equal(el('rating-3').disabled,true);assert.equal(cap.snapshot().ready,false,'font loading cannot become ready after attachComplete');
 holdBack=false;fontStates.set(backDoc,'loaded');await until(()=>cap.snapshot().ready&&cap.snapshot().answer,'actual back gate did not commit');
 observedBack=true;assert.equal(el('rating-3').disabled,false);const back=cap.snapshot();assert.notEqual(back.document,front.document);
 // Same authored document, new preferences revision, original fonts and stable
 // geometry gate. The consumer must not reuse the old committed token.
 fontStates.set(back.document,'loading');el('pref-wordSize').value='70';if(scoringMode.includes('good'))el('pref-spaceAction').value='good';el('preferences-form').dispatchEvent(new outer.Event('submit',{bubbles:true,cancelable:true}));
 await until(()=>events.filter(e=>e.type==='before'&&e.document===back.document).length>=2,'actual refresh skipped beforePrepare');
 assert.equal(el('rating-3').disabled,true);assert.equal(cap.snapshot().ready,false);assert.match(back.document.getElementById('study-preferences-style').textContent,/70px/);
 fontStates.set(back.document,'loaded');await until(()=>cap.snapshot().ready&&!el('rating-3').disabled,'refreshed original gate did not commit');
 assert.equal(cap.snapshot().document,back.document);assert.notEqual(cap.snapshot().viewToken,back.viewToken);
 // A real source disclosure, resize and overview re-display keep the fact
 // of the same completed document. Snapshot reads cannot rescan its geometry.
 const detail=back.document.getElementById('audit-disclosure');assert.ok(detail);assert.equal(detail.open,false);detail.open=true;
 let visibleHeight=40,geometryReads=0;back.document.body.getBoundingClientRect=()=>{geometryReads++;return{height:visibleHeight};};
 assert.equal(cap.snapshot().ready,true);assert.equal(cap.snapshot().ready,true);assert.equal(geometryReads,0);
 el('show-overview').click();assert.equal(el('card-stage').hidden,true);visibleHeight=0;
 el('start-session').click();visibleHeight=40;assert.equal(el('card-stage').hidden,false);assert.equal(cap.snapshot().ready,true);
 el('pause-study').click();el('resume-study').click();assert.equal(el('ratings').hidden,false);assert.equal(el('rating-3').disabled,false);
 const commitsBefore=events.filter(e=>e.type==='commit').length,busyBefore=events.filter(e=>e.type==='busy').length;
 if(scoringMode==='button')el('rating-3').click();
 else {const keyDoc=cap.snapshot().document,key=scoringMode==='digit'?'3':scoringMode==='enter-good'?'Enter':' ',target=scoringMode==='digit'?detail.querySelector('summary'):keyDoc.body;
  const event=new keyDoc.defaultView.KeyboardEvent('keydown',{key,code:key===' '?'Space':key==='3'?'Digit3':'Enter',bubbles:true,cancelable:true});target.dispatchEvent(event);assert.equal(event.defaultPrevented,true);}
 await until(()=>answers().length===1,'legitimate disclosure could not directly score '+scoringMode);
 assert.equal(events.filter(e=>e.type==='commit').length,commitsBefore,'rating must not add another show/refresh commit');
 assert.equal(events.filter(e=>e.type==='busy').length,busyBefore,'rating must not trigger a preparation command');
 assert.equal(geometryReads,0,'public commit-fact reads must not read layout');
 assert.equal(answers()[0].body.cardId,'old-A');assert.equal(answers()[0].body.revision,7);assert.equal(answers()[0].body.book,'redbook');
 await until(()=>!el('card-frame'),'successful score did not dispose outer frame');assert.equal(cap.snapshot().ready,false);assert.equal(await cap.show(true),null);
 assert.ok(observedBack);assert.equal(events.filter(e=>e.type==='error').length,0);assert.deepEqual(scriptErrors,[]);
 clearTimeout(watchdog);dom.window.close();console.log(JSON.stringify({contracts:6,host_sha256:input.host_sha256,frame_sha256:input.frame_sha256,
  actual_host:true,actual_complete_frame:true,capability_stub:false,commit_fact_readiness:true,direct_scoring_mode:scoringMode,extra_scoring_preparation:false,snapshot_geometry_reads:geometryReads,callback_counts:Object.fromEntries(['before','busy','commit','key'].map(k=>[k,events.filter(e=>e.type===k).length])),
  results:['actual descriptor entry and public selection','before preferences precede actual original font gate','complete back commits after full attachment and fonts','preferences re-gate same authored Document/new token','legitimate details/resize/overview retain commit fact and directly score '+scoringMode,'old scoring identity and actual capability disposal']}));
})().catch(error=>{console.error(error);console.error(JSON.stringify({scriptErrors}));console.error(JSON.stringify(events.map(e=>({type:e.type,path:e.path,message:e.message,id:e.id,generation:e.generation,viewToken:e.viewToken,answer:e.answer,ready:e.ready,busy:e.busy}))));dom.window.close();process.exit(1);});
