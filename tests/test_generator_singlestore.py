import unittest
import os
import sys

# Add workspace to path
sys.path.append(os.getcwd())

from sqeeel.database_modules.singlestore import SingleStoreModule

class TestQueryGeneratorSingleStore(unittest.TestCase):
    def setUp(self):
        self.singlestore_module = SingleStoreModule()

    def test_name(self):
        self.assertEqual(self.singlestore_module.name, "singlestore")

    def test_grammar_token_rewriter(self):
        # Should inherit from MariaDB
        self.assertEqual(self.singlestore_module._grammar_token_rewriter("AND_AND"), "&&")
        self.assertEqual(self.singlestore_module._grammar_token_rewriter("LE"), "<=")
        
        # Test some specific MariaDB replacements that should also work for SingleStore
        self.assertEqual(self.singlestore_module._grammar_token_rewriter("INT"), "INTEGER")
        self.assertEqual(self.singlestore_module._grammar_token_rewriter("VARCHAR"), "VARCHARACTER")

    def test_template_token_rewriter(self):
        # Should inherit from MariaDB
        self.assertEqual(self.singlestore_module._template_token_rewriter("ident"), "x")
        self.assertEqual(self.singlestore_module._template_token_rewriter("NUM"), "0")

    def test_executor_creation(self):
        class Args:
            db_image = "singlestore/cluster-in-a-box:latest"
            query_timeout = 10.0

        args = Args()
        executor = self.singlestore_module.create_executor(args)
        
        # We know it returns DockerExecutor but static analysis sees Executor
        # casting for clearer test intent or just ignoring since it's dynamic
        self.assertEqual(getattr(executor, "image_name"), args.db_image)
        self.assertEqual(getattr(executor, "container_name"), "sqeeel-test-db-singlestore")
        
        # Check client command has init-command with DB creation/usage
        client_cmd = getattr(executor, "client_command")
        self.assertIn("memsql", client_cmd)
        self.assertTrue(any("--init-command=CREATE DATABASE IF NOT EXISTS testdb; USE testdb" in cmd for cmd in client_cmd))
        
        # Check env has password
        env = getattr(executor, "env")
        self.assertIn("START_AFTER_INIT", env)
        self.assertEqual(env["START_AFTER_INIT"], "Y")
        self.assertEqual(env["MYSQL_PWD"], "mysecretpassword")

    def test_executor_crash_detector(self):
        # Basic check
        self.assertTrue(self.singlestore_module._crash_detector("", "Lost connection to MySQL server"))
        self.assertTrue(self.singlestore_module._crash_detector("", "Can't connect to MySQL server"))
        self.assertTrue(self.singlestore_module._crash_detector("", "ERROR 2013"))
        self.assertFalse(self.singlestore_module._crash_detector("", "Some other error"))

    def test_error_normalization(self):
        # Test basic MariaDB normalization (single quotes)
        err = "ERROR 1064 (42000): You have an error in your SQL syntax; check the manual that corresponds to your MySQL server version for the right syntax to use near 'foo bar' at line 1"
        normalized = self.singlestore_module._normalize_error("", err)
        self.assertIn("near '...'", normalized)

        # Test stack overrun normalization
        stack_err = "ERROR 1119 (HY000) at line 1: Thread stack overrun:  Used: 1287168 of a 1048576 stack.  Specify a bigger stack in the memsql.cnf file by setting the thread-stack engine variable.\n"
        normalized_stack = self.singlestore_module._normalize_error("", stack_err)
        self.assertIn("Used: X of a 1048576 stack", normalized_stack)
        self.assertNotIn("1287168", normalized_stack)

if __name__ == '__main__':
    unittest.main()
