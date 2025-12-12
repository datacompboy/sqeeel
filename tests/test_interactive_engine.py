import unittest
from unittest.mock import MagicMock, patch
import sys
from io import StringIO
from sqeeel.stress_engine.engine import StressEngine
from sqeeel.database_modules.base import ExecutionStatus, ExecResult
from sqeeel.stress_engine.intervals import add_interval

class TestStressEngineInteractive(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_executor = MagicMock()
        self.mock_db.executor = self.mock_executor
        self.mock_db.run_query.return_value = ExecResult(status=ExecutionStatus.SUCCESS, duration=0.1, exit_code=0)
        
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

    def test_fill_gaps_step(self):
        engine = StressEngine(self.mock_db, [])
        stats = {}
        # Initial intervals: [100, 100] Success, [200, 200] Success. Gap: 101-199.
        intervals = [
            {"begin": 100, "end": 100, "effect": ("success", "")},
            {"begin": 200, "end": 200, "effect": ("success", "")}
        ]
        
        # Mock instantiator
        mock_instantiator = MagicMock()
        mock_instantiator.instantiate.return_value = "SELECT ..."
        
        # Expect middle = 150
        merged, crashed = engine._fill_gaps_step(mock_instantiator, stats, intervals)
        
        self.mock_db.run_query.assert_called()
        # Verify 150 was run
        self.assertIn(150, stats)
        # Verify intervals updated: should have 3 intervals now (since middle 150 success same as neighbors, wait)
        # If middle is success, and neighbors are success, they should merge?
        # 100-100 (S), 150-150 (S), 200-200 (S).
        # Logic: 
        # effect == effect1 (Success == Success) -> new_intervals[-1]["end"] = middle -> 100-150
        # Loop continues. Next interval is 200-200.
        # Check merge with previous (100-150): 150 == 200-1? No.
        # So we get 100-150, 200-200.
        
        self.assertEqual(len(intervals), 2)
        self.assertEqual(intervals[0]["end"], 150)
        self.assertTrue(merged)

    def test_fill_gaps_bounds(self):
        engine = StressEngine(self.mock_db, [])
        stats = {}
        # [100, 100], [200, 200], [300, 300]
        intervals = [
            {"begin": 100, "end": 100, "effect": ("success", "")},
            {"begin": 200, "end": 200, "effect": ("success", "")},
            {"begin": 300, "end": 300, "effect": ("success", "")}
        ]
        mock_instantiator = MagicMock()
        mock_instantiator.instantiate.return_value = "SELECT ..."

        # Run with bounds 200-300. Gap 100-200 should be ignored. Gap 200-300 processed.
        merged, _ = engine._fill_gaps_step(mock_instantiator, stats, intervals, bounds=(200, 300))
        
        # Middle of 200-300 is 250.
        # Middle of 100-200 is 150.
        # We expect run at 250, NOT 150.
        
        calls = [c.args[0] for c in mock_instantiator.instantiate.call_args_list]
        self.assertIn(250, calls)
        self.assertNotIn(150, calls)

    @patch('sqeeel.stress_engine.engine.prompt')
    @patch('sqeeel.stress_engine.engine.TemplateInstantiator')
    @patch('sqeeel.stress_engine.engine.parse_template_string')
    def test_explore_range_command(self, mock_parse, mock_instantiator_cls, mock_prompt):
        # Test range command: 100..200
        mock_prompt.side_effect = ["100..200", "exit"]
        mock_parse.return_value = ("TPL",)
        
        mock_inst = MagicMock()
        mock_inst.instantiate.side_effect = lambda size: f"SELECT {size}"
        mock_instantiator_cls.return_value = mock_inst

        # Mock DB to return success for 100, timeout for 200 to prevent merge
        def side_effect(query):
            if "100" in query:
                return ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0)
            if "200" in query:
                return ExecResult(status=ExecutionStatus.TIMEOUT)
            # Middle 150
            return ExecResult(status=ExecutionStatus.SUCCESS, exit_code=0)
            
        self.mock_db.run_query.side_effect = side_effect

        engine = StressEngine(self.mock_db, [])
        
        engine.explore("TPL")
        
        # Should run 100, 200 (boundaries), then gap fill (150...)
        calls = [c.args[0] for c in mock_inst.instantiate.call_args_list]
        self.assertIn(100, calls)
        self.assertIn(200, calls)
        self.assertIn(150, calls)

if __name__ == '__main__':
    unittest.main()
