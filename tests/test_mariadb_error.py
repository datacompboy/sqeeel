import unittest
import sys
import os

sys.path.append(os.getcwd())

from sqeeel.database_modules.mariadb import MariaDBModule

class TestMariaDBErrorExtraction(unittest.TestCase):
    def test_normalize_error(self):
        module = MariaDBModule()
        
        # Simulating output with --skip-print-query-on-error (no query echo)
        stderr_input = "ERROR 1064 (42000) at line 1: You have an error in your SQL syntax; check the manual that corresponds to your MariaDB server version for the right syntax to use near 'EQUAL x DIV x )' at line 1\n"
        
        expected_output = "ERROR 1064 (42000) at line 1: You have an error in your SQL syntax; check the manual that corresponds to your MariaDB server version for the right syntax to use near '...' at line 1\n"
        
        actual_output = module._normalize_error("", stderr_input)
        
        self.assertEqual(actual_output, expected_output)

if __name__ == '__main__':
    unittest.main()
