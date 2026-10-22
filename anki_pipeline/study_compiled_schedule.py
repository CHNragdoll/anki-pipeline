"""Common build scheduling only; unchanged original semantic/profile producers.

This adapter must be included in the caller's frozen generator/source manifest.
It is not a content transform and does not alter the producer capability key.
"""
from . import study_compiled_build as shared


class StageSeparatedBuild(shared.CompiledBuild):
    """Retire the successful previous stage before allocating the next DOM heap."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_operation, self.worker_count = None, 0

    def _run(self, operation, request, output):
        if operation not in {'semantic', 'profile'}:
            raise ValueError('unknown shared build operation')
        if self.worker is not None and operation != self.worker_operation:
            if self.worker.broken or self.worker.process.poll() is not None:
                raise RuntimeError('shared worker is no longer available; no automatic restart')
            self.close()
        if self.worker is None:
            self.worker_count += 1
            name = 'worker.log' if self.worker_count == 1 else 'worker-' + str(self.worker_count) + '.log'
            self.worker = shared.BuildWorker(self.store.root / name, node=self.node, heap_mb=self.heap_mb)
            self.worker_operation = operation
        return self.worker.run(operation, request, output)

    def close(self):
        super().close()
        self.worker_operation = None
