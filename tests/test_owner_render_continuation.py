"""A rendering repair cannot silently authorize another database or code file."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from scripts import patch_exam_usage_preview as patcher
from scripts import update_exam_usage_preview as preview


class OwnerRenderContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        driver = str(Path(patcher.__file__).resolve())
        backup = self.root / 'accepted-driver.py'
        backup.write_bytes(b'previous accepted driver bytes')
        old = {'file': driver, 'sha256': preview.file_sha(backup)}
        new = {'file': driver, 'sha256': preview.file_sha(driver)}
        self.request = {'code_pins': {'driver': old}}
        request_pin = self.pin('request.json', self.request)
        self.checkpoint = {'request': request_pin, 'code_pins': self.request['code_pins'],
            'run_id': 'a' * 64, 'database': {'file': '/certified/immutable.sqlite3',
                'sha256': 'b' * 64, 'stat': {'bytes': 42, 'inode': 5}}}
        self.checkpoint_pin = self.pin('checkpoint.json', self.checkpoint)
        self.payload = {'schema': patcher.RENDER_CONTINUATION_SCHEMA,
            'scope': 'native_existing_rows_projection_only', 'request': request_pin,
            'prepared_checkpoint': self.checkpoint_pin, 'run_id': self.checkpoint['run_id'],
            'database': self.checkpoint['database'], 'original_code_pins': self.request['code_pins'],
            'code_changes': [{'old': old, 'new': new,
                'backup': {'file': str(backup), 'sha256': old['sha256']}}],
            'proof_pins': [self.pin('independent-review.json', {'status': 'passed'})]}

    def pin(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload))
        return {'file': str(path), 'sha256': preview.file_sha(path)}

    def load(self, payload):
        return patcher._load_render_continuation(self.pin('continuation.json', payload),
            self.checkpoint_pin, self.checkpoint, self.request)

    def test_explicit_render_delta_keeps_original_request_and_checkpoint(self):
        original = deepcopy((self.request, self.checkpoint))
        continuation = self.load(self.payload)
        actual = patcher._render_code_pins(self.request, continuation)
        self.assertEqual(actual['driver'], self.payload['code_changes'][0]['new'])
        self.assertEqual((self.request, self.checkpoint), original)
        evidence = patcher._render_continuation_evidence(self.request, continuation)
        self.assertEqual(evidence['render_code_continuation']['original_code_pins'],
                         self.request['code_pins'])
        self.assertEqual(evidence['render_code_continuation']['actual_code_pins'], actual)

    def test_another_database_run_checkpoint_or_original_code_is_rejected(self):
        for key, value in [('run_id', 'c' * 64), ('database', {'file': '/other.sqlite3'}),
                           ('prepared_checkpoint', {'file': '/other.json', 'sha256': 'd' * 64}),
                           ('original_code_pins', {}), ('scope', 'prepare_another_database')]:
            invalid = deepcopy(self.payload); invalid[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.load(invalid)

    def test_unrelated_code_duplicate_change_or_missing_backup_is_rejected(self):
        for kind in ('unrelated', 'duplicate', 'backup', 'same_code', 'proof'):
            invalid = deepcopy(self.payload)
            change = invalid['code_changes'][0]
            if kind == 'unrelated':
                change['old']['file'] = change['new']['file'] = '/other/unsafe.py'
            elif kind == 'duplicate':
                invalid['code_changes'].append(deepcopy(change))
            elif kind == 'backup':
                change['backup']['sha256'] = 'e' * 64
            elif kind == 'same_code':
                change['new'] = deepcopy(change['old'])
            else:
                invalid['proof_pins'] = []
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.load(invalid)

    def test_approved_payload_and_new_code_are_rechecked_during_render(self):
        continuation = self.load(self.payload)
        invalid = deepcopy(continuation)
        invalid['payload']['code_changes'][0]['new']['sha256'] = 'e' * 64
        with self.assertRaises(ValueError):
            patcher._render_code_pins(self.request, invalid)
        Path(continuation['pin']['file']).write_text('{}')
        with self.assertRaises(ValueError):
            patcher._render_code_pins(self.request, continuation)


if __name__ == '__main__':
    unittest.main()
