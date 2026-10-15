"""Read-only source adapters for the single PostgreSQL learning catalog.

Adapters describe source formats, never individual book names. The current
presentation and the complete source audit are retained as independent data.
"""
from __future__ import annotations

from contextlib import contextmanager
import base64
import errno
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

from psycopg import sql
from . import study_catalog as c
from .study_catalog_capacity import important_capacity


def file_sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def file_state(path):
    p=Path(path).resolve(strict=True);s=p.stat()
    return {'path':str(p),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'dev':s.st_dev,'inode':s.st_ino}


def insert(db,table,values,*,ignore=False):
    query=sql.SQL('INSERT INTO {} VALUES({})').format(sql.Identifier(table),sql.SQL(',').join(sql.Placeholder() for _ in values))
    if ignore:query+=sql.SQL(' ON CONFLICT DO NOTHING')
    db.execute(query,values)


def progress(callback,stage,**values):
    if callback:callback({'stage':stage,**values})


@contextmanager
def sqlite_source(path):
    db=sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
    try:yield db
    finally:db.close()


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate source JSON key')
        result[key]=value
    return result


def _zip_info(info):
    return {'date_time':list(info.date_time),'compress_type':info.compress_type,'comment':base64.b64encode(info.comment).decode(),
            'extra':base64.b64encode(info.extra).decode(),'create_system':info.create_system,'create_version':info.create_version,
            'extract_version':info.extract_version,'internal_attr':info.internal_attr,'external_attr':info.external_attr}


def _deck_parts(name):
    return tuple(re.sub(r'^Unit 0*([1-9][0-9]*)',r'Unit \1',re.sub(r'^\d+\s+','',part)) for part in name.split('::')[1:])


def _catalog_bindings(catalog,rows,fields,decks,cards):
    """Use explicit word, unit path and position; reject collisions, never guess."""
    if catalog is None:return {},{}
    entries={};by_word={}
    for entry in catalog['cards']:
        key=(entry['word'],_deck_parts(entry['deckName']),str(entry['position']))
        if key in entries:raise ValueError('catalog identity collision')
        entries[key]=entry;by_word.setdefault(entry['word'],[]).append(entry)
    mapping={};covered=set()
    for row in rows:
        values=dict(zip(fields[str(row['mid'])],row['flds'].split('\x1f')))
        if 'Word' not in values:continue
        word=html.unescape(values['Word']);native=cards[row['id']]
        if len(native)!=1:raise ValueError('catalog vocabulary mapping requires a single original card')
        name=decks[str(native[0]['did'])]['name'];meta=html.unescape(values.get('Meta',''))
        position=meta.rsplit(' ➫ ',1)[-1]
        entry=entries.get((word,_deck_parts(name),position))
        # Supplemental words may retain their origin's position label. The
        # catalog explicitly declares the unique supplemental association.
        if entry is None:
            candidates=[e for e in by_word.get(word,[]) if e.get('supplemental_lexeme') is True and _deck_parts(e['deckName'])==_deck_parts(name)]
            if len(candidates)==1:entry=candidates[0]
        if entry is None or entry['id'] in covered:raise ValueError('no unique exact catalog-to-note binding: '+word)
        mapping[row['id']]=entry['id'];covered.add(entry['id'])
    if covered!={e['id'] for e in catalog['cards']}:raise ValueError('catalog coverage differs from package')
    return mapping,{entry['id']:entry for entry in catalog['cards']}


def import_package(value,package,*,book_id,title,edition,collection=None,catalog=None,expected_sha=None,callback=None):
    package=Path(package).resolve(strict=True);initial=file_state(package);digest=file_sha(package)
    if expected_sha and digest!=expected_sha:raise ValueError('package SHA differs from sealed input')
    catraw=Path(catalog).read_bytes() if catalog else None;cat=json.loads(catraw) if catraw else None
    source_id=c.identity('apkg',book_id,digest,hashlib.sha256(catraw).hexdigest() if catraw else None)
    c.initialize(value)
    with c.connect(value) as db:
        previous=db.execute('select s.id,s.status from book_sources b join sources s on s.id=b.source_id where b.book_id=%s',(book_id,)).fetchone()
        if previous:
            if tuple(previous)!=(source_id,'complete'):raise ValueError('book already has another or incomplete import; preserve it for reconciliation')
            identity=db.execute('select title,edition from books where id=%s',(book_id,)).fetchone()
            if tuple(identity)!=(title,edition):raise ValueError('book identity already belongs to another edition/title')
            return {'book_id':book_id,'source_id':source_id,'already_imported':True}
    progress(callback,'package-start',book_id=book_id,bytes=initial['bytes'])
    with tempfile.TemporaryDirectory(prefix='anki-catalog-source-') as temp,zipfile.ZipFile(package) as archive:
        names=[i.filename for i in archive.infolist()]
        if len(names)!=len(set(names)) or not {'collection.anki2','collection.anki21'}&set(names):raise ValueError('ambiguous or unsupported package members')
        collection_entry='collection.anki21' if 'collection.anki21' in names else 'collection.anki2'
        mapping=json.loads(archive.read('media'),object_pairs_hook=_unique)
        if not isinstance(mapping,dict) or len(set(mapping.values()))!=len(mapping):raise ValueError('invalid media alias map')
        for key,name in mapping.items():
            if not isinstance(key,str) or not key.isdigit() or key not in names or not isinstance(name,str) or Path(name).name!=name or '\\' in name or '\x00' in name:
                raise ValueError('unsafe media alias')
        extras=set(names)-{collection_entry,'media',*mapping}
        if any(Path(name).name!=name or '\\' in name or name.isdigit() for name in extras):raise ValueError('unsafe/unmapped source package members')
        raw_collection=Path(collection).resolve(strict=True) if collection else Path(temp)/collection_entry
        if collection is None:
            with archive.open(collection_entry) as src,raw_collection.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
        else:
            with archive.open(collection_entry) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=file_sha(raw_collection):raise ValueError('external collection differs from exact package member')
        colstate=file_state(raw_collection)
        with sqlite_source(raw_collection) as src:
            colrows=list(src.execute('select * from col'))
            if len(colrows)!=1:raise ValueError('package must have one collection')
            col=dict(colrows[0]);models=json.loads(col['models']);decks=json.loads(col['decks'])
            model_fields={mid:[f['name'] for f in model['flds']] for mid,model in models.items()}
            cards={}
            for row in src.execute('select * from cards order by id'):cards.setdefault(row['nid'],[]).append(dict(row))
            # flds may be large. Only compact note metadata and catalog keys
            # remain in memory; the source cursor reads full fields one at a time.
            notes=list(src.execute('select id,mid,guid,sfld from notes order by id'))
            order={row['id']:index for index,row in enumerate(sorted(notes,key=lambda r:(min(x['due'] for x in cards[r['id']]),r['id'])))}
            bindings,entries=_catalog_bindings(cat,src.execute('select * from notes order by id'),model_fields,decks,cards)
            with c.connect(value) as db,c.transaction(db):
                c.write_lock(db)
                c.ensure_book(db,book_id,title,edition)
                manifest={'input':initial,'sha256':digest,'catalog_sha256':hashlib.sha256(catraw).hexdigest() if catraw else None,'media':mapping,
                          'collection_entry':collection_entry,'collection_zip_info':_zip_info(archive.getinfo(collection_entry)),
                          'media_index_id':c.put_object(db,archive.read('media')),
                          'extra_members':{name:{'object_id':c.put_object(db,archive.read(name)),'zip_info':_zip_info(archive.getinfo(name))} for name in sorted(extras)}}
                insert(db,'sources',(source_id,'apkg',book_id,c.put_json(db,manifest),'building'))
                collection_id=c.put_file(db,raw_collection)
                insert(db,'book_sources',(book_id,source_id,collection_id,c.put_json(db,col)))
                for did,deck in decks.items():
                    parent=next((int(k) for k,v in decks.items() if v['name']==deck['name'].rsplit('::',1)[0]),None) if '::' in deck['name'] else None
                    insert(db,'units',(book_id,int(did),deck['name'],parent,c.put_json(db,deck)))
                for row in src.execute('select * from notes order by id'):
                    data=dict(row);values=data.pop('flds').split('\x1f');fields=model_fields[str(row['mid'])]
                    if len(values)!=len(fields):raise ValueError('note field count differs from its model')
                    is_word='Word' in fields;word=c.ensure_word(db,html.unescape(values[fields.index('Word')])) if is_word else None
                    source_card_id=bindings.get(row['id']);entry=entries.get(source_card_id,{})
                    kind='supplemental' if entry.get('supplemental_lexeme') is True else 'word' if is_word else 'guide'
                    ordinal=next((i for i,e in enumerate(cat['cards']) if e['id']==source_card_id),order[row['id']]) if cat and source_card_id else order[row['id']]
                    # Guides need their own ordinal while catalog word order is
                    # retained exactly. Guide count is normally one, but not assumed.
                    ordinal=ordinal+len([r for r in notes if 'Word' not in model_fields[str(r['mid'])]]) if is_word and cat else ordinal
                    if not is_word and cat:ordinal=sum(1 for r in notes if r['id']<row['id'] and 'Word' not in model_fields[str(r['mid'])])
                    insert(db,'notes',(book_id,row['id'],row['guid'],word,kind,ordinal,row['mid'],c.put_json(db,data),source_card_id))
                    for index,(field,text) in enumerate(zip(fields,values)):
                        component=c.ensure_component(db,word,field,text,scope=book_id+':'+str(row['id']))
                        insert(db,'note_fields',(book_id,row['id'],index,field,component))
                    from . import study_catalog_math
                    if study_catalog_math.required(values):study_catalog_math.install(db)
                    for card in cards[row['id']]:insert(db,'native_cards',(book_id,card['id'],row['id'],card['did'],card['ord'],c.put_json(db,card)))
                for index,(key,name) in enumerate(mapping.items()):
                    raw=archive.read(key)
                    insert(db,'resource_aliases',(book_id,name,c.put_object(db,raw),c.put_json(db,_zip_info(archive.getinfo(key)))))
                    if index and index%5000==0:progress(callback,'package-media',book_id=book_id,completed=index,total=len(mapping))
                if file_state(package)!=initial or file_state(raw_collection)!=colstate or file_sha(package)!=digest:
                    raise ValueError('package/collection changed during import')
                db.execute("update sources set status='complete' where id=%s",(source_id,))
                c.event(db,'import-book',{'book_id':book_id,'source_id':source_id,'notes':len(notes),'media':len(mapping)})
    progress(callback,'package-complete',book_id=book_id,notes=len(notes),media=len(mapping))
    return {'book_id':book_id,'source_id':source_id,'notes':len(notes),'media':len(mapping),'source_sha256':digest}


def _dictionary_binding(record,sense):
    provenance=record['definition_provenance']
    correction=provenance.get('catalog_sense_revisions',{}).get(str(sense['ordinal']))
    if correction is not None:
        if (not isinstance(correction,dict) or correction.get('schema')!='study-catalog-dictionary-correction.v1'
            or not isinstance(correction.get('dictionary'),str) or not correction['dictionary'].strip()
            or not isinstance(correction.get('original_binding'),dict)
            or correction['original_binding'].get('dictionary')!=correction['dictionary']
            or not isinstance(correction.get('reason'),str) or not correction['reason'].strip()
            or any(not isinstance(correction.get(key),str) or not re.fullmatch(r'[0-9a-f]{64}',correction[key])
                   for key in ('entry_html_sha256','evidence_sha256'))):
            raise ValueError('invalid reviewed dictionary provenance correction')
        return correction
    component=next((p for p in provenance.get('components',[]) if p.get('sense_start',0)<=sense['ordinal']<p.get('sense_start',0)+p.get('sense_count',0)),None)
    if component:
        return {'dictionary':component['source'],'entry_html_sha256':component['html_sha256'],
                'sense_ordinal':sense['ordinal']-component['sense_start']}
    return {'dictionary':record['definition_source'],'supplemental_definitions':provenance.get('supplemental_definitions',{}),'ordinal':sense['ordinal']}


def import_analysis(db,record):
    """Normalize exact reviewed facts, preserving every original review seal."""
    book,card=record['book_id'],record['card_id'];word=c.ensure_word(db,record['word'])
    rows=record['occurrences']
    if len(rows)!=record['expected_occurrences']:raise ValueError('active physical count differs from its sealed record')
    insert(db,'analyses',(book,card,word,record['snapshot_id'],c.put_json(db,record),len(rows)))
    senses={}
    for ordinal,sense in enumerate(record['senses']):
        proof=_dictionary_binding(record,sense);sid=c.identity('sense',word,proof,sense['pos'],sense['text'])
        insert(db,'dictionary_senses',(sid,word,proof['dictionary'],sense['pos'],sense['text'],c.put_json(db,proof)),ignore=True)
        insert(db,'analysis_senses',(book,card,ordinal,sense['sense_id'],sid));senses[sense['sense_id']]=sid
    for ordinal,row in enumerate(rows):
        english=row['english'];translation=row['translation'];start,end=row['target_range']
        if not 0<=start<end<=len(english):raise ValueError('physical token range differs from exact text')
        if hashlib.sha256(english.encode()).hexdigest()!=row['english_hash']:raise ValueError('stale source English hash')
        alignment=row.get('alignment');aid=c.put_json(db,alignment) if alignment else None
        english_id=c.put_object(db,english.encode());translation_id=c.put_object(db,translation.encode())
        sentence=c.identity('sentence',row['paper_id'],row['physical_source'],english_id,translation_id,aid)
        insert(db,'sentences',(sentence,row['paper_id'],row['sentence_id'],english_id,translation_id,aid),ignore=True)
        for index,chunk in enumerate((alignment or {}).get('alignments',[])):insert(db,'chunks',(sentence,index,c.put_json(db,chunk)),ignore=True)
        physical=c.put_json(db,row['physical_source']);token=c.identity('token',row['occurrence_id'],word,sentence)
        insert(db,'tokens',(token,row['occurrence_id'],word,sentence,start,end,physical),ignore=True)
        sense=senses.get(row['sense_id'])
        if row['sense_id'] is not None and sense is None:raise ValueError('review points to missing dictionary sense')
        decision=c.identity('decision',word,token,sense,row['status'],row['reason'],row['method'])
        insert(db,'decisions',(decision,word,token,sense,row['status'],row['reason'],row['method']),ignore=True)
        insert(db,'analysis_occurrences',(book,card,ordinal,row['occurrence_id'],token,decision,c.put_json(db,row)))


def _sql_name(name):return '"'+name.replace('"','""')+'"'


def _bounded_rows(cursor,maximum,byte_limit=8*1024*1024):
    rows=[];size=0
    while len(rows)<maximum:
        row=cursor.fetchone()
        if row is None:break
        rows.append(row)
        # Conservative Unicode estimate avoids allocating another huge encoding
        # merely to decide where a batch ends. One source row remains atomic.
        size+=sum(len(v)*4 if isinstance(v,str) else len(v) if isinstance(v,bytes) else 32 for v in row)
        if size>=byte_limit:break
    return rows


def capacity_guard(path,minimum):
    if path is not None and shutil.disk_usage(path).free<minimum:
        important=important_capacity(path)
        if important is None or important<minimum:
            raise OSError(errno.ENOSPC,'insufficient allocatable storage for safe catalog migration; committed resume rows retained')


def import_sqlite_history(value,path,*,kind='semantic',callback=None,batch_size=250,space_guard=None,min_free_bytes=2*1024**3):
    """Archive every source table/row and project active review facts separately.

    Committed building imports remain visibly incomplete after interruption.
    Reruns verify the input seal and resume exact row ordinals. Consumers only
    accept completed sources. No source DDL is executed in PostgreSQL.
    """
    path=Path(path).resolve(strict=True);initial=file_state(path);digest=file_sha(path)
    wal=Path(str(path)+'-wal')
    if wal.exists() and wal.stat().st_size:raise ValueError('checkpoint the source WAL before immutable history import')
    sid=c.identity('sqlite-archive',kind,digest);c.initialize(value)
    with c.connect(value) as db:
        prior=db.execute('select status from sources where id=%s',(sid,)).fetchone()
        if prior and prior[0]=='complete':return {'source_id':sid,'already_imported':True}
        if not prior:
            with c.transaction(db):
                c.write_lock(db)
                insert(db,'sources',(sid,kind,path.name,c.put_json(db,{'input':initial,'sha256':digest}),'building'))
    counts={}
    with sqlite_source(path) as src,c.connect(value) as db:
        definitions=list(src.execute("select name,sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name"))
        for name,definition in definitions:
            columns=[r[1] for r in src.execute('pragma table_info('+_sql_name(name)+')')]
            with c.transaction(db):
                insert(db,'archive_tables',(sid,name,c.put_object(db,definition.encode()),c.put_json(db,columns),0,None),ignore=True)
            count=db.execute('select count(*) from archive_rows where source_id=%s and table_name=%s',(sid,name)).fetchone()[0]
            previous=db.execute('select row_count,row_digest from archive_tables where source_id=%s and name=%s',(sid,name)).fetchone()
            expected=src.execute('select count(*) from '+_sql_name(name)).fetchone()[0]
            if previous[1] is not None and previous[0]==count==expected:
                counts[name]=count;progress(callback,'archive-table-already-complete',table=name,rows=count)
                continue
            cursor=src.execute('select * from '+_sql_name(name)+' order by rowid limit -1 offset ?',(count,));hasher=hashlib.sha256()
            # The digest covers original rows, independent of batching/retries.
            if count:
                for row in src.execute('select * from '+_sql_name(name)+' order by rowid limit ?',(count,)):
                    hasher.update(c.canonical([c._pack_cell(v) for v in row]).encode()+b'\n')
            while True:
                capacity_guard(space_guard,min_free_bytes)
                rows=_bounded_rows(cursor,batch_size)
                if not rows:break
                with c.transaction(db):
                    from .study_catalog_archive import write_batch
                    count=write_batch(db,sid,name,count,rows,hasher)
                if count%5000<batch_size:progress(callback,'archive-table',table=name,rows=count)
            if count!=expected:raise ValueError('source history row count differs')
            with c.transaction(db):db.execute('update archive_tables set row_count=%s,row_digest=%s where source_id=%s and name=%s',(count,hasher.hexdigest(),sid,name))
            counts[name]=count;progress(callback,'archive-table-complete',table=name,rows=count)
        if kind=='semantic':
            already={(r[0],r[1]):r[2] for r in db.execute('select book_id,source_card_id,record_id from analyses')}
            for index,(raw,) in enumerate(src.execute('select s.payload from snapshots s join active_snapshots a on s.id=a.snapshot_id order by a.book_id,a.card_id')):
                record=json.loads(raw)
                old=already.get((record['book_id'],record['card_id']))
                if old:
                    if old!=hashlib.sha256(c.canonical(record).encode()).hexdigest():raise ValueError('new source conflicts with an existing active analysis')
                    continue
                capacity_guard(space_guard,min_free_bytes)
                with c.transaction(db):
                    from .study_catalog_normalize import import_analysis as batch_import_analysis
                    batch_import_analysis(db,record)
                if index%100==0:progress(callback,'active-analysis',completed=index)
        if file_state(path)!=initial or file_sha(path)!=digest:raise ValueError('source history changed; staged import not activated')
        with c.transaction(db):
            db.execute("update sources set status='complete' where id=%s",(sid,));c.event(db,'import-source-history',{'source_id':sid,'counts':counts})
    return {'source_id':sid,'tables':counts,'source_sha256':digest}
