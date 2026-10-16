from pathlib import Path
import datetime,hashlib,json,subprocess
D=Path(__file__).resolve().parent
OLD=Path('/tmp/study-compiled-2026-numbered-v3-20261017-qaT7rP')
P=Path('/tmp/study-compiled-largest-phase-clock-20261017-rsS2Tf2L')
sha=lambda b:hashlib.sha256(b).hexdigest()
def check(p,pin):
 raw=p.read_bytes();assert p.is_file() and not p.is_symlink() and sha(raw)==pin,str(p);return raw
baseMRaw=check(OLD/'manifest.json','ab584b920cdd26b78297342a110717a3b3438027762e1361fd945fcf9ed6146e');m=json.loads(baseMRaw);root=Path(m['target_root']);formal=check(root/'index.html',m['official_index_sha256'])
baseQA=check(root/m['qa_filename'],m['files'][m['qa_filename']]['sha256']);assert baseQA==(OLD/m['qa_filename']).read_bytes()
frozenRaw=check(P/'FROZEN.json','51eaa05ae6c609c19973d63977439821ac45ce4f52073eb329c02e1ed74e7f03');frozen=json.loads(frozenRaw)
for name,spec in frozen['files'].items():raw=check(P/name,spec['sha256']);assert len(raw)==spec['bytes']
frameRaw=check(P/'candidate-frame.js','4077d2d8cc5e9e4970d48f1409f8279e8f87e8a18a11a6af2764ce46c798ff7f');frame=frameRaw.decode();htmlRaw=check(P/'candidate-frame.html','4f1a9db323dccc4482d8c97dcd6dcb8e76053ead619fa447b3d80d1cd940ccaf');html=htmlRaw.decode();baseFrame=(OLD/'candidate-frame.js').read_bytes();baseHtml=(OLD/'candidate-frame.html').read_bytes();edits=json.loads((P/'edits.json').read_bytes());assert len(edits)==27
forward=baseFrame.decode()
for before,after in edits:assert forward.count(before)==1;forward=forward.replace(before,after,1)
assert forward==frame
inverse=frame
for before,after in reversed(edits):assert inverse.count(after)==1;inverse=inverse.replace(after,before,1)
assert inverse.encode()==baseFrame and html.replace(frame,baseFrame.decode(),1).encode()==baseHtml
for name in ['candidate-frame.js','candidate-frame.html','edits.json','phase-helper.js','protocol.json']:(D/name).write_bytes((P/name).read_bytes())
oldcfg=(OLD/'qa-config.literal').read_bytes();cfg=json.loads(oldcfg);assert cfg['sharedFrame']['html'].encode()==baseHtml
enc=lambda s:json.dumps(s,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').encode();oldenc=enc(baseHtml.decode());newenc=enc(html);assert oldcfg.count(oldenc)==1;newcfg=oldcfg.replace(oldenc,newenc,1)
newCfg=json.loads(newcfg);newCfg['sharedFrame']['html']=cfg['sharedFrame']['html'];assert newCfg==cfg
(D/'qa-config.literal').write_bytes(newcfg)
oldCollector=(OLD/'collector.js').read_text();collector=oldCollector;parentEdits=[]
def edit(before,after):
 global collector
 assert collector.count(before)==1,before[:100];collector=collector.replace(before,after,1);parentEdits.append([before,after])
at=collector.index(' const metadata=')+len(' const metadata=');oldMeta,n=json.JSONDecoder().raw_decode(collector[at:]);meta=json.loads(json.dumps(oldMeta));meta.update({'case_id':'compiled-largest2026-v3-phase-diagnostic-v1','candidate_identity':'same-numbered-v3-assets-and-e56-clock-only-FRAME-boundaries','candidate_frame_sha256':sha(frameRaw),'phase_protocol_sha256':sha((P/'protocol.json').read_bytes()),'phase_clock_scope':'First back prepare only; existing FRAME boundaries, <=64 scalar rows; same underlying gates/authors/runtime; no extra source DOM scans; no paint or CPU claim.'});oldLiteral=collector[at:at+n];edit(oldLiteral,json.dumps(meta,separators=(',',':')))
edit('const origin=location.origin,path=location.pathname,began=performance.now(),clock=', 'const origin=location.origin,path=location.pathname,began=performance.now(),parentTimeOrigin=performance.timeOrigin,clock=')
receiver=(D/'phase-receiver.js').read_text();edit(' const flips=[],validations=[];',receiver+'\n const flips=[],validations=[];')
edit("manual_and_auto_flips:flips.map(v=>({...v})),validation_runs:validations,", "manual_and_auto_flips:flips.map(v=>({...v})),validation_runs:validations,parent_time_origin:parentTimeOrigin,parent_clock_began:began,phase_clock:phase_clock.map(row=>({...row})),phase_clock_boundary:'FRAME timeOrigin+at; parent request epoch=parent_time_origin+parent_clock_began+first_back_request_ms. Click to prepare-start contains HOST/full-packet waiting, whose internal stages are not individually measured. Wall/inclusive intervals, concurrent resources and nested author/binder/batch spans must not be added; not paint.',")
edit("if(accepted!==null&&data.token!==accepted){state.status='superseded';", "if(data.type==='study-compiled-phase-clock'){receivePhase(data);return;}if(accepted!==null&&data.token!==accepted){state.status='superseded';")
inverseCollector=collector
for before,after in reversed(parentEdits):assert inverseCollector.count(after)==1;inverseCollector=inverseCollector.replace(after,before,1)
assert inverseCollector==oldCollector and 'inspectFailedTarget' not in collector and 'failure_probe' not in collector
(D/'collector.js').write_text(collector);(D/'parent-edits.json').write_text(json.dumps(parentEdits,indent=2)+'\n')
block=('<script id="study-compiled-profile-qa-clock">\n'+collector+'\n</script>\n').encode();oldBlock=(OLD/'clock-block.html').read_bytes();assert baseQA.count(oldBlock)==1 and baseQA.count(oldcfg)==1
qa=baseQA.replace(oldcfg,newcfg,1).replace(oldBlock,block,1);assert qa.replace(block,oldBlock,1).replace(newcfg,oldcfg,1)==baseQA
nameQA='_qa_compiled_profile_'+sha(qa)[:12]+'.html';assert not(root/nameQA).exists();(D/nameQA).write_bytes(qa);(D/'clock-block.html').write_bytes(block)
# The ownership-safe installer is byte-identical to the reviewed implementation except its truthful description.
installer=(OLD/'install.py').read_text();before='Default read-only; --apply exclusively creates a new pinned numbered body, profile and QA; existing assets remain read-only.';after='Default read-only; --apply exclusively creates one phase-diagnostic parent QA; all existing assets remain read-only.';assert installer.count(before)==1;installer=installer.replace(before,after,1);(D/'install.py').write_text(installer)
readonly=[{'name':entry['name'],'sha256':entry['sha256'],'bytes':entry['bytes']} for entry in m['readonly_assets'] if entry['sha256']=='e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc']+[{ 'name':name,**entry} for name,entry in m['files'].items()]
assert len(readonly)==4
for item in readonly:raw=check(root/item['name'],item['sha256']);assert len(raw)==item['bytes']
url=m['cold_only_url'].replace(m['qa_filename'],nameQA)
inputs={str(OLD/'manifest.json'):sha(baseMRaw),str(P/'FROZEN.json'):sha(frozenRaw)}
for name in ['candidate-frame.js','candidate-frame.html','edits.json','phase-helper.js','protocol.json','collector.js','parent-edits.json','phase-receiver.js']:
 p=D/name;inputs[str(p)]=sha(p.read_bytes())
manifest={key:m[key] for key in ['schema','target_root','official_index_sha256','official_host_sha256','candidate_host_filename','candidate_host_sha256','candidate_host_bytes']};manifest.update({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'asset_files':[],'qa_filename':nameQA,'files':{nameQA:{'sha256':sha(qa),'bytes':len(qa)}},'readonly_assets':readonly,'installer_sha256':sha(installer.encode()),'frozen_source_inputs':inputs,'metadata':meta,'cold_only_url':url,'digest_observer_url':url,'urls':{next(iter(meta['cases'])):url},'no_installation_or_UI':True});(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'phase':'manifest-ready','stage':str(D),'manifest_sha256':sha((D/'manifest.json').read_bytes()),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json'},indent=2),flush=True)
for name in ['candidate-frame.js','collector.js']:subprocess.run(['/opt/homebrew/bin/node','--check',str(D/name)],check=True)
r=subprocess.run(['/opt/homebrew/bin/node',str(D/'receiver-contract.cjs')],capture_output=True,text=True);(D/'receiver-contract.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run(['/tmp/anki-study-runtime-20261015/bin/python','-B',str(D/'install.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr;(D/'dry-run.json').write_text(r.stdout)
assert (root/'index.html').read_bytes()==formal
proof={'schema':'study-v3-compiled-phase-diagnostic-QA-acceptance.v1','frame_clock_edits':27,'frame_inverse_exact_to_v3_5abf':True,'frame_HTML_inverse_exact_to_v3_1d037':True,'parent_edits':len(parentEdits),'parent_collector_inverse_exact_to_normal_v3':True,'parent_QA_HTML_inverse_exact_to_installed_v3_f94a':True,'same_installed_HTML746_profile7a87_runtimee56':True,'new_large_assets':0,'new_parent_QA_files':1,'fullgate10s_and_authors_and_source_guards_unchanged':True,'phase_clock_rows_cap':64,'phase_trust':'existing source/origin/id/token plus first prepare generation/timeOrigin, strict field/label/kind/number whitelists','phase_collection_no_publish_or_DOM_scan':True,'parent_time_origin_and_existing_began_preserved':True,'receiver_contracts_passed':4,'syntax_passed':True,'installer_logic_unchanged_only_description_diff':True,'installer_default_dryrun_exit':0,'manifest_sha256':sha((D/'manifest.json').read_bytes()),'QA_sha256':sha(qa),'frame_sha256':sha(frameRaw),'frame_HTML_sha256':sha(htmlRaw),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json','installed':False,'browser_run':False,'CPU_terminal':True};(D/'acceptance.json').write_text(json.dumps(proof,indent=2)+'\n')
(D/'README.md').write_text('# V3 compiled card phase clocks, isolated QA\n\nOne new parent QA only. Installed numbered HTML746, profile7a87 and runtimee56 are exact read-only inputs.27 clock-only FRAME edits inverse exactly to installedv3; parent receiver is bounded64 numeric rows and never publishes per-message. Existing first-front/one-auto-flip/full-back timing and optional scalar verifier remain. No extra DOM/source scan, digest/native wrappers, gate extension or author change. Parent and FRAME time origins are preserved for epoch alignment. Resource times are parallel and spans wall/inclusive, not additive CPU or paint. Click→prepare-start includes HOST/fullpacket waiting, not individual HOST-internal stages.\n\nRoot install after review: `/tmp/anki-study-runtime-20261015/bin/python -B '+str(D)+'/install.py --apply`.\n')
files={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(D.iterdir()) if p.is_file() and p.name!='SEALS.json'};(D/'SEALS.json').write_text(json.dumps({'schema':'study-isolated-QA-files-seal.v1','files':files},indent=2)+'\n')
print(json.dumps({'phase':'complete','stage':str(D),'manifest_sha256':proof['manifest_sha256'],'acceptance_sha256':sha((D/'acceptance.json').read_bytes()),'seals_sha256':sha((D/'SEALS.json').read_bytes()),'QA_sha256':sha(qa),'url':url,'download_filename':proof['download_filename'],'CPU_terminal':True},indent=2))
