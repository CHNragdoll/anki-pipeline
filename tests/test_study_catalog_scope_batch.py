"""Atomic classification of existing books, using isolated PostgreSQL only."""
import concurrent.futures
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_library as lib


@unittest.skipUnless(os.environ.get('ANKI_STUDY_TEST_DSN'),
                     'requires explicit isolated PostgreSQL test connection')
class ScopeBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = c.Target(os.environ['ANKI_STUDY_TEST_DSN'], 'testcatalog_' + uuid.uuid4().hex)
        self.schemas = [self.target.schema]
        c.initialize(self.target)
        with c.connect(self.target) as db, c.transaction(db):
            for book in ('one', 'two', 'three', 'other'):
                c.ensure_book(db, book, book, 2027)
        self.changes = {book: {'subject': '英语', 'exam': '考研', 'language': 'en',
                               'topics': ['词汇']} for book in ('one', 'two', 'three')}
        self.expected = {book: None for book in self.changes}

    def tearDown(self):
        with psycopg.connect(self.target.dsn, autocommit=True) as db:
            for schema in self.schemas:
                db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))
        self.temp.cleanup()

    def state(self):
        with c.connect(self.target, readonly=True) as db:
            return lib.scopes(db), db.execute('select count(*) from events').fetchone()[0]

    def apply(self, changes=None, expected=None):
        return lib.classify_many(self.target, self.changes if changes is None else changes,
                                 expected=self.expected if expected is None else expected,
                                 backups=self.root / 'backups')

    def test_one_backup_precedes_all_classifications_and_restores_old_state(self):
        with c.connect(self.target) as db, c.transaction(db):
            lib.set_scope(db, 'other', {'subject': '数学', 'exam': '考研'})
        before = self.state()
        with patch.object(c, 'backup', wraps=c.backup) as backup:
            result = self.apply()
        self.assertEqual(backup.call_count, 1)
        registry, events = self.state()
        self.assertEqual(registry, {**before[0], **self.changes})
        self.assertEqual(events, before[1] + 3)
        restored = c.Target(self.target.dsn, 'testcatalog_' + uuid.uuid4().hex)
        self.schemas.append(restored.schema)
        c.restore(result['backup'], restored)
        with c.connect(restored, readonly=True) as db:
            self.assertEqual(lib.scopes(db), before[0])
            self.assertEqual(db.execute('select count(*) from events').fetchone()[0], before[1])
        self.assertEqual([book['id'] for book in lib.library(self.target, subject='英语')['books']],
                         ['one', 'three', 'two'])

    def test_changed_scope_after_backup_rejects_entire_batch(self):
        original = c.backup
        def intervening(*args):
            path = original(*args)
            with c.connect(self.target) as db, c.transaction(db):
                lib.set_scope(db, 'two', {'subject': '英语', 'exam': 'IELTS'})
            return path
        with patch.object(c, 'backup', side_effect=intervening):
            with self.assertRaisesRegex(ValueError, 'classification changed: two'):
                self.apply()
        self.assertEqual(self.state(), ({'two': {'subject': '英语', 'exam': 'IELTS'}}, 1))

    def test_exception_after_first_write_rolls_back_registry_and_events(self):
        before = self.state()
        original = lib.set_scope
        def fail_second(db, book, scope):
            if book == 'three':
                raise RuntimeError('injected write failure')
            return original(db, book, scope)
        with patch.object(lib, 'set_scope', side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, 'injected'):
                self.apply()
        self.assertEqual(self.state(), before)

    def test_unknown_book_is_checked_before_any_write(self):
        changes = {**self.changes, 'missing': {'subject': '数学'}}
        with self.assertRaisesRegex(ValueError, 'unknown book: missing'):
            self.apply(changes, {book: None for book in changes})
        self.assertEqual(self.state(), ({}, 0))

    def test_invalid_batch_does_not_start_a_backup(self):
        cases = [({}, {}), (self.changes, {}), ({'': {'subject': '数学'}}, {'': None}),
                 ({'one': {'subject': ''}}, {'one': None}),
                 ({'one': {'subject': '数学'}}, {'one': {'unexpected': 'field'}})]
        with patch.object(c, 'backup') as backup:
            for changes, expected in cases:
                with self.subTest(changes=changes, expected=expected), self.assertRaises(ValueError):
                    self.apply(changes, expected)
            backup.assert_not_called()

    def test_caller_mutation_during_backup_cannot_change_applied_scope(self):
        original = c.backup
        def mutate(*args):
            path = original(*args)
            self.changes['one']['subject'] = 'changed by caller'
            self.changes['one']['topics'].append('unexpected')
            self.expected['two'] = {'subject': 'unexpected'}
            return path
        with patch.object(c, 'backup', side_effect=mutate):
            result = self.apply()
        self.assertEqual(result['books']['one']['subject'], '英语')
        self.assertEqual(result['books']['one']['topics'], ['词汇'])
        self.assertIsNone(result['before']['two'])

    def test_concurrent_expected_absence_has_exactly_one_winner(self):
        def action(subject):
            try:
                self.apply({'one': {'subject': subject}}, {'one': None})
                return subject
            except ValueError as error:
                self.assertIn('classification changed', str(error))
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(action, ('英语', '数学')))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(self.state(), ({'one': {'subject': winners[0]}}, 1))

    def test_exact_noop_does_not_add_events_or_remove_unselected_books(self):
        self.apply()
        before = self.state()
        self.apply(expected=self.changes)
        self.assertEqual(self.state(), before)


if __name__ == '__main__':
    unittest.main()
