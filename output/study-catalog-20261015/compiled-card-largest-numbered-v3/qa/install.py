"""Default read-only; --apply exclusively creates a new pinned numbered body, profile and QA; existing assets remain read-only."""
from pathlib import Path
import argparse,hashlib,json,os,re
HERE=Path(__file__).resolve().parent
ROOT=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v3')
INDEX='e4e8b8618181bae6162f3c9c5d9eb77abe81a8a6095dcee425f3589b51e67212'
HOST='aed67c9ce6e87662cef875fad6c563259b32424f736a7ab63172e409125c9984'
def sha(value):return hashlib.sha256(value).hexdigest()
def ownership_stamp(stat):
 return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
def still_owned(item):
 # Keep the original descriptor open. A replaced pathname is never sufficient
 # proof of ownership, including replacement with the same planned bytes.
 try:
  descriptor=os.fstat(item['fd']);path_stat=item['path'].lstat()
  if (descriptor.st_dev,descriptor.st_ino)!=(item['dev'],item['ino']):return False
  if ownership_stamp(descriptor)!=item['stamp'] or ownership_stamp(path_stat)!=item['stamp']:return False
  if descriptor.st_size!=item['written']:return False
  if os.pread(item['fd'],item['written'],0)!=item['raw'][:item['written']]:return False
  # Recheck after reading; concurrent edits/replacements are preserved.
  return ownership_stamp(os.fstat(item['fd']))==item['stamp'] and ownership_stamp(item['path'].lstat())==item['stamp']
 except OSError:return False
def rollback_owned(created):
 for item in reversed(created):
  if not still_owned(item):continue
  try:item['path'].unlink()
  except OSError:pass  # Preserve the original failure and any ambiguous file.

def validate_inputs():
 assert Path(m['target_root']).resolve()==ROOT.resolve()
 assert m['official_index_sha256']==INDEX and sha((ROOT/'index.html').read_bytes())==INDEX,'Official index drifted'
 assert m['official_host_sha256']==HOST and sha((ROOT/('_study_library_'+HOST+'.js')).read_bytes())==HOST,'Official HOST drifted'
 for path,pin in m['frozen_source_inputs'].items():
  source=Path(path);assert not source.is_symlink() and source.is_file(),'Frozen source unavailable'
  assert sha(source.read_bytes())==pin,'Frozen source changed: '+path
 for name,checksum,size in shared_inputs:
  path=ROOT/name
  assert not path.is_symlink() and path.is_file(),'Existing candidate HOST is not a regular file'
  raw=path.read_bytes();assert len(raw)==size and sha(raw)==checksum,'Existing candidate HOST drifted'
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
m=json.loads((HERE/'manifest.json').read_bytes())
assert sha((HERE/'install.py').read_bytes())==m['installer_sha256'],'Installer SHA differs from manifest'
shared_inputs=[(m['candidate_host_filename'],m['candidate_host_sha256'],m['candidate_host_bytes'])]+[(item['name'],item['sha256'],item['bytes']) for item in m['readonly_assets']]
validate_inputs();plan=[]
assert len(m['asset_files'])<=7 and len(m['files'])==len(m['asset_files'])+1 and set(m['files'])==set(m['asset_files']+[m['qa_filename']])
assert len(set(m['asset_files']))==len(m['asset_files'])
assert re.fullmatch(r'_qa_compiled_profile_[a-f0-9]{12}\.html',m['qa_filename'])
for name in m['asset_files']+[m['qa_filename']]:
 assert re.fullmatch(r'_qa_[A-Za-z0-9_.-]{1,160}\.(?:js|json|html|gz)',name) and Path(name).name==name
 entry=m['files'][name];assert 0<entry['bytes']<=67108864
 raw=(HERE/name).read_bytes();target=ROOT/name
 assert sha(raw)==entry['sha256'] and len(raw)==entry['bytes']
 assert not target.exists() and not target.is_symlink(),'QA resource target exists; refusing overwrite'
 plan.append((name,raw,target))
validate_inputs()
created=[]
if args.apply:
 try:
  for name,raw,target in plan:
   fd=os.open(target,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o644)
   try:stat=os.fstat(fd)
   except BaseException:os.close(fd);raise
   item={'path':target,'fd':fd,'dev':stat.st_dev,'ino':stat.st_ino,'stamp':ownership_stamp(stat),'raw':raw,'written':0}
   created.append(item)
   while item['written']<len(raw):
    amount=os.write(fd,raw[item['written']:])
    if amount<=0:raise OSError('QA file write made no progress')
    item['written']+=amount;item['stamp']=ownership_stamp(os.fstat(fd))
   os.fsync(fd)
   assert still_owned(item) and sha(os.pread(fd,len(raw),0))==m['files'][name]['sha256']
  validate_inputs()
  assert all(still_owned(item) for item in created),'QA file changed during installation'
 except BaseException:
  rollback_owned(created)
  raise
 finally:
  for item in created:
   try:os.close(item['fd'])
   except OSError:pass
print(json.dumps({'mode':'applied' if args.apply else 'dry-run','files':[{'target':str(target),'sha256':sha(raw),'bytes':len(raw)} for _,raw,target in plan],'existing_host_inputs':[{'name':name,'sha256':checksum,'bytes':size} for name,checksum,size in shared_inputs],'cold_only_url':m['cold_only_url'],'digest_observer_url':m['digest_observer_url'],'formal_unchanged':True,'server_and_lan_bootstrap_unchanged':True,'progress_written':False},ensure_ascii=False,indent=2))
