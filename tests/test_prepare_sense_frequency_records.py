import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest


PATH = Path(__file__).resolve().parents[1] / "scripts/prepare_sense_frequency_records.py"
SPEC = importlib.util.spec_from_file_location("prepare_sense_frequency_records", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InventoryPreparationTests(unittest.TestCase):
    def test_offset_index_seeks_utf8_records_without_codepoint_confusion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            records = [{"book_id": "book", "card_id": str(n), "word": word,
                        "expected_occurrences": n, "senses": [{"text": "中文释义"}]}
                       for n, word in enumerate(("minute", "a/an"))]
            path.write_text("".join(MODULE.canonical_json(x) + "\n" for x in records), encoding="utf-8")
            index = MODULE.write_offset_index(path)
            self.assertEqual(index["bytes"], path.stat().st_size)
            with path.open("rb") as stream:
                for row, record in zip(index["records"], records):
                    stream.seek(row["byte_offset"])
                    self.assertEqual(json.loads(stream.read(row["byte_length"])), record)

    def test_parent_entry_forms_cannot_expand_a_different_headword(self):
        forms = object.__new__(MODULE.DisplayedForms)
        forms.cache = {"means": [{"kind": "present_participle", "label": "现在分词", "form": "meaning", "base": "mean"}]}
        variants, evidence, issues = forms.variants({"word": "means", "form_sections": [
            {"source": "webster", "rows": [{"label": "现在分词", "form": "meaning"}]}]})
        self.assertEqual(variants, {"means"})
        self.assertEqual(evidence[0]["accepted_match_forms"], [])
        self.assertEqual(issues, [])

    def test_slash_title_licenses_exact_components_with_separate_counts(self):
        forms = object.__new__(MODULE.DisplayedForms)
        forms.cache = {}
        variants, _, _ = forms.variants({"word": "a/an", "form_sections": []})
        self.assertEqual(variants, {"a", "an"})
        page = '<div id="preview-back"><h3>a</h3><section data-occurrences="4"></section><div class="dictionary-definition" data-dictionary="oxford"><div class="sense-unlabelled">一</div></div><h3>an</h3><section data-occurrences="2"></section><div class="dictionary-definition" data-dictionary="reviewed"><div class="sense-unlabelled">一个</div></div></div>'
        parsed = MODULE.parse_card_page(page, {})
        self.assertEqual(parsed["declared_counts"], [4, 2])
        self.assertEqual(len(parsed["definitions"]), 2)
        self.assertEqual(parsed["definitions"][1]["sense_start"], 1)
        self.assertEqual([x["headword"] for x in parsed["definitions"]], ["a", "an"])

    def test_shipped_class_aliases_and_source_inflections(self):
        page = '''<div id="preview-back" hidden>
          <section data-occurrences="2"></section>
          <div class="_r11" data-dictionary="oxford">
            <div class="_r12"><span class="_r13">v.</span><span class="_r14">限制 &amp; 约束</span></div>
          </div>
          <div class="_r19 _r20" data-dictionary="webster">
            <section class="_r21"><dl class="_r23"><dt>过去式</dt><dd>constrained <small>an inflection note</small></dd></dl></section>
            <section class="dictionary-derived"><dl class="_r23 derived-word"><dt>名词</dt><dd>constraint</dd></dl></section>
          </div></div>'''
        aliases = {"_r11": "dictionary-definition", "_r12": "sense-row", "_r13": "sense-pos", "_r14": "sense-text",
                   "_r19": "dictionary-form-groups", "_r20": "dictionary-forms", "_r21": "dictionary-inflections", "_r23": "form-row"}
        parsed = MODULE.parse_card_page(page, aliases)
        self.assertEqual(parsed["senses"], [{"pos": "v.", "text": "限制 & 约束"}])
        self.assertEqual(parsed["form_sections"], [{"source": "webster", "rows": [{"label": "过去式", "form": "constrained"}]}])
        self.assertEqual(parsed["declared_counts"], [2])

    def test_only_answer_definition_is_read(self):
        front = '<div class="dictionary-definition" data-dictionary="wordbook"><div class="sense-row"><span class="sense-text">Not the answer</span></div></div>'
        back = '<div id="preview-back"><div class="dictionary-definition" data-dictionary="reviewed"><div class="sense-row"><span class="sense-text">Correct answer</span></div></div></div>'
        self.assertEqual(MODULE.parse_card_page(front + back, {})["senses"], [{"pos": "", "text": "Correct answer"}])

    def test_index_matches_existing_boundary_regex_including_compounds(self):
        text = "pre-existing worker's worker-workers’ own; sixteen six; x_part; part-time."
        variants = {"pre-existing", "pre", "existing", "worker", "worker's", "s", "workers", "six", "part", "part-time", "time"}
        rows = [{"english": text}]
        index = MODULE.token_index(rows, variants)
        for variant in variants:
            expected = [list(m.span()) for m in re.finditer(r"(?<!\w)" + re.escape(variant) + r"(?!\w)", text, re.I)]
            self.assertEqual([span for _, span in index.get(variant, [])], expected, variant)

    def test_each_unicode_position_keeps_its_exact_alignment_evidence(self):
        row = {"id": "kaoyan:2020-01:p:b-1-1:0", "paperId": "kaoyan:2020-01",
               "english": "It’s minute by minute.", "englishHash": "hash", "translationZh": "逐分钟推进。",
               "alignments": [{"en": [5, 11], "zh": [[1, 3]], "relation": "equivalent"},
                              {"en": [15, 21], "zh": [[1, 3]], "relation": "equivalent"}],
               "canonical_occurrence_key": ["physical-key"], "reviewedContentHash": "review-hash",
               "sourceHash": "source-hash", "source_sentence_ids": ["sid"], "sourceBlockIds": ["bid"],
               "sourceFragments": [], "sourceSentenceRefs": [], "paragraphId": "paragraph",
               "start": 0, "end": 22, "translation_alignment": {"schema": "codex-sentence-alignment.v1", "alignments": []}}
        paths = {row["id"]: {"components": ["2020年考研英语一", "Text 1"]}}
        first, second = (MODULE.occurrence(row, span, paths) for span in ([5, 11], [15, 21]))
        self.assertEqual(first["translation_ranges"], [[1, 3]])
        self.assertEqual(second["target_range"], [15, 21])
        self.assertEqual(first["alignment_evidence"][0]["english_range"], [5, 11])
        self.assertEqual(second["alignment_evidence"][0]["english_range"], [15, 21])
        self.assertEqual(second["status"], "unmatched")
        self.assertEqual(second["alignment"], row["translation_alignment"])
        self.assertIsNone(second["sense_index"])


if __name__ == "__main__":
    unittest.main()
