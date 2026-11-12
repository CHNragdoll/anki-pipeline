import importlib.util
import io
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

    def test_pdf_and_apkg_assets_count_without_drafts_or_metadata(self):
        releases = [{"tag_name": "math-exams", "assets": [
            {"name": "book.apkg", "download_count": 5},
            {"name": "paper.PDF", "download_count": 7},
            {"name": "checksums.json", "download_count": 99}]},
            {"tag_name": "draft", "draft": True, "assets": [
                {"name": "hidden.pdf", "download_count": 50}]}]
        self.assertEqual(sum(a["download_count"] for a in metrics.download_assets(releases)), 12)
        self.assertEqual(sum(a["download_count"] for a in metrics.apkg_assets(releases)), 5)

    def test_full_readme_mixed_downloads_and_missing_unpublished_attachments(self):
        readme = (metrics.ROOT / "README.md").read_text()
        declared = metrics.current_download_rows(readme)
        self.assertEqual(len(declared), 85)  # 10 APKG + 75 PDF; repeated links deduplicate.
        self.assertEqual(sum(row["name"].endswith(".pdf") for row in declared), 75)
        sheets = [row["name"] for row in declared if row["tag"] == "answer-sheets"]
        self.assertEqual(sum(name.endswith("-2023.pdf") for name in sheets), 14)
        self.assertEqual(sum(name.endswith("-collection.pdf") for name in sheets), 20)
        math = [row for row in declared if row["tag"] == "math-exams"]
        self.assertEqual(len(math), 18)
        for n in (1, 2, 3):
            self.assertIn({"tag": "math-exams", "name": f"2027-math{n}-syllabus.pdf"}, math)
        self.assertIn({"tag": "politics-exams", "name": "2027-politics-syllabus-20261108.pdf"}, declared)
        # One current PDF is absent before upload; it must receive zero, not a stale count.
        missing = next(row for row in math if row["name"].endswith(".pdf"))
        available = [dict(row, download_count=7 if row["name"].endswith(".pdf") else 5, size=100)
                     for row in declared if row != missing]
        old = {"views": {"2026-10-30": {"count": 5, "uniques": 2}}}
        def fake_api(endpoint, **kwargs):
            if '/traffic/' in endpoint:
                raise RuntimeError('unavailable')
            if '/releases?' in endpoint:
                releases = [{"tag_name": tag, "assets": [row for row in available if row["tag"] == tag]}
                            for tag in dict.fromkeys(row["tag"] for row in available)]
                releases[0]["assets"].extend([
                    {"name": "old.pdf", "download_count": 11, "size": 100},
                    {"name": "checksums.json", "download_count": 999, "size": 100}])
                return releases
            if endpoint.endswith('/languages'):
                return {"Python": 100}
            if '/commits?' in endpoint or '/stargazers?' in endpoint:
                return []
            return {"stargazers_count": 9, "forks_count": 1, "open_issues_count": 0, "license": {"spdx_id": "MIT"}}
        with patch.object(metrics, 'api', side_effect=fake_api):
            data, history = metrics.collect(readme, old)
        self.assertEqual(data['apkg_downloads_all_releases'], 50)
        self.assertEqual(data['downloads_all_releases'], 50 + 74 * 7 + 11)
        self.assertEqual(history['views'], old['views'])
        absent = next(row for row in data['current_assets'] if row['name'] == missing['name'])
        self.assertEqual(absent['downloads'], 0)
        self.assertFalse(absent['published'])
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            metrics.render(data, output)
            self.assertIn('Downloads: 579', (output / 'downloads.svg').read_text())
            self.assertIn('APKG downloads: 50', (output / 'apkg-downloads.svg').read_text())
            self.assertIn('Anki: 15', (output / 'math-exams-apkg-downloads.svg').read_text())
            self.assertIn('PDF: 109', (output / 'math-exams-pdf-downloads.svg').read_text())
            self.assertIn('PDF: 42', (output / 'english-exams-pdf-downloads.svg').read_text())
            self.assertIn('Anki: /', (output / 'english-exams-apkg-downloads.svg').read_text())
            self.assertIn('Downloads: 42', (output / 'english-exams-downloads.svg').read_text())
            self.assertIn('PDF: 35', (output / 'politics-exams-pdf-downloads.svg').read_text())
            self.assertIn('Downloads: 124', (output / 'math-exams-downloads.svg').read_text())
            self.assertIn('current Downloads: 113', (output / 'math-exams-current-downloads.svg').read_text())
            self.assertIn('Downloads: /', (output / (Path(missing['name']).stem + '-downloads.svg')).read_text())
            self.assertEqual(json.loads((output / 'history.json').read_text()), history)
            self.assertEqual(len(list(output.glob('all-math*-downloads.svg'))), 12)

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
        self.assertEqual(len(rows), 10)
        self.assertEqual(sum(b["cards"] for b in rows), 21729)
        self.assertEqual(len([b for b in rows if b["subject"] == "数学"]), 3)
        self.assertEqual(len({b["subject"] for b in rows}), 6)
        self.assertEqual([line[3:] for line in readme.splitlines() if line.startswith("## ")][:3],
                         ["项目概述", "下载 Anki 卡包", "反馈问题"])

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

    def test_popular_traffic_keeps_changed_and_daily_snapshots(self):
        history = {}
        rows = [{"referrer": "Bing", "count": 27, "uniques": 25}]
        metrics.record_popular(history, "referrers", rows, "2026-11-07T22:00:00+00:00")
        metrics.record_popular(history, "referrers", rows, "2026-11-07T23:00:00+00:00")
        metrics.record_popular(history, "referrers", rows, "2026-11-08T00:00:00+00:00")
        metrics.record_popular(history, "referrers", [], "2026-11-08T01:00:00+00:00")
        snapshots = history["popular_traffic"]["referrers"]
        self.assertEqual(list(snapshots.values()), [rows, rows, []])
        with self.assertRaises(ValueError):
            metrics.record_popular(history, "referrers", None, "2026-11-08T02:00:00+00:00")
        self.assertEqual(list(snapshots.values()), [rows, rows, []])

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
        self.assertEqual(data['traffic_unavailable'], ['views', 'clones', 'referrers', 'paths'])
        self.assertEqual(history['views'], old['views'])

    def test_remote_link_activation_is_all_or_nothing(self):
        original = '![one](assets/project-metrics/overview.svg) ![two](assets/project-metrics/stars.svg)'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'README.md'
            path.write_text(original)
            with patch.object(metrics, 'urlopen', side_effect=[io.BytesIO(b'<svg/>'), OSError('404')]):
                with self.assertRaises(OSError):
                    metrics.activate_remote_links(path)
            self.assertEqual(path.read_text(), original)
            with patch.object(metrics, 'urlopen', side_effect=lambda *a, **k: io.BytesIO(b'<svg/>')):
                self.assertEqual(metrics.activate_remote_links(path), 2)
            self.assertNotIn('](assets/', path.read_text())

    def test_invalid_published_asset_never_switches_readme(self):
        original = '![one](assets/project-metrics/overview.svg)'
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'README.md'
            path.write_text(original)
            with patch.object(metrics, 'urlopen', return_value=io.BytesIO(b'<html>not found</html>')):
                with self.assertRaises(ValueError):
                    metrics.activate_remote_links(path)
            self.assertEqual(path.read_text(), original)

    def test_dashboard_escapes_embedded_public_metadata(self):
        page = metrics.dashboard({'name': '</script><script>alert(1)</script>'})
        self.assertNotIn('</script><script>alert(1)', page)
        self.assertIn('\\u003c/script', page)

    def test_old_snapshot_has_unknown_maintenance_not_fake_zeros(self):
        result = metrics.maintenance_heatmap({'collected_at': '2026-11-02T00:00:00Z'})
        self.assertIn('不以零代替未知', result)

    def test_overview_has_both_download_columns(self):
        snapshot = json.loads((metrics.ROOT/'assets/project-metrics/snapshot.json').read_text())
        result = metrics.overview(snapshot)
        self.assertIn('当前包下载', result)
        self.assertIn('全部版本下载', result)
        self.assertIn("未采集", result)
        self.assertNotIn("数学当前仅数学三", result)


if __name__ == "__main__":
    unittest.main()
