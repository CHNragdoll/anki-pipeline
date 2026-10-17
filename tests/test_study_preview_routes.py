"""Small authenticated catalogs; no live PG or source card HTML is needed."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog as catalog
from anki_pipeline import study_service_catalog as provider
from anki_pipeline.preview_static_mounts import MountDenied, Resource, StaticMounts
from tests import test_study_service_catalog as catalog_fixture
from tests.test_study_http import request, serving


class PreviewRoutesTests(unittest.TestCase):
    def setUp(self):
        self.f = catalog_fixture.ServiceCatalogTests('runTest'); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.quiet = patch('anki_pipeline.study_http.StudyHandler.log_message', return_value=None)
        self.quiet.start();self.addCleanup(self.quiet.stop)
        self.f.add_book('alpha', 'canonical-a', entry='old/entry.html')
        self.f.seal()
        self.export = self.f.root.parent / 'master-fixture-web-v3'
        (self.export/'cards').mkdir(parents=True); (self.export/'media').mkdir()
        self.filename = 'b'*64+'.html'
        self.wrapper = self.export/'cards'/self.filename
        self.wrapper.write_bytes(b'<body>current PG projection</body>')
        (self.export/'media'/'current.js').write_bytes(b'current source media')
        self.prefix = '/study-catalog-20261017/master-fixture-web-v3/'
        self.catalog = {'schema':'shared-book-web.v1','book_id':'canonical-a',
            'title':'Any subject','scope':{},'catalog_revision':11,'cards':[
                {'id':'a'*64,'guid':'guid-alpha','native_id':201,'template_ordinal':0,
                 'word':'label','label':'label','unit':'unit','ordinal':0,
                 'template':'Vocabulary','url':'cards/'+self.filename}]}
        self.f.registry['schema'] = 'study-service-catalog.v2'
        self.f.registry['books'][0]['projection'] = {'url_mount':self.prefix}
        self.pin()
        self.mounts = StaticMounts([{'url_mount':self.prefix, 'export':str(self.export),
            'cards':str(self.export/'cards'),'media':str(self.export/'media'),
            'catalog':str(self.export/'catalog.json')}])
        self.old = '/old/web-preview/fixture/cards/'+'a'*64+'.html'
        self.media = '/old/web-preview/fixture/media/'

    def pin(self):
        raw = catalog.canonical(self.catalog).encode()
        (self.export/'catalog.json').write_bytes(raw)
        self.f.registry['books'][0]['projection'].update(
            catalog_sha256=hashlib.sha256(raw).hexdigest(), catalog_bytes=len(raw))

    def load(self):
        with patch.object(catalog,'get_json',side_effect=lambda db,key:self.f.db.objects[key]):
            return provider.load_books_and_routes(self.f.db,document_root=self.f.root,
                registry=self.f.registry,static_mounts=self.mounts)

    def rejects(self):
        with self.assertRaises(ValueError):self.load()

    def test_authenticated_routes_keep_books_and_do_not_write(self):
        before = {p:p.read_bytes() for p in self.f.root.parent.rglob('*') if p.is_file()}
        with patch.object(Path,'write_bytes',side_effect=AssertionError('route construction wrote')), \
             patch.object(Path,'write_text',side_effect=AssertionError('route construction wrote')):
            books,routes = self.load()
        self.assertIsInstance(routes,StaticMounts)
        self.assertEqual(books['alpha']['cards'][0]['previewUrl'],self.old)
        self.assertEqual(books['alpha']['cards'][0]['id'],'a'*64)
        self.assertEqual(routes.resolve(self.old).path,self.wrapper.resolve())
        self.assertEqual(routes.resolve(self.media+'current.js').path,(self.export/'media/current.js').resolve())
        self.assertIsNone(routes.resolve('/old/catalog.json'))
        self.assertEqual(before,{p:p.read_bytes() for p in self.f.root.parent.rglob('*') if p.is_file()})
        self.assertTrue(all(sql.startswith('select ') for sql,_ in self.f.db.calls))
        # The complete v2 route construction reused the one authenticated
        # receipt read; it did not reopen or reauthenticate another PG session.
        self.assertEqual(sum(sql=='select key,value from metadata where key=any(%s)'
                             for sql,_ in self.f.db.calls),1)

    def test_v2_load_books_preserves_exact_shape_while_validating_routes(self):
        books,_=self.load()
        with patch.object(catalog,'get_json',side_effect=lambda db,key:self.f.db.objects[key]):
            actual=provider.load_books(self.f.db,document_root=self.f.root,
                registry=self.f.registry,static_mounts=self.mounts)
        self.assertEqual(actual,books)

    def test_projection_catalog_replacement_after_descriptor_open_is_rejected(self):
        original=Resource.open;path=(self.export/'catalog.json').resolve()
        def replaced(resource):
            stream,info=original(resource)
            if resource.path==path:
                replacement=path.with_suffix('.new');replacement.write_bytes(path.read_bytes())
                replacement.replace(path)
            return stream,info
        with patch.object(Resource,'open',replaced):self.rejects()

    def test_pin_size_changed_catalog_and_stale_revision_rejected(self):
        projection=self.f.registry['books'][0]['projection']; valid=deepcopy(projection)
        projection['catalog_sha256']='0'*64;self.rejects();projection.update(valid)
        projection['catalog_bytes']+=1;self.rejects();projection.update(valid)
        (self.export/'catalog.json').write_bytes(b'{}');self.rejects();self.pin()
        self.catalog['catalog_revision']=10;self.pin();self.rejects()

    def test_wrong_identity_and_extra_missing_native_members_rejected(self):
        original=deepcopy(self.catalog)
        for key,value in [('id','x'),('guid','wrong'),('native_id',999),('template_ordinal',1)]:
            with self.subTest(key=key):
                self.catalog=deepcopy(original);self.catalog['cards'][0][key]=value;self.pin();self.rejects()
        self.catalog=deepcopy(original);self.catalog['cards']=[];self.pin();self.rejects()
        self.catalog=deepcopy(original)
        self.catalog['cards'].append({**self.catalog['cards'][0],'id':'unapproved','native_id':999,
                                     'url':'cards/'+'c'*64+'.html'})
        self.pin();self.rejects()

    def test_guide_uses_explicit_native_and_guid_exception(self):
        binding=self.f.report['bindings'][0]; target=binding['target']
        binding['evidence']='exact-guide-proof'
        self.f.report['guide_proofs']['alpha']={
            'id':'a'*64, 'guid':target['guid'],'native_id':201,'note_id':101,
            'template_ordinal':0,'evidence':{'kind':'exact-native-and-web-identity-derivation'}}
        self.f.db.natives['canonical-a'][0]=(201,101,target['guid'],301,0,401,None,'guide')
        self.catalog['cards'][0]['id']=target['guid']; self.pin(); self.f.seal()
        books,routes=self.load()
        self.assertEqual(books['alpha']['cards'][0]['id'],'a'*64)
        self.assertEqual(routes.resolve(self.old).path,self.wrapper.resolve())
        self.catalog['cards'][0]['id']='a'*64; self.pin(); self.rejects()

    def test_explicit_supplement_coverage_does_not_add_learning_routes(self):
        target={**self.f.report['bindings'][0]['target'],'native_id':202,'note_id':102,
                'guid':'supplement-guid','unit_id':402}
        self.f.db.natives['canonical-a'].append((202,102,'supplement-guid',301,0,402,'c'*64,'supplemental'))
        self.f.report['books'][0]['native_cards']=2
        self.f.report['excluded_from_legacy_learning_catalog'].append(
            {**target,'id':'c'*64,'kind':'supplemental','word':'supplement','reason':'Explicit exclusion'})
        self.catalog['cards'].append({**self.catalog['cards'][0],'id':'c'*64,'guid':'supplement-guid',
            'native_id':202,'url':'cards/'+'d'*64+'.html'})
        self.pin();self.f.seal();books,routes=self.load()
        self.assertEqual(len(books['alpha']['cards']),1)
        with self.assertRaises(MountDenied):routes.resolve(self.old.replace('a'*64,'c'*64))
        self.catalog['cards'][1]['guid']='another supplement';self.pin();self.rejects()

    def test_paths_are_strict_and_unknown_old_resources_never_fall_back(self):
        original=self.catalog['cards'][0]['url']
        for bad in [original+'?x',original+'#x','cards/%62.html','cards/sub/x.html',
                    'cards/../x.html','https://outside/x.html','/cards/x.html']:
            self.catalog['cards'][0]['url']=bad;self.pin();self.rejects()
        self.catalog['cards'][0]['url']=original;self.pin();_,routes=self.load()
        for bad in [self.old.replace('a'*64,'e'*64),self.media+'../secret',
                    self.media+'%2e%2e/secret',self.media+'%252e%252e/secret',self.media+'x.sqlite3']:
            with self.subTest(path=bad),self.assertRaises(MountDenied):routes.resolve(bad)
        missing=routes.resolve(self.media+'missing.js')
        with self.assertRaises(FileNotFoundError):missing.open()

    def test_formal_mount_must_be_v3_registered_and_alias_retarget_stays_denied(self):
        projection=self.f.registry['books'][0]['projection'];original=projection['url_mount']
        for bad in [original.replace('v3','v2'),'/unregistered/',original+'nested/']:
            projection['url_mount']=bad;self.rejects()
        projection['url_mount']=original;_,routes=self.load()
        moved=self.export/'moved-cards';(self.export/'cards').rename(moved)
        (self.export/'cards').symlink_to(moved,target_is_directory=True)
        with self.assertRaises(MountDenied):routes.resolve(self.old)

    def test_http_get_head_range_and_original_catalog_bytes(self):
        _,routes=self.load()
        class Store:db_path=None
        old_catalog=self.f.root/'old/catalog.json'
        with serving(Store(),self.f.root,static_mounts=routes) as server:
            status,headers,body=request(server,'GET',self.old)
            self.assertEqual((status,body),(200,self.wrapper.read_bytes()))
            status,headers,body=request(server,'HEAD',self.old)
            self.assertEqual((status,body),(200,b''));self.assertEqual(int(headers['Content-Length']),self.wrapper.stat().st_size)
            status,headers,body=request(server,'GET',self.old,headers={'Range':'bytes=6-12'})
            self.assertEqual((status,body),(206,self.wrapper.read_bytes()[6:13]))
            self.assertEqual(request(server,'GET',self.media+'current.js')[2],b'current source media')
            self.assertEqual(request(server,'GET','/old/catalog.json')[2],old_catalog.read_bytes())
            unknown=self.old.replace('a'*64,'f'*64)
            (old_catalog.parent/'web-preview/fixture/cards'/('f'*64+'.html')).write_bytes(b'stale old card')
            self.assertEqual(request(server,'GET',unknown)[0],403)

    def test_audio_filesystem_resolver_reuses_routes_without_claiming_wrapper_parser_support(self):
        from anki_pipeline.study_audio import AudioBalancer, AudioBalanceError
        _,routes=self.load()
        audio=AudioBalancer(self.f.root,self.f.root.parent/'private-audio',[self.old],static_mounts=routes)
        self.assertEqual(audio._file(self.old),self.wrapper.resolve())
        self.assertEqual(audio._file(self.media+'current.js'),(self.export/'media/current.js').resolve())
        with self.assertRaises(AudioBalanceError):audio._file(self.old.replace('a'*64,'f'*64))

    def test_protected_filesystem_aliases_cannot_reach_stale_http_or_audio_files(self):
        from anki_pipeline.study_audio import AudioBalancer, AudioBalanceError
        _,routes=self.load()
        unknown=self.old.replace('a'*64,'f'*64)
        old_file=self.f.root/unknown.lstrip('/');old_file.write_bytes(b'stale old card')
        stale_media=self.f.root/(self.media+'stale.js').lstrip('/')
        stale_media.parent.mkdir();stale_media.write_bytes(b'stale old media')
        paths=[unknown.replace('/old/','/old//',1),unknown.replace('/old/','/OLD/',1),
               unknown.replace('/cards/','/CARDS/',1),unknown.replace('/cards/','/cards//',1),
               self.media.replace('/old/','/old//',1)+'stale.js',
               self.media.replace('/old/','/OLD/',1)+'stale.js',
               self.media.replace('/media/','/MEDIA/',1)+'stale.js',
               self.media+'/'+'stale.js']
        audio=AudioBalancer(self.f.root,self.f.root.parent/'private-audio',[self.old],static_mounts=routes)
        class Store:db_path=None
        with serving(Store(),self.f.root,static_mounts=routes) as server:
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(request(server,'GET',path)[0],403)
                    with self.assertRaises(AudioBalanceError):audio._file(path)
            # Unrelated legacy metadata still follows the original HTTP path.
            self.assertEqual(request(server,'GET','/old/catalog.json')[2],
                             (self.f.root/'old/catalog.json').read_bytes())


if __name__=='__main__':unittest.main()
