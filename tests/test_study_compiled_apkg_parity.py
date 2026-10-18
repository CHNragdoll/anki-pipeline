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
    def fixture(self):
        self.n+=1;p=self.root/str(self.n);p.mkdir();source=p/'source.anki2';candidate=p/'candidate.anki2'
        fields=[{'name':'Word','ord':0},{'name':'Back','ord':1}]
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
            db.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',(31,'GUID-31',17,19,8,' original tags ','cafe\u0301\x1f原释义','cafe\u0301',123,7,'original note data'))
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
        updated=copy.deepcopy(model);updated['mod']=21;updated['flds'].append({'name':'StudyCompiledDelivery','ord':2,'sticky':False,'rtl':False,'font':'Arial','size':12,'media':[]})
        # Exact approved shell, independent tiny SQLite/ZIP writer. No renderer is invoked.
        def shell(answer):
            return '<section data-study-native-owner data-answer="'+answer+'"><script type="application/json" data-study-native-delivery>{{StudyCompiledDelivery}}</script><p role="status" data-study-native-status>正在校验完整卡片…</p></section><script src="'+bootstrap+'"></script>'
        updated['tmpls'][0]['qfmt']=shell('false');updated['tmpls'][0]['afmt']=shell('true')
        with closing(sqlite3.connect(candidate)) as db, db:
            db.execute('update col set models=?',(dump({'17':updated,'18':guide}),))
            db.execute('update notes set mod=23,usn=-1,flds=flds||? where id=31',('\x1f'+dump(descriptor),))
        registration={'schema':'study-native-delivery-registration-result.v1','native_versions':{'book':{'models':{'17':21},'notes':{'31':23}}}}
        regpath=p/'registered.json';regpath.write_text(dump(registration))
        old_members={'0':b'original audio bytes','1':b'original JS bytes','README.txt':b'original extra bytes',
            'media':dump({'0':'音频.mp3','1':'original.js'}).encode()}
        new_members={**old_members,'2':carrier,'3':boot,'media':dump({'0':'音频.mp3','1':'original.js','2':carrier_name,'3':bootstrap}).encode()}
        request={'book_id':'book','source_collection_cache':str(source),'candidate_collection_cache':str(candidate),'collection_entry':'collection.anki2'}
        f={'dir':p,'source_db':source,'candidate_db':candidate,'old':old_members,'new':new_members,'request':request,'registration':registration,'registration_path':regpath}
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

if __name__ == "__main__":
    unittest.main()
