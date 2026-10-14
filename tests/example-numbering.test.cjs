const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const source=fs.readFileSync('anki_pipeline/templates/example-numbering.js','utf8');
const row=(n,text='word')=>'<li class="example-card"><div class="example-heading"><span class="index-tag">'+n+'</span><span class="example-text">'+text+'</span></div></li>';
function fixture(t,html){const dom=new JSDOM('<body>'+html+'</body>',{runScripts:'outside-only'});t.after(()=>dom.window.close());dom.window.eval(source);return dom.window;}
const tick=w=>new Promise(resolve=>w.setTimeout(resolve,10));
const labels=w=>Array.from(w.document.querySelectorAll('ol.examples > li.example-card:not([hidden]) .example-heading > .index-tag')).map(x=>x.textContent);

test('abide sole remaining row changes 2 to 1 immediately',t=>{const w=fixture(t,'<ol class="examples">'+row(2)+'</ol>');assert.deepEqual(labels(w),['1']);});
test('remove hide restore reorder and lazy append use actual list order',async t=>{
 const w=fixture(t,'<ol class="examples">'+row(2)+row(4)+row(8)+'</ol>');const list=w.document.querySelector('ol');
 assert.deepEqual(labels(w),['1','2','3']);list.children[0].remove();await tick(w);assert.deepEqual(labels(w),['1','2']);
 list.children[0].hidden=true;await tick(w);assert.deepEqual(labels(w),['1']);list.children[0].hidden=false;
 list.insertAdjacentHTML('beforeend',row(16));await tick(w);assert.deepEqual(labels(w),['1','2','3']);
 list.prepend(list.lastElementChild);await tick(w);assert.deepEqual(labels(w),['1','2','3']);
});
test('CSS filtered rows and lazy sentinel do not consume ordinals',t=>{
 const hidden=row(9).replace('<li ','<li style="display:none" ');
 const w=fixture(t,'<ol class="examples">'+hidden+row(13)+'<li class="as-lazy"></li>'+row(19)+'</ol>');
 assert.equal(w.document.querySelectorAll('.index-tag')[1].textContent,'1');assert.equal(w.document.querySelectorAll('.index-tag')[2].textContent,'2');
});
test('history ordinals source anchors marks and occurrence counts stay intact',t=>{
 const history='<details class="sf-inline-history"><summary>original</summary><ol class="examples">'+row(7)+'</ol></details>';
 const w=fixture(t,'<div data-count="3"></div><ol class="examples">'+row(2,'<mark data-id="physical">train</mark><a href="/source?id=unchanged">原句</a>')+'</ol>'+history);
 assert.equal(w.document.querySelector('.sf-inline-history .index-tag').textContent,'7');
 assert.equal(w.document.querySelector('[data-count]').dataset.count,'3');assert.equal(w.document.querySelector('a').getAttribute('href'),'/source?id=unchanged');assert.equal(w.document.querySelector('mark').dataset.id,'physical');
});
test('independent lists repeat install and reused card document',async t=>{
 const w=fixture(t,'<ol class="examples">'+row(5)+'</ol><ol class="examples">'+row(6)+'</ol>');assert.deepEqual(labels(w),['1','1']);
 const one=w.AnkiExampleNumbering.install(w.document);assert.equal(one,w.AnkiExampleNumbering.install(w.document));
 w.document.body.innerHTML='<ol class="examples">'+row(11)+row(17)+'</ol>';await tick(w);assert.deepEqual(labels(w),['1','2']);one.dispose();assert.deepEqual(labels(w),['11','17']);
});
test('persistent WebView releases every removed card badge including front-only replacement',async t=>{
 const w=fixture(t,'<ol class="examples">'+row(8)+'</ol>');const handle=w.AnkiExampleNumbering.install(w.document);
 for(let i=0;i<8;i++){w.document.body.innerHTML='<ol class="examples">'+row(12)+row(18)+'</ol>';await tick(w);assert.equal(handle.stats().retainedBadges,2);}
 w.document.body.innerHTML='<main>front only</main>';await tick(w);assert.equal(handle.stats().retainedBadges,0);
});
