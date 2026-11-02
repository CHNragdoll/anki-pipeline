"""Apply one display-only rule to registered exam books and export both hosts."""
from pathlib import Path
import copy,hashlib,json,sqlite3,tempfile,zipfile,re
from anki_pipeline import study_catalog as c,study_catalog_presentation as presentation
from anki_pipeline.study_catalog_math import displaystyle_markup
from anki_pipeline.study_exam_source import _halfwidth_display_text, _omit_standalone_question_number
from anki_pipeline.study_catalog_anki import bump_content_mods,bump_model_mods
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_exam_refresh import _backup
from scripts.deliver_math3_details import stable_rows

ROOT=Path(__file__).resolve().parents[1]
JOBS=[('politics-exams-2003-2023','politics','考研政治历年真题',832,'politics-displaystyle-20261103/Politics-Past-Exams-Full-20261103.apkg'),('cs408-exams','cs408','考研408历年真题',799,'cs408-displaystyle-20261103/CS408-Past-Exams-Full-20261103.apkg'),('math3-exams','math3','考研数学三历年真题',1060,'math3-displaystyle-final-20261103/Math3-Past-Exams-Full-20261103.apkg')]
CENTER='.exam-body .choice{align-items:center}.exam-body .choice>b{align-self:center}.exam-body .choice mjx-container{vertical-align:middle}'

def finish(source,baseline,target):
    """Carry forward exact existing guide and deck names, keeping question rows."""
    with tempfile.TemporaryDirectory() as folder,zipfile.ZipFile(source) as incoming,zipfile.ZipFile(baseline) as prior:
        path=Path(folder)/'collection.anki2';old=Path(folder)/'old.anki2'
        path.write_bytes(incoming.read('collection.anki2'));old.write_bytes(prior.read('collection.anki2'))
        db=sqlite3.connect(path);before=sqlite3.connect(old)
        models=json.loads(db.execute('select models from col').fetchone()[0]);original=json.loads(before.execute('select models from col').fetchone()[0])
        ids={r[0] for r in db.execute('select id from notes')};guides=[r for r in before.execute('select * from notes') if r[0] not in ids]
        assert len(guides)==1
        note=guides[0];models[str(note[2])]=original[str(note[2])]
        db.execute('insert into notes values('+','.join('?'*len(note))+')',note)
        cards=before.execute('select * from cards where nid=?',(note[0],)).fetchall();assert len(cards)==1
        card=cards[0];db.execute('insert into cards values('+','.join('?'*len(card))+')',card)
        old_decks=before.execute('select decks from col').fetchone()[0]
        old_cards=dict(before.execute('select id,did from cards'))
        assert set(old_cards)=={r[0] for r in db.execute('select id from cards')}
        for cid,did in old_cards.items():db.execute('update cards set did=? where id=?',(did,cid))
        db.execute('update col set models=?,decks=?',(json.dumps(models,ensure_ascii=False),old_decks));db.commit()
        assert db.execute('pragma quick_check').fetchone()[0]=='ok'
        db.close();before.close()
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as out:
            for item in incoming.infolist():
                out.writestr(item.filename,path.read_bytes() if item.filename=='collection.anki2' else incoming.read(item.filename))

def main():
    target=c.Target(c.DEFAULT_DSN,'study_catalog');results=[]
    for bid,slug,title,count,baseline in JOBS:
        delivery=ROOT/'output'/f'{slug}-display-clean-20261103';delivery.mkdir(exist_ok=True)
        with c.connect(target) as db,c.transaction(db):
            c.write_lock(db);backup,backup_sha=_backup(db,bid,ROOT/'backups'/delivery.name)
            state={t:stable_rows(db,t,'WHERE book_id=%s'.replace('%s',"'"+bid+"'")) for t in ['notes','native_cards','resource_aliases']}
            other={t:stable_rows(db,t,"WHERE book_id<>'"+bid+"'") for t in ['notes','note_fields','native_cards','resource_aliases']}
            progress=[r[0] for r in db.execute("select tablename from pg_tables where schemaname=current_schema() and tablename like 'study_progress%'")]
            progress_before={t:stable_rows(db,t) for t in progress}
            audit_before=stable_rows(db,'note_fields',"WHERE book_id='"+bid+"' AND name NOT IN ('Question','Answer')")
            titles={nid:c.get_object(db,oid).decode() for nid,oid in db.execute("select f.note_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.book_id=%s and f.name='Title'",(bid,))}
            rows=list(db.execute("select f.note_id,f.name,f.component_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.book_id=%s and f.name in ('Question','Answer')",(bid,)));changed=[]
            for nid,name,component,oid in rows:
                text=c.get_object(db,oid).decode();after=displaystyle_markup(text)
                if slug=='math3':after=_halfwidth_display_text(after)
                if name=='Question':
                    match=re.search(r'第\s*(\d+)\s*题',titles[nid])
                    if match:after=_omit_standalone_question_number(after,match[1])
                if after==text:continue
                assert db.execute('select count(*) from note_fields where component_id=%s',(component,)).fetchone()[0]==1
                key=c.put_object(db,after.encode());assert db.execute('update components set current_id=%s where id=%s and current_id=%s',(key,component,oid)).rowcount==1
                db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) values(%s,%s,%s,%s,%s)',(component,oid,key,'visible punctuation labels and standalone question number cleanup',c.now()));changed.append((bid,nid))
            registry=copy.deepcopy(presentation.registry(db));mids=[]
            for mid,parts in registry['books'][bid]['models'].items():
                component=parts['css'];oid=db.execute('select current_id from components where id=%s',(component,)).fetchone()[0];css=c.get_object(db,oid).decode()
                if CENTER not in css:parts['css']=c.ensure_component(db,None,'template:css',css+'\n'+CENTER,scope='presentation')
                mids.append((bid,mid))
            db.execute('update metadata set value=%s where key=%s',(c.put_json(db,registry),presentation.REGISTRY));bump_content_mods(db,changed);bump_model_mods(db,mids)
            assert state=={t:stable_rows(db,t,"WHERE book_id='"+bid+"'") for t in state}
            assert other=={t:stable_rows(db,t,"WHERE book_id<>'"+bid+"'") for t in other}
            assert progress_before=={t:stable_rows(db,t) for t in progress}
            assert audit_before==stable_rows(db,'note_fields',"WHERE book_id='"+bid+"' AND name NOT IN ('Question','Answer')")
        receipt=dict(book_id=bid,changed_fields=len(changed),backup=backup,backup_sha256=backup_sha,identities_media_learning_preserved=True,source_record_unchanged=True)
        (delivery/'receipt.json').write_text(json.dumps(receipt,indent=2));print('EXPORT',slug,flush=True)
        receipt['apkg']=export_book(target,bid,delivery/'questions.apkg',format='apkg');receipt['web']=export_book(target,bid,delivery/'web',format='web')
        package=delivery/(({'politics':'Politics','cs408':'CS408','math3':'Math3'}[slug])+'-Past-Exams-Full-20261103.apkg');finish(delivery/'questions.apkg',ROOT/'output'/baseline,package)
        receipt.update(package=str(package),bytes=package.stat().st_size,sha256=hashlib.sha256(package.read_bytes()).hexdigest(),cards=count+1)
        (delivery/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));results.append(receipt);print('DONE',slug,receipt['sha256'],flush=True)
    print('BOTH_COMPLETE',flush=True)
if __name__=='__main__':main()
