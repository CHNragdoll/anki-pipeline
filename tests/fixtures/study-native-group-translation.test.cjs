'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const baseline=fs.readFileSync(process.env.NATIVE_SOURCE,'utf8');
const adapterPath=process.env.GROUP_ADAPTER;
const adapt=adapterPath && fs.existsSync(adapterPath) ? require('node:vm').runInNewContext(fs.readFileSync(adapterPath,'utf8')+'\nadaptNativeGroupTranslationText;') : value=>value;
const pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const source=adapt(baseline,pin);
const physicalStart=source.indexOf('  function physicalNativeIndex(doc) {');
assert.ok(physicalStart>0);
const library=source.slice(0,source.length);
function fixture(t){const dom=new JSDOM('<!doctype html><body></body>',{runScripts:'outside-only',url:'https://example.test/card'});t.after(()=>dom.window.close());const w=dom.window;return{w,index:w.eval('(function(){'+library+';return physicalNativeIndex;})()')};}
const compactIdentity=(suffix='a')=>'x|2026-01|p%3Ab-1-1|'+suffix.repeat(43)+'|'+'b'.repeat(43)+'|x';
function addRow(doc,translation,compact=false,identity=compactIdentity()){
  const list=doc.createElement('ol'),row=doc.createElement('li'),en=doc.createElement('div'),zh=doc.createElement('div'),origin=doc.createElement('div'),link=doc.createElement('a');
  list.className='examples';row.className=compact?'_r28':'example-card';en.className=compact?'_r31':'example-text';zh.className=compact?'_r34':'example-translation';origin.className=compact?'_r36':'example-source';link.className='sentence-jump';
  en.textContent='  English 😀\ud800 \t';origin.textContent=' \n原文 source\t ';zh.innerHTML=translation;link.setAttribute('data-rb-j',identity);row.append(en,zh,origin,link);list.append(row);doc.body.append(list);return{row,en,zh,origin,link};
}
function oldText(zh){const copy=zh.cloneNode(true);copy.querySelectorAll('.translation-label,.translate-tag,._r35').forEach(el=>el.remove());return copy.textContent.trim();}
function entries(map){return Array.from(map,([key,values])=>[key,Array.from(values)]);}
function expected(row){return JSON.stringify([row.origin.textContent.trim(),row.en.textContent,oldText(row.zh)]);}

const cases=[
  ['plain whitespace and UTF16',' \n\t中文 😀 \ud800 e\u0301\u00a0正文\t\n '],
  ['mixed depth, overlapping and all label aliases',' 前<span>层<b class="translation-label">删<strong class="translate-tag">嵌套</strong>尾</b>后</span><i class="_r35">另删</i><span class="translate-tag">最后</span> 留 '],
  ['empty and adjacent labels','a<span class="translation-label"></span><span class="_r35">B</span><span class="translate-tag">C</span>d'],
  ['comments are not text offsets','首<!-- not text --><span>中<!-- ignored --><b class="translate-tag">删😀</b>尾</span><!--x-->末'],
  ['script and style text are retained unless inside a label',' A<script>const x="<tag>";\n//文本</script><style>.x{content:"中文"}</style><b class="translation-label"><script>remove()</script><style>erase{}</style></b>Z '],
  ['template content is never entered','A<template><span class="translation-label">inert</span>不可见</template><span>中</span><i class="translate-tag">删</i>Z'],
  ['nested nonlabel structure and root class does not exclude root',' 根<span>外<i class="translation-label">删</i>保</span>留 '],
  ['entities and exact white space','&nbsp; A&amp;B&#x1F600;\r\n<span class="translate-tag"> 翻译 </span>\t&#x2003;中 &#10;尾&nbsp;']
];
for(const [name,html]of cases)test('clone-equivalent index key: '+name,t=>{
  const {w,index}=fixture(t),item=addRow(w.document,html,name.includes('entities'));
  if(name.includes('root class'))item.zh.classList.add('translation-label');
  const before=item.zh.outerHTML,identityBefore=item.zh.firstChild,want=expected(item),out=entries(index(w.document));
  assert.equal(out.length,1);assert.equal(out[0][0],want);assert.equal(item.zh.outerHTML,before);assert.equal(item.zh.firstChild,identityBefore);
});

test('XML CDATA, processing instructions, comments and nested labels match clone text exactly',t=>{
  const {w,index}=fixture(t),doc=new w.DOMParser().parseFromString('<root><li class="example-card"><div class="example-text">EN</div><div class="example-translation"> A<![CDATA[😀前]]><?pi ignored?><!--ignored--><span><![CDATA[中]]><i class="translation-label"><![CDATA[删除]]><b class="_r35">重叠</b></i><![CDATA[尾]]></span> Z</div><div class="example-source"> source </div><a data-rb-j="'+compactIdentity()+'"/></li></root>','application/xml');
  assert.equal(doc.querySelector('parsererror'),null);
  const zh=doc.querySelector('.example-translation'),before=zh.outerHTML,want=oldText(zh),out=entries(index(doc));
  assert.equal(out[0][0],JSON.stringify(['source','EN',want]));assert.equal(want,'A😀前中尾 Z');assert.equal(zh.outerHTML,before);
});

test('the actual index reads all rows with zero clones or source mutations',t=>{
  const {w,index}=fixture(t);
  const items=cases.map(([name,html],i)=>addRow(w.document,html,i%2===0));
  const expectedKeys=items.map(expected),before=w.document.body.innerHTML;
  let clones=0;const clone=w.Node.prototype.cloneNode;
  w.Node.prototype.cloneNode=function(...args){clones++;return Reflect.apply(clone,this,args);};
  const observed=new w.MutationObserver(()=>{});observed.observe(w.document.body,{subtree:true,childList:true,attributes:true,characterData:true});
  const out=entries(index(w.document));
  assert.deepEqual(out.map(item=>item[0]),expectedKeys);assert.equal(w.document.body.innerHTML,before);assert.equal(observed.takeRecords().length,0);
  assert.equal(clones,0,'clone-free candidate must not clone each translation subtree');
  observed.disconnect();
});

test('same keys still deduplicate exact identities and preserve malformed-link rejection',t=>{
  const {w,index}=fixture(t);addRow(w.document,'<b class="translate-tag">翻译</b>中文',false,compactIdentity('a'));addRow(w.document,'中文',true,compactIdentity('a'));addRow(w.document,'中文',false,compactIdentity('c'));addRow(w.document,'中文',false,'malformed');
  const out=entries(index(w.document));assert.equal(out.length,1);assert.equal(out[0][1].length,2);
  assert.deepEqual(out[0][1],[JSON.stringify(['kaoyan:2026-01:p:b-1-1','a'.repeat(43),'b'.repeat(43)]),JSON.stringify(['kaoyan:2026-01:p:b-1-1','c'.repeat(43),'b'.repeat(43)])]);
});

test('URL identity checks and non-trimmed English remain exact',t=>{
  const {w,index}=fixture(t),item=addRow(w.document,'<b class="translation-label">译</b> \t中文\n');
  item.link.removeAttribute('data-rb-j');item.link.href='https://example.test/paper?anki-codex-sentence=paper%3A1&anki-codex-hash='+'a'.repeat(64)+'&anki-codex-review='+'b'.repeat(64);
  const out=entries(index(w.document));assert.equal(out[0][0],expected(item));assert.equal(JSON.parse(out[0][0])[1],'  English 😀\ud800 \t');assert.equal(out[0][1][0],JSON.stringify(['paper:1','a'.repeat(64),'b'.repeat(64)]));
  item.link.href='https://example.test/paper?anki-codex-sentence=paper%3A1&anki-codex-hash=bad';assert.deepEqual(entries(index(w.document)),[]);
});

const crypto=require('node:crypto');
const frozenIndexPin='2f4c541cca84f74e477d7538d04f32d58b28c95a1fc9acb4f465e7caa688be7f';
for(const kind of ['native','prepared'])test('audited '+kind+' wrapper preserves all bytes outside the group library',()=>{
  const prefix='// '+kind+' prefix\n',suffix='\n// unchanged suffix';
  const result=adapt(prefix+baseline+suffix,pin);
  assert.equal(result.slice(0,prefix.length),prefix);assert.equal(result.slice(-suffix.length),suffix);
  assert.equal(crypto.createHash('sha256').update(result.slice(prefix.length,-suffix.length)).digest('hex'),frozenIndexPin);
});
test('unapproved native pins do not adapt arbitrary inputs',()=>{
  for(const unknown of ['',pin.toUpperCase(),'0'.repeat(64),'6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'])assert.equal(adapt('unrelated',unknown),'unrelated');
});
test('changed or duplicate boundary and already-adapted input fail closed',()=>{
  for(const bad of [baseline.replace('var translation = zh.cloneNode(true);','var translation = zh.cloneNode(false);'),baseline.replace('translation.textContent.trim()','translation.textContent'),baseline+baseline,source])assert.throws(()=>adapt(bad,pin),/Audited native group translation boundary differs/);
});
