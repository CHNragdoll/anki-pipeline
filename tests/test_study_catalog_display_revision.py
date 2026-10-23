import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline.study_catalog_display_revision import read_plan


class DisplayPlanTests(unittest.TestCase):
    def fixture(self, root):
        descriptors = {}
        for name in ('after', 'inverse', 'authority'):
            path = root / name
            raw = ('authenticated ' + name).encode()
            path.write_bytes(raw)
            descriptors[name] = {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest()}
        plan = {'schema': 'study-reviewed-display-repair.v1', 'reason': 'reviewed source exclusion',
                'fields': [{'book_id': 'fixture', 'source_card_id': 'stable',
                            'field': 'Examples', **descriptors}]}
        path = root / 'plan.json'
        path.write_text(json.dumps(plan))
        return path, hashlib.sha256(path.read_bytes()).hexdigest(), descriptors

    def test_replacement_after_authenticated_read_cannot_change_retained_payload(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path, pin, descriptors = self.fixture(root)
            plan = read_plan(path, pin)
            item = descriptors['after']
            original = Path(item['path']).read_bytes()
            replacement = root / 'replacement'
            replacement.write_bytes(b'unreviewed replacement')
            replacement.replace(item['path'])
            self.assertEqual(plan['_authenticated_bytes'][(item['path'], item['sha256'])], original)
            with self.assertRaisesRegex(ValueError, 'evidence changed'):
                read_plan(path, pin)

    def test_wrong_plan_pin_and_duplicate_native_binding_reject(self):
        with tempfile.TemporaryDirectory() as name:
            path, pin, _ = self.fixture(Path(name))
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                read_plan(path, '0' * 64)
            value = json.loads(path.read_text())
            value['fields'].append(value['fields'][0])
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                read_plan(path, hashlib.sha256(path.read_bytes()).hexdigest())


class HeldBackupTests(unittest.TestCase):
    def test_authenticated_fd_and_path_are_checked_while_held(self):
        from anki_pipeline import study_catalog_display_revision as repair
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); backup = root / 'backup.gz'; backup.write_bytes(b'fixture')
            descriptor = {'bytes': 7, 'sha256': hashlib.sha256(b'fixture').hexdigest()}
            with patch.object(repair.c, 'read_backup_header') as header:
                with self.assertRaisesRegex(ValueError, 'backup changed'):
                    with repair._held_backup(backup, root, descriptor) as check:
                        self.assertTrue(hasattr(header.call_args.args[0], 'read'))
                        replacement = root / 'replacement'; replacement.write_bytes(b'fixture')
                        replacement.replace(backup)
                        check()

    def test_fifo_rejects_without_waiting_and_wrong_pin_rejects(self):
        from anki_pipeline import study_catalog_display_revision as repair
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); fifo = root / 'fifo'; os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, 'regular file'):
                with repair._held_backup(fifo, root):
                    self.fail('FIFO accepted')
            backup = root / 'backup'; backup.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'backup changed'):
                with repair._held_backup(backup, root, {'bytes': 7, 'sha256': '0' * 64}):
                    self.fail('wrong pin accepted')
