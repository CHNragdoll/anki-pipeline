#!/usr/bin/env python3
"""Prepare source-pinned, unreviewed sense records without changing live data.

Definitions and declared counts come from the currently active web libraries.
Matching uses explicit displayed dictionary inflections, their Webster ownership,
the reviewed Codex corpus and source-pinned homograph exclusions. Each original
Unicode token position is retained. No semantic assignment is guessed here.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import pickle
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.exam_library import _canonical_codex_sentences
from anki_pipeline.local_dictionary import (
    _Tree, _find_entries, _load_webster_parser, _normalize, _resolve_entries,
)
from anki_pipeline.match_forms import card_match_forms
from anki_pipeline.occurrence_exclusions import load_occurrence_exclusions
from anki_pipeline.sense_frequency import prepare_record
from anki_pipeline.source_paths import display_source_path, prepare_source_paths
from anki_pipeline.text import word_variants

SCHEMA = "sense-frequency-inventory.v1"
LABELS = {"原形": "base", "复数": "plural", "第三人称单数": "third_person_singular",
          "现在分词": "present_participle", "过去式": "past", "过去分词": "past_participle",
          "比较级": "comparative", "最高级": "superlative"}
TOKEN = re.compile(r"(?<!\w)[^\W\d_]+(?:[-'][^\W\d_]+)*(?!\w)", re.UNICODE)


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def progress(stage, **fields):
    print(canonical_json({"stage": stage, **fields}), flush=True)


def class_aliases(version):
    """Read the shipped reverse class map; never execute its JavaScript."""
    mappings = {}
    for path in sorted((version / "assets").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'"classes"\s*:\s*(\{[^{}]*\})', text):
            for alias, original in json.loads(match[1]).items():
                if alias in mappings and mappings[alias] != original:
                    raise ValueError("conflicting shipped class aliases")
                mappings[alias] = original
    return mappings


def fragments(page, tag, class_name, aliases):
    """Extract complete small markup sections without parsing large srcdoc data."""
    for opening in re.finditer(r"<" + tag + r"\b[^>]*>", page):
        classes = re.search(r'\bclass="([^"]*)"', opening[0])
        if not classes or class_name not in {aliases.get(x, x) for x in classes[1].split()}:
            continue
        depth = 1
        for closing in re.finditer(r"</?" + tag + r"\b[^>]*>", page[opening.end():]):
            depth += -1 if closing[0].startswith("</") else 1
            if depth == 0:
                yield page[opening.start():opening.end() + closing.end()]
                break
        else:
            raise ValueError("unterminated definition/form markup")


def tree(fragment, aliases):
    root = _Tree(fragment).root
    for node in root.walk():
        if "class" in node.attrs:
            node.attrs["class"] = " ".join(aliases.get(x, x) for x in node.attrs["class"].split())
    return root


def descendant(node, class_name):
    return next((x for x in node.walk() if x.has_class(class_name)), None)


def parse_card_page(page, aliases):
    # CSS contains '#preview-back', so anchor only on its real opening element.
    back = re.search(r'<div\b[^>]*\bid="preview-back"[^>]*>', page)
    scope = page[back.end():] if back else page
    definitions, senses, form_sections, positions, cursor = [], [], [], [], 0
    for index, fragment in enumerate(fragments(scope, "div", "dictionary-definition", aliases)):
        position = scope.index(fragment, cursor)
        cursor = position + len(fragment)
        positions.append(position)
        root = tree(fragment, aliases)
        definition = descendant(root, "dictionary-definition")
        source = definition.attrs.get("data-dictionary", "unknown")
        component = []
        for row in definition.walk():
            if not row.has_class("sense-row"):
                continue
            pos, text = descendant(row, "sense-pos"), descendant(row, "sense-text")
            if text is not None and text.text().strip():
                component.append({"pos": pos.text().strip() if pos is not None else "",
                                  "text": text.text().strip()})
        # Unlabelled source text is still a displayed sense, with its own source.
        if not component:
            for row in definition.walk():
                if row.has_class("sense-unlabelled") and row.text().strip():
                    component.append({"pos": "", "text": row.text().strip()})
        definitions.append({"source": source, "component_index": index,
                            "sense_start": len(senses), "sense_count": len(component),
                            "html_sha256": digest(fragment.encode())})
        senses.extend(component)
    if len(definitions) > 1:
        for definition, position in zip(definitions, positions):
            # Compound-word cards print an unclassified component h3 directly
            # before its frequency/definition block. Frequency headings use a
            # class, so they cannot replace this exact source headword evidence.
            headings = re.findall(r"<h3>\s*([^<]+?)\s*</h3>", scope[:position])
            if not headings:
                raise ValueError("compound definition has no original component headword")
            definition["headword"] = html.unescape(headings[-1]).strip()
    groups = list(fragments(scope, "div", "dictionary-form-groups", aliases))
    for fragment in groups:
        root = tree(fragment, aliases)
        group = descendant(root, "dictionary-form-groups")
        default_source = group.attrs.get("data-dictionary", "webster")
        for section in group.walk():
            if not section.has_class("dictionary-inflections"):
                continue
            source = section.attrs.get("data-dictionary", default_source)
            rows = []
            for row in section.walk():
                if not row.has_class("form-row") or row.has_class("derived-word"):
                    continue
                label = next((n for n in row.walk() if n.tag == "dt"), None)
                value = next((n for n in row.walk() if n.tag == "dd"), None)
                if label is None or value is None:
                    raise ValueError("malformed displayed inflection")
                # The renderer places provenance notes in a small element.
                text = "".join(n if isinstance(n, str) else n.text()
                               for n in value.children if isinstance(n, str) or n.tag != "small").strip()
                rows.append({"label": label.text().strip(), "form": text})
            form_sections.append({"source": source, "rows": rows})
    frequencies = [int(x) for x in re.findall(r'\bdata-occurrences="(\d+)"', scope)]
    return {"senses": senses, "definitions": definitions, "form_sections": form_sections,
            "declared_counts": frequencies}


def load_libraries(libraries, web_root, words=None):
    cards, inventory, hashes = [], [], {}
    for book_id, entry in libraries:
        entry = entry.resolve(strict=True)
        match = re.search(r'data-catalog-url="([^"]+)"', entry.read_text(encoding="utf-8"))
        if not match:
            raise ValueError("web library has no catalog reference")
        catalog_path = (entry.parent / html.unescape(match[1])).resolve(strict=True)
        if not catalog_path.is_relative_to(web_root):
            raise ValueError("catalog escapes web root")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        aliases = class_aliases(catalog_path.parent)
        identities = [x["id"] for x in catalog["cards"]]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate web card identity")
        hashes[str(entry)] = digest(entry.read_bytes())
        hashes[str(catalog_path)] = digest(catalog_path.read_bytes())
        inventory.append({"book_id": book_id, "entry": str(entry), "cards": len(identities)})
        for card in catalog["cards"]:
            if words is not None and card["word"] not in words:
                continue
            page_path = (web_root / card["previewUrl"].lstrip("/")).resolve(strict=True)
            if not page_path.is_relative_to(web_root):
                raise ValueError("card preview escapes web root")
            raw = page_path.read_bytes()
            parsed = parse_card_page(raw.decode("utf-8"), aliases)
            cards.append({**card, **parsed, "book_id": book_id, "page_sha256": digest(raw)})
        progress("web-library", book_id=book_id, selected_cards=sum(x["book_id"] == book_id for x in cards))
    return cards, inventory, hashes


class DisplayedForms:
    """Validate displayed Webster forms against original explicit ownership."""
    def __init__(self, dictionary_root):
        root = dictionary_root / "mw-now"
        self.parser, self.parser_hash = _load_webster_parser(root)
        self.db = sqlite3.connect((root / "dictionary.sqlite3").resolve(strict=True).as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA query_only=ON")
        self.cache = {}
        self.cache_snapshot = {}
        self.cached_words = self._seed_cache(root)

    def _seed_cache(self, root):
        """Reuse prior plain build data only while its source snapshot is valid."""
        directory = ROOT / "output/redbook-20261002"
        paths = [directory / name for name in ("dictionary.pickle", "dictionary-report.json", "baseline.json")]
        if not all(p.is_file() for p in paths):
            return 0
        report = json.loads(paths[1].read_text(encoding="utf-8")).get("sources", {}).get("webster", {})
        baseline = json.loads(paths[2].read_text(encoding="utf-8")).get("source_stats", {})
        database = (root / "dictionary.sqlite3").resolve(strict=True)
        stat = database.stat()
        manifest = root / "manifest.json"
        if (report.get("parser_sha256") != self.parser_hash or
                report.get("manifest_sha256") != digest(manifest.read_bytes()) or
                baseline.get(str(database)) != {"bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}):
            return 0
        class PlainUnpickler(pickle.Unpickler):
            def find_class(self, module, name):
                raise pickle.UnpicklingError("dictionary cache must contain only plain data")
        with paths[0].open("rb") as stream:
            cards = PlainUnpickler(stream).load()
        if not isinstance(cards, list):
            raise ValueError("dictionary build cache must be a card array")
        for card in cards:
            local = card.get("local_dictionary", {})
            word, provenance = local.get("lookup_word"), local.get("provenance", {}).get("webster", [])
            if not isinstance(word, str) or not word:
                raise ValueError("cached dictionary headword is missing")
            for pin in provenance:
                row = self.db.execute("SELECT sha256 FROM entries WHERE id=?", (pin["entry_id"],)).fetchone()
                if row is None or row[0] != pin["sha256"]:
                    raise ValueError("cached Webster entry no longer matches its pinned source")
            selected = local.get("webster_forms", local.get("forms", []))
            if word in self.cache and self.cache[word] != selected:
                raise ValueError("conflicting cached dictionary forms")
            self.cache[word] = selected
        self.cache_snapshot = {str(path): digest(path.read_bytes()) for path in paths}
        progress("dictionary-cache-validated", words=len(self.cache))
        return len(self.cache)

    def close(self):
        self.db.close()

    def variants(self, card):
        word = card["word"]
        lookup = word.replace("\r", "\n").split("\n", 1)[0].strip()
        # A slash title explicitly licenses both component headwords; no other
        # punctuation is silently expanded into guessed lexical alternatives.
        parts = lookup.split("/") if re.fullmatch(r"[a-z]+(?:/[a-z]+)+", lookup, re.I) else [lookup]
        variants, evidence, issues = set(), [], []
        sections = card["form_sections"]
        for index, part in enumerate(parts):
            section = sections[index] if len(sections) == len(parts) else sections[0] if len(parts) == 1 and sections else {"source": "", "rows": []}
            rows, source = section["rows"], section["source"]
            selected = []
            if source in {"webster", "mixed"} and rows:
                if part not in self.cache:
                    resolved, _ = _resolve_entries(self.db, part)
                    self.cache[part] = self.parser.relations(self.db, resolved, _find_entries, _resolve_entries, _normalize)["word_forms"]
                relations = self.cache[part]
                for row in rows:
                    matches = [r for r in relations if r["label"] == row["label"] and r["form"] == row["form"]]
                    if not matches:
                        issues.append({"type": "displayed_webster_form_not_source_verified", "headword": part, **row})
                    selected.extend(matches)
                actual_source = "webster"
            elif source == "ecdict":
                for row in rows:
                    if row["label"] not in LABELS:
                        issues.append({"type": "unknown_displayed_inflection_label", **row})
                        continue
                    selected.append({"kind": LABELS[row["label"]], "form": row["form"], "label": row["label"], "source": "ecdict"})
                actual_source = "ecdict"
            else:
                actual_source = ""
                if rows:
                    issues.append({"type": "unsupported_displayed_forms_source", "source": source})
            matching_card = {"word": part if len(parts) > 1 else word,
                             "local_dictionary": {"forms_source": actual_source, "forms": selected}}
            forms = card_match_forms(matching_card)
            variants.update(word_variants(matching_card["word"], forms, infer=False))
            evidence.append({"headword": part, "source": actual_source, "forms": selected,
                             "accepted_match_forms": sorted(forms)})
        return variants, evidence, issues


def token_index(sentences, wanted):
    """Index full tokens and hyphen/apostrophe components under exact boundaries."""
    index = defaultdict(list)
    for sentence in sentences:
        english = sentence["english"]
        for token in TOKEN.finditer(english):
            pieces = list(re.finditer(r"[^\W\d_]+", token[0], re.UNICODE))
            for first in range(len(pieces)):
                for last in range(first, len(pieces)):
                    start, end = token.start() + pieces[first].start(), token.start() + pieces[last].end()
                    form = english[start:end].casefold()
                    if form in wanted:
                        index[form].append((sentence, [start, end]))
    return index


def source_exclusions(staging, sources, cards):
    path = staging / "targets/occurrence-exclusions.json"
    if not path.exists():
        return set(), None
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Pin identities belong to source wordbooks. Their exact word and source
    # position transfer to another edition; no global inflection is removed.
    pins = {x["cardId"]: {"id": x["cardId"], "word": x["word"]} for x in payload["exclusions"]}
    excluded, aliases, sha = load_occurrence_exclusions(path, sources, list(pins.values()))
    words = {row["id"]: row["word"] for row in pins.values()}
    output = {(sid, words[cid], start, end) for sid, cid, start, end in excluded}
    output.update((sid, words[cid], start, end) for sid, cid, start, end in aliases)
    return output, sha


def occurrence(sentence, span, paths):
    aligned = [a for a in sentence["alignments"] if a["en"][0] < span[1] and span[0] < a["en"][1]]
    ranges = sorted({tuple(r) for a in aligned for r in a["zh"]})
    return {"physical_source": sentence["canonical_occurrence_key"],
            "paper_id": sentence["paperId"], "sentence_id": sentence["id"],
            "english": sentence["english"], "english_hash": sentence["englishHash"],
            "translation": sentence["translationZh"], "source": display_source_path(paths[sentence["id"]]),
            "target_range": span, "translation_ranges": [list(r) for r in ranges],
            "alignment": sentence["translation_alignment"],
            "alignment_evidence": [{"english_range": a["en"], "translation_ranges": a["zh"],
                                    "relation": a["relation"]} for a in aligned],
            "source_provenance": {"reviewedContentHash": sentence["reviewedContentHash"],
                "sourceHash": sentence["sourceHash"], "sourceSentenceIds": sentence["source_sentence_ids"],
                "sourceBlockIds": sentence["sourceBlockIds"], "sourceFragments": sentence["sourceFragments"],
                "sourceSentenceRefs": sentence["sourceSentenceRefs"],
                "paragraphId": sentence["paragraphId"], "paragraphRange": [sentence["start"], sentence["end"]],
                "sourcePathEvidence": paths[sentence["id"]]},
            "status": "unmatched", "sense_index": None, "reason": "等待逐条义项核对",
            "method": "context-review", "review_version": "20261011"}


def write_offset_index(path, *, work_items=False):
    """Index UTF-8 byte offsets for bounded parallel review without rereading GB."""
    rows, offset, sha = [], 0, hashlib.sha256()
    with path.open("rb") as stream:
        for line in stream:
            sha.update(line)
            value = json.loads(line)
            record = value["record"] if work_items else value
            row = {"word": record["word"], "byte_offset": offset, "byte_length": len(line),
                   "occurrences": record["expected_occurrences"], "senses": len(record["senses"])}
            if work_items:
                row.update(work_id=value["work_id"], cards=value["cards"])
            else:
                row.update(book_id=record["book_id"], card_id=record["card_id"])
            rows.append(row)
            offset += len(line)
    result = {"schema": "sense-frequency-jsonl-offsets.v1", "encoding": "utf-8",
              "file": path.name, "sha256": sha.hexdigest(), "bytes": offset, "records": rows}
    with path.with_suffix(".index.json").open("x", encoding="utf-8") as output:
        output.write(canonical_json(result) + "\n")
    return result


def prepare(libraries, staging, dictionary_root, output, web_root, words=None):
    started = time.monotonic()
    output = output.resolve()
    if output.exists():
        raise FileExistsError("inventory output must be a new directory")
    cards, libraries_report, input_hashes = load_libraries(libraries, web_root, words)
    sources, corpus_report = load_codex_exam_index(staging)
    sentences, dedup_report = _canonical_codex_sentences(sources)
    paths, _, watched, source_report = prepare_source_paths(ROOT, sources)
    input_hashes.update({str(p): h for p, h in watched.items()})
    input_hashes.update({str(staging / p): h for p, h in corpus_report["source_files"].items()})
    excluded, exclusion_hash = source_exclusions(staging, sources, cards)
    forms = DisplayedForms(dictionary_root)
    try:
        for number, card in enumerate(cards, 1):
            card["variants"], card["matching_evidence"], card["form_issues"] = forms.variants(card)
            if number % 2000 == 0:
                progress("forms-validated", cards=number, elapsed_seconds=round(time.monotonic()-started, 2))
        parser_hash = forms.parser_hash
        cached_words = forms.cached_words
        input_hashes.update(forms.cache_snapshot)
    finally:
        forms.close()
    wanted = set().union(*(card["variants"] for card in cards))
    index = token_index(sentences, wanted)
    progress("indexed", cards=len(cards), sentences=len(sentences), variants=len(wanted), elapsed_seconds=round(time.monotonic()-started, 2))
    output.mkdir(parents=True)
    reconciliation, skipped, work_items, record_count = [], [], {}, 0
    composite_token_summary = []
    token_counts, sense_counts, records_by_book = Counter(), Counter(), Counter()
    with (output / "records.jsonl").open("x", encoding="utf-8") as stream:
        for card in cards:
            if not card["senses"]:
                skipped.append({"book_id": card["book_id"], "card_id": card["id"], "word": card["word"], "reason": "no_displayed_dictionary_senses"})
                continue
            found = {}
            for form in sorted(card["variants"]):
                for sentence, span in index.get(form, []):
                    if any((sid, card["word"], *span) in excluded for sid in sentence["source_sentence_ids"]):
                        continue
                    key = canonical_json([sentence["paperId"], sentence["canonical_occurrence_key"], span])
                    found[key] = (sentence, span)
            occurrences = [occurrence(sentence, span, paths) for _, (sentence, span) in sorted(found.items())]
            declared = sum(card["declared_counts"]) if card["declared_counts"] else None
            source_names = sorted({x["source"] for x in card["definitions"]})
            source = source_names[0] if len(source_names) == 1 else "mixed"
            record = {"book_id": card["book_id"], "card_id": card["id"], "word": card["word"],
                      "definition_source": source,
                      "definition_provenance": {"web_source": card["previewUrl"], "page_sha256": card["page_sha256"],
                                                "headword": card["word"], "components": card["definitions"]},
                      "senses": card["senses"], "expected_occurrences": len(occurrences), "occurrences": occurrences,
                      "matching_evidence": card["matching_evidence"],
                      "frequency_reconciliation": {"declared_web_occurrences": declared,
                                                   "physical_occurrences": len(occurrences),
                                                   "status": "equal" if declared == len(occurrences) else "missing" if declared is None else "different"},
                      "needs_composite_rendering": len(card["definitions"]) > 1}
            if record["needs_composite_rendering"]:
                tokens = Counter(row["english"][slice(*row["target_range"])].casefold() for row in occurrences)
                headwords = {component["headword"].casefold() for component in card["definitions"]}
                composite_token_summary.append({"book_id": card["book_id"], "card_id": card["id"],
                    "word": card["word"], "target_token_counts": dict(tokens),
                    "not_exact_component_headword": {form: count for form, count in tokens.items() if form not in headwords},
                    "review_rule": "Explicit dictionary inflections establish lexical candidates only; source-aware semantic review is still required."})
            prepared = prepare_record(record)
            if len(prepared["occurrences"]) != len(occurrences):
                raise ValueError("inventory has duplicate physical token identities")
            stream.write(canonical_json(record) + "\n")
            record_count += 1
            token_counts[card["book_id"]] += len(occurrences)
            sense_counts[card["book_id"]] += len(card["senses"])
            records_by_book[card["book_id"]] += 1
            work_key = digest(canonical_json([card["word"], source, card["senses"],
                                              [r["occurrence_id"] for r in prepared["occurrences"]]]).encode())
            if work_key not in work_items:
                work_items[work_key] = {"work_id": work_key, "record": record, "cards": []}
            work_items[work_key]["cards"].append({"book_id": card["book_id"], "card_id": card["id"]})
            if declared != len(occurrences) or card["form_issues"]:
                reconciliation.append({"book_id": card["book_id"], "card_id": card["id"], "word": card["word"],
                                       **record["frequency_reconciliation"], "form_issues": card["form_issues"]})
    with (output / "work-items.jsonl").open("x", encoding="utf-8") as stream:
        for value in work_items.values():
            stream.write(canonical_json(value) + "\n")
    record_index = write_offset_index(output / "records.jsonl")
    work_index = write_offset_index(output / "work-items.jsonl", work_items=True)
    report = {"schema": SCHEMA, "libraries": libraries_report, "records": record_count,
              "records_by_book": dict(records_by_book), "senses_by_book": dict(sense_counts),
              "physical_tokens_by_book": dict(token_counts), "unique_work_items": len(work_items),
              "unique_work_tokens": sum(r["record"]["expected_occurrences"] for r in work_items.values()),
              "pending_records_only": True, "database_written": False, "source_written": False,
              "alignment_schema": "codex-sentence-alignment.v1",
              "corpus": corpus_report, "canonical_deduplication": dedup_report,
              "source_paths": source_report, "input_sha256": input_hashes,
              "webster_parser_sha256": parser_hash, "occurrence_exclusions_sha256": exclusion_hash,
              "source_verified_dictionary_cache_words": cached_words,
              "composite_token_review": composite_token_summary,
              "jsonl_sha256": {record_index["file"]: record_index["sha256"], work_index["file"]: work_index["sha256"]},
              "reconciliation_issues": len(reconciliation), "skipped_cards": skipped,
              "elapsed_seconds": round(time.monotonic() - started, 2)}
    (output / "reconciliation.json").write_text(json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    progress("complete", output=str(output), records=record_count, work_items=len(work_items),
             physical_tokens_by_book=dict(token_counts), issues=len(reconciliation), elapsed_seconds=report["elapsed_seconds"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", action="append", help="book_id=/absolute/or/relative/preview-library.html")
    parser.add_argument("--staging", type=Path, default=ROOT.parent / "exam-library/data/staging/codex-translations-v1")
    parser.add_argument("--dictionary-root", type=Path, default=ROOT.parent / "dictionary-unpacked")
    parser.add_argument("--web-root", type=Path, default=ROOT / "output")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--word", action="append", help="Optional small source-verification subset; repeat for multiple words")
    args = parser.parse_args()
    libraries = []
    for item in args.library or ["redbook=" + str(ROOT / "output/redbook-20261004/preview-library.html"),
                                 "redbook2027=" + str(ROOT / "output/redbook-2027-20261006/preview-library.html")]:
        book, separator, path = item.partition("=")
        if not book or not separator or not path:
            parser.error("--library must be book_id=path")
        libraries.append((book, Path(path)))
    prepare(libraries, args.staging.resolve(strict=True), args.dictionary_root.resolve(strict=True),
            args.output, args.web_root.resolve(strict=True), set(args.word) if args.word else None)


if __name__ == "__main__":
    main()
