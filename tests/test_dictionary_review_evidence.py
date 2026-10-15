"""New senses require actual native definitions, not plausible hash strings."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.dictionary_review_evidence import validate_new_sense


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class DictionaryReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.source = {'provider': 'oxford', 'source_entry_id': 42,
            'raw_sha256': sha('native raw entry'), 'sense_id': 'definition-1',
            'source_headword': 'rate', 'dictionary': 'oald10'}
        self.english = 'a measurement of the speed at which something happens'
        self.chinese = '速度；速率'
        self.row = {'source_ref': self.source, 'sense_ref': sha('sense'),
            'english': self.english, 'chinese': self.chinese,
            'native_definition_valid': True, 'raw_entry_valid': True}
        self.decision = {'dictionary_explanation': {
            'english_definition': self.english, 'original_chinese': self.chinese,
            'source_ref_pin': {**self.source, 'sense_ref': self.row['sense_ref']}},
            'new_sense': {'pos': 'n.', 'text': self.chinese,
                'original_english': self.english, 'original_chinese': self.chinese,
                'translation_kind': 'original'}}

    def validate(self, decision=None, registry=None):
        return validate_new_sense(decision or self.decision,
            registry=[self.row] if registry is None else registry)

    def test_forged_source_hash_does_not_match_a_freshly_validated_registry(self):
        decision = deepcopy(self.decision)
        decision['dictionary_explanation']['source_ref_pin']['raw_sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'registry'):
            self.validate(decision)

    def test_original_translation_requires_actual_native_chinese(self):
        row = {**self.row, 'chinese': ''}
        with self.assertRaisesRegex(ValueError, 'Chinese'):
            self.validate(registry=[row])

    def test_native_full_english_cannot_be_replaced_by_a_shorter_excerpt(self):
        decision = deepcopy(self.decision)
        decision['dictionary_explanation']['english_definition'] = 'a measurement'
        decision['new_sense']['original_english'] = 'a measurement'
        with self.assertRaisesRegex(ValueError, 'English'):
            self.validate(decision)

    def test_native_original_is_normalized_without_mutating_inputs(self):
        decision = deepcopy(self.decision)
        decision['new_sense']['original_english'] = self.english.replace(' ', '\n')
        before = deepcopy(decision)
        result = self.validate(decision)
        self.assertEqual(result['english_definition'], self.english)
        self.assertEqual(result['original_chinese'], self.chinese)
        self.assertEqual(result['primary_source']['kind'], 'native_registry')
        self.assertEqual(decision, before)

    def test_every_provenance_component_and_validation_flag_is_checked(self):
        for key, forged in (('provider', 'made-up'), ('source_entry_id', 99),
                            ('sense_id', 'different'), ('sense_ref', 'b' * 64)):
            with self.subTest(key=key):
                decision = deepcopy(self.decision)
                decision['dictionary_explanation']['source_ref_pin'][key] = forged
                with self.assertRaisesRegex(ValueError, 'registry'):
                    self.validate(decision)
        for key in ('native_definition_valid', 'raw_entry_valid'):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, 'validated'):
                    self.validate(registry=[{**self.row, key: False}])

    def test_original_cn_cannot_contain_authored_scope_or_punctuation_edits(self):
        for field in ('text', 'original_chinese'):
            decision = deepcopy(self.decision)
            decision['new_sense'][field] += '（指测量）'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Chinese'):
                self.validate(decision)

    def capture_decision(self, directory, *, chinese='', html=False):
        path = Path(directory) / ('source.html' if html else 'source.txt')
        raw = '<div>rate<p>' + self.english + '</p><p>' + chinese + '</p></div>' if html else (
            'rate\n' + self.english + '\n' + chinese)
        path.write_text(raw, encoding='utf-8')
        pin = {'provider': 'official_web', 'source_entry_id': 'https://dictionary.cambridge.org/rate#1',
               'sense_id': '1', 'source_headword': 'rate', 'source_url': 'https://dictionary.cambridge.org/rate',
               'capture_format': 'html' if html else 'text', 'capture_file': str(path),
               'capture_sha256': sha(raw), 'raw_sha256': sha(raw),
               'original_definition_text': self.english}
        decision = deepcopy(self.decision)
        decision['dictionary_explanation'].update(source_ref_pin=pin, original_chinese=chinese)
        decision['new_sense'].update(original_chinese=chinese)
        return path, decision

    def test_official_original_capture_verifies_utf8_bytes_and_both_languages(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, decision = self.capture_decision(temporary, chinese=self.chinese, html=True)
            result = self.validate(decision, registry=[])
            self.assertEqual(result['primary_source']['kind'], 'official_capture')
            self.assertEqual(result['primary_source']['source_ref_pin']['capture_file'], str(path.resolve()))
            path.write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                self.validate(decision, registry=[])

    def test_official_forged_hash_unofficial_url_or_missing_definition_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, baseline = self.capture_decision(temporary, chinese=self.chinese)
            for key, forged in (('capture_sha256', 'c' * 64),
                                ('source_url', 'https://dictionary.cambridge.org.evil.test/rate'),
                                ('original_definition_text', 'invented definition')):
                with self.subTest(key=key):
                    decision = deepcopy(baseline)
                    decision['dictionary_explanation']['source_ref_pin'][key] = forged
                    with self.assertRaises(ValueError):
                        self.validate(decision, registry=[])

    def test_reviewed_translation_requires_search_queries_and_actual_source_pins(self):
        decision = deepcopy(self.decision)
        decision['new_sense'].update(translation_kind='reviewed_translation', text='已审校的新译文')
        with self.assertRaisesRegex(ValueError, 'bilingual_search'):
            self.validate(decision)
        decision['dictionary_explanation']['bilingual_search'] = {
            'queries': ['rate bilingual definition'], 'source_pins': [self.source]}
        result = self.validate(decision)
        self.assertEqual(result['bilingual_search']['queries'], ['rate bilingual definition'])
        decision['dictionary_explanation']['bilingual_search']['source_pins'][0] = {
            **self.source, 'raw_sha256': 'd' * 64}
        with self.assertRaisesRegex(ValueError, 'registry'):
            self.validate(decision)

    def test_cross_dictionary_original_requires_independent_actual_chinese(self):
        second = deepcopy(self.row)
        second['source_ref'].update(provider='cdepe', source_entry_id=73, raw_sha256=sha('second raw'))
        second['chinese'] = '比率'
        decision = deepcopy(self.decision)
        decision['new_sense'].update(translation_kind='cross_dictionary_original', text='比率', original_chinese='比率')
        decision['dictionary_explanation']['secondary_source'] = {
            'source_ref_pin': deepcopy(second['source_ref']), 'english_definition': second['english'],
            'original_chinese': second['chinese']}
        result = self.validate(decision, registry=[self.row, second])
        self.assertEqual(result['secondary_source']['original_chinese'], '比率')
        decision['dictionary_explanation']['secondary_source']['source_ref_pin']['raw_sha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'registry'):
            self.validate(decision, registry=[self.row, second])

    def test_source_view_links_preserve_real_definition_words(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, decision = self.capture_decision(temporary, chinese=self.chinese)
            captured = self.english.replace('speed', 'cite42†speed') + '\n' + self.chinese
            path.write_text(captured, encoding='utf-8')
            pin = decision['dictionary_explanation']['source_ref_pin']
            pin['capture_sha256'] = pin['raw_sha256'] = sha(captured)
            self.assertEqual(self.validate(decision, registry=[])['english_definition'], self.english)

    def test_pons_and_american_heritage_exact_domains_retain_capture_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            _, decision = self.capture_decision(temporary, chinese=self.chinese)
            pin = decision['dictionary_explanation']['source_ref_pin']
            for domain in ('zh.pons.com', 'www.ahdictionary.com'):
                pin['source_url'] = 'https://' + domain + '/rate'
                self.assertEqual(self.validate(decision, registry=[])['original_chinese'], self.chinese)
                pin['source_url'] = 'https://' + domain + '.evil.test/rate'
                with self.assertRaisesRegex(ValueError, 'official'):
                    self.validate(decision, registry=[])

    def test_chinese_only_secondary_preserves_native_identity_without_fabricating_english(self):
        second = deepcopy(self.row)
        second['source_ref'].update(provider='chinese-dictionary', source_entry_id=73,
            raw_sha256=sha('Chinese only raw definition'))
        second.update(english='', chinese='比率')
        decision = deepcopy(self.decision)
        decision['new_sense'].update(translation_kind='cross_dictionary_original', text='比率', original_chinese='比率')
        decision['dictionary_explanation']['secondary_source'] = {
            'source_ref_pin': second['source_ref'], 'english_definition': '',
            'original_chinese': second['chinese'], 'scope_reason': '中文词典此处为名词比率，与完整英文定义范围对应'}
        result = self.validate(decision, registry=[self.row, second])
        self.assertEqual(result['secondary_source']['english_definition'], '')
        forged = deepcopy(decision)
        forged['dictionary_explanation']['secondary_source']['english_definition'] = 'invented English'
        with self.assertRaisesRegex(ValueError, 'English'):
            self.validate(forged, registry=[self.row, second])
        del decision['dictionary_explanation']['secondary_source']['scope_reason']
        with self.assertRaisesRegex(ValueError, 'scope explanation'):
            self.validate(decision, registry=[self.row, second])
