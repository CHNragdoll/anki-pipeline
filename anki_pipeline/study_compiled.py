"""Build-time inputs for the shared complete-card semantic producer.

This stage consumes an explicit, pinned prepared source. It neither changes
catalog content nor enables a delivery host. Both hosts must consume the same
result through their normal field projection before a full-build claim.
"""
from __future__ import annotations

import hashlib
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
               'resources': {url: store(raw, '.js') for url, raw in sorted(resources.items())},
               'base_url': base_url, 'source_url': source_url, 'policy': policy}
    request_raw = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode()
    with (destination / 'request.json').open('xb') as stream:
        stream.write(request_raw)
    return {'schema': 'study-compiled-semantic-inputs.v1',
            'request': {'path': str((destination / 'request.json').resolve()), 'sha256': _sha(request_raw)},
            'raw_wrapper_and_payload_verified': True,
            'source_files_unchanged': True, 'script_resources': len(resources),
            'product_enabled': False}
