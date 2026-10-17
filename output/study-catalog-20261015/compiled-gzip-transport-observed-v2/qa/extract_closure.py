"""One authorized read-only original-artifact resource closure extraction.

No DOM/JS execution, semantic producer, profile read or file installation.
Only the 55 MB artifact JSON is parsed once; wrapper head and CSS are scanned
as text. Outputs contain URL/path/stat/SHA metadata, never source HTML/rows.
"""
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urljoin, urlsplit

HERE=Path(__file__).resolve().parent
BOOK=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/exports/20261015/master-redbook-web-v3')
INPUTS=Path('/private/tmp/study-largest-codec-once-sealed-20261017-8ztnwna5/inputs.json')
MAX_INPUTS=Path('/private/tmp/study-compiled-2026-max-scaffold-20261017-vPV2vN/INPUTS.json')
BASE='http://qa.invalid/A/media/'
LIMIT=64*1024*1024
hash_bytes=lambda raw:hashlib.sha256(raw).hexdigest()


def signature(info):
 return {'dev':info.st_dev,'ino':info.st_ino,'bytes':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}


def inspect(path,pin=None,*,read=False,head=False):
 path=Path(path);canonical=path.resolve(strict=True);info=canonical.lstat()
 if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_size>LIMIT:raise ValueError('Source bounds differ')
 checksum=hashlib.sha256();parts=[];prefix=bytearray();head_done=False
 with os.fdopen(os.open(canonical,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
  if signature(os.fstat(stream.fileno()))!=signature(info):raise ValueError('Source changed before read')
  while chunk:=stream.read(1024*1024):
   checksum.update(chunk)
   if read:parts.append(chunk)
   if head and not head_done:
    prefix.extend(chunk)
    at=prefix.lower().find(b'</head>')
    if at>=0:prefix=prefix[:at+7];head_done=True
    elif len(prefix)>1024*1024:raise ValueError('Wrapper head exceeds small text boundary')
  if (signature(os.fstat(stream.fileno()))!=signature(info) or signature(canonical.lstat())!=signature(info)
      or path.resolve(strict=True)!=canonical):raise ValueError('Source changed during read')
 actual=checksum.hexdigest()
 if pin is not None and actual!=pin:raise ValueError('Pinned source differs')
 result={'path':str(path),'resolved':str(canonical),'bytes':info.st_size,'sha256':actual,'stat':signature(info)}
 return result,b''.join(parts) if read else bytes(prefix) if head else None


def write(name,value):
 path=HERE/name;raw=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
 return hash_bytes(raw)


def main():
 inputs=json.loads(INPUTS.read_bytes());old=json.loads(MAX_INPUTS.read_bytes())
 if old['card']!='ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576':raise ValueError('Case differs')
 artifact_info,raw=inspect(inputs['packet']['path'],inputs['packet']['sha256'],read=True)
 if artifact_info['bytes']!=55603149:raise ValueError('Original artifact size differs')
 artifact=json.loads(raw);del raw
 config_info,raw=inspect(inputs['policy_source']['path'],inputs['policy_source']['sha256'],read=True)
 config=json.loads(raw);del raw
 refs=set();ignored=set();sheets=[]
 def add(value,base=BASE):
  value=value.strip()
  if not value or value.startswith(('#','data:','blob:','about:','javascript:')):return
  target=urlsplit(urljoin(base,value))
  if target.scheme not in ('http','https') or target.netloc!='qa.invalid':ignored.add(value);return
  if target.query:raise ValueError('Actual resource has a query requiring explicit scope: '+value[:128])
  if not target.path.startswith('/A/'):raise ValueError('Resource escapes exact book prefix')
  route=unquote(target.path[3:])
  if '%' in route or '\\' in route or any(p in ('','.','..') for p in route.split('/')):raise ValueError('Unsafe resource path')
  refs.add(route)
 def css(value,base=BASE):
  for match in re.finditer(r'url\(\s*([\"\']?)(.*?)\1\s*\)',value,re.I|re.S):add(match.group(2),base)
  for match in re.finditer(r'@import\s+[\"\']([^\"\']+)[\"\']',value,re.I):add(match.group(1),base)
 class Resources(HTMLParser):
  def __init__(self,base=BASE):super().__init__(convert_charrefs=True);self.base=base;self.style=False
  def handle_starttag(self,tag,attrs):
   values=dict(attrs)
   if tag=='style':self.style=True
   if values.get('style'):css(values['style'],self.base)
   for name in ({'script':['src'],'img':['src'],'audio':['src'],'video':['src','poster'],
                 'source':['src'],'track':['src'],'iframe':['src']}.get(tag,[])):
    if values.get(name):add(values[name],self.base)
   if tag in ('source','img') and values.get('srcset') and not values['srcset'].startswith('data:'):
    for part in values['srcset'].split(','):add(part.strip().split()[0],self.base)
   if tag=='link' and set((values.get('rel') or '').lower().split())&{'stylesheet','preload','modulepreload','icon'} and values.get('href'):
    add(values['href'],self.base)
   if values.get('srcdoc'):
    if len(values['srcdoc'].encode())>1024*1024:raise ValueError('Unexpected oversized child source')
    nested=Resources(self.base);nested.feed(values['srcdoc']);nested.close()
  handle_startendtag=handle_starttag
  def handle_endtag(self,tag):
   if tag=='style':self.style=False
  def handle_data(self,value):
   if self.style:css(value,self.base)
 def parse(value,base=BASE):parser=Resources(base);parser.feed(value);parser.close()
 child_count=0
 for side in artifact['sides']:
  if len(side['html'].encode())>LIMIT:raise ValueError('Side text exceeds artifact bound')
  parse(side['html'])
  for child in side.get('children',[]):
   parse(child['html']);child_count+=1
 # Model styles/modules are packet metadata and retain the original URLs.
 metadata_resources=[]
 for key in ('styles','modules'):
  value=artifact.get(key,{})
  rows=value.values() if isinstance(value,dict) else value
  for row in rows:
   if isinstance(row,dict) and isinstance(row.get('src'),str):
    metadata_resources.append(row);add(row['src'],'http://qa.invalid/A/')
 for name in config['sharedFrame']['policy']['external']:add(name)
 wrapper_url=old['catalog_row'][4]
 wrapper_info,head=inspect(BOOK/wrapper_url,old['source_wrapper_sha256'],head=True)
 parse(head.decode(),'http://qa.invalid/A/'+wrapper_url)
 # CSS is small source text; follow only exact declared imports/URLs, once.
 scanned=set()
 while True:
  names=sorted(name for name in refs if name.lower().endswith('.css') and name not in scanned)
  if not names:break
  for name in names:
   info,raw=inspect(BOOK/name,read=True)
   if len(raw)>2*1024*1024:raise ValueError('Unexpected stylesheet size')
   css(raw.decode(),'http://qa.invalid/A/'+name);scanned.add(name);sheets.append(info)
 known={row['resolved']:row for row in inputs['resources'].values()}
 known[artifact_info['resolved']]=artifact_info;known[wrapper_info['resolved']]=wrapper_info
 for row in sheets:known[row['resolved']]=row
 output=[]
 def row_for(relative,purpose,expected=None):
  path=BOOK/relative;resolved=str(path.resolve(strict=True));meta=known.get(resolved)
  if meta is None:
   meta,_=inspect(path,expected);known[resolved]=meta
  else:
   info=Path(resolved).lstat()
   if info.st_size!=meta['bytes']:raise ValueError('Known source stat changed')
   if expected is not None and meta['sha256']!=expected:raise ValueError('Known source pin differs')
  output.append({'relative':relative,'purpose':purpose,**meta,'path':str(path)})
 for relative in sorted(refs):row_for(relative,'actual source/child/policy/CSS resource')
 # Original HOST chain; never invent a prepared packet or infer wrapper name.
 row_for(wrapper_url,'original wrapper raw',old['source_wrapper_sha256'])
 row_for(config['navigation'],'original navigation',old['navigation']['sha256'])
 row_for(config['navigationGzip'],'original navigation gzip carrier')
 descriptor=config['sharedFrame']['preparedIndex']
 row_for(descriptor['src'],'original prepared index',descriptor['sha256'])
 row_for(descriptor['gzipSrc'],'original prepared index gzip carrier')
 descriptor=old['prepared_card']['descriptor']
 for rule in (descriptor,descriptor['front']):
  row_for(rule['src'],'original complete/front prepared artifact',rule['sha256'])
  if rule.get('gzipSrc'):row_for(rule['gzipSrc'],'original complete/front gzip carrier')
 row_for('evidence/_study_prepared_wrapper_'+old['source_wrapper_sha256']+'.html.gz','original wrapper gzip carrier')
 # Record only original scalar proof/reference metadata, no native body data.
 result={'schema':'study-compiled-transport-exact-closure.v1','card_id':old['card'],
  'source_artifact':artifact_info,'source_wrapper':wrapper_info,'policy_source':config_info,
  'input_manifest_sha256':hash_bytes(INPUTS.read_bytes()),'max_input_manifest_sha256':hash_bytes(MAX_INPUTS.read_bytes()),
  'source_wrapper_url':wrapper_url,'artifact_JSON_parses':1,'profile_JSON_parses':0,'DOM_or_semantic_runs':0,
  'sides':len(artifact['sides']),'children':child_count,'resources':output,'resource_count':len(output),
  'external_resource_urls_not_remapped':sorted(ignored),'unknown_route_policy':'404; no dynamic fallback or directory exposure',
  'input_read_only':True,'production_written':False,'server_started':False}
 pin=write('source-closure.json',result)
 print(json.dumps({'closure_sha256':pin,'resources':len(output),'external_resource_urls':len(ignored),'artifact_JSON_parses':1,'profile_JSON_parses':0,'DOM_runs':0,'server_started':False}),flush=True)


if __name__=='__main__':main()
