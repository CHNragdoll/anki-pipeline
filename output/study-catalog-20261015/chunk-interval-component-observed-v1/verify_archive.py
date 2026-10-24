"""Verify the small immutable evidence archive without replaying browser work."""
from pathlib import Path
import gzip
import hashlib
import io
import json
import tarfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    root = Path(__file__).resolve().parent
    seal = json.loads((root / "SEAL.json").read_text())
    for name, pin in seal["files"].items():
        raw = (root / name).read_bytes()
        assert len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], name
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress((root / "pilot-files.tar.gz").read_bytes()))) as archive:
        members = archive.getmembers()
        assert all(m.isfile() and "/" not in m.name for m in members)
        assert len({m.name for m in members}) == len(members)
        source_seal = archive.extractfile("FROZEN.json").read()
        assert sha(source_seal) == "452246240a5a07c7aed23080472bb45dc0b70246b61de0e602bf8a8f5f784f2e"
        pins = json.loads(source_seal)["files"]
        assert {m.name for m in members} == set(pins) | {"FROZEN.json"}
        for name, pin in pins.items():
            raw = archive.extractfile(name).read()
            assert len(raw) == pin["bytes"] and sha(raw) == pin["sha256"], name
    closed = json.loads(next((root / "server").glob("closed-*.json")).read_text())
    assert closed["state"] == "closed" and closed["drained"]
    assert closed["used_sources_unchanged"]
    assert len(closed["used_source_checks"]) == 38
    assert all(item["source_unchanged"] for item in closed["used_source_checks"])
    print("PASS: sealed evidence, 63 exact pilot files, 38 used-source closing checks; no browser/runtime replay")


if __name__ == "__main__":
    main()
