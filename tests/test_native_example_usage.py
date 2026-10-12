"""Native changes stay pinned to source identity and invert exact HTML bytes."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_display as sd
from anki_pipeline.exam_usage import POLICY
from tests.test_sense_display import native_example, occurrence, sha, source


def prepared(rows):
    value = {'book_id': 'redbook2027', 'card_id': 'native-test', 'occurrences': deepcopy(rows)}
    value['snapshot_id'] = sha(sd._json(value))
    return value


def row(item, span, *, origin='option', correctness='unknown'):
    result = occurrence(item, span)
    result['paper_id'] = 'kaoyan:2022-01'
    result['occurrence_id'] = sha(sd._json([result['paper_id'], result['physical_source'], span]))
    result['usage'] = {'policy': POLICY, 'source_kind': 'answer_option',
        'source_role': 'reading_option' if origin == 'option' else 'question_stem',
        'reading_candidate_correctness': correctness,
        'reading_candidate': {'question_id': 'kaoyan:2022-01:q-29-1', 'option_label': 'B',
            'correctness': correctness, 'match_origins': [origin]}}
    return result


class NativeExampleUsageTests(unittest.TestCase):
    def update(self, page, old, new, **kwargs):
        from anki_pipeline.native_example_usage import update_native_examples, restore_original
        before = deepcopy((old, new))
        result = update_native_examples(page, old, new, **kwargs)
        self.assertEqual((old, new), before)
        self.assertEqual(restore_original(result['page'], result['inverse']), page)
        self.assertEqual(json.loads(json.dumps(result)), result)
        return result

    def test_pinned_original_keeps_chinese_jump_and_unrelated_bytes(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel idea.', '一个新颖想法。',
            [{'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'}])
        old = row(item, [2, 7], correctness='correct')
        page = '<!--外部 unchanged--><ol>' + native_example(item, item['english'], item['translationZh'], [[2, 7]]) + '</ol><script>const n = 1;</script>'
        result = self.update(page, prepared([old]), prepared([old]))
        revised = sd._native_examples(result['page'], {})[0]
        self.assertEqual(revised, sd._native_examples(page, {})[0])
        self.assertIn('正确选项 B', result['page'])
        self.assertIn('匹配来自选项', result['page'])
        self.assertIn('data-chunk-side="zh"', result['page'])
        self.assertIn('<!--外部 unchanged--><ol>', result['page'])
        self.assertTrue(result['page'].endswith('</ol><script>const n = 1;</script>'))
        self.assertEqual(result['stats']['updated_examples'], 1)

    def test_approved_derived_display_refreshes_fine_chunks_and_keeps_underlines(self):
        item = source('kaoyan:2022-01:p:q29:0', 'A novel idea ______', '一个新颖想法______',
            [{'en': [2, 12], 'zh': [[2, 6]], 'relation': 'equivalent'}])
        english, chinese = 'A novel idea succeeds.', '一个新颖想法成功了。完整中文尾部。'
        derived = {'sentenceId': item['id'], 'originalEnglish': item['english'],
            'completedEnglish': english, 'translationZh': chinese, 'blankRange': [13, 19],
            'insertedRange': [13, 21], 'answerNumber': '29', 'questionId': 'kaoyan:2022-01:q-29-1'}
        page = native_example(item, english, chinese, [[2, 7]], answer=[13, 21], answer_number=29)
        physical = row(item, [2, 7], origin='stem', correctness='incorrect')
        sources = {'sentences': {item['id']: item}, 'completions': {item['id']: derived}, 'options': {}, 'watched': {}}
        record = {'book_id': 'redbook2027', 'card_id': 'native-test', 'word': 'novel',
            'definition_provenance': {'headword': 'novel', 'page_sha256': sha(page)}, 'occurrences': [physical]}
        with patch.object(sd, '_load_sources', return_value=sources):
            physical = sd.attach_source_displays([record], {'native-test': page}, {})[0]['occurrences'][0]
        # Simulate the accepted old display, before explicit whole-sentence metadata.
        physical['display']['provenance'].pop('alignment_projection')
        physical['display']['alignment']['alignments'].pop()
        physical['display'].pop('display_hash')
        physical['display']['display_hash'] = sha(sd._json(physical['display']))
        result = self.update(page, prepared([physical]), prepared([physical]))
        visible = sd._native_examples(result['page'], {})[0]
        self.assertEqual(visible, sd._native_examples(page, {})[0])
        self.assertIn('错误选项 B', result['page'])
        self.assertIn('匹配来自题干', result['page'])
        self.assertIn('data-chunk-ids="0 1"', result['page'])
        self.assertIn('data-chunk-sentence-ids="1"', result['page'])
        self.assertIn('title="整句对应', result['page'])
        self.assertIn('class="cloze-answer"', result['page'])

    def test_all_excluded_removes_only_exact_native_example(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        original = native_example(item, item['english'], item['translationZh'], [[2, 7]])
        twin = source('kaoyan:2022-01:q-30-1:C:0', item['english'], item['translationZh'])
        untouched = native_example(twin, twin['english'], twin['translationZh'], [[2, 7]])
        result = self.update('HEAD' + original + untouched + 'TAIL', prepared([row(item, [2, 7])]), prepared([]))
        self.assertEqual(result['page'], 'HEAD' + untouched + 'TAIL')
        self.assertEqual(result['stats']['removed_examples'], 1)

    def test_partial_exclusion_retains_sentence_and_only_surviving_marks(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel plus a novel.', '一部小说加一部小说。')
        first, last = row(item, [2, 7]), row(item, [15, 20])
        page = native_example(item, item['english'], item['translationZh'], [[2, 7], [15, 20]])
        result = self.update(page, prepared([first, last]), prepared([last]))
        visible = sd._native_examples(result['page'], {})[0]
        self.assertEqual(visible['target_ranges'], [[15, 20]])
        self.assertEqual(visible['english'], item['english'])
        self.assertEqual(visible['translation'], item['translationZh'])
        self.assertIn('答案未核实 B', result['page'])
        self.assertEqual(visible['jump'], sd._native_examples(page, {})[0]['jump'])

    def test_compressed_classes_and_packed_jump_remain_exact(self):
        import base64
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        page = native_example(item, item['english'], item['translationZh'], [[2, 7]])
        packed = '|'.join(['1', '2022-01', 'q-29-1%3AB%3A0', *[
            base64.urlsafe_b64encode(bytes.fromhex(item[key])).decode().rstrip('=')
            for key in ('englishHash', 'reviewedContentHash')], '2,7'])
        import re
        page = re.sub(r'href="[^"]+"', 'data-rb-j="' + packed + '"', page)
        aliases = {'ec': 'example-card', 'et': 'example-text', 'ez': 'example-translation',
            'es': 'example-source', 'sj': 'sentence-jump', 'tt': 'translate-tag', 'tw': 'target-word'}
        for compact, full in aliases.items():
            page = page.replace('class="' + full + '"', 'class="' + compact + '"')
        physical = row(item, [2, 7])
        result = self.update(page, prepared([physical]), prepared([physical]), aliases=aliases)
        self.assertIn('data-rb-j="' + packed + '"', result['page'])
        self.assertIn('class="target-word tw"', result['page'])
        self.assertEqual(sd._native_examples(page, aliases), sd._native_examples(result['page'], aliases))

    def test_source_or_snapshot_tampering_fails_closed(self):
        from anki_pipeline.native_example_usage import update_native_examples, restore_original
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        physical = row(item, [2, 7])
        page = native_example(item, item['english'], item['translationZh'], [[2, 7]])
        old = prepared([physical]); changed = deepcopy(old)
        changed['occurrences'][0]['translation'] += '改'
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            update_native_examples(page, old, changed)
        stale = page.replace(item['reviewedContentHash'], '0' * 64)
        with self.assertRaisesRegex(ValueError, 'source.*hash|source.*binding'):
            update_native_examples(stale, old, old)
        result = update_native_examples(page, old, old)
        with self.assertRaisesRegex(ValueError, 'page'):
            restore_original(result['page'] + 'changed', result['inverse'])
        bad_inverse = deepcopy(result['inverse'])
        bad_inverse['bindings'][0]['targets'][0]['old_row_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'payload hash'):
            restore_original(result['page'], bad_inverse)

    def test_inherited_exclusion_removes_bound_original_and_preserves_unbound_derived(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        removed = row(item, [2, 7])
        old = prepared([])
        old['candidate_scope'] = {'excluded': [{'occurrence': removed,
            'occurrence_sha256': sha(sd._json(removed))}]}
        old.pop('snapshot_id'); old['snapshot_id'] = sha(sd._json(old))
        direct = native_example(item, item['english'], item['translationZh'], [[2, 7]])
        derived = native_example(item, 'Which novel?', '哪本小说？完整中文。', [[6, 11]], source_ranges=[[2, 7]])
        result = self.update(direct + derived, old, prepared([]))
        self.assertEqual(result['page'], derived)
        self.assertEqual(result['stats']['removed_examples'], 1)
        self.assertEqual(result['stats']['unbound_examples'], 1)

    def test_same_candidate_combines_stem_and_option_origins(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel plus a novel.', '一部小说加一部小说。')
        stem, option = row(item, [2, 7], origin='stem'), row(item, [15, 20])
        page = native_example(item, item['english'], item['translationZh'], [[2, 7], [15, 20]])
        result = self.update(page, prepared([stem, option]), prepared([stem, option]))
        self.assertEqual(result['page'].count('答案未核实 B'), 1)
        self.assertIn('匹配来自题干、选项', result['page'])

    def test_candidate_context_keeps_a_stem_target_after_its_option_is_excluded(self):
        stem = source('kaoyan:2022-01:p:q29:0', 'Which novel?', '哪部小说？')
        option = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        def ref(item):
            return {'sentenceId': item['id'], 'range': [0, len(item['english'])],
                'english': item['english'], 'translationZh': item['translationZh'],
                'englishHash': item['englishHash'], 'translationHash': sha(item['translationZh']),
                'reviewedContentHash': item['reviewedContentHash']}
        english, chinese = 'Which novel?\n\nA novel.', '题干：哪部小说？\n选项 B：一本小说。'
        derived = {'sentenceId': option['id'], 'completedEnglish': english, 'translationZh': chinese,
            'originalQuestionEnglish': stem['english'], 'questionEnglish': stem['english'],
            'insertedRange': [14, 21], 'answerNumber': '29', 'questionId': 'kaoyan:2022-01:q-29-1',
            'hasQuestionBlank': False, 'candidateOptionLabel': 'B', 'isCorrectCandidate': False,
            'optionSentenceRefs': [ref(option)], 'stemSentenceRefs': [ref(stem)], 'optionSentenceIds': [option['id']]}
        visible = 'Which novel?\nA novel.'
        page = native_example(option, visible, chinese, [[6, 11], [15, 20]],
            source_ranges=[[2, 7]], answer=[13, 20], answer_number=29)
        physical_option = row(option, [2, 7], correctness='incorrect')
        sources = {'sentences': {stem['id']: stem, option['id']: option}, 'completions': {},
            'options': {option['id']: derived}, 'watched': {}}
        record = {'book_id': 'redbook2027', 'card_id': 'native-test', 'word': 'novel',
            'definition_provenance': {'headword': 'novel', 'page_sha256': sha(page)},
            'occurrences': [physical_option]}
        with patch.object(sd, '_load_sources', return_value=sources):
            physical_option = sd.attach_source_displays([record], {'native-test': page}, {})[0]['occurrences'][0]
        physical_stem = row(stem, [6, 11], origin='stem', correctness='correct')
        old = prepared([physical_stem, physical_option])
        result = self.update(page, old, prepared([physical_stem]))
        rendered = sd._native_examples(result['page'], {})[0]
        self.assertEqual(rendered['target_ranges'], [[6, 11]])
        self.assertEqual(rendered['english'], visible)
        self.assertEqual(rendered['translation'], chinese)
        self.assertIn('错误选项 B', result['page'])
        self.assertIn('匹配来自题干', result['page'])
        self.assertNotIn('匹配来自选项', result['page'])
        self.assertEqual(result['stats']['removed_examples'], 0)

    def test_unbound_target_prevents_whole_example_deletion(self):
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel plus a novel.', '完整中文：两部小说。')
        page = native_example(item, item['english'], item['translationZh'], [[2, 7], [15, 20]])
        result = self.update(page, prepared([row(item, [2, 7])]), prepared([]))
        visible = sd._native_examples(result['page'], {})[0]
        self.assertEqual(visible['target_ranges'], [[15, 20]])
        self.assertEqual(visible['translation'], item['translationZh'])
        self.assertEqual(result['stats']['unbound_targets'], 1)
        self.assertEqual(result['stats']['removed_examples'], 0)

    def test_resealed_retained_physical_change_is_rejected(self):
        from anki_pipeline.native_example_usage import update_native_examples
        item = source('kaoyan:2022-01:q-29-1:B:0', 'A novel.', '一本小说。')
        physical = row(item, [2, 7])
        page = native_example(item, item['english'], item['translationZh'], [[2, 7]])
        changed = deepcopy(physical); changed['translation'] += '改'
        with self.assertRaisesRegex(ValueError, 'physical row'):
            update_native_examples(page, prepared([physical]), prepared([changed]))


class NativeOwnershipHistoryTests(unittest.TestCase):
    """Incoming explanations live under their existing physical native target."""
    update = NativeExampleUsageTests.update

    @staticmethod
    def history_fixture():
        from anki_pipeline.ownership_history import bind_incoming_history
        from scripts.update_exam_usage_preview import _history_document
        from tests.test_ownership_history import fixture
        target, transfer = fixture()
        raw = '<section><p>完整原审核界面：第一段</p><p>第二段不能截短。</p></section>'
        document = _history_document('novelty', transfer['source_parent_snapshot_id'], '/accepted/wrong.html', raw)
        ref = {'file': 'sealed-history.html', 'url': '/history/sealed-history.html', 'sha256': sha(document)}
        transfer['source_history_ref'] = ref
        after = bind_incoming_history(target, [transfer])
        assert not after['ownership_history_unresolved']
        after.pop('snapshot_id')
        after['snapshot_id'] = sha(sd._json(after))
        first = target['occurrences'][0]
        item = source(first['sentence_id'], first['english'], first['translation'])
        item['reviewedContentHash'] = first['source_provenance']['reviewedContentHash']
        page = '<!--原页面--><ol>' + native_example(item, item['english'], item['translationZh'],
            [r['target_range'] for r in target['occurrences']]) + '</ol><footer>原末尾</footer>'
        docs = {ref['file']: {'reference': deepcopy(ref), 'document_html': document,
            'original_html': raw, 'original_html_sha256': sha(raw)}}
        return target, after, page, docs

    def test_complete_sealed_history_attaches_to_existing_native_example_without_new_counts(self):
        old, new, page, docs = self.history_fixture()
        result = self.update(page, old, new, ownership_history_documents=docs,
                             target_urls={'wrong-card': '/updated/wrong.html'})
        self.assertEqual(sd._native_examples(result['page'], {}), sd._native_examples(page, {}))
        self.assertEqual(result['stats']['native_examples'], 1)
        self.assertEqual(result['stats']['removed_examples'], 0)
        self.assertEqual(result['stats']['ownership_history_examples'], 1)
        self.assertEqual(result['stats']['ownership_histories'], 1)
        self.assertEqual(new['expected_occurrences'], old['expected_occurrences'])
        self.assertEqual(len(new['occurrences']), len(old['occurrences']))
        self.assertIn('data-native-ownership-history="v1"', result['page'])
        self.assertIn('<summary>本句归属说明</summary>', result['page'])
        self.assertIn('原卡：', result['page'])
        self.assertIn('完整旧错归解释\n第二段理由：不是原名词。', result['page'])
        self.assertIn('实际词条：novel · adj. 新颖的 · oxford', result['page'])
        self.assertIn('实际义项依据：修饰 idea，表示新颖', result['page'])
        self.assertIn('legacy_projection_proof', result['page'])
        self.assertIn('完整原审核界面：第一段', result['page'])
        self.assertIn('第二段不能截短。', result['page'])
        self.assertIn('/history/sealed-history.html', result['page'])
        self.assertIn('/updated/wrong.html', result['page'])
        self.assertNotIn('<article class="sf-example"', result['page'])
        self.assertLess(result['page'].index('data-native-ownership-history'), result['page'].index('</li>'))
        self.assertTrue(result['page'].endswith('</ol><footer>原末尾</footer>'))
        history = next(r['ownership_history'][0] for r in new['occurrences'] if r.get('ownership_history'))
        binding = result['inverse']['bindings'][0]['targets'][0]
        self.assertIn({'history_id': history['history_id'], 'content_sha256': history['content_sha256']},
                      binding['ownership_history'])
        second = self.update(result['page'], new, new, ownership_history_documents=docs,
                             target_urls={'wrong-card': '/updated/wrong.html'})
        self.assertEqual(second['page'], result['page'])

    def test_history_and_document_tampering_fail_before_render_even_after_snapshot_reseal(self):
        from anki_pipeline.native_example_usage import update_native_examples
        from anki_pipeline.ownership_history import _content_sha256
        old, new, page, docs = self.history_fixture()
        for edit, message in [(lambda h: h.update(target_reason='篡改理由'), 'content SHA'),
                              (lambda h: h.update(target_card_id='another-card',
                                  content_sha256=None), 'destination')]:
            bad = deepcopy(new)
            history = next(r['ownership_history'][0] for r in bad['occurrences'] if r.get('ownership_history'))
            edit(history)
            if history['content_sha256'] is None:
                history['content_sha256'] = _content_sha256(history)
            bad.pop('snapshot_id'); bad['snapshot_id'] = sha(sd._json(bad))
            with self.assertRaisesRegex(ValueError, message):
                update_native_examples(page, old, bad, ownership_history_documents=docs)
        for field, value in [('document_html', '<html>改写</html>'), ('original_html', '<p>截短</p>')]:
            bad_docs = deepcopy(docs); next(iter(bad_docs.values()))[field] = value
            with self.assertRaises(ValueError):
                update_native_examples(page, old, new, ownership_history_documents=bad_docs)
        # A freshly computed outer seal cannot manufacture a different old audit.
        bad = deepcopy(new)
        history = next(r['ownership_history'][0] for r in bad['occurrences'] if r.get('ownership_history'))
        history['source_parent_row']['reason'] = '重新伪造旧完整说明'
        history['history_id'] = sha(sd._json([history['book_id'], history['source_card_id'],
            history['source_parent_snapshot_id'], history['source_parent_row'], history['exclusion_authority'],
            history['target_card_id'], history['target_occurrence_id']]))
        history['content_sha256'] = _content_sha256(history)
        bad.pop('snapshot_id'); bad['snapshot_id'] = sha(sd._json(bad))
        with self.assertRaisesRegex(ValueError, 'old X proof|old X.*reason'):
            update_native_examples(page, old, bad, ownership_history_documents=docs)

    def test_same_english_with_another_source_cannot_receive_incoming_history(self):
        from anki_pipeline.native_example_usage import update_native_examples
        old, new, page, docs = self.history_fixture()
        first = old['occurrences'][0]
        twin = source('kaoyan:2022-01:p:another-block:0', first['english'], first['translation'])
        wrong = native_example(twin, twin['english'], twin['translationZh'],
                               [r['target_range'] for r in old['occurrences']])
        with self.assertRaisesRegex(ValueError, 'ownership.*native|native.*ownership'):
            update_native_examples(wrong, old, new, ownership_history_documents=docs)

    def test_optional_history_arguments_preserve_no_history_output_exactly(self):
        old, _, page, _ = self.history_fixture()
        ordinary = self.update(page, old, old)
        extra = self.update(page, old, old, ownership_history_documents={}, target_urls={'wrong-card': '/new.html'})
        self.assertEqual(extra, ordinary)

    def test_actual_baseline_summary_activation_and_keyboard_guard_do_not_flip_card(self):
        import hashlib
        import re
        from anki_pipeline.native_example_usage import update_native_examples
        root = Path(sd.__file__).resolve().parents[1]
        ledger_path = root / 'output/exam-usage-policy-20261012/native-reviewed-jump-aliases.json'
        request_path = root / 'output/exam-usage-policy-20261012/trial-request-v5.json'
        if not ledger_path.is_file() or not request_path.is_file():
            self.skipTest('actual accepted card/library evidence is unavailable')
        ledger, request = (json.loads(path.read_bytes()) for path in (ledger_path, request_path))
        accepted = Path(ledger['source_files']['accepted_source_page']['file'])
        bundle = None
        for script in re.finditer(r'<script[^>]+src="([^"]+)"', accepted.read_text()):
            path = (accepted.parent / script[1]).resolve()
            raw = path.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), path.stem)
            if "var flip = event.target.closest('#preview-flip');" in raw.decode():
                bundle = raw.decode()
                break
        self.assertIsNotNone(bundle)
        entry = Path(request['books'][0]['entry']['file'])
        library_ref = next(script[1] for script in re.finditer(r'<script[^>]+src="([^"]+)"', entry.read_text())
                           if script[1].endswith('/library-preview.js'))
        library = (Path(request['web_root']) / library_ref.lstrip('/') if library_ref.startswith('/')
                   else (entry.parent / library_ref).resolve())
        library_source = library.read_text()
        start = library_source.index('  function keyboard(event) {')
        end = library_source.index('  async function loadCatalog()', start)
        keyboard = library_source[start:end]
        self.assertIn('a[href], summary, audio', keyboard)
        old, new, page, docs = self.history_fixture()
        rendered = update_native_examples(page, old, new, ownership_history_documents=docs)['page']
        html = ('<button id="preview-flip" aria-pressed="true">返回正面</button>'
                '<div id="preview-front" hidden></div><div id="preview-back">' + rendered + '</div>')
        javascript = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const dom=new JSDOM(input.html,{runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;
w.ResizeObserver=class{observe(){}disconnect(){}};w.eval(input.bundle);
const fold=d.querySelector('[data-native-ownership-history]>.sf-ownership-history');
const summary=fold.querySelector('summary'),flip=d.querySelector('#preview-flip');
assert.equal(fold.open,false);summary.click();assert.equal(fold.open,true);
assert.equal(flip.getAttribute('aria-pressed'),'true');summary.click();assert.equal(fold.open,false);
assert.equal(flip.getAttribute('aria-pressed'),'true');
w.eval('var browseOpen=false,activeFrame={ready:true},catalog={},guardFlips=0;function flipCard(){guardFlips++;document.querySelector("#preview-flip").click();}'+input.keyboard);
d.addEventListener('keydown',w.keyboard);
summary.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true}));
assert.equal(w.guardFlips,0);assert.equal(flip.getAttribute('aria-pressed'),'true');
d.body.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true,cancelable:true}));
assert.equal(w.guardFlips,1);assert.equal(flip.getAttribute('aria-pressed'),'false');
process.exit(0);
'''
        executed = subprocess.run(['node', '-e', javascript], input=json.dumps({
            'html': html, 'bundle': bundle, 'keyboard': keyboard}), text=True, capture_output=True, cwd=root)
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)


class NativeChunkRuntimeTests(unittest.TestCase):
    def shared_runtime(self):
        return (Path(sd.__file__).with_name('templates') / 'card-chunks.js').read_text()

    def test_inline_bundle_replacement_keeps_other_code_and_exact_inverse(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime, restore_original
        original = ('<main>完整内容</main><script>window.before = 1;\n' + self.shared_runtime() +
            '\nwindow.after = 2;</script><script>window.audio = 3;</script>')
        result = install_chunk_runtime(original, {'_r28': 'example-card'})
        self.assertEqual(restore_original(result['page'], result['inverse']), original)
        self.assertIn('window.before = 1;', result['page'])
        self.assertIn('window.after = 2;', result['page'])
        self.assertTrue(result['page'].endswith('<script>window.audio = 3;</script>'))
        self.assertIn("closest('.example-card,.sf-example,._r28')", result['page'])
        self.assertIn('if (window.__ankiNativeCardChunksBoundV1) return;', result['page'])
        self.assertNotIn('if (window.__ankiCardChunksBound) return;', result['page'])
        self.assertEqual(result['stats']['replaced_scripts'], 1)
        # The accepted runtime stays byte-identical on ordinary cards.
        self.assertEqual(result['inverse']['runtime_source_sha256'],
                         'c53f934aa243918fb5a7d36db5db14dcb87925046a886818b452cda9bbf3bd5d')

    def test_nested_archived_chunks_keep_ids_and_activate_only_their_nearest_root(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime, restore_original
        def pair(label):
            return ''.join('<span id="' + label + '-' + side + '" class="card-chunk" '
                'data-chunk-side="' + side + '" data-chunk-ids="0">' + label + side + '</span>'
                for side in ('en', 'zh'))
        body = ('<li class="_r28">' + pair('main') +
            '<div class="sf-native-ownership-history" data-native-ownership-history="v1">' + pair('fold') +
            '<article class="sf-archived-example">' + pair('archived') + '</article>' +
            '<ul><li class="sf-archived-native-example">' + pair('native-archive') + '</li></ul></div></li>')
        original = '<ol>' + body + '</ol><script>' + self.shared_runtime() + '</script>'
        result = install_chunk_runtime(original, {'_r28': 'example-card'})
        self.assertEqual(restore_original(result['page'], result['inverse']), original)
        self.assertTrue(result['page'].startswith('<ol>' + body + '</ol>'))
        self.assertIn('.sf-archived-example', result['stats']['root_selector'])
        self.assertIn('.sf-archived-native-example', result['stats']['root_selector'])
        javascript = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs');
const dom=new JSDOM(JSON.parse(fs.readFileSync(0,'utf8')),{runScripts:'outside-only'}),w=dom.window,d=w.document;
w.PointerEvent=function(){};w.__ankiCardChunksBound=true;
w.eval(d.querySelector('script').textContent);
const active=()=>[...d.querySelectorAll('.card-chunk-active')].map(x=>x.id).sort();
for(const label of ['main','fold','archived','native-archive']){
 const target=d.getElementById(label+'-en'),expected=[label+'-en',label+'-zh'].sort();
 target.dispatchEvent(new w.MouseEvent('pointerover',{bubbles:true}));assert.deepEqual(active(),expected);
 target.click();assert.deepEqual(active(),expected);assert.equal(w.__ankiCardChunkState.mode,'tap');
 target.click();assert.deepEqual(active(),[]);
}
assert.equal([...d.querySelectorAll('.card-chunk')].every(x=>x.dataset.chunkIds==='0'),true);
dom.window.close();
'''
        executed = subprocess.run(['node', '-e', javascript], input=json.dumps(result['page']),
            text=True, capture_output=True, cwd=Path(sd.__file__).resolve().parents[1])
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)

    def test_sf_only_history_gets_the_same_isolated_runtime_without_native_marker(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime, restore_original
        def pair(label):
            return ''.join('<span id="' + label + '-' + side + '" class="card-chunk" '
                'data-chunk-side="' + side + '" data-chunk-ids="0">' + label + side + '</span>'
                for side in ('en', 'zh'))
        body = ('<article class="sf-example">' + pair('sf-main') +
            '<details class="sf-ownership-history"><summary>本句归属说明</summary>' + pair('sf-fold') +
            '<article class="sf-archived-example">' + pair('sf-archive') + '</article></details></article>')
        original = body + '<script>' + self.shared_runtime() + '</script>'
        self.assertNotIn('data-native-ownership-history', original)
        result = install_chunk_runtime(original, {})
        self.assertEqual(restore_original(result['page'], result['inverse']), original)
        self.assertTrue(result['page'].startswith(body))
        self.assertIn('.sf-ownership-history', result['stats']['root_selector'])
        javascript = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs');
const dom=new JSDOM(JSON.parse(fs.readFileSync(0,'utf8')),{runScripts:'outside-only'}),w=dom.window,d=w.document;
w.PointerEvent=function(){};w.eval(d.querySelector('script').textContent);
const active=()=>[...d.querySelectorAll('.card-chunk-active')].map(x=>x.id).sort();
for(const label of ['sf-main','sf-fold','sf-archive']){
 const target=d.getElementById(label+'-en'),expected=[label+'-en',label+'-zh'].sort();
 target.dispatchEvent(new w.MouseEvent('pointerover',{bubbles:true}));assert.deepEqual(active(),expected);
 target.click();assert.deepEqual(active(),expected);target.click();assert.deepEqual(active(),[]);
}
dom.window.close();
'''
        executed = subprocess.run(['node', '-e', javascript], input=json.dumps(result['page']),
            text=True, capture_output=True, cwd=Path(sd.__file__).resolve().parents[1])
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)

    def test_content_addressed_external_bundle_needs_exact_source_context(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime, restore_original
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'assets').mkdir(); (root / 'cards').mkdir()
            bundle = 'window.kept = (window.kept || 0) + 1;\n' + self.shared_runtime()
            name = sha(bundle) + '.js'
            asset = root / 'assets' / name; asset.write_text(bundle)
            tag = '<script src="../assets/' + name + '"></script>'
            original = '<main>原DOM</main>' + tag * 3
            source_path = root / 'cards' / 'test.html'; source_path.write_text(original)
            with self.assertRaisesRegex(ValueError, 'source_path'):
                install_chunk_runtime(original, {'_r28': 'example-card'})
            result = install_chunk_runtime(original, {'_r28': 'example-card'}, source_path=source_path)
            self.assertEqual(result['stats']['replaced_scripts'], 3)
            self.assertEqual(restore_original(result['page'], result['inverse']), original)
            self.assertEqual(result['page'].count('window.kept ='), 3)
            self.assertNotIn('src="../assets/' + name, result['page'])
            self.assertEqual(asset.read_text(), bundle)
            self.assertEqual(source_path.read_text(), original)
            asset.write_text(bundle + 'changed')
            with self.assertRaisesRegex(ValueError, 'asset hash'):
                install_chunk_runtime(original, {}, source_path=source_path)

    def test_alias_hover_tap_fine_priority_links_and_old_singleton(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime
        chunk = lambda side, ids, extra, body: ('<span class="card-chunk" data-chunk-side="' + side +
            '" data-chunk-ids="' + ids + '" ' + extra + '>' + body + '</span>')
        en = chunk('en', '0 1', 'data-chunk-sentence-ids="1"', '<mark id="target">novel</mark>')
        zh = chunk('zh', '0 1', 'id="zh" data-chunk-sentence-ids="1"', '新颖')
        whole = chunk('en', '1', 'id="whole" data-chunk-sentence-ids="1"', '整句余文')
        original = ('<div id="outside"><li class="_r28" id="native">' + en + zh + whole +
            '<a id="jump" href="#original">出处</a></li><div class="sf-example" id="other">' +
            chunk('en', '0', 'id="other-en"', 'same') + chunk('zh', '0', 'id="other-zh"', '别句') +
            '</div></div><script>' + self.shared_runtime() + '</script>')
        installed = install_chunk_runtime(original, {'_r28': 'example-card'})['page']
        javascript = r'''
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const fs = require('node:fs');
const dom = new JSDOM(JSON.parse(fs.readFileSync(0, 'utf8')), {runScripts:'outside-only'});
const w = dom.window, d = w.document;
w.PointerEvent = function() {};
w.__ankiCardChunksBound = true;
let flips = 0; d.getElementById('outside').addEventListener('click', () => flips++);
for (const script of d.querySelectorAll('script')) w.eval(script.textContent);
for (const script of d.querySelectorAll('script')) w.eval(script.textContent);
const fire = (name, id) => {const event = new w.MouseEvent(name,{bubbles:true,cancelable:true});
  d.getElementById(id).dispatchEvent(event); return event;};
const active = id => d.getElementById(id).classList.contains('card-chunk-active');
fire('pointerover','target'); assert.equal(active('zh'),true); assert.equal(active('whole'),false);
assert.equal(active('other-en'),false);
assert.equal(fire('click','target').defaultPrevented,true); assert.equal(active('zh'),true);
assert.equal(flips,0); fire('click','target'); assert.equal(active('zh'),false);
fire('click','zh'); assert.equal(active('zh'),true); assert.equal(active('whole'),false);
fire('click','other-en'); assert.equal(active('other-zh'),true); assert.equal(active('zh'),false);
assert.equal(fire('click','jump').defaultPrevented,false); assert.equal(flips,1);
console.log('native runtime hover/tap and source navigation passed');
'''
        result = subprocess.run(['node', '-e', javascript], input=json.dumps(installed),
            text=True, capture_output=True, cwd=Path(sd.__file__).resolve().parents[1])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unrecognized_old_chunk_bootstrap_fails_closed(self):
        from anki_pipeline.native_example_usage import install_chunk_runtime
        with self.assertRaisesRegex(ValueError, 'unsupported.*bootstrap'):
            install_chunk_runtime('<script>window.__ankiCardChunksBound = true;</script>', {})


class ReviewedNativeSourceAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sqlite3
        from scripts.prepare_sense_frequency_records import class_aliases
        cls.root = Path(sd.__file__).resolve().parents[1]
        path = cls.root / 'output/exam-usage-policy-20261012/native-reviewed-jump-aliases.json'
        if not path.exists():
            raise unittest.SkipTest('pinned real Q45A alias ledger is unavailable')
        cls.ledger = json.loads(path.read_bytes())
        cls.pin = {'file': str(path), 'sha256': sha(path.read_text())}
        cls.entry = cls.ledger['entries'][0]
        cls.page_path = Path(cls.ledger['source_files']['accepted_source_page']['file'])
        cls.page = cls.page_path.read_text()
        cls.aliases = class_aliases(cls.page_path.parent.parent)
        database = cls.root / 'data/sense-frequency-supplement-20261011.sqlite3'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            raw = db.execute('SELECT s.payload FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id '
                'WHERE a.book_id=? AND a.card_id=?', (cls.entry['book_id'], cls.entry['card_id'])).fetchone()[0]
        cls.prepared = json.loads(raw)

    def test_actual_train_alias_preserves_complete_text_source_and_authored_hover_pair(self):
        from anki_pipeline.native_example_usage import (load_source_aliases, update_native_examples,
            restore_original, install_chunk_runtime, _Offsets)
        validated = load_source_aliases(self.pin)
        before = deepcopy(self.prepared)
        result = update_native_examples(self.page, self.prepared, self.prepared,
            aliases=self.aliases, source_aliases=validated)
        self.assertEqual(self.prepared, before)
        self.assertEqual(result['stats']['reviewed_source_alias_examples'], 1)
        self.assertEqual(result['stats']['unbound_targets'], 0)
        self.assertEqual(result['stats']['updated_examples'], 75)
        self.assertEqual(restore_original(result['page'], result['inverse']), self.page)
        self.assertEqual(sd._native_examples(result['page'], self.aliases), sd._native_examples(self.page, self.aliases))
        import re
        self.assertEqual(re.findall(r'<script\b.*?</script>', result['page'], re.S),
                         re.findall(r'<script\b.*?</script>', self.page, re.S))
        bindings = [part for binding in result['inverse']['bindings'] for part in binding['targets']
                    if part.get('source_alias_entry_sha256')]
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]['source_alias_entry_sha256'], self.entry['entry_sha256'])
        fragment = next(result['page'][node.start:node.end] for node in _Offsets(result['page'], self.aliases).root.walk()
            if node.tag == 'li' and 'example-card' in node.classes and
            sd._native_examples(result['page'][node.start:node.end], self.aliases)[0]['jump']['sentence_id'] == self.entry['alias_sentence_id'])
        self.assertIn('正确选项 A', fragment)
        self.assertIn('匹配来自选项', fragment)
        self.assertIn(self.entry['native_binding']['jump']['native_jump'], fragment)
        script = (self.root / 'anki_pipeline/templates/card-chunks.js').read_text()
        sample = install_chunk_runtime('<div id="outside">' + fragment + '</div><script>' + script + '</script>', self.aliases)['page']
        javascript = r'''
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs');
const dom=new JSDOM(JSON.parse(fs.readFileSync(0,'utf8')),{runScripts:'outside-only'}),w=dom.window,d=w.document;
w.PointerEvent=function(){};w.__ankiCardChunksBound=true;
for(const s of d.querySelectorAll('script'))w.eval(s.textContent);
const root=d.querySelector('li'),mark=root.querySelector('mark.target-word'),target=mark.querySelector('.card-chunk')||mark;
const fire=type=>{const e=new w.MouseEvent(type,{bubbles:true,cancelable:true});target.dispatchEvent(e);return e;};
const selected=side=>[...root.querySelectorAll('.card-chunk-active')].filter(x=>x.dataset.chunkSide===side).map(x=>x.textContent).join('');
fire('pointerover');assert.equal(selected('en'),'on a train');assert.equal(selected('zh'),'在火车上');
assert.equal(fire('click').defaultPrevented,true);assert.equal(selected('zh'),'在火车上');
fire('click');assert.equal(selected('en'),'');assert.equal(selected('zh'),'');
assert.equal(w.__ankiCardChunkState,null);dom.window.close();
'''
        executed = subprocess.run(['node', '-e', javascript], input=json.dumps(sample),
            text=True, capture_output=True, cwd=self.root)
        self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)

    def resealed_pin(self, ledger, directory):
        for entry in ledger['entries']:
            entry.pop('entry_sha256', None); entry['entry_sha256'] = sha(sd._json(entry))
        ledger.pop('ledger_sha256', None); ledger['ledger_sha256'] = sha(sd._json(ledger))
        path = Path(directory) / 'tampered-alias.json'; path.write_text(json.dumps(ledger, ensure_ascii=False))
        return {'file': str(path), 'sha256': sha(path.read_text())}

    def test_resealed_alias_displacement_or_source_pin_cannot_bypass_proof(self):
        from anki_pipeline.native_example_usage import load_source_aliases
        with tempfile.TemporaryDirectory() as directory:
            changed = deepcopy(self.ledger)
            changed['entries'][0]['prefix_displacement']['codepoints'] = 2
            with self.assertRaisesRegex(ValueError, 'prefix/range/chunk'):
                load_source_aliases(self.resealed_pin(changed, directory))
            changed = deepcopy(self.ledger)
            changed['source_files']['index']['sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'source byte hash'):
                load_source_aliases(self.resealed_pin(changed, directory))

    def test_unvalidated_items_and_tampered_native_jump_are_rejected(self):
        from dataclasses import replace
        from anki_pipeline.native_example_usage import load_source_aliases, update_native_examples
        with self.assertRaisesRegex(ValueError, 'file/sha256'):
            load_source_aliases({'entries': self.ledger['entries']})
        validated = load_source_aliases(self.pin)
        with self.assertRaisesRegex(ValueError, 'unvalidated'):
            load_source_aliases(replace(validated, _token=object()))
        changed_payload = deepcopy(self.ledger)
        changed_payload['entries'][0]['approved_display']['target_range'] = [0, 5]
        changed_json = sd._json(changed_payload)
        with self.assertRaisesRegex(ValueError, 'unvalidated'):
            load_source_aliases(replace(validated, _payload=changed_json, _payload_sha256=sha(changed_json)))
        jump = self.entry['native_binding']['jump']['native_jump']
        self.assertEqual(self.page.count(jump), 1)
        changed = self.page.replace(jump, jump + '|tamper', 1)
        with self.assertRaisesRegex(ValueError, 'native markup/jump/text'):
            update_native_examples(changed, self.prepared, self.prepared, aliases=self.aliases, source_aliases=validated)


if __name__ == '__main__':
    unittest.main()
