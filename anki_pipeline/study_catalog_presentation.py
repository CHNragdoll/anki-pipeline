"""Shared presentation revisions; native model IDs are book mapping data.

The registry stores references to common exact template/runtime components.
Original model/ZIP bytes remain immutable. Both output hosts resolve the same
current references, without a renderer branch for a title or edition year.
"""
from __future__ import annotations

import copy
import json
import re
from urllib.parse import unquote

from . import study_catalog as c

REGISTRY = 'presentation.registry.v1'

_RESOURCE_TOKEN=re.compile(r'(?<![\w./:@%+-])(?:\./)?([\w@%+~.-]+\.(?:js|css))(?=$|[^\w./:@%+-])',re.I)
_QUOTED_RESOURCE=re.compile(r'(["\'`])([^"\'`\r\n]+)\1')


def _reference_spans(text,names):
    """Locate exact local basenames, including URL-encoded and quoted names.

    Token boundaries avoid rewriting ``data.js`` when the registered name is
    ``a.js``, or replacing a basename inside a remote URL or directory path.
    """
    found={}
    for match in _RESOURCE_TOKEN.finditer(text):
        raw=match[1];name=raw if raw in names else unquote(raw)
        if name in names:found[match.span(1)]=name
    for match in _QUOTED_RESOURCE.finditer(text):
        raw=match[2];prefix=2 if raw.startswith('./') else 0;raw=raw[prefix:]
        name=raw if raw in names else unquote(raw)
        if name in names:found[(match.start(2)+prefix,match.end(2))]=name
    spans=[]
    for start,end,name in sorted(((start,end,name) for (start,end),name in found.items()),key=lambda span:(span[0],-span[1])):
        if spans and start<spans[-1][1]:continue
        spans.append((start,end,name))
    return spans


def rewrite_references(text,aliases):
    if not aliases:return text
    spans=_reference_spans(text,aliases)
    for start,end,name in reversed(spans):text=text[:start]+aliases[name]+text[end:]
    return text


def _dynamic_reference(text):
    if re.search(r'\bdocument\s*\.\s*currentScript\b|\bimport\s*\.\s*meta\s*\.\s*url\b',text):return True
    for match in _QUOTED_RESOURCE.finditer(text):
        if re.search(r'\\[ux]',match[2]) and re.search(r'\.(?:js|css)(?:[?#].*)?$',match[2],re.I):return True
    if re.search(r'''["'][^"'\n]*\.(?:js|css)["']\s*\+|\+\s*["'][^"'\n]*\.(?:js|css)["']|`[^`]*\$\{[^`]*\.(?:js|css)[^`]*`''',text,re.I):
        return True
    for match in re.finditer(r'\.\s*(?:src|href)\s*=\s*([^;\n]+)',text):
        value=match[1].strip()
        if not value.startswith(('"',"'",'`')) or '${' in value:return True
    literal=re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`[^`$]*`''')
    for match in re.finditer(r'\b(?:import|require|importScripts)\s*\(([^;\n]+?)\)',text):
        if literal.sub('',match[1]).strip(' \t,'):return True
    for match in re.finditer(r'@import\s+([^;\r\n]+)',text,re.I):
        value=match[1].strip()
        if not value.startswith(('"',"'")) and not re.match(r'''url\(\s*(?:["'][^"']+["']|[^\s()"']+)\s*\)''',value,re.I):return True
    return False



def _inert_registration(name, text):
    """Recognize unchanged codec data, never arbitrary executable resources."""
    from hashlib import sha256
    match = re.fullmatch(r'window\.(AnkiSlimAssets|AnkiFinalHistoryEvidence)=window\.\1\|\|\{\};window\.\1\["([a-f0-9]{64})"\]=(.*);', text, re.S)
    if not match:
        return False
    registry, pin, payload = match.groups()
    names = ({prefix + pin[:24] + '.js' for prefix in ('_ac_', '_as_')}
             if registry == 'AnkiSlimAssets' else {'_af_' + sha256(text.encode()).hexdigest()[:24] + '.js'})
    if name not in names:
        return False
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return False
    if isinstance(value, str):
        return sha256(value.encode()).hexdigest() == pin
    if registry != 'AnkiSlimAssets' or type(value) is not dict or set(value) != {'schema', 'dict', 'pieces'}:
        return False
    bank, pieces = value['dict'], value['pieces']
    return (value['schema'] == 'anki-slim-shared-strings.v1' and type(bank) is dict
            and set(bank) in ({'src', 'sha256'}, {'src', 'sha256', 'literal'})
            and ('literal' not in bank or bank['literal'] is True)
            and type(bank.get('sha256')) is str and re.fullmatch('[a-f0-9]{64}', bank['sha256']) is not None
            and bank.get('src') == '_as_' + bank['sha256'][:24] + '.js'
            and type(pieces) is list and all(type(piece) is str or type(piece) is int and 0 <= piece < 2**53 for piece in pieces))

def _runtime_projection(db,book_id,binding):
    originals=dict(db.execute('select name,object_id from resource_aliases where book_id=%s',(book_id,)))
    references=binding.get('resources',{})
    rows=dict(db.execute('select id,current_id from components where id=ANY(%s)',(list(set(references.values())),))) if references else {}
    if set(rows)!=set(references.values()):raise ValueError('missing shared runtime component')
    current={name:rows[component] for name,component in references.items()}
    changed={name for name,key in current.items() if originals.get(name)!=key}
    result={'sources':{name:originals[name] for name in current},'aliases':{},'generated':{}}
    if not changed:return result
    texts={name:c.get_object(db,key).decode('utf-8') for name,key in current.items()}
    reverse={name:set() for name in texts}
    inert=set();preserved=set()
    from .study_native_examples_complete import preserved_legacy_runtime
    for name,text in texts.items():
        dynamic=_dynamic_reference(text)
        if dynamic and name not in changed and _inert_registration(name, text):
            inert.add(name)
        elif dynamic and name not in changed and preserved_legacy_runtime(name, text):
            preserved.add(name)
        elif dynamic:
            # Explicit source-bound loader revision. All other dynamic changes
            # still fail closed; no wildcard URL/dependency admission is added.
            from .study_native_examples_complete import validate_completion_runtime
            try:
                validate_completion_runtime(c.get_object(db, originals[name]).decode('utf-8'), text)
            except ValueError as error:
                raise ValueError('dynamic shared runtime reference requires an explicit dependency declaration: '+name) from error
        for _,_,dependency in _reference_spans(text,texts):reverse[dependency].add(name)
    affected=set(changed);pending=list(changed)
    while pending:
        for parent in reverse[pending.pop()]-affected:affected.add(parent);pending.append(parent)
    if affected & inert:
        raise ValueError('inert registration cannot enter runtime rewrite closure')
    if affected & preserved:
        raise ValueError('preserved legacy runtime cannot enter rewrite closure')
    revision=c.identity('runtime-dependency-closure.v1',[(name,current[name]) for name in sorted(affected)])
    aliases={name:'_study_runtime_'+c.identity(revision,name)+'.'+name.rsplit('.',1)[-1] for name in affected}
    for name,alias in aliases.items():
        raw=rewrite_references(texts[name],aliases).encode('utf-8')
        if alias in originals and c.get_object(db,originals[alias])!=raw:
            raise ValueError('versioned runtime alias conflicts with an original resource')
        result['generated'][alias]=raw
    result['aliases']=aliases
    return result


def registry(db):
    row = db.execute('select value from metadata where key=%s', (REGISTRY,)).fetchone()
    return c.get_json(db, row[0]) if row else {'schema': REGISTRY, 'books': {}}


def register_book(db, book_id, col):
    """Append an idempotent binding. Existing revisions are never reset."""
    from .study_catalog_anki import initialize_model_mods

    c.write_lock(db)
    db.execute('select pg_advisory_xact_lock(%s)', (int(c.identity(REGISTRY)[:15], 16),))
    data = registry(db)
    if book_id in data['books']:
        binding = data['books'][book_id]
        initialize_model_mods(db, book_id, binding)
        return binding
    models = {}
    for mid, model in json.loads(col['models']).items():
        parts = {'css': c.ensure_component(db, None, 'template:css', model['css'], scope='presentation')}
        for ordinal, template in enumerate(model['tmpls']):
            for side in ('qfmt', 'afmt'):
                name = f'template:{side}:{ordinal}'
                parts[f'{side}:{ordinal}'] = c.ensure_component(db, None, name, template[side], scope='presentation')
        models[mid] = parts
    resources = {}
    for name, key in db.execute('select name,object_id from resource_aliases where book_id=%s', (book_id,)):
        suffix = name.rsplit('.', 1)[-1].lower()
        if suffix not in {'js', 'css'}:
            continue
        text = c.get_object(db, key).decode('utf-8')
        resources[name] = c.ensure_component(db, None, 'runtime:' + suffix, text, scope='presentation')
    binding = {'models': models, 'resources': resources}
    data['books'][book_id] = binding
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (REGISTRY, c.put_json(db, data)))
    initialize_model_mods(db, book_id, binding)
    c.event(db, 'register-shared-presentation', {'book_id': book_id, 'models': len(models), 'resources': len(resources)})
    return binding


def install(value):
    from .study_catalog_export import require_ready
    with c.connect(value) as db, c.transaction(db):
        require_ready(db)
        for book_id, col_id in db.execute('select book_id,col_payload_id from book_sources order by book_id'):
            register_book(db, book_id, c.get_json(db, col_id))
    return {'schema': REGISTRY, 'installed': True}


def project(db, book_id, original):
    binding = registry(db)['books'].get(book_id, {})
    models = copy.deepcopy(json.loads(original['models']))
    for mid, parts in binding.get('models', {}).items():
        model = models[mid]
        for name, component in parts.items():
            row = db.execute('select current_id from components where id=%s', (component,)).fetchone()
            if row is None:
                raise ValueError('missing shared presentation component')
            text = c.get_object(db, row[0]).decode('utf-8')
            if name == 'css':
                model['css'] = text
            else:
                side, ordinal = name.split(':')
                model['tmpls'][int(ordinal)][side] = text
    resources=_runtime_projection(db,book_id,binding)
    if resources['aliases']:
        for model in models.values():
            if _dynamic_reference(model['css']) or any(_dynamic_reference(t[side]) for t in model['tmpls'] for side in ('qfmt','afmt')):
                raise ValueError('dynamic model runtime reference requires an explicit dependency declaration')
            model['css']=rewrite_references(model['css'],resources['aliases'])
            for template in model['tmpls']:
                for side in ('qfmt','afmt'):
                    template[side]=rewrite_references(template[side],resources['aliases'])
    return models,resources
