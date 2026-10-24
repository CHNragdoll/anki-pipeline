"""Read-only identities from exact legacy catalogs and the current PG catalog."""
from pathlib import Path
import gzip
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import zipfile
import genanki
from anki_pipeline import study_catalog as c

ROOT = Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild')
OUTPUT = ROOT / 'output/study-catalog-20261015'

def pin(path):
    with path.open('rb') as stream:
        return {'path': str(path), 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest(),
                'bytes': path.stat().st_size}

specs = [('liu','liuxiaoyan2027','preview-library.html'),
         ('redbook','redbook','redbook-20261004/preview-library.html'),
         ('redbook2027','redbook2027','redbook-2027-20261006/preview-library.html')]
catalogs = {}
for legacy, book, relative in specs:
    entry = ROOT / 'output' / relative
    source = entry.parent / re.search(r'data-catalog-url="([^"]+)"', entry.read_text())[1]
    data = json.loads(source.read_text())
    cards = {row['id']: row for row in data['cards']}
    assert len(cards) == len(data['cards'])
    catalogs[book] = (legacy, source, cards, data)

seed = 'redbook-2026-guide-v1'
guide26 = {'id': hashlib.sha256(seed.encode()).hexdigest(), 'guid': genanki.guid_for(seed),
           'note_id':1791230400000, 'native_id':1791230400001, 'template_ordinal':0,
           'evidence': {'kind':'exact-native-and-web-identity-derivation', 'seed':seed,
                        'builder':pin(ROOT/'output/redbook-final-20261006/build.py')}}
guide_id27 = 'dfd55da8104b8c9ae41ab4b3e7803ca72e98c34c4cb47a46f3070341eadaae95'
card27 = catalogs['redbook2027'][2][guide_id27]
page = ROOT/'output'/card27['previewUrl'].lstrip('/')
html = page.read_text()
package = ROOT/'output/redbook-2027-20261006/2027考研英语红宝书（必考词+基础词+超纲词）真题例句版（Unit31分组修正版）.apkg'
with tempfile.TemporaryDirectory(prefix='study-guide-binding-') as temporary:
    collection = Path(temporary)/'collection.sqlite3'
    with zipfile.ZipFile(package) as archive, archive.open('collection.anki2') as source, collection.open('xb') as dest:
        shutil.copyfileobj(source,dest,1024*1024)
    db = sqlite3.connect(collection.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        nid,guid,mid,flds = db.execute('select id,guid,mid,flds from notes where id=1962027000000').fetchone()
        fields=flds.split('\x1f')
        assert all(field in html for field in fields)
        native = db.execute('select id,did,ord from cards where nid=?',(nid,)).fetchall()
        assert len(native)==1
        guide27 = {'id':guide_id27,'guid':guid,'note_id':nid,'native_id':native[0][0],
                   'template_ordinal':native[0][2], 'evidence':{
                       'kind':'every-original-field-exact-in-legacy-page-and-native-GUID',
                       'package':pin(package),'collection_sha256':pin(collection)['sha256'],
                       'legacy_page':pin(page),'field_sha256':[hashlib.sha256(x.encode()).hexdigest() for x in fields],
                       'model_id':mid,'original_unit_id':native[0][1]}}
    finally:
        db.close()
guides={'redbook':guide26,'redbook2027':guide27}
report={'schema':'study-progress-current-bindings-readonly.v1','captured_at':c.now(),
        'scope':'Legacy web catalog identity to native catalog only; no learning DB access, PG writes or service switch.',
        'books':[], 'bindings':[], 'excluded_from_legacy_learning_catalog':[],
        'guide_proofs':guides, 'ready_to_switch':False}
with c.connect(readonly=True) as db,db.transaction():
    db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
    db.execute("SET LOCAL statement_timeout='10s'")
    report['catalog_revision']=db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    for book,(legacy,path,cards,data) in catalogs.items():
        seen=set()
        source_id=db.execute('select source_id from book_sources where book_id=%s',(book,)).fetchone()[0]
        rows=db.execute('select n.note_id,n.guid,n.source_card_id,n.kind,n.model_id,v.native_id,v.ordinal,u.id,u.name,w.surface '
            'from notes n join native_cards v on v.book_id=n.book_id and v.note_id=n.note_id '
            'join units u on u.book_id=v.book_id and u.id=v.unit_id left join words w on w.id=n.word_id '
            'where n.book_id=%s order by n.ordinal,v.ordinal',(book,)).fetchall()
        for nid,guid,source,kind,model,native,ordinal,unit,unitname,word in rows:
            key=source or guid
            evidence='exact-source-card-id'
            if kind=='guide':
                proof=guides[book]
                assert (nid,guid,native,ordinal)==(proof['note_id'],proof['guid'],proof['native_id'],proof['template_ordinal'])
                key=proof['id']; evidence='exact-guide-proof'
            target={'book_id':book,'source_id':source_id,'note_id':nid,'guid':guid,
                    'model_id':model,'native_id':native,'template_ordinal':ordinal,'unit_id':unit}
            if key not in cards:
                assert kind=='supplemental'
                report['excluded_from_legacy_learning_catalog'].append({**target,'id':key,'word':word,
                    'kind':kind,'reason':'Absent from the exact existing learning catalog; preserved in master, no implicit new learning row.'})
                continue
            assert key not in seen
            seen.add(key)
            card=cards[key]
            assert card['deckId'] in {str(x['id']) for x in data['decks']}
            assert any(key in x['cardIds'] for x in data['decks'] if str(x['id'])==card['deckId'])
            report['bindings'].append({'legacy':{'book':legacy,'card_id':key,'deck_id':card['deckId']},
                'target':target,'evidence':evidence})
        assert seen==set(cards)
        report['books'].append({'legacy_book':legacy,'book_id':book,'source_id':source_id,
            'catalog':pin(path),'cards':len(cards),'native_cards':len(rows)})
assert len(report['bindings'])==15170 and len(report['excluded_from_legacy_learning_catalog'])==4
raw=(c.canonical(report)+'\n').encode()
dest=OUTPUT/'learning-identities-readonly-20261017.json.gz'
with dest.open('xb') as output,gzip.GzipFile(fileobj=output,mode='wb',mtime=0) as stream:stream.write(raw)
print(json.dumps({'artifact':pin(dest),'decoded_sha256':hashlib.sha256(raw).hexdigest(),
    'bindings':len(report['bindings']),'books':report['books'],
    'excluded':report['excluded_from_legacy_learning_catalog'],'ready_to_switch':False},ensure_ascii=False,indent=2))
