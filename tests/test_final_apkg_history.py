"""Offline history must select exactly the browser's one audited sentence."""
import html
import hashlib
import json
from pathlib import Path
import re
import unittest

from anki_pipeline.final_apkg_history import HistoryError, HistoryMaterializer, materialize_history


URL = '/exam-usage-policy-20261012/full-2027-v4/history/' + 'a' * 64 + '.html'
PARENT = '/sense-frequency-20261011/context-supplement-v1/changed-native-2027-v1/web-preview/' + 'b' * 64 + '/cards/' + 'c' * 64 + '.html'


def record(reason='old reason', source='2024 阅读 Text 3', target='training',
           english=None, chinese='原文翻译', extra=''):
    english = english or 'AI model <mark class="target-word">' + target + '</mark>.'
    return ('<article class="sf-archived-example" data-sf-year="2024"><p class="sf-source">' +
            html.escape(source) + '</p><div class="sf-sentence-pair"><p class="sf-en">' +
            english + '</p><p class="sf-zh">' + chinese + '</p></div><p class="sf-reason">' +
            html.escape('义项依据：' + reason) + '</p>' + extra + '</article>')


def archive(records=None, evidence='<html><script>original()</script>全稿 & proof</html>'):
    return ('<!doctype html><html><head><script>archive()</script></head><body>' +
            (record() if records is None else records) + '<details><summary>完整原 HTML 证据</summary>' +
            '<pre>' + html.escape(evidence) + '</pre></details></body></html>')


def disclosure(reason='old reason', source='2024 阅读 Text 3', target='training', url=URL,
               fallback=False):
    identity = ('<div class="sf-example"><p class="sf-source">' + html.escape(source) +
                '</p><p class="sf-en"><mark class="target-word">' + html.escape(target) +
                '</mark></p></div>' if fallback else
                '<p class="sf-source">原先目标标记：<mark>' + html.escape(target) + '</mark> · ' +
                html.escape(source) + '</p>')
    return ('<details class="sf-ownership-history"><summary>本句归属说明</summary>' +
            '<p class="sf-owner">实际词条：training · n. 训练；培训</p>' +
            '<p class="sf-history-old-reason" style="white-space:pre-wrap">原审核完整说明：' +
            html.escape(reason) + '</p>' + identity +
            '<p><a class = \'other sf-original-history-link\' href = \'' + html.escape(url, quote=True) +
            '\'>查看完整原审核记录</a></p><pre>外层原审核 JSON 必须完整保留</pre></details>')


def parent_page(records=None):
    return ('<!doctype html><html><body><div id="preview-back">' +
            (record() if records is None else records).replace('class="sf-archived-example"', 'class="sf-example"') +
            '</div><script>sourceRuntime()</script></body></html>')


def parent_disclosure(raw, *, english='AI model training.', reason='old reason',
                      source='2024 阅读 Text 3', target='training', sentence='kaoyan:2024-01:p:b-1-1:0', **overrides):
    start = english.index(target)
    proof = {'source_parent_page_url': PARENT,
             'source_parent_page_sha256': hashlib.sha256(raw.encode()).hexdigest(),
             'exclusion_authority': {'audit': {'english': english, 'source_identity': {
                 'english_hash': hashlib.sha256(english.encode()).hexdigest(), 'target_range': [start, start + len(target)],
                 'sentence_id': sentence}}}}
    proof.update(overrides)
    source_html = disclosure(reason, source, target)
    proof_html = '<details class="sf-ownership-authority"><summary>原审核权威与来源记录</summary><pre>' + html.escape(json.dumps(proof, ensure_ascii=False)) + '</pre></details>'
    return source_html[:-len('</details>')] + proof_html + '</details>'


class FinalApkgHistoryTests(unittest.TestCase):
    def test_only_exact_record_is_visible_and_all_outer_bytes_survive(self):
        source = '\n<!--前置原稿-->\n' + disclosure() + '\n<script>current()</script>\n'
        old = archive(record('other', english='OTHER SECRET') + record() + record('third'))
        result = materialize_history(source, lambda url: old)
        anchor = re.search(r'<a class = .*?</a>', source).group()
        prefix, suffix = source.split(anchor)
        self.assertTrue(result.startswith(prefix))
        self.assertTrue(result.endswith(suffix))
        inserted = result[len(prefix):len(result)-len(suffix)]
        self.assertEqual(source.replace(anchor, inserted), result)
        self.assertEqual(result.count('class="sf-archived-example"'), 1)
        self.assertNotIn('OTHER SECRET', result)
        self.assertIn('AI model <mark class="target-word">training</mark>.', result)
        self.assertIn('原文翻译', result)
        self.assertIn('义项依据：old reason', result)
        self.assertIn('外层原审核 JSON 必须完整保留', result)
        self.assertNotIn('sf-original-history-link', result)

    def test_cache_selects_different_sentences_not_whole_shared_archive(self):
        calls = []
        raw = archive(record() + record(reason='second', source='2007 阅读 Text 1', target='train'))
        worker = HistoryMaterializer(lambda url: calls.append(url) or raw)
        first = worker.materialize(disclosure())
        second = worker.materialize(disclosure('second', '2007 阅读 Text 1', 'train'))
        self.assertEqual(calls, [URL])
        self.assertEqual(first.count('class="sf-archived-example"'), 1)
        self.assertEqual(second.count('class="sf-archived-example"'), 1)
        self.assertNotIn('义项依据：second', first)
        self.assertNotIn('义项依据：old reason', second)
        together = worker.materialize(disclosure() + disclosure('second', '2007 阅读 Text 1', 'train'))
        self.assertEqual(together.count('class="sf-archived-example"'), 2)
        self.assertEqual(calls, [URL])

    def test_original_html_is_inert_and_safe_copy_matches_browser_allowlist(self):
        evidence = '<script>danger()</script><iframe src="https://bad">x</iframe>& proof'
        en = ('<span class="card-chunk" data-chunk-side="en" data-chunk-ids="5" '
              'onclick="danger()" style="color:red" id="bad">AI '
              '<mark class="target-word">training</mark></span>'
              '<script>evil()</script><svg><text>svg-content</text></svg>'
              '<img src="https://bad"><a href="javascript:bad()">original link text</a>')
        result = materialize_history(disclosure(), lambda url: archive(record(english=en), evidence))
        inserted = result[result.index('<details class="sf-inline-history"'):]
        self.assertNotIn('<script', inserted)
        self.assertNotIn('<iframe', inserted)
        self.assertNotIn('<svg', inserted)
        self.assertNotIn('<img', inserted)
        self.assertNotIn('onclick=', inserted)
        self.assertNotIn('style=', inserted)
        self.assertNotIn('id="bad"', inserted)
        self.assertNotIn('href=', inserted)
        self.assertNotIn('evil()', inserted)
        self.assertIn('<a>original link text</a>', inserted)
        self.assertIn('data-chunk-side="en" data-chunk-ids="5"', inserted)
        self.assertIn('<pre>' + html.escape(evidence) + '</pre>', inserted)

    def test_optional_evidence_renderer_gets_complete_decoded_html_and_is_cached(self):
        original = '<html><script>never execute()</script>完整证据 & 原内容</html>'
        received = []
        def renderer(value):
            received.append(value)
            return '<pre data-offline-evidence="pinned-media"></pre>'
        worker = HistoryMaterializer(lambda url: archive(evidence=original), evidence_renderer=renderer)
        result = worker.materialize(disclosure())
        self.assertEqual(received, [original])
        self.assertIn('<details><summary>完整原 HTML 证据</summary><pre data-offline-evidence="pinned-media">', result)
        self.assertNotIn('<script>never execute()', result)
        self.assertNotIn(html.escape(original), result)
        self.assertEqual(worker.materialize(disclosure()), result)
        self.assertEqual(received, [original])
        with self.assertRaisesRegex(HistoryError, 'renderer'):
            materialize_history(disclosure(), lambda url: archive(), evidence_renderer=lambda value: None)

    def test_pinned_parent_recovers_exact_sentence_and_preserves_both_complete_evidence(self):
        raw = parent_page(record() + record('unrelated', english='UNRELATED SOURCE'))
        old = archive(record('other'))
        calls = []
        def load(url):
            calls.append(url)
            return {URL: old, PARENT: raw}[url].encode()
        source = parent_disclosure(raw)
        result = HistoryMaterializer(load).materialize(source)
        self.assertEqual(calls, [URL, PARENT])
        self.assertIn('AI model <mark class="target-word">training</mark>.', result)
        self.assertIn('<pre>' + html.escape(raw) + '</pre>', result)
        self.assertIn('<pre>' + html.escape('<html><script>original()</script>全稿 & proof</html>') + '</pre>', result)
        visible = result[result.index('<details class="sf-inline-history"'):result.index('<details><summary>完整原 HTML 证据')]
        self.assertNotIn('UNRELATED SOURCE', visible)
        self.assertNotIn('<script>', visible)
        self.assertIn('原审核完整说明：old reason', result)
        self.assertIn('外层原审核 JSON 必须完整保留', result)

    def test_parent_pin_mismatch_illegal_path_and_missing_authority_fail_closed(self):
        raw = parent_page()
        for source in [parent_disclosure(raw, source_parent_page_sha256='d' * 64),
                       parent_disclosure(raw, source_parent_page_url='/private/secret.html'),
                       disclosure()]:
            with self.subTest(source=source[-200:]), self.assertRaises(HistoryError):
                materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw)

    def test_pinned_parent_unique_sentence_does_not_require_specific_audit_schema(self):
        for authority in [{}, {'accepted_helper': {'kind': 'previously validated source helper'}},
                          {'previous_review': {'complete': 'retained authority'}}]:
            raw = parent_page()
            source = parent_disclosure(raw, exclusion_authority=authority)
            result = materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw)
            self.assertIn('AI model <mark class="target-word">training</mark>.', result)
            self.assertIn('本句封存父页面完整原 HTML 证据', result)

    def test_missing_physical_proof_cannot_choose_multiple_parent_sentences(self):
        raw = parent_page(record() + record(english='Another <mark class="target-word">training</mark>.'))
        source = parent_disclosure(raw, exclusion_authority={'accepted_helper': {}})
        with self.assertRaisesRegex(HistoryError, 'matched 2 records'):
            materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw)
        raw = parent_page(record(target='train'))
        source = parent_disclosure(raw, exclusion_authority={})
        with self.assertRaisesRegex(HistoryError, 'matched 0 records'):
            materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw)

    def test_parent_target_is_part_of_unique_identity_before_optional_audit(self):
        raw = parent_page(record() + record(target='train'))
        source = parent_disclosure(raw, exclusion_authority={})
        result = materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw)
        selected = result[result.index('<details class="sf-inline-history"'):result.index('<details><summary>完整原 HTML 证据')]
        self.assertIn('<mark class="target-word">training</mark>', selected)
        self.assertNotIn('<mark class="target-word">train</mark>', selected)

    def test_legacy_occurrence_reuses_exact_physical_proof_in_same_archive(self):
        raw = archive(record() + record(english='Another <mark class="target-word">training</mark>.'))
        row = {'english':'AI model training.', 'english_hash':hashlib.sha256(b'AI model training.').hexdigest(),
               'target_range':[9,17], 'sentence_id':'kaoyan:2024-01:p:b-1-1:0'}
        source = parent_disclosure(parent_page(), exclusion_authority={'legacy_projection_proof':{'occurrence':row}},
                                  source_history_ref={'url':URL,'sha256':hashlib.sha256(raw.encode()).hexdigest()})
        worker = HistoryMaterializer(lambda url: raw if url == URL else self.fail('must not use parent'))
        result = worker.materialize(source)
        visible = result[result.index('<details class="sf-inline-history"'):result.index('<details><summary>完整原 HTML 证据')]
        self.assertIn('AI model', visible)
        self.assertNotIn('Another', visible)
        self.assertEqual(worker.resolutions[0]['method'], 'pinned_archive_physical_identity')
        with self.assertRaises(HistoryError):
            materialize_history(source.replace(hashlib.sha256(raw.encode()).hexdigest(), 'f'*64), lambda url: raw)

    def test_compound_display_source_and_original_reason_both_survive(self):
        old_source = '2024 阅读 Text 3 ➫ 第34题'
        display_source = old_source + ' ➫ 选项D'
        en = 'AI model training.'
        display = {'english':en, 'english_hash':hashlib.sha256(en.encode()).hexdigest(), 'target_range':[9,17],
                   'translation':'原文翻译','translation_hash':hashlib.sha256('原文翻译'.encode()).hexdigest(),
                   'source':display_source}
        row = dict(display, display=display)
        raw = archive(record(reason='原封存解释', source=display_source))
        source = parent_disclosure(parent_page(), source=old_source, reason='本次完整审核说明',
                 exclusion_authority={'occurrence':row}, source_parent_page_url=None, source_parent_page_sha256=None,
                 source_history_ref={'url':URL,'sha256':hashlib.sha256(raw.encode()).hexdigest()})
        worker = HistoryMaterializer(lambda url: raw)
        result = worker.materialize(source)
        self.assertIn('原审核完整说明：本次完整审核说明', result)
        self.assertIn('义项依据：原封存解释', result)
        self.assertEqual(worker.resolutions[0]['audit_identity']['source'],old_source)
        self.assertEqual(worker.resolutions[0]['record_identity']['reason'],'义项依据：原封存解释')

    def test_compound_can_select_only_one_record_from_pinned_inert_original_html(self):
        row = {'english':'AI model training.', 'english_hash':hashlib.sha256(b'AI model training.').hexdigest(),
               'target_range':[9,17]}
        evidence = parent_page(record('原解释') + record('unrelated', english='OTHER SOURCE'))
        raw = archive('', evidence)
        source = parent_disclosure(parent_page(), reason='新解释', exclusion_authority={'occurrence':row},
                 source_parent_page_url=None, source_parent_page_sha256=None,
                 source_history_ref={'url':URL,'sha256':hashlib.sha256(raw.encode()).hexdigest()})
        worker = HistoryMaterializer(lambda url: raw)
        result = worker.materialize(source)
        visible = result[result.index('<details class="sf-inline-history"'):result.index('<details><summary>完整原 HTML 证据')]
        self.assertIn('义项依据：原解释', visible)
        self.assertNotIn('OTHER SOURCE', visible)
        self.assertNotIn('<script>', visible)
        self.assertEqual(worker.resolutions[0]['method'],'pinned_inert_html_physical_identity')

    def test_large_pinned_local_parent_preserves_full_evidence_without_relaxing_archive_limit(self):
        raw = parent_page() + '<!--' + 'x'*20_000_001 + '-->'
        seen = []
        source = parent_disclosure(raw)
        result = materialize_history(source, lambda url: archive(record('missing')) if url == URL else raw,
                                     evidence_renderer=lambda value: seen.append(value) or '<pre data-media="proof"></pre>')
        self.assertIn('<mark class="target-word">training</mark>', result)
        self.assertIn(raw, seen)
        self.assertEqual(len(seen), 2)

    def test_parent_ambiguity_wrong_english_or_target_range_cannot_match(self):
        for raw in [parent_page(record() * 2), parent_page(record(english='Another <mark class="target-word">training</mark>.')),
                    parent_page(record(english='training <mark class="target-word">training</mark>.'))]:
            with self.subTest(raw=raw[:80]), self.assertRaises(HistoryError):
                materialize_history(parent_disclosure(raw), lambda url: archive(record('missing')) if url == URL else raw)
        raw = parent_page()
        source = parent_disclosure(raw).replace(hashlib.sha256(b'AI model training.').hexdigest(), 'f' * 64)
        calls = []
        with self.assertRaises(HistoryError):
            materialize_history(source, lambda url: calls.append(url) or archive(record('missing')))
        self.assertEqual(calls, [URL])

    def test_ambiguous_archive_never_uses_parent_even_when_parent_unique(self):
        raw = parent_page()
        calls = []
        with self.assertRaisesRegex(HistoryError, 'matched 2 records'):
            materialize_history(parent_disclosure(raw), lambda url: calls.append(url) or archive(record() * 2))
        self.assertEqual(calls, [URL])

    def test_same_reason_different_sentences_use_exact_audited_english_and_cache_identity(self):
        en1 = 'AI model <mark class="target-word">training</mark>.'
        en2 = 'Professional <mark class="target-word">training</mark>.'
        raw = parent_page(record(english=en1) + record(english=en2))
        worker = HistoryMaterializer(lambda url: archive(record('missing')) if url == URL else raw)
        first = worker.materialize(parent_disclosure(raw))
        second = worker.materialize(parent_disclosure(raw, english='Professional training.'))
        def visible(value):
            return value[value.index('<details class="sf-inline-history"'):value.index('<details><summary>完整原 HTML 证据')]
        self.assertIn('AI model', visible(first))
        self.assertNotIn('Professional', visible(first))
        self.assertIn('Professional', visible(second))
        self.assertNotIn('AI model', visible(second))

    def test_only_explicit_reading_option_allows_unique_physical_text_displacement(self):
        source = '2024 阅读 Text 3 ➫ 选项D'
        en = 'The companies should choose <u class="cloze-answer">professional <mark class="target-word">training</mark>.</u>'
        raw = parent_page(record(source=source, english=en))
        text = parent_disclosure(raw, english='professional training.', source=source,
                                 sentence='kaoyan:2024-01:q-34-1:D:new:0')
        result = materialize_history(text, lambda url: archive(record('missing')) if url == URL else raw)
        self.assertIn('The companies should choose', result)
        for bad in [text.replace('q-34-1:D:new:0', 'p:b-1-1:0'), text.replace('选项D', '选项C')]:
            with self.assertRaises(HistoryError):
                materialize_history(bad, lambda url: archive(record('missing')) if url == URL else raw)

    def test_fallback_identity_and_decoded_exact_entities(self):
        reason, source, target = 'A & B\n完整理由', '2024 <Text> & 3', 'train'
        result = materialize_history(disclosure(reason, source, target, fallback=True),
                                     lambda url: archive(record(reason, source, target)))
        self.assertIn('义项依据：A &amp; B\n完整理由', result)
        self.assertIn('2024 &lt;Text&gt; &amp; 3', result)

    def test_wrong_target_or_ambiguous_source_reason_fails_closed(self):
        bad = [record(target='train'), record() + record(target='train'),
               record(english='No target'), record(english='<mark class="target-word">training</mark>' * 2),
               record(chinese='')]
        for records in bad:
            with self.subTest(records=records), self.assertRaises(HistoryError):
                materialize_history(disclosure(), lambda url: archive(records))

    def test_bad_reason_missing_or_duplicate_evidence_rejected(self):
        for raw in [archive(record(reason='old reason ')), archive().replace('<pre>', '<p>').replace('</pre>', '</p>'),
                    archive() + '<details><summary>完整原HTML证据</summary><pre>another</pre></details>']:
            with self.subTest(raw=raw[:100]), self.assertRaises(HistoryError):
                materialize_history(disclosure(), lambda url: raw)

    def test_template_and_rcdata_cannot_fabricate_dom_sentence_or_target(self):
        for raw in [archive('<template>' + record() + '</template>'),
                    archive(record(english='<textarea><mark class="target-word">training</mark></textarea>')),
                    archive(record(english='<title><mark class="target-word">training</mark></title>'))]:
            with self.subTest(raw=raw[:100]), self.assertRaises(HistoryError):
                materialize_history(disclosure(), lambda url: raw)

    def test_illegal_paths_or_origins_rejected_before_loader(self):
        for url in ['https://evil.test' + URL, 'javascript:bad()', URL + '?x=1', URL + '#x',
                    URL.replace('a' * 64, 'A' * 64), URL.replace('/history/', '/cards/'),
                    URL.replace('/history/', '/%68istory/'), URL.replace('/history/', '/history\\'),
                    URL + '\n', '//evil.test' + URL, 'file://' + URL,
                    'http://user@localhost' + URL]:
            calls = []
            with self.subTest(url=url), self.assertRaises(HistoryError):
                materialize_history(disclosure(url=url), lambda url: calls.append(url) or archive())
            self.assertEqual(calls, [])

    def test_legal_frozen_paths_and_relative_path_resolution(self):
        paths = [URL, '/residual-optimization-20261013/engineering/preview-own/root-full-preview-v1/redbook/history/',
                 '/source-confirmations-20261014/cards-own/preview-v1/redbook2027/history/',
                 '/eleven-resolution-20261014/preview-own/final-v2/redbook/history/']
        for path in paths:
            if not path.endswith('.html'):
                path += 'b' * 64 + '.html'
            calls = []
            materialize_history(disclosure(url=path), lambda url: calls.append(url) or archive())
            self.assertEqual(calls, [path])
        path = paths[-1] + 'b' * 64 + '.html'
        calls = []
        materialize_history(disclosure(url='../history/' + 'b' * 64 + '.html'),
                            lambda url: calls.append(url) or archive(),
                            base_url='http://192.168.3.5:8771/eleven-resolution-20261014/preview-own/final-v2/redbook/cards/x.html')
        self.assertEqual(calls, [path])

    def test_no_actual_history_anchor_does_not_load_and_is_byte_identical(self):
        text = ('<script>const s=\'<a class="sf-original-history-link" href="' + URL + '\'>old</a>\';</script>'
                '<pre>&lt;a class="sf-original-history-link"&gt;</pre>'
                '<a class="sf-original-history-link" href="' + URL + '">outside</a>'
                '<details class="sf-semantic-history"><p>as 原文结构异常</p></details>')
        self.assertEqual(materialize_history(text, lambda url: self.fail('must not load')), text)

    def test_oversized_archive_and_duplicate_identity_fields_rejected(self):
        for raw in ['x' * 20_000_001]:
            with self.assertRaises(HistoryError):
                materialize_history(disclosure(), lambda url: raw)
        text = disclosure().replace('<p class="sf-history-old-reason"',
                                    '<p class="sf-history-old-reason">原审核完整说明：extra</p><p class="sf-history-old-reason"')
        with self.assertRaises(HistoryError):
            materialize_history(text, lambda url: self.fail('bad identity must not load'))

    def test_actual_accepted_train_training_as_fields(self):
        root = Path(__file__).resolve().parents[1]
        final = root / 'output/eleven-resolution-20261014/preview-own/final-v2'
        catalog = final / 'redbook2027/catalog.json'
        if not catalog.is_file():
            self.skipTest('accepted local artifact integration requires final-v2')
        from anki_pipeline.final_apkg_content import extract_fields
        loaded = []
        def loader(url):
            loaded.append(url)
            return (root / 'output' / url.lstrip('/')).read_text()
        worker = HistoryMaterializer(loader)
        examples = [(book, word) for book in ['redbook2027', 'redbook'] for word in ['train', 'training', 'as']]
        for book, word in examples:
            cards = json.loads((final / book / 'catalog.json').read_text())['cards']
            card = next(card for card in cards if card['word'] == word)
            source = (root / 'output' / card['previewUrl'].lstrip('/')).read_text()
            fields = extract_fields(source, {})
            for key, text in fields.items():
                links = len(re.findall(r'<a\b[^>]*class="sf-original-history-link"', text))
                result = worker.materialize(text, base_url=card['previewUrl'])
                self.assertEqual(result.count('<details class="sf-inline-history"'), links, (book, word, key))
                self.assertNotIn('sf-original-history-link', result, (book, word, key))
                if links == 0:
                    self.assertEqual(result, text)
                if word == 'as' and '原文结构异常' in text:
                    self.assertIn('原文结构异常', result)
        self.assertGreater(len(loaded), 0)


if __name__ == '__main__':
    unittest.main()
