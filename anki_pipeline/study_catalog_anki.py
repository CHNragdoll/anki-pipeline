"""Native field cache rules, shared by new mappings and later exports."""
import hashlib
import html
import re
import json
import time


def strip_html_media(value):
    value=re.sub(r'(?is)<!--.*?-->|<(script|style)\b[^>]*>.*?</\1\s*>','',value)
    def image(match):
        src=re.search(r'''(?is)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))''',match[0])
        return ' '+next((x for x in src.groups() if x is not None),'')+' ' if src else ''
    value=re.sub(r'(?is)<img\b[^>]*>',image,value)
    return html.unescape(re.sub(r'(?s)<[^>]*>','',value)).replace('\xa0',' ')


def field_cache(fields,model):
    ordinal=model.get('sortf',0)
    if type(ordinal) is not int or not 0<=ordinal<len(fields):raise ValueError('invalid native sort field')
    return strip_html_media(fields[ordinal]),int(hashlib.sha1(strip_html_media(fields[0]).encode()).hexdigest()[:8],16)


MODS='native.content-mods.v1'
MODEL_MODS='native.model-mods.v1'
RUNTIME_REVISIONS='native.runtime-revisions.v1'


def content_mods(db):
    row=db.execute('select value from metadata where key=%s',(MODS,)).fetchone()
    return json.loads(row[0]) if row else {}


def model_mods(db):
    """Persist model versions separately from immutable imported model bytes."""
    row=db.execute('select value from metadata where key=%s',(MODEL_MODS,)).fetchone()
    return json.loads(row[0]) if row else {}


def runtime_revisions(db):
    row=db.execute('select value from metadata where key=%s',(RUNTIME_REVISIONS,)).fetchone()
    return json.loads(row[0]) if row else {}


def effective_content_mod(original,content,runtime):
    if not runtime:return content
    if isinstance(runtime,int):runtime={'revision':runtime,'floor':0}
    return max(original,content or 0,runtime['floor'])+runtime['revision']


def _advance_runtime_revisions(db,books,*,initialize=False):
    from . import study_catalog as c
    data=runtime_revisions(db)
    for book in set(books):
        if not initialize or book not in data:
            previous=data.get(book,{'revision':0,'floor':0})
            if isinstance(previous,int):previous={'revision':previous,'floor':0}
            # Keep registered delivery policies. A later runtime revision makes
            # their old version seal stale; it must never silently disable them.
            data[book]={**previous,'revision':previous['revision']+1,'floor':max(int(time.time()),previous['floor'])}
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (RUNTIME_REVISIONS,c.canonical(data)))


def bump_content_mods(db,notes):
    from . import study_catalog as c
    data=content_mods(db);runtimes=runtime_revisions(db)
    for book,nid in set(notes):
        row=db.execute('select payload_id from notes where book_id=%s and note_id=%s',(book,nid)).fetchone()
        if row is None:raise ValueError('cannot version missing native note')
        original=c.get_json(db,row[0])['mod'];key=c.identity(book,nid)
        previous=effective_content_mod(original,data.get(key),runtimes.get(book)) or original
        data[key]=max(int(time.time()),previous+1,original+1)
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',(MODS,c.canonical(data)))


def bump_component_mods(db,component):
    """Version every native identity affected by one shared component edit.

    Called under the catalog write lock in the same transaction as the edit.
    Versions must survive a text revert: comparing current bytes with the sealed
    source during export cannot tell whether a learner already imported B.
    """
    from . import study_catalog_presentation as presentation
    from psycopg import sql

    notes=db.execute('select book_id,note_id from note_fields where component_id=%s',(component,)).fetchall()
    if notes:bump_content_mods(db,notes)
    affected=[];runtime_books=[]
    for book,binding in presentation.registry(db)['books'].items():
        runtime_changed=component in binding.get('resources',{}).values()
        if runtime_changed:runtime_books.append(book)
        for mid,parts in binding.get('models',{}).items():
            if runtime_changed or component in parts.values():affected.append((book,mid))
    if affected:bump_model_mods(db,affected)
    if runtime_books:_advance_runtime_revisions(db,runtime_books)
    model_groups={}
    for book,mid in affected:model_groups.setdefault(book,set()).add(int(mid))
    conditions=[];params=[component]
    for book,mids in sorted(model_groups.items()):
        conditions.append(sql.SQL('(book_id=%s and model_id=ANY(%s))'));params.extend((book,list(mids)))
    if runtime_books:conditions.append(sql.SQL('book_id=ANY(%s)'));params.append(runtime_books)
    predicate=sql.SQL(' OR ').join(conditions) if conditions else sql.SQL('FALSE')
    count=db.execute(sql.SQL('select count(*) from (select book_id,note_id from note_fields where component_id=%s '
                            'union select book_id,note_id from notes where {}) affected').format(predicate),params).fetchone()[0]
    return {'affected_notes':count,'affected_models':len(set(affected)),
            'affected_books':sorted({book for book,_ in notes}|set(model_groups)|set(runtime_books))}


def bump_model_mods(db,models):
    """Advance committed native model versions under the catalog write lock."""
    from . import study_catalog as c

    data=model_mods(db)
    originals={}
    for book,mid in set(models):
        if book not in originals:
            row=db.execute('select col_payload_id from book_sources where book_id=%s',(book,)).fetchone()
            if row is None:raise ValueError('cannot version missing native model source')
            originals[book]=json.loads(c.get_json(db,row[0])['models'])
        original=originals[book][mid]['mod'];key=c.identity(book,mid)
        data[key]=max(int(time.time()),data.get(key,original)+1,original+1)
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (MODEL_MODS,c.canonical(data)))


def initialize_model_mods(db,book,binding):
    """Bind an already revised shared template to a newly mapped book once.

    Existing bindings may predate model version tracking. Re-registering fills
    only missing versions and never increments an existing version. Even a
    component restored to its original bytes has revision history, so it still
    needs a newer version than the sealed native model.
    """
    from . import study_catalog as c

    versions=model_mods(db)
    resources=list(set(binding.get('resources',{}).values()))
    runtime_changed=bool(resources) and db.execute(
        'select exists(select 1 from component_revisions where component_id=ANY(%s))',(resources,)).fetchone()[0]
    if runtime_changed:_advance_runtime_revisions(db,[book],initialize=True)
    affected=[]
    for mid,parts in binding.get('models',{}).items():
        if c.identity(book,mid) in versions:continue
        revised=runtime_changed or db.execute('select exists(select 1 from component_revisions where component_id=ANY(%s))',
                                             (list(set(parts.values())),)).fetchone()[0]
        if revised:affected.append((book,mid))
    if affected:bump_model_mods(db,affected)
