"""Actual scheduler adapter lifecycle contracts; no Node producer."""
import os
import ast
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from anki_pipeline import study_compiled_build as build
from anki_pipeline import study_compiled_schedule as schedule
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

    def owned_process(self, worker):
        process = Mock(spec=schedule.subprocess.Popen)
        process.pid = 424242
        process.poll.return_value = None
        worker.process = process

    def test_default_never_queries_rss_or_reuses_across_stages(self):
        with BUILD(self.root / 'default') as context:
            context._run('semantic', 'request', self.root / 'one')
            self.owned_process(context.worker)
            with patch.object(schedule.subprocess, 'run') as read:
                context._run('profile', 'request', self.root / 'two')
            read.assert_not_called()
            self.assertEqual(context.worker_count, 2)

    def test_opt_in_reuses_low_rss_across_both_stage_directions(self):
        measured = types.SimpleNamespace(returncode=0, stdout=' 327680\n', stderr='')
        with BUILD(self.root / 'low', reuse_small_workers=True) as context:
            context._run('semantic', 'request', self.root / 'one')
            self.owned_process(context.worker)
            with patch.object(schedule.subprocess, 'run', return_value=measured) as read:
                context._run('profile', 'request', self.root / 'two')
                context._run('semantic', 'request', self.root / 'three')
            self.assertEqual(context.worker_count, 1)
            self.assertEqual(context.worker_operation, 'semantic')
            self.assertEqual(read.call_count, 2)
            self.assertEqual(read.call_args.args[0], ['/bin/ps', '-o', 'rss=', '-p', '424242'])
            self.assertEqual(self.workers[0].options['heap_mb'], 4096)

    def test_high_or_unknown_rss_keeps_normal_retirement(self):
        cases = [(0, '524288\n', ''), (0, '800000\n', ''), (1, '', ''),
                 (0, '', ''), (0, '0\n', ''), (0, '-1\n', ''),
                 (0, '12\n13\n', ''), (0, '١٢\n', ''), (0, '100\n', 'warning')]
        for i, (code, stdout, stderr) in enumerate(cases):
            with self.subTest(i=i), BUILD(self.root / ('unknown-' + str(i)), reuse_small_workers=True) as context:
                context._run('semantic', 'request', self.root / 'one')
                previous = context.worker
                self.owned_process(previous)
                measured = types.SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)
                with patch.object(schedule.subprocess, 'run', return_value=measured):
                    context._run('profile', 'request', self.root / 'two')
                self.assertTrue(previous.ended)
                self.assertEqual(context.worker_count, 2)

    def test_rss_measurement_failure_or_non_popen_retires(self):
        for i, error in enumerate((OSError('ps unavailable'), schedule.subprocess.TimeoutExpired('ps', 1))):
            with self.subTest(error=error), BUILD(self.root / ('failed-' + str(i)), reuse_small_workers=True) as context:
                context._run('semantic', 'request', self.root / 'one')
                self.owned_process(context.worker)
                with patch.object(schedule.subprocess, 'run', side_effect=error):
                    context._run('profile', 'request', self.root / 'two')
                self.assertEqual(context.worker_count, 2)
        with BUILD(self.root / 'unowned', reuse_small_workers=True) as context:
            context._run('semantic', 'request', self.root / 'one')
            with patch.object(schedule.subprocess, 'run') as read:
                context._run('profile', 'request', self.root / 'two')
            read.assert_not_called()
            self.assertEqual(context.worker_count, 2)

    def test_opt_in_broken_or_exited_worker_is_not_replaced(self):
        for name in ('broken', 'exited'):
            with self.subTest(name=name), BUILD(self.root / name, reuse_small_workers=True) as context:
                context._run('semantic', 'request', self.root / 'one')
                self.owned_process(context.worker)
                if name == 'broken': context.worker.broken = True
                else: context.worker.process.poll.return_value = 1
                with patch.object(schedule.subprocess, 'run') as read:
                    with self.assertRaisesRegex(RuntimeError, 'no automatic restart'):
                        context._run('profile', 'request', self.root / 'two')
                read.assert_not_called()
                self.assertEqual(context.worker_count, 1)

    def test_failed_operation_is_never_reused_as_success(self):
        with BUILD(self.root / 'operation-failed', reuse_small_workers=True) as context:
            context._run('semantic', 'request', self.root / 'one')
            previous = context.worker
            self.owned_process(previous)
            measured = types.SimpleNamespace(returncode=0, stdout='100\n', stderr='')
            with patch.object(schedule.subprocess, 'run', return_value=measured):
                with patch.object(previous, 'run', side_effect=ValueError('producer failed')):
                    with self.assertRaisesRegex(ValueError, 'producer failed'):
                        context._run('profile', 'request', self.root / 'two')
                self.assertEqual(context.worker_count, 1)
                context._run('semantic', 'request', self.root / 'three')
            self.assertTrue(previous.ended)
            self.assertEqual(context.worker_count, 2)

    def test_web_common_builder_enables_one_uniform_opt_in(self):
        module = ast.parse((HERE.parent / 'anki_pipeline/study_catalog_export.py').read_text())
        web = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == '_web')
        calls = [node for node in ast.walk(web) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'CompiledBuild']
        self.assertEqual(len(calls), 1)
        self.assertEqual([(k.arg, ast.literal_eval(k.value)) for k in calls[0].keywords],
                         [('reuse_small_workers', True)])


if __name__ == '__main__':
    unittest.main(verbosity=2)
