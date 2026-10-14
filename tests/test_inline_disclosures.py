import hashlib
import json
import unittest

from anki_pipeline.inline_disclosures import DisclosureRestoreError, restore_definition_disclosures


def lazy(kind='panel', total=1):
    part = {'src': '_as_' + 'a' * 24 + '.js', 'sha256': 'a' * 64, 'count': total}
    manifest = {'schema': 'anki-slim-segments.v1', 'parts': [part], 'total': total}
    return '<div class="as-lazy" data-as-kind="' + kind + '"><script class="as-manifest" type="application/json">' + json.dumps(manifest, separators=(',', ':')) + '</script></div>'


def fixtures():
    prefix = '<div title="outside > original"><p>原义项</p></div><!-- untouched outside -->'
    pending_head = '<details class="sf-pending"><summary>待核对 1 处</summary>'
    pending = ('\n<p>原始记录，英文 target，中文原译。</p><details class="sf-ownership-history"><summary>本句归属说明</summary>'
               '<p>原审核完整依据</p><pre>&lt;div class="sf-panel"&gt;原HTML证据&lt;/div&gt;</pre>'
               '<script type="application/json">{"raw":"<div class=\"sf-panel\">字面脚本证据</div>"}</script>'
               '<iframe srcdoc="&lt;details class=&quot;sf-pending&quot;&gt;原框架&lt;/details&gt;"></iframe></details>\n')
    sense_head = '<details class="sf-sense"><summary class="sf-row"><i>v.</i> 遵守 <b>1 次</b></summary><div class="sf-panel">'
    filters = '<button data-sf-filter="all" aria-pressed="true">全部 1</button><p class="sf-preview-count">显示 1 处原文</p>'
    row = ('<article class="sf-example" data-sf-occurrence-id="' + 'b' * 64 + '"><p class="sf-source">2012年英语一 Text 2</p>'
           '<div class="sf-sentence-pair example-card"><p class="sf-en"><mark class="target-word">abide</mark> by regulations.</p>'
           '<p class="sf-zh">遵守法规。</p></div><details class="sf-ownership-history"><summary>本句完整审核</summary><p>完整归属与原说明。</p></details></article>')
    tail = '<p class="original-tail">尾注原样</p>'
    outside = '<ol class="examples"><li class="example-card"><span class="index-tag">9</span>普通例句原样。</li></ol><script>var proof="sf-panel as-lazy";</script>'
    baseline = prefix + '<div class="sf-report">' + pending_head + pending + '</details>' + sense_head + filters + row + tail + '</div></details></div>' + outside
    current = prefix + '<div class="sf-report">' + pending_head + lazy('detail') + '</details>' + sense_head + filters + lazy('panel') + tail + '</div></details></div>' + outside
    return baseline, current, pending, row


class InlineDisclosuresTests(unittest.TestCase):
    def test_real_failure_shape_restores_both_original_bodies_without_lazy_dependency(self):
        baseline, current, pending, row = fixtures()
        result = restore_definition_disclosures(current, baseline)
        self.assertEqual(result.html, baseline)
        self.assertEqual(len(result.regions), 2)
        self.assertIn(pending, result.html)
        self.assertIn(row, result.html)
        self.assertNotIn('class="as-lazy"', result.html)
        self.assertNotIn('class="as-manifest"', result.html)

    def test_outer_bytes_main_examples_scripts_iframe_and_audit_are_exact(self):
        baseline, current, *_ = fixtures()
        current = current.replace('<!-- untouched outside -->', '<!-- CURRENT outside must remain -->')
        result = restore_definition_disclosures(current, baseline)
        self.assertEqual(result.html, baseline.replace('<!-- untouched outside -->', '<!-- CURRENT outside must remain -->'))
        self.assertIn('<span class="index-tag">9</span>', result.html)
        self.assertIn('<iframe srcdoc="&lt;details class=&quot;sf-pending&quot;&gt;原框架&lt;/details&gt;"></iframe>', result.html)

    def test_regions_support_byte_exact_inverse_and_correct_sha_offsets(self):
        baseline, current, *_ = fixtures()
        result = restore_definition_disclosures(current, baseline)
        restored = result.html
        for region in reversed(result.regions):
            a, b = region['revised_start'], region['revised_end']
            self.assertEqual(hashlib.sha256(restored[a:b].encode()).hexdigest(), region['baseline_sha256'])
            self.assertEqual(current[region['current_start']:region['current_end']], region['original'])
            self.assertEqual(hashlib.sha256(region['original'].encode()).hexdigest(), region['current_sha256'])
            restored = restored[:a] + region['original'] + restored[b:]
        self.assertEqual(restored, current)

    def test_counts_summary_or_sense_order_mismatch_refuses_restoration(self):
        baseline, current, *_ = fixtures()
        for changed in (current.replace('遵守 <b>1 次', '支持 <b>1 次'),
                        current.replace('待核对 1 处', '待核对 2 处'),
                        current.replace('全部 1', '全部 7')):
            with self.subTest(changed=changed), self.assertRaises(DisclosureRestoreError):
                restore_definition_disclosures(changed, baseline)

    def test_missing_extra_or_unclosed_target_fails_closed(self):
        baseline, current, *_ = fixtures()
        bad = [current.replace('class="sf-panel"', 'class="different-panel"', 1),
               current.replace('</div></details></div>', '</details></div>'),
               current.replace('</div></details></div>', '</div><div class="sf-panel"></div></details></div>')]
        for markup in bad:
            with self.subTest(markup=markup), self.assertRaises(DisclosureRestoreError):
                restore_definition_disclosures(markup, baseline)

    def test_missing_or_ambiguous_direct_summary_is_rejected(self):
        baseline, current, *_ = fixtures()
        bad = current.replace('<summary>待核对 1 处</summary>', '<summary>待核对 1 处</summary><summary>另一个标题</summary>')
        with self.assertRaises(DisclosureRestoreError):
            restore_definition_disclosures(bad, baseline)

    def test_historical_same_named_regions_and_non_html_literals_are_not_targets(self):
        baseline, current, *_ = fixtures()
        archive = '<details class="sf-ownership-history"><summary>旧历史</summary><details class="sf-pending"><summary>历史待核对</summary><div class="sf-panel">历史不改</div></details></details>'
        result = restore_definition_disclosures(current + archive, baseline + archive.replace('历史不改', '不是当前资料'))
        self.assertTrue(result.html.endswith(archive))
        self.assertEqual(len(result.regions), 2)

    def test_attribute_only_history_wrapper_is_not_current_content(self):
        baseline, current, *_ = fixtures()
        archive = '<section data-native-ownership-history="true"><details class="sf-pending"><summary>历史</summary><p>不动</p></details></section>'
        result = restore_definition_disclosures(current + archive, baseline + archive.replace('不动', '不应挪入'))
        self.assertTrue(result.html.endswith(archive))

    def test_lazy_or_manifest_in_baseline_target_is_never_accepted(self):
        baseline, current, pending, _ = fixtures()
        with self.assertRaises(DisclosureRestoreError):
            restore_definition_disclosures(current, baseline.replace(pending, lazy('detail')))

    def test_bad_current_placeholder_or_static_body_changes_are_not_silently_dropped(self):
        baseline, current, *_ = fixtures()
        bad = [current.replace('"total":1', '"total":2', 1),
               current.replace('data-as-kind="panel"', 'data-as-kind="examples"'),
               current.replace(lazy('panel'), '<p>无法核验的新句子</p>')]
        for markup in bad:
            with self.subTest(markup=markup), self.assertRaises(DisclosureRestoreError):
                restore_definition_disclosures(markup, baseline)

    def test_already_inline_equal_targets_are_idempotent(self):
        baseline, *_ = fixtures()
        result = restore_definition_disclosures(baseline, baseline)
        self.assertEqual(result.html, baseline)
        self.assertEqual(result.regions, [])

    def test_nested_audit_detail_holes_restore_the_complete_pending_and_panel(self):
        baseline, _, pending, row = fixtures()
        pending_audit = pending[pending.index('<p>原审核完整依据'):pending.index('</details>')]
        current = baseline.replace(pending_audit, lazy('detail'))
        current = current.replace('<p>完整归属与原说明。</p>', lazy('detail'))
        result = restore_definition_disclosures(current, baseline)
        self.assertEqual(result.html, baseline)
        self.assertEqual([item['kind'] for item in result.regions], ['sf-pending', 'sf-panel'])
        self.assertIn(row, result.html)

    def test_multiple_nested_holes_match_their_unmodified_surrounding_content(self):
        baseline, _, _, row = fixtures()
        second = row.replace('b' * 64, 'c' * 64).replace('2012年英语一', '2018年英语二').replace('遵守法规。', '遵守另一项规定。')
        baseline = baseline.replace(row, row + second)
        current = baseline.replace('<p>完整归属与原说明。</p>', lazy('detail'))
        self.assertEqual(restore_definition_disclosures(current, baseline).html, baseline)

    def test_original_scripts_srcdoc_and_pre_do_not_create_lazy_nodes(self):
        baseline, _, _, _ = fixtures()
        inert = ('<script>var raw="<div class=\\"as-lazy\\">inert</div>";</script>'
                 '<pre>&lt;script class="as-manifest"&gt;原记录&lt;/script&gt;</pre>'
                 '<iframe srcdoc="&lt;div class=&quot;as-lazy&quot;&gt;旧数据&lt;/div&gt;"></iframe>')
        baseline = baseline.replace('<p class="original-tail">', inert + '<p class="original-tail">')
        result = restore_definition_disclosures(baseline, baseline)
        self.assertEqual(result.html, baseline)
        self.assertEqual(result.regions, [])

    def test_orphan_manifest_and_bool_count_are_rejected(self):
        baseline, current, *_ = fixtures()
        orphan = '<script class="as-manifest" type="application/json">{}</script>'
        bad = [current.replace(lazy('detail'), orphan),
               current.replace('"count":1', '"count":true', 1)]
        for markup in bad:
            with self.subTest(markup=markup), self.assertRaises(DisclosureRestoreError):
                restore_definition_disclosures(markup, baseline)

    def test_definition_without_these_targets_is_unchanged(self):
        current = '<p>普通释义</p><script>var marker="sf-pending";</script>'
        result = restore_definition_disclosures(current, '<p>不同的旧释义，不是修复目标</p>')
        self.assertEqual(result.html, current)
        self.assertEqual(result.regions, [])


if __name__ == '__main__':
    unittest.main()
