'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(process.env.NUMBERING_SOURCE,'utf8');
const row=(id,number,attrs='')=>'<li id="'+id+'" class="example-card" '+attrs+'><div class="example-heading">'+(number===null?'':'<span class="index-tag">'+number+'</span>')+'<span class="example-text">word</span></div></li>';
function fixture(t,html){
  const dom=new JSDOM('<!doctype html><body>'+html+'</body>',{runScripts:'outside-only'});
  const w=dom.window, events=[];
  t.after(()=>w.close());
  const computed=w.getComputedStyle.bind(w);
  w.getComputedStyle=function(node){const result=computed(node);events.push({type:'style',id:node.id,display:result.display});return result;};
  const text=Object.getOwnPropertyDescriptor(w.Node.prototype,'textContent');
  Object.defineProperty(w.Node.prototype,'textContent',{...text,set(value){
    if(this.nodeType===1 && this.matches('.index-tag'))events.push({type:'write',id:this.closest('li.example-card').id,before:text.get.call(this),after:String(value)});
    return text.set.call(this,value);
  }});
  const Observer=w.MutationObserver;
  w.MutationObserver=function(callback){return new Observer((records,observer)=>{
    events.push({type:'observer-start'});callback(records,observer);events.push({type:'observer-end'});
  });};
  w.eval(source);
  return {w,events,handle:w.AnkiExampleNumbering.install(w.document)};
}
const label=(w,id)=>w.document.querySelector('#'+id+' .index-tag')?.textContent;
const styles=events=>events.filter(e=>e.type==='style').map(e=>e.id);
const writes=events=>events.filter(e=>e.type==='write');
const tick=w=>new Promise(resolve=>w.setTimeout(resolve,15));
function assertReadPhaseBeforeWrites(events){
  const firstWrite=events.findIndex(e=>e.type==='write');
  const lastStyle=events.findLastIndex(e=>e.type==='style');
  assert.ok(firstWrite>=0 && lastStyle>=0,'fixture must actually read styles and change badges');
  assert.ok(lastStyle<firstWrite,'every style read across all lists must complete before the first badge write; actual '+events.filter(e=>e.type==='style'||e.type==='write').map(e=>e.type+':'+e.id).join(', '));
}

test('one refresh reads all eligible rows across all lists before any badge write',t=>{
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('a',7)+row('b',8)+'</ol><ol class="examples">'+row('c',5)+row('d',4)+'</ol>');
  assert.deepEqual(styles(events),['a','b','c','d']);
  assert.deepEqual(writes(events).map(e=>[e.id,e.before,e.after]),[['a','7','1'],['b','8','2'],['c','5','1'],['d','4','2']]);
  assert.deepEqual(['a','b','c','d'].map(id=>label(w,id)),['1','2','1','2']);
  assert.equal(handle.stats().retainedBadges,4);
  assertReadPhaseBeforeWrites(events);
});

test('hidden, stylesheet display-none, history and sentinels keep exact ordinal qualification',t=>{
  const historyClasses=['sf-inline-history','sf-ownership-history','sf-ownership-authority','sf-native-ownership-history','sf-original-history-panel','residual-owner-history','sf-source-confirmation-history','sf-semantic-resolution-history','sf-final-history','sf-archived-example','sf-archived-native-example','sf-pending'];
  const histories=historyClasses.map((name,i)=>'<details class="'+name+'"><summary>old</summary><ol class="examples">'+row('history'+i,71)+'</ol></details>').join('');
  const {w,events}=fixture(t,'<style>.filtered{display:none}</style><ol class="examples">'+row('hidden',80,'hidden')+row('css',81,'style="display:none"')+row('rule',82).replace('class="example-card"','class="example-card filtered"')+row('direct-history',83).replace('class="example-card"','class="example-card sf-inline-history"')+'<li id="sentinel" class="as-lazy"></li>'+row('live',84)+'</ol>'+histories+'<div data-native-ownership-history><ol class="examples">'+row('data-history',85)+'</ol></div><div data-reviewed-source-comparison><ol class="examples">'+row('data-review',86)+'</ol></div>');
  assert.deepEqual(styles(events),['css','rule','live']);
  assert.deepEqual(writes(events).map(e=>e.id),['live']);
  assert.equal(label(w,'live'),'1');
  assert.deepEqual(['hidden','css','rule','direct-history'].map(id=>label(w,id)),['80','81','82','83']);
  for(let i=0;i<historyClasses.length;i++)assert.equal(label(w,'history'+i),'71');
  assert.equal(label(w,'data-history'),'85');assert.equal(label(w,'data-review'),'86');
});

test('missing, empty, illegal and non-owned badges still consume visible row ordinals',t=>{
  const owned='<li id="history-first" class="example-card"><div class="sf-inline-history"><span class="index-tag">88</span></div><span class="index-tag">99</span></li>';
  const nested='<li id="nested-first" class="example-card"><ol><li id="nested-child" class="example-card"><span class="index-tag">66</span></li></ol></li>';
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('missing',null)+row('empty','')+row('illegal','bad')+row('negative','-2')+row('first',99)+owned+row('second',' 77 ')+nested+row('third',98)+'</ol>');
  assert.deepEqual(styles(events),['missing','empty','illegal','negative','first','history-first','second','nested-first','third']);
  assert.deepEqual(writes(events).map(e=>[e.id,e.after]),[['first','5'],['second','7'],['third','9']]);
  assert.equal(label(w,'empty'),'');assert.equal(label(w,'illegal'),'bad');assert.equal(label(w,'negative'),'-2');
  assert.equal(label(w,'history-first'),'88');assert.equal(label(w,'nested-child'),'66');
  assert.equal(handle.stats().retainedBadges,3);
});

test('already-correct badges produce no writes or original records on install and repeated refresh',t=>{
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('a',1)+row('b',2)+'</ol><ol class="examples">'+row('c',1)+'</ol>');
  assert.deepEqual(styles(events),['a','b','c']);assert.deepEqual(writes(events),[]);assert.equal(handle.stats().retainedBadges,0);
  events.length=0;handle.refresh();handle.refresh();
  assert.deepEqual(styles(events),['a','b','c','a','b','c']);assert.deepEqual(writes(events),[]);assert.equal(handle.stats().retainedBadges,0);
  handle.dispose();assert.deepEqual(writes(events),[]);assert.deepEqual(['a','b','c'].map(id=>label(w,id)),['1','2','1']);
});

test('manual reorder refresh preserves first authored text and dispose restores it once',t=>{
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+row('c',33)+'</ol>');
  const list=w.document.querySelector('ol');list.prepend(list.lastElementChild);events.length=0;handle.refresh();
  assert.deepEqual(writes(events).map(e=>[e.id,e.before,e.after]),[['c','3','1'],['a','1','2'],['b','2','3']]);
  assert.equal(handle.stats().retainedBadges,3);
  list.prepend(list.lastElementChild);handle.refresh();
  events.length=0;handle.dispose();
  assert.deepEqual(['a','b','c'].map(id=>label(w,id)),['11','22','33']);
  assert.equal(writes(events).length,3);assert.equal(handle.stats().retainedBadges,0);
  events.length=0;handle.dispose();handle.refresh();assert.deepEqual(events,[]);
});

test('observer handles reorder and badge writes reach a no-write fixed point on second refresh',async t=>{
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+row('c',33)+'</ol>');
  events.length=0;const list=w.document.querySelector('ol');list.prepend(list.lastElementChild);await tick(w);
  assert.deepEqual(Array.from(list.children).map(x=>label(w,x.id)),['1','2','3']);
  const passes=[];let pass=null;
  for(const event of events){if(event.type==='observer-start'){pass=[];passes.push(pass);}else if(event.type==='observer-end'){pass=null;}else if(pass)pass.push(event);}
  assert.equal(passes.length,2,'one mutation refresh and one idempotent refresh caused by changed badge text');
  assert.equal(writes(passes[0]).length,3);assert.equal(writes(passes[1]).length,0);
  assert.deepEqual(styles(passes[0]),['c','a','b']);assert.deepEqual(styles(passes[1]),['c','a','b']);
  events.length=0;await tick(w);assert.deepEqual(events,[],'observer must settle without a mutation loop');
  handle.dispose();
});

test('prune releases removed badges and dispose does not rewrite detached content',async t=>{
  const {w,events,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+'</ol>');
  const detached=w.document.getElementById('a');detached.remove();await tick(w);
  assert.equal(handle.stats().retainedBadges,1);assert.equal(label(w,'b'),'1');
  events.length=0;handle.dispose();assert.equal(detached.querySelector('.index-tag').textContent,'1');assert.equal(label(w,'b'),'22');
  assert.deepEqual(writes(events).map(e=>e.id),['b']);assert.equal(handle.stats().retainedBadges,0);
  w.document.querySelector('ol').append(detached);await tick(w);assert.equal(detached.querySelector('.index-tag').textContent,'1');
});

test('scoped roots and reused install retain root lifecycle without touching neighboring lists',t=>{
  const {w}=fixture(t,'<section id="one"><ol class="examples">'+row('a',11)+row('b',22)+'</ol></section><section id="two"><ol class="examples">'+row('c',33)+'</ol></section>');
  w.AnkiExampleNumbering.install(w.document).dispose();
  const one=w.document.getElementById('one'), handle=w.AnkiExampleNumbering.install(one);
  assert.equal(handle,w.AnkiExampleNumbering.install(one));assert.equal(label(w,'a'),'1');assert.equal(label(w,'b'),'2');assert.equal(label(w,'c'),'33');
  handle.dispose();assert.equal(label(w,'a'),'11');assert.equal(label(w,'b'),'22');
  const replacement=w.AnkiExampleNumbering.install(one);assert.notEqual(handle,replacement);replacement.dispose();
});
