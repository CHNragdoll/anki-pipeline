"""Seal completed lossless field checkpoints with the separately reviewed renderer.

Renderer changes do not invalidate immutable field roundtrip proofs. Recheck
every input field, output field and content-addressed string before packaging.
Only the owned derived database, models and new output package are written.
"""
from pathlib import Path
import argparse,copy,hashlib,json,re,sqlite3,time,zipfile,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.build_slim_apkg import ROOT,BASE,OWN,SOURCE_SHA,compiled_runtime,file_sha
from anki_pipeline.slim_apkg_content import Store,digest,restore
from anki_pipeline.inline_disclosures import restore_definition_disclosures

FIELDS=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']


def check_literal(path):
    raw=path.read_text()
    match=re.fullmatch(r'window.AnkiSlimAssets=window.AnkiSlimAssets\|\|\{\};window.AnkiSlimAssets\["([a-f0-9]{64})"\]=(.*);',raw,re.S)
    if not match:raise ValueError('derived literal media is not inert JSON')
    value=json.loads(match[2]);pin=match[1]
    if not isinstance(value,str) or digest(value)!=pin or path.name!='_as_'+pin[:24]+'.js':raise ValueError('derived literal byte SHA differs')
    return pin


def check_references(raw, names):
    refs=set(re.findall(r'_as_[a-f0-9]{24}\.js',raw))
    missing=refs-set(names)
    if missing:raise ValueError('lossless checkpoint is missing a referenced local asset: '+','.join(sorted(missing)))


def finalize(year):
    started=time.monotonic();folder=OWN/year
    proofs_path=folder/'lossless-field-proofs.jsonl'
    proofs=[json.loads(row) for row in proofs_path.read_text().splitlines()]
    by_key={(r['nid'],r['field']):r for r in proofs}
    if len(by_key)!=len(proofs):raise ValueError('duplicate inverse field proofs')
    source=BASE/f'{year}红宝书完整版-最新释义校勘与chunk-20261015.apkg'
    if file_sha(source)!=SOURCE_SHA[year]:raise ValueError('sealed baseline package changed')
    pins={str(p):file_sha(p) for p in (Path(__file__),ROOT/'scripts/build_slim_apkg.py',ROOT/'anki_pipeline/slim_apkg_content.py',ROOT/'anki_pipeline/inline_disclosures.py',ROOT/'anki_pipeline/templates/slim-apkg.js')}
    previous=json.loads((BASE/year/'report.json').read_text())
    media_folder=folder/'new-media';store=Store(media_folder);additions=[]
    for path in sorted(media_folder.glob('_as_*.js')):
        if not re.fullmatch(r'_as_[a-f0-9]{24}\.js',path.name):continue
        pin=check_literal(path);store.files[pin]=path;additions.append(path)
    if not additions:raise ValueError('checkpoint has no lossless literal media')
    names={p.name for p in additions}
    for pin in store.files:
        check_references(store.read({'sha256':pin}),names)
    with zipfile.ZipFile(source) as archive:
        source_media=json.loads(archive.read('media')); reverse={v:k for k,v in source_media.items()}
        with archive.open('collection.anki2') as stream:
            source_db_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        source_db=BASE/year/'collection.anki2'
        if file_sha(source_db)!=source_db_sha:raise ValueError('baseline private DB changed')
        before=sqlite3.connect('file:'+str(source_db)+'?mode=ro',uri=True)
        after=sqlite3.connect(folder/'collection.anki2')
        models=json.loads(before.execute('select models from col').fetchone()[0])
        old=before.execute('select id,guid,mid,flds from notes order by id')
        new=after.execute('select id,guid,mid,flds from notes order by id')
        count=0;original_bytes=0;slim_bytes=0;checked=0
        for a,b in zip(old,new,strict=True):
            if a[:3]!=b[:3]:raise ValueError('checkpoint note identity changed')
            fields_a,fields_b=a[3].split('\x1f'),b[3].split('\x1f')
            if [f['name'] for f in models[str(a[2])]['flds']] == FIELDS:
                for n,kind in ((2,'definition'),(7,'examples')):
                    proof=by_key[(a[0],kind)]
                    if proof['guid']!=a[1] or digest(fields_a[n])!=proof['original_sha256'] or digest(fields_b[n])!=proof['slim_sha256'] or proof['restored_sha256']!=proof['original_sha256']:
                        raise ValueError('checkpoint field roundtrip proof no longer valid')
                    check_references(fields_b[n],names)
                    if restore(fields_b[n],store)!=fields_a[n]:
                        raise ValueError('complete current-media inverse differs from original field')
                    checked+=1
                if restore_definition_disclosures(fields_b[2],fields_a[2]).html!=fields_b[2]:
                    raise ValueError('checkpoint disclosure bodies must already be inline; regenerate before sealing')
                if any(fields_a[n]!=fields_b[n] for n in (0,1,3,4,5,6,8,9)):
                    raise ValueError('checkpoint changed unrelated field')
            elif a[3]!=b[3]:raise ValueError('guide changed')
            original_bytes+=len(a[3].encode());slim_bytes+=len(b[3].encode());count+=1
        if checked!=len(proofs):raise ValueError('inverse proof coverage differs')
        for table in ('cards','revlog','graves'):
            if before.execute('select * from '+table+' order by 1').fetchall()!=after.execute('select * from '+table+' order by 1').fetchall():raise ValueError('learning state changed '+table)
        js=compiled_runtime(archive.read(reverse[previous['runtime']['js']]).decode())
        name='_as_runtime_'+digest(js)[:24]+'.js';js_path=media_folder/name;js_path.write_text(js)
        css=archive.read(reverse[previous['runtime']['css']]).decode()+'\n.as-lazy{padding:0!important;margin:0!important;border:0!important;list-style:none!important;min-height:0!important;background:transparent!important}.as-lazy>script{display:none!important}\n'
        css_name='_as_runtime_'+digest(css)[:24]+'.css';css_path=media_folder/css_name;css_path.write_text(css)
        now=int(time.time())
        for model in models.values():
            if [f['name'] for f in model['flds']]!=FIELDS:continue
            model['mod']=max(model['mod']+1,now);model['css']+='\n'+css
            for template in model['tmpls']:
                old_suffix='<script src="'+previous['runtime']['js']+'"></script><script>window.AnkiFinalApkgHydrate();</script>'
                if template['afmt'].count(old_suffix)!=1:raise ValueError('original runtime insertion marker differs')
                template['afmt']=template['afmt'].replace(old_suffix,'<script src="'+name+'"></script><script>window.AnkiSlimApkgHydrate();</script>')
                template['qfmt']+='<script src="'+name+'"></script><script>window.AnkiSlimApkgDispose();</script>'
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',(json.dumps(models,ensure_ascii=False),now*1000));after.commit()
        if after.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('derived DB is invalid')
        before.close();after.close()
        additions.extend((js_path,css_path));mapping=dict(source_media);next_id=max(map(int,mapping))+1
        for path in additions:
            if path.name in reverse:raise ValueError('derived media collides with source')
            mapping[str(next_id)]=path.name;next_id+=1
        target=OWN/f'{year}红宝书完整版-无损瘦身与加载优化-20261015.apkg';staged=folder/'package-sealed.tmp.apkg'
        if target.exists():raise ValueError('never overwrite a handed off package')
        print(json.dumps({'year':year,'stage':'checkpoint-reconciled','cards':count,'field_proofs':checked,'original_bytes':original_bytes,'slim_bytes':slim_bytes,'new_media_items':len(additions),'elapsed':round(time.monotonic()-started,2)}),flush=True)
        with zipfile.ZipFile(staged,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
            package.write(folder/'collection.anki2','collection.anki2')
            for info in archive.infolist():
                if info.filename in ('collection.anki2','media'):continue
                with archive.open(info) as incoming,package.open(copy.copy(info),'w') as outgoing:
                    for part in iter(lambda:incoming.read(4*1024*1024),b''):outgoing.write(part)
            for key,value in mapping.items():
                if key not in source_media:package.write(media_folder/value,key)
            package.writestr('media',json.dumps(mapping,ensure_ascii=False))
        for path,pin in pins.items():
            if file_sha(path)!=pin:raise ValueError('sealing source changed '+path)
        if file_sha(source)!=SOURCE_SHA[year]:raise ValueError('original package changed during sealing')
        staged.replace(target)
        report={'schema':'lossless-slim-apkg.v1','year':year,'source':str(source),'source_sha256':SOURCE_SHA[year],'output':str(target),'bytes':target.stat().st_size,'sha256':file_sha(target),'cards':count,'runtime':{'js':name,'css':css_name,'js_sha256':file_sha(js_path),'css_sha256':file_sha(css_path)},'changed_notes':checked//2,'original_field_bytes':original_bytes,'slim_field_bytes':slim_bytes,'all_fields_byte_roundtrip_verified':True,'full_current_media_inverse_compared_to_every_original_field':True,'referenced_asset_closure_verified':True,'roundtrip_proof_coverage':checked,'all_checkpoint_fields_and_media_sha_rechecked':True,'all_original_media_preserved':True,'original_media_items':len(source_media),'new_media_items':len(additions),'source_code_pins':pins,'lossless_proofs_sha256':file_sha(proofs_path),'elapsed_seconds':round(time.monotonic()-started,2)}
        (folder/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',choices=('2026','2027'),required=True)
    finalize(parser.parse_args().year)
