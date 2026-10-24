"""One authorized interim-v4 complete format-only conversion and full parity."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,os,resource,shutil,time,zipfile
import stream_convert as sc
import independent_verify as iv
ROOT=Path(__file__).resolve().parent
SOURCE=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-authored-filter-v4-9o9w56zb/2026/2026-RedBook-Complete-Compiled-Author-Fixed.apkg')
SHA='2f1ffb556387c6557bcff5024fe1652cb3366d1fe3373919e5202262eeeeeb78'
SIZE=893171145
FALLBACK=ROOT/'fixtures/fallback.anki2'
FALLBACK_SHA='002eb310edeb31bd32829516752f68b0ea6f027be12e2667cde2dbb33ad500e5'
OUT=ROOT/'full-v4-modern-INTERIM'
RESERVE=2*1024**3
CAP=1300000000
LABEL='INTERIM_V4_CONTAINER_ONLY_NOT_DELIVERABLE'
def emit(phase,**extra):print(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'phase':phase,**extra}),flush=True)
start=time.monotonic()
assert not OUT.exists() and SOURCE.stat().st_size==SIZE
free=shutil.disk_usage(ROOT).free
required=CAP+sc.MAX_MEMBER_ENCODED_BYTES+RESERVE+64*1024**2
if free<required:raise OSError('cannot meet explicit whole-run private budget and 2GiB reserve')
with zipfile.ZipFile(SOURCE) as z:
 infos=z.infolist();names={i.filename for i in infos}
 assert len(infos)==len(names)<=sc.MAX_ENTRIES and not any(i.flag_bits&1 for i in infos)
 with z.open('media') as f:m=json.loads(sc.bounded_read(f,sc.MAX_INDEX),object_pairs_hook=sc.unique_object)
 members=set(m);assert len(m)==len(set(m.values())) and members<=names
 for alias in m.values():sc.safe_alias(alias)
 assert all(z.getinfo(k).file_size<=0xffffffff for k in members)
 reserved=members|{'media','collection.anki2'}
 extras=[i.filename for i in infos if i.filename not in reserved]
 assert not extras
 entries=sc.MediaEntries()
 for key,alias in m.items():entries.entries.add(name=alias,size=z.getinfo(key).file_size,sha1=b'\0'*20)
 index_size=entries.ByteSize();assert index_size<=sc.MAX_INDEX
 preflight={'schema':'study-modern-binding-full-preflight.v1','at':datetime.now(timezone.utc).isoformat(),'product_status':LABEL,'authorized':True,'source':{'path':str(SOURCE),'bytes':SIZE,'sha256':SHA},'source_members':len(infos),'media_count':len(m),'extra_count':len(extras),'all_aliases_safe_without_rename':True,'all_media_sizes_uint32':True,'future_protobuf_index_bytes':index_size,'raw_member_sum':sum(i.file_size for i in infos),'largest_raw_member':max(i.file_size for i in infos),'output_cap_bytes':CAP,'member_temp_cap_bytes':sc.MAX_MEMBER_ENCODED_BYTES,'minimum_live_free_bytes':RESERVE,'required_free_before':required,'actual_free_before':free,'budget_met':True,'dependencies':sc.dependencies()}
 sc.dump_new(ROOT/'FULL_PREFLIGHT.json',preflight)
del entries,infos,m,names,members,reserved
emit('full-conversion-start',budget=preflight['actual_free_before'],cap=CAP,reserve=RESERVE)
conversion_start=time.monotonic()
result=sc.convert(SOURCE,SHA,SIZE,OUT,FALLBACK,FALLBACK_SHA,reserve=RESERVE,max_output_bytes=CAP)
conversion_seconds=time.monotonic()-conversion_start
emit('conversion-complete-independent-all-member-byte-parity-start',modern=result['modern'],seconds=conversion_seconds)
verify_start=time.monotonic()
verified=iv.verify(SOURCE,SHA,SIZE,Path(result['modern']['path']),result['modern']['sha256'],result['modern']['bytes'],FALLBACK,FALLBACK_SHA)
verify_seconds=time.monotonic()-verify_start
sc.dump_new(OUT/'INDEPENDENT.json',verified)
report={'schema':'study-modern-binding-full-result.v1','status':'PASS','product_status':LABEL,'delivered':False,'reason_not_deliverable':'Interim v4 source still lacks the later corrected browser fallback; this task changes only the package container.','source':result['source'],'modern':result['modern'],'source_identity_before':result['source_identity_before'],'source_identity_after':result['source_identity_after'],'source_whole_SHA_before_after_equal':True,'conversion':result,'independent_verification':verified,'all_raw_SQLite_and_media_bytes_preserved':True,'all_extras_preserved':True,'every_member_stream_byte_compared':True,'actual_cli_sample_crosscheck':'ACTUAL_SAMPLES.json: SQLite and three largest carrier window27 frames full CLI decoded byte-equal before this run; same pinned binding/parameters.','conversion_seconds':round(conversion_seconds,6),'full_independent_verification_seconds':round(verify_seconds,6),'total_seconds':round(time.monotonic()-start,6),'saved_package_bytes':SIZE-result['modern']['bytes'],'saved_package_percent':round(100*(SIZE-result['modern']['bytes'])/SIZE,6),'peak_rss_bytes_macos':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'free_after':shutil.disk_usage(ROOT).free,'no_PG_GUI_native_import_or_SQL_engine':True,'runtime_source_or_media_content_modified':False,'operation':sc.pin(Path(__file__)), 'completed_at':datetime.now(timezone.utc).isoformat()}
sc.dump_new(ROOT/'FULL_REPORT.json',report)
sc.dump_new(OUT/(LABEL+'.json'),{'product_status':LABEL,'delivered':False,'full_report':sc.pin(ROOT/'FULL_REPORT.json'),'format_only':True})
emit('complete',report=sc.pin(ROOT/'FULL_REPORT.json'),modern=result['modern'],size_saved=report['saved_package_bytes'],peak_rss_bytes=report['peak_rss_bytes_macos'])
