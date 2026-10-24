from pathlib import Path
import hashlib,json,os,resource,signal,subprocess,sys,time,threading
D=Path(__file__).resolve().parent
expected=sys.argv[1] if len(sys.argv)==2 else ''
raw=(D/'FROZEN.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==expected,'Caller must supply exact external seal SHA'
seal=json.loads(raw)
for row in seal['files']:
 p=D/row['path'];assert p.parent==D and not p.is_symlink();b=p.read_bytes();assert len(b)==row['bytes'] and hashlib.sha256(b).hexdigest()==row['sha256'],row['path']
# An exclusive receipt consumes this stage's one attempt, including any failure.
started=D/'RUNNING.json';started.open('x').close()
input=json.loads((D/'inputs.json').read_bytes());node='/opt/homebrew/bin/node';argv=[node,'--max-old-space-size=2048',str(D/'worker.cjs'),expected];began=time.monotonic();peak=0;samples=0;timed_out=False
with (D/'stdout.log').open('xb') as stdout,(D/'stderr.log').open('xb') as stderr:
 child=subprocess.Popen(argv,cwd=D,env={**os.environ,'NODE_PATH':str(Path(input['root'])/'node_modules')},stdout=stdout,stderr=stderr)
 receipt={'schema':'study-largest-codec-once-running.v1','pid':child.pid,'argv':argv,'stage':str(D),'external_seal_sha256':expected,'wall_seconds':120,'attempt':1,'started_unix':time.time()};started.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)
 done=threading.Event();stats={'peak':0,'samples':0}
 def sample_rss():
  while not done.wait(.25):
   try:
    sample=subprocess.run(['/bin/ps','-p',str(child.pid),'-o','rss='],capture_output=True,text=True,check=False,timeout=1)
    if sample.returncode==0 and sample.stdout.strip():stats['peak']=max(stats['peak'],int(sample.stdout.strip())*1024);stats['samples']+=1
   except (subprocess.TimeoutExpired,ValueError):pass
 monitor=threading.Thread(target=sample_rss,name='owned-node-rss',daemon=True);monitor.start()
 try:
  status=child.wait(timeout=120)
 except subprocess.TimeoutExpired:
  timed_out=True;child.kill();status=child.wait()
 except BaseException:
  child.kill();child.wait();raise
 finally:
  done.set();monitor.join(timeout=2)
 peak=stats['peak'];samples=stats['samples']
ru=resource.getrusage(resource.RUSAGE_CHILDREN)
result={**receipt,'exit_code':status if status>=0 else None,'signal':-status if status<0 else None,'timed_out':timed_out,'elapsed_seconds':time.monotonic()-began,'sampled_peak_rss_bytes':peak,'rss_samples':samples,'process_children_ru_maxrss_bytes_macos':ru.ru_maxrss,'ru_scope':'controller direct children including small ps probes; sampled_peak is exact owned Node PID samples','restarted':False,'completed_unix':time.time()};(D/'RUN-ENDED.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True);sys.exit(0 if status==0 and not timed_out else 1)
