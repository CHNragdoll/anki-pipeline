from pathlib import Path
import subprocess,time,json,signal,os
D=Path(__file__).parent
start=time.monotonic()
with (D/'run.log').open('wb') as log:
 p=subprocess.Popen(['/opt/homebrew/bin/node','--max-old-space-size=1536',str(D/'run.cjs')],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 (D/'pid.json').write_text(json.dumps({'nodePid':p.pid,'supervisorPid':os.getpid(),'startEpoch':time.time(),'timeoutSeconds':180})+'\n')
 print(json.dumps({'stage':str(D),'nodePid':p.pid,'supervisorPid':os.getpid(),'timeoutSeconds':180}),flush=True)
 timeout=False
 try: code=p.wait(timeout=180)
 except subprocess.TimeoutExpired:
  timeout=True
  os.killpg(p.pid,signal.SIGTERM)
  try:code=p.wait(timeout=5)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL)
   code=p.wait()
 result={'exitCode':code,'timedOut':timeout,'elapsedSeconds':time.monotonic()-start,'terminal':True}
 (D/'process-result.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(result),flush=True)
