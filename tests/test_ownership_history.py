"""Lossless incoming history must be tied to an existing physical destination."""
import copy
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from anki_pipeline.ownership_history import bind_incoming_history, render_ownership_history, validate_history_content, _quantity_phrase
from tests.test_sense_frequency import aligned_record, completed_record


def fixture(target=None):
    target = sf.prepare_record(aligned_record()) if target is None else target
    row = target['occurrences'][0]
    source = copy.deepcopy(row)
    source.update(status='unmatched', sense_id=None, reviewed_sense_id=None,
                  assignment_context_hash=None, reason='完整旧错归解释\n第二段理由：不是原名词。')
    decision = {'book_id': target['book_id'], 'card_id': 'wrong-card',
                'after_snapshot_id': 'parent-snapshot', 'occurrence_id': source['occurrence_id'],
                'decision_after': {'status': 'unmatched', 'reason': source['reason']}}
    authority = {'parent_snapshot_id': 'parent-snapshot',
                 'decision_sha256': sf._sha(sf._json(decision)),
                 'legacy_projection_proof': {'decision': decision, 'occurrence': copy.deepcopy(source)}}
    sense = next(s for s in target['senses'] if s['sense_id'] == row['sense_id'])
    transfer = {'book_id': target['book_id'], 'source_card_id': 'wrong-card',
                'source_word': 'novelty', 'source_parent_snapshot_id': 'parent-snapshot',
                'source_parent_row': source, 'exclusion_authority': authority,
                'target_card_id': target['card_id'], 'target_occurrence_id': row['occurrence_id'],
                'verified_physical_match': True, 'match_kind': 'exact_span',
                'source_identity': {k: copy.deepcopy(source[k]) for k in
                    ('paper_id', 'physical_source', 'sentence_id', 'english_hash', 'target_range')},
                'target_range': copy.deepcopy(row['target_range']),
                'matched_sense': {**sense, 'dictionary_source': 'oxford',
                    'source_provenance': {'snapshot_id': target['snapshot_id'], 'entry': 'novel'}},
                'target_reason': row['reason']}
    return target, transfer


class OwnershipHistoryTests(unittest.TestCase):
    def test_full_old_row_attaches_without_a_second_occurrence_or_input_mutation(self):
        target, transfer = fixture(); originals = copy.deepcopy((target, transfer))
        result = bind_incoming_history(target, [transfer, copy.deepcopy(transfer)])
        self.assertEqual(result['expected_occurrences'], 2)
        self.assertEqual(len(result['occurrences']), 2)
        self.assertEqual(result['snapshot_id'], target['snapshot_id'])
        row = next(r for r in result['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id'])
        self.assertEqual(len(row['ownership_history']), 1)
        self.assertEqual(row['ownership_history'][0]['source_parent_row'], transfer['source_parent_row'])
        self.assertEqual(row['ownership_history'][0]['exclusion_authority'], transfer['exclusion_authority'])
        self.assertEqual(result['ownership_history_unresolved'], [])
        self.assertEqual((target, transfer), originals)

    def test_english_alone_wrong_book_card_physical_and_range_never_bind(self):
        for field, value in [('book_id', 'redbook'), ('target_card_id', 'other-card'),
                             ('target_occurrence_id', 'missing'), ('verified_physical_match', False),
                             ('target_range', [19, 24])]:
            with self.subTest(field=field):
                target, transfer = fixture(); transfer[field] = value
                result = bind_incoming_history(target, [transfer])
                self.assertEqual(len(result['ownership_history_unresolved']), 1)
                self.assertTrue(all(not r.get('ownership_history') for r in result['occurrences']))
        target, transfer = fixture(); transfer['source_identity']['physical_source'] = ['another-block']
        self.assertEqual(len(bind_incoming_history(target, [transfer])['ownership_history_unresolved']), 1)

    def test_residual_exact_span_alias_uses_identical_physical_guard(self):
        target, transfer = fixture(); transfer['match_kind'] = 'same_physical_exact_span'
        self.assertEqual(bind_incoming_history(target, [transfer])['ownership_history_unresolved'], [])
        transfer['target_range'][1] += 1
        self.assertEqual(len(bind_incoming_history(target, [transfer])['ownership_history_unresolved']), 1)

    def test_stale_old_reason_hash_authority_sense_or_reason_is_retained_as_unresolved(self):
        edits = [lambda t: t['source_parent_row'].update(english_hash='0' * 64),
                 lambda t: t['source_parent_row'].update(translation='更改的译文'),
                 lambda t: t['exclusion_authority'].update(decision_sha256='0' * 64),
                 lambda t: t['matched_sense'].update(text='任意释义'),
                 lambda t: t.update(target_reason='未经目标卡审核的原因')]
        for edit in edits:
            target, transfer = fixture(); edit(transfer)
            result = bind_incoming_history(target, [transfer])
            self.assertEqual(result['ownership_history_unresolved'][0]['transfer'], transfer)

    def test_scope_removed_destination_does_not_create_a_native_occurrence(self):
        target, transfer = fixture()
        target['occurrences'] = [r for r in target['occurrences'] if r['occurrence_id'] != transfer['target_occurrence_id']]
        target['expected_occurrences'] = 1
        result = bind_incoming_history(target, [transfer])
        self.assertEqual(len(result['occurrences']), 1)
        self.assertEqual(result['expected_occurrences'], 1)
        self.assertIn('destination', result['ownership_history_unresolved'][0]['reason'])

    def test_render_preserves_bilingual_chunks_marks_full_reason_authority_and_links(self):
        target, transfer = fixture(); result = bind_incoming_history(target, [transfer])
        row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        output = render_ownership_history(row, {(target['book_id'], 'wrong-card'): '/wrong.html'})
        self.assertIn('<details', output)
        self.assertIn('/wrong.html', output)
        self.assertIn('novelty', output)
        self.assertIn('新颖的', output)
        self.assertIn('完整旧错归解释\n第二段理由', output)
        self.assertIn('一部小说中的', output)
        self.assertIn('card-chunk', output)
        self.assertIn('<mark', output)
        self.assertIn('legacy_projection_proof', output)
        self.assertIn('2022年考研英语一', output)

    def test_safe_formatted_historical_html_and_recursive_preview_patch(self):
        target, transfer = fixture()
        transfer['source_history_html'] = '<details><summary>旧面板</summary><p>完整历史</p><script>alert(1)</script></details>'
        transfer['source_history_html_sha256'] = sf._sha(transfer['source_history_html'])
        result = bind_incoming_history(target, [transfer]); row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        original_preview = sf._previews
        def patched(rows):
            return original_preview(rows) + ''.join(render_ownership_history(r, {}) for r in rows)
        with patch.object(sf, '_previews', side_effect=patched):
            output = render_ownership_history(row, {'wrong-card': 'javascript:alert(1)'})
        self.assertIn('完整历史', output)
        self.assertNotIn('<script', output)
        self.assertNotIn('alert(1)', output)
        self.assertNotIn('href="javascript:', output)

    def test_verified_document_overlay_is_inline_without_repeating_the_source_example(self):
        import html
        target, transfer = fixture()
        raw = '<details><summary>完整旧诊断</summary><p>词典/上下文原依据</p><script>unsafe()</script></details>'
        full = '<html><pre>' + html.escape(raw) + '</pre></html>'
        ref = {'file': 'source-history.html', 'sha256': sf._sha(full), 'url': '/source-history.html'}
        transfer['source_history_ref'] = ref
        result = bind_incoming_history(target, [transfer]); row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        documents = {ref['file']: {'reference': copy.deepcopy(ref), 'document_html': full,
                     'original_html': raw, 'original_html_sha256': sf._sha(raw)}}
        original = copy.deepcopy(row)
        with patch.object(sf, '_previews', side_effect=AssertionError('source example repeated')):
            output = render_ownership_history(row, documents=documents, include_source_example=False)
        self.assertIn('词典/上下文原依据', output)
        self.assertIn('href="/source-history.html"', output)
        self.assertIn('<summary>本句归属说明</summary>', output)
        self.assertIn('原卡：novelty', output)
        self.assertNotIn('unsafe()', output)
        self.assertEqual(row, original)
        for field, value in [('document_html', '<html>changed</html>'), ('original_html', '<p>changed</p>'),
                             ('original_html_sha256', '0' * 64), ('reference', {**ref, 'url': '/changed.html'})]:
            bad = copy.deepcopy(documents); bad[ref['file']][field] = value
            with self.assertRaises(ValueError):
                render_ownership_history(row, documents=bad, include_source_example=False)
        documents[ref['file']]['inline_history_ids'] = []
        output = render_ownership_history(row, documents=documents, include_source_example=False)
        self.assertNotIn('词典/上下文原依据', output)
        self.assertIn('完整旧错归解释', output)
        self.assertIn('href="/source-history.html"', output)

    def test_archived_diagnostic_articles_do_not_join_runtime_example_selectors(self):
        from html.parser import HTMLParser
        target, transfer = fixture()
        raw = ('<article class="sf-example sf-example-original" data-sf-year="2007">'
               '<span class="card-chunk" data-chunk-ids="old-1"><mark>原历史一</mark></span></article>'
               '<article class="sf-example example-card" data-sf-year="2019"><mark>原历史二</mark></article>')
        transfer.update(source_history_html=raw, source_history_html_sha256=sf._sha(raw))
        result = bind_incoming_history(target, [transfer]); row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        output = '<div class="sf-panel"><article class="sf-example" data-sf-year="2022">当前句' + render_ownership_history(
            row, include_source_example=False) + '</article></div>'
        class Articles(HTMLParser):
            def __init__(self): super().__init__(); self.rows = []
            def handle_starttag(self, tag, attrs):
                if tag == 'article': self.rows.append(dict(attrs))
        parsed = Articles(); parsed.feed(output)
        active = [article for article in parsed.rows if 'sf-example' in article.get('class', '').split()]
        native = [article for article in parsed.rows if 'example-card' in article.get('class', '').split()]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]['data-sf-year'], '2022')
        self.assertEqual(native, [])
        self.assertEqual(sum('sf-archived-example' in article.get('class', '').split() for article in parsed.rows), 2)
        self.assertIn('sf-example-original', output)
        self.assertIn('sf-archived-native-example', output)
        self.assertIn('data-chunk-ids="old-1"', output)
        self.assertIn('<mark>原历史一</mark>', output)
        self.assertIn('<mark>原历史二</mark>', output)
        self.assertEqual(row['ownership_history'][0]['source_history_html'], raw)
        validate_history_content(row['ownership_history'][0])

    def test_real_empty_original_diagnostic_keeps_exact_document_proof(self):
        target, transfer = fixture()
        full = '<html><p>原页面无独立诊断块</p><pre></pre></html>'
        ref = {'file': 'empty-history.html', 'sha256': sf._sha(full), 'url': '/empty-history.html'}
        transfer['source_history_ref'] = ref
        result = bind_incoming_history(target, [transfer]); row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        documents = {ref['file']: {'reference': copy.deepcopy(ref), 'document_html': full,
                                  'original_html': '', 'original_html_sha256': sf._sha('')}}
        output = render_ownership_history(row, documents=documents, include_source_example=False)
        self.assertIn('完整旧错归解释', output)
        self.assertIn('href="/empty-history.html"', output)
        self.assertNotIn('sf-original-history-panel', output)
        documents[ref['file']]['original_html'] = None
        with self.assertRaises(ValueError): render_ownership_history(row, documents=documents)

    def test_old_html_requires_exact_hash(self):
        target, transfer = fixture(); transfer.update(source_history_html='<p>old</p>', source_history_html_sha256='0' * 64)
        self.assertEqual(len(bind_incoming_history(target, [transfer])['ownership_history_unresolved']), 1)

    def test_all_history_content_is_sealed_and_tampering_is_rejected_before_render(self):
        target, transfer = fixture()
        transfer['source_history_ref'] = {'file': 'original-source.html', 'sha256': 'a' * 64}
        transfer['source_history_html'] = '<p>完整原始说明</p>'
        transfer['source_history_html_sha256'] = sf._sha(transfer['source_history_html'])
        result = bind_incoming_history(target, [transfer])
        row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        original = row['ownership_history'][0]
        self.assertIsNone(validate_history_content(original))
        self.assertEqual(original['content_sha256'], sf._sha(sf._json({
            k: v for k, v in original.items() if k != 'content_sha256'})))
        changes = [lambda h: h['matched_sense'].update(text='伪造的实际义项'),
                   lambda h: h.update(target_reason='伪造解释'),
                   lambda h: h.update(target_word='伪造词头'),
                   lambda h: h['source_history_ref'].update(file='changed.html'),
                   lambda h: h['source_history_ref'].update(sha256='b' * 64),
                   lambda h: h.update(source_history_html='<p>改写</p>'),
                   lambda h: h['matched_sense']['source_provenance'].update(snapshot_id='changed')]
        for change in changes:
            with self.subTest(change=change):
                bad = copy.deepcopy(row); change(bad['ownership_history'][0])
                self.assertEqual(bad['ownership_history'][0]['history_id'], original['history_id'])
                with self.assertRaisesRegex(ValueError, 'content SHA'):
                    validate_history_content(bad['ownership_history'][0])
                with self.assertRaisesRegex(ValueError, 'content SHA'):
                    render_ownership_history(bad)

    def test_content_validation_preserves_historical_parent_snapshot_after_current_reseal(self):
        target, transfer = fixture()
        result = bind_incoming_history(target, [transfer])
        row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        result['snapshot_id'] = 'later-resealed-current-snapshot'
        self.assertIsNone(validate_history_content(row['ownership_history'][0]))
        self.assertIn('完整旧错归解释', render_ownership_history(row))
        bad = copy.deepcopy(row['ownership_history'][0]); bad.pop('content_sha256')
        with self.assertRaisesRegex(ValueError, 'content SHA'):
            validate_history_content(bad)

    def test_native_quantity_phrase_requires_exact_different_components_and_number_scope(self):
        english = 'People came by the millions.'
        x = english.index('the'); a = english.index('millions')
        source = {'english': english, 'target_range': [x, x + 3]}
        destination = {'occurrence_id': 'target-occurrence', 'target_range': [a, a + 8]}
        grammar = {'source_target_range': source['target_range'], 'destination_target_range': destination['target_range'],
                   'whole_phrase_range': [x, a + 8], 'whole_phrase': 'the millions',
                   'distinct_component_ranges': True, 'scope': 'by + the + plural number millions'}
        native = {'native_definition_valid': True, 'raw_entry_valid': True, 'source_headword': 'million',
                  'pos': 'num.', 'part_of_speech': 'number', 'chinese': '一百万', 'english': '1 000 000',
                  'native_usage_notes': ['Millions (of…) can be used if there is no number or quantity before it.'],
                  'native_db_path': '/native/oald10/dictionary.sqlite3',
                  'source_ref': {'dictionary': 'oald10', 'provider': 'oxford', 'source_headword': 'million',
                                 'raw_sha256': 'a' * 64, 'definition_html_sha256': 'b' * 64}}
        proof = {'grammar_evidence': grammar, 'shared_whole_phrase_range': grammar['whole_phrase_range'],
                 'native_dictionary_evidence': native, 'source_pin': {'file': 'confirmed.json', 'sha256': 'c' * 64}}
        transfer = {'source_word': 'the', 'target_card_id': 'million-card',
                    'matched_sense': {'pos': 'num.', 'text': '一百万'}, 'quantity_phrase_proof': proof,
                    'exclusion_authority': {'audit': {'grammar_evidence': grammar,
                        'targets': [{'card_id': 'million-card', 'occurrence_id': 'target-occurrence',
                                     'match_kind': 'same_native_quantity_phrase', **proof}]}}}
        self.assertIsNone(_quantity_phrase({'word': 'million'}, source, destination, transfer))
        changes = [lambda t: t.pop('quantity_phrase_proof'),
                   lambda t: t['quantity_phrase_proof']['grammar_evidence'].update(scope='generic nearby phrase'),
                   lambda t: t['quantity_phrase_proof']['native_dictionary_evidence'].update(native_usage_notes=[]),
                   lambda t: t['quantity_phrase_proof']['native_dictionary_evidence']['source_ref'].update(raw_sha256='invalid'),
                   lambda t: t['quantity_phrase_proof']['shared_whole_phrase_range'].append(99),
                   lambda t: t['exclusion_authority']['audit'].update(targets=[])]
        for change in changes:
            bad = copy.deepcopy(transfer); change(bad)
            with self.assertRaises(ValueError):
                _quantity_phrase({'word': 'million'}, source, destination, bad)

    def test_confirmed_reviewed_rehome_requires_full_pinned_audit(self):
        target, transfer = fixture()
        source = transfer['source_parent_row']
        source.update(status='reviewed', sense_id='old-sense', reviewed_sense_id='old-sense')
        audit = {'book_id': transfer['book_id'], 'card_id': transfer['source_card_id'],
                 'occurrence_id': source['occurrence_id'], 'exclusion_verified': True,
                 'decision_status': 'keep_exclusion', 'source_identity': copy.deepcopy(transfer['source_identity']),
                 'reason': '上下文逐条确认：独立名词归入实际词头。',
                 'targets': [{'card_id': transfer['target_card_id'],
                              'occurrence_id': transfer['target_occurrence_id'], 'verified_physical_match': True}]}
        transfer['exclusion_authority'] = {'source_parent_snapshot_id': transfer['source_parent_snapshot_id'],
            'source_parent_row_sha256': sf._sha(sf._json(source)), 'audit': audit}
        self.assertEqual(bind_incoming_history(target, [transfer])['ownership_history_unresolved'], [])
        for change in [lambda t: t['exclusion_authority'].update(source_parent_row_sha256='0' * 64),
                       lambda t: t['exclusion_authority']['audit'].pop('book_id'),
                       lambda t: t['exclusion_authority']['audit']['targets'][0].update(verified_physical_match=False)]:
            bad = copy.deepcopy(transfer); change(bad)
            result = bind_incoming_history(target, [bad, copy.deepcopy(bad)])
            self.assertEqual(len(result['ownership_history_unresolved']), 1)
            self.assertEqual(result['ownership_history_unresolved'][0]['transfer'], bad)

    def test_actual_dictionary_snapshot_and_source_paragraph_pins_are_checked(self):
        changes = [lambda t: t['matched_sense'].update(dictionary_source='unknown'),
                   lambda t: t['matched_sense']['source_provenance'].update(snapshot_id='stale'),
                   lambda t: t['matched_sense']['source_provenance'].update(page_sha256='0' * 64),
                   lambda t: t['source_parent_row']['source_provenance'].update(sourceHash='other-paragraph')]
        for change in changes:
            target, transfer = fixture(); change(transfer)
            result = bind_incoming_history(target, [transfer])
            self.assertEqual(len(result['ownership_history_unresolved']), 1)

    def test_complete_fixed_phrase_owner_retains_exact_component_mark(self):
        target, transfer = fixture()
        source = transfer['source_parent_row']; source['target_range'][1] -= 1
        source['occurrence_id'] = sf._sha(sf._json([source['paper_id'], source['physical_source'], source['target_range']]))
        transfer['source_identity']['target_range'] = copy.deepcopy(source['target_range'])
        decision = transfer['exclusion_authority']['legacy_projection_proof']['decision']
        decision['occurrence_id'] = source['occurrence_id']
        transfer['exclusion_authority']['legacy_projection_proof']['occurrence'] = copy.deepcopy(source)
        transfer['exclusion_authority']['decision_sha256'] = sf._sha(sf._json(decision))
        transfer['match_kind'] = 'fixed_phrase_contains_exact_component_span'
        self.assertEqual(bind_incoming_history(target, [transfer])['ownership_history_unresolved'], [])
        target['word'] = 'unproved whole phrase'
        self.assertEqual(len(bind_incoming_history(target, [transfer])['ownership_history_unresolved']), 1)

    def test_explicit_technical_sense_rebinding_preserves_actual_parent_proof(self):
        target, transfer = fixture()
        old_parent = copy.deepcopy(next(r for r in target['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id']))
        old_id = old_parent['sense_id']; new_id = 'new-sense-id'
        transfer['target_parent_row'] = old_parent
        transfer['target_parent_snapshot_id'] = target['snapshot_id']
        target['snapshot_id'] = 'child-snapshot'
        for sense in target['senses']:
            if sense['sense_id'] == old_id: sense['sense_id'] = new_id
        for row in target['occurrences']:
            if row['sense_id'] == old_id: row['sense_id'] = row['reviewed_sense_id'] = new_id
        result = bind_incoming_history(target, [transfer])
        row = next(r for r in result['occurrences'] if r.get('ownership_history'))
        self.assertEqual(row['ownership_history'][0]['matched_sense']['sense_id'], new_id)
        self.assertEqual(row['ownership_history'][0]['matched_sense']['technical_rebinding']['old_sense_id'], old_id)
        transfer['matched_sense']['pos'] = 'n.'
        self.assertEqual(len(bind_incoming_history(target, [transfer])['ownership_history_unresolved']), 1)

    def test_metadata_only_preparation_accepts_exact_parent_proof_and_preserves_old_pin(self):
        from anki_pipeline.exam_usage import occurrence_usage
        from anki_pipeline.exam_usage_policy import producer_record
        target, transfer = fixture()
        parent_snapshot = target['snapshot_id']
        transfer['target_parent_row'] = copy.deepcopy(next(r for r in target['occurrences']
            if r['occurrence_id'] == transfer['target_occurrence_id']))
        transfer['target_parent_snapshot_id'] = parent_snapshot
        producer = producer_record(target)
        for row in producer['occurrences']:
            row['usage'] = occurrence_usage(row)
        current = sf.prepare_record(producer)
        self.assertNotEqual(current['snapshot_id'], parent_snapshot)
        self.assertEqual(current['senses'], target['senses'])
        result = bind_incoming_history(current, [transfer])
        self.assertEqual(result['ownership_history_unresolved'], [])
        history = next(r for r in result['occurrences'] if r.get('ownership_history'))['ownership_history'][0]
        self.assertEqual(history['matched_sense']['source_provenance']['snapshot_id'], parent_snapshot)
        self.assertEqual(history['matched_sense']['technical_rebinding']['child_snapshot_id'], current['snapshot_id'])
        self.assertEqual(history['matched_sense']['technical_rebinding']['old_sense_id'], history['matched_sense']['sense_id'])
        validate_history_content(history)
        bads = [lambda t: t.pop('target_parent_row'),
                lambda t: t.update(target_parent_snapshot_id='arbitrary-old-pin'),
                lambda t: t['target_parent_row'].update(reason='changed parent meaning'),
                lambda t: t['target_parent_row'].update(translation_hash='0' * 64),
                lambda t: t['target_parent_row'].update(method='changed review authority')]
        for edit in bads:
            bad = copy.deepcopy(transfer); edit(bad)
            self.assertEqual(len(bind_incoming_history(current, [bad])['ownership_history_unresolved']), 1)
        changed = copy.deepcopy(current)
        sense_id = transfer['matched_sense']['sense_id']
        next(s for s in changed['senses'] if s['sense_id'] == sense_id)['text'] = '改变的实际词义'
        self.assertEqual(len(bind_incoming_history(changed, [transfer])['ownership_history_unresolved']), 1)
        changed = copy.deepcopy(current); changed['definition_source'] = 'changed-dictionary'
        self.assertEqual(len(bind_incoming_history(changed, [transfer])['ownership_history_unresolved']), 1)

    def test_only_exact_approved_derived_chunk_refresh_can_bridge_a_parent_display(self):
        from anki_pipeline.exam_usage_policy import producer_record
        from anki_pipeline.exam_usage import occurrence_usage
        from anki_pipeline import sense_display as sd
        parent = sf.prepare_record(completed_record())
        old = producer_record(parent)
        for row in old['occurrences']:
            view = row['display']; view['provenance'].pop('alignment_projection', None)
            view['alignment'] = sd._project_alignment(row, view['english'], view['translation'], view['alignment_sources'])
            view.pop('display_hash'); view['display_hash'] = sf._sha(sf._json(view))
        parent, transfer = fixture(sf.prepare_record(old))
        original_parent = copy.deepcopy(parent)
        transfer['target_parent_row'] = copy.deepcopy(next(r for r in parent['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id']))
        transfer['target_parent_snapshot_id'] = parent['snapshot_id']
        producer = producer_record(parent)
        producer['occurrences'] = [sd.refresh_derived_chunks(row) for row in producer['occurrences']]
        for row in producer['occurrences']: row['usage'] = occurrence_usage(row)
        current = sf.prepare_record(producer)
        result = bind_incoming_history(current, [transfer])
        self.assertEqual(result['ownership_history_unresolved'], [])
        history = next(r for r in result['occurrences'] if r.get('ownership_history'))['ownership_history'][0]
        refresh = history['matched_sense']['technical_rebinding']['display_refresh']
        self.assertEqual(refresh['method'], 'sense_display.refresh_derived_chunks')
        self.assertEqual(refresh['parent_display_sha256'], transfer['target_parent_row']['display']['display_hash'])
        self.assertEqual(refresh['target_display_sha256'], next(r for r in current['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id'])['display']['display_hash'])
        self.assertEqual(parent, original_parent)
        validate_history_content(history)
        def reseal(view):
            view.pop('display_hash'); view['display_hash'] = sf._sha(sf._json(view))
        edits = [lambda r: r['display']['alignment']['alignments'].pop(),
                 lambda r: r['display']['provenance'].update(input_manifest_sha256='d' * 64),
                 lambda r: r['display']['provenance'].update(source_files={'changed-source': 'f' * 64}),
                 lambda r: r['display'].update(source='伪造显示出处'),
                 lambda r: r['display']['alignment_sources'].append(copy.deepcopy(r['display']['alignment_sources'][0]))]
        for edit in edits:
            bad = copy.deepcopy(current)
            row = next(r for r in bad['occurrences'] if r['occurrence_id'] == transfer['target_occurrence_id'])
            edit(row); reseal(row['display'])
            self.assertEqual(len(bind_incoming_history(bad, [transfer])['ownership_history_unresolved']), 1)
        bad = copy.deepcopy(transfer); bad['target_parent_row']['alignment']['alignments'].pop()
        self.assertEqual(len(bind_incoming_history(current, [bad])['ownership_history_unresolved']), 1)


if __name__ == '__main__': unittest.main()
