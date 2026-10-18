import sys,os,time,json,hashlib,sqlite3,struct
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;CLONE=HERE/'collection.anki2'
APP=Path('/Applications/Anki.app/Contents/Resources/app_packages');sys.path.insert(0,str(APP))
SQL='select id, field_at_index(flds, 0) from notes where csum=? and mid=?'
MID=1552983369;RAW_SHA='72bc2a741150f1b222e7e144259cff8e45331376947d7c2c4fedc402f7127e02'
phase=sys.argv[1];started=time.monotonic()
def save(name,value):
 with (HERE/name).open('x') as f:f.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n');f.flush();os.fsync(f.fileno())
def timed(label,fn):
 print('BEGIN',label,flush=True);t=time.perf_counter();value=fn();s=time.perf_counter()-t;print('END',label,s,flush=True);return value,s
def ident(name):return '"'+name.replace('"','""')+'"'
def protected_hash():
 db=sqlite3.connect(CLONE.as_uri()+'?mode=ro',uri=True);db.text_factory=bytes;result={}
 try:
  for table in ('notes','cards','revlog'):
   names=[r[1].decode() for r in db.execute('pragma table_info('+ident(table)+')')]
   digest=hashlib.sha256(json.dumps(names,separators=(',',':')).encode());count=0
   expr=','.join('typeof('+ident(n)+'),'+ident(n) for n in names)
   for row in db.execute('select '+expr+' from '+ident(table)+' order by id'):
    digest.update(b'row:');count+=1
    for typ,v in zip(row[::2],row[1::2]):
     value=v if isinstance(v,bytes) else b'' if v is None else repr(v).encode('ascii')
     digest.update(typ+b':'+struct.pack('>Q',len(value)));digest.update(value)
   result[table]={'rows':count,'sha256':digest.hexdigest()}
 finally:db.close()
 return result
scope=json.loads((HERE/'SCOPE.json').read_text());st=CLONE.stat()
assert scope['stage']==str(HERE) and st.st_ino!=scope['source_state'][1] and st.st_nlink==1 and not CLONE.is_symlink()
if phase=='baseline':
 with CLONE.open('rb') as f:assert hashlib.file_digest(f,'sha256').hexdigest()==RAW_SHA
from anki.collection import Collection
from anki.notes_pb2 import NoteFieldsCheckResponse
col,opening=timed('native-open-owned-clone',lambda:Collection(str(CLONE)))
def metadata():
 return {'sqlite':col.db.scalar('select sqlite_version()'),
  'notes_stat1':col.db.all("select * from sqlite_stat1 where tbl='notes'"),
  'indexes':col.db.all("select name,sql from sqlite_master where type='index' and tbl_name='notes'")}
def sample(word):
 csum=int(hashlib.sha1(word.encode()).hexdigest()[:8],16)
 row,=col.db.all('select id,mid,csum,octet_length(flds) from notes indexed by ix_notes_csum where csum=? and mid=?',csum,MID)
 return {'word':word,'nid':row[0],'mid':row[1],'csum':row[2],'flds_bytes':row[3]}
try:
 before_meta=metadata();samples=[sample(w) for w in ('a','abide')]
 plans={r['word']:col.db.all('explain query plan '+SQL,r['csum'],MID) for r in samples}
 save(phase+'-before.json',{'phase':phase,'opening_seconds':opening,'metadata':before_meta,'samples':samples,'plans':plans})
 if phase=='baseline':
  r=samples[0];rows,seconds=timed('ONE-baseline-exact-SQL-a',lambda:col.db.all(SQL,r['csum'],MID))
  save('baseline-result.json',{'status':'PASS','rows':rows,'seconds':seconds,'metadata':metadata(),'plans':plans})
 elif phase=='timing':
  before=None;digest_before_seconds=None
  _,analyze_seconds=timed('ONLY-WRITE-ANALYZE-notes',lambda:col.db.execute('ANALYZE notes'))
  after_meta=metadata();results=[]
  for r in samples:
   plan=col.db.all('explain query plan '+SQL,r['csum'],MID)
   rows,seconds=timed('after-exact-SQL-'+r['word'],lambda:col.db.all(SQL,r['csum'],MID))
   note,load_seconds=timed('after-load-note-'+r['word'],lambda:col.get_note(r['nid']))
   response,api_seconds=timed('after-native-fieldscheck-'+r['word'],lambda:col._backend.note_fields_check(note._to_backend_note()))
   assert response.state==NoteFieldsCheckResponse.NORMAL
   results.append({**r,'plan':plan,'rows':rows,'query_seconds':seconds,'load_note_seconds':load_seconds,'fieldscheck_seconds':api_seconds,'state':response.state})
  after=None;digest_after_seconds=None
  save('analyze-timing-result.json',{'status':'PASS','only_explicit_write':'ANALYZE notes',
   'metadata_before':before_meta,'metadata_after':after_meta,'analyze_seconds':analyze_seconds,'results':results,
   'protected_before':before,'protected_after':after,'notes_cards_revlog_typed_stream_SHA256_exact':None,
   'protected_hash_seconds':{'before':digest_before_seconds,'after':digest_after_seconds},'elapsed_seconds':time.monotonic()-started})
 else:raise ValueError('phase')
finally:col.close()
