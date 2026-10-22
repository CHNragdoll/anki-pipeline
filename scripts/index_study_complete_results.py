"""Pin closed standard result logs; no producer/content qualification claim."""
import argparse
import json
from pathlib import Path
import sys

from derive_study_complete_web_batch import generator


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True, help='new metadata artifact directory')
    parser.add_argument('--seed-index', type=Path)
    parser.add_argument('--seed-index-sha256')
    args = parser.parse_args()
    source = generator(args.stage / 'SOURCE.json', args.source_sha256)
    sys.path.insert(0, str(source))
    from anki_pipeline import study_catalog_web_delivery as delivery
    from anki_pipeline import study_compiled_build as shared
    from anki_pipeline.study_compiled_resume import ResultCache
    value = {'schema': 'study-complete-result-cache.v1', 'files': [], 'completed_semantic': {}}
    if args.seed_index:
        if not args.seed_index_sha256:
            raise ValueError('seed requires independent index SHA')
        raw, _ = delivery._read(args.seed_index, args.seed_index_sha256)
        value = shared.inputs._json(raw)
    elif args.seed_index_sha256:
        raise ValueError('seed index path missing')
    for path in sorted(args.stage.glob('build-*-results-*.jsonl')):
        run = path.name.split('-results-', 1)[0]
        _, receipt = delivery._read(path, limit=256 * 1024 * 1024, keep=False)
        value['files'].append({'path': str(path.absolute()), 'sha256': receipt['sha256'],
                               'bytes': receipt['bytes'], 'assets': str((args.stage / run / 'assets').absolute())})
    store = shared.ArtifactStore(args.output)
    asset = store.put(shared._json(value), 'json')
    descriptor = store.descriptor(asset)
    with ResultCache({key: descriptor[key] for key in ('path', 'sha256')}) as cache:
        count = len(cache.rows)
    generator(args.stage / 'SOURCE.json', args.source_sha256)
    print(json.dumps({'scope': 'PINNED_COMPILED_LOG_INDEX_NOT_DELIVERY_ACCEPTANCE',
                      'index': descriptor, 'compiled_identities': count,
                      'authored_source_validation_is_always_fresh': True}), flush=True)


if __name__ == '__main__':
    main()
