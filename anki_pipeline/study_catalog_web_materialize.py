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


# Both new exports and saved, already SHA-verified legacy pages execute the
# same audited numbering template. The legacy text is inert guard data only.
_TEMPLATE_DIR = Path(__file__).with_name('templates')
NUMBERING_SOURCE = (_TEMPLATE_DIR / 'example-numbering.js').read_text(encoding='utf-8')
LEGACY_NUMBERING = json.loads((_TEMPLATE_DIR / 'example-numbering-legacy.json').read_text(encoding='utf-8'))
GROUP_TRANSLATION_ADAPTER = (_TEMPLATE_DIR / 'native-group-translation-adapter.js').read_text(encoding='utf-8')
GROUP_RANGES_ADAPTER = (_TEMPLATE_DIR / 'native-group-ranges-adapter.js').read_text(encoding='utf-8')
GROUP_CANDIDATES_ADAPTER = (_TEMPLATE_DIR / 'native-group-candidates-adapter.js').read_text(encoding='utf-8')
SHARED_READING_BANK_WARM_ADAPTER = (_TEMPLATE_DIR / 'shared-reading-bank-warm-adapter.js').read_text(encoding='utf-8')
FINE_WHOLE_ADAPTER = (_TEMPLATE_DIR / 'native-fine-whole-adapter.js').read_text(encoding='utf-8')
SLIM_LOAD_CHECKER_ADAPTER = (_TEMPLATE_DIR / 'native-slim-load-checker-adapter.js').read_text(encoding='utf-8')
SLIM_LOAD_CHECKER_BRIDGE = (_TEMPLATE_DIR / 'native-slim-load-checker-bridge.js').read_text(encoding='utf-8')
BANK_SIDE_CHECKER_ADAPTER = (_TEMPLATE_DIR / 'native-bank-side-checker-adapter.js').read_text(encoding='utf-8')
COMPACT_CANDIDATES_ADAPTER = (_TEMPLATE_DIR / 'authored-compact-candidates-adapter.js').read_text(encoding='utf-8')
if (digest(NUMBERING_SOURCE) != 'ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'
        or LEGACY_NUMBERING.get('sha256') != '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1'
        or digest(LEGACY_NUMBERING.get('source', '')) != LEGACY_NUMBERING['sha256']
        or digest(GROUP_TRANSLATION_ADAPTER) != '5cf41bf203bdaaac12804997b1f340bfcaa70a9f5092338db70913df47617fdc'
        or digest(GROUP_RANGES_ADAPTER) != 'bc663c570315a158aa49096a71b39d0b7233debebee811f9b8e0d6ad5db5433d'
        or digest(GROUP_CANDIDATES_ADAPTER) != '840879cbda99e4f69577774d77774a4712b22a07f66098ff33d963cf11ae1c5c'
        or digest(SHARED_READING_BANK_WARM_ADAPTER) != 'd48e83c2cf0087a92adcf3e3afeea1a981c3a8d6c0ba8db3eb3d404876fe96d1'
        or digest(FINE_WHOLE_ADAPTER) != '41e76ef2439ca7e100a11621d5fc620f74bd7efb95675f9426759b01155b5aed'
        or digest(SLIM_LOAD_CHECKER_ADAPTER) != 'a700665eebdfb78e2eb7f5ef2de4efb372e079ac0800cfe895147b9b3abd89eb'
        or digest(SLIM_LOAD_CHECKER_BRIDGE) != '954599732b93730c3b637ac37ad89117fc8d215f2611947c2343b7f656b8abd6'
        or digest(BANK_SIDE_CHECKER_ADAPTER) != '96c8fca3e467c7cf6ca529a945b66e65b54b544d68ff87a64ff01a4f98a3a188'
        or digest(COMPACT_CANDIDATES_ADAPTER) != '64f9178c2d57a12eb35dc1f2fa5e20f8c939db93eea2cf79d7954b6984fa605a'):
    raise ValueError('Audited native algorithm template differs')


def _script_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True).replace('<', r'\u003c')


AUTHORED_ALGORITHM_RUNTIME = (
    '// Verified legacy numbering maps to the same template used by new exports.\n'
    + 'const canonicalExampleNumberingSource=' + _script_string(NUMBERING_SOURCE) + ';\n'
    + 'const legacyExampleNumberingSource=' + _script_string(LEGACY_NUMBERING['source']) + ';\n'
    + "function adaptExampleNumbering(code,originalPin){if(originalPin!=='"
    + LEGACY_NUMBERING['sha256'] + "')return code;if(code!==legacyExampleNumberingSource)"
    + "throw Error('Audited example numbering boundary differs');return canonicalExampleNumberingSource}\n"
    + GROUP_TRANSLATION_ADAPTER
    + GROUP_RANGES_ADAPTER
    + GROUP_CANDIDATES_ADAPTER
    + SHARED_READING_BANK_WARM_ADAPTER
    + FINE_WHOLE_ADAPTER
    + SLIM_LOAD_CHECKER_BRIDGE
    + SLIM_LOAD_CHECKER_ADAPTER
    + BANK_SIDE_CHECKER_ADAPTER
    + COMPACT_CANDIDATES_ADAPTER
)


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
KNOWN_PIN_INTEGRITY_RUNTIME = (_TEMPLATE_DIR / 'known-pin-integrity.js').read_text(encoding='utf-8')
PROJECTION_TASK_RUNTIME = (_TEMPLATE_DIR / 'projection-task.js').read_text(encoding='utf-8')


PREPARED_FRAME_RUNTIME = r'''(function(){'use strict';
''' + KNOWN_PIN_INTEGRITY_RUNTIME + r'''
const knownPinMatches=createKnownPinVerifier(globalThis,async bytes=>{const provider=parent.crypto.subtle?parent.crypto:window.crypto;return Array.from(new Uint8Array(await provider.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('')});
''' + PROJECTION_TASK_RUNTIME + r'''
const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();
let side=document.getElementById('study-side'),current=null,accepted=0,reservedToken=0,sequence=0,answer=false,working=false,record=null,preparedTasks=[],frontSession=null;const realms=[{node:side,key:null,ready:null,modules:new Set()}];document.body.style.overflow='hidden';
let consumer=null,consumerRevision=0,consumerShowSequence=0,committedView=null,frameDisposed=false;const frameAbort=new AbortController();
const clock=()=>performance.timeOrigin+performance.now(),encode=value=>String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
async function sha(text){const bytes=new TextEncoder().encode(text),crypto=parent.crypto.subtle?parent.crypto:window.crypto;return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('')}
function report(){if(!current?.metricsAsset)return;let out=document.getElementById('study-render-metrics');if(!out){out=document.createElement('output');out.id='study-render-metrics';out.hidden=true;document.body.append(out)}out.textContent=JSON.stringify(records)}
function state(){if(!current)return;parent.postMessage({type:'study-side-state',id:current.id,token:accepted,answer},origin);if(typeof consumerBusy==='function')consumerBusy()}
// A consumer can alter preferences only on its currently owned candidate.
// Committed snapshots stay separate until the original promote() gate succeeds.
function consumerSnapshot(view=committedView){const owned=ownsView(view),ready=!working&&view===committedView&&owned&&consumerCurrent(consumer)&&view.consumerRevision===consumerRevision;return{id:current?.id??null,generation:accepted,viewToken:owned?String(view.token)+':'+String(view.consumerRevision):null,answer:owned?!!view.index:answer,busy:working,ready:!!ready,document:owned?view.doc:null}}
function consumerCurrent(owner){return !!owner&&owner===consumer&&!frameDisposed&&current?.token===owner.generation&&owner.valid()}
function consumerBusy(){const owner=consumer;if(consumerCurrent(owner)&&working)owner.onBusy?.(consumerSnapshot())}
function consumerCommit(view){committedView=view;const owner=consumer;if(consumerCurrent(owner))owner.onCommit?.(consumerSnapshot(view))}
function consumerKey(event){const owner=consumer;if(!owner)return false;if(!consumerCurrent(owner)||event.repeat||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey)return true;if(owner.onKey?.(event,consumerSnapshot())===true){event.preventDefault();event.stopImmediatePropagation()}return true}
function applyConsumerDocument(view){const owner=consumer,revision=consumerRevision;if(!owner){view.consumerRevision=revision;return true}if(!consumerCurrent(owner)||!ownsView(view))return false;const state={id:view.packet.id,generation:view.packet.token,viewToken:String(view.token)+':'+String(revision),answer:!!view.index,busy:true,ready:false,document:view.doc},result=owner.beforePrepare?.(view.doc,state);if(result&&typeof result.then==='function')throw Error('beforePrepare must be synchronous');if(!consumerCurrent(owner)||consumerRevision!==revision||!ownsView(view))return false;view.consumerRevision=revision;return true}
async function refreshConsumerView(view){if(!consumer||view.consumerRevision===consumerRevision)return true;const owner=consumer,revision=consumerRevision;committedView=null;if(!applyConsumerDocument(view))return false;if(!await waitPrepared(view.entry,()=>ownsView(view)&&consumerCurrent(owner)&&consumerRevision===revision))return false;view.geometry=JSON.stringify(snapshot(view.doc,false));return true}
function configureConsumer(value){if(frameDisposed||!value||!Number.isSafeInteger(value.generation)||value.generation<=0||typeof value.valid!=='function')throw Error('Invalid prepared consumer');for(const name of ['beforePrepare','onBusy','onCommit','onKey'])if(value[name]!==undefined&&typeof value[name]!=='function')throw Error('Invalid prepared consumer callback');consumer=value;consumerRevision++;committedView=null;return true}
function disposeConsumer(){if(frameDisposed)return;consumer=null;committedView=null;cancel(Math.max(accepted,reservedToken)+1);frameDisposed=true;frameAbort.abort();scriptCache.clear();for(const entry of realms){try{clearOld(entry)}catch(_){}finally{entry.node?.remove();entry.doc=null;entry.win=null}}}
function key(event){if(typeof consumerKey==='function'&&consumerKey(event))return;if(event.target.closest('input,select,textarea,button,summary,a,[contenteditable]'))return;if(event.code==='Space'){event.preventDefault();flip.click()}if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();parent.postMessage({type:'study-navigate',direction:event.key==='ArrowRight'?1:-1},origin)}}
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
 if(originalPin==='9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1')return adaptExampleNumbering(code,originalPin);
 return adaptAuthoredCompactCandidates(code,originalPin);
}
// A source module must reuse the already verified host digest on HTTP LAN.
// Its own legacy fallback then leaves that digest in place. BufferSource
// snapshotting, algorithm errors and worker limits belong to the host API.
function bridgeRealmDigest(win){if(win.crypto?.subtle)return false;const upstream=parent.crypto?.subtle;if(!win.crypto||typeof upstream?.digest!=='function')return false;const bridge={digest:function(algorithm,data){return Reflect.apply(upstream.digest,upstream,[algorithm,data])}};try{Object.defineProperty(win.crypto,'subtle',{value:bridge,configurable:true});return true}catch{return false}}
async function realm(base,fingerprint,valid){const cohortKey=JSON.stringify([base,fingerprint]);if(!valid())return null;let entry=realms.find(item=>item.node!==side);if(!entry){entry={node:null,key:null,ready:null,modules:new Set()};realms.push(entry)}if(entry.key===cohortKey&&entry.ready&&entry.node?.isConnected&&(!entry.doc||entry.node.contentDocument===entry.doc))return entry.ready;entry.key=cohortKey;entry.modules=new Set();entry.doc=null;entry.win=null;entry.packet=null;entry.viewToken=null;const fresh=document.createElement('iframe'),realmId=String(accepted)+'-'+String(sequence)+'-'+String(Date.now());fresh.title='当前卡片准备';stage(fresh);const old=entry.node;entry.node=fresh;entry.ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Prepared realm initialization timed out')),8000);fresh.onload=()=>{if(entry.node!==fresh){clearTimeout(timer);resolve(null);return}const win=fresh.contentWindow,doc=fresh.contentDocument;if(!doc?.body||doc.documentElement.dataset.studyRealm!==realmId||doc.readyState!=='complete')return;clearTimeout(timer);bridgeRealmDigest(win);doc.addEventListener('keydown',key);if(current?.metricsAsset)win.addEventListener('error',event=>{entry.row?.events.push({event:'realm-error',at:clock(),message:event.message,filename:event.filename,line:event.lineno,stack:event.error?.stack,body:!!doc.body,connected:!!win.frameElement?.isConnected,currentDocument:entry.node.contentDocument===doc});report()});win.StudyPreparedDiagnostic=detail=>{if(current?.metricsAsset){entry.row?.events.push({at:clock(),...detail});report()}};execute(doc,'('+installCigen.toString()+')(window,document);','owned-cigen-bridge');entry.win=win;entry.doc=doc;resolve(entry)}});if(!valid())return null;if(old)old.replaceWith(fresh);else document.body.append(fresh);fresh.srcdoc='<!doctype html><html data-study-realm="'+encode(realmId)+'"><head><base href="'+encode(base)+'"></head><body></body></html>';return entry.ready}

// Only exact prepared-module addresses can use compressed/cached full GETs.
// Legacy source resources retain Range so the LAN proxy preserves raw bytes.
async function resource(url,pin){const key=url+'|'+pin;if(scriptCache.has(key))return scriptCache.get(key);const task=(async()=>{const preparedModule=/^[a-f0-9]{64}$/.test(pin)&&new URL(url,document.baseURI).pathname.endsWith('/evidence/_study_prepared_module_'+pin+'.js'),response=await fetch(url,{...(preparedModule?{}:{headers:{Range:'bytes=0-'}}),...(typeof frameAbort!=='undefined'?{signal:frameAbort.signal}:{})});if(!response.ok)throw Error('Prepared resource HTTP '+response.status);let total=null;if(response.status===206){const range=/^bytes 0-(\d+)\/(\d+)$/i.exec(response.headers.get('Content-Range')||'');if(!range||!Number.isSafeInteger(Number(range[2]))||Number(range[2])<=0||Number(range[1])!==Number(range[2])-1)throw Error('Prepared resource range is not complete');total=Number(range[2])}const text=await response.text();if(total!==null&&new TextEncoder().encode(text).byteLength!==total)throw Error('Prepared resource byte length differs from complete range');if(!await knownPinMatches(text,pin))throw Error('Prepared resource byte SHA differs');return text})();scriptCache.set(key,task);task.catch(()=>{if(scriptCache.get(key)===task)scriptCache.delete(key)});while(scriptCache.size>24)scriptCache.delete(scriptCache.keys().next().value);return task}
// Validate every execution rule before starting requests. The verified reads
// may overlap; their array positions and later authored execution never do.
async function collectAuthoredScripts(parsed,packet){
 const scripts=[];for(const script of parsed.scripts){const type=(script.getAttribute('type')||'').trim().toLowerCase();if(['application/json','application/ld+json'].includes(type))continue;if(!['','text/javascript','application/javascript'].includes(type)||['async','defer','nomodule'].some(name=>script.hasAttribute(name)))throw Error('Prepared execution mode is not audited');let code,pin=script.getAttribute('src')?packet.policy.external[script.getAttribute('src')]:null,url=null;if(script.getAttribute('src')){if(!pin)throw Error('Unknown prepared script');const module=packet.prepared.modules?.[pin];if(module){if(module.original_sha256!==pin)throw Error('Prepared module source SHA differs');code=null}else url=new URL(script.getAttribute('src'),packet.base).href}else{const rule=packet.policy.inline.find(rule=>rule.source===script.textContent);if(!rule&&script.textContent.trim())throw Error('Unknown prepared inline script');code=script.textContent;pin=rule?.sha256||''}scripts.push({node:script,code,pin,url})}
 await Promise.all(scripts.map(async item=>{const module=packet.prepared.modules?.[item.pin];if(module)await resource(new URL(module.src,document.baseURI).href,module.sha256);else if(item.url)item.code=await resource(item.url,item.pin);if(item.code!==null)item.code=adaptAuthoredCompactClassScan(item.code,item.pin);item.node.type='application/x-study-inert'}));return scripts;
}
function installCigen(win,doc){const known=new Map(),selector='iframe.etymology-source-frame';let scheduled=false,batchDepth=0,dirty=false;
 function layout(frame){if(batchDepth){dirty=true;return}const entry=known.get(frame);if(!entry||!doc.contains(frame)||frame.getBoundingClientRect().width<=0)return;const meaning=frame.closest('.meaning-section'),sample=meaning?.querySelector('.form-row,.primary-definition .field-content');if(sample){const text=win.getComputedStyle(sample);frame.style.fontSize=text.fontSize;frame.style.lineHeight=text.lineHeight}const style=win.getComputedStyle(frame),title=meaning?.querySelector('.primary-definition .field-title'),callout=meaning?.querySelector('.field-callout'),tag=meaning?.querySelector('.level-list li'),font={fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color},metrics={'--ety-text-size':style.fontSize,'--ety-text-line':style.lineHeight};if(title){const t=win.getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':t.fontSize,'--ety-title-line':t.lineHeight,'--ety-title-gap':t.marginBottom})}if(callout)metrics['--ety-section-space']=win.getComputedStyle(callout).paddingTop;if(tag){const t=win.getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':t.fontSize,'--ety-tag-line':t.lineHeight,'--ety-tag-padding':t.padding,'--ety-tag-gap':win.getComputedStyle(tag.parentElement).gap})}const signature=JSON.stringify([Math.round(frame.getBoundingClientRect().width),font,metrics]);if(signature===entry.signature)return;entry.signature=signature;entry.ready=false;entry.readySignature=null;frame.contentWindow.postMessage({type:'cigen:layout',font,studySignature:signature},'*');frame.contentWindow.postMessage({type:'cigen:theme',metrics,studySignature:signature},'*')}
 const sizes=new win.ResizeObserver(entries=>{for(const entry of entries)layout(entry.target)});
 function refresh(){for(const [frame]of known)if(!doc.contains(frame)){sizes.unobserve(frame);known.delete(frame)}for(const frame of doc.querySelectorAll(selector))if(!known.has(frame)){known.set(frame,{signature:null,height:null,inits:0,ready:false,error:null});sizes.observe(frame);frame.addEventListener('load',()=>{const entry=known.get(frame);if(entry){entry.signature=null;entry.inits++;layout(frame)}})}if(batchDepth){dirty=true;return}for(const frame of known.keys())layout(frame)}
 function batch(action){batchDepth++;dirty=true;try{refresh();return action()}finally{if(--batchDepth===0&&dirty){dirty=false;refresh()}}}
 new win.MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh()})}).observe(doc.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden']});win.addEventListener('resize',refresh);win.addEventListener('message',event=>{const data=event.data;if(!['cigen:size','study-child-ready','study-child-error','study-child-phase'].includes(data?.type))return;const frame=Array.from(known.keys()).find(node=>node.contentWindow===event.source);if(!frame)return;const entry=known.get(frame);if(data.type!=='cigen:size'){if(data.type==='study-child-phase'){entry.phases=entry.phases||[];entry.phases.push(data);if(entry.phases.length>12)entry.phases.splice(6,1);return}entry.lastReady=data;if(data.token!==frame.dataset.studyChildToken||data.sourceSha!==frame.dataset.studyChildSource)return;if(data.type==='study-child-error'){entry.error=Error((data.message||'Original child initialization failed')+' ['+(data.filename||'')+':'+(data.line||'')+']');win.StudyPreparedDiagnostic?.({event:'child-error',...data});return}if(entry.error)return;if(data.signature!==entry.signature||!Number.isFinite(data.height)||data.height<=0||Math.abs(data.width-frame.getBoundingClientRect().width)>1)return;entry.ready=true;entry.readySignature=data.signature;entry.readyWidth=data.width}if(!Number.isFinite(data.height)||data.height<=0)return;entry.height=data.height;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value});win.__ankiCigenFrames={refresh,batch,known};
}
const staticHistoryCohorts={"modules":{"be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93":"6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e":"7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4"},"sequences":[["12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","ae91933dd0602830532df4ee6fe801a21e723e230ad62fc5e76147a7221fce57","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93","b383335a30cfb0df90c14c394b505b655f2520350b09a8dea5fab8de8592a4b7","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1"],["12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","ae91933dd0602830532df4ee6fe801a21e723e230ad62fc5e76147a7221fce57","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93","b383335a30cfb0df90c14c394b505b655f2520350b09a8dea5fab8de8592a4b7","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1","12e5c58c0829757e3081d2905fb63dfe924e54b9be80fae2fd6fa77d3d47f373","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93","afe4431fdd5254aa0b20c322ef3385a15a8a8ed8daddb6f6782f8866114fae3c","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1"],["9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","ae91933dd0602830532df4ee6fe801a21e723e230ad62fc5e76147a7221fce57","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","b383335a30cfb0df90c14c394b505b655f2520350b09a8dea5fab8de8592a4b7","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1"],["9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","ae91933dd0602830532df4ee6fe801a21e723e230ad62fc5e76147a7221fce57","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","b383335a30cfb0df90c14c394b505b655f2520350b09a8dea5fab8de8592a4b7","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1","e938f4c52ba27633c8617a014f2e79f29c0abce1ed62c590ad74271c07d146de","9014f667e36b6b3094b212c110cb2af8b0bb910a89ba15ea7a052df50d5a96ba","171b1a051840b2488c00ebdfd97874e205fac661cdf44c67b042957a11d15e57","71bcf5942a418885cd1b71065bb80504d3aba3fd658990cef739fe2706e83ee5","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","afe4431fdd5254aa0b20c322ef3385a15a8a8ed8daddb6f6782f8866114fae3c","9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1"]]};
const staticHistoryRoots='details.sf-ownership-history,details.sf-ownership-authority,details.sf-original-history-panel';
const staticHistorySelected='.example-card,._r28,.card-chunk-active,.selected,.is-selected,[selected],[aria-selected="true"],[data-selected="true"]';
const staticHistoryForbidden='li.example-card,li._r28,.as-lazy,script,style,link,iframe,frame,audio,video,source,track,img,picture,svg,canvas,object,embed,form,input,button,select,textarea,option,fieldset,[is],[contenteditable],[tabindex],[onclick],[onchange],[onload],.sf-sense,.sf-panel,.sf-example,[data-sf-filter],.sf-preview-count,.sentence-jump,[data-rb-j],.source-reader,.source-reader-setting,.examples-section,.etymology-section,.etymology-entry,.level-section,.level-list,.card-heading,.card-meta,.dictionary-definition,.dictionary-form-groups,.word-audio-status,.phonetic-accent-icon,.accent-audio-setting,.phonetic-accent-uk,.phonetic-accent-us,.accent-status-uk,.accent-status-us,[role="button"],#preview-flip,.dictionary-link,.dictionary-word-audio,.dictionary-audio-setting,.dictionary-audio-source,.preview-word-play,.recorded-audio,.audio-line,.phonetic-line,.phonetic-accent,.pronunciation-settings,[data-accent-source],.word,.vocab-card,.vocab-front,.vocab-back,.primary-definition,.secondary-definition,.meaning-section,.forms-section,.form-row,.field-content,.field-title,.field-callout,.field-section,[data-field],.exam-countdown,.anki-countdown-content,.card-chunk-active,details[open],span[_c],[class*="_r"],.selected,.is-selected,[selected],[aria-selected="true"],[data-selected="true"]';
function staticHistoryEligible(root){
 if(!root.matches(staticHistoryRoots)||root.open||root.closest(staticHistorySelected))return false;
 if(root.hasAttribute('id')||root.querySelector('[id]')||root.matches(staticHistoryForbidden))return false;
 const summaries=Array.from(root.children).filter(node=>node.tagName==='SUMMARY');if(summaries.length!==1)return false;const summary=summaries[0];
 if(summary.matches(staticHistoryForbidden)||summary.querySelector(staticHistoryForbidden))return false;
 for(let node=root.firstChild;node&&node!==summary;node=node.nextSibling)if(!(node.nodeType===8||node.nodeType===3&&!node.data.trim()))return false;
 const selection=root.ownerDocument.defaultView?.getSelection?.();if(selection?.rangeCount&&selection.containsNode(root,true))return false;
 const nodes=[];for(let node=summary.nextSibling;node;node=node.nextSibling){nodes.push(node);if(node.nodeType===1&&(node.matches(staticHistoryForbidden)||node.querySelector(staticHistoryForbidden)))return false}
 const walker=root.ownerDocument.createTreeWalker(root,1);for(let node=walker.nextNode();node;node=walker.nextNode())if(node.localName.includes('-'))return false;
 return nodes.length?{summary,nodes}:false;
}
function staticHistoryCohort(parsed,packet,scripts){
 if(parsed.querySelectorAll('script.anki-final-reviewed-data').length!==1)return false;
 const modules=Object.entries(packet.prepared.modules||{});if(modules.length!==1)return false;const [pin,value]=modules[0];
 if(staticHistoryCohorts.modules[pin]!==value.sha256||value.original_sha256!==pin||value.src!=='evidence/_study_prepared_module_'+value.sha256+'.js'||!scripts.some(item=>item.pin===pin))return false;
 const sequence=JSON.stringify(scripts.map(item=>['d34134c8918205c51c842963c7354f090e6041dcecd00480e695d4e874b8e21d','ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'].includes(item.pin)?'9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1':item.pin));return staticHistoryCohorts.sequences.some(known=>JSON.stringify(known)===sequence);
}
function stageStaticHistory(parsed){
 let entries=[],boundDoc=parsed,owns=()=>true,done=false;
 for(const root of parsed.querySelectorAll(staticHistoryRoots)){
  if(entries.some(entry=>entry.root.contains(root)||entry.fragment.contains(root)))continue;
  const value=staticHistoryEligible(root);if(!value)continue;
  const fragment=parsed.createDocumentFragment(),anchor=parsed.createComment('study-private-static-history-stage');root.insertBefore(anchor,value.nodes[0]);for(const node of value.nodes)fragment.append(node);
  entries.push({root,summary:value.summary,anchor,fragment});
 }
 const count=entries.length;
 function release(){for(const entry of entries){if(entry.anchor.parentNode)entry.anchor.remove();entry.fragment=null}entries=[];done=true;owns=()=>false;boundDoc=null}
 function restore(strict=true){
  if(done)return true;
  const okay=owns()&&entries.every(entry=>entry.root.ownerDocument===boundDoc&&entry.anchor.ownerDocument===boundDoc&&entry.anchor.parentNode===entry.root&&entry.summary.parentNode===entry.root);
  if(!okay){release();if(strict)throw Error('Staged static history ownership or anchor changed');return false}
  for(const entry of entries){entry.root.insertBefore(entry.fragment,entry.anchor);entry.anchor.remove();entry.fragment=null}entries=[];done=true;owns=()=>false;boundDoc=null;return true;
 }
 return{count,bind(doc,isOwner){if(done)return;boundDoc=doc;owns=isOwner},restore,cleanup(){restore(false)},pending:()=>entries.length};
}
function awaitStaticHistoryNative(active,valid,began){const {doc,win}=active;return new Promise(resolve=>{function check(){if(!valid()){resolve(false);return}const native=Array.from(doc.querySelectorAll('script.anki-final-reviewed-data')).slice(0,1).map(node=>node.dataset.nativeState||'preparing');if(native.includes('failed')||Array.from(win.__ankiCigenFrames.known.values()).some(state=>state.error)||performance.now()-began>10000||native.length===1&&native[0]==='ready'){resolve(true);return}requestAnimationFrame(check)}requestAnimationFrame(check)})}
function copyAttributes(from,to){for(const value of Array.from(to.attributes))to.removeAttribute(value.name);for(const value of from.attributes)to.setAttribute(value.name,value.value)}
function snapshot(doc,includeText=true){if(!doc.defaultView?.frameElement?.isConnected)return null;const major=Array.from(doc.querySelectorAll('.exam-frequency,.primary-definition,.secondary-definition,.etymology-section,.examples-section,iframe.etymology-source-frame')).filter(node=>node.getClientRects().length).map((node,index)=>{const box=node.getBoundingClientRect(),entry=node.tagName==='IFRAME'?doc.defaultView.__ankiCigenFrames.known.get(node):null;return{index,tag:node.tagName,classes:node.className,top:Math.round(box.top*10)/10,height:Math.round(box.height*10)/10,width:Math.round(box.width*10)/10,childHeight:entry?.height||null,childInits:entry?.inits||0}});return{bodyHeight:Math.round(doc.body.getBoundingClientRect().height*10)/10,textLength:includeText?(doc.body.innerText?.length||doc.body.textContent.length):null,nativeStates:Array.from(doc.querySelectorAll('script.anki-final-reviewed-data')).slice(0,1).map(n=>n.dataset.nativeState||'uninitialized'),major}}
function observe(doc,row,token){if(!current?.metricsAsset)return;const start=performance.now(),samples=[];let previous=start,lastSignature='',lastChange=start,stableSince=null,nativeReadyAt=null,first=null,last=null,frames=0,changes=0,maxFrameGap=0;function frame(now){if(record!==row||doc!==side.contentDocument)return;frames++;maxFrameGap=Math.max(maxFrameGap,now-previous);previous=now;const value=snapshot(doc);if(!value){row.events.push({event:'inactive-document-observation',at:clock()});report();return}const signature=JSON.stringify(value);if(!first&&value.bodyHeight>0&&value.textLength>0){first={at:clock(),...value};row.events.push({event:'first-visible-animation-frame',at:clock(),...value})}if(signature!==lastSignature){lastSignature=signature;lastChange=now;stableSince=null;changes++;if(samples.length<20)samples.push({at:clock(),...value})}const ready=value.textLength>0&&value.nativeStates.every(state=>state==='ready')&&value.major.filter(v=>v.tag==='IFRAME').every(v=>v.childHeight!==null&&v.height>=v.childHeight-1);if(ready&&nativeReadyAt===null)nativeReadyAt=clock();if(ready&&now-lastChange>=200&&stableSince===null)stableSince=performance.timeOrigin+lastChange;last=value;row.wholeCard={start:performance.timeOrigin+start,first,final:last,frames,changes,maxFrameGap,nativeReadyAt,stableSince,samples};report();if(now-start<2500)requestAnimationFrame(frame)}requestAnimationFrame(frame)}
function childReadiness(config){let fontEpoch=0,phaseSignature=null;function phase(name,extra={}){if(!config.debug)return;const value={phase:name,...extra},signature=JSON.stringify(value);if(signature===phaseSignature)return;phaseSignature=signature;parent.postMessage({type:'study-child-phase',token:config.token,sourceSha:config.sourceSha,...value},'*')}let loaded=document.readyState==='complete',fontReady=false,layout=null,theme=null,scheduled=false,last=null,count=0,sent=null;const send=(type,extra)=>parent.postMessage({type,token:config.token,sourceSha:config.sourceSha,...extra},'*');function check(){scheduled=false;phase('measure',{loaded,fontReady,layout,theme,body:!!document.body,imagesPending:Array.from(document.images).filter(image=>!image.complete).length});if(!loaded||!fontReady||document.fonts?.status==='loading'||!layout||layout!==theme||!document.body)return;if(Array.from(document.images).some(image=>!image.complete))return;const height=Math.ceil(document.body.getBoundingClientRect().height)+1,width=document.documentElement.getBoundingClientRect().width,signature=JSON.stringify([height,width,layout]);phase('measured',{height,width,count,signature:layout});if(signature===last)count++;else{last=signature;count=0}if(height>1&&count>=2){if(sent!==signature){sent=signature;send('study-child-ready',{height,width,signature:layout})}}else request()}function request(){if(scheduled)return;scheduled=true;setTimeout(check,0)}function fonts(){const epoch=++fontEpoch;fontReady=false;queueMicrotask(()=>{document.body?.getBoundingClientRect();Promise.resolve(document.fonts?.ready).then(()=>{if(epoch!==fontEpoch)return;fontReady=document.fonts?.status!=='loading';request()})})}window.addEventListener('load',()=>{loaded=true;if(document.body&&typeof ResizeObserver==='function')new ResizeObserver(request).observe(document.body);fonts()},{once:true});window.addEventListener('message',event=>{if(event.source!==parent||!event.data?.studySignature)return;if(event.data.type==='cigen:layout')layout=event.data.studySignature;if(event.data.type==='cigen:theme')theme=event.data.studySignature;count=0;last=null;fonts()});window.addEventListener('error',event=>send('study-child-error',{message:event.message||'Original child resource failed',filename:event.filename,line:event.lineno,stack:event.error?.stack}),true);document.addEventListener('load',request,true);document.fonts?.addEventListener?.('loadingdone',fonts);document.fonts?.addEventListener?.('loadingerror',fonts);if(loaded)fonts();phase('installed',{state:document.readyState})}
function gateMemberCache(doc){
 let frames=null,native=null,observer=null,disposed=false,enabled=false;
 function invalidate(){frames=null;native=null}
 function disable(){enabled=false;invalidate();if(observer){try{observer.disconnect()}catch(_){}observer=null}}
 try{const Observer=doc.defaultView?.MutationObserver;if(typeof Observer==='function'){observer=new Observer(records=>{if(!disposed&&records.length)invalidate()});observer.observe(doc,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});enabled=true}}catch(_){disable()}
 function read(kind){
  if(enabled){try{if(observer.takeRecords().length)invalidate()}catch(_){disable()}}
  const selector=kind==='frames'?'iframe.etymology-source-frame':'script.anki-final-reviewed-data';
  if(!enabled||disposed)return Array.from(doc.querySelectorAll(selector));
  if(kind==='frames'){if(frames===null)frames=Array.from(doc.querySelectorAll(selector));return frames}
  if(native===null)native=Array.from(doc.querySelectorAll(selector));return native;
 }
 return{doc,read,dispose(){if(disposed)return;disposed=true;disable()}};
}
function waitPrepared(entry,valid,beganAt=null){const began=beganAt===null?performance.now():beganAt;let previous=null,same=0,members=null;const release=()=>{members?.dispose();members=null},select=(doc,kind)=>{if(!members||members.doc!==doc){release();members=gateMemberCache(doc)}return members.read(kind)};return new Promise((finish,fail)=>{const resolve=value=>{release();finish(value)},reject=error=>{release();fail(error)};function check(){try{if(!valid()){resolve(false);return}const {doc,win}=entry,frames=select(doc,'frames').filter(frame=>frame.getBoundingClientRect().width>0);for(const frame of frames){const state=win.__ankiCigenFrames.known.get(frame);if(state?.error){reject(state.error);return}}const native=select(doc,'native').slice(0,1).map(node=>node.dataset.nativeState||'preparing');if(native.includes('failed')){reject(Error(doc.querySelector('.anki-final-status')?.textContent||'Original native validation failed'));return}const ready=native.every(value=>value==='ready')&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return state?.ready&&state.readySignature===state.signature&&Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1})&&doc.fonts?.status!=='loading';const signature=ready?JSON.stringify(snapshot(doc,false)):null;if(ready&&signature===previous)same++;else same=0;previous=signature;if(ready&&same>=2){resolve(true);return}if(performance.now()-began>10000){reject(Error('Connected original card preparation timed out: '+JSON.stringify({native,fonts:doc.fonts?.status,frames:frames.map(frame=>({width:frame.getBoundingClientRect().width,proof:frame.dataset.studyChildSource,token:frame.dataset.studyChildToken,...win.__ankiCigenFrames.known.get(frame)}))})));return}requestAnimationFrame(check)}catch(error){reject(error)}}try{requestAnimationFrame(check)}catch(error){release();throw error}})}
async function prepareView(packet,index,requestedAt){const token=++sequence,prepared=packet.prepared?.sides?.[index];if(!prepared)throw Error('Missing proven prepared side');const valid=()=>packet===current&&token===sequence;
 const row={card:packet.id,side:index?'back-preparing':'front-preparing',token:accepted+'-'+token,request:requestedAt,reason:'connected-preparation',events:[]};if(packet.metricsAsset){records.push(row);if(records.length>20)records.shift();report();}
 const verified=await Promise.all([knownPinMatches(packet.sides[index],prepared.proof.source_sha256),knownPinMatches(prepared.html,prepared.proof.expanded_sha256)]);if(!verified.every(Boolean))throw Error('Prepared body differs from its source proof');if(!valid())return null;
 const parsed=new DOMParser().parseFromString(prepared.html,'text/html');if(parsed.querySelector('[autoplay]'))throw Error('Autoplay retains its original wrapper');if(/<noscript\b/i.test(prepared.html))throw Error('Prepared parsing retains original noscript semantics');parsed.querySelector('base').href=packet.base;
 const scripts=await collectAuthoredScripts(parsed,packet);
 // Source styles and module bytes are prepared before the next authored body;
 // there is no new visible half-card waiting for external script downloads.
 for(const link of parsed.querySelectorAll('link[rel~="stylesheet"][href]')){if(Array.from(link.attributes).some(a=>!['rel','href'].includes(a.name))||link.rel.trim().toLowerCase().split(/\s+/).join(' ')!=='stylesheet')throw Error('Prepared stylesheet attributes retain their original protocol');const url=new URL(link.getAttribute('href'),packet.base).href,response=await fetch(url,{signal:frameAbort.signal});if(!response.ok)throw Error('Prepared stylesheet HTTP '+response.status);const raw=await response.text();if(/@import\b|<\/style/i.test(raw))throw Error('Prepared stylesheet needs its original lifecycle');const style=parsed.createElement('style');style.textContent=raw;link.replaceWith(style)}
 if(!valid())return null;const fingerprint=JSON.stringify(Object.entries(packet.prepared.modules||{}).sort(([a],[b])=>a.localeCompare(b))),active=await realm(packet.base,fingerprint,valid);if(!valid()||!active)return null;const {win,doc}=active;active.row=row;active.packet=packet;active.viewToken=token;
 for(const item of scripts){const module=packet.prepared.modules?.[item.pin];if(module&&!active.modules.has(item.pin)){const code=await resource(new URL(module.src,document.baseURI).href,module.sha256);if(!valid())return null;const slimLoadSource=adaptNativeFineWholeProbe(adaptSharedReadingBankWarm(adaptNativeGroupCoarseBuckets(adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask(adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin);withSlimLoadChecker(win,enabled=>execute(doc,enabled?adaptNativeBankSideChecker(adaptNativeSlimLoadChecker(slimLoadSource,item.pin),item.pin):slimLoadSource,item.pin+'-prepared-'+module.sha256));active.modules.add(item.pin)}}
 win.AnkiSlimDecode?.(parsed);const history=staticHistoryCohort(parsed,packet,scripts)?stageStaticHistory(parsed):null;try{for(const [pin,raw]of Object.entries(prepared.registry)){if(!await knownPinMatches(raw,pin))throw Error('Prepared native registration SHA differs');win.AnkiSlimAssets=win.AnkiSlimAssets||{};win.AnkiSlimAssets[pin]=raw}if(!valid())return null;
 for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){if(!win.StudySlimWarm)throw Error('Prepared native module is unavailable');for(const pair of [['asSrc','asSha'],['asIndexSrc','asIndexSha']])if(payload.dataset[pair[0]])await win.StudySlimWarm.load({src:payload.dataset[pair[0]],sha256:payload.dataset[pair[1]]});const raw=payload.dataset.asSha?prepared.registry[payload.dataset.asSha]:payload.textContent;const projectionOwner=projectionTaskBegin(win,packet,index,token,active);try{await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw))}finally{projectionOwner?.close()}await win.AnkiSharedReadingBankRuntime.warm(win.AnkiFinalReadingMetadata,Array.from(parsed.querySelectorAll('.sf-en,.example-text'),node=>node.textContent))}if(!valid())return null;
 const frames=Array.from(parsed.querySelectorAll('iframe.etymology-source-frame'));if(frames.length!==prepared.children.length)throw Error('Prepared child source count differs');frames.forEach((frame,n)=>{const child=prepared.children[n],section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section'),levels=meaning&&Array.from(meaning.children).find(node=>node.classList.contains('level-section'));if(levels)levels.after(section);if(section)section.style.margin='.2rem 0 .65rem';let childHTML=child.html;if(packet.metricsAsset){let ordinal=0;childHTML=childHTML.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,code,close)=>open+code+'\n//# sourceURL=study-child-'+child.scripts[ordinal++]+'.js\n'+close)}const base='<base href="'+encode(packet.base)+'">';if(/<base\b/i.test(childHTML))childHTML=childHTML.replace(/<base\b[^>]*>/i,base);else childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+base);const childToken=String(accepted)+'-'+String(token)+'-'+n,head='<scr'+'ipt>('+childReadiness.toString()+')('+JSON.stringify({token:childToken,sourceSha:child.source_sha256,debug:!!packet.metricsAsset})+');</scr'+'ipt>';childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+head);frame.dataset.studyChildToken=childToken;frame.dataset.studyChildSource=child.source_sha256;frame.setAttribute('srcdoc',childHTML);frame.removeAttribute('data-web-etymology-srcdoc')});
 if(!valid())return null;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;
 const head=doc.createDocumentFragment(),body=doc.createDocumentFragment();for(const node of Array.from(parsed.head.childNodes))head.append(doc.adoptNode(node));for(const node of Array.from(parsed.body.childNodes))body.append(doc.adoptNode(node));for(const audio of body.querySelectorAll('audio,video')){const play=audio.play,details=()=>({src:audio.src,currentSrc:audio.currentSrc,srcAttribute:audio.getAttribute('src'),ready:audio.readyState,network:audio.networkState,connected:audio.isConnected,ownerCurrent:audio.ownerDocument===doc,ownRealmPrototype:audio instanceof win.HTMLMediaElement,mediaError:audio.error?.message});if(packet.metricsAsset){row.audio=row.audio||{attempts:0,denied:0,errors:[],events:[]};for(const event of ['loadstart','loadedmetadata','canplay','error','abort','emptied','stalled','suspend'])audio.addEventListener(event,()=>{row.audio.events.push({event,at:clock(),...details()});if(row.audio.events.length>24)row.audio.events.shift();report()})}Object.defineProperty(audio,'play',{configurable:true,writable:true,value:function(...args){if(packet.metricsAsset){row.audio.attempts++;row.audio.userActivation=win.navigator.userActivation?.isActive;row.audio.call={...details(),play:String(play).slice(0,180),targetRealmPlay:String(win.HTMLMediaElement.prototype.play).slice(0,180)};report()}if(active.node!==side){row.audioAttempts=(row.audioAttempts||0)+1;if(row.audio)row.audio.denied++;return Promise.reject(Error('Prepared media cannot play before commit'))}try{const result=Reflect.apply(play,this,args);if(!packet.metricsAsset)return result;return Promise.resolve(result).catch(error=>{row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});if(row.audio.errors.length>4)row.audio.errors.shift();report();throw error})}catch(error){if(row.audio){row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});report()}throw error}}})}copyAttributes(parsed.documentElement,doc.documentElement);copyAttributes(parsed.body,doc.body);doc.head.replaceChildren(head);doc.body.replaceChildren(body);win.scrollTo(0,0);history?.bind(doc,()=>active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.contentDocument===doc);
 // Authored scripts still run in source order. Their repeated calls to our
 // bridge are coalesced so they cannot force intermediate whole-card layouts.
 const authoredComplete=win.__ankiCigenFrames.batch(()=>{for(const item of scripts){if(!valid())return false;if(packet.prepared.modules?.[item.pin]){item.node.remove();continue}execute(doc,item.code,item.pin);item.node.remove()}return true});if(!authoredComplete||!valid())return null;
 // Media adopted from the inert parser may retain a rejected temporary-URL
 // selection. Reset only after the final base and complete body are connected;
 // load() preserves authored preload/src and never starts playback.
 for(const media of doc.querySelectorAll('audio,video'))if(media.getAttribute('src')||media.querySelector('source[src]'))media.load();
 if(packet.metricsAsset&&packet.audioDiagnostics)installAudioDiagnostic(win,doc,row);if(!valid())return null;
 if(packet.metricsAsset){row.preparedBodyAt=clock();row.events.push({event:'connected-prepared-body',at:clock(),...snapshot(doc)});}const candidate={entry:active,doc,packet,index,row,token};if(!applyConsumerDocument(candidate)||!valid())return null;const historyBegan=performance.now();if(history?.count){if(!await awaitStaticHistoryNative(active,valid,historyBegan))return null;history.restore()}if(!await waitPrepared(active,valid,history?.count?historyBegan:null))return null;if(packet.metricsAsset){row.readyAt=clock();row.prepared=snapshot(doc);report();}return{...candidate,geometry:JSON.stringify(snapshot(doc,false))};}finally{history?.cleanup()}
}
function installAudioDiagnostic(win,doc,row){const box=doc.createElement('div');box.style.cssText='position:fixed;bottom:4px;right:4px;z-index:999999;background:white;border:1px solid #aaa;padding:5px';for(const [label,reset]of [['诊断：原生播放韦氏',false],['诊断：load 后播放韦氏',true]]){const button=doc.createElement('button');button.textContent=label;button.onclick=()=>{const audio=doc.querySelector('audio[data-dictionary-source="webster"]')||doc.querySelector('audio');if(!audio)return;const log=extra=>{row.audio.diagnostic={reset,src:audio.src,currentSrc:audio.currentSrc,ready:audio.readyState,network:audio.networkState,...extra};report()};try{if(reset)audio.load();const job=reset?audio.play():Reflect.apply(win.HTMLMediaElement.prototype.play,audio,[]);Promise.resolve(job).then(()=>log({result:'resolved',duration:audio.duration})).catch(error=>log({result:'rejected',name:error.name,message:error.message}))}catch(error){log({result:'threw',name:error.name,message:error.message})}};box.append(button)}doc.body.append(box)}
function clearOld(entry){if(!entry?.doc)return;const {win,doc}=entry;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();doc.body.replaceChildren();win.__ankiCigenFrames.refresh();win.__ankiCardChunkState=null;entry.packet=null;entry.viewToken=null}
function ownsView(view){return !!view&&view.packet===current&&view.entry.packet===view.packet&&view.entry.viewToken===view.token&&view.entry.doc===view.doc&&view.entry.node.isConnected&&view.entry.node.contentDocument===view.doc}
function currentPreparation(view){if(!ownsView(view)||view.doc.fonts?.status==='loading')return false;view.entry.win.__ankiCigenFrames.refresh();for(const frame of view.doc.querySelectorAll('iframe.etymology-source-frame')){if(frame.getBoundingClientRect().width<=0)continue;const state=view.entry.win.__ankiCigenFrames.known.get(frame);if(!state?.ready||state.readySignature!==state.signature||Math.abs(state.readyWidth-frame.getBoundingClientRect().width)>1)return false}return view.geometry===JSON.stringify(snapshot(view.doc,false))}
function promote(view,requestedAt){if(!currentPreparation(view))return false;const previous=realms.find(entry=>entry.node===side);if(previous&&previous!==view.entry)stage(previous.node);side=view.entry.node;side.id='study-side';side.inert=false;side.removeAttribute('aria-hidden');side.style.cssText='display:block;width:100%;height:100%;border:0';answer=!!view.index;side.title=answer?'学习卡片背面':'学习卡片正面';record=current.metricsAsset?view.row:null;if(record){record.side=answer?'back':'front';record.request=requestedAt;record.mount=clock();record.events.push({event:'complete-card-commit',at:clock(),...snapshot(view.doc)});}side.dataset.mountReason='connected-complete-card';side.dataset.cardId=current.id;flip.textContent=answer?'返回正面':'显示答案';flip.setAttribute('aria-pressed',String(answer));working=false;flip.disabled=false;state();observe(view.doc,record,view.token);if(previous!==view.entry){for(const audio of previous?.doc?.querySelectorAll('audio,video')||[])audio.pause();if(previous?.packet!==view.packet)clearOld(previous)}report();if(typeof consumerCommit==='function')consumerCommit(view);return true}
function getView(packet,index,requestedAt){const existing=preparedTasks[index];if(existing?.packet===packet&&(!existing.view||ownsView(existing.view)))return existing.promise;const task={packet,index,promise:null,view:null};task.promise=prepareView(packet,index,requestedAt).then(view=>{task.view=view;return view});preparedTasks[index]=task;task.promise.catch(()=>{});return task.promise}
function prepareBack(packet){if(packet!==current||packet.frontOnly)return;const task=getView(packet,1,clock());task.catch(error=>{if(packet===current&&packet.metricsAsset){const row={card:packet.id,side:'back-preparation-failed',message:String(error.message||error)};records.push(row);report()}})}
async function show(requestedAt,index){const command=typeof consumerShowSequence==='number'?++consumerShowSequence:0,commandValid=()=>!command||command===consumerShowSequence;const packet=current;working=true;flip.disabled=true;state();if(index&&packet.frontOnly){const session=frontSession;if(!session||session.packet!==packet||!await session.complete||current!==packet)return false}const view=await getView(packet,index,requestedAt);if(current!==packet||!view||!commandValid())return false;if(typeof refreshConsumerView==='function'&&!await refreshConsumerView(view))return false;if(!currentPreparation(view)){if(!await waitPrepared(view.entry,()=>ownsView(view)))return false;view.geometry=JSON.stringify(snapshot(view.doc,false))}if(!commandValid())return false;const result=promote(view,requestedAt);if(!result&&ownsView(view))throw Error('Prepared side lost readiness before commit');if(result&&!index)prepareBack(packet);return result}

function canonicalJSON(value){return JSON.stringify(value,function(key,item){return item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(name=>[name,item[name]])):item})}
function accepts(packet,count){return !!packet&&Number.isSafeInteger(packet.token)&&packet.token>accepted&&packet.token>=reservedToken&&typeof packet.id==='string'&&!!packet.prepared&&Array.isArray(packet.sides)&&packet.sides.length===count&&packet.sides.every(value=>typeof value==='string')&&Array.isArray(packet.prepared.sides)&&packet.prepared.sides.length===count}
function resourceBase(packet){const base=new URL(packet.base);if(base.origin!==origin||!['http:','https:'].includes(base.protocol))throw Error('Invalid prepared resource base');return base.href}
function captureFront(packet){
 const binding=packet.deliveryBinding,hashes=['index_sha256','full_prepared_sha256','source_wrapper_sha256','source_payload_sha256','source_front_sha256'];
 if(!binding||hashes.some(name=>typeof binding[name]!=='string'||!/^[a-f0-9]{64}$/.test(binding[name]))||typeof binding.wrapper_url!=='string'||!binding.wrapper_url)throw Error('Invalid front delivery binding');
 if(packet.prepared.source_wrapper_sha256!==binding.source_wrapper_sha256||packet.prepared.source_payload_sha256!==binding.source_payload_sha256||packet.prepared.sides[0]?.proof?.source_sha256!==binding.source_front_sha256)throw Error('Front source binding differs');
 if(!Array.isArray(packet.baseTags)||packet.baseTags.length!==1||typeof packet.baseTags[0]!=='string')throw Error('Front resource base tag differs');
 const session={packet,binding:canonicalJSON(binding),source:packet.sides[0],side:canonicalJSON(packet.prepared.sides[0]),modules:canonicalJSON(packet.prepared.modules||{}),base:resourceBase(packet),baseTag:packet.baseTags[0],attached:false};
 session.complete=new Promise(resolve=>session.resolve=resolve);return session;
}
function startSession(packet,session){projectionTaskCloseAll();if(frontSession)frontSession.resolve(false);accepted=packet.token;reservedToken=Math.max(reservedToken,accepted);current=packet;preparedTasks=[];frontSession=session;return show(packet.requestedAt,0)}
async function attachComplete(packet){
 const session=frontSession,shown=current;if(!session||!shown||packet?.id!==shown.id||packet?.token!==accepted||session.packet!==shown)return false;
 try{
  if(packet.frontOnly||!Array.isArray(packet.sides)||packet.sides.length!==2||!packet.sides.every(value=>typeof value==='string')||!Array.isArray(packet.prepared?.sides)||packet.prepared.sides.length!==2)throw Error('Complete attachment must contain both original sides');
  if(canonicalJSON(packet.deliveryBinding)!==session.binding||packet.prepared.source_wrapper_sha256!==shown.deliveryBinding.source_wrapper_sha256||packet.prepared.source_payload_sha256!==shown.deliveryBinding.source_payload_sha256)throw Error('Complete attachment source binding differs');
  if(resourceBase(packet)!==session.base||!Array.isArray(packet.baseTags)||packet.baseTags.length!==2||packet.baseTags[0]!==session.baseTag)throw Error('Complete attachment resource base differs');
  if(canonicalJSON(packet.prepared.modules||{})!==session.modules)throw Error('Complete attachment module cohort differs');
  if(packet.sides[0]!==session.source||shown.sides[0]!==session.source||canonicalJSON(packet.prepared.sides[0])!==session.side||canonicalJSON(shown.prepared.sides[0])!==session.side)throw Error('Complete attachment front differs');
  if(session.attached){if(canonicalJSON(packet.sides)!==canonicalJSON(shown.sides)||canonicalJSON(packet.prepared)!==canonicalJSON(shown.prepared))throw Error('Complete attachment changed after verification');return true}
  shown.sides=packet.sides;shown.prepared=packet.prepared;shown.baseTags=packet.baseTags;shown.frontOnly=false;session.attached=true;session.resolve(true);
  const front=preparedTasks[0]?.view;if(front&&ownsView(front)&&front.entry.node===side)prepareBack(shown);return true;
 }catch(error){if(current===shown&&frontSession===session){session.resolve(false);fail(error,shown,accepted)}throw error}
}
function cancel(token){if(!Number.isSafeInteger(token)||token<=accepted||token<=reservedToken)return false;projectionTaskCloseAll();reservedToken=token;sequence++;if(frontSession)frontSession.resolve(false);frontSession=null;current=null;preparedTasks=[];record=null;working=false;flip.disabled=true;if(typeof committedView!=='undefined')committedView=null;return true}

function fail(error,packet,token){if(current!==packet||token!==accepted)return;if(typeof committedView!=='undefined')committedView=null;working=false;flip.disabled=false;parent.postMessage({type:'study-source-error',id:packet.id,token:accepted,message:String(error.message||error),stack:error.stack},origin)}
flip.onclick=()=>{if(!current||working)return;const packet=current,token=accepted;show(clock(),answer?0:1).catch(error=>fail(error,packet,token))};document.addEventListener('keydown',key);
window.StudySharedFrame={cancel,attachComplete,configureConsumer,snapshot:consumerSnapshot,dispose:disposeConsumer,async show(value){if(typeof value!=='boolean'||frameDisposed)throw Error('Invalid prepared side');if(!current)return false;return show(clock(),value?1:0)},async refresh(){if(!current||!consumer||frameDisposed)return false;consumerRevision++;committedView=null;return show(clock(),answer?1:0)},async mountFront(packet){if(frameDisposed||!accepts(packet,1)||packet.frontOnly!==true)return false;const session=captureFront(packet);return startSession(packet,session)},async mount(packet){if(frameDisposed||!accepts(packet,2)||packet.frontOnly)return false;resourceBase(packet);return startSession(packet,null)}};
})();'''


PREPARED_FRAME_RUNTIME = PREPARED_FRAME_RUNTIME.replace(
    '// A source module must reuse', AUTHORED_ALGORITHM_RUNTIME + '// A source module must reuse', 1)


# Merge the accepted complete compiled path with the current learning consumer.
# Producer assets/certificates are delivery data; the runtime never branches by book.
_COMPILED_FRAME_PATCHES = (
    (r'''const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();
let side=document.getElementById('study-side'),current=null,accepted=0,reservedToken=0,sequence=0,answer=false,working=false,record=null,preparedTasks=[],frontSession=null;const realms=[{node:side,key:null,ready:null,modules:new Set()}];document.body.style.overflow='hidden';
''', r'''const origin=new URL(document.baseURI).origin,flip=document.getElementById('study-flip'),records=[],scriptCache=new Map();
// Proofs are keyed weakly by the original cache promise. No owner or extra cache.
const resourceProofs=new WeakMap();
function verifiedResourceString(reader,url,pin,text){
 try{
  if(reader!==resource||typeof url!=='string'||typeof pin!=='string'||!/^[a-f0-9]{64}$/.test(pin)||typeof text!=='string')return false;
  const task=scriptCache.get(url+'|'+pin),proof=task&&resourceProofs.get(task);
  return!!proof&&proof.pin===pin&&proof.text===text;
 }catch(_){return false}
}

let side=document.getElementById('study-side'),current=null,accepted=0,reservedToken=0,sequence=0,answer=false,working=false,record=null,preparedTasks=[],frontSession=null;const realms=[{node:side,key:null,ready:null,modules:new Set()}];document.body.style.overflow='hidden';
'''),
    (r'''function key(event){if(typeof consumerKey==='function'&&consumerKey(event))return;if(event.target.closest('input,select,textarea,button,summary,a,[contenteditable]'))return;if(event.code==='Space'){event.preventDefault();flip.click()}if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();parent.postMessage({type:'study-navigate',direction:event.key==='ArrowRight'?1:-1},origin)}}
function execute(doc,code,pin){const script=doc.createElement('script'),win=doc.defaultView;let failure=null;const catchError=event=>{failure=event.error||Error(event.message||'Authored script execution failed')};script.textContent=current?.metricsAsset?code+'\n//# sourceURL=study-source-'+(pin||'anonymous')+'.js':code;win.addEventListener('error',catchError);try{doc.head.append(script)}finally{script.remove();win.removeEventListener('error',catchError)}if(failure)throw failure}
function stage(node){node.removeAttribute('id');node.setAttribute('aria-hidden','true');node.inert=true;node.style.cssText='position:absolute;left:0;top:calc(100vh + 100px);display:block;width:100%;height:100%;border:0'}
''', r'''function key(event){if(typeof consumerKey==='function'&&consumerKey(event))return;if(event.target.closest('input,select,textarea,button,summary,a,[contenteditable]'))return;if(event.code==='Space'){event.preventDefault();flip.click()}if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();parent.postMessage({type:'study-navigate',direction:event.key==='ArrowRight'?1:-1},origin)}}
function execute(doc,code,pin,initialNumbering){if(initialNumbering&&['9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1','ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'].includes(pin))return initialNumbering.run(enabled=>execute(doc,enabled?adaptCompiledInitialNumbering(code,pin):code,pin));const script=doc.createElement('script'),win=doc.defaultView;let failure=null;const catchError=event=>{failure=event.error||Error(event.message||'Authored script execution failed')};script.textContent=current?.metricsAsset?code+'\n//# sourceURL=study-source-'+(pin||'anonymous')+'.js':code;win.addEventListener('error',catchError);try{doc.head.append(script)}finally{script.remove();win.removeEventListener('error',catchError)}if(failure)throw failure}
function stage(node){node.removeAttribute('id');node.setAttribute('aria-hidden','true');node.inert=true;node.style.cssText='position:absolute;left:0;top:calc(100vh + 100px);display:block;width:100%;height:100%;border:0'}
'''),
    (r'''// Legacy source resources retain Range so the LAN proxy preserves raw bytes.
async function resource(url,pin){const key=url+'|'+pin;if(scriptCache.has(key))return scriptCache.get(key);const task=(async()=>{const preparedModule=/^[a-f0-9]{64}$/.test(pin)&&new URL(url,document.baseURI).pathname.endsWith('/evidence/_study_prepared_module_'+pin+'.js'),response=await fetch(url,{...(preparedModule?{}:{headers:{Range:'bytes=0-'}}),...(typeof frameAbort!=='undefined'?{signal:frameAbort.signal}:{})});if(!response.ok)throw Error('Prepared resource HTTP '+response.status);let total=null;if(response.status===206){const range=/^bytes 0-(\d+)\/(\d+)$/i.exec(response.headers.get('Content-Range')||'');if(!range||!Number.isSafeInteger(Number(range[2]))||Number(range[2])<=0||Number(range[1])!==Number(range[2])-1)throw Error('Prepared resource range is not complete');total=Number(range[2])}const text=await response.text();if(total!==null&&new TextEncoder().encode(text).byteLength!==total)throw Error('Prepared resource byte length differs from complete range');if(!await knownPinMatches(text,pin))throw Error('Prepared resource byte SHA differs');return text})();scriptCache.set(key,task);task.catch(()=>{if(scriptCache.get(key)===task)scriptCache.delete(key)});while(scriptCache.size>24)scriptCache.delete(scriptCache.keys().next().value);return task}
// Validate every execution rule before starting requests. The verified reads
''', r'''// Legacy source resources retain Range so the LAN proxy preserves raw bytes.
async function resource(url,pin,phase){const key=url+'|'+pin;if(scriptCache.has(key))return scriptCache.get(key);const task=(async()=>{phase?.asset(pin,'start');const preparedModule=/^[a-f0-9]{64}$/.test(pin)&&new URL(url,document.baseURI).pathname.endsWith('/evidence/_study_prepared_module_'+pin+'.js'),response=await fetch(url,{...(preparedModule?{}:{headers:{Range:'bytes=0-'}}),...(typeof frameAbort!=='undefined'?{signal:frameAbort.signal}:{})});phase?.asset(pin,'headers',response.status);if(!response.ok)throw Error('Prepared resource HTTP '+response.status);let total=null;if(response.status===206){const range=/^bytes 0-(\d+)\/(\d+)$/i.exec(response.headers.get('Content-Range')||'');if(!range||!Number.isSafeInteger(Number(range[2]))||Number(range[2])<=0||Number(range[1])!==Number(range[2])-1)throw Error('Prepared resource range is not complete');total=Number(range[2])}const text=await response.text();phase?.asset(pin,'text',text.length);if(total!==null&&new TextEncoder().encode(text).byteLength!==total)throw Error('Prepared resource byte length differs from complete range');if(!await knownPinMatches(text,pin))throw Error('Prepared resource byte SHA differs');phase?.asset(pin,'verified');return text})();scriptCache.set(key,task);task.then(text=>{try{if(typeof text==='string'&&typeof pin==='string'&&/^[a-f0-9]{64}$/.test(pin)&&scriptCache.get(key)===task)resourceProofs.set(task,{text,pin})}catch(_){}},()=>{});task.catch(()=>{phase?.asset(pin,'failed');if(scriptCache.get(key)===task)scriptCache.delete(key)});while(scriptCache.size>24)scriptCache.delete(scriptCache.keys().next().value);return task}
// Validate every execution rule before starting requests. The verified reads
'''),
    (r'''function installCigen(win,doc){const known=new Map(),selector='iframe.etymology-source-frame';let scheduled=false,batchDepth=0,dirty=false;
 function layout(frame){if(batchDepth){dirty=true;return}const entry=known.get(frame);if(!entry||!doc.contains(frame)||frame.getBoundingClientRect().width<=0)return;const meaning=frame.closest('.meaning-section'),sample=meaning?.querySelector('.form-row,.primary-definition .field-content');if(sample){const text=win.getComputedStyle(sample);frame.style.fontSize=text.fontSize;frame.style.lineHeight=text.lineHeight}const style=win.getComputedStyle(frame),title=meaning?.querySelector('.primary-definition .field-title'),callout=meaning?.querySelector('.field-callout'),tag=meaning?.querySelector('.level-list li'),font={fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color},metrics={'--ety-text-size':style.fontSize,'--ety-text-line':style.lineHeight};if(title){const t=win.getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':t.fontSize,'--ety-title-line':t.lineHeight,'--ety-title-gap':t.marginBottom})}if(callout)metrics['--ety-section-space']=win.getComputedStyle(callout).paddingTop;if(tag){const t=win.getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':t.fontSize,'--ety-tag-line':t.lineHeight,'--ety-tag-padding':t.padding,'--ety-tag-gap':win.getComputedStyle(tag.parentElement).gap})}const signature=JSON.stringify([Math.round(frame.getBoundingClientRect().width),font,metrics]);if(signature===entry.signature)return;entry.signature=signature;entry.ready=false;entry.readySignature=null;frame.contentWindow.postMessage({type:'cigen:layout',font,studySignature:signature},'*');frame.contentWindow.postMessage({type:'cigen:theme',metrics,studySignature:signature},'*')}
 const sizes=new win.ResizeObserver(entries=>{for(const entry of entries)layout(entry.target)});
 function refresh(){for(const [frame]of known)if(!doc.contains(frame)){sizes.unobserve(frame);known.delete(frame)}for(const frame of doc.querySelectorAll(selector))if(!known.has(frame)){known.set(frame,{signature:null,height:null,inits:0,ready:false,error:null});sizes.observe(frame);frame.addEventListener('load',()=>{const entry=known.get(frame);if(entry){entry.signature=null;entry.inits++;layout(frame)}})}if(batchDepth){dirty=true;return}for(const frame of known.keys())layout(frame)}
 function batch(action){batchDepth++;dirty=true;try{refresh();return action()}finally{if(--batchDepth===0&&dirty){dirty=false;refresh()}}}
 new win.MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh()})}).observe(doc.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden']});win.addEventListener('resize',refresh);win.addEventListener('message',event=>{const data=event.data;if(!['cigen:size','study-child-ready','study-child-error','study-child-phase'].includes(data?.type))return;const frame=Array.from(known.keys()).find(node=>node.contentWindow===event.source);if(!frame)return;const entry=known.get(frame);if(data.type!=='cigen:size'){if(data.type==='study-child-phase'){entry.phases=entry.phases||[];entry.phases.push(data);if(entry.phases.length>12)entry.phases.splice(6,1);return}entry.lastReady=data;if(data.token!==frame.dataset.studyChildToken||data.sourceSha!==frame.dataset.studyChildSource)return;if(data.type==='study-child-error'){entry.error=Error((data.message||'Original child initialization failed')+' ['+(data.filename||'')+':'+(data.line||'')+']');win.StudyPreparedDiagnostic?.({event:'child-error',...data});return}if(entry.error)return;if(data.signature!==entry.signature||!Number.isFinite(data.height)||data.height<=0||Math.abs(data.width-frame.getBoundingClientRect().width)>1)return;entry.ready=true;entry.readySignature=data.signature;entry.readyWidth=data.width}if(!Number.isFinite(data.height)||data.height<=0)return;entry.height=data.height;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value});win.__ankiCigenFrames={refresh,batch,known};
}
''', r'''function installCigen(win,doc){const known=new Map(),selector='iframe.etymology-source-frame';let scheduled=false,batchDepth=0,dirty=false;
/* Local to the serialized installCigen realm; no FRAME closure references. */
 const qaNames=['refresh','layout','iframeSelector','firstGeometry','styleBlock','repeatGeometry'];
 let qaEnabled=false,qaFinalDepth=0;
 const qaCosts={batchFinallyCount:0,batchFinallyMs:0,batchIframeSelectorMs:0,batchFirstGeometryMs:0,batchStyleBlockMs:0,batchRepeatGeometryMs:0};
 for(const name of qaNames){qaCosts[name+'Count']=0;qaCosts[name+'Ms']=0}
 function qaNow(){try{const value=win.performance.now();return Number.isFinite(value)?value:0}catch(_){return 0}}
 function qaMeasure(name,action){if(!qaEnabled)return action();const started=qaNow();qaCosts[name+'Count']++;try{return action()}finally{const elapsed=Math.max(0,qaNow()-started);qaCosts[name+'Ms']+=elapsed;if(qaFinalDepth&&['iframeSelector','firstGeometry','styleBlock','repeatGeometry'].includes(name))qaCosts['batch'+name[0].toUpperCase()+name.slice(1)+'Ms']+=elapsed}}
 function qaCostReset(){for(const name of Object.keys(qaCosts))qaCosts[name]=0;qaFinalDepth=0;qaEnabled=true}
 function qaCostSeal(){qaEnabled=false;return Object.freeze({...qaCosts})}

 function layout(frame){return qaMeasure('layout',()=>{if(batchDepth){dirty=true;return}const entry=known.get(frame);if(!entry||!doc.contains(frame)||qaMeasure('firstGeometry',()=>frame.getBoundingClientRect().width)<=0)return;const {font,metrics}=qaMeasure('styleBlock',()=>{const meaning=frame.closest('.meaning-section'),sample=meaning?.querySelector('.form-row,.primary-definition .field-content');if(sample){const text=win.getComputedStyle(sample);frame.style.fontSize=text.fontSize;frame.style.lineHeight=text.lineHeight}const style=win.getComputedStyle(frame),title=meaning?.querySelector('.primary-definition .field-title'),callout=meaning?.querySelector('.field-callout'),tag=meaning?.querySelector('.level-list li'),font={fontFamily:style.fontFamily,fontSize:style.fontSize,lineHeight:style.lineHeight,color:style.color},metrics={'--ety-text-size':style.fontSize,'--ety-text-line':style.lineHeight};if(title){const t=win.getComputedStyle(title);Object.assign(metrics,{'--ety-title-size':t.fontSize,'--ety-title-line':t.lineHeight,'--ety-title-gap':t.marginBottom})}if(callout)metrics['--ety-section-space']=win.getComputedStyle(callout).paddingTop;if(tag){const t=win.getComputedStyle(tag);Object.assign(metrics,{'--ety-tag-size':t.fontSize,'--ety-tag-line':t.lineHeight,'--ety-tag-padding':t.padding,'--ety-tag-gap':win.getComputedStyle(tag.parentElement).gap})}return{font,metrics}});const signature=JSON.stringify([Math.round(qaMeasure('repeatGeometry',()=>frame.getBoundingClientRect().width)),font,metrics]);if(signature===entry.signature)return;entry.signature=signature;entry.ready=false;entry.readySignature=null;frame.contentWindow.postMessage({type:'cigen:layout',font,studySignature:signature},'*');frame.contentWindow.postMessage({type:'cigen:theme',metrics,studySignature:signature},'*')})}
 const sizes=new win.ResizeObserver(entries=>{for(const entry of entries)layout(entry.target)});
 function refresh(){return qaMeasure('refresh',()=>{for(const [frame]of known)if(!doc.contains(frame)){sizes.unobserve(frame);known.delete(frame)}for(const frame of qaMeasure('iframeSelector',()=>doc.querySelectorAll(selector)))if(!known.has(frame)){known.set(frame,{signature:null,height:null,inits:0,ready:false,error:null});sizes.observe(frame);frame.addEventListener('load',()=>{const entry=known.get(frame);if(entry){entry.signature=null;entry.inits++;layout(frame)}})}if(batchDepth){dirty=true;return}for(const frame of known.keys())layout(frame)})}
 function batch(action,qaClock){batchDepth++;dirty=true;try{refresh();return action()}finally{if(--batchDepth===0&&dirty){dirty=false;const qaRefreshStarted=qaClock?.now();const qaBatchStarted=qaEnabled?qaNow():null;if(qaEnabled){qaCosts.batchFinallyCount++;qaFinalDepth++}try{refresh()}finally{if(qaBatchStarted!==null){qaCosts.batchFinallyMs+=Math.max(0,qaNow()-qaBatchStarted);qaFinalDepth--}qaClock?.span('batch-finally-refresh',qaRefreshStarted)}}}}
 new win.MutationObserver(()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;refresh()})}).observe(doc.body,{subtree:true,childList:true,attributes:true,attributeFilter:['class','hidden']});win.addEventListener('resize',refresh);win.addEventListener('message',event=>{const data=event.data;if(!['cigen:size','study-child-ready','study-child-error','study-child-phase'].includes(data?.type))return;const frame=Array.from(known.keys()).find(node=>node.contentWindow===event.source);if(!frame)return;const entry=known.get(frame);if(data.type!=='cigen:size'){if(data.type==='study-child-phase'){entry.phases=entry.phases||[];entry.phases.push(data);if(entry.phases.length>12)entry.phases.splice(6,1);return}entry.lastReady=data;if(data.token!==frame.dataset.studyChildToken||data.sourceSha!==frame.dataset.studyChildSource)return;if(data.type==='study-child-error'){entry.error=Error((data.message||'Original child initialization failed')+' ['+(data.filename||'')+':'+(data.line||'')+']');win.StudyPreparedDiagnostic?.({event:'child-error',...data});return}if(entry.error)return;if(data.signature!==entry.signature||!Number.isFinite(data.height)||data.height<=0||Math.abs(data.width-frame.getBoundingClientRect().width)>1)return;entry.ready=true;entry.readySignature=data.signature;entry.readyWidth=data.width}if(!Number.isFinite(data.height)||data.height<=0)return;entry.height=data.height;const value=Math.ceil(data.height)+'px';if(frame.style.height!==value)frame.style.height=value});win.__ankiCigenFrames={refresh,batch,known,qaCostReset,qaCostSeal};
}
'''),
    (r'''function childReadiness(config){let fontEpoch=0,phaseSignature=null;function phase(name,extra={}){if(!config.debug)return;const value={phase:name,...extra},signature=JSON.stringify(value);if(signature===phaseSignature)return;phaseSignature=signature;parent.postMessage({type:'study-child-phase',token:config.token,sourceSha:config.sourceSha,...value},'*')}let loaded=document.readyState==='complete',fontReady=false,layout=null,theme=null,scheduled=false,last=null,count=0,sent=null;const send=(type,extra)=>parent.postMessage({type,token:config.token,sourceSha:config.sourceSha,...extra},'*');function check(){scheduled=false;phase('measure',{loaded,fontReady,layout,theme,body:!!document.body,imagesPending:Array.from(document.images).filter(image=>!image.complete).length});if(!loaded||!fontReady||document.fonts?.status==='loading'||!layout||layout!==theme||!document.body)return;if(Array.from(document.images).some(image=>!image.complete))return;const height=Math.ceil(document.body.getBoundingClientRect().height)+1,width=document.documentElement.getBoundingClientRect().width,signature=JSON.stringify([height,width,layout]);phase('measured',{height,width,count,signature:layout});if(signature===last)count++;else{last=signature;count=0}if(height>1&&count>=2){if(sent!==signature){sent=signature;send('study-child-ready',{height,width,signature:layout})}}else request()}function request(){if(scheduled)return;scheduled=true;setTimeout(check,0)}function fonts(){const epoch=++fontEpoch;fontReady=false;queueMicrotask(()=>{document.body?.getBoundingClientRect();Promise.resolve(document.fonts?.ready).then(()=>{if(epoch!==fontEpoch)return;fontReady=document.fonts?.status!=='loading';request()})})}window.addEventListener('load',()=>{loaded=true;if(document.body&&typeof ResizeObserver==='function')new ResizeObserver(request).observe(document.body);fonts()},{once:true});window.addEventListener('message',event=>{if(event.source!==parent||!event.data?.studySignature)return;if(event.data.type==='cigen:layout')layout=event.data.studySignature;if(event.data.type==='cigen:theme')theme=event.data.studySignature;count=0;last=null;fonts()});window.addEventListener('error',event=>send('study-child-error',{message:event.message||'Original child resource failed',filename:event.filename,line:event.lineno,stack:event.error?.stack}),true);document.addEventListener('load',request,true);document.fonts?.addEventListener?.('loadingdone',fonts);document.fonts?.addEventListener?.('loadingerror',fonts);if(loaded)fonts();phase('installed',{state:document.readyState})}
function gateMemberCache(doc){
''', r'''function childReadiness(config){let fontEpoch=0,phaseSignature=null;function phase(name,extra={}){if(!config.debug)return;const value={phase:name,...extra},signature=JSON.stringify(value);if(signature===phaseSignature)return;phaseSignature=signature;parent.postMessage({type:'study-child-phase',token:config.token,sourceSha:config.sourceSha,...value},'*')}let loaded=document.readyState==='complete',fontReady=false,layout=null,theme=null,scheduled=false,last=null,count=0,sent=null;const send=(type,extra)=>parent.postMessage({type,token:config.token,sourceSha:config.sourceSha,...extra},'*');function check(){scheduled=false;phase('measure',{loaded,fontReady,layout,theme,body:!!document.body,imagesPending:Array.from(document.images).filter(image=>!image.complete).length});if(!loaded||!fontReady||document.fonts?.status==='loading'||!layout||layout!==theme||!document.body)return;if(Array.from(document.images).some(image=>!image.complete))return;const height=Math.ceil(document.body.getBoundingClientRect().height)+1,width=document.documentElement.getBoundingClientRect().width,signature=JSON.stringify([height,width,layout]);phase('measured',{height,width,count,signature:layout});if(signature===last)count++;else{last=signature;count=0}if(height>1&&count>=2){if(sent!==signature){sent=signature;send('study-child-ready',{height,width,signature:layout})}}else request()}function request(){if(scheduled)return;scheduled=true;setTimeout(check,0)}function fonts(){const epoch=++fontEpoch;fontReady=false;queueMicrotask(()=>{document.body?.getBoundingClientRect();Promise.resolve(document.fonts?.ready).then(()=>{if(epoch!==fontEpoch)return;fontReady=document.fonts?.status!=='loading';request()})})}window.addEventListener('load',()=>{loaded=true;if(document.body&&typeof ResizeObserver==='function')new ResizeObserver(request).observe(document.body);fonts()},{once:true});window.addEventListener('message',event=>{if(event.source!==parent||!event.data?.studySignature)return;if(event.data.type==='cigen:layout')layout=event.data.studySignature;if(event.data.type==='cigen:theme')theme=event.data.studySignature;count=0;last=null;fonts()});window.addEventListener('error',event=>send('study-child-error',{message:event.message||'Original child resource failed',filename:event.filename,line:event.lineno,stack:event.error?.stack}),true);document.addEventListener('load',request,true);document.fonts?.addEventListener?.('loadingdone',fonts);document.fonts?.addEventListener?.('loadingerror',fonts);if(loaded)fonts();phase('installed',{state:document.readyState})}
/* QA only. WeakMap values contain pure scalars; no packet or node references. */
const qaLayoutCostRecords=new WeakMap();
function qaLayoutCostNow(){try{const value=performance.now();return Number.isFinite(value)?value:0}catch(_){return 0}}
function qaLayoutCostClear(doc){qaLayoutCostRecords.delete(doc);try{doc.defaultView?.__ankiCigenFrames?.qaCostSeal?.()}catch(_){}}
function qaLayoutCostBegin(entry,packet,viewToken){try{entry.win.__ankiCigenFrames.qaCostReset();qaLayoutCostRecords.set(entry.doc,{id:packet.id,token:packet.token,viewToken,active:true,sealed:null,gateCalls:0,gateChecks:0,gateCheckMs:0,gateMaxCheckMs:0,gateFirstCheckAt:null,gateFirstAllReadyAt:null,gateFinishedAt:null,gateReadyChecks:0,gateNativeBlocked:0,gateChildReadyBlocked:0,gateChildSignatureBlocked:0,gateChildWidthBlocked:0,gateFontsBlocked:0,gateLastBlocker:'none',snapshotCount:0,snapshotMs:0,snapshotMaxMs:0,gateResult:'pending'})}catch(_){}}
function qaLayoutCostGate(entry){const record=qaLayoutCostRecords.get(entry.doc);if(!record?.active||record.viewToken!==entry.viewToken)return null;record.gateCalls++;return record}
function qaLayoutCostCheckStart(record){if(!record?.active)return null;const at=qaLayoutCostNow();record.gateChecks++;if(record.gateFirstCheckAt===null)record.gateFirstCheckAt=at;return at}
function qaLayoutCostCheckEnd(record,started){if(!record?.active||started===null)return;const elapsed=Math.max(0,qaLayoutCostNow()-started);record.gateCheckMs+=elapsed;record.gateMaxCheckMs=Math.max(record.gateMaxCheckMs,elapsed)}
function qaLayoutCostCondition(record,kind,value){if(record?.active&&!value){record['gate'+kind+'Blocked']++;record.gateLastBlocker=kind}return value}
function qaLayoutCostReady(record,ready){if(record?.active&&ready){record.gateReadyChecks++;if(record.gateFirstAllReadyAt===null)record.gateFirstAllReadyAt=qaLayoutCostNow()}}
function qaLayoutCostSnapshot(record,action){if(!record?.active)return action();const at=qaLayoutCostNow();record.snapshotCount++;try{return action()}finally{const elapsed=Math.max(0,qaLayoutCostNow()-at);record.snapshotMs+=elapsed;record.snapshotMaxMs=Math.max(record.snapshotMaxMs,elapsed)}}
function qaLayoutCostResult(record,result){if(record?.active){record.gateResult=result;record.gateFinishedAt=qaLayoutCostNow()}}
function qaLayoutCostSeal(entry,packet,viewToken){try{const r=qaLayoutCostRecords.get(entry.doc);if(!r?.active||r.id!==packet.id||r.token!==packet.token||r.viewToken!==viewToken)return;const c=entry.win.__ankiCigenFrames.qaCostSeal();r.active=false;r.sealed=Object.freeze({schema:'study-compiled-layout-cost.v1',scope:'body-adoption-to-first-full-gate',id:r.id,token:r.token,viewToken:r.viewToken,timeOrigin:performance.timeOrigin,cigenRefreshCount:c.refreshCount,cigenRefreshMs:c.refreshMs,cigenLayoutCount:c.layoutCount,cigenLayoutMs:c.layoutMs,iframeSelectorCount:c.iframeSelectorCount,iframeSelectorMs:c.iframeSelectorMs,firstGeometryCount:c.firstGeometryCount,firstGeometryMs:c.firstGeometryMs,styleBlockCount:c.styleBlockCount,styleBlockMs:c.styleBlockMs,repeatGeometryCount:c.repeatGeometryCount,repeatGeometryMs:c.repeatGeometryMs,batchFinallyCount:c.batchFinallyCount,batchFinallyMs:c.batchFinallyMs,batchIframeSelectorMs:c.batchIframeSelectorMs,batchFirstGeometryMs:c.batchFirstGeometryMs,batchStyleBlockMs:c.batchStyleBlockMs,batchRepeatGeometryMs:c.batchRepeatGeometryMs,gateCalls:r.gateCalls,gateChecks:r.gateChecks,gateCheckMs:r.gateCheckMs,gateMaxCheckMs:r.gateMaxCheckMs,gateFirstCheckAt:r.gateFirstCheckAt,gateFirstAllReadyAt:r.gateFirstAllReadyAt,gateFinishedAt:r.gateFinishedAt,gateReadyChecks:r.gateReadyChecks,gateNativeBlocked:r.gateNativeBlocked,gateChildReadyBlocked:r.gateChildReadyBlocked,gateChildSignatureBlocked:r.gateChildSignatureBlocked,gateChildWidthBlocked:r.gateChildWidthBlocked,gateFontsBlocked:r.gateFontsBlocked,gateLastBlocker:r.gateLastBlocker,snapshotCount:r.snapshotCount,snapshotMs:r.snapshotMs,snapshotMaxMs:r.snapshotMaxMs,gateResult:r.gateResult})}catch(_){}}
if(!('StudyCompiledLayoutCostStatus' in window))Object.defineProperty(window,'StudyCompiledLayoutCostStatus',{configurable:false,writable:false,value:Object.freeze({read(target){try{const entry=realms.find(value=>value.doc===target&&value.node===side&&value.packet===current&&value.node.isConnected&&value.node.contentDocument===target),record=qaLayoutCostRecords.get(target);if(!entry||!record?.sealed||record.id!==current?.id||record.token!==current?.token||record.viewToken!==entry.viewToken)return null;return record.sealed}catch(_){return null}}})});

function gateMemberCache(doc){
'''),
    (r'''}
function waitPrepared(entry,valid,beganAt=null){const began=beganAt===null?performance.now():beganAt;let previous=null,same=0,members=null;const release=()=>{members?.dispose();members=null},select=(doc,kind)=>{if(!members||members.doc!==doc){release();members=gateMemberCache(doc)}return members.read(kind)};return new Promise((finish,fail)=>{const resolve=value=>{release();finish(value)},reject=error=>{release();fail(error)};function check(){try{if(!valid()){resolve(false);return}const {doc,win}=entry,frames=select(doc,'frames').filter(frame=>frame.getBoundingClientRect().width>0);for(const frame of frames){const state=win.__ankiCigenFrames.known.get(frame);if(state?.error){reject(state.error);return}}const native=select(doc,'native').slice(0,1).map(node=>node.dataset.nativeState||'preparing');if(native.includes('failed')){reject(Error(doc.querySelector('.anki-final-status')?.textContent||'Original native validation failed'));return}const ready=native.every(value=>value==='ready')&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return state?.ready&&state.readySignature===state.signature&&Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1})&&doc.fonts?.status!=='loading';const signature=ready?JSON.stringify(snapshot(doc,false)):null;if(ready&&signature===previous)same++;else same=0;previous=signature;if(ready&&same>=2){resolve(true);return}if(performance.now()-began>10000){reject(Error('Connected original card preparation timed out: '+JSON.stringify({native,fonts:doc.fonts?.status,frames:frames.map(frame=>({width:frame.getBoundingClientRect().width,proof:frame.dataset.studyChildSource,token:frame.dataset.studyChildToken,...win.__ankiCigenFrames.known.get(frame)}))})));return}requestAnimationFrame(check)}catch(error){reject(error)}}try{requestAnimationFrame(check)}catch(error){release();throw error}})}
async function prepareView(packet,index,requestedAt){const token=++sequence,prepared=packet.prepared?.sides?.[index];if(!prepared)throw Error('Missing proven prepared side');const valid=()=>packet===current&&token===sequence;
 const row={card:packet.id,side:index?'back-preparing':'front-preparing',token:accepted+'-'+token,request:requestedAt,reason:'connected-preparation',events:[]};if(packet.metricsAsset){records.push(row);if(records.length>20)records.shift();report();}
 const verified=await Promise.all([knownPinMatches(packet.sides[index],prepared.proof.source_sha256),knownPinMatches(prepared.html,prepared.proof.expanded_sha256)]);if(!verified.every(Boolean))throw Error('Prepared body differs from its source proof');if(!valid())return null;
 const parsed=new DOMParser().parseFromString(prepared.html,'text/html');if(parsed.querySelector('[autoplay]'))throw Error('Autoplay retains its original wrapper');if(/<noscript\b/i.test(prepared.html))throw Error('Prepared parsing retains original noscript semantics');parsed.querySelector('base').href=packet.base;
 const scripts=await collectAuthoredScripts(parsed,packet);
 // Source styles and module bytes are prepared before the next authored body;
 // there is no new visible half-card waiting for external script downloads.
 for(const link of parsed.querySelectorAll('link[rel~="stylesheet"][href]')){if(Array.from(link.attributes).some(a=>!['rel','href'].includes(a.name))||link.rel.trim().toLowerCase().split(/\s+/).join(' ')!=='stylesheet')throw Error('Prepared stylesheet attributes retain their original protocol');const url=new URL(link.getAttribute('href'),packet.base).href,response=await fetch(url,{signal:frameAbort.signal});if(!response.ok)throw Error('Prepared stylesheet HTTP '+response.status);const raw=await response.text();if(/@import\b|<\/style/i.test(raw))throw Error('Prepared stylesheet needs its original lifecycle');const style=parsed.createElement('style');style.textContent=raw;link.replaceWith(style)}
 if(!valid())return null;const fingerprint=JSON.stringify(Object.entries(packet.prepared.modules||{}).sort(([a],[b])=>a.localeCompare(b))),active=await realm(packet.base,fingerprint,valid);if(!valid()||!active)return null;const {win,doc}=active;active.row=row;active.packet=packet;active.viewToken=token;
 for(const item of scripts){const module=packet.prepared.modules?.[item.pin];if(module&&!active.modules.has(item.pin)){const code=await resource(new URL(module.src,document.baseURI).href,module.sha256);if(!valid())return null;const slimLoadSource=adaptNativeFineWholeProbe(adaptSharedReadingBankWarm(adaptNativeGroupCoarseBuckets(adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask(adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin);withSlimLoadChecker(win,enabled=>execute(doc,enabled?adaptNativeBankSideChecker(adaptNativeSlimLoadChecker(slimLoadSource,item.pin),item.pin):slimLoadSource,item.pin+'-prepared-'+module.sha256));active.modules.add(item.pin)}}
 win.AnkiSlimDecode?.(parsed);const history=staticHistoryCohort(parsed,packet,scripts)?stageStaticHistory(parsed):null;try{for(const [pin,raw]of Object.entries(prepared.registry)){if(!await knownPinMatches(raw,pin))throw Error('Prepared native registration SHA differs');win.AnkiSlimAssets=win.AnkiSlimAssets||{};win.AnkiSlimAssets[pin]=raw}if(!valid())return null;
 for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){if(!win.StudySlimWarm)throw Error('Prepared native module is unavailable');for(const pair of [['asSrc','asSha'],['asIndexSrc','asIndexSha']])if(payload.dataset[pair[0]])await win.StudySlimWarm.load({src:payload.dataset[pair[0]],sha256:payload.dataset[pair[1]]});const raw=payload.dataset.asSha?prepared.registry[payload.dataset.asSha]:payload.textContent;const projectionOwner=projectionTaskBegin(win,packet,index,token,active);try{await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw))}finally{projectionOwner?.close()}await win.AnkiSharedReadingBankRuntime.warm(win.AnkiFinalReadingMetadata,Array.from(parsed.querySelectorAll('.sf-en,.example-text'),node=>node.textContent))}if(!valid())return null;
 const frames=Array.from(parsed.querySelectorAll('iframe.etymology-source-frame'));if(frames.length!==prepared.children.length)throw Error('Prepared child source count differs');frames.forEach((frame,n)=>{const child=prepared.children[n],section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section'),levels=meaning&&Array.from(meaning.children).find(node=>node.classList.contains('level-section'));if(levels)levels.after(section);if(section)section.style.margin='.2rem 0 .65rem';let childHTML=child.html;if(packet.metricsAsset){let ordinal=0;childHTML=childHTML.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,code,close)=>open+code+'\n//# sourceURL=study-child-'+child.scripts[ordinal++]+'.js\n'+close)}const base='<base href="'+encode(packet.base)+'">';if(/<base\b/i.test(childHTML))childHTML=childHTML.replace(/<base\b[^>]*>/i,base);else childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+base);const childToken=String(accepted)+'-'+String(token)+'-'+n,head='<scr'+'ipt>('+childReadiness.toString()+')('+JSON.stringify({token:childToken,sourceSha:child.source_sha256,debug:!!packet.metricsAsset})+');</scr'+'ipt>';childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+head);frame.dataset.studyChildToken=childToken;frame.dataset.studyChildSource=child.source_sha256;frame.setAttribute('srcdoc',childHTML);frame.removeAttribute('data-web-etymology-srcdoc')});
 if(!valid())return null;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;
 const head=doc.createDocumentFragment(),body=doc.createDocumentFragment();for(const node of Array.from(parsed.head.childNodes))head.append(doc.adoptNode(node));for(const node of Array.from(parsed.body.childNodes))body.append(doc.adoptNode(node));for(const audio of body.querySelectorAll('audio,video')){const play=audio.play,details=()=>({src:audio.src,currentSrc:audio.currentSrc,srcAttribute:audio.getAttribute('src'),ready:audio.readyState,network:audio.networkState,connected:audio.isConnected,ownerCurrent:audio.ownerDocument===doc,ownRealmPrototype:audio instanceof win.HTMLMediaElement,mediaError:audio.error?.message});if(packet.metricsAsset){row.audio=row.audio||{attempts:0,denied:0,errors:[],events:[]};for(const event of ['loadstart','loadedmetadata','canplay','error','abort','emptied','stalled','suspend'])audio.addEventListener(event,()=>{row.audio.events.push({event,at:clock(),...details()});if(row.audio.events.length>24)row.audio.events.shift();report()})}Object.defineProperty(audio,'play',{configurable:true,writable:true,value:function(...args){if(packet.metricsAsset){row.audio.attempts++;row.audio.userActivation=win.navigator.userActivation?.isActive;row.audio.call={...details(),play:String(play).slice(0,180),targetRealmPlay:String(win.HTMLMediaElement.prototype.play).slice(0,180)};report()}if(active.node!==side){row.audioAttempts=(row.audioAttempts||0)+1;if(row.audio)row.audio.denied++;return Promise.reject(Error('Prepared media cannot play before commit'))}try{const result=Reflect.apply(play,this,args);if(!packet.metricsAsset)return result;return Promise.resolve(result).catch(error=>{row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});if(row.audio.errors.length>4)row.audio.errors.shift();report();throw error})}catch(error){if(row.audio){row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});report()}throw error}}})}copyAttributes(parsed.documentElement,doc.documentElement);copyAttributes(parsed.body,doc.body);doc.head.replaceChildren(head);doc.body.replaceChildren(body);win.scrollTo(0,0);history?.bind(doc,()=>active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.contentDocument===doc);
 // Authored scripts still run in source order. Their repeated calls to our
 // bridge are coalesced so they cannot force intermediate whole-card layouts.
 const authoredComplete=win.__ankiCigenFrames.batch(()=>{for(const item of scripts){if(!valid())return false;if(packet.prepared.modules?.[item.pin]){item.node.remove();continue}execute(doc,item.code,item.pin);item.node.remove()}return true});if(!authoredComplete||!valid())return null;
 // Media adopted from the inert parser may retain a rejected temporary-URL
''', r'''}
function waitPrepared(entry,valid,beganAt=null){const began=beganAt===null?performance.now():beganAt;const qaGate=qaLayoutCostGate(entry);let previous=null,same=0,members=null;const release=()=>{members?.dispose();members=null},select=(doc,kind)=>{if(!members||members.doc!==doc){release();members=gateMemberCache(doc)}return members.read(kind)};return new Promise((finish,fail)=>{const resolve=value=>{qaLayoutCostResult(qaGate,value?'ready':'cancelled');release();finish(value)},reject=error=>{qaLayoutCostResult(qaGate,'error');release();fail(error)};function check(){const qaCheckStarted=qaLayoutCostCheckStart(qaGate);try{if(!valid()){resolve(false);return}const {doc,win}=entry,frames=select(doc,'frames').filter(frame=>frame.getBoundingClientRect().width>0);for(const frame of frames){const state=win.__ankiCigenFrames.known.get(frame);if(state?.error){reject(state.error);return}}const native=select(doc,'native').slice(0,1).map(node=>node.dataset.nativeState||'preparing');if(native.includes('failed')){reject(Error(doc.querySelector('.anki-final-status')?.textContent||'Original native validation failed'));return}const ready=qaLayoutCostCondition(qaGate,'Native',native.every(value=>value==='ready'))&&frames.every(frame=>{const state=win.__ankiCigenFrames.known.get(frame);return qaLayoutCostCondition(qaGate,'ChildReady',state?.ready)&&qaLayoutCostCondition(qaGate,'ChildSignature',state.readySignature===state.signature)&&qaLayoutCostCondition(qaGate,'ChildWidth',Math.abs(state.readyWidth-frame.getBoundingClientRect().width)<=1)})&&qaLayoutCostCondition(qaGate,'Fonts',doc.fonts?.status!=='loading');qaLayoutCostReady(qaGate,ready);const signature=ready?JSON.stringify(qaLayoutCostSnapshot(qaGate,()=>snapshot(doc,false))):null;if(ready&&signature===previous)same++;else same=0;previous=signature;if(ready&&same>=2){resolve(true);return}if(performance.now()-began>10000){reject(Error('Connected original card preparation timed out: '+JSON.stringify({native,fonts:doc.fonts?.status,frames:frames.map(frame=>({width:frame.getBoundingClientRect().width,proof:frame.dataset.studyChildSource,token:frame.dataset.studyChildToken,...win.__ankiCigenFrames.known.get(frame)}))})));return}requestAnimationFrame(check)}catch(error){reject(error)}finally{qaLayoutCostCheckEnd(qaGate,qaCheckStarted)}}try{requestAnimationFrame(check)}catch(error){release();throw error}})}
/* Called only from the externally pinned compiled-capability FRAME. */
// The complete runtime must first pass resource SHA verification and valid().
function adaptCompiledFrozenProfile(code,pin){
 if(pin!=='e56d2656dbac64bc72fa3c53c8f303475faabf94991d47fb513eae9f450f37bc')return code;
 const edits=[[
 " 'use strict';\n const KEY=",
 " 'use strict';\n const compiledFrozenProfileReader=typeof root.__studyCompiledFrozenProfileCapture==='function'?root.__studyCompiledFrozenProfileCapture():null;\n const KEY="
 ],[
 '  const profile=JSON.parse(JSON.stringify(input));',
 "  const verifiedFrozenProfile=typeof compiledFrozenProfileReader==='function'?compiledFrozenProfileReader(doc,input):null;\n  const profile=verifiedFrozenProfile===input?input:JSON.parse(JSON.stringify(input));"
 ]];
 if(code.includes('compiledFrozenProfileReader')||edits.some(([before])=>code.split(before).length!==2))throw Error('Audited compiled frozen profile boundary differs');
 for(const [before,after]of edits)code=code.replace(before,after);return code;
}

function makeCompiledProfileSupport(assets, resource, matches, canonical, current) {
 'use strict';
 const owners=new WeakMap(), hash=/^[a-f0-9]{64}$/;
 const schema='study-compiled-card-interactions.v1';
 function fail(message){throw Error('Compiled profile: '+message)}
 function immutable(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(immutable);Object.freeze(value)}return value}
 // Only JSON parsed, binding-checked and recursively frozen load results qualify.
 const verifiedFrozenProfiles=new WeakSet();
 function rememberFrozenProfile(value){const profile=immutable(value);verifiedFrozenProfiles.add(profile);return profile}
 // One factory-lifetime reader; captures weak tables, never a request/doc/input.
 function readVerifiedFrozenProfile(doc,input){
  try{const owner=owners.get(doc);return owner&&owner.profile===input&&verifiedFrozenProfiles.has(input)&&owner.valid()===true&&current()===true?input:null}catch(_){return null}
 }
 function withFrozenCapture(win,action){
  const name='__studyCompiledFrozenProfileCapture';
  let conflict;try{conflict=name in win}catch(_){return action(false)}
  if(conflict)return action(false)
  const capture=()=>readVerifiedFrozenProfile;let installed=false;
  try{try{Object.defineProperty(win,name,{configurable:true,writable:false,value:capture});installed=true}catch(_){return action(false)}return action(true)}
  finally{if(installed)try{if(Object.getOwnPropertyDescriptor(win,name)?.value===capture)delete win[name]}catch(_){}}
 }

 function asset(value){if(!value||typeof value.src!=='string'||!/^_qa_compiled_[a-z0-9_]+\.(?:js|json|html)$/.test(value.src)||!hash.test(value.sha256||''))fail('asset descriptor');return value}
 async function load(packet,index,side,valid,phase){
  if(index!==1)return null;
  const entry=Object.prototype.hasOwnProperty.call(assets.entries,packet.id)?assets.entries[packet.id]:null;if(!entry)return null;
  if(!valid())return null;
  const source=entry.source,module=entry.module,anchors=entry.anchors;
  if(!source||!module||!anchors||anchors.schema!==schema||anchors.version!==1||entry.decoded!==true)fail('capability/schema');
  if(packet.prepared.source_wrapper_sha256!==source.wrapper_sha256||packet.prepared.source_payload_sha256!==source.payload_sha256||side.proof.source_sha256!==source.side_sha256||side.proof.expanded_sha256!==source.expanded_sha256||canonical(side.proof.registry_pins)!==canonical(source.registry_pins))fail('original side binding');
  const preparedModule=packet.prepared.modules?.[module.original_sha256];
  if(!preparedModule||preparedModule.original_sha256!==module.original_sha256||preparedModule.sha256!==module.sha256)fail('original module binding');
  if(anchors.bindings?.originalModuleSha256!==module.original_sha256||anchors.bindings?.nativeModuleSha256!==module.sha256||anchors.bindings?.derivedHTMLSha256!==entry.html.sha256)fail('external producer binding');
  phase?.point('compiled-assets-requested');const values=await Promise.all([entry.html,entry.profile,assets.runtime].map(value=>{asset(value);return resource(new URL(value.src,document.baseURI).href,value.sha256,phase)}));phase?.point('compiled-assets-verified');
  if(!valid())return null;
  const [html,raw,runtimeCode]=values;
  if(!(await Promise.all([[html,entry.html],[raw,entry.profile],[runtimeCode,assets.runtime]].map(([text,value])=>verifiedResourceString(resource,new URL(value.src,document.baseURI).href,value.sha256,text)===true?true:matches(text,value.sha256)))).every(Boolean))fail('external resource SHA');
  if(!valid())return null;phase?.point('compiled-recheck-verified');
  const profile=JSON.parse(raw);phase?.point('profile-json-parsed');
  if(profile.schema!==schema||profile.version!==1||canonical(profile.bindings)!==canonical(anchors.bindings))fail('external metadata binding');
  const result=Object.freeze({html,profile:rememberFrozenProfile(profile),runtimeCode,runtimeSha256:assets.runtime.sha256});phase?.point('profile-frozen');return result;
 }
 function bind(win,doc,value,valid){
  owners.delete(doc);
  if(!Object.prototype.hasOwnProperty.call(win,'StudyCompiledProfileBridge'))Object.defineProperty(win,'StudyCompiledProfileBridge',{configurable:false,writable:false,value:Object.freeze({get(target){const owner=owners.get(target);if(!owner)return null;if(target!==doc||!owner.valid()||!current())fail('expired document owner');return owner.profile},isCurrent(target,profile){const owner=owners.get(target);return!!owner&&target===doc&&owner.profile===profile&&owner.valid()&&current()}})});
  if(value)owners.set(doc,{profile:value.profile,valid});
 }
 return Object.freeze({load,bind,withFrozenCapture,clear(doc){owners.delete(doc)}});
}

// Experimental explicit compiled profile; caller must first authenticate the complete source/module.
function adaptActiveSlimCompiledProfile(code, originalPin) {
  'use strict';
  var approved = ["17b5c61a67f0efa96251065352361c0c8afadb61a417a3c2ed5bb611006ec0d7", "5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e", "be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"];
  if (approved.indexOf(originalPin) < 0) return code;
  var start = code.lastIndexOf('  async function hydrate() {');
  var end = code.indexOf('  window.AnkiSlimApkgHydrate = window.AnkiFinalApkgHydrate = hydrate;', start);
  var edits = [["      var raw = payload.textContent;\n      if (payload.dataset.asSrc || payload.dataset.asSha) raw = await load({ src: payload.dataset.asSrc, sha256: payload.dataset.asSha });\n      if (!alive()) return;\n      var data = JSON.parse(raw), nativeData = data;\n      if (payload.dataset.asIndexSrc || payload.dataset.asIndexSha) {\n        var nativeRaw = await load({ src: payload.dataset.asIndexSrc, sha256: payload.dataset.asIndexSha });\n        if (!alive()) return;\n        nativeData = { as_native_index: JSON.parse(nativeRaw) };\n      }\n      state.nativeIndex = index(nativeData);\n      fine = keep(window.AnkiFineChunkRuntime.install(document));\n      var token = await window.AnkiReviewedChunkProjection.prepare(data); if (!alive()) return;\n      projected = keep(window.AnkiReviewedChunkProjection.install(document, token, { isCurrent: alive }));\n      if (projected.stats().errors.length) throw Error('本卡细块核验失败');\n      bank = keep(window.AnkiSharedReadingBankRuntime.install(document, window.AnkiFinalReadingMetadata)); await bank.ready; if (!alive()) return;\n      // Install grouping on the initial empty shell, and refresh only after\n      // every loaded sense panel is complete; physical metadata is pre-pinned.\n      group = keep(window.AnkiSameSenseGroupRuntime.install(document));\n", "      var compiled = null, compiledInvalid = false, compiledBridge = window.StudyCompiledProfileBridge, compiledProfile;\n      function compiledCurrent() {\n        return alive() && compiledBridge && typeof compiledBridge.isCurrent === 'function' && compiledBridge.isCurrent(document, compiledProfile) === true;\n      }\n      function failCompiled(error) {\n        if (!compiledCurrent() || compiledInvalid) return;\n        compiledInvalid = true;\n        status.textContent = '本卡细块核验失败：' + String(error && error.message || error || 'Compiled profile invalidated');\n        if (!document.contains(status)) payload.before(status);\n        payload.dataset.nativeState = 'failed';\n      }\n      if (compiledBridge && typeof compiledBridge.get === 'function' && typeof compiledBridge.isCurrent !== 'function') throw Error('Compiled profile owner capability unavailable');\n      compiledProfile = compiledBridge && typeof compiledBridge.get === 'function' ? compiledBridge.get(document) : null;\n      if (compiledProfile) {\n        if (!compiledCurrent()) return;\n        if (compiledProfile.filter_mode !== 'host-after-authored-filter') throw Error('Compiled profile filter ownership differs');\n        if (document.querySelector('script.as-manifest')) throw Error('Compiled profile supports slotless documents only');\n        if (!window.AnkiCompiledCardRuntime || typeof window.AnkiCompiledCardRuntime.install !== 'function') throw Error('Compiled card binder unavailable');\n        compiled = keep(window.AnkiCompiledCardRuntime.install(document, compiledProfile, { isCurrent: compiledCurrent, onInvalid: failCompiled }));\n        if (!compiled || typeof compiled.refresh !== 'function' || typeof compiled.applyGrouping !== 'function' || typeof compiled.dispose !== 'function' || !compiled.ready || typeof compiled.ready.then !== 'function') throw Error('Compiled card binder contract differs');\n        await compiled.ready; if (!compiledCurrent() || compiledInvalid) return;\n        if (document.querySelector('script.as-manifest')) throw Error('Compiled profile became non-slotless during binding');\n      } else {\n      var raw = payload.textContent;\n      if (payload.dataset.asSrc || payload.dataset.asSha) raw = await load({ src: payload.dataset.asSrc, sha256: payload.dataset.asSha });\n      if (!alive()) return;\n      var data = JSON.parse(raw), nativeData = data;\n      if (payload.dataset.asIndexSrc || payload.dataset.asIndexSha) {\n        var nativeRaw = await load({ src: payload.dataset.asIndexSrc, sha256: payload.dataset.asIndexSha });\n        if (!alive()) return;\n        nativeData = { as_native_index: JSON.parse(nativeRaw) };\n      }\n      state.nativeIndex = index(nativeData);\n      fine = keep(window.AnkiFineChunkRuntime.install(document));\n      var token = await window.AnkiReviewedChunkProjection.prepare(data); if (!alive()) return;\n      projected = keep(window.AnkiReviewedChunkProjection.install(document, token, { isCurrent: alive }));\n      if (projected.stats().errors.length) throw Error('本卡细块核验失败');\n      bank = keep(window.AnkiSharedReadingBankRuntime.install(document, window.AnkiFinalReadingMetadata)); await bank.ready; if (!alive()) return;\n      // Install grouping on the initial empty shell, and refresh only after\n      // every loaded sense panel is complete; physical metadata is pre-pinned.\n      group = keep(window.AnkiSameSenseGroupRuntime.install(document));\n      }\n"], ["      fine.refresh(); projected.refresh();\n      if (projected.stats().errors.length) throw Error('本卡细块核验失败');\n      await bank.refresh(); if (!alive()) return;\n      if (slot.panel) filter(slot.panel);\n      // The compiled grouping helper checks AnkiSlimPanelReady for each\n      // individual panel before touching its processed WeakSet.\n      group.refresh();", "      if (compiled) {\n        await compiled.refresh(slot); if (!alive()) return;\n        if (slot.panel) { filter(slot.panel); compiled.applyGrouping(slot.panel); }\n      } else {\n      fine.refresh(); projected.refresh();\n      if (projected.stats().errors.length) throw Error('本卡细块核验失败');\n      await bank.refresh(); if (!alive()) return;\n      if (slot.panel) filter(slot.panel);\n      // The compiled grouping helper checks AnkiSlimPanelReady for each\n      // individual panel before touching its processed WeakSet.\n      group.refresh();\n      }"], ["      if (panel) { filter(panel); if (group) group.refresh(); }", "      if (panel) { filter(panel); if (compiled) compiled.applyGrouping(panel); else if (group) group.refresh(); }"]];
  if (start < 0 || end < start || code.indexOf('var compiledProfile = window.StudyCompiledProfileBridge') >= 0 || edits.some(function (edit) { var at = code.indexOf(edit[0]); return code.split(edit[0]).length !== 2 || at < start || at >= end; })) throw Error('Audited active Slim compiled boundary differs');
  edits.forEach(function (edit) { code = code.replace(edit[0], edit[1]); });
  return code;
}

// Includes the frozen v2 compiled branch; call this INSTEAD OF applying v2 twice.
function adaptCompiledHistorySlots(code, originalPin) {
  const approved = ["17b5c61a67f0efa96251065352361c0c8afadb61a417a3c2ed5bb611006ec0d7","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"];
  if (!approved.includes(originalPin)) return code;
  code = adaptActiveSlimCompiledProfile(code, originalPin);
  const edits = [{"before":"      var compiled = null, compiledInvalid = false, compiledBridge = window.StudyCompiledProfileBridge, compiledProfile;\n      function compiledCurrent() {\n        return alive() && compiledBridge && typeof compiledBridge.isCurrent === 'function' && compiledBridge.isCurrent(document, compiledProfile) === true;\n      }\n      function failCompiled(error) {\n        if (!compiledCurrent() || compiledInvalid) return;\n        compiledInvalid = true;\n        status.textContent = '本卡细块核验失败：' + String(error && error.message || error || 'Compiled profile invalidated');\n        if (!document.contains(status)) payload.before(status);\n        payload.dataset.nativeState = 'failed';\n      }\n","after":"      /* Compiled owner helpers are defined in hydrate scope. */\n"},{"before":"    var fine, projected, bank, group;","after":"      var compiled = null, compiledInvalid = false, compiledBridge = window.StudyCompiledProfileBridge, compiledProfile;\n      function compiledCurrent() {\n        return alive() && compiledBridge && typeof compiledBridge.isCurrent === 'function' && compiledBridge.isCurrent(document, compiledProfile) === true;\n      }\n      function failCompiled(error) {\n        if (!compiledCurrent() || compiledInvalid) return;\n        compiledInvalid = true;\n        status.textContent = '本卡细块核验失败：' + String(error && error.message || error || 'Compiled profile invalidated');\n        if (!document.contains(status)) payload.before(status);\n        payload.dataset.nativeState = 'failed';\n      }\n    var fine, projected, bank, group;"},{"before":"        if (document.querySelector('script.as-manifest')) throw Error('Compiled profile supports slotless documents only');","after":"        // Exact original excluded-history slots are validated by the binder; no other lazy slot is accepted."},{"before":"        if (document.querySelector('script.as-manifest')) throw Error('Compiled profile became non-slotless during binding');","after":"        compiled.assertHistorySlots();"},{"before":"      slot.holder.insertBefore(template.content, slot.anchor);","after":"      if (compiled && !compiled.authorizeHistoryPart(slot, part, template.content)) return false;\n      slot.holder.insertBefore(template.content, slot.anchor);"},{"before":"        if (!alive() || !document.contains(slot.manifest)) return;\n        slot.manifest.dataset.asState = 'failed';","after":"        if (!alive() || !document.contains(slot.manifest) || compiled && !compiledCurrent()) return;\n        if (compiled && error.studyCompiledHistoryFailure) { failCompiled(error); return; }\n        slot.manifest.dataset.asState = 'failed';"},{"before":"        if (alive()) { slot.holder.removeAttribute('aria-busy');","after":"        if (alive() && (!compiled || compiledCurrent())) { slot.holder.removeAttribute('aria-busy');"},{"before":"        if (alive() && document.contains(pre)) { pre.textContent = raw; pre.dataset.nativeHistoryReady = 'true'; }","after":"        if (alive() && document.contains(pre)) {\n          if (compiled && !compiled.authorizeHistoryText(pre, raw, {ready:true,failed:false})) return;\n          pre.textContent = raw; pre.dataset.nativeHistoryReady = 'true';\n        }"},{"before":"      } catch (error) { if (alive() && document.contains(pre)) pre.textContent = '证据载入失败：' + String(error.message || error); }","after":"      } catch (error) {\n        if (compiled && (!compiledCurrent() || error.studyCompiledHistoryFailure)) { if (compiledCurrent()) failCompiled(error); return; }\n        if (alive() && document.contains(pre)) {\n          var failure = '证据载入失败：' + String(error.message || error);\n          try { if (compiled && !compiled.authorizeHistoryText(pre, failure, {ready:false,failed:true})) return; }\n          catch (authorizationError) { failCompiled(authorizationError); return; }\n          pre.textContent = failure;\n        }\n      }"},{"before":"      payload.dataset.nativeState = 'ready'; scroll();","after":"      if (compiled && (!compiledCurrent() || compiledInvalid)) return;\n      payload.dataset.nativeState = 'ready'; scroll();"}];
  for (const edit of edits) {
    if (code.split(edit.before).length !== 2) throw Error("Audited compiled history boundary differs");
    code = code.replace(edit.before, edit.after);
  }
  return code;
}

// Explicit outer owner guards. Includes the frozen history-slot adapter once.
function adaptCompiledHistorySlotsOwner(code, originalPin) {
  const approved = ["17b5c61a67f0efa96251065352361c0c8afadb61a417a3c2ed5bb611006ec0d7","5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e","be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93"];
  if (!approved.includes(originalPin)) return code;
  code = adaptCompiledHistorySlots(code, originalPin);
  const edits = [{"before":"      function failCompiled(error) {","after":"      function ownsWork() { return alive() && (!compiled || !compiledInvalid && compiledCurrent()); }\n      function failCompiled(error) {"},{"before":"    async function refresh(slot) {\n      if (!alive()) return;","after":"    async function refresh(slot) {\n      if (!ownsWork()) return;"},{"before":"        await compiled.refresh(slot); if (!alive()) return;","after":"        await compiled.refresh(slot); if (!ownsWork()) return;"},{"before":"      var result = queue.then(function () { if (alive()) return task(); });","after":"      var result = queue.then(function () { if (ownsWork()) return task(); });"},{"before":"      if (!alive() || !document.contains(slot.manifest) || slot.at >= slot.value.parts.length) return false;","after":"      if (!ownsWork() || !document.contains(slot.manifest) || slot.at >= slot.value.parts.length) return false;"},{"before":"      if (!alive() || !document.contains(slot.manifest) || slot.anchor.parentElement !== slot.holder || slot.at !== position) return false;","after":"      if (!ownsWork() || !document.contains(slot.manifest) || slot.anchor.parentElement !== slot.holder || slot.at !== position) return false;"},{"before":"      if (!alive()) return false;\n      if (slot.sentinel)","after":"      if (!ownsWork()) return false;\n      if (slot.sentinel)"},{"before":"      if (!alive() || slot.busy || slot.at >= slot.value.parts.length || Date.now() < slot.retryAfter) return slot.busy || Promise.resolve();","after":"      if (!ownsWork() || slot.busy || slot.at >= slot.value.parts.length || Date.now() < slot.retryAfter) return slot.busy || Promise.resolve();"},{"before":"            if (!all || !alive() || (slot.detail && !slot.detail.open)) break;","after":"            if (!all || !ownsWork() || (slot.detail && !slot.detail.open)) break;"},{"before":"    function scroll() { if (alive()) slots.forEach","after":"    function scroll() { if (ownsWork()) slots.forEach"},{"before":"    async function history(detail) {\n      var pre","after":"    async function history(detail) {\n      if (!ownsWork()) return;\n      var pre"},{"before":"      var detail = event.target; if (!alive() || !detail.matches || !detail.matches('details[open]')) return;","after":"      var detail = event.target; if (!ownsWork() || !detail.matches || !detail.matches('details[open]')) return;"},{"before":"    function click(event) {\n      if (!alive()) return;","after":"    function click(event) {\n      if (!ownsWork()) return;"}];
  for (const edit of edits) {
    if (code.split(edit.before).length !== 2) throw Error("Audited compiled history owner boundary differs");
    code = code.replace(edit.before, edit.after);
  }
  return code;
}

const compiledAssets=JSON.parse(document.getElementById('study-compiled-assets')?.textContent||'{"entries":{}}');
/* Proposed compiled capability primitive only. The caller must authenticate
 * rawCss/attrs and capture the exact owned source/approved-author style nodes.
 * This function does NOT itself authorize skipping numbering or bind a view. */
function compiledNumberingCSSMatches(doc,records,isCurrent){
 try{
  if(typeof isCurrent!=='function'||!isCurrent()||!doc?.defaultView||!Array.isArray(records)||!records.length||records.length>16)return false;
  const win=doc.defaultView,Sheet=win.CSSStyleSheet;
  if(typeof Sheet!=='function'||typeof Sheet.prototype?.replaceSync!=='function')return false;
  const adopted=doc.adoptedStyleSheets;
  if(adopted!==undefined&&(!Number.isSafeInteger(adopted.length)||adopted.length!==0))return false;
  const sheets=Array.from(doc.styleSheets);if(sheets.length!==records.length)return false;
  const seen=new Set();let units=0;
  for(let n=0;n<records.length;n++){
   const record=records[n],node=record?.node,sheet=sheets[n];
   if(!node||seen.has(node)||node.ownerDocument!==doc||!doc.contains(node)||node.tagName!=='STYLE'||sheet.ownerNode!==node||node.sheet!==sheet)return false;
   seen.add(node);
   if(typeof record.rawCss!=='string'||!Array.isArray(record.attrs)||/@import\b/i.test(record.rawCss))return false;
   units+=record.rawCss.length;if(units>1048576)return false;
   if(node.textContent!==record.rawCss||JSON.stringify(Array.from(node.attributes,a=>[a.name,a.value]))!==JSON.stringify(record.attrs)||sheet.disabled!==false||sheet.media?.mediaText!=='')return false;
   const expected=new Sheet();expected.replaceSync(record.rawCss);
   const wanted=Array.from(expected.cssRules,r=>r.cssText),actual=Array.from(sheet.cssRules,r=>r.cssText);
   if(wanted.length!==actual.length||wanted.some((text,i)=>typeof text!=='string'||text!==actual[i]))return false;
  }
  return isCurrent()===true;
 }catch(_){return false}
}

/* Private compiled capability. Caller authenticates certificate/bindings and
 * every source byte before this factory. No public receipt/row seed is used. */
function makeCompiledInitialNumbering(doc,certificate,bindings,scripts,isCurrent){
 'use strict';
 const HISTORY='.sf-inline-history,.sf-ownership-history,.sf-ownership-authority,.sf-native-ownership-history,.sf-original-history-panel,.residual-owner-history,.sf-source-confirmation-history,.sf-semantic-resolution-history,.sf-final-history,.sf-archived-example,.sf-archived-native-example,.sf-pending,[data-native-ownership-history],[data-reviewed-source-comparison]';
 const NAME='__studyCompiledInitialNumberingCapture',attrs=node=>JSON.stringify(Array.from(node.attributes,a=>[a.name,a.value]));
 let ownedDoc=doc,list=null,rows=[],initial=[],styles=[],ancestors=[],afterAncestors=[],captured=false,consumed=false,dead=false;
 const resultStatus={schema:'study-compiled-initial-numbering-status.v1',qualified:false,readerCaptured:false,attempted:false,accepted:false,rows:certificate?.rows||0,reason:'not-consumed'};
 const owns=()=>{try{return !dead&&ownedDoc===doc&&doc.defaultView&&isCurrent()===true}catch(_){return false}};
 function ancestry(){const out=[];for(let n=list;n&&n.nodeType===1;n=n.parentElement)out.push({node:n,parent:n.parentNode,attrs:attrs(n)});return out}
 function sameRows(){if(!list||!doc.contains(list)||list.closest(HISTORY))return false;const current=Array.from(list.children);if(current.length!==rows.length)return false;for(let i=0;i<rows.length;i++){const s=rows[i],row=current[i],badge=row.querySelector('.index-tag');if(row!==s.row||attrs(row)!==s.attrs||row.hidden||row.hasAttribute('style')||row.closest(HISTORY)||badge!==s.badge||badge.closest('li.example-card')!==row||badge.closest(HISTORY)||attrs(badge)!==s.badgeAttrs||badge.childNodes.length!==1||badge.firstChild!==s.textNode||badge.firstChild.nodeType!==3||badge.textContent!==String(i+1))return false}return true}
 function sameAncestors(){const current=ancestry();return current.length===afterAncestors.length&&current.every((s,i)=>s.node===afterAncestors[i].node&&s.parent===afterAncestors[i].parent&&s.attrs===afterAncestors[i].attrs)}
 function clear(){rows=[];initial=[];styles=[];ancestors=[];afterAncestors=[];list=null}
 function disable(){resultStatus.qualified=false;resultStatus.reason='reader-capture-mismatch';consumed=true;captured=false;clear()}
 function stop(){dead=true;isCurrent=null;clear();ownedDoc=null}
 try{
  if(!owns()||!certificate?.bindings||Object.keys(certificate.bindings).length!==7||Object.values(certificate.bindings).some(value=>typeof value!=='string'||!/^[a-f0-9]{64}$/.test(value))||certificate?.schema!=='study-compiled-initial-numbering.v1'||certificate.countdownHost!=='body'||!Number.isSafeInteger(certificate.rows)||certificate.rows<1||certificate.rows>8192||JSON.stringify(scripts.map(s=>s.pin))!==JSON.stringify(certificate.cohort)||Object.entries(certificate.bindings||{}).some(([key,value])=>bindings[key]!==value))return null;
  const lists=Array.from(doc.querySelectorAll('ol.examples'));if(lists.length!==1||lists[0].closest(HISTORY)||!lists[0].parentElement?.matches('.examples-section'))return null;list=lists[0];
  const children=Array.from(list.children);if(children.length!==certificate.rows)return null;
  for(let i=0;i<children.length;i++){const row=children[i],badge=row.querySelector('.index-tag');if(row.tagName!=='LI'||row.namespaceURI!=='http://www.w3.org/1999/xhtml'||row.getAttribute('class')!=='example-card'||row.hasAttribute('is')||row.hidden||row.hasAttribute('style')||row.closest(HISTORY)||!badge||badge.closest('li.example-card')!==row||badge.closest(HISTORY)||badge.childNodes.length!==1||badge.firstChild.nodeType!==3||badge.textContent!==String(i+1))return null;rows.push({row,attrs:attrs(row),badge,badgeAttrs:attrs(badge),textNode:badge.firstChild})}
  ancestors=ancestry();const approved=certificate.approvedCss.slice();
  for(const sheet of Array.from(doc.styleSheets)){const node=sheet.ownerNode,index=approved.findIndex(text=>text===node?.textContent);if(index<0||node.tagName!=='STYLE'||!doc.contains(node))return null;initial.push({node,rawCss:approved[index],attrs:Array.from(node.attributes,a=>[a.name,a.value])});approved.splice(index,1)}
  if(approved.length||initial.length!==certificate.approvedCss.length)return null;
 }catch(_){return null}
 resultStatus.qualified=true;
 function after(pin){
  if(captured||consumed||!owns()||pin!==certificate.readerPin)return;
  try{
   if(!sameRows())return disable();const current=ancestry(),oldSet=new Set(ancestors.map(s=>s.node)),old=current.filter(s=>oldSet.has(s.node)),added=current.filter(s=>!oldSet.has(s.node));
   if(old.length!==ancestors.length||old.some((s,i)=>s.node!==ancestors[i].node)||added.length!==1)return disable();
   const wrapper=added[0].node;if(wrapper.tagName!=='DIV'||wrapper.parentNode!==doc.body||attrs(wrapper)!==JSON.stringify([['class','anki-countdown-content']]))return disable();
   for(let i=0;i<old.length;i++){const before=ancestors[i],node=old[i].node;if(before.attrs===attrs(node))continue;const original=JSON.parse(before.attrs),next=Array.from(node.attributes,a=>[a.name,a.value]),oldClass=original.find(a=>a[0]==='class');if(!oldClass||!oldClass[1].split(/\s+/).includes('vocab-card'))return disable();const wanted=original.map(a=>a[0]==='class'?[a[0],a[1].split(/\s+/).includes('rb-compact-note')?a[1]:a[1]+' rb-compact-note']:a);if(JSON.stringify(wanted)!==JSON.stringify(next))return disable()}
   const sheets=Array.from(doc.styleSheets),known=new Map(initial.map(s=>[s.node,s])),extra=sheets.filter(s=>!known.has(s.ownerNode));if(extra.length!==1)return disable();const node=extra[0].ownerNode;if(node.tagName!=='STYLE'||node.id!==certificate.countdownStyleId||node.parentNode!==doc.head||doc.getElementById(node.id)!==node||node.textContent!==certificate.countdownCss||attrs(node)!==JSON.stringify([['id',certificate.countdownStyleId]]))return disable();
   const dynamic={node,rawCss:certificate.countdownCss,attrs:[['id',certificate.countdownStyleId]]},expected=initial.filter(s=>doc.head.contains(s.node)).concat(dynamic,initial.filter(s=>!doc.head.contains(s.node)));
   if(sheets.length!==expected.length||sheets.some((s,i)=>s.ownerNode!==expected[i].node))return disable();styles=expected;afterAncestors=current;captured=true;resultStatus.readerCaptured=true;
  }catch(_){disable()}
 }
 function claim(root){if(consumed)return false;consumed=true;resultStatus.attempted=true;try{resultStatus.accepted=root===ownedDoc&&owns()&&captured&&sameRows()&&sameAncestors()&&compiledNumberingCSSMatches(doc,styles,owns)===true;resultStatus.reason=resultStatus.accepted?'accepted':'claim-mismatch';return resultStatus.accepted}catch(_){resultStatus.reason='claim-mismatch';return false}finally{rows=[];initial=[];styles=[];ancestors=[];afterAncestors=[]}}
 function run(action){if(!owns())return false;if(!captured||consumed)return action(false);const win=doc.defaultView;try{if(NAME in win)return action(false)}catch(_){return action(false)}const capture=()=>claim;let installed=false;try{try{Object.defineProperty(win,NAME,{configurable:true,writable:false,value:capture});installed=true}catch(_){return action(false)}return action(true)}finally{if(installed){try{const property=Object.getOwnPropertyDescriptor(win,NAME);if(property?.value===capture)delete win[NAME]}catch(_){}}}}
 return Object.freeze({after,run,dispose:stop,status(){return Object.freeze({...resultStatus})}});
}

/* Only after original resource SHA and common legacy->canonical adaptation. */
function adaptCompiledInitialNumbering(code,originalPin){
 const pins=['9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1','ac0546828766b0cb3645b2e5b226a2b3a4cc5a7644a25f6592695ab47c1ac042'];
 if(!pins.includes(originalPin))return code;
 if(code!==canonicalExampleNumberingSource)throw Error('Audited canonical numbering source differs');
 const edits=[['  var installed = new WeakMap();','  var installed = new WeakMap();\n  var compiledInitialNumbering = null;\n  if (typeof window.__studyCompiledInitialNumberingCapture === "function") compiledInitialNumbering = window.__studyCompiledInitialNumberingCapture();'],['    installed.set(root, handle); refresh();','    installed.set(root, handle);\n    var compiledInitialAccepted = false;\n    try { compiledInitialAccepted = typeof compiledInitialNumbering === "function" && compiledInitialNumbering(root) === true; } catch (_) {} finally { compiledInitialNumbering = null; }\n    if (!compiledInitialAccepted) refresh();']];
 if(code.includes('compiledInitialNumbering')||edits.some(([before])=>code.split(before).length!==2))throw Error('Audited compiled initial numbering boundary differs');for(const [before,after]of edits)code=code.replace(before,after);return code;
}

const compiledNumberingStatuses=new WeakMap();
if(!('StudyCompiledInitialNumberingStatus' in window))Object.defineProperty(window,'StudyCompiledInitialNumberingStatus',{configurable:false,writable:false,value:Object.freeze({read(target){try{const entry=realms.find(value=>value.doc===target&&value.node===side&&value.packet===current&&value.node.isConnected&&value.node.contentDocument===target),record=compiledNumberingStatuses.get(target);if(!entry||!record||record.id!==current?.id||record.token!==current?.token||record.viewToken!==entry.viewToken)return null;return Object.freeze({...record.status,id:record.id,token:record.token,viewToken:record.viewToken})}catch(_){return null}}})});

function compiledInitialNumberingCertificate(packet){return compiledAssets.entries[packet.id]?.initial_numbering_certificate??null}
/* Isolated QA clocks only: no selectors, geometry, timers, Promise observers or source text. */
let qaCompiledPhaseTaken=false;
function qaCompiledPhase(packet,index,sequenceValue,isCurrent){
 try{
  if(qaCompiledPhaseTaken||index!==1||!Object.prototype.hasOwnProperty.call(compiledAssets.entries,packet.id)||!isCurrent())return null;
  qaCompiledPhaseTaken=true;
  const entry=compiledAssets.entries[packet.id],pins=new Map([[entry.html.sha256,'derived-html'],[entry.profile.sha256,'profile'],[compiledAssets.runtime.sha256,'runtime']]),assets=new Map();
  const points=new Set(['prepare-start','source-proofs-verified','compiled-assets-requested','compiled-assets-verified','compiled-recheck-verified','profile-json-parsed','profile-frozen','compiled-load-complete','derived-dom-parsed','authored-resources-ready','styles-ready','realm-ready','native-module-ready','registry-ready','body-adoption-start','body-connected','authors-complete','media-reset-complete','full-gate-start','full-gate-complete']);
  let sent=0,spanOrdinal=0;const seen=new Set();
  const now=()=>{try{const value=performance.now();return Number.isFinite(value)?value:null}catch(_){return null}};
  function send(row){try{if(sent>=64||!isCurrent())return;const at=now();if(at===null||!Number.isFinite(performance.timeOrigin))return;const value={type:'study-compiled-phase-clock',schema:'study-compiled-phase-clock.v1',id:packet.id,token:packet.token,sequence:sequenceValue,side:1,source:'shared-frame',timeOrigin:performance.timeOrigin,at,...row};parent.postMessage(value,'*');sent++}catch(_){}}
  function point(label){try{if(!points.has(label)||seen.has(label))return;seen.add(label);send({kind:'point',label})}catch(_){}}
  function span(label,start,pin){try{if(!['author-execute','batch-finally-refresh'].includes(label)||!Number.isFinite(start))return;const end=now();if(end===null||end<start)return;const row={kind:'span',label,ordinal:++spanOrdinal,start,end,elapsed:end-start};if(label==='author-execute'){if(!/^[a-f0-9]{64}$/.test(pin||''))return;row.pin=pin}send(row)}catch(_){}}
  function asset(pin,step,value){try{const resource=pins.get(pin);if(!resource||!['start','headers','text','verified','failed'].includes(step))return;if(step==='failed'){assets.delete(pin);return}let row=assets.get(pin);if(step==='start'){if(row)return;row={kind:'resource',label:'compiled-resource',resource,pin,request_start:now()};assets.set(pin,row);return}if(!row||row[step+'_at']!==undefined)return;row[step+'_at']=now();if(step==='headers')row.http_status=value;if(step==='text')row.text_utf16=value;if(step==='verified'){row.elapsed=row.verified_at-row.request_start;send({...row});assets.delete(pin)}}catch(_){}}
  const result=Object.freeze({now,point,span,asset});point('prepare-start');return result;
 }catch(_){return null}
}

const compiledProfiles=makeCompiledProfileSupport(compiledAssets,resource,knownPinMatches,canonicalJSON,()=>!!current);
async function prepareView(packet,index,requestedAt){const token=++sequence,prepared=packet.prepared?.sides?.[index];if(!prepared)throw Error('Missing proven prepared side');const valid=()=>packet===current&&token===sequence;const phase=qaCompiledPhase(packet,index,token,valid);
 const row={card:packet.id,side:index?'back-preparing':'front-preparing',token:accepted+'-'+token,request:requestedAt,reason:'connected-preparation',events:[]};if(packet.metricsAsset){records.push(row);if(records.length>20)records.shift();report();}
 const verified=await Promise.all([knownPinMatches(packet.sides[index],prepared.proof.source_sha256),knownPinMatches(prepared.html,prepared.proof.expanded_sha256)]);if(!verified.every(Boolean))throw Error('Prepared body differs from its source proof');if(!valid())return null;phase?.point('source-proofs-verified');
 const compiled=await compiledProfiles.load(packet,index,prepared,valid,phase);if(!valid())return null;phase?.point('compiled-load-complete');const authoredHTML=compiled?compiled.html:prepared.html;
 const parsed=new DOMParser().parseFromString(authoredHTML,'text/html');if(parsed.querySelector('[autoplay]'))throw Error('Autoplay retains its original wrapper');if(/<noscript\b/i.test(authoredHTML))throw Error('Prepared parsing retains original noscript semantics');parsed.querySelector('base').href=packet.base;phase?.point('derived-dom-parsed');
 const scripts=await collectAuthoredScripts(parsed,packet);phase?.point('authored-resources-ready');
 // Source styles and module bytes are prepared before the next authored body;
 // there is no new visible half-card waiting for external script downloads.
 for(const link of parsed.querySelectorAll('link[rel~="stylesheet"][href]')){if(Array.from(link.attributes).some(a=>!['rel','href'].includes(a.name))||link.rel.trim().toLowerCase().split(/\s+/).join(' ')!=='stylesheet')throw Error('Prepared stylesheet attributes retain their original protocol');const url=new URL(link.getAttribute('href'),packet.base).href,response=await fetch(url,{signal:frameAbort.signal});if(!response.ok)throw Error('Prepared stylesheet HTTP '+response.status);const raw=await response.text();if(/@import\b|<\/style/i.test(raw))throw Error('Prepared stylesheet needs its original lifecycle');const style=parsed.createElement('style');style.textContent=raw;link.replaceWith(style)}phase?.point('styles-ready');
 if(!valid())return null;const fingerprint=JSON.stringify(Object.entries(packet.prepared.modules||{}).sort(([a],[b])=>a.localeCompare(b))),active=await realm(packet.base,fingerprint,valid);if(!valid()||!active)return null;const {win,doc}=active;active.row=row;active.packet=packet;active.viewToken=token;phase?.point('realm-ready');
 for(const item of scripts){const module=packet.prepared.modules?.[item.pin];if(module&&!active.modules.has(item.pin)){const code=await resource(new URL(module.src,document.baseURI).href,module.sha256);if(!valid())return null;const slimLoadSource=adaptCompiledHistorySlotsOwner(adaptNativeFineWholeProbe(adaptSharedReadingBankWarm(adaptNativeGroupCoarseBuckets(adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask(adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin);withSlimLoadChecker(win,enabled=>execute(doc,enabled?adaptNativeBankSideChecker(adaptNativeSlimLoadChecker(slimLoadSource,item.pin),item.pin):slimLoadSource,item.pin+'-prepared-'+module.sha256));active.modules.add(item.pin)}}phase?.point('native-module-ready');
 if(!compiled)win.AnkiSlimDecode?.(parsed);let initialNumbering=null;const history=compiled?null:staticHistoryCohort(parsed,packet,scripts)?stageStaticHistory(parsed):null;try{for(const [pin,raw]of Object.entries(prepared.registry)){if(!await knownPinMatches(raw,pin))throw Error('Prepared native registration SHA differs');win.AnkiSlimAssets=win.AnkiSlimAssets||{};win.AnkiSlimAssets[pin]=raw}if(!valid())return null;phase?.point('registry-ready');
 if(!compiled)for(const payload of parsed.querySelectorAll('script.anki-final-reviewed-data')){if(!win.StudySlimWarm)throw Error('Prepared native module is unavailable');for(const pair of [['asSrc','asSha'],['asIndexSrc','asIndexSha']])if(payload.dataset[pair[0]])await win.StudySlimWarm.load({src:payload.dataset[pair[0]],sha256:payload.dataset[pair[1]]});const raw=payload.dataset.asSha?prepared.registry[payload.dataset.asSha]:payload.textContent;const projectionOwner=projectionTaskBegin(win,packet,index,token,active);try{await win.AnkiReviewedChunkProjection.prepare(JSON.parse(raw))}finally{projectionOwner?.close()}await win.AnkiSharedReadingBankRuntime.warm(win.AnkiFinalReadingMetadata,Array.from(parsed.querySelectorAll('.sf-en,.example-text'),node=>node.textContent))}if(!valid())return null;
 const frames=Array.from(parsed.querySelectorAll('iframe.etymology-source-frame'));if(frames.length!==prepared.children.length)throw Error('Prepared child source count differs');frames.forEach((frame,n)=>{const child=prepared.children[n],section=frame.closest('.etymology-section'),meaning=section?.closest('.meaning-section'),levels=meaning&&Array.from(meaning.children).find(node=>node.classList.contains('level-section'));if(levels)levels.after(section);if(section)section.style.margin='.2rem 0 .65rem';let childHTML=child.html;if(packet.metricsAsset){let ordinal=0;childHTML=childHTML.replace(/(<script\b[^>]*>)([\s\S]*?)(<\/script\s*>)/gi,(all,open,code,close)=>open+code+'\n//# sourceURL=study-child-'+child.scripts[ordinal++]+'.js\n'+close)}const base='<base href="'+encode(packet.base)+'">';if(/<base\b/i.test(childHTML))childHTML=childHTML.replace(/<base\b[^>]*>/i,base);else childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+base);const childToken=String(accepted)+'-'+String(token)+'-'+n,head='<scr'+'ipt>('+childReadiness.toString()+')('+JSON.stringify({token:childToken,sourceSha:child.source_sha256,debug:!!packet.metricsAsset})+');</scr'+'ipt>';childHTML=childHTML.replace(/<head(?:\s[^>]*)?>/i,value=>value+head);frame.dataset.studyChildToken=childToken;frame.dataset.studyChildSource=child.source_sha256;frame.setAttribute('srcdoc',childHTML);frame.removeAttribute('data-web-etymology-srcdoc')});
 if(!valid())return null;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();win.__ankiCardChunkState=null;compiledProfiles.clear(doc);qaLayoutCostClear(doc);if(compiled){if(!win.AnkiCompiledCardRuntime)compiledProfiles.withFrozenCapture(win,enabled=>execute(doc,enabled?adaptCompiledFrozenProfile(compiled.runtimeCode,compiled.runtimeSha256):compiled.runtimeCode,'compiled-card-'+compiled.runtimeSha256));if(win.AnkiCompiledCardRuntime?.schema!==compiled.profile.schema||win.AnkiCompiledCardRuntime?.version!==compiled.profile.version)throw Error('Compiled runtime version differs')}
 phase?.point('body-adoption-start');if(phase)qaLayoutCostBegin(active,packet,token);const head=doc.createDocumentFragment(),body=doc.createDocumentFragment();for(const node of Array.from(parsed.head.childNodes))head.append(doc.adoptNode(node));for(const node of Array.from(parsed.body.childNodes))body.append(doc.adoptNode(node));for(const audio of body.querySelectorAll('audio,video')){const play=audio.play,details=()=>({src:audio.src,currentSrc:audio.currentSrc,srcAttribute:audio.getAttribute('src'),ready:audio.readyState,network:audio.networkState,connected:audio.isConnected,ownerCurrent:audio.ownerDocument===doc,ownRealmPrototype:audio instanceof win.HTMLMediaElement,mediaError:audio.error?.message});if(packet.metricsAsset){row.audio=row.audio||{attempts:0,denied:0,errors:[],events:[]};for(const event of ['loadstart','loadedmetadata','canplay','error','abort','emptied','stalled','suspend'])audio.addEventListener(event,()=>{row.audio.events.push({event,at:clock(),...details()});if(row.audio.events.length>24)row.audio.events.shift();report()})}Object.defineProperty(audio,'play',{configurable:true,writable:true,value:function(...args){if(packet.metricsAsset){row.audio.attempts++;row.audio.userActivation=win.navigator.userActivation?.isActive;row.audio.call={...details(),play:String(play).slice(0,180),targetRealmPlay:String(win.HTMLMediaElement.prototype.play).slice(0,180)};report()}if(active.node!==side){row.audioAttempts=(row.audioAttempts||0)+1;if(row.audio)row.audio.denied++;return Promise.reject(Error('Prepared media cannot play before commit'))}try{const result=Reflect.apply(play,this,args);if(!packet.metricsAsset)return result;return Promise.resolve(result).catch(error=>{row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});if(row.audio.errors.length>4)row.audio.errors.shift();report();throw error})}catch(error){if(row.audio){row.audio.errors.push({name:error.name,message:error.message,stack:error.stack,...details()});report()}throw error}}})}copyAttributes(parsed.documentElement,doc.documentElement);copyAttributes(parsed.body,doc.body);doc.head.replaceChildren(head);doc.body.replaceChildren(body);compiledProfiles.bind(win,doc,compiled,()=>packet===current&&active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.isConnected&&active.node.contentDocument===doc);win.scrollTo(0,0);history?.bind(doc,()=>active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.contentDocument===doc);phase?.point('body-connected');initialNumbering=compiled?makeCompiledInitialNumbering(doc,compiledInitialNumberingCertificate(packet),compiled.profile.bindings,scripts,()=>packet===current&&active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.isConnected&&active.node.contentDocument===doc):null;
 // Authored scripts still run in source order. Their repeated calls to our
 // bridge are coalesced so they cannot force intermediate whole-card layouts.
 const authoredComplete=win.__ankiCigenFrames.batch(()=>{for(const item of scripts){if(!valid())return false;if(packet.prepared.modules?.[item.pin]){item.node.remove();continue}const qaAuthorStarted=phase?.now();try{if(execute(doc,item.code,item.pin,initialNumbering)===false){if(!valid())return false;throw Error('Compiled initial numbering owner changed before authored execution')}}finally{phase?.span('author-execute',qaAuthorStarted,item.pin)}initialNumbering?.after(item.pin);item.node.remove()}return true},phase);if(!authoredComplete||!valid())return null;phase?.point('authors-complete');
 // Media adopted from the inert parser may retain a rejected temporary-URL
'''),
    (r''' // load() preserves authored preload/src and never starts playback.
 for(const media of doc.querySelectorAll('audio,video'))if(media.getAttribute('src')||media.querySelector('source[src]'))media.load();
 if(packet.metricsAsset&&packet.audioDiagnostics)installAudioDiagnostic(win,doc,row);if(!valid())return null;
 if(packet.metricsAsset){row.preparedBodyAt=clock();row.events.push({event:'connected-prepared-body',at:clock(),...snapshot(doc)});}const candidate={entry:active,doc,packet,index,row,token};if(!applyConsumerDocument(candidate)||!valid())return null;const historyBegan=performance.now();if(history?.count){if(!await awaitStaticHistoryNative(active,valid,historyBegan))return null;history.restore()}if(!await waitPrepared(active,valid,history?.count?historyBegan:null))return null;if(packet.metricsAsset){row.readyAt=clock();row.prepared=snapshot(doc);report();}return{...candidate,geometry:JSON.stringify(snapshot(doc,false))};}finally{history?.cleanup()}
}
function installAudioDiagnostic(win,doc,row){const box=doc.createElement('div');box.style.cssText='position:fixed;bottom:4px;right:4px;z-index:999999;background:white;border:1px solid #aaa;padding:5px';for(const [label,reset]of [['诊断：原生播放韦氏',false],['诊断：load 后播放韦氏',true]]){const button=doc.createElement('button');button.textContent=label;button.onclick=()=>{const audio=doc.querySelector('audio[data-dictionary-source="webster"]')||doc.querySelector('audio');if(!audio)return;const log=extra=>{row.audio.diagnostic={reset,src:audio.src,currentSrc:audio.currentSrc,ready:audio.readyState,network:audio.networkState,...extra};report()};try{if(reset)audio.load();const job=reset?audio.play():Reflect.apply(win.HTMLMediaElement.prototype.play,audio,[]);Promise.resolve(job).then(()=>log({result:'resolved',duration:audio.duration})).catch(error=>log({result:'rejected',name:error.name,message:error.message}))}catch(error){log({result:'threw',name:error.name,message:error.message})}};box.append(button)}doc.body.append(box)}
function clearOld(entry){if(!entry?.doc)return;const {win,doc}=entry;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();doc.body.replaceChildren();win.__ankiCigenFrames.refresh();win.__ankiCardChunkState=null;entry.packet=null;entry.viewToken=null}
function ownsView(view){return !!view&&view.packet===current&&view.entry.packet===view.packet&&view.entry.viewToken===view.token&&view.entry.doc===view.doc&&view.entry.node.isConnected&&view.entry.node.contentDocument===view.doc}
''', r''' // load() preserves authored preload/src and never starts playback.
 for(const media of doc.querySelectorAll('audio,video'))if(media.getAttribute('src')||media.querySelector('source[src]'))media.load();phase?.point('media-reset-complete');
 if(packet.metricsAsset&&packet.audioDiagnostics)installAudioDiagnostic(win,doc,row);if(!valid())return null;
 if(packet.metricsAsset){row.preparedBodyAt=clock();row.events.push({event:'connected-prepared-body',at:clock(),...snapshot(doc)});}const candidate={entry:active,doc,packet,index,row,token};if(!applyConsumerDocument(candidate)||!valid())return null;const historyBegan=performance.now();phase?.point('full-gate-start');if(history?.count){if(!await awaitStaticHistoryNative(active,valid,historyBegan))return null;history.restore()}if(!await waitPrepared(active,valid,history?.count?historyBegan:null))return null;if(phase)qaLayoutCostSeal(active,packet,token);phase?.point('full-gate-complete');if(packet.metricsAsset){row.readyAt=clock();row.prepared=snapshot(doc);report();}return{...candidate,geometry:JSON.stringify(snapshot(doc,false))};}finally{try{if(compiled&&packet===current&&active.packet===packet&&active.viewToken===token&&active.doc===doc&&active.node.isConnected&&active.node.contentDocument===doc)compiledNumberingStatuses.set(doc,{id:packet.id,token:packet.token,viewToken:token,status:initialNumbering?.status()||Object.freeze({schema:'study-compiled-initial-numbering-status.v1',qualified:false,readerCaptured:false,attempted:false,accepted:false,rows:0,reason:'unqualified-input'})});initialNumbering?.dispose()}finally{history?.cleanup()}}
}
function installAudioDiagnostic(win,doc,row){const box=doc.createElement('div');box.style.cssText='position:fixed;bottom:4px;right:4px;z-index:999999;background:white;border:1px solid #aaa;padding:5px';for(const [label,reset]of [['诊断：原生播放韦氏',false],['诊断：load 后播放韦氏',true]]){const button=doc.createElement('button');button.textContent=label;button.onclick=()=>{const audio=doc.querySelector('audio[data-dictionary-source="webster"]')||doc.querySelector('audio');if(!audio)return;const log=extra=>{row.audio.diagnostic={reset,src:audio.src,currentSrc:audio.currentSrc,ready:audio.readyState,network:audio.networkState,...extra};report()};try{if(reset)audio.load();const job=reset?audio.play():Reflect.apply(win.HTMLMediaElement.prototype.play,audio,[]);Promise.resolve(job).then(()=>log({result:'resolved',duration:audio.duration})).catch(error=>log({result:'rejected',name:error.name,message:error.message}))}catch(error){log({result:'threw',name:error.name,message:error.message})}};box.append(button)}doc.body.append(box)}
function clearOld(entry){if(!entry?.doc)return;const {win,doc}=entry;for(const name of ['AnkiSlimApkgDispose','__ankiExamCountdownCleanup'])if(typeof win[name]==='function')win[name]();for(const audio of doc.querySelectorAll('audio'))audio.pause();compiledProfiles.clear(doc);qaLayoutCostClear(doc);doc.body.replaceChildren();win.__ankiCigenFrames.refresh();win.__ankiCardChunkState=null;entry.packet=null;entry.viewToken=null}
function ownsView(view){return !!view&&view.packet===current&&view.entry.packet===view.packet&&view.entry.viewToken===view.token&&view.entry.doc===view.doc&&view.entry.node.isConnected&&view.entry.node.contentDocument===view.doc}
'''),
)
if digest(PREPARED_FRAME_RUNTIME) != '3fb080901abf1bd1b2bcd57d42347bdf4f331a18e70de1e1684c602f12c18d66':
    raise ValueError('compiled FRAME learning-consumer base differs')
for _before, _after in _COMPILED_FRAME_PATCHES:
    if PREPARED_FRAME_RUNTIME.count(_before) != 1:
        raise ValueError('compiled FRAME merge boundary differs')
    PREPARED_FRAME_RUNTIME = PREPARED_FRAME_RUNTIME.replace(_before, _after, 1)


# Explicit web transport admission. The semantic producer and native host keep
# the accepted 8a FRAME/profile source contract; no historical seal is changed.
COMPILED_DELIVERY_BASE_SHA256 = '8a938d35b1d76eee0681dd652cfbbf3998afae8fd4fab88abad0c42babea075d'
from .study_compiled_runtime import ADMITTED_RUNTIME_SHA256, CURRENT_RUNTIME_SHA256, LEGACY_RUNTIME_SHA256
COMPILED_DELIVERY_ENTRY_RUNTIME = r'''
function compiledDeliveryEntry(assets,packet){
 const inline=Object.prototype.hasOwnProperty.call(assets.entries,packet.id)?assets.entries[packet.id]:null;
 const delivery=packet.prepared?.compiled_delivery;if(!delivery)return inline;
 const fail=()=>{throw Error('Compiled delivery binding differs')},hash=/^[a-f0-9]{64}$/;
 if(assets.delivery!=='envelope.v1'||inline||delivery.schema!=='study-compiled-packet.v1'||delivery.card_id!==packet.id||!hash.test(delivery.source_artifact_sha256||''))fail();
 const entry=delivery.entry,b=entry?.anchors?.bindings,baseKeys=['producerInputSha256','sourceArtifactSha256','derivedHTMLSha256','sourceWrapperSha256','sourcePayloadSha256','sourceSideSha256','expandedSideSha256','materializerSha256','frameRuntimeSha256','frameHTMLSha256','adapterSha256','nativeModuleSha256','originalModuleSha256','rawSideSha256','rawIndexSha256','residualListenerSha256','readerDelegateSha256'],historyKeys=['historyScopeEvidenceSha256','historyProducerSourceSha256'];
 const keys=b&&historyKeys.every(key=>Object.prototype.hasOwnProperty.call(b,key))?baseKeys.concat(historyKeys):baseKeys;
 if(!entry||!b||Object.keys(b).length!==keys.length||keys.some(key=>!hash.test(b[key]||''))||b.sourceArtifactSha256!==delivery.source_artifact_sha256||b.frameRuntimeSha256!=='8a938d35b1d76eee0681dd652cfbbf3998afae8fd4fab88abad0c42babea075d'||b.frameHTMLSha256!=='b1510d852c94f7bdd98fd90fa3853ed006e1b90345f194819e4900e0a0e99b8a'||b.sourceWrapperSha256!==packet.prepared.source_wrapper_sha256||b.sourcePayloadSha256!==packet.prepared.source_payload_sha256||b.derivedHTMLSha256!==entry.html?.sha256||entry.anchors.htmlSha256!==entry.html?.sha256||entry.anchors.profileSha256!==entry.profile?.sha256)fail();
 if(canonicalJSON(delivery.runtime)!==canonicalJSON(assets.runtime)||!__COMPILED_RUNTIME_PINS__.includes(assets.runtime?.sha256))fail();
 for(const value of [entry.html,entry.profile,assets.runtime])if(!value||Object.keys(value).length!==2||!hash.test(value.sha256||'')||!new RegExp('^evidence/_study_compiled_'+value.sha256+'\\.(?:html|json|js)$').test(value.src||''))fail();
 function immutable(value){if(value&&typeof value==='object'&&!Object.isFrozen(value)){Object.values(value).forEach(immutable);Object.freeze(value)}return value}
 return immutable(entry);
}
'''.replace('__COMPILED_RUNTIME_PINS__', json.dumps(sorted(ADMITTED_RUNTIME_SHA256)))
_COMPILED_DELIVERY_FRAME_PATCHES = (
    ("const compiledAssets=JSON.parse(document.getElementById('study-compiled-assets')?.textContent||'{\"entries\":{}}');",
     "const compiledAssets=JSON.parse(document.getElementById('study-compiled-assets')?.textContent||'{\"entries\":{}}');" + COMPILED_DELIVERY_ENTRY_RUNTIME),
    ("!/^_qa_compiled_[a-z0-9_]+\\.(?:js|json|html)$/.test(value.src)",
     "!/^(?:_qa_compiled_[a-z0-9_]+|evidence\\/_study_compiled_[a-f0-9]{64})\\.(?:js|json|html)$/.test(value.src)"),
    ("const entry=Object.prototype.hasOwnProperty.call(assets.entries,packet.id)?assets.entries[packet.id]:null;if(!entry)return null;",
     "const entry=compiledDeliveryEntry(assets,packet);if(!entry)return null;"),
    ("if(!valid())return null;\n  const [html,raw,runtimeCode]=values;",
     "if(!valid())return null;if(compiledDeliveryEntry(assets,packet)!==entry)fail('delivery owner changed');\n  const [html,raw,runtimeCode]=values;"),
    ("if(!valid())return null;phase?.point('compiled-recheck-verified');",
     "if(!valid())return null;if(compiledDeliveryEntry(assets,packet)!==entry)fail('delivery owner changed');phase?.point('compiled-recheck-verified');"),
    ("function compiledInitialNumberingCertificate(packet){return compiledAssets.entries[packet.id]?.initial_numbering_certificate??null}",
     "function compiledInitialNumberingCertificate(packet){return compiledDeliveryEntry(compiledAssets,packet)?.initial_numbering_certificate??null}"),
    ("qaCompiledPhaseTaken||index!==1||!Object.prototype.hasOwnProperty.call(compiledAssets.entries,packet.id)||!isCurrent()",
     "qaCompiledPhaseTaken||index!==1||!compiledDeliveryEntry(compiledAssets,packet)||!isCurrent()"),
    ("const entry=compiledAssets.entries[packet.id],pins=new Map(",
     "const entry=compiledDeliveryEntry(compiledAssets,packet),pins=new Map("),
    ("if(pin!=='" + LEGACY_RUNTIME_SHA256 + "')return code;",
     "if(!" + json.dumps(sorted(ADMITTED_RUNTIME_SHA256)) + ".includes(pin))return code;"),
)
if digest(PREPARED_FRAME_RUNTIME) != COMPILED_DELIVERY_BASE_SHA256:
    raise ValueError('compiled web delivery source FRAME differs')
COMPILED_DELIVERY_FRAME_RUNTIME = PREPARED_FRAME_RUNTIME
for _before, _after in _COMPILED_DELIVERY_FRAME_PATCHES:
    if COMPILED_DELIVERY_FRAME_RUNTIME.count(_before) != 1:
        raise ValueError('compiled web delivery patch boundary differs')
    COMPILED_DELIVERY_FRAME_RUNTIME = COMPILED_DELIVERY_FRAME_RUNTIME.replace(_before, _after, 1)


def prepared_frame_html(compiled_assets: dict | None = None) -> str:
    from .study_catalog_web import shared_frame_html, DEFER_SCRIPTS_RUNTIME, SHARED_FRAME_RUNTIME, LAN_SHA256_RUNTIME
    original = shared_frame_html()
    runtime = DEFER_SCRIPTS_RUNTIME + '\n' + SHARED_FRAME_RUNTIME
    if '</script' in PREPARED_FRAME_RUNTIME.lower():
        raise ValueError('prepared runtime crosses the HTML script boundary')
    assets = {'entries': {}} if compiled_assets is None else compiled_assets
    if (not isinstance(assets, dict) or set(assets) - {'entries', 'runtime', 'delivery'}
            or not isinstance(assets.get('entries'), dict)
            or any(not isinstance(key, str) or not key or not isinstance(value, dict)
                   for key, value in assets['entries'].items())
            or (assets['entries'] and not isinstance(assets.get('runtime'), dict))
            or ('delivery' in assets and (assets['delivery'] != 'envelope.v1' or assets['entries']
                                         or not isinstance(assets.get('runtime'), dict)))):
        raise ValueError('compiled FRAME assets must be an explicit entry mapping')
    data = json.dumps(assets, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', r'\u003c')
    configuration = '<script id="study-compiled-assets" type="application/json">' + data + '</script>'
    frame_runtime = COMPILED_DELIVERY_FRAME_RUNTIME if assets.get('delivery') else PREPARED_FRAME_RUNTIME
    page = original.replace(runtime, LAN_SHA256_RUNTIME + '\n' + frame_runtime)
    if page.count('<script>') != 1:
        raise ValueError('compiled FRAME configuration boundary differs')
    return page.replace('<script>', configuration + '<script>', 1)


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


def write_wrapper_gzip(root: Path, raw: bytes) -> str:
    """Write a lossless source sidecar addressed by its decoded wrapper SHA.

    Existing outputs are opened without following links and verified against
    the original bytes. Atomic publication never exposes a partial gzip file.
    """
    import gzip
    import os
    import stat
    import uuid
    import zlib

    if not isinstance(raw, bytes):
        raise TypeError('wrapper gzip source must be bytes')
    artifacts = Path(root) / 'evidence'
    try:
        artifacts.mkdir(exist_ok=True)
        directory = os.open(artifacts, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise ValueError('wrapper gzip output must be a real directory') from error
    name = '_study_prepared_wrapper_' + digest(raw) + '.html.gz'

    def existing():
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ValueError('wrapper gzip output must be a regular file without symlinks') from error
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('wrapper gzip output must be a regular file')
            if stream.read(2) != b'\x1f\x8b':
                raise ValueError('wrapper gzip output has an invalid format')
            stream.seek(0)
            try:
                with gzip.GzipFile(fileobj=stream, mode='rb') as decoded:
                    restored = decoded.read(len(raw) + 1)
            except (OSError, EOFError, zlib.error) as error:
                raise ValueError('wrapper gzip output has an invalid format') from error
            if restored != raw:
                raise ValueError('wrapper gzip output differs from the original source')
        return True

    try:
        if existing():
            return 'evidence/' + name
        packed = gzip.compress(raw, compresslevel=6, mtime=0)
        temporary = '.wrapper-' + uuid.uuid4().hex + '.tmp'
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(packed)
            try:
                os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            except FileExistsError:
                if not existing():
                    raise ValueError('wrapper gzip output changed during publication')
        finally:
            os.unlink(temporary, dir_fd=directory)
        return 'evidence/' + name
    finally:
        os.close(directory)


def front_artifact_bytes(card: dict, source_front: str, value: dict, full_pin: str) -> bytes:
    """Project one authenticated front without serializing the large back.

    The caller authenticates the existing full artifact bytes and wrapper;
    both fresh exports and bounded backfills use this exact wire format.
    """
    def valid_pin(pin):
        return isinstance(pin, str) and re.fullmatch(r'[a-f0-9]{64}', pin) is not None

    if not isinstance(card, dict) or not isinstance(value, dict):
        raise ValueError('front delivery input has an invalid shape')
    if not valid_pin(full_pin) or any(not valid_pin(value.get(name)) for name in (
        'source_wrapper_sha256', 'source_payload_sha256'
    )):
        raise ValueError('front delivery source binding is invalid')
    if (not isinstance(card.get('id'), str) or not card['id']
            or not isinstance(card.get('url'), str) or not card['url']
            or not isinstance(source_front, str) or value.get('schema') != 'study-prepared-card.v1'
            or not isinstance(value.get('sides'), list) or len(value['sides']) != 2
            or not isinstance(value.get('modules'), dict)):
        raise ValueError('front delivery input has an invalid shape')
    link = urlsplit(card['url'])
    relative = Path(unquote(link.path))
    if link.scheme or link.netloc or link.query or link.fragment or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('front delivery wrapper URL leaves the authored cards directory')
    side = value['sides'][0]
    proof = side.get('proof') if isinstance(side, dict) else None
    if (not isinstance(proof, dict) or proof.get('source_sha256') != digest(source_front)
            or not isinstance(side.get('html'), str)
            or proof.get('expanded_sha256') != digest(side['html'])):
        raise ValueError('front delivery proof differs from the original front')
    front = {'schema': 'study-prepared-front.v1', 'card_id': card['id'],
             'wrapper_url': card['url'], 'base_href': '../media/',
             'source_wrapper_sha256': value['source_wrapper_sha256'],
             'source_payload_sha256': value['source_payload_sha256'],
             'source_front_sha256': proof['source_sha256'], 'source_front': source_front,
             'side': side, 'modules': value['modules'], 'full_prepared_sha256': full_pin}
    return json.dumps(front, ensure_ascii=False, separators=(',', ':')).encode()


_COMPILED_BINDINGS = (
    'producerInputSha256', 'sourceArtifactSha256', 'derivedHTMLSha256', 'sourceWrapperSha256',
    'sourcePayloadSha256', 'sourceSideSha256', 'expandedSideSha256', 'materializerSha256',
    'frameRuntimeSha256', 'frameHTMLSha256', 'adapterSha256', 'nativeModuleSha256',
    'originalModuleSha256', 'rawSideSha256', 'rawIndexSha256', 'residualListenerSha256', 'readerDelegateSha256',
)
_COMPILED_HISTORY_BINDINGS = ('historyScopeEvidenceSha256', 'historyProducerSourceSha256')


def _compiled_json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def _compiled_output(root, descriptor):
    """Read only an explicit content-addressed file inside this export."""
    from .study_compiled_build import _read
    if (not isinstance(descriptor, dict) or not isinstance(descriptor.get('src'), str)
            or re.fullmatch(r'evidence/[A-Za-z0-9_]+\.(?:json|json\.gz|js|html)', descriptor['src']) is None
            or (root / 'evidence').is_symlink() or (root / descriptor['src']).is_symlink()):
        raise ValueError('compiled delivery requires a local addressed artifact')
    return _read(root / descriptor['src'], descriptor.get('sha256'))


class _CompiledWebOutput:
    """One held evidence directory for every new attachment publication."""
    def __init__(self, path):
        import os
        self.path = Path(path)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.owned = os.fstat(self.fd)
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        import stat
        current = self.path.lstat()
        if (not stat.S_ISDIR(current.st_mode) or
                (current.st_dev, current.st_ino) != (self.owned.st_dev, self.owned.st_ino)):
            raise ValueError('compiled evidence directory ownership changed')

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        import os
        os.close(self.fd)

    def _existing(self, name, raw):
        import os
        import stat
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=self.fd)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise ValueError('compiled delivery address is not a regular owned output') from error
        with os.fdopen(descriptor, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size != len(raw) or stream.read(len(raw) + 1) != raw:
                raise ValueError('compiled delivery address bytes differ')
            after = os.fstat(stream.fileno())
        current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        fields = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if fields(before) != fields(after) or fields(current) != fields(after):
            raise ValueError('compiled delivery address changed during verification')
        return True

    def publish(self, prefix, suffix, raw):
        import os
        import uuid
        if (not isinstance(raw, bytes) or re.fullmatch('[A-Za-z0-9_]+', prefix) is None
                or suffix not in {'.html', '.js', '.json', '.json.gz'}):
            raise ValueError('invalid compiled publication')
        self.check()
        name = prefix + digest(raw) + suffix
        if self._existing(name, raw):
            self.check()
            return name
        temporary = '.compiled-' + uuid.uuid4().hex + '.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        owned, linked = os.fstat(fd), False

        def ours(child):
            try:
                value = os.stat(child, dir_fd=self.fd, follow_symlinks=False)
                return (value.st_dev, value.st_ino) == (owned.st_dev, owned.st_ino)
            except FileNotFoundError:
                return False
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            self.check()
            if not ours(temporary) or not self._existing(temporary, raw):
                raise ValueError('compiled temporary output ownership changed')
            try:
                os.link(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
                linked = True
            except FileExistsError:
                if not self._existing(name, raw):
                    raise ValueError('compiled publication disappeared during verification')
            if linked and not ours(name):
                raise ValueError('compiled published output ownership changed')
            if not self._existing(name, raw):
                raise ValueError('compiled publication disappeared during verification')
            self.check()
        except BaseException:
            if linked and ours(name):
                os.unlink(name, dir_fd=self.fd)
            raise
        finally:
            if ours(temporary):
                os.unlink(temporary, dir_fd=self.fd)
        return name


def _compiled_blob(output, raw, suffix):
    name = output.publish('_study_compiled_', suffix, raw)
    return {'src': 'evidence/' + name, 'sha256': digest(raw)}


def _compiled_web_entry(root, prepared, source_descriptor, result, output):
    """Validate one existing common build and move only its three carriers.

    Profile/body bytes and all seventeen source bindings remain unchanged. The
    old prepared JSON is an independent pinned input, never edited to add its
    own compiled profile (which would create a source-artifact hash cycle).
    """
    from .study_compiled_build import _read
    if not isinstance(result, dict) or result.get('mode') != 'compiled':
        raise ValueError('an explicit completed compiled build is required')
    entry = json.loads(_compiled_json(result.get('entry')))
    bindings = entry.get('anchors', {}).get('bindings', {}) if isinstance(entry, dict) else {}
    if (set(bindings) not in (set(_COMPILED_BINDINGS),
                             set(_COMPILED_BINDINGS + _COMPILED_HISTORY_BINDINGS))
            or any(not isinstance(pin, str) or re.fullmatch('[a-f0-9]{64}', pin) is None
                   for pin in bindings.values())):
        raise ValueError('compiled delivery requires the exact seventeen or nineteen source bindings')
    source, module, anchors = entry.get('source'), entry.get('module'), entry.get('anchors')
    if (prepared.get('schema') != 'study-prepared-card.v1' or len(prepared.get('sides', [])) != 2
            or not isinstance(source, dict) or not isinstance(module, dict)
            or anchors.get('schema') != 'study-compiled-card-interactions.v1' or anchors.get('version') != 1
            or entry.get('decoded') is not True):
        raise ValueError('compiled delivery/source schema differs')
    proof = prepared['sides'][1]['proof']
    expected = {'sourceArtifactSha256': source_descriptor['sha256'],
                'sourceWrapperSha256': prepared['source_wrapper_sha256'],
                'sourcePayloadSha256': prepared['source_payload_sha256'],
                'sourceSideSha256': proof['source_sha256'], 'expandedSideSha256': proof['expanded_sha256'],
                'frameRuntimeSha256': COMPILED_DELIVERY_BASE_SHA256,
                'frameHTMLSha256': 'b1510d852c94f7bdd98fd90fa3853ed006e1b90345f194819e4900e0a0e99b8a'}
    expected_source = {'wrapper_sha256': expected['sourceWrapperSha256'],
                       'payload_sha256': expected['sourcePayloadSha256'],
                       'side_sha256': expected['sourceSideSha256'],
                       'expanded_sha256': expected['expandedSideSha256'],
                       'registry_pins': proof['registry_pins']}
    actual_module = prepared.get('modules', {}).get(module.get('original_sha256'), {})
    if (source != expected_source or any(bindings.get(key) != pin for key, pin in expected.items())
            or module.get('original_sha256') not in AUDITED_NATIVE_MODULES
            or any(actual_module.get(key) != module.get(key) for key in ('original_sha256', 'sha256'))
            or bindings['originalModuleSha256'] != module['original_sha256']
            or bindings['nativeModuleSha256'] != module['sha256']):
        raise ValueError('compiled delivery does not bind its unchanged prepared source')
    resources = result.get('resources')
    if not isinstance(resources, dict):
        raise ValueError('compiled delivery requires explicit pinned build resources')

    def read_asset(asset, suffix):
        if (not isinstance(asset, dict) or set(asset) != {'src', 'sha256'}
                or not isinstance(asset['src'], str)
                or not isinstance(asset['sha256'], str)
                or re.fullmatch(r'_qa_compiled_[a-f0-9]{64}' + re.escape(suffix), asset['src']) is None
                or asset['src'] != '_qa_compiled_' + asset['sha256'] + suffix):
            raise ValueError('compiled build asset must be an addressed local basename')
        matches = [value for value in resources.values() if isinstance(value, dict)
                   and value.get('sha256') == asset['sha256']
                   and isinstance(value.get('path'), str) and Path(value['path']).name == asset['src']]
        if not matches:
            raise ValueError('compiled build asset has no authenticated resource')
        return _read(matches[0]['path'], asset['sha256'], matches[0].get('bytes'))

    html_raw = read_asset(entry.get('html'), '.html')
    profile_raw = read_asset(entry.get('profile'), '.json')
    runtime = result.get('runtime')
    runtime_raw = read_asset(runtime, '.js')
    profile = json.loads(profile_raw)
    if (runtime['sha256'] not in ADMITTED_RUNTIME_SHA256
            or anchors.get('htmlSha256') != digest(html_raw)
            or anchors.get('profileSha256') != digest(profile_raw)
            or bindings['derivedHTMLSha256'] != digest(html_raw)
            or profile.get('schema') != anchors['schema'] or profile.get('version') != anchors['version']
            or profile.get('bindings') != bindings):
        raise ValueError('compiled delivery body/profile/runtime binding differs')
    entry['html'] = _compiled_blob(output, html_raw, '.html')
    entry['profile'] = _compiled_blob(output, profile_raw, '.json')
    return entry, _compiled_blob(output, runtime_raw, '.js')


def attach_compiled_library(root: Path, catalog: dict, prepared_config: dict, compiled_results: dict) -> dict:
    """Attach already-built shared results without rerunning a semantic producer.

    Returns a candidate config/report only. It never writes index.html, source
    wrappers/media/catalog, native packages or live service configuration.
    """
    with _CompiledWebOutput(Path(root) / 'evidence') as output:
        return _attach_compiled_library(Path(root), catalog, prepared_config, compiled_results, output)


def _attach_compiled_library(root, catalog, prepared_config, compiled_results, output):
    import gzip
    root = Path(root)
    if (not isinstance(compiled_results, dict) or 'preparedIndex' not in prepared_config
            or prepared_config.get('compiledDelivery')):
        raise ValueError('compiled attachment requires an unmodified prepared index')
    artifacts = root / 'evidence'
    raw_index = _compiled_output(root, prepared_config['preparedIndex'])
    index = json.loads(raw_index)
    if index.get('schema') != 'study-prepared-index.v1' or not isinstance(index.get('cards'), dict):
        raise ValueError('compiled attachment prepared index differs')
    cards = {card['id']: card for card in catalog['cards']}
    if len(cards) != len(catalog['cards']) or set(compiled_results) - cards.keys():
        raise ValueError('compiled attachment card identity differs')
    count = envelope_bytes = 0
    shared_runtime = None
    for identity, result in compiled_results.items():
        if isinstance(result, dict) and result.get('mode') == 'authored':
            continue
        card = cards[identity]
        rule = index['cards'].get(identity)
        if not isinstance(rule, dict):
            raise ValueError('compiled card has no authenticated prepared source')
        source_raw = _compiled_output(root, rule)
        prepared = json.loads(source_raw)
        entry, runtime = _compiled_web_entry(root, prepared, rule, result, output)
        if shared_runtime is not None and shared_runtime != runtime:
            raise ValueError('one compiled library must use one pinned binder')
        shared_runtime = runtime
        first = json.loads(_compiled_output(root, rule.get('front')))
        if (first.get('card_id') != identity or first.get('wrapper_url') != card['url']
                or first.get('full_prepared_sha256') != rule['sha256']):
            raise ValueError('compiled attachment original front differs')
        envelope = {'schema': 'study-compiled-delivery.v1', 'card_id': identity,
                    'wrapper_url': card['url'], 'source_wrapper_sha256': prepared['source_wrapper_sha256'],
                    'source_payload_sha256': prepared['source_payload_sha256'],
                    'prepared': {key: rule[key] for key in ('src', 'sha256', 'gzipSrc') if key in rule},
                    'entry': entry, 'runtime': runtime}
        data = _compiled_json(envelope)
        name = 'evidence/' + output.publish('_study_compiled_delivery_', '.json', data)
        packed_name = 'evidence/' + output.publish('_study_compiled_delivery_', '.json.gz',
                                                  gzip.compress(data, compresslevel=6, mtime=0))
        new_front = front_artifact_bytes(card, first['source_front'], prepared, digest(data))
        first_name = 'evidence/' + output.publish('_study_prepared_front_', '.json', new_front)
        first_gzip = 'evidence/' + output.publish('_study_prepared_front_', '.json.gz',
                                                 gzip.compress(new_front, compresslevel=6, mtime=0))
        index['cards'][identity] = {'src': name, 'sha256': digest(data), 'gzipSrc': packed_name,
                                   'front': {'src': first_name, 'sha256': digest(new_front), 'gzipSrc': first_gzip}}
        count += 1
        envelope_bytes += len(data)
    if not count:
        return {'config': dict(prepared_config), 'report': {'schema': 'study-compiled-web-attachment.v1',
                'compiled': 0, 'envelope_bytes': 0, 'source_prepared_index_sha256': digest(raw_index)}}
    new_index = _compiled_json(index)
    index_name = 'evidence/' + output.publish('_study_prepared_index_', '.json', new_index)
    index_gzip = 'evidence/' + output.publish('_study_prepared_index_', '.json.gz',
                                             gzip.compress(new_index, compresslevel=9, mtime=0))
    assets = {'entries': {}, 'runtime': shared_runtime, 'delivery': 'envelope.v1'}
    config = {**prepared_config, 'html': prepared_frame_html(assets), 'compiledDelivery': 'envelope.v1',
              'preparedIndex': {'src': index_name, 'sha256': digest(new_index), 'gzipSrc': index_gzip}}
    return {'config': config, 'report': {'schema': 'study-compiled-web-attachment.v1', 'compiled': count,
            'envelope_bytes': envelope_bytes, 'source_prepared_index_sha256': digest(raw_index),
            'profile_source_frame_sha256': COMPILED_DELIVERY_BASE_SHA256,
            'delivery_frame_sha256': digest(COMPILED_DELIVERY_FRAME_RUNTIME),
            'original_cards_media_catalog_unchanged': True}}


def prepare_library(root: Path, catalog: dict, shared_config: dict, *, callback=None,
                    compiled_results: dict | None = None) -> dict:
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
    raw_bytes = compressed_bytes = front_bytes = front_compressed_bytes = fallbacks = 0
    wrapper_gzip_cards = wrapper_gzip_bytes = 0
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
            full_pin = digest(data)
            first = front_artifact_bytes(card, sides[0], value, full_pin)
            first_name = 'evidence/' + _write_addressed(artifacts, '_study_prepared_front_', '.json', first)
            first_packed = gzip.compress(first, compresslevel=6, mtime=0)
            first_packed_name = 'evidence/' + _write_addressed(
                artifacts, '_study_prepared_front_', '.json.gz', first_packed)
            wrapper_name = write_wrapper_gzip(root, raw)
            entries[card['id']] = {'src': name, 'sha256': full_pin, 'gzipSrc': packed_name,
                                   'front': {'src': first_name, 'sha256': digest(first),
                                             'gzipSrc': first_packed_name}}
            raw_bytes += len(data)
            compressed_bytes += len(packed)
            front_bytes += len(first)
            front_compressed_bytes += len(first_packed)
            wrapper_gzip_cards += 1
            wrapper_gzip_bytes += (root / wrapper_name).stat(follow_symlinks=False).st_size
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
              'wrapperDelivery': 'source-gzip.v1',
              'preparedIndex': {'src': index_name, 'sha256': digest(index), 'gzipSrc': packed_name}}
    config.pop('prepared', None)
    config.pop('metricsAsset', None)
    result = {'config': config, 'report': {'schema': 'study-prepared-delivery.v1', 'cards': total,
            'prepared': len(entries), 'fallbacks': fallbacks, 'fallback_samples': fallback_samples,
            'source_wrapper_payload_sha256': source_proof.hexdigest(),
            'artifact_bytes': raw_bytes, 'artifact_gzip_bytes': compressed_bytes,
            'front_artifact_bytes': front_bytes, 'front_artifact_gzip_bytes': front_compressed_bytes,
            'wrapper_gzip_cards': wrapper_gzip_cards, 'wrapper_gzip_bytes': wrapper_gzip_bytes,
            'index_bytes': len(index), 'index_gzip_bytes': len(packed),
            'max_resolver_cache_bytes': media.max_cache_bytes,
            'dictionary_decodes': media.dictionary_decodes,
            'original_cards_media_catalog_unchanged': True,
            'runtime_sha256': digest(PREPARED_FRAME_RUNTIME), 'qa_observation_enabled': False}}
    if compiled_results is not None:
        attached = attach_compiled_library(root, catalog, config, compiled_results)
        result['config'] = attached['config']
        result['report']['compiled_delivery'] = attached['report']
    return result
