/* Native view/pairs lookup contract; both paths share the same processor.
 * Compare exact view snapshots, DOM/highlights, processed/error ordering and
 * refreshed text. Full source validators/process remain unmodified by the
 * production adapter and are exercised by the existing real-card QA. */
const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const fixture=String.raw`(function(){
  var warmHashes=new Map(),warmHashBytes=0;
  function digest(value){if(warmHashes.has(value))return warmHashes.get(value);var job=uncachedDigest(value);if(value.length<=65536){warmHashes.set(value,job);warmHashBytes+=value.length*2;while(warmHashes.size>256||warmHashBytes>1048576){var oldest=warmHashes.keys().next().value;warmHashes.delete(oldest);warmHashBytes-=oldest.length*2;}job.catch(function(){if(warmHashes.get(value)===job){warmHashes.delete(value);warmHashBytes-=value.length*2;}});}return job;}
  function uncachedDigest(value){window.realDigestCalls=(window.realDigestCalls||0)+1;return window.digestBehavior(value);}
  window.cacheContract={digest:digest,has:function(value){return warmHashes.has(value)},keys:function(){return Array.from(warmHashes.keys())},entries:function(){return warmHashes.size},bytes:function(){return warmHashBytes}};
  var excluded='.history,[data-reviewed-source-comparison]';
  function key(en,zh){return JSON.stringify([en,zh]);}
  function view(container, nativeChinese) {
    window.lookupCalls[container.closest('.example-card,.sf-sentence-pair').id]=(window.lookupCalls[container.closest('.example-card,.sf-sentence-pair').id]||0)+1;
    var skip = new Set(), spacer = null, first = container.firstChild;
    if (nativeChinese && first && first.nodeType === 1 && first.matches('span.translate-tag') && first.textContent === '翻译') {
      skip.add(first);
      if (first.nextSibling && first.nextSibling.nodeType === 3 && first.nextSibling.data.startsWith(' ')) spacer = first.nextSibling;
    }
    var walker = container.ownerDocument.createTreeWalker(container, 4), nodes = [], text = '', node;
    while ((node = walker.nextNode())) {
      if (skip.has(node) || Array.from(skip).some(function (part) { return part.contains && part.contains(node); })) continue;
      var localStart = node === spacer ? 1 : 0, value = node.data.slice(localStart);
      if (value.length) nodes.push({ node: node, localStart: localStart, start: text.length, end: text.length + value.length }); text += value;
    }
    var offsets = [0], cursor = 0;
    for (var character of text) { cursor += character.length; offsets.push(cursor); }
    return { container: container, text: text, nodes: nodes, offsets: offsets };
  }
  function pairs(doc) {
    var result = [];
    doc.querySelectorAll('.example-card,.sf-sentence-pair').forEach(function (root) {
      if (root.closest(excluded)) return;
      var sf = root.classList.contains('sf-sentence-pair');
      function own(selector) { return Array.from(root.querySelectorAll(selector)).find(function (el) {
        return !el.closest(excluded) && el.closest('.example-card,.sf-sentence-pair') === root;
      }); }
      var en = own(sf ? '.sf-en' : '.example-text'), zh = own(sf ? '.sf-zh' : '.example-translation');
      if (en && zh) result.push({ root: root, en: view(en, false), zh: view(zh, !sf) });
    });
    return result;
  }
  window.createLookup=function(doc,index){var processed=new WeakMap(),stats={exactPairs:0,unmatchedPairs:0,errors:[]},snapshots=[];
    function process(pair) {
      var exact = key(pair.en.text, pair.zh.text), prior = processed.get(pair.root);
      if (prior === exact) return;
      if (prior !== undefined) { stats.errors.push('An already projected pair changed text; dispose/reinstall required'); processed.set(pair.root, exact); return; }
      var record = index.get(exact); if (!record) { stats.unmatchedPairs++; processed.set(pair.root, exact); return; }
      if(record.error)throw Error(record.error);
      snapshots.push({id:pair.root.id,en:{text:pair.en.text,offsets:pair.en.offsets,nodes:pair.en.nodes.map(n=>[n.node.data,n.localStart,n.start,n.end])},zh:{text:pair.zh.text,offsets:pair.zh.offsets,nodes:pair.zh.nodes.map(n=>[n.node.data,n.localStart,n.start,n.end])}});
      processed.set(pair.root,exact);stats.exactPairs++;
      var text=pair.en.nodes[0]?.node;if(text&&!text.parentElement.classList.contains('sf-target-chunk')){var mark=doc.createElement('span');mark.className='card-chunk sf-target-chunk';text.replaceWith(mark);mark.append(text);}
    }
    function refresh(){
      try { pairs(doc).forEach(function (pair) { try { process(pair); } catch (error) { stats.errors.push(error.message); if (options.onError) options.onError(error); } }); }
      catch(error){stats.errors.push(error.message)}
    }
    var options={};return{refresh,stats,snapshots};
  };
  window.originalLookupView=view;
})();`;
const pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const scope={};new Function(input.adapt+';this.adapt=adaptNativeProjectionLookup;').call(scope);const adapt=scope.adapt;
assert.equal(adapt(fixture,'unknown-original-pin'),fixture);
for(const token of ['  function pairs(doc) {','      if (en && zh) result.push({ root: root, en: view(en, false), zh: view(zh, !sf) });','      try { pairs(doc).forEach(function (pair) { try { process(pair); } catch (error) { stats.errors.push(error.message); if (options.onError) options.onError(error); } }); }','warmHashes.size>256||warmHashBytes>1048576']){
  assert.throws(()=>adapt(fixture.replace(token,token+' ')+token,pin),/boundary differs/,'a duplicate exact boundary was accepted');
  assert.throws(()=>adapt(fixture.replace(token,'changed:'+token.slice(1)),pin),/boundary differs/,'a changed boundary was accepted');
}
const optimized=input.disable?fixture:adapt(fixture,pin);if(!input.disable)assert.throws(()=>adapt(optimized,pin),/boundary differs/);
const html=`<article class="example-card" id="unicode"><p class="example-text">A<span>😀</span>\nB👩‍💻é Z<!--ignored--></p><p class="example-translation"><span class="translate-tag"><b>翻译</b></span> <span>甲😀 乙</span>\n尾</p></article>
<article class="example-card" id="spaces"><p class="example-text"> two spaces </p><p class="example-translation"><span class="translate-tag">翻译</span>  两空格</p></article>
<article class="example-card" id="leading"><p class="example-text">leading</p><p class="example-translation"> <span class="translate-tag">翻译</span> 正文</p></article>
<article class="example-card" id="wrong-label"><p class="example-text">label</p><p class="example-translation"><span class="translate-tag">译文</span> 正文</p></article>
<section class="sf-sentence-pair" id="sf"><p class="sf-en">sf😀</p><p class="sf-zh"><span class="translate-tag">翻译</span> 全部保留</p></section>
<article class="example-card" id="outer"><div class="example-text">outer<section class="sf-sentence-pair" id="inner"><p class="sf-en">inner</p><p class="sf-zh">内层</p></section></div><p class="example-translation">外层</p></article>
<article class="example-card" id="reject"><p class="example-text">reject</p><p class="example-translation">拒绝</p></article>
<article class="example-card" id="change-hit"><p class="example-text">change</p><p class="example-translation">会改变</p></article>
<article class="example-card" id="change-miss"><p class="example-text">not indexed</p><p class="example-translation">未命中</p></article>
<div class="history"><article class="example-card" id="excluded"><p class="example-text">excluded</p><p class="example-translation">历史</p></article></div>
`+Array.from({length:80},(_,i)=>`<article class="example-card" id="many-${i}"><p class="example-text">not indexed ${i} 😀<span> long original text </span></p><p class="example-translation">未命中 ${i}</p></article>`).join('');
function run(source){const dom=new JSDOM(html,{runScripts:'dangerously'}),w=dom.window,doc=w.document;w.lookupCalls={};w.eval(source);const index=new w.Map();for(const id of ['unicode','spaces','leading','wrong-label','sf','outer','inner','reject','change-hit']){const root=doc.getElementById(id),sf=root.classList.contains('sf-sentence-pair'),en=root.querySelector(sf?'.sf-en':'.example-text'),zh=root.querySelector(sf?'.sf-zh':'.example-translation');index.set(JSON.stringify([w.originalLookupView(en,false).text,w.originalLookupView(zh,!sf).text]),id==='reject'?{error:'accepted whole-ID filter must run before projection'}:{});}w.lookupCalls={};const api=w.createLookup(doc,index);api.refresh();const afterFirst={dom:doc.body.innerHTML,stats:JSON.parse(JSON.stringify(api.stats)),snapshots:JSON.parse(JSON.stringify(api.snapshots)),calls:{...w.lookupCalls}};api.refresh();doc.querySelector('#change-hit .example-text').append(' changed😀');doc.querySelector('#change-miss .example-text').textContent='change';doc.querySelector('#change-miss .example-translation').textContent='会改变';api.refresh();api.refresh();doc.querySelector('#change-hit .example-translation').append(' 中文改动');api.refresh();api.refresh();const result={afterFirst,final:{dom:doc.body.innerHTML,stats:JSON.parse(JSON.stringify(api.stats)),snapshots:JSON.parse(JSON.stringify(api.snapshots))}};dom.window.close();return result;}
const old=run(fixture),next=run(optimized),oldComparable=JSON.parse(JSON.stringify(old)),nextComparable=JSON.parse(JSON.stringify(next));delete oldComparable.afterFirst.calls;delete nextComparable.afterFirst.calls;assert.deepEqual(nextComparable,oldComparable,'DOM, target chunks, offsets, error ordering or refresh semantics changed');
for(let i=0;i<80;i++)assert.equal(next.afterFirst.calls['many-'+i]||0,0,'unmatched pair allocated detailed views');assert.ok(old.afterFirst.calls['many-1']>0);assert.ok(next.afterFirst.calls.unicode>0);function xmlResult(source){const dom=new JSDOM('',{runScripts:'dangerously'}),w=dom.window;w.lookupCalls={};w.eval(source);const doc=new w.DOMParser().parseFromString('<article class="example-card" id="xml"><p class="example-text"><![CDATA[excluded data]]>visible😀</p><p class="example-translation">文</p></article>','application/xml'),index=new w.Map([[JSON.stringify(['visible😀','文']),{}]]),api=w.createLookup(doc,index);api.refresh();const value={dom:new w.XMLSerializer().serializeToString(doc),stats:JSON.parse(JSON.stringify(api.stats)),snapshots:JSON.parse(JSON.stringify(api.snapshots))};dom.window.close();return value}assert.deepEqual(xmlResult(optimized),xmlResult(fixture),'XML CDATA fallback changed the original SHOW_TEXT semantics');
console.log(JSON.stringify({oldDetailedCalls:Object.values(old.afterFirst.calls).reduce((a,b)=>a+b,0),newDetailedCalls:Object.values(next.afterFirst.calls).reduce((a,b)=>a+b,0),sameDOMAndErrors:true}));
