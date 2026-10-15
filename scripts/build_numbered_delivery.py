"""Derive display-ordinal fixes from sealed slim packages; keep media and learning data."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from anki_pipeline.example_numbering import numbering_edits, renumber_examples

INPUT=ROOT/'output/slim-v2-anki-20261015'
OWN=ROOT/'output/example-numbering-20261015'
PINS={'2026':'1e73805d78df6f400891336ac60fc499d48e8eef7d700c6cd864f693400248a4',
      '2027':'51d23d6bb07b9a0e0e6f5f1a4ee9e8faa0e953eb821068f7bec8216bef641b91'}
RUNTIME=ROOT/'anki_pipeline/templates/example-numbering.js'
FIELDS=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def build(year):
    started=time.monotonic();source_report=json.loads((INPUT/year/'build-report.json').read_text());source=Path(source_report['output'])
    assert sha(source)==source_report['sha256']==PINS[year]
    folder=OWN/year;folder.mkdir(parents=True,exist_ok=False)
    code={str(p):sha(p) for p in (Path(__file__),RUNTIME,ROOT/'anki_pipeline/example_numbering.py',
                                ROOT/'anki_pipeline/native_example_usage.py',ROOT/'anki_pipeline/sense_display.py')}
    runtime_raw=RUNTIME.read_bytes();runtime_name='_as_numbering_'+hashlib.sha256(runtime_raw).hexdigest()[:24]+'.js'
    with zipfile.ZipFile(source) as archive:
        with archive.open('collection.anki2') as incoming,(folder/'collection.anki2').open('xb') as out:shutil.copyfileobj(incoming,out)
        before=sqlite3.connect(':memory:');before.deserialize((folder/'collection.anki2').read_bytes())
        after=sqlite3.connect(folder/'collection.anki2');models=json.loads(before.execute('select models from col').fetchone()[0]);now=int(time.time());proofs=[]
        for nid,guid,mid,flds,mod in before.execute('select id,guid,mid,flds,mod from notes order by id'):
            if [f['name'] for f in models[str(mid)]['flds']]!=FIELDS:continue
            fields=flds.split('\x1f');original=fields[7];edits=numbering_edits(original);fields[7]=renumber_examples(original)
            inverse=fields[7]
            # The only authorized field edits replace live numeric badge text.
            shift=0;spans=[]
            for start,end,revised in edits:
                spans.append({'start':start+shift,'end':start+shift+len(revised),'original':original[start:end]});shift+=len(revised)-(end-start)
            for span in reversed(spans):inverse=inverse[:span['start']]+span['original']+inverse[span['end']:]
            assert inverse==original and fields[:7]+fields[8:]==flds.split('\x1f')[:7]+flds.split('\x1f')[8:]
            if edits:
                after.execute('update notes set flds=?,mod=?,usn=-1 where id=?',('\x1f'.join(fields),max(now,mod+1),nid))
                proofs.append({'nid':nid,'guid':guid,'field':'Examples','old_sha256':hashlib.sha256(original.encode()).hexdigest(),'new_sha256':hashlib.sha256(fields[7].encode()).hexdigest(),'inverse':spans})
        tag='<script src="'+runtime_name+'"></script>'
        for model in models.values():
            if [f['name'] for f in model['flds']]!=FIELDS:continue
            model['mod']=max(now,model['mod']+1)
            for template in model['tmpls']:
                for face in ('qfmt','afmt'):
                    assert runtime_name not in template[face];template[face]+='\n'+tag
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',(json.dumps(models,ensure_ascii=False),now*1000));after.commit()
        assert after.execute('pragma integrity_check').fetchone()[0]=='ok'
        for table in ('cards','revlog','graves'):
            assert before.execute('select * from '+table+' order by 1').fetchall()==after.execute('select * from '+table+' order by 1').fetchall()
        assert before.execute('select id,guid,mid,tags from notes order by id').fetchall()==after.execute('select id,guid,mid,tags from notes order by id').fetchall()
        count=before.execute('select count(*) from notes').fetchone()[0];before.close();after.close()
        save(folder/'ordinal-field-proofs.json',proofs)
        media=json.loads(archive.read('media'));assert runtime_name not in media.values();new_key=str(max(map(int,media))+1);media[new_key]=runtime_name
        output=OWN/f'{year}红宝书完整版-无损瘦身与例句序号修复-20261015.apkg'
        staged=folder/'staged.apkg'
        with zipfile.ZipFile(staged,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as target:
            target.write(folder/'collection.anki2','collection.anki2')
            for info in archive.infolist():
                if info.filename in ('collection.anki2','media'):continue
                clone=copy.copy(info)
                with archive.open(info) as incoming,target.open(clone,'w') as outgoing:shutil.copyfileobj(incoming,outgoing,1024*1024)
            target.writestr(new_key,runtime_raw);target.writestr('media',json.dumps(media,ensure_ascii=False))
        assert all(sha(p)==pin for p,pin in code.items()) and sha(source)==PINS[year]
        assert not output.exists();staged.rename(output)
        report={'schema':'display-example-numbering-apkg.v1','year':year,'output':str(output),'bytes':output.stat().st_size,'sha256':sha(output),
                'source':source_report['source'],'source_sha256':source_report['source_sha256'],'storage_source':str(source),'storage_source_sha256':PINS[year],
                'runtime':source_report['runtime'],'numbering_runtime':{'file':runtime_name,'sha256':hashlib.sha256(runtime_raw).hexdigest()},
                'cards':count,'changed_notes':len(proofs),'changed_badges':sum(len(p['inverse']) for p in proofs),'field_proofs_sha256':sha(folder/'ordinal-field-proofs.json'),
                'only_live_badge_text_and_companion_script_changed':True,'field_byte_inverse_verified':True,'all_original_media_preserved':True,'learning_tables_and_identities_preserved':True,'source_code_pins':code,'elapsed_seconds':round(time.monotonic()-started,2)}
        save(folder/'build-report.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)

def web():
    folder=OWN/'web';folder.mkdir(parents=True,exist_ok=False);assets=folder/'assets';assets.mkdir();before=folder/'before';before.mkdir()
    accepted=ROOT/'output/eleven-resolution-20261014/preview-own/final-v2'
    runtime=(accepted/'assets/library-preview.js').read_text()
    needle='        constrainCardDocument(cardDocument);';assert runtime.count(needle)==1
    revised=runtime.replace(needle,needle+'\n        window.AnkiExampleNumbering.install(cardDocument);')
    (assets/'library-preview.js').write_text(revised);shutil.copyfile(RUNTIME,assets/'example-numbering.js')
    changes=[]
    for book in ('redbook','redbook2027'):
        shell=accepted/book/'preview-library.html';raw=shell.read_text();old='/eleven-resolution-20261014/preview-own/final-v2/assets/library-preview.js'
        assert raw.count('src="'+old+'"')==1
        new='/example-numbering-20261015/web/assets/'
        updated=raw.replace('<script src="'+old+'" defer></script>', '<script src="'+new+'example-numbering.js" defer></script>\n  <script src="'+new+'library-preview.js" defer></script>')
        shutil.copyfile(shell,before/(book+'-preview-library.html'));shell.write_text(updated)
        changes.append({'path':str(shell),'before_sha256':sha(before/(book+'-preview-library.html')),'after_sha256':sha(shell),'backup':str(before/(book+'-preview-library.html'))})
    save(folder/'web-receipt.json',{'only_unsigned_shell_script_references_changed':True,'source_card_catalog_evidence_and_original_runtime_unchanged':True,'shells':changes,'runtime_source_sha256':hashlib.sha256(runtime.encode()).hexdigest(),'runtime_sha256':sha(assets/'library-preview.js'),'numbering_sha256':sha(RUNTIME)})
    print(json.dumps(changes,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--year',choices=['2026','2027']);parser.add_argument('--web',action='store_true');args=parser.parse_args()
    if args.web:web()
    elif args.year:build(args.year)
    else:parser.error('choose --year or --web')
