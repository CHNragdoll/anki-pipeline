"""Pure counts and half-star ratings for exact kaoyan sentence matches."""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable


SCHEMA = 'kaoyan-frequency.v1'
RULE = 'occurrence-bands.v1'
OCCURRENCE_BANDS = (1, 2, 3, 5, 8, 13, 20, 30, 50, 80)


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
