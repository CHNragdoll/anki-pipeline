"""Small real SQLite fixtures for the isolated incremental writer contract."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import residual_optimization as writer
from anki_pipeline import sense_frequency as sf
from anki_pipeline import exam_usage_policy as policy
from tests.test_sense_frequency import record, completed_record


class WriterFixture:
    def __init__(self, directory, *, records=None):
        self.root = Path(directory)
        self.source = self.root / 'original.sqlite3'
        self.candidate = self.root / 'candidate.sqlite3'
        values = records if records is not None else [record()]
        sf.save_records(self.source, values, self.root / 'backups')
        shutil.copyfile(self.source, self.candidate)  # Only a tiny disposable fixture.
        with closing(sqlite3.connect(self.source)) as db:
            self.parents = [json.loads(r[0]) for r in db.execute('SELECT s.payload FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id')]
        self.evidence = self.pin('source-evidence.json', {'fixture': True, 'actual_context': 'A novel idea for a novel.'})
        self.items, self.decisions = [], []
        for parent in self.parents:
            row = next(r for r in parent['occurrences'] if r['target_range'] == [2, 7])
            item = next((i for i in self.items if i['id'] == row['occurrence_id']), None)
            if item is None:
                item = {'id': row['occurrence_id'], 'word': parent['word'], 'book_refs': [], 'raw': []}
                self.items.append(item)
                self.decisions.append({'id': row['occurrence_id'], 'word': parent['word'], 'action': 'match_existing_sense',
                    'actual_lemma': parent['word'], 'actual_pos': 'adj.', 'meaning_zh': '新颖的', 'meaning_en': 'new',
                    'reason': 'actual adjective modifying idea', 'context_evidence': {'english': row['english'], 'target_range': row['target_range']},
                    'dictionary_evidence': {'native_original': parent['senses'][1]}, 'source_pins': [self.evidence], 'book_decisions': []})
            book = {'book_id': parent['book_id'], 'card_id': parent['card_id'], 'snapshot_id': parent['snapshot_id'],
                    'occurrence_id': row['occurrence_id'], 'sense_id': parent['senses'][1]['sense_id']}
            item['book_refs'].append(deepcopy(book))
            item['raw'].append({'book_id': parent['book_id'], 'card_id': parent['card_id'], 'occurrence': deepcopy(row)})
            next(d for d in self.decisions if d['id'] == item['id'])['book_decisions'].append(deepcopy(book))
        self.input = self.pin('inputs.json', self.items)
        self.reviewed = self.pin('decisions.json', self.decisions)
        self.manifest = {'schema': 'residual-optimization-work-manifest.v1', 'root': str(self.root),
            'baseline': {'database': str(self.source)}, 'semantic_jobs': [self.input], 'chunk_jobs': [], 'source_inputs': []}
        self.request = {'schema': writer.REQUEST, 'baseline': {'file': str(self.source), 'stat': writer.stat_pin(self.source),
            'certified_sha256': writer.digest(self.source.read_bytes())}, 'candidate': {'file': str(self.candidate)},
            'work_manifest': self.pin('manifest.json', self.manifest), 'semantic': [{'input': self.input, 'decisions': self.reviewed}]}

    def pin(self, name, value):
        path = self.root / name
        path.write_bytes(value if isinstance(value, bytes) else writer.canonical(value).encode())
        return {'file': str(path), 'sha256': writer.digest(path.read_bytes())}

    def refresh(self):
        self.request['semantic'][0]['decisions'] = self.pin('decisions.json', self.decisions)
        self.request['work_manifest'] = self.pin('manifest.json', self.manifest)

    def native(self, lemma='novel', english='a new and unusual idea', chinese='新颖的观念'):
        pin = self.pin('native.html', ('<html><h1>' + lemma + '</h1><div id="native-sense"><span>' + english +
            '</span><span>' + chinese + '</span></div></html>').encode())
        ref = {'provider': 'official_web', 'source_url': 'https://dictionary.cambridge.org/dictionary/english/' + lemma,
            'capture_file': pin['file'], 'capture_sha256': pin['sha256'], 'capture_format': 'html',
            'source_headword': lemma, 'original_definition_text': english, 'dictionary': 'fixture-CALD4'}
        return {'new_sense': {'pos': 'adj.', 'text': chinese, 'original_english': english, 'original_chinese': chinese,
                    'translation_kind': 'original'},
                'dictionary_explanation': {'source': 'official_web', 'dictionary': 'fixture-CALD4', 'name': 'Cambridge',
                    'version': 'fixture', 'exact_entry': lemma, 'sense': 'native-sense', 'english_definition': english,
                    'original_chinese': chinese, 'source_ref_pin': ref}, 'dictionary_source_pins': [ref]}


class IncrementalWriterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.f = WriterFixture(self.temp.name)

    def test_contextual_review_is_its_own_counted_non_native_sense(self):
        d = self.f.decisions[0]
        d['action'] = 'contextual_usage'
        for b in d['book_decisions']:
            b['contextual_sense'] = {'kind': 'contextual_usage', 'is_dictionary_native': False, 'pos': 'adj.',
                'text': '在此指与众不同的设想', 'english': 'a distinctive idea in this passage',
                'base_sense_ids': [b['sense_id']], 'native_base_evidence': {'original': 'new and unusual'}}
        self.f.refresh()
        plan = writer.prepare(self.f.request)
        child = plan['affected'][0]['payload']
        supplement = child['definition_provenance']['supplemental_definitions']['appended'][0]
        self.assertEqual(supplement['kind'], 'contextual_usage')
        self.assertFalse(supplement['is_dictionary_native'])
        matched = next(r for r in child['occurrences'] if r['occurrence_id'] == d['id'])
        self.assertEqual(matched['status'], 'reviewed')
        report = sf.report_from_record(child)
        self.assertEqual(report['senses'][2]['count'], 1)
        writer.apply(plan, root_write_approved=True)
        self.assertEqual(sf.read_card(self.f.candidate, child['book_id'], child['card_id'])['pending_count'], 0)

    def test_dictionary_lane_is_not_parser_provider_and_prefix_preserved(self):
        d = self.f.decisions[0]
        d['action'] = 'append_dictionary_sense'
        d['book_decisions'][0]['technical_decision'] = self.f.native()
        self.f.refresh()
        plan = writer.prepare(self.f.request)
        child = plan['affected'][0]['payload']
        self.assertEqual([(s['pos'], s['text']) for s in child['senses'][:2]],
                         [(s['pos'], s['text']) for s in self.f.parents[0]['senses']])
        provenance = child['definition_provenance']['supplemental_definitions']['appended'][0]
        self.assertEqual(provenance['source_dictionary'], 'fixture-CALD4')
        self.assertEqual(provenance['source_provider'], 'official_web')
        self.assertTrue(provenance['is_dictionary_native'])
        writer.apply(plan, root_write_approved=True)

    def test_contextual_rejects_foreign_base_and_fake_native_label(self):
        d = self.f.decisions[0]
        d['action'] = 'contextual_usage'
        d['book_decisions'][0]['contextual_sense'] = {'kind': 'contextual_usage', 'is_dictionary_native': False,
            'pos': 'adj.', 'text': '语境', 'english': 'context', 'base_sense_ids': ['absent'], 'native_base_evidence': {'original': 'new'}}
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'base IDs'):
            writer.prepare(self.f.request)
        d['book_decisions'][0]['contextual_sense']['is_dictionary_native'] = True
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'distinguish'):
            writer.prepare(self.f.request)

    def test_materialized_plan_is_small_pinned_and_retry_after_write_fault(self):
        plan = writer.prepare(self.f.request)
        target = self.f.root / 'engineering/writer-own/prepared'
        prepared = writer.materialize(plan, target)
        wire = writer.read_json(prepared['plan'])
        self.assertNotIn('payload', wire['affected'][0])
        self.assertNotIn('ledger', wire['affected'][0])
        result = writer.apply(wire, root_write_approved=True)
        self.assertEqual(result['cards'][0]['payload_file'], wire['affected'][0]['payload_file'])
        self.assertNotIn('payload', result['cards'][0])
        self.assertTrue(writer.apply(wire, root_write_approved=True)['already_applied'])
        with self.assertRaisesRegex(ValueError, 'fresh'):
            writer.materialize(plan, target)

    def test_stale_source_pin_rejects_without_any_candidate_change(self):
        plan = writer.prepare(self.f.request)
        before = self.f.candidate.read_bytes()
        Path(self.f.evidence['file']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            writer.apply(plan, root_write_approved=True)
        self.assertEqual(self.f.candidate.read_bytes(), before)

    def test_exact_official_chinese_only_bridge_preserves_both_real_sources(self):
        d = self.f.decisions[0]
        d['action'] = 'append_dictionary_sense'
        technical = self.f.native(chinese='')
        text = 'novel\n1. 新事物\n'
        pin = self.f.pin('secondary.txt', text.encode())
        ref = {'provider': 'official_web', 'source_url': 'https://dictionary.cambridge.org/dictionary/english-chinese-simplified/novel',
               'capture_file': pin['file'], 'capture_sha256': pin['sha256'], 'capture_format': 'text',
               'source_headword': 'novel', 'dictionary': 'fixture-official-bilingual'}
        secondary = {'source_ref_pin': ref, 'dictionary': 'fixture-official-bilingual', 'english_definition': None,
            'original_chinese': '新事物', 'scope_reason': 'fixture independently pins the same noun meaning',
            'native_locator': 'capture section 1', 'sense_equivalence': {'reading_rationale': 'fixture bilingual correspondence'},
            'native_block': {'capture_range': [6, 12], 'text': text[6:12]}}
        technical['dictionary_explanation']['secondary_source'] = secondary
        technical['new_sense'].update(text='新事物', original_chinese='新事物', translation_kind='cross_dictionary_original')
        technical['dictionary_source_pins'].append(ref)
        d['book_decisions'][0]['technical_decision'] = technical
        self.f.refresh()
        plan = writer.prepare(self.f.request)
        entry = plan['affected'][0]['payload']['definition_provenance']['supplemental_definitions']['appended'][0]
        self.assertEqual(entry['source_dictionary'], 'fixture-CALD4')
        self.assertEqual(entry['chinese_source']['dictionary'], 'fixture-official-bilingual')
        self.assertIsNone(entry['native_definition']['secondary_source']['english_definition'])
        technical['dictionary_explanation']['secondary_source']['native_block']['text'] = '篡改中文'
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'native block'):
            writer.prepare(self.f.request)

    def test_artifact_write_failure_removes_every_partial_file_and_allows_same_retry(self):
        plan = writer.prepare(self.f.request)
        target = self.f.root / 'engineering/writer-own/fault'
        original_open = Path.open
        def fail_open(path, *args, **kwargs):
            if str(path).endswith('-after.json') and args and args[0] == 'xb':
                with original_open(path, *args, **kwargs) as stream:
                    stream.write(b'partial')
                raise OSError('injected partial export failure')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', fail_open):
            with self.assertRaisesRegex(OSError, 'partial'):
                writer.materialize(plan, target)
        self.assertFalse(target.exists())
        self.assertEqual(writer.materialize(plan, target)['summary']['cards'], 1)

    def test_original_snapshot_payloads_and_unaffected_assignment_bytes_survive(self):
        plan = writer.prepare(self.f.request)
        with closing(sqlite3.connect(self.f.candidate)) as db:
            tables = ('snapshots', 'senses', 'occurrences', 'assignments')
            old = {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)] for t in tables}
        writer.apply(plan, root_write_approved=True)
        with closing(sqlite3.connect(self.f.candidate)) as db:
            for table, rows in old.items():
                after = [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
                self.assertTrue(all(row in after for row in rows))
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])  # tiny fixture only
        writer.rollback(plan, root_write_approved=True)
        self.assertEqual(sf.read_card(self.f.candidate, 'redbook2027', 'novel-card')['snapshot_id'], self.f.parents[0]['snapshot_id'])

    def test_auxiliary_entity_has_once_full_token_and_complete_old_history(self):
        d = self.f.decisions[0]
        d.update(action='rehome', actual_lemma='novel idea', actual_pos='phrase', meaning_zh='新颖想法', meaning_en='a new idea')
        b = d['book_decisions'][0]
        b.update(target_range=[2, 12], translation_ranges=[[6, 10]], auxiliary_entity={
            'lemma': 'novel idea', 'pos': 'phrase', 'meaning_zh': '新颖想法', 'meaning_en': 'a new idea',
            'dictionary_evidence': {'fixture': 'native capture'}, 'learning_card': False},
            technical_decision=self.f.native('novel idea', 'a new idea', '新颖想法'))
        self.f.refresh()
        plan = writer.prepare(self.f.request)
        self.assertEqual(plan['summary']['learning_cards_added'], 0)
        self.assertEqual(plan['summary']['auxiliary_physical_usages'], 1)
        usage = plan['entity_usages'][0]
        self.assertEqual(usage['row']['target_range'], [2, 12])
        self.assertEqual(usage['origins'][0]['source_parent_row'], self.f.items[0]['raw'][0]['occurrence'])
        self.assertEqual(plan['affected'][0]['new_count'], 1)
        writer.apply(plan, root_write_approved=True)
        self.assertEqual(len(writer.read_auxiliary_usages(self.f.candidate)), 1)
        writer.rollback(plan, root_write_approved=True)
        self.assertEqual(writer.read_auxiliary_usages(self.f.candidate), [])

    def test_wrong_book_sense_and_missing_crossbook_ref_are_rejected(self):
        self.f.decisions[0]['book_decisions'][0]['sense_id'] = 'not-this-book'
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'sense must belong'):
            writer.prepare(self.f.request)
        self.f.decisions[0]['book_decisions'] = []
        self.f.refresh()
        with self.assertRaisesRegex(ValueError, 'cross-book'):
            writer.prepare(self.f.request)

    def test_lexical_owner_identity_does_not_depend_on_native_or_context_source(self):
        old = self.f.items[0]['raw'][0]['occurrence']
        origins = []
        for book in ('redbook', 'redbook2027'):
            for index, kind in enumerate(('contextual_usage', 'dictionary_sense')):
                entity = {'lemma': 'novel idea', 'pos': 'phrase', 'kind': kind,
                    'is_dictionary_native': kind == 'dictionary_sense', 'meaning_zh': '新颖想法',
                    'native_definition': {'fixture_source_kind': kind},
                    'validated_source_evidence': {'fixture_verified_kind': kind}, 'learning_card': False}
                origins.append({'entity': entity, 'book_id': book, 'source_card_id': 'component-' + str(index),
                    'source_parent_row': deepcopy(old), 'target_range': [2, 12], 'translation_ranges': []})
        entities, usages = writer._canonical_auxiliary(origins)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]['canonical_identity_kind'], 'lexical_owner')
        self.assertEqual(len(usages), 2)
        for usage in usages:
            self.assertEqual(usage['physical_count'], 1)
            self.assertEqual(len(usage['origins']), 2)
            variants = usage['definition_variants']
            selected = next(v for v in variants if v['definition_id'] == usage['selected_definition_id'])
            self.assertTrue(selected['is_dictionary_native'])
            self.assertEqual({v['kind'] for v in variants}, {'dictionary_sense', 'contextual_usage'})
        self.assertEqual(writer._source_phrase_chinese_ranges(old, [2, 12]), [])
        marked = deepcopy(old)
        marked['alignment'] = {'alignments': [{'en': [2, 12], 'zh': [[6, 10]], 'relation': 'equivalent'}]}
        self.assertEqual(writer._source_phrase_chinese_ranges(marked, [2, 12]), [[6, 10]])

    def test_rehome_appending_native_sense_reseals_other_reviewed_target_rows(self):
        from tests.test_residual_optimization_transactions import TransactionFixture, _record
        english = 'They are going at the task.'
        at = _record(word='at', card='at-card', english=english, spans=((15, 17),),
                     translation='他们正在着手处理这项任务。', senses=[{'pos': 'prep.', 'text': '向；对'}])
        go = _record(word='go', card='go-card', english=english, spans=((9, 14),),
                     translation='他们正在着手处理这项任务。', senses=[{'pos': 'v.', 'text': '前往'}])
        other = _record(word='go', card='go-card', english='They go home.', spans=((5, 7),),
                        physical_block='block-2', translation='他们回家。', senses=go['senses'])['occurrences'][0]
        other['semantic_review'] = {'occurrence_id': sf.prepare_record({**go, 'occurrences': [other]})['occurrences'][0]['occurrence_id'],
                                    'reason': '完整旧目标卡其他例句审核'}
        go['occurrences'].append(other)
        go['expected_occurrences'] = 2
        with tempfile.TemporaryDirectory() as root:
            f = TransactionFixture(root, [at, go])
            target_parent = f.parents['go-card']
            companion = next(r for r in target_parent['occurrences'] if r['target_range'] == [9, 14])
            retained = next(r for r in target_parent['occurrences'] if r['target_range'] == [5, 7])
            native = self.f.native('go', 'start to do something', '着手干')
            native['new_sense']['pos'] = 'v.'
            forms = Path(root) / 'native-forms.html'
            forms.write_text('<section id="go_at">go at / going at: start to do something 着手干</section>')
            forms_pin = {'file': str(forms), 'sha256': writer.digest(forms.read_bytes())}
            def rehome(decision, item, parent, row):
                decision.update(action='rehome', actual_lemma='go at', actual_pos='v.', meaning_zh='着手干')
                decision['source_pins'].append(forms_pin)
                book = decision['book_decisions'][0]
                book['lexical_form_evidence'] = {'kind': 'native_inflected_form', 'surface': 'going at',
                    'lemma': 'go at', 'native_locator': 'go_at', 'form_text': 'go at / going at', 'source_pin': forms_pin}
                book['target'] = {'card_id': 'go-card', 'snapshot_id': target_parent['snapshot_id'],
                    'target_range': [9, 17], 'translation_ranges': [[4, 8]], 'technical_decision': native,
                    'replace_occurrence_id': companion['occurrence_id'], 'companion_source_row_sha256': writer.digest(companion),
                    'lexical_scope': {'kind': 'native_phrase', 'card_lemma': 'go', 'complete_lemma': 'go at',
                                      'native_scope_evidence': {'source_pin': forms_pin}}}
            plan = writer.prepare(f.request(rehome, cards={'at-card'}))
            child = next(c['payload'] for c in plan['affected'] if c['card_id'] == 'go-card')
            self.assertEqual(child['expected_occurrences'], 2)
            self.assertEqual(len(child['senses']), 2)
            current = next(r for r in child['occurrences'] if r['occurrence_id'] == retained['occurrence_id'])
            self.assertEqual(current['semantic_review'], retained['semantic_review'])
            self.assertNotEqual(current['assignment_context_hash'], retained['assignment_context_hash'])
            for row in child['occurrences']:
                sf._occurrence({**row, 'sense_index': next(s['ordinal'] for s in child['senses'] if s['sense_id'] == row['sense_id'])},
                               sf._definition(child))
            f.assert_source_unchanged(self)

    def test_display_projection_only_changes_display_and_preserves_original_comparison(self):
        value = completed_record()
        parent = sf.prepare_record(value)
        view = parent['occurrences'][0]['display']
        chunks = [{'mapping_id': 'm' + str(i), 'en': en, 'zh': zh, 'reason': 'actual fine bilingual block', 'source': 'fixture'}
                  for i, (en, zh) in enumerate([([0, 12], [[6, 10]]), ([13, 25], [[0, 6]]), ([26, 35], [[11, 16]])])]
        before = {'english': view['english'], 'translation': view['translation'], 'chunks': chunks,
                  'source_comparisons': [{'english': 'raw', 'translation': '原译'}], 'unmapped': []}
        item = {'mapping_id': chunks[0]['mapping_id'], 'display_id': 'test-display', 'display_english': view['english'],
                'display_translation': view['translation'], 'raw': {'projection_record': before}}
        d = {'mapping_id': item['mapping_id'], 'display_id': item['display_id'], 'original_source_pins': [self.f.evidence],
             'before_display_english': view['english'], 'before_display_translation': view['translation'],
             'before_display_english_hash': sf._sha(view['english']), 'before_display_translation_hash': sf._sha(view['translation']),
             'after_display_english': view['english'], 'after_display_translation': view['translation'], 'chunks': chunks,
             'source_comparisons': [{'english': 'second source', 'translation': '另一原译'}], 'transform': {'type': 'preserve actual completion'}}
        update = writer._display_update(d, item, {})
        self.assertEqual(update['after']['source_comparisons'][0], before['source_comparisons'][0])
        self.assertEqual(update['after']['residual_transform_evidence'], d['transform'])
        update['occurrence_ids'] = [r['occurrence_id'] for r in parent['occurrences']]
        detached = policy.producer_record(parent)
        detached.setdefault('exam_usage_policy', {})['residual_display_updates'] = [update]
        sealed = sf.prepare_record(detached)
        presented = writer.presentation_record(sealed)
        for original, result in zip(sealed['occurrences'], presented['occurrences']):
            self.assertEqual({k: v for k, v in original.items() if k != 'display'},
                             {k: v for k, v in result.items() if k != 'display'})
        self.assertEqual(sf.prepare_record(policy.producer_record(sealed)), sealed)

    def test_certified_physical_copy_reproduces_core_and_rejects_any_legacy_display_change(self):
        parent = sf.prepare_record(completed_record())
        producer = policy.producer_record(parent, preserve_scope=False)
        self.assertEqual(writer._physical_prepare(producer, certified=parent), sf.prepare_record(producer))
        producer['occurrences'][0]['reason'] = 'a new explicit review, same physical text'
        for row in producer['occurrences']:
            row.update(sf.seal_reviewed_assignment(producer, row))
        self.assertEqual(writer._physical_prepare(producer, certified=parent), sf.prepare_record(producer))
        producer['occurrences'][0]['display']['translation'] += '伪改'
        with self.assertRaisesRegex(ValueError, 'legacy v2 display'):
            writer._physical_prepare(producer, certified=parent, reseal=True)


if __name__ == '__main__':
    unittest.main()
