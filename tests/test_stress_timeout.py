import unittest
from unittest.mock import MagicMock, patch
import subprocess
import time
from sqeeel.database_modules.base import ExecResult, ExecutionStatus
from sqeeel.stress_engine.engine import StressEngine
from sqeeel.database_modules.docker_db import DockerExecutor, DockerExecResult

class MockExecutorWithRecovery:
    def __init__(self):
        self.calls = []
        self.start_calls = 0
        self.stop_calls = 0
        self.wait_calls = 0
        self.queries_run = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def wait_for_ready(self):
        self.wait_calls += 1

    def run_query(self, query: str):
        self.calls.append(query)
        self.queries_run += 1
        
        if "hang" in query:
            return ExecResult(status=ExecutionStatus.HANG, error_message="Hang detected")
        if "crash" in query:
            return ExecResult(status=ExecutionStatus.CRASH, error_message="Crash detected")
        if "timeout" in query:
            return ExecResult(status=ExecutionStatus.TIMEOUT, error_message="Timeout")
            
        return ExecResult(status=ExecutionStatus.SUCCESS, error_message=None) # Missing duration but Engine might need it.
        # Engine expects 'duration' on result for logging. ExecResult doesn't have it by default but DockerExecResult does.
        # Engine uses result.duration. I should add it to my MockResult or use DockerExecResult logic.
        # ExecResult is a dataclass. I can add duration dynamically or use a subclass.

@unittest.skip("Integration test requiring docker not suitable here, mocking instead")
class TestDockerReal(unittest.TestCase):
    pass

class TestStressEngineRecovery(unittest.TestCase):
    def test_recovery_on_hang(self):
        executor = MockExecutorWithRecovery()
        # Mock ExecResult to have duration
        def mock_run_query(query):
            executor.calls.append(query)
            res = ExecResult(status=ExecutionStatus.SUCCESS)
            res.duration = 0.1
            
            if "hang" in query:
                res.status = ExecutionStatus.HANG
            elif "crash" in query:
                res.status = ExecutionStatus.CRASH
            elif "timeout" in query:
                res.status = ExecutionStatus.TIMEOUT
            
            return res
        
        executor.run_query = mock_run_query

        # Template generating HANG
        # We need a template that produces a query with "HANG" text for our mock to trigger.
        # But TemplateInstantiator generates "prefix left...".
        # We can set prefix="HANG".
        
        templates = [("", "hang", "", "", "")]
        engine = StressEngine(executor, templates, max_query_size=10, verbose=True)
        
        # Run
        engine.run()
        
        # Check recovery called
        # engine calls recover: stop -> start -> wait
        self.assertGreater(executor.stop_calls, 0)
        self.assertGreater(executor.start_calls, 0)
        self.assertGreater(executor.wait_calls, 0)

class TestDockerExecutorTimeout(unittest.TestCase):
    @patch("subprocess.Popen")
    def test_timeout_kill_fallback(self, mock_popen):
        # Setup mock process
        process_mock = MagicMock()
        process_mock.communicate.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=1)
        process_mock.poll.return_value = None # Still running
        process_mock.returncode = None
        
        mock_popen.return_value = process_mock
        
        executor = DockerExecutor(
            image_name="img", 
            container_name="cont", 
            client_command=["cmd"],
            timeout=1
        )
        executor._container_id = "123"
        
        # Run
        # We mock time.sleep to be fast
        with patch("time.sleep"):
            result = executor.run_query("SELECT 1")
        
        # Assertions
        process_mock.kill.assert_called() # Fallback kill should be called
        self.assertEqual(result.status, ExecutionStatus.HANG) # Because poll() returned None, so it's considered alive (hang)

    @patch("subprocess.Popen")
    def test_timeout_success(self, mock_popen):
        # Case: Timeout happens, kill called, process dies -> TIMEOUT status
        process_mock = MagicMock()
        process_mock.communicate.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=1)
        # First poll (before kill/during check) -> returns 0 (dead)
        process_mock.poll.return_value = 0
        
        mock_popen.return_value = process_mock
        
        executor = DockerExecutor(
            image_name="img", 
            container_name="cont", 
            client_command=["cmd"],
            timeout=1
        )
        executor._container_id = "123"
        
        with patch("time.sleep"):
             result = executor.run_query("SELECT 1")
             
        process_mock.kill.assert_called()
        self.assertEqual(result.status, ExecutionStatus.TIMEOUT)

    @patch("subprocess.Popen")
    def test_timeout_hang(self, mock_popen):
        # Case: Timeout, kill called, process still alive -> HANG
        process_mock = MagicMock()
        process_mock.communicate.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=1)
        process_mock.poll.return_value = None # Always alive
        
        mock_popen.return_value = process_mock
        
        executor = DockerExecutor(
            image_name="img", 
            container_name="cont", 
            client_command=["cmd"],
            timeout=1
        )
        executor._container_id = "123"
        
        with patch("time.sleep"):
             result = executor.run_query("SELECT 1")
             
        self.assertEqual(result.status, ExecutionStatus.HANG)

    @patch("subprocess.Popen")
    def test_custom_alive_check(self, mock_popen):
        # Case: Timeout, custom alive check returns True -> HANG
        process_mock = MagicMock()
        process_mock.communicate.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=1)
        mock_popen.return_value = process_mock
        
        alive_check = MagicMock(return_value=True)
        
        executor = DockerExecutor(
            image_name="img", 
            container_name="cont", 
            client_command=["cmd"],
            timeout=1,
            is_query_alive_callback=alive_check
        )
        executor._container_id = "123"
        
        with patch("time.sleep"):
             result = executor.run_query("SELECT 1")
        
        alive_check.assert_called()
        self.assertEqual(result.status, ExecutionStatus.HANG)

if __name__ == '__main__':
    unittest.main()
