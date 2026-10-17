"""Terminal failure regressions using exact shared-frame functions and async DOM rAF."""
import json
import shutil
import subprocess
import unittest

from anki_pipeline.study_catalog_web_materialize import PREPARED_FRAME_RUNTIME, PROJECTION_TASK_RUNTIME


def _section(start: str, end: str) -> str:
    begin = PREPARED_FRAME_RUNTIME.index(start)
    return PREPARED_FRAME_RUNTIME[begin:PREPARED_FRAME_RUNTIME.index(end, begin)]


CONTRACT = r"""'use strict';
const {JSDOM,VirtualConsole}=require('jsdom'),fs=require('node:fs'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8')),results=[];
function harness(mode='success'){
 const virtualConsole=new VirtualConsole(),jsdomErrors=[];virtualConsole.on('jsdomError',error=>jsdomErrors.push(error.message));
 const dom=new JSDOM('<!doctype html><body><button id="study-flip">显示答案</button></body>',{url:'http://localhost/isolated/',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole});
 const w=dom.window;let observerDisposals=0;const NativeObserver=w.MutationObserver;w.MutationObserver=class extends NativeObserver{disconnect(){observerDisposals++;super.disconnect()}};w.input=input;w.mode=mode;
 w.eval(`(function(){
 const doc=document,flip=document.getElementById('study-flip'),messages=[],events=[],origin=location.origin;let sourceErrorResolve;const nextSourceError=new Promise(resolve=>sourceErrorResolve=resolve),parent={postMessage:value=>{messages.push(value);if(value.type==='study-source-error')sourceErrorResolve(value)}};
 let accepted=1,reservedToken=1,sequence=1,frontSession=null,preparedTasks=[],record=null,working=false,answer=false,snapshotCalls=0,refreshCalls=0,fontReads=0,getViewCalls=0,clickCallbacks=0;
 let current={id:'A',token:1,metricsAsset:false,frontOnly:false},side={name:'complete-front'};
 const initial=current,visibleSide=side,child=doc.createElement('iframe');child.className='etymology-source-frame';
 child.getBoundingClientRect=()=>({width:200});if(mode==='child-late')doc.body.append(child);
 const childState={ready:true,readySignature:'same',signature:'same',readyWidth:200},known=new Map([[child,childState]]);
 const node={isConnected:true,contentDocument:doc,style:{},dataset:{},removeAttribute(){}};
 const entry={packet:current,viewToken:1,doc,node,win:{__ankiCigenFrames:{known,refresh(){refreshCalls++;if(mode==='foreign-owner'&&refreshCalls===2){current={id:'B',token:2};accepted=2;entry.packet=current;entry.viewToken=2}if(mode==='child-late'&&refreshCalls===2){childState.ready=false;childState.signature='changed'}}}}};
 const view={packet:current,token:1,entry,doc,index:1,row:{},geometry:JSON.stringify({revision:0})};
 const realms=[entry];Object.defineProperty(doc,'fonts',{configurable:true,value:{get status(){fontReads++;return mode==='raf-error'||mode==='cancel-wait'||mode==='aba-wait'||mode==='font-late'&&fontReads>=2?'loading':'loaded'}}});
 function snapshot(){snapshotCalls++;return {revision:['geometry-late','foreign-owner'].includes(mode)&&snapshotCalls>=2?1:0}}
 async function getView(){getViewCalls++;return view}
 function clock(){return performance.timeOrigin+performance.now()}
 function stage(){events.push('stage')}function observe(){}function report(){}function clearOld(){}function prepareBack(){events.push('prepareBack')}
 ${input.functions}
 // This is the exact product button handler, with no test wrapper.
 ${input.onclick}
 const originalClick=flip.onclick;flip.onclick=function(...args){clickCallbacks++;return Reflect.apply(originalClick,this,args)};
 const baseQuery=doc.querySelectorAll.bind(doc),rafError=Error('Intentional selector failure inside original asynchronous rAF check');
 if(mode==='raf-error')doc.querySelectorAll=function(selector){if(selector==='iframe.etymology-source-frame')throw rafError;return baseQuery(selector)};
 window.probe={nextSourceError,show:()=>show(clock(),1),button:flip,initial,view,error:rafError,
  state:()=>({working,disabled:flip.disabled,answer,visibleUnchanged:side===visibleSide,snapshotCalls,refreshCalls,fontReads,getViewCalls,clickCallbacks,sourceErrors:messages.filter(x=>x.type==='study-source-error').length,accepted,currentId:current?.id??null}),
  cancel:token=>cancel(token),replace(){current={id:'A',token:2,metricsAsset:false};accepted=2;reservedToken=2;sequence++;working=true;flip.disabled=true},oldFail:()=>fail(Error('old failure'),initial,1)};
 })();`);
 return{dom,w,p:w.probe,jsdomErrors,observerDisposals:()=>observerDisposals,close:()=>dom.window.close()};
}
(async()=>{
 const success=harness();assert.equal(await success.p.show(),true);assert.equal(success.p.state().working,false);assert.equal(success.p.state().disabled,false);results.push({case:'stable control',result:true,state:success.p.state()});success.close();
 for(const mode of ['geometry-late','font-late','child-late']){
  const direct=harness(mode);await assert.rejects(direct.p.show(),/Prepared side lost readiness before commit/);assert.equal(direct.p.state().visibleUnchanged,true);direct.close();
  const h=harness(mode);h.p.button.click();const message=await Promise.race([h.p.nextSourceError,new Promise((_,reject)=>setTimeout(()=>reject(Error('Original flip catch did not receive terminal rejection')),1000))]);const state=h.p.state();assert.match(message.message,/Prepared side lost readiness before commit/);assert.equal(state.working,false);assert.equal(state.disabled,false);assert.equal(state.visibleUnchanged,true);assert.equal(state.answer,false);assert.equal(state.sourceErrors,1);assert.equal(state.clickCallbacks,1);assert.equal(state.getViewCalls,1);results.push({case:mode,terminal:'scoped source-error via original flip.catch',state});h.close();
 }
 {
  const h=harness('raf-error'),errors=[];h.w.addEventListener('error',event=>{errors.push(event.error);event.preventDefault()});const error=await Promise.race([h.p.show().then(()=>{throw Error('waitPrepared unexpectedly resolved')},error=>error),new Promise((_,reject)=>setTimeout(()=>reject(Error('Asynchronous rAF exception did not reject show')),1000))]);assert.equal(error,h.p.error);await new Promise(resolve=>h.w.requestAnimationFrame(()=>h.w.requestAnimationFrame(resolve)));assert.equal(errors.length,0,'rAF error escaped globally rather than rejecting');assert.equal(h.observerDisposals(),1,'gate observer must be disposed once, not twice');h.close();
  const clicked=harness('raf-error');clicked.p.button.click();const message=await Promise.race([clicked.p.nextSourceError,new Promise((_,reject)=>setTimeout(()=>reject(Error('Original click catch did not handle rAF failure')),1000))]);const state=clicked.p.state();assert.equal(message.message,'Intentional selector failure inside original asynchronous rAF check');assert.equal(state.working,false);assert.equal(state.disabled,false);assert.equal(state.sourceErrors,1);assert.equal(state.visibleUnchanged,true);assert.equal(clicked.observerDisposals(),1);results.push({case:'asynchronous rAF selector throw',terminal:'original Error rejected; scoped source-error via original flip.catch',globalErrors:errors.length,state});clicked.close();
 }
 {
  const h=harness('cancel-wait');const promise=h.p.show();await Promise.resolve();assert.equal(h.p.cancel(2),true);assert.equal(await promise,false);const state=h.p.state();assert.equal(state.currentId,null);assert.equal(state.working,false);assert.equal(state.disabled,true);h.p.oldFail();assert.deepEqual(h.p.state(),state);results.push({case:'cancellation control',state,oldFailureCannotUnblockNewRequest:true});h.close();
 }
 {
  const h=harness('aba-wait');const promise=h.p.show();await Promise.resolve();h.p.replace();assert.equal(await promise,false);const state=h.p.state();assert.equal(state.accepted,2);assert.equal(state.currentId,'A');assert.equal(state.working,true);assert.equal(state.disabled,true);h.p.oldFail();assert.deepEqual(h.p.state(),state);results.push({case:'ABA same card id / new packet control',state,oldFailureCannotMutateNewSession:true});h.close();
 }
 {
  const h=harness('foreign-owner');assert.equal(await h.p.show(),false);const state=h.p.state();assert.equal(state.currentId,'B');assert.equal(state.accepted,2);assert.equal(state.working,true);assert.equal(state.disabled,true);assert.equal(state.sourceErrors,0);assert.equal(state.visibleUnchanged,true);results.push({case:'final promote lost owner / new realm session',state,oldRequestDoesNotReportFailure:true});h.close();
 }
 console.log(JSON.stringify({schema:'study-show-terminal-failure-contract.v1',source:input.source,functionsAreExactSlices:true,characterizationChecks:results.length,terminalDefectsFixed:2,safariCauseConfirmed:false,productChanged:false,results},null,2));
})().catch(error=>{console.error(error);process.exitCode=1});
"""


class StudySharedFrameTerminalTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires existing JavaScript runtime')
    def test_terminal_failures_reject_without_disabling_forever_or_affecting_new_owner(self):
        functions = [
            PROJECTION_TASK_RUNTIME,
            _section('function state(){', '\nfunction '),
            _section('function gateMemberCache(', '\nasync function prepareView'),
            _section('function ownsView(', '\nfunction getView('),
            _section('async function show(', '\n\nfunction canonicalJSON'),
            _section('function cancel(token){', '\n\nfunction fail('),
            _section('function fail(error,packet,token){', '\nflip.onclick='),
        ]
        payload = {
            'functions': '\n'.join(functions),
            'onclick': _section('flip.onclick=', ";document.addEventListener('keydown',key)") + ';',
            'source': {'scope': 'exact production control functions'},
        }
        result = subprocess.run(
            [shutil.which('node'), '-e', CONTRACT], input=json.dumps(payload),
            text=True, capture_output=True, timeout=20,
        )
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['characterizationChecks'], 8)
        self.assertEqual(report['terminalDefectsFixed'], 2)
        self.assertFalse(report['safariCauseConfirmed'])


if __name__ == '__main__':
    unittest.main()
