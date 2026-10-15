'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom'),{webcrypto,createHash}=require('node:crypto');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
async function until(predicate,message){for(let i=0;i<160;i++){if(predicate())return;await tick()}assert.fail(message)}
const clone=value=>JSON.parse(JSON.stringify(value));
const hash=text=>createHash('sha256').update(text).digest('hex');
function setup({files=input.files,navigation=input.navigation,runtime=input.runtime,page=input.page}={}){
 const errors=[],calls=[],mounted=[],attached=[],cancelled=[],gates=[],vc=new VirtualConsole();
 vc.on('jsdomError',error=>errors.push(error.message));
 const dom=new JSDOM(page,{url:'http://example.test/book/index.html',runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc}),w=dom.window;
 w.TextEncoder=TextEncoder;w.Response=Response;Object.defineProperty(w.crypto,'subtle',{value:webcrypto.subtle});
 const api={cancel(token){cancelled.push(token)},async mountFront(packet){mounted.push({kind:'front',packet});return true},async mount(packet){mounted.push({kind:'full',packet});return true},async attachComplete(packet){attached.push(packet);return true}};
 w.__fixtureApi=api;w.document.getElementById('frame').contentWindow.StudySharedFrame=api;
 w.fetch=async(url,options={})=>{const path=new URL(url,w.location.href).pathname.replace('/book/','');calls.push({path,signal:options.signal});
  if(path==='navigation.json')return new Response(JSON.stringify(navigation));
  if(path.startsWith('cards/'))return new Promise((resolve,reject)=>{const gate={path,signal:options.signal,resolve:()=>resolve(new Response(files[path]))};gates.push(gate);options.signal?.addEventListener('abort',()=>reject(new w.DOMException('superseded','AbortError')),{once:true})});
  if(!(path in files))throw Error('Unexpected fixture request '+path);
  return new Response(files[path]);
 };
 // The dependency is a stub, while fetch/mount/cache/cancel/fallback are the real host.
 const source=runtime.replace('function ensureSharedFrame(){','function ensureSharedFrame(){return Promise.resolve(window.__fixtureApi)}function originalFixtureFrameDependency(){');
 assert.notEqual(source,runtime,'missing exact dependency seam');w.eval(source);
 return{dom,w,calls,mounted,attached,cancelled,gates,errors,close:()=>dom.window.close()};
}
async function hostFlow(){
 const f=setup();await until(()=>f.mounted.length===1,'the complete front must mount while the original full wrapper is blocked');
 assert.equal(f.mounted[0].kind,'front');assert.equal(f.mounted[0].packet.sides.length,1);assert.equal(f.attached.length,0);
 await until(()=>f.gates.length===1,'complete original wrapper was not requested after the front commit');
 assert.equal(f.gates[0].path,'cards/A.html');assert.equal(f.gates[0].signal.aborted,false);
 f.w.document.getElementById('next-card').click();await until(()=>f.mounted.length===2,'B front did not mount');
 assert.equal(f.mounted[1].packet.id,'B');assert.equal(f.gates[0].signal.aborted,true,'navigation must abort A full delivery');
 await until(()=>f.gates.length===2,'B complete delivery did not start');
 f.w.document.getElementById('previous-card').click();await until(()=>f.mounted.length===3,'new A front did not mount');
 await until(()=>f.gates.length===3,'new A complete delivery did not start');
 assert.equal(f.mounted[2].packet.id,'A');assert.ok(f.mounted[2].packet.token>f.mounted[0].packet.token);
 assert.equal(f.gates[1].signal.aborted,true);f.gates[0].resolve();f.gates[1].resolve();await tick();
 assert.equal(f.attached.length,0,'cancelled A/B result attached to the new A session');
 f.gates[2].resolve();await until(()=>f.attached.length===1,'verified complete A never attached');
 assert.equal(f.attached[0].token,f.mounted[2].packet.token);assert.equal(f.attached[0].sides.length,2);
 assert.deepEqual(f.attached[0].deliveryBinding,f.mounted[2].packet.deliveryBinding);
 assert.equal(f.calls.filter(call=>call.path==='front-A.json').length,1,'front cache was not reused within the common cache');
 assert.equal(f.w.document.getElementById('frame').dataset.mountMode,'shared');assert.equal(f.errors.length,0,f.errors.join('\n'));f.close();
}
async function rejectBadFront(){
 const cases=[['card',v=>v.card_id='B'],['wrapper URL',v=>v.wrapper_url='cards/B.html'],['full artifact',v=>v.full_prepared_sha256='f'.repeat(64)],['base',v=>v.base_href='https://outside.test/'],['source bytes',v=>v.source_front+='changed'],['source proof',v=>v.side.proof.source_sha256='e'.repeat(64)],['front schema',v=>v.schema='unknown']];
 for(const[label,mutate]of cases){
  const files=clone(input.files),front=JSON.parse(files['front-A.json']);mutate(front);files['front-A.json']=JSON.stringify(front);
  const index=JSON.parse(files['prepared-index.json']);index.cards.A.front.sha256=hash(files['front-A.json']);files['prepared-index.json']=JSON.stringify(index);
  // Re-pin the fixture root, so each test reaches the source-binding validation.
  const page=input.page.replace(hash(input.files['prepared-index.json']),hash(files['prepared-index.json'])),f=setup({files,page});
  await until(()=>f.w.document.getElementById('frame').dataset.mountMode==='original-wrapper-fallback',label+' mismatch did not retain original-wrapper fallback');
  assert.equal(f.mounted.length,0,label+' mounted an unverified front');assert.equal(f.attached.length,0);f.close();
 }
 const files=clone(input.files);files['front-A.json']+=' ';const bad=setup({files});
 await until(()=>bad.w.document.getElementById('frame').dataset.mountMode==='original-wrapper-fallback','wrong front bytes digest did not fail closed');assert.equal(bad.mounted.length,0);bad.close();
}
async function rejectDifferentCompleteSide(){
 const files=clone(input.files),full=JSON.parse(files['full-A.json']);full.sides[0].html=full.sides[0].html.replace('完整正面','不一致编译正面');full.sides[0].proof.expanded_sha256=hash(full.sides[0].html);files['full-A.json']=JSON.stringify(full);
 const index=JSON.parse(files['prepared-index.json']),front=JSON.parse(files['front-A.json']);index.cards.A.sha256=hash(files['full-A.json']);front.full_prepared_sha256=index.cards.A.sha256;files['front-A.json']=JSON.stringify(front);index.cards.A.front.sha256=hash(files['front-A.json']);files['prepared-index.json']=JSON.stringify(index);
 const page=input.page.replace(hash(input.files['prepared-index.json']),hash(files['prepared-index.json'])),f=setup({files,page});
 await until(()=>f.mounted.length===1&&f.gates.length===1,'verified small front was not committed first');f.gates[0].resolve();
 await until(()=>f.w.document.getElementById('frame').dataset.mountMode==='original-wrapper-fallback','mismatched complete prepared front did not fail closed');
 assert.equal(f.attached.length,0,'mismatched complete packet crossed the frame API boundary');assert.equal(f.mounted.length,1);f.close();
}
async function legacyWithoutFront(){
 const files=clone(input.files),index=JSON.parse(files['prepared-index.json']);delete index.cards.A.front;files['prepared-index.json']=JSON.stringify(index);
 const page=input.page.replace(hash(input.files['prepared-index.json']),hash(files['prepared-index.json'])),f=setup({files,page});
 await until(()=>f.gates.length===1,'legacy full wrapper did not start');assert.equal(f.mounted.length,0);f.gates[0].resolve();
 await until(()=>f.mounted.length===1,'legacy complete mount failed');assert.equal(f.mounted[0].kind,'full');assert.equal(f.attached.length,0);f.close();
}
(async()=>{await hostFlow();await rejectBadFront();await rejectDifferentCompleteSide();await legacyWithoutFront();console.log(JSON.stringify({contracts:26,passed:true}))})().catch(error=>{console.error(error);process.exit(1)});
