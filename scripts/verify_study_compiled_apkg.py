#!/usr/bin/env python3
"""Independent archive/SQLite parity. No Anki import, PG, DOM or extraction.

Requires root-pinned final source/candidate APKGs and existing owned SQLite
caches. Each cache must match its actual final archive member byte-for-byte.
A source asset pin never substitutes for reading the candidate archive.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import html
import itertools
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import zipfile

HASH = re.compile(r'[a-f0-9]{64}')
CARRIER = re.compile(r'_study_native_([a-f0-9]{64})\.js')
BOOTSTRAP = re.compile(r'_study_native_bootstrap_([a-f0-9]{64})\.js')
FIELD = 'StudyCompiledDelivery'
CHUNK = 1024 * 1024

class ParityError(ValueError):
    def __init__(self, code, **context):
        self.code, self.context = code, context
        super().__init__(code + (': ' + json.dumps(context, ensure_ascii=False) if context else ''))

def require(ok, code, **context):
    if not ok: raise ParityError(code, **context)

def sha(raw): return hashlib.sha256(raw).hexdigest()
def identity(info): return [info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns]

def file_pin(path):
    path=Path(path)
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());require(stat.S_ISREG(before.st_mode),'regular-file-required',path=str(path))
        digest=hashlib.file_digest(stream,'sha256').hexdigest();after=os.fstat(stream.fileno())
    require(identity(before)==identity(after)==identity(path.stat()),'input-mutated',path=str(path))
    return {'path':str(path),'sha256':digest,'bytes':before.st_size},identity(before)

def check_pin(descriptor):
    require(type(descriptor) is dict and set(descriptor)=={'path','sha256','bytes'},'exact-file-pin-required')
    require(isinstance(descriptor['path'],str) and isinstance(descriptor['sha256'],str) and HASH.fullmatch(descriptor['sha256']) is not None and type(descriptor['bytes']) is int and descriptor['bytes']>=0,'invalid-file-pin')
    observed,state=file_pin(descriptor['path'])
    require(observed==descriptor,'file-pin-mismatch',path=descriptor['path'])
    return state

def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate-json-key',key=key)
        result[key]=value
    return result

def json_value(raw):
    return json.loads(raw,object_pairs_hook=no_duplicates,parse_constant=lambda value: (_ for _ in ()).throw(ParityError('nonfinite-json',value=value)))

def read_pinned_json(spec,limit=32*1024*1024):
    require(type(spec) is dict and spec.get('bytes',limit)<=limit,'metadata-size-limit')
    check_pin(spec)
    return json_value(Path(spec['path']).read_bytes())

def versions_for(registration,book):
    require(registration.get('schema')=='study-native-delivery-registration-result.v1','registration-schema')
    raw=registration.get('native_versions',{}).get(book)
    require(type(raw) is dict and set(raw)=={'models','notes'},'registered-book-required',book=book)
    result={}
    for kind,values in raw.items():
        require(type(values) is dict,'integer-version-map-required',kind=kind)
        result[kind]={}
        for key,value in values.items():
            require(isinstance(key,str) and re.fullmatch(r'[1-9][0-9]*',key) is not None and type(value) is int and value>0,'integer-version-map-required',kind=kind)
            result[kind][int(key)]=value
    return result

def archive_names(archive):
    names=[x.filename for x in archive.infolist()]
    require(len(names)==len(set(names)),'duplicate-zip-member')
    return set(names)

def member_pin(archive,name):
    digest=hashlib.sha256();size=0
    with archive.open(name) as stream:
        for block in iter(lambda:stream.read(CHUNK),b''):
            digest.update(block);size+=len(block)
    require(size==archive.getinfo(name).file_size,'zip-member-size',member=name)
    return {'sha256':digest.hexdigest(),'bytes':size}

def media_index(archive):
    require(archive.getinfo('media').file_size<=32*1024*1024,'media-index-size-limit')
    value=json_value(archive.read('media'))
    require(type(value) is dict and all(isinstance(k,str) and isinstance(v,str) and v for k,v in value.items()),'media-index-shape')
    names=set(archive.namelist())
    require(all(k in names for k in value),'media-member-missing')
    return value

def bind_collection_cache(archive,entry,path):
    path=Path(path)
    # No application package or user profile is imported or opened as Anki.
    user_root=Path.home()/'Library/Application Support/Anki2'
    require(not path.resolve().is_relative_to(user_root.resolve()),'real-anki-profile-refused')
    actual,state=file_pin(path)
    packed=member_pin(archive,entry)
    require({k:actual[k] for k in ('sha256','bytes')}==packed,'collection-cache-does-not-match-final-archive',entry=entry,path=str(path))
    return actual,state

def ident(name): return '"'+name.replace('"','""')+'"'
def columns(db,table): return [x[1] for x in db.execute('pragma table_info('+ident(table)+')')]
def row_count(db,table): return db.execute('select count(*) from '+ident(table)).fetchone()[0]
def ordered_rows(db,table):
    names=columns(db,table);order='id' if 'id' in names else ','.join(map(ident,names))
    return db.execute('select * from '+ident(table)+' order by '+('"id"' if order=='id' else order))

def exact_table(old,new,table):
    require(columns(old,table)==columns(new,table),'table-columns',table=table)
    count=0;missing=object()
    for a,b in itertools.zip_longest(ordered_rows(old,table),ordered_rows(new,table),fillvalue=missing):
        require(a is not missing and b is not missing,'table-row-count',table=table)
        require(a==b,'table-value',table=table,row_ordinal=count)
        count+=1
    return count

def shell(answer,bootstrap):
    return ('<section data-study-native-owner data-answer="'+str(answer).lower()+'">'
        '<script type="application/json" data-study-native-delivery>{{StudyCompiledDelivery}}</script>'
        '<p role="status" data-study-native-status>正在校验完整卡片…</p></section>'
        '<script src="'+bootstrap+'"></script>')

def compare_models(original,candidate,versions):
    require(set(original)==set(candidate),'model-id-set')
    bootstraps=set();changes=[]
    for mid,source in original.items():
        got=candidate[mid];registered=versions['models'].get(int(mid))
        if registered is None:
            require(source==got,'authored-model-changed',model_id=mid)
            continue
        require(got['mod']==registered and registered>source['mod'],'model-mod-not-registered',model_id=mid)
        require(got['flds'][:-1]==source['flds'] and len(got['flds'])==len(source['flds'])+1,'model-original-field-prefix',model_id=mid)
        expected={'name':FIELD,'ord':len(source['flds']),'sticky':False,'rtl':False,'font':'Arial','size':12,'media':[]}
        require(got['flds'][-1]==expected,'appended-field-definition',model_id=mid)
        require(len(got['tmpls'])==len(source['tmpls']),'template-count',model_id=mid)
        for before,after in zip(source['tmpls'],got['tmpls']):
            require({k:v for k,v in before.items() if k not in ('qfmt','afmt')}=={k:v for k,v in after.items() if k not in ('qfmt','afmt')},'template-metadata',model_id=mid)
            matches=re.findall(r'_study_native_bootstrap_[a-f0-9]{64}\.js',after['qfmt'])
            require(len(matches)==1,'native-template-bootstrap',model_id=mid)
            name=matches[0]
            require(after['qfmt']==shell(False,name) and after['afmt']==shell(True,name),'native-template-shell',model_id=mid)
            bootstraps.add(name)
        require({k:v for k,v in source.items() if k not in ('mod','flds','tmpls')}=={k:v for k,v in got.items() if k not in ('mod','flds','tmpls')},'unapproved-model-change',model_id=mid)
        changes.append({'model_id':int(mid),'source_mod':source['mod'],'registered_mod':registered,'templates':len(source['tmpls']),'appended_field':FIELD})
    require(set(versions['models'])=={int(x['model_id']) for x in changes},'registered-model-missing')
    return bootstraps,changes

def validate_descriptor(value,refs):
    require(type(value) is dict and set(value)=={'id','entry','runtime','packet','policy','transport','styles','local_media','bootstrap_version'},'delivery-descriptor-shape')
    require(isinstance(value['id'],str) and value['id'] and isinstance(value['bootstrap_version'],str) and HASH.fullmatch(value['bootstrap_version']) is not None,'delivery-descriptor-identity')
    transport=value['transport'];require(type(transport) is dict,'delivery-transport-shape')
    for name,item in transport.items():
        require(isinstance(name,str) and Path(name).name==name and type(item) is dict and set(item)=={'src','sha256'},'delivery-transport-shape')
        require(isinstance(item['src'],str) and CARRIER.fullmatch(item['src']) is not None and isinstance(item['sha256'],str) and HASH.fullmatch(item['sha256']) is not None,'delivery-transport-binding')
        previous=refs.setdefault(item['src'],item['sha256'])
        require(previous==item['sha256'],'conflicting-delivery-carrier-pin',alias=item['src'])
    def ref(item):
        require(type(item) is dict and set(item)=={'src','sha256'} and isinstance(item['src'],str) and item['src'] in transport and isinstance(item['sha256'],str) and HASH.fullmatch(item['sha256']) is not None and transport[item['src']]['sha256']==item['sha256'],'delivery-logical-reference')
    entry=value['entry'];require(type(entry) is dict and set(entry)=={'html','profile','source','anchors','decoded','module'},'delivery-entry-shape')
    allowed_modules={'5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e':'7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4','be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93':'6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633'}
    require(entry['decoded'] is True and type(entry['module']) is dict and set(entry['module'])=={'original_sha256','sha256'} and entry['module'].get('original_sha256') in allowed_modules and allowed_modules[entry['module']['original_sha256']]==entry['module']['sha256'],'delivery-module-cohort')
    for item in (entry['html'],entry['profile'],value['runtime'],value['packet'],value['policy']):ref(item)
    require(entry['anchors'].get('htmlSha256')==entry['html']['sha256'] and entry['anchors'].get('profileSha256')==entry['profile']['sha256'],'delivery-entry-anchors')
    for key in ('styles','local_media'):
        require(type(value[key]) is dict,'delivery-resource-map')
        for item in value[key].values():ref(item)

def compare_sqlite(source_path,candidate_path,versions):
    refs={};details={};notes_checked=field_values=0; cache_changes=[]
    old_uri=Path(source_path).resolve().as_uri()+'?mode=ro&immutable=1'
    new_uri=Path(candidate_path).resolve().as_uri()+'?mode=ro&immutable=1'
    with closing(sqlite3.connect(old_uri,uri=True)) as old,closing(sqlite3.connect(new_uri,uri=True)) as new:
        for db in (old,new):
            db.execute('pragma query_only=on');db.execute('pragma cache_size=-16384')
        require(new.execute('pragma integrity_check').fetchall()==[('ok',)],'candidate-sqlite-integrity')
        schema=lambda db:list(db.execute("select type,name,tbl_name,sql from sqlite_master order by type,name"))
        require(schema(old)==schema(new),'sqlite-schema')
        for key in ('user_version','application_id','page_size','encoding'):
            require(old.execute('pragma '+key).fetchone()==new.execute('pragma '+key).fetchone(),'sqlite-pragma',name=key)
        tables=[x[0] for x in old.execute("select name from sqlite_master where type='table' order by name")]
        require({'col','notes','cards','revlog'}<=set(tables),'anki-core-tables')
        for table in tables:
            if table not in ('col','notes'):details[table]=exact_table(old,new,table)
        require(columns(old,'col')==columns(new,'col'),'col-columns')
        names=columns(old,'col');oc=list(ordered_rows(old,'col'));nc=list(ordered_rows(new,'col'))
        require(len(oc)==len(nc)==1,'col-row-count')
        om,nm=None,None
        for index,name in enumerate(names):
            if name=='models':om,nm=json_value(oc[0][index]),json_value(nc[0][index])
            else:require(oc[0][index]==nc[0][index],'col-value',column=name)
        require(om is not None and nm is not None,'col-models-missing')
        bootstraps,model_changes=compare_models(om,nm,versions)
        names=columns(old,'notes');require(names==columns(new,'notes'),'notes-columns')
        need={'id','guid','mid','mod','usn','flds'};require(need<=set(names),'notes-required-columns')
        ix={name:i for i,name in enumerate(names)};seen_compiled=set();sentinel=object()
        for before,after in itertools.zip_longest(ordered_rows(old,'notes'),ordered_rows(new,'notes'),fillvalue=sentinel):
            require(before is not sentinel and after is not sentinel,'note-count')
            nid=before[ix['id']];mid=before[ix['mid']]
            require(after[ix['id']]==nid,'note-id',note_id=nid)
            registered=versions['notes'].get(nid)
            if registered is None:
                require(before==after,'authored-note-changed',note_id=nid)
                require(mid not in versions['models'],'partial-compiled-model',note_id=nid)
            else:
                require(mid in versions['models'],'note-model-not-registered',note_id=nid)
                for name,index in ix.items():
                    if name not in ('mod','usn','flds','csum','sfld'):require(before[index]==after[index],'note-value',note_id=nid,column=name)
                require(after[ix['mod']]==registered and registered>before[ix['mod']],'note-mod-not-registered',note_id=nid)
                require(after[ix['usn']]==-1,'note-usn',note_id=nid)
                fields=before[ix['flds']].split('\x1f');got=after[ix['flds']].split('\x1f')
                require(len(fields)==len(om[str(mid)]['flds']) and len(got)==len(fields)+1,'note-field-count',note_id=nid)
                require(fields==got[:-1],'original-field-prefix',note_id=nid)
                for name in ('csum','sfld'):
                    index=ix[name]
                    if before[index]!=after[index]:
                        ordinal=0 if name=='csum' else om[str(mid)].get('sortf',0)
                        plain=fields[ordinal]
                        require('<' not in plain,'changed-cache-needs-plain-source',note_id=nid,column=name)
                        plain=html.unescape(plain).replace('\xa0',' ')
                        expected=int(hashlib.sha1(plain.encode()).hexdigest()[:8],16) if name=='csum' else plain
                        require(after[index]==expected,'derived-field-cache',note_id=nid,column=name)
                        cache_changes.append({'note_id':nid,'column':name,'source':before[index],'candidate':after[index],'verified_from_unchanged_source_field':True})
                validate_descriptor(json_value(got[-1]),refs)
                seen_compiled.add(nid);field_values+=len(fields)
            notes_checked+=1
        require(seen_compiled==set(versions['notes']),'registered-note-coverage')
        details['notes']=notes_checked
        return {'tables_exact_except_documented_col_and_notes':details,'notes_checked':notes_checked,'compiled_notes_checked':len(seen_compiled),'original_compiled_field_values_exact':field_values,'model_changes':model_changes,'required_bootstraps':sorted(bootstraps),'carrier_logical_references':refs,'NFC_substitution_allowed':False,'derived_field_cache_changes':cache_changes}

def decode_carrier(raw,alias):
    require(raw.startswith(b'window.StudyCompiledNative.register('),'carrier-registration-prefix',alias=alias)
    text=raw.decode('utf-8');tail=text[len('window.StudyCompiledNative.register('):];decoder=json.JSONDecoder()
    pin,end=decoder.raw_decode(tail)
    require(isinstance(pin,str) and HASH.fullmatch(pin) is not None and tail[end:end+1]==',','carrier-logical-pin',alias=alias)
    value,stop=decoder.raw_decode(tail,end+1)
    require(isinstance(value,str) and tail[stop:]==');','carrier-registration-shape',alias=alias)
    require(sha(value.encode())==pin,'carrier-logical-sha',alias=alias)
    return pin

def compare_media(old,new,old_names,new_names,entry,sql,max_carrier_bytes):
    source=media_index(old);candidate=media_index(new)
    require(all(candidate.get(k)==v for k,v in source.items()),'original-media-index-binding')
    require(not ((set(candidate)-set(source))&old_names),'new-media-overwrites-old-member')
    require(new_names-old_names==set(candidate)-set(source),'unexpected-new-archive-members')
    original_aliases={};count=raw_bytes=0
    for member,alias in source.items():
        a,b=member_pin(old,member),member_pin(new,member)
        require(a==b,'original-media-bytes',alias=alias,member=member)
        if alias in original_aliases:require(original_aliases[alias]==a,'ambiguous-source-media-alias',alias=alias)
        original_aliases[alias]=a;count+=1;raw_bytes+=a['bytes']
    extras=old_names-set(source)-{entry,'media'}
    for name in sorted(extras):require(member_pin(old,name)==member_pin(new,name),'original-extra-member',member=name)
    added=[];logical={};bootstrap_names=set();added_aliases=set()
    for member,alias in candidate.items():
        if member in source:continue
        require(alias not in original_aliases,'new-media-alias-collision',alias=alias)
        require(alias not in added_aliases,'duplicate-new-media-alias',alias=alias)
        added_aliases.add(alias)
        carrier,bootstrap=CARRIER.fullmatch(alias),BOOTSTRAP.fullmatch(alias)
        require(carrier is not None or bootstrap is not None,'unapproved-new-media-alias',alias=alias)
        value=member_pin(new,member);expected=(carrier or bootstrap)[1]
        require(value['sha256']==expected,'content-addressed-new-media-sha',alias=alias)
        if carrier:
            require(value['bytes']<=max_carrier_bytes,'carrier-size-limit',alias=alias,bytes=value['bytes'])
            logical_pin=decode_carrier(new.read(member),alias)
            require(alias not in logical,'duplicate-new-media-alias',alias=alias)
            logical[alias]=logical_pin
        else:bootstrap_names.add(alias)
        added.append({'member':member,'alias':alias,**value,'kind':'register-carrier' if carrier else 'native-bootstrap'})
    require(bootstrap_names==set(sql['required_bootstraps']),'template-bootstrap-archive-binding')
    for alias,logical_pin in sql['carrier_logical_references'].items():
        require(logical.get(alias)==logical_pin,'descriptor-carrier-logical-binding',alias=alias)
    require(set(logical)==set(sql['carrier_logical_references']),'unreferenced-new-carrier')
    return {'original_media_members_checked':count,'original_media_aliases_checked':len(original_aliases),'original_media_raw_bytes_checked':raw_bytes,'original_extra_members_checked':len(extras),'new_media':added,'new_media_count':len(added),'new_media_raw_bytes':sum(x['bytes'] for x in added),'new_media_compressed_bytes':sum(new.getinfo(x['member']).compress_size for x in added),'all_original_media_and_extras_SHA_exact':True,'new_register_carriers_logical_SHA_exact':True}

def verify_book(request,registration):
    # Validate every explicit final pin/cache input before doing any heavy read.
    for key in ('source','candidate'):
        value=request.get(key);require(type(value) is dict and set(value)=={'path','sha256','bytes'},'final-archive-pin-required',side=key)
    for key in ('source_collection_cache','candidate_collection_cache'):
        require(isinstance(request.get(key),str) and Path(request[key]).is_file(),'existing-owned-collection-cache-required',side=key)
    entry=request.get('collection_entry');require(entry in ('collection.anki2','collection.anki21'),'supported-collection-entry-required')
    versions=versions_for(registration,request['book_id'])
    archive_states={key:check_pin(request[key]) for key in ('source','candidate')}
    with zipfile.ZipFile(request['source']['path']) as old,zipfile.ZipFile(request['candidate']['path']) as new:
        old_names,new_names=archive_names(old),archive_names(new)
        require(old_names<=new_names,'original-archive-member-missing')
        old_cache,old_state=bind_collection_cache(old,entry,request['source_collection_cache'])
        new_cache,new_state=bind_collection_cache(new,entry,request['candidate_collection_cache'])
        sql=compare_sqlite(old_cache['path'],new_cache['path'],versions)
        assets=compare_media(old,new,old_names,new_names,entry,sql,request.get('max_new_carrier_bytes',128*1024*1024))
    for key,state in archive_states.items():require(identity(Path(request[key]['path']).stat())==state,'archive-mutated-during-verification',side=key)
    for cache,state in ((old_cache,old_state),(new_cache,new_state)):
        require(identity(Path(cache['path']).stat())==state,'collection-cache-mutated-during-verification')
    refs=sql.pop('carrier_logical_references')
    return {'book_id':request['book_id'],'source':request['source'],'candidate':request['candidate'],'source_collection_bound_to_final_archive':old_cache,'candidate_collection_bound_to_final_archive':new_cache,'sqlite':sql,'media':assets,'descriptor_carrier_logical_references_checked':len(refs),'source_candidate_bytes_unchanged':True,'no_collection_copy_or_extraction':True}

def verify(request):
    require(request.get('schema')=='study-native-apkg-parity-request.v1','request-schema')
    require(type(request.get('books')) is list and request['books'],'book-requests-required')
    registration=read_pinned_json(request['registration'])
    ids=[b['book_id'] for b in request['books']];require(len(ids)==len(set(ids)),'duplicate-book')
    started=time.monotonic();books=[verify_book(book,registration) for book in request['books']]
    return {'schema':'study-native-apkg-complete-parity.v1','status':'PASS','registration':request['registration'],'books':books,'elapsed_seconds':round(time.monotonic()-started,3),'scope':'Actual pinned source and final candidate archives, complete SQLite row parity with only registered note/model versions, exact source-field prefix plus appended StudyCompiledDelivery; changed sort/checksum caches independently recomputed only from unchanged plain/entity source fields, native-template shell and content-addressed carrier additions. Every original media/extra member SHA checked from both actual archives. No NFC exception. No Anki import, actual user collection, PG, source extraction, DOM or visual/native-device acceptance.','actual_Anki_import_or_user_collection_access':False,'PG_writes':False,'visual_or_native_device_acceptance':False}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',required=True);parser.add_argument('--request-sha256',required=True);parser.add_argument('--report',required=True);args=parser.parse_args()
    output=Path(args.report);require(not output.exists(),'new-report-required')
    spec={'path':args.request,'sha256':args.request_sha256,'bytes':Path(args.request).stat().st_size}
    try:result=verify(read_pinned_json(spec))
    except Exception as error:
        result={'schema':'study-native-apkg-complete-parity.v1','status':'FAIL','request':spec,'error_type':type(error).__name__,'error':str(error),'no_Anki_import_or_PG_writes':True}
    with output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'report':str(output),'sha256':file_pin(output)[0]['sha256'],'status':result['status']}))
    if result['status']!='PASS':raise SystemExit(2)

if __name__=='__main__':main()
