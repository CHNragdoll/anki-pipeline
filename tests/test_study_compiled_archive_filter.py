"""Original authored all-descendant filtering with exact archived identities."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_JS = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),zlib=require('node:zlib'),crypto=require('node:crypto'),{JSDOM}=require('jsdom');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const rawModule=zlib.gunzipSync(fs.readFileSync('tests/fixtures/study-compiled-native/prepared-module-6a2b0f26.js.gz'));
assert.equal(sha(rawModule),'6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633');
const module=rawModule.toString(),start=module.indexOf('(function () {\n  if (window.__ankiSenseFrequencyBound)'),end=module.indexOf('\n})();',start)+7;
assert.ok(start>0&&end>start);const authoredFilter=module.slice(start,end);
const runtime=fs.readFileSync('anki_pipeline/compiled/card-runtime.js','utf8');
const attrs=n=>Array.from(n.attributes,a=>[a.name,a.value]);
const graph=n=>n.nodeType===1?{type:1,name:n.tagName,namespace:n.namespaceURI,attrs:attrs(n),children:Array.from(n.childNodes,graph)}:{type:n.nodeType,text:n.data};
function fixture(extra,options={}){
 const dom=new JSDOM('<section class="sf-report"><details class="sf-sense" open><summary>2次</summary><div class="sf-panel" data-study-compiled-key="panel"><div class="sf-filters"><button data-sf-filter="all" aria-pressed="true">全部</button><button data-sf-filter="2026" aria-pressed="false">2026</button><button data-sf-filter="2011" aria-pressed="false">2011</button></div><p class="sf-preview-count" data-study-compiled-key="status">显示 2 条原文</p><article class="sf-example" data-sf-year="2026" data-study-compiled-key="a"><p>主句A</p><details class="sf-inline-history"><summary>原审核</summary><article class="sf-example" data-sf-year="2011"><p>原归档全文</p></article></details></article><article class="sf-example" data-sf-year="2011" data-study-compiled-key="b"><p>主句B</p></article></div></details></section>',{runScripts:'outside-only',url:'https://card.invalid/'});
 const w=dom.window,d=w.document,panel=d.querySelector('.sf-panel'),a=d.querySelector('[data-study-compiled-key="a"]'),b=d.querySelector('[data-study-compiled-key="b"]'),status=d.querySelector('.sf-preview-count'),archive=d.querySelector('.sf-inline-history > .sf-example');
 const bindings={};for(const n of ['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'])bindings[n]='a'.repeat(64);
 const profile={schema:'study-compiled-card-interactions.v1',version:1,filter_mode:'host-after-authored-filter',residual_mode:'original-listener',bindings,nodeBindings:[],projectionWrappers:[],residualWrappers:[],readerLinks:[],groups:[],bankRecords:[],panels:[{panelKey:'panel',statusKey:'status',memberKeys:['a','b']}],historySlots:[]};
 function binding(node,key,rootKey,rootPath,relativePath,roles){return{key,rootKey,region:{selector:'.sf-report',ordinal:0,total:1,rootPath},relativePath,tag:node.tagName,namespace:node.namespaceURI,requiredAttrs:attrs(node),roles,logicalRoot:{kind:'original'},exactText:node.textContent};}
 let handle,current=true,invalidations=0;const errors=[],authoredCounts=[];
 const checkpoints=[];
 const f={w,d,panel,a,b,archive,status,profile,authoredCounts,errors,checkpoints,get handle(){return handle;},get invalidations(){return invalidations;},setCurrent(v){current=v;},install(){
  profile.nodeBindings=[binding(panel,'panel','panel',[0,1],[],['group-panel']),binding(status,'status','panel',[0,1],[1],['group-status']),binding(a,'a','a',[0,1,2],[],['original-example']),binding(b,'b','b',[0,1,3],[],['original-example'])];
  for(const s of profile.nodeBindings)s.region.total=d.querySelectorAll('.sf-report').length;
  w.eval(authoredFilter);w.eval(runtime);handle=w.AnkiCompiledCardRuntime.install(d,profile,{isCurrent:()=>current,onInvalid(){invalidations++;}});
  d.addEventListener('click',event=>{const button=event.target.closest('[data-sf-filter]');if(button){authoredCounts.push(status.textContent);const run=()=>{checkpoints.push(handle.stats().invalid);try{handle.applyGrouping(panel);}catch(e){errors.push(e);}};if(options.skipGrouping)return;if(options.deferGrouping)Promise.resolve().then(run);else run();}},true);
 },click(year){panel.querySelector('[data-sf-filter="'+year+'"]').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));},close(){handle?.dispose();w.close();}};
 if(extra)extra(f);return f;
}
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js is unavailable')
class CompiledArchiveFilterTests(unittest.TestCase):
    def node(self, source):
        result = subprocess.run(
            [shutil.which('node'), '-e', FIXTURE_JS + source], cwd=ROOT,
            text=True, capture_output=True, timeout=25,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_authored_filter_counts_all_descendants_then_groups_direct_members(self):
        self.node(r"""
(async()=>{const f=fixture();try{
 f.install();for(const year of ['2026','all','2011']){f.click(year);await tick();assert.equal(f.errors.length,0,f.errors[0]?.stack);assert.equal(f.handle.refresh(),true);}
 assert.deepEqual(f.authoredCounts,['显示 1 处原文','显示 3 处原文','显示 2 处原文']);
 assert.equal(f.status.textContent,'显示 1 条原文');assert.equal(f.archive.hidden,false);assert.equal(f.a.hidden,true);assert.equal(f.b.hidden,false);assert.equal(f.invalidations,0);
}finally{f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_external_visibility_source_text_and_node_identity_remain_rejected(self):
        self.node(r"""
(async()=>{for(const mutate of [
 f=>f.archive.hidden=true,
 f=>f.archive.firstChild.firstChild.data+='forged',
 f=>f.archive.dataset.sfYear='2026',
 f=>f.archive.setAttribute('data-other','forged'),
 f=>f.archive.replaceWith(f.archive.cloneNode(true)),
 f=>f.b.appendChild(f.archive),
 f=>f.archive.parentNode.appendChild(f.archive.cloneNode(true))
]){const f=fixture();try{f.install();mutate(f);await tick();assert.equal(f.invalidations,1);assert.throws(()=>f.handle.refresh(),/Compiled card invalid/);}finally{f.close();}}})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_incomplete_authored_transaction_does_not_authorize_archive_hidden(self):
        self.node(r"""
const f=fixture();try{f.install();f.archive.hidden=true;assert.throws(()=>f.handle.applyGrouping(f.panel),/Compiled card invalid/);assert.equal(f.invalidations,1);}finally{f.close();}
""")

    def test_observer_checkpoint_between_separate_source_and_consumer_listeners(self):
        self.node(r"""
(async()=>{const f=fixture(null,{deferGrouping:true});try{
 f.install();for(const year of ['2026','all','2011']){f.click(year);await tick();assert.equal(f.errors.length,0,f.errors[0]?.stack);assert.equal(f.handle.refresh(),true);}
 assert.deepEqual(f.checkpoints,[null,null,null]);assert.equal(f.invalidations,0);
 assert.deepEqual(f.authoredCounts,['显示 1 处原文','显示 3 处原文','显示 2 处原文']);assert.equal(f.status.textContent,'显示 1 条原文');
}finally{f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_event_scope_requires_clean_baseline_and_complete_source_state(self):
        self.node(r"""
(async()=>{
 const f=fixture();try{f.install();for(const button of f.panel.querySelectorAll('[data-sf-filter]'))button.setAttribute('aria-pressed',String(button.dataset.sfFilter==='2026'));for(const row of f.panel.querySelectorAll('.sf-example'))row.hidden=row.dataset.sfYear!=='2026';f.status.textContent='显示 1 处原文';assert.throws(()=>f.handle.applyGrouping(f.panel),/external archived visibility change/);assert.equal(f.invalidations,1);}finally{f.close();}
 const g=fixture();try{g.install();g.archive.hidden=true;g.click('2026');await tick();assert.equal(g.invalidations,1);assert.match(g.handle.stats().invalid,/external archived visibility change/);}finally{g.close();}
 const h=fixture(null,{skipGrouping:true});try{h.install();h.click('2026');h.status.textContent='forged status';await tick();assert.equal(h.invalidations,1);}finally{h.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_uncommitted_event_expires_and_dispose_cancels_its_owned_timer(self):
        self.node(r"""
(async()=>{
 const f=fixture(null,{skipGrouping:true});try{f.install();f.click('2026');await tick();await tick();assert.equal(f.invalidations,1);assert.match(f.handle.stats().invalid,/external archived visibility change/);}finally{f.close();}
 const g=fixture(null,{skipGrouping:true});try{g.install();g.click('2026');g.handle.dispose();await tick();await tick();assert.equal(g.invalidations,0);assert.equal(g.handle.stats().disposed,true);}finally{g.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""")

    def test_authorized_as_archive_uses_the_same_filter_and_history_graph(self):
        self.node(r"""
(async()=>{let as;
const f=fixture(f=>{
 const region=f.d.createElement('section');region.className='sf-report';f.a.appendChild(region);
 const owner=f.d.createElement('details');owner.className='sf-inline-history';owner.innerHTML='<summary>AS审核</summary><div class="as-lazy" data-as-kind="detail"><script class="as-manifest" type="application/json"></script></div>';region.appendChild(owner);
 const anchor=owner.lastChild,manifest=anchor.firstChild,pin=sha('AS archived source'),part={src:'_as_'+pin.slice(0,24)+'.js',sha256:pin,count:1};manifest.textContent=JSON.stringify({schema:'anki-slim-segments.v1',total:1,parts:[part]});
 const t=f.d.createElement('template');t.innerHTML='<article class="sf-example sf-archived-example" data-sf-year="2011"><p>AS原归档</p></article>';
 f.profile.historySlots=[{schema:'study-compiled-excluded-history-slot.v1',sourceArtifactSha256:f.profile.bindings.sourceArtifactSha256,region:{selector:'.sf-report',ordinal:1,total:2,ownerPath:[0]},ownerAttrs:attrs(owner),ownerTree:graph(owner),nativeSource:null,anchorPath:[1],manifestPath:[1,0],manifestText:manifest.textContent,parts:[{...part,tree:Array.from(t.content.childNodes,graph),evidence:[],consumerEvidence:{fine_example_roots:[],bank_containers:[],group_panels:[],group_physical_native_rows:[],residual_key_targets:[],projection_pair_roots:[]}}]}];
 as={owner,anchor,manifest,t,part,archive:t.content.firstChild,request:{manifest,anchor,holder:owner,detail:owner,kind:'disclosure',panel:null,value:JSON.parse(manifest.textContent),at:0}};
});try{
 f.install();assert.equal(f.handle.authorizeHistoryPart(as.request,as.part,as.t.content),true);as.owner.insertBefore(as.t.content,as.anchor);as.request.at=1;as.manifest.dataset.asLoadedParts='1';as.manifest.dataset.asState='ready';assert.equal(f.handle.refresh(),true);
 for(const year of ['2026','all','2011']){f.click(year);await tick();assert.equal(f.errors.length,0,f.errors[0]?.stack);assert.equal(f.handle.refresh(),true);}
 assert.deepEqual(f.authoredCounts,['显示 1 处原文','显示 4 处原文','显示 3 处原文']);assert.equal(f.status.textContent,'显示 1 条原文');assert.equal(f.invalidations,0);
 as.archive.hidden=true;await tick();assert.equal(f.invalidations,1);
}finally{f.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
""")


if __name__ == '__main__':
    unittest.main()
