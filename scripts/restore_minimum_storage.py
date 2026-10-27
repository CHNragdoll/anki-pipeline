"""Restore a cold file/directory from the local minimum-storage receipts.

Read-only by default. --restore requires the exact original path listed by
--list. Refuses overwrite, outside-root paths and corrupt archived bytes.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SERVICE = Path.home() / 'Library/Application Support/AnkiStudyCatalog'


def checked_path(value, roots):
    path = Path(value).resolve(strict=False)
    if not any(path.is_relative_to(root.resolve()) and path != root.resolve() for root in roots):
        raise ValueError('Path outside permitted roots')
    return path


def receipts(journal):
    records = []
    for name in ('cold-archives.json', 'semantic-source-archive.json', 'chunk-backups.json'):
        source = journal / name
        if source.exists():
            for row in json.loads(source.read_text())['files']:
                records.append(dict(row, kind='chunks' if 'chunks' in row else 'file'))
    source = journal / 'directory-archives.json'
    if source.exists():
        records.extend(dict(row, kind='directory') for row in json.loads(source.read_text())['directories'])
    return records


def restore_file(row, target, archives, chunk_root):
    if target.exists() or target.is_symlink():
        raise FileExistsError('Original path already exists')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.restore-', dir=target.parent)
    temp = Path(name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, 'wb') as out:
            if row['kind'] == 'chunks':
                for chunk in row['chunks']:
                    sha = chunk['sha256']
                    if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                        raise ValueError('Invalid chunk identity')
                    source = checked_path(str(chunk_root / sha), archives)
                    raw = source.read_bytes()
                    if len(raw) != chunk['bytes'] or hashlib.sha256(raw).hexdigest() != sha:
                        raise ValueError('Corrupt chunk')
                    out.write(raw); digest.update(raw); size += len(raw)
            else:
                source = checked_path(row['archive'], archives)
                with subprocess.Popen(['/opt/homebrew/bin/zstd', '-q', '-dc', str(source)], stdout=subprocess.PIPE) as proc:
                    for raw in iter(lambda: proc.stdout.read(4 * 1024**2), b''):
                        out.write(raw); digest.update(raw); size += len(raw)
                    if proc.wait():
                        raise ValueError('Decompression failed')
            out.flush(); os.fsync(out.fileno())
        if digest.hexdigest() != row['sha256'] or size != row['bytes']:
            raise ValueError('Restored bytes do not match receipt')
        os.chmod(temp, row['mode'])
        os.utime(temp, ns=(row['mtime_ns'], row['mtime_ns']))
        os.link(temp, target)  # atomic publication with no overwrite
    finally:
        temp.unlink(missing_ok=True)


def restore_directory(row, target, archives, journal):
    if target.exists() or target.is_symlink():
        raise FileExistsError('Original directory already exists')
    source = checked_path(row['archive'], archives)
    manifest_path = checked_path(row['file_manifest'], [journal])
    with gzip.open(manifest_path, 'rt') as stream:
        expected = json.load(stream)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=target.parent) as temporary:
        staging = Path(temporary)
        with subprocess.Popen(['/opt/homebrew/bin/zstd', '-q', '-dc', str(source)], stdout=subprocess.PIPE) as proc:
            with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
                for member in tar:
                    relative = Path(member.name)
                    if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != target.name:
                        raise ValueError('Archive member outside original directory')
                    tar.extract(member, path=staging, filter='data')
            for unused in iter(lambda: proc.stdout.read(1024**2), b''):
                pass
            if proc.wait():
                raise ValueError('Decompression failed')
        actual = {}
        for path in staging.rglob('*'):
            if path.is_file() and not path.is_symlink():
                h = hashlib.sha256()
                with path.open('rb') as stream:
                    for raw in iter(lambda: stream.read(1024**2), b''):
                        h.update(raw)
                actual[str(path.relative_to(staging))] = {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}
        if actual != expected:
            raise ValueError('Restored directory does not match receipt')
        if target.exists() or target.is_symlink():
            raise FileExistsError('Original directory appeared during restore')
        (staging / target.name).rename(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--journal', type=Path, default=ROOT / 'output/storage-minimum-20261027')
    parser.add_argument('--restore', help='Exact original path from the receipts; otherwise list only')
    args = parser.parse_args()
    journal = checked_path(str(args.journal), [ROOT / 'output'])
    rows = receipts(journal)
    if args.restore is None:
        for row in rows:
            print(row['original'])
        return
    matches = [row for row in rows if row['original'] == args.restore]
    if len(matches) != 1:
        raise ValueError('Path must identify exactly one receipt')
    row = matches[0]
    target = checked_path(row['original'], [ROOT.parent, SERVICE])
    archives = [ROOT / 'backups']
    if row['kind'] == 'directory':
        restore_directory(row, target, archives, journal)
    else:
        restore_file(row, target, archives, ROOT / 'backups/minimum-chunks-20261027')
    print('Restored and verified:', target)


if __name__ == '__main__':
    main()
