"""Exact retained-history PRE fragmentation contracts; no producer or browser."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_JS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const crypto=require('node:crypto'),zlib=require('node:zlib'),{JSDOM}=require('jsdom');
const base=path.resolve('tests/fixtures/compiled-history-text-split-v1');
const manifest=JSON.parse(fs.readFileSync(path.join(base,'manifest.json')));
const sha=raw=>crypto.createHash('sha256').update(raw).digest('hex');
function read(name){
 const spec=manifest.files[name],stored=fs.readFileSync(path.join(base,spec.path));
 assert.equal(sha(stored),spec.stored_sha256);assert.equal(stored.length,spec.stored_bytes);
 const raw=spec.compression==='gzip'?zlib.gunzipSync(stored):stored;
 assert.equal(sha(raw),spec.sha256);assert.equal(raw.length,spec.bytes);return raw.toString('utf8');
}
const html=read('delivery.html'),profileRaw=read('profile.json'),decoder=read('original-decoder.js');
const runtime=fs.readFileSync('anki_pipeline/compiled/card-runtime.js','utf8');
function fixture(){
 const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://card.invalid/'}),w=dom.window,d=w.document;
 w.eval(decoder);w.eval(runtime);let current=true;
 const profile=JSON.parse(profileRaw),handle=w.AnkiCompiledCardRuntime.install(d,profile,{isCurrent:()=>current});
 const at=(root,indices)=>indices.reduce((node,index)=>node.childNodes[index],root);
 return{w,d,profile,handle,setCurrent(value){current=value;},close(){handle.dispose();w.close();},slot(index){
  const spec=profile.historySlots[index],part=spec.parts[0];
  assert.equal(part.sha256,manifest.slots[index].raw_part_sha256);
  const owner=at(d.querySelectorAll(spec.region.selector)[spec.region.ordinal],spec.region.ownerPath);
  const anchor=at(owner,spec.anchorPath),script=at(owner,spec.manifestPath),template=d.createElement('template');
  template.innerHTML=read('part-'+index+'.html');w.AnkiSlimDecode(template.content);
  const request={manifest:script,anchor,holder:owner,detail:owner,kind:'disclosure',panel:null,value:JSON.parse(spec.manifestText),at:0};
  return{spec,part,owner,anchor,script,template,request,append(){
   assert.equal(handle.authorizeHistoryPart(request,part,template.content),true);
   owner.insertBefore(template.content,anchor);request.at=1;script.dataset.asLoadedParts='1';script.dataset.asState='ready';
   assert.equal(handle.refresh(),true);assert.equal(handle.stats().invalid,null);
  }};
 }};
}
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledHistoryTextTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(
            [shutil.which('node'), '-e', FIXTURE_JS + source], cwd=ROOT,
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_teem_long_pre_split_preserves_exact_history(self):
        self.node(r"""
const f=fixture();
try{
 let last;
 for(const index of [0,1]){
  const slot=f.slot(index),pre=slot.template.content.querySelector('pre'),text=pre.textContent;
  assert.equal(pre.childNodes.length,1);assert.equal(pre.firstChild.nodeType,3);
  assert.equal(text.length,index===0?30220:79852);
  const attrs=Array.from(pre.attributes,a=>[a.name,a.value]);
  pre.firstChild.splitText(index===0?1024:65536);
  assert.equal(pre.childNodes.length,2);assert.equal(pre.textContent,text);
  f.setCurrent(false);assert.equal(f.handle.authorizeHistoryPart(slot.request,slot.part,slot.template.content),false);
  assert.equal(pre.childNodes.length,2);f.setCurrent(true);
  slot.append();assert.equal(pre.childNodes.length,1);assert.equal(pre.firstChild.data,text);
  assert.deepEqual(Array.from(pre.attributes,a=>[a.name,a.value]),attrs);
  assert.equal(f.handle.assertHistorySlots(),true);
  last=slot;
 }
 assert.throws(()=>f.handle.authorizeHistoryPart(last.request,last.part,f.d.createDocumentFragment()),/history part scope/);
}finally{f.close();}
""")

    def test_changed_or_nontext_pre_graphs_stay_rejected(self):
        self.node(r"""
for(const mode of ['text','comment','element','attribute']){
 const f=fixture();
 try{
  const slot=f.slot(1),pre=slot.template.content.querySelector('pre');pre.firstChild.splitText(65536);
  if(mode==='text')pre.lastChild.data=(pre.lastChild.data[0]==='x'?'y':'x')+pre.lastChild.data.slice(1);
  if(mode==='comment')pre.insertBefore(f.d.createComment('not text'),pre.lastChild);
  if(mode==='element'){const span=f.d.createElement('span');span.textContent=pre.lastChild.data;pre.lastChild.replaceWith(span);}
  if(mode==='attribute')pre.setAttribute('style','white-space:normal');
  const before=pre.outerHTML,nodes=Array.from(pre.childNodes),ownerBefore=slot.owner.innerHTML;
  assert.throws(()=>slot.append(),/history part graph/);
  assert.equal(pre.outerHTML,before);assert.deepEqual(Array.from(pre.childNodes),nodes);
  assert.equal(slot.owner.innerHTML,ownerBefore);assert.equal(slot.script.hasAttribute('data-as-loaded-parts'),false);
 }finally{f.close();}
}
""")

    def test_nonpre_text_fragmentation_stays_strict(self):
        self.node(r"""
const f=fixture();
try{
 const slot=f.slot(1),paragraph=slot.template.content.querySelector('p.sf-reason');
 assert.equal(paragraph.childNodes.length,1);paragraph.firstChild.splitText(1);
 assert.equal(paragraph.childNodes.length,2);
 assert.throws(()=>slot.append(),/history part graph/);
 assert.equal(paragraph.childNodes.length,2);
}finally{f.close();}
""")


if __name__ == '__main__':
    unittest.main()
