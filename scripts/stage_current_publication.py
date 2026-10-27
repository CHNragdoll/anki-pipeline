"""Stage byte-preserving current web publications; never delete or activate them.

The existing service and its security guards remain authoritative. Old version
URLs get thin export shells backed by the current publication. Private settings
stay outside all mounted roots. A separate operator must validate and activate.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import stat


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def private_json(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def stage(config_path: Path, destination: Path, candidate_port=18871):
    config_path = config_path.resolve(strict=True)
    config = json.loads(config_path.read_text())
    original_mounts = json.loads(Path(config['static_mounts_path']).read_text())
    registry = json.loads(Path(config['registry_path']).read_text())
    rows = original_mounts['mounts']
    current = {row['url_mount']: row for row in rows if row['url_mount'].endswith('-web-v3/')}
    if not current or len({book['projection']['url_mount'] for book in registry['books']} - current.keys()):
        raise ValueError('Every registered book must have an explicit current publication')
    for row in rows:
        target = re.sub(r'-web-v[12]/$', '-web-v3/', row['url_mount'])
        if target not in current:
            raise ValueError('Unrecognized historical mount; no implicit retirement')
    destination = destination.absolute()
    public_roots = [Path(config['document_root']).resolve()]
    public_roots += [Path(row['export']).resolve() for row in rows]
    if any(destination.is_relative_to(root) or root.is_relative_to(destination) for root in public_roots):
        raise ValueError('Publication staging must not overlap current HTTP roots')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    settings = destination / 'settings'
    settings.mkdir(mode=0o700)
    private_json(settings / 'previous-service.json', config)
    private_json(settings / 'previous-mounts.json', original_mounts)
    private_json(settings / 'registry.json', registry)
    pool = {}
    counts = {'files': 0, 'logical_bytes': 0, 'duplicate_files': 0, 'duplicate_bytes': 0}
    replacements = {}
    with gzip.open(destination / 'file-ledger.jsonl.gz', 'xt') as ledger:
        for prefix, row in current.items():
            source = Path(row['export']).resolve(strict=True)
            target = destination / 'books' / source.name
            if target.name != prefix.rstrip('/').rsplit('/', 1)[1]:
                raise ValueError('Current root does not match its registered mount')
            target.mkdir(parents=True)
            for directory, directories, filenames in os.walk(source, followlinks=False):
                parent = Path(directory)
                if any((parent / name).is_symlink() for name in directories):
                    raise ValueError('Current publication still contains directory symlinks')
                relative = parent.relative_to(source)
                out = target / relative
                out.mkdir(exist_ok=True)
                for name in filenames:
                    old = parent / name
                    info = old.lstat()
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('Only regular current publication files may be staged')
                    new = out / name
                    identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
                    key = (name, info.st_size)
                    authority = old
                    sha = None
                    # Matching names alone never authorize deduplication.
                    for candidate, candidate_sha in pool.get(key, []):
                        sha = sha or digest(old)
                        if candidate_sha is None:
                            candidate_sha = digest(candidate)
                        if sha == candidate_sha:
                            authority = candidate
                            counts['duplicate_files'] += 1
                            counts['duplicate_bytes'] += info.st_size
                            break
                    os.link(authority, new, follow_symlinks=False)
                    after = old.stat()
                    if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                        raise ValueError('Source changed while staging')
                    pool.setdefault(key, []).append((new, sha))
                    counts['files'] += 1
                    counts['logical_bytes'] += info.st_size
                    ledger.write(json.dumps({'source': str(old), 'target': str(new),
                        'authority': str(authority), 'bytes': info.st_size,
                        'source_identity': identity, 'sha256': sha}) + '\n')
            replacements[prefix] = target
            print('staged', source.name, counts, flush=True)
    mounts = []
    for row in rows:
        prefix = row['url_mount']
        current_prefix = re.sub(r'-web-v[12]/$', '-web-v3/', prefix)
        target = replacements[current_prefix]
        if prefix == current_prefix:
            export = target
        else:
            export = destination / 'aliases' / prefix.rstrip('/').rsplit('/', 1)[1]
            export.mkdir(parents=True)
            # Current entry scripts and navigation are small; preserve relative URLs.
            for item in target.iterdir():
                if item.is_file() and item.name != 'catalog.json':
                    os.link(item, export / item.name)
            for name in ('cards', 'media', 'catalog.json'):
                (export / name).symlink_to(target / name, target_is_directory=name != 'catalog.json')
        mounts.append({'url_mount': prefix, 'export': str(export),
            'cards': str(target / 'cards'), 'media': str(target / 'media'),
            'catalog': str(target / 'catalog.json')})
    private_json(settings / 'mounts.json', {'schema': original_mounts['schema'], 'mounts': mounts})
    production = dict(config, registry_path=str(settings / 'registry.json'),
        static_mounts_path=str(settings / 'mounts.json'))
    private_json(settings / 'service.json', production)
    private_json(settings / 'candidate-service.json', dict(production, port=candidate_port))
    private_json(destination / 'STAGED.json', dict(counts, state='staged_not_activated',
        previous_config=str(config_path), retired_export_roots=[row['export'] for row in rows]))
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--candidate-port', type=int, default=18871)
    args = parser.parse_args()
    stage(args.config, args.destination, args.candidate_port)


if __name__ == '__main__':
    main()
