"""Small byte-preserving compiler contracts; no PG, browser or DOM dependency."""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import unittest

from anki_pipeline import study_chunk_intervals as intervals


def sha(raw):return hashlib.sha256(raw).hexdigest()


def example(en='A & B 😀.',zh='甲乙😀。',rows=None):
    rows=rows or [([0,1],[[0,1]]),([4,7],[[1,3]])]
    return {'text':en,'translation':zh,'translation_source':'codex','translation_alignment':{
        'schema':'codex-sentence-alignment.v1','englishHash':sha(en.encode()),'translationHash':sha(zh.encode()),
        'alignments':[{'en':a,'zh':b,'relation':'equivalent'}for a,b in rows]}}


TINY=(b'<!doctype html>\r\n<div class="example-card"><p class="en"><SPAN class=\'card-chunk\' '
      b'data-chunk-side=en data-chunk-ids="0">A</SPAN> &amp; '
      b'<span class="card-chunk" data-chunk-side="en" data-chunk-ids="1">B &#x1f600;</span>.</p>'
      b'<p class="zh"><span class="card-chunk" data-chunk-side="zh" data-chunk-ids="0">'+
      '甲'.encode()+b'</span><span class="card-chunk" data-chunk-side="zh" data-chunk-ids="1">'+
      '乙😀'.encode()+b'</span>'+ '。'.encode()+b'</p></div><!-- exact tail -->')


class ChunkIntervalsTests(unittest.TestCase):
    def binding(self,**kw):
        return intervals.SentenceBinding('tiny',0,example(),english_class='en',chinese_class='zh',**kw)
    def compile(self,raw=TINY,bindings=None):
        return intervals.compile_html(raw,bindings or [self.binding()],expected_source_sha256=sha(raw),
                                      css_sha256='f'*64,plain_chunks_are_interaction_only=True)
    def test_stream_compiles_pure_wrappers_and_inverse_is_original_bytes(self):
        built=self.compile()
        self.assertEqual(built.profile['stats']['removed_spans'],4,'identity renderer still allocates all chunk nodes')
        self.assertNotEqual(built.compact_html,TINY)
        self.assertIn(b'A &amp; B &#x1f600;.',built.compact_html)
        self.assertEqual(intervals.restore_html(built.compact_html,built.profile,
                         expected_source_sha256=sha(TINY),expected_profile_sha256=built.profile_sha256),TINY)
        self.assertEqual(built.profile['sentences'][0]['paragraphs'][0]['segments'][1][1],8)
    def test_wrong_source_css_capability_and_old_profile_are_not_accepted(self):
        with self.assertRaisesRegex(ValueError,'source SHA'):
            intervals.compile_html(TINY,[self.binding()],expected_source_sha256='0'*64,css_sha256='f'*64,
                                   plain_chunks_are_interaction_only=True)
        with self.assertRaisesRegex(ValueError,'style capability'):
            intervals.compile_html(TINY,[self.binding()],expected_source_sha256=sha(TINY),css_sha256='f'*64,
                                   plain_chunks_are_interaction_only=False)
        with self.assertRaises(ValueError):
            intervals.restore_html(TINY,{'schema':'study-compiled-card-interactions.v1'},
                                   expected_source_sha256=sha(TINY),expected_profile_sha256='0'*64)
    def test_valid_ids_moved_to_wrong_positions_rejected_even_with_new_source_hash(self):
        raw=TINY.replace(b'data-chunk-ids="0"',b'data-chunk-ids="x"',1).replace(
            b'data-chunk-ids="1"',b'data-chunk-ids="0"',1).replace(b'data-chunk-ids="x"',b'data-chunk-ids="1"',1)
        with self.assertRaisesRegex(ValueError,'canonical ID position'):self.compile(raw)
    def test_visual_aria_keyboard_unknown_and_nested_spans_are_retained(self):
        for attr in [b' style="color:red"',b' aria-label="x"',b' tabindex="0"',b' data-unknown="x"',b' id="stable"',b' role="button"']:
            with self.subTest(attr=attr):
                raw=TINY.replace(b"class='card-chunk'",b"class='card-chunk'"+attr,1)
                self.assertEqual(self.compile(raw).profile['stats']['removed_spans'],3)
        for open_,close_ in [(b'<mark class="target-word">',b'</mark>'),(b'<span class="sf-target-chunk">',b'</span>'),
                             (b'<span class="card-chunk" data-chunk-side="en" data-chunk-ids="0">',b'</span>')]:
            raw=TINY.replace(b'<SPAN',open_+b'<SPAN',1).replace(b'</SPAN>',b'</SPAN>'+close_,1)
            built=self.compile(raw);self.assertIn(open_,built.compact_html)
            self.assertEqual(built.profile['stats']['removed_spans'],3)
    def test_unknown_extra_class_comment_and_element_children_are_not_unwrapped(self):
        for raw in [TINY.replace(b"class='card-chunk'",b"class='card-chunk emphasis'",1),
                    TINY.replace(b'>A</SPAN>',b'>A<!--audit--></SPAN>'),
                    TINY.replace(b'>A</SPAN>',b'><b>A</b></SPAN>')]:
            self.assertEqual(self.compile(raw).profile['stats']['removed_spans'],3)
    def test_tampered_profile_compact_and_external_pins_fail_closed(self):
        b=self.compile();p=copy.deepcopy(b.profile);p['lexemes'][p['edits'][0][3]]='foreign'
        for raw,profile,pin in [(b.compact_html+b' ',b.profile,b.profile_sha256),(b.compact_html,p,b.profile_sha256),
                                (b.compact_html,b.profile,'0'*64)]:
            with self.assertRaises(ValueError):intervals.restore_html(raw,profile,expected_source_sha256=sha(TINY),expected_profile_sha256=pin)
        p=copy.deepcopy(b.profile);p['unknown']=True
        with self.assertRaises(ValueError):intervals.restore_html(b.compact_html,p,expected_source_sha256=sha(TINY),expected_profile_sha256=sha(intervals.profile_bytes(p)))
    def test_missing_duplicate_binding_and_reserved_anchors_rejected(self):
        for bindings in [[self.binding(),self.binding()],[intervals.SentenceBinding('missing',9,example(),english_class='en',chinese_class='zh')]]:
            with self.assertRaises(ValueError):self.compile(bindings=bindings)
        with self.assertRaises(ValueError):self.compile(TINY.replace(b'<p class="en">',b'<p class="en" data-study-chunk-interval-paragraph="foreign">'))
    def test_html5_ambiguous_context_and_malformed_selected_tree_are_rejected(self):
        for raw in [b'<template>'+TINY+b'</template>',b'<table><tr><td>'+TINY+b'</td></tr></table>',
                    TINY.replace(b'>A</SPAN>',b'>A</p></SPAN>'),TINY.replace(b'>A</SPAN>',b'>A<div></div></SPAN>'),
                    TINY.replace(b'data-chunk-side=en',b'data-chunk-side=en DATA-CHUNK-SIDE=en',1)]:
            with self.subTest(raw=raw[:30]),self.assertRaises(ValueError):self.compile(raw)
    def test_source_is_bounded_utf8_and_never_loads_external_assets(self):
        for raw in [TINY+b'\x00',TINY+b'\xff']:
            with self.assertRaises(ValueError):self.compile(raw)
        with self.assertRaisesRegex(ValueError,'limit'):
            intervals.compile_html(TINY,[self.binding()],expected_source_sha256=sha(TINY),css_sha256='f'*64,
                                   plain_chunks_are_interaction_only=True,max_source_bytes=10)
    def test_deterministic_and_caller_input_not_mutated(self):
        binding=self.binding();before=copy.deepcopy(binding.example);a=self.compile(bindings=[binding]);b=self.compile(bindings=[binding])
        self.assertEqual(a.compact_html,b.compact_html);self.assertEqual(a.profile_sha256,b.profile_sha256)
        self.assertEqual(binding.example,before)

    def test_numeric_cr_is_preserved_but_literal_crlf_is_normalized_before_dom_binding(self):
        def source(en,zh):
            return ('<div class="example-card"><p class="en"><span class="card-chunk" '
                    'data-chunk-side="en" data-chunk-ids="0">'+en+'</span></p><p class="zh">'
                    '<span class="card-chunk" data-chunk-side="zh" data-chunk-ids="0">'+zh+
                    '</span></p></div>').encode()
        numeric=source('A&#13;B','甲&#13;乙')
        original=example('A\rB','甲\r乙',[([0,3],[[0,3]])])
        binding=intervals.SentenceBinding('cr',0,original,english_class='en',chinese_class='zh')
        built=self.compile(numeric,[binding])
        self.assertEqual(built.profile['sentences'][0]['paragraphs'][0]['text_sha256'],sha(b'A\rB'))
        self.assertEqual(intervals.restore_html(built.compact_html,built.profile,
                         expected_source_sha256=sha(numeric),expected_profile_sha256=built.profile_sha256),numeric)
        normalized=example('A\nB','甲\n乙',[([0,3],[[0,3]])])
        normalized_binding=intervals.SentenceBinding('lf',0,normalized,english_class='en',chinese_class='zh')
        with self.assertRaisesRegex(ValueError,'canonical paragraph text'):
            self.compile(numeric,[normalized_binding])
        # Literal CRLF has the opposite rule; its DOM text is LF, not CRLF.
        literal=source('A\r\nB','甲\r\n乙')
        self.compile(literal,[normalized_binding])


    def test_real_train_three_member_group_and_native_compile_without_old_profile(self):
        path=Path(__file__).parent/'fixtures/experimental-compiled-card-v1/train/final.html.gz'
        raw=gzip.decompress(path.read_bytes())
        self.assertEqual(sha(raw),'20e8e39afe32a44052dc3b03f6683c4bd43a91d2487ce23ce5fced685d8800de')
        en='Ferrovie dello Stato Italiane, the publicly controlled group that owns train operator Trenitalia and the national train network RFI, said 23 percent of all high-speed trains it operated were late in 2023.'
        zh='意大利国家铁路集团是一家受政府控制的集团，旗下拥有铁路运营商意大利铁路公司和全国铁路网运营商 RFI；该集团表示，2023 年其运营的高铁列车有 23% 晚点。'
        # Original frozen ID order, certified by the pilot's exact bilingual
        # range bijection [0,1,2,3,4,5,7,8,6]; not a text-only ID remap.
        rows=[([0,29],[[0,9]]),([35,60],[[12,20]]),([66,96],[[21,37]]),([105,131],[[38,50]]),
              ([133,137],[[54,56]]),([138,148],[[73,76]]),([156,173],[[67,71]]),
              ([177,185],[[64,66]]),([191,195],[[77,79]])]
        ex=example(en,zh,rows)
        bindings=[intervals.SentenceBinding('sf-'+str(i),i,ex) for i in (4,5,6)]
        bindings.append(intervals.SentenceBinding('native',49,ex,english_class='example-text',
                        chinese_class='example-translation',chinese_prefix='翻译 '))
        b=self.compile(raw,bindings)
        self.assertEqual(b.profile['stats'],{'roots':4,'paragraphs':8,'segments':82,'removed_spans':64,'retained_spans':18})
        self.assertEqual(len(b.profile['sources']),1)
        self.assertGreater(len(b.profile['preserved_roots']),0)
        for row in b.profile['preserved_roots']:
            self.assertEqual(row['reason'],'unselected')
            self.assertEqual(sha(raw[row['start']:row['end']]),row['sha256'])
            self.assertIn(raw[row['start']:row['end']],b.compact_html)
            self.assertNotIn(row['root_index'],(4,5,6,49))
        self.assertEqual(intervals.restore_html(b.compact_html,b.profile,expected_source_sha256=sha(raw),
                         expected_profile_sha256=b.profile_sha256),raw)
        # All IDs/audits/other 26 panel rows remain raw source bytes outside
        # the exact wrapper edits; no DOM-profile file is loaded.
        self.assertEqual(b.compact_html.count(b'data-sf-occurrence-id='),raw.count(b'data-sf-occurrence-id='))
        self.assertEqual(b.compact_html.count(b'sf-group-member-evidence'),raw.count(b'sf-group-member-evidence'))
        self.assertLess(len(b.profile['attributes']),82)
    def test_real_abolish_native_uses_same_generic_interface_and_exact_inverse(self):
        path=Path(__file__).parent/'fixtures/experimental-compiled-card-v1/abolish/final.html'
        raw=path.read_bytes()
        self.assertEqual(sha(raw),'f6fad5fc6c2e5f457cdca2489754de547a52559924b13128ff1cfcb5d6d72c1d')
        en='This law abolished special educational requirements for federal jurors and required them to be selected at random from a cross section of the entire community.'
        zh='该法废除了联邦陪审员须满足的特殊教育要求，规定必须从整个社区具有代表性的人群中随机选出他们。'
        # Frozen original IDs, explicit reviewed bilingual range order
        # [0,1,2,3,7,4,5,6], not an old DOM profile.
        rows=[([5,8],[[0,2]]),([9,18],[[2,4]]),([19,51],[[14,20]]),([56,70],[[5,10]]),
              ([75,83],[[21,25]]),([95,113],[[39,43]]),([121,134],[[30,38]]),([142,158],[[26,30]])]
        binding=intervals.SentenceBinding('native',4,example(en,zh,rows),english_class='example-text',
                    chinese_class='example-translation',chinese_prefix='翻译 ')
        b=self.compile(raw,[binding])
        self.assertGreater(b.profile['stats']['removed_spans'],0)
        self.assertEqual(b.profile['stats']['roots'],1)
        self.assertEqual(intervals.restore_html(b.compact_html,b.profile,expected_source_sha256=sha(raw),
                         expected_profile_sha256=b.profile_sha256),raw)
        self.assertIn(b'<mark class="target-word target-word">',b.compact_html)


    def test_shared_overlap_whole_ids_and_utf16_offsets_are_distinct(self):
        from anki_pipeline.packaging import _example_chunk_ranges,_chunk_translation,_annotate_sentence_chunks,_highlight_example
        ex=example('A😀 BC & D','甲😀乙 & 丙',[([0,9],[[0,7]]),([1,3],[[1,3]]),([0,4],[[0,3]])])
        ex['translation_alignment']['alignments'][0]['note']='整句对应：controlled fallback'
        en,zh,ready=_example_chunk_ranges(ex);self.assertTrue(ready)
        # Produce legal shared markup, not a hand-authored span approximation.
        a=_annotate_sentence_chunks(_highlight_example(ex['text'],'absent','',[],chunk_ranges=en,preserve_source=True),ex['translation_alignment'])
        z=_annotate_sentence_chunks(_chunk_translation(ex['translation'],zh),ex['translation_alignment'])
        raw=('<div class="example-card"><p class="en">'+a+'</p><p class="zh">'+z+'</p></div>').encode()
        b=self.compile(raw,[intervals.SentenceBinding('overlap',0,ex,english_class='en',chinese_class='zh')])
        self.assertEqual(b.profile['sources'][0]['sentence_ids'],['0'])
        self.assertEqual(b.profile['sources'][0]['ranges']['en'][0],(1,3,1))
        self.assertTrue(any(b.profile['id_sets'][row[2]]==['1','2','0']for row in b.profile['sentences'][0]['paragraphs'][0]['segments']))
        self.assertEqual(intervals.restore_html(b.compact_html,b.profile,expected_source_sha256=sha(raw),expected_profile_sha256=b.profile_sha256),raw)
    def test_interactive_ancestor_is_not_unwrapped_and_self_closing_html_rejected(self):
        raw=TINY.replace(b'<SPAN',b'<a href="#exact"><SPAN',1).replace(b'</SPAN>',b'</SPAN></a>',1)
        self.assertEqual(self.compile(raw).profile['stats']['removed_spans'],3)
        for prefix in [b'<textarea/>',b'<script/>',b'<div/>']:
            with self.assertRaisesRegex(ValueError,'self-closing'):self.compile(prefix+TINY)
    def test_no_querying_css_evaluation_or_source_script_execution(self):
        raw=TINY+b'<script>throw Error("must never run");</script><style>/* preserved */</style>'
        b=self.compile(raw)
        self.assertIn(b'<script>throw Error("must never run");</script>',b.compact_html)
        self.assertEqual(intervals.restore_html(b.compact_html,b.profile,expected_source_sha256=sha(raw),expected_profile_sha256=b.profile_sha256),raw)
    def test_inverse_rejects_malformed_edits_even_with_a_fresh_profile_pin(self):
        b=self.compile()
        for change in ['position','reference','boolean','order']:
            p=copy.deepcopy(b.profile)
            if change=='position':p['edits'][0][1]+=1
            elif change=='reference':p['edits'][0][2]=len(p['lexemes'])
            elif change=='boolean':p['edits'][0][0]=False
            else:p['edits'].reverse()
            with self.subTest(change=change),self.assertRaises(ValueError):
                intervals.restore_html(b.compact_html,p,expected_source_sha256=sha(TINY),expected_profile_sha256=sha(intervals.profile_bytes(p)))


    def test_native_translation_prefix_is_exact_dom_text_not_stripped(self):
        raw=TINY.replace(b'<p class="zh">',b'<p class="zh"><span class="translate-tag">'+ '翻译'.encode()+b'</span> ')
        b=self.compile(raw,[self.binding(chinese_prefix='翻译 ')])
        self.assertEqual(b.profile['sentences'][0]['paragraphs'][1]['prefix'],'翻译 ')
        with self.assertRaisesRegex(ValueError,'paragraph text'):self.compile(raw,[self.binding(chinese_prefix='翻译')])


if __name__=='__main__':unittest.main()
