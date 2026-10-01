"""Offline cigen entries, with original DOM and controls isolated per entry.

Original CSS and PNGs preserve the source tree, affixes, memory and related
words. Scoped overrides fit the card's typography and width; an audited message
bridge gives opaque sandbox documents their natural height without scrolling.
"""
from __future__ import annotations

from contextlib import closing
import base64
import copy
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys
import types
import unicodedata
from urllib.parse import quote, unquote


_FIELDS = ("etymology_tree", "root_affixes", "root_memory", "derived_words", "same_root_words", "sections")
_CLASSES = {
    "wordSection": "etymology-source-section", "sectionHead": "etymology-source-heading",
    "title": "etymology-source-title", "sectionCont": "etymology-source-content",
    "treePart": "etymology-tree-node", "treePartCon": "etymology-tree-parts",
    "part": "etymology-combination", "rootWord": "etymology-root-word",
    "affixWord": "etymology-affix-word", "add": "etymology-add",
    "rootAffixUl": "etymology-affix-list", "rootAffixLi": "etymology-affix",
    "prefix": "etymology-affix-label", "preCont": "etymology-affix-description",
    "sameRoot": "etymology-related-entry", "nameBox": "etymology-name-box",
    "name": "etymology-related-word", "sameRootInfo": "etymology-related-info",
    "sentenceInfo": "etymology-related-content", "trans": "etymology-related-translation",
    "sentence": "etymology-example", "line": "etymology-example-english",
    "exp": "etymology-example-chinese", "key": "etymology-key",
}
_BLOCKED_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "math", "template"}
_STATIC_TAGS = {"div", "span", "p", "ul", "ol", "li", "i", "b", "strong", "em", "br", "mark"}

# The original source DOM, colors, tree connectors and disclosure classes stay
# intact. These local overrides fit that resource inside the card's text flow.
_CARD_LAYOUT_CSS = '''html,body{box-sizing:border-box;width:100%;max-width:100%;min-width:0;height:auto!important;min-height:0!important;overflow:hidden!important;-webkit-text-size-adjust:100%;text-size-adjust:100%}
html{font:inherit}body{display:flow-root;margin:0;padding:0;background:transparent;font:inherit;color:inherit;overflow-wrap:anywhere}
.etymology{box-sizing:border-box;width:100%;max-width:100%;min-width:0;line-height:inherit!important}
.etymology *{box-sizing:border-box;min-width:0;max-width:100%;overflow-wrap:anywhere;white-space:normal}
.wordSection{margin:0 0 1em}.wordSection:last-child{margin-bottom:0}.sectionHead{margin-bottom:.45em}
.treePart,.treePartCon,.treePart .part,.etymologyTree ul{max-width:100%;min-width:0}
.treePart .part{flex:1}.treePart .part .rootWord,.treePart .part .affixWord{padding:.25em .5em}
.treeIcon,.treeIconDefault,.expandIcon,.sameRootInfo>.smLine,.rootAffixLi>.prefix{flex-shrink:0}
.sameRootInfo,.nameBox,.rootAffixLi{min-width:0;max-width:100%}.sentenceInfo,.preCont,.name{flex:1;min-width:0}
.sentenceInfo{padding-bottom:.8em}.sentenceInfo .trans{margin:.35em 0}
.line,.exp,.trans,.name,.preCont,.part,.sectionHead{font-size:1em;line-height:inherit!important}
.line span{display:inline}.sentenceInfo .sentence{padding:.65em}
'''

# Safari can initialize an iframe inside a hidden answer at 100% zoom while its
# card is at another page zoom. Navigate once in its first visible layout box;
# later answer flips retain the source's disclosure state and measured height.
_PARENT_FRAME_BRIDGE = '''(function(){
const key='__ankiCigenFrames';if(window[key]){window[key].refresh();return;}
const known=new WeakSet(),visible=new WeakSet();const selector='iframe.etymology-source-frame';
function prepare(frame){const section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section');if(!section||!meaning)return;const levels=[...meaning.children].find(item=>item.classList.contains('level-section'));if(levels&&(section.parentElement!==meaning||section.previousElementSibling!==levels))levels.after(section);if(section.style.marginTop!=='0.2rem'||section.style.marginBottom!=='0.65rem')section.style.margin='.2rem 0 .65rem';const sample=meaning.querySelector('.form-row')||meaning.querySelector('.primary-definition .field-content');if(sample){const text=getComputedStyle(sample);if(frame.style.fontSize!==text.fontSize)frame.style.fontSize=text.fontSize;if(frame.style.lineHeight!==text.lineHeight)frame.style.lineHeight=text.lineHeight;}}
function theme(frame){const meaning=frame.closest('.meaning-section');if(!meaning)return;const text=getComputedStyle(frame),title=meaning.querySelector('.primary-definition .field-title'),callout=meaning.querySelector('.field-callout'),tag=meaning.querySelector('.level-list li');const metrics={'--ety-text-size':text.fontSize,'--ety-text-line':text.lineHeight};if(title){const style=getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':style.fontSize,'--ety-title-line':style.lineHeight,'--ety-title-gap':style.marginBottom});}if(callout)metrics['--ety-section-space']=getComputedStyle(callout).paddingTop;if(tag){const style=getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':style.fontSize,'--ety-tag-line':style.lineHeight,'--ety-tag-padding':style.padding,'--ety-tag-gap':getComputedStyle(tag.parentElement).gap});}frame.contentWindow.postMessage({type:'cigen:theme',metrics},'*');}
function layout(frame){prepare(frame);if(!frame.contentWindow||frame.getBoundingClientRect().width<=0)return;if(!visible.has(frame)){visible.add(frame);frame.style.height='1px';frame.srcdoc=frame.getAttribute('srcdoc');return;}const style=getComputedStyle(frame);frame.contentWindow.postMessage({type:'cigen:layout',font:{fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color}},'*');theme(frame);}
const sizes=new ResizeObserver(entries=>{for(const entry of entries)layout(entry.target);});
function refresh(){for(const frame of document.querySelectorAll(selector)){if(!known.has(frame)){known.add(frame);sizes.observe(frame);frame.addEventListener('load',()=>layout(frame));}layout(frame);}}
window.addEventListener('message',event=>{const data=event.data;if(!data||data.type!=='cigen:size'||!Number.isFinite(data.height)||data.height<=0)return;const frame=[...document.querySelectorAll(selector)].find(item=>item.contentWindow===event.source);if(!frame)return;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value;});
new MutationObserver(refresh).observe(document.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','style','hidden']});
window.addEventListener('resize',refresh);window[key]={refresh};refresh();
})();'''


def _original_resource_bundle(root):
    """Keep the actual local viewer CSS, display controls and PNG bytes offline."""
    if not (root / "resources/etyma.css").is_file() or not (root / "viewer.js").is_file():
        return None  # Parser fixtures do not supply a complete viewer bundle.
    paths = [root / "resources/etyma.css", root / "viewer.js", root / "server.py"]
    with closing(sqlite3.connect((root / "dictionary.sqlite3").as_uri() + "?mode=ro", uri=True)) as conn:
        records = conn.execute("SELECT archive_key,path,extension,bytes,sha256 FROM resources ORDER BY id").fetchall()
    images, resource_hashes = {}, {}
    for name, relative, extension, size, digest in records:
        path = (root / "resources" / relative).resolve(strict=True)
        if not path.is_relative_to((root / "resources").resolve()):
            raise ValueError("Cigen resource path escapes its resource directory")
        raw = path.read_bytes()
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Cigen resource integrity failed: {name}")
        resource_hashes[name] = digest
        paths.append(path)
        if extension == ".png":
            images[name] = "data:image/png;base64," + base64.b64encode(raw).decode("ascii") + "#" + name
    if len(images) != 10:
        raise ValueError("Cigen original viewer requires its complete ten PNG resources")
    viewer = (root / "viewer.js").read_text(encoding="utf-8-sig")
    if re.search(r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|eval)\b|https?://", viewer):
        raise ValueError("Cigen viewer contains an unaudited network or execution operation")
    server = (root / "server.py").read_text(encoding="utf-8")
    style = re.search(r"if url.path == '/entry':.*?<style>\n(.*?)\n</style>", server, re.S)
    if style is None:
        raise ValueError("Cigen source entry viewer style contract changed")
    return {"schema": "cigen-original-viewer.v1", "css": (root / "resources/etyma.css").read_bytes().decode("utf-8-sig"),
            "entry_page_css": style[1], "viewer_js": viewer, "images": images,
            "resource_sha256": resource_hashes, "viewer_js_sha256": _file_hash(root / "viewer.js"),
            "server_sha256": _file_hash(root / "server.py"), "watched_paths": [str(path) for path in paths]}


class _OriginalContent(HTMLParser):
    """Preserve original markup, changing only audited resource/lookup URLs."""

    def __init__(self, content, images):
        # Decode with the same HTML text semantics as the source page, then
        # escape text on output. Re-appending entity callbacks with a semicolon
        # would alter original unterminated/unknown references such as &v.
        super().__init__(convert_charrefs=True)
        self.output, self.images, self.skip_script = [], images, False
        self.feed(content)
        self.close()

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script":
            self.skip_script = True
            return
        if tag == "link":
            if attributes.get("href") != "eures://etyma.css":
                raise ValueError("Unexpected stylesheet in original cigen entry")
            return  # The same source CSS is embedded once in the iframe head.
        if self.skip_script:
            return
        if tag not in {"div", "span", "p", "ul", "ol", "li", "i", "b", "strong", "em", "br", "font", "a", "img", "hr"}:
            raise ValueError(f"Unexpected original cigen HTML element: {tag}")
        if any(name.lower().startswith("on") or name == "style" for name in attributes):
            raise ValueError("Original cigen content contains unaudited executable/style attributes")
        raw = self.get_starttag_text()
        for name in ("src", "href", "data-src"):
            value = attributes.get(name)
            if value is None:
                continue
            if name == "data-src" and value == "eures://":
                replacement = "cigen-asset:"
            elif name == "src" and value.startswith("eures://"):
                key = unquote(value[8:])
                if key not in self.images:
                    raise ValueError(f"Unknown original cigen image: {key}")
                replacement = self.images[key]
            elif name == "href" and value.startswith("dic://"):
                replacement = "eudic://x-callback-url/searchword?word=" + quote(unquote(value[6:]), safe="")
            else:
                raise ValueError(f"External URL in original cigen entry: {value}")
            pattern = r"(\b" + name + r"\s*=\s*)(['\"])(.*?)\2"
            raw = re.sub(pattern, lambda match: match[1] + match[2] + html.escape(replacement, quote=True) + match[2], raw, count=1)
        if tag == "a":
            raw = raw[:-1] + ' target="_top">'
        self.output.append(raw)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "script":
            self.skip_script = False
        elif not self.skip_script and tag != "link":
            self.output.append('</' + tag + '>')

    def handle_data(self, data):
        if not self.skip_script:
            self.output.append(html.escape(data, quote=False))

    def handle_comment(self, data):
        if not self.skip_script:
            self.output.append('<!--' + data + '-->')


def original_viewer_document(entry, bundle):
    """Original entry DOM/CSS and original local viewer controls in one srcdoc."""
    if not isinstance(bundle, dict) or bundle.get("schema") != "cigen-original-viewer.v1":
        raise ValueError("Complete original cigen viewer resources are required")
    content = entry.get("source_html")
    if not isinstance(content, str) or hashlib.sha256(content.encode()).hexdigest() != entry.get("html_sha256"):
        raise ValueError("Original cigen entry HTML does not match its source hash")
    converted = ''.join(_OriginalContent(content, bundle["images"]).output)
    templates = Path(__file__).with_name('templates')
    card_css = (templates / 'etymology-card.css').read_text(encoding='utf-8')
    card_js = (templates / 'etymology-card.js').read_text(encoding='utf-8')
    assets = json.dumps(bundle["images"], ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    bridge = '''(function(){const assets=ASSETS;const original=Element.prototype.setAttribute;
Element.prototype.setAttribute=function(name,value){if(this.tagName==='IMG'&&name==='src'&&String(value).startsWith('cigen-asset:')){const key=String(value).slice(12);if(!Object.hasOwn(assets,key))throw new Error('Unknown cigen image');value=assets[key];}return original.call(this,name,value);};})();'''.replace("ASSETS", assets)
    resize = '''(function(){let last=0,pending=false;function resize(){if(pending)return;pending=true;Promise.resolve().then(()=>{pending=false;const height=Math.ceil(document.body.getBoundingClientRect().height)+1;if(height>0&&height!==last){last=height;window.parent.postMessage({type:'cigen:size',height},'*');}});}window.addEventListener('message',event=>{const data=event.data;if(event.source!==window.parent||!data||data.type!=='cigen:layout'||!data.font)return;const root=document.documentElement;for(const name of ['fontFamily','fontSize','lineHeight','color']){const value=data.font[name];if(typeof value==='string'&&root.style[name]!==value)root.style[name]=value;}resize();});window.addEventListener('load',resize);window.addEventListener('resize',resize);document.addEventListener('load',resize,true);new ResizeObserver(resize).observe(document.body);new MutationObserver(resize).observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true});if(document.fonts)document.fonts.ready.then(resize);resize();})();'''
    resize += "\n" + card_js
    for script in (bridge, bundle["viewer_js"], resize):
        if "</script" in script.lower():
            raise ValueError("Original viewer script contains an unsafe HTML terminator")
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'
            + html.escape(entry["headword"]) + '</title><style>'
            + bundle["entry_page_css"] + '</style><style>' + bundle["css"]
            + '</style><style>' + _CARD_LAYOUT_CSS + '\n' + card_css + '</style></head><body>' + converted + '<script>' + bridge + '</script><script>'
            + bundle["viewer_js"] + '</script><script>' + resize + '</script></body></html>')


def _static_nodes(node):
    """Convert source DOM to inert, namespaced nodes, never raw HTML/attrs."""
    if isinstance(node, str):
        return [node]
    if node.tag in _BLOCKED_TAGS or node.tag in {"img", "link", "input", "source", "audio", "video"}:
        return []
    children = [safe for child in node.children for safe in _static_nodes(child)]
    tag = "span" if node.tag == "font" else node.tag
    if tag not in _STATIC_TAGS:
        return children  # dic:// anchors retain their text, with no link action.
    classes = [_CLASSES[name] for name in node.attrs.get("class", "").split() if name in _CLASSES]
    if "key" in node.attrs.get("class", "").split():
        tag = "mark"
    if tag == "span" and node.text().strip().startswith("#"):
        classes.append("etymology-exam-tag")
    safe = {"tag": tag, "classes": classes, "children": children}
    if node.has_class("treePart"):
        level = re.search(r"\betymology_(\d+)\b", node.attrs.get("class", ""))
        safe["level"] = int(level[1]) if level else None
    return [safe]


def _resource_sections(parser, content):
    tree = parser.TreeParser(content).root
    resources = []
    for section in (node for node in tree.walk() if node.has_class("wordSection")):
        title = section.first("sectionHead") if hasattr(section, "first") else next(
            (node for node in section.walk() if node.has_class("sectionHead")), None)
        label = " ".join(title.text().split()) if title is not None else ""
        kind = next((kind for name, kind in (("etymologyTree", "tree"), ("etymasDom", "affixes"),
                    ("derivativeSec", "derived"), ("sameRootWord", "same_root")) if section.has_class(name)),
                    "memory" if label == "词根记忆" else "other")
        resources.append({"kind": kind, "title": label, "node": _static_nodes(section)[0]})
    return resources


def _canonical(text):
    """Keep case significant: polish and Polish are different headwords."""
    return unicodedata.normalize("NFKC", text)


def _normalize(text):
    """The archive index key; candidates still need canonical verification."""
    return _canonical(text).casefold()


def _headword(text):
    return text.strip().splitlines()[0].strip()


def _stamp(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_parser(root):
    """Use the unpacked fields() parser under content-addressed private names."""
    tree_path, lookup_path = root / "html_tree.py", root / "lookup.py"
    tree_bytes, lookup_bytes = tree_path.read_bytes(), lookup_path.read_bytes()
    digest = hashlib.sha256(tree_bytes + b"\0" + lookup_bytes).hexdigest()
    tree_name, lookup_name = f"_anki_cigen_tree_{digest}", f"_anki_cigen_lookup_{digest}"
    if lookup_name in sys.modules:
        return sys.modules[lookup_name], digest
    tree = types.ModuleType(tree_name)
    tree.__file__ = str(tree_path)
    lookup = types.ModuleType(lookup_name)
    lookup.__file__ = str(lookup_path)
    dependency = "from html_tree import "
    source = lookup_bytes.decode("utf-8")
    if source.count(dependency) != 1:
        raise ImportError("Etymology parser sibling import changed; review its interface")
    try:
        sys.modules[tree_name] = tree
        exec(compile(tree_bytes, str(tree_path), "exec"), tree.__dict__)
        sys.modules[lookup_name] = lookup
        exec(compile(source.replace(dependency, f"from {tree_name} import ", 1),
                     str(lookup_path), "exec"), lookup.__dict__)
        if not callable(getattr(lookup, "fields", None)):
            raise ImportError("Etymology parser must expose fields(content)")
    except BaseException:
        sys.modules.pop(tree_name, None)
        sys.modules.pop(lookup_name, None)
        raise
    return lookup, digest


def _validated_fields(parser, content):
    parsed = parser.fields(content)
    if not isinstance(parsed, dict) or any(not isinstance(parsed.get(key), list) for key in _FIELDS):
        raise ValueError("Etymology parser returned an invalid fields schema")
    for node in parsed["etymology_tree"]:
        if not isinstance(node, dict) or set(node) != {"level", "text", "parts"} \
                or not isinstance(node.get("text"), str) \
                or not isinstance(node.get("parts"), list) \
                or any(not isinstance(part, str) for part in node["parts"]) \
                or (node.get("level") is not None
                    and (type(node["level"]) is not int or node["level"] < 0)):
            raise ValueError("Etymology parser returned an invalid tree node")
    for node in parsed["root_affixes"]:
        if not isinstance(node, dict) or set(node) != {"type", "description"} \
                or not isinstance(node.get("type"), str) \
                or not isinstance(node.get("description"), str):
            raise ValueError("Etymology parser returned an invalid root/affix node")
    if any(not isinstance(text, str) for text in parsed["root_memory"]):
        raise ValueError("Etymology parser returned invalid memory text")
    for name in ("derived_words", "same_root_words"):
        if any(not isinstance(item, dict) or set(item) != {"word", "translation", "text"}
               or any(not isinstance(value, str) for value in item.values()) for item in parsed[name]):
            raise ValueError("Etymology parser returned invalid related-word fields")
    if any(not isinstance(item, dict) or set(item) != {"title", "text"}
           or any(not isinstance(value, str) for value in item.values()) for item in parsed["sections"]):
        raise ValueError("Etymology parser returned invalid section fields")
    return {**{key: copy.deepcopy(parsed[key]) for key in _FIELDS},
            "source_html": content,
            "resource_schema": "cigen-resource-sections.v1",
            "resource_sections": _resource_sections(parser, content)}


def _entry_identity(row):
    """Verify the archive index and body before using its source identity."""
    if not isinstance(row["headword"], str) or _normalize(row["headword"]) != row["lookup_key"]:
        raise ValueError(f"Etymology lookup key integrity failed: {row['id']}")
    content = row["html"].encode("utf-8")
    if len(content) != row["bytes"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
        raise ValueError(f"Etymology entry integrity failed: {row['id']}")
    return {"id": row["id"], "headword": row["headword"], "html_sha256": row["sha256"]}


def _lookup_rows(conn, query):
    """Use the original headword or its case-preserving NFKC equivalent only."""
    rows = conn.execute("SELECT * FROM entries WHERE headword=? ORDER BY id", (query,)).fetchall()
    if rows:
        return rows, "exact", {}
    candidates = conn.execute("SELECT * FROM entries WHERE lookup_key=? ORDER BY id",
                              (_normalize(query),)).fetchall()
    # A corrupted lookup key cannot turn an unrelated word into a candidate.
    identities = [_entry_identity(row) for row in candidates]
    rows = [row for row in candidates if _canonical(row["headword"]) == _canonical(query)]
    missing = {"reason": "ambiguous_case", "candidates": identities} if candidates and not rows else {}
    return rows, "normalized", missing


def _content_features(entry, query):
    names = {_normalize(query), _normalize(entry["headword"])}
    tree = any(any(_normalize(part.strip()) not in names and part.strip() for part in node["parts"])
               or (_normalize(node["text"].strip()) not in names and node["text"].strip())
               for node in entry["etymology_tree"])
    return {"tree": bool(tree),
            "affixes": any(node["description"].strip() for node in entry["root_affixes"]),
            "memory": any(text.strip() for text in entry["root_memory"]),
            "derived": bool(entry["derived_words"]), "same_root": bool(entry["same_root_words"])}


def enrich_etymology_cards(cards, root: Path):
    """Return deep card copies with cigen-etymology.v1 data and coverage.

    Exact headword entries take priority; otherwise require case-preserving
    NFKC equality within the source's lookup-key bucket. Casefold-only candidates
    are reported as ambiguous and excluded. No title variants, lemmas or fuzzy
    matches are guessed. A word label is retained as source data, not content.
    """
    cards = list(cards)
    if any(not isinstance(card, dict) for card in cards):
        raise ValueError("Etymology enrichment requires dictionary cards")
    ids = [card.get("id") for card in cards]
    if any(not isinstance(identity, str) or not identity.strip() for identity in ids) or len(set(ids)) != len(ids):
        raise ValueError("Etymology enrichment requires unique, nonempty card IDs")
    if any(not isinstance(card.get("word"), str) or not card["word"].strip() for card in cards):
        raise ValueError("Etymology enrichment requires a nonempty word for every card")
    root = Path(root).resolve(strict=True)
    database, manifest_path = root / "dictionary.sqlite3", root / "manifest.json"
    watched = [database, root / "html_tree.py", root / "lookup.py"]
    if manifest_path.is_file():
        watched.append(manifest_path)
    bundle = _original_resource_bundle(root)
    if bundle is not None:
        watched.extend(Path(path) for path in bundle["watched_paths"])
    before = {path: _stamp(path) for path in watched}
    parser, parser_hash = _load_parser(root)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    provenance = {"database": str(database), "db_sha256": _file_hash(database),
                  "database_bytes": before[database][2], "parser_sha256": parser_hash,
                  "manifest_sha256": _file_hash(manifest_path) if manifest_path.is_file() else None,
                  "archive_sha256": manifest.get("source_sha256")}
    report = {"schema": "cigen-etymology.v1", "cards": len(cards),
              "unique_words": len({_canonical(_headword(card["word"])) for card in cards}),
              "source": copy.deepcopy(provenance),
              "counts": {"found": 0, "content": 0, "tree": 0, "affixes": 0, "memory": 0},
              "related_counts": {"derived_cards": 0, "same_root_cards": 0, "derived_words": 0, "same_root_words": 0},
              "missing": [], "empty": [], "warnings": []}
    cache, enriched = {}, []
    with closing(sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        for original in cards:
            query = _headword(original["word"])
            if query not in cache:
                rows, match, missing = _lookup_rows(conn, query)
                entries = []
                for row in rows:
                    entries.append({**_entry_identity(row), "match": match,
                                    **_validated_fields(parser, row["html"])})
                features = {key: any(_content_features(entry, query)[key] for entry in entries)
                            for key in ("tree", "affixes", "memory", "derived", "same_root")}
                cache[query] = ({"schema": "cigen-etymology.v1", "query": query, "found": bool(entries),
                                 "has_content": any(features.values()), "entries": entries,
                                 "original_viewer": copy.deepcopy(bundle),
                                 "provenance": copy.deepcopy(provenance)}, features, missing)
            cached, features, missing = cache[query]
            local = copy.deepcopy(cached)
            identity = {"id": original["id"], "word": original["word"]}
            if not local["found"]:
                report["missing"].append({**identity, **copy.deepcopy(missing)})
            elif not local["has_content"]:
                report["empty"].append(identity)
            report["counts"]["found"] += local["found"]
            report["counts"]["content"] += local["has_content"]
            for key in ("tree", "affixes", "memory"):
                report["counts"][key] += features[key]
            for kind, field in (("derived", "derived_words"), ("same_root", "same_root_words")):
                report["related_counts"][kind + "_cards"] += features[kind]
                report["related_counts"][field] += sum(len(entry[field]) for entry in local["entries"])
            if any(entry["match"] == "normalized" for entry in local["entries"]):
                report["warnings"].append({**identity, "type": "normalized_headword_match",
                                           "headwords": [entry["headword"] for entry in local["entries"]]})
            card = copy.deepcopy(original)
            card["etymology"] = local
            enriched.append(card)
    if any(_stamp(path) != stamp for path, stamp in before.items()):
        raise RuntimeError("Etymology source changed during enrichment")
    return enriched, report
