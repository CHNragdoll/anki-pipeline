"""Real frozen CLI prepare -> two shards -> index -> common finalize, tiny sources."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys,tempfile,unittest
HERE=Path(__file__).resolve().parent;REPO=HERE.parent;sys.path.insert(0,str(REPO))
from tests import test_study_catalog_web_delivery as delivery_tests

class CLI(unittest.TestCase):
 def test_actual_frozen_workflow_two_books(self):
  frozen=REPO;py=sys.executable
  fixture=delivery_tests.DeliveryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  job_stage=fixture.root/'jobs';job_stage.mkdir();source=job_stage
  members={}
  paths=[p for p in (REPO/'anki_pipeline').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
  paths += [REPO/'scripts'/n for n in ('build_study_complete_web_batch.py','derive_study_complete_web_batch.py','index_study_complete_results.py')]
  for path in paths:
   raw=path.read_bytes();members[str(path.relative_to(REPO))]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
  raw=(json.dumps({'schema':'study-complete-frozen-builder.v1','source_root':str(REPO),'files':members},sort_keys=True,separators=(',',':'))+'\n').encode()
  (job_stage/'SOURCE.json').write_bytes(raw);descriptor={'path':str(job_stage/'SOURCE.json'),'sha256':hashlib.sha256(raw).hexdigest()}
  parent,_=fixture.two_book_fixture();complete=hashlib.sha256((parent/'COMPLETE.json').read_bytes()).hexdigest()
  prepared=fixture.root/'preparation';final=fixture.root/'delivery';index=fixture.root/'cache-index'
  def run(name,*args):
   result=subprocess.run([py,'-B','-W','error::ResourceWarning',str(frozen/'scripts'/name),*map(str,args)],cwd=REPO,capture_output=True,text=True,timeout=30)
   self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   print(json.dumps({'command':name,'tail':result.stdout.splitlines()[-1]},ensure_ascii=False));return json.loads(result.stdout.splitlines()[-1])
  common=['--generator',descriptor['path'],'--generator-sha256',descriptor['sha256'],'--source',parent,'--source-complete-sha256',complete,'--base-url','https://study.test/']
  run('derive_study_complete_web_batch.py','prepare',*common,'--output',prepared)
  self.assertFalse((prepared/'COMPLETE.json').exists())
  for shard in (0,1):
   result=run('build_study_complete_web_batch.py','--stage',source,'--source-sha256',descriptor['sha256'],'--preparation-complete-sha256',hashlib.sha256((prepared/'preparation-authority/COMPLETE.json').read_bytes()).hexdigest(),'--exports',prepared,'--base-url','https://study.test/','--book','arbitrary-subject:web','--book','second-subject:web2','--shard-count',2,'--shard-index',shard,'--node','/not-run/owned-node','--heap-mb',4096)
   self.assertEqual(result['passed'],2);self.assertEqual(result['failed'],0)
  receipt=run('index_study_complete_results.py','--stage',source,'--source-sha256',descriptor['sha256'],'--output',index)
  self.assertEqual(receipt['compiled_identities'],0)
  run('derive_study_complete_web_batch.py','finalize',*common,'--output',final,'--cache-index',receipt['index']['path'],'--cache-index-sha256',receipt['index']['sha256'])
  self.assertTrue((final/'COMPLETE.json').exists())
  self.assertEqual(len(json.loads((final/'manifest.json').read_bytes())['webs']),2)
  from anki_pipeline import study_compiled_preparation as preparation
  from anki_pipeline.study_compiled_build import CompiledBuild
  plan={'schema':'study-compiled-repair-plan.v1','sources':preparation.source_pins(),
        'dependencies':CompiledBuild._dependencies(),'changed':[]}
  planraw=json.dumps(plan).encode();planpath=fixture.root/'approved-repair-plan.json';planpath.write_bytes(planraw)
  repaired=fixture.root/'planned-delivery'
  observed=run('derive_study_complete_web_batch.py','finalize',*common,'--output',repaired,
    '--cache-index',receipt['index']['path'],'--cache-index-sha256',receipt['index']['sha256'],
    '--repair-plan',planpath,'--repair-plan-sha256',hashlib.sha256(planraw).hexdigest())
  self.assertTrue((repaired/'COMPLETE.json').exists())
  self.assertEqual([r['repaired'] for r in observed['repairs']],[0,0])

if __name__=='__main__':unittest.main(verbosity=2)
