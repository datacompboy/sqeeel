import unittest
import argparse
from sqeeel.database_modules.postgresql import PostgresModule
from sqeeel.database_modules.docker_db import DockerExecutor

class TestPostgresErrorNormalization(unittest.TestCase):
    def setUp(self):
        self.module = PostgresModule()
        self.args = argparse.Namespace(db_image="postgres:latest", query_timeout=10.0)
        self.executor = self.module.create_executor(self.args)

    def test_executor_has_normalizer(self):
        self.assertIsInstance(self.executor, DockerExecutor)
        self.assertIsNotNone(self.executor.error_normalizer)
        # Check if it's the bound method _normalize_error of the module instance
        self.assertEqual(self.executor.error_normalizer, self.module._normalize_error)

    def test_normalize_multiline_error(self):
        raw_stderr = (
            'ERROR:  SELECT * with no tables specified is not valid\n'
            'LINE 1: ...T ON ( 0 , 0 , 0 , 0 , 0 , 0 , 0 ,'
        )
        expected = 'ERROR:  SELECT * with no tables specified is not valid\n'
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_quotes(self):
        raw_stderr = 'ERROR:  column "param" does not exist\n'
        expected = 'ERROR:  column "..." does not exist\n'
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

    def test_normalize_quotes_multiple(self):
        raw_stderr = 'ERROR:  column "param" and table "foo" do not exist\n'
        expected = 'ERROR:  column "..." and table "..." do not exist\n'
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)
        
    def test_normalize_empty(self):
        normalized = self.module._normalize_error("", "")
        self.assertEqual(normalized, "")

    def test_normalize_no_newline(self):
        raw_stderr = 'ERROR: something bad'
        expected = 'ERROR: something bad'
        normalized = self.module._normalize_error("", raw_stderr)
        self.assertEqual(normalized, expected)

if __name__ == '__main__':
    unittest.main()
