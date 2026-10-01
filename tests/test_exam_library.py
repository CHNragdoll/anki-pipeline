"""Regression checks for the read-only postgraduate sentence import."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from anki_pipeline.exam_library import (digest, library_examples, sentence_cloze_answers,
                                        sentence_ranges)
from anki_pipeline.forms import explicit_forms


def paragraph(paper_id, sentences, translations, *, kind="cloze"):
    source = "The rate rose. They 2 the result."
    text = " ".join(sentences)
    translation = "旧段落译文；不能用于卡片。"
    return {
        "id": paper_id + ":p:b-1-5",
        "paperId": paper_id,
        "title": paper_id,
        "kind": kind,
        "sourceText": source,
        "sourceHash": digest(source),
        "text": text,
        "textHash": digest(text),
        "translation": translation,
        "translationHash": digest(translation),
        "sentences": sentences,
        "sentenceTranslations": translations,
        "sentenceTranslationHashes": [digest(value) if value is not None else None
                                      for value in translations],
    }


class ExamLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = self.root / "data/sources/exam-library/structured/anki-sentences"
        (self.index / "kaoyan").mkdir(parents=True)
        self.card = {"id": 1960, "word": "rate", "word_forms": "过去式: rated",
                     "examples": [{"text": "original example"}], "audio_filename": "rate.mp3"}
        latest = paragraph("kaoyan:2026-01", [
            "The rate rose.", "They rated the result.",
            "The corporate results improved."], [
                "比率上升了。", "他们评价了结果。", "公司业绩改善了。"])
        latest["sourcePath"] = "2026年 ➫ Section II ➫ Part A ➫ Text 5"
        answer_start = latest["text"].index("rated")
        latest["clozeAnswerSpans"] = [{"start": answer_start, "end": answer_start + 5,
                                        "word": "rated", "number": "2"}]
        self.write_catalog([
            ("kaoyan:2026-01", [latest]),
            ("kaoyan:2025-02", [paragraph("kaoyan:2025-02", [
                "Prorate the expense.", "This rate matters."], [
                    "按比例分摊费用。", "这个比率很重要。"])]),
        ])

    def write_catalog(self, papers):
        entries = []
        for paper_id, paragraphs in papers:
            path = "kaoyan/" + paper_id.split(":", 1)[1] + ".json"
            data = {"schema": "anki-sentence-index.v1", "paperId": paper_id,
                    "paragraphs": paragraphs, "excluded": []}
            (self.index / path).write_text(json.dumps(data, ensure_ascii=False))
            entries.append({"paperId": paper_id, "path": path,
                            "digest": digest(json.dumps(data, sort_keys=True, ensure_ascii=False))})
        catalog = {"schema": "anki-sentence-catalog.v1", "category": "kaoyan",
                   "papers": entries}
        (self.index / "index.json").write_text(json.dumps(catalog, ensure_ascii=False))

    def import_cards(self, cards=None):
        return library_examples(self.root, cards if cards is not None else [self.card],
                                "http://localhost:8765", "latex")

    def rewrite_first_index(self, data):
        (self.index / "kaoyan/2026-01.json").write_text(json.dumps(data, ensure_ascii=False))
        catalog_path = self.index / "index.json"
        catalog = json.loads(catalog_path.read_text())
        catalog["papers"][0]["digest"] = digest(json.dumps(data, sort_keys=True,
                                                            ensure_ascii=False))
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False))

    def test_restored_cloze_exact_forms_links_and_unmatched_card_retention(self):
        missing = {"id": 1961, "word": "absent", "word_forms": "",
                   "examples": [{"text": "old example"}]}
        cards, report = self.import_cards([self.card, missing])
        self.assertEqual([card["id"] for card in cards], [1960, 1961])
        self.assertEqual([row["text"] for row in cards[0]["examples"]],
                         ["The rate rose.", "They rated the result.", "This rate matters."])
        self.assertEqual(cards[1]["examples"], [])
        self.assertEqual(cards[0]["audio_filename"], "rate.mp3")
        self.assertEqual(self.card["examples"], [{"text": "original example"}])
        self.assertEqual(report["cards_without_library_examples"], 1)
        self.assertEqual(report["cards"], 2)
        first = cards[0]["examples"][0]
        self.assertEqual(first["translation_scope"], "sentence")
        self.assertEqual(first["translation"], "比率上升了。")
        self.assertNotIn("旧段落译文", first["translation"])
        self.assertEqual(first["source"], "2026年 ➫ Section II ➫ Part A ➫ Text 5")
        self.assertEqual(first["cloze_answers"], [])
        self.assertEqual(cards[0]["examples"][1]["cloze_answers"], [
            {"start": 5, "end": 10, "word": "rated", "number": 2}])
        self.assertEqual(cards[0]["examples"][-1]["source"], "kaoyan:2025-02")
        self.assertEqual(cards[0]["examples"][-1]["cloze_answers"], [])
        self.assertIn("anki-paragraph=kaoyan%3A2026-01%3Ap%3Ab-1-5", first["latex_url"])
        self.assertIn("anki-sentence=0", first["full_paper_url"])
        self.assertIn("paper=kaoyan%3A2026-01", first["full_paper_url"])

    def test_catalog_rejects_non_kaoyan_and_escaping_paths(self):
        catalog_path = self.index / "index.json"
        original = json.loads(catalog_path.read_text())
        (self.index.parent / "outside.json").write_text("{}")
        for changed in (
            {**original, "category": "cet4"},
            {**original, "papers": [{**original["papers"][0], "paperId": "cet4:2026-01"}]},
            {**original, "papers": [{**original["papers"][0], "path": "../outside.json"}]},
        ):
            catalog_path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                self.import_cards()
        catalog_path.write_text(json.dumps(original))
        outside = self.root / "outside.json"
        outside.write_text("{}")
        (self.index / "kaoyan" / "escape.json").symlink_to(outside)
        original["papers"][0]["path"] = "kaoyan/escape.json"
        catalog_path.write_text(json.dumps(original))
        with self.assertRaisesRegex(ValueError, "路径越界"):
            self.import_cards()

    def test_index_and_source_hash_tampering_rejected(self):
        path = self.index / "kaoyan/2026-01.json"
        data = json.loads(path.read_text())
        data["paragraphs"][0]["text"] = "A changed sentence."
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "索引已变化"):
            self.import_cards()

        data["paragraphs"][0]["textHash"] = digest(data["paragraphs"][0]["text"])
        data["paragraphs"][0]["sourceText"] = "Unverified source."
        self.rewrite_first_index(data)
        with self.assertRaisesRegex(ValueError, "句子或译文索引不一致"):
            self.import_cards()

    def test_source_path_is_covered_by_catalog_digest_and_must_be_nonempty(self):
        path = self.index / "kaoyan/2026-01.json"
        original = json.loads(path.read_text())
        changed = json.loads(json.dumps(original))
        changed["paragraphs"][0]["sourcePath"] = "2026年 ➫ changed"
        path.write_text(json.dumps(changed, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "索引已变化"):
            self.import_cards()
        for value in ("", "   ", None, ["2026年"]):
            with self.subTest(value=value):
                changed = json.loads(json.dumps(original))
                changed["paragraphs"][0]["sourcePath"] = value
                self.rewrite_first_index(changed)
                with self.assertRaisesRegex(ValueError, "出处路径无效"):
                    self.import_cards()

    def test_cloze_spans_are_bound_to_completed_text_and_validate_position(self):
        path = self.index / "kaoyan/2026-01.json"
        original = json.loads(path.read_text())
        changed = json.loads(json.dumps(original))
        changed["paragraphs"][0]["clozeAnswerSpans"][0]["start"] += 1
        path.write_text(json.dumps(changed, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "索引已变化"):
            self.import_cards()
        for change in ("wrong_word", "past_end", "backwards", "overlap",
                       "cross_sentence", "bad_number", "wrong_type"):
            with self.subTest(change=change):
                data = json.loads(json.dumps(original))
                row = data["paragraphs"][0]
                span = row["clozeAnswerSpans"][0]
                if change == "wrong_word":
                    span["word"] = "rate"
                elif change == "past_end":
                    span["end"] = len(row["text"]) + 1
                elif change == "backwards":
                    span["end"] = span["start"]
                elif change == "overlap":
                    row["clozeAnswerSpans"].append(dict(span))
                elif change == "cross_sentence":
                    span["start"] = row["text"].index("rose.") + 4
                    span["end"] = row["text"].index("They") + 2
                    span["word"] = row["text"][span["start"]:span["end"]]
                elif change == "bad_number":
                    span["number"] = 0
                else:
                    row["clozeAnswerSpans"] = {"start": span["start"]}
                self.rewrite_first_index(data)
                with self.assertRaisesRegex(ValueError, "完形答案"):
                    self.import_cards()

    def test_repeated_sentence_maps_answer_to_second_occurrence(self):
        text = "The rate rose. The rate rose."
        sentences = ["The rate rose.", "The rate rose."]
        ranges = sentence_ranges(text, sentences, "repeated")
        self.assertEqual(ranges, [(0, 14), (15, 29)])
        span = {"start": 19, "end": 23, "word": "rate", "number": 2}
        answers = sentence_cloze_answers({"id": "repeated", "text": text,
                                          "clozeAnswerSpans": [span]}, ranges)
        self.assertEqual(answers, [[], [{"start": 4, "end": 8,
                                         "word": "rate", "number": 2}]])

    def test_default_exports_sixth_and_older_year_even_for_same_sentence(self):
        papers = []
        for year in range(2000, 2007):
            paper_id = f"kaoyan:{year}-01"
            row = paragraph(paper_id, ["The rate rose."], ["比率上升了。"])
            row["sourcePath"] = f"{year}年考研英语 ➫ Section II ➫ Part A ➫ Text 5"
            papers.append((paper_id, [row]))
        self.write_catalog(papers)

        cards, report = self.import_cards()
        examples = cards[0]["examples"]
        self.assertEqual(len(examples), 7)
        self.assertEqual(report["examples"], 7)
        self.assertEqual([row["paragraph_id"].split(":")[1] for row in examples],
                         [f"{year}-01" for year in range(2006, 1999, -1)])
        self.assertEqual([row["text"] for row in examples], ["The rate rose."] * 7)
        self.assertIn("2000年考研英语", examples[-1]["source"])

        capped, capped_report = library_examples(self.root, [self.card],
                                                  "http://localhost:8765", "latex", maximum=5)
        self.assertEqual(len(capped[0]["examples"]), 5)
        self.assertEqual(capped_report["examples"], 5)

    def test_analytic_comparative_does_not_match_more_or_most_alone(self):
        forms = "比较级：evener或more even | 最高级：evenest或most even"
        self.assertEqual(explicit_forms(forms), {"evener", "evenest"})
        self.assertEqual(explicit_forms("比较级：more direct | 最高级：most direct"), set())
        paper_id = "kaoyan:2026-01"
        row = paragraph(paper_id, ["Most people left.", "More people arrived.",
                                   "They even listened.", "A more even result emerged."],
                        ["多数人走了。", "更多人来了。", "他们甚至听了。", "更均匀的结果出现了。"])
        self.write_catalog([(paper_id, [row])])
        card = {"id": 1, "word": "even", "word_forms": forms, "examples": []}
        result, report = self.import_cards([card])
        self.assertEqual([example["text"] for example in result[0]["examples"]],
                         ["They even listened.", "A more even result emerged."])
        self.assertEqual(report["examples"], 2)

    def test_exam_import_uses_only_lemma_and_declared_forms(self):
        paper_id = "kaoyan:2026-01"
        row = paragraph(paper_id, ["The customer waited.", "Several customers waited."],
                        ["顾客等候。", "几位顾客等候。"])
        self.write_catalog([(paper_id, [row])])
        card = {"id": 1, "word": "customer", "word_forms": "", "examples": []}
        result, _ = self.import_cards([card])
        self.assertEqual([example["text"] for example in result[0]["examples"]],
                         ["The customer waited."])
        card["word_forms"] = "复数：customers"
        result, _ = self.import_cards([card])
        self.assertEqual([example["text"] for example in result[0]["examples"]],
                         ["The customer waited.", "Several customers waited."])

    def test_declared_us_heading_spelling_matches_without_inferred_inflections(self):
        paper_id = "kaoyan:2026-01"
        row = paragraph(paper_id, ["Her humor helped.", "His humour helped.",
                                   "Their humors differed."],
                        ["她的幽默有所帮助。", "他的幽默有所帮助。", "他们的情绪不同。"])
        self.write_catalog([(paper_id, [row])])
        word = "humour\n(美humor)"
        card = {"id": 1960, "word": word, "word_forms": "", "examples": [],
                "audio_filename": "humour.mp3"}
        result, _ = self.import_cards([card])
        self.assertEqual(result[0]["word"], word)
        self.assertEqual(result[0]["id"], 1960)
        self.assertEqual(result[0]["audio_filename"], "humour.mp3")
        self.assertEqual([example["text"] for example in result[0]["examples"]],
                         ["Her humor helped.", "His humour helped."])

    def test_dictionary_forms_replace_legacy_and_exclude_derivatives(self):
        paper_id = "kaoyan:2026-01"
        sentences = ["Her ambition grew.", "His ambitions grew.",
                     "They ambitioned success.", "They are ambitious.",
                     "They are ambitionless.", "Their ambitioning persisted."]
        self.write_catalog([(paper_id, [paragraph(paper_id, sentences,
                           [f"逐句译文 {index}" for index in range(len(sentences))])])])
        card = {"id": "ambition", "word": "ambition", "word_forms": "复数：ambitious",
                "examples": [], "ecdict": {"exchange": "i:ambitioning"},
                "local_dictionary": {"forms_source": "webster", "forms": [
                    {"kind": "plural", "form": "ambitions"},
                    {"kind": "past", "form": "ambitioned"}],
                    "derived": [{"word": "ambitious"}, {"word": "ambitionless"}]}}
        original = json.loads(json.dumps(card))
        inputs = {path: path.read_bytes() for path in self.index.rglob("*.json")}
        result, _ = self.import_cards([card])
        self.assertEqual([example["text"] for example in result[0]["examples"]], sentences[:3])
        self.assertEqual([example["translation"] for example in result[0]["examples"]],
                         ["逐句译文 0", "逐句译文 1", "逐句译文 2"])
        self.assertEqual(card, original)
        self.assertEqual(inputs, {path: path.read_bytes() for path in inputs})

    def test_webster_parent_owned_forms_do_not_select_parent_sentences(self):
        sentences = ["These means are reliable.", "We know the meaning.",
                     "They meant to leave.", "Customs checks the goods.",
                     "A custom matters."]
        self.write_catalog([("kaoyan:2026-01", [paragraph(
            "kaoyan:2026-01", sentences,
            ["这些方法可靠。", "我们知道含义。", "他们原打算离开。",
             "海关检查货物。", "一种习俗很重要。"], kind="reading")])])
        cards = [
            {"id": 1, "word": "means", "local_dictionary": {"forms_source": "webster",
             "forms": [{"kind": "plural", "form": "means", "base": "mean"},
                       {"kind": "present_participle", "form": "meaning", "base": "mean"},
                       {"kind": "past", "form": "meant", "base": "mean"}]}},
            {"id": 2, "word": "customs", "local_dictionary": {"forms_source": "webster",
             "forms": [{"kind": "plural", "form": "customs", "base": "custom"}]}}]
        actual, _ = self.import_cards(cards)
        self.assertEqual([e["text"] for e in actual[0]["examples"]], [sentences[0]])
        self.assertEqual([e["text"] for e in actual[1]["examples"]], [sentences[3]])

    def test_ecdict_fallback_matches_irregular_forms_without_parent_aliases(self):
        paper_id = "kaoyan:2026-01"
        sentences = ["They ran away.", "They run daily.", "The runner arrived.",
                     "Their means worked.", "They mean well.",
                     "The customs opened.", "The custom persisted."]
        self.write_catalog([(paper_id, [paragraph(paper_id, sentences,
                           [f"译文 {index}" for index in range(len(sentences))])])])
        cards = [{"id": word, "word": word, "word_forms": "", "examples": [],
                  "local_dictionary": {"forms_source": "ecdict", "forms": forms,
                                       "derived": []}}
                 for word, forms in (
                     ("run", [{"kind": "past", "form": "ran"}]),
                     ("means", [{"kind": "base", "form": "mean"}]),
                     ("customs", [{"kind": "base", "form": "custom"}]))]
        result, _ = self.import_cards(cards)
        self.assertEqual([[example["text"] for example in card["examples"]]
                          for card in result],
                         [sentences[:2], [sentences[3]], [sentences[5]]])

    def test_null_sentence_translation_is_skipped_without_paragraph_fallback(self):
        data = json.loads((self.index / "kaoyan/2026-01.json").read_text())
        data["paragraphs"][0]["sentenceTranslations"][0] = None
        data["paragraphs"][0]["sentenceTranslationHashes"][0] = None
        self.rewrite_first_index(data)
        cards, report = self.import_cards()
        self.assertEqual([row["text"] for row in cards[0]["examples"]],
                         ["They rated the result.", "This rate matters."])
        self.assertEqual(report["sentences_without_aligned_translation"], 1)
        self.assertEqual(report["skipped_unaligned_matches"], 1)
        self.assertTrue(all("旧段落译文" not in row["translation"]
                            for row in cards[0]["examples"]))

    def test_missing_misaligned_or_tampered_sentence_translation_rejected(self):
        original = json.loads((self.index / "kaoyan/2026-01.json").read_text())
        for change in ("missing", "short", "bad_hash", "half_null"):
            with self.subTest(change=change):
                data = json.loads(json.dumps(original))
                row = data["paragraphs"][0]
                if change == "missing":
                    del row["sentenceTranslations"]
                elif change == "short":
                    row["sentenceTranslations"].pop()
                elif change == "bad_hash":
                    row["sentenceTranslations"][0] = "未经核实的译文。"
                else:
                    row["sentenceTranslations"][0] = None
                self.rewrite_first_index(data)
                with self.assertRaisesRegex(ValueError, "句子译文"):
                    self.import_cards()

    def test_missing_match_does_not_write_source_database_or_index(self):
        source = self.root / "original.sqlite3"
        with sqlite3.connect(source) as connection:
            connection.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY, word TEXT)")
            connection.execute("INSERT INTO cards VALUES (1960, 'rate')")
        before = {path: path.read_bytes() for path in [source, *self.index.rglob("*.json")]}
        cards, report = self.import_cards([{"id": 1960, "word": "zzmissing",
                                           "word_forms": "", "examples": []}])
        self.assertEqual(len(cards), 1)
        self.assertEqual(report["cards_without_library_examples"], 1)
        self.assertFalse(report["database_modified"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_url_and_reader_validation(self):
        for url in ("file:///tmp", "http://user:secret@localhost:8765",
                    "http://localhost:8765/?query=1", "http://localhost:8765/#frag"):
            with self.assertRaises(ValueError):
                library_examples(self.root, [self.card], url, "latex")
        with self.assertRaises(ValueError):
            library_examples(self.root, [self.card], "http://localhost:8765", "unknown")
        for value in (-1, True, 1.5):
            with self.assertRaisesRegex(ValueError, "max_examples"):
                library_examples(self.root, [self.card], "http://localhost:8765",
                                 "latex", maximum=value)

    def test_frequency_counts_each_whole_token_and_retains_exact_examples(self):
        paper_id = "kaoyan:2026-01"
        sentences = ["Rate rates RATE.", "Prorate the expense."]
        row = paragraph(paper_id, sentences, ["比率、各比率、比率。", "按比例分摊。"],
                        kind="reading")
        self.write_catalog([(paper_id, [row])])
        card = {**self.card, "word_forms": "复数：rates"}
        original = json.loads(json.dumps(card))
        inputs = {path: path.read_bytes() for path in self.index.rglob("*.json")}

        actual, report = self.import_cards([card])

        self.assertEqual(actual[0]["exam_frequency"], {
            "schema": "kaoyan-frequency.v1", "occurrences": 3,
            "matched_sentences": 1, "paper_count": 1, "corpus_papers": 1,
            "stars": 1.5, "rule": "occurrence-bands.v1"})
        self.assertEqual(actual[0]["examples"][0]["text"], sentences[0])
        self.assertEqual(actual[0]["examples"][0]["translation"], "比率、各比率、比率。")
        self.assertEqual(actual[0]["examples"][0]["sentence_index"], 0)
        self.assertEqual(report["frequency"]["total_occurrences"], 3)
        self.assertEqual(report["frequency"]["nonzero_cards"], 1)
        self.assertEqual(report["frequency"]["star_distribution"]["1.5"], 1)
        self.assertEqual(report["frequency"]["cards"][0], {
            "id": card["id"], "word": card["word"],
            "exam_frequency": actual[0]["exam_frequency"]})
        self.assertEqual(report["frequency"]["corpus"]["kinds"], {
            "reading": {"paragraphs": 1, "sentences": 2}})
        self.assertEqual(card, original)
        self.assertEqual(inputs, {path: path.read_bytes() for path in inputs})

    def test_frequency_scans_all_sources_despite_display_cap_and_missing_translation(self):
        latest = paragraph("kaoyan:2026-01", ["Rate rates RATE.", "Rate rate."],
                           ["比率、各比率、比率。", None], kind="reading")
        older = paragraph("kaoyan:2000-01", ["The rate rose."], ["比率上升。"])
        self.write_catalog([("kaoyan:2026-01", [latest]),
                            ("kaoyan:2000-01", [older])])
        card = {**self.card, "word_forms": "复数：rates"}
        complete, complete_report = self.import_cards([card])
        capped, report = library_examples(self.root, [card], "http://localhost:8765",
                                         "latex", maximum=1)

        self.assertEqual(len(capped[0]["examples"]), 1)
        self.assertEqual(capped[0]["examples"], complete[0]["examples"][:1])
        self.assertEqual(capped[0]["exam_frequency"], complete[0]["exam_frequency"])
        self.assertEqual(capped[0]["exam_frequency"], {
            "schema": "kaoyan-frequency.v1", "occurrences": 6,
            "matched_sentences": 3, "paper_count": 2, "corpus_papers": 2,
            "stars": 2.0, "rule": "occurrence-bands.v1"})
        self.assertEqual(report["frequency"], complete_report["frequency"])
        self.assertEqual(report["skipped_unaligned_matches"], 1)
        corpus = report["frequency"]["corpus"]
        self.assertEqual(corpus["scope"], "indexed_english_sentences")
        self.assertEqual(corpus["paper_ids"], ["kaoyan:2000-01", "kaoyan:2026-01"])
        self.assertEqual((corpus["year_start"], corpus["year_end"]), (2000, 2026))
        self.assertEqual(corpus["paragraph_count"], 2)
        self.assertEqual(corpus["sentence_count"], 3)
        self.assertEqual(corpus["sentences_without_aligned_translation"], 1)
        self.assertEqual(corpus["missing_translation_policy"],
                         "english_counted_examples_skipped")

    def test_frequency_identical_text_at_distinct_source_positions_counts_each(self):
        paper_id = "kaoyan:2026-01"
        first = paragraph(paper_id, ["The rate rose."] * 2, ["比率上升。"] * 2)
        second = paragraph(paper_id, ["The rate rose."], ["比率上升。"])
        second["id"] = paper_id + ":p:b-1-6"
        older_id = "kaoyan:2000-01"
        older = paragraph(older_id, ["The rate rose."], ["比率上升。"])
        self.write_catalog([(paper_id, [first, second]), (older_id, [older])])

        cards, _ = self.import_cards()

        frequency = cards[0]["exam_frequency"]
        self.assertEqual(frequency["occurrences"], 4)
        self.assertEqual(frequency["matched_sentences"], 4)
        self.assertEqual(frequency["paper_count"], 2)
        self.assertEqual(len(cards[0]["examples"]), 4)
        self.assertEqual([e["sentence_index"] for e in cards[0]["examples"]], [0, 1, 0, 0])

    def test_duplicate_paragraph_identity_fails_closed_before_frequency_counting(self):
        paper_id = "kaoyan:2026-01"
        first = paragraph(paper_id, ["The rate rose."], ["比率上升。"])
        for duplicate in (dict(first),
                          paragraph(paper_id, ["A rate matters."], ["比率很重要。"]),
                          paragraph("kaoyan:2000-01", ["A rate matters."], ["比率很重要。"] )):
            with self.subTest(duplicate=duplicate["text"]):
                duplicate["id"] = first["id"]
                if duplicate["paperId"] == paper_id:
                    papers = [(paper_id, [first, duplicate])]
                else:
                    papers = [(paper_id, [first]), (duplicate["paperId"], [duplicate])]
                self.write_catalog(papers)
                with self.assertRaisesRegex(ValueError, "段落 ID 重复"):
                    self.import_cards()

    def test_frequency_uses_chosen_inflections_and_excludes_derived_and_parent_lemmas(self):
        paper_id = "kaoyan:2026-01"
        sentences = ["Ambition ambitions ambitioned.", "Ambitious ambitionless ambitioning.",
                     "These means work.", "The meaning meant something.",
                     "We run and ran.", "The runner ran away.", "The custom lasts.",
                     "Customs matters."]
        self.write_catalog([(paper_id, [paragraph(paper_id, sentences,
                           [f"译文 {index}" for index in range(len(sentences))])])])
        cards = [
            {"id": 1, "word": "ambition", "word_forms": "复数：ambitious",
             "ecdict": {"exchange": "i:ambitioning"},
             "local_dictionary": {"forms_source": "webster", "forms": [
                 {"kind": "plural", "form": "ambitions", "base": "ambition"},
                 {"kind": "past", "form": "ambitioned", "base": "ambition"}],
                 "derived": [{"word": "ambitious"}, {"word": "ambitionless"}]}},
            {"id": 2, "word": "means", "local_dictionary": {"forms_source": "webster",
             "forms": [{"kind": "present_participle", "form": "meaning", "base": "mean"},
                       {"kind": "past", "form": "meant", "base": "mean"}]}},
            {"id": 3, "word": "run", "local_dictionary": {"forms_source": "ecdict",
             "forms": [{"kind": "past", "form": "ran"}]}},
            {"id": 4, "word": "customs", "local_dictionary": {"forms_source": "ecdict",
             "forms": [{"kind": "base", "form": "custom"}]}},
            {"id": 5, "word": "absent", "local_dictionary": {"forms_source": "", "forms": []}}]

        actual, report = self.import_cards(cards)

        self.assertEqual([c["exam_frequency"]["occurrences"] for c in actual], [3, 1, 3, 1, 0])
        self.assertEqual([c["exam_frequency"]["matched_sentences"] for c in actual], [1, 1, 2, 1, 0])
        self.assertEqual(actual[-1]["exam_frequency"]["stars"], 0.0)
        self.assertEqual(actual[-1]["exam_frequency"]["paper_count"], 0)
        self.assertEqual(report["frequency"]["total_occurrences"], 8)
        self.assertEqual(report["frequency"]["nonzero_cards"], 4)
        self.assertEqual(report["frequency"]["star_distribution"]["0.0"], 1)


if __name__ == "__main__":
    unittest.main()
