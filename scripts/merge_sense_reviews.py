#!/usr/bin/env python3
"""Merge source-bound context reviews without touching a database or live page.

Incomplete runs are explicit: missing decisions retain the inventory's pending
state. A completed review can still be ambiguous/unmatched; completion means
each physical occurrence was considered, not that every meaning was confirmed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_pipeline import sense_frequency as sf

SCHEMA = 'sense-review-merge.v1'
_COMMON = ('paper_id', 'sentence_id', 'target_range', 'english', 'translation',
           'translation_ranges', 'source')
_DECISION = frozenset({'status', 'sense_index', 'reason', 'method', 'review_version',
    'reviewed_sense_id', 'assignment_context_hash', 'matching_proposal',
    'translation_hash', 'occurrence_id', 'year', 'sense_id', 'semantic_review_provenance'})
_ASSIGNMENT = frozenset({'index', 'status', 'sense_index', 'reason'})


class ReviewConflictError(ValueError):
    """Conflicts are structured evidence, never an instruction to overwrite."""
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__('conflicting semantic reviews: ' + canonical(conflicts))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip(): raise ValueError(f'{path}:{line_number}: blank JSONL record')
            value = json.loads(line)
            if not isinstance(value, dict): raise ValueError(f'{path}:{line_number}: object required')
            yield value


def _raw_hash(row):
    return fingerprint({key: value for key, value in row.items() if key not in _DECISION})


def _input_hash(row, *, parallel):
    value = {key: row[key] for key in _COMMON}
    if parallel:
        value.update(physical_source=row['physical_source'],
                     aligned_target_chunks=row.get('alignment_evidence', []))
    return fingerprint(value)


def _physical_id(row):
    """Reproduce core identity cheaply; full validation runs before publication.

    Work-item rows must match every edition row byte-for-byte in raw context.
    Thus the final per-record core validation also covers the source work rows;
    performing that same full alignment validation here would repeat it.
    """
    if not isinstance(row, dict):
        raise ValueError('work occurrence must be an object')
    english, paper, span = row.get('english'), row.get('paper_id'), row.get('target_range')
    if (not isinstance(english, str) or not english.strip() or
            row.get('english_hash') != hashlib.sha256(english.encode()).hexdigest() or
            not isinstance(paper, str) or not re.fullmatch(r'kaoyan:\d{4}-\d{2}', paper) or
            not isinstance(row.get('sentence_id'), str) or not row['sentence_id'].startswith(paper + ':')):
        raise ValueError('invalid work occurrence English hash or paper identity')
    if (not isinstance(span, list) or len(span) != 2 or any(type(n) is not int for n in span) or
            not 0 <= span[0] < span[1] <= len(english)):
        raise ValueError('invalid work occurrence Unicode physical range')
    physical = row.get('physical_source')
    if not isinstance(physical, list) or not physical: raise ValueError('missing work physical source')
    return fingerprint([paper, physical, span])


def _emit(progress, stage, **fields):
    if progress is not None: progress(stage, **fields)


def _load_work(inventory, manifest, progress=None):
    report_bytes = (inventory / 'inventory.json').read_bytes()
    report = json.loads(report_bytes)
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    hashes = report.get('jsonl_sha256', {})
    for name in ('records.jsonl', 'work-items.jsonl'):
        if sha256_file(inventory / name) != hashes.get(name):
            raise ValueError(f'stale inventory {name} hash')
    if hashes['work-items.jsonl'] != manifest.get('source_sha256'):
        raise ValueError('semantic manifest is bound to another work-items source')
    _emit(progress, 'source-hashes-verified', expected_work_items=report.get('unique_work_items'))
    works, cards = {}, {}
    tokens = 0
    for value in jsonl(inventory / 'work-items.jsonl'):
        work_id, record = value.get('work_id'), value.get('record')
        if not isinstance(record, dict): raise ValueError('work item needs its source record')
        rows = record.get('occurrences')
        if not isinstance(rows, list): raise ValueError('work item needs occurrence array')
        physical_ids = [_physical_id(row) for row in rows]
        if len(set(physical_ids)) != len(physical_ids):
            raise ValueError('source work item has duplicate physical occurrences')
        expected_id = fingerprint([record['word'], record['definition_source'], record['senses'],
                                   sorted(physical_ids)])
        if work_id != expected_id or work_id in works:
            raise ValueError('invalid or duplicate work identity')
        if len(rows) != record['expected_occurrences']:
            raise ValueError('source work item has duplicate physical occurrences')
        if any(row.get('status') != 'unmatched' or row.get('sense_index') is not None for row in rows):
            raise ValueError('source inventory must contain pending, unassigned occurrences')
        works[work_id] = {'word': record['word'], 'senses': record['senses'],
            'definition_source': record['definition_source'], 'count': len(rows),
            'raw_hashes': [_raw_hash(row) for row in rows],
            'unit_hashes': [_input_hash(row, parallel=False) for row in rows],
            'parallel_hashes': [_input_hash(row, parallel=True) for row in rows]}
        if not isinstance(value.get('cards'), list) or not value['cards']:
            raise ValueError('work item needs card identities')
        for card in value['cards']:
            key = (card['book_id'], card['card_id'])
            if key in cards: raise ValueError('card belongs to more than one work item')
            cards[key] = work_id
        tokens += len(rows)
        if len(works) % 100 == 0:
            _emit(progress, 'source-work-items', processed=len(works), occurrences=tokens)
    expected = manifest.get('new_occurrences'), manifest.get('existing_unit20_occurrences')
    if any(type(number) is not int or number < 0 for number in expected) or sum(expected) != tokens:
        raise ValueError('manifest physical totals do not reconcile with source work items')
    if tokens != report.get('unique_work_tokens') or len(works) != report.get('unique_work_items'):
        raise ValueError('inventory work totals do not reconcile')
    _emit(progress, 'source-work-items-complete', work_items=len(works), occurrences=tokens,
          edition_cards=len(cards))
    return report, works, cards, report_hash


def _validate_input(block, works, *, parallel):
    if not isinstance(block, dict): raise ValueError('review input block must be an object')
    work_id = block.get('work_id')
    if work_id not in works: raise ValueError('review input names unknown work item')
    work = works[work_id]
    if block.get('word') != work['word'] or block.get('senses') != work['senses']:
        raise ValueError('review input has stale word or dictionary senses')
    if parallel and block.get('definition_source') != work['definition_source']:
        raise ValueError('review input has stale definition source')
    if not isinstance(block.get('occurrences'), list): raise ValueError('review input needs occurrences')
    allowed = set(_COMMON) | {'index'}
    if parallel: allowed |= {'physical_source', 'aligned_target_chunks'}
    keys = set()
    for row in block['occurrences']:
        index = row.get('index')
        if type(index) is not int or not 0 <= index < work['count']:
            raise ValueError('review input occurrence index outside its source work item')
        if set(row) != allowed: raise ValueError('review input contains missing or unknown source fields')
        actual = fingerprint({key: row[key] for key in allowed if key != 'index'})
        expected = work['parallel_hashes' if parallel else 'unit_hashes'][index]
        if actual != expected: raise ValueError('review input occurrence differs from its source context')
        key = (work_id, index)
        if key in keys: raise ValueError('duplicate review input occurrence')
        keys.add(key)
    return keys


def _decision(value, work):
    if not isinstance(value, dict) or set(value) != _ASSIGNMENT:
        raise ValueError('review must contain index/status/sense_index/reason only')
    index, status, sense = value['index'], value['status'], value['sense_index']
    if type(index) is not int or not 0 <= index < work['count']:
        raise ValueError('review occurrence index outside its source work item')
    if not isinstance(status, str) or status not in {'reviewed', 'ambiguous', 'unmatched'}:
        raise ValueError('review status must be reviewed, ambiguous or unmatched')
    if status == 'reviewed':
        if type(sense) is not int or not 0 <= sense < len(work['senses']):
            raise ValueError('reviewed occurrence requires one valid sense')
    elif status not in {'ambiguous', 'unmatched'} or sense is not None:
        raise ValueError('suggestions or unresolved senses cannot become reviewed assignments')
    if not isinstance(value['reason'], str) or not value['reason'].strip():
        raise ValueError('review reason must be nonempty text')
    return dict(value)


def _decision_at(value, work, path, work_id):
    """Include the exact bad review location without weakening validation."""
    try:
        return _decision(value, work)
    except ValueError as error:
        index = value.get('index') if isinstance(value, dict) else None
        raise ValueError(f'{path}: work_id={work_id}, index={index}: {error}') from error


def _add_decision(assignments, key, value, provenance):
    if key in assignments:
        raise ReviewConflictError([{'work_id': key[0], 'index': key[1],
            'existing': assignments[key], 'incoming': {**value, 'provenance': provenance}}])
    assignments[key] = {**value, 'provenance': provenance}


def _load_reviews(manifest_path, manifest, works, unit_reviews, parallel_reviews, progress=None):
    assignments, covered = {}, set()
    files = []
    manifest_ids, manifest_files = set(), set()
    for shard in manifest.get('shards', []):
        number, name = shard.get('id'), shard.get('file')
        if type(number) is not int or number <= 0 or name != f'shard-{number:02d}.jsonl':
            raise ValueError('invalid manifest shard filename or ID')
        if number in manifest_ids or name in manifest_files: raise ValueError('duplicate manifest shard')
        manifest_ids.add(number); manifest_files.add(name)
        path = manifest_path.parent / name
        if sha256_file(path) != shard.get('sha256'): raise ValueError('stale manifest input shard hash')
        keys = set()
        blocks = 0
        for block in jsonl(path):
            new = _validate_input(block, works, parallel=True)
            if keys & new or covered & new: raise ValueError('duplicate token among parallel input shards')
            keys |= new; blocks += 1
        if len(keys) != shard.get('occurrences') or blocks != shard.get('blocks'):
            raise ValueError('manifest shard counts do not reconcile')
        covered |= keys
        reviewed = parallel_reviews.get(number)
        if reviewed is None: continue
        result_hash = sha256_file(reviewed)
        for value in jsonl(reviewed):
            if set(value) != _ASSIGNMENT | {'work_id', 'word', 'input_shard_sha256'}:
                raise ValueError('parallel review has missing or unknown fields')
            key = (value['work_id'], value['index'])
            if key not in keys or value['word'] != works[key[0]]['word']:
                raise ValueError('parallel review token does not belong to its input shard')
            if value['input_shard_sha256'] != shard['sha256']:
                raise ValueError('parallel review is bound to another input shard')
            decision = _decision_at({key: value[key] for key in _ASSIGNMENT},
                                    works[value['work_id']], reviewed, value['work_id'])
            _add_decision(assignments, key, decision, {'file': str(reviewed), 'sha256': result_hash,
                'input_sha256': shard['sha256'], 'method': 'context-agent.v1'})
        files.append({'file': str(reviewed), 'sha256': result_hash})
        _emit(progress, 'parallel-shard-verified', shard=number, considered_occurrences=len(assignments))
    if set(parallel_reviews) - manifest_ids: raise ValueError('reviewed shard missing from manifest')
    if len(covered) != manifest['new_occurrences']:
        raise ValueError('parallel input token total does not reconcile')
    unit_keys = set()
    for reviewed in unit_reviews:
        name = re.fullmatch(r'unit20-(\d+)-reviewed\.json', reviewed.name)
        if not name: raise ValueError('invalid unit20 review filename')
        source = reviewed.with_name(f'unit20-{name[1]}.json')
        source_hash, result_hash = sha256_file(source), sha256_file(reviewed)
        data = json.loads(reviewed.read_text())
        if (data.get('schema') != 'semantic-shard-review.v1' or data.get('input_sha256') != source_hash
                or data.get('review_method') != 'context-agent.v1'):
            raise ValueError('unit20 review has stale source or non-context method')
        source_blocks = json.loads(source.read_text())
        if not isinstance(source_blocks, list) or not isinstance(data.get('words'), list):
            raise ValueError('unit20 review/input needs word arrays')
        keys, source_words = set(), {}
        for block in source_blocks:
            new = _validate_input(block, works, parallel=False)
            if keys & new or covered & new or unit_keys & new: raise ValueError('duplicate unit20 source token')
            if block['work_id'] in source_words: raise ValueError('duplicate unit20 source work')
            keys |= new; source_words[block['work_id']] = block['word']
        unit_keys |= keys
        for word in data['words']:
            work_id = word.get('work_id')
            if word.get('word') != source_words.get(work_id) or not isinstance(word.get('assignments'), list):
                raise ValueError('unit20 review names an unknown source word')
            for value in word['assignments']:
                decision = _decision_at(value, works[work_id], reviewed, work_id)
                key = (work_id, decision['index'])
                if key not in keys: raise ValueError('unit20 review token outside its source input')
                _add_decision(assignments, key, decision, {'file': str(reviewed), 'sha256': result_hash,
                    'input_sha256': source_hash, 'method': data['review_method']})
        files.append({'file': str(reviewed), 'sha256': result_hash})
        _emit(progress, 'unit20-review-verified', file=reviewed.name, considered_occurrences=len(assignments))
    if len(unit_keys) > manifest['existing_unit20_occurrences']:
        raise ValueError('unit20 source token total exceeds manifest')
    return assignments, files


def _accepted(path, works, assignments):
    if path is None: return 0
    rows = json.loads(path.read_text()) if path.suffix == '.json' else jsonl(path)
    if isinstance(rows, dict): rows = rows.get('records', [])
    words = {}
    for work_id, work in works.items():
        words.setdefault((work['word'], fingerprint(work['senses']), work['definition_source']), []).append(work_id)
    added = 0
    conflicts = []
    for record in rows:
        sf.prepare_record(record)  # Accepted assignments require their prior explicit seals.
        candidates = words.get((record['word'], fingerprint(record['senses']), record['definition_source']), [])
        for row in record['occurrences']:
            raw_hash = _raw_hash(row)
            matches = [(work_id, index) for work_id in candidates
                       for index, value in enumerate(works[work_id]['raw_hashes']) if value == raw_hash]
            if len(matches) != 1: raise ValueError('accepted sample does not bind to exactly one raw context')
            key = matches[0]
            value = _decision({'index': key[1], 'status': row['status'], 'sense_index': row['sense_index'],
                               'reason': row['reason']}, works[key[0]])
            prior = assignments.get(key)
            if prior:
                if (prior['status'], prior['sense_index']) != (value['status'], value['sense_index']):
                    conflicts.append({'work_id': key[0], 'word': record['word'], 'index': key[1],
                        'existing': prior, 'accepted_sample': value, 'accepted_file': str(path)})
            else:
                _add_decision(assignments, key, value, {'file': str(path), 'sha256': sha256_file(path),
                    'input_sha256': raw_hash, 'method': 'accepted-context-review.v1'})
                added += 1
    if conflicts: raise ReviewConflictError(conflicts)
    return added


def merge_reviews(inventory_dir, manifest_path, output_dir, *, unit20_reviews=(),
                  reviewed_shards=(), accepted_records=None, require_complete=False, progress=None):
    inventory, manifest_path, output = map(Path, (inventory_dir, manifest_path, output_dir))
    unit_paths = list(map(Path, unit20_reviews))
    if output.exists(): raise FileExistsError('merge output must be a new directory')
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 'semantic-parallel-manifest.v1': raise ValueError('unknown semantic manifest')
    report, works, cards, inventory_hash = _load_work(inventory, manifest, progress)
    reviewed_map = {}
    for path in map(Path, reviewed_shards):
        name = re.fullmatch(r'shard-(\d+)-reviewed\.jsonl', path.name)
        if not name or int(name[1]) in reviewed_map: raise ValueError('invalid or duplicate reviewed shard')
        reviewed_map[int(name[1])] = path
    assignments, files = _load_reviews(manifest_path, manifest, works,
                                       unit_paths, reviewed_map, progress)
    bindings = [{'file': str(inventory / name), 'sha256': sha}
                for name, sha in report['jsonl_sha256'].items() if name in {'records.jsonl', 'work-items.jsonl'}]
    bindings.append({'file': str(inventory / 'inventory.json'), 'sha256': inventory_hash})
    bindings.append({'file': str(manifest_path), 'sha256': manifest_hash})
    bindings.extend({'file': str(manifest_path.parent / shard['file']), 'sha256': shard['sha256']}
                    for shard in manifest['shards'])
    bindings.extend(files)
    for path in unit_paths:
        source = path.with_name(path.name.replace('-reviewed.json', '.json'))
        bindings.append({'file': str(source), 'sha256': json.loads(path.read_text())['input_sha256']})
    if accepted_records:
        bindings.append({'file': str(accepted_records), 'sha256': sha256_file(accepted_records)})
    accepted = _accepted(Path(accepted_records) if accepted_records else None, works, assignments)
    total = sum(work['count'] for work in works.values())
    if require_complete and len(assignments) != total:
        raise ValueError(f'incomplete semantic coverage: {len(assignments)} / {total}')
    _emit(progress, 'review-coverage-verified', considered=len(assignments), total=total)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.sense-review-merge-', dir=output.parent))
    book_counts, book_statuses, book_senses = Counter(), {}, Counter()
    seen_cards = set()
    claimed_output = False
    moved = []
    try:
        with (staging / 'records.jsonl').open('x', encoding='utf-8') as stream:
            for record in jsonl(inventory / 'records.jsonl'):
                key = (record['book_id'], record['card_id'])
                if key in seen_cards or key not in cards: raise ValueError('duplicate or unknown source card')
                seen_cards.add(key); work_id = cards[key]; work = works[work_id]
                if (record['word'] != work['word'] or record['senses'] != work['senses'] or
                        record['definition_source'] != work['definition_source'] or
                        [_raw_hash(row) for row in record['occurrences']] != work['raw_hashes']):
                    raise ValueError('edition source card does not reconcile with its bound work item')
                if any(row.get('status') != 'unmatched' or row.get('sense_index') is not None
                       for row in record['occurrences']):
                    raise ValueError('edition source inventory must contain pending, unassigned occurrences')
                for index, row in enumerate(record['occurrences']):
                    decision = assignments.get((work_id, index))
                    if decision:
                        row.update({field: decision[field] for field in ('status', 'sense_index', 'reason')})
                        row.update(method=decision['provenance']['method'], review_version=SCHEMA)
                        row['semantic_review_provenance'] = {**decision['provenance'],
                            'work_id': work_id, 'index': index, 'work_items_sha256': manifest['source_sha256']}
                    if row['status'] == 'reviewed':
                        record['occurrences'][index] = sf.seal_reviewed_assignment(record, row)
                    else:
                        row.pop('reviewed_sense_id', None); row.pop('assignment_context_hash', None)
                    book_statuses.setdefault(record['book_id'], Counter())[row['status']] += 1
                sf.prepare_record(record)
                stream.write(canonical(record) + '\n')
                book_counts[record['book_id']] += 1
                book_senses[record['book_id']] += len(record['senses'])
                if len(seen_cards) % 200 == 0:
                    _emit(progress, 'edition-records', processed=len(seen_cards), expected=report['records'])
        if seen_cards != set(cards) or len(seen_cards) != report['records']:
            raise ValueError('edition card totals do not reconcile')
        book_tokens = {book: sum(counts.values()) for book, counts in book_statuses.items()}
        for field, actual in (('records_by_book', dict(book_counts)),
                              ('senses_by_book', dict(book_senses)),
                              ('physical_tokens_by_book', book_tokens)):
            if field in report and report[field] != actual:
                raise ValueError(f'inventory {field} totals do not reconcile')
        _emit(progress, 'edition-records-complete', records=len(seen_cards),
              records_by_book=dict(book_counts), physical_tokens_by_book=book_tokens)
        statuses = Counter(decision['status'] for decision in assignments.values())
        groups = Counter('unit20' if Path(decision['provenance']['file']).name.startswith('unit20-')
                         else 'parallel' if Path(decision['provenance']['file']).name.startswith('shard-')
                         else 'accepted_sample' for decision in assignments.values())
        coverage = {'schema': SCHEMA, 'source_work_items_sha256': manifest['source_sha256'],
            'source_records_sha256': report['jsonl_sha256']['records.jsonl'],
            'manifest_sha256': manifest_hash, 'review_files': files, 'input_bindings': bindings,
            'unique_occurrences': total, 'considered_occurrences': len(assignments),
            'not_yet_considered': total - len(assignments), 'considered_statuses': dict(statuses),
            'considered_by_review_group': dict(groups),
            'confirmed_occurrences': statuses['reviewed'],
            'pending_occurrences': total - statuses['reviewed'],
            'semantic_coverage_complete': len(assignments) == total,
            'require_complete': require_complete, 'accepted_sample_added': accepted,
            'records': len(seen_cards), 'records_by_book': dict(book_counts),
            'senses_by_book': dict(book_senses), 'physical_tokens_by_book': book_tokens,
            'occurrence_statuses_by_book': {book: dict(counts) for book, counts in book_statuses.items()},
            'records_sha256': sha256_file(staging / 'records.jsonl'),
            'database_written': False, 'formal_pages_written': False}
        (staging / 'coverage.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')
        for binding in bindings:
            if sha256_file(binding['file']) != binding['sha256']:
                raise ValueError('source or review file changed during merge: ' + binding['file'])
        output.mkdir()  # Exclusive final claim; never replace an existing user directory.
        claimed_output = True
        for file in staging.iterdir():
            destination = output / file.name
            os.replace(file, destination); moved.append(destination)
        return coverage
    except BaseException:
        # No final directory is created until every record and total validates.
        if claimed_output:
            for path in moved: path.unlink(missing_ok=True)
            if not any(output.iterdir()): output.rmdir()
        raise
    finally:
        shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--unit20-reviews', type=Path, action='append', default=[])
    parser.add_argument('--reviewed-shards', type=Path, action='append', default=[])
    parser.add_argument('--accepted-records', type=Path)
    parser.add_argument('--require-complete', action='store_true')
    args = parser.parse_args(argv)
    units = [file for path in args.unit20_reviews for file in
             (sorted(path.glob('unit20-*-reviewed.json')) if path.is_dir() else [path])]
    shards = [file for path in args.reviewed_shards for file in
              (sorted(path.glob('shard-*-reviewed.jsonl')) if path.is_dir() else [path])]
    coverage = merge_reviews(args.inventory, args.manifest, args.output, unit20_reviews=units,
        reviewed_shards=shards, accepted_records=args.accepted_records, require_complete=args.require_complete,
        progress=lambda stage, **fields: print(canonical({'stage': stage, **fields}), file=sys.stderr, flush=True))
    print(json.dumps(coverage, ensure_ascii=False))


if __name__ == '__main__': main()
