from pathlib import Path
import datetime,hashlib,json,re,subprocess
D=Path(__file__).resolve().parent;OLD=Path('/tmp/study-compiled-2026-v3-numbering-claim-v2-qa-20261017-tH6qX9');P=Path('/tmp/study-cigen-gate-cost-20261017-tWZkCeID')
sha=lambda b:hashlib.sha256(b).hexdigest()
def checked(path,pin):
 raw=path.read_bytes();assert not path.is_symlink() and path.is_file() and sha(raw)==pin,str(path);return raw
baseMRaw=checked(OLD/'manifest.json','ba628e917069a7dac2b21581d78c0a4e0f2a64d4cacd12eb6033b6b99a24949b');m=json.loads(baseMRaw);root=Path(m['target_root']);formal=checked(root/'index.html',m['official_index_sha256']);baseQA=checked(root/m['qa_filename'],m['files'][m['qa_filename']]['sha256']);assert baseQA==(OLD/m['qa_filename']).read_bytes()
frozenRaw=checked(P/'FROZEN.json','76d165acd3d1e023de6f7e3c083454824878d5e7e1951b346628b3e5e5447f6f');frozen=json.loads(frozenRaw);assert frozen['schema']=='study-cigen-gate-cost-seal.v1'
for name,spec in frozen['files'].items():raw=checked(P/name,spec['sha256']);assert len(raw)==spec['bytes']
frameRaw=checked(P/'candidate-frame.js','1c14c2f629111e4f912b6a027cbd1fb47feebdd00b8b18c7982f7193318fc84d');frame=frameRaw.decode();htmlRaw=checked(P/'candidate-frame.html','eda4e08d1ce9ce848896ec2d03d6e2996c7cf5d2b38df52c91eda39c54e951e1');html=htmlRaw.decode();baseFrame=checked(OLD/'phase-frame.js','bf909260b76e478608e6c313b8bdd49d14fb624e162750830a3295e6deb1e816');baseHTML=checked(OLD/'phase-frame.html','d70c033ac6e83d9b6b8138e8c23539c233479b328ac7800ef3f93d9b196c4786')
rawEdits=json.loads((P/'edits.json').read_bytes());assert all(set(item)=={'label','before','after'} for item in rawEdits);edits=[(item['before'],item['after']) for item in rawEdits];forward=baseFrame.decode()
for before,after in edits:assert forward.count(before)==1;forward=forward.replace(before,after,1)
assert forward==frame
inverse=frame
for before,after in reversed(edits):assert inverse.count(after)==1;inverse=inverse.replace(after,before,1)
assert inverse.encode()==baseFrame and html.replace(frame,baseFrame.decode(),1).encode()==baseHTML
for name in ['candidate-frame.js','candidate-frame.html','edits.json','protocol.json','proof.json','status-helper.js','cigen-helper.js']:(D/name).write_bytes((P/name).read_bytes())
protocol=json.loads((P/'protocol.json').read_bytes());assert protocol['schema']=='study-compiled-layout-cost.v1' and len(protocol['fields'])==42 and protocol['max_fields']==42
readerSpec={}
for name in protocol['fields']:
 if name in protocol['strings']:readerSpec[name]={'enum':protocol['strings'][name]}
 else:readerSpec[name]={'type':'integer' if name in ['token','viewToken'] or re.search(r'(Count|Calls|Checks|Blocked)$',name) else 'number',**({'nullable':True} if name in protocol['nullable_numbers'] else {})}
(D/'layout-reader-spec.json').write_text(json.dumps(readerSpec,indent=2)+'\n');reader=(D/'layout-status-reader.template.js').read_text();assert reader.count('__LAYOUT_SPEC_LITERAL__')==1;reader=reader.replace('__LAYOUT_SPEC_LITERAL__',json.dumps(readerSpec,separators=(',',':')),1);(D/'layout-status-reader.js').write_text(reader)
oldcfg=(OLD/'qa-config.literal').read_bytes();cfg=json.loads(oldcfg);assert cfg['sharedFrame']['html'].encode()==baseHTML
enc=lambda s:json.dumps(s,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').encode();assert oldcfg.count(enc(baseHTML.decode()))==1;newcfg=oldcfg.replace(enc(baseHTML.decode()),enc(html),1);undo=json.loads(newcfg);undo['sharedFrame']['html']=cfg['sharedFrame']['html'];assert undo==cfg;(D/'qa-config.literal').write_bytes(newcfg)
collector=(OLD/'collector.js').read_text();oldCollector=collector;parentEdits=[]
def edit(before,after):
 global collector
 assert collector.count(before)==1,before[:120];collector=collector.replace(before,after,1);parentEdits.append([before,after])
at=collector.index(' const metadata=')+len(' const metadata=');oldMeta,n=json.JSONDecoder().raw_decode(collector[at:]);meta=json.loads(json.dumps(oldMeta));meta.update({'case_id':'compiled-largest2026-v3-layout-cost-diagnostic-v1','candidate_identity':'same-numbered-v3-claim-v2-business-path-Cigen-and-gate-numeric-diagnostic-only','candidate_frame_sha256':sha(frameRaw),'layout_cost_frozen_sha256':sha(frozenRaw),'layout_cost_protocol_sha256':sha((P/'protocol.json').read_bytes()),'layout_cost_boundary':'Optional first valid after-gate verify click reads one sealed42-field scalar snapshot. Original Cigen/gate read/write counts/order and10s gate preserved. Wall/inclusive nested intervals are not additive; no extra geometry or DOM/source scan.'});edit(collector[at:at+n],json.dumps(meta,separators=(',',':')))
edit(' function scalarStats(value,depth=0){',reader+'\n function scalarStats(value,depth=0){')
edit("const numberingClaim=readInitialClaimStatus(doc,token);if(!selected()", "const numberingClaim=readInitialClaimStatus(doc,token),layoutCost=readLayoutCostStatus(doc,token);if(!selected()")
edit("initial_numbering_claim_status:numberingClaim,scope:'Bounded public scalar handle stats and one current initial-numbering claim-status read only; no full-card DOM query/count or text/HTML dump.'", "initial_numbering_claim_status:numberingClaim,layout_cost_status:layoutCost,scope:'Bounded public scalar handle stats, one current numbering claim-status read and one sealed layout-cost scalar snapshot only; no full-card DOM query/count or text/HTML dump.'")
inverseCollector=collector
for before,after in reversed(parentEdits):assert inverseCollector.count(after)==1;inverseCollector=inverseCollector.replace(after,before,1)
assert inverseCollector==oldCollector and 'inspectFailedTarget' not in collector and 'failure_probe' not in collector
(D/'collector.js').write_text(collector);(D/'parent-edits.json').write_text(json.dumps(parentEdits,indent=2)+'\n');block=('<script id="study-compiled-profile-qa-clock">\n'+collector+'\n</script>\n').encode();oldBlock=(OLD/'clock-block.html').read_bytes();assert baseQA.count(oldBlock)==1 and baseQA.count(oldcfg)==1
qa=baseQA.replace(oldcfg,newcfg,1).replace(oldBlock,block,1);assert qa.replace(block,oldBlock,1).replace(newcfg,oldcfg,1)==baseQA;nameQA='_qa_compiled_profile_'+sha(qa)[:12]+'.html';assert not(root/nameQA).exists();(D/nameQA).write_bytes(qa);(D/'clock-block.html').write_bytes(block)
installer=(OLD/'install.py').read_bytes();(D/'install.py').write_bytes(installer)
readonly=m['readonly_assets']+[{'name':m['qa_filename'],**m['files'][m['qa_filename']]}]
for item in readonly:raw=checked(root/item['name'],item['sha256']);assert len(raw)==item['bytes']
inputs={str(OLD/'manifest.json'):sha(baseMRaw),str(P/'FROZEN.json'):sha(frozenRaw)}
for name in ['candidate-frame.js','candidate-frame.html','edits.json','protocol.json','proof.json','status-helper.js','cigen-helper.js','collector.js','parent-edits.json','layout-status-reader.js','layout-reader-spec.json']:
 p=D/name;inputs[str(p)]=sha(p.read_bytes())
url=m['cold_only_url'].replace(m['qa_filename'],nameQA);manifest={key:m[key] for key in ['schema','target_root','official_index_sha256','official_host_sha256','candidate_host_filename','candidate_host_sha256','candidate_host_bytes']};manifest.update({'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'asset_files':[],'qa_filename':nameQA,'files':{nameQA:{'sha256':sha(qa),'bytes':len(qa)}},'readonly_assets':readonly,'installer_sha256':sha(installer),'frozen_source_inputs':inputs,'metadata':meta,'cold_only_url':url,'digest_observer_url':url,'urls':{next(iter(meta['cases'])):url},'no_installation_or_UI':True});(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'phase':'manifest-ready','stage':str(D),'manifest_sha256':sha((D/'manifest.json').read_bytes()),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json'},indent=2),flush=True)
for name in ['candidate-frame.js','collector.js']:subprocess.run(['/opt/homebrew/bin/node','--check',str(D/name)],check=True)
r=subprocess.run(['/opt/homebrew/bin/node',str(D/'layout-reader-contract.cjs')],capture_output=True,text=True);(D/'layout-reader-contract.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr
r=subprocess.run(['/tmp/anki-study-runtime-20261015/bin/python','-B',str(D/'install.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr;(D/'dry-run.json').write_text(r.stdout);assert (root/'index.html').read_bytes()==formal
proof={'schema':'study-v3-layout-cost-diagnostic-QA-acceptance.v1','frame_clock_only_edits':len(edits),'frame_inverse_exact_to_claim_v2_bf909':True,'frame_HTML_inverse_exact_to_d70c03':True,'parent_collector_inverse_exact_to_claim_v2':True,'parent_QA_HTML_inverse_exact_to_installed_0834':True,'existing_phase_and_claim_reader_logic_unchanged':True,'optional_layout_snapshot_read_once_aftergate42_strict_scalars':True,'layout_reader_missing_throw_getter_stale_extra_nonfinite_safe':True,'existing_compiled_handle_stats_retained':True,'same_HTML746_profile7a87_runtimee56_source_authors_and_fullgate10s':True,'new_large_assets':0,'new_parent_QA_files':1,'installer_byte_identical_to_previous_reviewed':True,'layout_reader_contracts_passed':2,'syntax_passed':True,'installer_default_dryrun_exit':0,'manifest_sha256':sha((D/'manifest.json').read_bytes()),'QA_sha256':sha(qa),'frame_sha256':sha(frameRaw),'frame_HTML_sha256':sha(htmlRaw),'url':url,'download_filename':meta['case_id']+'-'+next(iter(meta['cases']))[:12]+'-qa.json','installed':False,'browser_run':False,'diagnostic_not_an_optimization_or_performance_pass':True,'CPU_terminal':True};(D/'acceptance.json').write_text(json.dumps(proof,indent=2)+'\n')
files={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(D.iterdir()) if p.is_file() and p.name!='SEALS.json'};(D/'SEALS.json').write_text(json.dumps({'schema':'study-isolated-QA-files-seal.v1','files':files},indent=2)+'\n')
print(json.dumps({'phase':'complete','stage':str(D),'manifest_sha256':proof['manifest_sha256'],'acceptance_sha256':sha((D/'acceptance.json').read_bytes()),'seals_sha256':sha((D/'SEALS.json').read_bytes()),'QA_sha256':sha(qa),'url':url,'download_filename':proof['download_filename'],'CPU_terminal':True},indent=2))
