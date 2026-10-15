"""Sense previews retain exact authored chunks and original card interactions."""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from anki_pipeline.sense_chunks import render_sentence_pair
from anki_pipeline.translation_alignment import TranslationAlignmentError


ROOT = Path(__file__).resolve().parents[1]


def row(english="The rate rose.", translation="比率上升了。", entries=None, target=(4, 8)):
    if entries is None:
        entries = [{"en": [0, 8], "zh": [[0, 2]], "relation": "equivalent"},
                   {"en": [9, 13], "zh": [[2, 5]], "relation": "equivalent"}]
    return {"english": english, "translation": translation, "target_range": list(target),
            "alignment": {"schema": "codex-sentence-alignment.v1",
                          "englishHash": hashlib.sha256(english.encode()).hexdigest(),
                          "translationHash": hashlib.sha256(translation.encode()).hexdigest(),
                          "alignments": entries}}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")


def plain(fragment):
    parser = Text()
    parser.feed(fragment)
    return "".join(parser.parts)


class SenseChunkTests(unittest.TestCase):
    def test_default_accent_uses_full_target_chunk_and_its_chinese_pair(self):
        value = row()
        original = copy.deepcopy(value)
        rendered = render_sentence_pair(value)
        self.assertIn('sf-sentence-pair example-card', rendered)
        self.assertIn('class="card-chunk sf-target-chunk" data-chunk-side="en" data-chunk-ids="0">The ', rendered)
        self.assertIn('<mark class="target-word"><span class="card-chunk sf-target-chunk"', rendered)
        self.assertIn('class="card-chunk sf-target-chunk" data-chunk-side="zh" data-chunk-ids="0">比率</span>', rendered)
        self.assertIn('class="card-chunk" data-chunk-side="en" data-chunk-ids="1">rose</span>', rendered)
        self.assertEqual(plain(rendered), value['english'] + value['translation'])
        self.assertEqual(value, original)
        self.assertNotIn('term-highlight', rendered)

    def test_unicode_html_whitespace_and_many_to_many_ranges_remain_exact(self):
        english, chinese = " \n😀 rate <&> rose. ", "\n比率<&>上升😀。 "
        start = english.index("rate")
        value = row(english, chinese, [
            {"en": [start, english.index("rose") + 4], "zh": [[0, 3], [6, len(chinese)]],
             "relation": "equivalent"}], target=(start, start + 4))
        rendered = render_sentence_pair(value)
        self.assertEqual(plain(rendered), english + chinese)
        self.assertNotIn("<&>", rendered)
        self.assertEqual(rendered.count('data-chunk-side="zh" data-chunk-ids="0"'), 2)
        self.assertNotIn("card-chunk-active", rendered)

    def test_target_crossing_two_existing_chunks_keeps_both_complete_chunks(self):
        rendered = render_sentence_pair(row(entries=[
            {"en": [0, 6], "zh": [[0, 2]], "relation": "equivalent"},
            {"en": [6, 13], "zh": [[2, 5]], "relation": "equivalent"}]))
        self.assertEqual(rendered.count('<mark class="target-word">'), 1)
        self.assertIn('data-chunk-ids="0">ra</span><span class="card-chunk sf-target-chunk" data-chunk-side="en" data-chunk-ids="1">te</span></mark>', rendered)
        self.assertIn('data-chunk-ids="0">The </span>', rendered)
        self.assertIn('data-chunk-ids="1"> rose</span>', rendered)
        self.assertEqual(plain(rendered), "The rate rose.比率上升了。")

    def test_finest_exact_chunk_wins_over_containing_chunk_and_overlap_does_not_repeat_text(self):
        rendered = render_sentence_pair(row(entries=[
            {"en": [0, 13], "zh": [[0, 5]], "relation": "equivalent"},
            {"en": [4, 8], "zh": [[0, 2], [1, 3]], "relation": "equivalent"}]))
        self.assertIn('class="card-chunk sf-target-chunk" data-chunk-side="en" data-chunk-ids="1 0">rate</span>', rendered)
        self.assertIn('class="card-chunk" data-chunk-side="en" data-chunk-ids="0">The </span>', rendered)
        self.assertEqual(plain(rendered), "The rate rose.比率上升了。")

    def test_missing_and_implicit_alignment_do_not_fabricate_bilingual_highlight(self):
        missing = row()
        missing.pop("alignment")
        empty = row(entries=[])
        implicit = row(entries=[{"en": [4, 8], "zh": [], "relation": "implicit", "note": "未译"}])
        for value in (missing, empty, implicit):
            with self.subTest(value=value):
                rendered = render_sentence_pair(value)
                self.assertNotIn('data-chunk-', rendered)
                self.assertNotIn('sf-target-chunk', rendered)
                self.assertIn('<mark class="target-word">rate</mark>', rendered)
                self.assertIn('<p class="sf-zh">比率上升了。</p>', rendered)

    def test_provided_alignment_with_drift_or_invalid_ranges_fails(self):
        changes = [lambda value: value.update(translation="比率上升了！"),
                   lambda value: value.update(english="The rates rose."),
                   lambda value: value['alignment'].update(schema="unknown"),
                   lambda value: value['alignment']['alignments'][0].update(zh=[[0, 99]])]
        for change in changes:
            value = row()
            change(value)
            with self.subTest(value=value), self.assertRaises(TranslationAlignmentError):
                render_sentence_pair(value)
        for span in ([True, 8], [4, 999], [8, 4], None):
            with self.subTest(span=span), self.assertRaises(ValueError):
                render_sentence_pair({**row(), "target_range": span})

    def test_existing_hover_touch_and_filter_runtime_matches_real_rendered_markup(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node runtime unavailable")
        markup = render_sentence_pair(row())
        payload = {"markup": markup,
                   "chunks": (ROOT / "anki_pipeline/templates/card-chunks.js").read_text(),
                   "sense": (ROOT / "anki_pipeline/templates/sense-frequency.js").read_text(),
                   "css": (ROOT / "anki_pipeline/templates/sense-frequency.css").read_text()}
        script = r'''
const assert = require('node:assert/strict');
const { JSDOM } = require('jsdom');
const data = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const html = '<style>p,summary{font-weight:700}</style><style>' + data.css + '</style>' +
  '<div class="sf-report"><details class="sf-sense"><summary class="sf-row">' +
  '<span class="sf-meaning">释义</span><span class="sf-count">2次</span>' +
  '<span class="sf-years"><span class="sf-year-chip">2022 · 1次</span></span></summary>' +
  '<div class="sf-panel"><div class="sf-filters"><button data-sf-filter="all" aria-pressed="true">全部</button>' +
  '<button data-sf-filter="2022" aria-pressed="false">2022</button></div><p class="sf-preview-count"></p>' +
  '<article class="sf-example" data-sf-year="2022">' + data.markup + '</article>' +
  '<article class="sf-example" data-sf-year="2020">' + data.markup + '</article></div></details></div><button id="outside">离开</button>';
const dom = new JSDOM(html, { runScripts: 'outside-only' });
const { window } = dom, document = window.document;
window.PointerEvent = window.MouseEvent;
window.eval(data.chunks); window.eval(data.sense);
let flips = 0, keys = 0;
document.addEventListener('click', () => flips++);
document.addEventListener('keydown', () => keys++);
const examples = [...document.querySelectorAll('.sf-example')];
const first = examples[0], second = examples[1];
const en = first.querySelector('[data-chunk-side="en"][data-chunk-ids="0"]');
const zh = first.querySelector('[data-chunk-side="zh"][data-chunk-ids="0"]');
const other = first.querySelector('[data-chunk-side="en"][data-chunk-ids="1"]');
const otherZh = first.querySelector('[data-chunk-side="zh"][data-chunk-ids="1"]');
const active = node => node.classList.contains('card-chunk-active');
const accent = node => node.classList.contains('sf-target-chunk');
const emit = (type, target, pointerType='mouse', relatedTarget=null) => {
  const event = new window.MouseEvent(type, { bubbles:true, cancelable:true, relatedTarget });
  Object.defineProperty(event, 'pointerType', { value:pointerType });
  target.dispatchEvent(event); return event;
};
assert.equal(window.getComputedStyle(en).backgroundColor, 'rgb(230, 239, 255)');
assert.equal(window.getComputedStyle(zh).backgroundColor, 'rgb(230, 239, 255)');
assert.equal(window.getComputedStyle(document.querySelector('.sf-en')).fontWeight, '400');
assert.equal(window.getComputedStyle(document.querySelector('.sf-meaning')).fontWeight, '400');
emit('pointerover', other);
assert(active(other) && active(otherZh));
assert(!active(second.querySelector('.card-chunk')), 'identical IDs remain scoped to one occurrence');
emit('pointerout', other, 'mouse', document.body);
assert(!active(otherZh));
emit('pointerover', zh);
assert(active(en) && active(zh));
emit('pointerout', zh, 'mouse', document.body);
assert(!active(en) && accent(en), 'hover cleanup retains the full default target chunk');
emit('pointerover', other, 'touch');
assert(!active(otherZh), 'touch pointerover does not preactivate');
const tap = emit('click', other, 'touch');
assert(tap.defaultPrevented && active(otherZh));
assert.equal(flips, 0, 'chunk taps never reach card-flip/rating handlers');
emit('click', otherZh, 'touch');
assert(!active(other) && accent(en));
emit('click', zh, 'touch');
assert(active(en));
const escape = new window.KeyboardEvent('keydown', { key:'Escape', bubbles:true });
zh.dispatchEvent(escape);
assert(!active(en) && accent(en));
assert.equal(keys, 0);
second.querySelector('.card-chunk').click();
document.querySelector('[data-sf-filter="2022"]').click();
assert.equal(examples[0].hidden, false);
assert.equal(examples[1].hidden, true);
assert.equal(document.querySelector('.sf-preview-count').textContent, '显示 1 处原文');
assert.equal(window.__ankiCardChunkState, null);
assert.equal(flips, 0);
const summary = document.querySelector('summary');
summary.click(); assert.equal(document.querySelector('details').open, true);
summary.click(); assert.equal(document.querySelector('details').open, false);
assert.equal(flips, 0, 'native disclosure still works without triggering review');
const space = new window.KeyboardEvent('keydown', { key:' ', bubbles:true, cancelable:true });
summary.dispatchEvent(space);
assert.equal(space.defaultPrevented, false, 'native keyboard activation remains permitted');
assert.equal(keys, 0);
document.querySelector('#outside').click(); assert.equal(flips, 1);
dom.window.close();
'''
        result = subprocess.run([node, "-e", script], input=json.dumps(payload),
                                text=True, capture_output=True, cwd=ROOT, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
