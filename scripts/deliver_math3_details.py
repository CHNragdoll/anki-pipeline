"""Refresh only the registered Math III book and export its shared hosts."""
from pathlib import Path
import argparse
import copy
import hashlib
import json
from anki_pipeline import study_catalog as c, study_catalog_presentation as p
from anki_pipeline.study_exam_refresh import refresh
from anki_pipeline.study_catalog_anki import bump_model_mods
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_exam_package import FRONT, BACK, CSS
from anki_pipeline.study_exam_guide import add_guide

ROOT=Path(__file__).resolve().parents[1]
DELIVERY=ROOT/'output/math3-details-delivery-20261102'
BID='math3-exams'

def stable_rows(db,table,where=''):
    rows=db.execute('SELECT row_to_json(t)::text FROM '+table+' t '+where).fetchall()
    return hashlib.sha256('\n'.join(sorted(r[0] for r in rows)).encode()).hexdigest()

def main():
    global DELIVERY
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery',type=Path,default=DELIVERY)
    parser.add_argument('--package-name',default='Math3-Past-Exams-Full-20261102.apkg')
    args=parser.parse_args()
    DELIVERY=args.delivery.resolve()
    if not DELIVERY.is_relative_to((ROOT/'output').resolve()):
        raise ValueError('delivery must remain within project output')
    target=c.Target(c.DEFAULT_DSN,'study_catalog')
    report=json.loads((DELIVERY/'source/source-report.json').read_text())
    snapshot=json.loads((DELIVERY/'source/source-snapshot.json').read_text())
    assert report['notes']==len(snapshot['questions']) and report['years']==len(snapshot['papers'])
    if Path(args.package_name).name!=args.package_name or not args.package_name.endswith('.apkg'):
        raise ValueError('package name must be a local APKG filename')
    with c.connect(target) as db,c.transaction(db):
        c.write_lock(db)
        old_ids=set(db.execute('SELECT note_id,guid FROM notes WHERE book_id=%s',(BID,)))
        old_cards=set(db.execute('SELECT native_id,note_id,unit_id,payload_id FROM native_cards WHERE book_id=%s',(BID,)))
        tables=[r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'study_progress%'")]
        baseline={table:stable_rows(db,table) for table in tables}
        other={table:stable_rows(db,table,"WHERE book_id<>'math3-exams'") for table in ['notes','note_fields','native_cards','resource_aliases']}
        source=db.execute('SELECT source_id FROM book_sources WHERE book_id=%s',(BID,)).fetchone()[0]
        receipt=refresh(db,DELIVERY/'source/source.apkg',book_id=BID,title='考研数学三历年真题',edition=max(paper['year'] for paper in snapshot['papers']),
            expected_source=source,backup_dir=ROOT/'backups'/DELIVERY.name)
        assert old_ids<=set(db.execute('SELECT note_id,guid FROM notes WHERE book_id=%s',(BID,)))
        assert old_cards<=set(db.execute('SELECT native_id,note_id,unit_id,payload_id FROM native_cards WHERE book_id=%s',(BID,)))
        prior=copy.deepcopy(p.registry(db));data=copy.deepcopy(prior)
        for mid,parts in data['books'][BID]['models'].items():
            for name,text in [('css',CSS),('qfmt:0',FRONT),('afmt:0',BACK)]:
                parts[name]=c.ensure_component(db,None,'template:'+name,text,scope='presentation')
        db.execute('UPDATE metadata SET value=%s WHERE key=%s',(c.put_json(db,data),p.REGISTRY))
        bump_model_mods(db,[(BID,mid) for mid in data['books'][BID]['models']])
        prior['books'].pop(BID);data['books'].pop(BID);assert prior==data
        assert baseline=={table:stable_rows(db,table) for table in tables}
        assert other=={table:stable_rows(db,table,"WHERE book_id<>'math3-exams'") for table in other}
        receipt.update(old_identities_preserved=len(old_ids),old_native_cards_preserved=len(old_cards),other_books_unchanged=True,learning_records_unchanged=True)
    (DELIVERY/'refresh-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    for fmt,path in [('apkg',DELIVERY/'questions.apkg'),('web',DELIVERY/'web')]:
        print('EXPORT',fmt,flush=True)
        report[fmt]=export_book(target,BID,path,format=fmt)
        (DELIVERY/'export-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    report['guide']=add_guide(DELIVERY/'questions.apkg',DELIVERY/args.package_name,book_id=BID,
        root='考研数学三历年真题',question_count=report['notes'],guide_html=(DELIVERY/'guide.html').read_text())
    (DELIVERY/'export-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
