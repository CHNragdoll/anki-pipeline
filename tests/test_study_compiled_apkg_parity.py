import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('parity',HERE.parent/'scripts/verify_study_compiled_apkg.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def dump(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def pinned(path):return m.file_pin(path)[0]

class ParityFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.n=0
    def fixture(self,delivery_transport=None):
        self.n+=1;p=self.root/str(self.n);p.mkdir();source=p/'source.anki2';candidate=p/'candidate.anki2'
        fields=[{'name':'Word','ord':0},{'name':'Back','ord':1}]
        source_fields=['cafe\u0301','原释义']
        meta=delivery_transport=='meta-footer-v2'
        if meta:
            fields.append({'name':'Meta','ord':2})
            source_fields.append(' {"label":"原Meta e\u0301 >"}\r\n ')
        model={'id':17,'mod':19,'name':'unchanged model','css':'original CSS','sortf':0,'flds':fields,
            'tmpls':[{'name':'Card1','ord':0,'qfmt':'{{Word}}','afmt':'{{Back}}'}]}
        guide={'id':18,'mod':7,'name':'guide','css':'guide CSS','sortf':0,'flds':[{'name':'Text','ord':0}],
            'tmpls':[{'name':'Guide','ord':0,'qfmt':'{{Text}}','afmt':'guide'}]}
        with closing(sqlite3.connect(source)) as db, db:
            db.executescript('''
                create table col(id integer primary key,models text,decks text,conf text,mod integer);
                create table notes(id integer primary key,guid text,mid integer,mod integer,usn integer,tags text,
                    flds text,sfld text,csum integer,flags integer,data text);
                create table cards(id integer primary key,nid integer,did integer,ord integer,mod integer,usn integer,
                    type integer,queue integer,due integer,ivl integer,factor integer,reps integer,lapses integer,
                    left integer,odue integer,odid integer,flags integer,data text);
                create table revlog(id integer primary key,cid integer,usn integer,ease integer,ivl integer,
                    lastIvl integer,factor integer,time integer,type integer);
                create table graves(usn integer,oid integer,type integer);
            ''')
            db.execute('insert into col values(1,?,?,?,?)',(dump({'17':model,'18':guide}),'original decks','original conf',11))
            db.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',(31,'GUID-31',17,19,8,' original tags ','\x1f'.join(source_fields),'cafe\u0301',123,7,'original note data'))
            db.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',(32,'GUID-guide',18,7,8,' guide ','guide content','guide content',456,0,'guide note data'))
            for cid,nid in [(41,31),(42,32)]:
                db.execute('insert into cards values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,nid,51,0,101,8,2,2,92,14,2400,17,3,0,0,0,5,'scheduling'))
            db.execute('insert into revlog values(1,41,8,3,14,7,2400,950,1)');db.execute('insert into graves values(8,75,1)')
        shutil.copyfile(source,candidate)
        logical='原文😀\n<q>';logical_pin=m.sha(logical.encode())
        carrier=('window.StudyCompiledNative.register('+dump(logical_pin)+','+dump(logical).replace('<','\\u003c')+');').encode()
        carrier_name='_study_native_'+m.sha(carrier)+'.js'
        boot=b'/* tiny fixture bootstrap only: not executable */';bootstrap='_study_native_bootstrap_'+m.sha(boot)+'.js'
        ref={'src':'logical.txt','sha256':logical_pin}
        descriptor={'id':'canonical-31','bootstrap_version':'a'*64,'entry':{'html':ref,'profile':ref,'source':{},
            'anchors':{'htmlSha256':logical_pin,'profileSha256':logical_pin},'decoded':True,'module':{'original_sha256':'5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e','sha256':'7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4'}},'runtime':ref,'packet':ref,'policy':ref,
            'transport':{'logical.txt':{'src':carrier_name,'sha256':logical_pin}},'styles':{},'local_media':{}}
        updated=copy.deepcopy(model);updated['mod']=21
        if not meta:updated['flds'].append({'name':'StudyCompiledDelivery','ord':2,'sticky':False,'rtl':False,'font':'Arial','size':12,'media':[]})
        # Exact approved shell, independent tiny SQLite/ZIP writer. No renderer is invoked.
        def shell(answer):
            transport=('<template data-study-native-source-field>{{Meta}}</template>' if meta else
                '<script type="application/json" data-study-native-delivery>{{StudyCompiledDelivery}}</script>')
            return '<section data-study-native-owner data-answer="'+answer+'">'+transport+'<p role="status" data-study-native-status>正在校验完整卡片…</p></section><script src="'+bootstrap+'"></script>'
        updated['tmpls'][0]['qfmt']=shell('false');updated['tmpls'][0]['afmt']=shell('true')
        with closing(sqlite3.connect(candidate)) as db, db:
            db.execute('update col set models=?',(dump({'17':updated,'18':guide}),))
            if meta:
                values=source_fields[:]
                values[2]+='<script type="application/json" data-study-native-delivery="v2">'+dump(descriptor).replace('<','\\u003c')+'</script>'
                db.execute('update notes set mod=23,usn=-1,flds=? where id=31',('\x1f'.join(values),))
            else:db.execute('update notes set mod=23,usn=-1,flds=flds||? where id=31',('\x1f'+dump(descriptor),))
        registration={'schema':'study-native-delivery-registration-result.v1','native_versions':{'book':{'models':{'17':21},'notes':{'31':23}}}}
        regpath=p/'registered.json';regpath.write_text(dump(registration))
        old_members={'0':b'original audio bytes','1':b'original JS bytes','README.txt':b'original extra bytes',
            'media':dump({'0':'音频.mp3','1':'original.js'}).encode()}
        new_members={**old_members,'2':carrier,'3':boot,'media':dump({'0':'音频.mp3','1':'original.js','2':carrier_name,'3':bootstrap}).encode()}
        request={'book_id':'book','source_collection_cache':str(source),'candidate_collection_cache':str(candidate),'collection_entry':'collection.anki2'}
        if delivery_transport is not None:request['delivery_transport']=delivery_transport
        f={'dir':p,'source_db':source,'candidate_db':candidate,'old':old_members,'new':new_members,'request':request,'registration':registration,'registration_path':regpath,'descriptor':descriptor,'source_fields':source_fields}
        self.repack(f)
        return f
    def repack(self,f):
        for key,db,members in [('source',f['source_db'],f['old']),('candidate',f['candidate_db'],f['new'])]:
            path=f['dir']/(key+'.apkg')
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('collection.anki2',db.read_bytes())
                for name,raw in members.items():archive.writestr(name,raw)
            f['request'][key]=pinned(path)
    def run_one(self,f):return m.verify_book(f['request'],f['registration'])
    def mutate(self,f,sql,args=()):
        with closing(sqlite3.connect(f['candidate_db'])) as db, db:db.execute(sql,args)
        self.repack(f)
class TinyParityTests(ParityFixture):
    def test_complete_sqlite_media_and_source_field_prefix_pass(self):
        f=self.fixture();result=self.run_one(f)
        self.assertEqual(result['sqlite']['compiled_notes_checked'],1)
        self.assertEqual(result['sqlite']['notes_checked'],2)
        self.assertEqual(result['sqlite']['tables_exact_except_documented_col_and_notes']['cards'],2)
        self.assertEqual(result['sqlite']['original_compiled_field_values_exact'],2)
        self.assertFalse(result['sqlite']['NFC_substitution_allowed'])
        self.assertEqual(result['media']['original_media_members_checked'],2)
        self.assertEqual(result['media']['new_media_count'],2)
        self.assertTrue(result['media']['new_register_carriers_logical_SHA_exact'])
    def test_guid_mid_id_and_schedule_are_not_exempt(self):
        for sql,code in [('update notes set guid="OTHER" where id=31','note-value'),
                         ('update notes set mid=18 where id=31','note-value'),
                         ('update notes set id=33 where id=31','note-id'),
                         ('update cards set due=999 where id=41','table-value')]:
            with self.subTest(sql=sql):
                f=self.fixture();self.mutate(f,sql)
                with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_revlog_and_deck_are_exact(self):
        for sql,code in [('update revlog set time=951','table-value'),('update col set decks="other"','col-value')]:
            f=self.fixture();self.mutate(f,sql)
            with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_nfc_is_not_accepted_as_lossless_original_field(self):
        f=self.fixture()
        with closing(sqlite3.connect(f['candidate_db'])) as db, db:
            value=db.execute('select flds from notes where id=31').fetchone()[0]
            db.execute('update notes set flds=? where id=31',(value.replace('cafe\u0301','caf\u00e9'),))
        self.repack(f)
        with self.assertRaisesRegex(m.ParityError,'original-field-prefix'):self.run_one(f)
    def test_actual_archive_original_media_change_fails_even_with_matching_outer_pin(self):
        f=self.fixture();f['new']['0']=b'changed audio';self.repack(f)
        with self.assertRaisesRegex(m.ParityError,'original-media-bytes'):self.run_one(f)
    def test_actual_extra_change_or_missing_member_fails(self):
        for missing in (False,True):
            f=self.fixture()
            if missing:del f['new']['README.txt']
            else:f['new']['README.txt']=b'changed extra'
            self.repack(f)
            with self.assertRaisesRegex(m.ParityError,'original-extra-member|original-archive-member-missing'):self.run_one(f)
    def test_only_registered_mod_and_exact_shell_are_allowed(self):
        for change,code in [('mod','note-mod-not-registered'),('css','unapproved-model-change'),('template','native-template-shell')]:
            f=self.fixture()
            with closing(sqlite3.connect(f['candidate_db'])) as db, db:
                if change=='mod':db.execute('update notes set mod=24 where id=31')
                else:
                    models=json.loads(db.execute('select models from col').fetchone()[0])
                    if change=='css':models['17']['css']='other CSS'
                    else:models['17']['tmpls'][0]['afmt']='{{FrontSide}}'
                    db.execute('update col set models=?',(dump(models),))
            self.repack(f)
            with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_existing_cache_must_match_actual_final_zip_member(self):
        f=self.fixture();f['request']['candidate_collection_cache']=str(f['source_db'])
        with self.assertRaisesRegex(m.ParityError,'collection-cache-does-not-match-final-archive'):self.run_one(f)
    def test_new_carrier_outer_and_logical_binding_are_both_checked(self):
        f=self.fixture();f['new']['2']=f['new']['2'].replace('原文'.encode(),'外改'.encode());self.repack(f)
        with self.assertRaisesRegex(m.ParityError,'content-addressed-new-media-sha'):self.run_one(f)
        f=self.fixture()
        with closing(sqlite3.connect(f['candidate_db'])) as db, db:
            fields=db.execute('select flds from notes where id=31').fetchone()[0].split('\x1f');d=json.loads(fields[-1]);d['transport']['logical.txt']['sha256']='0'*64;d['entry']['html']['sha256']='0'*64
            db.execute('update notes set flds=? where id=31',('\x1f'.join(fields[:-1]+[dump(d)]),))
        self.repack(f)
        with self.assertRaises(m.ParityError):self.run_one(f)
    def test_missing_final_pin_refuses_before_any_package_read(self):
        f=self.fixture();f['request']['candidate']=None
        with patch.object(m,'file_pin',side_effect=AssertionError('must not read packages')):
            with self.assertRaisesRegex(m.ParityError,'final-archive-pin-required'):self.run_one(f)
    def test_duplicate_zip_member_is_not_silently_shadowed(self):
        f=self.fixture()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(f['request']['candidate']['path'],'a') as archive:archive.writestr('0',b'shadow')
        f['request']['candidate']=pinned(Path(f['request']['candidate']['path']))
        with self.assertRaisesRegex(m.ParityError,'duplicate-zip-member'):self.run_one(f)
    def test_request_dispatch_uses_pinned_registration_without_pg_or_anki(self):
        f=self.fixture();request={'schema':'study-native-apkg-parity-request.v1','registration':pinned(f['registration_path']),'books':[f['request']]}
        d=m.verify(request);self.assertEqual(d['status'],'PASS');self.assertFalse(d['actual_Anki_import_or_user_collection_access']);self.assertFalse(d['PG_writes'])



class DerivedCacheTests(ParityFixture):
    def test_recomputed_checksum_from_original_field(self):
        import hashlib
        f=self.fixture();value=int(hashlib.sha1('cafe\u0301'.encode()).hexdigest()[:8],16)
        self.mutate(f,'update notes set csum=? where id=31',(value,))
        result=self.run_one(f)
        self.assertEqual(len(result['sqlite']['derived_field_cache_changes']),1)
    def test_arbitrary_checksum_change_is_rejected(self):
        f=self.fixture();self.mutate(f,'update notes set csum=987 where id=31')
        with self.assertRaisesRegex(m.ParityError,'derived-field-cache'):self.run_one(f)
    def test_arbitrary_sort_change_is_rejected(self):
        f=self.fixture();self.mutate(f,'update notes set sfld="changed" where id=31')
        with self.assertRaisesRegex(m.ParityError,'derived-field-cache'):self.run_one(f)


class MetaFooterParityTests(ParityFixture):
    FOOTER='<script type="application/json" data-study-native-delivery="v2">'
    def change_fields(self,f,change):
        with closing(sqlite3.connect(f['candidate_db'])) as db,db:
            fields=db.execute('select flds from notes where id=31').fetchone()[0].split('\x1f')
            change(fields)
            db.execute('update notes set flds=? where id=31',('\x1f'.join(fields),))
        self.repack(f)
    def footer(self,f,descriptor=None):
        return f['source_fields'][2]+self.FOOTER+dump(f['descriptor'] if descriptor is None else descriptor).replace('<','\\u003c')+'</script>'
    def test_explicit_v2_exact_fields_inert_shell_and_original_media_pass(self):
        f=self.fixture('meta-footer-v2');result=self.run_one(f)
        self.assertEqual(result['delivery_transport'],'meta-footer-v2')
        self.assertEqual(result['sqlite']['original_compiled_field_values_exact'],3)
        self.assertTrue(result['sqlite']['model_changes'][0]['field_schema_unchanged'])
        self.assertEqual(result['media']['original_media_members_checked'],2)
        self.assertEqual(result['media']['new_media_count'],2)
        self.assertTrue(result['media']['all_original_media_and_extras_SHA_exact'])
    def test_v2_ten_field_source_with_meta_at_eight_preserves_all_other_nine_fields(self):
        f=self.fixture('meta-footer-v2')
        names=['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']
        fields=['cafe\u0301','/kæˈfeɪ/ 原音标','<p>原释义 中文😀 e\u0301</p>','原简释义',
                '原等级 Unit 01','original forms café','<audio src="original.mp3"></audio> 原音频字串',
                '<p>Original sentence.\r\n原文例句😀</p>',f['source_fields'][2],'原笔记 "quoted"\n原文']
        candidate_fields=fields[:];candidate_fields[8]=self.footer(f)
        for path,values in [(f['source_db'],fields),(f['candidate_db'],candidate_fields)]:
            with closing(sqlite3.connect(path)) as db,db:
                models=json.loads(db.execute('select models from col').fetchone()[0])
                models['17']['flds']=[{'name':name,'ord':index} for index,name in enumerate(names)]
                if path==f['source_db']:models['17']['tmpls'][0]['afmt']='{{Definition}}'
                db.execute('update col set models=?',(dump(models),))
                db.execute('update notes set flds=? where id=31',('\x1f'.join(values),))
        self.repack(f);result=self.run_one(f)
        self.assertEqual(result['sqlite']['model_changes'][0]['source_field_count'],10)
        self.assertTrue(result['sqlite']['model_changes'][0]['field_schema_unchanged'])
        self.assertEqual(result['sqlite']['original_compiled_field_values_exact'],10)
        for index in [0,1,2,3,4,5,6,7,9]:
            changed=candidate_fields[:];changed[index]+='篡改'
            self.mutate(f,'update notes set flds=? where id=31',('\x1f'.join(changed),))
            with self.subTest(field=names[index]),self.assertRaisesRegex(m.ParityError,'original-field-value'):
                self.run_one(f)
    def test_default_and_explicit_legacy_keep_the_original_contract(self):
        for mode in [None,'legacy-field-v1']:
            f=self.fixture(mode);result=self.run_one(f)
            self.assertEqual(result['delivery_transport'],'legacy-field-v1')
            self.assertEqual(result['sqlite']['model_changes'][0]['appended_field'],'StudyCompiledDelivery')
        for actual,requested in [('meta-footer-v2','legacy-field-v1'),('legacy-field-v1','meta-footer-v2')]:
            f=self.fixture(actual);f['request']['delivery_transport']=requested
            with self.assertRaises(m.ParityError):self.run_one(f)
    def test_unknown_transport_refuses_before_reading_package_bytes(self):
        for mode in [None,'auto','meta-footer-v3',17]:
            f=self.fixture();f['request']['delivery_transport']=mode
            with patch.object(m,'file_pin',side_effect=AssertionError('must not read packages')):
                with self.assertRaisesRegex(m.ParityError,'delivery-transport'):self.run_one(f)
    def test_all_non_meta_fields_and_the_meta_prefix_must_be_exact_without_nfc(self):
        for index,value,code in [(0,'caf\u00e9','original-field-value'),(1,'改释义','original-field-value'),
                                 (2,' {"label":"原Meta \u00e9 >"}\r\n ','original-meta-prefix')]:
            f=self.fixture('meta-footer-v2')
            self.change_fields(f,lambda values:values.__setitem__(index,value if index!=2 else value+self.FOOTER+dump(f['descriptor'])+'</script>'))
            with self.subTest(index=index),self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_footer_requires_one_canonical_terminal_json_script(self):
        for mutation in [lambda value:value+' ',lambda value:value+value,
                         lambda value:value.replace('="v2"','="v3"'),
                         lambda value:value.replace('application/json','text/plain'),
                         lambda value:value.replace(self.FOOTER,self.FOOTER+' '),
                         lambda value:value.replace(self.FOOTER+'{',self.FOOTER+'{"id":"duplicate",',1),
                         lambda value:value.replace('"canonical-31"','"canonical-31<source>"'),
                         lambda value:value.replace('</script>','</script><script></script>')]:
            f=self.fixture('meta-footer-v2');original=self.footer(f);changed=mutation(original)
            self.assertNotEqual(changed,original)
            self.change_fields(f,lambda fields:fields.__setitem__(2,changed))
            with self.subTest(changed=changed),self.assertRaises(m.ParityError):self.run_one(f)
    def test_escaped_less_than_in_descriptor_json_is_lossless(self):
        f=self.fixture('meta-footer-v2');descriptor=copy.deepcopy(f['descriptor']);descriptor['id']='canonical-31中文</template><source>'
        self.change_fields(f,lambda values:values.__setitem__(2,self.footer(f,descriptor)))
        self.assertEqual(self.run_one(f)['sqlite']['compiled_notes_checked'],1)
    def test_source_meta_must_be_inert_even_when_the_candidate_prefix_matches(self):
        for prefix in ['unsafe <source>','unsafe &amp;']:
            f=self.fixture('meta-footer-v2');old=f['source_fields'][2]
            for path in [f['source_db'],f['candidate_db']]:
                with closing(sqlite3.connect(path)) as db,db:
                    fields=db.execute('select flds from notes where id=31').fetchone()[0]
                    db.execute('update notes set flds=? where id=31',(fields.replace(old,prefix),))
            self.repack(f)
            with self.assertRaisesRegex(m.ParityError,'source-meta-not-inert'):self.run_one(f)
    def test_v2_rejects_changed_field_definitions_metadata_and_noninert_shells(self):
        for change,code in [('field','model-field-schema'),('css','unapproved-model-change'),
                            ('metadata','template-metadata'),('shell','native-template-shell'),
                            ('mod','model-mod-not-registered')]:
            f=self.fixture('meta-footer-v2')
            with closing(sqlite3.connect(f['candidate_db'])) as db,db:
                models=json.loads(db.execute('select models from col').fetchone()[0]);model=models['17']
                if change=='field':model['flds'][2]['ord']=0
                elif change=='css':model['css']='changed'
                elif change=='metadata':model['tmpls'][0]['name']='Changed'
                elif change=='mod':model['mod']=22
                else:model['tmpls'][0]['qfmt']=model['tmpls'][0]['qfmt'].replace('<template data-study-native-source-field>','<div hidden>').replace('</template>','</div>')
                db.execute('update col set models=?',(dump(models),))
            self.repack(f)
            with self.subTest(change=change),self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_v2_requires_exactly_one_source_meta_field(self):
        for replacement in ['Other','duplicate']:
            f=self.fixture('meta-footer-v2')
            for path in [f['source_db'],f['candidate_db']]:
                with closing(sqlite3.connect(path)) as db,db:
                    models=json.loads(db.execute('select models from col').fetchone()[0])
                    if replacement=='duplicate':models['17']['flds'][0]['name']='Meta'
                    else:models['17']['flds'][2]['name']=replacement
                    db.execute('update col set models=?',(dump(models),))
            self.repack(f)
            with self.assertRaisesRegex(m.ParityError,'model-meta-field-required'):self.run_one(f)
    def test_v2_has_no_extra_field_or_legacy_descriptor_escape(self):
        f=self.fixture('meta-footer-v2')
        self.change_fields(f,lambda fields:fields.append(dump(f['descriptor'])))
        with self.assertRaisesRegex(m.ParityError,'note-field-count'):self.run_one(f)
    def test_v2_uses_the_same_strict_descriptor_validation(self):
        for change,code in [('extra','delivery-descriptor-shape'),('logical','delivery-logical-reference')]:
            f=self.fixture('meta-footer-v2');descriptor=copy.deepcopy(f['descriptor'])
            if change=='extra':descriptor['extra']=True
            else:descriptor['runtime']['sha256']='0'*64
            self.change_fields(f,lambda fields:fields.__setitem__(2,self.footer(f,descriptor)))
            with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_v2_preserves_identity_scheduling_and_registered_versions(self):
        for sql,code in [('update notes set guid="OTHER" where id=31','note-value'),
                         ('update notes set mod=24 where id=31','note-mod-not-registered'),
                         ('update notes set usn=0 where id=31','note-usn'),
                         ('update cards set due=999 where id=41','table-value')]:
            f=self.fixture('meta-footer-v2');self.mutate(f,sql)
            with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_v2_checks_actual_original_media_and_new_carrier_bytes(self):
        for member,code in [('0','original-media-bytes'),('2','content-addressed-new-media-sha')]:
            f=self.fixture('meta-footer-v2');f['new'][member]=b'changed';self.repack(f)
            with self.assertRaisesRegex(m.ParityError,code):self.run_one(f)
    def test_request_dispatch_records_the_explicit_transport(self):
        f=self.fixture('meta-footer-v2')
        request={'schema':'study-native-apkg-parity-request.v1','registration':pinned(f['registration_path']),'books':[f['request']]}
        result=m.verify(request)
        self.assertEqual(result['status'],'PASS')
        self.assertEqual(result['books'][0]['delivery_transport'],'meta-footer-v2')

if __name__ == "__main__":
    unittest.main()
