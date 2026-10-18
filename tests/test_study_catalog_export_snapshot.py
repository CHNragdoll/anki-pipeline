"""Small export builders and an explicit RR fixture; never opens PostgreSQL."""
from contextlib import closing,contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from anki_pipeline import study_catalog_export as exporter

REAL_APKG=exporter._apkg


class Rows:
    def __init__(self, rows):self.rows=rows
    def fetchone(self):return self.rows[0]
    def fetchall(self):return self.rows
    def __iter__(self):return iter(self.rows)


class SnapshotDatabase:
    def __init__(self):
        self.live={'revision':17,'field':'original','component':'1'*64}
        self.view=None;self.calls=[];self.transactions=0
    @contextmanager
    def transaction(self):
        self.transactions+=1;self.view=deepcopy(self.live)
        try:yield self
        finally:self.view=None
    def execute(self,sql,params=None):
        query=' '.join(sql.split());self.calls.append((query,params))
        if self.view is None:raise AssertionError('read escaped the one transaction')
        if query.startswith('SET TRANSACTION '):return Rows([])
        if not query.lower().startswith('select '):raise AssertionError('export attempted a PG write')
        if query.startswith('select current_database()'):
            return Rows([('fixture','owned-fixture','10:20:','repeatable read','on')])
        if query=='select coalesce(max(id),0) from events':return Rows([(self.view['revision'],)])
        if query.startswith('select s.source_id,s.collection_id,s.col_payload_id,x.manifest_id '):
            return Rows([('source-'+params[0],'collection-'+params[0],'col-'+params[0],'manifest-'+params[0])])
        if query.startswith('select distinct c.id,c.current_id from components c '):
            return Rows([('field-component',self.view['component']),('template-component','2'*64)])
        if query=='select fixture_field':return Rows([(self.view['field'],self.view['revision'])])
        raise AssertionError('unknown fixture SELECT: '+query)


class ExportSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.output=self.root/'batch'
        self.db=SnapshotDatabase();self.connections=[];self.projects=[];self.builds=[]
        @contextmanager
        def connect(value,*,readonly=False):
            self.connections.append((value,readonly))
            yield self.db
        self.addCleanup(patch.stopall)
        patch.object(exporter.c,'connect',connect).start()
        patch.object(exporter,'project_book',self.project).start()
        patch.object(exporter,'_apkg',self.apkg).start()
        patch.object(exporter,'_web',self.web).start()
        patch.object(exporter.presentation,'registry',return_value={'books':{
            key:{'models':{'1':{'qfmt:0':'template-component'}},'resources':{}}
            for key in ('one','two','three')}}).start()

    def project(self,db,key):
        self.assertIs(db,self.db);self.assertIsNotNone(db.view);self.projects.append(key)
        if key=='missing':raise ValueError('unknown book')
        return {'id':key,'revision':db.view['revision'],'collection_id':'collection-'+key,
            'col':{'models':'{}'},'manifest':{'fixture':key},'models':{'model':{'version':1}},
            'runtime':{'sources':{'a.js':'0'*64},'aliases':{},'generated':{'b.js':b'fixed runtime'}},
            'content_mods':{},'runtime_revision':{'revision':2,'floor':99},'semantic_projections':{}}

    def built(self,db,book,folder,fmt,callback):
        field,revision=db.execute('select fixture_field').fetchone()
        self.builds.append((db,book['id'],fmt,book['revision'],field,revision))
        if callback:callback({'stage':'fixture','book_id':book['id'],'format':fmt})
        return json.dumps([book['id'],fmt,field,revision]).encode()

    def apkg(self,db,book,folder,name,callback):
        raw=self.built(db,book,folder,'apkg',callback)
        (folder/name).write_bytes(raw)
        return {'schema':'fixture-export.v1','format':'apkg','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}

    def web(self,db,book,folder,callback):
        raw=self.built(db,book,folder,'web',callback)
        (folder/'web').mkdir();(folder/'web/index.html').write_bytes(raw)
        return {'schema':'fixture-export.v1','format':'web','cards':1}

    def requests(self):
        return [{'book_id':book,'format':fmt,'name':book+('.apkg' if fmt=='apkg' else '-web')}
                for book in ('one','two','three') for fmt in ('apkg','web')]

    def test_six_exports_share_one_rr_snapshot_and_pinned_book_projection(self):
        def writer(_):self.db.live.update(revision=18,field='later',component='9'*64)
        report=exporter.export_batch('explicit-target',self.requests(),self.output,callback=writer)
        self.assertEqual(self.connections,[('explicit-target',True)]);self.assertEqual(self.db.transactions,1)
        self.assertEqual([query for query,_ in self.db.calls if query.startswith('SET TRANSACTION ')],
                         ['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'])
        self.assertEqual(self.projects,['one','two','three'])
        self.assertEqual(len(self.builds),6)
        self.assertTrue(all(row[0] is self.db and row[3:]==(17,'original',17) for row in self.builds))
        self.assertEqual(self.db.live['revision'],18)
        self.assertEqual(report['snapshot']['catalog_revision'],17)
        self.assertEqual(report['snapshot']['isolation'],'repeatable read')
        self.assertTrue(report['snapshot']['read_only'])
        for key,pins in report['books'].items():
            self.assertEqual(pins['catalog_revision'],17)
            self.assertEqual(pins['components']['field-component'],'1'*64)
            self.assertEqual(pins['runtime']['generated']['b.js'],hashlib.sha256(b'fixed runtime').hexdigest())
            self.assertEqual(pins['components_sha256'],hashlib.sha256(
                exporter.c.canonical(pins['components']).encode()).hexdigest())
        manifest=json.loads((self.output/'manifest.json').read_bytes())
        self.assertEqual(manifest,report)
        complete=json.loads((self.output/'COMPLETE.json').read_bytes())
        self.assertEqual(complete['manifest_sha256'],hashlib.sha256((self.output/'manifest.json').read_bytes()).hexdigest())
        self.assertEqual(len(report['artifacts']),6)

    def test_single_api_keeps_report_and_publication_shape(self):
        path=self.root/'one.apkg';report=exporter.export_book('explicit','one',path)
        raw=path.read_bytes()
        self.assertEqual(report,{'schema':'fixture-export.v1','format':'apkg',
            'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
            'output':str(path.resolve()),'book_id':'one','catalog_revision':17})
        web=self.root/'web';report=exporter.export_book('explicit','one',web,format='web')
        self.assertEqual(json.loads((web/'COMPLETE.json').read_bytes()),
                         {'schema':'fixture-export.v1','format':'web','cards':1})
        with self.assertRaises(ValueError):exporter.export_book('explicit','one',path)
        self.assertEqual(path.read_bytes(),raw)

    def test_modern_cli_is_explicit_and_keeps_legacy_format_available(self):
        from anki_pipeline.study_catalog_cli import parser
        for fmt in ('apkg','apkg-modern','web'):
            args=parser().parse_args(['export','--book','future-subject',
                '--format',fmt,'--output',str(self.root/'result')])
            self.assertEqual(args.format,fmt)

    def test_missing_modern_codec_stops_before_database_or_output(self):
        import builtins
        original=builtins.__import__
        def missing(name,*args,**kwargs):
            if name=='zstandard':raise ImportError('codec unavailable')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',missing):
            with self.assertRaisesRegex(ValueError,'--extra apkg'):
                exporter.export_book('explicit','one',self.root/'single.apkg',format='apkg-modern')
            with self.assertRaisesRegex(ValueError,'--extra apkg'):
                exporter.export_batch('explicit',[{'book_id':'one','format':'apkg-modern','name':'one.apkg'}],self.output)
        self.assertEqual(self.connections,[])
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.study-modern-build-*')))

    def test_modern_single_keeps_owned_failure_evidence_and_actor_files(self):
        def container(source,destination,report,callback):
            (source.parent.parent/'actor.txt').write_bytes(b'actor evidence')
            if destination.name!='result.apkg':raise AssertionError('external output name leaked into scratch layout')
            destination.write_bytes(b'candidate')
            return {**report,'format':'apkg-modern','sha256':hashlib.sha256(b'candidate').hexdigest(),'bytes':9}
        with patch.object(exporter,'_modern_container',container):
            # These external names coincide with internal scratch members.
            for name in ('legacy','standard-modern.apkg','result.apkg'):
                report=exporter.export_book('explicit','one',self.root/name,format='apkg-modern')
                self.assertEqual((self.root/name).read_bytes(),b'candidate')
                self.assertEqual((Path(report['retained_staging'])/'actor.txt').read_bytes(),b'actor evidence')
        def failed(source,destination,report,callback):
            (source.parent.parent/'failure.txt').write_bytes(b'failure evidence')
            raise RuntimeError('conversion failed')
        with patch.object(exporter,'_modern_container',failed),self.assertRaisesRegex(RuntimeError,'conversion failed'):
            exporter.export_book('explicit','one',self.root/'failed.apkg',format='apkg-modern')
        self.assertFalse((self.root/'failed.apkg').exists())
        self.assertEqual(len(list(self.root.glob('.study-modern-build-*/failure.txt'))),1)

    def test_modern_publication_refuses_replaced_source_in_single_and_batch(self):
        real_link=os.link
        for api in ('single','batch'):
            with self.subTest(api=api):
                path=self.root/('race-'+api)
                target=path if api=='single' else path/'one.apkg'
                def container(source,destination,report,callback):
                    destination.write_bytes(b'owned candidate')
                    return {**report,'format':'apkg-modern','sha256':hashlib.sha256(b'owned candidate').hexdigest(),'bytes':15}
                def replace(source,destination,*args,**kwargs):
                    if Path(destination)==target:
                        source=Path(source);source.rename(source.with_name('owned.kept'))
                        source.write_bytes(b'foreign replacement')
                    return real_link(source,destination,*args,**kwargs)
                with patch.object(exporter,'_modern_container',container),patch.object(exporter.os,'link',replace):
                    with self.assertRaisesRegex(ValueError,'modern publication'):
                        if api=='single':exporter.export_book('explicit','one',path,format='apkg-modern')
                        else:exporter.export_batch('explicit',[{'book_id':'one','format':'apkg-modern','name':'one.apkg'}],path)
                self.assertEqual(target.read_bytes(),b'foreign replacement')
                if api=='batch':self.assertFalse((path/'COMPLETE.json').exists())

    def test_modern_and_legacy_containers_share_the_same_snapshot_and_raw_content(self):
        import zstandard
        payloads={}
        audio=b'original audio bytes\0\xff'
        def apkg(db,book,folder,name,callback):
            raw=self.built(db,book,folder,'apkg',callback)
            with closing(sqlite3.connect(':memory:')) as sql:
                sql.execute('create table rendered (payload blob)')
                sql.execute('insert into rendered values (?)',(raw,))
                payload=sql.serialize()
            payloads[book['id']]=payload
            path=folder/name
            with zipfile.ZipFile(path,'x') as archive:
                archive.writestr('collection.anki2',payload)
                archive.writestr('media',json.dumps({'3':'声音.mp3'}))
                archive.writestr('3',audio)
                archive.writestr('extra.txt',b'original extra bytes')
            return {'format':'apkg','notes':1,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'bytes':path.stat().st_size,'projection':'project_book/project_note'}
        requests=[{'book_id':book,'format':fmt,'name':book+'-'+fmt}
            for book in ('one','two','three') for fmt in ('apkg','apkg-modern','web')]
        def later(_):self.db.live.update(revision=18,field='later',component='9'*64)
        with patch.object(exporter,'_apkg',apkg):
            result=exporter.export_batch('explicit',requests,self.output,callback=later)
        self.assertEqual(self.connections,[('explicit',True)])
        self.assertEqual(self.db.transactions,1)
        self.assertEqual(self.projects,['one','two','three'])
        self.assertTrue(all(item[3:]==(17,'original',17) for item in self.builds))
        self.assertEqual(result['snapshot']['catalog_revision'],17)
        self.assertEqual(len(result['artifacts']),9)
        for book in ('one','two','three'):
            path=self.output/(book+'-apkg-modern')
            report=next(row['report'] for row in result['artifacts']
                if row['book_id']==book and row['format']=='apkg-modern')
            self.assertEqual(report['format'],'apkg-modern')
            self.assertEqual(report['projection'],'project_book/project_note')
            self.assertEqual(report['bytes'],path.stat().st_size)
            self.assertEqual(report['sha256'],hashlib.sha256(path.read_bytes()).hexdigest())
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read('meta'),b'\x08\x03')
                self.assertEqual(zstandard.ZstdDecompressor().decompress(
                    archive.read('collection.anki21b')),payloads[book])
                self.assertEqual(zstandard.ZstdDecompressor().decompress(archive.read('0')),audio)
                self.assertEqual(archive.read('extra.txt'),b'original extra bytes')

    def test_real_small_apkg_members_match_single_and_batch_without_pg(self):
        source=self.root/'source.sqlite'
        with closing(sqlite3.connect(source)) as native,native:
            native.executescript('create table col(models text);insert into col values(\'{}\');'
                'create table notes(id integer primary key,guid text,mid integer,flds text,'
                'mod integer,sfld text,csum integer,usn integer);')
            native.execute('insert into notes values(1,?,1,?,1,?,0,0)',('guid','term\x1foriginal','term'))
        collection=source.read_bytes();original_project=self.project;original_execute=self.db.execute
        metadata={'date_time':[2020,1,2,3,4,6],'compress_type':8,'create_system':3,
                  'create_version':20,'extract_version':20,'internal_attr':0,
                  'external_attr':0,'comment':'','extra':''}
        def project(db,key):
            book=original_project(db,key);book['models']={}
            book['manifest']={'collection_entry':'collection.anki2','collection_zip_info':metadata,
                              'media':{},'extra_members':{}}
            return book
        def execute(sql,params=None):
            if sql.startswith('select note_id from notes '):return Rows([(1,)])
            if sql.startswith('select name,object_id,zip_info_id from resource_aliases '):return Rows([])
            return original_execute(sql,params)
        def write_object(db,key,stream):
            self.assertIs(db,self.db);self.assertEqual(key,'collection-one');stream.write(collection)
        note={'guid':'guid','model_id':1,'fields':['term','revised meaning'],
              'content_mod':2,'model':{'sortf':0}}
        with patch.object(exporter,'project_book',project),patch.object(exporter,'project_note',return_value=note), \
                patch.object(exporter,'_apkg',REAL_APKG),patch.object(exporter.c,'write_object',write_object), \
                patch.object(self.db,'execute',execute):
            single=self.root/'one.apkg';one=exporter.export_book('explicit','one',single)
            batch=exporter.export_batch('explicit',[{'book_id':'one','format':'apkg','name':'one.apkg'}],self.output)
        self.assertEqual(one['notes'],1);self.assertEqual(one['shared_field_changes'],1)
        with zipfile.ZipFile(single) as first,zipfile.ZipFile(self.output/'one.apkg') as second:
            self.assertEqual(set(first.namelist()),set(second.namelist()))
            for name in first.namelist():self.assertEqual(first.read(name),second.read(name))
            with closing(sqlite3.connect(':memory:')) as native:
                native.deserialize(second.read('collection.anki2'))
                self.assertEqual(native.execute('select guid,mid,flds,mod from notes').fetchone(),
                                 ('guid',1,'term\x1frevised meaning',2))
        self.assertEqual(batch['artifacts'][0]['report']['shared_field_changes'],1)
        self.assertEqual((self.output/'COMPLETE.json').stat().st_mode&0o777,0o600)

    def test_request_validation_happens_before_connect_or_output_creation(self):
        invalid=[[],[{'book_id':'one','format':'unknown','name':'x'}],
            [{'book_id':'one','format':'web','name':'../escape'}],
            [{'book_id':'one','format':'web','name':'/absolute'}],
            [{'book_id':'one','format':'web','name':'COMPLETE.json'}],
            [{'book_id':'one','format':'web','name':'manifest.json'}],
            [{'book_id':'one','format':'web','name':'a\\b'}],
            [{'book_id':'one','format':'web','name':'Café'}, {'book_id':'two','format':'apkg','name':'Cafe\u0301'}],
            [{'book_id':'one','format':'web','name':'a'}, {'book_id':'one','format':'web','name':'b'}],
            [{'book_id':'one','format':'web','name':'Same'}, {'book_id':'two','format':'apkg','name':'same'}]]
        for requests in invalid:
            with self.subTest(requests=requests),self.assertRaises(ValueError):
                exporter.export_batch('explicit',requests,self.output)
            self.assertFalse(self.output.exists());self.assertEqual(self.connections,[])

    def test_failure_keeps_completed_outputs_partial_diagnostic_and_no_complete(self):
        calls=0
        def fail(event):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('injected failure')
        with self.assertRaises(RuntimeError):exporter.export_batch('explicit',self.requests(),self.output,callback=fail)
        self.assertTrue((self.output/'one.apkg').is_file())
        self.assertFalse((self.output/'COMPLETE.json').exists())
        self.assertTrue((self.output/'FAILED.json').is_file())
        self.assertTrue((self.output/'.partial').is_dir())
        self.assertEqual(self.db.transactions,1)

    def test_existing_output_or_racing_child_is_never_overwritten(self):
        self.output.mkdir();sentinel=self.output/'keep';sentinel.write_bytes(b'original')
        with self.assertRaises(ValueError):exporter.export_batch('explicit',self.requests(),self.output)
        self.assertEqual(sentinel.read_bytes(),b'original');self.assertEqual(self.connections,[])
        other=self.root/'racing'
        def race(_):(other/'one.apkg').write_bytes(b'foreign output')
        with self.assertRaises(FileExistsError):exporter.export_batch('explicit',self.requests(),other,callback=race)
        self.assertEqual((other/'one.apkg').read_bytes(),b'foreign output')
        self.assertFalse((other/'COMPLETE.json').exists())

    def test_success_never_recursively_removes_actor_files_in_private_stage(self):
        actor=self.output/'.partial/0000/actor-owned.txt'
        def add_actor(_):
            if not actor.exists():actor.write_bytes(b'actor owned evidence')
        request=[{'book_id':'one','format':'apkg','name':'one.apkg'}]
        report=exporter.export_batch('explicit',request,self.output,callback=add_actor)
        self.assertEqual(actor.read_bytes(),b'actor owned evidence')
        self.assertTrue((self.output/'COMPLETE.json').exists())
        self.assertEqual(len(report['artifacts']),1)
        self.assertNotIn('.partial',[row['name'] for row in report['artifacts']])

    def test_web_publication_never_overwrites_a_racing_target_file(self):
        original=Path.mkdir
        for api in ('single','batch'):
            with self.subTest(api=api):
                root=self.root/('web-race-'+api);target=root if api=='single' else root/'one-web'
                actor=target/'index.html'
                def mkdir(path,*args,**kwargs):
                    result=original(path,*args,**kwargs)
                    if path==target:actor.write_bytes(b'actor index')
                    return result
                with patch.object(Path,'mkdir',mkdir),self.assertRaises(FileExistsError):
                    if api=='single':exporter.export_book('explicit','one',root,format='web')
                    else:exporter.export_batch('explicit',[{'book_id':'one','format':'web','name':'one-web'}],root)
                self.assertEqual(actor.read_bytes(),b'actor index')
                self.assertFalse((root/'COMPLETE.json').exists())

    def test_web_nested_publication_preserves_all_bytes_and_rejects_existing_directory(self):
        def web(db,book,folder,callback):
            report=self.web(db,book,folder,callback)
            (folder/'web/media').mkdir();(folder/'web/media/source.js').write_bytes(b'original runtime')
            return report
        request=[{'book_id':'one','format':'web','name':'one-web'}]
        with patch.object(exporter,'_web',web):report=exporter.export_batch('explicit',request,self.output)
        self.assertEqual((self.output/'one-web/media/source.js').read_bytes(),b'original runtime')
        self.assertEqual(json.loads((self.output/'one-web/index.html').read_bytes()),['one','web','original',17])
        self.assertEqual(report['artifacts'][0]['report'],{'schema':'fixture-export.v1','format':'web','cards':1})

        other=self.root/'web-directory-race';target=other/'one-web';original=Path.mkdir
        def mkdir(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==target:
                original(target/'media');(target/'media/actor.txt').write_bytes(b'actor directory')
            return result
        with patch.object(exporter,'_web',web),patch.object(Path,'mkdir',mkdir),self.assertRaises(FileExistsError):
            exporter.export_batch('explicit',request,other)
        self.assertEqual((target/'media/actor.txt').read_bytes(),b'actor directory')
        self.assertFalse((other/'COMPLETE.json').exists())

    def test_unknown_book_or_projection_revision_drift_stops_before_batch_reservation(self):
        with self.assertRaises(ValueError):
            exporter.export_batch('explicit',[{'book_id':'missing','format':'web','name':'x'}],self.output)
        self.assertFalse(self.output.exists())
        original=self.project
        def drift(db,key):
            value=original(db,key);value['revision']+=1;return value
        with patch.object(exporter,'project_book',side_effect=drift),self.assertRaises(ValueError):
            exporter.export_batch('explicit',self.requests(),self.output)
        self.assertFalse(self.output.exists());self.assertEqual(self.builds,[])

    def test_cancellation_and_transaction_exit_failure_never_complete_a_batch(self):
        def cancel(_):raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            exporter.export_batch('explicit',self.requests(),self.output,callback=cancel)
        self.assertEqual(json.loads((self.output/'FAILED.json').read_bytes())['error_type'],'KeyboardInterrupt')
        self.assertFalse((self.output/'COMPLETE.json').exists())
        second=self.root/'tx-exit-failure';original=self.db.transaction
        @contextmanager
        def exit_failure():
            with original():
                yield self.db
                raise RuntimeError('injected read transaction close failure')
        with patch.object(self.db,'transaction',exit_failure),self.assertRaises(RuntimeError):
            exporter.export_batch('explicit',self.requests(),second)
        self.assertTrue((second/'three-web/index.html').exists())
        self.assertFalse((second/'COMPLETE.json').exists())
        self.assertFalse((second/'manifest.json').exists())
        self.assertTrue((second/'FAILED.json').exists())

    def test_incomplete_completion_write_or_close_does_not_publish_complete(self):
        original_open,original_fdopen=Path.open,os.fdopen
        for failure in ('write','close'):
            output=self.root/('completion-'+failure)
            @contextmanager
            def wrap(stream):
                complete=False
                class Fault:
                    def __getattr__(inner,key):return getattr(stream,key)
                    def write(inner,value):
                        nonlocal complete
                        complete='study-catalog-export-batch-complete.v1' in (
                            value.decode() if isinstance(value,bytes) else value)
                        result=stream.write(value)
                        if complete and failure=='write':
                            stream.flush();raise OSError('injected completion write failure')
                        return result
                try:yield Fault()
                finally:
                    stream.close()
                    if complete and failure=='close':raise OSError('injected completion close failure')
            def fault_open(path,*args,**kwargs):return wrap(original_open(path,*args,**kwargs))
            def fault_fdopen(*args,**kwargs):return wrap(original_fdopen(*args,**kwargs))
            with self.subTest(failure=failure),patch.object(Path,'open',fault_open), \
                    patch.object(os,'fdopen',fault_fdopen),self.assertRaises(OSError):
                exporter.export_batch('explicit',self.requests(),output)
            self.assertFalse((output/'COMPLETE.json').exists())
            self.assertTrue((output/'FAILED.json').exists())

    def test_completion_publish_cancellation_cleans_only_owned_marker(self):
        original=os.link
        def link_then_cancel(source,destination,*args,**kwargs):
            result=original(source,destination,*args,**kwargs)
            if Path(destination).name=='COMPLETE.json':raise KeyboardInterrupt
            return result
        with patch.object(os,'link',link_then_cancel),self.assertRaises(KeyboardInterrupt):
            exporter.export_batch('explicit',self.requests(),self.output)
        self.assertFalse((self.output/'COMPLETE.json').exists())
        self.assertTrue((self.output/'FAILED.json').exists())

        other=self.root/'completion-race'
        def replace_then_cancel(source,destination,*args,**kwargs):
            result=original(source,destination,*args,**kwargs)
            if Path(destination).name=='COMPLETE.json':
                Path(destination).unlink();Path(destination).write_bytes(b'actor marker')
                raise KeyboardInterrupt
            return result
        with patch.object(os,'link',replace_then_cancel),self.assertRaises(KeyboardInterrupt):
            exporter.export_batch('explicit',self.requests(),other)
        self.assertEqual((other/'COMPLETE.json').read_bytes(),b'actor marker')
        self.assertTrue((other/'FAILED.json').exists())

    def test_completion_publish_does_not_replace_an_existing_actor_marker(self):
        original=os.link
        def actor_race(source,destination,*args,**kwargs):
            if Path(destination).name=='COMPLETE.json':Path(destination).write_bytes(b'actor marker')
            return original(source,destination,*args,**kwargs)
        with patch.object(os,'link',actor_race),self.assertRaises(FileExistsError):
            exporter.export_batch('explicit',self.requests(),self.output)
        self.assertEqual((self.output/'COMPLETE.json').read_bytes(),b'actor marker')
        self.assertTrue((self.output/'FAILED.json').exists())

    def test_completion_source_and_published_replacements_never_return_success(self):
        original=os.link
        for mutation in ('source-replaced','destination-replaced','source-inplace'):
            output=self.root/mutation;paths={}
            def replace(source,destination,*args,**kwargs):
                source,destination=Path(source),Path(destination)
                if destination.name!='COMPLETE.json':return original(source,destination,*args,**kwargs)
                paths['source']=source
                if mutation=='source-replaced':
                    source.unlink();source.write_bytes(b'foreign incomplete marker')
                if mutation=='source-inplace':source.write_bytes(b'modified owned bytes')
                result=original(source,destination,*args,**kwargs)
                if mutation=='destination-replaced':
                    destination.unlink();destination.write_bytes(b'foreign destination marker')
                return result
            with self.subTest(mutation=mutation),patch.object(os,'link',replace),self.assertRaises(OSError):
                exporter.export_batch('explicit',self.requests(),output)
            if mutation=='source-replaced':
                self.assertEqual(paths['source'].read_bytes(),b'foreign incomplete marker')
                self.assertEqual((output/'COMPLETE.json').read_bytes(),b'foreign incomplete marker')
            elif mutation=='destination-replaced':
                self.assertEqual((output/'COMPLETE.json').read_bytes(),b'foreign destination marker')
            else:
                self.assertFalse(paths['source'].exists());self.assertFalse((output/'COMPLETE.json').exists())
            self.assertTrue((output/'FAILED.json').exists())


if __name__=='__main__':unittest.main()
