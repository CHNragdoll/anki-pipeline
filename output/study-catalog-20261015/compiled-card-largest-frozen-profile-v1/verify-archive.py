#!/usr/bin/env python3
"""Verify exact archival pins and reconstruction without executing card code."""
from pathlib import Path
import argparse,base64,hashlib,json
from reconstruct import reconstruct,source,pinned


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expected-manifest-sha')
    a=p.parse_args();root=Path(__file__).resolve().parent
    raw=(root/'archive-manifest.json').read_bytes()
    if a.expected_manifest_sha:assert hashlib.sha256(raw).hexdigest()==a.expected_manifest_sha
    m=json.loads(raw)
    for name,spec in m['local_files'].items():pinned(root/name,spec)
    for name,item in m['source_inputs'].items():
        if item['storage'] in {'local','base64'}:source(root,name)
    values=reconstruct(root)
    for name,item in m['source_inputs'].items():
        if item['storage']=='derived':
            value=values[item['derived_name']]
            assert (len(value),hashlib.sha256(value).hexdigest())==(item['bytes'],item['sha256'])
    freeze=json.loads((root/'frozen-profile/FROZEN.json').read_bytes())
    assert len(freeze['files'])==24 and {item['path'] for item in freeze['files']}==set(m['source_inputs'])
    for item in freeze['files']:
        archived=m['source_inputs'][item['path']]
        assert (archived['bytes'],archived['sha256'])==(item['bytes'],item['sha256'])
    qseal=json.loads((root/'qa/SEALS.json').read_bytes())
    assert set(qseal['files'])==set(m['qa_inputs'])
    for name,item in m['qa_inputs'].items():
        assert (item['bytes'],item['sha256'])==(qseal['files'][name]['bytes'],qseal['files'][name]['sha256'])
        if item['storage']=='derived':value=values[item['derived_name']]
        elif item['storage']=='source':value=source(root,item['source_name'])
        elif item['storage']=='repository':
            shared=m['reused_inputs'][item['reused_key']]
            value=pinned(root.parents[2]/shared['repository_path'],shared)
        else:
            value=pinned(root/item['stored_path'],item['stored'])
            if item['storage']=='base64':value=base64.b64decode(value[:-1],validate=True)
        assert (len(value),hashlib.sha256(value).hexdigest())==(item['bytes'],item['sha256'])
    report=json.loads((root/'safari-frozen-profile-v1.json').read_bytes())
    assert report['first_front_complete_observed_ms']==1872 and report['first_back_elapsed_ms']==7419
    assert report['status']=='full-back-observed' and report['error'] is None
    run=report['validation_runs'][0];stats=run['compiled_handle_stats'][0]
    assert stats['invalid'] is None and stats['disposed'] is False
    assert (stats['groups'],stats['groupedOccurrences'],stats['bankRecords'])==(1800,4303,201)
    assert run['initial_numbering_claim_status']['accepted'] is True
    assert run['layout_cost_status']['gateResult']=='ready'
    assert any(row['label']=='full-gate-complete' for row in report['phase_clock'])
    print(json.dumps({'local_files':len(m['local_files']),'source_freeze_files':len(m['source_inputs']),
      'QA_source_pins':len(m['qa_inputs']),
      'reused_small_inputs':len(m['reused_inputs']),'derived_outputs':len(values),'raw_SHA_exact':True,
      'complete_back_and_invalid_null_observed':True,'full_card_speedup_proved':False,
      'large_assets_read_or_copied':False,'browser_or_DOM_run':False}))


if __name__=='__main__':main()
