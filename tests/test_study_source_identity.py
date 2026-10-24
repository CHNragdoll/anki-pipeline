"""New source namespaces are explicit, while legacy semantic seals stay exact."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from anki_pipeline import sense_frequency as sf
from tests.test_sense_frequency import aligned_record, record, reseal


def study_record(*, namespace='ielts', source_id='cambridge-18-test-1', year=2023,
                 kind='exam'):
    value = aligned_record()
    paper_id = f'study:{namespace}:{source_id}'
    for row in value['occurrences']:
        row['paper_id'] = paper_id
        row['sentence_id'] = paper_id + ':paragraph-1:sentence-1'
        # A human-readable label is deliberately not an authority for the year.
        row['source'] = 'A labelled 1999 source'
        row['source_provenance']['study_source'] = {
            'schema': 'study-source.v1', 'id': paper_id, 'namespace': namespace,
            'kind': kind, 'label': 'Cambridge IELTS practice',
            'locator': 'reading/test-1/passage-1/paragraph-1', 'year': year}
    return value


class StudySourceIdentityTests(unittest.TestCase):
    def test_explicit_ielts_identity_uses_existing_seals_and_physical_counts(self):
        original = study_record()
        sealed = reseal(deepcopy(original))
        prepared = sf.prepare_record(sealed)
        report = sf.report_from_record(prepared)
        self.assertEqual(report['total'], 2)
        self.assertEqual([sense['count'] for sense in report['senses']], [1, 1])
        self.assertEqual({row['year'] for row in prepared['occurrences']}, {2023})
        self.assertEqual({row['paper_id'] for row in prepared['occurrences']},
                         {'study:ielts:cambridge-18-test-1'})
        self.assertEqual(original, study_record())
        self.assertIn('2023', sf.render_report(report))
        stale = deepcopy(sealed)
        stale['occurrences'][0]['source_provenance']['study_source']['locator'] = 'other-location'
        with self.assertRaisesRegex(ValueError, 'binding'):
            sf.prepare_record(stale)

    def test_undated_article_round_trips_without_inventing_a_year(self):
        value = reseal(study_record(namespace='science-notes', source_id='article-47',
                                   year=None, kind='article'))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'semantic.sqlite3'
            sf.save_records(database, [value], Path(directory) / 'backups')
            report = sf.read_card(database, value['book_id'], value['card_id'])
        self.assertEqual(report['total'], 2)
        self.assertEqual([sense['years'] for sense in report['senses']],
                         [[{'year': 0, 'count': 1}], [{'year': 0, 'count': 1}]])
        rendered = sf.render_report(report)
        self.assertIn('未注明年份', rendered)
        self.assertNotIn('>0</span>', rendered)
        self.assertNotIn('>0 ·', rendered)
        # The internal filter key still addresses the same two physical tokens.
        self.assertEqual(rendered.count('data-sf-year="0"'), 2)
        self.assertEqual(rendered.count('data-sf-filter="0"'), 2)

    def test_legacy_kaoyan_payloads_and_snapshot_ids_are_byte_stable(self):
        for factory, snapshot, payload_sha in [
            (record, 'e128b083a885b077521aaed41560e8dd8197db980f0ef5180c882a263555d585',
             '5b6439b48840874f91f43322ef8e61d1b14aaf10d2e1d32c119b3a0f7d3aab0b'),
            (aligned_record, 'd9ea4dc8bdc4a64255ff583b0cc2beadeac6caf8ce9d23a614033b6be5756ca1',
             '7eaba7049f98f441e58f909731d79793ba233ded83a143f16d946ebd5dbc74cf'),
        ]:
            with self.subTest(factory=factory.__name__):
                prepared = sf.prepare_record(factory())
                self.assertEqual(prepared['snapshot_id'], snapshot)
                self.assertEqual(hashlib.sha256(sf._json(prepared).encode()).hexdigest(), payload_sha)

    def test_identity_proof_must_match_source_and_namespace(self):
        for field, replacement in [('schema', 'study-source.v2'), ('id', 'study:ielts:other'),
                                   ('namespace', 'toefl'), ('kind', 'guessed-exam'),
                                   ('kind', ['exam']),
                                   ('label', ' '), ('locator', '')]:
            with self.subTest(field=field):
                invalid = study_record()
                invalid['occurrences'][0]['source_provenance']['study_source'][field] = replacement
                with self.assertRaises(ValueError):
                    reseal(invalid)

    def test_source_kinds_are_explicit_and_not_limited_to_exam_names(self):
        for kind in ('exam', 'book', 'article', 'lesson', 'other'):
            with self.subTest(kind=kind):
                prepared = sf.prepare_record(reseal(study_record(
                    namespace='my-next-course', source_id='source-47', kind=kind, year=None)))
                self.assertEqual(prepared['expected_occurrences'], 2)
                self.assertEqual({row['year'] for row in prepared['occurrences']}, {0})

    def test_year_must_be_explicit_and_a_real_integer_or_null(self):
        for year in [True, False, 0, -1, 10000, 2023.0, '2023']:
            with self.subTest(year=year):
                with self.assertRaises(ValueError):
                    reseal(study_record(year=year))
        invalid = study_record()
        del invalid['occurrences'][0]['source_provenance']['study_source']['year']
        with self.assertRaises(ValueError):
            reseal(invalid)

    def test_new_sources_require_proof_and_exact_sentence_prefix(self):
        for mutation in ['missing-proof', 'wrong-prefix', 'empty-sentence-suffix',
                         'fake-kaoyan', 'reserved-kaoyan-namespace', 'unsafe-namespace']:
            with self.subTest(mutation=mutation):
                invalid = study_record()
                row = invalid['occurrences'][0]
                if mutation == 'missing-proof':
                    del row['source_provenance']['study_source']
                elif mutation == 'wrong-prefix':
                    row['sentence_id'] = 'study:ielts:different:paragraph-1'
                elif mutation == 'empty-sentence-suffix':
                    row['sentence_id'] = row['paper_id'] + ':'
                elif mutation == 'fake-kaoyan':
                    row['paper_id'] = 'kaoyan:ielts-practice'
                    row['sentence_id'] = row['paper_id'] + ':paragraph-1'
                    row['source_provenance']['study_source']['id'] = row['paper_id']
                elif mutation == 'reserved-kaoyan-namespace':
                    row['paper_id'] = 'study:kaoyan:2022-01'
                    row['sentence_id'] = row['paper_id'] + ':paragraph-1'
                    row['source_provenance']['study_source'].update(
                        id=row['paper_id'], namespace='kaoyan')
                else:
                    row['paper_id'] = 'study:../ielts:test-1'
                    row['sentence_id'] = row['paper_id'] + ':paragraph-1'
                    row['source_provenance']['study_source'].update(
                        id=row['paper_id'], namespace='../ielts')
                with self.assertRaises(ValueError):
                    reseal(invalid)


if __name__ == '__main__':
    unittest.main()
