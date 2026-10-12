"""Strict independent consumer for source-approved reading display projections.

Only load_approved_inputs creates an opaque replay cache. Parent rows must be
validated before review reassignment, and proposed views are regenerated from
live reviewed sources rather than trusted from the sidecar.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache
from anki_pipeline import sense_display as sd
from anki_pipeline.codex_exam_index import _expected_sentences, _PAPER_IDS, _COUNT_FIELDS, _INPUT_COUNTS, _counts, _rows
from anki_pipeline.reading_completion import prepare_reading_completions, _approved_completion_review
from anki_pipeline.option_context import prepare_option_contexts
from anki_pipeline.sentence_insertion import prepare_sentence_insertions

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def require(condition, message):
    if not condition: raise ValueError(message)

def stat_pin(path):
    value = Path(path).stat()
    return {key: getattr(value, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}

def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key: ' + key); result[key] = value
    return result

def read_materialized(path, watched):
    path = Path(path).resolve(strict=True)
    before = path.stat()
    require(not getattr(before, 'st_flags', 0) & 0x40000000, 'dataless source; hydration is not authorized: ' + str(path))
    raw = path.read_bytes()
    require(stat_pin(path) == {key: getattr(before, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')},
            'source changed while reading: ' + str(path))
    checksum = sha(raw)
    require(str(path) not in watched or watched[str(path)] == checksum, 'source changed during replay: ' + str(path))
    watched[str(path)] = checksum
    return json.loads(raw, object_pairs_hook=unique), checksum

def eligible_reading(row):
    evidence = row.get('source_provenance', {}).get('sourcePathEvidence', {})
    return evidence.get('kind') == 'answer_option' and 'Reading Comprehension' in evidence.get('sourcePath', '')

def physical_row_sha256(row):
    return sha(canonical({key: value for key, value in row.items() if key != 'display'}))

def load_paper_sources(exam_root, staging, paper_id, *, completion_path):
    """Replay one materialized paper against its complete approved manifests.

    Uses the same _expected_sentences, completion and option producers as
    sense_display._load_sources, while never hydrating unrelated papers.
    """
    root, staging = Path(exam_root).resolve(strict=True), Path(staging).resolve(strict=True)
    watched = {}
    manifest, manifest_sha = read_materialized(staging / 'index/manifest.json', watched)
    inventory, inventory_sha = read_materialized(staging / 'manifest.json', watched)
    require(manifest.get('schema') == 'codex-exam-sentence-index-manifest.v1' and manifest.get('scope') == 'full'
            and manifest.get('semanticReviewStatus') == 'approved' and manifest['inputManifestHash'] == inventory_sha,
            'approved complete index manifest binding differs')
    manifest_rows = _rows(manifest.get('papers'), 'manifest papers')
    inventory_rows = _rows(inventory.get('papers'), 'input inventory')
    for collection, count_keys, totals_keys in (
            (manifest_rows, _COUNT_FIELDS, ('papers', *_COUNT_FIELDS)),
            (inventory_rows, _INPUT_COUNTS, _INPUT_COUNTS)):
        identities = [row.get('paperId') for row in collection]
        require(set(identities) == _PAPER_IDS and len(identities) == len(set(identities)),
                'complete manifest must contain every paper once')
        for record in collection:
            _counts(record, count_keys, 'manifest paper')
        expected_totals = {key: sum(row[key] for row in collection) for key in count_keys}
        if 'papers' in totals_keys:
            expected_totals['papers'] = len(collection)
        actual_totals = manifest['totals'] if 'papers' in totals_keys else inventory['totals']
        require(actual_totals == expected_totals, 'complete manifest totals differ')
    require(inventory.get('schema') == 'codex-exam-translation-manifest.v1', 'input manifest schema differs')
    require(all(row.get('indexFile') == row['paperId'].split(':')[1] + '.json'
                and row.get('semanticReviewStatus') == 'approved' for row in manifest_rows),
            'index manifest path or approval differs')
    require(all(row.get('file') == 'inputs/' + row['paperId'].split(':')[1] + '.json'
                for row in inventory_rows), 'input manifest path differs')
    rows = [row for row in manifest_rows if row['paperId'] == paper_id]
    native = [row for row in inventory['papers'] if row['paperId'] == paper_id]
    require(len(rows) == len(native) == 1 and rows[0]['semanticReviewStatus'] == 'approved', 'paper has no unique approved manifest entry')
    paper = rows[0]; name = paper_id.split(':')[1]; values, source_files = {}, {}
    for lane, field in (('inputs', 'inputHash'), ('translations', 'translationHash'), ('reviews', 'reviewHash'), ('index', 'indexHash')):
        value, checksum = read_materialized(staging / lane / (name + '.json'), watched)
        require(checksum == paper[field], 'approved paper source hash differs: ' + lane)
        values[lane] = value; source_files[lane + '/' + name + '.json'] = checksum
    require(native[0]['sha256'] == paper['inputHash'] and values['inputs'].get('paperId') == paper_id,
            'native input inventory hash or identity differs')
    review = values['reviews']; require(review.get('approved') is True and review.get('issues') == []
        and review.get('paperId') == paper_id and review.get('inputHash') == paper['inputHash']
        and review.get('translationHash') == paper['translationHash'], 'paper semantic approval differs')
    def described(part):
        return ((isinstance(part, str) and bool(part.strip())) or
                (isinstance(part, list) and bool(part) and
                 all(isinstance(text, str) and text.strip() for text in part)))
    method = review.get('method')
    require(review.get('schema') == 'codex-exam-translation-review.v1' and
            (described(method) or (isinstance(method, dict) and bool(method) and
             all(isinstance(key, str) and key.strip() and described(part) for key, part in method.items()))),
            'semantic review requires its independent method')
    expected, answers, counts = _expected_sentences(values['inputs'], values['translations'])
    require(values['index'] == {'schema': 'codex-exam-sentence-index.v1', 'paperId': paper_id, 'sentences': expected},
            'approved index differs from the independently replayed source and translation')
    require(all(paper[key] == counts[key] for key in counts)
            and all(native[0][key] == counts[key] for key in ('paragraphs', 'sentences', 'blocked'))
            and native[0]['sourceParagraphs'] == counts['paragraphs']
            and type(review.get('reviewedSentences')) is int and type(review.get('reviewedAlignments')) is int
            and review['reviewedSentences'] == counts['sentences']
            and review['reviewedAlignments'] == counts['alignments'], 'paper review coverage differs')
    sentences = [{**row, 'cloze_answers': answers[row['id']], 'translation_alignment': {
        'schema': 'codex-sentence-alignment.v1', 'englishHash': row['englishHash'],
        'translationHash': row['translationHash'], 'alignments': deepcopy(row['alignments'])}} for row in expected]
    structured = root / 'data/sources/exam-library/structured/papers/kaoyan' / (name + '.json')
    read_materialized(structured, watched)  # Refuse hydration before the existing producers read it.
    report = {'manifest_sha256': manifest_sha, 'input_manifest_sha256': inventory_sha, 'source_files': source_files}
    target_completion, completion_watched = prepare_reading_completions(root, sentences, report)
    completion_payload, completion_sha = read_materialized(completion_path, watched)
    require(completion_payload['indexManifestHash'] == manifest_sha and completion_payload['inputManifestHash'] == inventory_sha,
            'completion sidecar has stale approved manifest binding')
    approval = Path(completion_path).with_suffix('.review.json'); read_materialized(approval, watched)
    _, approval_sha = _approved_completion_review(Path(completion_path), completion_sha, completion_payload)
    require(watched[str(approval.resolve())] == approval_sha, 'completion approval changed')
    approved = {row['sentenceId']: row for row in completion_payload['rows']}
    require(len(approved) == len(completion_payload['rows']), 'completion sidecar repeats a sentence')
    completions = {}
    for current in target_completion['rows']:
        saved = approved.get(current['sentenceId'])
        require(saved is not None and set(saved) == set(current) | {'status', 'translationZh'}
            and all(saved[key] == value for key, value in current.items()) and saved['status'] == 'reviewed'
            and isinstance(saved['translationZh'], str) and saved['translationZh'].strip(), 'approved completion no longer binds its original source')
        completions[current['sentenceId']] = deepcopy(saved)
    insertions, insertion_watched, _ = prepare_sentence_insertions(root, sentences, report)
    require(not set(completions).intersection(insertions), 'completion source identities overlap')
    completions.update(insertions)
    options, option_watched, _, _ = prepare_option_contexts(root, sentences, report, completions)
    watched.update({str(path.resolve()): value for path, value in {**completion_watched, **insertion_watched, **option_watched}.items()})
    return {'sentences': {row['id']: row for row in sentences}, 'completions': completions,
            'options': options, 'watched': {Path(path): checksum for path, checksum in watched.items()}}

_VALIDATED = object()


def _source_content_pin(sources):
    return sha(canonical({key: value for key, value in sources.items() if key != 'watched'}))


class ApprovedInputs:
    """Opaque materialized-source replay cache; never construct from a sidecar."""
    def __init__(self, token, paper_id, sources, file_stats=None):
        require(token is _VALIDATED, 'approved inputs must be independently replayed')
        self.paper_id = paper_id
        self._sources = sources
        self._content_sha256 = _source_content_pin(sources)
        self.source_files = {str(path): checksum for path, checksum in sources['watched'].items()}
        self._file_stats = file_stats if file_stats is not None else {str(path): stat_pin(path) for path in sources['watched']}

    def unchanged(self):
        require(self._content_sha256 == _source_content_pin(self._sources), 'approved replay cache was modified')
        require(self.source_files == {str(path): checksum for path, checksum in self._sources['watched'].items()},
                'approved replay file pins were modified')
        for path, pin in self._file_stats.items():
            require(stat_pin(path) == pin, 'approved replay source changed: ' + path)
        return self._sources


def load_approved_inputs(exam_root, staging, paper_id, *, completion_path):
    sources = load_paper_sources(exam_root, staging, paper_id, completion_path=completion_path)
    # Every source byte hash was established by materialized, stable reads and
    # every review/index/completion binding was replayed before cache creation.
    file_stats = {}
    for path, checksum in sources['watched'].items():
        before = stat_pin(path)
        _, actual = read_materialized(path, {})
        require(actual == checksum and before == stat_pin(path), 'approved source changed before replay cache: ' + str(path))
        file_stats[str(path)] = before
    result = ApprovedInputs(_VALIDATED, paper_id, sources, file_stats)
    result.unchanged()
    return result


def validate_projection(item, original_row, *, book_id, card_id, definition_provenance, inputs):
    """Regenerate the exact allowed display diff from independent reviewed input."""
    require(isinstance(inputs, ApprovedInputs), 'opaque validated approved inputs are required')
    require(item['book_id'] == book_id and item['card_id'] == card_id and
            item['occurrence_id'] == original_row['occurrence_id'], 'projection physical card/occurrence differs')
    require(eligible_reading(original_row) and original_row['display']['provenance']['derivation'] == 'original',
            'projection requires an original reviewed reading option')
    require(inputs.paper_id == original_row['paper_id'], 'approved inputs belong to another paper')
    require(item['physical_row_sha256'] == physical_row_sha256(original_row) and
            item['raw_context_hash'] == sd._raw_context_hash(original_row) and
            item['old_display_hash'] == original_row['display']['display_hash'], 'projection parent row/display pin differs')
    sd.validate_display(original_row['display'], original_row, definition_provenance)
    sources = inputs.unchanged()
    require(item['source_files'] == inputs.source_files, 'projection approved source file pins differ')
    expected_structured = original_row['source_provenance']['sourcePathEvidence'].get('structuredPaperHash')
    structured_pins = [checksum for path, checksum in sources['watched'].items()
        if Path(path).parent.name == 'kaoyan' and Path(path).name == original_row['paper_id'].split(':')[1] + '.json']
    require(structured_pins == [expected_structured], 'original physical structured source hash differs')
    source = sd._source_row(original_row, sources)
    derived = sd._derived_displays(original_row, sources)
    require(derived is not None and derived[2] in {'option_context', 'inserted_option'},
            'projection has no independently approved reading derivation')
    actual = sd._display(original_row, source, [], sources,
                         original_row['display']['provenance']['source_card_sha256'])
    sd.validate_display(actual, original_row, definition_provenance)
    require(item['new_display'] == actual and item['source_refs'] == actual['derivation_payload'],
            'projection differs from independently replayed approved sources')
    return deepcopy(actual)


def validate_sidecar(document):
    """Validate content seal, exact physical-key partition and source pin closure."""
    require(document.get('schema') == 'reading-option-display-projection.v1', 'projection sidecar schema differs')
    require(document.get('projection_sha256') == sha(canonical({k:v for k,v in document.items() if k != 'projection_sha256'})),
            'projection sidecar content seal differs')
    keys, totals = set(), {}
    for status in ('projected', 'blocked'):
        for item in document[status]:
            key = tuple(item.get(name) for name in ('book_id', 'card_id', 'occurrence_id'))
            require(all(isinstance(part, str) and part for part in key) and key not in keys,
                    'projection sidecar repeats or lacks a physical key')
            keys.add(key)
            counts = totals.setdefault(item['book_id'], {'projected':0, 'blocked':0})
            counts[status] += 1
            if status == 'projected':
                require(all(document['source_files'].get(path) == checksum for path, checksum in item['source_files'].items()),
                        'projection item source pins differ from sidecar')
    require(set(totals) == set(document['books']), 'projection sidecar book set differs')
    for book, counts in totals.items():
        metadata = document['books'][book]
        require(counts['projected'] == metadata['projected'] and counts['blocked'] == metadata['blocked_original_retained']
                and sum(counts.values()) == metadata['original'], 'projection sidecar partition does not close')
    return True


def _authority(authority):
    require(isinstance(authority, dict) and set(authority) == {'sidecar', 'replay'},
            'reading projection needs exact sidecar and replay authority')
    sidecar, replay = authority['sidecar'], authority['replay']
    require(isinstance(sidecar, dict) and set(sidecar) == {'file', 'sha256'} and
            isinstance(sidecar['file'], str) and isinstance(sidecar['sha256'], str) and
            re.fullmatch(r'[0-9a-f]{64}', sidecar['sha256']), 'reading projection sidecar pin differs')
    require(isinstance(replay, dict) and set(replay) == {'exam_root', 'staging', 'completion_path'} and
            all(isinstance(value, str) and value for value in replay.values()),
            'reading projection replay paths differ')
    return str(Path(sidecar['file']).resolve(strict=True)), sidecar['sha256'], replay


class _Catalog:
    def __init__(self, path, checksum):
        self.path = path
        before = stat_pin(path)
        raw = Path(path).read_bytes()
        require(before == stat_pin(path) and sha(raw) == checksum, 'reading projection sidecar bytes changed')
        document = json.loads(raw, object_pairs_hook=unique)
        validate_sidecar(document)
        self.stat = before
        self.database = deepcopy(document['source_database'])
        require(isinstance(self.database.get('file'), str) and
                isinstance(self.database.get('stat'), dict), 'reading projection source database pin is missing')
        # Reuse the accepted source SHA plus stable stat gate. Never rehash the
        # multi-gigabyte database for each presentation-only occurrence.
        self.entries = {(item['book_id'], item['card_id'], item['occurrence_id']): canonical(item)
                        for item in document['projected']}
        self.unchanged()

    def unchanged(self):
        require(stat_pin(self.path) == self.stat, 'reading projection sidecar changed after validation')
        require(stat_pin(self.database['file']) == self.database['stat'],
                'reading projection original source database changed')


@lru_cache(maxsize=8)
def _catalog(path, checksum):
    return _Catalog(path, checksum)


@lru_cache(maxsize=64)
def _approved_inputs(exam_root, staging, completion_path, paper_id):
    return load_approved_inputs(exam_root, staging, paper_id, completion_path=completion_path)


def get_projection(authority, book_id, card_id, occurrence_id):
    """Return a detached, exact authorized item, or None for an unprojected row."""
    path, checksum, _ = _authority(authority)
    catalog = _catalog(path, checksum)
    catalog.unchanged()
    serialized = catalog.entries.get((book_id, card_id, occurrence_id))
    return json.loads(serialized) if serialized is not None else None


def replay_projection(authority, item, parent_row, *, book_id, card_id, definition_provenance):
    """Allow only the frozen item, regenerated from independent reviewed sources."""
    _, _, replay = _authority(authority)
    accepted = get_projection(authority, book_id, card_id, parent_row['occurrence_id'])
    require(accepted is not None and item == accepted, 'projection is not the exact authorized sidecar item')
    inputs = _approved_inputs(replay['exam_root'], replay['staging'], replay['completion_path'], parent_row['paper_id'])
    return validate_projection(item, parent_row, book_id=book_id, card_id=card_id,
                               definition_provenance=definition_provenance, inputs=inputs)
