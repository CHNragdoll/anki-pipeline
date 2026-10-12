"""The full transfer explanation seal must survive storage and reject edits."""
import copy
import html
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from html.parser import HTMLParser

from anki_pipeline import sense_frequency as sf
from anki_pipeline.exam_usage_policy import producer_record
from anki_pipeline.ownership_history import bind_incoming_history
from tests.test_ownership_history import fixture


class SentenceParser(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.sentences, self.active, self.classes, self.articles = [], [], [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get('class', '').split()
        self.classes.extend(classes)
        if tag == 'article' and 'sf-example' in classes:
            sentence = {'text': '', 'classes': []}
            self.sentences.append(sentence)
            self.active.append(sentence)
            self.articles.append(sentence)
        elif tag == 'article':
            self.articles.append(None)
        for sentence in self.active:
            sentence['classes'].extend(classes)

    def handle_data(self, text):
        for sentence in self.active:
            sentence['text'] += text

    def handle_endtag(self, tag):
        if tag == 'article' and self.articles:
            sentence = self.articles.pop()
            if sentence is not None:
                self.active.remove(sentence)


class OwnershipHistoryPersistenceTests(unittest.TestCase):
    def prepared_record(self):
        target, transfer = fixture()
        transfer['source_history_ref'] = {'file': 'original-source.html', 'sha256': 'a' * 64}
        return producer_record(bind_incoming_history(target, [transfer]))

    def test_full_history_survives_prepare_and_database_roundtrip(self):
        value = self.prepared_record()
        expected = next(row['ownership_history'] for row in value['occurrences'] if row.get('ownership_history'))
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'history.sqlite3'
            sf.save_records(database, [value], Path(directory) / 'backups')
            report = sf.read_card(database, value['book_id'], value['card_id'])
        rows = [row for sense in report['senses'] for row in sense['occurrences']]
        histories = next(row['ownership_history'] for row in rows if row.get('ownership_history'))
        self.assertEqual(histories, expected)
        self.assertEqual(report['total'], 2)

    def test_prepare_rejects_changes_to_sealed_destination_and_full_history(self):
        value = self.prepared_record()
        edits = [lambda history: history.update(target_reason='改写后的解释'),
                 lambda history: history.update(target_word='another-word'),
                 lambda history: history['matched_sense'].update(text='另一个意思'),
                 lambda history: history['source_history_ref'].update(file='changed.html'),
                 lambda history: history['source_history_ref'].update(sha256='b' * 64)]
        for edit in edits:
            with self.subTest(edit=edit):
                changed = copy.deepcopy(value)
                history = next(row['ownership_history'][0] for row in changed['occurrences'] if row.get('ownership_history'))
                edit(history)
                with self.assertRaisesRegex(ValueError, 'ownership history content SHA'):
                    sf.prepare_record(changed)

    def test_transfer_explanation_is_inside_the_destination_sentence(self):
        prepared = sf.prepare_record(self.prepared_record())
        report = sf.report_from_record(prepared)
        rendered = SentenceParser(sf.render_report(report))
        sentence = next(row for row in rendered.sentences if 'sf-ownership-history' in row['classes'])
        self.assertIn('A novel idea for a novel.', sentence['text'])
        self.assertIn('完整旧错归解释', sentence['text'])
        self.assertIn('修饰 idea，表示新颖', sentence['text'])
        self.assertEqual(len(rendered.sentences), 2)
        self.assertEqual(report['total'], 2)

    def test_unbound_details_attach_to_the_existing_sentence_without_recount(self):
        target, transfer = fixture()
        report = sf.report_from_record(target)
        report['ownership_pending_diagnostics'] = [{'occurrence': transfer['source_parent_row'],
            'reason': '目标义项仍待确认；尚未转归', 'ownership': {'actual_binding': False}}]
        rendered = SentenceParser(sf.render_report(report))
        sentence = next(row for row in rendered.sentences if 'sf-ownership-pending-note' in row['classes'])
        self.assertIn('完整旧错归解释', sentence['text'])
        self.assertEqual(len(rendered.sentences), 2)
        self.assertNotIn('exam-usage-exclusions', rendered.classes)
        self.assertEqual(report['total'], 2)
        self.assertEqual(report['pending_count'], 0)

    def test_presentation_diagnostics_reject_changed_original_text(self):
        target, transfer = fixture()
        report = sf.report_from_record(target)
        original = copy.deepcopy(transfer['source_parent_row'])
        original['english'] += ' changed'
        report['ownership_pending_diagnostics'] = [{'occurrence': original,
            'reason': '待核', 'ownership': {}}]
        with self.assertRaisesRegex(ValueError, 'source English hash'):
            sf.render_report(report)

    def test_archived_unbound_sentence_remains_viewable_without_changing_counts(self):
        target, transfer = fixture()
        report = sf.report_from_record(target)
        original = copy.deepcopy(transfer['source_parent_row'])
        original['physical_source'] = ['paper', 'another-block']
        original['occurrence_id'] = sf._sha(sf._json([
            original['paper_id'], original['physical_source'], original['target_range']]))
        report['ownership_pending_diagnostics'] = [{'occurrence': original,
            'reason': '正确词条尚未确认；不计本词频', 'ownership': {}}]
        markup = sf.render_report(report)
        rendered = SentenceParser(markup)
        self.assertEqual(len(rendered.sentences), 3)
        self.assertIn('待核对例句（不计本词频）', markup)
        self.assertEqual(report['total'], 2)
        self.assertEqual(report['pending_count'], 0)

    def test_old_document_expands_within_the_destination_sentence_and_stays_pinned(self):
        target, transfer = fixture()
        raw = '<p>完整原界面说明</p>'
        document = '<pre>' + html.escape(raw) + '</pre>'
        reference = {'file': 'original-document.html', 'sha256': sf._sha(document), 'url': '/original-document.html'}
        transfer['source_history_ref'] = reference
        prepared = sf.prepare_record(producer_record(bind_incoming_history(target, [transfer])))
        report = sf.report_from_record(prepared)
        report['ownership_history_documents'] = {reference['file']: {'reference': reference,
            'document_html': document, 'original_html': raw, 'original_html_sha256': sf._sha(raw)}}
        rendered = SentenceParser(sf.render_report(report))
        sentence = next(row for row in rendered.sentences if 'sf-ownership-history' in row['classes'])
        self.assertIn('完整原界面说明', sentence['text'])
        self.assertEqual(len(rendered.sentences), 2)
        changed = copy.deepcopy(report)
        changed['ownership_history_documents'][reference['file']]['original_html'] = '<p>改写</p>'
        with self.assertRaisesRegex(ValueError, 'historical original diagnostic'):
            sf.render_report(changed)

    def test_year_filter_counts_only_current_sentences_with_nested_archives(self):
        target, transfer = fixture()
        raw = ('<article class="sf-example" data-sf-year="2001">第一条完整历史</article>'
               '<article class="sf-example" data-sf-year="2022">第二条完整历史</article>')
        document = '<pre>' + html.escape(raw) + '</pre>'
        reference = {'file': 'nested-history.html', 'sha256': sf._sha(document)}
        transfer['source_history_ref'] = reference
        report = sf.report_from_record(sf.prepare_record(producer_record(bind_incoming_history(target, [transfer]))))
        report['ownership_history_documents'] = {reference['file']: {'reference': reference,
            'document_html': document, 'original_html': raw, 'original_html_sha256': sf._sha(raw)}}
        markup = sf.render_report(report)
        parsed = SentenceParser(markup)
        self.assertEqual(len(parsed.sentences), 2)
        destination = next(row for row in parsed.sentences if 'sf-ownership-history' in row['classes'])
        self.assertIn('第一条完整历史', destination['text'])
        self.assertIn('第二条完整历史', destination['text'])
        javascript = r"""
const assert=require('node:assert/strict'),{JSDOM}=require('jsdom'),fs=require('node:fs');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const dom=new JSDOM(input.html,{runScripts:'outside-only'}),w=dom.window,d=w.document;
w.eval(input.script);
assert.equal(d.querySelectorAll('.sf-example').length,2);
assert.equal(d.querySelectorAll('.sf-archived-example').length,2);
for(const panel of d.querySelectorAll('.sf-panel')) {
  const examples=[...panel.querySelectorAll('.sf-example')];
  for(const filter of panel.querySelectorAll('[data-sf-filter]')) {
    filter.click();
    const year=filter.dataset.sfFilter;
    const expected=examples.filter(e=>year==='all'||e.dataset.sfYear===year).length;
    assert.equal(panel.querySelector('.sf-preview-count').textContent,'显示 '+expected+' 处原文');
    assert.equal(examples.filter(e=>!e.hidden).length,expected);
  }
}
assert.equal(d.querySelectorAll('.sf-archived-example[hidden]').length,0);
"""
        result = subprocess.run(['node', '-e', javascript], input=json.dumps({'html': markup,
            'script': (Path(sf.__file__).parent / 'templates/sense-frequency.js').read_text()}),
            text=True, capture_output=True, cwd=Path(sf.__file__).parent.parent, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
