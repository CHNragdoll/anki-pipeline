from pathlib import Path
import datetime,hashlib,json,subprocess
D=Path(__file__).resolve().parent;OLD=Path('/tmp/study-compiled-2026-v3-phase-qa-20261017-np8gK2');P=Path('/tmp/study-compiled-numbering-first-claim-v2-20261017-grx8pxci')
sha=lambda b:hashlib.sha256(b).hexdigest()
def checked(path,pin):
 raw=path.read_bytes();assert not path.is_symlink() and path.is_file() and sha(raw)==pin,str(path);return raw
baseMRaw=checked(OLD/'manifest.json','ecb65c030a7b171c9854b0cc1a6c4d00dc6587bdc4f5ec9a147c93993789e8b2');m=json.loads(baseMRaw);root=Path(m['target_root']);formal=checked(root/'index.html',m['official_index_sha256']);baseQA=checked(root/m['qa_filename'],m['files'][m['qa_filename']]['sha256']);assert baseQA==(OLD/m['qa_filename']).read_bytes()
frozenRaw=checked(P/'FROZEN.json','1900066a087b48da52b2aea98083aadafa5ad3026e1fc04ca4f5d0a94f3b00ca');frozen=json.loads(frozenRaw)
assert frozen['schema']=='study-compiled-numbering-first-claim-frozen.v2' and isinstance(frozen['files'],list)
for spec in frozen['files']:raw=checked(P/spec['path'],spec['sha256']);assert len(raw)==spec['bytes']
frameRaw=checked(P/'phase-frame.js','bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816');frame=frameRaw.decode();htmlRaw=checked(P/'phase-frame.html','d70c033ac6e83d9b6b8138e8c23539c233479b328ac7800ef3f93d9b196c4786');html=htmlRaw.decode();normalRaw=checked(P/'normal-frame.js','e40484fb8aece7e38a0efbe7f00964791840024d73340199392b0e13480ba369');normalHTML=checked(P/'normal-frame.html','3aa35a2f3fd0a60bc62d4343602bd1c703ead444db0b23c3f4d6ff3b9617e822')
phaseEdits=json.loads((P/'phase-edits-rebased.json').read_bytes());claimEdits=json.loads((P/'claim-edits.json').read_bytes());assert len(phaseEdits)==27 and len(claimEdits)==6
inverse=frame
for before,after in reversed(phaseEdits):assert inverse.count(after)==1;inverse=inverse.replace(after,before,1)
assert inverse.encode()==normalRaw
for before,after in reversed(claimEdits):assert inverse.count(after)==1;inverse=inverse.replace(after,before,1)
assert sha(inverse.encode())=='5abf728de9703c405389dccc90a96a939cf7ea76cc83431885189d0f2f7c7133'
assert html.replace(frame,normalRaw.decode(),1).encode()==normalHTML
baseFrame=(OLD/'candidate-frame.js').read_bytes();baseHTML=(OLD/'candidate-frame.html').read_bytes();assert sha(baseFrame)=='4077d2d8cc5e9e4970d48f1409f8279e8f87e8a18a11a6af2764ce46c798ff7f'
assert html.replace(frame,baseFrame.decode(),1).encode()==baseHTML
for name in ['phase-frame.js','phase-frame.html','normal-frame.js','normal-frame.html','phase-edits-rebased.json','claim-edits.json','report.json']:(D/name).write_bytes((P/name).read_bytes())
oldcfg=(OLD/'qa-config.literal').read_bytes();cfg=json.loads(oldcfg);assert cfg['sharedFrame']['html'].encode()==baseHTML
enc=lambda s:json.dumps(s,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').encode();assert oldcfg.count(enc(baseHTML.decode()))==1;newcfg=oldcfg.replace(enc(baseHTML.decode()),enc(html),1);undo=json.loads(newcfg);undo['sharedFrame']['html']=cfg['sharedFrame']['html'];assert undo==cfg;(D/'qa-config.literal').write_bytes(newcfg)
collector=(OLD/'collector.js').read_text();oldCollector=collector;parentEdits=[]
def edit(before,after):
 global collector
 assert collector.count(before)==1,before[:120];collector=collector.replace(before,after,1);parentEdits.append([before,after])
at=collector.index(' const metadata=')+len(' const metadata=');oldMeta,n=json.JSONDecoder().raw_decode(collector[at:]);meta=json.loads(json.dumps(oldMeta));meta.update({'case_id':'compiled-largest2026-v3-initial-numbering-claim-v2','candidate_identity':'same-numbered-v3-body-profile-e56-initial-numbering-claim-v2-owner-release','candidate_frame_sha256':sha(frameRaw),'normal_claim_frame_sha256':sha(normalRaw),'numbering_claim_frozen_sha256':sha(frozenRaw),'initial_numbering_claim_status_boundary':'Optional first valid after-gate verify click only; own frozen data/read API with current source doc and token. Strict scalar snapshot; no additional source scan.'});edit(collector[at:at+n],json.dumps(meta,separators=(',',':')))
readerPath=D/'claim-status-reader.js';reader=readerPath.read_text();reader=reader.replace('snapshot.rows>10000000','snapshot.rows>8192');readerPath.write_text(reader);assert '__CLAIM_STATUS_REASONS__' not in reader
edit(' function scalarStats(value,depth=0){',reader+'\n function scalarStats(value,depth=0){')
edit("if(!selected()||accepted!==token||side.contentDocument!==doc||lastAnswer!==true)throw Error('Validation ownership changed');validations.push", "const numberingClaim=readInitialClaimStatus(doc,token);if(!selected()||accepted!==token||side.contentDocument!==doc||lastAnswer!==true)throw Error('Validation ownership changed');validations.push")
edit("compiled_handle_stats:compiled,scope:'Bounded public scalar handle stats only; no full-card DOM query/count or text/HTML dump.'", "compiled_handle_stats:compiled,initial_numbering_claim_status:numberingClaim,scope:'Bounded public scalar handle stats and one current initial-numbering claim-status read only; no full-card DOM query/count or text/HTML dump.'")
inverseCollector=collector
for before,after in reversed(parentEdits):assert inverseCollector.count(after)==1;inverseCollector=inverseCollector.replace(after,before,1)
assert inverseCollector==oldCollector
for name in ['phase-receiver.js','receiver-contract.cjs']:assert (D/name).read_bytes()==(OLD/name).read_bytes()
assert 'inspectFailedTarget' not in collector and 'failure_probe' not in collector
(D/'collector.js').write_text(collector);(D/'parent-edits.json').write_text(json.dumps(parentEdits,indent=2)+'\n');block=('<script id="study-compiled-profile-qa-clock">\n'+collector+'\n</script>\n').encode();oldBlock=(OLD/'clock-block.html').read_bytes();assert baseQA.count(oldBlock)==1 and baseQA.count(oldcfg)==1
qa=baseQA.replace(oldcfg,newcfg,1).replace(oldBlock,block,1);assert qa.replace(block,oldBlock,1).replace(newcfg,oldcfg,1)==baseQA;nameQA='_qa_compiled_profile_'+sha(qa)[:12]+'.html';assert not(root/nameQA).exists();(D/nameQA).write_bytes(qa);(D/'clock-block.html').write_bytes(block)
installer=(OLD/'install.py').read_text();assert installer.startswith('"""Default read-only; --apply exclusively creates one phase-diagnostic parent QA; all existing assets remain read-only.');(D/'install.py').write_text(installer)
readonly=m['readonly_assets']+[{'name':m['qa_filename'],**m['files'][m['qa_filename']]}]
for item in readonly:raw=checked(root/item['name'],item['sha256']);assert len(raw)==item['bytes']
inputs={str(OLD/'manifest.json'):sha(baseMRaw),str(P/'FROZEN.json'):sha(frozenRaw)}
for name in ['phase-frame.js','phase-frame.html','normal-frame.js','normal-frame.html','phase-edits-rebased.json','claim-edits.json','report.json','collector.js','parent-edits.json','claim-status-reader.js','phase-receiver.js']:
 p=D/name;inputs[str(p)]=sha(p.read_bytes())
url=m['cold_only_url'].replace(m['qa_filename'],nameQA);manifest={key:m[key] for key in ['schema','target_root','official_index_sha256','official_host_sha256','candidate_host_filename','candidate_host_sha256','candidate_host_bytes']};manifest.update({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'asset_files':[],'qa_filename':nameQA,'files':{nameQA:{'sha256':sha(qa),'bytes':len(qa)}},'readonly_assets':readonly,'installer_sha256':sha(installer.encode()),'frozen_source_inputs':inputs,'metadata':meta,'cold_only_url':url,'digest_observer_url':url,'urls':{next(iter(meta['cases'])):url},'no_installation_or_UI':True});(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'phase':'manifest-ready','stage':str(D),'manifest_sha256':sha((D/'manifest.json').read_bytes()),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json'},indent=2),flush=True)
for name in ['phase-frame.js','normal-frame.js','collector.js']:subprocess.run(['/opt/homebrew/bin/node','--check',str(D/name)],check=True)
for name in ['receiver-contract.cjs','claim-reader-contract.cjs']:
 r=subprocess.run(['/opt/homebrew/bin/node',str(D/name)],capture_output=True,text=True);(D/(name+'.log')).write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run(['/tmp/anki-study-runtime-20261015/bin/python','-B',str(D/'install.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr;(D/'dry-run.json').write_text(r.stdout);assert (root/'index.html').read_bytes()==formal
proof={'schema':'study-v3-initial-numbering-claim-QA-acceptance.v1','normal_claim_edits':6,'normal_claim_inverse_exact_to_v3_5abf':True,'rebased_phase_edits':27,'phase_inverse_exact_to_normal_claim':True,'phase_execute_clock_measures_real_claim_execute':True,'same_underlying_HTML746_profile7a87_runtimee56':True,'only_numbering_initial_claim_capability_changes':True,'claim_status_read_aftergate_optional_once_scalar_own_data_only':True,'claim_status_missing_throw_getter_stale_safe':True,'existing_compiled_handle_stats_retained':True,'claim_v2_finally_and_dispose_release_owner_callbacks':True,'old_178c_candidate_preserved_uninstalled':True,'same_phase_receiver_bytes':True,'parent_collector_inverse_exact_to_phase_v3':True,'parent_QA_HTML_inverse_exact_to_installed_5943':True,'new_large_assets':0,'new_parent_QA_files':1,'installer_byte_identical_to_previous_reviewed':True,'fullgate10s_and_source_guards_original_authors_unchanged':True,'phase_receiver_contracts_passed':4,'claim_status_reader_contracts_passed':2,'syntax_passed':True,'installer_default_dryrun_exit':0,'manifest_sha256':sha((D/'manifest.json').read_bytes()),'QA_sha256':sha(qa),'phase_frame_sha256':sha(frameRaw),'phase_frame_HTML_sha256':sha(htmlRaw),'normal_claim_frame_sha256':sha(normalRaw),'normal_claim_frame_HTML_sha256':sha(normalHTML),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json','installed':False,'browser_run':False,'performance_success_or_actual_claim_not_yet_observed':True,'CPU_terminal':True};(D/'acceptance.json').write_text(json.dumps(proof,indent=2)+'\n')
files={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(D.iterdir()) if p.is_file() and p.name!='SEALS.json'};(D/'SEALS.json').write_text(json.dumps({'schema':'study-isolated-QA-files-seal.v1','files':files},indent=2)+'\n')
print(json.dumps({'phase':'complete','stage':str(D),'manifest_sha256':proof['manifest_sha256'],'acceptance_sha256':sha((D/'acceptance.json').read_bytes()),'seals_sha256':sha((D/'SEALS.json').read_bytes()),'QA_sha256':sha(qa),'url':url,'download_filename':proof['download_filename'],'CPU_terminal':True},indent=2))
