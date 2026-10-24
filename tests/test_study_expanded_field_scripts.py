"""Carrier preparation only: no PG, GUI, full producer or generated source edits."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from anki_pipeline import study_expanded_field_scripts as expanded
from anki_pipeline import study_field_scripts as fields
from anki_pipeline.study_catalog_web_materialize import ReadOnlyMedia, materialize_side


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = '<script class="as-manifest" type="application/json">{}</script>'


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def restore_html(html):
    code = r'''
const fs=require('fs'),u=require('util'),{JSDOM}=require('jsdom');
const p=JSON.parse(fs.readFileSync(0,'utf8'));
const d=new JSDOM(p.html,{runScripts:'outside-only'}),w=d.window;
w.TextEncoder=u.TextEncoder;w.TextDecoder=u.TextDecoder;w.eval(p.runtime);
const before=w.document.body.textContent;let result;
try {
 const first=w.StudyFieldScriptTransport.restore(w.document);
 const repeat=w.StudyFieldScriptTransport.restore(w.document);
 const textUnchanged=before===w.document.body.textContent;
 w.document.querySelector('script.anki-final-reviewed-data,script.as-manifest').textContent='tampered';
 let rejected=false;try{w.StudyFieldScriptTransport.restore(w.document)}catch(e){rejected=true}
 const edited=new JSDOM(p.html,{runScripts:'outside-only'}),v=edited.window;
 for(const n of v.document.querySelectorAll('script.anki-final-reviewed-data,script.as-manifest'))n.remove();
 v.TextEncoder=u.TextEncoder;v.TextDecoder=u.TextDecoder;v.eval(p.runtime);
 const deleted=v.StudyFieldScriptTransport.restore(v.document);
 const restoredText=before===v.document.body.textContent;v.close();
 result={first,repeat,deleted,textUnchanged,restoredText,tamperRejected:rejected};
}catch(e){result={error:e.message}}
w.close();console.log(JSON.stringify(result));
'''
    result = subprocess.run(['node', '-e', code], cwd=ROOT,
        input=json.dumps({'html': html, 'runtime': fields.RUNTIME_PATH.read_text()}),
        text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class ExpandedFieldScriptTests(unittest.TestCase):
    def fixture(self, root):
        def register(text):
            pin = sha(text)
            name = '_as_' + pin[:24] + '.js'
            (root / name).write_text('window.AnkiSlimAssets=window.AnkiSlimAssets||{};'
                'window.AnkiSlimAssets[' + json.dumps(pin) + ']=' + json.dumps(text, ensure_ascii=False) + ';')
            return {'src': name, 'sha256': pin}

        def slot(part, tag, kind):
            manifest = json.dumps({'schema': 'anki-slim-segments.v1',
                'parts': [{**part, 'count': 1}], 'total': 1}, separators=(',', ':'))
            return ('<' + tag + ' class="as-lazy" data-as-kind="' + kind + '">'
                    '<script class="as-manifest" type="application/json">' + manifest
                    + '</script></' + tag + '>')

        history = register('<p>完整审核原文 😀</p>')
        detail = '<details class="sf-ownership-history"><summary>原审核</summary>' + slot(history, 'div', 'detail') + '</details>'
        part = register('<li class="example-card">原句、译文' + detail + '</li>')
        reviewed = fields.protect_field('<script class="anki-final-reviewed-data" type="application/json">{}</script>')
        source = '<body><div>' + reviewed + '</div><ol class="examples">' + fields.protect_field(slot(part, 'li', 'examples')) + '</ol></body>'
        return source, materialize_side(source, ReadOnlyMedia(root)), part

    def test_authenticated_nested_expansion_restores_and_repeats_without_text_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, side, part = self.fixture(root)
            # The old base materializer faithfully expands the authenticated
            # part but introduces its unprotected nested transport: actual RED.
            self.assertIn('unpaired/moved', restore_html(side['html'])['error'])
            result = expanded.normalize_side(source, side, ReadOnlyMedia(root), context='back')
            self.assertTrue(result['evidence']['changed'])
            self.assertEqual(result['evidence']['added_carriers'], 1)
            self.assertEqual(result['evidence']['verified_carriers'], 1)
            self.assertEqual(result['evidence']['authenticated_fragments'], [
                {**part, 'bytes': len(ReadOnlyMedia(root).read(part).encode())}])
            actual = restore_html(result['html'])
            self.assertEqual(actual['first'], {'restored': 0, 'verified': 2})
            self.assertEqual(actual['repeat'], actual['first'])
            self.assertEqual(actual['deleted'], {'restored': 2, 'verified': 2})
            self.assertTrue(actual['textUnchanged'] and actual['restoredText'] and actual['tamperRejected'])

    def test_existing_carriers_are_validated_and_unchanged(self):
        protected = fields.protect_field('<div>' + MANIFEST + '</div>')
        result = expanded.protect_authenticated_fragment(protected,
            expected_sha256=sha(protected), context='existing')
        self.assertIs(result['html'], protected)
        self.assertEqual(result['proof']['added_carriers'], 0)
        self.assertEqual(result['proof']['verified_carriers'], 1)
        mixed = protected + '<div>' + MANIFEST + '</div>'
        first = expanded.protect_authenticated_fragment(mixed, expected_sha256=sha(mixed), context='mixed')
        self.assertTrue(first['html'].startswith(protected))
        second = expanded.protect_authenticated_fragment(first['html'],
            expected_sha256=sha(first['html']), context='mixed')
        self.assertEqual(second['html'], first['html'])
        self.assertEqual(second['proof']['added_carriers'], 0)
        # The original source-field parser remains strict, not an editor repair.
        with self.assertRaisesRegex(ValueError, 'reserved'):
            fields.protect_field(protected)

    def test_wrong_sha_tamper_moved_duplicate_and_nonempty_carriers_are_rejected(self):
        protected = fields.protect_field('<div>' + MANIFEST + '</div>')
        malformed = [protected.replace('>{}</script>', '>changed</script>'),
            protected.replace('display:none!important', 'display:block'),
            protected.replace('</span>', 'pollution</span>'),
            protected.replace('</script><span', '</script> <span'),
            protected + protected,
            protected.replace('data-study-script-sha256="', 'data-study-script-sha256="BAD')]
        for raw in malformed:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                expanded.protect_authenticated_fragment(raw, expected_sha256=sha(raw), context='bad')
        with self.assertRaisesRegex(ValueError, 'external SHA'):
            expanded.protect_authenticated_fragment(protected, expected_sha256='0' * 64, context='bad')

    def test_changed_prepared_or_corrupt_authenticated_media_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, side, part = self.fixture(root)
            altered = copy.deepcopy(side)
            altered['html'] = altered['html'].replace('原句、译文', '外改正文')
            altered['proof']['expanded_sha256'] = sha(altered['html'])
            with self.assertRaisesRegex(ValueError, 'base materialization'):
                expanded.normalize_side(source, altered, ReadOnlyMedia(root))
            asset = root / part['src']
            asset.write_text(asset.read_text().replace('原句', '篡改'))
            with self.assertRaisesRegex(ValueError, 'SHA'):
                expanded.normalize_side(source, side, ReadOnlyMedia(root))

    def test_noop_legacy_source_and_already_paired_side_keep_original_strings(self):
        old = '<body><div>' + MANIFEST + '</div></body>'
        side = {'html': old}
        result = expanded.normalize_side(old, side, None)
        self.assertIs(result['html'], old)
        self.assertFalse(result['evidence']['changed'])
        source = '<body>' + fields.protect_field('<div>' + MANIFEST + '</div>') + '</body>'
        with tempfile.TemporaryDirectory() as temporary:
            side = materialize_side(source, ReadOnlyMedia(Path(temporary)))
            result = expanded.normalize_side(source, side, None)
            self.assertIs(result['html'], side['html'])
            self.assertFalse(result['evidence']['changed'])

    def test_existing_source_lost_carrier_is_not_laundered_as_new_fragment(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, side, _ = self.fixture(Path(temporary))
            source = source.replace('<body><div>', '<body><div>' + MANIFEST)
            with self.assertRaisesRegex(ValueError, 'original source.*unpaired'):
                expanded.normalize_side(source, side, None)

    def test_repeated_authenticated_asset_uses_explicit_distinct_contexts(self):
        raw = '<div>' + MANIFEST + '</div>'
        a = expanded.protect_authenticated_fragment(raw, expected_sha256=sha(raw), context='insertion:1')
        b = expanded.protect_authenticated_fragment(raw, expected_sha256=sha(raw), context='insertion:2')
        self.assertNotEqual(a['html'], b['html'])
        self.assertEqual(restore_html(a['html'] + b['html'])['first']['verified'], 2)

    def test_unknown_script_stays_exact_and_new_executable_bridge_or_bad_grammar_rejected(self):
        raw = '<div><script>window.originalOnly=true;</script></div>'
        self.assertEqual(expanded.protect_authenticated_fragment(raw,
            expected_sha256=sha(raw), context='unchanged')['html'], raw)
        for raw in ('<table>' + MANIFEST + '</table>',
                    '<div><script data-cigen-frame-bridge="v1">unknown()</script></div>'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                expanded.protect_authenticated_fragment(raw, expected_sha256=sha(raw), context='bad')


if __name__ == '__main__':
    unittest.main()
