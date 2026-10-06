"""Read-only APKG subset export; execute from the repository or installed env."""
import argparse
import json
from pathlib import Path

from anki_pipeline.apkg_subset import export_subset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--deck", action="append", required=True, help="Exact subtree name; repeat to retain multiple subtrees")
    parser.add_argument("--guide-fields", type=Path, help="Optional JSON: guide note ID -> [Title, Overview, Guide]")
    args = parser.parse_args()
    replacements = json.loads(args.guide_fields.read_text()) if args.guide_fields else None
    try:
        report = export_subset(args.source, args.destination, args.deck, guide_fields=replacements)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
