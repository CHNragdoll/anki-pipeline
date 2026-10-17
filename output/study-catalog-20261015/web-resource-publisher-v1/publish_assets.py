"""Publish the pinned private candidate ledger; never replace a live index."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PLAN = Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/full-web-candidate-preparation-v2-jo6c7idy/PLAN.json')
PLAN_SHA = '78e16c2f8f8d0bc53ff4409cbd84fc8fec5bfa142ba90646a3c28546e65fd580'
NAME = re.compile(r'[A-Za-z0-9_]+_([a-f0-9]{64})\.(?:html|js|json|json\.gz)')

def require(ok, message):
    if not ok: raise ValueError(message)

def stamp(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

def content_stamp(s):
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

def checked_fd(path, expected, size=None, dir_fd=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode), 'regular input required')
        require(size is None or before.st_size == size, 'file length differs')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            observed = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(fd)
        require(stamp(before) == stamp(after) == stamp(os.stat(path, dir_fd=dir_fd, follow_symlinks=False)), 'input changed during verification')
        require(observed == expected, 'file SHA differs')
        return fd, after
    except BaseException:
        os.close(fd)
        raise

def read_json(path, expected):
    fd, s = checked_fd(path, expected)
    try:
        require(s.st_size < 256 * 1024 * 1024, 'bounded metadata required')
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), 'rb') as stream: raw = stream.read()
        require(hashlib.sha256(raw).hexdigest() == expected and stamp(s) == stamp(os.fstat(fd)), 'metadata changed')
        return json.loads(raw)
    finally: os.close(fd)

def open_directory(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'absolute owned directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    chain = []
    prefix = Path('/')
    try:
        for part in path.parts[1:]:
            nextfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nextfd; prefix = prefix / part
            s = os.fstat(fd); chain.append((prefix, s.st_dev, s.st_ino))
        owned = (fd, chain)
        check_directory(owned)
        return owned
    except BaseException:
        os.close(fd)
        raise

def check_chain(chain):
    for path, device, inode in chain:
        current = path.lstat()
        require(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == (device, inode), 'destination ancestor changed')

def check_directory(owned):
    fd, chain = owned
    check_chain(chain)
    last = os.fstat(fd)
    require(not chain or (last.st_dev, last.st_ino) == chain[-1][1:], 'held directory differs')

def link_one(source, destination_dir, name, expected, size, owned_directory=None):
    require(NAME.fullmatch(name) and NAME.fullmatch(name)[1] == expected, 'addressed filename differs')
    source = Path(source)
    fd, before = checked_fd(source, expected, size)
    owned = None
    created = False
    existing = None
    verified_target = None
    try:
        owned = owned_directory or open_directory(destination_dir)
        check_directory(owned)
        destfd = owned[0]
        require(content_stamp(before) == content_stamp(os.stat(source, follow_symlinks=False)), 'source replaced before link')
        try:
            os.link(source, name, dst_dir_fd=destfd, follow_symlinks=False)
            created = True
        except FileExistsError:
            existing, verified_target = checked_fd(name, expected, size, dir_fd=destfd)
        after = os.fstat(fd)
        require(content_stamp(before) == content_stamp(after) == content_stamp(os.stat(source, follow_symlinks=False)), 'source content identity changed')
        target = os.stat(name, dir_fd=destfd, follow_symlinks=False)
        require(stat.S_ISREG(target.st_mode), 'destination is not regular')
        if created: require(content_stamp(target) == content_stamp(after), 'new link is not held source inode')
        else: require(stamp(target) == stamp(verified_target) == stamp(os.fstat(existing)), 'verified existing destination changed')
        check_directory(owned)
        require(stamp(after) == stamp(os.fstat(fd)) == stamp(os.stat(source, follow_symlinks=False)), 'source changed after link verification')
        return created
    finally:
        if existing is not None: os.close(existing)
        if owned is not None and owned_directory is None: os.close(owned[0])
        os.close(fd)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidates', type=Path, required=True)
    p.add_argument('--candidates-sha256', required=True)
    p.add_argument('--receipt', type=Path, required=True)
    a = p.parse_args()
    require(not a.receipt.exists(), 'new receipt required')
    plan = read_json(PLAN, PLAN_SHA)
    report = read_json(a.candidates, a.candidates_sha256)
    require(report['schema'] == 'study-full-web-candidates.v1' and report['activation_performed'] is False and report['runtime'] == plan['runtime_sha256'], 'candidate scope differs')
    require(set(report['books']) == set(plan['books']), 'candidate books differ')
    for book, spec in plan['books'].items():
        row = report['books'][book]
        require(row['compiled'] + row['authored'] == spec['expected_total'] and row['accepted_preserved'] is True, 'incomplete book candidate')
        require(row['attachment']['compiled'] == row['compiled'], 'attachment coverage differs')
        live = spec['live_index']; fd, _ = checked_fd(live['path'], live['sha256'], live['bytes']); os.close(fd)
        candidate = row['candidate']
        fd, _ = checked_fd(candidate['path'], candidate['sha256'], candidate['bytes']); os.close(fd)
    receipts = {}
    all_targets = []
    directories = []
    for book, spec in plan['books'].items():
        root = Path(spec['root']); candidate = report['books'][book]
        source_root = Path(candidate['candidate']['path']).parent / 'evidence'
        counts = {'published': 0, 'reused': 0, 'bytes': 0}
        owned = open_directory(root / 'evidence')
        directories.append(owned[1])
        try:
            for item in candidate['new_assets']:
                source = Path(item['path']); name = source.name
                require(source.parent == source_root and Path(item['destination']) == root / 'evidence' / name, 'ledger path escapes its book')
                linked = link_one(source, root / 'evidence', name, item['sha256'], item['bytes'], owned)
                counts['published' if linked else 'reused'] += 1
                counts['bytes'] += item['bytes']
                all_targets.append((item['destination'], item['sha256'], item['bytes']))
            check_directory(owned)
        finally: os.close(owned[0])
        receipts[book] = counts
    # All intentional links have finished, so ctime is stable for this final pass.
    # A reused or earlier-published destination must not change unnoticed while
    # later ledger members are being published.
    verified_targets = []
    for path, expected, size in all_targets:
        fd, state = checked_fd(path, expected, size)
        os.close(fd)
        verified_targets.append((path, stamp(state)))
    for path, state in verified_targets:
        require(stamp(os.stat(path, follow_symlinks=False)) == state, 'destination changed after final SHA verification')
    # No index is changed here, including on partial resource-publication failure.
    for spec in plan['books'].values():
        live = spec['live_index']; fd, _ = checked_fd(live['path'], live['sha256'], live['bytes']); os.close(fd)
    for chain in directories: check_chain(chain)
    result = {'schema': 'study-full-web-resource-publication.v1', 'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'plan_sha256': PLAN_SHA,
              'candidates': {'path': str(a.candidates), 'sha256': a.candidates_sha256}, 'books': receipts,
              'live_indexes_unchanged': True, 'resources_complete': True, 'native_stat_validation_may_start': True}
    with a.receipt.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__': main()
