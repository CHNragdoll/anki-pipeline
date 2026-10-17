"""Exact small-string reconstruction only; no DOM, network or deployment."""
from pathlib import Path
import base64,hashlib,json


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(path, spec):
    raw=path.read_bytes()
    assert (len(raw),sha(raw))==(spec['bytes'],spec['sha256']),str(path)
    return raw


def source(root, name):
    m=json.loads((root/'archive-manifest.json').read_bytes())
    item=m['source_inputs'][name]
    assert item['storage'] in {'local','base64'}
    raw=pinned(root/item['stored_path'],item['stored'])
    if item['storage']=='base64':
        assert raw.endswith(b'\n')
        raw=base64.b64decode(raw[:-1],validate=True)
    assert (len(raw),sha(raw))==(item['bytes'],item['sha256'])
    return raw


def apply(text, edits):
    for before,after in edits:
        assert text.count(before)==1
        text=text.replace(before,after,1)
    return text


def undo(text, edits):
    for before,after in reversed(edits):
        assert text.count(after)==1
        text=text.replace(after,before,1)
    return text


def reconstruct(root=None):
    root=Path(root or __file__).resolve()
    if root.is_file():root=root.parent
    repo=root.parents[2]
    m=json.loads((root/'archive-manifest.json').read_bytes())
    deps={key:pinned(repo/spec['repository_path'],spec) for key,spec in m['reused_inputs'].items()}
    layout=deps['layout_frame'].decode()
    resource_edits=json.loads(deps['resource_edits'])
    resource=apply(layout,resource_edits)
    assert undo(resource,resource_edits)==layout
    edits=json.loads(source(root,'edits.json'))
    candidate=apply(resource,edits)
    assert undo(candidate,edits)==resource
    phase=deps['phase_frame'].decode();shell=deps['phase_html'].decode()
    assert shell.count(phase)==1
    basehtml=shell.replace(phase,resource,1)
    candidatehtml=basehtml.replace(resource,candidate,1)
    assert candidatehtml.replace(candidate,resource,1)==basehtml
    encode=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<',r'\u003c').encode()
    phasecfg=deps['phase_config'];assert phasecfg.count(encode(shell))==1
    basecfg=phasecfg.replace(encode(shell),encode(basehtml),1)
    candidatecfg=basecfg.replace(encode(basehtml),encode(candidatehtml),1)
    assert candidatecfg.replace(encode(candidatehtml),encode(basehtml),1)==basecfg
    phaseqa=deps['phase_parent'];phaseblock=deps['phase_clock'];baseblock=deps['resource_clock'];newblock=pinned(root/'qa/clock-block.html',m['local_files']['qa/clock-block.html'])
    assert phaseqa.count(phasecfg)==1 and phaseqa.count(phaseblock)==1
    baseqa=phaseqa.replace(phasecfg,basecfg,1).replace(phaseblock,baseblock,1)
    newqa=baseqa.replace(basecfg,candidatecfg,1).replace(baseblock,newblock,1)
    assert newqa.replace(newblock,baseblock,1).replace(candidatecfg,basecfg,1)==baseqa
    runtime=source(root,'input-runtime.js').decode();runtimeedits=json.loads(source(root,'runtime-adapter-edits.json'))
    adapted=apply(runtime,runtimeedits);assert undo(adapted,runtimeedits)==runtime
    values={'baseline-frame.js':resource.encode(),'baseline-frame.html':basehtml.encode(),
            'candidate-frame.js':candidate.encode(),'candidate-frame.html':candidatehtml.encode(),
            'adapted-runtime.js':adapted.encode(),'baseline-parent.html':baseqa,
            'qa-config.literal':candidatecfg,m['candidate_QA_filename']:newqa}
    for key,spec in m['derived_outputs'].items():
        raw=values[key];assert (len(raw),sha(raw))==(spec['bytes'],spec['sha256']),key
    return values


if __name__=='__main__':
    values=reconstruct()
    print(json.dumps({'reconstructed':{name:{'bytes':len(raw),'sha256':sha(raw)} for name,raw in values.items()},
                      'frame_5_edits_and_runtime_2_edits_and_parent_inverse_exact':True,
                      'large_assets_read_or_copied':False,'DOM_or_browser_executed':False},indent=2))
