"""Reconcile the generated package against the preceding package and source pins."""
from collections import Counter
import copy
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit
import zipfile
from lxml import html


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def notes(path, directory, name):
    with zipfile.ZipFile(path) as archive:
        database = directory / (name + '.sqlite3')
        database.write_bytes(archive.read('collection.anki2'))
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as connection:
        return {guid: fields.split('\x1f') for guid, fields in connection.execute('select guid,flds from notes')}


def examples(field):
    document = html.fragment_fromstring(field, create_parent='div')
    rows = []
    for element in document.xpath('.//li[@class="example-card"]'):
        english = element.xpath('.//span[@class="example-text"]')[0]
        chinese = element.xpath('.//span[@class="example-translation"]')[0]
        badge = chinese.xpath('.//span[@class="translate-tag"]')[0]
        def text_with_breaks(element):
            copied = copy.deepcopy(element)
            for br in copied.xpath('.//br'):
                br.text = '\n'
            return copied.text_content()
        text = text_with_breaks(chinese)[len(badge.text_content()):].lstrip()
        link = element.xpath('.//a[@class="sentence-jump"]')[0]
        params = parse_qs(urlsplit(link.get('href')).query)
        rows.append({'id': params['anki-codex-sentence'][0], 'en': text_with_breaks(english),
                     'zh': text, 'link': link.get('href'), 'element': element,
                     'english': english, 'chinese': chinese})
    return rows


def marked_ranges(element):
    """Read rendered mark offsets independently of the packaging renderer."""
    ranges = []
    position = 0

    def walk(node):
        nonlocal position
        start = position
        if node.tag == 'br':
            position += 1
            return
        position += len(node.text or '')
        for child in node:
            walk(child)
            position += len(child.tail or '')
        if node.tag == 'mark' and node.get('class') == 'target-word':
            ranges.append((start, position))

    walk(element)
    return set(ranges)


def main():
    if not __debug__:
        raise RuntimeError('Delivery verification requires validation; optimized Python is unsupported')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / 'output'
    backup = args.backup.resolve(strict=True)
    manifest = json.loads((backup / 'manifest.json').read_text())
    database_pin = next(row['sha256'] for row in manifest['files'] if row['path'] == 'data/anki.sqlite3')
    assert sha(root / 'data/anki.sqlite3') == database_pin, 'Source database changed'
    sidecar = json.loads((root / 'data/reading-completions-v1.json').read_text())
    completion = {row['sentenceId']: row for row in sidecar['rows']}
    insertion_path = output / 'sentence-insertion-completion-review.json'
    insertions = json.loads(insertion_path.read_text())['rows']
    insertion_review = json.loads((output / 'sentence-insertion-semantic-review.json').read_text())
    assert insertion_review['status'] == 'approved'
    assert insertion_review['inputSHA'] == sha(insertion_path)
    assert set(insertion_review['reviewedIds']) == {row['sentenceId'] for row in insertions}
    assert not insertion_review['findings']
    question_count = len(completion)
    assert not set(completion) & {row['sentenceId'] for row in insertions}
    completion.update({row['sentenceId']: row for row in insertions})
    completion_by_display = {}
    for item in completion.values():
        for sid in {item['sentenceId'], *item.get('optionSentenceIds', []),
                    *([item['optionSentenceId']] if 'optionSentenceId' in item else [])}:
            completion_by_display.setdefault((sid, item['completedEnglish']), []).append(item)
    option_path = output / 'reading-option-context-review.json'
    option_payload = json.loads(option_path.read_text())
    option_contexts = copy.deepcopy(option_payload['rows'])
    sys.path.insert(0, str(root))
    from anki_pipeline.option_translation import context_hash, load_option_translations
    from anki_pipeline.text import word_variants
    frozen_path = output / 'reading-option-translation-review/source-context-registry.json'
    frozen = json.loads(frozen_path.read_text())
    current_web = json.loads((output / 'web-preview-report.json').read_text())
    approved_translations, _, translation_report = load_option_translations(
        root / 'data/reading-option-translations-v1.json', frozen['rows'],
        current_web['exam_library']['codex_index'])
    frozen_by_id = {row['sentenceId']: row for row in frozen['rows']}
    assert sha(frozen_path) == json.loads((root / 'data/reading-option-translations-v1.json').read_text())['sourceRegistrySha256']
    assert len(approved_translations) == 2614
    assert len(option_contexts) - len(approved_translations) == 637
    # This inventory deliberately records the original approved stem/option
    # translations. The independently reviewed sidecar supplies delivery text.
    # Reconstruct its expected display without overwriting the source inventory.
    for context in option_contexts:
        if context['sentenceId'] in approved_translations:
            translation = approved_translations[context['sentenceId']]
            context.update(translationZh=translation,
                           translationHash=hashlib.sha256(translation.encode()).hexdigest(),
                           translationScope='independently_reviewed_complete_candidate_translation',
                           newTranslationAuthored=True)
    option_by_id, option_by_display = {}, {}
    for item in option_contexts:
        for sid in item['optionSentenceIds']:
            assert sid not in option_by_id, 'An original option has multiple derived identities'
            option_by_id[sid] = item
            option_by_display[(sid, item['completedEnglish'])] = item
    sources = {}
    for path in (root.parent / 'exam-library/data/staging/codex-translations-v1/index').glob('*.json'):
        if path.name != 'manifest.json':
            sources.update({row['id']: row for row in json.loads(path.read_text())['sentences']})
    for context in option_contexts:
        assert context_hash(context) == context_hash(frozen_by_id[context['sentenceId']]), 'Candidate source context changed'
        if context['sentenceId'] in approved_translations:
            assert context['newTranslationAuthored']
            assert context['translationScope'] == 'independently_reviewed_complete_candidate_translation'
            assert context['translationZh'] == approved_translations[context['sentenceId']]
            assert context['translationHash'] == hashlib.sha256(context['translationZh'].encode()).hexdigest()
        else:
            assert not context['newTranslationAuthored']
            assert context['translationZh'] == frozen_by_id[context['sentenceId']]['translationZh']
        assert context['isCorrectCandidate'] == \
            (context['candidateOptionLabel'] == context['correctOptionLabel'])
        for ref in [*context['stemSentenceRefs'], *context['optionSentenceRefs']]:
            source = sources[ref['sentenceId']]
            assert ref['paragraphId'] == source['paragraphId']
            assert ref['range'] == [source['start'], source['end']]
            assert ref['sourceBlockIds'] == source['sourceBlockIds']
            assert all(ref[key] == source[key] for key in
                       ('english', 'translationZh', 'englishHash', 'translationHash',
                        'sourceHash', 'reviewedContentHash')), 'Restored context source drift'
    completed_count = insertion_count = option_count = merged_option_count = old_count = new_count = 0
    restored_question_marks = 0
    with tempfile.TemporaryDirectory() as temp:
        old = notes(backup / 'output/Anki-本地双词典版.apkg', Path(temp), 'old')
        new = notes(output / 'Anki-本地双词典版.apkg', Path(temp), 'new')
        assert old.keys() == new.keys(), 'Note identities changed'
        for guid, fields in new.items():
            before = old[guid]
            assert len(fields) == len(before) == 10
            assert fields[:7] + fields[8:] == before[:7] + before[8:], 'Non-example fields changed'
            previous = examples(before[7]) if before[7] else []
            current = examples(fields[7]) if fields[7] else []
            old_count += len(previous); new_count += len(current)
            ordinary = Counter((row['id'], row['en'], row['zh'], row['link'])
                               for row in previous if row['id'] not in completion and row['id'] not in option_by_id)
            actual_ordinary = Counter()
            replaced = Counter()
            for row in current:
                displayed_source = row['element'].xpath('.//*[@class="example-source"]')[0].text_content()
                assert not re.search(r'kaoyan:|cet[46]:', displayed_source), 'Internal source identifier remains'
                assert ' ➫ ' in displayed_source, 'Source hierarchy separator missing'
                assert not row['chinese'].xpath('.//mark | .//*[@class="term-highlight"]'), 'Chinese highlight remains'
                assert row['english'].xpath('.//mark[@class="target-word"]'), 'English target highlight missing'
                assert not re.search(r'_{2,}', row['en']), 'Unanswered example blank: ' + row['id']
                params = parse_qs(urlsplit(row['link']).query)
                source = sources[row['id']]
                assert params['anki-codex-hash'] == [source['englishHash']]
                assert params['anki-codex-review'] == [source['reviewedContentHash']]
                assert all(0 <= a < b <= len(source['english']) for a, b in json.loads(params['anki-codex-en'][0]))
                underlines = row['english'].xpath('.//u[@class="cloze-answer"]')
                candidates = [item for item in completion_by_display.get((row['id'], row['en']), [])
                              if len(underlines) == 1 and underlines[0].text_content() ==
                              item['completedEnglish'][slice(*item['insertedRange'])]]
                option = option_by_display.get((row['id'], row['en']))
                if option is not None:
                    assert row['zh'] == option['translationZh'], 'Option context translation changed'
                    assert len(underlines) == 1 and underlines[0].text_content() == \
                        option['completedEnglish'][slice(*option['insertedRange'])]
                    # The combined display must mark every whole-word lemma,
                    # including restored question text. Source coordinates and
                    # printed frequency are reconciled separately above/below.
                    marked = row['english'].xpath('.//mark[@class="target-word"]')
                    heading = html.fragment_fromstring(fields[0], create_parent='div')
                    for br in heading.xpath('.//br'):
                        br.text = '\n'
                    lemma = heading.text_content()
                    variants = word_variants(lemma, infer=False)
                    assert variants, 'Card heading has no exact target lemma'
                    pattern = re.compile(r'(?<!\w)(?:' + '|'.join(
                        re.escape(form) for form in sorted(variants, key=len, reverse=True)
                    ) + r')(?!\w)', re.IGNORECASE)
                    expected = {(match.start(), match.end()) for match in pattern.finditer(row['en'])}
                    assert expected <= marked_ranges(row['english']), \
                        'Restored question target mark missing: ' + repr((lemma, row['id'], expected,
                                                                        marked_ranges(row['english'])))
                    restored_question_marks += sum(not mark.xpath('ancestor::u[@class="cloze-answer"]')
                                                   for mark in marked)
                    option_count += 1
                elif candidates:
                    assert len(candidates) == 1
                    item = candidates[0]
                    assert row['zh'] == item['translationZh']
                    assert len(underlines) == 1
                    assert underlines[0].text_content() == item['completedEnglish'][slice(*item['insertedRange'])]
                    completed_count += 1; replaced[item['sentenceId']] += 1
                    insertion_count += item.get('completionType') == 'sentence_insertion'
                else:
                    actual_ordinary[(row['id'], row['en'], row['zh'], row['link'])] += 1
            assert ordinary == actual_ordinary, 'An unrelated example changed'
            expected_replaced = Counter(row['id'] for row in previous if row['id'] in completion)
            assert all(replaced[sid] >= count for sid, count in expected_replaced.items()), 'Old stem example disappeared'
            current_keys = Counter((row['id'], row['en'], row['zh']) for row in current)
            for old_option in (row for row in previous if row['id'] in option_by_id):
                context = option_by_id[old_option['id']]
                key = (old_option['id'], context['completedEnglish'], context['translationZh'])
                if current_keys[key]:
                    current_keys[key] -= 1
                    continue
                # A correct candidate can merge with the identical already
                # displayed correct completion, while every distractor remains.
                assert context['isCorrectCandidate'], 'A distractor option disappeared'
                same = [row for row in current if row['en'] == context['completedEnglish']
                        and row['zh'] == context['translationZh']
                        and any(item['questionId'] == context['questionId'] for item in
                                completion_by_display.get((row['id'], row['en']), []))]
                assert len(same) == 1, 'Correct option context was dropped without an equivalent completion'
                merged_option_count += 1
    web = json.loads((output / 'web-preview-report.json').read_text())
    prior = json.loads((backup / 'output/web-preview-report.json').read_text())
    assert web['counts']['examples'] == new_count
    assert web['exam_library']['codex_index']['source_files'] == prior['exam_library']['codex_index']['source_files']
    current_frequency = web['exam_library']['frequency']
    previous_frequency = prior['exam_library']['frequency']
    # New explanatory metadata is allowed; every previous statistic must remain identical.
    def contains(actual, expected):
        return all(key in actual and contains(actual[key], value) for key, value in expected.items()) if isinstance(expected, dict) else actual == expected
    assert contains(current_frequency, previous_frequency), 'Printed-source frequency changed'
    with zipfile.ZipFile(output / 'Anki-完整网页预览.zip') as archive:
        assert archive.testzip() is None
        assert web['input_digest'] in archive.read('Anki-完整网页预览/preview-library.html').decode()
    report = {'status': 'passed', 'notes': len(new), 'old_examples': old_count,
              'examples': new_count, 'completed_reading_questions': question_count,
              'completed_sentence_insertion_gaps': len(insertions),
              'completed_sentence_insertion_examples': insertion_count,
              'contextualized_reading_option_paragraphs': len(option_contexts),
              'contextualized_reading_option_examples': option_count,
              'joined_candidate_translations': len(approved_translations),
              'preserved_reviewed_correct_translations': 637,
              'candidate_translation_semantic_corrections': translation_report['semantic_corrections'],
              'source_hierarchy_and_separator_checked': True,
              'merged_correct_option_examples': merged_option_count,
              'completed_reading_examples': completed_count,
              'chinese_highlights': 0, 'unanswered_example_blanks': 0,
              'english_marks_and_answer_underlines_checked': True,
              'restored_question_lemma_marks_checked': True,
              'restored_question_english_marks': restored_question_marks,
              'non_example_fields_identical': True, 'ordinary_example_text_translation_links_identical': True,
              'printed_source_frequency_unchanged': True, 'reviewed_source_files_unchanged': True,
              'source_database_unchanged': True, 'zip_crc_and_version_valid': True,
              'web_version': web['input_digest'], 'package_sha256': sha(output / 'Anki-本地双词典版.apkg'),
              'zip_sha256': sha(output / 'Anki-完整网页预览.zip')}
    (output / 'reading-completion-delivery-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
