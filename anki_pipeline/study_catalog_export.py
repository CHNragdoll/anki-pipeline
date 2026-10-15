"""One PostgreSQL projection shared by APKG and static browser generation."""
from __future__ import annotations

import base64
from contextlib import closing
import copy
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile
from urllib.parse import quote

from . import study_catalog as c
from .packaging import _render_template
from . import study_catalog_presentation as presentation
from .study_catalog_anki import field_cache,content_mods,model_mods,runtime_revisions,effective_content_mod
from . import study_catalog_math
from . import study_catalog_web


def require_ready(db):
    pending=db.execute("select count(*) from sources where status<>'complete'").fetchone()[0]
    if pending:raise ValueError('catalog migration is incomplete; no artifact may be published')


def project_book(db,book_id):
    """This is the only book/field read path used by both output formats."""
    require_ready(db)
    row=db.execute('select b.title,b.edition,s.collection_id,s.col_payload_id,x.manifest_id from books b '
                   'join book_sources s on s.book_id=b.id join sources x on x.id=s.source_id where b.id=%s',(book_id,)).fetchone()
    if row is None:raise ValueError('unknown book or missing exact import source')
    title,edition,collection,col_id,manifest_id=row
    col=c.get_json(db,col_id);models,runtime=presentation.project(db,book_id,col);units=json.loads(col['decks'])
    versions=model_mods(db);originals=json.loads(col['models'])
    for mid,model in models.items():
        version=versions.get(c.identity(book_id,mid))
        if version is not None:model['mod']=max(model['mod'],version)
        original=originals[mid]
        if model!=original and model['mod']<=original['mod']:
            raise ValueError('shared presentation revision has no committed native model version')
    from .study_catalog_library import scopes
    from .study_catalog_revision import registry
    return {'id':book_id,'title':title,'edition':edition,'collection_id':collection,'col':col,
            'models':models,'runtime':runtime,'units':units,'scope':scopes(db).get(book_id,{}),'manifest':c.get_json(db,manifest_id),
            'content_mods':content_mods(db),
            'runtime_revision':runtime_revisions(db).get(book_id),
            'semantic_projections':registry(db),
            'revision':db.execute('select coalesce(max(id),0) from events').fetchone()[0]}


def project_note(db,book,note_id,*,apply_runtime=True):
    """Project shared fields, optionally followed by host resource references.

    Semantic revision writers must use ``apply_runtime=False`` so a generated
    resource alias never becomes authored content. Both delivery hosts use the
    default final projection; their resource rewrite remains identical.
    """
    row=db.execute('select guid,word_id,kind,ordinal,model_id,payload_id,source_card_id from notes where book_id=%s and note_id=%s',
                   (book['id'],note_id)).fetchone()
    if row is None:raise ValueError('unknown book note')
    guid,word,kind,ordinal,mid,payload,source_id=row
    fields=c.note_fields(db,book['id'],note_id);model=book['models'][str(mid)]
    names=[f['name'] for f in model['flds']]
    if len(names)!=len(fields):raise ValueError('master note field/model mismatch')
    from .study_catalog_revision import project_fields,project_display_fields
    fields=project_fields(db,book,source_id,names,fields)
    if apply_runtime:fields=project_display_fields(db,book,source_id,names,fields)
    if apply_runtime and book['runtime']['aliases']:
        if any(presentation._dynamic_reference(text) for text in fields):
            raise ValueError('dynamic note runtime reference requires an explicit dependency declaration')
        fields=[presentation.rewrite_references(text,book['runtime']['aliases']) for text in fields]
    payload=c.get_json(db,payload);mod=book['content_mods'].get(c.identity(book['id'],note_id))
    mod=effective_content_mod(payload['mod'],mod,book['runtime_revision'])
    return {'id':source_id or guid,'note_id':note_id,'guid':guid,'word_id':word,'kind':kind,'ordinal':ordinal,
            'model_id':mid,'model':model,'field_names':names,'fields':fields,'payload':payload,'content_mod':mod}


def _zip_info(name,metadata):
    info=zipfile.ZipInfo(name,tuple(metadata['date_time']))
    for field in ('compress_type','create_system','create_version','extract_version','internal_attr','external_attr'):
        setattr(info,field,metadata[field])
    info.comment=base64.b64decode(metadata['comment']);info.extra=base64.b64decode(metadata['extra'])
    return info


def _write_member(archive,db,key,info):
    with archive.open(info,'w',force_zip64=True) as stream:c.write_object(db,key,stream)


def _render_note(note,template_ordinal=0):
    """Shared source template registry; no book-name or year-specific branch."""
    fields=dict(zip(note['field_names'],note['fields']));template=note['model']['tmpls'][template_ordinal]
    front=_render_template(template['qfmt'],fields)
    back=_render_template(template['afmt'],{**fields,'FrontSide':front})
    return front,back


def export_book(value,book_id,output,*,format='apkg',callback=None):
    destination=c.guard_new_output(output)
    if format not in {'apkg','web'}:raise ValueError('unknown output format')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with c.connect(value,readonly=True) as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        book=project_book(db,book_id)
        with tempfile.TemporaryDirectory(prefix='.study-build-',dir=destination.parent) as staging:
            staging=Path(staging)
            report=_apkg(db,book,staging,destination.name,callback) if format=='apkg' else _web(db,book,staging,callback)
            result=staging/destination.name if format=='apkg' else staging/'web'
            # No-clobber publication; source packages are unnecessary. A web
            # directory is reserved first and gets its completion marker last.
            if destination.exists() or destination.is_symlink():raise FileExistsError('output appeared during generation')
            if format=='apkg':
                import os
                os.link(result,destination)
            else:
                # Reserve the destination to avoid replacing an existing path.
                # Consumers require the completion marker written last below.
                destination.mkdir()
                try:
                    for child in result.iterdir():shutil.move(str(child),destination/child.name)
                    (destination/'COMPLETE.json').write_text(c.canonical(report))
                except BaseException:
                    # Keep partial output visible for diagnosis, never delete a
                    # path another actor may have added after reservation.
                    raise
        return {**report,'output':str(destination.resolve()),'book_id':book_id,'catalog_revision':book['revision']}


def _apkg(db,book,folder,name,callback):
    collection=folder/book['manifest']['collection_entry']
    with collection.open('xb') as stream:c.write_object(db,book['collection_id'],stream)
    changed=0;count=0;created=0
    with closing(sqlite3.connect(collection)) as native, native:
        if json.loads(book['col']['models'])!=book['models']:
            native.execute('update col set models=?',(c.canonical(book['models']),))
        for nid, in db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],)):
            note=project_note(db,book,nid);fields='\x1f'.join(note['fields'])
            row=native.execute('select guid,mid,flds,mod from notes where id=?',(nid,)).fetchone()
            if row is None and book['manifest'].get('collection_mode')=='skeleton':
                sort_value,checksum=field_cache(note['fields'],note['model'])
                payload={**note['payload'],'flds':fields,'sfld':sort_value,'csum':checksum}
                if note['content_mod'] is not None:payload['mod']=note['content_mod']
                columns=[r[1] for r in native.execute('pragma table_info(notes)')]
                native.execute('insert into notes values('+','.join('?' for _ in columns)+')',[payload[name] for name in columns])
                created+=1;row=(note['guid'],note['model_id'],fields,payload['mod'])
            if row is None or row[0]!=note['guid'] or row[1]!=note['model_id']:raise ValueError('native identity differs from catalog')
            if row[2]!=fields or (note['content_mod'] is not None and note['content_mod']>row[3]):
                if note['content_mod'] is None or note['content_mod']<=row[3]:
                    raise ValueError('shared field revision has no newer committed native note version')
                plain,checksum=field_cache(note['fields'],note['model'])
                native.execute('update notes set flds=?,sfld=?,csum=?,mod=?,usn=-1 where id=?',
                               (fields,plain,checksum,note['content_mod'],nid));changed+=1
            count+=1
        if book['manifest'].get('collection_mode')=='skeleton':
            columns=[r[1] for r in native.execute('pragma table_info(cards)')]
            for payload_id, in db.execute('select payload_id from native_cards where book_id=%s order by native_id',(book['id'],)):
                payload=c.get_json(db,payload_id)
                native.execute('insert into cards values('+','.join('?' for _ in columns)+')',[payload[name] for name in columns])
        if native.execute('select count(*) from notes').fetchone()[0]!=count:raise ValueError('incomplete catalog note coverage')
        if native.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('generated Anki database failed integrity check')
    package=folder/name
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        info=_zip_info(book['manifest']['collection_entry'],book['manifest']['collection_zip_info'])
        with collection.open('rb') as source,archive.open(info,'w',force_zip64=True) as target:shutil.copyfileobj(source,target,1024*1024)
        resources={name:(book['runtime']['sources'].get(name,key),metadata) for name,key,metadata in db.execute('select name,object_id,zip_info_id from resource_aliases where book_id=%s',(book['id'],))}
        for index,(member,name) in enumerate(book['manifest']['media'].items()):
            key,metadata=resources[name];_write_member(archive,db,key,_zip_info(member,c.get_json(db,metadata)))
            if callback and index and index%10000==0:callback({'stage':'export-media','book_id':book['id'],'completed':index})
        for member,extra in book['manifest']['extra_members'].items():_write_member(archive,db,extra['object_id'],_zip_info(member,extra['zip_info']))
        media_index=dict(book['manifest']['media']);next_member=0
        for alias,raw in sorted(book['runtime']['generated'].items()):
            if alias in resources:continue
            while str(next_member) in media_index or str(next_member) in book['manifest']['extra_members']:next_member+=1
            member=str(next_member);media_index[member]=alias
            archive.writestr(member,raw,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        archive.writestr('media',c.canonical(media_index).encode() if book['runtime']['generated'] else c.get_object(db,book['manifest']['media_index_id']))
    with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'schema':'study-catalog-export.v1','format':'apkg','notes':count,'media':len(media_index),'shared_field_changes':changed,'created_notes':created,
            'bytes':package.stat().st_size,'sha256':digest,'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note'}


def _card_page(note,base,*,styles_href=None,template_ordinal=0,math_href=None,mount_audit=None):
    front,back=_render_note(note,template_ordinal)
    # Native Anki mounts one side at a time. Mounting two source templates in
    # the same DOM runs both scripts, duplicates IDs and breaks disclosures.
    # srcdoc gives the browser adapter the same one-active-document lifecycle;
    # replacing it also stops audio/timers from the previous side.
    def side(content):
        def sound(match):
            filename=html.unescape(match[1])
            return '<audio controls preload="none" src="'+quote(filename,safe='')+'"></audio>'
        content=re.sub(r'\[sound:([^\]\r\n]+)\]',sound,content)
        return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<base href="'+html.escape(base,quote=True)+'">'+
            ('<link rel="stylesheet" href="'+html.escape(styles_href,quote=True)+'">' if styles_href else '<style>'+note['model']['css']+'</style>')+
            (study_catalog_math.header(math_href) if math_href else '')+
            '</head><body class="card">'+content+'</body></html>')
    sides=[side(front),side(back)]
    if mount_audit is not None:mount_audit.observe(sides)
    payload=c.canonical(sides).replace('<','\\u003c')
    return study_catalog_web.card_shell(payload,base)


def _web_model(model,media,cache):
    """Keep CSS and field-independent template scripts once per exact version.

    The source templates still pass through the same Python field renderer.
    This changes resource delivery only; neither host recomputes source facts.
    """
    key=model['id']
    if key in cache:return cache[key]
    result=copy.deepcopy(model)
    def asset(text,suffix):
        name='_study_'+hashlib.sha256(text.encode()).hexdigest()+'.'+suffix
        path=media/name
        if not path.exists():path.write_text(text)
        return name
    css=asset(result['css'],'css');result['css']=''
    def script(match):
        attributes,body=match[1],match[2]
        if not body or '{{' in body or re.search(r'\bsrc\s*=|\btype\s*=\s*[\"\']application/(?:json|ld\+json)',attributes,re.I):return match[0]
        return '<script'+attributes+' src="'+asset(body,'js')+'"></script>'
    for template in result['tmpls']:
        for side in ('qfmt','afmt'):
            template[side]=re.sub(r'<script\b([^>]*)>(.*?)</script\s*>',script,template[side],flags=re.I|re.S)
    cache[key]=result,css
    return result,css


def _web(db,book,folder,callback):
    root=folder/'web';cards=root/'cards';media=root/'media';cards.mkdir(parents=True);media.mkdir()
    from .study_catalog_navigation import catalog_navigation_metadata,note_navigation_metadata
    retained=db.execute('select value from metadata where key=%s',('source.catalog.'+book['id'],)).fetchone()
    grouping=catalog_navigation_metadata(json.loads(c.get_object(db,retained[0])),grouping_only=True)['cards'] if retained else {}
    metadata={'cards':{},'provenance':{'kind':'current-projected-fields','grouping_source_sha256':retained[0] if retained else None}}
    members=[]
    catalog=[];model_cache={};math_href=None;mount_audit=study_catalog_web.SharedMountAudit()
    for index,(nid,) in enumerate(db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],))):
        note=project_note(db,book,nid);values=dict(zip(note['field_names'],note['fields']))
        from . import study_catalog_math
        needs_math=study_catalog_math.required(note['fields'])
        if needs_math and math_href is None:math_href=study_catalog_math.write_assets(db,media)
        web_model,css=_web_model(note['model'],media,model_cache)
        natives=db.execute('select n.native_id,n.ordinal,u.name from native_cards n join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s and n.note_id=%s order by n.ordinal',(book['id'],nid)).fetchall()
        label=html.unescape(values.get('Word',values.get('Title',note['fields'][note['model'].get('sortf',0)])))
        original=grouping.get(note['id'],{})
        summary=note_navigation_metadata(note,source_entry={'deckName':original.get('deck_name')})
        for native_id,ordinal,unit in natives:
            if not 0<=ordinal<len(web_model['tmpls']):raise ValueError('native card references missing template')
            # Keep existing single-template deep links stable.
            parts=('page',book['id'],note['guid'])
            filename=c.identity(*parts,*(() if len(natives)==1 else (ordinal,)))+'.html'
            (cards/filename).write_text(_card_page({**note,'model':web_model},'../media/',styles_href=css,template_ordinal=ordinal,math_href=math_href if needs_math else None,mount_audit=mount_audit))
            card_id=note['id'] if len(natives)==1 else str(native_id)
            metadata['cards'][card_id]=summary
            # Retained inventories can omit a separate package guide. New
            # content added to that book still belongs in its directory.
            if note['id'] in grouping or note['kind']!='guide':members.append(card_id)
            catalog.append({'id':card_id,'guid':note['guid'],
                'word':label,'label':label+(' · '+web_model['tmpls'][ordinal]['name'] if len(natives)>1 else ''),'template':web_model['tmpls'][ordinal]['name'],'template_ordinal':ordinal,
                'unit':unit,'url':'cards/'+filename,'ordinal':note['ordinal'],'native_id':native_id})
        if callback and index and index%500==0:callback({'stage':'export-web-cards','book_id':book['id'],'completed':index})
    resources=0
    for name,key in db.execute('select name,object_id from resource_aliases where book_id=%s order by name',(book['id'],)):
        key=book['runtime']['sources'].get(name,key)
        if Path(name).name!=name:raise ValueError('unsafe resource alias')
        with (media/name).open('xb') as stream:c.write_object(db,key,stream)
        resources+=1
    for alias,raw in sorted(book['runtime']['generated'].items()):
        path=media/alias
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('runtime alias collides with another generated resource')
            continue
        path.write_bytes(raw);resources+=1
    full_catalog={'schema':'shared-book-web.v1','book_id':book['id'],'title':book['title'],'scope':book['scope'],'cards':catalog,'catalog_revision':book['revision']}
    (root/'catalog.json').write_text(c.canonical(full_catalog))
    if retained:metadata['member_ids']=members
    navigation=study_catalog_web.write_library(root,full_catalog,metadata,shared_frame=study_catalog_web.audited_shared_config(root,mount_audit))
    return {'schema':'study-catalog-export.v1','format':'web','notes':index+1 if catalog else 0,'cards':len(catalog),'media':resources,
            'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note',**navigation}


def _library_html(title):
    """Compatibility wrapper for the subject-neutral browser host."""
    return study_catalog_web.library_html(title)


def verify_catalog(value,*,deep=False):
    problems=[]
    with c.connect(value,readonly=True) as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        pending=db.execute("select count(*) from sources where status<>'complete'").fetchone()[0]
        if pending:problems.append({'kind':'incomplete_sources','count':pending})
        for sid,name,count in db.execute('select source_id,name,row_count from archive_tables'):
            actual=db.execute('select count(*) from archive_rows where source_id=%s and table_name=%s',(sid,name)).fetchone()[0]
            if actual!=count:problems.append({'kind':'archive_count','source':sid,'table':name,'expected':count,'actual':actual})
        for book,card,expected in db.execute('select book_id,source_card_id,expected_occurrences from analyses'):
            actual=db.execute('select count(*) from analysis_occurrences where book_id=%s and source_card_id=%s',(book,card)).fetchone()[0]
            if actual!=expected:problems.append({'kind':'physical_count','book':book,'card':card,'expected':expected,'actual':actual})
        checked=0
        if deep:
            class Sink:
                def write(self,_):pass
            with db.cursor(name='verify_objects') as cursor:
                cursor.itersize=64
                cursor.execute('select id,codec,byte_length,data from objects')
                for key,codec,size,data in cursor:
                    c.write_encoded_object(key,codec,size,data,Sink());checked+=1
            for sid,name,expected,seal in db.execute('select source_id,name,row_count,row_digest from archive_tables'):
                digest=hashlib.sha256();count=0
                class RowsDigest:
                    def write(self,part):digest.update(part)
                with db.cursor(name='verify_archive_rows') as cursor:
                    cursor.itersize=64
                    cursor.execute('select r.ordinal,o.id,o.codec,o.byte_length,o.data from archive_rows r join objects o on o.id=r.payload_id '
                        'where r.source_id=%s and r.table_name=%s order by r.ordinal',(sid,name))
                    for ordinal,key,codec,size,data in cursor:
                        if ordinal!=count:raise ValueError('history archive has a missing or duplicated row ordinal')
                        c.write_encoded_object(key,codec,size,data,RowsDigest());digest.update(b'\n');count+=1
                if count!=expected or digest.hexdigest()!=seal:
                    problems.append({'kind':'archive_digest','source':sid,'table':name})
    return {'schema':'study-catalog-verification.v1','ok':not problems,'engine':'postgresql','problems':problems,'objects_deep_verified':checked}
