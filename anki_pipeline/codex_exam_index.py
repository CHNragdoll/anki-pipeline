"""Read reviewed Codex sentence indexes without executing staging scripts.

The consumer independently binds the index to the exact input, translation and
review bytes. Partial data is available only through an explicit development
argument; production calls require all 44 papers and current approved reviews.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .translation_alignment import validate_translation_alignment


PAPER_NAMES = tuple(f"{year}-{series}" for year in range(2000, 2027)
                    for series in (("01",) if year < 2010 else ("01", "02")))
_PAPER_IDS = frozenset("kaoyan:" + name for name in PAPER_NAMES)
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_COUNT_FIELDS = ("paragraphs", "sentences", "alignments", "blocked")
_INPUT_COUNTS = ("paragraphs", "sentences", "blocked", "sourceParagraphs")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@dataclass(frozen=True)
class _Snapshot:
    path: Path
    stamp: tuple
    sha256: str

    def unchanged(self):
        try:
            before = _stamp(self.path)
            raw = self.path.read_bytes()
            return self.stamp == before == _stamp(self.path) and _sha(raw) == self.sha256
        except OSError:
            return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def _read_json(path: Path, root: Path):
    """Read one safe, stable file and return data plus its byte snapshot."""
    try:
        resolved = path.resolve(strict=True)
        _require(resolved.is_relative_to(root) and resolved.is_file(),
                 f"Codex source path escapes staging: {path}")
        before = _stamp(path)
        raw = path.read_bytes()
        _require(before == _stamp(path), f"Codex source changed while reading: {path}")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read Codex source: {path}") from exc
    _require(isinstance(value, dict), f"Codex source must be an object: {path}")
    return value, _Snapshot(path, before, _sha(raw))


def _bound(actual, recorded, label):
    _require(isinstance(recorded, str) and _HASH.fullmatch(recorded) and actual == recorded,
             f"Codex {label} hash mismatch")


def _counts(row, keys, label):
    _require(all(type(row.get(key)) is int and row[key] >= 0 for key in keys),
             f"Invalid Codex {label} counts")


def _rows(value, label):
    _require(isinstance(value, list) and all(isinstance(row, dict) for row in value),
             f"Invalid Codex {label} array")
    return value


def _span(value, text, label):
    _require(isinstance(value, list) and len(value) == 2 and
             all(type(n) is int for n in value) and 0 <= value[0] < value[1] <= len(text),
             f"Invalid Codex {label} range")
    return value


def _references(paragraph, original_fragments):
    context, source = paragraph["context"], paragraph["sourceEnglish"]
    sentences = {s["id"]: s for s in paragraph["sentences"]}
    for field in ("sourceFragments", "sourceSentenceRefs"):
        entries = _rows(context.get(field, []), field)
        seen, covered = set(), []
        for entry in entries:
            identifier, old = entry.get("id"), entry.get("sourceText")
            _require(isinstance(identifier, str) and identifier.startswith(paragraph["paperId"] + ":")
                     and isinstance(old, str),
                     f"Invalid or duplicate Codex {field} identity")
            _bound(_sha(old), entry.get("sourceHash"), field + " source")
            a, b = _span(entry.get("oldRange"), old, field + " old")
            if field == "sourceFragments":
                target = source
                group = original_fragments.setdefault(identifier, {"text": old, "spans": []})
                _require(group["text"] == old, f"Inconsistent Codex source fragment: {identifier}")
                group["spans"].append((a, b))
            else:
                _require(entry.get("catalog") in {"anki-sentence-index.v1", "codex-exam-translation-input.v1"}
                         and entry.get("targetSentenceId") in sentences,
                         f"Invalid Codex source sentence reference: {identifier}")
                target = sentences[entry["targetSentenceId"]]["english"]
            x, y = _span(entry.get("newRange"), target, field + " new")
            identity = (identifier, entry.get("targetSentenceId"), (a, b), (x, y)) \
                if field == "sourceSentenceRefs" else identifier
            _require(identity not in seen, f"Duplicate Codex {field} identity")
            seen.add(identity)
            _require(old[a:b] == target[x:y], f"Codex source reference text mismatch: {identifier}")
            covered.append((x, y))
        if field == "sourceFragments" and covered:
            cursor = 0
            for a, b in sorted(covered):
                _require(cursor <= a and not source[cursor:a].strip(),
                         f"Codex source fragments overlap or leave unmapped text: {paragraph['id']}")
                cursor = b
            _require(not source[cursor:].strip(), f"Codex source fragment tail is unmapped: {paragraph['id']}")


def _expected_sentences(source, translated):
    """Validate the reviewed source, then reproduce the producer's exact index rows."""
    paper_id = source.get("paperId")
    _require(source.get("schema") == "codex-exam-translation-input.v1" and paper_id in _PAPER_IDS,
             "Invalid Codex input schema or paper")
    _require(source.get("blocked") == [], "Codex source contains blocked paragraphs")
    _require(translated.get("schema") == "codex-exam-translations.v1" and
             translated.get("paperId") == paper_id, "Invalid Codex translation identity")
    paragraphs = _rows(source.get("paragraphs"), "paragraphs")
    _require(bool(paragraphs), f"Empty Codex paper: {paper_id}")
    translations = _rows(translated.get("paragraphs"), "translated paragraphs")
    translated_by_id = {}
    for row in translations:
        identifier = row.get("id")
        _require(isinstance(identifier, str) and identifier not in translated_by_id,
                 "Duplicate or invalid Codex translated paragraph")
        translated_by_id[identifier] = row
    seen_paragraphs, seen_sentences, cloze_numbers = set(), set(), set()
    original_fragments, expected, local_answers = {}, [], {}
    for paragraph in paragraphs:
        identifier = paragraph.get("id")
        _require(isinstance(identifier, str) and identifier.startswith(paper_id + ":")
                 and identifier not in seen_paragraphs, "Duplicate or invalid Codex paragraph ID")
        seen_paragraphs.add(identifier)
        raw, filled, kind = (paragraph.get(k) for k in ("sourceEnglish", "filledEnglish", "kind"))
        _require(isinstance(raw, str) and isinstance(filled, str) and filled.strip()
                 and isinstance(kind, str) and kind.strip(), f"Invalid Codex source: {identifier}")
        _bound(_sha(raw), paragraph.get("sourceHash"), "sourceEnglish")
        _require(kind == "cloze" or raw == filled, f"Codex non-cloze source was changed: {identifier}")
        context = paragraph.get("context")
        _require(isinstance(context, dict), f"Missing Codex context: {identifier}")
        _rows(context.get("sourceSentenceRefs", []), "sourceSentenceRefs")
        _rows(context.get("sourceFragments", []), "sourceFragments")
        block_ids = context.get("sourceBlockIds", [])
        _require(isinstance(block_ids, list) and all(isinstance(b, str) and b.startswith(paper_id + ":")
                 for b in block_ids) and len(set(block_ids)) == len(block_ids),
                 f"Invalid Codex sourceBlockIds: {identifier}")
        path = context.get("sourcePath") or context.get("questionId")
        _require(isinstance(path, str) and path.strip(), f"Missing Codex sourcePath/questionId: {identifier}")
        translation = translated_by_id.get(identifier)
        _require(translation is not None and translation.get("sourceHash") == paragraph["sourceHash"],
                 f"Codex translation is not bound to its paragraph: {identifier}")
        translated_sentences = _rows(translation.get("sentences"), "translated sentences")
        by_id = {}
        for row in translated_sentences:
            sid = row.get("id")
            _require(isinstance(sid, str) and sid not in by_id, "Duplicate Codex translated sentence")
            by_id[sid] = row
        sentences = _rows(paragraph.get("sentences"), "sentences")
        _require(bool(sentences), f"Empty Codex paragraph: {identifier}")
        cursor, paragraph_answers = 0, 0
        for sentence in sentences:
            sid, english = sentence.get("id"), sentence.get("english")
            _require(isinstance(sid, str) and sid.startswith(identifier + ":") and sid not in seen_sentences
                     and isinstance(english, str) and english.strip(), "Duplicate or invalid Codex sentence ID/text")
            seen_sentences.add(sid)
            start, end = _span([sentence.get("start"), sentence.get("end")], filled, "sentence")
            _require(cursor <= start and not filled[cursor:start].strip() and filled[start:end] == english,
                     f"Codex sentence range/text mismatch: {sid}")
            cursor = end
            answers = []
            previous_end = 0
            for answer in _rows(sentence.get("clozeAnswers"), "clozeAnswers"):
                a, b = _span([answer.get("start"), answer.get("end")], english, "cloze answer")
                number = answer.get("number")
                _require(kind == "cloze" and isinstance(number, str) and re.fullmatch(r"[1-9][0-9]*", number)
                         and number not in cloze_numbers and a >= previous_end
                         and english[a:b] == answer.get("answer"), f"Invalid Codex cloze answer: {sid}")
                cloze_numbers.add(number); previous_end = b; paragraph_answers += 1
                answers.append({"start": a, "end": b, "word": answer["answer"], "number": int(number)})
            local_answers[sid] = answers
            row = by_id.get(sid)
            _require(row is not None, f"Missing Codex translated sentence: {sid}")
            zh = row.get("translationZh")
            _require(isinstance(zh, str) and zh.strip() and zh == zh.strip(), f"Invalid Codex Chinese sentence: {sid}")
            payload = {"schema": "codex-sentence-alignment.v1", "englishHash": row.get("englishHash"),
                       "translationHash": _sha(zh), "alignments": row.get("alignments")}
            validate_translation_alignment(english, zh, payload)
            _require(bool(payload["alignments"]), f"Missing Codex alignments: {sid}")
            for link in payload["alignments"]:
                _require(not (link["relation"] == "equivalent" and len(english.split()) >= 8
                         and link["en"] == [0, len(english)] and link["zh"] == [[0, len(zh)]]),
                         f"Codex whole-sentence catch-all alignment: {sid}")
            expected.append({"id": sid, "paperId": paper_id, "paragraphId": identifier,
                "kind": kind, "sourcePath": path, "context": copy.deepcopy(context),
                "sourceBlockIds": copy.deepcopy(block_ids), "sourceHash": paragraph["sourceHash"],
                "sourceEnglish": raw, "filledEnglish": filled, "start": start, "end": end,
                "english": english, "englishHash": _sha(english), "translationZh": zh,
                "clozeAnswers": copy.deepcopy(sentence['clozeAnswers']),
                "translationHash": _sha(zh), "alignments": copy.deepcopy(payload["alignments"]),
                "reviewedContentHash": _sha(zh + "\0" + json.dumps(payload["alignments"],
                    ensure_ascii=False, separators=(",", ":"))),
                "sourceFragments": copy.deepcopy(context.get("sourceFragments", [])),
                "sourceSentenceRefs": copy.deepcopy([ref for ref in context.get("sourceSentenceRefs", [])
                                                     if ref.get("targetSentenceId") == sid])})
        _require(not filled[cursor:].strip(), f"Codex sentence coverage incomplete: {identifier}")
        _require(raw == filled or paragraph_answers, f"Codex filled cloze lacks declared answers: {identifier}")
        _require(set(by_id) == {s["id"] for s in sentences}, "Missing or extra Codex translated sentence")
        _references({**paragraph, "paperId": paper_id}, original_fragments)
    _require(set(translated_by_id) == seen_paragraphs, "Missing or extra Codex translated paragraph")
    for identifier, group in original_fragments.items():
        spans = sorted(group["spans"])
        _require(spans[0][0] == 0 and spans[-1][1] == len(group["text"])
                 and all(a[1] == b[0] for a, b in zip(spans, spans[1:])),
                 f"Codex original fragment coverage mismatch: {identifier}")
    return expected, local_answers, {"paragraphs": len(paragraphs), "sentences": len(expected),
        "alignments": sum(len(row["alignments"]) for row in expected), "blocked": 0}


def load_codex_exam_index(staging_root: Path, *, allow_partial: bool = False):
    """Return verified sentence copies and provenance; never mix legacy translations."""
    _require(type(allow_partial) is bool, "allow_partial must be a boolean development flag")
    try:
        root = Path(staging_root).resolve(strict=True)
    except OSError as exc:
        raise ValueError("Codex staging root is missing") from exc
    snapshots = []
    def read(relative):
        value, snapshot = _read_json(root / relative, root)
        snapshots.append(snapshot)
        return value, snapshot.sha256
    manifest, manifest_hash = read("index/manifest.json")
    _require(manifest.get("schema") == "codex-exam-sentence-index-manifest.v1",
             "Wrong Codex index manifest schema")
    scope = manifest.get("scope")
    _require(scope in {"full", "partial"} and (scope == "full" or allow_partial),
             "Codex production input must be full; partial requires explicit development mode")
    _require(manifest.get("semanticReviewStatus") == "approved", "Codex index requires approved semantic reviews")
    rows = _rows(manifest.get("papers"), "manifest papers")
    _require(bool(rows), "Empty Codex index manifest")
    ids = [row.get("paperId") for row in rows]
    _require(all(isinstance(pid, str) and pid in _PAPER_IDS for pid in ids) and len(set(ids)) == len(ids),
             "Invalid or duplicate Codex manifest paper")
    _require(scope != "full" or set(ids) == _PAPER_IDS, "Full Codex index must cover exactly all 44 papers")
    for row in rows:
        _counts(row, _COUNT_FIELDS, "paper")
        _require(row.get("indexFile") == row["paperId"].split(":")[1] + ".json",
                 "Invalid Codex index file path")
        _require(row.get("semanticReviewStatus") == "approved" and row.get("reviewHash"),
                 "Every Codex paper requires an approved review")
    totals = {"papers": len(rows), **{key: sum(row[key] for row in rows) for key in _COUNT_FIELDS}}
    _require(isinstance(manifest.get("totals"), dict), "Missing Codex index totals")
    _counts(manifest["totals"], ("papers", *_COUNT_FIELDS), "manifest totals")
    _require(manifest["totals"] == totals, "Codex index manifest totals mismatch")
    inventory, inventory_hash = read("manifest.json")
    _bound(inventory_hash, manifest.get("inputManifestHash"), "input manifest")
    _require(inventory.get("schema") == "codex-exam-translation-manifest.v1", "Wrong Codex input manifest schema")
    inventory_rows = _rows(inventory.get("papers"), "input inventory")
    inventory_ids = [row.get("paperId") for row in inventory_rows]
    _require(all(isinstance(pid, str) and pid in _PAPER_IDS for pid in inventory_ids)
             and len(inventory_ids) == len(set(inventory_ids)) == 44, "Codex input inventory must cover all 44 papers")
    for row in inventory_rows:
        _counts(row, _INPUT_COUNTS, "input inventory")
        _require(row.get("file") == "inputs/" + row["paperId"].split(":")[1] + ".json",
                 "Invalid Codex input inventory file path")
    expected_totals = {key: sum(row[key] for row in inventory_rows) for key in _INPUT_COUNTS}
    _require(isinstance(inventory.get("totals"), dict), "Missing Codex input inventory totals")
    _counts(inventory["totals"], _INPUT_COUNTS, "input inventory totals")
    _require(inventory["totals"] == expected_totals, "Codex input inventory totals mismatch")
    inventory_by_id = {row["paperId"]: row for row in inventory_rows}
    sentences, seen = [], set()
    for row in sorted(rows, key=lambda r: r["paperId"], reverse=True):
        name = row["paperId"].split(":")[1]
        source, input_hash = read(f"inputs/{name}.json")
        translated, translation_hash = read(f"translations/{name}.json")
        review, review_hash = read(f"reviews/{name}.json")
        index, index_hash = read(f"index/{name}.json")
        for actual, field in ((input_hash, "inputHash"), (translation_hash, "translationHash"),
                              (review_hash, "reviewHash"), (index_hash, "indexHash")):
            _bound(actual, row.get(field), field)
        entry = inventory_by_id[row["paperId"]]
        _bound(input_hash, entry.get("sha256"), "input inventory")
        _require(review.get("schema") == "codex-exam-translation-review.v1" and review.get("paperId") == row["paperId"]
                 and review.get("approved") is True and review.get("inputHash") == input_hash
                 and review.get("translationHash") == translation_hash, f"Unapproved or stale Codex review: {name}")
        _require(source.get("paperId") == row["paperId"], "Codex input paper identity mismatch")
        expected, answers, counts = _expected_sentences(source, translated)
        method = review.get("method")
        def described(part):
            return ((isinstance(part, str) and bool(part.strip())) or
                    (isinstance(part, list) and bool(part) and
                     all(isinstance(text, str) and text.strip() for text in part)))
        _require(described(method) or
                 (isinstance(method, dict) and bool(method) and
                  all(isinstance(key, str) and key.strip() and described(part)
                      for key, part in method.items())),
                 f"Codex review must describe its independent method: {name}")
        _require(review.get("issues") == [] and
                 type(review.get("reviewedSentences")) is int and
                 review["reviewedSentences"] == counts["sentences"] and
                 type(review.get("reviewedAlignments")) is int and
                 review["reviewedAlignments"] == counts["alignments"],
                 f"Codex review must cover every sentence/alignment with no unresolved issues: {name}")
        _require(all(row[key] == counts[key] for key in _COUNT_FIELDS)
                 and all(entry[key] == counts[key] for key in ("paragraphs", "sentences", "blocked"))
                 and entry["sourceParagraphs"] == counts["paragraphs"], "Codex per-paper counts mismatch")
        _require(index == {"schema": "codex-exam-sentence-index.v1", "paperId": row["paperId"], "sentences": expected},
                 f"Codex index sentences are not bound to reviewed source/translation: {name}")
        for sentence in expected:
            _require(sentence["id"] not in seen, "Duplicate Codex sentence across papers")
            seen.add(sentence["id"])
            sentences.append({**sentence, "cloze_answers": answers[sentence["id"]],
                "translation_alignment": {"schema": "codex-sentence-alignment.v1",
                    "englishHash": sentence["englishHash"], "translationHash": sentence["translationHash"],
                    "alignments": copy.deepcopy(sentence["alignments"])}})
    _require(all(snapshot.unchanged() for snapshot in snapshots), "Codex source changed during index load")
    return sentences, {"schema": manifest["schema"], "scope": scope,
        "semantic_review_status": "approved", "papers": totals["papers"],
        **{key: totals[key] for key in _COUNT_FIELDS}, "manifest_sha256": manifest_hash,
        "input_manifest_sha256": inventory_hash, "database_modified": False,
        "source_files": {str(snapshot.path.relative_to(root)): snapshot.sha256 for snapshot in snapshots}}
