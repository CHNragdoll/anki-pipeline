from pathlib import Path
import base64,copy,gzip,hashlib,importlib.util,json,sqlite3,sys,tempfile,zipfile
ROOT=Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild');sys.path.insert(0,str(ROOT))
from anki_pipeline.study_compiled_native import bind_native_delivery,split_native_delivery_meta,native_bootstrap_source
from anki_pipeline.study_native_carrier import build_native_carrier
BASE=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime')
STAGE=BASE/'native-editor-compatible-v3-txoev54z/2027'
SQL=STAGE/'collection.anki2';APKG=STAGE/'2027-RedBook-Complete-Compiled-Editor-Compatible.apkg'
OUT=Path(tempfile.mkdtemp(prefix='native-year-filter-pilot-',dir=BASE))
sha=lambda raw:hashlib.sha256(raw).hexdigest()
def text(raw):return raw.decode('utf-8')
def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('<','\\u003c')
def unpack(raw):
    assert len(raw)<=128*1024*1024
    pref=b'window.StudyCompiledNative.register('
    join=b'(function(v){var d=v[1];window.StudyCompiledNative.register(v[0],v[2].map(function(p){return typeof p==="string"?p:d[p];}).join(""));})('
    if raw.startswith(pref):
        pin,value=json.loads('['+raw[len(pref):-2].decode()+']')
    else:
        assert raw.startswith(join) and raw.endswith(b');')
        pin,d,p=json.loads(raw[len(join):-2]);assert len(d)<=256 and len(p)<=20000
        value=''.join(item if isinstance(item,str) else d[item] for item in p)
    assert isinstance(value,str) and sha(value.encode())==pin
    return pin,value
spec=importlib.util.spec_from_file_location('native_test_bundle',ROOT/'tests/test_study_compiled_native.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
bundle=fixture.NativeCompiledTests();sample=bundle.native(bundle.bundle(fixture.SECOND_ORIGINAL))
_,sample_desc=split_native_delivery_meta(sample['note']['fields'][8]);pkt=sample_desc['packet'];sample_packet=json.loads(unpack(sample['media'][sample_desc['transport'][pkt['src']]['src']])[1])
cohort=fixture.SECOND_ORIGINAL;new_module=sample_packet['modules'][cohort]
new_alias=sample_desc['transport'][new_module['src']]['src'];new_carrier=sample['media'][new_alias];new_pin,new_loader=unpack(new_carrier)
assert new_pin==new_module['sha256']=='d17ea6bef41ff58a09b9b76f8ab9113bc1ad480eeb9d209d1dfc49ff4298a74e'
module=gzip.decompress((ROOT/'tests/fixtures/study-compiled-native/prepared-module-6a2b0f26.js.gz').read_bytes()).decode()
assert sha(module.encode())==fixture.SECOND_PREPARED
author=module[1919521:1921522]
assert sha(author.encode())=='f378c04e7e9d7aebe1f0ed3fa31ac986e569bf00d5b44dcf936528c72bfe1560'
assert new_loader.count(author)==1
proof=sample['loader_sources'][cohort]
assert '\n'.join(module[start:end] for start,end in proof['source_ranges'])==new_loader
assert proof['source_ranges'][2]==[1919521,1921522]
assert sha(native_bootstrap_source().encode())=='55de54c0e83ee7efce579b64a5402880acef949cada737e7afd3903192df50b8'
(OUT/new_alias).write_bytes(new_carrier);overrides={new_alias:str(OUT/new_alias)};records=[]
c=sqlite3.connect(SQL.as_uri()+'?mode=ro&immutable=1',uri=True);models=json.loads(c.execute('select models from col').fetchone()[0])
with zipfile.ZipFile(APKG) as z:
    media={name:key for key,name in json.loads(z.read('media')).items()}
    def original_asset(desc,asset):
        alias=desc['transport'][asset['src']]['src'];raw=z.read(media[alias]);assert sha(raw)==alias[len('_study_native_'):-3]
        pin,value=unpack(raw);assert pin==asset['sha256'];return value
    for word,guid in [('abide','P6_28j~Ts#'),('venture','pBLi=<Uf;=')]:
        nid,mid,mod,flds=c.execute('select id,mid,mod,flds from notes where guid=?',(guid,)).fetchone();fields=flds.split('\x1f');prefix,desc=split_native_delivery_meta(fields[8]);original=copy.deepcopy(desc)
        packet=json.loads(original_asset(desc,desc['packet']));old_module=packet['modules'][cohort];old_loader=original_asset(desc,old_module)
        assert new_loader.replace(author+'\n','',1)==old_loader
        assert old_module['module_sha256']==new_module['module_sha256']
        packet['modules'][cohort]=new_module
        packet_raw=compact(packet).encode();packet_pin=sha(packet_raw);packet_name='_study_native_packet_'+packet_pin+'.json'
        packet_carrier=build_native_carrier(packet_pin,packet_raw.decode());packet_alias='_study_native_'+sha(packet_carrier)+'.js';(OUT/packet_alias).write_bytes(packet_carrier);overrides[packet_alias]=str(OUT/packet_alias)
        del desc['transport'][desc['packet']['src']];del desc['transport'][old_module['src']]
        desc['packet']={'src':packet_name,'sha256':packet_pin};desc['transport'][packet_name]={'src':packet_alias,'sha256':packet_pin};desc['transport'][new_module['src']]={'src':new_alias,'sha256':new_pin}
        assert all(desc[key]==original[key] for key in ('id','entry','runtime','policy','styles','local_media','bootstrap_version'))
        model=models[str(mid)];stem=fields[:];stem[8]=prefix
        note={'id':desc['id'],'note_id':nid,'guid':guid,'model_id':mid,'model':copy.deepcopy(model),'field_names':[f['name'] for f in model['flds']],'fields':stem,'payload':{'id':nid,'mid':mid,'guid':guid,'mod':mod},'content_mod':mod+1}
        bootstrap='_study_native_bootstrap_'+sha(native_bootstrap_source().encode())+'.js'
        fixed=bind_native_delivery(note,desc,bootstrap_name=bootstrap,model_mod=model['mod']+1,note_mod=mod+1)
        restored=fixed['fields'][:];restored[8]=split_native_delivery_meta(restored[8])[0];assert restored==stem
        # Both pages use the exact production binder template/CSS. The added
        # nav identifies the QA harness and is outside the native owner.
        for side,key in [('front','qfmt'),('back','afmt')]:
            tpl=fixed['model']['tmpls'][0][key];assert tpl.count('{{Meta}}')==1
            rendered=tpl.replace('{{Meta}}',fixed['fields'][8])
            page=('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+word+' '+side+' · retained original year filter pilot</title><style>'+model['css']+'</style></head><body class="card"><nav style="position:relative;z-index:9999;padding:12px;font:14px system-ui;background:white;border-bottom:1px solid #ddd">原年份处理器恢复小样（不是完整新包，也不是 Anki 浏览预览验收） · <a href="/abide-front.html">abide 正面</a> · <a href="/abide-back.html">abide 背面</a> · <a href="/venture-back.html">venture 背面</a></nav><div id="qa">'+rendered+'</div></body></html>').encode()
            name=word+'-'+side+'.html';(OUT/name).write_bytes(page);overrides[name]=str(OUT/name)
        records.append({'word':word,'guid':guid,'note_id':nid,'old_loader':old_module,'new_loader':new_module,'loader_inverse_removing_exact_original_author_is_old_loader':True,'all_ten_source_field_values_exact_after_transport_inverse':True,'entry_profile_HTML_policy_styles_local_media_bootstrap_unchanged':True,'old_packet':original['packet'],'new_packet':desc['packet'],'meta_sha256':sha(fixed['fields'][8].encode())})
c.close()
(OUT/'overrides.json').write_text(json.dumps(overrides,ensure_ascii=False,indent=2)+'\n')
report={'schema':'study-native-original-year-filter-browser-pilot.v1','source_commit_before_fix':'9c9ef2d','source_package':{'path':str(APKG),'sha256':'3327fc72d1bf41bf5cc3a95a5f7f2f0541a8d828a875c14890f715ce827acce5'},'source_module_sha256':fixture.SECOND_PREPARED,'author_source_sha256':sha(author.encode()),'author_source_bytes':len(author.encode()),'source_ranges_proof':proof,'new_loader_sha256':new_pin,'new_loader_bytes':len(new_loader.encode()),'full_original_source_inverse':True,'notes':records,'scope':'Two private HTML pages through production binder using exact fixed projector loader and unchanged actual complete-v3 content, original APKG media and bootstrap; no APKG generation, PG, native collection writes or Anki client acceptance'}
(OUT/'PILOT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
old=(BASE/'native-v3-browser-harness-mqrw_o61/serve.py').read_text()
old=old.replace("lock=threading.Lock()", "overrides=json.loads((ROOT/'overrides.json').read_text())\nlock=threading.Lock()")
old=old.replace("if name in pages:\n            raw=pages[name];mime='text/html; charset=utf-8'", "if name in overrides:\n            raw=Path(overrides[name]).read_bytes();mime='text/html; charset=utf-8' if name.endswith('.html') else 'text/javascript; charset=utf-8'\n        elif name in pages:\n            raw=pages[name];mime='text/html; charset=utf-8'")
# Do not allow the old harness bootstrap to overwrite the fixed page files.
old=old.replace("pages[name]=page;(ROOT/name).write_bytes(page)", "pages[name]=page")
old=old.replace("'source':'page' if name in pages else 'actual_final_APKG_member'", "'source':'fixed_private_pilot' if name in overrides else 'page' if name in pages else 'actual_final_APKG_member'")
(OUT/'serve.py').write_text(old)
(OUT/'build-pilot.py').write_bytes(Path(__file__).read_bytes())
Path('/private/tmp/study-native-year-filter-pilot-current.json').write_text(json.dumps({'stage':str(OUT),'script':str(OUT/'serve.py')}))
print(json.dumps({'stage':str(OUT),'new_loader_sha256':new_pin,'author_bytes':len(author.encode()),'notes':len(records),'inverse':True},ensure_ascii=False))
