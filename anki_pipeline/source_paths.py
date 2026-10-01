"""Readable paper hierarchy derived from original block and TOC evidence."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .reading_completion import _require, _sha, _unique_object


SEPARATOR = ' ➫ '
_INTERNAL = re.compile(r'\bkaoyan:|\b(?:q|b)-[0-9]+-[0-9]+\b')


def display_source_path(record, *, question_record=None, option_label=None):
    """Format one evidenced hierarchy; overrides keep candidate identity unique."""
    selected = question_record or record
    parts = list(selected['components'])
    label = option_label if option_label is not None else record.get('optionLabel')
    if label:
        _require(re.fullmatch(r'[A-Z]', label) is not None, 'Invalid displayed source option label')
        parts.append('选项' + label)
    value = SEPARATOR.join(parts)
    _require(bool(value.strip()) and not _INTERNAL.search(value), 'Displayed source contains an internal ID')
    return value


def _common(paths):
    result = list(paths[0]) if paths else []
    for path in paths[1:]:
        result = result[:next((i for i, pair in enumerate(zip(result, path)) if pair[0] != pair[1]),
                             min(len(result), len(path)))]
    return result


def prepare_source_paths(root, source_sentences, *, allow_partial=False):
    """Return display records, question records, watched files and an audit report."""
    root = Path(root).resolve(strict=True)
    papers, watched, records, question_records, reviewed_path_only = {}, {}, {}, {}, set()
    directory = root / 'data/sources/exam-library/structured/papers/kaoyan'
    for paper_id in sorted({row['paperId'] for row in source_sentences}):
        _require(re.fullmatch(r'kaoyan:[0-9]{4}-[0-9]{2}', paper_id) is not None,
                 'Invalid source path paper ID')
        path = directory / (paper_id.split(':')[1] + '.json')
        fallback_rows = [row for row in source_sentences if row['paperId'] == paper_id]
        if not path.is_file() and (allow_partial or all(
                isinstance(row.get('sourcePath'), str) and row['sourcePath'].strip()
                and not _INTERNAL.search(row['sourcePath']) for row in fallback_rows)):
            paper = {'id': paper_id, 'blocks': [], 'questions': [], 'toc': []}
            paper_hash = None
            reviewed_path_only.add(paper_id)
        else:
            resolved = path.resolve(strict=True)
            _require(resolved.is_relative_to(directory.resolve(strict=True)), 'Source path paper escapes its directory')
            raw = resolved.read_bytes(); paper_hash = _sha(raw)
            paper = json.loads(raw, object_pairs_hook=_unique_object)
            watched[resolved] = paper_hash
        _require(isinstance(paper, dict) and paper.get('id') == paper_id,
                 'Source path structured paper identity mismatch')
        title = paper.get('title')
        if (allow_partial or paper_id in reviewed_path_only) and not title:
            title = next((row['sourcePath'].split(SEPARATOR)[0] for row in source_sentences
                          if row['paperId'] == paper_id and not _INTERNAL.search(row['sourcePath'])),
                         paper_id.split(':')[1][:4] + '年考研英语')
        _require(isinstance(title, str) and bool(title.strip()) and not _INTERNAL.search(title),
                 'Source path paper has no readable original title')
        blocks = {block['id']: block for block in paper.get('blocks', [])}
        toc = {item['id']: item for item in paper.get('toc', [])}
        questions = {question['id']: question for question in paper.get('questions', [])}
        _require(len(blocks) == len(paper.get('blocks', [])) and len(toc) == len(paper.get('toc', []))
                 and len(questions) == len(paper.get('questions', [])), 'Duplicate source path source identity')
        chains = {}
        def chain(identifier, active=()):
            _require(identifier not in active and identifier in toc, 'Invalid source path TOC parent chain')
            item = toc[identifier]
            if identifier not in chains:
                label = item.get('label')
                _require(item.get('kind') == 'section' and identifier in blocks
                         and isinstance(label, str) and label == blocks[identifier].get('text'),
                         'Source path heading does not match its original block')
                parent = item.get('parentId')
                chains[identifier] = (chain(parent, (*active, identifier)) if parent else []) + [label]
            return chains[identifier]
        for identifier, item in toc.items():
            if item.get('kind') == 'section': chain(identifier)
        block_paths, current = {}, []
        for block in paper.get('blocks', []):
            if block['id'] in chains: current = chains[block['id']]
            block_paths[block['id']] = list(current)
        by_block_question = {}
        for qid, question in questions.items():
            for block_id in question.get('sourceBlocks', []):
                by_block_question.setdefault(block_id, set()).add(qid)
            item = toc.get(qid)
            evidence = []
            if item and item.get('kind') == 'question' and item.get('parentId'):
                levels = chain(item['parentId'])
                first_block = (question.get('sourceBlocks') or [None])[0]
                _require(first_block not in block_paths or block_paths[first_block] == levels,
                         'Source path question TOC disagrees with its original block hierarchy')
                evidence.append({'kind': 'question_toc_parent', 'tocId': qid, 'parentId': item['parentId']})
            else:
                levels = _common([block_paths[b] for b in question.get('sourceBlocks', []) if b in block_paths])
                evidence.append({'kind': 'question_source_blocks', 'sourceBlockIds': question.get('sourceBlocks', [])})
            number = question.get('number')
            _require(isinstance(number, str) and re.fullmatch(r'[1-9][0-9]*', number),
                     'Source path question has an invalid printed number')
            question_records[paper_id + ':' + qid] = {'components': [title, *levels, '第' + number + '题'],
                'evidence': evidence, 'questionId': paper_id + ':' + qid}
        papers[paper_id] = title, paper_hash, blocks, block_paths, chains, questions, by_block_question
    for row in source_sentences:
        paper_id = row['paperId']
        title, paper_hash, blocks, paths, chains, questions, by_block_question = papers[paper_id]
        prefix = paper_id + ':'
        context = row.get('context', {})
        source_blocks = [value.removeprefix(prefix) for value in row.get('sourceBlockIds', [])]
        known = [value for value in source_blocks if value in paths]
        evidence = [{'kind': 'structured_source_blocks', 'sourceBlockIds': [prefix + value for value in known]}] if known else []
        if not known:
            exact = [block_id for block_id, block in blocks.items()
                     if row['sourceEnglish'].strip() == block.get('text', '').strip()]
            if len(exact) == 1:
                known = exact
                evidence.append({'kind': 'exact_original_block_text', 'sourceBlockId': prefix + exact[0]})
        levels = _common([paths[value] for value in known])
        original = row.get('sourcePath', '')
        old_parts = original.split(SEPARATOR)
        if paper_id in reviewed_path_only and not _INTERNAL.search(original):
            levels = old_parts[1:]
            evidence.append({'kind': 'reviewed_source_path', 'sourcePath': original,
                             'reviewedContentHash': row['reviewedContentHash']})
        if len(old_parts) > 1 and old_parts[0] == title and old_parts[1:] in chains.values():
            legacy_levels = old_parts[1:]
            if not levels or legacy_levels[:len(levels)] == levels:
                levels = legacy_levels
                evidence.append({'kind': 'reviewed_source_path', 'sourcePath': original,
                                 'reviewedContentHash': row['reviewedContentHash']})
        qid = context.get('questionId')
        question = questions.get(qid.removeprefix(prefix)) if isinstance(qid, str) and qid.startswith(prefix) else None
        bank_id = context.get('sourceOptionId') or context.get('pdfVerifiedSource', {}).get('sourceOptionId')
        shared_bank = bool(bank_id and ':part-b:' in bank_id)
        option_label = None
        if row['kind'] == 'answer_option':
            label_match = re.fullmatch(re.escape(prefix) + r'(?:q-[0-9]+-[0-9]+|part-b):([A-Z])',
                                      bank_id if shared_bank else row['paragraphId'])
            _require(label_match is not None or allow_partial, 'Source option has no evidenced printed label')
            option_label = label_match[1] if label_match else None
        elif row['kind'] in {'heading_option', 'passage_option'}:
            label = context.get('optionLabel')
            printed = re.match(r'^\s*[\[(]?([A-Z])[\]).]\s*', row['sourceEnglish'])
            label = label or (printed[1] if printed else None)
            printed_pattern = ((r'(?<!\S)' if context.get('optionLabel') else r'^\s*') +
                               r'[\[(]?' + re.escape(label) + r'[\]).]\s*' +
                               (re.escape(row['sourceEnglish'].strip())
                                if context.get('optionLabel') else '')) if label else None
            if label and any(len(list(re.finditer(printed_pattern, blocks[value].get('text', '')))) == 1
                             for value in known):
                option_label = label
                evidence.append({'kind': 'printed_choice_bank_label', 'optionLabel': label})
        if shared_bank and question:
            bank = (question.get('context') or {}).get('choiceBank', [])
            selected = [item for item in bank if item.get('id') == bank_id and item.get('text') == row['sourceEnglish']]
            _require(len(selected) == 1, 'Source path shared option bank identity is ambiguous')
            bank_blocks = [value.removeprefix(prefix) for value in context.get('reflowBlockIds', [])]
            if not levels:
                levels = _common([paths[value] for value in bank_blocks if value in paths])
            if not levels:
                parent = question_records.get(qid, {}).get('components', [title])[1:-1]
                levels = parent
            evidence.append({'kind': 'shared_choice_bank', 'sourceOptionId': bank_id,
                             'reflowBlockIds': context.get('reflowBlockIds', [])})
            qid = None
        elif question:
            levels = question_records[qid]['components'][1:-1]
            evidence.extend(question_records[qid]['evidence'])
        elif row['kind'] in {'question_prompt', 'writing_prompt', 'figure_caption', 'chart_label', 'speaker_marker'}:
            possible = set().union(*(by_block_question.get(value, set()) for value in known)) if known else set()
            if len(possible) == 1:
                qid = prefix + next(iter(possible))
                question = questions[qid.removeprefix(prefix)]
                levels = question_records[qid]['components'][1:-1]
                evidence.extend(question_records[qid]['evidence'])
        components = [title, *levels]
        if question and not shared_bank: components.append('第' + question['number'] + '题')
        record = {'sentenceId': row['id'], 'paperId': paper_id, 'kind': row['kind'],
            'originalSourcePath': original, 'components': components, 'evidence': evidence,
            'questionId': qid if question and not shared_bank else None, 'optionLabel': option_label,
            'structuredPaperHash': paper_hash}
        record['sourcePath'] = display_source_path(record)
        records[row['id']] = record
    report = {'papers': len(papers), 'source_sentences': len(records), 'separator': '➫',
        'sentences_with_original_hierarchy': sum(len(row['components']) > 1 for row in records.values()),
        'sentences_with_title_only': sum(len(row['components']) == 1 for row in records.values()),
        'internal_ids_displayed': 0, 'question_number_policy': 'explicit_source_association_only',
        'shared_bank_question_policy': 'no_single_question_claim',
        'papers_using_reviewed_paths_without_structured_source': len(reviewed_path_only)}
    return records, question_records, watched, report
