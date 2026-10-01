"""Reject unaudited root documents and frame capabilities before any Anki import."""
from __future__ import annotations
import base64
import copy
import hashlib
import html
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
SPEC = importlib.util.spec_from_file_location('etymology_import_verifier', ROOT / 'scripts/verify_etymology_import.py')
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


def document():
    png = b'original-archive-png-bytes'
    image = 'data:image/png;base64,' + base64.b64encode(png).decode() + '#grey-open.png'
    styles = ['entry-page-css', 'original-resource-css', 'scoped-card-layout-css']
    scripts = ['offlineAssetBridge()', 'originalEntryViewer()', 'opaqueSizeBridge()']
    value = ('<!doctype html><html><head>' + ''.join('<style>' + content + '</style>' for content in styles)
             + '</head><body><div class="etymology"><p>exact source &amp; text</p><img src="' + image
             + '"><a href="eudic://x-callback-url/searchword?word=rate" target="_top">rate</a></div>'
             + ''.join('<script>' + content + '</script>' for content in scripts) + '</body></html>')
    audit = dict(zip(('entry_page_css_sha256', 'original_resource_css_text_sha256', 'card_layout_css_sha256'),
                     map(verification.digest_text, styles)))
    audit.update(dict(zip(('asset_bridge_script_sha256', 'original_viewer_js_sha256', 'resize_script_sha256'),
                          map(verification.digest_text, scripts))))
    audit['original_resources_sha256'] = {'grey-open.png': hashlib.sha256(png).hexdigest()}
    record = {'headword': 'rate', 'original_viewer_document_sha256': verification.digest_text(value),
              'source_items': {'img': 1}}
    return value, record, audit


def markup(content):
    return ('<section class="etymology-section" aria-label="词根词缀与词源" data-schema="cigen-etymology.v1" '
            'data-source="cigen" data-renderer="cigen-original-viewer.v1" style="' + verification.ROOT_STYLE + '">'
            '<div class="etymology-entry" data-entry-id="12" data-headword="rate" data-html-sha256="' + 'a' * 64 + '">'
            '<iframe class="etymology-source-frame" title="rate 原词根资源" sandbox="' + verification.FRAME_SANDBOX
            + '" scrolling="no" style="' + verification.FRAME_STYLE + '" srcdoc="' + html.escape(content, quote=True)
            + '"></iframe></div><script data-cigen-frame-bridge="v1">auditedParentBridge()</script></section>')


def native_fixture():
    content, record, audit = document()
    content = content.replace('exact source &amp; text', 'exact source 了 論 冷 料 cafe\u0301 ① &amp; text')
    content = content.replace('entry-page-css', 'entry-page-css\r\n')
    original = content.replace('\r\n', '\n')
    record.update(entry_id=12, source_html_sha256='a' * 64,
                  original_viewer_document_sha256=verification.digest_text(original))
    audit['entry_page_css_sha256'] = verification.digest_text('entry-page-css\n')
    changes = tuple((original.index(source), source, target)
                    for source, target in (('了', '了'), ('論', '論'), ('冷', '冷'), ('料', '料')))
    approved = {key: record[key] for key in ('headword', 'source_html_sha256', 'original_viewer_document_sha256')}
    approved['changes'] = changes
    return content, record, audit, approved


class OriginalRootVerifierTests(unittest.TestCase):
    def test_native_import_accepts_only_source_bound_four_characters(self):
        content, record, audit, approved = native_fixture()
        with patch.dict(verification.NATIVE_SOURCE_CHARACTER_CONVERSIONS, {12: approved}, clear=True):
            converted, changes = verification.native_source_document(content, record)
            self.assertEqual(len(changes), 4)
            self.assertEqual([item['source_occurrences'] for item in changes], [1] * 4)
            verification.verify_original_document(converted, record, audit, native_original=content)
            with self.assertRaises(RuntimeError):
                verification.verify_original_document(converted, record, audit)
            fields = ['original'] * len(verification.FIELD_NAMES)
            index = verification.FIELD_NAMES.index('Definition')
            fields[index] = 'Oxford 了\r\n' + markup(content)
            actual = fields.copy()
            actual[index] = 'Oxford 了\n' + markup(converted)
            self.assertTrue(verification.verify_imported_fields(actual, fields, 'rate', [record]))
            with self.assertRaises(RuntimeError):
                verification.verify_imported_fields(actual, fields, 'rate')
            for value in (actual[index].replace('Oxford 了', 'Oxford 了'),
                          actual[index].replace('cafe\u0301', 'café'),
                          actual[index].replace('①', '1'),
                          actual[index].replace('originalEntryViewer()', 'differentViewer()')):
                tampered = actual.copy(); tampered[index] = value
                with self.subTest(value=value[:80]), self.assertRaises(RuntimeError):
                    verification.verify_imported_fields(tampered, fields, 'rate', [record])

    def test_native_four_character_rules_bind_identity_hash_positions_and_counts(self):
        content, record, _, approved = native_fixture()
        with patch.dict(verification.NATIVE_SOURCE_CHARACTER_CONVERSIONS, {12: approved}, clear=True):
            for key, value in (('headword', 'different'), ('source_html_sha256', 'b' * 64),
                               ('original_viewer_document_sha256', 'c' * 64)):
                forged = record.copy(); forged[key] = value
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    verification.native_source_document(content, forged)
            for invalid_content in (content.replace('了', '了了'), content.replace('exact source', 'changed source')):
                with self.subTest(content=invalid_content[:80]), self.assertRaises(RuntimeError):
                    verification.native_source_document(invalid_content, record)
            converted, _ = verification.native_source_document(content, record)
            wrong_entry = record.copy(); wrong_entry['entry_id'] = 13
            with self.assertRaises(RuntimeError):
                verification.verify_original_document(converted, wrong_entry, {}, native_original=content)
        bad_position = approved.copy()
        bad_position['changes'] = ((approved['changes'][0][0] + 1, '了', '了'),) + approved['changes'][1:]
        with patch.dict(verification.NATIVE_SOURCE_CHARACTER_CONVERSIONS, {12: bad_position}, clear=True):
            with self.assertRaises(RuntimeError):
                verification.native_source_document(content, record)
        duplicated = content.replace('了', '了了')
        duplicate_record = record.copy()
        duplicate_record['original_viewer_document_sha256'] = verification.digest_text(duplicated.replace('\r\n', '\n'))
        duplicate_rule = approved.copy()
        duplicate_rule['original_viewer_document_sha256'] = duplicate_record['original_viewer_document_sha256']
        with patch.dict(verification.NATIVE_SOURCE_CHARACTER_CONVERSIONS, {12: duplicate_rule}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'position/count'):
                verification.native_source_document(duplicated, duplicate_record)

    def test_native_import_allows_only_definition_crlf_to_lf(self):
        self.assertEqual(verification.normalized_document('one\rtwo\r\nthree'), 'one\rtwo\nthree')
        fields = ['original'] * len(verification.FIELD_NAMES)
        self.assertFalse(verification.verify_imported_fields(fields, fields, 'rigid'))
        fields[verification.FIELD_NAMES.index('Definition')] = 'exact source CSS\r\nnext line'
        actual = fields.copy()
        actual[verification.FIELD_NAMES.index('Definition')] = 'exact source CSS\nnext line'
        self.assertTrue(verification.verify_imported_fields(actual, fields, 'rigid'))

    def test_native_import_rejects_other_field_newlines_or_definition_changes(self):
        fields = ['original'] * len(verification.FIELD_NAMES)
        index = verification.FIELD_NAMES.index('Definition')
        fields[index] = 'original\r\nsource\rcafe\u0301'
        for changed_index, changed_value in (
            (index, 'original\nsource\ncafe\u0301'),
            (index, 'original\nsource\rcafé'),
            (index, 'original \nsource\rcafe\u0301'),
            (index, 'changed\nsource\rcafe\u0301'),
            (0, 'original\n'),
        ):
            actual = fields.copy()
            actual[changed_index] = changed_value
            with self.subTest(index=changed_index, value=changed_value):
                with self.assertRaises(RuntimeError):
                    verification.verify_imported_fields(actual, fields, 'rigid')
        fields[0] = 'original\r\nword'
        actual = fields.copy(); actual[0] = 'original\nword'
        with self.assertRaises(RuntimeError):
            verification.verify_imported_fields(actual, fields, 'rigid')

    def test_web_definition_preserves_literal_srcdoc_crlf(self):
        definition = '<iframe srcdoc="&lt;style&gt;one{color:red}\r\ntwo{color:blue}\r\n&lt;/style&gt;"></iframe>'
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / 'card.html'
            page.write_bytes(('<html><body>' + definition + '</body></html>').encode('utf-8'))
            self.assertNotIn(definition, page.read_text(encoding='utf-8'))
            verification.verify_web_definition(definition, page, 'ambition')

    def test_web_definition_still_rejects_newline_or_content_changes(self):
        definition = '<iframe srcdoc="exact original\r\nsource &amp; text"></iframe>'
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / 'card.html'
            for changed in (definition.replace('\r\n', '\n'), definition.replace('original', 'changed')):
                with self.subTest(changed=changed):
                    page.write_bytes(('<html><body>' + changed + '</body></html>').encode('utf-8'))
                    with self.assertRaisesRegex(RuntimeError, 'web/package definition differs: ambition'):
                        verification.verify_web_definition(definition, page, 'ambition')

    def test_exact_original_document_and_outer_frame_are_accepted(self):
        content, record, audit = document()
        verification.verify_original_document(content, record, audit)
        parsed = verification.Components(markup(content))
        self.assertEqual(parsed.entries[0]['id'], '12')
        self.assertEqual(parsed.frames[0]['srcdoc'], content)
        self.assertEqual(parsed.parent_scripts, ['auditedParentBridge()'])
        self.assertEqual(len(parsed.roots), 1)

    def test_frame_cannot_add_parent_origin_access_url_event_or_fixed_height(self):
        content, _, _ = document()
        original = markup(content)
        for changed in (
            original.replace('allow-scripts ', 'allow-scripts allow-same-origin '),
            original.replace('scrolling="no"', 'scrolling="yes"'),
            original.replace('height:1px;', 'height:300px;'),
            original.replace('<iframe ', '<iframe src="http://example.invalid/" '),
            original.replace('<iframe ', '<iframe onload="evil()" '),
            original.replace('<div class="etymology-entry"', '<object class="etymology-entry"'),
        ):
            with self.subTest(changed=changed[:120]):
                with self.assertRaises(RuntimeError):
                    verification.Components(changed)

    def test_source_text_tampering_fails_complete_document_hash(self):
        content, record, audit = document()
        with self.assertRaisesRegex(RuntimeError, 'srcdoc differs'):
            verification.verify_original_document(content.replace('exact source', 'replaced source'), record, audit)

    def test_rebinding_document_hash_does_not_approve_different_styles_scripts_or_assets(self):
        content, record, audit = document()
        for changed in (
            content.replace('original-resource-css', 'unapproved-resource-css'),
            content.replace('originalEntryViewer()', 'fetch("/api/entry")'),
            content.replace(base64.b64encode(b'original-archive-png-bytes').decode(), base64.b64encode(b'other-png').decode()),
            content.replace('target="_top"', 'target="_blank"'),
            content.replace('<p>', '<p onclick="evil()">'),
            content.replace('<script>originalEntryViewer()', '<script src="/viewer.js">originalEntryViewer()'),
        ):
            forged = copy.deepcopy(record)
            forged['original_viewer_document_sha256'] = verification.digest_text(changed)
            with self.subTest(changed=changed[:120]):
                with self.assertRaises(RuntimeError):
                    verification.verify_original_document(changed, forged, audit)

    def test_original_css_is_unchanged_and_only_two_exact_outer_rules_are_added(self):
        original = '.card{font:inherit}\n'
        addition = ('/* Only the isolated source frame host. */\n.etymology-section{' + verification.ROOT_STYLE + '}'
                    '.etymology-source-frame{' + verification.FRAME_STYLE.replace('height:1px;', '') + '}')
        verification.verify_etymology_css_delta(original, original + addition)
        for changed in (
            (original + addition).replace('.card{font:inherit}', '.card{font-size:30px}'),
            (original + addition).replace('.etymology-source-frame', 'body'),
            original + addition + '.etymology-source-frame{height:300px}',
            (original + addition).replace('overflow:hidden;', 'overflow:auto;'),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(RuntimeError):
                    verification.verify_etymology_css_delta(original, changed)


if __name__ == '__main__':
    unittest.main()
