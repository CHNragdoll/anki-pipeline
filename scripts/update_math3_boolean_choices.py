"""Refresh only shared Boolean interactions; leave all card fields intact."""
from pathlib import Path
import argparse, copy, hashlib, json, re
from anki_pipeline import study_catalog as c, study_catalog_presentation as p
from anki_pipeline.study_catalog_anki import bump_model_mods
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_exam_package import CHOICE_SCRIPT, CSS
from anki_pipeline.study_exam_refresh import _backup
from scripts.deliver_math3_details import stable_rows
from scripts.update_exam_visible_cleanup import finish

ROOT=Path(__file__).resolve().parents[1]
BID='math3-exams'
DELIVERY=ROOT/'output/math3-boolean-choices-20261103'
BASE=ROOT/'output/math3-display-clean-20261103/Math3-Past-Exams-Full-20261103.apkg'
BOOLEAN_CSS=CSS[CSS.index('.exam-boolean-choices{'):]

def main():
    global DELIVERY, BASE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery',type=Path,default=DELIVERY)
    parser.add_argument('--baseline',type=Path,default=BASE)
    args=parser.parse_args();DELIVERY=args.delivery.resolve();BASE=args.baseline.resolve()
    assert DELIVERY.is_relative_to(ROOT/'output') and BASE.is_file()
    DELIVERY.mkdir(exist_ok=True)
    target=c.Target(c.DEFAULT_DSN,'study_catalog')
    with c.connect(target) as db,c.transaction(db):
        c.write_lock(db)
        backup,sha=_backup(db,BID,ROOT/'backups'/DELIVERY.name)
        tables=['notes','note_fields','native_cards','resource_aliases']
        tables += [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'study_progress%'")]
        before={t:stable_rows(db,t) for t in tables}
        original=copy.deepcopy(p.registry(db));registry=copy.deepcopy(original);changed=0
        for mid,parts in registry['books'][BID]['models'].items():
            for name in ['qfmt:0','afmt:0']:
                oid=db.execute('SELECT current_id FROM components WHERE id=%s',(parts[name],)).fetchone()[0]
                text=c.get_object(db,oid).decode()
                matches=list(re.finditer(r'<script>\(function\(\)\{[\s\S]*?</script>',text))
                scripts=[m for m in matches if 'var type=record.questionType' in m.group()]
                assert len(scripts)==1,(name,len(scripts))
                m=scripts[0];text=text[:m.start()]+CHOICE_SCRIPT+text[m.end():]
                parts[name]=c.ensure_component(db,None,'template:'+name,text,scope='presentation');changed+=1
            oid=db.execute('SELECT current_id FROM components WHERE id=%s',(parts['css'],)).fetchone()[0]
            css=c.get_object(db,oid).decode()
            if BOOLEAN_CSS not in css:css+='\n'+BOOLEAN_CSS
            parts['css']=c.ensure_component(db,None,'template:css',css,scope='presentation')
        other_before=copy.deepcopy(original);other_after=copy.deepcopy(registry)
        other_before['books'].pop(BID);other_after['books'].pop(BID);assert other_before==other_after
        db.execute('UPDATE metadata SET value=%s WHERE key=%s',(c.put_json(db,registry),p.REGISTRY))
        bump_model_mods(db,[(BID,mid) for mid in registry['books'][BID]['models']])
        assert before=={t:stable_rows(db,t) for t in tables}
    receipt=dict(backup=backup,backup_sha256=sha,changed_templates=changed,fields_identities_media_learning_unchanged=True)
    (DELIVERY/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    for fmt,dest in [('apkg',DELIVERY/'questions.apkg'),('web',DELIVERY/'web')]:
        print('EXPORT',fmt,flush=True);receipt[fmt]=export_book(target,BID,dest,format=fmt)
    package=DELIVERY/'Math3-Past-Exams-Full-20261103.apkg'
    finish(DELIVERY/'questions.apkg',BASE,package)
    receipt.update(package=str(package),sha256=hashlib.sha256(package.read_bytes()).hexdigest(),bytes=package.stat().st_size)
    (DELIVERY/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print('COMPLETE',receipt['sha256'],flush=True)
if __name__=='__main__':main()
