"""Embedded study consumes the original host and the original readiness gate.

The host uses small, genuinely hashed front/full fixtures. Only its FRAME
dependency is replaced. The FRAME contracts execute exact production functions
against connected authored Documents and the original asynchronous gate.
"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize
from tests.test_study_catalog_web_front import front_host_fixture


HOST_CONTRACT = r"""'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom'),{webcrypto}=require('node:crypto');
const watchdog=setTimeout(()=>{console.error('Embedded contract did not settle');process.exit(2)},8000);const input=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function until(test,message){for(let i=0;i<180;i++){if(test())return;await tick()}assert.fail(message)}
function setup({delayedNavigation=false,delayedIndex=false,files=input.files}={}){
 const calls=[],gates=[],navigationGates=[],indexGates=[],mounts=[],attachments=[],before=[],commits=[],errors=[],keys=[],owners=[],vc=new VirtualConsole();
 const dom=new JSDOM(input.page,{url:'http://example.test/book/index.html?study-embed=1#card=A',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc}),w=dom.window;
 w.TextEncoder=TextEncoder;w.Response=Response;Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle});
 let owner=null,raw={id:null,generation:0,viewToken:null,answer:false,busy:false,ready:false,document:null},packet=null,fullResolve=null,full=null,backResolve=null,disposals=0,revision=0;
 const authored=new Map();
 function busy(){raw={...raw,busy:true,ready:false};owner.onBusy(raw)}
 function commit(value,answer){if(!owner.valid())return false;let doc=authored.get(value.id+':'+answer);if(!doc){doc=w.document.implementation.createHTMLDocument('authored');doc.body.textContent=value.sides[answer?1:0];authored.set(value.id+':'+answer,doc)}const state={id:value.id,generation:value.token,viewToken:value.token+':'+(++revision),answer,busy:true,ready:false,document:doc};owner.beforePrepare(doc,state);if(!owner.valid())return false;raw={...state,busy:false,ready:true};owner.onCommit(raw);return true}
 const api={configureConsumer(value){owner=value;owners.push(value)},snapshot(){return raw},cancel(){fullResolve?.(false);backResolve?.(false)},dispose(){disposals++;fullResolve?.(false);backResolve?.(false);raw={...raw,busy:false,ready:false,document:null}},async mountFront(value){packet=value;full=null;fullResolve=null;mounts.push(value);return commit(value,false)},async mount(value){packet=value;full=value;mounts.push(value);return commit(value,false)},async attachComplete(value){attachments.push(value);full=value;fullResolve?.(true);return true},async show(answer){busy();const expected=packet;if(answer&&!full){if(!await new Promise(resolve=>fullResolve=resolve))return false}if(expected!==packet||!owner.valid())return false;if(answer){if(!await new Promise(resolve=>backResolve=resolve))return false}return commit(full||packet,answer)},async refresh(){busy();return commit(full||packet,raw.answer)}};
 const frame=w.document.getElementById('frame');function installApi(){frame.contentWindow.StudySharedFrame=api}installApi();w.__fixtureApi=api;w.__installApi=installApi;
 w.fetch=async(url,options={})=>{const path=new URL(url,w.location.href).pathname.replace('/book/','');calls.push({path,signal:options.signal});
  if(path==='navigation.json'){
   if(delayedNavigation)return new Promise((resolve,reject)=>{const gate={signal:options.signal,resolve:()=>resolve(new Response(JSON.stringify(input.navigation)))};navigationGates.push(gate);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('disposed','AbortError')),{once:true})});
   return new Response(JSON.stringify(input.navigation));
  }
  if(path==='prepared-index.json'&&delayedIndex)return new Promise((resolve,reject)=>{const gate={signal:options.signal,resolve:()=>resolve(new Response(files[path]))};indexGates.push(gate);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('disposed','AbortError')),{once:true})});
  if(path.startsWith('cards/'))return new Promise((resolve,reject)=>{const gate={path,signal:options.signal,resolve:()=>resolve(new Response(files[path]))};gates.push(gate);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('disposed','AbortError')),{once:true})});
  if(!(path in files))throw Error('Unexpected fixture request '+path);return new Response(files[path]);
 };
 const runtime=input.runtime.replace('function ensureSharedFrame(){','function ensureSharedFrame(){window.__installApi();return Promise.resolve(window.__fixtureApi)}function originalFixtureFrameDependency(){');
 assert.notEqual(runtime,input.runtime);w.eval(runtime);
 assert.ok(w.StudyBookEmbed,'the common host must expose the embedded capability');
 function configure(extra={}){let cap;cap=w.StudyBookEmbed.configure({beforePrepare(doc,state){assert.equal(state.document,doc);assert.equal(state.ready,false);assert.equal(state.busy,true);assert.equal(state.generation,cap.snapshot().generation);doc.documentElement.dataset.pref='applied';before.push(state);return extra.beforePrepare?.(doc,state)},onBusy(state){assert.deepEqual(state,cap.snapshot());extra.onBusy?.(state)},onCommit(state){assert.deepEqual(state,cap.snapshot());assert.equal(state.ready,true);assert.equal(state.busy,false);assert.equal(state.document.documentElement.dataset.pref,'applied');assert.ok(state.viewToken);commits.push(state);extra.onCommit?.(state)},onError(error,state){errors.push({error,state});assert.equal(state.ready,false);extra.onError?.(error,state)},onKey(event,state){keys.push({event,state});return extra.onKey?.(event,state)??true}});return cap}
 return{dom,w,frame,calls,gates,navigationGates,indexGates,mounts,attachments,before,commits,errors,keys,owners,configure,api,releaseBack:()=>backResolve?.(true),disposals:()=>disposals,close(){dom.window.close()}};
}
(async()=>{
 {
  const f=setup({delayedNavigation:true});await tick();assert.equal(f.mounts.length,0);assert.equal(f.calls.filter(x=>x.path!=='navigation.json').length,0,'embed must not prepare before configure/select');
  const cap=f.configure();await tick();assert.equal(f.mounts.length,0);const selected=cap.select('B');assert.equal(cap.snapshot().ready,false);assert.equal(f.mounts.length,0);f.navigationGates[0].resolve();
  const front=await selected;assert.equal(front.id,'B');assert.equal(front.answer,false);assert.equal(front.ready,true);assert.equal(f.before.length,1);assert.equal(f.mounts.length,1);assert.equal(f.commits.length,1,'unlisted guide must select without automatic A mount');
  await until(()=>f.gates.length===1,'complete packet never requested');const shown=cap.show(true);await tick();assert.equal(cap.snapshot().ready,false);assert.equal(f.commits.length,1);f.gates[0].resolve();await until(()=>f.attachments.length===1,'complete packet never attached');await tick();assert.equal(f.commits.length,1,'attachComplete is not back readiness');assert.equal(cap.snapshot().ready,false);f.releaseBack();const back=await shown;assert.equal(back.answer,true);assert.equal(back.ready,true);assert.equal(f.commits.length,2);
  const refreshed=await cap.refresh();assert.equal(refreshed.answer,true);assert.equal(refreshed.document,back.document);assert.notEqual(refreshed.viewToken,back.viewToken);assert.equal(f.mounts.length,1,'preference refresh must reuse the original prepared session');assert.equal(f.before.length,3);
  const event=new f.w.KeyboardEvent('keydown',{key:' ',code:'Space',bubbles:true,cancelable:true});f.w.document.body.dispatchEvent(event);assert.equal(f.keys.length,1);assert.equal(event.defaultPrevented,true);assert.equal(f.commits.length,3,'Space must be delegated, never flipped twice');
  for(const options of [{key:'1',ctrlKey:true},{key:'r',repeat:true}])f.w.document.body.dispatchEvent(new f.w.KeyboardEvent('keydown',{...options,bubbles:true}));assert.equal(f.keys.length,1,'repeated/modified key reached consumer');
  const count=f.commits.length,stale=f.owners[0];cap.dispose();assert.equal(f.frame.isConnected,false);assert.equal(cap.snapshot().ready,false);assert.ok(f.disposals()>0);stale.onCommit(back);assert.equal(f.commits.length,count);assert.equal(await cap.select('A'),null);results.push('explicit selection, unlisted guide, committed faces, refresh, keyboard, disposal');f.close();
 }
 {
  const f=setup();const cap=f.configure();await cap.select('A');await until(()=>f.gates.length===1,'A full delivery not pending');const oldOwner=f.owners[0],old=f.commits[0];const next=cap.select('B');await next;await until(()=>f.gates.length===2,'B full delivery not pending');assert.equal(f.gates[0].signal.aborted,true);oldOwner.beforePrepare(old.document,{...old,ready:false,busy:true});oldOwner.onCommit(old);assert.equal(f.before.length,2);assert.equal(f.commits.length,2,'stale same-capability owner committed');cap.dispose();assert.equal(f.gates[1].signal.aborted,true);assert.equal(f.frame.hasAttribute('srcdoc'),false);results.push('navigation ownership and all pending wrapper requests aborted');f.close();
 }
 {
  const f=setup({delayedNavigation:true});const first=f.configure();const pending=first.select('A');first.dispose();assert.equal(f.navigationGates[0].signal.aborted,true);const cap=f.configure();const selection=cap.select('B');await until(()=>f.navigationGates.length===2,'reconfigure did not restart cancelled navigation');f.navigationGates[1].resolve();assert.equal((await selection).id,'B');assert.equal(await pending,null);assert.equal(f.errors.length,0);cap.dispose();results.push('navigation lifetime cancels and a new capability owns the restart');f.close();
 }
 {
  const f=setup({delayedIndex:true}),first=f.configure(),pending=first.select('A');await until(()=>f.indexGates.length===1,'prepared index not requested');first.dispose();const next=f.configure(),selection=next.select('B');assert.equal(f.indexGates[0].signal.aborted,true);await until(()=>f.indexGates.length===2,'new owner reused cancelled prepared index promise');f.indexGates[1].resolve();assert.equal((await selection).id,'B');assert.equal(await pending,null);assert.equal(f.errors.length,0);next.dispose();results.push('aborted index promise cannot invalidate new owner index');f.close();
 }
 {
  const files={...input.files,'front-A.json':input.files['front-A.json']+' '},f=setup({files}),cap=f.configure();assert.equal(await cap.select('A'),null);assert.equal(f.mounts.length,0);assert.equal(f.errors.length,1);assert.equal(f.frame.dataset.mountMode,'embedded-failed');assert.equal(f.frame.hasAttribute('src'),false,'embed must never fall back to unverified wrapper');assert.equal(cap.snapshot().ready,false);results.push('root artifact failure remains fail-closed');f.close();
 }
 {
  const f=setup(),cap=f.configure({beforePrepare(){return Promise.resolve()}});assert.equal(await cap.select('A'),null);assert.equal(f.errors.length,1);assert.match(f.errors[0].error.message,/synchronous/);assert.equal(f.commits.length,0);results.push('asynchronous preference hook is rejected before commit');f.close();
 }
 clearTimeout(watchdog);console.log(JSON.stringify({contracts:results.length,results}));
})().catch(error=>{console.error(error);process.exit(1)});
"""


FRAME_CONTRACT = r"""'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM,VirtualConsole}=require('jsdom');
const watchdog=setTimeout(()=>{console.error('Embedded contract did not settle');process.exit(2)},8000);const input=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function until(test,message){for(let i=0;i<180;i++){if(test())return;await tick()}assert.fail(message)}
function setup(mode='stable'){
 const vc=new VirtualConsole(),dom=new JSDOM('<!doctype html><body><button id="study-flip">显示答案</button><iframe id="authored"></iframe></body>',{url:'http://example.test/book/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc}),w=dom.window;w.input=input;w.mode=mode;
 w.eval(`(function(){
 const flip=document.getElementById('study-flip'),origin=location.origin,messages=[],parent={postMessage(value){messages.push(value)}},records=[],scriptCache=new Map(),frameAbort=new AbortController();
 let current={id:'A',token:1,metricsAsset:false,frontOnly:false},accepted=1,reservedToken=1,sequence=1,answer=false,working=false,record=null,preparedTasks=[],frontSession=null;
 let consumer=null,consumerRevision=0,consumerShowSequence=0,committedView=null,frameDisposed=false,side=document.getElementById('authored'),snapshotCalls=0,layoutRevision=0,before=0,commits=[],keys=0,cleanups=0,authorRuns=0,validOwner=true;
 const doc=side.contentDocument,win=side.contentWindow;doc.body.innerHTML='<main id="content">unchanged source</main><input id="edit">';win.__ankiCigenFrames={known:new Map(),refresh(){}};
 const entry={packet:current,viewToken:1,doc,win,node:side},realms=[entry];
 let fonts='loaded';Object.defineProperty(doc,'fonts',{value:{get status(){return fonts}}});
 const view={packet:current,token:1,entry,doc,index:0,row:{},geometry:JSON.stringify({pref:0,layoutRevision:0})};
 const clock=()=>performance.timeOrigin+performance.now();function snapshot(){snapshotCalls++;return {pref:Number(doc.documentElement.dataset.pref||0),layoutRevision}}function report(){}function observe(){}function stage(){}function prepareBack(){}async function prepareView(packet,index){authorRuns++;view.index=index;if(!applyConsumerDocument(view))return null;if(!await waitPrepared(entry,()=>ownsView(view)))return null;view.geometry=JSON.stringify(snapshot(doc));return view}
 function clearOld(value){cleanups++;value.win.__ankiExamCountdownCleanup?.();value.doc.body.replaceChildren();value.packet=null;value.viewToken=null}
 ${input.functions}
 window.StudySharedFrame={configureConsumer,snapshot:consumerSnapshot,dispose:disposeConsumer,show:async value=>show(clock(),value?1:0),refresh:async()=>{consumerRevision++;committedView=null;return show(clock(),answer?1:0)}};
 const api=window.StudySharedFrame;
 function configure(extra={}){const owner={generation:1,valid:()=>validOwner,beforePrepare(value,state){before++;if(extra.beforePrepare)return extra.beforePrepare(value,state);value.documentElement.dataset.pref=String(before)},onCommit(state){commits.push(state)},onKey(){keys++;return true}};configureConsumer(owner);return owner}
 window.probe={api,doc,win,view,entry,configure,apply:()=>applyConsumerDocument(view),gate:()=>waitPrepared(entry,()=>ownsView(view)),
  state:()=>({before,commits,keys,cleanups,authorRuns,working,answer,snapshotCalls,aborted:frameAbort.signal.aborted,disposed:frameDisposed,sourceErrors:messages.filter(value=>value.type==='study-source-error').length}),
  geometry:value=>layoutRevision=value,fail:()=>fail(Error('terminal source failure'),current,accepted),bumpRevision:()=>consumerRevision++,
  fonts:value=>fonts=value,invalidate(){validOwner=false},replace(){current={id:'A',token:2};accepted=2},native(value){let n=doc.querySelector('script.anki-final-reviewed-data');if(!n){n=doc.createElement('script');n.type='application/json';n.className='anki-final-reviewed-data';doc.body.append(n)}n.dataset.nativeState=value},key(event){key(event)},projectCloseCount:()=>projectionTaskSessions.size};
 })();`);
 return{dom,w,p:w.probe,close:()=>dom.window.close()};
}
(async()=>{
 {
  const h=setup(),p=h.p;p.configure();assert.equal(p.api.snapshot().ready,false);assert.equal(await p.api.show(false),true);assert.equal(p.state().commits.length,1);let before=p.api.snapshot();assert.equal(before.document,p.doc);assert.equal(before.ready,true);assert.equal(before.busy,false);assert.equal(before.answer,false);
  p.fonts('loading');const refreshing=p.api.refresh();await until(()=>p.state().before===2,'refresh did not synchronously apply new preferences');assert.equal(p.api.snapshot().ready,false);assert.equal(p.state().commits.length,1,'loading fonts passed refresh gate');p.fonts('loaded');assert.equal(await refreshing,true);const after=p.api.snapshot();assert.equal(after.ready,true);assert.equal(after.document,before.document);assert.notEqual(after.viewToken,before.viewToken);assert.equal(p.state().authorRuns,1);assert.equal(p.state().commits.length,2);results.push('preferences precede original fonts and three-frame geometry gate; refresh reuses author document');
  const beforeKeys=p.state().keys;for(const [target,options]of [[p.doc.body,{key:' ',code:'Space'}],[p.doc.body,{key:'1'}],[p.doc.body,{key:'r'}],[p.doc.body,{key:'z'}],[p.doc.body,{key:'Enter'}]]){const e=new h.w.KeyboardEvent('keydown',{...options,bubbles:true,cancelable:true});Object.defineProperty(e,'target',{value:target});p.key(e);assert.equal(e.defaultPrevented,true)}assert.equal(p.state().keys,beforeKeys+5);
  for(const [target,options]of [[p.doc.body,{key:'1',ctrlKey:true}],[p.doc.body,{key:'1',repeat:true}]]){const e=new h.w.KeyboardEvent('keydown',options);Object.defineProperty(e,'target',{value:target});p.key(e)}assert.equal(p.state().keys,beforeKeys+5);results.push('one consumer key delegation; original learning keyboard owns interactive policy');
  p.win.__ankiExamCountdownCleanup=()=>{p.doc.documentElement.dataset.cleaned='true'};p.api.dispose();assert.equal(p.state().aborted,true);assert.equal(p.state().cleanups,1);assert.equal(p.entry.node.isConnected,false);assert.equal(p.api.snapshot().ready,false);assert.equal(p.doc.documentElement.dataset.cleaned,'true');assert.equal(p.api.snapshot().document,null);results.push('dispose aborts resources, author timers and actual realm DOM');h.close();
 }
 {
  const h=setup(),p=h.p;p.configure({beforePrepare(){p.invalidate()}});assert.equal(p.apply(),false);assert.equal(p.api.snapshot().ready,false);assert.equal(p.state().commits.length,0);results.push('preference callback losing ownership cannot commit');h.close();
 }
 {
  const h=setup(),p=h.p;p.configure({beforePrepare(){return Promise.resolve()}});assert.throws(()=>p.apply(),/synchronous/);assert.equal(p.state().commits.length,0);h.close();results.push('async beforePrepare rejected');
 }
 {
  const h=setup(),p=h.p;p.configure();assert.equal(p.apply(),true);p.view.geometry=JSON.stringify({pref:1});p.native('failed');await assert.rejects(p.api.refresh(),/native validation failed/);assert.equal(p.state().commits.length,0);assert.equal(p.api.snapshot().ready,false);results.push('native failure does not publish embedded readiness');h.close();
 }
 {
  const h=setup(),p=h.p;p.configure();p.apply();p.view.geometry=JSON.stringify({pref:1});p.fonts('loading');const pending=p.api.show(true);await tick();p.replace();assert.equal(await pending,false);assert.equal(p.state().commits.length,0);assert.equal(p.api.snapshot().ready,false);results.push('same id ABA generation cancels pending gate');h.close();
 }
 {
  const h=setup(),p=h.p;p.configure();p.fonts('loading');const initial=p.api.show(false);await until(()=>p.state().before===1,'initial candidate not prepared');assert.equal(p.state().commits.length,0);assert.equal(p.api.snapshot().ready,false,'initial loading fonts exposed ready');p.fonts('loaded');assert.equal(await initial,true);const committed=p.api.snapshot(),calls=p.state().snapshotCalls;assert.equal(p.api.snapshot({...p.view}).ready,false,'a copied view is not the committed view');
  const details=p.doc.createElement('details');details.open=true;details.innerHTML='<summary>audit</summary><p>expanded history</p>';p.doc.body.append(details);p.geometry(17);
  for(let i=0;i<8;i++){const state=p.api.snapshot();assert.equal(state.ready,true,'authored layout change revoked an already complete commit');assert.equal(state.document,committed.document);assert.equal(state.viewToken,committed.viewToken)}assert.equal(p.state().snapshotCalls,calls,'snapshot performed an unsolicited geometry scan');
  p.fonts('loading');const shown=p.api.show(false);await tick();assert.equal(p.api.snapshot().ready,false);assert.equal(p.state().commits.length,1,'show skipped the original font/geometry gate');p.fonts('loaded');assert.equal(await shown,true);assert.equal(p.state().commits.length,2);assert.ok(p.state().snapshotCalls>calls);assert.equal(p.state().authorRuns,1,'show reran author source instead of rechecking its cached document');results.push('committed readiness survives details/resize without snapshot scans; every show retains original gate');h.close();
 }
 {
  for(const change of ['owner','token','document','revision','generation','terminal']){
   const h=setup(),p=h.p;p.configure();assert.equal(await p.api.show(false),true);assert.equal(p.api.snapshot().ready,true);
   if(change==='owner')p.invalidate();if(change==='token')p.entry.viewToken++;if(change==='document')p.entry.doc=p.doc.implementation.createHTMLDocument('replacement');if(change==='revision')p.bumpRevision();if(change==='generation')p.replace();if(change==='terminal')p.fail();
   assert.equal(p.api.snapshot().ready,false,change+' retained committed readiness');if(change==='terminal'){assert.equal(p.state().sourceErrors,1);assert.equal(p.api.snapshot().document,null,'source-error must invalidate before its message is handled')};h.close();
  }
  results.push('consumer, document, token, revision, generation and terminal error invalidate committed state');
 }
 clearTimeout(watchdog);console.log(JSON.stringify({contracts:results.length,results}));
})().catch(error=>{console.error(error);process.exit(1)});
"""


def _section(start, end):
    source = materialize.PREPARED_FRAME_RUNTIME
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


KEYBOARD_CONTRACT = r"""'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),{JSDOM}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
for(const route of ['host','frame']){
 const dom=new JSDOM('<!doctype html><body><button id="audio">play</button><a id="lookup" href="#">lookup</a><details><summary id="history">history</summary></details><input id="input"><audio id="media"></audio></body>',{url:'http://example.test/book/',runScripts:'outside-only'}),w=dom.window;w.input=input;w.route=route;
 w.eval(`(function(){
 let scores=0,plays=0,undos=0,flips=0,delegations=0;const state={restore:null,frame:{ready:true,document},busy:false,pendingAnswer:null,session:{card:{id:'A'},canUndo:true}},paused=false,overviewMode=false,elements={'study-panel':{open:false},'card-tools':{open:false}},hasAnswer=()=>true,submitAnswer=()=>scores++,undoAnswer=()=>undos++,flipCard=()=>flips++,toggleOverview=()=>{},tick=()=>{},cardTools={open(){}},StudyPreferences={get:()=>({spaceAction:'good',autoplay:'uk'}),play:()=>plays++};
 ${input.keyboard}
 const dispatch=(event)=>{delegations++;keyboard(event);return event.defaultPrevented},consumer={onKey:dispatch},embedOwner={options:{onKey:dispatch}},embedActive=()=>true,consumerCurrent=()=>true,embedSnapshot=()=>({}),consumerSnapshot=()=>({}),interactive='input,select,textarea,button,summary,a,[contenteditable]',flip={click(){flips++}},parent={postMessage(){flips++}},origin=location.origin;
 ${input.host}
 ${input.frame}
 document.addEventListener('keydown',route==='host'?embedKey:key);
 window.probe={state:()=>({scores,plays,undos,flips,delegations})};
 })();`);
 const controls=['audio','lookup','history'];
 function dispatch(id,key){const event=new w.KeyboardEvent('keydown',{key,code:key===' '?'Space':'',bubbles:true,cancelable:true});w.document.getElementById(id).dispatchEvent(event);return event}
 for(const id of controls){const previous=w.probe.state();for(const key of ['1','2','3','4'])assert.equal(dispatch(id,key).defaultPrevented,true);assert.equal(w.probe.state().scores,previous.scores+4,route+' dropped focused '+id+' ratings');assert.equal(dispatch(id,'r').defaultPrevented,true);assert.equal(w.probe.state().plays,previous.plays+1);assert.equal(dispatch(id,'z').defaultPrevented,true);assert.equal(w.probe.state().undos,previous.undos+1);
  const before=w.probe.state();for(const key of [' ','Enter'])assert.equal(dispatch(id,key).defaultPrevented,false,route+' stole native activation on '+id);const after=w.probe.state();assert.equal(after.flips,before.flips);assert.equal(after.scores,before.scores);assert.equal(after.delegations,before.delegations+2,'delegate exactly once before original keyboard policy');
 }
 for(const id of ['input','media']){const before=w.probe.state();for(const key of ['3','r','z',' ','Enter'])assert.equal(dispatch(id,key).defaultPrevented,false);const after=w.probe.state();assert.equal(after.scores,before.scores);assert.equal(after.plays,before.plays);assert.equal(after.undos,before.undos);assert.equal(after.flips,before.flips)}
 results.push({route,...w.probe.state()});dom.window.close();
}
console.log(JSON.stringify({routes:results.length,results}));
"""


@unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
class StudyBookEmbedTests(unittest.TestCase):
    def _run(self, code, payload):
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps(payload), text=True,
                                capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_host_capability_uses_hashed_original_delivery_and_owns_lifetime(self):
        payload = front_host_fixture()
        payload['navigation']['cards'][1][7] = False  # A guide outside the word list.
        report = self._run(HOST_CONTRACT, payload)
        self.assertEqual(report['contracts'], 6)

    def test_frame_consumer_preserves_original_gate_ownership_and_keyboard(self):
        functions = [materialize.PROJECTION_TASK_RUNTIME,
                     _section('function state(){', '\nfunction execute('),
                     _section('function gateMemberCache(', '\nasync function prepareView'),
                     _section('function ownsView(', '\nfunction getView('),
                     _section('function getView(', '\nfunction prepareBack('),
                     _section('async function show(', '\n\nfunction canonicalJSON'),
                     _section('function cancel(token){', '\n\nfunction fail('),
                     _section('function fail(error,packet,token){', '\nflip.onclick=')]
        report = self._run(FRAME_CONTRACT, {'functions': '\n'.join(functions)})
        self.assertEqual(report['contracts'], 9)

    def test_embedded_keyboard_preserves_original_focused_controls_policy(self):
        original = (Path(__file__).parent / 'fixtures/study-shared-client/original-study.js').read_text()
        begin = original.index('  function keyboard(event) {')
        keyboard = original[begin:original.index("  elements['book-select']", begin)]
        begin = web.HOST_RUNTIME.index('function embedKey(')
        host = web.HOST_RUNTIME[begin:web.HOST_RUNTIME.index('\nfunction embedFailure(', begin)]
        payload = {'keyboard': keyboard, 'host': host,
                   'frame': _section('function consumerKey(', '\nfunction applyConsumerDocument(')
                            + _section('function key(', '\nfunction execute(')}
        report = self._run(KEYBOARD_CONTRACT, payload)
        self.assertEqual(report['routes'], 2)


if __name__ == '__main__':
    unittest.main()
