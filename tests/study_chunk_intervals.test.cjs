'use strict';
// Geometry below is an explicit JSDOM oracle. Browser glyph/touch/Find and
// full delivery authentication are separate integration acceptance gates.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {spawnSync}=require('node:child_process');
const {JSDOM}=require('jsdom');
const runtimePath=path.join(__dirname,'../anki_pipeline/templates/study-chunk-intervals.js');
const base=path.resolve(__dirname,'..');
const python=String.raw`
import json, hashlib
from tests.test_study_chunk_intervals import ChunkIntervalsTests, TINY, example
from anki_pipeline import study_chunk_intervals as C
from anki_pipeline.packaging import _example_chunk_ranges, _chunk_translation, _annotate_sentence_chunks, _highlight_example
out={}
def put(name,raw,bindings):
    b=C.compile_html(raw,bindings,expected_source_sha256=hashlib.sha256(raw).hexdigest(),css_sha256='f'*64,plain_chunks_are_interaction_only=True)
    out[name]={'source':raw.decode(),'compact':b.compact_html.decode(),'profile':b.profile,'profile_sha256':b.profile_sha256}
    return b
t=ChunkIntervalsTests()
for name,method in [('train','test_real_train_three_member_group_and_native_compile_without_old_profile'),('abolish','test_real_abolish_native_uses_same_generic_interface_and_exact_inverse')]:
    t.compile=lambda raw,bindings:put(name,raw,bindings)
    getattr(t,method)()
put('tiny',TINY,[t.binding()])
for name,encoded_en,encoded_zh,decoded_en,decoded_zh in [
    ('numeric_cr','A&#13;B','甲&#13;乙','A\rB','甲\r乙'),
    ('literal_crlf','A\r\nB','甲\r\n乙','A\nB','甲\n乙')]:
    raw=('<div class="example-card"><p class="en"><span class="card-chunk" data-chunk-side="en" data-chunk-ids="0">'+encoded_en+'</span></p><p class="zh"><span class="card-chunk" data-chunk-side="zh" data-chunk-ids="0">'+encoded_zh+'</span></p></div>').encode()
    put(name,raw,[C.SentenceBinding('cr',0,example(decoded_en,decoded_zh,[([0,3],[[0,3]])]),english_class='en',chinese_class='zh')])
put('long_key',TINY,[C.SentenceBinding('k'*160,0,example(),english_class='en',chinese_class='zh')])
try:
    put('invalid_long_key',TINY,[C.SentenceBinding('k'*161,0,example(),english_class='en',chinese_class='zh')])
    raise AssertionError('compiler accepted 161-character root key')
except ValueError:
    pass
rich=TINY.replace(b"class='card-chunk'",b"class='card-chunk emphasis' id='original' aria-label='keep' tabindex='0' style='color:red' data-unknown='yes'",1).replace(b'>A</SPAN>',b'>A<!--audit--></SPAN>',1)
put('rich',rich,[t.binding()])
ex=example('A😀 BC & D','甲😀乙 & 丙',[([0,9],[[0,7]]),([1,3],[[1,3]]),([0,4],[[0,3]])])
ex['translation_alignment']['alignments'][0]['note']='整句对应：controlled fallback'
en,zh,_=_example_chunk_ranges(ex)
a=_annotate_sentence_chunks(_highlight_example(ex['text'],'absent','',[],chunk_ranges=en,preserve_source=True),ex['translation_alignment'])
z=_annotate_sentence_chunks(_chunk_translation(ex['translation'],zh),ex['translation_alignment'])
raw=('<div class="example-card"><p class="en">'+a+'</p><p class="zh">'+z+'</p></div>').encode()
put('overlap',raw,[C.SentenceBinding('overlap',0,ex,english_class='en',chinese_class='zh')])
print(json.dumps(out,ensure_ascii=False))
`;
const built=spawnSync(process.env.PYTHON||'python3',['-B','-c',python],{cwd:base,encoding:'utf8',maxBuffer:4*1024*1024});
assert.equal(built.status,0,built.stderr);
const samples=JSON.parse(built.stdout);
const code=fs.readFileSync(runtimePath,'utf8');
const legacyCode=fs.readFileSync(path.join(base,'anki_pipeline/templates/card-chunks.js'),'utf8');
const ROOT='data-study-chunk-interval-root',PAR='data-study-chunk-interval-paragraph';
function clone(x){return JSON.parse(JSON.stringify(x));}
function installAgain(f,p=clone(samples.tiny.profile),sample=samples.tiny){return f.w.StudyChunkIntervals.install(f.d,p,{binding:{source_sha256:sample.profile.source_sha256,compact_sha256:sample.profile.compact_sha256,profile_sha256:sample.profile_sha256,css_sha256:sample.profile.css_sha256},isCurrent:()=>true,clearLegacy(){}});}
function flattened(p){return p.sentences.flatMap(s=>s.paragraphs);}
function pointAt(d,par,at,endBias=false){const w=d.createTreeWalker(par,4);let n,sum=0,last;while((n=w.nextNode())){last=n;if(at<sum+n.data.length||(endBias&&at===sum+n.data.length))return[n,at-sum];sum+=n.data.length;}return[last,last.data.length];}
function spans(par){let at=0,out=[];function walk(n,depth){const start=at;if(n.nodeType===3)at+=n.data.length;else for(const c of n.childNodes)walk(c,depth+1);if(n.nodeType===1&&n.classList.contains('card-chunk'))out.push({node:n,start,end:at,depth});}walk(par,0);return out;}
function fixture(name='tiny',{profile=clone(samples[name].profile),html=samples[name].compact,legacy=false,current=()=>true,binding={},beforeInstall}={}){
  const sample=samples[name],dom=new JSDOM(html,{runScripts:'outside-only'}),w=dom.window,d=w.document;
  let pos=null,invalid=null,cleared=0,flips=0;
  w.PointerEvent=w.MouseEvent;
  // Tests alone supply glyph geometry. No browser support claim is inferred.
  d.caretRangeFromPoint=()=>{if(!pos)return null;const n=parFor(pos.key),[t,o]=pointAt(d,n,pos.offset),r=d.createRange();r.setStart(t,o);r.collapse(true);return r;};
  w.Range.prototype.getClientRects=function(){
    if(!pos||pos.empty)return[];
    const n=parFor(pos.key),r=d.createRange();r.selectNodeContents(n);r.setEnd(this.startContainer,this.startOffset);const a=r.toString().length;r.setEnd(this.endContainer,this.endOffset);const z=r.toString().length;
    return a===pos.start&&z===pos.end?[{left:-1,right:1,top:-1,bottom:1,width:2,height:2}]:[];
  };
  function parFor(key){if(!legacy)return d.querySelector('['+PAR+'="'+key+'"]');const sentence=profile.sentences.find(s=>s.paragraphs.some(p=>p.key===key)),p=sentence.paragraphs.find(p=>p.key===key),root=d.querySelectorAll('.example-card')[sentence.root_index];return root.querySelector(p.side==='en'?'.sf-en,.example-text,.en':'.sf-zh,.example-translation,.zh');}
  let handle;
  try{
    if(legacy)w.eval(legacyCode);
    else{w.eval(code);if(beforeInstall)beforeInstall(w,d,profile);handle=w.StudyChunkIntervals.install(d,profile,{binding:{source_sha256:sample.profile.source_sha256,compact_sha256:sample.profile.compact_sha256,profile_sha256:sample.profile_sha256,css_sha256:sample.profile.css_sha256,...binding},isCurrent:current,clearLegacy(){cleared++;},onInvalid(e){invalid=e;}});}
  }catch(e){w.close();throw e;}
  d.body.addEventListener('click',()=>flips++);
  function fire(type,target,props={}){const event=type==='keydown'?new w.KeyboardEvent(type,{bubbles:true,cancelable:true,...props}):new w.MouseEvent(type,{bubbles:true,cancelable:true,...props});if('pointerType'in props)Object.defineProperty(event,'pointerType',{value:props.pointerType});if(props.alreadyPrevented)event.preventDefault();target.dispatchEvent(event);return event;}
  function dispatch(p,i,type='click',props={}){
    const row=p.segments[i],node=parFor(p.key);pos={key:p.key,offset:props.offset??row[0],start:row[0],end:row[1],empty:!!props.empty};
    let target=node;
    if(legacy||row[5]){const match=spans(node).filter(s=>s.start===row[0]&&s.end===row[1]).sort((a,b)=>b.depth-a.depth)[0];if(match)target=match.node;}
    return fire(type,target,props);
  }
  function active(){return[...d.querySelectorAll('.card-chunk-active')].map(n=>{const p=legacy?flattened(profile).find(p=>parFor(p.key).contains(n)):flattened(profile).find(p=>n.closest('['+PAR+']')===parFor(p.key));return[p?.key,n.dataset.chunkSide,n.dataset.chunkIds,n.textContent];});}
  return{w,d,profile,handle,parFor,fire,dispatch,active,invalid:()=>invalid,cleared:()=>cleared,flips:()=>flips,close(){handle?.dispose();w.close();}};
}
test('common interval runtime is present and exposes the new schema, not the pilot',()=>{
  const runtime=fs.readFileSync(runtimePath,'utf8');
  const dom=new JSDOM('',{runScripts:'outside-only'});
  try {dom.window.eval(runtime);assert.equal(dom.window.StudyChunkIntervals.schema,'study-chunk-intervals.v1');}
  finally {dom.window.close();}
});
test('new compiler real train/abolish outputs use common runtime; every source position agrees with old bilingual chunks',()=>{
  for(const name of ['train','abolish']){
    const f=fixture(name),old=fixture(name,{legacy:true,html:samples[name].source});
    try{
      const text=f.d.body.textContent,audits=[...f.d.querySelectorAll('.sf-group-member-evidence')].map(n=>n.outerHTML);
      for(const p of flattened(f.profile))for(let i=0;i<p.segments.length;i++){
        f.dispatch(p,i,'pointerover',{pointerType:'mouse'});old.dispatch(p,i,'pointerover',{pointerType:'mouse'});
        assert.deepEqual(f.active(),old.active(),name+' '+p.key+' '+i+' hover');
        f.fire('keydown',f.d.body,{key:'Escape'});old.fire('keydown',old.d.body,{key:'Escape'});
        assert.equal(f.dispatch(p,i).defaultPrevented,old.dispatch(p,i).defaultPrevented);
        assert.deepEqual(f.active(),old.active(),name+' '+p.key+' '+i+' tap');
        f.dispatch(p,i);old.dispatch(p,i);assert.deepEqual(f.active(),[]);
      }
      assert.equal(f.invalid(),null);assert.equal(f.flips(),0);assert.equal(f.d.body.textContent,text);
      assert.deepEqual([...f.d.querySelectorAll('.sf-group-member-evidence')].map(n=>n.outerHTML),audits);
    }finally{f.close();old.close();}
  }
});
test('paint/clear restores original Text and mark/unknown/ARIA/tabindex element identities and exact DOM',()=>{
  for(const name of ['rich','train']){const f=fixture(name);try{
    const before=f.d.body.innerHTML,walker=f.d.createTreeWalker(f.d.body,4),texts=[];while(walker.nextNode())texts.push(walker.currentNode);
    const elements=[...f.d.querySelectorAll('mark,[data-unknown],[aria-label],[tabindex]')];
    const p=flattened(f.profile)[0];f.dispatch(p,0);assert(f.active().length);f.fire('keydown',f.d.body,{key:'Escape'});
    assert.equal(f.d.body.innerHTML,before);assert(elements.every(n=>n.isConnected));assert(texts.every(n=>n.isConnected));
    f.handle.dispose();assert.equal(f.d.body.innerHTML,before);
  }finally{f.close();}}
});
test('English first ID, Chinese fine before whole IDs, Unicode boundary and whole tooltip match the original',()=>{
  const f=fixture('overlap'),old=fixture('overlap',{legacy:true,html:samples.overlap.source});try{
    for(const p of flattened(f.profile))for(let i=0;i<p.segments.length;i++){
      f.dispatch(p,i);old.dispatch(p,i);assert.deepEqual(f.active(),old.active());
      f.fire('keydown',f.d.body,{key:'Escape'});old.fire('keydown',old.d.body,{key:'Escape'});
    }
    const p=flattened(f.profile)[0],i=p.segments.findIndex(row=>f.profile.id_sets[row[2]].join(' ')==='1 2 0');
    f.dispatch(p,i);assert.deepEqual(Array.from(f.handle.stats().activeIds),['1']);
    f.fire('keydown',f.d.body,{key:'Escape'});
    const j=p.segments.findIndex(row=>f.profile.attributes[row[4]].some(a=>a[0]==='title'));
    f.dispatch(p,j,'pointerover',{pointerType:'mouse'});assert.equal(f.parFor(p.key).title,'整句对应：已审校双语全文，非词语级对齐');
    f.fire('keydown',f.d.body,{key:'Escape'});assert.equal(f.parFor(p.key).hasAttribute('title'),false);
  }finally{f.close();old.close();}
});
test('Escape latches physical segment: same-segment move stays cleared, crossing boundaries and pointerover reenter',()=>{
  const f=fixture(),p=flattened(f.profile)[0];try{
    f.dispatch(p,0);f.fire('keydown',f.d.body,{key:'Escape'});assert.deepEqual(f.active(),[]);
    f.dispatch(p,0,'pointermove',{pointerType:'mouse'});assert.deepEqual(f.active(),[]);
    f.dispatch(p,1,'pointermove',{pointerType:'mouse'});assert(f.active().length);
    f.fire('keydown',f.d.body,{key:'Escape'});f.dispatch(p,1,'pointerover',{pointerType:'mouse'});assert(f.active().length);
    assert.equal(f.invalid(),null);
  }finally{f.close();}
});
test('pointerout to blank space within the same root clears hover, while a tap survives',()=>{
  const f=fixture(),p=flattened(f.profile)[0];try{
    f.dispatch(p,0,'pointerover',{pointerType:'mouse'});assert(f.active().length);
    f.fire('pointerout',f.d.querySelector('.card-chunk-active'),{pointerType:'mouse',relatedTarget:f.parFor(p.key)});
    assert.deepEqual(f.active(),[]);
    f.dispatch(p,0);f.fire('pointerout',f.d.querySelector('.card-chunk-active'),{pointerType:'mouse',relatedTarget:f.parFor(p.key)});
    assert(f.active().length);
  }finally{f.close();}
});
test('nearest caret requires actual glyph containment, including the right edge; controls/touch/pen do not get intercepted',()=>{
  const f=fixture(),p=flattened(f.profile)[0];try{
    f.dispatch(p,0,'click',{offset:p.segments[0][1]});assert(f.active().length);
    f.fire('keydown',f.d.body,{key:'Escape'});assert.equal(f.dispatch(p,0,'click',{empty:true}).defaultPrevented,false);assert.deepEqual(f.active(),[]);
    for(const pointerType of ['touch','pen']){f.dispatch(p,1,'pointerover',{pointerType});assert.deepEqual(f.active(),[]);}
    const a=f.d.createElement('a');a.href='#original';a.textContent='go';f.d.body.append(a);
    assert.equal(f.fire('click',a).defaultPrevented,false);assert.equal(f.fire('keydown',a,{key:' '}).defaultPrevented,false);
  }finally{f.close();}
});
test('keyboard acts only on retained original chunks and honors modifiers/repeat/default prevention',()=>{
  const f=fixture('rich'),p=flattened(f.profile)[0],n=f.d.getElementById('original');try{
    for(const key of ['Enter',' ']){assert(f.fire('keydown',n,{key}).defaultPrevented);assert(f.active().length);f.fire('keydown',n,{key:'Escape'});}
    for(const props of [{key:'Enter',ctrlKey:true},{key:' ',altKey:true},{key:' ',metaKey:true},{key:' ',repeat:true},{key:'Enter',alreadyPrevented:true}]){assert.equal(f.fire('keydown',n,props).defaultPrevented,!!props.alreadyPrevented);assert.deepEqual(f.active(),[]);}
    assert.equal(n.style.color,'red');assert.equal(n.getAttribute('data-unknown'),'yes');assert.equal(n.getAttribute('aria-label'),'keep');
    assert.equal(f.fire('keydown',f.parFor(p.key),{key:'Enter'}).defaultPrevented,false);
  }finally{f.close();}
});
test('semantic/binding negatives fail before writing; valid IDs cannot be moved to another position',()=>{
  for(const change of [p=>p.schema='study-chunk-interval-pilot.v1',p=>p.sentences[0].root_index++,p=>p.sentences[0].paragraphs[0].segments[0][1]++,p=>p.sentences[0].paragraphs[0].segments[0][2]=p.sentences[0].paragraphs[0].segments[1][2],p=>p.sentences[0].paragraphs[0].prefix='x']){
    const p=clone(samples.tiny.profile);change(p);assert.throws(()=>fixture('tiny',{profile:p}),/Chunk intervals/);
  }
  assert.throws(()=>fixture('tiny',{binding:{compact_sha256:'a'.repeat(64)}}),/mismatch/);
  assert.throws(()=>fixture('tiny',{html:samples.tiny.compact.replace('A &amp;','Z &amp;')}),/canonical paragraph/);
  assert.throws(()=>fixture('tiny',{html:samples.tiny.compact+samples.tiny.compact}),/duplicate/);
  assert.throws(()=>fixture('tiny',{beforeInstall(w,d,p){Object.defineProperty(p,'sources',{get(){throw Error('getter invoked');}});}}),/own JSON data/);
  assert.throws(()=>fixture('tiny',{beforeInstall(w,d,p){Object.setPrototypeOf(p.sentences[0],{foreign:true});}}),/JSON prototype/);
});
test('canonical alignment independently determines range order/IDs/whole membership even with a newly pinned profile',()=>{
  for(const alter of [
    p=>{p.sources[0].ranges.en[0][2]=1;},
    p=>{p.sources[0].ranges.en[0][0]++;},
    p=>{p.sources[0].ranges.en.reverse();},
    p=>{p.sources[0].ranges.zh.reverse();},
    p=>{p.sources[0].sentence_ids=['1'];},
    p=>{p.sources[0].example.translation_alignment.alignments[0].relation='implicit';},
    p=>{p.sources[0].example.translation_alignment.alignments[0].en=[0,999];}
  ]){
    const p=clone(samples.tiny.profile);alter(p);
    const profile_sha256=require('node:crypto').createHash('sha256').update(JSON.stringify(p)).digest('hex');
    assert.throws(()=>fixture('tiny',{profile:p,binding:{profile_sha256}}),/canonical ranges|alignment/);
  }
});
test('profile/caller mutation after install does not change the private snapshot or invoke getters',()=>{
  const p=clone(samples.tiny.profile),f=fixture('tiny',{profile:p});try{
    p.sentences[0].paragraphs[0].segments[0][2]=0;p.id_sets.length=0;p.sources[0].example.text='foreign';
    f.dispatch(samples.tiny.profile.sentences[0].paragraphs[0],0);assert.deepEqual(Array.from(f.handle.stats().activeIds),['0']);assert.equal(f.invalid(),null);
  }finally{f.close();}
});
test('current-root interaction never queries/scans other roots or the whole document after its initial index',()=>{
  const f=fixture('train'),p=flattened(f.profile)[0];try{
    f.d.querySelectorAll=()=>{throw Error('whole document rescan');};
    const other=f.parFor(flattened(f.profile).at(-1).key);Object.defineProperty(other,'textContent',{get(){throw Error('other root visited');}});
    f.dispatch(p,0);assert(f.handle.stats().handled);assert.equal(f.invalid(),null);f.fire('keydown',f.d.body,{key:'Escape'});
  }finally{f.close();}
});
test('explicit legacy handoff and reverse release keep one owner; stale/cancel/ABA disposal does not alter the new document',()=>{
  let current=true;const f=fixture('tiny',{current:()=>current}),p=flattened(f.profile)[0];try{
    f.dispatch(p,0);assert.equal(f.cleared(),1);assert(f.active().length);assert.equal(f.handle.release(),true);assert.deepEqual(f.active(),[]);
    f.dispatch(p,0);current=false;const before=f.d.body.innerHTML;
    f.dispatch(p,1);assert.equal(f.handle.release(),false);assert.throws(()=>f.handle.refresh(),/cancelled/);f.handle.dispose();assert.equal(f.d.body.innerHTML,before);
    const g=fixture();try{g.dispatch(flattened(g.profile)[0],1);const html=g.d.body.innerHTML;f.fire('keydown',f.d.body,{key:'Escape'});assert.equal(g.d.body.innerHTML,html);}finally{g.close();}
  }finally{f.close();}
});
test('external text, moved/replaced nodes or altered owned paint fail closed without deleting foreign changes',()=>{
  for(const mode of ['text','move','replace','paint']){
    const f=fixture(),p=flattened(f.profile)[0];try{
      const par=f.parFor(p.key),root=par.closest('['+ROOT+']');
      if(mode==='paint'){f.dispatch(p,0);const n=f.d.querySelector('[data-study-chunk-interval-painted]');n.setAttribute('data-external','keep');n.append('foreign');}
      else if(mode==='text')par.firstChild.data+='external';
      else if(mode==='move'){const host=f.d.createElement('div');f.d.body.append(host);host.append(root);}
      else root.replaceWith(root.cloneNode(true));
      const before=f.d.body.innerHTML;
      assert.throws(()=>f.handle.refresh(),/changed|moved|replaced/);f.handle.dispose();assert.equal(f.d.body.innerHTML,before);
    }finally{f.close();}
  }
});
test('review regression: duplicate same/other profile installs reject without listeners until explicit dispose; old dispose is ABA-safe',()=>{
  const f=fixture();let next=null;try{
    const before=f.d.body.innerHTML;
    assert.throws(()=>installAgain(f),/document already owned/);
    const other=clone(samples.tiny.profile);other.sentences[0].key='foreign';
    assert.throws(()=>installAgain(f,other),/document already owned/);assert.equal(f.d.body.innerHTML,before);
    const p=flattened(f.profile)[0];f.dispatch(p,0);assert.equal(f.invalid(),null);assert(f.active().length);
    f.handle.dispose();assert.equal(f.d.body.innerHTML,before);
    next=installAgain(f);f.handle.dispose();f.dispatch(p,0);assert(next.stats().handled);assert.equal(next.stats().invalid,null);
    f.handle.dispose();assert.deepEqual(Array.from(next.stats().activeIds),['0']);
  }finally{next?.dispose();f.close();}
});
test('review regression: repeating the same runtime script preserves the API and document owner registry',()=>{
  const f=fixture();try{
    const first=f.w.StudyChunkIntervals;f.w.eval(code);assert.equal(f.w.StudyChunkIntervals,first);
    assert.throws(()=>f.w.eval(code.replace("var REVISION = 'study-chunk-intervals.runtime.v1';","var REVISION = 'study-chunk-intervals.runtime.other';")),/runtime revision conflict/);
    assert.equal(f.w.StudyChunkIntervals,first);
    assert.throws(()=>installAgain(f),/document already owned/);
    const p=flattened(f.profile)[0];f.dispatch(p,0);assert.equal(f.invalid(),null);assert(f.active().length);
  }finally{f.close();}
});
test('review regression: Shift+Enter/Space match the real Projection keyboard modifier predicate',()=>{
  // Verbatim be392 Projection keyboard function, originally lines 650-657.
  // It delegates a synthetic click to the unchanged legacy chunk handler.
  const original=String.raw`    function keyboard(event) {
      if (disposed || event.defaultPrevented || event.repeat || event.ctrlKey || event.altKey || event.metaKey || (event.key !== 'Enter' && event.key !== ' ')) return;
      var el = event.target;
      if (!wrappers.has(el) || el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable]')) return;
      event.preventDefault();
      el.dispatchEvent(new doc.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    }`;
  const old=fixture('rich',{legacy:true,html:samples.rich.source}),f=fixture('rich');try{
    const a=old.d.getElementById('original'),b=f.d.getElementById('original');
    const keyboard=new Function('doc','wrappers','disposed',original+';return keyboard;')(old.d,new Set([a]),false);
    old.d.addEventListener('keydown',keyboard,true);
    for(const key of ['Enter',' ']){
      assert.equal(f.fire('keydown',b,{key,shiftKey:true}).defaultPrevented,old.fire('keydown',a,{key,shiftKey:true}).defaultPrevented);
      assert.deepEqual(f.active(),old.active());assert(f.active().length);
      f.fire('keydown',f.d.body,{key:'Escape'});old.fire('keydown',old.d.body,{key:'Escape'});
    }
  }finally{f.close();old.close();}
});
test('review regression: immutable root/nearest physical occurrence drift rejects; legitimate hidden UI state remains allowed',()=>{
  for(const kind of ['occurrence','root-attrs']){
    const f=fixture('train'),p=flattened(f.profile)[0];try{
      const root=f.parFor(p.key).closest('['+ROOT+']'),physical=root.closest('article[data-sf-occurrence-id]');assert(physical);
      if(kind==='occurrence')physical.setAttribute('data-sf-occurrence-id','f'.repeat(64));
      else root.setAttribute('data-external-owner','foreign');
      const before=f.d.body.innerHTML;f.dispatch(p,0);
      assert.deepEqual(f.active(),[]);assert(f.invalid());assert.equal(f.d.body.innerHTML,before);
    }finally{f.close();}
  }
  const f=fixture('train'),p=flattened(f.profile)[0];try{
    const root=f.parFor(p.key).closest('['+ROOT+']'),physical=root.closest('article[data-sf-occurrence-id]');
    root.hidden=true;physical.hidden=true;assert.equal(f.handle.refresh(),true);root.hidden=false;physical.hidden=false;
    f.dispatch(p,0);assert(f.active().length);assert.equal(f.invalid(),null);
  }finally{f.close();}
});
test('review regression: real compiler accepts root key length 160 with 163-character derived paragraph keys and rejects root 161',()=>{
  assert.equal(samples.long_key.profile.sentences[0].key.length,160);
  assert.equal(samples.long_key.profile.sentences[0].paragraphs[0].key.length,163);
  assert.equal(samples.invalid_long_key,undefined);
  const f=fixture('long_key');try{
    const p=flattened(f.profile)[0];f.dispatch(p,0);assert(f.active().length);assert.equal(f.invalid(),null);
  }finally{f.close();}
});
test('numeric character-reference CR and literal CRLF preserve HTML5 text and bilingual interaction',()=>{
  for(const name of ['numeric_cr','literal_crlf']){
    const f=fixture(name),old=fixture(name,{legacy:true,html:samples[name].source});try{
      const p=flattened(f.profile)[0],before=f.d.body.innerHTML;
      assert.equal(f.parFor(p.key).textContent,name==='numeric_cr'?'A\rB':'A\nB');
      f.dispatch(p,0);old.dispatch(p,0);assert.deepEqual(f.active(),old.active());assert.equal(f.active().length,2);
      f.fire('keydown',f.d.body,{key:'Escape'});assert.deepEqual(f.active(),[]);assert.equal(f.d.body.innerHTML,before);
      assert.equal(f.invalid(),null);
    }finally{f.close();old.close();}
  }
});
