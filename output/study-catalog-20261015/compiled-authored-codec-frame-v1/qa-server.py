from __future__ import annotations
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hashlib,json,mimetypes,os,re,signal,threading,time
from urllib.parse import urlsplit,unquote
STAGE=Path(__file__).resolve().parent
H=lambda b:hashlib.sha256(b).hexdigest()
manifest=json.loads((STAGE/'manifest.json').read_bytes());routes=json.loads((STAGE/'routes.json').read_bytes())
routes={('book/'+key if key.endswith('-frame.html') else key):value for key,value in routes.items()}
for name in ['baseline','candidate']:routes[name]='parent.html'
routes['manifest.json']='manifest.json'
local={}
for route,name in routes.items():
 path=STAGE/name;raw=path.read_bytes();local[route]={'path':str(path),'resolved':str(path.resolve()),'sha256':H(raw),'bytes':len(raw),'purpose':'isolated-QA'}
allowed={row['route']:row for row in manifest['mapped']};allowed.update(local)
stop=threading.Event();ledger=[];lock=threading.Lock()
class Handler(BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 def log_message(self,*args):pass
 def do_HEAD(self):self.serve(False)
 def do_GET(self):self.serve(True)
 def serve(self,body):
  if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:self.send_error(403);return
  parsed=urlsplit(self.path);route=unquote(parsed.path).removeprefix('/')
  if parsed.query or '\\' in route or any(x in {'.','..'} for x in route.split('/')) or route not in allowed:self.send_error(404);return
  row=allowed[route];path=Path(row['path'])
  try:
   if str(path.resolve())!=row['resolved']:raise ValueError('source alias changed')
   raw=path.read_bytes()
   if len(raw)!=row['bytes'] or H(raw)!=row['sha256']:raise ValueError('pinned resource changed')
  except Exception:self.send_error(409,'Pinned QA resource changed');return
  length=len(raw);start,end,status=0,max(0,length-1),200;range_header=self.headers.get('Range')
  if range_header:
   match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
   if not match or not any(match.groups()):self.send_error(416);return
   left,right=match.groups()
   if left:start=int(left);end=int(right) if right else length-1
   else:start=max(0,length-int(right));end=length-1
   if start>=length or end<start:self.send_error(416);return
   end=min(end,length-1);status=206
  payload=raw[start:end+1] if length else b'';kind=mimetypes.guess_type(route)[0] or ('text/html' if route in {'baseline','candidate'} else 'application/octet-stream')
  self.send_response(status);self.send_header('Content-Type',kind+('; charset=utf-8' if kind.startswith('text/') or kind=='application/json' else ''));self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('Accept-Ranges','bytes');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
  if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{length}')
  self.end_headers()
  with lock:ledger.append({'at':time.time(),'method':self.command,'route':route,'status':status,'bytes':len(payload),'sha256':row['sha256']})
  if body:
   try:self.wfile.write(payload)
   except (BrokenPipeError,ConnectionResetError):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=False;server.block_on_close=True;server.timeout=.5
port=server.server_port;manifest['server']={'pid':os.getpid(),'host':'127.0.0.1','port':port,'script_sha256':H(Path(__file__).read_bytes()),'started':time.time(),'close':'SIGINT/SIGTERM to this exact process; private script flag-only shutdown and request drain','urls':{x:f'http://127.0.0.1:{port}/{x}' for x in ['baseline','candidate']}}
manifest['local']=[{'route':k,**v} for k,v in local.items() if k!='manifest.json'];(STAGE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');raw=(STAGE/'manifest.json').read_bytes();allowed['manifest.json']={'path':str(STAGE/'manifest.json'),'resolved':str((STAGE/'manifest.json').resolve()),'sha256':H(raw),'bytes':len(raw),'purpose':'server-manifest'}
for signum in [signal.SIGINT,signal.SIGTERM]:signal.signal(signum,lambda *_:stop.set())
print(json.dumps({'status':'ready','stage':str(STAGE),'manifest_sha256':H(raw),**manifest['server']}),flush=True)
try:
 while not stop.is_set():server.handle_request()
finally:
 server.server_close();(STAGE/'requests.json').write_text(json.dumps(ledger,indent=2)+'\n');print(json.dumps({'status':'closed','requests':len(ledger)}),flush=True)
