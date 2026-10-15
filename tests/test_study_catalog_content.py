"""Cross-book reviewed content corrections, native body parity and rollback."""
from copy import deepcopy
import hashlib
import json
import os
import re
import sqlite3
import unittest
import tempfile
import zipfile

import genanki

from anki_pipeline import sense_frequency as sf, study_catalog as c
from anki_pipeline.study_catalog_content import (
    SOURCE_KEYS, ROW_KEYS, amend_dictionary_sense, amend_sentence,
    source_articles, _source, _row_review)
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_catalog_query import frequency_report
from anki_pipeline.study_catalog_import import import_package
from anki_pipeline.study_catalog_normalize import import_analysis
from tests.test_sense_frequency import reseal
from tests import test_study_catalog_revision as revision_tests


class SharedContentRevisionTests(revision_tests.SharedFactRevisionTests):
    # Inherited setUp creates two original books and an IELTS mapped book.
    # Hide inherited tests: they are exercised in their own dedicated module.
    test_one_fact_revision_updates_queries_apkg_and_web_and_keeps_complete_source_articles = None
    test_stale_scope_and_direct_html_edits_cannot_diverge_facts_from_body = None
    test_late_compile_failure_rolls_back_every_book = None

    def setUp(self):
        super().setUp()
        # Native Examples is a second live presentation, in addition to the
        # sense disclosure. Both must follow the same reviewed source revision.
        for book, record in self.before.items():
            row = record['occurrences'][0]
            body = ('<li class="example-card"><div class="example-heading"><span class="index-tag">1</span>'
                '<span class="example-text">' + row['english'] + '</span></div>'
                '<span class="example-translation"><span class="translate-tag">翻译</span> '
                + row['translation'] + '</span><span class="example-source">完整原来源</span></li>')
            with c.connect(self.target) as db:
                component = db.execute("select component_id from note_fields where book_id=%s and name='Examples'", (book,)).fetchone()[0]
                db.execute('update components set current_id=%s where id=%s', (c.put_object(db, body.encode()), component))

    def scope(self):
        with c.connect(self.target, readonly=True) as db:
            return {b + '/' + card: rid for b, card, rid in db.execute(
                'select book_id,source_card_id,record_id from analyses')}

    def dictionary_request(self):
        with c.connect(self.target, readonly=True) as db:
            sense_id = db.execute("select sense_id from analysis_senses where book_id='one' and ordinal=0").fetchone()[0]
        reviews = {book + '/' + before['card_id']: {r['occurrence_id']: '词典详细说明核对后仍为小说作品'
            for r in before['occurrences'] if r['sense_id'] == before['senses'][0]['sense_id']}
            for book, before in self.before.items()}
        return dict(sense_id=sense_id, expected_sense={'pos': 'n.', 'text': '小说'},
            new_sense={'pos': 'n.', 'text': '长篇小说'}, reason='核对完整词典条目的详细限定后修订',
            evidence={'dictionary': 'oxford', 'entry': 'novel', 'entry_html':
                '<article><h1>novel</h1><p>n. a long written story 长篇小说</p></article>',
                'locator': '本地牛津词典 novel 名词义项1', 'quoted_definition': 'a long written story 长篇小说',
                'reviewed_pos': 'n.', 'reviewed_text': '长篇小说', 'usage_reviews': reviews},
            expected=self.scope(), backups=self.root/'backups')

    def sentence_request(self, *, shifted=True):
        row = self.before['one']['occurrences'][0]
        old = _source(row); new = deepcopy(old)
        if shifted:
            new['english'] = 'Indeed, ' + old['english']
            new['translation'] = '的确，' + old['translation']
        new['source_provenance'] = {'reviewedContentHash': 'new-approved-source', 'evidence': '原卷准确校核'}
        new['alignment']['englishHash'] = hashlib.sha256(new['english'].encode()).hexdigest()
        new['alignment']['translationHash'] = hashlib.sha256(new['translation'].encode()).hexdigest()
        for chunk in new['alignment']['alignments']:
            if shifted:
                chunk['en'] = [v+8 for v in chunk['en']]
                chunk['zh'] = [[v+3 for v in span] for span in chunk['zh']]
            else:
                # Explicitly reviewed complete wider chunks, no word guessing.
                chunk['en'] = [0, 12] if chunk['en'] == [2, 7] else [13, 24]
        reviews = {}
        for book, before in self.before.items():
            scoped = {}
            for row in before['occurrences']:
                replacement = _row_review(row)
                if shifted:
                    replacement['target_range'] = [v+8 for v in row['target_range']]
                    replacement['translation_ranges'] = [[v+3 for v in span] for span in row['translation_ranges']]
                replacement['reason'] += '；新原句和chunk逐处复核'
                scoped[row['occurrence_id']] = {'expected': _row_review(row), 'new': replacement}
            reviews[book+'/'+before['card_id']] = scoped
        return dict(paper_id=row['paper_id'], physical_source=row['physical_source'],
            expected_source=old, new_source=new, occurrence_reviews=reviews, expected=self.scope(),
            reason='核对完整新原句、翻译及逐词位置', backups=self.root/'backups')

    def fields(self, book):
        with c.connect(self.target, readonly=True) as db:
            nid = db.execute('select note_id from notes where book_id=%s', (book,)).fetchone()[0]
            note = project_note(db, project_book(db, book), nid)
            return dict(zip(note['field_names'], note['fields']))

    def assert_hosts(self, marker):
        for book in ('one', 'two', 'future'):
            fields = self.fields(book)
            self.assertIn(marker, fields['Definition'])
            apkg = self.root/(book+'-content.apkg')
            export_book(self.target, book, apkg)
            with zipfile.ZipFile(apkg) as z:
                db = sqlite3.connect(':memory:')
                try:
                    db.deserialize(z.read('collection.anki2'))
                    native = db.execute('select flds from notes').fetchone()[0]
                finally:
                    db.close()
            self.assertIn(fields['Definition'], native)
            folder = self.root/(book+'-content-web')
            export_book(self.target, book, folder, format='web')
            card = json.loads((folder/'catalog.json').read_text())['cards'][0]
            page = (folder/card['url']).read_text()
            sides = json.loads(re.search(r'const sides=(.*?);let answer=', page).group(1))
            self.assertIn(fields['Definition'], sides[1])

    def test_dictionary_correction_updates_all_books_with_exact_source_evidence_and_unchanged_counts(self):
        old_ids = list(self.scope().values())
        result = amend_dictionary_sense(self.target, **self.dictionary_request())
        self.assertEqual(len(result['changes']), 2)
        report = frequency_report(self.target, word='novel')
        self.assertEqual(report['physical_occurrences'], 2)
        self.assertEqual([r['physical_occurrences'] for r in report['books']], [2, 2, 2])
        self.assert_hosts('长篇小说')
        for book in ('one', 'two', 'future'):
            fields = self.fields(book)
            for marker in ('完整词典详细解释', '原来源与补充释义', '全部内容、旧版本说明都保留',
                           '本句完整修订记录', 'card-chunk', '本地牛津词典'):
                self.assertIn(marker, fields['Definition'])
        with c.connect(self.target, readonly=True) as db:
            for rid in old_ids:
                self.assertEqual(c.get_json(db, rid)['senses'][0]['text'], '小说')
            active = db.execute('select s.text,p.provenance_id from analysis_senses a '
                'join dictionary_senses s on s.id=a.sense_id join dictionary_senses p on p.id=s.id '
                'where a.ordinal=0').fetchall()
            self.assertTrue(all(text == '长篇小说' for text, _ in active))
            for _, provenance in active:
                proof = c.get_json(db, provenance)
                self.assertEqual(proof['schema'], 'study-catalog-dictionary-correction.v1')
                self.assertIn('a long written story', c.get_object(db, proof['entry_html_sha256']).decode())

    def test_sentence_translation_and_chunk_revision_keeps_physical_count_and_original_audits(self):
        request = self.sentence_request()
        old_ids = list(self.scope().values())
        result = amend_sentence(self.target, **request)
        self.assertEqual(len(result['changes']), 2)
        self.assert_hosts('Indeed, ')
        self.assertEqual(frequency_report(self.target, word='novel')['physical_occurrences'], 2)
        with c.connect(self.target, readonly=True) as db:
            for (rid,) in db.execute('select record_id from analyses'):
                record = c.get_json(db, rid)
                for row in record['occurrences']:
                    self.assertEqual(row['english'], request['new_source']['english'])
                    self.assertEqual(row['translation'], request['new_source']['translation'])
                    self.assertEqual(row['alignment'], request['new_source']['alignment'])
            for rid in old_ids:
                self.assertEqual(c.get_json(db, rid)['occurrences'][0]['english'], request['expected_source']['english'])
            self.assertEqual(db.execute('select count(distinct original_occurrence_id) from analysis_occurrences').fetchone()[0], 2)
        self.assertIn('全部内容、旧版本说明都保留', self.fields('future')['Definition'])
        for book in ('one', 'two', 'future'):
            examples = self.fields(book)['Examples']
            self.assertIn('Indeed, ', examples)
            self.assertIn('的确，', examples)
            self.assertIn('完整原来源', examples)
            self.assertIn('本句完整修订记录', examples)

    def test_corrected_common_sense_needs_fresh_explicit_group_review(self):
        for book, before in list(self.before.items()):
            raw = deepcopy(before)
            for row in raw['occurrences']:
                row['sense_index'] = next(s['ordinal'] for s in before['senses'] if s['sense_id'] == row['sense_id'])
            raw['senses'][1].update(pos='n.', text='小说')
            raw['sense_group_equivalences'] = [{'member_ordinals': [0, 1], 'meaning': '小说',
                'reason': '原两项有完整词典依据同义', 'review_version': 'original-test',
                'usage_scope': '名词作品', 'evidence': [{'dictionary': 'oxford', 'review': '完整原义项'}]}]
            raw['sense_group_equivalences'][0]['member_sense_ids'] = [sense['sense_id'] for sense in sf._definition(raw)['senses']]
            raw = sf.prepare_record(reseal(raw))
            self.before[book] = raw
            with c.connect(self.target) as db, c.transaction(db):
                for table in ('analysis_occurrences', 'analysis_senses', 'analyses'):
                    db.execute('delete from '+table+' where book_id=%s', (book,))
                import_analysis(db, raw)
                component = db.execute("select component_id from note_fields where book_id=%s and name='Definition'", (book,)).fetchone()[0]
                db.execute('update components set current_id=%s where id=%s',
                    (c.put_object(db, sf.render_report(sf.report_from_record(raw)).encode()), component))
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'explicit reviewed equivalence'):
            amend_dictionary_sense(self.target, **self.dictionary_request())
        self.assertEqual(c.logical_digest(self.target), original)
        request = self.dictionary_request()
        request['evidence']['group_reviews'] = {book+'/'+record['card_id']: [] for book, record in self.before.items()}
        amend_dictionary_sense(self.target, **request)
        self.assertEqual(frequency_report(self.target, word='novel')['physical_occurrences'], 2)
        with c.connect(self.target, readonly=True) as db:
            for (rid,) in db.execute('select record_id from analyses'):
                record = c.get_json(db, rid)
                self.assertEqual(record['sense_group_equivalences'], [])
                self.assertEqual([sense['count'] for sense in sf.report_from_record(record)['senses']], [1, 1])

    def test_source_scope_includes_other_words_and_sentence_aliases(self):
        raw = deepcopy(self.before['one'])
        raw.update(book_id='other', card_id='other-idea', word='idea', expected_occurrences=1)
        raw['senses'] = [{'pos': 'n.', 'text': '想法'}]
        raw['definition_provenance'] = {'entry': 'idea'}
        row = deepcopy(raw['occurrences'][0])
        row.update(target_range=[8, 12], translation_ranges=[[8, 10]], sense_index=0,
                   reason='名词idea指想法', physical_source=['same-sentence-alias', 'block-1'])
        row['alignment']['alignments'].append({'en': [8, 12], 'zh': [[8, 10]], 'relation': 'equivalent'})
        raw['occurrences'] = [row]
        raw = sf.prepare_record(reseal(raw))
        definition = sf.render_report(sf.report_from_record(raw))
        model = genanki.Model(7221, 'other word shared source',
            fields=[{'name':'Word'}, {'name':'Definition'}, {'name':'Examples'}],
            templates=[{'name':'Card', 'qfmt':'{{Word}}', 'afmt':'{{Definition}} {{Examples}}'}])
        deck = genanki.Deck(7222, 'Other book')
        deck.add_note(genanki.Note(model=model, fields=['idea', definition, '']))
        package = self.root/'other.apkg'
        genanki.Package(deck).write_to_file(str(package))
        import_package(self.target, package, book_id='other', title='Other', edition=2027)
        with c.connect(self.target) as db, c.transaction(db):
            import_analysis(db, raw)
            db.execute("update notes set source_card_id='other-idea' where book_id='other'")
        self.before['other'] = raw
        request = self.sentence_request()
        # Its alignment genuinely differs, so the caller must review the full
        # per-variant source explicitly. Refuse partial edits rather than leave
        # a shared word stale.
        before = c.logical_digest(self.target)
        request['expected'].pop('other/other-idea')
        request['occurrence_reviews'].pop('other/other-idea')
        with self.assertRaisesRegex(ValueError, 'incomplete cross-book'):
            amend_sentence(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), before)
        # Different original word/dictionary editions can retain different
        # reviewed chunk maps. Supply every exact variant explicitly; none is
        # overwritten by a guessed generic map.
        request = self.sentence_request()
        variants = {}; replacements = {}
        for before_record in self.before.values():
            source = _source(before_record['occurrences'][0])
            identity = hashlib.sha256(c.canonical(source).encode()).hexdigest()
            variants[identity] = source
            new_source = deepcopy(source)
            new_source['english'] = 'Indeed, ' + source['english']
            new_source['translation'] = '的确，' + source['translation']
            new_source['source_provenance'] = {'reviewedContentHash': 'new-approved-source', 'evidence': '原卷准确校核'}
            new_source['alignment']['englishHash'] = hashlib.sha256(new_source['english'].encode()).hexdigest()
            new_source['alignment']['translationHash'] = hashlib.sha256(new_source['translation'].encode()).hexdigest()
            for chunk in new_source['alignment']['alignments']:
                chunk['en'] = [v+8 for v in chunk['en']]
                chunk['zh'] = [[v+3 for v in span] for span in chunk['zh']]
            replacements[identity] = new_source
        request['expected_source'] = {'variants': variants}
        request['new_source'] = {'variants': replacements}
        result = amend_sentence(self.target, **request)
        self.assertEqual(len(result['changes']), 3)
        with c.connect(self.target, readonly=True) as db:
            (rid,) = db.execute("select record_id from analyses where book_id='other'").fetchone()
            updated = c.get_json(db, rid)['occurrences'][0]
            self.assertTrue(updated['english'].startswith('Indeed, '))
            self.assertEqual(updated['physical_source'], ['same-sentence-alias', 'block-1'])
        self.assertEqual(frequency_report(self.target, word='idea')['physical_occurrences'], 1)
        self.assertEqual(frequency_report(self.target, word='novel')['physical_occurrences'], 2)

    def test_chunk_only_revision_preserves_exact_en_cn_and_updates_both_hosts(self):
        request = self.sentence_request(shifted=False)
        amend_sentence(self.target, **request)
        self.assert_hosts('新原句和chunk逐处复核')
        with c.connect(self.target, readonly=True) as db:
            for (rid,) in db.execute('select record_id from analyses'):
                row = c.get_json(db, rid)['occurrences'][0]
                self.assertEqual(row['english'], request['expected_source']['english'])
                self.assertEqual(row['translation'], request['expected_source']['translation'])
                self.assertNotEqual(row['alignment'], request['expected_source']['alignment'])

    def test_incomplete_stale_scope_and_unsubstantiated_dictionary_revision_make_no_changes(self):
        request = self.dictionary_request()
        request['expected'].pop('two/two-novel')
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'incomplete cross-book'):
            amend_dictionary_sense(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), original)
        request = self.dictionary_request()
        request['evidence']['quoted_definition'] = 'an invented non-source meaning'
        with self.assertRaisesRegex(ValueError, 'absent from exact dictionary'):
            amend_dictionary_sense(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), original)
        request = self.sentence_request()
        request['occurrence_reviews']['two/two-novel'].pop(next(iter(request['occurrence_reviews']['two/two-novel'])))
        with self.assertRaisesRegex(ValueError, 'every physical token'):
            amend_sentence(self.target, **request)
        self.assertEqual(c.logical_digest(self.target), original)

    def test_late_compile_failure_reverts_all_current_rows_projections_versions_and_audits(self):
        with c.connect(self.target) as db:
            key = db.execute("select component_id from note_fields where book_id='two' and name='Definition'").fetchone()[0]
            db.execute('update components set current_id=%s where id=%s', (c.put_object(db, b'broken source'), key))
        original = c.logical_digest(self.target)
        with self.assertRaisesRegex(ValueError, 'complete live physical articles'):
            amend_sentence(self.target, **self.sentence_request())
        self.assertEqual(c.logical_digest(self.target), original)


class SourceRevisionDisplayProofTests(unittest.TestCase):
    def amended_transfer(self):
        from tests import test_study_catalog_ownership as ownership_tests
        from anki_pipeline import sense_display as sd
        from anki_pipeline.study_catalog_ownership import _reseal
        from anki_pipeline.study_catalog_content import SOURCE_REVISION_KEYS, _prepare, _restore_sense_indexes
        _, draft = ownership_tests.TransferredDisplayProofTests().transfer_fixture()
        before = _reseal(draft)
        draft = deepcopy(before); _restore_sense_indexes(draft)
        original = before['occurrences'][0]; row = draft['occurrences'][0]
        row['alignment']['alignments'] = [
            {'en': [2, 7], 'zh': [[6, 8]], 'relation': 'equivalent'},
            {'en': [19, 24], 'zh': [[2, 4]], 'relation': 'equivalent'}]
        row['reason'] = '转归以后重新核实完整chunk'
        row['method'] = 'shared-catalog-source-review.v1'
        display = row['display']
        display['provenance']['raw_context_hash'] = sd._raw_context_hash(row)
        display['alignment'] = sd._project_alignment(row, display['english'], display['translation'],
            display['alignment_sources'], sentence_fallback=bool(display['provenance'].get('alignment_projection')))
        display.pop('display_hash')
        display['display_hash'] = sd._sha(sd._json(display))
        proof = {'schema': 'study-catalog-reviewed-source-revision.v1',
            'book_id': before['book_id'], 'card_id': before['card_id'], 'word': before['word'],
            'before_record': before, 'before_row': original,
            'after_source': {key: deepcopy(row.get(key)) for key in SOURCE_REVISION_KEYS},
            'reason': '经完整来源核对后修订chunk',
            'evidence': {'expected_source': _source(original), 'new_source': _source(row),
                'token_review': {'expected': _row_review(original), 'new': _row_review(row)}}}
        proof['revision_sha256'] = sd._sha(sd._json(proof))
        row['semantic_review'].setdefault('catalog_source_revisions', []).append(proof)
        return before, draft, _prepare

    def test_transferred_display_accepts_explicit_later_source_revision_and_subsequent_decision(self):
        before, draft, prepare = self.amended_transfer()
        after = prepare(draft)
        self.assertNotEqual(after['occurrences'][0]['alignment'], before['occurrences'][0]['alignment'])
        self.assertEqual(after['occurrences'][0]['display']['provenance']['source_card_sha256'],
                         before['occurrences'][0]['display']['provenance']['source_card_sha256'])
        later = deepcopy(after)
        from anki_pipeline.study_catalog_content import _restore_sense_indexes
        _restore_sense_indexes(later)
        later['occurrences'][0]['reason'] = '后续再核实细分义项'
        self.assertEqual(prepare(later)['occurrences'][0]['reason'], '后续再核实细分义项')

    def test_rebound_source_revision_proof_is_rejected_even_after_digest_is_recomputed(self):
        _, draft, prepare = self.amended_transfer()
        proof = draft['occurrences'][0]['semantic_review']['catalog_source_revisions'][-1]
        proof['evidence']['new_source']['translation'] = '伪造旧转归来源'
        proof.pop('revision_sha256')
        proof['revision_sha256'] = hashlib.sha256(c.canonical(proof).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'replacement evidence'):
            prepare(draft)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'), 'requires isolated PostgreSQL test connection')
class SourceRevisionOwnershipIntegrationTests(unittest.TestCase):
    def test_twenty_two_committed_source_amendments_keep_counts_and_linear_offline_history(self):
        from tests import test_study_catalog_ownership as ownership_tests
        from anki_pipeline import sense_display as sd
        from anki_pipeline.study_catalog_ownership import transfer_occurrence
        fixture = ownership_tests.OwnershipRevisionTests()
        fixture.setUp(); self.addCleanup(fixture.tearDown)
        transfer_occurrence(fixture.target, **fixture.request())
        physical = fixture.records[('one','train')]['occurrences'][0]['physical_source']
        paper = fixture.records[('one','train')]['occurrences'][0]['paper_id']
        record_sizes = []; html_sizes = []
        for index in range(22):
            scoped = {}
            with c.connect(fixture.target, readonly=True) as db:
                for book, card, rid in db.execute('select book_id,source_card_id,record_id from analyses'):
                    record = c.get_json(db,rid)
                    if any(row['physical_source']==physical for row in record['occurrences']):
                        scoped[book+'/'+card] = (rid,record)
            original = next(row for _,record in scoped.values() for row in record['occurrences'] if row['physical_source']==physical)
            new_source = _source(original)
            new_source['alignment']['alignments'][0] = ({'en':[0,14],'zh':[[0,4]],'relation':'equivalent'}
                if index%2==0 else {'en':[6,14],'zh':[[2,4]],'relation':'equivalent'})
            reviews = {}
            for key, (_,record) in scoped.items():
                old = next(row for row in record['occurrences'] if row['physical_source']==physical)
                row = deepcopy(old); row.update(deepcopy(new_source)); row['reason']='第'+str(index+1)+'次逐处核对chunk'
                display = row['display']
                display['provenance']['raw_context_hash'] = sd._raw_context_hash(row)
                display['alignment'] = sd._project_alignment(row,display['english'],display['translation'],display['alignment_sources'])
                display.pop('display_hash'); display['display_hash']=sd._sha(sd._json(display))
                reviews[key] = {old['occurrence_id']:{'expected':_row_review(old),'new':_row_review(row)}}
            amend_sentence(fixture.target,paper_id=paper,physical_source=physical,expected_source=_source(original),
                new_source=new_source,occurrence_reviews=reviews,expected={key:rid for key,(rid,_) in scoped.items()},
                reason='第'+str(index+1)+'次完整来源chunk核订',backups=fixture.root/'backups')
            with c.connect(fixture.target,readonly=True) as db:
                rid=db.execute("select record_id from analyses where book_id='one' and source_card_id='one-training'").fetchone()[0]
                record=c.get_json(db,rid)
                nid=db.execute("select note_id from notes where book_id='one' and source_card_id='one-training'").fetchone()[0]
                note=project_note(db,project_book(db,'one'),nid)
                definition=note['fields'][note['field_names'].index('Definition')]
            record_sizes.append(len(c.canonical(record).encode()));html_sizes.append(len(definition.encode()))
        current=next(row for row in record['occurrences'] if row['physical_source']==physical)
        self.assertEqual(len(current['semantic_review']['catalog_source_revision_chain']['steps']),22)
        self.assertEqual(frequency_report(fixture.target,word='training')['physical_occurrences'],2)
        self.assertEqual(len(list((fixture.root/'backups').glob('*.pg.jsonl.gz'))),23)
        for sizes in (record_sizes,html_sizes):
            self.assertLess(sizes[-1]-sizes[0],21*(sizes[1]-sizes[0])*1.4)

    def test_transfer_then_full_source_revision_preserves_display_page_chain_and_native_jumps(self):
        from tests import test_study_catalog_ownership as ownership_tests
        from anki_pipeline import sense_display as sd
        from anki_pipeline.study_catalog_ownership import transfer_occurrence
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        fixture = ownership_tests.OwnershipRevisionTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        transfer_occurrence(fixture.target, **fixture.request())
        physical = fixture.records[('one', 'train')]['occurrences'][0]['physical_source']
        records = {}
        with c.connect(fixture.target, readonly=True) as db:
            for book, card, rid in db.execute('select book_id,source_card_id,record_id from analyses'):
                record = c.get_json(db, rid)
                if any(row['physical_source'] == physical for row in record['occurrences']):
                    records[book+'/'+card] = (rid, record)
        first = next(row for _, record in records.values() for row in record['occurrences'] if row['physical_source'] == physical)
        old_source = _source(first); new_source = deepcopy(old_source)
        new_source['english'] = 'Indeed, ' + old_source['english']
        new_source['translation'] = '的确，' + old_source['translation']
        new_source['source_provenance']['reviewedContentHash'] = hashlib.sha256(b'new reviewed source').hexdigest()
        new_source['alignment']['englishHash'] = hashlib.sha256(new_source['english'].encode()).hexdigest()
        new_source['alignment']['translationHash'] = hashlib.sha256(new_source['translation'].encode()).hexdigest()
        for part in new_source['alignment']['alignments']:
            part['en'] = [value+8 for value in part['en']]
            part['zh'] = [[value+3 for value in span] for span in part['zh']]
        reviews = {}
        for key, (_, record) in records.items():
            reviews[key] = {}
            for original in record['occurrences']:
                if original['physical_source'] != physical:
                    continue
                row = deepcopy(original); row.update(deepcopy(new_source))
                row['english_hash'] = new_source['alignment']['englishHash']
                row['translation_hash'] = new_source['alignment']['translationHash']
                row['target_range'] = [v+8 for v in original['target_range']]
                row['translation_ranges'] = [[v+3 for v in span] for span in original['translation_ranges']]
                row['reason'] = '转归后新原句的名词用法及完整chunk复核'
                display = row['display']
                display.update(english=row['english'], translation=row['translation'],
                    english_hash=row['english_hash'], translation_hash=row['translation_hash'],
                    target_range=row['target_range'])
                provenance = display['provenance']
                provenance.update(physical_target_range=row['target_range'], english_hash=row['english_hash'],
                    translation_hash=row['translation_hash'], raw_context_hash=sd._raw_context_hash(row))
                display['alignment'] = sd._project_alignment(row, display['english'], display['translation'], display['alignment_sources'])
                jump = provenance['native_jump']
                parsed = urlsplit(jump['native_jump'])
                replacements = {'anki-codex-hash': row['english_hash'],
                    'anki-codex-review': row['source_provenance']['reviewedContentHash'],
                    'anki-codex-en': json.dumps([row['target_range']])}
                query = [(k, replacements.get(k, v)) for k, v in parse_qsl(parsed.query)]
                jump.update(english_hash=row['english_hash'], reviewed_content_hash=row['source_provenance']['reviewedContentHash'],
                    target_ranges=[row['target_range']], native_jump=urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)))
                display.pop('display_hash')
                display['display_hash'] = sd._sha(sd._json(display))
                reviews[key][original['occurrence_id']] = {'expected': _row_review(original), 'new': _row_review(row)}
        result = amend_sentence(fixture.target, paper_id=first['paper_id'], physical_source=physical,
            expected_source=old_source, new_source=new_source, occurrence_reviews=reviews,
            expected={key: rid for key, (rid, _) in records.items()}, reason='完整原卷及双语chunk核订', backups=fixture.root/'backups')
        self.assertEqual(len(result['changes']), 2)
        self.assertEqual(frequency_report(fixture.target, word='training')['physical_occurrences'], 2)
        for book in ('one', 'two', 'future'):
            with c.connect(fixture.target, readonly=True) as db:
                nid = db.execute("select note_id from notes where book_id=%s and source_card_id=%s", (book, book+'-training' if book!='future' else 'one-training')).fetchone()
                if nid is None:
                    nid = db.execute('select note_id from notes where book_id=%s and word_id=%s', (book, c.identity('word', 'en', 'training'))).fetchone()
                note = project_note(db, project_book(db, book), nid[0])
                fields = dict(zip(note['field_names'], note['fields']))
            self.assertIn('Indeed, Model ', fields['Examples'])
            self.assertIn(new_source['alignment']['englishHash'], fields['Examples'])
            self.assertIn('catalog_source_revision_chain', fields['Definition'])
            self.assertIn('完整原记录与转归证据', fields['Definition'])


class CandidateScopeContentRevisionTests(unittest.TestCase):
    def test_revised_record_keeps_exact_exclusions_and_complete_reconstructible_ledger(self):
        from tests.test_sense_candidate_scope import scope_fixture
        from anki_pipeline.study_catalog_content import _prepare, _restore_sense_indexes
        from anki_pipeline.sense_candidate_scope import validate_stored_scope
        with tempfile.TemporaryDirectory() as directory:
            raw, scope = scope_fixture(directory)
            raw['candidate_scope'] = scope
            before = sf.prepare_record(raw)
            draft = deepcopy(before); _restore_sense_indexes(draft)
            draft['occurrences'][0]['reason'] = '总库后续修订，全部原排除仍然保留'
            after = _prepare(draft)
            self.assertEqual(after['expected_occurrences'], before['expected_occurrences'])
            self.assertEqual(after['candidate_scope']['excluded'], before['candidate_scope']['excluded'])
            self.assertNotEqual(after['snapshot_id'], before['snapshot_id'])
            self.assertEqual(validate_stored_scope(after['candidate_source_record'], after['candidate_scope']),
                             after['candidate_scope'])

    def test_original_candidate_indices_survive_sha_reordering_and_explicit_span_revision(self):
        from tests import test_sense_candidate_scope as fixtures
        from anki_pipeline.study_catalog_content import _prepare, _restore_sense_indexes
        from anki_pipeline import sense_display as sd
        from unittest.mock import patch
        import types
        code = fixtures.candidate_fixture.__code__
        shifted = types.FunctionType(code.replace(co_consts=tuple(2010 if value==2019 else value for value in code.co_consts)),
            fixtures.candidate_fixture.__globals__)
        shifted.__kwdefaults__ = fixtures.candidate_fixture.__kwdefaults__
        for edit_span in (False, True):
            with self.subTest(edit_span=edit_span), tempfile.TemporaryDirectory() as directory:
                with patch.object(fixtures,'candidate_fixture',shifted):
                    raw,scope = fixtures.scope_fixture(directory)
                raw['candidate_scope'] = scope
                before = sf.prepare_record(raw)
                wanted = {entry['original_index']:before['candidate_source_record']['occurrences'][entry['candidate_index']]['paper_id']
                    for entry in before['candidate_scope']['retained_map']}
                self.assertEqual(wanted,{0:'kaoyan:2010-01',2:'kaoyan:2012-01',4:'kaoyan:2014-01'})
                draft=deepcopy(before);_restore_sense_indexes(draft)
                row=draft['occurrences'][0];row['reason']='只改本条，原始索引不能调换'
                if edit_span:
                    row['english']='Now '+row['english'];row['target_range']=[v+4 for v in row['target_range']]
                    row['english_hash']=hashlib.sha256(row['english'].encode()).hexdigest()
                    if row.get('display'):
                        display=row['display'];display['english']=row['english'];display['english_hash']=row['english_hash']
                        display['target_range']=row['target_range']
                        display['alignment']['englishHash']=row['english_hash']
                        display['provenance'].update(physical_target_range=row['target_range'],english_hash=row['english_hash'],raw_context_hash=sd._raw_context_hash(row))
                        display.pop('display_hash');display['display_hash']=sd._sha(sd._json(display))
                after=_prepare(draft)
                actual={entry['original_index']:after['candidate_source_record']['occurrences'][entry['candidate_index']]['paper_id']
                    for entry in after['candidate_scope']['retained_map']}
                self.assertEqual(actual,wanted)
                self.assertEqual(after['candidate_scope']['excluded'],before['candidate_scope']['excluded'])


class NativeSourcePresentationTests(unittest.TestCase):
    def test_paragraph_translation_label_and_line_breaks_are_source_bound_and_revised(self):
        from tests.test_sense_frequency import aligned_record
        from anki_pipeline.study_catalog_content import _examples, _native_text
        from anki_pipeline import study_catalog_revision as rev
        row = deepcopy(aligned_record()['occurrences'][0])
        row['english'] += '\nMore context.'
        row['translation'] += '更多上下文。'
        row['english_hash'] = row['alignment']['englishHash'] = hashlib.sha256(row['english'].encode()).hexdigest()
        row['alignment']['translationHash'] = hashlib.sha256(row['translation'].encode()).hexdigest()
        after = deepcopy(row)
        after['english'] = 'Indeed, ' + row['english']
        after['translation'] = '的确，' + row['translation']
        after['target_range'] = [v+8 for v in row['target_range']]
        after['alignment']['englishHash'] = hashlib.sha256(after['english'].encode()).hexdigest()
        after['alignment']['translationHash'] = hashlib.sha256(after['translation'].encode()).hexdigest()
        for part in after['alignment']['alignments']:
            part['en'] = [v+8 for v in part['en']]
            part['zh'] = [[v+3 for v in span] for span in part['zh']]
        source = ('<li class="example-card"><span class="example-text">'
            + row['english'].replace('\n', '<br>') + '</span><span class="example-translation">'
            '<span class="translate-tag">段落译文</span> ' + row['translation'] + '</span></li>')
        result = _examples(source, [(row, after)], '核订段落原文')
        en = rev._nodes(result, 'example-text')[0]
        zh = rev._nodes(result, 'example-translation')[0]
        self.assertEqual(_native_text(result, en), after['english'])
        self.assertEqual(_native_text(result, zh, translation=True), after['translation'])
        self.assertIn('段落译文', result)
        self.assertIn('本句完整修订记录', result)

    def test_native_example_without_translation_span_receives_reviewed_text_and_chunks(self):
        from anki_pipeline.study_catalog_content import _examples, _native_text
        from anki_pipeline import study_catalog_revision as rev
        english = 'Use a novel.'
        before = {'english': english, 'translation': '', 'target_range': [6, 11],
            'sentence_id': 'kaoyan:2024-01:p:block:0', 'english_hash': hashlib.sha256(english.encode()).hexdigest(),
            'source_provenance': {'reviewedContentHash': hashlib.sha256(b'old').hexdigest()}}
        after = deepcopy(before); after['translation'] = '使用一本小说。'
        after['alignment'] = {'schema': 'codex-sentence-alignment.v1',
            'englishHash': before['english_hash'], 'translationHash': hashlib.sha256(after['translation'].encode()).hexdigest(),
            'alignments': [{'en': [6, 11], 'zh': [[4, 6]], 'relation': 'equivalent'}]}
        raw = '<li class="example-card"><span class="example-text">Use a novel.</span></li>'
        result = _examples(raw, [(before, after)], '核订新增的准确译文')
        zh = rev._nodes(result, 'example-translation')[0]
        self.assertEqual(_native_text(result, zh, translation=True), after['translation'])
        self.assertIn('card-chunk', result)

    def test_bound_native_example_with_unreconciled_translation_is_rejected(self):
        from anki_pipeline.study_catalog_content import _examples
        before = {'english': 'Model training.', 'translation': '模型训练。'}
        raw = ('<li class="example-card"><span class="example-text">Model training.</span>'
            '<span class="example-translation"><span class="translate-tag">翻译</span> 未核对的另一译文</span></li>')
        with self.assertRaisesRegex(ValueError, 'translation differs'):
            _examples(raw, [(before, deepcopy(before))], '不能静默留下旧文本')

    def same_text_sources(self, *, other_translation='火车到了。'):
        from tests.test_sense_display import source, occurrence, native_example
        items = [source('kaoyan:'+year+'-01:p:x:0', 'A train arrives.', translation,
            [{'en':[2,7], 'zh':[[0,2]], 'relation':'equivalent'}])
            for year, translation in (('2012','火车到了。'), ('2021',other_translation))]
        rows = [occurrence(item,[2,7]) for item in items]
        for row in rows:
            row['paper_id'] = row['sentence_id'].split(':p:')[0]
        after = deepcopy(rows[0]);after['english'] = 'Indeed, ' + after['english'];after['target_range'] = [10,15]
        after['translation'] = '的确，火车到了。'
        after['english_hash'] = after['alignment']['englishHash'] = hashlib.sha256(after['english'].encode()).hexdigest()
        after['source_provenance']['reviewedContentHash'] = hashlib.sha256(b'new source').hexdigest()
        after['alignment']['translationHash'] = hashlib.sha256(after['translation'].encode()).hexdigest()
        after['alignment']['alignments'] = [{'en':[10,15], 'zh':[[3,5]], 'relation':'equivalent'}]
        native = [native_example(item, item['english'], item['translationZh'], [[2,7]]) for item in items]
        return rows, after, native

    def test_identical_bilingual_examples_from_other_exams_are_not_revised(self):
        from anki_pipeline.study_catalog_content import _examples
        rows, after, native = self.same_text_sources()
        revised = _examples(''.join(native), [(rows[0],after)], '只校订2012来源', known_occurrences=rows)
        self.assertIn(native[1], revised)
        from anki_pipeline.study_catalog_content import _native_text
        from anki_pipeline import study_catalog_revision as rev
        active = rev._nodes(revised, 'example-text')
        self.assertEqual([_native_text(revised, node) for node in active], [after['english'], rows[1]['english']])

        self.assertIn(after['english_hash'], revised)
        # The other source's full URL, year and old source hash are byte intact.
        self.assertTrue(revised.endswith(native[1]))

    def test_same_english_but_distinct_translation_bound_to_other_source_stays_intact(self):
        from anki_pipeline.study_catalog_content import _examples
        rows, after, native = self.same_text_sources(other_translation='列车已经抵达。')
        revised = _examples(''.join(native), [(rows[0],after)], '只校订2012来源', known_occurrences=rows)
        self.assertTrue(revised.endswith(native[1]))

    def test_identical_unbound_examples_from_multiple_sources_are_rejected(self):
        from anki_pipeline.study_catalog_content import _examples
        rows, after, native = self.same_text_sources()
        raw = re.sub(r'<a class="sentence-jump"[^>]*></a>', '', ''.join(native))
        with self.assertRaisesRegex(ValueError, 'ambiguous physical sources'):
            _examples(raw, [(rows[0],after)], '无绑定不能猜来源', known_occurrences=rows)

    def test_same_source_with_stale_hash_review_or_range_is_rejected(self):
        from anki_pipeline.study_catalog_content import _examples
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
        from html import escape, unescape
        rows, after, native = self.same_text_sources()
        href = unescape(re.search(r'href="([^"]+)"', native[0]).group(1))
        parsed = urlsplit(href)
        for key, value in (('anki-codex-hash', '0'*64), ('anki-codex-review', '0'*64), ('anki-codex-en', '[[0,1]]')):
            with self.subTest(stale=key):
                query = [(k, value if k==key else v) for k, v in parse_qsl(parsed.query)]
                revised = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
                raw = native[0].replace(escape(href, quote=True), escape(revised, quote=True))
                with self.assertRaisesRegex(ValueError, 'stale hash, review or target'):
                    _examples(raw, [(rows[0],after)], '不能跳过同源损坏绑定', known_occurrences=rows)


class LongSourceRevisionChainTests(unittest.TestCase):
    def test_twenty_five_source_revisions_are_iterative_complete_and_near_linear(self):
        from tests import test_study_catalog_ownership as ownership_tests
        from anki_pipeline import sense_display as sd
        from anki_pipeline import study_catalog_revision as rev
        from anki_pipeline.native_example_usage import _Offsets
        from anki_pipeline.study_catalog_ownership import _reseal
        from anki_pipeline.study_catalog_content import (_prepare, _restore_sense_indexes,
            _append_source_chain, _replace_pair, repartition_definition)
        _, draft = ownership_tests.TransferredDisplayProofTests().transfer_fixture()
        before = _reseal(draft)
        definition = sf.render_report(sf.report_from_record(before))
        record_sizes = []; html_sizes = []
        for index in range(25):
            original = before['occurrences'][0]
            draft = deepcopy(before); _restore_sense_indexes(draft)
            row = draft['occurrences'][0]
            row['alignment']['alignments'][0] = ({'en':[2,7], 'zh':[[6,8]], 'relation':'equivalent'}
                if index % 2 == 0 else {'en':[0,12], 'zh':[[6,10]], 'relation':'equivalent'})
            row['reason'] = '第'+str(index+1)+'次明确核对原chunk'
            display = row['display']
            display['provenance']['raw_context_hash'] = sd._raw_context_hash(row)
            display['alignment'] = sd._project_alignment(row, display['english'], display['translation'],
                display['alignment_sources'], sentence_fallback=bool(display['provenance'].get('alignment_projection')))
            display.pop('display_hash')
            display['display_hash'] = sd._sha(sd._json(display))
            review = {'expected': _row_review(original), 'new': _row_review(row)}
            semantic = row['semantic_review']
            semantic['catalog_source_revision_chain'] = _append_source_chain(before, original, _source(row), review, row['reason'])
            semantic.pop('catalog_source_revisions', None)
            semantic.pop('catalog_ownership_transfers', None)
            after = _prepare(draft)
            article = source_articles(definition, before)[original['occurrence_id']]
            revised = _replace_pair(article, original, after['occurrences'][0], row['reason'])
            definition = repartition_definition(definition, before, after,
                {after['occurrences'][0]['occurrence_id']: revised})
            record_sizes.append(len(c.canonical(after).encode()))
            html_sizes.append(len(definition.encode()))
            before = after
        chain = before['occurrences'][0]['semantic_review']['catalog_source_revision_chain']
        self.assertEqual(len(chain['steps']), 25)
        self.assertIn('catalog_ownership_transfers', c.canonical(chain['base_record']))
        self.assertEqual(sum('sf-catalog-source-chain' in n.classes for n in _Offsets(definition, {}).root.walk()), 1)
        self.assertEqual(sum('sf-example' in n.classes for n in _Offsets(definition, {}).root.walk()), 1)
        self.growth_evidence = {'iterations': 25,
            'samples': [{'revision': index+1, 'record_bytes': record_sizes[index], 'definition_bytes': html_sizes[index]}
                        for index in (0, 4, 9, 19, 24)],
            'record_increment_first': record_sizes[1]-record_sizes[0],
            'definition_increment_first': html_sizes[1]-html_sizes[0]}
        for sizes in (record_sizes, html_sizes):
            self.assertLess(sizes[-1]-sizes[0], 24*(sizes[1]-sizes[0])*1.4)
        # A caller cannot edit a former step and simply recompute its outer
        # digest: all later exact previous-step and source bindings still hold.
        corrupt = deepcopy(before)
        root = corrupt['occurrences'][0]['semantic_review']['catalog_source_revision_chain']
        root['steps'][4]['new_source']['translation'] = '伪造前步的源译文'
        root['steps'][4].pop('step_sha256')
        root['steps'][4]['step_sha256'] = hashlib.sha256(c.canonical(root['steps'][4]).encode()).hexdigest()
        root.pop('chain_sha256')
        root['chain_sha256'] = hashlib.sha256(c.canonical(root).encode()).hexdigest()
        _restore_sense_indexes(corrupt)
        with self.assertRaises(ValueError):
            _prepare(corrupt)
