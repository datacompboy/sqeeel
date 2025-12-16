import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os
import time

sys.path.append(os.getcwd())

from sqeeel.database_modules.scylladb import ScyllaExecutor
from sqeeel.database_modules.docker_db import ExecutionStatus

class TestScyllaCrash(unittest.TestCase):
    @patch("subprocess.Popen")
    @patch("subprocess.check_output")
    @patch("time.sleep")
    def test_recover_auto_bounce(self, mock_sleep, mock_check_output, mock_popen):
        # Setup executor
        # We mock check_output to handle network creation if it happens, but __init__ doesn't do it.
        executor = ScyllaExecutor(nodes_count=1, image_name="test-image", container_name="test-scylla")
        executor._container_id = "123"
        
        # Mock run_query results for recover()
        # First call: Fail (still restarting)
        # Second call: Success (auto-bounced)
        
        proc_fail = MagicMock()
        proc_fail.communicate.return_value = ("", "ConnectionRefusedError")
        proc_fail.returncode = 1
        
        proc_success = MagicMock()
        proc_success.communicate.return_value = ("Success", "")
        proc_success.returncode = 0
        
        mock_popen.side_effect = [proc_fail, proc_success]
        
        # Call recover
        with patch.object(executor, 'stop') as mock_stop:
             executor.recover()
             # Should NOT call stop() (full recovery)
             mock_stop.assert_not_called()
             
        # Verify it tried multiple times
        self.assertEqual(mock_popen.call_count, 2)

    @patch("subprocess.Popen")
    @patch("subprocess.check_output")
    @patch("time.sleep")
    @patch("time.time")
    def test_recover_full_restart(self, mock_time, mock_sleep, mock_check_output, mock_popen):
        # Setup executor
        executor = ScyllaExecutor(nodes_count=1, image_name="test-image", container_name="test-scylla")
        executor._container_id = "123"
        
        # Mock time to simulate timeout
        # recover() calls time.time() once for start_time, then in while loop
        # We return 0 (start), then 0.1, ... then >30
        mock_time.side_effect = [0, 1, 35, 100, 100, 100] 
        
        proc_fail = MagicMock()
        proc_fail.communicate.return_value = ("", "ConnectionRefusedError")
        proc_fail.returncode = 1
        
        mock_popen.return_value = proc_fail
        
        # Call recover
        with patch.object(executor, 'stop') as mock_stop:
             with patch.object(executor, 'start') as mock_start:
                 with patch.object(executor, 'wait_for_ready') as mock_wait:
                     executor.recover()
                     
                     # Should call stop/start/wait (full recovery)
                     mock_stop.assert_called_once()
                     mock_start.assert_called_once()
                     mock_wait.assert_called_once()

    def test_crash_detector(self):
        from sqeeel.database_modules.scylladb import ScyllaDBModule
        module = ScyllaDBModule()
        
        self.assertTrue(module._crash_detector("", "ConnectionShutdown"))
        self.assertTrue(module._crash_detector("ConnectionShutdown", ""))
        self.assertFalse(module._crash_detector("", "Syntax Error"))

if __name__ == '__main__':
    unittest.main()
