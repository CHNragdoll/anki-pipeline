"""Read-only, exact ECDICT data for dictionary fallbacks and exam tags.

This adapter supplies plain source text, not HTML. It does not choose which
existing dictionary fields to replace, follow lemmas, invent word families,
or expose frequency and star metadata. ``provenance.row`` is the logical CSV
record number, with the header numbered 1, including quoted multiline text.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import os
from pathlib import Path
import re
import unicodedata


_TAG_LABELS = {"zk": "中考", "gk": "高中", "cet4": "CET4", "cet6": "CET6",
               "ky": "考研", "toefl": "TOEFL", "ielts": "IELTS", "gre": "GRE"}
_FORMS = {"p": ("past", "过去式", {"verb"}),
          "d": ("past_participle", "过去分词", {"verb"}),
          "i": ("present_participle", "现在分词", {"verb"}),
          "3": ("third_person_singular", "第三人称单数", {"verb"}),
          "s": ("plural", "复数", {"noun"}),
          "r": ("comparative", "比较级", {"adjective", "adverb"}),
          "t": ("superlative", "最高级", {"adjective", "adverb"})}
_POS = {"n": "noun", "v": "verb", "vt": "verb", "vi": "verb",
        "adj": "adjective", "a": "adjective", "s": "adjective",
        "adv": "adverb", "r": "adverb"}


def _normalize(word):
    return unicodedata.normalize("NFKC", word).casefold()


def _headword(word):
    return word.strip().splitlines()[0].strip()


def _snapshot(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _iter_lines(stream, digest):
    """Hash the exact bytes during the single CSV read, including a UTF-8 BOM."""
    for number, raw in enumerate(stream):
        digest.update(raw)
        yield raw.decode("utf-8-sig" if number == 0 else "utf-8")


def _source_positions(row, card):
    positions = set()
    for field in ("translation", "definition"):
        for line in row[field].replace("\\n", "\n").splitlines():
            prefix = re.match(r"\s*((?:[a-z]+\.\s*(?:[&/]\s*)?)+)", line, re.IGNORECASE)
            if prefix:
                positions.update(_POS[name] for name in re.findall(r"([a-z]+)\.", prefix[1].casefold())
                                 if name in _POS)
    local = card.get("local_dictionary")
    lookup = local.get("lookup_word", _headword(card["word"])) if isinstance(local, dict) else None
    senses = local.get("senses", []) if isinstance(local, dict) else []
    if isinstance(lookup, str) and isinstance(senses, list) \
            and _normalize(lookup) == _normalize(_headword(card["word"])):
        for sense in senses:
            if not isinstance(sense, dict) or not isinstance(sense.get("pos"), str):
                continue
            label = sense["pos"].casefold().strip()
            if label in {"noun", "verb", "adjective", "adverb"}:
                positions.add(label)
            else:
                positions.update(_POS[name] for name in re.findall(r"(?<![a-z])([a-z]+)\.", label)
                                 if name in _POS)
    return positions


def _forms(exchange, positions, word, identity, row_number, warnings):
    forms = []
    for token in exchange.split("/"):
        token = token.strip()
        if not token:
            continue
        code, separator, value = token.partition(":")
        code, value = code.strip(), value.strip()
        if code in {"0", "1"}:
            continue  # Lemma metadata is not an inflection or derivation.
        if not separator or not value:
            warnings.append({**identity, "row": row_number, "type": "malformed_exchange", "token": token})
            continue
        if code not in _FORMS:
            warnings.append({**identity, "row": row_number, "type": "unknown_exchange_type", "code": code})
            continue
        kind, label, required = _FORMS[code]
        if not positions & required:
            warnings.append({**identity, "row": row_number, "type": "unsupported_exchange_pos",
                             "kind": kind, "form": value, "explicit_pos": sorted(positions)})
            continue
        form = {"kind": kind, "label": label, "form": value, "source": "ecdict"}
        if form not in forms:
            forms.append(form)
    if forms and all(_normalize(form["form"]) == _normalize(word) for form in forms):
        warnings.append({**identity, "row": row_number, "type": "self_only_exchange",
                         "forms": copy.deepcopy(forms)})
        return []
    return forms


def enrich_ecdict_cards(cards, root: Path):
    """Return independent card copies plus source and per-feature coverage.

    Matching uses only each title's first line, NFKC and casefold. Duplicate
    normalized matched CSV headwords abort rather than silently merging senses.
    Explicit exchange forms require matching noun/verb/adjective/adverb evidence
    in the exact source definitions or the already matched Oxford card senses.
    """
    cards = list(cards)
    if any(not isinstance(card, dict) for card in cards):
        raise ValueError("ECDICT enrichment requires dictionary cards")
    ids = [card.get("id") for card in cards]
    if any(not isinstance(identity, str) or not identity.strip() for identity in ids) or len(set(ids)) != len(ids):
        raise ValueError("ECDICT enrichment requires unique, nonempty card IDs")
    if any(not isinstance(card.get("word"), str) or not card["word"].strip() for card in cards):
        raise ValueError("ECDICT enrichment requires a nonempty word for every card")
    root = Path(root).resolve(strict=True)
    source, license_path = root / "ecdict.csv", root / "LICENSE"
    source_before, license_before = _snapshot(source.stat()), _snapshot(license_path.stat())
    license_bytes = license_path.read_bytes()
    license_text = license_bytes.decode("utf-8")
    if not license_text.strip():
        raise ValueError("ECDICT source license is empty")
    targets = {_normalize(_headword(card["word"])) for card in cards}
    found, digest, row_count = {}, hashlib.sha256(), 0
    with source.open("rb") as stream:
        if _snapshot(os.fstat(stream.fileno())) != source_before:
            raise RuntimeError("ECDICT source changed before reading")
        reader = csv.DictReader(_iter_lines(stream, digest), strict=True)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or not {"word", "translation", "definition", "tag", "exchange"} <= set(headers):
            raise ValueError("ECDICT CSV header must include unique word, translation, definition, tag and exchange columns")
        for row_count, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()) or not row["word"].strip():
                raise ValueError(f"Malformed ECDICT CSV row {row_count + 1}")
            key = _normalize(row["word"].strip())
            if key not in targets:
                continue
            if key in found:
                raise ValueError(f"Duplicate ECDICT headword {row['word']!r} at records {found[key][0]} and {row_count + 1}")
            found[key] = (row_count + 1, row)
        if _snapshot(os.fstat(stream.fileno())) != source_before:
            raise RuntimeError("ECDICT source changed during reading")
    if _snapshot(source.stat()) != source_before or _snapshot(license_path.stat()) != license_before:
        raise RuntimeError("ECDICT source or license changed during reading")
    file_sha256 = digest.hexdigest()
    report = {"schema_version": 1, "cards": len(cards), "unique_words": len(targets),
              "source": {"file": str(source), "sha256": file_sha256, "bytes": source_before[2],
                         "row_count": row_count, "license_file": str(license_path),
                         "license_sha256": hashlib.sha256(license_bytes).hexdigest()},
              "counts": {"matches": 0, "translation": 0, "tags": 0, "forms": 0, "derived": 0},
              "missing": {"entries": [], "translation": [], "tags": [], "forms": [], "derived": []},
              "unknown_tags": [], "warnings": []}
    enriched = []
    for original in cards:
        word = _headword(original["word"])
        identity = {"id": original["id"], "word": original["word"]}
        record = found.get(_normalize(word))
        local = {"word": word, "translation": "", "forms": [], "derived": [], "tags": [], "tag_labels": [],
                 "provenance": {"file_sha256": file_sha256, "row": None, "headword": None,
                                "license_text": license_text}}
        if record is None:
            report["missing"]["entries"].append(identity)
        else:
            row_number, row = record
            local["word"] = row["word"]
            local["translation"] = row["translation"].replace("\\n", "\n")
            local["tags"] = list(dict.fromkeys(row["tag"].split()))
            local["tag_labels"] = [_TAG_LABELS[code] for code in local["tags"] if code in _TAG_LABELS]
            local["forms"] = _forms(row["exchange"], _source_positions(row, original), word,
                                    identity, row_number, report["warnings"])
            local["provenance"].update(row=row_number, headword=row["word"])
            report["counts"]["matches"] += 1
            unknown = [code for code in local["tags"] if code not in _TAG_LABELS]
            if unknown:
                report["unknown_tags"].append({**identity, "row": row_number, "tags": unknown})
        for feature, present in (("translation", local["translation"].strip()), ("tags", local["tag_labels"]),
                                 ("forms", local["forms"]), ("derived", local["derived"])):
            report["counts"][feature] += bool(present)
            if not present:
                report["missing"][feature].append(identity)
        card = copy.deepcopy(original)
        card["ecdict"] = local
        enriched.append(card)
    return enriched, report
