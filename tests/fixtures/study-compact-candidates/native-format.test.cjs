'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{JSDOM}=require('jsdom');
const helper=fs.readFileSync(process.env.COMPACT_HELPER_SOURCE,'utf8'),raw=JSON.parse(fs.readFileSync(path.join(__dirname,'safari-stock-intrinsics-v2.raw.json'),'utf8'));
function predicate(window){
 const start=helper.indexOf('      function nativeFunction('),end=helper.indexOf('      for (var i',start);assert.ok(start>=0&&end>start);
 let text;const oracle={prototype:{toString:{call:value=>{assert.equal(typeof value,'function');return text;}}}};
 // Replay only actual native text supplied to the unmodified predicate body.
 // Metadata/prototype/coercion guards use real realm functions. This is not
 // actual Safari execution or a replacement of the production stringifier.
 const accept=new Function('Function','Object','Symbol','functionPrototype',helper.slice(start,end)+';return nativeFunction;')(oracle,window.Object,window.Symbol,window.Function.prototype);
 return(value,name,source)=>{text=source;return accept(value,name);};
}
function slot(window,row){if(row.slot.endsWith(' getter'))return window.Object.getOwnPropertyDescriptor(window.Object.prototype,'__proto__').get;if(row.slot.endsWith(' setter'))return window.Object.getOwnPropertyDescriptor(window.Object.prototype,'__proto__').set;return window.Object.prototype[row.slot.slice('Object.prototype.'.length)];}
test('all 13 exact Safari stock native strings downloaded from the actual browser are recognized',t=>{
 const w=new JSDOM('').window;t.after(()=>w.close());const accept=predicate(w);assert.equal(raw.object_prototype_native_functions.length,13);assert.equal(raw.fast_selector,false,'recorded v2 control must remain the original negative Safari evidence');
 for(const row of raw.object_prototype_native_functions){assert.equal(row.actual,'function '+row.expected_name+'() {\n    [native code]\n}');assert.equal(accept(slot(w,row),row.expected_name,row.actual),true,row.slot);}
});
test('non-native bodies, anonymous proxy text and unobserved native representations stay rejected',t=>{
 const w=new JSDOM('').window;t.after(()=>w.close());const accept=predicate(w);
 for(const text of ['function Object() { return "[native code]"; }','function Object() { /* [native code] */ }','function () { [native code] }','function Object() {\n [native code]\n}','function Object() { [native code] } trailing'])assert.equal(accept(w.Object,'Object',text),false,text);
});
test('actual non-native function masquerading by name and native-code comment forces full-scan fallback',t=>{
 const w=new JSDOM('<p class="ordinary">ordinary</p><p class="_r0">alias</p>',{runScripts:'outside-only'}).window;t.after(()=>w.close());
 w.eval('Object.defineProperty(Object.prototype,"hasOwnProperty",{configurable:true,writable:true,value:function hasOwnProperty(){ /* [native code] */ return true;}});');
 w.eval(helper+';window.__compactCandidates=compactClassCandidates;');const selectors=[],query=w.document.querySelectorAll.bind(w.document);w.document.querySelectorAll=selector=>{selectors.push(selector);return query(selector);};
 const result=w.__compactCandidates(w.document,{_r0:'mapped'});assert.deepEqual(selectors,['[class]']);assert.equal(result.length,2);
});
