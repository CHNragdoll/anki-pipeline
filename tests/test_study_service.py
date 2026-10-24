"""Explicit launcher configuration and real disposable dual-loopback lifecycle."""
from contextlib import contextmanager
import importlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from tests.test_study_http import request


class FakeDatabase:
    def __init__(self):self.calls=[];self.in_transaction=False
    @contextmanager
    def transaction(self):
        self.in_transaction=True
        try:yield self
        finally:self.in_transaction=False
    def execute(self,sql):self.calls.append(sql)


class StudyServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='study-service-',dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve()
        self.public=self.root/'public';self.public.mkdir()
        (self.public/'index.html').write_text('fixture bookshelf')
        self.registry=self.root/'registry.json';self.registry.write_text('{"schema":"study-service-catalog.v1","books":[]}')
        self.path=self.root/'service.json'
        self.value={'schema':'study-service.v1','postgres':{'dsn':'host=/fixture password=DO_NOT_LOG','schema':'fixture_catalog'},
            'document_root':str(self.public),'registry_path':str(self.registry),'static_mounts_path':None,
            'backups_path':str(self.root/'backups'),'audio_cache_path':str(self.root/'audio-cache'),'port':0}
        self.write_config()
        self.events=[]

    def module(self):
        return importlib.import_module('anki_pipeline.study_service')

    def write_config(self):
        self.path.write_text(json.dumps(self.value))
        self.path.chmod(0o600)

    def dependencies(self,store=None,server_factory=None):
        service=self.module()
        self.db=FakeDatabase();self.connected=[];self.loaded=[];self.storage_calls=[];self.store_calls=[]
        @contextmanager
        def connect(target,*,readonly=False):
            self.connected.append((target,readonly))
            try:yield self.db
            finally:self.connected.append('closed')
        def load(db,*,document_root,registry):
            self.assertTrue(db.in_transaction)
            self.assertEqual(db.calls,['SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'])
            self.loaded.append((document_root,registry))
            return {'future-subject':{'cards':[{'previewUrl':'/fixture/cards/a.html'}]}}
        def storage(target,*,backups):
            self.storage_calls.append((target,backups));return object()
        class Store:
            db_path=None
            def __init__(inner,db_path,books,*,storage):
                self.store_calls.append((db_path,books,storage));inner.books=books
            def dispatch(inner,method,path,query,body):
                return {'backend':'fixture','method':method}
        return service.Dependencies(connect=connect,load_books=load,storage_factory=storage,
            store_factory=store or Store,**({'server_factory':server_factory} if server_factory else {}))

    def build(self,**options):
        module=self.module()
        dependencies=options.pop('dependencies',None)
        if dependencies is None:dependencies=self.dependencies()
        options.setdefault('allow_legacy_catalog',True)
        built=module.build_service(module.load_config(self.path),dependencies=dependencies,
                                   log=self.events.append,**options)
        self.addCleanup(built.close)
        return built

    def test_explicit_config_build_never_initializes_and_two_listeners_share_port(self):
        service=self.build()
        self.assertEqual(self.connected[-1],'closed')
        self.assertTrue(self.connected[0][1])
        self.assertEqual(self.connected[0][0].schema,'fixture_catalog')
        self.assertEqual(self.store_calls[0][0],None)
        self.assertEqual(len(self.storage_calls),1)
        self.assertEqual(self.storage_calls[0][1],self.root/'backups')
        self.assertEqual({s.server_address[0] for s in service.servers},{'127.0.0.1','::1'})
        self.assertEqual(len({s.server_port for s in service.servers}),1)
        self.assertGreater(service.port,0)
        self.assertTrue(all(s.request_queue_size==128 and not s.daemon_threads and s.block_on_close for s in service.servers))
        self.assertEqual((self.root/'backups').stat().st_mode&0o777,0o700)
        self.assertEqual((self.root/'audio-cache').stat().st_mode&0o777,0o700)
        service.start()
        for server in service.servers:
            status,_,raw=request(server,'GET','/api/study/overview')
            self.assertEqual(status,200);self.assertEqual(json.loads(raw)['backend'],'fixture')
        service.close();service.close()
        self.assertTrue(all(not t.is_alive() for t in service.threads))
        self.assertTrue(all(s.socket.fileno()==-1 for s in service.servers))
        self.assertEqual(self.events[-1],{'state':'stopped','drained':True})
        self.assertNotIn('DO_NOT_LOG',repr(self.events))

    def test_legacy_registry_requires_explicit_compatibility(self):
        module=self.module()
        with self.assertRaises(module.ServiceError):
            module.build_service(module.load_config(self.path),dependencies=self.dependencies())
        self.assertEqual(self.storage_calls,[])
        service=self.build(allow_legacy_catalog=True)
        self.assertEqual(len(service.servers),2)

    def test_v2_launcher_passes_authenticated_routes_to_http_and_audio_in_same_transaction(self):
        from dataclasses import replace
        from tests import test_study_preview_routes as route_fixture
        fixture=route_fixture.PreviewRoutesTests('runTest');fixture.setUp();self.addCleanup(fixture.doCleanups)
        books,routes=fixture.load()
        self.registry.write_text(json.dumps(fixture.f.registry))
        manifest=self.root/'mounts.json'
        manifest.write_text(json.dumps({'schema':'preview.static-mounts.v1','mounts':[
            {'url_mount':prefix,**{key:str(path) for key,path in paths.items()}}
            for prefix,paths in fixture.mounts.mounts.items()]}))
        self.value['static_mounts_path']=str(manifest);self.write_config()
        deps=self.dependencies();calls=[]
        def projected(db,*,document_root,registry,static_mounts):
            self.assertTrue(db.in_transaction)
            self.assertEqual(registry,fixture.f.registry)
            self.assertEqual(static_mounts.mounts,routes.mounts)
            calls.append('projection');return books,routes
        def audio(*args,**kwargs):
            self.assertIs(kwargs['static_mounts'],routes);calls.append('audio');return None
        deps=replace(deps,load_books_and_routes=projected,audio_factory=audio)
        running=self.build(dependencies=deps,allow_legacy_catalog=False);running.start()
        self.assertEqual(calls,['projection','audio']);self.assertEqual(self.loaded,[])
        for server in running.servers:
            self.assertIs(server.RequestHandlerClass.keywords['static_mounts'],routes)
            self.assertEqual(request(server,'GET',fixture.old)[2],fixture.wrapper.read_bytes())
        running.close()
        deps=replace(deps,load_books_and_routes=lambda *args,**kwargs:(books,None))
        with self.assertRaises(self.module().ServiceError):
            self.build(dependencies=deps,allow_legacy_catalog=True)

    def test_config_private_paths_cannot_be_public_or_mounted(self):
        module=self.module()
        for key in ('backups_path','audio_cache_path','registry_path'):
            with self.subTest(key=key):
                original=self.value[key];self.value[key]=str(self.public/key);self.write_config()
                with self.assertRaises(module.ServiceError):self.build()
                self.value[key]=original
        self.write_config()
        public_config=self.public/'service.json';public_config.write_bytes(self.path.read_bytes());public_config.chmod(0o600)
        with self.assertRaises(module.ServiceError):module.build_service(module.load_config(public_config),dependencies=self.dependencies())
        from tests.test_study_http import mount_fixture
        mounts,_,export=mount_fixture(self.root)
        manifest=self.root/'mounts.json'
        manifest.write_text(json.dumps({'schema':'preview.static-mounts.v1','mounts':[
            {'url_mount':prefix,**{key:str(path) for key,path in paths.items()}}
            for prefix,paths in mounts.mounts.items()]}))
        self.value['static_mounts_path']=str(manifest)
        self.value['audio_cache_path']=str(export/'private-cache');self.write_config()
        with self.assertRaises(module.ServiceError):self.build()

    def test_invalid_config_does_not_echo_credentials_or_fall_back_to_environment(self):
        module=self.module()
        self.value['port']=True;self.write_config()
        with patch.dict(os.environ,ANKI_STUDY_DSN='password=ENV_SECRET'):
            with self.assertRaises(module.ServiceError) as caught:module.load_config(self.path)
        self.assertNotIn('DO_NOT_LOG',str(caught.exception));self.assertNotIn('ENV_SECRET',str(caught.exception))
        self.value['port']=0;self.write_config();self.path.chmod(0o644)
        with self.assertRaises(module.ServiceError):module.load_config(self.path)
        self.path.chmod(0o600)
        self.value['postgres']={'schema':'fixture_catalog'};self.write_config()
        with self.assertRaises(module.ServiceError):module.load_config(self.path)

    def test_existing_private_directory_permissions_are_not_rewritten(self):
        module=self.module()
        (self.root/'backups').mkdir(mode=0o755)
        before=(self.root/'backups').stat().st_mode
        with self.assertRaises(module.ServiceError):self.build()
        self.assertEqual((self.root/'backups').stat().st_mode,before)

    def test_second_bind_failure_closes_first_socket(self):
        module=self.module();opened=[]
        from anki_pipeline.study_http import create_server
        def bind(*args,**kwargs):
            if opened:raise OSError('second bind failed password=DO_NOT_LOG')
            server=create_server(*args,**kwargs);opened.append(server);return server
        with self.assertRaises(module.ServiceError) as caught:self.build(dependencies=self.dependencies(server_factory=bind))
        self.assertNotIn('DO_NOT_LOG',str(caught.exception))
        self.assertEqual(opened[0].socket.fileno(),-1)

    def test_close_waits_for_inflight_post_to_finish_before_stopped(self):
        entered,release,saved=threading.Event(),threading.Event(),threading.Event()
        class SlowStore:
            db_path=None
            def __init__(inner,db_path,books,*,storage):inner.books=books
            def dispatch(inner,*args):
                entered.set()
                if not release.wait(3):raise RuntimeError('fixture did not release write')
                saved.set();return {'saved':True}
        service=self.build(dependencies=self.dependencies(store=SlowStore));service.start()
        results=[]
        client=threading.Thread(target=lambda:results.append(request(service.servers[0],'POST','/api/study/settings',
            body=b'{}',headers={'Content-Type':'application/json','X-Study-Request':'1'})))
        client.start();self.addCleanup(client.join,4)
        self.assertTrue(entered.wait(2))
        closing=threading.Thread(target=service.close);closing.start()
        try:
            deadline=time.monotonic()+2
            while not any(e['state']=='stopping' for e in self.events) and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(closing.is_alive())
            self.assertFalse(saved.is_set())
            self.assertFalse(any(e['state']=='stopped' for e in self.events))
        finally:release.set()
        closing.join(3);client.join(3)
        self.assertFalse(closing.is_alive());self.assertTrue(saved.is_set())
        self.assertEqual(results[0][0],200)
        self.assertTrue(self.events[-1]['drained'])

    def test_import_has_no_application_file_connection_or_listener_io(self):
        module=self.module()
        with patch.object(Path,'read_text',side_effect=AssertionError('import file read')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('import file read')), \
             patch.object(Path,'mkdir',side_effect=AssertionError('import mkdir')), \
             patch('psycopg.connect',side_effect=AssertionError('import database connection')), \
             patch.object(socket,'socket',side_effect=AssertionError('import listener')):
            importlib.reload(module)

    def test_logger_failure_cannot_prevent_close_or_leave_accept_workers(self):
        module=self.module()
        service=self.build()
        service.start()
        def broken(_):raise RuntimeError('password=DO_NOT_LOG')
        service.log=broken
        try:service.close()
        finally:
            service.log=self.events.append
            service.close()
        self.assertTrue(all(not worker.is_alive() for worker in service.threads))
        self.assertTrue(all(server.socket.fileno()==-1 for server in service.servers))

    def test_main_failure_status_never_contains_exception_dsn_or_traceback(self):
        module=self.module();out,err=io.StringIO(),io.StringIO()
        with patch.object(module,'run',side_effect=RuntimeError('postgres password=DO_NOT_LOG')), \
             patch('sys.stdout',out),patch('sys.stderr',err):
            result=module.main(['--config',str(self.path)])
        self.assertEqual(result,1)
        self.assertEqual(json.loads(err.getvalue()),{'state':'failed','error':'study_service_failed'})
        self.assertEqual(out.getvalue(),'')
        self.assertNotIn('DO_NOT_LOG',err.getvalue())

    def test_signal_handlers_are_restored_and_early_stop_closes_unstarted_listeners(self):
        module=self.module();seen=[]
        before={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
        event=threading.Event()
        with module._signals() as requested:
            for number in before:
                handler=signal.getsignal(number)
                self.assertNotEqual(handler,before[number]);handler(number,None)
                self.assertTrue(requested())
                self.assertFalse(event.is_set())
        self.assertEqual({number:signal.getsignal(number) for number in before},before)
        event.set()
        def factory(*args,**kwargs):
            from anki_pipeline.study_http import create_server
            server=create_server(*args,**kwargs);seen.append(server);return server
        module.run(module.load_config(self.path),dependencies=self.dependencies(server_factory=factory),
                   log=self.events.append,stop_event=event,handle_signals=False,allow_legacy_catalog=True)
        self.assertEqual(len(seen),2);self.assertTrue(all(server.socket.fileno()==-1 for server in seen))
        self.assertFalse(any(row['state']=='ready' for row in self.events))
        self.assertTrue(self.events[-1]['drained'])

    def test_sigint_and_sigterm_drain_actual_child_request_before_exit(self):
        import queue
        for number in (signal.SIGINT,signal.SIGTERM):
            with self.subTest(signal=number):
                folder=self.root/str(int(number));folder.mkdir()
                child=subprocess.Popen([sys.executable,'-B','-c',CHILD,str(self.path),str(folder)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                lines=queue.Queue()
                reader=threading.Thread(target=lambda:[lines.put(line) for line in child.stdout],daemon=True)
                reader.start();client=None;result=[]
                try:
                    ready=json.loads(lines.get(timeout=3))
                    self.assertEqual(ready['state'],'ready');port=ready['port']
                    def write():
                        import http.client
                        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                        try:
                            connection.request('POST','/api/study/settings',body=b'{}',
                                headers={'Content-Type':'application/json','X-Study-Request':'1'})
                            response=connection.getresponse();result.append((response.status,response.read()))
                        finally:connection.close()
                    client=threading.Thread(target=write);client.start()
                    deadline=time.monotonic()+3
                    while not (folder/'entered').exists() and time.monotonic()<deadline:time.sleep(.01)
                    self.assertTrue((folder/'entered').exists())
                    child.send_signal(number)
                    self.assertEqual(json.loads(lines.get(timeout=3))['state'],'stopping')
                    self.assertIsNone(child.poll())
                    self.assertFalse((folder/'saved').exists())
                    (folder/'release').touch()
                    self.assertEqual(child.wait(timeout=3),0)
                    self.assertEqual(json.loads(lines.get(timeout=3)),{'state':'stopped','drained':True})
                    client.join(3);self.assertEqual(result,[(200,b'{"saved": true}')])
                    self.assertTrue((folder/'saved').exists())
                    reader.join(3)
                    self.assertNotIn('DO_NOT_LOG',child.stderr.read())
                finally:
                    (folder/'release').touch()
                    if child.poll() is None:child.kill();child.wait(timeout=3)
                    if client is not None:client.join(5)
                    reader.join(3);child.stdout.close();child.stderr.close()


    def test_partial_accept_thread_start_failure_closes_both_listeners(self):
        module=self.module();service=self.build();original=threading.Thread.start;calls=0
        def start(worker):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('password=DO_NOT_LOG')
            return original(worker)
        with patch.object(threading.Thread,'start',side_effect=start,autospec=True):
            with self.assertRaises(module.ServiceError) as caught:service.start()
        self.assertNotIn('DO_NOT_LOG',str(caught.exception))
        self.assertTrue(all(not worker.is_alive() for worker in service.threads))
        self.assertTrue(all(server.socket.fileno()==-1 for server in service.servers))
        self.assertFalse(any(row['state']=='ready' for row in self.events))


CHILD = r'''
from contextlib import contextmanager
from pathlib import Path
import sys,time
from anki_pipeline import study_service as service
path,folder=Path(sys.argv[1]),Path(sys.argv[2])
class DB:
 @contextmanager
 def transaction(self):yield self
 def execute(self,*args):pass
@contextmanager
def connect(*args,**kwargs):yield DB()
class Store:
 db_path=None
 def __init__(self,db_path,books,**kwargs):self.books=books
 def dispatch(self,*args):
  (folder/'entered').touch()
  deadline=time.monotonic()+5
  while not (folder/'release').exists():
   if time.monotonic()>deadline:raise RuntimeError('fixture release timeout')
   time.sleep(.01)
  (folder/'saved').touch()
  return {'saved':True}
deps=service.Dependencies(connect=connect,load_books=lambda *args,**kwargs:{'future':{'cards':[]}},
 storage_factory=lambda *args,**kwargs:None,store_factory=Store)
service.run(service.load_config(path),dependencies=deps,allow_legacy_catalog=True)
'''


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class StudyServicePostgresTests(unittest.TestCase):
    def test_default_provider_store_http_stack_uses_migrated_state_without_seed(self):
        import hashlib
        from anki_pipeline import study_service as service
        from anki_pipeline import study_progress as progress
        from anki_pipeline import study_progress_pg as pg
        from anki_pipeline import study_catalog as catalog
        from tests.test_study_progress_import import ProgressImportTests
        fixture=ProgressImportTests('test_lossless_all_rows_inactive_aliases_and_same_seal_idempotence')
        self.addCleanup(fixture.doCleanups);fixture.setUp()
        public=fixture.root/'service-public';public.mkdir()
        legacy=fixture.legacy_catalog
        legacy.update(deckName='Any subject',counts={'cards':1})
        legacy['cards'][0].update(word='unchanged label',unit='Unit 01',lesson='Lesson 01',position='1',
                                  previewUrl='cards/example.html')
        raw=catalog.canonical(legacy).encode()
        fixture.catalog_path=public/'catalog.json';fixture.catalog_path.write_bytes(raw)
        fixture.aliases['books'][0]['catalog'].update(path=str(fixture.catalog_path),
            sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        fixture.write_aliases()
        (public/'preview-library.html').write_text('<div data-catalog-url="catalog.json"></div>')
        (public/'cards').mkdir();(public/'cards'/'example.html').write_text('<body>source unchanged</body>')
        with fixture.transaction() as db:fixture.run_import(db)
        before=fixture.state()
        registry=fixture.root/'service-registry.json'
        registry.write_text(catalog.canonical({'schema':'study-service-catalog.v1','books':[
            {'id':'liu','previewPath':'/preview-library.html','unitLessonSeparator':' ➫ '}]}))
        path=fixture.root/'service.json'
        path.write_text(catalog.canonical({'schema':'study-service.v1',
            'postgres':{'dsn':fixture.target.dsn,'schema':fixture.target.schema},
            'document_root':str(public),'registry_path':str(registry),'static_mounts_path':None,
            'backups_path':str(fixture.root/'service-backups'),'audio_cache_path':str(fixture.root/'service-cache'),'port':0}))
        path.chmod(0o600);events=[]
        with patch.object(progress.StudyStore,'initialize_catalog',side_effect=AssertionError('startup seeded cards')), \
             patch.object(progress.StudyStore,'_initialize_rows',side_effect=AssertionError('startup seeded cards')), \
             patch.object(pg.PgStudyStorage,'initialize',side_effect=AssertionError('startup initialized storage')), \
             patch.object(pg,'initialize_connection',side_effect=AssertionError('startup initialized storage')):
            running=service.build_service(service.load_config(path),log=events.append,allow_legacy_catalog=True)
            self.addCleanup(running.close)
            try:
                running.start()
                for server in running.servers:
                    status,_,payload=request(server,'GET','/api/study/overview')
                    self.assertEqual(status,200)
                    value=json.loads(payload)
                    self.assertEqual(value['algorithm'],'FSRS')
                    self.assertEqual([(b['id'],b['cardCount']) for b in value['books']],[('liu',1)])
            finally:running.close()
        self.assertEqual(fixture.state(),before)
        self.assertEqual(events[-1],{'state':'stopped','drained':True})
