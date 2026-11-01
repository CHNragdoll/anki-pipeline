import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

SPEC = importlib.util.spec_from_file_location("project_metrics", Path(__file__).resolve().parents[1] / "scripts/project_metrics.py")
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


class ProjectMetricsTests(unittest.TestCase):
    def test_only_public_apkg_assets_count(self):
        releases = [{"tag_name": "book", "assets": [{"name": "book.apkg", "download_count": 5},
                     {"name": "SHA256SUMS.txt", "download_count": 99}]},
                    {"tag_name": "draft", "draft": True, "assets": [{"name": "hidden.apkg", "download_count": 9}]}]
        self.assertEqual(sum(a["download_count"] for a in metrics.apkg_assets(releases)), 5)

    def test_corrections_replace_instead_of_adding_or_taking_max(self):
        old = {"views": {"2026-10-30": {"count": 20, "uniques": 9}, "2026-10-29": {"count": 3, "uniques": 2}}}
        current = {"views": {"count": 10, "uniques": 4, "views": [
            {"timestamp": "2026-10-30T00:00:00Z", "count": 10, "uniques": 4}]}}
        merged = metrics.merge_traffic(old, current, "2026-11-02T00:00:00Z")
        self.assertEqual(merged["views"]["2026-10-30"]["count"], 10)
        self.assertEqual(merged["views"]["2026-10-29"]["count"], 3)
        self.assertNotIn("2026-10-31", merged["views"])
        self.assertEqual(old["views"]["2026-10-30"]["count"], 20)

    def test_permission_failure_keeps_all_history(self):
        old = {"views": {"2026-10-30": {"count": 5, "uniques": 2}}, "views_window": {"uniques": 2}}
        self.assertEqual(metrics.merge_traffic(old, {"views": None, "clones": None}, "now"), old)

    def test_empty_first_window_is_supported(self):
        result = metrics.merge_traffic({}, {"views": {"count": 0, "uniques": 0, "views": []}}, "now")
        self.assertEqual(result["views"], {})
        self.assertIsNone(result["views_window"]["start"])

    def test_uv_is_not_summed(self):
        rows = [{"timestamp": f"2026-10-{day}T00:00:00Z", "count": 5, "uniques": 4} for day in (29, 30)]
        result = metrics.merge_traffic({}, {"views": {"count": 10, "uniques": 5, "views": rows}}, "now")
        self.assertEqual(result["views_window"]["uniques"], 5)

    def test_bad_counts_fail(self):
        with self.assertRaises(ValueError):
            metrics.merge_traffic({}, {"views": {"count": 1, "uniques": 2, "views": [
                {"timestamp": "2026-10-30T00:00:00Z", "count": 1, "uniques": 2}]}}, "now")

    def test_current_readme_rows_and_content_scope(self):
        readme = (metrics.ROOT / "README.md").read_text()
        rows = metrics.book_rows(readme)
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(b["cards"] for b in rows), 16807)
        self.assertEqual(sum(b["questions"] for b in rows), 1631)
        self.assertEqual(len({b["subject"] for b in rows}), 3)
        self.assertEqual([line[3:] for line in readme.splitlines() if line.startswith("## ")][:2],
                         ["反馈问题", "下载 Anki 卡包"])

    def test_render_is_portable_xml_and_missing_dates_are_gaps(self):
        chart = metrics.chart("test & graph", "UTC", ["2026-10-29", "2026-10-30", "2026-10-31"],
                              [("PV", {"2026-10-29": 2, "2026-10-31": 4}, metrics.BLUE)], "no zeros", "now")
        root = ET.fromstring(chart)
        ns = {"s": "http://www.w3.org/2000/svg"}
        self.assertEqual(len(root.findall("s:polyline", ns)), 2)
        self.assertEqual(len(root.findall("s:circle", ns)), 2)
        self.assertFalse(root.findall(".//s:script", ns))

    def test_chart_scale_excludes_hidden_historical_spikes(self):
        chart = metrics.chart("test", "UTC", ["2026-10-31"],
                              [("PV", {"2026-10-01": 1000, "2026-10-31": 10}, metrics.BLUE)], "", "now")
        self.assertNotIn('>1000</text>', chart)
        self.assertIn('>10</text>', chart)

    def test_expired_traffic_token_does_not_freeze_public_metrics(self):
        book = metrics.book_rows((metrics.ROOT / "README.md").read_text())[0]
        def fake_api(endpoint, **kwargs):
            if '/traffic/' in endpoint:
                self.assertEqual(kwargs['token'], 'expired-test-fixture')
                raise RuntimeError('HTTP 401')
            self.assertNotIn('token', kwargs)
            if endpoint.endswith('/releases?per_page=100'):
                return [{'tag_name': book['tag'], 'assets': [{'name': book['asset'], 'download_count': 5, 'size': 100}]}]
            if endpoint.endswith('/languages'):
                return {'Python': 100}
            if '/commits?' in endpoint or '/stargazers?' in endpoint:
                return []
            return {'stargazers_count': 9, 'forks_count': 1, 'open_issues_count': 0, 'license': {'spdx_id': 'MIT'}}
        old = {'views': {'2026-10-30': {'count': 5, 'uniques': 2}}}
        with patch.object(metrics, 'api', side_effect=fake_api), patch.object(metrics, 'book_rows', return_value=[book]), patch.dict(metrics.os.environ, PROJECT_METRICS_TOKEN='expired-test-fixture'):
            data, history = metrics.collect('', old)
        self.assertEqual(data['stars'], 9)
        self.assertEqual(data['traffic_unavailable'], ['views', 'clones'])
        self.assertEqual(history['views'], old['views'])


if __name__ == "__main__":
    unittest.main()
