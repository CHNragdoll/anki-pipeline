"""Offline math host assets, stored once in PostgreSQL and shared by all books."""
import hashlib
from importlib.resources import files
import json
from pathlib import PurePosixPath

from . import study_catalog as c

KEY='host.mathjax.v1'


def required(fields):return any('\\(' in value or '\\[' in value for value in fields)


def install(db):
    old=db.execute('select value from metadata where key=%s',(KEY,)).fetchone()
    if old:return c.get_json(db,old[0])
    root=files('anki_pipeline').joinpath('web_runtime/mathjax')
    manifest=json.loads(root.joinpath('SOURCE.json').read_text());resources={}
    for name,expected in manifest['files'].items():
        raw=root.joinpath(name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('bundled math runtime differs from pinned source')
        resources[name]=c.put_object(db,raw)
    value={'schema':KEY,'source':manifest,'resources':resources}
    db.execute('insert into metadata values(%s,%s)',(KEY,c.put_json(db,value)))
    c.event(db,'install-web-math-runtime',{'version':manifest['version'],'resources':len(resources)})
    return value


def write_assets(db,media):
    row=db.execute('select value from metadata where key=%s',(KEY,)).fetchone()
    if row is None:raise ValueError('math cards need the common offline math host registered before export')
    registry=c.get_json(db,row[0]);prefix='_study_mathjax'
    for name,key in registry['resources'].items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe math runtime resource')
        target=media/prefix/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as output:c.write_object(db,key,output)
    return prefix+'/tex-chtml-full.js'


def header(href):
    # Anki itself supplies MathJax. This is the web-only host adaptation; both
    # hosts consume the same original TeX in their shared projected fields.
    return ('<script>window.MathJax={tex:{inlineMath:[["\\\\(","\\\\)"]],displayMath:[["\\\\[","\\\\]"]]},'
            'options:{enableMenu:false}};</script><script defer src="'+href+'"></script>')
