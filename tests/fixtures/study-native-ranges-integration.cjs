'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const input=JSON.parse(fs.readFileSync(0,'utf8')),pin='be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93';
const adapt=input.adapter?new Function(input.adapter+';return adaptNativeGroupRanges;')():(code=>code),next=adapt(input.fixture,pin),w=new JSDOM('<div id="outside"><p id="root" class="card-chunk" data-chunk-ids="1">A😀<b id="nested" class="card-chunk" data-chunk-ids="2">B</b></p></div>',{runScripts:'outside-only'}).window;
try{
 const api=source=>w.eval('(function(){'+source+';return {view:textView,ranges:ranges,graph:chunkGraph};})()'),old=api(input.fixture),current=api(next),root=w.document.getElementById('root'),visited=[],result=current.ranges(current.view(root),el=>{visited.push(el.id);return el.classList.contains('card-chunk')});
 assert.deepEqual(visited,['root','nested','root'],'eligible predicates must never visit ancestors outside the original view root');
 assert.equal(current.view(root).root,root);const compact=entries=>Array.from(entries,item=>[item.el.id,Array.from(item.ranges,range=>Array.from(range))]);
 assert.deepEqual(compact(result),compact(old.ranges(old.view(root),el=>el.classList.contains('card-chunk')&&root.contains(el))));
 assert.equal(adapt(input.fixture,'unknown'),input.fixture);
 for(const marker of ['return { text: el.textContent, nodes: nodes };','el && el !== part.node.ownerDocument','paragraph.contains(el)','en.contains(el)'])assert.throws(()=>adapt(input.fixture.replace(marker,'changed'),pin),/ranges boundary differs/);
 assert.throws(()=>adapt(input.fixture+input.fixture,pin),/ranges boundary differs/);assert.throws(()=>adapt(next,pin),/ranges boundary differs/);
 process.stdout.write(JSON.stringify({passed:true}));
}finally{w.close()}
