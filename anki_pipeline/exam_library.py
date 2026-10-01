"""Read-only exact-form examples from the user's kaoyan library."""
from __future__ import annotations
import hashlib
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from .exam_frequency import frequency_for_matches, frequency_report
from .match_forms import card_match_forms
from .text import word_variants


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def standalone_word_option(text: str, kind: str) -> bool:
    """A bare printed answer word has no context for a separate example card."""
    return kind == 'answer_option' and re.fullmatch(
        r"[\s\"'“”‘’(\[]*[A-Za-z]+(?:[-'’][A-Za-z]+)*[\s\"'“”‘’)\].,;:!?]*",
        text) is not None


def sentence_ranges(text: str, sentences: list[str], paragraph_id: str) -> list[tuple[int, int]]:
    """Locate each indexed sentence in order, including repeated sentence text."""
    ranges = []
    cursor = 0
    for sentence in sentences:
        if not isinstance(sentence, str) or not sentence:
            raise ValueError(f'句子索引无效: {paragraph_id}')
        start = text.find(sentence, cursor)
        if start < 0:
            raise ValueError(f'句子位置与段落不一致: {paragraph_id}')
        end = start + len(sentence)
        ranges.append((start, end))
        cursor = end
    return ranges


def sentence_cloze_answers(paragraph: dict, ranges: list[tuple[int, int]]) -> list[list[dict]]:
    """Map verified completed-paragraph spans to sentence-local offsets."""
    paragraph_id = paragraph['id']
    text = paragraph['text']
    spans = paragraph.get('clozeAnswerSpans', [])
    if not isinstance(spans, list):
        raise ValueError(f'完形答案位置无效: {paragraph_id}')
    answers = [[] for _ in ranges]
    previous_end = 0
    for span in spans:
        if not isinstance(span, dict):
            raise ValueError(f'完形答案位置无效: {paragraph_id}')
        start, end, word, number = (span.get(key) for key in ('start', 'end', 'word', 'number'))
        if (type(start) is not int or type(end) is not int or
                not 0 <= start < end <= len(text) or start < previous_end or
                not isinstance(word, str) or not word or text[start:end] != word or
                not ((type(number) is int and number > 0) or
                     (isinstance(number, str) and re.fullmatch(r'[1-9][0-9]*', number)))):
            raise ValueError(f'完形答案位置无效: {paragraph_id}')
        previous_end = end
        for index, (sentence_start, sentence_end) in enumerate(ranges):
            if start < sentence_end and end > sentence_start:
                if start < sentence_start or end > sentence_end:
                    raise ValueError(f'完形答案跨越句子边界: {paragraph_id}')
                answers[index].append({'start': start - sentence_start,
                                       'end': end - sentence_start,
                                       'word': word, 'number': int(number)})
                break
    return answers


def library_examples(root: Path, cards: list[dict], base_url: str, reader: str,
                     maximum: int = 0, *, sentence_source: str = 'legacy',
                     codex_index_root: Path | None = None,
                     allow_partial_codex: bool = False,
                     reading_completion_path: Path | None = None) -> tuple[list[dict], dict]:
    if reader not in {'latex', 'full-paper'}:
        raise ValueError('exam_library.reader 必须是 latex 或 full-paper')
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
        raise ValueError('exam_library.max_examples 必须是非负整数，0 表示全部例句')
    base = urlsplit(base_url)
    if base.scheme not in {'http', 'https'} or not base.netloc or base.query or base.fragment or base.username or base.password:
        raise ValueError('exam_library.base_url 必须是 HTTP(S) 服务地址，不能含凭据或查询参数')
    if sentence_source not in {'legacy', 'codex'}:
        raise ValueError('exam_library.sentence_source 必须是 legacy 或 codex')
    if sentence_source == 'codex':
        return _codex_examples(root, cards, base_url, reader, maximum,
                               codex_index_root, allow_partial_codex,
                               reading_completion_path=reading_completion_path)
    if codex_index_root is not None or allow_partial_codex or reading_completion_path is not None:
        raise ValueError('Codex 索引参数必须明确选择 sentence_source=codex')
    index_root = root.resolve(strict=True) / 'data/sources/exam-library/structured/anki-sentences'
    catalog = json.loads((index_root / 'index.json').read_text())
    if catalog.get('schema') != 'anki-sentence-catalog.v1' or catalog.get('category') != 'kaoyan':
        raise ValueError('考研句子目录格式不匹配')
    paragraphs, seen_papers, seen_paragraphs, unaligned_sentences = [], set(), set(), 0
    corpus_kinds = {}
    for entry in sorted(catalog['papers'], key=lambda x: x['paperId'], reverse=True):
        paper_id = entry['paperId']
        if not re.fullmatch(r'kaoyan:\d{4}-\d{2}', paper_id) or paper_id in seen_papers:
            raise ValueError('考研试卷 ID 重复或无效')
        seen_papers.add(paper_id)
        path = (index_root / entry['path']).resolve(strict=True)
        if not path.is_relative_to(index_root.resolve()):
            raise ValueError('句子索引路径越界')
        data = json.loads(path.read_text())
        if (data.get('schema') != 'anki-sentence-index.v1' or data['paperId'] != paper_id or
                digest(json.dumps(data, sort_keys=True, ensure_ascii=False)) != entry['digest']):
            raise ValueError('句子索引已变化，请重新生成目录')
        for paragraph in data['paragraphs']:
            paragraph_id = paragraph.get('id')
            if (not isinstance(paragraph_id, str) or not paragraph_id.strip() or
                    paragraph_id in seen_paragraphs):
                raise ValueError('段落 ID 重复或无效')
            seen_paragraphs.add(paragraph_id)
            sentences = paragraph['sentences']
            translations = paragraph.get('sentenceTranslations')
            translation_hashes = paragraph.get('sentenceTranslationHashes')
            if ('sourcePath' in paragraph and
                    (not isinstance(paragraph['sourcePath'], str) or
                     not paragraph['sourcePath'].strip())):
                raise ValueError(f"句子出处路径无效: {paragraph['id']}")
            if (paragraph['paperId'] != paper_id or
                    digest(paragraph['sourceText']) != paragraph['sourceHash'] or
                    digest(paragraph['text']) != paragraph['textHash'] or
                    any(s not in paragraph['text'] for s in sentences)):
                raise ValueError('句子或译文索引不一致')
            ranges = sentence_ranges(paragraph['text'], sentences, paragraph['id'])
            cloze_answers = sentence_cloze_answers(paragraph, ranges)
            if (not isinstance(translations, list) or not isinstance(translation_hashes, list) or
                    len(translations) != len(sentences) or len(translation_hashes) != len(sentences)):
                raise ValueError(f"句子译文未逐句对齐: {paragraph['id']}")
            for value, value_hash in zip(translations, translation_hashes):
                if value is None and value_hash is None:
                    unaligned_sentences += 1
                elif not isinstance(value, str) or not value.strip() or digest(value) != value_hash:
                    raise ValueError(f"句子译文哈希不一致: {paragraph['id']}")
            paragraphs.append((paragraph, cloze_answers))
            counts = corpus_kinds.setdefault(paragraph['kind'], {'paragraphs': 0, 'sentences': 0})
            counts['paragraphs'] += 1
            counts['sentences'] += len(sentences)
    years = [int(paper_id.split(':')[1][:4]) for paper_id in seen_papers]
    corpus = {'scope': 'indexed_english_sentences', 'paper_count': len(seen_papers),
              'paper_ids': sorted(seen_papers), 'year_start': min(years) if years else None,
              'year_end': max(years) if years else None, 'paragraph_count': len(paragraphs),
              'sentence_count': sum(counts['sentences'] for counts in corpus_kinds.values()),
              'kinds': dict(sorted(corpus_kinds.items())),
              'sentences_without_aligned_translation': unaligned_sentences,
              'missing_translation_policy': 'english_counted_examples_skipped'}
    result, total, no_examples, skipped_unaligned_matches = [], 0, [], 0
    skipped_word_options = 0
    for card in cards:
        item = dict(card)
        item['examples'] = []
        frequency_matches = []
        variants = word_variants(card['word'], card_match_forms(card), infer=False)
        pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(x) for x in sorted(variants, key=lambda x: (-len(x), x))) + r')(?!\w)', re.I)
        for paragraph, cloze_answers in paragraphs:
            for index, sentence in enumerate(paragraph['sentences']):
                if not variants:
                    continue
                occurrences = sum(1 for _ in pattern.finditer(sentence))
                if not occurrences:
                    continue
                frequency_matches.append((paragraph['paperId'], paragraph['id'], index, occurrences))
                if standalone_word_option(sentence, paragraph['kind']):
                    skipped_word_options += 1
                    continue
                translation = paragraph['sentenceTranslations'][index]
                if translation is None:
                    skipped_unaligned_matches += 1
                    continue
                if maximum and len(item['examples']) >= maximum:
                    continue
                stem = paragraph['paperId'].split(':')[1]
                params = {'anki-paragraph': paragraph['id'], 'anki-sentence': str(index)}
                latex = base_url.rstrip('/') + '/english-exams-reflow-latex/kaoyan/papers/' + stem + '.htm?' + urlencode(params)
                whole = base_url.rstrip('/') + '/exam-library/practice/full-paper.htm?' + urlencode({'paper': paragraph['paperId'], **params})
                item['examples'].append({'text': sentence, 'translation': translation,
                    'translation_scope': 'sentence',
                    'source': paragraph.get('sourcePath', paragraph['title']),
                    'cloze_answers': cloze_answers[index],
                    'latex_url': latex, 'full_paper_url': whole, 'reader': reader,
                    'paragraph_id': paragraph['id'], 'sentence_index': index,
                    'kind': paragraph['kind']})
        item['exam_frequency'] = frequency_for_matches(frequency_matches, len(seen_papers))
        total += len(item['examples'])
        if not item['examples']:
            no_examples.append(card['word'])
        result.append(item)
    return result, {'papers': len(seen_papers), 'paragraphs': len(paragraphs),
        'cards': len(result), 'examples': total, 'cards_without_library_examples': len(no_examples),
        'sentences_without_aligned_translation': unaligned_sentences,
        'skipped_unaligned_matches': skipped_unaligned_matches,
        'skipped_standalone_word_option_matches': skipped_word_options,
        'example_policy': 'bare_word_options_counted_but_not_displayed',
        'words_without_library_examples': no_examples, 'database_modified': False,
        'translation_scope': 'aligned_library_sentence', 'default_reader': reader,
        'frequency': frequency_report(result, corpus)}


def _legacy_anchor_sentences(root: Path, paper_ids: set[str]):
    """Use legacy data only to verify a source location, never its translation."""
    index_root = root.resolve(strict=True) / 'data/sources/exam-library/structured/anki-sentences'
    catalog_path = index_root / 'index.json'
    if not catalog_path.is_file():
        return {}, {}
    watched = {catalog_path: hashlib.sha256(catalog_path.read_bytes()).hexdigest()}
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    if catalog.get('schema') != 'anki-sentence-catalog.v1' or catalog.get('category') != 'kaoyan':
        raise ValueError('原句锚点目录格式不匹配')
    anchors = {}
    seen = set()
    for entry in catalog['papers']:
        paper_id = entry['paperId']
        if paper_id not in paper_ids:
            continue
        if paper_id in seen:
            raise ValueError('原句锚点试卷 ID 重复')
        seen.add(paper_id)
        path = (index_root / entry['path']).resolve(strict=True)
        if not path.is_relative_to(index_root.resolve()):
            raise ValueError('原句锚点索引路径越界')
        raw = path.read_bytes()
        watched[path] = hashlib.sha256(raw).hexdigest()
        data = json.loads(raw)
        if (data.get('schema') != 'anki-sentence-index.v1' or data.get('paperId') != paper_id
                or digest(json.dumps(data, sort_keys=True, ensure_ascii=False)) != entry['digest']):
            raise ValueError('原句锚点索引已变化')
        for paragraph in data['paragraphs']:
            for index, english in enumerate(paragraph['sentences']):
                identifier = f"{paragraph['id']}:{index}"
                if not isinstance(english, str) or not english or identifier in anchors:
                    raise ValueError('原句锚点身份无效或重复')
                anchors[identifier] = {'paragraph_id': paragraph['id'], 'sentence_index': index,
                                       'text': english, 'english_hash': digest(english)}
    return anchors, watched


def _codex_anchor(sentence, ranges, anchors):
    """Prefer the original fragment containing this card's selected occurrence."""
    refs = sorted((ref for ref in sentence['sourceSentenceRefs']
                   if any(a >= ref['newRange'][0] and b <= ref['newRange'][1]
                          for a, b in ranges)), key=lambda ref: ref['newRange'][0])
    for ref in refs:
        old = anchors.get(ref['id']) if ref['catalog'] == 'anki-sentence-index.v1' else None
        if old is not None:
            if old['text'] != ref['sourceText'] or old['english_hash'] != ref['sourceHash']:
                raise ValueError(f"Codex 原句引用已过期: {ref['id']}")
            return {'paragraph_id': old['paragraph_id'], 'sentence_index': old['sentence_index'],
                    'kind': 'legacy_sentence_ref', 'sentence_id': ref['id'],
                    'english_hash': old['english_hash']}
    old = anchors.get(sentence['id'])
    if old is not None and old['text'] == sentence['english'] and old['english_hash'] == sentence['englishHash']:
        return {'paragraph_id': old['paragraph_id'], 'sentence_index': old['sentence_index'],
                'kind': 'legacy_sentence', 'sentence_id': sentence['id'],
                'english_hash': old['english_hash']}
    # The legacy reader requires a verified sentence, not a coarse block ID.
    # New/merged sentence provenance is retained in the example, but a link
    # cannot claim success until the public Codex reader can locate it.
    return None


def _canonical_codex_sentences(sentences):
    """Collapse only repeated printed answer options with explicit provenance."""
    selected, options, ambiguous, deduplicated = [], {}, [], 0
    by_paragraph = {}
    for row in sentences:
        by_paragraph.setdefault(row['paragraphId'], []).append(row)
    paragraph_aliases = []
    for sentence in sentences:
        context = sentence['context']
        if sentence['kind'] == 'answer_option' and context.get('coverageStatus') == 'covered_by_paragraph':
            owner = context.get('translationRef')
            owner_rows = by_paragraph.get(owner, []) if isinstance(owner, str) else []
            if (not owner_rows or owner_rows[0]['paperId'] != sentence['paperId'] or
                    set(owner_rows[0]['sourceBlockIds']) != set(sentence['sourceBlockIds']) or
                    not sentence['sourceBlockIds'] or
                    _printed_text(owner_rows[0]['sourceEnglish']).count(_printed_text(sentence['sourceEnglish'])) != 1):
                raise ValueError('Option paragraph alias lacks an exact verified physical source')
            paragraph_aliases.append({'sentence_id': sentence['id'], 'owner_paragraph_id': owner,
                                      'source_hash': sentence['sourceHash']})
            deduplicated += 1
            continue
        canonical = None
        if sentence['kind'] == 'answer_option':
            letter = re.search(r':([A-G])\Z', sentence['paragraphId'])
            pdf = sentence['context'].get('pdfVerifiedSource')
            if pdf is not None:
                if (not isinstance(pdf, dict) or
                        not isinstance(pdf.get('sourcePdfSha256'), str) or
                        not re.fullmatch(r'[0-9a-f]{64}', pdf['sourcePdfSha256']) or
                        type(pdf.get('pdfPage')) is not int or pdf['pdfPage'] < 1 or
                        pdf.get('anchorKind') != 'figure_bank' or not letter or
                        pdf.get('sourceOptionId') != sentence['paperId'] + ':part-b:' + letter[1]):
                    raise ValueError('PDF option has invalid physical source provenance')
                canonical = (sentence['paperId'], pdf['sourcePdfSha256'], pdf['pdfPage'],
                             pdf['sourceOptionId'], sentence['sourceHash'], sentence['start'], sentence['end'])
            elif (letter and context.get('reflowBlockIds') and
                  type(context.get('reflowOptionIndex')) is int and context['reflowOptionIndex'] >= 0):
                block_ids = context['reflowBlockIds']
                if (not isinstance(block_ids, list) or len(block_ids) != 1 or
                        not isinstance(block_ids[0], str) or
                        not block_ids[0].startswith(sentence['paperId'] + ':b-')):
                    raise ValueError('Option has invalid exact reflow provenance')
                canonical = (sentence['paperId'], block_ids[0], context['reflowOptionIndex'],
                             letter[1], sentence['sourceHash'], sentence['start'], sentence['end'])
            else:
                ambiguous.append(sentence['id'])
        if canonical is not None and canonical in options:
            old = options[canonical]
            if any(old[key] != sentence[key] for key in ('english', 'translationZh', 'alignments')):
                raise ValueError('相同选项物理来源产生不同英文、中文或对齐，不能自动去重')
            old['source_sentence_ids'].append(sentence['id'])
            old['duplicate_source_contexts'].append(copy.deepcopy(sentence['context']))
            deduplicated += 1
            continue
        item = copy.deepcopy(sentence)
        item['canonical_occurrence_key'] = list(canonical) if canonical is not None else [sentence['id']]
        item['source_sentence_ids'] = [sentence['id']]
        item['duplicate_source_contexts'] = []
        if canonical is not None:
            options[canonical] = item
        selected.append(item)
    return selected, {'deduplicated_answer_option_sentences': deduplicated,
                      'answer_option_sentences_without_physical_provenance': ambiguous,
                      'answer_option_paragraph_aliases': paragraph_aliases}


def _printed_text(value):
    """Ignore print whitespace around punctuation without joining English words."""
    from .occurrence_exclusions import printed_text_map
    return printed_text_map(value)[0]


def _published_codex_index(root, report):
    """Study URLs must point at the same immutable reviewed static sentence data."""
    directory = root / 'data/sources/exam-library/structured/codex-translations/kaoyan'
    path = directory / 'manifest.json'
    if not path.is_file():
        raise ValueError('Reviewed Codex reader sidecars have not been published locally')
    raw = path.read_bytes()
    public = json.loads(raw)
    if (public.get('schema') != 'codex-exam-static-manifest.v1' or
            public.get('scope') != 'full' or public.get('semanticReviewStatus') != 'approved' or
            public.get('indexManifestHash') != report['manifest_sha256'] or
            public.get('inputManifestHash') != report['input_manifest_sha256'] or
            public.get('totals') != {key: report[key] for key in
                                    ('papers', 'paragraphs', 'sentences', 'alignments', 'blocked')}):
        raise ValueError('Published Codex reader sidecars do not match current reviewed index')
    rows = public.get('papers')
    if not isinstance(rows, list):
        raise ValueError('Invalid published Codex paper inventory')
    expected = {key.removeprefix('index/').removesuffix('.json') for key in report['source_files']
                if key.startswith('index/') and key != 'index/manifest.json'}
    seen, watched = set(), {path: hashlib.sha256(raw).hexdigest()}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('paperId'), str):
            raise ValueError('Invalid published Codex paper row')
        name = row['paperId'].removeprefix('kaoyan:')
        if (row['paperId'] != 'kaoyan:' + name or name not in expected or name in seen or
                row.get('file') != name + '.json' or
                row.get('sha256') != report['source_files']['index/' + name + '.json'] or
                any(row.get(field) != report['source_files'][folder + '/' + name + '.json']
                    for field, folder in [('inputHash', 'inputs'), ('translationHash', 'translations'),
                                          ('reviewHash', 'reviews')])):
            raise ValueError('Published Codex paper identity/hash mismatch')
        candidate = (directory / row['file']).resolve(strict=True)
        if not candidate.is_relative_to(directory.resolve(strict=True)):
            raise ValueError('Published Codex sidecar escapes its directory')
        observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if observed != row['sha256']:
            raise ValueError('Published Codex sidecar content changed')
        watched[candidate] = observed
        seen.add(name)
    if seen != expected:
        raise ValueError('Published Codex sidecars do not cover every reviewed paper')
    return watched


def _codex_examples(root, cards, base_url, reader, maximum, staging_root, allow_partial,
                    *, reading_completion_path=None):
    from .codex_exam_index import load_codex_exam_index
    from .occurrence_exclusions import load_occurrence_exclusions
    from .reading_completion import load_reading_completions, option_range, original_range
    from .sentence_insertion import insertion_option_source, prepare_sentence_insertions
    from .option_context import context_target_ranges, prepare_option_contexts
    from .source_paths import display_source_path, prepare_source_paths
    root = Path(root).resolve(strict=True)
    staging_root = staging_root or root / 'data/staging/codex-translations-v1'
    source_sentences, index_report = load_codex_exam_index(staging_root, allow_partial=allow_partial)
    exclusion_path = Path(staging_root) / 'targets/occurrence-exclusions.json'
    exclusions, exclusion_aliases, exclusion_hash = load_occurrence_exclusions(
        exclusion_path, source_sentences, cards)
    consumed_exclusions = set()
    completion_path = (reading_completion_path if reading_completion_path is not None else
                       root / 'data/reading-completions-v1.json')
    completions, completion_watched, completion_report = load_reading_completions(
        root, completion_path, source_sentences, index_report)
    insertions, insertion_watched, insertion_report = prepare_sentence_insertions(
        root, source_sentences, index_report)
    if set(completions) & set(insertions):
        raise ValueError('Question and passage completions overlap')
    completions.update(insertions)
    joined_translation_path = Path(completion_path).with_name('reading-option-translations-v1.json')
    if allow_partial and (reading_completion_path is None or not joined_translation_path.exists()):
        joined_translation_path = None
    option_contexts, option_watched, option_report, _ = prepare_option_contexts(
        root, source_sentences, index_report, completions,
        joined_translation_path=joined_translation_path)
    source_paths, question_paths, source_watched, source_report = prepare_source_paths(
        root, source_sentences, allow_partial=allow_partial)
    by_source_id = {sentence['id']: sentence for sentence in source_sentences}
    sentences, deduplication = _canonical_codex_sentences(source_sentences)
    canonical_by_source_id = {sid: sentence for sentence in sentences
                              for sid in sentence['source_sentence_ids']}
    paper_ids = {sentence['paperId'] for sentence in source_sentences}
    watched = {Path(staging_root) / relative: sha for relative, sha in index_report['source_files'].items()}
    watched.update(completion_watched)
    watched.update(insertion_watched)
    watched.update(option_watched)
    watched.update(source_watched)
    if not allow_partial:
        watched.update(_published_codex_index(root, index_report))
    kinds = {}
    for sentence in sentences:
        counts = kinds.setdefault(sentence['kind'], {'paragraph_ids': set(), 'sentences': 0})
        counts['paragraph_ids'].add(sentence['paragraphId']); counts['sentences'] += 1
    years = [int(paper.split(':')[1][:4]) for paper in paper_ids]
    corpus = {'scope': 'codex_reviewed_english_sentences', 'index_scope': index_report['scope'],
        'semantic_review_status': index_report['semantic_review_status'], 'paper_count': len(paper_ids),
        'paper_ids': sorted(paper_ids), 'year_start': min(years), 'year_end': max(years),
        'paragraph_count': index_report['paragraphs'], 'sentence_count': len(sentences),
        'raw_index_sentence_count': len(source_sentences),
        'kinds': {kind: {'paragraphs': len(counts['paragraph_ids']), 'sentences': counts['sentences']}
                  for kind, counts in sorted(kinds.items())},
        'sentences_without_aligned_translation': 0, 'missing_translation_policy': 'fail_closed',
        'reading_completion_frequency_policy': 'printed_original_occurrences_only',
        **deduplication}
    result, no_examples, total, anchor_kinds, missing_anchors = [], [], 0, {}, set()
    skipped_word_options = 0
    deduplicated_correct_options = 0
    for card in cards:
        item = copy.deepcopy(card); item['examples'] = []; matches = []
        # Codex builds cannot silently import old wordbook or guessed inflections.
        forms = card_match_forms(card) if 'local_dictionary' in card else set()
        variants = word_variants(card['word'], forms, infer=False)
        pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(x) for x in sorted(
            variants, key=lambda x: (-len(x), x))) + r')(?!\w)', re.I) if variants else None
        def accepted_ranges(sentence, candidate_ranges):
            eligible = []
            for start, end in candidate_ranges:
                keys = [(sid, card['id'], start, end) for sid in sentence.get(
                    'source_sentence_ids', [sentence['id']])]
                rejected = {key for key in keys if key in exclusions}
                for key in keys:
                    rejected.update(exclusion_aliases.get(key, ()))
                consumed_exclusions.update(rejected)
                if not rejected:
                    eligible.append((start, end))
            return eligible
        for sentence in sentences:
            raw_ranges = accepted_ranges(sentence, [(match.start(), match.end())
                for match in pattern.finditer(sentence['english'])] if pattern else [])
            if raw_ranges:
                matches.append((sentence['paperId'], sentence['id'], 0, len(raw_ranges)))
            completion = completions.get(sentence['id'])
            option_context = option_contexts.get(sentence['id'])
            derived = option_context or completion
            display = derived['completedEnglish'] if derived else sentence['english']
            ranges, stem_ranges, answer_targets = [], [], []
            if option_context:
                ranges = context_target_ranges(option_context, sentence, raw_ranges)
                stem_ranges = raw_ranges
            elif completion:
                candidates = [(match.start(), match.end()) for match in pattern.finditer(display)] if pattern else []
                for span in candidates:
                    old_span = original_range(completion, span)
                    if completion.get('completionType') == 'sentence_insertion':
                        answer_target = insertion_option_source(completion, span, by_source_id)
                    else:
                        answer_span = option_range(completion, span)
                        answer_target = ((by_source_id[completion['optionSentenceId']], answer_span)
                                         if answer_span is not None else None)
                    if old_span is not None and accepted_ranges(sentence, [old_span]):
                        ranges.append(span); stem_ranges.append(old_span)
                    elif answer_target is not None:
                        answer_sentence, answer_span = answer_target
                        physical_owner = canonical_by_source_id.get(answer_sentence['id'], answer_sentence)
                        if accepted_ranges(physical_owner, [answer_span]):
                            ranges.append(span); answer_targets.append(answer_target)
            else:
                ranges = raw_ranges
                stem_ranges = raw_ranges
            if not ranges:
                continue
            if standalone_word_option(display, sentence['kind']):
                skipped_word_options += 1
                continue
            if maximum and not option_contexts and len(item['examples']) >= maximum:
                continue
            displayed_source = display_source_path(source_paths[sentence['id']],
                question_record=question_paths.get(derived['questionId']) if derived else None,
                option_label=option_context['candidateOptionLabel'] if option_context else
                             completion['optionLabel'] if completion else None)
            example = {'text': display,
                'translation': derived['translationZh'] if derived else sentence['translationZh'],
                'translation_scope': option_context['translationScope'] if option_context else 'sentence',
                'translation_source': 'codex',
                'translation_alignment': copy.deepcopy(derived['translation_alignment'] if derived
                                                       else sentence['translation_alignment']),
                'matched_english_ranges': [list(span) for span in ranges],
                'source': displayed_source,
                'kind': sentence['kind'],
                'cloze_answers': ([{'start': derived['insertedRange'][0],
                    'end': derived['insertedRange'][1],
                    'word': display[slice(*derived['insertedRange'])],
                    'number': int(derived['answerNumber'])}] if derived else
                    copy.deepcopy(sentence['cloze_answers'])), 'reader': reader,
                'paragraph_id': sentence['paragraphId'], 'sentence_id': sentence['id'],
                'english_hash': derived['englishHash'] if derived else sentence['englishHash'],
                'translation_hash': derived['translationHash'] if derived else sentence['translationHash'],
                'reviewed_content_hash': sentence['reviewedContentHash'],
                'source_hash': sentence['sourceHash'], 'source_english': sentence['sourceEnglish'],
                'filled_english': sentence['filledEnglish'],
                'sentence_range': [sentence['start'], sentence['end']],
                'source_context': copy.deepcopy(sentence['context']),
                'source_block_ids': copy.deepcopy(sentence['sourceBlockIds']),
                'source_fragments': copy.deepcopy(sentence['sourceFragments']),
                'source_sentence_refs': copy.deepcopy(sentence['sourceSentenceRefs']),
                'canonical_occurrence_key': copy.deepcopy(sentence['canonical_occurrence_key']),
                'source_sentence_ids': copy.deepcopy(sentence['source_sentence_ids']),
                'duplicate_source_contexts': copy.deepcopy(sentence['duplicate_source_contexts'])}
            anchor_sentence = sentence if stem_ranges else answer_targets[0][0]
            anchor_ranges = (stem_ranges if stem_ranges else
                [span for row, span in answer_targets if row['id'] == anchor_sentence['id']])
            if derived:
                field = ('option_context' if option_context else 'sentence_insertion_completion'
                         if completion.get('completionType') == 'sentence_insertion' else 'reading_completion')
                example[field] = copy.deepcopy(derived)
                example['source_target_ranges'] = [list(span) for span in anchor_ranges]
                source_targets = {}
                for row, span in [(sentence, span) for span in stem_ranges] + answer_targets:
                    target = source_targets.setdefault(row['id'], {
                        'sentence_id': row['id'], 'english_hash': row['englishHash'],
                        'reviewed_content_hash': row['reviewedContentHash'], 'ranges': []})
                    target['ranges'].append(list(span))
                example['source_target_refs'] = list(source_targets.values())
            example['source_anchor'] = {'kind': 'codex_reviewed_sentence',
                'sentence_id': anchor_sentence['id'], 'english_hash': anchor_sentence['englishHash'],
                'reviewed_content_hash': anchor_sentence['reviewedContentHash']}
            params = {'anki-codex-sentence': anchor_sentence['id'],
                      'anki-codex-hash': anchor_sentence['englishHash'],
                      'anki-codex-review': anchor_sentence['reviewedContentHash'],
                      'anki-codex-en': json.dumps([list(span) for span in anchor_ranges], separators=(',', ':'))}
            stem = sentence['paperId'].split(':')[1]
            example['latex_url'] = base_url.rstrip('/') + '/english-exams-reflow-latex/kaoyan/papers/' + stem + '.htm?' + urlencode(params)
            example['full_paper_url'] = base_url.rstrip('/') + '/exam-library/practice/full-paper.htm?' + urlencode({'paper': sentence['paperId'], **params})
            item['examples'].append(example)
        retained_completions = {(example['reading_completion']['questionId'], example['text']): example
            for example in item['examples'] if 'reading_completion' in example}
        filtered = []
        for example in item['examples']:
            context = example.get('option_context')
            owner = (retained_completions.get((context['questionId'], example['text']))
                     if context and context['isCorrectCandidate'] else None)
            if owner is not None:
                owner['source'] = display_source_path(source_paths[owner['sentence_id']],
                    question_record=question_paths.get(context['questionId']),
                    option_label=context['candidateOptionLabel'])
                owner.setdefault('deduplicated_option_contexts', []).append({
                    'sentence_id': example['sentence_id'], 'option_context': context,
                    'source_target_refs': copy.deepcopy(example['source_target_refs'])})
                # Only a merged two-way completion frames both printed parts.
                # Ordinary prompt/option links retain their original single pin.
                def outline_refs(refs):
                    return [{'id': ref['sentenceId'], 'englishHash': ref['englishHash'],
                             'reviewedContentHash': ref['reviewedContentHash']}
                            for ref in refs]
                outline_context = {'questionId': context['questionId'],
                    'optionLabel': context['candidateOptionLabel'],
                    'stem': outline_refs(context['stemSentenceRefs']),
                    'option': outline_refs(context['optionSentenceRefs'])}
                query = urlencode({'anki-codex-context': json.dumps(
                    outline_context, separators=(',', ':'))})
                for field in ('latex_url', 'full_paper_url'):
                    owner[field] += '&' + query
                deduplicated_correct_options += 1
            else:
                filtered.append(example)
        item['examples'] = filtered[:maximum] if maximum else filtered
        anchor_kinds['codex_reviewed_sentence'] = (anchor_kinds.get('codex_reviewed_sentence', 0) +
                                                 len(item['examples']))
        item['exam_frequency'] = frequency_for_matches(matches, len(paper_ids))
        total += len(item['examples'])
        if not item['examples']:
            no_examples.append(card['word'])
        result.append(item)
    if any(hashlib.sha256(path.read_bytes()).hexdigest() != expected for path, expected in watched.items()):
        raise ValueError('生成 Codex 例句时原句锚点来源发生变化')
    if set(exclusions) != consumed_exclusions:
        raise ValueError('Occurrence exclusion does not match a declared dictionary form')
    if exclusion_hash and hashlib.sha256(exclusion_path.read_bytes()).hexdigest() != exclusion_hash:
        raise ValueError('Occurrence exclusions changed during matching')
    return result, {'papers': len(paper_ids), 'paragraphs': index_report['paragraphs'],
        'cards': len(result), 'examples': total, 'cards_without_library_examples': len(no_examples),
        'words_without_library_examples': no_examples, 'database_modified': False,
        'translation_scope': 'codex_reviewed_sentence', 'sentence_source': 'codex',
        'sentences_without_aligned_translation': 0, 'skipped_unaligned_matches': 0,
        'skipped_standalone_word_option_matches': skipped_word_options,
        'example_policy': 'bare_word_options_counted_but_not_displayed',
        'default_reader': reader, 'codex_index': index_report, **deduplication,
        'reading_completions': completion_report,
        'sentence_insertions': insertion_report,
        'option_contexts': {**option_report,
            'deduplicated_correct_option_examples': deduplicated_correct_options},
        'source_paths': source_report,
        'excluded_homograph_occurrences': len(consumed_exclusions), 'exclusions_sha256': exclusion_hash,
        'source_anchor_kinds': anchor_kinds, 'sentences_without_source_anchor': sorted(missing_anchors),
        'frequency': frequency_report(result, corpus)}
