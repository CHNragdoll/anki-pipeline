"""Byte-invertible lazy storage for already verified complete Anki fields.

No linguistic transformation, occurrence counting or source lookup happens here.
HTML is sliced at original offsets; each external string is content addressed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import base64
from hashlib import sha256
from html import escape, unescape
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

SCHEMA = 'anki-slim-segments.v1'
_TAG = re.compile(r'<!--[\s\S]*?-->|<(?:script|style)\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*?>[\s\S]*?</(?:script|style)\s*>|</?[A-Za-z][\w:-]*\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*?>', re.I)
_NAME = re.compile(r'<\s*(/?)\s*([\w:-]+)')
_ATTR = re.compile(r'''([^\s=/<>]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]+))?''')
_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_DETAIL = frozenset({'sf-ownership-history', 'sf-inline-history', 'sf-ownership-authority', 'sf-supplemental-lexeme'})
_INTEREST = _DETAIL | frozenset({'sf-panel','sf-example','example-card','example-text','example-translation','example-source','translation-label','translate-tag','sentence-jump','anki-final-reviewed-data','as-lazy','as-manifest','_r28','_r31','_r34','_r35','_r36'})


def digest(value: str) -> str:
    return sha256(value.encode('utf-8')).hexdigest()


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


def attributes(opening):
    match = _NAME.match(opening)
    result = {}
    for item in _ATTR.finditer(opening, match.end()):
        value = item[2]
        if value is not None and value[:1] in ('"', "'"):
            value = value[1:-1]
        result[item[1].lower()] = unescape(value or '')
    return result


@dataclass
class Node:
    tag: str
    attrs: dict
    start: int
    opened: int
    parent: 'Node | None'
    closed: int | None = None
    end: int | None = None
    children: list = field(default_factory=list)
    direct_parent: int | None = None

    @property
    def classes(self):
        return set(self.attrs.get('class','').split())


class Slices:
    """Retain only relevant nodes, but balance every actual HTML tag.

    Script/style bodies and quoted srcdoc attributes are opaque. This avoids
    constructing millions of span objects merely to locate one panel boundary.
    """
    def __init__(self, raw, interests=None):
        self.raw, self.nodes = raw, []
        interests = _INTEREST if interests is None else interests
        stack = []
        for match in _TAG.finditer(raw):
            text = match[0]
            if text.startswith('<!--'):
                continue
            opening = _NAME.match(text)
            closing, tag = bool(opening[1]), opening[2].lower()
            if closing:
                for i in range(len(stack)-1,-1,-1):
                    if stack[i][0] == tag:
                        node = stack[i][1]
                        if node:
                            node.closed, node.end = match.start(), match.end()
                        del stack[i:]
                        break
                continue
            opened = match.start() + text.find('>') + 1
            # Quoted attributes may contain >; locate the true end using the
            # scanner's complete opening tag, not the first > in srcdoc.
            if tag in ('script','style'):
                end_open = re.match(r'<[\w:-]+\b(?:"[^"]*"|\'[^\']*\'|[^\'">])*?>', text, re.I).end()
                opened = match.start() + end_open
            else:
                opened = match.end()
            attrs = attributes(raw[match.start():opened]) if ('class' in text[:opened-match.start()] or tag == 'a') else {}
            classes = set(attrs.get('class','').split())
            wanted = bool(classes & interests) or tag == 'summary' or 'data-rb-j' in attrs
            node = None
            if wanted:
                parent = next((entry[1] for entry in reversed(stack) if entry[1]), None)
                node = Node(tag, attrs, match.start(), opened, parent)
                node.direct_parent=stack[-1][2] if stack else None
                self.nodes.append(node)
                if parent:
                    parent.children.append(node)
            if tag in ('script','style'):
                if node:
                    node.closed = match.start() + text.lower().rfind('</'+tag)
                    node.end = match.end()
            elif tag in _VOID or text.rstrip().endswith('/>'):
                if node:
                    node.closed = node.end = opened
            else:
                stack.append((tag,node,match.start()))
        for node in self.nodes:
            if node.end is None:
                raise ValueError('unclosed selected HTML subtree: '+node.tag+' '+str(node.classes))


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.files, self.raw_bytes, self.references = {}, 0, 0

    def add(self, raw: str):
        pin = digest(raw)
        name = '_as_'+pin[:24]+'.js'
        self.references += 1
        if pin not in self.files:
            data = ('window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['+json.dumps(pin)+']='+compact(raw)+';').encode()
            path = self.folder/name
            if path.exists() and path.read_bytes()!=data:
                raise ValueError('content-addressed media filename collision')
            path.write_bytes(data)
            self.files[pin] = path
            self.raw_bytes += len(raw.encode())
        return {'src':name,'sha256':pin}

    def read(self, part):
        pin = part['sha256']
        path = self.files[pin]
        prefix = 'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['+json.dumps(pin)+']='
        data = path.read_text()
        if not data.startswith(prefix) or not data.endswith(';'):
            raise ValueError('invalid literal media')
        raw = json.loads(data[len(prefix):-1])
        if digest(raw)!=pin:
            raise ValueError('lazy content SHA mismatch')
        return raw


def apply(raw, edits):
    end = 0
    pieces = []
    for start, finish, replacement in sorted(edits):
        if start<end:
            raise ValueError('overlapping lossless edits')
        pieces.extend((raw[end:start],replacement));end=finish
    pieces.append(raw[end:])
    return ''.join(pieces)


def _ancestor(node, predicate):
    while node:
        if predicate(node):
            return True
        node = node.parent
    return False


def placeholder(parts, kind, total):
    tag = 'li' if kind=='examples' else 'div'
    manifest = {'schema':SCHEMA,'parts':parts,'total':total}
    return '<'+tag+' class="as-lazy" data-as-kind="'+kind+'"><script class="as-manifest" type="application/json">'+compact(manifest)+'</script></'+tag+'>'


def partition(raw, nodes, store, kind, max_items=25, max_bytes=180000):
    if not nodes:
        return raw
    left, right = nodes[0].start, nodes[-1].end
    parts=[]; begin=left;count=0
    for i,node in enumerate(nodes):
        count+=1
        finish = nodes[i+1].start if i+1<len(nodes) else right
        if count>=max_items or finish-begin>=max_bytes or i+1==len(nodes):
            part=store.add(raw[begin:finish]);part['count']=count
            parts.append(part);begin=finish;count=0
    return apply(raw,[(left,right,placeholder(parts,kind,len(nodes)))])


def details(raw, store, classes=None, layer=None):
    classes = _DETAIL if classes is None else frozenset(classes)
    tree=Slices(raw, interests=_INTEREST | classes)
    selected=[n for n in tree.nodes if n.tag=='details' and n.classes&classes and
              not _ancestor(n.parent,lambda x:x.tag=='details' and bool(x.classes&classes))]
    edits=[]
    for node in selected:
        summaries=[n for n in node.children if n.tag=='summary' and n.direct_parent==node.start]
        if len(summaries)!=1:
            raise ValueError('lazy audit detail has no unique original summary')
        left=summaries[0].end
        if node.closed-left<2048:
            continue
        part=store.add(raw[left:node.closed]);part['count']=1
        replacement = placeholder([part],'detail',1)
        if layer is not None:
            replacement = replacement.replace('class="as-lazy"', 'class="as-lazy" data-as-layer="'+escape(layer,quote=True)+'"',1)
        edits.append((left,node.closed,replacement))
    return apply(raw,edits)


def restore_layer(raw, store, layer):
    tree = Slices(raw)
    edits = []
    for node in tree.nodes:
        if 'as-lazy' not in node.classes or node.attrs.get('data-as-layer') != layer:
            continue
        manifests = [child for child in node.children if 'as-manifest' in child.classes]
        if len(manifests) != 1:
            raise ValueError('layer inverse has no unique manifest')
        manifest = json.loads(raw[manifests[0].opened:manifests[0].closed])
        if manifest.get('schema') != SCHEMA:
            raise ValueError('layer inverse schema differs')
        replacement = ''.join(store.read(part) for part in manifest['parts'])
        edits.append((node.start,node.end,replacement))
    return apply(raw, edits)


def text(raw):
    # Selected paragraphs contain text and span markup, never raw script/style.
    return unescape(_TAG.sub('', raw))


def descendants(node):
    for child in node.children:
        yield child
        yield from descendants(child)


def native_index(raw):
    tree=Slices(raw); entries=[]
    rows=[n for n in tree.nodes if n.tag=='li' and n.classes&{'example-card','_r28'} and
          not _ancestor(n.parent,lambda x:x.tag=='li')]
    for row in rows:
        children=list(descendants(row))
        def one(classes):
            items=[n for n in children if n.classes&classes and not _ancestor(n.parent,lambda x:x is not row and x.tag=='details')]
            return items[0] if len(items)==1 else None
        en,zh,source=one({'example-text','_r31'}),one({'example-translation','_r34'}),one({'example-source','_r36'})
        links=[n for n in children if 'sentence-jump' in n.classes or 'data-rb-j' in n.attrs]
        if not en or not zh or not source or not links:
            continue
        link=links[0]
        if 'data-rb-j' in link.attrs:
            f=link.attrs['data-rb-j'].split('|')
            if len(f)<6 or not all(re.fullmatch(r'[A-Za-z0-9_-]{43}',v) for v in f[3:5]):
                continue
            # The unchanged original compact decoder removes data-rb-j and
            # produces hexadecimal URL hashes before helpers are installed.
            # Use that exact resulting identity so eager rows and static rows
            # do not look like two distinct physical sources.
            hashes=[base64.urlsafe_b64decode(v+'=').hex() for v in f[3:5]]
            identity=['kaoyan:'+f[1]+':'+unquote(f[2]),*hashes]
        else:
            p=parse_qs(urlsplit(link.attrs.get('href','')).query)
            identity=[p.get(k,[''])[0] for k in ('anki-codex-sentence','anki-codex-hash','anki-codex-review')]
            if not identity[0] or not all(re.fullmatch('[a-f0-9]{64}',v) for v in identity[1:]):
                continue
        labels=[n for n in children if zh.start<n.start<n.end<zh.end and n.classes&{'translation-label','translate-tag','_r35'}]
        translation=apply(raw[zh.opened:zh.closed],[(n.start-zh.opened,n.end-zh.opened,'') for n in labels])
        entries.append({'source':text(raw[source.opened:source.closed]).strip(),
            'english':text(raw[en.opened:en.closed]),'translation':text(translation).strip(),
            'identity':json.dumps(identity,ensure_ascii=False,separators=(',',':'))})
    return entries


def transform(raw, store, kind='definition', index_part=None):
    revised=details(raw,store)
    tree=Slices(revised)
    if kind=='examples':
        # Ordinary examples are always present in the note, including mobile
        # review and Browse Preview. Storage factoring must not hide rows.
        pass
    else:
        edits=[]
        for panel in [n for n in tree.nodes if 'sf-panel' in n.classes]:
            rows=[n for n in panel.children if n.tag=='article' and 'sf-example' in n.classes and n.direct_parent==panel.start]
            if not rows:
                continue
            inner=revised[rows[0].start:rows[-1].end]
            local=[Node(n.tag,n.attrs,n.start-rows[0].start,n.opened-rows[0].start,None,n.closed-rows[0].start,n.end-rows[0].start) for n in rows]
            replacement=partition(inner,local,store,'panel')
            edits.append((rows[0].start,rows[-1].end,replacement))
        payloads=[n for n in tree.nodes if 'anki-final-reviewed-data' in n.classes]
        for payload in payloads:
            part=store.add(revised[payload.opened:payload.closed])
            attrs=' data-as-src="'+part['src']+'" data-as-sha="'+part['sha256']+'"'
            if index_part:
                attrs+=' data-as-index-src="'+index_part['src']+'" data-as-index-sha="'+index_part['sha256']+'"'
            opening=revised[payload.start:payload.opened]
            attrs+=' data-as-original-open="'+escape(opening,quote=True)+'"'
            replacement=opening[:-1]+attrs+'>{}</script>'
            edits.append((payload.start,payload.end,replacement))
        revised=apply(revised,edits)
        # These two native phone disclosures must already contain their exact
        # body HTML before any JavaScript runs. Keep the existing storage and
        # inverse rules for all other content, then restore only this scope.
        # Import locally because the strict offset helper reuses this scanner.
        from .inline_disclosures import restore_definition_disclosures
        revised=restore_definition_disclosures(revised,raw).html
    return revised


def restore(raw, store):
    tree=Slices(raw);edits=[]
    for node in tree.nodes:
        if 'as-lazy' in node.classes and not _ancestor(node.parent,lambda n:'as-lazy' in n.classes):
            manifest=[n for n in node.children if 'as-manifest' in n.classes]
            if len(manifest)!=1:
                raise ValueError('inverse lazy placeholder missing manifest')
            value=json.loads(raw[manifest[0].opened:manifest[0].closed])
            if value['schema']!=SCHEMA:
                raise ValueError('unknown inverse schema')
            edits.append((node.start,node.end,''.join(restore(store.read(part),store) for part in value['parts'])))
        elif 'anki-final-reviewed-data' in node.classes and 'data-as-src' in node.attrs:
            value=store.read({'sha256':node.attrs['data-as-sha']})
            edits.append((node.start,node.end,node.attrs['data-as-original-open']+value+'</script>'))
    return apply(raw,edits)
