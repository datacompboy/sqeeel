import unittest
from sqeeel.query_generator.grammar_parser import parse_grammar

class TestGrammarParser(unittest.TestCase):
    def test_parse_grammar(self):
        rules = parse_grammar('tests/sample.y')
        expected_rules = {
            'expr': [['term'], ['expr', '+', 'term']],
            'term': [['factor'], ['term', '*', 'factor']],
            'factor': [['(', 'expr', ')'], ['NUMBER']]
        }
        self.assertEqual(rules, expected_rules)

if __name__ == '__main__':
    unittest.main()