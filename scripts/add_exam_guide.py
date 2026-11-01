"""Append a usage guide after the shared exam catalog APKG export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Also support `python scripts/add_exam_guide.py ...` from a source checkout.
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anki_pipeline.study_exam_guide import add_guide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('target', type=Path)
    parser.add_argument('--book-id', required=True, help='Immutable catalog book ID')
    parser.add_argument('--root', required=True, help='Top-level deck name')
    parser.add_argument('--questions', type=int, required=True)
    parser.add_argument('--html', type=Path, required=True, help='UTF-8 guide answer HTML')
    parser.add_argument('--title')
    args = parser.parse_args()
    report = add_guide(args.source, args.target, book_id=args.book_id, root=args.root,
                       question_count=args.questions, guide_html=args.html.read_text(encoding='utf-8'),
                       title=args.title)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
