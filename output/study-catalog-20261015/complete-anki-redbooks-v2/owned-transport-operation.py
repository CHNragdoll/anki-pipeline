"""Owned one-time transport migration; all semantic assets are already authenticated.
Uses the normal exporter's pure native binder, never a second card generator.
"""
from pathlib import Path
import copy,hashlib,itertools,json,os,shutil,sqlite3,sys,time,zipfile
sys.path.insert(0,'/Users/apple/Documents/PyCharm/Anki/anki_rebuild')
from anki_pipeline import study_compiled_native as native
from anki_pipeline import study_catalog_native_delivery as delivery
from anki_pipeline.study_apkg_repack import repack_apkg
BASE=Path(__file__).resolve().parent
V1=Path('/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-native-delivery-preparation-v4-20261017-q4e4hfse')
PARITY=Path('/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-native-apkg-parity-20261017-vgc2bka1')
SOURCES=Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/output/inline-disclosures-20261015')
CONFIG={2026:('redbook','0000','2026-PARITY-v3.json','99ab1360d3a4c0c5401b05d122046f852b6440c869352af0b4baaa92bbda2547'),2027:('redbook2027','0001','2027-PARITY-v4.json','d66a3d09fb14b762908ecc3cca2b6e541783c8bc39eef17e319bcd01f791ad57')}
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,value):
 with Path(path).open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def ro(path):return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
def build(year):
 start=time.monotonic();bid,part,parity_name,parity_pin=CONFIG[year]
 plan=json.loads((BASE/'PLAN.json').read_text());assert delivery.native_host_sha256()==plan['native_host_sha256']
 raw=(PARITY/parity_name).read_bytes();assert hashlib.sha256(raw).hexdigest()==parity_pin
 proof=json.loads(raw);assert proof['status']=='PASS';proof=proof['books'][0]
 reg=json.loads((BASE/'REGISTERED.json').read_text());assert reg['plan_sha256']==plan['sha256']
 assert json.loads((BASE/'REGISTRATION_JOURNAL/COMMITTED.json').read_text())==reg
 versions=reg['native_versions'][bid];versions={kind:{int(k):v for k,v in values.items()} for kind,values in versions.items()}
 original=SOURCES/str(year)/'collection.anki2';previous=V1/'EXPORT_BATCH/.partial'/part/'collection.anki2'
 assert str(previous)==proof['candidate_collection_bound_to_final_archive']['path'];assert sha(previous)==proof['candidate_collection_bound_to_final_archive']['sha256']
 assert sha(original)==proof['source_collection_bound_to_final_archive']['sha256']
 out=BASE/str(year);out.mkdir(mode=0o700)
 candidate=out/'collection.anki2'
 with previous.open('rb') as src,candidate.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
 bootstrap=native.native_bootstrap_source().encode();bootstrap_name='_study_native_bootstrap_'+hashlib.sha256(bootstrap).hexdigest()+'.js'
 bootstrap_version=native._bootstrap_parts()[1]
 identities={row['note_id']:row['id'] for row in plan['books'][bid]}
 checked=0;original_fields_checked=0;models_after={};descriptor_hash=hashlib.sha256()
 with ro(original) as old,ro(previous) as prior,sqlite3.connect(candidate) as new:
  old_models=json.loads(old.execute('select models from col').fetchone()[0]);new_models=json.loads(prior.execute('select models from col').fetchone()[0])
  columns=[x[1] for x in old.execute('pragma table_info(notes)')];assert columns==[x[1] for x in prior.execute('pragma table_info(notes)')]
  ix={name:i for i,name in enumerate(columns)};missing=object()
  for before,was in itertools.zip_longest(old.execute('select * from notes order by id'),prior.execute('select * from notes order by id'),fillvalue=missing):
   assert before is not missing and was is not missing
   nid=before[ix['id']];assert was[ix['id']]==nid
   if nid not in versions['notes']:continue
   mid=before[ix['mid']];assert mid==was[ix['mid']]
   fields=before[ix['flds']].split('\x1f');v1fields=was[ix['flds']].split('\x1f');assert v1fields[:-1]==fields
   descriptor=json.loads(v1fields[-1]);assert descriptor['id']==identities[nid]
   descriptor_hash.update(nid.to_bytes(8,'big'));descriptor_hash.update(v1fields[-1].encode())
   descriptor['bootstrap_version']=bootstrap_version
   model=copy.deepcopy(old_models[str(mid)])
   note={'id':descriptor['id'],'field_names':[f['name'] for f in model['flds']],'fields':fields,'model':model,'payload':dict(zip(columns,before)),'content_mod':before[ix['mod']]}
   bound=native.bind_native_delivery(note,descriptor,bootstrap_name=bootstrap_name,model_mod=versions['models'][mid],note_mod=versions['notes'][nid])
   assert native.restore_native_source_fields(bound)==fields
   if mid in models_after:assert models_after[mid]==bound['model']
   else:models_after[mid]=bound['model']
   new.execute('update notes set flds=?,mod=?,usn=-1 where id=?',('\x1f'.join(bound['fields']),versions['notes'][nid],nid))
   checked+=1;original_fields_checked+=len(fields)
  assert checked==len(versions['notes'])==len(identities);assert set(models_after)==set(versions['models'])
  for mid,model in models_after.items():new_models[str(mid)]=model
  new.execute('update col set models=?',(json.dumps(new_models,ensure_ascii=False,separators=(',',':')),))
  new.commit();assert new.execute('pragma integrity_check').fetchall()==[('ok',)]
 with candidate.open('rb') as stream:os.fsync(stream.fileno())
 archive=Path(proof['candidate']['path']);assert archive==V1/f'EXPORT_BATCH/{year}-RedBook-Complete-Compiled.apkg'
 with zipfile.ZipFile(archive) as z:
  media=json.loads(z.read('media'));old_boots=[(k,v) for k,v in media.items() if v.startswith('_study_native_bootstrap_')]
  assert len(old_boots)==1;boot_member,old_boot=old_boots[0];assert old_boot!=bootstrap_name
  with zipfile.ZipFile(proof['source']['path']) as original_archive:assert old_boot not in set(json.loads(original_archive.read('media')).values())
  media[boot_member]=bootstrap_name
 package=out/f'{year}-RedBook-Complete-Compiled-Schema-Compatible.apkg'
 receipt=repack_apkg(archive,package,{'collection.anki2':candidate,'media':json.dumps(media,ensure_ascii=False,separators=(',',':')).encode(),boot_member:bootstrap},expected_source_sha256=proof['candidate']['sha256'])
 directory_fd=os.open(out,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(directory_fd)
 finally:os.close(directory_fd)
 result={'schema':'study-native-schema-compatible-complete-rebind.v1','book_id':bid,'year':year,'status':'PACKED_AWAITING_INDEPENDENT_PARITY_AND_NATIVE_IMPORT','plan_sha256':plan['sha256'],'host_sha256':plan['native_host_sha256'],'registered_versions_used':True,'compiled_notes':checked,'original_field_values_roundtrip_exact':original_fields_checked,'field_schema_unchanged':True,'prior_delivery_descriptor_stream_sha256':descriptor_hash.hexdigest(),'only_descriptor_change':'bootstrap_version','bootstrap_version':bootstrap_version,'bootstrap':{'alias':bootstrap_name,'sha256':hashlib.sha256(bootstrap).hexdigest(),'bytes':len(bootstrap)},'collection':{'path':str(candidate),'sha256':sha(candidate),'bytes':candidate.stat().st_size},'package':{'path':str(package),'sha256':sha(package),'bytes':package.stat().st_size},'repack':receipt,'prior_archive_parity_report_sha256':parity_pin,'elapsed_seconds':round(time.monotonic()-start,3),'PG_writes':False,'Anki_user_profile_access':False,'full_content_recompiled':False}
 save(out/'PACKED.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)
if __name__=='__main__':build(int(sys.argv[1]))
