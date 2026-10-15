"""Verify full APKG updates in a disposable native Anki collection.

The collection path is always created by TemporaryDirectory. No profile path
can be supplied. --qa exports actual native question/answer HTML and non-audio
media for a separate browser check; it does not claim device acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWN = ROOT / "output/final-anki-20261015"
APP_PACKAGES = Path("/Applications/Anki.app/Contents/Resources/app_packages")
COUNTS = {"2026": 6682, "2027": 6532}
FIELD_NAMES = ("Word", "Phonetic", "Definition", "SimpleDefinition", "Level",
               "WordForms", "Audio", "Examples", "Meta", "Note")
QA_WORDS = ("oblige", "train", "training", "as", "deep-rooted", "teem", "data")
SOURCE_SHA = {
    "2026": "a2461fc562cdc8870b13c94ab4338a1c7f1a7f10d75df1ea8eb400d60a7f746d",
    "2027": "a687a998d037c3c7b5f213c0f70378a4d8dfbe43b152e873bf00a7bada0a4512",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def check_identities(before, after, new_guids):
    prior = {row[1]: tuple(row) for row in before}
    current = {row[1]: tuple(row) for row in after}
    require(len(prior) == len(before) and len(current) == len(after), "duplicate note GUID")
    require(len(new_guids) == 2 and set(current) == set(prior) | set(new_guids),
            "note identity set differs from original plus two supplemental notes")
    require(not set(prior) & set(new_guids), "supplemental GUID collides with original")
    require(all(current.get(guid) == row for guid, row in prior.items()),
            "original GUID, note ID or model ID changed")


def check_guid_models(expected, actual):
    """First import may assign IDs; GUID and model identity remain exact."""
    wanted = {row[1]: tuple(row) for row in expected}
    current = {row[1]: tuple(row) for row in actual}
    require(len(current) == len(actual) and set(current) == set(wanted),
            "new native import package GUID set differs")
    require(len(wanted) == len(expected), "duplicate package GUID")
    require(all(current[guid][2] == row[2] for guid, row in wanted.items()),
            "native import package model ID differs")


def project_card_states(columns, rows):
    require("id" in columns, "cards table has no identity")
    included = [i for i, name in enumerate(columns) if name not in ("mod", "usn")]
    identity = columns.index("id")
    result = {row[identity]: tuple(row[i] for i in included) for row in rows}
    require(len(result) == len(rows), "duplicate card ID")
    return result


def check_original_states(before, after):
    require(all(after.get(cid) == row for cid, row in before.items()),
            "original card schedule, suspension, flags or identity changed")


def check_runtime_bytes(runtime, js_bytes, css_bytes):
    require(sha(js_bytes) == runtime["js_sha256"], "runtime JS byte hash differs")
    require(sha(css_bytes) == runtime["css_sha256"], "runtime CSS byte hash differs")


def check_runtime_model(actual, expected, runtime):
    require([f["name"] for f in actual["flds"]] == [f["name"] for f in expected["flds"]],
            "native model fields differ from package")
    require(nfc(actual["css"]) == nfc(expected["css"]), "native model CSS differs from package")
    require(len(actual["tmpls"]) == len(expected["tmpls"]) > 0, "native model template count differs")
    for got, wanted in zip(actual["tmpls"], expected["tmpls"]):
        for face in ("qfmt", "afmt"):
            require(nfc(got[face]) == nfc(wanted[face]), "native model template differs from package")
        require("AnkiFinalApkgDispose" in got["qfmt"], "native question has no current disposal runtime")
        require(f'src="{runtime["js"]}"' in got["afmt"] and "AnkiFinalApkgHydrate" in got["afmt"],
                "native answer has no current hydration runtime")


def _extract_database(package, destination):
    with zipfile.ZipFile(package) as archive, archive.open("collection.anki2") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target, length=1024 * 1024)
    database = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    require(database.execute("pragma quick_check").fetchone()[0] == "ok", "package database is corrupt")
    return database


def _identities(database):
    return database.execute("select id,guid,mid from notes order by id").fetchall()


def _native_identities(collection):
    return collection.db.all("select id,guid,mid from notes order by id")


def _native_states(collection):
    columns = [row[1] for row in collection.db.all("pragma table_info(cards)")]
    return project_card_states(columns, collection.db.all("select * from cards order by id"))


def _media_map(archive):
    result = json.loads(archive.read("media"))
    require(isinstance(result, dict) and len(set(result.values())) == len(result), "package media map is not unique")
    for name in result.values():
        require(isinstance(name, str) and name not in ("", ".", "..") and Path(name).name == name,
                "package media path is not flat")
    return result


def _media_checks(source, package, runtime):
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(package) as new:
        prior = _media_map(old)
        current = _media_map(new)
        reverse = {name: key for key, name in current.items()}
        require(set(prior.values()) <= set(current.values()), "original media filename was removed")
        for key, name in prior.items():
            with old.open(key) as one, new.open(reverse[name]) as two:
                require(hashlib.file_digest(one, "sha256").digest() == hashlib.file_digest(two, "sha256").digest(),
                        "original media bytes changed: " + name)
        check_runtime_bytes(runtime, new.read(reverse[runtime["js"]]), new.read(reverse[runtime["css"]]))
        return current


def _fields_and_models(collection, expected, models, runtime):
    checked = 0
    qa = {}
    for nid, guid, mid, fields in expected.execute("select id,guid,mid,flds from notes order by id"):
        actual = collection.db.first("select id,mid,flds from notes where guid=?", guid)
        require(actual is not None and actual[1] == mid,
                "native note does not match package identity")
        require(nfc(actual[2]) == nfc(fields), "native fields differ from package for GUID " + guid)
        names = [field["name"] for field in models[str(mid)]["flds"]]
        if "Word" in names:
            word = html.unescape(actual[2].split("\x1f")[names.index("Word")])
            if word in QA_WORDS:
                require(word not in qa, "QA word is not unique: " + word)
                qa[word] = {"guid": guid, "nid": actual[0], "package_nid": nid, "mid": mid}
        checked += 1
    for mid, expected_model in models.items():
        actual = collection.models.get(int(mid))
        require(actual is not None, "native model missing")
        if tuple(f["name"] for f in expected_model["flds"]) == FIELD_NAMES:
            check_runtime_model(actual, expected_model, runtime)
        else:
            require(nfc(actual["css"]) == nfc(expected_model["css"]), "guide model CSS differs")
            require([f["name"] for f in actual["flds"]] == [f["name"] for f in expected_model["flds"]], "guide fields differ")
            require(len(actual["tmpls"]) == len(expected_model["tmpls"]), "guide template count differs")
            for got, wanted in zip(actual["tmpls"], expected_model["tmpls"]):
                require(all(nfc(got[face]) == nfc(wanted[face]) for face in ("qfmt", "afmt")), "guide templates differ")
    return checked, qa


def _export_qa(collection, candidates, media_map, target):
    require(set(candidates) == set(QA_WORDS), "native QA sample words are missing")
    target.mkdir(exist_ok=False)
    media_directory = Path(collection.media.dir())
    copied = []
    for name in sorted(media_map.values()):
        if Path(name).suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac", ".opus"):
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


def verify(year: str, qa: bool = False):
    start = time.monotonic()
    require(year in COUNTS, "unsupported year")
    folder = OWN / year
    report_path = folder / "report.json"
    result_path = folder / "native-verification.json"
    require(not result_path.exists(), "native verification output already exists; preserve it before another run")
    require(not qa or not (folder / "native-qa").exists(), "native QA output already exists")
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    require(report.get("schema") == "final-full-apkg.v1" and str(report.get("year")) == year, "build report scope differs")
    package = OWN / f"{year}红宝书完整版-最新释义校勘与chunk-20261015.apkg"
    source = Path("/Users/apple/Downloads") / f"{year}红宝书完整版-手机词根与跳转交互修复-20261010.apkg"
    require(Path(report["output"]) == package and Path(report["source"]) == source, "build report package paths differ")
    require(report["cards"] == COUNTS[year] and report["supplemental_cards_suspended"] == 2, "build report cardinality differs")
    require(package.stat().st_size == report["bytes"] and file_sha(package) == report["sha256"], "new package is incomplete or changed")
    require(file_sha(source) == report["source_sha256"] == SOURCE_SHA[year], "mother package changed")
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
    with tempfile.TemporaryDirectory(prefix="final-redbook-native-") as directory:
        scratch = Path(directory)
        old = _extract_database(source, scratch / "mother.anki2")
        expected = _extract_database(package, scratch / "expected.anki2")
        collection = None
        try:
            old_identities = _identities(old)
            expected_identities = _identities(expected)
            new_guids = {row[1] for row in expected_identities} - {row[1] for row in old_identities}
            check_identities(old_identities, expected_identities, new_guids)
            models = json.loads(expected.execute("select models from col").fetchone()[0])
            guide_guids = [guid for _, guid, mid in old_identities
                           if "Word" not in [f["name"] for f in models[str(mid)]["flds"]]]
            require(len(guide_guids) == report["guides"] == 1, "source guide scope differs")
            for guid in guide_guids:
                prior = old.execute("select flds from notes where guid=?", (guid,)).fetchone()[0]
                current = expected.execute("select flds from notes where guid=?", (guid,)).fetchone()[0]
                require(nfc(prior) != nfc(current) and "2026-10-15" in current, "original guide was not updated")
            supplemental_words = set()
            for guid in new_guids:
                fields, mid = expected.execute("select flds,mid from notes where guid=?", (guid,)).fetchone()
                names = [f["name"] for f in models[str(mid)]["flds"]]
                supplemental_words.add(html.unescape(fields.split("\x1f")[names.index("Word")]))
            require(supplemental_words == {"deep-rooted", "teem"}, "unexpected supplemental lexemes")
            (scratch / "native").mkdir()
            collection = Collection(str(scratch / "native/collection.anki2"))
            import_package(collection, source)
            check_guid_models(old_identities, _native_identities(collection))
            require(collection.card_count() == collection.note_count() == COUNTS[year] - 2, "mother native import count differs")
            cid = collection.db.scalar("select id from cards where queue>=0 and type=0 order by id limit 1")
            require(cid is not None, "mother package has no schedulable review sample")
            collection.decks.select(collection.get_card(cid).did)
            collection.sched.reset()
            queued_cards = collection.sched.get_queued_cards(fetch_limit=1).cards
            require(bool(queued_cards), "native scheduler returned no review sample")
            queued = queued_cards[0]
            reviewed = collection.get_card(queued.card.id)
            reviewed.start_timer()
            collection.sched.answer_card(collection.sched.build_answer(card=reviewed, states=queued.states, rating=3))
            collection.sched.suspend_cards([reviewed.id])
            states = _native_states(collection)
            history = collection.db.all("select * from revlog order by id")
            require(bool(history) and collection.get_card(reviewed.id).queue == -1, "native answer and suspension were not persisted")
            identities = _native_identities(collection)
            first_import_identities = None
            first_import_states = None
            for attempt in range(2):
                phase_start = time.monotonic()
                import_package(collection, package)
                require(collection.card_count() == collection.note_count() == COUNTS[year], "new native import count differs")
                check_identities(identities, _native_identities(collection), new_guids)
                actual_identities = [tuple(r) for r in _native_identities(collection)]
                check_guid_models(expected_identities, actual_identities)
                check_original_states(states, _native_states(collection))
                if first_import_identities is None:
                    first_import_identities = actual_identities
                    first_import_states = _native_states(collection)
                else:
                    require(actual_identities == first_import_identities, "repeat import changed a native note identity")
                    require(_native_states(collection) == first_import_states, "repeat import changed a native card state")
                require(collection.db.all("select * from revlog order by id") == history, "native update altered review log")
                extra_cards = collection.db.all("select c.id,c.queue,n.guid from cards c join notes n on n.id=c.nid where n.guid in (?,?) order by c.id", *sorted(new_guids))
                require(len(extra_cards) == 2 and all(row[1] == -1 for row in extra_cards), "supplemental cards are not both suspended")
                checked, candidates = _fields_and_models(collection, expected, models, runtime)
                require(checked == COUNTS[year], "not all native fields were checked")
                media_directory = Path(collection.media.dir())
                check_runtime_bytes(runtime, (media_directory / runtime["js"]).read_bytes(), (media_directory / runtime["css"]).read_bytes())
                media_result = collection.media.check()
                require(not media_result.missing, "native collection has missing media")
                attempts.append({"attempt": attempt + 1, "operation": "update" if not attempt else "repeat",
                                 "notes_and_cards": checked, "all_fields_nfc_match_package": True,
                                 "original_identities_states_revlog_preserved": True, "missing_media": 0,
                                 "elapsed_seconds": round(time.monotonic() - phase_start, 3)})
                print(json.dumps({"year": year, **attempts[-1]}, ensure_ascii=False), flush=True)
            qa_result = _export_qa(collection, candidates, media_map, folder / "native-qa") if qa else None
            native_original_nids = {row[1]: row[0] for row in identities}
            package_original_nids = {row[1]: row[0] for row in old_identities}
            result = {"schema": "final-full-apkg-native-verification.v1", "year": year,
                      "package": str(package), "package_sha256": report["sha256"],
                      "source": str(source), "source_sha256": SOURCE_SHA[year],
                      "build_report_sha256": sha(report_bytes), "verifier_sha256": file_sha(Path(__file__)),
                      "original_notes_and_cards": len(identities), "supplemental_notes_and_cards": 2,
                      "supplemental_guids": sorted(new_guids), "supplemental_queue": -1,
                      "supplemental_native_identities": [list(row) for row in first_import_identities if row[1] in new_guids],
                      "supplemental_package_identities": [list(row) for row in expected_identities if row[1] in new_guids],
                      "source_package_identities_preserved": True, "native_baseline_identities_preserved": True,
                      "native_initial_source_note_ids_reassigned": sum(
                          native_original_nids[guid] != nid for guid, nid in package_original_nids.items()),
                      "import_options": import_options,
                      "reviewed_and_suspended_original_card": reviewed.id, "preserved_revlog_rows": len(history),
                      "guide_updated": True, "runtime": runtime, "original_media_bytes_preserved": True,
                      "attempts": attempts, "qa": qa_result, "actual_user_collection_modified": False,
                      "phone_verified": False, "native_import_verified": True}
        finally:
            if collection is not None:
                collection.close()
            old.close()
            expected.close()
    require(report_path.read_bytes() == report_bytes, "build report changed during native verification")
    require(file_sha(package) == report["sha256"] and file_sha(source) == SOURCE_SHA[year], "package changed during native verification")
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    with result_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"year": year, "result": str(result_path), "sha256": file_sha(result_path),
                      "elapsed_seconds": result["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", choices=sorted(COUNTS), required=True)
    parser.add_argument("--qa", action="store_true", help="export actual native HTML plus flat non-audio media")
    args = parser.parse_args()
    verify(args.year, args.qa)


if __name__ == "__main__":
    main()
