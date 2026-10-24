"""Bounded first-publication receipts for newly owned, unreceipted outputs.

The caller must have just created the private directory and file, still own the
directory FD, and know the SHA from the bytes it wrote. An ordinary FD does not
prove that history: this function must never be used to rebaseline an input or
an output which already has a receipt. It writes no bytes, flags or xattrs.

macOS may finish registering a new document after its writer has closed. Only
this initial publication window permits ctime/flags to settle. The returned
receipt has the ordinary complete six-field identity; every subsequent check
must use the existing strict reader. This is not an OS registration barrier.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import time

QUIET_SECONDS = 0.5
DEADLINE_SECONDS = 2.0
POLL_SECONDS = 0.025
MAX_BYTES = 256 * 1024 * 1024
_HASH = re.compile('[a-f0-9]{64}')


def _five(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)


def _six(value):
    return list(_five(value)) + [value.st_ctime_ns]


def _metadata(value):
    return (*_five(value), value.st_ctime_ns, getattr(value, 'st_flags', 0),
            value.st_uid, value.st_gid, value.st_nlink)


def _directory_identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)


def owned_output_receipts(directory, directory_fd, outputs, *, limit=MAX_BYTES,
                          prepare_admission=None):
    """Return a basename-to-first-receipt map after one shared quiet window.

    ``directory_fd`` is the caller's still-open, newly created 0700 directory.
    ``outputs`` maps up to 256 newly owned regular basenames to external SHA
    pins of the bytes written by that caller, never digests first obtained from
    the candidate files. Each file must have one hard link. The caller retains
    its FD; this function duplicates it and closes only its own descriptors.
    A timeout or any identity/content mismatch leaves the output untouched.

    Optional ``prepare_admission(initial_receipts)`` runs after all files are
    open and inspected, before the quiet window. It must return a callable
    ``commit(final_receipts)``. The initial map is only for exclusion/preparation,
    not admission: its ctime is not final and the bytes have not yet been hashed.
    Commit runs once after final authentication, while all FDs are still held.
    Both callbacks must be trusted caller code; commit is in-memory only and
    must not mutate receipts or perform I/O. Its error aborts without retry;
    the caller is responsible for atomicity of its own memory update. Callback
    time counts against the same deadline; no callback is an OS metadata fence.
    """
    directory = Path(directory)
    if (not directory.is_absolute() or type(directory_fd) is not int or directory_fd < 0
            or type(outputs) is not dict or not 1 <= len(outputs) <= 256
            or type(limit) is not int or not 0 <= limit <= MAX_BYTES
            or prepare_admission is not None and not callable(prepare_admission)):
        raise ValueError('exact new owned output directory, basename, SHA and byte limit required')
    outputs = outputs.copy()
    for filename, expected in outputs.items():
        if (type(filename) is not str or filename in {'', '.', '..'}
                or '/' in filename or '\\' in filename or '\x00' in filename
                or type(expected) is not str or not _HASH.fullmatch(expected)):
            raise ValueError('exact new owned output basename and external SHA required')
    if not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('no-follow owned output publication is unavailable')
    began = time.monotonic()

    def remaining():
        available = DEADLINE_SECONDS - (time.monotonic() - began)
        if available <= 0:
            raise TimeoutError('owned output publication did not settle within two seconds')
        return available

    held_directory = os.dup(directory_fd)
    files = {}
    try:
        initial_directory = os.fstat(held_directory)
        owner = os.geteuid()
        if (not stat.S_ISDIR(initial_directory.st_mode)
                or stat.S_IMODE(initial_directory.st_mode) != 0o700
                or initial_directory.st_uid != owner):
            raise ValueError('new owned output root must be a private 0700 directory')
        directory_identity = _directory_identity(initial_directory)

        def root_check():
            remaining()
            held, named = os.fstat(held_directory), directory.lstat()
            if (_directory_identity(held) != directory_identity
                    or _directory_identity(named) != directory_identity
                    or not stat.S_ISDIR(named.st_mode)):
                raise ValueError('owned output directory FD/path ownership changed')

        root_check()
        for filename, expected in outputs.items():
            output_fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=held_directory)
            # Register the descriptor before validation so every error closes it.
            files[filename] = {'fd': output_fd, 'expected': expected}
            initial = os.fstat(output_fd)
            if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                    or initial.st_uid != owner or initial.st_size > limit):
                raise ValueError('new owned output must be a bounded single-link regular file')
            files[filename].update(fixed=_five(initial), owner=(initial.st_uid, initial.st_gid))

        def inspect():
            root_check()
            values, coherent = {}, True
            for filename, item in files.items():
                before = os.fstat(item['fd'])
                named = os.stat(filename, dir_fd=held_directory, follow_symlinks=False)
                after = os.fstat(item['fd'])
                for value in (before, named, after):
                    if (_five(value) != item['fixed'] or not stat.S_ISREG(value.st_mode)
                            or value.st_nlink != 1 or (value.st_uid, value.st_gid) != item['owner']):
                        raise ValueError('owned output fixed identity, bytes metadata or owner changed')
                coherent = coherent and _metadata(before) == _metadata(named) == _metadata(after)
                values[filename] = after
            root_check()
            return values, coherent

        def digest():
            for item in files.values():
                total, result = 0, hashlib.sha256()
                while True:
                    remaining()
                    raw = os.pread(item['fd'], min(1024 * 1024, limit + 1 - total), total)
                    if not raw:
                        break
                    total += len(raw)
                    if total > limit:
                        raise ValueError('owned output exceeded its byte limit')
                    result.update(raw)
                remaining()
                if total != item['fixed'][3] or result.hexdigest() != item['expected']:
                    raise ValueError('owned output bytes differ from the external SHA')

        def metadata(values):
            return {name: _metadata(value) for name, value in values.items()}

        def receipts(values):
            return {name: {'path': str((directory / name).absolute()),
                           'bytes': files[name]['fixed'][3],
                           'sha256': files[name]['expected'], 'six': _six(value)}
                    for name, value in values.items()}

        initial_values, _ = inspect()
        commit = None
        if prepare_admission is not None:
            commit = prepare_admission(receipts(initial_values))
            if not callable(commit):
                raise TypeError('owned output admission preparation must return a commit callable')
            remaining()
        digest()  # Authenticate actual written bytes before accepting any settling.
        current, coherent = inspect()
        quiet_metadata = metadata(current)
        quiet_since = time.monotonic() if coherent else None
        while True:
            now = time.monotonic()
            remaining()
            if coherent and quiet_since is not None and now - quiet_since >= QUIET_SECONDS:
                tail_before = metadata(current)
                digest()
                tail, tail_coherent = inspect()
                if tail_coherent and metadata(tail) == tail_before:
                    final = receipts(tail)
                    if commit is not None:
                        remaining()
                        commit(final)
                        remaining()
                    return final
                # A ctime/flags update during the final full hash starts another
                # quiet interval, within the same original deadline.
                current, coherent = tail, tail_coherent
                quiet_metadata = metadata(tail)
                quiet_since = time.monotonic() if coherent else None
            time.sleep(min(POLL_SECONDS, remaining()))
            current, coherent = inspect()
            current_metadata = metadata(current)
            if not coherent or current_metadata != quiet_metadata:
                quiet_metadata = current_metadata
                quiet_since = time.monotonic() if coherent else None
            elif quiet_since is None:
                quiet_since = time.monotonic()
    finally:
        for item in files.values():
            os.close(item['fd'])
        os.close(held_directory)


def owned_output_receipt(directory, directory_fd, filename, expected_sha256, *, limit=MAX_BYTES,
                         prepare_admission=None):
    """Single-file convenience with the same strict new-output preconditions."""
    return owned_output_receipts(directory, directory_fd, {filename: expected_sha256},
                                 limit=limit, prepare_admission=prepare_admission)[filename]
