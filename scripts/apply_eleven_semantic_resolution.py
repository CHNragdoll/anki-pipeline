"""Prepare and rehearse the 11-record classification lane; explicit ROOT applies."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from anki_pipeline import eleven_semantic_resolution as lane
from anki_pipeline import residual_optimization as ro
from anki_pipeline import source_confirmations as sc

OWNED = ROOT / 'output/eleven-resolution-20261014/semantic-apply-own'
CANDIDATE = ROOT / 'data/sense-frequency-optimized-20261013.sqlite3'
PROTECTED = ROOT / 'data/sense-frequency-usage-20261012-v5-recovery.sqlite3'


def owned(path):
    path = Path(path).resolve()
    lane.require(path.is_relative_to(OWNED) and path != OWNED, 'fresh semantic-owned child output required')
    return path


def load(path, sha):
    plan = ro.read_json({'file': str(owned(path)), 'sha256': sha})
    lane.require(Path(plan['candidate']).resolve() == CANDIDATE and Path(plan['protected']['file']).resolve() == PROTECTED,
                 'only authorized current candidate and recovery baseline permitted')
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--output', type=Path, required=True)
    for action in ('rehearse', 'apply', 'rollback'):
        p = sub.add_parser(action)
        p.add_argument('--plan', type=Path, required=True)
        p.add_argument('--plan-sha256', required=True)
        p.add_argument('--output', type=Path, required=True)
        if action != 'rehearse':
            p.add_argument('--root-write-approved', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        evidence = ROOT / 'output/eleven-resolution-20261014'
        request = {'schema': lane.REQUEST, 'candidate': {'file': str(CANDIDATE)},
            'protected': {'file': str(PROTECTED), 'stat': sc.stat_pin(PROTECTED)},
            'body_evidence': lane.pin(evidence / 'research-body.json'),
            'option_evidence': lane.pin(evidence / 'research-options.json'),
            'as_evidence': lane.pin(evidence / 'research-as.json'),
            'as_deep_evidence': lane.pin(evidence / 'as-deep-research-summary.json'),
            'secure_chinese_evidence': lane.pin(evidence / 'source-targets-own/secure-native-chinese.json')}
        result = lane.prepare(request, owned(args.output))
    else:
        plan = load(args.plan, args.plan_sha256)
        if args.command == 'rehearse':
            result = lane.rehearse(plan, owned(args.output))
        else:
            output = owned(args.output)
            lane.require(not output.exists(), 'fresh semantic receipt required')
            result = getattr(lane, args.command)(plan, root_write_approved=args.root_write_approved)
            output.parent.mkdir(parents=True, exist_ok=True)
            sc._write_json(output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
