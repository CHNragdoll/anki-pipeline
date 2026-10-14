"""Verify lossless slim APKG updates in a disposable native Anki collection.

No profile path is accepted. Baseline and slim packages are read-only inputs;
all scheduling mutations occur in a TemporaryDirectory. --qa exports actual
native question/answer HTML and non-audio media for a separate browser check.
This verifier does not claim physical-device acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_final_apkg_native import (
    APP_PACKAGES, FIELD_NAMES, ROOT, _extract_database, _identities,
    _media_checks, _native_identities, _native_states,
    check_guid_models, check_runtime_bytes, file_sha, nfc,
    project_card_states, require, sha,
)
from scripts import verify_final_apkg_native as baseline_verifier

OWN = ROOT / "output/slim-anki-20261015"
BASELINE = ROOT / "output/final-anki-20261015"
COUNTS = {"2026": 6682, "2027": 6532}
BASELINE_SHA = {
    "2026": "227399bbd6cfa2c8f268dda51034caa48bce957a9846b3c5306849cc3080d36b",
    "2027": "4a41e3e57ac9ea7563d3bb1223fa92474e92100484b2e98766c4a324a5ae4c46",
}
QA_WORDS = ("abide", "the", "more", "training", "train", "oblige", "as", "teem", "deep-rooted")
AUDIO_SUFFIXES = frozenset((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus"))


def check_exact_identities(before, after):
    prior = {row[1]: tuple(row) for row in before}
    current = {row[1]: tuple(row) for row in after}
    require(len(prior) == len(before) and len(current) == len(after), "duplicate note GUID")
    require(current == prior, "slim update changed a note GUID, note ID or model ID")


def check_exact_states(before, after):
    require(after == before, "slim update changed a card identity, schedule, suspension or flag")


def check_slim_model(actual, expected, runtime):
    require([f["name"] for f in actual["flds"]] == [f["name"] for f in expected["flds"]],
            "native model fields differ from slim package")
    require(nfc(actual["css"]) == nfc(expected["css"]), "native model CSS differs from slim package")
    require(len(actual["tmpls"]) == len(expected["tmpls"]) > 0, "native model template count differs")
    dispose = runtime.get("dispose", "AnkiSlimApkgDispose")
    hydrate = runtime.get("hydrate", "AnkiSlimApkgHydrate")
    for got, wanted in zip(actual["tmpls"], expected["tmpls"]):
        for face in ("qfmt", "afmt"):
            require(nfc(got[face]) == nfc(wanted[face]), "native model template differs from slim package")
        require(dispose in got["qfmt"], "native question has no slim disposal runtime")
        require(f'src="{runtime["js"]}"' in got["afmt"] and hydrate in got["afmt"],
                "native answer has no slim hydration runtime")


def _check_fields_and_models(collection, expected, models, runtime):
    candidates = {}
    checked = 0
    for nid, guid, mid, fields, tags in expected.execute("select id,guid,mid,flds,tags from notes order by id"):
        actual = collection.db.first("select id,mid,flds,tags from notes where guid=?", guid)
        require(actual is not None and actual[1] == mid, "native note does not match slim package identity")
        require(nfc(actual[2]) == nfc(fields), "native fields differ from slim package for GUID " + guid)
        require(set(actual[3].split()) == set(tags.split()), "native note tags differ from slim package")
        names = [field["name"] for field in models[str(mid)]["flds"]]
        if "Word" in names:
            word = html.unescape(actual[2].split("\x1f")[names.index("Word")])
            if word in QA_WORDS:
                require(word not in candidates, "QA word is not unique: " + word)
                candidates[word] = {"guid": guid, "nid": actual[0], "package_nid": nid, "mid": mid}
        checked += 1
    for mid, wanted in models.items():
        actual = collection.models.get(int(mid))
        require(actual is not None, "native model missing")
        if tuple(field["name"] for field in wanted["flds"]) == FIELD_NAMES:
            check_slim_model(actual, wanted, runtime)
        else:
            require(nfc(actual["css"]) == nfc(wanted["css"]), "guide model CSS differs")
            require([f["name"] for f in actual["flds"]] == [f["name"] for f in wanted["flds"]], "guide fields differ")
            require(len(actual["tmpls"]) == len(wanted["tmpls"]), "guide template count differs")
            for got, template in zip(actual["tmpls"], wanted["tmpls"]):
                require(all(nfc(got[face]) == nfc(template[face]) for face in ("qfmt", "afmt")), "guide templates differ")
    return checked, candidates


def export_qa(collection, candidates, media_map, target):
    require(set(candidates) == set(QA_WORDS), "native QA sample words are missing")
    target.mkdir(exist_ok=False)
    media_directory = Path(collection.media.dir())
    copied = []
    for name in sorted(media_map.values()):
        if Path(name).suffix.lower() in AUDIO_SUFFIXES:
            continue
        source = media_directory / name
        require(source.is_file(), "native non-audio media absent: " + name)
        destination = target / name
        require(not destination.exists(), "QA media destination collision")
        shutil.copyfile(source, destination)
        copied.append({"file": name, "sha256": file_sha(destination)})
    samples = []
    for word in QA_WORDS:
        identity = candidates[word]
        cards = collection.db.all("select id from cards where nid=? order by id", identity["nid"])
        require(len(cards) == 1, "QA sample must have exactly one card")
        card = collection.get_card(cards[0][0])
        css = collection.models.get(identity["mid"])["css"]
        for face, content in (("question", card.question()), ("answer", card.answer())):
            document = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
                        'content="width=device-width,initial-scale=1"><title>' + html.escape(word + " " + face) +
                        '</title><style>' + css + '</style></head><body class="card">' + content + '</body></html>')
            path = target / f"{word}-{face}.html"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(document)
            samples.append({"word": word, "face": face, **identity, "cid": card.id,
                            "file": str(path), "sha256": file_sha(path)})
    return {"path": str(target), "actual_native_render": True, "samples": samples,
            "non_audio_media": copied, "browser_verified": False}


def _supplemental_guids(database, models):
    result = {}
    for guid, mid, fields in database.execute("select guid,mid,flds from notes"):
        names = [field["name"] for field in models[str(mid)]["flds"]]
        if "Word" not in names:
            continue
        word = html.unescape(fields.split("\x1f")[names.index("Word")])
        if word in ("deep-rooted", "teem"):
            require(word not in result, "duplicate supplemental word")
            result[word] = guid
    require(set(result) == {"deep-rooted", "teem"}, "baseline supplemental lexemes are missing")
    return result


def _check_native_media_bytes(collection, package, media_map):
    directory = Path(collection.media.dir())
    with zipfile.ZipFile(package) as archive:
        for key, name in media_map.items():
            path = directory / name
            require(path.is_file(), "native media absent: " + name)
            with archive.open(key) as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == file_sha(path),
                        "native media bytes differ: " + name)
    return len(media_map)


def resolve_scope(year, report, output_root=None, baseline_root=None):
    """Resolve a report within caller-selected roots without loosening baseline identity."""
    require(year in COUNTS, "unsupported year")
    own = Path(OWN if output_root is None else output_root).expanduser().resolve()
    baseline = Path(BASELINE if baseline_root is None else baseline_root).expanduser().resolve()
    package = Path(report["output"]).expanduser().resolve()
    source = Path(report["source"]).expanduser().resolve()
    expected_source = baseline / f"{year}红宝书完整版-最新释义校勘与chunk-20261015.apkg"
    require(package.parent == own and package.name.startswith(f"{year}红宝书完整版-")
            and package.suffix == ".apkg", "build report output package is outside selected scope")
    require(source == expected_source, "build report baseline package is outside selected scope")
    return package, source


def verify(year: str, qa: bool = False, output_root=None, baseline_root=None):
    start = time.monotonic()
    require(year in COUNTS, "unsupported year")
    own = Path(OWN if output_root is None else output_root).expanduser().resolve()
    folder = own / year
    require(folder.resolve().parent == own, "verification folder is outside selected output root")
    report_path = folder / "build-report.json"
    result_path = folder / "native-verification.json"
    require(not result_path.exists(), "verification output already exists; preserve it before another run")
    require(not qa or not (folder / "native-qa").exists(), "native QA output already exists")
    report_bytes = report_path.read_bytes()
    guard_path = Path(baseline_verifier.__file__)
    guard_sha = file_sha(guard_path)
    report = json.loads(report_bytes)
    require(str(report["year"]) == year, "build report year differs")
    package, source = resolve_scope(year, report, own, baseline_root)
    require(report["cards"] == COUNTS[year], "build report card count differs")
    require(package.stat().st_size == report["bytes"] and file_sha(package) == report["sha256"], "slim package changed")
    require(file_sha(source) == report["source_sha256"] == BASELINE_SHA[year], "baseline package changed")
    runtime = report["runtime"]
    media_map = _media_checks(source, package, runtime)
    sys.path.insert(0, str(APP_PACKAGES))
    from anki.collection import Collection
    from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest
    import_options = {"with_scheduling": True}

    def import_package(collection, path):
        collection.import_anki_package(ImportAnkiPackageRequest(
            package_path=str(path), options=ImportAnkiPackageOptions(**import_options)))
        collection.models._clear_cache()

    attempts = []
    with tempfile.TemporaryDirectory(prefix="slim-redbook-native-") as directory:
        scratch = Path(directory)
        old = _extract_database(source, scratch / "baseline.anki2")
        expected = _extract_database(package, scratch / "expected.anki2")
        collection = None
        try:
            package_identities = _identities(old)
            expected_identities = _identities(expected)
            check_exact_identities(package_identities, expected_identities)
            old_models = json.loads(old.execute("select models from col").fetchone()[0])
            models = json.loads(expected.execute("select models from col").fetchone()[0])
            supplemental = _supplemental_guids(old, old_models)
            (scratch / "native").mkdir()
            collection = Collection(str(scratch / "native/collection.anki2"))
            import_package(collection, source)
            check_guid_models(package_identities, _native_identities(collection))
            require(collection.card_count() == collection.note_count() == COUNTS[year], "baseline native import count differs")
            cid = collection.db.scalar("select id from cards where queue>=0 and type=0 order by id limit 1")
            require(cid is not None, "baseline has no schedulable review sample")
            collection.decks.select(collection.get_card(cid).did)
            collection.sched.reset()
            queued_cards = collection.sched.get_queued_cards(fetch_limit=1).cards
            require(bool(queued_cards), "native scheduler returned no review sample")
            queued = queued_cards[0]
            reviewed = collection.get_card(queued.card.id)
            reviewed.start_timer()
            collection.sched.answer_card(collection.sched.build_answer(card=reviewed, states=queued.states, rating=3))
            collection.sched.suspend_cards([reviewed.id])
            collection.set_user_flag_for_cards(3, [reviewed.id])
            identities = _native_identities(collection)
            states = _native_states(collection)
            history = collection.db.all("select * from revlog order by id")
            review_card = collection.get_card(reviewed.id)
            require(bool(history) and review_card.queue == -1 and review_card.user_flag() == 3,
                    "native answer, suspension and flag were not persisted")
            for attempt in range(2):
                phase_start = time.monotonic()
                import_package(collection, package)
                require(collection.card_count() == collection.note_count() == COUNTS[year], "slim native import count differs")
                check_exact_identities(identities, _native_identities(collection))
                check_guid_models(expected_identities, _native_identities(collection))
                check_exact_states(states, _native_states(collection))
                require(collection.db.all("select * from revlog order by id") == history, "slim import altered review log")
                extra_cards = collection.db.all(
                    "select c.id,c.queue,n.guid from cards c join notes n on n.id=c.nid where n.guid in (?,?) order by c.id",
                    *sorted(supplemental.values()))
                require(len(extra_cards) == 2 and all(row[1] == -1 for row in extra_cards), "supplemental cards lost suspension")
                checked, candidates = _check_fields_and_models(collection, expected, models, runtime)
                require(checked == COUNTS[year], "not all native fields were checked")
                media_directory = Path(collection.media.dir())
                check_runtime_bytes(runtime, (media_directory / runtime["js"]).read_bytes(), (media_directory / runtime["css"]).read_bytes())
                media_result = collection.media.check()
                require(not media_result.missing, "native collection has missing media")
                checked_media = _check_native_media_bytes(collection, package, media_map) if not attempt else None
                attempts.append({"attempt": attempt + 1, "operation": "update" if not attempt else "repeat",
                                 "notes_and_cards": checked, "all_fields_nfc_match_package": True,
                                 "all_identities_states_flags_revlog_preserved": True, "missing_media": 0,
                                 "native_media_byte_hashes_verified": checked_media,
                                 "elapsed_seconds": round(time.monotonic() - phase_start, 3)})
                print(json.dumps({"year": year, **attempts[-1]}, ensure_ascii=False), flush=True)
            qa_result = export_qa(collection, candidates, media_map, folder / "native-qa") if qa else None
            result = {"schema": "slim-full-apkg-native-verification.v1", "year": year,
                      "package": str(package), "package_sha256": report["sha256"],
                      "source": str(source), "source_sha256": BASELINE_SHA[year],
                      "output_root": str(own), "baseline_root": str(source.parent),
                      "build_report_sha256": sha(report_bytes), "verifier_sha256": file_sha(Path(__file__)),
                      "shared_guard_sha256": guard_sha,
                      "notes_and_cards": len(identities), "supplemental_notes_and_cards": 2,
                      "supplemental_guids": supplemental, "supplemental_queue": -1,
                      "source_package_identities_preserved": True, "native_baseline_identities_preserved": True,
                      "import_options": import_options,
                      "reviewed_suspended_and_flagged_original_card": reviewed.id, "preserved_revlog_rows": len(history),
                      "runtime": runtime, "original_media_bytes_preserved": True,
                      "native_media_byte_hashes_verified": len(media_map),
                      "attempts": attempts, "qa": qa_result, "actual_user_collection_modified": False,
                      "phone_verified": False, "native_import_verified": True}
        finally:
            if collection is not None:
                collection.close()
            old.close()
            expected.close()
    require(report_path.read_bytes() == report_bytes, "build report changed during native verification")
    require(file_sha(guard_path) == guard_sha, "shared verifier guards changed during native verification")
    require(file_sha(package) == report["sha256"] and file_sha(source) == BASELINE_SHA[year], "package changed during native verification")
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    with result_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"year": year, "result": str(result_path), "sha256": file_sha(result_path),
                      "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    return result


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", choices=sorted(COUNTS), required=True)
    parser.add_argument("--qa", action="store_true", help="export native HTML and flat non-audio media")
    parser.add_argument("--output-root", type=Path, help="owned output root; defaults to the original slim package directory")
    parser.add_argument("--baseline-root", type=Path, help="baseline package directory; fixed original package SHA remains required")
    return parser.parse_args(argv)


def main():
    args = parse_arguments()
    verify(args.year, args.qa, args.output_root, args.baseline_root)


if __name__ == "__main__":
    main()
