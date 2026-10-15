"""Candidate exclusions need an approved audit AND a live physical-source read."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import sense_candidate_scope as cs
from anki_pipeline import sense_display as sd
from anki_pipeline import sense_frequency as sf
from anki_pipeline import sense_frequency_reconcile as sr
from anki_pipeline.packaging import _exam_frequency_markup
from tests.test_sense_frequency_reconcile import source


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _write(path, value):
    text = json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n'
    path.write_text(text)
    return _sha(text)


def candidate_fixture(directory, *, edition='redbook2027'):
    """Small complete source/audit fixture; never mock the overlay or planner."""
    directory = Path(directory)
    inventory = directory / 'full-inventory-v2'
    inventory.mkdir(exist_ok=True)
    definitions = [f'<div class="dictionary-definition" data-dictionary="oxford">'
        f'<div class="definition-row"><span class="part-of-speech">{pos}</span>'
        f'<span class="definition-text">{meaning}</span></div></div>'
        for pos, meaning in [('indefinite article', '一'), ('det.', '一个')]]
    rows = []
    for index, token in enumerate(('a', 'as', 'A', 'As', 'an')):
        english, paper = 'Use ' + token + ' here.', f'kaoyan:{2019 + index}-01'
        row = {'physical_source': [paper + ':p:first:0'], 'paper_id': paper,
            'sentence_id': paper + ':p:first:0', 'english': english, 'english_hash': _sha(english),
            'translation': '请用这个。', 'source': str(2019 + index) + '年考研英语一',
            'target_range': [4, 4 + len(token)], 'translation_ranges': [],
            'alignment': None, 'alignment_evidence': [],
            'source_provenance': {'reviewedContentHash': _sha(str(index))},
            'status': 'unmatched', 'sense_index': None, 'reason': 'unreviewed raw candidate',
            'method': 'pending-context-review', 'review_version': 'raw-test'}
        rows.append(row)
    form_group = ('<div class="dictionary-form-groups" data-dictionary="webster">'
        '<section class="dictionary-inflections"><dl class="form-row"><dt>复数</dt>'
        '<dd>as</dd></dl></section></div>')
    forms = ('<section class="forms-section"><h3>a · 词形</h3>' + form_group + '</section>'
        '<section class="forms-section"><h3>an · 词形</h3><div class="dictionary-form-groups" '
        'data-dictionary="webster"><section class="dictionary-inflections">无词形</section>'
        '</div></section>')
    components = [{'component_index': i, 'headword': word, 'sense_start': i,
        'sense_count': 1, 'source': 'oxford', 'html_sha256': _sha(fragment)}
        for i, (word, fragment) in enumerate(zip(('a', 'an'), definitions))]
    panels = [_exam_frequency_markup({'exam_frequency': sr._frequency(group, 44)})
              for group in (rows[:4], rows[4:])]
    word = 'a/an'
    page = ('<html><body><h1 class="word">a/an</h1><section><h3>a</h3>' + panels[0] +
        definitions[0] + '</section><section><h3>an</h3>' + panels[1] + definitions[1] +
        '</section>' + forms + '</body></html>')
    provenance = {'headword': word, 'page_sha256': _sha(page), 'web_source': '/a-an.html',
                  'components': components}
    record = {'book_id': edition, 'card_id': 'article-card', 'word': word,
        'definition_source': 'oxford', 'definition_provenance': provenance, 'expected_occurrences': 5,
        'matching_evidence': [], 'senses': [{'pos': 'indefinite article', 'text': '一'},
        {'pos': 'det.', 'text': '一个'}], 'occurrences': rows}
    raw_data = sr._json(record) + '\n'
    (inventory / 'records.jsonl').write_text(raw_data)
    manifest_sha = _write(inventory / 'inventory.json', {'records': 1})
    page_path = directory / 'original.html'
    page_path.write_text(page)
    source_path = directory / 'canonical.json'
    source_sha = _write(source_path, {'original': True})
    sources = {'sentences': {row['sentence_id']: source(row) for row in rows},
               'completions': {}, 'options': {}, 'watched': {source_path: source_sha}}
    exclusions = []
    for index in (1, 3):
        row = rows[index]
        exclusions.append({'global_index': index, 'work_id': 'article-work',
            'physical_id': cs._physical(row), 'raw_english_hash': row['english_hash'],
            'actual_token': row['english'][slice(*row['target_range'])],
            'english': row['english'], 'translation': row['translation'], 'source': row['source'],
            'source_provenance': row['source_provenance'], 'context_proof_ref': row['sentence_id'],
            'canonical_sentence_exact_match': True, 'classification': 'different_lemma_as',
            'same_original_article_headword': False, 'a_noun_plural': False,
            'reason': 'as 为其他 lemma，不是冠词。'})
    audit = {'schema': 'codex-a-an-form-audit.v1', 'book_id': edition, 'card_id': 'article-card',
        'work_id': 'article-work', 'summary': {'raw_physical_total': 5, 'pending_as': 0,
            'confirmed_same_original_article_headword_as': 0, 'confirmed_letter_or_grade_a_noun_plural_as': 0,
            'safe_to_exclude_all_as_from_article_candidate_denominator': True,
            'non_as_candidate_count_is_not_certified_article_total': True,
            'non_as_candidate_count_after_overlay': 3, 'excluded_as_indices': [1, 3],
            'raw_casefold_counts': {'a': 2, 'as': 2, 'an': 1}},
        'pending': [], 'same_headword_as_records': [], 'confirmed_exclusions': exclusions,
        'non_as_retained_candidate_indices': [0, 2, 4],
        'original_book_intent': {'definition_provenance': deepcopy(provenance)},
        'word_form_origin': {'formal_page_forms_raw': forms,
            'formal_page_form_raw_character_range': [page.index(forms), page.index(forms) + len(forms)]},
        'context_proofs': {row['sentence_id']: {'raw_source_english': row['english']} for row in rows},
        'source_snapshot': {'inventory_record_byte_locator': {'book_id': edition, 'card_id': record['card_id'],
            'word': word, 'byte_offset': 0, 'byte_length': len(raw_data.encode()), 'occurrences': 5, 'senses': 2},
            'inventory_record_sha256': _sha(raw_data), 'inventory_manifest_sha256': manifest_sha,
            'official_page': str(page_path), 'official_page_sha256': _sha(page),
            'canonical_and_structured_files': {str(source_path): source_sha}}}
    audit_path = directory / 'a-an-form-audit.json'
    audit_sha = _write(audit_path, audit)
    # Legitimate merged reviews differ from the original inventory. Uppercase A
    # remains unresolved; no candidate exclusion implies article confirmation.
    record = deepcopy(record)
    for index, sense in ((0, 0), (4, 1)):
        row = record['occurrences'][index]
        row.update(status='reviewed', sense_index=sense, reason='explicit article review',
            semantic_review_provenance={'index': index, 'source_file_sha256': 'f' * 64})
        record['occurrences'][index] = sf.seal_reviewed_assignment(record, row)
    return record, page, sources, audit_path, audit_sha


def scope_fixture(directory):
    """Return (filtered raw record, ledger) for core persistence integration tests."""
    record, page, sources, audit_path, digest = candidate_fixture(directory)
    with patch.object(sd, '_load_sources', return_value=sources):
        records, verified = sr.reread_source_displays([record], {record['card_id']: page}, {})
    filtered, scopes = cs.apply_candidate_scope(records, {record['card_id']: page}, {},
        verified_sources=verified, audit_path=audit_path, expected_audit_sha256=digest)
    return filtered[0], scopes.for_record(filtered[0]).verification()


def supplement_fixture(directory, primary_record, primary_page, audit_path):
    """Map 2026's independently indexed a card into the primary physical proof."""
    directory = Path(directory)
    audit = json.loads(audit_path.read_text())
    definition = list(sr._fragments(primary_page, 'div', 'dictionary-definition', {}))[0]
    forms = list(sr._fragments(primary_page, 'section', 'forms-section', {}))[0]
    # Reverse 2026 raw order to prove that no 2027 global index is reused.
    source_indices = [3, 2, 1, 0]
    raw27 = json.loads((directory / 'full-inventory-v2/records.jsonl').read_text())
    record = deepcopy(raw27)
    record.update(book_id='redbook', card_id='independent-a', word='a', expected_occurrences=4,
        senses=[raw27['senses'][0]], occurrences=[deepcopy(raw27['occurrences'][i]) for i in source_indices])
    panel = _exam_frequency_markup({'exam_frequency': sr._frequency(record['occurrences'], 44)})
    page = '<html><body><h1 class="word">a</h1>' + panel + definition + forms + '</body></html>'
    component = deepcopy(raw27['definition_provenance']['components'][0])
    record['definition_provenance'] = {'headword': 'a', 'page_sha256': _sha(page),
        'web_source': '/independent-a.html', 'components': [component]}
    path = directory / 'independent-a.html'
    path.write_text(page)
    inventory_path = directory / 'full-inventory-v2/records.jsonl'
    original = inventory_path.read_bytes()
    data = (sr._json(record) + '\n').encode()
    inventory_path.write_bytes(original + data)
    manifest_sha = _write(directory / 'full-inventory-v2/inventory.json', {'records': 2})
    audit['source_snapshot']['inventory_manifest_sha256'] = manifest_sha
    primary_sha = _write(audit_path, audit)
    mapping = []
    for index, original_index in enumerate(source_indices):
        if original_index not in (1, 3):
            continue
        proof = next(item for item in audit['confirmed_exclusions'] if item['global_index'] == original_index)
        mapping.append({'global_index_2026': index, 'global_index_2027': original_index,
            **{field: deepcopy(proof[field]) for field in ('physical_id', 'raw_english_hash', 'actual_token', 'source')},
            'context_proof_ref_in_primary_audit': proof['context_proof_ref'],
            'identical_raw_english_translation_source_and_provenance': True,
            'classification': 'different_lemma_as'})
    supplement = {'schema': 'codex-a-an-form-audit-2026-supplement.v1',
        'primary_audit': {'sha256': primary_sha, '2027_work_id': audit['work_id'], '2027_card_id': audit['card_id']},
        'summary': {'safe_to_reuse_primary_as_exclusion_by_exact_physical_binding': True,
            '2026_a_as_pending': 0, '2027_as_missing_in_2026': [],
            '2026_a_candidate_total_after_as_only_overlay': 2},
        'pending_2026_as_indices': [], 'strict_2026_as_exclusion_indices': [0, 2],
        'physical_evidence_map': mapping, 'bindings': {'a': {'work_id': 'independent-a-work',
            'inventory_card_id': record['card_id'], 'raw_occurrences': 4,
            'definition_provenance': record['definition_provenance'],
            'formal_page': str(path), 'formal_page_sha256': _sha(page),
            'formal_page_forms_raw': forms, 'formal_page_forms_raw_character_range':
                [page.index(forms), page.index(forms) + len(forms)],
            'surface_casefold_counts': {'a': 2, 'as': 2},
            'inventory_record_sha256': hashlib.sha256(data).hexdigest(),
            'inventory_record_byte_locator': {'book_id': record['book_id'], 'card_id': record['card_id'],
                'word': 'a', 'byte_offset': len(original), 'byte_length': len(data), 'occurrences': 4, 'senses': 1}}}}
    supplement_path = directory / 'a-an-form-audit-2026-supplement.json'
    supplement_sha = _write(supplement_path, supplement)
    return record, page, primary_sha, supplement_path, supplement_sha


class CandidateScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.record, self.page, self.sources, self.path, self.digest = candidate_fixture(self.directory.name)

    def verified(self, record=None, page=None):
        record, page = record or self.record, self.page if page is None else page
        with patch.object(sd, '_load_sources', return_value=self.sources):
            records, capability = sr.reread_source_displays([record], {record['card_id']: page}, {})
        return records, capability

    def apply(self, records=None, capability=None, **overrides):
        if records is None:
            records, capability = self.verified()
        options = {'verified_sources': capability, 'audit_path': self.path,
                   'expected_audit_sha256': self.digest}
        options.update(overrides)
        return cs.apply_candidate_scope(records, {self.record['card_id']: self.page}, {}, **options)

    def rewrite_audit(self, change):
        audit = json.loads(self.path.read_text())
        change(audit)
        return _write(self.path, audit)

    def test_exact_exclusions_preserve_inputs_retained_seals_and_full_reversible_ledger(self):
        records, capability = self.verified()
        original = deepcopy(records)
        filtered, scopes = self.apply(records, capability)
        record = filtered[0]
        scope = scopes.for_record(record)
        ledger = scope.verification()
        self.assertEqual(records, original)
        self.assertEqual(record['expected_occurrences'], 3)
        self.assertEqual(record['occurrences'], [original[0]['occurrences'][i] for i in (0, 2, 4)])
        self.assertEqual(ledger['excluded'][0]['occurrence'], original[0]['occurrences'][1])
        self.assertEqual(record['occurrences'][1]['status'], 'unmatched')
        self.assertIsNone(ledger['certified_article_total'])
        self.assertIn('不能视为全部已确认', ledger['notice'])
        self.assertEqual(cs.validate_stored_scope({**record, 'candidate_scope': ledger}, ledger), ledger)
        scopes.verified_sources._require(self.page, record, {})
        with self.assertRaises(AttributeError): scope._payload = '{}'
        ledger['excluded'][0]['reason'] = 'mutated copy'
        self.assertNotEqual(ledger, scope.verification())

    def test_multi_component_panels_recalculate_only_source_candidates_and_restore_exact_bytes(self):
        filtered, scopes = self.apply()
        record = filtered[0]
        plan = sr.plan_frequency_panel(self.page, record, {}, verified_sources=scopes.verified_sources,
            candidate_scope=scopes.for_record(record))
        audit = plan.verification()
        self.assertEqual([component['old_frequency']['occurrences'] for component in audit['component_panels']], [4, 1])
        self.assertEqual([component['new_frequency']['occurrences'] for component in audit['component_panels']], [2, 1])
        revised = sr.apply_frequency_panel(self.page, plan)
        self.assertEqual(sr.restore_frequency_panel(revised, plan), self.page)
        self.assertIn('原始词形候选5次', revised)
        for fragment in sr._fragments(self.page, 'div', 'dictionary-definition', {}):
            self.assertIn(fragment, revised)
        self.assertIn('data-occurrences="2"', revised)
        with self.assertRaises(ValueError): sr.apply_frequency_panel(revised, plan)
        with self.assertRaises(ValueError): sr.restore_frequency_panel(revised + ' ', plan)

    def test_missing_live_capability_or_approval_pin_cannot_authorize_scope(self):
        records, capability = self.verified()
        for missing in (None, True, {'sha256': _sha(self.page)}):
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, 'producer'):
                self.apply(records, missing)
        for pin in (None, '0' * 64):
            with self.assertRaises(ValueError): self.apply(records, capability, expected_audit_sha256=pin)

    def test_after_read_context_page_and_retained_assignment_changes_fail_closed(self):
        records, capability = self.verified()
        for kind in ('physical', 'english', 'target', 'reason', 'definition'):
            changed = deepcopy(records)
            row = changed[0]['occurrences'][0]
            if kind == 'physical': row['physical_source'] = ['invented']
            if kind == 'english': row['english'] += 'changed'
            if kind == 'target': row['target_range'] = [0, 3]
            if kind == 'reason': row['reason'] = 'changed'
            if kind == 'definition': changed[0]['senses'][0]['text'] = 'different'
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.apply(changed, capability)
        original_page = self.page
        self.page += 'changed'
        with self.assertRaises(ValueError): self.apply(records, capability)
        self.page = original_page

    def test_fresh_live_capability_cannot_hide_changed_raw_inventory_context(self):
        changed = deepcopy(self.record)
        changed['occurrences'][2]['source'] += 'wrong source'
        records, capability = self.verified(changed)
        with self.assertRaisesRegex(ValueError, 'merged linguistic'):
            self.apply(records, capability)

    def test_reviewed_other_lemma_exclusion_is_a_conflict_not_silently_dropped(self):
        changed = deepcopy(self.record)
        row = changed['occurrences'][1]
        row.update(status='reviewed', sense_index=0, reason='incorrect reviewed article')
        changed['occurrences'][1] = sf.seal_reviewed_assignment(changed, row)
        records, capability = self.verified(changed)
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.apply(records, capability)

    def test_audited_indices_and_physical_evidence_fail_closed_even_with_approved_new_digest(self):
        original = self.path.read_bytes()
        changes = (
            lambda a: a['summary']['excluded_as_indices'].append(1),
            lambda a: a['confirmed_exclusions'][0]['physical_id'].update(target_range=[4, 5]),
            lambda a: a['confirmed_exclusions'][0].update(actual_token='a'),
            lambda a: a['non_as_retained_candidate_indices'].append(1),
            lambda a: a['confirmed_exclusions'].pop(),
            lambda a: a['summary'].update(non_as_candidate_count_is_not_certified_article_total=False))
        for change in changes:
            self.path.write_bytes(original)
            pin = self.rewrite_audit(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.apply(expected_audit_sha256=pin)

    def test_inventory_snapshot_or_canonical_manifest_changes_are_rejected(self):
        inventory = Path(self.directory.name) / 'full-inventory-v2/records.jsonl'
        original = inventory.read_bytes()
        inventory.write_bytes(original + b'changed')  # outside locator changes do not alter audited row
        self.apply()
        inventory.write_bytes(b'changed' + original)
        with self.assertRaisesRegex(ValueError, 'inventory record changed'): self.apply()
        inventory.write_bytes(original)
        (Path(self.directory.name) / 'canonical.json').write_text('changed')
        with self.assertRaises(ValueError): self.apply()

    def test_stored_validator_is_not_live_authority_and_rejects_changed_ledger_or_record(self):
        filtered, scopes = self.apply()
        record, ledger = filtered[0], scopes.for_record(filtered[0]).verification()
        with self.assertRaisesRegex(ValueError, 'issued exclusion audit scope'):
            sr.plan_frequency_panel(self.page, record, {}, verified_sources=scopes.verified_sources)
        with self.assertRaisesRegex(ValueError, 'issued live'):
            sr.plan_frequency_panel(self.page, record, {}, verified_sources=scopes.verified_sources,
                                    candidate_scope=ledger)
        for kind in ('excluded', 'counts', 'map', 'seal'):
            changed, value = deepcopy(record), deepcopy(ledger)
            if kind == 'excluded': value['excluded'][0]['occurrence']['english'] += 'changed'
            if kind == 'counts': value['certified_article_total'] = 3
            if kind == 'map': value['retained_map'][0]['original_index'] = 1
            if kind == 'seal': changed['occurrences'][0]['assignment_context_hash'] = '0' * 64
            digest = value.pop('ledger_sha256')
            value['ledger_sha256'] = sr._sha(sr._json(value))
            with self.subTest(kind=kind), self.assertRaises(ValueError): cs.validate_stored_scope(changed, value)

    def test_original_inputs_replay_deterministically_but_filtered_inputs_cannot_be_filtered_twice(self):
        raw, capability = self.verified()
        first, first_scopes = self.apply(raw, capability)
        second, second_scopes = self.apply(raw, capability)
        self.assertEqual(first, second)
        self.assertEqual(first_scopes.verification(), second_scopes.verification())
        with self.assertRaises(ValueError): self.apply(first, first_scopes.verified_sources)

    def test_no_scope_card_retains_valid_derived_capability(self):
        records, capability = self.verified()
        other = deepcopy(records[0])
        other['card_id'] = 'other-card'
        page = self.page
        with patch.object(sd, '_load_sources', return_value=self.sources):
            values, verified = sr.reread_source_displays([self.record, other],
                {'article-card': page, 'other-card': page}, {})
        filtered, scopes = cs.apply_candidate_scope(values, {'article-card': page, 'other-card': page}, {},
            verified_sources=verified, audit_path=self.path, expected_audit_sha256=self.digest)
        self.assertIsNone(scopes.for_record(filtered[1]))
        self.assertEqual(filtered[1], values[1])
        scopes.verified_sources._require(page, filtered[1], {})

    def test_independent_2026_mapping_uses_own_indices_and_single_panel_is_reversible(self):
        record26, page26, digest, supplement, supplement_digest = supplement_fixture(
            self.directory.name, self.record, self.page, self.path)
        pages = {'article-card': self.page, 'independent-a': page26}
        with patch.object(sd, '_load_sources', return_value=self.sources):
            raw, capability = sr.reread_source_displays([self.record, record26], pages, {})
        with self.assertRaisesRegex(ValueError, '2026 a requires'):
            cs.apply_candidate_scope(raw, pages, {}, verified_sources=capability,
                audit_path=self.path, expected_audit_sha256=digest)
        filtered, scopes = cs.apply_candidate_scope(raw, pages, {}, verified_sources=capability,
            audit_path=self.path, expected_audit_sha256=digest, supplement_path=supplement,
            expected_supplement_sha256=supplement_digest)
        ledger = scopes.for_record(filtered[1]).verification()
        self.assertEqual([item['original_index'] for item in ledger['excluded']], [0, 2])
        self.assertEqual([item['audit_evidence']['mapped_primary_index'] for item in ledger['excluded']], [3, 1])
        self.assertEqual(filtered[1]['expected_occurrences'], 2)
        self.assertEqual([row['english'][slice(*row['target_range'])] for row in filtered[1]['occurrences']], ['A', 'a'])
        plan = sr.plan_frequency_panel(page26, filtered[1], {}, verified_sources=scopes.verified_sources,
            candidate_scope=scopes.for_record(filtered[1]))
        self.assertEqual(plan.verification()['component_panels'][0]['new_frequency']['occurrences'], 2)
        self.assertEqual(sr.restore_frequency_panel(sr.apply_frequency_panel(page26, plan), plan), page26)

    def test_2026_inexact_primary_physical_mapping_is_rejected(self):
        record26, page26, digest, supplement, supplement_digest = supplement_fixture(
            self.directory.name, self.record, self.page, self.path)
        value = json.loads(supplement.read_text())
        value['physical_evidence_map'][0]['global_index_2026'] = 1
        supplement_digest = _write(supplement, value)
        pages = {'article-card': self.page, 'independent-a': page26}
        with patch.object(sd, '_load_sources', return_value=self.sources):
            raw, capability = sr.reread_source_displays([self.record, record26], pages, {})
        with self.assertRaises(ValueError):
            cs.apply_candidate_scope(raw, pages, {}, verified_sources=capability,
                audit_path=self.path, expected_audit_sha256=digest, supplement_path=supplement,
                expected_supplement_sha256=supplement_digest)

    def test_persisted_2026_scope_cannot_reenter_ordinary_source_read_or_generic_panel_planner(self):
        record26, page26, digest, supplement, supplement_digest = supplement_fixture(
            self.directory.name, self.record, self.page, self.path)
        pages = {'article-card': self.page, 'independent-a': page26}
        with patch.object(sd, '_load_sources', return_value=self.sources):
            raw, capability = sr.reread_source_displays([record26], pages, {})
        filtered, scopes = cs.apply_candidate_scope(raw, pages, {}, verified_sources=capability,
            audit_path=self.path, expected_audit_sha256=digest, supplement_path=supplement,
            expected_supplement_sha256=supplement_digest)
        stored = {**filtered[0], 'candidate_scope': scopes.for_record(filtered[0]).verification()}
        # Legitimate storage consistency is independent of live source authority.
        self.assertEqual(sf.prepare_record(stored)['expected_occurrences'], 2)
        with patch.object(sd, '_load_sources', return_value=self.sources) as loader:
            with self.assertRaisesRegex(ValueError, 'persisted candidate scope.*original source replay'):
                sr.reread_source_displays([stored], pages, {})
            loader.assert_not_called()
        for marker in (stored['candidate_scope'], None, {}):
            marked = {**filtered[0], 'candidate_scope': marker}
            with self.subTest(marker=bool(marker)), self.assertRaisesRegex(
                    ValueError, 'persisted candidate scope.*original source replay'):
                sr.plan_frequency_panel(page26, marked, {}, verified_sources=scopes.verified_sources,
                                        candidate_scope=scopes.for_record(filtered[0]))
        # The approved original-source replay and live overlay still work.
        live = sr.plan_frequency_panel(page26, filtered[0], {}, verified_sources=scopes.verified_sources,
                                      candidate_scope=scopes.for_record(filtered[0]))
        self.assertEqual(live.verification()['component_panels'][0]['new_frequency']['occurrences'], 2)


if __name__ == '__main__':
    unittest.main()
