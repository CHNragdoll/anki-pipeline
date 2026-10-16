#!/usr/bin/env python3
"""Read-only compact-archive SHA/size verification."""
from pathlib import Path
import argparse,hashlib,json
def digest(path):
    h=hashlib.sha256(); n=0
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b);n+=len(b)
    return n,h.hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--external',action='store_true');a=p.parse_args();root=Path(__file__).resolve().parent;repo=root.parents[2];m=json.loads((root/'archive-manifest.json').read_text());counts={'local':0,'reused':0,'external':0}
    for r in m['copied_original_files']+m['generated_files']:
        path=root/r['repository_path']
        if digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'SHA/size mismatch: {path}')
        counts['local']+=1
    for r in m['reused_repository_evidence']:
        path=repo/r['repository_path']
        if digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'Reused SHA/size mismatch: {path}')
        counts['reused']+=1
    if a.external:
        for r in m['external_evidence_not_copied']:
            path=Path(r['source_path'])
            if not path.is_file() or digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'External evidence absent or changed: {path}')
            counts['external']+=1
    print(json.dumps({'checked':counts,'status':m['status'],'stable_net_speedup_proved':False}))
if __name__=='__main__':main()
