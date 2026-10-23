"""Real own-temp files, injected clock only; no document flags are written."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

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

    def test_batch_admission_prepares_before_quiet_commits_once_with_all_fds_still_held(self):
        second = self.root / 'two.json'
        second.write_bytes(b'second exact bytes')
        pins = {self.path.name: self.pin, second.name: hashlib.sha256(second.read_bytes()).hexdigest()}
        opened, events, committed = [], [], []
        original_open, original_pread = os.open, os.pread
        reads = [0]
        def track_open(*args, **kwargs):
            descriptor = original_open(*args, **kwargs)
            if 'dir_fd' in kwargs:
                opened.append(descriptor)
            return descriptor
        def tail_change(*args):
            reads[0] += 1
            if reads[0] == 5:  # Two initial full hashes, then first final read.
                events.append(('tail-ctime', self.clock.now))
                self.ctime_event()
            return original_pread(*args)
        def prepare(initial):
            events.append(('prepare', self.clock.now))
            self.assertEqual(set(initial), set(pins))
            self.assertEqual(len(opened), 2)
            for descriptor in opened:
                os.fstat(descriptor)
            self.assertLess(self.clock.now, publication.QUIET_SECONDS)
            initial.clear()  # The initial map is not the final result or state.
            def commit(final):
                events.append(('commit', self.clock.now))
                self.assertEqual(set(final), set(pins))
                for descriptor in opened:
                    os.fstat(descriptor)
                committed.append(final)
            return commit
        with self.timed(), patch.object(publication.os, 'open', side_effect=track_open), \
                patch.object(publication.os, 'pread', side_effect=tail_change):
            result = publication.owned_output_receipts(self.root, self.fd, pins,
                prepare_admission=prepare)
        self.assertEqual([name for name, _ in events], ['prepare', 'tail-ctime', 'commit'])
        self.assertGreaterEqual(events[-1][1] - events[-2][1], publication.QUIET_SECONDS)
        self.assertEqual(committed, [result])
        self.assertEqual(len(opened), 2)  # No post-return path reopen.
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)
        for receipt in result.values():
            delivery._again(receipt)

    def test_disallowed_changes_never_commit_admission(self):
        for kind in ('body', 'inode'):
            with self.subTest(kind=kind):
                self.clock = Clock()
                path = self.root / (kind + '.json')
                path.write_bytes(self.raw)
                committed = Mock()
                prepared = Mock(return_value=committed)
                def change():
                    if kind == 'body':
                        path.write_bytes(b'X' * len(self.raw))
                    else:
                        path.rename(self.root / 'retained-original-inode')
                        path.write_bytes(self.raw)
                self.clock.at(0.1, change)
                with self.timed(), self.assertRaisesRegex(ValueError, 'fixed identity'):
                    publication.owned_output_receipts(self.root, self.fd, {path.name: self.pin},
                        prepare_admission=prepared)
                prepared.assert_called_once()
                committed.assert_not_called()

    def test_timeout_cancel_and_prepare_failure_do_not_commit(self):
        for kind in ('timeout', 'cancel', 'prepare-error', 'prepare-timeout', 'bad-return'):
            with self.subTest(kind=kind):
                self.clock = Clock()
                committed = Mock()
                def prepare(initial):
                    if kind == 'prepare-error':
                        raise RuntimeError('prepare rejected existing identity')
                    if kind == 'prepare-timeout':
                        self.clock.now += 2.1
                    if kind == 'bad-return':
                        return None
                    return committed
                if kind == 'timeout':
                    for i in range(1, 20):
                        self.clock.at(i / 10, self.ctime_event)
                elif kind == 'cancel':
                    self.clock.at(0.1, lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
                expected = {'timeout': TimeoutError, 'cancel': KeyboardInterrupt,
                            'prepare-error': RuntimeError, 'prepare-timeout': TimeoutError,
                            'bad-return': TypeError}[kind]
                with self.timed(), self.assertRaises(expected):
                    publication.owned_output_receipts(self.root, self.fd, {self.path.name: self.pin},
                        prepare_admission=prepare)
                committed.assert_not_called()

    def test_single_forwards_admission_and_commit_errors_never_retry(self):
        committed = Mock(side_effect=RuntimeError('memory admission rejected'))
        prepared = Mock(return_value=committed)
        with self.timed(), self.assertRaisesRegex(RuntimeError, 'memory admission rejected'):
            publication.owned_output_receipt(self.root, self.fd, self.path.name, self.pin,
                prepare_admission=prepared)
        prepared.assert_called_once()
        committed.assert_called_once()
        self.assertGreaterEqual(self.clock.now, publication.QUIET_SECONDS)
        os.fstat(self.fd)


if __name__ == '__main__':
    unittest.main()
