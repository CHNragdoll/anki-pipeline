"""Build-time inputs for the shared complete-card semantic producer.

This stage consumes an explicit, pinned prepared source. It neither changes
catalog content nor enables a delivery host. Both hosts must consume the same
result through their normal field projection before a full-build claim.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urljoin, urlsplit

from . import study_catalog_web as web
from . import study_catalog_web_materialize as materializer

_HASH = re.compile('[a-f0-9]{64}')
_LIMIT = 64 * 1024 * 1024
_HELPERS = Path(__file__).parent / 'compiled/semantic-helpers.js'
_HELPERS_SHA256 = 'd96e8acfd2338377fe2db5b415f3c96d80a20300c9b31405e03a18e63528627d'
_DELEGATES = {
    'readerDelegateSha256': (
        b'// Refresh every time Anki reuses its card webview; bind delegated events once.\n(function () {',
        13077, '9532ae0469f789f047d2e22fe096fb7ecf9d6c779ee4f14228af99c5a6181e2f'),
    'residualListenerSha256': (
        b'/* Reviewed residual spans reuse the existing bilingual click delegate. */\n(function () {',
        1517, '76365bee74cf1ff1a96fa5ff6d63c88877c6053e384bb4e84b2815d7eab38f1b'),
}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, expected, *, limit=_LIMIT):
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise ValueError('a complete source SHA-256 is required')
    path = Path(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or _sha(raw) != expected:
        raise ValueError('source bytes differ from the explicit pin: ' + path.name)
    return raw


def _local(root, name):
    link = urlsplit(name)
    relative = Path(unquote(link.path))
    if (link.scheme or link.netloc or link.query or link.fragment or
            relative.is_absolute() or '..' in relative.parts or '\\' in name):
        raise ValueError('source descriptor must be a local relative resource')
    # These are read-only capabilities. Existing exports deliberately delegate
    # cards/media directories through symlinks; expected bytes remain mandatory.
    path = root / relative
    if not path.is_file():
        raise ValueError('missing pinned source resource: ' + name)
    return path


def _descriptor(root, value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('source requires an explicit path and SHA-256')
    path = _local(root, value['path'])
    return path, _read(path, value['sha256'])


def _json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError('duplicate input JSON key')
            result[key] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)


def build_semantic_request(root, wrapper, artifact, destination, *, policy, source_url):
    """Freeze inputs for one shared semantic operation without running it.

    The wrapper is produced from the common field/template projection. Pins
    must come from that same projected delivery. A request is not a compiled
    artifact, native update, package, or permission to activate either host.
    """
    root = Path(root)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('semantic inputs must use a new output directory')
    origin = urlsplit(source_url)
    if (origin.scheme not in {'http', 'https'} or not origin.netloc or
            origin.username or origin.password or origin.query or origin.fragment):
        raise ValueError('source URL must be a plain logical source document')
    source_dir = urljoin(source_url, './')
    base_url = urljoin(source_url, 'media/')
    if not isinstance(policy, dict) or set(policy) - {'external', 'inline'}:
        raise ValueError('explicit authored-script policy is required')
    external = policy.get('external', {})
    if not isinstance(external, dict) or not isinstance(policy.get('inline', []), list):
        raise ValueError('invalid authored-script policy')
    _, wrapper_raw = _descriptor(root, wrapper)
    _, artifact_raw = _descriptor(root, artifact)
    value = _json(artifact_raw)
    if value.get('schema') != 'study-prepared-card.v1':
        raise ValueError('unsupported prepared source schema')
    if value.get('source_wrapper_sha256') != _sha(wrapper_raw):
        raise ValueError('source wrapper binding differs')
    payload = web.card_payload(wrapper_raw)
    if value.get('source_payload_sha256') != _sha(payload):
        raise ValueError('source payload binding differs')
    sides = _json(payload)
    prepared_sides = value.get('sides')
    if (not isinstance(sides, list) or len(sides) != 2 or
            not isinstance(prepared_sides, list) or len(prepared_sides) != 2):
        raise ValueError('complete two-sided source is required')
    for source, side in zip(sides, prepared_sides):
        if not isinstance(source, str) or not isinstance(side, dict):
            raise ValueError('invalid prepared source side')
        proof = side.get('proof', {})
        expanded = side.get('html')
        if (not isinstance(expanded, str) or
                proof.get('source_sha256') != _sha(source.encode()) or
                proof.get('expanded_sha256') != _sha(expanded.encode())):
            raise ValueError('source/expanded side binding differs')
        registry = side.get('registry')
        if not isinstance(registry, dict) or proof.get('registry_pins') != sorted(registry):
            raise ValueError('source registry membership differs')
        for pin, text in registry.items():
            if not isinstance(text, str) or not _HASH.fullmatch(pin) or _sha(text.encode()) != pin:
                raise ValueError('source registry text differs from pin')
    modules = value.get('modules')
    if not isinstance(modules, dict) or len(modules) != 1:
        raise ValueError('unsupported semantic module cohort')
    native_pin, module = next(iter(modules.items()))
    if native_pin not in materializer.AUDITED_NATIVE_MODULES or module.get('original_sha256') != native_pin:
        raise ValueError('semantic module is not an approved source capability')
    module_path = _local(root, module['src'])
    module_raw = _read(module_path, module['sha256'])
    resources = {}
    original_native = None
    for match in web.SharedMountAudit.pattern.finditer(sides[1]):
        attrs = web._MountScriptTag(match[1]).attributes
        src = attrs.get('src')
        if not src:
            continue
        pin = external.get(src)
        if not isinstance(pin, str) or not _HASH.fullmatch(pin):
            raise ValueError('authored source is absent from the explicit policy')
        url = urljoin(base_url, src)
        if not url.startswith(source_dir):
            raise ValueError('authored resource leaves the logical source directory')
        path = _local(root / 'media', src)
        raw = _read(path, pin)
        resources[url] = raw
        if pin == native_pin:
            original_native = raw
    if original_native is None:
        raise ValueError('prepared module lacks its actual authored source')
    if materializer.prepare_native_module(original_native.decode('utf-8')).encode() != module_raw:
        raise ValueError('prepared native module differs from its source derivative')
    source_media = materializer.ReadOnlyMedia(root / 'media')
    parsed_source = _ProfileHTML(value['sides'][1]['html'])
    for attrs in parsed_source.styles:
        name = attrs.get('href', '')
        match = re.fullmatch(r'_study_([a-f0-9]{64})\.css', name)
        if (set(attrs) != {'rel', 'href'} or attrs.get('rel', '').strip().lower() != 'stylesheet' or not match):
            raise ValueError('source stylesheet requires its exact local content address')
        raw = _read(_local(root / 'media', name), match[1])
        resources[urljoin(base_url, name)] = raw
    for attrs in parsed_source.evidence:
        raw, _ = _history_evidence(source_media, attrs)
        resources[urljoin(base_url, attrs['data-native-history-media'])] = raw
    resources[urljoin(source_url, module['src'])] = module_raw
    helpers = _read(_HELPERS, _HELPERS_SHA256)

    # All source and policy qualification precedes publication of private input
    # files. Only selected script resources are copied, never unrelated media.
    destination.mkdir()
    def store(raw, suffix):
        pin = _sha(raw)
        path = destination / (pin + suffix)
        if path.exists():
            if path.is_symlink() or path.read_bytes() != raw:
                raise ValueError('semantic input address collision')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
        return {'path': str(path.resolve()), 'sha256': pin}
    request = {'schema': 'study-compiled-semantic-request.v1',
               'artifact': store(artifact_raw, '.json'),
               'module': {**store(module_raw, '.js'), 'original_sha256': native_pin},
               'helpers': store(helpers, '.js'),
               'source': {'wrapper_sha256': _sha(wrapper_raw), 'payload_sha256': _sha(payload)},
               'resources': {url: store(raw, '.css' if urlsplit(url).path.endswith('.css') else '.js')
                             for url, raw in sorted(resources.items())},
               'base_url': base_url, 'source_url': source_url, 'policy': policy}
    request_raw = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode()
    with (destination / 'request.json').open('xb') as stream:
        stream.write(request_raw)
    return {'schema': 'study-compiled-semantic-inputs.v1',
            'request': {'path': str((destination / 'request.json').resolve()), 'sha256': _sha(request_raw)},
            'raw_wrapper_and_payload_verified': True,
            'source_files_unchanged': True, 'script_resources': len(resources),
            'product_enabled': False}


def _absolute(value):
    if (not isinstance(value, dict) or set(value) != {'path', 'sha256'} or
            not isinstance(value['path'], str) or not Path(value['path']).is_absolute()):
        raise ValueError('a pinned absolute input descriptor is required')
    return _read(value['path'], value['sha256'])


class _ProfileHTML(HTMLParser):
    """Read inert script/pre declarations without executing authored code."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.scripts, self.evidence, self.styles, self.active = [], [], [], None
        self.pre_texts, self.pre_active = [], None
        self.template_depth = 0
        self.feed(text)
        self.close()
        if self.active is not None:
            raise ValueError('unclosed inert script declaration')
        if self.pre_active is not None:
            raise ValueError('unclosed original history evidence')

    def handle_starttag(self, tag, attrs):
        if tag == 'template':
            self.template_depth += 1
        if self.template_depth:
            return
        # This source pass precedes DOMParser, which would silently discard
        # duplicate attributes. The numbering preparer consumes this qualified
        # original markup, rather than claiming it can recover discarded attrs.
        if len({key for key, _ in attrs}) != len(attrs):
            raise ValueError('duplicate source HTML attribute')
        if tag == 'link':
            if len({key for key, _ in attrs}) != len(attrs):
                raise ValueError('duplicate stylesheet attribute')
            values = dict(attrs)
            if 'stylesheet' in values.get('rel', '').lower().split():
                self.styles.append(values)
            return
        if tag not in {'script', 'pre'}:
            return
        names = [key for key, _ in attrs]
        if len(set(names)) != len(names):
            raise ValueError('duplicate inert declaration attribute')
        attrs = dict(attrs)
        if tag == 'script':
            if self.active is not None:
                raise ValueError('nested script declaration')
            self.active = [attrs, []]
        elif 'data-native-history-media' in attrs or 'data-native-history-sha' in attrs:
            self.evidence.append(attrs)
            if self.pre_active is not None:
                raise ValueError('nested original history evidence')
            self.pre_active = [attrs, []]

    def handle_data(self, text):
        if self.active is not None:
            self.active[1].append(text)
        if self.pre_active is not None:
            self.pre_active[1].append(text)

    def handle_endtag(self, tag):
        if tag == 'template' and self.template_depth:
            self.template_depth -= 1
            return
        if self.template_depth:
            return
        if tag == 'pre' and self.pre_active is not None:
            attrs, text = self.pre_active
            self.pre_texts.append((attrs, ''.join(text)))
            self.pre_active = None
        if tag == 'script' and self.active is not None:
            attrs, text = self.active
            self.scripts.append((attrs, ''.join(text)))
            self.active = None

    def scripts_with_class(self, name):
        return [(attrs, text) for attrs, text in self.scripts if name in attrs.get('class', '').split()]


def _delegate_pins(resources):
    pins = {}
    for name, (prefix, size, expected) in _DELEGATES.items():
        found = False
        for raw in resources:
            at = raw.find(prefix)
            while at >= 0:
                if _sha(raw[at:at + size]) != expected:
                    raise ValueError('unsupported authored delegate source: ' + name)
                found = True
                at = raw.find(prefix, at + len(prefix))
        if not found:
            raise ValueError('missing actual authored delegate source: ' + name)
        pins[name] = expected
    return pins


def _history_evidence(media, attrs):
    name, pin = attrs.get('data-native-history-media'), attrs.get('data-native-history-sha')
    if (not isinstance(name, str) or not re.fullmatch(r'_af_[a-f0-9]{24}\.js', name) or
            not isinstance(pin, str) or not _HASH.fullmatch(pin)):
        raise ValueError('invalid original history evidence reference')
    original_text = media.history(name, pin)
    resource = media.local(name).read_bytes()
    if len(resource) > _LIMIT:
        raise ValueError('original history evidence exceeds the byte limit')
    match = materializer._HISTORY.fullmatch(resource.decode('utf-8'))
    if (not match or match[1] != pin or _json(match[2].encode()) != original_text or
            _sha(original_text.encode()) != pin):
        raise ValueError('history evidence changed during input freeze')
    return resource, original_text


def _history_inputs(manifests, media, initial=()):
    if not manifests and not initial:
        return {}, {}
    if media is None:
        raise ValueError('closed history requires its explicit read-only media')
    if not isinstance(media, materializer.ReadOnlyMedia):
        media = materializer.ReadOnlyMedia(Path(media))
    parts, evidence = {}, {}
    for attrs, text in initial:
        resource, original_text = _history_evidence(media, attrs)
        if attrs.get('data-native-history-ready') != 'true' or text != original_text:
            raise ValueError('initial history evidence differs from its original source')
        evidence[attrs['data-native-history-media']] = resource
    for attrs, text in manifests:
        manifest = _json(text.encode())
        if (attrs.get('type') != 'application/json' or
                not isinstance(manifest, dict) or set(manifest) != {'schema', 'parts', 'total'} or
                manifest['schema'] != 'anki-slim-segments.v1' or
                not isinstance(manifest['parts'], list) or not manifest['parts']):
            raise ValueError('unsupported closed-history manifest')
        total = 0
        for part in manifest['parts']:
            if (not isinstance(part, dict) or set(part) != {'src', 'sha256', 'count'} or
                    type(part['count']) is not int or part['count'] < 0):
                raise ValueError('invalid closed-history part')
            total += part['count']
            decoded = media.read(part)
            raw = decoded.encode()
            if len(raw) > _LIMIT:
                raise ValueError('closed-history part exceeds the byte limit')
            parts[part['sha256']] = raw
            for item in _ProfileHTML(decoded).evidence:
                resource, _ = _history_evidence(media, item)
                evidence[item['data-native-history-media']] = resource
        if type(manifest['total']) is not int or total != manifest['total']:
            raise ValueError('closed-history total differs from its original parts')
    return parts, evidence


def build_profile_request(semantic_request, producer_report, destination, *, media=None):
    """Freeze the existing v1 profile request from one completed semantic result.

    All provenance is derived from the actual pinned request, result and current
    common runtime. This operation does not activate a host, change fields, or
    discard unsupported history. The emitter owns node paths and slot scope.
    """
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('profile inputs must use a new output directory')
    request_raw, report_raw = _absolute(semantic_request), _absolute(producer_report)
    request, report = _json(request_raw), _json(report_raw)
    if (request.get('schema') != 'study-compiled-semantic-request.v1' or
            report.get('schema') != 'study-compiled-semantic-result.v1' or
            report.get('real_native_ready') is not True or report.get('pure_semantic_only') is not True or
            report.get('authored_startup_executed') is not False):
        raise ValueError('profile requires a completed common semantic result')
    root = Path(producer_report['path']).parent
    def child(name):
        item = report[name]
        if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'bytes'} or
                not isinstance(item['path'], str) or Path(item['path']).name != item['path'] or
                item['path'] in {'.', '..'} or '\\' in item['path'] or
                type(item['bytes']) is not int or not 0 <= item['bytes'] <= _LIMIT):
            raise ValueError('invalid semantic result descriptor: ' + name)
        raw = _read(root / item['path'], item['sha256'])
        if len(raw) != item['bytes']:
            raise ValueError('semantic result byte count differs: ' + name)
        return raw
    html = child('final_html').decode('utf-8')
    draft, proof = _json(child('bindings')), _json(child('source_proof'))
    reconciliation = _json(child('reconciliation'))
    _json(child('capture_inverse'))
    _json(child('metadata'))
    artifact = _json(_absolute(request['artifact']))
    if (artifact.get('schema') != 'study-prepared-card.v1' or
            not isinstance(artifact.get('sides'), list) or len(artifact['sides']) != 2):
        raise ValueError('profile requires a complete prepared source')
    side = artifact['sides'][1]
    if (_sha(side['html'].encode()) != side['proof']['expanded_sha256'] or
            sorted(side['registry']) != side['proof']['registry_pins']):
        raise ValueError('prepared side differs from its original proof')
    for pin, text in side['registry'].items():
        if not isinstance(text, str) or _sha(text.encode()) != pin:
            raise ValueError('prepared registry differs from its original pin')
    module = request['module']
    module_raw = _absolute({key: module[key] for key in ('path', 'sha256')})
    helper_raw = _absolute(request['helpers'])
    if (_sha(helper_raw) != _HELPERS_SHA256 or
            module['original_sha256'] not in materializer.AUDITED_NATIVE_MODULES):
        raise ValueError('unsupported semantic source capability')
    module_entry = artifact['modules'].get(module['original_sha256'])
    if (not module_entry or len(artifact['modules']) != 1 or
            module_entry['sha256'] != module['sha256'] or
            module_entry['original_sha256'] != module['original_sha256']):
        raise ValueError('semantic module differs from prepared source')
    resources = [_absolute(value) for value in request['resources'].values()]
    original = next((raw for raw in resources if _sha(raw) == module['original_sha256']), None)
    if (original is None or materializer.prepare_native_module(original.decode()).encode() != module_raw):
        raise ValueError('semantic module differs from original authored source')
    expected = {
        'request_sha256': _sha(request_raw), 'artifact_sha256': request['artifact']['sha256'],
        'helpers_sha256': request['helpers']['sha256'],
        'source_wrapper_sha256': artifact['source_wrapper_sha256'],
        'source_payload_sha256': artifact['source_payload_sha256'],
        'source_side_sha256': side['proof']['source_sha256'],
        'expanded_side_sha256': side['proof']['expanded_sha256'],
        'source_side_utf8_bytes': side['proof']['source_bytes'],
        'expanded_side_utf8_bytes': len(side['html'].encode()),
        'original_module_sha256': module['original_sha256'], 'prepared_module_sha256': module['sha256'],
        'registry_pins': side['proof']['registry_pins'], 'metadata_sha256': report['metadata']['sha256'],
    }
    if (proof.get('schema') != 'study-compiled-semantic-source.v1' or
            any(proof.get(key) != value for key, value in expected.items()) or
            request['source'] != {'wrapper_sha256': artifact['source_wrapper_sha256'],
                                  'payload_sha256': artifact['source_payload_sha256']} or
            draft.get('schema') != 'study-canonical-interaction-bindings.draft.v1' or
            draft.get('source_artifact_sha256') != request['artifact']['sha256']):
        raise ValueError('semantic request/result provenance differs')
    numbering_required = '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1' in request.get('policy', {}).get('external', {}).values()
    if numbering_required or report.get('initial_numbering') is not None:
        if report.get('initial_numbering') is None:
            raise ValueError('qualified original numbering requires its initial preparation proof')
        numbered = _json(child('initial_numbering'))
        if (numbered.get('schema') != 'study-semantic-initial-numbering.v1' or
                numbered.get('source_sha256') != '9d1549871010e581820bad578577e1234f65d78f6725c6cc85a126c1ef5f84f1' or
                numbered.get('helper_sha256') != _sha((_HELPERS.parent / 'numbering-preparation.cjs').read_bytes()) or
                proof.get('initial_numbering') != report['initial_numbering'] or
                reconciliation.get('initial_numbering') != report['initial_numbering'] or
                numbered.get('source_fields_counts_and_occurrence_ids_unchanged') is not True or
                numbered.get('inverse_exact') is not True or
                numbered.get('proof', {}).get('schema') != 'study-original-numbering-dom-preparation.v1' or
                numbered['proof'].get('numberingSha256') != numbered['source_sha256'] or
                numbered['proof'].get('stats', {}).get('changedBadges') != len(numbered['proof'].get('edits', []))):
            raise ValueError('initial numbering source/proof binding differs')
    parsed = _ProfileHTML(html)
    if any(attrs.get('data-native-history-ready') != 'true' for attrs in parsed.evidence):
        raise ValueError('initial history evidence is not fully prepared')
    initial_proof = proof.get('initial_history_evidence', [])
    if (not isinstance(initial_proof, list) or len(initial_proof) != len(parsed.pre_texts) or
            reconciliation.get('initial_history_evidence', 0) != len(parsed.pre_texts)):
        raise ValueError('initial history evidence census differs')
    for item, (attrs, text) in zip(initial_proof, parsed.pre_texts):
        if (item.get('media') != attrs.get('data-native-history-media') or
                item.get('sha256') != attrs.get('data-native-history-sha') or
                item.get('complete_text_sha256') != _sha(text.encode()) or item.get('inverse_exact') is not True):
            raise ValueError('initial history evidence expansion proof differs')
    payloads = parsed.scripts_with_class('anki-final-reviewed-data')
    if len(payloads) != 1:
        raise ValueError('profile requires exactly one original native payload')
    payload_attrs = payloads[0][0]
    raw_side, raw_index = payload_attrs.get('data-as-sha'), payload_attrs.get('data-as-index-sha')
    if raw_side not in side['registry'] or raw_index not in side['registry']:
        raise ValueError('native payload refers outside the original registry')
    manifests = parsed.scripts_with_class('as-manifest')
    if reconciliation.get('closed_history_manifests_preserved') != len(manifests):
        raise ValueError('closed-history census differs from semantic reconciliation')
    parts, evidence = _history_inputs(manifests, media, parsed.pre_texts)
    bindings = {
        'producerInputSha256': report['bindings']['sha256'], 'sourceArtifactSha256': request['artifact']['sha256'],
        'derivedHTMLSha256': report['final_html']['sha256'], 'sourceWrapperSha256': proof['source_wrapper_sha256'],
        'sourcePayloadSha256': proof['source_payload_sha256'], 'sourceSideSha256': proof['source_side_sha256'],
        'expandedSideSha256': proof['expanded_side_sha256'],
        'materializerSha256': _sha(Path(materializer.__file__).read_bytes()),
        'frameRuntimeSha256': materializer.digest(materializer.PREPARED_FRAME_RUNTIME),
        'frameHTMLSha256': materializer.digest(materializer.prepared_frame_html()),
        'adapterSha256': request['helpers']['sha256'], 'nativeModuleSha256': module['sha256'],
        'originalModuleSha256': module['original_sha256'], 'rawSideSha256': raw_side, 'rawIndexSha256': raw_index,
        **_delegate_pins(resources),
    }
    destination.mkdir()
    def store(raw, suffix):
        pin = _sha(raw)
        path = destination / (pin + suffix)
        if path.exists():
            if path.is_symlink() or path.read_bytes() != raw:
                raise ValueError('profile input address collision')
        else:
            with path.open('xb') as stream:
                stream.write(raw)
        return {'path': str(path.resolve()), 'sha256': pin}
    result = {'schema': 'study-compiled-profile-request.v1', 'producer_report': producer_report,
              'bindings': store(json.dumps(bindings, separators=(',', ':')).encode(), '.json')}
    if manifests or parsed.evidence:
        result['history'] = {'source_request': semantic_request,
                             'parts': {pin: store(raw, '.html') for pin, raw in sorted(parts.items())},
                             'evidence': {name: store(raw, '.js') for name, raw in sorted(evidence.items())}}
    result_raw = json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()
    with (destination / 'request.json').open('xb') as stream:
        stream.write(result_raw)
    return {'schema': 'study-compiled-profile-inputs.v1',
            'request': {'path': str((destination / 'request.json').resolve()), 'sha256': _sha(result_raw)},
            'closed_history_manifests': len(manifests), 'history_parts': len(parts), 'history_evidence': len(evidence),
            'initial_history_evidence': len(parsed.pre_texts),
            'product_enabled': False}
