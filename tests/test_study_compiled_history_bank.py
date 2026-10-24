"""Shared AF text-bank references retain the original AS history capabilities."""
import shutil
import subprocess
import unittest

from tests.test_study_compiled_initial_history import FIXTURE_JS, ROOT


BANK_FIXTURE_JS = FIXTURE_JS + r"""
const graph=node=>node.nodeType===1?{type:1,name:node.tagName,namespace:node.namespaceURI,attrs:attrs(node),children:Array.from(node.childNodes,graph)}:{type:node.nodeType,text:node.data};
function addAS(f,legacy=false){
 const region=f.d.querySelector('.sf-report'),owner=f.d.createElement('details');
 owner.className='sf-inline-history';owner.innerHTML='<summary>原AS审核</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json"></script></div>';region.appendChild(owner);
 const anchor=owner.lastChild,manifest=anchor.firstChild,partPin=sha('pinned AS '+region.children.length),part={src:'_as_'+partPin.slice(0,24)+'.js',sha256:partPin,count:1};
 manifest.textContent=JSON.stringify({schema:'anki-slim-segments.v1',total:1,parts:[part]});
 const template=f.d.createElement('template');template.innerHTML='<details><summary>原AF完整证据</summary><pre data-native-history-media="'+media+'" data-native-history-sha="'+pin+'">原AS占位</pre></details>';
 const pre=template.content.querySelector('pre'),evidence={path:[0,1],media,sha256:pin,resourceSha256:sha('original inert AF'),...(legacy?{text:full}:{textKey:pin})};
 const spec={schema:'study-compiled-excluded-history-slot.v1',sourceArtifactSha256:f.profile.bindings.sourceArtifactSha256,region:{selector:'.sf-report',ordinal:0,total:1,ownerPath:[region.childNodes.length-1]},ownerAttrs:attrs(owner),ownerTree:graph(owner),nativeSource:null,anchorPath:[1],manifestPath:[1,0],manifestText:manifest.textContent,parts:[{...part,tree:Array.from(template.content.childNodes,graph),evidence:[evidence],consumerEvidence:{fine_example_roots:[],bank_containers:[],group_panels:[],group_physical_native_rows:[],residual_key_targets:[],projection_pair_roots:[]}}]};
 f.profile.historySlots.push(spec);
 const request={manifest,anchor,holder:owner,detail:owner,kind:'disclosure',panel:null,value:JSON.parse(manifest.textContent),at:0};
 return{owner,manifest,anchor,template,pre,evidence,spec,part,request,load(){assert.equal(f.handle.authorizeHistoryPart(request,part,template.content),true);owner.insertBefore(template.content,anchor);request.at=1;manifest.dataset.asLoadedParts='1';manifest.dataset.asState='ready';assert.equal(f.handle.refresh(),true);}};
}
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledHistoryBankTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(
            [shutil.which('node'), '-e', BANK_FIXTURE_JS + source], cwd=ROOT,
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_as_only_history_bank_authorizes_each_original_af_pre(self):
        self.node(r"""
(async()=>{const f=fixture(0);try{
 const a=addAS(f),b=addAS(f);assert.equal(f.profile.initialHistorySlots.length,0);
 f.install();a.load();b.load();assert.equal(f.write(a.pre),true);assert.equal(f.write(b.pre),true);
 await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.handle.assertHistorySlots(),true);
 assert.equal(f.invalidations,0);assert.equal(Object.keys(f.profile.initialHistoryText).length,1);
 assert.equal(a.pre.textContent,full);assert.equal(b.pre.textContent,full);
}finally{f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_initial_and_as_evidence_share_one_bank_with_late_closed_owner(self):
        self.node(r"""
(async()=>{const f=fixture(1);try{
 const a=addAS(f);f.install();assert.equal(f.write(),true);a.load();a.pre.parentNode.open=true;a.pre.parentNode.open=false;
 assert.equal(f.write(a.pre),true);await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.invalidations,0);
 assert.equal(f.profile.historySlots[0].parts[0].evidence[0].text,undefined);
 assert.equal(f.profile.historySlots[0].parts[0].evidence[0].textKey,pin);
}finally{f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_legacy_text_evidence_remains_compatible_without_shared_tables(self):
        self.node(r"""
(async()=>{const f=fixture(0);try{
 delete f.profile.initialHistorySlots;delete f.profile.initialHistoryText;const a=addAS(f,true);
 f.install();a.load();assert.equal(f.write(a.pre),true);await tick();assert.equal(f.handle.refresh(),true);assert.equal(f.invalidations,0);
}finally{f.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
""")

    def test_conflicting_missing_or_unused_text_references_fail_before_install(self):
        self.node(r"""
for(const change of [
 (f,a)=>a.evidence.text=full,
 (f,a)=>delete a.evidence.textKey,
 (f,a)=>a.evidence.textKey=sha('different pin'),
 (f,a)=>delete f.profile.initialHistoryText[pin],
 (f,a)=>f.profile.initialHistoryText[pin]=42,
 (f,a)=>f.profile.initialHistoryText[sha('unused')]='unused',
 (f,a)=>delete f.profile.initialHistorySlots,
 (f,a)=>delete f.profile.initialHistoryText,
 (f,a)=>a.evidence.resourceSha256='invalid',
 (f,a)=>delete a.evidence.resourceSha256,
 (f,a)=>a.evidence.path=[-1],
 (f,a)=>a.spec.parts[0].evidence.push({...a.evidence}),
 (f,a)=>a.evidence.sha256='not a SHA'
]){const f=fixture(0),a=addAS(f);try{change(f,a);const before=f.d.body.innerHTML;assert.throws(()=>f.install(),/Compiled card invalid/);assert.equal(f.d.body.innerHTML,before);assert.equal(f.invalidations,0);}finally{f.close();}}
""")

    def test_existing_part_graph_scope_text_and_owner_lifecycle_remain_enforced(self):
        self.node(r"""
(async()=>{
for(const change of [a=>a.pre.setAttribute('data-forged','yes'),a=>a.pre.textContent+='changed',a=>a.part.sha256='0'.repeat(64)]){const f=fixture(0),a=addAS(f);try{f.install();change(a);assert.throws(()=>a.load(),/history part/);assert.equal(f.invalidations,1);}finally{f.close();}}
const f=fixture(0);try{
 const a=addAS(f);f.install();f.setCurrent(false);assert.equal(f.handle.authorizeHistoryPart(a.request,a.part,a.template.content),false);f.setCurrent(true);a.load();
 const before=a.pre.outerHTML;f.setCurrent(false);assert.equal(f.write(a.pre),false);assert.equal(a.pre.outerHTML,before);f.setCurrent(true);
 assert.throws(()=>f.write(a.pre,full+'forged'),/uncovered history evidence write/);assert.equal(a.pre.outerHTML,before);
}finally{f.close();}
const g=fixture(0);try{const a=addAS(g);g.install();a.load();g.handle.dispose();const before=a.pre.outerHTML;assert.equal(g.write(a.pre),false);assert.equal(a.pre.outerHTML,before);}finally{g.close();}
const h=fixture(0);try{const a=addAS(h);h.install();a.load();assert.equal(h.write(a.pre),true);a.pre.firstChild.data+='forged';await tick();assert.equal(h.invalidations,1);}finally{h.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
""")


if __name__ == '__main__':
    unittest.main()
