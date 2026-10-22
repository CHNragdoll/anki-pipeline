"""Build accepted complete-card deliveries from a sealed existing export.

Operational runner only: the frozen common builder owns all semantics. This
does not replace live files, write PG, or build/import an Anki collection.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import os
import stat
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin


def pin(path, expected=None):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    stamp = lambda s: (s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            raise ValueError('bounded regular source metadata required')
        pieces = []
        total = 0
        while chunk := os.read(fd, 65536):
            pieces.append(chunk)
            total += len(chunk)
            if total > 64 * 1024 * 1024:
                raise ValueError('source metadata byte limit')
        raw = b''.join(pieces)
        if stamp(before) != stamp(os.fstat(fd)) or stamp(before) != stamp(path.lstat()):
            raise ValueError('source metadata FD/path identity differs')
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != before.st_size or expected is not None and digest != expected:
            raise ValueError('source metadata SHA/bytes differs')
        return digest, raw
    finally:
        os.close(fd)


def read_json(path):
    return json.loads(pin(path)[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--preparation-complete-sha256', required=True)
    parser.add_argument('--cache-index', type=Path)
    parser.add_argument('--cache-index-sha256')
    parser.add_argument('--exports', type=Path, required=True)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--book', action='append', required=True,
                        help='catalog book id:export directory name')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--shard-index', type=int, default=0)
    parser.add_argument('--shard-count', type=int, default=1)
    parser.add_argument('--min-bytes', type=int, default=0)
    parser.add_argument('--max-bytes', type=int, default=0)
    parser.add_argument('--heap-mb', type=int, default=4096)
    parser.add_argument('--repair-from', type=Path,
                        help='retry only currently failed identities from a previous frozen batch')
    parser.add_argument('--node', required=True)
    args = parser.parse_args()
    with ExitStack() as stack:
        if not (1 <= args.shard_count <= 8 and 0 <= args.shard_index < args.shard_count
                and args.min_bytes >= 0 and args.max_bytes >= 0 and args.limit >= 0):
            raise ValueError('invalid bounded batch partition')
        if bool(args.cache_index) != bool(args.cache_index_sha256):
            raise ValueError('cache index requires independent SHA')
        source_pin, source_raw = pin(args.stage / 'SOURCE.json', args.source_sha256)
        frozen = json.loads(source_raw)
        source = Path(frozen['source_root'])
        link = frozen.get('readonly_dependency_link')
        if link and (not (source / link['path']).is_symlink() or os.readlink(source / link['path']) != link['target']):
            raise ValueError('frozen dependency link changed')
        for relative, expected in frozen['files'].items():
            name = Path(relative)
            if name.is_absolute() or '..' in name.parts or '\\' in relative:
                raise ValueError('frozen generator relative path differs')
            actual, code = pin(source / name, expected['sha256'])
            if len(code) != expected['bytes']:
                raise ValueError('frozen generator file byte count differs')
        # Import the sealed source, never mutable working-tree modules.
        sys.path.insert(0, str(source))
        from anki_pipeline.study_compiled_schedule import StageSeparatedBuild as CompiledBuild
        from anki_pipeline.study_compiled_resume import ResultCache, MapBuilder
        from anki_pipeline import study_compiled
        if not Path(study_compiled.__file__).is_relative_to(source):
            raise ValueError('common generator is not the frozen source')
        for relative, expected in frozen['files'].items():
            if pin(source / relative)[0] != expected['sha256']:
                raise ValueError('frozen generator changed: ' + relative)
        preparation_marker = args.exports / 'preparation-authority/COMPLETE.json'
        _, preparation_raw = pin(preparation_marker, args.preparation_complete_sha256)
        preparation = study_compiled._json(preparation_raw)
        if preparation.get('schema') != 'study-web-batch-preparation-complete.v1':
            raise ValueError('explicit completed preparation required')
        manifest_path = args.exports / 'manifest.json'
        _, manifest_raw = pin(manifest_path, preparation['manifest_sha256'])
        manifest = study_compiled._json(manifest_raw)
        if (len(manifest_raw) != preparation['manifest_bytes'] or
                manifest.get('schema') != 'study-web-batch-preparation.v1' or
                len(manifest['webs']) != preparation['webs']):
            raise ValueError('preparation manifest differs')
        prepared_books = {row['name']: row for row in manifest['webs']}
        if len(prepared_books) != len(manifest['webs']):
            raise ValueError('duplicate prepared book directories')
        aliases = []
        def catalog_bytes(root, dirname, book):
            row = prepared_books[dirname]
            if row['book_id'] != book:
                raise ValueError('prepared book namespace differs')
            receipts = [r for r in row['source_metadata'] if Path(r['path']).name == 'catalog.json']
            if len(receipts) != 1:
                raise ValueError('one authenticated parent catalog required')
            receipt = receipts[0]
            alias = root / 'catalog.json'
            target = Path(receipt['path'])
            stamp = lambda s: [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
            if (not target.is_absolute() or not alias.is_symlink() or os.readlink(alias) != str(target) or
                    alias.resolve(strict=True) != target or target.resolve(strict=True) != target):
                raise ValueError('catalog alias must target its authenticated canonical parent')
            before = stamp(alias.lstat())
            actual, raw = pin(target, receipt['sha256'])
            if (len(raw) != receipt['bytes'] or stamp(target.lstat()) != receipt['six'] or
                    stamp(alias.lstat()) != before or os.readlink(alias) != str(target)):
                raise ValueError('parent catalog alias/SHA/six differs')
            aliases.append((alias,target,before,receipt))
            return actual, raw
        snapshot, jobs = {}, []
        for specification in args.book:
            book, dirname = specification.split(':', 1)
            root = args.exports / dirname
            catalog_pin, catalog_raw = catalog_bytes(root, dirname, book)
            sealed_index = args.stage / 'inputs' / book / 'index.html'
            index_pin, index_raw = pin(sealed_index if sealed_index.exists() else root / 'index.html')
            match = re.search(rb'<script id="study-library-config" type="application/json">(.*?)</script>', index_raw, re.S)
            if match is None:
                raise ValueError('one explicit library configuration is required')
            config = json.loads(match[1])['sharedFrame']
            descriptor = config['preparedIndex']
            index_actual, prepared_raw = pin(root / descriptor['src'])
            if index_actual != descriptor['sha256']:
                raise ValueError('prepared index differs')
            catalog, prepared = json.loads(catalog_raw), json.loads(prepared_raw)
            if catalog['book_id'] != book:
                raise ValueError('source book namespace differs')
            prepared = prepared['cards']
            snapshot[book] = {'root': str(root), 'catalog_sha256': catalog_pin,
                              'index_sha256': index_pin, 'prepared_index': descriptor,
                              'revision': catalog.get('catalog_revision'),
                              'total': len(catalog['cards'])}
            for card in catalog['cards']:
                wrapper = root / card['url']
                jobs.append((root, config['policy'], card, prepared[card['id']],
                             {'path': card['url'], 'sha256': pin(wrapper)[0]}, book, dirname))
        snapshot = {'books': snapshot, 'base_url': args.base_url.rstrip('/') + '/', 'generator_sha256': source_pin, 'preparation_complete_sha256': args.preparation_complete_sha256}
        snapshot_path = args.stage / 'INPUTS.json'
        if snapshot_path.exists() and read_json(snapshot_path) != snapshot:
            raise ValueError('export source changed between bounded runs')
        if not snapshot_path.exists():
            snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
        cache = stack.enter_context(ResultCache({'path': str(args.cache_index.resolve()), 'sha256': args.cache_index_sha256})) if args.cache_index else None
        reused = MapBuilder(cache) if cache is not None else None
        done = set()
        pending = []
        repair = None
        if args.repair_from:
            failed, recovered = set(), set()
            for previous in args.repair_from.glob('results*.jsonl'):
                for line in previous.read_text().splitlines(keepends=True):
                    if not line.endswith('\n'):
                        continue
                    item = json.loads(line)
                    (recovered if item['status'] == 'ok' else failed).add(item['identity'])
            repair = failed - recovered
        for index, job in enumerate(jobs):
            identity = job[5] + ':' + job[2]['id']
            if (index % args.shard_count != args.shard_index or identity in done
                    or repair is not None and identity not in repair):
                continue
            size = (job[0] / job[3]['src']).stat().st_size
            if size < args.min_bytes or args.max_bytes and size > args.max_bytes:
                continue
            if cache is not None and identity in cache.rows:
                reused.build(job[0], job[4], {'path': job[3]['src'], 'sha256': job[3]['sha256']},
                    identity=identity, policy=job[1], source_url=urljoin(args.base_url.rstrip('/') + '/', job[6] + '/index.html'))
                done.add(identity)
                continue
            pending.append(job)
        if args.limit:
            pending = pending[:args.limit]
        run = args.stage / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
        result_file = args.stage / (run.name + f'-results-{args.shard_index}-of-{args.shard_count}.jsonl')
        started = time.monotonic()
        passed = failed = 0
        print(json.dumps({'event': 'begin', 'total': len(jobs), 'previously_done': len(done),
                          'selected': len(pending), 'run': str(run)}), flush=True)
        with result_file.open('x', encoding='utf-8') as log, CompiledBuild(run, node=args.node, heap_mb=args.heap_mb) as build:
            for root, policy, card, artifact, wrapper, book, dirname in pending:
                identity = book + ':' + card['id']
                before = time.monotonic()
                try:
                    result = build.build(root, wrapper, {'path': artifact['src'], 'sha256': artifact['sha256']},
                        identity=identity, policy=policy,
                        source_url=urljoin(args.base_url.rstrip('/') + '/', dirname + '/index.html'))
                    item = {'status': 'ok', 'identity': identity, 'word': card['word'],
                            'seconds': round(time.monotonic() - before, 3), 'result': result}
                    passed += 1
                except Exception as error:
                    item = {'status': 'failed', 'identity': identity, 'word': card['word'],
                            'seconds': round(time.monotonic() - before, 3),
                            'error': type(error).__name__ + ': ' + str(error)[:2048]}
                    failed += 1
                    print(json.dumps({'event': 'failure', **{k: v for k, v in item.items() if k != 'result'}}), flush=True)
                if item['status'] != 'ok' or item['result']['mode'] == 'compiled':
                    log.write(json.dumps(item, ensure_ascii=False, separators=(',', ':')) + '\n')
                    log.flush()
                if (passed + failed) % 25 == 0:
                    print(json.dumps({'event': 'progress', 'passed': passed, 'failed': failed,
                                      'seconds': round(time.monotonic() - started, 2)}), flush=True)
                # A dead worker is terminal; do not retry or silently restart it.
                if build.worker is not None and build.worker.process.poll() is not None:
                    raise RuntimeError('common worker exited; retained job is terminal')
                if failed >= 20:
                    raise RuntimeError('bounded failure threshold reached; inspect retained jobs')
        if reused is not None:
            reused.check()
        for alias,target,before,receipt in aliases:
            stamp = lambda s: [s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
            if (stamp(alias.lstat()) != before or not alias.is_symlink() or os.readlink(alias) != str(target) or
                    stamp(target.lstat()) != receipt['six']):
                raise ValueError('parent catalog alias/six changed during shard')
            pin(target, receipt['sha256'])
            if (stamp(target.lstat()) != receipt['six'] or stamp(alias.lstat()) != before or
                    not alias.is_symlink() or os.readlink(alias) != str(target)):
                raise ValueError('parent catalog alias/six changed during final SHA read')
        pin(preparation_marker, args.preparation_complete_sha256)
        pin(manifest_path, preparation['manifest_sha256'])
        pin(args.stage / 'SOURCE.json', args.source_sha256)
        for relative, expected in frozen['files'].items():
            pin(source / relative, expected['sha256'])
        print(json.dumps({'event': 'done', 'passed': passed, 'failed': failed,
                          'seconds': round(time.monotonic() - started, 2), 'result_file': str(result_file)}), flush=True)


if __name__ == '__main__':
    main()
