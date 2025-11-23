import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.getcwd())

from sqeeel.database_modules.docker_db import DockerExecutor, DockerExecResult, ExecutionStatus

class TestDockerExecutorCrash(unittest.TestCase):
    def setUp(self):
        self.executor = DockerExecutor(
            image_name="test-image",
            container_name="test-container",
            client_command=["client"],
            crash_detector=lambda out, err: "Lost connection" in err
        )
        self.executor._container_id = "12345" # Fake container ID

    @patch("subprocess.Popen")
    def test_run_query_exit_137(self, mock_popen):
        # Setup mock process
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 137
        mock_popen.return_value = mock_proc

        # Run query
        result = self.executor.run_query("SELECT 1")

        # Verify
        self.assertEqual(result.status, ExecutionStatus.CRASH)
        # error_message should be empty string (default logic when stderr is empty)
        self.assertEqual(result.error_message, "")

    @patch("subprocess.Popen")
    def test_run_query_container_not_running(self, mock_popen):
        # Setup mock process
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Error response from daemon: container 123 is not running\n")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Run query and expect RuntimeError
        with self.assertRaises(RuntimeError) as cm:
            self.executor.run_query("SELECT 1")
        
        self.assertIn("Critical Docker failure", str(cm.exception))

    @patch("subprocess.Popen")
    def test_run_query_crash_detector(self, mock_popen):
        # Setup mock process
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Lost connection to MySQL server")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Run query
        result = self.executor.run_query("SELECT 1")

        # Verify
        self.assertEqual(result.status, ExecutionStatus.CRASH)

    @patch("subprocess.Popen")
    def test_run_query_normal_error(self, mock_popen):
        # Setup mock process
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Syntax error")
        mock_proc.returncode = 1
        mock_popen.return_value = mock_proc

        # Run query
        result = self.executor.run_query("SELECT 1")

        # Verify
        self.assertEqual(result.status, ExecutionStatus.SUCCESS)
        self.assertEqual(result.exit_code, 1)
        self.assertIsNotNone(result.error_message)
        self.assertIn("Syntax error", result.error_message)

if __name__ == '__main__':
    unittest.main()
