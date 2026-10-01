"""Read-only reconciliation of the frequency build, old notes and all web cards."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import parse_qs, urlsplit
import zipfile

import genanki
from lxml import html

from anki_pipeline.store import logical_digest
from anki_pipeline.config import load_config


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
BASELINE = OUTPUT / "history/before-exam-frequency"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def by_class(tree, name):
    return tree.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " ' + name + ' ")]')


def package_notes(path):
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "collection.anki2"
        database.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(database) as connection:
            notes = {guid: fields.split("\x1f") for guid, fields in connection.execute("SELECT guid, flds FROM notes")}
            models = json.loads(connection.execute("SELECT models FROM col").fetchone()[0])
        return notes, models, json.loads(archive.read("media"))


def main():
    delivery = json.loads((OUTPUT / "dictionary-delivery-report.json").read_text())
    frequency = delivery["exam_library"]["frequency"]
    # Current source has aligned translations everywhere. This lets target
    # markup independently reconcile counts without rerunning the accumulator.
    require(delivery["exam_library"]["skipped_unaligned_matches"] == 0, "source has untranslated matches; use a source-level audit")
    require(load_config(ROOT / "config.toml").exam_max_examples == 0, "this audit requires unlimited source examples")
    baseline = json.loads((BASELINE / "baseline.json").read_text())
    require(logical_digest(ROOT / "data/anki.sqlite3") == baseline["source_database_logical_digest"], "source database changed")
    source_hashes = json.loads((BASELINE / "source-index-hashes.json").read_text())["source_files"]
    require(all(checksum(Path(path)) == sha for path, sha in source_hashes.items()), "source sentence index changed")
    package = OUTPUT / "Anki-本地双词典版.apkg"
    old_package = BASELINE / "output/Anki-本地双词典版.apkg"
    new, new_models, new_media = package_notes(package)
    old, old_models, old_media = package_notes(old_package)
    require(new.keys() == old.keys(), "note GUIDs changed")
    require(new_media == old_media, "media filename mapping changed")
    require(new_models.keys() == old_models.keys(), "model IDs changed")
    for model_id, model in new_models.items():
        require([x["name"] for x in model["flds"]] == [x["name"] for x in old_models[model_id]["flds"]], "field order changed")
    web = delivery["web"]
    version = Path(web["version_directory"])
    catalog = json.loads((version / "catalog.json").read_text())
    require(len(catalog["cards"]) == len(new), "web/APKG card counts differ")
    catalog_guids = [genanki.guid_for("anki-rebuild-card-v1", entry["id"]) for entry in catalog["cards"]]
    require(len(set(catalog_guids)) == len(catalog_guids) and set(catalog_guids) == new.keys(), "web GUIDs duplicated or missing")
    counts, distribution, examples = [], Counter(), 0
    countdown_script = '<script>' + (ROOT / 'anki_pipeline/templates/countdown.js').read_text() + '</script>'
    for entry in catalog["cards"]:
        guid = genanki.guid_for("anki-rebuild-card-v1", entry["id"])
        fields, original = new[guid], old[guid]
        require(len(fields) == 10, "model lost ten-field contract")
        require(all(fields[i] == original[i] for i in range(10) if i not in {2, 8}), f"unrelated field changed: {entry['word']}")
        require(fields[8] == original[8] + countdown_script, f"countdown helper changed original metadata: {entry['word']}")
        require(fields[2].endswith(original[2]) and fields[2].startswith('<style>'), "original definition was replaced rather than retained after frequency")
        definition = html.fragment_fromstring(fields[2], create_parent="div")
        sections = by_class(definition, "exam-frequency")
        require(len(sections) == 1, "missing/duplicate frequency section")
        section = sections[0]
        require(section.get("data-schema") == "kaoyan-frequency.v1" and section.get("data-rule") == "occurrence-bands.v1", "frequency schema/rule missing")
        occurrences, score = int(section.get("data-occurrences")), float(section.get("data-stars"))
        # Deliberately independent of the production frequency_stars function.
        expected = sum(occurrences >= floor for floor in (1, 2, 3, 5, 8, 13, 20, 30, 50, 80)) / 2
        require(score == expected, f"wrong band: {entry['word']}")
        require(len(by_class(section, "frequency-star")) == 5, "not five stars")
        widths = [float(x.get("width").removesuffix("%")) for x in by_class(section, "frequency-star-fill")]
        require(all(width in {50, 100} for width in widths) and sum(widths) / 100 == score, "wrong half-star fill")
        example_tree = html.fragment_fromstring(fields[7] or "<div></div>", create_parent="div")
        require(len(by_class(example_tree, "target-word")) == occurrences, f"count differs from every source-token highlight: {entry['word']}")
        matched_sentences = len(by_class(example_tree, "example-card"))
        papers = {parse_qs(urlsplit(link.get("data-full-paper-url")).query)["paper"][0]
                  for link in by_class(example_tree, "sentence-jump")}
        require(int(section.get("data-matched-sentences")) == matched_sentences, "matched sentence count differs")
        require(int(section.get("data-paper-count")) == len(papers), "paper coverage differs from source jumps")
        require(int(section.get("data-corpus-papers")) == delivery["exam_library"]["papers"], "corpus paper count differs")
        examples += matched_sentences
        page_path = OUTPUT / entry["previewUrl"]
        page = page_path.read_text()
        require(fields[2] in page, "web/APKG frequency or definition differs")
        page_tree = html.fromstring(page)
        require(len(by_class(page_tree, "exam-frequency")) == 1, "web frequency duplicated")
        front = page_tree.get_element_by_id("preview-front")
        require(not by_class(front, "exam-frequency"), "answer frequency leaks onto front")
        counts.append(occurrences)
        distribution[f"{score:.1f}"] += 1
    require(sum(counts) == frequency["total_occurrences"], "report total differs")
    require(sum(count > 0 for count in counts) == frequency["nonzero_cards"], "report nonzero cards differs")
    require(dict(distribution) == {key: value for key, value in frequency["star_distribution"].items() if value}, "report star distribution differs")
    require(examples == delivery["exam_library"]["examples"], "example count changed")
    result = {"verified_at": datetime.now(timezone.utc).isoformat(), "status": "PASS",
              "package_sha256": checksum(package), "web_version": web["input_digest"],
              "cards": len(new), "source_index_files_unchanged": len(source_hashes),
              "source_database_unchanged": True, "guid_model_ten_fields_media_preserved": True,
              "eight_other_fields_byte_identical": True,
              "original_meta_preserved_with_fixed_countdown_script_only": True,
              "countdown_script_sha256": checksum(ROOT / 'anki_pipeline/templates/countdown.js'), "examples": examples,
              "occurrences": sum(counts), "stars": dict(sorted(distribution.items())),
              "web_apkg_all_frequency_sections_identical": True,
              "counts_reconciled_against_all_target_word_markup": True,
              "source_jump_paper_coverage_and_sentence_counts_all_verified": True,
              "five_shapes_and_half_fills_all_verified": True,
              "scope": "Current unlimited, fully translated corpus; static artifacts, not GUI import."}
    (OUTPUT / "exam-frequency-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
