"""Exact restoration, stable fitting and UTF-8 budget contracts."""
import json
import pickle
import random
import unittest

from anki_pipeline.slim_shared_codec import (
    DICTIONARY_SCHEMA, MAX_SAFE_INTEGER, SharedDictionary,
    dictionary_json, expand, factor, fit, prepare_dictionary, tokenize,
)


class SharedCodecTests(unittest.TestCase):
    def test_html_and_json_tokenization_preserves_every_character(self):
        cases = [
            '', '<', ' \n<div class="sf-example"><b>目标词</b> 译文\r\n</div>',
            '<span title="a > b">引号 " 和 \\ 路径</span>',
            '{"source":"中国\\n例句","quotes":"a\\\"b\\\\c","n":1}',
            '["<script>字面证据</script>","\\u4e2d",null]',
            '裸文本  👍 e\u0301 / é\r\n \\ " stray',
            '"not complete JSON \\',
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(''.join(tokenize(raw)), raw)
                self.assertEqual(expand(factor(raw, ()), ()), raw)

    def test_fitted_dictionary_restores_complete_html_and_json(self):
        sources = [
            '<p class="sf-en">原句与 target word。</p><p class="sf-zh">原译文。</p>',
            '<p class="sf-en">原句与 another word。</p><p class="sf-zh">原译文。</p>',
            '{"schema":"proof.v1","translation":"原译文。","source":"原句与 target word。"}',
        ] * 3
        dictionary = fit(sources, 2048)
        self.assertIsInstance(dictionary, SharedDictionary)
        self.assertTrue(dictionary)
        for raw in sources:
            pieces = factor(raw, dictionary, index=dictionary.indices)
            self.assertTrue(any(isinstance(piece, int) for piece in pieces))
            self.assertEqual(expand(pieces, dictionary), raw)

    def test_missing_adjacent_tokens_are_one_literal(self):
        raw = '<i>只出现一次，保持原样。</i>'
        self.assertEqual(factor(raw, ()), [raw])
        self.assertEqual(factor('', ()), [])
        raw_json = '{"key":"不可分割字串","quoted":"原\\\"引号"}'
        self.assertEqual(factor(raw_json, ()), [raw_json])

    def test_exact_budget_includes_utf8_escaping_envelope_and_commas(self):
        sources = [json.dumps({'quoted': '\\"中文👍\n' * 3, 'other': '字符' * 9}, ensure_ascii=False)] * 5
        empty_size = len(dictionary_json(()).encode('utf-8'))
        for budget in (empty_size, empty_size + 10, 128, 256, 1024):
            dictionary = fit(sources, budget)
            raw = dictionary_json(dictionary)
            self.assertLessEqual(len(raw.encode('utf-8')), budget)
            self.assertEqual(json.loads(raw)['schema'], DICTIONARY_SCHEMA)
            for source in sources:
                self.assertEqual(expand(factor(source, dictionary), dictionary), source)

    def test_fitting_is_stable_and_factory_is_consumed_once(self):
        sources = ['<p>long common sentence</p>', '<p>long common sentence</p>',
                   '{"long property":"long common sentence"}'] * 3
        calls = []
        def iterator():
            calls.append(True)
            yield from sources
        first = fit(iterator, 4096)
        shuffled = list(sources)
        random.Random(11).shuffle(shuffled)
        self.assertEqual(first, fit(shuffled, 4096))
        self.assertEqual(calls, [True])

    def test_density_prefers_reusable_short_tokens_to_one_enormous_literal(self):
        short = '<p class="repeated-token">'
        huge = 'unique huge srcdoc literal ' * 55
        sources = ['<div>' + short + 'text</p></div>'] * 60 + [json.dumps([huge])] * 2
        density = fit(sources, 1600, strategy='density')
        total = fit(sources, 1600, strategy='score')
        self.assertEqual(density[0], short)
        self.assertNotEqual(total[0], short)
        for dictionary in (density, total):
            for raw in sources:
                self.assertEqual(expand(factor(raw, dictionary), dictionary), raw)

    def test_token_cap_and_strategies_preserve_all_excluded_literals(self):
        sources = [json.dumps({'large': '长' * 500, 'frequent': '重复的字串'}, ensure_ascii=False)] * 3
        for strategy in ('density', 'frequency', 'score'):
            dictionary = fit(sources, 4096, strategy=strategy, max_token_bytes=512)
            self.assertTrue(all(len(token.encode('utf-8')) <= 512 for token in dictionary))
            for raw in sources:
                self.assertEqual(expand(factor(raw, dictionary), dictionary), raw)
        for bad in (True, 0, -1, 1.5):
            with self.assertRaises(ValueError):
                fit(sources, max_token_bytes=bad)
        with self.assertRaises(ValueError):
            fit(sources, strategy='unsupported')

    def test_default_frequency_keeps_frequent_short_tags_and_json_structure(self):
        sources = ['<p></p>', '{"id":0}'] * 5
        dictionary = fit(sources, 4096)
        for short in ('<p>', '</p>', '"id"', '{', ':0}'):
            self.assertIn(short, dictionary)
            self.assertLessEqual(len(short.encode('utf-8')), 6)
        self.assertEqual(dictionary, fit(sources, 4096, strategy='freq'))
        self.assertEqual(dictionary, fit(sources, 4096, strategy='frequency'))
        for raw in sources:
            self.assertEqual(expand(factor(raw, dictionary), dictionary), raw)

    def test_dictionary_and_prepared_index_are_immutable(self):
        dictionary = SharedDictionary(['<div>', '</div>'])
        self.assertIs(prepare_dictionary(dictionary), dictionary)
        with self.assertRaises(TypeError):
            dictionary.indices['<div>'] = 10
        with self.assertRaises(AttributeError):
            dictionary.indices = {}
        self.assertEqual(json.loads(dictionary_json(dictionary))['strings'], ['<div>', '</div>'])
        restored = pickle.loads(pickle.dumps(dictionary))
        self.assertEqual(restored, dictionary)
        self.assertEqual(dict(restored.indices), dict(dictionary.indices))

    def test_bad_types_and_dictionary_conflicts_are_rejected(self):
        for strings in ('abc', b'abc', [None], [1], ['dup', 'dup']):
            with self.subTest(strings=strings), self.assertRaises(ValueError):
                prepare_dictionary(strings)
        with self.assertRaises(ValueError):
            tokenize(None)
        for budget in (-1, True, 1.5, 0):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                fit([], budget)
        with self.assertRaises(ValueError):
            fit('not an iterable of whole assets')

    def test_invalid_reference_types_and_extreme_indices_are_rejected(self):
        dictionary = SharedDictionary(['known string'])
        for invalid in (True, False, None, 1.0, -1, 1, MAX_SAFE_INTEGER, MAX_SAFE_INTEGER + 1, {}, []):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                expand([invalid], dictionary)
        for invalid in ('raw pieces', b'raw pieces', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                expand(invalid, dictionary)

    def test_prepared_index_cannot_silently_point_to_another_token(self):
        dictionary = SharedDictionary(['<p>', '</p>'])
        for index in ({'<p>': True}, {'<p>': 1}, {'<p>': -1}, {'<p>': 9}, []):
            with self.subTest(index=index), self.assertRaises(ValueError):
                factor('<p>字面</p>', dictionary, index)

    def test_fuzz_round_trips_without_unicode_or_escape_normalization(self):
        rng = random.Random(9817)
        alphabet = 'abc目标词👍é\u0301\\"\n\t<>[]{}:; '
        corpus = [json.dumps({'text': ''.join(rng.choice(alphabet) for _ in range(90)),
                              'original': '完整审核说明'}, ensure_ascii=False) for _ in range(100)]
        dictionary = fit(corpus, 8192)
        for raw in corpus:
            self.assertEqual(expand(factor(raw, dictionary, dictionary.indices), dictionary), raw)


if __name__ == '__main__':
    unittest.main()
