"""Pure native host projection of an already authenticated shared delivery.

This adapter does not compile source content, write catalog versions or publish
an APKG. Call it only after producing the common semantic artifact. The extra
field is transport data and must never become a semantic producer input.
"""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from . import study_catalog_web_materialize as materializer
from .study_compiled_runtime import ADMITTED_RUNTIME_SHA256, LEGACY_RUNTIME_SHA256

FIELD = 'StudyCompiledDelivery'
_HASH = re.compile(r'[a-f0-9]{64}')
_NAME = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*')
_MODULES = {
    '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e':
    '7f16cca577841d16037b879714e9518570226c3a8e024f898c3b5a335ac995b4',
    'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93':
    '6a2b0f26c883d52e8ec2e4df0656ae9dae258a5cc41e0b84f2aa73da3d228633',
}
_RUNTIME = ADMITTED_RUNTIME_SHA256


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _slice(source, first, following):
    first, following = '\n' + first, '\n' + following
    if source.count(first) != 1:
        raise ValueError('native support source boundary differs: ' + first.strip())
    start = source.index(first)
    end = source.find(following, start + len(first))
    if end < 0:
        raise ValueError('native support source end differs')
    return source[start:end] + '\n'


def _bootstrap_parts():
    """Return a content-versioned factory, without a self-referential hash."""
    frame = materializer.PREPARED_FRAME_RUNTIME
    # The task scheduler is a browser preparation service, not needed by the
    # compiled native branch; only its exact source adapter is retained.
    task = materializer.PROJECTION_TASK_RUNTIME
    marker = '\nfunction adaptNativeProjectionTask'
    if task.count(marker) != 1:
        raise ValueError('native projection adapter boundary differs')
    frozen_adapter = _slice(frame, 'function adaptCompiledFrozenProfile', 'function makeCompiledProfileSupport')
    guard = "if(pin!=='" + LEGACY_RUNTIME_SHA256 + "')return code;"
    if frozen_adapter.count(guard) != 1:
        raise ValueError('native compatible binder adapter boundary differs')
    frozen_adapter = frozen_adapter.replace(guard, "if(!" + _json(sorted(_RUNTIME)) + ".includes(pin))return code;", 1)
    support = (materializer.KNOWN_PIN_INTEGRITY_RUNTIME +
               _slice(frame, 'function adaptNativeProjectionLookup', 'function bridgeRealmDigest') +
               task[task.index(marker):] +
               frozen_adapter +
               _slice(frame, 'function adaptActiveSlimCompiledProfile', 'const compiledAssets='))
    raw = Path(__file__).with_name('compiled').joinpath('native-bootstrap.js').read_text('utf-8')
    if raw.count('/*__SHARED_NATIVE_ADAPTERS__*/') != 1:
        raise ValueError('native bootstrap source boundary differs')
    factory = raw.replace('/*__SHARED_NATIVE_ADAPTERS__*/', support).rstrip()
    if not factory.endswith('})'):
        raise ValueError('native bootstrap factory boundary differs')
    return factory, _sha(factory.encode())


def native_bootstrap_source():
    """Reuse exact current adapters; no copied experimental runtime baseline."""
    factory, version = _bootstrap_parts()
    return factory + '(' + _json(version) + ',window,document);\n'


def project_native_note(note, entry, runtime, *, prepared=None, policy=None,
                        resources=None, model_mod=None, note_mod=None,
                        original_model_mod=None, original_note_mod=None):
    """Return an export-only note/model and content-addressed media carriers.

    ``resources`` maps explicit local basenames to immutable original bytes.
    Their HTML/profile logical bytes are identical to the web delivery. Source
    fields and all original identities are retained; only a new transport field
    is appended. Supplied versions must already be committed by the caller.
    Explicit original versions identify the sealed import baseline when current
    projected versions already include those committed delivery revisions.
    """
    result = copy.deepcopy(note)
    if entry is None:
        return {'note': result, 'media': {}, 'capability': 'original-native'}
    model_baseline = note['model']['mod'] if original_model_mod is None else original_model_mod
    note_baseline = note['payload']['mod'] if original_note_mod is None else original_note_mod
    if (type(model_baseline) is not int or type(note_baseline) is not int or
            model_baseline < 0 or note_baseline < 0 or
            model_baseline > note['model']['mod'] or note_baseline > note['payload']['mod'] or
            type(model_mod) is not int or model_mod <= model_baseline or model_mod < note['model']['mod'] or
            type(note_mod) is not int or note_mod <= note_baseline or
            note_mod < max(note['payload']['mod'], note.get('content_mod') or 0)):
        raise ValueError('new committed model and note versions are required')
    if FIELD in note['field_names']:
        raise ValueError('transport fields cannot be compiled as semantic source')
    if len(note['model']['tmpls']) != 1:
        raise ValueError('one explicit compiled delivery is required per native template')
    if any(re.search(r'\[sound:[^\]\r\n]+\]', text) for text in note['fields']):
        raise ValueError('native sound tags require their original Anki replay protocol')
    if not isinstance(runtime, dict) or runtime.get('sha256') not in _RUNTIME:
        raise ValueError('unsupported native compiled binder runtime')
    resources = dict(resources) if isinstance(resources, dict) else resources
    if (not isinstance(prepared, dict) or prepared.get('schema') != 'study-prepared-card.v1' or
            len(prepared.get('sides', [])) != 2 or not isinstance(policy, dict) or
            set(policy) != {'external', 'inline'} or not isinstance(resources, dict)):
        raise ValueError('explicit complete prepared source, policy and resources are required')
    module = entry.get('module', {})
    original = module.get('original_sha256')
    if _MODULES.get(original) != module.get('sha256'):
        raise ValueError('unsupported native compiled module cohort')
    actual = prepared.get('modules', {}).get(original)
    if not actual or any(actual.get(k) != module.get(k) for k in ('original_sha256', 'sha256')):
        raise ValueError('prepared native module differs from compiled entry')
    source = entry.get('source', {})
    back = prepared['sides'][1]
    proof = back.get('proof', {})
    if (source.get('wrapper_sha256') != prepared.get('source_wrapper_sha256') or
            source.get('payload_sha256') != prepared.get('source_payload_sha256') or
            source.get('side_sha256') != proof.get('source_sha256') or
            source.get('expanded_sha256') != proof.get('expanded_sha256') or
            source.get('registry_pins') != proof.get('registry_pins')):
        raise ValueError('compiled entry does not bind the complete prepared source')
    media, transport = {}, {}
    def asset(descriptor):
        if (not isinstance(descriptor, dict) or not _NAME.fullmatch(descriptor.get('src', '')) or
                not _HASH.fullmatch(descriptor.get('sha256', ''))):
            raise ValueError('native asset requires a local basename and SHA')
        name, pin = descriptor['src'], descriptor['sha256']
        raw = resources.get(name)
        if not isinstance(raw, bytes) or _sha(raw) != pin:
            raise ValueError('native asset bytes differ: ' + name)
        text = raw.decode('utf-8')
        carrier = ('window.StudyCompiledNative.register(' + _json(pin) + ',' +
                   _json(text).replace('<', '\\u003c') + ');').encode()
        address = '_study_native_' + _sha(carrier) + '.js'
        media[address] = carrier
        transport[name] = {'src': address, 'sha256': pin}
        return text
    html = asset(entry.get('html')); profile_raw = asset(entry.get('profile'))
    asset(runtime)
    profile = json.loads(profile_raw)
    anchors = entry.get('anchors', {})
    if (entry.get('decoded') is not True or profile.get('schema') != 'study-compiled-card-interactions.v1' or
            profile.get('version') != 1 or anchors.get('schema') != profile['schema'] or
            anchors.get('version') != 1 or anchors.get('bindings') != profile.get('bindings') or
            anchors.get('profileSha256') != entry['profile']['sha256'] or
            anchors.get('htmlSha256') != entry['html']['sha256'] or
            profile['bindings'].get('derivedHTMLSha256') != _sha(html.encode()) or
            profile['bindings'].get('originalModuleSha256') != original or
            profile['bindings'].get('nativeModuleSha256') != module['sha256']):
        raise ValueError('native compiled profile bindings differ')
    bindings = profile['bindings']
    source_bindings = {
        'sourceWrapperSha256': source.get('wrapper_sha256'),
        'sourcePayloadSha256': source.get('payload_sha256'),
        'sourceSideSha256': source.get('side_sha256'),
        'expandedSideSha256': source.get('expanded_sha256'),
    }
    if any(not isinstance(pin, str) or not _HASH.fullmatch(pin) or bindings.get(key) != pin
           for key, pin in source_bindings.items()):
        raise ValueError('native profile source bindings differ')
    class NativePayload(HTMLParser):
        def __init__(self):
            super().__init__(); self.payloads, self.template_depth = [], 0
        def handle_starttag(self, tag, attrs):
            if tag == 'template':
                self.template_depth += 1
            if self.template_depth or tag != 'script':
                return
            values = dict(attrs)
            if 'anki-final-reviewed-data' in values.get('class', '').split():
                if len(values) != len(attrs):
                    raise ValueError('duplicate native payload attributes')
                self.payloads.append(values)
        def handle_endtag(self, tag):
            if tag == 'template' and self.template_depth:
                self.template_depth -= 1
    payload_parser = NativePayload(); payload_parser.feed(back['html']); payload_parser.close()
    if len(payload_parser.payloads) != 1:
        raise ValueError('native source requires one original registry payload')
    payload_attrs = payload_parser.payloads[0]
    for key, name in [('rawSideSha256', 'data-as-sha'), ('rawIndexSha256', 'data-as-index-sha')]:
        pin = payload_attrs.get(name)
        if not isinstance(pin, str) or not _HASH.fullmatch(pin) or pin not in back.get('registry', {}) or bindings.get(key) != pin:
            raise ValueError('native profile registry binding differs')
    local_media, history_proofs, decoded, decoding = {}, {}, {}, set()
    def registration(pin):
        if not _HASH.fullmatch(pin or '') or pin in decoding:
            raise ValueError('invalid or cyclic native history registration')
        if pin in decoded:
            return decoded[pin]
        decoding.add(pin)
        try:
            names = ['_ac_' + pin[:24] + '.js', '_as_' + pin[:24] + '.js']
            name = next((name for name in names if name in resources), None)
            if name is None:
                raise ValueError('missing explicit native history resource: ' + pin)
            raw = resources[name]
            if not isinstance(raw, bytes):
                raise ValueError('native history resource is not immutable bytes')
            match = materializer._REGISTRY.fullmatch(raw.decode('utf-8'))
            if not match or match[1] != pin:
                raise ValueError('native history source is not an inert registration')
            value = json.loads(match[2])
            if isinstance(value, dict):
                if value.get('schema') != 'anki-slim-shared-strings.v1':
                    raise ValueError('unsupported native history packing')
                info = value.get('dict', {})
                if info.get('src') != '_as_' + info.get('sha256', '')[:24] + '.js':
                    raise ValueError('native shared dictionary identity differs')
                bank = json.loads(registration(info.get('sha256')))
                if bank.get('schema') != 'anki-slim-shared-dictionary.v1':
                    raise ValueError('native shared dictionary schema differs')
                value = materializer.expand(value['pieces'], materializer.prepare_dictionary(bank['strings']))
            if not isinstance(value, str) or _sha(value.encode()) != pin:
                raise ValueError('native history logical SHA differs')
            descriptor = {'src': name, 'sha256': _sha(raw)}
            asset(descriptor)
            local_media[name] = descriptor
            # A literal dictionary asks for its logical _as name even if its
            # authenticated exact registration is stored under the _ac alias.
            local_media[names[1]] = descriptor
            history_proofs[name] = {'raw_sha256': _sha(raw), 'logical_sha256': pin}
            decoded[pin] = value
            return value
        finally:
            decoding.remove(pin)
    has_initial = 'initialHistorySlots' in profile
    has_bank = 'initialHistoryText' in profile
    initial = profile.get('initialHistorySlots', [])
    bank = profile.get('initialHistoryText', {})
    if (has_initial != has_bank or not isinstance(initial, list) or not isinstance(bank, dict) or
            any(not isinstance(pin, str) or not _HASH.fullmatch(pin) or not isinstance(text, str)
                for pin, text in bank.items())):
        raise ValueError('native history text bank shape differs')
    used_bank = set()

    def history_text(evidence, *, initial=False):
        if not isinstance(evidence, dict):
            raise ValueError('native history evidence shape differs')
        pin = evidence.get('sha256')
        if not isinstance(pin, str) or not _HASH.fullmatch(pin):
            raise ValueError('native history evidence logical SHA differs')
        inline, shared = 'text' in evidence, 'textKey' in evidence
        if initial or shared:
            if (inline or (initial and shared) or (not initial and evidence['textKey'] != pin) or
                    pin not in bank or _sha(bank[pin].encode()) != pin):
                raise ValueError('native history shared evidence differs')
            used_bank.add(pin)
            return bank[pin]
        if not inline or not isinstance(evidence['text'], str) or _sha(evidence['text'].encode()) != pin:
            raise ValueError('native history inline evidence differs')
        return evidence['text']

    def history_asset(evidence, text):
        name, pin = evidence.get('media'), evidence['sha256']
        if not isinstance(name, str) or not re.fullmatch(r'_af_[a-f0-9]{24}\.js', name):
            raise ValueError('native history evidence media differs')
        raw = resources.get(name)
        if not isinstance(raw, bytes) or _sha(raw) != evidence.get('resourceSha256'):
            raise ValueError('native history evidence raw SHA differs')
        match = materializer._HISTORY.fullmatch(raw.decode('utf-8'))
        if not match or match[1] != pin or json.loads(match[2]) != text:
            raise ValueError('native history evidence logical source differs')
        descriptor = {'src': name, 'sha256': _sha(raw)}
        asset(descriptor); local_media[name] = descriptor
        history_proofs[name] = {'raw_sha256': _sha(raw), 'logical_sha256': pin}

    for evidence in initial:
        history_asset(evidence, history_text(evidence, initial=True))
    for slot in profile.get('historySlots', []):
        for part in slot['parts']:
            if part['src'] != '_as_' + part['sha256'][:24] + '.js':
                raise ValueError('native history part name differs')
            registration(part['sha256'])
            for evidence in part['evidence']:
                history_asset(evidence, history_text(evidence))
    if set(bank) != used_bank:
        raise ValueError('native history text bank has unused evidence')
    # Authenticate source dependencies before any package bytes are returned.
    for src, pin in policy['external'].items():
        if pin == original:
            continue
        asset({'src': src, 'sha256': pin})
    loaders, loader_proofs = {}, {}
    for pin, value in prepared['modules'].items():
        # Web directories are not Anki media names; only the pinned basename is
        # carried, and the packet preserves the original logical reference.
        name = value['src'].rsplit('/', 1)[-1]
        raw = resources.get(name)
        if pin != original or not isinstance(raw, bytes) or _sha(raw) != value['sha256']:
            raise ValueError('explicit native prepared module bytes differ')
        text = raw.decode('utf-8')
        decode_end = '};window.AnkiSlimDecode(document);\n'
        decode_start = "window.AnkiSlimDecode=function(root){'use strict';"
        if text.count(decode_start) != 1 or text.count(decode_end) != 1:
            raise ValueError('audited native fragment decoder boundary differs')
        decoder_start = text.index(decode_start)
        decoder_end = text.index(decode_end) + 2
        decoder = text[decoder_start:decoder_end]
        marker = '/* Offline shared literals only. The outer loader verifies the dictionary and\n'
        if text.count(marker) != 1 or not text.endswith('})();\n'):
            raise ValueError('audited native codec/active loader boundary differs')
        loader = text[text.index(marker):]
        if loader.count('  async function hydrate() {') != 1:
            raise ValueError('audited native active loader differs')
        published = '  window.AnkiResidualReviewedChunkRuntime = Object.freeze({ install: install });\n})();'
        if text.count(published) != 1:
            raise ValueError('audited native residual runtime differs')
        residual_end = text.index(published) + len(published)
        residual_start = text.rfind('\n(function () {\n', 0, residual_end)
        if residual_start < 0:
            raise ValueError('audited native residual boundary differs')
        codec_start = text.index(marker)
        residual = text[residual_start:residual_end]
        loader = decoder + '\n' + residual + '\n' + loader
        loader_name = '_study_native_loader_' + _sha(loader.encode()) + '.js'
        resources[loader_name] = loader.encode()
        asset({'src': loader_name, 'sha256': _sha(loader.encode())})
        loaders[pin] = {'src': loader_name, 'sha256': _sha(loader.encode()),
                        'original_sha256': pin, 'module_sha256': value['sha256']}
        loader_proofs[pin] = {'module_sha256': value['sha256'], 'extracted_sha256': _sha(loader.encode()),
                              'source_ranges': [[decoder_start, decoder_end], [residual_start, residual_end], [codec_start, len(text)]],
                              'offset_unit': 'unicode-codepoints', 'join': '\n',
                              'decoder_initial_document_call_removed': True,
                              'original_four_semantic_definitions_excluded': True}
    for side in prepared['sides']:
        for pin, text in side.get('registry', {}).items():
            if not _HASH.fullmatch(pin) or not isinstance(text, str) or _sha(text.encode()) != pin:
                raise ValueError('prepared native registry SHA differs')
        if _sha(side['html'].encode()) != side.get('proof', {}).get('expanded_sha256'):
            raise ValueError('prepared side SHA differs')
    class Styles(HTMLParser):
        def __init__(self):
            super().__init__(); self.names = set()
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'link' and 'stylesheet' in attrs.get('rel', '').split():
                if set(attrs) != {'href', 'rel'} or attrs['rel'].strip() != 'stylesheet':
                    raise ValueError('unsupported native stylesheet attributes')
                self.names.add(attrs['href'])
    parser = Styles()
    parser.feed(prepared['sides'][0]['html']); parser.feed(html)
    styles = {}
    for name in sorted(parser.names):
        if not _NAME.fullmatch(name) or not isinstance(resources.get(name), bytes):
            raise ValueError('stylesheet needs an explicit local resource')
        styles[name] = {'src': name, 'sha256': _sha(resources[name])}
        asset(styles[name])
    def children(values):
        result = []
        for child in values:
            if (not isinstance(child.get('source'), str) or
                    _sha(child['source'].encode()) != child.get('source_sha256') or
                    not isinstance(child.get('html'), str)):
                raise ValueError('original child source SHA differs')
            result.append({'html': child['html'], 'html_sha256': _sha(child['html'].encode()),
                           'source_sha256': child['source_sha256']})
        return result
    def generated(value, kind):
        raw = _json(value).encode(); pin = _sha(raw)
        name = '_study_native_' + kind + '_' + pin + '.json'
        resources_local = resources.get(name)
        if resources_local is not None and resources_local != raw:
            raise ValueError('generated native resource collides')
        resources[name] = raw
        asset({'src': name, 'sha256': pin})
        return {'src': name, 'sha256': pin}
    # No second copy of the expanded back or semantic raw-side/index is needed:
    # the authenticated compiled branch never reads those original inputs.
    packet = {'front': {'html': prepared['sides'][0]['html'], 'proof': prepared['sides'][0]['proof'],
                        'children': children(prepared['sides'][0].get('children', []))},
              'back_children': children(back.get('children', [])), 'modules': loaders}
    descriptor = {'id': note['id'], 'entry': entry, 'runtime': runtime,
                  'packet': generated(packet, 'packet'), 'policy': generated(policy, 'policy'),
                  'transport': transport, 'styles': styles, 'local_media': local_media}
    factory, bootstrap_version = _bootstrap_parts()
    bootstrap = (factory + '(' + _json(bootstrap_version) + ',window,document);\n').encode()
    bootstrap_name = '_study_native_bootstrap_' + _sha(bootstrap) + '.js'
    descriptor['bootstrap_version'] = bootstrap_version
    media[bootstrap_name] = bootstrap
    result['field_names'].append(FIELD)
    result['fields'].append(_json(descriptor).replace('<', '\\u003c'))
    model = result['model']; model['mod'] = model_mod
    model['flds'].append({'name': FIELD, 'ord': len(model['flds']), 'sticky': False,
                          'rtl': False, 'font': 'Arial', 'size': 12, 'media': []})
    for template in model['tmpls']:
        def shell(answer):
            return ('<section data-study-native-owner data-answer="' + str(answer).lower() + '">'
                    '<script type="application/json" data-study-native-delivery>{{' + FIELD + '}}</script>'
                    '<p role="status" data-study-native-status>正在校验完整卡片…</p></section>'
                    '<script src="' + bootstrap_name + '"></script>')
        template['qfmt'], template['afmt'] = shell(False), shell(True)
    result['content_mod'] = note_mod
    result['payload']['mod'] = note_mod
    return {'note': result, 'media': media, 'capability': 'compiled-native',
            'source_fields_sha256': _sha(_json(note['fields']).encode()),
            'source_model_sha256': _sha(_json(note['model']).encode()),
            'history_sources': history_proofs, 'loader_sources': loader_proofs}
