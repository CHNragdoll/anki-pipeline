"""Restore source punctuation, applying only the owner's comma/full-stop rule."""
from pathlib import Path
import json
from anki_pipeline import study_catalog as c
from anki_pipeline.study_exam_source import _halfwidth_display_text, _omit_standalone_question_number
from anki_pipeline.study_catalog_anki import bump_content_mods
from anki_pipeline.study_exam_refresh import _backup
from scripts.deliver_math3_details import stable_rows
import re
ROOT=Path(__file__).resolve().parents[1]
def main():
 with c.connect(c.Target(c.DEFAULT_DSN,'study_catalog')) as db,c.transaction(db):
  c.write_lock(db);backup,sha=_backup(db,'math3-exams',ROOT/'backups/math3-punctuation-scope-20261103')
  frozen={t:stable_rows(db,t) for t in ['notes','native_cards','resource_aliases']}
  audits=stable_rows(db,'note_fields',"WHERE book_id<>'math3-exams' OR name NOT IN ('Question','Answer')")
  progress=[r[0] for r in db.execute("select tablename from pg_tables where schemaname=current_schema() and tablename like 'study_progress%'")]
  learning={t:stable_rows(db,t) for t in progress};changed=[]
  titles={n:c.get_object(db,o).decode() for n,o in db.execute("select f.note_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.book_id='math3-exams' and f.name='Title'")}
  for nid,name,cid,oid in db.execute("select f.note_id,f.name,f.component_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.book_id='math3-exams' and f.name in ('Question','Answer')").fetchall():
   rev=db.execute("select before_id from component_revisions where component_id=%s and reason='visible punctuation labels and standalone question number cleanup' order by id limit 1",(cid,)).fetchone()
   if rev:
    chain=db.execute("select before_id,after_id,reason from component_revisions where component_id=%s and id >= (select min(id) from component_revisions where component_id=%s and reason='visible punctuation labels and standalone question number cleanup') order by id",(cid,cid)).fetchall()
    previous=rev[0]
    for old,new,reason in chain:
     assert old==previous and reason in {'visible punctuation labels and standalone question number cleanup','owner narrowed punctuation to comma and full stop only'}, (cid,'unrecognized revision chain')
     previous=new
    assert previous==oid, (cid,'unrecorded current change')
   text=c.get_object(db,rev[0] if rev else oid).decode()
   after=_halfwidth_display_text(text)
   if name=='Question':
    number=re.search(r'第\s*(\d+)\s*题',titles[nid]);assert number
    after=_omit_standalone_question_number(after,number[1])
   if after==c.get_object(db,oid).decode():continue
   key=c.put_object(db,after.encode());assert db.execute('update components set current_id=%s where id=%s and current_id=%s',(key,cid,oid)).rowcount==1
   db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) values(%s,%s,%s,%s,%s)',(cid,oid,key,'owner narrowed punctuation to comma and full stop only',c.now()));changed.append(('math3-exams',nid))
  bump_content_mods(db,changed)
  assert frozen=={t:stable_rows(db,t) for t in frozen}
  assert audits==stable_rows(db,'note_fields',"WHERE book_id<>'math3-exams' OR name NOT IN ('Question','Answer')")
  assert learning=={t:stable_rows(db,t) for t in progress}
  receipt={'backup':backup,'backup_sha256':sha,'changed_fields':len(changed),'identities_media_learning_unchanged':True}
 (ROOT/'backups/math3-punctuation-scope-20261103/receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print(receipt)
if __name__=='__main__':main()
