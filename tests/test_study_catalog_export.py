import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch
import psycopg
import genanki
from psycopg import sql
from anki_pipeline import study_catalog as c
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_export import export_book,verify_catalog
from anki_pipeline import study_catalog_presentation as presentation
from anki_pipeline.study_catalog_books import create_book
from tests import test_study_catalog_import as fixtures


class RuntimeReferenceTests(unittest.TestCase):
    def test_only_exact_local_basenames_are_rewritten(self):
        aliases={'a.js':'alias-a.js','two words.js':'alias-space.js','words.js':'alias-word.js','_dep.js':'alias-dep.js'}
        raw='"data.js" "a.js" "two words.js" "./a.js" "%5Fdep.js?x=1" "https://host/a.js"'
        self.assertEqual(presentation.rewrite_references(raw,aliases),
                         '"data.js" "alias-a.js" "alias-space.js" "./alias-a.js" "alias-dep.js?x=1" "https://host/a.js"')

    def test_dynamic_and_filename_dependent_loads_are_not_silently_rewritten(self):
        for text in ('import(name)','import("./"+name)','script.src=name;',
                     'var src="_"+name+".js";','var src=document.currentScript.src;',
                     '@import url(var(--theme));',r'var src="\u005fdep.js";'):
            with self.subTest(text=text):self.assertTrue(presentation._dynamic_reference(text))
        self.assertFalse(presentation._dynamic_reference('import("_dep.js"); @import "_dep.css";'))


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires explicit isolated PostgreSQL test connection')
class CatalogExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
        self.originals={}
        for book in ['one','two']:
            path=fixtures.CatalogImportTests.package(self,book)
            with zipfile.ZipFile(path) as z:self.originals[book]={name:z.read(name) for name in z.namelist()}
            import_package(self.target,path,book_id=book,title=book,edition=2027)
            path.unlink()  # Generation must now depend only on PostgreSQL.

    def tearDown(self):
        with psycopg.connect(self.target.dsn,autocommit=True) as db:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def runtime_package(self,*,dynamic=False):
        contents={
            '_dep.js':'window.dependency="A";',
            '_parent.js':'var dependency="_dep.js",cycle="_cycle.js",unrelated="data_dep.js";',
            '_cycle.js':'var parent="_parent.js";',
            '_unrelated.js':'window.unrelated="untouched";',
            '_dep.css':'.card { color: #123456; }',
            '_parent.css':'@import "_dep.css";',
        }
        if dynamic:contents['_parent.js']='var dependency="_"+name+".js";'
        model=genanki.Model(3456,'Shared runtime test',fields=[{'name':'Word'},{'name':'Meaning'}],
            templates=[{'name':'Card','qfmt':'<link rel="stylesheet" href="_parent.css">{{Word}}<script src="_parent.js"></script>',
                        'afmt':'{{FrontSide}} {{Meaning}}'}])
        deck=genanki.Deck(5432,'Runtime book::Unit 01')
        deck.add_note(genanki.Note(model=model,fields=['runtime','<script src="_dep.js"></script>'],guid=genanki.guid_for('runtime-test')))
        files=[]
        for name,text in contents.items():
            path=self.root/name;path.write_text(text);files.append(str(path))
        source=self.root/'runtime-source.apkg';package=genanki.Package(deck);package.media_files=files;package.write_to_file(str(source))
        with zipfile.ZipFile(source) as archive:originals={name:archive.read(name) for name in archive.namelist()}
        import_package(self.target,source,book_id='runtime',title='Runtime test',edition=2027)
        presentation.install(self.target)
        with c.connect(self.target,readonly=True) as db:
            components=presentation.registry(db)['books']['runtime']['resources']
        source.unlink()
        return contents,components,originals

    def test_standalone_apkg_export_retains_all_original_member_bytes(self):
        presentation.install(self.target)
        for book in ['one','two']:
            path=self.root/f'{book}-generated.apkg';report=export_book(self.target,book,path)
            self.assertEqual(report['notes'],2);self.assertEqual(report['shared_field_changes'],0)
            with zipfile.ZipFile(path) as z:
                self.assertEqual(set(z.namelist()),set(self.originals[book]))
                for name,data in self.originals[book].items():self.assertEqual(z.read(name),data)
            with self.assertRaises(ValueError):export_book(self.target,book,path)

    def test_shared_component_edit_reaches_apkg_and_web_of_both_books(self):
        with c.connect(self.target,readonly=True) as db:
            key=db.execute("select c.id from components c join words w on w.id=c.word_id where w.surface='train' and c.name='SimpleDefinition'").fetchone()[0]
        c.edit_component(self.target,key,'统一修订',expected='训练',reason='测试共用修订',backups=self.root/'backups')
        for book in ['one','two']:
            apkg=self.root/f'{book}-edited.apkg';export_book(self.target,book,apkg)
            with zipfile.ZipFile(apkg) as z:
                db=sqlite3.connect(':memory:');db.deserialize(z.read('collection.anki2'))
                fields=db.execute("select flds from notes where sfld='train'").fetchone()[0].split('\x1f')
                self.assertEqual(fields[3],'统一修订');db.close()
            folder=self.root/f'{book}-web';report=export_book(self.target,book,folder,format='web')
            catalog=json.loads((folder/'catalog.json').read_text());card=next(x for x in catalog['cards'] if x['word']=='train')
            self.assertEqual(report['projection'],'project_book/project_note')
            page=(folder/card['url']).read_text()
            self.assertIn('统一修订',page);self.assertIn('original examples',page)
            self.assertEqual((folder/'media/recording.mp3').read_bytes(),b'original immutable media bytes')

    def test_incomplete_source_stops_both_formats_before_output(self):
        with c.connect(self.target) as db:db.execute("update sources set status='building' where label='one'")
        for fmt in ['apkg','web']:
            dest=self.root/f'incomplete-{fmt}'
            with self.assertRaises(ValueError):export_book(self.target,'one',dest,format=fmt)
            self.assertFalse(dest.exists())

    def test_deep_object_validation_runs_on_real_postgresql(self):
        result=verify_catalog(self.target,deep=True)
        self.assertTrue(result['ok']);self.assertGreater(result['objects_deep_verified'],0)

    def test_one_template_revision_reaches_both_hosts_and_both_books(self):
        presentation.install(self.target)
        with c.connect(self.target,readonly=True) as db:
            bindings=presentation.registry(db)['books']
            component=bindings['one']['models']['1234']['qfmt:0']
            self.assertEqual(component,bindings['two']['models']['1234']['qfmt:0'])
        c.edit_component(self.target,component,'<main data-shared-template="v2">{{Word}}</main>',
                         expected='{{Word}}',reason='公共模板修订验证',backups=self.root/'backups')
        presentation.install(self.target)  # Idempotence must not reset v2.
        for book in ['one','two']:
            path=self.root/(book+'-template.apkg');export_book(self.target,book,path)
            with zipfile.ZipFile(path) as z:
                native=sqlite3.connect(':memory:')
                try:
                    native.deserialize(z.read('collection.anki2'))
                    models=json.loads(native.execute('select models from col').fetchone()[0])
                    self.assertIn('data-shared-template',models['1234']['tmpls'][0]['qfmt'])
                    self.assertEqual(native.execute('select count(*) from cards').fetchone()[0],2)
                finally:native.close()
            folder=self.root/(book+'-template-web');export_book(self.target,book,folder,format='web')
            self.assertTrue((folder/'COMPLETE.json').is_file())
            catalog=json.loads((folder/'catalog.json').read_text())
            page=(folder/catalog['cards'][0]['url']).read_text()
            self.assertIn('data-shared-template',page)
            self.assertIn('side.srcdoc=sides[answer?1:0]',page)

    def test_same_second_template_and_css_revisions_and_revert_advance_model_mods(self):
        presentation.install(self.target)
        create_book(self.target,{
            'schema':'study-book-map.v1','id':'future','title':'Mapped book','edition':2028,
            'units':[{'name':'Unit 01','words':[{'word':'train','from_book':'one'}]}]})
        with c.connect(self.target,readonly=True) as db:
            bindings=presentation.registry(db)['books']
            parts=bindings['one']['models']['1234']
            mapped_mid=next(iter(bindings['future']['models']))
            self.assertEqual(parts,bindings['future']['models'][mapped_mid])
        expected={'qfmt:0':'{{Word}}','css':''}
        previous={book:None for book in ('one','two','future')}
        with patch('anki_pipeline.study_catalog_anki.time.time',return_value=1_800_000_000):
            for step,(part,text) in enumerate((
                    ('qfmt:0','<main>{{Word}}</main>'),
                    ('qfmt:0','<article>{{Word}}</article>'),
                    ('qfmt:0','{{Word}}'),
                    ('css','.card { color: #123456; }'),
                    ('css','.card { color: #654321; }'),
                    ('css',''))):
                c.edit_component(self.target,parts[part],text,expected=expected[part],
                                 reason='持久模型版本验证',backups=self.root/'backups')
                expected[part]=text
                for book in previous:
                    path=self.root/f'{book}-model-revision-{step}.apkg'
                    export_book(self.target,book,path)
                    with zipfile.ZipFile(path) as archive:
                        native=sqlite3.connect(':memory:')
                        try:
                            native.deserialize(archive.read('collection.anki2'))
                            models=json.loads(native.execute('select models from col').fetchone()[0])
                            model=models[mapped_mid if book=='future' else '1234']
                            self.assertEqual(model['tmpls'][0]['qfmt'],expected['qfmt:0'])
                            self.assertEqual(model['css'],expected['css'])
                            if previous[book] is not None:
                                self.assertGreater(model['mod'],previous[book])
                            previous[book]=model['mod']
                        finally:native.close()

    def test_mapping_after_template_revert_gets_one_committed_model_version(self):
        presentation.install(self.target)
        with c.connect(self.target,readonly=True) as db:
            component=presentation.registry(db)['books']['one']['models']['1234']['qfmt:0']
        with patch('anki_pipeline.study_catalog_anki.time.time',return_value=1_800_000_000):
            c.edit_component(self.target,component,'<main>{{Word}}</main>',expected='{{Word}}',
                             reason='映射前修订',backups=self.root/'backups')
            c.edit_component(self.target,component,'{{Word}}',expected='<main>{{Word}}</main>',
                             reason='映射前恢复',backups=self.root/'backups')
            create_book(self.target,{
                'schema':'study-book-map.v1','id':'later','title':'Later book','edition':2028,
                'units':[{'name':'Unit 01','words':[{'word':'train','from_book':'one'}]}]})
        versions=[]
        for index in range(2):
            presentation.install(self.target)
            path=self.root/f'later-stable-model-{index}.apkg';export_book(self.target,'later',path)
            with zipfile.ZipFile(path) as archive:
                native=sqlite3.connect(':memory:')
                try:
                    native.deserialize(archive.read('collection.anki2'))
                    model=next(iter(json.loads(native.execute('select models from col').fetchone()[0]).values()))
                    self.assertEqual(model['tmpls'][0]['qfmt'],'{{Word}}')
                    versions.append(model['mod'])
                finally:native.close()
        self.assertEqual(versions,[1_800_000_000,1_800_000_000])

    def test_runtime_aliases_cover_reverse_dependencies_cycles_and_both_hosts(self):
        contents,components,originals=self.runtime_package()
        baseline=self.root/'runtime-baseline.apkg';export_book(self.target,'runtime',baseline)
        with zipfile.ZipFile(baseline) as archive:
            self.assertEqual(set(archive.namelist()),set(originals))
            for name,raw in originals.items():self.assertEqual(archive.read(name),raw)
        c.edit_component(self.target,components['_dep.js'],'window.dependency="B";',
                         expected=contents['_dep.js'],reason='依赖版本验证',backups=self.root/'backups')
        from anki_pipeline.study_catalog_export import project_book
        with c.connect(self.target,readonly=True) as db:
            runtime=project_book(db,'runtime')['runtime']
        aliases=runtime['aliases']
        self.assertEqual(set(aliases),{'_dep.js','_parent.js','_cycle.js'})
        self.assertIn(aliases['_dep.js'],runtime['generated'][aliases['_parent.js']].decode())
        self.assertIn(aliases['_cycle.js'],runtime['generated'][aliases['_parent.js']].decode())
        self.assertIn(aliases['_parent.js'],runtime['generated'][aliases['_cycle.js']].decode())
        self.assertIn('data_dep.js',runtime['generated'][aliases['_parent.js']].decode())
        path=self.root/'runtime-revised.apkg';export_book(self.target,'runtime',path)
        with zipfile.ZipFile(path) as archive:
            media=json.loads(archive.read('media'));by_name={name:member for member,name in media.items()}
            original_media=json.loads(originals['media'])
            for member,name in original_media.items():self.assertEqual(archive.read(by_name[name]),originals[member])
            for alias,raw in runtime['generated'].items():self.assertEqual(archive.read(by_name[alias]),raw)
            native=sqlite3.connect(':memory:')
            try:
                native.deserialize(archive.read('collection.anki2'))
                model=next(iter(json.loads(native.execute('select models from col').fetchone()[0]).values()))
                self.assertIn(aliases['_parent.js'],model['tmpls'][0]['qfmt'])
                self.assertIn(aliases['_dep.js'],native.execute('select flds from notes').fetchone()[0])
            finally:native.close()
        folder=self.root/'runtime-web';export_book(self.target,'runtime',folder,format='web')
        for alias,raw in runtime['generated'].items():self.assertEqual((folder/'media'/alias).read_bytes(),raw)
        c.edit_component(self.target,components['_dep.js'],contents['_dep.js'],expected='window.dependency="B";',
                         reason='依赖回退验证',backups=self.root/'backups')
        path=self.root/'runtime-reverted.apkg';export_book(self.target,'runtime',path)
        with zipfile.ZipFile(path) as archive:self.assertEqual(archive.read('media'),originals['media'])
        c.edit_component(self.target,components['_dep.css'],'.card { color: #654321; }',
                         expected=contents['_dep.css'],reason='CSS依赖版本验证',backups=self.root/'backups')
        with c.connect(self.target,readonly=True) as db:
            css_runtime=project_book(db,'runtime')['runtime']
        self.assertEqual(set(css_runtime['aliases']),{'_dep.css','_parent.css'})
        self.assertIn(css_runtime['aliases']['_dep.css'],css_runtime['generated'][css_runtime['aliases']['_parent.css']].decode())

    def test_dynamic_runtime_dependencies_are_rejected_before_either_output(self):
        contents,components,_=self.runtime_package(dynamic=True)
        c.edit_component(self.target,components['_dep.js'],'window.dependency="B";',
                         expected=contents['_dep.js'],reason='动态依赖保护验证',backups=self.root/'backups')
        for fmt in ('apkg','web'):
            path=self.root/('runtime-dynamic-'+fmt)
            with self.assertRaisesRegex(ValueError,'dynamic shared runtime reference'):
                export_book(self.target,'runtime',path,format=fmt)
            self.assertFalse(path.exists())

    def test_same_second_runtime_and_field_revisions_share_a_monotonic_note_version(self):
        contents,components,_=self.runtime_package()
        with c.connect(self.target,readonly=True) as db:
            field=db.execute("select component_id from note_fields where book_id='runtime' and name='Meaning'").fetchone()[0]
        original='<script src="_dep.js"></script>'
        edits=[(components['_dep.js'],contents['_dep.js'],'window.dependency="B";'),
               (field,original,original+'<p>updated</p>'),
               (components['_dep.js'],'window.dependency="B";','window.dependency="C";'),
               (field,original+'<p>updated</p>',original),
               (components['_dep.js'],'window.dependency="C";',contents['_dep.js'])]
        mods=[]
        with patch('anki_pipeline.study_catalog_anki.time.time',return_value=1_800_000_000):
            for index,(key,old,text) in enumerate(edits):
                c.edit_component(self.target,key,text,expected=old,reason='混合版本验证',backups=self.root/'backups')
                path=self.root/f'mixed-version-{index}.apkg';export_book(self.target,'runtime',path)
                with zipfile.ZipFile(path) as archive:
                    native=sqlite3.connect(':memory:')
                    try:
                        native.deserialize(archive.read('collection.anki2'))
                        mods.append(native.execute('select mod from notes').fetchone()[0])
                    finally:native.close()
        self.assertGreater(mods[0],1_800_000_000)
        self.assertTrue(all(a<b for a,b in zip(mods,mods[1:])),mods)


if __name__=='__main__':unittest.main()
