"""Publish local derived candidate text only after complete independent review."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_pipeline.codex_exam_index import load_codex_exam_index
from anki_pipeline.option_context import prepare_option_contexts
from anki_pipeline.option_translation import (
    REVIEW_SCHEMA, context_hash, expected_translations, load_option_translations, validate_evidence,
)
from anki_pipeline.reading_completion import _require, _sha, _unique_object, load_reading_completions

REGISTRY_SHA = '96c06918c8b7677b5fc545006b05d6ad4463d8424acd755102acbced19e3ae52'
INDEX_SHA = '9972635fdecd6c8a7c0663872e74f8aec0f7d3f5fc3d258921e28b0ce1910244'
COMPLETION_SHA = '4ed48d871a0ffffda2d0f1b8919170301cdbb88fe61d2ffa73df89a51a6bfc4a'
COMPLETION_REVIEW_SHA = 'ae64c6033e93d2f63de8234347bed3d200a61f3c87becf7664f05a616ffd7085'
DATABASE_PINS = {
    'data/anki.sqlite3': '5e0be927903a40d0fb5e33469ce86d4f6eb50b5486e3c0779edf04b56fae87dc',
    '../anki_template/V2.0/anki_data.db': '8dc5264b78b845df7308807ed1fd4ba9a70d5eba0f5cf76258f1b5cb3994f210',
    '../exam-library/data/question-bank.sqlite3': '7a80f4322c956419759ca00f88a0038c117e10983dde979f9a00101364894d86',
}


def source_pins(root):
    pins = {**DATABASE_PINS,
        'output/reading-option-translation-review/source-context-registry.json': REGISTRY_SHA,
        'data/reading-completions-v1.json': COMPLETION_SHA,
        'data/reading-completions-v1.review.json': COMPLETION_REVIEW_SHA,
        '../exam-library/data/staging/codex-translations-v1/index/manifest.json': INDEX_SHA}
    actual = {}
    for name, expected in pins.items():
        digest = _sha((root / name).read_bytes())
        _require(digest == expected, f'Immutable reading option source changed: {name}')
        actual[name] = digest
    return actual


def _atomic_json(path, value):
    _require(not path.is_symlink(), 'Reading option translation output must not be a symlink')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            temporary = Path(stream.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def assemble(root=ROOT):
    root = Path(root).resolve(strict=True)
    before = source_pins(root)
    registry_file = json.loads((root / 'output/reading-option-translation-review/source-context-registry.json').read_bytes(),
                               object_pairs_hook=_unique_object)
    sentences, report = load_codex_exam_index(root.parent / 'exam-library/data/staging/codex-translations-v1')
    completions, _, _ = load_reading_completions(root, root / 'data/reading-completions-v1.json', sentences, report)
    _, structured_watched, _, registry = prepare_option_contexts(root, sentences, report, completions)
    _require(registry == registry_file['rows'], 'Current reading context no longer matches immutable authoring baseline')
    header, expected = expected_translations(registry, report, REGISTRY_SHA)
    _require(len(expected) == 2614 and len(header['excludedSentenceIds']) == 637,
             'Reading option translation approved scope changed')
    directory = root / 'output/reading-option-translation-review'
    names = [f'author-{kind}-{batch:02d}.json' for batch in range(1, 17) for kind in ('input', 'output')]
    names.extend(f'reviewer-{reviewer:02d}.json' for reviewer in range(1, 9))
    evidence = {name: _sha((directory / name).read_bytes()) for name in names}
    translations, _, corrections = validate_evidence(directory, evidence, expected, REGISTRY_SHA)
    payload = {**header, 'rows': [
        {'sentenceId': sid, 'contextHash': context_hash(row), 'englishHash': _sha(row['completedEnglish']),
         'translationZh': translations[sid], 'translationHash': _sha(translations[sid]), 'status': 'reviewed'}
        for sid, row in expected.items()]}
    sidecar = root / 'data/reading-option-translations-v1.json'
    _atomic_json(sidecar, payload)
    approval = {**header, 'schema': REVIEW_SCHEMA, 'status': 'approved',
        'sidecarSha256': _sha(sidecar.read_bytes()), 'reviewedSentenceIds': sorted(expected), 'evidenceFiles': evidence}
    _atomic_json(sidecar.with_suffix('.review.json'), approval)
    loaded, watched, counts = load_option_translations(sidecar, registry, report)
    _require(loaded == translations and source_pins(root) == before,
             'Reading option translation reconciliation or immutable source check failed')
    _require(all(_sha(path.read_bytes()) == digest for path, digest in watched.items()),
             'Reading option translation evidence changed during assembly')
    source_directory = root.parent / 'exam-library/data/staging/codex-translations-v1'
    _require(all(_sha(path.read_bytes()) == digest for path, digest in structured_watched.items())
             and all(_sha((source_directory / name).read_bytes()) == digest
                     for name, digest in report['source_files'].items()),
             'Reading option translation original structured/index sources changed during assembly')
    summary = {'schema': 'reading-option-translation-assembly-report.v1', 'status': 'approved',
        'method': '16_codex_authors_with_8_independent_full_semantic_reviews',
        **counts, 'author_batches': 16, 'independent_reviewers': 8,
        'filled_candidate_sentences': sum(row['hasQuestionBlank'] for row in expected.values()),
        'question_plus_candidate_paragraphs': sum(not row['hasQuestionBlank'] for row in expected.values()),
        'original_contexts_checked': len(registry),
        'original_sentence_refs_checked': sum(len(row['stemSentenceRefs']) + len(row['optionSentenceRefs'])
                                              for row in registry),
        'structured_papers_checked': len(structured_watched),
        'original_reviewed_index_files_checked': len(report['source_files']),
        'sourcePins': before, 'evidenceFiles': evidence,
        'correct637_preserved_exactly': True, 'original_index_structured_sources_and_databases_modified': False,
        'alignment_policy': 'no_new_alignment_or_chinese_highlighting',
        'scope': '2614 candidate translations only; source index and 695 approved completions remain immutable'}
    _atomic_json(directory / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    value = assemble()
    print(json.dumps({key: value[key] for key in ('status', 'joined_candidate_translations',
        'independently_reviewed_candidates', 'semantic_corrections', 'sidecar_sha256')}, ensure_ascii=False))
