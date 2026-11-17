"""Collect and compare complete public fork lists in private staging files."""

import argparse
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import json

from project_metrics import REPO, api, write_json


def collect_forks():
    for _ in range(2):
        try:
            rows = api(f"repos/{REPO}/forks?per_page=100", paginate=True)
            count = api(f"repos/{REPO}")["forks_count"]
            forks = [
                {"id": row["id"], "full_name": row["full_name"],
                 "owner_id": row["owner"]["id"], "created_at": row["created_at"]}
                for row in rows
            ]
            if len(forks) == count == len({row["id"] for row in forks}) and all(
                type(row["id"]) is int and row["id"] > 0
                and type(row["owner_id"]) is int and row["owner_id"] > 0
                and re.fullmatch(r"[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+", row["full_name"])
                and datetime.fromisoformat(row["created_at"]).utcoffset() is not None
                for row in forks
            ):
                return sorted(forks, key=lambda row: row["id"])
        except (RuntimeError, subprocess.TimeoutExpired, KeyError, TypeError, ValueError):
            continue
    return None


def record_forks(forks, previous, timestamp):
    sample = {"collected_at": timestamp, "forks": forks}
    if previous is not None and forks is not None:
        old = {row["id"]: row for row in previous["forks"]}
        new = {row["id"]: row for row in forks}
        sample["changes"] = {
            "previous_at": previous["collected_at"],
            "previous_count": len(old),
            "added": [new[key] for key in sorted(new.keys() - old.keys())],
            "removed": [old[key] for key in sorted(old.keys() - new.keys())],
        }
    return sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text()) if args.previous.exists() else None
    forks = collect_forks()
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json(args.archive, record_forks(forks, previous, timestamp))
    if forks is None:
        print("::warning::Incomplete Fork list. The last complete list is preserved.")


if __name__ == "__main__":
    main()
