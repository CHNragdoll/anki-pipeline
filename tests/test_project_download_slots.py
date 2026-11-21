import unittest
from pathlib import Path

from scripts.project_download_slots import (
    DOWNLOAD_RELEASES,
    asset_links,
    asset_slot,
    build_download_slots,
    offline_slot_assets,
    readme_slots,
    record_slot_assets,
)


BASE = "https://github.com/CHNragdoll/anki-pipeline/releases/download"
TAG = "math-exams"


class ProjectDownloadSlotTests(unittest.TestCase):
    def test_readme_uses_stable_slot_and_deduplicates_shared_workbook_link(self):
        scope = (Path(__file__).resolve().parents[1] / "README.md").read_text()
        mapping = readme_slots(scope)
        pinned = scope.split("## 下载 Anki 卡包", 1)[1].split("<!-- pinned-entrypoints:end -->", 1)[0]
        self.assertEqual(set(mapping), asset_links(pinned))
        for slot in ("math1.questions", "math1.a4-adaptive", "english2.answers",
                     "sheet.economics-396.new", "liuxiaoyan2027.anki"):
            self.assertEqual(list(mapping.values()).count(slot), 1)
        self.assertNotIn("v3.0.0-rc.2", DOWNLOAD_RELEASES)
        self.assertIsNone(asset_slot(TAG, "all-math1-questions.pdf.txt"))
        self.assertIsNone(asset_slot("retired", "all-math1-questions.pdf"))

    def test_renamed_link_and_withdrawn_attachment_remain_in_the_same_cell(self):
        def readme(filename):
            return (f"| 科目 | 真题试卷 PDF |\n|---|---|\n"
                    f"| 数学一 · 301 | [下载]({BASE}/{TAG}/{filename}) |")

        archive = {"assets": {
            "1": [TAG, "original.pdf", "2026-11-19T00:00:00Z"],
            "2": [TAG, "new name.pdf", "2026-11-20T00:00:00Z"],
        }, "samples": {
            "2026-11-19T10:00:00Z": {"counts": {"1": 12}, "total": 12},
            "2026-11-20T10:00:00Z": {"counts": {"2": 4}, "total": 4},
            "2026-11-21T10:00:00Z": {"counts": {"2": 3}, "total": 3},
        }}
        for filename, api_name, identity in (("original.pdf", "original.pdf", 1),
                                             ("new%20name.pdf", "new name.pdf", 2)):
            record_slot_assets(archive, readme(filename), [{
                "tag_name": TAG,
                "assets": [{"id": identity, "name": api_name}],
            }])
        self.assertEqual(archive["slot_assets"], {"1": "math1.questions", "2": "math1.questions"})
        slot, = build_download_slots(archive, "2026-11-21T10:00:00Z")
        self.assertEqual(slot["asset_ids"], ["2", "1"])
        self.assertEqual([(point["total"], point["change"]) for point in slot["points"]],
                         [(12, None), (16, 4), (15, -1)])

    def test_renamed_syllabus_and_vocabulary_links_are_associated_by_display_role(self):
        readme = (f"| 卡包 | APKG 下载 |\n|---|---|\n"
                  f"| 2027考研红宝书 | [下载]({BASE}/new-redbook/edition.apkg) |\n\n"
                  f"[考研数学一考试大纲 PDF]({BASE}/{TAG}/guide.pdf)")
        self.assertEqual(readme_slots(readme), {
            ("new-redbook", "edition.apkg"): "redbook2027.anki",
            (TAG, "guide.pdf"): "math1.syllabus",
        })

    def test_single_link_cannot_be_attributed_to_two_different_cells(self):
        link = f"[下载]({BASE}/{TAG}/sample.pdf)"
        readme = (f"| 科目 | 真题试卷 PDF | 答案速查 PDF |\n|---|---|---|\n"
                  f"| 数学一 · 301 | {link} | {link} |")
        with self.assertRaises(ValueError):
            readme_slots(readme)

    def test_legacy_same_name_is_conservative_and_missing_days_are_not_zero(self):
        filename = "all-math1-questions.pdf"
        archive = {"assets": {
            "1": [TAG, filename, "2026-11-15T00:00:00Z"],
            "2": [TAG, filename, "2026-11-16T00:00:00Z"],
        }, "legacy": {
            "2026-11-15T01:00:00Z": {"files": [[TAG, filename, 9]]},
            "2026-11-16T01:00:00Z": {"files": [[TAG, filename, 99]]},
        }, "samples": {
            "2026-11-17T01:00:00Z": {"counts": {"2": 4}, "total": 4},
            "2026-11-18T01:00:00Z": {"counts": {"2": 12}, "total": 12},
        }}
        slot, = build_download_slots(archive, "2026-11-17T01:00:00Z")
        self.assertEqual([(point["day"], point["total"], point["change"]) for point in slot["points"]],
                         [("2026-11-15", 9, None), ("2026-11-17", 13, None)])
        self.assertTrue(slot["points"][-1]["partial"])

    def test_change_does_not_mix_different_coverage_or_unmeasured_old_downloads(self):
        filename = "all-math1-questions.pdf"
        archive = {
            "assets": {
                str(identity): [TAG, filename, "2026-11-10T00:00:00Z"] for identity in range(1, 4)
            },
            "samples": {
                "2026-11-13T01:00:00Z": {"counts": {"1": 9}},
                "2026-11-14T01:00:00Z": {"counts": {"1": 10, "2": 45}, "total": 55},
                "2026-11-15T01:00:00Z": {"counts": {"1": 11, "2": 46, "3": 90}, "total": 147},
                "2026-11-16T01:00:00Z": {"counts": {"1": 12, "2": 47, "3": 91}, "total": 150},
            },
        }
        slot, = build_download_slots(archive, "2026-11-16T01:00:00Z")
        for series in ("points", "utc_points"):
            self.assertEqual([(point["total"], point["change"]) for point in slot[series]],
                             [(9, None), (55, None), (147, None), (150, 3)])

    def test_first_downloads_have_a_delta_only_with_a_proven_zero_baseline(self):
        filename = "all-math1-questions.pdf"
        at = "2026-11-21T01:00:00Z"
        before = "2026-11-20T01:00:00Z"
        archive = {
            "assets": {"1": [TAG, filename, "2026-11-20T20:00:00Z"]},
            "samples": {before: {"counts": {}, "total": 0}, at: {"counts": {"1": 3}, "total": 3}},
        }
        slot, = build_download_slots(archive, at)
        self.assertEqual([p["change"] for p in slot["points"]], [3])
        self.assertEqual([p["change"] for p in slot["utc_points"]], [3])
        archive["assets"]["1"][2] = None
        slot, = build_download_slots(archive, at)
        self.assertIsNone(slot["points"][0]["change"])
        archive["assets"]["1"][2] = "2026-11-20T20:00:00Z"
        archive["legacy"] = {before: {"files": [[TAG, "all-math1-questions-20261107.pdf", 2]]}}
        slot, = build_download_slots(archive, at)
        self.assertIsNone(slot["points"][0]["change"])
        self.assertEqual(slot["asset_ids"], ["1"])

    def test_days_and_delta_are_rebucketed_in_each_timezone(self):
        filename = "all-math1-questions.pdf"
        archive = {"assets": {"1": [TAG, filename, "2026-11-15T00:00:00Z"]},
                   "samples": {
                       "2026-11-15T15:59:00Z": {"counts": {"1": 4}, "total": 4},
                       "2026-11-15T16:05:00Z": {"counts": {"1": 8}, "total": 8},
                       "2026-11-16T01:00:00Z": {"counts": {"1": 12}, "total": 12},
                   }}
        slot, = build_download_slots(archive, "2026-11-16T01:00:00Z")
        self.assertEqual([point["change"] for point in slot["points"]], [None, 8])
        self.assertEqual([point["change"] for point in slot["utc_points"]], [None, 4])
        self.assertFalse(slot["points"][0]["partial"])
        self.assertTrue(slot["points"][1]["partial"])

    def test_offline_render_only_matches_links_confirmed_in_that_snapshot(self):
        at = "2026-11-19T10:00:00Z"
        archive = {"assets": {"1": [TAG, "older.pdf", at], "2": [TAG, "newer.pdf", at]},
                   "samples": {at: {"counts": {"1": 8, "2": 6}, "total": 14}}}
        mapping = {(TAG, "older.pdf"): "math1.questions", (TAG, "newer.pdf"): "math2.questions"}
        current = [{"tag": TAG, "name": "older.pdf"}, {"tag": TAG, "name": "newer.pdf", "published": False}]
        self.assertEqual(offline_slot_assets(archive, mapping, current, at), {"1": "math1.questions"})
        self.assertEqual(offline_slot_assets(archive, mapping, current, "2026-11-18T10:00:00Z"), {})
