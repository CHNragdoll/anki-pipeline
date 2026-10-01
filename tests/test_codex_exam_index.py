"""Reviewed Codex data is isolated, complete and bound to exact source bytes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from lxml import html

from anki_pipeline.packaging import _fields
from tests.test_packaging import card


PAPERS = tuple(f"{year}-{series}" for year in range(2000, 2027)
               for series in (("01",) if year < 2010 else ("01", "02")))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def rendered_text(element):
    """Read visible text independent of transparent authored chunk wrappers."""
    source = copy.deepcopy(element)
    for line_break in list(source.iter('br')):
        line_break.tail = '\n' + (line_break.tail or '')
        line_break.drop_tag()
    return source.text_content()


def marked_ranges(element):
    """Observe actual highlighted offsets, including nested chunk spans."""
    cursor, ranges = 0, []
    def visit(node):
        nonlocal cursor
        start = cursor
        cursor += len(node.text or '')
        for child in node:
            visit(child)
            cursor += len(child.tail or '')
        if node.tag == 'mark' and node.get('class') == 'target-word':
            ranges.append((start, cursor))
    visit(element)
    return ranges


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sha(path.read_bytes())


def record(name="2026-01", english="The rate rose.", translation="比率上升了。",
           alignments=None, *, identifier=None, kind="reading", source=None,
           context=None, cloze_answers=None):
    paper_id = "kaoyan:" + name
    identifier = identifier or paper_id + ":p:b-1-5"
    source = english if source is None else source
    context = context or {"sourcePath": name + " ➫ Reading",
                          "sourceBlockIds": [paper_id + ":b-1-5"]}
    sentence = {"id": identifier + ":0", "start": 0, "end": len(english),
                "english": english, "clozeAnswers": cloze_answers or []}
    paragraph = {"id": identifier, "kind": kind, "sourceHash": sha(source),
                 "sourceEnglish": source, "filledEnglish": english,
                 "context": context, "sentences": [sentence]}
    if alignments is None:
        alignments = [{"en": [4, 8], "zh": [[0, 2]], "relation": "equivalent"}]
    translated = {"id": identifier, "sourceHash": sha(source), "sentences": [
        {"id": sentence["id"], "englishHash": sha(english),
         "translationZh": translation, "alignments": alignments}]}
    return paragraph, translated


def write_fixture(root, *, names=("2026-01",), scope="partial", records=None,
                  reviewed=True):
    """Write only controlled fixture data; unused input inventory rows remain empty."""
    records = records or {}
    inventory = []
    index_rows = []
    for name in PAPERS:
        pairs = records.get(name, [record(name)]) if name in names else []
        paragraphs, translated_paragraphs = zip(*pairs) if pairs else ([], [])
        source = {"schema": "codex-exam-translation-input.v1", "paperId": "kaoyan:" + name,
                  "paragraphs": list(paragraphs), "blocked": []}
        translations = {"schema": "codex-exam-translations.v1", "paperId": source["paperId"],
                        "paragraphs": list(translated_paragraphs)}
        counts = {"paragraphs": len(paragraphs), "sentences": sum(
            len(p["sentences"]) for p in paragraphs), "blocked": 0,
            "sourceParagraphs": len(paragraphs)}
        if name in names:
            input_hash = write_json(root / "inputs" / (name + ".json"), source)
            translation_hash = write_json(root / "translations" / (name + ".json"), translations)
            sentence_rows = []
            for paragraph, translated in pairs:
                by_id = {s["id"]: s for s in translated["sentences"]}
                for sentence in paragraph["sentences"]:
                    t = by_id[sentence["id"]]
                    sentence_rows.append({
                        "id": sentence["id"], "paperId": source["paperId"],
                        "paragraphId": paragraph["id"], "kind": paragraph["kind"],
                        "sourcePath": paragraph["context"].get("sourcePath") or
                                      paragraph["context"].get("questionId"),
                        "context": paragraph["context"],
                        "sourceBlockIds": paragraph["context"].get("sourceBlockIds", []),
                        "sourceHash": paragraph["sourceHash"],
                        "sourceEnglish": paragraph["sourceEnglish"],
                        "filledEnglish": paragraph["filledEnglish"],
                        "start": sentence["start"], "end": sentence["end"],
                        "english": sentence["english"], "englishHash": sha(sentence["english"]),
                        "clozeAnswers": sentence['clozeAnswers'],
                        "translationZh": t["translationZh"], "translationHash": sha(t["translationZh"]),
                        "alignments": t["alignments"],
                        "reviewedContentHash": sha(t["translationZh"] + "\0" + json.dumps(t["alignments"],
                            ensure_ascii=False, separators=(",", ":"))),
                        "sourceFragments": paragraph["context"].get("sourceFragments", []),
                        "sourceSentenceRefs": [ref for ref in paragraph["context"].get(
                            "sourceSentenceRefs", []) if ref["targetSentenceId"] == sentence["id"]],
                    })
            index_hash = write_json(root / "index" / (name + ".json"), {
                "schema": "codex-exam-sentence-index.v1", "paperId": source["paperId"],
                "sentences": sentence_rows})
            review_hash = None
            if reviewed:
                review_hash = write_json(root / "reviews" / (name + ".json"), {
                    "schema": "codex-exam-translation-review.v1", "paperId": source["paperId"],
                    "approved": True, "inputHash": input_hash, "translationHash": translation_hash,
                    "method": "Independent full sentence and alignment review", "issues": [],
                    "reviewedSentences": counts["sentences"],
                    "reviewedAlignments": sum(len(s["alignments"]) for s in sentence_rows)})
            index_rows.append({"paperId": source["paperId"], "indexFile": name + ".json",
                "indexHash": index_hash, "inputHash": input_hash, "translationHash": translation_hash,
                "reviewHash": review_hash, "semanticReviewStatus": "approved" if reviewed else "unreviewed",
                "paragraphs": counts["paragraphs"], "sentences": counts["sentences"],
                "alignments": sum(len(s["alignments"]) for s in sentence_rows), "blocked": 0})
        else:
            input_hash = "0" * 64
        inventory.append({"paperId": source["paperId"], "file": "inputs/" + name + ".json",
                          "sha256": input_hash, **counts})
    input_manifest_hash = write_json(root / "manifest.json", {
        "schema": "codex-exam-translation-manifest.v1", "papers": inventory,
        "totals": {key: sum(r[key] for r in inventory) for key in
                   ("paragraphs", "sentences", "blocked", "sourceParagraphs")}})
    totals = {"papers": len(index_rows), **{key: sum(r[key] for r in index_rows)
              for key in ("paragraphs", "sentences", "alignments", "blocked")}}
    write_json(root / "index/manifest.json", {
        "schema": "codex-exam-sentence-index-manifest.v1", "scope": scope,
        "semanticReviewStatus": "approved" if reviewed else "unreviewed",
        "papers": index_rows, "totals": totals, "inputManifestHash": input_manifest_hash})


class CodexAlignedPackagingTests(unittest.TestCase):
    def test_trimmed_source_whitespace_does_not_shift_pinned_target(self):
        from anki_pipeline.packaging import _highlight_example
        self.assertEqual(_highlight_example(' rate ', 'rate', '', [], declared_only=True,
                                           target_ranges=[(1, 5)]), '<mark class="target-word">rate</mark>')

    def example(self, english="The rate rose.", translation="比率上升了。", alignments=None):
        return {"text": english, "source": "Codex fixture", "translation": translation,
                "translation_source": "codex", "translation_alignment": {
                    "schema": "codex-sentence-alignment.v1", "englishHash": sha(english),
                    "translationHash": sha(translation), "alignments": alignments or [
                        {"en": [4, 8], "zh": [[0, 2]], "relation": "equivalent"}]}}

    def test_alignment_metadata_keeps_chinese_plain_and_english_highlighted(self):
        value = card(audio="")
        value["examples"] = [self.example()]
        content = _fields(value, None, 0)[0]["Examples"]
        markup = html.fragment_fromstring(content)
        self.assertEqual(rendered_text(markup.find_class('example-translation')[0]), '翻译 比率上升了。')
        self.assertNotIn('term-highlight', content)
        self.assertNotIn('<style>', content)
        self.assertEqual(marked_ranges(markup.find_class('example-text')[0]), [(4, 8)])
        del value["examples"][0]["translation_alignment"]
        value["examples"][0].pop("translation_source")
        self.assertNotIn('class="term-highlight"', _fields(value, None, 0)[0]["Examples"])

    def test_structural_validation_does_not_certify_semantics_or_rewrite_translation(self):
        english = "His ambition showed."
        zh = '  他的雄心表明了一个愿望。\n下一行 <script>alert(1)</script> & "原文"  '
        start = zh.index("表明了")
        value = card(word="ambition", audio="")
        value["examples"] = [self.example(english, zh, [
            {"en": [4, 12], "zh": [[start, start + 3]], "relation": "equivalent"}])]
        before = copy.deepcopy(value)
        content = _fields(value, None, 0)[0]["Examples"]
        markup = html.fragment_fromstring(content)
        self.assertEqual(marked_ranges(markup.find_class('example-text')[0]), [(4, 12)])
        chinese = markup.find_class('example-translation')[0]
        self.assertEqual(rendered_text(chinese), '翻译 ' + zh)
        # The supplied pair is linguistically wrong despite valid hashes/ranges.
        # Rendering preserves that authored data; this is an explicit limitation,
        # not approval of "ambition -> 表明了" or an inferred correction to 雄心.
        self.assertEqual([rendered_text(chunk) for chunk in chinese.find_class('card-chunk')], ['表明了'])
        self.assertEqual(chinese.xpath('.//mark'), [])
        self.assertNotIn('term-highlight', content)
        self.assertNotIn('<style>', content)
        self.assertNotIn('<script>alert', content)
        self.assertEqual(value, before)

    def test_explicit_forms_whole_boundaries_cloze_and_chinese_html_are_preserved(self):
        english = "The rate rated corporate rates."
        zh = '比率评价了公司比率。<script>alert(1)</script>'
        pairs = [{"en": [4, 8], "zh": [[0, 2]], "relation": "equivalent"},
                 {"en": [9, 14], "zh": [[2, 4]], "relation": "equivalent"},
                 {"en": [25, 30], "zh": [[7, 9]], "relation": "equivalent"}]
        value = card(audio="")
        value['word_forms'] = '第三人称单数: rates|过去式: rated'
        value["examples"] = [self.example(english, zh, pairs)]
        value["examples"][0]["cloze_answers"] = [
            {"start": 9, "end": 14, "word": "rated", "number": 2}]
        content = _fields(value, None, 0)[0]["Examples"]
        markup = html.fragment_fromstring(content)
        english_markup = markup.find_class('example-text')[0]
        underlines = english_markup.xpath('.//u[@class="cloze-answer"]')
        self.assertEqual([(entry.get('data-blank-number'), rendered_text(entry)) for entry in underlines], [('2', 'rated')])
        self.assertEqual(marked_ranges(english_markup), [(4, 8), (9, 14), (25, 30)])
        self.assertEqual(rendered_text(markup.find_class('example-translation')[0]), '翻译 ' + zh)
        self.assertNotIn('term-highlight', content)
        self.assertNotIn('<style>', content)
        self.assertNotIn('<mark class="target-word">corporate', content)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', content)
        self.assertNotIn('<script>alert', content)

    def test_stale_text_missing_codex_alignment_and_invalid_ranges_fail_closed(self):
        value = card(audio="")
        cases = []
        stale = self.example(); stale["text"] = "The rate Rose."; cases.append(stale)
        stale_translation = self.example(); stale_translation["translation"] = "比率下降了。"; cases.append(stale_translation)
        missing = self.example(); missing.pop("translation_alignment"); cases.append(missing)
        invalid = self.example(); invalid["translation_alignment"]["alignments"][0]["zh"] = [[0, 99]]; cases.append(invalid)
        for example in cases:
            value["examples"] = [example]
            with self.subTest(example=example), self.assertRaises(ValueError):
                _fields(value, None, 0)

    def test_overlapping_authored_mapping_keeps_plain_text_without_fixed_chinese_paint(self):
        value = card(audio="")
        value["examples"] = [self.example("one rate three four", "一比率三四", [
            {"en": [0, 8], "zh": [[0, 3]], "relation": "equivalent"},
            {"en": [4, 12], "zh": [[1, 4]], "relation": "equivalent"}])]
        content = _fields(value, None, 0)[0]["Examples"]
        markup = html.fragment_fromstring(content)
        self.assertEqual(rendered_text(markup.find_class('example-text')[0]), 'one rate three four')
        self.assertEqual(marked_ranges(markup.find_class('example-text')[0]), [(4, 8)])
        self.assertEqual(rendered_text(markup.find_class('example-translation')[0]), '翻译 一比率三四')
        self.assertNotIn('term-highlight', content)

    def test_pinned_occurrence_subset_controls_only_english_highlights(self):
        english, zh = "The rate differs from that rate.", "这个比率不同于那个比率。"
        value = card(audio="")
        value['examples'] = [self.example(english, zh, [
            {"en": [4, 8], "zh": [[2, 4]], "relation": "equivalent"},
            {"en": [27, 31], "zh": [[9, 11]], "relation": "equivalent"}])]
        value['examples'][0]['matched_english_ranges'] = [[27, 31]]
        content = _fields(value, None, 0)[0]['Examples']
        markup = html.fragment_fromstring(content)
        self.assertEqual(rendered_text(markup.find_class('example-text')[0]), english)
        self.assertEqual(marked_ranges(markup.find_class('example-text')[0]), [(27, 31)])
        self.assertEqual(rendered_text(markup.find_class('example-translation')[0]), '翻译 ' + zh)
        self.assertNotIn('term-highlight', content)
        self.assertEqual(content.count('<mark class="target-word">'), 1)
        value['examples'][0]['matched_english_ranges'] = [[5, 8]]
        with self.assertRaisesRegex(ValueError, 'whole-word'):
            _fields(value, None, 0)


class CodexIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_fixture(self.root)

    def load(self, **kwargs):
        from anki_pipeline.codex_exam_index import load_codex_exam_index
        return load_codex_exam_index(self.root, **kwargs)

    def test_partial_is_explicit_and_input_translation_review_and_index_are_byte_bound(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*.json')}
        with self.assertRaisesRegex(ValueError, "full|partial"):
            self.load()
        rows, report = self.load(allow_partial=True)
        self.assertEqual(report["scope"], "partial")
        self.assertEqual(report["semantic_review_status"], "approved")
        self.assertEqual((report["papers"], report["sentences"]), (1, 1))
        self.assertEqual(rows[0]["english"], "The rate rose.")
        self.assertEqual(rows[0]["translation_alignment"]["englishHash"], sha(rows[0]["english"]))
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_full_requires_exact_all_44_and_approved_review(self):
        write_fixture(self.root, names=PAPERS, scope="full")
        rows, report = self.load()
        self.assertEqual((len(rows), report["papers"]), (44, 44))
        self.assertEqual(len({r["id"] for r in rows}), 44)
        manifest = json.loads((self.root/'index/manifest.json').read_text())
        manifest['papers'].pop(); write_json(self.root/'index/manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, "44|coverage|totals"):
            self.load()

    def test_unreviewed_and_missing_review_are_never_consumed(self):
        write_fixture(self.root, reviewed=False)
        with self.assertRaisesRegex(ValueError, "review|approved"):
            self.load(allow_partial=True)
        write_fixture(self.root)
        (self.root/'reviews/2026-01.json').unlink()
        with self.assertRaises(ValueError):
            self.load(allow_partial=True)

    def test_changed_source_translation_review_index_or_inventory_rejected(self):
        for filename in ('manifest.json', 'inputs/2026-01.json', 'translations/2026-01.json',
                         'reviews/2026-01.json', 'index/2026-01.json'):
            with self.subTest(filename=filename):
                write_fixture(self.root)
                path=self.root/filename; path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError, "hash|changed"):
                    self.load(allow_partial=True)

    def test_false_approval_and_hash_stale_review_rejected_even_with_updated_review_hash(self):
        for change in ({'approved':False}, {'translationHash':'0'*64}, {'paperId':'kaoyan:2025-01'}):
            with self.subTest(change=change):
                write_fixture(self.root)
                review=json.loads((self.root/'reviews/2026-01.json').read_text());review.update(change)
                review_hash=write_json(self.root/'reviews/2026-01.json',review)
                manifest=json.loads((self.root/'index/manifest.json').read_text())
                manifest['papers'][0]['reviewHash']=review_hash
                write_json(self.root/'index/manifest.json',manifest)
                with self.assertRaisesRegex(ValueError,'review|approved'):
                    self.load(allow_partial=True)

    def test_review_must_cover_every_sentence_and_alignment_without_open_issues(self):
        for change in ({'issues': ['unresolved']}, {'issues': None}, {'method': ''},
                       {'method': []}, {'method': {}}, {'method': {'review': True}},
                       {'method': {'review': []}}, {'method': {'': 'reviewed'}},
                       {'reviewedSentences': 0},
                       {'reviewedAlignments': 0}, {'reviewedSentences': True}):
            with self.subTest(change=change):
                write_fixture(self.root)
                path = self.root / 'reviews/2026-01.json'
                review = json.loads(path.read_text()); review.update(change)
                manifest = json.loads((self.root / 'index/manifest.json').read_text())
                manifest['papers'][0]['reviewHash'] = write_json(path, review)
                write_json(self.root / 'index/manifest.json', manifest)
                with self.assertRaisesRegex(ValueError, 'review'):
                    self.load(allow_partial=True)

    def test_structured_independent_review_method_retains_full_description(self):
        review_path = self.root / 'reviews/2026-01.json'
        review = json.loads(review_path.read_text())
        review['method'] = {'sentenceReview': 'Compared every sentence in context',
                            'alignmentReview': ['Checked exact English and Chinese ranges']}
        manifest = json.loads((self.root / 'index/manifest.json').read_text())
        manifest['papers'][0]['reviewHash'] = write_json(review_path, review)
        write_json(self.root / 'index/manifest.json', manifest)
        self.assertEqual(self.load(allow_partial=True)[1]['semantic_review_status'], 'approved')

    def test_self_consistent_index_hash_cannot_forge_translation_sentence_or_context(self):
        for field, value in (('translationZh','旧Google译文'), ('english','Changed rate.'),
                             ('id','kaoyan:2026-01:p:b-9-9:0'), ('sourceHash','0'*64),
                             ('context',{'sourcePath':'invented'})):
            with self.subTest(field=field):
                write_fixture(self.root)
                index=json.loads((self.root/'index/2026-01.json').read_text())
                index['sentences'][0][field]=value
                h=write_json(self.root/'index/2026-01.json',index)
                manifest=json.loads((self.root/'index/manifest.json').read_text())
                manifest['papers'][0]['indexHash']=h;write_json(self.root/'index/manifest.json',manifest)
                with self.assertRaisesRegex(ValueError,'index|sentence|bound'):
                    self.load(allow_partial=True)

    def test_index_file_escape_duplicate_papers_and_invalid_count_rejected(self):
        for change in ('escape','duplicate','count'):
            with self.subTest(change=change):
                write_fixture(self.root)
                manifest=json.loads((self.root/'index/manifest.json').read_text())
                if change=='escape': manifest['papers'][0]['indexFile']='../inputs/2026-01.json'
                if change=='duplicate': manifest['papers'].append(copy.deepcopy(manifest['papers'][0]))
                if change=='count': manifest['totals']['sentences']=True
                write_json(self.root/'index/manifest.json',manifest)
                with self.assertRaises(ValueError): self.load(allow_partial=True)

    def test_changed_snapshot_during_loading_is_rejected(self):
        import anki_pipeline.codex_exam_index as module
        original=module._read_json
        def changed(path, *args, **kwargs):
            result=original(path,*args,**kwargs)
            if Path(path).name=='2026-01.json' and Path(path).parent.name=='reviews':
                path.write_bytes(path.read_bytes()+b' ')
            return result
        with patch.object(module,'_read_json',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'changed'):
                self.load(allow_partial=True)


if __name__ == '__main__':
    unittest.main()
