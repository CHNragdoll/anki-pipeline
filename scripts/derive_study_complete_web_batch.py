"""Build complete web delivery from a completed RR export; native files untouched."""
import argparse
import json
from pathlib import Path

from anki_pipeline.study_catalog_web_delivery import derive_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='completed parent DELIVERY directory')
    parser.add_argument('--source-complete-sha256', required=True, help='independent external parent COMPLETE pin')
    parser.add_argument('--output', type=Path, required=True, help='new immutable derivative directory')
    parser.add_argument('--base-url', required=True, help='logical final parent URL; no network is used')
    parser.add_argument('--node', default='node')
    parser.add_argument('--heap-mb', type=int, default=4096)
    args = parser.parse_args()
    report = derive_batch(args.source, args.output, expected_complete_sha256=args.source_complete_sha256,
        base_url=args.base_url, node=args.node, heap_mb=args.heap_mb,
        callback=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    print(json.dumps({'schema': report['schema'], 'webs': len(report['webs'])}), flush=True)


if __name__ == '__main__':
    main()
