import unittest
from sqeeel.stress_engine.intervals import add_interval

class TestIntervals(unittest.TestCase):
    def test_add_sequential(self):
        intervals = []
        add_interval(intervals, 10, "Success")
        self.assertEqual(intervals, [{"begin": 10, "end": 10, "effect": "Success"}])
        
        add_interval(intervals, 20, "Success")
        self.assertEqual(intervals, [{"begin": 10, "end": 20, "effect": "Success"}])
        
        add_interval(intervals, 100, "Fail")
        self.assertEqual(intervals, [
            {"begin": 10, "end": 20, "effect": "Success"},
            {"begin": 100, "end": 100, "effect": "Fail"}
        ])

    def test_merge_middle(self):
        intervals = [
            {"begin": 10, "end": 20, "effect": "Success"},
            {"begin": 40, "end": 50, "effect": "Success"}
        ]
        add_interval(intervals, 30, "Success")
        self.assertEqual(intervals, [{"begin": 10, "end": 50, "effect": "Success"}])

    def test_split_middle(self):
        intervals = [{"begin": 10, "end": 50, "effect": "Success"}]
        add_interval(intervals, 30, "Fail")
        self.assertEqual(intervals, [
            {"begin": 10, "end": 10, "effect": "Success"},
            {"begin": 30, "end": 30, "effect": "Fail"},
            {"begin": 50, "end": 50, "effect": "Success"}
        ])

    def test_split_start(self):
        intervals = [{"begin": 10, "end": 50, "effect": "Success"}]
        add_interval(intervals, 10, "Fail")
        self.assertEqual(intervals, [
            {"begin": 10, "end": 10, "effect": "Fail"},
            {"begin": 50, "end": 50, "effect": "Success"}
        ])

    def test_split_end(self):
        intervals = [{"begin": 10, "end": 50, "effect": "Success"}]
        add_interval(intervals, 50, "Fail")
        self.assertEqual(intervals, [
            {"begin": 10, "end": 10, "effect": "Success"},
            {"begin": 50, "end": 50, "effect": "Fail"}
        ])

    def test_point_update(self):
        intervals = [{"begin": 10, "end": 10, "effect": "Success"}]
        add_interval(intervals, 10, "Fail")
        self.assertEqual(intervals, [{"begin": 10, "end": 10, "effect": "Fail"}])
