import unittest
from unittest.mock import MagicMock, patch
import sys
from io import StringIO
from sqeeel.stress_engine.engine import StressEngine
from sqeeel.database_modules.base import ExecutionStatus, ExecResult

class TestStressEngineInteractive(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_executor = MagicMock()
        self.mock_db.executor = self.mock_executor
        self.mock_db.run_query.return_value = ExecResult(status=ExecutionStatus.SUCCESS, duration=0.1)
        
        # Mock stop/start/wait
        self.mock_db.stop = MagicMock()
        self.mock_db.start = MagicMock()
        self.mock_db.wait_for_ready = MagicMock()

    def test_run_query_no_cache(self):
        # "Whenever size is given, it should be ran no matter what"
        engine = StressEngine(self.mock_db, [])
        stats = {100: ExecResult(status=ExecutionStatus.SUCCESS, duration=0.2)}
        
        # Mock instantiator
        mock_instantiator = MagicMock()
        mock_instantiator.instantiate.return_value = "SELECT ..."
        
        result = engine._run_query_for_size(mock_instantiator, 100, stats)
        
        # Should call run_query
        self.mock_db.run_query.assert_called_once()
        # Should return new result (mock returns 0.1s, old stats was 0.2s)
        self.assertEqual(result.duration, 0.1)

    def test_extra_queries_on_start(self):
        extra = ["SELECT 1", "SELECT 2"]
        engine = StressEngine(self.mock_db, [], extra_queries=extra)
        
        engine._run_extra_queries()
        self.assertEqual(self.mock_db.run_query.call_count, 2)
        self.mock_db.run_query.assert_any_call("SELECT 1")
        self.mock_db.run_query.assert_any_call("SELECT 2")

    def test_extra_queries_on_recovery(self):
        extra = ["CREATE TABLE foo"]
        engine = StressEngine(self.mock_db, [], extra_queries=extra)
        
        engine._recover_database()
        
        self.mock_db.stop.assert_called_once()
        self.mock_db.start.assert_called_once()
        self.mock_db.wait_for_ready.assert_called_once()
        self.mock_db.run_query.assert_called_once_with("CREATE TABLE foo")

    @patch('sqeeel.stress_engine.engine.prompt')
    def test_interactive_commands_flow(self, mock_prompt):
        # Setup inputs for the interactive loop
        commands = [
            "q SELECT 1",
            "extra CREATE TABLE t1",
            "extra-clean",
            "exit"
        ]
        mock_prompt.side_effect = commands
        
        engine = StressEngine(self.mock_db, [])
        
        # Run explore
        engine.explore()
        
        # 1. "q SELECT 1"
        self.mock_db.run_query.assert_any_call("SELECT 1")
        
        # 2. "extra CREATE TABLE t1"
        self.mock_db.run_query.assert_any_call("CREATE TABLE t1")
        
        # 4. "extra-clean"
        # Since we added one and cleaned it, list should be empty
        self.assertEqual(engine.extra_queries, [])

    @patch('sqeeel.stress_engine.engine.prompt')
    @patch('sqeeel.stress_engine.engine.TemplateInstantiator')
    @patch('sqeeel.stress_engine.engine.parse_template_string')
    def test_explore_size_execution(self, mock_parse, mock_instantiator_cls, mock_prompt):
        mock_prompt.side_effect = ["100", "exit"]
        mock_parse.return_value = ("TPL",)
        
        mock_inst = MagicMock()
        mock_inst.instantiate.return_value = "SELECT SIZE 100"
        mock_instantiator_cls.return_value = mock_inst
        
        engine = StressEngine(self.mock_db, [])
        
        # Pass initial template to enable size command
        engine.explore("TPL")
             
        self.mock_db.run_query.assert_called_with("SELECT SIZE 100")

    @patch('sqeeel.stress_engine.engine.prompt')
    def test_explore_extra_command(self, mock_prompt):
        mock_prompt.side_effect = ["extra Q1", "extra", "exit"]
        engine = StressEngine(self.mock_db, [])
        
        with patch('sys.stdout', new=StringIO()) as fake_out:
            engine.explore()
            output = fake_out.getvalue()
        
        # Check if Q1 was executed
        self.mock_db.run_query.assert_called_with("Q1")
        # Check if it was listed
        self.assertIn("1: Q1", output)
        self.assertIn("Q1", engine.extra_queries)

if __name__ == '__main__':
    unittest.main()
