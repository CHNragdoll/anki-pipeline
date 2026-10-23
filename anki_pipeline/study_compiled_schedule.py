"""Common build scheduling only; unchanged original semantic/profile producers.

This adapter must be included in the caller's frozen generator/source manifest.
It is not a content transform and does not alter the producer capability key.
"""
import subprocess
from . import study_compiled_build as shared


class StageSeparatedBuild(shared.CompiledBuild):
    """Retire between stages unless an opted-in, successful worker is small."""
    def __init__(self, *args, reuse_small_workers=False, **kwargs):
        if type(reuse_small_workers) is not bool:
            raise ValueError('reuse_small_workers must be a boolean')
        super().__init__(*args, **kwargs)
        self.reuse_small_workers = reuse_small_workers
        self.worker_operation, self.worker_count, self.worker_succeeded = None, 0, False

    def _small_idle_worker(self):
        process = self.worker.process
        if not isinstance(process, subprocess.Popen):
            return False
        try:
            measured = subprocess.run(['/bin/ps', '-o', 'rss=', '-p', str(process.pid)],
                                      capture_output=True, text=True, timeout=1)
            value = measured.stdout.strip()
            return (measured.returncode == 0 and not measured.stderr and value.isascii()
                    and value.isdecimal() and 0 < int(value) * 1024 < 512 * 1024 * 1024)
        except (OSError, subprocess.SubprocessError, ValueError):
            return False

    def _run(self, operation, request, output):
        if operation not in {'semantic', 'profile'}:
            raise ValueError('unknown shared build operation')
        if self.worker is not None and operation != self.worker_operation:
            if self.worker.broken or self.worker.process.poll() is not None:
                raise RuntimeError('shared worker is no longer available; no automatic restart')
            if not (self.reuse_small_workers and self.worker_succeeded
                    and self._small_idle_worker()):
                self.close()
        if self.worker is None:
            self.worker_count += 1
            name = 'worker.log' if self.worker_count == 1 else 'worker-' + str(self.worker_count) + '.log'
            self.worker = shared.BuildWorker(self.store.root / name, node=self.node, heap_mb=self.heap_mb)
        self.worker_operation = operation
        self.worker_succeeded = False
        result = self.worker.run(operation, request, output)
        self.worker_succeeded = True
        return result

    def close(self):
        super().close()
        self.worker_operation = None
