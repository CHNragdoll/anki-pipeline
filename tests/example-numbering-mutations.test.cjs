'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync('anki_pipeline/templates/example-numbering.js','utf8');
const row=(id,n,attrs='')=>'<li id="'+id+'" class="example-card" '+attrs+'><span class="index-tag">'+n+'</span></li>';
function fixture(t,html){
  const dom=new JSDOM('<!doctype html><body>'+html+'</body>',{runScripts:'outside-only'});t.after(()=>dom.window.close());const w=dom.window,styles=[],deliveries=[];
  const computed=w.getComputedStyle.bind(w);w.getComputedStyle=node=>{styles.push(node.id);return computed(node);};
  const Observer=w.MutationObserver;let beforeCallback=null;
  w.MutationObserver=function(callback){return new Observer((records,observer)=>{deliveries.push(records);if(beforeCallback)beforeCallback(records);callback(records,observer);});};
  w.eval(source);return{w,styles,deliveries,handle:w.AnkiExampleNumbering.install(w.document),beforeCallback:callback=>{beforeCallback=callback;}};
}
const tick=w=>new Promise(resolve=>w.setTimeout(resolve,20));
const labels=w=>Array.from(w.document.querySelectorAll('ol.examples > li.example-card:not([hidden]) > .index-tag'),badge=>badge.textContent);

for(const action of ['delete','hide'])test('one external '+action+' scans rows once, not again for its own badge replacements',async t=>{
  const {w,styles,deliveries}=fixture(t,'<ol class="examples">'+row('a',1)+row('b',2)+row('c',3)+row('d',4)+'</ol>');
  styles.length=0;if(action==='delete')w.document.getElementById('a').remove();else w.document.getElementById('a').hidden=true;await tick(w);
  assert.deepEqual(labels(w),['1','2','3']);assert.equal(deliveries.length,2,'own records must still be delivered and inspected, not globally drained');
  assert.deepEqual(styles,['b','c','d'],'only the external mutation should cause a full refresh');
});

test('external badge and class mutations in the same pending batch are not hidden by owned writes',async t=>{
  const {w,styles,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+row('c',33)+'</ol>');
  styles.length=0;w.document.querySelector('ol').prepend(w.document.getElementById('c'));handle.refresh();
  w.document.querySelector('#c .index-tag').textContent='90';w.document.getElementById('b').style.display='none';w.document.getElementById('b').classList.add('externally-updated');await tick(w);
  assert.equal(w.document.querySelector('#c .index-tag').textContent,'1');assert.equal(w.document.querySelector('#a .index-tag').textContent,'2');
  assert.equal(styles.length,6,'manual refresh and one external-batch refresh only');
});

test('subsequent external same-text replacement still triggers a refresh by node identity',async t=>{
  const {w,styles,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+'</ol>');
  w.document.querySelector('ol').prepend(w.document.getElementById('b'));handle.refresh();await tick(w);styles.length=0;
  const badge=w.document.querySelector('#b .index-tag'),previous=badge.firstChild;badge.textContent=badge.textContent;assert.notEqual(badge.firstChild,previous);await tick(w);
  assert.deepEqual(styles,['b','a'],'equal text is not evidence that an external record is owned');
});

test('external child-node restoration can repeat identical node lists without being consumed twice',async t=>{
  const {w,styles,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+'</ol>');
  const badge=w.document.querySelector('#b .index-tag'),old=badge.firstChild;w.document.querySelector('ol').prepend(w.document.getElementById('b'));styles.length=0;handle.refresh();
  const own=badge.firstChild;badge.replaceChildren(old);badge.replaceChildren(own);await tick(w);
  assert.equal(badge.textContent,'1');assert.equal(styles.length,4,'the second identical target+added+removed record remains external');
});

test('external edits made just before callback inspection remain observable',async t=>{
  const item=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+row('c',33)+'</ol>'),{w,styles,handle}=item;
  let edited=false;item.beforeCallback(()=>{if(!edited){edited=true;w.document.getElementById('a').hidden=true;w.document.querySelector('#c .index-tag').textContent='99';}});
  styles.length=0;w.document.querySelector('ol').prepend(w.document.getElementById('c'));handle.refresh();await tick(w);
  assert.equal(w.document.querySelector('#c .index-tag').textContent,'1');assert.equal(w.document.querySelector('#b .index-tag').textContent,'2');assert.ok(edited);
  // The external records queued immediately before callback inspection arrive in
  // a later delivery and must trigger a refresh even if current text is correct.
  assert.deepEqual(styles,['c','a','b','c','b','c','b']);
});

test('history stays excluded and disposal clears pending own writes and preserves first originals',async t=>{
  const {w,styles,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+'</ol><details class="sf-inline-history"><summary>old</summary><ol class="examples">'+row('history',71)+'</ol></details>');
  styles.length=0;w.document.querySelector('ol').prepend(w.document.getElementById('b'));handle.refresh();handle.dispose();
  assert.equal(w.document.querySelector('#a .index-tag').textContent,'11');assert.equal(w.document.querySelector('#b .index-tag').textContent,'22');assert.equal(w.document.querySelector('#history .index-tag').textContent,'71');assert.equal(handle.stats().retainedBadges,0);
  styles.length=0;await tick(w);assert.deepEqual(styles,[]);
  const next=w.AnkiExampleNumbering.install(w.document);styles.length=0;w.document.getElementById('a').remove();await tick(w);assert.equal(next.stats().retainedBadges,1);assert.deepEqual(styles,['b']);next.dispose();
});


test('multiple owned writes to the same badge consume only their own ordered records',async t=>{
  const {w,styles,handle}=fixture(t,'<ol class="examples">'+row('a',11)+row('b',22)+row('c',33)+'</ol>');
  const list=w.document.querySelector('ol');styles.length=0;list.prepend(w.document.getElementById('c'));handle.refresh();list.prepend(w.document.getElementById('b'));handle.refresh();await tick(w);
  assert.deepEqual(labels(w),['1','2','3']);assert.deepEqual(styles,['c','a','b','b','c','a','b','c','a']);
});


test('own replacement still prunes a formerly tracked nested badge before disposal',async t=>{
  const {w,handle}=fixture(t,'<ol class="examples"><li id="a" class="example-card"><span id="outer"><span id="inner" class="index-tag">12</span></span></li></ol>');
  const outer=w.document.getElementById('outer'),inner=w.document.getElementById('inner');assert.equal(handle.stats().retainedBadges,1);
  outer.className='index-tag';inner.textContent='19';await tick(w);assert.equal(inner.isConnected,false);
  assert.equal(handle.stats().retainedBadges,1,'owned child replacement must retain original prune behavior');
  handle.dispose();assert.equal(inner.textContent,'19','detached badge must not be restored after pruning');assert.equal(outer.textContent,'19');
});
