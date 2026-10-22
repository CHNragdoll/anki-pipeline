"""Actual scheduler adapter lifecycle contracts; no Node producer."""
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from anki_pipeline import study_compiled_build as build
HERE = Path(__file__).resolve().parent
ORIGINAL = build.CompiledBuild
ORIGINAL_DEPENDENCIES = ORIGINAL._dependencies()
from anki_pipeline.study_compiled_schedule import StageSeparatedBuild
BUILD=StageSeparatedBuild

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events, self.workers = [], []
        owner = self
        class Worker:
            def __init__(self, log, **options):
                self.number = len(owner.workers) + 1
                self.log, self.options = Path(log), options
                with self.log.open('xb') as stream:
                    stream.write(b'owned worker fixture')
                self.broken, self.ended, self.fail_close = False, False, False
                self.process = types.SimpleNamespace(poll=lambda: 0 if self.ended else None)
                owner.workers.append(self)
                owner.events.append(('new', self.number))
            def run(self, operation, request, output):
                if self.broken or self.ended:
                    raise RuntimeError('no automatic restart')
                if operation not in {'semantic', 'profile'}:
                    raise ValueError('unknown operation')
                owner.events.append(('run', self.number, operation))
                return {'operation': operation}, {'operation': operation}
            def close(self):
                owner.events.append(('close', self.number))
                if self.fail_close:
                    raise RuntimeError('owned worker close failed')
                self.ended = True
        self.patch = patch.object(build, 'BuildWorker', Worker)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_same_stage_reuses_but_switch_waits_close_before_new(self):
        with BUILD(self.root / 'build', node='/owned/node', heap_mb=4096) as context:
            context._run('semantic', 'request', self.root / 'one')
            context._run('semantic', 'request', self.root / 'two')
            self.assertEqual(len(self.workers), 1)
            context._run('profile', 'request', self.root / 'three')
            self.assertEqual(self.events, [('new', 1), ('run', 1, 'semantic'), ('run', 1, 'semantic'),
                                           ('close', 1), ('new', 2), ('run', 2, 'profile')])
            self.assertTrue(self.workers[0].ended)
            self.assertEqual(self.workers[1].options, {'node': '/owned/node', 'heap_mb': 4096})

    def test_repeated_switches_use_distinct_logs_and_one_live_worker(self):
        with BUILD(self.root / 'build') as context:
            for operation in ('semantic', 'profile', 'semantic', 'profile'):
                context._run(operation, 'request', self.root / operation)
                self.assertEqual(sum(not worker.ended for worker in self.workers), 1)
            self.assertEqual([worker.log.name for worker in self.workers],
                             ['worker.log', 'worker-2.log', 'worker-3.log', 'worker-4.log'])
        self.assertTrue(all(worker.ended for worker in self.workers))

    def test_broken_or_dead_worker_is_never_replaced(self):
        for name in ('broken', 'ended'):
            with self.subTest(name=name), BUILD(self.root / name) as context:
                context._run('semantic', 'request', self.root / 'one')
                worker = context.worker
                setattr(worker, name, True)
                count = len(self.workers)
                with self.assertRaisesRegex(RuntimeError, 'no automatic restart'):
                    context._run('profile', 'request', self.root / 'never')
                self.assertIs(context.worker, worker)
                self.assertEqual(len(self.workers), count)

    def test_failed_close_does_not_start_next_stage(self):
        with BUILD(self.root / 'build') as context:
            context._run('semantic', 'request', self.root / 'one')
            original = context.worker
            original.fail_close = True
            try:
                with self.assertRaisesRegex(RuntimeError, 'close failed'):
                    context._run('profile', 'request', self.root / 'never')
                self.assertIs(context.worker, original)
                self.assertEqual(len(self.workers), 1)
            finally:
                original.fail_close = False

    def test_unknown_operation_does_not_retire_valid_worker(self):
        with BUILD(self.root / 'build') as context:
            context._run('semantic', 'request', self.root / 'one')
            original = context.worker
            with self.assertRaisesRegex(ValueError, 'unknown'):
                context._run('unknown', 'request', self.root / 'never')
            self.assertIs(context.worker, original)
            self.assertFalse(original.ended)
            self.assertEqual(len(self.workers), 1)


    def test_producer_key_and_semantic_publish_methods_are_unchanged(self):
        self.assertEqual(BUILD._dependencies(), ORIGINAL_DEPENDENCIES)
        self.assertIs(BUILD.build, ORIGINAL.build)
        self.assertIs(BUILD._publish, ORIGINAL._publish)
        self.assertIs(BUILD._qualify_completed_semantic, ORIGINAL._qualify_completed_semantic)
        key = {'identity': 'subject:card', 'wrapper': {'path': 'cards/source.html', 'sha256': 'a' * 64},
               'artifact': {'path': 'evidence/prepared.json', 'sha256': 'b' * 64},
               'source_url': 'https://study.test/book/index.html', 'policy': {'inline': [], 'external': {}},
               'dependencies': ORIGINAL_DEPENDENCIES}
        expected = build._sha(build._json(key))
        key['dependencies'] = BUILD._dependencies()
        self.assertEqual(build._sha(build._json(key)), expected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
