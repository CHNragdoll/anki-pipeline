"""Real own-temp files, injected clock only; no document flags are written."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from anki_pipeline import study_catalog_web_delivery as delivery
from anki_pipeline import study_owned_output_publication as publication


class Clock:
    def __init__(self):
        self.now = 0.0
        self.events = []

    def at(self, when, callback):
        self.events.append((when, callback))
        self.events.sort(key=lambda event: event[0])

    def sleep(self, duration):
        until = self.now + duration
        while self.events and self.events[0][0] <= until:
            self.now, callback = self.events.pop(0)
            callback()
        self.now = until


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.parent = Path(temporary.name)
        self.root = self.parent / 'owned'
        self.root.mkdir(mode=0o700)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.addCleanup(os.close, self.fd)
        self.raw = b'new known output: \xe5\x8e\x9f\xe6\x96\x87\x00'
        self.path = self.root / 'one.json'
        self.path.write_bytes(self.raw)
        self.path.chmod(0o600)
        self.pin = hashlib.sha256(self.raw).hexdigest()
        self.clock = Clock()

    @contextmanager
    def timed(self):
        with patch.object(publication.time, 'monotonic', side_effect=lambda: self.clock.now), \
                patch.object(publication.time, 'sleep', side_effect=self.clock.sleep):
            yield

    def run_receipt(self):
        with self.timed():
            return publication.owned_output_receipt(self.root, self.fd, self.path.name, self.pin)

    def ctime_event(self):
        before = self.path.stat()
        os.chmod(self.path, stat.S_IMODE(before.st_mode))
        after = self.path.stat()
        self.assertEqual(publication._five(before), publication._five(after))
        self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)

    def test_single_output_waits_and_returns_original_complete_receipt_shape(self):
        result = self.run_receipt()
        self.assertGreaterEqual(self.clock.now, 0.5)
        self.assertLess(self.clock.now, 0.6)
        _, expected = delivery._read(self.path, self.pin, keep=False)
        self.assertEqual(result, expected)
        os.fstat(self.fd)  # Caller still owns the original directory descriptor.

    def test_real_clock_small_file_publication_preserves_bytes_and_flags(self):
        before = self.path.stat()
        began = time.monotonic()
        receipt = publication.owned_output_receipt(self.root, self.fd, self.path.name, self.pin)
        elapsed = time.monotonic() - began
        self.assertGreaterEqual(elapsed, publication.QUIET_SECONDS)
        self.assertLess(elapsed, publication.DEADLINE_SECONDS)
        self.assertEqual(self.path.read_bytes(), self.raw)
        self.assertEqual(publication._metadata(self.path.stat()), publication._metadata(before))
        delivery._again(receipt)

    def test_batch_has_one_shared_quiet_window_not_one_delay_per_file(self):
        second = self.root / 'two.json'
        second.write_bytes(b'second exact bytes')
        pins = {self.path.name: self.pin, second.name: hashlib.sha256(second.read_bytes()).hexdigest()}
        self.clock.at(0.2, self.ctime_event)
        with self.timed():
            result = publication.owned_output_receipts(self.root, self.fd, pins)
        self.assertEqual(set(result), set(pins))
        self.assertGreaterEqual(self.clock.now, 0.7)
        self.assertLess(self.clock.now, 0.8)
        for receipt in result.values():
            delivery._again(receipt)

    def test_ctime_only_publication_waits_for_continuous_quiet_before_first_receipt(self):
        # The original strict reader is intentionally not changed or weakened.
        _, early = delivery._read(self.path, self.pin, keep=False)
        self.ctime_event()
        with self.assertRaisesRegex(ValueError, 'changed'):
            delivery._again(early)
        self.clock.at(0.125, self.ctime_event)
        self.clock.at(0.375, self.ctime_event)
        receipt = self.run_receipt()
        self.assertGreaterEqual(self.clock.now, 0.875)
        delivery._again(receipt)

    def test_flags_changes_also_restart_the_quiet_window(self):
        original = publication._metadata
        phase = [0]
        self.clock.at(0.3, lambda: phase.__setitem__(0, 1))
        # Portable model of st_flags only; no xattr/chflags operation is used.
        def metadata(value):
            result = list(original(value))
            result[6] = phase[0]
            return tuple(result)
        with patch.object(publication, '_metadata', side_effect=metadata):
            self.run_receipt()
        self.assertGreaterEqual(self.clock.now, 0.8)

    def test_never_quiet_times_out_without_rebaselining_or_writing_content(self):
        for i in range(1, 20):
            self.clock.at(i / 10, self.ctime_event)
        with self.assertRaises(TimeoutError):
            self.run_receipt()
        self.assertLessEqual(self.clock.now, 2.0)
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_late_ctime_after_return_still_fails_original_six_guard(self):
        receipt = self.run_receipt()
        self.ctime_event()
        with self.assertRaisesRegex(ValueError, 'changed'):
            delivery._again(receipt)

    def test_body_or_first_five_changes_are_rejected_not_settled(self):
        for mutation in ('bytes', 'mode', 'mtime'):
            with self.subTest(mutation=mutation):
                old = self.path.stat()
                def change():
                    if mutation == 'bytes':
                        self.path.write_bytes(b'X' * len(self.raw))
                    elif mutation == 'mode':
                        self.path.chmod(0o400)
                    else:
                        os.utime(self.path, ns=(old.st_atime_ns, old.st_mtime_ns + 1000000))
                self.clock = Clock()
                self.clock.at(0.1, change)
                with self.assertRaisesRegex(ValueError, 'fixed identity'):
                    self.run_receipt()
                self.path.chmod(0o600)
                self.path.write_bytes(self.raw)

    def test_external_sha_rejects_body_change_even_when_mtime_is_restored(self):
        old = self.path.stat()
        def change():
            self.path.write_bytes(b'X' * len(self.raw))
            os.utime(self.path, ns=(old.st_atime_ns, old.st_mtime_ns))
        self.clock.at(0.1, change)
        with self.assertRaisesRegex(ValueError, 'external SHA'):
            self.run_receipt()

    def test_file_replacement_and_directory_retarget_are_rejected(self):
        def replace_file():
            self.path.rename(self.root / 'retained-original')
            self.path.write_bytes(self.raw)
            self.path.chmod(0o600)
        self.clock.at(0.1, replace_file)
        with self.assertRaisesRegex(ValueError, 'fixed identity'):
            self.run_receipt()
        self.clock = Clock()
        def replace_directory():
            self.root.rename(self.parent / 'retained-original-root')
            self.root.mkdir(mode=0o700)
            self.path.write_bytes(self.raw)
            self.path.chmod(0o600)
        self.clock.at(0.1, replace_directory)
        with self.assertRaisesRegex(ValueError, 'directory FD/path'):
            self.run_receipt()

    def test_symlink_hardlink_and_nonprivate_root_are_rejected(self):
        alias = self.root / 'alias.json'
        alias.symlink_to(self.path.name)
        with self.timed(), self.assertRaises(OSError):
            publication.owned_output_receipt(self.root, self.fd, alias.name, self.pin)
        alias.unlink()
        os.link(self.path, alias)
        with self.assertRaisesRegex(ValueError, 'single-link'):
            self.run_receipt()
        alias.unlink()
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            self.run_receipt()

    def test_tail_hash_metadata_change_restarts_quiet_not_adopts_latest_ctime(self):
        pread = os.pread
        count = [0]
        def read(*args):
            count[0] += 1
            if count[0] == 3:  # First read of the final hash, after initial EOF.
                self.ctime_event()
            return pread(*args)
        with patch.object(publication.os, 'pread', side_effect=read):
            receipt = self.run_receipt()
        self.assertGreaterEqual(self.clock.now, 1.0)
        delivery._again(receipt)

    def test_all_owned_descriptors_close_on_cancel_and_original_fd_stays_open(self):
        opened, duplicated = [], []
        real_open, real_dup = os.open, os.dup
        def record_open(*args, **kwargs):
            value = real_open(*args, **kwargs)
            opened.append(value)
            return value
        def record_dup(*args):
            value = real_dup(*args)
            duplicated.append(value)
            return value
        self.clock.at(0.1, lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        with patch.object(publication.os, 'open', side_effect=record_open), \
                patch.object(publication.os, 'dup', side_effect=record_dup):
            with self.assertRaises(KeyboardInterrupt):
                self.run_receipt()
        self.assertEqual(len(opened), 1)
        self.assertEqual(len(duplicated), 1)
        for descriptor in opened + duplicated:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        os.fstat(self.fd)

    def test_strict_external_pin_basename_and_deadline_include_full_hash(self):
        for filename, pin in (('../one.json', self.pin), ('one.json', '0' * 64),
                              ('one.json', self.pin.upper())):
            with self.subTest(filename=filename, pin=pin), self.timed(), self.assertRaises(ValueError):
                publication.owned_output_receipt(self.root, self.fd, filename, pin)
        pread = os.pread
        def slow_read(*args):
            self.clock.now += 2.1
            return pread(*args)
        with patch.object(publication.os, 'pread', side_effect=slow_read), self.assertRaises(TimeoutError):
            self.run_receipt()


if __name__ == '__main__':
    unittest.main()
