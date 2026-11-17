import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import project_forks


class ForkArchiveTests(unittest.TestCase):
    timestamp = "2026-11-17T12:00:00+00:00"

    def raw_fork(self, key):
        return {"id": key, "full_name": f"fixture-{key}/repo",
                "owner": {"id": key + 100}, "created_at": self.timestamp}

    def test_same_total_retains_both_id_changes(self):
        with patch.object(project_forks, "api", side_effect=[
            [self.raw_fork(1), self.raw_fork(2)], {"forks_count": 2},
            [self.raw_fork(2), self.raw_fork(3)], {"forks_count": 2},
        ]):
            previous = project_forks.record_forks(project_forks.collect_forks(), None, self.timestamp)
            now = project_forks.record_forks(project_forks.collect_forks(), previous, self.timestamp)
        self.assertEqual([row["id"] for row in now["changes"]["added"]], [3])
        self.assertEqual([row["id"] for row in now["changes"]["removed"]], [1])
        self.assertEqual(now["changes"]["previous_count"], 2)

    def test_incomplete_page_does_not_generate_removals(self):
        with patch.object(project_forks, "api", side_effect=[
            [self.raw_fork(1)], {"forks_count": 2},
            [self.raw_fork(1), self.raw_fork(1)], {"forks_count": 2},
        ]):
            current = project_forks.collect_forks()
        self.assertIsNone(current)
        sample = project_forks.record_forks(current, {"forks": [{"id": 1}]}, self.timestamp)
        self.assertIsNone(sample["forks"])
        self.assertNotIn("changes", sample)

    def test_empty_complete_list_can_record_a_removal(self):
        with patch.object(project_forks, "api", side_effect=[[], {"forks_count": 0}]):
            current = project_forks.collect_forks()
        self.assertEqual(current, [])
        sample = project_forks.record_forks(
            current, {"collected_at": self.timestamp, "forks": [{"id": 1}]}, self.timestamp
        )
        self.assertEqual(sample["changes"]["removed"], [{"id": 1}])
