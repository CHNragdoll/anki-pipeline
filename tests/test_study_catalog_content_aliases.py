"""Compressed source class maps survive transfer, correction and both hosts."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

import genanki

from anki_pipeline import study_catalog as c, study_catalog_revision as rev
from anki_pipeline.native_example_usage import _Offsets
from anki_pipeline.study_catalog_content import _examples, _native_text
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_catalog_web import card_payload
from tests import test_study_catalog_content as content_tests
from tests.test_study_catalog_native_groups import fixture, live_nodes
from anki_pipeline.study_catalog_native_groups import _current_descendant

ALIASES = {'ec':'example-card', 'et':'example-text', 'ez':'example-translation',
           'sj':'sentence-jump', 'tt':'translate-tag', 'tw':'target-word', 'cc':'card-chunk'}


def compressed(raw):
    def replace(match):
        reverse = {name: alias for alias,name in ALIASES.items()}
        return 'class="' + ' '.join(reverse.get(name,name) for name in match[1].split()) + '"'
    return re.sub(r'class="([^"]+)"',replace,raw)


class CompressedNativeSourceTests(unittest.TestCase):
    def test_unknown_or_partial_source_shell_aliases_are_rejected(self):
        raw,record,_=fixture()
        raw=compressed(raw)
        pairs=[(row,row) for row in record['occurrences']]
        for aliases in (None, {key:value for key,value in ALIASES.items() if key!='ec'},
                        {key:value for key,value in ALIASES.items() if key!='et'},
                        {key:value for key,value in ALIASES.items() if key!='sj'},
                        {key:value for key,value in ALIASES.items() if key!='tw'},
                        {key:value for key,value in ALIASES.items() if key!='cc'}):
            with self.subTest(aliases=aliases):
                with self.assertRaisesRegex(ValueError,'aliases are missing or incomplete'):
                    _examples(raw,pairs,'不得静默留下旧正文',known_occurrences=record['occurrences'],aliases=aliases)
        for key in ('tw','cc'):
            dual=re.sub(r'class="([^"]+)"',lambda match: 'class="'+
                (' '.join([ALIASES[key],*match[1].split()]) if key in match[1].split() else match[1])+'"',raw)
            self.assertNotEqual(dual,raw)
            with self.subTest(dual_alias=key):
                with self.assertRaisesRegex(ValueError,'aliases are missing or incomplete'):
                    _examples(dual,pairs,'双类名也不能漏配置',known_occurrences=record['occurrences'],
                        aliases={name:value for name,value in ALIASES.items() if name!=key})

    def test_compressed_nodes_are_revised_using_exact_source_and_keep_dual_chunk_classes(self):
        raw,record,_ = fixture()
        import hashlib
        pairs=[]
        for row in record['occurrences']:
            after=deepcopy(row);after['english']='Indeed, '+row['english'];after['translation']='的确，'+row['translation']
            after['english_hash']=after['alignment']['englishHash']=hashlib.sha256(after['english'].encode()).hexdigest()
            after['alignment']['translationHash']=hashlib.sha256(after['translation'].encode()).hexdigest()
            after['source_provenance']['reviewedContentHash']=hashlib.sha256(b'new source').hexdigest()
            after['target_range']=[v+8 for v in row['target_range']]
            for part in after['alignment']['alignments']:
                part['en']=[v+8 for v in part['en']]
                part['zh']=[[v+3 for v in span] for span in part['zh']]
            pairs.append((row,after))
        raw=compressed(raw)
        revised=_examples(raw,pairs,'别名仍使用准确原位置',known_occurrences=record['occurrences'],aliases=ALIASES)
        nodes=live_nodes(revised,ALIASES)
        # Every declared token in this source paragraph follows the same new
        # source text, retaining its separate physical target and audit.
        selected=[node for node in nodes if 'Indeed, ' in _native_text(revised,_current_descendant(node,'example-text'),aliases=ALIASES)]
        self.assertEqual(len(selected),3)
        self.assertIn('class="et"',revised)
        self.assertRegex(revised,r'class="[^"]*card-chunk[^"]*\bcc\b')
        self.assertIn('token-1.mp3',revised)
        self.assertIn('历史解释-1',revised)
        self.assertEqual(_native_text(revised,_current_descendant(selected[0],'example-translation'),translation=True,aliases=ALIASES),after['translation'])


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires isolated PostgreSQL test connection')
class CompressedSourceCompositionTests(unittest.TestCase):
    def test_first_source_edit_requires_explicit_aliases_then_reuses_them_and_rejects_conflict(self):
        from anki_pipeline.study_catalog_content import amend_sentence
        from anki_pipeline.study_catalog_query import frequency_report
        fixture=content_tests.SharedContentRevisionTests()
        fixture.setUp();self.addCleanup(fixture.tearDown)
        with c.connect(fixture.target) as db,c.transaction(db):
            for component,key in db.execute("select f.component_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.name='Examples' and f.book_id in ('one','two')"):
                raw=compressed(c.get_object(db,key).decode())
                db.execute('update components set current_id=%s where id=%s',(c.put_object(db,raw.encode()),component))
            self.assertFalse(rev.registry(db))
        request=fixture.sentence_request()
        before=c.logical_digest(fixture.target)
        with self.assertRaisesRegex(ValueError,'aliases are missing or incomplete'):
            amend_sentence(fixture.target,**request)
        self.assertEqual(c.logical_digest(fixture.target),before)
        aliases={'one':ALIASES,'two':ALIASES}
        result=amend_sentence(fixture.target,**request,aliases_by_book=aliases)
        self.assertEqual(len(result['changes']),2)
        self.assertEqual(frequency_report(fixture.target,word='novel')['physical_occurrences'],2)
        with c.connect(fixture.target,readonly=True) as db:
            entries=rev.registry(db)
            for book,card,rid in db.execute('select book_id,source_card_id,record_id from analyses'):
                self.assertEqual(entries[c.identity(book,card)]['native_aliases'],ALIASES)
                fixture.before[book]=c.get_json(db,rid)
        request=fixture.sentence_request()
        before=c.logical_digest(fixture.target)
        with self.assertRaisesRegex(ValueError,'aliases conflict'):
            amend_sentence(fixture.target,**request,aliases_by_book={'one':{**ALIASES,'wrong':'example-card'}})
        self.assertEqual(c.logical_digest(fixture.target),before)
        # First-use configuration is now shared data, reused without any
        # per-book generation branch in the next correction or mapped book.
        amend_sentence(fixture.target,**request)
        fixture.assert_hosts('Indeed, Indeed, ')
        for book in ('one','two','future'):
            examples=fixture.fields(book)['Examples']
            self.assertIn('Indeed, Indeed, ',examples)
            self.assertIn('的确，的确，',examples)
            self.assertIn('class="et"',examples)
            self.assertRegex(examples,r'class="[^"]*card-chunk[^"]*\bcc\b')
            with zipfile.ZipFile(fixture.root/(book+'-content.apkg')) as archive:
                native=sqlite3.connect(':memory:')
                try:
                    native.deserialize(archive.read('collection.anki2'))
                    self.assertIn(examples,native.execute('select flds from notes').fetchone()[0])
                finally:native.close()
            folder=fixture.root/(book+'-content-web')
            card=json.loads((folder/'catalog.json').read_text())['cards'][0]
            page=(folder/card['url']).read_text()
            sides=json.loads(card_payload(page.encode('utf-8')))
            self.assertIn(examples,sides[1])
        self.assertEqual(frequency_report(fixture.target,word='novel')['physical_occurrences'],2)

    def test_transfer_then_source_edit_updates_compressed_apkg_web_and_preserves_media(self):
        from tests import test_study_catalog_ownership as ownership_tests
        original_fixture=ownership_tests.OwnershipRevisionTests
        created=[]
        class CompressedFixture(original_fixture):
            def setUp(self):
                super().setUp();created.append(self)
                with c.connect(self.target) as db,c.transaction(db):
                    for book,component,key in db.execute("select f.book_id,f.component_id,c.current_id from note_fields f join components c on c.id=f.component_id where f.name='Examples' and f.book_id in ('one','two')"):
                        raw=c.get_object(db,key).decode()
                        raw=raw.replace('</li>','<audio src="kept.wav"></audio><details class="sf-source-confirmation-history"><summary>旧审核</summary><p>来源修订别名原审计</p></details></li>')
                        db.execute('update components set current_id=%s where id=%s',(c.put_object(db,compressed(raw).encode()),component))
            def request(self):
                return {**super().request(),'aliases_by_book':{'one':ALIASES,'two':ALIASES}}
        with tempfile.TemporaryDirectory() as directory:
            audio=Path(directory)/'kept.wav'
            with wave.open(str(audio),'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\x00\x00'*16)
            original_package=genanki.Package
            def package_with_audio(*args,**kwargs):
                return original_package(*args,**{**kwargs,'media_files':[str(audio)]})
            case=content_tests.SourceRevisionOwnershipIntegrationTests('test_transfer_then_full_source_revision_preserves_display_page_chain_and_native_jumps')
            try:
                with patch.object(ownership_tests,'OwnershipRevisionTests',CompressedFixture),patch.object(genanki,'Package',package_with_audio):
                    case.test_transfer_then_full_source_revision_preserves_display_page_chain_and_native_jumps()
                owned=created[0]
                for book in ('one','two','future'):
                    with c.connect(owned.target,readonly=True) as db:
                        nid=db.execute('select n.note_id from notes n join words w on w.id=n.word_id where n.book_id=%s and w.surface=%s',(book,'training')).fetchone()[0]
                        note=project_note(db,project_book(db,book),nid)
                        fields=dict(zip(note['field_names'],note['fields']))
                    raw=fields['Examples'];nodes=live_nodes(raw,ALIASES)
                    views=[_native_text(raw,_current_descendant(node,'example-text'),aliases=ALIASES) for node in nodes]
                    self.assertTrue(any(text.startswith('Indeed, Model training') for text in views))
                    self.assertIn('class="et"',raw)
                    self.assertRegex(raw,r'class="[^"]*card-chunk[^"]*\bcc\b')
                    self.assertIn('来源修订别名原审计',raw)
                    self.assertIn('kept.wav',raw)
                    path=owned.root/(book+'-alias.apkg');export_book(owned.target,book,path)
                    with zipfile.ZipFile(path) as archive:
                        mapping=json.loads(archive.read('media'))
                        self.assertEqual(archive.read(next(name for name,target in mapping.items() if target=='kept.wav')),audio.read_bytes())
                        native=sqlite3.connect(':memory:')
                        try:
                            native.deserialize(archive.read('collection.anki2'))
                            target=next(row[0] for row in native.execute('select flds from notes') if row[0].split('\x1f')[0]=='training')
                        finally:native.close()
                        self.assertIn(raw,target)
                    folder=owned.root/(book+'-alias-web');export_book(owned.target,book,folder,format='web')
                    cards=json.loads((folder/'catalog.json').read_text())['cards']
                    page=(folder/next(card['url'] for card in cards if card['word']=='training')).read_text()
                    sides=json.loads(card_payload(page.encode('utf-8')))
                    self.assertIn(raw,sides[1]);self.assertEqual((folder/'media'/'kept.wav').read_bytes(),audio.read_bytes())
            finally:
                case.doCleanups()


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires isolated PostgreSQL test connection')
class ContentHostPreflightRollbackTests(unittest.TestCase):
    def test_final_host_projection_failure_rolls_back_all_shared_content_and_versions(self):
        from anki_pipeline import study_catalog_export as output
        from anki_pipeline.study_catalog_content import amend_sentence
        fixture=content_tests.SharedContentRevisionTests()
        fixture.setUp();self.addCleanup(fixture.tearDown)
        before=c.logical_digest(fixture.target)
        original=output.project_note
        observed=[]
        def reject_new_projection(db,book,note_id,*args,**kwargs):
            source=db.execute('select source_card_id from notes where book_id=%s and note_id=%s',(book['id'],note_id)).fetchone()[0]
            projection,_=rev._projection(db,book,source)
            if projection is not None:
                observed.append(book['id'])
                raise ValueError('final shared host projection cannot render revised content')
            return original(db,book,note_id,*args,**kwargs)
        with patch.object(output,'project_note',side_effect=reject_new_projection):
            with self.assertRaisesRegex(ValueError,'final shared host projection'):
                amend_sentence(fixture.target,**fixture.sentence_request())
        self.assertTrue(observed)
        self.assertEqual(c.logical_digest(fixture.target),before)
