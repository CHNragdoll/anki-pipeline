'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const baseline=fs.readFileSync(process.env.FINE_BASELINE,'utf8'),candidate=fs.readFileSync(process.env.FINE_SOURCE,'utf8');
function fixture(t,source,html,options={}){
  const dom=new JSDOM('<!doctype html><body>'+html+'</body>',{runScripts:'outside-only'});t.after(()=>dom.window.close());const w=dom.window;
  w.__ankiSlimManualRefresh=options.manual!==false;
  if(options.state)w.__ankiCardChunkState={...options.state,root:w.document.getElementById(options.state.root)};
  const calls={nativeClosest:0,selectors:[]},closest=w.Element.prototype.closest,query=w.Element.prototype.querySelectorAll;
  w.Element.prototype.closest=function(selector){if(selector==='.example-card')calls.nativeClosest++;return Reflect.apply(closest,this,[selector]);};
  w.Element.prototype.querySelectorAll=function(selector){if(this.classList.contains('example-card')&&selector.startsWith('[data-chunk-'))calls.selectors.push([this.id,selector]);return Reflect.apply(query,this,[selector]);};
  w.eval(source);const handle=w.AnkiFineChunkRuntime.install(w.document);assert.equal(handle,w.AnkiFineChunkRuntime.install(w.document));return{w,handle,calls};
}
function snapshot(item){const state=item.w.__ankiCardChunkState;return{html:item.w.document.body.innerHTML,stats:JSON.stringify(item.handle.stats()),state:state?{root:state.root.id,side:state.side,ids:state.ids,sentenceIds:state.sentenceIds}:null};}
function compare(t,html,options,action){
  const old=fixture(t,baseline,html,options),next=fixture(t,candidate,html,options);
  assert.deepEqual(snapshot(next),snapshot(old));
  if(action){action(old);action(next);assert.deepEqual(snapshot(next),snapshot(old));}
  old.handle.refresh();next.handle.refresh();assert.deepEqual(snapshot(next),snapshot(old));
  old.handle.dispose();next.handle.dispose();assert.deepEqual(snapshot(next),snapshot(old));return{old,next};
}
const fineOnly=()=>'<ol><li id="r" class="example-card">'+Array.from({length:40},(_,i)=>'<span class="card-chunk sf-target-chunk" data-chunk-ids="'+(i+1)+'">fine '+i+'</span>').join('')+'</li></ol>';
const active=()=>'<ol><li id="r" class="example-card"><p><span id="whole" class="card-chunk sf-target-chunk card-chunk-active" data-chunk-ids="9" data-chunk-sentence-ids="9">whole</span><span id="mixed" class="card-chunk sf-target-chunk card-chunk-active" data-chunk-ids="9 1"><mark class="target-word">target</mark></span><span id="other" class="card-chunk sf-target-chunk" data-chunk-ids="9 2">other</span><span id="inline" data-chunk-sentence-ids="9" class="sf-target-chunk">inline metadata only</span></p></li></ol>';

test('no-whole root skips all fine-only isNative checks and the original all-selector scan',t=>{
  const item=fixture(t,candidate,fineOnly());
  assert.equal(item.calls.nativeClosest,0,'whole probe must not run isNative on 40 fine-only chunks');
  assert.deepEqual(item.calls.selectors,[['r','[data-chunk-sentence-ids]']]);
  assert.deepEqual(JSON.parse(JSON.stringify(item.handle.stats())),{rootsWithWhole:0,filteredSpans:0,wholeOnlySpans:0,malformedMetadata:0});
});

test('fine-only no-whole early return preserves DOM, stats and an existing selection object',t=>{
  const html=fineOnly(),options={state:{root:'r',side:'en',ids:['1'],sentenceIds:['9']}};
  const {next}=compare(t,html,options);assert.equal(next.w.document.body.innerHTML,html);assert.equal(next.w.__ankiCardChunkState.ids[0],'1');
});

test('whole, mixed, wrong-target and sentence-only inline metadata keep all original outputs',t=>{
  const old=fixture(t,baseline,active()),next=fixture(t,candidate,active());assert.deepEqual(snapshot(next),snapshot(old));
  assert.equal(next.w.document.getElementById('whole').getAttribute('data-chunk-ids'),'');assert.equal(next.w.document.getElementById('mixed').getAttribute('data-chunk-ids'),'1');assert.equal(next.w.document.getElementById('other').classList.contains('sf-target-chunk'),false);
  assert.equal(next.handle.stats().rootsWithWhole,1);assert.equal(next.handle.stats().filteredSpans,3);assert.equal(next.handle.stats().wholeOnlySpans,1);
  assert.deepEqual(next.calls.selectors.slice(0,2),[['r','[data-chunk-sentence-ids]'],['r','[data-chunk-ids],[data-chunk-sentence-ids]']]);
  old.handle.dispose();next.handle.dispose();assert.equal(next.w.document.body.innerHTML,old.w.document.body.innerHTML);assert.equal(next.w.document.body.innerHTML,active());
});

test('malformed metadata, duplicate IDs, null sentence attributes and leading-zero IDs keep exact statistics',t=>{
  const html='<ol><li id="r" class="example-card"><span data-chunk-ids="7">fine</span><span data-chunk-sentence-ids="">empty</span><span data-chunk-sentence-ids="x">bad</span><span data-chunk-sentence-ids="1  2">spacing</span><span data-chunk-sentence-ids="-1">negative</span><span id="zero" class="card-chunk" data-chunk-ids="09 3" data-chunk-sentence-ids="09 09">zero</span></li></ol>';
  const {next}=compare(t,html,{});assert.equal(next.handle.stats().malformedMetadata,4);assert.equal(next.handle.stats().rootsWithWhole,1);
});

test('malformed-only whole probe retains its malformed count without changing no-whole state',t=>{
  const html='<ol><li id="r" class="example-card"><span class="card-chunk" data-chunk-ids="1">fine</span><span data-chunk-sentence-ids="x">bad</span></li></ol>',options={state:{root:'r',side:'zh',ids:['1'],sentenceIds:['1']}};
  const {next}=compare(t,html,options);assert.equal(next.handle.stats().rootsWithWhole,0);assert.equal(next.handle.stats().malformedMetadata,1);assert.equal(next.w.__ankiCardChunkState.ids[0],'1');
});

test('history, nested roots, root-only metadata, script/style and template scopes remain exact',t=>{
  const history=['sf-ownership-history','sf-original-history-panel','sf-ownership-authority','sf-archived-example','sf-archived-native-example'].map((name,i)=>'<div class="'+name+'"><li class="example-card"><span data-chunk-sentence-ids="bad" data-chunk-ids="9">history'+i+'</span></li></div>').join('');
  const html=history+'<div data-native-ownership-history><li class="example-card"><span data-chunk-sentence-ids="bad">history data</span></li></div><ol><li id="outer" class="example-card" data-chunk-sentence-ids="99"><span data-chunk-ids="99">root attr is ignored</span><div class="sf-ownership-history"><span data-chunk-sentence-ids="bad">inner history</span></div><ol><li id="nested" class="example-card"><span class="card-chunk" data-chunk-ids="9" data-chunk-sentence-ids="9">nested</span><script data-chunk-ids="9 1">text()</script><style data-chunk-ids="9">.x{}</style><template><span data-chunk-sentence-ids="bad" data-chunk-ids="9">inert</span></template></li></ol></li></ol>';
  const {next}=compare(t,html,{});assert.equal(next.handle.stats().rootsWithWhole,1);assert.equal(next.handle.stats().malformedMetadata,0);
});

for(const state of [{side:'en',ids:['9','1'],sentenceIds:['9']},{side:'zh',ids:['9'],sentenceIds:['9']},{side:'zh',ids:['9','1'],sentenceIds:['9']}])test('selection cleanup parity: '+JSON.stringify(state),t=>{
  const {next}=compare(t,active(),{state:{root:'r',...state}});assert.equal(!!next.w.__ankiCardChunkState,state.side==='zh'&&state.ids.length===2);
});

test('late metadata and roots on explicit refresh preserve exact external replacement/restoration',t=>{
  compare(t,fineOnly(),{},item=>{
    const root=item.w.document.getElementById('r'),chunk=root.firstElementChild;chunk.id='changed';chunk.setAttribute('data-chunk-sentence-ids','1');chunk.setAttribute('data-chunk-ids','1 7');chunk.className='card-chunk sf-target-chunk external';item.handle.refresh();
    chunk.setAttribute('data-chunk-ids','1 8');chunk.className='card-chunk sf-target-chunk external-new';item.handle.refresh();
    root.insertAdjacentHTML('beforeend','<div class="example-card"><span class="card-chunk" data-chunk-sentence-ids="2" data-chunk-ids="2 3">late</span></div>');item.handle.refresh();
  });
});

test('late automatic observer refresh and post-dispose external changes remain identical',async t=>{
  const old=fixture(t,baseline,fineOnly(),{manual:false}),next=fixture(t,candidate,fineOnly(),{manual:false});
  for(const item of [old,next]){const span=item.w.document.querySelector('[data-chunk-ids="1"]');span.setAttribute('data-chunk-sentence-ids','1');span.setAttribute('data-chunk-ids','1 8');}
  await new Promise(resolve=>setTimeout(resolve,25));assert.deepEqual(snapshot(next),snapshot(old));assert.equal(next.handle.stats().rootsWithWhole,1);
  old.handle.dispose();next.handle.dispose();for(const item of [old,next])item.w.document.querySelector('span').setAttribute('data-chunk-ids','1 10');await new Promise(resolve=>setTimeout(resolve,15));assert.deepEqual(snapshot(next),snapshot(old));assert.equal(next.w.document.querySelector('span').getAttribute('data-chunk-ids'),'1 10');
});
