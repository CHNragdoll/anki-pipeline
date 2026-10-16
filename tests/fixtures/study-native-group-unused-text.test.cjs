'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),crypto=require('node:crypto');
const {JSDOM}=require('jsdom');
const dir=__dirname,pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const other='5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e';
const root=process.env.GROUP_UNUSED_TEMPLATES+path.sep;
const read=name=>fs.readFileSync(path.join(dir,name),'utf8'),hash=text=>crypto.createHash('sha256').update(text).digest('hex');
const noClone=vm.runInNewContext(fs.readFileSync(root+'native-group-translation-adapter.js','utf8')+'\nadaptNativeGroupTranslationText;');
const bounded=vm.runInNewContext(fs.readFileSync(root+'native-group-ranges-adapter.js','utf8')+'\nadaptNativeGroupRanges;');
const original=read('study-native-group-candidates-runtime.js'),coarse=vm.runInNewContext(fs.readFileSync(root+'native-group-candidates-adapter.js','utf8')+';adaptNativeGroupCoarseBuckets;'),rangesSource=fs.readFileSync(root+'native-group-ranges-adapter.js','utf8'),previousRanges=rangesSource.replace('return { root: el, nodes: nodes };','return { root: el, text: el.textContent, nodes: nodes };');assert.equal(hash(previousRanges),'0faa57d85e721a0a3172ac3fa1e8da6431808043d773ee40a473309c1227a9d9');const oldBounded=vm.runInNewContext(previousRanges+';adaptNativeGroupRanges;'),baseline=coarse(oldBounded(noClone(original,pin),pin),pin);
const adapterSource=read('study-native-group-unused-text-inverse.js'),adapt=vm.runInNewContext(adapterSource+';adaptNativeGroupUnusedText;');
const candidate=coarse(bounded(noClone(original,pin),pin),pin),graphHook='  function chunkGraph(pair) {';
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

test('private textView does not read unused element textContent; node identities and UTF16 offsets stay exact',t=>{
 const f=fixture(t,candidate,[panel([row(1),row(2),row(3)])]),d=f.doc,w=f.w;let reads=0;const descriptor=Object.getOwnPropertyDescriptor(w.Node.prototype,'textContent');Object.defineProperty(w.Node.prototype,'textContent',{...descriptor,get:function(){if(/at textView\b/.test(new Error().stack))reads++;return Reflect.apply(descriptor.get,this,[]);}});const h=f.install();assert.equal(h.stats().groupedOccurrences,3);assert.equal(reads,0,'the old textView still reads a full element string which no caller consumes');h.refresh();h.dispose();assert.equal(reads,0);assertIdentity(f);
});
test('nested chunks and three target/translation/audit unions preserve grouped HTML stats and disposal',t=>{
 const rows=[row(1,{target:0}),row(2,{target:1}),row(3,{target:0})].map(s=>s.replace('A😀 train &amp; ','A😀 <b>train</b> &amp; ').replace('训练与','<i>训练</i>与'));
 const out=compare(t,[panel(rows)]);assert.equal(JSON.parse(out.stats).groupedOccurrences,3);const dom=new JSDOM(out.grouped);t.after(()=>dom.window.close());assert.equal(dom.window.document.querySelectorAll('.sf-group-evidence .audit').length,3);assert.equal(dom.window.document.querySelector('.sf-en').textContent,en);assert.equal(dom.window.document.querySelector('.sf-zh').textContent,zh);
});
test('duplicate rows, different senses/graphs and year filters retain original DOM and stats',t=>{
 compare(t,[panel([row(1),row(2,{graph:'split'}),row(3),row(4,{graph:'split'})]),panel([row(5),row(6)])],undefined,(f,h)=>{const buttons=f.doc.querySelectorAll('[data-sf-filter]');buttons[0].setAttribute('aria-pressed','false');buttons[1].setAttribute('aria-pressed','true');buttons[1].click();assert.equal(f.doc.querySelector('.sf-example').hidden,true);});
 compare(t,[panel([row(1,{oid:id('same')}),row(2,{oid:id('same')})])]);
});
test('late members, repeated refresh and dispose preserve original node identity',t=>{
 const outputs=[];for(const source of [baseline,candidate]){const f=fixture(t,source,[panel([row(1)])]),p=f.doc.querySelector('.sf-panel'),first=p.querySelector('.sf-example'),h=f.install();assert.equal(h.stats().groups,0);p.insertAdjacentHTML('beforeend',row(2)+row(3));const late=Array.from(p.querySelectorAll('.sf-example'));h.refresh();const grouped=f.doc.body.innerHTML;h.refresh();assert.equal(f.doc.body.innerHTML,grouped);outputs.push({html:grouped,stats:JSON.stringify(h.stats())});h.dispose();assert.equal(p.querySelector('.sf-example'),first);late.forEach(n=>assert.equal(n.isConnected,true));assertIdentity(f);}assert.deepEqual(outputs[1],outputs[0]);
});
test('text walker errors and all original grouping-key textContent accesses remain untouched',t=>{
 for(const source of [baseline,candidate]){const f=fixture(t,source,[panel([row(1),row(2)])]),error=Error('walker failure'),walker=f.doc.createTreeWalker.bind(f.doc);f.doc.createTreeWalker=(node,...args)=>{if(node.matches?.('.sf-en,.sf-zh'))throw error;return walker(node,...args)};assert.throws(f.install,e=>e===error);assert.equal(f.doc.querySelector('.sf-group-evidence'),null);}
 const before='    return { root: el, text: el.textContent, nodes: nodes };',after='    return { root: el, nodes: nodes };';assert.equal(candidate.replace(after,before),baseline);assert.ok(candidate.includes('en.textContent, zh.textContent'));assert.ok(candidate.includes('sourceKey(source.textContent.trim(), en.textContent, zh.textContent.trim())'));
});
test('dual approved pin boundary is unique; unknown/raw/duplicate/drift/already-adapted sources fail safely',()=>{
 const before='    return { root: el, text: el.textContent, nodes: nodes };',after='    return { root: el, nodes: nodes };';
 for(const sourcePin of [pin,other]){assert.equal(adapt(baseline,sourcePin).replace(after,before),baseline);for(const bad of [original,baseline+baseline,baseline.replace(before,'changed();'),adapt(baseline,sourcePin)])assert.throws(()=>adapt(bad,sourcePin),/boundary differs/);}
 assert.equal(adapt('unknown module','f'.repeat(64)),'unknown module');
});
