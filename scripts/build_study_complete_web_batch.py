"""Build accepted complete-card deliveries from a sealed existing export.

Operational runner only: the frozen common builder owns all semantics. This
does not replace live files, write PG, or build/import an Anki collection.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urljoin


def pin(path):
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), raw


def read_json(path):
    return json.loads(path.read_text('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
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
    if not (1 <= args.shard_count <= 8 and 0 <= args.shard_index < args.shard_count
            and args.min_bytes >= 0 and args.max_bytes >= 0 and args.limit >= 0):
        raise ValueError('invalid bounded batch partition')
    frozen = read_json(args.stage / 'SOURCE.json')
    source = Path(frozen['source_root'])
    # Import the sealed source, never mutable working-tree modules.
    sys.path.insert(0, str(source))
    from anki_pipeline.study_compiled_build import CompiledBuild
    from anki_pipeline import study_compiled
    if not Path(study_compiled.__file__).is_relative_to(source):
        raise ValueError('common generator is not the frozen source')
    for relative, expected in frozen['files'].items():
        if pin(source / relative)[0] != expected['sha256']:
            raise ValueError('frozen generator changed: ' + relative)
    snapshot, jobs = {}, []
    for specification in args.book:
        book, dirname = specification.split(':', 1)
        root = args.exports / dirname
        catalog_pin, catalog_raw = pin(root / 'catalog.json')
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
    snapshot_path = args.stage / 'INPUTS.json'
    if snapshot_path.exists() and read_json(snapshot_path) != snapshot:
        raise ValueError('export source changed between bounded runs')
    if not snapshot_path.exists():
        snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n')
    result_file = args.stage / f'results-{args.shard_index}-of-{args.shard_count}-{args.min_bytes}-{args.max_bytes}.jsonl'
    done = set()
    for previous in args.stage.glob('results*.jsonl'):
        for line in previous.read_text().splitlines(keepends=True):
            if not line.endswith('\n'):
                continue  # Another disjoint shard may be appending its last record.
            item = json.loads(line)
            if item['status'] == 'ok':
                done.add(item['identity'])
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
        pending.append(job)
    if args.limit:
        pending = pending[:args.limit]
    run = args.stage / ('build-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    started = time.monotonic()
    passed = failed = 0
    print(json.dumps({'event': 'begin', 'total': len(jobs), 'previously_done': len(done),
                      'selected': len(pending), 'run': str(run)}), flush=True)
    with result_file.open('a', encoding='utf-8') as log, CompiledBuild(run, node=args.node, heap_mb=args.heap_mb) as build:
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
    print(json.dumps({'event': 'done', 'passed': passed, 'failed': failed,
                      'seconds': round(time.monotonic() - started, 2), 'result_file': str(result_file)}), flush=True)


if __name__ == '__main__':
    main()
