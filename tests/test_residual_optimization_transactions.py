"""Independent candidate-only transaction checks with small, disposable SQLite.

No production database or source corpus is opened. Baseline bytes, immutable
history documents, and active pointers are compared around real writer calls.
"""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from anki_pipeline import residual_optimization as ro
from anki_pipeline import sense_frequency as sf


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _record(word='novel', card='novel-card', english='A novel idea for a novel.',
            spans=((2, 7), (19, 24)), translation='一部小说中的新颖想法。', physical_block='block-1',
            senses=None):
    data = {'book_id': 'fixture-book', 'card_id': card, 'word': word,
            'definition_source': 'fixture-dictionary',
            'definition_provenance': {'entry': word, 'original_source': 'kept'},
            'expected_occurrences': len(spans),
            'senses': senses or [{'pos': 'n.', 'text': '原始名词义'}, {'pos': 'adj.', 'text': '原始形容词义'}],
            'occurrences': []}
    for n, span in enumerate(spans):
        row = {'physical_source': ['fixture-paper', physical_block], 'paper_id': 'kaoyan:2022-01',
               'sentence_id': 'kaoyan:2022-01:p:' + physical_block + ':0', 'english': english,
               'english_hash': _sha(english.encode()), 'translation': translation,
               'target_range': list(span), 'translation_ranges': [],
               'source': '2022年考研英语一 ➫ Text 1',
               'source_provenance': {'reviewedContentHash': 'fixture-source-review'},
               'status': 'reviewed', 'sense_index': n % len(data['senses']), 'reason': '原始完整核查理由',
               'method': 'fixture-context-review', 'review_version': 'fixture-v1'}
        data['occurrences'].append(sf.seal_reviewed_assignment(data, row))
    return data


class TransactionFixture:
    def __init__(self, root, records=None):
        self.root = Path(root)
        self.source = self.root / 'protected.sqlite3'
        self.candidate = self.root / 'candidate.sqlite3'
        sf.save_records(self.source, records or [_record()], self.root / 'backups')
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('CREATE TABLE exam_usage_update_runs(id TEXT PRIMARY KEY)')
            db.execute("INSERT INTO exam_usage_update_runs VALUES('immutable-history-run')")
            db.execute('''CREATE TABLE exam_usage_history_documents(
                run_id TEXT NOT NULL REFERENCES exam_usage_update_runs(id),
                book_id TEXT NOT NULL, card_id TEXT NOT NULL, parent_snapshot_id TEXT NOT NULL,
                source_url TEXT NOT NULL, source_sha256 TEXT NOT NULL,
                document_sha256 TEXT NOT NULL, original_html TEXT NOT NULL,
                PRIMARY KEY(run_id,book_id,card_id))''')
            self.parents = {}
            for book, card, sid, payload in db.execute('SELECT a.book_id,a.card_id,a.snapshot_id,s.payload '
                    'FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id').fetchall():
                self.parents[card] = json.loads(payload)
                html = '\ufeff<section>原审核完整理由与原译\n训练 ≠ training</section>\n' + card
                db.execute('INSERT INTO exam_usage_history_documents VALUES(?,?,?,?,?,?,?,?)',
                           ('immutable-history-run', book, card, sid, 'fixture://original/' + card,
                            _sha(html.encode()), _sha(html.encode()), html))
            db.commit()
        shutil.copyfile(self.source, self.candidate)
        self.source_bytes = self.source.read_bytes()
        self.source_stat = ro.stat_pin(self.source)
        self.evidence = self.pin_json('native-evidence.json',
            {'dictionary': 'Fixture bilingual dictionary', 'native_definition': 'original meaning',
             'chinese': '原始名词义', 'context': 'a separately reviewed actual usage'})

    def pin_json(self, name, value):
        path = self.root / name
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        path.write_bytes(raw)
        return {'file': str(path), 'sha256': _sha(raw)}

    def request(self, overrides=None, *, cards=None):
        items, decisions = [], []
        for card, parent in self.parents.items():
            if cards is not None and card not in cards:
                continue
            row = parent['occurrences'][0]
            binding = {key: parent[key] for key in ('book_id', 'card_id', 'snapshot_id')}
            binding['occurrence_id'] = row['occurrence_id']
            item = {'id': row['occurrence_id'], 'word': parent['word'], 'book_refs': [binding],
                    'raw': [{**binding, 'occurrence': row}]}
            decision = {'id': row['occurrence_id'], 'word': parent['word'],
                        'action': 'match_existing_sense', 'actual_lemma': parent['word'],
                        'actual_pos': 'n.', 'meaning_zh': '原始名词义',
                        'reason': '本次完整上下文核实，保留原释义与来源',
                        'context_evidence': ['the same exact source with a fuller explanation'],
                        'dictionary_evidence': [deepcopy(self.evidence)],
                        'source_pins': [deepcopy(self.evidence)],
                        'book_decisions': [{**binding, 'sense_id': row['sense_id']}],
                        'remaining_reason': None}
            if overrides:
                overrides(decision, item, parent, row)
            items.append(item)
            decisions.append(decision)
        input_pin = self.pin_json('semantic-inputs.json', items)
        decision_pin = self.pin_json('semantic-decisions.json', decisions)
        manifest = {'root': str(self.root), 'baseline': {'database': str(self.source)},
                    'semantic_jobs': [input_pin], 'chunk_jobs': [], 'source_inputs': []}
        manifest_pin = self.pin_json('manifest.json', manifest)
        return {'schema': ro.REQUEST, 'work_manifest': manifest_pin,
                'baseline': {'file': str(self.source), 'stat': self.source_stat,
                             'certified_sha256': _sha(self.source_bytes)},
                'candidate': {'file': str(self.candidate)},
                'semantic': [{'input': input_pin, 'decisions': decision_pin}], 'chunks': []}

    def state(self, path=None):
        with closing(sqlite3.connect(path or self.candidate)) as db:
            active = db.execute('SELECT * FROM active_snapshots ORDER BY book_id,card_id').fetchall()
            history = db.execute('SELECT * FROM exam_usage_history_documents ORDER BY book_id,card_id').fetchall()
            active_payloads = db.execute('SELECT s.id,s.payload FROM active_snapshots a '
                    'JOIN snapshots s ON s.id=a.snapshot_id ORDER BY a.book_id,a.card_id').fetchall()
            return {'active': active, 'history': history,
                    'history_utf8': [(r[-1].encode('utf-8')) for r in history],
                    'active_payload_bytes': [(sid, payload.encode('utf-8')) for sid, payload in active_payloads]}

    def assert_source_unchanged(self, case):
        case.assertEqual(self.source.read_bytes(), self.source_bytes)
        case.assertEqual(ro.stat_pin(self.source), self.source_stat)


class ResidualOptimizationTransactionTests(unittest.TestCase):
    def test_prepare_is_readonly_and_rejects_source_path_symlink_and_hardlink(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root)
            request = fixture.request()
            plan = ro.prepare(request)
            self.assertEqual(len(plan['affected']), 1)
            fixture.assert_source_unchanged(self)
            for kind in ('same', 'symlink', 'hardlink'):
                path = fixture.source
                if kind != 'same':
                    path = Path(root) / (kind + '.sqlite3')
                    if kind == 'symlink':
                        path.symlink_to(fixture.source)
                    else:
                        os.link(fixture.source, path)
                bad = deepcopy(request)
                bad['candidate']['file'] = str(path)
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'candidate|alias'):
                    ro.prepare(bad)
                fixture.assert_source_unchanged(self)

    def test_apply_and_rollback_refuse_protected_source_aliases_before_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root)
            plan = ro.prepare(fixture.request())
            hardlink = Path(root) / 'writer-alias.sqlite3'
            os.link(fixture.source, hardlink)
            for candidate in (fixture.source, hardlink):
                bad = deepcopy(plan)
                bad['candidate'] = str(candidate)
                bad['run_id'] = ro.digest({k: v for k, v in bad.items() if k != 'run_id'})
                for operation in (ro.apply, ro.rollback):
                    with self.subTest(candidate=str(candidate), operation=operation.__name__):
                        with self.assertRaisesRegex(ValueError, 'source/alias'):
                            operation(bad, root_write_approved=True)
                        fixture.assert_source_unchanged(self)

    def test_stale_active_candidate_is_rejected_without_touching_history(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root)
            plan = ro.prepare(fixture.request())
            revised = _record()
            revised['occurrences'][0]['reason'] = 'later independent active change'
            revised['occurrences'][0] = sf.seal_reviewed_assignment(revised, revised['occurrences'][0])
            sf.save_records(fixture.candidate, [revised], Path(root) / 'candidate-backups')
            before = fixture.state()
            with self.assertRaisesRegex(ValueError, 'active graph'):
                ro.apply(plan, root_write_approved=True)
            self.assertEqual(fixture.state(), before)
            fixture.assert_source_unchanged(self)

    def test_injected_partial_apply_is_atomic_and_keeps_original_active_payloads(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root, [_record(),
                _record(card='second-novel-card', physical_block='block-2')])
            plan = ro.prepare(fixture.request())
            before = fixture.state()
            with self.assertRaisesRegex(RuntimeError, 'injected transaction failure'):
                ro.apply(plan, root_write_approved=True, fail_after_cards=1)
            self.assertEqual(fixture.state(), before)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='residual_batches'").fetchone())
            fixture.assert_source_unchanged(self)

    def test_apply_counts_fk_idempotence_and_rollback_restore_history_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root)
            plan = ro.prepare(fixture.request())
            before = fixture.state()
            first = ro.apply(plan, root_write_approved=True)
            self.assertFalse(first['already_applied'])
            after = fixture.state()
            self.assertNotEqual(after['active'], before['active'])
            self.assertEqual(after['history_utf8'], before['history_utf8'])
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
                child = plan['affected'][0]['child_snapshot_id']
                self.assertEqual(db.execute('SELECT count(*) FROM occurrences WHERE snapshot_id=?',
                                            (child,)).fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT count(*) FROM assignments WHERE snapshot_id=?',
                                            (child,)).fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT payload FROM snapshots WHERE id=?',
                                            (plan['affected'][0]['parent_snapshot_id'],)).fetchone()[0].encode(),
                                 before['active_payload_bytes'][0][1])
            repeated = ro.apply(plan, root_write_approved=True)
            self.assertTrue(repeated['already_applied'])
            self.assertEqual(fixture.state(), after)
            rollback = ro.rollback(plan, root_write_approved=True)
            self.assertTrue(rollback['rolled_back'])
            self.assertEqual(fixture.state(), before)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('SELECT state FROM residual_batches WHERE run_id=?',
                                            (plan['run_id'],)).fetchone()[0], 'rolled_back')
                self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            fixture.assert_source_unchanged(self)

    def test_contextual_append_retains_dictionary_base_and_never_claims_native_text(self):
        def contextual(decision, item, parent, row):
            decision['action'] = 'contextual_usage'
            decision['book_decisions'][0]['contextual_sense'] = {
                'kind': 'contextual_usage', 'is_dictionary_native': False,
                'pos': 'adj.', 'text': '在本语境中新出现的', 'english': 'newly arising in this context',
                'base_sense_ids': [row['sense_id']],
                'native_base_evidence': {'base': row['sense_id'], 'source': 'fixture dictionary'}}
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root)
            request = fixture.request(contextual)
            plan = ro.prepare(request)
            child = plan['affected'][0]['payload']
            supplement, = child['definition_provenance']['supplemental_definitions']['appended']
            self.assertFalse(supplement['is_dictionary_native'])
            self.assertEqual(supplement['source_dictionary'], 'contextual_review')
            self.assertEqual(supplement['translation_kind'], 'contextual_review')
            self.assertEqual(supplement['translation_label'], '语境释义')
            self.assertIsNone(supplement['original_chinese'])
            self.assertTrue(supplement['native_base_evidence'])
            self.assertEqual(child['expected_occurrences'], 2)
            self.assertEqual(len(child['senses']), 3)
            ro.apply(plan, root_write_approved=True)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                persisted = json.loads(db.execute('SELECT payload FROM snapshots WHERE id=?',
                    (child['snapshot_id'],)).fetchone()[0])
                self.assertEqual(persisted, child)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            # Re-read a new pinned decision, with only the native claim changed.
            bad = fixture.request(contextual)
            pin = bad['semantic'][0]['decisions']
            values = json.loads(Path(pin['file']).read_text())
            values[0]['book_decisions'][0]['contextual_sense']['is_dictionary_native'] = True
            bad['semantic'][0]['decisions'] = fixture.pin_json('false-native-decision.json', values)
            with self.assertRaisesRegex(ValueError, 'distinguish review from native'):
                ro.prepare(bad)
            fixture.assert_source_unchanged(self)

    def test_two_component_cards_rehome_one_full_lexeme_and_keep_both_origin_rows(self):
        english = 'They prefer plant-based meat.'
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root, [
                _record(word='plant', card='plant-card', english=english,
                        spans=((12, 17),), translation='他们更喜欢植物肉。'),
                _record(word='meat', card='meat-card', english=english,
                        spans=((24, 28),), translation='他们更喜欢植物肉。')])
            native = Path(root) / 'native-bilingual.html'
            native.write_text('<section id="plant_based_meat_1">meat made from plants 植物制成的肉</section>')
            native_pin = {'file': str(native), 'sha256': _sha(native.read_bytes())}
            def rehome(decision, item, parent, row):
                decision.update(action='rehome', actual_lemma='plant-based meat',
                                actual_pos='n.', meaning_zh='植物制成的肉', meaning_en='meat made from plants',
                                dictionary_evidence=[deepcopy(native_pin)])
                decision['source_pins'].append(deepcopy(native_pin))
                book = decision['book_decisions'][0]
                book.update(target_range=[12, 28], translation_ranges=[[5, 8]],
                    auxiliary_entity={'lemma': 'plant-based meat', 'pos': 'n.',
                        'meaning_zh': '植物制成的肉', 'meaning_en': 'meat made from plants',
                        'dictionary_evidence': [deepcopy(native_pin)], 'learning_card': False},
                    new_sense={'pos': 'n.', 'dictionary': 'Fixture bilingual dictionary', 'version': 'fixture-v1',
                        'exact_headword': 'plant-based meat', 'native_sense_id': 'plant_based_meat_1',
                        'source_entry_id': 42, 'original_english': 'meat made from plants',
                        'original_chinese': '植物制成的肉', 'source_evidence': deepcopy(native_pin)})
            plan = ro.prepare(fixture.request(rehome))
            self.assertEqual(len(plan['entities']), 1)
            usage, = plan['entity_usages']
            self.assertEqual(usage['physical_count'], 1)
            self.assertEqual(usage['row']['target_range'], [12, 28])
            self.assertEqual({o['source_card_id'] for o in usage['origins']}, {'plant-card', 'meat-card'})
            self.assertEqual({tuple(o['source_parent_row']['target_range']) for o in usage['origins']},
                             {(12, 17), (24, 28)})
            self.assertEqual(len(usage['origins']), 2)
            self.assertEqual([c['new_count'] for c in plan['affected']], [0, 0])
            self.assertEqual(plan['summary']['learning_cards_added'], 0)
            before = fixture.state()
            ro.apply(plan, root_write_approved=True)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM active_snapshots').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT count(*) FROM residual_entities').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM residual_entity_usages').fetchone()[0], 1)
                stored = json.loads(db.execute('SELECT payload FROM residual_entity_usages').fetchone()[0])
                self.assertEqual(stored, usage)
                self.assertEqual(len(stored['origins']), 2)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            ro.rollback(plan, root_write_approved=True)
            self.assertEqual(fixture.state(), before)
            fixture.assert_source_unchanged(self)

    def test_chunk_only_spooled_materialized_overlay_never_changes_physical_snapshot(self):
        from tests.test_sense_frequency import completed_record
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root, [completed_record()])
            parent = fixture.parents['novel-card']
            view = parent['occurrences'][0]['display']
            chunks = [{'mapping_id': 'chunk-' + str(i), 'en': en, 'zh': zh,
                       'reason': '原已分块在完成译文中仍完整保留', 'source': 'fixture original bilingual chunk'}
                      for i, (en, zh) in enumerate([([0, 12], [[6, 10]]),
                                                   ([13, 25], [[0, 6]]), ([26, 35], [[11, 16]])])]
            before = {'english': view['english'], 'translation': view['translation'], 'chunks': deepcopy(chunks),
                      'source_comparisons': [{'english': view['english'], 'translation': view['translation']}],
                      'unmapped': []}
            refs = [{**{k: parent[k] for k in ('book_id', 'card_id', 'snapshot_id')},
                     'occurrence_id': row['occurrence_id']} for row in parent['occurrences']]
            item = {'mapping_id': 'chunk-2', 'display_id': 'fixture-completed-display',
                    'display_english': view['english'], 'display_translation': view['translation'],
                    'raw': {'projection_record': before}}
            decision = {'mapping_id': item['mapping_id'], 'display_id': item['display_id'],
                        'before_display_english': view['english'], 'before_display_translation': view['translation'],
                        'before_display_english_hash': sf._sha(view['english']),
                        'before_display_translation_hash': sf._sha(view['translation']),
                        'after_display_english': view['english'],
                        'after_display_translation': view['translation'].replace('获得成功', '取得成功'),
                        'chunks': chunks, 'original_source_pins': [fixture.evidence], 'book_refs': refs,
                        'source_comparisons': [{'english': view['english'], 'translation': view['translation']}],
                        'transform': {'kind': 'only-reviewed-display-translation'}}
            request = fixture.request(cards=set())
            input_pin = fixture.pin_json('chunk-inputs.json', [item])
            decision_pin = fixture.pin_json('chunk-decisions.json', [decision])
            manifest = ro.read_json(request['work_manifest'])
            manifest['chunk_jobs'] = [input_pin]
            request['work_manifest'] = fixture.pin_json('chunk-manifest.json', manifest)
            request['chunks'] = [{'input': input_pin, 'decisions': decision_pin}]
            request['readonly_spool'] = str(Path(root) / 'engineering/writer-own/readonly-spool')
            original = fixture.state()
            plan = ro.prepare(request)
            card, = plan['affected']
            self.assertFalse(card['physical_updated'])
            self.assertEqual(card['parent_snapshot_id'], parent['snapshot_id'])
            self.assertEqual(card['child_snapshot_id'], parent['snapshot_id'])
            self.assertNotIn('payload', card)
            self.assertEqual(ro.read_json(card['payload_file']), parent)
            overlays = card['ledger']['residual_display_updates']
            presented = ro.presentation_record(parent, display_updates=overlays)
            self.assertEqual(presented['snapshot_id'], parent['snapshot_id'])
            for raw, shown in zip(parent['occurrences'], presented['occurrences']):
                self.assertEqual({k: v for k, v in raw.items() if k != 'display'},
                                 {k: v for k, v in shown.items() if k != 'display'})
                self.assertIn('取得成功', shown['display']['translation'])
                self.assertEqual(raw['display']['translation'], view['translation'])
            materialized = ro.materialize(plan, Path(root) / 'engineering/writer-own/materialized')
            wire = ro.read_json(materialized['plan'])
            self.assertEqual(wire['affected'][0]['child_snapshot_id'], parent['snapshot_id'])
            ro.apply(wire, root_write_approved=True)
            self.assertEqual(fixture.state(), original)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT count(*) FROM residual_display_updates').fetchone()[0], 1)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            ro.rollback(wire, root_write_approved=True)
            self.assertEqual(fixture.state(), original)
            with self.assertRaisesRegex(ValueError, 'fresh writer-owned readonly spool'):
                ro.prepare(request)
            fixture.assert_source_unchanged(self)

    def test_native_phrase_replaces_existing_companion_once_with_both_complete_histories(self):
        english = 'They are going at the task.'
        records = [_record(word='at', card='at-card', english=english, spans=((15, 17),),
                           translation='他们正在着手处理这项任务。', senses=[{'pos': 'prep.', 'text': '向；对'}]),
                   _record(word='go', card='go-card', english=english, spans=((9, 14),),
                           translation='他们正在着手处理这项任务。', senses=[{'pos': 'v.', 'text': '着手干；攻击'}])]
        for record in records:
            row = record['occurrences'][0]
            oid = sf.prepare_record(record)['occurrences'][0]['occurrence_id']
            row['semantic_review'] = {'occurrence_id': oid, 'reason': '完整旧审核说明 ' + record['word'],
                                      'original_evidence': {'english': english, 'translation': row['translation']}}
        with tempfile.TemporaryDirectory() as root:
            fixture = TransactionFixture(root, records)
            at_parent, go_parent = fixture.parents['at-card'], fixture.parents['go-card']
            old_at, old_go = at_parent['occurrences'][0], go_parent['occurrences'][0]
            native = Path(root) / 'native-go-at.html'
            native.write_text('<section id="go_at_1">go at / going at: start to do something 着手干</section>')
            native_pin = {'file': str(native), 'sha256': _sha(native.read_bytes())}
            def rehome(decision, item, parent, row):
                decision.update(action='rehome', actual_lemma='go at', actual_pos='v.',
                                meaning_zh='着手干', dictionary_evidence=[native_pin])
                decision['source_pins'].append(native_pin)
                book = decision['book_decisions'][0]
                book['lexical_form_evidence'] = {'surface': 'going at', 'lemma': 'go at',
                    'kind': 'native_inflected_form', 'native_locator': 'go_at_1',
                    'form_text': 'go at / going at', 'source_pin': native_pin}
                book['target'] = {'book_id': go_parent['book_id'], 'card_id': go_parent['card_id'],
                    'snapshot_id': go_parent['snapshot_id'], 'target_range': [9, 17],
                    'translation_ranges': [[4, 8]], 'sense_id': old_go['sense_id'],
                    'replace_occurrence_id': old_go['occurrence_id'],
                    'companion_source_row_sha256': ro.digest(old_go),
                    'lexical_scope': {'kind': 'native_phrase', 'card_lemma': 'go', 'complete_lemma': 'go at',
                        'native_scope_evidence': {'source_pin': native_pin, 'native_locator': 'go_at_1',
                                                  'original_definition': 'start to do something'}}}
            request = fixture.request(rehome, cards={'at-card'})
            plan = ro.prepare(request)
            source = next(c for c in plan['affected'] if c['card_id'] == 'at-card')
            target = next(c for c in plan['affected'] if c['card_id'] == 'go-card')
            self.assertEqual(source['new_count'], 0)
            self.assertEqual(target['new_count'], target['original_count'])
            current, = target['payload']['occurrences']
            self.assertEqual(current['target_range'], [9, 17])
            self.assertNotIn(current['occurrence_id'], (old_at['occurrence_id'], old_go['occurrence_id']))
            self.assertEqual(current['semantic_review']['occurrence_id'], current['occurrence_id'])
            history = current['semantic_review']['residual_owner_history']
            self.assertEqual(history['source_parent_row'], old_at)
            self.assertEqual(history['companion_parent_row'], old_go)
            self.assertEqual(history['source_parent_row_sha256'], ro.digest(old_at))
            self.assertEqual(history['companion_parent_row_sha256'], ro.digest(old_go))
            self.assertEqual(history['source_parent_row']['semantic_review']['reason'], '完整旧审核说明 at')
            self.assertEqual(history['companion_parent_row']['semantic_review']['reason'], '完整旧审核说明 go')
            original = fixture.state()
            ro.apply(plan, root_write_approved=True)
            with closing(sqlite3.connect(fixture.candidate)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM occurrences WHERE snapshot_id=?',
                                            (target['child_snapshot_id'],)).fetchone()[0], 1)
                persisted = json.loads(db.execute('SELECT payload FROM snapshots WHERE id=?',
                                            (target['child_snapshot_id'],)).fetchone()[0])
                self.assertEqual(persisted['occurrences'][0]['semantic_review']['residual_owner_history'], history)
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            ro.rollback(plan, root_write_approved=True)
            self.assertEqual(fixture.state(), original)
            bad = fixture.request(rehome, cards={'at-card'})
            pin = bad['semantic'][0]['decisions']
            values = ro.read_json(pin)
            values[0]['book_decisions'][0]['target']['companion_source_row_sha256'] = '0' * 64
            bad['semantic'][0]['decisions'] = fixture.pin_json('stale-companion-decisions.json', values)
            with self.assertRaisesRegex(ValueError, 'companion is not the exact'):
                ro.prepare(bad)
            fixture.assert_source_unchanged(self)


if __name__ == '__main__':
    unittest.main()
