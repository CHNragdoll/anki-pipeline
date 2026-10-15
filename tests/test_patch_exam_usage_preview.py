"""Focused owner-recovery data boundaries, using only detached/temp data."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from scripts import patch_exam_usage_preview as patcher
from scripts import update_exam_usage_preview as preview
from tests.test_sense_frequency import record, completed_record


class OwnerPatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.target = sf.prepare_record(record())
        self.source = deepcopy(self.target)
        self.source.update(card_id='wrong-owner', word='novelty')
        self.row = deepcopy(self.target['occurrences'][0])
        self.row.update(status='unmatched', sense_id=None, reviewed_sense_id=None,
                        assignment_context_hash=None, reason='完整原错归依据')
        self.source['occurrences'] = [self.row]
        self.source['expected_occurrences'] = 1
        self.exclusion = {'occurrence_id': self.row['occurrence_id'], 'occurrence': self.row,
            'exclusion_kind': 'wrong_lemma', 'authority': {'frozen_complete_source': True}}
        self.ledger = {'excluded': [self.exclusion]}
        self.case = {'book_id': self.source['book_id'], 'source_card_id': self.source['card_id'],
            'source_word': self.source['word'], 'source_occurrence_id': self.row['occurrence_id'],
            'source_parent_snapshot_id': self.source['snapshot_id'], 'source_parent_row': self.row,
            'source_exclusion': self.exclusion, 'scope_ledger_sha256': preview.digest(self.ledger)}
        row = self.target['occurrences'][0]
        sense = next(s for s in self.target['senses'] if s['sense_id'] == row['sense_id'])
        self.decision = {'input_id': preview.digest(self.case), 'source_record_sha256': preview.digest(self.row),
            'action': 'bind_existing', 'book_id': self.source['book_id'], 'source_card_id': self.source['card_id'],
            'source_occurrence_id': self.row['occurrence_id'], 'source_parent_snapshot_id': self.source['snapshot_id'],
            'target': {'card_id': self.target['card_id'], 'word': self.target['word'],
                'parent_snapshot_id': self.target['snapshot_id'], 'definition_snapshot_id': self.target['definition_snapshot_id'],
                'occurrence_id': row['occurrence_id'], 'target_range': row['target_range'],
                'translation_ranges': row['translation_ranges'], 'sense_id': row['sense_id'],
                'ordinal': sense['ordinal'], 'pos': sense['pos'], 'text': sense['text'], 'reason': row['reason'],
                'dictionary_source': self.target['definition_source'],
                'source_provenance': {'snapshot_id': self.target['snapshot_id']}, 'target_row': deepcopy(row)},
            'dictionary_evidence': {'actual_headword': 'novel', 'reviewed': True},
            'physical_proof': {'same_physical_exact_span': True}, 'rationale': '逐源核实的目标义项',
            'review_version': 'owner-recovery.v1'}

    @unittest.skipUnless(sys.platform == 'darwin', 'actual APFS clonefile requires macOS; production forbids copy fallback')
    def test_apfs_clone_is_independent_and_preserves_the_complete_source_bytes(self):
        source = self.root / 'base.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE proof (value TEXT)'); db.execute("INSERT INTO proof VALUES('original')"); db.commit()
        original = source.read_bytes()
        target = self.root / 'working.sqlite3'
        proof = patcher.clone_working_copy({'file': str(source), 'sha256': preview.file_sha(source)}, target)
        self.assertEqual(target.read_bytes(), original)
        self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)
        with closing(sqlite3.connect(target)) as db:
            db.execute("UPDATE proof SET value='new work'"); db.commit()
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(proof['clone_method'], 'apfs_clonefile')
        with self.assertRaises(FileExistsError):
            patcher.clone_working_copy({'file': str(source), 'sha256': preview.file_sha(source)}, target)

    def test_non_macos_clone_is_rejected_before_ffi_or_destination_write(self):
        source = self.root / 'base.sqlite3'
        with closing(sqlite3.connect(source)) as db:
            db.execute('CREATE TABLE proof(value TEXT)')
            db.execute("INSERT INTO proof VALUES('original')")
            db.commit()
        original = source.read_bytes()
        target = self.root / 'forbidden-copy.sqlite3'
        with patch.object(patcher.sys, 'platform', 'linux'), \
                patch.object(patcher.ctypes, 'CDLL') as library:
            with self.assertRaisesRegex(ValueError, 'macOS APFS clonefile'):
                patcher.clone_working_copy({'file': str(source), 'sha256': preview.file_sha(source)}, target)
            library.assert_not_called()
        self.assertFalse(target.exists())
        self.assertEqual(source.read_bytes(), original)

    def test_existing_owner_decision_requires_exact_original_and_current_reviewed_row(self):
        patcher.validate_decision(self.case, self.decision, self.source, self.ledger, self.target)
        for field in ('reason', 'assignment_context_hash', 'english', 'translation'):
            invalid = deepcopy(self.decision); invalid['target']['target_row'][field] = 'forged'
            with self.subTest(field=field), self.assertRaises(ValueError):
                patcher.validate_decision(self.case, invalid, self.source, self.ledger, self.target)

    def test_new_owner_row_keeps_raw_source_and_counts_each_canonical_owner_once(self):
        target = deepcopy(self.target)
        target['occurrences'] = target['occurrences'][1:]; target['expected_occurrences'] = len(target['occurrences'])
        item = deepcopy(self.decision); item['action'] = 'append_owner_row'; item['target'].pop('target_row')
        item['target']['parent_snapshot_id'] = target['snapshot_id']
        result = patcher.add_approved_owner_rows(target, [(self.case, item), (self.case, deepcopy(item))])
        self.assertEqual(result['expected_occurrences'], target['expected_occurrences'] + 1)
        row = next(r for r in result['occurrences'] if r['occurrence_id'] == self.row['occurrence_id'])
        for field in ('english', 'translation', 'english_hash', 'translation_hash', 'alignment', 'physical_source', 'source_provenance'):
            self.assertEqual(row[field], self.row[field])
        self.assertEqual(row['status'], 'reviewed')
        self.assertEqual(row['sense_id'], item['target']['sense_id'])
        self.assertNotEqual(row['assignment_context_hash'], self.row['assignment_context_hash'])

    def test_contradictory_owner_meanings_for_one_physical_row_are_rejected(self):
        target = deepcopy(self.target); target['occurrences'] = []; target['expected_occurrences'] = 0
        first = deepcopy(self.decision); first['action'] = 'append_owner_row'; first['target'].pop('target_row')
        other = deepcopy(first); sense = next(s for s in self.target['senses']
                                               if s['sense_id'] != first['target']['sense_id'])
        other['target'].update(sense_id=sense['sense_id'], ordinal=sense['ordinal'], pos=sense['pos'], text=sense['text'])
        with self.assertRaises(ValueError):
            patcher.add_approved_owner_rows(target, [(self.case, first), (self.case, other)])

    def test_cross_card_display_requires_explicit_replayed_projection_and_keeps_chunks(self):
        before = sf.prepare_record(completed_record())
        original = before['occurrences'][0]
        target = deepcopy(before)
        target['definition_provenance']['page_sha256'] = 'f' * 64
        owner = deepcopy(original)
        owner['target_range'] = before['occurrences'][1]['target_range']
        decision = {'input_id': 'a'*64, 'source_record_sha256': preview.digest(original), 'physical_proof': {}}
        with self.assertRaises(ValueError):
            patcher.sense_display.validate_display(original['display'], owner, target['definition_provenance'])
        result = patcher.project_owner_display(original, owner, target, decision)
        self.assertEqual(result['target_range'], owner['target_range'])
        for field in ('english','translation','alignment','alignment_sources','derivation_payload'):
            self.assertEqual(result[field], original['display'][field])
        self.assertEqual(result['provenance']['owner_transfer_projection']['original_source_provenance'], original['display']['provenance'])
        invalid = deepcopy(original); invalid['display']['derivation_payload'] = {}
        invalid['display'].pop('display_hash'); invalid['display']['display_hash'] = sf._sha(sf._json(invalid['display']))
        with self.assertRaises((ValueError, KeyError)):
            patcher.project_owner_display(invalid, owner, target, decision)

    def test_original_paper_jump_uses_approved_raw_owner_span_not_completed_display(self):
        row = deepcopy(self.row); row['source_provenance']['reviewedContentHash'] = 'b'*64
        result = patcher.original_paper_jump(row, [19,24], 'http://localhost:8765')
        from urllib.parse import urlsplit, parse_qs
        query = parse_qs(urlsplit(result['full_paper_url']).query)
        self.assertEqual(json.loads(query['anki-codex-en'][0]), [[19,24]])
        self.assertEqual(query['anki-codex-sentence'][0], row['sentence_id'])
        self.assertEqual(query['anki-codex-hash'][0], row['english_hash'])
        for url in ('javascript:alert(1)', 'http://user:password@localhost:8765'):
            with self.assertRaises(ValueError): patcher.original_paper_jump(row, [19,24], url)

    def _native_owner_fixture(self, *, old_history=False):
        """A real retained native sentence plus an independently sealed SF row."""
        from tests.test_ownership_history import fixture
        from tests.test_sense_frequency import aligned_record
        from tests.test_sense_display import native_example
        from anki_pipeline.ownership_history import bind_incoming_history
        target = sf.prepare_record(aligned_record())
        target, first = fixture(target)
        transfers = [first]
        if old_history:
            second = deepcopy(first)
            second_row = target['occurrences'][1]
            second_source = deepcopy(second_row)
            second_source.update(status='unmatched', sense_id=None, reviewed_sense_id=None,
                assignment_context_hash=None, reason='第二条完整旧依据')
            decision = deepcopy(first['exclusion_authority']['legacy_projection_proof']['decision'])
            decision.update(occurrence_id=second_row['occurrence_id'],
                decision_after={'status':'unmatched', 'reason':second_source['reason']})
            sense = next(s for s in target['senses'] if s['sense_id'] == second_row['sense_id'])
            second.update(source_parent_row=second_source,
                exclusion_authority={'parent_snapshot_id':'parent-snapshot',
                    'decision_sha256':preview.digest(decision),
                    'legacy_projection_proof':{'decision':decision, 'occurrence':second_source}},
                source_identity={k:deepcopy(second_source[k]) for k in patcher.history._IDENTITY_FIELDS},
                target_occurrence_id=second_row['occurrence_id'], target_range=second_row['target_range'],
                target_reason=second_row['reason'],
                matched_sense={**sense, 'dictionary_source':'oxford',
                    'source_provenance':{'snapshot_id':target['snapshot_id'],'entry':'novel'}})
            transfers.append(second)
        after = sf.prepare_record(patcher.producer_record(bind_incoming_history(target, transfers), preserve_scope=False))
        before_record = patcher.producer_record(after, preserve_scope=False)
        before_record['occurrences'] = before_record['occurrences'][1:]
        before_record['expected_occurrences'] = 1
        before = sf.prepare_record(before_record)
        retained = before['occurrences'][0]
        item = {'id':retained['sentence_id'], 'english':retained['english'],
            'translationZh':retained['translation'], 'englishHash':retained['english_hash'],
            'reviewedContentHash':retained['source_provenance']['reviewedContentHash']}
        page = '<!--original--><ol>' + native_example(item, item['english'], item['translationZh'],
            [retained['target_range']]) + '</ol><!--end-->'
        return before, after, page

    def _native_owner_render(self, before, after, page):
        from anki_pipeline.native_example_usage import update_native_examples
        native_after, inventory = patcher._native_owner_projection(before, after, {}, {})
        native = update_native_examples(page, before, native_after, defer_ownership_coverage=True)
        coverage = patcher._complete_native_owner_coverage(native, after, inventory)
        final = native['page'] + sf.render_report(sf.report_from_record(after))
        proof = patcher.history.validate_rendered_history_coverage(final, after, coverage,
            ownership_history_documents={}, target_urls={})
        return native_after, native, coverage, final, proof

    def test_new_owner_sf_row_does_not_fabricate_native_li_and_full_history_is_covered(self):
        from anki_pipeline.native_example_usage import update_native_examples, restore_original
        from anki_pipeline.sense_chunks import render_sentence_pair
        before, after, page = self._native_owner_fixture()
        original = deepcopy((before, after))
        with self.assertRaisesRegex(ValueError, 'preserve each retained physical row'):
            update_native_examples(page, before, after, defer_ownership_coverage=True)
        projection, native, coverage, final, proof = self._native_owner_render(before, after, page)
        added = after['occurrences'][0]
        self.assertEqual(len(projection['occurrences']), 1)
        self.assertEqual(projection['occurrences'][0], after['occurrences'][1])
        self.assertEqual(projection['expected_occurrences'], 1)
        self.assertNotEqual(projection['snapshot_id'], after['snapshot_id'])
        self.assertEqual(coverage['snapshot_id'], after['snapshot_id'])
        self.assertEqual(set(coverage['deferred']), {added['occurrence_id']})
        self.assertEqual(coverage['native'], {})
        self.assertEqual(native['stats']['native_examples'], 1)
        self.assertEqual(proof['sf_only_histories'], 1)
        self.assertEqual(proof['sf_histories'], 1)
        self.assertIn(render_sentence_pair(added), final)
        self.assertIn('完整旧错归解释\n第二段理由', final)
        self.assertIn('card-chunk', final)
        report = sf.render_report(sf.report_from_record(after))
        self.assertTrue(final.endswith(report))
        self.assertEqual(restore_original(final[:-len(report)], native['inverse']), page)
        self.assertEqual((before, after), original)

    def test_native_owner_projection_preserves_old_history_and_immutable_physical_guard(self):
        from anki_pipeline.native_example_usage import update_native_examples
        before, after, page = self._native_owner_fixture(old_history=True)
        _, native, coverage, _, proof = self._native_owner_render(before, after, page)
        self.assertEqual(proof['sf_histories'], 2)
        self.assertEqual(proof['native_histories'], 1)
        self.assertEqual(proof['sf_only_histories'], 1)
        self.assertEqual(set(coverage['native']), {before['occurrences'][0]['occurrence_id']})
        self.assertIn('第二条完整旧依据', native['page'])
        for field, value in [('translation', '伪造原译文'), ('physical_source', ['foreign']),
                             ('source_provenance', {'reviewedContentHash':'foreign'}),
                             ('alignment', {'foreign':True})]:
            invalid = deepcopy(after)
            invalid['occurrences'][1][field] = value
            if field == 'translation': invalid['occurrences'][1]['translation_hash'] = sf._sha(value)
            invalid.pop('snapshot_id'); invalid['snapshot_id'] = preview.digest(invalid)
            with self.subTest(field=field), self.assertRaises(ValueError):
                projected, _ = patcher._native_owner_projection(before, invalid, {}, {})
                update_native_examples(page, before, projected, defer_ownership_coverage=True)
        invalid = deepcopy(after)
        invalid['occurrences'][1]['ownership_history'] = []
        invalid.pop('snapshot_id'); invalid['snapshot_id'] = preview.digest(invalid)
        with self.assertRaisesRegex(ValueError, 'immutable ownership history'):
            projected, _ = patcher._native_owner_projection(before, invalid, {}, {})
            update_native_examples(page, before, projected, defer_ownership_coverage=True)

    def test_deferred_owner_requires_complete_current_sf_sentence_and_explanation(self):
        before, after, page = self._native_owner_fixture()
        _, native, coverage, final, _ = self._native_owner_render(before, after, page)
        invalid = [native['page'], final.replace('完整旧错归解释', '说明已删除'),
            final.replace('data-snapshot="' + after['snapshot_id'] + '"', 'data-snapshot="wrong"')]
        for candidate in invalid:
            with self.subTest(page_sha256=sf._sha(candidate)), self.assertRaises(ValueError):
                patcher.history.validate_rendered_history_coverage(candidate, after, coverage,
                    ownership_history_documents={}, target_urls={})
        forged = deepcopy(coverage); forged['deferred'] = {}
        forged.pop('coverage_sha256'); forged['coverage_sha256'] = preview.digest(forged)
        with self.assertRaisesRegex(ValueError, 'inventory differs'):
            patcher.history.validate_rendered_history_coverage(final, after, forged,
                ownership_history_documents={}, target_urls={})

    def _licensed_native_history_fixture(self):
        """A hyphen spelling licensed by actual bytes in a detached dictionary."""
        source = deepcopy(self.row)
        source.update(english='Their lay-off was temporary.', translation='他们的下岗是暂时的。',
            target_range=[6,9], source_provenance={'reviewedContentHash':'a'*64})
        source['english_hash'] = sf._sha(source['english'])
        source['translation_hash'] = sf._sha(source['translation'])
        source['occurrence_id'] = sf._sha(sf._json([source['paper_id'],source['physical_source'],source['target_range']]))
        producer = record(); producer.update(word='layoff', definition_provenance={'entry':'layoff'},
            senses=[{'pos':'n.','text':'解雇'}], expected_occurrences=1)
        owner = deepcopy(source); owner.update(target_range=[6,13], status='reviewed', sense_index=0,
            reason='真实名词 lay-off，指暂时下岗',method='owner-review',review_version='v5')
        for key in ('occurrence_id','sense_id','reviewed_sense_id','assignment_context_hash'):owner.pop(key,None)
        producer['occurrences'] = [sf.seal_reviewed_assignment(producer,owner)]
        target = sf.prepare_record(producer); row = target['occurrences'][0]; sense = target['senses'][0]
        dictionary = self.root/'hyphen-dictionary.sqlite3'
        header='<h1>layoff</h1><span>noun (also lay-off)</span>'; block='<p>解雇</p>';raw=header+block
        with closing(sqlite3.connect(dictionary))as db:
            db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY,headword TEXT,html TEXT,sha256 TEXT)')
            db.execute('INSERT INTO entries VALUES(1,?,?,?)',('layoff',raw,sf._sha(raw)));db.commit()
        native_source={'db_path':str(dictionary),'source_entry_id':1,'headword':'layoff','raw_html':raw,'raw_sha256':sf._sha(raw)}
        definition={'source_headword':'layoff','part_of_speech':'noun','header_html':header,'html':block,
            'source_ref':{'source_entry_id':1,'raw_sha256':sf._sha(raw),'source_headword':'layoff',
                'part_of_speech':'noun','definition_html_sha256':sf._sha(block)}}
        audit={'book_id':target['book_id'],'card_id':'wrong-owner','after_snapshot_id':'source-parent',
            'occurrence_id':source['occurrence_id'],'decision_after':{'status':'unmatched','reason':source['reason']}}
        authority={'parent_snapshot_id':'source-parent','decision_sha256':preview.digest(audit),
            'legacy_projection_proof':{'decision':audit,'occurrence':source}}
        decision={'input_id':'e'*64,'source_record_sha256':preview.digest(source),'action':'append_owner_row',
            'book_id':target['book_id'],'source_card_id':'wrong-owner','source_occurrence_id':source['occurrence_id'],
            'source_parent_snapshot_id':'source-parent','target':{'card_id':target['card_id'],'word':'layoff',
                'occurrence_id':row['occurrence_id'],'target_range':row['target_range'],
                'sense_id':sense['sense_id'],'ordinal':sense['ordinal'],'pos':sense['pos'],'text':sense['text'],
                'dictionary_source':target['definition_source']},'dictionary_evidence':{
                'native_source':native_source,'native_definition':definition,'explicit_variant_bridge':{
                    'canonical_headword':'layoff','printed_variant':'lay-off','native_header_html':header,
                    'source_ref':definition['source_ref'],'part_of_speech':'noun'}}}
        h={'schema':patcher.history.SCHEMA,'book_id':target['book_id'],'source_card_id':'wrong-owner',
            'source_word':'lie','source_parent_snapshot_id':'source-parent','source_parent_row':source,
            'exclusion_authority':authority,'target_card_id':target['card_id'],'target_occurrence_id':row['occurrence_id'],
            'target_word':'layoff','target_range':row['target_range'],'target_reason':row['reason'],
            'source_identity':{k:deepcopy(source[k])for k in patcher.history._IDENTITY_FIELDS},
            'matched_sense':{**sense,'dictionary_source':target['definition_source'],
                'source_provenance':{'snapshot_id':target['snapshot_id'],'entry':'layoff'}},
            'verified_physical_match':True,'match_kind':'licensed_native_owner_variant',
            'owner_recovery_decision':decision}
        h['history_id']=sf._sha(sf._json([h['book_id'],h['source_card_id'],h['source_parent_snapshot_id'],source,
            authority,h['target_card_id'],h['target_occurrence_id']]))
        h['content_sha256']=patcher.history._content_sha256(h)
        row['ownership_history']=[h];target.pop('snapshot_id');target['snapshot_id']=preview.digest(target)
        return target,row,h

    def test_native_licensed_history_replays_actual_dictionary_and_preserves_sealed_evidence(self):
        from anki_pipeline.native_example_usage import _native_histories, _rows
        target,row,h=self._licensed_native_history_fixture();original=deepcopy(target)
        markup,pins=_native_histories(target,_rows(target),documents={},target_urls={})
        self.assertIn('完整原错归依据',markup[row['occurrence_id']])
        self.assertEqual(pins[row['occurrence_id']],[{'history_id':h['history_id'],'content_sha256':h['content_sha256']}])
        self.assertEqual(target,original)
        for mutate in [lambda d:d['target'].update(card_id='another-card'),
                lambda d:d['target'].update(ordinal=999),
                lambda d:d['dictionary_evidence']['native_source'].update(source_entry_id=999),
                lambda d:d['dictionary_evidence']['explicit_variant_bridge'].update(native_header_html='invented lay-off')]:
            bad=deepcopy(target);history=bad['occurrences'][0]['ownership_history'][0]
            mutate(history['owner_recovery_decision']);history['content_sha256']=patcher.history._content_sha256(history)
            bad.pop('snapshot_id');bad['snapshot_id']=preview.digest(bad)
            with self.assertRaises(ValueError):_native_histories(bad,_rows(bad),documents={},target_urls={})
        # A re-sealed author assertion still cannot replace the native entry.
        path=Path(h['owner_recovery_decision']['dictionary_evidence']['native_source']['db_path'])
        with closing(sqlite3.connect(path))as db:
            db.execute("UPDATE entries SET headword='lay someone off'");db.commit()
        with self.assertRaises(ValueError):_native_histories(target,_rows(target),documents={},target_urls={})

    def _transaction_fixture(self):
        from tests.test_ownership_history import fixture
        target, transfer = fixture()
        producer = patcher.producer_record(target, preserve_scope=False)
        producer['card_id'] = transfer['source_card_id']; producer['word'] = transfer['source_word']
        producer['occurrences'] = [transfer['source_parent_row']]; producer['expected_occurrences'] = 1
        source = sf.prepare_record(producer)
        source_row = source['occurrences'][0]
        audit = {'book_id': source['book_id'], 'card_id': source['card_id'], 'after_snapshot_id':source['snapshot_id'],
            'occurrence_id': source_row['occurrence_id'], 'decision_after':{'status':'unmatched','reason':source_row['reason']}}
        authority = {'parent_snapshot_id': source['snapshot_id'], 'decision_sha256':preview.digest(audit),
            'legacy_projection_proof':{'decision':audit,'occurrence':deepcopy(source_row)}}
        exclusion = {'occurrence_id':source_row['occurrence_id'], 'occurrence':source_row,
            'exclusion_kind':'wrong_lemma','authority':authority}
        ledger = {'excluded':[exclusion]}
        case = {**self.case, 'source_parent_row':source_row, 'source_parent_snapshot_id':source['snapshot_id'],
            'source_card_id':source['card_id'], 'source_word':source['word'],
            'source_occurrence_id':source_row['occurrence_id'],'source_exclusion':exclusion,'scope_ledger_sha256':preview.digest(ledger)}
        row = next(r for r in target['occurrences'] if r['occurrence_id']==source_row['occurrence_id'])
        sense = next(s for s in target['senses'] if s['sense_id']==row['sense_id'])
        decision = {**deepcopy(self.decision), 'input_id':preview.digest(case),'source_record_sha256':preview.digest(source_row),
            'source_card_id':source['card_id'],
            'source_parent_snapshot_id':source['snapshot_id'],'source_occurrence_id':source_row['occurrence_id'],
            'target': {**deepcopy(self.decision['target']), 'parent_snapshot_id':target['snapshot_id'],
                'definition_snapshot_id':target['definition_snapshot_id'], 'occurrence_id':row['occurrence_id'],
                'target_range':row['target_range'],'translation_ranges':row['translation_ranges'],'sense_id':sense['sense_id'],
                'ordinal':sense['ordinal'],'pos':sense['pos'],'text':sense['text'],'reason':row['reason'],
                'source_provenance':{'snapshot_id':target['snapshot_id'],'entry':'novel'},'target_row':row}}
        source_path = self.root/'certified.sqlite3'; base_run={'unchanged_base_evidence':'original'}; run_id=preview.digest(base_run)
        raw=''; metadata={'id':source['card_id'],'word':source['word'],'previewUrl':'/source.html'}
        doc=preview._history_document(source['word'],source['snapshot_id'],metadata['previewUrl'],raw)
        with closing(sqlite3.connect(source_path)) as db:
            db.executescript(sf._SQL); db.executescript(preview._LEDGER_SQL)
            preview.insert_prepared(db, source); preview.insert_prepared(db, target)
            db.execute('INSERT INTO exam_usage_update_runs VALUES(?,?,?)',(run_id,preview.digest(base_run),preview.canonical(base_run)))
            for data, scope in ((source,ledger),(target,{'excluded':[]})):
                db.execute('INSERT INTO exam_usage_parent_snapshots VALUES(?,?,?,?,?,?,?,?,?)',
                    (run_id,data['book_id'],data['card_id'],data['snapshot_id'],data['snapshot_id'],preview.digest(data),'',preview.digest(scope),preview.canonical(scope)))
            db.execute('INSERT INTO exam_usage_history_documents VALUES(?,?,?,?,?,?,?,?)',
                (run_id,source['book_id'],source['card_id'],source['snapshot_id'],metadata['previewUrl'],'0'*64,sf._sha(doc),raw)); db.commit()
        base={'run_id':run_id,'run':base_run,'database':preview._checked_database_hash(source_path),'word_cards':2}
        request={'scope':'v5-owner-recovery','new_database':str(self.root/'working.sqlite3'), 'base_checkpoint':{},'code_pins':{},'decisions':[],
            'expected_source_cases':1,'expected_added_occurrences':0,'expected_bound_histories':1,'expected_retained_unresolved':0,'expected_affected_cards':1}
        original={'web_root':str(self.root),'books':[{'book_id':target['book_id'],'output':str(self.root/'full')} ]}
        source_bytes=source_path.read_bytes()
        return base,request,original,case,decision,metadata,source_bytes

    def _prepare_test(self, data, *, input_check=None):
        base,request,original,case,decision,metadata,_=data
        with patch.object(patcher,'_load_request',return_value=(self.root/'request.json',request,base,original)), \
             patch.object(patcher,'load_reviewed_decisions',return_value=([(case,decision,{'actual_input':'fixture'})],{})), \
             patch.object(preview,'load_catalog',return_value=(None,None,None,{'cards':[metadata]})), \
             patch.object(patcher,'_patch_inputs',side_effect=input_check):
            return patcher.prepare_patch(self.root/'request.json','a'*64)

    @unittest.skipUnless(sys.platform == 'darwin', 'actual owner-recovery transaction uses mandatory APFS clonefile')
    def test_single_delta_transaction_preserves_base_and_resolves_original_parent(self):
        data=self._transaction_fixture(); base,request,*_=data
        pin=self._prepare_test(data); checkpoint=json.loads(Path(pin['file']).read_text())
        self.assertEqual(checkpoint['bound_histories'],1); self.assertEqual(checkpoint['added_occurrences'],0)
        self.assertEqual(Path(base['database']['file']).read_bytes(),data[-1])
        with closing(preview._ro(Path(request['new_database']))) as db:
            before,ledger,after=patcher.resolve_prepared(db,base['run_id'],checkpoint['run_id'],self.target['book_id'],self.target['card_id'])
            self.assertEqual(before['snapshot_id'],data[4]['target']['parent_snapshot_id'])
            self.assertEqual(after['expected_occurrences'],before['expected_occurrences'])
            self.assertEqual(sum(len(r.get('ownership_history',[]))for r in after['occurrences']),1)
            self.assertEqual(db.execute('SELECT count(*) FROM exam_usage_parent_snapshots').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM exam_usage_owner_patch_cards').fetchone()[0],1)
            self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())

    @unittest.skipUnless(sys.platform == 'darwin', 'actual owner-recovery transaction uses mandatory APFS clonefile')
    def test_late_input_failure_discards_only_uncertified_clone_and_all_delta_writes(self):
        data=self._transaction_fixture(); base,request,*_=data
        with self.assertRaisesRegex(ValueError,'late source tamper'):
            self._prepare_test(data,input_check=ValueError('late source tamper'))
        self.assertFalse(Path(request['new_database']).exists())
        self.assertFalse(Path(request['new_database']+'.prepared.json').exists())
        self.assertEqual(Path(base['database']['file']).read_bytes(),data[-1])

    @unittest.skipUnless(sys.platform == 'darwin', 'actual owner-recovery transaction uses mandatory APFS clonefile')
    def test_midtransaction_failure_rolls_back_delta_ddl_run_and_snapshot(self):
        data=self._transaction_fixture(); base,request,*_=data
        observed=[]; original=patcher._discard_uncertified_clone
        def observe_then_discard(database,inode):
            with closing(preview._ro(Path(database)))as db:
                observed.append((db.execute("SELECT count(*) FROM sqlite_master WHERE name LIKE 'exam_usage_owner_patch_%'").fetchone()[0],
                    db.execute('SELECT count(*) FROM snapshots').fetchone()[0],db.execute('SELECT count(*) FROM exam_usage_parent_snapshots').fetchone()[0]))
            original(database,inode)
        with patch.object(patcher,'bind_recovery_histories',side_effect=ValueError('inside delta transaction')), \
             patch.object(patcher,'_discard_uncertified_clone',side_effect=observe_then_discard):
            with self.assertRaisesRegex(ValueError,'inside delta transaction'): self._prepare_test(data)
        self.assertEqual(observed,[(0,2,2)])
        self.assertFalse(Path(request['new_database']).exists())
        self.assertEqual(Path(base['database']['file']).read_bytes(),data[-1])

    @unittest.skipUnless(sys.platform == 'darwin', 'actual owner-recovery transaction uses mandatory APFS clonefile')
    def test_render_failure_retains_certified_clone_and_readonly_resume_does_not_prepare(self):
        data=self._transaction_fixture(); base,request,original,*_=data
        pin=self._prepare_test(data); checkpoint=json.loads(Path(pin['file']).read_text())
        unchanged=Path(request['new_database']).read_bytes()
        with patch.object(patcher,'_load_request',return_value=(self.root/'request.json',request,base,original)), \
             patch.object(preview,'load_catalog',side_effect=ValueError('actual render boundary failure')), \
             patch.object(patcher,'clone_working_copy',side_effect=AssertionError('must not clone on resume')):
            with self.assertRaisesRegex(ValueError,'actual render boundary failure'):
                patcher.render_patch(pin)
        self.assertEqual(Path(request['new_database']).read_bytes(),unchanged)
        self.assertTrue(Path(pin['file']).exists())
        failure=list(self.root.glob('working.sqlite3.render-failure-*.json'))
        self.assertEqual(len(failure),1)
        receipt=json.loads(failure[0].read_text())
        self.assertTrue(receipt['database_retained']);self.assertTrue(receipt['database_stat_matches_checkpoint'])
        self.assertEqual(receipt['run_id'],checkpoint['run_id'])

    def test_card_proof_seals_materialized_utf8_bytes_and_refuses_overwrite(self):
        path=self.root/'actual.html'; proof={};content='<p>完整原文\r\n释义</p>'
        patcher._write_card(path,content,proof)
        self.assertEqual(proof['after_sha256'],preview.file_sha(path))
        self.assertEqual(path.read_bytes(),content.encode())
        with self.assertRaises(FileExistsError):patcher._write_card(path,'overwrite',{})

    def test_owner_jump_ignores_completed_display_coordinate_and_rejects_forged_raw_range(self):
        row=deepcopy(self.row);row['source_provenance']['reviewedContentHash']='b'*64
        decision=deepcopy(self.decision);decision['target']['target_range']=row['target_range'];decision['target']['occurrence_id']=row['occurrence_id']
        row['display']={'target_range':[99,105]}
        row['ownership_history']=[{'source_parent_row':deepcopy(row),'owner_recovery_decision':decision}]
        data={**self.target,'occurrences':[row]}
        from urllib.parse import urlsplit,parse_qs
        jump=patcher._source_jumps(data,'http://localhost:8765')[row['occurrence_id']]
        self.assertEqual(json.loads(parse_qs(urlsplit(jump['full_paper_url']).query)['anki-codex-en'][0]),[row['target_range']])
        row['ownership_history'][0]['owner_recovery_decision']['physical_proof']['canonical_full_target_range']=[99,105]
        with self.assertRaises(ValueError):patcher._source_jumps(data,'http://localhost:8765')

    def test_native_lexical_permission_requires_real_entry_and_exact_definition(self):
        path=self.root/'dictionary.sqlite3';header='<h1>layoff</h1><span>noun (also lay-off)</span>';block='<p>解雇</p>'
        raw=header+block
        with closing(sqlite3.connect(path))as db:
            db.execute('CREATE TABLE entries(id INTEGER PRIMARY KEY,headword TEXT,html TEXT,sha256 TEXT)')
            db.execute('INSERT INTO entries VALUES(1,?,?,?)',('layoff',raw,sf._sha(raw)));db.commit()
        source={'db_path':str(path),'source_entry_id':1,'headword':'layoff','raw_html':raw,'raw_sha256':sf._sha(raw)}
        definition={'source_headword':'layoff','part_of_speech':'noun','header_html':header,'html':block,
            'source_ref':{'source_entry_id':1,'raw_sha256':sf._sha(raw),'source_headword':'layoff','part_of_speech':'noun','definition_html_sha256':sf._sha(block)}}
        self.assertEqual(patcher._verified_native_entry(source,definition),(header,block))
        for field,value in [('source_entry_id',99),('headword','lay someone off'),('raw_html','layoff lay-off')]:
            bad={**source,field:value}
            with self.assertRaises(ValueError):patcher._verified_native_entry(bad,definition)
        bad=deepcopy(definition);bad['header_html']='<h1>layoff lay-off invented permission</h1>'
        with self.assertRaises(ValueError):patcher._verified_native_entry(source,bad)

    def test_will_requires_complete_native_negative_contraction_not_past_won(self):
        raw="<table><tr>will not</tr><tr>won't</tr></table>"
        entry={'provider':'oxford','archive_source':'oald10','source_entry_id':280089,'raw_sha256':sf._sha(raw)}
        native={'source_headword':'will','part_of_speech':'modal verb','context_id':'will_3','source_entry':entry,
            'forms_source_range':[0,len(raw)],'forms_native_html':raw,'forms_native_html_sha256':sf._sha(raw),'forms':[]}
        for kind,text in [('neg','will not'),('short',"won't")]:
            html='<tr>'+text+'</tr>';a=raw.index(html)
            native['forms'].append({'kind':kind,'text':text,'source_range':[a,a+len(html)],'native_html':html,'native_html_sha256':sf._sha(html)})
        path=self.root/'native.json';path.write_text(preview.canonical({'raw_html':raw,'negative':native}))
        pin={'file':str(path),'sha256':preview.file_sha(path)}
        evidence={'negative_contraction_evidence':native,'source_entry':entry,
            'negative_contraction_proof_ref':{**pin,'json_pointer':'/negative'},'native_raw_entry_ref':{**pin,'json_pointer':'/raw_html','content_sha256':sf._sha(raw)}}
        source=deepcopy(self.row);source['english']="They won't leave.";source['english_hash']=sf._sha(source['english']);source['target_range']=[5,8]
        owner=deepcopy(source);owner['target_range']=[5,10]
        target={'word':'will','senses':[{'pos':'modal v.'}]}; decision={'target':{'ordinal':0},'dictionary_evidence':evidence}
        self.assertEqual(patcher._licensed_span(target,source,owner,decision,source_word='win'),'licensed_will_negative_contraction')
        for changed in ({**owner,'target_range':[5,8]}, {**owner,'target_range':[6,10]}, {**owner,'english':'They won a prize.','english_hash':sf._sha('They won a prize.')}):
            with self.assertRaises(ValueError):patcher._licensed_span(target,source,changed,decision,source_word='win')
        for wrong in ('won','other-card',None):
            with self.assertRaises(ValueError):patcher._licensed_span(target,source,owner,decision,source_word=wrong)
        broken=deepcopy(decision);broken['dictionary_evidence']['negative_contraction_evidence']['forms'][0]['native_html']='invented'
        with self.assertRaises(ValueError):patcher._licensed_span(target,source,owner,broken,source_word='win')


if __name__ == '__main__':
    unittest.main()
