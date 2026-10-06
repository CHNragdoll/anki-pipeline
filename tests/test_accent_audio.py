import copy
import unittest
from anki_pipeline.packaging import _dictionary_audio_markup, _card_audio_files


class AccentAudioTests(unittest.TestCase):
    def setUp(self):
        self.card = {"local_dictionary": {
            "audio": {"oxford": [{"filename": "old.mp3", "accent": "us"}], "webster": []},
            "accent_audio": {
                "uk": {"cambridge": [{"filename": "c-uk.mp3", "accent": "uk"}]},
                "us": {"oxford": [{"filename": "o-us.mp3", "accent": "us"}]},
            },
            "accent_audio_fallback": {"us": {"webster": "oxford"}},
        }}

    def test_explicit_accents_and_media_are_packaged(self):
        markup = _dictionary_audio_markup(self.card, None, preview=False)
        self.assertIn('data-accent-playback="v1"', markup)
        self.assertIn('data-dictionary-accent="uk"', markup)
        self.assertIn('data-dictionary-accent="us"', markup)
        self.assertIn('data-fallback-us-webster="oxford"', markup)
        self.assertNotIn('preview-word-play', markup)
        self.assertEqual(set(_card_audio_files(self.card, None)), {'old.mp3', 'c-uk.mp3', 'o-us.mp3'})

    def test_unknown_accent_or_cross_accent_source_is_rejected(self):
        bad = copy.deepcopy(self.card)
        bad['local_dictionary']['accent_audio']['uk']['cambridge'][0]['accent'] = 'us'
        with self.assertRaises(ValueError):
            _dictionary_audio_markup(bad, None, preview=False)
        bad = copy.deepcopy(self.card)
        bad['local_dictionary']['accent_audio']['us']['untrusted'] = []
        with self.assertRaises(ValueError):
            _dictionary_audio_markup(bad, None, preview=False)

    def test_fallback_needs_missing_requested_and_present_same_accent(self):
        for choices in ({'oxford': 'webster'}, {'webster': 'cambridge'}, {'webster': 'webster'}):
            bad = copy.deepcopy(self.card)
            bad['local_dictionary']['accent_audio_fallback']['us'] = choices
            with self.assertRaises(ValueError):
                _dictionary_audio_markup(bad, None, preview=False)

    def test_unsafe_resource_path_is_rejected(self):
        self.card['local_dictionary']['accent_audio']['uk']['cambridge'][0]['filename'] = '../private.mp3'
        with self.assertRaises(ValueError):
            _dictionary_audio_markup(self.card, None, preview=False)

    def test_declared_null_audio_or_empty_filename_is_rejected(self):
        for value in (None, []):
            bad = copy.deepcopy(self.card)
            bad['local_dictionary']['accent_audio'] = value
            with self.assertRaisesRegex(ValueError, 'separate uk and us'):
                _dictionary_audio_markup(bad, None, preview=False)
        self.card['local_dictionary']['accent_audio']['uk']['cambridge'][0]['filename'] = ''
        with self.assertRaisesRegex(ValueError, 'actual accent and filename'):
            _dictionary_audio_markup(self.card, None, preview=False)

    def test_verified_supplements_keep_source_name_and_accent(self):
        for source in ('collins', 'wiktionary', 'forvo'):
            card = copy.deepcopy(self.card)
            card['local_dictionary']['accent_audio']['uk'] = {
                source: [{'filename': 'supplement-uk.mp3', 'accent': 'uk'}]}
            card['local_dictionary']['accent_audio_fallback']['uk'] = {'cambridge': source, 'oxford': source}
            markup = _dictionary_audio_markup(card, None, preview=False)
            self.assertIn(f'data-dictionary-source="{source}"', markup)
            self.assertIn(f'data-fallback-uk-cambridge="{source}"', markup)
            self.assertIn('supplement-uk.mp3', _card_audio_files(card, None))

    def test_supplement_cannot_be_used_as_a_requested_selector(self):
        self.card['local_dictionary']['accent_audio_fallback']['uk'] = {'forvo': 'cambridge'}
        with self.assertRaises(ValueError):
            _dictionary_audio_markup(self.card, None, preview=False)
