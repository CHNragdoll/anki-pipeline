"""Reconcile original cigen DOM and controls after a disposable APKG update.

Only source-audited srcdoc, PNG bytes, scoped font/layout CSS and exact display
bridges are accepted. Never opens the GUI, an Anki2 profile, or sync; only the
verification JSON and answer HTML survive cleanup.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import html
from html.parser import HTMLParser
import inspect
import json
from pathlib import Path
import sqlite3
import re
import sys
import tempfile
import zipfile

import genanki
from lxml import html as dom

from verify_anki_import import (
    DEFAULT_ANKI_PACKAGES, FIELD_NAMES, OUTPUT, ROOT, file_sha256,
    package_media_hashes, project_path, require, verify_imported_media, write_report,
)

SAMPLES = ("console", "ambition", "polish")
SCHEDULE_FIELDS = (
    "type", "queue", "ivl", "due", "factor", "reps", "lapses", "left",
    "odue", "odid", "flags",
)
ROOT_STYLE = "margin:.55rem 0 0;min-width:0"
FRAME_STYLE = "display:block;width:100%;min-width:0;height:1px;border:0;overflow:hidden;font:inherit;color:inherit"
FRAME_SANDBOX = "allow-scripts allow-top-navigation-by-user-activation allow-top-navigation-to-custom-protocols"

# These four compatibility characters are the only observed native canonical
# substitutions. Bind the original whole document, source identity, positions
# and occurrence counts rather than accepting Unicode normalization generally.
NATIVE_SOURCE_CHARACTER_CONVERSIONS = {
    76074: {
        "headword": "subjective",
        "source_html_sha256": "c80e859c1f4643f2c02b23dcb375472905838ccea12081268e8e694d274e7098",
        "original_viewer_document_sha256": "683f79f9f4e2a616e5908cedee79c8b0d7c8a161a12b82591a435ebc64789e71",
        "changes": ((16090, "\uf9ba", "\u4e86"), (16102, "\uf941", "\u8ad6")),
    },
    40426: {
        "headword": "insulate",
        "source_html_sha256": "28b881db0aed4831ebaf5e888bcf0322d4460862922ccd5e7ce0550ccad36518",
        "original_viewer_document_sha256": "1ac883a2c7e13d8097abb2a301a88b6edfc316fa68da65201e7a35de6d56f499",
        "changes": ((12722, "\uf92e", "\u51b7"), (12728, "\uf9be", "\u6599")),
    },
}


def css_declarations(content: str) -> dict[str, str]:
    result = {}
    for declaration in filter(str.strip, content.split(";")):
        require(":" in declaration, "invalid etymology CSS declaration")
        name, value = (part.strip() for part in declaration.split(":", 1))
        require(name not in result, "duplicate etymology CSS declaration")
        result[name] = value
    return result


def verify_etymology_css_delta(old: str, new: str) -> None:
    require(new.startswith(old), "new model CSS modifies previously installed styles")
    delta = re.sub(r"/\*.*?\*/", "", new[len(old):], flags=re.S)
    approved = {
        ".etymology-section": css_declarations(ROOT_STYLE),
        ".etymology-source-frame": css_declarations(FRAME_STYLE.replace("height:1px;", "")),
    }
    seen = set()
    end = 0
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", delta):
        require(not delta[end:rule.start()].strip(), "unexpected CSS outside etymology rules")
        selector = rule[1].strip()
        require(selector in approved and selector not in seen,
                f"CSS change escapes the exact etymology frame contract: {selector}")
        require(css_declarations(rule[2]) == approved[selector], "unexpected outer frame CSS declaration")
        seen.add(selector)
        end = rule.end()
    require(not delta[end:].strip(), "unexpected trailing etymology CSS")
    require(seen == set(approved), "missing etymology frame CSS rules")


class Components(HTMLParser):
    """Locate literal markup without matching selector names in CSS or scripts."""

    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.content = content
        self.lines = [0]
        for line in content.split("\n")[:-1]:
            self.lines.append(self.lines[-1] + len(line) + 1)
        self.markers: dict[str, list[int]] = {}
        self.roots: list[tuple[int, int]] = []
        self.root_attributes: list[dict] = []
        self.entries: list[dict] = []
        self.frames: list[dict] = []
        self.parent_scripts: list[str] = []
        self._parent_script: list[str] | None = None
        self._root_start: int | None = None
        self._section_depth = 0
        self.feed(content)
        self.close()
        require(self._root_start is None, "unclosed root section")

    def character_index(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        for marker in classes & {
            "exam-frequency", "etymology-section", "frequency-definition-title",
            "dictionary-definition",
        }:
            self.markers.setdefault(marker, []).append(self.character_index())
        if tag == "section" and "etymology-section" in classes:
            require(self._root_start is None, "nested root section")
            self._root_start = self.character_index()
            self._section_depth = 0
            self.root_attributes.append(attributes)
        if self._root_start is not None:
            if tag == "section":
                self._section_depth += 1
            if tag == "section":
                require(attributes == {"class": "etymology-section", "aria-label": "词根词缀与词源",
                        "data-schema": "cigen-etymology.v1", "data-source": "cigen",
                        "data-renderer": "cigen-original-viewer.v1", "style": ROOT_STYLE},
                        "root section differs from the exact original-viewer host contract")
            elif tag == "div":
                require(classes == {"etymology-entry"} and set(attributes)
                        == {"class", "data-entry-id", "data-headword", "data-html-sha256"},
                        "unapproved root entry element or attribute")
                self.entries.append({
                    "id": attributes.get("data-entry-id"),
                    "headword": attributes.get("data-headword"),
                    "html_sha256": attributes.get("data-html-sha256"),
                })
            elif tag == "iframe":
                require(bool(self.entries), "root frame lacks source entry identity")
                require(set(attributes) == {"class", "title", "sandbox", "scrolling", "style", "srcdoc"}
                        and classes == {"etymology-source-frame"}
                        and attributes["title"] == self.entries[-1]["headword"] + " 原词根资源"
                        and attributes["sandbox"] == FRAME_SANDBOX and attributes["scrolling"] == "no"
                        and attributes["style"] == FRAME_STYLE and isinstance(attributes["srcdoc"], str),
                        "unapproved root frame capabilities, style, URL or attribute")
                self.frames.append({"entry_id": self.entries[-1]["id"], "srcdoc": attributes["srcdoc"]})
            elif tag == "script":
                require(attributes == {"data-cigen-frame-bridge": "v1"} and self._parent_script is None,
                        "unapproved script in the root host")
                self._parent_script = []
            else:
                require(False, f"unapproved original-viewer outer element: {tag}")

    def handle_data(self, data: str) -> None:
        if self._parent_script is not None:
            self._parent_script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._parent_script is not None:
            self.parent_scripts.append("".join(self._parent_script))
            self._parent_script = None
        if tag == "section" and self._root_start is not None:
            self._section_depth -= 1
            if self._section_depth == 0:
                end = self.content.find(">", self.character_index())
                require(end >= 0, "unclosed root end tag")
                self.roots.append((self._root_start, end + 1))
                self._root_start = None


def read_package(package: Path, directory: Path, name: str) -> tuple[dict, dict]:
    database = directory / (name + ".anki2")
    with zipfile.ZipFile(package) as archive:
        database.write_bytes(archive.read("collection.anki2"))
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        rows = list(connection.execute("SELECT guid, mid, flds FROM notes"))
        notes = {guid: {"mid": mid, "fields": fields.split("\x1f")}
                 for guid, mid, fields in rows}
        require(len(notes) == len(rows) == 1960, "package notes duplicated or count differs")
        models = json.loads(connection.execute("SELECT models FROM col").fetchone()[0])
    require(all(len(note["fields"]) == len(FIELD_NAMES) for note in notes.values()),
            "package violates ten-field contract")
    return notes, models


def model_contract(model: dict) -> dict:
    return {
        "name": model["name"],
        "fields": [field["name"] for field in model["flds"]],
        "templates": [(item["name"], item["qfmt"], item["afmt"]) for item in model["tmpls"]],
        "css": model["css"],
    }


def digest_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def verify_web_definition(definition: str, page: Path, word: str) -> None:
    # Source CSS carries CRLF inside the escaped srcdoc attribute. read_text()
    # translates those line endings, falsely failing this exact field check.
    literal_page = page.read_bytes().decode("utf-8")
    require(definition in literal_page, f"web/package definition differs: {word}")


def native_source_document(content: str, record: dict) -> tuple[str, list[dict]]:
    """Derive only the four source-bound native character substitutions."""
    original = normalized_document(content)
    require(digest_text(original) == record["original_viewer_document_sha256"],
            f"native expectation source document differs: {record['headword']}")
    approved = NATIVE_SOURCE_CHARACTER_CONVERSIONS.get(record["entry_id"])
    if approved is None:
        return original, []
    require(all(record[key] == approved[key] for key in (
        "headword", "source_html_sha256", "original_viewer_document_sha256")),
        "native character conversion source identity/hash differs")
    characters = list(original)
    changes = []
    for position, source, target in approved["changes"]:
        require(len(source) == len(target) == 1 and original.count(source) == 1
                and position < len(original) and original[position] == source,
                "native character conversion position/count differs")
        characters[position] = target
        changes.append({
            "srcdoc_character_offset_after_crlf_to_lf": position,
            "source_character": source, "source_codepoint": f"U+{ord(source):04X}",
            "native_character": target, "native_codepoint": f"U+{ord(target):04X}",
            "source_occurrences": 1,
        })
    return "".join(characters), changes


def native_definition(definition: str, source_entries: list[dict]) -> str:
    """Preserve all field bytes except literal CRLF and four bound srcdoc chars."""
    expected = normalized_document(definition)
    if not source_entries:
        return expected
    parsed = Components(expected)
    require(len(parsed.frames) == len(source_entries), "native expectation source frame count differs")
    require(parsed.entries == [{"id": str(record["entry_id"]), "headword": record["headword"],
                                "html_sha256": record["source_html_sha256"]}
                               for record in source_entries],
            "native expectation source entry identities/order differ")
    for frame, record in zip(parsed.frames, source_entries, strict=True):
        require(frame["entry_id"] == str(record["entry_id"]), "native expectation source frame order differs")
        converted, changes = native_source_document(frame["srcdoc"], record)
        if changes:
            original_attribute = html.escape(frame["srcdoc"], quote=True)
            require(expected.count(original_attribute) == 1,
                    "native character conversion escaped source document is not unique/exact")
            expected = expected.replace(original_attribute, html.escape(converted, quote=True), 1)
    return expected


def verify_imported_fields(actual: list[str], packaged: list[str], word: str,
                           source_entries: list[dict] | None = None) -> bool:
    """Accept only the observed Definition CRLF and four bound source changes."""
    require(len(actual) == len(packaged) == len(FIELD_NAMES), "imported ten-field count differs")
    definition_index = FIELD_NAMES.index("Definition")
    definition = native_definition(packaged[definition_index], source_entries or [])
    for index, (value, expected) in enumerate(zip(actual, packaged, strict=True)):
        require(value == (definition if index == definition_index else expected),
                f"actual imported field differs beyond explicit native conversions: {word}/{FIELD_NAMES[index]}")
    return definition != packaged[definition_index]


def normalized_document(content: str) -> str:
    return content.replace("\r\n", "\n")


def verify_original_document(content: str, record: dict, audit: dict,
                             *, native_original: str | None = None) -> None:
    """Accept the complete audited document, including its exact resource bytes."""
    content = normalized_document(content)
    if native_original is None:
        require(digest_text(content) == record["original_viewer_document_sha256"],
                f"srcdoc differs from complete original source audit: {record['headword']}")
    else:
        expected, _ = native_source_document(native_original, record)
        require(content == expected,
                f"native srcdoc differs beyond explicit source-bound conversions: {record['headword']}")
    tree = dom.fromstring(content)
    styles = tree.xpath("//style")
    scripts = tree.xpath("//script")
    require(len(styles) == 3 and all(not node.attrib for node in styles), "unapproved srcdoc stylesheets")
    require([digest_text(node.text or "") for node in styles] == [
        audit["entry_page_css_sha256"], audit["original_resource_css_text_sha256"], audit["card_layout_css_sha256"]],
        "source stylesheet or approved card layout override differs")
    require(len(scripts) == 3 and all(not node.attrib for node in scripts), "unapproved srcdoc display script")
    require([digest_text(node.text or "") for node in scripts] == [
        audit["asset_bridge_script_sha256"], audit["original_viewer_js_sha256"], audit["resize_script_sha256"]],
        "audited offline asset, original entry control or resize script differs")
    require(not tree.xpath("//link|//iframe|//object|//embed|//audio|//video|//*[@onload]|//*[@onclick]"),
            "external or unaudited executable resource in original document")
    source = tree.xpath('//body/div[@class="etymology"]')
    require(len(source) == 1, "isolated original entry root missing or duplicated")
    images = source[0].xpath('.//img')
    require(len(images) == record["source_items"].get("img", 0), "original image count differs")
    for node in images:
        value = node.get("src", "")
        require(value.startswith("data:image/png;base64,") and "#" in value, "nonoriginal image URL")
        encoded, name = value.split(",", 1)[1].rsplit("#", 1)
        require(name.endswith(".png") and name in audit["original_resources_sha256"], "unknown source image")
        raw = base64.b64decode(encoded, validate=True)
        require(hashlib.sha256(raw).hexdigest() == audit["original_resources_sha256"][name],
                "source PNG bytes differ")
    for node in source[0].iter():
        require(not any(name.lower().startswith("on") or name == "style" for name in node.attrib),
                "unaudited executable/style attribute in original entry")
        if node.get("href") is not None:
            require(node.tag == "a" and node.get("href", "").startswith("eudic://x-callback-url/searchword?word=")
                    and node.get("target") == "_top", "non-Eudic original dictionary link")
    require("eures://" not in content and "/api/" not in content and "localhost" not in content,
            "original document depends on the source server")


def write_answer_html(path: Path, answers: list[dict], binding: dict) -> None:
    frames = []
    for sample in answers:
        document = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<style>' + sample["css"] + '</style></head><body class="card">'
                    + sample["answer"] + '</body></html>')
        frames.append('<section><h2>' + html.escape(sample["word"]) + '</h2>'
                      '<iframe title="' + html.escape(sample["word"], quote=True)
                      + ' actual imported answer" srcdoc="'
                      + html.escape(document, quote=True) + '"></iframe></section>')
    content = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>词根卡包：实际默认导入答案</title><style>'
               'body{margin:1.5rem;font:15px/1.6 system-ui;color:#24324b;background:#f5f7fa}'
               'main{max-width:1000px;margin:auto}iframe{width:100%;height:1100px;'
               'border:1px solid #dce4ef;background:white}code{overflow-wrap:anywhere}'
               '</style></head><body><main><h1>临时 Anki 默认导入后的答案</h1>'
               '<p>由实际 Anki backend 的 card.answer() 提取；尚未做 Anki GUI 显示验收。</p>'
               '<p>APKG SHA256：<code>' + binding["package_sha256"] + '</code><br>'
               '网页版本：<code>' + binding["web_digest"] + '</code></p>'
               + ''.join(frames) + '</main></body></html>')
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-package", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--web-digest", required=True)
    parser.add_argument("--adapter-report", default="output/etymology-adapter-verification.json")
    parser.add_argument("--backend-report", default="output/etymology-anki-import-verification.json")
    parser.add_argument("--full-source-report", default="output/etymology-original-viewer-verification.json")
    parser.add_argument("--report", default="output/etymology-import-content-verification.json")
    parser.add_argument("--answer-html", default="output/etymology-imported-answer.html")
    parser.add_argument("--anki-packages", default=str(DEFAULT_ANKI_PACKAGES))
    args = parser.parse_args()
    require(len(args.web_digest) == 64 and all(char in "0123456789abcdef" for char in args.web_digest),
            "web digest must be a SHA256 string")
    old_package, package = project_path(args.old_package), project_path(args.package)
    adapter_path, backend_path = project_path(args.adapter_report), project_path(args.backend_report)
    full_source_path = project_path(args.full_source_report)
    report_path, answer_path = project_path(args.report), project_path(args.answer_html)
    require(report_path.is_relative_to(OUTPUT) and report_path.suffix == ".json", "report must be output JSON")
    require(answer_path.is_relative_to(OUTPUT) and answer_path.suffix == ".html", "answer must be output HTML")
    require(old_package != package, "old and new package paths must differ")
    full_source = json.loads(full_source_path.read_text(encoding="utf-8"))
    require(full_source["status"] == "PASS"
            and full_source["schema"] == "etymology-original-viewer-verification.v1",
            "original source DOM/viewer audit failed")
    require(full_source["source_items"]["source_entries"] == 1951
            and full_source["coverage"]["cards"] == 1960
            and all(full_source["checks"].values()), "original source audit coverage/checks incomplete")
    version = OUTPUT / "web-preview" / args.web_digest
    manifest_path, catalog_path = version / "manifest.json", version / "catalog.json"
    tracked = (old_package, package, adapter_path, backend_path, manifest_path,
               catalog_path, ROOT / "anki_pipeline/templates/countdown.js", Path(__file__).resolve(), full_source_path)
    source_root = (ROOT.parent / "dictionary-unpacked/cigen-en-new").resolve(strict=True)
    for name in full_source["source_file_sha256_after"]:
        path = Path(name).resolve(strict=True)
        require(path.is_relative_to(source_root) or path == ROOT / "data/anki.sqlite3",
                "source audit path escapes approved dictionary/card inputs")
        tracked += (path,)
    for name in full_source["implementation_sha256"]:
        require(name in {"anki_pipeline/etymology.py", "anki_pipeline/templates/style.css",
                         "tests/test_etymology.py", "tests/test_etymology_packaging.py"},
                "unapproved source audit implementation path")
        tracked += (ROOT / name,)
    before = {str(path): file_sha256(path) for path in tracked}
    package_digest, old_digest = before[str(package)], before[str(old_package)]
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    require(json.loads(full_source_path.read_text(encoding="utf-8")) == full_source,
            "original source audit changed while binding inputs")
    backend = json.loads(backend_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    require(adapter["ok"] and adapter["schema"] == "etymology-adapter-verification.v1", "adapter audit failed")
    require(all(before[str(ROOT / name)] == value for name, value in full_source["implementation_sha256"].items()),
            "original source audit belongs to a different renderer or styles")
    require(all(before[name] == value for name, value in full_source["source_file_sha256_after"].items()),
            "original source audit belongs to different dictionary/card/resource inputs")
    sys.path.insert(0, str(ROOT))
    from anki_pipeline.packaging import _etymology_markup
    require(digest_text(inspect.getsource(_etymology_markup)) == full_source["etymology_markup_function_sha256"],
            "original source audit markup function has changed")
    require(backend["package_sha256"] == package_digest and backend["old_package_sha256"] == old_digest,
            "backend report is not for the current packages")
    require(backend.get("web_digest") == args.web_digest, "backend report web binding differs")
    require(backend["all_packaged_media_hashes_match_imported"] and backend["sample_review_schedule_preserved"],
            "backend audit has not verified media and scheduling")
    require(manifest["input_digest"] == args.web_digest, "web manifest digest differs")
    require(manifest["files"]["catalog.json"]["sha256"] == before[str(catalog_path)], "catalog hash differs")
    reconciliation = {row["card_id"]: row for row in adapter["entry_reconciliation"]}
    full_reconciliation = {}
    for row in full_source["entry_reconciliation"]:
        full_reconciliation.setdefault(row["card_id"], []).append(row)
    entries = catalog["cards"]
    require(len(reconciliation) == len(entries) == 1960, "adapter/catalog card count differs")
    require(set(reconciliation) == {entry["id"] for entry in entries}, "adapter/catalog card identities differ")
    roots_present, missing, samples, normalized_definition_words = [], [], [], []
    native_character_documents = []
    with tempfile.TemporaryDirectory(prefix="etymology-import-verify-", dir=OUTPUT) as folder:
        directory = Path(folder)
        old, old_models = read_package(old_package, directory, "old")
        expected, new_models = read_package(package, directory, "new")
        require(old.keys() == expected.keys(), "package note GUIDs changed")
        require(old_models.keys() == new_models.keys(), "package note type IDs changed")
        require(all(model_contract(model)["fields"] == list(FIELD_NAMES) for model in old_models.values()),
                "package note types violate ten-field names/order")
        for key in old_models:
            old_contract, new_contract = model_contract(old_models[key]), model_contract(new_models[key])
            require({name: value for name, value in old_contract.items() if name != "css"}
                    == {name: value for name, value in new_contract.items() if name != "css"},
                    "templates or ten-field model changed")
            verify_etymology_css_delta(old_contract["css"], new_contract["css"])
        countdown = '<script>' + tracked[6].read_text(encoding="utf-8") + '</script>'
        by_guid = {}
        for entry in entries:
            row = reconciliation[entry["id"]]
            require(row["word"] == entry["word"], "adapter/catalog word differs")
            guid = genanki.guid_for("anki-rebuild-card-v1", entry["id"])
            require(guid in expected and guid not in by_guid, "catalog GUID missing or duplicated")
            by_guid[guid] = row
            fields, previous = expected[guid]["fields"], old[guid]["fields"]
            expected_word = html.escape(row["word"].strip(), quote=True).replace("\n", "<br>")
            require(fields[0] == expected_word, f"package/adapter word differs: {row['word']}")
            require(all(fields[index] == previous[index] for index in range(10) if index != 2),
                    f"unrelated field changed: {row['word']}")
            require(fields[8].endswith(countdown), f"countdown helper differs: {row['word']}")
            parsed = Components(fields[2])
            has_content = row["has_content"]
            require(len(parsed.roots) == int(has_content), f"source/root coverage differs: {row['word']}")
            require(len(parsed.markers.get("exam-frequency", [])) == 1
                    and len(parsed.markers.get("frequency-definition-title", [])) == 1,
                    f"frequency/meaning heading missing or duplicated: {row['word']}")
            if has_content:
                start, end = parsed.roots[0]
                require(fields[2][:start] + fields[2][end:] == previous[2],
                        f"root insertion changed frequency or dictionary definition: {row['word']}")
                require(parsed.markers["exam-frequency"][0]
                        < parsed.markers["frequency-definition-title"][0]
                        < parsed.markers["dictionary-definition"][0] < start < end == len(fields[2]),
                        f"frequency/meaning/appended-original-root order differs: {row['word']}")
                require(parsed.root_attributes[0].get("data-schema") == "cigen-etymology.v1"
                        and parsed.root_attributes[0].get("data-source") == "cigen",
                        f"root source/schema marker differs: {row['word']}")
                require(parsed.entries == [{"id": str(item["id"]), "headword": item["headword"],
                                            "html_sha256": item["html_sha256"]} for item in row["entries"]],
                        f"source entry identity/order differs: {row['word']}")
                require(entry["id"] in full_reconciliation,
                        f"root card absent from full source audit: {row['word']}")
                require(parsed.entries == [{"id": str(item["entry_id"]), "headword": item["headword"],
                                            "html_sha256": item["source_html_sha256"]}
                                           for item in full_reconciliation[entry["id"]]],
                        f"full source entry identities/order differ: {row['word']}")
                require({digest_text(fields[2][start:end])}
                        == {item["rendered_root_markup_sha256"] for item in full_reconciliation[entry["id"]]},
                        f"package root text differs from complete source audit: {row['word']}")
                require(len(parsed.frames) == len(parsed.entries)
                        and len(parsed.parent_scripts) == 1
                        and digest_text(parsed.parent_scripts[0]) == full_source["parent_frame_bridge_script_sha256"],
                        f"root frame count or exact audited parent bridge differs: {row['word']}")
                for frame, original_entry in zip(parsed.frames, full_reconciliation[entry["id"]], strict=True):
                    require(frame["entry_id"] == str(original_entry["entry_id"]), "root frame entry order differs")
                    verify_original_document(frame["srcdoc"], original_entry, full_source)
                roots_present.append(row["word"])
            else:
                require(fields[2] == previous[2], f"missing root changed definition: {row['word']}")
                missing.append(row["word"])
            page = (OUTPUT / entry["previewUrl"]).resolve()
            require(page.is_relative_to(version.resolve()), "card page escapes frozen web version")
            relative = page.relative_to(version).as_posix()
            require(file_sha256(page) == manifest["files"][relative]["sha256"], "web card file hash differs")
            verify_web_definition(fields[2], page, row["word"])
        require(len(roots_present) == adapter["coverage"]["counts"]["content"] == 1951,
                "root content coverage differs from 1951")
        require(sorted(missing) == sorted(item["word"] for item in adapter["coverage"]["missing"])
                and len(missing) == 9, "missing root words differ from adapter")
        require(set(by_guid) == set(expected), "not every package note reconciled to source")
        old_media, new_media = package_media_hashes(old_package), package_media_hashes(package)
        require(len(new_media) == 6530, "new package media count differs from 6530")
        require(old_media == new_media, "etymology update changed media names or bytes")
        anki_packages = Path(args.anki_packages).expanduser().resolve(strict=True)
        require((anki_packages / "anki/_rsbridge.so").is_file(), "installed Anki backend missing")
        sys.path.insert(0, str(anki_packages))
        import anki
        from anki.collection import Collection
        from anki.import_export_pb2 import ImportAnkiPackageRequest
        require(Path(next(iter(anki.__path__))).resolve() == anki_packages / "anki", "wrong Anki module imported")
        collection = Collection(str(directory / "collection.anki2"))
        try:
            require(collection.note_count() == collection.card_count() == 0, "temporary collection not empty")
            collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(old_package)))
            note_ids, card_ids = set(collection.find_notes("")), set(collection.find_cards(""))
            require(len(note_ids) == len(card_ids) == 1960, "old package import count differs")
            guids = {nid: collection.get_note(nid).guid for nid in note_ids}
            require(set(guids.values()) == set(expected), "old import GUID set differs")
            memberships = {cid: (collection.get_card(cid).nid, collection.get_card(cid).did) for cid in card_ids}
            contracts = {int(key): model_contract(collection.models.get(int(key))) for key in old_models}
            for index, word in enumerate(SAMPLES):
                matched = [cid for cid, (nid, _) in memberships.items()
                           if collection.get_note(nid).fields[0] == word]
                require(len(matched) == 1, f"review sample missing or duplicated: {word}")
                card = collection.get_card(matched[0])
                card.type = card.queue = 2
                card.ivl, card.due, card.reps, card.factor, card.lapses = (
                    7 + index, collection.sched.today + 7 + index, 4 + index, 2350 + index, 2 + index)
                collection.update_card(card)
            schedules = {cid: tuple(getattr(collection.get_card(cid), key) for key in SCHEDULE_FIELDS)
                         for cid in card_ids}
            collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(package)))
            require(set(collection.find_notes("")) == note_ids and set(collection.find_cards("")) == card_ids,
                    "default update changed or duplicated note/card IDs")
            for nid, guid in guids.items():
                note = collection.get_note(nid)
                require(note.guid == guid and note.note_type()["id"] == expected[guid]["mid"],
                        "default update changed note GUID or model")
                word = by_guid[guid]["word"]
                source_entries = full_reconciliation.get(by_guid[guid]["card_id"], [])
                if verify_imported_fields(note.fields, expected[guid]["fields"], word, source_entries):
                    normalized_definition_words.append(word)
                imported = Components(note.fields[FIELD_NAMES.index("Definition")])
                packaged = Components(expected[guid]["fields"][FIELD_NAMES.index("Definition")])
                require(len(imported.frames) == len(source_entries), "imported original frame count differs")
                if source_entries:
                    require(len(imported.parent_scripts) == 1
                            and digest_text(imported.parent_scripts[0]) == full_source["parent_frame_bridge_script_sha256"],
                            "actual imported parent bridge differs from exact audited code")
                for frame, packaged_frame, original_entry in zip(
                        imported.frames, packaged.frames, source_entries, strict=True):
                    require(frame["entry_id"] == str(original_entry["entry_id"]), "imported original frame entry order differs")
                    verify_original_document(frame["srcdoc"], original_entry, full_source,
                                             native_original=packaged_frame["srcdoc"])
                    native_document, changes = native_source_document(packaged_frame["srcdoc"], original_entry)
                    if changes:
                        native_character_documents.append({
                            "word": word, "entry_id": original_entry["entry_id"],
                            "source_html_sha256": original_entry["source_html_sha256"],
                            "original_viewer_document_sha256": original_entry["original_viewer_document_sha256"],
                            "expected_native_document_sha256": digest_text(native_document),
                            "actual_native_document_sha256": digest_text(normalized_document(frame["srcdoc"])),
                            "changes": changes,
                        })
            retained_old_css = 0
            applied_new_css = 0
            for mid, previous in contracts.items():
                actual = model_contract(collection.models.get(mid))
                require({name: value for name, value in actual.items() if name != "css"}
                        == {name: value for name, value in previous.items() if name != "css"},
                        "default update changed installed model template/schema")
                require(actual["css"] in {previous["css"], new_models[str(mid)]["css"]},
                        "default import applied unexpected CSS")
                retained_old_css += actual["css"] == previous["css"]
                applied_new_css += actual["css"] != previous["css"]
            for cid in card_ids:
                card = collection.get_card(cid)
                require((card.nid, card.did) == memberships[cid], "default update changed card membership")
                require(tuple(getattr(card, key) for key in SCHEDULE_FIELDS) == schedules[cid],
                        f"default update changed scheduling: {cid}")
                note = collection.get_note(card.nid)
                question, answer = card.question(), card.answer()
                require(not Components(question).roots, "actual question exposes root content")
                require(note.fields[2] in answer, "actual answer does not contain exact package Definition")
                require(len(Components(answer).roots) == int(by_guid[note.guid]["has_content"]),
                        "actual answer root count differs")
                if note.fields[0] in SAMPLES:
                    samples.append({"word": note.fields[0], "note_id": card.nid, "card_id": cid,
                                    "guid": note.guid, "question_sha256": digest_text(question),
                                    "answer_sha256": digest_text(answer),
                                    "definition_sha256": digest_text(note.fields[2]),
                                    "has_root": by_guid[note.guid]["has_content"],
                                    "schedule_fields": dict(zip(SCHEDULE_FIELDS, schedules[cid])),
                                    "css": note.note_type()["css"], "answer": answer})
            verify_imported_media(Path(collection.media.dir()), new_media)
            media_check = collection.media.check()
            require(not media_check.missing and not media_check.unused, "actual imported media missing or unused")
        finally:
            collection.close()
    after = {str(path): file_sha256(path) for path in tracked}
    require(before == after, "frozen inputs changed during verification")
    require(len(normalized_definition_words) == 1951, "observed native Definition CRLF note count differs")
    require({row["entry_id"] for row in native_character_documents} == set(NATIVE_SOURCE_CHARACTER_CONVERSIONS)
            and len(native_character_documents) == 2
            and sum(len(row["changes"]) for row in native_character_documents) == 4,
            "observed native source character conversion coverage differs")
    binding = {"package_sha256": package_digest, "old_package_sha256": old_digest, "web_digest": args.web_digest}
    samples.sort(key=lambda sample: SAMPLES.index(sample["word"]))
    require([sample["word"] for sample in samples] == list(SAMPLES), "render samples incomplete")
    write_answer_html(answer_path, samples, binding)
    result = {
        "schema": "etymology-import-content-verification.v1", "status": "PASS",
        "verified_at": datetime.now(timezone.utc).isoformat(), **binding,
        "package": str(package), "old_package": str(old_package),
        "backend_report": str(backend_path), "adapter_report": str(adapter_path), "full_source_report": str(full_source_path),
        "notes": 1960, "cards": 1960, "media": len(new_media),
        "native_field_normalization": {
            "field": "Definition",
            "conversion": "literal CRLF to LF plus four explicitly source-bound CJK compatibility characters",
            "crlf_notes": len(normalized_definition_words),
            "canonical_character_notes": len(native_character_documents),
            "canonical_character_changes": sum(len(row["changes"]) for row in native_character_documents),
            "canonical_source_documents": sorted(native_character_documents, key=lambda row: row["entry_id"]),
            "sample_words": sorted(normalized_definition_words)[:10],
            "all_other_nine_fields_byte_identical_to_package": True,
            "raw_package_srcdoc_matches_original_source_audit": True,
            "native_srcdoc_matches_original_source_after_only_explicit_conversions": True,
            "native_srcdoc_source_codepoints_identical": False,
            "general_nfc_nfkc_whitespace_or_standalone_cr_normalization_allowed": False,
        },
        "checks": {
            "all_1960_imported_ten_fields_equal_package_after_only_explicit_native_definition_conversions": True,
            "all_actual_imported_srcdoc_css_assets_controls_and_bridges_equal_complete_source_audit": True,
            "all_1960_note_card_ids_guids_models_and_deck_memberships_preserved": True,
            "all_1960_card_schedules_preserved_after_three_distinct_review_samples": True,
            "package_and_installed_model_templates_ten_field_order_preserved": True,
            "package_model_css_adds_only_whitelisted_etymology_scoped_rules": True,
            "all_original_frames_outer_attributes_styles_sandbox_and_bridges_pass_exact_contract": True,
            "only_definition_changes_and_exact_root_removal_recovers_old_definition": True,
            "all_nine_other_fields_including_meta_byte_identical": True,
            "all_meta_countdown_helpers_equal_frozen_source": True,
            "all_1951_original_roots_follow_frequency_and_dictionary_definition": True,
            "all_source_entry_ids_headwords_body_hashes_and_order_match_adapter": True,
            "all_root_markup_hashes_equal_complete_source_audit_rendered_resources": True,
            "all_1951_raw_package_srcdoc_hashes_equal_complete_source_audit": True,
            "all_1951_native_srcdoc_equal_source_after_only_crlf_and_four_bound_character_conversions": True,
            "all_srcdoc_fonts_width_spacing_overrides_and_size_bridges_equal_audited_code": True,
            "opaque_sandbox_disallows_child_access_to_parent_dom": True,
            "all_1960_answers_include_exact_definition_and_questions_exclude_roots": True,
            "all_1960_frozen_web_card_hashes_and_definitions_match_package": True,
            "all_6530_media_hashes_preserved_imported_and_anki_scanned_without_missing_or_unused": True,
            "all_tracked_input_hashes_stable_before_after": True,
        },
        "root_notes": len(roots_present), "notes_without_root": len(missing),
        "default_import_model_css": {"retained_old_models": retained_old_css, "applied_new_models": applied_new_css},
        "inline_root_presentation_available_without_new_model_css": True,
        "words_without_root": sorted(missing),
        "samples": [{key: value for key, value in sample.items() if key not in {"css", "answer"}} for sample in samples],
        "answer_html": str(answer_path), "answer_html_sha256": file_sha256(answer_path),
        "input_sha256_before": before, "input_sha256_after": after,
        "collection_scope": "disposable temporary collection under project output; cleaned up",
        "anki_gui_rendering": "NOT_RUN", "anki_user_profile_import": "NOT_RUN", "anki_sync": "NOT_RUN",
    }
    write_report(report_path, result)
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"input_sha256_before", "input_sha256_after"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
