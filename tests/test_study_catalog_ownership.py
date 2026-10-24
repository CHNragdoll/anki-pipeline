"""Cross-book ownership amendments keep content and counts in one revision."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import genanki
import psycopg
from psycopg import sql

from anki_pipeline import sense_frequency as sf, sense_display as sd, study_catalog as c
from anki_pipeline.study_catalog_books import create_book
from anki_pipeline.study_catalog_export import export_book
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_normalize import import_analysis
from anki_pipeline.study_catalog_ownership import transfer_occurrence
from anki_pipeline.study_catalog_ownership import _move_row, _reseal
from anki_pipeline.study_catalog_query import frequency_report
from anki_pipeline.packaging import _exam_frequency_markup
from anki_pipeline import study_catalog_revision as revision
from tests.test_sense_display import native_example, occurrence, source
from tests.test_sense_frequency import completed_record


class TransferredDisplayProofTests(unittest.TestCase):
    def transfer_fixture(self):
        before = sf.prepare_record(completed_record())
        target = {'book_id': before['book_id'], 'card_id': 'correct-target', 'word': 'training',
                  'definition_source': 'oxford', 'definition_provenance': {'entry': 'training', 'page_sha256': '1' * 64},
                  'expected_occurrences': 0, 'senses': [{'pos': 'n.', 'text': '训练'}], 'occurrences': []}
        target = sf.prepare_record(target)
        oid = before['occurrences'][0]['occurrence_id']
        moved, _, _ = _move_row(before, target, oid, 0, '完整上下文及词典证明名词归属', {'dictionary': 'oxford'})
        draft = deepcopy(target)
        draft['occurrences'] = [moved]
        return before, draft

    def reseal_proof(self, draft):
        proof = draft['occurrences'][0]['semantic_review']['catalog_ownership_transfers'][-1]
        proof.pop('proof_sha256')
        proof['proof_sha256'] = sf._sha(sf._json(proof))

    def test_exact_display_provenance_survives_legitimate_ownership_and_later_decision(self):
        before, draft = self.transfer_fixture()
        result = _reseal(draft)
        self.assertEqual(result['occurrences'][0]['display'], before['occurrences'][0]['display'])
        draft = deepcopy(result)
        draft['occurrences'][0].update(reason='再次核实细分意义', method='shared-catalog-reviewed.v1')
        self.assertEqual(_reseal(draft)['occurrences'][0]['reason'], '再次核实细分意义')

    def test_stale_or_rebound_transfer_proofs_are_rejected(self):
        for change, reseal in (('reason', False), ('target_card_id', True), ('physical_id', True)):
            with self.subTest(change=change):
                _, draft = self.transfer_fixture()
                proof = draft['occurrences'][0]['semantic_review']['catalog_ownership_transfers'][-1]
                proof[change] = 'forged'
                if reseal:
                    self.reseal_proof(draft)
                with self.assertRaisesRegex(ValueError, 'ownership proof|target owner|source occurrence'):
                    _reseal(draft)


class NativeOwnershipSourceHistoryTests(unittest.TestCase):
    def test_source_revision_then_transfer_preserves_both_current_and_complete_old_sentences(self):
        self.assert_source_revision_then_transfer()

    def test_attribute_only_source_archives_use_the_same_transfer_boundaries(self):
        self.assert_source_revision_then_transfer(attribute_only=True)

    def assert_source_revision_then_transfer(self,attribute_only=False):
        from anki_pipeline.study_catalog_content import _examples
        from anki_pipeline.study_catalog_ownership import _native_transfer, _prepared
        from anki_pipeline.native_example_usage import (_Offsets, _historical,
            _current_descendant, _current_native_example, restore_original, update_native_examples)
        item=source('kaoyan:2024-01:p:block-1:0',
            'Model training and training develop skills.','模型训练与培训培养技能。',
            [{'en':[6,14],'zh':[[2,4]],'relation':'equivalent'},
             {'en':[19,27],'zh':[[5,7]],'relation':'equivalent'}])
        spans=([6,14],[19,27])
        native=[]
        rows=[]
        for index,span in enumerate(spans):
            fragment=native_example(item,item['english'],item['translationZh'],[span])
            fragment=fragment.replace('<li class="example-card">',
                '<li class="example-card"><span class="index-tag">9</span>',1)
            fragment=fragment.replace('</li>','<span data-native-example-usage="v1">原位置角色'
                +str(index)+'</span><audio src="source-'+str(index)+'.mp3"></audio></li>')
            native.append(fragment)
            row=occurrence(item,span)
            row.update(paper_id='kaoyan:2024-01',method='context-review',review_version='test',
                       translation_ranges=[[2,4]] if index==0 else [[5,7]])
            rows.append(row)
        raw='<ol>'+''.join(native)+'</ol>'
        value={'book_id':'one','card_id':'one-train','word':'train','definition_source':'oxford',
            'definition_provenance':{'entry':'train','page_sha256':sd._sha(raw)},
            'expected_occurrences':2,'senses':[{'pos':'v.','text':'训练'}],'occurrences':rows}
        for row in value['occurrences']:
            row.update(sf.seal_reviewed_assignment(value,row))
        before=sf.prepare_record(value);draft=deepcopy(before)
        for row in draft['occurrences']:
            row['alignment']['alignments'][0]={'en':[0,14],'zh':[[0,4]],'relation':'equivalent'}
        revised=_reseal(draft)
        revised_raw=_examples(raw,list(zip(before['occurrences'],revised['occurrences'])),
            '完整上下文核实后补充chunk',known_occurrences=before['occurrences'])
        if attribute_only:
            revised_raw=revised_raw.replace('class="sf-catalog-revision" ','')
        audits=[revised_raw[node.start:node.end] for node in _Offsets(revised_raw,{}).root.walk()
                if 'sf-catalog-revision' in node.classes or 'data-reviewed-source-comparison' in node.attrs]
        self.assertEqual(len(audits),2)
        target=sf.prepare_record({'book_id':'one','card_id':'one-training','word':'training',
            'definition_source':'oxford','definition_provenance':{'entry':'training'},
            'expected_occurrences':0,'senses':[{'pos':'n.','text':'训练；培训'}],'occurrences':[]})
        moved_id=next(row['occurrence_id'] for row in revised['occurrences'] if row['target_range']==spans[0])
        moved,_,_=_move_row(revised,target,moved_id,0,
            '名词用法已核实',{'dictionary':'oxford'})
        remaining=deepcopy(revised)
        remaining['occurrences']=[row for row in remaining['occurrences'] if row['occurrence_id']!=moved_id]
        remaining=_reseal(remaining)
        destination=deepcopy(target);destination['occurrences']=[moved]
        self.assertEqual(len(remaining['occurrences'])+len(_reseal(destination)['occurrences']),2)
        target_archive=('<details data-reviewed-source-comparison="catalog-revision"><summary>目标原稿</summary>'
                        '<ol>'+native[0]+'</ol></details>')
        source_raw,target_raw=_native_transfer(revised_raw,'<ol></ol>'+target_archive,revised,remaining,target,
            moved,'<details class="sf-catalog-revision"><summary>本句归属说明</summary>转归证据</details>',{})
        def current(markup):
            return [node for node in _Offsets(markup,{}).root.walk()
                    if node.tag=='li' and 'example-card' in node.classes and not _historical(node)]
        self.assertEqual(len(current(source_raw)),1)
        self.assertEqual(len(current(target_raw)),1)
        self.assertIn(audits[1],source_raw)
        self.assertIn(audits[0],target_raw)
        self.assertIn(target_archive,target_raw)
        self.assertIn('source-0.mp3',target_raw)
        self.assertIn('source-1.mp3',source_raw)
        for markup,span in ((source_raw,spans[1]),(target_raw,spans[0])):
            node=current(markup)[0]
            self.assertEqual(_current_native_example(markup[node.start:node.end],{})['target_ranges'],[span])
            badge=_current_descendant(node,'index-tag')
            self.assertEqual(markup[badge.opened:badge.closed],'1')
        # The shared updater still supplies an exact byte inverse after archive-aware edits.
        check=update_native_examples(revised_raw,_prepared(revised),_prepared(remaining))
        self.assertEqual(restore_original(check['page'],check['inverse']),revised_raw)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires isolated PostgreSQL test connection')
class OwnershipRevisionTests(unittest.TestCase):
    def physical_fixtures(self):
        first = source('kaoyan:2024-01:p:block-1:0', 'Model training develops skills.', '模型训练培养技能。',
            [{'en': [6, 14], 'zh': [[2, 4]], 'relation': 'equivalent'}])
        second = source('kaoyan:2022-01:p:block-2:0', 'Training takes time.', '培训需要时间。',
            [{'en': [0, 8], 'zh': [[0, 2]], 'relation': 'equivalent'}])
        return first, second, [6, 14], [0, 8]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_' + uuid.uuid4().hex)
        self.records = {}
        self.fields = {}
        self.transferred, self.other, first_span, second_span = self.physical_fixtures()
        for index, book in enumerate(('one', 'two')):
            model = genanki.Model(7411, 'ownership semantics',
                fields=[{'name': name} for name in ('Word', 'Definition', 'Examples')],
                templates=[{'name': 'Card', 'qfmt': '{{Word}}', 'afmt': '{{Definition}} {{Examples}}'}])
            deck = genanki.Deck(7412 + index, book)
            for word, item, span, pos in (('train', self.transferred, first_span, 'v.'),
                                          ('training', self.other, second_span, 'n.')):
                examples = '<ol>' + native_example(item, item['english'], item['translationZh'], [span]) + '</ol>'
                examples = examples.replace('<li class="example-card">', '<li class="example-card"><span class="index-tag">9</span>')
                row = occurrence(item, span)
                row.update(paper_id=item['id'].split(':p:')[0], method='context-review', review_version='20261015',
                           translation_ranges=next(chunk['zh'] for chunk in item['translation_alignment']['alignments']
                                                   if chunk['en'] == span))
                value = {'book_id': book, 'card_id': book + '-' + word, 'word': word,
                         'definition_source': 'oxford', 'definition_provenance': {
                             'entry': word, 'headword': word, 'page_sha256': sd._sha(examples)},
                         'expected_occurrences': 1, 'senses': [{'pos': pos, 'text': '训练；培训'}],
                         'occurrences': [row]}
                value['occurrences'][0] = sf.seal_reviewed_assignment(value, row)
                sources = {'sentences': {item['id']: item}, 'completions': {}, 'options': {}, 'watched': {}}
                with patch.object(sd, '_load_sources', return_value=sources):
                    value = sd.attach_source_displays([value], {value['card_id']: examples}, {})[0]
                record = sf.prepare_record(value)
                self.records[(book, word)] = record
                report = sf.render_report(sf.report_from_record(record))
                report = report.replace('</article>', '<details class="sf-source-confirmation-history">'
                    '<summary>完整原审核</summary><p>旧版本全部解释</p></details></article>')
                frequency = {'schema': 'kaoyan-frequency.v1', 'rule': 'occurrence-bands.v1',
                    'occurrences': 1, 'matched_sentences': 1, 'paper_count': 1, 'corpus_papers': 44, 'stars': .5}
                definition = (_exam_frequency_markup({'exam_frequency': frequency})
                    + '<header>原词典完整解释 ' + word + '</header>' + report + '<footer>词典来源</footer>')
                self.fields[(book, word)] = [word, definition, examples]
                deck.add_note(genanki.Note(model=model, fields=self.fields[(book, word)]))
            package = self.root / (book + '.apkg')
            genanki.Package(deck).write_to_file(str(package))
            import_package(self.target, package, book_id=book, title=book, edition=2027)
            with c.connect(self.target) as db, c.transaction(db):
                for word in ('train', 'training'):
                    record = self.records[(book, word)]
                    import_analysis(db, record)
                    db.execute('update notes set source_card_id=%s where book_id=%s and word_id=%s',
                               (record['card_id'], book, c.ensure_word(db, word)))
        create_book(self.target, {'schema': 'study-book-map.v1', 'id': 'future', 'title': 'Future', 'edition': 2028,
            'scope': {'subject': '英语', 'exam': 'IELTS'},
            'units': [{'name': 'Unit 01', 'items': [{'word': word, 'from_book': 'one'} for word in ('train', 'training')]}]})

    def tearDown(self):
        with psycopg.connect(self.target.dsn, autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.target.schema)))
        self.temp.cleanup()

    def request(self):
        with c.connect(self.target, readonly=True) as db:
            expected = {book + '/' + card: rid for book, card, rid in db.execute(
                'select book_id,source_card_id,record_id from analyses')}
            sense = db.execute("select sense_id from analysis_senses where book_id='one' and source_card_id='one-training'").fetchone()[0]
        return dict(source_word='train', target_word='training',
                    physical_id=self.records[('one', 'train')]['occurrences'][0]['occurrence_id'],
                    sense_id=sense, reason='AI model training 是独立名词，归训练名词',
                    evidence={'dictionary': 'oxford', 'definition': 'the process of learning the skills'},
                    expected=expected, backups=self.root / 'backups')

    def test_transfer_two_sources_and_mapped_book_preserves_exact_audits_and_hosts(self):
        before = frequency_report(self.target)['physical_occurrences']
        result = transfer_occurrence(self.target, **self.request())
        self.assertEqual(len(result['changes']), 4)
        self.assertEqual(frequency_report(self.target)['physical_occurrences'], before)
        self.assertEqual(frequency_report(self.target, word='train')['physical_occurrences'], 0)
        report = frequency_report(self.target, word='training')
        self.assertEqual(report['physical_occurrences'], 2)
        self.assertEqual([book['physical_occurrences'] for book in report['books']], [2, 2, 2])
        for book in ('one', 'two', 'future'):
            apkg = self.root / (book + '-changed.apkg')
            export_book(self.target, book, apkg)
            with zipfile.ZipFile(apkg) as archive:
                db = sqlite3.connect(':memory:')
                try:
                    db.deserialize(archive.read('collection.anki2'))
                    fields = {row[0].split('\x1f')[0]: row[0].split('\x1f') for row in db.execute('select flds from notes')}
                finally:
                    db.close()
            self.assertEqual(revision._nodes(fields['train'][1], 'sf-example'), [])
            self.assertIn('data-occurrences="0"', fields['train'][1])
            self.assertNotIn('Model training', fields['train'][2])
            target = fields['training']
            current = revision._nodes(target[1], 'sf-example')
            self.assertEqual(len(current), 2)
            self.assertIn('data-occurrences="2"', target[1])
            self.assertIn('data-paper-count="2"', target[1])
            self.assertIn('data-corpus-papers="44"', target[1])
            for marker in ('Model training', '模型训练', '旧版本全部解释', '本句归属说明', '完整原记录与转归证据', 'card-chunk'):
                self.assertIn(marker, target[1])
            self.assertIn('Model ', target[2])
            self.assertIn('本句归属说明', target[2])
            self.assertIn('class="index-tag">1</span>', target[2])
            self.assertIn('class="index-tag">2</span>', target[2])
            folder = self.root / (book + '-web')
            export_book(self.target, book, folder, format='web')
            cards = json.loads((folder / 'catalog.json').read_text())['cards']
            page = next(folder / card['url'] for card in cards if card['word'] == 'training')
            self.assertIn('AI model training', page.read_text())

    def test_existing_correct_target_deduplicates_the_physical_position(self):
        for book in ('one', 'two'):
            before = self.records[(book, 'training')]
            draft = deepcopy(before)
            row = deepcopy(self.records[(book, 'train')]['occurrences'][0])
            row.pop('display', None)
            row.update(sense_id=draft['senses'][0]['sense_id'], reason='原目标已经正确收录')
            draft['occurrences'].append(row)
            after = _reseal(draft)
            examples = self.fields[(book, 'training')][2].replace('</ol>', native_example(
                self.transferred, self.transferred['english'], self.transferred['translationZh'], [[6, 14]]) + '</ol>')
            with c.connect(self.target) as db, c.transaction(db):
                ref = (book, before['card_id'])
                for table in ('analysis_occurrences', 'analysis_senses', 'analyses'):
                    db.execute('delete from ' + table + ' where book_id=%s and source_card_id=%s', ref)
                import_analysis(db, after)
                for name, raw in (('Definition', sf.render_report(sf.report_from_record(after))), ('Examples', examples)):
                    component = db.execute('select component_id from note_fields f join notes n '
                        'on n.book_id=f.book_id and n.note_id=f.note_id '
                        'where f.book_id=%s and n.source_card_id=%s and f.name=%s', (*ref, name)).fetchone()[0]
                    db.execute('update components set current_id=%s where id=%s', (c.put_object(db, raw.encode()), component))
        transfer_occurrence(self.target, **self.request())
        self.assertEqual(frequency_report(self.target, word='training')['physical_occurrences'], 2)
        self.assertEqual(frequency_report(self.target, word='train')['physical_occurrences'], 0)
        from anki_pipeline.study_catalog_export import project_book, project_note
        with c.connect(self.target, readonly=True) as db:
            nid = db.execute("select note_id from notes where book_id='one' and source_card_id='one-training'").fetchone()[0]
            note = project_note(db, project_book(db, 'one'), nid)
            definition = dict(zip(note['field_names'], note['fields']))['Definition']
            self.assertEqual(len(revision._nodes(definition, 'sf-example')), 2)
            self.assertIn('目标句合并前完整内容', definition)
            self.assertIn('原目标已经正确收录', definition)

    def test_later_reviewed_decision_keeps_the_transferred_display_and_its_history(self):
        request = self.request()
        transfer_occurrence(self.target, **request)
        with c.connect(self.target, readonly=True) as db:
            rows = db.execute("select a.book_id,a.source_card_id,a.record_id from analyses a "
                "join words w on w.id=a.word_id where w.surface='training'").fetchall()
        later = revision.amend_decision(self.target, word='training', physical_id=request['physical_id'],
            sense_id=request['sense_id'], reason='转归后再次核对，名词细义确认',
            expected={book + '/' + card: rid for book, card, rid in rows}, backups=self.root/'backups')
        self.assertEqual(len(later['changes']), 2)
        self.assertEqual(frequency_report(self.target, word='training')['physical_occurrences'], 2)
        from anki_pipeline.study_catalog_export import project_book, project_note
        with c.connect(self.target, readonly=True) as db:
            for book in ('one', 'two', 'future'):
                nid = db.execute('select n.note_id from notes n join words w on w.id=n.word_id '
                    "where n.book_id=%s and w.surface='training'", (book,)).fetchone()[0]
                note = project_note(db, project_book(db, book), nid)
                fields = dict(zip(note['field_names'], note['fields']))
                self.assertIn('转归后再次核对', fields['Definition'])
                self.assertIn('本句归属说明', fields['Definition'])
                self.assertIn('旧版本全部解释', fields['Definition'])

    def test_native_fields_with_template_owned_list_wrappers_are_supported(self):
        with c.connect(self.target) as db, c.transaction(db):
            for book in ('one', 'two'):
                for word in ('train', 'training'):
                    component = db.execute('select f.component_id from note_fields f join notes n '
                        'on n.book_id=f.book_id and n.note_id=f.note_id join words w on w.id=n.word_id '
                        "where n.book_id=%s and w.surface=%s and f.name='Examples'", (book, word)).fetchone()[0]
                    raw = self.fields[(book, word)][2]
                    self.assertTrue(raw.startswith('<ol>') and raw.endswith('</ol>'))
                    db.execute('update components set current_id=%s where id=%s',
                               (c.put_object(db, raw[4:-5].encode()), component))
        transfer_occurrence(self.target, **self.request())
        from anki_pipeline.study_catalog_export import project_book, project_note
        with c.connect(self.target, readonly=True) as db:
            nid = db.execute("select note_id from notes where book_id='one' and source_card_id='one-training'").fetchone()[0]
            note = project_note(db, project_book(db, 'one'), nid)
            examples = dict(zip(note['field_names'], note['fields']))['Examples']
            self.assertTrue(examples.startswith('<li class="example-card">'))
            self.assertEqual(examples.count('<li class="example-card">'), 2)

    def test_stale_or_partial_scope_rolls_back(self):
        request = self.request()
        request['expected'].pop('two/two-training')
        before = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'incomplete cross-book'):
            transfer_occurrence(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), before)

    def test_missing_target_in_mapped_book_is_rejected(self):
        create_book(self.target, {'schema': 'study-book-map.v1', 'id': 'missing-target', 'title': 'Incomplete',
            'edition': 2028, 'units': [{'name': 'One', 'items': [{'word': 'train', 'from_book': 'one'}]}]})
        before = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'mapped book.*lacks'):
            transfer_occurrence(self.target, **self.request())
        self.assertEqual(c.logical_digest(self.target), before)

    def test_late_second_book_failure_rolls_back_both_ends_and_versions(self):
        request = self.request()
        before = c.logical_digest(self.target)
        from anki_pipeline.study_catalog_content import repartition_definition
        calls = []
        def fail_late(*args, **kwargs):
            calls.append(args[1]['book_id'])
            if args[1]['book_id'] == 'two':
                raise ValueError('second book cannot preserve its native content')
            return repartition_definition(*args, **kwargs)
        with patch('anki_pipeline.study_catalog_content.repartition_definition', side_effect=fail_late):
            with self.assertRaisesRegex(ValueError, 'second book'):
                transfer_occurrence(self.target, **request)
        self.assertIn('one', calls)
        self.assertEqual(c.logical_digest(self.target), before)

    def test_missing_target_source_record_is_rejected_without_creating_a_word(self):
        request = self.request()
        request['target_word'] = 'nonexistent-entry'
        before = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'existing dictionary-backed target'):
            transfer_occurrence(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), before)
