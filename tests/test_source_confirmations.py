"""Small standalone recovery rehearsal; no learning or production data is read."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_frequency as sf
from anki_pipeline import source_confirmations as sc


NUMBER = 'Read the following text and match each of the number items in the left column to its corresponding information in the right column.'
JUG = 'I have discovered, as perhaps Kelsey will after her much-publicized resignation from the editorship of She after a build-up of stress, that abandoning the doctrine of “jugging your life”, and making the alternative move into “downshifting” brings with it far greater rewards than financial success and social status.'


class Fixture:
    def __init__(self, root, *, common=False):
        self.root = Path(root)
        self.source = self.root / 'protected.sqlite3'
        self.candidate = self.root / 'candidate.sqlite3'
        records = []
        specs = [('number', NUMBER, sc.CORRECTIONS['number']['sentence_id'], [46, 52], 9),
                 ('jug', JUG, sc.CORRECTIONS['jug']['sentence_id'], [168, 175], None),
                 ('as', JUG, sc.CORRECTIONS['jug']['sentence_id'], [19, 21], 0),
                 ('later', NUMBER, sc.CORRECTIONS['number']['sentence_id'], [53, 58], 0),
                 ('later-meta', 'The source continues.', 'kaoyan:2017-02:p:b-11-3:new:1', [4, 10], 0),
                 ('remote', 'Established in an old paper mill, it is powered by a nearby river and its remote heat warms the people who live in the surrounding town of Kajaani.', 'kaoyan:2025-01:p:b-5-7:2', [74, 80], None),
                 ('pick', 'Studying this could help understand why human evolution picked pace in the last 30,000 years, with social environment being a major contributory factor.', 'kaoyan:2015-01:p:b-1-9:1', [56, 62], None),
                 ('as', 'For instance, as convenient and provocative.', 'kaoyan:2026-01:p:b-1-6:3', [14, 16], None),
                 ('juggle', 'We juggle tasks.', 'kaoyan:2001-01:p:other:0', [3, 9], 1)]
        for index, (word, english, sid, target, sense_index) in enumerate(specs):
            record = {'book_id': 'redbook', 'card_id': f'{word}-{index}', 'word': word,
                'definition_source': 'fixture-original', 'definition_provenance': {'source': 'original', 'headword': word},
                'senses': [{'pos': 'v.' if word in ('number', 'juggle', 'pick') else 'adj.', 'text': '兼顾' if word == 'juggle' and n == 1 else '原义' + str(n)} for n in range(10 if word == 'number' else 2)],
                'expected_occurrences': 1, 'occurrences': []}
            if word == 'juggle':
                # Real redbook order has juggle before jug; exercise the pre-stage.
                record['card_id'] = '000-juggle-before-source'
            alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': sf._sha(english),
                'translationHash': sf._sha('原译'), 'alignments': [{'en': target, 'zh': [[0, 2]], 'relation': 'equivalent'}]}
            row = {'paper_id': ':'.join(sid.split(':')[:2]), 'sentence_id': sid, 'physical_source': [sid],
                'english': english, 'english_hash': sf._sha(english), 'translation': '原译', 'target_range': target,
                'translation_ranges': [[0, 2]], 'alignment': alignment, 'alignment_evidence': [{'english_range': target, 'translation_ranges': [[0, 2]], 'relation': 'equivalent'}],
                'source': '原始来源', 'source_provenance': {'reviewedContentHash': 'a' * 64, 'paragraphRange': [0, len(english)], 'sourceHash': 'b' * 64},
                'status': 'reviewed' if sense_index is not None else 'ambiguous', 'sense_index': sense_index,
                'reason': '旧审核完整说明\n必须保留', 'method': 'fixture', 'review_version': 'fixture'}
            if sense_index is not None:
                row = sf.seal_reviewed_assignment(record, row)
            if word == 'later-meta':
                row['source_provenance']['paragraphRange'] = [133, 154]
                row = sf.seal_reviewed_assignment(record, row)
            record['occurrences'] = [row]
            if common and word == 'remote':
                record['definition_provenance']['components'] = [{'sense_start': 0, 'sense_count': 2}]
                record['sense_group_equivalences'] = [{'member_sense_ids': [s['sense_id'] for s in sf._definition(record)['senses']], 'meaning': '已审共同义',
                    'usage_scope': 'fixture adjective', 'reason': '两来源完整范围已审',
                    'evidence': [{'source': 'fixture'}], 'review_version': 'fixture'}]
            if word == 'jug':
                record['exam_usage_policy'] = {'source_notices': [{'decision': {'reason': '旧卡片完整转归依据不可丢'}, 'old_notice_only': True}]}
            records.append(record)
        sf.save_records(self.source, records, self.root / 'backups')
        shutil.copyfile(self.source, self.candidate)
        self.bytes = self.source.read_bytes()
        with closing(sqlite3.connect(self.source)) as db:
            self.parents = [json.loads(row[0]) for row in db.execute('SELECT payload FROM snapshots')]
        self.evidence = self.pin('evidence.json', {'schema': 'five-source-confirmations-evidence.v1', 'items': [
            {'key': key, 'verified_in_current_conversation': True, 'url': 'https://example.org/' + key}
            for key in ('remote', 'pick', 'as', 'remote-technical')] + [
            {'key': key + '-human-confirmation', 'original': value['old_phrase'], 'corrected': value['new_phrase'],
             'authority': 'direct_user_confirmation_in_current_conversation'} for key, value in sc.CORRECTIONS.items()]})
        canonical = {'decisions': [{'id': r['occurrences'][0]['occurrence_id'], 'word': r['word'], 'reason': '完整既有审查', 'dictionary_evidence': {'fixture': True}} for r in self.parents if r['word'] in ('number', 'jug', 'remote', 'pick') or r['occurrences'][0]['sentence_id'].startswith('kaoyan:2026')]}
        self.canonical = self.pin('canonical.json', canonical)
        meta = {key: {'sentence_id': value['sentence_id'], 'english_hash': value['new_hash'],
            'reviewed_content_hash': 'c' * 64, 'source_hash': 'd' * 64, 'structured_paper_hash': 'e' * 64}
            for key, value in sc.CORRECTIONS.items()}
        self.revisions = self.pin('revisions.json', meta)
        self.request = {'schema': sc.REQUEST, 'protected': {'file': str(self.source), 'stat': sc.stat_pin(self.source)},
            'candidate': {'file': str(self.candidate)}, 'evidence': self.evidence, 'canonical_decisions': self.canonical,
            'source_revisions': self.revisions, 'expected_cards': 9, 'expected_corrected_rows': 4, 'expected_metadata_rows': 1,
            'expected_books': ['redbook']}

    def pin(self, name, value):
        p = self.root / name
        p.write_text(sc.canonical(value))
        return {'file': str(p), 'sha256': sc.digest(p.read_bytes())}

    def state(self):
        with closing(sqlite3.connect(self.candidate)) as db:
            return db.execute('SELECT * FROM active_snapshots ORDER BY book_id,card_id').fetchall()


class SourceConfirmationTests(unittest.TestCase):
    def test_fine_projection_changes_only_current_reports_and_keeps_native_bytes(self):
        from scripts import apply_source_confirmations as script
        from anki_pipeline import residual_optimization as ro
        from tests.test_sense_frequency import completed_record
        from anki_pipeline.packaging import _highlight_example
        parent = sf.prepare_record(completed_record())
        view = parent['occurrences'][0]['display']
        chunks = [{'mapping_id': 'm' + str(i), 'en': en, 'zh': zh, 'reason': '保留原细块', 'source': 'fixture'}
            for i, (en, zh) in enumerate([([0, 12], [[6, 10]]), ([13, 25], [[0, 6]]), ([26, 35], [[11, 16]])])]
        prior = {'english': view['english'], 'translation': view['translation'], 'chunks': chunks,
            'source_comparisons': [], 'unmapped': []}
        item = {'mapping_id': 'm0', 'display_id': 'fixture', 'display_english': view['english'],
            'display_translation': view['translation'], 'raw': {'projection_record': prior}}
        decision = {'mapping_id': 'm0', 'display_id': 'fixture', 'original_source_pins': [{'file': __file__, 'sha256': sc.digest(Path(__file__).read_bytes())}],
            'before_display_english': view['english'], 'before_display_translation': view['translation'],
            'before_display_english_hash': sf._sha(view['english']), 'before_display_translation_hash': sf._sha(view['translation']),
            'after_display_english': view['english'], 'after_display_translation': view['translation'],
            'chunks': chunks, 'source_comparisons': [], 'transform': {'type': 'retained fine blocks'}}
        overlay = ro._display_update(decision, item, {})
        overlay['occurrence_ids'] = [row['occurrence_id'] for row in parent['occurrences']]
        shown = ro.presentation_record(parent, display_updates=[overlay])
        native = '<li class="example-card"><div class="example-text">' + _highlight_example(view['english'], '', '', [],
            target_ranges=[view['target_range']], preserve_source=True) + '</div><div class="example-translation">' + view['translation'] + '</div></li>'
        page = native + sf.render_report(sf.report_from_record(parent))
        revised, _, stats = script.project_current_reports(page, parent, shown, {})
        self.assertTrue(revised.startswith(native))
        self.assertEqual(stats['native_pairs'], 0)
        self.assertEqual(stats['sf_pairs'], len(parent['occurrences']))

    def test_source_comparison_adapter_requires_exact_parent_markup_and_full_inverse(self):
        from scripts import apply_source_confirmations as script
        from scripts import build_residual_optimization_preview as renderer
        from scripts import update_exam_usage_preview as preview
        comparison = {'english': 'Old English.', 'english_hash': sf._sha('Old English.'),
            'translation': '原译', 'translation_hash': sf._sha('原译'), 'chunks': [], 'reason': '完整原对照'}
        view = {'alignment': {'alignments': []}, 'source_comparisons': [comparison]}
        shown = {'occurrences': [{'occurrence_id': 'fixture', 'display': view}]}
        page = '<article class="sf-example" data-sf-occurrence-id="fixture"><div class="sf-sentence-pair"><p class="sf-en">Current.</p>' + renderer._comparison_markup([comparison]) + '</div></article>'
        adapted, inverse, proof = script.source_report_comparisons(page, shown, {})
        self.assertNotIn('data-reviewed-source-comparison=', adapted)
        self.assertEqual(preview.restore_edits(adapted, inverse), page)
        self.assertEqual(proof['details'], 1)
        self.assertEqual(proof['blocks'][0]['source_count'], 1)
        with self.assertRaisesRegex(ValueError, 'pinned parent'):
            script.source_report_comparisons(page.replace('Old English.', 'Changed English.', 1), shown, {})

    def test_render_accepts_certified_parent_common_report_and_preserves_exact_inverse(self):
        from scripts import apply_source_confirmations as script
        from scripts import update_exam_usage_preview as preview
        from anki_pipeline.packaging import _exam_frequency_markup
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root, common=True)
            plan = sc.prepare(f.request)
            card = next(c for c in plan['cards'] if c['word'] == 'remote')
            before, after = card['before_payload'], card['payload']
            page = ('<!doctype html><html><head><style data-supplement-preview="style"></style></head><body>'
                + _exam_frequency_markup({'exam_frequency': preview._frequency(before['occurrences']),
                    'exam_frequency_breakdown': preview._breakdown(before['occurrences'], 0)})
                + sf.render_report(sf.report_from_record(before)) + '</body></html>')
            with closing(sc._connect(f.candidate)) as db:
                rendered, _, _, proof, _ = script.render_card(page, before, after, card,
                    source_url='/old/remote.html', target_url='/new/redbook/source-correction-cards/remote.html',
                    exam_base='http://localhost:8765', db=db, target_urls={})
                self.assertTrue(proof['source_report_bridge_certification']['adapted'])
                self.assertTrue(proof['inverse_exact'])
                self.assertNotIn('data-residual-source-report-scaffold=', rendered)
                with self.assertRaisesRegex(ValueError, 'snapshot'):
                    script.render_card(page.replace(before['snapshot_id'], 'f' * 64), before, after, card,
                        source_url='/old/remote.html', target_url='/new/redbook/source-correction-cards/remote.html',
                        exam_base='http://localhost:8765', db=db, target_urls={})

    def test_rehearsal_repins_verified_scratch_file_after_failed_transaction(self):
        from scripts import apply_source_confirmations as script
        with tempfile.TemporaryDirectory(dir=script.OWNED) as root:
            f = Fixture(root)
            plan = sc.prepare(f.request)
            actual_apply = sc.apply
            def touch_after_failure(trial, **kwargs):
                try:
                    return actual_apply(trial, **kwargs)
                except RuntimeError:
                    path = Path(trial['candidate'])
                    info = path.stat()
                    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
                    raise
            with patch.object(sc, 'apply', side_effect=touch_after_failure):
                receipt = script.rehearse(plan, Path(root) / 'rehearsal')
            self.assertTrue(receipt['injected_failure_atomic'])
            self.assertTrue(receipt['full_parent_recovery_exact'])
            self.assertTrue(receipt['apply_idempotent'])
            self.assertTrue(receipt['rollback_idempotent'])
            self.assertEqual(f.source.read_bytes(), f.bytes)

    def test_native_renderer_uses_remapped_chunks_jump_and_exact_inverse(self):
        from scripts import apply_source_confirmations as script
        from scripts import patch_exam_usage_preview as owner
        from scripts import update_exam_usage_preview as preview
        from anki_pipeline import sense_display as sd
        from anki_pipeline.packaging import _highlight_example, _source_jump
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            plan = sc.prepare(f.request)
            card = next(c for c in plan['cards'] if c['word'] == 'number')
            before, after = card['before_payload'], card['payload']
            row = before['occurrences'][0]
            native = ('<li class="example-card"><div class="example-text">'
                + _highlight_example(row['english'], '', '', [], target_ranges=[row['target_range']], preserve_source=True)
                + '</div><div class="example-translation"><span class="translate-tag">译文：</span> ' + row['translation']
                + '</div><p class="example-source">原始来源'
                + _source_jump(owner.original_paper_jump(row, row['target_range'], 'http://localhost:8765')) + '</p></li>')
            rendered, inverse, stats = script.correct_native_examples(native, before, after, {}, 'http://localhost:8765')
            parsed = sd._native_examples(rendered, {})[0]
            self.assertEqual(parsed['english'], NUMBER.replace('number items', 'numbered items'))
            self.assertEqual(parsed['translation'], '原译')
            self.assertEqual(parsed['target_ranges'], [[46, 54]])
            self.assertEqual(parsed['jump']['english_hash'], sc.CORRECTIONS['number']['new_hash'])
            self.assertEqual(parsed['jump']['reviewed_content_hash'], 'c' * 64)
            self.assertEqual(preview.restore_edits(rendered, inverse), native)
            self.assertEqual(stats['updated_native_examples'], 1)
            self.assertIn('data-chunk-side="zh"', rendered)
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
            old_jump = owner.original_paper_jump(row, row['target_range'], 'http://localhost:8765')
            for field in ('latex_url', 'full_paper_url'):
                parts = urlsplit(old_jump[field])
                query = dict(parse_qsl(parts.query))
                query['anki-codex-en'] = json.dumps([[46, 52], [53, 58]], separators=(',', ':'))
                old_jump[field] = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            plain_mark = _highlight_example(row['english'], '', '', [], target_ranges=[[46, 52]], preserve_source=True)
            extra_mark = _highlight_example(row['english'], '', '', [], target_ranges=[[46, 52], [53, 58]], preserve_source=True)
            extra = native.replace(plain_mark, extra_mark).replace(_source_jump(owner.original_paper_jump(row, row['target_range'], 'http://localhost:8765')), _source_jump(old_jump))
            cleaned, cleaned_inverse, cleaned_stats = script.correct_native_examples(extra, before, after, {}, 'http://localhost:8765')
            self.assertEqual(sd._native_examples(cleaned, {})[0]['target_ranges'], [[46, 54]])
            self.assertEqual(cleaned_stats['removed_stale_declared_marks_not_owned'], 1)
            self.assertEqual(preview.restore_edits(cleaned, cleaned_inverse), extra)
            with self.assertRaisesRegex(ValueError, 'reviewed context'):
                script.correct_native_examples(extra.replace('a' * 64, 'b' * 64), before, after, {}, 'http://localhost:8765')

    def test_scope_offsets_raw_history_and_phrase_meanings(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            plan = sc.prepare(f.request)
            self.assertEqual(f.source.read_bytes(), f.bytes)
            self.assertEqual(plan['summary']['corrected_rows'], 4)
            after = {c['word'] + ':' + c['card_id']: c['payload'] for c in plan['cards']}
            later = next(p for p in after.values() if p['word'] == 'later')['occurrences'][0]
            self.assertEqual(later['target_range'], [55, 60])
            self.assertEqual(later['alignment']['alignments'][0]['en'], [55, 60])
            self.assertEqual(later['translation'], '原译')
            self.assertEqual(later['alignment']['alignments'][0]['zh'], [[0, 2]])
            self.assertEqual(later['source_provenance']['source_confirmation']['original_row']['english'], NUMBER)
            self.assertNotIn('display', later)
            metadata = next(p for p in after.values() if p['word'] == 'later-meta')['occurrences'][0]
            self.assertEqual(metadata['english'], 'The source continues.')
            self.assertEqual(metadata['target_range'], [4, 10])
            self.assertEqual(metadata['alignment']['alignments'][0]['en'], [4, 10])
            self.assertEqual(metadata['source_provenance']['paragraphRange'], [135, 156])
            self.assertEqual(metadata['source_provenance']['sourceHash'], 'd' * 64)
            self.assertEqual(metadata['source_provenance']['reviewedContentHash'], 'a' * 64)
            self.assertEqual(next(p for p in after.values() if p['word'] == 'jug')['expected_occurrences'], 0)
            moved = next(p for p in after.values() if p['word'] == 'juggle')
            self.assertEqual(moved['expected_occurrences'], 2)
            self.assertEqual(sum(r['sentence_id'] == sc.CORRECTIONS['jug']['sentence_id'] for r in moved['occurrences']), 1)
            transferred = next(r for r in moved['occurrences'] if r['sentence_id'] == sc.CORRECTIONS['jug']['sentence_id'])
            self.assertEqual(transferred['source_provenance']['source_confirmation']['prior_card_source_notices'][0]['decision']['reason'], '旧卡片完整转归依据不可丢')
            for word in ('remote', 'pick'):
                p = next(p for p in after.values() if p['word'] == word)
                self.assertIn('语境用法', p['senses'][-1]['text'])
                self.assertFalse(p['definition_provenance']['supplemental_definitions']['appended'][-1]['is_dictionary_native'])
                self.assertEqual(p['occurrences'][0]['status'], 'reviewed')
            special_as = next(p for p in after.values() if p['word'] == 'as' and p['occurrences'][0]['sentence_id'].startswith('kaoyan:2026'))
            self.assertEqual(special_as['occurrences'][0]['status'], 'ambiguous')
            self.assertIn('唯一', special_as['occurrences'][0]['reason'])

    def test_report_renderer_context_label_history_citations_and_plan_unchanged(self):
        from scripts import apply_source_confirmations as script
        from scripts import update_exam_usage_preview as preview
        from anki_pipeline.packaging import _exam_frequency_markup
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            plan = sc.prepare(f.request)
            card = next(c for c in plan['cards'] if c['word'] == 'remote')
            before, after = card['before_payload'], card['payload']
            frequency = preview._frequency(before['occurrences'])
            page = ('<!doctype html><html><head><style data-supplement-preview="style"></style></head><body>'
                + _exam_frequency_markup({'exam_frequency': frequency, 'exam_frequency_breakdown': preview._breakdown(before['occurrences'], 0)})
                + sf.render_report(sf.report_from_record(before)) + '</body></html>')
            checksum = sc.digest(plan)
            with closing(sc._connect(f.candidate)) as db:
                rendered, frequency, _, proof, sources = script.render_card(page, before, after, card,
                    source_url='/old/remote.html', target_url='/new/redbook/source-correction-cards/remote.html',
                    exam_base='http://localhost:8765', db=db, target_urls={})
            self.assertEqual(sc.digest(plan), checksum)
            self.assertTrue(proof['inverse_exact'])
            self.assertEqual(frequency['occurrences'], 1)
            self.assertIn('语境用法（非词典原义）', rendered)
            self.assertIn('原审核完整说明：旧审核完整说明', rendered)
            self.assertIn('href="https://example.org/remote"', rendered)
            self.assertIn('sf-source-confirmation-history', rendered)
            self.assertEqual(len(sources), 1)

    def test_moved_example_inlines_complete_old_card_notice(self):
        from scripts import apply_source_confirmations as script
        with tempfile.TemporaryDirectory() as root:
            plan = sc.prepare(Fixture(root).request)
            after = next(c['payload'] for c in plan['cards'] if c['word'] == 'juggle')
            page, inverse = script.inline_history(sf.render_report(sf.report_from_record(after)), after, {})
            self.assertIn('历史 jug 卡片完整来源与转归审查（原判断）', page)
            self.assertIn('旧卡片完整转归依据不可丢', page)
            self.assertIn('old_notice_only', page)
            self.assertTrue(inverse)

    def test_canonical_sha_is_byte_identical_to_existing_writer(self):
        from anki_pipeline import residual_optimization as ro
        value = {'b': ['保留中文', {'with': '\\literal\\n', 'offset': [46, 54]}], 'a': None}
        self.assertEqual(sc.digest(value), ro.digest(value))

    def test_cached_validator_rejects_valid_but_unrelated_row_and_definition_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            plan = sc.prepare(Fixture(root).request)
            card = next(c for c in plan['cards'] if c['word'] == 'juggle')
            changed = deepcopy(sc._payload(card))
            unrelated = next(r for r in changed['occurrences'] if not r['source_provenance'].get('source_confirmation'))
            unrelated['reason'] = '形式上合法但未授权的新判断'
            with self.assertRaisesRegex(ValueError, 'scope|unrelated'):
                sc._validate_child(sc._payload(card, True), changed)

    def test_streamed_prepare_keeps_only_pins_and_replays_exact_payloads(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            ordinary = sc.prepare(f.request)
            output = Path(root) / 'streamed'
            streamed = sc.prepare(f.request, artifact_root=output)
            for old, new in zip(ordinary['cards'], streamed['cards']):
                self.assertNotIn('payload', new)
                self.assertNotIn('before_payload', new)
                self.assertEqual(sc._payload(new), old['payload'])
                self.assertEqual(sc._payload(new, True), old['before_payload'])
            saved = sc.materialize(streamed, output)
            loaded = json.loads(Path(saved['plan']['file']).read_text())
            sc._validate(loaded)
            card = next(c for c in loaded['cards'] if c['word'] == 'later-meta')
            changed = deepcopy(sc._payload(card))
            changed['occurrences'][0]['reason'] = '形式合法但未授权的元数据语义改写'
            with self.assertRaisesRegex(ValueError, 'semantic'):
                sc._validate_child(sc._payload(card, True), changed)
            changed = deepcopy(sc._payload(card))
            changed['senses'][0]['text'] = '不相关的新词典原义'
            with self.assertRaisesRegex(ValueError, 'definition'):
                sc._validate_child(sc._payload(card, True), changed)
            changed = deepcopy(sc._payload(card))
            moved = next(r for r in changed['occurrences'] if r['source_provenance'].get('source_confirmation'))
            moved['english_hash'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'English|text/chunks'):
                sc._validate_child(sc._payload(card, True), changed)

    def test_transaction_idempotency_failure_and_exact_pointer_rollback(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            before = f.state()
            plan = sc.prepare(f.request)
            with self.assertRaisesRegex(ValueError, 'approval'):
                sc.apply(plan)
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                sc.apply(plan, root_write_approved=True, fail_after_cards=2)
            self.assertEqual(f.state(), before)
            first = sc.apply(plan, root_write_approved=True)
            self.assertFalse(first['already_applied'])
            self.assertTrue(sc.apply(plan, root_write_approved=True)['already_applied'])
            sc.rollback(plan, root_write_approved=True)
            self.assertEqual(f.state(), before)
            self.assertTrue(sc.rollback(plan, root_write_approved=True)['already_rolled_back'])
            self.assertEqual(f.source.read_bytes(), f.bytes)

    def test_tamper_alias_and_stale_parent_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            plan = sc.prepare(f.request)
            changed = deepcopy(plan)
            changed['cards'][0]['payload']['occurrences'][0]['translation'] = '篡改'
            with self.assertRaisesRegex(ValueError, 'seal'):
                sc.apply(changed, root_write_approved=True)
            for kind in ('symlink', 'hardlink'):
                path = Path(root) / (kind + '.sqlite3')
                path.symlink_to(f.source) if kind == 'symlink' else os.link(f.source, path)
                request = deepcopy(f.request)
                request['candidate']['file'] = str(path)
                with self.assertRaisesRegex(ValueError, 'protected|alias'):
                    sc.prepare(request)
            with closing(sqlite3.connect(f.candidate)) as db:
                db.execute('DELETE FROM active_snapshots WHERE card_id=?', (plan['cards'][0]['card_id'],))
                db.commit()
            with self.assertRaisesRegex(ValueError, 'graph|parent'):
                sc.apply(plan, root_write_approved=True)
            self.assertEqual(f.source.read_bytes(), f.bytes)


if __name__ == '__main__':
    unittest.main()
