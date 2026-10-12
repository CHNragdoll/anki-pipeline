"""Conservative common senses retain source identities and physical counts."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from anki_pipeline import sense_groups as sg


def occurrence(identity='o1', year=2022):
    return {'occurrence_id': identity, 'year': year, 'sentence_id': 'paper:p:1',
            'physical_source': ['paper', 'p'], 'target_range': [0, 6],
            'english': 'change', 'english_hash': 'source', 'status': 'reviewed'}


def report(senses=None, pending=None):
    senses = senses or [
        {'sense_id': 's0', 'ordinal': 0, 'pos': 'n.', 'text': '变化',
         'original_english': 'the process of becoming different',
         'usage_scope': {'headword': 'change', 'kind': 'main', 'grammar': ['C/U']},
         'occurrences': [occurrence()], 'count': 1},
        {'sense_id': 's1', 'ordinal': 1, 'pos': 'n.', 'text': '变化',
         'original_english': 'the process of becoming different',
         'usage_scope': {'headword': 'change', 'kind': 'main', 'grammar': ['C/U']},
         'occurrences': [occurrence('o2', 2021)], 'count': 1}]
    pending = pending or []
    return {'schema': 'exam-sense-frequency.v2', 'snapshot_id': 'snapshot',
            'word': 'change', 'book_id': 'book', 'card_id': 'card',
            'definition_source': 'oxford', 'definition_provenance': {'entry': 'change'},
            'total': len({o['occurrence_id'] for s in senses for o in s['occurrences']}) + len(pending),
            'senses': senses, 'pending': pending, 'pending_count': len(pending)}


def equivalence(ids=('s0', 's1')):
    return {'member_sense_ids': list(ids), 'meaning': '事物变得不同',
            'usage_scope': '名词，普通变化，不含特定更换对象',
            'reason': '原词典定义与用法范围已逐项核对',
            'evidence': [{'source_sense_ref': 'source0', 'quote': 'becoming different'}],
            'review_version': '20261012'}


class SenseGroupingTests(unittest.TestCase):
    def test_equal_meaning_and_scope_merge_with_all_original_members_retained(self):
        source = report()
        before = deepcopy(source)
        grouped = sg.group_report(source)
        self.assertEqual(source, before)
        self.assertEqual(grouped['senses'], before['senses'])
        self.assertEqual(grouped['definition_provenance'], before['definition_provenance'])
        group, = grouped['sense_groups']
        self.assertEqual(group['member_sense_ids'], ['s0', 's1'])
        self.assertEqual([m['sense_id'] for m in group['members']], ['s0', 's1'])
        self.assertEqual(group['count'], 2)
        self.assertEqual(group['years'], [{'year': 2022, 'count': 1}, {'year': 2021, 'count': 1}])
        self.assertEqual(grouped['sense_group_by_id']['s0'], grouped['sense_group_by_id']['s1'])

    def test_identical_chinese_with_different_english_or_scope_never_merge(self):
        for field, value in [('original_english', 'financial help'),
                             ('english_definitions', ['money paid to help someone']),
                             ('usage_scope', {'headword': 'support', 'kind': 'financial'})]:
            with self.subTest(field=field):
                source = report()
                source['senses'][1][field] = value
                self.assertEqual(len(sg.group_report(source)['sense_groups']), 2)

    def test_missing_context_is_a_proposal_not_automatic_equivalence(self):
        source = report()
        for sense in source['senses']:
            del sense['original_english']
            del sense['usage_scope']
        grouped = sg.group_report(source)
        self.assertEqual(len(grouped['sense_groups']), 2)
        self.assertEqual(grouped['merge_candidates'][0]['member_sense_ids'], ['s0', 's1'])
        self.assertEqual(grouped['merge_candidates'][0]['status'], 'needs-source-review')
        approved = sg.group_report(source, equivalences=[equivalence()])
        self.assertEqual(len(approved['sense_groups']), 1)
        source['sense_group_equivalences'] = [equivalence()]
        self.assertEqual(len(sg.group_report(source)['sense_groups']), 1)

    def test_component_slice_retains_global_ordinals_and_certificate_membership(self):
        source = report()
        source['senses'][0]['ordinal'] = 13
        source['senses'][1]['ordinal'] = 20
        proof = equivalence()
        del proof['member_sense_ids']
        proof['member_ordinals'] = [13, 20]
        display = sg.display_report(source, equivalences=[proof])
        self.assertEqual(display['senses'][0]['ordinal'], 13)
        self.assertEqual([m['ordinal'] for m in display['senses'][0]['members']], [13, 20])

    def test_review_cannot_merge_noun_and_verb_or_change_supplied_source_context(self):
        source = report()
        source['senses'][1]['pos'] = 'v.'
        with self.assertRaisesRegex(ValueError, 'part of speech'):
            sg.group_report(source, equivalences=[equivalence()])
        source = report()
        source['senses'][1]['original_english'] = 'financial help'
        # Semantic review may explain distinct English wording, but must retain
        # and explicitly account for every source member in its evidence.
        with self.assertRaisesRegex(ValueError, 'source context'):
            sg.group_report(source, equivalences=[equivalence()])

    def test_duplicate_physical_occurrence_is_counted_once(self):
        source = report()
        source['senses'][1]['occurrences'] = [deepcopy(source['senses'][0]['occurrences'][0])]
        group, = sg.group_report(source)['sense_groups']
        self.assertEqual(group['count'], 1)
        self.assertEqual(group['deduplicated_count'], 1)
        self.assertEqual(group['occurrences'][0]['original_member_sense_ids'], ['s0', 's1'])

    def test_duplicate_identity_with_conflicting_source_is_rejected(self):
        source = report()
        row = deepcopy(source['senses'][0]['occurrences'][0])
        row['english'] = 'replacement source'
        source['senses'][1]['occurrences'] = [row]
        with self.assertRaisesRegex(ValueError, 'conflicting physical'):
            sg.group_report(source)

    def test_context_reviewed_common_match_counts_without_selecting_original_index(self):
        row = occurrence('pending')
        row.update(status='ambiguous', sense_id=None,
                   common_sense_match={'candidate_sense_ids': ['s0', 's1'],
                       'reason': '原句明确表示变化，两条来源义项语义范围一致',
                       'method': 'context-review', 'review_version': '20261012'})
        source = report(pending=[row])
        grouped = sg.group_report(source)
        group, = grouped['sense_groups']
        self.assertEqual(group['count'], 3)
        self.assertEqual(group['common_match_count'], 1)
        self.assertEqual(grouped['group_pending_count'], 0)
        self.assertEqual(grouped['pending'], source['pending'])
        common_row = next(r for r in group['occurrences'] if r['occurrence_id'] == 'pending')
        self.assertIsNone(common_row['sense_id'])
        self.assertEqual(grouped['group_matches'][0]['kind'], 'reviewed-common-sense')
        display = sg.display_report(source)
        self.assertEqual(display['total'], source['total'])
        self.assertEqual(display['original_senses'], source['senses'])
        self.assertEqual(display['original_pending'], source['pending'])
        self.assertEqual(len(display['senses']), 1)
        self.assertEqual(display['pending'], [])
        self.assertEqual(sum(s['count'] for s in display['senses']) + display['pending_count'], display['total'])
        self.assertEqual(sg.display_report(display), display)

    def test_lexical_same_group_proposal_remains_uncounted(self):
        row = occurrence('pending')
        row.update(status='ambiguous', sense_id=None,
                   matching_proposal={'candidate_sense_ids': ['s0', 's1'], 'reason': '词面候选'})
        grouped = sg.group_report(report(pending=[row]))
        self.assertEqual(grouped['sense_groups'][0]['count'], 2)
        self.assertFalse(grouped['group_matches'][0]['counted'])
        self.assertEqual(grouped['group_pending_count'], 1)

    def test_broad_match_keeps_distinct_funding_and_general_help_candidates(self):
        source = report()
        source['senses'][0].update(text='支持', original_english='give practical help')
        source['senses'][1].update(text='资助', original_english='provide money')
        row = occurrence('pending')
        row.update(status='ambiguous', sense_id=None,
                   broad_match={'candidate_sense_ids': ['s0', 's1'],
                                'reason': '原句未说明资金或实际援助手段'})
        source['pending'] = [row]
        source['pending_count'] = 1
        source['total'] = 3
        grouped = sg.group_report(source)
        self.assertEqual(len(grouped['sense_groups']), 2)
        match, = grouped['group_matches']
        self.assertEqual(match['label'], '宽泛匹配')
        self.assertEqual(match['candidate_sense_ids'], ['s0', 's1'])
        self.assertEqual(match['reason'], row['broad_match']['reason'])
        self.assertFalse(match['counted'])

    def test_broad_label_requires_known_candidates_and_reason(self):
        for metadata in ({'candidate_sense_ids': ['s0', 'missing'], 'reason': 'scope unclear'},
                         {'candidate_sense_ids': ['s0', 's1'], 'reason': ''}):
            with self.subTest(metadata=metadata):
                source = report(pending=[{**occurrence('pending'), 'broad_match': metadata}])
                with self.assertRaises(ValueError):
                    sg.group_report(source)

    def test_reviewed_broad_match_counts_its_actual_sense_once(self):
        source = report()
        source['senses'][0]['occurrences'][0].update(sense_id='s0',
            broad_match={'candidate_sense_ids': ['s0', 's1'],
                         'reason': '实际原词典广义适用，语境未细分具体援助手段'})
        grouped = sg.group_report(source)
        self.assertEqual(grouped['sense_groups'][0]['count'], 2)
        self.assertTrue(grouped['group_matches'][0]['counted'])

    def test_pending_identity_cannot_repeat_or_overlap_original_review(self):
        for rows in ([occurrence('pending'), occurrence('pending')], [occurrence('o1')]):
            with self.subTest(rows=rows):
                with self.assertRaisesRegex(ValueError, 'reviewed and pending'):
                    sg.group_report(report(pending=rows))

    def test_supplement_source_metadata_is_used_and_kept_in_member_provenance(self):
        source = report()
        for sense in source['senses']:
            del sense['original_english']
            del sense['usage_scope']
        appended = [{'ordinal': i, 'pos': 'n.', 'text': '变化', 'english': 'becoming different',
                     'source_headword': 'change', 'scope_kind': 'main',
                     'sense_ref': f'native{i}', 'source_dictionary': 'cald4',
                     'source_ref': {'sense_id': f'ID{i}', 'raw_sha256': 'original'},
                     'native_definition': {'grammar': ['C/U'], 'usage_labels': []}}
                    for i in range(2)]
        source['definition_provenance']['supplemental_definitions'] = {'appended': appended}
        grouped = sg.group_report(source)
        group, = grouped['sense_groups']
        self.assertEqual(group['members'][1]['provenance']['supplemental']['source_ref']['sense_id'], 'ID1')
        self.assertEqual(grouped['definition_provenance'], source['definition_provenance'])

    def test_database_proposal_is_read_only_and_covers_each_active_card(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.sqlite3'
            source = report()
            payload = {**source, 'expected_occurrences': source['total'],
                       'occurrences': [o for s in source['senses'] for o in s['occurrences']]}
            for sense in payload['senses']:
                for row in sense['occurrences']:
                    row['sense_id'] = sense['sense_id']
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE snapshots(id TEXT PRIMARY KEY, payload TEXT)')
                db.execute('CREATE TABLE active_snapshots(book_id TEXT,card_id TEXT,snapshot_id TEXT)')
                db.execute('INSERT INTO snapshots VALUES(?,?)', ('snapshot', json.dumps(payload)))
                db.execute('INSERT INTO active_snapshots VALUES(?,?,?)', ('book','card','snapshot'))
                db.commit()
            before = path.read_bytes()
            summary = sg.write_database_proposal(path, Path(directory) / 'maps')
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(summary['cards'], 1)
            self.assertEqual(summary['original_senses'], 2)
            self.assertEqual(summary['groups'], 1)
            rows = [json.loads(line) for line in (Path(directory) / 'maps/groups.jsonl').read_text().splitlines()]
            self.assertEqual(rows[0]['sense_group_by_id'].keys(), {'s0', 's1'})
            self.assertEqual(summary['database_sql_mutations'], 0)


if __name__ == '__main__':
    unittest.main()
