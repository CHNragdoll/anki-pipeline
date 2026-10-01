"""A study link must select a verified fragment containing the target word."""
import unittest
from anki_pipeline.exam_library import _codex_anchor, digest


class CodexSourceAnchorTests(unittest.TestCase):
    def test_word_crossing_fragment_boundary_does_not_pick_half_a_word(self):
        paper = 'kaoyan:2026-01'
        old_id = paper + ':p:b-1-1:0'
        sentence = {'id': paper + ':p:joined:0', 'english': 'The banks offer rates.',
                    'englishHash': digest('The banks offer rates.'), 'sourceSentenceRefs': [{
                        'id': old_id, 'catalog': 'anki-sentence-index.v1',
                        'sourceText': 'The banks o', 'sourceHash': digest('The banks o'),
                        'newRange': [0, 11]}]}
        anchors = {old_id: {'paragraph_id': paper + ':p:b-1-1', 'sentence_index': 0,
                           'text': 'The banks o', 'english_hash': digest('The banks o')}}
        self.assertIsNone(_codex_anchor(sentence, [(10, 15)], anchors))

    def test_right_fragment_cannot_fall_back_to_unrelated_left_sentence(self):
        english = "The banks offer rates for loans."
        left = "The banks offer"
        right = "rates for loans."
        paper = "kaoyan:2026-01"
        sentence = {
            "id": paper + ":p:joined:0", "english": english,
            "englishHash": digest(english), "sourceEnglish": english,
            "filledEnglish": english, "start": 0,
            "sourceBlockIds": [paper + ":b-1-5", paper + ":b-2-1"],
            "sourceFragments": [],
            "sourceSentenceRefs": [
                {"id": paper + ":p:b-1-5:0", "catalog": "anki-sentence-index.v1",
                 "sourceText": left, "sourceHash": digest(left), "newRange": [0, 15]},
                {"id": paper + ":p:b-2-1:0", "catalog": "codex-exam-translation-input.v1",
                 "sourceText": right, "sourceHash": digest(right), "newRange": [16, 32]},
            ],
        }
        anchors = {paper + ":p:b-1-5:0": {
            "paragraph_id": paper + ":p:b-1-5", "sentence_index": 0,
            "text": left, "english_hash": digest(left)}}
        # The current reader requires a real sentence index. A coarse block
        # URL is not a usable fallback, and the left sentence is unrelated.
        self.assertIsNone(_codex_anchor(sentence, [(16, 21)], anchors))

    def test_verified_right_sentence_is_used(self):
        paper = "kaoyan:2026-01"
        english = "The banks offer rates for loans."
        right = "rates for loans."
        sid = paper + ":p:b-2-1:0"
        sentence = {"id": paper + ":p:joined:0", "english": english,
            "englishHash": digest(english), "sourceSentenceRefs": [{
                "id": sid, "catalog": "anki-sentence-index.v1", "sourceText": right,
                "sourceHash": digest(right), "newRange": [16, len(english)]}]}
        anchors = {sid: {"paragraph_id": paper + ":p:b-2-1", "sentence_index": 0,
                        "text": right, "english_hash": digest(right)}}
        self.assertEqual(_codex_anchor(sentence, [(16, 21)], anchors)["sentence_id"], sid)
