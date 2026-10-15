"""Read-only, byte-proven delivery expansion for an isolated web experiment.

This module never changes source wrappers, media, notes or statistics. Existing
lossless inverse functions restore storage slices; the native browser renderer
still owns chunk projection, grouping, filters, reader links and validation.
"""
from __future__ import annotations

import hashlib
import html
import json
from collections import OrderedDict
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

from .slim_apkg_content import Slices, apply, attributes, restore
from .slim_shared_codec import expand, prepare_dictionary

_REGISTRY = re.compile(r'window\.AnkiSlimAssets=window\.AnkiSlimAssets\|\|\{\};window\.AnkiSlimAssets\["([a-f0-9]{64})"\]=(.*);', re.S)
_HISTORY = re.compile(r'window\.AnkiFinalHistoryEvidence=window\.AnkiFinalHistoryEvidence\|\|\{\};window\.AnkiFinalHistoryEvidence\["([a-f0-9]{64})"\]=(.*);', re.S)
_TAG = re.compile(r'<(?:script|style)\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>[\s\S]*?</(?:script|style)\s*>|<(?:link|iframe|pre)\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>', re.I)
AUDITED_CHILD_SCRIPTS = frozenset({
    'df06c994a3eb3afa497d8281fc37cbe243ee7c503cdd14b52bc0da15fcd0cd4f',
    '283a0c3850d180bc6a5c230eecd523b18ec3820e9632e76dea439ae584dd088c',
    'a653c115ca3c1b012a667c9d6563776dc4b4423f631ffc5370f3e05ee6d4e650',
    'f41a3916f837b335aa423a70442bd6e0a8c3cf3164d488b4511f2cb1202a3769',
    'a761d5a548050f1879f80fc4267610227a3bfedbb92364fb7349cb3f8d1f60aa',
})
AUDITED_NATIVE_MODULES = frozenset({
    '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',
    'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',
})


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


class ReadOnlyMedia:
    """Decode inert registrations with the existing exact shared-string codec."""
    def __init__(self, folder: Path, *, max_cache_bytes: int = 32 * 1024 * 1024):
        self.folder = folder.resolve(strict=True)
        self.values: OrderedDict[str, str] = OrderedDict()
        self.proofs: OrderedDict[str, dict] = OrderedDict()
        self.max_cache_bytes = max_cache_bytes
        self.cache_bytes = 0
        self.dictionaries = OrderedDict()
        self.dictionary_decodes = 0
        self.pending: set[str] = set()

    def _trim(self):
        while self.cache_bytes > self.max_cache_bytes and self.values:
            pin, value = self.values.popitem(last=False)
            self.cache_bytes -= sys.getsizeof(value) + sys.getsizeof(pin) + 128
        while (self.cache_bytes > self.max_cache_bytes or len(self.dictionaries) > 2) and self.dictionaries:
            _, (_, cost) = self.dictionaries.popitem(last=False)
            self.cache_bytes -= cost

    def dictionary(self, part):
        pin = part.get('sha256', '')
        if not re.fullmatch(r'[a-f0-9]{64}', pin) or part.get('src') != '_as_' + pin[:24] + '.js':
            raise ValueError('invalid shared dictionary reference')
        if pin in self.dictionaries:
            self.dictionaries.move_to_end(pin)
            return self.dictionaries[pin][0]
        bank = json.loads(self.read(part))
        if bank.get('schema') != 'anki-slim-shared-dictionary.v1':
            raise ValueError('invalid shared dictionary')
        dictionary = prepare_dictionary(bank['strings'])
        self.dictionary_decodes += 1
        cost = (sys.getsizeof(dictionary) + sum(sys.getsizeof(value) for value in dictionary)
                + sys.getsizeof(dictionary.indices.copy()) + len(dictionary) * sys.getsizeof(0)
                + sys.getsizeof(pin) + 128)
        if cost <= self.max_cache_bytes:
            self.dictionaries[pin] = dictionary, cost
            self.cache_bytes += cost
            self._trim()
        return dictionary

    def local(self, name: str) -> Path:
        url = urlsplit(name)
        filename = unquote(url.path)
        if url.scheme or url.netloc or url.query or Path(filename).name != filename:
            raise ValueError('delivery expansion requires a local resource basename')
        path = (self.folder / filename).resolve(strict=True)
        if not path.is_relative_to(self.folder) or not path.is_file():
            raise ValueError('delivery resource leaves the frozen media directory')
        return path

    def read(self, part: dict) -> str:
        pin = part.get('sha256', '')
        if not re.fullmatch(r'[a-f0-9]{64}', pin):
            raise ValueError('invalid exact content pin')
        if part.get('src') is not None and part['src'] != '_as_' + pin[:24] + '.js':
            raise ValueError('logical resource name differs from its exact pin')
        if pin in self.values:
            self.values.move_to_end(pin)
            return self.values[pin]
        if pin in self.pending:
            raise ValueError('cyclic packed registration')
        self.pending.add(pin)
        try:
            names = ['_ac_' + pin[:24] + '.js', '_as_' + pin[:24] + '.js']
            path = next((self.local(name) for name in names if (self.folder / name).is_file()), None)
            if path is None:
                raise ValueError('missing pinned local registration: ' + pin)
            raw = path.read_text()
            match = _REGISTRY.fullmatch(raw)
            if not match or match[1] != pin:
                raise ValueError('resource is not an inert exact registration')
            value = json.loads(match[2])
            if isinstance(value, dict):
                if value.get('schema') != 'anki-slim-shared-strings.v1':
                    raise ValueError('unsupported packed registration')
                value = expand(value['pieces'], self.dictionary(value['dict']))
            if not isinstance(value, str) or digest(value) != pin:
                raise ValueError('exact decoded string SHA differs')
            cost = sys.getsizeof(value) + sys.getsizeof(pin) + 128
            if cost <= self.max_cache_bytes:
                self.values[pin] = value
                self.cache_bytes += cost
                self._trim()
            self.proofs[pin] = {'name': path.name, 'resource_sha256': digest(raw), 'decoded_sha256': pin,
                                'resource_bytes': len(raw.encode()), 'decoded_bytes': len(value.encode())}
            while len(self.proofs) > 4096:
                self.proofs.popitem(last=False)
            return value
        finally:
            self.pending.remove(pin)

    def history(self, name: str, pin: str) -> str:
        if not re.fullmatch(r'[a-f0-9]{64}', pin) or not re.fullmatch(r'_af_[a-f0-9]{24}\.js', name):
            raise ValueError('invalid original history pin')
        raw = self.local(name).read_text()
        match = _HISTORY.fullmatch(raw)
        if not match or match[1] != pin:
            raise ValueError('history resource is not an inert registration')
        value = json.loads(match[2])
        if not isinstance(value, str) or digest(value) != pin:
            raise ValueError('history evidence byte SHA differs')
        self.proofs[pin] = {'name': name, 'resource_sha256': digest(raw), 'decoded_sha256': pin,
                            'resource_bytes': len(raw.encode()), 'decoded_bytes': len(value.encode())}
        while len(self.proofs) > 4096:
            self.proofs.popitem(last=False)
        return value


def inline_child(source: str, media: ReadOnlyMedia) -> dict:
    """Keep original viewer bytes and order, avoiding parser-blocking fetches."""
    if re.search(r'<(?:audio|video)\b|\bdocument\s*\.\s*(?:write|currentScript)\b', source, re.I):
        raise ValueError('child source needs its original lifecycle')
    edits, resources, scripts = [], [], []
    for match in _TAG.finditer(source):
        tag = match[0]
        opening = re.match(r'<[\w:-]+\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>', tag)[0]
        attrs = attributes(opening)
        if tag.lower().startswith('<link') and 'stylesheet' in attrs.get('rel', '').lower().split():
            if set(attrs) - {'rel', 'href'} or attrs['rel'].lower().split() != ['stylesheet']:
                raise ValueError('child stylesheet attributes require their original protocol')
            path = media.local(attrs['href'])
            raw = path.read_text()
            if '</style' in raw.lower() or re.search(r'@import\b', raw, re.I):
                raise ValueError('child stylesheet requires its original loading protocol')
            edits.append((match.start(), match.end(), '<style>' + raw + '</style>'))
            resources.append({'name': path.name, 'sha256': digest(raw), 'bytes': len(raw.encode()), 'kind': 'css'})
        elif tag.lower().startswith('<script'):
            if attrs.get('type', '').lower() in {'application/json', 'application/ld+json'}:
                continue
            if any(name in attrs for name in ('async', 'defer', 'nomodule')) or attrs.get('type', '') not in {'', 'text/javascript', 'application/javascript'}:
                raise ValueError('child script requires its original loading protocol')
            raw = media.local(attrs['src']).read_text() if attrs.get('src') else tag[len(opening):tag.lower().rfind('</script')]
            pin = digest(raw)
            if pin not in AUDITED_CHILD_SCRIPTS or '</script' in raw.lower():
                raise ValueError('child script has not been explicitly audited')
            if attrs.get('src'):
                edits.append((match.start(), match.end(), '<script>' + raw + '</script>'))
                resources.append({'name': attrs['src'], 'sha256': pin, 'bytes': len(raw.encode()), 'kind': 'js'})
            scripts.append(pin)
    return {'source': source, 'source_sha256': digest(source), 'html': apply(source, edits),
            'scripts': scripts, 'resources': resources}


def prepare_native_module(source: str) -> str:
    """Add bounded preparation hooks to two explicitly audited module versions.

    All original validators still run. A prepared token is reused only when its
    exact canonical input is identical; no validation result crosses a realm or
    resource version. Storage pins are verified by the original loader.
    """
    if digest(source) not in AUDITED_NATIVE_MODULES:
        raise ValueError('native module has not been explicitly audited')
    edits = {
        'window.AnkiReviewedChunkProjection = Object.freeze({ prepare: prepare, load: load, install: install });':
        '''var warmInput=null,warmResult=null;
  function prepareOnce(data){var raw=JSON.stringify(data);if(raw===warmInput)return warmResult;warmInput=raw;warmResult=prepare(data);warmResult.catch(function(){if(warmInput===raw){warmInput=null;warmResult=null;}});return warmResult;}
  window.AnkiReviewedChunkProjection = Object.freeze({ prepare: prepareOnce, load: load, install: install });''',
        'function digest(value) {\n    demand(window.crypto && window.crypto.subtle && window.TextEncoder,':
        '''var warmHashes=new Map(),warmHashBytes=0;
  function digest(value){if(warmHashes.has(value))return warmHashes.get(value);var job=uncachedDigest(value);if(value.length<=65536){warmHashes.set(value,job);warmHashBytes+=value.length*2;while(warmHashes.size>256||warmHashBytes>1048576){var oldest=warmHashes.keys().next().value;warmHashes.delete(oldest);warmHashBytes-=oldest.length*2;}job.catch(function(){if(warmHashes.get(value)===job){warmHashes.delete(value);warmHashBytes-=value.length*2;}});}return job;}
  function uncachedDigest(value) {
    demand(window.crypto && window.crypto.subtle && window.TextEncoder,''',
        'window.AnkiSharedReadingBankRuntime = Object.freeze({ install: install, sidecarSha256: SIDECAR_SHA });':
        '''window.AnkiSharedReadingBankRuntime = Object.freeze({ install: install, sidecarSha256: SIDECAR_SHA,
    warm:async function(metadata,texts){await buildIndex(metadata);await Promise.all(texts.map(digest));} });''',
        'window.AnkiSlimApkgHydrate = window.AnkiFinalApkgHydrate = hydrate;':
        '''window.AnkiSlimApkgHydrate = window.AnkiFinalApkgHydrate = hydrate;
  window.StudySlimWarm = Object.freeze({load:load});''',
    }
    for before, after in edits.items():
        if source.count(before) != 1:
            raise ValueError('audited module preparation boundary differs')
        source = source.replace(before, after)
    return source


def materialize_side(source: str, media: ReadOnlyMedia) -> dict:
    """Expand exact HTML slices while keeping native JSON/index pins separate."""
    preserved = {}
    native_markers, disclosure_markers = set(), set()

    def protect(raw):
        if '<!--study-preserved-payload:' in raw:
            raise ValueError('source collides with the private preservation boundary')
        tree = Slices(raw)
        edits = []
        protected_end = -1
        for node in tree.nodes:
            native = node.tag == 'script' and 'anki-final-reviewed-data' in node.classes
            disclosure = 'as-lazy' in node.classes and node.attrs.get('data-as-kind') == 'detail'
            if native or disclosure:
                original = raw[node.start:node.end]
                marker = '<!--study-preserved-payload:' + digest(original) + '-->'
                preserved[marker] = original
                (native_markers if native else disclosure_markers).add(marker)
                # Preserve a containing closed disclosure once. Its selected
                # descendants are already byte-protected by that outer span.
                if node.start >= protected_end:
                    edits.append((node.start, node.end, marker))
                    protected_end = node.end
        return apply(raw, edits)

    class ProtectedStore:
        def read(self, part):
            return protect(media.read(part))

    expanded = restore(protect(source), ProtectedStore())
    for marker, original in preserved.items():
        expanded = expanded.replace(marker, original)
    # The original renderer loads a complete historical text only when its
    # details is opened. Repeating that shared text into every pre can turn a
    # small current card into gigabytes; retain every original pre byte instead.
    histories = {}
    for match in _TAG.finditer(expanded):
        if not match[0].lower().startswith('<pre'):
            continue
        attrs = attributes(match[0])
        if 'data-native-history-media' not in attrs:
            continue
        name, pin = attrs['data-native-history-media'], attrs.get('data-native-history-sha', '')
        if not re.fullmatch(r'_af_[a-f0-9]{24}\.js', name) or not re.fullmatch(r'[a-f0-9]{64}', pin):
            raise ValueError('invalid retained original history reference')
        histories[name, pin] = histories.get((name, pin), 0) + 1
    registry = {}
    for node in Slices(expanded).nodes:
        if node.tag != 'script' or 'anki-final-reviewed-data' not in node.classes:
            continue
        for name in ('src', 'index-src'):
            key = 'data-as-' + name
            pin_key = 'data-as-' + ('sha' if name == 'src' else 'index-sha')
            if key in node.attrs:
                pin = node.attrs[pin_key]
                registry[pin] = media.read({'sha256': pin, 'src': node.attrs[key]})
        original = expanded[node.start:node.end]
        if original not in preserved.values():
            raise ValueError('current native proof markup changed during expansion')
    children = []
    for match in _TAG.finditer(expanded):
        if not match[0].lower().startswith('<iframe'):
            continue
        attrs = attributes(match[0])
        if set(attrs.get('class', '').split()) & {'etymology-source-frame', '_r17'}:
            if 'srcdoc' not in attrs:
                raise ValueError('etymology source is not an inline preserved viewer')
            children.append(inline_child(attrs['srcdoc'], media))
    return {'html': expanded, 'registry': registry, 'children': children,
            'proof': {'source_sha256': digest(source), 'expanded_sha256': digest(expanded),
                      'source_bytes': len(source.encode()), 'expanded_bytes': len(expanded.encode()),
                      'preserved_native_payloads': [digest(preserved[key]) for key in sorted(native_markers)],
                      'preserved_disclosure_payloads': [digest(preserved[key]) for key in sorted(disclosure_markers)],
                      'registry_pins': sorted(registry), 'history_pins': sorted({pin for _, pin in histories}),
                      'history_storage': 'original-native-lazy',
                      'history_references': [{'src': name, 'sha256': pin, 'count': count}
                                             for (name, pin), count in histories.items()],
                      'original_source_unmodified': True}}


# An isolated candidate. It is deliberately not the default export host until
# whole-card browser acceptance establishes that source layout no longer jumps.
PREPARED_FRAME_RUNTIME = r'''(function(){'use strict';
const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();
let side=document.getElementById('study-side'),current=null,accepted=0,sequence=0,answer=false,working=false,record=null,preparedTasks=[];const realms=[{node:side,key:null,ready:null,modules:new Set()}];document.body.style.overflow='hidden';
const clock=()=>performance.timeOrigin+performance.now(),encode=value=>String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
async function sha(text){const bytes=new TextEncoder().encode(text),crypto=parent.crypto.subtle?parent.crypto:window.crypto;return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('')}
function report(){if(!current?.metricsAsset)return;let out=document.getElementById('study-render-metrics');if(!out){out=document.createElement('output');out.id='study-render-metrics';out.hidden=true;document.body.append(out)}out.textContent=JSON.stringify(records)}
function state(){if(!current)return;parent.postMessage({type:'study-side-state',id:current.id,token:accepted,answer},origin)}
function key(event){if(event.target.closest('input,select,textarea,button,summary,a,[contenteditable]'))return;if(event.code==='Space'){event.preventDefault();flip.click()}if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();parent.postMessage({type:'study-navigate',direction:event.key==='ArrowRight'?1:-1},origin)}}
function execute(doc,code,pin){const script=doc.createElement('script'),win=doc.defaultView;let failure=null;const catchError=event=>{failure=event.error||Error(event.message||'Authored script execution failed')};script.textContent=current?.metricsAsset?code+'\n//# sourceURL=study-source-'+(pin||'anonymous')+'.js':code;win.addEventListener('error',catchError);try{doc.head.append(script)}finally{script.remove();win.removeEventListener('error',catchError)}if(failure)throw failure}
function stage(node){node.removeAttribute('id');node.setAttribute('aria-hidden','true');node.inert=true;node.style.cssText='position:absolute;left:0;top:calc(100vh + 100px);display:block;width:100%;height:100%;border:0'}
// Only this exact, already hash-verified native module shape is adapted.
// The original process/validation/annotation code and matched-view snapshot
// phase remain unchanged; non-matches do not allocate offsets/node records.
function adaptNativeProjectionLookup(code,originalPin){
 const approved=["5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"];if(!approved.includes(originalPin))return code;
 const edits=[["  function pairs(doc) {","  function projectionLookupView(container, nativeChinese) {\n    var text = container.textContent, first = container.firstChild;\n    if (nativeChinese && first && first.nodeType === 1 && first.matches('span.translate-tag') && first.textContent === '翻译') {\n      text = text.slice(first.textContent.length);\n      if (first.nextSibling && first.nextSibling.nodeType === 3 && first.nextSibling.data.startsWith(' ')) text = text.slice(1);\n    }\n    return { container: container, text: text };\n  }\n  function pairs(doc, index, processed) {\n    var isHTML = (doc.ownerDocument || doc).contentType === 'text/html';"],["      if (en && zh) result.push({ root: root, en: view(en, false), zh: view(zh, !sf) });","      if (en && zh) {\n        var ev = isHTML ? projectionLookupView(en, false) : view(en, false), zv = isHTML ? projectionLookupView(zh, !sf) : view(zh, !sf);\n        if (isHTML && processed.get(root) === undefined && index.has(key(ev.text, zv.text))) {\n          ev = view(en, false); zv = view(zh, !sf);\n        }\n        result.push({ root: root, en: ev, zh: zv });\n      }"],["      try { pairs(doc).forEach(function (pair) { try { process(pair); } catch (error) { stats.errors.push(error.message); if (options.onError) options.onError(error); } }); }","      try { pairs(doc, index, processed).forEach(function (pair) { try { process(pair); } catch (error) { stats.errors.push(error.message); if (options.onError) options.onError(error); } }); }"]];
 edits.push(['warmHashes.size>256||warmHashBytes>1048576','warmHashes.size>2048||warmHashBytes>1048576']);
 if(code.includes('function projectionLookupView(')||edits.some(([before])=>code.split(before).length!==2))throw Error('Audited native projection lookup boundary differs');
 for(const [before,after]of edits)code=code.replace(before,after);return code;
}
// This verified author's compact aliases all begin with _r. Keep its original
// per-element decoding and source order, without visiting ordinary classes.
function adaptAuthoredCompactClassScan(code,originalPin){
 if(originalPin!=='12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373')return code;
 const before="document.querySelectorAll('[class]')",after="document.querySelectorAll('[class*=\"_r\"]')";
 if(code.split(before).length!==2)throw Error('Audited compact class scanner boundary differs');
 return code.replace(before,after);
}
// A source module must reuse the already verified host digest on HTTP LAN.
// Its own legacy fallback then leaves that digest in place. BufferSource
// snapshotting, algorithm errors and worker limits belong to the host API.
function bridgeRealmDigest(win){if(win.crypto?.subtle)return false;const upstream=parent.crypto?.subtle;if(!win.crypto||typeof upstream?.digest!=='function')return false;const bridge={digest:function(algorithm,data){return Reflect.apply(upstream.digest,upstream,[algorithm,data])}};try{Object.defineProperty(win.crypto,'subtle',{value:bridge,configurable:true});return true}catch{return false}}
async function realm(base,fingerprint,valid){const cohortKey=JSON.stringify([base,fingerprint]);if(!valid())return null;let entry=realms.find(item=>item.node!==side);if(!entry){entry={node:null,key:null,ready:null,modules:new Set()};realms.push(entry)}if(entry.key===cohortKey&&entry.ready&&entry.node?.isConnected&&(!entry.doc||entry.node.contentDocument===entry.doc))return entry.ready;entry.key=cohortKey;entry.modules=new Set();entry.doc=null;entry.win=null;entry.packet=null;entry.viewToken=null;const fresh=document.createElement('iframe'),realmId=String(accepted)+'-'+String(sequence)+'-'+String(Date.now());fresh.title='当前卡片准备';stage(fresh);const old=entry.node;entry.node=fresh;entry.ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Prepared realm initialization timed out')),8000);fresh.onload=()=>{if(entry.node!==fresh){clearTimeout(timer);resolve(null);return}const win=fresh.contentWindow,doc=fresh.contentDocument;if(!doc?.body||doc.documentElement.dataset.studyRealm!==realmId||doc.readyState!=='complete')return;clearTimeout(timer);bridgeRealmDigest(win);doc.addEventListener('keydown',key);if(current?.metricsAsset)win.addEventListener('error',event=>{entry.row?.events.push({event:'realm-error',at:clock(),message:event.message,filename:event.filename,line:event.lineno,stack:event.error?.stack,body:!!doc.body,connected:!!win.frameElement?.isConnected,currentDocument:entry.node.contentDocument===doc});report()});win.StudyPreparedDiagnostic=detail=>{if(current?.metricsAsset){entry.row?.events.push({at:clock(),...detail});report()}};execute(doc,'('+installCigen.toString()+')(window,document);','owned-cigen-bridge');entry.win=win;entry.doc=doc;resolve(entry)}});if(!valid())return null;if(old)old.replaceWith(fresh);else document.body.append(fresh);fresh.srcdoc='<!doctype html><html data-study-realm="'+encode(realmId)+'"><head><base href="'+encode(base)+'"></head><body></body></html>';return entry.ready}

async function resource(url,pin){const key=url+'|'+pin;if(scriptCache.has(key))return scriptCache.get(key);const task=(async()=>{const response=await fetch(url,{headers:{Range:'bytes=0-'}});if(!response.ok)throw Error('Prepared resource HTTP '+response.status);let total=null;if(response.status===206){const range=/^bytes 0-(\d+)\/(\d+)$/i.exec(response.headers.get('Content-Range')||'');if(!range||!Number.isSafeInteger(Number(range[2]))||Number(range[2])<=0||Number(range[1])!==Number(range[2])-1)throw Error('Prepared resource range is not complete');total=Number(range[2])}const text=await response.text();if(total!==null&&new TextEncoder().encode(text).byteLength!==total)throw Error('Prepared resource byte length differs from complete range');if(await sha(text)!==pin)throw Error('Prepared resource byte SHA differs');return text})();scriptCache.set(key,task);task.catch(()=>{if(scriptCache.get(key)===task)scriptCache.delete(key)});while(scriptCache.size>24)scriptCache.delete(scriptCache.keys().next().value);return task}
function installCigen(win,doc){const known=new Map(),selector='iframe.etymology-source-frame';let scheduled=false,batchDepth=0,dirty=false;
 function layout(frame){if(batchDepth){dirty=true;return}const entry=known.get(frame);if(!entry||!doc.contains(frame)||frame.getBoundingClientRect().width<=0)return;const meaning=frame.closest('.meaning-section'),sample=meaning?.querySelector('.form-row,.primary-definition .field-content');if(sample){const text=win.getComputedStyle(sample);frame.style.fontSize=text.fontSize;frame.style.lineHeight=text.lineHeight}const style=win.getComputedStyle(frame),title=meaning?.querySelector('.primary-definition .field-title'),callout=meaning?.querySelector('.field-callout'),tag=meaning?.querySelector('.level-list li'),font={fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color},metrics={'--ety-text-size':style.fontSize,'--ety-text-line':style.lineHeight};if(title){const t=win.getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':t.fontSize,'--ety-title-line':t.lineHeight,'--ety-title-gap':t.marginBottom})}if(callout)metrics['--ety-section-space']=win.getComputedStyle(callout).paddingTop;if(tag){const t=win.getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':t.fontSize,'--ety-tag-line':t.lineHeight,'--ety-tag-padding':t.padding,'--ety-tag-gap':win.getComputedStyle(tag.parentElement).gap})}const signature=JSON.stringify([Math.round(frame.getBoundingClientRect().width),font,metrics]);if(signature===entry.signature)return;entry.signature=signature;entry.ready=false;entry.readySignature=null;frame.contentWindow.postMessage({type:'cigen:layout',font,studySignature:signature},'*');frame.contentWindow.postMessage({type:'cigen:theme',metrics,studySignature:signature},'*')}
 const sizes=new win.ResizeObserver(entries=>{for(const entry of entries)layout(entry.target)});
 function refresh(){for(const [frame]of known)if(!doc.contains(frame)){sizes.unobserve(frame);known.delete(frame)}for(const frame of doc.querySelectorAll(selector))if(!known.has(frame)){known.set(frame,{signature:null,height:null,inits:0,ready:false,error:null});sizes.observe(frame);frame.addEventListener('load',()=>{const entry=known.get(frame);if(entry){entry.signature=null;entry.inits++;layout(frame)}})}if(batchDepth){dirty=true;return}for(const frame of known.keys())layout(frame)}
 function batch(action){batchDepth++;dirty=true;try{refresh();return action()}finally{if(--batchDepth===0&&dirty){dirty=false;refresh()}}}
 new win.MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh()})}).observe(doc.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden']});win.addEventListener('resize',refresh);win.addEventListener('message',event=>{const data=event.data;if(!['cigen:size','study-child-ready','study-child-error','study-child-phase'].includes(data?.type))return;const frame=Array.from(known.keys()).find(node=>node.contentWindow===event.source);if(!frame)return;const entry=known.get(frame);if(data.type!=='cigen:size'){if(data.type==='study-child-phase'){entry.phases=entry.phases||[];entry.phases.push(data);if(entry.phases.length>12)entry.phases.splice(6,1);return}entry.lastReady=data;if(data.token!==frame.dataset.studyChildToken||data.sourceSha!==frame.dataset.studyChildSource)return;if(data.type==='study-child-error'){entry.error=Error((data.message||'Original child initialization failed')+' ['+(data.filename||'')+':'+(data.line||'')+']');win.StudyPreparedDiagnostic?.({event:'child-error',...data});return}if(entry.error)return;if(data.signature!==entry.signature||!Number.isFinite(data.height)||data.height<=0||Math.abs(data.width-frame.getBoundingClientRect().width)>1)return;entry.ready=true;entry.readySignature=data.signature;entry.readyWidth=data.width}if(!Number.isFinite(data.height)||data.height<=0)return;entry.height=data.height;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value});win.__ankiCigenFrames={refresh,batch,known};
}
function copyAttributes(from,to){for(const value of Array.from(to.attributes))to.removeAttribute(value.name);for(const value of from.attributes)to.setAttribute(value.name,value.value)}
function snapshot(doc,includeText=true){if(!doc.defaultView?.frameElement?.isConnected)return null;const major=Array.from(doc.querySelectorAll('.exam-frequency,.primary-definition,.secondary-definition,.etymology-section,.examples-section,iframe.etymology-source-frame')).filter(node=>node.getClientRects().length).map((node,index)=>{const box=node.getBoundingClientRect(),entry=node.tagName==='IFRAME'?doc.defaultView.__ankiCigenFrames.known.get(node):null;return{index,tag:node.tagName,classes:node.className,top:Math.round(box.top*10)/10,height:Math.round(box.height*10)/10,width:Math.round(box.width*10)/10,childHeight:entry?.height||null,childInits:entry?.inits||0}});return{bodyHeight:Math.round(doc.body.getBoundingClientRect().height*10)/10,textLength:includeText?(doc.body.innerText?.length||doc.body.textContent.length):null,nativeStates:Array.from(doc.querySelectorAll('script.anki-final-reviewed-data')).slice(0,1).map(n=>n.dataset.nativeState||'uninitialized'),major}}
function observe(doc,row,token){if(!current?.metricsAsset)return;const start=performance.now(),samples=[];let previous=start,lastSignature='',lastChange=start,stableSince=null,nativeReadyAt=null,first=null,last=null,frames=0,changes=0,maxFrameGap=0;function frame(now){if(record!==row||doc!==side.contentDocument)return;frames++;maxFrameGap=Math.max(maxFrameGap,now-previous);previous=now;const value=snapshot(doc);if(!value){row.events.push({event:'inactive-document-observation',at:clock()});report();return}const signature=JSON.stringify(value);if(!first&&value.bodyHeight>0&&value.textLength>0){first={at:clock(),...value};row.events.push({event:'first-visible-animation-frame',at:clock(),...value})}if(signature!==lastSignature){lastSignature=signature;lastChange=now;stableSince=null;changes++;if(samples.length<20)samples.push({at:clock(),...value})}const ready=value.textLength>0&&value.nativeStates.every(state=>state==='ready')&&value.major.filter(v=>v.tag==='IFRAME').every(v=>v.childHeight!==null&&v.height>=v.childHeight-1);if(ready&&nativeReadyAt===null)nativeReadyAt=clock();if(ready&&now-lastChange>=200&&stableSince===null)stableSince=performance.timeOrigin+lastChange;last=value;row.wholeCard={start:performance.timeOrigin+start,first,final:last,frames,changes,maxFrameGap,nativeReadyAt,stableSince,samples};report();if(now-start<2500)requestAnimationFrame(frame)}requestAnimationFrame(frame)}
function childReadiness(config){let fontEpoch=0,phaseSignature=null;function phase(name,extra={}){if(!config.debug)return;const value={phase:name,...extra},signature=JSON.stringify(value);if(signature===phaseSignature)return;phaseSignature=signature;parent.postMessage({type:'study-child-phase',token:config.token,sourceSha:config.sourceSha,...value},'*')}let loaded=document.readyState==='complete',fontReady=false,layout=null,theme=null,scheduled=false,last=null,count=0,sent=null;const send=(type,extra)=>parent.postMessage({type,token:config.token,sourceSha:config.sourceSha,...extra},'*');function check(){scheduled=false;phase('measure',{loaded,fontReady,layout,theme,body:!!document.body,imagesPending:Array.from(document.images).filter(image=>!image.complete).length});if(!loaded||!fontReady||document.fonts?.status==='loading'||!layout||layout!==theme||!document.body)return;if(Array.from(document.images).some(image=>!image.complete))return;const height=Math.ceil(document.body.getBoundingClientRect().height)+1,width=document.documentElement.getBoundingClientRect().width,signature=JSON.stringify([height,width,layout]);phase('measured',{height,width,count,signature:layout});if(signature===last)count++;else{last=signature;count=0}if(height>1&&count>=2){if(sent!==signature){sent=signature;send('study-child-ready',{height,width,signature:layout})}}else request()}function request(){if(scheduled)return;scheduled=true;setTimeout(check,0)}function fonts(){const epoch=++fontEpoch;fontReady=false;queueMicrotask(()=>{document.body?.getBoundingClientRect();Promise.resolve(document.fonts?.ready).then(()=>{if(epoch!==fontEpoch)return;fontReady=document.fonts?.status!=='loading';request()})})}window.addEventListener('load',()=>{loaded=true;if(document.body&&typeof ResizeObserver==='function')new ResizeObserver(request).observe(document.body);fonts()},{once:true});window.addEventListener('message',event=>{if(event.source!==parent||!event.data?.studySignature)return;if(event.data.type==='cigen:layout')layout=event.data.studySignature;if(event.data.type==='cigen:theme')theme=event.data.studySignature;count=0;last=null;fonts()});window.addEventListener('error',event=>send('study-child-error',{message:event.message||'Original child resource failed',filename:event.filename,line:event.lineno,stack:event.error?.stack}),true);document.addEventListener('load',request,true);document.fonts?.addEventListener?.('loadingdone',fonts);document.fonts?.addEventListener?.('loadingerror',fonts);if(loaded)fonts();phase('installed',{state:document.readyState})}
function waitPrepared(entry,valid){const began=performance.now();let previous=null,same=0;return new Promise((resolve,reject)=>{function check(){if(!valid()){resolve(false);return}const {doc,win}=entry,frames=Array.from(doc.querySelectorAll('iframe.etymology-source-frame')).filter(frame=>frame.getBoundingClientRect().width>0);for(const frame of frames){const state=win.__ankiCigenFrames.known.get(frame);if(state?.error){reject(state.error);return}}const native=Array.from(doc.querySelectorAll('script.anki-final-reviewed-data')).slice(0,1).map(node=>node.dataset.nativeState||'preparing');if(native.includes('failed')){reject(Error(doc.querySelector('.anki-final-status')?.textContent||'Original native validation failed'));return}const ready=native.every(value=>value==='ready')&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return state?.ready&&state.readySignature===state.signature&&Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1})&&doc.fonts?.status!=='loading';const signature=JSON.stringify(snapshot(doc,false));if(ready&&signature===previous)same++;else same=0;previous=signature;if(ready&&same>=2){resolve(true);return}if(performance.now()-began>10000){reject(Error('Connected original card preparation timed out: '+JSON.stringify({native,fonts:doc.fonts?.status,frames:frames.map(frame=>({width:frame.getBoundingClientRect().width,proof:frame.dataset.studyChildSource,token:frame.dataset.studyChildToken,...win.__ankiCigenFrames.known.get(frame)}))})));return}requestAnimationFrame(check)}requestAnimationFrame(check)})}
async function prepareView(packet,index,requestedAt){const token=++sequence,prepared=packet.prepared?.sides?.[index];if(!prepared)throw Error('Missing proven prepared side');const valid=()=>packet===current&&token===sequence;
 const row={card:packet.id,side:index?'back-preparing':'front-preparing',token:accepted+'-'+token,request:requestedAt,reason:'connected-preparation',events:[]};if(packet.metricsAsset){records.push(row);if(records.length>20)records.shift();report();}
 const hashes=await Promise.all([sha(packet.sides[index]),sha(prepared.html)]);if(hashes[0]!==prepared.proof.source_sha256||hashes[1]!==prepared.proof.expanded_sha256)throw Error('Prepared body differs from its source proof');if(!valid())return null;
 const parsed=new DOMParser().parseFromString(prepared.html,'text/html');if(parsed.querySelector('[autoplay]'))throw Error('Autoplay retains its original wrapper');if(/<noscript\b/i.test(prepared.html))throw Error('Prepared parsing retains original noscript semantics');parsed.querySelector('base').href=packet.base;
 const scripts=[];for(const script of parsed.scripts){const type=(script.getAttribute('type')||'').trim().toLowerCase();if(['application/json','application/ld+json'].includes(type))continue;if(!['','text/javascript','application/javascript'].includes(type)||['async','defer','nomodule'].some(name=>script.hasAttribute(name)))throw Error('Prepared execution mode is not audited');let code,pin=script.getAttribute('src')?packet.policy.external[script.getAttribute('src')]:null;if(script.getAttribute('src')){if(!pin)throw Error('Unknown prepared script');const module=packet.prepared.modules?.[pin];if(module){if(module.original_sha256!==pin)throw Error('Prepared module source SHA differs');code=null}else code=await resource(new URL(script.getAttribute('src'),packet.base).href,pin)}else{const rule=packet.policy.inline.find(rule=>rule.source===script.textContent);if(!rule&&script.textContent.trim())throw Error('Unknown prepared inline script');code=script.textContent;pin=rule?.sha256||''}if(code!==null)code=adaptAuthoredCompactClassScan(code,pin);scripts.push({node:script,code,pin});script.type='application/x-study-inert'}
 // Source styles and module bytes are prepared before the next authored body;
 // there is no new visible half-card waiting for external script downloads.
 for(const link of parsed.querySelectorAll('link[rel~="stylesheet"][href]')){if(Array.from(link.attributes).some(a=>!['rel','href'].includes(a.name))||link.rel.trim().toLowerCase().split(/\s+/).join(' ')!=='stylesheet')throw Error('Prepared stylesheet attributes retain their original protocol');const url=new URL(link.getAttribute('href'),packet.base).href,response=await fetch(url);if(!response.ok)throw Error('Prepared stylesheet HTTP '+response.status);const raw=await response.text();if(/@import\b|<\/style/i.test(raw))throw Error('Prepared stylesheet needs its original lifecycle');const style=parsed.createElement('style');style.textContent=raw;link.replaceWith(style)}
 if(!valid())return null;const fingerprint=JSON.stringify(Object.entries(packet.prepared.modules||{}).sort(([a],[b])=>a.localeCompare(b))),active=await realm(packet.base,fingerprint,valid);if(!valid()||!active)return null;const {win,doc}=active;active.row=row;active.packet=packet;active.viewToken=token;
 for(const item of scripts){const module=packet.prepared.modules?.[item.pin];if(module&&!active.modules.has(item.pin)){const code=await resource(new URL(module.src,document.baseURI).href,module.sha256);if(!valid())return null;execute(doc,adaptNativeProjectionLookup(code,item.pin),item.pin+'-prepared-'+module.sha256);active.modules.add(item.pin)}}
 win.AnkiSlimDecode?.(parsed);for(const [pin,raw]of Object.entries(prepared.registry)){if(await sha(raw)!==pin)throw Error('Prepared native registration SHA differs');win.AnkiSlimAssets=win.AnkiSlimAssets||{};win.AnkiSlimAssets[pin]=raw}if(!valid())return null;
 for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){if(!win.StudySlimWarm)throw Error('Prepared native module is unavailable');for(const pair of [['asSrc','asSha'],['asIndexSrc','asIndexSha']])if(payload.dataset[pair[0]])await win.StudySlimWarm.load({src:payload.dataset[pair[0]],sha256:payload.dataset[pair[1]]});const raw=payload.dataset.asSha?prepared.registry[payload.dataset.asSha]:payload.textContent;await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw));await win.AnkiSharedReadingBankRuntime.warm(win.AnkiFinalReadingMetadata,Array.from(parsed.querySelectorAll('.sf-en,.example-text'),node=>node.textContent))}if(!valid())return null;
 const frames=Array.from(parsed.querySelectorAll('iframe.etymology-source-frame'));if(frames.length!==prepared.children.length)throw Error('Prepared child source count differs');frames.forEach((frame,n)=>{const child=prepared.children[n],section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section'),levels=meaning&&Array.from(meaning.children).find(node=>node.classList.contains('level-section'));if(levels)levels.after(section);if(section)section.style.margin='.2rem 0 .65rem';let childHTML=child.html;if(packet.metricsAsset){let ordinal=0;childHTML=childHTML.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,code,close)=>open+code+'\n//# sourceURL=study-child-'+child.scripts[ordinal++]+'.js\n'+close)}const base='<base href="'+encode(packet.base)+'">';if(/<base\b/i.test(childHTML))childHTML=childHTML.replace(/<base\b[^>]*>/i,base);else childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+base);const childToken=String(accepted)+'-'+String(token)+'-'+n,head='<scr'+'ipt>('+childReadiness.toString()+')('+JSON.stringify({token:childToken,sourceSha:child.source_sha256,debug:!!packet.metricsAsset})+');</scr'+'ipt>';childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+head);frame.dataset.studyChildToken=childToken;frame.dataset.studyChildSource=child.source_sha256;frame.setAttribute('srcdoc',childHTML);frame.removeAttribute('data-web-etymology-srcdoc')});
 if(!valid())return null;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;
 const head=doc.createDocumentFragment(),body=doc.createDocumentFragment();for(const node of Array.from(parsed.head.childNodes))head.append(doc.adoptNode(node));for(const node of Array.from(parsed.body.childNodes))body.append(doc.adoptNode(node));for(const audio of body.querySelectorAll('audio,video')){const play=audio.play,details=()=>({src:audio.src,currentSrc:audio.currentSrc,srcAttribute:audio.getAttribute('src'),ready:audio.readyState,network:audio.networkState,connected:audio.isConnected,ownerCurrent:audio.ownerDocument===doc,ownRealmPrototype:audio instanceof win.HTMLMediaElement,mediaError:audio.error?.message});if(packet.metricsAsset){row.audio=row.audio||{attempts:0,denied:0,errors:[],events:[]};for(const event of ['loadstart','loadedmetadata','canplay','error','abort','emptied','stalled','suspend'])audio.addEventListener(event,()=>{row.audio.events.push({event,at:clock(),...details()});if(row.audio.events.length>24)row.audio.events.shift();report()})}Object.defineProperty(audio,'play',{configurable:true,writable:true,value:function(...args){if(packet.metricsAsset){row.audio.attempts++;row.audio.userActivation=win.navigator.userActivation?.isActive;row.audio.call={...details(),play:String(play).slice(0,180),targetRealmPlay:String(win.HTMLMediaElement.prototype.play).slice(0,180)};report()}if(active.node!==side){row.audioAttempts=(row.audioAttempts||0)+1;if(row.audio)row.audio.denied++;return Promise.reject(Error('Prepared media cannot play before commit'))}try{const result=Reflect.apply(play,this,args);if(!packet.metricsAsset)return result;return Promise.resolve(result).catch(error=>{row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});if(row.audio.errors.length>4)row.audio.errors.shift();report();throw error})}catch(error){if(row.audio){row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});report()}throw error}}})}copyAttributes(parsed.documentElement,doc.documentElement);copyAttributes(parsed.body,doc.body);doc.head.replaceChildren(head);doc.body.replaceChildren(body);win.scrollTo(0,0);
 // Authored scripts still run in source order. Their repeated calls to our
 // bridge are coalesced so they cannot force intermediate whole-card layouts.
 const authoredComplete=win.__ankiCigenFrames.batch(()=>{for(const item of scripts){if(!valid())return false;if(packet.prepared.modules?.[item.pin]){item.node.remove();continue}execute(doc,item.code,item.pin);item.node.remove()}return true});if(!authoredComplete||!valid())return null;
 // Media adopted from the inert parser may retain a rejected temporary-URL
 // selection. Reset only after the final base and complete body are connected;
 // load() preserves authored preload/src and never starts playback.
 for(const media of doc.querySelectorAll('audio,video'))if(media.getAttribute('src')||media.querySelector('source[src]'))media.load();
 if(packet.metricsAsset&&packet.audioDiagnostics)installAudioDiagnostic(win,doc,row);if(!valid())return null;
 if(packet.metricsAsset){row.preparedBodyAt=clock();row.events.push({event:'connected-prepared-body',at:clock(),...snapshot(doc)});}if(!await waitPrepared(active,valid))return null;if(packet.metricsAsset){row.readyAt=clock();row.prepared=snapshot(doc);report();}return{entry:active,doc,packet,index,row,token,geometry:JSON.stringify(snapshot(doc,false))};
}
function installAudioDiagnostic(win,doc,row){const box=doc.createElement('div');box.style.cssText='position:fixed;bottom:4px;right:4px;z-index:999999;background:white;border:1px solid #aaa;padding:5px';for(const [label,reset]of [['诊断：原生播放韦氏',false],['诊断：load 后播放韦氏',true]]){const button=doc.createElement('button');button.textContent=label;button.onclick=()=>{const audio=doc.querySelector('audio[data-dictionary-source="webster"]')||doc.querySelector('audio');if(!audio)return;const log=extra=>{row.audio.diagnostic={reset,src:audio.src,currentSrc:audio.currentSrc,ready:audio.readyState,network:audio.networkState,...extra};report()};try{if(reset)audio.load();const job=reset?audio.play():Reflect.apply(win.HTMLMediaElement.prototype.play,audio,[]);Promise.resolve(job).then(()=>log({result:'resolved',duration:audio.duration})).catch(error=>log({result:'rejected',name:error.name,message:error.message}))}catch(error){log({result:'threw',name:error.name,message:error.message})}};box.append(button)}doc.body.append(box)}
function clearOld(entry){if(!entry?.doc)return;const {win,doc}=entry;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();doc.body.replaceChildren();win.__ankiCigenFrames.refresh();win.__ankiCardChunkState=null;entry.packet=null;entry.viewToken=null}
function ownsView(view){return !!view&&view.packet===current&&view.entry.packet===view.packet&&view.entry.viewToken===view.token&&view.entry.doc===view.doc&&view.entry.node.isConnected&&view.entry.node.contentDocument===view.doc}
function currentPreparation(view){if(!ownsView(view)||view.doc.fonts?.status==='loading')return false;view.entry.win.__ankiCigenFrames.refresh();for(const frame of view.doc.querySelectorAll('iframe.etymology-source-frame')){if(frame.getBoundingClientRect().width<=0)continue;const state=view.entry.win.__ankiCigenFrames.known.get(frame);if(!state?.ready||state.readySignature!==state.signature||Math.abs(state.readyWidth-frame.getBoundingClientRect().width)>1)return false}return view.geometry===JSON.stringify(snapshot(view.doc,false))}
function promote(view,requestedAt){if(!currentPreparation(view))return false;const previous=realms.find(entry=>entry.node===side);if(previous&&previous!==view.entry)stage(previous.node);side=view.entry.node;side.id='study-side';side.inert=false;side.removeAttribute('aria-hidden');side.style.cssText='display:block;width:100%;height:100%;border:0';answer=!!view.index;side.title=answer?'学习卡片背面':'学习卡片正面';record=current.metricsAsset?view.row:null;if(record){record.side=answer?'back':'front';record.request=requestedAt;record.mount=clock();record.events.push({event:'complete-card-commit',at:clock(),...snapshot(view.doc)});}side.dataset.mountReason='connected-complete-card';side.dataset.cardId=current.id;flip.textContent=answer?'返回正面':'显示答案';flip.setAttribute('aria-pressed',String(answer));working=false;flip.disabled=false;state();observe(view.doc,record,view.token);if(previous!==view.entry){for(const audio of previous?.doc?.querySelectorAll('audio,video')||[])audio.pause();if(previous?.packet!==view.packet)clearOld(previous)}report();return true}
function getView(packet,index,requestedAt){const existing=preparedTasks[index];if(existing?.packet===packet&&(!existing.view||ownsView(existing.view)))return existing.promise;const task={packet,index,promise:null,view:null};task.promise=prepareView(packet,index,requestedAt).then(view=>{task.view=view;return view});preparedTasks[index]=task;task.promise.catch(()=>{});return task.promise}
async function show(requestedAt,index){const packet=current;working=true;flip.disabled=true;state();const view=await getView(packet,index,requestedAt);if(current!==packet||!view)return false;if(!currentPreparation(view)){if(!await waitPrepared(view.entry,()=>ownsView(view)))return false;view.geometry=JSON.stringify(snapshot(view.doc,false))}const result=promote(view,requestedAt);if(result&&!index){const task=getView(packet,1,clock());task.catch(error=>{if(packet===current&&packet.metricsAsset){const row={card:packet.id,side:'back-preparation-failed',message:String(error.message||error)};records.push(row);report()}})}return result}

function fail(error,packet,token){if(current!==packet||token!==accepted)return;working=false;flip.disabled=false;parent.postMessage({type:'study-source-error',id:packet.id,token:accepted,message:String(error.message||error),stack:error.stack},origin)}
flip.onclick=()=>{if(!current||working)return;const packet=current,token=accepted;show(clock(),answer?0:1).catch(error=>fail(error,packet,token))};document.addEventListener('keydown',key);
window.StudySharedFrame={async mount(packet){if(!packet||!Number.isSafeInteger(packet.token)||packet.token<=accepted||!packet.prepared||!Array.isArray(packet.sides)||packet.sides.length!==2)return false;const base=new URL(packet.base);if(base.origin!==origin)throw Error('Invalid prepared resource base');accepted=packet.token;current=packet;preparedTasks=[];return show(packet.requestedAt,0)}};
})();'''


def prepared_frame_html() -> str:
    from .study_catalog_web import shared_frame_html, DEFER_SCRIPTS_RUNTIME, SHARED_FRAME_RUNTIME, LAN_SHA256_RUNTIME
    original = shared_frame_html()
    runtime = DEFER_SCRIPTS_RUNTIME + '\n' + SHARED_FRAME_RUNTIME
    if '</script' in PREPARED_FRAME_RUNTIME.lower():
        raise ValueError('prepared runtime crosses the HTML script boundary')
    return original.replace(runtime, LAN_SHA256_RUNTIME + '\n' + PREPARED_FRAME_RUNTIME)


class UnsupportedDelivery(ValueError):
    """An authored page needs its original browser execution protocol."""


def _eligible_side(source: str, policy: dict) -> None:
    """Require explicit source audits, not heuristic JavaScript safety."""
    from .study_catalog_web import SharedMountAudit, _MountScriptTag
    if re.search(r'<noscript\b|\bautoplay(?:\s|=|>)', source, re.I):
        raise UnsupportedDelivery('authored noscript/autoplay lifecycle')
    inline = {rule['source'] for rule in policy.get('inline', ())}
    external = policy.get('external', {})
    for match in SharedMountAudit.pattern.finditer(source):
        attrs = _MountScriptTag(match[1]).attributes
        mode = (attrs.get('type') or '').strip().lower()
        if mode in {'application/json', 'application/ld+json'}:
            continue
        if mode not in {'', 'text/javascript', 'application/javascript'} or set(attrs) & {'async', 'defer', 'nomodule'}:
            raise UnsupportedDelivery('authored script execution mode')
        if attrs.get('src'):
            if attrs['src'] not in external:
                raise UnsupportedDelivery('script source lacks an exact audit')
        elif match[2].strip() and match[2] not in inline:
            raise UnsupportedDelivery('inline script lacks an exact audit')
    for match in _TAG.finditer(source):
        if not match[0].lower().startswith('<link'):
            continue
        attrs = attributes(match[0])
        if 'stylesheet' in attrs.get('rel', '').lower().split() and (
            set(attrs) - {'rel', 'href'} or attrs['rel'].lower().split() != ['stylesheet']
        ):
            raise UnsupportedDelivery('authored stylesheet loading attributes')


def _write_addressed(root: Path, prefix: str, suffix: str, raw: bytes) -> str:
    """Never overwrite an existing content-addressed artifact with other bytes."""
    name = prefix + digest(raw) + suffix
    path = root / name
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('content-addressed delivery artifact differs')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return name


def prepare_library(root: Path, catalog: dict, shared_config: dict, *, callback=None) -> dict:
    """Build one proven, bounded-cache delivery projection for any whole book.

    This consumes the existing common wrappers after their media are present;
    it does not project notes again or change cards/media/catalog. Unknown source
    protocols keep the original wrapper and are explicitly reported. The small
    content-addressed index is fetched only when a card is opened.
    """
    import gzip
    from .study_catalog_web import card_payload, card_shell
    root = Path(root)
    artifacts = root / 'evidence'
    if artifacts.is_symlink():
        raise ValueError('prepared artifacts must not follow an output symlink')
    artifacts.mkdir(exist_ok=True)
    media = ReadOnlyMedia(root / 'media')
    policy = shared_config.get('policy', {})
    module_descriptors = {}
    for name, pin in policy.get('external', {}).items():
        if pin not in AUDITED_NATIVE_MODULES or pin in module_descriptors:
            continue
        original = media.local(name).read_text()
        if digest(original) != pin:
            raise ValueError('audited native resource changed during delivery build')
        adapted = prepare_native_module(original).encode()
        filename = 'evidence/' + _write_addressed(artifacts, '_study_prepared_module_', '.js', adapted)
        module_descriptors[pin] = {'src': filename, 'sha256': digest(adapted), 'original_sha256': pin}
    cards_root = (root / 'cards').resolve(strict=True)
    entries, fallback_samples = {}, []
    source_proof = hashlib.sha256()
    raw_bytes = compressed_bytes = fallbacks = 0
    seen_ids = set()
    total = len(catalog['cards'])
    for completed, card in enumerate(catalog['cards'], 1):
        if not isinstance(card['id'], str) or card['id'] in seen_ids:
            raise ValueError('prepared card identities must be unique strings')
        seen_ids.add(card['id'])
        link = urlsplit(card['url'])
        relative = Path(unquote(link.path))
        if link.scheme or link.netloc or link.query or link.fragment or relative.is_absolute() or '..' in relative.parts:
            raise ValueError('prepared card link leaves the authored cards directory')
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(cards_root):
            raise ValueError('prepared card source leaves the authored cards directory')
        raw = path.read_bytes()
        literal = None
        try:
            literal = card_payload(raw)
            sides = json.loads(literal)
            if raw != card_shell(literal.decode(), '../media/').encode():
                raise UnsupportedDelivery('authored wrapper differs from the common known skeleton')
            for side in sides:
                _eligible_side(side, policy)
            prepared_sides = [materialize_side(side, media) for side in sides]
            # Only the source modules actually authored by this card determine
            # the persistent realm cohort; unrelated modules cannot replace it.
            used = set()
            from .study_catalog_web import SharedMountAudit, _MountScriptTag
            for side in sides:
                for match in SharedMountAudit.pattern.finditer(side):
                    attrs = _MountScriptTag(match[1]).attributes
                    pin = policy.get('external', {}).get(attrs.get('src'))
                    if pin in module_descriptors:
                        used.add(pin)
            value = {'schema': 'study-prepared-card.v1', 'source_wrapper_sha256': digest(raw),
                     'source_payload_sha256': digest(literal), 'sides': prepared_sides,
                     'modules': {pin: module_descriptors[pin] for pin in sorted(used)}}
            data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
            name = 'evidence/' + _write_addressed(artifacts, '_study_prepared_card_', '.json', data)
            packed = gzip.compress(data, compresslevel=6, mtime=0)
            packed_name = 'evidence/' + _write_addressed(artifacts, '_study_prepared_card_', '.json.gz', packed)
            entries[card['id']] = {'src': name, 'sha256': digest(data), 'gzipSrc': packed_name}
            raw_bytes += len(data)
            compressed_bytes += len(packed)
        except ValueError as error:
            # Retaining the original complete wrapper is the safe compatibility
            # path; coverage reports distinguish this from optimized cards.
            fallbacks += 1
            if len(fallback_samples) < 256:
                fallback_samples.append({'id': card['id'], 'reason': str(error)})
        source_proof.update(json.dumps([card['id'], digest(raw), digest(literal) if literal is not None else None], separators=(',', ':')).encode() + b'\n')
        if callback and (completed % 100 == 0 or completed == total):
            callback({'stage': 'export-web-prepare', 'book_id': catalog.get('book_id'),
                      'completed': completed, 'total': total, 'prepared': len(entries), 'fallbacks': fallbacks})
    index = json.dumps({'schema': 'study-prepared-index.v1', 'cards': entries}, ensure_ascii=False, separators=(',', ':')).encode()
    index_name = 'evidence/' + _write_addressed(artifacts, '_study_prepared_index_', '.json', index)
    packed = gzip.compress(index, compresslevel=9, mtime=0)
    packed_name = 'evidence/' + _write_addressed(artifacts, '_study_prepared_index_', '.json.gz', packed)
    config = {**shared_config, 'html': prepared_frame_html(),
              'preparedIndex': {'src': index_name, 'sha256': digest(index), 'gzipSrc': packed_name}}
    config.pop('prepared', None)
    config.pop('metricsAsset', None)
    return {'config': config, 'report': {'schema': 'study-prepared-delivery.v1', 'cards': total,
            'prepared': len(entries), 'fallbacks': fallbacks, 'fallback_samples': fallback_samples,
            'source_wrapper_payload_sha256': source_proof.hexdigest(),
            'artifact_bytes': raw_bytes, 'artifact_gzip_bytes': compressed_bytes,
            'index_bytes': len(index), 'index_gzip_bytes': len(packed),
            'max_resolver_cache_bytes': media.max_cache_bytes,
            'dictionary_decodes': media.dictionary_decodes,
            'original_cards_media_catalog_unchanged': True,
            'runtime_sha256': digest(PREPARED_FRAME_RUNTIME), 'qa_observation_enabled': False}}
