"""A sense correction applies to one reviewed occurrence, never a whole form."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.exam_library import _canonical_codex_sentences
from anki_pipeline.occurrence_exclusions import load_occurrence_exclusions


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class OccurrenceExclusionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'exclusions.json'
        self.english = 'The ground was uneven. They ground the grain.'
        self.sentences = [{'id': 'kaoyan:2013-02:p:b-1-1:0',
                           'paperId': 'kaoyan:2013-02', 'english': self.english, 'sourceHash': sha(self.english)}]
        self.cards = [{'id': 'grind-card', 'word': 'grind'}]
        self.pin = {'sentenceId': self.sentences[0]['id'], 'cardId': 'grind-card',
                    'paperId': 'kaoyan:2013-02', 'englishHash': sha(self.english),
                    'sourceHash': sha(self.english),
                    'word': 'grind', 'form': 'ground', 'en': [4, 10],
                    'reason': 'This occurrence is the land noun.'}

    def write(self, pins):
        self.path.write_text(json.dumps({'schema': 'codex-anki-occurrence-exclusions.v1',
            'rangeUnit': 'sentence-codepoints', 'exclusions': pins}))

    def test_only_reviewed_noun_is_excluded_not_later_past_tense(self):
        self.write([self.pin])
        exclusions, aliases, digest = load_occurrence_exclusions(self.path, self.sentences, self.cards)
        self.assertEqual(aliases, {})
        self.assertEqual(exclusions, {(self.pin['sentenceId'], 'grind-card', 4, 10): self.pin['reason']})
        second = self.english.index('ground', 10)
        self.assertNotIn((self.pin['sentenceId'], 'grind-card', second, second + 6), exclusions)
        self.assertEqual(digest, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_stale_source_or_wrong_identity_cannot_silently_remove_matches(self):
        for field, value in [('englishHash', '0' * 64), ('sourceHash', '0' * 64), ('sourceHash', None), ('paperId', 'kaoyan:2026-01'),
                             ('word', 'ground'), ('cardId', 'unknown'), ('sentenceId', 'unknown'),
                             ('form', 'grounds'), ('en', [4, 9]), ('en', [True, 10]),
                             ('en', [4, 100]), ('reason', '   ')]:
            with self.subTest(field=field, value=value):
                pin = copy.deepcopy(self.pin); pin[field] = value
                self.write([pin])
                with self.assertRaises(ValueError):
                    load_occurrence_exclusions(self.path, self.sentences, self.cards)

    def test_duplicate_and_partial_word_pins_are_rejected(self):
        self.write([self.pin, self.pin])
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            load_occurrence_exclusions(self.path, self.sentences, self.cards)
        pin = copy.deepcopy(self.pin); pin.update(en=[5, 10], form='round')
        self.write([pin])
        with self.assertRaises(ValueError):
            load_occurrence_exclusions(self.path, self.sentences, self.cards)

    def alias_fixture(self):
        alias = copy.deepcopy(self.sentences[0])
        alias.update(paragraphId='kaoyan:2013-02:q-41-1:C', start=0,
                     filledEnglish=self.english, sourceBlockIds=['kaoyan:2013-02:b-1-1'],
                     context={'coverageStatus': 'covered_by_paragraph',
                              'translationRef': 'kaoyan:2013-02:p:b-1-1'})
        owner = copy.deepcopy(alias)
        owner.update(id='kaoyan:2013-02:p:b-1-1:0', paragraphId='kaoyan:2013-02:p:b-1-1',
                     english='C) ' + self.english, filledEnglish='C) ' + self.english,
                     sourceHash=sha('C) ' + self.english), context={})
        alias['id'] = 'kaoyan:2013-02:q-41-1:C:0'
        pin = copy.deepcopy(self.pin)
        pin.update(sentenceId=alias['id'], canonicalOwner={
            'sentenceId': owner['id'], 'en': [7, 13],
            'englishHash': sha(owner['english']), 'sourceHash': owner['sourceHash']})
        return alias, owner, pin

    def test_alias_pin_maps_exactly_through_printed_prefix_not_same_word_elsewhere(self):
        alias, owner, pin = self.alias_fixture()
        self.write([pin])
        exclusions, aliases, _ = load_occurrence_exclusions(
            self.path, [alias, owner], self.cards)
        original_key = (alias['id'], 'grind-card', 4, 10)
        self.assertEqual(aliases, {(owner['id'], 'grind-card', 7, 13): {original_key}})
        self.assertIn(original_key, exclusions)
        pin['canonicalOwner']['en'] = [owner['english'].rindex('ground'),
                                       owner['english'].rindex('ground') + 6]
        self.write([pin])
        with self.assertRaisesRegex(ValueError, 'another occurrence'):
            load_occurrence_exclusions(self.path, [alias, owner], self.cards)

    def test_alias_owner_requires_source_identity_and_unique_full_paragraph(self):
        for change in ('stale-hash', 'wrong-source', 'wrong-reference', 'different-block', 'repeat'):
            with self.subTest(change=change):
                alias, owner, pin = self.alias_fixture()
                if change == 'stale-hash': pin['canonicalOwner']['englishHash'] = '0' * 64
                if change == 'wrong-source': pin['canonicalOwner']['sourceHash'] = '0' * 64
                if change == 'wrong-reference': alias['context']['translationRef'] = 'another-paragraph'
                if change == 'different-block': owner['sourceBlockIds'] = ['another-block']
                if change == 'repeat': owner['filledEnglish'] += ' ' + self.english
                self.write([pin])
                with self.assertRaises(ValueError):
                    load_occurrence_exclusions(self.path, [alias, owner], self.cards)

    def test_matching_consumes_alias_pin_after_canonicalization_without_losing_true_past_tense(self):
        from anki_pipeline.exam_library import _codex_examples
        from tests.test_codex_exam_index import record, write_fixture
        from tests.test_packaging import card
        root = Path(self.temp.name)
        stage = root / 'staging'
        owner_id, alias_id = 'kaoyan:2013-02:p:b-1-1', 'kaoyan:2013-02:q-41-1:C'
        block = ['kaoyan:2013-02:b-1-1']
        owner_text = 'C) ' + self.english
        write_fixture(stage, names=('2013-02',), records={'2013-02': [
            record('2013-02', english=owner_text, identifier=owner_id,
                   context={'sourceBlockIds': block, 'sourcePath': '2013 Reading'}),
            record('2013-02', english=self.english, identifier=alias_id, kind='answer_option',
                   context={'sourceBlockIds': block, 'coverageStatus': 'covered_by_paragraph',
                            'translationRef': owner_id, 'sourcePath': '2013 Reading'})]})
        _, _, pin = self.alias_fixture()
        self.write([pin])
        (stage / 'targets').mkdir()
        (stage / 'targets/occurrence-exclusions.json').write_bytes(self.path.read_bytes())
        value = card('grind-card', word='grind', audio='')
        value['local_dictionary'] = {'forms_source': 'webster',
            'forms': [{'kind': 'past', 'form': 'ground', 'base': 'grind'}]}
        cards, report = _codex_examples(root, [value], '', 'latex', 0, stage, True)
        self.assertEqual(report['excluded_homograph_occurrences'], 1)
        self.assertEqual(len(cards[0]['examples']), 1)
        start = owner_text.rindex('ground')
        self.assertEqual(cards[0]['examples'][0]['matched_english_ranges'], [[start, start + 6]])


class PhysicalOptionDeduplicationTests(unittest.TestCase):
    def option(self, *, paper='kaoyan:2026-01', paragraph='q-41-1:A', block='b-9-1', page=9):
        return {'id': paper + ':' + paragraph + ':0', 'paperId': paper,
            'paragraphId': paper + ':' + paragraph, 'kind': 'answer_option',
            'context': {'pdfVerifiedSource': {'sourcePdfSha256': 'a' * 64,
                'pdfPage': page, 'anchorKind': 'figure_bank', 'sourceOptionId': paper + ':part-b:A'}},
            'sourceBlockIds': [paper + ':' + block], 'sourceHash': sha('Same option.'),
            'sourceEnglish': 'Same option.', 'start': 0, 'end': 12,
            'english': 'Same option.', 'translationZh': '同一选项。',
            'alignments': [{'en': [0, 4], 'zh': [[0, 2]], 'relation': 'equivalent'}]}

    def test_one_printed_option_in_five_question_rows_is_one_occurrence(self):
        rows = [self.option(paragraph=f'q-{number}-1:A') for number in range(41, 46)]
        selected, report = _canonical_codex_sentences(rows)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['source_sentence_ids'], [row['id'] for row in rows])
        self.assertEqual(report['deduplicated_answer_option_sentences'], 4)

    def test_same_words_on_different_pages_or_papers_are_real_occurrences(self):
        rows = [self.option(), self.option(page=10, paragraph='q-42-1:A'),
                self.option(paper='kaoyan:2025-01')]
        selected, report = _canonical_codex_sentences(rows)
        self.assertEqual(len(selected), 3)
        self.assertEqual(report['deduplicated_answer_option_sentences'], 0)

    def test_same_block_and_letter_without_an_option_location_is_not_proof(self):
        first = self.option(paragraph='q-1-1:A')
        second = self.option(paragraph='q-2-1:A')
        first['context'] = {}; second['context'] = {}
        selected, report = _canonical_codex_sentences([first, second])
        self.assertEqual(len(selected), 2)
        self.assertEqual(report['deduplicated_answer_option_sentences'], 0)

    def test_conflicting_translations_or_alignments_are_never_deduplicated(self):
        first = self.option()
        for field, value in [('translationZh', '另一译文。'), ('alignments', [])]:
            second = self.option(paragraph='q-42-1:A'); second[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '不能自动去重'):
                _canonical_codex_sentences([first, second])

    def test_alias_to_a_body_paragraph_requires_exact_physical_provenance(self):
        option = self.option()
        body = copy.deepcopy(option)
        body.update(id='kaoyan:2026-01:p:b-9-1:0', paragraphId='kaoyan:2026-01:p:b-9-1', kind='reading',
                    sourceEnglish='A) Same option.', context={})
        option['context'].update(coverageStatus='covered_by_paragraph', translationRef=body['paragraphId'])
        selected, report = _canonical_codex_sentences([body, option])
        self.assertEqual([row['id'] for row in selected], [body['id']])
        self.assertEqual(report['deduplicated_answer_option_sentences'], 1)
        body['sourceBlockIds'] = ['kaoyan:2026-01:b-9-2']
        with self.assertRaisesRegex(ValueError, 'exact verified physical source'):
            _canonical_codex_sentences([body, option])

    def test_alias_print_spacing_does_not_join_separate_words(self):
        option = self.option()
        body = copy.deepcopy(option)
        body.update(id='kaoyan:2026-01:p:b-9-1:0', paragraphId='kaoyan:2026-01:p:b-9-1', kind='reading',
                    sourceEnglish='A) Same option.', context={})
        option['sourceEnglish'] = 'Same  option .'
        option['context'].update(coverageStatus='covered_by_paragraph', translationRef=body['paragraphId'])
        selected, report = _canonical_codex_sentences([body, option])
        self.assertEqual(len(selected), 1)
        body['sourceEnglish'] = 'A) the rapist.'
        option['sourceEnglish'] = 'therapist.'
        with self.assertRaises(ValueError):
            _canonical_codex_sentences([body, option])


if __name__ == '__main__':
    unittest.main()
