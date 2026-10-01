"""Reviewed candidate translations with complete source and review provenance.

This module only loads approved derived text. It never authors translations or
changes the immutable sentence index, original translations or source databases.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .reading_completion import _HASH, _require, _sha, _unique_object, complete_english


SCHEMA = 'reading-option-translations.v1'
REVIEW_SCHEMA = 'reading-option-translation-review.v1'
TARGET_SCOPE = 'separate_approved_question_and_candidate_translations'
PRESERVED_SCOPES = {'reviewed_correct_completion', 'approved_context_with_reviewed_correct_completion'}
_OUTPUT_FIELDS = {'translationZh', 'translationHash', 'translationScope',
                  'newTranslationAuthored', 'translation_alignment'}
_SOURCE_FIELDS = {'sentenceId', 'optionSentenceIds', 'optionParagraphId', 'paperId',
    'questionId', 'answerNumber', 'candidateOptionLabel', 'correctOptionLabel',
    'isCorrectCandidate', 'answerSource', 'structuredPaperHash', 'originalQuestionEnglish',
    'questionEnglish', 'originalQuestionChinese', 'stemSentenceRefs', 'optionSentenceRefs',
    'optionText', 'optionTextHash', 'hasQuestionBlank', 'completedEnglish', 'insertedRange',
    'englishHash', 'reviewedCompletionSentenceId', 'indexFileHash', 'reviewedInputHash',
    'reviewedTranslationHash', 'reviewHash'}
_REF_FIELDS = {'sentenceId', 'paragraphId', 'range', 'english', 'translationZh',
    'englishHash', 'translationHash', 'sourceHash', 'reviewedContentHash', 'sourceBlockIds'}
_INPUT_FIELDS = {'sentenceId', 'contextHash', 'questionId', 'candidateOptionLabel',
    'hasQuestionBlank', 'completedEnglish', 'questionEnglish', 'questionChinese',
    'optionEnglish', 'optionChinese'}
_LABEL = re.compile(r'(?:题干|选项)\s*(?:[A-DＡ-Ｄ]\s*)?[:：]|[［【\[]\s*(?:选项|[A-DＡ-Ｄ])\s*[］】\]]')
_NUMBER = re.compile(r'^\s*(?:[0-9]+\s*[.)、．]|[（(][0-9]+[）)])')
_EVIDENCE_NAME = re.compile(r'(?:author-(?:input|output)-[0-9]{2}|reviewer-[0-9]{2})\.json\Z')


def _canonical_hash(value):
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def context_hash(context):
    """Hash source-only fields, so the new translation cannot hash itself."""
    _require(isinstance(context, dict) and _SOURCE_FIELDS <= context.keys(),
             'Reading option translation lacks source context fields')
    return _canonical_hash({key: context[key] for key in _SOURCE_FIELDS})


def _without_number(text, number):
    return re.sub(r'^\s*(?:' + re.escape(number) + r'\s*[.)、]|[（(]' +
                  re.escape(number) + r'[）)])\s*', '', text, count=1)


def validate_translation(text, context):
    """Reject display artifacts; semantic acceptance comes from independent review."""
    _require(isinstance(text, str) and bool(text) and text == text.strip()
             and not any(char in text for char in '\r\n\t_<>')
             and not re.search(r'\s{2,}|[\x00-\x1f\x7f]', text)
             and not _LABEL.search(text) and not _NUMBER.search(text)
             and not re.search(r'［.*?］|\[\s*(?:空白|blank|placeholder).*?\]', text, re.I),
             'Reading option translation contains blank, label, number or markup')
    if not context['hasQuestionBlank'] and '?' in context['questionEnglish']:
        _require('？' in text or '?' in text,
                 'Reading option translation must retain the original question')


def _verify_refs(refs, source, paper_id, paragraph_id=None):
    _require(isinstance(refs, list) and bool(refs), 'Reading option source references are missing')
    cursor, seen, paragraph = 0, set(), None
    for ref in refs:
        _require(isinstance(ref, dict) and set(ref) == _REF_FIELDS,
                 'Reading option source reference has unknown or missing fields')
        sid, span = ref['sentenceId'], ref['range']
        _require(isinstance(sid, str) and sid.startswith(paper_id + ':') and sid not in seen
                 and isinstance(span, list) and len(span) == 2
                 and all(type(value) is int for value in span)
                 and cursor <= span[0] < span[1] <= len(source)
                 and not source[cursor:span[0]].strip()
                 and source[span[0]:span[1]] == ref['english']
                 and isinstance(ref['translationZh'], str) and bool(ref['translationZh'])
                 and ref['englishHash'] == _sha(ref['english'])
                 and ref['translationHash'] == _sha(ref['translationZh'])
                 and ref['sourceHash'] == _sha(source)
                 and isinstance(ref['reviewedContentHash'], str) and _HASH.fullmatch(ref['reviewedContentHash']),
                 'Reading option source reference text, range or hash mismatch')
        _require(isinstance(ref['paragraphId'], str)
                 and (paragraph is None or paragraph == ref['paragraphId'])
                 and (paragraph_id is None or paragraph_id == ref['paragraphId'])
                 and isinstance(ref['sourceBlockIds'], list) and bool(ref['sourceBlockIds'])
                 and all(isinstance(block, str) and block.startswith(paper_id + ':')
                         for block in ref['sourceBlockIds']),
                 'Reading option source reference paragraph/block mismatch')
        paragraph, cursor = ref['paragraphId'], span[1]
        seen.add(sid)
    _require(not source[cursor:].strip(), 'Reading option source references leave uncovered text')


def author_input(context):
    return {'sentenceId': context['sentenceId'], 'contextHash': context_hash(context),
        'questionId': context['questionId'], 'candidateOptionLabel': context['candidateOptionLabel'],
        'hasQuestionBlank': context['hasQuestionBlank'], 'completedEnglish': context['completedEnglish'],
        'questionEnglish': context['questionEnglish'], 'questionChinese': context['originalQuestionChinese'],
        'optionEnglish': context['optionText'],
        'optionChinese': ''.join(ref['translationZh'] for ref in context['optionSentenceRefs'])}


def expected_translations(context_registry, index_report, registry_sha256):
    """Validate the current registry and create a source-only expected manifest."""
    _require(isinstance(context_registry, list) and isinstance(index_report, dict)
             and isinstance(registry_sha256, str) and _HASH.fullmatch(registry_sha256),
             'Invalid reading option translation source inventory')
    source_files = index_report.get('source_files')
    _require(isinstance(source_files, dict), 'Reading option translation index files are missing')
    targets, preserved, contexts, seen = {}, [], [], set()
    for row in context_registry:
        _require(isinstance(row, dict) and set(row) == _SOURCE_FIELDS | _OUTPUT_FIELDS,
                 'Reading option translation context has unknown or missing fields')
        sid = row['sentenceId']
        _require(isinstance(sid, str) and sid not in seen
                 and isinstance(row['translationScope'], str)
                 and row['translationScope'] in PRESERVED_SCOPES | {TARGET_SCOPE},
                 'Duplicate, unknown or already modified reading option context')
        seen.add(sid)
        paper, number = row['paperId'], row['answerNumber']
        _require(isinstance(paper, str) and re.fullmatch(r'kaoyan:[0-9]{4}-0[12]', paper)
                 and isinstance(number, str) and re.fullmatch(r'[1-9][0-9]*', number)
                 and isinstance(row['questionId'], str)
                 and re.fullmatch(re.escape(paper) + ':q-' + number + '-[1-9][0-9]*', row['questionId'])
                 and isinstance(row['candidateOptionLabel'], str) and row['candidateOptionLabel'] in {'A', 'B', 'C', 'D'}
                 and isinstance(row['correctOptionLabel'], str) and row['correctOptionLabel'] in {'A', 'B', 'C', 'D'}
                 and type(row['isCorrectCandidate']) is bool
                 and row['isCorrectCandidate'] == (row['candidateOptionLabel'] == row['correctOptionLabel'])
                 and type(row['hasQuestionBlank']) is bool,
                 'Reading option translation candidate identity mismatch')
        for field in ('originalQuestionEnglish', 'questionEnglish', 'originalQuestionChinese',
                      'optionText', 'completedEnglish', 'translationZh'):
            _require(isinstance(row[field], str) and bool(row[field]),
                     'Reading option translation source text is missing')
        _verify_refs(row['stemSentenceRefs'], row['originalQuestionEnglish'], paper)
        _verify_refs(row['optionSentenceRefs'], row['optionText'], paper, row['optionParagraphId'])
        _require(row['optionSentenceIds'] == [ref['sentenceId'] for ref in row['optionSentenceRefs']]
                 and sid == row['optionSentenceIds'][0]
                 and row['optionParagraphId'] == row['questionId'] + ':' + row['candidateOptionLabel']
                 and row['questionEnglish'] == _without_number(row['originalQuestionEnglish'], number)
                 and row['originalQuestionChinese'] == ''.join(
                     _without_number(ref['translationZh'], number) for ref in row['stemSentenceRefs']
                     if _without_number(ref['english'], number).strip()),
                 'Reading option translation source sentence identity or Chinese mismatch')
        has_blank = bool(re.search(r'_{2,}', row['questionEnglish']))
        _require(row['hasQuestionBlank'] == has_blank, 'Reading option translation blank identity mismatch')
        if has_blank:
            completed, _, inserted = complete_english(row['questionEnglish'], row['optionText'])
        else:
            completed = row['questionEnglish'] + '\n\n' + row['optionText']
            start = len(row['questionEnglish']) + 2
            inserted = [start, start + len(row['optionText'].rstrip('.!?'))]
        _require(row['completedEnglish'] == completed and row['insertedRange'] == inserted
                 and row['englishHash'] == _sha(completed)
                 and row['optionTextHash'] == _sha(row['optionText'])
                 and row['translationHash'] == _sha(row['translationZh']),
                 'Reading option translation completed English or source hash mismatch')
        name = paper.split(':')[1] + '.json'
        for key, directory in (('indexFileHash', 'index'), ('reviewedInputHash', 'inputs'),
                               ('reviewedTranslationHash', 'translations'), ('reviewHash', 'reviews')):
            _require(row[key] == source_files.get(directory + '/' + name)
                     and isinstance(row[key], str) and _HASH.fullmatch(row[key]),
                     'Reading option translation has stale reviewed source files')
        _require(isinstance(row['structuredPaperHash'], str) and _HASH.fullmatch(row['structuredPaperHash']),
                 'Reading option translation structured source hash is invalid')
        contexts.append({'sentenceId': sid, 'contextHash': context_hash(row)})
        if row['translationScope'] == TARGET_SCOPE:
            targets[sid] = row
        else:
            _require(row['isCorrectCandidate'], 'Reading option translation excludes an unreviewed distractor')
            preserved.append({key: row[key] for key in ('sentenceId', 'translationZh',
                                                       'translationHash', 'translationScope')})
    header = {'schema': SCHEMA, 'sourceRegistrySha256': registry_sha256,
        'indexManifestHash': index_report.get('manifest_sha256'),
        'inputManifestHash': index_report.get('input_manifest_sha256'),
        'contextManifestHash': _canonical_hash(sorted(contexts, key=lambda row: row['sentenceId'])),
        'preservedTranslationsHash': _canonical_hash(sorted(preserved, key=lambda row: row['sentenceId'])),
        'excludedSentenceIds': sorted(row['sentenceId'] for row in preserved)}
    _require(all(isinstance(header[key], str) and _HASH.fullmatch(header[key])
                 for key in ('indexManifestHash', 'inputManifestHash')),
             'Reading option translation source manifest hashes are invalid')
    return header, targets


def _read_json(path):
    try:
        raw = path.read_bytes()
        return json.loads(raw, object_pairs_hook=_unique_object), _sha(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Reading option translation file is unavailable or invalid: {path.name}') from exc


def validate_evidence(directory, evidence, expected, registry_sha256):
    """Reconcile every reviewed output, correction and exact author file hash."""
    directory = Path(directory).resolve()
    _require(isinstance(evidence, dict) and bool(evidence)
             and all(isinstance(name, str) and _EVIDENCE_NAME.fullmatch(name)
                     and isinstance(digest, str) and _HASH.fullmatch(digest)
                     for name, digest in evidence.items()),
             'Reading option translation evidence names or hashes are invalid')
    loaded, watched = {}, {}
    for name, digest in evidence.items():
        path = directory / name
        _require(path.resolve().parent == directory, 'Reading option translation evidence escapes directory')
        value, actual = _read_json(path)
        _require(actual == digest, 'Reading option translation author/reviewer evidence changed')
        loaded[name], watched[path] = value, digest
    translations, batches, authored_ids = {}, {}, set()
    for name in sorted(loaded):
        if not name.startswith('author-input-'):
            continue
        source = loaded[name]
        output_name = name.replace('author-input-', 'author-output-', 1)
        _require(output_name in loaded, 'Reading option translation author output evidence is missing')
        output = loaded[output_name]
        batch = int(name[-7:-5])
        _require(isinstance(source, dict) and set(source) == {'schema', 'batch', 'registrySha256', 'rows'}
                 and source['schema'] == 'reading-option-translation-author-input.v1'
                 and source['batch'] == batch and source['registrySha256'] == registry_sha256
                 and isinstance(output, dict) and set(output) == {'schema', 'batch', 'rows'}
                 and output['schema'] == 'reading-option-translation-author-output.v1'
                 and output['batch'] == batch and isinstance(source['rows'], list)
                 and bool(source['rows']) and isinstance(output['rows'], list)
                 and len(source['rows']) == len(output['rows']),
                 'Reading option translation author evidence schema/coverage mismatch')
        ids = []
        for original, authored in zip(source['rows'], output['rows']):
            _require(isinstance(original, dict) and set(original) == _INPUT_FIELDS
                     and isinstance(original['sentenceId'], str) and original['sentenceId'] in expected
                     and original == author_input(expected[original['sentenceId']])
                     and isinstance(authored, dict) and set(authored) == {'sentenceId', 'translationZh'}
                     and authored['sentenceId'] == original['sentenceId']
                     and authored['sentenceId'] not in authored_ids,
                     'Reading option translation author evidence has stale, duplicate or unknown sentence')
            sid = authored['sentenceId']
            validate_translation(authored['translationZh'], expected[sid])
            translations[sid] = authored['translationZh']
            authored_ids.add(sid); ids.append(sid)
        batches[batch] = ids
    _require(authored_ids == set(expected), 'Reading option translation authors do not cover every candidate')
    reviewed, reviewed_batches, corrected = set(), set(), set()
    review_names = [name for name in loaded if name.startswith('reviewer-')]
    _require(bool(review_names), 'Reading option translation has no independent semantic review')
    for name in sorted(review_names):
        review = loaded[name]
        fields = {'schema', 'reviewer', 'authorBatches', 'evidenceFiles', 'reviewedSentenceIds', 'corrections', 'blocked'}
        _require(isinstance(review, dict) and set(review) == fields
                 and review['schema'] == 'reading-option-translation-semantic-review.v1'
                 and review['reviewer'] == name[:-5].replace('-', '_')
                 and review['blocked'] == [] and isinstance(review['authorBatches'], list)
                 and bool(review['authorBatches']) and all(type(batch) is int for batch in review['authorBatches'])
                 and len(review['authorBatches']) == len(set(review['authorBatches']))
                 and all(batch in batches and batch not in reviewed_batches for batch in review['authorBatches']),
                 'Reading option translation review is blocked or has invalid batch coverage')
        ids = [sid for batch in review['authorBatches'] for sid in batches[batch]]
        files = {f'author-{kind}-{batch:02d}.json': evidence[f'author-{kind}-{batch:02d}.json']
                 for batch in review['authorBatches'] for kind in ('input', 'output')}
        _require(review['evidenceFiles'] == files and isinstance(review['reviewedSentenceIds'], list)
                 and all(isinstance(sid, str) for sid in review['reviewedSentenceIds'])
                 and len(review['reviewedSentenceIds']) == len(set(review['reviewedSentenceIds']))
                 and set(review['reviewedSentenceIds']) == set(ids) and not reviewed.intersection(ids)
                 and isinstance(review['corrections'], list),
                 'Reading option translation reviewer is stale or lacks exact sentence coverage')
        for item in review['corrections']:
            _require(isinstance(item, dict) and set(item) == {'sentenceId', 'translationZh', 'reason'}
                     and isinstance(item['sentenceId'], str)
                     and item['sentenceId'] in ids and item['sentenceId'] not in corrected
                     and isinstance(item['reason'], str) and bool(item['reason'].strip()),
                     'Reading option translation correction is duplicate, unbound or unexplained')
            sid = item['sentenceId']
            validate_translation(item['translationZh'], expected[sid])
            translations[sid] = item['translationZh']; corrected.add(sid)
        reviewed.update(ids); reviewed_batches.update(review['authorBatches'])
    _require(reviewed == set(expected) and reviewed_batches == set(batches),
             'Reading option translation semantic review is incomplete')
    needed = {f'author-{kind}-{batch:02d}.json' for batch in batches for kind in ('input', 'output')}
    _require(set(evidence) == needed | set(review_names), 'Reading option translation has extraneous evidence files')
    return translations, watched, len(corrected)


def load_option_translations(path: Path, context_registry: list[dict], index_report: dict):
    """Return sentence-ID to approved text, watched hashes and source counts.

    The sidecar belongs in the data directory. Its approved evidence files live
    in the sibling output/reading-option-translation-review directory. No old
    generated context registry is read during production loading.
    """
    path = Path(path)
    payload, sidecar_hash = _read_json(path)
    _require(isinstance(payload, dict), 'Reading option translation sidecar must be an object')
    header, expected = expected_translations(context_registry, index_report, payload.get('sourceRegistrySha256'))
    _require(set(payload) == set(header) | {'rows'} and all(payload.get(key) == value for key, value in header.items()),
             'Reading option translation sidecar has unknown fields or stale context inventory')
    review_path = path.with_suffix('.review.json')
    approval, approval_hash = _read_json(review_path)
    fields = set(header) - {'schema'} | {'schema', 'status', 'sidecarSha256', 'reviewedSentenceIds', 'evidenceFiles'}
    _require(isinstance(approval, dict) and set(approval) == fields
             and approval['schema'] == REVIEW_SCHEMA and approval['status'] == 'approved'
             and approval['sidecarSha256'] == sidecar_hash
             and all(approval.get(key) == value for key, value in header.items() if key != 'schema'),
             'Reading option translation approval is missing, stale or has unknown fields')
    ids = approval['reviewedSentenceIds']
    _require(isinstance(ids, list) and all(isinstance(sid, str) for sid in ids)
             and len(ids) == len(set(ids)) and set(ids) == set(expected),
             'Reading option translation approval must cover exactly every current candidate')
    accepted, watched, corrections = validate_evidence(
        path.parent.parent / 'output/reading-option-translation-review',
        approval['evidenceFiles'], expected, header['sourceRegistrySha256'])
    rows = payload['rows']
    _require(isinstance(rows, list) and len(rows) == len(expected),
             'Reading option translation sidecar candidate coverage is incomplete')
    result = {}
    for row in rows:
        _require(isinstance(row, dict) and set(row) == {'sentenceId', 'contextHash', 'englishHash',
                 'translationZh', 'translationHash', 'status'} and isinstance(row['sentenceId'], str)
                 and row['sentenceId'] in expected
                 and row['sentenceId'] not in result, 'Reading option translation row has unknown fields or duplicate identity')
        sid, source = row['sentenceId'], expected[row['sentenceId']]
        _require(row['status'] == 'reviewed' and row['contextHash'] == context_hash(source)
                 and row['englishHash'] == _sha(source['completedEnglish'])
                 and row['translationZh'] == accepted[sid]
                 and row['translationHash'] == _sha(row['translationZh']),
                 'Reading option translation row has stale source or unapproved text')
        validate_translation(row['translationZh'], source)
        result[sid] = row['translationZh']
    watched[path] = sidecar_hash; watched[review_path] = approval_hash
    _require(all(_sha(watched_path.read_bytes()) == digest for watched_path, digest in watched.items()),
             'Reading option translation evidence changed during loading')
    return result, watched, {'joined_candidate_translations': len(result),
        'independently_reviewed_candidates': len(ids), 'semantic_corrections': corrections,
        'preserved_reviewed_translations': len(header['excludedSentenceIds']),
        'new_translations': len(result), 'sidecar_sha256': sidecar_hash, 'approval_sha256': approval_hash,
        'translation_scope': 'independently_reviewed_complete_candidate_translation',
        'word_alignments_added': 0, 'chinese_target_marking': 'disabled'}
