"""Derive complete webs; only an explicit pinned repair plan may run a producer."""
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


class RepairPlans:
    """Partition one externally pinned approved set into exact book scopes."""
    def __init__(self, descriptor, receipts):
        from anki_pipeline import study_compiled_preparation as preparation
        from anki_pipeline.study_compiled_build import CompiledBuild
        from anki_pipeline.study_catalog_web_delivery import _decode
        self.receipts = receipts
        raw = receipts.read(descriptor['path'], descriptor['sha256'])
        self.value = _decode(raw)
        if (set(self.value) != {'schema', 'sources', 'dependencies', 'changed'} or
                self.value['schema'] != 'study-compiled-repair-plan.v1' or
                self.value['sources'] != preparation.source_pins() or
                self.value['dependencies'] != CompiledBuild._dependencies() or
                type(self.value['changed']) is not list):
            raise ValueError('global repair plan schema/source/dependencies differ')
        self.changed = {}
        for row in self.value['changed']:
            if (type(row) is not dict or set(row) != {'identity', 'base_artifact', 'artifact'} or
                    type(row['identity']) is not str or row['identity'] in self.changed):
                raise ValueError('global repair identities must be exact and unique')
            self.changed[row['identity']] = row
        self.assigned, self.books, self.reports = set(), set(), []

    def book(self, directory):
        from anki_pipeline import study_catalog_web_delivery as delivery
        directory = Path(directory)
        root = directory.parent.parent / directory.name
        catalog_path = (root / 'catalog.json').resolve(strict=True)
        raw, receipt = delivery._read(catalog_path)
        self.receipts.read(catalog_path, receipt['sha256'])
        catalog = delivery._decode(raw)
        book = catalog['book_id']
        if book in self.books:
            raise ValueError('duplicate repair book scope')
        self.books.add(book)
        members = {book + ':' + card['id'] for card in catalog['cards']}
        selected = sorted(members & self.changed.keys())
        if self.assigned.intersection(selected):
            raise ValueError('repair identity assigned twice')
        self.assigned.update(selected)
        value = {**self.value, 'changed': [self.changed[key] for key in selected]}
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        path = directory.parent / (directory.name + '.repair-plan.json')
        with path.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            written = delivery._six(os.fstat(stream.fileno()))
        pin = hashlib.sha256(raw).hexdigest()
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            receipt = self.receipts.publish_new_owned(path.parent.absolute(), fd, {path.name: pin})[path.name]
            if receipt['six'][:5] != written[:5]:
                raise ValueError('new book repair plan identity changed during publication')
        finally:
            os.close(fd)
        return {'path': str(path.absolute()), 'sha256': pin}

    def check(self):
        if self.assigned != set(self.changed) or len(self.reports) != len(self.books):
            raise ValueError('repair plan was not completely processed across all books')
        self.receipts.check()


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
    parser.add_argument('--repair-plan', type=Path)
    parser.add_argument('--repair-plan-sha256')
    args = parser.parse_args()
    if bool(args.repair_plan) != bool(args.repair_plan_sha256):
        parser.error('repair plan and external SHA must be paired')
    if args.mode == 'prepare' and args.repair_plan:
        parser.error('prepare cannot start a planned repair producer')
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
            plans = (RepairPlans({'path': str(args.repair_plan.absolute()), 'sha256': args.repair_plan_sha256}, receipts)
                     if args.repair_plan else None)
            @contextmanager
            def factory(directory):
                if plans is not None:
                    from anki_pipeline.study_compiled_repair import RepairBuilder
                    with RepairBuilder(cache, directory, plan=plans.book(directory), receipts=receipts) as repair:
                        yield repair
                    plans.reports.append(repair.report())
                    return
                # This original validator is used only for native-free authored
                # cards; every compiled card MUST come from the qualified map.
                with StageSeparatedBuild(directory, heap_mb=4096) as original:
                    yield MapBuilder(cache, source_builder=original, receipts=receipts)
                    if original.worker is not None:
                        raise AssertionError('finalization must never start a producer')
            def final_check():
                cache.check()
                receipts.check()
                if plans is not None:
                    plans.check()
                generator(args.generator, args.generator_sha256)
            result = delivery.derive_batch(args.source, args.output,
                builder_factory=factory, final_check=final_check, **options)
        marker = args.output / 'COMPLETE.json'
    with marker.open('rb') as stream:
        pin = hashlib.file_digest(stream, 'sha256').hexdigest()
    receipt = {'schema': result['schema'], 'marker': str(marker), 'sha256': pin,
               'webs': len(result['webs']), 'native_artifacts_regenerated': False}
    if args.mode == 'finalize' and plans is not None:
        receipt['repair_plan'] = {'path': str(args.repair_plan.absolute()), 'sha256': args.repair_plan_sha256}
        receipt['repairs'] = plans.reports
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    main()
