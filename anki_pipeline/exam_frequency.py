"""Pure counts and half-star ratings for exact kaoyan sentence matches."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable
import re


SCHEMA = 'kaoyan-frequency.v1'
RULE = 'occurrence-bands.v1'
OCCURRENCE_BANDS = (1, 2, 3, 5, 8, 13, 20, 30, 50, 80)


def _question_number(sentence: dict) -> int | None:
    """Read a question number only within a recognized kaoyan English paper."""
    paper = sentence.get('paperId')
    if not isinstance(paper, str) or not re.fullmatch(r'kaoyan:\d{4}-0[12]', paper):
        return None
    context = sentence.get('context') or {}
    question = context.get('questionId')
    if not isinstance(question, str):
        paragraph = sentence.get('paragraphId', sentence.get('id', ''))
        match = re.match(re.escape(paper) + r':(q-[1-9][0-9]*-[1-9][0-9]*)(?::|$)', paragraph)
        question = paper + ':' + match[1] if match else ''
    match = re.fullmatch(re.escape(paper) + r':q-([1-9][0-9]*)-[1-9][0-9]*', question)
    return int(match[1]) if match else None


def exclude_cloze_option(sentence: dict) -> bool:
    """Exclude printed cloze alternatives, including phrases and correct choices.

    Explicit section identity takes precedence over question numbering. Older
    papers use different reading/cloze number ranges.
    These alternatives have a different physical position from the correctly
    filled passage, which is the sole cloze frequency/example source. Text
    length and lexical shape never determine whether an option is excluded.
    """
    if sentence.get('kind') != 'answer_option':
        return False
    context = sentence.get('context') or {}
    if any(context.get(key) in {'reading', 'matching', 'reading_comprehension'}
           for key in ('kind', 'questionKind', 'sectionKind')):
        return False
    if any(context.get(key) == 'cloze' for key in ('kind', 'questionKind', 'sectionKind')):
        return True
    number = _question_number(sentence)
    year = int(sentence['paperId'][7:11]) if number is not None else 0
    return year >= 2005 and number is not None and 1 <= number <= 20


def sentence_usage(sentence: dict, *, option_context: dict | None = None,
                   completion: dict | None = None) -> dict:
    """Classify an original occurrence without counting its derived display.

    Callers can reuse the reviewed option context/completion lookup to obtain
    verified correctness; an unverified reading option always stays unknown.
    """
    kind = sentence['kind']
    role = {'cloze': 'cloze_passage', 'reading': 'reading_passage',
            'question_prompt': 'question_stem'}.get(kind, kind)
    correctness = 'not_applicable'
    number = _question_number(sentence)
    if kind == 'answer_option' and (option_context is not None or
                                    number is not None and 21 <= number <= 40):
        role = 'reading_option'
        verified = option_context.get('isCorrectCandidate') if option_context else None
        correctness = ('correct' if verified is True else
                       'incorrect' if verified is False else 'unknown')
        if completion is not None and sentence['id'] == completion.get('optionSentenceId'):
            correctness = 'correct'
    return {'source_kind': kind, 'source_role': role,
            'reading_candidate_correctness': correctness}


def frequency_breakdown_for_matches(matches: Iterable[tuple[str, str, int, int, dict]],
                                    *, excluded_cloze_option_occurrences: int = 0) -> dict:
    """Summarize each accepted original source once, independent of display caps."""
    _nonnegative_integer(excluded_cloze_option_occurrences, 'excluded_cloze_option_occurrences')
    sources = {}
    for paper, paragraph, index, count, usage in matches:
        identity = (paper, paragraph, index)
        _nonnegative_integer(count, 'occurrences')
        value = (count, usage)
        if identity in sources and sources[identity] != value:
            raise ValueError('frequency breakdown source identity has conflicting metadata')
        sources[identity] = value
    groups = {key: Counter() for key in
              ('source_kind', 'source_role', 'reading_candidate_correctness')}
    for count, usage in sources.values():
        for key, totals in groups.items():
            label = usage[key]
            if count and label != 'not_applicable':
                totals[label] += count
    return {'schema': 'kaoyan-frequency-breakdown.v1',
            'occurrences': sum(count for count, _ in sources.values()),
            **{key: dict(sorted(totals.items())) for key, totals in groups.items()},
            'excluded_cloze_option_occurrences': excluded_cloze_option_occurrences}


def _nonnegative_integer(value: int, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f'{label} must be a nonnegative integer')


def frequency_stars(occurrences: int) -> float:
    """Return the fixed 0–5 rating, in half-star steps, for a token count."""
    _nonnegative_integer(occurrences, 'occurrences')
    return bisect_right(OCCURRENCE_BANDS, occurrences) / 2


def frequency_for_matches(matches: Iterable[tuple[str, str, int, int]],
                          corpus_papers: int) -> dict:
    """Count tokens once per (paper, paragraph, sentence) source identity.

    Distinct source positions remain distinct even when their English text is
    identical. A repeated identity must carry the same count or it is rejected.
    """
    _nonnegative_integer(corpus_papers, 'corpus_papers')
    sources = {}
    for paper_id, paragraph_id, sentence_index, occurrences in matches:
        if (not isinstance(paper_id, str) or not paper_id.strip() or
                not isinstance(paragraph_id, str) or not paragraph_id.strip()):
            raise ValueError('frequency source identity must contain paper and paragraph IDs')
        _nonnegative_integer(sentence_index, 'sentence_index')
        _nonnegative_integer(occurrences, 'occurrences')
        identity = (paper_id, paragraph_id, sentence_index)
        if identity in sources and sources[identity] != occurrences:
            raise ValueError('frequency source identity has conflicting token counts')
        sources[identity] = occurrences
    matched = {identity: count for identity, count in sources.items() if count}
    occurrences = sum(matched.values())
    matched_sentences = len(matched)
    paper_count = len({identity[0] for identity in matched})
    if not 0 <= paper_count <= matched_sentences <= occurrences or paper_count > corpus_papers:
        raise ValueError('frequency counts exceed the corpus or violate count relationships')
    return {'schema': SCHEMA, 'occurrences': occurrences,
            'matched_sentences': matched_sentences, 'paper_count': paper_count,
            'corpus_papers': corpus_papers, 'stars': frequency_stars(occurrences),
            'rule': RULE}


def frequency_report(cards: list[dict], corpus: dict) -> dict:
    """Describe the actual indexed corpus and aggregate the per-card counts.

    Total occurrences sum matches across cards; they are not a distinct corpus
    token count when separate card headwords share an explicitly declared form.
    """
    frequencies = [card['exam_frequency'] for card in cards]
    distribution = Counter(str(frequency['stars']) for frequency in frequencies)
    return {'schema': SCHEMA, 'rule': RULE,
            'bands': [{'minimum': minimum, 'stars': (index + 1) / 2}
                      for index, minimum in enumerate(OCCURRENCE_BANDS)],
            'total_occurrences': sum(frequency['occurrences'] for frequency in frequencies),
            'nonzero_cards': sum(frequency['occurrences'] > 0 for frequency in frequencies),
            'star_distribution': {str(index / 2): distribution[str(index / 2)]
                                  for index in range(11)},
            'corpus': corpus,
            'cards': [{'id': card['id'], 'word': card['word'],
                       'exam_frequency': dict(card['exam_frequency'])} for card in cards]}
