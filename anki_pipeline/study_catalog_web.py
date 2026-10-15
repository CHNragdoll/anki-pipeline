"""Small, subject-neutral navigation host for the common book projection.

The complete catalog remains an export artifact. The browser boots from a compact
navigation index and opens only the selected card; card contents and media are
never copied into the navigation index or modified here.
"""
from __future__ import annotations

import gzip
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit


class _LabelText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1
        elif tag in {'br', 'p', 'div', 'li'} and not self.ignored:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.ignored = max(0, self.ignored - 1)
        elif tag in {'p', 'div', 'li'} and not self.ignored:
            self.parts.append(' ')

    def handle_data(self, value):
        if not self.ignored:
            self.parts.append(value)


def plain_label(value: str) -> str:
    """Present authored HTML as text without changing its stored source field."""
    parser = _LabelText()
    parser.feed(str(value))
    parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def navigation_index(catalog: dict, metadata: dict | None = None) -> dict:
    """Keep native card order and index only compact current display metadata.

    ``member_ids`` is an explicit retained inventory, allowing a known package
    guide to have its own entry. Without that evidence every card stays listed:
    the legacy importer calls all notes without a Word field ``guide``, which
    also includes ordinary mathematics and other non-vocabulary study content.
    A future guide role must be explicit, never guessed from a title or field.
    """
    metadata = metadata or {}
    metadata_cards = metadata.get('cards', {})
    units: list[str] = []
    positions: dict[str, int] = {}
    rows = []
    membership = metadata.get('member_ids')
    if membership is not None:
        if not isinstance(membership, list) or any(not isinstance(identity, str) for identity in membership) or len(set(membership)) != len(membership):
            raise ValueError('navigation source membership must contain unique text identities')
        membership = set(membership)
        if not membership.issubset({str(card['id']) for card in catalog['cards']}):
            raise ValueError('navigation source membership references a missing card')
    elif metadata.get('provenance', {}).get('kind') == 'sealed-source-catalog':
        membership = set(metadata_cards)
    for card in catalog['cards']:
        details = metadata_cards.get(str(card['id']), {})
        unit = details.get('deck_name') or card['unit']
        if not isinstance(unit, str):
            raise ValueError('navigation grouping path must be text')
        example_count = details.get('example_count')
        if example_count is not None and (type(example_count) is not int or example_count < 0):
            raise ValueError('navigation example count must be nonnegative or unknown')
        if unit not in positions:
            positions[unit] = len(units)
            units.append(unit)
        rows.append([str(card['id']), plain_label(card['word']),
                     plain_label(card.get('label') or card['word']),
                     positions[unit], card['url'], plain_label(details.get('summary', '')),
                     example_count,
                     membership is None or str(card['id']) in membership])
    return {'schema': 'study-navigation.v2', 'units': units, 'cards': rows,
            'totals': {'cards': sum(row[7] for row in rows), 'groups': len({row[3] for row in rows if row[7]}),
                       'examples': sum(row[6] for row in rows if row[7] and row[6] is not None),
                       'unknown_example_cards': sum(row[7] and row[6] is None for row in rows)},
            'catalog_revision': catalog.get('catalog_revision'), 'metadata_provenance': metadata.get('provenance')}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


class _ShelfBrowseLinks(HTMLParser):
    """Locate attribute values without serializing the original bookshelf DOM."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.lines = [0]
        for line in source.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.articles = []
        self.links = {}
        self.fragments = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article':
            self.articles.append(attrs.get('data-study-book'))
        if tag != 'a':
            return
        identity = self.articles[-1] if self.articles else None
        browse = bool(identity and 'browse-book' in attrs.get('class', '').split())
        fragment = attrs.get('href', '').startswith('#')
        if not browse and not fragment:
            return
        if browse and identity in self.links:
            raise ValueError('source bookshelf has duplicate browse links for a book')
        matches = list(re.finditer(r'\bhref\s*=\s*([\"\'])(.*?)\1', self.get_starttag_text(), re.I | re.S))
        if len(matches) != 1:
            raise ValueError('source bookshelf browse link needs one quoted href')
        line, column = self.getpos()
        offset = self.lines[line - 1] + column
        positions = offset + matches[0].start(2), offset + matches[0].end(2)
        if fragment:
            self.fragments.append((*positions, attrs['href']))
        if browse:
            self.links[identity] = positions

    def handle_endtag(self, tag):
        if tag == 'article' and self.articles:
            self.articles.pop()


def write_shelf(root: Path, entries: list[dict], *, source: Path, service_origin: str,
                mount_path: str | None = None) -> dict:
    """Reuse the original bookshelf, adapting browse and local fragment URLs.

    The original DOM, covers, downloads, stable study IDs and progress scripts
    remain its sole UI and data path. A separate QA origin redirects to the same
    service before the original deferred scripts read progress; no second study
    service or browser storage namespace is created.
    """
    root, source = root.resolve(), source.resolve(strict=True)
    if source == root / 'index.html':
        raise ValueError('the original bookshelf cannot be overwritten')
    origin = urlsplit(service_origin)
    if (origin.scheme not in {'http', 'https'} or not origin.netloc or
            origin.path not in {'', '/'} or origin.query or origin.fragment or
            origin.username is not None or origin.password is not None or
            any(ord(char) < 32 for char in service_origin)):
        raise ValueError('bookshelf service requires a plain HTTP origin')
    service_origin = origin.scheme + '://' + origin.netloc
    if mount_path is None:
        mount_path = '/' + root.relative_to(source.parent).as_posix().strip('/') + '/'
    mount = urlsplit(mount_path)
    if (mount.scheme or mount.netloc or mount.query or mount.fragment or
            not mount.path.startswith('/') or '\\' in unquote(mount.path) or
            '..' in Path(unquote(mount.path)).parts or any(ord(char) < 32 for char in mount_path)):
        raise ValueError('bookshelf mount must be a local absolute URL path')
    mount_path = mount.path.rstrip('/') + '/'
    original_bytes = source.read_bytes()
    original = original_bytes.decode('utf-8')
    if re.search(r'<base\b', original, re.I):
        raise ValueError('source bookshelf already declares a resource base')
    source_links = _ShelfBrowseLinks(original)
    links = source_links.links
    # A service-root base retains existing assets and downloads. Fragment-only
    # links must name this mounted page so they do not jump to the old root.
    replacements = {(start, end): html.escape(mount_path + 'index.html' + fragment, quote=True)
                    for start, end, fragment in source_links.fragments}
    identities = set()
    for entry in entries:
        identity, href = entry['study_book_id'], entry['href']
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('bookshelf stable study IDs must be unique text')
        identities.add(identity)
        if identity not in links:
            raise ValueError('book is missing from the original bookshelf configuration')
        if not isinstance(href, str):
            raise ValueError('shelf links must be relative text URLs')
        url = urlsplit(href)
        path = unquote(url.path)
        if (not path or url.scheme or url.netloc or url.query or url.fragment or
                path.startswith('/') or '\\' in path or '..' in Path(path).parts or
                any(ord(char) < 32 for char in href)):
            raise ValueError('shelf links must stay within the relative book directory')
        start, end = links[identity]
        replacements[(start, end)] = html.escape(mount_path + href, quote=True)
    page = original
    for (start, end), href in sorted(replacements.items(), reverse=True):
        page = page[:start] + href + page[end:]
    base = '<base href="' + html.escape(service_origin + '/', quote=True) + '">'
    redirect = ('<script>(function(){const target=new URL(' + _json(mount_path + 'index.html') + ',' +
                _json(service_origin) + ');if(location.origin!==target.origin){target.search=location.search;'
                'target.hash=location.hash;location.replace(target.href)}})();</script>')
    page, inserted = re.subn(r'<head(?:\s[^>]*)?>', lambda match: match[0] + base + redirect,
                             page, count=1, flags=re.I)
    if inserted != 1:
        raise ValueError('original bookshelf needs a head element')
    raw = page.encode('utf-8')
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=root, prefix='.shelf-', delete=False) as stream:
        staging = Path(stream.name)
        stream.write(raw)
    try:
        os.replace(staging, root / 'index.html')
    finally:
        staging.unlink(missing_ok=True)
    return {'schema': 'study-web-shelf.v2', 'books': len(entries), 'path': str(root / 'index.html'),
            'sha256': hashlib.sha256(raw).hexdigest(), 'source': str(source),
            'source_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'stable_study_ids': sorted(identities), 'service_origin': service_origin,
            'mount_path': mount_path, 'progress_service': '/api/study/overview',
            'original_dom_preserved_except_browse_and_local_fragment_hrefs': True,
            'local_fragment_links': len(source_links.fragments)}


class _ScriptSources(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.sources.add(attrs['src'])


def script_deferral_policy(sides: list[str], media: Path, *, audited_sha256: set[str] | None = None) -> dict:
    """Audit local script bytes before an opt-in mounting-time experiment.

    Explicit content-hash audits are required; absence of a suspicious token
    does not prove arbitrary JavaScript safe. Unknown hashes, paths and detected
    parser-time writes are excluded. The browser adapter
    retains the entire original execution mode if any classic script lacks an
    audited entry, or an inline classic/async/module script is present.
    """
    media = media.resolve(strict=True)
    sources = _ScriptSources()
    for side in sides:
        sources.feed(side)
    sources.close()
    policy = {}
    approved = audited_sha256 or set()
    parser_time = re.compile(r'\bdocument\s*(?:\.\s*(?:write(?:ln)?|open|close|currentScript)\b|\[\s*["\'](?:write(?:ln)?|open|close|currentScript)["\']\s*\])')
    for name in sorted(sources.sources):
        url = urlsplit(name)
        if url.scheme or url.netloc or url.query or url.fragment or Path(name).name != name:
            continue
        path = (media / name).resolve()
        if not path.is_relative_to(media) or not path.is_file():
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest in approved and not parser_time.search(text):
            policy[name] = digest
    return policy


# Exact bytes reviewed for full-document mounting and readyState-safe setup.
# New script versions keep their original wrapper until independently audited.
AUDITED_MOUNT_EXTERNAL_SHA256 = frozenset({
    '12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373',
    '171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57',
    '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',
    '71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5',
    '9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba',
    '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1',
    'ae91933dd0602830532df4ee6fe801a21e723e230ad62fc5e76147a7221fce57',
    'afe4431fdd5254aa0b20c322ef3385a15a8a8ed8daddb6f6782f8866114fae3c',
    'b383335a30cfb0df90c14c394b505b655f2520350b09a8dea5fab8de8592a4b7',
    'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',
    'deb2a18520702454420553b7ef1b8a4d8f0ebaa6aeb4094857211b4143abe065',
})
AUDITED_MOUNT_INLINE_SHA256 = frozenset({
    '6cea87551da1b7dfea2fbfe01a0e184b41ee991442fd9a436859648e44b47334',
    '6dc4685fe495463c00482898a011338c333907f3c2f93811529b8c0cef57c7ed',
    'e938f4c52ba27633c8617a014f2e79f29c0abce1ed62c590ad74271c07d146de',
})


class _MountScriptTag(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.attributes = {}
        self.feed(value)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.attributes = dict(attrs)


class SharedMountAudit:
    """Collect script identities during the existing side-rendering pass.

    No authored side is retained. Only audited inline bytes and distinct source
    names survive, so future exports need neither another full card scan nor a
    book-specific execution rule. Browser eligibility remains conservative.
    """
    pattern = re.compile(r'(<script\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>)(.*?)</script\s*>', re.I | re.S)

    def __init__(self):
        self.external = set()
        self.inline = {}
        self.sides = 0

    def observe(self, sides):
        for side in sides:
            self.sides += 1
            for match in self.pattern.finditer(side):
                attrs = _MountScriptTag(match[1]).attributes
                if attrs.get('src'):
                    self.external.add(attrs['src'])
                elif (attrs.get('type') or '').strip().lower() not in {'application/json', 'application/ld+json'} and match[2].strip():
                    source = match[2]
                    digest = hashlib.sha256(source.encode()).hexdigest()
                    if digest in AUDITED_MOUNT_INLINE_SHA256:
                        self.inline[digest] = source


def audited_shared_config(root: Path, audit: SharedMountAudit) -> dict:
    """Build the same opt-in host configuration for every subject and book.

    The allowlist certifies parser-time independence and readyState-compatible
    initialization, not just absence of a suspicious token. Unknown scripts,
    execution modes and wrappers are retained through the original-page path.
    """
    external = script_deferral_policy(
        ['<script src="' + html.escape(name, quote=True) + '"></script>' for name in sorted(audit.external)],
        root / 'media', audited_sha256=AUDITED_MOUNT_EXTERNAL_SHA256 | AUDITED_MOUNT_INLINE_SHA256)
    inline = write_deferred_inline_assets(root, list(audit.inline.values()), audited_sha256=AUDITED_MOUNT_INLINE_SHA256)
    return {'html': shared_frame_html(), 'policy': {'external': external, 'inline': inline}}


DEFER_SCRIPTS_RUNTIME = r'''function prepareScriptMount(source,policy){
const unchanged=reason=>({html:source,inserted:0,externalized:0,reason});
const external=policy?.external||policy||{},inline=policy?.inline||[];
if(!Object.keys(external).length&&!inline.length)return unchanged('no-audited-scripts');
const doc=new DOMParser().parseFromString(source,'text/html'),scripts=Array.from(doc.scripts);
// Conservative token alignment: raw script-like text that disagrees with the
// browser's parsed script inventory retains the complete original document.
const tags=Array.from(source.matchAll(/(<script\b(?:[^"'<>]|"[^"]*"|'[^']*')*>)([\s\S]*?)(<\/script\s*>)/gi));
if(tags.length!==scripts.length)return unchanged('ambiguous-script-markup');
const edits=[],modes=new Set();let externalized=0;
const attr=value=>String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
for(let i=0;i<scripts.length;i++){
 const script=scripts[i],type=(script.getAttribute('type')||'').trim().toLowerCase(),tag=tags[i];
 if(type==='application/json'||type==='application/ld+json')continue;
 if(type&&!['text/javascript','application/javascript','text/ecmascript','application/ecmascript'].includes(type))return unchanged('unsupported-script-type');
 if(script.hasAttribute('async')||script.hasAttribute('nomodule'))return unchanged('unordered-script');
 if(/\/\s*>$/.test(tag[1]))return unchanged('ambiguous-script-markup');
 const src=script.getAttribute('src');
 if(script.hasAttribute('src')&&!src)return unchanged('empty-script-resource');
 if(!src){
  if(!script.textContent.trim())continue;
  const rule=inline.find(item=>item.source===tag[2]&&item.source===script.textContent);
  if(!rule)return unchanged('inline-classic-script');
  modes.add(false);
  let url;try{url=new URL(rule.src,document.baseURI);if(!['http:','https:'].includes(url.protocol))return unchanged('unsafe-inline-resource')}catch(_){return unchanged('unsafe-inline-resource')}
  edits.push({start:tag.index,end:tag.index+tag[1].length+tag[2].length,value:tag[1].slice(0,-1)+' src="'+attr(url.href)+'" defer>'});
  externalized++;continue;
 }
 if(!Object.prototype.hasOwnProperty.call(external,src))return unchanged('unaudited-script');
 modes.add(script.hasAttribute('defer'));if(script.hasAttribute('defer'))continue;
 const probe=new DOMParser().parseFromString(tag[1]+'</scr'+'ipt>','text/html').scripts[0];
 if(!probe||probe.getAttribute('src')!==src||probe.getAttribute('type')!==script.getAttribute('type'))return unchanged('ambiguous-script-markup');
 edits.push({start:tag.index+tag[1].length-1,end:tag.index+tag[1].length-1,value:' defer'});
}
if(modes.size>1)return unchanged('mixed-defer-and-parser-blocking');
let html=source;for(let i=edits.length-1;i>=0;i--){const edit=edits[i];html=html.slice(0,edit.start)+edit.value+html.slice(edit.end)}
return{html,inserted:edits.length,externalized,reason:edits.length?'deferred-in-source-order':'already-deferred'};
}'''


def write_deferred_inline_assets(root: Path, sources: list[str], *, audited_sha256: set[str]) -> list[dict]:
    """Externalize only explicitly audited inline bytes, outside source media."""
    result = []
    seen = set()
    for source in sources:
        raw = source.encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        if digest not in audited_sha256:
            raise ValueError('inline script requires an explicit exact-byte audit')
        if digest in seen:
            continue
        seen.add(digest)
        name = '_study_deferred_inline_' + digest + '.js'
        path = root / name
        if path.exists() and path.read_bytes() != raw:
            raise ValueError('content-addressed inline asset differs from its digest')
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(raw)
        result.append({'source': source, 'src': name, 'sha256': digest})
    return result


SHARED_FRAME_RUNTIME = r'''(function(){'use strict';
let side=document.getElementById('study-side');const flip=document.getElementById('study-flip'),origin=new URL(document.baseURI).origin;
let current=null,answer=false,accepted=0,sequence=0,activeRecord=null,pending=null;const records=[],styles=new Map();
const clock=()=>performance.timeOrigin+performance.now(),attr=value=>String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
function recordEvent(record,detail){record.events.push(detail);if(record.events.length<=100)return;const keep=new Set(record.events.slice(0,8));for(const name of ['atomic-body-commit','first-any-animation-frame','first-visible-animation-frame','next-animation-frame','DOMContentLoaded','load','native-state','source-error','resource-error']){const first=record.events.find(row=>row.event===name);if(first)keep.add(first)}for(const status of ['ready','failed']){const first=record.events.find(row=>row.event==='native-state'&&row.nativeStates?.includes(status));if(first)keep.add(first)}const remove=record.events.findIndex(row=>!keep.has(row));record.events.splice(remove<0?8:remove,1)}
function report(){if(!current?.metricsAsset)return;let output=document.getElementById('study-render-metrics');if(!output){output=document.createElement('output');output.id='study-render-metrics';output.hidden=true;document.body.append(output)}output.textContent=JSON.stringify(records)}
function state(){parent.postMessage({type:'study-side-state',id:current.id,token:accepted,answer},origin)}
function note(detail){if(activeRecord){recordEvent(activeRecord,{at:clock(),...detail});report()}}
function fail(error){if(pending){clearTimeout(pending.timer);pending.reject(error);pending=null}flip.disabled=false;parent.postMessage({type:'study-source-error',id:current?.id,token:accepted,message:String(error.message||error)},origin)}
function preloadStyles(doc,base){return Promise.all(Array.from(doc.querySelectorAll('link[rel~="stylesheet"][href]'),link=>{const href=new URL(link.getAttribute('href'),base).href;if(styles.has(href))return styles.get(href).promise;const preload=document.createElement('link');preload.rel='preload';preload.as='style';preload.href=href;for(const name of ['crossorigin','integrity','referrerpolicy'])if(link.hasAttribute(name))preload.setAttribute(name,link.getAttribute(name));const entry={node:preload,promise:null};entry.promise=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Stylesheet preload timed out')),8000);preload.onload=()=>{clearTimeout(timer);resolve()};preload.onerror=()=>{clearTimeout(timer);reject(Error('Stylesheet preload failed'))}});entry.promise.catch(()=>{if(styles.get(href)===entry){styles.delete(href);preload.remove()}});styles.set(href,entry);document.head.append(preload);while(styles.size>32){const first=styles.keys().next().value;styles.get(first).node.remove();styles.delete(first)}return entry.promise}))}
function copyAttributes(from,to){for(const attribute of Array.from(to.attributes))to.removeAttribute(attribute.name);for(const attribute of from.attributes)to.setAttribute(attribute.name,attribute.value)}
function earlyCigenBridge(win,doc){const sizes=new Map();let replaying=false;win.addEventListener('message',event=>{if(replaying||event.data?.type!=='cigen:size'||!Number.isFinite(event.data.height)||event.data.height<=0||win.__ankiCigenFrames)return;const frame=Array.from(doc.querySelectorAll('iframe')).find(frame=>frame.contentWindow===event.source);if(frame)sizes.set(frame,{data:event.data,source:event.source,origin:event.origin})});return()=>{if(!win.__ankiCigenFrames)return;replaying=true;try{for(const [frame,event]of sizes)if(doc.contains(frame))win.dispatchEvent(new win.MessageEvent('message',event))}finally{sizes.clear();replaying=false}}}
function childDiagnostics(doc){const code='('+function(){const seen=new Map(),send=(event,extra={})=>{const detail={type:'study-child-diagnostic',event,state:document.readyState,body:!!document.body,height:document.body?.getBoundingClientRect().height||0,...extra},key=event+'|'+(extra.src||extra.filename||''),signature=JSON.stringify(detail);if(seen.get(key)===signature)return;seen.set(key,signature);parent.postMessage({...detail,at:performance.timeOrigin+performance.now()},'*')};window.addEventListener('error',event=>send('error',{message:event.message,filename:event.filename,line:event.lineno,stack:event.error?.stack}));document.addEventListener('error',event=>{const target=event.target;if(target&&target!==document)send('resource-error',{tag:target.tagName,src:target.src||target.href||'',base:document.baseURI})},true);for(const event of ['DOMContentLoaded','load'])window.addEventListener(event,()=>send(event),{once:true});window.addEventListener('message',event=>{if(event.source===parent&&['cigen:layout','cigen:theme'].includes(event.data?.type))send(event.data.type)});send('head-installed')}.toString()+')()';for(const frame of doc.querySelectorAll('iframe.etymology-source-frame[srcdoc]')){const helper='<scr'+'ipt>'+code+'</scr'+'ipt>';frame.setAttribute('srcdoc',frame.getAttribute('srcdoc').replace(/<head(?:\s[^>]*)?>/i,match=>match+helper))}}
function commit(doc,token){if(!pending||pending.token!==token||doc!==side.contentDocument)return false;const task=pending,win=doc.defaultView,replay=earlyCigenBridge(win,doc),source=task.document;
 try{copyAttributes(source.documentElement,doc.documentElement);copyAttributes(source.head,doc.head);copyAttributes(source.body,doc.body);const head=doc.createDocumentFragment(),body=doc.createDocumentFragment();for(const node of Array.from(source.head.childNodes))head.append(doc.importNode(node,true));for(const node of Array.from(source.body.childNodes))body.append(doc.importNode(node,true));doc.head.replaceChildren(head);doc.body.replaceChildren(body);doc.addEventListener('keydown',key);
 // The whole authored body is committed before any approved classic script.
 // Imported script nodes are inert; fresh nodes below execute in authored order.
 const scripts=Array.from(doc.querySelectorAll('script[data-study-classic]'));for(const old of scripts){const script=doc.createElement('script');for(const attribute of old.attributes)if(!['type','data-study-classic','data-study-type'].includes(attribute.name))script.setAttribute(attribute.name,attribute.value);const type=old.getAttribute('data-study-type');if(type)script.type=type;script.async=false;script.textContent=old.textContent;script.addEventListener('load',replay,{once:true});script.addEventListener('error',()=>{if(current===task.packet&&side.contentDocument===doc)fail(Error('Authored script failed to load'))},{once:true});old.replaceWith(script)}
 replay();note({event:'atomic-body-commit',visibleTextLength:doc.body.innerText?.length||doc.body.textContent.length,hasMeaning:!!doc.querySelector('.vocab-back .meaning-section'),hasExamples:!!doc.querySelector('.examples-section .example-card,.examples-section ._r28')});clearTimeout(task.timer);pending=null;flip.disabled=false;state();task.resolve(true);return true;
 }catch(error){fail(error);return false}}
async function show(requestedAt){if(!current)return false;flip.disabled=true;state();const packet=current,index=answer?1:0,base='<base href="'+attr(packet.base)+'">',original=packet.sides[index].replace(packet.baseTags[index],base),mounted=prepareScriptMount(original,packet.policy),token=String(accepted)+'-'+String(++sequence);if(pending){clearTimeout(pending.timer);pending.resolve(false);pending=null}activeRecord=null;
 if(packet.metricsAsset){activeRecord={card:packet.id,side:answer?'back':'front',token,request:requestedAt,preparing:clock(),fetchMs:answer?0:packet.fetchMs,deferred:mounted.inserted,externalized:mounted.externalized,reason:mounted.reason,events:[]};records.push(activeRecord);if(records.length>40)records.shift();report()}
 const atomic=packet.execution!=='parser';let parsed=null;if(atomic){if(!['deferred-in-source-order','already-deferred'].includes(mounted.reason)&&new DOMParser().parseFromString(original,'text/html').scripts.length)throw Error('Source scripts are not approved for atomic mounting: '+mounted.reason);parsed=new DOMParser().parseFromString(mounted.html,'text/html');if(/<noscript\b/i.test(mounted.html))throw Error('Scripting-dependent noscript parsing retains the original wrapper');if(packet.metricsAsset)childDiagnostics(parsed);for(const script of parsed.scripts){const type=(script.getAttribute('type')||'').trim().toLowerCase();if(['application/json','application/ld+json'].includes(type))continue;script.setAttribute('data-study-type',script.getAttribute('type')||'');script.setAttribute('data-study-classic','');script.type='application/x-study-inert'}await preloadStyles(parsed,packet.base);if(current!==packet||token!==String(accepted)+'-'+String(sequence))return false}
 const fresh=document.createElement('iframe');fresh.id='study-side';fresh.title=answer?'学习卡片背面':'学习卡片正面';fresh.dataset.mountReason=atomic?'atomic-'+mounted.reason:'original-parser';fresh.dataset.deferredScripts=String(mounted.inserted);fresh.dataset.externalizedScripts=String(mounted.externalized);fresh.dataset.cardId=packet.id;fresh.addEventListener('load',()=>{fresh.contentDocument?.addEventListener('keydown',key);if(fresh===side&&activeRecord){activeRecord.wrapperLoad=clock();report()}});
 flip.textContent=answer?'返回正面':'显示答案';flip.setAttribute('aria-pressed',String(answer));flip.disabled=atomic;if(activeRecord){activeRecord.mount=clock();report()}
 const helper=packet.metricsAsset?'<scr'+'ipt src="'+attr(packet.metricsAsset)+'" data-study-token="'+token+'" data-study-origin="'+attr(origin)+'"></scr'+'ipt>':'';
 if(!atomic){const html=original.replace(/<head(?:\s[^>]*)?>/i,match=>match+helper);side.replaceWith(fresh);side=fresh;fresh.srcdoc=html;state();return true}
 const promise=new Promise((resolve,reject)=>{pending={token,document:parsed,packet,resolve,reject,timer:setTimeout(()=>fail(Error('Atomic document initialization timed out')),8000)}});
 const bootstrap='<!doctype html><html><head><meta charset="utf-8">'+base+helper+'</head><body><scr'+'ipt>parent.StudySharedFrame.commit(document,'+JSON.stringify(token)+');</scr'+'ipt></body></html>';
 side.replaceWith(fresh);side=fresh;fresh.srcdoc=bootstrap;state();return promise;
}
function key(event){if(event.target.closest('input,select,textarea,button,summary,a,[contenteditable]'))return;if(event.code==='Space'){event.preventDefault();flip.click()}if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();parent.postMessage({type:'study-navigate',direction:event.key==='ArrowRight'?1:-1},origin)}}
flip.onclick=()=>{if(!current||flip.disabled)return;const packet=current,token=accepted,expected=sequence+1;answer=!answer;show(clock()).catch(error=>{if(current===packet&&accepted===token&&sequence===expected)fail(error)})};document.addEventListener('keydown',key);
window.addEventListener('message',event=>{if(event.source!==side.contentWindow||event.data?.type!=='study-render-metric')return;const record=records.find(row=>row.token===event.data.token);if(!record)return;recordEvent(record,event.data.detail);report()});
window.StudySharedFrame={commit,async mount(packet){if(!packet||!Number.isSafeInteger(packet.token)||packet.token<=accepted||typeof packet.id!=='string'||!Array.isArray(packet.sides)||packet.sides.length!==2||!packet.sides.every(value=>typeof value==='string')||!Array.isArray(packet.baseTags)||packet.baseTags.length!==2)return false;const base=new URL(packet.base);if(base.origin!==origin||!['http:','https:'].includes(base.protocol))throw Error('Invalid shared card resource base');accepted=packet.token;current=packet;answer=false;return show(packet.requestedAt)}};
})();'''


RENDER_METRICS_RUNTIME = r'''(function(){'use strict';
const helper=document.currentScript,token=helper.dataset.studyToken,origin=helper.dataset.studyOrigin,start=performance.now();
const clock=()=>performance.timeOrigin+performance.now();let heights=0,h500=0,h1000=0,lastHeight=null,cigenCount=0,cigenChanges=0,lastCigen=null,longtasks=0,maxLongtask=0,queued=false,first=false;
const sizes=[];const send=detail=>parent.postMessage({type:'study-render-metric',token,detail:{at:clock(),...detail}},origin);
function content(){const body=document.body;return{visibleTextLength:body?.innerText?.length||0,hasMeaning:!!document.querySelector('.vocab-back .meaning-section'),hasExamples:!!document.querySelector('.examples-section .example-card,.examples-section ._r28'),height:body?body.getBoundingClientRect().height:0,nativeStates:Array.from(document.querySelectorAll('[data-native-state]'),node=>node.getAttribute('data-native-state'))}}
function counters(event){return{event,cigenCount,cigenHeightChanges:cigenChanges,cigenRecentHeights:sizes.slice(),longtasks,maxLongtask,heightChanges500:h500,heightChanges1000:h1000,totalHeightChanges:heights}}
function schedule(){if(queued)return;queued=true;setTimeout(()=>{queued=false;send(counters('activity'))},250)}
requestAnimationFrame(()=>send({event:'first-any-animation-frame',...content()}));
function firstFrame(){const info=content();if(info.visibleTextLength){first=true;send({event:'first-visible-animation-frame',...info});requestAnimationFrame(()=>send({event:'next-animation-frame',...content()}))}else if(performance.now()-start<5000)requestAnimationFrame(firstFrame)}requestAnimationFrame(firstFrame);
const resize=new ResizeObserver(()=>{const height=document.body?.getBoundingClientRect().height;if(height===undefined||height===lastHeight)return;lastHeight=height;heights++;if(performance.now()-start<=500)h500++;if(performance.now()-start<=1000)h1000++});
const discovery=new MutationObserver(()=>{if(document.body){resize.observe(document.body);discovery.disconnect()}});if(document.documentElement)discovery.observe(document.documentElement,{childList:true,subtree:true});if(document.body){resize.observe(document.body);discovery.disconnect()}
window.addEventListener('error',event=>send({event:'source-error',message:event.message,filename:event.filename,line:event.lineno}));
document.addEventListener('error',event=>{const target=event.target;if(target&&target!==document)send({event:'resource-error',tag:target.tagName,src:target.src||target.href||''})},true);
const states=new MutationObserver(entries=>{for(const entry of entries)if(entry.attributeName==='data-native-state')send({event:'native-state',...content()})});if(document.documentElement)states.observe(document.documentElement,{subtree:true,attributes:true,attributeFilter:['data-native-state']});
for(const event of ['DOMContentLoaded','load'])window.addEventListener(event,()=>send({event,...content(),...counters(event)}),{once:true});
window.addEventListener('message',event=>{if(event.data?.type==='study-child-diagnostic'){const frame=Array.from(document.querySelectorAll('iframe')).find(frame=>frame.contentWindow===event.source);if(frame)send({event:'child-diagnostic',detail:event.data});return}if(event.data?.type!=='cigen:size'||!Number.isFinite(event.data.height))return;cigenCount++;if(event.data.height!==lastCigen){lastCigen=event.data.height;cigenChanges++;sizes.push(event.data.height);if(sizes.length>12)sizes.shift()}schedule()});
if(typeof PerformanceObserver==='function'){for(const type of ['longtask','paint']){if(!PerformanceObserver.supportedEntryTypes?.includes(type))continue;try{new PerformanceObserver(list=>{for(const entry of list.getEntries())if(type==='longtask'){longtasks++;maxLongtask=Math.max(maxLongtask,entry.duration);schedule()}else send({event:entry.name,entryStart:performance.timeOrigin+entry.startTime})}).observe({type,buffered:true})}catch(_){}}}
for(const event of ['pointerdown','click'])document.addEventListener(event,e=>send({event:'source-'+event,target:e.target.tagName,label:e.target.textContent?.trim().slice(0,60)}),true);
setTimeout(()=>send({...counters('500ms'),...content()}),500);setTimeout(()=>{send({...counters('1000ms'),...content()});resize.disconnect();discovery.disconnect()},1000);
})();'''


def shared_frame_html() -> str:
    """One reusable frame host. Authored card HTML arrives only as data."""
    runtime = DEFER_SCRIPTS_RUNTIME + '\n' + SHARED_FRAME_RUNTIME
    if '</script' in runtime.lower():
        raise ValueError('shared frame runtime contains an unsafe HTML script boundary')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<style>html,body{margin:0;height:100%;background:#f5f7fc}'
            '#study-side{display:block;border:0;width:100%;height:100%}'
            '#study-flip{position:fixed;right:12px;top:10px;z-index:99999;border:1px solid #dbe3ef;'
            'border-radius:6px;padding:8px 12px;background:white;color:#215fbb;font:14px system-ui;cursor:pointer}'
            '</style></head><body><button id="study-flip" type="button" aria-pressed="false">显示答案</button>'
            '<iframe id="study-side" title="学习卡片正面"></iframe><script>' + runtime + '</script></body></html>')


def card_shell(payload: str, base: str, *, script_policy: dict | None = None) -> str:
    """Mount exactly one authored side, with resources resolved before parsing.

    The JSON literal is the shared renderer's exact output, not a second field
    renderer. Refreshing an existing export passes that same literal through.
    """
    original_base = '<base href="' + html.escape(base, quote=True) + '">'
    mount_runtime = ''
    mount_side = 'side.srcdoc=sides[answer?1:0];'
    if script_policy is not None:
        mount_runtime = DEFER_SCRIPTS_RUNTIME + 'const mountPolicy=' + _json(script_policy) + ';'
        mount_side = ('const mounted=prepareScriptMount(sides[answer?1:0],mountPolicy);'
                      'side.dataset.mountReason=mounted.reason;side.dataset.deferredScripts=String(mounted.inserted);side.srcdoc=mounted.html;')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;height:100%;background:#f5f7fc}#study-side{border:0;width:100%;height:100%}'
        '#study-flip{position:fixed;right:12px;top:10px;z-index:99999;border:1px solid #dbe3ef;border-radius:6px;'
        'padding:8px 12px;background:white;color:#215fbb;font:14px system-ui;cursor:pointer}</style></head><body>'
        '<button id="study-flip" type="button" aria-pressed="false">显示答案</button><iframe id="study-side" title="学习卡片正面"></iframe>'
        '<script>const absoluteBase=document.createElement("base");absoluteBase.href=new URL(' + _json(base) + ',location.href);'
        'const sides=' + payload + '.map(content=>content.replace(' + _json(original_base) + ',absoluteBase.outerHTML));'
        + mount_runtime + 'let answer=false;const side=document.getElementById("study-side"),flip=document.getElementById("study-flip");'
        'function show(){' + mount_side + 'side.title=answer?"学习卡片背面":"学习卡片正面";flip.textContent=answer?"返回正面":"显示答案";'
        'flip.setAttribute("aria-pressed",String(answer))}flip.onclick=()=>{answer=!answer;show()};'
        'function key(e){if(e.target.matches("input,select,textarea,button,summary,a,[contenteditable]"))return;'
        'if(e.code==="Space"){e.preventDefault();flip.click()}if(e.key==="ArrowLeft"||e.key==="ArrowRight")'
        '{e.preventDefault();parent.postMessage({type:"study-navigate",direction:e.key==="ArrowRight"?1:-1},location.origin)}}'
        'document.addEventListener("keydown",key);side.onload=()=>{side.contentDocument.addEventListener("keydown",key)};show();</script></body></html>')


def write_library(root: Path, catalog: dict, metadata: dict | None = None, *, shared_frame: dict | None = None) -> dict:
    """Write a versioned navigation index and common host assets.

    Content addressed names let ordinary HTTP caches reuse the host without a
    service worker, cache invalidation rule, or a second content renderer.
    """
    navigation = navigation_index(catalog, metadata)
    payload = _json(navigation).encode()
    nav_name = '_study_navigation_' + hashlib.sha256(payload).hexdigest() + '.json'
    runtime = HOST_RUNTIME.encode()
    runtime_name = '_study_library_' + hashlib.sha256(runtime).hexdigest() + '.js'
    (root / nav_name).write_bytes(payload)
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    (root / (nav_name + '.gz')).write_bytes(compressed)
    (root / runtime_name).write_bytes(runtime)
    initial = next((row for row in navigation['cards'] if row[7]), navigation['cards'][0] if navigation['cards'] else None)
    (root / 'index.html').write_text(library_html(catalog['title'], navigation_href=nav_name,
                                               navigation_gzip_href=nav_name + '.gz', initial=initial,
                                               total=navigation['totals']['cards'], totals=navigation['totals'],
                                               initial_path=navigation['units'][initial[3]] if initial else '', shared_frame=shared_frame))
    return {'navigation_bytes': len(payload), 'navigation_cards': len(navigation['cards']),
            'runtime_bytes': len(runtime), 'navigation_gzip_bytes': len(compressed)}


def card_payload(page: bytes) -> bytes:
    """Read the JSON array boundary without mistaking quoted card text for JS."""
    prefix = b'<script>const sides='
    marker = page.find(prefix)
    if marker < 0:
        # This is the shared v2 shell, with its base prepared before the array.
        marker = page.find(b'<script>const absoluteBase=')
        if marker < 0:
            raise ValueError('source card has an unsupported browser wrapper')
        marker = page.find(b'const sides=', marker)
        if marker < 0:
            raise ValueError('source card is missing the common side payload')
        start = marker + len(b'const sides=')
        expected_suffix = '.map(content=>content.replace('
    else:
        start = marker + len(prefix)
        expected_suffix = ';let answer=false;const side='
    source = page[start:].decode('utf-8')
    try:
        sides, end = json.JSONDecoder().raw_decode(source)
    except json.JSONDecodeError as error:
        raise ValueError('source card has an invalid side payload') from error
    if not isinstance(sides, list) or len(sides) != 2 or not all(isinstance(side, str) for side in sides):
        raise ValueError('source card has an unsupported side payload')
    if not source[end:].startswith(expected_suffix):
        raise ValueError('source card is missing the common flip wrapper')
    # raw_decode locates the end by JSON syntax. This is the exact source
    # literal, not a serialization of the decoded sides.
    return source[:end].encode('utf-8')


def upgrade_card_base(page: bytes) -> bytes:
    """Absolutize the common wrapper base while keeping its payload byte exact.

    Chromium's speculative loader can request srcdoc resources against the
    parent card URL before resolving a relative base. An absolute srcdoc base
    avoids the failed first request. This adapter changes only the enclosing
    wrapper; it neither parses nor serializes the authored front/back payload.
    """
    if b'<script>const absoluteBase=' in page:
        card_payload(page)
        return page
    payload = card_payload(page)
    # Both refreshes and new PostgreSQL exports use this exact host generator.
    result = card_shell(payload.decode('utf-8'), '../media/').encode()
    if payload not in result:
        raise AssertionError('card refresh changed the authored side payload')
    return result


def refresh_library(source: Path, destination: Path, *, expected_revision: int | None = None,
                    upgrade_card_bases: bool = False, metadata: dict | None = None, callback=None) -> dict:
    """Publish the new common host around a complete, immutable web export.

    Cards, media and the complete catalog stay in their original export. Only
    small navigation/host files are generated; relative directory symlinks do
    not duplicate thousands of media files or revise source card fields. The
    original export must be retained alongside this local host refresh.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    # macOS /var and /tmp can be symlinked parents. Compute link paths against
    # the actual parent so they still resolve after staging publication.
    destination = destination.parent.resolve() / destination.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('refreshed web destination already exists')
    if destination.is_relative_to(source):
        raise ValueError('refreshed host must not be written inside its source export')
    marker_raw = (source / 'COMPLETE.json').read_bytes()
    marker = json.loads(marker_raw)
    catalog_raw = (source / 'catalog.json').read_bytes()
    catalog = json.loads(catalog_raw)
    if marker.get('format') != 'web' or catalog.get('schema') != 'shared-book-web.v1':
        raise ValueError('source is not a complete common web export')
    if marker.get('cards') != len(catalog['cards']):
        raise ValueError('source completion marker has a different card count')
    if expected_revision is not None and catalog.get('catalog_revision') != expected_revision:
        raise ValueError('source catalog revision differs from the approved source')
    for name in ('cards', 'media'):
        if not (source / name).is_dir():
            raise ValueError('source export is missing its ' + name + ' directory')
    ids = set()
    for card in catalog['cards']:
        path = (source / card['url']).resolve()
        if not path.is_relative_to((source / 'cards').resolve()) or not path.is_file():
            raise ValueError('source catalog has an unsafe or missing card')
        if card['id'] in ids:
            raise ValueError('source catalog repeats a native card identity')
        ids.add(card['id'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.study-host-', dir=destination.parent) as staging:
        staging = Path(staging)
        for name in ('media', 'catalog.json', *(() if upgrade_card_bases else ('cards',))):
            # Staging and destination have equal depth under the same parent.
            (staging / name).symlink_to(os.path.relpath(source / name, destination),
                                      target_is_directory=name != 'catalog.json')
        upgraded = 0
        if upgrade_card_bases:
            (staging / 'cards').mkdir()
            for number, card in enumerate(catalog['cards'], 1):
                raw = (source / card['url']).read_bytes()
                revised = upgrade_card_base(raw)
                target = staging / card['url']
                # Card URLs have already been bounded to the source cards
                # directory above. They must also stay in the new directory.
                if not target.resolve().is_relative_to((staging / 'cards').resolve()):
                    raise ValueError('source card URL cannot be reused in refreshed export')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(revised)
                upgraded += revised != raw
                if callback and number % 500 == 0:
                    callback({'stage': 'refresh-card-host', 'completed': number,
                              'cards': len(catalog['cards'])})
        navigation = write_library(staging, catalog, metadata)
        report = {**marker, **navigation, 'schema': 'study-web-host-refresh.v1',
                  'host_version': 'study-web-host.v3',
                  'host_runtime_sha256': hashlib.sha256(HOST_RUNTIME.encode()).hexdigest(),
                  'source_export': os.path.relpath(source, destination),
                  'source_catalog_revision': catalog.get('catalog_revision'),
                  'source_catalog_sha256': hashlib.sha256(catalog_raw).hexdigest(),
                  'source_complete_sha256': hashlib.sha256(marker_raw).hexdigest(),
                  'reused_cards_and_media': 'exact-payload-new-card-hosts' if upgrade_card_bases else 'relative-symlink',
                  'upgraded_card_bases': upgraded,
                  'generator': 'anki_pipeline.study_catalog_web.refresh_library'}
        destination.mkdir()
        for child in staging.iterdir():
            shutil.move(str(child), destination / child.name)
        # No successful-looking marker is visible for a partially moved host.
        (destination / 'COMPLETE.json').write_text(_json(report))
    return {**report, 'output': str(destination)}


def redirect_library_entry(source: Path, destination: Path) -> dict:
    """Retain an existing URL after an immutable common-host refresh.

    The old index is recoverable by its SHA. Catalog, cards, media and completion
    markers remain untouched; query parameters and card/deck hashes pass through.
    """
    source, destination = source.resolve(strict=True), destination.resolve(strict=True)
    if source == destination:
        raise ValueError('entry redirect requires a different complete host')
    marker = json.loads((destination / 'COMPLETE.json').read_bytes())
    if marker.get('format') != 'web' or marker.get('host_version') != 'study-web-host.v3':
        raise ValueError('entry destination is not a complete current common host')
    for name in ('cards', 'media'):
        if (source / name).resolve(strict=True) != (destination / name).resolve(strict=True):
            raise ValueError('entry redirect must retain the original cards and media')
    if (source / 'catalog.json').read_bytes() != (destination / 'catalog.json').read_bytes():
        raise ValueError('entry redirect must retain the exact original catalog')
    page = source / 'index.html'
    original = page.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    backup = source / ('index.before-host-v3.' + digest + '.html')
    if backup.exists():
        if backup.read_bytes() != original:
            raise ValueError('entry backup differs from the original index')
    else:
        with backup.open('xb') as stream:
            stream.write(original)
    href = Path(os.path.relpath(destination / 'index.html', source)).as_posix()
    body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>正在打开学习目录</title><p><a href="' + html.escape(href, quote=True) + '">打开学习目录</a></p>'
            '<script>const target=new URL(' + _json(href) + ',location.href);'
            'target.search=location.search;target.hash=location.hash;location.replace(target.href);</script></html>').encode()
    with tempfile.NamedTemporaryFile(dir=source, prefix='.index-redirect-', delete=False) as stream:
        staging = Path(stream.name)
        stream.write(body)
    try:
        if page.read_bytes() != original:
            raise ValueError('entry changed during redirect preparation; original was retained')
        os.replace(staging, page)
    finally:
        staging.unlink(missing_ok=True)
    return {'source': str(source), 'destination': str(destination), 'backup': str(backup),
            'original_index_sha256': digest, 'redirect_index_sha256': hashlib.sha256(body).hexdigest(),
            'relative_target': href, 'preserves_query_and_hash': True}


def library_html(title: str, *, navigation_href: str = 'navigation.json',
                 runtime_href: str | None = None, navigation_gzip_href: str | None = None,
                 initial: list | None = None, total: int = 0, totals: dict | None = None,
                 initial_path: str = '', shared_frame: dict | None = None) -> str:
    """Use the original three-column/drawer layout with bounded live rows."""
    config = _json({'navigation': navigation_href, 'navigationGzip': navigation_gzip_href,
                    'initial': initial, 'total': total, 'totals': totals, 'initialPath': initial_path, 'sharedFrame': shared_frame})
    stylesheet = (Path(__file__).parent / 'templates' / 'library-preview.css').read_text()
    stylesheet = stylesheet.replace('#card-frame', '#frame')
    stylesheet += '.word-list .virtual-spacer{padding:0;margin:0;border:0;pointer-events:none}.word-list{overflow-anchor:none}#frame{border:0}#status:empty{display:none}'
    runtime = ('<script defer src="' + html.escape(runtime_href, quote=True) + '"></script>'
               if runtime_href else '<script>' + HOST_RUNTIME + '</script>')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><style>' + stylesheet + '</style></head><body>' + '''
<header class="library-header"><button id="browse-toggle" class="small-button browse-toggle" aria-controls="browse-panel" aria-expanded="false">目录</button><div class="library-heading"><h1 id="library-name">''' + html.escape(title) + '''</h1><p id="library-summary" role="status">正在加载目录…</p></div><div class="card-toolbar" aria-label="卡片导航"><button id="guide-card" class="small-button" hidden>说明</button><span id="card-position" class="card-position" aria-live="polite"></span><button id="previous-card" class="small-button" aria-label="上一张卡片" title="上一张（←）" disabled>上一张</button><button id="next-card" class="small-button" aria-label="下一张卡片" title="下一张（→）" disabled>下一张</button><button id="flip-card" class="small-button primary-button" aria-pressed="false" title="翻面（空格）" disabled>显示答案</button></div></header>
<div class="catalog-failure" id="catalog-failure" hidden><p id="status" role="status"></p><button id="retry" class="small-button" hidden>重新读取目录</button></div>
<main class="library-workspace"><div id="browse-backdrop" class="browse-backdrop" hidden></div><aside id="browse-panel" class="browse-panel" aria-label="卡组和单词目录"><nav class="deck-panel" aria-labelledby="decks-heading"><div class="panel-heading"><h2 id="decks-heading">卡组</h2><button id="browse-close" class="small-button browse-close" aria-label="关闭目录">关闭</button></div><div id="deck-tree" class="deck-tree"></div></nav><section class="word-panel" aria-labelledby="words-heading"><div class="word-search-panel"><div class="panel-heading"><h2 id="words-heading">单词</h2><span id="word-count" class="muted"></span></div><label class="visually-hidden" for="word-search">在当前卡组中搜索单词或释义</label><div class="search-field"><input id="word-search" type="search" placeholder="搜索单词或释义" aria-label="在当前卡组中搜索单词或释义" autocomplete="off" spellcheck="false" disabled><button id="clear-search" aria-label="清空搜索" hidden>清空</button></div></div><p id="word-empty" class="word-empty" role="status" hidden>没有匹配的单词。清空搜索或选择其他卡组。</p><ul id="word-list" class="word-list" aria-label="单词列表"></ul></section></aside><section id="card-stage" class="card-stage" tabindex="-1" aria-labelledby="deck-path"><div class="reader-heading"><p id="deck-path">全部卡组</p><span class="shortcut-hint">← → 切卡 · 空格翻面</span></div><p id="card-render-notice" class="muted" role="status" hidden></p><div class="frame-area"><div id="frame-host" class="frame-host"><iframe id="frame" title="学习卡片"></iframe></div><p id="empty" class="card-status" role="status" hidden>没有匹配的内容</p></div></section></main>
<script id="study-library-config" type="application/json">''' + config + '''</script><script>(function(){const c=JSON.parse(document.getElementById('study-library-config').textContent),wanted=new URLSearchParams(location.hash.slice(1)).get('card');if(!c.sharedFrame&&c.initial&&(!wanted||wanted===c.initial[0])){const f=document.getElementById('frame');f.src=c.initial[4];f.dataset.studyCardId=c.initial[0];document.getElementById('card-position').textContent='1 / '+c.total;document.getElementById('deck-path').textContent=c.initialPath}})();</script>''' + runtime + '</body></html>'


def card_wrapper_contracts() -> list[dict]:
    """Known generated wrapper versions; every non-payload byte is checked."""
    token = '["__study_contract_front__","__study_contract_back__"]'
    modern = card_shell(token, '../media/')
    prefix, suffix = modern.split(token)
    marker = '<script>const absoluteBase=document.createElement("base");absoluteBase.href=new URL("../media/",location.href);const sides='
    legacy_prefix = prefix.replace(marker, '<script>const sides=').replace('学习卡片正面', '词卡正面')
    mapped = '.map(content=>content.replace(' + _json('<base href="../media/">') + ',absoluteBase.outerHTML))'
    legacy_suffix = suffix.removeprefix(mapped).replace('学习卡片背面', '词卡背面').replace('学习卡片正面', '词卡正面')
    return [{'prefix': prefix, 'suffix': suffix}, {'prefix': legacy_prefix, 'suffix': legacy_suffix}]


HOST_RUNTIME = r'''(function(){
'use strict';
const $=id=>document.getElementById(id),frame=$('frame'),list=$('word-list'),query=$('word-search'),panel=$('browse-panel');
const config=JSON.parse($('study-library-config').textContent),lower=value=>value.toLocaleLowerCase(),count=value=>Number(value).toLocaleString();
''' + r'''function readAuthoredCard(page,href){
 const contracts=''' + _json(card_wrapper_contracts()) + r''';
 const url=new URL(href,location.href),modern='<script>const absoluteBase=document.createElement("base");absoluteBase.href=new URL(',old='<script>const sides=';
 let start,baseValue=null,mode;
 const marker=page.indexOf(modern);
 if(marker>=0){const tail=page.slice(marker+modern.length),match=/^("(?:[^"\\]|\\.)*"),location\.href\);const sides=/.exec(tail);if(!match)throw Error('Unsupported card resource-base wrapper');baseValue=JSON.parse(match[1]);start=marker+modern.length+match[0].length;mode='modern'}
 else{const marker=page.indexOf(old);if(marker<0)throw Error('Unsupported card wrapper');start=marker+old.length;mode='legacy'}
 if(page[start]!=='[')throw Error('Missing card side array');let quote=false,escape=false,depth=0,end=-1;
 for(let index=start;index<page.length;index++){const char=page[index];if(quote){if(escape)escape=false;else if(char==='\\')escape=true;else if(char==='"')quote=false}else if(char==='"')quote=true;else if(char==='['||char==='{')depth++;else if(char===']'||char==='}'){depth--;if(!depth){end=index+1;break}}}
 if(end<0)throw Error('Incomplete card side array');
 const literal=page.slice(start,end),sides=JSON.parse(literal),suffix=page.slice(end);
 if(!contracts.some(contract=>page.slice(0,start)===contract.prefix&&suffix===contract.suffix))throw Error('Unknown card wrapper skeleton');
 if(!Array.isArray(sides)||sides.length!==2||!sides.every(value=>typeof value==='string'))throw Error('Unsupported card side payload');
 if(!(mode==='modern'?suffix.startsWith('.map(content=>content.replace('):suffix.startsWith(';let answer=false;const side=')))throw Error('Unsupported card mount wrapper');
 const baseTags=[];for(const side of sides){const tags=Array.from(side.matchAll(/<base\b(?:[^"'<>]|"[^"]*"|'[^']*')*>/gi));if(tags.length!==1)throw Error('Ambiguous authored resource base');const document=new DOMParser().parseFromString(side.slice(0,side.indexOf('</head>')+7),'text/html'),bases=document.querySelectorAll('base');if(bases.length!==1||!bases[0].hasAttribute('href'))throw Error('Missing authored resource base');const value=bases[0].getAttribute('href');if(baseValue===null)baseValue=value;if(value!==baseValue)throw Error('Inconsistent authored resource base');baseTags.push(tags[0][0])}
 const base=new URL(baseValue,url),bookRoot=new URL('../',url);if(base.origin!==url.origin||!['http:','https:'].includes(base.protocol)||base.username||base.password||base.search||base.hash||!base.pathname.startsWith(bookRoot.pathname))throw Error('Unsafe authored resource base');
 return{sides,base:base.href,baseTags,literal};
}
let sharedReady=null,sharedMountPending=false,cardGeneration=0,activeCardRequest=null,cardCacheBytes=0;const cardCache=new Map(),cardRequests=new Map(),cacheLimit=4,cacheByteLimit=2*1024*1024;
function resetSharedFrame(){cardGeneration++;sharedMountPending=false;activeCardRequest?.controller.abort();sharedReady=null;frame.removeAttribute('srcdoc');delete frame.dataset.sharedHost}
function cacheCard(id,value,bytes){if(bytes>cacheByteLimit)return;const previous=cardCache.get(id);if(previous)cardCacheBytes-=previous.bytes;cardCache.delete(id);cardCache.set(id,{value,bytes});cardCacheBytes+=bytes;while(cardCache.size>cacheLimit||cardCacheBytes>cacheByteLimit){const first=cardCache.keys().next().value;cardCacheBytes-=cardCache.get(first).bytes;cardCache.delete(first)}}
async function fetchCard(card){const cached=cardCache.get(card.id);if(cached){cardCache.delete(card.id);cardCache.set(card.id,cached);return cached.value}let pending=cardRequests.get(card.id);if(pending&&!pending.controller.signal.aborted)return pending.promise;const controller=new AbortController();pending={controller,promise:null};activeCardRequest=pending;pending.promise=(async()=>{const response=await fetch(safeURL(card.url),{signal:controller.signal});if(!response.ok)throw Error('HTTP '+response.status);const text=await response.text(),parsed=readAuthoredCard(text,safeURL(card.url));const value={sides:parsed.sides,base:parsed.base,baseTags:parsed.baseTags},bytes=2*(value.sides[0].length+value.sides[1].length+value.base.length+value.baseTags.join('').length);cacheCard(card.id,value,bytes);return value})().finally(()=>{if(cardRequests.get(card.id)===pending)cardRequests.delete(card.id);if(activeCardRequest===pending)activeCardRequest=null});cardRequests.set(card.id,pending);return pending.promise}
function ensureSharedFrame(){if(sharedReady)return sharedReady;sharedReady=new Promise((resolve,reject)=>{const loaded=()=>{cleanup();const api=frame.contentWindow?.StudySharedFrame;if(api){frame.dataset.sharedHost='ready';resolve(api)}else reject(Error('Shared card host failed to initialize'))};const timer=setTimeout(()=>{cleanup();reject(Error('Shared card host initialization timed out'))},8000);function cleanup(){clearTimeout(timer);frame.removeEventListener('load',loaded)}frame.addEventListener('load',loaded);frame.removeAttribute('src');frame.srcdoc=config.sharedFrame.html});return sharedReady}
function resolvedPolicy(){const original=config.sharedFrame.policy||{};if(config.sharedFrame.metricsAsset&&new URL(location.href).searchParams.get('execution')==='original')return{};return{external:original.external||original,inline:(original.inline||[]).map(rule=>({...rule,src:new URL(rule.src,location.href).href}))}}
async function mountSharedCard(card){sharedMountPending=true;$('flip-card').disabled=true;const token=++cardGeneration,requestedAt=performance.timeOrigin+performance.now();activeCardRequest?.controller.abort();const notice=$('card-render-notice');if(notice)notice.hidden=true;try{const began=performance.now(),[payload,api]=await Promise.all([fetchCard(card),ensureSharedFrame()]);if(token!==cardGeneration||selected!==card.id&&loaded)return;const accepted=await api.mount({...payload,literal:undefined,id:card.id,token,requestedAt,fetchMs:performance.now()-began,policy:resolvedPolicy(),execution:config.sharedFrame.metricsAsset&&new URL(location.href).searchParams.get('execution')==='original'?'parser':'atomic',metricsAsset:config.sharedFrame.metricsAsset?new URL(config.sharedFrame.metricsAsset,location.href).href:null});if(token!==cardGeneration||selected!==card.id&&loaded)return;if(!accepted)throw Error('Shared card mount was superseded');frame.dataset.mountMode='shared';syncFlip()}catch(error){if(token!==cardGeneration)return;sharedReady=null;frame.removeAttribute('srcdoc');delete frame.dataset.sharedHost;frame.src=safeURL(card.url);frame.dataset.mountMode='original-wrapper-fallback';if(notice){notice.hidden=false;notice.textContent='卡片载入异常，已重试原始页面。'}console.warn('Study library retained the original card wrapper:',error)}finally{if(token===cardGeneration){sharedMountPending=false;syncFlip()}}}
''' + r'''
let all=[],entries=[],visible=[],units=[],byId=new Map(),byUnit=new Map(),selected=null,selectedIndex=-1,selectedDeck='',loaded=false,loading=false,browseOpen=false;
let offsets=[0],heights=new Map(),renderStart=-1,renderEnd=-1,scrollScheduled=false,measuring=false;
const rowEstimate=91,interactive='input,select,textarea,button,summary,a,[contenteditable]',media=window.matchMedia?window.matchMedia('(max-width: 900px)'):null;
const narrow=()=>media?media.matches:window.innerWidth<=900,requested=()=>new URLSearchParams(location.hash.slice(1)).get('card');
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el}
function safeURL(value){const url=new URL(value,location.href);if(url.origin!==location.origin||url.protocol!==location.protocol)throw Error('目录中的卡片地址无效');return url.href}
function drawer(open){browseOpen=Boolean(open)&&narrow();panel.hidden=narrow()&&!browseOpen;$('browse-backdrop').hidden=!browseOpen;$('browse-toggle').setAttribute('aria-expanded',String(browseOpen))}
$('browse-toggle').onclick=()=>drawer(!browseOpen);$('browse-close').onclick=()=>drawer(false);$('browse-backdrop').onclick=()=>drawer(false);media?.addEventListener('change',()=>drawer(false));drawer(false);
function updateHash(id){const params=new URLSearchParams({card:id});if(selectedDeck!=='')params.set('deck',selectedDeck);const hash=params.toString();if(location.hash.slice(1)!==hash)location.hash=hash}
function controls(){selectedIndex=visible.findIndex(card=>card.id===selected);$('card-position').textContent=count(selectedIndex+1)+' / '+count(visible.length);$('previous-card').disabled=selectedIndex<=0;$('next-card').disabled=selectedIndex<0||selectedIndex>=visible.length-1;$('word-count').textContent=count(visible.length);$('flip-card').disabled=!selected||sharedMountPending;}
function empty(){if(config.sharedFrame)resetSharedFrame();selected=null;selectedIndex=-1;frame.hidden=true;frame.removeAttribute('src');delete frame.dataset.studyCardId;$('empty').hidden=false;$('word-empty').hidden=false;$('flip-card').textContent='显示答案';$('flip-card').setAttribute('aria-pressed','false');controls()}
function offsetsForRows(){offsets=[0];for(const card of visible)offsets.push(offsets[offsets.length-1]+(heights.get(card.id)||rowEstimate))}
function indexAt(y){let low=0,high=visible.length;while(low<high){const mid=(low+high)>>1;if(offsets[mid+1]<=y)low=mid+1;else high=mid}return low}
function renderRows(force=false,target=null){const at=indexAt(target??list.scrollTop),start=Math.max(0,at-15),end=Math.min(visible.length,start+90);if(!force&&start===renderStart&&end===renderEnd){if(target!==null)list.scrollTop=target;return}renderStart=start;renderEnd=end;const fragment=document.createDocumentFragment();
function spacer(height){const el=node('li','virtual-spacer');el.style.height=height+'px';el.setAttribute('aria-hidden','true');return el}fragment.append(spacer(offsets[start]||0));
for(let i=start;i<end;i++){const card=visible[i],li=node('li'),b=node('button','word-entry');b.type='button';b.dataset.cardId=card.id;b.setAttribute('aria-current',String(card.id===selected));b.append(node('span','word-entry-name',card.label),node('span','word-entry-definition',card.summary),node('span','word-entry-meta',card.examples===null?'例句数未确认':count(card.examples)+' 例句'));b.onclick=()=>open(card,{close:true});li.append(b);fragment.append(li)}fragment.append(spacer((offsets[visible.length]||0)-(offsets[end]||0)));list.replaceChildren(fragment);if(target!==null)list.scrollTop=target;
if(!measuring){measuring=true;requestAnimationFrame(()=>{measuring=false;const anchor=indexAt(list.scrollTop),old=offsets[anchor]||0;let changed=false;for(const b of list.querySelectorAll('.word-entry')){const height=b.parentElement.getBoundingClientRect().height;if(height>0&&Math.abs(height-(heights.get(b.dataset.cardId)||rowEstimate))>.5){heights.set(b.dataset.cardId,height);changed=true}}if(changed){offsetsForRows();list.scrollTop+=(offsets[anchor]||0)-old;renderRows(true)}})}}
list.addEventListener('scroll',()=>{if(!scrollScheduled){scrollScheduled=true;requestAnimationFrame(()=>{scrollScheduled=false;renderRows()})}},{passive:true});
function draw({rebuild=false,ensure=false}={}){controls();let target=rebuild?0:null;if(rebuild){offsetsForRows();renderStart=-1;renderEnd=-1}if(ensure&&selectedIndex>=0){const top=offsets[selectedIndex],bottom=offsets[selectedIndex+1],height=list.clientHeight||400,current=target??list.scrollTop;if(top<current||bottom>current+height)target=Math.max(0,top-30)}renderRows(rebuild,target);for(const b of list.querySelectorAll('.word-entry')){const current=String(b.dataset.cardId===selected);if(b.getAttribute('aria-current')!==current)b.setAttribute('aria-current',current)}for(const b of $('deck-tree').querySelectorAll('.deck-entry')){const current=b.dataset.deckKey===selectedDeck?'page':'false';if(b.getAttribute('aria-current')!==current)b.setAttribute('aria-current',current)}}
function open(card,{hash=true,close=false,rebuild=false}={}){if(!card){empty();draw({rebuild});return}selected=card.id;frame.hidden=false;$('empty').hidden=true;$('word-empty').hidden=true;$('deck-path').textContent=units[card.unit];if(frame.dataset.studyCardId!==card.id){frame.dataset.studyCardId=card.id;if(config.sharedFrame)mountSharedCard(card);else frame.src=safeURL(card.url);$('flip-card').textContent='显示答案';$('flip-card').setAttribute('aria-pressed','false')}if(hash)updateHash(card.id);draw({rebuild,ensure:true});if(close)drawer(false)}
function filter({deckChanged=false}={}){const q=lower(query.value.trim()),source=selectedDeck===''?all:(byUnit.get(Number(selectedDeck))||[]);visible=q?source.filter(card=>card.search.includes(q)):source;$('clear-search').hidden=!q;if(!visible.some(card=>card.id===selected))open(visible.find(card=>lower(card.word)===q)||visible[0],{rebuild:true});else draw({rebuild:true,ensure:deckChanged})}
function chooseDeck(key){selectedDeck=key;filter({deckChanged:true});if(selected)updateHash(selected)}
function decks(){const fragment=document.createDocumentFragment(),groups=new Map();function button(key,label,total){const b=node('button','deck-entry');b.type='button';b.dataset.deckKey=key;b.append(node('span','',label),node('span','entry-count',count(total)));b.onclick=()=>chooseDeck(key);return b}fragment.append(button('','全部卡组',all.length));units.forEach((path,index)=>{if(!byUnit.has(index))return;const parts=path.split('::').slice(1),label=parts.pop()||path,group=parts.join(' / ')||'未分组';if(!groups.has(group))groups.set(group,[]);groups.get(group).push({index,label,count:(byUnit.get(index)||[]).length})});for(const[group,entries]of groups){const details=node('details','unit-group');details.open=true;const summary=node('summary','',group);summary.append(node('span','entry-count',count(entries.reduce((total,x)=>total+x.count,0))));const lessons=node('ul','lesson-list');for(const entry of entries){const li=node('li');li.append(button(String(entry.index),entry.label,entry.count));lessons.append(li)}details.append(summary,lessons);fragment.append(details)}$('deck-tree').replaceChildren(fragment)}
function navigate(direction){if(!loaded)return;const card=visible[selectedIndex+direction];if(card)open(card)}
function flip(){if(frame.hidden)return;frame.contentDocument?.getElementById('study-flip')?.click();syncFlip()}
function syncFlip(){const b=frame.contentDocument?.getElementById('study-flip'),answer=b?.getAttribute('aria-pressed')==='true';$('flip-card').textContent=answer?'返回正面':'显示答案';$('flip-card').setAttribute('aria-pressed',String(answer));$('flip-card').disabled=!selected||sharedMountPending||!!b?.disabled}
frame.addEventListener('load',()=>{const b=frame.contentDocument?.getElementById('study-flip');if(b){b.style.display='none';b.addEventListener('click',syncFlip)}syncFlip()});
query.addEventListener('input',()=>filter());$('clear-search').onclick=()=>{query.value='';filter();query.focus()};$('previous-card').onclick=()=>navigate(-1);$('next-card').onclick=()=>navigate(1);$('flip-card').onclick=flip;
document.addEventListener('keydown',e=>{if(e.key==='Escape'){drawer(false);return}if(e.target.closest(interactive))return;if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();navigate(e.key==='ArrowRight'?1:-1)}if(e.code==='Space'&&!frame.hidden){e.preventDefault();flip()}});
window.addEventListener('message',e=>{if(e.source!==frame.contentWindow||e.origin!==location.origin)return;if(e.data?.type==='study-source-error'&&e.data.id===selected&&e.data.token===cardGeneration){resetSharedFrame();frame.src=safeURL(byId.get(selected).url);frame.dataset.mountMode='original-wrapper-fallback';const notice=$('card-render-notice');notice.hidden=false;notice.textContent='卡片资源载入异常，已重试原始页面。';return}if(e.data?.type==='study-side-state'&&e.data.id===selected){syncFlip();return}if(e.data?.type==='study-navigate'&&(e.data.direction===1||e.data.direction===-1))navigate(e.data.direction)});
window.addEventListener('hashchange',()=>{if(!loaded)return;const id=requested(),card=byId.get(id),deck=new URLSearchParams(location.hash.slice(1)).get('deck');if(!card)return;const desired=deck!==null&&card.listed?String(card.unit):'';if(id===selected&&desired===selectedDeck)return;query.value='';selectedDeck=desired;visible=!card.listed?[card]:(desired===''?all:byUnit.get(card.unit));offsetsForRows();open(card,{hash:false,rebuild:true})});
async function readNavigation(){if(config.navigationGzip&&typeof DecompressionStream==='function'){try{const r=await fetch(config.navigationGzip);if(!r.ok)throw Error('HTTP '+r.status);return await(r.headers.get('Content-Encoding')==='gzip'?r:new Response(r.body.pipeThrough(new DecompressionStream('gzip')))).json()}catch(error){console.warn('Study library compressed navigation unavailable:',error)}}const r=await fetch(config.navigation);if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
async function load(){if(loading)return;loading=true;$('retry').hidden=true;$('status').textContent='正在读取目录…';try{const data=await readNavigation();if(data.schema!=='study-navigation.v2'||!Array.isArray(data.cards)||!Array.isArray(data.units))throw Error('目录格式无效');units=data.units;entries=data.cards.map(row=>{if(!Array.isArray(row)||row.length!==8||typeof row[0]!=='string'||typeof row[1]!=='string'||typeof row[2]!=='string'||!Number.isInteger(row[3])||row[3]<0||row[3]>=units.length||typeof row[4]!=='string'||typeof row[5]!=='string'||(row[6]!==null&&(!Number.isInteger(row[6])||row[6]<0))||typeof row[7]!=='boolean')throw Error('目录条目无效');safeURL(row[4]);return{id:row[0],word:row[1],label:row[2],unit:row[3],url:row[4],summary:row[5],examples:row[6],listed:row[7],search:lower(row[1]+' '+row[5])}});all=entries.filter(card=>card.listed);byId=new Map();byUnit=new Map();for(const card of entries){if(byId.has(card.id))throw Error('目录卡片重复');byId.set(card.id,card);if(!card.listed)continue;if(!byUnit.has(card.unit))byUnit.set(card.unit,[]);byUnit.get(card.unit).push(card)}decks();loaded=true;visible=all;query.disabled=false;$('catalog-failure').hidden=true;$('library-summary').textContent=count(all.length)+' 张卡 · '+count(data.totals?.groups??byUnit.size)+' 个卡组 · '+count(data.totals?.examples||0)+(data.totals?.unknown_example_cards?' 条已索引例句':' 条例句');const guides=entries.filter(card=>!card.listed);if(guides.length){$('guide-card').hidden=false;$('guide-card').onclick=()=>{visible=guides;selectedDeck='';open(guides[0],{rebuild:true})}}const first=byId.get(requested())||all[0],deck=new URLSearchParams(location.hash.slice(1)).get('deck');if(first&&!first.listed)visible=[first];if(first&&deck!==null&&first.listed){selectedDeck=String(first.unit);visible=byUnit.get(first.unit)}open(first,{rebuild:true})}catch(error){$('catalog-failure').hidden=false;$('status').textContent='目录暂时无法读取，请重试。';$('retry').hidden=false;console.error('Study library navigation:',error)}finally{loading=false}}
$('retry').onclick=load;if(config.sharedFrame&&config.initial&&(!requested()||requested()===config.initial[0])){frame.dataset.studyCardId=config.initial[0];mountSharedCard({id:config.initial[0],url:config.initial[4]})}load();
})();'''
