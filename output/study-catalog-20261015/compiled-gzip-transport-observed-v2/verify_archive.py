"""Verify only bounded archived evidence, never serve or load large external assets."""
from pathlib import Path
import argparse,json,hashlib,gzip
D=Path(__file__).resolve().parent
H=lambda raw:hashlib.sha256(raw).hexdigest()
parser=argparse.ArgumentParser();parser.add_argument('--extract-candidate',type=Path);args=parser.parse_args()
seal=json.loads((D/'SEAL.json').read_bytes())
for row in seal['files']:
 path=D/row['path'];assert path.is_file() and not path.is_symlink();raw=path.read_bytes();assert len(raw)==row['bytes'] and H(raw)==row['sha256'],row['path']
manifest=json.loads((D/'archive-manifest.json').read_bytes());decoded={}
for row in manifest['stored_source_files']:
 data=(D/row['stored_path']).read_bytes();assert len(data)==row['stored_bytes'] and H(data)==row['stored_sha256']
 raw=gzip.decompress(data) if row['storage']=='gzip' else data
 assert len(raw)==row['raw_bytes'] and H(raw)==row['raw_sha256'],row['logical_path'];decoded[row['logical_path']]=raw
cf=json.loads(decoded['candidate/FROZEN.json']);assert H(decoded['candidate/FROZEN.json'])=='6dd1b9ae8f9af98ee0478104faabd5db3ccbd801788d1425c2dd5271768bca85'
for row in cf['files']:
 raw=decoded['candidate/'+row['path']];assert len(raw)==row['bytes'] and H(raw)==row['sha256']
qf=json.loads(decoded['qa/FROZEN.json'])
for name,row in qf['files'].items():
 raw=decoded['qa/'+name];assert len(raw)==row['bytes'] and H(raw)==row['sha256']
frame=decoded['candidate/candidate-frame.js'].decode();baseline=decoded['candidate/baseline-candidate-frame.js'].decode();edits=json.loads(decoded['candidate/edits.json']);assert len(edits)==6
undo=frame
for before,after in reversed(edits):assert undo.count(after)==1;undo=undo.replace(after,before,1)
assert undo==baseline
before,after=edits[-1];assert frame.replace(after,before,1).encode()==decoded['candidate/pre-fix-candidate-frame.js']
assert decoded['candidate/candidate-frame.html'].decode().replace(frame,baseline,1).encode()==decoded['candidate/baseline-candidate-frame.html']
requests=json.loads(decoded['qa/requests-08451e9c7347.json']);closed=json.loads(decoded['qa/closed-08451e9c7347.json']);assert len(requests)==172 and closed['drained'] and closed['used_sources_unchanged'] and len(closed['used_source_checks'])==54
summary=json.loads((D/'observation-summary.json').read_bytes());assert [r['full_back_elapsed_ms'] for r in summary['runs']]==[4464,8959,6575];assert summary['B_gzip_total_bytes']==8184676 and summary['B_compiled_raw_fallback_requests']==0
if args.extract_candidate:
 out=args.extract_candidate.absolute();assert str(out).startswith('/tmp/') or str(out).startswith('/private/tmp/');assert not out.exists();out.mkdir(mode=0o700)
 for logical,raw in decoded.items():
  if logical.startswith('candidate/'):
   name=logical.removeprefix('candidate/');assert '/' not in name and name not in {'.','..'}
   with (out/name).open('xb') as f:f.write(raw)
print(json.dumps({'passed':True,'stored_source_files':len(decoded),'exact_frame_inverse':True,'exact_html_inverse':True,'large_external_payloads_read':0,'tests_replayed':0,'browser_or_server_started':False,'extracted_candidate':str(args.extract_candidate) if args.extract_candidate else None}))
