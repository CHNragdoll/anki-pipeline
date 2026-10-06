"""Build-time, read-only access to the user's unpacked Oxford and Webster data.

The returned card data and flat MP3 files are self-contained.  Nothing here
starts a dictionary server, contacts an API, or modifies a dictionary export.
Webster's existing parser is loaded under private module names so the two
exports' identically named ``lookup.py`` files cannot shadow one another.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
import tempfile
import types
import unicodedata
from urllib.parse import unquote


_SOURCES = {"oxford": "oald10", "webster": "mw-now"}
_POS = {"noun": "n.", "verb": "v.", "adjective": "adj.", "adverb": "adv.",
        "pronoun": "pron.", "preposition": "prep.", "conjunction": "conj.",
        "determiner": "det.", "exclamation": "exclam.", "interjection": "interj.",
        "modal verb": "modal v.", "auxiliary verb": "aux. v.", "number": "num.",
        "phrasal verb": "phr. v."}
_NON_MAIN = {"examples", "unbox", "idm-g", "id-g", "pv-g", "phrasal_verb",
             "derivs", "deriv", "verb_forms_table", "verb_form"}


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _compact(value: str) -> str:
    return " ".join(value.replace("\u200b", "").split())


class _Node:
    def __init__(self, tag="", attrs=None, parent=None):
        self.tag, self.attrs, self.parent = tag, attrs or {}, parent
        self.children = []

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def text(self):
        return "".join(child.text() if isinstance(child, _Node) else child
                       for child in self.children)


class _Tree(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
             "meta", "param", "source", "track", "wbr"}

    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.root = _Node()
        self.stack = [self.root]
        self.feed(content)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self._VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _ancestors(node):
    while node is not None:
        yield node
        node = node.parent


def _first(node, name):
    return next((child for child in node.walk() if child.has_class(name)), None)


def _matching_entries(tree, word):
    candidates = []
    for node in tree.walk():
        if not node.has_class("entry"):
            continue
        header = _first(node, "webtop")
        headword = _first(header, "headword") if header else None
        if headword is not None:
            text = _compact(headword.text())
            # Oxford prints a homograph number in a child .hm element.
            for child in headword.walk():
                if child.has_class("hm"):
                    text = text.removesuffix(_compact(child.text())).strip()
            if _normalize(text) == _normalize(word):
                candidates.append((node, header, text))
    exact = [candidate for candidate in candidates if candidate[2] == word]
    return exact or candidates


def _oxford_senses(entry, header, scope, word, *, include_idioms=False):
    pos_node = _first(header, "pos")
    position = _compact(pos_node.text()) if pos_node is not None else ""
    excluded = _NON_MAIN - ({"pv-g", "phrasal_verb"} if position == "phrasal verb" else set())
    if include_idioms:
        excluded -= {"idm-g", "id-g"}
    senses = []
    for node in scope.walk():
        ancestors = list(_ancestors(node))
        if any(set(parent.attrs.get("class", "").split()) & excluded for parent in ancestors):
            continue
        if next((parent for parent in ancestors if parent.has_class("entry")), None) is not entry:
            continue
        if node.tag != "chn" or not any(parent.tag == "deft" for parent in ancestors):
            continue
        text = _compact(node.text())
        if not text:
            continue
        item = {"pos": _POS.get(position, position), "text": text}
        phrase_block = next((parent for parent in ancestors
                             if parent.has_class("idm-g") or parent.has_class("pv-g")), None)
        if phrase_block is not None:
            phrase_node = _first(phrase_block, "idm") or _first(phrase_block, "pv")
            phrase = _compact(phrase_node.text()) if phrase_node is not None else word
            item.update(phrase=phrase, text=f"{phrase}：{text}")
        if item not in senses:
            senses.append(item)
    return senses


def _oxford_definition_scopes(tree, word):
    """A redirect is an index link, not permission to copy a root article.

    The requested spelling/case wins. Explicit header variants license their
    own entry, while variants printed inside a sense license only that sense.
    Inflections, derivatives and unrelated phrasal verbs need their own source.
    """
    # Casefold is useful for locating an index page, but does not prove that
    # polish defines Polish, or august defines August.
    matches = [item for item in _matching_entries(tree, word) if item[2] == word]
    if matches:
        return [(entry, header, entry) for entry, header, _ in matches]
    scopes = []
    for entry in tree.walk():
        if not entry.has_class("entry"):
            continue
        header = _first(entry, "webtop")
        if header is None:
            continue
        for variant in entry.walk():
            if not variant.has_class("v") or _compact(variant.text()) != word:
                continue
            parents = list(_ancestors(variant))
            if next((node for node in parents if node.has_class("entry")), None) is not entry:
                continue
            if not any(node.has_class("variants") for node in parents) \
                    or any(set(node.attrs.get("class", "").split()) & _NON_MAIN for node in parents):
                continue
            scope = entry if header in parents else next(
                (node for node in parents if node.has_class("sense")), None)
            item = (entry, header, scope)
            if scope is not None and item not in scopes:
                scopes.append(item)
    return scopes


def _oxford_definition_senses(content, word, *, include_idioms=False):
    senses = []
    for entry, header, scope in _oxford_definition_scopes(_Tree(content).root, word):
        for sense in _oxford_senses(entry, header, scope, word, include_idioms=include_idioms):
            if sense not in senses:
                senses.append(sense)
    return senses


def _reviewed_definition_corrections():
    """Load the small, source-bound ledger of independently checked repairs."""
    path = Path(__file__).with_name("definition-corrections.json")
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != "verified-definitions.v1":
        raise ValueError("Unknown reviewed definition correction schema")
    corrections = {}
    for row in document.get("rows", []):
        word = row.get("word")
        if not isinstance(word, str) or not word or word in corrections \
                or not row.get("expected_oxford_sources") or not row.get("senses"):
            raise ValueError("Reviewed definition requires unique words, sources and senses")
        corrections[word] = row
    return corrections


def _apply_reviewed_definition(local, word, corrections):
    row = corrections.get(word)
    if row is None:
        return False
    actual = {(item["entry_id"], item["headword"], item["sha256"])
              for item in local["provenance"]["oxford"] if item.get("role") != "linked_phrase"}
    expected = {(item["entry_id"], item["headword"], item["sha256"])
                for item in row["expected_oxford_sources"]}
    if actual != expected:
        raise ValueError(f"Reviewed definition source changed; recheck {word!r}")
    local["senses"] = copy.deepcopy(row["senses"])
    local["definition_source"] = "reviewed"
    local["definition_fallback"] = ""
    local["definition_source_notice"] = copy.deepcopy(row["source_notice"])
    return True


def _oxford_entry(content, word, *, include_idioms=False):
    senses, audio, phonetics = [], [], []
    for entry, header, _ in _matching_entries(_Tree(content).root, word):
        for sense in _oxford_senses(entry, header, entry, word, include_idioms=include_idioms):
            if sense not in senses:
                senses.append(sense)
        # Only the main webtop phonetics are eligible, never example recordings
        # or the verb forms table that also lives inside webtop.
        variants = {_normalize(word)}
        for group in (child for child in entry.walk() if child.has_class("variants")):
            variants.update(_normalize(_compact(child.text())) for child in group.walk() if child.has_class("v"))
        for node in header.walk():
            ancestors = list(_ancestors(node))
            if any(set(parent.attrs.get("class", "").split()) & _NON_MAIN
                   for parent in ancestors):
                continue
            phonetic_block = next((parent for parent in ancestors
                                   if parent.has_class("phons_n_am") or parent.has_class("phons_br")), None)
            if phonetic_block is None:
                continue
            block_word = phonetic_block.attrs.get("wd", word)
            if _normalize(block_word) not in variants:
                continue
            accent = "us" if phonetic_block.has_class("phons_n_am") else "uk"
            if node.has_class("phon"):
                value = _compact(node.text())
                if value and (accent, value) not in phonetics:
                    phonetics.append((accent, value))
            href = node.attrs.get("href", "")
            if node.tag == "a" and href.casefold().startswith("sound://"):
                item = {"resource_key": href[8:], "accent": accent}
                if item not in audio:
                    audio.append(item)
    return {"senses": senses, "audio": audio, "phonetics": phonetics}


def _oxford_fallback(conn, resolved, word):
    """Use explicitly linked phrase entries only when the main entry has no senses.

    Oxford sometimes gives a verb only a pronunciation/forms header and puts
    its actual definitions in linked phrasal entries. Those senses retain the
    phrase label, so they never masquerade as an unrestricted lemma meaning.
    """
    senses, provenance, phrases = [], [], []
    for row, _ in resolved:
        for sense in _oxford_definition_senses(row["html"], word, include_idioms=True):
            if sense not in senses:
                senses.append(sense)
        scopes = _oxford_definition_scopes(_Tree(row["html"]).root, word)
        # A sense-local spelling must not inherit another lemma's link list.
        for entry, _, scope in scopes:
            if scope is not entry:
                continue
            for node in entry.walk():
                if node.tag == "a" and node.attrs.get("href", "").startswith("entry://") \
                        and any(parent.has_class("phrasal_verb_links") for parent in _ancestors(node)):
                    phrase = _compact(node.text())
                    if phrase and phrase not in phrases:
                        phrases.append(phrase)
    for phrase in phrases:
        phrase_rows, _ = _resolve_entries(conn, phrase)
        for row, chain in phrase_rows:
            # Require a real spaced phrase headword, rather than its hyphen
            # alias that can redirect straight back to the empty main entry.
            if _normalize(row["headword"]) != _normalize(phrase):
                continue
            parsed = _oxford_entry(row["html"], row["headword"])
            if parsed["senses"]:
                provenance.append({"entry_id": row["id"], "headword": row["headword"],
                    "sha256": row["sha256"], "redirect_chain": chain, "role": "linked_phrase"})
            for sense in parsed["senses"]:
                if sense not in senses:
                    senses.append(sense)
    return senses, provenance


def _load_webster_parser(root):
    """Reuse the existing parser without global imports named lookup/html_tree."""
    paths = [root / "html_tree.py", root / "mw_parser.py"]
    contents = [path.read_bytes() for path in paths]
    digest = hashlib.sha256(b"\0".join(contents)).hexdigest()
    tree_name, parser_name = f"_anki_mw_tree_{digest}", f"_anki_mw_parser_{digest}"
    if parser_name in sys.modules:
        return sys.modules[parser_name], digest
    spec = importlib.util.spec_from_file_location(tree_name, paths[0])
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load the unpacked dictionary parser: {paths[0]}")
    tree = importlib.util.module_from_spec(spec)
    sys.modules[tree_name] = tree
    try:
        # Execute the bytes whose hash we recorded, even if a helper is replaced
        # concurrently. Only its one sibling import is qualified privately.
        exec(compile(contents[0], str(paths[0]), "exec"), tree.__dict__)
        source = contents[1].decode("utf-8")
        dependency = "from html_tree import "
        if source.count(dependency) != 1:
            raise ImportError("Webster parser sibling import changed; review its interface")
        parser = types.ModuleType(parser_name)
        parser.__file__ = str(paths[1])
        sys.modules[parser_name] = parser
        exec(compile(source.replace(dependency, f"from {tree_name} import ", 1),
                     str(paths[1]), "exec"), parser.__dict__)
    except BaseException:
        sys.modules.pop(tree_name, None)
        sys.modules.pop(parser_name, None)
        raise
    return parser, digest


def _find_entries(conn, word):
    rows = conn.execute("SELECT * FROM entries WHERE headword=? ORDER BY id", (word,)).fetchall()
    return rows or conn.execute("SELECT * FROM entries WHERE lookup_key=? ORDER BY id",
                                (_normalize(word),)).fetchall()


def _resolve_entries(conn, word):
    resolved, issues, seen = [], [], set()

    def visit(query, chain, visited):
        if len(chain) > 40:
            issues.append({"type": "redirect_cycle", "chain": chain + [query]})
            return
        rows = _find_entries(conn, query)
        if not rows:
            issues.append({"type": "missing_redirect_target", "target": query, "chain": chain})
        for row in rows:
            if row["id"] in visited:
                issues.append({"type": "redirect_cycle", "chain": chain + [query]})
            elif row["redirect_target"] is not None:
                visit(row["redirect_target"], chain + [query], visited | {row["id"]})
            elif row["id"] not in seen:
                seen.add(row["id"])
                resolved.append((row, chain))

    visit(word, [], set())
    return resolved, issues


def _resource(conn, key, root):
    key = unquote(key).replace("\\", "/").lstrip("/")
    if "\0" in key or ":" in key or ".." in PurePosixPath(key).parts:
        raise ValueError(f"Unsafe dictionary resource key: {key!r}")
    row = conn.execute("SELECT * FROM resources WHERE lookup_path=?",
                       (unicodedata.normalize("NFC", key).casefold(),)).fetchone()
    if row is None and ("?" in key or "#" in key):
        return _resource(conn, re.split("[?#]", key, 1)[0], root)
    if row is None:
        return None
    relative = PurePosixPath(row["path"])
    if relative.is_absolute() or ".." in relative.parts or ":" in str(relative) or "\0" in str(relative):
        raise ValueError(f"Unsafe dictionary resource path: {row['path']!r}")
    resources = (root / "resources").resolve(strict=True)
    absolute = (resources / str(relative)).resolve()
    if not absolute.is_relative_to(resources):
        raise ValueError("Dictionary resource escapes its resources directory")
    if absolute.suffix.casefold() != ".mp3" or row["extension"].casefold() != ".mp3":
        raise ValueError(f"Dictionary pronunciation is not an MP3: {row['path']}")
    if not absolute.is_file():
        return None
    data = absolute.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not data or len(data) != row["bytes"] or digest != row["sha256"]:
        raise ValueError(f"Dictionary audio integrity failed: {row['path']}")
    return {"path": absolute, "data": data, "sha256": digest, "bytes": len(data),
            "resource_key": key, "archive_key": row["archive_key"]}


def _copy_audio(resource, source, destination):
    filename = f"dict_{source}_{resource['sha256']}.mp3"
    target = destination / filename
    if target.is_symlink():
        raise ValueError(f"Dictionary media destination must not be a symlink: {target}")
    if target.exists():
        if not target.is_file() or target.read_bytes() != resource["data"]:
            raise FileExistsError(f"Existing dictionary media differs: {target}")
        return filename
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination, prefix=".dictionary-audio-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(resource["data"])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return filename


def _webster_audio(parser, resolved):
    found = []
    for row, _ in resolved:
        tree = parser.parse(row["html"])
        for header in parser.headers(tree):
            if _normalize(parser.headword(header.first("hword"))) != _normalize(row["headword"]):
                continue
            for node in header.walk():
                href = node.attrs.get("href", "")
                if node.tag == "a" and href.casefold().startswith("sound://"):
                    item = {"resource_key": href[8:], "accent": "us"}
                    if item not in found:
                        found.append(item)
    return found


def _webster_case_audio(parser, conn, word, resolved):
    """A same-spelling case record may contain the only headword recording.

    No plural or morphological root is guessed: customs must not use custom,
    nor means use mean, because that changes the word being pronounced.
    """
    audio = _webster_audio(parser, resolved)
    if audio:
        return audio, []
    existing = {row["id"] for row, _ in resolved}
    rows = conn.execute("SELECT * FROM entries WHERE lookup_key=? ORDER BY id", (_normalize(word),)).fetchall()
    extra, provenance = [], []
    for row in rows:
        if row["id"] in existing or row["redirect_target"] is not None:
            continue
        found = _webster_audio(parser, [(row, [])])
        if found:
            extra.extend(found)
            provenance.append({"entry_id": row["id"], "headword": row["headword"],
                "sha256": row["sha256"], "redirect_chain": [], "role": "case_variant_audio"})
    return extra, provenance


def _webster_spelling_audio(parser, conn, word, resolved):
    """Follow explicit British spelling references for pronunciation only.

    A spelling-only entry can lack a parts-of-speech header and any recording.
    Its main ``cxl-ref`` still identifies the canonical spelling. Parallel
    lists (honour, honourable, honourary) must map by position, never borrow
    the recording of a related word or follow a plural/root reference.
    """
    audio, provenance = [], []
    for original, _ in resolved:
        for reference in _Tree(original["html"]).root.walk():
            if not reference.has_class("cxl-ref"):
                continue
            ancestors = list(_ancestors(reference))
            if any(parent.has_class("widget") or parent.tag == "karxthsr" for parent in ancestors):
                continue
            entry = next((parent for parent in ancestors
                          if re.fullmatch(r"dictionary-entry-\d+", parent.attrs.get("id", ""))), None)
            header = _first(entry, "entry-header") if entry is not None else None
            headword = _first(header, "hword") if header is not None else None
            label = _first(reference, "cxl")
            if headword is None or label is None:
                continue
            relationship = _compact(label.text())
            if not re.fullmatch(r"(?:chiefly )?British spellings? of", relationship):
                continue
            names = [_compact(name) for name in headword.text().split(",")]
            links = [node for node in reference.walk() if node.tag == "a" and node.has_class("cxt")]
            if len(names) != len(links):
                continue
            for name, link in zip(names, links):
                if _normalize(name) != _normalize(word):
                    continue
                target = unquote(link.attrs.get("href", "").removeprefix("entry://"))
                if not target or any(char in target for char in "/:?#\0") \
                        or _normalize(target) != _normalize(_compact(link.text())):
                    continue
                targets, _ = _resolve_entries(conn, target)
                for row, chain in targets:
                    if _normalize(row["headword"]) != _normalize(target):
                        continue
                    found = _webster_audio(parser, [(row, chain)])
                    if not found:
                        continue
                    for item in found:
                        if item not in audio:
                            audio.append(item)
                    item = {"entry_id": row["id"], "headword": row["headword"],
                        "sha256": row["sha256"], "redirect_chain": chain, "role": "spelling_variant_audio",
                        "declared_variant": name, "declared_relationship": relationship,
                        "via_entry_id": original["id"], "via_sha256": original["sha256"]}
                    if item not in provenance:
                        provenance.append(item)
    return audio, provenance


def enrich_dictionary_cards(cards, dictionary_root: Path, media_dir: Path):
    """Return new cards plus an auditable coverage/media report; originals stay intact.

    Missing entries, Chinese senses, or headword recordings remain empty in
    their actual-source fields. Explicit fallback metadata names the other
    available pronunciation source or the original wordbook definition.
    Damaged media or unsafe paths abort the build rather than publishing it.
    """
    cards = list(cards)
    ids = [card.get("id") for card in cards]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Dictionary enrichment requires unique, nonempty card IDs")
    if any(not isinstance(card.get("word"), str) or not card["word"].strip() for card in cards):
        raise ValueError("Dictionary enrichment requires a nonempty word for every card")
    dictionary_root = Path(dictionary_root).resolve(strict=True)
    media_dir = Path(media_dir).resolve()
    if media_dir.is_relative_to(dictionary_root):
        raise ValueError("Dictionary media destination must be outside the original dictionary export")
    parser, parser_digest = _load_webster_parser(dictionary_root / "mw-now")
    reviewed_corrections = _reviewed_definition_corrections()
    report = {"schema_version": 1, "cards": len(cards), "unique_words": len(set(card["word"] for card in cards)),
              "sources": {}, "media": {}, "missing": {"oxford_senses": [], "oxford_audio": [],
              "webster_audio": [], "webster_entry": []}, "warnings": [],
              "fallbacks": {"audio": [], "definitions": []},
              "fallback_counts": {"audio": 0, "definitions": 0},
              "counts": {"oxford_senses": 0, "oxford_audio": 0, "webster_audio": 0,
                         "webster_forms": 0, "webster_derived": 0}}
    connections, snapshots = {}, {}
    with ExitStack() as stack:
        for source, directory in _SOURCES.items():
            root = dictionary_root / directory
            database = root / "dictionary.sqlite3"
            stat = database.stat()
            snapshots[source] = (stat.st_size, stat.st_mtime_ns)
            conn = sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
            stack.callback(conn.close)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN")
            connections[source] = conn
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            report["sources"][source] = {"database": str(database), "database_bytes": stat.st_size,
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest else None,
                "archives": [{"name": Path(item["path"]).name, "bytes": item["bytes"], "sha256": item["sha256"]}
                             for item in manifest.get("sources", [])]}
        report["sources"]["webster"]["parser_sha256"] = parser_digest
        media_dir.mkdir(parents=True, exist_ok=True)
        cache, enriched = {}, []
        for card in cards:
            display_word = card["word"].strip()
            # Historical headings include a declared US variant on line 2.
            # It is display metadata, not part of the dictionary lookup key.
            word = display_word.replace("\r", "\n").split("\n", 1)[0].strip()
            if word not in cache:
                local = {"senses": [], "forms": [], "derived": [], "audio": {"oxford": [], "webster": []},
                         "provenance": {"oxford": [], "webster": []}, "lookup_word": word}
                raw_audio, phonetics = {}, []
                for source, directory in _SOURCES.items():
                    conn = connections[source]
                    resolved, issues = _resolve_entries(conn, word)
                    report["warnings"].extend({"word": word, "source": source, **issue} for issue in issues)
                    local["provenance"][source] = [{"entry_id": row["id"], "headword": row["headword"],
                        "sha256": row["sha256"], "redirect_chain": chain} for row, chain in resolved]
                    if source == "oxford":
                        raw_audio[source] = []
                        for row, _ in resolved:
                            parsed = _oxford_entry(row["html"], row["headword"])
                            for sense in _oxford_definition_senses(row["html"], word):
                                if sense not in local["senses"]:
                                    local["senses"].append(sense)
                            raw_audio[source].extend(parsed["audio"])
                            phonetics.extend(parsed["phonetics"])
                        if not local["senses"]:
                            local["senses"], phrase_provenance = _oxford_fallback(conn, resolved, word)
                            local["provenance"][source].extend(phrase_provenance)
                    else:
                        relations = parser.relations(conn, resolved, _find_entries, _resolve_entries, _normalize)
                        local["forms"] = relations["word_forms"]
                        local["derived"] = relations["derived_words"]
                        raw_audio[source], audio_provenance = _webster_case_audio(parser, conn, word, resolved)
                        if not raw_audio[source]:
                            raw_audio[source], audio_provenance = _webster_spelling_audio(parser, conn, word, resolved)
                        local["provenance"][source].extend(audio_provenance)
                local["phonetic"] = next((value for accent, value in phonetics if accent == "us"),
                                         phonetics[0][1] if phonetics else "")
                for source, items in raw_audio.items():
                    for item in items:
                        resource = _resource(connections[source], item["resource_key"], dictionary_root / _SOURCES[source])
                        if resource is None:
                            report["warnings"].append({"type": "missing_audio_resource", "word": word,
                                "source": source, "resource_key": item["resource_key"]})
                            continue
                        filename = _copy_audio(resource, source, media_dir)
                        audio = {"filename": filename, "accent": item["accent"],
                                 "sha256": resource["sha256"], "bytes": resource["bytes"]}
                        if audio not in local["audio"][source]:
                            local["audio"][source].append(audio)
                        report["media"][filename] = {"source": source, "sha256": resource["sha256"],
                            "bytes": resource["bytes"], "archive_key": resource["archive_key"]}
                for source in local["audio"]:
                    local["audio"][source].sort(key=lambda item: item["accent"] != "us")
                cache[word] = local
            local = copy.deepcopy(cache[word])
            local["fallback_audio"] = {}
            for requested, actual in (("oxford", "webster"), ("webster", "oxford")):
                if not local["audio"][requested] and local["audio"][actual]:
                    local["fallback_audio"][requested] = actual
                    report["fallbacks"]["audio"].append({"id": card["id"], "word": display_word,
                        "requested_source": requested, "actual_source": actual})
            # An absent Oxford sense is still an Oxford lookup result. The
            # renderer can display its missing state without a third source.
            local["definition_source"] = "oxford"
            local["definition_fallback"] = ""
            if not local["senses"]:
                definition = card.get("definition", "")
                if not isinstance(definition, str):
                    raise ValueError(f"Wordbook definition must be text: {card['id']}")
                if definition.strip():
                    local["definition_source"] = "wordbook"
                    local["definition_fallback"] = definition
                    report["fallbacks"]["definitions"].append({"id": card["id"], "word": display_word,
                        "source": "wordbook"})
            if _apply_reviewed_definition(local, word, reviewed_corrections):
                report["fallbacks"]["definitions"] = [item for item in report["fallbacks"]["definitions"]
                                                       if item["id"] != card["id"]]
                report["fallbacks"]["definitions"].append({"id": card["id"], "word": display_word,
                    "source": "reviewed", "source_name": local["definition_source_notice"]["source_name"]})
            new_card = copy.deepcopy(card)
            new_card["local_dictionary"] = local
            if local["phonetic"]:
                new_card["phonetic"] = local["phonetic"]
            enriched.append(new_card)
            identity = {"id": card["id"], "word": display_word}
            for key, present in (("oxford_senses", local["senses"]), ("oxford_audio", local["audio"]["oxford"]),
                                 ("webster_audio", local["audio"]["webster"]),
                                 ("webster_entry", local["provenance"]["webster"])):
                if not present:
                    report["missing"][key].append(identity)
                elif key in report["counts"]:
                    report["counts"][key] += 1
            report["counts"]["webster_forms"] += bool(local["forms"])
            report["counts"]["webster_derived"] += bool(local["derived"])
        for source, directory in _SOURCES.items():
            stat = (dictionary_root / directory / "dictionary.sqlite3").stat()
            if (stat.st_size, stat.st_mtime_ns) != snapshots[source]:
                raise RuntimeError(f"Dictionary source changed during build: {source}")
    report["media_files"] = len(report["media"])
    report["media_bytes"] = sum(item["bytes"] for item in report["media"].values())
    report["fallback_counts"] = {key: len(items) for key, items in report["fallbacks"].items()}
    return enriched, report


def apply_ecdict_fallbacks(cards, dictionary_report):
    """Fill whole missing sections without conflating actual source coverage.

    Oxford senses and Webster morphology remain separately auditable. ECDICT
    cannot turn lemma links or guessed suffixes into derived words. The adapter
    supplies only validated explicit rows; no source cards/databases are written.
    """
    cards = copy.deepcopy(list(cards))
    report = copy.deepcopy(dictionary_report)
    fallbacks = report.setdefault("fallbacks", {})
    for kind in ("definitions", "forms", "derived"):
        fallbacks.setdefault(kind, [])
    replacements = set()
    additions = {"definitions": [], "forms": [], "derived": []}
    for card in cards:
        payload = card.get("ecdict")
        local = card.get("local_dictionary")
        if payload is None or local is None:
            continue
        if not isinstance(payload, dict) or not isinstance(local, dict):
            raise ValueError("ECDICT fallback requires structured dictionary payloads")
        identity = {"id": card["id"], "word": card["word"], "source": "ecdict"}
        translation = payload.get("translation", "")
        if not isinstance(translation, str):
            raise ValueError("ECDICT translation must be plain text")
        if not local.get("senses") and translation.strip():
            local["definition_source"] = "ecdict"
            local["definition_fallback"] = translation
            additions["definitions"].append(identity)
            replacements.add(card["id"])
        for section, record_key in (("forms", "form"), ("derived", "word")):
            original_key = "webster_" + section
            originals = local.get(original_key, local.get(section, []))
            supplement = payload.get(section, [])
            if not isinstance(originals, list) or not isinstance(supplement, list):
                raise ValueError("Dictionary morphology must be an explicit list")
            local[original_key] = copy.deepcopy(originals)
            local[section] = copy.deepcopy(originals)
            local[section + "_source"] = "webster" if originals else ""
            if not originals and supplement:
                if any(not isinstance(row, dict) or row.get("source") != "ecdict"
                       or not isinstance(row.get("label"), str)
                       or not isinstance(row.get(record_key), str) for row in supplement):
                    raise ValueError("ECDICT morphology needs explicit source-tracked rows")
                local[section] = copy.deepcopy(supplement)
                local[section + "_source"] = "ecdict"
                additions[section].append(identity)
    for kind, rows in additions.items():
        ids = {row["id"] for row in rows}
        if kind == "definitions":
            ids |= replacements
        fallbacks[kind] = [row for row in fallbacks[kind] if row["id"] not in ids] + rows
    report["fallback_counts"] = {kind: len(rows) for kind, rows in fallbacks.items()}
    counts = report.setdefault("counts", {})
    for kind, rows in additions.items():
        counts["ecdict_" + kind] = len(rows)
    for section in ("forms", "derived"):
        counts["available_" + section] = sum(bool(card.get("local_dictionary", {}).get(section))
                                            for card in cards)
    return cards, report
