"""Card chunk interaction uses only exact, existing sentence alignment ranges."""

from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from anki_pipeline.packaging import _fields, build_package, render_preview
from anki_pipeline.chunk_projection import project_reviewed_chunks, SENTENCE_FALLBACK_NOTE
from anki_pipeline.translation_alignment import TranslationAlignmentError


def card(english="The rate rose.", chinese="比率上升了。", entries=None):
    if entries is None:
        entries = [{"en": [0, 8], "zh": [[0, 2]], "relation": "equivalent"},
                   {"en": [9, 13], "zh": [[2, 5]], "relation": "equivalent"}]
    return {
        "id": "chunk-card", "sheet": "Unit 1", "lesson": "Lesson 1", "position": 1,
        "word": "rate", "phonetic": "", "definition": "比率", "simple_definition": "",
        "level": "", "word_forms": "", "audio_filename": "",
        "examples": [{"text": english, "translation": chinese, "source": "2020",
                      "translation_source": "codex", "translation_alignment": {
                          "schema": "codex-sentence-alignment.v1",
                          "englishHash": hashlib.sha256(english.encode()).hexdigest(),
                          "translationHash": hashlib.sha256(chinese.encode()).hexdigest(),
                          "alignments": entries,
                      }}],
    }


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")


def plain(fragment):
    parser = Text()
    parser.feed(fragment)
    return "".join(parser.parts)


class CardChunkTests(unittest.TestCase):
    def fields(self, item):
        return _fields(item, None, 0)[0]["Examples"]

    def test_derived_reading_completions_and_candidates_keep_bilingual_interaction(self):
        from anki_pipeline.codex_exam_index import load_codex_exam_index
        from anki_pipeline.option_context import prepare_option_contexts
        from anki_pipeline.reading_completion import load_reading_completions
        from tests.test_option_context import OptionContextTests

        fixture = OptionContextTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        sentences, report = load_codex_exam_index(fixture.stage, allow_partial=True)
        completed, _, _ = load_reading_completions(fixture.root, fixture.sidecar, sentences, report)
        contexts, _, _, _ = prepare_option_contexts(fixture.root, sentences, report, completed)
        derived = [*completed.values(), *{row['sentenceId']: row for row in contexts.values()}.values()]
        for row in derived:
            with self.subTest(sentence_id=row['sentenceId']):
                self.assertTrue(row['translation_alignment']['alignments'])
                item = card(row['completedEnglish'], row['translationZh'],
                            row['translation_alignment']['alignments'])
                rendered = self.fields(item)
                self.assertIn('data-chunk-side="en"', rendered)
                self.assertIn('data-chunk-side="zh"', rendered)
                self.assertIn('<mark class="target-word"><span class="card-chunk"', rendered)
                self.assertIn(row['completedEnglish'], plain(rendered))
                self.assertIn(row['translationZh'], plain(rendered))

    def test_all_reviewed_chunks_are_annotated_without_fixed_chinese_highlight(self):
        item = card()
        original = copy.deepcopy(item)
        rendered = self.fields(item)
        self.assertIn('data-chunk-side="en" data-chunk-ids="0"', rendered)
        self.assertIn('data-chunk-side="en" data-chunk-ids="1"', rendered)
        self.assertIn('data-chunk-side="zh" data-chunk-ids="0"', rendered)
        self.assertIn('data-chunk-side="zh" data-chunk-ids="1"', rendered)
        self.assertIn('<mark class="target-word">', rendered)
        chinese = rendered.split('class="example-translation"', 1)[1]
        self.assertNotIn("<mark", chinese)
        self.assertNotIn("term-highlight", chinese)
        self.assertNotIn("card-chunk-active", chinese)
        self.assertEqual(item, original)

    def test_missing_empty_and_implicit_indices_stay_plain(self):
        for entries in ([], [{"en": [0, 3], "zh": [], "relation": "implicit", "note": "Omitted article"}]):
            with self.subTest(entries=entries):
                rendered = self.fields(card(entries=entries))
                self.assertNotIn("data-chunk-", rendered)
                self.assertIn("比率上升了。", rendered)
        item = card()
        del item["examples"][0]["translation_alignment"]
        del item["examples"][0]["translation_source"]
        self.assertNotIn("data-chunk-", self.fields(item))

    def test_optional_generic_stale_or_malformed_chunks_disable_all_interaction(self):
        changes = [lambda e: e.update(text="The rates rose."),
                   lambda e: e.update(translation="比率上升了！"),
                   lambda e: e["translation_alignment"].update(schema="unknown"),
                   lambda e: e["translation_alignment"]["alignments"].append(
                       {"en": [0, 1], "zh": [[0, 99]], "relation": "equivalent"}),
                   lambda e: e.update(translation_alignment=None)]
        for mutate in changes:
            item = card()
            # Codex provenance is mandatory and fails the build on drift;
            # optional generic alignment can leave readable text without chunks.
            item['examples'][0].pop('translation_source')
            mutate(item["examples"][0])
            with self.subTest(item=item):
                rendered = self.fields(item)
                self.assertNotIn("data-chunk-", rendered)
                self.assertIn(item["examples"][0]["translation"], rendered)

    def test_unicode_whitespace_html_and_many_to_many_text_are_preserved(self):
        english, chinese = " \n😀 rate <&> rose. ", "\n比率<&>上升😀。 "
        item = card(english, chinese, [
            {"en": [english.index("rate"), english.index("rose") + 4],
             "zh": [[0, 3], [6, len(chinese)]], "relation": "equivalent"}])
        rendered = self.fields(item)
        english_html = rendered.split('<span class="example-text">', 1)[1].split('</div>', 1)[0]
        self.assertEqual(plain(english_html), english)
        chinese_html = rendered.split('</span> ', 1)[1].split('</span><span class="example-source">', 1)[0]
        self.assertEqual(plain(chinese_html), chinese)
        self.assertNotIn("<&>", rendered)

    def test_chunk_boundaries_preserve_target_and_actual_cloze_underlines(self):
        item = card(entries=[{"en": [0, 6], "zh": [[0, 2]], "relation": "equivalent"},
                             {"en": [6, 13], "zh": [[2, 5]], "relation": "equivalent"}])
        item["examples"][0]["cloze_answers"] = [{"start": 4, "end": 8, "word": "rate", "number": 2}]
        rendered = self.fields(item)
        self.assertEqual(rendered.count('<u class="cloze-answer" data-blank-number="2">'), 1)
        self.assertEqual(rendered.count('<mark class="target-word">'), 1)
        self.assertIn('data-chunk-ids="0">ra</span><span class="card-chunk" data-chunk-side="en" data-chunk-ids="1">te</span></mark></u>', rendered)

    def test_overlapping_existing_chunks_partition_text_without_repeating_it(self):
        item = card(entries=[{"en": [0, 13], "zh": [[0, 5]], "relation": "equivalent"},
                             {"en": [4, 8], "zh": [[0, 2], [1, 3]], "relation": "equivalent"}])
        rendered = self.fields(item)
        self.assertIn('data-chunk-side="en" data-chunk-ids="1 0"', rendered)
        self.assertIn('data-chunk-side="zh" data-chunk-ids="0 1"', rendered)
        self.assertEqual(plain(rendered).count("The rate rose."), 1)
        self.assertEqual(plain(rendered).count("比率上升了。"), 1)

    def test_apkg_and_web_use_same_fields_and_runtime(self):
        item = card()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "test.apkg"
            build_package([item], root, output, max_examples=0)
            with zipfile.ZipFile(output) as archive:
                archive.extract("collection.anki2", root)
            with sqlite3.connect(root / "collection.anki2") as connection:
                fields = connection.execute("SELECT flds FROM notes").fetchone()[0].split("\x1f")
                models = json.loads(connection.execute("SELECT models FROM col").fetchone()[0])
            model = next(iter(models.values()))
        preview = render_preview(item, max_examples=0)
        self.assertIn(fields[7], preview)
        for name in ("card-chunks.js", "card-chunks.css"):
            asset = (Path(__file__).parents[1] / "anki_pipeline" / "templates" / name).read_text()
            self.assertIn(asset, preview)
            self.assertIn(asset, model["css"] if name.endswith("css") else model["tmpls"][0]["afmt"])


class ChunkProjectionTests(unittest.TestCase):
    def source(self, english='The rate rose.', chinese='比率上升了。', entries=None):
        example = card(english, chinese, entries)['examples'][0]
        return {'english': english, 'translation': chinese,
                'alignment': example['translation_alignment']}

    def test_exact_reviewed_chunks_keep_codepoint_ranges_and_source_segmentation(self):
        source = self.source()
        before = copy.deepcopy(source)
        result = project_reviewed_chunks('😀 The rate rose.', '前文比率上升了。', [source])
        self.assertEqual(result['alignments'], [
            {'en': [2, 10], 'zh': [[2, 4]], 'relation': 'equivalent'},
            {'en': [11, 15], 'zh': [[4, 7]], 'relation': 'equivalent'}])
        self.assertEqual(source, before)

    def test_2022_q29_b_keeps_authored_chunks_inside_the_reviewed_complete_translation(self):
        english = 'It is advised in Paragraph 5 that those with one degree should attend on the job training programs.'
        chinese = '第五段建议，已经取得一个学位的人应当参加在职培训课程。'
        stem = self.source('It is advised in Paragraph 5 that those with one degree should ____',
            '第五段建议那些已有一个学位的人应该____。', [
                {'en': [0, 13], 'zh': [[3, 5]], 'relation': 'equivalent'},
                {'en': [17, 28], 'zh': [[0, 3]], 'relation': 'equivalent'},
                {'en': [34, 55], 'zh': [[5, 15]], 'relation': 'equivalent'},
                {'en': [56, 62], 'zh': [[15, 17]], 'relation': 'equivalent'},
                {'en': [63, 67], 'zh': [[17, 21]], 'relation': 'equivalent'}])
        option = self.source('attend on the job training programs.', '参加在职培训课程。', [
            {'en': [0, 6], 'zh': [[0, 2]], 'relation': 'equivalent'},
            {'en': [7, 35], 'zh': [[2, 8]], 'relation': 'equivalent'}])
        alignment = project_reviewed_chunks(english, chinese, [stem, option], sentence_fallback=True)
        self.assertEqual(alignment['alignments'][:-1], [
            {'en': [0, 13], 'zh': [[3, 5]], 'relation': 'equivalent'},
            {'en': [17, 28], 'zh': [[0, 3]], 'relation': 'equivalent'},
            {'en': [63, 69], 'zh': [[18, 20]], 'relation': 'equivalent'},
            {'en': [70, 98], 'zh': [[20, 26]], 'relation': 'equivalent'}])
        item = card(english, chinese, alignment['alignments'])
        item['word'] = 'training'
        rendered = _fields(item, None, 0)[0]['Examples']
        self.assertIn('<mark class="target-word"><span class="card-chunk"', rendered)
        self.assertEqual(plain(rendered).count(english), 1)
        self.assertEqual(plain(rendered).count(chinese), 1)

    def test_reworded_repeated_or_conflicting_fragments_are_never_guessed(self):
        source = self.source('rate', '比率', [{'en': [0, 4], 'zh': [[0, 2]], 'relation': 'equivalent'}])
        for english, chinese in [('rate or rate', '比率'), ('rates', '比例'), ('rate', '比率和比率')]:
            with self.subTest(english=english, chinese=chinese):
                self.assertEqual(project_reviewed_chunks(english, chinese, [source])['alignments'], [])
        other = self.source('rate', '比率数值', [{'en': [0, 4], 'zh': [[2, 4]], 'relation': 'equivalent'}])
        self.assertEqual(project_reviewed_chunks('rate', '比率数值', [source, other])['alignments'], [])

    def test_sentence_correspondence_is_explicit_and_keeps_finer_reviewed_chunks(self):
        result = project_reviewed_chunks('The rate rose.', '比率上升了。', [self.source()], sentence_fallback=True)
        self.assertEqual(len(result['alignments']), 3)
        self.assertEqual(result['alignments'][-1], {'en': [0, 14], 'zh': [[0, 6]],
                         'relation': 'equivalent', 'note': SENTENCE_FALLBACK_NOTE})
        fallback = project_reviewed_chunks('Rate?', '比率？', [], sentence_fallback=True)
        self.assertEqual(fallback['alignments'], [{'en': [0, 5], 'zh': [[0, 3]],
                         'relation': 'equivalent', 'note': SENTENCE_FALLBACK_NOTE}])

    def test_stale_source_does_not_silently_become_a_sentence_fallback(self):
        source = self.source()
        source['alignment']['translationHash'] = '0' * 64
        with self.assertRaises(TranslationAlignmentError):
            project_reviewed_chunks('The rate rose.', '比率上升了。', [source], sentence_fallback=True)


if __name__ == "__main__":
    unittest.main()
