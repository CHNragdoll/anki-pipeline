#!/usr/bin/env python3
"""Read-only SHA/size check of this raw evidence archive."""
from pathlib import Path
import argparse, hashlib, json

def measure(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true", help="also hash indexed external evidence")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "archive-manifest.json").read_text())
    checked = 0
    for row in manifest["copied_original_files"] + manifest["archive_generated_files"]:
        path = root / row["repository_path"]
        if measure(path) != (row["bytes"], row["sha256"]):
            raise SystemExit(f"SHA/size mismatch: {path}")
        checked += 1
    external_count = 0
    if args.external:
        for row in manifest["external_evidence_not_copied"]:
            path = Path(row["source_path"])
            if not path.is_file():
                raise SystemExit(f"External evidence unavailable: {path}")
            if measure(path) != (row["bytes"], row["sha256"]):
                raise SystemExit(f"External SHA/size mismatch: {path}")
            external_count += 1
    print(json.dumps({"copied_files_checked": checked, "external_files_checked": external_count, "archive_status": manifest["status"], "browser_accepted": False}))

if __name__ == "__main__":
    main()
