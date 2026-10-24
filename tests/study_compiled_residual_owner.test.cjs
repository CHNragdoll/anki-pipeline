'use strict';
// Profile-only contracts: use the pinned native selectors, never run producers.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const test=require('node:test');
const zlib=require('node:zlib');
const a=require('../anki_pipeline/compiled/profile-ast.cjs');
const moduleDescriptor={
 original_sha256:'5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',
 sha256:'7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4'
};
const moduleCode=zlib.gunzipSync(fs.readFileSync(path.join(__dirname,
 'fixtures/experimental-authored-codec-frame-v1/resource-00.gz'))).toString('utf8');
assert.equal(a.sha(moduleCode),moduleDescriptor.sha256);
const sourceArtifactSha256='1'.repeat(64);
const historyHash='2'.repeat(64);
const safePart='<details class="sf-archived-example"><summary>原审核😀</summary>'+
 '<div class="sf-sentence-pair sf-source-preview"><p class="sf-en">old '+
 '<span class="_r32 keep" _c="e0">word</span></p><p class="sf-zh">原'+
 '<span _c="z0">译</span></p></div></details><pre>完整原始说明\n保留</pre>';
function makeHTML(raw=safePart){
 const pin=a.sha(raw),part={src:'_as_'+pin.slice(0,24)+'.js',sha256:pin,count:1};
 const manifest=JSON.stringify({schema:'anki-slim-segments.v1',parts:[part],total:1});
 const html='<!doctype html><section class="examples-section"><ol><li class="example-card kept">'+
 '<a class="sentence-jump" data-rb-j="source" data-latex-url="latex" data-full-paper-url="full"></a>'+
 '<div class="sf-native-ownership-history" data-native-ownership-history="residual-v1">'+
 '<details class="residual-owner-history" data-history-sha256="'+historyHash+'">'+
 '<summary>本句完整词组转归依据</summary><div class="as-lazy" data-as-kind="detail">'+
 '<script class="as-manifest" type="application/json">'+manifest+'</script></div></details>'+
 '</div></li></ol></section>';
 return{html,pin,part,manifest};
}
function build(html,raw=safePart,parts={[a.sha(raw)]:raw}){
 return a.buildHistorySlots({index:a.indexHTML(html),sourceArtifactSha256,
  moduleCode,module:moduleDescriptor,parts,evidence:{}});
}
test('exact closed residual owner chain preserves graph, pins and source exclusions',()=>{
 const f=makeHTML(),result=build(f.html),slot=result.slots[0],part=slot.parts[0];
 assert.equal(result.slots.length,1);
 assert.deepEqual(slot.region,{selector:'.examples-section',ordinal:0,total:1,ownerPath:[0,0,1,0]});
 assert.deepEqual(slot.ownerAttrs,[['class','residual-owner-history'],['data-history-sha256',historyHash]]);
 assert.equal(slot.ownerTree.name,'DETAILS');
 assert.equal(slot.manifestText,f.manifest);
 assert.deepEqual(slot.nativeSource,['source','latex','full']);
 assert.equal(part.sha256,f.pin);assert.notEqual(part.sha256,historyHash);
 assert.equal(result.scope.parts[0].raw_bytes,Buffer.byteLength(safePart));
 assert.equal(result.scope.parts[0].sha256,f.pin);
 const graph=JSON.stringify(part.tree);
 for(const text of ['原审核😀','完整原始说明\\n保留','card-chunk','target-word','keep'])assert.ok(graph.includes(text));
 assert.ok(!graph.includes('"_c"'));
 assert.equal(part.consumerEvidence.projection_pair_roots.length,1);
 assert.equal(part.consumerEvidence.projection_pair_roots[0].excluded,true);
 for(const name of ['fine_example_roots','bank_containers','group_panels','group_physical_native_rows','residual_key_targets'])
  assert.deepEqual(part.consumerEvidence[name],[]);
 for(const name of ['fine_history_exclusion','projection_exclusion','bank_histories'])
  assert.ok(part.consumerSelectors[name].includes('[data-native-ownership-history]'));
});
test('residual class alone and displaced or unmarked ownership chains are rejected',()=>{
 const {html}=makeHTML();
 const variants=[
  html.replace(' data-native-ownership-history="residual-v1"',''),
  html.replace('data-native-ownership-history="residual-v1"','data-native-ownership-history="other"'),
  html.replace('class="sf-native-ownership-history"','class="other"'),
  html.replace('class="sf-native-ownership-history"','class="sf-native-ownership-history extra"'),
  html.replace('<div class="sf-native-ownership-history"','<section class="sf-native-ownership-history"').replace('</div></li>','</section></li>'),
  html.replace('<details class="residual-owner-history"','<div><details class="residual-owner-history"').replace('</details></div></li>','</details></div></div></li>'),
  html.replace('class="residual-owner-history"','class="residual-owner-history extra"'),
  html.replace('class="example-card kept"','class="_r28"'),
  html.replace('<li class="example-card kept">','<li class="example-card kept"><div>').replace('</div></li>','</div></div></li>')
 ];
 for(const [n,value]of variants.entries())assert.throws(()=>build(value),/unsupported history owner\/manifest/,'variant '+n);
});
test('closed detail, native jump and examples region gates remain mandatory',()=>{
 const {html}=makeHTML();
 for(const value of [
  html.replace('<details class="residual-owner-history"','<details open class="residual-owner-history"'),
  html.replace('class="sentence-jump"','class="unrelated"'),
  html.replace('class="examples-section"','class="unrelated"'),
  html.replace('data-as-kind="detail"','data-as-kind="examples"')
 ])assert.throws(()=>build(value),/unsupported history owner\/manifest/);
});
test('residual direct closed archived DETAILS retains exact example-card graph and exclusions',()=>{
 const raw=safePart.replace('sf-sentence-pair sf-source-preview','sf-sentence-pair example-card');
 const f=makeHTML(raw),result=build(f.html,raw),part=result.slots[0].parts[0];
 assert.equal(part.sha256,f.pin);
 assert.equal(part.tree[0].name,'DETAILS');
 assert.deepEqual(part.tree[0].attrs,[['class','sf-archived-example']]);
 assert.equal(part.tree[0].children[1].name,'DIV');
 assert.deepEqual(part.tree[0].children[1].attrs,[['class','sf-sentence-pair example-card']]);
 const graph=JSON.stringify(part.tree);
 for(const text of ['原审核😀','完整原始说明\\n保留','card-chunk','target-word','keep'])assert.ok(graph.includes(text));
 assert.deepEqual(part.consumerEvidence.projection_pair_roots.map(row=>row.excluded),[true]);
 for(const name of ['fine_example_roots','bank_containers','group_panels','group_physical_native_rows','residual_key_targets'])
  assert.deepEqual(part.consumerEvidence[name],[]);
});
test('residual archived DETAILS exception requires the exact closed direct graph and owner',()=>{
 const raw=safePart.replace('sf-sentence-pair sf-source-preview','sf-sentence-pair example-card');
 for(const variant of [
  raw.replace('<details class="sf-archived-example"','<details open class="sf-archived-example"'),
  raw.replace('class="sf-archived-example"','class="sf-archived-example extra"'),
  raw.replace('class="sf-sentence-pair example-card"','class="sf-sentence-pair example-card extra"'),
  '<div>'+raw+'</div>',
  raw.replace('<details class="sf-archived-example"','<article class="sf-archived-example"').replace('</details>','</article>'),
  raw.replace('<div class="sf-sentence-pair example-card"','<section class="sf-sentence-pair example-card"').replace('</div></details>','</section></details>')
 ])assert.throws(()=>build(makeHTML(variant).html,variant),/history part forbidden scope/);
 const {html}=makeHTML(raw);
 assert.throws(()=>build(html.replace('class="residual-owner-history"','class="sf-ownership-history"'),raw),/history part forbidden scope/);
 assert.throws(()=>build(html.replace(' data-native-ownership-history="residual-v1"',''),raw),/unsupported history owner\/manifest/);
});
test('residual support does not widen other example-card or live consumer scope',()=>{
 for(const raw of [
  '<li class="example-card">another physical row</li>',
  '<div class="sf-sense"><div class="sf-panel"></div></div>',
  '<a class="sentence-jump">reader</a>',
  '<span class="card-chunk" data-reviewed-chunk-projection="residual">key</span>',
  '<script>forbidden()</script>'
 ])assert.throws(()=>build(makeHTML(raw).html,raw),/history part forbidden scope|history has live semantic consumer/);
});
test('residual parts retain strict raw SHA and audited module authentication',()=>{
 const f=makeHTML();
 assert.throws(()=>build(f.html,safePart,{[f.pin]:safePart+' '}),/history part source SHA differs/);
 assert.throws(()=>a.buildHistorySlots({index:a.indexHTML(f.html),sourceArtifactSha256,
  moduleCode:moduleCode+' ',module:moduleDescriptor,parts:{[f.pin]:safePart},evidence:{}}),/history module SHA differs/);
});
