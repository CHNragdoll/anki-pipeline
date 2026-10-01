"""Offline etymology identity, original text, coverage and import isolation."""
from __future__ import annotations

import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from anki_pipeline.etymology import _load_parser, _normalize, enrich_etymology_cards


ROOT = Path(__file__).resolve().parents[2] / "dictionary-unpacked/cigen-en-new"
# Independent small fixture helpers use the same archive classes/field shapes.
TREE = '''from anki_pipeline.local_dictionary import _Tree
TreeParser = _Tree
def compact(text):
    return ' '.join(text.split())
def first(node, name):
    return next((child for child in node.walk() if child.has_class(name)), None)
'''
PARSER = '''from html_tree import TreeParser, compact, first
import re
def fields(content):
    tree = TreeParser(content).root
    result = {'etymology_tree': [], 'root_affixes': [], 'root_memory': [],
              'derived_words': [], 'same_root_words': [], 'sections': []}
    for section in (node for node in tree.walk() if node.has_class('wordSection')):
        title, body = first(section, 'sectionHead'), first(section, 'sectionCont')
        if body is not None:
            result['sections'].append({'title': compact(title.text()) if title is not None else '', 'text': compact(body.text())})
        if title is not None and compact(title.text()) == '词根记忆' and body is not None:
            result['root_memory'].append(compact(body.text()))
        for node in section.walk():
            if node.has_class('treePart'):
                level = re.search(r'etymology_(\\d+)', node.attrs.get('class', ''))
                part = first(node, 'part')
                result['etymology_tree'].append({'level': int(level[1]) if level else None,
                    'parts': [compact(n.text()) for n in part.walk() if n.has_class('rootWord') or n.has_class('affixWord')] if part is not None else [],
                    'text': compact(part.text()) if part is not None else ''})
            if node.has_class('rootAffixLi'):
                kind, description = first(node, 'prefix'), first(node, 'preCont')
                result['root_affixes'].append({'type': compact(kind.text()) if kind is not None else '',
                    'description': compact(description.text()) if description is not None else compact(node.text())})
            if node.has_class('sameRoot') and (section.has_class('derivativeSec') or section.has_class('sameRootWord')):
                name, translation = first(node, 'name'), first(node, 'trans')
                if name is not None:
                    item = {'word': compact(name.text()), 'translation': compact(translation.text()) if translation is not None else '',
                            'text': compact(node.text())}
                    result['derived_words' if section.has_class('derivativeSec') else 'same_root_words'].append(item)
    return result
'''

RELATED = '''<div class="wordSection sameRootWord"><div class="sectionHead">同根词</div>
<div class="sectionCont"><div class="sameRoot"><p class="name"><a href="dic://circuit">circu<span class="key">it</span></a></p>
<div class="sentenceInfo"><p class="trans">环道；电路，回路</p><p class="trans">另一条原释义</p>
<p class="trans"><span>#四级</span><span>#考研</span></p>
<div class="sentence sameRootSent"><p class="line">I ran a <span class="key">circuit</span> of the village.</p>
<p class="exp">我绕村子跑了个环线。</p></div></div></div></div></div>'''


def entry(word="console", construction=True, memory=False):
    tree = f'''<div class="wordSection etymologyTree"><div class="sectionCont">
    <div class="treePart etymology_0"><p class="part"><span class="rootWord">{word}</span></p></div>'''
    if construction:
        tree += '''<div class="treePart etymology_1"><p class="part">
        <span class="affixWord">con-</span> + <span class="rootWord">sol-</span></p></div>'''
    tree += "</div></div>"
    if construction:
        tree += '''<div class="wordSection etymasDom"><div class="sectionCont"><li class="rootAffixLi">
        <span class="prefix">词根</span><span class="preCont">sol- 表示“安慰”。&lt;script&gt;原文&lt;/script&gt;</span>
        </li></div></div>'''
    if memory:
        tree += '''<div class="wordSection"><div class="sectionHead">词根记忆</div>
        <div class="sectionCont">记忆 &amp; 原文</div></div>'''
    return tree + '<script src="eures://etyma.js"></script>'


class EtymologyTest(unittest.TestCase):
    def test_original_viewer_preserves_unterminated_entities_as_source_text(self):
        from lxml import html
        from anki_pipeline.etymology import _OriginalContent
        for original in (
            '&Conservation ;', '&v.漫步', '&African market', '&grammar,',
            '&event management', '&Guilliet manufacturers', 'cliche&1&s?',
            '&amp; &lt;img src=x onerror=bad()&gt; &#169; &copy;',
        ):
            with self.subTest(original=original):
                source = '<p>' + original + '</p>'
                converted = ''.join(_OriginalContent(source, {}).output)
                self.assertEqual(html.fromstring(converted).text_content(),
                                 html.fromstring(source).text_content())
                self.assertEqual(html.fromstring(converted).xpath('.//img'), [])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "html_tree.py").write_text(TREE, encoding="utf-8")
        (self.root / "lookup.py").write_text(PARSER, encoding="utf-8")
        (self.root / "manifest.json").write_text(json.dumps({"source_sha256": "a" * 64}))
        self.database = self.root / "dictionary.sqlite3"
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.executescript('''CREATE TABLE entries(id INTEGER PRIMARY KEY,headword TEXT,
                lookup_key TEXT,html TEXT,redirect_target TEXT,entry_file TEXT,bytes INTEGER,
                sha256 TEXT,source_body_offset INTEGER);
                CREATE INDEX headword_index ON entries(headword);
                CREATE INDEX lookup_index ON entries(lookup_key);''')
        self.insert(1, "console", entry(memory=True))

    def insert(self, identity, word, html):
        raw = html.encode()
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?,?)", (identity, word, _normalize(word), html,
                None, f"entries/{identity}.html", len(raw), hashlib.sha256(raw).hexdigest(), 0))

    def enrich(self, *cards):
        return enrich_etymology_cards(cards, self.root)

    def test_real_html_format_preserves_tree_levels_and_plain_source_text(self):
        cards, report = self.enrich({"id": "keep", "word": "console"})
        local = cards[0]["etymology"]
        self.assertEqual(local["schema"], "cigen-etymology.v1")
        self.assertTrue(local["found"])
        self.assertTrue(local["has_content"])
        original = local["entries"][0]
        self.assertEqual(original["etymology_tree"], [
            {"level": 0, "parts": ["console"], "text": "console"},
            {"level": 1, "parts": ["con-", "sol-"], "text": "con- + sol-"}])
        self.assertEqual(original["root_affixes"], [{"type": "词根", "description": 'sol- 表示“安慰”。<script>原文</script>'}])
        self.assertEqual(original["root_memory"], ["记忆 & 原文"])
        self.assertNotIn("html", original)
        self.assertEqual(original["derived_words"], [])
        self.assertEqual(original["same_root_words"], [])
        self.assertEqual(report["counts"], {"found": 1, "content": 1, "tree": 1, "affixes": 1, "memory": 1})

    def test_same_headword_entries_stay_separate_in_source_id_order(self):
        self.insert(2, "console", entry("console", construction=False, memory=True))
        cards, report = self.enrich({"id": "keep", "word": "console"})
        originals = cards[0]["etymology"]["entries"]
        self.assertEqual([item["id"] for item in originals], [1, 2])
        self.assertEqual([len(item["etymology_tree"]) for item in originals], [2, 1])
        self.assertEqual(report["counts"]["found"], 1)

    def test_related_word_full_source_semantics_and_tree_structure_survive(self):
        self.insert(2, "ambition", entry("ambition", memory=True) + RELATED)
        cards, _ = self.enrich({"id": "full", "word": "ambition"})
        source = cards[0]["etymology"]["entries"][0]
        self.assertIn("resource_sections", source)
        serialized = json.dumps(source["resource_sections"], ensure_ascii=False)
        for original in ("词根记忆", "同根词", "环道；电路，回路", "另一条原释义", "#四级", "#考研",
                         "I ran a ", "circuit", " of the village.", "我绕村子跑了个环线。", "etymology-key"):
            self.assertIn(original, serialized)
        self.assertNotIn("dic://", serialized)
        self.assertNotIn("eures://", serialized)
        self.assertEqual(source["resource_schema"], "cigen-resource-sections.v1")

    def test_safe_source_tree_drops_execution_and_attributes_but_keeps_literal_text(self):
        malicious = RELATED.replace('<span class="key">it</span>',
            '<span class="key" onclick="evil()">it</span><script>evil()</script><img src="https://evil">')
        self.insert(2, "safe", entry("safe") + malicious)
        cards, _ = self.enrich({"id": "safe", "word": "safe"})
        serialized = json.dumps(cards[0]["etymology"]["entries"][0]["resource_sections"], ensure_ascii=False)
        self.assertNotIn("evil", serialized)
        self.assertNotIn("onclick", serialized)
        self.assertNotIn('"img"', serialized)
        self.assertIn("<script>原文</script>", serialized)

    def test_related_only_source_counts_as_content_without_fabricating_tree_or_affixes(self):
        self.insert(2, "related", RELATED)
        cards, report = self.enrich({"id": "related", "word": "related"})
        source = cards[0]["etymology"]
        self.assertTrue(source["has_content"])
        self.assertEqual(source["entries"][0]["etymology_tree"], [])
        self.assertEqual(source["entries"][0]["root_affixes"], [])
        self.assertEqual(source["entries"][0]["same_root_words"][0]["word"], "circuit")
        self.assertEqual(report["related_counts"], {"derived_cards": 0, "same_root_cards": 1,
                                                 "derived_words": 0, "same_root_words": 1})

    def test_all_tree_nodes_keep_unclamped_source_levels_and_each_combination(self):
        content = entry("deep") + '<div class="wordSection etymologyTree"><div class="sectionHead">词源树</div>' \
            '<div class="sectionCont"><div class="treePart etymology_4"><p class="part">' \
            '<span class="rootWord">deep-root</span> + <span class="affixWord">-end</span></p></div></div></div>'
        self.insert(2, "deep", content)
        cards, _ = self.enrich({"id": "deep", "word": "deep"})
        original = cards[0]["etymology"]["entries"][0]
        self.assertEqual([node["level"] for node in original["etymology_tree"]], [0, 1, 4])
        self.assertEqual(original["etymology_tree"][-1]["parts"], ["deep-root", "-end"])
        serialized = json.dumps(original["resource_sections"], ensure_ascii=False)
        self.assertIn('"level": 4', serialized)
        self.assertIn('deep-root', serialized)

    def test_exact_case_takes_priority_over_normalized_other_entry(self):
        self.insert(2, "Console", entry("Console", construction=False))
        cards, report = self.enrich({"id": "keep", "word": "console"})
        self.assertEqual([item["id"] for item in cards[0]["etymology"]["entries"]], [1])
        self.assertEqual(report["warnings"], [])

    def test_nfkc_match_preserves_case_and_source_headword(self):
        cards, report = self.enrich({"id": "keep", "word": "ｃｏｎｓｏｌｅ"})
        self.assertEqual(cards[0]["word"], "ｃｏｎｓｏｌｅ")
        self.assertEqual(cards[0]["etymology"]["entries"][0]["headword"], "console")
        self.assertEqual(cards[0]["etymology"]["entries"][0]["match"], "normalized")
        self.assertEqual(report["warnings"][0]["headwords"], ["console"])

    def test_casefold_only_match_is_missing_with_candidate_provenance(self):
        self.insert(2, "Polish", entry("Polish"))
        cards, report = self.enrich({"id": "keep", "word": "polish"})
        local = cards[0]["etymology"]
        self.assertFalse(local["found"])
        self.assertFalse(local["has_content"])
        self.assertEqual(local["entries"], [])
        self.assertEqual(report["counts"], {"found": 0, "content": 0, "tree": 0, "affixes": 0, "memory": 0})
        self.assertEqual(report["missing"][0]["reason"], "ambiguous_case")
        self.assertEqual(report["missing"][0]["candidates"], [{
            "id": 2, "headword": "Polish", "html_sha256": hashlib.sha256(entry("Polish").encode()).hexdigest()}])

    def test_uppercase_query_is_not_casefolded_into_lowercase_source(self):
        cards, report = self.enrich({"id": "keep", "word": "ＣＯＮＳＯＬＥ"})
        self.assertFalse(cards[0]["etymology"]["found"])
        self.assertEqual(report["missing"][0]["reason"], "ambiguous_case")

    def test_normalized_bucket_only_selects_equivalent_case_preserving_headwords(self):
        self.insert(2, "Console", entry("Console"))
        cards, report = self.enrich({"id": "keep", "word": "ｃｏｎｓｏｌｅ"})
        self.assertEqual([node["id"] for node in cards[0]["etymology"]["entries"]], [1])
        self.assertEqual(report["warnings"][0]["headwords"], ["console"])

    def test_bad_lookup_key_cannot_attach_an_unrelated_headword(self):
        self.insert(2, "different", entry("different"))
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("UPDATE entries SET lookup_key=? WHERE id=2", ("absent",))
        with self.assertRaisesRegex(ValueError, "lookup key integrity"):
            self.enrich({"id": "keep", "word": "absent"})

    def test_source_parser_extra_html_fields_are_not_exposed(self):
        parser = types.SimpleNamespace(fields=lambda _: {
            "etymology_tree": [{"level": 1, "parts": ["con-", "sol-"], "text": "con- + sol-", "html": "<script>bad()</script>"}],
            "root_affixes": [], "root_memory": [], "derived_words": [], "same_root_words": [], "sections": []})
        with patch("anki_pipeline.etymology._load_parser", return_value=(parser, "f" * 64)):
            with self.assertRaisesRegex(ValueError, "tree node"):
                self.enrich({"id": "keep", "word": "console"})

    def test_word_only_and_absent_columns_do_not_claim_constructed_content(self):
        self.insert(2, "label", entry("label", construction=False))
        self.insert(3, "empty", "<p>source entry with no selected fields</p>")
        cards, report = self.enrich({"id": "one", "word": "label"}, {"id": "two", "word": "empty"})
        self.assertTrue(all(card["etymology"]["found"] for card in cards))
        self.assertTrue(all(not card["etymology"]["has_content"] for card in cards))
        self.assertEqual(report["counts"]["content"], 0)
        self.assertEqual([item["word"] for item in report["empty"]], ["label", "empty"])

    def test_memory_only_entry_is_genuine_content(self):
        self.insert(2, "memory", entry("memory", construction=False, memory=True))
        cards, report = self.enrich({"id": "keep", "word": "memory"})
        self.assertTrue(cards[0]["etymology"]["has_content"])
        self.assertEqual(report["counts"], {"found": 1, "content": 1, "tree": 0, "affixes": 0, "memory": 1})

    def test_missing_lemma_or_fuzzy_title_alias_is_not_guessed(self):
        cards, report = self.enrich({"id": "one", "word": "consoles"},
                                   {"id": "two", "word": "different\n(美console)"})
        self.assertTrue(all(not card["etymology"]["found"] for card in cards))
        self.assertTrue(all(card["etymology"]["entries"] == [] for card in cards))
        self.assertEqual([item["word"] for item in report["missing"]], ["consoles", "different\n(美console)"])

    def test_multiline_title_and_all_existing_identity_data_are_preserved(self):
        original = {"id": "stable", "word": "console\n(美console)", "note": "keep",
                    "examples": [{"text": "original", "translation": "原译"}],
                    "local_dictionary": {"senses": [{"text": "原牛津"}]}, "ecdict": {"tags": ["ky"]}}
        untouched = copy.deepcopy(original)
        source_bytes = {path: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        cards, report = self.enrich(original)
        self.assertEqual(original, untouched)
        self.assertEqual({key: cards[0][key] for key in original}, untouched)
        self.assertEqual(cards[0]["etymology"]["query"], "console")
        self.assertEqual(cards[0]["etymology"]["provenance"]["db_sha256"], hashlib.sha256(self.database.read_bytes()).hexdigest())
        self.assertEqual(report["source"]["archive_sha256"], "a" * 64)
        self.assertEqual(source_bytes, {path: path.read_bytes() for path in source_bytes})
        cards[0]["examples"][0]["text"] = "changed copy"
        self.assertEqual(original, untouched)

    def test_duplicate_word_cards_remain_independent_copies(self):
        cards, report = self.enrich({"id": "one", "word": "console"}, {"id": "two", "word": "console"})
        cards[0]["etymology"]["entries"][0]["root_affixes"].clear()
        self.assertTrue(cards[1]["etymology"]["entries"][0]["root_affixes"])
        self.assertEqual(report["cards"], 2)
        self.assertEqual(report["unique_words"], 1)

    def test_case_distinct_exact_cards_remain_distinct_words(self):
        self.insert(2, "Console", entry("Console", construction=False))
        cards, report = self.enrich({"id": "one", "word": "console"}, {"id": "two", "word": "Console"})
        self.assertEqual(report["unique_words"], 2)
        self.assertEqual([card["etymology"]["entries"][0]["id"] for card in cards], [1, 2])

    def test_missing_optional_manifest_does_not_invent_archive_identity(self):
        (self.root / "manifest.json").unlink()
        cards, report = self.enrich({"id": "one", "word": "console"})
        self.assertTrue(cards[0]["etymology"]["found"])
        self.assertIsNone(report["source"]["manifest_sha256"])
        self.assertIsNone(report["source"]["archive_sha256"])

    def test_lookup_and_html_tree_global_modules_are_not_replaced(self):
        lookup, tree = types.ModuleType("lookup"), types.ModuleType("html_tree")
        with patch.dict(sys.modules, {"lookup": lookup, "html_tree": tree}):
            parser, digest = _load_parser(self.root)
            self.assertIs(sys.modules["lookup"], lookup)
            self.assertIs(sys.modules["html_tree"], tree)
            self.assertEqual(len(digest), 64)
            self.assertTrue(parser.fields(entry())["root_affixes"])

    def test_corrupt_entry_hash_aborts_without_changing_source(self):
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute("UPDATE entries SET html=? WHERE id=1", ("tampered",))
        original = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.enrich({"id": "one", "word": "console"})
        self.assertEqual(self.database.read_bytes(), original)

    def test_source_helper_changes_during_read_are_rejected(self):
        original = _load_parser
        def changed(root):
            result = original(root)
            with (root / "lookup.py").open("a") as stream:
                stream.write("\n# changed during loading\n")
            return result
        with patch("anki_pipeline.etymology._load_parser", changed):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.enrich({"id": "one", "word": "console"})

    def test_invalid_card_id_and_word_types_are_rejected(self):
        for cards in ([{"id": "same", "word": "console"}, {"id": "same", "word": "other"}],
                      [{"id": "", "word": "console"}], [{"id": "one", "word": 3}],
                      ["invalid"]):
            with self.subTest(cards=cards), self.assertRaises(ValueError):
                enrich_etymology_cards(cards, self.root)


@unittest.skipUnless((ROOT / "dictionary.sqlite3").is_file(), "Local root dictionary is not installed")
class ActualEtymologyTest(unittest.TestCase):
    def test_actual_ambition_keeps_all_five_same_root_words_and_circuit_example(self):
        cards, _ = enrich_etymology_cards([{"id": "ambition", "word": "ambition"}], ROOT)
        source = cards[0]["etymology"]["entries"][0]
        self.assertEqual([item["word"] for item in source["same_root_words"]],
                         ["circuit", "exit", "transition", "ambitious", "transit"])
        serialized = json.dumps(source["resource_sections"], ensure_ascii=False)
        self.assertIn("I ran a ", serialized)
        self.assertIn(" of the village.", serialized)
        self.assertIn("我绕村子跑了个环线。", serialized)
        self.assertIn("#高考", serialized)
        self.assertIn("#GMAT", serialized)

    def test_actual_ambition_console_exsert_and_missing_resources(self):
        cards, report = enrich_etymology_cards(
            [{"id": word, "word": word} for word in ("ambition", "console", "exsert", "chunk")], ROOT)
        self.assertEqual(report["counts"]["found"], 3)
        self.assertEqual(report["counts"]["content"], 3)
        self.assertEqual(report["missing"], [{"id": "chunk", "word": "chunk"}])
        expected = {"ambition": ["ambi-", "it-", "-ion"], "console": ["con-", "sol-"], "exsert": ["ex-", "sert-"]}
        for card in cards[:3]:
            local = card["etymology"]
            self.assertEqual(local["entries"][0]["etymology_tree"][1]["parts"], expected[card["word"]])
            self.assertTrue(local["entries"][0]["root_affixes"])
            self.assertEqual(local["entries"][0]["root_memory"], [])
            self.assertIn("derived_words", local["entries"][0])
            self.assertNotIn("html", local["entries"][0])
        self.assertEqual(report["source"]["archive_sha256"], "4265019a44310745e6cc02b31f71d849ebcf78273e48edb78324ba703536e109")

    def test_actual_polish_is_not_given_the_mixed_polish_source_entry(self):
        cards, report = enrich_etymology_cards([{"id": "polish", "word": "polish"}], ROOT)
        self.assertEqual(cards[0]["etymology"]["entries"], [])
        self.assertFalse(cards[0]["etymology"]["has_content"])
        self.assertEqual(report["missing"][0]["reason"], "ambiguous_case")
        self.assertEqual(report["missing"][0]["candidates"], [{
            "id": 61357, "headword": "Polish",
            "html_sha256": "3ec472ca972e74b6e300b7dd96f0c61d170daa717296aaf8d3e466a4ae2d0cd6"}])


if __name__ == "__main__":
    unittest.main()
