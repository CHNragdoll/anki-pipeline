from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.configure_preview_service import (
    LABEL, configure, responsive_configuration, rollback,
)


class PreviewServiceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "bookshelf.plist"
        self.receipt = self.root / "receipt.json"
        self.value = {"Label": LABEL, "ProcessType": "Background",
                      "ProgramArguments": ["/existing/python", "-u", "/existing/server.py"],
                      "EnvironmentVariables": {"WEB_STUDY_PORT": "8771", "WEB_STUDY_DB": "/private/progress.sqlite3"},
                      "WorkingDirectory": "/existing", "KeepAlive": True}
        self.raw = plistlib.dumps(self.value)
        self.path.write_bytes(self.raw)
        self.path.chmod(0o600)

    def test_only_scheduling_class_changes(self):
        actual = plistlib.loads(responsive_configuration(self.raw))
        expected = {**self.value, "ProcessType": "Interactive"}
        self.assertEqual(actual, expected)
        self.assertEqual(responsive_configuration(plistlib.dumps(actual)), plistlib.dumps(actual))

    def test_rejects_other_services_and_unexpected_policies(self):
        for value in ({**self.value, "Label": "other"}, {**self.value, "ProcessType": "Standard"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                responsive_configuration(plistlib.dumps(value))

    def test_configuration_backup_and_rollback_are_exact(self):
        result = configure(self.path, self.receipt)
        self.assertTrue(result["changed"])
        self.assertEqual(Path(result["backup"]).read_bytes(), self.raw)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(rollback(self.receipt)["restored"])
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_rollback_preserves_later_user_edits(self):
        configure(self.path, self.receipt)
        self.path.write_bytes(b"later user change")
        with self.assertRaisesRegex(ValueError, "subsequently edited"):
            rollback(self.receipt)
        self.assertEqual(self.path.read_bytes(), b"later user change")

    def test_existing_receipt_is_not_overwritten(self):
        self.receipt.write_text("keep")
        with self.assertRaises(FileExistsError):
            configure(self.path, self.receipt)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(self.receipt.read_text(), "keep")

    def test_failed_reload_restores_original_configuration(self):
        with patch("scripts.configure_preview_service.runtime_preflight"), \
                patch("scripts.configure_preview_service.subprocess.run") as run:
            run.side_effect = [None, subprocess.CalledProcessError(1, "bootstrap"), None]
            with self.assertRaises(subprocess.CalledProcessError):
                configure(self.path, self.receipt, reload=True)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(run.call_args_list[0].args[0][1], "bootout")
        self.assertEqual(run.call_args_list[1].args[0][1], "bootstrap")

    def test_missing_runtime_is_detected_before_configuration_or_service_changes(self):
        with patch("scripts.configure_preview_service.runtime_preflight", side_effect=RuntimeError("missing dependency")), \
                patch("scripts.configure_preview_service.subprocess.run") as run:
            with self.assertRaisesRegex(RuntimeError, "missing dependency"):
                configure(self.path, self.receipt, reload=True)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertFalse(self.receipt.exists())
        run.assert_not_called()

    def test_failed_bootstrap_preserves_configuration_edited_during_reload(self):
        later = plistlib.dumps({**self.value, "WorkingDirectory": "/later-user-choice"})

        def launchctl(arguments, **kwargs):
            if arguments[1] == "bootstrap":
                self.path.write_bytes(later)
                raise subprocess.CalledProcessError(1, arguments)

        with patch("scripts.configure_preview_service.runtime_preflight"), \
                patch("scripts.configure_preview_service.subprocess.run", side_effect=launchctl) as run:
            with self.assertRaisesRegex(RuntimeError, "subsequently edited"):
                configure(self.path, self.receipt, reload=True)
        self.assertEqual(self.path.read_bytes(), later)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(self.receipt.exists())


if __name__ == "__main__":
    unittest.main()
