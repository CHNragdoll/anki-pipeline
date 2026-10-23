"""Bounded metadata readers and separate producer/consumer authorities; no Node."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled_resume as resume

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location('result_index_cli', SCRIPTS / 'index_study_complete_results.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ReaderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def cache(self, raw):
        path = self.root / 'rows.jsonl'
        path.write_bytes(raw)
        index = self.root / 'index.json'
        data = packed({'schema': 'study-complete-result-cache.v1', 'completed_semantic': {},
            'files': [{'path': str(path), 'sha256': sha(raw), 'bytes': len(raw), 'assets': str(self.root)}]})
        index.write_bytes(data)
        return resume.ResultCache({'path': str(index), 'sha256': sha(data)})

    def row(self, count):
        return packed({'status': 'ok', 'identity': 'subject:one',
                       'result': {'mode': 'compiled', 'metadata': 'x' * count}}) + b'\n'

    def test_large_complete_row_retains_original_bytes_and_read_block_size(self):
        raw = self.row(252238)
        actual = resume.os.read
        sizes = []
        def read(fd, count):
            sizes.append(count)
            return actual(fd, count)
        with patch.object(resume.os, 'read', new=read), self.cache(raw) as cache:
            row, _ = cache.get('subject:one')
            self.assertEqual(packed(row) + b'\n', raw)
        self.assertIn(65536, sizes)
        self.assertLessEqual(max(sizes), 1024 * 1024)

    def test_one_mib_boundary_accepts_exact_rejects_one_extra_and_partial(self):
        raw = self.row(0)
        exact = self.row(1024 * 1024 - len(raw))
        self.assertEqual(len(exact), 1024 * 1024)
        with self.cache(exact) as cache:
            self.assertEqual(set(cache.rows), {'subject:one'})
        for bad in (exact[:-1] + b' \n', b'x' * (1024 * 1024 + 1)):
            with self.subTest(bytes=len(bad)), self.assertRaisesRegex(ValueError, 'row exceeds'):
                self.cache(bad)

    def test_duplicate_and_malformed_large_rows_are_rejected(self):
        row = self.row(100000)
        for raw, error in ((row + row, 'duplicate'), (b'{"pad":"' + b'x' * 100000 + b'",bad}\n', 'JSON|property|Expecting')):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                self.cache(raw)

    def test_file_limit_and_external_hash_are_still_strict(self):
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            resume._Log({'path': str(self.root / 'absent'), 'sha256': '0' * 64,
                         'bytes': 256 * 1024 * 1024 + 1, 'assets': str(self.root)})
        raw = self.row(100000)
        with self.cache(raw) as cache:
            cache.logs[0].descriptor['sha256'] = '0' * 64
            resume.os.lseek(cache.logs[0].fd, 0, 0)
            with self.assertRaisesRegex(ValueError, 'SHA/bytes'):
                list(cache.logs[0].rows())

    def test_same_bytes_replacement_reports_exact_failed_receipt(self):
        path = self.root / 'resource.js'
        raw = b'original resource'
        path.write_bytes(raw)
        receipts = resume._Receipts()
        receipts.read(path, sha(raw))
        expected = copy.deepcopy(receipts.items[str(path)])
        replacement = self.root / 'replacement.js'
        replacement.write_bytes(raw)
        os.replace(replacement, path)
        with self.assertRaises(ValueError) as failure:
            receipts.check()
        detail = getattr(failure.exception, 'receipt_difference', None)
        self.assertIsNotNone(detail)
        self.assertEqual(detail['expected'], expected)
        self.assertEqual(detail['actual']['path'], str(path))
        self.assertEqual(detail['actual']['sha256'], expected['sha256'])
        self.assertNotEqual(detail['actual']['six'], expected['six'])
        self.assertIn(str(path), str(failure.exception))

    def test_first_owned_admission_cannot_rebase_or_accept_late_identity_change(self):
        path = self.root / 'new.js'
        raw = b'new output'
        path.write_bytes(raw)
        _, ready = resume.delivery._read(path, sha(raw))
        receipts = resume._Receipts()
        receipts.admit_new_owned(ready)
        with self.assertRaisesRegex(ValueError, 'cannot reenter'):
            receipts.admit_new_owned(ready)
        replacement = self.root / 'replacement.js'
        replacement.write_bytes(raw)
        os.replace(replacement, path)
        with self.assertRaisesRegex(ValueError, 'after publication'):
            resume._Receipts().admit_new_owned(ready)
        with self.assertRaisesRegex(ValueError, 'resource changed'):
            receipts.check()


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.jobs = self.root / 'jobs'
        self.jobs.mkdir()
        self.names = ('anki_pipeline/study_compiled_resume.py', 'scripts/index_study_complete_results.py',
                      'anki_pipeline/study_compiled_build.py')
        self.old = self.make_source('producer', (b'old reader', b'old index', b'unchanged producer'))
        self.new = self.make_source('consumer', (b'new reader', b'new index', b'unchanged producer'))
        (self.jobs / 'SOURCE.json').write_bytes(self.old.read_bytes())

    def make_source(self, name, values):
        root = self.root / name
        root.mkdir()
        files = {}
        for name, raw in zip(self.names, values):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files[name] = {'sha256': sha(raw), 'bytes': len(raw)}
        source = root / 'SOURCE.json'
        source.write_bytes(packed({'schema': 'study-complete-frozen-builder.v1', 'source_root': str(root), 'files': files}))
        return source

    def authenticate(self, producer_sha=None, consumer_sha=None):
        with patch.object(cli, '__file__', str(self.new.parent / 'scripts/index_study_complete_results.py')):
            return cli.authorities(self.jobs, producer_sha or sha(self.old.read_bytes()), self.new,
                                   consumer_sha or sha(self.new.read_bytes()))

    def test_separate_authorities_accept_only_two_reader_differences(self):
        root, proof = self.authenticate()
        self.assertEqual(root, self.new.parent)
        self.assertEqual(proof['producer']['sha256'], sha(self.old.read_bytes()))
        self.assertEqual(proof['consumer']['sha256'], sha(self.new.read_bytes()))
        self.assertEqual(proof['changed_files'], list(self.names[:2]))

    def test_external_pins_required_and_both_authorities_rechecked(self):
        for which in ('producer', 'consumer'):
            with self.subTest(which=which), self.assertRaisesRegex(ValueError, 'SHA'):
                self.authenticate(**{which + '_sha': '0' * 64})
        self.authenticate()
        (self.old.parent / self.names[2]).write_bytes(b'later changed original dependency')
        with self.assertRaisesRegex(ValueError, 'SHA'):
            self.authenticate()

    def test_content_dependency_or_census_change_rejected_even_with_new_pin(self):
        for kind in ('dependency', 'census'):
            with self.subTest(kind=kind):
                original = self.new.read_bytes()
                value = json.loads(original)
                if kind == 'dependency':
                    path = self.new.parent / self.names[2]
                    path.write_bytes(b'changed producer')
                    value['files'][self.names[2]] = {'bytes': path.stat().st_size, 'sha256': sha(path.read_bytes())}
                else:
                    del value['files'][self.names[2]]
                self.new.write_bytes(packed(value))
                with self.assertRaisesRegex(ValueError, 'only the two|census'):
                    self.authenticate()
                self.new.write_bytes(original)
                (self.new.parent / self.names[2]).write_bytes(b'unchanged producer')

    def test_legacy_one_source_and_unpaired_consumer_inputs(self):
        root, proof = cli.authorities(self.jobs, sha(self.old.read_bytes()))
        self.assertEqual(root, self.old.parent)
        self.assertEqual(proof['producer'], proof['consumer'])
        for source, pin in ((self.new, None), (None, sha(self.new.read_bytes()))):
            with self.assertRaisesRegex(ValueError, 'paired'):
                cli.authorities(self.jobs, sha(self.old.read_bytes()), source, pin)


if __name__ == '__main__':
    unittest.main(verbosity=2)
