"""Later decisions must retain earlier source/ownership and exclusion edits."""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
import uuid
import zipfile

import genanki
import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c, sense_frequency as sf
from anki_pipeline.study_catalog_content import amend_sentence, _prepare
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_normalize import import_analysis
from anki_pipeline.study_catalog_ownership import transfer_occurrence
from anki_pipeline.study_catalog_query import reviewed_record, word_report
from anki_pipeline.study_catalog_revision import amend_decision,reviewed_ownership_origin
from tests import test_study_catalog_content as content_tests
from tests import test_study_catalog_ownership as ownership_tests
from tests.test_sense_candidate_scope import scope_fixture


class OwnershipDisplayQualificationTests(unittest.TestCase):
    def flat_revised_transfer(self):
        from anki_pipeline.study_catalog_content import _append_source_chain,_source,_row_review
        before,draft,prepare=content_tests.SourceRevisionDisplayProofTests().amended_transfer()
        original=before['occurrences'][0];row=draft['occurrences'][0]
        row['semantic_review']['catalog_source_revision_chain']=_append_source_chain(
            before,original,_source(row),{'expected':_row_review(original),'new':_row_review(row)},row['reason'])
        row['semantic_review'].pop('catalog_source_revisions',None)
        row['semantic_review'].pop('catalog_ownership_transfers',None)
        return prepare(draft)

    def test_valid_flat_source_chain_retains_reviewed_transfer_qualification(self):
        record=self.flat_revised_transfer()
        self.assertNotIn('catalog_ownership_transfers',record['occurrences'][0]['semantic_review'])
        self.assertTrue(reviewed_ownership_origin(record))

    def test_forged_chain_and_rebound_transfer_do_not_authorize_grouping(self):
        record=self.flat_revised_transfer();altered=deepcopy(record)
        chain=altered['occurrences'][0]['semantic_review']['catalog_source_revision_chain']
        chain['steps'][0]['new_source']['translation']='伪造译文'
        chain.pop('chain_sha256');chain['chain_sha256']=sf._sha(sf._json(chain))
        with self.assertRaisesRegex(ValueError,'step seal'):reviewed_ownership_origin(altered)
        _,draft=ownership_tests.TransferredDisplayProofTests().transfer_fixture()
        from anki_pipeline.study_catalog_ownership import _reseal
        direct=_reseal(draft)
        proof=direct['occurrences'][0]['semantic_review']['catalog_ownership_transfers'][-1]
        proof['target_card_id']='wrong-owner';proof.pop('proof_sha256');proof['proof_sha256']=sf._sha(sf._json(proof))
        with self.assertRaisesRegex(ValueError,'target owner'):reviewed_ownership_origin(direct)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),'requires isolated PostgreSQL test connection')
class RevisionSequenceTests(unittest.TestCase):
    def fixture(self,kind):
        item=kind();item.setUp();self.addCleanup(item.tearDown);return item

    def fields(self,target,book,word):
        with c.connect(target,readonly=True) as db:
            nid=db.execute('select n.note_id from notes n join words w on w.id=n.word_id '
                           'where n.book_id=%s and w.surface=%s',(book,word)).fetchone()[0]
            note=project_note(db,project_book(db,book),nid)
            return dict(zip(note['field_names'],note['fields']))

    def decision(self,target,word,physical=None):
        with c.connect(target,readonly=True) as db:
            rows=db.execute('select a.book_id,a.source_card_id,a.record_id from analyses a '
                            'join words w on w.id=a.word_id where w.surface=%s',(word,)).fetchall()
            current=c.get_json(db,rows[0][2])
            physical=physical or current['occurrences'][0]['occurrence_id']
            expected={b+'/'+card:rid for b,card,rid in rows if any(
                r['occurrence_id']==physical for r in c.get_json(db,rid)['occurrences'])}
            sense=db.execute('select sense_id from analysis_senses where book_id=%s '
                             'and source_card_id=%s and ordinal=0',rows[0][:2]).fetchone()[0]
        return dict(word=word,physical_id=physical,sense_id=sense,reason='后续完整上下文复核',expected=expected)

    def assert_hosts_keep_examples(self,fixture,word,expected):
        for book in ('one','two','future'):
            fields=self.fields(fixture.target,book,word)
            self.assertEqual(fields['Examples'],expected[book])
            self.assertIn('后续完整上下文复核',fields['Definition'])
            path=fixture.root/(book+'-sequence.apkg');export_book(fixture.target,book,path)
            with zipfile.ZipFile(path) as archive:
                db=sqlite3.connect(':memory:')
                try:
                    db.deserialize(archive.read('collection.anki2'))
                    self.assertTrue(any(expected[book] in row[0] for row in db.execute('select flds from notes')))
                finally:db.close()
            folder=fixture.root/(book+'-sequence-web');export_book(fixture.target,book,folder,format='web')
            card=next(x for x in json.loads((folder/'catalog.json').read_text())['cards'] if x['word']==word)
            page=(folder/card['url']).read_text()
            sides,_=json.JSONDecoder().raw_decode(page.split('const sides=',1)[1])
            self.assertIn(expected[book],sides[1])
            report=word_report(fixture.target,word)
            variant=next(x for x in report['book_variants'] if x['book_id']==book)
            example=next(x for x in variant['fields'] if x['name']=='Examples')
            with c.connect(fixture.target,readonly=True) as db:
                semantic=project_note(db,project_book(db,book),variant['note_id'],apply_runtime=False)
                original=semantic['fields'][semantic['field_names'].index('Examples')]
            self.assertEqual(example['current_sha256'],__import__('hashlib').sha256(original.encode()).hexdigest())
            record=reviewed_record(fixture.target,book_id=book,source_card_id=variant['source_card_id'])
            self.assertEqual(record['record_sha256'],variant['record_sha256'])

    def test_source_then_decision_keeps_new_examples_in_both_hosts_and_read_api(self):
        item=self.fixture(content_tests.SharedContentRevisionTests)
        amend_sentence(item.target,**item.sentence_request())
        expected={book:self.fields(item.target,book,'novel')['Examples'] for book in ('one','two','future')}
        self.assertTrue(all('Indeed, ' in text for text in expected.values()))
        amend_decision(item.target,**self.decision(item.target,'novel'),backups=item.root/'backup')
        self.assert_hosts_keep_examples(item,'novel',expected)

    def test_transfer_then_decision_keeps_destination_and_source_examples(self):
        item=self.fixture(ownership_tests.OwnershipRevisionTests)
        request=item.request();transfer_occurrence(item.target,**request)
        expected={book:self.fields(item.target,book,'training')['Examples'] for book in ('one','two','future')}
        self.assertTrue(all('本句归属说明' in text for text in expected.values()))
        amend_decision(item.target,**self.decision(item.target,'training',request['physical_id']),backups=item.root/'backup')
        self.assert_hosts_keep_examples(item,'training',expected)
        for book in ('one','two','future'):self.assertNotIn('Model training',self.fields(item.target,book,'train')['Examples'])

    def test_same_paragraph_transfer_groups_both_hosts_without_persisting_derived_native_markup(self):
        from tests.test_sense_display import source
        from anki_pipeline.native_example_usage import _Offsets
        from anki_pipeline.study_catalog_native_groups import _historical
        class SameParagraph(ownership_tests.OwnershipRevisionTests):
            def physical_fixtures(self):
                original=source('kaoyan:2024-01:p:block-1:0',
                    'Model training and training develop skills.','模型训练与培训培养技能。',
                    [{'en':[6,14],'zh':[[2,4]],'relation':'equivalent'},
                     {'en':[19,27],'zh':[[5,7]],'relation':'equivalent'}])
                return original,original,[6,14],[19,27]
        item=self.fixture(SameParagraph);request=item.request();transfer_occurrence(item.target,**request)
        def current_rows(raw):
            return [n for n in _Offsets(raw,{}).root.walk() if n.tag=='li' and 'example-card' in n.classes and not _historical(n)]
        for book in ('one','two','future'):
            shown=self.fields(item.target,book,'training')['Examples']
            self.assertEqual(len(current_rows(shown)),1)
            with c.connect(item.target,readonly=True) as db:
                nid=db.execute('select n.note_id from notes n join words w on w.id=n.word_id '
                    "where n.book_id=%s and w.surface='training'",(book,)).fetchone()[0]
                raw=project_note(db,project_book(db,book),nid,apply_runtime=False)
                stored=raw['fields'][raw['field_names'].index('Examples')]
                self.assertEqual(len(current_rows(stored)),2)
                self.assertNotEqual(shown,stored)
        amend_decision(item.target,**self.decision(item.target,'training',request['physical_id']),backups=item.root/'backup')
        expected={book:self.fields(item.target,book,'training')['Examples'] for book in ('one','two','future')}
        self.assert_hosts_keep_examples(item,'training',expected)
        from anki_pipeline.study_catalog_query import frequency_report
        self.assertEqual(frequency_report(item.target,word='training')['physical_occurrences'],2)

    def test_decision_reissues_candidate_seals_without_dropping_excluded_source_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=c.Target(os.environ['ANKI_STUDY_TEST_DSN'],'testcatalog_'+uuid.uuid4().hex)
            try:
                raw,scope=scope_fixture(root);raw['candidate_scope']=scope;before=sf.prepare_record(raw)
                model=genanki.Model(7621,'candidate decision sequence',fields=[{'name':n} for n in ('Word','Definition','Examples')],
                    templates=[{'name':'Card','qfmt':'{{Word}}','afmt':'{{Definition}} {{Examples}}'}])
                deck=genanki.Deck(7622,'Candidate ledger')
                deck.add_note(genanki.Note(model=model,fields=[before['word'],sf.render_report(sf.report_from_record(before)),'original native']))
                path=root/'scope.apkg';genanki.Package(deck).write_to_file(str(path))
                import_package(target,path,book_id=before['book_id'],title='Candidate ledger',edition=2027)
                with c.connect(target) as db,c.transaction(db):
                    import_analysis(db,before)
                    db.execute('update notes set source_card_id=%s',(before['card_id'],))
                amend_decision(target,**self.decision(target,before['word']),backups=root/'backup')
                current=reviewed_record(target,book_id=before['book_id'],source_card_id=before['card_id'])['record']
                self.assertEqual(current['candidate_scope']['excluded'],before['candidate_scope']['excluded'])
                self.assertEqual(current['expected_occurrences'],3)
                from anki_pipeline.sense_candidate_scope import validate_stored_scope
                validate_stored_scope(current['candidate_source_record'],current['candidate_scope'])
            finally:
                with psycopg.connect(target.dsn,autocommit=True) as db:
                    db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(target.schema)))

    def same_paragraph_fixture(self):
        from tests.test_sense_display import source
        class SameParagraph(ownership_tests.OwnershipRevisionTests):
            def physical_fixtures(self):
                original=source('kaoyan:2024-01:p:block-1:0',
                    'Model training and training develop skills.','模型训练与培训培养技能。',
                    [{'en':[6,14],'zh':[[2,4]],'relation':'equivalent'},
                     {'en':[19,27],'zh':[[5,7]],'relation':'equivalent'}])
                return original,original,[6,14],[19,27]
        return self.fixture(SameParagraph)

    def test_transfer_then_source_revision_keeps_grouping_in_both_hosts(self):
        self.assert_transfer_source_grouping()

    def test_transfer_without_display_then_source_revision_keeps_grouping_in_both_hosts(self):
        self.assert_transfer_source_grouping(without_display=True)

    def assert_transfer_source_grouping(self,without_display=False):
        from anki_pipeline import sense_display as sd
        from anki_pipeline.study_catalog_content import _source,_row_review
        from anki_pipeline.native_example_usage import _Offsets
        from anki_pipeline.study_catalog_native_groups import _historical
        from anki_pipeline.study_catalog_query import frequency_report
        item=self.same_paragraph_fixture()
        if without_display:
            from anki_pipeline.study_catalog_ownership import _reseal
            with c.connect(item.target) as db,c.transaction(db):
                for (book,word),before in item.records.items():
                    draft=deepcopy(before)
                    for row in draft['occurrences']:row.pop('display',None)
                    after=_reseal(draft);ref=(book,before['card_id'])
                    for table in ('analysis_occurrences','analysis_senses','analyses'):
                        db.execute('delete from '+table+' where book_id=%s and source_card_id=%s',ref)
                    import_analysis(db,after)
                    component=db.execute('select f.component_id from note_fields f join notes n '
                        'on n.book_id=f.book_id and n.note_id=f.note_id '
                        "where n.book_id=%s and n.source_card_id=%s and f.name='Definition'",ref).fetchone()[0]
                    raw=item.fields[(book,word)][1].replace(before['snapshot_id'],after['snapshot_id'])
                    db.execute('update components set current_id=%s where id=%s',(c.put_object(db,raw.encode()),component))
                    item.records[(book,word)]=after
        request=item.request();transfer_occurrence(item.target,**request)
        physical=item.records[('one','train')]['occurrences'][0]['physical_source']
        records={}
        with c.connect(item.target,readonly=True) as db:
            for book,card,rid in db.execute('select book_id,source_card_id,record_id from analyses'):
                record=c.get_json(db,rid)
                if any(row['physical_source']==physical for row in record['occurrences']):
                    records[book+'/'+card]=(rid,record)
        first=next(row for _,record in records.values() for row in record['occurrences'] if row['physical_source']==physical)
        old_source=_source(first);new_source=deepcopy(old_source)
        new_source['alignment']['alignments'][0]={'en':[0,14],'zh':[[0,4]],'relation':'equivalent'}
        reviews={}
        for key,(_,record) in records.items():
            reviews[key]={}
            for old in record['occurrences']:
                if old['physical_source']!=physical:continue
                row=deepcopy(old);row.update(deepcopy(new_source));row['reason']='后续完整上下文复核'
                display=row.get('display')
                if display is not None:
                    display['provenance']['raw_context_hash']=sd._raw_context_hash(row)
                    display['alignment']=sd._project_alignment(row,display['english'],display['translation'],display['alignment_sources'])
                    display.pop('display_hash');display['display_hash']=sd._sha(sd._json(display))
                reviews[key][old['occurrence_id']]={'expected':_row_review(old),'new':_row_review(row)}
        amend_sentence(item.target,paper_id=first['paper_id'],physical_source=physical,
            expected_source=old_source,new_source=new_source,occurrence_reviews=reviews,
            expected={key:rid for key,(rid,_) in records.items()},reason='转归后完整chunk校勘',backups=item.root/'backup')
        expected={}
        for book in ('one','two','future'):
            examples=self.fields(item.target,book,'training')['Examples'];expected[book]=examples
            nodes=[node for node in _Offsets(examples,{}).root.walk() if node.tag=='li' and 'example-card' in node.classes and not _historical(node)]
            self.assertEqual(len(nodes),1)
            self.assertIn('本句归属说明',examples)
            with c.connect(item.target,readonly=True) as db:
                card=db.execute('select n.source_card_id from notes n join words w on w.id=n.word_id '
                    "where n.book_id=%s and w.surface='training'",(book,)).fetchone()[0]
            record=reviewed_record(item.target,book_id=book,source_card_id=card)['record']
            if not without_display:self.assertTrue(reviewed_ownership_origin(record))
            else:
                self.assertTrue(all('display' not in row for row in record['occurrences']))
        self.assertEqual(frequency_report(item.target,word='training')['physical_occurrences'],2)
        self.assert_hosts_keep_examples(item,'training',expected)

    def test_false_or_missing_immutable_origin_cannot_enable_grouping(self):
        from anki_pipeline import study_catalog_revision as revision
        item=self.same_paragraph_fixture();transfer_occurrence(item.target,**item.request())
        with c.connect(item.target) as db,c.transaction(db):
            registry=revision.registry(db);key=c.identity('one','one-training')
            original=deepcopy(registry[key]);origin=c.get_json(db,original['native_grouping_origin_record_id'])
            wrong=deepcopy(origin);wrong['book_id']='wrong-book'
            invalid=deepcopy(origin)
            proof=next(row for row in invalid['occurrences'] if row.get('semantic_review',{}).get('catalog_ownership_transfers'))['semantic_review']['catalog_ownership_transfers'][-1]
            proof['source_record']['word']='forged-source-owner'
            cases=[('0'*64,'content object'),(c.put_json(db,wrong),'another semantic owner'),
                   (c.put_json(db,invalid),'immutable source records')]
            for origin_id,_ in cases:
                registry[key]={**original,'native_grouping_origin_record_id':origin_id}
                db.execute('update metadata set value=%s where key=%s',(c.canonical(registry),revision.KEY))
                nid=db.execute("select note_id from notes where book_id='one' and source_card_id='one-training'").fetchone()[0]
                with self.assertRaises(ValueError):project_note(db,project_book(db,'one'),nid)
            registry[key]=original
            db.execute('update metadata set value=%s where key=%s',(c.canonical(registry),revision.KEY))

    def test_unsupported_final_native_grouping_rolls_back_all_books_and_versions(self):
        item=self.same_paragraph_fixture()
        with c.connect(item.target) as db,c.transaction(db):
            component=db.execute("select f.component_id from note_fields f join notes n on n.book_id=f.book_id and n.note_id=f.note_id "
                "where n.book_id='two' and n.source_card_id='two-training' and f.name='Examples'").fetchone()[0]
            raw=item.fields[('two','training')][2]
            native=raw.replace('</span><a class="sentence-jump"','<audio src="inline.mp3"></audio></span><a class="sentence-jump"',1)
            self.assertNotEqual(native,raw)
            db.execute('update components set current_id=%s where id=%s',(c.put_object(db,native.encode()),component))
        before=c.logical_digest(item.target)
        with self.assertRaisesRegex(ValueError,'unsupported native sentence'):
            transfer_occurrence(item.target,**item.request())
        self.assertEqual(c.logical_digest(item.target),before)
        with c.connect(item.target,readonly=True) as db:
            self.assertIsNone(db.execute('select value from metadata where key=%s',('semantic.projections.v1',)).fetchone())

    def test_later_decision_new_grouping_failure_rolls_back_all_books_and_versions(self):
        """A valid transfer may gain a new merge boundary in a later review."""
        from anki_pipeline.study_catalog_ownership import _reseal
        item=self.same_paragraph_fixture()
        with c.connect(item.target) as db,c.transaction(db):
            for book in ('one','two'):
                before=item.records[(book,'training')];draft=deepcopy(before)
                draft['senses']=[{'pos':'n.','text':'训练；培训'},{'pos':'n.','text':'体育训练'}]
                draft['senses']=sf._definition(draft)['senses']
                draft['occurrences'][0]['sense_id']=draft['senses'][1]['sense_id']
                after=_reseal(draft);ref=(book,before['card_id'])
                for table in ('analysis_occurrences','analysis_senses','analyses'):
                    db.execute('delete from '+table+' where book_id=%s and source_card_id=%s',ref)
                import_analysis(db,after)
                original=item.fields[(book,'training')]
                start=original[1].index('<div class="sf-report"')
                definition=original[1][:start]+sf.render_report(sf.report_from_record(after))+'<footer>词典来源</footer>'
                examples=original[2]
                if book=='two':
                    examples=examples.replace('</span><a class="sentence-jump"',
                        '<audio src="inline.mp3"></audio></span><a class="sentence-jump"',1)
                    self.assertIn('inline.mp3',examples)
                for name,value in (('Definition',definition),('Examples',examples)):
                    component=db.execute('select f.component_id from note_fields f join notes n '
                        'on n.book_id=f.book_id and n.note_id=f.note_id '
                        'where n.book_id=%s and n.source_card_id=%s and f.name=%s',(*ref,name)).fetchone()[0]
                    db.execute('update components set current_id=%s where id=%s',
                        (c.put_object(db,value.encode()),component))
                item.records[(book,'training')]=after
                item.fields[(book,'training')]=[original[0],definition,examples]
        request=item.request()
        with c.connect(item.target,readonly=True) as db:
            request['sense_id']=db.execute("select sense_id from analysis_senses where book_id='one' "
                "and source_card_id='one-training' and ordinal=0").fetchone()[0]
        transfer_occurrence(item.target,**request)
        physical=item.records[('one','training')]['occurrences'][0]['occurrence_id']
        self.assertIn('inline.mp3',self.fields(item.target,'two','training')['Examples'])
        before=c.logical_digest(item.target)
        with self.assertRaisesRegex(ValueError,'unsupported native sentence'):
            amend_decision(item.target,**self.decision(item.target,'training',physical),backups=item.root/'backup')
        self.assertEqual(c.logical_digest(item.target),before)


if __name__=='__main__':unittest.main()
