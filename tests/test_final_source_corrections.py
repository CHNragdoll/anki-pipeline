"""Real transactions against isolated five-case fixtures, never study data."""
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import final_source_corrections as fs
from anki_pipeline import source_confirmations as sc, sense_frequency as sf

SPECS = {
    'be': ('be', 'Which of the following measures would be the Productivity Commission support?',
           'Which of the following measures would the Productivity Commission support?', [38, 40], None),
    'prompted': ('promote', 'What promoted the chancellor to develop his scheme?',
                 'What prompted the chancellor to develop his scheme?', [5, 13], [5, 13]),
    'data': ('date', 'The product they’re selling is data, and we, the users, convert our lives to date for the benefit of the digital giants.',
             'The product they’re selling is data, and we, the users, convert our lives to data for the benefit of the digital giants.', [77, 81], [77, 81]),
    'deep-rooted': ('root', 'a deep-root belief.', 'a deep-rooted belief.', [7, 11], [2, 13]),
    'teeming': ('team', 'We can offer them a visit to Blackwater National Wildlife Refuge in Dorchester County where bald eagles fly over tidal marshes so shallow you could not paddle a boat across them but teaming with aquatic life.',
                'We can offer them a visit to Blackwater National Wildlife Refuge in Dorchester County where bald eagles fly over tidal marshes so shallow you could not paddle a boat across them but teeming with aquatic life.', [182, 189], [182, 189]),
}
SIDS = {'be': 'kaoyan:2022-01:p:b-10-6:new:1', 'prompted': 'kaoyan:2014-01:p:b-4-5:new:1',
        'data': 'kaoyan:2018-02:p:b-7-5:0', 'deep-rooted': 'kaoyan:2021-01:q-34-1:A:new:0',
        'teeming': 'kaoyan:2024-01:p:b-9-6:1'}


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.protected = self.root / 'protected.sqlite3'
        self.database = self.root / 'candidate.sqlite3'
        self.records = []
        self.confirmations = {}
        self.revisions = []
        targets = []
        for key, (word, old, new, span, target) in SPECS.items():
            original = json.loads((Path(__file__).resolve().parents[1] / 'docs/evidence' /
                                   ('source-confirmation-' + key + '-20261014.json')).read_text())
            self.confirmations[key] = self.pin(key + '.json', original)
            old_record = self.index(key, old)
            new_record = self.index(key, new)
            self.revisions.append({'caseKey': key, 'paperId': old_record['paperId'],
                'sentenceId': SIDS[key], 'paragraphId': old_record['paragraphId'],
                'oldRecord': old_record, 'newRecord': new_record,
                'oldStructuredPaperHash': 'c' * 64, 'newStructuredPaperHash': 'd' * 64,
                'paragraphAffectedRecords': [{'oldRecord': old_record, 'newRecord': new_record}]})
            for book in ('redbook', 'redbook2027'):
                self.records.append(self.record(book, word, [(key, span)]))
                if key == 'deep-rooted':
                    self.records.append(self.record(book, 'deep', [(key, [2, 6])]))
                if target is not None:
                    lemma = {'prompted': 'prompt', 'data': 'data', 'deep-rooted': 'deep-rooted', 'teeming': 'teem'}[key]
                    created = key in ('deep-rooted', 'teeming')
                    if not created:
                        occurrences = [(key, [31, 35])] if key == 'data' else []
                        self.records.append(self.record(book, lemma, occurrences))
                    evidence = self.pin(key + '-native.json', {'english': 'native full definition', 'chinese': '词典原译'})
                    targets.append({'case_key': key, 'book_id': book, 'card_id': book + '-' + lemma,
                        'word': lemma, 'kind': 'supplemental' if created else 'existing',
                        'sense_ordinal': 0, 'target_range': target, 'translation_ranges': [[0, 2]],
                        'definition_source': 'fixture-native', 'definition_provenance': {'source': 'fixture', 'headword': lemma,
                            'native_english': 'native full definition', 'native_chinese': '词典原译'},
                        'senses': [{'pos': 'adj.' if lemma == 'deep-rooted' else 'v.' if lemma != 'data' else 'n.', 'text': '词典原译'}],
                        'native_sense': {'original_english': 'native full definition', 'original_chinese': '词典原译'},
                        'evidence_pins': [evidence]})
        for book in ('redbook', 'redbook2027'):
            self.records.append(self.record(book, 'sibling', [(k, [0, 1]) for k in SPECS]))
        sf.save_records(self.protected, self.records, self.root / 'backup')
        shutil.copyfile(self.protected, self.database)
        self.original_protected = self.protected.read_bytes()
        with closing(sqlite3.connect(self.database)) as db:
            active = {(r[0], r[1]): r[2] for r in db.execute('SELECT * FROM active_snapshots')}
        for target in targets:
            if target['kind'] == 'existing':
                target['snapshot_id'] = active[(target['book_id'], target['card_id'])]
        self.request = {'schema': fs.REQUEST, 'candidate': {'file': str(self.database), 'stat': sc.stat_pin(self.database)},
            'protected': {'file': str(self.protected), 'stat': sc.stat_pin(self.protected)},
            'confirmations': self.confirmations, 'expected_books': ['redbook', 'redbook2027'],
            'targets': self.pin('targets.json', {'schema': 'final-source-targets.v1', 'targets': targets}),
            'source_revisions': self.pin('revisions.json', {'schema': 'confirmed-reader-source-revisions.v1', 'records': self.revisions})}
        live=self.pin('reader-live.json',{'reader':'current'});other=self.pin('reader-code.json',{'code':'fixed'})
        source_revision=self.request['source_revisions']
        review=self.pin('reader-review.json',{'schema':'confirmed-reader-freeze.v1',
            'files':[{'absolutePath':p['file'],'afterSha256':p['sha256']} for p in [live,other]],
            'database':{'path':str(self.protected),'afterSha256':sc.digest(self.original_protected)},
            'receipts':{'source-revisions.json':source_revision}})
        completion=self.pin('reader-completion.json',{'schema':'confirmed-reader-completion.v1',
            'allAppliedFileHashesVerified':True,'regeneratedJsonAndTexExactlyMatchLive':True,
            'databaseAfterSha256':sc.digest(self.original_protected),
            'receipts':{'source-revisions.json':source_revision,'review-inputs.json':review}})
        self.request['expected_reader_files']=2
        self.request['reader_binding']={'review_inputs':review,'completion_receipt':completion,'database_stat':sc.stat_pin(self.protected)}

    def pin(self, name, value):
        path = self.root / name
        if not path.exists():
            path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
        return {'file': str(path), 'sha256': sc.digest(path.read_bytes())}

    def index(self, key, english):
        span = [0, 1]
        alignments = [{'en': span, 'zh': [[0, 2]], 'relation': 'equivalent'}]
        if key != 'be':
            target = SPECS[key][4] if english == SPECS[key][2] else SPECS[key][3]
            alignments.append({'en': target, 'zh': [[0, 2]], 'relation': 'equivalent'})
        if key == 'data':
            alignments.append({'en': [31, 35], 'zh': [[0, 2]], 'relation': 'equivalent'})
        return {'id': SIDS[key], 'paperId': ':'.join(SIDS[key].split(':')[:2]),
            'paragraphId': SIDS[key].rsplit(':new:', 1)[0].rsplit(':', 1)[0] if ':new:' not in SIDS[key] else SIDS[key].split(':new:')[0],
            'english': english, 'englishHash': sf._sha(english), 'translationZh': '原译', 'translationHash': sf._sha('原译'),
            'alignments': alignments, 'start': 0, 'end': len(english), 'sourceHash': sf._sha(english),
            'reviewedContentHash': sf._sha('原译' + '\0' + json.dumps(alignments, ensure_ascii=False, separators=(',', ':')))}

    def record(self, book, word, specs):
        record = {'book_id': book, 'card_id': book + '-' + word, 'word': word,
            'definition_source': 'fixture-native', 'definition_provenance': {'source': 'fixture', 'headword': word},
            'senses': [{'pos': 'v.', 'text': '词典原译'}], 'expected_occurrences': len(specs), 'occurrences': []}
        for key, span in specs:
            source = self.index(key, SPECS[key][1])
            alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': source['englishHash'],
                'translationHash': source['translationHash'], 'alignments': source['alignments']}
            row = {'paper_id': source['paperId'], 'sentence_id': source['id'], 'physical_source': [source['id']],
                'english': source['english'], 'english_hash': source['englishHash'], 'translation': '原译',
                'target_range': span, 'translation_ranges': [[0, 2]], 'alignment': alignment, 'alignment_evidence': [],
                'source': '完整原来源', 'source_provenance': {'paragraphId': source['paragraphId'],
                    'paragraphRange': [0, len(source['english'])], 'reviewedContentHash': source['reviewedContentHash'],
                    'sourceHash': source['sourceHash'], 'sourcePathEvidence': {'structuredPaperHash': 'c' * 64}},
                'status': 'reviewed', 'sense_index': 0, 'reason': '完整旧解释\n不得丢失', 'method': 'fixture', 'review_version': 'fixture'}
            record['occurrences'].append(sf.seal_reviewed_assignment(record, row))
        return record

    def graph(self):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute('SELECT * FROM active_snapshots ORDER BY book_id,card_id').fetchall()


class FinalSourceTests(unittest.TestCase):
    def plan(self, fixture):
        scope = fs.inspect_scope(fixture.request)
        fixture.request['scope'] = fixture.pin('scope.json', scope)
        return fs.prepare(fixture.request)

    def test_five_corrections_preserve_full_history_and_data_positions(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            plan = self.plan(f)
            self.assertEqual(plan['summary']['physical_count_delta_by_book'], {'redbook': -2, 'redbook2027': -2})
            self.assertEqual(sum(c['created'] for c in plan['cards']), 4)
            for book in ('redbook', 'redbook2027'):
                data = next(c['payload'] for c in plan['cards'] if c['book_id'] == book and c['word'] == 'data')
                self.assertEqual([r['target_range'] for r in sorted(data['occurrences'], key=lambda r:r['target_range'])], [[31,35],[77,81]])
                be = next(c['payload'] for c in plan['cards'] if c['book_id'] == book and c['word'] == 'be')
                self.assertEqual(be['expected_occurrences'], 0)
                removed = be['exam_usage_policy']['final_source_corrections']['removed_rows']
                self.assertIn('完整旧解释', removed[0]['original_row']['reason'])
                compound = next(c['payload'] for c in plan['cards'] if c['book_id'] == book and c['word'] == 'deep-rooted')
                self.assertEqual(compound['occurrences'][0]['target_range'], [2,13])
                self.assertIn('完整旧解释', compound['occurrences'][0]['source_provenance']['source_confirmation']['original_row']['reason'])
            self.assertEqual(f.protected.read_bytes(), f.original_protected)

    def test_atomic_failure_idempotence_created_target_rollback_and_readback(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root);plan=self.plan(f);before=f.graph()
            with self.assertRaisesRegex(RuntimeError,'injected'):
                fs.apply(plan, root_write_approved=True, fail_after_cards=3)
            self.assertEqual(f.graph(),before)
            plan['candidate_stat']=sc.stat_pin(f.database);plan['run_id']=sc.digest({k:v for k,v in plan.items() if k!='run_id'})
            fs.apply(plan,root_write_approved=True)
            self.assertTrue(fs.apply(plan,root_write_approved=True)['already_applied'])
            for card in plan['cards']:
                with closing(sc._connect(f.database)) as db:
                    sc.ro._reconcile(db,card['payload'])
            fs.rollback(plan,root_write_approved=True)
            self.assertTrue(fs.rollback(plan,root_write_approved=True)['already_rolled_back'])
            self.assertEqual(f.graph(),before)
            self.assertEqual(f.protected.read_bytes(),f.original_protected)

    def test_resealed_unrelated_content_tamper_and_later_graph_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root);plan=self.plan(f)
            card=next(c for c in plan['cards'] if c['word']=='sibling')
            card['payload']['occurrences'][0]['translation']='坏'
            card['payload']['snapshot_id']=sc.digest({k:v for k,v in card['payload'].items() if k!='snapshot_id'})
            card['child_snapshot_id']=card['payload']['snapshot_id'];card['payload_sha256']=sc.digest(card['payload'])
            plan['run_id']=sc.digest({k:v for k,v in plan.items() if k!='run_id'})
            with self.assertRaises(ValueError):fs.apply(plan,root_write_approved=True)

    def test_protected_inode_and_changed_pinned_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root)
            alias=Path(root)/'alias.sqlite3';os.link(f.protected,alias)
            request=deepcopy(f.request);request['candidate']['file']=str(alias)
            with self.assertRaisesRegex(ValueError,'inode alias'):fs.inspect_scope(request)
            plan=self.plan(f)
            Path(f.request['source_revisions']['file']).write_text('{}')
            with self.assertRaisesRegex(ValueError,'pinned source changed'):fs.apply(plan,root_write_approved=True)

    def test_rollback_refuses_later_active_graph_and_normalized_sql_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root);plan=self.plan(f);fs.apply(plan,root_write_approved=True)
            card=next(c for c in plan['cards'] if not c['created'])
            with closing(sqlite3.connect(f.database)) as db:
                db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',
                    (card['parent_snapshot_id'],card['book_id'],card['card_id']));db.commit()
            with self.assertRaisesRegex(ValueError,'later graph'):fs.rollback(plan,root_write_approved=True)

    def test_scratch_rehearsal_checks_full_created_and_recovery_records(self):
        from scripts import apply_final_source_corrections as driver
        fs.OWNED.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=fs.OWNED) as root:
            f=Fixture(root);plan=self.plan(f)
            receipt=driver.rehearse(plan,Path(root)/'rehearsal')
            self.assertTrue(receipt['injected_failure_atomic'])
            self.assertTrue(receipt['apply_idempotent'])
            self.assertTrue(receipt['rollback_idempotent'])
            self.assertTrue(receipt['full_child_payload_readback_exact'])
            self.assertEqual(f.protected.read_bytes(),f.original_protected)

    def test_third_book_shared_sentence_is_excluded_in_memory(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root)
            memory=sqlite3.connect(':memory:');memory.row_factory=sqlite3.Row
            with closing(sqlite3.connect(f.database)) as source:source.backup(memory)
            foreign=sf.prepare_record(f.record('unrelated-book','foreign', [('teeming',[0,1])]))
            sc.ro._insert(memory,foreign)
            memory.execute('INSERT INTO active_snapshots VALUES(?,?,?)',('unrelated-book','unrelated-book-foreign',foreign['snapshot_id']));memory.commit()
            with patch.object(sc,'_connect',return_value=memory):scope=fs.inspect_scope(f.request)
            self.assertNotIn('unrelated-book',{c['book_id'] for c in scope['cards']})
            self.assertNotIn('unrelated-book',{r['book_id'] for r in scope['rows']})
            plan=self.plan(f)
            plan['cards'][0]['book_id']='unrelated-book'
            plan['run_id']=sc.digest({k:v for k,v in plan.items() if k!='run_id'})
            with self.assertRaisesRegex(ValueError,'foreign book'):fs.apply(plan,root_write_approved=True)

    def test_live_reader_drift_is_rejected_before_candidate_writes(self):
        with tempfile.TemporaryDirectory() as root:
            f=Fixture(root);plan=self.plan(f);before=f.graph()
            Path(root,'reader-live.json').write_text('changed source')
            with self.assertRaisesRegex(ValueError,'pinned source changed'):fs.apply(plan,root_write_approved=True)
            self.assertEqual(f.graph(),before)


if __name__=='__main__':unittest.main()
