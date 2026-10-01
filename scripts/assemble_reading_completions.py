"""Join authored complete translations only after independent review covers all IDs."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not __debug__:
        raise RuntimeError('Reading completion review assembly requires validation; optimized Python is unsupported')
    root = Path(__file__).resolve().parents[1]
    directory = root / 'output/reading-completion-review'
    payload = json.loads((directory / 'inputs.json').read_text())
    expected = {row['sentenceId']: row for row in payload['rows']}
    assert len(expected) == len(payload['rows']) == 695
    translations, evidence = {}, {}
    for batch in range(1, 9):
        before = directory / f'author-input-{batch}.json'
        after = directory / f'author-output-{batch}.json'
        inputs, outputs = (json.loads(path.read_text())['rows'] for path in (before, after))
        assert [row['sentenceId'] for row in inputs] == [row['sentenceId'] for row in outputs]
        for original, row in zip(inputs, outputs):
            sid = row['sentenceId']
            assert sid in expected and sid not in translations
            current = expected[sid]
            assert original['originalEnglish'] == current['originalEnglish']
            assert original['optionEnglish'] == current['optionEnglish']
            if original['completedEnglish'] != current['completedEnglish']:
                # Independently reviewed correction of a duplicate terminal period,
                # after a period already enclosed by a closing quote.
                assert sid == 'kaoyan:2019-01:p:b-4-7:new:1'
                assert original['completedEnglish'] == current['completedEnglish'] + '.'
            text = row['translationZh']
            assert isinstance(text, str) and text.strip() == text and text
            assert not any(char in text for char in ('_', '<', '>'))
            translations[sid] = text
        evidence[before.name] = sha(before); evidence[after.name] = sha(after)
    assert translations.keys() == expected.keys()
    reviewed, corrections = set(), []
    for name, batches in (('review-1-3.json', (1, 2, 3)), ('review-4-6.json', (4, 5, 6)),
                          ('review-7-8.json', (7, 8))):
        path = directory / name
        review = json.loads(path.read_text())
        reviewed_files = {f'author-{kind}-{batch}.json': evidence[f'author-{kind}-{batch}.json']
                          for batch in batches for kind in ('input', 'output')}
        assert review.get('evidenceFiles') == reviewed_files, 'Author files changed after semantic review'
        ids = review['reviewedSentenceIds']
        assert not review['blocked'] and len(ids) == len(set(ids))
        assert set(ids) <= expected.keys() and not reviewed.intersection(ids)
        reviewed.update(ids)
        for item in review['corrections']:
            assert item['sentenceId'] in ids and item['reason'].strip()
            assert item['translationZh'].strip() == item['translationZh']
            assert not any(char in item['translationZh'] for char in ('_', '<', '>'))
            translations[item['sentenceId']] = item['translationZh']
            corrections.append(item)
        evidence[name] = sha(path)
    assert reviewed == expected.keys()
    for row in payload['rows']:
        row.update(translationZh=translations[row['sentenceId']], status='reviewed')
    target = root / 'data/reading-completions-v1.json'
    assert not target.is_symlink()
    target.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    os.replace(temporary, target)
    approval = {'schema': 'reading-question-completion-review.v1', 'status': 'approved',
                'sidecarSha256': sha(target), 'indexManifestHash': payload['indexManifestHash'],
                'inputManifestHash': payload['inputManifestHash'],
                'reviewedSentenceIds': sorted(reviewed), 'evidenceFiles': evidence}
    review_target = target.with_suffix('.review.json')
    assert not review_target.is_symlink()
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent, delete=False) as stream:
        json.dump(approval, stream, ensure_ascii=False, indent=2)
        temporary = Path(stream.name)
    os.replace(temporary, review_target)
    report = {'status': 'reviewed', 'method': 'codex_authoring_with_independent_semantic_review',
              'reading_questions': len(expected), 'independently_reviewed_sentences': len(reviewed),
              'corrections': corrections, 'input_sha256': sha(directory / 'inputs.json'),
              'sidecar_sha256': sha(target), 'evidence_files': evidence,
              'approval_sha256': sha(review_target),
              'scope': 'complete translations of answer-filled reading prompts only; original complete translations retained'}
    (directory / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: report[key] for key in ('status', 'reading_questions', 'independently_reviewed_sentences', 'sidecar_sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
