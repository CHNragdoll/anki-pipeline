#!/usr/bin/env python3
"""Replay only the frozen44KB/17KB small DOM contracts in an owned temp dir."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,tempfile
from reconstruct import reconstruct,source


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node',default='node')
    parser.add_argument('--jsdom',type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parent;repo=root.parents[2]
    jsdom=(args.jsdom or repo/'node_modules/jsdom').resolve(strict=True)
    values=reconstruct(root)
    with tempfile.TemporaryDirectory(prefix='study-frozen-profile-small-') as name:
        folder=Path(name)
        for filename in ['input-runtime.js','fixture-input.html','fixture-profile.json',
                         'runtime-adapter.js','load-harness.cjs','contracts.cjs','link-contract.cjs']:
            raw=source(root,filename)
            if filename=='contracts.cjs':
                before=b"require('/Users/apple/Documents/PyCharm/Anki/anki_rebuild/node_modules/jsdom')"
                after=b'require(process.env.STUDY_ARCHIVE_JSDOM)'
                assert raw.count(before)==1
                portable=raw.replace(before,after,1)
                assert portable.replace(after,before,1)==raw
                raw=portable
            (folder/filename).write_bytes(raw)
        (folder/'candidate-frame.js').write_bytes(values['candidate-frame.js'])
        env=dict(os.environ,STUDY_ARCHIVE_JSDOM=str(jsdom))
        for script in ['contracts.cjs','link-contract.cjs']:
            result=subprocess.run([args.node,str(folder/script)],cwd=folder,env=env,capture_output=True,text=True)
            print(result.stdout,end='')
            if result.returncode:raise SystemExit(result.stderr or result.returncode)
        assert (folder/'adapted-runtime.js').read_bytes()==values['adapted-runtime.js']
        assert (folder/'runtime-adapter-edits.json').read_bytes()==source(root,'runtime-adapter-edits.json')
    print(json.dumps({'small_contract_groups':7,'exact_archived_candidate':True,
      'portability_only':'one frozen absolute jsdom require replaced in temporary copy, exact inverse verified',
      'no_large_DOM_or_browser_or_service_or_PG_or_APKG':True,'temporary_jobs_finished':True}))


if __name__=='__main__':main()
