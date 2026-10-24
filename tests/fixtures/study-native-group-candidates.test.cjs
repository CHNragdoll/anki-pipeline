'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const {JSDOM}=require('jsdom');
const dir=__dirname,pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const other='5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e';
const root=process.env.GROUP_CANDIDATES_TEMPLATES+path.sep;
const read=name=>fs.readFileSync(path.join(dir,name),'utf8'),hash=text=>crypto.createHash('sha256').update(text).digest('hex');
const noClone=vm.runInNewContext(fs.readFileSync(root+'native-group-translation-adapter.js','utf8')+'\nadaptNativeGroupTranslationText;');
const bounded=vm.runInNewContext(fs.readFileSync(root+'native-group-ranges-adapter.js','utf8')+'\nadaptNativeGroupRanges;');
const original=fs.readFileSync(process.env.GROUP_CANDIDATES_SOURCE,'utf8'),baseline=bounded(noClone(original,pin),pin);
const adapterSource=fs.readFileSync(root+'native-group-candidates-adapter.js','utf8'),adapt=vm.runInNewContext(adapterSource+'\nadaptNativeGroupCoarseBuckets;');
const candidate=adapt(baseline,pin),graphHook='  function chunkGraph(pair) {';
const id=n=>crypto.createHash('sha256').update(String(n)).digest('hex');
const en='A😀 train & trains.',zh='训练与列车。',source='source';
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
function row(n,options={}){
  const ids=options.graph===false?['bad','bad']:options.graph==='split'?['1','1']:['1','2'];
  const target=options.target??n%2;
  const eng=['A😀 train & ','trains.'].map((text,k)=>'<span class="card-chunk'+(k===target?' sf-target-chunk':'')+'" data-chunk-ids="'+ids[k]+'">'+(k===target?'<mark class="target-word">'+esc(text)+'</mark>':esc(text))+'</span>').join('');
  const ch=['训练与','列车。'].map((text,k)=>'<span class="card-chunk" data-chunk-ids="'+ids[k]+'">'+text+'</span>').join('');
  return '<article class="sf-example" data-sf-year="'+esc(options.year||'2026')+'" data-sf-occurrence-id="'+(options.oid||id(n))+'"><p class="sf-source">'+esc(options.source||source)+'</p><div class="sf-sentence-pair"><p class="sf-en">'+(options.en!==undefined?esc(options.en):eng)+'</p><p class="sf-zh">'+(options.zh!==undefined?esc(options.zh):ch)+'</p></div><p class="exam-usage-labels">'+esc(options.usage||'阅读正文')+'</p><details class="audit"><summary>完整审核 '+n+'</summary><!--evidence--><p>原句译文与依据 '+n+'</p></details></article>';
}
function physical(options={}){
 const e=options.en??en,z=options.zh??zh,s=options.source||source,identity=options.identity||'a';
 return '<li class="example-card"><p class="example-text">'+esc(e)+'</p><p class="example-translation"><span class="translation-label">翻译</span>'+esc(z)+'</p><p class="example-source">'+esc(s)+'</p><a data-rb-j="x|2026-01|p%3Ab-1-1|'+identity.repeat(43)+'|'+'b'.repeat(43)+'|x"></a></li>';
}
function panel(rows){return '<details class="sf-sense"><summary>sense</summary><div class="sf-panel"><button data-sf-filter="2026" aria-pressed="true">2026</button><button data-sf-filter="2025" aria-pressed="false">2025</button><p class="sf-preview-count">initial count</p>'+rows.join('')+'</div></details>';}
function fixture(t,code,panels,physicalRows=[physical()]){
 const dom=new JSDOM('<!doctype html><body><ol>'+physicalRows.join('')+'</ol>'+panels.join('')+'</body>',{runScripts:'outside-only',url:'https://example.test/card'});t.after(()=>dom.window.close());
 const w=dom.window;w.__groupGraphCalls=[];assert.equal(code.split(graphHook).length,2);
 w.eval(code.replace(graphHook,graphHook+' window.__groupGraphCalls.push(pair.parentElement.dataset.sfOccurrenceId);'));
 const doc=w.document,original=doc.body.innerHTML,nodes=Array.from(doc.querySelectorAll('.sf-example,.audit,.audit p,.sf-en span')),texts=nodes.map(node=>node.firstChild);
 const install=()=>w.AnkiSameSenseGroupRuntime.install(doc);
 return{w,doc,original,nodes,texts,install};
}
function assertIdentity(f){f.nodes.forEach((node,i)=>{assert.equal(node.isConnected,true);assert.equal(node.firstChild,f.texts[i]);});}
function compare(t,panels,physicalRows,action){
 const out=[];for(const code of [baseline,candidate]){const f=fixture(t,code,panels,physicalRows),h=f.install();action?.(f,h);const grouped=f.doc.body.innerHTML,stats=JSON.stringify(h.stats());h.refresh();assert.equal(f.doc.body.innerHTML,grouped);h.dispose();assertIdentity(f);out.push({grouped,stats,restored:f.doc.body.innerHTML});}assert.deepEqual(out[1],out[0]);return out[1];
}

test('singletons do not compute chunkGraph but keep original guard/status/output',t=>{
 const f=fixture(t,candidate,[panel([row(1)])]),h=f.install();assert.equal(f.w.__groupGraphCalls.length,0,'old runtime needlessly computes the singleton graph');assert.equal(h.stats().groups,0);h.refresh();assert.equal(f.w.__groupGraphCalls.length,0);h.dispose();assert.equal(f.doc.body.innerHTML,f.original);assertIdentity(f);
});
test('same graph unions three targets and bilingual audit members exactly like original',t=>{
 const out=compare(t,[panel([row(1,{target:0}),row(2,{target:1}),row(3,{target:0})])]);assert.equal(JSON.parse(out.stats).groupedOccurrences,3);
 const dom=new JSDOM(out.grouped);t.after(()=>dom.window.close());const d=dom.window.document;assert.equal(d.querySelectorAll('.sf-group-member-evidence').length,3);assert.equal(d.querySelectorAll('.sf-group-evidence .audit').length,3);assert.equal(d.querySelector('.sf-en').textContent,en);assert.equal(d.querySelector('.sf-zh').textContent,zh);assert.equal(d.querySelectorAll('.sf-example:not([hidden]) .sf-en .sf-target-chunk').length,2);assert.equal(d.querySelectorAll('.sf-example:not([hidden]) .sf-en mark.target-word').length,2);
});
test('same coarse key with different graph stays separate',t=>{const out=compare(t,[panel([row(1),row(2,{graph:'split'})])]);assert.equal(JSON.parse(out.stats).groups,0);});
test('same coarse key with different usage stays separate',t=>{const out=compare(t,[panel([row(1),row(2,{usage:'翻译真题'})])]);assert.equal(JSON.parse(out.stats).groups,0);});
test('ambiguous physical identities and malformed occurrence ids retain all original rejection',t=>{
 const out=compare(t,[panel([row(1),row(2)])],[physical(),physical({identity:'c'})]);assert.equal(JSON.parse(out.stats).groups,0);
 const f=fixture(t,candidate,[panel([row(1,{oid:'invalid'}),row(2,{oid:'invalid'})])]),h=f.install();assert.equal(f.w.__groupGraphCalls.length,0);assert.equal(h.stats().groups,0);
});
test('panel/year/source/exact English/Chinese boundaries remain distinct',t=>{
 const options=[{}, {year:'2025'}, {source:'other'}, {en:en+' '}, {zh:' '+zh}];
 const panels=[panel(options.map((opt,i)=>row(i+1,opt))),panel([row(10)])];
 const native=[physical(),physical({source:'other'}),physical({en:en+' '}),physical({zh:' '+zh})];
 const f=fixture(t,candidate,panels,native),h=f.install();assert.equal(f.w.__groupGraphCalls.length,0);assert.equal(h.stats().groups,0);compare(t,panels,native);
});
test('late panel parts are not processed or cached as singleton; refresh merges and dispose restores identity',t=>{
 const results=[];for(const code of [baseline,candidate]){const f=fixture(t,code,[panel([row(1)])]),p=f.doc.querySelector('.sf-panel'),first=p.querySelector('.sf-example'),audit=first.querySelector('.audit'),h=f.install();let ready=false;f.w.AnkiSlimPanelReady=()=>ready;p.insertAdjacentHTML('beforeend',row(2)+row(3));h.refresh();assert.equal(h.stats().groups,0);ready=true;const expectedDom=new JSDOM(f.original);t.after(()=>expectedDom.window.close());expectedDom.window.document.querySelector('.sf-panel').insertAdjacentHTML('beforeend',row(2)+row(3));const expectedDisposed=expectedDom.window.document.body.innerHTML,late=Array.from(p.querySelectorAll('.sf-example'));h.refresh();assert.equal(h.stats().groupedOccurrences,3);assert.equal(f.doc.querySelector('.sf-group-evidence .audit'),audit);results.push({grouped:f.doc.body.innerHTML,stats:JSON.stringify(h.stats())});h.dispose();assert.equal(f.doc.body.innerHTML,expectedDisposed);late.forEach(node=>assert.equal(node.isConnected,true));assert.equal(p.querySelector('.sf-example'),first);assertIdentity(f);const n=f.w.__groupGraphCalls.length;h.refresh();assert.equal(f.w.__groupGraphCalls.length,n);}assert.deepEqual(results[1],results[0]);
});
test('original grouping order is kept even when coarse buckets interleave final graph keys',t=>{
 const rows=[row(1),row(2,{graph:'split'}),row(3),row(4,{graph:'split'})];const out=compare(t,[panel(rows)]);assert.equal(JSON.parse(out.stats).groups,2);
 const f=fixture(t,candidate,[panel(rows)]);f.install();assert.deepEqual(Array.from(f.w.__groupGraphCalls),[1,2,3,4].map(id));assert.deepEqual(Array.from(f.doc.querySelectorAll('.sf-group-evidence')).map(el=>el.parentElement.dataset.sfOccurrenceId),[id(1),id(2)]);
});
test('filter visibility, exact invalid chunk behavior, refresh and disposal match original',t=>{
 const out=compare(t,[panel([row(1,{graph:false}),row(2,{graph:false})])],undefined,(f,h)=>{const buttons=f.doc.querySelectorAll('[data-sf-filter]');buttons[0].setAttribute('aria-pressed','false');buttons[1].setAttribute('aria-pressed','true');buttons[1].click();assert.equal(f.doc.querySelector('.sf-example').hidden,true);});assert.equal(JSON.parse(out.stats).groups,1);
});
test('real graph errors for multi-member candidates remain the same error before any merge',t=>{
 for(const code of [baseline,candidate]){const f=fixture(t,code,[panel([row(1),row(2)])]),error=new Error('tree walk failure');const originalWalker=f.doc.createTreeWalker.bind(f.doc);f.doc.createTreeWalker=(node,...args)=>{if(node.matches?.('.sf-en,.sf-zh')&&args[0]===4)throw error;return originalWalker(node,...args);};assert.throws(f.install,e=>e===error);assert.equal(f.doc.querySelector('.sf-group-evidence'),null);}
});
test('both original pins share the exact boundary and invert byte-for-byte with the existing algorithms',()=>{
 const edits=vm.runInNewContext(adapterSource.split('  var edits = ')[1].split(';\n  if (edits.some')[0]);
 assert.equal(hash(original),'71d58ba4d44f6c4636f00d017e1cc67aec01fb2286f3ec0880142fd90720993b');
 for(const originalPin of [pin,other]){const result=adapt(original,originalPin);let inverse=result;for(const [before,after]of edits){assert.equal(inverse.split(after).length,2);inverse=inverse.replace(after,before);}assert.equal(inverse,original);assert.equal(adapt(bounded(noClone(original,originalPin),originalPin),originalPin),bounded(noClone(result,originalPin),originalPin));}
});
test('unknown pin remains unchanged and changed/duplicate/already-adapted boundaries reject',()=>{
 for(const unknown of ['',pin.toUpperCase(),'0'.repeat(64),'6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'])assert.equal(adapt('unknown',unknown),'unknown');
 for(const bad of [baseline.replace('var buckets = new Map();','var buckets = new Set();'),baseline+baseline,candidate])assert.throws(()=>adapt(bad,pin),/Audited native group coarse boundary differs/);
});

test('duplicate occurrence identity still rejects a final bucket without marking rows processed',t=>{
 const same=id('same'),rows=[row(1,{oid:same}),row(2,{oid:same})];const out=compare(t,[panel(rows)]);assert.equal(JSON.parse(out.stats).groups,0);
});
test('singleton chunkGraph is a pure reader with invalid ids and no hidden validation or mutations',t=>{
 const f=fixture(t,baseline,[panel([row(1,{graph:false})])]);const start=baseline.indexOf('  function ids(el)'),end=baseline.indexOf('  function sourceKey(',start),graph=f.w.eval('(function(){'+baseline.slice(start,end)+';return chunkGraph;})()');
 const pair=f.doc.querySelector('.sf-sentence-pair'),before=pair.outerHTML,observer=new f.w.MutationObserver(()=>{});observer.observe(pair,{subtree:true,attributes:true,characterData:true,childList:true});
 assert.equal(graph(pair).size,0);assert.equal(pair.outerHTML,before);assert.equal(observer.takeRecords().length,0);observer.disconnect();
});
