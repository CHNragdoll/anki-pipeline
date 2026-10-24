#!/usr/bin/env python3
"""Collect exact, bounded milestone receipts; never read payloads or live QA."""
from pathlib import Path
import datetime,hashlib,json,os,re,stat,subprocess
OUT=Path(__file__).resolve().parent
REPO=OUT.parents[2]
BASE=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime')
BUILD=BASE/'native-bundled-v5-preparation-bd6qsmrr'
MODERN=Path('/private/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-modern-binding-converter-20261018-9xso6ed7')
SOURCE_COMMIT='77caf5cff61f64975856bc2b954f12a8639668fd'
EXPECTED_SEAL='82b106cbce619c5d8c377601e766e8c2cc017cd67d5395e0a6235cb43ef5a519'
CLEANUPS={
 '01-interim-and-old-qa':BASE/'owned-interim-qa-reclaim-20261018-8f_njtpj',
 '02-retired-v2-v3-apkg':BASE/'owned-obsolete-v2-v3-apkg-readonly-20261018-l42eb_37/EXECUTION-y__jie8g',
 '03-retired-sql-cache-archives':BASE/'owned-retired-v2-v3-sql-cache-archive-20261018-7nklf5tb'}
source_records={};outputs=[]
SENSITIVE_KEY=re.compile(r'(^|_)(?:dsn|password|passwd|secret|api_key|access_token|refresh_token|authorization|cookie|connection_string)($|_)',re.I)
URL_DSN=re.compile(r'postgres(?:ql)?://[^\s\"\'<>]+',re.I)
LIBPQ=re.compile(r'\b(?:host|hostaddr|dbname|user|password|passfile|port|sslmode|connect_timeout)\s*=\s*(?:\'[^\']*\'|\"[^\"]*\"|[^\s,;]+)',re.I)
def sha(b):return hashlib.sha256(b).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def need(ok,message):
 if not ok:raise RuntimeError(message)
def identity(p):
 s=p.lstat();need(stat.S_ISREG(s.st_mode) and not p.is_symlink(),'nonregular input: '+str(p));return {k:getattr(s,k) for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']}
def read(p,cap=8*1024*1024):
 p=Path(p);before=identity(p);need(before['st_size']<=cap,'input exceeds small receipt cap: '+str(p));raw=p.read_bytes();need(identity(p)==before,'input changed while reading: '+str(p));source_records[str(p)]={'source_path':str(p),'source_bytes':len(raw),'source_sha256':sha(raw),'source_identity':before};return raw
def value(p):return json.loads(read(p))
def clean_text(text):return LIBPQ.sub('[REDACTED_CONNECTION_FIELD]',URL_DSN.sub('[REDACTED_POSTGRES_DSN]',text))
def clean(v):
 if isinstance(v,dict):return {k:('[REDACTED]' if SENSITIVE_KEY.search(k) else clean(x)) for k,x in v.items()}
 if isinstance(v,list):return [clean(x) for x in v]
 if isinstance(v,str):return clean_text(v)
 return v
def write(rel,raw,source=None,transform='generated'):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True)
 try:fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 except FileExistsError:
  need(not p.is_symlink() and p.is_file() and p.read_bytes()==raw,'existing evidence differs; preserve it: '+rel)
 else:
  with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 record={'output_path':rel,'output_bytes':len(raw),'output_sha256':sha(raw),'transform':transform}
 if source is not None:record.update(source_records[str(Path(source))])
 outputs.append(record);return record
def write_json(rel,v,source=None,transform='generated-summary'):
 return write(rel,(json.dumps(clean(v),ensure_ascii=False,indent=2)+'\n').encode(),source,transform)
def copy_json(source,rel):
 raw=read(source,128*1024);v=json.loads(raw);return write_json(rel,v,source,'sanitized-JSON-receipt')
def copy_text(source,rel):
 raw=read(source,128*1024);return write(rel,clean_text(raw.decode()).encode(),source,'sanitized-text-log')
def summary_parity(p):
 raw=value(p);need(raw['status']=='PASS' and len(raw['books'])==1,'parity receipt not PASS');book=raw['books'][0]
 return {'schema':'study-v5-complete-parity-summary.v1','source_receipt_schema':raw['schema'],'status':raw['status'],'scope':raw['scope'],'source':book['source'],'candidate':book['candidate'],'source_candidate_bytes_unchanged':book['source_candidate_bytes_unchanged'],'sqlite':{k:v for k,v in book['sqlite'].items() if not isinstance(v,list)},'omitted_itemized_SQLite_change_lists':{k:len(v) for k,v in book['sqlite'].items() if isinstance(v,list)},'media':{k:v for k,v in book['media'].items() if not isinstance(v,(list,dict))},'source_collection_bound_to_final_archive':book['source_collection_bound_to_final_archive'],'candidate_collection_bound_to_final_archive':book['candidate_collection_bound_to_final_archive'],'full_payload_or_cache_copied':False,'new_parity_test_run':False}
def git_head():return subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
def main():
 # Check redaction behavior without reading any external account/configuration.
 need(clean({'dsn':'://'.join(['postgresql','u:testvalue@example/db']),'password':'testvalue'})=={'dsn':'[REDACTED]','password':'[REDACTED]'},'key redaction failed')
 need('testvalue' not in clean_text('://'.join(['postgresql','u:testvalue@localhost/db'])+' '+'='.join(['password','testvalue'])),'string redaction failed')
 ignored=subprocess.run(['git','check-ignore',str(OUT/'STATUS.md')],cwd=REPO,capture_output=True,text=True);need(ignored.returncode==0,'target must remain Git ignored')
 before=git_head();need(before==SOURCE_COMMIT,'source milestone HEAD differs')
 existing_status=OUT/'STATUS.md'
 start=(re.search(r'^# v5 本地阶段记录（([^）]+)）',existing_status.read_text()).group(1)
        if existing_status.exists() else now())
 for name,root in CLEANUPS.items():
  for filename in ['RESULT.json','FINAL_SEAL.json']:copy_json(root/filename,'cleanup/'+name+'/'+filename)
  result=value(root/'RESULT.json');need(result['status'].startswith('COMPLETE'),'cleanup receipt incomplete')
 reg=value(BUILD/'REGISTRATION_PROTECTED.json');need(reg['source_commit']==SOURCE_COMMIT and reg['protected_state_exact'] is True and reg['learning_rows']==15177 and len(reg['write_keys'])==3,'registration protection mismatch')
 before_state=value(BUILD/'PROTECTED_BEFORE.json');after_state=value(BUILD/'PROTECTED_AFTER.json');need(before_state==after_state,'protected state receipts differ')
 for f in ['REGISTRATION_PROTECTED.json','PROTECTED_BEFORE.json','PROTECTED_AFTER.json','SEAL.json']:copy_json(BUILD/f,'registration/'+f)
 need(source_records[str(BUILD/'SEAL.json')]['source_sha256']==EXPECTED_SEAL,'operation seal differs')
 cfg=value(BUILD/'CONFIG.json');need(cfg['source_commit']==SOURCE_COMMIT,'configuration source commit mismatch')
 sizes={};payloads={}
 for year,book in [('2026','redbook'),('2027','redbook2027')]:
  packed_path=BUILD/book/'PACKED.json';packed=value(packed_path);need(packed['source_commit']==SOURCE_COMMIT,'PACKED source mismatch');bundles=packed['carrier_bundles']
  summary={k:v for k,v in packed.items() if k not in ['carrier_bundles','carrier_cache']};summary['source_schema']=summary.pop('schema');summary['schema']='study-native-bundled-build-summary.v1';summary['carrier_bundles']={k:v for k,v in bundles.items() if k!='groups'};summary['carrier_bundles']['group_count']=len(bundles['groups']);summary['full_carrier_groups_and_cache_omitted']=True
  write_json('build/'+year+'-PACKED-SUMMARY.json',summary,packed_path,'selected-small-build-summary')
  parity_path=BUILD/book/'ARCHIVE_PARITY.json';parity=summary_parity(parity_path);need(parity['candidate']==packed['package'],'build/parity package pin mismatch');write_json('build/'+year+'-PARITY-SUMMARY.json',parity,parity_path,'selected-complete-parity-summary')
  root=MODERN/('full-v5-modern-'+year);report=value(root/'FULL_REPORT.json');independent=value(root/'INDEPENDENT.json');expected=503725729 if year=='2026' else 482770183
  need(report['source_payload_commit']==SOURCE_COMMIT and report['source']==packed['package'] and report['modern']['bytes']==expected and report['every_SQLite_and_media_byte_equal'] is True and independent==report['independent_verification'] and independent['status']=='PASS','modern full-byte proof mismatch')
  for key in ['all_media_aliases_raw_bytes_size_sha1_exact','all_original_sqlite_bytes_exact','all_original_extra_bytes_exact','source_candidate_before_after_identity_sha_exact']:need(independent[key] is True,'modern independent scope missing')
  for filename in ['FULL_REPORT.json','INDEPENDENT.json']:copy_json(root/filename,'modern/'+year+'/'+filename)
  sizes[year]={'modern_bytes':expected,'old_release_bytes':cfg['books'][book]['source']['bytes'],'modern_sha256':report['modern']['sha256'],'modern_path':report['modern']['path']};payloads[year]=packed['package']
 pgroot=REPO/'output/study-catalog-20261015/native-carrier-bundles-20261018';pg=value(pgroot/'POSTGRESQL.json');need(pg['status']=='PASS' and pg['tests_run']==25 and pg['source_commit']==SOURCE_COMMIT,'PG25 receipt mismatch');log=read(pgroot/'postgresql-registration.log',128*1024).decode();need('Ran 25 tests' in log and log.rstrip().endswith('OK'),'PG25 log mismatch')
 copy_json(pgroot/'POSTGRESQL.json','postgresql/POSTGRESQL.json');copy_text(pgroot/'postgresql-registration.log','postgresql/postgresql-registration.log')
 status=f'''# v5 本地阶段记录（{start}）

本目录仅封存小凭据，绑定源码提交 `{SOURCE_COMMIT}` 和 operation seal `{EXPECTED_SEAL}`。未修改 README、源码、HEAD 或发行；未重新导入 Anki、连接 PostgreSQL、打开 GUI、读取正在增长的 native QA 输出，未复制 SQL/APKG/媒体/完整 carrier cache 或大型 ledger。

| 年份 | modern 候选 | 已发行旧包 | 当前结论 |
|---|---:|---:|---|
| 2026 | {sizes['2026']['modern_bytes']:,} B（503.7 MB） | {sizes['2026']['old_release_bytes']:,} B（399.0 MB） | 仍大于旧包 |
| 2027 | {sizes['2027']['modern_bytes']:,} B（482.8 MB） | {sizes['2027']['old_release_bytes']:,} B（354.1 MB） | 仍大于旧包 |

两本 modern 容器均已有完整独立逐字节对账：SQLite 原字节、每个媒体别名的原字节/大小/哈希及额外成员全部相等，绑定各自封印的 v5 payload；这不表示 modern 与旧发行包整包字节相等。见 [2026 完整报告](modern/2026/FULL_REPORT.json)、[2027 完整报告](modern/2027/FULL_REPORT.json)。**无损转换对账已通过，瘦身目标尚未达到。**

原生完整导入、重复更新/学习记录及真实 GUI/手机验收仍待完成；2026 原生完整 QA 在父任务执行（session 69075），本收集任务没有读取其未完成输出。不得把上述容器字节对账、构建或历史样本视为当前客户端验收通过，候选尚未交付。

已有真实登记保护凭据：仅 3 个登记键、10 个学习表共 15,177 行及其它受保护状态前后完全一致，见 [登记保护](registration/REGISTRATION_PROTECTED.json)。[PostgreSQL 25 项回归](postgresql/POSTGRESQL.json) 是隔离 schema 测试，与真实登记和客户端验收分别记账。

三轮明确授权回收的最终凭据在 [cleanup](cleanup/)：退休派生 APKG 与两个 INTERIM 硬链接按精确范围回收；旧 QA/派生 SQLite 缓存先完整无损 gzip 归档、独立解压逐字节核验，才移除裸副本。不存在的缓存仅记录未操作。gzip 仍保留全部旧字节；未泛化为原始数据删除，也不宣称已退休容器可由 v4 逐字恢复。原始包、当前 v4/v5 输入、真实 profile、GUI clone、备份及媒体均受保护。

[MANIFEST.json](MANIFEST.json) 记录每个来源的完整路径、原始 SHA/大小/稳定身份，以及脱敏副本或摘要的独立 SHA。所有数据库连接串及凭证键均经过收集脚本的删除/脱敏检查。HEAD 保持不变；文件仅位于 ignored output，等待父任务选择保存 Git 节点。
'''
 write('STATUS.md',status.encode())
 # The collector itself is intentionally small and contains no credentials.
 own=Path(__file__).read_bytes();outputs.append({'output_path':Path(__file__).name,'output_bytes':len(own),'output_sha256':sha(own),'transform':'collection-script'})
 for source,record in source_records.items():need(identity(Path(source))==record['source_identity'],'source receipt changed before manifest: '+source)
 for record in outputs:
  raw=(OUT/record['output_path']).read_bytes();need(len(raw)==record['output_bytes'] and sha(raw)==record['output_sha256'],'output pin mismatch');text=raw.decode();need(not URL_DSN.search(text) and not LIBPQ.search(text),'unredacted connection material in output')
 after=git_head();need(after==before,'HEAD changed during collection')
 manifest={'schema':'study-v5-sanitized-small-evidence-manifest.v1','created_at':start,'status':'READY_FOR_GIT_SMALL_EVIDENCE_ONLY','source_commit':SOURCE_COMMIT,'operation_seal_sha256':EXPECTED_SEAL,'HEAD_before':before,'HEAD_after':after,'ignored_output_confirmed':True,'source_records':list(source_records.values()),'files':outputs,'package_size_snapshot':sizes,'payload_packages_from_sealed_reports':payloads,'native_and_GUI_acceptance':'PENDING_NOT_READ_BY_COLLECTOR','slimming_goal':'UNMET_MODERN_CANDIDATES_LARGER_THAN_OLD_RELEASES','source_and_output_SHA_are_distinct_when_summarized_or_sanitized':True,'archive_payloads_SQL_media_carrier_cache_member_ledgers_copied':False,'credentials_or_DSN_collected':False,'new_PG_import_GUI_or_heavy_QA_run':False}
 data=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();fd=os.open(OUT/'MANIFEST.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 print(json.dumps({'output':str(OUT),'manifest_sha256':sha(data),'files_including_manifest':len(outputs)+1,'total_bytes_including_manifest':sum(r['output_bytes'] for r in outputs)+len(data),'HEAD':after,'status':'READY_FOR_GIT_SMALL_EVIDENCE_ONLY'},ensure_ascii=False))
if __name__=='__main__':main()
