"""Reuse approved native backfill displays while keeping physical counts intact.

An occurrence remains a source token. Its optional display is a separately
hashed view from the existing, approved reading completion/option pipeline.
Only exact unchanged authored chunks acquire projected alignment ranges.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .local_dictionary import _Tree
from .translation_alignment import validate_translation_alignment

SCHEMA = 'exam-sense-display.v2'
ROOT = Path(__file__).resolve().parents[1]


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _raw_context_hash(row):
    """Seal only physical inputs, independently of review and display fields."""
    return _sha(_json({
        'sentence_id': row['sentence_id'], 'physical_source': row['physical_source'],
        'english_hash': row['english_hash'], 'translation_hash': _sha(row['translation']),
        'target_range': row['target_range'], 'source_provenance': row['source_provenance'],
        'alignment': row.get('alignment', row.get('translation_alignment'))}))


def _digest(value, name):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError(f'{name} must be a lowercase SHA-256 digest')
    return value


def _span(value, text, name):
    if (not isinstance(value, list) or len(value) != 2 or
            any(type(part) is not int for part in value) or
            not 0 <= value[0] < value[1] <= len(text)):
        raise ValueError(f'{name} must identify an exact nonempty text range')
    return value


def _source_revision_chain(display, row, context, depth):
    review = row.get('semantic_review') or {}
    if not isinstance(review, dict):
        raise ValueError('display semantic evidence must be an object')
    chain = review.get('catalog_source_revision_chain')
    if chain is None:
        return False
    if not isinstance(chain, dict) or chain.get('schema') != 'study-catalog-reviewed-source-chain.v2':
        raise ValueError('revised display source chain is invalid')
    if any(chain.get(key) != context.get(key) for key in ('book_id', 'card_id', 'word')):
        return False  # A subsequent ownership transfer validates the old chain.
    sealed = {key: value for key, value in chain.items() if key != 'chain_sha256'}
    if chain.get('chain_sha256') != _sha(_json(sealed)):
        raise ValueError('revised display source chain seal is stale')
    base = chain.get('base_record')
    steps = chain.get('steps')
    if (not isinstance(base, dict) or not isinstance(steps, list) or not steps
            or any(base.get(key) != context.get(key) for key in ('book_id', 'card_id', 'word'))
            or base.get('snapshot_id') != _sha(_json({k: v for k, v in base.items() if k != 'snapshot_id'}))):
        raise ValueError('revised display source chain base is invalid')
    originals = [entry for entry in base.get('occurrences', [])
                 if entry.get('occurrence_id') == chain.get('base_occurrence_id')]
    if len(originals) != 1 or not isinstance(originals[0].get('display'), dict):
        raise ValueError('revised display source chain lacks one original display')
    state = deepcopy(originals[0])
    validate_display(state['display'], state, base['definition_provenance'],
                     ownership_context=base, _ownership_depth=depth + 1)
    source_page = state['display']['provenance']['source_card_sha256']
    source_keys = ('english', 'translation', 'alignment', 'source_provenance')
    row_keys = ('target_range', 'translation_ranges', 'alignment_evidence', 'reason', 'display')
    previous = base['snapshot_id']
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('revised display source chain step must be an object')
        payload = {key: value for key, value in step.items() if key != 'step_sha256'}
        if step.get('previous_sha256') != previous or step.get('step_sha256') != _sha(_json(payload)):
            raise ValueError('revised display source chain step seal is stale')
        expected_source, new_source = step.get('expected_source'), step.get('new_source')
        tokens = step.get('token_review')
        if (expected_source != {key: state.get(key) for key in source_keys}
                or not isinstance(new_source, dict) or set(new_source) != set(source_keys)
                or not isinstance(tokens, dict) or set(tokens) != {'expected', 'new'}
                or any(not isinstance(tokens[key], dict) or set(tokens[key]) != set(row_keys)
                       for key in ('expected', 'new'))):
            raise ValueError('revised display source chain has incomplete replacement evidence')
        if any(tokens['expected'][key] != state.get(key) for key in row_keys if key != 'reason'):
            raise ValueError('revised display source chain former token differs')
        if any(not isinstance(text, str) or not text.strip() for text in
               (tokens['expected']['reason'], tokens['new']['reason'], step.get('reason'))):
            raise ValueError('revised display source chain needs reviewed reasons')
        old_token = state['english'][slice(*state['target_range'])]
        state.update(deepcopy(new_source))
        state.update(deepcopy(tokens['new']))
        if (not isinstance(state.get('english'), str) or not state['english']
                or not isinstance(state.get('translation'), str)
                or not isinstance(state.get('source_provenance'), dict) or not state['source_provenance']):
            raise ValueError('revised display source chain has invalid source text or provenance')
        _span(state['target_range'], state['english'], 'revised physical target')
        if state['english'][slice(*state['target_range'])] != old_token:
            raise ValueError('revised display source chain changed lexical ownership')
        state['english_hash'] = _sha(state['english'])
        state['translation_hash'] = _sha(state['translation'])
        state['occurrence_id'] = _sha(_json([state['paper_id'], state['physical_source'], state['target_range']]))
        validate_translation_alignment(state['english'], state['translation'], state['alignment'])
        new_display = state.get('display')
        if (not isinstance(new_display, dict)
                or new_display.get('provenance', {}).get('source_card_sha256') != source_page):
            raise ValueError('revised display source chain changed the original page identity')
        # The base proves this page once. Each new reviewed transform must then
        # pass every normal display/range/chunk/source check independently.
        validate_display(new_display, state, {'page_sha256': source_page})
        previous = step['step_sha256']
    keys = ('paper_id', 'sentence_id', 'physical_source', 'english', 'english_hash', 'translation',
            'translation_hash', 'target_range', 'translation_ranges', 'alignment',
            'alignment_evidence', 'source_provenance', 'display')
    if any(state.get(key) != (display if key == 'display' else row.get(key)) for key in keys):
        raise ValueError('revised display source chain differs from its current physical source')
    return True


def _revised_display_source(display, row, definition_provenance, context, depth):
    review = row.get('semantic_review') or {}
    if not isinstance(review, dict):
        raise ValueError('display semantic evidence must be an object')
    revisions = review.get('catalog_source_revisions', [])
    if not isinstance(revisions, list) or not revisions:
        return False
    proof = deepcopy(revisions[-1])
    if not isinstance(proof, dict) or proof.get('schema') != 'study-catalog-reviewed-source-revision.v1':
        raise ValueError('revised display source proof is invalid')
    if any(proof.get(key) != context.get(key) for key in ('book_id', 'card_id', 'word')):
        # A later reviewed ownership transfer carries the earlier source
        # revision inside its exact former row; validate that chain below.
        return False
    seal = proof.pop('revision_sha256', None)
    if seal != _sha(_json(proof)):
        raise ValueError('revised display source proof hash is stale')
    before, original = proof.get('before_record'), proof.get('before_row')
    if not isinstance(before, dict) or not isinstance(original, dict):
        raise ValueError('revised display needs its complete former source')
    if before.get('snapshot_id') != _sha(_json({k: v for k, v in before.items() if k != 'snapshot_id'})):
        raise ValueError('revised display former record seal is stale')
    if any(before.get(key) != context.get(key)
           for key in ('book_id', 'card_id', 'word')):
        raise ValueError('revised display ownership context differs')
    if original not in before.get('occurrences', []):
        raise ValueError('revised display former physical row differs')
    keys = ('paper_id', 'sentence_id', 'physical_source', 'english', 'english_hash',
            'translation', 'translation_hash', 'target_range', 'translation_ranges',
            'alignment', 'alignment_evidence', 'source_provenance', 'display')
    current = {key: (display if key == 'display' else row.get(key)) for key in keys}
    if proof.get('after_source') != current:
        raise ValueError('revised display current source differs from its exact reviewed replacement')
    evidence = proof.get('evidence') or {}
    if not isinstance(evidence, dict) or not isinstance(evidence.get('token_review'), dict):
        raise ValueError('revised display replacement evidence is incomplete')
    source_keys = ('english', 'translation', 'alignment', 'source_provenance')
    row_keys = ('target_range', 'translation_ranges', 'alignment_evidence', 'reason', 'display')
    new_token = (evidence.get('token_review') or {}).get('new') or {}
    if (evidence.get('expected_source') != {key: original.get(key) for key in source_keys}
            or evidence.get('new_source') != {key: row.get(key) for key in source_keys}
            or (evidence.get('token_review') or {}).get('expected') != {key: original.get(key) for key in row_keys}
            or {key: new_token.get(key) for key in row_keys if key != 'reason'} != {
                key: display if key == 'display' else row.get(key) for key in row_keys if key != 'reason'}
            or not isinstance(new_token.get('reason'), str) or not new_token['reason'].strip()
            or not isinstance(proof.get('reason'), str) or not proof['reason'].strip()):
        raise ValueError('revised display replacement evidence is incomplete')
    old_display = original.get('display')
    if (not isinstance(old_display, dict) or display['provenance']['source_card_sha256']
            != old_display.get('provenance', {}).get('source_card_sha256')):
        raise ValueError('revised display changed its original page identity')
    validate_display(old_display, original, before['definition_provenance'],
                     ownership_context=before, _ownership_depth=depth + 1)
    return True


def _transferred_display_source(display, row, definition_provenance, context, depth):
    """Accept a different source page only with the complete exact transfer."""
    if (depth >= 16 or not isinstance(context, dict) or not isinstance(definition_provenance, dict)
            or definition_provenance != context.get('definition_provenance')):
        raise ValueError('transferred display needs its exact ownership context')
    if _source_revision_chain(display, row, context, depth):
        return
    if _revised_display_source(display, row, definition_provenance, context, depth):
        return
    review = row.get('semantic_review') or {}
    if not isinstance(review, dict):
        raise ValueError('display semantic evidence must be an object')
    transfers = review.get('catalog_ownership_transfers', [])
    if not isinstance(transfers, list) or not transfers:
        raise ValueError('display source card differs from the definition snapshot')
    proof = deepcopy(transfers[-1])
    if not isinstance(proof, dict) or proof.get('schema') != 'study-reviewed-ownership.v1':
        raise ValueError('transferred display ownership proof is invalid')
    seal = proof.pop('proof_sha256', None)
    if seal != _sha(_json(proof)):
        raise ValueError('transferred display ownership proof hash is stale')
    source = proof.get('source_record')
    original = proof.get('source_row')
    target = proof.get('target_before_record')
    if not isinstance(source, dict) or not isinstance(original, dict) or not isinstance(target, dict):
        raise ValueError('transferred display needs the complete original source')
    unsealed = {key: value for key, value in source.items() if key != 'snapshot_id'}
    if (proof.get('source_record_sha256') != _sha(_json(source))
            or source.get('snapshot_id') != _sha(_json(unsealed))
            or proof.get('source_snapshot') != source.get('snapshot_id')):
        raise ValueError('transferred display original record seal is stale')
    if (proof.get('target_before_record_sha256') != _sha(_json(target))
            or target.get('snapshot_id') != _sha(_json({k: v for k, v in target.items() if k != 'snapshot_id'}))):
        raise ValueError('transferred display original target seal is stale')
    for name in ('book_id', 'card_id', 'word'):
        if proof.get('source_' + name) != source.get(name):
            raise ValueError('transferred display original owner differs')
        if proof.get('target_' + name) != context.get(name) or target.get(name) != context.get(name):
            raise ValueError('transferred display target owner differs')
    sense = proof.get('target_dictionary_sense') or {}
    if (source.get('word') == context.get('word')
            or proof.get('target_definition_snapshot_id') != target.get('definition_snapshot_id')
            or sense not in target.get('senses', [])
            or not isinstance(proof.get('reason'), str) or not proof['reason'].strip()
            or not isinstance(proof.get('evidence'), dict) or not proof['evidence']):
        raise ValueError('transferred display current assignment differs from its reviewed target')
    identity = _sha(_json([original.get('paper_id'), original.get('physical_source'), original.get('target_range')]))
    if (proof.get('physical_id') != identity or original.get('occurrence_id') != identity
            or row.get('occurrence_id') != identity or original not in source.get('occurrences', [])
            or original.get('display') != display
            or proof.get('source_definition_provenance') != source.get('definition_provenance')):
        raise ValueError('transferred display differs from its exact source occurrence')
    for name in ('paper_id', 'physical_source', 'english', 'translation', 'english_hash',
                 'target_range', 'translation_ranges', 'source_provenance', 'alignment'):
        if row.get(name) != original.get(name):
            raise ValueError('transferred display changed its physical evidence')
    validate_display(display, original, source['definition_provenance'],
                     ownership_context=source, _ownership_depth=depth + 1)


def validate_display(display, row, definition_provenance=None, *, ownership_context=None,
                     _ownership_depth=0):
    """Validate a source-pinned presentation and return a copy without writes.

    The producer validates the live approved sidecars and native HTML. This
    validator is also usable while storing or reading immutable snapshots: it
    checks the complete presentation, the physical source binding, and the
    source-card fingerprint without rewriting a reviewed assignment.
    """
    if not isinstance(display, dict) or display.get('schema') != SCHEMA:
        raise ValueError('unsupported sense display schema')
    if not isinstance(row, dict):
        raise ValueError('display must bind to a physical occurrence object')
    try:
        data = json.loads(_json(display))
        for key in ('english', 'translation'):
            if not isinstance(data.get(key), str) or (key == 'english' and not data[key]):
                raise ValueError(f'display {key} must be source text')
            if _digest(data.get(key + '_hash'), 'display ' + key + ' hash') != _sha(data[key]):
                raise ValueError(f'stale display {key} hash')
        if (not isinstance(row.get('english'), str) or not isinstance(row.get('translation'), str) or
                row.get('english_hash') != _sha(row['english'])):
            raise ValueError('stale physical source English or translation')
        physical = _span(row.get('target_range'), row['english'], 'physical target')
        target = _span(data.get('target_range'), data['english'], 'display target')
        if data['english'][slice(*target)] != row['english'][slice(*physical)]:
            raise ValueError('display target differs from its physical source token')
        alignment = data.get('alignment')
        if not isinstance(alignment, dict):
            raise ValueError('display must preserve a complete alignment payload')
        answers = data.get('cloze_answers')
        if not isinstance(answers, list):
            raise ValueError('display cloze answers must be an array')
        for answer in answers:
            if not isinstance(answer, dict):
                raise ValueError('display cloze answer must be an object')
            span = _span([answer.get('start'), answer.get('end')], data['english'], 'display cloze answer')
            if type(answer.get('number')) is not int or answer['number'] <= 0:
                raise ValueError('display cloze answer needs its exact positive blank number')
            if answer.get('word') != data['english'][slice(*span)]:
                raise ValueError('display cloze answer text differs from its exact range')
        if not isinstance(data.get('source'), str) or not data['source'].strip():
            raise ValueError('display source label is required')
        provenance = data.get('provenance')
        if not isinstance(provenance, dict):
            raise ValueError('display source provenance is required')
        if provenance.get('method') not in {'native-example-with-approved-source-maps', 'approved-source-maps'}:
            raise ValueError('unsupported display provenance method')
        page_hash = _digest(provenance.get('source_card_sha256'), 'display source card hash')
        if definition_provenance is not None:
            if not isinstance(definition_provenance, dict) or page_hash != definition_provenance.get('page_sha256'):
                _transferred_display_source(data, row, definition_provenance, ownership_context, _ownership_depth)
        if (provenance.get('physical_sentence_id') != row['sentence_id'] or
                provenance.get('physical_target_range') != physical or
                provenance.get('english_hash') != row['english_hash'] or
                provenance.get('translation_hash') != _sha(row['translation']) or
                provenance.get('raw_context_hash') != _raw_context_hash(row)):
            raise ValueError('display physical source/context binding is stale')
        _digest(provenance.get('input_manifest_sha256'), 'approved display input manifest hash')
        derivation = provenance.get('derivation')
        if derivation not in {'original', 'completion', 'option_context', 'inserted_option'}:
            raise ValueError('unsupported approved display derivation')
        if derivation == 'original':
            if (provenance.get('derivation_sha256') is not None or
                    data['english'] != row['english'] or data['translation'] != row['translation'] or target != physical):
                raise ValueError('original display must exactly preserve its source text and target')
            expected_answers = provenance.get('source_cloze_answers')
            if not isinstance(expected_answers, list) or answers != expected_answers:
                raise ValueError('display cloze answers differ from the approved original source')
        else:
            _digest(provenance.get('derivation_sha256'), 'approved display derivation hash')
            if not isinstance(provenance.get('question_id'), str) or not provenance['question_id']:
                raise ValueError('derived display needs its exact question identity')
            derived = data.get('derivation_payload')
            if (not isinstance(derived, dict) or
                    _sha(json.dumps(derived, ensure_ascii=False, sort_keys=True)) != provenance['derivation_sha256'] or
                    derived.get('questionId') != provenance['question_id']):
                raise ValueError('display approved derivation payload/hash is stale')
            approved_english, approved_translation, approved_target, approved_answers = (
                _approved_derived_view(row, derived, derivation))
            if (data['english'] != approved_english or data['translation'] != approved_translation or
                    target != approved_target or answers != approved_answers):
                raise ValueError('display text, target or cloze differs from the approved derivation')
        # Establish the approved linguistic view before interpreting chunk
        # offsets into it. Resealed text edits must fail their source binding,
        # even when a resulting shorter translation also invalidates ranges.
        validate_translation_alignment(data['english'], data['translation'], alignment)
        parts = data.get('alignment_sources')
        if (not isinstance(parts, list) or
                _digest(provenance.get('alignment_sources_sha256'), 'approved chunk input hash') != _sha(_json(parts))):
            raise ValueError('display approved chunk inputs are stale')
        strategy = provenance.get('alignment_projection')
        if strategy not in {None, 'reviewed-source-plus-sentence.v1'}:
            raise ValueError('unknown display chunk projection strategy')
        if strategy == 'reviewed-source-plus-sentence.v1' and derivation == 'original':
            raise ValueError('sentence fallback is only an approved derived display')
        if alignment != _project_alignment(row, data['english'], data['translation'], parts,
                sentence_fallback=strategy is not None):
            raise ValueError('display chunk mapping differs from the approved source projection')
        files = provenance.get('source_files')
        if not isinstance(files, dict):
            raise ValueError('display source file fingerprints must be an object')
        for path, digest in files.items():
            if not isinstance(path, str) or not path:
                raise ValueError('display source file path must be nonempty text')
            _digest(digest, 'approved display source file hash')
        jump = provenance.get('native_jump')
        if provenance['method'] == 'native-example-with-approved-source-maps':
            if not isinstance(jump, dict):
                raise ValueError('native display needs its exact original jump binding')
            if not isinstance(jump.get('sentence_id'), str) or not jump['sentence_id']:
                raise ValueError('native display jump needs its source sentence identity')
            _digest(jump.get('english_hash'), 'native display source English hash')
            _digest(jump.get('reviewed_content_hash'), 'native display source review hash')
            ranges = jump.get('target_ranges')
            if (not isinstance(ranges, list) or any(not isinstance(span, list) or len(span) != 2 or
                    any(type(part) is not int for part in span) or not 0 <= span[0] < span[1] for span in ranges)):
                raise ValueError('native display jump target ranges are invalid')
            if not isinstance(jump.get('native_jump'), str) or not jump['native_jump']:
                raise ValueError('native display jump representation is required')
            if jump['sentence_id'] == row['sentence_id']:
                if jump['english_hash'] != row['english_hash'] or physical not in ranges:
                    raise ValueError('native display jump differs from the physical target')
        elif jump is not None:
            raise ValueError('sidecar-only display cannot claim a native jump')
        claimed = _digest(data.pop('display_hash', None), 'sense display hash')
        if _sha(_json(data)) != claimed:
            raise ValueError('sense display payload hash is stale')
        data['display_hash'] = claimed
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError('malformed source-pinned display') from error
    return data


def _load_sources(root=None, staging=None, completion_path=None, option_translation_path=None):
    from .codex_exam_index import load_codex_exam_index
    from .reading_completion import load_reading_completions
    from .sentence_insertion import prepare_sentence_insertions
    from .option_context import prepare_option_contexts
    root = Path(root or ROOT.parent / 'exam-library').resolve(strict=True)
    staging = Path(staging or root / 'data/staging/codex-translations-v1').resolve(strict=True)
    completion_path = Path(completion_path or ROOT / 'data/reading-completions-v1.json').resolve(strict=True)
    option_translation_path = Path(option_translation_path or completion_path.with_name('reading-option-translations-v1.json')).resolve(strict=True)
    sentences, report = load_codex_exam_index(staging)
    completions, watched, _ = load_reading_completions(root, completion_path, sentences, report)
    insertions, insertion_watched, _ = prepare_sentence_insertions(root, sentences, report)
    if set(completions).intersection(insertions):
        raise ValueError('reading and passage completion identities overlap')
    completions.update(insertions)
    options, option_watched, _, _ = prepare_option_contexts(
        root, sentences, report, completions, joined_translation_path=option_translation_path)
    watched.update(insertion_watched)
    watched.update(option_watched)
    watched.update({staging / name: digest for name, digest in report['source_files'].items()})
    return {'sentences': {row['id']: row for row in sentences}, 'completions': completions,
            'options': options, 'watched': watched}


def _descendant(node, name):
    return next((child for child in node.walk() if child.has_class(name)), None)


def _text_and_ranges(node, skip=None):
    pieces, marks, answers = [], [], []
    length = 0
    def walk(child):
        nonlocal length
        if isinstance(child, str):
            pieces.append(child); length += len(child); return
        if skip and child.has_class(skip):
            return
        if child.tag == 'br':
            pieces.append('\n'); length += 1; return
        start = length
        for item in child.children:
            walk(item)
        if child.has_class('target-word'):
            marks.append([start, length])
        if child.has_class('cloze-answer'):
            number = child.attrs.get('data-blank-number')
            if number is None or not re.fullmatch(r'\d+', number):
                raise ValueError('native answer has no exact blank identity')
            answers.append({'start': start, 'end': length, 'number': int(number)})
    walk(node)
    return ''.join(pieces), marks, answers


def _decode_jump(node):
    if node is None:
        return None
    packed = node.attrs.get('data-rb-j')
    if packed is not None:
        fields = packed.split('|')
        if (len(fields) not in {6, 7} or not re.fullmatch(r'\d+', fields[0]) or
                not re.fullmatch(r'\d{4}-\d{2}', fields[1])):
            raise ValueError('invalid packed native source identity')
        def hexadecimal(value):
            try:
                raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
            except ValueError as error:
                raise ValueError('invalid packed native source hash') from error
            if len(raw) != 32:
                raise ValueError('invalid packed native source hash length')
            return raw.hex()
        ranges = []
        for span in fields[5].split(';') if fields[5] else []:
            if not re.fullmatch(r'\d+,\d+', span):
                raise ValueError('invalid packed native source range')
            ranges.append([int(value) for value in span.split(',')])
        return {'sentence_id': 'kaoyan:' + fields[1] + ':' + unquote(fields[2]),
                'english_hash': hexadecimal(fields[3]), 'reviewed_content_hash': hexadecimal(fields[4]),
                'target_ranges': ranges, 'native_jump': packed}
    url = node.attrs.get('data-latex-url') or node.attrs.get('href')
    if not url:
        return None
    query = parse_qs(urlsplit(url).query)
    keys = ('anki-codex-sentence', 'anki-codex-hash', 'anki-codex-review', 'anki-codex-en')
    if any(len(query.get(key, [])) != 1 for key in keys):
        raise ValueError('native jump lacks a unique source binding')
    try:
        ranges = json.loads(query['anki-codex-en'][0])
    except (ValueError, TypeError) as error:
        raise ValueError('invalid native source ranges') from error
    return {'sentence_id': query[keys[0]][0], 'english_hash': query[keys[1]][0],
            'reviewed_content_hash': query[keys[2]][0], 'target_ranges': ranges, 'native_jump': url}


def _native_examples(page, aliases):
    root = _Tree(page).root
    for node in root.walk():
        if 'class' in node.attrs:
            node.attrs['class'] = ' '.join(aliases.get(value, value) for value in node.attrs['class'].split())
    examples = []
    for node in root.walk():
        if node.tag != 'li' or not node.has_class('example-card'):
            continue
        en = _descendant(node, 'example-text')
        zh = _descendant(node, 'example-translation')
        source = _descendant(node, 'example-source')
        if en is None or zh is None or source is None:
            raise ValueError('native example lacks English, translation or source')
        english, targets, answers = _text_and_ranges(en)
        translation, _, _ = _text_and_ranges(zh, 'translate-tag')
        # Packaging adds exactly one separator outside the translated source.
        if translation.startswith(' '):
            translation = translation[1:]
        for answer in answers:
            answer['word'] = english[answer['start']:answer['end']]
        examples.append({'english': english, 'translation': translation, 'target_ranges': targets,
                         'cloze_answers': answers, 'source': source.text(),
                         'jump': _decode_jump(_descendant(node, 'sentence-jump'))})
    return examples


def _source_ids(row):
    return list(dict.fromkeys([row['sentence_id'], *row['source_provenance'].get('sourceSentenceIds', [])]))


def _source_row(row, sources):
    matches = [sources['sentences'][identity] for identity in _source_ids(row)
               if identity in sources['sentences']]
    if not matches:
        raise ValueError('physical occurrence has no current approved source sentence')
    span = row.get('target_range')
    if (not isinstance(span, list) or len(span) != 2 or
            any(type(value) is not int for value in span) or
            not 0 <= span[0] < span[1] <= len(row['english'])):
        raise ValueError('physical occurrence has an invalid exact token range')
    for match in matches:
        if (match['english'] != row['english'] or match['translationZh'] != row['translation'] or
                match['englishHash'] != row['english_hash'] or
                match['reviewedContentHash'] != row['source_provenance'].get('reviewedContentHash')):
            raise ValueError('physical occurrence source text is stale')
    return matches[0]


def _completion_target(completion, row, owner, *, option=False):
    start, end = row['target_range']
    if option:
        refs = completion.get('optionSentenceRefs')
        if refs:
            selected = [ref for ref in refs if ref['sentenceId'] in _source_ids(row)]
            if len(selected) != 1:
                raise ValueError('inserted option has no unique source sentence reference')
            offset = completion['insertedRange'][0] + selected[0]['range'][0]
        else:
            offset = completion['insertedRange'][0]
            option_text = completion.get('optionText', '')
            offset -= len(option_text) - len(option_text.lstrip())
        return [offset + start, offset + end]
    if completion['originalEnglish'] != row['english']:
        raise ValueError('completion stem differs from the physical source')
    before, after = completion['blankRange']
    if end <= before:
        return [start, end]
    if start >= after:
        suffix = completion['originalEnglish'][after:]
        offset = len(completion['completedEnglish']) - len(suffix) - after
        return [start + offset, end + offset]
    raise ValueError('physical target crosses a replaced question blank')


def _approved_derived_view(row, derived, kind):
    """Replay only the approved presentation transform, without semantic matching."""
    english, translation = derived['completedEnglish'], derived['translationZh']
    if kind == 'option_context':
        from .option_context import context_target_ranges
        refs = [ref for ref in derived['optionSentenceRefs']
                if ref['sentenceId'] in _source_ids(row)]
        if len(refs) != 1:
            raise ValueError('approved option display lacks one exact physical sentence reference')
        target = list(context_target_ranges(derived,
            {'id': refs[0]['sentenceId'], 'english': row['english']},
            [tuple(row['target_range'])])[0])
    else:
        target = _completion_target(derived, row, row['sentence_id'], option=kind == 'inserted_option')
    answers = [{'start': derived['insertedRange'][0], 'end': derived['insertedRange'][1],
                'number': int(derived['answerNumber']),
                'word': english[slice(*derived['insertedRange'])]}]
    if kind == 'option_context' and not derived['hasQuestionBlank']:
        separator = derived['insertedRange'][0] - 2
        if english[separator:separator + 2] != '\n\n':
            raise ValueError('approved option display lacks its exact separator')
        english = english[:separator] + english[separator + 1:]
        target = [value - 1 if value > separator else value for value in target]
        for answer in answers:
            answer['start'] -= 1
            answer['end'] -= 1
    return english, translation, target, answers


def _completion_option_index(completions):
    """Index exact option identities without changing completion insertion order."""
    index = {}
    for ordinal, derived in enumerate(completions.values()):
        identities = derived.get('optionSentenceIds', [derived.get('optionSentenceId')])
        for identity in dict.fromkeys(identities):
            index.setdefault(identity, []).append((ordinal, derived))
    return index


def _derived_displays(row, sources):
    from .option_context import context_target_ranges
    candidates = []
    for identity in _source_ids(row):
        if identity in sources['options']:
            derived = sources['options'][identity]
            source = sources['sentences'][identity]
            target = context_target_ranges(derived, source, [tuple(row['target_range'])])[0]
            candidates.append((derived, list(target), 'option_context'))
        elif identity in sources['completions']:
            derived = sources['completions'][identity]
            candidates.append((derived, _completion_target(derived, row, identity), 'completion'))
    if not candidates:
        index = sources.get('_completion_option_index')
        if index is None:
            for derived in sources['completions'].values():
                option_ids = derived.get('optionSentenceIds', [derived.get('optionSentenceId')])
                if set(_source_ids(row)).intersection(option_ids):
                    candidates.append((derived, _completion_target(derived, row, row['sentence_id'], option=True), 'inserted_option'))
        else:
            ordered = {ordinal: derived for identity in _source_ids(row)
                       for ordinal, derived in index.get(identity, [])}
            for ordinal in sorted(ordered):
                derived = ordered[ordinal]
                candidates.append((derived, _completion_target(derived, row, row['sentence_id'], option=True), 'inserted_option'))
    unique = {}
    for derived, target, kind in candidates:
        key = (derived['completedEnglish'], derived['translationZh'], tuple(target))
        unique.setdefault(key, (derived, target, kind))
    if len(unique) > 1:
        raise ValueError('physical target has conflicting approved display contexts')
    return next(iter(unique.values())) if unique else None


def _positions(text, needle):
    if not needle:
        return []
    return [match.start() for match in re.finditer('(?=' + re.escape(needle) + ')', text)]


def _map_range(original, span, display):
    start, end = span
    if original == display:
        return [start, end]
    positions = _positions(display, original[start:end])
    if len(positions) != 1:
        return None
    return [positions[0], positions[0] + end - start]


def _project_alignment(row, english, translation, parts, *, sentence_fallback=False):
    if sentence_fallback:
        from .chunk_projection import project_reviewed_chunks
        return project_reviewed_chunks(english, translation, [row, *parts], sentence_fallback=True)
    # Original positions remain authoritative when the whole sentence is
    # unchanged. Modified displays require a unique exact substring on both
    # sides. Reworded or repeated fragments are deliberately not projected.
    entries, conflicts = {}, set()
    for part in [row, *parts]:
        payload = part.get('alignment')
        if payload is None:
            continue
        validate_translation_alignment(part['english'], part['translation'], payload)
        for entry in payload['alignments']:
            if entry['relation'] != 'equivalent':
                continue
            en = _map_range(part['english'], entry['en'], english)
            zh = [_map_range(part['translation'], span, translation) for span in entry['zh']]
            if en is None or any(span is None for span in zh):
                continue
            candidate = {'en': en, 'zh': zh, 'relation': 'equivalent'}
            key = tuple(en)
            if key in entries and entries[key] != candidate:
                conflicts.add(key)
            else:
                entries[key] = candidate
    alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': _sha(english),
                 'translationHash': _sha(translation),
                 'alignments': [value for key, value in sorted(entries.items()) if key not in conflicts]}
    validate_translation_alignment(english, translation, alignment)
    return alignment


def refresh_derived_chunks(row):
    """Version a validated display's chunks while keeping its linguistic inputs."""
    if not row.get('display'):
        return deepcopy(row)
    validate_display(row['display'], row)
    result = deepcopy(row)
    view = result['display']
    if view['provenance']['derivation'] == 'original':
        return result
    view['provenance']['alignment_projection'] = 'reviewed-source-plus-sentence.v1'
    view['alignment'] = _project_alignment(row, view['english'], view['translation'],
        view['alignment_sources'], sentence_fallback=True)
    view.pop('display_hash')
    view['display_hash'] = _sha(_json(view))
    validate_display(view, result)
    return result


def _parts(derived, sources):
    identities = []
    if derived:
        identities.extend([derived.get('sentenceId'), derived.get('optionSentenceId')])
        identities.extend(derived.get('optionSentenceIds', []))
        for key in ('stemSentenceRefs', 'optionSentenceRefs'):
            identities.extend(ref['sentenceId'] for ref in derived.get(key, []))
    parts = []
    for identity in dict.fromkeys(identities):
        source = sources['sentences'].get(identity)
        if source is not None:
            parts.append({'english': source['english'], 'translation': source['translationZh'],
                          'alignment': source['translation_alignment']})
    return parts


def _anchor_valid(example, row, derived, sources):
    jump = example['jump']
    if jump is None:
        return False
    identity = jump['sentence_id']
    source = sources['sentences'].get(identity)
    if source is None or source['englishHash'] != jump['english_hash'] or source['reviewedContentHash'] != jump['reviewed_content_hash']:
        raise ValueError('native example jump has stale original source hashes')
    if not isinstance(jump['target_ranges'], list):
        raise ValueError('native example jump has invalid original target ranges')
    for span in jump['target_ranges']:
        _span(span, source['english'], 'native source target')
    if identity in _source_ids(row):
        return row['target_range'] in jump['target_ranges']
    if derived:
        allowed = {derived.get('sentenceId'), derived.get('optionSentenceId'), *derived.get('optionSentenceIds', [])}
        allowed.update(ref['sentenceId'] for key in ('stemSentenceRefs', 'optionSentenceRefs') for ref in derived.get(key, []))
        return identity in allowed
    return False


def _display(row, source, examples, sources, page_hash):
    proposed = _derived_displays(row, sources)
    if proposed:
        derived, target, kind = proposed
        english, translation, target, answers = _approved_derived_view(row, derived, kind)
        if (english[slice(*target)] != row['english'][slice(*row['target_range'])] or
                not 0 <= target[0] < target[1] <= len(english)):
            raise ValueError('approved display target does not preserve its exact physical token')
    else:
        derived, kind = None, 'original'
        english, translation, target = row['english'], row['translation'], list(row['target_range'])
        answers = deepcopy(source.get('cloze_answers', []))
    matches = [example for example in examples if example['english'] == english and
               example['translation'] == translation and target in example['target_ranges'] and
               _anchor_valid(example, row, derived, sources)]
    if len(matches) > 1:
        raise ValueError('physical occurrence matches multiple native example displays')
    native = matches[0] if matches else None
    if native is not None:
        if native['cloze_answers'] != answers:
            raise ValueError('native cloze ranges differ from the approved source display')
        answers = native['cloze_answers']
    parts = _parts(derived, sources)
    alignment = _project_alignment(row, english, translation, parts, sentence_fallback=derived is not None)
    result = {'schema': SCHEMA, 'english': english, 'english_hash': _sha(english),
              'translation': translation, 'translation_hash': _sha(translation), 'target_range': target,
              'alignment': alignment, 'cloze_answers': answers,
              'derivation_payload': deepcopy(derived),
              'alignment_sources': parts,
              'source': native['source'] if native is not None else row['source'],
              'provenance': {'method': 'native-example-with-approved-source-maps' if native is not None else 'approved-source-maps',
                'source_card_sha256': page_hash, 'physical_sentence_id': row['sentence_id'],
                'physical_target_range': list(row['target_range']), 'english_hash': row['english_hash'],
                'translation_hash': _sha(row['translation']), 'raw_context_hash': _raw_context_hash(row), 'derivation': kind,
                'source_cloze_answers': deepcopy(source.get('cloze_answers', [])),
                'alignment_sources_sha256': _sha(_json(parts)),
                'question_id': derived.get('questionId') if derived else None,
                'native_jump': native['jump'] if native else None,
                'input_manifest_sha256': (sources.get('_display_input_manifest_sha256') or _sha(json.dumps(
                    {str(path): digest for path, digest in sources['watched'].items()}, sort_keys=True))),
                'derivation_sha256': _sha(json.dumps(derived, ensure_ascii=False, sort_keys=True)) if derived else None,
                'source_files': {str(path): digest for path, digest in sources['watched'].items()
                                 if derived and Path(path).name.startswith(('reading-completions-v1.', 'reading-option-translations-v1.'))}}}
    if derived is not None:
        result['provenance']['alignment_projection'] = 'reviewed-source-plus-sentence.v1'
    result['display_hash'] = _sha(_json(result))
    return result


def attach_source_displays(records, source_card_pages, aliases, *, root=None, staging=None,
                           completion_path=None, option_translation_path=None):
    """Return deep copies with optional source-pinned displays; perform no writes.

    Pages are keyed by card ID or ``(book_id, card_id)`` and contain the exact
    immutable HTML used by definition_provenance. ``aliases`` is its shipped
    compressed-to-original class map. Missing or stale linguistic inputs fail
    closed. Native originals, completion/option positions and counting fields
    are retained byte-for-byte in the input occurrence objects.
    """
    result = deepcopy(records)
    sources = dict(_load_sources(root, staging, completion_path, option_translation_path))
    sources['_display_input_manifest_sha256'] = _sha(json.dumps(
        {str(path): digest for path, digest in sources['watched'].items()}, sort_keys=True))
    sources['_completion_option_index'] = _completion_option_index(sources['completions'])
    for record in result:
        key = (record['book_id'], record['card_id'])
        page = source_card_pages.get(key, source_card_pages.get(record['card_id']))
        if not isinstance(page, str):
            raise ValueError('record has no exact source card page')
        page_hash = _sha(page)
        provenance = record['definition_provenance']
        if page_hash != provenance.get('page_sha256') or provenance.get('headword') != record['word']:
            raise ValueError('source card page or headword differs from its reviewed snapshot')
        examples = _native_examples(page, aliases)
        for row in record['occurrences']:
            source = _source_row(row, sources)
            row['display'] = validate_display(_display(row, source, examples, sources, page_hash), row, provenance)
    for path, digest in sources['watched'].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError('approved backfill display input changed during construction')
    return result
