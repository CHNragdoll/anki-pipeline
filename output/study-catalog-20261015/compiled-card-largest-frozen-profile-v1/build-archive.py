"""Capture this one frozen experiment; all writes stay in this new archive."""
from pathlib import Path
import base64,datetime,hashlib,json,re,subprocess,sys

D=Path(__file__).resolve().parent;REPO=D.parents[2]
P=Path('/tmp/study-compiled-frozen-profile-reuse-20261017-gs235ciw')
Q=Path('/tmp/study-compiled-2026-v3-frozen-profile-qa-20261017-dP6sM3')
RAW=Path('/Users/apple/Downloads/compiled-largest2026-v3-frozen-profile-reuse-v1-ae0981431390-qa.json')
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def spec(raw):return {'bytes':len(raw),'sha256':sha(raw)}
def write(name,raw):
 path=D/name;assert path.resolve().is_relative_to(D.resolve());path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():assert path.read_bytes()==raw,name
 else:
  with path.open('xb') as stream:stream.write(raw)
 return {'stored_path':name,'stored':spec(raw)}
def checked(path,pin):
 raw=path.read_bytes();assert not path.is_symlink() and sha(raw)==pin,str(path);return raw

def local_original(prefix,name,raw):
 # Preserve any original trailing blanks or multiple ending lines losslessly.
 encoded=name.endswith('.diff') or bool(re.search(rb'(?m)[\t ]+\r?$',raw)) or raw.endswith(b'\n\n')
 stored_name=prefix+'/'+name+('.base64' if encoded else '')
 stored=base64.b64encode(raw)+b'\n' if encoded else raw
 return {'storage':'base64' if encoded else 'local',**spec(raw),**write(stored_name,stored)}

fraw=checked(P/'FROZEN.json','192b2b411fc92dbcf260e4e868b965ecdbc58027c7e7fb3cea8c9abf0929b1fb');freeze=json.loads(fraw)
qraw=checked(Q/'SEALS.json','4131b465d93a3ade3d9e796c03bf00492cd2b4afbe8dbeb87f0e5cc38de3eeb6');qseal=json.loads(qraw)
manifest_raw=checked(Q/'manifest.json','8894765d211c636af0f11e371dcb27e0b6d1bc8ced67e22b4ddaf0d6293bd457');qm=json.loads(manifest_raw)
raw=checked(RAW,'cae40d243dddd44018e7156c7cb4dae7acd29fe9ad929d58398b75aac30afc50');assert len(raw)==23200;actual=json.loads(raw)
source_inputs={};qa_inputs={};source_by_sha={}
derived_names={'baseline-frame.js','baseline-frame.html','candidate-frame.js','candidate-frame.html','adapted-runtime.js'}
for row in freeze['files']:
 value=checked(P/row['path'],row['sha256']);assert len(value)==row['bytes']
 item={'source_path':str(P/row['path']),**spec(value)}
 if row['path'] in derived_names:item.update(storage='derived',derived_name=row['path'])
 else:item.update(local_original('frozen-profile',row['path'],value))
 source_inputs[row['path']]=item;source_by_sha[item['sha256']]=row['path']
assert len(source_inputs)==24
write('frozen-profile/FROZEN.json',fraw)
reused_paths={
 'layout_frame':'output/study-catalog-20261015/compiled-card-largest-layout-cost-v1/layout-cost/candidate-frame.js',
 'resource_edits':'output/study-catalog-20261015/compiled-card-largest-resource-proof-v1/resource-proof/edits.json',
 'phase_frame':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-clock/candidate-frame.js',
 'phase_html':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-clock/candidate-frame.html',
 'phase_config':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-qa/qa-config.literal',
 'phase_parent':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-qa/_qa_compiled_profile_5943ea97a742.html',
 'phase_clock':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-qa/clock-block.html',
 'resource_clock':'output/study-catalog-20261015/compiled-card-largest-resource-proof-v1/qa/clock-block.html',
 'installer':'output/study-catalog-20261015/compiled-card-largest-phase-v1/phase-qa/install.py',
}
reused={key:{'repository_path':name,**spec((REPO/name).read_bytes())} for key,name in reused_paths.items()}
expected_reuse={'layout_frame':'1c14c2f629111e4f912b6a027cbd1fb47feebdd00b8b18c7982f7193318fc84d','resource_edits':'97f2a7730adb1efec9f7a1473b5177b9659a7ab2996299fdf41cce24834afbd2','phase_frame':'4077d2d8cc5e9e4970d48f1409f8279e8f87e8a18a11a6af2764ce46c798ff7f','phase_html':'4f1a9db323dccc4482d8c97dcd6dcb8e76053ead619fa447b3d80d1cd940ccaf','phase_parent':'5943ea97a7428344d55f44dcf2971e6729cf803d00d4f4953e4d83d1be099ea1','installer':'3b6686c6a621cb8a0387b697a6bbff9053ded900090bb073873965c64c95a26c'}
for key,pin in expected_reuse.items():assert reused[key]['sha256']==pin
outputs={name:spec((P/name).read_bytes()) for name in derived_names}
outputs['baseline-parent.html']=spec((Path('/tmp/study-compiled-2026-v3-resource-proof-qa-20261017-bL5wN8')/'_qa_compiled_profile_2b09d6660712.html').read_bytes())
outputs['qa-config.literal']=spec((Q/'qa-config.literal').read_bytes())
outputs[qm['qa_filename']]=qm['files'][qm['qa_filename']]
for name,row in qseal['files'].items():
 value=checked(Q/name,row['sha256']);assert len(value)==row['bytes'];item={'source_path':str(Q/name),**spec(value)}
 if name in outputs:item.update(storage='derived',derived_name=name)
 elif name=='install.py':assert spec(value)=={k:reused['installer'][k] for k in ('bytes','sha256')};item.update(storage='repository',reused_key='installer')
 elif sha(value) in source_by_sha:item.update(storage='source',source_name=source_by_sha[sha(value)])
 else:item.update(local_original('qa',name,value))
 qa_inputs[name]=item
write('qa/SEALS.json',qraw);write('safari-frozen-profile-v1.json',raw)
installed=checked(Path(qm['target_root'])/qm['qa_filename'],qm['files'][qm['qa_filename']]['sha256'])
assert installed==(Q/qm['qa_filename']).read_bytes()
write('installation-readback.json',(json.dumps({'schema':'study-isolated-QA-readback.v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'parent_QA':{'path':str(Path(qm['target_root'])/qm['qa_filename']),**spec(installed)},'root_performed_installation_and_Safari':True,'archiver_installed_or_opened_UI':False,'large_assets_not_rehashed':True},indent=2)+'\n').encode())
run=actual['validation_runs'][0];stats=run['compiled_handle_stats'][0];layout=run['layout_cost_status'];phases=actual['phase_clock'];point={v['label']:v['at'] for v in phases if v['kind']=='point'};author11=next(v for v in phases if v['kind']=='span' and v['label']=='author-execute' and v['ordinal']==11);batch=next(v for v in phases if v['kind']=='span' and v['label']=='batch-finally-refresh')
assert actual['first_front_complete_observed_ms']==1872 and actual['first_back_elapsed_ms']==7419 and stats['invalid'] is None
summary={'schema':'study-largest-frozen-profile-observation.v1','status':'FULL_BACK_OBSERVED_NOT_SECONDS_TARGET_OR_CAUSAL_SPEEDUP_PROOF','raw':{'path':'safari-frozen-profile-v1.json',**spec(raw)},'observed_parent_clock_ms':{'first_front':1872,'first_full_back_elapsed':7419,'author11_inclusive':author11['elapsed'],'batch_finally_span':batch['elapsed'],'full_gate_interval':point['full-gate-complete']-point['full-gate-start']},'aftergate':{'compiled':stats,'initial_numbering_claim':run['initial_numbering_claim_status'],'layout_scalar_snapshot':layout},'limits':['One uncontrolled Safari wall-clock sample, not cold-cache/paint/stable performance evidence.','The difference from the prior11.808s sample is not attributed to this candidate.','Nested/parallel wall durations cannot be added; batch span and layout aggregate have different sampling boundaries.','Root reported complete screenshot visually checked and owned QA window closed; archiver ran no UI.','No per-card full-content equivalence or mobile/Anki acceptance is inferred from scalar stats.'],'original_fullgate10s_source_resource_pins_preserved':True,'formal_promoted':False}
write('observation-summary.json',(json.dumps(summary,ensure_ascii=False,indent=2)+'\n').encode())
external=[{'name':item['name'],'bytes':item['bytes'],'sha256':item['sha256'],'source_path':str(Path(qm['target_root'])/item['name']),'copied':False,'rehash_in_this_archive':False,'basis':'existing frozen QA input pin, original dry-run, same pin in actual capture'} for item in qm['readonly_assets'] if item['sha256'] in {'746ce538774979ca1108ba5b3233ae5871a3f0ee6d5e232fb93a65b9f7af68cc','7a870e83fa2c7efb2430269c34c192424fb6d9cd7ec3ca097f70b9b8eda0d67f','e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc'}]
write('ARCHIVE.md',b'# Frozen profile reuse: one complete Safari sample\n\nRaw Safari capture is byte-exact. Front1872ms and first complete back7419ms; compiled invalid=null,1800groups/4303members/201Bank and accepted numbering claim were observed after the original full gate. This is not seconds-level acceptance, a stable-latency benchmark or proof that the difference from the prior11.808s sample was caused by this candidate. Inclusive phase/layout intervals are not additive. Root performed the actual browser run and visually checked the complete screenshot.\n\nThe original24-file freeze and all QA source pins are classified as exact local bytes, strict base64, shared repository bytes or exact derived outputs. No49MB HTML or22MB profile is copied or rehashed. Both sealed diffs and any original trailing whitespace are base64-encoded without altering original bytes.\n\nRun verify-archive.py for SHA/size, raw result and exact reconstruction/inverse of FRAME5edits, runtime2edits, complete frameHTML/config and parentQA. reconstruct.py only returns small strings and hashes. run-small-contracts.py is optional: seven frozen small44KB/17KB fixture groups run in an owned temporary folder, with a single reversible jsdom-path portability edit. None of these tools deploys or opens a browser.\n')
m={'schema':'largest-frozen-profile-compact-archive.v1','status':summary['status'],'source_freeze':{'source_path':str(P/'FROZEN.json'),**spec(fraw),'declared_files':24},'QA_freeze':{'source_path':str(Q/'SEALS.json'),**spec(qraw),'declared_files':len(qseal['files'])},'candidate_QA_filename':qm['qa_filename'],'source_inputs':source_inputs,'qa_inputs':qa_inputs,'reused_inputs':reused,'derived_outputs':outputs,'external_large_assets_not_copied':external,'local_files':{}}
def save_manifest():
 m['local_files']={str(p.relative_to(D)):spec(p.read_bytes()) for p in sorted(D.rglob('*')) if p.is_file() and p.name!='archive-manifest.json' and '__pycache__' not in p.parts}
 (D/'archive-manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
save_manifest()
r=subprocess.run([sys.executable,'-B',str(D/'verify-archive.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr
write('archive-verification.log',r.stdout.encode())
r=subprocess.run([sys.executable,'-B',str(D/'run-small-contracts.py'),'--node','/opt/homebrew/bin/node'],capture_output=True,text=True);assert r.returncode==0,r.stderr
write('small-contracts-replay.log',r.stdout.encode())
save_manifest()
r=subprocess.run([sys.executable,'-B',str(D/'verify-archive.py')],capture_output=True,text=True);assert r.returncode==0,r.stderr
print(r.stdout,end='');print(json.dumps({'archive':str(D),'manifest_sha256':sha((D/'archive-manifest.json').read_bytes()),'raw_sha256':sha(raw),'source_freeze_files':24,'local_files':len(m['local_files']),'total_local_bytes':sum(v['bytes'] for v in m['local_files'].values())+(D/'archive-manifest.json').stat().st_size,'CPU_terminal':True},indent=2))
