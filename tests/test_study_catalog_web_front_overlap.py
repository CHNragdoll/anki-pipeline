"""Complete delivery overlaps front rendering without crossing its acceptance gate."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.test_study_catalog_web_front import front_host_fixture


CONTRACT = r'''
const unhandled=[];
process.on('unhandledRejection',error=>unhandled.push(error.message));
function blockedFront(f){
 const mounts=[];
 f.w.__fixtureApi.mountFront=packet=>new Promise((resolve,reject)=>{
  f.mounted.push({kind:'front',packet});mounts.push({packet,resolve,reject});
 });
 return mounts;
}
async function overlapsWithoutEarlyAttach(){
 const f=setup(),mounts=blockedFront(f);
 try{
  await until(()=>mounts.length===1,'front rendering did not start');
  await until(()=>f.gates.length===1,'full delivery must start while mountFront is still blocked');
  assert.equal(f.gates[0].path,'cards/A.html');
  assert.ok(f.calls.some(call=>call.path==='full-A.json'),'prepared full artifact must overlap the front');
  f.gates[0].resolve();await tick();await tick();
  assert.equal(f.attached.length,0,'complete data crossed the unaccepted front gate');
  mounts[0].resolve(true);
  await until(()=>f.attached.length===1,'complete card did not attach after front acceptance');
  assert.equal(f.attached[0].token,mounts[0].packet.token);
  assert.equal(f.attached[0].id,'A');
  assert.deepEqual(f.attached[0].deliveryBinding,mounts[0].packet.deliveryBinding);
  assert.equal(f.errors.length,0,f.errors.join('\n'));
 }finally{f.close()}
}
async function rejectedFullIsObservedWhileFrontIsBlocked(){
 const files=clone(input.files);files['full-A.json']+='changed';
 const f=setup({files}),mounts=blockedFront(f);
 try{
  await until(()=>mounts.length===1&&f.gates.length===1,'full error fixture never overlapped');
  f.gates[0].resolve();await tick();await tick();
  assert.equal(f.attached.length,0);assert.equal(unhandled.length,0,'early full rejection was unobserved');
  mounts[0].resolve(true);
  await until(()=>f.w.document.getElementById('frame').dataset.mountMode==='original-wrapper-fallback','full SHA error did not retain fallback');
  assert.equal(f.gates[0].signal.aborted,true);assert.equal(f.attached.length,0);
 }finally{f.close()}
}
async function rejectedFrontAbortsItsOverlappedFull(){
 const f=setup(),mounts=blockedFront(f);
 try{
  await until(()=>mounts.length===1&&f.gates.length===1,'front failure fixture never overlapped');
  mounts[0].reject(Error('front rendering failed'));
  await until(()=>f.w.document.getElementById('frame').dataset.mountMode==='original-wrapper-fallback','front failure did not retain fallback');
  assert.equal(f.gates[0].signal.aborted,true,'fallback left its complete delivery running');
  f.gates[0].resolve();await tick();assert.equal(f.attached.length,0);
 }finally{f.close()}
}
async function cancelledABAOnlyAttachesTheAcceptedCurrentFront(){
 const f=setup(),mounts=blockedFront(f);
 try{
  await until(()=>mounts.length===1&&f.gates.length===1,'first A did not overlap');
  f.w.document.getElementById('next-card').click();
  await until(()=>mounts.length===2&&f.gates.length===2,'B did not overlap');
  assert.equal(f.gates[0].signal.aborted,true);
  f.w.document.getElementById('previous-card').click();
  await until(()=>mounts.length===3&&f.gates.length===3,'current A did not overlap');
  assert.equal(f.gates[1].signal.aborted,true);
  for(let i=0;i<2;i++){mounts[i].resolve(true);f.gates[i].resolve()}
  await tick();assert.equal(f.attached.length,0,'obsolete A/B attached to current A');
  assert.notEqual(f.w.document.getElementById('frame').dataset.mountMode,'original-wrapper-fallback');
  f.gates[2].resolve();await tick();assert.equal(f.attached.length,0,'current A attached before its own front acceptance');
  mounts[2].resolve(true);
  await until(()=>f.attached.length===1,'current accepted A did not attach');
  assert.equal(f.attached[0].token,mounts[2].packet.token);
  assert.ok(mounts[2].packet.token>mounts[0].packet.token);
  assert.equal(f.calls.filter(call=>call.path==='front-A.json').length,1,'existing bounded front cache changed');
  assert.equal(f.gates.length,3,'a whole neighboring card was speculatively fetched');
  assert.equal(f.errors.length,0,f.errors.join('\n'));
 }finally{f.close()}
}
(async()=>{
 await overlapsWithoutEarlyAttach();
 await rejectedFullIsObservedWhileFrontIsBlocked();
 await rejectedFrontAbortsItsOverlappedFull();
 await cancelledABAOnlyAttachesTheAcceptedCurrentFront();
 await tick();assert.deepEqual(unhandled,[],'overlapped delivery leaked a rejection');
 console.log(JSON.stringify({passed:true,scenarios:4}));
})().catch(error=>{console.error(error);process.exit(1)});
'''


@unittest.skipUnless(shutil.which('node'), 'requires JavaScript runtime')
class FrontDeliveryOverlapTests(unittest.TestCase):
    def test_complete_fetch_overlaps_front_mount_without_early_or_stale_attach(self):
        # Reuse the existing real-host fixture. Only its frame API is held; the
        # host's fetch, proofs, cache, cancellation and fallback remain real.
        fixture = (Path(__file__).parent / 'fixtures/study-front-host-contract.cjs').read_text()
        seam = 'async function hostFlow()'
        self.assertEqual(fixture.count(seam), 1)
        code = fixture.split(seam)[0] + CONTRACT
        result = subprocess.run([shutil.which('node'), '-e', code],
                                input=json.dumps(front_host_fixture()), text=True,
                                capture_output=True, timeout=30)
        if "Cannot find module 'jsdom'" in result.stderr:
            self.skipTest('requires existing jsdom dependency')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True, 'scenarios': 4})


if __name__ == '__main__':
    unittest.main()
