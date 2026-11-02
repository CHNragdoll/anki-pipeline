"""Apply the nine source-evidenced Politics type corrections without content edits."""
from pathlib import Path
import copy, hashlib, html, json, re, sqlite3, tempfile, zipfile
import genanki
from anki_pipeline import study_catalog as c, study_catalog_units as units
from anki_pipeline.study_catalog_anki import bump_content_mods
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_exam_refresh import _backup
from anki_pipeline.study_exam_package import _number
from anki_pipeline.study_politics_types import projected_question_type
from scripts.deliver_math3_details import stable_rows

ROOT = Path(__file__).resolve().parents[1]
BID = 'politics-exams-2003-2023'
DELIVERY = ROOT/'output/politics-discrimination-20261103'
BASELINE = ROOT/'output/politics-display-clean-20261103/Politics-Past-Exams-Full-20261103.apkg'


def finish_with_guide(source, baseline, target):
    """Copy exactly the old guide; retain newly exported question deck mappings."""
    with tempfile.TemporaryDirectory() as folder, zipfile.ZipFile(source) as incoming, zipfile.ZipFile(baseline) as old:
        path = Path(folder)/'collection.anki2'; path.write_bytes(incoming.read('collection.anki2'))
        before = sqlite3.connect(':memory:'); before.deserialize(old.read('collection.anki2'))
        db = sqlite3.connect(path)
        try:
            ids = {row[0] for row in db.execute('SELECT id FROM notes')}
            guides = [row for row in before.execute('SELECT * FROM notes') if row[0] not in ids]
            if len(guides) != 1: raise ValueError('exactly one retained guide required')
            guide = guides[0]
            cards = list(before.execute('SELECT * FROM cards WHERE nid=?', (guide[0],)))
            if len(cards) != 1: raise ValueError('guide must have exactly one card')
            guide_card = cards[0]
            models, decks = [json.loads(db.execute('SELECT '+name+' FROM col').fetchone()[0]) for name in ('models','decks')]
            old_models, old_decks = [json.loads(before.execute('SELECT '+name+' FROM col').fetchone()[0]) for name in ('models','decks')]
            models[str(guide[2])] = old_models[str(guide[2])]
            decks[str(guide_card[2])] = old_decks[str(guide_card[2])]
            root = old_decks[str(guide_card[2])]['name'].split('::')[0]
            for deck in decks.values():
                if '::' in deck['name']:
                    deck['name'] = root + '::' + deck['name'].split('::', 1)[1]
                elif deck['name'] != 'Default':
                    deck['name'] = root
            db.execute('INSERT INTO notes VALUES('+','.join('?' for _ in guide)+')', guide)
            db.execute('INSERT INTO cards VALUES('+','.join('?' for _ in guide_card)+')', guide_card)
            db.execute('UPDATE col SET models=?,decks=?', (json.dumps(models,ensure_ascii=False),json.dumps(decks,ensure_ascii=False)))
            db.commit()
            assert db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT count(*) FROM notes').fetchone()[0] == 833
        finally: db.close(); before.close()
        with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED) as out:
            for item in incoming.infolist():
                out.writestr(item.filename,path.read_bytes() if item.filename=='collection.anki2' else incoming.read(item.filename))


def apply(target, delivery):
    with c.connect(target) as db, c.transaction(db):
        c.write_lock(db)
        backup, backup_sha = _backup(db,BID,ROOT/'backups'/delivery.name)
        protected = {t:stable_rows(db,t) for t in ('notes','native_cards','resource_aliases')}
        other = {t:stable_rows(db,t,"WHERE book_id<>'"+BID+"'") for t in ('note_fields','units')}
        progress = [r[0] for r in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename LIKE 'study_progress%'")]
        learning = {t:stable_rows(db,t) for t in progress}
        content = stable_rows(db,'note_fields',"WHERE book_id='"+BID+"' AND name NOT IN ('Title','SourceRecord')")
        binding = units.registry(db).get(BID)
        if binding is None: raise ValueError('explicit existing political unit map required')
        decks, membership = copy.deepcopy(binding['units']), copy.deepcopy(binding['cards'])
        changed = []
        title_rows = list(db.execute("SELECT f.note_id,c.current_id FROM note_fields f JOIN components c ON c.id=f.component_id WHERE f.book_id=%s AND f.name='Title'",(BID,)))
        for nid, title_oid in title_rows:
            title = html.unescape(c.get_object(db,title_oid).decode())
            match = re.fullmatch(r'(200[345]) · 材料分析题 · 第 (3[123]) 题', title)
            if not match: continue
            year, number = map(int,match.groups())
            rows = {name:(component,oid) for name,component,oid in db.execute("SELECT f.name,f.component_id,c.current_id FROM note_fields f JOIN components c ON c.id=f.component_id WHERE f.book_id=%s AND f.note_id=%s AND f.name IN ('Title','SourceRecord')",(BID,nid))}
            record = json.loads(html.unescape(c.get_object(db,rows['SourceRecord'][1]).decode()))
            assert record['paper']['year']==year and str(record['question']['number'])==str(number)
            assert projected_question_type('politics',year,record['question'],'free_response')=='discrimination'
            record['question_type_label']='辨析题'
            values={'Title':html.escape(title.replace('材料分析题','辨析题')), 'SourceRecord':html.escape(json.dumps(record,ensure_ascii=False,separators=(',',':')))}
            for name,text in values.items():
                component,oid=rows[name]
                assert db.execute('SELECT count(*) FROM note_fields WHERE component_id=%s',(component,)).fetchone()[0]==1
                after=c.put_object(db,text.encode())
                assert db.execute('UPDATE components SET current_id=%s WHERE id=%s AND current_id=%s',(after,component,oid)).rowcount==1
                db.execute('INSERT INTO component_revisions(component_id,before_id,after_id,reason,created_at) VALUES(%s,%s,%s,%s,%s)',(component,oid,after,'verified 2003-2005 politics discrimination section',c.now()))
            cid=db.execute('SELECT native_id FROM native_cards WHERE book_id=%s AND note_id=%s',(BID,nid)).fetchone()[0]
            old_deck=decks[str(membership[str(cid)])]
            assert old_deck['name'].endswith(str(year)+' 年::材料分析题')
            did=_number('exam-unit',BID+':'+str(year)+':discrimination')
            deck=genanki.Deck(did,old_deck['name'].rsplit('::',1)[0]+'::辨析题').to_json()
            if str(did) in decks: assert decks[str(did)]['name']==deck['name']
            else: decks[str(did)]=deck
            membership[str(cid)]=did
            changed.append({'note_id':nid,'native_id':cid,'year':year,'number':number,'before_deck':old_deck['name'],'after_deck':deck['name']})
        assert {(r['year'],r['number']) for r in changed}=={(year,number) for year in (2003,2004,2005) for number in (31,32,33)}
        overlay=units.install(db,BID,decks,membership,expected=binding)
        bump_content_mods(db,[(BID,r['note_id']) for r in changed])
        assert protected=={t:stable_rows(db,t) for t in protected}
        assert other=={t:stable_rows(db,t,"WHERE book_id<>'"+BID+"'") for t in other}
        assert learning=={t:stable_rows(db,t) for t in progress}
        assert content==stable_rows(db,'note_fields',"WHERE book_id='"+BID+"' AND name NOT IN ('Title','SourceRecord')")
        after_registry=units.registry(db);before_registry=copy.deepcopy(after_registry);before_registry[BID]=binding
        assert {k:v for k,v in after_registry.items() if k!=BID}=={k:v for k,v in before_registry.items() if k!=BID}
        receipt={'book_id':BID,'backup':backup,'backup_sha256':backup_sha,'changed':changed,'identities_content_media_learning_preserved':True,'questions':832,'guide_cards':1,'type_groups':69}
        c.event(db,'politics-discrimination-classification',receipt)
    return receipt


def main():
    if DELIVERY.exists(): raise FileExistsError('retain prior delivery; choose a new explicit output')
    assert BASELINE.is_file()
    DELIVERY.mkdir()
    receipt=apply(c.Target(),DELIVERY)
    (DELIVERY/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    for fmt,path in [('apkg',DELIVERY/'questions.apkg'),('web',DELIVERY/'web')]:
        print('EXPORT',fmt,flush=True)
        receipt[fmt]=export_book(c.Target(),BID,path,format=fmt)
    package=DELIVERY/'Politics-Past-Exams-Full-20261103.apkg'
    finish_with_guide(DELIVERY/'questions.apkg',BASELINE,package)
    receipt.update(package=str(package),sha256=hashlib.sha256(package.read_bytes()).hexdigest(),bytes=package.stat().st_size)
    (DELIVERY/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));print('COMPLETE',flush=True)

if __name__=='__main__':main()
