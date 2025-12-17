import unittest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.append(os.getcwd())

from sqeeel.database_modules.scylladb import ScyllaExecutor
from sqeeel.database_modules.base import ExecResult, ExecutionStatus

class TestScyllaHang(unittest.TestCase):
    @patch("subprocess.check_call")  # prevent network creation if any
    def test_entry_node_stuck(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to return NoHostAvailable + OperationTimedOut
        mock_result = ExecResult(status=ExecutionStatus.ERROR, exit_code=1)
        mock_result.stderr = "cassandra.cluster.NoHostAvailable: ('Unable to connect to any servers', {'172.20.0.4:9042': OperationTimedOut('errors=Timed out creating connection (5 seconds), last_host=None')})"
        
        executor.run_query = MagicMock(return_value=mock_result)
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "entry-stuck")
        self.assertEqual(executor._detected_hang, "entry-stuck")
        # Verify it called run_query with correct query
        executor.run_query.assert_called_with("SELECT * FROM system_traces.sessions BYPASS CACHE")

    @patch("subprocess.check_call")
    def test_cluster_node_stuck(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to return ReadTimeout
        mock_result = ExecResult(status=ExecutionStatus.ERROR, exit_code=1)
        mock_result.stderr = "cassandra.ReadTimeout: Error from server: code=1200 [Coordinator node timed out waiting for replica nodes' responses]"
        
        executor.run_query = MagicMock(return_value=mock_result)
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "cluster-stuck")
        self.assertEqual(executor._detected_hang, "cluster-stuck")
        executor.run_query.assert_called_with("SELECT * FROM system_traces.sessions BYPASS CACHE")

    @patch("subprocess.check_call")
    def test_check_timeout(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to return TIMEOUT status
        mock_result = ExecResult(status=ExecutionStatus.TIMEOUT, exit_code=None, stderr="")
        
        executor.run_query = MagicMock(return_value=mock_result)
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "check-timeout")
        self.assertEqual(executor._detected_hang, "check-timeout")
        executor.run_query.assert_called_with("SELECT * FROM system_traces.sessions BYPASS CACHE")

    @patch("subprocess.check_call")
    def test_check_hang(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to return HANG status
        mock_result = ExecResult(status=ExecutionStatus.HANG, exit_code=None, stderr="")
        
        executor.run_query = MagicMock(return_value=mock_result)
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "check-hang")
        self.assertEqual(executor._detected_hang, "check-hang")
        executor.run_query.assert_called_with("SELECT * FROM system_traces.sessions BYPASS CACHE")

    @patch("subprocess.check_call")
    def test_node_refused(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to return ConnectionRefusedError
        mock_result = ExecResult(status=ExecutionStatus.ERROR, exit_code=1)
        mock_result.stderr = "cassandra.cluster.NoHostAvailable: ('Unable to connect to any servers', {'172.19.0.2:9042': ConnectionRefusedError(111, \"Tried connecting to [('172.19.0.2', 9042)]. Last error: Connection refused\")})"
        
        executor.run_query = MagicMock(return_value=mock_result)
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "node-refused")
        self.assertEqual(executor._detected_hang, "node-refused")
        executor.run_query.assert_called_with("SELECT * FROM system_traces.sessions BYPASS CACHE")

    @patch("subprocess.check_call")
    def test_node_dead(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # 1. Primary check succeeds
        mock_result_ok = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="None\n")
        
        # 2. Secondary check fails (returns row)
        mock_result_dead = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="Row(up=False)\n")
        
        executor.run_query = MagicMock(side_effect=[mock_result_ok, mock_result_dead])
        
        # Call _is_query_alive
        result = executor._is_query_alive(executor)
        
        self.assertEqual(result, "node-dead")
        self.assertEqual(executor._detected_hang, "node-dead")
        
        # Verify calls
        self.assertEqual(executor.run_query.call_count, 2)
        executor.run_query.assert_any_call("SELECT * FROM system_traces.sessions BYPASS CACHE")
        executor.run_query.assert_any_call("SELECT up FROM system.cluster_status WHERE up = False ALLOW FILTERING BYPASS CACHE USING TIMEOUT 1s")

    @patch("subprocess.check_call")
    def test_latching(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # 1. Fail first
        mock_result_fail = ExecResult(status=ExecutionStatus.TIMEOUT, exit_code=None, stderr="")
        mock_query_1 = MagicMock(return_value=mock_result_fail)
        executor.run_query = mock_query_1
        
        result1 = executor._is_query_alive(executor)
        self.assertEqual(result1, "check-timeout")
        mock_query_1.assert_called_once()
        
        # 2. Succeed second (simulating transient issue or whatever)
        mock_result_ok = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="None\n")
        # And secondary check succeed
        mock_result_dead_ok = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="None\n")
        
        mock_query_2 = MagicMock(side_effect=[mock_result_ok, mock_result_dead_ok])
        executor.run_query = mock_query_2
        
        result2 = executor._is_query_alive(executor)
        # Should return cached result
        self.assertEqual(result2, "check-timeout")
        
        # Verify run_query was NOT called second time
        mock_query_2.assert_not_called()

    @patch("subprocess.check_call")
    def test_start_resets_latch(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        executor._detected_hang = "some-hang"
        
        # Mock start internals
        with patch.object(executor, 'nodes', []), \
             patch('subprocess.check_output', return_value=b"123"), \
             patch('time.sleep'):
             executor.start()
             
        self.assertIsNone(executor._detected_hang)

    @patch("subprocess.check_call")
    def test_not_stuck(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        
        # Mock run_query to success
        mock_result = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="None\n")
        # Secondary check success
        mock_result_dead = ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0, stderr="", stdout="None\n")
        
        executor.run_query = MagicMock(side_effect=[mock_result, mock_result_dead])
        
        result = executor._is_query_alive(executor)
        
        self.assertIsNone(result)

    @patch("subprocess.check_call")
    def test_recursion_prevention(self, mock_check_call):
        executor = ScyllaExecutor(
            nodes_count=1, 
            image_name="img", 
            container_name="cont",
            test_query="SELECT * FROM system_traces.sessions BYPASS CACHE"
        )
        executor._in_check = True
        
        result = executor._is_query_alive(executor)
        
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
