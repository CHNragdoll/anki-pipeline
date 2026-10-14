"""Second lossless storage layer over immutable, verified full v1 packages.

The shared bank is frozen across both books, so equal logical strings produce
equal physical media bytes even when both books coexist in an Anki collection.
No source package/database or user collection is written.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, sqlite3, time, zipfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anki_pipeline.slim_apkg_content import Store, compact, details, digest, restore_layer
from anki_pipeline.slim_shared_codec import SharedDictionary, PACKED_SCHEMA, dictionary_json, expand, factor, fit
from anki_pipeline.slim_viewer_storage import ViewerStore, collect_blocks, factor_frames, restore_frames

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'output/slim-anki-20261015'
BASE = ROOT / 'output/final-anki-20261015'
OWN = ROOT / 'output/slim-v2-anki-20261015'
FIELDS = ['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']
SOURCE_SHA = {'2026':'49a29ce210e42f69471a4f397107457b2c406daaf4792e6af461d86c32508ca2',
              '2027':'a6edf04693cdc1bc14f181864400c08f4c879a92880b296a0d754a4690f833cf'}
EXTRA_DETAILS = {'sf-pending','residual-owner-history','sf-ownership-pending-note',
                 'sf-semantic-resolution-history','sf-source-confirmation-history','sf-final-history'}
LITERAL = re.compile(r'window.AnkiSlimAssets=window.AnkiSlimAssets\|\|\{\};window.AnkiSlimAssets\["([a-f0-9]{64})"\]=(.*);',re.S)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def registration(pin, value):
    return 'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['+json.dumps(pin)+']='+compact(value)+';'


def literal(path):
    match = LITERAL.fullmatch(Path(path).read_text())
    if not match:
        raise ValueError('asset is not a pure literal registration: '+str(path))
    value = json.loads(match[2])
    if not isinstance(value,str) or digest(value)!=match[1] or Path(path).name!='_as_'+match[1][:24]+'.js':
        raise ValueError('source literal SHA differs: '+str(path))
    return match[1],value


def input_package(year):
    report=json.loads((INPUT/year/'build-report.json').read_text())
    path=Path(report['output'])
    if sha(path)!=SOURCE_SHA[year] or report['sha256']!=SOURCE_SHA[year]:
        raise ValueError('handed-off v1 package changed')
    if not report['full_current_media_inverse_compared_to_every_original_field'] or not report['referenced_asset_closure_verified']:
        raise ValueError('v1 semantic inverse evidence is incomplete')
    return path,report


def raw_files(year):
    files={}
    bank_file = None
    if (OWN/'dictionary-report.json').exists():
        bank_pin = json.loads((OWN/'dictionary-report.json').read_text())['sha256']
        bank_file = '_as_'+bank_pin[:24]+'.js'
    for directory in (INPUT/year/'new-media',OWN/year/'new-media'):
        if not directory.exists():continue
        for path in directory.glob('_as_*.js'):
            if not re.fullmatch(r'_as_[a-f0-9]{24}\.js',path.name):continue
            if directory==OWN/year/'new-media' and path.name==bank_file:continue
            pin=path.name[4:-3]
            prior=files.get(pin)
            if prior and sha(prior)!=sha(path):raise ValueError('logical source filename collision')
            files[pin]=path
    return files


def source_connection(year):
    return sqlite3.connect('file:'+str(INPUT/year/'collection.anki2')+'?mode=ro',uri=True)


def load_viewer(year):
    data=json.loads((OWN/year/'prepare-report.json').read_text())
    store=ViewerStore(OWN/year/'new-media')
    for entry in data['viewer_assets']:
        store.files[entry['pin']]=store.folder/entry['file']
        store.originals[entry['replacement']]=(entry['pin'],entry['tag'],entry['original'])
    return store


def prepare(year):
    started=time.monotonic();package,prior=input_package(year)
    folder=OWN/year;folder.mkdir(parents=True,exist_ok=False)
    store=Store(folder/'new-media');viewer=ViewerStore(folder/'new-media')
    before=source_connection(year)
    with zipfile.ZipFile(package) as archive:
        with archive.open('collection.anki2') as incoming:
            archived_db_sha=hashlib.file_digest(incoming,'sha256').hexdigest()
    if sha(INPUT/year/'collection.anki2')!=archived_db_sha:raise ValueError('v1 private DB differs from package')
    models=json.loads(before.execute('select models from col').fetchone()[0])
    def definitions():
        for mid,flds in before.execute('select mid,flds from notes order by id'):
            if [f['name'] for f in models[str(mid)]['flds']]==FIELDS:
                yield flds.split('\x1f')[2]
    blocks=collect_blocks(definitions())
    after=sqlite3.connect(folder/'collection.anki2');before.backup(after)
    now=int(time.time());count=0;original_bytes=0;derived_bytes=0;proofs=[]
    for nid,guid,mid,flds,mod in before.execute('select id,guid,mid,flds,mod from notes order by id'):
        old=flds.split('\x1f');new=list(old)
        if [f['name'] for f in models[str(mid)]['flds']]==FIELDS:
            for position,kind in ((2,'definition'),(7,'examples')):
                revised=details(old[position],store,classes=EXTRA_DETAILS,layer='v2')
                revised=factor_frames(revised,viewer,blocks)
                restored=restore_layer(restore_frames(revised,viewer),store,'v2')
                if restored!=old[position]:raise ValueError('v2 field inverse differs '+str(nid)+' '+kind)
                proofs.append({'nid':nid,'guid':guid,'field':kind,'v1_sha256':digest(old[position]),
                               'v2_sha256':digest(revised),'restored_sha256':digest(restored)})
                new[position]=revised
            if any(old[n]!=new[n] for n in (0,1,3,4,5,6,8,9)):
                raise ValueError('unrelated original field changed')
            joined='\x1f'.join(new)
            after.execute('update notes set flds=?,mod=?,usn=-1 where id=?',(joined,max(now,mod+1),nid))
            count+=1
            if count%500==0:
                print(json.dumps({'year':year,'stage':'exact-frame-and-detail-inverse','notes':count,'seconds':round(time.monotonic()-started,1)}),flush=True)
        original_bytes+=len(flds.encode());derived_bytes+=len('\x1f'.join(new).encode())
    after.commit()
    for table in ('cards','revlog','graves'):
        if before.execute('select * from '+table+' order by 1').fetchall()!=after.execute('select * from '+table+' order by 1').fetchall():raise ValueError('learning state changed')
    after.execute('vacuum')
    if after.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('derived database failed integrity check')
    before.close();after.close()
    viewer_assets=[{'replacement':replacement,'pin':pin,'tag':tag,'original':original,'file':viewer.files[pin].name,'file_sha256':sha(viewer.files[pin])}
                   for replacement,(pin,tag,original) in viewer.originals.items()]
    proof_file=folder/'v2-field-proofs.jsonl'
    proof_file.write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in proofs))
    report={'year':year,'storage_source':str(package),'storage_source_sha256':SOURCE_SHA[year],
            'storage_source_database_sha256':archived_db_sha,'inherited_v1_inverse_report_sha256':sha(INPUT/year/'build-report.json'),
            'proof_file_sha256':sha(proof_file),'viewer_assets':viewer_assets,'new_detail_assets':len(store.files),
            'original_field_bytes':original_bytes,'derived_field_bytes':derived_bytes,'changed_notes':count,
            'v2_field_inverse_proofs':len(proofs),'every_v2_field_restored_to_sealed_v1':True,'seconds':round(time.monotonic()-started,1)}
    write_json(folder/'prepare-report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='viewer_assets'},ensure_ascii=False),flush=True)


def fit_bank():
    started=time.monotonic();files={}
    for year in ('2026','2027'):
        for pin,path in raw_files(year).items():
            if pin in files and sha(files[pin])!=sha(path):raise ValueError('cross-book source collision')
            files[pin]=path
    def stream():
        for n,pin in enumerate(sorted(files)):
            _,raw=literal(files[pin]);yield raw
            if n and n%5000==0:print(json.dumps({'stage':'shared-bank-fit','sources':n,'seconds':round(time.monotonic()-started,1)}),flush=True)
    dictionary=fit(stream,max_dictionary_bytes=4*1024*1024,strategy='frequency')
    raw=dictionary_json(dictionary);target=OWN/'shared-dictionary.json'
    if target.exists():raise ValueError('shared dictionary already frozen')
    target.write_text(raw)
    write_json(OWN/'dictionary-report.json',{'bytes':len(raw.encode()),'sha256':digest(raw),'entries':len(dictionary),'source_assets':len(files),
                                          'codec_source_sha256':sha(ROOT/'anki_pipeline/slim_shared_codec.py'),'seconds':round(time.monotonic()-started,1)})
    print(json.dumps({'stage':'bank-frozen','entries':len(dictionary),'bytes':len(raw.encode()),'seconds':round(time.monotonic()-started,1)}),flush=True)


def encode(year):
    started=time.monotonic();report=json.loads((OWN/'dictionary-report.json').read_text())
    if sha(ROOT/'anki_pipeline/slim_shared_codec.py')!=report['codec_source_sha256']:raise ValueError('frozen codec changed')
    bank_raw=(OWN/'shared-dictionary.json').read_text()
    if digest(bank_raw)!=report['sha256']:raise ValueError('frozen shared bank changed')
    dictionary=SharedDictionary(json.loads(bank_raw)['strings'])
    bank={'src':'_as_'+report['sha256'][:24]+'.js','sha256':report['sha256'],'literal':True}
    folder=OWN/year/'new-media';(folder/bank['src']).write_text(registration(bank['sha256'],bank_raw))
    files=raw_files(year);proofs=[];input_bytes=0;encoded_bytes=0
    for n,prefix in enumerate(sorted(files)):
        pin,raw=literal(files[prefix]);pieces=factor(raw,dictionary)
        if expand(pieces,dictionary)!=raw:raise ValueError('shared string inverse differs')
        packed={'schema':PACKED_SCHEMA,'dict':bank,'pieces':pieces}
        body=registration(pin,packed)
        target=folder/('_ac_'+pin[:24]+'.js');target.write_text(body)
        input_bytes+=files[prefix].stat().st_size;encoded_bytes+=target.stat().st_size
        proofs.append({'source':str(files[prefix]),'logical_sha256':pin,'output':target.name,'output_sha256':sha(target)})
        if n and n%5000==0:print(json.dumps({'year':year,'stage':'factored-exact-media','assets':n,'seconds':round(time.monotonic()-started,1)}),flush=True)
    proof_file=OWN/year/'media-proofs.jsonl';proof_file.write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in proofs))
    write_json(OWN/year/'encode-report.json',{'bank':bank,'dictionary_sha256':report['sha256'],'source_assets':len(proofs),
               'source_bytes':input_bytes,'encoded_bytes':encoded_bytes,'all_original_strings_and_sha_restored':True,
               'proof_file_sha256':sha(proof_file),'seconds':round(time.monotonic()-started,1)})
    print(json.dumps({'year':year,'stage':'encoding-complete','assets':len(proofs),'source_bytes':input_bytes,'encoded_bytes':encoded_bytes,'seconds':round(time.monotonic()-started,1)}),flush=True)


class PackedStore:
    def __init__(self,folder,dictionary,bank):
        self.folder=folder;self.dictionary=dictionary;self.bank=bank
    def read(self,part):
        pin=part['sha256'];path=self.folder/('_ac_'+pin[:24]+'.js')
        match=LITERAL.fullmatch(path.read_text())
        if not match or match[1]!=pin:raise ValueError('packed registration differs')
        value=json.loads(match[2])
        if not isinstance(value,dict) or value.get('schema')!=PACKED_SCHEMA or value.get('dict')!=self.bank:raise ValueError('packed schema or shared bank differs')
        raw=expand(value['pieces'],self.dictionary)
        if digest(raw)!=pin:raise ValueError('packed full literal SHA differs')
        return raw


def seal(year):
    started=time.monotonic();source,prior=input_package(year);folder=OWN/year
    prepared=json.loads((folder/'prepare-report.json').read_text());encoded=json.loads((folder/'encode-report.json').read_text())
    if sha(folder/'v2-field-proofs.jsonl')!=prepared['proof_file_sha256'] or sha(folder/'media-proofs.jsonl')!=encoded['proof_file_sha256']:
        raise ValueError('inverse proof file changed')
    bank_raw=(OWN/'shared-dictionary.json').read_text()
    if digest(bank_raw)!=encoded['dictionary_sha256']:raise ValueError('shared bank changed before sealing')
    actual_bank_pin,actual_bank=literal(folder/'new-media'/encoded['bank']['src'])
    if actual_bank_pin!=encoded['dictionary_sha256'] or actual_bank!=bank_raw:raise ValueError('physical shared bank differs')
    dictionary=SharedDictionary(json.loads(bank_raw)['strings']);store=PackedStore(folder/'new-media',dictionary,encoded['bank']);viewer=load_viewer(year)
    pins={str(p):sha(p) for p in [Path(__file__),ROOT/'anki_pipeline/slim_shared_codec.py',ROOT/'anki_pipeline/slim_viewer_storage.py',
                                 ROOT/'anki_pipeline/slim_apkg_content.py',ROOT/'anki_pipeline/templates/slim-apkg-v2.js',ROOT/'anki_pipeline/templates/slim-shared-codec.js']}
    media_proofs=[json.loads(l) for l in (folder/'media-proofs.jsonl').read_text().splitlines()]
    logical_names={('_as_'+p['logical_sha256'][:24]+'.js') for p in media_proofs}
    for n,proof in enumerate(media_proofs):
        raw=store.read({'sha256':proof['logical_sha256']})
        original_pin,original=literal(proof['source'])
        if original_pin!=proof['logical_sha256'] or raw!=original or sha(folder/'new-media'/proof['output'])!=proof['output_sha256']:
            raise ValueError('current packed media inverse differs from original literal')
        missing=set(re.findall(r'_as_[a-f0-9]{24}\.js',raw))-logical_names
        if missing:raise ValueError('missing logical media references: '+','.join(missing))
        if n and n%5000==0:print(json.dumps({'year':year,'stage':'current-media-inverse','assets':n,'seconds':round(time.monotonic()-started,1)}),flush=True)
    before=source_connection(year);after=sqlite3.connect(folder/'collection.anki2')
    if sha(INPUT/year/'collection.anki2')!=prepared['storage_source_database_sha256']:raise ValueError('sealed v1 source DB changed')
    models=json.loads(before.execute('select models from col').fetchone()[0]);count=0
    for original,derived in zip(before.execute('select id,guid,mid,flds from notes order by id'),after.execute('select id,guid,mid,flds from notes order by id'),strict=True):
        if original[:3]!=derived[:3]:raise ValueError('source note identity changed')
        a,b=original[3].split('\x1f'),derived[3].split('\x1f')
        if [f['name'] for f in models[str(original[2])]['flds']]==FIELDS:
            for position in (2,7):
                if restore_layer(restore_frames(b[position],viewer),store,'v2')!=a[position]:raise ValueError('current field inverse differs')
                if set(re.findall(r'_as_[a-f0-9]{24}\.js',b[position]))-logical_names:raise ValueError('missing field media reference')
            if any(a[i]!=b[i] for i in (0,1,3,4,5,6,8,9)):raise ValueError('unrelated source field changed')
        elif original[3]!=derived[3]:raise ValueError('guide content changed')
        count+=1
    for table in ('cards','revlog','graves'):
        if before.execute('select * from '+table+' order by 1').fetchall()!=after.execute('select * from '+table+' order by 1').fetchall():raise ValueError('learning state changed')
    with zipfile.ZipFile(source) as archive:
        mapping=json.loads(archive.read('media'));reverse={v:k for k,v in mapping.items()}
        old_js=archive.read(reverse[prior['runtime']['js']]).decode()
        marker='/* Lossless local-media segments. The producer pins the exact UTF-8 HTML/JSON;'
        if old_js.count(marker)!=1:raise ValueError('old compiled runtime boundary differs')
        js=old_js[:old_js.index(marker)]+(ROOT/'anki_pipeline/templates/slim-shared-codec.js').read_text()+'\n'+(ROOT/'anki_pipeline/templates/slim-apkg-v2.js').read_text()
        js_name='_as_runtime_'+digest(js)[:24]+'.js';(folder/'new-media'/js_name).write_text(js)
        now=int(time.time())
        for model in models.values():
            if [f['name'] for f in model['flds']]!=FIELDS:continue
            model['mod']=max(model['mod']+1,now)
            for template in model['tmpls']:
                for face in ('qfmt','afmt'):
                    old='src="'+prior['runtime']['js']+'"'
                    if template[face].count(old)!=1:raise ValueError('original template attachment differs')
                    template[face]=template[face].replace(old,'src="'+js_name+'"')
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',(json.dumps(models,ensure_ascii=False),now*1000));after.commit()
        if after.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('derived database integrity differs')
        before.close();after.close()
        actual=dict(mapping)
        for key,name in mapping.items():
            if re.fullmatch(r'_as_[a-f0-9]{24}\.js',name):actual[key]=name.replace('_as_','_ac_',1)
        additions=[folder/'new-media'/encoded['bank']['src'],folder/'new-media'/js_name]+list(viewer.files.values())
        old_physical=set(actual.values())
        additions.extend(folder/'new-media'/p['output'] for p in media_proofs if p['output'] not in old_physical)
        next_id=max(map(int,actual))+1
        for path in additions:
            if path.name in actual.values():raise ValueError('new media filename collision')
            actual[str(next_id)]=path.name;next_id+=1
        target=OWN/f'{year}红宝书完整版-深度无损瘦身-20261015.apkg';staged=folder/'package-sealed.tmp.apkg'
        if target.exists():raise ValueError('never overwrite a handed-off package')
        with zipfile.ZipFile(staged,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
            package.write(folder/'collection.anki2','collection.anki2')
            for info in archive.infolist():
                if info.filename in ('collection.anki2','media'):continue
                if mapping[info.filename]!=actual[info.filename]:package.write(folder/'new-media'/actual[info.filename],info.filename)
                else:
                    with archive.open(info) as incoming,package.open(copy.copy(info),'w') as outgoing:
                        for block in iter(lambda:incoming.read(4*1024*1024),b''):outgoing.write(block)
            for key,name in actual.items():
                if key not in mapping:package.write(folder/'new-media'/name,key)
            package.writestr('media',json.dumps(actual,ensure_ascii=False))
        if any(sha(p)!=pin for p,pin in pins.items()) or sha(source)!=SOURCE_SHA[year]:raise ValueError('sealing source changed')
        staged.replace(target)
        semantic=json.loads((INPUT/year/'build-report.json').read_text())
        report={'schema':'lossless-shared-apkg.v2','year':year,'source':semantic['source'],'source_sha256':semantic['source_sha256'],
                'storage_source':str(source),'storage_source_sha256':SOURCE_SHA[year],'output':str(target),'bytes':target.stat().st_size,'sha256':sha(target),'cards':count,
                'runtime':{'js':js_name,'css':prior['runtime']['css'],'js_sha256':sha(folder/'new-media'/js_name),'css_sha256':prior['runtime']['css_sha256']},
                'all_fields_byte_roundtrip_verified':True,'full_current_media_inverse_compared_to_every_v1_field':True,'inherited_original_semantic_inverse_sha256':sha(INPUT/year/'build-report.json'),
                'referenced_asset_closure_verified':True,'roundtrip_proof_coverage':prepared['v2_field_inverse_proofs'],'all_original_audio_and_nonliteral_media_preserved':True,
                'source_literal_logical_bytes_preserved':True,'shared_dictionary_bytes':len(bank_raw.encode()),'shared_dictionary_sha256':encoded['dictionary_sha256'],
                'source_code_pins':pins,'native_media_items':len(actual),'source_literal_media_items':len(media_proofs),'viewer_media_items':len(viewer.files),
                'original_field_bytes':prepared['original_field_bytes'],'slim_field_bytes':prepared['derived_field_bytes'],'elapsed_seconds':round(time.monotonic()-started,1)}
        write_json(folder/'build-report.json',report)
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=('prepare','fit','encode','seal'),required=True);parser.add_argument('--year',choices=('2026','2027'))
    args=parser.parse_args()
    if args.stage=='fit':fit_bank()
    elif not args.year:parser.error('--year is required for this stage')
    else:{'prepare':prepare,'encode':encode,'seal':seal}[args.stage](args.year)
