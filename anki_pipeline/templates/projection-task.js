/* Private task source for already-audited native projection preparation.
 * One pending task per owner; scheduling never executes authored source. */
const projectionTaskSessions=new Set();
function createProjectionTaskScheduler(realmWindow,owns){
 let channel=null,pending=null,closed=false,next=0;
 const abort=()=>{const e=Error('Projection preparation superseded');e.name='AbortError';return e};
 function clear(item){try{if(item.watch!==null)clearTimeout(item.watch)}catch{}try{if(item.timer!==null)realmWindow.clearTimeout(item.timer)}catch{}item.watch=null;item.timer=null}
 function finish(item,error){if(pending!==item)return;clear(item);pending=null;if(error)item.reject(error);else item.resolve()}
 function dropChannel(){if(!channel)return;try{channel.port1.onmessage=null;channel.port1.onmessageerror=null;channel.port1.close();channel.port2.close()}catch{}channel=null}
 function fallback(item){if(pending!==item)return;if(item.watch!==null)clearTimeout(item.watch);item.watch=null;try{item.timer=realmWindow.setTimeout(()=>finish(item,closed||!owns()?abort():null),0)}catch(error){finish(item,error)}}
 function ensure(){if(channel)return true;try{if(typeof MessageChannel!=='function')return false;channel=new MessageChannel();channel.port1.onmessage=event=>{const item=pending;if(!item||event.data!==item.id)return;finish(item,closed||!owns()?abort():null)};channel.port1.onmessageerror=()=>{const item=pending;dropChannel();if(item)fallback(item)};channel.port1.start?.();return true}catch{dropChannel();return false}}
 function yieldTask(){if(closed||!owns())return Promise.reject(abort());if(pending)return Promise.reject(Error('Projection task pending limit exceeded'));return new Promise((resolve,reject)=>{const item={id:++next,resolve,reject,watch:null,timer:null};pending=item;if(!ensure()){fallback(item);return}try{item.watch=setTimeout(()=>{dropChannel();fallback(item)},2000);channel.port2.postMessage(item.id)}catch{dropChannel();fallback(item)}})}
 function close(){if(closed)return;closed=true;if(pending)finish(pending,abort());dropChannel()}
 return{yieldTask,close};
}
function projectionTaskCloseAll(){for(const session of Array.from(projectionTaskSessions))session.close()}
window.addEventListener('pagehide',projectionTaskCloseAll);
function projectionTaskBegin(win,packet,index,token,active){
 if(index!==1)return null;
 const owns=()=>packet===current&&token===sequence&&active.packet===packet&&active.viewToken===token&&active.doc===active.node.contentDocument;
 const scheduler=createProjectionTaskScheduler(win,owns);
 const session={yieldTask:()=>scheduler.yieldTask(),close(){try{scheduler.close();projectionTaskSessions.delete(session);if(win.__studyProjectionTaskCapture===capture)delete win.__studyProjectionTaskCapture}catch{}}};
 const capture=()=>session;
 try{Object.defineProperty(win,'__studyProjectionTaskCapture',{value:capture,configurable:true});projectionTaskSessions.add(session);return session}catch{session.close();return null}
}
function adaptNativeProjectionTask(code,originalPin){
 if(!["5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93", "b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26", "286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67"].includes(originalPin))return code;
 const edits=[
  ["  async function prepare(data) {\n    if (!data || data.schema !== SCHEMA", "  async function prepare(data) {\n    var projectionTaskSession = window.__studyProjectionTaskCapture ? window.__studyProjectionTaskCapture() : null;\n    if (!data || data.schema !== SCHEMA"],
  ["        await new Promise(function (resolve) { window.setTimeout(resolve, 0); });\n        work = 0; started = window.Date.now();", "        if (projectionTaskSession) await projectionTaskSession.yieldTask();\n        else await new Promise(function (resolve) { window.setTimeout(resolve, 0); });\n        work = 0; started = window.Date.now();"]];
 if(edits.some(([before])=>code.split(before).length!==2))throw Error('Audited projection task boundary differs');
 for(const [before,after]of edits)code=code.replace(before,after);return code;
}
