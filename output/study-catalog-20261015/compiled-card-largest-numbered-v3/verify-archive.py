#!/usr/bin/env python3
"""Read-only SHA/size checks; no DOM, AST, browser or semantic replay."""
from pathlib import Path
import argparse, hashlib, json

def digest(path):
    h=hashlib.sha256(); size=0
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024), b''):
            h.update(block); size+=len(block)
    return size,h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--external',action='store_true')
    args=parser.parse_args(); root=Path(__file__).resolve().parent
    manifest=json.loads((root/'archive-manifest.json').read_text()); count=0
    for row in manifest['copied_original_files']+manifest['generated_files']:
        path=root/row['repository_path']
        if digest(path)!=(row['bytes'],row['sha256']): raise SystemExit(f'SHA/size mismatch: {path}')
        count+=1
    external=0
    if args.external:
        for row in manifest['external_evidence_not_copied']:
            path=Path(row['source_path'])
            if not path.is_file(): raise SystemExit(f'External evidence absent: {path}')
            if digest(path)!=(row['bytes'],row['sha256']): raise SystemExit(f'External SHA/size mismatch: {path}')
            external+=1
    print(json.dumps({'local_files_checked':count,'external_files_checked':external,'status':manifest['status'],'first_flip_performance_target_met':manifest['acceptance']['performance_target_met']}))

if __name__=='__main__': main()
