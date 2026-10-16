'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),{JSDOM}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),hash=value=>crypto.createHash('sha256').update(value).digest('hex');
const legacyPin=hash(input.legacy),canonicalPin=hash(input.canonical),nativePin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const adapt=new Function(input.adapt+';return adaptAuthoredCompactClassScan')();
assert.equal(adapt(input.legacy,legacyPin),input.canonical);
assert.equal(adapt(input.canonical,canonicalPin),input.canonical);
assert.throws(()=>adapt(input.legacy+'\n',legacyPin),/numbering boundary differs/);
assert.equal(adapt('unknown shape','unknown-pin'),'unknown shape');
(async()=>{
 const dom=new JSDOM('<script src="old.js"></script><script src="new.js"></script><script src="native.js"></script>');
 const packet={base:'https://example.test/book/media/',policy:{external:{'old.js':legacyPin,'new.js':canonicalPin,'native.js':nativePin},inline:[]},prepared:{modules:{[nativePin]:{src:'evidence/native.js',original_sha256:nativePin,sha256:hash(input.native)}}}};
 const events=[],bodies=new Map([['https://example.test/book/media/old.js',input.legacy],['https://example.test/book/media/new.js',input.canonical],['https://example.test/book/evidence/native.js',input.native]]);
 const resource=async(url,pin)=>{events.push('verify:'+url);const code=bodies.get(url);assert.equal(hash(code),pin,'resource must verify the original bytes before adapting');return code};
 const collect=new Function('resource','URL','document',input.adapt+input.collector+';return collectAuthoredScripts;')(resource,URL,{baseURI:'https://example.test/book/index.html'});
 const scripts=await collect(dom.window.document,packet);
 assert.deepEqual(scripts.map(item=>item.pin),[legacyPin,canonicalPin,nativePin]);
 assert.equal(scripts[0].code,input.canonical);assert.equal(scripts[1].code,input.canonical);assert.equal(scripts[2].code,null);
 assert.ok(events.some(event=>event.endsWith('old.js'))&&events.some(event=>event.endsWith('native.js')));
 // A wrong resource digest is rejected before any authored code is available.
 bodies.set('https://example.test/book/media/old.js',input.legacy+'tampered');
 const corrupt=new JSDOM('<script src="old.js"></script>');await assert.rejects(collect(corrupt.window.document,packet),/original bytes/);corrupt.window.close();
 bodies.set('https://example.test/book/media/old.js',input.legacy);
 // Exercise the exact module-execution slice: verified read -> projection -> group -> execute.
 const executed=[],doc=new JSDOM('<li class="example-card"><div class="example-text">EN</div><div class="example-translation">A<b class="translate-tag">译</b>B</div><div class="example-source">S</div><a data-rb-j="x|2026|p|'+ 'a'.repeat(43)+'|'+ 'b'.repeat(43)+'|x"></a></li>',{runScripts:'outside-only'}).window.document;
 const execute=(actual,code,pin)=>{assert.equal(actual,doc);assert.ok(code.includes('function projectionLookupView('));assert.ok(code.includes('function nativeTranslationText('));assert.ok(code.includes('return { root: el, text: el.textContent, nodes: nodes };'));assert.ok(!code.includes('paragraph.contains(el)'));assert.ok(!code.includes('en.contains(el)'));assert.ok(!code.includes('var translation = zh.cloneNode(true);'));let clones=0;const old=doc.defaultView.Node.prototype.cloneNode;doc.defaultView.Node.prototype.cloneNode=function(...args){clones++;return Reflect.apply(old,this,args)};const start=code.indexOf('/* Presentation only: physical occurrences'),library=code.slice(start),exportSite='  window.AnkiSameSenseGroupRuntime = Object.freeze';assert.equal(library.split(exportSite).length,2);doc.defaultView.eval(library.replace(exportSite,'  window.__testPhysicalNativeIndex = physicalNativeIndex;\n'+exportSite));const index=doc.defaultView.__testPhysicalNativeIndex;assert.equal(Array.from(index(doc).keys())[0],JSON.stringify(['S','EN','AB']));assert.equal(clones,0);executed.push(pin)};
 const active={modules:new Set()};const run=new Function('scripts','packet','active','resource','document','valid','execute','doc',input.adapt+';return (async()=>{const win=doc.defaultView||{};'+input.module+'})();');
 await run(scripts,packet,active,resource,{baseURI:'https://example.test/book/index.html'},()=>true,execute,doc);
 assert.equal(executed.length,1);await run(scripts,packet,active,resource,{baseURI:'https://example.test/book/index.html'},()=>true,execute,doc);assert.equal(executed.length,1,'same realm must not reexecute module');
 // Only the canonical replacement at already-audited numbering positions preserves cohorts.
 const cohort=new Function(input.history+';return {table:staticHistoryCohorts,accept:staticHistoryCohort};')();
 for(const sequence of cohort.table.sequences){const pin=sequence.find(value=>cohort.table.modules[value]),sha=cohort.table.modules[pin],p={prepared:{modules:{[pin]:{original_sha256:pin,sha256:sha,src:'evidence/_study_prepared_module_'+sha+'.js'}}}},parsed={querySelectorAll:()=>[{}]};const accepted=values=>cohort.accept(parsed,p,values.map(pin=>({pin})));assert.equal(accepted(sequence),true);assert.equal(accepted(sequence.map(value=>value===legacyPin?canonicalPin:value)),true);const mixed=sequence.slice();mixed[mixed.indexOf(legacyPin)]=canonicalPin;assert.equal(accepted(mixed),true);const wrong=sequence.slice();wrong[0]=canonicalPin;assert.equal(accepted(wrong),false);assert.equal(accepted(sequence.map(value=>value===legacyPin?'f'.repeat(64):value)),false);}
 doc.defaultView.close();dom.window.close();process.stdout.write(JSON.stringify({contracts:10,passed:true}));
})().catch(error=>{console.error(error);process.exit(1)});
