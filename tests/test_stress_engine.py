import unittest
from dataclasses import dataclass
from sqeeel.stress_engine.engine import StressEngine

@dataclass
class MockResult:
    exit_code: int
    stderr: str
    duration: float

class MockExecutor:
    def __init__(self):
        self.calls = []

    def start(self):
        pass

    def stop(self):
        pass

    def run_query(self, query: str):
        self.calls.append(query)
        return MockResult(exit_code=0, stderr="", duration=0.1)

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

if __name__ == '__main__':
    unittest.main()
