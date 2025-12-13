import unittest
from dataclasses import dataclass
from unittest.mock import patch
from sqeeel.stress_engine.engine import StressEngine
from sqeeel.template_instantiator.instantiator import TemplateInstantiator

@dataclass
class MockResult:
    exit_code: int
    stderr: str
    duration: float
    status: str

class MockExecutor:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def run_query(self, query: str):
        self.calls.append(query)
        return MockResult(exit_code=0, stderr="", duration=0.1, status="success")

class TestStressEngine(unittest.TestCase):
    def test_multiple_templates_execution(self):
        # Define 2 different templates
        t1 = ("P1", "L1", "M1", "R1", "S1")
        t2 = ("P2", "L2", "M2", "R2", "S2")
        
        templates = [t1, t2]
        
        executor = MockExecutor()
        engine = StressEngine(executor, templates, 32*1024)  # Use smaller limit for fast testing.
        
        # Run engine
        results = engine.run()
        
        # Check results structure
        self.assertIsInstance(results, dict)
        self.assertEqual(len(results), 2)
        self.assertIn(str(t1), results)
        self.assertIn(str(t2), results)
        
        # Check return values structure (intervals, stats)
        for template_str, (intervals, stats) in results.items():
            self.assertIsInstance(intervals, list)
            self.assertIsInstance(stats, dict)
            # Check that stats contain results for checked sizes
            self.assertGreater(len(stats), 0)

        # Analyze calls
        t1_calls = [c for c in executor.calls if "P1" in c]
        t2_calls = [c for c in executor.calls if "P2" in c]
        
        # We expect calls for both
        self.assertGreater(len(t1_calls), 0, "T1 should have been executed")
        self.assertGreater(len(t2_calls), 0, "T2 should have been executed")
        
        # Check that we have unique stats per template
        stats1 = results[str(t1)][1]
        stats2 = results[str(t2)][1]
        
        # They should not be the same object
        self.assertIsNot(stats1, stats2)

    def test_discover_intervals(self):
        t1 = ("P1", "L1", "M1", "R1", "S1")
        executor = MockExecutor()
        engine = StressEngine(executor, [t1], 100) # Small limit
        
        instantiator = TemplateInstantiator(t1)
        stats = {}
        intervals = []
        
        engine._discover_intervals(instantiator, stats, intervals)
        
        # Check that we have intervals
        self.assertGreater(len(intervals), 0)
        # Check that at least one success interval is recorded
        effects = [i['effect'][0] for i in intervals]
        self.assertIn("success", effects)

    @patch('sqeeel.stress_engine.engine.prompt', side_effect=['init', 'quit'])
    def test_explore_mode_init(self, mock_prompt):
        t1 = ("P1", "L1", "M1", "R1", "S1")
        executor = MockExecutor()
        # engine = StressEngine(executor, [t1], 100)
        # explore mode doesn't use self.templates usually, but we can set it via command
        # or pass initial string
        engine = StressEngine(executor, [], 100)
        
        template_str = "('P1', 'L1', 'M1', 'R1', 'S1')"
        
        # Run explore with initial template
        # Mocking input to type "init" then "quit"
        engine.explore(template_str)
        
        # We can't easily check internal state of local variables in explore
        # But if it doesn't crash, it's good sign.
        # And we can check executor calls
        self.assertGreater(len(executor.calls), 0)

if __name__ == '__main__':
    unittest.main()
