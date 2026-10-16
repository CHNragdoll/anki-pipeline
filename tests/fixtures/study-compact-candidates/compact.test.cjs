'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{JSDOM}=require('jsdom');
const read=name=>fs.readFileSync(name==='adapter.js'?process.env.COMPACT_ADAPTER_SOURCE:name==='compact-class-candidates.js'?process.env.COMPACT_HELPER_SOURCE:path.join(__dirname,name),'utf8'),baseline=read('original-codec.js'),candidate=fs.readFileSync(process.env.COMPACT_SOURCE,'utf8');
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
function configured(code,extra={},custom=false){const match=code.match(/var config=(\{[^\n]+\});/);assert.ok(match);const config=JSON.parse(match[1]);Object.assign(config.classes,extra);return code.replace(match[0],'var config='+JSON.stringify(config)+';'+(custom?'Object.setPrototypeOf(config.classes,window.__customCompactPrototype);':''));}
// Test-only oracle: JSDOM stock DOM constructors are JavaScript classes.
// Only their source-text representation is replayed; real CE/adoption APIs remain.
function stockElementNativeText(w){
 const stringify=w.Function.prototype.toString,stock=new Map();
 for(const name of Object.getOwnPropertyNames(w)){if(!/^(HTML|SVG|MathML|Element).*Element$/.test(name)&&name!=='Element')continue;const d=Object.getOwnPropertyDescriptor(w,name);if(!d||typeof d.value!=='function')continue;const p=Object.getOwnPropertyDescriptor(d.value,'prototype');if(p&&p.value&&Object.getOwnPropertyDescriptor(p.value,'constructor')?.value===d.value)stock.set(d.value,name);}
 Object.defineProperty(w.Function.prototype,'toString',{configurable:true,writable:true,value:function(){return stock.has(this)?'function '+stock.get(this)+'() { [native code] }':Reflect.apply(stringify,this,[]);}});
}
function execute(t,source,html,options={}){
 const w=new JSDOM(html,{runScripts:'outside-only',url:'https://fixture.test/book/'}).window;t.after(()=>w.close());const d=w.document,query=d.querySelectorAll.bind(d),scans=[],reads=[];
 d.querySelectorAll=function(selector){const nodes=query(selector);if(selector==='[class]'||selector.includes('[class*="_r"]')||selector.startsWith('._r'))scans.push({selector,matches:nodes.length,ids:Array.from(nodes,node=>node.id)});return nodes;};
 stockElementNativeText(w);
 if(options.setup)options.setup(w,reads);
 const snapshots=[];const invoke=()=>{let error=null;try{w.eval(source)}catch(e){error={name:e.name,message:e.message}}snapshots.push({html:d.body.innerHTML,error,reads:reads.slice()});};
 invoke();if(options.repeat){options.repeat(w);invoke();}return{w,scans,snapshots};
}
function compare(t,html,options={},code=source=>source){const old=execute(t,code(baseline),html,options),next=execute(t,code(candidate),html,options);assert.deepEqual(next.snapshots,old.snapshots);return{old,next};}
const aliases=()=>'<div class="vocab-card">'+Array.from({length:45},(_,i)=>'<p class="ordinary _r'+i+'">'+i+'</p>').join('')+'</div>';
test('after parsed decode, ordinary classes no longer enter the mapping loop',t=>{
 const initial=execute(t,baseline,aliases()).snapshots[0].html;
 const {old,next}=compare(t,initial);assert.equal(old.scans[0].matches,46);assert.equal(next.scans[0].matches,0);assert.notEqual(next.scans[0].selector,'[class]');
});
test('all 45 aliases and mixed/duplicate ordinary tokens retain exact DOM and ancestor markers',t=>{
 const {next}=compare(t,aliases()+'<div class="vocab-card _r0 ordinary"><span class="_r1 _r2 ordinary">x</span></div>');assert.equal(next.snapshots[0].error,null);assert.ok(next.snapshots[0].html.includes('rb-compact-note'));
});
test('unknown aliases and embedded _r strings preserve original no-op behavior',t=>compare(t,'<p class="_r999 foo_r0 not_an_alias">x</p><p class="plain">y</p>'));
for(const inherited of ['constructor','toString','__proto__'])test('inherited '+inherited+' preserves the original exception and mutation order',t=>{
 const {next}=compare(t,'<div class="vocab-card"><i class="_r0">first</i><b class="'+inherited+'">bad</b><i class="_r1">last</i></div>');assert.equal(next.snapshots[0].error.name,'InvalidCharacterError');assert.ok(next.snapshots[0].html.includes('class="_r1"'));
});
test('new non-enumerable inherited key is included without eager value/getter reads',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'newCompactInherited',{configurable:true,enumerable:false,get(){reads.push('inherited');return 'mapped-inherited';}});
 const {next}=compare(t,'<p class="ordinary newCompactInherited">x</p>',{setup});assert.deepEqual(next.snapshots[0].reads,['inherited','inherited']);assert.equal(next.snapshots[0].error,null);assert.equal(next.scans[0].matches,1);
});
test('an inherited throwing getter retains its original point in document order',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'throwCompactInherited',{configurable:true,get(){reads.push('throwing');throw Error('inherited getter failed');}});
 const {next}=compare(t,'<i class="_r0">first</i><b class="throwCompactInherited">bad</b><i class="_r1">last</i>',{setup});assert.deepEqual(next.snapshots[0].reads,['throwing']);assert.equal(next.snapshots[0].error.message,'inherited getter failed');
});
test('unsafe CSS inherited key falls back to original all-class selector',t=>{
 const setup=w=>Object.defineProperty(w.Object.prototype,'unsafe:key',{value:'mapped',configurable:true});const {next}=compare(t,'<p class="plain unsafe:key">x</p>',{setup});assert.equal(next.scans[0].selector,'[class]');
});
test('unknown non-_r own alias falls back without changing original mapping',t=>{
 const {next}=compare(t,'<p class="plainAlias">x</p>',{},code=>configured(code,{plainAlias:'mapped'}));assert.equal(next.scans[0].selector,'[class]');assert.ok(next.snapshots[0].html.includes('mapped'));
});
test('unsafe own key and oversized own table conservatively use the original scan',t=>{
 for(const extra of [{'_runsafe:key':'mapped'},Object.fromEntries(Array.from({length:150},(_,i)=>['_rx'+i,'mapped']))]){const {next}=compare(t,'<p class="_r0 plain">x</p>',{},code=>configured(code,extra));assert.equal(next.scans[0].selector,'[class]');}
});
test('oversized inherited table conservatively uses the original scan',t=>{
 const setup=w=>{for(let i=0;i<130;i++)Object.defineProperty(w.Object.prototype,'extraCompact'+i,{value:'mapped',configurable:true});};const {next}=compare(t,'<p class="_r0 extraCompact1">x</p>',{setup});assert.equal(next.scans[0].selector,'[class]');
});
test('unfamiliar prototype chain falls back before inspecting a Proxy ownKeys trap',t=>{
 const setup=(w,reads)=>{w.__customCompactPrototype=new w.Proxy(w.Object.prototype,{ownKeys(){reads.push('proxy-ownKeys');throw Error('unexpected prototype enumeration');}});};const {next}=compare(t,'<p class="_r0 plain">x</p>',{setup},code=>configured(code,{},true));assert.equal(next.scans[0].selector,'[class]');assert.deepEqual(next.snapshots[0].reads,[]);
});
test('late aliases and repeated initialization retain original processing and order',t=>{
 const repeat=w=>w.document.body.insertAdjacentHTML('beforeend','<div class="vocab-card"><p class="_r2 plain">late</p></div>');const {next}=compare(t,'<p class="_r1">first</p>',{repeat});assert.equal(next.snapshots.length,2);assert.equal(next.snapshots[1].error,null);
});
test('chunk attributes and valid/invalid jump decoding are byte-equivalent',t=>{
 compare(t,'<div class="vocab-card"><span class="_r1" _c="e1,2">chunk</span><span _c="invalid">bad</span><a data-rb-j="0|2026-01|p:x|'+ 'a'.repeat(43)+'|'+ 'b'.repeat(43)+'|0,1">jump</a><a data-rb-j="bad">invalid</a></div>');
});
test('selector union processes multi-match nodes once in original DOM order',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'sharedInherited',{configurable:true,get(){reads.push('value');return 'mapped';}});const {next}=compare(t,'<p class="_r0 sharedInherited">first</p><p class="sharedInherited _r1">second</p>',{setup});assert.deepEqual(next.snapshots[0].reads,['value','value','value','value']);
});
const adapt=new Function(read('adapter.js')+';return adaptAuthoredCompactCandidates;')();
for(const year of ['2026','2027'])test('full '+year+' source changes only the exact compact helper/selector and inverses to its pin',()=>{
 const original=read('original-'+year+'.js'),expected=JSON.parse(read('inverse-check.json')).find(row=>row.year===year).candidate_sha256,pin=JSON.parse(read('source-provenance.json')).find(x=>x.year===year).sha256,helper=read('compact-class-candidates.js'),start="(function(){'use strict';var config=",afterStart="(function(){'use strict';\n"+helper+'var config=',after='compactClassCandidates(document,config.classes)';
 const result=adapt(original,pin);assert.equal(hash(result),expected);const inverse=result.replace(after,"document.querySelectorAll('[class]')").replace(afterStart,start);assert.equal(inverse,original);assert.equal(hash(inverse),pin);
});
test('unknown source pins retain exact original bytes',()=>{for(const pin of ['', '0'.repeat(64)])assert.equal(adapt('unrelated code',pin),'unrelated code');});
test('both source pins reject missing/duplicate boundaries and repeated adaptation',()=>{
 for(const row of JSON.parse(read('source-provenance.json'))){const source=read('original-'+row.year+'.js');for(const bad of [source.replace("document.querySelectorAll('[class]')",'changedScan()'),source.replace("(function(){'use strict';var config=",'changedStart()'),source+source,adapt(source,row.sha256)])assert.throws(()=>adapt(bad,row.sha256),/boundary differs/);}
});

test('inherited accessor may add an alias to a later initially ordinary node',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'addAliasLater',{configurable:true,get(){reads.push('mutating');w.document.getElementById('later').classList.add('_r1');return 'mapped';}});
 const {next}=compare(t,'<p class="addAliasLater">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.ok(next.snapshots[0].html.includes('field-title'));
});

test('new ordinary inherited data-string key uses union without falling back',t=>{
 const setup=w=>Object.defineProperty(w.Object.prototype,'dataCompactInherited',{configurable:true,enumerable:false,value:'mapped-data'});const {next}=compare(t,'<p class="dataCompactInherited">mapped</p><p class="ordinary">skip</p>',{setup});assert.notEqual(next.scans[0].selector,'[class]');assert.equal(next.scans[0].matches,1);
});
test('custom own accessor that changes a later class retains the full scan',t=>{
 const extra=source=>configured(source).replace(/var config=(\{[^\n]+\});/,matched=>matched+"Object.defineProperty(config.classes,'_rGetter',{get:function(){document.getElementById('later').classList.add('_r1');return 'mapped';}});");
 const {next}=compare(t,'<p class="_rGetter">first</p><p id="later" class="ordinary">later</p>',{},extra);assert.equal(next.scans[0].selector,'[class]');
});
test('unknown inherited object coercion cannot hide later alias mutations',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'objectCompactInherited',{configurable:true,value:{toString(){reads.push('coerce');w.document.getElementById('later').classList.add('_r1');return 'mapped';}}});
 const {next}=compare(t,'<p class="objectCompactInherited">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]');
});
test('custom __proto__ accessor falls back and retains later-node mutations',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object.prototype,'__proto__',{configurable:true,get(){reads.push('custom-proto');w.document.getElementById('later').classList.add('_r1');return 'mapped';}});
 const {next}=compare(t,'<p class="__proto__">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]');
});
test('native inherited function with an own coercion getter falls back before executing it',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Object,'toString',{configurable:true,get(){reads.push('function-coercion');w.document.getElementById('later').classList.add('_r1');return()=> 'mapped';}});
 const {next}=compare(t,'<p class="constructor">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]');assert.deepEqual(next.snapshots[0].reads,['function-coercion']);
});
test('Function.prototype data Symbol.toPrimitive preserves the reviewed later-node regression',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Function.prototype,w.Symbol.toPrimitive,{configurable:true,value:function(){reads.push('function-primitive');w.document.getElementById('later').classList.add('_r1');return 'mapped';}});
 const {next}=compare(t,'<p class="constructor">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]');assert.deepEqual(next.snapshots[0].reads,['function-primitive']);assert.ok(next.snapshots[0].html.includes('ordinary field-title'));
});
test('Function.prototype Symbol.toPrimitive accessor is not read during eligibility',t=>{
 const setup=(w,reads)=>Object.defineProperty(w.Function.prototype,w.Symbol.toPrimitive,{configurable:true,get(){reads.push('primitive-get');return function(){reads.push('primitive-call');w.document.getElementById('later').classList.add('_r1');return 'mapped';};}});
 const {next}=compare(t,'<p class="constructor">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]');assert.deepEqual(next.snapshots[0].reads,['primitive-get','primitive-call']);
});
test('Function.prototype valueOf and detectable toString anomalies fall back without early getter execution',t=>{
 for(const kind of ['valueOf-data','valueOf-accessor','toString-accessor','toString-nonfunction']){
  const setup=(w,reads)=>{const original=w.Function.prototype.toString;if(kind==='valueOf-data')Object.defineProperty(w.Function.prototype,'valueOf',{configurable:true,value:function(){reads.push('valueOf-call');return 'mapped';}});if(kind==='valueOf-accessor')Object.defineProperty(w.Function.prototype,'valueOf',{configurable:true,get(){reads.push('valueOf-get');return function(){return 'mapped';};}});if(kind==='toString-accessor')Object.defineProperty(w.Function.prototype,'toString',{configurable:true,get(){reads.push('toString-get');w.document.getElementById('later').classList.add('_r1');return original;}});if(kind==='toString-nonfunction')Object.defineProperty(w.Function.prototype,'toString',{configurable:true,value:'not callable'});};
  const {next}=compare(t,'<p class="constructor">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]',kind);if(kind.startsWith('valueOf'))assert.deepEqual(next.snapshots[0].reads,[],kind);if(kind==='toString-accessor')assert.deepEqual(next.snapshots[0].reads,['toString-get']);
 }
});
test('unknown Function/native-value prototype coercion chains retain the full original NodeList',t=>{
 for(const target of ['Function.prototype','native-value']){
  const setup=(w,reads)=>{const parent=w.Object.create(target==='Function.prototype'?w.Object.prototype:w.Function.prototype);w.Object.defineProperty(parent,w.Symbol.toPrimitive,{value:function(){reads.push('chain-primitive');w.document.getElementById('later').classList.add('_r1');return 'mapped';}});w.Object.setPrototypeOf(target==='Function.prototype'?w.Function.prototype:w.Object,parent);};
  const {next}=compare(t,'<p class="constructor">trigger</p><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector,'[class]',target);assert.deepEqual(next.snapshots[0].reads,['chain-primitive']);
 }
});

// v4: only selector construction changes. Full IIFE comparisons retain DOM,
// exception, original getter/coercion and mutation-order assertions above.
test('v4 selects known own aliases and omits unknown _r tokens and substrings',t=>{
 const html='<div class="vocab-card"><p id="known" class="ordinary _r0">known</p><p id="unknown" class="_r999">unknown</p><p id="substring" class="ordinary_r_suffix">substring</p><p id="suffix" class="_r0_suffix">suffix</p><p id="custom" class="_rCustom">custom</p></div>';
 const {old,next}=compare(t,html,{},code=>configured(code,{_rCustom:'mapped-custom'}));
 assert.equal(old.scans[0].matches,6);assert.deepEqual(next.scans[0].ids,['known','custom']);
 assert.equal(next.scans[0].selector.includes('[class*='),false);
 assert.ok(next.scans[0].selector.split(',').includes('._r0'));
 assert.ok(next.scans[0].selector.split(',').includes('._rCustom'));
 assert.ok(next.scans[0].selector.split(',').includes('.constructor'));
 assert.equal(next.snapshots[0].error,null);
});
test('v4 direct safe CSS identifiers use class selectors while token-only names retain attribute selectors',t=>{
 const names=['safeClass','_under','9number','-leading','-','--double','9'];
 const setup=w=>{for(const name of names)Object.defineProperty(w.Object.prototype,name,{configurable:true,writable:true,value:'mapped-'+name.replace(/[^A-Za-z0-9]/g,'x')});};
 const html=names.map((name,i)=>'<p id="name'+i+'" class="'+name+'">'+name+'</p>').join('')+'<p class="ordinary">ordinary</p>';
 const {next}=compare(t,html,{setup});const clauses=next.scans[0].selector.split(',');
 for(const name of names.slice(0,2))assert.ok(clauses.includes('.'+name),name);
 for(const name of names.slice(2))assert.ok(clauses.includes('[class~="'+name+'"]'),name);
 assert.equal(next.scans[0].matches,names.length);assert.equal(next.snapshots[0].error,null);
 // A non-writable inherited array index also affects selector-array push;
 // preserve the previous helper's conservative full-scan fallback.
 const blocked=compare(t,'<p class="9">numeric</p><p class="ordinary">plain</p>',{setup:w=>Object.defineProperty(w.Object.prototype,'9',{configurable:true,value:'mapped-number'})});
 assert.equal(blocked.next.scans[0].selector,'[class]');
});
test('v4 indexed-selector union deduplicates overlapping matches in document order',t=>{
 const setup=w=>Object.defineProperty(w.Object.prototype,'dataInherited',{configurable:true,value:'mapped-data'});
 const html='<section id="parent" class="_r1 dataInherited"><p id="first" class="dataInherited _r0">first</p><p id="skip" class="ordinary_r_suffix">skip</p><p id="second" class="_r2 dataInherited">second</p></section><p id="last" class="dataInherited">last</p>';
 const {next}=compare(t,html,{setup});assert.deepEqual(next.scans[0].ids,['parent','first','second','last']);assert.equal(next.scans[0].selector.includes('[class*='),false);assert.equal(next.snapshots[0].error,null);
});


test('custom element class reactions retain the full original live callback order',t=>{
 const setup=w=>{w.customElements.define('compact-reaction',class extends w.HTMLElement{static get observedAttributes(){return ['class'];}attributeChangedCallback(){if(this.classList.contains('exam-frequency')||this.classList.contains('rb-compact-note'))w.document.getElementById('later').classList.add('_r1');}});};
 const {next}=compare(t,'<compact-reaction class="_r0">first</compact-reaction><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[0].selector.startsWith('._r'),true);assert.equal(next.scans[1].selector,'[class]');assert.ok(next.snapshots[0].html.includes('id="later" class="ordinary field-title"'));
});
test('custom closest vocab-card reactions force fallback before any decoder mutation',t=>{
 const setup=w=>{w.customElements.define('compact-card',class extends w.HTMLElement{static get observedAttributes(){return ['class'];}attributeChangedCallback(){if(this.classList.contains('exam-frequency')||this.classList.contains('rb-compact-note'))w.document.getElementById('later').classList.add('_r1');}});};
 const {next}=compare(t,'<compact-card class="vocab-card"><i class="_r0">first</i></compact-card><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[1].selector,'[class]');assert.ok(next.snapshots[0].html.includes('id="later" class="ordinary field-title"'));
});
test('customized builtins and unknown constructors fail closed without invoking custom getters',t=>{
 const setup=w=>{w.customElements.define('compact-button',class extends w.HTMLButtonElement{static get observedAttributes(){return ['class'];}attributeChangedCallback(){if(this.classList.contains('exam-frequency')||this.classList.contains('rb-compact-note'))w.document.getElementById('later').classList.add('_r1');}},{extends:'button'});};
 const {next}=compare(t,'<button is="compact-button" class="_r0">first</button><p id="later" class="ordinary">later</p>',{setup});assert.equal(next.scans[1].selector,'[class]');assert.ok(next.snapshots[0].html.includes('id="later" class="ordinary field-title"'));
 const getterSetup=(w,reads)=>{const n=w.document.querySelector('p'),p=w.Object.create(w.HTMLParagraphElement.prototype);w.Object.defineProperty(p,'constructor',{get(){reads.push('forbidden-constructor');throw Error('custom getter must not run');}});w.Object.setPrototypeOf(n,p);};
 const unknown=compare(t,'<p class="_r0">first</p><b class="ordinary">last</b>',{setup:getterSetup});assert.deepEqual(unknown.next.snapshots[0].reads,[]);assert.equal(unknown.next.scans[1].selector,'[class]');
});
test('cross-realm adopted ordinary elements retain the single-query fast path',t=>{
 const setup=w=>{const donor=new JSDOM('<div class="vocab-card"><p class="_r0">adopted</p><b class="ordinary">unchanged</b></div>',{runScripts:'outside-only'});t.after(()=>donor.window.close());stockElementNativeText(donor.window);const parentStringify=w.Function.prototype.toString,donorProto=donor.window.HTMLParagraphElement.prototype,donorCtor=Object.getOwnPropertyDescriptor(donorProto,'constructor').value,divCtor=donor.window.HTMLDivElement;Object.defineProperty(w.Function.prototype,'toString',{configurable:true,writable:true,value:function(){return this===donorCtor?'function HTMLParagraphElement() { [native code] }':this===divCtor?'function HTMLDivElement() {\n    [native code]\n}':Reflect.apply(parentStringify,this,[]);}});w.document.body.appendChild(w.document.adoptNode(donor.window.document.querySelector('div')));};
 const {next}=compare(t,'<main class="ordinary">plain</main>',{setup});assert.equal(next.scans.length,1);assert.notEqual(next.scans[0].selector,'[class]');assert.equal(next.scans[0].matches,1);assert.ok(next.snapshots[0].html.includes('exam-frequency'));
});
