#!/usr/bin/env python3
"""Read-only evidence SHA/size checker; no runtime or browser execution."""
from pathlib import Path
import argparse, hashlib, json

def digest(path):
    h=hashlib.sha256(); size=0
    with path.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):
            h.update(data); size+=len(data)
    return size,h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--external',action='store_true'); args=parser.parse_args()
    root=Path(__file__).resolve().parent; m=json.loads((root/'archive-manifest.json').read_text()); count=0
    for row in m['copied_original_files']+m['generated_files']:
        path=root/row['repository_path']
        if digest(path)!=(row['bytes'],row['sha256']): raise SystemExit(f'SHA/size mismatch: {path}')
        count+=1
    ext=0
    if args.external:
        for row in m['external_assets_not_copied']:
            path=Path(row['source_path'])
            if not path.is_file(): raise SystemExit(f'External evidence absent: {path}')
            if digest(path)!=(row['bytes'],row['sha256']): raise SystemExit(f'External SHA/size mismatch: {path}')
            ext+=1
    print(json.dumps({'local_files_checked':count,'external_files_checked':ext,'status':m['status'],'speedup_proved':False}))

if __name__=='__main__': main()
