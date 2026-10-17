"""A completed semantic snapshot can shed only proven closed AF copies."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.study_compiled_history_compact import compact_html, compact_semantic_result


def pin(text):
    return hashlib.sha256(text.encode()).hexdigest()


def fixture(*, owner='', text='original & <audit>\n完整证据'):
    from html import escape
    full_pin = pin(text)
    attrs = [['data-native-history-media', '_af_' + 'a' * 24 + '.js'],
             ['data-native-history-sha', full_pin]]
    start = '<pre' + ''.join(' ' + k + '="' + v + '"' for k, v in attrs)
    original = start + '>展开后载入完整原 HTML 证据</pre>'
    prepared = start + ' data-native-history-ready="true">' + escape(text, quote=False) + '</pre>'
    proof = {'ordinal': 0, 'media': attrs[0][1], 'sha256': full_pin,
             'resource_sha256': 'b' * 64, 'original_text': '展开后载入完整原 HTML 证据',
             'original_attributes': attrs, 'original_pre_dom_sha256': pin(original),
             'prepared_pre_dom_sha256': pin(prepared),
             'original_text_sha256': pin('展开后载入完整原 HTML 证据'),
             'complete_text_sha256': full_pin, 'inverse_exact': True}
    return '<!DOCTYPE html><html><body><details' + owner + '><summary>审核</summary>' + prepared + '</details></body></html>', proof, original, prepared


class HistoryCompactionTests(unittest.TestCase):
    def test_duplicate_copies_restore_placeholders_and_global_inverse(self):
        source, proof, original, prepared = fixture()
        source = source.replace('<body>', '<body>前😀')
        source = source.replace('</details>', prepared + '</details>')
        second = dict(proof, ordinal=1)
        result = compact_html(source, [proof, second])
        self.assertEqual(result['html'], source.replace(prepared, original))
        self.assertEqual(result['inverse_sha256'], pin(source))
        self.assertEqual(result['source_sha256'], pin(source))
        self.assertEqual(len(result['edits']), 2)
        raw_source = source.encode()
        for edit in result['edits']:
            self.assertEqual(hashlib.sha256(raw_source[edit['start_byte']:edit['end_byte']]).hexdigest(), edit['before_sha256'])
            self.assertEqual(edit['start_byte'], len(source[:edit['start']].encode()))
            self.assertEqual(edit['after_bytes'], len(original.encode()))
        self.assertEqual([p['preparation'] for p in result['initial_proof']], ['deferred-closed'] * 2)
        self.assertTrue(all(p['complete_text_sha256'] == proof['sha256'] for p in result['initial_proof']))

    def test_open_classed_and_originally_ready_evidence_remain_complete(self):
        for owner in [' open=""', ' class="sf-source-confirmation-history"']:
            source, proof, _, _ = fixture(owner=owner)
            result = compact_html(source, [proof])
            self.assertEqual(result['html'], source)
            self.assertEqual(result['edits'], [])

    def test_tampered_copy_or_missing_proof_is_rejected_before_result(self):
        source, proof, _, _ = fixture()
        with self.assertRaisesRegex(ValueError, 'prepared|text'):
            compact_html(source.replace('original &amp;', 'changed &amp;'), [proof])
        with self.assertRaisesRegex(ValueError, 'census'):
            compact_html(source, [])
        with self.assertRaisesRegex(ValueError, 'original'):
            compact_html(source, [dict(proof, original_text='different')])

    def test_script_comment_template_pretend_pre_is_not_a_source_position(self):
        source, proof, original, prepared = fixture(text='original & <audit>')
        source = source.replace('<body>', '<body><script>const x=' + repr(prepared) + ';</script><!--' + prepared + '--><template>' + prepared + '</template>')
        result = compact_html(source, [proof])
        self.assertEqual(result['html'].count(original), 1)
        self.assertEqual(result['html'].count(prepared), 3)
        self.assertEqual(len(result['edits']), 1)

    def test_new_report_preserves_parent_and_labels_semantic_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, item, original, _ = fixture()
            def store(name, value):
                raw = value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()
                path = root / name
                path.write_bytes(raw)
                return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            request = store('request.json', {'schema': 'study-compiled-semantic-request.v1', 'artifact': {'sha256': 'c' * 64}})
            absolute_request = {**request, 'path': str(root / request['path'])}
            proof = {'request_sha256': request['sha256'], 'artifact_sha256': 'c' * 64, 'initial_history_evidence': [item]}
            report = {'schema': 'study-compiled-semantic-result.v1', 'real_native_ready': True,
                      'pure_semantic_only': True, 'authored_startup_executed': False,
                      'final_html': store('body.html', source), 'source_proof': store('source.json', proof),
                      'bindings': store('bindings.json', {'unmodified': '原始绑定'}),
                      'reconciliation': store('reconciliation.json', {'count': 3}),
                      'capture_inverse': store('inverse.json', {'exact': True}),
                      'metadata': store('metadata.json', {'original': '原释义'})}
            parent = store('report.json', report)
            before = {path.name: path.read_bytes() for path in root.iterdir()}
            derived = compact_semantic_result(absolute_request, {**parent, 'path': str(root / 'report.json')}, root / 'derived')
            result = json.loads(Path(derived['path']).read_bytes())
            out = root / 'derived'
            self.assertEqual((out / 'body.html').read_text(), source.replace(source[source.index('<pre'):source.index('</pre>') + 6], original))
            for name in ('bindings', 'capture_inverse', 'metadata'):
                self.assertEqual((out / result[name]['path']).read_bytes(), before[result[name]['path']])
            receipt = json.loads((out / result['initial_history_compaction']['path']).read_bytes())
            self.assertIs(receipt['semantic_preparation_rerun'], False)
            self.assertEqual(receipt['source_html_sha256'], receipt['inverse_html_sha256'])
            self.assertEqual(hashlib.sha256((out / 'compaction-helper.py').read_bytes()).hexdigest(), receipt['helper_sha256'])
            for name, raw in before.items():
                self.assertEqual((root / name).read_bytes(), raw)
            (root / report['final_html']['path']).write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'pin/size'):
                compact_semantic_result(absolute_request, {**parent, 'path': str(root / 'report.json')}, root / 'rejected')
            self.assertFalse((root / 'rejected').exists())


if __name__ == '__main__':
    unittest.main()
