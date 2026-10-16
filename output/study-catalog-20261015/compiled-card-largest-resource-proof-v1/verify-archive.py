#!/usr/bin/env python3
"""Read-only compact evidence and3-edit string reconstruction check."""
from pathlib import Path
import argparse,base64,hashlib,json
def digest(path):
    h=hashlib.sha256();n=0
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b);n+=len(b)
    return n,h.hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--external',action='store_true');a=p.parse_args();root=Path(__file__).resolve().parent;repo=root.parents[2];m=json.loads((root/'archive-manifest.json').read_text());counts={'local':0,'encoded':0,'reused':0,'external':0}
    for r in m['copied_original_files']+m['generated_files']:
        path=root/r['repository_path']
        if digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'SHA/size mismatch: {path}')
        counts['local']+=1
    for r in m.get('encoded_original_files',[]):
        stored=r['stored_as'];path=root/stored['repository_path']
        if r['encoding']!='base64' or digest(path)!=(stored['bytes'],stored['sha256']):raise SystemExit(f'Encoded SHA/size mismatch: {path}')
        encoded=path.read_bytes()
        if not encoded.endswith(b'\n'):raise SystemExit(f'Encoded evidence missing final newline: {path}')
        decoded=base64.b64decode(encoded[:-1],validate=True)
        if (len(decoded),hashlib.sha256(decoded).hexdigest())!=(r['bytes'],r['sha256']):raise SystemExit(f'Decoded original SHA/size mismatch: {path}')
        counts['encoded']+=1
    for r in m['reused_repository_evidence']:
        path=repo/r['repository_path']
        if digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'Reused SHA/size mismatch: {path}')
        counts['reused']+=1
    d=m['derived_frame'];base=(repo/d['base_repository_path']).read_text();assert hashlib.sha256(base.encode()).hexdigest()==d['base_sha256'];text=base;edits=json.loads((root/d['edits_repository_path']).read_text())
    for before,after in edits:
        assert text.count(before)==1; text=text.replace(before,after,1)
    assert hashlib.sha256(text.encode()).hexdigest()==d['candidate_sha256']
    for before,after in reversed(edits):
        assert text.count(after)==1; text=text.replace(after,before,1)
    assert text==base
    if a.external:
        for r in m['external_evidence_not_copied']:
            path=Path(r['source_path'])
            if not path.is_file() or digest(path)!=(r['bytes'],r['sha256']):raise SystemExit(f'External absent/changed: {path}')
            counts['external']+=1
    print(json.dumps({'checked':counts,'three_edit_reconstruction_and_inverse':True,'status':m['status'],'whole_card_speedup_proved':False}))
if __name__=='__main__':main()
