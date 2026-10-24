from pathlib import Path
import hashlib,json
from unittest.mock import patch
from tests.test_study_compiled_build import CompiledBuildTests
from anki_pipeline import study_compiled_build as b
out=[]
for scenario in ['stage_replaced','cache_resources']:
    fixture=CompiledBuildTests();fixture.setUp()
    try:
        root,wrapper,artifact=fixture.source()
        prepared=json.loads((root/'card.json').read_bytes());prepared['modules']={'proof':'not executed'}
        raw=json.dumps(prepared).encode();(root/'card.json').write_bytes(raw);artifact['sha256']=hashlib.sha256(raw).hexdigest()
        with b.CompiledBuild(fixture.root/'build') as ctx:
            def publish(*args):
                stage=args[4]
                if scenario=='stage_replaced':
                    (stage/'own.txt').write_text('owned')
                    saved=stage.with_name(stage.name+'-owned');stage.rename(saved);stage.mkdir()
                    (stage/'foreign.txt').write_text('foreign')
                    out.append({'scenario':scenario,'stage':str(stage),'saved':str(saved)})
                    return {'mode':'compiled'}
                html=ctx.store.put(b'<p>complete</p>','html');profile=ctx.store.put(b'{}','json')
                css=ctx.store.put(b'body{color:blue}','css');evidence=ctx.store.put(b'{"proof":true}','json')
                record=ctx.store.put(json.dumps({'evidence':{'source':evidence}}).encode(),'json')
                return {'mode':'compiled','entry':{'html':html,'profile':profile},'runtime':ctx.runtime,
                        'resources':{'https://study.invalid/style.css':ctx.store.descriptor(css)},'record':record}
            def run(*args):return ({'path':'unused','sha256':'a'*64},{})
            request={'request':{'path':'unused','sha256':'a'*64}}
            kw={'identity':'book:note','policy':{},'source_url':'https://study.invalid/book/index.html'}
            with patch.object(b.inputs,'build_semantic_request',return_value=request),patch.object(b.inputs,'build_profile_request',return_value=request),patch.object(ctx,'_run',side_effect=run),patch.object(ctx,'_publish',side_effect=publish):
                if scenario=='stage_replaced':
                    try:ctx.build(root,wrapper,artifact,**kw)
                    except ValueError as e: error=str(e)
                    else:raise AssertionError('foreign scratch replacement returned success')
                    item=out[-1];stage=Path(item['stage']);saved=Path(item['saved'])
                    assert (stage/'foreign.txt').read_text()=='foreign'
                    assert not (stage/'FAILED.json').exists()
                    assert (saved/'own.txt').read_text()=='owned' and (saved/'FAILED.json').exists()
                    assert ctx.cache=={}
                    out[-1]={'scenario':scenario,'error':error,'foreign_preserved':True,'failure_written_only_to_held_own_directory':True,'cache_empty':True}
                else:
                    result=ctx.build(root,wrapper,artifact,**kw)
                    resource=next(iter(result['resources'].values()));css=Path(resource['path']);original=css.read_bytes()
                    css.write_bytes(b'foreign CSS')
                    try:ctx.build(root,wrapper,artifact,**kw)
                    except ValueError as e:css_error=str(e)
                    else:raise AssertionError('corrupt CSS cache returned success')
                    css.write_bytes(original)
                    record=json.loads((ctx.store.assets/result['record']['src']).read_bytes())
                    evidence=ctx.store.assets/record['evidence']['source']['src'];evidence.write_bytes(b'foreign proof')
                    try:ctx.build(root,wrapper,artifact,**kw)
                    except ValueError as e:evidence_error=str(e)
                    else:raise AssertionError('corrupt evidence cache returned success')
                    out.append({'scenario':scenario,'resource_rejected':css_error,'evidence_rejected':evidence_error})
    finally:fixture.doCleanups()
print(json.dumps({'passed':len(out),'producer_executed':False,'results':out},ensure_ascii=False,indent=2))
