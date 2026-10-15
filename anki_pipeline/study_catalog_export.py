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
import time
import zipfile
from urllib.parse import quote

from . import study_catalog as c
from .packaging import _render_template
from . import study_catalog_presentation as presentation


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
    from .study_catalog_library import scopes
    return {'id':book_id,'title':title,'edition':edition,'collection_id':collection,'col':col,
            'models':models,'runtime':runtime,'units':units,'scope':scopes(db).get(book_id,{}),'manifest':c.get_json(db,manifest_id),
            'revision':db.execute('select coalesce(max(id),0) from events').fetchone()[0]}


def project_note(db,book,note_id):
    row=db.execute('select guid,word_id,kind,ordinal,model_id,payload_id,source_card_id from notes where book_id=%s and note_id=%s',
                   (book['id'],note_id)).fetchone()
    if row is None:raise ValueError('unknown book note')
    guid,word,kind,ordinal,mid,payload,source_id=row
    fields=c.note_fields(db,book['id'],note_id);model=book['models'][str(mid)]
    names=[f['name'] for f in model['flds']]
    if len(names)!=len(fields):raise ValueError('master note field/model mismatch')
    return {'id':source_id or guid,'note_id':note_id,'guid':guid,'word_id':word,'kind':kind,'ordinal':ordinal,
            'model_id':mid,'model':model,'field_names':names,'fields':fields,'payload':c.get_json(db,payload)}


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
            models=json.loads(c.canonical(book['models']))
            originals=json.loads(book['col']['models'])
            for mid,model in models.items():
                if model!=originals.get(mid):model['mod']=max(int(time.time()),originals.get(mid,{}).get('mod',0)+1)
            native.execute('update col set models=?',(c.canonical(models),))
        for nid, in db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],)):
            note=project_note(db,book,nid);fields='\x1f'.join(note['fields'])
            row=native.execute('select guid,mid,flds,mod from notes where id=?',(nid,)).fetchone()
            if row is None and book['manifest'].get('collection_mode')=='skeleton':
                payload={**note['payload'],'flds':fields}
                columns=[r[1] for r in native.execute('pragma table_info(notes)')]
                native.execute('insert into notes values('+','.join('?' for _ in columns)+')',[payload[name] for name in columns])
                created+=1;row=(note['guid'],note['model_id'],fields,payload['mod'])
            if row is None or row[0]!=note['guid'] or row[1]!=note['model_id']:raise ValueError('native identity differs from catalog')
            if row[2]!=fields:
                word=note['fields'][0];checksum=int(hashlib.sha1(re.sub('<[^>]*>','',html.unescape(word)).encode()).hexdigest()[:8],16)
                native.execute('update notes set flds=?,sfld=?,csum=?,mod=?,usn=-1 where id=?',
                               (fields,word,checksum,max(int(time.time()),row[3]+1),nid));changed+=1
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
        resources={name:(book['runtime'].get(name,key),metadata) for name,key,metadata in db.execute('select name,object_id,zip_info_id from resource_aliases where book_id=%s',(book['id'],))}
        for index,(member,name) in enumerate(book['manifest']['media'].items()):
            key,metadata=resources[name];_write_member(archive,db,key,_zip_info(member,c.get_json(db,metadata)))
            if callback and index and index%10000==0:callback({'stage':'export-media','book_id':book['id'],'completed':index})
        for member,extra in book['manifest']['extra_members'].items():_write_member(archive,db,extra['object_id'],_zip_info(member,extra['zip_info']))
        archive.writestr('media',c.get_object(db,book['manifest']['media_index_id']))
    with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'schema':'study-catalog-export.v1','format':'apkg','notes':count,'media':len(resources),'shared_field_changes':changed,'created_notes':created,
            'bytes':package.stat().st_size,'sha256':digest,'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note'}


def _card_page(note,base,*,styles_href=None,template_ordinal=0):
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
            '</head><body class="card">'+content+'</body></html>')
    payload=c.canonical([side(front),side(back)]).replace('<','\\u003c')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;height:100%;background:#f5f7fc}#study-side{border:0;width:100%;height:100%}'
        '#study-flip{position:fixed;right:12px;top:10px;z-index:99999;border:1px solid #dbe3ef;border-radius:6px;'
        'padding:8px 12px;background:white;color:#215fbb;font:14px system-ui;cursor:pointer}</style></head><body>'
        '<button id="study-flip" type="button" aria-pressed="false">显示答案</button><iframe id="study-side" title="词卡正面"></iframe>'
        '<script>const sides='+payload+';let answer=false;const side=document.getElementById("study-side"),flip=document.getElementById("study-flip");'
        'function show(){side.srcdoc=sides[answer?1:0];side.title=answer?"词卡背面":"词卡正面";flip.textContent=answer?"返回正面":"显示答案";'
        'flip.setAttribute("aria-pressed",String(answer))}flip.onclick=()=>{answer=!answer;show()};'
        'function key(e){if(e.target.matches("input,select,textarea,button,summary,a,[contenteditable]"))return;'
        'if(e.code==="Space"){e.preventDefault();flip.click()}if(e.key==="ArrowLeft"||e.key==="ArrowRight")'
        '{e.preventDefault();parent.postMessage({type:"study-navigate",direction:e.key==="ArrowRight"?1:-1},location.origin)}}'
        'document.addEventListener("keydown",key);side.onload=()=>{side.contentDocument.addEventListener("keydown",key)};show();</script></body></html>')


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
    catalog=[];model_cache={}
    for index,(nid,) in enumerate(db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],))):
        note=project_note(db,book,nid);values=dict(zip(note['field_names'],note['fields']))
        web_model,css=_web_model(note['model'],media,model_cache)
        natives=db.execute('select n.native_id,n.ordinal,u.name from native_cards n join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s and n.note_id=%s order by n.ordinal',(book['id'],nid)).fetchall()
        label=html.unescape(values.get('Word',values.get('Title',note['fields'][note['model'].get('sortf',0)])))
        for native_id,ordinal,unit in natives:
            if not 0<=ordinal<len(web_model['tmpls']):raise ValueError('native card references missing template')
            # Keep existing single-template deep links stable.
            parts=('page',book['id'],note['guid'])
            filename=c.identity(*parts,*(() if len(natives)==1 else (ordinal,)))+'.html'
            (cards/filename).write_text(_card_page({**note,'model':web_model},'../media/',styles_href=css,template_ordinal=ordinal))
            catalog.append({'id':note['id'] if len(natives)==1 else str(native_id),'guid':note['guid'],
                'word':label,'label':label,'template':web_model['tmpls'][ordinal]['name'],'template_ordinal':ordinal,
                'unit':unit,'url':'cards/'+filename,'ordinal':note['ordinal'],'native_id':native_id})
        if callback and index and index%500==0:callback({'stage':'export-web-cards','book_id':book['id'],'completed':index})
    resources=0
    for name,key in db.execute('select name,object_id from resource_aliases where book_id=%s order by name',(book['id'],)):
        key=book['runtime'].get(name,key)
        if Path(name).name!=name:raise ValueError('unsafe resource alias')
        with (media/name).open('xb') as stream:c.write_object(db,key,stream)
        resources+=1
    (root/'catalog.json').write_text(c.canonical({'schema':'shared-book-web.v1','book_id':book['id'],'title':book['title'],'scope':book['scope'],'cards':catalog,'catalog_revision':book['revision']}))
    (root/'index.html').write_text(_library_html(book['title']))
    return {'schema':'study-catalog-export.v1','format':'web','notes':index+1 if catalog else 0,'cards':len(catalog),'media':resources,
            'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note'}


def _library_html(title):
    # The same small host shell serves every book. Only the JSON catalog varies.
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>'''+html.escape(title)+'''</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f7fc;color:#253247;font:14px system-ui}header{height:58px;padding:12px 18px;display:flex;align-items:center;gap:12px;background:white;border-bottom:1px solid #e0e6ef}h1{font-size:16px;margin:0;flex:1}button,input,select{font:inherit;border:1px solid #dbe3ef;background:white;border-radius:6px;padding:8px}main{display:flex;height:calc(100vh - 58px)}aside{width:270px;padding:12px;background:white;border-right:1px solid #e0e6ef;overflow:auto}aside input,aside select{width:100%;margin-bottom:10px}.entry{display:block;width:100%;text-align:left;margin:3px 0;border:0;cursor:pointer}.entry.active{background:#eaf1fc;color:#215fbb}iframe{flex:1;border:0;width:0;height:100%;background:#f5f7fc}@media(max-width:650px){aside{width:155px;padding:6px}h1{font-size:13px}header{padding:8px;gap:5px}.entry{padding:9px 5px}header button{padding:7px}}</style></head><body>
<header><h1>'''+html.escape(title)+'''</h1><span id="position"></span><button id="previous">上一张</button><button id="next">下一张</button></header>
<main><aside><select id="units" aria-label="单元"><option value="">全部单元</option></select><input id="query" placeholder="搜索内容" aria-label="搜索内容"><div id="list"></div></aside><iframe id="frame" title="学习卡片"></iframe></main>
<script>(async function(){const data=await(await fetch('catalog.json')).json(),all=data.cards;let selected=all[0]?.id,visible=all;
const $=id=>document.getElementById(id),frame=$('frame'),list=$('list');for(const unit of [...new Set(all.map(x=>x.unit))]){const o=document.createElement('option');o.value=unit;o.textContent=unit.split('::').slice(1).join(' / ')||unit;$('units').append(o)}
function open(card){if(!card)return;selected=card.id;frame.src=card.url;location.hash='card='+encodeURIComponent(card.id);draw()}
function draw(){const i=visible.findIndex(x=>x.id===selected),start=Math.max(0,i-30);list.replaceChildren();for(const card of visible.slice(start,start+90)){const b=document.createElement('button');b.className='entry'+(card.id===selected?' active':'');b.textContent=card.word;b.onclick=()=>open(card);list.append(b)}if(start>0){const b=document.createElement('button');b.textContent='前一组';b.onclick=()=>open(visible[Math.max(0,start-60)]);list.prepend(b)}if(start+90<visible.length){const b=document.createElement('button');b.textContent='后一组';b.onclick=()=>open(visible[start+90]);list.append(b)}$('position').textContent=(i+1)+' / '+visible.length;$('previous').disabled=i<=0;$('next').disabled=i<0||i>=visible.length-1}
function filter(){const q=$('query').value.trim().toLocaleLowerCase(),unit=$('units').value;visible=all.filter(x=>(!unit||x.unit===unit)&&(!q||x.word.toLocaleLowerCase().includes(q)));if(!visible.some(x=>x.id===selected))open(visible.find(x=>x.word.toLocaleLowerCase()===q)||visible[0]);draw()}
$('query').oninput=filter;$('units').onchange=filter;$('previous').onclick=()=>open(visible[visible.findIndex(x=>x.id===selected)-1]);$('next').onclick=()=>open(visible[visible.findIndex(x=>x.id===selected)+1]);
window.onkeydown=e=>{if(e.target.matches('input,select,textarea'))return;if(e.key==='ArrowRight')$('next').click();if(e.key==='ArrowLeft')$('previous').click();if(e.code==='Space'){e.preventDefault();frame.contentDocument?.getElementById('study-flip')?.click()}};
window.addEventListener('message',e=>{if(e.source!==frame.contentWindow||e.origin!==location.origin||e.data?.type!=='study-navigate')return;open(visible[visible.findIndex(x=>x.id===selected)+(e.data.direction===1?1:-1)])});
window.onhashchange=()=>{const id=new URLSearchParams(location.hash.slice(1)).get('card');if(id!==selected){const card=visible.find(x=>x.id===id);if(card)open(card)}};
const id=new URLSearchParams(location.hash.slice(1)).get('card');open(all.find(x=>x.id===id)||all[0])})();</script></body></html>'''


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
                cursor.execute('select id,codec,byte_length,data from objects order by id')
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
