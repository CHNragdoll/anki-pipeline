"""Offline dictionary enrichment and media/source preservation checks."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.local_dictionary import (
    _Tree, _copy_audio, _find_entries, _load_webster_parser, _normalize,
    _oxford_entry, _resolve_entries, _resource, enrich_dictionary_cards,
)


ROOT = Path(__file__).resolve().parents[2] / "dictionary-unpacked"


def oxford_html(word="study"):
    return f'''<div class="entry"><div class="webtop">
    <h1 class="headword">{word}</h1><span class="pos">noun</span>
    <span class="phonetics"><div class="phons_br" wd="{word}">
    <a href="sound://word_uk.mp3"></a><span class="phon">/uk/</span></div>
    <div class="phons_n_am" wd="{word}"><a href="sound://word_us.mp3"></a>
    <span class="phon">/us/</span></div></span>
    <table class="verb_forms_table"><tr><td><div class="phons_n_am" wd="{word}">
    <a href="sound://form.mp3"></a><span class="phon">/form/</span></div></td></tr></table>
    </div><li class="sense"><span class="def">study</span><defT><chn>学习；研究</chn></defT>
    <ul class="examples"><li><chn>这是一条例句。</chn><a href="sound://example.mp3"></a></li></ul>
    <div class="unbox"><defT><chn>不应提取的附录</chn></defT></div></li>
    <div class="idm-g"><defT><chn>不应提取的习语</chn></defT></div></div>
    <div class="entry"><div class="webtop"><h1 class="headword">{word}</h1>
    <span class="pos">verb</span></div><li class="sense"><defT><chn>学习；攻读</chn></defT></li></div>
    <div class="entry"><div class="webtop"><h1 class="headword">studious</h1>
    <span class="pos">adjective</span></div><li class="sense"><defT><chn>不应提取的派生词</chn></defT></li></div>'''


WEBSTER_HTML = '''<div><div class="entry-header"><h1 class="hword">study</h1>
<h2 class="parts-of-speech">noun</h2><a href="sound://sound/study.mp3"></a></div>
<div class="uro"><a href="sound://sound/studious.mp3"></a></div></div>'''


class _StubParser:
    """A small loader stand-in; real source parser behavior is checked below."""
    @staticmethod
    def parse(content):
        return _Tree(content).root

    @staticmethod
    def headers(tree):
        return [node for node in tree.walk() if node.has_class("entry-header")]

    @staticmethod
    def headword(node):
        return node.text()

    @staticmethod
    def relations(conn, resolved, *args):
        # Any accidental dictionary write remains blocked at the SQLite level.
        try:
            conn.execute("CREATE TABLE forbidden_write(id INTEGER)")
        except sqlite3.OperationalError:
            pass
        else:
            raise AssertionError("Dictionary was opened writable")
        if not resolved:
            return {"word_forms": [], "derived_words": []}
        return {"word_forms": [{"kind": "plural", "label": "复数", "form": "studies",
                                "base": "study", "source": "mw_inflections"}],
                "derived_words": [{"word": "studious", "parts_of_speech": ["adjective"],
                                   "label": "形容词", "source": "mw_explicit_uro"}]}


def _first(node, name):
    return next((child for child in node.walk() if child.has_class(name)), None)


def create_export(root, content, sounds):
    root.mkdir()
    conn = sqlite3.connect(root / "dictionary.sqlite3")
    conn.executescript('''CREATE TABLE entries(id INTEGER PRIMARY KEY, headword TEXT,
        lookup_key TEXT, html TEXT, redirect_target TEXT, entry_file TEXT,
        bytes INTEGER, sha256 TEXT);
        CREATE TABLE resources(id INTEGER PRIMARY KEY, archive_key TEXT, path TEXT,
        lookup_path TEXT, extension TEXT, bytes INTEGER, sha256 TEXT);''')
    data = content.encode()
    conn.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)",
                 (1, "study", "study", content, None, "entries/study.html", len(data), hashlib.sha256(data).hexdigest()))
    (root / "resources").mkdir()
    for number, name in enumerate(sounds, 1):
        path = root / "resources" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"ID3" + name.encode()
        path.write_bytes(payload)
        conn.execute("INSERT INTO resources VALUES(?,?,?,?,?,?,?)",
                     (number, name, name, name.casefold(), ".mp3", len(payload), hashlib.sha256(payload).hexdigest()))
    conn.commit()
    conn.close()


class OxfordParserTest(unittest.TestCase):
    def test_pos_per_main_entry_and_no_example_idiom_or_derivative_senses(self):
        result = _oxford_entry(oxford_html(), "study")
        self.assertEqual(result["senses"], [{"pos": "n.", "text": "学习；研究"},
                                           {"pos": "v.", "text": "学习；攻读"}])
        self.assertEqual(result["audio"], [{"resource_key": "word_uk.mp3", "accent": "uk"},
                                          {"resource_key": "word_us.mp3", "accent": "us"}])
        self.assertEqual(result["phonetics"], [("uk", "/uk/"), ("us", "/us/")])

    def test_case_exact_entry_prevents_capitalized_names_from_polluting_word(self):
        source = oxford_html("Study") + oxford_html("study")
        source = source.replace("学习；研究", "Capitalized name", 1)
        self.assertNotIn("Capitalized name", [sense["text"] for sense in _oxford_entry(source, "study")["senses"]])

    def test_phrase_entry_is_labeled_and_its_example_translation_is_excluded(self):
        source = '''<div class="entry"><div class="webtop"><h1 class="headword">rely on</h1>
        <span class="pos">phrasal verb</span></div><span class="pv-g"><span class="pv">rely on/upon somebody</span>
        <li class="sense"><defT><chn>依赖；依靠</chn></defT><ul class="examples"><chn>这不是释义。</chn>
        </ul></li></span></div>'''
        self.assertEqual(_oxford_entry(source, "rely on")["senses"], [
            {"pos": "phr. v.", "text": "rely on/upon somebody：依赖；依靠", "phrase": "rely on/upon somebody"}])

    def test_oxford_accepts_explicit_header_spelling_variant_not_arbitrary_audio_word(self):
        source = oxford_html().replace('wd="study"', 'wd="enquire"')
        self.assertEqual(_oxford_entry(source, "study")["audio"], [])
        source = source.replace('<span class="phonetics">', '<div class="variants"><span class="v">enquire</span></div><span class="phonetics">', 1)
        self.assertEqual(len(_oxford_entry(source, "study")["audio"]), 2)


class LocalDictionaryTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dictionaries = self.root / "dictionary"
        self.dictionaries.mkdir()
        create_export(self.dictionaries / "oald10", oxford_html(),
                      ["word_uk.mp3", "word_us.mp3", "form.mp3", "example.mp3"])
        create_export(self.dictionaries / "mw-now", WEBSTER_HTML,
                      ["sound/study.mp3", "sound/studious.mp3"])
        self.media = self.root / "media"

    def enrich(self, cards):
        # Adapter uses the same Node API as the real unpacked parser.
        with patch.object(type(_Tree("").root), "first", _first, create=True), \
             patch("anki_pipeline.local_dictionary._load_webster_parser", return_value=(_StubParser, "helper-hash")):
            return enrich_dictionary_cards(cards, self.dictionaries, self.media)

    def test_enrich_preserves_identity_examples_and_source_bytes(self):
        cards = [{"id": "stable", "word": "study", "phonetic": "old", "note": "keep",
                  "level": "CET4", "word_forms": "old forms", "audio_filename": "old.mp3",
                  "examples": [{"text": "original", "translation": "原译文", "cloze_answers": [{"answer": "study"}]}]}]
        original = copy.deepcopy(cards)
        hashes = {source: hashlib.sha256((self.dictionaries / source / "dictionary.sqlite3").read_bytes()).hexdigest()
                  for source in ("oald10", "mw-now")}
        result, report = self.enrich(cards)
        self.assertEqual(cards, original)
        self.assertEqual(result[0]["id"], "stable")
        self.assertEqual(result[0]["examples"], original[0]["examples"])
        self.assertEqual(result[0]["note"], "keep")
        self.assertEqual(result[0]["phonetic"], "/us/")
        local = result[0]["local_dictionary"]
        self.assertEqual(local["forms"][0]["form"], "studies")
        self.assertEqual(local["derived"][0]["word"], "studious")
        self.assertEqual(len(local["audio"]["oxford"]), 2)
        self.assertEqual(len(local["audio"]["webster"]), 1)
        self.assertEqual(local["audio"]["oxford"][0]["accent"], "us")
        self.assertEqual(report["media_files"], 3)
        self.assertEqual(report["counts"]["oxford_senses"], 1)
        self.assertEqual(report["missing"]["webster_audio"], [])
        self.assertEqual(len(list(self.media.glob("*.mp3"))), 3)
        for source in hashes:
            self.assertEqual(hashlib.sha256((self.dictionaries / source / "dictionary.sqlite3").read_bytes()).hexdigest(), hashes[source])
        for filename, item in report["media"].items():
            self.assertEqual(hashlib.sha256((self.media / filename).read_bytes()).hexdigest(), item["sha256"])

    def test_missing_dictionary_content_remains_empty_and_is_reported(self):
        result, report = self.enrich([{"id": "missing", "word": "doesnotexist", "definition": "old definition"}])
        local = result[0]["local_dictionary"]
        self.assertEqual(local["senses"], [])
        self.assertEqual(local["forms"], [])
        self.assertEqual(local["audio"], {"oxford": [], "webster": []})
        self.assertEqual(report["missing"]["oxford_senses"], [{"id": "missing", "word": "doesnotexist"}])
        self.assertEqual(report["media_files"], 0)
        self.assertEqual(local["fallback_audio"], {})
        self.assertEqual(local["definition_source"], "wordbook")
        self.assertEqual(local["definition_fallback"], "old definition")
        self.assertEqual(report["fallback_counts"], {"audio": 0, "definitions": 1})

    def test_empty_definition_missing_word_reaches_preview_missing_state(self):
        from anki_pipeline.packaging import render_preview
        original = {"id": "missing", "sheet": "Unit 1", "lesson": "Lesson 1", "position": "1",
                    "word": "doesnotexist", "phonetic": "", "definition": "", "simple_definition": "",
                    "level": "", "word_forms": "", "audio_filename": "", "examples": []}
        cards, report = self.enrich([original])
        local = cards[0]["local_dictionary"]
        self.assertEqual(local["definition_source"], "oxford")
        self.assertEqual(local["definition_fallback"], "")
        self.assertEqual(local["senses"], [])
        self.assertEqual(report["fallback_counts"], {"audio": 0, "definitions": 0})
        rendered = render_preview(cards[0], self.media)
        self.assertIn('data-dictionary="oxford"', rendered)
        self.assertIn("牛津原包未收录此词的中文释义", rendered)

    def test_cross_dictionary_audio_fallback_is_explicit_and_missing_stays_reported(self):
        for name in ["word_uk.mp3", "word_us.mp3"]:
            (self.dictionaries / "oald10/resources" / name).unlink()
        result, report = self.enrich([{"id": "stable", "word": "study"}])
        local = result[0]["local_dictionary"]
        self.assertEqual(local["audio"]["oxford"], [])
        self.assertEqual(len(local["audio"]["webster"]), 1)
        self.assertEqual(local["fallback_audio"], {"oxford": "webster"})
        self.assertEqual(local["definition_source"], "oxford")
        self.assertEqual(local["definition_fallback"], "")
        self.assertEqual(report["missing"]["oxford_audio"], [{"id": "stable", "word": "study"}])
        self.assertEqual(report["counts"]["oxford_audio"], 0)
        self.assertEqual(report["counts"]["webster_audio"], 1)
        self.assertEqual(report["fallbacks"]["audio"], [{"id": "stable", "word": "study",
            "requested_source": "oxford", "actual_source": "webster"}])

    def test_definition_fallback_uses_each_original_card_without_polluting_senses(self):
        conn = sqlite3.connect(self.dictionaries / "oald10/dictionary.sqlite3")
        conn.execute("DELETE FROM entries")
        conn.commit()
        conn.close()
        originals = [{"id": "one", "word": "study", "definition": "n. 学习；研究"},
                     {"id": "two", "word": "study", "definition": "v. 学习；攻读"}]
        result, report = self.enrich(originals)
        for card, original in zip(result, originals):
            local = card["local_dictionary"]
            self.assertEqual(card["id"], original["id"])
            self.assertEqual(local["senses"], [])
            self.assertEqual(local["definition_source"], "wordbook")
            self.assertEqual(local["definition_fallback"], original["definition"])
        self.assertEqual(report["counts"]["oxford_senses"], 0)
        self.assertEqual(report["fallback_counts"], {"audio": 2, "definitions": 2})

    def test_duplicate_words_deduplicate_media_but_not_cards(self):
        cards = [{"id": "one", "word": "study"}, {"id": "two", "word": "study"}]
        first, report = self.enrich(cards)
        self.assertEqual(len(first), 2)
        self.assertEqual(report["cards"], 2)
        self.assertEqual(report["unique_words"], 1)
        self.assertEqual(report["media_files"], 3)
        again, next_report = self.enrich(cards)
        self.assertEqual(first, again)
        self.assertEqual(report, next_report)
        first[0]["local_dictionary"]["senses"].clear()
        self.assertTrue(first[1]["local_dictionary"]["senses"])

    def test_variant_heading_looks_up_first_line_without_changing_title_or_id(self):
        source = {"id": "stable", "word": "study\n(美study)", "examples": []}
        cards, report = self.enrich([source])
        self.assertEqual(cards[0]["id"], "stable")
        self.assertEqual(cards[0]["word"], source["word"])
        self.assertEqual(cards[0]["local_dictionary"]["lookup_word"], "study")
        self.assertEqual(report["missing"]["oxford_audio"], [])

    def test_explicit_multiword_spelling_reference_maps_only_requested_word(self):
        content = '''<div id="dictionary-entry-1"><div class="entry-header">
        <h1 class="hword">studie, studious</h1></div><p class="cxl-ref">
        <span class="cxl">chiefly British spellings of</span>
        <a class="cxt" href="study">study</a>,
        <a class="cxt" href="studious">studious</a></p></div>'''
        conn = sqlite3.connect(self.dictionaries / "mw-now/dictionary.sqlite3")
        for number, word, html in [(2, "studie", content), (3, "studious", WEBSTER_HTML.replace("study", "studious"))]:
            encoded = html.encode()
            conn.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)", (number, word, _normalize(word),
                html, None, "", len(encoded), hashlib.sha256(encoded).hexdigest()))
        conn.commit()
        conn.close()
        original = {"id": "stable", "word": "studie\n(美study)", "examples": [{"text": "keep"}]}
        cards, report = self.enrich([original])
        card = cards[0]
        self.assertEqual(card["id"], original["id"])
        self.assertEqual(card["word"], original["word"])
        self.assertEqual(card["examples"], original["examples"])
        local = card["local_dictionary"]
        self.assertEqual(len(local["audio"]["webster"]), 1)
        expected = hashlib.sha256((self.dictionaries / "mw-now/resources/sound/study.mp3").read_bytes()).hexdigest()
        self.assertEqual(local["audio"]["webster"][0]["sha256"], expected)
        spelling = [item for item in local["provenance"]["webster"] if item.get("role") == "spelling_variant_audio"]
        self.assertEqual(len(spelling), 1)
        self.assertEqual(spelling[0]["headword"], "study")
        self.assertEqual(spelling[0]["declared_variant"], "studie")
        self.assertEqual(spelling[0]["via_entry_id"], 2)
        self.assertEqual(report["missing"]["webster_audio"], [])

    def test_non_spelling_root_reference_does_not_substitute_pronunciation(self):
        content = '''<div id="dictionary-entry-1"><div class="entry-header">
        <h1 class="hword">studies</h1></div><p class="cxl-ref">
        <span class="cxl">plural of</span><a class="cxt" href="study">study</a></p></div>'''
        conn = sqlite3.connect(self.dictionaries / "mw-now/dictionary.sqlite3")
        encoded = content.encode()
        conn.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)", (2, "studies", "studies", content,
            None, "", len(encoded), hashlib.sha256(encoded).hexdigest()))
        conn.commit()
        conn.close()
        cards, report = self.enrich([{"id": "root", "word": "studies"}])
        self.assertEqual(cards[0]["local_dictionary"]["audio"]["webster"], [])
        self.assertEqual(report["missing"]["webster_audio"], [{"id": "root", "word": "studies"}])

    def test_corrupt_resource_aborts_instead_of_substituting_old_audio(self):
        (self.dictionaries / "oald10/resources/word_us.mp3").write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.enrich([{"id": "one", "word": "study", "audio_filename": "old.mp3"}])

    def test_media_destination_inside_source_and_invalid_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            enrich_dictionary_cards([{"id": "one", "word": "study"}], self.dictionaries,
                                    self.dictionaries / "oald10/resources/new")
        with self.assertRaisesRegex(ValueError, "IDs"):
            self.enrich([{"id": "one", "word": "study"}, {"id": "one", "word": "good"}])

    def test_alias_cycles_and_missing_targets_have_bounded_resolution(self):
        conn = sqlite3.connect(self.dictionaries / "oald10/dictionary.sqlite3")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        for number, word, target in [(2, "alias", "study"), (3, "cycle", "cycle"), (4, "lost", "absent")]:
            conn.execute("INSERT INTO entries VALUES(?,?,?,?,?,?,?,?)", (number, word, _normalize(word), "", target, "", 0, ""))
        resolved, issues = _resolve_entries(conn, "alias")
        self.assertEqual([(row["headword"], chain) for row, chain in resolved], [("study", ["alias"])])
        self.assertEqual(issues, [])
        self.assertEqual(_resolve_entries(conn, "cycle")[1][0]["type"], "redirect_cycle")
        self.assertEqual(_resolve_entries(conn, "lost")[1][0]["type"], "missing_redirect_target")
        self.assertEqual(_find_entries(conn, "STUDY")[0]["headword"], "study")

    def test_resource_path_traversal_and_escape_symlink_are_rejected(self):
        conn = sqlite3.connect(self.dictionaries / "oald10/dictionary.sqlite3")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        for key in ("../secret.mp3", "%2e%2e/secret.mp3", "sound://remote.mp3"):
            with self.assertRaises(ValueError):
                _resource(conn, key, self.dictionaries / "oald10")
        (self.dictionaries / "oald10/resources/word_us.mp3").unlink()
        (self.dictionaries / "oald10/resources/word_us.mp3").symlink_to(self.root / "outside.mp3")
        with self.assertRaisesRegex(ValueError, "escapes"):
            _resource(conn, "word_us.mp3", self.dictionaries / "oald10")

    def test_existing_different_output_is_preserved(self):
        self.media.mkdir()
        resource = {"data": b"ID3source", "sha256": hashlib.sha256(b"ID3source").hexdigest()}
        destination = self.media / f"dict_oxford_{resource['sha256']}.mp3"
        destination.write_bytes(b"user file")
        with self.assertRaises(FileExistsError):
            _copy_audio(resource, "oxford", self.media)
        self.assertEqual(destination.read_bytes(), b"user file")

    def test_helper_loader_uses_private_modules_not_dictionary_lookup_globals(self):
        helpers = self.root / "helpers"
        helpers.mkdir()
        (helpers / "html_tree.py").write_text("SENTINEL = 42\n")
        (helpers / "mw_parser.py").write_text("from html_tree import SENTINEL\n")
        before = {name: sys.modules.get(name) for name in ("html_tree", "lookup", "mw_parser")}
        module, digest = _load_webster_parser(helpers)
        self.assertEqual(module.SENTINEL, 42)
        self.assertEqual(len(digest), 64)
        self.assertEqual(before, {name: sys.modules.get(name) for name in before})


@unittest.skipUnless((ROOT / "mw-now/dictionary.sqlite3").exists(), "User dictionary exports are not installed")
class ActualExportIntegrationTest(unittest.TestCase):
    def test_nine_declared_british_spellings_use_actual_webster_variant_recordings(self):
        pairs = {"humour": "humor", "emphasise": "emphasize", "analyse": "analyze",
                 "recognise": "recognize", "artefact": "artifact", "utilise": "utilize",
                 "paralyse": "paralyze", "endeavour": "endeavor", "honour": "honor"}
        originals = [{"id": f"keep-{word}", "word": word, "examples": [{"text": "keep"}]} for word in pairs]
        with tempfile.TemporaryDirectory() as temporary:
            cards, report = enrich_dictionary_cards(originals, ROOT, Path(temporary))
            self.assertEqual(report["missing"]["webster_audio"], [])
            self.assertEqual(report["counts"]["webster_audio"], 9)
            for card, original in zip(cards, originals):
                self.assertEqual(card["id"], original["id"])
                self.assertEqual(card["word"], original["word"])
                self.assertEqual(card["examples"], original["examples"])
                local = card["local_dictionary"]
                self.assertTrue(local["audio"]["webster"])
                self.assertEqual(local["fallback_audio"], {})
                provenance = [item for item in local["provenance"]["webster"]
                              if item.get("role") == "spelling_variant_audio"]
                self.assertTrue(provenance)
                self.assertEqual({item["headword"] for item in provenance}, {pairs[card["word"]]})
                self.assertTrue(all(item["declared_variant"] == card["word"] for item in provenance))

    def test_actual_ambition_dominate_and_irregular_forms(self):
        words = ["ambition", "dominate", "run", "good", "neighbourhood"]
        with tempfile.TemporaryDirectory() as temporary:
            cards, report = enrich_dictionary_cards([{"id": word, "word": word} for word in words], ROOT, Path(temporary))
            self.assertEqual(report["missing"], {"oxford_senses": [], "oxford_audio": [],
                                                 "webster_audio": [], "webster_entry": []})
            by_word = {card["word"]: card["local_dictionary"] for card in cards}
            self.assertEqual(by_word["ambition"]["senses"], [{"pos": "n.", "text": "追求的目标；夙愿"},
                                                               {"pos": "n.", "text": "野心；雄心；志向；抱负"}])
            ambition_forms = {(item["kind"], item["form"]) for item in by_word["ambition"]["forms"]}
            # Webster actually includes a verb sense attested from 1601.
            self.assertIn(("past", "ambitioned"), ambition_forms)
            self.assertIn(("present_participle", "ambitioning"), ambition_forms)
            run_forms = {(item["kind"], item["form"]) for item in by_word["run"]["forms"]}
            self.assertIn(("past", "ran"), run_forms)
            self.assertIn(("past_participle", "run"), run_forms)
            self.assertFalse(any(item["kind"] == "third_person_singular" for item in by_word["good"]["forms"]))
            self.assertEqual(by_word["dominate"]["phonetic"], "/ˈdɑːmɪneɪt/")
            self.assertEqual(len(by_word["dominate"]["audio"]["webster"]), 1)
            self.assertEqual(len(by_word["dominate"]["audio"]["oxford"]), 2)
            self.assertEqual(by_word["neighbourhood"]["provenance"]["webster"][0]["redirect_chain"], ["neighbourhood"])

    def test_source_only_phrase_entries_case_audio_and_genuine_missing_recordings(self):
        words = ["catalogue\n(美catalog)", "consist", "ascribe", "outset", "rely", "derive",
                 "devote", "deprive", "rid", "inquire", "advent", "customs", "means", "exsert"]
        with tempfile.TemporaryDirectory() as temporary:
            cards, report = enrich_dictionary_cards([{"id": word, "word": word} for word in words], ROOT, Path(temporary))
            by_word = {card["word"]: card["local_dictionary"] for card in cards}
            self.assertEqual(report["missing"]["oxford_senses"], [{"id": "exsert", "word": "exsert"}])
            self.assertEqual(report["missing"]["oxford_audio"], [{"id": "exsert", "word": "exsert"}])
            self.assertEqual(report["missing"]["webster_audio"], [{"id": "customs", "word": "customs"},
                                                                  {"id": "means", "word": "means"}])
            self.assertTrue(all("phrase" in sense for sense in by_word["consist"]["senses"]))
            self.assertTrue(any(item.get("role") == "linked_phrase" for item in by_word["rely"]["provenance"]["oxford"]))
            self.assertTrue(any(item.get("role") == "case_variant_audio" for item in by_word["advent"]["provenance"]["webster"]))
            self.assertEqual(len(by_word["inquire"]["audio"]["oxford"]), 2)
            self.assertEqual(by_word["catalogue\n(美catalog)"]["lookup_word"], "catalogue")

    def test_three_genuine_gaps_keep_actual_source_and_explicit_fallback(self):
        database = Path(__file__).resolve().parents[1] / "data/anki.sqlite3"
        if not database.exists():
            self.skipTest("Original wordbook database is not installed")
        conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            originals = [dict(row) for row in conn.execute("SELECT * FROM cards WHERE word IN ('exsert','customs','means') ORDER BY word")]
        finally:
            conn.close()
        self.assertEqual(len(originals), 3)
        with tempfile.TemporaryDirectory() as temporary:
            cards, report = enrich_dictionary_cards(originals, ROOT, Path(temporary))
            by_word = {card["word"]: card for card in cards}
            original_by_word = {card["word"]: card for card in originals}
            exsert = by_word["exsert"]["local_dictionary"]
            self.assertEqual(exsert["audio"]["oxford"], [])
            self.assertTrue(exsert["audio"]["webster"])
            self.assertEqual(exsert["fallback_audio"], {"oxford": "webster"})
            self.assertEqual(exsert["senses"], [])
            self.assertEqual(exsert["definition_source"], "wordbook")
            self.assertEqual(exsert["definition_fallback"], original_by_word["exsert"]["definition"])
            for word in ["customs", "means"]:
                local = by_word[word]["local_dictionary"]
                self.assertEqual(local["audio"]["webster"], [])
                self.assertTrue(local["audio"]["oxford"])
                self.assertEqual(local["fallback_audio"], {"webster": "oxford"})
                self.assertEqual(local["definition_source"], "oxford")
            for card in cards:
                self.assertEqual(card["id"], original_by_word[card["word"]]["id"])
            self.assertEqual(report["counts"]["oxford_senses"], 2)
            self.assertEqual(report["counts"]["oxford_audio"], 2)
            self.assertEqual(report["counts"]["webster_audio"], 1)
            self.assertEqual(report["fallback_counts"], {"audio": 3, "definitions": 1})
            self.assertEqual([item["word"] for item in report["missing"]["oxford_senses"]], ["exsert"])
            self.assertEqual([item["word"] for item in report["missing"]["webster_audio"]], ["customs", "means"])


if __name__ == "__main__":
    unittest.main()
