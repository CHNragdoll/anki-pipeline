from pathlib import Path
import subprocess,time,json,os,signal
D=Path(__file__).parent
assert not (D/'STARTED.json').exists(), 'one maximum application only'
started=time.monotonic();log=(D/'large.log').open('xb')
p=subprocess.Popen(['/opt/homebrew/bin/node','--expose-gc',str(D/'apply-large.cjs')],stdout=log,stderr=subprocess.STDOUT)
(D/'STARTED.json').write_text(json.dumps({'pid':p.pid,'parent':os.getpid(),'max_seconds':180,'rss_limit_bytes':1536*1024*1024},indent=2)+'\n')
print(json.dumps({'pid':p.pid,'parent':os.getpid(),'stage':str(D)}),flush=True);peak=0;reason=None
while p.poll() is None:
 try:rss=int(subprocess.check_output(['/bin/ps','-o','rss=','-p',str(p.pid)],text=True).strip())*1024
 except (ValueError,subprocess.CalledProcessError):rss=0
 peak=max(peak,rss)
 if rss>1536*1024*1024:reason='RSS limit exceeded'
 if time.monotonic()-started>180:reason='180s deadline exceeded'
 if reason:
  p.terminate()
  try:p.wait(timeout=5)
  except subprocess.TimeoutExpired:p.kill();p.wait()
  break
 time.sleep(0.5)
log.close();r={'pid':p.pid,'returncode':p.poll(),'stop_reason':reason,'peak_observed_rss':peak,'elapsed_s':time.monotonic()-started,'single_run':True,'child_exited':p.poll() is not None};(D/'ENDED.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
raise SystemExit(0 if p.returncode==0 and not reason else 1)
