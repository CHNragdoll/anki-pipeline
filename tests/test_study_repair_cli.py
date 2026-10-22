"""Exact externally pinned global repair scope, without a Node producer."""
import hashlib
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled_preparation as preparation
from anki_pipeline.study_compiled_build import CompiledBuild
from anki_pipeline.study_compiled_resume import _Receipts

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/derive_study_complete_web_batch.py'
spec = importlib.util.spec_from_file_location('repair_cli', SCRIPT)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class Plans(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / 'new-delivery'
        self.output.mkdir()
        (self.output / '.build').mkdir()
        self.receipts = _Receipts()

    def row(self, identity):
        return {'identity': identity, 'base_artifact': {'path': 'evidence/base.json', 'sha256': '1' * 64},
                'artifact': {'path': 'evidence/current.json', 'sha256': '2' * 64}}

    def plan(self, rows):
        value = {'schema': 'study-compiled-repair-plan.v1', 'sources': preparation.source_pins(),
                 'dependencies': CompiledBuild._dependencies(), 'changed': rows}
        path = self.root / 'global-plan.json'
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}

    def book(self, name, book_id, ids):
        root = self.output / name
        root.mkdir()
        catalog = self.root / (name + '.catalog.json')
        catalog.write_text(json.dumps({'book_id': book_id, 'cards': [{'id': key} for key in ids]}))
        (root / 'catalog.json').symlink_to(catalog)
        return self.output / '.build' / name

    def test_per_book_exact_partition_and_all_book_close_required(self):
        plans = cli.RepairPlans(self.plan([self.row('english:a'), self.row('math:b')]), self.receipts)
        first = plans.book(self.book('web1', 'english', ['a', 'unchanged']))
        second = plans.book(self.book('web2', 'math', ['b']))
        self.assertEqual([row['identity'] for row in json.loads(Path(first['path']).read_bytes())['changed']], ['english:a'])
        self.assertEqual([row['identity'] for row in json.loads(Path(second['path']).read_bytes())['changed']], ['math:b'])
        with self.assertRaisesRegex(ValueError, 'completely processed'):
            plans.check()
        plans.reports.extend([{'complete': True}, {'complete': True}])
        plans.check()

    def test_unknown_identity_not_silently_ignored(self):
        plans = cli.RepairPlans(self.plan([self.row('missing:x')]), self.receipts)
        plans.book(self.book('web1', 'english', ['a']))
        plans.reports.append({'complete': True})
        with self.assertRaisesRegex(ValueError, 'completely processed'):
            plans.check()

    def test_duplicate_identity_and_wrong_external_pin_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unique'):
            cli.RepairPlans(self.plan([self.row('english:a')] * 2), self.receipts)
        descriptor = self.plan([])
        descriptor['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA'):
            cli.RepairPlans(descriptor, _Receipts())

    def test_duplicate_json_schema_or_changed_keys_are_rejected(self):
        descriptor = self.plan([])
        original = Path(descriptor['path']).read_bytes()
        for prefix in (b'"schema":"not-approved",', b'"changed":[{}],'):
            raw = b'{' + prefix + original[1:]
            Path(descriptor['path']).write_bytes(raw)
            descriptor['sha256'] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                cli.RepairPlans(descriptor, _Receipts())

    def test_subset_plan_change_and_duplicate_book_rejected(self):
        plans = cli.RepairPlans(self.plan([]), self.receipts)
        directory = self.book('web1', 'english', ['a'])
        descriptor = plans.book(directory)
        with self.assertRaisesRegex(ValueError, 'duplicate repair book'):
            plans.book(directory)
        Path(descriptor['path']).write_text('changed')
        plans.reports.append({'complete': True})
        with self.assertRaisesRegex(ValueError, 'SHA'):
            plans.check()

    def test_prepare_and_unpaired_flags_fail_before_opening_any_source(self):
        base = ['derive', 'prepare', '--generator', '/not-opened/SOURCE.json',
                '--generator-sha256', '0' * 64, '--source', '/not-opened/parent',
                '--source-complete-sha256', '1' * 64, '--output', '/not-created/output',
                '--base-url', 'https://study.test/']
        for flags, message in ((['--repair-plan', '/not-opened/plan'], 'must be paired'),
                (['--repair-plan', '/not-opened/plan', '--repair-plan-sha256', '2' * 64],
                 'prepare cannot start')):
            stderr = io.StringIO()
            with patch.object(cli.sys, 'argv', base + flags), contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as failure:
                    cli.main()
            self.assertEqual(failure.exception.code, 2)
            self.assertIn(message, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
