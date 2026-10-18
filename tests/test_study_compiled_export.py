"""Native export glue, against actual tiny SQLite/APKG bytes without PostgreSQL."""
import base64
import copy
from contextlib import ExitStack, closing, nullcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_export as export
from anki_pipeline.study_catalog_anki import field_cache
from anki_pipeline.study_compiled_build import ArtifactStore
from anki_pipeline.study_compiled_runtime import upgrade_delivery_runtime
from tests import test_study_compiled_native as native_fixture


class Rows:
    def __init__(self, rows): self.rows = list(rows)
    def __iter__(self): return iter(self.rows)
    def fetchone(self): return self.rows[0] if self.rows else None


class CompiledExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.note = native_fixture.sample_note()
        self.note['content_mod'] = None
        self.notes = {31: self.note}
        self.models = {'17': copy.deepcopy(self.note['model'])}
        source = self.root/'source.anki2'
        with closing(sqlite3.connect(source)) as db, db:
            db.executescript('''
                create table col(id integer primary key, models text, decks text, conf text);
                create table notes(id integer primary key,guid text,mid integer,mod integer,usn integer,
                    tags text,flds text,sfld text,csum integer,flags integer,data text);
                create table cards(id integer primary key,nid integer,did integer,ord integer,mod integer,
                    usn integer,type integer,queue integer,due integer,ivl integer,factor integer,
                    reps integer,lapses integer,left integer,odue integer,odid integer,flags integer,data text);
                create table revlog(id integer primary key,cid integer,usn integer,ease integer,ivl integer,
                    lastIvl integer,factor integer,time integer,type integer);
                create table graves(usn integer,oid integer,type integer);
            ''')
            db.execute('insert into col values(1,?,?,?)',(c.canonical(self.models),'original decks','original config'))
            plain, checksum = field_cache(self.note['fields'], self.note['model'])
            db.execute('insert into notes values(?,?,?,?,?,?,?,?,?,?,?)',
                (31,self.note['guid'],17,19,8,' original tags ','\x1f'.join(self.note['fields']),plain,checksum,7,'original note data'))
            db.execute('insert into cards values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (41,31,51,0,101,8,2,2,92,14,2400,17,3,0,0,0,5,'original scheduling'))
            db.execute('insert into revlog values(1,41,8,3,14,7,2400,950,1)')
            db.execute('insert into graves values(8,75,1)')
        self.original = source.read_bytes()
        metadata = dict(date_time=[2026,10,17,0,0,0],compress_type=zipfile.ZIP_DEFLATED,
            create_system=3,create_version=20,extract_version=20,internal_attr=0,external_attr=0,comment='',extra='')
        self.objects = {'collection':self.original,'audio':b'original audio bytes','js':b'original JS bytes',
            'media-index':b'{"0": "recording.mp3", "1": "original.js"}', 'extra':b'original extra member'}
        self.book = {'id':'book','revision':77,'models':copy.deepcopy(self.models),'col':{'models':c.canonical(self.models)},
            'collection_id':'collection','runtime':{'sources':{},'generated':{}},
            'manifest':{'collection_entry':'collection.anki2','collection_zip_info':metadata,
                'media':{'0':'recording.mp3','1':'original.js'},'media_index_id':'media-index',
                'extra_members':{'README.txt':{'object_id':'extra','zip_info':metadata}}}}
        self.metadata = metadata
        class DB:
            def __enter__(inner):return inner
            def __exit__(inner,*args):return False
            def transaction(inner):return nullcontext()
            def execute(inner, query, args=()):
                if query.startswith('SET TRANSACTION'):return Rows([])
                if query.startswith('select note_id from notes'): return Rows((key,) for key in self.notes)
                if query.startswith('select name,object_id,zip_info_id from resource_aliases'):
                    return Rows([('recording.mp3','audio','metadata'),('original.js','js','metadata')])
                raise AssertionError('unexpected catalog read: '+query)
        self.db = DB()

    def tearDown(self): self.temporary.cleanup()

    def registered(self):
        self.book['models']['17']['mod'] = 22
        self.note['model'] = self.book['models']['17']
        self.note['content_mod'] = 23
        return {'models':{17:22},'notes':{31:23}}

    def delivery(self, note=None, previous=False):
        note=note or self.note
        bundle = native_fixture.NativeCompiledTests().bundle()
        if previous:
            from anki_pipeline.study_compiled_runtime import PREVIOUS_RUNTIME_SHA256
            bundle['runtime']['sha256'] = PREVIOUS_RUNTIME_SHA256
            bundle['resources'][bundle['runtime']['src']] = (Path(__file__).parent /
                'fixtures/experimental-compiled-card-v1/history-slots-v1/previous-owner-runtime.js').read_bytes()
        store = ArtifactStore(self.root/('assets-'+str(len(list(self.root.glob('assets-*'))))))
        resources = {}
        for name, raw in bundle['resources'].items():
            asset = store.put(raw, 'html' if name.endswith('.html') else 'json' if name.endswith('.json') else 'js')
            resources['https://example.test/book/'+name] = store.descriptor(asset)
        # Real CompiledBuild assets use content-addressed public basenames.
        entry = copy.deepcopy(bundle['entry'])
        for key in ['html','profile']:
            old = entry[key]['src']; descriptor = resources.pop('https://example.test/book/'+old)
            entry[key] = {'src':Path(descriptor['path']).name,'sha256':descriptor['sha256']}
            resources['https://example.test/book/'+entry[key]['src']] = descriptor
        old_runtime = bundle['runtime']; descriptor = resources.pop('https://example.test/book/'+old_runtime['src'])
        runtime = {'src':Path(descriptor['path']).name,'sha256':descriptor['sha256']}
        resources['https://example.test/book/'+runtime['src']] = descriptor
        identity = 'book:'+note['id']
        record = {'schema':'study-complete-card-build.v1','identity':identity,'build_key':'a'*64,
            'entry':entry,'runtime':runtime,'resources':{url:{k:v for k,v in item.items() if k!='path'} for url,item in resources.items()}}
        result = {'mode':'compiled','identity':identity,'entry':entry,'runtime':runtime,
            'resources':resources,'build_key':'a'*64,'record':store.put(c.canonical(record).encode(),'json')}
        result = upgrade_delivery_runtime(result,store)
        return {note['note_id']:{'result':result,'prepared':bundle['prepared'],'policy':bundle['policy'],
                    'source_sha256':export.compiled_source_sha256(note)}}

    def catalog(self):
        stack=ExitStack()
        stack.enter_context(patch.object(export,'project_note',side_effect=lambda db,book,nid:copy.deepcopy(self.notes[nid])))
        stack.enter_context(patch.object(export,'project_book',return_value=self.book))
        stack.enter_context(patch.object(c,'connect',return_value=self.db))
        stack.enter_context(patch.object(c,'write_object',side_effect=lambda db,key,out:out.write(self.objects[key])))
        stack.enter_context(patch.object(c,'get_object',side_effect=lambda db,key:self.objects[key]))
        stack.enter_context(patch.object(c,'get_json',return_value=self.metadata))
        return stack

    def run_apkg(self, **kwargs):
        folder = self.root/('run-'+str(len(list(self.root.glob('run-*')))));folder.mkdir()
        with self.catalog():
            report = export._apkg(self.db,self.book,folder,'out.apkg',None,**kwargs)
        return folder/'out.apkg', report

    def contents(self, path):
        with zipfile.ZipFile(path) as archive:
            members={name:archive.read(name) for name in archive.namelist()}
        db=sqlite3.connect(':memory:');db.deserialize(members['collection.anki2'])
        self.addCleanup(db.close)
        return db, members

    def test_default_export_preserves_collection_original_members_and_report(self):
        path, report = self.run_apkg()
        db, members = self.contents(path)
        self.assertEqual(members,{'collection.anki2':self.original,'media':self.objects['media-index'],
            '0':self.objects['audio'],'1':self.objects['js'],'README.txt':self.objects['extra']})
        self.assertNotIn('compiled_delivery',report)

    def test_explicit_common_delivery_keeps_all_native_identities_records_and_source_fields(self):
        versions=self.registered();delivery=self.delivery();before=copy.deepcopy(delivery)
        path,report=self.run_apkg(compiled_delivery=delivery,native_versions=versions)
        db,members=self.contents(path);original=sqlite3.connect(':memory:');original.deserialize(self.original)
        self.addCleanup(original.close)
        for table in ['cards','revlog','graves']:
            self.assertEqual(db.execute('select * from '+table).fetchall(),original.execute('select * from '+table).fetchall())
        row=db.execute('select id,guid,mid,mod,tags,flds,flags,data from notes').fetchone()
        self.assertEqual(row[:4],(31,self.note['guid'],17,23))
        fields=row[5].split('\x1f');meta=self.note['field_names'].index('Meta')
        self.assertEqual(len(fields),len(self.note['fields']))
        self.assertEqual(fields[:meta]+fields[meta+1:],self.note['fields'][:meta]+self.note['fields'][meta+1:])
        prefix,payload=fields[meta].split('[[study-native-delivery:v3:')
        self.assertEqual(prefix,self.note['fields'][meta]);self.assertTrue(payload.endswith(']]'))
        token=payload[:-2]
        descriptor=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
        self.assertEqual(descriptor['id'],self.note['id'])
        self.assertEqual(row[4:5]+row[6:],(' original tags ',7,'original note data'))
        models=json.loads(db.execute('select models from col').fetchone()[0])
        self.assertEqual(models['17']['flds'],self.models['17']['flds']);self.assertEqual(models['17']['mod'],22)
        self.assertNotIn('FrontSide',models['17']['tmpls'][0]['afmt'])
        for member,key in [('0','audio'),('1','js'),('README.txt','extra')]:self.assertEqual(members[member],self.objects[key])
        self.assertEqual(json.loads(members['media'])['0'],'recording.mp3')
        self.assertEqual(report['compiled_delivery']['compiled_notes'],1)
        evidence=report['compiled_delivery']['notes'][0]
        self.assertEqual(evidence['record'],delivery[31]['result']['record'])
        self.assertEqual(evidence['runtime_projection'],delivery[31]['result']['runtime_projection'])
        self.assertEqual(delivery,before)

    def test_unregistered_versions_wrong_source_or_changed_resource_refuse_output(self):
        versions=self.registered();delivery=self.delivery()
        for mutate in [lambda d,v:v['notes'].update({31:24}),lambda d,v:v['models'].update({17:23}),
                       lambda d,v:d[31].update(source_sha256='0'*64),
                       lambda d,v:d[31]['result'].update(identity='other:note')]:
            d,v=copy.deepcopy(delivery),copy.deepcopy(versions);mutate(d,v)
            with self.assertRaises(ValueError):self.run_apkg(compiled_delivery=d,native_versions=v)
        item=next(iter(delivery[31]['result']['resources'].values()));Path(item['path']).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.run_apkg(compiled_delivery=delivery,native_versions=versions)
        self.assertFalse(list(self.root.glob('run-*/out.apkg')))

    def test_previous_binder_build_record_can_upgrade_without_changing_body_or_profile(self):
        from anki_pipeline.study_compiled_runtime import PREVIOUS_RUNTIME_SHA256, CURRENT_RUNTIME_SHA256
        versions = self.registered(); delivery = self.delivery(previous=True)
        path, report = self.run_apkg(compiled_delivery=delivery, native_versions=versions)
        evidence = report['compiled_delivery']['notes'][0]
        self.assertEqual(evidence['runtime_projection']['from_sha256'], PREVIOUS_RUNTIME_SHA256)
        self.assertEqual(evidence['runtime_projection']['to_sha256'], CURRENT_RUNTIME_SHA256)
        self.assertEqual(evidence['html'], delivery[31]['result']['entry']['html'])
        self.assertEqual(evidence['profile'], delivery[31]['result']['entry']['profile'])
        self.assertTrue(path.is_file())

    def test_mixed_model_or_string_id_mapping_is_rejected(self):
        versions=self.registered();delivery=self.delivery();other=copy.deepcopy(self.note)
        other.update(note_id=32,id='plain-source',guid='plain-guid');self.notes[32]=other
        # Coverage validation must fail before an archive can be published.
        with self.assertRaisesRegex(ValueError,'mixed'):
            self.run_apkg(compiled_delivery=delivery,native_versions=versions)
        with self.assertRaises(ValueError):self.run_apkg(compiled_delivery={'31':delivery[31]},native_versions=versions)
        with self.assertRaises(ValueError):self.run_apkg(compiled_delivery=delivery,native_versions={'models':{'17':22},'notes':{31:23}})

    def test_single_and_batch_public_apis_forward_only_explicit_native_inputs(self):
        versions=self.registered();delivery=self.delivery()
        with self.catalog():
            single=export.export_book('unused','book',self.root/'single.apkg',
                compiled_delivery=delivery,native_versions=versions)
            self.assertEqual(single['compiled_delivery']['compiled_notes'],1)
            with patch.object(export,'_batch_snapshot',return_value={'catalog_revision':77}),\
                    patch.object(export,'_book_snapshot_pins',return_value={'fixture':True}):
                batch=export.export_batch('unused',[{'book_id':'book','format':'apkg','name':'deck.apkg'}],
                    self.root/'batch',compiled_delivery={'book':delivery},native_versions={'book':versions})
            self.assertEqual(batch['artifacts'][0]['report']['compiled_delivery']['compiled_notes'],1)
        self.assertTrue((self.root/'batch'/'COMPLETE.json').is_file())
        with self.assertRaises(ValueError):
            export.export_batch('unused',[{'book_id':'book','format':'web','name':'web'}],self.root/'bad-batch',
                compiled_delivery={'book':delivery},native_versions={'book':versions})

    def test_source_pin_ignores_only_revision_not_fields_templates_or_identity(self):
        before=export.compiled_source_sha256(self.note)
        clone=copy.deepcopy(self.note);clone['model']['mod']+=100;clone['content_mod']=200
        self.assertEqual(export.compiled_source_sha256(clone),before)
        for mutate in [lambda n:n['fields'].__setitem__(2,'changed'),
                       lambda n:n['model']['tmpls'][0].update(qfmt='different'),
                       lambda n:n.update(note_id=32)]:
            clone=copy.deepcopy(self.note);mutate(clone)
            self.assertNotEqual(export.compiled_source_sha256(clone),before)

    def test_same_model_multiple_compiled_notes_share_model_and_exact_carriers(self):
        versions=self.registered();delivery=self.delivery()
        other=copy.deepcopy(self.note);other.update(note_id=32,id='second-opaque-source',guid='other-guid')
        other['payload'].update(id=32,guid=other['guid']);self.notes[32]=other
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(self.original)
            db.execute('insert into notes select 32,?,mid,mod,usn,tags,flds,sfld,csum,flags,data from notes where id=31',(other['guid'],))
            db.execute('insert into cards select 42,32,did,ord,mod,usn,type,queue,due,ivl,factor,reps,lapses,left,odue,odid,flags,data from cards where id=41')
            db.commit();self.original=db.serialize();self.objects['collection']=self.original
        delivery.update(self.delivery(other));versions['notes'][32]=23
        path,report=self.run_apkg(compiled_delivery=delivery,native_versions=versions)
        db,members=self.contents(path);media=json.loads(members['media'])
        self.assertEqual(report['compiled_delivery']['compiled_notes'],2)
        self.assertEqual(db.execute('select count(*) from cards').fetchone()[0],2)
        self.assertEqual(len(json.loads(db.execute('select models from col').fetchone()[0])['17']['flds']),10)
        self.assertEqual(len(set(media.values())),len(media),'content-addressed carriers occur only once')
        self.assertEqual(len(db.execute('select flds from notes').fetchall()),2)

    def test_changed_staging_media_or_record_never_publishes_final_package(self):
        versions=self.registered();delivery=self.delivery()
        original_finish=export._CompiledNativeExport.finish
        def corrupt(context):
            report=original_finish(context)
            value=next(iter(context.media.values()))
            path=value if isinstance(value,Path) else value.members[0].path
            path.write_bytes(b'changed staged carrier')
            return report
        with self.catalog(),patch.object(export._CompiledNativeExport,'finish',corrupt):
            with self.assertRaisesRegex(ValueError,'staging media'):
                export.export_book('unused','book',self.root/'must-not-publish.apkg',
                    compiled_delivery=delivery,native_versions=versions)
        self.assertFalse((self.root/'must-not-publish.apkg').exists())
        result=delivery[31]['result']
        html=next(Path(item['path']) for url,item in result['resources'].items() if url.endswith('/'+result['entry']['html']['src']))
        (html.parent/result['record']['src']).write_bytes(b'changed build record')
        with self.assertRaises(ValueError):self.run_apkg(compiled_delivery=delivery,native_versions=versions)


if __name__=='__main__':unittest.main()
