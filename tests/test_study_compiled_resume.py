"""Own-temp protocol and actual shared orchestration tests; no Node/DB/browser."""
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urljoin

HERE=Path(__file__).resolve().parent
REPO=HERE.parent
sys.path.insert(0,str(REPO))
import anki_pipeline
from anki_pipeline import study_compiled_build as shared
from anki_pipeline import study_catalog_web_materialize as materialize
from tests import test_study_compiled_web_delivery as compiled_fixture
ORIGINAL=compiled_fixture.ORIGINAL
from tests import test_study_catalog_web_delivery as delivery_fixture

from anki_pipeline import study_compiled_schedule as schedule
from anki_pipeline import study_catalog_web_delivery as delivery
from anki_pipeline import study_compiled_resume as resume
sha=shared._sha
packed=shared._json

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def fixture(self):
        root=self.root/'book';root.mkdir()
        catalog,config,results,inputs=compiled_fixture.CompiledWebDeliveryTests().fixture(root)
        result=results['card-0'];prepared=inputs['card-0']['prepared'];rule=inputs['card-0']['rule']
        # Module bytes are a protocol fixture, not claimed native initialization.
        module_raw=b'/* current prepared module fixture */'
        module=prepared['modules'][ORIGINAL];module['sha256']=sha(module_raw)
        (root/module['src']).write_bytes(module_raw)
        raw_side,raw_index=sha(b'original side registry'),sha(b'original index registry')
        prepared['sides'][1]['registry']={raw_side:{},raw_index:{}}
        prepared['sides'][1]['proof']['registry_pins']=[raw_side,raw_index]
        artifact_raw=packed(prepared);artifact={'path':'evidence/current.json','sha256':sha(artifact_raw)}
        (root/artifact['path']).write_bytes(artifact_raw)
        wrapper={'path':catalog['cards'][0]['url'],'sha256':sha((root/catalog['cards'][0]['url']).read_bytes())}
        policy={'external':{},'inline':[]};url='https://study.test/book/index.html';identity='subject:card-0'
        result['identity']=identity
        bindings=result['entry']['anchors']['bindings']
        bindings.update(sourceArtifactSha256=artifact['sha256'],nativeModuleSha256=module['sha256'],
            rawSideSha256=raw_side,rawIndexSha256=raw_index,materializerSha256=sha(Path(materialize.__file__).read_bytes()),
            adapterSha256=shared.inputs._HELPERS_SHA256,producerInputSha256=sha(b'producer bindings'))
        for name,(_,_,pin) in shared.inputs._DELEGATES.items():bindings[name]=pin
        result['entry']['module']['sha256']=module['sha256']
        result['entry']['source']['registry_pins']=[raw_side,raw_index]
        assets=root/'build-assets'
        def put(raw,suffix):
            name='_qa_compiled_'+sha(raw)+suffix;(assets/name).write_bytes(raw);return {'src':name,'sha256':sha(raw)}
        oldprofile=result['entry']['profile'];oldurl=urljoin(url,oldprofile['src']);result['resources'].pop(oldurl)
        profile={'schema':'study-compiled-card-interactions.v1','version':1,'bindings':bindings,'nodeBindings':[]}
        raw=packed(profile);result['entry']['profile']=put(raw,'.json');result['entry']['anchors']['profileSha256']=sha(raw)
        for asset in (result['entry']['html'],result['entry']['profile'],result['runtime']):
            path=assets/asset['src'];result['resources'][urljoin(url,asset['src'])]={'path':str(path),'sha256':asset['sha256'],'bytes':path.stat().st_size}
        result['resources'][urljoin(url,module['src'])]={'path':str(root/module['src']),'sha256':module['sha256'],'bytes':len(module_raw)}
        # Result descriptors use cached addressed storage as the real producer does.
        cached=assets/('_qa_compiled_'+module['sha256']+'.js');cached.write_bytes(module_raw)
        result['resources'][urljoin(url,module['src'])]['path']=str(cached)
        key={'identity':identity,'wrapper':wrapper,'artifact':artifact,'policy':policy,'source_url':url,'dependencies':shared.CompiledBuild._dependencies()}
        result['build_key']=sha(packed(key))
        record={'schema':'study-complete-card-build.v1','identity':identity,'build_key':result['build_key'],'dependencies':key['dependencies'],
            'entry':result['entry'],'runtime':result['runtime'],'resources':{u:{k:v for k,v in d.items() if k!='path'} for u,d in result['resources'].items()},
            'semantic_report':{'bindings':{'sha256':bindings['producerInputSha256']}},'profile_report':{'external_bindings':bindings},'evidence':{}}
        result['record']=put(packed(record),'.json')
        row={'status':'ok','identity':identity,'result':result}
        return root,wrapper,artifact,identity,policy,url,row,assets
    def cache(self,rows,assets):
        path=self.root/'results.jsonl';raw=b''.join(packed(row)+b'\n' for row in rows);path.write_bytes(raw)
        value={'schema':'study-complete-result-cache.v1','files':[{'path':str(path),'sha256':sha(raw),'bytes':len(raw),'assets':str(assets)}],'completed_semantic':{}}
        index=self.root/'index.json';raw=packed(value);index.write_bytes(raw)
        return resume.ResultCache({'path':str(index),'sha256':sha(raw)})
    def build(self,mapper,f):return mapper.build(f[0],f[1],f[2],identity=f[3],policy=f[4],source_url=f[5])
    def test_actual_producer_three_field_resource_descriptor_is_accepted(self):
        f=self.fixture()
        for descriptor in f[6]['result']['resources'].values():descriptor.pop('src',None)
        record=json.loads((f[7]/f[6]['result']['record']['src']).read_bytes())
        record['resources']={url:{k:v for k,v in descriptor.items() if k!='path'} for url,descriptor in f[6]['result']['resources'].items()}
        raw=packed(record);name='_qa_compiled_'+sha(raw)+'.json';(f[7]/name).write_bytes(raw);f[6]['result']['record']={'src':name,'sha256':sha(raw)}
        with self.cache([f[6]],f[7]) as cache:self.build(resume.MapBuilder(cache),f)
    def test_current_complete_result_and_all_bindings_pass(self):
        f=self.fixture()
        with self.cache([f[6]],f[7]) as cache:
            mapper=resume.MapBuilder(cache);self.assertEqual(self.build(mapper,f)['build_key'],f[6]['result']['build_key']);mapper.check()
    def test_duplicate_success_identity_rejected(self):
        f=self.fixture()
        with self.assertRaisesRegex(ValueError,'duplicate'):self.cache([f[6],f[6]],f[7])
    def test_external_log_pin_and_late_row_tamper_rejected(self):
        f=self.fixture();cache=self.cache([f[6]],f[7]);self.addCleanup(cache.close)
        (self.root/'results.jsonl').write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError,'identity'):cache.get(f[3])
    def test_external_index_pin_rejected(self):
        path=self.root/'index.json';path.write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'SHA'):resume.ResultCache({'path':str(path),'sha256':'0'*64})
    def test_current_key_not_identity_controls_reuse(self):
        f=self.fixture()
        with self.cache([f[6]],f[7]) as cache:
            for change in ('url','policy','identity','artifact'):
                row=list(f)
                if change=='url':row[5]='https://study.test/other/index.html'
                if change=='policy':row[4]={'external':{'new.js':'0'*64},'inline':[]}
                if change=='identity':row[3]='other:card'
                if change=='artifact':
                    value=json.loads((f[0]/f[2]['path']).read_bytes());value['extra']='changed';raw=packed(value)
                    (f[0]/'evidence/changed.json').write_bytes(raw);row[2]={'path':'evidence/changed.json','sha256':sha(raw)}
                with self.subTest(change=change),self.assertRaises((ValueError,KeyError)):self.build(resume.MapBuilder(cache),row)
    def test_profile_report_binding_mismatch_is_rejected(self):
        f=self.fixture();result=f[6]['result'];path=f[7]/result['record']['src'];record=json.loads(path.read_bytes())
        record['profile_report']['external_bindings']['readerDelegateSha256']='0'*64
        raw=packed(record);name='_qa_compiled_'+sha(raw)+'.json';(f[7]/name).write_bytes(raw);result['record']={'src':name,'sha256':sha(raw)}
        with self.cache([f[6]],f[7]) as cache,self.assertRaisesRegex(ValueError,'binding'):self.build(resume.MapBuilder(cache),f)
    def test_later_card_resource_drift_caught_by_final_receipts(self):
        f=self.fixture()
        with self.cache([f[6]],f[7]) as cache:
            mapper=resume.MapBuilder(cache);self.build(mapper,f)
            (f[0]/'evidence/original.js').write_bytes(b'later card changes previous resource')
            with self.assertRaisesRegex(ValueError,'SHA|changed'):mapper.check()
    def test_unpinned_current_module_rejected(self):
        f=self.fixture();(f[0]/'evidence/original.js').write_bytes(b'wrong current module')
        with self.cache([f[6]],f[7]) as cache,self.assertRaisesRegex(ValueError,'SHA'):self.build(resume.MapBuilder(cache),f)

class TwoBooks(unittest.TestCase):
    setUp=delivery_fixture.DeliveryTests.setUp
    fixture=delivery_fixture.DeliveryTests.fixture
    reseal=delivery_fixture.DeliveryTests.reseal
    two_book_fixture=delivery_fixture.DeliveryTests.two_book_fixture
    # Only these added cases are loaded below, not inherited product suite.
    def test_prepare_has_distinct_authority_not_delivery_complete(self):
        source,_=self.two_book_fixture()
        result=self.delivery.derive_batch(source,self.root/'prepared',expected_complete_sha256=sha((source/'COMPLETE.json').read_bytes()),base_url='https://study.test/',prepare_only=True)
        self.assertEqual(result['schema'],'study-web-batch-preparation.v1')
        self.assertFalse((self.root/'prepared/COMPLETE.json').exists())
        self.assertTrue((self.root/'prepared/preparation-authority/COMPLETE.json').exists())
    def test_finalize_same_common_builder_two_authored_books_without_node(self):
        source,_=self.two_book_fixture();empty=self.root/'empty.json';raw=packed({'schema':'study-complete-result-cache.v1','files':[],'completed_semantic':{}});empty.write_bytes(raw)
        with resume.ResultCache({'path':str(empty),'sha256':sha(raw)}) as cache:
            receipts=resume._Receipts()
            @contextmanager
            def factory(directory):
                with schedule.StageSeparatedBuild(directory) as original:
                    yield resume.MapBuilder(cache,source_builder=original,receipts=receipts)
                    self.assertIsNone(original.worker)
            result=self.delivery.derive_batch(source,self.root/'final',expected_complete_sha256=sha((source/'COMPLETE.json').read_bytes()),base_url='https://study.test/',builder_factory=factory,final_check=receipts.check)
        self.assertEqual([r['delivery']['modes'] for r in result['webs']],[{'compiled':0,'authored':2}]*2)
        self.assertTrue((self.root/'final/COMPLETE.json').exists())
    def test_second_book_changes_first_resource_no_complete(self):
        source,first=self.two_book_fixture();changed=[]
        def callback(event):
            if event['stage']=='export-web-compile' and event['book_id']=='second-subject' and not changed:
                (first/'media/ordinary.mp3').write_bytes(b'second book mutation');changed.append(True)
        with self.assertRaisesRegex(ValueError,'SHA|changed'):
            self.delivery.derive_batch(source,self.root/'final',expected_complete_sha256=sha((source/'COMPLETE.json').read_bytes()),base_url='https://study.test/',callback=callback)
        self.assertFalse((self.root/'final/COMPLETE.json').exists());self.assertTrue((self.root/'final/FAILED.json').exists())

if __name__=='__main__':
    suite=unittest.TestSuite();suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CacheTests))
    suite.addTests(TwoBooks(n) for n in ('test_prepare_has_distinct_authority_not_delivery_complete','test_finalize_same_common_builder_two_authored_books_without_node','test_second_book_changes_first_resource_no_complete'))
    result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())
