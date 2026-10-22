"""Pin closed standard result logs; no producer/content qualification claim."""
import argparse
import json
from pathlib import Path
import sys

from derive_study_complete_web_batch import generator, pinned


_CONSUMER_CHANGES = {'anki_pipeline/study_compiled_resume.py',
                     'scripts/index_study_complete_results.py'}


def authorities(stage, producer_sha256, consumer_source=None, consumer_sha256=None):
    """Authenticate the original producer separately from an optional reader upgrade."""
    producer_source = stage / 'SOURCE.json'
    producer_root = generator(producer_source, producer_sha256)
    producer = {'path': str(producer_source.absolute()), 'sha256': producer_sha256}
    if bool(consumer_source) != bool(consumer_sha256):
        raise ValueError('consumer SOURCE and external SHA must be paired')
    if consumer_source is None:
        return producer_root, {'producer': producer, 'consumer': producer, 'changed_files': []}
    consumer_root = generator(consumer_source, consumer_sha256)
    original = json.loads(pinned(producer_source, producer_sha256))
    updated = json.loads(pinned(consumer_source, consumer_sha256))
    if (set(original['files']) != set(updated['files']) or
            original.get('readonly_dependency_link') != updated.get('readonly_dependency_link')):
        raise ValueError('producer/consumer frozen file census or dependency link differs')
    changed = {name for name, value in original['files'].items() if value != updated['files'][name]}
    if changed != _CONSUMER_CHANGES:
        raise ValueError('consumer may change only the two metadata reader files')
    if Path(__file__).absolute() != consumer_root / 'scripts/index_study_complete_results.py':
        raise ValueError('index CLI is outside authenticated consumer SOURCE')
    return consumer_root, {'producer': producer,
        'consumer': {'path': str(consumer_source.absolute()), 'sha256': consumer_sha256},
        'changed_files': sorted(changed)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--consumer-source', type=Path,
                        help='independently pinned reader SOURCE; producer remains stage/SOURCE.json')
    parser.add_argument('--consumer-source-sha256')
    parser.add_argument('--output', type=Path, required=True, help='new metadata artifact directory')
    parser.add_argument('--seed-index', type=Path)
    parser.add_argument('--seed-index-sha256')
    args = parser.parse_args()
    source, proof = authorities(args.stage, args.source_sha256,
                                args.consumer_source, args.consumer_source_sha256)
    sys.path.insert(0, str(source))
    from anki_pipeline import study_catalog_web_delivery as delivery
    from anki_pipeline import study_compiled_build as shared
    from anki_pipeline.study_compiled_resume import ResultCache
    if any(not Path(module.__file__).is_relative_to(source) for module in
           (delivery, shared, sys.modules[ResultCache.__module__])):
        raise ValueError('index reader is outside authenticated consumer SOURCE')
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
    if authorities(args.stage, args.source_sha256, args.consumer_source,
                   args.consumer_source_sha256) != (source, proof):
        raise ValueError('producer/consumer authority changed during indexing')
    print(json.dumps({'scope': 'PINNED_COMPILED_LOG_INDEX_NOT_DELIVERY_ACCEPTANCE',
                      'index': descriptor, 'compiled_identities': count,
                      'sources': proof,
                      'authored_source_validation_is_always_fresh': True}), flush=True)


if __name__ == '__main__':
    main()
