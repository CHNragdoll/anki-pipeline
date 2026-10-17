"""Exact residual ownership disclosures retain the original history graph gate."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_JS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),{JSDOM}=require('jsdom');
const runtime=fs.readFileSync('anki_pipeline/compiled/card-runtime.js','utf8'),sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const raw='<pre>完整原始审核\n保留😀</pre><details class="sf-archived-example"><summary>原审核</summary><div class="sf-sentence-pair example-card"><p class="sf-en"><span class="card-chunk" data-chunk-side="en" data-chunk-ids="0">original</span> sentence</p><p class="sf-zh">完整原句</p></div></details>';
const attrs=n=>Array.from(n.attributes,a=>[a.name,a.value]);
const graph=n=>n.nodeType===1?{type:1,name:n.tagName,namespace:n.namespaceURI,attrs:attrs(n),children:Array.from(n.childNodes,graph)}:{type:n.nodeType,text:n.data};
function fixture(partText=raw){
 const pin=sha(partText),part={src:'_as_'+pin.slice(0,24)+'.js',sha256:pin,count:1},value={schema:'anki-slim-segments.v1',parts:[part],total:1};
 const dom=new JSDOM('<section class="examples-section"><ol><li class="example-card kept"><a class="sentence-jump" data-rb-j="source" data-latex-url="latex" data-full-paper-url="full"></a><div class="sf-native-ownership-history" data-native-ownership-history="residual-v1"><details class="residual-owner-history" data-history-sha256="'+ '2'.repeat(64)+'"><summary>本句完整词组转归依据</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json">'+JSON.stringify(value)+'</script></div></details></div></li></ol></section>',{runScripts:'outside-only',url:'https://card.invalid/'}),w=dom.window,d=w.document;
 const region=d.querySelector('.examples-section'),row=d.querySelector('li'),jump=row.firstChild,container=row.lastChild,owner=container.firstChild,anchor=owner.lastChild,manifest=anchor.firstChild,t=d.createElement('template');t.innerHTML=partText;
 const bindings={};for(const n of ['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'])bindings[n]='a'.repeat(64);
 const pairs=Array.from(t.content.querySelectorAll('.sf-sentence-pair'),()=>({excluded:true})),spec={schema:'study-compiled-excluded-history-slot.v1',sourceArtifactSha256:bindings.sourceArtifactSha256,region:{selector:'.examples-section',ordinal:0,total:1,ownerPath:[0,0,1,0]},ownerAttrs:attrs(owner),ownerTree:graph(owner),nativeSource:['source','latex','full'],anchorPath:[1],manifestPath:[1,0],manifestText:manifest.textContent,parts:[{...part,tree:Array.from(t.content.childNodes,graph),evidence:[],consumerEvidence:{fine_example_roots:[],bank_containers:[],group_panels:[],group_physical_native_rows:[],residual_key_targets:[],projection_pair_roots:pairs}}]};
 const profile={schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',residual_mode:'original-listener',bindings,nodeBindings:[],projectionWrappers:[],residualWrappers:[],readerLinks:[],panels:[],groups:[],bankRecords:[],historySlots:[spec]};
 let current=true,handle,invalidations=0;w.eval(runtime);
 const request={manifest,anchor,holder:owner,detail:owner,kind:'disclosure',panel:null,value,at:0};
 return{w,d,region,row,jump,container,owner,anchor,manifest,t,part,spec,profile,request,get handle(){return handle;},get invalidations(){return invalidations;},setCurrent(v){current=v;},install(){return handle=w.AnkiCompiledCardRuntime.install(d,profile,{isCurrent:()=>current,onInvalid(){invalidations++;}});},load(){assert.equal(handle.authorizeHistoryPart(request,part,t.content),true);owner.insertBefore(t.content,anchor);request.at=1;manifest.dataset.asLoadedParts='1';manifest.dataset.asState='ready';assert.equal(handle.refresh(),true);},close(){handle?.dispose();w.close();}};
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledResidualHistoryTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(
            [shutil.which('node'), '-e', FIXTURE_JS + source], cwd=ROOT,
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_residual_owner_and_closed_details_pair_are_authorized(self):
        self.node(r"""
(async()=>{const f=fixture();try{f.install();f.owner.open=true;f.load();const archive=f.owner.querySelector('details.sf-archived-example');assert.ok(archive);assert.equal(archive.open,false);archive.open=true;await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.handle.assertHistorySlots(),true);assert.equal(f.invalidations,0);assert.equal(f.owner.querySelector('.sf-zh').textContent,'完整原句');}finally{f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_owner_chain_region_source_and_closed_install_are_exact(self):
        self.node(r"""
for(const change of [
 f=>f.owner.open=true,
 f=>f.owner.className='residual-owner-history extra',
 f=>f.container.className='sf-native-ownership-history extra',
 f=>f.container.dataset.nativeOwnershipHistory='other',
 f=>f.container.removeAttribute('data-native-ownership-history'),
 f=>{const wrapper=f.d.createElement('div');f.owner.replaceWith(wrapper);wrapper.appendChild(f.owner);},
 f=>{const section=f.d.createElement('section');section.className=f.container.className;section.dataset.nativeOwnershipHistory='residual-v1';f.container.replaceWith(section);section.appendChild(f.owner);},
 f=>f.row.className='_r28',
 f=>f.region.className='other',
 f=>f.jump.className='other',
 f=>f.jump.dataset.rbJ='wrong source',
 f=>f.spec.sourceArtifactSha256='0'.repeat(64)
]){const f=fixture();try{change(f);const before=f.d.body.innerHTML;assert.throws(()=>f.install(),/Compiled card invalid/);assert.equal(f.d.body.innerHTML,before);assert.equal(f.invalidations,0);}finally{f.close();}}
""")

    def test_residual_pair_exception_does_not_widen_other_graphs_or_owners(self):
        self.node(r"""
for(const text of [
 raw.replace('<details class="sf-archived-example"','<details open class="sf-archived-example"'),
 raw.replace('class="sf-archived-example"','class="sf-archived-example extra"'),
 raw.replace('class="sf-sentence-pair example-card"','class="sf-sentence-pair example-card extra"'),
 '<div>'+raw+'</div>',
 raw.replace('<details class="sf-archived-example"','<article class="sf-archived-example"').replace('</details>','</article>'),
 raw.replace('<div class="sf-sentence-pair example-card"','<section class="sf-sentence-pair example-card"').replace('</div></details>','</section></details>'),
 '<li class="example-card">forbidden physical row</li>',
 '<div class="sf-panel">live semantic panel</div>'
]){const f=fixture(text);try{f.install();assert.throws(()=>f.load(),/history part/);assert.equal(f.invalidations,1);}finally{f.close();}}
const f=fixture();try{f.owner.className='sf-ownership-history';f.spec.ownerAttrs=attrs(f.owner);f.spec.ownerTree=graph(f.owner);f.install();assert.throws(()=>f.load(),/history part scope/);}finally{f.close();}
""")

    def test_source_chain_and_fragment_tamper_stale_and_dispose_are_rejected(self):
        self.node(r"""
(async()=>{for(const change of [f=>f.container.dataset.nativeOwnershipHistory='other',f=>f.jump.dataset.fullPaperUrl='foreign',f=>f.owner.parentNode.appendChild(f.d.createElement('div')).appendChild(f.owner)]){const f=fixture();try{f.install();change(f);await tick();assert.equal(f.invalidations,1);assert.throws(()=>f.load(),/Compiled card invalid/);}finally{f.close();}}
for(const change of [f=>f.t.content.querySelector('.sf-zh').firstChild.data+='forged',f=>f.t.content.querySelector('.sf-sentence-pair').setAttribute('style','display:none'),f=>f.spec.parts[0].consumerEvidence.projection_pair_roots[0].excluded=false]){const f=fixture();try{if(change.toString().includes('consumerEvidence')){change(f);assert.throws(()=>f.install(),/history part/);}else{f.install();change(f);assert.throws(()=>f.load(),/history part graph/);}}finally{f.close();}}
const f=fixture();try{f.install();f.setCurrent(false);assert.equal(f.handle.authorizeHistoryPart(f.request,f.part,f.t.content),false);f.setCurrent(true);f.handle.dispose();assert.equal(f.handle.authorizeHistoryPart(f.request,f.part,f.t.content),false);}finally{f.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


if __name__ == '__main__':
    unittest.main()
