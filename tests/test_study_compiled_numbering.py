"""Tiny DOM-only original ordinal preparation; no authored startup or real cards."""
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
FIXTURE = r"""
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const {JSDOM} = require('jsdom');
const api = require('./anki_pipeline/compiled/numbering-preparation.cjs');
const legacy = JSON.parse(fs.readFileSync('./anki_pipeline/templates/example-numbering-legacy.json', 'utf8'));
const sha = text => crypto.createHash('sha256').update(text).digest('hex');
function fixture(body, css = '') {
  const dom = new JSDOM('<!doctype html><html><head>' + (css ? '<style>' + css + '</style>' : '') + '</head><body>' + body + '</body></html>',
    {url: 'https://study.test/cards/card.html', runScripts: 'outside-only', pretendToBeVisual: true});
  const doc = dom.window.document;
  const options = {sourceCode: legacy.source, sourcePin: legacy.sha256,
    styleSources: [...doc.querySelectorAll('style')].map(node => ({node, sourceNode: node,
      sourceText: node.textContent, sha256: sha(node.textContent), kind: 'inline'}))};
  return {dom, doc, options, prepare() { return api.prepareInitialNumbering(doc, options); }};
}
const row = (n, attrs = '', content = '') => '<li class="example-card" ' + attrs + '><span class="index-tag">' + n + '</span>' + content + '</li>';
const list = text => '<ol class="examples">' + text + '</ol>';
function external(f, css) {
  const link = f.doc.createElement('link'); link.rel = 'stylesheet';
  link.href = '../media/_study_' + sha(css) + '.css'; f.doc.head.append(link);
  const node = f.doc.createElement('style'); node.textContent = css; link.after(node);
  f.options.styleSources.push({node, sourceNode: link, sourceText: css, sha256: sha(css), kind: 'external'});
  return {link, node};
}
function unchangedReject(f, pattern) {
  const before = f.doc.documentElement.outerHTML;
  assert.throws(() => f.prepare(), pattern);
  assert.equal(f.doc.documentElement.outerHTML, before, 'rejection must happen before any ordinal write');
}
"""


@unittest.skipUnless(NODE, 'Node.js is unavailable')
class CompiledNumberingTests(unittest.TestCase):
    def run_js(self, program):
        result = subprocess.run([NODE, '-e', FIXTURE + program], cwd=ROOT,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_source_52_becomes_34_without_changing_ids_counts_or_text_identity(self):
        self.run_js(r"""
const f = fixture(list(Array.from({length:52}, (_, i) => row(i+1,
  (i < 18 ? 'hidden ' : '') + 'id="source-' + i + '" data-count="3" data-study-compiled-key="node-' + i + '"')).join('')));
const before = f.doc.documentElement.outerHTML, badge = f.doc.querySelector('#source-51 .index-tag'), text = badge.firstChild;
assert.equal(text.data, '52');
f.dom.window.MutationObserver = function () { throw Error('No author observer'); };
f.dom.window.setTimeout = () => { throw Error('No author timer'); };
const proof = f.prepare();
assert.equal(badge.textContent, '34'); assert.equal(badge.firstChild, text);
assert.equal(proof.numberingSha256, legacy.sha256); assert.equal(proof.stats.eligibleRows, 34);
assert.equal(proof.edits.at(-1).decodedBefore, '52'); assert.equal(proof.edits.at(-1).after, '34');
assert.equal(proof.edits.at(-1).rowKey, 'node-51');
assert.equal(f.doc.querySelectorAll('[data-count="3"]').length, 52);
assert.equal(sha(proof.edits.at(-1).decodedBefore), proof.edits.at(-1).beforeSha256);
assert.equal(api.inverse(f.doc, proof), proof); assert.equal(f.doc.documentElement.outerHTML, before);
""")

    def test_original_first_badge_counting_history_nested_and_template_rules(self):
        self.run_js(r"""
const f = fixture(list(row('9') + '<div>not row</div><li class="example-card">missing</li>' + row('not numeric') +
  '<li class="example-card"><div class="sf-pending"><span class="index-tag">81</span></div><span class="index-tag">82</span></li>' +
  row('55', '', list(row('77'))) + row('66', 'hidden') + row('88', 'data-native-ownership-history') + row('99')) +
  '<div class="sf-final-history">' + list(row('101')) + '</div><template>' + list(row('102')) + '</template>' + list(row('\u00a0 7 ')));
const proof = f.prepare();
assert.deepEqual([...f.doc.querySelectorAll('.index-tag')].map(x=>x.textContent), ['1','not numeric','81','82','5','1','66','88','6','101','1']);
assert.equal(f.doc.querySelector('template').content.querySelector('.index-tag').textContent, '102');
assert.equal(proof.stats.missingBadges, 1); assert.equal(proof.stats.invalidBadges, 1);
assert.equal(proof.stats.foreignOrHistoryFirstBadges, 1); assert.equal(proof.stats.excludedLists, 1);
""")

    def test_nested_first_badge_is_not_replaced_by_later_badge(self):
        self.run_js(r"""
const f = fixture(list('<li class="example-card">' + list(row('77')) + '<span class="index-tag">88</span></li>' + row('99')));
const proof = f.prepare();
assert.deepEqual([...f.doc.querySelectorAll('.index-tag')].map(x=>x.textContent), ['1','88','2']);
assert.equal(proof.stats.foreignOrHistoryFirstBadges, 1);
""")

    def test_single_original_text_slot_is_required_before_any_write(self):
        self.run_js(r"""
for (const contents of ['<b>9</b>', '9<!--comment-->', '']) {
  const f = fixture(list(row('7') + '<li class="example-card"><span class="index-tag">' + contents + '</span></li>'));
  if (!contents) { f.doc.querySelectorAll('.index-tag')[1].append(f.doc.createTextNode('9'), f.doc.createTextNode('0')); }
  unchangedReject(f, /one original Text/);
}
""")

    def test_numbering_source_and_style_descriptors_are_authenticated(self):
        self.run_js(r"""
for (const mutate of [f=>f.options.sourceCode+=' ', f=>f.options.sourcePin='0'.repeat(64),
 f=>f.options.styleSources[0].sourceText+=' ', f=>f.options.styleSources[0].sha256='0'.repeat(64),
 f=>f.options.styleSources=[], f=>f.doc.head.append(f.doc.createElement('style')),
 f=>f.options.styleSources.push(f.options.styleSources[0])]) {
 const f=fixture(list(row('8')), '.off{display:none}'); mutate(f); unchangedReject(f, /numbering|style/i);
}
""")

    def test_cssom_edits_cannot_keep_an_old_authenticated_style_text(self):
        self.run_js(r"""
const f=fixture(list(row('8')), '.off{display:none}');
f.doc.styleSheets[0].insertRule('li.example-card{display:none}',0);
unchangedReject(f,/style/i);
""")

    def test_external_style_requires_exact_hash_name_live_sibling_and_text(self):
        self.run_js(r"""
const css='.off{display:none}';
const f=fixture(list(row('8') + row('9'))); external(f,css); f.prepare();
assert.equal(f.doc.querySelector('.index-tag').textContent,'1');
for(const mutate of [
 (f,x)=>x.link.href='../media/_study_'+'0'.repeat(64)+'.css',
 (f,x)=>x.link.href='https://outside.test/_study_'+sha(css)+'.css',
 (f,x)=>x.link.href+='?changed',
 (f,x)=>x.link.after(f.doc.createElement('i')),
 (f,x)=>x.node.textContent+=' ',
 (f,x)=>x.link.rel='alternate stylesheet',
 (f,x)=>f.options.styleSources[0].sourceNode=x.node]) {
 const f=fixture(list(row('8')));const x=external(f,css);mutate(f,x);unchangedReject(f,/style/i);
}
""")

    def test_static_display_and_non_display_responsive_rules_use_real_computed_style(self):
        self.run_js(r"""
const f=fixture(list(row('7','style="display:none"')+row('8','data-test="off"')+row('9')),
  '[data-test="off"]{display:none}@media(max-width:500px){li.example-card{padding:0}summary{display:none}}');
const proof=f.prepare();assert.equal(proof.stats.eligibleRows,1);
assert.deepEqual([...f.doc.querySelectorAll('.index-tag')].map(x=>x.textContent),['7','8','1']);
for(const css of ['li.example-card{display:flex}', '@media(max-width:500px){li.example-card{display:none}}',
 '@supports(display:grid){.example-card{display:grid}}', 'li.example-card:hover{display:none}',
 'li.example-card:not(:hover){display:none}', 'li.example-card:state(hidden){display:none}',
 'li.example-card:h\\6fver{display:none}', '@import url("other.css");']) {
 const f=fixture(list(row('7')),css);unchangedReject(f,/display|style|conditional|import/i);
}
""")

    def test_conditionally_displayed_excluded_history_does_not_change_main_rows(self):
        self.run_js(r"""
const f=fixture(list(row('7'))+'<div class="sf-pending">'+list(row('8'))+'</div>',
 '@media(max-width:500px){.sf-pending li.example-card{display:none}}');
f.prepare();assert.deepEqual([...f.doc.querySelectorAll('.index-tag')].map(x=>x.textContent),['1','8']);
""")

    def test_live_dom_attribute_ambiguity_rejects_without_claiming_raw_parser_recovery(self):
        self.run_js(r"""
for(const selector of ['ol','li','.index-tag']) {
 const f=fixture(list(row('7'))); f.doc.querySelector(selector).setAttributeNS('urn:unexpected','class','example-card');
 unchangedReject(f,/attribute/i);
}
""")

    def test_inverse_rejects_foreign_report_document_and_later_changes_atomically(self):
        self.run_js(r"""
const f=fixture(list(row('8')+row('9'))), proof=f.prepare();
assert.throws(()=>api.inverse(f.doc, JSON.parse(JSON.stringify(proof))), /proof/i);
assert.throws(()=>api.inverse(fixture(list(row('8'))).doc, proof), /document/i);
f.doc.querySelectorAll('.index-tag')[1].firstChild.data='independent';
assert.throws(()=>api.inverse(f.doc, proof), /changed/i);
assert.equal(f.doc.querySelector('.index-tag').textContent,'1');
""")


if __name__ == '__main__':
    unittest.main()
