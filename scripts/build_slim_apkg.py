"""Losslessly reorganize the sealed full APKGs; never touch a user profile."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from anki_pipeline.slim_apkg_content import Store,compact,digest,native_index,restore,transform

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/final-anki-20261015'
OWN=ROOT/'output/slim-anki-20261015'
SOURCE_SHA={'2026':'227399bbd6cfa2c8f268dda51034caa48bce957a9846b3c5306849cc3080d36b',
 '2027':'4a41e3e57ac9ea7563d3bb1223fa92474e92100484b2e98766c4a324a5ae4c46'}


def file_sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def compiled_runtime(raw):
    start=raw.rfind('(function(){',0,raw.index('var config='))
    end=raw.index('})();',raw.index('var config=',start))+len('})();')
    decoder=raw[start:end]
    if decoder.count('document.querySelectorAll(')!=3:
        raise ValueError('original compact decoder selector count changed')
    scoped='window.AnkiSlimDecode=function(root){'+decoder[len('(function(){'):-len('})();')].replace('document.querySelectorAll(','root.querySelectorAll(')+'};window.AnkiSlimDecode(document);'
    revised=raw[:start]+scoped+raw[end:]
    if revised.count('    observer.observe(')!=3:
        raise ValueError('owned native helper observer contract changed')
    revised=revised.replace('    observer.observe(','    if (!window.__ankiSlimManualRefresh) observer.observe(')
    marker='if (disposed) return; var natives = physicalNativeIndex(doc);'
    if revised.count(marker)!=1:
        raise ValueError('same-sense physical index hook changed')
    revised=revised.replace(marker,marker+'''\n      if (window.AnkiSlimPhysicalNativeIndex) window.AnkiSlimPhysicalNativeIndex(doc).forEach(function(values,key){var current=natives.get(key)||new Set();values.forEach(function(v){current.add(v);});natives.set(key,current);});''')
    gate="doc.querySelectorAll('.sf-sense > .sf-panel').forEach(function (panel) {"
    if revised.count(gate)!=1:
        raise ValueError('same-sense panel readiness hook changed')
    revised=revised.replace(gate,gate+'\n        if (window.AnkiSlimPanelReady && !window.AnkiSlimPanelReady(panel)) return;')
    return revised+'\n'+(ROOT/'anki_pipeline/templates/slim-apkg.js').read_text()


def build(year, sample=False):
    start=time.monotonic()
    original=BASE/f'{year}红宝书完整版-最新释义校勘与chunk-20261015.apkg'
    if file_sha(original)!=SOURCE_SHA[year]:raise ValueError('sealed source package changed')
    folder=OWN/(year+'-sample' if sample else year)
    folder.mkdir(parents=True,exist_ok=False)
    store=Store(folder/'new-media')
    codepins={str(p):file_sha(p) for p in (Path(__file__),ROOT/'anki_pipeline/slim_apkg_content.py',ROOT/'anki_pipeline/inline_disclosures.py',ROOT/'anki_pipeline/templates/slim-apkg.js')}
    old_report=json.loads((BASE/year/'report.json').read_text())
    with zipfile.ZipFile(original) as archive:
        mapping=json.loads(archive.read('media'));reverse={name:key for key,name in mapping.items()}
        source_db=BASE/year/'collection.anki2'
        with archive.open('collection.anki2') as stream:
            archive_db_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if file_sha(source_db)!=archive_db_sha:raise ValueError('private source DB does not match sealed APKG')
        before=sqlite3.connect('file:'+str(source_db)+'?mode=ro',uri=True)
        after=sqlite3.connect(folder/'collection.anki2');before.backup(after)
        models=json.loads(before.execute('select models from col').fetchone()[0])
        js=compiled_runtime(archive.read(reverse[old_report['runtime']['js']]).decode())
        js_file=store.add(js)
        # Runtime is executable code, not a lazy string registration.
        runtime_name='_as_runtime_'+digest(js)[:24]+'.js'
        runtime_path=folder/'new-media'/runtime_name;runtime_path.write_text(js)
        store.files.pop(js_file['sha256']).unlink()
        css=archive.read(reverse[old_report['runtime']['css']]).decode()+'''\n.as-lazy{padding:0!important;margin:0!important;border:0!important;list-style:none!important;min-height:0!important;background:transparent!important}.as-lazy>script{display:none!important}\n'''
        css_name='_as_runtime_'+digest(css)[:24]+'.css';css_path=folder/'new-media'/css_name;css_path.write_text(css)
        now=int(time.time())
        for model in models.values():
            if [f['name'] for f in model['flds']]!=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']:
                continue
            model['mod']=max(model['mod']+1,now)
            model['css']+='\n'+css
            for template in model['tmpls']:
                old_suffix='<script src="'+old_report['runtime']['js']+'"></script><script>window.AnkiFinalApkgHydrate();</script>'
                if template['afmt'].count(old_suffix)!=1:raise ValueError('baseline answer runtime attachment changed')
                template['afmt']=template['afmt'].replace(old_suffix,'<script src="'+runtime_name+'"></script><script>window.AnkiSlimApkgHydrate();</script>')
                template['qfmt']+='<script src="'+runtime_name+'"></script><script>window.AnkiSlimApkgDispose();</script>'
        proofs=[];changed=0;raw_fields=0;slim_fields=0;count=before.execute('select count(*) from notes').fetchone()[0]
        sample_words={'the','more','training','train','oblige','as','teem','deep-rooted'}
        for nid,guid,mid,flds,mod,sfld in before.execute('select id,guid,mid,flds,mod,sfld from notes order by id'):
            if [f['name'] for f in models[str(mid)]['flds']]!=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']:
                continue
            if sample and sfld not in sample_words:
                continue
            values=flds.split('\x1f');prior=list(values)
            index=store.add(compact(native_index(values[7])))
            for pos,kind in ((2,'definition'),(7,'examples')):
                revised=transform(values[pos],store,kind,index_part=index if pos==2 else None)
                restored=restore(revised,store)
                if restored!=values[pos]:raise ValueError('lossless roundtrip mismatch '+str(nid)+' '+kind)
                proofs.append({'nid':nid,'guid':guid,'field':kind,'original_sha256':digest(values[pos]),'restored_sha256':digest(restored),'slim_sha256':digest(revised),'original_bytes':len(values[pos].encode()),'slim_bytes':len(revised.encode())})
                values[pos]=revised
            if any(values[i]!=prior[i] for i in (0,1,3,4,5,6,8,9)):
                raise ValueError('unrelated original field changed')
            new='\x1f'.join(values);raw_fields+=len(flds.encode());slim_fields+=len(new.encode())
            after.execute('update notes set flds=?,mod=?,usn=-1 where id=?',(new,max(now,mod+1),nid));changed+=1
            if changed%250==0 or sample:
                print(json.dumps({'year':year,'stage':'lossless-fields','done':changed,'notes':count,'elapsed':round(time.monotonic()-start,2),'original_bytes':raw_fields,'slim_bytes':slim_fields}),flush=True)
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',(json.dumps(models,ensure_ascii=False),now*1000));after.commit()
        if after.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('private DB integrity failed')
        for table in ('cards','revlog','graves'):
            if before.execute('select * from '+table+' order by 1').fetchall()!=after.execute('select * from '+table+' order by 1').fetchall():raise ValueError('original '+table+' changed')
        if before.execute('select id,guid,mid from notes order by id').fetchall()!=after.execute('select id,guid,mid from notes order by id').fetchall():raise ValueError('original note identity changed')
        before.close();after.execute('vacuum');after.close()
        (folder/'lossless-field-proofs.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in proofs))
        for path,pin in codepins.items():
            if file_sha(path)!=pin:raise ValueError('generation source changed '+path)
        if sample:
            print(json.dumps({'year':year,'sample_complete':True,'path':str(folder),'elapsed':round(time.monotonic()-start,2)}),flush=True)
            return
        media=dict(mapping);next_id=max(map(int,media))+1
        additions=list(store.files.values())+[runtime_path,css_path]
        for path in additions:
            if path.name in reverse:raise ValueError('new media collides with source')
            media[str(next_id)]=path.name;next_id+=1
        target=OWN/f'{year}红宝书完整版-无损瘦身与加载优化-20261015.apkg'
        staged=folder/'package.tmp.apkg'
        with zipfile.ZipFile(staged,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
            package.write(folder/'collection.anki2','collection.anki2')
            for info in archive.infolist():
                if info.filename in ('collection.anki2','media'):continue
                # Original media bytes/names are unchanged. Their already
                # compressed recordings are not transcoded or recompressed.
                copied=copy.copy(info)
                with archive.open(info) as incoming,package.open(copied,'w') as outgoing:
                    for chunk in iter(lambda:incoming.read(4*1024*1024),b''):outgoing.write(chunk)
            for key,name in media.items():
                if key not in mapping:package.write(folder/'new-media'/name,key)
            package.writestr('media',json.dumps(media,ensure_ascii=False))
        staged.replace(target)
        if file_sha(original)!=SOURCE_SHA[year]:raise ValueError('sealed source package changed during build')
        runtime={'js':runtime_name,'css':css_name,'js_sha256':file_sha(runtime_path),'css_sha256':file_sha(css_path)}
        report={'schema':'lossless-slim-apkg.v1','year':year,'source':str(original),'source_sha256':SOURCE_SHA[year],'output':str(target),'bytes':target.stat().st_size,'sha256':file_sha(target),'cards':count,'runtime':runtime,'changed_notes':changed,'original_field_bytes':raw_fields,'slim_field_bytes':slim_fields,'all_fields_byte_roundtrip_verified':True,'all_original_media_preserved':True,'original_media_items':len(mapping),'new_media_items':len(additions),'source_code_pins':codepins,'lossless_proofs_sha256':file_sha(folder/'lossless-field-proofs.jsonl'),'elapsed_seconds':round(time.monotonic()-start,2)}
        (folder/'build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',choices=('2026','2027'),required=True);parser.add_argument('--sample',action='store_true')
    args=parser.parse_args();build(args.year,args.sample)
