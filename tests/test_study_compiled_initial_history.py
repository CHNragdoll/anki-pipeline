"""Deferred initial AF writes use the existing authenticated history capability."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_JS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto');
const {JSDOM}=require('jsdom');
const runtime=fs.readFileSync('anki_pipeline/compiled/card-runtime.js','utf8');
const sha=value=>crypto.createHash('sha256').update(value).digest('hex');
const full='完整审核原文\n中文😀 e\u0301 <source> & '+ 'long '.repeat(14000);
const pin=sha(full),media='_af_'+sha('original inert AF').slice(0,24)+'.js';
const attrs=node=>Array.from(node.attributes,a=>[a.name,a.value]);
const pathTo=(root,node)=>node===root?[]:[...pathTo(root,node.parentNode),Array.from(node.parentNode.childNodes).indexOf(node)];
function fixture(count=1,mutate){
 const html='<section class="sf-report"><article class="sf-example" data-study-compiled-key="root">'+
  Array.from({length:count},(_,n)=>'<details><summary>审核 '+n+'</summary><pre data-native-history-media="'+media+'" data-native-history-sha="'+pin+'">原占位 '+n+'\n</pre></details>').join('')+'</article></section>';
 const dom=new JSDOM(html,{runScripts:'outside-only',url:'https://card.invalid/'}),w=dom.window,d=w.document;
 w.eval(runtime);const root=d.querySelector('article'),pres=Array.from(root.querySelectorAll('pre'));
 const bindings={};for(const name of ['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'])bindings[name]='a'.repeat(64);
 const profile={schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',residual_mode:'original-listener',bindings,
  nodeBindings:[{key:'root',rootKey:'root',region:{selector:'.sf-report',ordinal:0,total:1,rootPath:[0]},relativePath:[],requiredAttrs:attrs(root),roles:['original-example'],tag:'ARTICLE',namespace:root.namespaceURI,logicalRoot:{kind:'occurrence',id:null},exactText:root.textContent}],
  projectionWrappers:[],residualWrappers:[],panels:[],groups:[],bankRecords:[],readerLinks:[],historySlots:[],
  initialHistorySlots:pres.map(pre=>({rootKey:'root',relativePath:pathTo(root,pre),ownerPath:pathTo(root,pre.parentNode),requiredAttrs:attrs(pre),ownerAttrs:attrs(pre.parentNode),placeholder:pre.textContent,media,sha256:pin,resourceSha256:sha('original inert AF')})),initialHistoryText:{[pin]:full}};
 let current=true,invalidations=0,handle;
 const f={w,d,root,pres,profile,install(){return handle=w.AnkiCompiledCardRuntime.install(d,profile,{isCurrent:()=>current,onInvalid(){invalidations++;}});},get handle(){return handle;},get invalidations(){return invalidations;},setCurrent(value){current=value;},close(){handle?.dispose();w.close();},write(pre=pres[0],text=full,result={ready:true,failed:false}){const allowed=handle.authorizeHistoryText(pre,text,result);if(allowed){pre.textContent=text;if(result.ready)pre.dataset.nativeHistoryReady='true';}return allowed;}};
 if(mutate)mutate(f);return f;
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledInitialHistoryTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(
            [shutil.which('node'), '-e', FIXTURE_JS + source], cwd=ROOT,
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_shared_text_is_authorized_without_changing_placeholder_baseline(self):
        self.node(r"""
(async()=>{const f=fixture(2);try{
 const original=f.root.textContent;f.install();assert.equal(f.pres[0].dataset.nativeHistoryReady,undefined);
 // A request may finish after the user has closed its owner again.
 f.pres[0].parentNode.open=true;f.pres[0].parentNode.open=false;
 assert.equal(f.write(f.pres[0]),true);assert.equal(f.handle.refresh(),true);
 assert.equal(f.write(f.pres[1]),true);await tick();
 assert.notEqual(f.root.textContent,original);assert.equal(f.handle.refresh(),true);
 assert.equal(f.handle.assertHistorySlots(),true);assert.equal(f.invalidations,0);
 assert.equal(f.profile.nodeBindings[0].exactText,original);
 assert.equal(Object.keys(f.profile.initialHistoryText).length,1);
}finally{f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_pair_bank_paths_and_exact_original_nodes_are_required_before_install(self):
        self.node(r"""
const cases=[
 f=>delete f.profile.initialHistoryText,
 f=>delete f.profile.initialHistorySlots,
 f=>f.profile.initialHistoryText=[],
 f=>f.profile.initialHistoryText[sha('unused')]='unused',
 f=>delete f.profile.initialHistoryText[pin],
 f=>f.profile.initialHistoryText[pin]=4,
 f=>f.profile.initialHistorySlots.push(f.profile.initialHistorySlots[0]),
 f=>f.profile.initialHistorySlots[0].relativePath=[-1],
 f=>f.profile.initialHistorySlots[0].ownerPath=[],
 f=>f.profile.initialHistorySlots[0].rootKey='absent',
 f=>f.profile.initialHistorySlots[0].placeholder+='changed',
 f=>f.profile.initialHistorySlots[0].media='_af_unknown.js',
 f=>f.profile.initialHistorySlots[0].resourceSha256='not a pin',
 f=>f.profile.initialHistorySlots[0].requiredAttrs.push(['data-forged','yes']),
 f=>f.profile.initialHistorySlots[0].ownerAttrs.push(['open','']),
 f=>f.pres[0].parentNode.open=true,
 f=>f.pres[0].parentNode.setAttribute('is','custom-details'),
 f=>{f.pres[0].parentNode.className='sf-inline-history';f.profile.initialHistorySlots[0].ownerAttrs=attrs(f.pres[0].parentNode);},
 f=>f.pres[0].setAttribute('is','custom-pre'),
 f=>f.pres[0].dataset.nativeHistoryReady='true',
 f=>f.pres[0].appendChild(f.d.createComment('not text')),
 f=>{const span=f.d.createElement('span');span.textContent=f.pres[0].textContent;f.pres[0].replaceChildren(span);},
 f=>{const div=f.d.createElement('div');f.pres[0].replaceWith(div);div.appendChild(f.pres[0]);}
];
for(const change of cases){const f=fixture(1,change);try{const before=f.root.outerHTML;assert.throws(()=>f.install(),/Compiled card invalid/);assert.equal(f.root.outerHTML,before);assert.equal(f.invalidations,0);}finally{f.close();}}
""")

    def test_no_as_slots_still_observe_initial_af_unauthorized_writes(self):
        self.node(r"""
(async()=>{for(const mutate of [
 f=>f.pres[0].textContent=full,
 f=>f.pres[0].dataset.nativeHistoryReady='true',
 f=>f.pres[0].setAttribute('data-other','forged'),
 f=>f.pres[0].removeAttribute('data-native-history-sha'),
 f=>f.pres[0].parentNode.setAttribute('class','unknown'),
 f=>f.pres[0].parentNode.appendChild(f.d.createElement('span')),
 f=>f.root.appendChild(f.pres[0]),
 f=>f.pres[0].replaceWith(f.pres[0].cloneNode(true))
]){const f=fixture();try{f.install();mutate(f);await tick();assert.equal(f.invalidations,1);assert.match(f.handle.stats().invalid,/Compiled card invalid/);assert.throws(()=>f.handle.refresh(),/Compiled card invalid/);}finally{f.close();}}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_text_failure_retry_current_and_dispose_guards_preserve_original_flow(self):
        self.node(r"""
(async()=>{const f=fixture();try{
 f.install();const pre=f.pres[0],before=pre.outerHTML;
 f.setCurrent(false);assert.equal(f.write(),false);assert.equal(pre.outerHTML,before);f.setCurrent(true);
 assert.equal(f.write(pre,'证据载入失败：测试',{ready:false,failed:true}),true);assert.equal(f.handle.refresh(),true);
 assert.equal(f.write(),true);await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.invalidations,0);
 pre.firstChild.splitText(65536);await tick();assert.equal(f.handle.refresh(),true);
 const after=pre.outerHTML;f.handle.dispose();assert.equal(f.write(),false);assert.equal(pre.outerHTML,after);
}finally{f.close();}
for(const [text,result]of [[full+'x',{ready:true,failed:false}],['forged failure',{ready:false,failed:true}],[full,{ready:true,failed:true}]]){const g=fixture();try{g.install();const before=g.root.outerHTML;assert.throws(()=>g.write(g.pres[0],text,result),/uncovered history evidence write/);assert.equal(g.root.outerHTML,before);assert.equal(g.invalidations,1);}finally{g.close();}}
})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_authorized_text_still_rejects_new_element_or_source_attribute(self):
        self.node(r"""
(async()=>{for(const mutate of [
 f=>{const span=f.d.createElement('span');span.textContent=f.pres[0].textContent;f.pres[0].replaceChildren(span);},
 f=>f.pres[0].dataset.nativeHistoryMedia='_af_'+ '0'.repeat(24)+'.js',
 f=>f.pres[0].parentNode.insertBefore(f.d.createTextNode('extra'),f.pres[0])
]){const f=fixture();try{f.install();assert.equal(f.write(),true);assert.equal(f.handle.refresh(),true);mutate(f);await tick();assert.equal(f.invalidations,1);}finally{f.close();}}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_old_profile_without_new_tables_remains_compatible(self):
        self.node(r"""
const f=fixture(0);try{delete f.profile.initialHistorySlots;delete f.profile.initialHistoryText;f.install();assert.equal(f.handle.refresh(),true);assert.equal(f.handle.assertHistorySlots(),true);assert.equal(f.handle.stats().invalid,null);}finally{f.close();}
""")

    def test_as_disclosure_and_initial_af_share_the_existing_capability_flow(self):
        self.node(r"""
(async()=>{const f=fixture();try{
 const region=f.d.querySelector('.sf-report'),owner=f.d.createElement('details');
 owner.className='sf-inline-history';owner.innerHTML='<summary>原AS审核</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json"></script></div>';region.appendChild(owner);
 const anchor=owner.lastChild,manifest=anchor.firstChild,partPin=sha('pinned AS text'),part={src:'_as_'+partPin.slice(0,24)+'.js',sha256:partPin,count:1};
 manifest.textContent=JSON.stringify({schema:'anki-slim-segments.v1',total:1,parts:[part]});
 const graph=node=>node.nodeType===1?{type:1,name:node.tagName,namespace:node.namespaceURI,attrs:attrs(node),children:Array.from(node.childNodes,graph)}:{type:node.nodeType,text:node.data};
 const template=f.d.createElement('template');template.innerHTML='<p>原AS排除片段</p>';
 f.profile.historySlots=[{schema:'study-compiled-excluded-history-slot.v1',sourceArtifactSha256:f.profile.bindings.sourceArtifactSha256,region:{selector:'.sf-report',ordinal:0,total:1,ownerPath:[1]},ownerAttrs:attrs(owner),ownerTree:graph(owner),nativeSource:null,anchorPath:[1],manifestPath:[1,0],manifestText:manifest.textContent,parts:[{...part,tree:Array.from(template.content.childNodes,graph),evidence:[],consumerEvidence:{fine_example_roots:[],bank_containers:[],group_panels:[],group_physical_native_rows:[],residual_key_targets:[],projection_pair_roots:[]}}]}];
 f.install();assert.equal(f.write(),true);assert.equal(f.handle.refresh(),true);
 const slot={manifest,anchor,holder:owner,detail:owner,kind:'disclosure',panel:null,value:JSON.parse(manifest.textContent),at:0};
 assert.equal(f.handle.authorizeHistoryPart(slot,part,template.content),true);owner.insertBefore(template.content,anchor);slot.at=1;manifest.dataset.asLoadedParts='1';manifest.dataset.asState='ready';
 await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.handle.assertHistorySlots(),true);assert.equal(f.invalidations,0);
}finally{f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
""")


if __name__ == '__main__':
    unittest.main()
