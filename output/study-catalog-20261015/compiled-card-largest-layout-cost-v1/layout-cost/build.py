from pathlib import Path
import hashlib,json

D=Path(__file__).parent
S=Path('/tmp/study-compiled-numbering-first-claim-v2-20261017-grx8pxci')
PIN='bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816'
HTMLPIN='d70c033ac6e83d9b6b8138e8c23539c233479b328ac7800ef3f93d9b196c4786'
sha=lambda x:hashlib.sha256(x.encode() if isinstance(x,str) else x).hexdigest()
base=(S/'phase-frame.js').read_text();html=(S/'phase-frame.html').read_text()
assert sha(base)==PIN and sha(html)==HTMLPIN
code=base;edits=[]
def add(before,after,label):
 global code
 assert code.count(before)==1,(label,code.count(before))
 code=code.replace(before,after);edits.append({'label':label,'before':before,'after':after})
start=base.index('function installCigen(win,doc){')
end=base.index('\nconst staticHistoryCohorts=',start)
original=base[start:end];cigen=original
needle="let scheduled=false,batchDepth=0,dirty=false;"
assert cigen.count(needle)==1
cigen=cigen.replace(needle,needle+'\n'+(D/'cigen-helper.js').read_text())
def sub(before,after):
 global cigen
 assert cigen.count(before)==1,before
 cigen=cigen.replace(before,after)
layout_start=cigen.index(' function layout(frame){')
layout_end=cigen.index('\n const sizes=',layout_start)
layout=cigen[layout_start:layout_end]
assert layout.count('frame.getBoundingClientRect().width')==2
layout=layout.replace('frame.getBoundingClientRect().width',"qaMeasure('firstGeometry',()=>frame.getBoundingClientRect().width)",1)
at=layout.index('const meaning=')
stop=layout.index('const signature=')
styles=layout[at:stop]
layout=layout[:at]+"const {font,metrics}=qaMeasure('styleBlock',()=>{"+styles+"return{font,metrics}});"+layout[stop:]
old="Math.round(frame.getBoundingClientRect().width)"
assert layout.count(old)==1
layout=layout.replace(old,"Math.round(qaMeasure('repeatGeometry',()=>frame.getBoundingClientRect().width))")
layout=layout.replace(' function layout(frame){'," function layout(frame){return qaMeasure('layout',()=>{",1)
assert layout.endswith('}')
layout=layout[:-1]+'})}'
cigen=cigen[:layout_start]+layout+cigen[layout_end:]
sub('doc.querySelectorAll(selector)',"qaMeasure('iframeSelector',()=>doc.querySelectorAll(selector))")
refresh_start=cigen.index(' function refresh(){');refresh_end=cigen.index('\n function batch(',refresh_start)
refresh=cigen[refresh_start:refresh_end]
refresh=refresh.replace(' function refresh(){'," function refresh(){return qaMeasure('refresh',()=>{",1)
assert refresh.endswith('}')
refresh=refresh[:-1]+'})}'
cigen=cigen[:refresh_start]+refresh+cigen[refresh_end:]
sub("try{refresh()}finally{qaClock?.span('batch-finally-refresh',qaRefreshStarted)}", "const qaBatchStarted=qaEnabled?qaNow():null;if(qaEnabled){qaCosts.batchFinallyCount++;qaFinalDepth++}try{refresh()}finally{if(qaBatchStarted!==null){qaCosts.batchFinallyMs+=Math.max(0,qaNow()-qaBatchStarted);qaFinalDepth--}qaClock?.span('batch-finally-refresh',qaRefreshStarted)}")
sub('win.__ankiCigenFrames={refresh,batch,known};','win.__ankiCigenFrames={refresh,batch,known,qaCostReset,qaCostSeal};')
add(original,cigen,'serialized-cigen-local-measurements')
helper=(D/'status-helper.js').read_text()
add('function gateMemberCache(doc){',helper+'\nfunction gateMemberCache(doc){','private-scalar-status-api')
line=next(l for l in base.splitlines() if l.startswith('function waitPrepared('))
gate=line
def gate_sub(a,b):
 global gate
 assert gate.count(a)==1,a
 gate=gate.replace(a,b)
gate_sub('let previous=null,same=0,members=null;', 'const qaGate=qaLayoutCostGate(entry);let previous=null,same=0,members=null;')
gate_sub('const resolve=value=>{release();finish(value)},reject=error=>{release();fail(error)};', "const resolve=value=>{qaLayoutCostResult(qaGate,value?'ready':'cancelled');release();finish(value)},reject=error=>{qaLayoutCostResult(qaGate,'error');release();fail(error)};")
gate_sub('function check(){try{','function check(){const qaCheckStarted=qaLayoutCostCheckStart(qaGate);try{')
ready="native.every(value=>value==='ready')&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return state?.ready&&state.readySignature===state.signature&&Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1})&&doc.fonts?.status!=='loading'"
new_ready="qaLayoutCostCondition(qaGate,'Native',native.every(value=>value==='ready'))&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return qaLayoutCostCondition(qaGate,'ChildReady',state?.ready)&&qaLayoutCostCondition(qaGate,'ChildSignature',state.readySignature===state.signature)&&qaLayoutCostCondition(qaGate,'ChildWidth',Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1)})&&qaLayoutCostCondition(qaGate,'Fonts',doc.fonts?.status!=='loading')"
gate_sub(ready,new_ready)
gate_sub('const signature=ready?JSON.stringify(snapshot(doc,false)):null;', 'qaLayoutCostReady(qaGate,ready);const signature=ready?JSON.stringify(qaLayoutCostSnapshot(qaGate,()=>snapshot(doc,false))):null;')
gate_sub('}catch(error){reject(error)}}try{requestAnimationFrame(check)}', '}catch(error){reject(error)}finally{qaLayoutCostCheckEnd(qaGate,qaCheckStarted)}}try{requestAnimationFrame(check)}')
add(line,gate,'gate-existing-values-and-snapshot-timing')
add("phase?.point('body-adoption-start');const head=", "phase?.point('body-adoption-start');if(phase)qaLayoutCostBegin(active,packet,token);const head=",'begin-before-original-body-adoption')
add("phase?.point('full-gate-complete');if(packet.metricsAsset)", "if(phase)qaLayoutCostSeal(active,packet,token);phase?.point('full-gate-complete');if(packet.metricsAsset)",'seal-at-original-full-gate')
add('compiledProfiles.clear(doc);if(compiled){','compiledProfiles.clear(doc);qaLayoutCostClear(doc);if(compiled){','release-before-new-body')
add('compiledProfiles.clear(doc);doc.body.replaceChildren();','compiledProfiles.clear(doc);qaLayoutCostClear(doc);doc.body.replaceChildren();','release-clearOld')
inverse=code
for e in reversed(edits):
 assert inverse.count(e['after'])==1,e['label']
 inverse=inverse.replace(e['after'],e['before'])
assert inverse==base
assert html.count(base)==1
candidate_html=html.replace(base,code)
assert candidate_html.replace(code,base)==html
(D/'baseline-frame.js').write_text(base);(D/'candidate-frame.js').write_text(code);(D/'candidate-frame.html').write_text(candidate_html)
(D/'edits.json').write_text(json.dumps(edits,indent=2)+'\n')
fields=['schema','scope','id','token','viewToken','timeOrigin','cigenRefreshCount','cigenRefreshMs','cigenLayoutCount','cigenLayoutMs','iframeSelectorCount','iframeSelectorMs','firstGeometryCount','firstGeometryMs','styleBlockCount','styleBlockMs','repeatGeometryCount','repeatGeometryMs','batchFinallyCount','batchFinallyMs','batchIframeSelectorMs','batchFirstGeometryMs','batchStyleBlockMs','batchRepeatGeometryMs','gateCalls','gateChecks','gateCheckMs','gateMaxCheckMs','gateFirstCheckAt','gateFirstAllReadyAt','gateFinishedAt','gateReadyChecks','gateNativeBlocked','gateChildReadyBlocked','gateChildSignatureBlocked','gateChildWidthBlocked','gateFontsBlocked','gateLastBlocker','snapshotCount','snapshotMs','snapshotMaxMs','gateResult']
assert len(fields)<=64
protocol={'schema':'study-compiled-layout-cost.v1','api':'StudyCompiledLayoutCostStatus.read(currentSourceDocument)','fields':fields,'strings':{'schema':['study-compiled-layout-cost.v1'],'scope':['body-adoption-to-first-full-gate'],'id':['ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576'],'gateLastBlocker':['none','Native','ChildReady','ChildSignature','ChildWidth','Fonts'],'gateResult':['pending','ready','cancelled','error']},'nullable_numbers':['gateFirstCheckAt','gateFirstAllReadyAt','gateFinishedAt'],'numbers':'Every other field is a finite nonnegative number; token/viewToken and Count/Calls/Checks/Blocked are integers.','max_fields':len(fields),'arrays':0,'hot_messages':0,'time_boundary':'At fields use FRAME performance.timeOrigin; cigen durations use realm performance.now differences. All times wall/inclusive, not CPU.','nested':'layout/selector/style/geometry and batch numbers are nested in refresh; snapshot is nested in gate checks. Do not add them.','styleBlock':'Existing local meaning/sample/title/callout/tag queries, computed-style property reads, and the two original frame font style writes; no extra DOM read.'}
(D/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
proof={'schema':'study-cigen-gate-cost-composition.v1','baseline_path':str(S/'phase-frame.js'),'baseline_frame_sha256':PIN,'baseline_html_sha256':HTMLPIN,'candidate_frame_sha256':sha(code),'candidate_html_sha256':sha(candidate_html),'edits':len(edits),'inverse_exact_frame':True,'inverse_exact_html':True,'original_claim_author_e56_source_order_unchanged':True,'original_raf_same_2_timeout_10000_retained':True,'no_new_dom_reads_await_messages':True,'only_tmp_no_install':True}
(D/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
