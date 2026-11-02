"""Adapt a read-only reflow question bank to the common catalog input format."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_pipeline.study_exam_source import read_bank
from anki_pipeline.study_exam_package import source_package


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--database',required=True,type=Path)
    p.add_argument('--structured-root',required=True,type=Path)
    p.add_argument('--asset-root',required=True,type=Path)
    p.add_argument('--category',required=True)
    p.add_argument('--book-id',required=True)
    p.add_argument('--title',required=True)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--asset-overrides',type=Path)
    p.add_argument('--label',action='append',default=[],metavar='TYPE=LABEL')
    a=p.parse_args();labels={}
    for item in a.label:
        kind,separator,label=item.partition('=')
        if not separator or kind in labels:p.error('each --label must uniquely specify TYPE=LABEL')
        labels[kind]=label
    a.output.mkdir(parents=True,exist_ok=True)
    snapshot=read_bank(a.database,a.category,structured_root=a.structured_root,asset_root=a.asset_root,
                       asset_overrides=json.loads(a.asset_overrides.read_text()) if a.asset_overrides else None,
                       type_labels=labels)
    (a.output/'source-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False))
    report=source_package(snapshot,a.output/'source.apkg',book_id=a.book_id,title=a.title)
    report.update(question_types=dict(Counter(q['type'] for q in snapshot['questions'])),
                  answer_statuses=dict(Counter(q['status'] for q in snapshot['questions'])))
    (a.output/'source-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
