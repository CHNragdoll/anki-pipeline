"""Prepare or finalize one immutable full-web derivative; never runs a producer."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def pinned(path, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            raise ValueError('bounded regular metadata required')
        pieces, total = [], 0
        while raw := os.read(fd, 65536):
            total += len(raw)
            if total > 64 * 1024 * 1024:
                raise ValueError('metadata byte bound exceeded')
            pieces.append(raw)
        raw = b''.join(pieces)
        if (stamp(before) != stamp(os.fstat(fd)) or stamp(before) != stamp(Path(path).lstat()) or
                len(raw) != before.st_size or hashlib.sha256(raw).hexdigest() != expected):
            raise ValueError('external metadata SHA/bytes/identity differs')
        return raw
    finally:
        os.close(fd)


def generator(path, expected):
    raw = pinned(path, expected)
    value = json.loads(raw)
    if value.get('schema') != 'study-complete-frozen-builder.v1' or not value.get('files'):
        raise ValueError('frozen generator required')
    root = Path(value['source_root'])
    if not root.is_absolute():
        raise ValueError('absolute frozen source root required')
    link = value.get('readonly_dependency_link')
    if link and (not (root / link['path']).is_symlink() or os.readlink(root / link['path']) != link['target']):
        raise ValueError('frozen dependency link changed')
    for name, descriptor in value['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('unsafe frozen generator member')
        code = pinned(root / relative, descriptor['sha256'])
        if type(descriptor['bytes']) is not int or len(code) != descriptor['bytes']:
            raise ValueError('frozen generator byte count differs')
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'finalize'))
    parser.add_argument('--generator', type=Path, required=True)
    parser.add_argument('--generator-sha256', required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-complete-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--cache-index', type=Path)
    parser.add_argument('--cache-index-sha256')
    args = parser.parse_args()
    source = generator(args.generator, args.generator_sha256)
    sys.path.insert(0, str(source))
    from anki_pipeline import study_catalog_web_delivery as delivery
    from anki_pipeline.study_compiled_schedule import StageSeparatedBuild
    from anki_pipeline.study_compiled_resume import ResultCache, MapBuilder, _Receipts
    if not Path(delivery.__file__).is_relative_to(source):
        raise ValueError('delivery is outside authenticated frozen source')
    options = dict(expected_complete_sha256=args.source_complete_sha256,
                   base_url=args.base_url, callback=lambda value: print(json.dumps(value), flush=True))
    if args.mode == 'prepare':
        if args.cache_index or args.cache_index_sha256:
            raise ValueError('prepare does not consume cached results')
        result = delivery.derive_batch(args.source, args.output, prepare_only=True,
            final_check=lambda: generator(args.generator, args.generator_sha256), **options)
        marker = args.output / 'preparation-authority/COMPLETE.json'
    else:
        if not args.cache_index or not args.cache_index_sha256:
            raise ValueError('finalize requires externally pinned complete cache index')
        with ResultCache({'path': str(args.cache_index), 'sha256': args.cache_index_sha256}) as cache:
            receipts = _Receipts()
            @contextmanager
            def factory(directory):
                # This original validator is used only for native-free authored
                # cards; every compiled card MUST come from the qualified map.
                with StageSeparatedBuild(directory, heap_mb=4096) as original:
                    yield MapBuilder(cache, source_builder=original, receipts=receipts)
                    if original.worker is not None:
                        raise AssertionError('finalization must never start a producer')
            def final_check():
                cache.check()
                receipts.check()
                generator(args.generator, args.generator_sha256)
            result = delivery.derive_batch(args.source, args.output,
                builder_factory=factory, final_check=final_check, **options)
        marker = args.output / 'COMPLETE.json'
    with marker.open('rb') as stream:
        pin = hashlib.file_digest(stream, 'sha256').hexdigest()
    print(json.dumps({'schema': result['schema'], 'marker': str(marker), 'sha256': pin,
                      'webs': len(result['webs']), 'native_artifacts_regenerated': False}), flush=True)


if __name__ == '__main__':
    main()
