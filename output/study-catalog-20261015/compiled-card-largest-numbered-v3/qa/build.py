from pathlib import Path
import datetime,hashlib,json,re,subprocess
D=Path(__file__).resolve().parent
S=Path('/tmp/study-compiled-largest-v3-setup-20261017-4ND3gV')
OLD=Path('/tmp/study-compiled-2026-max-bank-v2-20261017-u22eiB')
F=Path('/tmp/study-largest-numbered-profile-v3-20261017-44x2a3q0/profile')
BODY=Path('/tmp/study-native-ordinal-prepare-20261017-nzd88w9n/result/replay-input-numbered.html')
sha=lambda b:hashlib.sha256(b).hexdigest()
now=lambda:datetime.datetime.now(datetime.timezone.utc).isoformat()
def checked(p,pin,size=None):
 assert p.is_file() and not p.is_symlink(),str(p)
 raw=p.read_bytes();assert sha(raw)==pin,str(p)
 if size is not None:assert len(raw)==size,str(p)
 return raw
oldManifestRaw=checked(OLD/'manifest.json','0f7e814c9dac5c2c37cf727a87589c75e2e1a909c4faf44985ee478f825ef084')
m=json.loads(oldManifestRaw);root=Path(m['target_root'])
formal=checked(root/'index.html',m['official_index_sha256']);assert formal==(S/'official-2026-index.html').read_bytes()
indices={str(root.parent/(name+'/index.html')):sha((root.parent/(name+'/index.html')).read_bytes()) for name in ['master-redbook-web-v3','master-redbook2027-web-v3','master-liuxiaoyan2027-web-v3']}
oldFrameRaw=checked(OLD/'candidate-frame.js','9fce1ad450ed0c602a1cda0d65f2b4f8d20fdd1975d837497e8883596715e918');oldFrame=oldFrameRaw.decode()
profileRaw=checked(F/'profile.json','7a870e83fa2c7efb2430269c34c192424fb6d9cd7ec3ca097f70b9b8eda0d67f',22459697)
bodyRaw=checked(BODY,'746ce538774979ca1108ba5b3233ae5871a3f0ee6d5e232fb93a65b9f7af68cc',49390544)
anchorsRaw=checked(F/'anchors.json','c59caed58a41ad3488c8f791ce98c8e386bb40568c5952cda219fef70c0c3c33')
anchors=json.loads(anchorsRaw);profile=json.loads(profileRaw)
assert anchors['profileSha256']==sha(profileRaw) and anchors['htmlSha256']==sha(bodyRaw)
assert profile['bindings']==anchors['bindings'] and profile['schema']==anchors['schema'] and profile['version']==anchors['version']
oldAnchors=json.loads((OLD/'anchors.json').read_bytes());checkBindings=dict(anchors['bindings']);checkBindings['derivedHTMLSha256']=oldAnchors['bindings']['derivedHTMLSha256'];assert checkBindings==oldAnchors['bindings']
counts={k:len(profile.get(k,[])) for k in ['nodeBindings','projectionWrappers','residualWrappers','panels','groups','bankRecords','readerLinks','historySlots']}
assert counts==m['metadata']['cases'][next(iter(m['metadata']['cases']))]['compiled_profile_counts'];del profile
nameProfile='_qa_compiled_largest_v3_profile_'+sha(profileRaw)+'.json';nameBody='_qa_compiled_largest_v3_body_'+sha(bodyRaw)+'.html'
for name,raw in [(nameProfile,profileRaw),(nameBody,bodyRaw)]:
 assert not(root/name).exists();(D/name).write_bytes(raw)
(D/'anchors.json').write_bytes(anchorsRaw)
marker='const compiledAssets=';at=oldFrame.index(marker)+len(marker);oldTable,n=json.JSONDecoder().raw_decode(oldFrame[at:]);table=json.loads(json.dumps(oldTable));CARD=next(iter(table['entries']));assert CARD=='ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576'
entry=table['entries'][CARD];entry['profile']={'src':nameProfile,'sha256':sha(profileRaw)};entry['html']={'src':nameBody,'sha256':sha(bodyRaw)};entry['anchors']={k:anchors[k] for k in ['schema','version','bindings']}
oldLiteral=marker+oldFrame[at:at+n]+';';newLiteral=marker+json.dumps(table,separators=(',',':'),ensure_ascii=False)+';';assert oldFrame.count(oldLiteral)==1;frame=oldFrame.replace(oldLiteral,newLiteral,1);assert frame.replace(newLiteral,oldLiteral,1)==oldFrame
(D/'candidate-frame.js').write_text(frame)
edits=json.loads((OLD/'candidate-edits.json').read_bytes());assert len(edits)==11 and edits[0][1].count(oldLiteral)==1;edits[0][1]=edits[0][1].replace(oldLiteral,newLiteral,1);(D/'candidate-edits.json').write_text(json.dumps(edits,indent=2)+'\n')
inverse=frame
for before,after in reversed(edits):assert inverse.count(after)==1;inverse=inverse.replace(after,before,1)
sourceRaw=checked(S/'source-frame.c7.js','c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02');assert inverse.encode()==sourceRaw
sourceHTML=checked(S/'source-frame.8b.html','8b6e59ff2457dc7cd2cfefbe46d81404dc55ce8c2dd941b040a7ac5ac9de1710').decode();assert sourceHTML.count(sourceRaw.decode())==1
html=sourceHTML.replace(sourceRaw.decode(),frame,1);assert html.replace(frame,sourceRaw.decode(),1)==sourceHTML
(D/'candidate-frame.html').write_text(html)
oldcfg=(S/'official-2026-config.literal').read_bytes();cfg=json.loads(oldcfg);oldhtml=cfg['sharedFrame']['html'];enc=lambda s:json.dumps(s,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').encode();assert oldcfg.count(enc(oldhtml))==1;newcfg=oldcfg.replace(enc(oldhtml),enc(html),1);assert json.loads(newcfg)=={**cfg,'sharedFrame':{**cfg['sharedFrame'],'html':html}}
(D/'qa-config.literal').write_bytes(newcfg)
bundle={'schema':'study-largest-numbered-data-QA-update.v1','previous_manifest_sha256':sha(oldManifestRaw),'profile_source':{'path':str(F/'profile.json'),'sha256':sha(profileRaw),'bytes':len(profileRaw)},'HTML_source':{'path':str(BODY),'sha256':sha(bodyRaw),'bytes':len(bodyRaw)},'anchors_source':{'path':str(F/'anchors.json'),'sha256':sha(anchorsRaw),'bytes':len(anchorsRaw)},'frame_sha256':sha(frame.encode()),'only_external_profile_HTML_and_derived_binding_changed':True,'asset_table':table};(D/'bundle.json').write_text(json.dumps(bundle,indent=2)+'\n')
collector=(OLD/'collector.js').read_text();assert 'inspectFailedTarget' not in collector and 'failure_probe' not in collector
start=collector.index(' const metadata=')+len(' const metadata=');oldMeta,used=json.JSONDecoder().raw_decode(collector[start:]);meta=json.loads(json.dumps(oldMeta));meta.update({'case_id':'compiled-largest-redbook2026-v3','candidate_identity':'common-eleven-edit-runtime-e56-numbered-HTML-profile-data-only','candidate_frame_sha256':sha(frame.encode()),'bundle_sha256':sha((D/'bundle.json').read_bytes()),'numbered_HTML_sha256':sha(bodyRaw),'compiled_profile_sha256':sha(profileRaw)})
newMeta=json.dumps(meta,separators=(',',':'));newcollector=collector[:start]+newMeta+collector[start+used:];assert newcollector[:start]+collector[start:start+used]+newcollector[start+len(newMeta):]==collector
block=('<script id="study-compiled-profile-qa-clock">\n'+newcollector+'\n</script>\n').encode();oldTag=re.search(br'<script defer src="_study_library_[a-f0-9]+\.js"></script>',formal).group(0);newTag=(S/'classic-defer-host-tag.html').read_bytes();assert formal.count(oldcfg)==1 and formal.count(oldTag)==1
qa=formal.replace(oldcfg,newcfg,1).replace(oldTag,block+newTag,1);assert qa.replace(block,b'',1).replace(newTag,oldTag,1).replace(newcfg,oldcfg,1)==formal
nameQA='_qa_compiled_profile_'+sha(qa)[:12]+'.html';assert not(root/nameQA).exists();(D/nameQA).write_bytes(qa);(D/'collector.js').write_text(newcollector);(D/'clock-block.html').write_bytes(block)
readonly=m['readonly_assets']+[{'name':name,**entry} for name,entry in m['files'].items()]
assert len({item['name'] for item in readonly})==len(readonly)
for item in readonly:checked(root/item['name'],item['sha256'],item['bytes'])
installer=(OLD/'install.py').read_text();oldDescription='Default read-only; --apply exclusively creates one new pinned profile and one new QA; existing assets remain read-only.';newDescription='Default read-only; --apply exclusively creates a new pinned numbered body, profile and QA; existing assets remain read-only.';assert installer.count(oldDescription)==1;installer=installer.replace(oldDescription,newDescription,1);(D/'install.py').write_text(installer)
sourceInputs={str(OLD/'manifest.json'):sha(oldManifestRaw),str(F/'profile.json'):sha(profileRaw),str(F/'anchors.json'):sha(anchorsRaw),str(BODY):sha(bodyRaw)}
for p in [D/'anchors.json',D/'candidate-frame.js',D/'candidate-edits.json',D/'bundle.json',D/'collector.js']:sourceInputs[str(p)]=sha(p.read_bytes())
manifest={k:m[k] for k in ['schema','target_root','official_index_sha256','official_host_sha256','candidate_host_filename','candidate_host_sha256','candidate_host_bytes']};newFiles={nameProfile:profileRaw,nameBody:bodyRaw,nameQA:qa};url=m['cold_only_url'].replace(m['qa_filename'],nameQA)
manifest.update({'created_at':now(),'asset_files':[nameProfile,nameBody],'qa_filename':nameQA,'files':{n:{'sha256':sha(raw),'bytes':len(raw)} for n,raw in newFiles.items()},'readonly_assets':readonly,'installer_sha256':sha(installer.encode()),'frozen_source_inputs':sourceInputs,'metadata':meta,'cold_only_url':url,'digest_observer_url':url,'urls':{CARD:url},'no_installation_or_UI':True});(D/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'phase':'manifest-ready','stage':str(D),'manifest_sha256':sha((D/'manifest.json').read_bytes()),'url':url,'download_filename':meta['case_id']+'-'+CARD[:12]+'-qa.json'},indent=2),flush=True)
for f in ['candidate-frame.js','collector.js']:subprocess.run(['/opt/homebrew/bin/node','--check',str(D/f)],check=True)
r=subprocess.run(['/tmp/anki-study-runtime-20261015/bin/python','-B',str(D/'install.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr;(D/'dry-run.json').write_text(r.stdout)
assert indices=={path:sha(Path(path).read_bytes()) for path in indices}
proof={'schema':'study-max-numbered-HTML-profile-QA-acceptance.v1','created_at':now(),'previous_v2_and_diagnostic_QA_and_assets_preserved':True,'profile_sha256':sha(profileRaw),'profile_bytes':len(profileRaw),'HTML_sha256':sha(bodyRaw),'HTML_bytes':len(bodyRaw),'anchors_sha256':sha(anchorsRaw),'profile_counts':counts,'frame_data_delta':'new profile/numbered HTML descriptors plus derivedHTMLSha256 binding; runtime/source/module/other bindings unchanged','eleven_edits_inverse_exact_to_c7':True,'frame_HTML_inverse_exact_to_source8b':True,'parent_HTML_inverse_exact_to_official_index':True,'runtime_e56_owner_d9f_fullgate10s_authors_same':True,'parent_collector_same_except_case_identity_and_data_pins':True,'no_9951_per_error_reader':True,'optional_scalar_validation_same':True,'installer_logic_same_only_docstring_changed':True,'all_existing_resources_readonly_sha_size_validated':True,'three_formal_index_hashes_unchanged':indices,'new_files':3,'manifest_sha256':sha((D/'manifest.json').read_bytes()),'QA_sha256':sha(qa),'frame_sha256':sha(frame.encode()),'frame_html_sha256':sha(html.encode()),'syntax_passed':True,'installer_default_dry_run_exit':0,'url':url,'download_filename':meta['case_id']+'-'+CARD[:12]+'-qa.json','installed':False,'browser_run':False,'performance_or_full_author_pass_claimed':False,'cpu_terminal':True};(D/'acceptance.json').write_text(json.dumps(proof,indent=2)+'\n')
(D/'README.md').write_text('# Largest2026 numbered data QA v3\n\nPrepared and dry-run only. Only new numbered HTML, re-extracted profile, and parent QA are planned. Existing runtimee56 and every old QA/resource remain read-only. Eleven common FRAME edits, authors, source/module guards,64MiB admission and10s fullgate remain unchanged. Normal first-front/full-back/manual-flip clock and optional scalar public-handle verifier are copied from v2; no9951 per-error reader. No performance or browser pass is asserted.\n\nRoot-reviewed installation only:\n`/tmp/anki-study-runtime-20261015/bin/python -B '+str(D)+'/install.py --apply`\n\nURL/download name in acceptance.json.\n')
files={p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(D.iterdir()) if p.is_file() and p.name!='SEALS.json'};(D/'SEALS.json').write_text(json.dumps({'schema':'study-isolated-QA-files-seal.v1','files':files},indent=2)+'\n')
print(json.dumps({'phase':'complete','stage':str(D),'manifest_sha256':proof['manifest_sha256'],'acceptance_sha256':sha((D/'acceptance.json').read_bytes()),'seals_sha256':sha((D/'SEALS.json').read_bytes()),'frame_sha256':proof['frame_sha256'],'frame_html_sha256':proof['frame_html_sha256'],'qa_sha256':proof['QA_sha256'],'url':url,'download_filename':proof['download_filename'],'dryrun_exit':0,'cpu_terminal':True},indent=2))
