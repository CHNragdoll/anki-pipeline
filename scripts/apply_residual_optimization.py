#!/usr/bin/env python3
"""Prepare/dry-run residual decisions; ROOT explicitly applies to a clone."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_pipeline import residual_optimization as writer


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'dry-run', 'apply', 'rollback'))
    parser.add_argument('--request')
    parser.add_argument('--request-sha256')
    parser.add_argument('--output')
    parser.add_argument('--plan')
    parser.add_argument('--plan-sha256')
    parser.add_argument('--root-candidate-write-approved', action='store_true')
    args = parser.parse_args(argv)
    if args.mode in {'prepare', 'dry-run'}:
        if not (args.request and args.request_sha256):
            parser.error('request and request SHA required')
        request = writer.read_json({'file': args.request, 'sha256': args.request_sha256})
        plan = writer.prepare(request)
        if args.mode == 'prepare':
            if not args.output:
                parser.error('fresh owned output directory required')
            result = writer.materialize(plan, args.output)
        else:
            result = {'schema': writer.PLAN, 'run_id': plan['run_id'], 'summary': plan['summary'],
                      'affected': [{k: v for k, v in c.items() if k not in {'before_payload', 'payload', 'ledger'}} for c in plan['affected']],
                      'database_writes': 0}
    else:
        if not (args.root_candidate_write_approved and args.plan and args.plan_sha256):
            parser.error('ROOT write approval, exact plan and SHA required')
        pin = {'file': args.plan, 'sha256': args.plan_sha256}
        plan = writer.read_json(pin)
        method = writer.apply if args.mode == 'apply' else writer.rollback
        result = method(plan, root_write_approved=True)
        result['plan'] = pin
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
