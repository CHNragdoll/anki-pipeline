"""Read-only evidence and optional current-source check; no test/browser replay."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import sys
import tarfile


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    seal = json.loads((root / 'SEAL.json').read_text())
    for name, pin in seal['files'].items():
        raw = (root / name).read_bytes()
        assert len(raw) == pin['bytes'] and sha(raw) == pin['sha256'], name
    count = 0
    bundles = json.loads((root / 'bundles.json').read_text())
    for name, bundle in bundles.items():
        raw = (root / name).read_bytes()
        assert len(raw) == bundle['bytes'] and sha(raw) == bundle['sha256'], name
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw))) as archive:
            members = archive.getmembers()
            assert len(members) == len({m.name for m in members})
            assert {m.name for m in members} == set(bundle['files'])
            for member in members:
                path = PurePosixPath(member.name)
                assert member.isfile() and not path.is_absolute() and '..' not in path.parts
                content = archive.extractfile(member).read()
                pin = bundle['files'][member.name]
                assert len(content) == pin['bytes'] and sha(content) == pin['sha256'], member.name
                count += 1
    if '--current-source' in sys.argv:
        repo = root.parents[2]
        for name, pin in json.loads((root / 'source-pins.json').read_text()).items():
            raw = (repo / name).read_bytes()
            assert len(raw) == pin['bytes'] and sha(raw) == pin['sha256'], name
    print(f'PASS: {len(bundles)} evidence bundles, {count} exact members; current source checked={"--current-source" in sys.argv}; no replay')


if __name__ == '__main__':main()
