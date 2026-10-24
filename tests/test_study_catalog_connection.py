import unittest
from unittest.mock import MagicMock, patch

from anki_pipeline import study_catalog as c


class ConnectionTimeoutTests(unittest.TestCase):
    def test_explicit_connection_timeout_is_respected_and_default_remains_bounded(self):
        for dsn,expected in [('dbname=example', '10'), ('dbname=example connect_timeout=60', '60')]:
            db=MagicMock()
            with self.subTest(dsn=dsn),patch.object(c.psycopg,'connect',return_value=db) as connect,patch.object(c,'validate'):
                with c.connect(c.Target(dsn,'study_catalog'),readonly=True) as actual:self.assertIs(actual,db)
                self.assertEqual(connect.call_args.kwargs['connect_timeout'],expected)
                self.assertTrue(connect.call_args.kwargs['autocommit'])
                db.close.assert_called_once()

    def test_initialization_uses_the_same_explicit_timeout_and_default(self):
        for dsn,expected in [('dbname=example', '10'), ('dbname=example connect_timeout=60', '60')]:
            db=MagicMock()
            selected=c.Target(dsn,'study_catalog')
            with self.subTest(dsn=dsn),patch.object(c.psycopg,'connect',return_value=db) as connect,patch.object(c,'_initialize_connection') as initialize:
                c.initialize(selected)
                self.assertEqual(connect.call_args.kwargs['connect_timeout'],expected)
                self.assertTrue(connect.call_args.kwargs['autocommit'])
                initialize.assert_called_once_with(db.__enter__.return_value,selected)


if __name__=='__main__':unittest.main()
