"""Count the unchanged modern ZIP representation; never materialize an APKG."""
import hashlib,importlib.util,io,json,os,resource,shutil,sys,time,zipfile,gc,signal
from pathlib import Path
START=time.monotonic(); LIMIT=240; RSS=512*1024**2; FLOOR=1024**3
ROOT=Path(__file__).resolve().parent
BASE=Path('/private/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-modern-binding-converter-20261018-9xso6ed7')
SOURCE=Path('/private/var/folders/0l/1ywxg96x2cd4d5m6qc_xfjzm0000gn/T/study-modern-binding-converter-20261018-9xso6ed7/fixtures/source-legacy.apkg')
EXPECTED='984ebbda2292e50f0f0d6df30c885ae962f3a2ccb738937d5a3587400c391666'
FALLBACK=BASE/'fixtures/fallback.anki2'; FALLBACK_SHA='002eb310edeb31bd32829516752f68b0ea6f027be12e2667cde2dbb33ad500e5'
HELPER=BASE/'stream_convert.py'; HELPER_SHA='6f66f6e5eb87590a154eb10efdd520146e69d28612876ba7530c2ea386698887'
assert hashlib.sha256(HELPER.read_bytes()).hexdigest()==HELPER_SHA
spec=importlib.util.spec_from_file_location('frozen_stream_converter',HELPER);sc=importlib.util.module_from_spec(spec);spec.loader.exec_module(sc)

def guard():
 if time.monotonic()-START>LIMIT:raise TimeoutError('240 second counting budget')
 if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>RSS:raise MemoryError('512 MiB peak RSS budget')
 if shutil.disk_usage(ROOT).free<FLOOR:raise OSError('1 GiB free-space floor')

def deadline_signal(*args):raise TimeoutError('240 second wall alarm')
signal.signal(signal.SIGALRM,deadline_signal);signal.alarm(LIMIT)

def identity(s):return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]

class Counter:
 def __init__(self):self.position=0;self.maximum=0
 def write(self,b):
  guard();self.position+=len(b);self.maximum=max(self.maximum,self.position)
  if self.maximum>sc.MAX_OUTPUT_BYTES:raise ValueError('modern length exceeds cap')
  return len(b)
 def tell(self):return self.position
 def seekable(self):return True
 def seek(self,offset,whence=0):
  self.position=offset if whence==0 else self.position+offset if whence==1 else self.maximum+offset
  if not 0<=self.position<=self.maximum:raise OSError('unexpected count seek')
  return self.position
 def flush(self):pass

# Match the seekable ZipFile layout, including local header rewrites and ZIP64.
for force in (False,True):
 for name in ('0','collection.anki21b','测试'):
  a=io.BytesIO();b=Counter()
  for sink in (a,b):
   with zipfile.ZipFile(sink,'w',allowZip64=True) as z:
    z.comment=b'archive-comment'
    z.writestr(sc.zip_info('meta'),b'xx')
    with z.open(sc.zip_info(name),'w',force_zip64=force) as f:f.write(b'x'*1027)
  assert len(a.getvalue())==b.maximum

class RawSink:
 def __init__(self):self.n=0;self.h=hashlib.sha256()
 def write(self,b):guard();self.n+=len(b);self.h.update(b);return len(b)
 def flush(self):pass

class EncodedSink:
 def __init__(self,dest):
  self.dest=dest;self.n=0;self.h=hashlib.sha256();self.raw=RawSink()
  self.decoder=sc.zstd_binding.ZstdDecompressor().stream_writer(self.raw,closefd=False)
 def write(self,b):
  guard();self.n+=len(b);self.h.update(b)
  if self.n>sc.MAX_MEMBER_ENCODED_BYTES:raise ValueError('encoded member cap')
  if self.dest.write(b)!=len(b) or self.decoder.write(b)!=len(b):raise OSError('short stream write')
  return len(b)
 def flush(self):pass
 def finish(self):self.decoder.flush();self.decoder.close()

report={'schema':'study-v6-modern-virtual-length.v1','status':'INCOMPLETE','APKG_created':False,'source':str(SOURCE),'helper_sha256':HELPER_SHA,'limits':{'seconds':LIMIT,'peak_rss_bytes':RSS,'minimum_free_bytes':FLOOR},'counter_layout_tests':6,'native_or_GUI_acceptance':False}
try:
 report['dependencies']=sc.dependencies(); before=SOURCE.stat()
 assert before.st_size==19949 and not SOURCE.is_symlink()
 with SOURCE.open('rb') as f:assert sc.digest_stream(f)==EXPECTED
 assert sc.pin(FALLBACK)['sha256']==FALLBACK_SHA
 ledger=hashlib.sha256(); counts={'media':0,'frames':0,'extras':0}; categories={}; sink=Counter()
 with SOURCE.open('rb') as sf,zipfile.ZipFile(sf) as incoming:
  names=incoming.namelist();assert len(names)==len(set(names)) and 'collection.anki2' in names
  mapping=json.loads(incoming.read('media'),object_pairs_hook=sc.unique_object)
  for alias in mapping.values():sc.safe_alias(alias)
  assert len(set(mapping.values()))==len(mapping)
  reserved=set(mapping)|{'media','collection.anki2'}
  extras=[]
  for ix,i in enumerate(incoming.infolist()):
   if ix%1000==0:guard()
   if i.filename not in reserved:extras.append(i)
  entries=sc.MediaEntries()
  with zipfile.ZipFile(sink,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as outgoing:
   outgoing.comment=incoming.comment
   outgoing.writestr(sc.zip_info('meta'),sc.PackageMetadata(version=sc.PackageMetadata.VERSION_LATEST).SerializeToString())
   def encode(old,new,reader,size,kind,info=None):
    guard();raw=hashlib.sha256();raw1=hashlib.sha1();n=0
    params=sc.zstd_binding.ZstdCompressionParameters.from_level(9,window_log=27,threads=0,write_content_size=1,write_checksum=1)
    with outgoing.open(sc.zip_info(new,info),'w',force_zip64=True) as dest:
     es=EncodedSink(dest)
     with sc.zstd_binding.ZstdCompressor(compression_params=params).stream_writer(es,size=size,closefd=False) as writer:
      while b:=reader.read(sc.CHUNK):
       guard();n+=len(b);raw.update(b);raw1.update(b)
       if writer.write(b)!=len(b):raise OSError('short compressor input')
     es.finish();assert n==size==es.raw.n and raw.hexdigest()==es.raw.h.hexdigest()
    row={'old':old,'new':new,'raw_bytes':n,'sha256':raw.hexdigest(),'encoded_bytes':es.n,'encoded_sha256':es.h.hexdigest()}
    ledger.update(json.dumps(row,sort_keys=True,separators=(',',':')).encode()+b'\n');counts['frames']+=1
    categories[kind]=categories.get(kind,0)+es.n
    return n,raw1.digest()
   info=incoming.getinfo('collection.anki2')
   with incoming.open(info) as f:encode(info.filename,'collection.anki21b',f,info.file_size,'collection',info)
   with FALLBACK.open('rb') as f,outgoing.open(sc.zip_info('collection.anki2'),'w',force_zip64=True) as dest:sc.copy_stream(f,dest)
   for index,(member,alias) in enumerate(sorted(mapping.items(),key=lambda x:int(x[0]))):
    info=incoming.getinfo(member)
    with incoming.open(info) as f:n,sha1=encode(member,str(index),f,info.file_size,'media',info)
    entries.entries.add(name=alias,size=n,sha1=sha1);counts['media']+=1
    if counts['media']%10000==0:print(json.dumps({'media_checked':counts['media'],'encoded_bytes_so_far':sink.maximum}),flush=True)
   ir=entries.SerializeToString();encode('media','media',io.BytesIO(ir),len(ir),'protobuf-index')
   for info in extras:
    with incoming.open(info) as f,outgoing.open(sc.zip_info(info.filename,info),'w',force_zip64=True) as dest:sc.copy_stream(f,dest)
    counts['extras']+=1
 guard()
 assert sink.maximum==161260, 'count differs from retained actual modern ZIP'
 with SOURCE.open('rb') as f:assert sc.digest_stream(f)==EXPECTED
 assert identity(before)==identity(SOURCE.stat())
 report.update(status='FULL_COUNT_PASS_NOT_A_PACKAGE',expected_modern_zip_bytes=sink.maximum,counts=counts,encoded_payload_categories=categories,ordered_frame_ledger_sha256=ledger.hexdigest(),all_generated_frames_roundtrip_SHA_exact=True,source_before_after_SHA_and_identity_exact=True,source_sha256=EXPECTED,source_identity=identity(before))
except BaseException as error:
 report.update(status='STOPPED',error_type=type(error).__name__,error=str(error))
finally:
 report.update(elapsed_seconds=time.monotonic()-START,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),free_after=shutil.disk_usage(ROOT).free)
 with (ROOT/'REPORT-control.json').open('x') as f:json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 print(json.dumps({k:report[k] for k in ('status','elapsed_seconds','peak_rss_bytes')}|{'expected_modern_zip_bytes':report.get('expected_modern_zip_bytes'),'error':report.get('error')}),flush=True)
if report['status']!='FULL_COUNT_PASS_NOT_A_PACKAGE':raise SystemExit(2)
