"""Lossless delivery-only protection for known inline field transport scripts.

Authored PG fields and old media are never rewritten. Empty phrasing carriers
are appended at original offsets; removing them recovers each source byte.
"""
from __future__ import annotations

import base64
import copy
import hashlib
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re

SCHEMA = 'study-field-script.v1'
MARKER = 'data-study-script-source'
SAFE_PARENTS = frozenset('div section article aside main header footer nav figure figcaption details li dd dt blockquote p span a b i em strong small label body'.split())
FORBIDDEN_CONTEXT = frozenset('table thead tbody tfoot tr colgroup select option optgroup svg math template noscript head'.split())
VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
RUNTIME_PATH = Path(__file__).with_name('templates') / 'field-script-restore.js'
# Actual original field bridge; restoration stays inert. Its template controller
# must also be present, so unknown executable field scripts cannot gain a path.
CIGEN_PINS = frozenset({'e938f4c52ba27633c8617a014f2e79f29c0abce1ed62c590ad74271c07d146de'})
CIGEN_CONTROLLER = ('43c9161e273ed3d85109cc31e0e30232aaa6626be802401edd7976e6e74877e2', 3256)


def _digest(raw):
    return hashlib.sha256(raw.encode() if isinstance(raw, str) else raw).hexdigest()


def source_pins():
    from . import study_catalog_anki
    return {'runtime_sha256': _digest(RUNTIME_PATH.read_bytes()),
            'projector_sha256': _digest(Path(__file__).read_bytes()),
            'versions_sha256': _digest(Path(study_catalog_anki.__file__).read_bytes())}


def _hydrate_rows(value):
    result = []
    for row in _Scripts(value).scripts:
        attrs = dict(row['attrs'])
        body = row['text'].strip()
        prefix = 'window.StudyFieldScriptTransport.restore(document);'
        if body.startswith(prefix):
            body = body[len(prefix):].strip()
        if (re.fullmatch(r'window\.(?:AnkiSlimApkgHydrate|AnkiFinalApkgHydrate)\s*\(\s*\)\s*;?', body)
                and attrs.get('type', '').lower() in ('', 'text/javascript', 'application/javascript') and 'src' not in attrs):
            result.append(row)
    return result


def _registered(book, mids):
    runtime = book.get('runtime_revision')
    marker = runtime.get('field_script_transport') if isinstance(runtime, dict) else None
    if not isinstance(marker, dict) or marker.get('schema') != 'study-field-script-registration.v1' or marker.get('sources') != source_pins():
        raise ValueError('field-script protection requires current explicitly registered source pins')
    previous = marker.get('previous_runtime', {})
    if (not isinstance(previous, dict) or type(previous.get('revision')) is not int or type(previous.get('floor')) is not int
            or type(runtime.get('revision')) is not int or runtime['revision'] != previous['revision'] + 1
            or type(runtime.get('floor')) is not int or runtime['floor'] < previous['floor']):
        raise ValueError('field-script protection runtime version did not advance')
    versions = marker.get('models', {})
    if not isinstance(versions, dict) or set(versions) != mids:
        raise ValueError('field-script registration does not cover exact affected models')
    for mid, value in versions.items():
        if (not isinstance(value, dict) or set(value) != {'before', 'after'} or type(value['before']) is not int
                or type(value['after']) is not int or value['after'] <= value['before']
                or book['models'][mid]['mod'] != value['after']):
            raise ValueError('field-script model version must exceed previous registered candidate')
    return marker


def registration_plan(db, books, *, expected_revision):
    """Read-only plan, using the existing version writers against a write sink.

    Root applies the returned exact two metadata values only after backing up
    before-values and validating CAS under the common lock/transaction. This
    function never issues a data write through ``db``.
    """
    from . import study_catalog as c
    from . import study_catalog_anki as native
    from .study_catalog_export import project_book
    if not isinstance(books, (list, tuple)) or not books or any(type(book) is not str or not book for book in books) or len(set(books)) != len(books):
        raise ValueError('explicit unique book IDs required')
    revision = db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    if type(expected_revision) is not int or revision != expected_revision:
        raise ValueError('field-script registration event revision changed')
    keys = (native.MODEL_MODS, native.RUNTIME_REVISIONS)
    before = {key: None for key in keys}
    before.update(dict(db.execute('select key,value from metadata where key=ANY(%s)', (list(keys),))))
    projected = {book: project_book(db, book) for book in sorted(books)}
    affected = {book: {mid: model['mod'] for mid, model in value['models'].items()
                        if any(_hydrate_rows(t[side]) for t in model['tmpls'] for side in ('qfmt', 'afmt'))}
                for book, value in projected.items()}
    selected = [book for book in sorted(books) if affected[book]]
    if not selected:
        raise ValueError('no recognized inline native models in selected books')
    captured = {}
    class VersionSink:
        def execute(self, query, params=()):
            text = str(query).strip().lower()
            if text.startswith('select '):
                return db.execute(query, params)
            if text.startswith('insert into metadata values') and len(params) == 2 and params[0] in keys:
                captured[params[0]] = params[1]
                return None
            raise ValueError('version plan attempted an unapproved write')
    sink = VersionSink()
    native.bump_model_mods(sink, [(book, mid) for book in selected for mid in affected[book]])
    native._advance_runtime_revisions(sink, selected)
    models, runtimes = json.loads(captured[native.MODEL_MODS]), json.loads(captured[native.RUNTIME_REVISIONS])
    prior_runtime = json.loads(before[native.RUNTIME_REVISIONS]) if before[native.RUNTIME_REVISIONS] is not None else {}
    for book in selected:
        prior = prior_runtime.get(book, {'revision': 0, 'floor': 0})
        if isinstance(prior, int):
            prior = {'revision': prior, 'floor': 0}
        runtimes[book]['field_script_transport'] = {'schema': 'study-field-script-registration.v1', 'sources': source_pins(),
            'previous_runtime': {key: prior[key] for key in ('revision', 'floor')},
            'models': {mid: {'before': old, 'after': models[c.identity(book, mid)]} for mid, old in affected[book].items()}}
    captured[native.RUNTIME_REVISIONS] = c.canonical(runtimes)
    result = {'schema': 'study-field-script-registration-plan.v1', 'event_revision': revision,
              'books': selected, 'affected_models': affected, 'sources': source_pins(),
              'runtime_version_scope_note_counts': {book: db.execute('select count(*) from notes where book_id=%s', (book,)).fetchone()[0] for book in selected},
              'metadata_before': before, 'metadata_after': captured,
              'writes': list(keys), 'canonical_fields_media_learning_written': False}
    return {**result, 'sha256': _digest(c.canonical(result))}


def validate_registration_plan(db, plan, *, expected_sha256, rollback=False, unpublished=False):
    """CAS check only, under the existing common lock/transaction.

    Rollback is restricted to an explicitly unpublished operation and exact
    current after-values. A returned ``None`` before-value means delete that
    metadata key; callers must not insert a SQL NULL or JSON null instead.
    """
    from . import study_catalog as c
    from . import study_catalog_anki as native
    body = {key: value for key, value in plan.items() if key != 'sha256'}
    keys = {native.MODEL_MODS, native.RUNTIME_REVISIONS}
    if type(rollback) is not bool or type(unpublished) is not bool or rollback and not unpublished:
        raise ValueError('field-script rollback requires explicit unpublished=True')
    if (plan.get('schema') != 'study-field-script-registration-plan.v1' or plan.get('sha256') != expected_sha256
            or plan.get('sha256') != _digest(c.canonical(body))
            or plan.get('sources') != source_pins() or set(plan.get('metadata_before', {})) != keys
            or set(plan.get('metadata_after', {})) != keys or set(plan.get('writes', [])) != keys):
        raise ValueError('field-script registration plan/source seal differs')
    revision = db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    current = {key: None for key in keys}
    current.update(dict(db.execute('select key,value from metadata where key=ANY(%s)', (list(keys),))))
    expected = plan['metadata_after' if rollback else 'metadata_before']
    if revision != plan['event_revision'] or current != expected:
        raise ValueError('field-script registration stale metadata/revision CAS')
    return copy.deepcopy(plan['metadata_before' if rollback else 'metadata_after'])


class _Scripts(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=False)
        self.raw, self.stack, self.rows, self.active, self.scripts = raw, [], [], None, []
        self.lines = [0]
        self.lines.extend(i + 1 for i, char in enumerate(raw) if char == '\n')
        self.feed(raw)
        self.close()
        if self.active is not None:
            raise ValueError('unclosed field transport script')

    def absolute_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attrs = [(name, (value or '').replace('\r\n', '\n').replace('\r', '\n')) for name, value in attrs]
        if any(name == MARKER or name.startswith('data-study-script-') for name, _ in attrs):
            raise ValueError('source already contains reserved field-script carrier metadata')
        if tag == 'script':
            values = dict(attrs)
            classes = values.get('class', '').split()
            kind = ('reviewed' if 'anki-final-reviewed-data' in classes else
                    'manifest' if 'as-manifest' in classes else
                    'cigen' if 'data-cigen-frame-bridge' in values else None)
            if kind:
                if sum((('anki-final-reviewed-data' in classes), ('as-manifest' in classes), ('data-cigen-frame-bridge' in values))) != 1:
                    raise ValueError('ambiguous field transport kind')
                if (len(values) != len(attrs) or 'src' in values or 'is' in values or any(name.startswith('on') for name in values)
                        or any(not re.fullmatch(r'[a-z_][a-z0-9_.:-]*', name) for name in values)):
                    raise ValueError('ambiguous/active field transport attributes')
                if kind != 'cigen' and values.get('type', '').lower() != 'application/json':
                    raise ValueError('known data transport must be inert application/json')
                if kind == 'cigen' and values['data-cigen-frame-bridge'] != 'v1':
                    raise ValueError('unknown Cigen field bridge version')
                if any(parent in FORBIDDEN_CONTEXT for parent in self.stack) or self.stack and self.stack[-1] not in SAFE_PARENTS:
                    raise ValueError('unsupported field carrier parent grammar')
            start = self.absolute_offset()
            self.active = {'start': start, 'opened': start + len(self.get_starttag_text()),
                           'attrs': attrs, 'kind': kind, 'parent': self.stack[-1] if self.stack else None}
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == 'script':
            raise ValueError('self-closing script transport is unsupported')
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == 'script' and self.active is not None:
            row = self.active
            row['text'] = self.raw[row['opened']:self.absolute_offset()].replace('\r\n', '\n').replace('\r', '\n')
            end = self.raw.find('>', self.absolute_offset())
            if end < 0 or '\x00' in row['text'] or any('\x00' in value for _, value in row['attrs']):
                raise ValueError('invalid field script text/closing tag')
            row['end'] = end + 1
            self.scripts.append(row)
            if row['kind']:
                self.rows.append(row)
            self.active = None
        if tag in self.stack:
            del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag):]


def protect_field(raw, *, cigen_controller=False, field_name=''):
    parser = _Scripts(raw)
    edits = []
    field_key = _digest(field_name + '\x00' + raw) if parser.rows else None
    for ordinal, row in enumerate(parser.rows):
        if row['kind'] == 'cigen' and (not cigen_controller or _digest(row['text']) not in CIGEN_PINS):
            raise ValueError('unverified Cigen field/template controller pairing')
        payload = {key: row[key] for key in ('attrs', 'text', 'parent', 'kind')}
        payload['schema'] = SCHEMA
        encoded = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        source = base64.b64encode(encoded).decode('ascii')
        key = field_key + ':' + str(ordinal)
        carrier = ('<span hidden="" style="display:none!important" aria-hidden="true" '
                   'data-study-script-transport="v1" data-study-script-key="' + key + '" '
                   'data-study-script-sha256="' + _digest(encoded) + '" '
                   + MARKER + '="' + source + '"></span>')
        edits.append((row['end'], carrier))
    result = raw
    for at, carrier in reversed(edits):
        result = result[:at] + carrier + result[at:]
    # The inverse concerns original bytes, independent of HTML serialization.
    inverse = result
    for _, carrier in edits:
        if inverse.count(carrier) != 1:
            raise ValueError('ambiguous carrier inverse')
        inverse = inverse.replace(carrier, '', 1)
    if inverse != raw:
        raise ValueError('field carrier exact inverse failed')
    return result


def protect_fields(model, names, fields):
    known = [_Scripts(value).rows for value in fields]
    if not any(known):
        return fields
    templates = model['tmpls']
    def controller(template):
        for script in _Scripts(template).scripts:
            start = script['text'].find("(function(){\nconst key='__ankiCigenFrames';")
            if start >= 0:
                candidate = script['text'][start:start + CIGEN_CONTROLLER[1]]
                if _digest(candidate) == CIGEN_CONTROLLER[0]:
                    return True
        return False
    cigen_controller = (all(controller(template['afmt']) for template in templates)
                        if any(row['kind'] == 'cigen' for rows in known for row in rows) else False)
    for index, rows in enumerate(known):
        if not rows:
            continue
        field = names[index]
        for template in templates:
            for side in ('qfmt', 'afmt'):
                used = any(token.strip().split(':')[-1] == field for token in re.findall(r'{{([^{}]+)}}', template[side]))
                if used and not _hydrate_rows(template[side]):
                    raise ValueError('field transport has no recognized pre-hydrate template boundary')
    return [protect_field(value, cigen_controller=cigen_controller, field_name=name) if rows else value
            for name, value, rows in zip(names, fields, known)]


def project_inline_book(book):
    """One pure overlay for both default hosts; compiled delivery never calls it."""
    if book.get('field_script_transport'):
        return book
    models = copy.deepcopy(book['models'])
    runtime = {**book['runtime'], 'generated': dict(book['runtime']['generated'])}
    resource = RUNTIME_PATH.read_bytes()
    alias = '_study_field_script_' + _digest(resource) + '.js'
    changed = set()
    for mid, model in models.items():
        for template in model['tmpls']:
            for side in ('qfmt', 'afmt'):
                value = template[side]
                boundaries = _hydrate_rows(value)
                if not boundaries:
                    continue
                if len(boundaries) != 1 or 'data-study-field-restore' in value:
                    raise ValueError('ambiguous/already bound native hydrate template')
                at = boundaries[0]['start']
                hook = '<script src="' + escape(alias, quote=True) + '" data-study-field-restore="v1"></script>'
                body = boundaries[0]['opened']
                # Same script execution: a restoration failure prevents hydrate,
                # unlike an earlier independent script whose exception is ignored.
                template[side] = (value[:at] + hook + value[at:body]
                                  + 'window.StudyFieldScriptTransport.restore(document);' + value[body:])
                changed.add(mid)
    if not changed:
        if isinstance(book.get('runtime_revision'), dict) and 'field_script_transport' in book['runtime_revision']:
            _registered(book, changed)
        return {**book, 'field_script_transport': True}
    registration = _registered(book, changed)
    originals = json.loads(book['col']['models'])
    for mid, model in models.items():
        if model != originals[mid] and model['mod'] <= originals[mid]['mod']:
            raise ValueError('field-script protection requires a committed newer native model version')
    if alias in runtime['generated'] and runtime['generated'][alias] != resource or alias in runtime['sources']:
        raise ValueError('field-script recovery media alias collision')
    runtime['generated'][alias] = resource
    return {**book, 'models': models, 'runtime': runtime,
            'field_script_transport': {'schema': SCHEMA, 'runtime_alias': alias, **source_pins(),
                                       'models': sorted(changed), 'registration': registration}}
